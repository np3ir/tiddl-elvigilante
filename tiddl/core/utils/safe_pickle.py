"""Restricted unpickling for importing third-party session files.

``pickle.load()`` on an untrusted file is a remote-code-execution primitive: the
opcode stream can import arbitrary modules and call arbitrary callables while it
is being loaded. tiddl only needs the *data* inside OrpheusDL's
``loginstorage.bin`` (nested dicts/lists of strings and numbers), so we unpickle
it through an allowlist that permits only plain builtin container/scalar types
and refuses everything else with ``pickle.UnpicklingError``.
"""
from __future__ import annotations

import builtins
import io
import pickle
from pathlib import Path
from typing import Any

# Builtin names that may be reconstructed from the pickle stream. These are the
# only "globals" OrpheusDL's storage is composed of; anything else (a module
# import, a class, a callable) is a code-execution vector and is rejected.
_SAFE_BUILTINS = frozenset(
    {
        "dict",
        "list",
        "tuple",
        "set",
        "frozenset",
        "str",
        "bytes",
        "bytearray",
        "int",
        "float",
        "bool",
    }
)


class RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that only allows a small allowlist of plain builtin types."""

    def find_class(self, module: str, name: str) -> Any:
        if module == "builtins" and name in _SAFE_BUILTINS:
            obj = getattr(builtins, name, None)
            if obj is not None:
                return obj
        raise pickle.UnpicklingError(
            f"blocked unpickling of unsafe global '{module}.{name}'"
        )


def safe_load(path: Path) -> Any:
    """Load a pickle file through the restricted unpickler.

    Raises ``pickle.UnpicklingError`` if the stream references anything outside
    the safe builtin allowlist (i.e. anything that could execute code).
    """
    with Path(path).open("rb") as f:
        return RestrictedUnpickler(f).load()


def safe_loads(data: bytes) -> Any:
    """In-memory variant of :func:`safe_load`."""
    return RestrictedUnpickler(io.BytesIO(data)).load()
