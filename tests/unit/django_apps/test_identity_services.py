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
table for the row to be in. What a *recorded* resolution does to a row it found
is in `tests/integration/django_apps/test_identity_resolution.py`, for the same
reason. What is decided before any query is whether the inputs can describe a
package at all, and that is what this module holds.

**`record_resolution`'s refusals all precede its lookup, and that ordering is
part of the claim.** Every case below reaches its refusal without a database
because the service validates everything it was handed before it asks which
package the pair names -- so a resolution that cannot be recorded correctly never
touches a row, and a caller that catches `ResolutionError` knows nothing was
half-written. A refusal that had moved after the query would fail here with a
`RuntimeError` about database access rather than passing quietly.

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
from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_package_supply_chain_monitor.core.clock import Clock
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.identity.models import ESTABLISHED
from conda_package_supply_chain_monitor.identity.models import Feedstock
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import MappingKind
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.services import ASSOCIATOR_KEY_FIELD
from conda_package_supply_chain_monitor.identity.services import ASSOCIATOR_KEY_LENGTH
from conda_package_supply_chain_monitor.identity.services import CANONICAL_NAME_FIELD
from conda_package_supply_chain_monitor.identity.services import CANONICAL_NAME_LENGTH
from conda_package_supply_chain_monitor.identity.services import FEEDSTOCK_NAME_FIELD
from conda_package_supply_chain_monitor.identity.services import FEEDSTOCK_NAME_LENGTH
from conda_package_supply_chain_monitor.identity.services import FEEDSTOCK_URL_LENGTHS
from conda_package_supply_chain_monitor.identity.services import PACKAGE_FIELD_LENGTHS
from conda_package_supply_chain_monitor.identity.services import FeedstockMapping
from conda_package_supply_chain_monitor.identity.services import Resolution
from conda_package_supply_chain_monitor.identity.services import ResolutionError
from conda_package_supply_chain_monitor.identity.services import record_resolution
from conda_package_supply_chain_monitor.identity.services import resolve_package_shell
from tests.clocks import FIXED_INSTANT

if TYPE_CHECKING:
    from django.db import models

#: A source package key a case uses when it does not care which.
A_KEY: Final[str] = "internal/numpy"

#: The package name that goes with it, and deliberately not the same string.
#: `CPM-IDENTITY-S07` split the two -- the key becomes `associator_key` and the
#: name becomes `canonical_name` -- and a case supplying one value for both could
#: not tell a service that had put either in the wrong column.
A_NAME: Final[str] = "numpy"

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


def _too_long(field: str) -> str:
    """Return a value one character wider than a column can hold.

    Read off the model rather than written out, so the case stays correct when a
    column is widened -- and stays a case about the *bound* rather than about the
    numbers 128 and 512.

    Args:
        field: The column to exceed.

    Returns:
        A value whose length is that field's `max_length + 1`.

    """
    limit = Package._meta.get_field(field).max_length  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    assert limit is not None
    return "n" * (limit + 1)


def _too_long_key() -> str:
    """Return a source package key one character wider than `associator_key` can hold.

    Returns:
        The over-long key.

    """
    return _too_long(ASSOCIATOR_KEY_FIELD)


def _too_long_name() -> str:
    """Return a package name one character wider than `canonical_name` can hold.

    Returns:
        The over-long name.

    """
    return _too_long(CANONICAL_NAME_FIELD)


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
        resolve_package_shell(
            source_package_key=key,
            package_name=A_NAME,
            identity_source=A_SOURCE,
            clock=FixedClock(instant=FIXED_INSTANT),
        )

    assert "names nothing" in str(refused.value)


def test_a_key_wider_than_its_own_column_is_refused_rather_than_truncated() -> None:
    """The local-versus-gate parity gap, refused where it is visible.

    SQLite ignores `max_length` and PostgreSQL raises, so an over-long key is a
    stored row locally and a failed run in the gate -- the divergence `R-5`
    names, arriving through the one input this service takes from outside.

    Measured against `associator_key`, which is where the key goes.
    """
    with pytest.raises(ResolutionError) as refused:
        resolve_package_shell(
            source_package_key=_too_long_key(),
            package_name=A_NAME,
            identity_source=A_SOURCE,
            clock=FixedClock(instant=FIXED_INSTANT),
        )

    assert ASSOCIATOR_KEY_FIELD in str(refused.value)


@pytest.mark.parametrize(
    "name",
    [pytest.param("", id="empty"), pytest.param("   ", id="whitespace"), pytest.param("\t\n", id="blank-lines")],
)
def test_a_package_name_that_names_nothing_is_refused(name: str) -> None:
    """The name is the other half of the pair, and it is what `canonical_name` becomes.

    `CPM-IDENTITY-S07` separated the two values the source supplies, which means
    a usable key no longer implies a usable name: a record carrying a key and a
    blank name would otherwise write the empty string into `canonical_name`, and
    `unique=True` would then refuse the *second* such row -- making the failure
    look like a duplicate rather than like the nameless row it is.
    """
    with pytest.raises(ResolutionError) as refused:
        resolve_package_shell(
            source_package_key=A_KEY,
            package_name=name,
            identity_source=A_SOURCE,
            clock=FixedClock(instant=FIXED_INSTANT),
        )

    assert "names nothing" in str(refused.value)


def test_a_package_name_wider_than_the_column_is_refused_rather_than_truncated() -> None:
    """The same parity gap as the key's, on the column the name actually lands in.

    The key is measured against `canonical_name`'s bound because the record
    contract is; the name is measured against it because that is the column it is
    written to. Both matter: SQLite stores an over-long value truncated and
    PostgreSQL refuses it, so an unrefused one is a working row locally and a
    failed run in the gate (`R-5`).
    """
    with pytest.raises(ResolutionError) as refused:
        resolve_package_shell(
            source_package_key=A_KEY,
            package_name=_too_long_name(),
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
        resolve_package_shell(
            source_package_key=A_KEY,
            package_name=A_NAME,
            identity_source=A_SOURCE,
            clock=NaiveClock(),
        )

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
            package_name=A_NAME,
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


def test_the_declared_key_bound_is_the_one_its_own_column_declares() -> None:
    """The same anti-drift guard for the second bound, and for their separation.

    `CPM-IDENTITY-S07` split the name from the key, and the two land in two
    columns of two widths. A `getattr` default of `0` would refuse every key
    silently; a bound that had been re-fused onto `canonical_name` would refuse
    legitimately long source keys for a column they no longer occupy. Both are a
    failing test here rather than an inventory that quietly ingests less than it
    was given.
    """
    field = Package._meta.get_field(ASSOCIATOR_KEY_FIELD)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert ASSOCIATOR_KEY_LENGTH > 0
    assert field.max_length == ASSOCIATOR_KEY_LENGTH
    assert ASSOCIATOR_KEY_LENGTH > CANONICAL_NAME_LENGTH


def test_the_declared_feedstock_name_bound_is_the_one_its_column_declares() -> None:
    """The third bound, guarded the same way and read off the model that owns it.

    `Feedstock.name` and `Package.canonical_name` are the same width today and
    are two separate declarations, so a bound read from the wrong model would go
    on passing until one of them moved -- and the failure would then be a
    feedstock refused for a length its own column has room for.
    """
    field = Feedstock._meta.get_field(FEEDSTOCK_NAME_FIELD)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert FEEDSTOCK_NAME_LENGTH > 0
    assert field.max_length == FEEDSTOCK_NAME_LENGTH


@pytest.mark.parametrize(
    ("model", "bounds"),
    [
        pytest.param(Package, PACKAGE_FIELD_LENGTHS, id="package"),
        pytest.param(Feedstock, FEEDSTOCK_URL_LENGTHS, id="feedstock"),
    ],
)
def test_every_declared_bound_is_the_one_its_own_column_declares(
    model: type[models.Model],
    bounds: dict[str, int],
) -> None:
    """The same anti-drift guard, for the tables rather than the three constants.

    A `_column_length` that had started answering `0` -- a column that stopped
    declaring a width, a field name that stopped resolving -- would refuse every
    value silently rather than none, which is the failure mode a bound read off a
    model has and a literal does not. Reconciled here so it is a failing test.
    """
    assert bounds, model.__name__
    for name, limit in bounds.items():
        assert limit > 0, name
        assert model._meta.get_field(name).max_length == limit, name  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


def test_the_bounded_column_table_covers_every_value_a_caller_supplies() -> None:
    """The vacuity guard the table above needs, and the completeness claim.

    A table that had lost an entry would leave that column unbounded with every
    case still green, so the two are reconciled against `Resolution`'s own text
    fields: every string a caller can supply is either bounded here, or is
    `canonical_name`, which carries its own refusal and its own message.
    """
    supplied = {"canonical_name", *PACKAGE_FIELD_LENGTHS}

    assert supplied == {
        "canonical_name",
        "source_repository_url",
        "primary_purl",
        "primary_type",
        "conda_purl",
    }
    assert set(FEEDSTOCK_URL_LENGTHS) == {"url", "metadata_url"}


# ---------------------------------------------------------------------------
# `record_resolution`: what it refuses before it looks anything up.
# ---------------------------------------------------------------------------

#: Every mapping kind answered `not_found`, which is the state a resolution that
#: established nothing is in. The base for the cases below, so each one differs
#: from a recordable resolution by exactly the thing it is about.
NOTHING_FOUND: Final[dict[str, str]] = dict.fromkeys(MappingKind.values, OutcomeState.NOT_FOUND.value)

#: A feedstock a case hands over when it needs a well-formed one.
A_FEEDSTOCK: Final[FeedstockMapping] = FeedstockMapping(name="numpy", url="https://example.invalid/numpy-feedstock")


def _resolution(**overrides: object) -> Resolution:
    """Return a recordable resolution, with any field replaced.

    The base establishes nothing: every kind is `not_found`, no value is
    supplied, and the confidence is `unmapped`. That is the honest floor -- a
    resolution that ran and concluded nothing -- so a case that changes one field
    is asserting about that field rather than about a scaffold of plausible
    values.

    Args:
        **overrides: Fields to replace.

    Returns:
        The resolution.

    """
    fields: dict[str, object] = {
        "identity_source": A_SOURCE,
        "associator_key": A_KEY,
        "confidence": IdentityConfidence.UNMAPPED.value,
        "outcomes": dict(NOTHING_FOUND),
    }
    fields.update(overrides)
    return Resolution(**fields)  # type: ignore[arg-type] - a case's own overrides, checked by the dataclass


def _established(*kinds: str) -> dict[str, str]:
    """Return an outcome table answering `established` for the named kinds.

    Args:
        *kinds: The mapping kinds that were established.

    Returns:
        Every kind answered, the named ones `established` and the rest
        `not_found` -- exhaustive, because the service refuses a table that
        leaves a kind out.

    """
    return {kind: (ESTABLISHED if kind in kinds else OutcomeState.NOT_FOUND.value) for kind in MappingKind.values}


def _too_long_feedstock_name() -> str:
    """Return a feedstock name one character wider than its column can hold.

    Returns:
        The over-long name, read off `Feedstock` rather than off `Package`.

    """
    limit = Feedstock._meta.get_field(FEEDSTOCK_NAME_FIELD).max_length  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    assert limit is not None
    return "f" * (limit + 1)


@pytest.mark.parametrize("source", [pytest.param("", id="empty"), pytest.param("  ", id="whitespace")])
def test_a_recorded_resolution_that_names_no_resolver_is_refused(source: str) -> None:
    """`CPM-FR-2`: a resolution is traceable to what established it.

    The matrix row, and it is not the same refusal `resolve_package_shell` makes.
    There the source becomes a stored value; here it is half of the pair the
    package is *found* by, so a blank one is a lookup that cannot name its
    subject rather than a row that would name nothing.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(identity_source=source), clock=FixedClock(instant=FIXED_INSTANT))

    assert "identity_source" in str(refused.value)


@pytest.mark.parametrize("key", [pytest.param("", id="empty"), pytest.param("  ", id="whitespace")])
def test_a_recorded_resolution_that_names_no_associator_key_is_refused(key: str) -> None:
    """The blank key is deliberately not unique, so a lookup on it is not a lookup.

    `one_package_per_source_key` carries `condition=~Q(associator_key="")`, which
    leaves every package no source claims unconstrained. A blank key would
    therefore match an unbounded number of rows and raise
    `MultipleObjectsReturned` -- an exception no caller of this module is told to
    catch, from a query that should never have been issued.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(associator_key=key), clock=FixedClock(instant=FIXED_INSTANT))

    assert ASSOCIATOR_KEY_FIELD in str(refused.value)


def test_a_naive_resolution_instant_is_refused_by_the_recorder_too() -> None:
    """`CPM-AD-26`, on the second door and for the same reason as the first.

    The consequence is larger here than for a shell: `record_resolution` writes
    `resolved_at` on the package row *and* on every mapping row, so a naive
    instant would record several conclusions at a time none of them was reached.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(), clock=NaiveClock())

    assert "naive resolved_at" in str(refused.value)


@pytest.mark.parametrize(
    "confidence",
    [
        pytest.param("", id="empty"),
        pytest.param("inventory_derived", id="underscored"),
        pytest.param("Verified", id="capitalised"),
        pytest.param("high", id="invented"),
    ],
)
def test_a_confidence_outside_the_prds_three_values_is_refused(confidence: str) -> None:
    """`CPM-AD-4` gates every outward claim on this value, so an unknown one gates nothing.

    Refused here rather than left to the column, because `choices` is enforced by
    model validation and nothing in this product runs `full_clean` -- the value
    would be stored, and the gate would meet a confidence it has no rule for.

    `inventory_derived` is in the parameters on purpose: the PRD spells it with a
    hyphen, and the underscored spelling is what a writer following `CPM-AD-5`'s
    fixed-lowercase rule would reach for.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(confidence=confidence), clock=FixedClock(instant=FIXED_INSTANT))

    assert "confidence" in str(refused.value)


def test_an_outcome_table_missing_a_mapping_kind_is_refused() -> None:
    """Exhaustive on purpose: every default a missing kind could take is a fold.

    `unknown` would silently claim nobody looked, and leaving the stored row
    alone would silently claim the previous resolution's finding still holds.
    `CPM-FR-6` is about not folding states together, and a default is a fold
    nobody wrote down.
    """
    partial = {kind: outcome for kind, outcome in NOTHING_FOUND.items() if kind != MappingKind.FEEDSTOCK.value}

    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(outcomes=partial), clock=FixedClock(instant=FIXED_INSTANT))

    assert MappingKind.FEEDSTOCK.value in str(refused.value)


def test_an_outcome_table_naming_something_that_is_not_a_mapping_kind_is_refused() -> None:
    """The other direction, which a "has every kind" check alone would miss.

    An outcome recorded against `pypi_identity` would be written to a `kind`
    column whose choices do not offer it and would then be invisible to every
    reader that filters by kind -- a row that exists and answers nothing.
    """
    invented = {**NOTHING_FOUND, "pypi_identity": OutcomeState.NOT_FOUND.value}

    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(outcomes=invented), clock=FixedClock(instant=FIXED_INSTANT))

    assert "pypi_identity" in str(refused.value)


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param("", id="empty"),
        pytest.param("ok", id="the-generic-determinate-value"),
        pytest.param("Not Found", id="a-label-rather-than-a-value"),
        pytest.param("resolved", id="a-synonym"),
    ],
)
def test_an_outcome_outside_the_composed_vocabulary_is_refused(outcome: str) -> None:
    """`CPM-AD-5`: every status in this product is drawn from one table.

    `ok` is in the parameters because it is the *generic* determinate value and
    is exactly what a writer reaches for before noticing that this vocabulary
    refines it into `established` -- and it would be stored, because the column's
    `choices` are enforced by no writer here.
    """
    claimed = {**NOTHING_FOUND, MappingKind.SOURCE_REPOSITORY.value: outcome}

    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(outcomes=claimed), clock=FixedClock(instant=FIXED_INSTANT))

    assert MappingKind.SOURCE_REPOSITORY.value in str(refused.value)


@pytest.mark.parametrize(
    ("kind", "supplied"),
    [
        pytest.param(
            MappingKind.SOURCE_REPOSITORY.value,
            {"source_repository_url": "https://example.invalid/numpy"},
            id="source-repository",
        ),
        pytest.param(
            MappingKind.RELEASE_ECOSYSTEM.value,
            {"primary_purl": "pkg:pypi/numpy"},
            id="release-ecosystem",
        ),
        pytest.param(MappingKind.CONDA_ARTIFACT.value, {"conda_purl": "pkg:conda/numpy"}, id="conda-artifact"),
        pytest.param(
            MappingKind.CROSS_ECOSYSTEM.value,
            {"cpes": ("cpe:2.3:a:numpy:numpy:*:*:*:*:*:*:*:*",)},
            id="cross-ecosystem",
        ),
    ],
)
def test_a_value_recorded_beside_an_outcome_that_says_there_is_none_is_refused(
    kind: str,
    supplied: dict[str, object],
) -> None:
    """`CPM-FR-1`: a resolution that cannot establish a mapping records nothing rather than a guess.

    The value would be dropped -- only an `established` mapping is written -- and
    the caller would never learn that half of what it supplied was discarded.
    That is the quiet failure this refusal exists to make loud, and it is
    parametrized over every kind that owns a column so the rule cannot hold for
    one of them and not the rest.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(**supplied), clock=FixedClock(instant=FIXED_INSTANT))

    assert kind in str(refused.value)


def test_feedstocks_supplied_beside_a_non_established_outcome_are_refused() -> None:
    """The same rule for the mapping whose value is rows rather than columns.

    `MAPPED_FIELDS` is empty for the feedstock kind, so the column check cannot
    see this one -- which is precisely why it needs its own case: a rule that
    covered four kinds out of five would be the fold arrived at by omission.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(feedstocks=(A_FEEDSTOCK,)), clock=FixedClock(instant=FIXED_INSTANT))

    assert MappingKind.FEEDSTOCK.value in str(refused.value)


@pytest.mark.parametrize("name", [pytest.param("", id="empty"), pytest.param("   ", id="whitespace")])
def test_a_feedstock_that_names_nothing_is_refused(name: str) -> None:
    """A nameless feedstock is worse than a missing one, because it is counted.

    `package.feedstocks` returns it, so "this package has a feedstock" reads true
    for a row naming nothing -- the claim `CPM-FR-5` forbids making about a
    package whose identity is unresolved. `feedstock_name_is_present` would refuse
    it at the table, but these rows are written in a loop, so that refusal would
    arrive with some rows already written and would name neither the feedstock
    nor the rule.
    """
    resolution = _resolution(
        outcomes=_established(MappingKind.FEEDSTOCK.value),
        feedstocks=(FeedstockMapping(name=name),),
    )

    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=resolution, clock=FixedClock(instant=FIXED_INSTANT))

    assert "names nothing" in str(refused.value)


def test_a_feedstock_name_wider_than_its_column_is_refused_rather_than_truncated() -> None:
    """The local-versus-gate parity gap, on the third column a caller can overflow.

    SQLite stores an over-long value truncated and PostgreSQL refuses it, so an
    unrefused one is a working row on a developer's machine and a failed run in
    the gate (`R-5`).
    """
    resolution = _resolution(
        outcomes=_established(MappingKind.FEEDSTOCK.value),
        feedstocks=(FeedstockMapping(name=_too_long_feedstock_name()),),
    )

    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=resolution, clock=FixedClock(instant=FIXED_INSTANT))

    assert FEEDSTOCK_NAME_FIELD in str(refused.value)
    assert str(FEEDSTOCK_NAME_LENGTH) in str(refused.value)


@pytest.mark.parametrize(
    "name",
    [pytest.param("   ", id="whitespace"), pytest.param("\t\n", id="blank-lines")],
)
def test_a_corrected_name_that_names_nothing_is_refused(name: str) -> None:
    """Correcting a name to nothing is not a correction.

    A blank `canonical_name` is left alone rather than written -- that is how "no
    correction" is spelled, and the empty string is therefore absent from these
    parameters on purpose. Whitespace is not blank, and writing it would be
    refused by `canonical_name_is_present` as an `IntegrityError` naming a
    constraint rather than the input that broke it.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(canonical_name=name), clock=FixedClock(instant=FIXED_INSTANT))

    assert "names nothing" in str(refused.value)


def test_a_corrected_name_wider_than_its_column_is_refused_rather_than_truncated() -> None:
    """The same bound `resolve_package_shell` applies, on the door that corrects the name.

    Correction is the ordinary outcome of a real resolution -- the shell was
    named by whatever the inventory called the package -- so this is the path an
    over-long name actually arrives by rather than a theoretical one.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(
            resolution=_resolution(canonical_name=_too_long_name()),
            clock=FixedClock(instant=FIXED_INSTANT),
        )

    assert CANONICAL_NAME_FIELD in str(refused.value)


@pytest.mark.parametrize("kind", sorted(set(MappingKind.values) - {MappingKind.FEEDSTOCK.value}), ids=str)
def test_a_mapping_established_with_no_value_is_refused(kind: str) -> None:
    """The converse of the rule above, and the half that was missing.

    `established` with every field blank stores exactly what `not_found` stores
    -- nothing -- so the two stop being distinguishable in the columns at the
    moment the row is written. That is the fold `PackageMapping` exists to
    prevent, arrived at from the other direction: a caller that established
    nothing has four sentinels to say so with.

    Parametrized over every kind that owns columns, and the feedstock kind is
    excluded because it is the one exception: `CPM-FR-1` says "zero or more", so
    `established` with no rows is the successful empty result rather than a
    contradiction.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(outcomes=_established(kind)), clock=FixedClock(instant=FIXED_INSTANT))

    assert kind in str(refused.value)
    assert ESTABLISHED in str(refused.value)


def test_a_feedstock_mapping_established_with_no_rows_is_the_one_permitted_emptiness() -> None:
    """The other side of that rule, so it is not a ban on the successful empty result.

    A package that genuinely has no conda-forge recipe is a resolved package
    rather than an unresolved one, and `CPM-FR-6` insists that stays distinct
    from `not_found` and `not_applicable`. A refusal that covered all five kinds
    would have made the distinction unrecordable at the moment the story added
    the column for it.
    """
    resolution = _resolution(outcomes=_established(MappingKind.FEEDSTOCK.value))

    with pytest.raises(RuntimeError, match="Database access not allowed"):
        record_resolution(resolution=resolution, clock=FixedClock(instant=FIXED_INSTANT))


@pytest.mark.parametrize(
    "confidence",
    [
        pytest.param(IdentityConfidence.VERIFIED.value, id="verified"),
        pytest.param(IdentityConfidence.INVENTORY_DERIVED.value, id="inventory-derived"),
    ],
)
def test_a_confidence_above_unmapped_resting_on_nothing_is_refused(confidence: str) -> None:
    """`CPM-AD-4` gates every outward claim on this value, so it cannot rest on none.

    `verified` shows comparisons and recommendations normally and
    `inventory-derived` shows them with a label, so a row carrying either while
    every mapping reads `not_found` is a package the product will speak about on
    the strength of nothing -- the `CPM-SM-C1` failure the whole system exists to
    avoid. `CPM-FR-1` says it from the other side: a resolution that cannot
    establish a mapping records `unmapped`, never a guess.
    """
    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(confidence=confidence), clock=FixedClock(instant=FIXED_INSTANT))

    assert IdentityConfidence.UNMAPPED.value in str(refused.value)


def test_a_resolution_that_established_nothing_may_still_record_unmapped() -> None:
    """The negative control for the rule above, and the ordinary failed resolution.

    `unmapped` is always available and never refused. A rule that had made every
    resolution need a mapping would have left a resolver that looked and found
    nothing with nothing it could record at all -- so the outcome rows saying
    where it looked would never be written either.
    """
    with pytest.raises(RuntimeError, match="Database access not allowed"):
        record_resolution(resolution=_resolution(), clock=FixedClock(instant=FIXED_INSTANT))


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        pytest.param(MappingKind.SOURCE_REPOSITORY.value, "source_repository_url", id="source-repository-url"),
        pytest.param(MappingKind.RELEASE_ECOSYSTEM.value, "primary_purl", id="primary-purl"),
        pytest.param(MappingKind.RELEASE_ECOSYSTEM.value, "primary_type", id="primary-type"),
        pytest.param(MappingKind.CONDA_ARTIFACT.value, "conda_purl", id="conda-purl"),
    ],
)
def test_a_mapping_value_wider_than_its_column_is_refused_rather_than_truncated(kind: str, field: str) -> None:
    """The parity rule the two names already carried, applied to the mappings too.

    SQLite ignores `max_length` and PostgreSQL raises, so an unrefused over-long
    purl is a working row on a developer's machine and a failed run in the gate
    (`R-5`). Applying that to three columns and not to the other four was an
    inconsistency rather than a decision, and this is parametrized over every
    bounded column so a seventh cannot be added without one.
    """
    over_long = "x" * (PACKAGE_FIELD_LENGTHS[field] + 1)

    with pytest.raises(ResolutionError) as refused:
        record_resolution(
            resolution=_resolution(outcomes=_established(kind), **{field: over_long}),
            clock=FixedClock(instant=FIXED_INSTANT),
        )

    assert field in str(refused.value)
    assert str(PACKAGE_FIELD_LENGTHS[field]) in str(refused.value)


@pytest.mark.parametrize("field", sorted(FEEDSTOCK_URL_LENGTHS), ids=str)
def test_a_feedstock_url_wider_than_its_column_is_refused_rather_than_truncated(field: str) -> None:
    """The same rule on the child table's two URL columns.

    Written in a loop, so an unrefused one would reach PostgreSQL with some rows
    already inserted and would name neither the feedstock nor the column.
    """
    over_long = "x" * (FEEDSTOCK_URL_LENGTHS[field] + 1)
    resolution = _resolution(
        outcomes=_established(MappingKind.FEEDSTOCK.value),
        feedstocks=(FeedstockMapping(name="numpy", **{field: over_long}),),
    )

    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=resolution, clock=FixedClock(instant=FIXED_INSTANT))

    assert field in str(refused.value)


@pytest.mark.parametrize("collection", ["alternative_purls", "cpes"], ids=str)
@pytest.mark.parametrize(
    "element",
    [pytest.param(None, id="none"), pytest.param(7, id="a-number"), pytest.param("  ", id="whitespace")],
)
def test_a_purl_list_holding_something_that_is_not_an_identifier_is_refused(
    collection: str,
    element: object,
) -> None:
    """A `JSONField` validates shape nowhere, so the writer has to.

    `alternative_purls` and `cpes` are documented as lists of identifiers and
    typed as tuples of `str`, and neither claim is enforced at runtime by
    anything -- a `None`, a number or a blank string is stored without complaint
    and is read back by an advisory matcher expecting a purl or a CPE name
    (`CPM-FR-1`). `CPM-IDENTITY-S01`'s review recorded this as belonging with the
    writer that produces them, in this `_require_*` shape.
    """
    resolution = _resolution(
        outcomes=_established(MappingKind.CROSS_ECOSYSTEM.value),
        **{collection: ("pkg:pypi/numpy", element)},
    )

    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=resolution, clock=FixedClock(instant=FIXED_INSTANT))

    assert collection in str(refused.value)


def test_two_feedstocks_sharing_a_name_are_refused_rather_than_merged() -> None:
    """The write is a `get_or_create` per name, so a duplicate would be last-wins.

    The second entry's URLs would overwrite the first's,
    `one_feedstock_name_per_package` would keep exactly one row, and the resolver
    would never learn that half of what it supplied was discarded. A resolver
    with two things to say about one feedstock has a defect rather than a
    preference.
    """
    resolution = _resolution(
        outcomes=_established(MappingKind.FEEDSTOCK.value),
        feedstocks=(
            FeedstockMapping(name="numpy", url="https://example.invalid/one"),
            FeedstockMapping(name=" numpy ", url="https://example.invalid/two"),
        ),
    )

    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=resolution, clock=FixedClock(instant=FIXED_INSTANT))

    assert "numpy" in str(refused.value)


def test_a_pair_matching_several_packages_is_refused_rather_than_escaping(monkeypatch: pytest.MonkeyPatch) -> None:
    """`MultipleObjectsReturned` is translated, not allowed out.

    Unreachable through a schema carrying `one_package_per_source_key` and
    entirely reachable on one written before it -- a database migrated from an
    earlier release is exactly where the duplicate shells this story exists to
    prevent already are. So the branch cannot be reached by writing rows: the
    constraint refuses them, which is the point.

    The manager's `get` is substituted for that reason and no other. What is
    being measured is the translation from Django's exception into the one this
    module's contract names -- a caller told to catch `ResolutionError` would
    otherwise meet an exception from `django.core.exceptions` with no mention of
    resolution in it. Substituting the *database* would be mocking
    infrastructure; substituting the one call whose failure mode the schema makes
    unreachable is how the failure mode gets a test at all.
    """

    def _several(**_lookup: object) -> Package:
        raise Package.MultipleObjectsReturned

    monkeypatch.setattr(Package.objects, "get", _several)

    with pytest.raises(ResolutionError) as refused:
        record_resolution(resolution=_resolution(), clock=FixedClock(instant=FIXED_INSTANT))

    assert "one_package_per_source_key" in str(refused.value)
    assert A_KEY in str(refused.value)


def test_a_recordable_resolution_reaches_the_lookup_and_not_a_refusal() -> None:
    """The negative control, and the reason every case above is a unit test.

    A well-formed resolution passes every check and then asks the database which
    package the pair names -- which pytest-django refuses in a case carrying no
    `django_db` mark. So this asserts two things at once: that the validation
    above is not simply rejecting everything, and that the lookup really is the
    first thing to touch a table.
    """
    resolution = _resolution(
        confidence=IdentityConfidence.VERIFIED.value,
        canonical_name=A_NAME,
        source_repository_url="https://example.invalid/numpy",
        outcomes=_established(MappingKind.SOURCE_REPOSITORY.value),
    )

    with pytest.raises(RuntimeError, match="Database access not allowed"):
        record_resolution(resolution=resolution, clock=FixedClock(instant=FIXED_INSTANT))
