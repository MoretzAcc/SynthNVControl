"""Qt windows for selecting a SynthNV and operating its documented fields."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QVBoxLayout, QWidget,
)

from synthnvcontrol.device import DeviceTarget, DiscoveryWorker, Request, SerialWorker
from synthnvcontrol.protocol import BY_CODE, COMMANDS, GROUPS, Command, FieldKind
from synthnvcontrol.storage import load_persistent, load_settings, save_persistent, save_settings


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
        connect = QPushButton("Connect")
        buttons.addWidget(refresh)
        buttons.addStretch()
        buttons.addWidget(connect)
        layout.addLayout(buttons)
        refresh.clicked.connect(self.refresh)
        connect.clicked.connect(self.accept_target)
        self.devices.itemDoubleClicked.connect(lambda _: self.accept_target())
        self.refresh()

    def refresh(self) -> None:
        if self._scanner is not None and self._scanner.isRunning():
            return
        self.devices.clear()
        self.devices.addItem("Scanning USB serial devices for SynthNV serial-number responses…")
        self._scanner = DiscoveryWorker()
        self._scanner.targets_found.connect(self.show_targets)
        self._scanner.start()

    def show_targets(self, targets: list[tuple[DeviceTarget, str]]) -> None:
        self.devices.clear()
        for target, details in targets:
            item = QListWidgetItem(f"{details}\nPort: {target.port} · Serial: {target.serial_number}")
            item.setData(Qt.ItemDataRole.UserRole, target)
            self.devices.addItem(item)
        if not targets:
            self.devices.addItem("No USB serial device responded with a SynthNV serial number.")

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
    def __init__(self, visible: set[str], persistent_enabled: bool, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._checks: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Visible fields are still queried and retained when hidden."))
        for group in GROUPS:
            box = QGroupBox(group)
            form = QFormLayout(box)
            for command in (item for item in COMMANDS if item.group == group):
                check = QCheckBox(command.label)
                check.setChecked(command.code in visible)
                self._checks[command.code] = check
                form.addRow(check)
            layout.addWidget(box)
        self.persistent = QCheckBox("Apply persistent device configuration after startup")
        self.persistent.setChecked(persistent_enabled)
        layout.addWidget(self.persistent)
        buttons = QHBoxLayout()
        save = QPushButton("Save")
        cancel = QPushButton("Cancel")
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)

    @property
    def visible(self) -> set[str]:
        return {code for code, check in self._checks.items() if check.isChecked()}


class FieldRow(QWidget):
    def __init__(self, command: Command, apply: Callable[[Command, str], None], query: Callable[[Command], None], action: Callable[[Command], None]) -> None:
        super().__init__()
        self.command = command
        layout = QGridLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.addWidget(QLabel(f"{command.label}\n<small>{command.code}</small>"), 0, 0)
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
            if command.kind is FieldKind.BOOLEAN:
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
        self.resize(1180, 780)
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
        refresh.clicked.connect(lambda: self.refresh_values())
        settings = QPushButton("Settings")
        settings.clicked.connect(self.open_settings)
        header.addWidget(refresh)
        header.addWidget(settings)
        layout.addLayout(header)
        controls = QHBoxLayout()
        export = QPushButton("Export values")
        export.clicked.connect(self.export_values)
        self.import_button = QPushButton("Import values")
        self.import_button.clicked.connect(self.import_values)
        self.persistent_import_button = QPushButton("Import persistent")
        self.persistent_import_button.clicked.connect(self.import_persistent)
        persistent_save = QPushButton("Save persistent")
        persistent_save.clicked.connect(self.save_persistent)
        for button in (export, self.import_button, self.persistent_import_button, persistent_save):
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
        self.persistent_import_button.setEnabled(False)

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
        self.persistent_import_button.setEnabled(True)
        self.status.setText("Connected" if not reconnected else "Reconnected — refreshing device state")
        self.log("[connection] Reconnected; refreshing values." if reconnected else "[connection] Connected.")
        self.refresh_values(after_startup=not self._startup_complete)

    def _disconnected(self, reason: str) -> None:
        self._connected_to_device = False
        self.form_container.setEnabled(False)
        self.manual.setEnabled(False)
        self.import_button.setEnabled(False)
        self.persistent_import_button.setEnabled(False)
        self.status.setText("Disconnected — waiting for the same serial number")
        self.log(f"[connection] {reason}")

    def _submit(self, payload: str, expect_response: bool, callback: Callable[[str, str], None] | None = None, drain_response: bool = False) -> None:
        if not self._connected_to_device:
            if callback:
                callback("", "Device is disconnected; command was not queued")
            return
        self._request_id += 1
        identifier = self._request_id
        if callback:
            self._callbacks[identifier] = callback
        self.client.submit(Request(identifier, payload, expect_response, drain_response))

    def _completed(self, identifier: int, response: str, error: str) -> None:
        callback = self._callbacks.pop(identifier, None)
        if callback:
            callback(response, error)

    def query_value(self, command: Command, quiet: bool = False, after: Callable[[], None] | None = None) -> None:
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
        self._submit(command.query_payload(), True, done, drain_response=command.code in {"?", "m"})

    def refresh_values(self, after_startup: bool = False) -> None:
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
                return
            self.query_value(commands[index], quiet=True, after=lambda: next_command(index + 1))
        next_command()

    def apply_value(self, command: Command, raw_value: str) -> None:
        try:
            value = command.normalize(raw_value)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid value", f"{command.label}: {error}")
            return
        payload = command.write_payload(value)
        self.log(f"> {payload}")
        self._submit(payload, False, lambda _response, error: self._after_set(command, error))

    def _after_set(self, command: Command, error: str) -> None:
        if error:
            self.log(f"[set {command.code}] {error}")
            return
        self.query_value(command, quiet=True, after=lambda: self._refresh_measured_power(command))

    def _refresh_measured_power(self, command: Command) -> None:
        if command.code in {"f", "a", "h"}:
            self.query_value(BY_CODE["w"], quiet=True)

    def run_action(self, command: Command) -> None:
        if QMessageBox.question(self, "Confirm device action", f"Run '{command.label}' on the SynthNV?") != QMessageBox.StandardButton.Yes:
            return
        self.log(f"> {command.code}")
        self._submit(command.code, False, lambda _response, error: self.log(f"[{command.label}] completed." if not error else f"[{command.label}] {error}"))

    def send_manual(self) -> None:
        payload = self.manual.text().strip()
        if not payload:
            return
        self.log(f"> {payload}")
        self._submit(payload, True, lambda response, error: self.log(response if not error else f"[manual] {error}"))

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.visible, bool(self.settings.get("use_persistent_configuration", False)), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.visible = dialog.visible
        self.settings["visible_fields"] = sorted(self.visible)
        self.settings["use_persistent_configuration"] = dialog.persistent.isChecked()
        save_settings(self.settings)
        self.rebuild_form()

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

    def apply_import_data(self, data: Any) -> None:
        values = data.get("values") if isinstance(data, dict) else None
        if not isinstance(values, dict):
            self.log("[import] Invalid configuration: expected an object with a values object.")
            return
        self.log("[import] Started.")
        pending: list[tuple[Command, str]] = []
        for code, raw_value in values.items():
            command = BY_CODE.get(code)
            if command is None:
                self.log(f"[import] Ignored unknown field {code!r}.")
                continue
            if not command.can_write:
                self.log(f"[import] Ignored non-writable field {code}.")
                continue
            try:
                value = command.normalize(raw_value)
            except ValueError as error:
                self.log(f"[import] Invalid {code}: {error}.")
                continue
            if self.values.get(code) != value:
                pending.append((command, value))
        def apply_next(index: int = 0) -> None:
            if index == len(pending):
                self.log("[import] Finished.")
                return
            command, value = pending[index]
            payload = command.write_payload(value)
            self.log(f"[import] Applying {payload}")
            self._submit(payload, False, lambda _r, error: self._after_import_set(command, error, lambda: apply_next(index + 1)))
        apply_next()

    def _after_import_set(self, command: Command, error: str, next_step: Callable[[], None]) -> None:
        if error:
            self.log(f"[import] {command.code}: {error}")
            next_step()
            return
        self.query_value(command, quiet=True, after=lambda: self._after_import_query(command, next_step))

    def _after_import_query(self, command: Command, next_step: Callable[[], None]) -> None:
        if command.code in {"f", "a", "h"}:
            self.query_value(BY_CODE["w"], quiet=True, after=next_step)
            return
        next_step()

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
