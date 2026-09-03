"""End-to-end checks that request context reaches the log stream.

These drive the real test client so django-structlog's middleware actually
runs, and read the emitted records through `caplog`. `structlog.testing.
capture_logs` is deliberately not used: it swaps in its own processor chain,
which drops `merge_contextvars` -- and `request_id` is bound as a contextvar,
so it would never appear.

Reading the stdlib records instead exercises the configured pipeline, including
the shared processors and the OpenTelemetry correlation.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.urls import reverse

if TYPE_CHECKING:
    from django.test import Client

    from django_service.users.models import User

pytestmark = pytest.mark.django_db

REQUEST_LOGGER = "django_structlog"


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
def request_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Capture django-structlog's request events, which are emitted at INFO."""
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        yield caplog


class TestRequestLogging:
    def test_request_lifecycle_is_logged(
        self,
        client: Client,
        request_logs: pytest.LogCaptureFixture,
    ):
        response = client.get(reverse("home"))

        assert response.status_code == HTTPStatus.OK
        assert _events(request_logs, "request_started")
        assert _events(request_logs, "request_finished")

    def test_request_id_is_bound_and_stable_across_the_request(
        self,
        client: Client,
        request_logs: pytest.LogCaptureFixture,
    ):
        """One id ties every line from a single request together."""
        client.get(reverse("home"))

        started = _events(request_logs, "request_started")[0]
        finished = _events(request_logs, "request_finished")[0]

        assert started["request_id"]
        assert started["request_id"] == finished["request_id"]

    def test_separate_requests_get_separate_ids(
        self,
        client: Client,
        request_logs: pytest.LogCaptureFixture,
    ):
        client.get(reverse("home"))
        client.get(reverse("about"))

        started = _events(request_logs, "request_started")
        ids = {event["request_id"] for event in started}
        assert len(ids) == 2  # noqa: PLR2004

    def test_anonymous_requests_have_no_user_id(
        self,
        client: Client,
        request_logs: pytest.LogCaptureFixture,
    ):
        client.get(reverse("home"))

        assert _events(request_logs, "request_started")[0]["user_id"] is None

    def test_authenticated_requests_carry_the_user_id(
        self,
        client: Client,
        user: User,
        request_logs: pytest.LogCaptureFixture,
    ):
        """Proves RequestMiddleware runs after AuthenticationMiddleware."""
        client.force_login(user)
        client.get(reverse("home"))

        assert _events(request_logs, "request_started")[0]["user_id"] == user.pk

    def test_response_code_is_recorded(
        self,
        client: Client,
        request_logs: pytest.LogCaptureFixture,
    ):
        client.get("/no-such-page/")

        finished = _events(request_logs, "request_finished")[0]
        assert finished["code"] == HTTPStatus.NOT_FOUND


class TestLogPipeline:
    def test_shared_processors_are_applied_to_request_events(
        self,
        client: Client,
        request_logs: pytest.LogCaptureFixture,
    ):
        """Timestamp, level and logger come from the shared processor chain."""
        client.get(reverse("home"))

        started = _events(request_logs, "request_started")[0]
        assert started["level"] == "info"
        assert started["timestamp"].endswith("Z")
        assert started["logger"].startswith("django_structlog")
