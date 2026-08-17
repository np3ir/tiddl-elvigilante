from __future__ import annotations

import os
from logging import getLogger
from pathlib import Path

from tiddl.cli.config import APP_PATH
from tiddl.core.utils.fsio import atomic_write_bytes

from .models import AuthData

AUTH_DATA_FILE = APP_PATH / "auth.json"
# Segundo token para el modo hibrido: cliente TV (lossless) que cubre los tracks
# donde el cliente HiRes primario degrada a 320. Ver ctx.fallback_api.
AUTH_FALLBACK_FILE = APP_PATH / "auth_fallback.json"


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

    payload = auth_data.json()

    # Write to a temp file in the same directory, then publish with os.replace()
    # so a crash or full disk mid-write can never leave a truncated auth.json
    # (which used to wipe the user's session and force a re-login). These
    # tokens are secrets — restrict to owner-only on POSIX (chmod_posix=0o600
    # is a no-op on Windows; ACLs already default to the user profile there).
    # Extracted into `tiddl.core.utils.fsio.atomic_write_bytes` (same behavior,
    # now shared with the retained-staging registry) — see that function's
    # docstring for the exact contract.
    atomic_write_bytes(
        file,
        payload.encode("utf-8"),
        chmod_posix=0o600 if os.name == "posix" else None,
    )
