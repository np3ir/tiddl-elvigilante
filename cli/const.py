from __future__ import annotations
import sys
from os import environ
from pathlib import Path


ENV_KEY = "TIDDL_PATH"
APP_DIR_NAME = ".tiddl"


def get_app_path(env_key: str = ENV_KEY) -> Path:
    # Check if running as PyInstaller bundle (Portable Mode)
    if getattr(sys, 'frozen', False):
        # Return a 'config' directory next to the executable
        return Path(sys.executable).parent / "config"

    if environ.get(env_key):
        return Path(environ[env_key])

    return Path.home() / APP_DIR_NAME


def create_app_path() -> Path:
    app_path = get_app_path()
    app_path.mkdir(parents=True, exist_ok=True)

    return app_path


APP_PATH = create_app_path()
