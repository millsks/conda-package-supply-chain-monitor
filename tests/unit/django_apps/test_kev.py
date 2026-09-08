"""What the KEV collector declares, what a KEV source is, what a catalog means, and what a cross-reference is.

`CPM-FR-12` is several questions and only the last needs a run. Declaring the one
KEV source slot and refusing a second; reading a catalog document into its entries;
and cross-referencing a package's advisories against those entries are all pure
functions of data, and all are here with no database, no socket and no clock
(`CPM-AD-27`). What needs a run -- the rows, the link followed back to the finding
it derives from, the superseded case, the ledger, the constraint the database
enforces and the dispatch's selection -- is in
`tests/integration/django_apps/test_kev.py`.

**The vocabulary is asserted here first, and that is deliberate.**
`CPM-SECURITY-S01` shipped its sibling table with `ok` as the value meaning "this
package has a vulnerability" and two reviewers caught it independently. The two
cases below -- that neither determinate value is the one the shared order ranks
best, and that the order refuses them both until a rollup decides -- are the ones
that would have failed then, written before the collector rather than after the
review.

**The declarations are asserted against their derivations rather than against
themselves**, on the terms `tests/unit/django_apps/test_vulnerability.py` sets:
the target is the cadence times one plus the tolerated misses, the window is
shorter than the cadence, and one whole collection fits inside the inherited Celery
soft limit read from the settings module.

**The adapter slot is process-global, so every case that touches it withdraws.**
`kev_source_slot` is autouse and asserts the slot is empty on the way in as well as
clearing it on the way out: a case that left an adapter declared would change what
every later case in the whole suite reads, and one that found a slot already full
would be measuring somebody else's declaration.

No database, no network: nothing here saves a row, no queryset is evaluated, and
every payload is a literal. `current_findings` and `translate` read a table, so
they are asserted in the integration module and only *swept for* here.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.conf import settings
from structlog.testing import capture_logs

from conda_sentinel.collectors import kev as kev_module
from conda_sentinel.collectors.agent import USER_AGENT
from conda_sentinel.collectors.kev import ADVISORY_ID_FIELD
from conda_sentinel.collectors.kev import ALIASES_FIELD
from conda_sentinel.collectors.kev import CATALOG_ABSENT_EVENT
from conda_sentinel.collectors.kev import COLLECTOR_NAME
from conda_sentinel.collectors.kev import DATE_ADDED_FIELD
from conda_sentinel.collectors.kev import DOCUMENT_FIELDS
from conda_sentinel.collectors.kev import EARLIEST_CATALOG_DATE
from conda_sentinel.collectors.kev import ENTRIES_FIELD
from conda_sentinel.collectors.kev import ENTRY_FIELDS
from conda_sentinel.collectors.kev import KEV_CACHE_TTL
from conda_sentinel.collectors.kev import KEV_CADENCE
from conda_sentinel.collectors.kev import KEV_FRESHNESS_TARGET
from conda_sentinel.collectors.kev import KEV_HEADERS
from conda_sentinel.collectors.kev import KEV_OBSERVATION_WINDOW
from conda_sentinel.collectors.kev import KEV_RATE_LIMIT
from conda_sentinel.collectors.kev import KEV_RETRIES
from conda_sentinel.collectors.kev import KEV_SOURCE_LOCATOR
from conda_sentinel.collectors.kev import KEV_TIMEOUT
from conda_sentinel.collectors.kev import LATEST_CATALOG_DATE
from conda_sentinel.collectors.kev import MAX_ALIASES
from conda_sentinel.collectors.kev import MAX_CATALOG_CHARACTERS
from conda_sentinel.collectors.kev import MAX_CROSS_REFERENCES
from conda_sentinel.collectors.kev import MAX_ECHOED_CHARACTERS
from conda_sentinel.collectors.kev import MAX_ENTRIES
from conda_sentinel.collectors.kev import MAX_SENTINEL_DETAIL_CHARACTERS
from conda_sentinel.collectors.kev import NO_CATALOG_DATE_DETAIL
from conda_sentinel.collectors.kev import NO_KEV_SOURCE_EVENT
from conda_sentinel.collectors.kev import NOT_LISTED_DETAIL
from conda_sentinel.collectors.kev import OUT_OF_RANGE_CATALOG_DATE_DETAIL
from conda_sentinel.collectors.kev import SHORTENED_DETAIL
from conda_sentinel.collectors.kev import UNKNOWN_LOCATOR_DETAIL
from conda_sentinel.collectors.kev import UNKNOWN_SCHEME_DETAIL
from conda_sentinel.collectors.kev import UNREADABLE_CATALOG_DATE_DETAIL
from conda_sentinel.collectors.kev import Catalog
from conda_sentinel.collectors.kev import CatalogEntry
from conda_sentinel.collectors.kev import CrossReference
from conda_sentinel.collectors.kev import CurrentFinding
from conda_sentinel.collectors.kev import KevCollector
from conda_sentinel.collectors.kev import KevDocumentError
from conda_sentinel.collectors.kev import KevSourceError
from conda_sentinel.collectors.kev import catalog_in
from conda_sentinel.collectors.kev import cross_reference
from conda_sentinel.collectors.kev import declare_kev_source
from conda_sentinel.collectors.kev import declared_kev_source
from conda_sentinel.collectors.kev import kev_source
from conda_sentinel.collectors.kev import stale_clause
from conda_sentinel.collectors.kev import withdraw_kev_source
from conda_sentinel.collectors.models import KevFinding
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.collectors.outcomes import KEV_UNKNOWN
from conda_sentinel.collectors.outcomes import LISTED
from conda_sentinel.collectors.outcomes import LISTED_MEMBER
from conda_sentinel.collectors.outcomes import MATCHED
from conda_sentinel.collectors.outcomes import NOT_LISTED
from conda_sentinel.collectors.outcomes import NOT_LISTED_MEMBER
from conda_sentinel.collectors.outcomes import KevOutcome
from conda_sentinel.collectors.tasks import COLLECT_KEV_TASK_NAME
from conda_sentinel.collectors.tasks import collect_kev
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.collection import CONDITIONAL_HEADERS
from conda_sentinel.core.collection import NO_CACHE
from conda_sentinel.core.collection import Collector
from conda_sentinel.core.collection import CollectorConfigurationError
from conda_sentinel.core.outcomes import SENTINEL_MEMBERS
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.outcomes import OutcomeVocabularyError
from conda_sentinel.core.outcomes import aggregate
from conda_sentinel.core.outcomes import verify_sentinels
from conda_sentinel.core.queues import Queue
from conda_sentinel.core.queues import queue_for
from conda_sentinel.core.transport import DEFAULT_RETRIES
from conda_sentinel.core.transport import MAX_TIMEOUT
from conda_sentinel.core.transport import worst_case_call_seconds
from tests.clocks import FIXED_INSTANT
from tests.collectors import RecordedTransport
from tests.source_scan import SRC_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: The module this file's source sweeps are about, relative to `src/`.
KEV_MODULE: Final[str] = "django_apps/conda_sentinel/collectors/kev.py"

#: The two models this collector may name, and the write methods it may not reach
#: for on either. `CPM-AD-7` says a collector "reads only `identity`"; this one
#: also reads `vulnerability_findings`, which is the exception
#: `CPM-SECURITY-S02`'s Spec Change Log records -- so the sweep asserts the read is
#: *there* and that nothing anywhere in the module writes.
PACKAGE_MODEL_NAME: Final[str] = "Package"
VULNERABILITY_MODEL_NAME: Final[str] = "VulnerabilityFinding"
WRITE_METHODS: Final[frozenset[str]] = frozenset(
    {
        "abulk_create",
        "acreate",
        "adelete",
        "asave",
        "aupdate",
        "bulk_create",
        "bulk_update",
        "create",
        "delete",
        "get_or_create",
        "save",
        "update",
        "update_or_create",
        # The three the append-only base enumerates as the paths that reach a
        # table without constructing an instance, so `save()` cannot see them --
        # `_raw_delete` is the deletion collector's own statement, `raw` executes
        # whatever SQL it is handed, and `_base_manager` is the plain manager
        # Django builds on a model's behalf and the one somebody reaches for after
        # `objects.update()` has refused. A sweep that omitted them would license
        # exactly the escapes `core/models.py` guards.
        "_raw_delete",
        "raw",
        "_base_manager",
    },
)

#: The modules this repository permits to declare a KEV source, and it is empty:
#: no source ships (PRD Open Question 1). A named, licensable set rather than a
#: bare "nowhere", on the terms the advisory sweep states: a deployment that *does*
#: declare one has to put the call somewhere under `src/`, and a rule that could
#: not be satisfied would be deleted rather than amended. `docs/deployment.md`
#: tells an operator to add the declaring module here in the same change.
MODULES_PERMITTED_TO_DECLARE_A_KEV_SOURCE: Final[frozenset[str]] = frozenset()

#: The locator a payload claims to have come from -- the adapter's own, which is
#: what a determinate row records and is deliberately *not* the opaque question the
#: run asked.
AN_ANSWERING_SOURCE: Final[str] = "https://kev.invalid/catalog.json"

#: What the catalogs say, and what this product records.
#:
#: Three schemes, because the scheme is load-bearing: a catalog that states one and
#: a finding recorded under another is the case `not_listed` may not be claimed for,
#: and a set of fixtures all in one scheme would never reach it. `ANOTHER_CVE` and
#: `A_THIRD_CVE` exist for the cases that are about *listing* rather than about
#: schemes, where sharing a scheme with the catalog is the point.
AN_ADVISORY: Final[str] = "CVE-2024-23334"
ANOTHER_ADVISORY: Final[str] = "GHSA-5h86-8mv2-jq9f"
A_THIRD_ADVISORY: Final[str] = "PYSEC-2024-42"
ANOTHER_CVE: Final[str] = "CVE-2023-49081"
A_THIRD_CVE: Final[str] = "CVE-2022-33124"
A_CATALOG_DATE: Final[str] = "2024-02-06T00:00:00+00:00"
A_CATALOG_INSTANT: Final[datetime] = datetime(2024, 2, 6, tzinfo=UTC)

#: Primary keys the cases that need one use. This tier never reads a row.
A_PACKAGE: Final[int] = 11
A_FINDING: Final[int] = 101
ANOTHER_FINDING: Final[int] = 102
A_THIRD_FINDING: Final[int] = 103

#: How much of the inherited soft limit one whole *collection* may spend -- three
#: quarters, so the claim is "with room for the ledger writes around it" rather
#: than "by a hair". This collector makes one call, so the figure is one retried
#: call rather than a product.
SOFT_LIMIT_SHARE: Final[float] = 0.75

#: What `collectors/vulnerability.py` declares against a source that publishes no
#: numeric ceiling either. Named so the comparison below reads as the argument it
#: is rather than as a bare number.
A_SIBLINGS_COURTESY_BOUND: Final[int] = 30

#: How many advisories the public catalogue this product would most plausibly read
#: carries, as of writing. Named rather than spelled in the assertions below,
#: because the two bounds are measured *against a real catalog's size* and a bare
#: number would read as a preference.
A_PUBLIC_CATALOGUES_SIZE: Final[int] = 1500

#: The most findings `collectors/vulnerability.py` records from one advisory
#: document. Restated here rather than imported, exactly as the collector restates
#: it: no collector imports another (`CPM-AD-7`), and this story's one exception is
#: a read of a table rather than of a constant.
A_SIBLINGS_DOCUMENT_BOUND: Final[int] = 1000

#: The counts the cases assert against, one named constant per concept, because
#: `PLR2004` is right about a bare number in an assertion.
THREE_ANSWERS: Final[int] = 3
TWO_EXCLUDED: Final[int] = 2
FOUR_SENTINELS: Final[int] = 4
SIX_VALUES: Final[int] = 6

#: The marker the document builder treats as "the catalog did not send this field
#: at all", as distinct from `None`, which is an explicit JSON `null`.
OMITTED: Final[object] = object()


class _NotATransport:
    """Something with no `fetch`, for the case about what an adapter must be."""


@pytest.fixture(autouse=True)
def kev_source_slot() -> Iterator[None]:
    """Assert the one adapter slot starts empty, and leave it empty.

    Autouse because the slot is process-global: a case that left an adapter
    declared would change what every later case in the suite reads, and one that
    found the slot already full would be measuring somebody else's declaration.
    Both halves are asserted rather than only the clean-up, which is what makes
    this a guard rather than a tidy-up.

    Yields:
        Nothing; the slot is empty for the duration of the case.

    """
    assert declared_kev_source() is None
    yield
    if declared_kev_source() is not None:
        withdraw_kev_source()


def _stopped_clock() -> FixedClock:
    """Return the clock every case injects.

    Returns:
        A clock stopped at the suite's shared instant.

    """
    return FixedClock(instant=FIXED_INSTANT)


def _entry(
    advisory_id: object = AN_ADVISORY,
    *,
    date_added: object = A_CATALOG_DATE,
    aliases: object = OMITTED,
) -> dict[str, Any]:
    """Return one catalog entry as an adapter would state it.

    Args:
        advisory_id: The advisory's identifier, or `OMITTED` to leave it out.
        date_added: The date the catalog states, or `OMITTED`.
        aliases: The other identifiers the catalog says the advisory carries, or
            `OMITTED`.

    Returns:
        The entry object.

    """
    stated = {ADVISORY_ID_FIELD: advisory_id, DATE_ADDED_FIELD: date_added, ALIASES_FIELD: aliases}
    return {field: value for field, value in stated.items() if value is not OMITTED}


def _catalog(*entries: dict[str, Any]) -> str:
    """Return the body a KEV source adapter would record.

    Args:
        *entries: The advisories the catalog lists, in order.

    Returns:
        The JSON body.

    """
    return json.dumps({ENTRIES_FIELD: list(entries)})


def _finding(finding_id: int = A_FINDING, advisory_id: str = AN_ADVISORY) -> CurrentFinding:
    """Return one advisory this product currently records against a package.

    Args:
        finding_id: The vulnerability finding's key.
        advisory_id: The advisory it named.

    Returns:
        The value the pure cross-reference takes.

    """
    return CurrentFinding(finding_id=finding_id, package_id=A_PACKAGE, advisory_id=advisory_id)


def _kev_module() -> Path:
    """Return the collector module's own source file.

    Returns:
        Its path under `src/`.

    """
    return SRC_ROOT / KEV_MODULE


# ---------------------------------------------------------------------------
# The declarations.
# ---------------------------------------------------------------------------


def test_the_collector_declares_every_value_the_base_checks() -> None:
    """All nine, written out on the class and carrying the module's own constants.

    Compared by *value* rather than by presence, for the reason the five sibling
    collectors' cases give: a class attribute rebound to the wrong constant
    declares nine names and behaves like something nobody wrote down.
    """
    declared = vars(KevCollector)

    assert KevCollector.name == COLLECTOR_NAME
    assert KevCollector.evidence_model is KevFinding
    assert KevCollector.observation_window == KEV_OBSERVATION_WINDOW
    assert KevCollector.timeout == KEV_TIMEOUT
    assert KevCollector.retries == KEV_RETRIES
    assert KevCollector.rate_limit == KEV_RATE_LIMIT
    assert KevCollector.headers == KEV_HEADERS
    assert KevCollector.freshness_target == KEV_FRESHNESS_TARGET
    assert KevCollector.response_cache_ttl == KEV_CACHE_TTL
    assert {
        "name",
        "evidence_model",
        "observation_window",
        "timeout",
        "retries",
        "rate_limit",
        "headers",
        "freshness_target",
        "response_cache_ttl",
    } <= set(declared)


def test_the_cadence_is_the_daily_one_the_prd_states_rather_than_a_range_to_choose_in() -> None:
    """`CPM-NFR-2` gives security and KEV "daily", with no range.

    Asserted against the slow end of the *currency* range as well, so a cadence
    quietly lengthened to match the feedstock collector fails here rather than
    passing by agreeing with a constant beside it.
    """
    assert timedelta(days=1) == KEV_CADENCE
    assert timedelta(days=7) > KEV_CADENCE


def test_the_freshness_target_is_the_arithmetic_open_question_7_settled() -> None:
    """`cadence x (1 + tolerated_missed_runs)`, which for this signal class is two days.

    `core/freshness.py` reports stale when `observed_at < now - target`, so a target
    *equal* to the cadence makes every package read stale at exactly the moment its
    next run is due, without a single collection having failed.
    """
    assert KEV_FRESHNESS_TARGET == KEV_CADENCE * (1 + kev_module.TOLERATED_MISSED_RUNS)
    assert timedelta(days=2) == KEV_FRESHNESS_TARGET
    assert KEV_FRESHNESS_TARGET > KEV_CADENCE


def test_the_observation_window_cannot_suppress_a_scheduled_run() -> None:
    """Shorter than the cadence, which is the property rather than the halving."""
    assert KEV_OBSERVATION_WINDOW < KEV_CADENCE
    assert timedelta(0) < KEV_OBSERVATION_WINDOW


def test_nothing_is_remembered_between_runs_and_the_declaration_says_so() -> None:
    """`NO_CACHE`, declared rather than defaulted.

    A remembered body is only usable against a source that offers a validator, and
    nothing here knows whether the declared adapter speaks HTTP at all. The
    equality with the sentinel is the assertion: a lifetime of zero *seconds* would
    behave the same way and would read as an oversight.
    """
    assert KEV_CACHE_TTL == NO_CACHE
    assert KevCollector.response_cache_ttl == NO_CACHE


def test_the_worst_collection_this_declaration_permits_fits_inside_the_inherited_soft_limit() -> None:
    """One retried call, reconciled against the settings module's own limit.

    Read from the settings module rather than repeated here, so lowering the limit
    there fails this rather than passing quietly. The timeout is also checked
    against the transport's own ceiling, which is the bound `core/transport.py`
    refuses above.
    """
    worst_case = worst_case_call_seconds(timeout=KEV_TIMEOUT, retries=KEV_RETRIES)

    assert worst_case <= SOFT_LIMIT_SHARE * settings.CELERY_TASK_SOFT_TIME_LIMIT
    assert KEV_TIMEOUT <= MAX_TIMEOUT


def test_the_retry_budget_is_the_shared_default_because_nothing_here_argues_it_down() -> None:
    """One call per collection and no chosen source, so the default is the honest declaration."""
    assert KEV_RETRIES == DEFAULT_RETRIES


def test_the_declared_headers_carry_what_the_source_expects_and_nothing_conditional() -> None:
    """Headers reach a source only through the base (`CPM-AD-20`, `CPM-AD-27`).

    The JSON representation `catalog_in` reads is asked for by name and the
    `User-Agent` is the one identity every collector shares. What is not declared is
    a validator, which the base composes from the response cache and refuses at
    construction.
    """
    lowered = {name.lower(): value for name, value in KEV_HEADERS.items()}

    assert lowered["user-agent"] == USER_AGENT
    assert lowered["accept"] == "application/json"
    assert set(lowered).isdisjoint({header.lower() for header in CONDITIONAL_HEADERS})


def test_the_declared_allowance_is_a_courtesy_bound_a_whole_collection_fits_inside() -> None:
    """No source is chosen, so there is no published ceiling to quote.

    Three things are worth pinning: a single collection's charge fits inside it --
    an allowance smaller than `1 + retries` would refuse every call -- it is counted
    per minute, and it is no looser than the sibling security collector, which faces
    a source with the same silence and fires on the same tick.
    """
    assert KEV_RATE_LIMIT.calls >= 1 + KEV_RETRIES
    assert KEV_RATE_LIMIT.per == timedelta(minutes=1)
    assert KEV_RATE_LIMIT.calls <= A_SIBLINGS_COURTESY_BOUND


def test_the_collector_is_constructed_from_its_declarations_alone() -> None:
    """The base's nine refusals, run against the real class rather than a fixture."""
    collector = KevCollector(clock=_stopped_clock())

    try:
        assert collector.request_cost == 1 + KEV_RETRIES
        assert KEV_RATE_LIMIT.calls >= collector.request_cost
    finally:
        collector.close()


def test_the_task_name_routes_to_the_collect_queue() -> None:
    """`cpm.collect.*` is what puts external I/O on the `collect` queue (`R-11`).

    The Celery binding is asserted too: the constant is what routes, and a task
    registered under a name the constant does not spell would route nowhere.
    """
    assert queue_for(COLLECT_KEV_TASK_NAME) == Queue.COLLECT
    assert COLLECT_KEV_TASK_NAME.endswith(COLLECTOR_NAME)
    assert collect_kev.name == COLLECT_KEV_TASK_NAME


def test_the_two_catalog_ceilings_are_separately_reachable() -> None:
    """Two bounds within a percent of each other are one bound and the wrong refusal.

    That is what the first pass shipped: a full-size catalog of minimal entries
    tripped the *character* ceiling first, so an operator whose source served too
    many entries was told their document was too long. Both halves are asserted as
    relations rather than as numbers:

    * a catalog of `MAX_ENTRIES` **minimal** entries fits inside
      `MAX_CATALOG_CHARACTERS`, so the entry bound is the one it meets; and
    * a catalog of far fewer **wide** entries exceeds `MAX_CATALOG_CHARACTERS`
      while staying under `MAX_ENTRIES`, so the character bound is reachable too.
    """
    smallest = len(json.dumps({ADVISORY_ID_FIELD: AN_ADVISORY})) + 1
    width = int(VulnerabilityFinding._meta.get_field("advisory_id").max_length)  # noqa: SLF001 - Django's own API
    widest = len(json.dumps(_entry("C" * width, aliases=["A" * width] * MAX_ALIASES))) + 1

    assert smallest * MAX_ENTRIES < MAX_CATALOG_CHARACTERS
    assert widest * MAX_ENTRIES > MAX_CATALOG_CHARACTERS


def test_both_ceilings_are_far_above_the_public_catalogue_and_far_below_a_malfunction() -> None:
    """A ceiling nothing bounds is not a ceiling, and one a real document trips records `error`.

    The public catalogue this product would most plausibly read carries some fifteen
    hundred entries, and in this collector's own schema that is well under a hundred
    kilobytes.
    """
    honest = len(json.dumps({ENTRIES_FIELD: [_entry() for _ in range(A_PUBLIC_CATALOGUES_SIZE)]}))

    assert A_PUBLIC_CATALOGUES_SIZE < MAX_ENTRIES
    assert honest < MAX_CATALOG_CHARACTERS
    assert MAX_ENTRIES > 0


def test_the_row_bound_admits_a_whole_advisory_document_and_the_misses_it_tolerates() -> None:
    """The bound on what one collection writes, asserted as the arithmetic it is.

    A run writes one row per *current* advisory, and current is bounded in time
    rather than in number -- so without a bound a package with a long enough
    advisory history inserts that many rows in one `bulk_create`, inside one
    package's transaction, every day. The number is the sibling collector's own
    per-document bound times `1 + TOLERATED_MISSED_RUNS`, because at most that many
    collections' worth of distinct advisories can be inside the freshness window at
    once -- and it is restated rather than imported, because no collector imports
    another.
    """
    assert MAX_CROSS_REFERENCES == A_SIBLINGS_DOCUMENT_BOUND * (1 + kev_module.TOLERATED_MISSED_RUNS)
    assert MAX_CROSS_REFERENCES > A_SIBLINGS_DOCUMENT_BOUND


def test_the_locator_this_run_asks_about_fits_the_column_that_records_it() -> None:
    """The constant is what a sentinel row and the `unknown` row both carry as their `source`.

    Asserted as a relation rather than against a number: a locator wider than the
    column is a value PostgreSQL refuses at insert and SQLite stores (`R-5`), and
    the sibling has a whole refusal path for exactly that because its locator
    embeds a purl. This one cannot vary, so the case is the whole of the guard.
    """
    width = KevFinding._meta.get_field("source").max_length  # noqa: SLF001 - Django's public-by-convention API

    assert len(KEV_SOURCE_LOCATOR) <= int(width)


def test_the_locator_names_no_host_of_its_own() -> None:
    """`CPM-AD-29` makes the source a transport substitution, so the locator names the question.

    A hostname here would be this module answering PRD Open Question 1, and it would
    be an answer a reader of the declarations would never see, because the adapter
    slot would still look empty.
    """
    assert KEV_SOURCE_LOCATOR.startswith("kev://")
    assert "http" not in KEV_SOURCE_LOCATOR


# ---------------------------------------------------------------------------
# The KEV source slot, which is a second slot and not a second use of the first.
# ---------------------------------------------------------------------------


def test_no_kev_source_ships_declared() -> None:
    """The shipped state, asserted rather than assumed.

    PRD Open Question 1 blocks this epic, so `CollectorsConfig.ready()` deliberately
    declares nothing -- and this runs after `django.setup()` has called it. A
    `ready()` that quietly started declaring a default source would fail here, which
    is one of two places in the suite that could notice.
    """
    assert declared_kev_source() is None


def test_a_declared_adapter_is_the_one_the_collector_reads() -> None:
    """Declare, read, withdraw -- the whole of the slot's contract.

    `declare_kev_source` answers with the adapter so a caller can bind it in one
    statement, which is what an `AppConfig.ready()` does.
    """
    adapter = RecordedTransport()

    assert declare_kev_source(adapter) is adapter
    assert declared_kev_source() is adapter
    assert kev_source() is adapter

    withdraw_kev_source()

    assert declared_kev_source() is None


def test_something_that_is_not_a_transport_cannot_be_a_kev_source() -> None:
    """`CPM-AD-29`'s seam is the transport's, so an adapter is a `Transport` and nothing else."""
    with pytest.raises(KevSourceError, match="is not a Transport"):
        declare_kev_source(_NotATransport())  # type: ignore[arg-type]

    assert declared_kev_source() is None


def test_a_second_adapter_is_refused_at_the_declaration_rather_than_overwriting_the_first() -> None:
    """One slot (`CPM-AD-29`), and the refusal names both classes.

    A second declaration silently replacing the first is how a deployed component
    comes to believe a development catalog: the cross-references it then records,
    and the ones it fails to record, are permanent.
    """
    declare_kev_source(RecordedTransport())

    with pytest.raises(KevSourceError, match="already this component's KEV source"):
        declare_kev_source(RecordedTransport())


def test_declaring_the_same_adapter_twice_is_refused_too() -> None:
    """The slot is refused on being *occupied*, not on the adapter differing.

    A caller that wants to know whether a declaration has already been made asks
    `declared_kev_source`, which is what a `ready()` that may run twice does. A
    declaration that quietly succeeded for an identical object would make the slot's
    emptiness unobservable.
    """
    adapter = RecordedTransport()
    declare_kev_source(adapter)

    with pytest.raises(KevSourceError, match="already this component's KEV source"):
        declare_kev_source(adapter)


def test_withdrawing_nothing_is_refused_rather_than_ignored() -> None:
    """A silent no-op turns a mistaken withdrawal into a declaration that stays live."""
    with pytest.raises(KevSourceError, match="nothing to withdraw"):
        withdraw_kev_source()


def test_a_run_with_no_declared_source_is_refused_naming_the_declaration() -> None:
    """The message tells an operator what to do, which is the whole of this story's posture.

    It names the function that declares one and the open question that is why none
    ships, so an operator meeting a failed task is not left to read the source.
    """
    with pytest.raises(KevSourceError, match="declare_kev_source") as refused:
        kev_source()

    assert "Open Question 1" in str(refused.value)


def test_the_kev_slot_is_a_second_slot_and_not_a_second_use_of_the_advisory_one() -> None:
    """Two sources, two slots, two refusals, and neither withdrawal touches the other.

    An advisory database and a KEV catalog are different products with different
    licences, and an operator may reasonably have one and not the other. A shared
    slot would make declaring either one silently declare both -- and withdrawing
    one would stop the other collector with nothing said.

    Imported inside the case rather than at module scope, because this file's
    autouse fixture guards the KEV slot alone and a module-level import of the
    advisory slot would invite a case here to leave that one occupied.
    """
    from conda_sentinel.collectors.advisories import declared_advisory_source  # noqa: PLC0415 - see above

    declare_kev_source(RecordedTransport())

    assert declared_advisory_source() is None
    assert declared_kev_source() is not None


# ---------------------------------------------------------------------------
# The composed outcome vocabulary -- the correction CPM-SECURITY-S01 was patched
# for, made here by construction.
# ---------------------------------------------------------------------------


def test_neither_determinate_value_is_the_one_the_shared_order_ranks_best() -> None:
    """The whole reason this vocabulary exists, asserted as the facts that make it necessary.

    On this table a determinate row is either "the catalog says this advisory is
    being used against people" or "it says it is not". `CPM-AD-24` carries a state's
    value verbatim onto every read surface and `core`'s single precedence order
    ranks `ok` best of five, so a table using `ok` for the first would render
    exactly the known-exploited packages as the clean ones -- and `CPM-UJ-1`'s
    queue, which opens on KEV findings, would sort them last.
    """
    assert OutcomeState.OK.value != LISTED
    assert OutcomeState.OK.value != NOT_LISTED
    assert LISTED not in set(OutcomeState.values)
    assert NOT_LISTED not in set(OutcomeState.values)
    assert LISTED_MEMBER[1] == LISTED
    assert NOT_LISTED_MEMBER[1] == NOT_LISTED
    assert KevFinding._meta.get_field("state").choices == KevOutcome.choices  # noqa: SLF001 - Django's own API


def test_the_vocabulary_carries_the_four_sentinels_by_name_and_value() -> None:
    """`outcome_type`'s post-condition, asserted on the type this table actually declares.

    It is what lets `sentinel_evidence` write `state.value` straight onto a row: an
    `OutcomeState` sentinel *is* a `KevOutcome` value, by construction rather than
    by coincidence. A case rather than a comment, because the write depends on it.
    """
    verify_sentinels(KevOutcome)

    values = set(KevOutcome.values)

    assert len(SENTINEL_MEMBERS) == FOUR_SENTINELS
    assert {value for _, value in SENTINEL_MEMBERS} <= values
    assert values == {value for _, value in SENTINEL_MEMBERS} | {LISTED, NOT_LISTED}
    assert len(values) == SIX_VALUES


def test_the_vocabulary_declares_no_precedence_order_of_its_own() -> None:
    """Nothing reduces these rows yet, so an order here would be data no function reads.

    `core.outcomes.aggregate` refuses both determinate values outright until a story
    decides their rank, which is the safe failure and exactly what that module says
    it is for. `CPM-SECURITY-S04`'s rollup pass is the first consumer and is where
    the order will be declared -- and the ordering question it has to answer is the
    interesting one: `not_listed` is not clean, so it must not be ranked as though
    it were.
    """
    for determinate in (LISTED, NOT_LISTED):
        with pytest.raises(OutcomeVocabularyError, match="has no rank"):
            aggregate([determinate])

    # And the sentinels still rank, so the refusal is about the determinate values
    # rather than about the vocabulary being unrecognised wholesale.
    assert aggregate([KEV_UNKNOWN, OutcomeState.NOT_APPLICABLE.value]) is OutcomeState.UNKNOWN


def test_the_established_negative_is_its_own_value_rather_than_a_sentinel() -> None:
    """Three different facts, three different values, which is `CPM-FR-6` on this table.

    "The catalog does not list this advisory" is a negative that was *established*;
    `unknown` is nothing established at all; and `not_found` is the KEV source
    reporting that the locator itself is gone. Folding any two of them together
    would leave a reader unable to tell "not in the catalog" from "the catalog is
    gone".
    """
    assert len({NOT_LISTED, KEV_UNKNOWN, OutcomeState.NOT_FOUND.value}) == THREE_ANSWERS


# ---------------------------------------------------------------------------
# The catalog document.
# ---------------------------------------------------------------------------


def test_a_catalog_that_lists_one_advisory_with_a_date_reads_as_that_entry() -> None:
    """The simplest whole document: one entry, keyed for lookup, carrying an aware instant."""
    catalog = catalog_in(_catalog(_entry()), source=AN_ANSWERING_SOURCE)

    (entry,) = catalog.entries.values()
    assert entry.advisory_id == AN_ADVISORY
    assert entry.date_added == A_CATALOG_INSTANT
    assert entry.fault == ""
    assert set(catalog.entries) == {AN_ADVISORY.casefold()}
    assert catalog.schemes == {"cve"}


@pytest.mark.parametrize("stated", [OMITTED, None, "", "   "], ids=["omitted", "null", "blank", "whitespace"])
def test_a_catalog_that_states_no_date_says_so_rather_than_inventing_one(stated: Any) -> None:
    """Blank means missing (PRD Appendix A.1), and the entry carries the reason it is blank."""
    catalog = catalog_in(_catalog(_entry(date_added=stated)), source=AN_ANSWERING_SOURCE)

    (entry,) = catalog.entries.values()
    assert entry.date_added is None
    assert entry.fault == NO_CATALOG_DATE_DETAIL


@pytest.mark.parametrize(
    "stated",
    ["not a date", "2024-02-06T00:00:00", "2024-02-06", "6 February 2024"],
    ids=["nonsense", "naive-datetime", "bare-date", "prose"],
)
def test_a_date_the_collector_cannot_read_is_recorded_as_missing_rather_than_guessed(stated: str) -> None:
    """Unreadable and naive are one outcome, and the entry says which value it could not read.

    A naive value is discarded rather than assumed to be UTC (`CPM-AD-26`): there is
    no offset to convert from, and an instant shifted by a guess would be a
    permanent claim about when an advisory became known-exploited. A **bare date** is
    the shape a catalogue is likeliest to publish and it parses naive, which is why
    it is here rather than left to be discovered.

    The document is **not** refused, which is the one place this module reads past
    something it did not understand: what `CPM-FR-12` is about is the link, and
    discarding a whole catalog over one malformed date would lose every
    cross-reference for every package to protect a secondary field.
    """
    catalog = catalog_in(_catalog(_entry(date_added=stated)), source=AN_ANSWERING_SOURCE)

    (entry,) = catalog.entries.values()
    assert entry.date_added is None
    assert entry.fault.startswith(UNREADABLE_CATALOG_DATE_DETAIL)
    assert stated in entry.fault


@pytest.mark.parametrize(
    "stated",
    ["0001-01-01T00:00:00+00:00", "9999-12-31T23:59:59+00:00", "1998-12-31T23:59:59+00:00"],
    ids=["earliest-representable", "latest-representable", "before-cve-existed"],
)
def test_a_catalog_date_outside_the_recordable_range_is_recorded_as_missing(stated: str) -> None:
    """A stored instant is not the whole of what Python can represent, and the gap is where a row is lost.

    A date near `datetime.min`/`datetime.max` converts on its way to the driver and
    raises **there** -- several frames past the guard `translate` is wrapped in -- so
    an unbounded one escapes as neither a document refusal nor a recorded
    observation, which is "no row" on the one path this module cannot see. Bounded
    rather than refused, on the terms every other unreadable date is: the fact
    `CPM-FR-12` is about is the link, and the advisory is still recorded as listed.
    """
    catalog = catalog_in(_catalog(_entry(date_added=stated)), source=AN_ANSWERING_SOURCE)

    (entry,) = catalog.entries.values()
    assert entry.date_added is None
    assert entry.fault.startswith(OUT_OF_RANGE_CATALOG_DATE_DETAIL)
    assert stated in entry.fault


def test_the_recordable_range_admits_the_dates_a_real_catalogue_states() -> None:
    """The anti-vacuity half: the window refuses what it must and admits what it must.

    A bound that refused a date the public catalogue actually publishes would put
    every real entry into the "missing" branch, which reads exactly like a source
    that states no dates at all.
    """
    assert EARLIEST_CATALOG_DATE <= A_CATALOG_INSTANT <= LATEST_CATALOG_DATE
    assert EARLIEST_CATALOG_DATE < LATEST_CATALOG_DATE


def test_a_stated_date_carrying_a_control_character_is_refused_where_it_enters() -> None:
    """The one value a catalog states that lands in a `detail` rather than a column of its own.

    It is echoed onto an append-only row and copied from there into the ledger row
    and every log line the run emits, so it passes the same guard every stored value
    passes -- which the first pass did not do.
    """
    with pytest.raises(KevDocumentError, match="control character"):
        catalog_in(_catalog(_entry(date_added="2024-02-\x0006")), source=AN_ANSWERING_SOURCE)


def test_a_stated_date_longer_than_the_echo_bound_is_refused_rather_than_shortened() -> None:
    """A date is short, and a shortened date is a different date.

    Refused rather than truncated, unlike a sentinel's reason: this value is a
    *fact the entry claimed*, and the row would otherwise carry an unbounded slab of
    a source's text in a column nothing may correct.
    """
    with pytest.raises(KevDocumentError, match="copies at most"):
        catalog_in(_catalog(_entry(date_added="2" * (MAX_ECHOED_CHARACTERS + 1))), source=AN_ANSWERING_SOURCE)


def test_a_catalog_that_lists_nothing_is_an_answer_rather_than_a_defect() -> None:
    """A catalog listing no advisories is a source doing its job on a quiet day.

    It states no scheme either, so every finding reads as `unknown` rather than as
    an advisory the catalog does not list -- which falls out of the scheme rule
    rather than being a special case, and is the safe direction.
    """
    catalog = catalog_in(_catalog(), source=AN_ANSWERING_SOURCE)

    assert catalog.entries == {}
    assert catalog.schemes == frozenset()


@pytest.mark.parametrize("stated", [OMITTED, None], ids=["omitted", "explicit-null"])
def test_an_absent_entry_list_is_a_catalog_that_lists_nothing(stated: Any) -> None:
    """Absent and null both mean the same thing, and neither is a shape change."""
    document: dict[str, Any] = {} if stated is OMITTED else {ENTRIES_FIELD: None}

    assert catalog_in(json.dumps(document), source=AN_ANSWERING_SOURCE).entries == {}


def test_three_listed_advisories_are_three_entries_keyed_for_lookup() -> None:
    """The plural half, and the keying is what makes a cross-reference a lookup."""
    body = _catalog(_entry(), _entry(ANOTHER_ADVISORY), _entry(A_THIRD_ADVISORY, date_added=None))

    catalog = catalog_in(body, source=AN_ANSWERING_SOURCE)

    assert set(catalog.entries) == {
        AN_ADVISORY.casefold(),
        ANOTHER_ADVISORY.casefold(),
        A_THIRD_ADVISORY.casefold(),
    }
    assert len(catalog.entries) == THREE_ANSWERS
    assert catalog.schemes == {"cve", "ghsa", "pysec"}


def test_an_alias_a_catalog_states_reaches_the_same_entry_as_the_identifier() -> None:
    """The aliasing fix, at the reader: one advisory, several spellings, one entry.

    A catalog that publishes CVE identifiers and knows their GHSA spellings says so,
    and a finding recorded under either reaches the same entry with the same date.
    """
    catalog = catalog_in(_catalog(_entry(aliases=[ANOTHER_ADVISORY])), source=AN_ANSWERING_SOURCE)

    assert set(catalog.entries) == {AN_ADVISORY.casefold(), ANOTHER_ADVISORY.casefold()}
    assert catalog.entries[ANOTHER_ADVISORY.casefold()].date_added == A_CATALOG_INSTANT
    # And the alias's scheme joins the catalog's, because the catalog now speaks it.
    assert catalog.schemes == {"cve", "ghsa"}


@pytest.mark.parametrize("stated", [OMITTED, None], ids=["omitted", "explicit-null"])
def test_a_catalog_that_states_no_aliases_is_read_without_them(stated: Any) -> None:
    """Optional, because the catalogue this product would most plausibly read states none."""
    catalog = catalog_in(_catalog(_entry(aliases=stated)), source=AN_ANSWERING_SOURCE)

    assert set(catalog.entries) == {AN_ADVISORY.casefold()}


def test_an_alias_list_that_is_not_a_list_is_refused() -> None:
    """A source whose shape has changed is refused rather than read past."""
    with pytest.raises(KevDocumentError, match="rather than a list"):
        catalog_in(_catalog(_entry(aliases=ANOTHER_ADVISORY)), source=AN_ANSWERING_SOURCE)


@pytest.mark.parametrize("alias", [None, "", "   ", 7], ids=["null", "blank", "spaces", "int"])
def test_an_alias_that_is_not_an_identifier_is_refused(alias: Any) -> None:
    """A blank alias would key every unnamed advisory to this entry."""
    with pytest.raises(KevDocumentError, match="alias 0 of the entry"):
        catalog_in(_catalog(_entry(aliases=[alias])), source=AN_ANSWERING_SOURCE)


def test_more_aliases_than_an_advisory_carries_is_refused() -> None:
    """An advisory issued under a handful of schemes carries a handful of identifiers."""
    stated = [f"GHSA-{index:04d}" for index in range(MAX_ALIASES + 1)]

    with pytest.raises(KevDocumentError, match="reads at most"):
        catalog_in(_catalog(_entry(aliases=stated)), source=AN_ANSWERING_SOURCE)


def test_an_alias_wider_than_the_column_an_identifier_is_compared_against_is_refused() -> None:
    """An alias is an identifier, so it passes the identifier's own guard."""
    width = int(VulnerabilityFinding._meta.get_field("advisory_id").max_length)  # noqa: SLF001 - Django's own API

    with pytest.raises(KevDocumentError, match="the column that holds it takes"):
        catalog_in(_catalog(_entry(aliases=["C" * (width + 1)])), source=AN_ANSWERING_SOURCE)


def test_one_advisory_reachable_under_two_entries_is_refused_rather_than_read_for_one_of_them() -> None:
    """A document defect, and the date is why it matters.

    Two entries for one advisory could carry two dates, and the date is half of what
    `CPM-FR-12` records -- so choosing between them would be an invention. Both
    spellings are named, because the pair is what a reader has to go and reconcile.
    """
    body = _catalog(_entry(), _entry(AN_ADVISORY.lower(), date_added="2020-01-01T00:00:00+00:00"))

    with pytest.raises(KevDocumentError, match="more than one entry") as refused:
        catalog_in(body, source=AN_ANSWERING_SOURCE)

    assert AN_ADVISORY in str(refused.value)
    assert AN_ADVISORY.lower() in str(refused.value)


def test_an_alias_that_collides_with_another_entrys_identifier_is_refused_too() -> None:
    """The collision the alias contract makes newly possible, closed by the same rule.

    Without this an entry could claim another entry's advisory as its own alias, and
    the second one read would silently win -- a date chosen by document order.
    """
    body = _catalog(_entry(), _entry(ANOTHER_ADVISORY, aliases=[AN_ADVISORY]))

    with pytest.raises(KevDocumentError, match="more than one entry"):
        catalog_in(body, source=AN_ANSWERING_SOURCE)


def test_an_advisory_spelled_two_ways_is_still_one_advisory() -> None:
    """The keying folds case, which is what makes the refusal above reachable at all.

    Every catalogue that issues `CVE-2024-23334` issues one advisory, and a lookup
    on the verbatim string would miss a finding whose source spelled it differently.
    """
    catalog = catalog_in(_catalog(_entry()), source=AN_ANSWERING_SOURCE)

    assert AN_ADVISORY.lower().casefold() in catalog.entries
    assert AN_ADVISORY.upper().casefold() in catalog.entries


def test_a_recorded_advisory_identifier_keeps_the_case_the_catalog_used() -> None:
    """Folded for comparison and stored verbatim: normalising a recorded fact is rewriting it."""
    catalog = catalog_in(_catalog(_entry(AN_ADVISORY.lower())), source=AN_ANSWERING_SOURCE)

    (entry,) = catalog.entries.values()
    assert entry.advisory_id == AN_ADVISORY.lower()


def test_a_document_carrying_a_field_the_contract_does_not_define_is_refused() -> None:
    """A catalog that grew a truncation flag would otherwise be read as one that lists nothing."""
    body = json.dumps({ENTRIES_FIELD: [], "truncated": True})

    with pytest.raises(KevDocumentError, match="does not define"):
        catalog_in(body, source=AN_ANSWERING_SOURCE)


def test_the_document_contract_is_exactly_the_field_the_reader_reads() -> None:
    """One field, and no narrative one.

    The sibling reads a document-level `detail` because its document is an answer
    *about the package*; a catalog says nothing about our package, so a `detail`
    here would have no row to land on but every one of them. The module's own
    adapter contract has to say the same thing, and a first pass in which it did not
    would have had every document an adapter author wrote refused.
    """
    assert {ENTRIES_FIELD} == DOCUMENT_FIELDS


def test_the_adapter_contract_the_module_states_is_the_contract_the_reader_enforces() -> None:
    """The docstring is what an adapter author writes against, so it is swept rather than trusted.

    A docstring naming a field the reader refuses is not a documentation defect: it
    is every document that author writes being refused, and every package recording
    `error` until the source changes. Asserted as the *absence* of the field the
    first pass wrongly promised, and the presence of the two the contract has.
    """
    stated = kev_module.__doc__ or ""
    contract = stated.partition("## What a KEV source adapter must do")[2]

    assert contract
    assert f"`{ENTRIES_FIELD}`" in contract
    assert f"`{ADVISORY_ID_FIELD}`" in contract
    assert f"`{ALIASES_FIELD}`" in contract
    assert f"`{DATE_ADDED_FIELD}`" in contract
    assert "`detail` (a string, optional)" not in contract


def test_the_entry_contract_is_exactly_the_fields_the_reader_reads() -> None:
    """PRD Appendix A.2 gives this table two facts; `aliases` is how the first is matched, not a third."""
    assert {ADVISORY_ID_FIELD, ALIASES_FIELD, DATE_ADDED_FIELD} == ENTRY_FIELDS


def test_an_entry_carrying_a_field_the_contract_does_not_define_is_refused() -> None:
    """A silently dropped field is a source that believes it supplied one."""
    body = json.dumps({ENTRIES_FIELD: [{**_entry(), "required_action": "patch"}]})

    with pytest.raises(KevDocumentError, match="does not define"):
        catalog_in(body, source=AN_ANSWERING_SOURCE)


@pytest.mark.parametrize("stated", [OMITTED, None, "", "   ", 7], ids=["omitted", "null", "blank", "spaces", "int"])
def test_an_entry_that_names_no_advisory_is_refused(stated: Any) -> None:
    """An entry that names no advisory cannot be cross-referenced against anything."""
    with pytest.raises(KevDocumentError, match="names the advisory"):
        catalog_in(_catalog(_entry(stated)), source=AN_ANSWERING_SOURCE)


def test_a_date_of_the_wrong_type_is_refused_rather_than_read_as_a_date_that_would_not_parse() -> None:
    """A shape change and a malformed value are different, and only one is read past.

    A `date_added` this collector could not even attempt to read is a source whose
    shape has changed; one it attempted and could not is an entry with a blank date
    and a sentence.
    """
    with pytest.raises(KevDocumentError, match="rather than a string"):
        catalog_in(_catalog(_entry(date_added=1707177600)), source=AN_ANSWERING_SOURCE)


@pytest.mark.parametrize("body", ['["a"]', '"one"', "7", "null"], ids=["list", "string", "number", "null"])
def test_a_document_that_is_not_an_object_is_refused(body: str) -> None:
    """A source whose shape has changed is refused rather than read for whatever still parses."""
    with pytest.raises(KevDocumentError, match="rather than an object"):
        catalog_in(body, source=AN_ANSWERING_SOURCE)


@pytest.mark.parametrize("body", [None, 7, b"{}", ["{}"]], ids=["null", "int", "bytes", "list"])
def test_a_payload_whose_body_is_not_a_string_is_refused_by_name(body: Any) -> None:
    """A `Payload` is a value a third-party adapter built, so its body is checked rather than assumed.

    Left unchecked, `len(body)` raises a `TypeError` naming no source before the
    decode branch is reached -- so the branch documented for a body that is not a
    string was unreachable, and an adapter author meeting it got a message about a
    length rather than about their payload.
    """
    with pytest.raises(KevDocumentError, match="rather than a string"):
        catalog_in(body, source=AN_ANSWERING_SOURCE)


def test_a_body_that_is_not_json_is_refused_naming_the_source() -> None:
    """The gateway-error-page case, and the message names where it came from."""
    with pytest.raises(KevDocumentError, match="readable KEV catalog") as refused:
        catalog_in("<html>gateway timeout</html>", source=AN_ANSWERING_SOURCE)

    assert AN_ANSWERING_SOURCE in str(refused.value)


def test_a_deeply_nested_document_is_refused_rather_than_crashing_the_worker() -> None:
    """A nested body is refused, and the refusal is a `KevDocumentError` however it is reached.

    **Which** refusal fires is a property of the interpreter's stack, not of this module, so it
    is deliberately not asserted -- the three sibling collectors state the guarantee the same
    way for the same reason. `json.loads` recurses per level, so on a platform whose limit the
    nesting exceeds the body raises `RecursionError` and this module refuses it as unreadable;
    on a platform where the parse completes, the result is a list rather than an object and the
    shape check refuses it instead. Both are the guarantee this case is about: a document this
    module cannot read is refused rather than allowed to take the worker down with it.
    Asserting the recursion message pinned one platform's answer and failed on Linux.
    """
    with pytest.raises(KevDocumentError):
        catalog_in("[" * 200_000, source=AN_ANSWERING_SOURCE)


def test_a_document_larger_than_the_ceiling_is_refused_before_it_is_decoded() -> None:
    """The bound protects the parse, which is where a worker's soft time limit would go."""
    body = " " * (MAX_CATALOG_CHARACTERS + 1)

    with pytest.raises(KevDocumentError, match="decodes at most"):
        catalog_in(body, source=AN_ANSWERING_SOURCE)


@pytest.mark.parametrize("stated", ['{"a": 1}', '"one"', "7"], ids=["object", "string", "number"])
def test_an_entry_list_that_is_not_a_list_is_refused(stated: str) -> None:
    """A source whose shape has changed is refused rather than read past."""
    with pytest.raises(KevDocumentError, match="rather than a list"):
        catalog_in(f'{{"{ENTRIES_FIELD}": {stated}}}', source=AN_ANSWERING_SOURCE)


def test_an_entry_that_is_not_an_object_is_refused_naming_where_it_sat() -> None:
    """A refusal that named no position would leave a reader scanning a catalog by eye."""
    body = json.dumps({ENTRIES_FIELD: [_entry(), "CVE-2024-99999"]})

    with pytest.raises(KevDocumentError, match="at position 1"):
        catalog_in(body, source=AN_ANSWERING_SOURCE)


def test_more_entries_than_this_collector_reads_is_refused_rather_than_truncated() -> None:
    """Reading the first `MAX_ENTRIES` would record that listed advisories are not listed.

    Which is the one answer on this table that reads as reassuring, so the whole
    document is refused instead.
    """
    stated = [{ADVISORY_ID_FIELD: f"CVE-2024-{index:06d}"} for index in range(MAX_ENTRIES + 1)]
    body = json.dumps({ENTRIES_FIELD: stated})

    with pytest.raises(KevDocumentError, match="reads at most"):
        catalog_in(body, source=AN_ANSWERING_SOURCE)


def test_an_advisory_identifier_wider_than_the_column_that_stores_one_is_refused() -> None:
    """Measured against `vulnerability_findings`, which is the table that stores an identifier.

    An identifier wider than that column is one no vulnerability finding could ever
    carry, so it could never match anything -- and holding it would be this module
    keeping a value the product has already decided is not an advisory identifier.
    That read couples this module to the sibling table's *schema* as well as to its
    rows, which `CPM-SECURITY-S02`'s Spec Change Log names.
    """
    width = int(VulnerabilityFinding._meta.get_field("advisory_id").max_length)  # noqa: SLF001 - Django's own API

    with pytest.raises(KevDocumentError, match="the column that holds it takes"):
        catalog_in(_catalog(_entry("C" * (width + 1))), source=AN_ANSWERING_SOURCE)


def test_an_advisory_identifier_carrying_a_control_character_is_refused_where_it_enters() -> None:
    """PostgreSQL refuses a NUL from the driver, outside the guard that would record the failure."""
    with pytest.raises(KevDocumentError, match="control character"):
        catalog_in(_catalog(_entry("CVE-2024-\x00 23334")), source=AN_ANSWERING_SOURCE)


def test_a_source_locator_wider_than_its_column_is_refused_before_an_entry_is_read() -> None:
    """The locator an adapter recorded lands on a row, so it is checked before anything is built."""
    width = int(KevFinding._meta.get_field("source").max_length)  # noqa: SLF001 - Django's own API

    with pytest.raises(KevDocumentError, match="the column that holds it takes"):
        catalog_in(_catalog(_entry()), source="k" * (width + 1))


def test_a_column_with_no_declared_width_is_refused_rather_than_left_unguarded() -> None:
    """A width guard that quietly stops guarding is worse than one that is absent.

    A field renamed, or one turned into a `TextField`, would otherwise silently turn
    its refusal off with nothing anywhere failing -- and the consequence is a value
    stored on SQLite and a failed run in the gate (`R-5`). `detail` is the real
    `TextField` on this model, so the refusal is reachable without inventing one.
    """
    with pytest.raises(CollectorConfigurationError, match="declares no max_length"):
        kev_module._column_width("detail")  # noqa: SLF001 - the guard under test


def test_a_sentinel_reason_is_cleaned_and_shortened_rather_than_refused() -> None:
    """The opposite posture from every guard above, and the path is the reason.

    A sentinel row is written where a failure is already being recorded and
    `CPM-NFR-3` requires a row, and the reason arriving there is the base's own
    sentence with a third party's exception message inside it. Raising over its
    shape would turn "the source failed" into "no row at all".
    """
    cleaned = kev_module._safe_detail("TransportError: bad\x00gateway\n")  # noqa: SLF001 - the guard under test
    shortened = kev_module._safe_detail("t" * (MAX_SENTINEL_DETAIL_CHARACTERS + 1))  # noqa: SLF001 - as above

    assert "\x00" not in cleaned
    assert "\n" not in cleaned
    assert "bad gateway" in cleaned
    assert shortened.endswith(SHORTENED_DETAIL)
    assert len(shortened) < MAX_SENTINEL_DETAIL_CHARACTERS + len(SHORTENED_DETAIL) + THREE_ANSWERS


# ---------------------------------------------------------------------------
# The cross-reference itself, which is AC 1's rule.
# ---------------------------------------------------------------------------


def test_a_listed_advisory_is_a_determinate_answer_carrying_the_catalog_date() -> None:
    """AC 1 as a pure function: the link to the finding, and the catalog date added."""
    catalog = catalog_in(_catalog(_entry()), source=AN_ANSWERING_SOURCE)

    (answer,) = cross_reference([_finding()], catalog)

    assert answer.finding_id == A_FINDING
    assert answer.package_id == A_PACKAGE
    assert answer.state == LISTED
    assert answer.catalog_date_added == A_CATALOG_INSTANT
    assert answer.detail == ""


def test_an_advisory_the_catalog_does_not_list_is_an_established_negative_that_says_so() -> None:
    """`not_listed`, with a sentence saying it is not a statement that the package is clear.

    Claimed only because the catalog states an advisory in the finding's own scheme:
    it had the vocabulary to list this one and did not.
    """
    catalog = catalog_in(_catalog(_entry(ANOTHER_CVE)), source=AN_ANSWERING_SOURCE)

    (answer,) = cross_reference([_finding()], catalog)

    assert answer.state == NOT_LISTED
    assert answer.catalog_date_added is None
    assert answer.detail == NOT_LISTED_DETAIL


def test_an_advisory_in_a_scheme_the_catalog_never_uses_is_unknown_rather_than_not_listed() -> None:
    """The reassuring value withheld where it cannot honestly be established.

    A catalog of CVE identifiers has nothing to say about a `GHSA-` finding it never
    had the vocabulary to list, and `not_listed` there would be an established
    negative the run did not establish -- permanently, about whether something is
    being exploited. The row still links to its finding, because it is about that
    advisory and a reader has to know which.
    """
    catalog = catalog_in(_catalog(_entry()), source=AN_ANSWERING_SOURCE)

    (answer,) = cross_reference([_finding(A_FINDING, ANOTHER_ADVISORY)], catalog)

    assert answer.state == KEV_UNKNOWN
    assert answer.finding_id == A_FINDING
    assert answer.detail == UNKNOWN_SCHEME_DETAIL


def test_an_alias_the_catalog_states_makes_a_cross_scheme_finding_a_real_answer() -> None:
    """The other half of the aliasing fix, and the reason the contract carries aliases at all.

    The same GHSA finding, against a catalog that states the GHSA spelling as an
    alias of its CVE entry, is `listed` with that entry's date -- rather than the
    `unknown` above or, worse, the `not_listed` an unaliased exact match produced
    before.
    """
    catalog = catalog_in(_catalog(_entry(aliases=[ANOTHER_ADVISORY])), source=AN_ANSWERING_SOURCE)

    (answer,) = cross_reference([_finding(A_FINDING, ANOTHER_ADVISORY)], catalog)

    assert answer.state == LISTED
    assert answer.catalog_date_added == A_CATALOG_INSTANT


def test_an_identifier_carrying_no_scheme_at_all_fails_toward_unknown() -> None:
    """The rule is a prefix convention rather than a registry, so it must fail safe.

    An identifier with no separator answers with itself, matches no catalog scheme,
    and produces `unknown` -- never the reassuring value.
    """
    catalog = catalog_in(_catalog(_entry()), source=AN_ANSWERING_SOURCE)

    (answer,) = cross_reference([_finding(A_FINDING, "2024-23334")], catalog)

    assert answer.state == KEV_UNKNOWN


def test_an_empty_catalog_answers_unknown_rather_than_not_listed() -> None:
    """A catalog that lists nothing states no scheme, so it can contradict nothing.

    This is the case a reader is most likely to expect the reassuring value from,
    and it is exactly the case where the reassuring value would be least earned.
    """
    (answer,) = cross_reference([_finding()], Catalog(entries={}, schemes=frozenset()))

    assert answer.state == KEV_UNKNOWN


def test_three_advisories_of_which_two_are_listed_are_three_answers_each_linked_to_its_own_finding() -> None:
    """The matrix's plural row: three answers, never merged, and no answer links to two findings."""
    catalog = catalog_in(_catalog(_entry(), _entry(ANOTHER_CVE)), source=AN_ANSWERING_SOURCE)
    findings = [
        _finding(A_FINDING, AN_ADVISORY),
        _finding(ANOTHER_FINDING, ANOTHER_CVE),
        _finding(A_THIRD_FINDING, A_THIRD_CVE),
    ]

    answers = cross_reference(findings, catalog)

    assert len(answers) == THREE_ANSWERS
    assert [answer.finding_id for answer in answers] == [A_FINDING, ANOTHER_FINDING, A_THIRD_FINDING]
    assert [answer.state for answer in answers] == [LISTED, LISTED, NOT_LISTED]


def test_a_finding_and_a_catalog_that_spell_one_advisory_differently_still_match() -> None:
    """The lookup folds case on both sides, which is what stops a spelling becoming a false negative.

    A `not_listed` row written because two systems capitalised an identifier
    differently is the worst answer this table can give: it is permanent, it reads
    as reassuring, and nothing about it looks wrong.
    """
    catalog = catalog_in(_catalog(_entry(AN_ADVISORY.lower())), source=AN_ANSWERING_SOURCE)

    (answer,) = cross_reference([_finding(A_FINDING, AN_ADVISORY.upper())], catalog)

    assert answer.state == LISTED


def test_a_listed_advisory_whose_date_could_not_be_read_carries_the_reason_rather_than_a_date() -> None:
    """The row is still determinate -- the catalog lists it -- and the date is missing with a reason."""
    catalog = catalog_in(_catalog(_entry(date_added="tomorrow")), source=AN_ANSWERING_SOURCE)

    (answer,) = cross_reference([_finding()], catalog)

    assert answer.state == LISTED
    assert answer.catalog_date_added is None
    assert answer.detail.startswith(UNREADABLE_CATALOG_DATE_DETAIL)


def test_a_package_with_no_current_finding_produces_no_cross_reference_at_all() -> None:
    """Having nothing to cross-reference is a statement about our evidence, not about the catalog.

    So the pure function answers with nothing and `translate` writes the `unknown`
    row itself -- which is what keeps a catalog's document from deciding what a row
    about our own missing evidence says.
    """
    assert cross_reference([], catalog_in(_catalog(_entry()), source=AN_ANSWERING_SOURCE)) == ()


def test_a_run_that_excluded_stale_observations_says_so_and_one_that_did_not_says_nothing() -> None:
    """The clause every row of the run carries, and the reason it is on every row.

    A reader holds one row, not a run, so a row computed against a partial view must
    say so wherever it is read. The empty half matters as much: a clause on every
    row of every run would be noise nobody reads.
    """
    assert stale_clause(0) == ""
    assert str(TWO_EXCLUDED) in stale_clause(TWO_EXCLUDED)
    assert str(KEV_FRESHNESS_TARGET) in stale_clause(TWO_EXCLUDED)


# ---------------------------------------------------------------------------
# The value objects enforce what they claim.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("finding_id", "package_id", "advisory_id"),
    [(0, A_PACKAGE, AN_ADVISORY), (A_FINDING, 0, AN_ADVISORY), (A_FINDING, A_PACKAGE, "")],
    ids=["no-finding", "no-package", "no-advisory"],
)
def test_a_current_finding_missing_any_of_its_three_facts_is_refused(
    finding_id: int,
    package_id: int,
    advisory_id: str,
) -> None:
    """A cross-reference derives from one finding, is about one advisory, and belongs to one package.

    The package is carried rather than taken from the run, which is what makes a row
    pairing one package with another's observation unreachable from this writer --
    see `KevFinding.save` for why that invariant cannot be a check constraint.
    """
    with pytest.raises(CollectorConfigurationError, match="leaves one of its three facts empty"):
        CurrentFinding(finding_id=finding_id, package_id=package_id, advisory_id=advisory_id)


@pytest.mark.parametrize(
    ("date_added", "fault"),
    [(A_CATALOG_INSTANT, "and also a reason"), (None, "")],
    ids=["both", "neither"],
)
def test_a_catalog_entry_that_sets_both_or_neither_of_its_date_and_its_reason_is_refused(
    date_added: datetime | None,
    fault: str,
) -> None:
    """A docstring is not enforcement.

    An entry carrying neither would make a `listed` row whose `detail` says nothing
    about why its date column is empty -- which the model's own docstring promises
    it does.
    """
    with pytest.raises(CollectorConfigurationError, match="exactly one is set"):
        CatalogEntry(advisory_id=AN_ADVISORY, date_added=date_added, fault=fault)


def test_a_cross_reference_may_not_carry_a_state_a_catalog_cannot_produce() -> None:
    """Three answers a lookup can reach, and the three sentinels are the base's, never a reader's."""
    with pytest.raises(CollectorConfigurationError, match="is none of"):
        CrossReference(
            finding_id=A_FINDING,
            package_id=A_PACKAGE,
            state=OutcomeState.ERROR.value,
            catalog_date_added=None,
            detail="a reason",
        )


@pytest.mark.parametrize("state", [NOT_LISTED, KEV_UNKNOWN], ids=[NOT_LISTED, KEV_UNKNOWN])
def test_a_cross_reference_that_is_not_listed_may_not_carry_a_catalog_date(state: str) -> None:
    """A date is something only a listed advisory has.

    On `not_listed` a row carrying one would say the catalog both does and does not
    list the advisory; on `unknown` it would be a date from a catalog that has
    nothing to say about the identifier at all.
    """
    with pytest.raises(CollectorConfigurationError, match="only a listed advisory has"):
        CrossReference(
            finding_id=A_FINDING,
            package_id=A_PACKAGE,
            state=state,
            catalog_date_added=A_CATALOG_INSTANT,
            detail=NOT_LISTED_DETAIL,
        )


@pytest.mark.parametrize(
    ("catalog_date_added", "detail"),
    [(A_CATALOG_INSTANT, "a reason"), (None, "")],
    ids=["both", "neither"],
)
def test_a_cross_reference_states_either_a_date_or_the_reason_it_has_none(
    catalog_date_added: datetime | None,
    detail: str,
) -> None:
    """The half worth enforcing is the second: a blank date with no reason is a shrug.

    The model's docstring promises that `detail` says which of the two ways a
    `listed` row's date is missing, and a row that carried neither would break that
    promise in a table nothing may correct.
    """
    with pytest.raises(CollectorConfigurationError, match="Exactly one is set"):
        CrossReference(
            finding_id=A_FINDING,
            package_id=A_PACKAGE,
            state=LISTED,
            catalog_date_added=catalog_date_added,
            detail=detail,
        )


# ---------------------------------------------------------------------------
# The sentinel rows and the hooks the base calls.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [OutcomeState.ERROR, OutcomeState.NOT_FOUND],
    ids=[OutcomeState.ERROR.value, OutcomeState.NOT_FOUND.value],
)
def test_a_sentinel_row_carries_the_state_and_derives_from_no_finding(state: OutcomeState) -> None:
    """`CPM-AD-24`: the value is carried verbatim, and the link and the date are both null.

    They are the half the table's own constraint would otherwise have to catch at
    insert, several frames from the call that was wrong -- a sentinel row is written
    for a call that produced no catalog at all, so it derives from nothing.
    """
    collector = KevCollector(clock=_stopped_clock())

    try:
        row = collector.sentinel_evidence(
            state=state,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="something happened",
        )
    finally:
        collector.close()

    assert row.state == state.value
    assert row.package_id == A_PACKAGE
    assert row.observed_at == FIXED_INSTANT
    assert row.source == KEV_SOURCE_LOCATOR
    assert row.vulnerability_finding_id is None
    assert row.catalog_date_added is None


def test_the_absent_locator_row_says_it_is_not_a_package_with_nothing_exploited_against_it() -> None:
    """The one row in this table a reader could mistake for reassuring, and it says so itself.

    On every sibling table `not_found` means the observed thing is not there; here
    the base reaches it when the source says the *locator* is not there. The base
    cannot know the difference, so the collector appends the caveat rather than
    leaving it to be inferred -- and the base's own reason survives in front of it.
    """
    collector = KevCollector(clock=_stopped_clock())

    try:
        absent = collector.sentinel_evidence(
            state=OutcomeState.NOT_FOUND,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="the source reports that the resource does not exist",
        )
        failed = collector.sentinel_evidence(
            state=OutcomeState.ERROR,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="the source reports that the resource does not exist",
        )
    finally:
        collector.close()

    assert absent.detail.startswith("the source reports that the resource does not exist")
    assert UNKNOWN_LOCATOR_DETAIL in absent.detail
    # And the caveat is about absence rather than about failure: an `error` row is
    # nobody's idea of reassuring and does not carry it.
    assert UNKNOWN_LOCATOR_DETAIL not in failed.detail


def test_a_declared_source_reporting_the_catalog_absent_says_so_in_the_log_as_well() -> None:
    """The silence a *declared* source produces, which the other event cannot cover.

    `NO_KEV_SOURCE_EVENT` fires when the adapter *slot* is empty. This one fires
    when the slot is full and the catalog is not there: the base writes `not_found`
    and finalizes the run **`succeeded`**, because the source answered -- so a
    withdrawn or misconfigured catalog produces a full day of clean-looking runs
    with nothing else in the log at all.

    Emitted once per package rather than once per dispatch, which is noisier than
    the other by design: it is the failure a reader of the rows would most easily
    mistake for an answer.
    """
    collector = KevCollector(clock=_stopped_clock())

    try:
        with capture_logs() as captured:
            collector.sentinel_evidence(
                state=OutcomeState.NOT_FOUND,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="the source reports that the resource does not exist",
            )
            collector.sentinel_evidence(
                state=OutcomeState.ERROR,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="TransportError: unreachable",
            )
    finally:
        collector.close()

    events = [entry for entry in captured if entry["event"] == CATALOG_ABSENT_EVENT]

    (absent,) = events
    assert absent["log_level"] == "warning"
    assert absent["collector"] == COLLECTOR_NAME
    assert absent["package_id"] == A_PACKAGE
    assert absent["source"] == KEV_SOURCE_LOCATOR
    assert "withdrawn or misconfigured" in absent["detail"]


def test_a_sentinel_reason_reaches_the_row_cleaned_rather_than_verbatim() -> None:
    """The `error` path carries a third party's exception message onto an append-only row.

    Every other value this module stores passes a control-character guard that
    raises; this one cannot, because raising here is the one outcome `CPM-NFR-3`
    forbids -- so it is cleaned instead, and a case pins that rather than leaving it
    to the driver.
    """
    collector = KevCollector(clock=_stopped_clock())

    try:
        row = collector.sentinel_evidence(
            state=OutcomeState.ERROR,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="TransportError: bad\x00gateway",
        )
    finally:
        collector.close()

    assert "\x00" not in row.detail
    assert "bad gateway" in row.detail


@pytest.mark.parametrize(
    "state",
    [OutcomeState.OK, OutcomeState.UNKNOWN, OutcomeState.NOT_APPLICABLE],
    ids=[OutcomeState.OK.value, OutcomeState.UNKNOWN.value, OutcomeState.NOT_APPLICABLE.value],
)
def test_a_sentinel_state_this_collector_has_no_row_for_is_refused(state: OutcomeState) -> None:
    """Refused at the call rather than at the insert, which is where the constraint would catch it.

    `ok` because it is not in this vocabulary at all, which is the whole of why the
    vocabulary is composed; `unknown` because that row is `translate`'s to write
    with the reason the run established, not the base's reason for a state the base
    never decides; `not_applicable` because a KEV question applies to every package.
    """
    collector = KevCollector(clock=_stopped_clock())

    try:
        with pytest.raises(CollectorConfigurationError, match="shapes a sentinel row for"):
            collector.sentinel_evidence(
                state=state,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="",
            )
    finally:
        collector.close()


def test_the_plural_sentinel_hook_is_the_bases_because_one_surface_owes_one_row() -> None:
    """`CPM-CURRENCY-S04`'s hook exists for a collector that owes several rows; this one does not.

    A run writes one row per *current advisory*, which is several -- but a sentinel
    path is reached when the catalog produced no answer at all, and there is exactly
    one thing to say about that. Asserted by identity rather than by counting rows,
    because an override that happened to return one row would pass a count and would
    still be a second place to keep in step with the base.
    """
    assert KevCollector.sentinel_evidence_rows is Collector.sentinel_evidence_rows


def test_the_applicability_hook_is_the_bases_because_the_question_applies_to_every_package() -> None:
    """Not overridden, and the omission is the decision.

    The sibling overrides it to forget a run's remembered identity; nothing here is
    remembered on the instance, so an override would be a hook that exists to
    restate a default. A package with nothing to cross-reference is deliberately not
    answered through it either -- that would write `not_applicable`, and what is
    missing is our own evidence rather than the question's relevance.
    """
    assert KevCollector.inapplicability is Collector.inapplicability
    assert KevCollector(clock=_stopped_clock()).inapplicability(package_id=A_PACKAGE) == ""


def test_the_locator_is_the_same_question_whichever_package_is_being_collected() -> None:
    """The catalog is one document about advisories, so there is nothing of a package's in it.

    What varies between runs is which of *our* findings are cross-referenced against
    the answer, and that is read inside `translate` from this product's own evidence.
    """
    collector = KevCollector(clock=_stopped_clock())

    try:
        assert collector.source_for(package_id=A_PACKAGE) == KEV_SOURCE_LOCATOR
        assert collector.source_for(package_id=A_PACKAGE + 1) == KEV_SOURCE_LOCATOR
    finally:
        collector.close()


def test_an_unsaved_finding_renders_its_absences_rather_than_raising() -> None:
    """A `__str__` that raised would break a debugger and a traceback alike."""
    rendered = str(KevFinding())

    assert "no vulnerability finding" in rendered
    assert "no package" in rendered
    assert "never" in rendered


def test_a_kev_findings_rendering_names_the_finding_it_derives_from() -> None:
    """The fact a reviewer scanning a log is looking for: which observation this came from."""
    rendered = str(
        KevFinding(
            observed_at=FIXED_INSTANT,
            package_id=A_PACKAGE,
            vulnerability_finding_id=A_FINDING,
            state=LISTED,
        ),
    )

    assert str(A_FINDING) in rendered
    assert str(A_PACKAGE) in rendered
    assert LISTED in rendered
    assert FIXED_INSTANT.isoformat() in rendered


# ---------------------------------------------------------------------------
# The selection, and the one event an undeclared component emits.
# ---------------------------------------------------------------------------


def test_an_undeclared_component_says_so_in_the_log_rather_than_only_in_an_empty_selection() -> None:
    """A `succeeded` dispatch over an empty selection is byte-identical to a healthy day.

    So the only way to learn that this component has stopped cross-referencing --
    or that somebody withdrew its source from a running process -- is a line it
    emits itself. `docs/deployment.md` tells an operator to alert on this event by
    name.
    """
    with capture_logs() as captured:
        selected = list(KevCollector.selectable_packages())

    events = [entry for entry in captured if entry["event"] == NO_KEV_SOURCE_EVENT]

    assert selected == []
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["collector"] == COLLECTOR_NAME
    assert "declared KEV source" in events[0]["detail"]


def test_asking_for_the_empty_selection_says_nothing_until_something_draws_it() -> None:
    """The laziness is what keeps this line out of every start-up reconciliation.

    `cadence_reconciliation_fault` asks every registered collector for its selection
    and only tests whether it is `None`, so a warning emitted where the selection is
    *built* would land inside every boot -- including the refusals
    `tests/integration/startup/test_stage_two_served_path.py` asserts emit nothing in
    place of raising, where a stray event is indistinguishable from a condition that
    logged instead of refusing.
    """
    with capture_logs() as captured:
        selection = KevCollector.selectable_packages()

    assert selection is not None
    assert [entry for entry in captured if entry["event"] == NO_KEV_SOURCE_EVENT] == []


def test_a_declared_component_selects_without_saying_anything() -> None:
    """The anti-vacuity half: the event is about the undeclared state and not about every dispatch."""
    declare_kev_source(RecordedTransport())

    with capture_logs() as captured:
        # Built rather than drawn: a declared component's selection is a queryset
        # and drawing it here would need a database, which this tier has none of.
        selection = KevCollector.selectable_packages()

    assert selection is not None
    assert [entry for entry in captured if entry["event"] == NO_KEV_SOURCE_EVENT] == []


def test_the_collector_never_closes_the_adapter_it_was_handed() -> None:
    """The adapter is process-global and outlives every run (`CPM-AD-29`).

    `Collector.close()` releases only a transport the base built, and this collector
    is always handed one -- so a run that closed it would take the declared source
    away from every later collection in the worker, and the failure would appear one
    package later with nothing pointing back here.
    """
    adapter = RecordedTransport()
    declare_kev_source(adapter)

    with KevCollector(clock=_stopped_clock(), transport=kev_source()) as collector:
        assert collector._transport is adapter  # noqa: SLF001 - the seam under test

    assert declared_kev_source() is adapter
    assert not hasattr(adapter, "closed")


# ---------------------------------------------------------------------------
# The module's own source -- including the one read CPM-AD-7 does not grant.
# ---------------------------------------------------------------------------


def test_the_collector_module_writes_no_row_of_any_kind() -> None:
    """The half of the `CPM-AD-7` exception that is not taken, asserted rather than promised.

    `CPM-SECURITY-S02`'s Spec Change Log takes a *read* of one table, read-only. A
    write anywhere in this module -- to `vulnerability_findings` or to its own table
    -- would be a second evidence writer beside the base's (`CPM-AD-7`,
    `CPM-AD-14`), and it is the failure a reader of that exception should be able to
    rule out mechanically.
    """
    written = sorted(
        node.lineno
        for node in ast.walk(parse(_kev_module()))
        if isinstance(node, ast.Call) and dotted_name(node.func).rpartition(".")[2] in WRITE_METHODS
    )

    assert written == [], f"the collector reaches a table directly at lines {written}"


def test_the_collector_module_reads_the_two_models_the_exception_permits_and_no_third() -> None:
    """The anti-vacuity half, and the whole of the exception's scope.

    `CPM-AD-7` is "a collector writes its own evidence table and reads only
    `identity`", and this one also reads `vulnerability_findings` -- one table,
    read-only, for the advisories to cross-reference. Both names are asserted
    *present*, because a module that named neither would sweep clean; and the other
    evidence models are asserted absent, because the exception is for one table and
    a second read would be one nothing argued for.

    **Three evasions are closed rather than left to the bare-name scan**, because a
    scan that collected `ast.Name` alone would sweep clean over all three: a model
    fetched by string through `apps.get_model`, a model named as a string anywhere
    at all, and a related manager traversed off a `Package` instance -- which reads
    another collector's table without ever naming its class. What is *not* closed is
    a name assembled at run time from parts; that is stated rather than defended,
    because a scan cannot see it and `tests/unit/django_apps/test_collector_base_audit.py`
    holds the repository-wide licence that would have to be amended for a second
    reader either way.
    """
    tree = parse(_kev_module())
    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    called = {dotted_name(node.func).rpartition(".")[2] for node in ast.walk(tree) if isinstance(node, ast.Call)}

    assert PACKAGE_MODEL_NAME in named
    assert VULNERABILITY_MODEL_NAME in named
    assert "get_model" not in called
    for beyond in ("InventorySnapshot", "SourceReleaseSnapshot", "PyPIReleaseSnapshot", "FeedstockSnapshot"):
        assert beyond not in named | attributes | strings, beyond
    for traversal in ("inventory_snapshots", "source_release_snapshots", "pypi_release_snapshots"):
        assert traversal not in attributes | strings, traversal
    # The one this module could most plausibly reach for: `package.vulnerability_findings`
    # is the same read through a relation, and it would name no model at all.
    assert "vulnerability_findings" not in attributes


def test_the_collector_module_does_not_re_export_the_outcome_vocabulary() -> None:
    """`collectors/outcomes.py` argues that binding the type once is load-bearing.

    `outcome_type` mints a distinct class on every call, so the vocabulary is bound
    once at module scope and imported from there. A re-export is a second name for
    it that a reader can import instead -- and the first pass re-exported four of
    the six values, which is worse than none: a caller reaching for the fifth
    through this module would find nothing and conclude it did not exist.
    """
    exported = set(kev_module.__all__)

    assert "KevOutcome" not in exported
    for value in ("LISTED", "NOT_LISTED", "KEV_UNKNOWN"):
        assert value not in exported, value


def test_the_collector_module_opens_no_transaction_of_its_own() -> None:
    """The per-package transaction is the base's, around the evidence write (`CPM-AD-23`)."""
    opened = sorted(
        node.lineno
        for node in ast.walk(parse(_kev_module()))
        if isinstance(node, ast.Call) and dotted_name(node.func).endswith("transaction.atomic")
    )

    assert opened == []


def test_the_collector_module_imports_no_other_collector_and_no_config() -> None:
    """`CPM-AD-7`'s import rule and inherited `AD-4`, asserted rather than assumed.

    The exception this story takes is a *read*, not a dependency between collector
    modules: the evidence model is reached through `collectors/models.py`, which
    every collector already imports, and `collectors/vulnerability.py` is never
    imported. That distinction is the whole of what the Spec Change Log claims, so it
    is the one asserted here.
    """
    imported = {
        node.module
        for node in ast.walk(parse(_kev_module()))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    siblings = (".source_release", ".pypi_release", ".feedstock", ".conda_package", ".vulnerability", ".tasks")

    assert not any(module.endswith(siblings) for module in imported), imported
    assert not any(module == "config" or module.startswith("config.") for module in imported), imported
    assert any(module.endswith(".collectors.models") for module in imported)
    assert any(module.endswith(".collectors.agent") for module in imported)


def test_the_collector_module_names_no_kev_source_of_its_own() -> None:
    """PRD Open Question 1, as a property of the source text rather than a promise in prose.

    A hostname, an API path or a catalogue's name appearing here would be this module
    answering the question the epic says blocks it -- and it would be an answer a
    reader of the declarations would never see, because the adapter slot would still
    look empty.
    """
    source = _kev_module().read_text(encoding="utf-8").lower()

    for named_source in ("cisa.gov", "known_exploited_vulnerabilities", "nvd.nist.gov", "vulncheck", "api.first.org"):
        assert named_source not in source, named_source


def test_no_shipped_module_declares_a_kev_source_unless_it_is_licensed_here() -> None:
    """PRD Open Question 1, as a property of the source tree.

    A `declare_kev_source(...)` call anywhere under `src/` is a source somebody
    chose, wherever they wrote it -- and every application lives under `src/`, so a
    deployment that declares one meets this case by design. It is a *licensed* set
    rather than a flat ban for exactly that reason: a rule that could not be
    satisfied would be deleted rather than amended, and the amendment is the record
    of which catalog was chosen.
    """
    calling = sorted(
        f"{path.relative_to(SRC_ROOT)}:{node.lineno}"
        for path in SRC_ROOT.rglob("*.py")
        if str(path.relative_to(SRC_ROOT)) not in MODULES_PERMITTED_TO_DECLARE_A_KEV_SOURCE
        for node in ast.walk(parse(path))
        if isinstance(node, ast.Call) and dotted_name(node.func).rpartition(".")[2] == "declare_kev_source"
    )

    assert calling == [], f"a KEV source is declared at {calling}"


def test_this_repository_licenses_no_module_to_declare_a_kev_source() -> None:
    """The anti-vacuity half: the set is empty, so the sweep above is not licensing everything."""
    assert frozenset() == MODULES_PERMITTED_TO_DECLARE_A_KEV_SOURCE


def test_only_determinate_vulnerability_rows_are_read_as_current() -> None:
    """The filter is the one the sibling table's own constraint makes necessary.

    A vulnerability row carrying `unknown`, `error` or `not_found` names no advisory
    at all -- `vulnerability_findings` refuses one that does -- so there is nothing
    in it to cross-reference, and reading one would produce a `CurrentFinding` with a
    blank identifier that its own invariant refuses. Asserted against the sibling
    module's constant rather than the string, so a renamed determinate value fails
    here rather than silently reading nothing.
    """
    source = _kev_module().read_text(encoding="utf-8")

    assert "state=MATCHED" in source
    assert MATCHED == "matched"
