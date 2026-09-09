"""The one execution backend this component verifies through, and the fact that none ships with it.

`CPM-FR-14` makes Python 3.14 verification "a separate, optionally triggered
capability", and what verification *is* is running somebody else's build and
somebody else's import. Nothing in the PRD and nothing in the architecture spine
decides how that execution is isolated -- not a sandbox, not a container, not a
resource bound, not a network posture. This module is the seam that lets the
mechanism ship without those answers: an execution backend is a **declared
adapter** at the collector base's transport seam, on the terms `CPM-AD-29`
established for the inventory and `collectors/advisories.py` took for the
advisory source, and this component declares none.

**Choosing an isolation posture for executing third-party code, unasked, in a
supply-chain security tool is not a decision a story makes on its own.** That
sentence is `CPM-PY314-S02`'s Block If and it is the whole reason this file
exists rather than a `subprocess` call. A default backend would mean this
component ran arbitrary build scripts from the internet on whatever host the
worker happens to be, chosen by nobody, in the one product whose subject is what
arbitrary code from the internet does to an organisation. So the mechanism ships,
the evidence table ships, the queue routing ships, and the thing that executes is
declared by an operator who has decided what it may touch.

**An adapter *is* a `Transport`** (`CPM-AD-27`, `CPM-AD-29`). It is handed a
locator naming the package and answers with a recorded `Payload`, so
`collectors/py314_verification.py` carries no branch on which backend is active,
the seam needs no second protocol, and `CPM-PY314-S03`'s policy never learns which
runner produced a row -- it reads the columns like any other evidence. It is also
what makes the whole of `core/collection.py` apply unchanged: the run ledger, the
`error` row for a backend that raised, the `not_found` row for an artifact that is
not there, the append-only write inside one transaction.

**One slot, declared and never discovered** (inherited `AD-8`, `CPM-AD-29`).
"Which backend does this component execute through" is answered by one call in an
`AppConfig.ready()`, where a reader can see it, and by no entry point, module walk
or import order. A second declaration of a *different* adapter is refused rather
than allowed to overwrite the first, for the reason `collectors/advisories.py`
refuses one and with more at stake: the second one silently replacing the first
would change **what code runs on which machine**, and every row written after it
would name a platform it was never asked to build on.

**Nothing is declared here and nothing is shipped.** `collectors/apps.py` declares
no execution backend, `verification_backend()` refuses until an operator declares
one, and `Py314VerificationCollector` is not swept across the inventory by
anything -- so an undeclared component verifies nothing, claims nothing and writes
nothing, rather than failing a package a day. `docs/deployment.md` tells an
operator what the refusal looks like and what declaring one commits them to.

## What an adapter must do, beyond satisfying `Transport`

`Transport` is `runtime_checkable`, so `isinstance` here sees one method *name*.
Everything else an adapter owes is a contract this module states and cannot check,
and an adapter that meets the protocol and breaks any of the following is one
whose results this component silently cannot record.

**The locator it is handed names the package and nothing else.** It is
`py314-verify://declared-backend/<the package's primary purl>`, or
`py314-verify://declared-backend/unnameable-identity/<package key>` when this
product's identity for the package names no usable package URL. The scheme is
opaque on purpose -- the adapter already knows which runner, image or cluster it
drives -- so what an adapter parses out of it is the purl, and the
`unnameable-identity` form is a question it may answer however it likes, because
the collector never offers such a package in the first place.

**It answers with a JSON document in the collector's own schema.** A top-level
object carrying `verified` (a boolean, required), `platform`, `architecture` and
`log_reference` (strings, required and non-blank), and `detail` (a string,
optional) -- and **no other field**, because an undefined one is refused rather
than dropped: a backend that grows a `partial` flag must fail loudly rather than
have this product read a half-run build as a finished one.
`collectors/py314_verification.py`'s `result_in` is the whole of the rule and its
refusals name what was wrong.

**`verified: false` is a result and not a failure.** It means the build or the
import did not come out, and it is recorded as `verification_failed` with the log
reference beside it. A backend that raised instead would lose exactly the row an
engineer wants to open.

**It always says where it ran.** The platform, the architecture and the log
reference are required of every document, including a `verified: false` one:
`CPM-PY314-S02`'s AC 1 is not conditional on the answer, and
`python_verification_results` refuses a determinate row that names fewer than all
three. An adapter that cannot say where it ran has not verified anything.

**It sets `found` itself.** `False` means the *locator* does not exist -- the
backend cannot obtain the artifact at all -- which the collector records as
`not_found`. "I ran it and it did not build" is **not** that: it is a document
answering `verified: false`, which is a determinate row. An adapter that conflates
them turns a failing build into an absence nobody investigates.

**It raises `TransportError` and nothing else.** `core/collection.py` catches that
class alone; anything else escapes `collect()` **before any evidence row is
written**, which defeats `CPM-NFR-3`'s "never no row" through the one seam this
story makes pluggable. An adapter driving a container runtime, a CI API or a build
cluster must convert every exception those raise, including the ones raised while
*starting* the work rather than while waiting for it.

**It never answers `not_modified`.** The collector declares `NO_CACHE`, so it
sends no validator and holds no cached body -- and a replayed verification would
be this product recording a build that did not run, which is the one thing an
evidence table about executions must never do.

**It finishes, or fails, inside the inherited soft time limit.** `CPM-AD-9` fixes
that limit in settings and forbids raising it, and the whole point of the `verify`
queue (`CPM-AD-20`, `R-11`) is that a long compute job does not share a worker with
the daily sweeps -- which bounds *what it starves*, not *how long it may take*. A
`fetch` that blocks for the length of a real build will meet the soft limit and the
task will be killed with no row written. An adapter therefore either completes
quickly or drives the build somewhere else and answers about a run that has already
finished. This is stated here, and in `docs/deployment.md`, rather than left for a
first operator to discover; `CPM-PY314-S02` records it as deferred work, because
resolving it means changing a limit `CPM-AD-9` owns.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from threading import Lock
from typing import Final

from conda_sentinel.core.transport import Transport

__all__ = [
    "VerificationBackendError",
    "declare_verification_backend",
    "declared_verification_backend",
    "verification_backend",
    "withdraw_verification_backend",
]

#: The declared execution backend adapter, by the one slot there is.
#:
#: A module-level mapping rather than a rebound global, for the reason
#: `collectors/advisories.py`'s `_DECLARED` is one: ruff `PLW0603` forbids the
#: `global` statement, and a `from ... import` of a rebound name would bind a copy
#: that never observes a later write.
_DECLARED: Final[dict[str, Transport]] = {}

#: The key `_DECLARED` holds the adapter under.
#:
#: One slot, because `CPM-AD-29` gives a substitution seam exactly one adapter: two
#: would make "which machine does this component build on" a question answered by
#: import order. The key itself is arbitrary and is deliberately *not* the
#: collector's declared name imported from `collectors/py314_verification.py` --
#: that module reads this one, and importing back would be a cycle for a string
#: nothing outside this file reads.
_ADAPTER_SLOT: Final[str] = "py314-execution-backend"

#: What makes a declaration and a withdrawal atomic against each other.
#:
#: Both read the slot and then write it, and `AppConfig.ready()` is not the only
#: caller: a Celery worker with a thread pool, or any process that declares a
#: backend outside boot, can reach these concurrently. Unguarded, two declarations
#: that both read an empty slot would *both* succeed and the second would silently
#: replace the first -- which is exactly the outcome the duplicate refusal exists
#: to prevent -- and two withdrawals could have the second raise `KeyError` from
#: `del` rather than this module's own refusal. A lock is what makes the check and
#: the write one step; it is held for two dict operations and never across a call
#: into an adapter.
_SLOT_LOCK: Final[Lock] = Lock()


class VerificationBackendError(ValueError):
    """No usable execution backend adapter is declared, or a second one is.

    A `ValueError` subclass on the same terms as `collectors/advisories.py`'s
    `AdvisorySourceError`, which it is deliberately shaped after: adapters are
    declared, never discovered (inherited `AD-8`, `CPM-AD-29`), and a duplicate is
    refused rather than overwritten.

    **The absent case is a misconfiguration and not a verification outcome**, which
    is why it is this class rather than an evidence row. A component with no
    execution backend has not built anything and cannot say anything about any
    package; a row recording that would be an observation nobody made. So the run
    is refused before the ledger recorder opens, and `docs/deployment.md` tells an
    operator what the refusal looks like and what to do about it.
    """


def declare_verification_backend(adapter: Transport) -> Transport:
    """Adopt one execution backend adapter for this process.

    Args:
        adapter: The `Transport` the verification collector runs builds through.

    Returns:
        The adapter, unchanged, so a caller can bind it in one statement.

    Raises:
        VerificationBackendError: When the object is not a `Transport`, or when one
            is already declared. `Transport` is `runtime_checkable`, so this check
            sees method *names* only -- the same bound `core/transport.py` records,
            and the reason this module's docstring writes out what an adapter owes
            beyond the protocol.

            The check and the write are one step under `_SLOT_LOCK`, so two
            concurrent declarations cannot both find an empty slot; the refusal is
            raised outside the lock, because a message is not shared state.

    """
    if not isinstance(adapter, Transport):
        message = (
            f"{adapter!r} is not a Transport and cannot be this component's Python 3.14 execution backend. A "
            f"backend is a transport substitution at the collector base's seam (CPM-AD-27, CPM-AD-29): it "
            f"answers fetch() with a recorded Payload, in the document schema this module's docstring states, "
            f"and raises TransportError for every failure."
        )
        raise VerificationBackendError(message)
    with _SLOT_LOCK:
        existing = _DECLARED.get(_ADAPTER_SLOT)
        if existing is None:
            _DECLARED[_ADAPTER_SLOT] = adapter
    if existing is not None:
        message = (
            f"{type(adapter).__name__} cannot be declared: {type(existing).__name__} is already this "
            f"component's Python 3.14 execution backend. A substitution seam reads exactly one adapter "
            f"(CPM-AD-29); a second one silently replacing the first would make which machine runs somebody "
            f"else's build a question answered by import order, in results nothing may correct."
        )
        raise VerificationBackendError(message)
    return adapter


def withdraw_verification_backend() -> None:
    """Withdraw the declared execution backend adapter.

    Symmetric with `declare_verification_backend` rather than a test hook bolted
    on, for the reason `collectors/advisories.py`'s `withdraw_advisory_source` is:
    the declaration is process-global, so a case that could only add to it could
    never measure the refusal when nothing is declared, and one that left an
    adapter behind would change what every later case reads.

    **Withdrawing returns the component to the state it ships in**, which is one
    that executes nothing: the next trigger is refused by name before any row is
    written.

    Raises:
        VerificationBackendError: When nothing is declared. Refused rather than
            ignored, because a silent no-op turns a mistaken withdrawal into a
            declaration that stays live and a caller that believes it does not. One
            `pop` under `_SLOT_LOCK` rather than a membership test and a `del`, so
            two concurrent withdrawals raise this rather than one of them raising a
            bare `KeyError`.

    """
    with _SLOT_LOCK:
        withdrawn = _DECLARED.pop(_ADAPTER_SLOT, None)
    if withdrawn is None:
        message = (
            "no Python 3.14 execution backend is declared, so there is nothing to withdraw. "
            "Declare one with declare_verification_backend (CPM-AD-29)."
        )
        raise VerificationBackendError(message)


def declared_verification_backend() -> Transport | None:
    """Return the declared execution backend adapter, or `None` when there is none.

    The read `verification_backend` below refuses on, without the refusal. It is
    shaped after `collectors/advisories.py`'s `declared_advisory_source` and exists
    for the caller shape that must **ask** rather than demand: a boot hook checking
    whether the declaration it is about to make has already been made
    (`AppConfig.ready` is Django's to call, and a second `django.setup()` in one
    process calls it again).

    Returns:
        The adapter this component executes through, or `None` when nothing is
        declared. `None` is an answer here and never a default: a caller that wants
        the run refused calls `verification_backend`.

    """
    return _DECLARED.get(_ADAPTER_SLOT)


def verification_backend() -> Transport:
    """Return the declared execution backend adapter.

    Returns:
        The adapter this component runs builds through.

    Raises:
        VerificationBackendError: When none is declared -- which is what ships. The
            run is refused here, before the recorder opens and therefore before any
            row exists, which is `CPM-PY314-S02`'s matrix row saying an
            unconfigured component leaves no row claiming a result.

    """
    adapter = _DECLARED.get(_ADAPTER_SLOT)
    if adapter is None:
        message = (
            "no Python 3.14 execution backend is declared, so there is nothing to build this package with. "
            "Adapters are declared and never discovered (AD-8, CPM-AD-29), and this component ships with "
            "none: verification means running somebody else's build and import, and nothing in this product's "
            "requirements or architecture decides how that is isolated -- so a backend nobody chose would run "
            "arbitrary code on whatever host the worker happens to be. Declare one with "
            "declare_verification_backend(...) in an AppConfig.ready() (docs/deployment.md)."
        )
        raise VerificationBackendError(message)
    return adapter
