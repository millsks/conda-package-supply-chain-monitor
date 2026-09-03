"""Tests for the two probe views and the per-process state they read (AD-22, FR-42).

The load-bearing assertion in this module is
`test_liveness_issues_no_query_at_the_view`: NFR-2 makes "liveness touches
nothing external" a system-wide invariant, and `django_assert_num_queries(0)` is
its mechanical form. It is deliberately not an inspection of the view's body -- a
source scan would pass over a view that called a helper that opened a connection,
which is precisely how the invariant gets lost. Its full-stack twin lives in
`tests/integration/test_health.py`, because this one calls the view directly and
therefore bypasses every middleware, including the one that binds `user_id` and
could resolve `request.user`.

These are unit tests. Readiness is exercised against a fake connection handler
rather than a real database wherever the point is the *decision* readiness makes
-- which is every case here except the zero-query assertion, which needs a
connection to count queries on and counts none. The real database is
`tests/integration/test_health.py`'s job.

The fake handler is a plain `dict`, and that is not a shortcut. `readiness` reads
exactly two things from `django.db.connections`: it iterates it for the
configured aliases and it subscripts it for one connection. A dict does both, so
the substitution is faithful to the whole surface the view uses, and it keeps
these cases from depending on the shape of a Django internal they do not test.

The autouse fixture is not hygiene. Both flags are process-global and one-way, so
without it the first case to reach a healthy probe would leave
`first_contact_made()` True for every case after it, and every later "readiness
refuses before first contact" assertion would be passing on the flag another test
set rather than on anything the code under test did.
"""

from __future__ import annotations

import ast
import json
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Final
from typing import Self

import pytest
import structlog
from django.db import connections
from django.db.utils import OperationalError
from django.test import RequestFactory
from django.urls import reverse

from config.component.loader import ComponentDeclaration
from config.component.loader import DatabaseDeclaration
from config.health import state
from config.health import views as health_views
from config.health.views import ALIAS_ERROR
from config.health.views import ALIAS_OK
from config.health.views import LIVENESS_BODY
from config.health.views import PROBE_QUERY
from config.health.views import STATUS_READY
from config.health.views import STATUS_UNREADY
from config.health.views import _required_aliases
from config.health.views import liveness
from config.health.views import readiness

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

    from django.http import HttpResponse
    from structlog.typing import EventDict

#: The alias every combination has. Named once so a rename is one edit.
DEFAULT_ALIAS: Final[str] = "default"

#: The module whose source the AC #4 assertions parse. Taken from the imported
#: module rather than spelled as a path, so a move fails on the import rather
#: than leaving a stale literal that parses nothing and passes.
VIEWS_SOURCE: Final[Path] = Path(str(health_views.__file__))

#: The import prefix that would make readiness a migration check.
FORBIDDEN_IMPORT_PREFIX: Final[str] = "django.db.migrations"

#: Names that reach migration state without importing that package by that path
#: -- the three Django exposes, the management command, and the table a
#: hand-written query would have to name.
FORBIDDEN_MIGRATION_NAMES: Final[frozenset[str]] = frozenset(
    {
        "MigrationExecutor",
        "MigrationLoader",
        "MigrationRecorder",
        "django_migrations",
        "showmigrations",
    }
)


@pytest.fixture(autouse=True)
def _reset_health_state() -> Iterator[None]:
    """Give every case a process that has just started, and leave one behind."""
    state.reset_health_state_for_testing()
    yield
    state.reset_health_state_for_testing()


class _FakeCursor:
    """A cursor that answers the probe query with no database behind it.

    Attributes:
        executed: Every statement handed to `execute`, so a case can assert both
            that readiness issued the probe query and that it issued nothing else.

    """

    def __init__(self) -> None:
        self.executed: list[str] = []

    def __enter__(self) -> Self:
        """Enter the context manager readiness opens the cursor in."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Leave the context manager, suppressing nothing."""
        return False

    def execute(self, sql: str) -> None:
        """Record one statement.

        Args:
            sql: The statement readiness issued.

        """
        self.executed.append(sql)


class _FakeConnection:
    """One database connection, healthy or not, without a server.

    Attributes:
        cursor_handed_out: The cursor `cursor()` returns, so a case can read back
            what was executed on it.
        failure: The exception `cursor()` raises instead of answering, or None
            when the connection is healthy.

    """

    def __init__(self, failure: Exception | None = None) -> None:
        self.cursor_handed_out = _FakeCursor()
        self.failure = failure

    def cursor(self) -> _FakeCursor:
        """Hand out a cursor, or fail the way an unreachable server does.

        Returns:
            The cursor.

        Raises:
            Exception: Whatever `failure` holds, when it holds anything.

        """
        if self.failure is not None:
            raise self.failure
        return self.cursor_handed_out


@pytest.fixture
def healthy_database(monkeypatch: pytest.MonkeyPatch) -> _FakeConnection:
    """Configure one `default` alias whose connection answers the probe query.

    Args:
        monkeypatch: pytest's patcher, which restores `connections` on teardown.

    Returns:
        The connection readiness will be handed.

    """
    connection = _FakeConnection()
    monkeypatch.setattr(health_views, "connections", {DEFAULT_ALIAS: connection})
    return connection


@pytest.fixture
def unreachable_database(monkeypatch: pytest.MonkeyPatch) -> _FakeConnection:
    """Configure one `default` alias whose connection refuses to open a cursor.

    `OperationalError` is what a real driver raises when the server is down, and
    it is one of the two types readiness names in its `except` clause.

    Args:
        monkeypatch: pytest's patcher.

    Returns:
        The connection readiness will be handed.

    """
    connection = _FakeConnection(OperationalError("connection refused"))
    monkeypatch.setattr(health_views, "connections", {DEFAULT_ALIAS: connection})
    return connection


#: The control event the capture fixture emits to prove it can see anything at
#: all. Never asserted for by a case -- the fixture removes it before yielding.
_CAPTURE_CONTROL: Final[str] = "health.capture-control"


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EventDict]]:
    """Capture what the views module logs, with two guards the plain helper lacks.

    **The logger is rebound first.** `config.health.views` binds its logger at
    module scope, and structlog is configured with `cache_logger_on_first_use`,
    so the proxy freezes its processor chain the first time anything logs through
    it. `structlog.testing.capture_logs` swaps the chain by mutating the
    configured processor *list in place* -- which reaches a frozen logger only
    while it still holds that same list object. Any test that reconfigured
    structlog with a fresh list earlier in the session (re-importing
    `config.settings.base` does exactly that) leaves this module's cached logger
    pointing at an orphaned chain, and the capture then sees nothing at all. A
    fresh lazy proxy installed here binds inside the capture instead, so what is
    asserted does not depend on what ran before. This is the failure
    `tests/integration/test_site_migration.py` documents from the other side, and
    it is silent: the events still appear on stderr while the capture stays
    empty.

    **The capture is proved live before the case runs.** The control event below
    is emitted and checked at setup, then removed, so a case asserting over an
    empty capture fails here -- naming the cause -- rather than reporting that the
    view logged nothing.

    Args:
        monkeypatch: pytest's patcher, which restores the module's own logger.

    Yields:
        The captured events, in order.

    """
    monkeypatch.setattr(health_views, "logger", structlog.get_logger(health_views.__name__))
    with structlog.testing.capture_logs() as captured:
        health_views.logger.warning(_CAPTURE_CONTROL)
        assert [event["event"] for event in captured] == [_CAPTURE_CONTROL], (
            "structlog.testing.capture_logs() cannot see config.health.views' logger, so every "
            "assertion over what it logged would be vacuous"
        )
        captured.clear()
        yield captured


def _declaration(*databases: DatabaseDeclaration) -> ComponentDeclaration:
    """Build a component declaration carrying nothing but the given databases.

    Args:
        *databases: The `[[databases]]` entries the declaration should carry.

    Returns:
        A declaration valid for readiness's purposes: it reads `databases` and
        nothing else.

    """
    return ComponentDeclaration(
        name="test-component",
        adopted_apps=(),
        selected_features=frozenset(),
        databases=databases,
        processes=(),
        admin_processes=(),
    )


def _declare(monkeypatch: pytest.MonkeyPatch, *databases: DatabaseDeclaration) -> None:
    """Make the views module read the given declaration instead of `component.toml`.

    Args:
        monkeypatch: pytest's patcher.
        *databases: The `[[databases]]` entries the declaration should carry.

    """
    declaration = _declaration(*databases)
    monkeypatch.setattr(health_views, "load_component_declaration", lambda: declaration)


def _body(response: HttpResponse) -> dict[str, Any]:
    """Return one readiness response's decoded body.

    Args:
        response: The response readiness returned.

    Returns:
        The parsed JSON object.

    """
    decoded: dict[str, Any] = json.loads(response.content)
    return decoded


def _parsed_views() -> ast.Module:
    """Return the views module's parsed source.

    Returns:
        The syntax tree, which is what the AC #4 assertions read instead of the
        file's text -- a text search would also match the module docstring that
        explains the rule, which is the opposite of a finding.

    """
    return ast.parse(VIEWS_SOURCE.read_text(encoding="utf-8"), filename=str(VIEWS_SOURCE))


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Return the identity of every docstring constant in one module.

    Args:
        tree: The parsed module.

    Returns:
        The `id()` of each docstring node, so the name scan can exempt prose that
        merely *describes* the machinery it is checking for.

    """
    documented: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            documented.add(id(first.value))
    return documented


# ---------------------------------------------------------------------------
# Liveness (AC #1)
# ---------------------------------------------------------------------------


def test_liveness_answers_200_with_a_plain_text_body() -> None:
    """AC #1: the process answers, and the answer says nothing it had to look up."""
    response = liveness(RequestFactory().get(reverse("liveness")))

    assert response.status_code == HTTPStatus.OK
    assert response.content.decode() == LIVENESS_BODY
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"


@pytest.mark.django_db
def test_liveness_issues_no_query_at_the_view(django_assert_num_queries: Any) -> None:
    """AC #1 and NFR-2, mechanically: liveness opens no connection of its own.

    Called directly rather than through the client, so what is measured is the
    view alone. The middleware stack is measured by the twin assertion in
    `tests/integration/test_health.py`, and both are needed: this one would still
    pass if a middleware started querying, and that one would still pass if this
    view started querying while a middleware stopped.
    """
    with django_assert_num_queries(0):
        liveness(RequestFactory().get(reverse("liveness")))


def test_liveness_answers_a_head_probe() -> None:
    """`HEAD` is a probe verb, and `require_GET` answers it 405.

    `require_safe` is what permits both, verified here rather than assumed:
    `require_GET` is `require_http_methods(["GET"])` in the installed Django and
    refuses `HEAD` outright, so this case is why the view carries the other
    decorator.
    """
    assert liveness(RequestFactory().head(reverse("liveness"))).status_code == HTTPStatus.OK


def test_liveness_refuses_a_write_verb() -> None:
    """Nothing about a probe is a mutation, so `POST` is not a way in."""
    assert liveness(RequestFactory().post(reverse("liveness"))).status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_liveness_forbids_caching() -> None:
    """A cached liveness answer is a dead process reported alive by a proxy."""
    response = liveness(RequestFactory().get(reverse("liveness")))

    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("view", [liveness, readiness], ids=["liveness", "readiness"])
def test_neither_probe_is_wrapped_in_a_transaction(view: Any) -> None:
    """Every alias that declares `ATOMIC_REQUESTS` is exempted on both probes.

    `config/settings/base.py` turns the setting on for `default`, and Django's
    handler wraps a view in a transaction for *each* alias that declares it and
    does not exempt the view. On the liveness path that is a database round trip
    NFR-2 forbids and, with the database down, a 500 raised before the view runs
    -- AD-22's crash loop, arriving through the settings module rather than
    through anything in the view.

    Asserted per alias rather than as "the decorator is present" so that a
    contributed database (Epic 9) turning the setting on for a second alias fails
    here instead of quietly re-arming it for that alias alone.
    """
    exempted = getattr(view, "_non_atomic_requests", set())
    atomic = {alias for alias, config in connections.settings.items() if config.get("ATOMIC_REQUESTS")}

    assert atomic - exempted == set(), f"{view.__name__} is still wrapped in a transaction for {atomic - exempted}"


def test_the_component_still_declares_atomic_requests_somewhere() -> None:
    """The assertion above is vacuous if nothing declares the setting at all.

    It would pass just as happily over a component that had quietly turned
    `ATOMIC_REQUESTS` off everywhere, which is a different change entirely and
    not one this story's evidence should be able to hide.
    """
    assert any(config.get("ATOMIC_REQUESTS") for config in connections.settings.values())


# ---------------------------------------------------------------------------
# Readiness: the ordering, the flag and the refusals (AC #2, AC #3)
# ---------------------------------------------------------------------------


def test_readiness_answers_200_once_every_required_database_answers(healthy_database: _FakeConnection) -> None:
    """AC #2: readiness reports ready when every required alias answers."""
    response = readiness(RequestFactory().get(reverse("readiness")))

    assert response.status_code == HTTPStatus.OK
    assert _body(response) == {"status": STATUS_READY, "databases": {DEFAULT_ALIAS: ALIAS_OK}}
    assert healthy_database.cursor_handed_out.executed == [PROBE_QUERY]
    assert state.first_contact_made() is True


def test_readiness_answers_503_when_a_required_database_does_not(unreachable_database: _FakeConnection) -> None:
    """AC #2: non-200 when a required database does not answer -- 503, never 500."""
    response = readiness(RequestFactory().get(reverse("readiness")))

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert _body(response) == {"status": STATUS_UNREADY, "databases": {DEFAULT_ALIAS: ALIAS_ERROR}}
    assert state.first_contact_made() is False


def test_readiness_logs_the_alias_and_the_failure_type(
    unreachable_database: _FakeConnection,
    captured_events: list[EventDict],
) -> None:
    """Nothing is swallowed: the refusal says which alias and what it raised."""
    readiness(RequestFactory().get(reverse("readiness")))

    events = [event for event in captured_events if event["event"] == "health.readiness_database_unreachable"]
    assert len(events) == 1
    assert events[0]["alias"] == DEFAULT_ALIAS
    assert events[0]["failure"] == OperationalError.__name__


def test_readiness_refuses_before_first_contact_even_when_the_probe_succeeds(
    healthy_database: _FakeConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #3: the flag is what gates the 200, not this probe's result.

    `mark_first_contact` is neutered so the two conditions come apart: the probe
    succeeds, the alias reports `ok`, and readiness still refuses because this
    process holds no record of ever having reached its databases. Without this
    case the flag could be deleted and every other assertion here would pass.
    """
    monkeypatch.setattr(health_views, "mark_first_contact", lambda: None)

    response = readiness(RequestFactory().get(reverse("readiness")))

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert _body(response) == {"status": STATUS_UNREADY, "databases": {DEFAULT_ALIAS: ALIAS_OK}}
    assert state.first_contact_made() is False
    assert healthy_database.cursor_handed_out.executed == [PROBE_QUERY]


def test_readiness_refuses_while_draining_even_with_a_healthy_database(healthy_database: _FakeConnection) -> None:
    """Drain is evaluated first, so a healthy database cannot override it.

    The empty `databases` mapping is the evidence that the ordering holds: no
    alias was asked, because a draining process's answer does not depend on them.
    Story 5.4's shutdown handler is built on exactly this.
    """
    state.begin_drain()

    response = readiness(RequestFactory().get(reverse("readiness")))

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert _body(response) == {"status": STATUS_UNREADY, "databases": {}}
    assert healthy_database.cursor_handed_out.executed == []


def test_readiness_refuses_while_draining_after_first_contact(healthy_database: _FakeConnection) -> None:
    """A process that was ready and is now draining stops being ready."""
    assert readiness(RequestFactory().get(reverse("readiness"))).status_code == HTTPStatus.OK

    state.begin_drain()

    assert readiness(RequestFactory().get(reverse("readiness"))).status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_readiness_refuses_when_a_database_goes_away_after_first_contact(
    healthy_database: _FakeConnection,
) -> None:
    """First contact is a record of the past, never a licence for the present.

    The flag is one-way by design, so the refusal here has to come from the probe
    result. A readiness check that consulted only the flag would report a process
    with a dead database as ready forever after its first successful probe.
    """
    assert readiness(RequestFactory().get(reverse("readiness"))).status_code == HTTPStatus.OK

    healthy_database.failure = OperationalError("server closed the connection unexpectedly")

    response = readiness(RequestFactory().get(reverse("readiness")))

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert state.first_contact_made() is True


def test_readiness_logs_the_drain_refusal(captured_events: list[EventDict]) -> None:
    """A drain refusal that read as a database outage in the logs would mislead."""
    state.begin_drain()

    readiness(RequestFactory().get(reverse("readiness")))

    assert [event["event"] for event in captured_events] == ["health.readiness_refused_draining"]


def test_readiness_answers_a_head_probe(healthy_database: _FakeConnection) -> None:
    """Both probe verbs reach readiness, for the reason they reach liveness."""
    assert readiness(RequestFactory().head(reverse("readiness"))).status_code == HTTPStatus.OK


def test_readiness_refuses_a_write_verb(healthy_database: _FakeConnection) -> None:
    """A probe endpoint is not a way to make something happen."""
    assert readiness(RequestFactory().post(reverse("readiness"))).status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_readiness_forbids_caching(healthy_database: _FakeConnection) -> None:
    """A cached readiness answer routes traffic to a process that stopped being ready."""
    response = readiness(RequestFactory().get(reverse("readiness")))

    assert "no-store" in response.headers["Cache-Control"]


# ---------------------------------------------------------------------------
# Requiredness comes from component.toml, and fails closed (AD-9, AD-26)
# ---------------------------------------------------------------------------


def test_a_declared_required_alias_is_probed(monkeypatch: pytest.MonkeyPatch) -> None:
    """AD-9: `required = true` means readiness must be able to reach it."""
    _declare(monkeypatch, DatabaseDeclaration(alias=DEFAULT_ALIAS, required=True, migrate=()))

    assert _required_aliases() == (DEFAULT_ALIAS,)


def test_a_declared_optional_alias_is_not_probed(monkeypatch: pytest.MonkeyPatch) -> None:
    """AD-9: the requiredness field is read, never inferred from the alias name."""
    _declare(monkeypatch, DatabaseDeclaration(alias=DEFAULT_ALIAS, required=False, migrate=()))

    assert _required_aliases() == ()


def test_an_undeclared_configured_alias_is_treated_as_required(
    monkeypatch: pytest.MonkeyPatch,
    captured_events: list[EventDict],
) -> None:
    """An alias `DATABASES` has and `component.toml` does not is required, and is named.

    Failing closed here is the point: a forgotten `[[databases]]` entry must not
    make readiness quietly stop checking a database the component depends on.
    """
    _declare(monkeypatch)

    aliases = _required_aliases()

    assert aliases == (DEFAULT_ALIAS,)
    undeclared = [event for event in captured_events if event["event"] == "health.readiness_alias_undeclared"]
    assert [event["alias"] for event in undeclared] == [DEFAULT_ALIAS]


def test_a_component_with_no_required_alias_is_ready(
    monkeypatch: pytest.MonkeyPatch,
    healthy_database: _FakeConnection,
) -> None:
    """No required database is a valid component, not a misconfiguration.

    It is ready as soon as it is draining-free, and the empty `databases` mapping
    says why: there was nothing to ask.
    """
    _declare(monkeypatch, DatabaseDeclaration(alias=DEFAULT_ALIAS, required=False, migrate=()))

    response = readiness(RequestFactory().get(reverse("readiness")))

    assert response.status_code == HTTPStatus.OK
    assert _body(response) == {"status": STATUS_READY, "databases": {}}
    assert healthy_database.cursor_handed_out.executed == []


def test_the_shipped_declaration_makes_the_default_alias_required() -> None:
    """The component this repository *is* declares its one database required.

    Read through the real loader and the real `connections`, unlike every case
    above: those prove the reading, and this one proves the file being read says
    what they assume.
    """
    assert _required_aliases() == (DEFAULT_ALIAS,)


# ---------------------------------------------------------------------------
# Readiness never re-checks migrations (AC #4)
# ---------------------------------------------------------------------------


def test_the_views_module_imports_nothing_from_django_db_migrations() -> None:
    """AC #4, at the one place it can be asserted structurally.

    An older replica running against a newer schema during a rolling deploy is a
    legitimate, expected state; a readiness check that compared the migration
    graph would drain the whole old generation for it. The rule is therefore that
    this module cannot reach migration state at all, and the parsed import
    statements are what say so.
    """
    imported: list[str] = []
    for node in ast.walk(_parsed_views()):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.extend(f"{node.module}.{alias.name}" for alias in node.names)

    offending = [name for name in imported if name.startswith(FORBIDDEN_IMPORT_PREFIX)]
    assert offending == [], f"readiness must never re-check migrations, but {VIEWS_SOURCE.name} imports {offending}"


def test_the_views_module_names_no_migration_machinery() -> None:
    """The same rule, against the names that reach migration state without that import.

    Read over identifiers and over non-docstring string constants, so the module
    docstring's explanation of why readiness does not do this is not itself read
    as doing it -- and so a raw `SELECT ... FROM django_migrations` would still be
    caught.
    """
    tree = _parsed_views()
    documented = _docstring_nodes(tree)

    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in documented:
            used.update(node.value.replace(".", " ").split())

    offending = sorted(used & FORBIDDEN_MIGRATION_NAMES)
    assert offending == [], f"{VIEWS_SOURCE.name} reaches migration state through {offending}"
