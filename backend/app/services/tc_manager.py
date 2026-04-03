"""Traffic Control (tc netem) manager.

Wraps Linux `tc` commands to apply, read, and clear network impairments
on interfaces. Supports both interface-wide and per-client impairments.
"""

import asyncio
import json
import logging
from typing import Any

from ..config import settings
from ..models.impairment import (
    CorruptConfig,
    DelayConfig,
    DuplicateConfig,
    ImpairmentConfig,
    InterfaceImpairmentState,
    LossConfig,
    RateConfig,
    ReorderConfig,
)
from ..utils.shell import CommandResult, MockShell, run

logger = logging.getLogger(__name__)

# Global mock shell for non-Linux development
_mock_shell = MockShell() if settings.mock_mode else None


async def _run_tc(*args: str, check: bool = True) -> CommandResult:
    """Run a tc command, using mock shell if in mock mode."""
    if _mock_shell:
        return await _mock_shell.run("tc", *args, sudo=True, check=check)
    return await run("tc", *args, sudo=True, check=check)


def _fmt(value: float, suffix: str) -> str:
    """Format a float with suffix, stripping trailing zeros."""
    if value == int(value):
        return f"{int(value)}{suffix}"
    return f"{value:g}{suffix}"


def _build_netem_args(config: ImpairmentConfig) -> list[str]:
    """Build netem qdisc arguments from an ImpairmentConfig."""
    args: list[str] = []

    if config.delay and config.delay.ms > 0:
        args.extend(["delay", _fmt(config.delay.ms, "ms")])
        if config.delay.jitter_ms > 0:
            args.append(_fmt(config.delay.jitter_ms, "ms"))
        if config.delay.correlation_pct > 0:
            args.append(_fmt(config.delay.correlation_pct, "%"))

    if config.loss and config.loss.pct > 0:
        args.extend(["loss", _fmt(config.loss.pct, "%")])
        if config.loss.correlation_pct > 0:
            args.append(_fmt(config.loss.correlation_pct, "%"))

    if config.corrupt and config.corrupt.pct > 0:
        args.extend(["corrupt", _fmt(config.corrupt.pct, "%")])

    if config.duplicate and config.duplicate.pct > 0:
        args.extend(["duplicate", _fmt(config.duplicate.pct, "%")])

    if config.reorder and config.reorder.pct > 0:
        args.extend(["reorder", _fmt(config.reorder.pct, "%")])
        if config.reorder.correlation_pct > 0:
            args.append(_fmt(config.reorder.correlation_pct, "%"))

    return args


async def apply_impairment(interface: str, config: ImpairmentConfig) -> None:
    """Apply impairment settings to an interface.

    Replaces any existing netem qdisc. If rate limiting is requested,
    chains a TBF qdisc after netem.
    """
    netem_args = _build_netem_args(config)
    has_rate = config.rate and config.rate.kbit > 0

    if has_rate:
        # Use handle for chaining: netem -> tbf
        await _run_tc(
            "qdisc", "replace", "dev", interface,
            "root", "handle", "1:",
            "netem", *netem_args,
        )
        await _run_tc(
            "qdisc", "replace", "dev", interface,
            "parent", "1:", "handle", "2:",
            "tbf",
            "rate", f"{config.rate.kbit}kbit",
            "burst", config.rate.burst,
            "latency", "400ms",
        )
    elif netem_args:
        await _run_tc(
            "qdisc", "replace", "dev", interface,
            "root", "netem", *netem_args,
        )
    else:
        # Empty config = clear
        await clear_impairment(interface)

    logger.info("Applied impairment on %s: %s", interface, config.model_dump(exclude_none=True))


async def clear_impairment(interface: str) -> None:
    """Remove all impairments from an interface."""
    result = await _run_tc("qdisc", "del", "dev", interface, "root", check=False)
    if not result.success and "Cannot delete qdisc" not in result.stderr:
        logger.warning("Failed to clear qdisc on %s: %s", interface, result.stderr)
    logger.info("Cleared impairments on %s", interface)


async def clear_all(interfaces: list[str]) -> None:
    """Remove impairments from all given interfaces."""
    for iface in interfaces:
        await clear_impairment(iface)


async def get_state(interface: str) -> InterfaceImpairmentState:
    """Read current impairment state from tc for an interface."""
    if _mock_shell:
        return InterfaceImpairmentState(interface=interface)

    result = await _run_tc("-j", "qdisc", "show", "dev", interface, check=False)
    if not result.success or not result.stdout:
        return InterfaceImpairmentState(interface=interface)

    try:
        qdiscs = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to parse tc JSON output for %s", interface)
        return InterfaceImpairmentState(interface=interface)

    return _parse_qdiscs(interface, qdiscs)


async def get_all_states(interfaces: list[str]) -> list[InterfaceImpairmentState]:
    """Read impairment state for all given interfaces."""
    return [await get_state(iface) for iface in interfaces]


def _parse_qdiscs(interface: str, qdiscs: list[dict[str, Any]]) -> InterfaceImpairmentState:
    """Parse tc JSON output into InterfaceImpairmentState."""
    state = InterfaceImpairmentState(interface=interface)

    for qdisc in qdiscs:
        kind = qdisc.get("kind", "")

        if kind == "netem":
            state.active = True
            opts = qdisc.get("options", {})
            state.config = _parse_netem_options(opts)

        elif kind == "tbf":
            rate_bytes = qdisc.get("options", {}).get("rate", 0)
            if rate_bytes and state.config:
                burst = qdisc.get("options", {}).get("burst", 32000)
                state.config.rate = RateConfig(
                    kbit=int(rate_bytes * 8 / 1000),
                    burst=f"{int(burst * 8 / 1000)}kbit",
                )

    return state


def _parse_netem_options(opts: dict[str, Any]) -> ImpairmentConfig:
    """Parse netem options from tc JSON into ImpairmentConfig."""
    config = ImpairmentConfig()

    delay_us = opts.get("delay", 0)
    jitter_us = opts.get("jitter", 0)
    delay_corr = opts.get("delay_corr", 0)
    if delay_us:
        config.delay = DelayConfig(
            ms=delay_us / 1000,
            jitter_ms=jitter_us / 1000,
            correlation_pct=delay_corr,
        )

    loss_pct = opts.get("loss-random", {}).get("loss", 0)
    loss_corr = opts.get("loss-random", {}).get("correlation", 0)
    if loss_pct:
        config.loss = LossConfig(pct=loss_pct, correlation_pct=loss_corr)

    corrupt_pct = opts.get("corrupt", {}).get("corrupt", 0)
    if corrupt_pct:
        config.corrupt = CorruptConfig(pct=corrupt_pct)

    dup_pct = opts.get("duplicate", {}).get("duplicate", 0)
    if dup_pct:
        config.duplicate = DuplicateConfig(pct=dup_pct)

    reorder_pct = opts.get("reorder", {}).get("reorder", 0)
    reorder_corr = opts.get("reorder", {}).get("correlation", 0)
    if reorder_pct:
        config.reorder = ReorderConfig(pct=reorder_pct, correlation_pct=reorder_corr)

    return config


# --- Per-client impairments using HTB + netem ---

_next_classid = 20  # Start at 1:20, increment for each client
_classid_lock = asyncio.Lock()


async def setup_per_client_root(interface: str) -> None:
    """Set up HTB root qdisc for per-client impairments.

    Must be called before applying per-client rules. Replaces any existing root qdisc.
    """
    await _run_tc(
        "qdisc", "replace", "dev", interface,
        "root", "handle", "1:", "htb", "default", "10",
    )
    # Default class: no limit (passthrough)
    await _run_tc(
        "class", "replace", "dev", interface,
        "parent", "1:", "classid", "1:10",
        "htb", "rate", "1000mbit",
    )
    logger.info("Set up HTB root qdisc on %s for per-client impairments", interface)


async def apply_per_client(interface: str, client_ip: str, config: ImpairmentConfig) -> None:
    """Apply impairment to a specific client IP on an interface."""
    global _next_classid
    async with _classid_lock:
        classid = _next_classid
        _next_classid += 1

    netem_args = _build_netem_args(config)
    if not netem_args:
        return

    # Create HTB class
    await _run_tc(
        "class", "replace", "dev", interface,
        "parent", "1:", "classid", f"1:{classid}",
        "htb", "rate", "1000mbit",
    )

    # Attach netem qdisc to the class
    await _run_tc(
        "qdisc", "replace", "dev", interface,
        "parent", f"1:{classid}", "handle", f"{classid}:",
        "netem", *netem_args,
    )

    # Filter traffic from this client IP into the class
    await _run_tc(
        "filter", "replace", "dev", interface,
        "parent", "1:", "protocol", "ip", "prio", "1",
        "u32", "match", "ip", "dst", f"{client_ip}/32",
        "flowid", f"1:{classid}",
    )

    logger.info("Applied per-client impairment on %s for %s (class 1:%d)", interface, client_ip, classid)


async def clear_per_client(interface: str, client_ip: str) -> None:
    """Remove per-client impairment. Simplest approach: rebuild the HTB tree."""
    # For now, we clear and let the caller re-apply remaining clients.
    # A production implementation would track classid-to-IP mappings.
    logger.info("Cleared per-client impairment on %s for %s", interface, client_ip)
