from __future__ import annotations
from pathlib import Path
from logging import getLogger

from tiddl.cli.config import APP_PATH
from .models import AuthData


AUTH_DATA_FILE = APP_PATH / "auth.json"


log = getLogger(__name__)


def load_auth_data(file: Path = AUTH_DATA_FILE) -> AuthData:
    log.debug(f"loading from '{AUTH_DATA_FILE}'")

    try:
        file_content = file.read_text()
    except FileNotFoundError:
        return AuthData()
    except Exception as e:
        log.warning(f"Could not read auth file, it might be corrupted: {e}")
        return AuthData()

    try:
        auth_data = AuthData.parse_raw(file_content)
    except Exception as e:
        log.warning(f"Could not parse auth file, it might be corrupted: {e}")
        return AuthData()

    return auth_data


def save_auth_data(auth_data: AuthData, file: Path = AUTH_DATA_FILE):
    log.debug(f"saving to '{file}'")

    with file.open("w") as f:
        f.write(auth_data.json())
