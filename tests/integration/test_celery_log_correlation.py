"""AC #3: correlation propagates from the request that enqueues into the task.

This module is separate from `tests/integration/test_log_correlation.py` on
purpose. It imports `celery` and `django_structlog.celery` at module level, both
of which are feature-owned, so a `core` module importing them could not survive
pruning in the four combinations that carry no background processing (AD-29).
Epic 7 marks this whole file `feature:celery`; its sibling stays `core`.

`CELERY_TASK_ALWAYS_EAGER` cannot carry the assertion, and the suite runs eager
by default (`config/settings/test.py` plus `--ds=config.settings.test`). Under
eager execution `apply_async` short-circuits to `apply()`, so
`before_task_publish` never fires and `__django_structlog__` is never written
into the headers; and `task_prerun`'s receiver is connected only by the worker
bootstep, which no test process runs. The task body would then execute in the
*same* contextvar context as the request and log the request's `request_id`
incidentally -- the case would pass identically with
`DJANGO_STRUCTLOG_CELERY_ENABLED = False` and would assert nothing at all.

So the propagation *vehicle* is asserted instead, in two halves, both using the
real receivers rather than a stand-in:

* publish -- eager off and the broker pointed at kombu's in-process `memory://`
  transport, a task enqueued from inside a real request, and the headers celery
  actually published read off `before_task_publish`. `__django_structlog__`
  carries the request's own `request_id`.
* execute -- those captured headers fed through the real
  `CeleryReceiver.receiver_task_prerun`, and the log line it emits from inside
  the context they restore carries that same `request_id`.

Together they are "correlation propagates into task execution" without a live
broker or a worker process.

The task is defined here with `@shared_task` rather than reusing
`django_service.users.tasks.get_users_count`: AD-29 deletes that module rather
than relocating it, and a case built on it would be removed along with it.

The publish is driven from inside a request because that is the only place
django-structlog's `RequestMiddleware` has bound `request_id` into the
contextvars `receiver_before_task_publish` reads. Enqueuing from the test body
would prove nothing -- those contextvars are cleared once the response returns.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from types import SimpleNamespace
from typing import TYPE_CHECKING
from typing import Any

import pytest
import structlog
from celery import shared_task
from celery.signals import before_task_publish
from django.http import HttpResponse
from django.urls import path
from django.urls import reverse
from django_structlog.celery.receivers import CeleryReceiver

from config.celery_app import app
from tests.conftest import temporary_root_urlconf

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.http import HttpRequest
    from django.test import Client
    from pytest_django.fixtures import SettingsWrapper

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

REQUEST_LOGGER = "django_structlog"

#: kombu's in-process transport. No server, no socket, no cleanup -- and unlike
#: eager execution it goes through the real publish path, which is the whole
#: point of the first half.
MEMORY_BROKER = "memory://"

#: The header django-structlog writes the enqueueing request's context into.
METADATA_HEADER = "__django_structlog__"

ENQUEUE_ROUTE = "celery-correlation-enqueue"


@shared_task(ignore_result=True)
def correlation_probe() -> str:
    """Do nothing worth asserting; only its publication is under test.

    `ignore_result=True` keeps `apply_async` away from the result backend, which
    is a Redis URL nothing in this run stands up.

    Returns:
        A constant, so the task has a body rather than an implicit `None`.

    """
    return "probed"


def _enqueue_view(request: HttpRequest) -> HttpResponse:
    """Enqueue the probe task from inside a request.

    Args:
        request: The incoming request, unused beyond being the reason the
            middleware has bound `request_id` by the time this runs.

    Returns:
        A trivial response; the assertion is on what was published, not on this.

    """
    correlation_probe.delay()
    return HttpResponse("enqueued")


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
def real_publishing(settings: SettingsWrapper) -> Iterator[None]:
    """Turn eager execution off and point the broker at the memory transport.

    Written through Django's settings rather than through `app.conf`, because
    `config_from_object("django.conf:settings", ...)` leaves the application's
    configuration a *live view* over `django.conf.settings` -- so an override
    there is what `apply_async` reads, and pytest-django restores it.

    Writing `app.conf.task_always_eager = False` instead would look like it took
    and change nothing: celery's `Settings` is a namespaced chain map whose
    lookup tries the `CELERY_`-prefixed spelling first, and that spelling is what
    the Django settings map already answers.

    The connection and producer pools are dropped on the way in and out. A pool
    built against one broker URL would otherwise outlive the override and serve
    the rest of the session.

    Args:
        settings: pytest-django's settings wrapper, which restores what it sets.

    Yields:
        Nothing; the fixture exists for the configuration it swaps.

    """
    settings.CELERY_TASK_ALWAYS_EAGER = False
    settings.CELERY_BROKER_URL = MEMORY_BROKER
    app._pool = None  # noqa: SLF001 - no public reset; a cached pool holds the old URL
    app.amqp._producer_pool = None  # noqa: SLF001 - built from the pool above
    try:
        yield
    finally:
        app._pool = None  # noqa: SLF001 - restores the state found
        app.amqp._producer_pool = None  # noqa: SLF001 - restores the state found


@pytest.fixture
def published_headers() -> Iterator[list[dict[str, Any]]]:
    """Record the headers celery publishes, without displacing any receiver.

    Connected after `django_structlog`'s own receiver -- which the app registry
    connected at `ready()` -- so it observes the header that receiver wrote
    rather than racing it.

    Yields:
        A list the probe appends each published header mapping to.

    """
    captured: list[dict[str, Any]] = []

    def _record(sender: object = None, headers: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if headers is not None:
            captured.append(dict(headers))

    before_task_publish.connect(_record, weak=False)
    try:
        yield captured
    finally:
        before_task_publish.disconnect(_record)


@pytest.mark.usefixtures("real_publishing")
class TestThePublishedHeadersCarryTheRequestsCorrelation:
    """The first half: the request's `request_id` leaves with the message."""

    def test_a_task_enqueued_in_a_request_publishes_that_requests_request_id(
        self,
        client: Client,
        caplog: pytest.LogCaptureFixture,
        published_headers: list[dict[str, Any]],
    ):
        """Compared against the request's own log line, not against a literal.

        Reading `request_id` off `request_started` rather than out of the
        response ties the two observations to the same request: a header that
        carried *some* correlation id would satisfy a presence check while
        pointing at nothing.
        """
        with (
            caplog.at_level(logging.INFO, logger=REQUEST_LOGGER),
            temporary_root_urlconf(path("enqueue/", _enqueue_view, name=ENQUEUE_ROUTE)),
        ):
            response = client.get(reverse(ENQUEUE_ROUTE))

        assert response.status_code == HTTPStatus.OK

        started = _events(caplog, "request_started")
        assert started, "django-structlog emitted no request_started event for the enqueueing request"
        request_id = started[0]["request_id"]

        assert published_headers, "nothing was published; apply_async did not reach the broker"
        metadata = published_headers[-1].get(METADATA_HEADER)
        assert metadata is not None, (
            f"the published headers carry no {METADATA_HEADER}: {sorted(published_headers[-1])}"
        )
        assert metadata["request_id"] == request_id, (
            f"published {metadata['request_id']!r} for a request logged as {request_id!r}"
        )


@pytest.mark.usefixtures("real_publishing")
class TestTheHeadersRestoreTheContextForTheTask:
    """The second half: what was published binds again on the execution side."""

    def test_a_log_line_from_inside_task_prerun_carries_the_published_request_id(
        self,
        client: Client,
        caplog: pytest.LogCaptureFixture,
        published_headers: list[dict[str, Any]],
    ):
        """The real receiver, the real header, and the log line it emits.

        `receiver_task_prerun` clears the contextvars before binding the
        metadata, which is exactly why this proves propagation: whatever the
        request left behind is gone, and the `request_id` on `task_started` can
        only have come out of the header.
        """
        with (
            caplog.at_level(logging.INFO, logger=REQUEST_LOGGER),
            temporary_root_urlconf(path("enqueue/", _enqueue_view, name=ENQUEUE_ROUTE)),
        ):
            client.get(reverse(ENQUEUE_ROUTE))

        request_id = _events(caplog, "request_started")[0]["request_id"]
        assert published_headers, "nothing was published; apply_async did not reach the broker"
        metadata = published_headers[-1][METADATA_HEADER]

        task = SimpleNamespace(
            name="tests.correlation_probe",
            request=SimpleNamespace(**{METADATA_HEADER: metadata}),
        )
        caplog.clear()
        structlog.contextvars.clear_contextvars()
        try:
            with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
                CeleryReceiver().receiver_task_prerun(task_id="probe-task-id", task=task)
        finally:
            # The receiver binds into the ambient context, which is this test's
            # own; leaving it bound would leak `request_id` into every later
            # case in the session.
            structlog.contextvars.clear_contextvars()

        started = _events(caplog, "task_started")
        assert started, "the receiver emitted no task_started event"
        assert started[0]["request_id"] == request_id, (
            f"the task logged {started[0].get('request_id')!r} for a request logged as {request_id!r}"
        )


@pytest.mark.usefixtures("real_publishing")
class TestPublishingIsReal:
    """Both halves depend on eager being off; asserted rather than assumed."""

    def test_the_override_actually_disables_eager_execution(self):
        """A silently eager run would make the two halves above vacuous."""
        assert app.conf.task_always_eager is False
        assert app.conf.broker_url == MEMORY_BROKER
