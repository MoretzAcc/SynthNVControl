# AGENTS.md

## Project status

This repository is currently a skeleton for MoSynthNVControl. No application
source, dependency manifest, or test configuration has been established yet.
Treat the first implementation work as an opportunity to document the selected
runtime, package manager, and development commands here.

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
