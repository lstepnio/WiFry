"""STB_AUTOMATION — Smart crawl engine with map-aware discovery.

Four-phase strategy:
  A. Map analysis — find unexplored areas from existing data
  B. Directed navigation — navigate TO targets using pathfinding
  C. Smart sibling sweep — use map predictions to skip AI calls
  D. Prioritized enter — menu items first, content last

Works with single-activity STBs by tracking focused_element changes.
Uses vision_map.predict() to avoid expensive AI calls (~6s each)
when the map already knows what a transition will produce.
"""

import asyncio
import logging
import time
from typing import Optional, Set

from . import action_executor, fingerprint as fp, screen_reader, vision_cache, vision_map
from .logcat_monitor import get_monitor
from .models import CrawlConfig, CrawlStatus, VisionAnalysis

logger = logging.getLogger("wifry.stb_automation.crawl_engine")

_crawl_status = CrawlStatus()
_crawl_task: Optional[asyncio.Task] = None
_crawl_cancel = asyncio.Event()

SAVE_INTERVAL = 10


def get_status() -> CrawlStatus:
    return _crawl_status.model_copy()


async def start_crawl(config: CrawlConfig) -> CrawlStatus:
    global _crawl_task, _crawl_status
    if _crawl_status.state == "running":
        return _crawl_status
    _crawl_status = CrawlStatus(state="running")
    _crawl_cancel.clear()
    _crawl_task = asyncio.create_task(_crawl_loop(config))
    logger.info("[STB_AUTOMATION] Crawl started: serial=%s depth=%d transitions=%d vision=%s predictions=%s",
                config.serial, config.max_depth, config.max_transitions,
                config.enable_vision_fallback, config.use_map_predictions)
    return _crawl_status


async def stop_crawl() -> CrawlStatus:
    global _crawl_status
    if _crawl_status.state != "running":
        return _crawl_status
    _crawl_cancel.set()
    if _crawl_task and not _crawl_task.done():
        try:
            await asyncio.wait_for(_crawl_task, timeout=5.0)
        except asyncio.TimeoutError:
            _crawl_task.cancel()
    _crawl_status.state = "completed"
    return _crawl_status


async def crawl_step(config: CrawlConfig) -> dict:
    """Execute a single exploration step (manual mode)."""
    monitor = get_monitor()
    state, _ = await screen_reader.read_screen_state(
        config.serial, include_hierarchy=False,
        recent_events=monitor.get_events(5) if monitor.is_active else [],
    )
    screen_key = f"{state.package}/{state.activity}"
    focused = await _get_focused_label(config.serial, config.enable_vision_fallback)
    if focused:
        vision_map.set_last_focused(screen_key, focused)

    tried = {e.action for e in vision_map.get_screen_entries(screen_key)
             if e.from_element == focused}
    action = next((a for a in config.explore_actions if a not in tried), None)

    if not action:
        vision_map.save()
        return {"status": "exhausted", "screen_key": screen_key, "focused": focused}

    result = await action_executor.navigate(
        serial=config.serial, action=action,
        settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
    )
    post_key = f"{result.post_state.package}/{result.post_state.activity}"
    post_focused = await _get_focused_label(config.serial, config.enable_vision_fallback)

    vision_map.observe_transition(
        screen_key=screen_key, action=action,
        from_element=focused or screen_key,
        to_element=post_focused or post_key,
        to_screen_key=post_key if post_key != screen_key else "",
        transition_ms=result.settle_ms, source="crawl",
    )
    if post_focused:
        vision_map.set_last_focused(post_key if post_key != screen_key else screen_key, post_focused)
    vision_map.save()

    return {
        "status": "stepped", "action": action,
        "from_screen": screen_key, "to_screen": post_key,
        "from_focused": focused, "to_focused": post_focused,
        "settle_ms": round(result.settle_ms, 1),
    }


# ── Vision helper ──────────────────────────────────────────────────


async def _get_focused_label(serial: str, enable_vision: bool) -> str:
    if not enable_vision:
        return ""
    try:
        from ..video_capture import streamer, analyzer
        if not streamer.is_running():
            return ""
        frame = streamer.get_latest_frame()
        if frame is None:
            return ""

        cache_key = fp.frame_hash(frame)
        cached = vision_cache.get(cache_key)
        if cached:
            vision_map.update_fast_path(cached)
            return cached.focused_label or ""

        result = await analyzer.analyze_frame(frame_jpeg=frame)
        vision_obj = VisionAnalysis(
            screen_type=result.screen_type or "unknown",
            screen_title=result.screen_title or "",
            focused_label=result.focused_element.label if result.focused_element else "",
            focused_position=result.focused_element.position if result.focused_element else "",
            focused_confidence=result.focused_element.confidence if result.focused_element else "low",
            navigation_path=result.navigation_path or [],
            visible_text=result.visible_text_summary or "",
            raw_description=result.raw_description or "",
            provider=result.provider or "",
            tokens_used=result.tokens_used or 0,
        )
        if cache_key:
            vision_cache.put(cache_key, vision_obj)
        vision_map.update_fast_path(vision_obj)
        return vision_obj.focused_label or ""
    except ImportError:
        return ""
    except Exception as e:
        logger.warning("[STB_AUTOMATION] Crawl vision failed: %s", e)
        return ""


# ── Smart crawl loop ───────────────────────────────────────────────


# Queue item: (priority, screen_key, focused_element, depth)
_QueueItem = tuple[int, str, str, int]


async def _crawl_loop(config: CrawlConfig) -> None:
    global _crawl_status
    monitor = get_monitor()
    t_start = time.monotonic()
    transitions = 0
    skipped = 0
    ai_saved = 0
    use_vision = config.enable_vision_fallback

    try:
        # ── Phase A: Analyze existing map ──────────────────────
        _crawl_status.current_phase = "analyzing_map"

        explored: Set[tuple[str, str, str]] = set()
        for screen_key in list(vision_map._transitions.keys()):
            for (action, from_el) in vision_map._transitions[screen_key]:
                explored.add((screen_key, from_el, action))

        logger.info("[STB_AUTOMATION] Phase A: %d existing transitions across %d screens",
                     len(explored), len(vision_map._screens))

        # Get initial state
        state, _ = await screen_reader.read_screen_state(
            config.serial, include_hierarchy=False,
            recent_events=monitor.get_events(5) if monitor.is_active else [],
        )
        root_key = f"{state.package}/{state.activity}"
        root_focused = await _get_focused_label(config.serial, use_vision)
        if root_focused:
            vision_map.set_last_focused(root_key, root_focused)

        logger.info("[STB_AUTOMATION] Root: screen=%s focused='%s'", root_key, root_focused)

        # Build frontier of unexplored targets from known elements
        frontier = _build_frontier(explored, config.explore_actions)
        _crawl_status.unexplored_targets = len(frontier)

        # Priority queue: lower number = explore first
        queue: list[_QueueItem] = []
        queue.append((0, root_key, root_focused, 0))

        # Add frontier menu items with high priority
        seen_queue: Set[tuple[str, str]] = {(root_key, root_focused)}
        for (sk, elem, _action) in frontier:
            if (sk, elem) not in seen_queue:
                seen_queue.add((sk, elem))
                priority = _element_priority(elem, config)
                queue.append((priority, sk, elem, 1 if sk != root_key else 0))

        # Sort by priority
        queue.sort(key=lambda x: x[0])

        _update_status(_crawl_status, transitions, skipped, ai_saved, frontier, t_start)

        # ── Main crawl loop ────────────────────────────────────
        while queue and not _crawl_cancel.is_set():
            _priority, current_key, current_focused, depth = queue.pop(0)

            if depth >= config.max_depth or transitions >= config.max_transitions:
                continue

            # ── Phase B: Navigate to target ────────────────────
            _crawl_status.current_phase = "navigating"
            _crawl_status.current_node_id = f"{current_key}::{current_focused}"
            _crawl_status.current_action = f"navigating to '{current_focused}'"

            actual_key, actual_focused = await _ensure_at(
                config, current_key, current_focused, monitor,
            )
            if actual_key != current_key:
                logger.warning("[STB_AUTOMATION] Could not reach %s, skipping", current_key)
                continue

            # ── Phase C: Sibling sweep (directional) ───────────
            _crawl_status.current_phase = "exploring"
            directional = [a for a in config.explore_actions if a not in ("enter", "back")]

            for action in directional:
                if _crawl_cancel.is_set() or transitions >= config.max_transitions:
                    break

                from_el = current_focused or current_key
                explore_key = (current_key, from_el, action)
                if explore_key in explored:
                    skipped += 1
                    continue
                explored.add(explore_key)

                # Try map prediction first
                post_focused = None
                used_prediction = False
                if config.use_map_predictions:
                    prediction = vision_map.predict(
                        current_key, action, from_el,
                        min_confidence=config.prediction_confidence,
                        min_observations=1,
                    )
                    if prediction:
                        post_focused = prediction.to_element
                        used_prediction = True
                        ai_saved += 1

                # Execute action
                _crawl_status.current_action = f"{action} on '{from_el}'"
                result = await action_executor.navigate(
                    serial=config.serial, action=action,
                    settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
                )
                transitions += 1

                post_key = f"{result.post_state.package}/{result.post_state.activity}"

                # Get post-focused: use prediction or AI
                if not used_prediction and use_vision:
                    post_focused = await _get_focused_label(config.serial, True)

                # Record
                vision_map.observe_transition(
                    screen_key=current_key, action=action,
                    from_element=from_el,
                    to_element=post_focused or post_key,
                    to_screen_key=post_key if post_key != current_key else "",
                    transition_ms=result.settle_ms, source="crawl",
                )
                if post_focused:
                    target = post_key if post_key != current_key else current_key
                    vision_map.set_last_focused(target, post_focused)
                    current_focused = post_focused

                _update_status(_crawl_status, transitions, skipped, ai_saved, frontier, t_start)

            # ── Phase D: Enter on current element ──────────────
            if "enter" in config.explore_actions and not _crawl_cancel.is_set():
                from_el = current_focused or current_key
                enter_key = (current_key, from_el, "enter")

                if enter_key not in explored and transitions < config.max_transitions:
                    # Skip content tiles if menu items are still unexplored
                    if config.prioritize_menu and _is_content(from_el, config):
                        if _has_unexplored_menu(current_key, explored, config):
                            logger.info("[STB_AUTOMATION] Deferring enter on content '%s'", from_el)
                            queue.append((10, current_key, from_el, depth))
                            continue

                    explored.add(enter_key)
                    _crawl_status.current_phase = "entering"
                    _crawl_status.current_action = f"enter on '{from_el}'"

                    result = await action_executor.navigate(
                        serial=config.serial, action="enter",
                        settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
                    )
                    transitions += 1

                    post_key = f"{result.post_state.package}/{result.post_state.activity}"
                    post_focused = ""
                    if use_vision:
                        post_focused = await _get_focused_label(config.serial, True)

                    vision_map.observe_transition(
                        screen_key=current_key, action="enter",
                        from_element=from_el,
                        to_element=post_focused or post_key,
                        to_screen_key=post_key if post_key != current_key else "",
                        transition_ms=result.settle_ms, source="crawl",
                    )

                    # Detect if we entered something worth exploring
                    state_changed = (
                        post_key != current_key
                        or (post_focused and post_focused != from_el)
                    )

                    if state_changed:
                        # Check if it's a player (skip deeper)
                        if _is_content(post_focused or "", config):
                            logger.info("[STB_AUTOMATION] Hit content screen, backing out")
                        else:
                            # Queue for deeper exploration
                            priority = _element_priority(post_focused or "", config)
                            queue.append((priority, post_key, post_focused, depth + 1))
                            queue.sort(key=lambda x: x[0])
                            logger.info("[STB_AUTOMATION] Queued depth=%d: '%s' on %s",
                                       depth + 1, post_focused, post_key.split("/")[-1])

                    # Navigate back
                    _crawl_status.current_phase = "returning"
                    back_result = await action_executor.navigate(
                        serial=config.serial, action="back",
                        settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
                    )
                    transitions += 1

                    back_key = f"{back_result.post_state.package}/{back_result.post_state.activity}"
                    back_focused = ""
                    if use_vision:
                        back_focused = await _get_focused_label(config.serial, True)

                    vision_map.observe_transition(
                        screen_key=post_key, action="back",
                        from_element=post_focused or post_key,
                        to_element=back_focused or back_key,
                        to_screen_key=back_key if back_key != post_key else "",
                        transition_ms=back_result.settle_ms, source="crawl",
                    )
                    if back_focused:
                        vision_map.set_last_focused(back_key, back_focused)

                    _update_status(_crawl_status, transitions, skipped, ai_saved, frontier, t_start)

            if transitions % SAVE_INTERVAL == 0:
                vision_map.save()

        _crawl_status.state = "completed"
        _crawl_status.current_phase = ""
        _crawl_status.current_action = ""

    except asyncio.CancelledError:
        _crawl_status.state = "completed"
    except Exception as e:
        logger.exception("[STB_AUTOMATION] Crawl error")
        _crawl_status.state = "error"
        _crawl_status.error = str(e)
    finally:
        vision_map.save()
        vision_cache.save()
        elapsed = round(time.monotonic() - t_start, 1)
        logger.info("[STB_AUTOMATION] Crawl finished: %d screens, %d transitions, "
                     "%d skipped, %d AI saved, %.1fs",
                     len(vision_map._screens), transitions, skipped, ai_saved, elapsed)


# ── Helpers ────────────────────────────────────────────────────────


def _build_frontier(
    explored: Set[tuple[str, str, str]],
    actions: list[str],
) -> list[tuple[str, str, str]]:
    """Find unexplored (screen_key, element, action) triples from known elements."""
    frontier = []
    for screen_key in list(vision_map._transitions.keys()):
        elements: Set[str] = set()
        for (action, from_el), entry in vision_map._transitions[screen_key].items():
            elements.add(from_el)
            if entry.to_element:
                elements.add(entry.to_element)
        for element in elements:
            for action in actions:
                if (screen_key, element, action) not in explored:
                    frontier.append((screen_key, element, action))
    return frontier


def _element_priority(element: str, config: CrawlConfig) -> int:
    """Lower = higher priority. Menu=0, unknown=5, content=10."""
    if not element:
        return 5
    el_lower = element.lower()
    for kw in config.menu_keywords:
        if kw in el_lower:
            return 0
    for kw in config.content_keywords:
        if kw in el_lower:
            return 10
    return 5


def _is_content(element: str, config: CrawlConfig) -> bool:
    if not element:
        return False
    el_lower = element.lower()
    for kw in config.content_keywords:
        if kw in el_lower:
            return True
    if len(element) > 25 and not any(kw in el_lower for kw in config.menu_keywords):
        return True
    return False


def _has_unexplored_menu(screen_key: str, explored: set, config: CrawlConfig) -> bool:
    entries = vision_map.get_screen_entries(screen_key)
    known = {e.from_element for e in entries} | {e.to_element for e in entries}
    for el in known:
        if _element_priority(el, config) == 0:
            if (screen_key, el, "enter") not in explored:
                return True
    return False


def _update_status(
    status: CrawlStatus,
    transitions: int,
    skipped: int,
    ai_saved: int,
    frontier: list,
    t_start: float,
) -> None:
    elapsed = time.monotonic() - t_start
    status.transitions_executed = transitions
    status.transitions_skipped = skipped
    status.ai_calls_saved = ai_saved
    status.nodes_discovered = len(vision_map._screens)
    status.unexplored_targets = len(frontier) - skipped if frontier else 0
    status.elapsed_secs = round(elapsed, 1)
    if transitions > 0:
        status.avg_action_ms = round((elapsed * 1000) / transitions, 0)


async def _ensure_at(
    config: CrawlConfig,
    target_key: str,
    target_focused: str,
    monitor,
) -> tuple[str, str]:
    """Ensure we're at the right screen+element."""
    state, _ = await screen_reader.read_screen_state(
        config.serial, include_hierarchy=False,
    )
    actual_key = f"{state.package}/{state.activity}"

    if actual_key != target_key:
        recovered = await _navigate_to(config, target_key, monitor)
        if not recovered:
            return actual_key, ""
        actual_key = target_key

    actual_focused = vision_map.get_last_focused(actual_key) or ""

    # Try to navigate to specific element within screen
    if target_focused and actual_focused and actual_focused != target_focused:
        path = vision_map.find_element_path(actual_key, actual_focused, target_focused)
        if path and len(path) <= 10:
            for action in path:
                await action_executor.navigate(
                    serial=config.serial, action=action,
                    settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
                )
            actual_focused = target_focused
            vision_map.set_last_focused(actual_key, actual_focused)

    return actual_key, actual_focused


async def _navigate_to(config: CrawlConfig, target_key: str, monitor) -> bool:
    home_result = await action_executor.navigate(
        serial=config.serial, action="home",
        settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
    )
    home_key = f"{home_result.post_state.package}/{home_result.post_state.activity}"
    if home_key == target_key:
        return True
    path = vision_map.find_screen_path(home_key, target_key)
    if path is None:
        return False
    for action, _ in path:
        result = await action_executor.navigate(
            serial=config.serial, action=action,
            settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
        )
        if f"{result.post_state.package}/{result.post_state.activity}" == target_key:
            return True
    return False
