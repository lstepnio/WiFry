"""STB_AUTOMATION — ADB-based screen state reader.

Reads the current STB screen state using three signal sources:
  1. ``dumpsys window windows`` → foreground package/activity
  2. ``uiautomator dump`` → full UI hierarchy as XML
  3. Recent logcat events (via logcat_monitor)

All ADB interactions go through ``adb_manager`` — no raw subprocess calls.
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Optional

from ...services import adb_manager
from .models import LogcatEvent, ScreenState, UIElement

logger = logging.getLogger("wifry.stb_automation.screen_reader")


# ── Foreground activity via dumpsys ─────────────────────────────────


async def read_foreground_activity(serial: str) -> tuple[str, str]:
    """Return (package, activity) of the foreground window.

    Uses ``dumpsys window windows`` and looks for the ``mCurrentFocus``
    or ``mFocusedApp`` line.  Falls back to empty strings on parse
    failure.
    """
    result = await adb_manager.shell(serial, "dumpsys window windows")
    return _parse_foreground(result.stdout)


def _parse_foreground(dumpsys_output: str) -> tuple[str, str]:
    """Extract package/activity from dumpsys output."""
    # Look for: mCurrentFocus=Window{... com.foo.bar/com.foo.bar.MainActivity}
    for pattern in (
        r"mCurrentFocus=.*\s+(\S+)/(\S+)\}",
        r"mFocusedApp=.*\s+(\S+)/(\S+)\s",
    ):
        m = re.search(pattern, dumpsys_output)
        if m:
            return m.group(1), m.group(2)
    return "", ""


# ── UI hierarchy via uiautomator ────────────────────────────────────


async def read_ui_hierarchy(serial: str) -> List[UIElement]:
    """Dump the UI hierarchy and return parsed elements.

    Runs ``uiautomator dump`` on the device, then reads the resulting
    XML file.  Returns an empty list when the dump fails (e.g. custom
    renderer without accessibility).
    """
    # uiautomator dump writes to /sdcard/window_dump.xml by default
    dump_result = await adb_manager.shell(serial, "uiautomator dump /sdcard/window_dump.xml")
    if dump_result.exit_code != 0:
        logger.warning("uiautomator dump failed: %s", dump_result.stderr or dump_result.stdout)
        return []

    read_result = await adb_manager.shell(serial, "cat /sdcard/window_dump.xml")
    if read_result.exit_code != 0 or not read_result.stdout.strip():
        return []

    return _parse_ui_xml(read_result.stdout)


def _parse_ui_xml(xml_text: str) -> List[UIElement]:
    """Parse uiautomator XML dump into UIElement list."""
    elements: List[UIElement] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("Failed to parse uiautomator XML")
        return elements

    for node in root.iter("node"):
        elements.append(
            UIElement(
                resource_id=node.get("resource-id", ""),
                text=node.get("text", ""),
                class_name=node.get("class", ""),
                bounds=node.get("bounds", ""),
                focused=node.get("focused", "false") == "true",
                clickable=node.get("clickable", "false") == "true",
                selected=node.get("selected", "false") == "true",
            )
        )
    return elements


def _find_focused(elements: List[UIElement]) -> Optional[UIElement]:
    """Return the first focused element, or None."""
    for el in elements:
        if el.focused:
            return el
    return None


# ── Combined screen state ───────────────────────────────────────────


async def read_screen_state(
    serial: str,
    recent_events: Optional[List[LogcatEvent]] = None,
    include_hierarchy: bool = True,
) -> ScreenState:
    """Read the full screen state from ADB.

    Parameters
    ----------
    serial:
        ADB device serial (e.g. ``192.168.1.50:5555``).
    recent_events:
        Optional logcat events to attach for context.
    include_hierarchy:
        If False, skip the (slower) uiautomator dump and only read
        the foreground activity via dumpsys.
    """
    package, activity = await read_foreground_activity(serial)

    elements: List[UIElement] = []
    focused: Optional[UIElement] = None
    if include_hierarchy:
        elements = await read_ui_hierarchy(serial)
        focused = _find_focused(elements)

    return ScreenState(
        package=package,
        activity=activity,
        ui_elements=elements,
        focused_element=focused,
        recent_events=recent_events or [],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── Mock helpers ────────────────────────────────────────────────────


def mock_screen_state() -> ScreenState:
    """Return a synthetic screen state for mock / dev mode."""
    elements = [
        UIElement(
            resource_id="com.example.stb:id/menu_home",
            text="Home",
            class_name="android.widget.TextView",
            bounds="[0,0][200,50]",
            focused=True,
            clickable=True,
        ),
        UIElement(
            resource_id="com.example.stb:id/menu_apps",
            text="Apps",
            class_name="android.widget.TextView",
            bounds="[200,0][400,50]",
            clickable=True,
        ),
        UIElement(
            resource_id="com.example.stb:id/menu_settings",
            text="Settings",
            class_name="android.widget.TextView",
            bounds="[400,0][600,50]",
            clickable=True,
        ),
    ]
    return ScreenState(
        package="com.example.stb",
        activity="com.example.stb/.HomeActivity",
        ui_elements=elements,
        focused_element=elements[0],
        recent_events=[
            LogcatEvent(
                event_type="ACTIVITY_DISPLAYED",
                package="com.example.stb",
                activity=".HomeActivity",
                timestamp=datetime.now(timezone.utc).isoformat(),
                raw="ActivityManager: Displayed com.example.stb/.HomeActivity",
            )
        ],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
