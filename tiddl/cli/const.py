from __future__ import annotations
import sys
from os import environ
from pathlib import Path


ENV_KEY = "TIDDL_PATH"
APP_DIR_NAME = ".tiddl"


def get_app_path(env_key: str = ENV_KEY) -> Path:
    # Explicit TIDDL_PATH always wins, frozen or not.
    if environ.get(env_key):
        return Path(environ[env_key])

    # PyInstaller bundle (Portable Mode): config next to the executable,
    # but only if that location is writable - installed under Program Files
    # it is not, and crashing at import left a clean machine unusable.
    if getattr(sys, "frozen", False):
        portable = Path(sys.executable).parent / "config"
        try:
            portable.mkdir(parents=True, exist_ok=True)
            probe = portable / ".write_test"
            probe.touch()
            probe.unlink()
            return portable
        except OSError:
            pass

    return Path.home() / APP_DIR_NAME


def create_app_path() -> Path:
    app_path = get_app_path()
    app_path.mkdir(parents=True, exist_ok=True)

    return app_path


APP_PATH = create_app_path()
