"""AI-powered packet capture analysis.

Supports Anthropic Claude and OpenAI GPT as configurable backends.
Pre-processes tshark statistics into structured prompts, then sends
to the AI for natural-language analysis.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import settings
from ..models.capture import AnalysisIssue, AnalysisRequest, AnalysisResult
from . import capture as capture_service

logger = logging.getLogger(__name__)

# System prompt for AI analysis
SYSTEM_PROMPT = """You are a network analysis expert. You are given packet capture statistics from tshark and must analyze them for network issues.

Your analysis should:
1. Identify problems (retransmissions, high latency, packet loss, DNS issues, protocol errors)
2. Rate each issue by severity: critical, high, medium, low
3. Categorize issues: retransmissions, latency, errors, dns, throughput, security
4. Identify affected network flows
5. Provide actionable recommendations

Respond with valid JSON matching this schema:
{
  "summary": "1-3 sentence overview of capture health",
  "issues": [
    {
      "severity": "high",
      "category": "retransmissions",
      "description": "Detailed description of the issue",
      "affected_flows": ["192.168.4.10:54321 → 104.16.132.229:443"],
      "recommendation": "What to do about it"
    }
  ],
  "statistics": {
    "total_packets": 1000,
    "retransmission_rate_pct": 3.2,
    "unique_hosts": 5,
    "protocols": {"TCP": 900, "UDP": 60, "ICMP": 20},
    "top_talkers": [{"host": "192.168.4.10", "bytes": 550000}]
  }
}"""


def _build_analysis_prompt(stats: Dict[str, Any], request: AnalysisRequest) -> str:
    """Build the user prompt from capture stats and analysis request."""
    parts = [request.prompt, "", "Focus areas: " + ", ".join(request.focus), ""]

    for key, value in stats.items():
        label = key.replace("_", " ").title()
        parts.append(f"=== {label} ===")
        if isinstance(value, str):
            # Truncate very long outputs
            parts.append(value[:3000])
        else:
            parts.append(json.dumps(value, indent=2)[:3000])
        parts.append("")

    return "\n".join(parts)


async def analyze_capture(
    capture_id: str,
    request: AnalysisRequest,
) -> AnalysisResult:
    """Run AI analysis on a capture.

    1. Extract stats from pcap via tshark
    2. Build prompt
    3. Send to AI provider
    4. Parse structured response
    5. Save and return results
    """
    # Get capture stats
    stats = await capture_service.get_capture_stats(capture_id)
    if not stats:
        return AnalysisResult(
            capture_id=capture_id,
            summary="No capture data available for analysis.",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )

    provider = request.provider or settings.ai_provider
    prompt = _build_analysis_prompt(stats, request)

    if settings.mock_mode or (not settings.anthropic_api_key and not settings.openai_api_key):
        result = _mock_analysis(capture_id, provider)
    elif provider == "anthropic":
        result = await _analyze_with_anthropic(capture_id, prompt)
    elif provider == "openai":
        result = await _analyze_with_openai(capture_id, prompt)
    else:
        raise ValueError(f"Unknown AI provider: {provider}")

    # Save analysis result
    _save_analysis(capture_id, result)
    return result


async def _analyze_with_anthropic(capture_id: str, prompt: str) -> AnalysisResult:
    """Send analysis to Anthropic Claude API."""
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        model = "claude-sonnet-4-20250514"

        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens

        return _parse_ai_response(capture_id, content, "anthropic", model, tokens)

    except Exception as e:
        logger.error("Anthropic analysis failed: %s", e)
        return AnalysisResult(
            capture_id=capture_id,
            summary=f"Analysis failed: {e}",
            provider="anthropic",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )


async def _analyze_with_openai(capture_id: str, prompt: str) -> AnalysisResult:
    """Send analysis to OpenAI API."""
    try:
        import openai

        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        model = "gpt-4o"

        response = await client.chat.completions.create(
            model=model,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0

        return _parse_ai_response(capture_id, content, "openai", model, tokens)

    except Exception as e:
        logger.error("OpenAI analysis failed: %s", e)
        return AnalysisResult(
            capture_id=capture_id,
            summary=f"Analysis failed: {e}",
            provider="openai",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )


def _parse_ai_response(
    capture_id: str,
    content: str,
    provider: str,
    model: str,
    tokens: int,
) -> AnalysisResult:
    """Parse the AI JSON response into an AnalysisResult."""
    try:
        # Extract JSON from response (handle markdown code blocks)
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1])

        data = json.loads(text)

        issues = [
            AnalysisIssue(**issue)
            for issue in data.get("issues", [])
        ]

        return AnalysisResult(
            capture_id=capture_id,
            summary=data.get("summary", "Analysis complete."),
            issues=issues,
            statistics=data.get("statistics", {}),
            provider=provider,
            model=model,
            tokens_used=tokens,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Failed to parse AI response as JSON: %s", e)
        return AnalysisResult(
            capture_id=capture_id,
            summary=content[:500],
            provider=provider,
            model=model,
            tokens_used=tokens,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )


def _save_analysis(capture_id: str, result: AnalysisResult) -> None:
    """Save analysis result to disk."""
    from . import capture as cap_svc
    path = cap_svc._captures_dir() / f"{capture_id}.analysis.json"
    path.write_text(result.model_dump_json(indent=2))


def get_analysis(capture_id: str) -> Optional[AnalysisResult]:
    """Load a previously saved analysis result."""
    path = capture_service._captures_dir() / f"{capture_id}.analysis.json"
    if path.exists():
        return AnalysisResult.model_validate_json(path.read_text())
    return None


def _mock_analysis(capture_id: str, provider: str) -> AnalysisResult:
    """Return mock analysis for development."""
    return AnalysisResult(
        capture_id=capture_id,
        summary=(
            "Capture shows moderate network health with some concerns. "
            "TCP retransmission rate of 3.2% detected between client and CDN, "
            "likely caused by wireless interference or congestion. "
            "DNS resolution times are normal."
        ),
        issues=[
            AnalysisIssue(
                severity="high",
                category="retransmissions",
                description=(
                    "TCP retransmission rate of 3.2% detected on the primary "
                    "CDN connection. This exceeds the recommended 1% threshold "
                    "and may cause ABR bitrate downswitching."
                ),
                affected_flows=["192.168.4.10:54321 -> 104.16.132.229:443"],
                recommendation=(
                    "Check WiFi signal strength and channel congestion. "
                    "Consider switching to 5GHz band or changing channel."
                ),
            ),
            AnalysisIssue(
                severity="medium",
                category="latency",
                description=(
                    "15 TCP duplicate ACKs observed, indicating occasional "
                    "out-of-order delivery. This is within acceptable range "
                    "but worth monitoring."
                ),
                affected_flows=["192.168.4.10:54321 -> 104.16.132.229:443"],
                recommendation="Monitor during peak usage hours.",
            ),
            AnalysisIssue(
                severity="low",
                category="dns",
                description=(
                    "3 DNS queries observed with normal response times (<50ms). "
                    "No DNS issues detected."
                ),
                affected_flows=[],
                recommendation="No action needed.",
            ),
        ],
        statistics={
            "total_packets": 1000,
            "retransmission_rate_pct": 3.2,
            "duplicate_acks": 15,
            "unique_hosts": 3,
            "protocols": {"TCP/TLS": 800, "UDP/DNS": 40, "ICMP": 20},
            "top_talkers": [
                {"host": "192.168.4.10", "bytes": 550000},
                {"host": "104.16.132.229", "bytes": 400000},
            ],
        },
        provider=provider,
        model="mock",
        tokens_used=0,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
    )
