"""Inventory ingestion's declarations, its record contract, and what its module may not do.

`CPM-AD-25` makes the inventory an observation like any other, and the two halves
of that sentence fail in different places. What the *collector* declares -- the
nine `ClassVar`s, the adapter it will and will not read through, what a record
has to be -- is decided before a run exists, so it is decided here, with no
database and no socket. What happens once a run does exist is
`tests/integration/django_apps/test_inventory_ingestion.py`'s, because writing a
snapshot needs a real table and opening the recorder needs a real ledger.

**Three of the rules here are structural, and they are the ones nothing at run
time would report.** The collector must never write the package table
(`CPM-AD-14`, `CPM-AD-25`); no transaction may span more than one package
(`CPM-AD-23`); and the resolution service must actually be the thing it calls.
A behavioural case cannot show the first two: rows land either way, and a
transaction that wrapped the whole sweep would pass every single-package
assertion in the integration tier. So the module's own source is parsed and
swept, in the same shape `tests/unit/django_apps/test_collector_base_audit.py`
sweeps `src/` -- and each sweep is paired with an anti-vacuity case, because a
detector that had stopped detecting looks exactly like a module that is clean.

**The record contract's refusals are all here, and all of them are `CPM-FR-42`'s
"no run partially ingests a malformed source".** The document is decoded in full
before the first write, so every one of these is reachable with no database:
a body that is not a list of objects, a record naming no package, a missing
required signal, a signal that is not a count, a field the contract does not
define, and one key named twice.

**The base's own sweep path is measured here too**, for the reason
`tests/unit/django_apps/test_collection.py` measures the per-package
declarations: `sweep_source` and `persist_sweep` are refusals a collector meets
before any run opens, and the window query a sweep asks is a `Q` whose shape is
one keyword away from asking about the wrong runs.

No database, no network: nothing here saves a row, no queryset is evaluated, and
every transport is a recorded fake.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.apps import apps
from django.db import connection

from conda_package_supply_chain_monitor.collectors.models import SNAPSHOT_KEY_INDEX
from conda_package_supply_chain_monitor.collectors.models import SNAPSHOT_READ_INDEX
from conda_package_supply_chain_monitor.collectors.models import InventorySnapshot
from conda_package_supply_chain_monitor.collectors.tasks import COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.tasks import INGEST_TASK_NAME
from conda_package_supply_chain_monitor.collectors.tasks import INVENTORY_SOURCE
from conda_package_supply_chain_monitor.collectors.tasks import MAX_COUNT
from conda_package_supply_chain_monitor.collectors.tasks import OPTIONAL_SIGNALS
from conda_package_supply_chain_monitor.collectors.tasks import PACKAGE_NAME
from conda_package_supply_chain_monitor.collectors.tasks import RECORD_FIELDS
from conda_package_supply_chain_monitor.collectors.tasks import REQUIRED_SIGNALS
from conda_package_supply_chain_monitor.collectors.tasks import SOURCE_PACKAGE_KEY
from conda_package_supply_chain_monitor.collectors.tasks import InventoryAdapterError
from conda_package_supply_chain_monitor.collectors.tasks import InventoryIngestionCollector
from conda_package_supply_chain_monitor.collectors.tasks import InventoryRecord
from conda_package_supply_chain_monitor.collectors.tasks import InventoryRecordError
from conda_package_supply_chain_monitor.collectors.tasks import declare_inventory_adapter
from conda_package_supply_chain_monitor.collectors.tasks import declared_inventory_adapter
from conda_package_supply_chain_monitor.collectors.tasks import ingest_inventory
from conda_package_supply_chain_monitor.collectors.tasks import inventory_adapter
from conda_package_supply_chain_monitor.collectors.tasks import records_in
from conda_package_supply_chain_monitor.collectors.tasks import withdraw_inventory_adapter
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.collection import NO_CACHE
from conda_package_supply_chain_monitor.core.collection import NO_WINDOW
from conda_package_supply_chain_monitor.core.collection import CollectorConfigurationError
from conda_package_supply_chain_monitor.core.collection import SweepOutcome
from conda_package_supply_chain_monitor.core.collection import window_query
from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.rate_limit import RateLimit
from conda_package_supply_chain_monitor.core.registry import registrations
from conda_package_supply_chain_monitor.core.transport import MAX_TIMEOUT
from conda_package_supply_chain_monitor.identity.services import ASSOCIATOR_KEY_LENGTH
from conda_package_supply_chain_monitor.identity.services import CANONICAL_NAME_LENGTH
from tests.clocks import FIXED_INSTANT
from tests.collectors import RecordedTransport
from tests.collectors import collector_class
from tests.collectors import fixture_evidence_model
from tests.collectors import recorded_payload
from tests.source_scan import SRC_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: The module every structural sweep below reads, relative to `src/`. Named once
#: because three cases parse it and a path spelled three times is a sweep that can
#: be pointed at the wrong file twice.
INGESTION_MODULE: Final[str] = "django_apps/conda_package_supply_chain_monitor/collectors/tasks.py"

#: The model this collector must never write, by the name an import of it would
#: bind. The sweep is on the *name* rather than on a call, and that is the wider
#: net on purpose: `Package.objects.create`, `Package(...)`, a `Package` passed to
#: something else -- every one of them names the class, and a rule that listed
#: write methods would be a rule somebody could get around by finding a sixth.
PACKAGE_MODEL_NAME: Final[str] = "Package"

#: The service that is allowed to make the shell, by the name the module binds.
#: Asserted present as the anti-vacuity half of the sweep above: a module that
#: had stopped creating packages altogether would satisfy "never names Package"
#: perfectly.
RESOLUTION_SERVICE: Final[str] = "resolve_package_shell"

#: The transaction opener whose enclosure `CPM-AD-23` is about.
ATOMIC_FORM: Final[str] = "transaction.atomic"

#: The application whose `ready()` adopts this collector, by its derived label.
COLLECTORS_APP_LABEL: Final[str] = "collectors"

#: The one door this module writes evidence through, and the doors it must not.
#: `_write_evidence` is the base's: it checks the declared model, checks the
#: instant, inserts through the append-only manager and tallies the row. The
#: others reach the table without any of that.
BASE_WRITE_METHOD: Final[str] = "_write_evidence"
DIRECT_WRITE_METHODS: Final[frozenset[str]] = frozenset({"abulk_create", "acreate", "bulk_create", "create"})

#: The nine declarations the base checks at construction, and what this collector
#: must declare for each. Written out here rather than read off the class, which
#: would assert that the class equals itself.
EXPECTED_DECLARATIONS: Final[dict[str, object]] = {
    "name": COLLECTOR_NAME,
    "evidence_model": InventorySnapshot,
    "observation_window": NO_WINDOW,
    "timeout": MAX_TIMEOUT,
    "retries": 0,
    "rate_limit": RateLimit(calls=60, per=timedelta(seconds=60)),
    "headers": {},
    "freshness_target": timedelta(days=2),
    "response_cache_ttl": NO_CACHE,
}

#: The cadence this collector's freshness target is derived from
#: (`CPM-NFR-2`: inventory ingestion is a daily sweep). Named here rather than
#: spelled at the one assertion, because the assertion is about the *relation*
#: between the two intervals and a literal on both sides would be two numbers
#: nothing reconciles.
INVENTORY_CADENCE: Final[timedelta] = timedelta(days=1)

#: One well-formed record, as the adapter yields it. Every signal populated, so a
#: case about a *missing* one differs from this by exactly the key it is about.
A_RECORD: Final[dict[str, Any]] = {
    SOURCE_PACKAGE_KEY: "internal/numpy",
    PACKAGE_NAME: "numpy",
    "internal_component_count": 3,
    "internal_lob_count": 2,
    "apps": 7,
    "platforms": 4,
    "downloads": 1200,
    "versions": 5,
}

#: A package a case names when it does not care which.
A_PACKAGE: Final[int] = 42


def _clock() -> FixedClock:
    """Return the stopped clock these cases construct collectors with.

    Built here rather than taken from the `fixed_clock` fixture because several
    of these cases construct a collector inside a `pytest.raises` block, where a
    fixture argument would put the clock's construction further from the
    collector's than the assertion is.

    Returns:
        A `FixedClock` at `tests.clocks.FIXED_INSTANT`.

    """
    return FixedClock(instant=FIXED_INSTANT)


def _document(*records: dict[str, Any]) -> str:
    """Return the body an adapter would record for these records.

    Args:
        *records: The record objects the document carries.

    Returns:
        The JSON array `records_in` decodes.

    """
    return json.dumps(list(records))


def _ingestion_module() -> Path:
    """Return the collector module's path, for the sweeps that parse it.

    Returns:
        The absolute path under `src/`.

    """
    return SRC_ROOT / INGESTION_MODULE


def _named(tree: ast.Module) -> set[str]:
    """Return every bare name and attribute this module mentions.

    Args:
        tree: The parsed module.

    Returns:
        Every `Name` identifier and every attribute's final segment, which is
        what an import binds and what an attribute access spells.

    """
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return names | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def _atomic_blocks(tree: ast.Module) -> list[ast.With]:
    """Return every `with transaction.atomic():` block in a module.

    Args:
        tree: The parsed module.

    Returns:
        The `With` nodes, in walk order.

    """
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call) and dotted_name(item.context_expr.func) == ATOMIC_FORM
            for item in node.items
        )
    ]


@pytest.fixture
def declared_adapter() -> Iterator[RecordedTransport]:
    """Declare a recorded adapter for one case and withdraw it afterwards.

    The declaration is process-global, exactly as the collector registry is, so
    an adapter left behind would be the source every later case in the session
    ingests through. Withdrawal is in the teardown rather than at the end of the
    body, because several of these cases assert a *refusal* and leave by an
    exception.

    Yields:
        The adapter that was declared, so a case can script what it answers.

    """
    adapter = RecordedTransport(payload=recorded_payload(source=INVENTORY_SOURCE, body=_document(A_RECORD)))
    declare_inventory_adapter(adapter)
    try:
        yield adapter
    finally:
        withdraw_inventory_adapter()


# ---------------------------------------------------------------------------
# The declarations (AC #1) and the task's name (AC #5).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("declaration", "expected"), sorted(EXPECTED_DECLARATIONS.items()))
def test_the_collector_declares_every_value_the_base_requires(declaration: str, expected: object) -> None:
    """AC #1: all nine, and each is the value this collector's source justifies.

    Read off the class rather than off an instance, because that is what
    `config/startup/stage_two.py`'s boot sweep reads -- constructing a collector
    to ask what it declares would build a transport and its connection pool
    inside `django.setup()`.
    """
    assert getattr(InventoryIngestionCollector, declaration) == expected


def test_the_declared_freshness_target_exceeds_the_cadence_it_is_derived_from() -> None:
    """PRD Open Question 7's rule, which is what the value above is an instance of.

    Two things, and the second is the one that is easy to get wrong. `CPM-AD-28`
    requires a strictly positive target: an unset one behaves as fresh forever and
    a zero one makes evidence stale the instant it is written. Open Question 7
    adds the rule the arithmetic exists to satisfy -- the target must be strictly
    *greater than the cadence*, because `core/freshness.py` reports stale when
    `observed_at < now - target`, so a target equal to a daily cadence makes the
    whole inventory read stale at exactly the moment the next run is due, without
    a single collection having failed.

    Asserted against the cadence rather than against `timedelta(days=2)`, which
    the parametrized case above already pins: this is the rule, and the rule is
    what a later re-derivation has to keep.
    """
    target = InventoryIngestionCollector.freshness_target

    assert target is not None
    assert target > timedelta(0)
    assert target > INVENTORY_CADENCE


def test_the_collector_is_registered_under_its_declared_name() -> None:
    """AC #1: adoption is `CollectorsConfig.ready()`'s, and it has happened.

    The registry is what `CPM-AD-28`'s boot sweep walks and what a later
    scheduling story enumerates, so a collector that exists and is not in it is
    a collector nothing runs.
    """
    assert registrations().get(COLLECTOR_NAME) is InventoryIngestionCollector


def test_adopting_the_collector_twice_is_not_a_second_registration() -> None:
    """`AppConfig.ready()` must be safe to run again, because sometimes it is.

    `core/registry.py` refuses a duplicate name rather than overwriting it, which
    is right -- two classes under one name share an allowance and a run history.
    But the same class arriving twice is not that: a repeated `django.setup()`, a
    registry repopulated by a test, or a second app-registry population in one
    process would raise `CollectorRegistryError` out of `ready()` and take
    startup down over an adoption that had already succeeded.

    The hook also declares `CPM-IDENTITY-S07`'s watchlist adapter, which is why
    this leaves by a `finally`: the declaration is process-global exactly as the
    registry is, and an adapter left behind by *this* case would be the source
    every later case in the session ingests through.
    """
    config = apps.get_app_config(COLLECTORS_APP_LABEL)

    try:
        config.ready()
        config.ready()

        assert registrations()[COLLECTOR_NAME] is InventoryIngestionCollector
    finally:
        # Guarded rather than unconditional. A `ready()` that failed *before*
        # declaring leaves the slot empty, and an unconditional withdrawal would
        # then raise out of the teardown and replace the real failure with a
        # complaint about there being nothing to withdraw.
        if declared_inventory_adapter() is not None:
            withdraw_inventory_adapter()


def test_the_task_declares_a_collect_namespace_name() -> None:
    """AC #5: the workload class lives in the name, so `core/queues.py` needs no edit.

    Asserted against the *registered* name rather than against the constant
    alone: a decorator that dropped its `name=` would register under
    `conda_package_supply_chain_monitor.collectors.tasks.ingest_inventory`, which
    routes to no product queue at all and would be published to a queue nobody
    drains.
    """
    assert INGEST_TASK_NAME == "cpm.collect.inventory"
    assert ingest_inventory.name == INGEST_TASK_NAME


def test_the_task_declares_no_schedule_and_no_time_limit() -> None:
    """AC #5: cadence is data in `django_celery_beat`, never a decorator argument.

    `CPM-AD-20` and `CPM-NFR-2`: a cadence written into a decorator cannot be
    changed without a deploy. The repository-wide gate is
    `tests/unit/django_apps/test_task_declaration_audit.py`; this is the same
    claim made about the one task this story adds, so a failure names it.
    """
    for attribute in ("run_every", "schedule", "time_limit", "soft_time_limit"):
        assert getattr(ingest_inventory, attribute, None) is None, attribute


def test_the_sweep_source_is_the_declared_locator() -> None:
    """The locator every ledger row and log line of a sweep names.

    Opaque on purpose: the adapter knows which file it reads (`CPM-AD-29`), and a
    path spelled in the collector would be this story choosing the inventory
    source, which is `CPM-IDENTITY-S07`'s.
    """
    collector = InventoryIngestionCollector(clock=_clock(), transport=RecordedTransport())

    assert collector.sweep_source() == INVENTORY_SOURCE


# ---------------------------------------------------------------------------
# The structural rules (AC #3).
# ---------------------------------------------------------------------------


def test_the_collector_module_never_names_the_package_model() -> None:
    """AC #3: the collector never writes the package table (`CPM-AD-14`, `CPM-AD-25`).

    Swept on the *name* rather than on a list of write methods, which is the
    wider net: `Package.objects.create(...)`, `Package(...)`, and a `Package`
    handed to something else all name the class, while a method table is a table
    somebody can get around by finding a sixth spelling. The rule is that
    resolution is the only creator of a package row, and a module that cannot
    name the model cannot be a second one.
    """
    named = _named(parse(_ingestion_module()))

    assert PACKAGE_MODEL_NAME not in named


def test_the_collector_module_creates_shells_through_the_resolution_service() -> None:
    """The anti-vacuity half: a module that created no packages would sweep clean.

    `CPM-AD-25` is not "ingestion makes no packages" -- it is "ingestion makes
    them *through resolution*", and only this half says the door is being used.
    """
    tree = parse(_ingestion_module())
    called = {dotted_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}

    assert RESOLUTION_SERVICE in _named(tree)
    assert RESOLUTION_SERVICE in called


def test_no_transaction_in_the_collector_module_encloses_a_loop() -> None:
    """AC #3: no `transaction.atomic()` spans more than one package (`CPM-AD-23`).

    A loop *inside* a transaction is what "more than one package" looks like in
    source, and it is the shape nothing at run time would report: the rows still
    land, the run still succeeds, and the only symptom is that one package's
    failure takes every earlier package's evidence with it -- which shows up as a
    `failed` run where `CPM-FR-15` promised a `partial` one, months later, in a
    sweep nobody was watching.
    """
    blocks = _atomic_blocks(parse(_ingestion_module()))
    spanning = [
        block.lineno
        for block in blocks
        for statement in block.body
        for node in ast.walk(statement)
        if isinstance(node, ast.For | ast.AsyncFor | ast.While)
    ]

    assert blocks != [], "the module opens no transaction, so the enclosure rule proves nothing"
    assert spanning == [], f"transaction blocks at lines {spanning} enclose a loop"


def test_every_evidence_write_in_the_collector_module_is_inside_a_transaction() -> None:
    """The other direction: every row this module writes is inside a transaction.

    Swept for `_write_evidence` rather than for `bulk_create`, because that is the
    one door this module writes through -- and the fact that it *has* no
    `bulk_create` of its own is asserted below. The repository-wide audit in
    `tests/unit/django_apps/test_collector_base_audit.py` covers the base's own
    insert; this covers the module `CPM-AD-23`'s per-package rule is actually
    about, and it fails naming the collector rather than naming a scan.
    """
    tree = parse(_ingestion_module())
    enclosed = {
        id(node)
        for block in _atomic_blocks(tree)
        for statement in block.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
    }
    writes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and dotted_name(node.func).rpartition(".")[2] == BASE_WRITE_METHOD
    ]
    bare = [node.lineno for node in writes if id(node) not in enclosed]

    assert writes != [], "the module writes no evidence, so the enclosure rule proves nothing"
    assert bare == [], f"evidence writes at lines {bare} are outside any transaction"


def test_the_collector_module_writes_no_evidence_of_its_own() -> None:
    """Every row goes through the base, which is what makes the base able to check it.

    `Collector._require_counted` reconciles what a sweep *reports* against what
    the base actually inserted, and the whole guarantee rests on there being one
    door. A `bulk_create` here would write rows the base never saw -- unstamped,
    unchecked against the declared model, and uncounted -- and the run would then
    be refused for a count that does not add up, which is the right failure but a
    long way from the mistake. So the mistake is caught here instead.
    """
    tree = parse(_ingestion_module())
    direct = sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and dotted_name(node.func).rpartition(".")[2] in DIRECT_WRITE_METHODS
    )

    assert direct == [], f"the collector reaches the table directly at lines {direct}"


# ---------------------------------------------------------------------------
# The declared adapter (`CPM-AD-29`).
# ---------------------------------------------------------------------------


def test_ingestion_is_refused_when_no_adapter_is_declared() -> None:
    """The matrix row: the run is refused before any row is written.

    Refused *before the recorder opens*, which is why this is a unit case: a
    component with no inventory source must not leave a run row claiming to have
    observed an empty inventory, and there is nothing to observe it with.
    """
    with pytest.raises(InventoryAdapterError) as refused:
        inventory_adapter()

    assert "declared" in str(refused.value)


def test_the_task_refuses_before_it_builds_a_collector_when_no_adapter_is_declared() -> None:
    """The same refusal, through the entry point a worker actually calls."""
    with pytest.raises(InventoryAdapterError):
        ingest_inventory()


def test_the_declared_adapter_is_what_is_handed_back(declared_adapter: RecordedTransport) -> None:
    """The ordinary path: one adapter is declared and it is the one ingestion reads."""
    assert inventory_adapter() is declared_adapter


def test_a_second_adapter_is_refused_rather_than_replacing_the_first(
    declared_adapter: RecordedTransport,
) -> None:
    """`CPM-AD-29`: ingestion reads exactly one adapter.

    The failure a silent replacement causes is not recoverable: a deployed
    component ingesting a development subset records every package outside it as
    absent, in an append-only log nothing may update.
    """
    with pytest.raises(InventoryAdapterError) as refused:
        declare_inventory_adapter(RecordedTransport())

    assert inventory_adapter() is declared_adapter
    assert "already" in str(refused.value)


def test_an_object_that_cannot_fetch_is_not_an_adapter() -> None:
    """An adapter is a `Transport`, which is the seam and the whole contract."""
    with pytest.raises(InventoryAdapterError) as refused:
        declare_inventory_adapter(object())  # type: ignore[arg-type]

    assert "Transport" in str(refused.value)


def test_withdrawing_nothing_is_refused_rather_than_ignored() -> None:
    """A silent no-op turns a mistaken withdrawal into a declaration that stays live."""
    with pytest.raises(InventoryAdapterError):
        withdraw_inventory_adapter()


# ---------------------------------------------------------------------------
# The record contract, and every way a document is refused (`CPM-FR-42`).
# ---------------------------------------------------------------------------


def test_a_well_formed_document_yields_one_record_per_entry() -> None:
    """The ordinary path, and the anti-vacuity guard for every refusal below."""
    records = records_in(recorded_payload(source=INVENTORY_SOURCE, body=_document(A_RECORD)))

    assert len(records) == 1
    assert records[0].source_package_key == A_RECORD[SOURCE_PACKAGE_KEY]
    for signal in (*REQUIRED_SIGNALS, *OPTIONAL_SIGNALS):
        assert getattr(records[0], signal) == A_RECORD[signal], signal


def test_an_omitted_optional_signal_is_missing_rather_than_zero() -> None:
    """PRD Appendix A.1's data rules and Open Question 3b, in one assertion.

    `None` and `0` are different facts -- a package nobody counted and a package
    nobody downloaded -- and the whole reason the columns are nullable is that a
    score built on them has to be able to tell.
    """
    sparse = {key: value for key, value in A_RECORD.items() if key not in OPTIONAL_SIGNALS}

    records = records_in(recorded_payload(source=INVENTORY_SOURCE, body=_document(sparse)))

    for signal in OPTIONAL_SIGNALS:
        assert getattr(records[0], signal) is None, signal


def test_a_zero_optional_signal_is_zero_rather_than_missing() -> None:
    """The other half, without which the case above passes for a collapsing decoder."""
    records = records_in(recorded_payload(source=INVENTORY_SOURCE, body=_document({**A_RECORD, "downloads": 0})))

    assert records[0].downloads == 0


def test_a_document_naming_no_packages_is_refused() -> None:
    """The most dangerous well-formed document there is, and the least alarming.

    An empty array is *not* an inventory of no packages -- it is a source that
    told this run nothing, and a sweep that accepted it would derive an absence
    for every package the system has ever seen. Those rows are permanent, the log
    is append-only, and every later replay reads them. So the refusal is here, at
    the contract, before anything downstream can act on the emptiness.
    """
    with pytest.raises(InventoryRecordError) as refused:
        records_in(recorded_payload(source=INVENTORY_SOURCE, body=json.dumps([])))

    assert "naming no packages" in str(refused.value)


def test_a_source_package_key_wider_than_its_column_refuses_the_whole_document() -> None:
    """`CPM-FR-42`: no run partially ingests a malformed source.

    `resolve_package_shell` refuses the same key, but it refuses it one package at
    a time and halfway through a sweep -- which is a `partial` run over a document
    that was malformed before the first row was written. The contract is where the
    document is judged whole, so the bound is applied here as well as there.

    The bound is `associator_key`'s, which is the column the key lands in since
    `CPM-IDENTITY-S07` separated it from the name. That is *wider* than
    `canonical_name`, so a key between the two lengths is accepted here and
    refused only if somebody re-fuses the two.
    """
    with pytest.raises(InventoryRecordError) as refused:
        records_in(
            recorded_payload(
                source=INVENTORY_SOURCE,
                body=_document({**A_RECORD, SOURCE_PACKAGE_KEY: "n" * (ASSOCIATOR_KEY_LENGTH + 1)}),
            ),
        )

    assert SOURCE_PACKAGE_KEY in str(refused.value)
    assert str(ASSOCIATOR_KEY_LENGTH) in str(refused.value)


def test_a_source_package_key_wider_than_a_package_name_is_accepted() -> None:
    """The two bounds are separate, and this is the case that would fail if they were fused.

    A key longer than `canonical_name` holds is perfectly usable: it goes to
    `associator_key`, which is wider. Refusing it would reject a legitimate
    source key for a column it does not occupy -- which is the confusion this
    story split the two values to remove, and the shape it would come back in.
    """
    long_key = "n" * (CANONICAL_NAME_LENGTH + 1)

    records = records_in(
        recorded_payload(source=INVENTORY_SOURCE, body=_document({**A_RECORD, SOURCE_PACKAGE_KEY: long_key})),
    )

    assert records[0].source_package_key == long_key


def test_a_count_larger_than_the_column_holds_is_refused() -> None:
    """The other end of the parity gap `PositiveIntegerField` leaves open.

    The column is a signed 32-bit integer, enforced by PostgreSQL and ignored by
    SQLite -- so an oversized count is a stored row on a developer's machine and a
    failed run in the gate, which is the same failure the negative case guards and
    the same reason it is refused where the value enters.
    """
    with pytest.raises(InventoryRecordError) as refused:
        records_in(
            recorded_payload(
                source=INVENTORY_SOURCE,
                body=_document({**A_RECORD, "downloads": MAX_COUNT + 1}),
            ),
        )

    assert "downloads" in str(refused.value)


def test_the_declared_ceiling_is_never_wider_than_the_column_accepts() -> None:
    """The anti-drift half, and the parity gap it has to be stated across.

    `PositiveIntegerField`'s upper bound is not a property of the field: Django
    asks `connection.ops.integer_field_range` for it, and the answers differ --
    PostgreSQL's `integer` stops at 2147483647 while SQLite's integers are 64-bit
    and stop nowhere the field cares about. That is exactly `R-5`'s local/gate
    divergence, and it is why `MAX_COUNT` is a declared number rather than a
    number read off the running backend: the contract has to refuse what the
    *narrowest* supported backend refuses, or an ingest that worked on a
    developer's machine fails in the gate.

    So what is asserted here is the direction that must hold everywhere -- the
    declared bound never exceeds what this backend would accept -- and it is the
    `gate-postgres` run where that becomes tight, because there the two numbers
    are equal. A `MAX_COUNT` widened past PostgreSQL's `integer` fails there.
    """
    _, ceiling = connection.ops.integer_field_range("PositiveIntegerField")

    assert ceiling is not None
    assert ceiling >= MAX_COUNT


def test_the_record_fields_are_exactly_the_declared_signals() -> None:
    """The two rosters and the dataclass are one declaration written three ways.

    `REQUIRED_SIGNALS` and `OPTIONAL_SIGNALS` drive `RECORD_FIELDS`, which is what
    refuses an undefined field; `InventoryRecord`'s own fields are what a record
    is built from, written out rather than unpacked from a mapping. This is what
    keeps the two in step: a signal added to a tuple and not to the record would
    be accepted by the contract and dropped on the floor.
    """
    declared = {field.name for field in dataclasses.fields(InventoryRecord)}

    assert declared == {SOURCE_PACKAGE_KEY, PACKAGE_NAME, *REQUIRED_SIGNALS, *OPTIONAL_SIGNALS}
    assert declared == set(RECORD_FIELDS) | {SOURCE_PACKAGE_KEY, PACKAGE_NAME}


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("not json at all", "readable inventory document", id="unreadable"),
        pytest.param(json.dumps({"records": []}), "rather than a list", id="not-a-list"),
        pytest.param(json.dumps(["a string"]), "rather than an object", id="entry-not-an-object"),
    ],
)
def test_a_document_that_is_not_a_list_of_records_is_refused(body: str, expected: str) -> None:
    """`CPM-AD-29`: an adapter yields records or fails.

    Refused rather than read as an empty inventory, which would record every
    package it should have named as absent -- permanently, in a log nothing may
    correct.
    """
    with pytest.raises(InventoryRecordError) as refused:
        records_in(recorded_payload(source=INVENTORY_SOURCE, body=body))

    assert expected in str(refused.value)


@pytest.mark.parametrize("signal", REQUIRED_SIGNALS)
def test_a_record_missing_a_required_signal_fails_the_run(signal: str) -> None:
    """PRD Open Question 3b: both counts are required on every record.

    Together they are the internal usage breadth `CPM-FR-4` ranks by, so a record
    without them is one that cannot be ranked -- and storing it half-observed
    would put a package in the inventory that no priority pass can place.
    """
    incomplete = {key: value for key, value in A_RECORD.items() if key != signal}

    with pytest.raises(InventoryRecordError) as refused:
        records_in(recorded_payload(source=INVENTORY_SOURCE, body=_document(incomplete)))

    assert signal in str(refused.value)


@pytest.mark.parametrize(
    "value",
    [pytest.param("three", id="text"), pytest.param(-1, id="negative"), pytest.param(True, id="boolean")],
)
def test_a_signal_that_is_not_a_count_fails_the_run(value: object) -> None:
    """`CPM-FR-42`: a non-numeric count fails the run.

    `True` is in the table because `bool` is a subclass of `int`: a document
    carrying `true` would otherwise be a component count of one. A negative is
    here because `PositiveIntegerField` is enforced by PostgreSQL and not by
    SQLite, so it would be a row on a developer's machine and a failed run in the
    gate.
    """
    with pytest.raises(InventoryRecordError) as refused:
        records_in(
            recorded_payload(
                source=INVENTORY_SOURCE,
                body=_document({**A_RECORD, "internal_component_count": value}),
            ),
        )

    assert "internal_component_count" in str(refused.value)


def test_a_record_naming_no_package_is_refused() -> None:
    """A record that cannot be traced back to a key is one nothing can re-derive."""
    with pytest.raises(InventoryRecordError) as refused:
        records_in(recorded_payload(source=INVENTORY_SOURCE, body=_document({**A_RECORD, SOURCE_PACKAGE_KEY: "   "})))

    assert SOURCE_PACKAGE_KEY in str(refused.value)


@pytest.mark.parametrize(
    "name",
    [pytest.param(None, id="omitted"), pytest.param("   ", id="blank"), pytest.param(7, id="not-a-string")],
)
def test_a_record_giving_its_package_no_name_is_refused(name: object) -> None:
    """The name is required of every record, and it is not the key.

    `CPM-IDENTITY-S07` separated the two: the key becomes `associator_key` and
    the name becomes `canonical_name`, so a record carrying a usable key no
    longer implies a usable name. Refused in the contract rather than at
    resolution, because the document is decoded whole before the first write --
    `CPM-FR-42`'s "no run partially ingests a malformed source".
    """
    record = {key: value for key, value in A_RECORD.items() if key != PACKAGE_NAME}
    if name is not None:
        record[PACKAGE_NAME] = name

    with pytest.raises(InventoryRecordError) as refused:
        records_in(recorded_payload(source=INVENTORY_SOURCE, body=_document(record)))

    assert PACKAGE_NAME in str(refused.value)


def test_a_package_name_wider_than_the_column_fails_the_whole_document() -> None:
    """The same bound the key is measured against, on the column the name lands in.

    Refused here rather than left to resolution for the reason the key's own
    bound is: resolution refuses it one package at a time and halfway through a
    sweep, which is a `partial` run over a source that was malformed from the
    start.
    """
    with pytest.raises(InventoryRecordError) as refused:
        records_in(
            recorded_payload(
                source=INVENTORY_SOURCE,
                body=_document({**A_RECORD, PACKAGE_NAME: "n" * (CANONICAL_NAME_LENGTH + 1)}),
            ),
        )

    assert PACKAGE_NAME in str(refused.value)


def test_a_field_the_contract_does_not_define_is_refused_rather_than_ignored() -> None:
    """`CPM-FR-1`: ingestion never asserts a mapping.

    A source supplying a repository URL, a purl or a confidence believes it is
    supplying one, and silently dropping the column would leave it believing
    that. The refusal is what makes "ingestion resolves nothing" a property of
    the system rather than of what the collector happened to read.
    """
    with pytest.raises(InventoryRecordError) as refused:
        records_in(
            recorded_payload(
                source=INVENTORY_SOURCE,
                body=_document({**A_RECORD, "source_repository_url": "https://example.invalid/numpy"}),
            ),
        )

    assert "source_repository_url" in str(refused.value)


def test_a_repeated_source_package_key_fails_the_run() -> None:
    """`CPM-FR-42`: repeating a key fails the run, rather than the last one winning.

    Two records for one key are two claims about the same package's usage in one
    observation, and choosing between them would be an invention.
    """
    with pytest.raises(InventoryRecordError) as refused:
        records_in(recorded_payload(source=INVENTORY_SOURCE, body=_document(A_RECORD, A_RECORD)))

    assert A_RECORD[SOURCE_PACKAGE_KEY] in str(refused.value)


# ---------------------------------------------------------------------------
# The base's run-scoped path, before a run exists.
# ---------------------------------------------------------------------------


def test_a_collector_with_no_run_scoped_source_is_refused_when_asked_to_sweep() -> None:
    """The base's default `sweep_source`: a refusal rather than an invented locator.

    Not abstract, deliberately -- eight collectors read one locator per package
    and would otherwise have to implement a path they do not have -- so the
    refusal is what stands in for the missing declaration.
    """
    built = collector_class(declared_model=fixture_evidence_model())
    collector = built(clock=_clock(), transport=RecordedTransport())

    with pytest.raises(CollectorConfigurationError) as refused:
        collector.sweep_source()

    assert "sweep_source" in str(refused.value)


def test_a_collector_with_no_run_scoped_persistence_is_refused() -> None:
    """The base's default `persist_sweep`, on the same terms."""
    built = collector_class(declared_model=fixture_evidence_model())
    collector = built(clock=_clock(), transport=RecordedTransport())

    with pytest.raises(CollectorConfigurationError) as refused:
        collector.persist_sweep(recorded_payload(), observed_at=FIXED_INSTANT)

    assert "persist_sweep" in str(refused.value)


@pytest.mark.parametrize("hook", ["source_for", "translate", "sentinel_evidence"])
def test_the_ingestion_collector_has_no_per_package_path(hook: str) -> None:
    """All three per-package hooks refuse, and one message says why.

    A `source_for` returning the document's own locator would make
    `collect(package_id=...)` re-read the whole inventory to observe one package
    -- a defect that would look exactly like it worked.
    """
    collector = InventoryIngestionCollector(clock=_clock(), transport=RecordedTransport())
    arguments: dict[str, dict[str, object]] = {
        "source_for": {"package_id": A_PACKAGE},
        "translate": {"payload": recorded_payload(), "package_id": A_PACKAGE, "observed_at": FIXED_INSTANT},
        "sentinel_evidence": {
            "state": OutcomeState.ERROR,
            "package_id": A_PACKAGE,
            "observed_at": FIXED_INSTANT,
            "detail": "",
        },
    }

    with pytest.raises(CollectorConfigurationError) as refused:
        getattr(collector, hook)(**arguments[hook])

    assert hook in str(refused.value)
    assert "per-package path" in str(refused.value)


def test_the_sweep_window_asks_about_runs_scoped_to_no_package() -> None:
    """`package_id=None` is `IS NULL`, which is the question a sweep asks.

    A sweep must not be suppressed by a package-scoped run of the same collector
    and vice versa: they observe different things, and a window that conflated
    them would let a single package's recollection silence the whole inventory.
    """
    swept = window_query(collector=COLLECTOR_NAME, package_id=None, since=FIXED_INSTANT)
    scoped = window_query(collector=COLLECTOR_NAME, package_id=A_PACKAGE, since=FIXED_INSTANT)

    assert ("package_id", None) in swept.children
    assert swept != scoped


def test_a_sweep_outcome_reports_no_failures_by_default() -> None:
    """The ordinary ending, so `partial` is something a collector has to declare.

    A default of "some failures" would make every clean run look partial; a
    required argument would make the ordinary path the noisy one.
    """
    outcome = SweepOutcome(observed_rows=1)

    assert outcome.failures == ()
    assert outcome.derived_rows == 0
    assert outcome.evidence_rows == 1


def test_a_snapshot_renders_as_its_key_state_and_instant() -> None:
    """What a log line, a debugger and a failure message show for one row."""
    row = InventorySnapshot(
        observed_at=FIXED_INSTANT,
        package_id=A_PACKAGE,
        source_package_key=A_RECORD[SOURCE_PACKAGE_KEY],
        state=OutcomeState.OK.value,
    )

    rendered = str(row)

    assert A_RECORD[SOURCE_PACKAGE_KEY] in rendered
    assert str(A_PACKAGE) in rendered
    assert OutcomeState.OK.value in rendered
    assert FIXED_INSTANT.isoformat() in rendered


def test_an_unsaved_snapshot_renders_its_absences_rather_than_raising() -> None:
    """A `__str__` that raised would break the two places a half-built row is shown.

    Read off `package_id` rather than `package`, because the related object of an
    unsaved instance raises `RelatedObjectDoesNotExist` -- and a debugger
    rendering a row it was handed must not be the thing that fails.
    """
    rendered = str(InventorySnapshot())

    assert "no source package key" in rendered
    assert "no package" in rendered
    assert "never" in rendered


def test_the_evidence_model_is_an_append_only_model() -> None:
    """`CPM-AD-2`, asserted where the collector declares it.

    A plain `Model` satisfies every annotation in the base and carries none of
    the refusals, so "the declared model is append-only" is a claim worth making
    about the first real declaration there is.
    """
    assert issubclass(InventorySnapshot, AppendOnlyModel)


@pytest.mark.parametrize(
    ("index", "fields"),
    [
        pytest.param(SNAPSHOT_READ_INDEX, ["package", "-observed_at"], id="cut-off-read"),
        pytest.param(SNAPSHOT_KEY_INDEX, ["source_package_key"], id="absence-derivation"),
    ],
)
def test_the_evidence_table_indexes_the_two_paths_that_read_it(index: str, fields: list[str]) -> None:
    """Indexes are permitted on an evidence model; unique constraints are not.

    The difference is `CPM-AD-2`'s: an index makes a read cheaper and changes no
    write, while a unique constraint turns a re-observation into an
    `IntegrityError` -- which is why
    `tests/unit/django_apps/test_evidence_constraint_audit.py` reads
    `Meta.constraints` and never `Meta.indexes`.

    The two access paths this table has are indexed: `snapshot_as_of`'s
    filter-and-order, which every policy pass runs, and the absence derivation's
    exclusion on the source's own key. The *shape* is asserted rather than the
    existence, because an index on the right column in the wrong order does not
    serve the sort it was added for.
    """
    declared = {
        candidate.name: list(candidate.fields)
        for candidate in InventorySnapshot._meta.indexes  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    }

    assert declared[index] == fields
