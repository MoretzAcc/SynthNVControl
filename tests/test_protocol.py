from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from synthnvcontrol.device import discover_synthnv_targets
from synthnvcontrol.protocol import BY_CODE, COMMANDS


class ProtocolTests(unittest.TestCase):
    def test_frequency_query_is_converted_from_khz_to_mhz(self) -> None:
        self.assertEqual(BY_CODE["f"].value_from_response("1000000\n"), "1000")
        self.assertEqual(BY_CODE["f"].write_payload("1000"), "f1000.0")

    def test_power_and_boolean_validation(self) -> None:
        self.assertEqual(BY_CODE["a"].normalize("063"), "63")
        self.assertEqual(BY_CODE["o"].normalize("1"), "1")
        with self.assertRaises(ValueError):
            BY_CODE["a"].normalize("64")
        with self.assertRaises(ValueError):
            BY_CODE["o"].normalize("yes")

    def test_documented_extended_commands_are_present_and_hidden_by_default(self) -> None:
        for code in ("l", "u", "s", "t", "g", "B", "P", "G", "j"):
            self.assertIn(code, BY_CODE)
            self.assertFalse(BY_CODE[code].default_visible)
        self.assertGreaterEqual(len(COMMANDS), 45)

    def test_startup_discovery_only_keeps_usb_devices_with_a_serial_response(self) -> None:
        ports = [
            SimpleNamespace(device="/dev/ttyUSB0", vid=0x1A2B, pid=0x0001, description="Candidate", manufacturer="Vendor"),
            SimpleNamespace(device="/dev/ttyS0", vid=None, pid=None, description="Built-in", manufacturer=None),
        ]
        with patch("synthnvcontrol.device.list_ports.comports", return_value=ports), patch(
            "synthnvcontrol.device._probe_serial_number", return_value="SN-42"
        ) as probe:
            targets = discover_synthnv_targets()
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0][0].serial_number, "SN-42")
        probe.assert_called_once_with("/dev/ttyUSB0")


if __name__ == "__main__":
    unittest.main()
