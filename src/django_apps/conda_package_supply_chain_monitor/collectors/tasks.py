"""This application's Celery tasks, and inventory ingestion's collector and adapter.

**Every task this application registers is declared here and nowhere else.**
Celery's autodiscovery imports each installed application's `tasks` module and no
other (`config/celery_app.py`), so a `@shared_task` in a sibling module is
registered by whatever happens to import it -- which is the suite, and not a
worker. `CPM-CURRENCY-S01`'s collector therefore lives in
`collectors/source_release.py` while its task lives at the foot of this file: the
collector is code a reader wants beside the source it reads, and the task is a
line that has to be *here* to run at all.

`CPM-FR-42` acquires the package inventory from a declared source, and
`CPM-AD-25` fixes how: as an **observation**, through the shared collector base,
on the `collect` queue, written to an append-only log. This module is that
collector. It is the first concrete collector in the repository and the only one
that introduces a package -- `CPM-FR-7` through `CPM-FR-10` observe surfaces
*about packages the inventory already names*.

**The collector never writes the package table**, and that is the sentence this
module is arranged around. A record naming a package with no row calls
`identity`'s resolution service, which is the only creator of a package row
(`CPM-AD-14`, `CPM-AD-25`). `tests/unit/django_apps/test_inventory_ingestion.py`
sweeps this module's own source for a `Package` write, because the rule is only
worth what a reviewer who has not read this paragraph is stopped by.

**The atomic unit is one package** (`CPM-AD-23`). The shell and its snapshot
commit together, in a `transaction.atomic()` nested inside the base's run
recorder and never around it, so a later package's failure never rolls back an
earlier package's rows and the run finalizes `partial` (`CPM-FR-15`).

**The source is reached through the base's transport seam and nothing else**
(`CPM-AD-29`). An inventory source adapter *is* a `Transport`, so this collector
carries no branch on which source is active and the seam needs no second
protocol. `CPM-IDENTITY-S07` declares the watchlist adapter, its columns, its
refusals and the rule that selects a file by locality; what is here is the one
declared point an adapter is bound to, and the refusal when none is.

**Absence is a row, not a deletion.** `CPM-AD-25`: "a package present in an
earlier run and absent from a later one is recorded as absent with a timestamp.
No package row is ever deleted." So a sweep that no longer sees a key it has seen
before writes a `not_found` snapshot carrying *this* run's `observed_at`, and the
package keeps its row and its place in the rollup. An absence is written on every
run it is still true for, which is why this collector declares `NO_WINDOW`:
suppressing a run would suppress the absence observations too, and absence is the
signal that decays.

**No run partially ingests a malformed source** (`CPM-FR-42`, inherited `CG-3`).
The whole document is decoded into records before the first row is written, so a
missing required signal, a non-numeric count, a repeated source package key or a
field the record contract does not define fails the run with nothing written --
rather than leaving half an inventory behind and an operator to work out which
half.

**There is no per-package path here, and the three hooks say so.** `source_for`,
`translate` and `sentinel_evidence` are the base's per-package contract: one
locator per package, one payload about one package, one sentinel row about one
package. Inventory ingestion reads one document naming many packages and has none
of those things, so each refuses rather than inventing an answer. A `source_for`
returning the document's locator would make `collect(package_id=...)` re-read the
whole inventory to observe one package, which is a defect that would look like it
worked.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final
from typing import NoReturn

from celery import shared_task
from django.db import DatabaseError
from django.db import transaction

from conda_package_supply_chain_monitor.collectors.models import InventorySnapshot
from conda_package_supply_chain_monitor.collectors.source_release import SourceReleaseCollector
from conda_package_supply_chain_monitor.core.clock import SystemClock
from conda_package_supply_chain_monitor.core.collection import NO_CACHE
from conda_package_supply_chain_monitor.core.collection import NO_WINDOW
from conda_package_supply_chain_monitor.core.collection import Collector
from conda_package_supply_chain_monitor.core.collection import CollectorConfigurationError
from conda_package_supply_chain_monitor.core.collection import SweepOutcome
from conda_package_supply_chain_monitor.core.ledger import current_trace_id
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.rate_limit import RateLimit
from conda_package_supply_chain_monitor.core.transport import MAX_TIMEOUT
from conda_package_supply_chain_monitor.core.transport import Transport
from conda_package_supply_chain_monitor.identity.services import ASSOCIATOR_KEY_LENGTH
from conda_package_supply_chain_monitor.identity.services import CANONICAL_NAME_LENGTH
from conda_package_supply_chain_monitor.identity.services import ResolutionError
from conda_package_supply_chain_monitor.identity.services import resolve_package_shell

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence
    from datetime import datetime

    from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
    from conda_package_supply_chain_monitor.core.transport import Payload

__all__ = [
    "ABSENT_DETAIL",
    "COLLECTOR_NAME",
    "COLLECT_SOURCE_RELEASE_TASK_NAME",
    "INGEST_TASK_NAME",
    "INVENTORY_SOURCE",
    "MAX_COUNT",
    "OPTIONAL_SIGNALS",
    "PACKAGE_NAME",
    "REQUIRED_SIGNALS",
    "SOURCE_PACKAGE_KEY",
    "InventoryAdapterError",
    "InventoryIngestionCollector",
    "InventoryRecord",
    "InventoryRecordError",
    "collect_source_release",
    "declare_inventory_adapter",
    "declared_inventory_adapter",
    "ingest_inventory",
    "inventory_adapter",
    "records_in",
    "withdraw_inventory_adapter",
]

#: This module declares no logger and emits no events of its own, deliberately.
#: `core/collection.py` owns the six a collection can emit -- skipped, refused,
#: failed, partial, not-modified, not-remembered -- and fixes the keys every one
#: of them carries so a log query does not have to know which path produced it.
#: A seventh emitted from here would be a second schema for the same run, and a
#: "sweep completed" line would say what the run ledger row already records
#: durably.

#: What this collector is called, on its ledger rows and in its cache keys. It is
#: also what the shells it triggers record as their `identity_source`
#: (`CPM-FR-2`), which is the same name a run is traced to (`CPM-FR-39`).
COLLECTOR_NAME: Final[str] = "inventory"

#: The task's declared name. `cpm.collect.` is what `core/queues.py`'s derived
#: route table sends to the `collect` queue, and the workload class lives in the
#: name rather than in the module for the reason that module records: this
#: package will hold `verify` collectors too, so a route keyed on module path
#: could not tell a compute-backed build from a file read (`R-11`).
INGEST_TASK_NAME: Final[str] = "cpm.collect.inventory"

#: The upstream-release collection task's declared name, on the same terms
#: (`CPM-CURRENCY-S01`, `CPM-FR-7`). The `cpm.collect.` namespace is what routes
#: it to the `collect` queue with no edit to `core/queues.py`; it names the
#: *collector* rather than the module, because `CPM-EP-PY314` will put `verify`
#: work in this same package and a route keyed on module path could not tell a
#: compute-backed build from an HTTP read (`R-11`).
COLLECT_SOURCE_RELEASE_TASK_NAME: Final[str] = "cpm.collect.source_release"

#: The locator handed to the adapter, and it is deliberately opaque.
#:
#: `CPM-AD-29` makes an inventory source a transport substitution, so the adapter
#: already knows which file or endpoint it reads -- the locator's job here is to
#: name the *run* in the ledger's `detail` and in every log line, not to address a
#: resource. A path spelled here would be this module choosing the inventory
#: source, which is `CPM-IDENTITY-S07`'s and not this story's.
INVENTORY_SOURCE: Final[str] = "inventory://declared-adapter"

#: The record field naming the package, and the two signals every record carries.
#: `CPM-FR-42` and PRD Open Question 3b: together the counts are the "internal
#: usage breadth" `CPM-FR-4` ranks by, so a record without both is a record that
#: cannot be ranked and is refused rather than stored half-observed.
SOURCE_PACKAGE_KEY: Final[str] = "source_package_key"
REQUIRED_SIGNALS: Final[tuple[str, ...]] = ("internal_component_count", "internal_lob_count")

#: The record field naming the *package*, as against the key the source filed it
#: under, and every record carries one.
#:
#: The two are different facts and were the same value until `CPM-IDENTITY-S07`.
#: `source_package_key` is what the inventory calls this entry -- stable, the
#: thing a later sweep matches on, and never corrected -- while the name is what
#: the package is called, which `CPM-IDENTITY-S02` corrects when it establishes a
#: real identity. Writing one value into both `canonical_name` and
#: `associator_key` made the correction invisible: a lookup keyed on the
#: corrected name no longer matches the key the source still sends, and the next
#: sweep creates a second shell for the same package. Separating them does not by
#: itself close that trap -- resolution still has to match on
#: `(identity_source, associator_key)` -- but it stops the two values being
#: indistinguishable, which is what hid it.
PACKAGE_NAME: Final[str] = "package_name"

#: The signals a record may omit. Open Question 3b: they are score inputs for
#: `CPM-FR-20`, whose function is itself undecided, and no hand-authored source
#: can state them credibly -- so missing is an ordinary state and is stored as
#: NULL, which stays distinguishable from a stored `0`.
OPTIONAL_SIGNALS: Final[tuple[str, ...]] = ("apps", "platforms", "downloads", "versions")

#: Every field a record may carry, and nothing else is accepted. A record naming
#: a repository URL, a purl or a confidence is refused rather than having the
#: field ignored, because ingestion never asserts a mapping (`CPM-FR-42`,
#: `CPM-FR-1`) and a silently dropped column is a source that believes it is
#: supplying one.
RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {SOURCE_PACKAGE_KEY, PACKAGE_NAME, *REQUIRED_SIGNALS, *OPTIONAL_SIGNALS},
)

#: What an absence row says in its own words. Named so the row the sweep writes
#: and the case that reads it back cannot drift.
ABSENT_DETAIL: Final[str] = "the inventory source no longer lists this package"

#: The largest count a usage signal may carry.
#:
#: `PositiveIntegerField`'s ceiling, which is a signed 32-bit maximum on every
#: backend Django supports. Declared rather than left to the column because the
#: column enforces it on PostgreSQL and not on SQLite;
#: `tests/unit/django_apps/test_inventory_ingestion.py` reconciles this number
#: against the field's own validator, so a widened column is a failing test
#: rather than a silently unenforced bound.
MAX_COUNT: Final[int] = 2_147_483_647

#: How hard this collector may push its source. The base offers no opt-out, and a
#: generously declared allowance is the honest form for a source that is not rate
#: limited at all -- a fabricated small number would be a limit nobody measured.
INVENTORY_RATE_LIMIT: Final[RateLimit] = RateLimit(calls=60, per=timedelta(seconds=60))

#: How long this collector's evidence may be read as current (`CPM-AD-28`).
#:
#: Two days, and it is derived rather than picked. PRD Open Question 7 was
#: resolved on 2026-09-05 and fixes the rule:
#:
#:     freshness_target = cadence x (1 + tolerated_missed_runs) + one sweep duration
#:
#: Inventory ingestion's cadence is daily (`CPM-NFR-2`) and its signal class
#: tolerates one missed run, which gives two days.
#:
#: **The target is strictly greater than the cadence, and that is the rule rather
#: than the arithmetic.** `core/freshness.py` reports stale when
#: `observed_at < now - target`, so a target *equal* to the cadence makes evidence
#: go stale at exactly the moment the next run is due -- any delay in scheduling
#: and the whole inventory reads stale without one collection having failed. That
#: is why this is two days and not the one a "daily sweep, daily target" reading
#: would give.
#:
#: What is still owed is Open Question 7b's measurement: a target must also exceed
#: one sweep's wall-clock duration, and no sweep has run at `CPM-NFR-1`'s ten
#: thousand packages yet. This value assumes a sweep finishes well inside its
#: cadence, which `CPM-EP-CURRENCY` is where it is confirmed.
INVENTORY_FRESHNESS_TARGET: Final[timedelta] = timedelta(days=2)

#: The declared inventory source adapter, by the one slot there is.
#:
#: A module-level mapping rather than a rebound global, for the reason
#: `core/registry.py`'s is one: ruff `PLW0603` forbids the `global` statement,
#: and a `from ... import` of a rebound name would bind a copy that never
#: observes a later write.
_DECLARED: Final[dict[str, Transport]] = {}

#: The key `_DECLARED` holds the adapter under. One slot, because `CPM-AD-29`
#: says ingestion "reads exactly one inventory source adapter": two would make
#: "which source is this component's inventory" a question answered by import
#: order.
_ADAPTER_SLOT: Final[str] = COLLECTOR_NAME


class InventoryAdapterError(ValueError):
    """No usable inventory source adapter is declared, or two are.

    A `ValueError` subclass on the same terms as `core/registry.py`'s
    `CollectorRegistryError`, which it is deliberately shaped after: adapters are
    declared, never discovered (inherited `AD-8`), and a duplicate is refused
    rather than overwritten because the second one silently replacing the first
    is how a deployed component comes to ingest a development subset -- and every
    package outside that subset is then recorded absent, permanently, in a log
    nothing may update (`CPM-AD-29`).
    """


class InventoryRecordError(ValueError):
    """A source document could not be read as inventory records.

    Raised before any row is written, which is the whole of `CPM-FR-42`'s "no run
    partially ingests a malformed source". The alternative -- skipping the bad
    record and ingesting the rest -- writes an absence observation for every
    package the truncated document failed to name, into an append-only log that
    nothing may correct.
    """


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    """One package as the inventory source describes it.

    The contract `CPM-AD-29` calls "yield records, or fail", as data. It is
    deliberately not the watchlist's shape: `CPM-IDENTITY-S07` owns the file, its
    columns and its delimiter, and an adapter's job is to turn one into these.
    Frozen and slotted, so a record cannot be edited between being read and being
    written.

    Attributes:
        source_package_key: The key the source used for this package. It becomes
            the shell's `associator_key`: the stable thing a later sweep, and a
            later resolution, matches this package back on.
        package_name: What the source calls the package. It becomes the shell's
            `canonical_name`, which is the one *correctable* name --
            `CPM-IDENTITY-S02` rewrites it when it establishes a real identity,
            and the key above is what survives that rewrite.
        internal_component_count: How many internal components use the package.
        internal_lob_count: How many internal lines of business use it.
        apps: How many applications name it, or `None` where the source did not
            say. `None` is *missing*, and stays distinguishable from `0`.
        platforms: How many platforms it is used on, or `None`.
        downloads: How many internal downloads it has, or `None`.
        versions: How many versions of it are in use, or `None`.

    """

    source_package_key: str
    package_name: str
    internal_component_count: int
    internal_lob_count: int
    apps: int | None = None
    platforms: int | None = None
    downloads: int | None = None
    versions: int | None = None


def declare_inventory_adapter(adapter: Transport) -> Transport:
    """Adopt one inventory source adapter for this process.

    Args:
        adapter: The `Transport` the ingestion task reads its document through.

    Returns:
        The adapter, unchanged, so a caller can bind it in one statement.

    Raises:
        InventoryAdapterError: When the object is not a `Transport`, or when one
            is already declared. `Transport` is `runtime_checkable`, so this
            check sees method *names* only -- which is the same bound
            `core/transport.py` records, and the reason a case pins what `fetch`
            returns as well as that it exists.

    """
    if not isinstance(adapter, Transport):
        message = (
            f"{adapter!r} is not a Transport and cannot be the inventory source adapter. An adapter is a "
            f"transport substitution at the collector base's seam (CPM-AD-29), so it answers fetch() with a "
            f"recorded Payload and nothing else is required of it."
        )
        raise InventoryAdapterError(message)
    existing = _DECLARED.get(_ADAPTER_SLOT)
    if existing is not None:
        message = (
            f"{type(adapter).__name__} cannot be declared: {type(existing).__name__} is already this "
            f"component's inventory source adapter. Ingestion reads exactly one (CPM-AD-29); a second one "
            f"silently replacing the first is how a deployed component ingests a development subset and "
            f"records every package outside it as absent."
        )
        raise InventoryAdapterError(message)
    _DECLARED[_ADAPTER_SLOT] = adapter
    return adapter


def withdraw_inventory_adapter() -> None:
    """Withdraw the declared inventory source adapter.

    Symmetric with `declare_inventory_adapter` rather than a test hook bolted on,
    for the reason `core/registry.py`'s `unregister` is: the declaration is
    process-global, so a case that could only add to it could never measure the
    refusal when nothing is declared, and one that left an adapter behind would
    change what every later case ingests.

    Raises:
        InventoryAdapterError: When nothing is declared. Refused rather than
            ignored, because a silent no-op turns a mistaken withdrawal into a
            declaration that stays live and a caller that believes it does not.

    """
    if _ADAPTER_SLOT not in _DECLARED:
        message = (
            "no inventory source adapter is declared, so there is nothing to withdraw. "
            "Declare one with declare_inventory_adapter (CPM-AD-29)."
        )
        raise InventoryAdapterError(message)
    del _DECLARED[_ADAPTER_SLOT]


def declared_inventory_adapter() -> Transport | None:
    """Return the declared inventory source adapter, or `None` when there is none.

    The read `inventory_adapter` below refuses on, without the refusal. It exists
    for one caller shape and is shaped after `core/registry.py`'s `registrations`,
    which `CollectorsConfig.ready()` already reads for the same reason: a boot
    hook has to be able to *ask* whether the declaration it is about to make has
    already been made, because `AppConfig.ready` is Django's to call and a second
    `django.setup()` in one process calls it again. Asking through
    `inventory_adapter` would mean catching the refusal as control flow, and
    declaring unconditionally would abort boot over a declaration that had
    already succeeded.

    Returns:
        The adapter this component reads its inventory through, or `None` when
        nothing is declared. `None` is an answer here and never a default: a
        caller that wants the run refused calls `inventory_adapter`.

    """
    return _DECLARED.get(_ADAPTER_SLOT)


def inventory_adapter() -> Transport:
    """Return the declared inventory source adapter.

    Returns:
        The adapter this component reads its inventory through.

    Raises:
        InventoryAdapterError: When none is declared. The run is refused here,
            before the recorder opens and therefore before any row exists --
            which is the matrix row that says ingestion with no source leaves no
            trace of a run that could not have observed anything.

    """
    adapter = _DECLARED.get(_ADAPTER_SLOT)
    if adapter is None:
        message = (
            "no inventory source adapter is declared, so there is nothing to ingest. Adapters are declared "
            "and never discovered (AD-8, CPM-AD-29): CPM-IDENTITY-S07 declares the watchlist adapter, and "
            "until one is bound the run is refused rather than recorded as an empty inventory."
        )
        raise InventoryAdapterError(message)
    return adapter


def records_in(payload: Payload) -> tuple[InventoryRecord, ...]:
    """Decode a whole source document into records, or refuse the document.

    The record contract `CPM-AD-29` names, applied to what the adapter recorded.
    The document is decoded in full before this returns, which is what makes
    "no run partially ingests a malformed source" true: the caller has either
    every record or none, and never a prefix.

    Args:
        payload: What the adapter said, recorded. Its `body` is a JSON array of
            record objects -- a neutral encoding chosen here rather than the
            source's own, because the file format belongs to the adapter
            (`CPM-IDENTITY-S07`) and the collector must be unchanged by which one
            is active.

    Returns:
        One record per entry, in the document's own order.

    Raises:
        InventoryRecordError: When the body is not a JSON array of objects, when
            a record omits a required signal or carries one that is not a
            non-negative integer, when it carries a field the contract does not
            define, or when two records share a source package key.

    """
    try:
        document = json.loads(payload.body)
    except json.JSONDecodeError as unreadable:
        message = (
            f"{payload.source} did not yield a readable inventory document: "
            f"{type(unreadable).__name__}: {unreadable}. The run is refused rather than treated as an empty "
            f"inventory, which would record every package it should have named as absent (CPM-FR-42)."
        )
        raise InventoryRecordError(message) from unreadable
    if not isinstance(document, list):
        message = (
            f"{payload.source} yielded {type(document).__name__} rather than a list of inventory records. "
            f"An adapter yields records or fails (CPM-AD-29)."
        )
        raise InventoryRecordError(message)
    if not document:
        # A well-formed empty array is the most dangerous document there is, and
        # it is the one a reader most expects to be harmless. It is *not* an
        # inventory of no packages: it is a source that told this run nothing,
        # and a sweep that accepted it would record every package the system has
        # ever seen as departed -- permanently, in an append-only log, and
        # replayable at every later cut-off. A source with genuinely nothing to
        # say has stopped being an inventory source (CPM-FR-42, CPM-AD-29).
        message = (
            f"{payload.source} yielded an inventory naming no packages at all. That is refused rather than "
            f"ingested: an empty document is indistinguishable from a source that broke, and accepting one "
            f"would record every package the inventory has ever named as absent, in a log nothing may "
            f"correct (CPM-FR-42, CPM-AD-25)."
        )
        raise InventoryRecordError(message)

    records = tuple(_record(entry, position=position) for position, entry in enumerate(document))
    _refuse_repeated_keys(records, source=payload.source)
    return records


def _record(entry: object, *, position: int) -> InventoryRecord:
    """Turn one decoded entry into a record, refusing anything it cannot be.

    Args:
        entry: One element of the decoded document.
        position: Where it sat, so a refusal names the record a reader can find
            rather than only saying that one of them was wrong.

    Returns:
        The record.

    Raises:
        InventoryRecordError: When the entry is not an object, carries an
            undefined field, names no package, gives that package no name, or
            carries a signal that is not a non-negative integer.

    """
    if not isinstance(entry, dict):
        message = (
            f"inventory record {position} is {type(entry).__name__} rather than an object. Every record "
            f"names a package and its usage signals (CPM-FR-42)."
        )
        raise InventoryRecordError(message)
    undefined = sorted(set(entry) - RECORD_FIELDS)
    if undefined:
        message = (
            f"inventory record {position} carries the field(s) {undefined}, which the record contract does "
            f"not define. The run is refused rather than the field ignored: ingestion never asserts a "
            f"mapping (CPM-FR-42, CPM-FR-1), and a silently dropped field is a source that believes it "
            f"supplied one."
        )
        raise InventoryRecordError(message)
    key = entry.get(SOURCE_PACKAGE_KEY)
    if not isinstance(key, str) or not key.strip():
        message = (
            f"inventory record {position} declares {SOURCE_PACKAGE_KEY}={key!r} and names no package. "
            f"A record that cannot be traced back to a package key is one nothing can re-derive (CPM-FR-2)."
        )
        raise InventoryRecordError(message)
    name = key.strip()
    if len(name) > ASSOCIATOR_KEY_LENGTH:
        # Refused *here*, in the contract, rather than left to resolution.
        # `resolve_package_shell` refuses the same key, but it refuses it one
        # package at a time and halfway through a sweep -- which is a `partial`
        # run over a source that was malformed from the start, and `CPM-FR-42`
        # says no run partially ingests a malformed source. A document is either
        # ingestable whole or refused whole.
        #
        # The bound is `associator_key`'s, which is the column the key lands in
        # since `CPM-IDENTITY-S07` separated it from the name. The name has its
        # own, narrower bound below.
        message = (
            f"inventory record {position} declares a {SOURCE_PACKAGE_KEY} of {len(name)} characters, and "
            f"the column that holds it takes {ASSOCIATOR_KEY_LENGTH}. The document is refused rather than "
            f"ingested until this record: no run partially ingests a malformed source (CPM-FR-42)."
        )
        raise InventoryRecordError(message)
    package_name = _require_package_name(entry.get(PACKAGE_NAME), position=position)
    # Written out rather than unpacked from two mappings built over
    # `REQUIRED_SIGNALS` and `OPTIONAL_SIGNALS`. The mapping form needed a
    # blanket `# type: ignore[arg-type]` -- `dict[str, int | None]` cannot be
    # unpacked into parameters typed `int` -- and an ignore that wide would have
    # hidden a real signature change as readily as the one it was there for.
    # `test_the_record_fields_are_exactly_the_declared_signals` reconciles these
    # names against the two tuples in both directions, which is what a mapping
    # bought and is cheaper than what it cost.
    return InventoryRecord(
        source_package_key=name,
        package_name=package_name,
        internal_component_count=_required_count(
            entry.get("internal_component_count"),
            field="internal_component_count",
            key=name,
        ),
        internal_lob_count=_required_count(entry.get("internal_lob_count"), field="internal_lob_count", key=name),
        apps=_optional_count(entry.get("apps"), field="apps", key=name),
        platforms=_optional_count(entry.get("platforms"), field="platforms", key=name),
        downloads=_optional_count(entry.get("downloads"), field="downloads", key=name),
        versions=_optional_count(entry.get("versions"), field="versions", key=name),
    )


def _require_package_name(value: object, *, position: int) -> str:
    """Return the name the record gives its package, or refuse the record.

    Required of every record, and refused *here* for the reason the key's own
    bound is refused here: the document is decoded whole before the first row is
    written, so a record that could not produce a usable identity fails the run
    with nothing ingested rather than one package at a time halfway through a
    sweep (`CPM-FR-42`).

    The bound is `canonical_name`'s, because that is the column the name lands
    in. It is the same number the key is measured against above and it is checked
    against a different column: SQLite ignores `max_length` and PostgreSQL
    refuses, so an over-long name is a stored row on a developer's machine and a
    failed run in the gate unless it is refused where the value enters (`R-5`).

    Args:
        value: What the record carried for the name, or `None` when it carried
            nothing.
        position: Where the record sat, for the message.

    Returns:
        The name with surrounding whitespace removed.

    Raises:
        InventoryRecordError: When the record names no package, or names one
            longer than the column that has to hold it.

    """
    if not isinstance(value, str) or not value.strip():
        message = (
            f"inventory record {position} declares {PACKAGE_NAME}={value!r} and gives its package no name. "
            f"The name is what the shell's canonical name is created from, and a package with no name "
            f"cannot be corrected, exported or found again (CPM-FR-2)."
        )
        raise InventoryRecordError(message)
    name = value.strip()
    if len(name) > CANONICAL_NAME_LENGTH:
        message = (
            f"inventory record {position} declares a {PACKAGE_NAME} of {len(name)} characters, and a "
            f"package name holds {CANONICAL_NAME_LENGTH}. The document is refused rather than ingested "
            f"until this record: no run partially ingests a malformed source (CPM-FR-42)."
        )
        raise InventoryRecordError(message)
    return name


def _required_count(value: object, *, field: str, key: str) -> int:
    """Return one of the two counts every record must carry, or refuse the record.

    Args:
        value: What the record carried for this signal, or `None` when it carried
            nothing.
        field: Which signal, for the message.
        key: The record's source package key, for the message.

    Returns:
        The count.

    Raises:
        InventoryRecordError: When the signal is absent, or is not a count.

    """
    if value is None:
        message = (
            f"inventory record {key!r} declares no {field}. Both {' and '.join(REQUIRED_SIGNALS)} are "
            f"required on every record: together they are the internal usage breadth CPM-FR-4 ranks by, "
            f"and a record without them cannot be ranked (PRD Open Question 3b)."
        )
        raise InventoryRecordError(message)
    return _require_count(value, field=field, key=key)


def _optional_count(value: object, *, field: str, key: str) -> int | None:
    """Return one of the four nullable score inputs, or `None` for a missing one.

    Args:
        value: What the record carried for this signal, or `None` when it carried
            nothing.
        field: Which signal, for the message.
        key: The record's source package key, for the message.

    Returns:
        The count, or `None` when the source did not supply one. `None` means
        *missing* and is stored as NULL, which stays distinguishable from a
        stored `0` -- so a `0` here comes back as `0` and is never collapsed
        (PRD Appendix A.1 data rules, Open Question 3b).

    Raises:
        InventoryRecordError: When a present value is not a count.

    """
    if value is None:
        return None
    return _require_count(value, field=field, key=key)


def _require_count(value: object, *, field: str, key: str) -> int:
    """Refuse a usage signal that is not a count this schema can hold.

    Args:
        value: What the record carried, already known not to be `None`.
        field: Which signal, for the message.
        key: The record's source package key, for the message.

    Returns:
        The count, unchanged.

    Raises:
        InventoryRecordError: When the value is not a whole number, is negative,
            or exceeds what the column holds.

            `bool` is refused explicitly: it is a subclass of `int`, so `true` in
            a document would otherwise be a component count of one.

            Both bounds are refused *here* rather than left to the column, and
            for one reason: `PositiveIntegerField` is a check constraint on
            PostgreSQL and a suggestion on SQLite, so a negative or an oversized
            count is a stored row on a developer's machine and a failed run in
            the gate. That is `R-5`'s parity gap arriving through the one input
            this collector takes from outside, and it is closed where the value
            enters rather than where it lands.

    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_COUNT:
        message = (
            f"inventory record {key!r} declares {field}={value!r}, which is not a count this schema can "
            f"hold. A usage signal is a whole number between 0 and {MAX_COUNT}; omit it entirely to record "
            f"that the source did not say, which is stored as missing and stays distinguishable from zero "
            f"(PRD Appendix A.1 data rules)."
        )
        raise InventoryRecordError(message)
    return value


def _refuse_repeated_keys(records: Sequence[InventoryRecord], *, source: str) -> None:
    """Refuse a document that names one package twice.

    `CPM-FR-42`: a record "repeating a source package key fails the run". Two
    records for one key are two different claims about the same package's usage
    in one observation, and there is no rule for choosing between them that is
    not an invention -- so the document is refused rather than the last one
    winning by arriving second.

    Args:
        records: Every record the document yielded.
        source: The locator, for the message.

    Raises:
        InventoryRecordError: When any source package key appears more than once.

    """
    # `Counter` rather than `list.count` inside a comprehension over the same
    # list. The latter is one pass per record over every record, which at
    # `CPM-NFR-1`'s ten thousand packages is a hundred million comparisons on
    # every sweep, for a check that has to be linear to be worth having.
    repeated = sorted(key for key, seen in Counter(record.source_package_key for record in records).items() if seen > 1)
    if repeated:
        message = (
            f"{source} names the package key(s) {repeated} more than once. One observation records one fact "
            f"per package (CPM-AD-7); two records for one key are two claims about the same package, and "
            f"choosing between them would be an invention (CPM-FR-42)."
        )
        raise InventoryRecordError(message)


class InventoryIngestionCollector(Collector):
    """The collector that observes the internal inventory. Writes `inventory_snapshots`.

    See the module docstring for why it never writes the package table, why the
    transaction is per package, and why its three per-package hooks refuse.
    """

    #: The nine declarations the base checks at construction. Every one is
    #: written out, including the two that would otherwise inherit a usable
    #: default, because a declaration a reader has to go and look up in the base
    #: is one they cannot check against the source this collector reads.
    name: ClassVar[str] = COLLECTOR_NAME

    evidence_model: ClassVar[type[AppendOnlyModel] | None] = InventorySnapshot

    #: `NO_WINDOW`: observe on every run. A sweep that was scheduled has been
    #: asked to run, and suppressing it would suppress the absence observations
    #: too -- absence is the signal that decays, so it is the one that must not
    #: be skipped.
    observation_window: ClassVar[timedelta | None] = NO_WINDOW

    #: The cap `core/transport.py` allows, rather than a smaller number pretending
    #: to have been measured. A timeout is required of every collector and means
    #: nothing to a file adapter, so the honest declaration is the bound.
    timeout: ClassVar[float | None] = MAX_TIMEOUT

    #: None. A malformed or unreachable local document does not become
    #: well-formed on a second read, and `CPM-IDENTITY-S07` refuses it outright.
    retries: ClassVar[int] = 0

    rate_limit: ClassVar[RateLimit] = INVENTORY_RATE_LIMIT

    #: Empty, and declared empty. A file adapter ignores request headers, and the
    #: base refuses a conditional one from any collector anyway.
    headers: ClassVar[Mapping[str, str]] = MappingProxyType({})

    freshness_target: ClassVar[timedelta | None] = INVENTORY_FRESHNESS_TARGET

    #: `NO_CACHE`: short-circuits the cache read, the cache write and the
    #: conditional headers, so no `ETag` machinery runs against a source that has
    #: no validators to offer.
    response_cache_ttl: ClassVar[timedelta | None] = NO_CACHE

    def sweep_source(self) -> str:
        """Return the locator this run names in its ledger row and its logs.

        Returns:
            `INVENTORY_SOURCE`, which is opaque on purpose -- see its own
            comment. The adapter knows which file or endpoint it reads
            (`CPM-AD-29`); this collector must not.

        """
        return INVENTORY_SOURCE

    def persist_sweep(self, payload: Payload, *, observed_at: datetime) -> SweepOutcome:
        """Write one snapshot per package the document names, and one per absence.

        The whole of `CPM-AD-25`'s write path. The document is decoded in full
        first, so a malformed source leaves nothing behind; then each record gets
        one transaction of its own, in which resolution creates the shell if
        there is none and the snapshot is inserted beside it. A package that
        cannot be persisted is recorded as a failure and the sweep continues,
        which is what makes the run `partial` rather than losing the packages
        that worked (`CPM-AD-23`, `CPM-FR-15`).

        **Absences are recorded only by a run that observed something**, and that
        is the guard rather than an optimisation. An absence row asserts "the
        source no longer lists this package", which is a claim about a document
        this run read and acted on. A run whose every record failed read a
        document it could not act on at all, and writing absences off the back of
        it would record every package the source *did* still list as departed --
        permanently, in a log nothing may correct. `records_in` refuses an empty
        document for the same reason, one step earlier.

        Args:
            payload: What the adapter said, recorded.
            observed_at: The instant every row must carry, from the base's
                injected clock. Handed to the absence rows too: they are
                observations made by *this* run (`CPM-AD-7`).

        Returns:
            How many rows the records produced, how many their absence implied,
            and which packages could not be written.

        Raises:
            InventoryRecordError: When the document cannot be read as records.
                Raised before the first write, so the run fails with nothing
                ingested.

        """
        records = records_in(payload)
        trace_id = current_trace_id()
        observed = 0
        failures: list[str] = []
        for record in records:
            try:
                observed += self._observe(record, observed_at=observed_at, trace_id=trace_id)
            # Narrow, and both are reachable: resolution refuses a record it
            # cannot make an identity from, and the database refuses a row this
            # schema will not take. Neither is swallowed -- each becomes a
            # failure the ledger row names, which is what `partial` means.
            except (ResolutionError, DatabaseError) as unwritable:
                failures.append(f"{record.source_package_key}: {type(unwritable).__name__}: {unwritable}")
        derived = 0
        if observed:
            derived = self._observe_absences(
                named={record.source_package_key for record in records},
                observed_at=observed_at,
                trace_id=trace_id,
            )
        return SweepOutcome(observed_rows=observed, derived_rows=derived, failures=tuple(failures))

    def _observe(self, record: InventoryRecord, *, observed_at: datetime, trace_id: str) -> int:
        """Commit one package's shell and its snapshot, together.

        `transaction.atomic()` is *here* -- around one package -- and nowhere
        else in this module but its sibling below. It is nested inside the base's
        run recorder and never around it (`CPM-AD-23`), which
        `tests/unit/django_apps/test_inventory_ingestion.py` asserts structurally
        over this file.

        The row goes to `_write_evidence` rather than to `bulk_create`, which is
        what applies the base's declared-model and `observed_at` checks and puts
        it in the tally `Collector._require_counted` reconciles on the way out.

        Args:
            record: The package as the source described it.
            observed_at: The instant the row carries.
            trace_id: The run's correlation identifier (`CPM-AD-15`).

        Returns:
            How many rows were inserted, which is one.

        Raises:
            ResolutionError: When the record cannot produce a usable identity.
            DatabaseError: When the row is one this schema will not take.

        """
        with transaction.atomic():
            package = resolve_package_shell(
                source_package_key=record.source_package_key,
                package_name=record.package_name,
                identity_source=COLLECTOR_NAME,
                clock=self._clock,
            )
            return self._write_evidence(
                [
                    InventorySnapshot(
                        observed_at=observed_at,
                        package=package,
                        source_package_key=record.source_package_key,
                        state=OutcomeState.OK.value,
                        internal_component_count=record.internal_component_count,
                        internal_lob_count=record.internal_lob_count,
                        apps=record.apps,
                        platforms=record.platforms,
                        downloads=record.downloads,
                        versions=record.versions,
                        detail="",
                        trace_id=trace_id,
                    ),
                ],
                observed_at=observed_at,
            )

    def _observe_absences(self, *, named: set[str], observed_at: datetime, trace_id: str) -> int:
        """Record the packages that have just stopped being named, as observations.

        `CPM-AD-25`: absence is a row and never a deletion. The set is derived
        from the evidence rather than from the package table, and that is the
        narrower question: a package the *inventory* once listed and no longer
        does is what this collector observed, while a package row created by some
        other path was never this source's to say anything about.

        **Absence is recorded on the transition, not on every run, and the
        difference is the difference between an observation and a leak.** A
        package the source drops is absent from then on, so a rule of "write a
        row whenever the key is missing" writes one per sweep for ever, into a
        table nothing may prune -- ten thousand packages a day for one package
        that left. What is worth recording is that it *changed*: the run in which
        a package's latest observation stops being `ok` is the run that observed
        something new. So the latest state per package is what is read, and only a
        package whose latest is `ok` is recorded absent.

        That still leaves the absence re-readable at any later cut-off, which is
        what `snapshot_as_of` is for: the row's `observed_at` is when the package
        went, and no row after it means nothing has changed since.

        **A refused absence row fails the run rather than becoming a per-package
        failure**, which is the one place this method departs from `_observe`
        above. A record's failure is a fact about what the source supplied and
        the sweep can carry on past it; an absence row is built entirely from
        rows this table already holds, so a database that refuses one is refusing
        a row it accepted the makings of -- there is nothing to carry on from,
        and a run that swallowed it would report `partial` over a schema defect.

        Args:
            named: Every source package key the document carried, including the
                ones whose write failed -- a package that could not be persisted
                was named, so recording it absent would be false.
            observed_at: The instant the absence rows carry -- this run's, which
                is what makes "absent as of when" answerable.
            trace_id: The run's correlation identifier.

        Returns:
            How many absence rows were written.

        Raises:
            DatabaseError: When an absence row is refused. See above.

        """
        # Ordered ascending and folded into a mapping, so what survives per
        # package is its *latest* state and the key it was last seen under.
        # `distinct(*fields)` would do this in the database in one row per
        # package, and it is PostgreSQL-only while this suite runs on SQLite
        # locally -- so the fold is here. Rows for a key this document still
        # names are excluded first: a package keeps one key for its whole life
        # (the key is what its `associator_key` was created from, and unlike its
        # `canonical_name` nothing corrects it), so a named key is a package that
        # cannot be absent.
        latest: dict[int, tuple[str, str]] = {
            package_id: (state, key)
            for package_id, state, key in InventorySnapshot.objects.exclude(source_package_key__in=named)
            .order_by("observed_at", "pk")
            .values_list("package_id", "state", SOURCE_PACKAGE_KEY)
        }

        written = 0
        for package_id, (state, key) in latest.items():
            if state != OutcomeState.OK.value:
                continue
            # One transaction per package here too (`CPM-AD-23`), so an absence
            # row commits with the packages around it rather than with the whole
            # sweep. The row goes through the base for the reason `_observe`'s
            # does: it is what stamps-checks it and puts it in the tally.
            with transaction.atomic():
                written += self._write_evidence(
                    [
                        InventorySnapshot(
                            observed_at=observed_at,
                            package_id=package_id,
                            source_package_key=key,
                            state=OutcomeState.NOT_FOUND.value,
                            detail=ABSENT_DETAIL,
                            trace_id=trace_id,
                        ),
                    ],
                    observed_at=observed_at,
                )
        return written

    def source_for(self, *, package_id: int) -> str:
        """Refuse: this collector reads one document, not one locator per package.

        Args:
            package_id: The package a per-package caller asked about.

        Raises:
            CollectorConfigurationError: Always. Returning the document's own
                locator would make `collect(package_id=...)` re-read the whole
                inventory to observe one package -- a defect that would look
                like it worked.

        """
        self._no_per_package_path("source_for", package_id=package_id)

    def translate(self, payload: Payload, *, package_id: int, observed_at: datetime) -> Sequence[AppendOnlyModel]:
        """Refuse: a run-scoped document is not one package's payload.

        Args:
            payload: What a per-package caller recorded.
            package_id: The package it asked about.
            observed_at: The instant it would have stamped.

        Raises:
            CollectorConfigurationError: Always. `persist_sweep` is this
                collector's translation, and it writes many packages' rows in
                many transactions rather than returning one package's.

        """
        self._no_per_package_path("translate", package_id=package_id)

    def sentinel_evidence(
        self,
        *,
        state: OutcomeState,
        package_id: int,
        observed_at: datetime,
        detail: str,
    ) -> AppendOnlyModel:
        """Refuse: a failing sweep has no one package to write a sentinel row about.

        Args:
            state: The sentinel a per-package caller decided on.
            package_id: The package it asked about.
            observed_at: The instant it would have stamped.
            detail: What it says happened.

        Raises:
            CollectorConfigurationError: Always. The `not_found` rows this
                collector *does* write are absence observations about packages
                the source named before, written by `persist_sweep` where the key
                each was last seen under is known -- which this signature has no
                way to carry.

        """
        self._no_per_package_path("sentinel_evidence", package_id=package_id)

    def _no_per_package_path(self, hook: str, *, package_id: int) -> NoReturn:
        """Refuse for all three per-package hooks, in one place.

        Written once because the three refusals are one decision, and three
        separately worded messages would read as three different limitations.
        It raises rather than returning the exception for the caller to raise:
        `NoReturn` is what tells the type checker that a hook whose body is only
        this call still honours its own return annotation.

        Args:
            hook: Which hook was called, so the message names it.
            package_id: The package the caller asked about.

        Raises:
            CollectorConfigurationError: Always.

        """
        message = (
            f"{type(self).__name__}.{hook} was asked about package {package_id}, and this collector has no "
            f"per-package path. Inventory ingestion reads one document naming many packages (CPM-AD-25); it "
            f"is run through sweep(), and collect(package_id=...) belongs to the collectors that observe a "
            f"surface about a package the inventory already names."
        )
        raise CollectorConfigurationError(message)


@shared_task(name=INGEST_TASK_NAME)  # type: ignore[untyped-decorator]
def ingest_inventory(*, force: bool = False) -> str:
    """Ingest the inventory once, through the declared adapter.

    The `cpm.collect.` name is what routes this to the `collect` queue, derived
    by `core/queues.py` with no edit there. It declares **no schedule and no time
    limit**: cadence is data in `django_celery_beat` (`CPM-AD-20`, `CPM-NFR-2`),
    and the inherited limits are settings' (`CPM-AD-9`) --
    `tests/unit/django_apps/test_task_declaration_audit.py` is the gate on both.

    Args:
        force: Bypass the observation window, for `CPM-UJ-1`'s manually
            triggered recollection. Keyword-only, so a caller can never enqueue a
            forced run by getting an argument's position wrong.

            **It is inert for this collector today, and it is plumbed through
            anyway.** The window is `NO_WINDOW`, which the base short-circuits
            rather than querying, so nothing is being bypassed. What the
            parameter is for is the manual-recollection path itself: an operator
            triggering a sweep by hand goes through this task, and a task that
            could not carry the flag would have to grow one the day the window
            became non-zero -- at which point every existing caller would be
            silently subject to a window they had not asked for.
            `tests/integration/django_apps/test_inventory_ingestion.py` pins that
            it reaches the base rather than being dropped here.

    Returns:
        How the run ended, as the `RunState` value the ledger row carries. A
        string rather than the `CollectionResult`, because a task's return value
        is serialized into the result backend and the durable record of the run
        is the ledger row.

    Raises:
        InventoryAdapterError: When no adapter is declared. Raised before the
            recorder opens, so a component with no inventory source leaves no run
            row claiming to have observed an empty inventory.
        InventoryRecordError: When the declared adapter yields a document that is
            not readable as records. It escapes the task rather than being turned
            into a failed return value, which is what makes the whole document
            refused rather than half-ingested (`CPM-FR-42`); the ledger row is
            finalized to `failed` by the recorder on the way out, so the run is
            on the record even though nothing else is.
        ImproperlyConfigured: When the declared adapter refuses its *source*
            before it has produced a document at all -- `CPM-IDENTITY-S07`'s
            watchlist adapter raises `WatchlistError`, an `ImproperlyConfigured`,
            for a file that is missing, malformed or awaiting review. It leaves
            by the same route and with the same consequence as the line above:
            the base's transport handling catches `TransportError` and nothing
            else, so a misconfigured *source file* is not a recorded transport
            failure, it is a refused run. The distinction is the point --
            `CPM-AD-14` makes a bad watchlist a misconfigured deployment, and an
            operator is sent to the file rather than to a broken remote.
        CollectorConfigurationError: When the rows this collector reports writing
            are not the rows the base wrote. A defect in this class rather than
            in a source, and refused rather than recorded.

    """
    with InventoryIngestionCollector(clock=SystemClock(), transport=inventory_adapter()) as collector:
        return str(collector.sweep(force=force).state.value)


@shared_task(name=COLLECT_SOURCE_RELEASE_TASK_NAME)  # type: ignore[untyped-decorator]
def collect_source_release(*, package_id: int, force: bool = False) -> str:
    """Observe one package's upstream releases (`CPM-FR-7`).

    Package-scoped, where ingestion above is run-scoped, and that is the whole
    difference between them: this collector reads one locator per package
    (`CPM-AD-7`), so the unit of work is one package and the transaction and the
    ledger row are one package's too (`CPM-AD-23`). No transport is passed --
    the base builds one from the collector's declared timeout and retry count,
    which is the only place either becomes a call setting.

    It declares **no schedule and no time limit**: cadence is data in
    `django_celery_beat` (`CPM-AD-20`, `CPM-NFR-2`) and the inherited limits are
    settings' (`CPM-AD-9`). Nothing schedules this yet -- `CPM-CURRENCY-S05` owns
    the full-inventory sweep and the selection of the packages that have a source
    repository at all.

    Args:
        package_id: The package to observe, by the integer primary key
            `CPM-AD-3` fixes. Keyword only, so a caller can never enqueue a
            collection for the wrong package by getting an argument's position
            wrong.
        force: Bypass the observation window, for `CPM-UJ-1`'s manually triggered
            recollection.

    Returns:
        How the run ended, as the `RunState` value the ledger row carries. A
        string rather than the `CollectionResult`, because a task's return value
        is serialized into the result backend and the durable record of the run
        is the ledger row.

    Raises:
        RunLedgerError: When `package_id` names no package. The recorder checks
            the key before it writes the opening row (`CPM-EVIDENCE-S09`), so
            this leaves nothing behind at all.
        SourceLocatorError: When the package has no source repository, or has one
            this collector cannot read. The ledger row is finalized `failed`
            carrying the reason; see that class for why it is not an evidence row.
        SourceReleaseDocumentError: When the source served something that is not a
            release document. An `error` evidence row is written first and the
            ledger row is `failed`, so the run is on the record either way.

    """
    with SourceReleaseCollector(clock=SystemClock()) as collector:
        return str(collector.collect(package_id=package_id, force=force).state.value)
