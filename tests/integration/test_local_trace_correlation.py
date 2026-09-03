"""FR-21: observability is not substituted locally.

Nothing here configures an OTLP endpoint, which is the ambient state of every
local run and every test run -- no settings module and no pixi task sets an
`OTEL_*` variable. That is exactly the condition under test: with no collector
anywhere, the tracer provider is still installed, the instrumentors still
instrument, spans are still created and ended, and `trace_id` and `span_id`
still reach every log line. Only the terminal export step is absent.

The provider is *not* installed here. `config/__init__.py` imports
`config.celery_app`, which calls `configure_observability()` at module scope, so
the provider and all four instrumentors are already live by the time any test
runs -- and `trace.set_tracer_provider` refuses to override. So the spans are
read off the live provider by attaching an in-memory exporter and putting the
processor tuple back afterwards. `reset_telemetry_for_testing()` is deliberately
not called: clearing the process-wide guard would let a later
`configure_telemetry()` instrument Django, Celery, psycopg and redis a second
time for the rest of the session.

Log lines are read through `caplog` and `record.msg`, never through
`structlog.testing.capture_logs`. That helper installs its own processor chain,
which drops `merge_contextvars` *and* `add_otel_context` itself -- so `trace_id`
and `span_id` could never appear in what it captures and the test would assert
the absence of the property it exists to prove.
"""

from __future__ import annotations

import logging
import os
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.urls import reverse
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind

from config.observability.telemetry import NONE
from config.observability.telemetry import has_span_processor
from config.observability.telemetry import resolve_traces_exporter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.test import Client
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

REQUEST_LOGGER = "django_structlog"

#: Both OTLP retry emitters -- `opentelemetry.exporter.otlp.proto.http.
#: trace_exporter` and `opentelemetry.sdk.trace.export` -- propagate here.
OTEL_LOGGER = "opentelemetry"

TRACE_ID_HEX_LEN = 32
SPAN_ID_HEX_LEN = 16

SDK_DISABLED_VALUES = {"true", "1", "yes"}
SUPPRESSING_SAMPLERS = {"always_off", "parentbased_always_off", "traceidratio", "parentbased_traceidratio"}


def _sdk_is_disabled() -> bool:
    """Report whether `OTEL_SDK_DISABLED` is set, matching telemetry's reading.

    Returns:
        True when the documented kill switch is on, in which case
        `configure_telemetry` installs no SDK provider at all.

    """
    return os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in SDK_DISABLED_VALUES


def _suppressing_sampler() -> str:
    """Return `OTEL_TRACES_SAMPLER` when it can drop the spans these tests read.

    Returns:
        The configured sampler when it may suppress sampling, otherwise "".

    """
    sampler = os.environ.get("OTEL_TRACES_SAMPLER", "").strip().lower()
    return sampler if sampler in SUPPRESSING_SAMPLERS else ""


def _span_absence_hint() -> str:
    """Return a clause naming an environment cause for missing spans, if any.

    Nothing here skips -- `tests/unit/test_suite_policy.py` forbids it, and a
    run with no spans is a run that does not meet FR-21. The environment cause
    is named in the failure instead of being left for the reader to rediscover.

    Returns:
        A trailing clause for an assertion message, or "" when the environment
        does not explain the absence.

    """
    if _sdk_is_disabled():
        return " -- OTEL_SDK_DISABLED is set"
    sampler = _suppressing_sampler()
    return f" -- OTEL_TRACES_SAMPLER={sampler} may be dropping it" if sampler else ""


def _events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, Any]]:
    """Return the emitted event dictionaries for one structlog event.

    Args:
        caplog: The pytest log capture fixture.
        name: The structlog `event` value to filter on.

    Returns:
        Every captured event dictionary with that event name.

    """
    return [record.msg for record in caplog.records if isinstance(record.msg, dict) and record.msg.get("event") == name]


@pytest.fixture
def request_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Capture django-structlog's request events, which are emitted at INFO."""
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        yield caplog


class TestNoEndpointIsConfigured:
    """The premise every other test in this module rests on."""

    def test_the_run_resolves_to_no_exporter(self):
        """Nothing in the tree configures an endpoint, so nothing is exported."""
        assert resolve_traces_exporter() == NONE


class TestSpansAreStillCreatedAndEnded:
    """AC #1: the SDK runs unchanged; only export is absent."""

    def test_a_request_produces_a_finished_server_span(
        self,
        client: Client,
        recorded_spans: InMemorySpanExporter,
    ):
        """`get_finished_spans` is the created-and-ended assertion in one call.

        A SERVER span specifically: the psycopg and redis instrumentors are
        live too, so "at least one span" would be satisfied by a database span
        while the request span was missing entirely.
        """
        response = client.get(reverse("home"))

        assert response.status_code == HTTPStatus.OK
        kinds = [span.kind for span in recorded_spans.get_finished_spans()]
        assert SpanKind.SERVER in kinds, f"the request produced no server span: {kinds}{_span_absence_hint()}"


class TestTraceContextReachesTheLogs:
    """AC #1: `trace_id` and `span_id` reach every log line with no collector."""

    def test_request_events_carry_the_trace_and_span_ids(
        self,
        client: Client,
        request_logs: pytest.LogCaptureFixture,
    ):
        """`add_otel_context` writes them whenever a span context is live.

        Asserting the behaviour, not the processor's presence in a list.
        """
        client.get(reverse("home"))

        started = _events(request_logs, "request_started")
        assert started, f"django-structlog emitted no request_started event{_span_absence_hint()}"

        for event in started:
            trace_id = event.get("trace_id", "")
            span_id = event.get("span_id", "")
            assert len(trace_id) == TRACE_ID_HEX_LEN, (
                f"no trace_id on the log line: {sorted(event)}{_span_absence_hint()}"
            )
            assert len(span_id) == SPAN_ID_HEX_LEN, f"no span_id on the log line: {sorted(event)}{_span_absence_hint()}"
            # Length alone passes on whitespace and on the all-zero id an
            # invalid span context would produce, which is the regression
            # these two lines exist to catch.
            assert int(trace_id, 16) != 0, f"trace_id is the invalid all-zero id: {trace_id!r}"
            assert int(span_id, 16) != 0, f"span_id is the invalid all-zero id: {span_id!r}"

    def test_the_logged_trace_id_is_the_recorded_span_s_trace_id(
        self,
        client: Client,
        recorded_spans: InMemorySpanExporter,
        request_logs: pytest.LogCaptureFixture,
    ):
        """Correlation, not merely presence: the two ids are the same trace."""
        client.get(reverse("home"))

        logged = {event["trace_id"] for event in _events(request_logs, "request_started")}
        recorded = {format(span.context.trace_id, "032x") for span in recorded_spans.get_finished_spans()}

        assert logged, f"no request_started event carried a trace_id{_span_absence_hint()}"
        assert logged <= recorded, f"logged trace ids {logged} are not among the recorded ones {recorded}"


class TestNothingRetriesAgainstAnUnreachableCollector:
    """AC #3: no batch processor is attached to an endpoint that is not there."""

    def test_the_live_provider_carries_no_span_processor(self):
        """The assertion AC #3 actually rests on, made over the object.

        `test_no_retry_output_during_a_run` below cannot carry AC #3 by itself.
        `BatchSpanProcessor`'s default schedule delay is five seconds, so a
        processor wrongly attached to an unreachable endpoint would emit its
        first retry warning long after any request-scoped log capture has
        closed -- the observation would stay silent while the defect shipped.
        The structural property has no such window: with no endpoint
        configured, the provider this process installed carries no processor at
        all, and that absence is how spans are discarded.
        """
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider), (
            "no SDK tracer provider is installed, so FR-21's non-substitution cannot be observed"
            + (" -- OTEL_SDK_DISABLED is set" if _sdk_is_disabled() else "")
        )

        attached = [
            type(processor).__name__
            for processor in provider._active_span_processor._span_processors  # noqa: SLF001 - no public accessor
        ]
        assert has_span_processor(provider) is False, (
            f"a span processor is attached with no endpoint configured: {attached}"
        )

    def test_no_retry_output_during_a_run(
        self,
        client: Client,
        caplog: pytest.LogCaptureFixture,
    ):
        """Asserted over captured records, never by scraping stderr.

        The secondary check: no exporter logs anything at all during a run.
        The property it guards is held by the test above -- this one would go
        quiet for a batch processor whose export cycle has not come round yet.
        """
        with caplog.at_level(logging.WARNING, logger=OTEL_LOGGER):
            client.get(reverse("home"))
            client.get(reverse("about"))

        offending = [
            record.getMessage()
            for record in caplog.records
            if record.name == OTEL_LOGGER or record.name.startswith(f"{OTEL_LOGGER}.")
        ]

        assert offending == [], f"the OpenTelemetry exporter logged during a local run: {offending}"
