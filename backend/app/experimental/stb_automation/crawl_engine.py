"""STB_AUTOMATION — BFS crawl engine for automated UI discovery.

Explores the STB UI by sending key presses and recording state
transitions into the navigation model.  The crawl uses BFS with
bounded depth and a max-transitions cap.

Back-tracking: uses ``back`` key to return to parent.  If ``back``
goes somewhere unexpected, falls back to ``home`` and replays the
path from the navigation model.

The engine runs as an async background task and can be paused,
resumed, or stopped via the API.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Set

from . import action_executor, fingerprint as fp, nav_model, screen_reader
from .logcat_monitor import get_monitor
from .models import CrawlConfig, CrawlStatus, NavigationModel, ScreenNode, ScreenState

logger = logging.getLogger("wifry.stb_automation.crawl_engine")

# Module-level crawl state
_crawl_status = CrawlStatus()
_crawl_task: Optional[asyncio.Task] = None
_crawl_cancel = asyncio.Event()

SAVE_INTERVAL = 10  # Persist model every N transitions


def get_status() -> CrawlStatus:
    return _crawl_status.model_copy()


async def start_crawl(config: CrawlConfig) -> CrawlStatus:
    """Start a BFS crawl as a background task."""
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
    """Stop the running crawl and persist the model."""
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
    """Execute a single exploration step (manual mode).

    Reads the current state, tries the next unexplored action, and
    records the result.  Returns the transition details.
    """
    model = nav_model.get_or_create_model(config.serial)
    monitor = get_monitor()

    state, _ = await screen_reader.read_screen_state(
        config.serial,
        recent_events=monitor.get_events(5) if monitor.is_active else [],
    )
    node_id = fp.fingerprint(state)
    node = _state_to_node(state, node_id)
    nav_model.upsert_node(model, node)

    # Find first untried action from this node
    tried = _tried_actions(model, node_id)
    action = None
    for a in config.explore_actions:
        if a not in tried:
            action = a
            break

    if action is None:
        nav_model.save_model(config.serial)
        return {
            "status": "exhausted",
            "node_id": node_id,
            "message": "All actions already tried from this node",
        }

    result = await action_executor.navigate(
        serial=config.serial,
        action=action,
        settle_timeout_ms=config.settle_timeout_ms,
        monitor=monitor,
    )

    post_id = fp.fingerprint(result.post_state)
    post_node = _state_to_node(result.post_state, post_id)
    nav_model.upsert_node(model, post_node)
    nav_model.record_transition(
        model, node_id, post_id, action, result.settle_ms, result.settle_method,
    )
    nav_model.save_model(config.serial)

    return {
        "status": "stepped",
        "action": action,
        "from_node": node_id,
        "to_node": post_id,
        "transitioned": result.transitioned,
        "settle_method": result.settle_method,
        "settle_ms": round(result.settle_ms, 1),
    }


# ── BFS crawl loop ─────────────────────────────────────────────────


async def _crawl_loop(config: CrawlConfig) -> None:
    """BFS exploration loop.  Runs as a background task."""
    global _crawl_status

    model = nav_model.get_or_create_model(config.serial, config.serial)
    monitor = get_monitor()
    transitions = 0

    try:
        # Read initial state
        state, _ = await screen_reader.read_screen_state(
            config.serial,
            recent_events=monitor.get_events(5) if monitor.is_active else [],
        )
        root_id = fp.fingerprint(state)
        root_node = _state_to_node(state, root_id)
        nav_model.upsert_node(model, root_node)

        if not model.home_node_id:
            model.home_node_id = root_id

        _crawl_status.nodes_discovered = len(model.nodes)
        _crawl_status.current_node_id = root_id

        # BFS queue: (node_id, depth, path_from_home)
        queue: list[tuple[str, int, list[str]]] = [(root_id, 0, [])]
        visited_from: Set[tuple[str, str]] = set()  # (node_id, action) pairs tried

        while queue and not _crawl_cancel.is_set():
            current_id, depth, path = queue.pop(0)

            if depth >= config.max_depth:
                continue
            if transitions >= config.max_transitions:
                break

            # Navigate to current node if we're not already there
            actual_state, _ = await screen_reader.read_screen_state(
                config.serial, include_hierarchy=False,
            )
            actual_id = fp.fingerprint_from_activity(
                actual_state.package, actual_state.activity,
            )

            # If not at expected node, try to navigate there
            if actual_id != current_id:
                recovered = await _navigate_to(config, model, current_id, monitor)
                if not recovered:
                    logger.warning("[STB_AUTOMATION] Could not reach node %s, skipping", current_id)
                    continue

            _crawl_status.current_node_id = current_id

            # Try each action from this node
            for action in config.explore_actions:
                if _crawl_cancel.is_set():
                    break
                if transitions >= config.max_transitions:
                    break
                if (current_id, action) in visited_from:
                    continue

                visited_from.add((current_id, action))

                result = await action_executor.navigate(
                    serial=config.serial,
                    action=action,
                    settle_timeout_ms=config.settle_timeout_ms,
                    monitor=monitor,
                )
                transitions += 1
                _crawl_status.transitions_executed = transitions

                post_id = fp.fingerprint(result.post_state)
                post_node = _state_to_node(result.post_state, post_id)
                nav_model.upsert_node(model, post_node)
                nav_model.record_transition(
                    model, current_id, post_id, action,
                    result.settle_ms, result.settle_method,
                )

                _crawl_status.nodes_discovered = len(model.nodes)

                if result.transitioned and post_id not in model.nodes or post_node.visit_count <= 1:
                    # New node — add to BFS queue
                    queue.append((post_id, depth + 1, path + [action]))

                # Navigate back to current node for next action
                if result.transitioned and action != "back":
                    back_result = await action_executor.navigate(
                        serial=config.serial,
                        action="back",
                        settle_timeout_ms=config.settle_timeout_ms,
                        monitor=monitor,
                    )
                    transitions += 1
                    _crawl_status.transitions_executed = transitions

                    back_id = fp.fingerprint(back_result.post_state)
                    back_node = _state_to_node(back_result.post_state, back_id)
                    nav_model.upsert_node(model, back_node)
                    nav_model.record_transition(
                        model, post_id, back_id, "back",
                        back_result.settle_ms, back_result.settle_method,
                    )

                    # If back didn't return us, try home + replay
                    if back_id != current_id:
                        recovered = await _navigate_to(config, model, current_id, monitor)
                        if not recovered:
                            logger.warning("[STB_AUTOMATION] Back failed and recovery failed, moving on")
                            break

                # Periodic save
                if transitions % SAVE_INTERVAL == 0:
                    nav_model.save_model(config.serial)

        _crawl_status.state = "completed"

    except asyncio.CancelledError:
        _crawl_status.state = "completed"
    except Exception as e:
        logger.exception("[STB_AUTOMATION] Crawl error")
        _crawl_status.state = "error"
        _crawl_status.error = str(e)
    finally:
        nav_model.save_model(config.serial)
        logger.info(
            "[STB_AUTOMATION] Crawl finished: %d nodes, %d transitions",
            len(model.nodes), transitions,
        )


async def _navigate_to(
    config: CrawlConfig,
    model: NavigationModel,
    target_id: str,
    monitor,
) -> bool:
    """Try to navigate to a specific node using the nav model.

    First tries home + pathfinding.  Returns True if successful.
    """
    # Press home first
    home_result = await action_executor.navigate(
        serial=config.serial,
        action="home",
        settle_timeout_ms=config.settle_timeout_ms,
        monitor=monitor,
    )
    home_id = fp.fingerprint(home_result.post_state)

    if home_id == target_id:
        return True

    # Try pathfinding from home
    path = nav_model.find_path(model, home_id, target_id)
    if path is None:
        return False

    for action in path:
        result = await action_executor.navigate(
            serial=config.serial,
            action=action,
            settle_timeout_ms=config.settle_timeout_ms,
            monitor=monitor,
        )
        current_id = fp.fingerprint(result.post_state)
        if current_id == target_id:
            return True

    return False


# ── Helpers ─────────────────────────────────────────────────────────


def _state_to_node(state: ScreenState, node_id: str) -> ScreenNode:
    """Convert a ScreenState into a ScreenNode."""
    return ScreenNode(
        id=node_id,
        fingerprint=node_id,
        package=state.package,
        activity=state.activity,
        elements=state.ui_elements,
        last_visited=datetime.now(timezone.utc).isoformat(),
    )


def _tried_actions(model, node_id: str) -> Set[str]:
    """Return the set of actions already tried from a node."""
    tried = set()
    for edge in model.edges:
        if edge.from_node == node_id:
            tried.add(edge.action)
    return tried
