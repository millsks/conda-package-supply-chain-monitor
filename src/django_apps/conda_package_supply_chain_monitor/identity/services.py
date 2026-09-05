"""Resolution: the only thing in this product that creates a package row.

`CPM-AD-25`: "the collector never writes the package table. For a source record
naming a package that does not exist yet, it calls `identity`'s resolution
service, which creates the shell at `unmapped` confidence." `CPM-AD-14` is the
other half and is unchanged: identity is mutated by resolution or by the override
path, and by nothing else. This module is the door that sentence names.

**Only the shell, and deliberately only the shell.** `CPM-IDENTITY-S02` owns
resolution proper -- the source repository, the purls, the feedstocks, the
confidence above `unmapped` -- and it arrives behind this same door. What is here
is the one entry point ingestion needs: a package named by the inventory for the
first time gets an identity row *before* anything has resolved it, and
`unmapped` is the honest value for that row rather than a placeholder waiting to
be corrected. `CPM-FR-1` is explicit that a resolution which cannot establish a
mapping records nothing rather than a guess, so this asserts no mapping at all.

**The canonical name is the source's key, until resolution says otherwise.**
Ingestion knows one name for a package -- the key the inventory source used --
and `CPM-FR-2` requires the key a resolution matched on to be kept so the
resolution can be re-derived and disputed. Writing the key as
`canonical_name` is therefore not a guess: it is the only name that exists at
this point, and `canonical_name` is documented as "the one *correctable* name",
correctable precisely because nothing in this product references a package by it.
`CPM-IDENTITY-S02` corrects it when it establishes a real identity, and no
foreign key cascades when it does.

**Get-or-create, not create.** A sweep runs daily over a source that names the
same packages every time, so the second run must find the rows the first one made
rather than refusing on `canonical_name`'s unique constraint. It is also not an
`update_or_create`: an existing package row is left exactly as it is, including
its `confidence` -- ingestion must never lower a `verified` identity back to
`unmapped`, which is the rule PRD Appendix A.1's data rules state in so many
words and which "get or create" delivers by construction rather than by a branch
somebody has to remember.

**Refusals are `ValueError`s and they are raised before the row.** This is a
domain service, so `ImproperlyConfigured` is wrong: that exception belongs to the
two startup stages, and raising it here would make a bad inventory record look
like a misconfigured process. The shape of each check is `core/ledger.py`'s
`_require_*(value, *, field)`, which is the house form for "this input cannot
describe what it claims to".

**The provenance is written even though the mapping is not.** `CPM-FR-2` wants
the resolver that established an identity and the key it matched on recorded so
the resolution "can be re-derived and disputed rather than merely trusted", and a
shell is a resolution -- a very small one. It matters more here than for a real
resolution, not less: the source's own key survives on the row as
`canonical_name` only until `CPM-IDENTITY-S02` corrects the name, and a shell
with no `associator_key` is a package the next sweep cannot match back to the
record that created it. Neither field asserts a mapping, and `confidence` stays
`unmapped`.

**The transaction boundary is the caller's** (`CPM-AD-23`). The shell and the
evidence row that occasioned it commit together, one package at a time, and the
caller is what knows where that boundary is -- so nothing here opens a
transaction the caller could be *outside* of. A service that wrapped its own
would put the shell outside the block the snapshot is in, and a snapshot write
that then failed would leave a package row nothing ever observed.

The one qualification, stated rather than left to be discovered: `get_or_create`
opens a savepoint around its `create`, so that losing the unique-constraint race
rolls back to a known point and re-reads instead of poisoning the caller's
transaction. That is a savepoint *within* the caller's block rather than a
boundary of its own -- the shell still commits or rolls back with the snapshot
beside it.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from conda_package_supply_chain_monitor.core.clock import is_aware
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import Package

if TYPE_CHECKING:
    from datetime import datetime

    from conda_package_supply_chain_monitor.core.clock import Clock

__all__ = [
    "CANONICAL_NAME_FIELD",
    "CANONICAL_NAME_LENGTH",
    "ResolutionError",
    "resolve_package_shell",
]

#: The column a shell's name is written to, named once because the length bound
#: below is read off it. A literal 128 here would be a second declaration of a
#: width `identity/models.py` already owns, and the two would drift the day the
#: column is widened.
CANONICAL_NAME_FIELD: Final[str] = "canonical_name"

#: How long a shell's name may be, read off the column rather than restated.
#:
#: Public because it is also the bound a *caller* has to apply. The inventory
#: record contract refuses an over-long source package key so that the whole
#: document is refused rather than one record failing mid-sweep (`CPM-FR-42`: "no
#: run partially ingests a malformed source"), and it cannot do that against a
#: number only this module knows. `_require_key` below applies the same bound for
#: a caller that did not.
#:
#: `getattr` with a default rather than an attribute access: `get_field` is
#: annotated as returning any of three field kinds, two of which have no
#: `max_length`, and a `cast` would be asserting something about the schema that
#: this line is trying to read. `tests/unit/django_apps/test_identity_services.py`
#: reconciles the value against the field, so a column that stopped declaring one
#: fails there rather than silently admitting every key.
CANONICAL_NAME_LENGTH: Final[int] = int(
    getattr(
        Package._meta.get_field(CANONICAL_NAME_FIELD),  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        "max_length",
        0,
    )
    or 0,
)


class ResolutionError(ValueError):
    """A package identity could not be established from what was supplied.

    One type rather than a hierarchy, on the same terms as `core/models.py`'s
    `AppendOnlyError`: every occurrence is a defect in the record that was handed
    over or in the caller that handed it, and no caller branches on which check
    failed. The detail is in the message.

    A `ValueError` subclass, matching `core/collection.py`'s
    `CollectorConfigurationError`, `core/registry.py`'s `CollectorRegistryError`
    and `core/freshness.py`'s `FreshnessError`: every "this declaration or input
    is unusable" in this product is a `ValueError`, so a caller catching one
    catches them all. Deliberately **not** `ImproperlyConfigured`, which is
    reserved for the two startup stages -- a malformed inventory record is not a
    misconfigured process, and a sweep that reported it as one would send an
    operator to the settings.
    """


def resolve_package_shell(*, source_package_key: str, identity_source: str, clock: Clock) -> Package:
    """Return the package row for one source key, creating the shell if there is none.

    The whole of this story's resolution: `CPM-AD-25`'s "creates the shell at
    `unmapped` confidence", and nothing more. See the module docstring for why it
    asserts no mapping, why the source key becomes the canonical name, why the
    provenance is recorded anyway, and why the transaction belongs to the caller.

    Args:
        source_package_key: The key the inventory source used for this package.
            It becomes both the shell's canonical name and its `associator_key`
            -- the first is the correctable one and the second is the record.
        identity_source: What established this identity, recorded on the row
            (`CPM-FR-2`). A collector's declared name rather than a relation:
            resolvers are code, declared and never discovered (inherited `AD-8`),
            so there is no table for it to point at.
        clock: The clock `resolved_at` is read from (`CPM-AD-26`). Injected
            rather than reached for, because `CPM-FR-2` records the resolution's
            timestamp and a service that read a wall clock would make every
            assertion about that instant a statement about how long the test
            took.

    Returns:
        The existing package row, untouched, or the shell this call created --
        `unmapped` confidence, no mapping of any kind, the provenance above, and
        `resolved_at` from the clock.

    Raises:
        ResolutionError: When the key names nothing, when it is longer than the
            column that has to hold it, when nothing is named as the identity
            source, or when the clock answered a naive instant. Each is refused
            before the row is written, so a record that cannot produce a usable
            identity leaves no half-made one behind.

    """
    name = _require_key(source_package_key)
    source = _require_source(identity_source)
    resolved_at = _require_aware(clock.now(), field="resolved_at")
    package, _created = Package.objects.get_or_create(
        canonical_name=name,
        defaults={
            "resolved_at": resolved_at,
            # Written out rather than left to the column's default. The default
            # is `unmapped` and this passes `unmapped`, which is not redundancy:
            # the value this service asserts is the thing `CPM-AD-25` names, and
            # a reader must not have to open the model to find out that ingestion
            # claims nothing about the package it just created.
            "confidence": IdentityConfidence.UNMAPPED,
            "identity_source": source,
            "associator_key": name,
        },
    )
    return package


def _require_source(identity_source: str) -> str:
    """Refuse a resolution that does not say what established it.

    `CPM-FR-2` needs a resolution traceable to the resolver that made it, on the
    same terms `core/ledger.py` needs a run traceable to the code that performed
    it. The refusal is here rather than at the column because a blank `CharField`
    is perfectly valid SQL: the row would be written, would be counted, and would
    name nothing.

    Args:
        identity_source: What the caller says established the identity.

    Returns:
        The name with surrounding whitespace removed.

    Raises:
        ResolutionError: When it is empty or only whitespace.

    """
    source = identity_source.strip()
    if not source:
        message = (
            f"a package shell needs an identity_source; {identity_source!r} names nothing. A resolution is "
            f"traceable to the resolver that made it (CPM-FR-2), and a blank name is a row nothing can be "
            f"re-derived from."
        )
        raise ResolutionError(message)
    return source


def _require_key(source_package_key: str) -> str:
    """Refuse a source key that cannot name a package.

    Args:
        source_package_key: The key the caller supplied.

    Returns:
        The key with surrounding whitespace removed, which is what the row
        carries: a key that differs from another only by a trailing space is the
        same key to the source and two rows to `unique=True`.

    Raises:
        ResolutionError: When the key is blank or only whitespace, or when it is
            longer than `canonical_name` can hold. The length check is here
            rather than left to the database because the two disagree: SQLite
            ignores `max_length` entirely and PostgreSQL raises, so an
            over-long key is a working row on a developer's machine and a failed
            run in the gate.

    """
    name = source_package_key.strip()
    if not name:
        message = (
            f"a package shell needs a source package key; {source_package_key!r} names nothing. A package "
            f"with no name cannot be corrected, cannot be exported and cannot be found again (CPM-FR-2)."
        )
        raise ResolutionError(message)
    if len(name) > CANONICAL_NAME_LENGTH:
        message = (
            f"the source package key {name!r} is {len(name)} characters and {CANONICAL_NAME_FIELD} holds "
            f"{CANONICAL_NAME_LENGTH}. SQLite would store it truncated and PostgreSQL would refuse it, so "
            f"the row would exist on a developer's machine and fail in the gate -- the parity gap is "
            f"refused here instead."
        )
        raise ResolutionError(message)
    return name


def _require_aware(instant: datetime, *, field: str) -> datetime:
    """Refuse a naive instant, on the same terms `core/ledger.py` does.

    `identity/models.py` says the model performs no awareness check of its own
    and that the check is this service's. This is it: `USE_TZ` is on, so Django
    warns and stores a naive value as if it were UTC, and a `resolved_at`
    silently shifted by the writer's offset is a provenance record that says the
    identity was established at a time it was not.

    Args:
        instant: The value the clock answered.
        field: Which field it is for, for the message.

    Returns:
        The instant, unchanged.

    Raises:
        ResolutionError: When the instant carries no usable offset.

    """
    if not is_aware(instant):
        message = (
            f"a package shell was resolved with a naive {field} ({instant!r}). The instant comes from a "
            f"Clock, which always answers in UTC (CPM-AD-26); a naive value has no offset to interpret and "
            f"would record a resolution at a time it did not happen rather than failing."
        )
        raise ResolutionError(message)
    return instant
