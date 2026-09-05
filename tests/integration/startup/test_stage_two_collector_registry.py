"""Condition 10: a registered collector with no freshness target refuses to start.

`CPM-AD-28`, and `EVIDENCE.06-AUDIT-001`. An unset per-collector freshness target
behaves as "fresh forever", so evidence collected six months ago reads as current
on every surface -- the `CPM-SM-C1` failure this product exists to prevent, and
one that nothing at run time would report: the collector collects, the rows are
written, and every view shows a clean result derived from an observation nobody
made this year. So the process refuses to start instead.

**Why this lives in the integration tier rather than beside the URLconf cases.**
The condition needs no database and opens no socket, so the *shape* of its
refusal is asserted in `tests/unit/startup/test_no_softening.py` like the other
thirteen. What is asserted here is the behaviour through the real dispatch and the
real, process-global registry: `run_stage_two()` evaluating its whole roster in
order, over the module-level mapping every other process in this repository
shares -- which is the state a deployed boot is actually in, and which a
monkeypatched mapping deliberately is not. That is the same division
`tests/integration/startup/test_stage_two_database_conditions.py` makes for
conditions 5 and 7.

**Nothing is left behind, and that clause is load-bearing here.** The registry is
global and lives for the whole session, so a registration that survived a case
would be a collector every later boot sweep in the run refuses over -- and the
failure would land in whichever case happened to run next rather than in this
file. `tests/collectors.py`'s `registered_collector` withdraws in a `finally`,
which is the only ordering that survives a case whose whole body raises.

**The registry this component really boots with is the other half.**
`CPM-IDENTITY-S06` adopted the first collector, so a deployed boot now sweeps a
roster of one rather than of nothing, and the case that asserts it is what proves
the condition passes over a *real* declaration and not only over fixtures. The
empty case it replaces made the opposite claim and was worth making while it was
true; what it cannot do any more is be true. A condition that refused the roster
below would stop every process in this repository, and it would do so while every
refusal case above still passed -- which is why the roster is asserted rather than
assumed.

`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ImproperlyConfigured

from conda_package_supply_chain_monitor.collectors.tasks import COLLECTOR_NAME as INVENTORY_COLLECTOR_NAME
from conda_package_supply_chain_monitor.core.registry import registrations
from config.locality import PROCESS_ENV_VAR
from config.locality import RUNTIME_ENV_VAR
from config.startup import run_stage_two
from tests.collectors import FIXTURE_FRESHNESS_TARGET
from tests.collectors import collector_class
from tests.collectors import fixture_evidence_model
from tests.collectors import registered_collector
from tests.conftest import deployed_url_patterns
from tests.conftest import temporary_root_urlconf

if TYPE_CHECKING:
    from conda_package_supply_chain_monitor.core.collection import Collector


@pytest.fixture(autouse=True)
def _deployed_and_not_serving(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put every case in a deployed component that is not a serving process.

    Deployed by *deleting* `COMPONENT_RUNTIME` rather than by setting it, because
    locality fails closed (AD-13) and absent therefore means deployed.

    `COMPONENT_PROCESS` goes for a different reason, and it is what keeps these
    cases from needing a database: conditions 5 and 7 gate on
    `config.locality.is_serving_process()`, which reads that variable, so a shell
    or a CI runner holding `COMPONENT_PROCESS=web` would turn every case here
    into one that opens a connection and iterates every configured alias.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(PROCESS_ENV_VAR, raising=False)


def _collector_declaring(target: timedelta | None) -> type[Collector]:
    """Build a fixture collector whose freshness target is the one under test.

    Args:
        target: The declared target, or `None` for the collector that declares
            none.

    Returns:
        A concrete `Collector` subclass, unconstructed -- which is what the boot
        sweep reads, and deliberately: constructing one would build a transport
        and its connection pool inside `django.setup()`.

    """
    return collector_class(
        declared_model=fixture_evidence_model(),
        declared_freshness_target=target,
    )


@pytest.mark.forbidden_state("collector-without-freshness-target")
def test_a_registered_collector_with_no_freshness_target_refuses_the_boot() -> None:
    """`EVIDENCE.06-AUDIT-001`: startup raises rather than defaulting to fresh-forever.

    The message has to name the class, because "a collector has no freshness
    target" tells an operator nothing they can act on while naming the class
    tells them which file to open -- the same standard
    `_refuse_unapplied_migrations` is held to when it names the alias and the
    pending migrations.
    """
    undeclared = _collector_declaring(None)

    with (
        registered_collector(undeclared),
        temporary_root_urlconf(*deployed_url_patterns()),
        pytest.raises(ImproperlyConfigured) as refused,
    ):
        run_stage_two()

    assert undeclared.__name__ in str(refused.value)
    assert "freshness_target=None" in str(refused.value)


@pytest.mark.parametrize(
    "target",
    [timedelta(0), -FIXTURE_FRESHNESS_TARGET],
    ids=["zero", "negative"],
)
def test_a_registered_collector_with_an_unusable_target_refuses_the_boot(target: timedelta) -> None:
    """Absence is not the only way to declare nothing usable.

    A zero target says "evidence is stale the instant it is written", which
    nobody means and which would make every surface permanently amber; a negative
    one says something that has no reading at all. Both would pass a check that
    only asked whether the attribute was set, which is the check somebody writes
    after seeing the case above.

    `NO_WINDOW` is the deliberate contrast: a zero *observation window* is
    accepted, because "observe on every run" is a thing an operator means. The
    two sentinels are the same interval and the opposite decision.
    """
    unusable = _collector_declaring(target)

    with (
        registered_collector(unusable),
        temporary_root_urlconf(*deployed_url_patterns()),
        pytest.raises(ImproperlyConfigured, match="freshness_target"),
    ):
        run_stage_two()


def test_every_offender_is_named_in_one_refusal() -> None:
    """One boot tells the operator about all of them, not the first one alphabetically.

    Raising on the first offender costs a restart per collector: fix the target
    the message named, redeploy, meet the next refusal. With the eight collectors
    `CPM-EP-CURRENCY` is bringing, that is eight boots to learn what one could
    have said -- and each one looks like a fresh problem rather than the
    remainder of a known one.

    Both names are asserted, and the count with them: a message that happened to
    interpolate a list would satisfy a substring check for either name on its
    own.
    """
    first = collector_class(
        declared_model=fixture_evidence_model(),
        declared_name="cpm-fixture-first-undeclared",
        declared_freshness_target=None,
    )
    second = collector_class(
        declared_model=fixture_evidence_model(),
        declared_name="cpm-fixture-second-undeclared",
        declared_freshness_target=timedelta(0),
    )

    with (
        registered_collector(first),
        registered_collector(second),
        temporary_root_urlconf(*deployed_url_patterns()),
        pytest.raises(ImproperlyConfigured) as refused,
    ):
        run_stage_two()

    reported = str(refused.value)
    assert "cpm-fixture-first-undeclared" in reported
    assert "cpm-fixture-second-undeclared" in reported
    assert reported.startswith("2 registered collector(s)")


def test_a_registered_collector_that_declares_a_target_starts() -> None:
    """The negative control, without which the refusals above prove nothing.

    A condition that refused every registered collector would satisfy all three
    cases above and would stop the first component that adopted one.
    """
    declared = _collector_declaring(FIXTURE_FRESHNESS_TARGET)

    with registered_collector(declared), temporary_root_urlconf(*deployed_url_patterns()):
        run_stage_two()


def test_the_registry_this_component_actually_boots_with_does_not_refuse() -> None:
    """The state every component in this repository is actually in today.

    `CPM-IDENTITY-S06` adopted the first real collector, so the registry a
    deployed boot sweeps is no longer empty: `CollectorsConfig.ready()` registers
    inventory ingestion during `django.setup()`, and the sweep meets it on every
    boot in this tree. That is asserted rather than assumed, and both halves
    matter -- the roster is what it is meant to be, and stage two passes over it
    without a fixture in sight.

    Asserted by *name* rather than by identity, and the reason is what the
    registry is *for* rather than an import rule -- this module imports the
    collector's module either way, because a constant lives in it. The name is
    the registry's key, it is what a ledger row carries (`CPM-FR-39`) and what a
    rate-limit allowance is counted against, so "which collectors is this
    component running" is a question about names. A roster compared by identity
    would still pass if two classes had come to share one.
    """
    assert sorted(registrations()) == [INVENTORY_COLLECTOR_NAME]
    assert registrations()[INVENTORY_COLLECTOR_NAME].freshness_target is not None

    with temporary_root_urlconf(*deployed_url_patterns()):
        run_stage_two()
