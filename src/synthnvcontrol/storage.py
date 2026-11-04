"""Small JSON persistence helpers for local UI state and SynthNV values."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "settings.json"
SETTINGS_DEFAULT_PATH = PROJECT_ROOT / "settings_default.json"
PERSISTENT_PATH = PROJECT_ROOT / "persistent_configuration.json"
PERSISTENT_DEFAULT_PATH = PROJECT_ROOT / "persistent_configuration_default.json"


def ensure_from_default(path: Path, default_path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(default_path, path)
    return path


def load_json(path: Path, default_path: Path) -> dict[str, Any]:
    ensure_from_default(path, default_path)
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)
        file.write("\n")


def load_settings() -> dict[str, Any]:
    return load_json(SETTINGS_PATH, SETTINGS_DEFAULT_PATH)


def save_settings(settings: dict[str, Any]) -> None:
    save_json(SETTINGS_PATH, settings)


def load_persistent() -> dict[str, Any]:
    return load_json(PERSISTENT_PATH, PERSISTENT_DEFAULT_PATH)


def save_persistent(values: dict[str, str]) -> None:
    save_json(PERSISTENT_PATH, {"version": 1, "values": values})
