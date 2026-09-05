"""What a recorded resolution does to a row it found, against real tables.

`tests/unit/django_apps/test_identity_services.py` holds what
`record_resolution` refuses before it looks anything up -- every one of those
cases reaches its refusal without a database, which is the property being
asserted as much as the message is. Everything here needs a row to have been
found, a column to have been written, or a constraint to have refused, and none
of the three is decidable from `_meta`.

**The three rows this module is really about are the ones a value column cannot
hold.** `CPM-FR-6` says a check that does not apply is never folded into clean or
unknown, and `CPM-FR-1` applies that to mappings: a package whose type makes a
PyPI identity inapplicable, one whose source repository was looked for and not
found, and one that genuinely has zero feedstocks are three different facts that
a blank `source_repository_url` and an empty `package.feedstocks` cannot tell
apart. Each has a case below, and each asserts the *outcome row*, because that is
where the distinction now lives.

**The regression is the whole point of the story and it is at the bottom.**
`CPM-IDENTITY-S06`'s review recorded that resolution correcting a canonical name
would make the next inventory sweep create a second shell. `CPM-IDENTITY-S07`
moved the lookup onto `(identity_source, associator_key)`; this story adds the
uniqueness constraint behind that pair and the invariant that resolution never
writes either field. `test_a_corrected_package_still_receives_the_next_sweeps_snapshot`
composes all three: ingest, resolve to a new name, ingest the same source record
again.

**Refusals are asserted inside `transaction.atomic()`,** for the reason
`tests/integration/django_apps/test_identity_models.py` gives at length: a
statement raising `IntegrityError` marks pytest-django's per-test transaction
broken, so an unwrapped `pytest.raises` passes and then fails the teardown of a
case that had nothing wrong with it.

No `connection.vendor` branch and no assertion on a constraint's message. The
suite runs on the sqlite fallback and `pixi run gate-postgres` runs the same
cases against `postgres:17`; `IntegrityError` is what both raise, and it is the
whole claim.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction

from conda_package_supply_chain_monitor.collectors.models import InventorySnapshot
from conda_package_supply_chain_monitor.collectors.tasks import COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.tasks import INVENTORY_SOURCE
from conda_package_supply_chain_monitor.collectors.tasks import PACKAGE_NAME
from conda_package_supply_chain_monitor.collectors.tasks import SOURCE_PACKAGE_KEY
from conda_package_supply_chain_monitor.collectors.tasks import InventoryIngestionCollector
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.identity.models import ESTABLISHED
from conda_package_supply_chain_monitor.identity.models import Feedstock
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import MappingKind
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.models import PackageMapping
from conda_package_supply_chain_monitor.identity.services import FeedstockMapping
from conda_package_supply_chain_monitor.identity.services import Resolution
from conda_package_supply_chain_monitor.identity.services import ResolutionError
from conda_package_supply_chain_monitor.identity.services import record_resolution
from conda_package_supply_chain_monitor.identity.services import resolve_package_shell
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.collectors import FixedLimiter
from tests.collectors import RecordedTransport
from tests.collectors import cleared_cache
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

#: The source key the inventory files this package under, and the name it calls
#: it. Two different strings, which is what `CPM-IDENTITY-S07` separated and what
#: makes a service that wrote either into the wrong column visible.
A_KEY: Final[str] = "internal/numpy"
A_NAME: Final[str] = "numpy"

#: What a real resolution corrects the name to. The shell was named by whatever
#: the inventory called the package, so correcting it is the ordinary outcome
#: rather than a rare one -- which is why the duplicate-shell trap fires for
#: every package this story resolves rather than for a few.
A_CORRECTED_NAME: Final[str] = "numpy-corrected"

#: What resolution names as having established an identity, and deliberately not
#: the ingestion collector's own name: `record_resolution` finds a package by the
#: pair the *creator* wrote, so the cases below use `COLLECTOR_NAME` where they
#: resolve a shell ingestion made, and this where they make the shell themselves.
A_RESOLVER: Final[str] = "pypi-associator"

#: The mappings a fully resolved package carries. Real-looking values, because a
#: purl that is not shaped like a purl would let a column truncation or a
#: mis-assignment read as a pass.
A_REPOSITORY_URL: Final[str] = "https://example.invalid/numpy/numpy"
A_PRIMARY_PURL: Final[str] = "pkg:pypi/numpy@2.4.0"
A_PRIMARY_TYPE: Final[str] = "pypi"
A_CONDA_PURL: Final[str] = "pkg:conda/numpy@2.4.0"
AN_ALTERNATIVE_PURL: Final[str] = "pkg:github/numpy/numpy"
A_CPE: Final[str] = "cpe:2.3:a:numpy:numpy:*:*:*:*:*:*:*:*"

#: The feedstock a resolution establishes, and its URL.
A_FEEDSTOCK_NAME: Final[str] = "numpy"
A_FEEDSTOCK_URL: Final[str] = "https://example.invalid/conda-forge/numpy-feedstock"

#: A second feedstock, for the case that proves a later resolution does not prune
#: what an earlier one recorded. `CPM-FR-1`'s "zero or more" is real: `numpy` and
#: `numpy-base` are two feedstocks one package legitimately maps to.
ANOTHER_FEEDSTOCK_NAME: Final[str] = "numpy-base"

#: The counts a well-formed inventory record carries. Distinct values, so a case
#: asserting both reached the row asserts two things rather than one twice.
A_COMPONENT_COUNT: Final[int] = 3
A_LOB_COUNT: Final[int] = 2

#: How many packages a case that writes two of them expects to find, and how many
#: snapshots the ingest-resolve-ingest regression expects. Named because a bare
#: number in an assertion says nothing about which two.
TWO_ROWS: Final[int] = 2

#: What the caller that abandons its transaction raises, so the case matches on
#: the failure it arranged rather than on any `RuntimeError` at all -- pytest-django
#: raises one of its own for unpermitted database access.
CALLER_ABANDONED: Final[str] = "the caller changed its mind"


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    """Leave no rate-limit counter behind, in either direction.

    Autouse because the cases that drive a real ingestion sweep go through the
    collector base's allowance, and the cache is process-wide while the ledger is
    not. The body lives in `tests/collectors.py` because every module that
    touches the cache needs the identical guard.

    Yields:
        Nothing; the fixture is entirely its two side effects.

    """
    with cleared_cache():
        yield


def _outcomes(*established: str) -> dict[str, str]:
    """Return an outcome table answering `established` for the named kinds.

    Args:
        *established: The mapping kinds this resolution established.

    Returns:
        Every kind answered exactly once, the named ones `established` and the
        rest `not_found` -- exhaustive, because `record_resolution` refuses a
        table that leaves a kind out.

    """
    return {kind: (ESTABLISHED if kind in established else OutcomeState.NOT_FOUND.value) for kind in MappingKind.values}


def _shell(*, key: str = A_KEY, name: str = A_NAME, source: str = A_RESOLVER) -> Package:
    """Create the package row a resolution is later recorded against.

    Through `resolve_package_shell` rather than `Package.objects.create`, because
    that is the only thing in this product that creates one (`CPM-AD-25`) and a
    row built any other way could carry a pair no real shell would have.

    Args:
        key: The source package key, which becomes `associator_key`.
        name: What the source calls the package, which becomes `canonical_name`.
        source: What created the shell, which becomes `identity_source`.

    Returns:
        The shell, at `unmapped` confidence with no mapping of any kind.

    """
    return resolve_package_shell(
        source_package_key=key,
        package_name=name,
        identity_source=source,
        clock=FixedClock(instant=FIXED_INSTANT),
    )


def _record(key: str) -> dict[str, Any]:
    """Return one well-formed inventory record.

    Written out here rather than imported from
    `tests/integration/django_apps/test_inventory_ingestion.py`: importing a
    private helper across two collected modules ties their collection together,
    which `tests/conftest.py` argues against, and the shared home for a fixture
    two modules need is `tests/collectors.py` -- which a single-caller record
    builder does not yet earn.

    Args:
        key: The source package key the record names.

    Returns:
        The record document an adapter would yield.

    """
    return {
        SOURCE_PACKAGE_KEY: key,
        PACKAGE_NAME: key.rsplit("/", 1)[-1],
        "internal_component_count": A_COMPONENT_COUNT,
        "internal_lob_count": A_LOB_COUNT,
    }


def _ingest(*keys: str, at: datetime = FIXED_INSTANT) -> RunState:
    """Run one real ingestion sweep over the named packages.

    Args:
        *keys: The source package keys the document names.
        at: The instant the run's clock is stopped at, so two sweeps can be
            placed apart rather than run twice against one clock.

    Returns:
        How the run finished. Asserted rather than ignored: the regression below
        is only meaningful if the second sweep *succeeded* -- a `partial` run
        would mean the record failed, which is the failure the story is about
        wearing the wrong name.

    """
    adapter = RecordedTransport(
        payload=recorded_payload(source=INVENTORY_SOURCE, body=json.dumps([_record(key) for key in keys])),
    )
    collector = InventoryIngestionCollector(
        clock=FixedClock(instant=at),
        transport=adapter,
        limiter=FixedLimiter(permitted=True),
    )
    return collector.sweep().state


def _resolve_then_abandon() -> None:
    """Record a full resolution inside one transaction, then abandon it.

    A helper rather than the body of a `pytest.raises` block: the block would
    hold a call and a raise, and a multi-statement one hides which statement the
    exception came out of.

    Raises:
        RuntimeError: Always, after the resolution has been written. That is the
            point -- the caller owning the boundary means everything written here
            goes back when the caller's transaction does.

    """
    with transaction.atomic():
        record_resolution(
            resolution=Resolution(
                identity_source=A_RESOLVER,
                associator_key=A_KEY,
                confidence=IdentityConfidence.VERIFIED.value,
                outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value, MappingKind.FEEDSTOCK.value),
                canonical_name=A_CORRECTED_NAME,
                source_repository_url=A_REPOSITORY_URL,
                feedstocks=(FeedstockMapping(name=A_FEEDSTOCK_NAME),),
            ),
            clock=FixedClock(instant=LATER_INSTANT),
        )
        raise RuntimeError(CALLER_ABANDONED)


def _outcome_of(package: Package, kind: str) -> str:
    """Return the stored outcome for one of a package's mappings.

    Read back from the database rather than off an instance, because the point of
    every case using it is what the column holds.

    Args:
        package: The package the mapping is about.
        kind: The mapping kind.

    Returns:
        The stored outcome value.

    """
    return str(PackageMapping.objects.values_list("outcome", flat=True).get(package=package, kind=kind))


# ---------------------------------------------------------------------------
# AC #1: what a recorded resolution writes.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_established_resolution_writes_its_mappings_provenance_and_confidence() -> None:
    """AC #1, and the matrix's first row.

    Every mapping `CPM-FR-1` lists, established at once: the source repository,
    the release ecosystem identity, the conda artifact, one feedstock and the
    cross-ecosystem identifiers. Read back from the database rather than asserted
    on the instance the service returned, because a value assigned and left out
    of `update_fields` would satisfy the second and none of the first.

    `resolved_at` is asserted to be the injected clock's instant rather than
    merely "not the old one" -- `CPM-AD-26` exists so that a claim about *which*
    instant was recorded is available at all.
    """
    shell = _shell()

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(*MappingKind.values),
            canonical_name=A_CORRECTED_NAME,
            source_repository_url=A_REPOSITORY_URL,
            primary_purl=A_PRIMARY_PURL,
            primary_type=A_PRIMARY_TYPE,
            conda_purl=A_CONDA_PURL,
            alternative_purls=(AN_ALTERNATIVE_PURL,),
            cpes=(A_CPE,),
            feedstocks=(FeedstockMapping(name=A_FEEDSTOCK_NAME, url=A_FEEDSTOCK_URL),),
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert package.canonical_name == A_CORRECTED_NAME
    assert package.source_repository_url == A_REPOSITORY_URL
    assert package.primary_purl == A_PRIMARY_PURL
    assert package.primary_type == A_PRIMARY_TYPE
    assert package.conda_purl == A_CONDA_PURL
    assert package.alternative_purls == [AN_ALTERNATIVE_PURL]
    assert package.cpes == [A_CPE]
    assert package.identity_source == A_RESOLVER
    assert package.associator_key == A_KEY
    assert package.confidence == IdentityConfidence.VERIFIED
    assert package.resolved_at == LATER_INSTANT
    assert [(feedstock.name, feedstock.url) for feedstock in package.feedstocks.all()] == [
        (A_FEEDSTOCK_NAME, A_FEEDSTOCK_URL),
    ]
    assert dict(PackageMapping.objects.filter(package=package).values_list("kind", "outcome")) == dict.fromkeys(
        MappingKind.values,
        ESTABLISHED,
    )
    assert set(PackageMapping.objects.filter(package=package).values_list("resolved_at", flat=True)) == {LATER_INSTANT}


@pytest.mark.django_db
def test_a_mapping_that_could_not_be_established_leaves_the_value_blank_and_says_why() -> None:
    """The matrix's second row: `CPM-FR-1` records nothing rather than a guess.

    The distinction the outcome row buys is the one asserted last: the column is
    blank *and* the reason is `not_found`, which a reader of the column alone
    could not have told from "nobody has looked". The confidence stays `unmapped`
    because that is what this resolution claimed -- it established nothing, so it
    asserts nothing.
    """
    shell = _shell()

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.UNMAPPED.value,
            outcomes=_outcomes(),
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert package.source_repository_url == ""
    assert package.confidence == IdentityConfidence.UNMAPPED
    assert _outcome_of(package, MappingKind.SOURCE_REPOSITORY.value) == OutcomeState.NOT_FOUND.value


@pytest.mark.django_db
def test_a_mapping_that_does_not_apply_is_neither_not_found_nor_an_empty_result() -> None:
    """The matrix's third row, and the reason `CPM-FR-6` exists.

    A package whose type puts a PyPI identity out of scope -- the non-Python
    conda artifacts the later phase is about -- has no release ecosystem
    identity, and that is not the same fact as "we looked on PyPI and it is not
    there". Both leave `primary_purl` blank, so the column can never carry the
    difference and the outcome row is the only thing that does.

    Asserted against its two neighbours by value rather than only against itself,
    because "it stored what I passed" is satisfied by a column that stores
    anything.

    The source repository is established alongside it, and not as scenery: an
    `inventory-derived` confidence has to rest on something (`CPM-AD-4`), and the
    package this row describes is exactly the realistic one -- a conda artifact
    with a repository and no PyPI identity to have.
    """
    shell = _shell()

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.INVENTORY_DERIVED.value,
            outcomes={
                **_outcomes(MappingKind.SOURCE_REPOSITORY.value),
                MappingKind.RELEASE_ECOSYSTEM.value: OutcomeState.NOT_APPLICABLE.value,
            },
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    stored = _outcome_of(package, MappingKind.RELEASE_ECOSYSTEM.value)
    assert stored == OutcomeState.NOT_APPLICABLE.value
    assert stored != OutcomeState.NOT_FOUND.value
    assert stored != ESTABLISHED
    assert package.primary_purl == ""


@pytest.mark.django_db
def test_a_successful_empty_result_is_established_with_no_feedstock_rows() -> None:
    """The matrix's fourth row: zero feedstocks is an answer, not an absence of one.

    `CPM-FR-1` says "zero or more", so a package that genuinely has no
    conda-forge recipe is a resolved package rather than an unresolved one --
    and `CPM-FR-5` forbids reporting an unmapped package as "lacking a
    feedstock", which is precisely the claim this state makes legitimately.

    The two halves are the assertion: `established` beside an empty queryset. The
    empty queryset alone is what `not_found` and `not_applicable` also produce.

    **The `verified` confidence rests on the source repository, not on the empty
    feedstock result**, and that is not incidental to the case. An empty
    establishment carries no value, so it earns no confidence on its own
    (`CPM-AD-4`) -- "this package has no conda-forge recipe and we know nothing
    else about it" is an `unmapped` package with one thing recorded about it. The
    feedstock kind is nonetheless the only one permitted to be `established` and
    empty, which is what this case is really pinning.
    """
    shell = _shell()

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.FEEDSTOCK.value, MappingKind.SOURCE_REPOSITORY.value),
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert _outcome_of(package, MappingKind.FEEDSTOCK.value) == ESTABLISHED
    assert list(package.feedstocks.all()) == []
    assert package.confidence == IdentityConfidence.VERIFIED


@pytest.mark.django_db
def test_a_second_resolution_replaces_the_outcome_rather_than_appending_one() -> None:
    """One answer per question, which is what `one_outcome_per_package_mapping` buys.

    A resolution that finds what an earlier one missed must leave one row saying
    `established`, not two rows disagreeing. `PackageMapping` is identity rather
    than evidence -- it carries no `observed_at` -- so a second row would leave
    "what do we conclude about this package's source repository" with two answers
    and no way to order them.
    """
    shell = _shell()
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.UNMAPPED.value,
            outcomes=_outcomes(),
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.INVENTORY_DERIVED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert PackageMapping.objects.filter(package=package).count() == len(MappingKind.values)
    assert _outcome_of(package, MappingKind.SOURCE_REPOSITORY.value) == ESTABLISHED
    assert package.source_repository_url == A_REPOSITORY_URL


@pytest.mark.django_db
def test_re_resolving_a_feedstock_fills_in_its_urls_without_duplicating_the_mapping() -> None:
    """The ordinary second resolution: the same feedstock, now with a URL.

    `one_feedstock_name_per_package` would refuse a second row, so a recorder
    that blindly created would turn the commonest re-resolution there is into an
    `IntegrityError`. The mapping is matched on `(package, name)` and its URLs
    are filled in, which is also why the *first* resolution is allowed to record
    a feedstock known only by name: blank means missing, and missing is
    correctable.

    Additive by design, and this is where that shows: a feedstock a later
    resolution stops naming stays where it is. Removing one says an earlier
    conclusion was *wrong* rather than that a newer one is available, and
    `CPM-AD-14` puts that on `CPM-IDENTITY-S05`'s audited override path.
    """
    shell = _shell()
    established = _outcomes(MappingKind.FEEDSTOCK.value)
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.INVENTORY_DERIVED.value,
            outcomes=established,
            feedstocks=(FeedstockMapping(name=A_FEEDSTOCK_NAME),),
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=established,
            feedstocks=(FeedstockMapping(name=A_FEEDSTOCK_NAME, url=A_FEEDSTOCK_URL),),
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert [(feedstock.name, feedstock.url) for feedstock in package.feedstocks.all()] == [
        (A_FEEDSTOCK_NAME, A_FEEDSTOCK_URL),
    ]


@pytest.mark.django_db
def test_a_feedstock_a_later_resolution_stops_naming_is_left_where_it_is() -> None:
    """The additive rule, pinned rather than argued.

    Every other feedstock case names one feedstock, so an implementation that
    pruned the rows a resolution did not name -- in a loop, which the
    mutation-path audit's source scan cannot see, unlike the queryset spelling --
    passes all of them. This is the case that fails: two resolutions naming two
    different feedstocks leave two rows.

    Removing a mapping says an earlier conclusion was *wrong* rather than that a
    newer one is available, and `CPM-AD-14` puts that on `CPM-IDENTITY-S05`'s
    audited override path, which records who removed it and why. A recorder that
    pruned silently would be that path without the audit.
    """
    shell = _shell()
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.INVENTORY_DERIVED.value,
            outcomes=_outcomes(MappingKind.FEEDSTOCK.value),
            feedstocks=(FeedstockMapping(name=A_FEEDSTOCK_NAME, url=A_FEEDSTOCK_URL),),
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.FEEDSTOCK.value),
            feedstocks=(FeedstockMapping(name=ANOTHER_FEEDSTOCK_NAME),),
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert sorted(feedstock.name for feedstock in package.feedstocks.all()) == sorted(
        (A_FEEDSTOCK_NAME, ANOTHER_FEEDSTOCK_NAME),
    )
    assert package.feedstocks.get(name=A_FEEDSTOCK_NAME).url == A_FEEDSTOCK_URL


@pytest.mark.django_db
def test_a_later_not_found_does_not_blank_a_value_an_earlier_resolution_established() -> None:
    """The write guard, pinned from the side that a passing suite could not see.

    `_write_identity` writes a kind's columns only when *this* resolution
    answered that kind `established`. Remove the guard and every mapped field is
    written unconditionally, which blanks a source repository an earlier
    resolution established while the outcome row beside it says `not_found` --
    the "records a guess" state `CPM-FR-1` forbids, arrived at by erasure rather
    than by invention. No case that resolves a package once can tell the two
    implementations apart, which is why this one resolves it twice.

    The second resolution is at *equal* confidence, so nothing is being held back
    by the verified guard: the value survives because of the write rule alone.
    """
    shell = _shell()
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )

    recorded = record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.CONDA_ARTIFACT.value),
            conda_purl=A_CONDA_PURL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert recorded.downgrade_refused is False
    assert package.source_repository_url == A_REPOSITORY_URL
    assert _outcome_of(package, MappingKind.SOURCE_REPOSITORY.value) == OutcomeState.NOT_FOUND.value
    assert package.conda_purl == A_CONDA_PURL


@pytest.mark.django_db
def test_a_second_resolution_advances_every_mapping_row_it_rewrote() -> None:
    """`PackageMapping.resolved_at` is when the mapping was last looked at.

    Dropping the assignment and narrowing `update_fields` to `["outcome"]` leaves
    every row carrying the instant of the resolution that *created* it while its
    outcome reflects a later one -- so "when did we last check this package's
    feedstocks" answers with a date that has nothing to do with the answer beside
    it. Nothing else in the suite reads these instants, so nothing else fails.
    """
    shell = _shell()
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.UNMAPPED.value,
            outcomes=_outcomes(),
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )
    assert set(PackageMapping.objects.filter(package=shell).values_list("resolved_at", flat=True)) == {FIXED_INSTANT}

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    assert set(PackageMapping.objects.filter(package=shell).values_list("resolved_at", flat=True)) == {LATER_INSTANT}
    assert PackageMapping.objects.filter(package=shell).count() == len(MappingKind.values)


@pytest.mark.django_db
def test_a_resolution_that_changed_nothing_leaves_the_package_row_alone() -> None:
    """`Package.resolved_at` is when the identity changed, not when a resolver looked.

    A resolver that runs daily and finds nothing would otherwise stamp the row
    every day, and `CPM-IDENTITY-S04`'s review queue -- which exists to surface
    exactly these packages -- would read every one of them as freshly resolved.
    When somebody last *looked* is on the mapping rows, and they do advance,
    which is the pair of assertions here.
    """
    shell = _shell()
    unresolved = Resolution(
        identity_source=A_RESOLVER,
        associator_key=A_KEY,
        confidence=IdentityConfidence.UNMAPPED.value,
        outcomes=_outcomes(),
    )
    record_resolution(resolution=unresolved, clock=FixedClock(instant=FIXED_INSTANT))

    record_resolution(resolution=unresolved, clock=FixedClock(instant=LATER_INSTANT))

    package = Package.objects.get(pk=shell.pk)
    assert package.resolved_at == FIXED_INSTANT
    assert set(PackageMapping.objects.filter(package=package).values_list("resolved_at", flat=True)) == {LATER_INSTANT}


@pytest.mark.django_db
def test_a_resolution_leaves_the_display_name_alone() -> None:
    """`Resolution` carries no `display_name`, and this is what that means for the row.

    It is what a human is shown rather than a mapping `CPM-FR-1` asks a resolver
    to establish, so the one path that sets it is `CPM-IDENTITY-S05`'s audited
    override. Asserted rather than left to the absence of a field, because a
    field added to `Resolution` later would make the claim false without failing
    anything else.
    """
    shell = _shell()
    # Set the way `CPM-IDENTITY-S05`'s override will: this door has no parameter
    # for it, so the value has to arrive from outside for the case to mean
    # anything. Written on the instance rather than through the manager, so the
    # column this case is about is the only one touched.
    shell.display_name = "NumPy"
    shell.save(update_fields=["display_name"])

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
            canonical_name=A_CORRECTED_NAME,
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert package.display_name == "NumPy"
    assert package.canonical_name == A_CORRECTED_NAME


@pytest.mark.django_db
def test_deleting_a_package_takes_its_mappings_with_it() -> None:
    """`CASCADE`, proved by a database rather than asserted from `_meta`.

    The same objection this module's docstring raises about unique constraints: a
    relation declared `CASCADE` and never migrated satisfies every introspection
    assertion, and the residue would appear as orphaned outcome rows describing a
    package that is gone -- rows every later join would silently carry.

    Nothing in this product deletes a package (`CPM-AD-25` records absence as an
    observation), which is exactly why the behaviour is worth pinning: it is
    reachable only by a path nobody exercises, so it is where a wrong
    `on_delete` would sit undetected.
    """
    shell = _shell()
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.FEEDSTOCK.value),
            feedstocks=(FeedstockMapping(name=A_FEEDSTOCK_NAME),),
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )
    assert PackageMapping.objects.count() == len(MappingKind.values)

    shell.delete()

    assert PackageMapping.objects.count() == 0
    assert Feedstock.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_the_whole_resolution_rolls_back_with_the_callers_transaction() -> None:
    """`CPM-AD-23`: the caller owns the boundary, and the module's contract rests on it.

    `record_resolution` opens no transaction of its own, exactly as
    `resolve_package_shell` does not -- so a caller that wraps a package's
    resolution and the evidence beside it in one `atomic()` gets both or neither.
    The module says so in prose; nothing proved it, and a `transaction.atomic()`
    added inside the service would satisfy every other case here while quietly
    committing the identity write ahead of whatever the caller does next.

    `transaction=True` is what makes the rollback real: the ordinary `django_db`
    mark already wraps each case in a transaction, so an inner block would roll
    back to a savepoint and prove nothing about a commit boundary.
    """
    shell = _shell()

    with pytest.raises(RuntimeError, match=CALLER_ABANDONED):
        _resolve_then_abandon()

    package = Package.objects.get(pk=shell.pk)
    assert package.canonical_name == A_NAME
    assert package.source_repository_url == ""
    assert package.confidence == IdentityConfidence.UNMAPPED
    assert PackageMapping.objects.count() == 0
    assert Feedstock.objects.count() == 0


# ---------------------------------------------------------------------------
# AC #2: a verified identity is never lowered.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_verified_identity_holds_its_confidence_and_its_name_against_a_lower_claim() -> None:
    """AC #2 and `CPM-FR-2`: a resolution never overwrites `verified` with a lower one.

    What is protected is stated narrowly, because the rule is narrow: the
    *confidence*, and the canonical name that confidence is a statement about.
    Rewriting either from a lower-confidence resolver is the downgrade
    `CPM-FR-2` and `CPM-AD-14` forbid, and correcting them anyway is
    `CPM-IDENTITY-S05`'s audited override.

    The mappings the package already held are unchanged too -- but by the rule
    that a mapping is written only when *this* resolution established it, not by
    the holding. The case below is what proves the findings still land.
    """
    shell = _shell()
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )

    recorded = record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.INVENTORY_DERIVED.value,
            outcomes=_outcomes(MappingKind.CONDA_ARTIFACT.value),
            canonical_name=A_CORRECTED_NAME,
            conda_purl=A_CONDA_PURL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert recorded.downgrade_refused is True
    assert package.confidence == IdentityConfidence.VERIFIED
    assert package.canonical_name == A_NAME
    assert package.source_repository_url == A_REPOSITORY_URL


@pytest.mark.django_db
def test_a_lower_confidence_resolution_against_a_verified_package_still_records_its_findings() -> None:
    """`CPM-FR-2` protects the confidence, and nothing else -- so the findings land.

    This is the half that matters operationally. Every `CPM-EP-CURRENCY`
    collector will call this door, most of them at `inventory-derived`, and a
    door that discarded the whole resolution would mean that the moment a human
    verifies a package **no later collector can ever record a newly discovered
    feedstock or purl for it**. A verified identity would become a frozen one.

    So the conda purl this resolution established is written, its outcome row
    reads `established`, and only the confidence claim and the corrected name are
    held back. `downgrade_refused` is how a caller learns which of the two
    happened, since the call succeeded either way.
    """
    shell = _shell()
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )

    recorded = record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.INVENTORY_DERIVED.value,
            outcomes=_outcomes(MappingKind.CONDA_ARTIFACT.value, MappingKind.FEEDSTOCK.value),
            conda_purl=A_CONDA_PURL,
            feedstocks=(FeedstockMapping(name=A_FEEDSTOCK_NAME, url=A_FEEDSTOCK_URL),),
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert recorded.downgrade_refused is True
    assert package.conda_purl == A_CONDA_PURL
    assert [feedstock.name for feedstock in package.feedstocks.all()] == [A_FEEDSTOCK_NAME]
    assert _outcome_of(package, MappingKind.CONDA_ARTIFACT.value) == ESTABLISHED
    assert _outcome_of(package, MappingKind.FEEDSTOCK.value) == ESTABLISHED
    assert package.confidence == IdentityConfidence.VERIFIED
    assert package.resolved_at == LATER_INSTANT


@pytest.mark.django_db
def test_a_verified_identity_accepts_an_equally_confident_resolution() -> None:
    """The other side of the same rule, so it is not a ban on resolving a verified package.

    A re-resolution that is itself `verified` is how a mapping is corrected
    without a human: the claim is not lower, so nothing is being downgraded, and
    `downgrade_refused` says so. An implementation that refused every write to a
    `verified` row would pass the case above and freeze the product's best-known
    identities permanently.
    """
    shell = _shell()
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.CONDA_ARTIFACT.value),
            conda_purl=A_CONDA_PURL,
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )

    recorded = record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value, MappingKind.FEEDSTOCK.value),
            source_repository_url=A_REPOSITORY_URL,
            feedstocks=(FeedstockMapping(name=A_FEEDSTOCK_NAME, url=A_FEEDSTOCK_URL),),
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert recorded.downgrade_refused is False
    assert package.confidence == IdentityConfidence.VERIFIED
    assert package.source_repository_url == A_REPOSITORY_URL
    assert package.resolved_at == LATER_INSTANT
    assert [feedstock.name for feedstock in package.feedstocks.all()] == [A_FEEDSTOCK_NAME]


@pytest.mark.django_db
def test_an_inventory_derived_identity_may_fall_back_to_unmapped() -> None:
    """Only `verified` is protected, and that narrowness is the decision.

    `CPM-FR-2` names one value: "a resolution never overwrites a `verified`
    confidence with a lower one". `inventory-derived` is not that value, and the
    fall to `unmapped` has to be reachable -- a re-resolution that finds the purl
    it once derived is gone must be able to say so, after which `CPM-AD-4`'s gate
    correctly stops the product claiming anything about the package. Freezing
    every confidence would make an identity that has quietly become wrong
    unfixable by anything but a human.

    Pinned rather than left implicit, because "never lowered" is easy to widen
    from one value to all three by somebody reading the rule's name instead of
    its text.
    """
    shell = _shell()
    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.INVENTORY_DERIVED.value,
            outcomes=_outcomes(MappingKind.RELEASE_ECOSYSTEM.value),
            primary_purl=A_PRIMARY_PURL,
            primary_type=A_PRIMARY_TYPE,
        ),
        clock=FixedClock(instant=FIXED_INSTANT),
    )

    recorded = record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.UNMAPPED.value,
            outcomes=_outcomes(),
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    package = Package.objects.get(pk=shell.pk)
    assert recorded.downgrade_refused is False
    assert package.confidence == IdentityConfidence.UNMAPPED
    assert package.resolved_at == LATER_INSTANT
    assert _outcome_of(package, MappingKind.RELEASE_ECOSYSTEM.value) == OutcomeState.NOT_FOUND.value
    assert package.primary_purl == A_PRIMARY_PURL, "the value is not blanked; only the claim about it is withdrawn"


# ---------------------------------------------------------------------------
# AC #3: the join key is never rewritten.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_correcting_the_canonical_name_leaves_the_join_key_byte_identical() -> None:
    """AC #3, asserted directly, because this is the invariant the trap turns on.

    Not "the lookup still works" -- that is the regression below, and it would
    keep passing for a while if the pair were rewritten to a value the source
    happened to send next. This is the narrower claim: the two columns hold the
    same bytes after the write as before it, so `update_fields` cannot have
    included either.
    """
    shell = _shell()
    before = Package.objects.values("identity_source", "associator_key").get(pk=shell.pk)

    record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
            canonical_name=A_CORRECTED_NAME,
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    after = Package.objects.values("identity_source", "associator_key").get(pk=shell.pk)
    assert after == before
    assert after == {"identity_source": A_RESOLVER, "associator_key": A_KEY}
    assert Package.objects.get(pk=shell.pk).canonical_name == A_CORRECTED_NAME


@pytest.mark.django_db
def test_a_pair_that_names_no_package_is_refused_rather_than_created() -> None:
    """The matrix's "resolution of an unknown package": creation is the other door's.

    A recorder that quietly created what it could not find would give the product
    a second creator of package rows, which is exactly what `CPM-AD-14` and
    `CPM-AD-25` exist to forbid -- and the row it created would be a package the
    inventory never named, at whatever confidence the resolver claimed.
    """
    _shell()

    with pytest.raises(ResolutionError) as refused:
        record_resolution(
            resolution=Resolution(
                identity_source=A_RESOLVER,
                associator_key="internal/scipy",
                confidence=IdentityConfidence.VERIFIED.value,
                outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
                source_repository_url=A_REPOSITORY_URL,
            ),
            clock=FixedClock(instant=LATER_INSTANT),
        )

    assert "internal/scipy" in str(refused.value)
    assert Package.objects.count() == 1


@pytest.mark.django_db
def test_a_correction_onto_another_packages_name_is_refused_before_the_write() -> None:
    """A colliding correction is a `ResolutionError`, not an `IntegrityError`.

    Two shells converging on one upstream package is precisely what correction is
    *for*, and it is a state this product deliberately permits: two inventory
    sources may file one package under two keys, which
    `test_one_source_key_may_be_claimed_by_two_different_sources` sets up on
    purpose. `canonical_name` is `unique=True`, so without a check here the
    collision escapes the `save()` as a `django.db.utils.IntegrityError` -- an
    exception this door's contract does not mention, from a module whose every
    other refusal is a `ResolutionError` raised before the first write.

    Merging the two rows is not this door's to do: it has to decide which key
    survives and which evidence moves, which is `CPM-IDENTITY-S05`'s audited
    correction. What this asserts is that the refusal is legible and that the
    resolution left nothing behind -- no mapping row, no changed confidence.
    """
    shell = _shell()
    _shell(key="internal/numpy-mirror", name=A_CORRECTED_NAME, source="another-associator")

    with pytest.raises(ResolutionError) as refused:
        record_resolution(
            resolution=Resolution(
                identity_source=A_RESOLVER,
                associator_key=A_KEY,
                confidence=IdentityConfidence.VERIFIED.value,
                outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
                canonical_name=A_CORRECTED_NAME,
                source_repository_url=A_REPOSITORY_URL,
            ),
            clock=FixedClock(instant=LATER_INSTANT),
        )

    assert A_CORRECTED_NAME in str(refused.value)
    package = Package.objects.get(pk=shell.pk)
    assert package.canonical_name == A_NAME
    assert package.confidence == IdentityConfidence.UNMAPPED
    assert package.source_repository_url == ""
    assert PackageMapping.objects.count() == 0


@pytest.mark.django_db
def test_correcting_a_name_onto_the_one_the_package_already_holds_is_not_a_collision() -> None:
    """The other side of that check, so it is not a ban on re-stating the name.

    A resolver that hands back the name the row already carries is the ordinary
    case for a package the inventory happened to name correctly, and an
    `exists()` that had not excluded the package itself would refuse every one of
    them -- turning the commonest resolution there is into a hard failure.
    """
    shell = _shell()

    recorded = record_resolution(
        resolution=Resolution(
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
            canonical_name=A_NAME,
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    assert recorded.package.pk == shell.pk
    assert Package.objects.get(pk=shell.pk).canonical_name == A_NAME


# ---------------------------------------------------------------------------
# AC #6: the pair is unique, and only where a source claims the package.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_second_package_under_the_same_source_key_is_refused_by_the_database() -> None:
    """AC #6: `one_package_per_source_key`, enforced by the table rather than by review.

    The refusal has to come from the database. An application-level check is a
    check-then-act, and two sweeps resolving the same source key concurrently are
    exactly the case that defeats it -- each finding nothing, each creating a
    shell, and the second key's evidence hanging off a row the first key's does
    not.
    """
    _shell()

    with pytest.raises(IntegrityError), transaction.atomic():
        Package.objects.create(
            canonical_name="a-different-name",
            resolved_at=FIXED_INSTANT,
            identity_source=A_RESOLVER,
            associator_key=A_KEY,
        )

    assert Package.objects.filter(identity_source=A_RESOLVER, associator_key=A_KEY).count() == 1


@pytest.mark.django_db
def test_two_packages_no_source_claims_both_persist() -> None:
    """AC #6's other half, and the reason the constraint carries a condition.

    `identity_source` and `associator_key` are `blank=True, default=""`, so an
    unconditional constraint would make `("", "")` a single permissible row for
    the whole product -- and `CPM-IDENTITY-S05`'s override path, or any creator
    that is not ingestion, would collide with it for no reason at all. The
    uniqueness rule is about a package *some source claims*.
    """
    Package.objects.create(canonical_name=A_NAME, resolved_at=FIXED_INSTANT)
    Package.objects.create(canonical_name="scipy", resolved_at=FIXED_INSTANT)

    assert Package.objects.filter(identity_source="", associator_key="").count() == TWO_ROWS


@pytest.mark.django_db
def test_one_source_key_may_be_claimed_by_two_different_sources() -> None:
    """The constraint is over the pair, not over the key, and that is deliberate.

    Two inventory sources may legitimately file different packages under the same
    key -- the key is a source's own identifier and means nothing outside it --
    so a constraint narrowed to `associator_key` alone would refuse a second
    adapter the day one is declared. Asserted because that narrowing passes the
    case above unchanged.
    """
    _shell(source=A_RESOLVER)
    _shell(key=A_KEY, name="scipy", source="another-associator")

    assert Package.objects.filter(associator_key=A_KEY).count() == TWO_ROWS


# ---------------------------------------------------------------------------
# The regression: ingest, resolve, ingest.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_corrected_package_still_receives_the_next_sweeps_snapshot() -> None:
    """The matrix's "correction survives the next sweep", and the story's reason for existing.

    `CPM-IDENTITY-S06`'s review recorded the failure this composes against: the
    shell is named by whatever the inventory calls the package, resolution
    corrects that name, and a lookup keyed on the name then matches nothing -- so
    the next sweep creates a second shell, the corrected package silently stops
    receiving inventory evidence, and the run reports success. Correction is the
    expected outcome for every package resolution touches, so the failure would
    fire for all of them rather than rarely.

    Three assertions, and each rules out a different way of half-passing: exactly
    one `Package` (no second shell), its name is the corrected one (the sweep did
    not overwrite the correction), and it gained a second snapshot on the row it
    already had (the evidence still lands on the package a reader would look at).
    The run state is asserted too, because a sweep that failed the record would
    leave one package and one snapshot as well.
    """
    assert _ingest(A_KEY) is RunState.SUCCEEDED
    shell = Package.objects.get(associator_key=A_KEY)

    record_resolution(
        resolution=Resolution(
            identity_source=COLLECTOR_NAME,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value),
            canonical_name=A_CORRECTED_NAME,
            source_repository_url=A_REPOSITORY_URL,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    assert _ingest(A_KEY, at=LATER_INSTANT) is RunState.SUCCEEDED

    assert Package.objects.count() == 1
    package = Package.objects.get()
    assert package.pk == shell.pk
    assert package.canonical_name == A_CORRECTED_NAME
    assert package.confidence == IdentityConfidence.VERIFIED
    assert InventorySnapshot.objects.filter(package=package).count() == TWO_ROWS


@pytest.mark.django_db
def test_the_sweep_after_a_resolution_leaves_the_identity_it_established_alone() -> None:
    """`CPM-AD-25` and the get-or-create that is deliberately not an update-or-create.

    The regression above proves the row is *found*; this proves finding it is
    harmless. Ingestion asserts no mapping (`CPM-FR-42`), so a second sweep must
    leave the source repository, the feedstocks and the `verified` confidence
    exactly as resolution left them -- including the outcome rows, which
    ingestion has no business writing at all.
    """
    _ingest(A_KEY)

    record_resolution(
        resolution=Resolution(
            identity_source=COLLECTOR_NAME,
            associator_key=A_KEY,
            confidence=IdentityConfidence.VERIFIED.value,
            outcomes=_outcomes(MappingKind.SOURCE_REPOSITORY.value, MappingKind.FEEDSTOCK.value),
            source_repository_url=A_REPOSITORY_URL,
            feedstocks=(FeedstockMapping(name=A_FEEDSTOCK_NAME, url=A_FEEDSTOCK_URL),),
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    _ingest(A_KEY, at=LATER_INSTANT)

    package = Package.objects.get()
    assert package.confidence == IdentityConfidence.VERIFIED
    assert package.source_repository_url == A_REPOSITORY_URL
    assert package.resolved_at == LATER_INSTANT
    assert [feedstock.name for feedstock in Feedstock.objects.filter(package=package)] == [A_FEEDSTOCK_NAME]
    assert _outcome_of(package, MappingKind.SOURCE_REPOSITORY.value) == ESTABLISHED
