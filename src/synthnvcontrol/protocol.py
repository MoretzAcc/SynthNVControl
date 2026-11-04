"""Typed representation of the documented SynthNV serial protocol."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class FieldKind(StrEnum):
    BOOLEAN = "boolean"
    DECIMAL = "decimal"
    POWER = "power"
    INTEGER = "integer"
    HEX = "hex"
    READ_ONLY = "read_only"
    ACTION = "action"


@dataclass(frozen=True)
class Command:
    code: str
    label: str
    group: str
    kind: FieldKind
    default_visible: bool = True

    @property
    def can_write(self) -> bool:
        return self.kind not in {FieldKind.READ_ONLY, FieldKind.ACTION}

    @property
    def can_query(self) -> bool:
        return self.kind is not FieldKind.ACTION

    @property
    def exportable(self) -> bool:
        return self.code != "?"

    def query_payload(self) -> str:
        return self.code if self.kind is FieldKind.READ_ONLY else f"{self.code}?"

    def normalize(self, value: object) -> str:
        text = str(value).strip()
        if self.kind is FieldKind.BOOLEAN:
            if text not in {"0", "1"}:
                raise ValueError("must be 0 or 1")
            return text
        if self.kind is FieldKind.POWER:
            if not text.isdigit() or not 0 <= int(text) <= 63:
                raise ValueError("must be an integer from 0 to 63")
            return str(int(text))
        if self.kind is FieldKind.INTEGER:
            if not text.isdigit():
                raise ValueError("must be a non-negative integer")
            return str(int(text))
        if self.kind is FieldKind.DECIMAL:
            try:
                number = Decimal(text)
            except InvalidOperation as error:
                raise ValueError("must be a decimal number") from error
            if not number.is_finite():
                raise ValueError("must be finite")
            normalized = format(number.normalize(), "f")
            if "." in normalized:
                normalized = normalized.rstrip("0").rstrip(".")
            return normalized or "0"
        if self.kind is FieldKind.HEX:
            if not text or any(char not in "0123456789abcdefABCDEF" for char in text):
                raise ValueError("must contain hexadecimal digits only")
            return text.upper()
        return text

    def value_from_response(self, response: str) -> str:
        """Return a canonical value suitable for display and configuration files.

        The SynthNV protocol uses MHz for `f<value>` writes but reports queried
        frequency in kHz.  Keeping the application value in MHz prevents an
        exported configuration from becoming 1,000 times too large on import.
        """
        text = response.strip()
        if self.code == "f":
            try:
                return self.normalize(Decimal(text) / Decimal("1000"))
            except ValueError:
                return text
        if self.can_write:
            try:
                return self.normalize(text)
            except ValueError:
                return text
        return text

    def write_payload(self, value: str) -> str:
        """Build a setter payload in the exact format expected by the device."""
        # The vendor documents that an `f` setter needs a decimal point and at
        # least one digit after it, even for an integral MHz value.
        if self.code == "f" and "." not in value:
            value = f"{value}.0"
        return f"{self.code}{value}"


COMMANDS: tuple[Command, ...] = (
    Command("f", "Frequency (MHz)", "RF output", FieldKind.DECIMAL),
    Command("o", "RF output enabled", "RF output", FieldKind.BOOLEAN),
    Command("h", "High power range", "RF output", FieldKind.BOOLEAN),
    Command("a", "RF power setting (0–63)", "RF output", FieldKind.POWER),
    Command("D", "Power detector ADC", "RF output", FieldKind.READ_ONLY),
    Command("w", "Measured RF power (dBm)", "RF output", FieldKind.READ_ONLY),
    Command("V", "ADC voltage reference", "Calibration", FieldKind.DECIMAL),
    Command("Q", "Power measurement offset", "Calibration", FieldKind.DECIMAL),
    Command("x", "Internal reference", "Calibration", FieldKind.BOOLEAN),
    Command("p", "Phase lock status", "PLL", FieldKind.READ_ONLY),
    Command("*", "PLL comparator (MHz)", "PLL", FieldKind.DECIMAL),
    Command("H0", "PLL register 0", "PLL", FieldKind.HEX),
    Command("H1", "PLL register 1", "PLL", FieldKind.HEX),
    Command("H2", "PLL register 2", "PLL", FieldKind.HEX),
    Command("H3", "PLL register 3", "PLL", FieldKind.HEX),
    Command("H4", "PLL register 4", "PLL", FieldKind.HEX),
    Command("H5", "PLL register 5", "PLL", FieldKind.HEX),
    Command("C1", "GP ADC J8 pin 1", "GPIO", FieldKind.READ_ONLY),
    Command("C2", "GP ADC J8 pin 2", "GPIO", FieldKind.READ_ONLY),
    Command("#", "GP output J8 pin 3", "GPIO", FieldKind.BOOLEAN),
    Command("$", "GP output J8 pin 5", "GPIO", FieldKind.BOOLEAN),
    Command("v", "Firmware version", "Device", FieldKind.READ_ONLY),
    Command("+", "Model type", "Device", FieldKind.READ_ONLY),
    Command("-", "Serial number", "Device", FieldKind.READ_ONLY),
    Command("?", "Protocol help", "Device", FieldKind.READ_ONLY),
    Command("e", "Write EEPROM", "Device", FieldKind.ACTION),
    # Fields below are documented in the official serial protocol but were not
    # represented by the predecessor. They remain hidden by default.
    Command("l", "Sweep lower frequency (MHz)", "Sweep", FieldKind.DECIMAL, False),
    Command("u", "Sweep upper frequency (MHz)", "Sweep", FieldKind.DECIMAL, False),
    Command("s", "Sweep step size (MHz)", "Sweep", FieldKind.DECIMAL, False),
    Command("t", "Sweep step time (ms)", "Sweep", FieldKind.DECIMAL, False),
    Command("g", "Run sweep", "Sweep", FieldKind.BOOLEAN, False),
    Command("r", "Read detector while sweeping", "Sweep", FieldKind.BOOLEAN, False),
    Command("d", "Report points while sweeping", "Sweep", FieldKind.BOOLEAN, False),
    Command("m", "Sweep maximum and minimum", "Sweep", FieldKind.READ_ONLY, False),
    Command("c", "Continuous sweep", "Sweep", FieldKind.BOOLEAN, False),
    Command("F", "AM step time (µs)", "AM modulation", FieldKind.INTEGER, False),
    Command("q", "AM cycle repetitions", "AM modulation", FieldKind.INTEGER, False),
    Command("%", "AM gain (%)", "AM modulation", FieldKind.INTEGER, False),
    Command("@", "AM offset", "AM modulation", FieldKind.INTEGER, False),
    Command("B", "Run one AM burst", "AM modulation", FieldKind.ACTION, False),
    Command("A", "Continuous AM burst", "AM modulation", FieldKind.BOOLEAN, False),
    Command("P", "Pulse on time (µs)", "Pulse modulation", FieldKind.INTEGER, False),
    Command("O", "Pulse off time (µs)", "Pulse modulation", FieldKind.INTEGER, False),
    Command("R", "Pulse repetitions", "Pulse modulation", FieldKind.INTEGER, False),
    Command("M", "Pulse off amplitude", "Pulse modulation", FieldKind.INTEGER, False),
    Command("G", "Run one pulse burst", "Pulse modulation", FieldKind.ACTION, False),
    Command("j", "Continuous pulse", "Pulse modulation", FieldKind.BOOLEAN, False),
)

BY_CODE = {command.code: command for command in COMMANDS}
GROUPS = ("RF output", "Calibration", "PLL", "GPIO", "Sweep", "AM modulation", "Pulse modulation", "Device")
