"""The collectors this process knows about, declared one by one and never discovered.

`CPM-AD-28` puts a refusal at boot: a *registered* collector that declares no
freshness target stops the process. That sentence needs something to sweep, and
this is it -- the list of collector classes a component has adopted, which
`config/startup/stage_two.py` walks before a worker picks up any work.

**Declared, never discovered** (inherited `AD-8`). There is no entry-point scan
and no module walk: adoption in this product is already two explicit lines, and
a registry populated by import side effects would make "which collectors does
this component run" a question answered by whatever happened to be imported. A
collector arrives here because somebody wrote `register(TheCollector)` in an
`AppConfig.ready()`, where a reader can see it.

**It is not in `core/collection.py`, and that is the whole reason this module
exists.** `collection.py` is imported by anything that defines a collector --
every one of the eight, plus the fixtures that measure the base -- so a registry
living there would mean that importing the base populates a global. Keeping it
separate lets startup sweep a registry without the base importing one, and lets
a test build a collector class without that class becoming something boot will
refuse over.

**A duplicate name is refused rather than overwritten.** The name is what ledger
rows carry (`CPM-FR-39`) and what rate-limit cache keys are built from
(`core/rate_limit.py`), so two classes registered under one name share an
allowance, share a run history and are indistinguishable in every report --
while the second one silently replaces the first in whatever this module
returns. `core/collection.py` already refuses a blank name for the same class of
reason; this is the other half of making a name identify something.

**`unregister` exists because registration is process-global.** A registry that
can only grow cannot be measured: the refusal `CPM-AD-28` asks for is
"a registered collector declaring no target", so a case has to be able to put
one there and take it away again, and a case that left one behind would refuse
every case that ran after it. It is symmetric with `register` rather than a test
hook bolted on, and nothing on a product path calls it.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix. `AD-8` above is the platform's declared-not-discovered
rule and `CPM-AD-28` is this product's freshness refusal -- two registers, not a
typo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from conda_package_supply_chain_monitor.core.collection import Collector

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CollectorRegistryError",
    "register",
    "registered_collectors",
    "registrations",
    "unregister",
]

#: The registered collector classes, by the name each declares.
#:
#: A module-level mapping rather than a rebound global, for the reason
#: `config/startup/stage_two.py`'s boot sentinel is one: ruff `PLW0603` forbids
#: the `global` statement, and a `from ... import` of a rebound name would bind a
#: copy that never observes a later write. Read through `registrations()` rather
#: than directly, so no caller performs the cross-module private read `SLF001`
#: forbids.
_REGISTERED: Final[dict[str, type[Collector]]] = {}


class CollectorRegistryError(ValueError):
    """A collector could not be added to, or removed from, the registry.

    A `ValueError` subclass, matching `core/collection.py`'s
    `CollectorConfigurationError` and `core/freshness.py`'s `FreshnessError`:
    every "this declaration is unusable" in this product is a `ValueError`, so a
    caller catching one catches them all.

    Raised at registration, which is the moment the answer exists and is
    reachable at import time in the `AppConfig.ready()` that performs it -- not
    at the boot sweep, and certainly not in a worker that has already opened a
    run ledger row.
    """


def register(collector: type[Collector]) -> type[Collector]:
    """Adopt one collector class, under the name it declares.

    Args:
        collector: The collector class to adopt. A class, not an instance: the
            sweep at boot asks what a collector *declares*, and constructing one
            to find out would build a transport and a connection pool during
            `django.setup()`.

    Returns:
        The class, unchanged, so the call can be written as a decorator on the
        class it adopts where that reads better than a separate line.

    Raises:
        CollectorRegistryError: When the argument is not a `Collector` subclass;
            when it declares no name -- `core/collection.py` refuses a blank one
            at construction and a registry keyed on it cannot accept one either;
            or when another class is already registered under that name.

    """
    if not (isinstance(collector, type) and issubclass(collector, Collector)):
        message = (
            f"{collector!r} is not a Collector subclass and cannot be registered. Every external-call rule "
            f"this product has lives in that base (CPM-AD-20, CPM-AD-27), so a registered class that does "
            f"not inherit it carries none of them."
        )
        raise CollectorRegistryError(message)

    name = collector.name
    if not isinstance(name, str) or not name.strip():
        message = (
            f"{collector.__name__} declares name={name!r} and cannot be registered under it. The name is what "
            f"a run is traced to (CPM-FR-39) and what its rate-limit allowance is keyed on; a blank one names "
            f"nothing."
        )
        raise CollectorRegistryError(message)

    existing = _REGISTERED.get(name)
    if existing is not None:
        message = (
            f"{collector.__name__} declares name={name!r}, which {existing.__name__} is already registered "
            f"under. Two collectors sharing a name share one rate-limit allowance and one run history, and "
            f"neither can be told from the other in any report."
        )
        raise CollectorRegistryError(message)

    _REGISTERED[name] = collector
    return collector


def unregister(name: str) -> None:
    """Withdraw the collector registered under one name.

    Args:
        name: The declared name the class was registered under.

    Raises:
        CollectorRegistryError: When nothing is registered under that name.
            Refused rather than ignored, because a silent no-op turns a
            misspelled withdrawal into a registration that stays live and a
            caller that believes it does not.

    """
    if name not in _REGISTERED:
        message = (
            f"no collector is registered under name={name!r}, so there is nothing to withdraw. "
            f"The registered names are {sorted(_REGISTERED)}."
        )
        raise CollectorRegistryError(message)
    del _REGISTERED[name]


def registered_collectors() -> tuple[type[Collector], ...]:
    """Return every registered collector class, in a fixed order.

    Returns:
        The classes, ordered by declared name. Ordered rather than in insertion
        order so that a component whose `AppConfig.ready()` adopts collectors in
        a different sequence meets the same refusal first -- which is the
        property `AD-26` asks of the stage-2 roster, applied to what that roster
        sweeps.

        Empty until `CPM-EP-CURRENCY` declares the first collector, and an empty
        sweep is not a failure: a component with no collectors is a component
        that has adopted none, not one that has forgotten a target.

    """
    return tuple(_REGISTERED[name] for name in sorted(_REGISTERED))


def registrations() -> Mapping[str, type[Collector]]:
    """Return what is registered, by name.

    Returns:
        A copy, so a caller cannot widen or empty the registry by mutating what
        it was handed -- the same reason `core/collection.py` returns declared
        headers as a read-only mapping.

    """
    return dict(_REGISTERED)
