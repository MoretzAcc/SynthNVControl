"""Serialized serial transport with safe disconnect and reconnect handling.

LEGACY-002 / LEGACY-003: requests are never represented by one mutable global
callback or completed because one short poll was empty.  A worker owns one
request queue and uses a per-request serial timeout instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from time import monotonic

import serial
from PySide6.QtCore import QThread, Signal
from serial.tools import list_ports

from synthnvcontrol.platform_support import serial_access_hint


BAUD_RATE = 115200
RESPONSE_TIMEOUT_SECONDS = 1.5
RECONNECT_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class DeviceTarget:
    port: str
    serial_number: str | None


@dataclass(frozen=True)
class Request:
    identifier: int
    payload: str
    expect_response: bool
    drain_response: bool = False


def discover_synthnv_targets() -> list[tuple[DeviceTarget, str]]:
    """Return USB serial devices that answer the SynthNV serial-number command."""
    targets: list[tuple[DeviceTarget, str]] = []
    for port in list_ports.comports():
        if port.vid is None or port.pid is None:
            continue
        serial_number = _probe_serial_number(port.device)
        if not serial_number:
            continue
        details = " · ".join(part for part in (port.description, port.manufacturer) if part)
        usb_id = f"{port.vid:04X}:{port.pid:04X}"
        description = f"{details} · {usb_id}" if details else usb_id
        targets.append((DeviceTarget(port.device, serial_number), description))
    return targets


def _probe_serial_number(port: str) -> str | None:
    """Ask a USB serial device for the documented SynthNV `-` response."""
    try:
        with serial.Serial(port, BAUD_RATE, timeout=0.5, write_timeout=0.5) as connection:
            connection.reset_input_buffer()
            connection.write(b"-")
            connection.flush()
            response = connection.read_until(b"\n").decode("utf-8", errors="replace").strip()
    except (serial.SerialException, OSError):
        return None
    return response or None


class DiscoveryWorker(QThread):
    """Probe candidate USB serial devices without pausing the startup dialog."""

    targets_found = Signal(object)

    def run(self) -> None:
        self.targets_found.emit(discover_synthnv_targets())


class SerialWorker(QThread):
    connected = Signal(bool)
    disconnected = Signal(str)
    completed = Signal(int, str, str)

    def __init__(self, target: DeviceTarget) -> None:
        super().__init__()
        self._target = target
        self._requests: Queue[Request] = Queue()
        self._running = True
        self._serial: serial.Serial | None = None
        self._was_connected = False
        self._last_attempt = 0.0
        self._last_connection_error: str | None = None

    def submit(self, request: Request) -> None:
        self._requests.put(request)

    def identify(self, serial_number: str) -> None:
        """Enable safe reconnect matching after the device serial query completes."""
        if serial_number.strip():
            self._target = DeviceTarget(self._target.port, serial_number.strip())

    def stop(self) -> None:
        self._running = False
        self.wait(2_000)

    def run(self) -> None:
        while self._running:
            if not self._ensure_connection():
                self.msleep(100)
                continue
            try:
                request = self._requests.get(timeout=0.1)
            except Empty:
                continue
            self._perform(request)
        self._close()

    def _ensure_connection(self) -> bool:
        if self._serial and self._serial.is_open:
            if self._target.serial_number and not self._device_is_present():
                self._close()
                self.disconnected.emit("Disconnected: the selected serial number is no longer present")
                self._fail_pending_requests()
                return False
            return True
        now = monotonic()
        if now - self._last_attempt < RECONNECT_INTERVAL_SECONDS:
            return False
        self._last_attempt = now
        port = self._reconnect_port()
        if port is None:
            return False
        try:
            self._serial = serial.Serial(port, BAUD_RATE, timeout=RESPONSE_TIMEOUT_SECONDS, write_timeout=1)
        except (serial.SerialException, OSError) as error:
            message = serial_access_hint(error)
            if message != self._last_connection_error:
                self.disconnected.emit(message)
                self._last_connection_error = message
            return False
        reconnected = self._was_connected
        self._was_connected = True
        self._last_connection_error = None
        self.connected.emit(reconnected)
        return True

    def _device_is_present(self) -> bool:
        return any(port.serial_number == self._target.serial_number for port in list_ports.comports())

    def _reconnect_port(self) -> str | None:
        if self._serial is None and not self._was_connected:
            return self._target.port
        # A port name can change after USB re-enumeration. Only resume a session
        # after a serial-number match; never attach to an arbitrary new device.
        if not self._target.serial_number:
            return None
        for port in list_ports.comports():
            if port.serial_number == self._target.serial_number:
                return port.device
        return None

    def _perform(self, request: Request) -> None:
        assert self._serial is not None
        try:
            self._serial.reset_input_buffer()
            self._serial.write(request.payload.encode("ascii"))
            self._serial.flush()
            response = ""
            if request.expect_response:
                if request.drain_response:
                    response = self._read_until_quiet()
                else:
                    response = self._serial.read_until(b"\n").decode("utf-8", errors="replace").rstrip("\r\n")
                if not response:
                    self.completed.emit(request.identifier, "", "No response before timeout")
                    return
            self.completed.emit(request.identifier, response, "")
        except (serial.SerialException, OSError) as error:
            self._close()
            self.disconnected.emit(f"Disconnected: {error}")
            self.completed.emit(request.identifier, "", "Device disconnected")
            self._fail_pending_requests()

    def _read_until_quiet(self) -> str:
        """Read non-newline protocol replies (`?` and sweep result) completely."""
        assert self._serial is not None
        chunks: list[bytes] = []
        deadline = monotonic() + RESPONSE_TIMEOUT_SECONDS
        quiet_since: float | None = None
        while monotonic() < deadline:
            waiting = self._serial.in_waiting
            if waiting:
                chunks.append(self._serial.read(waiting))
                quiet_since = None
                self.msleep(20)
                continue
            if chunks:
                if quiet_since is None:
                    quiet_since = monotonic()
                elif monotonic() - quiet_since >= 0.15:
                    break
            self.msleep(20)
        return b"".join(chunks).decode("utf-8", errors="replace").strip()

    def _close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except (serial.SerialException, OSError):
                pass
        self._serial = None

    def _fail_pending_requests(self) -> None:
        """Never replay commands issued before a disconnect on a reconnected unit."""
        while True:
            try:
                request = self._requests.get_nowait()
            except Empty:
                return
            self.completed.emit(request.identifier, "", "Request cancelled by device disconnect")
