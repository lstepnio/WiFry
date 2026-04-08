"""Application configuration via pydantic-settings."""

import platform
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WIFRY_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # Mock mode: if True, log commands instead of executing them.
    # Auto-detected on non-Linux systems.
    mock_mode: bool = platform.system() != "Linux"

    # Data directories
    data_dir: Path = Path("/var/lib/wifry")
    profiles_dir: Path = Path(__file__).resolve().parent.parent / "profiles"
    captures_dir: Path = Path("/var/lib/wifry/captures")

    # Network interfaces (auto-detected if empty)
    ap_interface: str = ""  # e.g. wlan0
    upstream_interface: str = ""  # e.g. eth0
    bridge_interfaces: list[str] = []

    # WiFi AP defaults
    ap_ssid: str = "WiFry"
    ap_password: str = "wifry1234"
    ap_channel: int = 6
    ap_band: str = "2.4GHz"  # "2.4GHz" or "5GHz"

    # AI analysis
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ai_provider: str = "anthropic"  # "anthropic" or "openai"
    ai_model: str = ""  # Empty = provider default (gpt-5.4-mini / claude-sonnet-4-20250514)

    # Capture v2
    capture_max_concurrent: int = 2
    capture_ring_segment_kb: int = 10240  # 10 MB per segment
    capture_ring_max_files: int = 10  # Max 100 MB per capture
    capture_min_disk_mb: int = 200  # Minimum free disk for new capture
    capture_retention_max_count: int = 20
    capture_retention_max_mb: int = 500
    capture_retention_max_days: int = 7

    # DNS
    dns_enabled: bool = True
    coredns_binary: str = "/usr/local/bin/coredns"

    def model_post_init(self, __context: object) -> None:
        # Ensure data directories exist when not in mock mode
        # Silently skip if we don't have permissions (e.g., CI environment)
        if not self.mock_mode:
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                self.captures_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                pass  # Running in CI or unprivileged environment


settings = Settings()
