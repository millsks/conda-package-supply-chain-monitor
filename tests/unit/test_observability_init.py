"""Tests for the observability entrypoint and its instrumentation prerequisites."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from config import observability
from config.observability import read_dot_env

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestAsgiInstrumentationIsAvailable:
    """Guards an optional dependency whose absence fails silently.

    `opentelemetry-instrumentation-asgi` is an optional import of the Django
    instrumentor. Without it `_is_asgi_supported` is False and the middleware
    returns early for ASGI requests -- no span, no warning. uvicorn is exactly
    that path, in `pixi run serve` and behind the production uvicorn worker, so
    dropping the package would silently disable tracing in production.
    """

    def test_asgi_support_is_enabled(self):
        from opentelemetry.instrumentation.django.middleware.otel_middleware import _is_asgi_supported  # noqa: PLC0415

        assert _is_asgi_supported is True, (
            f"_is_asgi_supported is {_is_asgi_supported!r}, which means "
            "opentelemetry-instrumentation-asgi is not importable in this environment. The Django "
            "instrumentor's middleware then returns early for every ASGI request and produces no span and "
            "no warning -- tracing does not fail, it silently stops. Both `pixi run serve` (uvicorn) and "
            "the production gunicorn + uvicorn-worker pairing are exactly that path, so the whole of FR-47 "
            "would be lost in production while `runserver` kept working. Restore the declaration in "
            "pixi.toml's [dependencies]; tests/unit/test_dependency_policy.py guards it staying there."
        )


class TestReadDotEnv:
    def test_skipped_when_the_flag_is_off(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DJANGO_READ_DOT_ENV_FILE", raising=False)
        assert read_dot_env() is False

    def test_skipped_when_the_file_is_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.setenv("DJANGO_READ_DOT_ENV_FILE", "True")
        monkeypatch.setattr(observability, "BASE_DIR", tmp_path)
        assert read_dot_env() is False

    def test_values_are_loaded_before_telemetry_reads_them(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Settings read .env far too late for OTEL_* to affect tracing."""
        monkeypatch.setenv("DJANGO_READ_DOT_ENV_FILE", "True")
        monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
        (tmp_path / ".env").write_text("OTEL_TRACES_EXPORTER=console\n")
        monkeypatch.setattr(observability, "BASE_DIR", tmp_path)

        assert read_dot_env() is True
        assert os.environ["OTEL_TRACES_EXPORTER"] == "console"

    def test_real_environment_variables_win(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.setenv("DJANGO_READ_DOT_ENV_FILE", "True")
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
        (tmp_path / ".env").write_text("OTEL_TRACES_EXPORTER=console\n")
        monkeypatch.setattr(observability, "BASE_DIR", tmp_path)

        read_dot_env()
        assert os.environ["OTEL_TRACES_EXPORTER"] == "none"
