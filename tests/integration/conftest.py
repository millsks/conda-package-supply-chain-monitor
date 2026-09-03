"""Fixtures and collection rules for integration tests."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# Imported at module scope, deliberately. `get_asgi_application()` runs
# `django.setup()`, whose `configure_logging(dictConfig)` *replaces* the root
# logger's handlers -- including the `LogCaptureHandler` pytest installs for
# `caplog`. Deferring this import into the driver put that wipe inside the
# `caplog.at_level` window of whichever test called `drive_asgi` first, which
# silently emptied that test's captured records: running
# `tests/integration/test_asgi_tracing.py::TestTheAsgiRequestsLogLineNamesTheSameTrace`
# on its own failed while the whole module passed. A conftest for this directory
# is loaded after pytest-django has configured settings -- and
# `tests/integration/test_asgi_request_path.py` already imports this at module
# scope -- so doing it here runs the wipe once, before any test's capture window
# is open.
import config.asgi

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

INTEGRATION_DIR = Path(__file__).parent

SDK_DISABLED_VALUES = {"true", "1", "yes"}

#: How long the ASGI application may take before the driver below gives up. A
#: handler that awaits `receive` once more and never returns is a hang, and a
#: hang in CI is a job that burns its whole wall-clock limit reporting nothing.
DRIVE_TIMEOUT_SECONDS = 10


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Mark every test collected under tests/integration/ as an integration test."""
    for item in items:
        if INTEGRATION_DIR in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.integration)


def _sdk_is_disabled() -> bool:
    """Report whether `OTEL_SDK_DISABLED` is set, matching telemetry's reading.

    A conftest cannot be imported from a test module, so the modules that also
    need this predicate in their own assertion messages keep their own copy.

    Returns:
        True when the documented kill switch is on, in which case
        `configure_telemetry` installs no SDK provider at all.

    """
    return os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in SDK_DISABLED_VALUES


@pytest.fixture
def recorded_spans() -> Iterator[InMemorySpanExporter]:
    """Record spans from the process-wide tracer provider, then detach.

    The provider is installed once, when the `config` package is first imported
    (`config/__init__.py` -> `config.celery_app` -> `configure_observability()`,
    which pytest-django triggers by loading `config.settings.test`), and cannot
    be replaced -- `set_tracer_provider` refuses to override. So the exporter is
    attached to the live provider and the processor list is put back exactly as
    it was found, leaving no processor behind for later tests.

    A disabled SDK fails here rather than skipping. The requirements that read
    this fixture -- correlated logs and ASGI spans alike -- hold in every
    combination, so a run with no provider is a run that does not meet them, and
    `tests/unit/test_suite_policy.py` forbids an integration test from dodging
    the gate it is supposed to fail on.

    Yields:
        The in-memory exporter collecting spans for the duration of the test.

    """
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider), (
        "no SDK tracer provider is installed, so the trace context under test cannot be observed"
        + (" -- OTEL_SDK_DISABLED is set" if _sdk_is_disabled() else "")
    )

    multi_processor = provider._active_span_processor  # noqa: SLF001 - no public detach exists
    original = getattr(multi_processor, "_span_processors", None)
    assert original is not None, "OpenTelemetry SDK internals moved; update this fixture's detach"

    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    try:
        yield exporter
    finally:
        multi_processor._span_processors = original  # noqa: SLF001 - restores the state found
        processor.shutdown()
        exporter.clear()


def _http_scope(path: str) -> dict[str, Any]:
    """Build the ASGI `http` scope uvicorn would hand the application.

    Args:
        path: The request path, including its leading slash.

    Returns:
        A connection scope of type `http` for a plain anonymous GET.

    """
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 43210),
        "server": ("testserver", 80),
    }


async def _drive_scope(scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Call `config.asgi.application` directly and collect what it sends back.

    `receive` yields one empty body and then never returns, which is what a live
    connection looks like: answering `http.disconnect` straight away would cancel
    the response before Django had finished it. The timeout is what turns "the
    handler awaited `receive` again and never finished" into a named failure
    rather than a job that hangs.

    Args:
        scope: The ASGI connection scope to drive.

    Returns:
        Every ASGI message the application sent, in order.

    """
    body_events = [{"type": "http.request", "body": b"", "more_body": False}]
    never = asyncio.Event()
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        if body_events:
            return body_events.pop(0)
        await never.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    async with asyncio.timeout(DRIVE_TIMEOUT_SECONDS):
        await config.asgi.application(scope, receive, send)
    return messages


@pytest.fixture
def drive_asgi() -> Callable[[str], list[dict[str, Any]]]:
    """Return a callable that drives one anonymous GET through the deployed callable.

    `config.asgi.application` is Django's own `ASGIHandler` and is the exact
    object uvicorn imports (AD-16), so a raw scope driven against it exercises
    the deployment path. `django.test.AsyncClient` would not: it builds an
    `AsyncClientHandler` subclass of its own, and the thing under test here is
    what happens in the process an operator actually runs.

    A fixture rather than an importable helper, because a conftest cannot be
    imported from a test module and the second copy of this driver is what the
    deferred-work ledger already records as belonging here.

    Returns:
        A callable taking a request path and returning every ASGI message the
        application sent, in order.

    """

    def drive(path: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = async_to_sync(_drive_scope)(_http_scope(path))
        return messages

    return drive
