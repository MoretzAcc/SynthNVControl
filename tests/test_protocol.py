from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
