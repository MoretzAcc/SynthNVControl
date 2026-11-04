from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from synthnvcontrol.device import discover_synthnv_targets, discover_usb_targets
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

    def test_sweep_output_options_are_write_only(self) -> None:
        for code in ("r", "d"):
            self.assertTrue(BY_CODE[code].can_write)
            self.assertFalse(BY_CODE[code].can_query)

    def test_startup_discovery_keeps_usb_devices_without_a_serial_response(self) -> None:
        ports = [
            SimpleNamespace(device="/dev/ttyUSB0", vid=0x1A2B, pid=0x0001, description="Candidate", manufacturer="Vendor"),
            SimpleNamespace(device="/dev/ttyUSB1", vid=0x1A2B, pid=0x0002, description="No response", manufacturer="Vendor"),
            SimpleNamespace(device="/dev/ttyS0", vid=None, pid=None, description="Built-in", manufacturer=None),
        ]
        with patch("synthnvcontrol.device.list_ports.comports", return_value=ports), patch(
            "synthnvcontrol.device._probe_serial_number", side_effect=[("SN-42", None), (None, "Access denied")]
        ) as probe:
            targets = discover_usb_targets()
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0][0].serial_number, "SN-42")
        self.assertIsNone(targets[1][0].serial_number)
        self.assertEqual(targets[1][3], "Access denied")
        self.assertEqual(probe.call_args_list, [call("/dev/ttyUSB0"), call("/dev/ttyUSB1")])

    def test_startup_selector_only_keeps_devices_with_a_serial_response(self) -> None:
        targets = [
            (SimpleNamespace(port="/dev/ttyUSB0"), "SynthNV", "SN-42", None),
            (SimpleNamespace(port="/dev/ttyUSB1"), "Other device", None, "No response"),
        ]
        with patch("synthnvcontrol.device.discover_usb_targets", return_value=targets):
            responsive = discover_synthnv_targets()
        self.assertEqual(responsive, [targets[0]])



if __name__ == "__main__":
    unittest.main()
