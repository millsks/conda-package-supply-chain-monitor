"""Fixtures and collection rules for integration tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

if TYPE_CHECKING:
    from collections.abc import Iterator

INTEGRATION_DIR = Path(__file__).parent

SDK_DISABLED_VALUES = {"true", "1", "yes"}


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
