"""`EVIDENCE.07-AUDIT-002`: no policy pass writes the rollup, and no column has two owners.

`CPM-AD-11` gives current package health one writer. `core/policy.py` refuses a
pass that claims the rollup as its own derived table -- and that refusal binds
only passes that come through `register_pass`, which is exactly the kind of rule
`ASR-3` is about: it holds while everybody remembers to use the front door.

So the rule is checked here as well, over the declarations themselves rather than
over the registration path. The two are complementary rather than redundant: the
registry's refusal is what a developer meets at the moment they make the mistake,
and this is what notices a pass that got into the set some other way -- assigned
directly into the mapping, registered before a column was reassigned, or declared
by a story that decided registration was optional.

**The registry is swept, never a list.** A hand-written roster of passes is
edited by whoever remembers it exists, so the first pass added by somebody who
did not is the one that escapes -- the argument `tests/model_registry.py` records
for models and `tests/unit/django_apps/test_task_routing_audit.py` records for
tasks, applied to passes.

**The sweep is no longer empty, and this module says so rather than assuming
it.** `CPM-CURRENCY-S06` landed `CurrencyPass`, which `policies/apps.py` adopts
during `django.setup()`, so `registered_passes()` returns a real pass owning a
real rollup column and the three sweeps below inspect something. It was written
before that pass existed, deliberately, so the rules would be shaped by
`CPM-AD-11` rather than by whatever the first pass happened to do.

What still keeps it honest either way is that each detector is *also* measured
against fixture passes built in `tests/passes.py` and registered around the case
-- one conforming, one not -- because a single real subject can be conforming for
reasons the detector never had to notice. `test_the_sweep_reaches_the_adopted_passes`
is the anti-vacuity guard for the sweeps themselves.

Reads the pass registry and the model registry: no database, no network, no
subprocess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.policy import PolicyPassError
from conda_package_supply_chain_monitor.core.policy import column_owners
from conda_package_supply_chain_monitor.core.policy import pass_registrations
from conda_package_supply_chain_monitor.core.policy import register_pass
from conda_package_supply_chain_monitor.core.policy import registered_passes
from conda_package_supply_chain_monitor.core.rollup import ROLLUP_MODEL
from conda_package_supply_chain_monitor.core.rollup import STAMP_COLUMNS
from conda_package_supply_chain_monitor.core.rollup import contributable_columns
from conda_package_supply_chain_monitor.policies.currency import POLICY_NAME as CURRENCY_POLICY_NAME
from conda_package_supply_chain_monitor.policies.currency import ROLLUP_COLUMN
from conda_package_supply_chain_monitor.policies.feedstock import POLICY_NAME as FEEDSTOCK_POLICY_NAME
from conda_package_supply_chain_monitor.policies.feedstock import ROLLUP_COLUMN as FEEDSTOCK_ROLLUP_COLUMN
from tests.passes import A_DOMAIN_STATUS
from tests.passes import ADOPTED_PASS_NAMES
from tests.passes import FIRST_DOMAIN
from tests.passes import SECOND_DOMAIN
from tests.passes import fixture_derived_models
from tests.passes import registered_pass
from tests.passes import substituted_rollup
from tests.passes import working_pass_class

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Iterator

    from conda_package_supply_chain_monitor.core.policy import PolicyPass

#: The column the substituted rollup offers, for the cases that need a
#: contributable column *nobody owns* -- the real rollup's two columns,
#: `currency_status` and `feedstock_presence_status`, are owned by `CurrencyPass`
#: and `FeedstockPresencePass` from `django.setup()` onwards.
#:
#: `tests/passes.py` owns both the name and the model that declares it, so the
#: substitution and the column it is about cannot drift. And the substitution is
#: of `core/rollup.py`'s model rather than of a name inside `core/policy.py`:
#: the registry reads `rollup.contributable_columns()` at call time precisely so
#: that patching the rollup reaches it, and a case that patched a name bound at
#: import would be describing a path it never took.
A_SHARED_COLUMN: Final[str] = A_DOMAIN_STATUS


@pytest.fixture(autouse=True)
def _only_the_adopted_passes() -> Iterator[None]:
    """Assert the registry holds exactly the adopted passes, before and after each case.

    Not "empty": the registry has not been empty since `policies/apps.py` adopted
    `CurrencyPass`, and this module's whole point is to sweep the registry as it
    really is. What it must catch is *leakage* -- a case that failed after
    registering a fixture pass would otherwise leave it behind, the next case's
    sweep would fail for a reason it does not name, and
    `tests/unit/django_apps/test_policy_registry.py` would fail in a different
    module with no indication of where the pass came from.

    `ADOPTED_PASS_NAMES` is `tests/passes.py`'s single declaration of the roster,
    so this and the withdrawal that module offers cannot disagree about it.

    Yields:
        Nothing; the assertions are the fixture.

    """
    expected = sorted(ADOPTED_PASS_NAMES)
    assert sorted(pass_registrations()) == expected, "a previous case left a policy pass registered"
    yield
    assert sorted(pass_registrations()) == expected, "this case left a policy pass registered"


def rollup_claimants(passes: Iterable[type[PolicyPass]]) -> list[str]:
    """Return every pass declaring the rollup as the table it owns.

    Args:
        passes: The pass classes to inspect.

    Returns:
        The offending passes' declared names, in the order they were given. A
        list rather than a boolean so a failure names the pass, which is what
        `EVIDENCE.07-AUDIT-002` asks for.

    """
    return [declared.name for declared in passes if declared.derived_model is ROLLUP_MODEL]


def stamp_claimants(passes: Iterable[type[PolicyPass]]) -> list[str]:
    """Return every pass contributing a column the writer owns outright.

    Args:
        passes: The pass classes to inspect.

    Returns:
        `pass name: column` strings, one per offence. A stamp is a real field on
        the rollup, so nothing but this and the registry's own refusal separates
        it from a legitimate contribution.

    """
    return [
        f"{declared.name}: {column}"
        for declared in passes
        for column in declared.contributes
        if column in STAMP_COLUMNS
    ]


def contested_columns(passes: Iterable[type[PolicyPass]]) -> list[str]:
    """Return every rollup column more than one pass claims.

    Read off the declarations rather than off `column_owners()`, deliberately:
    the ownership map is written *by* registration, so an audit that read it
    would only ever confirm what the registry already refused.

    Args:
        passes: The pass classes to inspect.

    Returns:
        `column: [pass, pass]` strings, one per contested column, sorted.

    """
    claims: dict[str, list[str]] = {}
    for declared in passes:
        for column in declared.contributes:
            claims.setdefault(column, []).append(declared.name)
    return sorted(f"{column}: {sorted(owners)}" for column, owners in claims.items() if len(owners) > 1)


def uncontributable_columns(passes: Iterable[type[PolicyPass]]) -> list[str]:
    """Return every claim on a column the rollup does not offer.

    Args:
        passes: The pass classes to inspect.

    Returns:
        `pass name: column` strings, one per offence.

    """
    offered = contributable_columns()
    return [
        f"{declared.name}: {column}" for declared in passes for column in declared.contributes if column not in offered
    ]


def test_no_registered_pass_claims_the_rollup() -> None:
    """`EVIDENCE.07-AUDIT-002`, against whatever the registry actually holds.

    Real since `CPM-CURRENCY-S06`: `CurrencyPass` declares `PackageCurrency` as
    its derived table, so this sweep now compares a live declaration against the
    rule rather than comparing nothing. It was written before that pass existed
    because the guard has to exist before the thing it guards, or it is shaped by
    that thing instead of by `CPM-AD-11` -- and because the moment a pass declares
    `derived_model = PackageHealth`, this is what says so.
    """
    claimants = rollup_claimants(registered_passes())

    assert claimants == [], (
        f"a policy pass declares the rollup as its own derived table: {claimants}. CPM-AD-11 gives current "
        f"package health one writer, core/rollup.py; a pass owns its own per-domain table and nothing else."
    )


def test_no_registered_pass_contributes_a_stamp_or_an_unoffered_column() -> None:
    """The other half of ownership: what a pass may put *into* the rollup.

    Two rules in one case because they fail the same way -- a claim on a column
    that is not this pass's to produce -- and because separating them would make
    a reader think one of them was optional.
    """
    passes = registered_passes()

    assert stamp_claimants(passes) == [], "a policy pass contributes one of the rollup writer's own stamps"
    assert uncontributable_columns(passes) == [], "a policy pass contributes a column the rollup does not declare"


def test_the_sweep_reaches_the_adopted_passes() -> None:
    """The three sweeps above mean nothing if the registry they read is empty.

    That was the honest state of this module until `CPM-CURRENCY-S06`: no policy
    epic had run, so every assertion passed over nothing and would have passed
    just as well with the detectors broken. `CurrencyPass` is now adopted at
    `django.setup()`, and this is what says the sweeps are reading it -- so a
    `policies/apps.py` that stopped registering, or an application dropped from
    `LOCAL_APPS`, fails here rather than quietly restoring the vacuum.

    Both halves, because either alone is satisfiable for the wrong reason: the
    adopted pass must be in the registry, and it must own a column that the
    rollup really offers -- an ownership map naming a column nobody declares
    would be the very state `uncontributable_columns` exists to report.
    """
    registered = {declared.name for declared in registered_passes()}

    assert set(ADOPTED_PASS_NAMES) <= registered, (
        f"the adopted passes are not in the registry the sweeps read: {sorted(registered)}"
    )
    assert ROLLUP_COLUMN in contributable_columns(), (
        f"{ROLLUP_COLUMN!r} is not a column the rollup offers, so the adopted pass's contribution is not "
        f"something these sweeps can be about"
    )


def test_no_rollup_column_has_two_owners() -> None:
    """One owner per column, or the row's per-domain version map cannot say who produced it."""
    contested = contested_columns(registered_passes())

    assert contested == [], f"more than one policy pass claims a rollup column: {contested}"


def test_the_claim_detector_would_notice_a_pass_claiming_the_rollup() -> None:
    """The anti-vacuity guard for the sweep, and the reason it can be trusted while empty.

    Two passes, differing only in the declaration under test, so the detector is
    shown to *separate* them rather than merely to return an empty list. The
    offender is never registered: `register_pass` refuses it, which is the other
    half of the rule and is asserted in
    `tests/unit/django_apps/test_policy_registry.py`. This audit is what catches
    the same declaration arriving some other way, so it is measured on the
    declaration rather than on the registration.
    """
    conforming = working_pass_class()
    claimant = working_pass_class(name=SECOND_DOMAIN, derived_model=PackageHealth)

    assert rollup_claimants([claimant]) == [SECOND_DOMAIN]
    assert rollup_claimants([conforming]) == []
    assert rollup_claimants([conforming, claimant]) == [SECOND_DOMAIN]


def test_the_contest_detector_would_notice_two_owners() -> None:
    """The anti-vacuity guard for the contested-column case.

    The offered set is substituted for the reason
    `tests/unit/django_apps/test_policy_registry.py` gives at length: every column
    the real rollup offers already has an adopted owner from `django.setup()`
    onwards, so against the real model the *first* pass below would collide with a
    real owner and the two-fixture-pass rule would never be reached. The
    substitution puts an *unowned* column in the world.

    `substituted_rollup()` rather than a bare `monkeypatch`, and for the reason
    `tests/passes.py` records: the substitution has to end before any fixture
    teardown that re-registers a real pass, because `register_pass` re-reads
    `contributable_columns()` and would refuse `CurrencyPass` against a synthetic
    rollup that does not declare its column.

    **The first pass really is registered, which is the point of the patch.** The
    detector reads declarations rather than the ownership map, so it would answer
    identically over two unregistered classes -- and the case would then describe
    a path it never took, with an inert `monkeypatch` above it saying otherwise.
    Registering the owner puts the audit's subject in the live registry, shows the
    registry's own refusal and this detector agreeing about the same pair, and
    makes the patch load-bearing.
    """
    first, second = fixture_derived_models()
    owner = working_pass_class(name=FIRST_DOMAIN, derived_model=first, contributes=(A_SHARED_COLUMN,))
    rival = working_pass_class(name=SECOND_DOMAIN, derived_model=second, contributes=(A_SHARED_COLUMN,))

    with substituted_rollup(), registered_pass(owner):
        assert column_owners()[A_SHARED_COLUMN] == FIRST_DOMAIN
        assert column_owners()[ROLLUP_COLUMN] == CURRENCY_POLICY_NAME, (
            "the adopted currency pass no longer owns the rollup column it declares, so this case is "
            "measuring the ownership map with a piece missing"
        )
        assert contested_columns(registered_passes()) == []
        with pytest.raises(PolicyPassError, match=A_SHARED_COLUMN):
            register_pass(rival)

        # The rival never reached the registry, so the detector is shown the pair
        # the registry refused -- which is the arrangement it exists to catch
        # when something gets in some other way.
        assert contested_columns([owner, rival]) == [f"{A_SHARED_COLUMN}: {[FIRST_DOMAIN, SECOND_DOMAIN]}"]
        assert contested_columns([owner]) == []


def test_the_stamp_detector_would_notice_a_claim_on_a_stamp() -> None:
    """The anti-vacuity guard for the stamp rule.

    A stamp is a real field on the rollup, unlike an invented column, so a
    detector that only compared against `contributable_columns()` would report
    it -- and one that compared against *every* field would not. The pair is what
    separates the two.
    """
    a_stamp = "computed_at"
    forger = working_pass_class(contributes=(a_stamp,))
    conforming = working_pass_class(name=SECOND_DOMAIN)

    assert a_stamp in STAMP_COLUMNS
    assert stamp_claimants([forger]) == [f"{FIRST_DOMAIN}: {a_stamp}"]
    assert stamp_claimants([conforming]) == []


def test_the_audit_reaches_a_pass_that_is_actually_registered() -> None:
    """The sweep means nothing if what it reads is not the live registry.

    A conforming pass is registered and the audit is re-run over it: the set the
    detectors were handed has to be the one `register_pass` writes into, or the
    three cases above are inspecting a tuple that nothing populates.
    """
    with registered_pass(working_pass_class()) as declared:
        assert declared in registered_passes()
        assert rollup_claimants(registered_passes()) == []
        # The fixture pass contributes nothing, so the only entries in the map
        # are the two adopted passes' own columns. Asserted as equality rather
        # than as a containment check: an ownership map that had acquired a
        # second owner for either column some other way is exactly what this
        # audit is for.
        assert column_owners() == {
            ROLLUP_COLUMN: CURRENCY_POLICY_NAME,
            FEEDSTOCK_ROLLUP_COLUMN: FEEDSTOCK_POLICY_NAME,
        }


def test_the_rollup_the_audit_guards_is_the_one_the_writer_writes() -> None:
    """The two modules must be talking about the same table.

    `core/rollup.py` names the model once and `core/policy.py` refuses a pass
    claiming it; an audit reading a different model would police a table nobody
    writes. Asserted rather than assumed, because the two are separate imports
    and a later split of the rollup into two tables is exactly the edit that
    would leave one of them unguarded.
    """
    assert ROLLUP_MODEL is PackageHealth
    assert STAMP_COLUMNS & contributable_columns() == set()
