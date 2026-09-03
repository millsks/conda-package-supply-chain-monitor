"""Tests for the three-branch database selection in `config.settings.base`.

FR-32 puts a PostgreSQL service on the gate, and the whole mechanism that
selects it is the `DATABASE_URL` environment variable read at
`config/settings/base.py:57`. These tests pin that contract: which branch wins
for which environment, and that the sqlite fallback survives for local
development (AC #4, risk R-5).

The settings module is evicted from `sys.modules` and imported fresh under each
environment, matching `tests/unit/test_settings.py` -- asserting on the
already-imported `django.conf.settings` would only ever show the environment
the suite itself was started in.

No database connection is opened: these tests read the `DATABASES` dict the
module builds, and never connect. Re-importing the module is not free of side
effects, though, and the claim should not be overstated -- it resolves
`BASE_DIR` against the filesystem, may read a `.env`, and calls
`configure_structlog()`, which is process-global. That hazard is inherited from
`test_settings.py` rather than introduced here; it is recorded in the deferred
ledger, and the fixture below at least restores whatever module object was in
place before each test.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

BASE = "config.settings.base"

SQLITE_ENGINE = "django.db.backends.sqlite3"
POSTGRES_ENGINE = "django.db.backends.postgresql"

# Every variable either branch of the selection reads, so each test starts from
# a known-empty environment rather than inheriting the developer's or the gate's.
DATABASE_ENV_VARS = (
    "DATABASE_URL",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
)


@pytest.fixture(autouse=True)
def _evict_base_settings() -> Iterator[None]:
    """Import base settings fresh per test, then put the original module back.

    Popping without restoring leaves the next importer to rebuild the module --
    under whatever environment *it* happens to run in -- and leaves the parent
    package still holding `config.settings.base` as an attribute pointing at a
    module built under a monkeypatched environment. Restoring both closes that.
    """
    package_name, _, attribute = BASE.rpartition(".")
    package = sys.modules.get(package_name)
    original = sys.modules.pop(BASE, None)
    try:
        yield
    finally:
        sys.modules.pop(BASE, None)
        if original is not None:
            sys.modules[BASE] = original
            if package is not None:
                setattr(package, attribute, original)


@pytest.fixture(autouse=True)
def _clean_database_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every database variable so each test declares its own branch."""
    for name in DATABASE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # A developer with a .env file would otherwise reintroduce DATABASE_URL.
    monkeypatch.delenv("DJANGO_READ_DOT_ENV_FILE", raising=False)


def _load_base() -> ModuleType:
    """Import `config.settings.base` fresh against the current environment."""
    return importlib.import_module(BASE)


def test_database_url_selects_the_named_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Branch 1: `DATABASE_URL` is handed to `env.db()` and decides the engine."""
    monkeypatch.setenv("DATABASE_URL", "postgres://gateuser:gatepass@localhost:5432/gatedb")
    base = _load_base()
    engine = base.DATABASES["default"]["ENGINE"]
    assert engine != SQLITE_ENGINE
    assert engine == POSTGRES_ENGINE
    assert base.DATABASES["default"]["NAME"] == "gatedb"


def test_postgres_variables_select_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    """Branch 2: with no `DATABASE_URL`, `POSTGRES_DB` selects PostgreSQL.

    `POSTGRES_DB` alone is what the branch tests -- `POSTGRES_USER` and
    `POSTGRES_PASSWORD` are then read without a default, so they are required
    to get *through* the branch rather than required to enter it. The
    difference is the subject of the next test.
    """
    monkeypatch.setenv("POSTGRES_DB", "appdb")
    monkeypatch.setenv("POSTGRES_USER", "appuser")
    monkeypatch.setenv("POSTGRES_PASSWORD", "apppass")
    base = _load_base()
    assert base.DATABASES["default"]["ENGINE"] == POSTGRES_ENGINE
    assert base.DATABASES["default"]["NAME"] == "appdb"


def test_partial_postgres_variables_refuse_rather_than_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Branch 2 half-configured refuses at import; it does not degrade to sqlite.

    This is the realistic developer mistake -- `POSTGRES_DB` exported, the
    credentials not -- and refusing is the correct behaviour: silently serving
    the sqlite fallback to someone who has asked for PostgreSQL is exactly the
    parity gap R-5 warns about, arrived at by accident. Pinned so a later
    `default=` on either variable is a deliberate decision rather than a slip.
    """
    monkeypatch.setenv("POSTGRES_DB", "appdb")
    with pytest.raises(ImproperlyConfigured):
        _load_base()


def test_an_empty_database_url_falls_back_rather_than_selecting_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`DATABASE_URL=""` is not a PostgreSQL selection -- the branch is truthiness.

    `base.py:57` reads the variable for truthiness, so an empty value skips
    branch 1 entirely and lands on sqlite. Pinned because it is the single
    edit that would revert the gate to the substitution while leaving the
    variable present; `tests/unit/test_gate_contract.py` guards the other end
    of the same hole by asserting the value CI actually sets.
    """
    monkeypatch.setenv("DATABASE_URL", "")
    base = _load_base()
    assert base.DATABASES["default"]["ENGINE"] == SQLITE_ENGINE


def test_an_empty_postgres_db_falls_back_rather_than_half_selecting(monkeypatch: pytest.MonkeyPatch) -> None:
    """`POSTGRES_DB=""` is the sibling of the empty-URL case, and behaves alike.

    `base.py:59` is a truthiness branch too, so an exported-but-empty
    `POSTGRES_DB` skips branch 2 rather than entering it and raising for the
    missing credentials. Pinned because the two branches are read the same way
    and only one of them was covered.
    """
    monkeypatch.setenv("POSTGRES_DB", "")
    base = _load_base()
    assert base.DATABASES["default"]["ENGINE"] == SQLITE_ENGINE


def test_no_database_environment_falls_back_to_sqlite() -> None:
    """Branch 3 (AC #4): a developer with nothing running still gets a database.

    The divergence from the gate's PostgreSQL is R-5 -- a knowingly traded
    parity gap, not a defect -- so this fallback is load-bearing and must not
    be removed to make the gate stricter.
    """
    base = _load_base()
    assert base.DATABASES["default"]["ENGINE"] == SQLITE_ENGINE
    assert base.DATABASES["default"]["NAME"].endswith("db.sqlite3")


def test_database_url_wins_over_the_postgres_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """The branches are ordered, not merged: the gate sets only `DATABASE_URL`."""
    monkeypatch.setenv("DATABASE_URL", "postgres://gateuser:gatepass@localhost:5432/gatedb")
    monkeypatch.setenv("POSTGRES_DB", "ignored")
    monkeypatch.setenv("POSTGRES_USER", "ignored")
    monkeypatch.setenv("POSTGRES_PASSWORD", "ignored")
    base = _load_base()
    assert base.DATABASES["default"]["NAME"] == "gatedb"


@pytest.mark.parametrize(
    ("environment", "expected_engine"),
    [
        ({"DATABASE_URL": "postgres://gateuser:gatepass@localhost:5432/gatedb"}, POSTGRES_ENGINE),
        (
            {"POSTGRES_DB": "appdb", "POSTGRES_USER": "appuser", "POSTGRES_PASSWORD": "apppass"},
            POSTGRES_ENGINE,
        ),
        ({}, SQLITE_ENGINE),
    ],
    ids=["database-url", "postgres-variables", "sqlite-fallback"],
)
def test_every_branch_sets_atomic_requests(
    environment: dict[str, str],
    expected_engine: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ATOMIC_REQUESTS` is applied whichever branch wins.

    It is a PostgreSQL-meaningful setting that sqlite tolerates, so it is
    exactly the kind of configuration a sqlite-only suite never proves. The
    assertion iterates every configured alias rather than naming `default`,
    because AD-9 forecasts a second database and a check written against one
    key would quietly stop covering the rest. It reads the key with `.get()`
    for that same reason: when the second alias does arrive, this should report
    which database is missing the setting, not raise a bare `KeyError` from
    inside a generator expression.
    """
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    base = _load_base()
    assert base.DATABASES["default"]["ENGINE"] == expected_engine
    without = [alias for alias, config in base.DATABASES.items() if config.get("ATOMIC_REQUESTS") is not True]
    assert without == [], f"ATOMIC_REQUESTS is not set on {without}"


# ---------------------------------------------------------------------------
# Story 3.2 -- the local substitution as a reusable selection (AD-9).
#
# `apply_local_database_substitution` is called on the module's own `DATABASES`
# at import, where it is a no-op today: the three branches above always leave
# `default` configured. Its reason for existing is the alias a contributed
# database adds in Epic 9, and that alias is unit-testable now -- the function
# takes a plain dict, so these tests need neither a second database nor a
# connection. Testing it only through the module would mean the hook stayed
# unexercised until the epic that depends on it arrived.
# ---------------------------------------------------------------------------


def test_local_substitution_fills_an_unconfigured_extra_alias() -> None:
    """AD-9's hook: an alias with no configuration gets its own sqlite database.

    "Its own" is the assertion that matters. Two aliases pointing at one file
    would satisfy a naive check that both are sqlite while giving a contributed
    database the same tables as the component's -- so the filenames are asserted
    distinct rather than merely present.
    """
    base = _load_base()
    databases = {"default": dict(base.DATABASES["default"]), "contributed": {}}

    base.apply_local_database_substitution(databases, base.BASE_DIR)

    assert databases["contributed"]["ENGINE"] == SQLITE_ENGINE
    assert databases["contributed"]["NAME"] != databases["default"]["NAME"]


def test_local_substitution_leaves_a_configured_alias_untouched() -> None:
    """A substitution that shadowed a real database would be a data-loss bug.

    The developer who has pointed a second alias at a running PostgreSQL is the
    one the substitution must not help: silently rewriting their configuration
    to a local file would send every write to a database they never named, and
    the reads that followed would succeed against it.
    """
    base = _load_base()
    configured = {"ENGINE": POSTGRES_ENGINE, "NAME": "contributeddb", "HOST": "contributed.internal"}
    databases = {"default": {}, "contributed": dict(configured)}

    base.apply_local_database_substitution(databases, base.BASE_DIR)

    assert databases["contributed"] == configured


def test_the_default_alias_is_unchanged_by_the_substitution_call_site() -> None:
    """The new call site runs at import, so `default` is asserted after it has.

    The regression this catches is the alias-aware filename being applied to
    `default` as well: `db.default.sqlite3` would be a *new, empty* database for
    every existing checkout, which looks from the outside like the data having
    vanished. `default` keeps `db.sqlite3`, and the three branches above -- not
    the substitution -- remain what decides its backend.
    """
    base = _load_base()

    name = base.DATABASES["default"]["NAME"]

    assert name.endswith("db.sqlite3")
    assert not name.endswith("db.default.sqlite3")
    assert list(base.DATABASES) == ["default"], "the base configures one database; a second is Epic 9's"
