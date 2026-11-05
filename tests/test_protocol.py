from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QPushButton
from synthnvcontrol.device import DeviceTarget, discover_synthnv_targets, discover_usb_targets
from synthnvcontrol.protocol import BY_CODE, COMMANDS
from synthnvcontrol.storage import load_json
from synthnvcontrol.ui import FieldRow, MainWindow, PersistentProfileDialog, StartupDialog, ToggleSwitch


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_frequency_query_is_converted_from_khz_to_mhz(self) -> None:
        self.assertEqual(BY_CODE["f"].value_from_response("1000000\n"), "1000")
        self.assertEqual(BY_CODE["f"].write_payload("1000"), "f1000.0")

    def test_all_frequency_queries_are_converted_from_khz_to_mhz(self) -> None:
        for code in ("f", "l", "u", "s", "*"):
            with self.subTest(code=code):
                self.assertEqual(BY_CODE[code].value_from_response("2000000"), "2000")
        self.assertEqual(
            BY_CODE["m"].value_from_response("4000000\n-22.217\n50000\n-28.312"),
            "4000\n-22.217\n50\n-28.312",
        )

    def test_power_and_boolean_validation(self) -> None:
        self.assertEqual(BY_CODE["a"].normalize("063"), "63")
        self.assertEqual(BY_CODE["o"].normalize("1"), "1")
        with self.assertRaises(ValueError):
            BY_CODE["a"].normalize("64")
        with self.assertRaises(ValueError):
            BY_CODE["o"].normalize("yes")

    def test_frequency_limits_and_sweep_step_are_validated(self) -> None:
        self.assertEqual(BY_CODE["f"].normalize("34.4"), "34.4")
        self.assertEqual(BY_CODE["u"].normalize("4400"), "4400")
        with self.assertRaises(ValueError):
            BY_CODE["f"].normalize("34.3")
        with self.assertRaises(ValueError):
            BY_CODE["s"].normalize("0")

    def test_documented_extended_commands_are_present_and_hidden_by_default(self) -> None:
        defaults = json.loads((Path(__file__).resolve().parents[1] / "settings_default.json").read_text())
        for code in ("l", "u", "s", "t", "g", "B", "P", "G", "j"):
            self.assertIn(code, BY_CODE)
            self.assertNotIn(code, defaults["visible_fields"])
        self.assertFalse(hasattr(BY_CODE["l"], "default_visible"))
        self.assertGreaterEqual(len(COMMANDS), 45)

    def test_internal_reference_is_grouped_with_pll_status(self) -> None:
        self.assertEqual(BY_CODE["x"].group, "PLL")

    def test_sweep_output_options_are_write_only(self) -> None:
        for code in ("r", "d"):
            self.assertTrue(BY_CODE[code].can_write)
            self.assertFalse(BY_CODE[code].can_query)

    def test_rf_output_and_write_only_values_are_not_exported(self) -> None:
        for code in ("o", "r", "d", "?"):
            self.assertFalse(BY_CODE[code].exportable)

    def test_startup_discovery_keeps_usb_devices_without_a_serial_response(self) -> None:
        ports = [
            SimpleNamespace(device="/dev/ttyUSB0", vid=0x1A2B, pid=0x0001, description="Candidate", manufacturer="Vendor"),
            SimpleNamespace(device="/dev/ttyUSB1", vid=0x1A2B, pid=0x0002, description="No response", manufacturer="Vendor"),
            SimpleNamespace(device="/dev/ttyS0", vid=None, pid=None, description="Built-in", manufacturer=None),
        ]
        with patch("synthnvcontrol.device.list_ports.comports", return_value=ports), patch(
            "synthnvcontrol.device._probe_serial_number", side_effect=[("SN-42", None), (None, "Access denied")]
        ) as probe, patch("synthnvcontrol.device._probe_model_type", return_value=("WFT SynthNV 42", None)):
            targets = discover_usb_targets()
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0][0].serial_number, "SN-42")
        self.assertIsNone(targets[1][0].serial_number)
        self.assertEqual(targets[1][3], "Access denied")
        self.assertEqual(probe.call_args_list, [call("/dev/ttyUSB0"), call("/dev/ttyUSB1")])

    def test_startup_selector_only_keeps_devices_with_a_serial_response(self) -> None:
        targets = [
            (SimpleNamespace(port="/dev/ttyUSB0", model_type="WFT SynthNV 42"), "SynthNV", "SN-42", None),
            (SimpleNamespace(port="/dev/ttyUSB1", model_type=None), "Other device", None, "No response"),
        ]
        with patch("synthnvcontrol.device.discover_usb_targets", return_value=targets):
            responsive = discover_synthnv_targets()
        self.assertEqual(responsive, [targets[0]])

    def test_startup_disables_a_recognized_foreign_model(self) -> None:
        with patch.object(StartupDialog, "refresh"):
            dialog = StartupDialog()
        dialog.show_targets(
            [(DeviceTarget("/dev/ttyUSB0", "SN-42", "WFT SynthNVP 42"), "Windfreak", "SN-42", None)]
        )
        item = dialog.devices.item(0)
        self.assertFalse(bool(item.flags() & Qt.ItemFlag.ItemIsEnabled))
        self.assertIn("SynthNVP", item.text())

    def test_startup_shows_access_help_for_permission_denied_ports(self) -> None:
        with patch.object(StartupDialog, "refresh"):
            dialog = StartupDialog()
        dialog.show_targets(
            [(SimpleNamespace(port="/dev/ttyACM0"), "SynthNV", None, "Permission denied")]
        )
        self.assertEqual(dialog._inaccessible_ports, ["/dev/ttyACM0"])
        self.assertFalse(dialog.access_warning.isHidden())
        self.assertFalse(dialog.access_help_button.isHidden())

    def test_boolean_controls_show_and_send_their_semantic_state(self) -> None:
        applied: list[tuple[str, str]] = []
        apply = lambda command, value: applied.append((command.code, value))
        query = lambda _command: None
        action = lambda _command: None

        output = FieldRow(BY_CODE["o"], apply, query, action)
        output.show_value("1")
        self.assertIsInstance(output.editor, QPushButton)
        self.assertTrue(output.editor.isChecked())
        self.assertEqual(output.editor.text(), "RF Output: ON")
        output.editor.click()
        self.assertEqual(applied.pop(), ("o", "0"))

        power_range = FieldRow(BY_CODE["h"], apply, query, action)
        power_range.show_value("1")
        self.assertIsInstance(power_range.editor, ToggleSwitch)
        self.assertTrue(power_range.editor.isChecked())
        power_range.editor.click()
        self.assertEqual(applied.pop(), ("h", "0"))

        gpio = FieldRow(BY_CODE["#"], apply, query, action)
        gpio.show_value("1")
        self.assertIsInstance(gpio.editor, QPushButton)
        self.assertTrue(gpio.editor.isChecked())
        gpio.editor.click()
        self.assertEqual(applied.pop(), ("#", "0"))

        sweep_reading = FieldRow(BY_CODE["r"], apply, query, action)
        self.assertIsNone(sweep_reading.editor)
        enabled = next(button for button in sweep_reading.findChildren(QPushButton) if button.text() == "Send enabled")
        enabled.click()
        self.assertEqual(applied.pop(), ("r", "1"))

        for code in ("g", "c", "A"):
            with self.subTest(code=code):
                control = FieldRow(BY_CODE[code], apply, query, action)
                self.assertIsInstance(control.editor, QPushButton)

    def test_enter_applies_a_text_field_value(self) -> None:
        applied: list[tuple[str, str]] = []
        row = FieldRow(
            BY_CODE["f"],
            lambda command, value: applied.append((command.code, value)),
            lambda _command: None,
            lambda _command: None,
        )
        assert isinstance(row.editor, QLineEdit)
        row.editor.setText("1000")
        row.editor.returnPressed.emit()
        self.assertEqual(applied, [("f", "1000")])

    def test_toggle_switch_uses_its_whole_visible_area_as_a_hitbox(self) -> None:
        switch = ToggleSwitch()
        self.assertTrue(switch.hitButton(QPoint(44, 12)))
        self.assertFalse(switch.hitButton(QPoint(46, 12)))

    def test_one_shot_bursts_align_with_value_editors(self) -> None:
        apply = lambda _command, _value: None
        query = lambda _command: None
        action = lambda _command: None
        for code in ("B", "G"):
            with self.subTest(code=code):
                row = FieldRow(BY_CODE[code], apply, query, action)
                button = row.findChild(QPushButton)
                assert button is not None
                position = row.layout().getItemPosition(row.layout().indexOf(button))
                self.assertEqual(position[:2], (0, 2))
                self.assertEqual(position[2:], (1, 1))

    def test_setting_rf_controls_does_not_refresh_measured_rf_power(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.values = {}
        window.rows = {}
        window.query_value = MagicMock()

        window._after_set(BY_CODE["a"], "10", "")

        window.query_value.assert_called_once_with(
            BY_CODE["a"], quiet=True, origin="automatic readback"
        )

    def test_setting_internal_reference_refreshes_phase_lock_status(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.values = {}
        window.rows = {}
        window.query_value = MagicMock()

        window._after_set(BY_CODE["x"], "1", "")

        initial_call = window.query_value.call_args
        self.assertEqual(initial_call.args[0], BY_CODE["x"])
        initial_call.kwargs["after"]()
        self.assertEqual(window.query_value.call_args.args[0], BY_CODE["p"])
        self.assertTrue(window.query_value.call_args.kwargs["quiet"])
        window.query_value.call_args.kwargs["after"]()
        self.assertEqual(window.query_value.call_args.args[0], BY_CODE["*"])

    def test_unlocked_phase_status_is_visually_marked(self) -> None:
        row = FieldRow(BY_CODE["p"], lambda _command, _value: None, lambda _command: None, lambda _command: None)
        row.show_value("0")
        self.assertEqual(row.current.text(), "UNLOCKED (0)")
        self.assertIn("#c62828", row.current.styleSheet())

    def test_persistent_profile_has_a_dedicated_control_dialog(self) -> None:
        dialog = PersistentProfileDialog(True, lambda _enabled: None, lambda: None, lambda: None, None)
        self.assertEqual(dialog.windowTitle(), "Persistent profile")
        self.assertTrue(dialog.findChild(QCheckBox, "").isChecked())

    def test_field_rows_align_value_columns_across_groups(self) -> None:
        callbacks = (lambda _command, _value: None, lambda _command: None, lambda _command: None)
        rf_row = FieldRow(BY_CODE["a"], *callbacks)
        pll_row = FieldRow(BY_CODE["H0"], *callbacks)
        for row in (rf_row, pll_row):
            row.resize(900, 40)
            row.show()
        self.application.processEvents()
        self.assertEqual(rf_row.current.x(), pll_row.current.x())

    def test_raw_help_command_drains_the_complete_response(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.manual = QLineEdit("?")
        window.log = MagicMock()
        window._submit = MagicMock()

        window.send_manual()

        self.assertTrue(window._submit.call_args.kwargs["drain_response"])
        self.assertEqual(window.manual.text(), "")

    def test_raw_setter_does_not_wait_for_a_response(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.manual = QLineEdit("f1000.0")
        window.log = MagicMock()
        window._submit = MagicMock()

        window.send_manual()

        self.assertFalse(window._submit.call_args.args[1])

    def test_continuous_mode_is_not_read_back_after_setting(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.values = {}
        window.rows = {}
        window.query_value = MagicMock()

        window._after_set(BY_CODE["c"], "1", "")

        self.assertEqual(window.values["c"], "1")
        window.query_value.assert_not_called()

    def test_sweep_with_report_mode_collects_the_complete_stream(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.values = {"d": "1"}
        window.log = MagicMock()
        window._submit = MagicMock()

        window.apply_value(BY_CODE["g"], "1")

        self.assertTrue(window._submit.call_args.args[1])
        self.assertTrue(window._submit.call_args.kwargs["drain_response"])
        self.assertEqual(window._submit.call_args.kwargs["response_terminator"], "endofsweep.")

    def test_continuous_sweep_does_not_wait_for_an_end_marker(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.values = {"c": "1"}
        window.log = MagicMock()
        window._submit = MagicMock()

        window.apply_value(BY_CODE["g"], "1")

        self.assertFalse(window._submit.call_args.args[1])
        self.assertEqual(window._submit.call_args.args[2], "user continuous sweep")

    def test_persistent_profile_keeps_rf_output_disabled(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.values = {"o": "1"}
        window.rows = {}
        window._operation_active = False
        window._connected_to_device = True
        window._unrecoverable = False
        window._set_user_controls = MagicMock()
        window.log = MagicMock()
        submitted: list[str] = []

        def submit(payload, _expects, _origin, callback, **_kwargs):
            submitted.append(payload)
            callback("", "")

        window._submit = submit
        window.apply_import_data(
            {"version": 1, "values": {}},
            operation="persistent profile",
            restore_rf_output=False,
        )

        self.assertEqual(submitted, ["o0"])
        self.assertEqual(window.values["o"], "0")

    def test_invalid_local_json_uses_the_tracked_default_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            default = Path(directory) / "settings_default.json"
            path.write_text("{not valid JSON", encoding="utf-8")
            default.write_text('{"version": 1}', encoding="utf-8")
            self.assertEqual(load_json(path, default), {"version": 1})

    def test_protocol_help_is_console_only(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.values = {}
        window.rows = {"?": FieldRow(BY_CODE["?"], lambda _command, _value: None, lambda _command: None, lambda _command: None)}
        window.log = MagicMock()
        window._submit = MagicMock(
            side_effect=lambda _payload, _expects, _origin, callback, **_kwargs: callback("line one\nline two", "")
        )

        window.query_value(BY_CODE["?"], quiet=False)

        self.assertNotIn("?", window.values)
        self.assertEqual(window.rows["?"].current.text(), "—")
        window.log.assert_has_calls([call("> ?"), call("line one\nline two")])



if __name__ == "__main__":
    unittest.main()
