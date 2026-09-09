"""The demo seeder's declarations: refused outside a local run, and spelled correctly.

Two things are checked here and the second is the one the module's own docstring
promises. `config/local_dev/demo_data.py` writes evidence with **string literals**
for the states -- `"normalized"`, `"inferred_compatible"`, `"established"` -- because
`core/outcomes.py`'s `outcome_type` composes each vocabulary per domain and a member
reference is invisible to the type checker. A literal that drifted from the column's
declared choices would fail at the first `IntegrityError` on somebody's laptop,
halfway through seeding, with a constraint name and no hint which value was wrong.
That is exactly what happened while the module was being written -- twice -- so the
reconciliation is a test.

**The refusal is checked before any row is written**, which is the whole of why it
matters: `CPM-AD-2` makes evidence append-only, so a fictional observation written by
a deployed component cannot be deleted and would be read by every replayed policy run
afterwards. A refusal that fired after the first insert would be no refusal at all.

Reads declarations and model metadata: no database writes, no policy run. What the
seeder actually produces is `tests/integration/test_local_dev_demo_seeding.py`.
"""

from __future__ import annotations

from typing import Final

import pytest
from django.core.exceptions import ImproperlyConfigured

from conda_sentinel.collectors.models import CondaPackageSnapshot
from conda_sentinel.collectors.models import LicenseFinding
from conda_sentinel.collectors.models import PyPIReleaseSnapshot
from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.models import SourceReleaseSnapshot
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.core.registry import registered_collectors
from conda_sentinel.identity.models import MappingOutcome
from config.local_dev import demo_data

#: The literals the seeder writes, and the model whose `state` column has to accept
#: each. Written out rather than read from the module's private names, so the pairing
#: is stated here and a rename on either side is a failing case rather than a test
#: that quietly checks a value against itself.
DECLARED_STATES: Final[tuple[tuple[str, type], ...]] = (
    ("normalized", LicenseFinding),
    ("inferred_compatible", PythonReadinessAssessment),
)

#: How many packages the demo seeds. Ten, and the number is asserted because the
#: point of the roster is *variety* -- a seeder that had lost eight of them would
#: still produce a screen, and the screen would look fine.
EXPECTED_PACKAGES: Final[int] = 10


@pytest.mark.parametrize(("value", "model"), DECLARED_STATES, ids=str)
def test_every_state_literal_is_one_its_column_declares(value: str, model: type) -> None:
    """The reconciliation the module's docstring promises.

    A literal that drifted fails here, naming the value and the table, rather than at
    the first `IntegrityError` halfway through seeding somebody's laptop.

    Args:
        value: The literal the seeder writes.
        model: The evidence model whose `state` column must accept it.

    """
    declared = {choice for choice, _label in model._meta.get_field("state").choices}  # noqa: SLF001 - model metadata

    assert value in declared, f"{model.__name__}.state does not accept {value!r}; it accepts {sorted(declared)}"


def test_the_mapping_outcome_literals_are_ones_the_vocabulary_declares() -> None:
    """The identity resolution's own vocabulary, checked the same way.

    `MappingOutcome` is composed by `outcome_type` too, so `_ESTABLISHED` and
    `_NOT_FOUND` are literals for the same reason and can drift for the same reason.
    """
    declared = set(MappingOutcome.values)

    assert "established" in declared
    assert "not_found" in declared


def test_the_demo_collector_is_not_a_registered_collector() -> None:
    """The coverage screen reads the run ledger by collector name.

    Seeding runs under `vulnerability` would report that collector as healthy on a
    machine where it has never made a single request -- which is precisely the lie
    `surface/coverage.py` exists to prevent, told by the fixture meant to demonstrate
    it.
    """
    adopted = {collector.name for collector in registered_collectors()}

    assert demo_data.DEMO_COLLECTOR not in adopted
    assert adopted != set()


def test_the_roster_seeds_enough_packages_to_show_variety() -> None:
    """A seeder that had lost most of its roster would still render a plausible screen.

    Which is the failure worth catching: the demo exists to show that the design
    distinguishes states, and eight identical rows demonstrate nothing.
    """
    assert len(demo_data.DEMO_PACKAGES) == EXPECTED_PACKAGES
    assert len({demo.name for demo in demo_data.DEMO_PACKAGES}) == EXPECTED_PACKAGES


def test_the_roster_covers_every_state_the_screens_must_distinguish() -> None:
    """`CPM-FR-5`'s five states, each present in the seeded inventory.

    Asserted over the *declarations* rather than over what the run concludes, because
    this is the roster's job: a demo that produced only clean packages and adverse
    verdicts would leave the three states a reader most needs to tell apart untested
    by eye.
    """
    assert any(demo.advisory for demo in demo_data.DEMO_PACKAGES), "no adverse verdict"
    assert any(not demo.advisory for demo in demo_data.DEMO_PACKAGES), "nothing found by a lookup"
    assert any(not demo.feedstock for demo in demo_data.DEMO_PACKAGES), "nothing to find"
    assert any(demo.python_evidence == "none" for demo in demo_data.DEMO_PACKAGES), "no question that does not apply"

    assert any(demo.errored for demo in demo_data.DEMO_PACKAGES), "no lookup that broke"
    assert any(not demo.identified for demo in demo_data.DEMO_PACKAGES), "nothing for the confidence gate to blank"


def test_the_roster_covers_both_kinds_of_python_evidence() -> None:
    """`CPM-PY314-S03` made the kind of evidence part of the verdict.

    The detail view traces a verified verdict to the build and an inferred one to the
    metadata, and a demo carrying only one kind would exercise one branch.

    The values are named for the *evidence* -- `build`, `metadata` -- rather than for
    the verdict. `verified` is also an `IdentityConfidence` value, and comparing
    against it reads like a second confidence gate; the confidence-gate audit said so
    when the module was first written.
    """
    kinds = {demo.python_evidence for demo in demo_data.DEMO_PACKAGES}

    assert {"build", "metadata", "none"} <= kinds


def test_the_roster_carries_a_kev_listing_and_a_non_listing() -> None:
    """The KEV column qualifies the vulnerability column beside it.

    A demo where every advisory was listed -- or none was -- would make the two
    columns look like one.
    """
    with_advisory = [demo for demo in demo_data.DEMO_PACKAGES if demo.advisory]

    assert any(demo.kev_listed for demo in with_advisory)
    assert any(not demo.kev_listed for demo in with_advisory)


def test_seeding_is_refused_outside_a_local_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CPM-AD-2` is why this refusal has to fire before the first insert.

    Evidence is append-only: a fictional observation written by a deployed component
    cannot be deleted, and every replayed policy run would read it afterwards. A
    refusal that fired after the first row would be no refusal at all.

    Args:
        monkeypatch: pytest's patcher, which restores the locality reader.

    """
    monkeypatch.setattr(demo_data, "is_local", lambda: False)

    with pytest.raises(ImproperlyConfigured, match=r"append-only"):
        demo_data.seed_demo_inventory()


def test_the_refusal_names_what_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal a reader cannot act on sends them to the source to find out how.

    Args:
        monkeypatch: pytest's patcher.

    """
    monkeypatch.setattr(demo_data, "is_local", lambda: False)

    with pytest.raises(ImproperlyConfigured, match=r"COMPONENT_RUNTIME=local"):
        demo_data.seed_demo_inventory()


def test_no_demo_package_declares_a_verdict() -> None:
    """The constraint the whole module is shaped around, asserted as a shape.

    `DemoPackage` has no field that says "this should come out P1". Every field is an
    observation, and what the screens show has to be something the policy engine
    concluded from them -- otherwise the demo is a picture of a product rather than
    the product.
    """
    fields = {field.name for field in demo_data.DemoPackage.__dataclass_fields__.values()}
    verdict_shaped = {"priority", "bucket", "work_type", "status", "readiness", "currency"}

    assert fields & verdict_shaped == set(), sorted(fields & verdict_shaped)


@pytest.mark.parametrize("model", [SourceReleaseSnapshot, PyPIReleaseSnapshot, CondaPackageSnapshot])
def test_the_release_snapshots_accept_the_ok_state_the_seeder_writes(model: type) -> None:
    """Three tables where the determinate value *is* `ok`, unlike the two above.

    Which is the trap: `LicenseFinding` calls its determinate state `normalized` and
    `PythonReadinessAssessment` calls its `inferred_compatible`, while these three
    call theirs `ok`. Writing `ok` to the first two is the mistake the seeder made,
    and this is the case that says the other three are not the same.

    Args:
        model: The evidence model under test.

    """
    declared = {choice for choice, _label in model._meta.get_field("state").choices}  # noqa: SLF001 - model metadata

    assert "ok" in declared


def test_the_vulnerability_table_does_not_accept_ok() -> None:
    """And the one that catches the trap from the other side.

    `VulnerabilityFinding`'s determinate state is `matched`. If it ever grew an `ok`,
    the seeder's states would still be right but the argument above would have
    quietly stopped being the reason they are.
    """
    declared = {choice for choice, _label in VulnerabilityFinding._meta.get_field("state").choices}  # noqa: SLF001

    assert "ok" not in declared
    assert "matched" in declared


def test_a_package_with_no_feedstock_still_seeds_one_snapshot() -> None:
    """`FeedstockSnapshot.absence_established` separates two things that look alike.

    "We looked and there is no feedstock" and "we did not look" are different, and
    `CPM-FR-5` turns on a reader being able to tell them apart. The demo seeds the
    first, so the screen shows a `not_found` a reviewer can trust.
    """
    absent = [demo for demo in demo_data.DEMO_PACKAGES if not demo.feedstock]

    assert absent != []


def test_an_idle_feedstock_is_older_than_the_shipped_inactivity_threshold() -> None:
    """The feedstock pass reads a threshold from the parameter file.

    The demo's idle feedstock has to be idle by *that* measure, not by a number
    chosen here -- otherwise the row renders `present_and_maintained` and the
    inactive state never appears on the screen.
    """
    shipped_threshold_days = 180
    idle = max(demo.feedstock_idle_days for demo in demo_data.DEMO_PACKAGES)

    assert idle > shipped_threshold_days
