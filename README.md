# SynthNVControl

> **AI-generated notice:** This project was primarily generated with AI assistance. Review it before production use.

SynthNVControl is a Windows and Linux desktop controller for Windfreak
SynthNV USB-serial signal generators. It uses Python 3.14+, [uv](https://docs.astral.sh/uv/),
PySide6, and pyserial.

Note that, as of now, this software is exclusively designed for the WFT SynthNV, and not for sister devices like the WFT SynthNV Pro.


## Run

Install Python 3.14 or later and [uv](https://docs.astral.sh/uv/), then run the
following from the repository root:

```bash
uv run synthnv
```

The first run creates the virtual environment and installs dependencies. Select
the SynthNV serial port in the connection window to open the controller.

### Linux serial-port access

The device name depends on the installed Linux driver; Use the port shown by the application, examples are `/dev/ttyACM0` and
`/dev/ttyUSB0`, then inspect its owning group:

```bash
ls -l "/dev/ttyACM0" # Replace with the port shown by the application.
```

Then add the current user to that group; it is commonly `dialout` or `uucp`:

```bash
sudo usermod -aG dialout "$USER"
```

Restart your PC before starting the application again. 
Do not run the GUI with `sudo`:
it gives the full application unnecessary administrator access and can create
root-owned project, settings, or export files which may lead to problems in the future.

### Windows serial-port access

Install the vendor virtual-COM driver if the device does not appear. Windfreak
provides driver and product resources on the [official SynthNV product page](https://windfreaktech.com/product/rf-signal-generator-and-power-detector/).

## Features

- Reads supported device-state fields at startup. The `r` and `d` sweep
  options are write-only on tested firmware. Field visibility changes only the
  UI; hidden supported fields remain retained and can be imported or exported
  where the protocol permits.
- Groups RF output, calibration, PLL, GPIO, sweep, AM, pulse, and device
  controls in the main window, with a compact serial console.
- Imports and exports device values as JSON. Import temporarily disables RF
  output, applies changed writable fields, then restores its prior RF-output
  state; errors and changes are reported in the console. RF output and
  write-only sweep settings are omitted from JSON and persistent profiles.
  Active continuous sweep or modulation modes are not restored from files.
- Provides a dedicated persistent-profile dialog for startup application and
  manual loading or saving. Local configuration files are ignored by Git.
  `settings_default.json` is the sole source of the initial field-visibility
  selection.
- Detects serial transport failures. Writes and imports are disabled while the
  device is disconnected, while export remains available. A device that reports
  the same serial number may reconnect automatically; eligible cached writable
  values are restored with RF output disabled, then verified. Interrupted
  commands are never replayed.

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

If a continuous mode does not answer during a refresh, the session is locked
and the console recommends a restart; export the last values read by the
application when useful.

## Documentation

Consult the current official sources and their applicable terms:

- [Serial protocol](https://windfreaktech.com/wp-content/uploads/docs/synthnv/serialcomm.pdf)
- [Operating instructions](https://windfreaktech.com/wp-content/uploads/docs/synthnv/readme.pdf)
- [Datasheet](https://windfreaktech.com/wp-content/uploads/docs/synthnv/rf-%20network-analyzer-synthnv.pdf)

The serial protocol is marked preliminary by the vendor. Verify device
behavior and limits on physical hardware before relying on it.

Protocol note: observed firmware accepts frequency writes in MHz but returns
frequency-bearing query responses in kHz. The application converts its modeled
frequency fields, including sweep extrema, to MHz for display and JSON files.

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
