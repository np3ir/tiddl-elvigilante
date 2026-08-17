"""Tests for the restricted unpickler used by `tiddl auth import-orpheus`.

These guard the security contract: plain data loads, but any attempt to smuggle
code execution through the pickle stream is rejected.
"""
from __future__ import annotations

import os
import pickle

import pytest

from tiddl.core.utils.safe_pickle import safe_load, safe_loads


def test_plain_data_roundtrips():
    payload = {
        "modules": {
            "tidal": {
                "sessions": {
                    "default": {
                        "custom_data": {
                            "sessions": {
                                "TV": {"refresh_token": "abc", "user_id": 42}
                            }
                        }
                    }
                }
            }
        }
    }
    assert safe_loads(pickle.dumps(payload)) == payload


def test_nested_containers_and_scalars():
    payload = [1, 2.5, "x", b"y", True, (3, 4), {"k": {"v"}}]
    assert safe_loads(pickle.dumps(payload)) == payload


class _Evil:
    """A class whose unpickling would call an arbitrary global (os.system)."""

    def __reduce__(self):
        return (os.system, ("echo pwned",))


def test_code_execution_reduce_is_blocked():
    blob = pickle.dumps(_Evil())
    with pytest.raises(pickle.UnpicklingError):
        safe_loads(blob)


def test_global_callable_reference_is_blocked():
    # Functions pickle as a GLOBAL reference (module, qualname). Loading one must
    # be refused, since a global reference is exactly the code-execution vector.
    blob = pickle.dumps(os.system)
    with pytest.raises(pickle.UnpicklingError):
        safe_loads(blob)


def test_builtin_outside_allowlist_is_blocked():
    # `exec` lives in `builtins` but is NOT a data type on the allowlist — the
    # module==builtins branch must still reject names it does not explicitly allow.
    blob = pickle.dumps(exec)
    with pytest.raises(pickle.UnpicklingError):
        safe_loads(blob)


def test_safe_load_from_file(tmp_path):
    p = tmp_path / "loginstorage.bin"
    p.write_bytes(pickle.dumps({"ok": True}))
    assert safe_load(p) == {"ok": True}
