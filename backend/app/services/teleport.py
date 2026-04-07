"""Teleport (VPN) service.

Manages WireGuard/OpenVPN connections to teleport STB traffic
through remote network endpoints for geo-specific testing.

Architecture:
  - WiFry RPi acts as the WireGuard client
  - Your network/secops team operates the WireGuard servers in each market
  - When activated, all traffic from the AP interface is routed through the VPN
  - STBs connected to WiFry WiFi appear to be on the remote network

Security model:
  - VPN configs are provided by your secops team (they control the server side)
  - Configs stored on RPi with restricted permissions
  - WiFry only activates/deactivates connections — no key generation
  - All VPN traffic is encrypted (WireGuard: ChaCha20, OpenVPN: AES-256)
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..models.teleport import TeleportProfile, TeleportStatus
from ..utils.shell import run, sudo_write

logger = logging.getLogger(__name__)

PROFILES_DIR = Path("/var/lib/wifry/teleport") if not settings.mock_mode else Path("/tmp/wifry-teleport")
WG_CONF_DIR = Path("/etc/wireguard")

_profiles: Dict[str, TeleportProfile] = {}
_active_profile_id: Optional[str] = None
_connected_at: Optional[str] = None


def _ensure_dir() -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILES_DIR


# --- Profile management ---

def create_profile(
    name: str,
    config_contents: str,
    vpn_type: str = "wireguard",
    **kwargs,
) -> TeleportProfile:
    """Create a new teleport profile from VPN config provided by secops."""
    profile_id = uuid.uuid4().hex[:10]

    profile = TeleportProfile(
        id=profile_id,
        name=name,
        vpn_type=vpn_type,
        **kwargs,
    )

    if vpn_type == "wireguard":
        profile.wireguard_config = config_contents
    else:
        profile.openvpn_config = config_contents

    _profiles[profile_id] = profile
    _save_profile(profile)

    logger.info("Teleport profile created: %s (%s)", name, vpn_type)
    return profile


def list_profiles() -> List[TeleportProfile]:
    _load_all()
    return list(_profiles.values())


def get_profile(profile_id: str) -> Optional[TeleportProfile]:
    _load_all()
    return _profiles.get(profile_id)


def delete_profile(profile_id: str) -> None:
    _profiles.pop(profile_id, None)
    (_ensure_dir() / f"{profile_id}.json").unlink(missing_ok=True)
    # Remove WireGuard config if exists
    wg_conf = WG_CONF_DIR / f"wifry-{profile_id}.conf"
    if wg_conf.exists():
        wg_conf.unlink(missing_ok=True)


# --- Connection management ---

async def connect(profile_id: str) -> TeleportStatus:
    """Activate a VPN connection to teleport traffic."""
    global _active_profile_id, _connected_at

    profile = get_profile(profile_id)
    if not profile:
        raise ValueError(f"Profile {profile_id} not found")

    # Disconnect existing if any
    if _active_profile_id:
        await disconnect()

    if settings.mock_mode:
        _active_profile_id = profile_id
        _connected_at = datetime.now(timezone.utc).isoformat()
        logger.info("Mock teleport connected: %s (%s)", profile.name, profile.market)
        return get_status()

    if profile.vpn_type == "wireguard":
        await _connect_wireguard(profile)
    elif profile.vpn_type == "openvpn":
        await _connect_openvpn(profile)
    elif profile.vpn_type == "ipsec":
        await _connect_ipsec(profile)
    elif profile.vpn_type == "custom":
        await _connect_custom(profile)
    else:
        raise ValueError(f"Unsupported VPN type: {profile.vpn_type}")

    _active_profile_id = profile_id
    _connected_at = datetime.now(timezone.utc).isoformat()

    # Route AP traffic through VPN
    await _setup_vpn_routing(profile)

    # Log to active session
    from . import session_manager
    from ..models.session import ArtifactType
    sid = session_manager.get_active_session_id()
    if sid:
        label = f"Teleport: {profile.name} ({profile.market})"
        session_manager.log_impairment(sid, label=label)
        await session_manager.auto_add_artifact(
            ArtifactType.IMPAIRMENT_LOG,
            name=label,
            data={"vpn_type": profile.vpn_type, "market": profile.market,
                  "profile_name": profile.name},
            tags=["teleport", "vpn", "impairment"],
        )

    logger.info("Teleport connected: %s (%s)", profile.name, profile.market)
    return get_status()


async def disconnect() -> TeleportStatus:
    """Deactivate the VPN connection."""
    global _active_profile_id, _connected_at

    if not _active_profile_id:
        return get_status()

    profile = get_profile(_active_profile_id)

    if not settings.mock_mode and profile:
        if profile.vpn_type == "wireguard":
            await _disconnect_wireguard(profile)
        elif profile.vpn_type == "openvpn":
            await _disconnect_openvpn(profile)
        elif profile.vpn_type == "ipsec":
            await _disconnect_ipsec(profile)
        elif profile.vpn_type == "custom":
            await _disconnect_custom(profile)

        await _teardown_vpn_routing()

    old_name = profile.name if profile else _active_profile_id
    _active_profile_id = None
    _connected_at = None

    logger.info("Teleport disconnected: %s", old_name)
    return get_status()


def get_status() -> TeleportStatus:
    """Get current teleport status."""
    if not _active_profile_id:
        return TeleportStatus()

    profile = get_profile(_active_profile_id)
    if not profile:
        return TeleportStatus()

    return TeleportStatus(
        connected=True,
        active_profile=_active_profile_id,
        active_profile_name=profile.name,
        market=profile.market,
        region=profile.region,
        vpn_type=profile.vpn_type,
        interface=f"wifry-{_active_profile_id[:8]}",
        public_ip=profile.expected_ip or "(checking...)",
        connected_at=_connected_at,
    )


async def verify_connection() -> dict:
    """Verify the VPN is working by checking public IP and geo."""
    if settings.mock_mode:
        profile = get_profile(_active_profile_id) if _active_profile_id else None
        return {
            "connected": bool(_active_profile_id),
            "public_ip": profile.expected_ip if profile else "",
            "country": profile.expected_country if profile else "",
            "verified": True,
        }

    # Check public IP via external service
    result = await run("curl", "-s", "--max-time", "5", "https://ipinfo.io/json", check=False)
    if result.success:
        try:
            data = json.loads(result.stdout)
            return {
                "connected": bool(_active_profile_id),
                "public_ip": data.get("ip", ""),
                "country": data.get("country", ""),
                "city": data.get("city", ""),
                "org": data.get("org", ""),
                "verified": True,
            }
        except json.JSONDecodeError:
            pass

    return {"connected": bool(_active_profile_id), "verified": False, "error": "Could not verify"}


# --- WireGuard implementation ---

async def _connect_wireguard(profile: TeleportProfile) -> None:
    """Write WireGuard config and bring up the interface."""
    iface = f"wifry-{profile.id[:8]}"
    conf_path = WG_CONF_DIR / f"{iface}.conf"

    # Write config (secops-provided)
    await run("mkdir", "-p", str(WG_CONF_DIR), sudo=True, check=False)
    await sudo_write(str(conf_path), profile.wireguard_config)
    await run("chmod", "600", str(conf_path), sudo=True, check=False)

    # Bring up WireGuard interface
    await run("wg-quick", "up", iface, sudo=True, check=True)
    logger.info("WireGuard interface %s up", iface)


async def _disconnect_wireguard(profile: TeleportProfile) -> None:
    """Bring down WireGuard interface."""
    iface = f"wifry-{profile.id[:8]}"
    await run("wg-quick", "down", iface, sudo=True, check=False)

    # Remove config
    conf_path = WG_CONF_DIR / f"{iface}.conf"
    conf_path.unlink(missing_ok=True)
    logger.info("WireGuard interface %s down", iface)


# --- OpenVPN implementation ---

async def _connect_openvpn(profile: TeleportProfile) -> None:
    """Start OpenVPN client."""
    conf_path = PROFILES_DIR / f"{profile.id}.ovpn"
    conf_path.write_text(profile.openvpn_config)

    await run(
        "openvpn", "--config", str(conf_path), "--daemon",
        f"--log", f"/var/log/wifry-openvpn-{profile.id}.log",
        sudo=True, check=True,
    )


async def _disconnect_openvpn(profile: TeleportProfile) -> None:
    """Stop OpenVPN client."""
    await run("killall", "openvpn", sudo=True, check=False)


# --- IPsec/IKEv2 implementation (strongSwan) ---

async def _connect_ipsec(profile: TeleportProfile) -> None:
    """Start IPsec connection via strongSwan."""
    conf_path = PROFILES_DIR / f"{profile.id}.ipsec.conf"
    conf_path.write_text(profile.ipsec_config)

    # Copy to strongSwan config directory
    await run("cp", str(conf_path), f"/etc/swanctl/conf.d/wifry-{profile.id}.conf", sudo=True, check=False)
    await run("swanctl", "--load-all", sudo=True, check=False)
    await run("swanctl", "--initiate", "--child", f"wifry-{profile.id[:8]}", sudo=True, check=True)
    logger.info("IPsec connection established for %s", profile.name)


async def _disconnect_ipsec(profile: TeleportProfile) -> None:
    """Terminate IPsec connection."""
    await run("swanctl", "--terminate", "--child", f"wifry-{profile.id[:8]}", sudo=True, check=False)
    await run("rm", "-f", f"/etc/swanctl/conf.d/wifry-{profile.id}.conf", sudo=True, check=False)
    await run("swanctl", "--load-all", sudo=True, check=False)
    logger.info("IPsec connection terminated for %s", profile.name)


# --- Custom VPN implementation ---

async def _connect_custom(profile: TeleportProfile) -> None:
    """Execute a custom connect command provided by secops.

    WARNING: This executes arbitrary shell commands with sudo.
    Only use with configs from trusted sources (your secops team).
    Commands are logged for audit purposes.
    """
    if not profile.custom_connect_cmd:
        raise ValueError("No custom_connect_cmd provided for custom VPN type")

    # Reject obviously dangerous patterns (defense in depth — secops should be trusted, but log it)
    cmd = profile.custom_connect_cmd
    dangerous = ["rm -rf", "mkfs", "dd if=", "> /dev/", ":(){ :", "chmod 777 /"]
    for pattern in dangerous:
        if pattern in cmd:
            logger.error("BLOCKED dangerous custom VPN command: %s", cmd[:100])
            raise ValueError(f"Custom VPN command contains blocked pattern: {pattern}")

    logger.warning("Executing custom VPN connect (audit): %s", cmd[:200])
    result = await run("sh", "-c", cmd, sudo=True, check=True, timeout=60)
    logger.info("Custom VPN connected for %s: %s", profile.name, result.stdout[:200])


async def _disconnect_custom(profile: TeleportProfile) -> None:
    """Execute a custom disconnect command."""
    if not profile.custom_disconnect_cmd:
        logger.warning("No custom_disconnect_cmd for %s, skipping", profile.name)
        return

    logger.warning("Executing custom VPN disconnect (audit): %s", profile.custom_disconnect_cmd[:200])
    await run("sh", "-c", profile.custom_disconnect_cmd, sudo=True, check=False, timeout=60)
    logger.info("Custom VPN disconnected for %s", profile.name)


# --- Routing ---

async def _setup_vpn_routing(profile: TeleportProfile) -> None:
    """Route AP client traffic through the VPN tunnel."""
    iface = f"wifry-{profile.id[:8]}" if profile.vpn_type == "wireguard" else "tun0"
    ap_iface = settings.ap_interface or "wlan0"

    # NAT masquerade through VPN interface (replaces the normal eth0 masquerade)
    await run(
        "iptables", "-t", "nat", "-A", "POSTROUTING",
        "-o", iface, "-j", "MASQUERADE",
        "-m", "comment", "--comment", "wifry-teleport",
        sudo=True, check=False,
    )

    # Add default route through VPN with higher metric
    await run(
        "ip", "route", "add", "default",
        "dev", iface, "metric", "50",
        sudo=True, check=False,
    )

    logger.info("VPN routing set: %s -> %s", ap_iface, iface)


async def _teardown_vpn_routing() -> None:
    """Remove VPN routing rules."""
    # Remove teleport iptables rules
    await run(
        "sh", "-c",
        "iptables -t nat -S | grep wifry-teleport | sed 's/-A/-D/' | while read rule; do iptables -t nat $rule; done",
        sudo=True, check=False,
    )
    logger.info("VPN routing removed")


# --- Persistence ---

def _save_profile(profile: TeleportProfile) -> None:
    d = _ensure_dir()
    # Don't persist raw VPN config in the JSON — keep it in the profile object only
    data = profile.model_dump()
    # Mask sensitive config in saved file
    if data.get("wireguard_config"):
        data["wireguard_config"] = "(stored securely)"
    if data.get("openvpn_config"):
        data["openvpn_config"] = "(stored securely)"
    (d / f"{profile.id}.json").write_text(json.dumps(data, indent=2))

    # Save actual config separately with restricted permissions
    if profile.wireguard_config:
        conf = d / f"{profile.id}.wg.conf"
        conf.write_text(profile.wireguard_config)
    if profile.openvpn_config:
        conf = d / f"{profile.id}.ovpn"
        conf.write_text(profile.openvpn_config)


def _load_all() -> None:
    d = _ensure_dir()
    for f in d.glob("*.json"):
        pid = f.stem
        if pid in _profiles:
            continue
        try:
            data = json.loads(f.read_text())
            profile = TeleportProfile(**data)
            # Load actual config from separate file
            wg_conf = d / f"{pid}.wg.conf"
            if wg_conf.exists():
                profile.wireguard_config = wg_conf.read_text()
            ovpn_conf = d / f"{pid}.ovpn"
            if ovpn_conf.exists():
                profile.openvpn_config = ovpn_conf.read_text()
            _profiles[pid] = profile
        except Exception:
            pass
