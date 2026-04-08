"""AI-powered packet capture analysis — V2.

V2 changes per ai-analysis-framework.md and capture-v2-master-spec:
- Structured CaptureSummary JSON input (not raw tshark text)
- Pack-specific prompt templates with domain expertise
- Evidence-based AnalysisResultV2 output with citations + confidence
- Output validation: drop findings without evidence, enforce confidence rules
- Input guardrails: size limits, minimum packet threshold, rate limiting
- Domain sanitization to prevent prompt injection
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import settings
from ..models.analysis_packs import AnalysisPack, get_pack_config
from ..models.capture import (
    AnalysisIssue,
    AnalysisRequest,
    AnalysisResult,
    AnalysisResultV2,
    CaptureSummary,
    Confidence,
    EvidenceCitation,
    Finding,
    HealthBadge,
    InsufficientEvidenceNote,
)
from . import capture as capture_service

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MAX_INPUT_BYTES = 20480  # 20 KB max summary input
MIN_PACKETS_FOR_ANALYSIS = 10
MAX_FINDINGS = 10

# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are WiFry, an expert network diagnostics AI embedded in a Raspberry Pi 5 appliance.
You receive a structured JSON summary of a packet capture (CaptureSummary) and must produce evidence-based findings.

## Rules

1. **Evidence required**: Every finding MUST cite specific metrics from the input. No vague claims.
2. **Confidence levels**:
   - HIGH: 3+ corroborating metrics, clear causal chain
   - MEDIUM: 1-2 supporting metrics, plausible explanation
   - LOW: Indirect inference, pattern matching, limited data
3. **Severity levels**: critical, high, medium, low — based on user impact, not just metric values.
4. **Insufficient evidence**: If you cannot assess an area, say so explicitly in insufficient_evidence.
5. **Max 10 findings**: Focus on actionable issues, not noise.
6. **No hallucination**: Only reference data present in the input. Never invent metric values.
7. **Cross-reference**: Link related findings by ID (e.g., F1 relates to F3).

## Input Format

You receive a CaptureSummary JSON with:
- meta: capture metadata (duration, packet count, pack type)
- protocol_breakdown: protocol hierarchy with frame/byte counts
- tcp_health: retransmissions, RSTs, zero windows, dup ACKs
- conversations: top TCP/UDP flows by bytes
- dns: query/response stats, NXDOMAIN, SERVFAIL, latency
- throughput: per-second I/O stats with avg/max/min/CoV
- expert: tshark expert info entries
- icmp: echo request/reply, unreachable, TTL exceeded
- endpoints: IP endpoint traffic stats
- tls: handshake stats, versions, ciphers, failures
- interest: pre-identified anomalies and focus flows

## Output Format

Respond with valid JSON matching this exact schema:
{
  "summary": "1-3 sentence overview of capture health",
  "health_badge": "healthy|degraded|unhealthy|insufficient",
  "findings": [
    {
      "id": "F1",
      "title": "Short title",
      "severity": "high",
      "confidence": "high",
      "category": "retransmissions|latency|dns|tls|throughput|security|connectivity",
      "description": "Detailed description of what was observed and why it matters",
      "evidence": [
        {"metric": "tcp_health.retransmission_pct", "value": "3.2%", "context": "Exceeds 2% threshold"}
      ],
      "affected_flows": ["192.168.4.10:54321 → 104.16.132.229:443"],
      "likely_causes": ["WiFi interference", "Congestion on upstream link"],
      "next_steps": ["Check WiFi signal strength", "Run streaming pack for throughput analysis"],
      "cross_references": ["F2"]
    }
  ],
  "insufficient_evidence": [
    {"area": "dns_health", "reason": "No DNS traffic in capture (port 53 filtered)", "suggestion": "Run DNS pack without BPF filter"}
  ]
}"""

# ── Pack-Specific Prompt Templates ───────────────────────────────────────────

PACK_PROMPTS: Dict[str, str] = {
    "connectivity": """## Connectivity Check Analysis

Focus your analysis on general network health:
1. **Reachability**: Are all expected hosts reachable? Check ICMP unreachable messages.
2. **TCP health**: Retransmission rate, connection resets, zero windows.
3. **Latency**: Round-trip times from ICMP, TCP handshake timing.
4. **Packet loss indicators**: Gaps in sequence numbers, retransmission patterns.
5. **Protocol distribution**: Is the traffic mix expected?

Key thresholds:
- Retransmission rate > 2% = HIGH severity
- Retransmission rate > 0.5% = MEDIUM severity
- Any ICMP unreachable = HIGH severity
- Zero window events > 5 = HIGH severity
- Connection resets > 10 = MEDIUM severity""",

    "dns": """## DNS Deep Dive Analysis

Focus your analysis on DNS resolution health:
1. **Query success rate**: What percentage of queries get successful responses?
2. **NXDOMAIN patterns**: Are there misconfigured domains or typosquatting attempts?
3. **SERVFAIL responses**: Indicate upstream DNS server issues.
4. **Latency**: Average and max response times. >100ms is elevated, >200ms is high.
5. **Timeout detection**: Queries with no matching response.
6. **Query patterns**: Unusual query volumes or repeated queries to same domain.

Key thresholds:
- SERVFAIL count > 0 = HIGH severity
- Avg latency > 200ms = HIGH severity
- Avg latency > 100ms = MEDIUM severity
- NXDOMAIN > 5 = MEDIUM severity (check if expected)
- Timeout count > 0 = HIGH severity""",

    "https": """## HTTPS / Web Analysis

Focus your analysis on TLS and web traffic health:
1. **TLS handshake health**: Success rate, handshake times, version distribution.
2. **Connection setup**: Time from SYN to established connection.
3. **Certificate issues**: TLS alerts, handshake failures.
4. **Throughput per flow**: Are web requests completing in reasonable time?
5. **Retransmissions on HTTPS flows**: Impact on page load performance.

Key thresholds:
- TLS handshake failure > 0 = HIGH severity
- Avg handshake time > 500ms = HIGH severity
- Avg handshake time > 200ms = MEDIUM severity
- Retransmissions > 1% on HTTPS flows = MEDIUM severity""",

    "streaming": """## Streaming / Video Analysis

Focus your analysis on streaming QoE indicators:
1. **Throughput stability**: Coefficient of variation (CoV > 0.3 = unstable, > 0.5 = highly unstable).
2. **Throughput dips**: Intervals where throughput drops significantly below average.
3. **Retransmission impact**: Retransmissions during streaming cause buffering.
4. **Flow analysis**: Identify the primary streaming flow(s) and their health.
5. **Buffering risk**: Sustained throughput below typical ABR bitrate thresholds.

Key thresholds:
- Throughput CoV > 0.5 = HIGH severity (likely causes buffering)
- Throughput CoV > 0.3 = MEDIUM severity
- Retransmission rate > 1% = HIGH severity
- Min throughput < 500 Kbps = MEDIUM severity (below lowest ABR tier)

Note: Look for patterns in the throughput samples that indicate periodic congestion or interference.""",

    "security": """## Security Audit Analysis

Focus your analysis on security indicators:
1. **Unencrypted traffic**: What percentage of application traffic is unencrypted (HTTP, FTP, Telnet)?
2. **Unusual destinations**: Many unique destination IPs may indicate scanning or C2 communication.
3. **Port patterns**: Connections to unusual ports, rapid connection attempts (scan patterns).
4. **TLS version security**: Flag TLS 1.0/1.1 as deprecated.
5. **Connection reset patterns**: High RST count may indicate port scanning.
6. **DNS anomalies**: NXDOMAIN spikes may indicate DGA-based malware.

Key thresholds:
- Unencrypted traffic > 20% = MEDIUM severity
- Unique destinations > 50 = MEDIUM severity (investigate)
- Connection resets > 20 = MEDIUM severity (scan indicator)
- Any TLS 1.0/1.1 = MEDIUM severity""",

    "custom": """## Custom Capture Analysis

Analyze this capture comprehensively. Look for:
1. Protocol distribution and any anomalies
2. TCP health: retransmissions, resets, zero windows
3. Throughput patterns and stability
4. DNS issues if DNS traffic is present
5. Any security concerns
6. Expert info warnings and errors

Prioritize findings by user impact and actionability.""",
}


# ── Sanitization ─────────────────────────────────────────────────────────────

def _sanitize_domain(domain: str) -> str:
    """Sanitize domain names to prevent prompt injection."""
    return re.sub(r"[^a-zA-Z0-9.\-_]", "", domain)[:253]


def _sanitize_summary_input(summary_json: str) -> str:
    """Sanitize the summary JSON to prevent prompt injection via captured data."""
    # Remove any strings that look like prompt injection attempts
    # This is a defense-in-depth measure
    sanitized = summary_json
    for pattern in [
        r"ignore\s+(?:previous|above)\s+instructions",
        r"you\s+are\s+now\s+(?:a|an)\s+",
        r"system\s*:\s*",
        r"<\|im_start\|>",
        r"<\|im_end\|>",
    ]:
        sanitized = re.sub(pattern, "[SANITIZED]", sanitized, flags=re.IGNORECASE)
    return sanitized


# ── Main Analysis Entry Point ────────────────────────────────────────────────

async def analyze_capture(
    capture_id: str,
    request: AnalysisRequest,
) -> AnalysisResultV2:
    """Run AI analysis on a capture using v2 pipeline.

    1. Load CaptureSummary (or generate if missing)
    2. Build structured prompt with pack template
    3. Send to AI provider
    4. Parse and validate response
    5. Save and return results
    """
    # Load or generate summary
    summary = capture_service.get_summary(capture_id)
    if not summary:
        # Try to generate summary on-the-fly
        info = capture_service.get_capture(capture_id)
        if info and info.pcap_path:
            from . import capture_stats
            from ..models.capture import CaptureMeta
            meta = CaptureMeta(
                capture_id=capture_id,
                pack=info.pack,
                interface=info.interface,
                total_packets=info.packet_count,
                total_bytes=info.file_size_bytes,
            )
            summary = await capture_stats.generate_summary(
                capture_id, info.pcap_path, info.pack, meta,
            )

    if not summary:
        result = AnalysisResultV2(
            capture_id=capture_id,
            summary="No capture data available for analysis.",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )
        _save_analysis_v2(capture_id, result)
        return result

    # Input guardrails
    if summary.meta.total_packets < MIN_PACKETS_FOR_ANALYSIS:
        result = AnalysisResultV2(
            capture_id=capture_id,
            summary=f"Capture contains only {summary.meta.total_packets} packets — insufficient for meaningful analysis. Try a longer capture.",
            health_badge=HealthBadge.INSUFFICIENT,
            insufficient_evidence=[
                InsufficientEvidenceNote(
                    area="all",
                    reason=f"Only {summary.meta.total_packets} packets captured (minimum {MIN_PACKETS_FOR_ANALYSIS})",
                    suggestion="Run a longer capture or use a less restrictive BPF filter",
                )
            ],
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )
        _save_analysis_v2(capture_id, result)
        return result

    # Determine pack
    pack = request.pack or (summary.meta.pack if summary.meta else "custom")

    provider = request.provider or settings.ai_provider

    if settings.mock_mode:
        result = _mock_analysis_v2(capture_id, pack, provider)
    elif not settings.anthropic_api_key and not settings.openai_api_key:
        result = AnalysisResultV2(
            capture_id=capture_id,
            pack=pack,
            provider="none",
            model="none",
            summary="AI analysis requires an API key. Go to System > App Settings to configure your Anthropic or OpenAI API key.",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )
    else:
        # Build prompt
        prompt = _build_v2_prompt(summary, pack, request)
        # Model priority: explicit request > saved setting > provider default
        model_override = request.model or settings.ai_model or None

        if provider == "anthropic":
            result = await _analyze_with_anthropic_v2(capture_id, pack, prompt, model_override)
        elif provider == "openai":
            result = await _analyze_with_openai_v2(capture_id, pack, prompt, model_override)
        else:
            raise ValueError(f"Unknown AI provider: {provider}")

    # Save result
    _save_analysis_v2(capture_id, result)

    # Update capture metadata
    info = capture_service.get_capture(capture_id)
    if info:
        info.has_analysis = True
        capture_service._captures[capture_id] = info
        capture_service._save_metadata(info)

    return result


def _build_v2_prompt(summary: CaptureSummary, pack: str, request: AnalysisRequest) -> str:
    """Build the structured user prompt from CaptureSummary and pack template."""
    parts = []

    # Pack-specific context
    pack_prompt = PACK_PROMPTS.get(pack, PACK_PROMPTS["custom"])
    parts.append(pack_prompt)
    parts.append("")

    # Pre-identified issues from interest detection
    if summary.interest and summary.interest.anomaly_flags:
        parts.append("## Pre-Identified Anomalies")
        for flag in summary.interest.anomaly_flags:
            parts.append(f"- [{flag.severity.upper()}] {flag.label}: {flag.metric} = {flag.value} (threshold: {flag.threshold})")
        parts.append("")

    if summary.interest and summary.interest.focus_flows:
        parts.append("## Focus Flows")
        for flow in summary.interest.focus_flows:
            parts.append(f"- {flow.src} → {flow.dst}: {flow.reason}")
        parts.append("")

    if summary.interest and summary.interest.interest_windows:
        parts.append("## Interesting Time Windows")
        for window in summary.interest.interest_windows:
            parts.append(f"- {window.start_secs:.1f}s–{window.end_secs:.1f}s: {window.reason}")
        parts.append("")

    # The actual data
    parts.append("## CaptureSummary Data")
    summary_json = summary.model_dump_json(indent=2)

    # Enforce input size limit
    if len(summary_json) > MAX_INPUT_BYTES:
        # Truncate conversations and endpoints first
        trimmed = summary.model_copy()
        trimmed.conversations = trimmed.conversations[:10]
        trimmed.endpoints = trimmed.endpoints[:15]
        if trimmed.throughput:
            trimmed.throughput.samples = trimmed.throughput.samples[:60]
        summary_json = trimmed.model_dump_json(indent=2)

    summary_json = _sanitize_summary_input(summary_json)
    parts.append(summary_json)

    return "\n".join(parts)


# ── Provider Calls ───────────────────────────────────────────────────────────

async def _analyze_with_anthropic_v2(capture_id: str, pack: str, prompt: str, model_override: str = None) -> AnalysisResultV2:
    """Send analysis to Anthropic Claude API."""
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        model = model_override or "claude-sonnet-4-20250514"

        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens

        return _parse_v2_response(capture_id, pack, content, "anthropic", model, tokens)

    except Exception as e:
        logger.error("Anthropic analysis failed: %s", e)
        return AnalysisResultV2(
            capture_id=capture_id,
            pack=pack,
            summary=f"Analysis failed: {e}",
            provider="anthropic",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )


async def _analyze_with_openai_v2(capture_id: str, pack: str, prompt: str, model_override: str = None) -> AnalysisResultV2:
    """Send analysis to OpenAI API."""
    try:
        import openai

        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        model = model_override or "gpt-5.4-mini"

        response = await client.chat.completions.create(
            model=model,
            max_completion_tokens=8192,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        choice = response.choices[0]
        content = choice.message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        finish = choice.finish_reason or "unknown"

        if not content:
            logger.warning("OpenAI returned empty content (model=%s, finish_reason=%s, tokens=%d)", model, finish, tokens)
        elif finish != "stop":
            logger.warning("OpenAI finish_reason=%s (model=%s, content_len=%d)", finish, model, len(content))

        return _parse_v2_response(capture_id, pack, content, "openai", model, tokens)

    except Exception as e:
        logger.error("OpenAI analysis failed: %s", e)
        return AnalysisResultV2(
            capture_id=capture_id,
            pack=pack,
            summary=f"Analysis failed: {e}",
            provider="openai",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )


# ── Response Parsing + Validation ────────────────────────────────────────────

def _parse_v2_response(
    capture_id: str,
    pack: str,
    content: str,
    provider: str,
    model: str,
    tokens: int,
) -> AnalysisResultV2:
    """Parse and validate the AI JSON response into AnalysisResultV2."""
    try:
        # Extract JSON from response (handle markdown code blocks)
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Find the end of the code block
            end_idx = len(lines) - 1
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip().startswith("```"):
                    end_idx = i
                    break
            text = "\n".join(lines[1:end_idx])

        data = json.loads(text)

        # Parse findings with validation
        findings: List[Finding] = []
        for i, f_data in enumerate(data.get("findings", [])[:MAX_FINDINGS]):
            try:
                evidence = [
                    EvidenceCitation(**e) for e in f_data.get("evidence", [])
                ]

                # Output guardrail: drop findings with no evidence
                if not evidence:
                    logger.info("Dropping finding '%s' — no evidence citations", f_data.get("title", "?"))
                    continue

                finding = Finding(
                    id=f_data.get("id", f"F{i + 1}"),
                    title=f_data.get("title", "Untitled finding"),
                    severity=f_data.get("severity", "medium"),
                    confidence=_validate_confidence(f_data.get("confidence", "low")),
                    category=f_data.get("category", "connectivity"),
                    description=f_data.get("description", ""),
                    evidence=evidence,
                    affected_flows=f_data.get("affected_flows", []),
                    likely_causes=f_data.get("likely_causes", []),
                    next_steps=f_data.get("next_steps", []),
                    cross_references=f_data.get("cross_references", []),
                )

                # Confidence enforcement: can't be HIGH with only 1 evidence
                if finding.confidence == Confidence.HIGH and len(finding.evidence) < 2:
                    finding.confidence = Confidence.MEDIUM

                findings.append(finding)
            except Exception as e:
                logger.warning("Failed to parse finding %d: %s", i, e)

        # Parse insufficient evidence notes
        insufficient: List[InsufficientEvidenceNote] = []
        for note_data in data.get("insufficient_evidence", []):
            try:
                insufficient.append(InsufficientEvidenceNote(**note_data))
            except Exception:
                pass

        # Parse health badge
        health_str = data.get("health_badge", "insufficient")
        try:
            health_badge = HealthBadge(health_str)
        except ValueError:
            health_badge = HealthBadge.INSUFFICIENT

        return AnalysisResultV2(
            capture_id=capture_id,
            pack=pack,
            summary=data.get("summary", "Analysis complete."),
            health_badge=health_badge,
            findings=findings,
            insufficient_evidence=insufficient,
            provider=provider,
            model=model,
            tokens_used=tokens,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Failed to parse AI response as JSON: %s", e)
        return AnalysisResultV2(
            capture_id=capture_id,
            pack=pack,
            summary=content[:500],
            provider=provider,
            model=model,
            tokens_used=tokens,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )


def _validate_confidence(value: str) -> Confidence:
    """Validate and normalize confidence level."""
    try:
        return Confidence(value.lower())
    except ValueError:
        return Confidence.LOW


# ── Persistence ──────────────────────────────────────────────────────────────

def _save_analysis_v2(capture_id: str, result: AnalysisResultV2) -> None:
    """Save v2 analysis result to disk."""
    path = capture_service._captures_dir() / f"{capture_id}.analysis.json"
    path.write_text(result.model_dump_json(indent=2))


def get_analysis(capture_id: str) -> Optional[AnalysisResultV2]:
    """Load a previously saved analysis result (v2 or v1)."""
    path = capture_service._captures_dir() / f"{capture_id}.analysis.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())

        # Detect v2 format (has "findings" key)
        if "findings" in data:
            return AnalysisResultV2.model_validate(data)

        # v1 format — convert to v2
        v1 = AnalysisResult.model_validate(data)
        return _convert_v1_to_v2(v1)

    except Exception as e:
        logger.warning("Failed to load analysis for %s: %s", capture_id, e)
        return None


def _convert_v1_to_v2(v1: AnalysisResult) -> AnalysisResultV2:
    """Convert a v1 AnalysisResult to v2 format."""
    findings = []
    for i, issue in enumerate(v1.issues):
        findings.append(Finding(
            id=f"F{i + 1}",
            title=f"{issue.category.title()} issue",
            severity=issue.severity,
            confidence=Confidence.MEDIUM,  # v1 has no confidence info
            category=issue.category,
            description=issue.description,
            evidence=[EvidenceCitation(
                metric="legacy_analysis",
                value="v1 analysis",
                context="Converted from v1 format — original evidence not available",
            )],
            affected_flows=issue.affected_flows,
            next_steps=[issue.recommendation] if issue.recommendation else [],
        ))

    return AnalysisResultV2(
        capture_id=v1.capture_id,
        summary=v1.summary,
        findings=findings,
        provider=v1.provider,
        model=v1.model,
        tokens_used=v1.tokens_used,
        analyzed_at=v1.analyzed_at,
    )


# ── Mock Data ────────────────────────────────────────────────────────────────

def _mock_analysis_v2(capture_id: str, pack: str, provider: str) -> AnalysisResultV2:
    """Return mock v2 analysis for development."""
    return AnalysisResultV2(
        capture_id=capture_id,
        pack=pack,
        summary=(
            "Capture shows moderate network health with some concerns. "
            "TCP retransmission rate of 3.2% detected between client and CDN, "
            "likely caused by wireless interference or congestion. "
            "DNS resolution times are normal."
        ),
        health_badge=HealthBadge.DEGRADED,
        findings=[
            Finding(
                id="F1",
                title="Elevated TCP retransmission rate",
                severity="high",
                confidence=Confidence.HIGH,
                category="retransmissions",
                description=(
                    "TCP retransmission rate of 3.2% detected on the primary CDN connection. "
                    "This exceeds the recommended 2% threshold and may cause ABR bitrate "
                    "downswitching in video streaming applications."
                ),
                evidence=[
                    EvidenceCitation(
                        metric="tcp_health.retransmission_pct",
                        value="3.2%",
                        context="Exceeds 2.0% threshold for high severity",
                    ),
                    EvidenceCitation(
                        metric="tcp_health.retransmission_count",
                        value="29 of 900 segments",
                        context="29 retransmitted TCP segments observed",
                    ),
                    EvidenceCitation(
                        metric="tcp_health.duplicate_ack_count",
                        value="15",
                        context="Corroborates packet loss detection by receiver",
                    ),
                ],
                affected_flows=["192.168.4.10:54321 → 104.16.132.229:443"],
                likely_causes=["WiFi interference on current channel", "Congestion on upstream link"],
                next_steps=[
                    "Check WiFi signal strength and channel congestion",
                    "Consider switching to 5GHz band or changing channel",
                    "Run streaming pack for detailed throughput analysis",
                ],
                cross_references=["F2"],
            ),
            Finding(
                id="F2",
                title="Occasional out-of-order delivery",
                severity="medium",
                confidence=Confidence.MEDIUM,
                category="latency",
                description=(
                    "15 TCP duplicate ACKs observed alongside 3 out-of-order segments, "
                    "indicating occasional misordering in delivery. This is within "
                    "acceptable range but correlates with the retransmission pattern in F1."
                ),
                evidence=[
                    EvidenceCitation(
                        metric="tcp_health.duplicate_ack_count",
                        value="15",
                        context="Indicates receiver detected out-of-order or lost segments",
                    ),
                    EvidenceCitation(
                        metric="tcp_health.out_of_order_count",
                        value="3",
                        context="Segments arrived out of sequence",
                    ),
                ],
                affected_flows=["192.168.4.10:54321 → 104.16.132.229:443"],
                likely_causes=["Multi-path routing", "WiFi retransmissions at L2"],
                next_steps=["Monitor during peak usage hours"],
                cross_references=["F1"],
            ),
            Finding(
                id="F3",
                title="DNS resolution healthy",
                severity="low",
                confidence=Confidence.HIGH,
                category="dns",
                description=(
                    "3 DNS queries observed with average response time of 12.5ms. "
                    "No NXDOMAIN or SERVFAIL responses. DNS infrastructure is functioning normally."
                ),
                evidence=[
                    EvidenceCitation(
                        metric="dns.avg_latency_ms",
                        value="12.5ms",
                        context="Well below 100ms threshold",
                    ),
                    EvidenceCitation(
                        metric="dns.nxdomain_count",
                        value="0",
                        context="No failed domain lookups",
                    ),
                    EvidenceCitation(
                        metric="dns.servfail_count",
                        value="0",
                        context="No DNS server failures",
                    ),
                ],
                affected_flows=[],
                likely_causes=[],
                next_steps=["No action needed"],
            ),
        ],
        insufficient_evidence=[
            InsufficientEvidenceNote(
                area="tls_health",
                reason="No TLS handshake data extracted in this capture",
                suggestion="Run HTTPS pack for TLS-specific analysis",
            ),
        ],
        provider=provider,
        model="mock",
        tokens_used=0,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
    )
