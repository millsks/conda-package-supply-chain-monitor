"""FR-46 / SC-7: one log line carrying `request_id`, `trace_id` and `span_id`.

What this adds over `tests/integration/test_local_trace_correlation.py`: that
module covers FR-21 -- observability is not substituted locally -- and asserts
`trace_id` and `span_id` only, because those two are what a missing collector
would take away. Neither it nor anything else in the tree asserts that
`request_id` appears on the *same* line as them. That conjunction is the whole
of SC-7: `trace_id` alone opens the trace, `request_id` alone joins a component's
own lines together, and only both on one line let an operator move between the
two views for a request whose services never coordinated.

This module is `core` (AD-29) and imports nothing feature-owned. The Celery half
of FR-46 lives in `tests/integration/test_celery_log_correlation.py`, which is
`feature:celery` precisely because it cannot be written without importing
`celery` at module level.

`account_login` is the route, not `home`. AD-29 deletes `home` and `about` as
demonstration content along with their `TemplateView`s -- `src/config/urls.py`
already carries the comment recording that Story 7.4 removes them -- and this
story must not add a new dependency on a route that is being deleted.
`account_login` is registered by `include("allauth.urls")` and is `core` in every
combination, because FR-4's interactive flow is immovable core.

Log lines are read through `caplog` and `record.msg`, never through
`structlog.testing.capture_logs`. That helper installs its own processor chain,
dropping `merge_contextvars` -- so `request_id` vanishes -- and `add_otel_context`
-- so `trace_id` and `span_id` vanish. Every identifier this module exists to
observe would be absent by construction.
"""

from __future__ import annotations

import logging
import os
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.urls import reverse

from config.authorization.claims import ClaimsContract
from config.local_dev.constants import LOCAL_SIGNIN_URL_NAME
from config.locality import RUNTIME_ENV_VAR
from django_service.users.provisioning import provision_designated_groups

if TYPE_CHECKING:
    from django.test import Client
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from pytest_django.fixtures import SettingsWrapper

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

REQUEST_LOGGER = "django_structlog"
MAPPER_LOGGER = "config.authorization.mapper"

#: Hex widths mandated by the OpenTelemetry spec.
TRACE_ID_HEX_LEN = 32
SPAN_ID_HEX_LEN = 16

#: The three identifiers SC-7 requires together, named once so the assertion and
#: its failure message cannot disagree about what was being looked for.
CORRELATION_KEYS = frozenset({"request_id", "trace_id", "span_id"})

SDK_DISABLED_VALUES = {"true", "1", "yes"}
SUPPRESSING_SAMPLERS = {"always_off", "parentbased_always_off", "traceidratio", "parentbased_traceidratio"}

# Names that appear nowhere in `src/`, matching the convention
# `tests/integration/test_local_dev_signin.py` records: nothing here can pass
# because a literal in the source happened to match.
IDENTITY_CLAIM = "urn:example:principal-id"
GROUP_CLAIM = "realm_access.roles"
STAFF_GROUP = "shipping-desk-operators"
SUPERUSER_GROUP = "shipping-desk-owners"

STAFF_PERSONA = "staff"


def _span_absence_hint() -> str:
    """Return a clause naming an environment cause for missing ids, if any.

    Nothing here skips -- `tests/unit/test_suite_policy.py` forbids it, and a run
    with no trace context is a run that does not meet FR-46. The environment
    cause is named in the failure instead of being left to be rediscovered.

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


def _assert_trace_context_is_valid(event: dict[str, Any]) -> None:
    """Assert an event's trace and span ids are well-formed and not the null ids.

    Length alone passes on whitespace and on the all-zero ids an invalid span
    context produces, which is the regression the non-zero checks catch.

    Args:
        event: One captured structlog event dictionary.

    """
    trace_id = event["trace_id"]
    span_id = event["span_id"]
    assert len(trace_id) == TRACE_ID_HEX_LEN, f"malformed trace_id {trace_id!r}{_span_absence_hint()}"
    assert len(span_id) == SPAN_ID_HEX_LEN, f"malformed span_id {span_id!r}{_span_absence_hint()}"
    assert int(trace_id, 16) != 0, f"trace_id is the invalid all-zero id: {trace_id!r}"
    assert int(span_id, 16) != 0, f"span_id is the invalid all-zero id: {span_id!r}"


@pytest.fixture
def _local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declare this run local, explicitly rather than by inheritance."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, "local")


@pytest.fixture
def _contract(settings: SettingsWrapper) -> None:
    """Point the claims contract at names that appear nowhere in the source."""
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim=GROUP_CLAIM,
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )


@pytest.fixture
def _groups(db: None) -> None:
    """Provision the designated groups through the component's own one callable.

    The contract above names groups the migration never created, so without this
    the mapper would correctly ignore every asserted group (AD-12) and the sync
    would be a no-op with an empty `groups_added` -- which is exactly what this
    module has to distinguish a real authorization change from.
    """
    provision_designated_groups()


class TestOneLogLineCarriesAllThreeIdentifiers:
    """AC #2: `request_id`, `trace_id` and `span_id`, together, on one line."""

    def test_a_request_event_carries_all_three(
        self,
        client: Client,
        caplog: pytest.LogCaptureFixture,
    ):
        """One dictionary holding all three keys, not three dictionaries.

        A per-key search across the captured events would be satisfied by a
        `request_id` on one line and a `trace_id` on another, which is precisely
        the state SC-7 exists to rule out: neither line would let an operator
        cross from the log view to the trace view.
        """
        with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
            response = client.get(reverse("account_login"))

        assert response.status_code == HTTPStatus.OK

        started = _events(caplog, "request_started")
        assert started, f"django-structlog emitted no request_started event{_span_absence_hint()}"

        carrying = [event for event in started if set(event) >= CORRELATION_KEYS]
        assert carrying, (
            f"no request_started event carried all of {sorted(CORRELATION_KEYS)}; "
            f"one had {sorted(started[0])}{_span_absence_hint()}"
        )

        event = carrying[0]
        _assert_trace_context_is_valid(event)
        assert isinstance(event["request_id"], str)
        assert event["request_id"], "request_id is present but empty"

    def test_the_logged_trace_id_is_one_the_exporter_recorded(
        self,
        client: Client,
        caplog: pytest.LogCaptureFixture,
        recorded_spans: InMemorySpanExporter,
    ):
        """Agreement, not merely presence: the two views name the same trace.

        A `trace_id` on the log line that matched no span would satisfy every
        assertion above while pointing at a trace no backend holds.
        """
        with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
            client.get(reverse("account_login"))

        logged = {event["trace_id"] for event in _events(caplog, "request_started") if "trace_id" in event}
        recorded = {format(span.context.trace_id, "032x") for span in recorded_spans.get_finished_spans()}

        assert logged, f"no request_started event carried a trace_id{_span_absence_hint()}"
        assert logged <= recorded, f"logged trace ids {logged} are not among the recorded ones {recorded}"


@pytest.mark.usefixtures("_local", "_contract", "_groups")
class TestTheAuthorizationChangeEventIsCorrelated:
    """AC #4: the mapper's own event carries the request's identifiers."""

    def test_authorization_synced_carries_the_requests_identifiers(
        self,
        client: Client,
        caplog: pytest.LogCaptureFixture,
        recorded_spans: InMemorySpanExporter,
    ):
        """Driven through the real mapper inside a real request.

        `persona_signin` runs `resolve_user` then `sync_for_interactive` inside
        the request, so `authorization.synced` is emitted with the request's
        contextvars still bound -- which is the only condition under which it can
        carry `request_id` at all. Nothing here reaches the network: the claims
        are synthesized by `config.local_dev.personas.build_claims` and there is
        no JWKS fetch.

        The existing coverage in
        `tests/integration/authorization/test_mapper_sync.py` reads this event
        through `structlog.testing.capture_logs`, which by construction can see
        neither identifier. That is the gap this case closes.

        `groups_added` is asserted non-empty so the event under test is a real
        authorization change rather than a no-op sync, which would carry the same
        keys and prove nothing about the case an operator actually audits.
        """
        with caplog.at_level(logging.INFO, logger=MAPPER_LOGGER):
            response = client.post(reverse(LOCAL_SIGNIN_URL_NAME, kwargs={"persona_key": STAFF_PERSONA}))

        assert response.status_code == HTTPStatus.FOUND

        synced = _events(caplog, "authorization.synced")
        assert synced, "the mapper emitted no authorization.synced event for the persona sign-in"

        event = synced[0]
        assert set(event) >= CORRELATION_KEYS, (
            f"authorization.synced carried {sorted(event)}, missing {sorted(CORRELATION_KEYS - set(event))}"
            f"{_span_absence_hint()}"
        )
        _assert_trace_context_is_valid(event)
        assert event["request_id"], "request_id is present but empty"

        # A tuple, not a list: `SyncOutcome.added` is declared as one and the
        # event carries it unconverted, so a membership check that happened to
        # pass on either would hide a change in the payload's shape.
        groups_added = event["groups_added"]
        assert isinstance(groups_added, tuple), f"groups_added is {type(groups_added).__name__}, not a tuple"
        assert STAFF_GROUP in groups_added, f"the staff persona's sync added {groups_added}"

        recorded = {format(span.context.trace_id, "032x") for span in recorded_spans.get_finished_spans()}
        assert event["trace_id"] in recorded, (
            f"the authorization event's trace id {event['trace_id']} is not among the recorded ones {recorded}"
        )
