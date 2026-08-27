"""VPN connection manager for WireGuard."""
import subprocess
import os
from pathlib import Path


class VPNManager:
    """Manages WireGuard VPN connections."""

    def __init__(self):
        self._config_path = Path("/etc/wireguard/wg0.conf")
        self._active = False

    def is_configured(self) -> bool:
        """Check if WireGuard config exists."""
        return self._config_path.exists()

    def is_active(self) -> bool:
        """Check if WireGuard tunnel is active."""
        try:
            result = subprocess.run(
                ["wg", "show", "wg0"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def activate(self) -> bool:
        """Start WireGuard tunnel."""
        if not self.is_configured():
            return False
        try:
            subprocess.run(
                ["wg-quick", "up", "wg0"],
                capture_output=True,
                timeout=30,
            )
            self._active = True
            return True
        except Exception:
            return False

    def deactivate(self) -> bool:
        """Stop WireGuard tunnel."""
        try:
            subprocess.run(
                ["wg-quick", "down", "wg0"],
                capture_output=True,
                timeout=30,
            )
            self._active = False
            return True
        except Exception:
            return False

    def status(self) -> dict:
        """Get VPN status."""
        return {
            "configured": self.is_configured(),
            "active": self.is_active(),
            "config_path": str(self._config_path),
        }


vpn_manager = VPNManager()
