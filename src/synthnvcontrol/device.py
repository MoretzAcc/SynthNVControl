"""Serialized serial transport with safe disconnect and reconnect handling.

LEGACY-002 / LEGACY-003: requests are never represented by one mutable global
callback or completed because one short poll was empty.  A worker owns one
request queue and uses a per-request serial timeout instead.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from queue import Empty, Queue
from time import monotonic, sleep

import serial
from PySide6.QtCore import QThread, Signal
from serial.tools import list_ports

from synthnvcontrol.platform_support import serial_access_hint


LOGGER = logging.getLogger(__name__)

BAUD_RATE = 115200
RESPONSE_TIMEOUT_SECONDS = 1.5
RECONNECT_INTERVAL_SECONDS = 2.0


def log_command(
    event: str,
    origin: str,
    command: str,
    *,
    port: str = "-",
    response: str | None = None,
) -> None:
    """Write serial traffic in fixed-width columns for terminal readability."""
    message = "%-8s origin=%-36s port=%-16s command=%-10r"
    arguments: tuple[object, ...] = (event, origin, port, command)
    if response is not None:
        message += " response=%r"
        arguments += (response,)
    LOGGER.info(message, *arguments)


@dataclass(frozen=True)
class DeviceTarget:
    port: str
    serial_number: str | None


@dataclass(frozen=True)
class Request:
    identifier: int
    payload: str
    expect_response: bool
    origin: str
    drain_response: bool = False
    response_terminator: str | None = None


def discover_usb_targets() -> list[tuple[DeviceTarget, str, str | None, str | None]]:
    """Return USB serial devices with their optional SynthNV serial response."""
    targets: list[tuple[DeviceTarget, str, str | None, str | None]] = []
    for port in list_ports.comports():
        if port.vid is None:
            continue
        LOGGER.info("probing USB serial device port=%s", port.device)
        serial_number, probe_error = _probe_serial_number(port.device)
        details = " · ".join(part for part in (port.description, port.manufacturer) if part)
        usb_id = f"{port.vid:04X}:{port.pid:04X}" if port.pid is not None else f"{port.vid:04X}"
        description = f"{details} · {usb_id}" if details else usb_id
        targets.append((DeviceTarget(port.device, serial_number), description, serial_number, probe_error))
        if serial_number:
            LOGGER.info("SynthNV serial-number response port=%s serial=%r", port.device, serial_number)
        elif probe_error:
            LOGGER.warning("serial probe failed port=%s reason=%s", port.device, probe_error)
        else:
            LOGGER.info("no SynthNV serial-number response port=%s", port.device)
    return targets


def discover_synthnv_targets() -> list[tuple[DeviceTarget, str, str | None, str | None]]:
    """Return only USB serial devices that answer the SynthNV `-` command."""
    return [target for target in discover_usb_targets() if target[2] is not None]


def _probe_serial_number(port: str) -> tuple[str | None, str | None]:
    """Ask a USB serial device for the documented SynthNV `-` response."""
    try:
        with serial.Serial(port, BAUD_RATE, timeout=0.5, write_timeout=0.5) as connection:
            # USB serial adapters can reset the device when their port opens.
            # The legacy UI waited 200 ms before its first command as well.
            sleep(0.2)
            connection.reset_input_buffer()
            log_command("sending", "automatic startup probe", "-", port=port)
            connection.write(b"-")
            connection.flush()
            response = connection.read_until(b"\n").decode("utf-8", errors="replace").strip()
    except (serial.SerialException, OSError) as error:
        LOGGER.warning("could not probe serial number port=%s error=%s", port, error)
        return None, serial_access_hint(error)
    return response or None, None


class DiscoveryWorker(QThread):
    """Probe candidate USB serial devices without pausing the startup dialog."""

    targets_found = Signal(object)

    def run(self) -> None:
        # The dialog keeps unresponsive devices non-selectable, but still shows
        # access errors so Linux users can fix permissions without guessing.
        self.targets_found.emit(discover_usb_targets())


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
        log_command("queued", request.origin, request.payload)
        self._requests.put(request)

    def identify(self, serial_number: str) -> None:
        """Enable safe reconnect matching after the device serial query completes."""
        if serial_number.strip():
            self._target = DeviceTarget(self._target.port, serial_number.strip())

    def stop(self) -> None:
        LOGGER.info("stopping serial worker")
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
            LOGGER.info("reconnect skipped: original serial number is not currently available")
            return False
        try:
            self._serial = serial.Serial(port, BAUD_RATE, timeout=RESPONSE_TIMEOUT_SECONDS, write_timeout=1)
        except (serial.SerialException, OSError, UnicodeError) as error:
            message = serial_access_hint(error)
            LOGGER.warning("could not open serial port=%s error=%s", port, error)
            if message != self._last_connection_error:
                self.disconnected.emit(message)
                self._last_connection_error = message
            return False
        # Do not issue startup queries while the device is still recovering
        # from a possible USB-serial open/reset transition.
        self.msleep(200)
        reconnected = self._was_connected
        self._was_connected = True
        self._last_connection_error = None
        LOGGER.info("serial connection opened port=%s reconnected=%s", port, reconnected)
        self.connected.emit(reconnected)
        return True

    def _device_is_present(self) -> bool:
        # `PortInfo.serial_number` is USB metadata and need not match the
        # SynthNV protocol serial number returned by `-`. The current port is
        # sufficient for passive presence detection; protocol matching happens
        # when searching for a replacement port after a real disconnect.
        return any(port.device == self._target.port for port in list_ports.comports())

    def _reconnect_port(self) -> str | None:
        if self._serial is None and not self._was_connected:
            return self._target.port
        # A port name can change after USB re-enumeration. Only resume a session
        # after a serial-number match; never attach to an arbitrary new device.
        if not self._target.serial_number:
            return None
        for target, _details, serial_number, _error in discover_synthnv_targets():
            if serial_number == self._target.serial_number:
                LOGGER.info("found reconnect candidate port=%s serial=%r", target.port, serial_number)
                self._target = target
                return target.port
        return None

    def _perform(self, request: Request) -> None:
        assert self._serial is not None
        try:
            self._serial.reset_input_buffer()
            log_command("sending", request.origin, request.payload, port=self._serial.port)
            self._serial.write(request.payload.encode("ascii"))
            self._serial.flush()
            response = ""
            if request.expect_response:
                if request.drain_response:
                    response = self._read_until_quiet(request.response_terminator)
                else:
                    response = self._serial.read_until(b"\n").decode("utf-8", errors="replace").rstrip("\r\n")
                if not response:
                    LOGGER.warning("timeout  origin=%-36s command=%-10r", request.origin, request.payload)
                    self.completed.emit(request.identifier, "", "No response before timeout")
                    return
                log_command("received", request.origin, request.payload, port=self._serial.port, response=response)
            else:
                log_command("sent", request.origin, request.payload, port=self._serial.port)
            self.completed.emit(request.identifier, response, "")
        except (serial.SerialException, OSError) as error:
            LOGGER.warning("serial command failed origin=%s command=%r error=%s", request.origin, request.payload, error)
            self._close()
            self.disconnected.emit(f"Disconnected: {error}")
            self.completed.emit(request.identifier, "", "Device disconnected")
            self._fail_pending_requests()

    def _read_until_quiet(self, terminator: str | None = None) -> str:
        """Read multi-part protocol replies (`?` and sweep result) completely."""
        assert self._serial is not None
        chunks: list[bytes] = []
        terminator_bytes = terminator.encode("ascii") if terminator else None
        deadline = monotonic() + RESPONSE_TIMEOUT_SECONDS
        quiet_since: float | None = None
        while monotonic() < deadline:
            waiting = self._serial.in_waiting
            if waiting:
                chunks.append(self._serial.read(waiting))
                if terminator_bytes and terminator_bytes in b"".join(chunks):
                    break
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
        LOGGER.info("serial connection closed")

    def _fail_pending_requests(self) -> None:
        """Never replay commands issued before a disconnect on a reconnected unit."""
        while True:
            try:
                request = self._requests.get_nowait()
            except Empty:
                return
            LOGGER.warning("cancelled origin=%-36s command=%-10r after disconnect", request.origin, request.payload)
            self.completed.emit(request.identifier, "", "Request cancelled by device disconnect")
