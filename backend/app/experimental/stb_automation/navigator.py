"""STB_AUTOMATION — Non-fragile element-based navigation.

Navigate to specific UI elements or screens by identity, not by
counting key presses.  Uses the vision map to find the action
sequence and verifies each step via vision analysis.

Example: navigate_to_element("Settings") instead of "press down 4 times".
"""

import asyncio
import logging
from typing import Optional

from . import action_executor, fingerprint as fp, screen_reader, vision_cache, vision_map
from .logcat_monitor import get_monitor
from .models import VisionAnalysis

logger = logging.getLogger("wifry.stb_automation.navigator")

MAX_RETRIES = 3
MAX_PATH_LENGTH = 20


async def navigate_to_element(
    serial: str,
    target_element: str,
    screen_key: Optional[str] = None,
    settle_timeout_ms: int = 1000,
) -> dict:
    """Navigate to a specific UI element on the current screen.

    Uses vision map pathfinding to determine the action sequence,
    then executes each action and verifies focus via vision.

    Returns dict with success status, actions taken, and final focused element.
    """
    monitor = get_monitor()

    # Determine current screen if not provided
    if not screen_key:
        state, _ = await screen_reader.read_screen_state(
            serial, include_hierarchy=False,
        )
        screen_key = f"{state.package}/{state.activity}"

    # Get current focused element
    from_element = vision_map.get_last_focused(screen_key)
    if not from_element:
        # Try vision to determine current focus
        from_element = await _get_current_focus(serial)
        if from_element:
            vision_map.set_last_focused(screen_key, from_element)

    if not from_element:
        return {
            "success": False,
            "error": "Cannot determine current focused element",
            "screen_key": screen_key,
        }

    if from_element == target_element:
        return {
            "success": True,
            "actions": [],
            "from_element": from_element,
            "to_element": target_element,
            "screen_key": screen_key,
        }

    # Find path via vision map
    path = vision_map.find_element_path(screen_key, from_element, target_element)
    if path is None:
        return {
            "success": False,
            "error": f"No known path from '{from_element}' to '{target_element}' on {screen_key}",
            "screen_key": screen_key,
            "from_element": from_element,
        }

    if len(path) > MAX_PATH_LENGTH:
        return {
            "success": False,
            "error": f"Path too long ({len(path)} actions), likely a loop",
            "screen_key": screen_key,
        }

    # Execute path, verify after each step
    actions_taken = []
    current_focus = from_element
    retries = 0

    for action in path:
        result = await action_executor.navigate(
            serial=serial, action=action,
            settle_timeout_ms=settle_timeout_ms, monitor=monitor,
        )
        actions_taken.append(action)

        # Verify focus via vision
        new_focus = await _get_current_focus(serial)
        if new_focus:
            vision_map.set_last_focused(screen_key, new_focus)
            current_focus = new_focus

            if new_focus == target_element:
                return {
                    "success": True,
                    "actions": actions_taken,
                    "from_element": from_element,
                    "to_element": target_element,
                    "screen_key": screen_key,
                }

    # Path completed — check if we arrived
    final_focus = await _get_current_focus(serial) or current_focus
    if final_focus:
        vision_map.set_last_focused(screen_key, final_focus)

    return {
        "success": final_focus == target_element,
        "actions": actions_taken,
        "from_element": from_element,
        "to_element": final_focus or "unknown",
        "expected_element": target_element,
        "screen_key": screen_key,
    }


async def navigate_to_screen(
    serial: str,
    target_screen_key: str,
    settle_timeout_ms: int = 1000,
) -> dict:
    """Navigate to a specific screen (activity).

    Uses vision map cross-screen pathfinding to determine the sequence
    of enter/back actions needed, then navigates element-by-element.

    Returns dict with success status, actions taken, and final screen.
    """
    monitor = get_monitor()

    # Determine current screen
    state, _ = await screen_reader.read_screen_state(
        serial, include_hierarchy=False,
    )
    current_key = f"{state.package}/{state.activity}"

    if current_key == target_screen_key:
        return {
            "success": True,
            "actions": [],
            "from_screen": current_key,
            "to_screen": target_screen_key,
        }

    # Find cross-screen path
    path = vision_map.find_screen_path(current_key, target_screen_key)
    if path is None:
        # Try home first, then pathfind from home
        home_result = await action_executor.navigate(
            serial=serial, action="home",
            settle_timeout_ms=settle_timeout_ms, monitor=monitor,
        )
        home_key = f"{home_result.post_state.package}/{home_result.post_state.activity}"
        if home_key == target_screen_key:
            return {
                "success": True,
                "actions": ["home"],
                "from_screen": current_key,
                "to_screen": target_screen_key,
            }

        path = vision_map.find_screen_path(home_key, target_screen_key)
        if path is None:
            return {
                "success": False,
                "error": f"No known path from '{current_key}' to '{target_screen_key}'",
                "from_screen": current_key,
            }
        current_key = home_key

    # Execute path: each hop is (action, element_to_activate)
    actions_taken = []
    for action, element in path:
        # If we need to focus a specific element before pressing the action
        if element and action == "enter":
            focus_result = await navigate_to_element(
                serial=serial,
                target_element=element,
                screen_key=current_key,
                settle_timeout_ms=settle_timeout_ms,
            )
            if focus_result.get("success"):
                actions_taken.extend(focus_result.get("actions", []))

        # Execute the cross-screen action
        result = await action_executor.navigate(
            serial=serial, action=action,
            settle_timeout_ms=settle_timeout_ms, monitor=monitor,
        )
        actions_taken.append(action)

        # Check if we arrived
        post_state, _ = await screen_reader.read_screen_state(
            serial, include_hierarchy=False,
        )
        current_key = f"{post_state.package}/{post_state.activity}"

        if current_key == target_screen_key:
            return {
                "success": True,
                "actions": actions_taken,
                "from_screen": f"{state.package}/{state.activity}",
                "to_screen": target_screen_key,
            }

    return {
        "success": current_key == target_screen_key,
        "actions": actions_taken,
        "from_screen": f"{state.package}/{state.activity}",
        "to_screen": current_key,
        "expected_screen": target_screen_key,
    }


async def _get_current_focus(serial: str) -> str:
    """Get the current focused element label via vision."""
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
        if cache_key:
            vision_cache.put(cache_key, vision_obj)

        return vision_obj.focused_label or ""

    except (ImportError, Exception) as e:
        logger.debug("[STB_AUTOMATION] _get_current_focus failed: %s", e)
        return ""
