"""The sole location for operating-system-specific user guidance."""

from __future__ import annotations

import sys


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
