# AGENTS.md

## Project status

SynthNVControl is a Python 3.14+ desktop application managed with `uv`.
Source lives in `src/synthnvcontrol`, and the supported entry points are
`uv run synthnv`.
Run the test suite with `uv run python -m unittest discover -s tests -v`.

## Protocol implementation note

The official documentation does not accurately describe the observed frequency
response behavior. Device testing found that frequency setters accept MHz while
frequency-bearing queries return kHz; the application converts queried
frequency values to MHz before display and export. This has not been
exhaustively verified for every command or firmware revision. Treat
protocol-response handling cautiously and verify changes against physical
hardware before relying on them.

On tested firmware 2.5f, the sweep options `r` and `d` accept writes but their
`r?` and `d?` queries time out. Keep them write-only: do not include them in
startup queries or automatic read-backs.

## Working conventions

- Keep changes focused on the requested task and preserve unrelated user work.
- Prefer small, clear modules with explicit interfaces and type annotations where
  the selected language supports them.
- Put automated tests alongside the chosen test layout when adding behavior.
- Update `README.md` when setup, execution, configuration, or hardware
  requirements change.
- Do not commit credentials, private keys, device-specific secrets, generated
  build output, or local IDE settings.

## Validation

- Run the project's configured formatter, linter, and test suite before handing
  off code changes once those tools are present.
- For hardware-facing changes, separate transport logic from device-control
  logic and make it possible to test behavior without physical equipment.
- Report commands run and any validation that could not be performed.

## Git hygiene

- Use descriptive, imperative commit messages.
- Do not amend, reset, discard, or overwrite existing work unless explicitly
  requested.
- Keep generated files out of version control unless they are intentionally
  required for releases or deployment.
