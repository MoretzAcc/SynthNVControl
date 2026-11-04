"""Qt windows for selecting a SynthNV and operating its documented fields."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QVBoxLayout, QWidget,
)

from synthnvcontrol.device import DeviceTarget, DiscoveryWorker, Request, SerialWorker
from synthnvcontrol.protocol import BY_CODE, COMMANDS, GROUPS, Command, FieldKind
from synthnvcontrol.storage import load_persistent, load_settings, save_persistent, save_settings


LOGGER = logging.getLogger(__name__)


class StartupDialog(QDialog):
    """Connection selection is intentionally separate from the main window."""

    def __init__(self) -> None:
        super().__init__()
        self.target: DeviceTarget | None = None
        self._scanner: DiscoveryWorker | None = None
        self.setWindowTitle("SynthNV Control — Connect")
        self.resize(680, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the SynthNV serial device."))
        self.devices = QListWidget()
        layout.addWidget(self.devices)
        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setDefault(True)
        buttons.addWidget(refresh)
        buttons.addStretch()
        buttons.addWidget(self.connect_button)
        layout.addLayout(buttons)
        refresh.clicked.connect(self.refresh)
        self.connect_button.clicked.connect(self.accept_target)
        self.devices.itemDoubleClicked.connect(lambda _: self.accept_target())
        self.refresh()

    def refresh(self) -> None:
        if self._scanner is not None and self._scanner.isRunning():
            return
        self.devices.clear()
        self.devices.addItem("Scanning USB serial devices and probing SynthNV serial-number responses…")
        self._scanner = DiscoveryWorker()
        self._scanner.targets_found.connect(self.show_targets)
        self._scanner.start()

    def show_targets(self, targets: list[tuple[DeviceTarget, str, str | None, str | None]]) -> None:
        self.devices.clear()
        for target, details, serial_response, probe_error in targets:
            response_text = serial_response or probe_error or "No response to SynthNV serial-number command"
            item = QListWidgetItem(f"{details}\nPort: {target.port} · Serial: {response_text}")
            item.setData(Qt.ItemDataRole.UserRole, target)
            self.devices.addItem(item)
        if targets:
            self.devices.setCurrentRow(0)
            self.connect_button.setFocus()
        else:
            self.devices.addItem("No USB serial devices found.")

    def accept_target(self) -> None:
        item = self.devices.currentItem()
        if item is None:
            return
        target = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(target, DeviceTarget):
            return
        self.target = target
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, visible: set[str], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(820, 620)
        self._checks: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Visible fields are still queried and retained when hidden."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        group_container = QWidget()
        groups_layout = QGridLayout(group_container)
        groups_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for group in GROUPS:
            box = QGroupBox(group)
            form = QVBoxLayout(box)
            for command in (item for item in COMMANDS if item.group == group):
                check = QCheckBox(command.label)
                check.setChecked(command.code in visible)
                self._checks[command.code] = check
                form.addWidget(check)
            index = GROUPS.index(group)
            groups_layout.addWidget(box, index // 2, index % 2)
        scroll.setWidget(group_container)
        layout.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        apply = QPushButton("Apply")
        cancel = QPushButton("Cancel")
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        layout.addLayout(buttons)
        cancel.clicked.connect(self.reject)
        apply.clicked.connect(self.accept)
        apply.setDefault(True)
        apply.setFocus()

    @property
    def visible(self) -> set[str]:
        return {code for code, check in self._checks.items() if check.isChecked()}


class FieldRow(QWidget):
    def __init__(self, command: Command, apply: Callable[[Command, str], None], query: Callable[[Command], None], action: Callable[[Command], None]) -> None:
        super().__init__()
        self.command = command
        layout = QGridLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        label = QLabel(f"{command.label}<br><small>{command.code}</small>")
        label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label, 0, 0)
        self.current = QLabel("—")
        self.current.setMinimumWidth(110)
        layout.addWidget(self.current, 0, 1)
        self.editor: QLineEdit | QComboBox | None = None
        if command.kind is FieldKind.ACTION:
            button = QPushButton(command.label)
            button.clicked.connect(lambda: action(command))
            layout.addWidget(button, 0, 2, 1, 2)
        elif command.kind is FieldKind.READ_ONLY:
            button = QPushButton("Query")
            button.clicked.connect(lambda: query(command))
            layout.addWidget(button, 0, 3)
        else:
            if command.input_kind is FieldKind.BOOLEAN:
                editor = QComboBox()
                editor.addItem("0 — Off", "0")
                editor.addItem("1 — On", "1")
                self.editor = editor
            else:
                self.editor = QLineEdit()
            layout.addWidget(self.editor, 0, 2)
            apply_button = QPushButton("Apply")
            apply_button.clicked.connect(self._apply)
            layout.addWidget(apply_button, 0, 3)
            if command.can_query:
                query_button = QPushButton("Query")
                query_button.clicked.connect(lambda: query(command))
                layout.addWidget(query_button, 0, 4)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 2)
        self._apply_callback = apply

    def _apply(self) -> None:
        assert self.editor is not None
        value = self.editor.currentData() if isinstance(self.editor, QComboBox) else self.editor.text()
        self._apply_callback(self.command, str(value))

    def show_value(self, value: str) -> None:
        self.current.setText(value or "—")
        if isinstance(self.editor, QComboBox) and value in {"0", "1"}:
            self.editor.setCurrentIndex(int(value))


class MainWindow(QMainWindow):
    def __init__(self, target: DeviceTarget) -> None:
        super().__init__()
        self.setWindowTitle("SynthNV Control")
        self.resize(1320, 860)
        self.settings = load_settings()
        self.visible = set(self.settings.get("visible_fields", []))
        self.values: dict[str, str] = {}
        self.rows: dict[str, FieldRow] = {}
        self._request_id = 0
        self._callbacks: dict[int, Callable[[str, str], None]] = {}
        self._startup_complete = False
        self._connected_to_device = False
        self.client = SerialWorker(target)
        self.client.connected.connect(self._connected)
        self.client.disconnected.connect(self._disconnected)
        self.client.completed.connect(self._completed)
        self._build()
        self.client.start()

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        header = QHBoxLayout()
        self.status = QLabel("Connecting…")
        self.status.setProperty("state", "waiting")
        header.addWidget(self.status, 1)
        refresh = QPushButton("Refresh values")
        refresh.clicked.connect(lambda: self.refresh_values(origin="user refresh"))
        settings = QPushButton("Settings")
        settings.clicked.connect(self.open_settings)
        header.addWidget(refresh)
        header.addWidget(settings)
        layout.addLayout(header)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("JSON"))
        export = QPushButton("Export to JSON…")
        export.setToolTip("Save the current SynthNV values to a JSON file.")
        export.clicked.connect(self.export_values)
        self.import_button = QPushButton("Import from JSON…")
        self.import_button.setToolTip("Apply changed writable values from a JSON file.")
        self.import_button.clicked.connect(self.import_values)
        controls.addWidget(export)
        controls.addWidget(self.import_button)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        controls.addWidget(separator)
        controls.addWidget(QLabel("Persistent profile"))
        self.persistent_startup = QCheckBox("Apply on startup")
        self.persistent_startup.setChecked(bool(self.settings.get("use_persistent_configuration", False)))
        self.persistent_startup.setToolTip("Apply the local persistent profile after reading the device at startup.")
        self.persistent_startup.toggled.connect(self.set_persistent_startup)
        self.load_profile_button = QPushButton("Load profile")
        self.load_profile_button.setToolTip("Apply the local persistent profile to the connected device.")
        self.load_profile_button.clicked.connect(self.import_persistent)
        self.save_profile_button = QPushButton("Save current as profile")
        self.save_profile_button.setToolTip("Replace the local persistent profile with the current device values.")
        self.save_profile_button.clicked.connect(self.save_persistent)
        for button in (self.persistent_startup, self.load_profile_button, self.save_profile_button):
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        self.form_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_container)
        splitter.addWidget(scroll)
        console_frame = QFrame()
        console_layout = QVBoxLayout(console_frame)
        console_layout.addWidget(QLabel("Console"))
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1_000)
        console_layout.addWidget(self.console)
        raw = QHBoxLayout()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("Raw command")
        send = QPushButton("Send")
        send.clicked.connect(self.send_manual)
        raw.addWidget(self.manual)
        raw.addWidget(send)
        console_layout.addLayout(raw)
        splitter.addWidget(console_frame)
        splitter.setSizes([800, 320])
        layout.addWidget(splitter, 1)
        self.rebuild_form()
        self.form_container.setEnabled(False)
        self.manual.setEnabled(False)
        self.import_button.setEnabled(False)
        self.load_profile_button.setEnabled(False)

    def rebuild_form(self) -> None:
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows.clear()
        for group in GROUPS:
            fields = [command for command in COMMANDS if command.group == group and command.code in self.visible]
            if not fields:
                continue
            box = QGroupBox(group)
            box_layout = QVBoxLayout(box)
            for command in fields:
                row = FieldRow(command, self.apply_value, self.query_value, self.run_action)
                self.rows[command.code] = row
                if command.code in self.values:
                    row.show_value(self.values[command.code])
                box_layout.addWidget(row)
            self.form_layout.addWidget(box)

    def log(self, text: str) -> None:
        self.console.appendPlainText(text)

    def _connected(self, reconnected: bool) -> None:
        self._connected_to_device = True
        self.form_container.setEnabled(True)
        self.manual.setEnabled(True)
        self.import_button.setEnabled(True)
        self.load_profile_button.setEnabled(True)
        if reconnected:
            recovery_values = {
                code: value
                for code, value in self.values.items()
                if code in BY_CODE and BY_CODE[code].can_write
            }
            self.status.setText("Reconnected — restoring previous device state")
            self.log("[connection] Reconnected; restoring previous device state.")
            self.apply_import_data(
                {"version": 1, "values": recovery_values},
                origin="automatic reconnect restore",
                force=True,
                operation="restore",
                on_complete=self._verify_reconnected_state,
            )
            return
        self.status.setText("Connected")
        self.log("[connection] Connected.")
        self.refresh_values(after_startup=True, origin="automatic startup refresh")

    def _disconnected(self, reason: str) -> None:
        self._connected_to_device = False
        self.form_container.setEnabled(False)
        self.manual.setEnabled(False)
        self.import_button.setEnabled(False)
        self.load_profile_button.setEnabled(False)
        self.status.setText("Disconnected — waiting for the same serial number")
        self.log(f"[connection] {reason}")

    def _submit(self, payload: str, expect_response: bool, origin: str, callback: Callable[[str, str], None] | None = None, drain_response: bool = False) -> None:
        if not self._connected_to_device:
            LOGGER.warning("blocked command while disconnected origin=%s command=%r", origin, payload)
            if callback:
                callback("", "Device is disconnected; command was not queued")
            return
        self._request_id += 1
        identifier = self._request_id
        if callback:
            self._callbacks[identifier] = callback
        self.client.submit(Request(identifier, payload, expect_response, origin, drain_response))

    def _completed(self, identifier: int, response: str, error: str) -> None:
        callback = self._callbacks.pop(identifier, None)
        if callback:
            callback(response, error)

    def query_value(self, command: Command, quiet: bool = False, after: Callable[[], None] | None = None, origin: str = "user query") -> None:
        if not quiet:
            self.log(f"> {command.query_payload()}")
        def done(response: str, error: str) -> None:
            if error:
                self.log(f"[query {command.code}] {error}")
            else:
                value = command.value_from_response(response)
                self.values[command.code] = value
                if command.code == "-":
                    self.client.identify(value)
                if command.code in self.rows:
                    self.rows[command.code].show_value(value)
                if not quiet:
                    self.log(response)
            if after:
                after()
        self._submit(command.query_payload(), True, origin, done, drain_response=command.code in {"?", "m"})

    def refresh_values(self, after_startup: bool = False, origin: str = "user refresh", on_complete: Callable[[], None] | None = None) -> None:
        # `?` is a long protocol diagnostic and `m` only has a value after a
        # sweep. All persisted/device-setting fields are still queried here.
        commands = [command for command in COMMANDS if command.can_query and command.code not in {"?", "m"}]
        def next_command(index: int = 0) -> None:
            if index == len(commands):
                if after_startup:
                    self._startup_complete = True
                    if self.settings.get("use_persistent_configuration", False):
                        self.log("[persistent] Applying persistent configuration.")
                        self.apply_import_data(load_persistent())
                if on_complete:
                    on_complete()
                return
            self.query_value(commands[index], quiet=True, after=lambda: next_command(index + 1), origin=origin)
        next_command()

    def apply_value(self, command: Command, raw_value: str) -> None:
        try:
            value = command.normalize(raw_value)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid value", f"{command.label}: {error}")
            return
        payload = command.write_payload(value)
        self.log(f"> {payload}")
        self._submit(payload, False, "user field edit", lambda _response, error: self._after_set(command, value, error))

    def _after_set(self, command: Command, value: str, error: str) -> None:
        if error:
            self.log(f"[set {command.code}] {error}")
            return
        if not command.can_query:
            self.values[command.code] = value
            if command.code in self.rows:
                self.rows[command.code].show_value(value)
            return
        self.query_value(command, quiet=True, after=lambda: self._refresh_measured_power(command), origin="automatic readback")

    def _refresh_measured_power(self, command: Command) -> None:
        if command.code in {"f", "a", "h"}:
            self.query_value(BY_CODE["w"], quiet=True, origin="automatic power refresh")

    def run_action(self, command: Command) -> None:
        if QMessageBox.question(self, "Confirm device action", f"Run '{command.label}' on the SynthNV?") != QMessageBox.StandardButton.Yes:
            return
        self.log(f"> {command.code}")
        self._submit(command.code, False, "user action", lambda _response, error: self.log(f"[{command.label}] completed." if not error else f"[{command.label}] {error}"))

    def send_manual(self) -> None:
        payload = self.manual.text().strip()
        if not payload:
            return
        self.log(f"> {payload}")
        self._submit(payload, True, "user raw command", lambda response, error: self.log(response if not error else f"[manual] {error}"))

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.visible, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.visible = dialog.visible
        self.settings["visible_fields"] = sorted(self.visible)
        save_settings(self.settings)
        self.rebuild_form()

    def set_persistent_startup(self, enabled: bool) -> None:
        self.settings["use_persistent_configuration"] = enabled
        save_settings(self.settings)

    def export_values(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export SynthNV values", "synthnv-values.json", "JSON files (*.json)")
        if not path:
            return
        data = {"version": 1, "values": {code: value for code, value in self.values.items() if BY_CODE[code].exportable}}
        Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.log(f"[export] Saved {len(data['values'])} values.")

    def import_values(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import SynthNV values", "", "JSON files (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "Import failed", str(error))
            return
        self.apply_import_data(data)

    def apply_import_data(
        self,
        data: Any,
        *,
        origin: str = "automatic import",
        force: bool = False,
        operation: str = "import",
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        values = data.get("values") if isinstance(data, dict) else None
        if not isinstance(values, dict):
            self.log(f"[{operation}] Invalid configuration: expected an object with a values object.")
            return
        try:
            previous_rf_output = BY_CODE["o"].normalize(self.values.get("o", "0"))
        except ValueError:
            previous_rf_output = "0"
        self.log(f"[{operation}] Started; RF output disabled during changes.")
        pending: list[tuple[Command, str]] = []
        for code, raw_value in values.items():
            command = BY_CODE.get(code)
            if command is None:
                self.log(f"[{operation}] Ignored unknown field {code!r}.")
                continue
            if not command.can_write:
                self.log(f"[{operation}] Ignored non-writable field {code}.")
                continue
            try:
                value = command.normalize(raw_value)
            except ValueError as error:
                self.log(f"[{operation}] Invalid {code}: {error}.")
                continue
            if code == "o":
                if value != previous_rf_output:
                    self.log(f"[{operation}] Preserved RF output state ({previous_rf_output}).")
                continue
            if force or self.values.get(code) != value:
                pending.append((command, value))

        def finish() -> None:
            payload = BY_CODE["o"].write_payload(previous_rf_output)
            self.log(f"[{operation}] Restoring RF output state to {previous_rf_output}.")
            self._submit(payload, False, f"{origin} RF restore", after_restore)

        def after_restore(_response: str, error: str) -> None:
            if error:
                self.log(f"[{operation}] Could not restore RF output: {error}")
            else:
                self.values["o"] = previous_rf_output
                if "o" in self.rows:
                    self.rows["o"].show_value(previous_rf_output)
            self.log(f"[{operation}] Finished.")
            if on_complete:
                on_complete()

        def apply_next(index: int = 0) -> None:
            if index == len(pending):
                finish()
                return
            command, value = pending[index]
            payload = command.write_payload(value)
            self.log(f"[{operation}] Applying {payload}")
            self._submit(payload, False, origin, lambda _r, error: self._after_import_set(command, value, error, lambda: apply_next(index + 1), operation))

        def after_disable(_response: str, error: str) -> None:
            if error:
                self.log(f"[{operation}] Could not disable RF output: {error}")
                if on_complete:
                    on_complete()
                return
            self.values["o"] = "0"
            if "o" in self.rows:
                self.rows["o"].show_value("0")
            apply_next()

        self._submit("o0", False, f"{origin} RF safety", after_disable)

    def _after_import_set(self, command: Command, value: str, error: str, next_step: Callable[[], None], operation: str) -> None:
        if error:
            self.log(f"[{operation}] {command.code}: {error}")
            next_step()
            return
        if not command.can_query:
            self.values[command.code] = value
            if command.code in self.rows:
                self.rows[command.code].show_value(value)
            next_step()
            return
        self.query_value(command, quiet=True, after=lambda: self._after_import_query(command, next_step), origin=f"{operation} readback")

    def _after_import_query(self, command: Command, next_step: Callable[[], None]) -> None:
        if command.code in {"f", "a", "h"}:
            self.query_value(BY_CODE["w"], quiet=True, after=next_step, origin="automatic import power refresh")
            return
        next_step()

    def _verify_reconnected_state(self) -> None:
        self.status.setText("Reconnected — verifying restored device state")
        self.refresh_values(origin="automatic reconnect verification", on_complete=lambda: self.status.setText("Connected"))

    def import_persistent(self) -> None:
        if QMessageBox.question(self, "Confirm import", "Apply the persistent device configuration now?") == QMessageBox.StandardButton.Yes:
            self.apply_import_data(load_persistent())

    def save_persistent(self) -> None:
        if QMessageBox.question(self, "Confirm save", "Replace the persistent device configuration with current values?") != QMessageBox.StandardButton.Yes:
            return
        save_persistent({code: value for code, value in self.values.items() if BY_CODE[code].exportable})
        self.log("[persistent] Saved current values.")

    def closeEvent(self, event: Any) -> None:
        self.client.stop()
        event.accept()
