"""FR-47 / SC-7: a request served over ASGI produces a span, and the log agrees.

`tests/integration/test_asgi_request_path.py` already asserts that a `SERVER`
span exists for an ASGI request and that its *name* comes from the resolved
route -- that is Story 1.4's claim, and this module does not try to own it. The
existence check still opens every test below, because reading a span's contents
requires first having one, and a bare `IndexError` is a worse failure than a
sentence naming the environment cause. What that module does not assert, and
what this one adds, is the content of the span an operator actually queries on:
the HTTP-method attribute, a trace id that is not the all-zero id an invalid
span context produces, and -- the half that no other
module covers on this path -- that the *same* request's `django_structlog` line
carries that span's trace id.

That last conjunction is why this file exists next to
`tests/integration/test_log_correlation.py`. That module asserts it over the
**WSGI** test client. ASGI is the only way a component is served: `pixi run
serve` runs uvicorn, and production is gunicorn with the uvicorn worker. So the
log half and the trace half could drift apart on the only path that ships while
every existing assertion stayed green.

The dependency that makes any of this work is not imported by project code at
all. `opentelemetry-instrumentation-asgi` is an *optional* import of the Django
instrumentor: without it `_is_asgi_supported` is False, `_DjangoMiddleware`
returns early for every ASGI request, and there is no span and no warning.
`tests/unit/test_dependency_policy.py` asserts the package is declared
unconditionally and `tests/unit/test_observability_init.py` asserts the flag it
flips; this module asserts the behaviour those two exist to protect.

`account_login` is the route, not `home`. AD-29 deletes `home` and `about` as
demonstration content -- `src/config/urls.py` already carries the comment
recording that Story 7.4 removes them -- while `account_login`, registered by
`include("allauth.urls")`, is `core` in every combination because FR-4's
interactive flow is immovable core.

Log lines are read through `caplog` and `record.msg`, never through
`structlog.testing.capture_logs`. That helper installs a processor chain of its
own, dropping `merge_contextvars` and `add_otel_context` -- so the `trace_id`
this module exists to compare would be absent by construction.
"""

from __future__ import annotations

import logging
import os
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.urls import reverse
from opentelemetry.trace import SpanKind

if TYPE_CHECKING:
    from collections.abc import Callable

    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

REQUEST_LOGGER = "django_structlog"
REQUEST_STARTED = "request_started"
RESPONSE_START = "http.response.start"

#: The three identifiers SC-7 requires on one line, named once so the assertion
#: and its failure message cannot disagree about what was looked for. The same
#: frozenset shape `tests/integration/test_log_correlation.py` uses for the WSGI
#: path.
CORRELATION_KEYS = frozenset({"request_id", "trace_id", "span_id"})

#: Hex width the OpenTelemetry spec mandates for a trace id.
TRACE_ID_HEX_LEN = 32

#: The method the driver sends, restated here so the assertion and its failure
#: message cannot disagree about what was being looked for.
EXPECTED_METHOD = "GET"

#: Both spellings of the HTTP-method attribute, because which one is written is
#: an environment decision rather than a property of the instrumentor. With no
#: `OTEL_SEMCONV_STABILITY_OPT_IN` set the stability mode is DEFAULT and
#: `_set_http_method` writes the old `http.method`; opting in to the stable
#: conventions writes `http.request.method` instead. Accepting either is what
#: makes an opt-in read as a convention change rather than as a missing span.
METHOD_ATTRIBUTES = ("http.method", "http.request.method")
SEMCONV_OPT_IN_VAR = "OTEL_SEMCONV_STABILITY_OPT_IN"

SDK_DISABLED_VALUES = {"true", "1", "yes"}
SUPPRESSING_SAMPLERS = {"always_off", "parentbased_always_off", "traceidratio", "parentbased_traceidratio"}


def _span_absence_hint() -> str:
    """Return a clause naming an environment cause for missing spans, if any.

    A local copy rather than an import: a conftest cannot be imported from a test
    module, and this is the convention `tests/integration/conftest.py` records for
    predicates used inside assertion messages. Nothing here skips --
    `tests/unit/test_suite_policy.py` forbids it, and a run with no span is a run
    that does not meet FR-47 -- so the environment cause is named in the failure
    instead of being left to be rediscovered.

    Returns:
        A trailing clause for an assertion message, or "" when the environment
        does not explain the absence.

    """
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in SDK_DISABLED_VALUES:
        return " -- OTEL_SDK_DISABLED is set"
    sampler = os.environ.get("OTEL_TRACES_SAMPLER", "").strip().lower()
    return f" -- OTEL_TRACES_SAMPLER={sampler} may be dropping it" if sampler in SUPPRESSING_SAMPLERS else ""


def _events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, Any]]:
    """Return the emitted event dictionaries for one structlog event.

    Args:
        caplog: The pytest log capture fixture.
        name: The structlog `event` value to filter on.

    Returns:
        Every captured event dictionary with that event name.

    """
    return [record.msg for record in caplog.records if isinstance(record.msg, dict) and record.msg.get("event") == name]


def _assert_served(messages: list[dict[str, Any]], path: str) -> None:
    """Assert the driven request actually reached its view.

    Every assertion in this module is satisfied by a request that never got
    there. A 404 produces a `SERVER` span carrying `http.method` and a real trace
    id, and django-structlog emits `request_started` before resolution either
    way, so a renamed or broken `account_login` would leave the whole module
    green while proving nothing about a served request. Both sibling modules
    check the status for this reason -- `test_asgi_request_path.py` through its
    own `_status_of`, `test_log_correlation.py` through `response.status_code`.

    Args:
        messages: Every ASGI message the application sent, in order.
        path: The path that was driven, for the failure message.

    Raises:
        AssertionError: If no single `http.response.start` carrying 200 was sent.

    """
    starts = [message for message in messages if message["type"] == RESPONSE_START]
    assert len(starts) == 1, (
        f"driving {path!r} produced {len(starts)} {RESPONSE_START!r} messages, not one: "
        f"{[message['type'] for message in messages]}"
    )
    assert starts[0]["status"] == HTTPStatus.OK, (
        f"driving {path!r} returned {starts[0]['status']}, not {HTTPStatus.OK}. The spans and log lines "
        "below would be produced for an error response too, so they would say nothing about a served request."
    )


def _server_spans(exporter: InMemorySpanExporter) -> list[ReadableSpan]:
    """Return the exported spans that describe an inbound request.

    `configure_observability()` instruments psycopg, redis and Celery process-wide
    as well, so "some span was exported" is satisfied by a database span while the
    request span -- the only one FR-47 is about -- is missing entirely. Filtering
    by kind is what keeps the assertions below about the right span.

    Args:
        exporter: The in-memory exporter attached to the live tracer provider.

    Returns:
        Every finished span whose kind is SERVER, in export order.

    """
    return [span for span in exporter.get_finished_spans() if span.kind is SpanKind.SERVER]


def _the_server_span(exporter: InMemorySpanExporter) -> ReadableSpan:
    """Return the one `SERVER` span the driven request produced.

    Exactly one, not the first of several. `recorded_spans` attaches to the
    *process-wide* provider, so the exporter also collects the database spans the
    request ran; asserting the count is what makes indexing into the list mean
    "the request's span" rather than "whichever finished first".

    Args:
        exporter: The in-memory exporter attached to the live tracer provider.

    Returns:
        The single finished span of kind SERVER.

    Raises:
        AssertionError: If there is not exactly one.

    """
    spans = _server_spans(exporter)
    assert len(spans) == 1, (
        f"expected exactly one SERVER span for the ASGI request, got {[span.name for span in spans]} "
        f"(all exported kinds: {[span.kind for span in exporter.get_finished_spans()]})"
        f"{_span_absence_hint()}"
    )
    return spans[0]


def _trace_id_of(span: ReadableSpan) -> int:
    """Return a span's trace id, failing with a message if it carries no context.

    `ReadableSpan.context` is `SpanContext | None`, and mypy is scoped to `src/`
    so nothing in the gate types this call. A missing context is exactly the
    shape of failure this module exists to catch, and reaching through `None`
    would report it as a bare `AttributeError` instead of the sentence below.

    Args:
        span: The span to read.

    Returns:
        The span's trace id as an integer.

    Raises:
        AssertionError: If the span carries no `SpanContext`.

    """
    context = span.context
    assert context is not None, (
        f"the SERVER span named {span.name!r} carries no SpanContext at all, so it names no trace{_span_absence_hint()}"
    )
    return context.trace_id


class TestAsgiRequestsProduceSpans:
    """AC #2: the deployed ASGI callable produces a usable request span."""

    def test_the_server_span_carries_the_requests_http_method(
        self,
        drive_asgi: Callable[[str], list[dict[str, Any]]],
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """FR-47: a span with no method attribute is not a request span an operator can use.

        The span's existence is Story 1.4's assertion; its *content* is this
        one's. `http.method` is the first thing a trace backend groups and filters
        on, so a span exported without it is present in the store and absent from
        every view an operator would reach it through -- a failure the existence
        check cannot see.

        Both attribute spellings are accepted because the environment picks: with
        no `OTEL_SEMCONV_STABILITY_OPT_IN` the instrumentor writes the old
        `http.method`, and opting in to the stable conventions makes it
        `http.request.method`. Naming both keys and the variable in the failure
        message is what makes an opt-in read as a convention change rather than as
        a vanished span.
        """
        path = reverse("account_login")
        _assert_served(drive_asgi(path), path)

        span = _the_server_span(recorded_spans)
        attributes = dict(span.attributes or {})
        methods = {attributes[key] for key in METHOD_ATTRIBUTES if key in attributes}
        assert EXPECTED_METHOD in methods, (
            f"the SERVER span named {span.name!r} carries no {EXPECTED_METHOD!r} under any of "
            f"{list(METHOD_ATTRIBUTES)}; it carries {sorted(attributes)}. Which key is written is decided by "
            f"{SEMCONV_OPT_IN_VAR} -- unset means the DEFAULT stability mode and the old 'http.method', while "
            "opting in to the stable HTTP conventions writes 'http.request.method'. If a third spelling has "
            "arrived, add it to METHOD_ATTRIBUTES rather than loosening the assertion."
        )

    def test_the_server_spans_trace_id_is_not_the_all_zero_id(
        self,
        drive_asgi: Callable[[str], list[dict[str, Any]]],
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """An invalid span context exports as zeros and satisfies every presence check.

        `INVALID_SPAN_CONTEXT` carries a trace id of `0`, formats to 32 legal hex
        characters and is exported like any other. So a span whose context never
        got a real id passes "a SERVER span exists" and "it has a trace id" while
        naming a trace no backend holds and no log line can be joined to. The
        non-zero check is the one that distinguishes them.
        """
        path = reverse("account_login")
        _assert_served(drive_asgi(path), path)

        span = _the_server_span(recorded_spans)
        trace_id = _trace_id_of(span)
        assert trace_id != 0, (
            f"the SERVER span named {span.name!r} carries the invalid all-zero trace id "
            f"{format(trace_id, f'0{TRACE_ID_HEX_LEN}x')!r}, so it names no trace an operator could open"
            f"{_span_absence_hint()}"
        )


class TestTheAsgiRequestsLogLineNamesTheSameTrace:
    """AC #2 meeting Story 6.1's AC #2 on the only path a component is served on."""

    def test_the_request_started_event_carries_the_server_spans_trace_id(
        self,
        drive_asgi: Callable[[str], list[dict[str, Any]]],
        recorded_spans: InMemorySpanExporter,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """FR-47 and FR-46 for one request, so the two halves cannot drift apart.

        `tests/integration/test_log_correlation.py` asserts this agreement over
        the WSGI test client, and `tests/integration/test_asgi_request_path.py`
        asserts the span alone over ASGI. Neither would notice the state where
        ASGI requests produce spans and ASGI log lines carry a trace id from
        somewhere else -- or none -- which is precisely the state that makes a
        trace unreachable from the logs in production, since production is ASGI
        and nothing else.

        Equality against the span's own id, not merely membership in the recorded
        set: the exporter also collects the database spans the request ran, and a
        `trace_id` matching one of those while missing the request's would satisfy
        a subset check and still point the operator at the wrong span.
        """
        path = reverse("account_login")
        with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
            messages = drive_asgi(path)
        _assert_served(messages, path)

        expected = format(_trace_id_of(_the_server_span(recorded_spans)), f"0{TRACE_ID_HEX_LEN}x")

        started = _events(caplog, REQUEST_STARTED)
        assert started, (
            f"django-structlog emitted no {REQUEST_STARTED!r} event for the ASGI request; its middleware is "
            f"what binds the identifiers SC-7 requires{_span_absence_hint()}"
        )

        missing = sorted(CORRELATION_KEYS - set(started[0]))
        assert not missing, (
            f"the ASGI {REQUEST_STARTED!r} line is missing {missing}; it carried {sorted(started[0])}. "
            "django-structlog binds these through `sync_to_async(self.prepare)` on the async path and "
            "directly on the sync one, so the WSGI assertion in tests/integration/test_log_correlation.py "
            "cannot speak for this path -- and ASGI is the only path a component is served on."
        )

        logged = {event["trace_id"] for event in started if "trace_id" in event}
        assert expected in logged, (
            f"the ASGI request's SERVER span is trace {expected}, but its {REQUEST_STARTED!r} lines carry "
            f"{sorted(logged) or 'no trace_id at all'}. The log view and the trace view name different traces "
            f"for the same request, so neither leads to the other{_span_absence_hint()}"
        )
