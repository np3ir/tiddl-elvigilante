from __future__ import annotations

import importlib.metadata

import pytest
import typer

from tiddl.cli import app as app_module


def test_installed_version_reads_distribution_metadata(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "1.2.3")

    assert app_module._installed_version() == "1.2.3"


def test_installed_version_has_controlled_fallback(monkeypatch):
    def missing(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing)

    assert app_module._installed_version() == "unknown"


def test_version_callback_reports_semver_without_network(monkeypatch, capsys):
    monkeypatch.setattr(app_module, "_installed_version", lambda: "1.2.3")
    monkeypatch.setattr(app_module, "_installed_commit", lambda: "")

    with pytest.raises(typer.Exit):
        app_module.version_callback(True)

    assert capsys.readouterr().out == "tiddl-elvigilante 1.2.3\n"


def test_version_callback_keeps_git_provenance(monkeypatch, capsys):
    monkeypatch.setattr(app_module, "_installed_version", lambda: "1.2.3")
    monkeypatch.setattr(app_module, "_installed_commit", lambda: "abcdef12")
    monkeypatch.setattr(
        app_module, "_commit_datetime", lambda _commit: "2026-08-19 09:30"
    )

    with pytest.raises(typer.Exit):
        app_module.version_callback(True)

    assert (
        capsys.readouterr().out
        == "tiddl-elvigilante 1.2.3 (abcdef12, 2026-08-19 09:30)\n"
    )


def test_version_callback_ignores_false_value(capsys):
    assert app_module.version_callback(False) is None
    assert capsys.readouterr().out == ""
