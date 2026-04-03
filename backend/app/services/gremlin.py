"""Network Chaos Mode (PacketGremlin).

Introduces non-deterministic, hard-to-reproduce issues with adjustable intensity:

Intensity 1 (Mild):   0.05% drop, 100ms TLS delay, stall every 5-8 min
Intensity 2 (Medium): 0.2% drop, 400ms TLS delay, stall every 2-4 min
Intensity 3 (Severe): 1% drop, 800ms TLS delay, stall every 1-2 min
Intensity 4 (Extreme): 3% drop, 1500ms TLS delay, stall every 30-60 sec

Triggered via Konami code in the UI.
"""

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)

_active = False
_intensity = 2  # 1-4
_task: Optional[asyncio.Task] = None
_stall_count = 0
_activated_at: Optional[str] = None

# Intensity presets: (drop_probability, tls_delay_ms, tls_jitter_ms, stall_min_secs, stall_max_secs)
INTENSITY_PRESETS = {
    1: (0.0005, 100, 50, 300, 480),
    2: (0.002, 400, 200, 120, 240),
    3: (0.01, 800, 400, 60, 120),
    4: (0.03, 1500, 700, 30, 60),
}

INTENSITY_LABELS = {
    1: "Mild",
    2: "Medium",
    3: "Severe",
    4: "Extreme",
}


async def activate(intensity: int = 2) -> dict:
    """Enable Network Chaos Mode."""
    global _active, _task, _activated_at, _intensity

    intensity = max(1, min(4, intensity))
    _intensity = intensity

    if _active:
        # Re-apply with new intensity
        await deactivate()

    _active = True
    _activated_at = datetime.now(timezone.utc).isoformat()

    logger.warning("PacketGremlin has entered the network. (intensity=%d/%s)", _intensity, INTENSITY_LABELS[_intensity])

    if not settings.mock_mode:
        iface = settings.ap_interface or "wlan0"
        await _apply_gremlin_rules(iface)

    _task = asyncio.create_task(_stall_loop())

    return get_status()


async def deactivate() -> dict:
    """Disable Network Chaos Mode."""
    global _active, _task

    if not _active:
        return get_status()

    _active = False

    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None

    if not settings.mock_mode:
        iface = settings.ap_interface or "wlan0"
        await _remove_gremlin_rules(iface)

    logger.info("PacketGremlin has left the network.")
    return get_status()


def get_status() -> dict:
    preset = INTENSITY_PRESETS[_intensity]
    return {
        "active": _active,
        "intensity": _intensity,
        "intensity_label": INTENSITY_LABELS[_intensity],
        "stall_count": _stall_count,
        "activated_at": _activated_at,
        "message": "PacketGremlin has entered the network." if _active else "All clear.",
        "details": {
            "drop_pct": round(preset[0] * 100, 3),
            "tls_delay_ms": preset[1],
            "tls_jitter_ms": preset[2],
            "stall_interval": f"{preset[3] // 60}-{preset[4] // 60} min" if preset[3] >= 60 else f"{preset[3]}-{preset[4]} sec",
        },
    }


async def _apply_gremlin_rules(iface: str) -> None:
    preset = INTENSITY_PRESETS[_intensity]
    drop_prob, tls_delay, tls_jitter = preset[0], preset[1], preset[2]

    await run(
        "iptables", "-A", "FORWARD",
        "-i", iface, "-m", "statistic",
        "--mode", "random", "--probability", str(drop_prob),
        "-j", "DROP",
        "-m", "comment", "--comment", "wifry-gremlin-drop",
        sudo=True, check=False,
    )

    await run(
        "tc", "qdisc", "add", "dev", iface,
        "root", "handle", "99:", "prio",
        sudo=True, check=False,
    )
    await run(
        "tc", "qdisc", "add", "dev", iface,
        "parent", "99:3", "handle", "990:",
        "netem", "delay", f"{tls_delay}ms", f"{tls_jitter}ms",
        sudo=True, check=False,
    )
    await run(
        "tc", "filter", "add", "dev", iface,
        "parent", "99:", "protocol", "ip", "prio", "1",
        "u32", "match", "ip", "dport", "443", "0xffff",
        "match", "ip", "protocol", "6", "0xff",
        "flowid", "99:3",
        sudo=True, check=False,
    )

    logger.info("Gremlin rules applied on %s (intensity=%d)", iface, _intensity)


async def _remove_gremlin_rules(iface: str) -> None:
    preset = INTENSITY_PRESETS[_intensity]
    await run(
        "iptables", "-D", "FORWARD",
        "-i", iface, "-m", "statistic",
        "--mode", "random", "--probability", str(preset[0]),
        "-j", "DROP",
        "-m", "comment", "--comment", "wifry-gremlin-drop",
        sudo=True, check=False,
    )
    await run(
        "tc", "qdisc", "del", "dev", iface, "root", "handle", "99:",
        sudo=True, check=False,
    )
    logger.info("Gremlin rules removed from %s", iface)


async def _stall_loop() -> None:
    global _stall_count

    while _active:
        preset = INTENSITY_PRESETS[_intensity]
        wait_secs = random.randint(preset[3], preset[4])
        try:
            await asyncio.sleep(wait_secs)
        except asyncio.CancelledError:
            return

        if not _active:
            return

        logger.warning("PacketGremlin is stalling a stream...")
        _stall_count += 1

        if not settings.mock_mode:
            iface = settings.ap_interface or "wlan0"
            await run("tc", "qdisc", "replace", "dev", iface, "root", "netem", "loss", "100%", sudo=True, check=False)
            await asyncio.sleep(10)
            await run("tc", "qdisc", "del", "dev", iface, "root", sudo=True, check=False)
            await _apply_gremlin_rules(iface)

        logger.warning("PacketGremlin stall complete (stall #%d)", _stall_count)
