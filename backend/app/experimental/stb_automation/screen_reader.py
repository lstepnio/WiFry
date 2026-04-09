"""STB_AUTOMATION — ADB-based screen state reader.

Reads the current STB screen state using multiple signal sources:
  1. ``dumpsys window displays`` → foreground package/activity
  2. ``uiautomator dump`` → full UI hierarchy as XML
  3. ``dumpsys activity top`` → fragment names, view hierarchy context
  4. ``dumpsys window`` → window title
  5. Recent logcat events (via logcat_monitor)

All ADB interactions go through ``adb_manager`` — no raw subprocess calls.
"""

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from ...services import adb_manager
from .models import LogcatEvent, ScreenState, UIElement

logger = logging.getLogger("wifry.stb_automation.screen_reader")


@dataclass
class ReadTimings:
    """Per-stage timing breakdown for screen state reads."""
    foreground_ms: int = 0
    hierarchy_ms: int = 0
    fragments_ms: int = 0
    window_title_ms: int = 0
    total_ms: int = 0


# ── Foreground activity via dumpsys ─────────────────────────────────


async def read_foreground_activity(
    serial: str,
    window_dumpsys_output: Optional[str] = None,
) -> tuple[str, str]:
    """Return (package, activity) of the foreground window.

    Tries multiple dumpsys sources because STBs vary widely:
      1. ``dumpsys window displays`` — modern Android TV / operator STBs
      2. ``dumpsys window windows``  — standard AOSP / older devices
      3. ``dumpsys activity activities`` — fallback via ActivityManager

    Falls back to empty strings on parse failure.

    Parameters
    ----------
    window_dumpsys_output:
        Pre-fetched ``dumpsys window displays`` output to avoid redundant
        ADB calls.  When provided, the first ADB command is skipped.
    """
    # Try pre-fetched output first (if provided)
    if window_dumpsys_output is not None:
        pkg, act = _parse_foreground(window_dumpsys_output)
        if pkg:
            return pkg, act
    else:
        # Try dumpsys window displays first (works on most Android TV STBs)
        result = await adb_manager.shell(serial, "dumpsys window displays")
        pkg, act = _parse_foreground(result.stdout)
        if pkg:
            return pkg, act

    # Try dumpsys window windows (standard AOSP)
    result = await adb_manager.shell(serial, "dumpsys window windows")
    pkg, act = _parse_foreground(result.stdout)
    if pkg:
        return pkg, act

    # Fallback: dumpsys activity activities
    result = await adb_manager.shell(serial, "dumpsys activity activities")
    pkg, act = _parse_activity_dumpsys(result.stdout)
    return pkg, act


def _parse_foreground(dumpsys_output: str) -> tuple[str, str]:
    """Extract package/activity from dumpsys window output."""
    for pattern in (
        # mCurrentFocus=Window{... u0 com.foo/com.foo.MainActivity}
        r"mCurrentFocus=.*\s+(\S+)/(\S+)\}",
        # mFocusedApp=ActivityRecord{... u0 com.foo/.MainActivity ...}
        r"mFocusedApp=.*\s+(\S+)/(\S+)\s",
        # mFocusedWindow=Window{... u0 com.foo/com.foo.MainActivity}
        r"mFocusedWindow=.*\s+(\S+)/(\S+)\}",
    ):
        m = re.search(pattern, dumpsys_output)
        if m:
            return m.group(1), m.group(2)
    return "", ""


def _parse_activity_dumpsys(activity_output: str) -> tuple[str, str]:
    """Extract package/activity from dumpsys activity output."""
    for pattern in (
        # mResumedActivity: ActivityRecord{... u0 com.foo/.MainActivity t123}
        r"mResumedActivity:.*\s+(\S+)/(\S+)\s",
        # mFocusedActivity: ActivityRecord{... u0 com.foo/.MainActivity t123}
        r"mFocusedActivity:.*\s+(\S+)/(\S+)\s",
    ):
        m = re.search(pattern, activity_output)
        if m:
            return m.group(1), m.group(2)
    return "", ""


# ── Window title via dumpsys window ────────────────────────────────


async def read_window_title(
    serial: str,
    window_dumpsys_output: Optional[str] = None,
) -> str:
    """Extract the window title from dumpsys window.

    Parses ``mCurrentFocus`` and ``mFocusedWindow`` for the window
    title string.  On Android TV STBs, this often contains the app's
    declared label or a meaningful screen name.

    Parameters
    ----------
    window_dumpsys_output:
        Pre-fetched ``dumpsys window displays`` output to avoid redundant
        ADB calls.  When provided, the first ADB command is skipped.
    """
    # Try pre-fetched output first (if provided)
    if window_dumpsys_output is not None:
        title = _parse_window_title(window_dumpsys_output)
        if title:
            return title
    else:
        result = await adb_manager.shell(serial, "dumpsys window displays")
        title = _parse_window_title(result.stdout)
        if title:
            return title

    result = await adb_manager.shell(serial, "dumpsys window windows")
    return _parse_window_title(result.stdout)


def _parse_window_title(dumpsys_output: str) -> str:
    """Parse window title from dumpsys window output."""
    # mCurrentFocus=Window{abcdef0 u0 com.tivo.hydra.app/com.tivo.hydra.ui.TvActivity}
    # The full window descriptor after "u0 " is the title
    for pattern in (
        r"mCurrentFocus=Window\{[^}]*\s+u\d+\s+([^}]+)\}",
        r"mFocusedWindow=Window\{[^}]*\s+u\d+\s+([^}]+)\}",
    ):
        m = re.search(pattern, dumpsys_output)
        if m:
            return m.group(1).strip()
    return ""


# ── Fragments via dumpsys activity top ─────────────────────────────


async def read_fragments(serial: str) -> List[str]:
    """Extract active fragment names from ``dumpsys activity top``.

    Fragment names are incredibly valuable on operator STBs — they tell
    us exactly which screen we're on (e.g. ``GuideFragment``,
    ``HomeFragment``, ``MyShowsFragment``), even when the Activity name
    is always the same (single-activity apps).
    """
    result = await adb_manager.shell(serial, "dumpsys activity top")
    return _parse_fragments(result.stdout)


def _parse_fragments(activity_top_output: str) -> List[str]:
    """Parse fragment class names from dumpsys activity top output.

    The output contains lines like:
      Added Fragments:
        #0: GuideFragment{abc1234 ...}
        #1: PlayerOverlayFragment{def5678 ...}
      Back Stack:
        #0: BackStackEntry{...}
    """
    fragments: List[str] = []
    seen: set = set()

    # Match fragment entries: #N: FragmentName{hash ...}
    for m in re.finditer(
        r"#\d+:\s+(\w+)\{[0-9a-f]+",
        activity_top_output,
    ):
        name = m.group(1)
        # Skip generic framework fragments
        if name in (
            "BackStackEntry",
            "FragmentManagerImpl",
            "FragmentContainerView",
        ):
            continue
        if name not in seen:
            seen.add(name)
            fragments.append(name)

    # Also look for "Local FragmentActivity" section lines like:
    #   com.tivo.hydra.ui.fragments.GuideFragment (abc1234)
    for m in re.finditer(
        r"\b(\w+Fragment\w*)\b",
        activity_top_output,
    ):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            fragments.append(name)

    return fragments


# ── Accessibility / input focus via dumpsys ─────────────────────────


async def read_input_focus(serial: str) -> str:
    """Get the current input focus description from ``dumpsys input``.

    Returns the focused window name from the input system, which can
    differ from the WindowManager focus (e.g., during IME input or
    popup overlays).
    """
    result = await adb_manager.shell(serial, "dumpsys input")
    return _parse_input_focus(result.stdout)


def _parse_input_focus(input_output: str) -> str:
    """Parse focused window from dumpsys input output."""
    # FocusedWindow: name='com.tivo.hydra.app/com.tivo.hydra.ui.TvActivity', ...
    m = re.search(r"FocusedWindow:.*?name='([^']+)'", input_output)
    if m:
        return m.group(1)
    # focusedWindowHandle: name='...'
    m = re.search(r"focusedWindowHandle:.*?name='([^']+)'", input_output)
    if m:
        return m.group(1)
    return ""


# ── UI hierarchy via uiautomator ────────────────────────────────────


async def read_ui_hierarchy(serial: str) -> Tuple[List[UIElement], Optional[ET.Element]]:
    """Dump the UI hierarchy and return parsed elements + raw XML root.

    Runs ``uiautomator dump`` on the device, then reads the resulting
    XML file.  Returns (elements, xml_root) — xml_root is kept for
    tree-based focused context analysis.  Returns ([], None) when the
    dump fails.
    """
    # uiautomator dump writes to /sdcard/window_dump.xml by default
    dump_result = await adb_manager.shell(serial, "uiautomator dump /sdcard/window_dump.xml")
    if dump_result.exit_code != 0:
        logger.warning("uiautomator dump failed: %s", dump_result.stderr or dump_result.stdout)
        return [], None

    read_result = await adb_manager.shell(serial, "cat /sdcard/window_dump.xml")
    if read_result.exit_code != 0 or not read_result.stdout.strip():
        return [], None

    return _parse_ui_xml(read_result.stdout)


def _parse_ui_xml(xml_text: str) -> Tuple[List[UIElement], Optional[ET.Element]]:
    """Parse uiautomator XML dump into UIElement list + raw root."""
    elements: List[UIElement] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("Failed to parse uiautomator XML")
        return elements, None

    for node in root.iter("node"):
        elements.append(
            UIElement(
                resource_id=node.get("resource-id", ""),
                text=node.get("text", ""),
                class_name=node.get("class", ""),
                package=node.get("package", ""),
                content_desc=node.get("content-desc", ""),
                bounds=node.get("bounds", ""),
                focused=node.get("focused", "false") == "true",
                clickable=node.get("clickable", "false") == "true",
                selected=node.get("selected", "false") == "true",
            )
        )
    return elements, root


def _find_focused(elements: List[UIElement]) -> Optional[UIElement]:
    """Return the focused or selected element with the best label.

    STBs vary: some use ``focused=true``, others use ``selected=true``,
    and NAF (Not Accessibility Friendly) nodes may have empty text/class.
    When multiple candidates exist, prefer the one with a meaningful label.
    """
    candidates = [el for el in elements if el.focused or el.selected]
    if not candidates:
        return None

    def _label_score(el: UIElement) -> int:
        """Higher = more informative label."""
        score = 0
        if el.text:
            score += 4
        if el.resource_id:
            score += 3
        if el.content_desc:
            score += 2
        if el.class_name:
            score += 1
        return score

    # Prefer focused over selected, then best label
    candidates.sort(key=lambda el: (el.focused, _label_score(el)), reverse=True)
    return candidates[0]


# ── Focused context from XML tree ──────────────────────────────────


def _build_focused_context(
    xml_root: Optional[ET.Element],
    focused_el: Optional[UIElement],
    fragments: List[str],
    window_title: str,
    activity: str,
    recent_events: Optional[List[LogcatEvent]] = None,
) -> str:
    """Build a human-readable context string from all available signals.

    When the focused element is a NAF node (empty text/resource_id),
    we mine the XML tree for:
      - Parent node resource_id (tells us which container has focus)
      - Sibling node text labels (tells us what's nearby)
      - Child node text (focused container might have text children)

    Also incorporates:
      - Fragment names from ``dumpsys activity top``
      - Window title from ``dumpsys window``
      - Recent logcat events (fragment transitions, accessibility focus,
        view focus changes) for real-time context
    """
    parts: List[str] = []

    # 1. Direct focused element label
    if focused_el:
        direct_label = (
            focused_el.text
            or focused_el.content_desc
            or focused_el.resource_id
        )
        if direct_label:
            parts.append(f"focused on: {direct_label}")

    # 2. XML tree context around the focused node
    if xml_root is not None and focused_el:
        tree_ctx = _tree_context_for_focused(xml_root, focused_el)
        if tree_ctx:
            parts.append(tree_ctx)

    # 3. Recent logcat hints — fragment, accessibility, view focus events
    if recent_events:
        logcat_ctx = _logcat_context(recent_events)
        if logcat_ctx:
            parts.append(logcat_ctx)

    # 4. Fragment names — most valuable signal for single-activity apps
    if fragments:
        frag_names = ", ".join(fragments[:5])
        parts.append(f"fragments: [{frag_names}]")

    # 5. Activity short name (last component)
    if activity:
        short_act = activity.rsplit(".", 1)[-1] if "." in activity else activity
        parts.append(f"activity: {short_act}")

    # 6. Window title if different from package/activity
    if window_title and "/" in window_title:
        parts.append(f"window: {window_title}")

    return " | ".join(parts) if parts else ""


def _logcat_context(events: List[LogcatEvent]) -> str:
    """Extract UI context hints from recent logcat events.

    Looks for the most recent fragment, accessibility focus, and view
    focus events to provide real-time navigation context.
    """
    hints: List[str] = []

    # Walk events newest-first
    for ev in reversed(events):
        if len(hints) >= 3:
            break

        if ev.event_type in ("FRAGMENT_LIFECYCLE", "FRAGMENT_ADDED"):
            frag_name = ev.activity  # fragment name stored in activity field
            if frag_name and f"fragment: {frag_name}" not in hints:
                hints.append(f"fragment: {frag_name}")

        elif ev.event_type == "A11Y_FOCUS":
            label = ev.activity  # text or class stored in activity field
            if label and f"a11y focus: {label}" not in hints:
                hints.append(f"a11y focus: {label}")

        elif ev.event_type == "VIEW_FOCUS":
            view = ev.activity  # resource_id or view class
            if view:
                # Shorten resource IDs: com.foo:id/some_view → some_view
                if ":id/" in view:
                    view = view.split(":id/", 1)[1]
                if f"view focus: {view}" not in hints:
                    hints.append(f"view focus: {view}")

        elif ev.event_type == "FOCUS_CHANGED":
            if ev.activity and f"window focus: {ev.activity}" not in hints:
                hints.append(f"window focus: {ev.activity}")

    if hints:
        return "logcat: [" + ", ".join(hints) + "]"
    return ""


def _tree_context_for_focused(
    xml_root: ET.Element,
    focused_el: UIElement,
) -> str:
    """Walk the XML tree to find context around the focused node.

    Returns a string like:
      "in: main_menu_bar | siblings: [Home, Guide, My Shows]"
    """
    # Build parent map for upward traversal
    parent_map = {child: parent for parent in xml_root.iter("node") for child in parent}

    # Find the focused node in the tree by matching bounds (most unique attr)
    focused_node = _find_xml_node(xml_root, focused_el)
    if focused_node is None:
        return ""

    context_parts: List[str] = []

    # --- Child text labels (focused container might wrap text nodes) ---
    child_texts = _collect_child_texts(focused_node, max_depth=3, max_items=5)
    if child_texts:
        context_parts.append(f"contains: [{', '.join(child_texts)}]")

    # --- Parent context ---
    parent = parent_map.get(focused_node)
    if parent is not None:
        parent_id = parent.get("resource-id", "")
        parent_desc = parent.get("content-desc", "")
        parent_label = parent_id or parent_desc
        if parent_label:
            # Shorten resource IDs: com.foo.bar:id/menu_bar → menu_bar
            if ":id/" in parent_label:
                parent_label = parent_label.split(":id/", 1)[1]
            context_parts.append(f"in: {parent_label}")

        # --- Sibling text labels ---
        sibling_texts = []
        for sibling in parent:
            if sibling is focused_node:
                continue
            text = (
                sibling.get("text", "")
                or sibling.get("content-desc", "")
            )
            if text:
                sibling_texts.append(text)
            elif not text:
                # Check one level down for text
                for child in sibling:
                    ct = child.get("text", "") or child.get("content-desc", "")
                    if ct:
                        sibling_texts.append(ct)
                        break
        if sibling_texts:
            context_parts.append(
                f"siblings: [{', '.join(sibling_texts[:8])}]"
            )

        # --- Grandparent for deeper context ---
        grandparent = parent_map.get(parent)
        if grandparent is not None and not context_parts:
            gp_id = grandparent.get("resource-id", "")
            if gp_id:
                if ":id/" in gp_id:
                    gp_id = gp_id.split(":id/", 1)[1]
                context_parts.append(f"in: {gp_id}")

    # --- Position among siblings ---
    if focused_node is not None:
        parent = parent_map.get(focused_node)
        if parent is not None:
            siblings = list(parent)
            idx = None
            for i, s in enumerate(siblings):
                if s is focused_node:
                    idx = i
                    break
            if idx is not None and len(siblings) > 1:
                context_parts.append(f"position: {idx + 1}/{len(siblings)}")

    return " | ".join(context_parts)


def _find_xml_node(
    root: ET.Element, el: UIElement
) -> Optional[ET.Element]:
    """Find the ET node matching a UIElement by bounds + focused/selected."""
    # Best match: same bounds and focused/selected state
    for node in root.iter("node"):
        if node.get("bounds", "") == el.bounds:
            node_focused = node.get("focused", "false") == "true"
            node_selected = node.get("selected", "false") == "true"
            if (node_focused == el.focused) and (node_selected == el.selected):
                return node

    # Fallback: match by bounds alone
    for node in root.iter("node"):
        if node.get("bounds", "") == el.bounds:
            return node

    return None


def _collect_child_texts(
    node: ET.Element, max_depth: int = 3, max_items: int = 5
) -> List[str]:
    """Recursively collect text/content-desc from child nodes."""
    texts: List[str] = []
    if max_depth <= 0:
        return texts

    for child in node:
        if len(texts) >= max_items:
            break
        text = child.get("text", "") or child.get("content-desc", "")
        if text:
            texts.append(text)
        else:
            texts.extend(
                _collect_child_texts(child, max_depth - 1, max_items - len(texts))
            )
    return texts


# ── Combined screen state ───────────────────────────────────────────


async def read_screen_state(
    serial: str,
    recent_events: Optional[List[LogcatEvent]] = None,
    include_hierarchy: bool = True,
) -> tuple[ScreenState, ReadTimings]:
    """Read the full screen state from ADB.

    Combines five signal sources for maximum context:
      1. dumpsys window → foreground package/activity
      2. uiautomator dump → UI hierarchy + focused element
      3. dumpsys activity top → fragment names
      4. dumpsys window → window title
      5. logcat events (passed in)

    Independent ADB calls are parallelized via ``asyncio.gather()``.
    The ``dumpsys window displays`` output is fetched once and shared
    between foreground-activity and window-title parsing.

    Returns
    -------
    tuple[ScreenState, ReadTimings]
        The screen state and per-stage timing breakdown.
    """
    timings = ReadTimings()
    t_total = time.monotonic()

    # ── Phase 1: shared dumpsys (one ADB call, reused below) ──────
    t0 = time.monotonic()
    window_displays = (await adb_manager.shell(serial, "dumpsys window displays")).stdout
    package, activity = await read_foreground_activity(serial, window_dumpsys_output=window_displays)
    timings.foreground_ms = int((time.monotonic() - t0) * 1000)

    # ── Phase 2: parallel independent reads ───────────────────────
    #   - hierarchy (if requested): uiautomator dump + cat XML
    #   - fragments: dumpsys activity top
    #   - window_title: parsed from shared output (0 ADB calls usually)

    elements: List[UIElement] = []
    xml_root: Optional[ET.Element] = None
    focused: Optional[UIElement] = None
    fragments: List[str] = []
    window_title: str = ""

    async def _timed_hierarchy() -> Tuple[List[UIElement], Optional[ET.Element]]:
        t = time.monotonic()
        result = await read_ui_hierarchy(serial)
        timings.hierarchy_ms = int((time.monotonic() - t) * 1000)
        return result

    async def _timed_fragments() -> List[str]:
        t = time.monotonic()
        result = await read_fragments(serial)
        timings.fragments_ms = int((time.monotonic() - t) * 1000)
        return result

    async def _timed_window_title() -> str:
        t = time.monotonic()
        result = await read_window_title(serial, window_dumpsys_output=window_displays)
        timings.window_title_ms = int((time.monotonic() - t) * 1000)
        return result

    if include_hierarchy:
        (elements, xml_root), fragments, window_title = await asyncio.gather(
            _timed_hierarchy(),
            _timed_fragments(),
            _timed_window_title(),
        )
        focused = _find_focused(elements)
    else:
        fragments, window_title = await asyncio.gather(
            _timed_fragments(),
            _timed_window_title(),
        )

    # Build human-readable focused context from ALL signals
    focused_context = _build_focused_context(
        xml_root=xml_root,
        focused_el=focused,
        fragments=fragments,
        window_title=window_title,
        activity=activity,
        recent_events=recent_events,
    )

    timings.total_ms = int((time.monotonic() - t_total) * 1000)

    return ScreenState(
        package=package,
        activity=activity,
        ui_elements=elements,
        focused_element=focused,
        focused_context=focused_context,
        window_title=window_title,
        fragments=fragments,
        recent_events=recent_events or [],
        timestamp=datetime.now(timezone.utc).isoformat(),
    ), timings


async def read_screen_state_minimal(
    serial: str,
    recent_events: Optional[List[LogcatEvent]] = None,
) -> tuple[ScreenState, ReadTimings]:
    """Lightweight ADB read: foreground activity + fragments only.

    Skips the expensive uiautomator hierarchy dump.  Used by the
    vision-first fast path when the cache already knows what is on
    screen and we only need package/activity for the navigation graph.

    Returns
    -------
    tuple[ScreenState, ReadTimings]
        Minimal screen state (empty ``ui_elements``) and timings.
    """
    timings = ReadTimings()
    t_total = time.monotonic()

    # Shared dumpsys — one ADB call
    t0 = time.monotonic()
    window_displays = (await adb_manager.shell(serial, "dumpsys window displays")).stdout
    package, activity = await read_foreground_activity(serial, window_dumpsys_output=window_displays)
    timings.foreground_ms = int((time.monotonic() - t0) * 1000)

    # Fragments in parallel with window_title (usually 0ms from shared output)
    async def _timed_fragments() -> List[str]:
        t = time.monotonic()
        result = await read_fragments(serial)
        timings.fragments_ms = int((time.monotonic() - t) * 1000)
        return result

    async def _timed_window_title() -> str:
        t = time.monotonic()
        result = await read_window_title(serial, window_dumpsys_output=window_displays)
        timings.window_title_ms = int((time.monotonic() - t) * 1000)
        return result

    fragments, window_title = await asyncio.gather(
        _timed_fragments(),
        _timed_window_title(),
    )

    focused_context = _build_focused_context(
        xml_root=None,
        focused_el=None,
        fragments=fragments,
        window_title=window_title,
        activity=activity,
        recent_events=recent_events,
    )

    timings.total_ms = int((time.monotonic() - t_total) * 1000)

    return ScreenState(
        package=package,
        activity=activity,
        ui_elements=[],
        focused_element=None,
        focused_context=focused_context,
        window_title=window_title,
        fragments=fragments,
        recent_events=recent_events or [],
        timestamp=datetime.now(timezone.utc).isoformat(),
    ), timings


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
        focused_context="focused on: Home | in: menu_bar | siblings: [Apps, Settings] | position: 1/3 | fragments: [HomeFragment] | activity: HomeActivity",
        window_title="com.example.stb/com.example.stb.HomeActivity",
        fragments=["HomeFragment"],
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
