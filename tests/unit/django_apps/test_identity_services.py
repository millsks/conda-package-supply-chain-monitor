"""What the resolution service refuses, before it ever reaches a row.

`CPM-AD-25` makes `identity`'s resolution service the only creator of a package
row, and `CPM-AD-14` keeps it that way: identity is mutated by resolution or by
the override path, and by nothing else. That makes its refusals load bearing in a
way an ordinary validation is not -- a record this door accepts becomes a
permanent row that every later story treats as a package.

**Only the refusals are here.** Creating a shell writes to `packages`, so the
behaviour -- first sight creates, second sight reuses, an existing row is left
alone -- is in
`tests/integration/django_apps/test_inventory_ingestion.py`, where there is a
table for the row to be in. What is decided before any query is whether the
inputs can describe a package at all, and that is what this module holds.

**Each refusal exists because the failure it prevents lands somewhere else.** A
blank key makes a row that cannot be corrected, exported or found again. An
over-long key is stored truncated by SQLite and refused by PostgreSQL, so it is a
working row on a developer's machine and a failed run in the gate. A naive
`resolved_at` is stored by Django as though it were UTC, so the provenance record
`CPM-FR-2` requires says the identity was established at a time it was not.

No database and no network: every case here raises before the service issues a
query, which is the property being asserted as much as the message is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import pytest

from conda_package_supply_chain_monitor.core.clock import Clock
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.services import CANONICAL_NAME_FIELD
from conda_package_supply_chain_monitor.identity.services import CANONICAL_NAME_LENGTH
from conda_package_supply_chain_monitor.identity.services import ResolutionError
from conda_package_supply_chain_monitor.identity.services import resolve_package_shell
from tests.clocks import FIXED_INSTANT

#: A source package key a case uses when it does not care which.
A_KEY: Final[str] = "internal/numpy"

#: What a case names as having established the identity. The inventory
#: collector's own name in production (`CPM-FR-2`); any non-blank name here,
#: because what these cases are about is the *other* arguments.
A_SOURCE: Final[str] = "inventory"

#: A naive instant, for the clock that answers one. `FixedClock` refuses to be
#: built from one and `SystemClock` cannot produce one, so this is what a writer
#: that went around the clock looks like from the service's side -- which is the
#: only way the refusal is reachable at all.
A_NAIVE_INSTANT: Final[datetime] = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - naive on purpose; see above


class NaiveClock:
    """A clock that answers a naive instant, which no real clock can.

    `Clock` is `runtime_checkable` and that check sees method *names* only, which
    is exactly the hole this stands in: a class whose `now` returns a naive
    datetime satisfies the protocol and breaks every comparison made against a
    value read back from the database. The service is what refuses it, and this
    is what lets the refusal be reached.
    """

    def now(self) -> datetime:
        """Return a naive instant.

        Returns:
            `A_NAIVE_INSTANT`, unchanged on every call.

        """
        return A_NAIVE_INSTANT


def _too_long_key() -> str:
    """Return a key one character wider than `canonical_name` can hold.

    Read off the model rather than written out, so the case stays correct when
    the column is widened -- and stays a case about the *bound* rather than about
    the number 128.

    Returns:
        A key whose length is `canonical_name.max_length + 1`.

    """
    limit = Package._meta.get_field(CANONICAL_NAME_FIELD).max_length  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    assert limit is not None
    return "n" * (limit + 1)


def test_the_naive_clock_double_satisfies_the_clock_protocol() -> None:
    """The fixture is only meaningful if it is the thing the service accepts.

    A stand-in the type system would have refused anyway proves nothing about a
    runtime check, and this is the hole `core/clock.py` records: `isinstance`
    against a `runtime_checkable` protocol sees method names and not what they
    return.
    """
    assert isinstance(NaiveClock(), Clock)


@pytest.mark.parametrize(
    "key",
    [pytest.param("", id="empty"), pytest.param("   ", id="whitespace"), pytest.param("\t\n", id="blank-lines")],
)
def test_a_key_that_names_nothing_is_refused(key: str) -> None:
    """A package with no name cannot be corrected, exported or found again.

    `blank=False` is a form rule and nothing here runs a form, so without this
    the empty string is a canonical name the database accepts -- once, because
    `unique=True` then refuses the second one, which makes the failure look like
    a duplicate rather than like the nameless row it is.
    """
    with pytest.raises(ResolutionError) as refused:
        resolve_package_shell(source_package_key=key, identity_source=A_SOURCE, clock=FixedClock(instant=FIXED_INSTANT))

    assert "names nothing" in str(refused.value)


def test_a_key_wider_than_the_column_is_refused_rather_than_truncated() -> None:
    """The local-versus-gate parity gap, refused where it is visible.

    SQLite ignores `max_length` and PostgreSQL raises, so an over-long key is a
    stored row locally and a failed run in the gate -- the divergence `R-5`
    names, arriving through the one input this service takes from outside.
    """
    with pytest.raises(ResolutionError) as refused:
        resolve_package_shell(
            source_package_key=_too_long_key(),
            identity_source=A_SOURCE,
            clock=FixedClock(instant=FIXED_INSTANT),
        )

    assert CANONICAL_NAME_FIELD in str(refused.value)


def test_a_naive_resolution_instant_is_refused() -> None:
    """`CPM-AD-26`, and `identity/models.py` says this check is the service's.

    The model declares `resolved_at` with no `default` and no `auto_now_add` and
    performs no awareness check of its own; this is where the check lives. The
    consequence lands far away: `USE_TZ` is on, so Django warns and stores a
    naive value as if it were UTC, and the resolution timestamp `CPM-FR-2`
    requires then records a time the resolution did not happen at.
    """
    with pytest.raises(ResolutionError) as refused:
        resolve_package_shell(source_package_key=A_KEY, identity_source=A_SOURCE, clock=NaiveClock())

    assert "naive resolved_at" in str(refused.value)


@pytest.mark.parametrize("source", [pytest.param("", id="empty"), pytest.param("  ", id="whitespace")])
def test_a_resolution_that_names_no_resolver_is_refused(source: str) -> None:
    """`CPM-FR-2`: a resolution is traceable to what established it.

    The same rule `core/ledger.py` applies to a run, applied to the row that run
    creates -- and refused here rather than at the column for the same reason: a
    blank `CharField` is perfectly valid SQL, so the shell would be written, would
    be counted, and would name nothing. It matters more for a shell than for a
    real resolution, because the source key survives as `canonical_name` only
    until `CPM-IDENTITY-S02` corrects the name.
    """
    with pytest.raises(ResolutionError) as refused:
        resolve_package_shell(
            source_package_key=A_KEY,
            identity_source=source,
            clock=FixedClock(instant=FIXED_INSTANT),
        )

    assert "identity_source" in str(refused.value)


def test_the_declared_name_bound_is_the_one_the_column_declares() -> None:
    """The anti-drift half of the bound the record contract borrows.

    `CANONICAL_NAME_LENGTH` is read off the field at import, and its `getattr`
    default of `0` is the honest answer for a column with no bound -- but it is
    also a value that would refuse every key, silently, everywhere. So the number
    is reconciled against the field here: a `canonical_name` that stopped
    declaring a length fails as a test rather than as an inventory that ingests
    nothing.
    """
    field = Package._meta.get_field(CANONICAL_NAME_FIELD)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert CANONICAL_NAME_LENGTH > 0
    assert field.max_length == CANONICAL_NAME_LENGTH
