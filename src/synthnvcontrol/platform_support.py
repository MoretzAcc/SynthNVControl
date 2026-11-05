"""The sole location for operating-system-specific user guidance."""

from __future__ import annotations

import sys


def is_serial_permission_error(message: str | None) -> bool:
    """Return whether a probe error indicates missing local port access."""
    return bool(
        message
        and sys.platform.startswith("linux")
        and ("permission denied" in message.lower() or "errno 13" in message.lower())
    )


def serial_port_group(port: str) -> str | None:
    """Return the Linux group that owns a serial-device path, when available."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        import grp
        from os import stat

        return grp.getgrgid(stat(port).st_gid).gr_name
    except (OSError, KeyError):
        return None


def serial_access_hint(error: Exception) -> str:
    """Describe the likely port-access remedy without requiring elevated access."""
    if sys.platform.startswith("win"):
        return f"Could not open the COM port: {error}. Close other applications using it and check the USB serial driver."
    if sys.platform.startswith("linux"):
        return (
            f"Could not open the serial port: {error}. Add your user to the serial-device group "
            "(commonly dialout or uucp), then sign in again. Running the GUI with sudo is not recommended."
        )
    return f"Could not open the serial port: {error}"
