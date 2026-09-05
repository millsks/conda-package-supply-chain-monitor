"""Passes register rather than being called, and the registry refuses four things.

`CPM-AD-21` puts the passes under one orchestrating run and `CPM-AD-11` gives the
rollup one writer. Neither survives a run that *called* its passes: the set would
not be enumerable, so "no pass writes the rollup" would be a code review somebody
has to remember to do -- which is `ASR-3`. Registration is what makes the rule
checkable against passes nobody has written.

**Declared order, not sorted order.** This is the one place this registry
deliberately differs from `core/registry.py`, which sorts collectors by name.
`CPM-AD-21` says a later pass may read an earlier pass's derived rows for the
same run, so the order is a *declaration* about which reads which, and sorting it
alphabetically would make that depend on what somebody called their pass.

**The rollup offers no contributable column today**, because it declares no
domain status column yet -- `epics.md` says it "grows as passes are added" and
none has been. That is why the two column refusals are shaped differently below:
"a column the rollup does not declare" is reachable against the real rollup and
is asserted against it, while "two passes, one column" needs a column to exist at
all, so the case substitutes the offered set and says so.

Every case registers through the fixture context manager in `tests/passes.py`,
which withdraws on the way out: registration is process-global, and a case that
left a pass behind would be seen by the ownership audit in a different module
with no indication of where it came from.

Reads no database and opens no network: a registry is a dictionary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.db import models

from conda_package_supply_chain_monitor.core import rollup as rollup_module
from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.policy import PolicyPass
from conda_package_supply_chain_monitor.core.policy import PolicyPassError
from conda_package_supply_chain_monitor.core.policy import column_owners
from conda_package_supply_chain_monitor.core.policy import pass_registrations
from conda_package_supply_chain_monitor.core.policy import register_pass
from conda_package_supply_chain_monitor.core.policy import registered_passes
from conda_package_supply_chain_monitor.core.policy import unregister_pass
from conda_package_supply_chain_monitor.core.rollup import contributable_columns
from tests.passes import A_DOMAIN_STATUS
from tests.passes import AN_UNDECLARED_COLUMN
from tests.passes import FIRST_DOMAIN
from tests.passes import NO_DERIVED_MODEL
from tests.passes import OTHER_DOMAIN
from tests.passes import SECOND_DOMAIN
from tests.passes import fixture_derived_models
from tests.passes import registered_pass
from tests.passes import rollup_with_a_domain_column
from tests.passes import working_pass_class

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The column the substituted rollup offers, for the cases that need a
#: contributable column to exist at all -- the real one declares none.
#:
#: `tests/passes.py` owns both the name and the model that declares it, so the
#: substitution and the column it is about cannot drift. And the substitution is
#: of `core/rollup.py`'s model rather than of a name inside `core/policy.py`:
#: the registry reads `rollup.contributable_columns()` at call time precisely so
#: that patching the rollup reaches it, and a case that patched a name bound at
#: import would be describing a path it never took.
A_SHARED_COLUMN: Final[str] = A_DOMAIN_STATUS


@pytest.fixture(autouse=True)
def _empty_registry() -> Iterator[None]:
    """Assert the registry starts and ends empty, so cases cannot leak into each other.

    Registration is process-global. Without this, a case that failed *after*
    registering would leave a pass behind, the next case's "declared order"
    assertion would fail for a reason it does not name, and the ownership audit
    in another module would fail too.

    Yields:
        Nothing; the assertions are the fixture.

    """
    assert pass_registrations() == {}, "a previous case left a policy pass registered"
    yield
    assert pass_registrations() == {}, "this case left a policy pass registered"


def test_a_registered_pass_is_returned() -> None:
    """The plainest thing the registry does, and the anti-vacuity guard for the rest.

    Every refusal below is only meaningful while registration itself works: a
    `register_pass` that refused everything would satisfy each of them.
    """
    declared = working_pass_class()

    with registered_pass(declared):
        assert registered_passes() == (declared,)
        assert pass_registrations() == {FIRST_DOMAIN: declared}


def test_passes_are_returned_in_declared_order_not_sorted_order() -> None:
    """`CPM-AD-21`'s ordered read is a property of the declaration.

    The two names are chosen so that the declared order and the sorted order
    disagree: `second` is registered before `first`, so a registry that sorted by
    name -- as `core/registry.py` deliberately does for collectors -- would return
    them the other way round and this case would say so.
    """
    first, second = fixture_derived_models()
    later = working_pass_class(name=SECOND_DOMAIN, derived_model=second)
    earlier = working_pass_class(name=FIRST_DOMAIN, derived_model=first)

    with registered_pass(later), registered_pass(earlier):
        assert registered_passes() == (later, earlier)
        assert [declared.name for declared in registered_passes()] != sorted(
            declared.name for declared in registered_passes()
        ), "the two fixture names must disagree with their sorted order, or this case proves nothing"


def test_a_second_pass_under_a_registered_name_is_refused() -> None:
    """Two passes under one name are indistinguishable in every report.

    The name keys this registry and keys the rollup's per-domain `policy_versions`
    map, so the second would silently replace the first in what the orchestration
    executes while both remained in somebody's mental model.
    """
    first, second = fixture_derived_models()
    declared = working_pass_class(name=FIRST_DOMAIN, derived_model=first)
    impostor = working_pass_class(name=FIRST_DOMAIN, derived_model=second)

    with registered_pass(declared), pytest.raises(PolicyPassError, match=FIRST_DOMAIN):
        register_pass(impostor)


def test_a_pass_claiming_the_rollup_as_its_own_table_is_refused() -> None:
    """`CPM-AD-11`: one writer composes current package health, and it is not a pass.

    Refused at the moment somebody tries rather than discovered later in a table
    with two authors. `tests/unit/django_apps/test_pass_ownership_audit.py`
    refuses it again from outside the registry, because this refusal only binds
    passes that come through this function.
    """
    claimant = working_pass_class(derived_model=PackageHealth)

    with pytest.raises(PolicyPassError, match=PackageHealth._meta.label):  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        register_pass(claimant)


def test_a_contribution_the_rollup_does_not_declare_is_refused() -> None:
    """A misspelled column contributes nowhere, silently, for as long as the pass runs.

    Asserted against the real rollup, which offers no contributable column at
    all: `PackageHealth` declares its identity, its stamps and the confidence and
    no domain status yet. So every contribution is refused today, and the message
    names both the column and the pass.
    """
    inventor = working_pass_class(contributes=(AN_UNDECLARED_COLUMN,))

    with pytest.raises(PolicyPassError, match=AN_UNDECLARED_COLUMN):
        register_pass(inventor)


def test_a_stamp_column_is_not_contributable() -> None:
    """The writer's own columns are not a pass's to produce.

    `package`, `policy_run`, `computed_at`, `evidence_cutoff`, `confidence` and
    `policy_versions` are the row's identity and provenance. A pass contributing
    one would be rewriting the statement about where the row came from, which is
    the single thing `CPM-AD-11` puts in one writer's hands -- and unlike an
    invented column, a stamp *is* a real field, so nothing but this refusal stops
    it.
    """
    a_stamp = "computed_at"
    forger = working_pass_class(contributes=(a_stamp,))

    assert a_stamp not in contributable_columns()
    with pytest.raises(PolicyPassError, match=a_stamp):
        register_pass(forger)


def test_two_passes_cannot_own_one_column(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rollup column has one owner, or its version map cannot say which version produced it.

    **The offered set is substituted, and that is the honest way to write this
    case.** The rollup declares no contributable column yet, so against the real
    model the *first* registration would be refused for inventing a column and
    the second-owner rule would never be reached -- a case that "passed" without
    exercising anything. Substituting `contributable_columns` where
    `core/policy.py` reads it puts one column in the world, which is exactly the
    state the first real policy epic creates, and leaves every other refusal
    reading the real model.
    """
    first, second = fixture_derived_models()
    monkeypatch.setattr(rollup_module, "ROLLUP_MODEL", rollup_with_a_domain_column())
    owner = working_pass_class(name=FIRST_DOMAIN, derived_model=first, contributes=(A_SHARED_COLUMN,))
    rival = working_pass_class(name=SECOND_DOMAIN, derived_model=second, contributes=(A_SHARED_COLUMN,))

    with registered_pass(owner):
        assert column_owners() == {A_SHARED_COLUMN: FIRST_DOMAIN}
        with pytest.raises(PolicyPassError, match=A_SHARED_COLUMN):
            register_pass(rival)


def test_withdrawing_a_pass_frees_the_columns_it_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    """A withdrawal that left the columns owned would refuse the pass's own re-registration.

    The failure is not hypothetical: every case that registers a pass withdraws
    it on the way out, so a leftover ownership entry would make the *next* case
    registering the same column fail with a message naming a pass that is no
    longer there.
    """
    monkeypatch.setattr(rollup_module, "ROLLUP_MODEL", rollup_with_a_domain_column())
    owner = working_pass_class(contributes=(A_SHARED_COLUMN,))

    register_pass(owner)
    unregister_pass(FIRST_DOMAIN)

    assert column_owners() == {}
    with registered_pass(owner):
        assert column_owners() == {A_SHARED_COLUMN: FIRST_DOMAIN}


def test_withdrawing_a_name_nothing_registered_is_refused() -> None:
    """A silent no-op turns a misspelled withdrawal into a registration that stays live.

    The same rule `core/registry.py`'s `unregister` states, for the same reason:
    the caller believes the pass is gone and it is not.
    """
    with pytest.raises(PolicyPassError, match=OTHER_DOMAIN):
        unregister_pass(OTHER_DOMAIN)


def test_something_that_is_not_a_pass_is_refused() -> None:
    """The contract the orchestration and the audit both read lives in the base class.

    A registered class that does not inherit it carries none of the declarations
    either of them looks for, and the failure would land in a worker that had
    already opened a ledger row.
    """
    with pytest.raises(PolicyPassError, match="PolicyPass"):
        register_pass(object)  # type: ignore[arg-type] - the refusal is the subject


@pytest.mark.parametrize(
    "name",
    ["", "   "],
    ids=["empty", "whitespace"],
)
def test_a_pass_declaring_no_name_is_refused(name: str) -> None:
    """A blank name keys nothing -- not the registry, and not the row's version map.

    Whitespace is included because `"  "` is truthy in Python and would otherwise
    be a name that satisfies every check and appears in a report as nothing at
    all.
    """
    nameless = working_pass_class(name=name)

    with pytest.raises(PolicyPassError, match="names nothing"):
        register_pass(nameless)


def test_a_pass_owning_no_derived_table_is_refused() -> None:
    """A pass owns exactly one per-domain table and writes only that (`CPM-AD-21`).

    A pass with none has nowhere to put what it computed, so its verdicts would
    exist only inside one run's memory -- and `CPM-FR-22`'s replay guarantee is
    about comparing a re-run against what the original wrote.
    """
    tableless = working_pass_class()
    tableless.derived_model = NO_DERIVED_MODEL

    with pytest.raises(PolicyPassError, match="not a Django model"):
        register_pass(tableless)


def test_the_base_class_computes_nothing() -> None:
    """A registered pass that never overrode `evaluate` must fail loudly at the first package.

    The alternative is a run that writes a clean-looking rollup having evaluated
    nothing, which is the silent failure `CPM-FR-6` and `CPM-AD-5` exist to keep
    out of a status column.
    """
    with pytest.raises(NotImplementedError):
        PolicyPass().evaluate(None, policy_run=None, evidence_cutoff=None)  # type: ignore[arg-type] - the refusal is the subject


def test_the_fixture_derived_models_are_shaped_like_a_real_one() -> None:
    """The fixtures are only evidence about the rules while they look like the thing.

    `CPM-AD-21` keys a derived table `(package, policy_run)`, so a fixture
    carrying one of the two -- or neither -- would let the orchestration cases
    pass while proving nothing about what a real pass writes.
    """
    for model in fixture_derived_models():
        declared = {field.name for field in model._meta.concrete_fields}  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

        assert {"package_id", "policy_run_id"} <= declared, model
        assert issubclass(model, models.Model)


def test_two_passes_cannot_own_one_derived_table() -> None:
    """`CPM-AD-21` gives each pass its own per-domain table keyed `(package, policy_run)`.

    Two passes writing one table make that key ambiguous: a later pass reading an
    earlier one's rows for this run cannot tell whose rows it is reading, and the
    ordered read is the whole reason the registry keeps declaration order. The
    duplicate-*name* refusal cannot see this -- the names differ, which is exactly
    what a copy-pasted pass declaration looks like before somebody finishes
    editing it.
    """
    first, _second = fixture_derived_models()
    owner = working_pass_class(name=FIRST_DOMAIN, derived_model=first)
    squatter = working_pass_class(name=SECOND_DOMAIN, derived_model=first)

    with registered_pass(owner), pytest.raises(PolicyPassError, match=FIRST_DOMAIN):
        register_pass(squatter)


def test_one_class_cannot_be_registered_under_two_names() -> None:
    """`name` is a class attribute, so this is one object claiming two domains.

    It would run twice per package per run, write its derived table twice, and
    claim two entries in the rollup's per-domain version map for one domain --
    and the duplicate-name check cannot see it, because the names differ by
    construction.
    """
    declared = working_pass_class(name=FIRST_DOMAIN)

    with registered_pass(declared):
        declared.name = SECOND_DOMAIN
        try:
            with pytest.raises(PolicyPassError, match="already registered"):
                register_pass(declared)
        finally:
            # Restored inside the case rather than left to the fixture: the
            # withdrawal on the way out is keyed on the name, and a class left
            # renamed would be withdrawn under a name nothing registered.
            declared.name = FIRST_DOMAIN


def test_a_pass_declaring_one_column_twice_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repeated entry reads as two claims that happen to agree.

    The ownership map records one of them, so the duplicate is invisible
    afterwards -- and the day the two entries stop agreeing, because somebody
    edited one of them, the pass silently contributes whichever the map kept. The
    offered set is substituted for the reason the two-owner case gives: the
    rollup declares no contributable column yet.
    """
    monkeypatch.setattr(rollup_module, "ROLLUP_MODEL", rollup_with_a_domain_column())
    stutterer = working_pass_class(contributes=(A_SHARED_COLUMN, A_SHARED_COLUMN))

    with pytest.raises(PolicyPassError, match=A_SHARED_COLUMN):
        register_pass(stutterer)
