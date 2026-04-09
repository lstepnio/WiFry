"""STB_AUTOMATION — Chaos mode: autonomous random UI exploration.

Sends weighted-random key presses while monitoring for anomalies.
Configurable duration, seed (reproducible), key weights, and anomaly
response (stop/collect/ignore).

Runs the anomaly detector continuously.  Optionally does periodic
HDMI vision checks for stuck-UI or error-dialog detection.
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Optional, Set

from . import action_executor, diagnostics, fingerprint as fp, nav_model, screen_reader
from .anomaly_detector import get_detector
from .logcat_monitor import get_monitor
from .models import ChaosConfig, ChaosResult, DetectedAnomaly, VisionAnalysis

logger = logging.getLogger("wifry.stb_automation.chaos_engine")

# Track consecutive vision results for diff-based anomaly detection
_last_vision: Optional[VisionAnalysis] = None
_stuck_vision_count: int = 0  # consecutive identical vision results

# Default key weights — bias toward navigation, avoid home
DEFAULT_KEY_WEIGHTS = {
    "up": 1.0,
    "down": 1.0,
    "left": 1.0,
    "right": 1.0,
    "enter": 0.8,
    "back": 0.5,
    "home": 0.1,
}

# Module-level state
_chaos_result: Optional[ChaosResult] = None
_chaos_task: Optional[asyncio.Task] = None
_chaos_cancel = asyncio.Event()


def get_status() -> Optional[ChaosResult]:
    """Return current chaos run status, or None if never run."""
    return _chaos_result.model_copy() if _chaos_result else None


async def start_chaos(config: ChaosConfig) -> ChaosResult:
    """Start a chaos exploration session as a background task."""
    global _chaos_result, _chaos_task

    if _chaos_result and _chaos_result.state == "running":
        return _chaos_result

    seed = config.seed if config.seed is not None else random.randint(0, 2**31)
    _chaos_result = ChaosResult(state="running", seed_used=seed)
    _chaos_cancel.clear()
    _chaos_task = asyncio.create_task(_chaos_loop(config, seed))
    logger.info(
        "[STB_AUTOMATION] Chaos started: serial=%s duration=%ds seed=%d",
        config.serial, config.duration_secs, seed,
    )
    return _chaos_result


async def stop_chaos() -> Optional[ChaosResult]:
    """Stop the running chaos session."""
    global _chaos_result

    if _chaos_result is None or _chaos_result.state != "running":
        return _chaos_result

    _chaos_cancel.set()
    if _chaos_task and not _chaos_task.done():
        try:
            await asyncio.wait_for(_chaos_task, timeout=5.0)
        except asyncio.TimeoutError:
            _chaos_task.cancel()

    if _chaos_result.state == "running":
        _chaos_result.state = "completed"

    logger.info(
        "[STB_AUTOMATION] Chaos stopped: %d keys, %d screens, %d anomalies",
        _chaos_result.keys_sent,
        _chaos_result.screens_visited,
        len(_chaos_result.anomalies),
    )
    return _chaos_result


async def _chaos_loop(config: ChaosConfig, seed: int) -> None:
    """Main chaos exploration loop."""
    global _chaos_result, _last_vision, _stuck_vision_count
    if _chaos_result is None:
        return

    # Reset vision diff state for this session
    _last_vision = None
    _stuck_vision_count = 0

    rng = random.Random(seed)
    monitor = get_monitor()
    detector = get_detector()
    screens_seen: Set[str] = set()
    t_start = time.monotonic()

    # Build weighted key list
    weights = {**DEFAULT_KEY_WEIGHTS, **config.key_weights}
    keys = list(weights.keys())
    key_weights = [weights[k] for k in keys]

    try:
        while not _chaos_cancel.is_set():
            elapsed = time.monotonic() - t_start
            if elapsed >= config.duration_secs:
                break

            # Pick a random key
            action = rng.choices(keys, weights=key_weights, k=1)[0]

            # Execute
            result = await action_executor.navigate(
                serial=config.serial,
                action=action,
                settle_timeout_ms=2000,
                monitor=monitor,
            )

            _chaos_result.keys_sent += 1
            post_fp = fp.fingerprint(result.post_state)
            screens_seen.add(post_fp)
            _chaos_result.screens_visited = len(screens_seen)

            # Check logcat for anomalies
            if monitor.is_active:
                events = monitor.get_events(last_n=10)
                anomalies = detector.check_events(events)
                for anomaly in anomalies:
                    _chaos_result.anomalies.append(anomaly)

                    if config.on_anomaly == "stop":
                        logger.warning(
                            "[STB_AUTOMATION] Chaos stopping on anomaly: %s",
                            anomaly.pattern_name,
                        )
                        _chaos_result.state = "completed"
                        return

                    if config.on_anomaly == "collect":
                        anomaly.diagnostics_collected = True
                        await diagnostics.collect_diagnostics(
                            serial=config.serial,
                            reason=f"chaos_{anomaly.pattern_name}",
                            severity=anomaly.severity,
                            anomaly=anomaly,
                        )

            # Optional periodic vision check
            if (
                config.enable_vision_checks
                and _chaos_result.keys_sent % max(1, int(config.vision_check_interval_secs / 2)) == 0
            ):
                await _vision_check(config.serial, _chaos_result)

            # Brief pause between actions
            await asyncio.sleep(0.3)

        _chaos_result.state = "completed"

    except asyncio.CancelledError:
        _chaos_result.state = "completed"
    except Exception as e:
        logger.exception("[STB_AUTOMATION] Chaos error")
        _chaos_result.state = "error"
    finally:
        _chaos_result.duration_secs = round(time.monotonic() - t_start, 1)
        logger.info(
            "[STB_AUTOMATION] Chaos finished: %d keys in %.1fs, %d screens, %d anomalies",
            _chaos_result.keys_sent,
            _chaos_result.duration_secs,
            _chaos_result.screens_visited,
            len(_chaos_result.anomalies),
        )


async def _vision_check(serial: str, result: ChaosResult) -> None:
    """Run a vision anomaly check via HDMI capture.

    Detects three categories of vision anomalies:
      1. **Error screen** — AI identifies an error/crash dialog
      2. **Stuck UI** — Same screen_type + focused_label for 3+ consecutive
         checks despite key presses being sent (UI is frozen)
      3. **Focus lost** — Vision cannot identify any focused element
         (confidence=low or empty label) which may indicate an overlay
         or unexpected state
    """
    global _last_vision, _stuck_vision_count

    try:
        from ..video_capture import analyzer, streamer

        if not streamer.is_running():
            return

        frame = streamer.get_latest_frame()
        if frame is None:
            return

        analysis = await analyzer.analyze_frame(frame_jpeg=frame)
        if analysis.error:
            return

        now = datetime.now(timezone.utc).isoformat()

        # Build a VisionAnalysis from the FrameAnalysisResult for comparison
        current = VisionAnalysis(
            screen_type=analysis.screen_type or "unknown",
            screen_title=analysis.screen_title or "",
            focused_label=analysis.focused_element.label if analysis.focused_element else "",
            focused_position=analysis.focused_element.position if analysis.focused_element else "",
            focused_confidence=analysis.focused_element.confidence if analysis.focused_element else "low",
            navigation_path=analysis.navigation_path or [],
            visible_text=analysis.visible_text_summary or "",
            raw_description=analysis.raw_description or "",
            provider=analysis.provider or "",
            tokens_used=analysis.tokens_used or 0,
        )

        # ── Check 1: Error screen ─────────────────────────────────
        if current.screen_type == "error":
            result.anomalies.append(DetectedAnomaly(
                pattern_name="vision_error_screen",
                severity="high",
                category="ui",
                timestamp=now,
                vision_state=current.screen_type,
                context_lines=[current.raw_description[:200]],
            ))
            logger.warning("[STB_AUTOMATION] Vision detected error screen during chaos")

        # ── Check 2: Stuck UI (same screen for 3+ consecutive checks) ─
        if _last_vision is not None:
            same_screen = (
                current.screen_type == _last_vision.screen_type
                and current.focused_label == _last_vision.focused_label
            )
            if same_screen:
                _stuck_vision_count += 1
            else:
                _stuck_vision_count = 0

            if _stuck_vision_count >= 3:
                result.anomalies.append(DetectedAnomaly(
                    pattern_name="vision_stuck_ui",
                    severity="medium",
                    category="ui",
                    timestamp=now,
                    vision_state=f"{current.screen_type}:{current.focused_label}",
                    context_lines=[
                        f"UI unchanged for {_stuck_vision_count} consecutive vision checks",
                        f"screen_type={current.screen_type}, focused={current.focused_label}",
                    ],
                ))
                logger.warning(
                    "[STB_AUTOMATION] Vision detected stuck UI: %s/%s for %d checks",
                    current.screen_type, current.focused_label, _stuck_vision_count,
                )
                _stuck_vision_count = 0  # Reset after reporting

        # ── Check 3: Focus lost ────────────────────────────────────
        if not current.focused_label and current.focused_confidence == "low":
            result.anomalies.append(DetectedAnomaly(
                pattern_name="vision_focus_lost",
                severity="low",
                category="ui",
                timestamp=now,
                vision_state=current.screen_type,
                context_lines=[
                    "Vision cannot identify any focused element",
                    f"screen_type={current.screen_type}, visible_text={current.visible_text[:100]}",
                ],
            ))
            logger.info("[STB_AUTOMATION] Vision: no focused element detected")

        _last_vision = current

    except ImportError:
        logger.debug("[STB_AUTOMATION] Vision check not available: video_capture module missing")
    except Exception as e:
        logger.debug("[STB_AUTOMATION] Vision check failed: %s", e)
