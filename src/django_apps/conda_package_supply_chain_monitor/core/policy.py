"""What a policy pass is, and the ordered registry that makes the ownership rule auditable.

`CPM-AD-21` puts the passes under one orchestrating run. `CPM-AD-11` says one
writer owns the rollup. Neither survives a design in which the run *calls* its
passes: a run that called them directly would make "no pass writes the rollup" a
code review somebody has to remember to do, which is `ASR-3` -- the risk that a
rule holds only while everyone remembers it. So passes **register**, and the set
becomes enumerable; `tests/unit/django_apps/test_pass_ownership_audit.py` then
checks the rule against passes nobody has written yet.

**Declared, never discovered** (inherited `AD-8`), on exactly the terms
`core/registry.py` states for collectors: no entry-point scan and no module walk.
A pass arrives here because somebody wrote `register_pass(TheCurrencyPass)` where
a reader can see it.

**Ordered by declaration, not by name.** This is the one place this registry
differs from the collector registry, and the difference is the point:
`core/registry.py` sorts by name so that a component adopting collectors in a
different sequence meets the same refusal first, because collectors are
independent of each other. Passes are not. `CPM-AD-21` says a later pass may read
an earlier pass's derived rows for the same run, so the order is a *declaration*
about which reads which -- and sorting it alphabetically would make that
depend on what somebody called their pass.

**Four refusals, and each closes a way the ownership rule could be lost.**

* *A duplicate name.* The name is what a derived table's rows are traced to and
  what the per-domain version map is keyed by, so two passes under one name are
  indistinguishable in every report -- and the second silently replaces the first
  in whatever this module returns.
* *A pass claiming the rollup as its derived table.* This is `CPM-AD-11`'s single
  writer, refused at the moment somebody tries rather than found later in a
  table with two authors. The audit checks it independently, because a refusal
  here only binds passes that go through this function.
* *Two passes claiming one column.* A column has one owner, or "who computed
  this verdict" has two answers and the rollup's `policy_versions` map cannot say
  which version produced it.
* *A contribution naming a column the rollup does not declare.* Validated
  against `core/rollup.py`'s real fields rather than against a list, so a
  misspelled `currency_stauts` is refused at registration instead of silently
  contributing nothing forever.

**And three more that each defeat one of those four by a side door.** *Two passes
declaring one derived table* makes `(package, policy_run)` ambiguous, so a later
pass reading an earlier one's rows cannot tell whose it is reading -- and the
duplicate-name check cannot see it, because the names differ. *One class
registered under two names* makes it run twice per package and claim two entries
in the version map for one domain, and again the name check cannot see it. *A
column declared twice by one pass* reads as two claims that happen to agree, and
the ownership map would silently record one. None of the three is exotic; each is
what a copy-pasted pass declaration looks like before somebody finishes editing
it.

**A pass writes only its own derived table.** That is a rule about behaviour
rather than about declaration, so this module cannot enforce it and does not
pretend to: what it does is make the *claim* explicit -- `derived_model` is
declared, keyed `(package, policy_run)` by the story that adds it -- so the
ownership audit can read the claim and the reviewer has one place to check the
behaviour against.

**`unregister_pass` exists because registration is process-global**, for the
reason `core/registry.py`'s does: the refusals above can only be measured by a
case that puts a pass in the registry and takes it away again, and a case that
left one behind would change what every later case sees. It is symmetric with
`register_pass` rather than a test hook bolted on, and nothing on a product path
calls it.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix. `AD-8` above is the platform's declared-not-discovered
rule and `CPM-AD-21` is this product's policy-run rule -- two registers, not a
typo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

from django.db import models

from conda_package_supply_chain_monitor.core import rollup

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from conda_package_supply_chain_monitor.core.models import PolicyRun
    from conda_package_supply_chain_monitor.identity.models import Package

__all__ = [
    "PolicyPass",
    "PolicyPassError",
    "column_owners",
    "pass_registrations",
    "register_pass",
    "registered_passes",
    "unregister_pass",
]

#: The registered pass classes, by the name each declares, in declaration order.
#:
#: A module-level mapping rather than a rebound global, for the reason
#: `core/registry.py`'s is: ruff `PLW0603` forbids the `global` statement, and a
#: `from ... import` of a rebound name would bind a copy that never observes a
#: later write. `dict` preserves insertion order, which is what makes "declared
#: order" a property of the structure rather than of a separate list that could
#: fall out of step with it.
_REGISTERED: Final[dict[str, type[PolicyPass]]] = {}

#: Rollup column to the name of the pass that owns it.
#:
#: Kept beside the registry rather than derived from it on demand, because the
#: refusal it powers has to name *which* pass already owns the column -- and
#: because withdrawing a pass must free its columns in the same operation that
#: removes it, or a re-registration of the same pass would be refused by its own
#: leftovers.
_COLUMN_OWNERS: Final[dict[str, str]] = {}


class PolicyPassError(ValueError):
    """A pass could not be added to, or removed from, the registry.

    A `ValueError` subclass, matching `core/registry.py`'s
    `CollectorRegistryError` and `core/confidence.py`'s `ConfidenceError`: every
    "this declaration is unusable" in this product is a `ValueError`, so a caller
    catching one catches them all.

    Raised at registration, which is the moment the answer exists and is
    reachable at import time in the `AppConfig.ready()` that performs it -- not
    in a worker that has already opened a policy run's ledger row.
    """


class PolicyPass:
    """One domain's contribution to a policy run: a derived table and some rollup columns.

    Subclassed by each of `CPM-EP-CURRENCY`, `CPM-EP-SECURITY` and the rest.
    Three declarations and one method, and the declarations are what the registry
    and the ownership audit read.

    **`derived_model` is the table this pass owns and the only one it writes.**
    `CPM-AD-21` keys it `(package, policy_run)`: one row per package per run, so
    a replay of a version at a cut-off can be compared against the original
    without either of them having overwritten the other. It is emphatically not
    the rollup -- `register_pass` refuses that, and
    `tests/unit/django_apps/test_pass_ownership_audit.py` refuses it again from
    outside the registry.

    **`contributes` is a claim, checked against the rollup's real fields.** A
    pass says which rollup columns it produces; the writer in `core/rollup.py` is
    what actually writes them, after `CPM-AD-4`'s gate. A pass never sees a
    confidence and never writes a rollup row.

    Attributes:
        name: What this pass is called. It keys the registry, keys the rollup's
            per-domain `policy_versions` map, and appears in every refusal
            message. Blank is refused: a name that names nothing cannot key
            anything.
        derived_model: The per-domain table this pass owns.
        contributes: The rollup columns this pass produces, if any. Empty is
            legitimate -- a pass whose whole output is its own derived table is a
            pass the rollup does not yet project.

    """

    name: ClassVar[str] = ""
    derived_model: ClassVar[type[models.Model] | None] = None
    contributes: ClassVar[tuple[str, ...]] = ()

    def evaluate(
        self,
        package: Package,
        *,
        policy_run: PolicyRun,
        evidence_cutoff: datetime,
    ) -> Mapping[str, str]:
        """Compute this pass's verdict for one package, writing its own derived rows.

        Called once per package, inside that package's transaction
        (`CPM-AD-23`), with the passes of one package run in declared order --
        which is what lets a later pass read an earlier one's derived rows for
        this run.

        Args:
            package: The package to evaluate.
            policy_run: The run this evaluation belongs to. Written onto every
                derived row so `(package, policy_run)` identifies it.
            evidence_cutoff: The instant to read evidence as of (`CPM-AD-21`). A
                pass reads no evidence written after it, and never reads the
                current time to decide.

        Returns:
            The rollup columns this pass produced for this package, by column
            name, each as the stored string of an outcome value. Only columns
            this pass declared in `contributes` may appear; anything else is
            refused by the orchestration rather than silently dropped. An empty
            mapping is legitimate.

        Raises:
            NotImplementedError: Always, here. A registered pass that has not
                overridden this has declared a domain and computes nothing, and
                failing loudly at the first package is better than a run that
                writes a clean rollup having evaluated nothing.

        """
        raise NotImplementedError


def register_pass(policy_pass: type[PolicyPass]) -> type[PolicyPass]:
    """Adopt one policy pass, under the name it declares.

    Args:
        policy_pass: The pass class to adopt. A class, not an instance, on the
            same terms as `core/registry.py`'s collectors: the ownership audit
            asks what a pass *declares*, and constructing one to find out would
            do work during `django.setup()`.

    Returns:
        The class, unchanged, so the call can be written as a decorator where
        that reads better than a separate line.

    Raises:
        PolicyPassError: When the argument is not a `PolicyPass` subclass; when
            it declares no name or a name already registered; when it declares no
            derived model, or declares the rollup as its derived model; or when a
            contributed column is not one the rollup offers or is already owned
            by another pass.

    """
    if not (isinstance(policy_pass, type) and issubclass(policy_pass, PolicyPass)):
        message = (
            f"{policy_pass!r} is not a PolicyPass subclass and cannot be registered. The contract the "
            f"orchestration and the ownership audit both read -- the declared name, the derived table it "
            f"owns, and the rollup columns it contributes -- lives in that base (CPM-AD-21)."
        )
        raise PolicyPassError(message)

    name = _declared_name(policy_pass)
    _require_unregistered_class(policy_pass, name=name)
    _require_derived_model(policy_pass, name=name)
    columns = _require_contributable(policy_pass, name=name)

    _REGISTERED[name] = policy_pass
    for column in columns:
        _COLUMN_OWNERS[column] = name
    return policy_pass


def unregister_pass(name: str) -> None:
    """Withdraw the pass registered under one name, and free the columns it owned.

    Args:
        name: The declared name the class was registered under.

    Raises:
        PolicyPassError: When nothing is registered under that name. Refused
            rather than ignored, for the reason `core/registry.py`'s `unregister`
            refuses: a silent no-op turns a misspelled withdrawal into a
            registration that stays live and a caller that believes it does not.

    """
    if name not in _REGISTERED:
        message = (
            f"no policy pass is registered under name={name!r}, so there is nothing to withdraw. "
            f"The registered names are {sorted(_REGISTERED)}."
        )
        raise PolicyPassError(message)
    del _REGISTERED[name]
    for column in [column for column, owner in _COLUMN_OWNERS.items() if owner == name]:
        del _COLUMN_OWNERS[column]


def registered_passes() -> tuple[type[PolicyPass], ...]:
    """Return every registered pass class, in the order they were declared.

    Returns:
        The classes, in registration order. See the module docstring for why this
        registry keeps declaration order where `core/registry.py` sorts by name:
        a later pass may read an earlier pass's derived rows, so the order is
        part of what was declared.

        Empty until the first policy epic declares a pass, and an empty run is
        not a failure: a run with no passes writes a rollup carrying the stamps
        and nothing else, which is exactly what this product currently knows.

    """
    return tuple(_REGISTERED.values())


def pass_registrations() -> Mapping[str, type[PolicyPass]]:
    """Return what is registered, by name.

    Returns:
        A copy, so a caller cannot widen or empty the registry by mutating what
        it was handed -- the same reason `core/registry.py`'s `registrations`
        returns one.

    """
    return dict(_REGISTERED)


def column_owners() -> Mapping[str, str]:
    """Return which pass owns each contributed rollup column.

    Returns:
        Column name to the name of the pass that declared it, as a copy. Read by
        the ownership audit, which asks the question from outside the registry so
        that a column with two owners fails even if it got there some other way.

    """
    return dict(_COLUMN_OWNERS)


def _declared_name(policy_pass: type[PolicyPass]) -> str:
    """Return the pass's declared name, refusing a blank or a duplicate one.

    Args:
        policy_pass: The class being registered.

    Returns:
        The name, unchanged.

    Raises:
        PolicyPassError: When the name is blank, is not a string, or is already
            registered to another class.

    """
    name = policy_pass.name
    if not isinstance(name, str) or not name.strip():
        message = (
            f"{policy_pass.__name__} declares name={name!r} and cannot be registered under it. The name keys "
            f"this registry and keys the rollup's per-domain policy version map (CPM-AD-11); a blank one "
            f"names nothing."
        )
        raise PolicyPassError(message)

    existing = _REGISTERED.get(name)
    if existing is not None:
        message = (
            f"{policy_pass.__name__} declares name={name!r}, which {existing.__name__} is already registered "
            f"under. Two passes sharing a name share one entry in the rollup's version map and cannot be told "
            f"apart in any report, and the second would silently replace the first."
        )
        raise PolicyPassError(message)
    return name


def _require_unregistered_class(policy_pass: type[PolicyPass], *, name: str) -> None:
    """Refuse a class that is already registered under a different name.

    `name` is a class attribute, so registering one class twice means somebody
    reassigned it between the two calls -- and the result is one object running
    twice per package, writing its derived table twice per run and claiming two
    entries in the rollup's per-domain version map for one domain. The duplicate
    *name* check cannot see it, because the two names differ.

    Args:
        policy_pass: The class being registered.
        name: The name it currently declares, for the message.

    Raises:
        PolicyPassError: When this exact class is already registered.

    """
    already = [registered for registered, declared in _REGISTERED.items() if declared is policy_pass]
    if already:
        message = (
            f"{policy_pass.__name__} is already registered under {already}, and would now also be registered "
            f"as {name!r}. A pass class runs once per package per run; registering one twice makes it write "
            f"its derived table twice and claim two entries in the rollup's version map for one domain."
        )
        raise PolicyPassError(message)


def _require_derived_model(policy_pass: type[PolicyPass], *, name: str) -> None:
    """Refuse a pass that owns no derived table, claims the rollup, or shares a table.

    Args:
        policy_pass: The class being registered.
        name: Its declared name, for the messages.

    Raises:
        PolicyPassError: When `derived_model` is absent, is not a Django model,
            is the rollup itself, or is a table another registered pass already
            owns.

    """
    derived = policy_pass.derived_model
    if not (isinstance(derived, type) and issubclass(derived, models.Model)):
        message = (
            f"policy pass {name!r} declares derived_model={derived!r}, which is not a Django model. A pass "
            f"owns exactly one per-domain table keyed (package, policy_run) and writes only that "
            f"(CPM-AD-21)."
        )
        raise PolicyPassError(message)
    if derived is rollup.ROLLUP_MODEL:
        message = (
            f"policy pass {name!r} declares the rollup {rollup.ROLLUP_MODEL._meta.label} as its derived table. "  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
            f"No pass writes current package health: one writer composes it from every pass's own derived "
            f"table (CPM-AD-11), and a pass writing it directly is the second author that rule exists to "
            f"prevent."
        )
        raise PolicyPassError(message)

    sharing = [
        registered for registered, declared in _REGISTERED.items() if declared.derived_model is derived
    ]
    if sharing:
        message = (
            f"policy pass {name!r} declares the derived table {derived._meta.label}, which {sharing} already "  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
            f"owns. `CPM-AD-21` gives each pass its own per-domain table keyed (package, policy_run): two "
            f"passes writing one table make `(package, policy_run)` ambiguous, so a later pass reading an "
            f"earlier one's rows cannot tell whose it is reading."
        )
        raise PolicyPassError(message)


def _require_contributable(policy_pass: type[PolicyPass], *, name: str) -> tuple[str, ...]:
    """Refuse a contribution the rollup does not offer, or that another pass owns.

    Args:
        policy_pass: The class being registered.
        name: Its declared name, for the messages.

    Returns:
        The contributed columns, unchanged.

    Raises:
        PolicyPassError: When the same column is declared twice; when a column is
            not one the rollup offers -- because it is not a field at all, or
            because it is one of the writer's own stamps -- or when another
            registered pass already owns it.

    """
    columns = tuple(policy_pass.contributes)
    repeated = sorted({column for column in columns if columns.count(column) > 1})
    if repeated:
        message = (
            f"policy pass {name!r} declares {repeated} more than once in contributes={list(columns)}. A "
            f"column has one owner and one declaration: a repeated entry reads as two claims that happen to "
            f"agree, and the ownership map would record one of them."
        )
        raise PolicyPassError(message)

    offered = rollup.contributable_columns()
    invented = [column for column in columns if column not in offered]
    if invented:
        message = (
            f"policy pass {name!r} contributes {invented}, which the rollup {rollup.ROLLUP_MODEL._meta.label} does "  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
            f"not offer. The columns a pass may contribute are {sorted(offered)}: a rollup field that is not "
            f"one of the writer's own stamps. A column the rollup does not declare would be contributed "
            f"nowhere, silently, for as long as the pass ran."
        )
        raise PolicyPassError(message)

    taken = {column: _COLUMN_OWNERS[column] for column in columns if column in _COLUMN_OWNERS}
    if taken:
        message = (
            f"policy pass {name!r} contributes columns another pass already owns: {sorted(taken.items())}. "
            f"A rollup column has one owner, or 'which pass computed this verdict' has two answers and the "
            f"row's per-domain version map cannot say which version produced it (CPM-AD-11)."
        )
        raise PolicyPassError(message)
    return columns
