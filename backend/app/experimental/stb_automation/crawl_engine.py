"""STB_AUTOMATION — BFS crawl engine with AI-guided discovery.

Explores the STB UI by sending key presses and recording transitions
into the unified vision map.  When HDMI vision is available, uses AI
to identify focused elements for rich element-level mapping.

AI strategy hints: the vision analysis identifies screen types that
need different crawl strategies (list, grid, guide, player, settings).

The engine runs as an async background task.
"""

import asyncio
import logging
from typing import Optional, Set

from . import action_executor, fingerprint as fp, screen_reader, vision_cache, vision_map
from .logcat_monitor import get_monitor
from .models import CrawlConfig, CrawlStatus, ScreenState, VisionAnalysis

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
    logger.info("[STB_AUTOMATION] Crawl started: serial=%s max_depth=%d vision=%s",
                config.serial, config.max_depth, config.enable_vision_fallback)
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
    logger.info("[STB_AUTOMATION] Crawl stopped: %d nodes, %d transitions",
                _crawl_status.nodes_discovered, _crawl_status.transitions_executed)
    return _crawl_status


async def crawl_step(config: CrawlConfig) -> dict:
    """Execute a single exploration step (manual mode)."""
    monitor = get_monitor()
    state, _ = await screen_reader.read_screen_state(
        config.serial,
        recent_events=monitor.get_events(5) if monitor.is_active else [],
        include_hierarchy=False,
    )
    screen_key = f"{state.package}/{state.activity}"

    tried = _tried_actions(screen_key)
    action = None
    for a in config.explore_actions:
        if a not in tried:
            action = a
            break

    if action is None:
        vision_map.save()
        return {"status": "exhausted", "screen_key": screen_key,
                "message": "All actions already tried from this screen"}

    # Get pre-navigate focused label via vision
    pre_focused = await _get_focused_label(config.serial, config.enable_vision_fallback)
    if pre_focused:
        vision_map.set_last_focused(screen_key, pre_focused)

    result = await action_executor.navigate(
        serial=config.serial, action=action,
        settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
    )
    post_key = f"{result.post_state.package}/{result.post_state.activity}"

    # Get post-navigate focused label
    post_focused = await _get_focused_label(config.serial, config.enable_vision_fallback)

    vision_map.observe_transition(
        screen_key=screen_key, action=action,
        from_element=pre_focused or screen_key,
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
        "from_focused": pre_focused or "", "to_focused": post_focused or "",
        "transitioned": result.transitioned,
        "settle_ms": round(result.settle_ms, 1),
    }


# ── Vision helper ──────────────────────────────────────────────────


async def _get_focused_label(serial: str, enable_vision: bool) -> str:
    """Get the current focused element label via vision cache or AI.

    Returns empty string if vision is disabled or unavailable.
    """
    if not enable_vision:
        return ""

    try:
        from ..video_capture import streamer, analyzer

        if not streamer.is_running():
            return ""

        frame = streamer.get_latest_frame()
        if frame is None:
            return ""

        # Check vision cache first
        from . import fingerprint as fp
        cache_key = fp.frame_hash(frame)
        cached = vision_cache.get(cache_key)
        if cached:
            vision_map.update_fast_path(cached)
            return cached.focused_label or ""

        # Cache miss — call AI
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

        # Store in vision cache for reuse
        if cache_key:
            vision_cache.put(cache_key, vision_obj)
        vision_map.update_fast_path(vision_obj)

        logger.debug("[STB_AUTOMATION] Crawl vision: %s focused=%s screen=%s",
                     result.provider, vision_obj.focused_label, vision_obj.screen_type)

        return vision_obj.focused_label or ""

    except ImportError:
        return ""
    except Exception as e:
        logger.warning("[STB_AUTOMATION] Crawl vision failed: %s", e)
        return ""


# ── BFS crawl loop ─────────────────────────────────────────────────


async def _crawl_loop(config: CrawlConfig) -> None:
    global _crawl_status
    monitor = get_monitor()
    transitions = 0
    use_vision = config.enable_vision_fallback

    try:
        # Read initial state + vision
        state, _ = await screen_reader.read_screen_state(
            config.serial,
            recent_events=monitor.get_events(5) if monitor.is_active else [],
            include_hierarchy=False,
        )
        root_key = f"{state.package}/{state.activity}"

        # Get initial focused label
        initial_focused = await _get_focused_label(config.serial, use_vision)
        if initial_focused:
            vision_map.set_last_focused(root_key, initial_focused)

        _crawl_status.nodes_discovered = len(vision_map._screens) or 1
        _crawl_status.current_node_id = root_key

        queue: list[tuple[str, int, list[str]]] = [(root_key, 0, [])]
        visited_from: Set[tuple[str, str]] = set()

        while queue and not _crawl_cancel.is_set():
            current_key, depth, path = queue.pop(0)

            if depth >= config.max_depth or transitions >= config.max_transitions:
                continue

            # Verify location
            actual_state, _ = await screen_reader.read_screen_state(
                config.serial, include_hierarchy=False,
            )
            actual_key = f"{actual_state.package}/{actual_state.activity}"

            if actual_key != current_key:
                recovered = await _navigate_to(config, current_key, monitor)
                if not recovered:
                    logger.warning("[STB_AUTOMATION] Could not reach %s, skipping", current_key)
                    continue

            _crawl_status.current_node_id = current_key

            for action in config.explore_actions:
                if _crawl_cancel.is_set() or transitions >= config.max_transitions:
                    break
                if (current_key, action) in visited_from:
                    continue

                visited_from.add((current_key, action))

                # Pre-navigate: get current focused label
                pre_focused = vision_map.get_last_focused(current_key)
                if not pre_focused and use_vision:
                    pre_focused = await _get_focused_label(config.serial, use_vision)
                    if pre_focused:
                        vision_map.set_last_focused(current_key, pre_focused)

                result = await action_executor.navigate(
                    serial=config.serial, action=action,
                    settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
                )
                transitions += 1
                _crawl_status.transitions_executed = transitions

                post_key = f"{result.post_state.package}/{result.post_state.activity}"

                # Post-navigate: get new focused label
                post_focused = ""
                if use_vision:
                    post_focused = await _get_focused_label(config.serial, True)

                # Record in vision map with element-level detail
                vision_map.observe_transition(
                    screen_key=current_key, action=action,
                    from_element=pre_focused or current_key,
                    to_element=post_focused or post_key,
                    to_screen_key=post_key if post_key != current_key else "",
                    transition_ms=result.settle_ms, source="crawl",
                )
                if post_focused:
                    target_key = post_key if post_key != current_key else current_key
                    vision_map.set_last_focused(target_key, post_focused)

                _crawl_status.nodes_discovered = len(vision_map._screens)

                # New screen → queue for deeper exploration
                if result.transitioned and post_key != current_key:
                    screen = vision_map.get_screen(post_key)
                    if screen is None or screen.visit_count <= 1:
                        queue.append((post_key, depth + 1, path + [action]))

                # Navigate back
                if result.transitioned and action != "back":
                    back_result = await action_executor.navigate(
                        serial=config.serial, action="back",
                        settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
                    )
                    transitions += 1
                    _crawl_status.transitions_executed = transitions

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

                    if back_key != current_key:
                        recovered = await _navigate_to(config, current_key, monitor)
                        if not recovered:
                            logger.warning("[STB_AUTOMATION] Back failed, moving on")
                            break

                if transitions % SAVE_INTERVAL == 0:
                    vision_map.save()

        _crawl_status.state = "completed"

    except asyncio.CancelledError:
        _crawl_status.state = "completed"
    except Exception as e:
        logger.exception("[STB_AUTOMATION] Crawl error")
        _crawl_status.state = "error"
        _crawl_status.error = str(e)
    finally:
        vision_map.save()
        vision_cache.save()
        logger.info("[STB_AUTOMATION] Crawl finished: %d screens, %d transitions",
                     len(vision_map._screens), transitions)


async def _navigate_to(config: CrawlConfig, target_key: str, monitor) -> bool:
    """Navigate to a screen using home + vision map pathfinding."""
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

    for action, _element in path:
        result = await action_executor.navigate(
            serial=config.serial, action=action,
            settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
        )
        current_key = f"{result.post_state.package}/{result.post_state.activity}"
        if current_key == target_key:
            return True

    return False


def _tried_actions(screen_key: str) -> Set[str]:
    entries = vision_map.get_screen_entries(screen_key)
    return {e.action for e in entries}
