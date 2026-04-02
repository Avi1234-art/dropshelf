import json
import os

from .constants import DEFAULT_SETTINGS, SETTINGS_PATH


def load_settings():
    try:
        with open(SETTINGS_PATH, "r") as f:
            merged = dict(DEFAULT_SETTINGS)
            merged.update(json.load(f))
            return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
