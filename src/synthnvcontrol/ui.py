"""Qt windows for selecting a SynthNV and operating its documented fields."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QSignalBlocker, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from synthnvcontrol.device import DeviceTarget, DiscoveryWorker, Request, SerialWorker
from synthnvcontrol.protocol import BY_CODE, COMMANDS, GROUPS, Command, FieldKind
from synthnvcontrol.storage import load_persistent, load_settings, save_persistent, save_settings


LOGGER = logging.getLogger(__name__)
DEPENDENT_STATUS_CODES: dict[str, tuple[str, ...]] = {"x": ("p", "*")}
CONTINUOUS_MODE_CODES = {"c", "A", "j"}
NO_READBACK_CODES = CONTINUOUS_MODE_CODES | {"g"}


class StartupDialog(QDialog):
    """Connection selection is intentionally separate from the main window."""

    def __init__(self) -> None:
        super().__init__()
        self.target: DeviceTarget | None = None
        self._scanner: DiscoveryWorker | None = None
        self.setWindowTitle("SynthNV Control — Connect")
        self.resize(680, 360)
        self.settings = load_settings()
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
        connection_options = QVBoxLayout()
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Apply defaults after connecting"))
        self.persistent_startup = ToggleSwitch()
        self.persistent_startup.setChecked(bool(self.settings.get("use_persistent_configuration", False)))
        self.persistent_startup.toggled.connect(self.set_persistent_startup)
        profile_row.addWidget(self.persistent_startup)
        connection_options.addLayout(profile_row)
        connection_options.addWidget(self.connect_button)
        buttons.addLayout(connection_options)
        layout.addLayout(buttons)
        refresh.clicked.connect(self.refresh)
        self.connect_button.clicked.connect(self.accept_target)
        self.devices.itemDoubleClicked.connect(lambda _: self.accept_target())
        self.refresh()

    def set_persistent_startup(self, enabled: bool) -> None:
        self.settings["use_persistent_configuration"] = enabled
        save_settings(self.settings)

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
        first_selectable: int | None = None
        for target, details, serial_response, probe_error in targets:
            if not serial_response and not probe_error:
                continue
            response_text = serial_response or probe_error or "No response to SynthNV serial-number command"
            item = QListWidgetItem(f"{details}\nPort: {target.port} · Serial: {response_text}")
            if serial_response:
                item.setData(Qt.ItemDataRole.UserRole, target)
                if first_selectable is None:
                    first_selectable = self.devices.count()
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.devices.addItem(item)
        if first_selectable is not None:
            self.devices.setCurrentRow(first_selectable)
            self.connect_button.setFocus()
        else:
            self.devices.addItem("No accessible SynthNV device found.")

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
        self.setWindowTitle("Field visibility")
        self.resize(1_060, 780)
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


class PersistentProfileDialog(QDialog):
    """Controls for the local profile applied independently of UI settings."""

    def __init__(
        self,
        apply_on_startup: bool,
        set_apply_on_startup: Callable[[bool], None],
        load_profile: Callable[[], None],
        save_profile: Callable[[], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Persistent profile")
        self.resize(520, 250)
        layout = QVBoxLayout(self)
        description = QLabel(
            "A persistent profile is a local JSON file of SynthNV values. "
            "It can be automatically applied to the device when it is connected.\n\n"
            "Warning: this might override an already configured device."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        startup_row = QHBoxLayout()
        startup_row.addWidget(QLabel("Apply profile on startup"))
        startup = ToggleSwitch()
        startup.setChecked(apply_on_startup)
        startup.toggled.connect(set_apply_on_startup)
        startup_row.addWidget(startup)
        startup_row.addStretch()
        layout.addLayout(startup_row)
        actions = QHBoxLayout()
        load = QPushButton("Load profile now")
        load.clicked.connect(load_profile)
        save = QPushButton("Save current values as profile")
        save.clicked.connect(save_profile)
        actions.addWidget(load)
        actions.addWidget(save)
        layout.addLayout(actions)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close.setDefault(True)
        close.setFocus()
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)


class ToggleSwitch(QCheckBox):
    """Small two-state switch used for boolean SynthNV settings."""

    def __init__(self) -> None:
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(46, 24)

    def hitButton(self, position: QPoint) -> bool:
        """Make the complete painted switch respond to clicks."""
        return self.rect().contains(position)

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self.rect().adjusted(1, 3, -1, -3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2e7d32") if self.isChecked() else QColor("#777777"))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        diameter = track.height() - 4
        x = track.right() - diameter - 2 if self.isChecked() else track.left() + 2
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(x, track.top() + 2, diameter, diameter)


class FieldRow(QWidget):
    def __init__(self, command: Command, apply: Callable[[Command, str], None], query: Callable[[Command], None], action: Callable[[Command], None]) -> None:
        super().__init__()
        self.command = command
        layout = QGridLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        self.label = QLabel(f"{command.label}<br><small>{command.code}</small>")
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        self.label.setFixedWidth(220)
        layout.addWidget(self.label, 0, 0)
        self.current = QLabel("—")
        self.current.setFixedWidth(180)
        self.current.setWordWrap(True)
        self.current.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.current, 0, 1)
        self.editor: QLineEdit | QComboBox | QCheckBox | QPushButton | ToggleSwitch | None = None
        if command.kind is FieldKind.ACTION:
            button = QPushButton(command.label)
            button.clicked.connect(lambda: action(command))
            if command.code in {"B", "G"}:
                layout.addWidget(button, 0, 2)
            else:
                layout.addWidget(button, 0, 2, 1, 2)
        elif command.kind is FieldKind.READ_ONLY:
            button = QPushButton("Query")
            button.clicked.connect(lambda: query(command))
            layout.addWidget(button, 0, 3)
        else:
            if command.code == "o":
                self.editor = self._boolean_button(command, "RF Output")
            elif command.code in {"h", "x"}:
                labels = ("Low Power", "High Power") if command.code == "h" else ("External", "Internal")
                toggle_container = QWidget()
                toggle_layout = QHBoxLayout(toggle_container)
                toggle_layout.setContentsMargins(0, 0, 0, 0)
                toggle_layout.addWidget(QLabel(labels[0]))
                self.editor = ToggleSwitch()
                self.editor.toggled.connect(
                    lambda enabled: self._apply_callback(command, "1" if enabled else "0")
                )
                toggle_layout.addWidget(self.editor)
                toggle_layout.addWidget(QLabel(labels[1]))
                toggle_layout.addStretch()
                layout.addWidget(toggle_container, 0, 2)
            elif command.code in {"r", "d"}:
                controls = QWidget()
                controls_layout = QHBoxLayout(controls)
                controls_layout.setContentsMargins(0, 0, 0, 0)
                enabled = QPushButton("Send enabled")
                disabled = QPushButton("Send disabled")
                enabled.clicked.connect(lambda: self._apply_callback(command, "1"))
                disabled.clicked.connect(lambda: self._apply_callback(command, "0"))
                controls_layout.addWidget(enabled)
                controls_layout.addWidget(disabled)
                controls_layout.addStretch()
                layout.addWidget(controls, 0, 2)
            elif command.input_kind is FieldKind.BOOLEAN:
                self.editor = self._boolean_button(command)
            else:
                self.editor = QLineEdit()
            if command.code not in {"h", "x", "r", "d"}:
                layout.addWidget(self.editor, 0, 2)
            if command.input_kind is not FieldKind.BOOLEAN:
                apply_button = QPushButton("Apply")
                apply_button.clicked.connect(self._apply)
                if isinstance(self.editor, QLineEdit):
                    self.editor.returnPressed.connect(self._apply)
                layout.addWidget(apply_button, 0, 3)
            if command.can_query:
                query_button = QPushButton("Query")
                query_button.clicked.connect(lambda: query(command))
                layout.addWidget(query_button, 0, 4 if command.input_kind is not FieldKind.BOOLEAN else 3)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 2)
        self._apply_callback = apply

    def _boolean_button(self, command: Command, prefix: str = "") -> QPushButton:
        button = QPushButton(f"{prefix + ': ' if prefix else ''}OFF")
        button.setCheckable(True)
        button.setProperty("status_button", True)
        button.setProperty("status_prefix", prefix)
        button.setStyleSheet(
            "QPushButton:checked { background-color: #2e7d32; color: white; font-weight: bold; }"
        )
        button.toggled.connect(
            lambda enabled: self._apply_callback(command, "1" if enabled else "0")
        )
        return button

    def _apply(self) -> None:
        assert self.editor is not None
        value = self.editor.currentData() if isinstance(self.editor, QComboBox) else self.editor.text()
        self._apply_callback(self.command, str(value))

    def show_value(self, value: str) -> None:
        if self.command.code == "p" and value == "0":
            self.current.setText("UNLOCKED (0)")
            self.current.setStyleSheet(
                "background-color: #c62828; color: white; font-weight: bold; padding: 3px;"
            )
        else:
            self.current.setText(value or "—")
            self.current.setStyleSheet("")
        self.current.setToolTip(value)
        if (
            isinstance(self.editor, QPushButton)
            and self.editor.property("status_button")
            and value in {"0", "1"}
        ):
            with QSignalBlocker(self.editor):
                self.editor.setChecked(value == "1")
                prefix = str(self.editor.property("status_prefix"))
                self.editor.setText(f"{prefix + ': ' if prefix else ''}{'ON' if value == '1' else 'OFF'}")
        elif isinstance(self.editor, ToggleSwitch) and value in {"0", "1"}:
            with QSignalBlocker(self.editor):
                self.editor.setChecked(value == "1")
        elif isinstance(self.editor, QCheckBox) and value in {"0", "1"}:
            with QSignalBlocker(self.editor):
                self.editor.setChecked(value == "1")


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
        self._operation_active = False
        self._unrecoverable = False
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
        self.refresh_button = QPushButton("Refresh values")
        self.refresh_button.clicked.connect(lambda: self.refresh_values(origin="user refresh"))
        settings = QPushButton("Field visibility…")
        settings.clicked.connect(self.open_settings)
        header.addWidget(self.refresh_button)
        header.addWidget(settings)
        layout.addLayout(header)
        controls = QHBoxLayout()
        export = QPushButton("Export to JSON…")
        export.setToolTip("Save the current SynthNV values to a JSON file.")
        export.clicked.connect(self.export_values)
        self.import_button = QPushButton("Import from JSON…")
        self.import_button.setToolTip("Apply changed writable values from a JSON file.")
        self.import_button.clicked.connect(self.import_values)
        persistent_profile = QPushButton("More options…")
        persistent_profile.clicked.connect(self.open_persistent_profile)
        controls.addWidget(export)
        controls.addWidget(self.import_button)
        controls.addWidget(persistent_profile)
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
        self.manual.returnPressed.connect(self.send_manual)
        raw.addWidget(self.manual)
        raw.addWidget(send)
        console_layout.addLayout(raw)
        splitter.addWidget(console_frame)
        splitter.setSizes([800, 320])
        layout.addWidget(splitter, 1)
        self.rebuild_form()
        self._set_user_controls(False)

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
        if self._unrecoverable:
            self.status.setText("Session requires restart")
            return
        self._connected_to_device = True
        if reconnected:
            recovery_values = {
                code: value
                for code, value in self.values.items()
                if code in BY_CODE and BY_CODE[code].can_write
            }
            self._operation_active = True
            self._set_user_controls(False)
            self.status.setText("Reconnected — refreshing device state")
            self.log("[connection] Reconnected; comparing device state before restore.")
            self.refresh_values(
                origin="automatic reconnect refresh",
                on_complete=lambda: self.apply_import_data(
                    {"version": 1, "values": recovery_values},
                    origin="automatic reconnect restore",
                    operation="restore",
                    on_complete=self._verify_reconnected_state,
                    manage_operation=False,
                ),
            )
            return
        self._set_user_controls(True)
        self.status.setText("Connected")
        self.log("[connection] Connected.")
        self.refresh_values(after_startup=True, origin="automatic startup refresh")

    def _disconnected(self, reason: str) -> None:
        self._connected_to_device = False
        self._operation_active = False
        self._set_user_controls(False)
        self.status.setText("Disconnected — waiting for the same serial number")
        self.log(f"[connection] {reason}")

    def _set_user_controls(self, enabled: bool) -> None:
        self.form_container.setEnabled(enabled)
        self.manual.setEnabled(enabled)
        self.import_button.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)

    def _mark_unrecoverable(self, reason: str) -> None:
        self._unrecoverable = True
        self._operation_active = False
        self._set_user_controls(False)
        self.status.setText("Session requires restart")
        self.log(f"[connection] {reason} Restart required; saving values to JSON is recommended.")

    def _submit(
        self,
        payload: str,
        expect_response: bool,
        origin: str,
        callback: Callable[[str, str], None] | None = None,
        drain_response: bool = False,
        response_terminator: str | None = None,
    ) -> None:
        if self._unrecoverable:
            error = "Session requires restart; command was not queued"
        elif not self._connected_to_device:
            error = "Device is disconnected; command was not queued"
        elif self._operation_active and origin.startswith("user"):
            error = "Device state is being restored; command was not queued"
        else:
            error = ""
        if error:
            LOGGER.warning("blocked command while disconnected origin=%s command=%r", origin, payload)
            if callback:
                callback("", error)
            return
        self._request_id += 1
        identifier = self._request_id
        if callback:
            self._callbacks[identifier] = callback
        self.client.submit(Request(identifier, payload, expect_response, origin, drain_response, response_terminator))

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
                if command.code in CONTINUOUS_MODE_CODES:
                    self._mark_unrecoverable(
                        f"{command.label} did not respond; the device may be running a continuous program."
                    )
                    return
            else:
                if command.code == "?":
                    # The protocol help is a multi-line diagnostic, not a value.
                    if not quiet:
                        self.log(response)
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
                        self.apply_import_data(
                            load_persistent(),
                            operation="persistent startup",
                            restore_rf_output=False,
                        )
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
        if command.code == "g" and value == "1":
            self._submit(
                payload,
                True,
                "user sweep",
                lambda response, error: self._after_sweep_stream(value, response, error, self.values.get("d") == "1"),
                drain_response=True,
                response_terminator="endofsweep.",
            )
            return
        self._submit(payload, False, "user field edit", lambda _response, error: self._after_set(command, value, error))

    def _after_sweep_stream(self, value: str, response: str, error: str, show_stream: bool) -> None:
        if error:
            self.log(f"[sweep] {error}")
            return
        self.values["g"] = value
        if "g" in self.rows:
            self.rows["g"].show_value(value)
        if response and show_stream:
            self.log(response)

    def _after_set(self, command: Command, value: str, error: str) -> None:
        if error:
            self.log(f"[set {command.code}] {error}")
            return
        if not command.can_query or command.code in NO_READBACK_CODES:
            self.values[command.code] = value
            if command.code in self.rows:
                self.rows[command.code].show_value(value)
            return
        dependent_statuses = DEPENDENT_STATUS_CODES.get(command.code, ())
        if dependent_statuses:
            self.query_value(
                command,
                quiet=True,
                after=lambda: self._query_dependent_statuses(dependent_statuses),
                origin="automatic readback",
            )
            return
        self.query_value(command, quiet=True, origin="automatic readback")

    def _query_dependent_statuses(
        self, codes: tuple[str, ...], on_complete: Callable[[], None] | None = None
    ) -> None:
        """Refresh status values affected by a preceding setting change."""
        def query_next(index: int = 0) -> None:
            if index >= len(codes):
                if on_complete:
                    on_complete()
                return
            self.query_value(
                BY_CODE[codes[index]],
                quiet=True,
                after=lambda: query_next(index + 1),
                origin="automatic dependent-status refresh",
            )

        query_next()

    def run_action(self, command: Command) -> None:
        if QMessageBox.question(self, "Confirm device action", f"Run '{command.label}' on the SynthNV?") != QMessageBox.StandardButton.Yes:
            return
        self.log(f"> {command.code}")
        self._submit(command.code, False, "user action", lambda _response, error: self.log(f"[{command.label}] completed." if not error else f"[{command.label}] {error}"))

    def send_manual(self) -> None:
        payload = self.manual.text().strip()
        if not payload:
            return
        try:
            payload.encode("ascii")
        except UnicodeEncodeError:
            self.log("[manual] Commands must use ASCII characters.")
            return
        self.log(f"> {payload}")
        self.manual.clear()
        expect_response = self._manual_expects_response(payload)
        self._submit(
            payload,
            expect_response,
            "user raw command",
            lambda response, error: self.log(
                response if response else ("[manual] Command sent." if not error else f"[manual] {error}")
            ),
            drain_response=payload in {"?", "m"},
        )

    @staticmethod
    def _manual_expects_response(payload: str) -> bool:
        for command in sorted(COMMANDS, key=lambda item: len(item.code), reverse=True):
            if payload == command.query_payload():
                return True
            if payload.startswith(command.code):
                return False
        return True

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.visible, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.visible = dialog.visible
        self.settings["visible_fields"] = sorted(self.visible)
        save_settings(self.settings)
        self.rebuild_form()

    def open_persistent_profile(self) -> None:
        dialog = PersistentProfileDialog(
            bool(self.settings.get("use_persistent_configuration", False)),
            self.set_persistent_startup,
            self.import_persistent,
            self.save_persistent,
            self,
        )
        dialog.exec()

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
        manage_operation: bool = True,
        restore_rf_output: bool = True,
    ) -> None:
        if self._operation_active and manage_operation:
            self.log(f"[{operation}] Another device operation is already active.")
            return
        if manage_operation:
            self._operation_active = True
            self._set_user_controls(False)

        def complete() -> None:
            if manage_operation:
                self._operation_active = False
                if self._connected_to_device and not self._unrecoverable:
                    self._set_user_controls(True)
            if on_complete and not self._unrecoverable:
                on_complete()

        def abort(message: str) -> None:
            self.log(f"[{operation}] {message}")
            if operation == "restore":
                self._mark_unrecoverable("State restoration failed.")
                return
            complete()

        values = data.get("values") if isinstance(data, dict) else None
        if not isinstance(values, dict):
            abort("Invalid configuration: expected an object with a values object.")
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
            if code in CONTINUOUS_MODE_CODES and value == "1":
                self.log(f"[{operation}] Skipped active continuous mode {code} for session safety.")
                continue
            if force or self.values.get(code) != value:
                pending.append((command, value))

        def finish() -> None:
            if not restore_rf_output:
                self.values["o"] = "0"
                if "o" in self.rows:
                    self.rows["o"].show_value("0")
                self.log(f"[{operation}] RF output remains disabled after profile application.")
                self.log(f"[{operation}] Finished.")
                complete()
                return
            payload = BY_CODE["o"].write_payload(previous_rf_output)
            self.log(f"[{operation}] Restoring RF output state to {previous_rf_output}.")
            self._submit(payload, False, f"{origin} RF restore", after_restore)

        def after_restore(_response: str, error: str) -> None:
            if error:
                abort(f"Could not restore RF output: {error}")
                return
            else:
                self.values["o"] = previous_rf_output
                if "o" in self.rows:
                    self.rows["o"].show_value(previous_rf_output)
            self.log(f"[{operation}] Finished.")
            complete()

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
                abort(f"Could not disable RF output: {error}")
                return
            self.values["o"] = "0"
            if "o" in self.rows:
                self.rows["o"].show_value("0")
            apply_next()

        self._submit("o0", False, f"{origin} RF safety", after_disable)

    def _after_import_set(self, command: Command, value: str, error: str, next_step: Callable[[], None], operation: str) -> None:
        if error:
            self.log(f"[{operation}] {command.code}: {error}")
            if operation == "restore":
                self._mark_unrecoverable("State restoration failed.")
            else:
                self._operation_active = False
                if self._connected_to_device and not self._unrecoverable:
                    self._set_user_controls(True)
            return
        if not command.can_query or command.code in NO_READBACK_CODES:
            self.values[command.code] = value
            if command.code in self.rows:
                self.rows[command.code].show_value(value)
            next_step()
            return
        self.query_value(command, quiet=True, after=lambda: self._after_import_query(command, next_step), origin=f"{operation} readback")

    def _after_import_query(self, command: Command, next_step: Callable[[], None]) -> None:
        self._query_dependent_statuses(
            DEPENDENT_STATUS_CODES.get(command.code, ()), next_step
        )

    def _verify_reconnected_state(self) -> None:
        if not self._connected_to_device or self._unrecoverable:
            return
        self.status.setText("Reconnected — verifying restored device state")
        def complete() -> None:
            if not self._connected_to_device or self._unrecoverable:
                return
            self._operation_active = False
            self._set_user_controls(True)
            self.status.setText("Connected")

        self.refresh_values(origin="automatic reconnect verification", on_complete=complete)

    def import_persistent(self) -> None:
        if QMessageBox.question(self, "Confirm import", "Apply the persistent device configuration now?") == QMessageBox.StandardButton.Yes:
            self.apply_import_data(
                load_persistent(),
                operation="persistent profile",
                restore_rf_output=False,
            )

    def save_persistent(self) -> None:
        if QMessageBox.question(self, "Confirm save", "Replace the persistent device configuration with current values?") != QMessageBox.StandardButton.Yes:
            return
        save_persistent({code: value for code, value in self.values.items() if BY_CODE[code].exportable})
        self.log("[persistent] Saved current values.")

    def closeEvent(self, event: Any) -> None:
        self.client.stop()
        event.accept()
