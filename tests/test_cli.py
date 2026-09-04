import json
from pathlib import Path

from typer.testing import CliRunner

from fdt.cli import app


def test_ingest_command_emits_json():
    result = CliRunner().invoke(app, ["ingest", "data/seed/A_steady"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["count"] > 0
    assert payload["reconcile"]["balance_mismatch"] == 0


def test_serve_defers_to_fdt_web_app(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = CliRunner().invoke(app, ["serve", "--host", "127.0.0.1", "--port", "9999"])

    assert result.exit_code == 0, result.stdout
    assert calls == [(('fdt.web:app',), {"host": "127.0.0.1", "port": 9999})]


def test_serve_rejects_non_loopback_host(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0"])

    assert result.exit_code != 0
    assert not calls


def test_serve_accepts_named_loopback_host(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = CliRunner().invoke(app, ["serve", "--host", "localhost", "--port", "9999"])

    assert result.exit_code == 0, result.stdout
    assert calls == [(('fdt.web:app',), {"host": "localhost", "port": 9999})]


def test_eval_report_delegates_to_report_module(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr("fdt.eval.report.run_report", lambda log_dir, out=None: calls.append((log_dir, out)) or {"turns": 1})

    result = CliRunner().invoke(app, ["eval", "report", "--log-dir", str(tmp_path), "--out", str(tmp_path / "report.json")])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == {"turns": 1}
    assert calls == [(tmp_path, tmp_path / "report.json")]
