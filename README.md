# SynthNVControl

> **AI-generated notice:** This project was primarily generated with AI assistance. Review it before production use.

SynthNVControl is a Windows and Linux desktop controller for Windfreak
SynthNV USB-serial signal generators. It uses Python 3.14+, [uv](https://docs.astral.sh/uv/),
PySide6, and pyserial.

## Run

Install Python 3.14 or later and [uv](https://docs.astral.sh/uv/), then run the
following from the repository root:

```bash
uv run synthnv
```

The first run creates the virtual environment and installs dependencies. Select
the SynthNV serial port in the connection window to open the controller.

### Linux serial-port access

The device name depends on the installed Linux driver; `/dev/ttyACM0` and
`/dev/ttyUSB0` are examples only. Use the port shown by the application, then
inspect its owning group:

```bash
PORT=/dev/ttyACM0  # Replace with the port shown by the application.
ls -l "$PORT"
```

Then add the current user to that group; it is commonly `dialout` or `uucp`:

```bash
sudo usermod -aG dialout "$USER"
```

Sign out and back in before starting the application again. Replace `dialout`
with the group reported by `ls` when necessary. Do not run the GUI with `sudo`:
it gives the full application unnecessary administrator access and can create
root-owned project, settings, or export files.

### Windows serial-port access

Install the vendor virtual-COM driver if the device does not appear. Windfreak
provides driver and product resources on the [official SynthNV product page](https://windfreaktech.com/product/rf-signal-generator-and-power-detector/).

## Features

- Reads every queryable persisted device field at startup. The `r` and `d`
  sweep options are write-only on tested firmware. Settings controls which
  fields are shown; hidden fields remain available for import and export.
- Groups RF output, calibration, PLL, GPIO, sweep, AM, pulse, and device
  controls in the main window, with a compact serial console.
- Imports and exports device values as JSON. Import temporarily disables RF
  output, applies changed writable fields, then restores its prior RF-output
  state; errors and changes are reported in the console.
- Saves an optional local persistent device-value profile, applied after the
  initial device read. Local `settings.json` and `persistent_configuration.json`
  are created from tracked defaults and ignored by Git.
- Detects serial transport failures. Writes and imports are disabled while the
  device is disconnected, while export remains available. A device that reports
  the same serial number may reconnect automatically; cached writable values
  are restored with RF output disabled, then verified. Interrupted commands are
  never replayed.

RF power is shown as the documented `0`–`63` register value. The vendor does
not publish a fixed conversion to output dBm; use the device's `w` value as its
power measurement.

## Hardware and recovery

Follow the limits and connection instructions in the current vendor
documentation. Before connecting RF output to a receiver, spectrum analyser,
or other equipment, verify compatible power limits, impedance, attenuation,
and external-power requirements. Incorrect RF or power connections can damage
the SynthNV or connected equipment.

Long-running sweep or modulation programs can stop USB command processing.
Automatic recovery is therefore safest for ordinary idle use only. If the
device has no reported serial number, or an operation was active when it
disconnects, export values when possible and restart the application after the
hardware is restored.

## Documentation

The `docs/` directory contains vendor PDFs kept for local development
reference. Consult the current official sources and their applicable terms
before redistributing them:

- [Serial protocol](https://windfreaktech.com/wp-content/uploads/docs/synthnv/serialcomm.pdf)
- [Operating instructions](https://windfreaktech.com/wp-content/uploads/docs/synthnv/readme.pdf)
- [Datasheet](https://windfreaktech.com/wp-content/uploads/docs/synthnv/rf-%20network-analyzer-synthnv.pdf)

The serial protocol is marked preliminary by the vendor. Verify device
behavior and limits on physical hardware before relying on it.

## Troubleshooting

- **No device listed:** reconnect the USB cable, verify the Windows driver or
  Linux serial-group membership, and restart the application.
- **Disconnected:** export remains enabled; reconnect the same unit and wait
  for its state refresh, or restart after exporting values.
- **No response during a sweep or modulation:** stop or power-cycle the device,
  then restart the application. The application does not retry the interrupted
  command.

## Development

```bash
uv run python -m unittest discover -s tests -v
uv run python -m compileall src
```

See `AGENTS.md` for contributor conventions and `LEGACY_ISSUES.md` for the
predecessor audit.

## License

This project is licensed under the [MIT License](LICENSE).
