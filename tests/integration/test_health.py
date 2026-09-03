"""The probe endpoints against the real thing: a real database and the real stack.

Three claims live here that the unit suite structurally cannot make.

**Liveness issues no query through the whole middleware stack.** The unit twin
calls the view directly and therefore bypasses every middleware -- including
`django_structlog.middlewares.RequestMiddleware`, which binds `user_id` and
resolves `request.user` to do it. Resolving the lazy user reads the session, and
a session backend that had to be loaded from the database would put a query on
the liveness path and break NFR-2 without a single line of this component's code
changing. That is a hazard to *measure*, not to reason about, so it is measured:
`django_assert_num_queries(0)` around an anonymous client request to `/livez`.

**Readiness answers 200 against a real connection.** The unit suite hands
readiness a fake connection, which proves the decision and proves nothing about
`SELECT 1` being a statement a real backend accepts.

**Readiness still answers 200 with an unapplied migration present.** This is AC #4
stated as an experiment rather than as an absence: a migration is un-recorded, so
Django's own executor reports work outstanding, and readiness answers 200 anyway.
It is the assertion that would fail the day somebody adds a migration check
"while they are in there", which the unit suite's import scan would not catch if
the check arrived through a management command or a raw query.

The migration case mutates `django_migrations`. `django_db` wraps each test in a
transaction that is rolled back, and the case restores the row itself as well:
one of those alone would be enough, and a test that leaves the migration table
short of a row poisons every test that runs after it in the same session.
"""

from __future__ import annotations

from contextlib import contextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.db.utils import OperationalError
from django.urls import reverse

from config.health import state
from config.health.views import ALIAS_ERROR
from config.health.views import ALIAS_OK
from config.health.views import STATUS_READY
from config.health.views import STATUS_UNREADY
from config.health.views import _required_aliases

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.test import Client

pytestmark = pytest.mark.integration

#: The alias every combination has.
DEFAULT_ALIAS: Final[str] = "default"


@pytest.fixture(autouse=True)
def _reset_health_state() -> Iterator[None]:
    """Give every case a process that has just started, and leave one behind.

    The flags are process-global and one-way. Without this, the first case to
    reach a healthy probe would leave `first_contact_made()` True for the rest of
    the session, and the unit module's AC #3 assertions -- which run in the same
    process under `pixi run test-cov` -- would pass on that rather than on
    anything they did themselves.
    """
    state.reset_health_state_for_testing()
    yield
    state.reset_health_state_for_testing()


@contextmanager
def broken_cursor(alias: str) -> Iterator[None]:
    """Make one real connection refuse to open a cursor, then put it back exactly.

    Written out rather than done with `monkeypatch.setattr`, which restores by
    *assigning* the value it read -- and `cursor` is inherited from
    `BaseDatabaseWrapper`, so what it read is a bound method and what it would
    put back is an instance attribute the connection never carried. This installs
    an instance attribute and deletes it again, which leaves the object in the
    state it was found in.

    Args:
        alias: The alias whose connection should refuse.

    Yields:
        None. The refusal is the effect.

    Raises:
        AssertionError: The connection already carries its own `cursor`, which
            this helper would otherwise clobber and then delete.

    """
    connection = connections[alias]
    if "cursor" in vars(connection):
        message = f"the {alias} connection already carries its own `cursor`; this helper would clobber it"
        raise AssertionError(message)

    def _refuse(*_args: Any, **_kwargs: Any) -> None:
        message = "connection refused"
        raise OperationalError(message)

    connection.cursor = _refuse  # type: ignore[method-assign]
    try:
        yield
    finally:
        del connection.cursor  # type: ignore[attr-defined]


@pytest.fixture
def unreachable_default_database() -> Iterator[None]:
    """Break the `default` connection for the duration of one case.

    Yields:
        None.

    """
    with broken_cursor(DEFAULT_ALIAS):
        yield


# ---------------------------------------------------------------------------
# Both routes resolve by name and answer an unauthenticated probe (AC #5)
# ---------------------------------------------------------------------------


def test_the_probe_routes_resolve_at_the_documented_paths() -> None:
    """The paths a deployment manifest is written against are these two, exactly."""
    assert reverse("liveness") == "/livez"
    assert reverse("readiness") == "/readyz"


@pytest.mark.django_db
def test_liveness_answers_an_anonymous_probe(client: Client) -> None:
    """AC #1: a probe carries no credential, and liveness answers it anyway."""
    response = client.get(reverse("liveness"))

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "text/plain; charset=utf-8"


@pytest.mark.django_db
def test_readiness_answers_an_anonymous_probe(client: Client) -> None:
    """AC #2: readiness is reachable with no session and no bearer token.

    `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]` is `IsAuthenticated`, which is
    why these are not DRF views. If they ever became DRF views this case would
    report 403 and say so.
    """
    response = client.get(reverse("readiness"))

    assert response.status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# Liveness touches nothing external, through the whole stack (AC #1, NFR-2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_liveness_issues_no_query_through_the_middleware_stack(
    client: Client,
    django_assert_num_queries: Any,
) -> None:
    """NFR-2 measured where it can actually fail: with every middleware installed.

    See the module docstring for the specific hazard this is aimed at. If this
    ever fails, the fix is to exclude the health URLs from the offending
    binding -- never to drop the middleware and never to relax the count.
    """
    with django_assert_num_queries(0):
        response = client.get(reverse("liveness"))

    assert response.status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# Readiness against a real connection (AC #2, AC #3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_reports_every_required_alias_ok(client: Client) -> None:
    """AC #2: the body names each required alias, and each one answered."""
    response = client.get(reverse("readiness"))

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "status": STATUS_READY,
        "databases": dict.fromkeys(_required_aliases(), ALIAS_OK),
    }
    assert set(response.json()["databases"]) == {DEFAULT_ALIAS}


@pytest.mark.django_db
def test_readiness_answers_503_when_a_required_connection_raises(
    client: Client,
    unreachable_default_database: None,
) -> None:
    """AC #2: a required database that does not answer makes the process unready.

    503 and not 500: the process is fine, its dependency is not, and the platform
    should stop routing to it rather than restart it.
    """
    response = client.get(reverse("readiness"))

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json() == {"status": STATUS_UNREADY, "databases": {DEFAULT_ALIAS: ALIAS_ERROR}}
    assert state.first_contact_made() is False


@pytest.mark.django_db
def test_readiness_recovers_once_the_database_answers_again(client: Client) -> None:
    """A brief outage degrades the component; it does not latch it unready.

    This is AD-22's stated purpose seen from the other end: the process stayed
    alive through the refusal, so it is available to answer 200 the moment its
    dependency returns.
    """
    with broken_cursor(DEFAULT_ALIAS):
        assert client.get(reverse("readiness")).status_code == HTTPStatus.SERVICE_UNAVAILABLE

    assert client.get(reverse("readiness")).status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# Readiness never re-checks migrations (AC #4)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_answers_200_with_an_unapplied_migration_present(client: Client) -> None:
    """AC #4, as an experiment rather than as an absence.

    The scenario is a rolling deploy: the release stage migrated first, so every
    still-serving replica of the old generation is running against a newer schema
    and sees migrations it has not applied. Reporting those replicas unready
    would drain the whole old generation at once and turn a backwards-compatible
    migration into an outage.

    A recorded migration is un-recorded here, which is what "an unapplied
    migration is present" means to every mechanism that could check -- Django's
    own executor is asked, and reports outstanding work -- and readiness answers
    200 regardless.
    """
    connection = connections[DEFAULT_ALIAS]
    loader = MigrationExecutor(connection).loader
    app_label, name = next(node for node in sorted(loader.graph.leaf_nodes()) if node in loader.applied_migrations)
    recorder = MigrationRecorder(connection)

    recorder.record_unapplied(app_label, name)
    try:
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        assert plan != [], "the test could not create the unapplied-migration state it asserts over"

        response = client.get(reverse("readiness"))
    finally:
        recorder.record_applied(app_label, name)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == STATUS_READY
