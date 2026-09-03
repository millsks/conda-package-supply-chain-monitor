"""Schema-strictness tests that run against whatever `DATABASE_URL` names.

In the gate that is PostgreSQL (FR-32); locally, with nothing running, it is
the sqlite substitution. The file is skip-free and engine-blind by design: AC #2
forbids skipping or `xfail`ing a PostgreSQL failure, and a test that branched on
the engine would be the same evasion written differently. So every assertion
here is one both backends must satisfy -- what changes between them is only how
much of the declared schema is genuinely being enforced, which is the parity gap
R-5 names and the reason the gate runs on PostgreSQL at all.

Each test relies on pytest-django's `db` fixture, which wraps the test in a
transaction and rolls it back, so the database is left exactly as it was found.
Not `transactional_db`, which is a different fixture with the opposite property
-- it commits and truncates afterwards -- and must not be substituted here on
the strength of the word "transaction" in this paragraph. The writes expected to
fail are wrapped in an inner `transaction.atomic()` block: on PostgreSQL a
failed statement poisons the enclosing transaction until it is rolled back to a
savepoint, which sqlite does not require -- itself an instance of the
permissiveness this story is about.
"""

from __future__ import annotations

import os

import environ
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import connection
from django.db import transaction

from django_service.users.models import CredentialEpoch
from django_service.users.models import User

pytestmark = pytest.mark.integration

NAME_MAX_LENGTH = User._meta.get_field("name").max_length  # noqa: SLF001
assert NAME_MAX_LENGTH is not None, "users.User.name must declare a max_length for this module to assert anything"

JTI_MAX_LENGTH = CredentialEpoch._meta.get_field("jti").max_length  # noqa: SLF001
assert JTI_MAX_LENGTH is not None, "users.CredentialEpoch.jti must declare a max_length for this module to assert"

# Every URL scheme `django-environ` resolves to a PostgreSQL backend, read from
# the library rather than listed here. `postgres://` and `postgresql://` are not
# the only ones -- `psql://`, `pgsql://` and `postgis://` are all accepted and
# all report `connection.vendor == "postgresql"` -- and a developer using one of
# them is correctly configured. A hand-written pair would have failed their run
# for it, which is the same mistake as deriving the expectation from
# `DATABASE_URL` while ignoring the `POSTGRES_DB` branch.
POSTGRES_URL_SCHEMES = tuple(
    f"{scheme}://" for scheme, backend in environ.Env.DB_SCHEMES.items() if backend.endswith(("postgresql", "postgis"))
)

# Sentinel distinguishing "the column reports no width" from "there is no such
# column" -- a bare `next()` default of None would conflate the two.
_MISSING = object()


@pytest.mark.django_db
def test_the_connection_is_the_backend_database_url_names() -> None:
    """The declared environment actually reached the live connection.

    Everything else in this file passes on either backend, so without this the
    suite cannot tell a PostgreSQL gate from a sqlite one and FR-32 could be
    reverted -- by emptying the URL, or by anything overriding `DATABASES`
    downstream of it -- with every test still green.

    Both PostgreSQL-selecting branches of `config/settings/base.py:57-69` are
    read, not just the URL: a developer configured through `POSTGRES_DB` is on
    PostgreSQL too, and deriving the expectation from `DATABASE_URL` alone
    would fail their run for being correctly configured.

    This is not the engine conditional AC #2 forbids. That prohibition is
    against suppressing a PostgreSQL failure; nothing here skips or tolerates
    anything. The expectation is derived from the declared environment and then
    asserted unconditionally, so both legs assert and either can fail.
    """
    url = os.environ.get("DATABASE_URL", "")
    selects_postgres = url.startswith(POSTGRES_URL_SCHEMES) or (not url and bool(os.environ.get("POSTGRES_DB")))
    expected_vendor = "postgresql" if selects_postgres else "sqlite"
    assert connection.vendor == expected_vendor, (
        f"DATABASE_URL={url!r} implies a {expected_vendor} connection, got {connection.vendor}"
    )


@pytest.mark.django_db
def test_the_migrated_schema_is_reachable() -> None:
    """The migrations applied and the application's own tables exist."""
    tables = set(connection.introspection.table_names())
    assert "users_user" in tables
    assert "django_migrations" in tables

    with connection.cursor() as cursor:
        columns = {column.name for column in connection.introspection.get_table_description(cursor, "users_user")}
    assert {"id", "username", "email", "name"} <= columns


@pytest.mark.django_db
def test_a_value_at_the_declared_max_length_round_trips_intact() -> None:
    """A write at the boundary is stored whole -- no silent truncation."""
    exact = "n" * NAME_MAX_LENGTH
    user = User.objects.create(username="boundary", email="boundary@example.com", name=exact)
    user.refresh_from_db()
    assert user.name == exact
    assert len(user.name) == NAME_MAX_LENGTH


@pytest.mark.django_db
def test_the_column_is_declared_at_the_max_length_the_model_states() -> None:
    """The width lives in the schema, not only in the Python declaration.

    `display_size` is the declared `varchar(n)` width as the backend itself
    reports it, so this is the one assertion here that reads the database
    rather than the model. Both backends report it as an integer -- PostgreSQL
    derives it from the column's type modifier, sqlite parses it out of the
    stored `varchar(255)` DDL -- so the assertion is exact and unconditional on
    either.

    Not `internal_size`: that is the fixed-width byte size, which is `None` for
    every variable-length type on *both* backends, so a check against it can
    never fail and would pin nothing. What sqlite does not give is enforcement
    -- it stores an over-length value happily -- which is why the sibling
    boundary tests below exist and why the gate runs on PostgreSQL. That is the
    parity gap R-5 names; it is not a reason to weaken this assertion.
    """
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, "users_user")
    reported = next((column.display_size for column in columns if column.name == "name"), _MISSING)
    assert reported is not _MISSING, "users_user has no column named 'name'"
    assert reported == NAME_MAX_LENGTH, f"users_user.name is declared {reported} wide, model says {NAME_MAX_LENGTH}"


@pytest.mark.django_db
def test_the_epoch_jti_column_is_declared_at_the_max_length_the_model_states() -> None:
    """The mapper reads its bound from the model; the migration is what built the column.

    `config.authorization.mapper` refuses a `jti` longer than
    `CredentialEpoch.jti` declares, and it asks the *model* how long that is.
    The column the value actually goes into was written by the migration, so
    the two can drift apart with no test noticing: a narrowed model would start
    refusing credentials the database would have stored, and a widened one
    would let a value through to a `DataError` on PostgreSQL in the middle of
    an authentication. Read exactly as the `users_user.name` width above is,
    for the same reasons.
    """
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, "users_credentialepoch")
    reported = next((column.display_size for column in columns if column.name == "jti"), _MISSING)
    assert reported is not _MISSING, "users_credentialepoch has no column named 'jti'"
    assert reported == JTI_MAX_LENGTH, (
        f"users_credentialepoch.jti is declared {reported} wide, model says {JTI_MAX_LENGTH}"
    )


@pytest.mark.django_db
def test_a_value_over_the_declared_max_length_is_rejected() -> None:
    """An over-length write raises rather than being quietly shortened.

    Asserted through model validation, which holds on both backends. sqlite
    ignores a `VARCHAR(n)` length entirely and would store the long value, so
    the database-level half of this guarantee is real only on PostgreSQL --
    which is precisely why the gate runs there, and why the sibling test above
    reads the declared width out of the schema.

    `full_clean()` on an unsaved user reports every invalid field at once, so
    the assertion names `name` explicitly: a bare `pytest.raises` here would
    also be satisfied by the blank `password` this instance carries, and would
    keep passing if the length rule were removed entirely.
    """
    too_long = "n" * (NAME_MAX_LENGTH + 1)
    user = User(username="overlong", email="overlong@example.com", name=too_long)
    with pytest.raises(ValidationError) as excinfo:
        user.full_clean()
    assert "name" in excinfo.value.error_dict, f"expected a name error, got {sorted(excinfo.value.error_dict)}"


@pytest.mark.django_db
def test_a_duplicate_username_is_rejected_by_the_database() -> None:
    """The declared `unique` constraint is enforced by the schema, not the form."""
    User.objects.create(username="taken", email="first@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(username="taken", email="second@example.com")
    assert User.objects.filter(username="taken").count() == 1


@pytest.mark.django_db
def test_a_null_in_a_not_null_column_is_rejected_by_the_database() -> None:
    """`null=False` is a schema constraint, and the schema is what enforces it."""
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(username="nullname", email="nullname@example.com", name=None)
    assert not User.objects.filter(username="nullname").exists()
