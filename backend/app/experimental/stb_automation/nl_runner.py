"""STB_AUTOMATION — Natural language → test flow generation via AI.

Translates plain-English test descriptions into executable TestFlow
objects.  Uses the navigation model (if available) for realistic
navigation paths and the current screen state for context.

Supports iterative refinement: generate → review → refine → execute.

Provider abstraction follows the same pattern as ai_analyzer.py:
Anthropic Claude or OpenAI GPT, selected via settings.ai_provider.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from ...config import settings
from . import test_flows, vision_cache, vision_map
from .models import TestFlow, TestStep

logger = logging.getLogger("wifry.stb_automation.nl_runner")

# ── System Prompt ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an STB (Set-Top Box) test automation assistant.  Your job is to
translate natural-language test descriptions into structured test flows
that can be executed on an Android-based STB via ADB key presses.

Available actions (keycodes): up, down, left, right, enter, back, home,
menu, play_pause, fast_forward, rewind, volume_up, volume_down, mute,
power, 0-9 (number keys).

Special pseudo-actions:
- "wait" — pause for a duration (set wait_ms)
- "assert" — verify the screen matches expectations

Assertion fields (use on any step, not just "assert"):
- expected_activity: Android activity name to match
- expected_screen_type: Vision screen type ("home", "settings", "player", etc.)
- expected_focused_label: Vision focused element label (e.g., "Device Preferences")

PREFER vision-based assertions (expected_screen_type, expected_focused_label)
over activity-based ones. Vision assertions work on all STBs including NAF
(non-accessible framework) devices.

You MUST respond with valid JSON matching this schema:
{
  "name": "<short descriptive flow name>",
  "description": "<what this test verifies>",
  "steps": [
    {
      "action": "<keycode or wait or assert>",
      "description": "<human-readable step description>",
      "expected_activity": "<optional: Android activity after action>",
      "expected_screen_type": "<optional: vision screen type>",
      "expected_focused_label": "<optional: focused element label>",
      "wait_ms": <optional: milliseconds to wait, default 0>,
      "collect_diagnostics": <optional: true to snapshot diagnostics>
    }
  ]
}

Guidelines:
- Be specific: include exact key sequences for navigation.
- Use "enter" to select/confirm, "back" to go up one level.
- Insert brief waits (500-2000ms) after actions that trigger loading screens.
- Add assert steps at critical checkpoints to verify correct screen.
- If a navigation model is provided, use known paths between screens.
- If the user mentions network impairments (packet loss, delay, etc.),
  note them in step descriptions but do NOT generate API calls — the
  test runner handles impairment orchestration separately.
- Keep flows focused: 5-30 steps for typical scenarios.
- Always start from a known state (home screen) unless told otherwise.

Respond ONLY with the JSON object, no markdown fences, no commentary.\
"""


# ── Public API ────────────────────────────────────────────────────────


async def generate_flow(
    prompt: str,
    serial: str,
    device_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> TestFlow:
    """Generate a TestFlow from a natural-language description.

    Args:
        prompt: Plain-English test description.
        serial: ADB device serial for the generated flow.
        device_id: Optional device ID for nav model lookup.
        provider: AI provider override ("anthropic" or "openai").
        model: Model name override.

    Returns:
        A new TestFlow with source="nl_generated".
    """
    user_prompt = _build_user_prompt(prompt, device_id)
    ai_provider = provider or settings.ai_provider or "anthropic"

    if settings.mock_mode or (not settings.anthropic_api_key and not settings.openai_api_key):
        return _mock_generate(prompt, serial)

    if ai_provider == "anthropic":
        content, tokens = await _call_anthropic(user_prompt, model)
    elif ai_provider == "openai":
        content, tokens = await _call_openai(user_prompt, model)
    else:
        raise ValueError(f"Unknown AI provider: {ai_provider}")

    logger.info(
        "[STB_AUTOMATION] NL generate: provider=%s tokens=%d prompt_len=%d",
        ai_provider, tokens, len(prompt),
    )

    return _parse_flow_response(content, serial, source_prompt=prompt)


async def refine_flow(
    flow_id: str,
    refinement_prompt: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> TestFlow:
    """Refine an existing flow with a follow-up instruction.

    Sends the current flow JSON + the refinement prompt to the AI
    and replaces the flow steps with the updated result.
    """
    flow = test_flows.get_flow(flow_id)
    if flow is None:
        raise ValueError(f"Flow '{flow_id}' not found")

    user_prompt = _build_refine_prompt(flow, refinement_prompt)
    ai_provider = provider or settings.ai_provider or "anthropic"

    if settings.mock_mode or (not settings.anthropic_api_key and not settings.openai_api_key):
        # In mock mode, just return the existing flow unchanged
        return flow

    if ai_provider == "anthropic":
        content, tokens = await _call_anthropic(user_prompt, model)
    elif ai_provider == "openai":
        content, tokens = await _call_openai(user_prompt, model)
    else:
        raise ValueError(f"Unknown AI provider: {ai_provider}")

    logger.info(
        "[STB_AUTOMATION] NL refine: flow=%s provider=%s tokens=%d",
        flow_id, ai_provider, tokens,
    )

    # Parse response and update the existing flow
    parsed = _parse_json_response(content)
    steps = [TestStep(**s) for s in parsed.get("steps", [])]

    updates = {
        "steps": steps,
        "description": parsed.get("description", flow.description),
    }
    if "name" in parsed:
        updates["name"] = parsed["name"]

    updated = test_flows.update_flow(flow_id, updates)
    if updated is None:
        raise ValueError(f"Failed to update flow '{flow_id}'")

    return updated


# ── Vision Enrichment ─────────────────────────────────────────────────


async def enrich_state_with_vision(serial: str) -> dict:
    """Add vision analysis to the current screen state.

    Captures an HDMI frame (if the streamer is running) and runs
    AI vision analysis to identify screen type, focused element, etc.
    Returns the enrichment data or an error explanation.
    """
    try:
        from ..video_capture import analyzer, streamer

        if not streamer.is_running():
            return {"error": "HDMI streamer is not running", "enriched": False}

        frame = streamer.get_latest_frame()
        if frame is None:
            return {"error": "No HDMI frame available", "enriched": False}

        result = await analyzer.analyze_frame(frame_jpeg=frame)
        return {
            "enriched": True,
            "screen_type": result.screen_type,
            "screen_title": result.screen_title,
            "focused_element": result.focused_element.model_dump() if result.focused_element else None,
            "navigation_path": result.navigation_path,
            "visible_text_summary": result.visible_text_summary,
            "provider": result.provider,
            "model": result.model,
            "tokens_used": result.tokens_used,
        }

    except ImportError:
        return {"error": "Video capture module not available", "enriched": False}
    except Exception as e:
        logger.error("[STB_AUTOMATION] Vision enrichment failed: %s", e)
        return {"error": str(e), "enriched": False}


# ── Prompt Builders ───────────────────────────────────────────────────


def _build_user_prompt(prompt: str, device_id: Optional[str] = None) -> str:
    """Build the user message with all available device context."""
    parts = [f"Generate a test flow for the following scenario:\n\n{prompt}"]

    # Current device state
    current_state = _format_current_state()
    if current_state:
        parts.append(current_state)

    # Vision map — unified menu structure with exact key sequences
    map_context = _format_vision_map_context()
    if map_context:
        parts.append(map_context)

    # Known screen descriptions from vision cache
    vision_context = _format_vision_cache_context()
    if vision_context:
        parts.append(vision_context)

    return "\n\n".join(parts)


def _build_refine_prompt(flow: TestFlow, refinement: str) -> str:
    """Build the user message for flow refinement."""
    flow_json = json.dumps(
        {
            "name": flow.name,
            "description": flow.description,
            "steps": [s.model_dump(exclude_none=True) for s in flow.steps],
        },
        indent=2,
    )

    return (
        f"Here is an existing test flow:\n\n{flow_json}\n\n"
        f"Please modify this flow according to the following instruction:\n\n{refinement}\n\n"
        f"Return the complete updated flow JSON (same schema as the original)."
    )


    # _format_nav_model_context removed — absorbed into _format_vision_map_context

    return "\n".join(parts)


def _format_current_state() -> str:
    """Format the current screen state from the last vision result."""
    # Get the last known focused label from any screen
    s = vision_map.stats()
    if s["total_entries"] == 0:
        return ""

    # Find the most recently updated screen
    screens = vision_map.get_all_screens()
    if not screens:
        return ""

    # Report current state from last_focused tracking
    parts = ["CURRENT DEVICE STATE:"]
    for screen in screens:
        focused = vision_map.get_last_focused(screen["screen_key"])
        if focused:
            parts.append(f"  Screen: {screen['screen_key']}")
            parts.append(f"  Currently focused on: {focused}")
            break

    return "\n".join(parts) if len(parts) > 1 else ""


def _format_vision_map_context() -> str:
    """Format the UI map as a readable menu structure.

    Builds a tree showing how to navigate between menu items using
    exact key presses. This is the primary context for generating
    accurate test flows.
    """
    screens = vision_map.get_all_screens()
    if not screens:
        return ""

    parts = [
        "LEARNED MENU MAP (verified by observation):",
        "Use these EXACT key sequences — they are confirmed to work on this device.",
    ]

    for screen_summary in screens[:10]:
        screen_key = screen_summary["screen_key"]
        entries = vision_map.get_screen_entries(screen_key)
        if not entries:
            continue

        # Extract a friendly screen name from the activity
        activity = screen_key.split("/")[-1] if "/" in screen_key else screen_key
        parts.append(f"\n--- {activity} ---")

        # Build ordered menu items by following down/right chains
        # Group transitions by action type
        down_chain: dict[str, str] = {}  # from → to (via down)
        up_chain: dict[str, str] = {}  # from → to (via up)
        left_chain: dict[str, str] = {}
        right_chain: dict[str, str] = {}
        enter_targets: dict[str, str] = {}  # from → to (via enter)

        for e in entries:
            if e.confidence < 0.3:
                continue
            if e.action == "down":
                down_chain[e.from_focused] = e.to_focused
            elif e.action == "up":
                up_chain[e.from_focused] = e.to_focused
            elif e.action == "right":
                right_chain[e.from_focused] = e.to_focused
            elif e.action == "left":
                left_chain[e.from_focused] = e.to_focused
            elif e.action == "enter":
                enter_targets[e.from_focused] = e.to_focused

        # Build vertical menu order from down chain
        if down_chain:
            # Find the top item (not a target of any down)
            all_targets = set(down_chain.values())
            top_items = [k for k in down_chain if k not in all_targets]
            if top_items:
                parts.append("  Vertical menu (navigate with up/down):")
                current = top_items[0]
                idx = 1
                visited = set()
                while current and current not in visited:
                    visited.add(current)
                    enter_note = f" → [enter] opens: {enter_targets[current]}" if current in enter_targets else ""
                    parts.append(f"    {idx}. {current}{enter_note}")
                    current = down_chain.get(current)
                    idx += 1
                # Add last item if it's only a target
                if current and current not in visited:
                    enter_note = f" → [enter] opens: {enter_targets[current]}" if current in enter_targets else ""
                    parts.append(f"    {idx}. {current}{enter_note}")

        # Build horizontal menu order from right chain
        if right_chain:
            all_targets = set(right_chain.values())
            left_items = [k for k in right_chain if k not in all_targets]
            if left_items:
                parts.append("  Horizontal menu (navigate with left/right):")
                current = left_items[0]
                items = []
                visited = set()
                while current and current not in visited:
                    visited.add(current)
                    items.append(current)
                    current = right_chain.get(current)
                if current and current not in visited:
                    items.append(current)
                parts.append(f"    {' ↔ '.join(items)}")

    if len(parts) <= 2:
        return ""

    parts.append(
        "\nIMPORTANT: Use the exact menu item names and key sequences above. "
        "Count the number of 'down' presses needed from the top of a menu to "
        "reach the target item. For example, if 'Settings' is item #5, you "
        "need 4 'down' presses from the top."
    )
    return "\n".join(parts)


def _format_vision_cache_context() -> str:
    """Format known screen descriptions from the vision cache."""
    cache_items = vision_cache.items()
    if not cache_items:
        return ""

    parts = ["KNOWN SCREEN DESCRIPTIONS (from AI vision analysis):"]
    seen_types = set()

    for _key, analysis in cache_items[-15:]:  # Last 15 entries
        desc = f"{analysis.screen_type}: {analysis.screen_title or analysis.focused_label}"
        if desc not in seen_types:
            seen_types.add(desc)
            nav = " > ".join(analysis.navigation_path) if analysis.navigation_path else ""
            parts.append(f"  - {desc}" + (f" (nav: {nav})" if nav else ""))

    return "\n".join(parts) if len(parts) > 1 else ""


# ── AI Provider Calls ─────────────────────────────────────────────────


async def _call_anthropic(user_prompt: str, model_override: Optional[str] = None) -> tuple[str, int]:
    """Call Anthropic Claude API. Returns (content, tokens_used)."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    model = model_override or settings.ai_model or "claude-sonnet-4-20250514"

    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    content = response.content[0].text
    tokens = response.usage.input_tokens + response.usage.output_tokens
    return content, tokens


async def _call_openai(user_prompt: str, model_override: Optional[str] = None) -> tuple[str, int]:
    """Call OpenAI API. Returns (content, tokens_used)."""
    import openai

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    model = model_override or settings.ai_model or "gpt-5.4-mini"

    response = await client.chat.completions.create(
        model=model,
        max_completion_tokens=8192,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if response.usage else 0
    return content, tokens


# ── Response Parsing ──────────────────────────────────────────────────


def _parse_json_response(content: str) -> dict:
    """Parse JSON from AI response, handling markdown code fences."""
    text = content.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        end_idx = next(
            (i for i in range(len(lines) - 1, 0, -1) if lines[i].startswith("```")),
            len(lines) - 1,
        )
        text = "\n".join(lines[1:end_idx])

    return json.loads(text)


def _parse_flow_response(content: str, serial: str, source_prompt: str = "") -> TestFlow:
    """Parse AI response into a TestFlow."""
    try:
        data = _parse_json_response(content)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("[STB_AUTOMATION] Failed to parse NL response: %s", e)
        # Return a minimal flow with the error noted
        return test_flows.create_flow(
            name="NL Generation Error",
            serial=serial,
            description=f"Failed to parse AI response: {e}\n\nOriginal prompt: {source_prompt}",
            source="nl_generated",
        )

    steps = [TestStep(**s) for s in data.get("steps", [])]

    return test_flows.create_flow(
        name=data.get("name", "NL-Generated Flow"),
        serial=serial,
        description=data.get("description", source_prompt),
        steps=steps,
        source="nl_generated",
    )


# ── Mock ──────────────────────────────────────────────────────────────


def _mock_generate(prompt: str, serial: str) -> TestFlow:
    """Generate a mock flow for dev/CI when no AI key is available."""
    return test_flows.create_flow(
        name="Mock NL Flow",
        serial=serial,
        description=f"Mock flow generated from: {prompt}",
        steps=[
            TestStep(action="home", description="Start from home screen"),
            TestStep(action="down", description="Navigate down"),
            TestStep(action="enter", description="Select item"),
            TestStep(action="wait", wait_ms=2000, description="Wait for content to load"),
            TestStep(
                action="assert",
                description="Verify content screen",
                expected_activity="com.example/.ContentActivity",
            ),
            TestStep(action="back", description="Return to previous screen"),
        ],
        source="nl_generated",
    )
