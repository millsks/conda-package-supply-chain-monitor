"""End-to-end checks that the ASGI entrypoint routes, refuses and still traces.

`config.asgi.application` is Django's own `ASGIHandler` -- there is no scope
dispatcher in front of it any more (AD-16). These tests call that object the way
uvicorn does, with a raw scope, so they exercise the real deployment path rather
than Django's test client.

Three things must hold together. Every request has to reach the URL resolver,
including one for a path that matches nothing: the deleted wrapper answered
unknown scope types with `NotImplementedError`, and a 404 from Django's handler
is the proof that the resolver, not a wrapper, decided. Every non-HTTP scope has
to be *refused* -- the deleted wrapper accepted websocket connections with no
authentication at all, and that acceptance is the surface AD-16 exists to
remove. And the ASGI instrumentor has to keep producing spans across the
deletion (FR-47) -- `opentelemetry-instrumentation-asgi` is an optional import
of the Django instrumentor, and without it ASGI requests silently produce no
span at all.

This module drives real requests through the real handler and reads the spans the
live tracer provider collects, so it lives here and not in `tests/unit/`. It also
imports `config.asgi`, which builds Django's handler -- though the instrumentors
themselves are already installed by then, at `config` package import.
"""

from __future__ import annotations

import asyncio
import os
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.core.handlers.asgi import ASGIHandler
from django.urls import reverse
from opentelemetry.trace import SpanKind

import config.asgi

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

RESPONSE_START = "http.response.start"
DRIVE_TIMEOUT_SECONDS = 10
SDK_DISABLED_VALUES = {"true", "1", "yes"}
SUPPRESSING_SAMPLERS = {"always_off", "parentbased_always_off", "traceidratio", "parentbased_traceidratio"}


def _sdk_is_disabled() -> bool:
    """Report whether `OTEL_SDK_DISABLED` is set, matching telemetry's reading.

    Returns:
        True when the documented kill switch is on, in which case
        `configure_telemetry` installs no SDK provider and there is nothing for
        the span tests to observe.

    """
    return os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in SDK_DISABLED_VALUES


def _suppressing_sampler() -> str:
    """Return `OTEL_TRACES_SAMPLER` when it can drop the spans these tests read.

    `configure_telemetry` builds its `TracerProvider` without naming a sampler,
    so the SDK's default applies and the environment decides. A sampler that
    drops the request span makes these tests fail for a reason that has nothing
    to do with the ASGI instrumentor -- so it is named in the failure rather than
    left for the reader to rediscover. The failure itself is correct: FR-47 wants
    the instrumentor producing spans, and `tests/unit/test_suite_policy.py`
    forbids an integration test from skipping its way past that.

    Returns:
        The configured sampler when it may suppress sampling, otherwise "".

    """
    sampler = os.environ.get("OTEL_TRACES_SAMPLER", "").strip().lower()
    return sampler if sampler in SUPPRESSING_SAMPLERS else ""


def _span_absence_hint() -> str:
    """Return a clause naming an environment cause for missing spans, if any.

    Returns:
        A trailing clause for an assertion message, or "" when the environment
        does not explain the absence.

    """
    if _sdk_is_disabled():
        return " -- OTEL_SDK_DISABLED is set"
    sampler = _suppressing_sampler()
    return f" -- OTEL_TRACES_SAMPLER={sampler} may be dropping it" if sampler else ""


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
    """Call the ASGI application directly and collect what it sends back.

    `receive` yields one empty body and then never returns, which is what a live
    connection looks like: returning `http.disconnect` straight away would cancel
    the response before Django finished it. The timeout is what turns "the
    handler awaited `receive` again and never finished" into a failure instead of
    a CI job that hangs until its own wall-clock limit.

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


async def _drive(path: str) -> list[dict[str, Any]]:
    """Drive a plain anonymous GET for `path`.

    Args:
        path: The request path to fetch.

    Returns:
        Every ASGI message the application sent, in order.

    """
    return await _drive_scope(_http_scope(path))


def _status_of(messages: list[dict[str, Any]]) -> int:
    """Return the status code from a collected ASGI response.

    Args:
        messages: The messages the application sent.

    Returns:
        The status code carried on the `http.response.start` message.

    """
    starts = [message for message in messages if message["type"] == RESPONSE_START]
    assert len(starts) == 1, f"expected one {RESPONSE_START}, got {len(starts)}"
    status: int = starts[0]["status"]
    return status


class TestTheApplicationIsDjangosHandler:
    """The runtime object uvicorn imports is Django's handler, unwrapped."""

    def test_application_is_exactly_djangos_asgi_handler(self):
        """Not a subclass.

        `ASGIStaticFilesHandler` subclasses `ASGIHandler` and serves everything
        under `STATIC_URL` from inside itself, never consulting the URLconf --
        the shape AD-16 forbids. An `isinstance` check would accept it.
        """
        assert type(config.asgi.application) is ASGIHandler


class TestRequestsResolveThroughTheUrlResolver:
    """Django's resolver decides every response; nothing sits in front of it."""

    def test_a_known_route_is_served(self):
        messages = async_to_sync(_drive)(reverse("home"))

        assert _status_of(messages) == HTTPStatus.OK

    def test_an_unknown_path_is_a_404_from_django(self):
        """The deleted wrapper raised NotImplementedError; the resolver 404s."""
        messages = async_to_sync(_drive)("/no-such-page/")

        assert _status_of(messages) == HTTPStatus.NOT_FOUND

    def test_a_second_known_route_is_served(self):
        """Two distinct routes prove the resolver is consulted, not a default."""
        messages = async_to_sync(_drive)(reverse("about"))

        assert _status_of(messages) == HTTPStatus.OK


class TestNonHttpScopesAreRefused:
    """AD-16's point: the websocket surface is gone behaviourally, not just structurally."""

    def test_a_websocket_scope_is_refused_rather_than_accepted(self):
        """The deleted handler answered `websocket.connect` with `websocket.accept`."""
        scope = {**_http_scope("/"), "type": "websocket"}

        with pytest.raises(ValueError, match="can only handle ASGI/HTTP connections"):
            async_to_sync(_drive_scope)(scope)

    def test_a_lifespan_scope_is_refused(self):
        """`--lifespan` is a server flag; nothing in this application answers it."""
        scope = {**_http_scope("/"), "type": "lifespan"}

        with pytest.raises(ValueError, match="can only handle ASGI/HTTP connections"):
            async_to_sync(_drive_scope)(scope)


class TestAsgiRequestsAreStillTraced:
    """FR-47: the ASGI instrumentor stays active across the deletion."""

    def test_a_span_is_recorded_for_an_asgi_request(
        self,
        recorded_spans: InMemorySpanExporter,
    ):
        """A SERVER span, specifically.

        `configure_observability()` installs the psycopg, redis and Celery
        instrumentors process-wide, so "at least one span was recorded" is
        satisfied by a database span while the request span -- the only one
        FR-47 is about -- is missing entirely.
        """
        async_to_sync(_drive)(reverse("home"))

        kinds = [span.kind for span in recorded_spans.get_finished_spans()]
        assert SpanKind.SERVER in kinds, f"the ASGI request produced no server span: {kinds}{_span_absence_hint()}"

    def test_the_span_is_named_for_the_resolved_route(
        self,
        recorded_spans: InMemorySpanExporter,
    ):
        """The span *name* is the only field the resolver produces.

        `http.method` and friends are copied out of the scope this test builds,
        so they say nothing about whether resolution happened. The name is
        `"GET home"` only because the instrumentor read the resolved URL name
        off the request -- a handler that answered without consulting the
        resolver could not produce it.
        """
        async_to_sync(_drive)(reverse("home"))

        names = {span.name for span in recorded_spans.get_finished_spans()}
        assert "GET home" in names, f"no span named for the resolved route: {names}{_span_absence_hint()}"

    def test_an_unresolved_path_produces_a_span_without_a_route_name(
        self,
        recorded_spans: InMemorySpanExporter,
    ):
        """The counterpart: no route resolved, so the name is the method alone.

        Asserting the positive value rather than `"GET home" not in names`,
        which any span set that happens to lack that one name would satisfy.
        """
        async_to_sync(_drive)("/no-such-page/")

        names = {span.name for span in recorded_spans.get_finished_spans()}
        assert "GET" in names, f"expected an unnamed-route span for the 404: {names}{_span_absence_hint()}"
        assert "GET home" not in names
