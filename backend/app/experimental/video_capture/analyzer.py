"""EXPERIMENTAL_VIDEO_CAPTURE — Vision-based STB UI focus analysis.

Captures the current HDMI frame and sends it to an AI vision model
(Anthropic Claude or OpenAI GPT) to identify:
- Screen type (home, settings, player, etc.)
- Which UI element currently has focus/highlight
- Navigation path/breadcrumb
- Visible text summary

Both providers accept JPEG images via base64-encoded content blocks.
"""

import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from ...config import settings
from . import streamer

logger = logging.getLogger("wifry.experimental.video_capture")


# ── Models ────────────────────────────────────────────────────────────


class FocusedElement(BaseModel):
    """EXPERIMENTAL_VIDEO_CAPTURE — Detected focused UI element."""
    element_type: str = ""   # menu_item, button, tile, card, tab, input, etc.
    label: str = ""          # Visible text of focused element
    position: str = ""       # Spatial description ("3rd item in left sidebar")
    confidence: str = "low"  # high, medium, low


class FrameAnalysisResult(BaseModel):
    """EXPERIMENTAL_VIDEO_CAPTURE — Structured result from vision analysis."""
    screen_type: str = "unknown"                    # home, settings, app_launcher, content_details, player, search, menu, error, loading, unknown
    screen_title: Optional[str] = None              # Header/title if visible
    focused_element: Optional[FocusedElement] = None
    navigation_path: Optional[list[str]] = None     # Breadcrumb: ["Home", "Settings", "Network"]
    visible_text_summary: str = ""
    raw_description: str = ""
    provider: str = ""
    model: str = ""
    tokens_used: int = 0
    analyzed_at: str = ""
    error: Optional[str] = None


# ── Prompts ───────────────────────────────────────────────────────────


_SYSTEM_PROMPT = """\
You are a set-top box UI analyst. You receive screenshots from an HDMI capture \
of a set-top box (e.g., Roku, Apple TV, Fire TV, Android TV, cable box). \
Your job is to identify the current screen state and which UI element has \
focus or is highlighted.

IMPORTANT: Focus ONLY on the active foreground panel or dialog. Ignore any \
dimmed, grayed-out, or partially visible background content behind the active \
UI layer. Only report text, elements, and navigation paths from the \
currently active panel.

Respond with valid JSON matching the schema below. Be precise about what you \
see. If you cannot determine something with confidence, say so rather than \
guessing."""

_USER_PROMPT = """\
Analyze this set-top box screenshot and identify:

1. **screen_type**: What type of screen is this? One of: home, settings, \
app_launcher, content_details, player, search, menu, error, loading, unknown
2. **screen_title**: Any visible title or header text for this screen
3. **focused_element**: Which UI element currently has focus/highlight? Look for:
   - Highlighted/selected item (brighter border, different background, enlarged)
   - Cursor or selection indicator
   - Active/focused state styling
   Describe its type, visible label text, and position on screen.
4. **navigation_path**: If you can determine the navigation breadcrumb \
(e.g., Settings > Network > WiFi), provide it as a list
5. **visible_text_summary**: Brief summary of key readable text on screen

Respond with JSON only:
{
  "screen_type": "...",
  "screen_title": "...",
  "focused_element": {
    "element_type": "...",
    "label": "...",
    "position": "...",
    "confidence": "high|medium|low"
  },
  "navigation_path": ["...", "..."],
  "visible_text_summary": "...",
  "raw_description": "..."
}"""


# ── Public API ────────────────────────────────────────────────────────


def get_snapshot() -> Optional[bytes]:
    """EXPERIMENTAL_VIDEO_CAPTURE — Get the latest JPEG frame from the stream."""
    return streamer.get_latest_frame()


def get_default_prompts() -> tuple[str, str]:
    """Return the default (system_prompt, user_prompt) pair."""
    return _SYSTEM_PROMPT, _USER_PROMPT


async def analyze_frame(
    frame_jpeg: bytes,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
) -> FrameAnalysisResult:
    """EXPERIMENTAL_VIDEO_CAPTURE — Send a frame to AI vision and parse the result.

    Args:
        frame_jpeg: Raw JPEG bytes of the frame to analyze.
        provider: "anthropic" or "openai". Defaults to settings.ai_provider.
        model: Model override. Defaults to settings.ai_model or provider default.
        system_prompt: Override the default system prompt.
        user_prompt: Override the default user prompt.

    Returns:
        FrameAnalysisResult with structured analysis or error details.
    """
    provider = provider or settings.ai_provider
    analyzed_at = datetime.now(timezone.utc).isoformat()
    sys_prompt = system_prompt or _SYSTEM_PROMPT
    usr_prompt = user_prompt or _USER_PROMPT

    if settings.mock_mode:
        logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Mock analysis")
        return _mock_analyze(provider, analyzed_at)

    b64_frame = base64.b64encode(frame_jpeg).decode("ascii")

    try:
        if provider == "anthropic":
            return await _analyze_anthropic(b64_frame, model, analyzed_at, sys_prompt, usr_prompt)
        else:
            return await _analyze_openai(b64_frame, model, analyzed_at, sys_prompt, usr_prompt)
    except Exception as e:
        logger.exception("[EXPERIMENTAL_VIDEO_CAPTURE] Vision analysis failed")
        return FrameAnalysisResult(
            provider=provider,
            model=model or "",
            analyzed_at=analyzed_at,
            error=str(e),
        )


# ── Provider Implementations ─────────────────────────────────────────


async def _analyze_anthropic(
    b64_frame: str,
    model_override: Optional[str],
    analyzed_at: str,
    sys_prompt: str = _SYSTEM_PROMPT,
    usr_prompt: str = _USER_PROMPT,
) -> FrameAnalysisResult:
    """EXPERIMENTAL_VIDEO_CAPTURE — Anthropic Claude vision analysis."""
    import anthropic

    model = model_override or settings.ai_model or "claude-sonnet-4-20250514"
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Analyzing frame with Anthropic %s", model)

    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=sys_prompt,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64_frame,
                    },
                },
                {"type": "text", "text": usr_prompt},
            ],
        }],
    )

    content = response.content[0].text if response.content else ""
    tokens = (response.usage.input_tokens + response.usage.output_tokens) if response.usage else 0

    logger.info(
        "[EXPERIMENTAL_VIDEO_CAPTURE] Anthropic response: %d tokens, %d chars",
        tokens, len(content),
    )

    return _parse_response(content, "anthropic", model, tokens, analyzed_at)


async def _analyze_openai(
    b64_frame: str,
    model_override: Optional[str],
    analyzed_at: str,
    sys_prompt: str = _SYSTEM_PROMPT,
    usr_prompt: str = _USER_PROMPT,
) -> FrameAnalysisResult:
    """EXPERIMENTAL_VIDEO_CAPTURE — OpenAI GPT vision analysis."""
    import openai

    model = model_override or settings.ai_model or "gpt-5.4-mini"
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    logger.info("[EXPERIMENTAL_VIDEO_CAPTURE] Analyzing frame with OpenAI %s", model)

    response = await client.chat.completions.create(
        model=model,
        max_completion_tokens=1024,
        messages=[
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": usr_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_frame}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
    )

    choice = response.choices[0]
    content = choice.message.content or ""
    tokens = response.usage.total_tokens if response.usage else 0

    logger.info(
        "[EXPERIMENTAL_VIDEO_CAPTURE] OpenAI response: %d tokens, %d chars, finish=%s",
        tokens, len(content), choice.finish_reason,
    )

    return _parse_response(content, "openai", model, tokens, analyzed_at)


# ── Response Parsing ──────────────────────────────────────────────────


def _parse_response(
    content: str,
    provider: str,
    model: str,
    tokens: int,
    analyzed_at: str,
) -> FrameAnalysisResult:
    """EXPERIMENTAL_VIDEO_CAPTURE — Parse AI JSON response into FrameAnalysisResult."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("[EXPERIMENTAL_VIDEO_CAPTURE] Failed to parse JSON: %s", e)
        return FrameAnalysisResult(
            raw_description=content[:500],
            provider=provider,
            model=model,
            tokens_used=tokens,
            analyzed_at=analyzed_at,
            error=f"Failed to parse AI response as JSON: {e}",
        )

    focused = None
    if data.get("focused_element"):
        fe = data["focused_element"]
        focused = FocusedElement(
            element_type=fe.get("element_type", ""),
            label=fe.get("label", ""),
            position=fe.get("position", ""),
            confidence=fe.get("confidence", "low"),
        )

    return FrameAnalysisResult(
        screen_type=data.get("screen_type", "unknown"),
        screen_title=data.get("screen_title"),
        focused_element=focused,
        navigation_path=data.get("navigation_path"),
        visible_text_summary=data.get("visible_text_summary", ""),
        raw_description=data.get("raw_description", ""),
        provider=provider,
        model=model,
        tokens_used=tokens,
        analyzed_at=analyzed_at,
    )


# ── Mock ──────────────────────────────────────────────────────────────


def _mock_analyze(provider: str, analyzed_at: str) -> FrameAnalysisResult:
    """EXPERIMENTAL_VIDEO_CAPTURE — Synthetic result for dev/CI."""
    return FrameAnalysisResult(
        screen_type="home",
        screen_title="Home",
        focused_element=FocusedElement(
            element_type="tile",
            label="Netflix",
            position="first row, 3rd tile",
            confidence="high",
        ),
        navigation_path=["Home"],
        visible_text_summary=(
            "Home screen showing app tiles: Netflix, YouTube, Disney+, HBO Max. "
            "Top bar shows time 8:42 PM and WiFi icon."
        ),
        raw_description=(
            "The STB home screen is displayed with a grid of application tiles. "
            "Netflix is highlighted with a white border, indicating it has focus."
        ),
        provider=provider,
        model="mock-vision",
        tokens_used=1234,
        analyzed_at=analyzed_at,
    )
