"""Logging and telemetry wiring.

`configure_observability` is the single call each process entrypoint makes --
`manage.py`, `wsgi.py`, `asgi.py` and the Celery app. structlog itself is
configured from the settings module instead, because `LOGGING` has to be built
while settings are being read.
"""

from __future__ import annotations

from pathlib import Path

import environ

from config.observability.logging import add_otel_context
from config.observability.logging import build_logging_config
from config.observability.logging import configure_structlog
from config.observability.logging import resolve_log_format
from config.observability.telemetry import configure_telemetry

__all__ = [
    "add_otel_context",
    "build_logging_config",
    "configure_observability",
    "configure_structlog",
    "configure_telemetry",
    "read_dot_env",
    "resolve_log_format",
]

# Repository root: observability -> config -> src -> root.
BASE_DIR = Path(__file__).resolve().parents[3]


def read_dot_env() -> bool:
    """Load `.env` before telemetry reads any `OTEL_*` variable.

    Settings read `.env` too, but that happens when Django loads its settings --
    long after this runs at entrypoint import. Without this, `OTEL_*` entries in
    `.env` would be parsed too late to affect tracing and would appear to be
    ignored.

    Real environment variables still win: `read_env` does not overwrite entries
    already present in `os.environ`.

    Returns:
        True when a `.env` file was read.

    """
    env = environ.Env()
    if not env.bool("DJANGO_READ_DOT_ENV_FILE", default=False):
        return False

    dot_env = BASE_DIR / ".env"
    if not dot_env.is_file():
        return False

    env.read_env(str(dot_env))
    return True


def configure_observability(service_version: str | None = None) -> bool:
    """Configure logging-adjacent environment and telemetry for this process.

    Args:
        service_version: Version to report on the OpenTelemetry resource.

    Returns:
        True when telemetry was configured by this call, False when skipped.

    """
    read_dot_env()
    return configure_telemetry(service_version)
