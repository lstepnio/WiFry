"""STB_AUTOMATION — BFS crawl engine for automated UI discovery.

Explores the STB UI by sending key presses and recording transitions
into the unified vision map.  Uses activity-based screen identity
and feeds all transitions through vision_map.observe_transition().

Back-tracking: uses ``back`` key to return to parent.  If ``back``
goes somewhere unexpected, falls back to ``home`` and replays the
path from the vision map.

The engine runs as an async background task and can be paused,
resumed, or stopped via the API.
"""

import asyncio
import logging
from typing import Optional, Set

from . import action_executor, fingerprint as fp, screen_reader, vision_map
from .logcat_monitor import get_monitor
from .models import CrawlConfig, CrawlStatus, ScreenState

logger = logging.getLogger("wifry.stb_automation.crawl_engine")

# Module-level crawl state
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
    logger.info("[STB_AUTOMATION] Crawl started: serial=%s max_depth=%d",
                config.serial, config.max_depth)
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

    # Find first untried action
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

    result = await action_executor.navigate(
        serial=config.serial, action=action,
        settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
    )
    post_key = f"{result.post_state.package}/{result.post_state.activity}"

    # Record in vision map
    from_focused = vision_map.get_last_focused(screen_key)
    vision_map.observe_transition(
        screen_key=screen_key, action=action,
        from_element=from_focused or screen_key,
        to_element=from_focused or post_key,  # best we have without vision
        to_screen_key=post_key if post_key != screen_key else "",
        transition_ms=result.settle_ms, source="crawl",
    )
    vision_map.save()

    return {
        "status": "stepped", "action": action,
        "from_screen": screen_key, "to_screen": post_key,
        "transitioned": result.transitioned,
        "settle_ms": round(result.settle_ms, 1),
    }


# ── BFS crawl loop ─────────────────────────────────────────────────


async def _crawl_loop(config: CrawlConfig) -> None:
    global _crawl_status
    monitor = get_monitor()
    transitions = 0

    try:
        # Read initial state
        state, _ = await screen_reader.read_screen_state(
            config.serial,
            recent_events=monitor.get_events(5) if monitor.is_active else [],
            include_hierarchy=False,
        )
        root_key = f"{state.package}/{state.activity}"
        _crawl_status.nodes_discovered = len(vision_map._screens) or 1
        _crawl_status.current_node_id = root_key

        # BFS queue: (screen_key, depth, path_from_home)
        queue: list[tuple[str, int, list[str]]] = [(root_key, 0, [])]
        visited_from: Set[tuple[str, str]] = set()

        while queue and not _crawl_cancel.is_set():
            current_key, depth, path = queue.pop(0)

            if depth >= config.max_depth or transitions >= config.max_transitions:
                continue

            # Verify we're at the right screen
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
                from_focused = vision_map.get_last_focused(current_key)

                result = await action_executor.navigate(
                    serial=config.serial, action=action,
                    settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
                )
                transitions += 1
                _crawl_status.transitions_executed = transitions

                post_key = f"{result.post_state.package}/{result.post_state.activity}"

                # Record observation in unified vision map
                vision_map.observe_transition(
                    screen_key=current_key, action=action,
                    from_element=from_focused or current_key,
                    to_element=from_focused or post_key,
                    to_screen_key=post_key if post_key != current_key else "",
                    transition_ms=result.settle_ms, source="crawl",
                )

                _crawl_status.nodes_discovered = len(vision_map._screens)

                # New screen — add to BFS queue
                if result.transitioned and post_key != current_key:
                    screen = vision_map.get_screen(post_key)
                    if screen is None or screen.visit_count <= 1:
                        queue.append((post_key, depth + 1, path + [action]))

                # Navigate back for next action
                if result.transitioned and action != "back":
                    back_result = await action_executor.navigate(
                        serial=config.serial, action="back",
                        settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
                    )
                    transitions += 1
                    _crawl_status.transitions_executed = transitions

                    back_key = f"{back_result.post_state.package}/{back_result.post_state.activity}"
                    vision_map.observe_transition(
                        screen_key=post_key, action="back",
                        from_element=vision_map.get_last_focused(post_key) or post_key,
                        to_element=vision_map.get_last_focused(back_key) or back_key,
                        to_screen_key=back_key if back_key != post_key else "",
                        transition_ms=back_result.settle_ms, source="crawl",
                    )

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
        logger.info("[STB_AUTOMATION] Crawl finished: %d screens, %d transitions",
                     len(vision_map._screens), transitions)


async def _navigate_to(
    config: CrawlConfig,
    target_key: str,
    monitor,
) -> bool:
    """Navigate to a screen using home + vision map pathfinding."""
    home_result = await action_executor.navigate(
        serial=config.serial, action="home",
        settle_timeout_ms=config.settle_timeout_ms, monitor=monitor,
    )
    home_key = f"{home_result.post_state.package}/{home_result.post_state.activity}"
    if home_key == target_key:
        return True

    # Try screen-level pathfinding
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
    """Return actions already observed from this screen."""
    entries = vision_map.get_screen_entries(screen_key)
    return {e.action for e in entries}
