"""Re-export hw_capabilities from the service module for test use."""

from app.services.hw_capabilities import (
    WifiCapabilities,
    clear_cache,
    detect_capabilities,
)

__all__ = ["WifiCapabilities", "detect_capabilities", "clear_cache"]
