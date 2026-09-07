"""The one advisory source this component reads, and the fact that none ships with it.

`CPM-FR-11` matches a package and a version against advisory sources, and PRD
Open Question 1 -- "which advisory and KEV data sources are available and
licensed for use" -- is unresolved and explicitly blocks `CPM-EP-SECURITY`. This
module is the seam that lets the mechanism ship without the answer: an advisory
source is a **declared adapter** at the collector base's transport seam, on the
terms `CPM-AD-29` established for the inventory, and this component declares
none.

**An adapter *is* a `Transport`** (`CPM-AD-27`, `CPM-AD-29`). It is handed a
locator and answers with a recorded `Payload`, so
`collectors/vulnerability.py` carries no branch on which source is active, the
seam needs no second protocol, and the policy pass `CPM-SECURITY-S04` builds
later never learns which source produced a row -- it reads the `source` column
like any other evidence. That is AC 3 of `CPM-SECURITY-S01`: changing the source
touches neither the collector nor any policy.

**One slot, declared and never discovered** (inherited `AD-8`, `CPM-AD-29`).
"Which source is this component's advisory source" is answered by one call in an
`AppConfig.ready()`, where a reader can see it, and by no entry point, module
walk or import order. A second declaration of a *different* adapter is refused
rather than allowed to overwrite the first, for the reason
`collectors/tasks.py`'s `declare_inventory_adapter` refuses one: the second one
silently replacing the first is how a deployed component comes to read a
development subset, and every finding it then records -- or fails to record -- is
permanent in a log nothing may correct.

**Nothing is declared here and nothing is shipped**, which is the whole posture
of this epic. `CPM-IDENTITY-S07` set it for the watchlist -- the file ships
unpopulated and ingestion fails loudly until it is reviewed in -- and a
vulnerability source chosen by default would be worse than a watchlist chosen by
default: it would produce security findings about an organisation's packages
from a source that organisation never agreed to act on. So
`collectors/apps.py` declares no advisory source, `advisory_source()` refuses
until an operator declares one, and `VulnerabilityCollector.selectable_packages`
answers with nothing so an undeclared component sweeps nothing rather than
failing every package every day.

**What this module does not own is the document.** An adapter yields a payload;
what a readable advisory document *is* -- its fields, its bounds and its
refusals -- belongs beside the collector that reads it, in
`collectors/vulnerability.py`, exactly as the inventory record contract lives
beside the collector that reads it. This module is the slot; what an adapter
*owes* is written out below, because "it satisfies `Transport`" is not the whole
of it.

## What an adapter must do, beyond satisfying `Transport`

`Transport` is `runtime_checkable`, so `isinstance` here sees one method *name*.
Everything else an adapter owes is a contract this module states and cannot
check, and an adapter that meets the protocol and breaks any of the following is
one whose findings this component silently cannot record.

**The locator it is handed names the package and nothing else.** It is
`advisory://declared-source/<the package's primary purl>`, or
`advisory://declared-source/unnameable-identity/<package key>` when this
product's identity for the package names no usable package URL. The scheme is
opaque on purpose -- the adapter already knows which API or file it reads
(`CPM-AD-29`) -- so what an adapter parses out of it is the purl, and the
`unnameable-identity` form is a question it may answer however it likes, because
the collector discards the answer.

**It answers with a JSON document in the collector's own schema.** A top-level
object carrying `identified` (a boolean, required), `findings` (a list, optional)
and `detail` (a string, optional), and **no other field** -- an undefined one is
refused rather than dropped, so a source that grows a truncation flag fails
loudly instead of being read as "nothing matched". Each finding carries
`advisory_id`, `affected_range` and `match_confidence`, all required and
non-blank, plus optional `severity` and `fixed_range`; `match_confidence` must be
one of `collectors/match_confidence.py`'s three values. Every value must fit its
column and carry no control character. `collectors/vulnerability.py`'s
`findings_in` is the whole of the rule and its refusals name what was wrong.

**It sets `found` itself.** `False` means the *locator* does not exist, which the
collector records as `not_found` with a caveat saying it is a withdrawn or
misconfigured source rather than a clean package. "I have no record of this
package" is **not** that: it is a document answering `identified: false`, which
becomes `unknown`. An adapter that conflates them writes the one row on this
table a reader could mistake for a clean answer.

**It raises `TransportError` and nothing else.** `core/collection.py` catches
that class alone; anything else escapes `collect()` **before any evidence row is
written**, which defeats `CPM-NFR-3`'s "never no row" through the one seam this
story makes pluggable. An adapter that wraps a client library must convert its
exceptions, including the ones raised while building a request rather than while
issuing it. `tests/integration/django_apps/test_vulnerability.py` measures what
happens when one does not, so the consequence is a fact rather than a warning.

**It never answers `not_modified`.** The collector declares `NO_CACHE`, so it
sends no validator and holds no cached body -- a `304` is therefore an answer to
a question nobody asked, and the base fails every such run with no body to read.
An adapter that revalidates against its own remembered state must return the body
it is revalidating.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from threading import Lock
from typing import Final

from conda_package_supply_chain_monitor.core.transport import Transport

__all__ = [
    "AdvisorySourceError",
    "advisory_source",
    "declare_advisory_source",
    "declared_advisory_source",
    "withdraw_advisory_source",
]

#: The declared advisory source adapter, by the one slot there is.
#:
#: A module-level mapping rather than a rebound global, for the reason
#: `collectors/tasks.py`'s `_DECLARED` is one: ruff `PLW0603` forbids the
#: `global` statement, and a `from ... import` of a rebound name would bind a
#: copy that never observes a later write.
_DECLARED: Final[dict[str, Transport]] = {}

#: The key `_DECLARED` holds the adapter under.
#:
#: One slot, because `CPM-AD-29` gives a source-substitution seam exactly one
#: adapter: two would make "which source is this component's advisory source" a
#: question answered by import order. The key itself is arbitrary and is
#: deliberately *not* the collector's declared name imported from
#: `collectors/vulnerability.py` -- that module reads this one, and importing
#: back would be a cycle for a string nothing outside this file reads.
_ADAPTER_SLOT: Final[str] = "advisory-source"

#: What makes a declaration and a withdrawal atomic against each other.
#:
#: Both read the slot and then write it, and `AppConfig.ready()` is not the only
#: caller: a Celery worker with a thread pool, or any process that declares a
#: source outside boot, can reach these concurrently. Unguarded, two declarations
#: that both read an empty slot would *both* succeed and the second would silently
#: replace the first -- which is exactly the outcome the duplicate refusal exists
#: to prevent -- and two withdrawals could have the second raise `KeyError` from
#: `del` rather than this module's own refusal. A lock is what makes the check and
#: the write one step; it is held for two dict operations and never across a call
#: into an adapter.
_SLOT_LOCK: Final[Lock] = Lock()


class AdvisorySourceError(ValueError):
    """No usable advisory source adapter is declared, or a second one is.

    A `ValueError` subclass on the same terms as `collectors/tasks.py`'s
    `InventoryAdapterError`, which it is deliberately shaped after: adapters are
    declared, never discovered (inherited `AD-8`, `CPM-AD-29`), and a duplicate
    is refused rather than overwritten.

    **The absent case is a misconfiguration and not a match failure**, which is
    why it is this class rather than an evidence row. A component with no
    advisory source has not looked and cannot say anything about any package; a
    row recording that would be an observation nobody made, and one recorded for
    every package in the inventory on every sweep. So the run is refused before
    the ledger recorder opens, and `docs/deployment.md` tells an operator what
    the refusal looks like and what to do about it.
    """


def declare_advisory_source(adapter: Transport) -> Transport:
    """Adopt one advisory source adapter for this process.

    Args:
        adapter: The `Transport` the vulnerability collector reads its advisory
            documents through.

    Returns:
        The adapter, unchanged, so a caller can bind it in one statement.

    Raises:
        AdvisorySourceError: When the object is not a `Transport`, or when one is
            already declared. `Transport` is `runtime_checkable`, so this check
            sees method *names* only -- the same bound `core/transport.py`
            records, and the reason a case pins what `fetch` returns as well as
            that it exists, and the reason this module's docstring writes out what
            an adapter owes beyond the protocol.

            The check and the write are one step under `_SLOT_LOCK`, so two
            concurrent declarations cannot both find an empty slot; the refusal is
            raised outside the lock, because a message is not shared state.

    """
    if not isinstance(adapter, Transport):
        message = (
            f"{adapter!r} is not a Transport and cannot be this component's advisory source. An advisory source "
            f"is a transport substitution at the collector base's seam (CPM-AD-27, CPM-AD-29): it answers "
            f"fetch() with a recorded Payload, in the document schema this module's docstring states, and "
            f"raises TransportError for every failure."
        )
        raise AdvisorySourceError(message)
    with _SLOT_LOCK:
        existing = _DECLARED.get(_ADAPTER_SLOT)
        if existing is None:
            _DECLARED[_ADAPTER_SLOT] = adapter
    if existing is not None:
        message = (
            f"{type(adapter).__name__} cannot be declared: {type(existing).__name__} is already this "
            f"component's advisory source. A source-substitution seam reads exactly one adapter (CPM-AD-29); a "
            f"second one silently replacing the first would make which advisory database this component "
            f"believes a question answered by import order, in findings nothing may correct."
        )
        raise AdvisorySourceError(message)
    return adapter


def withdraw_advisory_source() -> None:
    """Withdraw the declared advisory source adapter.

    Symmetric with `declare_advisory_source` rather than a test hook bolted on,
    for the reason `collectors/tasks.py`'s `withdraw_inventory_adapter` is: the
    declaration is process-global, so a case that could only add to it could
    never measure the refusal when nothing is declared, and one that left an
    adapter behind would change what every later case reads.

    **Withdrawing returns the component to the state it ships in**, which is one
    that observes nothing: the next dispatch selects no package and emits
    `NO_ADVISORY_SOURCE_EVENT`, which is what an operator alerts on.

    Raises:
        AdvisorySourceError: When nothing is declared. Refused rather than
            ignored, because a silent no-op turns a mistaken withdrawal into a
            declaration that stays live and a caller that believes it does not.
            One `pop` under `_SLOT_LOCK` rather than a membership test and a
            `del`, so two concurrent withdrawals raise this rather than one of
            them raising a bare `KeyError`.

    """
    with _SLOT_LOCK:
        withdrawn = _DECLARED.pop(_ADAPTER_SLOT, None)
    if withdrawn is None:
        message = (
            "no advisory source adapter is declared, so there is nothing to withdraw. "
            "Declare one with declare_advisory_source (CPM-AD-29)."
        )
        raise AdvisorySourceError(message)


def declared_advisory_source() -> Transport | None:
    """Return the declared advisory source adapter, or `None` when there is none.

    The read `advisory_source` below refuses on, without the refusal. It is
    shaped after `collectors/tasks.py`'s `declared_inventory_adapter` and exists
    for two caller shapes that must **ask** rather than demand: a boot hook
    checking whether the declaration it is about to make has already been made
    (`AppConfig.ready` is Django's to call, and a second `django.setup()` in one
    process calls it again), and `VulnerabilityCollector.selectable_packages`,
    which offers no package at all while nothing is declared.

    Returns:
        The adapter this component reads advisories through, or `None` when
        nothing is declared. `None` is an answer here and never a default: a
        caller that wants the run refused calls `advisory_source`.

    """
    return _DECLARED.get(_ADAPTER_SLOT)


def advisory_source() -> Transport:
    """Return the declared advisory source adapter.

    Returns:
        The adapter this component reads advisories through.

    Raises:
        AdvisorySourceError: When none is declared. The run is refused here,
            before the recorder opens and therefore before any row exists --
            which is the matrix row saying that a component with no advisory
            source leaves no trace of a run that could not have observed
            anything, rather than a finding claiming it looked.

    """
    adapter = _DECLARED.get(_ADAPTER_SLOT)
    if adapter is None:
        message = (
            "no advisory source adapter is declared, so there is nothing to match this package against. "
            "Adapters are declared and never discovered (AD-8, CPM-AD-29), and this component ships with "
            "none: which advisory sources are licensed for use is PRD Open Question 1, and a source nobody "
            "chose would record security findings an organisation never agreed to act on. Declare one with "
            "declare_advisory_source(...) in an AppConfig.ready() (docs/deployment.md)."
        )
        raise AdvisorySourceError(message)
    return adapter
