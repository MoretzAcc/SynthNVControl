# SynthNV Pro discussion

This document tracks the compatibility review between SynthNVControl's current
SynthNV support and the SynthNV Pro serial API.

Reference: [WFT_NVP_SerialProgramming_API_1.pdf](https://windfreaktech.com/wp-content/uploads/2019/10/WFT_NVP_SerialProgramming_API_1.pdf)

## Questions under review

1. Which protocol commands and behaviours are shared by SynthNV and SynthNV Pro?
2. Which differences affect device discovery, reading values, writing values,
   imports, or recovery?
3. Does the Pro documentation provide reliable additional information for the
   existing SynthNV implementation?
4. Can this application safely support both devices, and what device-specific
   handling would be needed?

## Review result

The current serial transport is likely able to discover a SynthNV Pro: both
devices use USB virtual serial communication, case-sensitive whole command
packets without a line terminator, newline replies, and the `-` serial-number
query. This makes port discovery and serial-number-based reconnect compatible
in principle.

The current SynthNV field model is not safe for SynthNV Pro control. Important
semantic differences include:

- SynthNV uses `o` for RF output and `h` for power range; the Pro API documents
  `h` as RF mute and does not document `o` for this purpose.
- `a` is `0`–`63` on SynthNV but a `0`–`4000` VGA-DAC value on Pro.
- `D`, `V`, `x`, `*`, `@`, and pulse modulation fields have different meanings
  or value domains. In particular, Pro supports three `x` reference states.
- SynthNV observed frequency queries return kHz; the Pro API documents MHz
  replies. A shared frequency-response conversion would be wrong.
- Pro has additional commands and uses `EOM` to finish streamed sweep output;
  SynthNV ends this stream with `endofsweep.`.

The Pro API confirms useful transport information already used by this project:
whole packets without CR/LF, newline replies, the `-` serial identifier, and
the fact that active sweep/modulation modes can stop USB command processing. It
also supports treating `w` as a detector/input measurement rather than an RF
output-level setting.

## Additional Pro-to-SynthNV inferences

The Pro API independently confirms several behaviours that the SynthNV
documentation also describes, so they are useful for reviewing the normal
device implementation:

- With continuous sweep enabled (`c1`), a `g1` sweep does not emit the normal
  `endofsweep.` marker. The application must not wait for that marker in this
  mode, and it should prevent `r1` or `d1` while continuous sweep is enabled.
- Writing EEPROM while a sweep or modulation mode is active can preserve a
  state that prevents normal USB communication after the next boot. The Write
  EEPROM confirmation should call this out explicitly.
- The existing treatment of `w` as a detector/input measurement independent of
  output-level changes is appropriate. The Pro documentation does not justify
  coupling it to RF output power.

The Pro-only numeric timing and modulation limits should not be imposed on
SynthNV without normal-device hardware validation.

## Compatibility decision

SynthNVControl should currently support only SynthNV. It should detect a model
string containing `SynthNVP` from `+` and show that SynthNV Pro is not yet
supported before any field refresh, import, or restore occurs. Supporting Pro
requires a separate protocol profile with its own command definitions,
validation, response parsing, import rules, and sweep-stream terminator. Do
not reuse SynthNV persistent profiles with a Pro device.

## Sources

- [SynthNV Pro serial API](https://windfreaktech.com/wp-content/uploads/2019/10/WFT_NVP_SerialProgramming_API_1.pdf), especially pages 2–3, 5–17.
- [SynthNV serial protocol](https://windfreaktech.com/wp-content/uploads/docs/synthnv/serialcomm.pdf), especially pages 1–3.
