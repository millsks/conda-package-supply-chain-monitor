"""What the one writer puts in a row, including the columns no rollup declares yet.

The unit half of `tests/integration/django_apps/test_rollup.py`. That module
asserts what reaches the database; this one asserts the *composition* -- which is
where the two rules with no real subject today live.

**`CPM-AD-4`'s gate applied to a contributed column has nowhere to happen against
the real rollup.** `PackageHealth` declares its identity, its stamps and the
confidence and no domain status column, because `epics.md` says the table "grows
as passes are added" and no policy epic has run. So the acceptance criterion --
an `unmapped` package's gated statuses read `unknown` -- cannot be shown end to
end without inventing a column, which the story forbids. What it *can* be shown
against is a synthetic rollup declaring one, substituted where `core/rollup.py`
names the model. That is the same device
`tests/unit/django_apps/test_derived_status_writability_audit.py` uses for the
rule it was written before there was a table for: measure the detector against a
declaration built here, so an empty repository cannot make it pass vacuously.

**The full-row replace is the other rule with no subject.** A merge and a replace
are indistinguishable while every column is a stamp the writer always sets; they
differ only on a contributable column *nobody contributed*, which must come out
as the field's own default rather than as whatever a previous run left. That is
the fourth case below, and it is the one that fails if the writer ever starts
merging.

**The two rules meet in the fifth case, which is where a real defect lived.** A
column nobody contributed, on a package whose identity is `unmapped`: gating only
the *contributed* verdicts leaves the default path ungated, and a field default
is a claim about the package just as much as a verdict is. Neither the gate cases
nor the default case reaches that combination on its own.

Reads no database and opens no network: `_replacement` builds a dictionary from
an unsaved package and an unsaved run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_package_supply_chain_monitor.core import rollup as rollup_module
from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.models import PolicyRun
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.rollup import STAMP_COLUMNS
from conda_package_supply_chain_monitor.core.rollup import contributable_columns
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import Package
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.passes import A_DOMAIN_STATUS
from tests.passes import THE_COLUMN_DEFAULT
from tests.passes import rollup_with_a_domain_column

if TYPE_CHECKING:
    from django.db import models

#: A determinate verdict a pass produced, which the gate must pass through for a
#: resolved identity and replace for an unresolved one.
A_VERDICT: Final[str] = OutcomeState.OK.value

#: The policy version stamped on the composed row.
A_POLICY_VERSION: Final[str] = "cpm-fixture-policy-1"


@pytest.fixture
def a_rollup_with_a_domain_column(monkeypatch: pytest.MonkeyPatch) -> type[models.Model]:
    """Substitute a rollup that declares one contributable column.

    The model itself is `tests/passes.py`'s, so this module and
    `tests/unit/django_apps/test_policy_contribution.py` measure the same
    declaration: two synthetic rollups that could disagree about which column is
    contributable would look exactly like two passing modules.

    Args:
        monkeypatch: pytest's patcher, used to point `core/rollup.py` at this
            model where it names the real one. It is also the teardown: the
            substitution is undone when the case ends, so nothing here needs a
            `finally` of its own.

    Returns:
        The synthetic rollup model.

    """
    synthetic = rollup_with_a_domain_column()
    monkeypatch.setattr(rollup_module, "ROLLUP_MODEL", synthetic)
    assert contributable_columns() == frozenset({A_DOMAIN_STATUS}), (
        "the synthetic rollup must offer exactly the one column these cases are about"
    )
    return synthetic


def a_package(confidence: str) -> Package:
    """Build an unsaved package at a stated identity confidence.

    Args:
        confidence: How certain its identity is (`CPM-AD-4`).

    Returns:
        An unsaved `Package`. Unsaved because composition reads two attributes
        off it and writes no row, so a database would add nothing but time.

    """
    return Package(canonical_name="numpy", resolved_at=FIXED_INSTANT, confidence=confidence)


def composed(package: Package, contributed: dict[str, str]) -> dict[str, object]:
    """Compose one row the way the writer does.

    Args:
        package: The package the row is about.
        contributed: What the registered passes produced for it.

    Returns:
        The complete row, stamps included.

    """
    return rollup_module._replacement(  # noqa: SLF001 - the composition is this module's whole subject
        package,
        policy_run=PolicyRun(policy_version=A_POLICY_VERSION, evidence_cutoff=FIXED_INSTANT),
        evidence_cutoff=FIXED_INSTANT,
        computed_at=LATER_INSTANT,
        policy_versions={"a-domain": A_POLICY_VERSION},
        contributed=contributed,
    )


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_a_verified_packages_verdict_reaches_the_column_unchanged() -> None:
    """The ordinary path, and the anti-vacuity guard for the gated case below.

    A writer that wrote `unknown` into every column would satisfy the unmapped
    case perfectly, and only this one would notice.
    """
    row = composed(a_package(IdentityConfidence.VERIFIED), {A_DOMAIN_STATUS: A_VERDICT})

    assert row[A_DOMAIN_STATUS] == A_VERDICT
    assert row["confidence"] == IdentityConfidence.VERIFIED


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_an_unmapped_packages_gated_status_reads_unknown() -> None:
    """The acceptance criterion `CPM-AD-4` and `CPM-FR-5` share, at the point it happens.

    The row still exists and still carries every stamp -- the gate writes a value
    rather than suppressing a row -- and the domain status reads `unknown`
    because automation claims nothing about a package whose identity was never
    established.
    """
    row = composed(a_package(IdentityConfidence.UNMAPPED), {A_DOMAIN_STATUS: A_VERDICT})

    assert row[A_DOMAIN_STATUS] == OutcomeState.UNKNOWN.value
    assert row["confidence"] == IdentityConfidence.UNMAPPED
    assert row["computed_at"] == LATER_INSTANT


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_an_inventory_derived_packages_verdict_is_not_degraded() -> None:
    """The third row of the gate, asserted where the rollup actually applies it.

    `tests/unit/django_apps/test_confidence.py` proves the function; this proves
    the writer calls it with the package's own confidence rather than with a
    value it decided for itself.
    """
    row = composed(a_package(IdentityConfidence.INVENTORY_DERIVED), {A_DOMAIN_STATUS: A_VERDICT})

    assert row[A_DOMAIN_STATUS] == A_VERDICT
    assert row["confidence"] == IdentityConfidence.INVENTORY_DERIVED


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_a_column_nobody_contributed_is_written_as_its_default() -> None:
    """Full-row replace, which is only distinguishable from a merge here.

    A pass that has been withdrawn takes its verdict with it. A merge would leave
    the column holding a value computed by a run the row no longer names, which
    is the one thing a row carrying `policy_run` and `computed_at` promises cannot
    happen -- and every other case in this file would pass regardless.
    """
    row = composed(a_package(IdentityConfidence.VERIFIED), {})

    assert row[A_DOMAIN_STATUS] == THE_COLUMN_DEFAULT


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_an_unmapped_package_gets_the_gated_value_even_where_nobody_contributed() -> None:
    """The one combination the other four do not reach, and the bug that lived in it.

    Gating only *contributed* verdicts leaves the default path open, and the
    default path is not a neutral one: a field default is a claim about the
    package just as much as a pass's verdict is. The first `currency_status`
    declared `default=OutcomeState.OK` would have made every `unmapped` package's
    row read `ok` -- the exact claim `CPM-FR-5` forbids about a package whose
    identity was never established -- through the one path no pass touches and no
    contribution case would notice.

    The synthetic column's default is `not_applicable` precisely so this is
    visible: an empty-string default would be indistinguishable from "nothing was
    written", and the assertion would hold for the wrong reason. The default is
    determinate enough to be a claim, and the gate replaces it.
    """
    row = composed(a_package(IdentityConfidence.UNMAPPED), {})

    assert OutcomeState.UNKNOWN.value != THE_COLUMN_DEFAULT, (
        "the synthetic column's default must differ from the gated value, or this case cannot tell "
        "a gated default from an ungated one"
    )
    assert row[A_DOMAIN_STATUS] == OutcomeState.UNKNOWN.value


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_the_composed_row_covers_every_column_the_rollup_declares() -> None:
    """The writer sets the whole row, which is what makes the replace a replace.

    A field added to the rollup and forgotten by the writer would leave a column
    it never sets. `package` is deliberately absent: it is the key the row is
    matched on rather than part of what is replaced.
    """
    row = composed(a_package(IdentityConfidence.VERIFIED), {A_DOMAIN_STATUS: A_VERDICT})

    assert set(row) == (STAMP_COLUMNS | contributable_columns()) - {"package"}


def test_the_real_rollup_offers_nothing_yet_which_is_why_the_synthetic_one_exists() -> None:
    """The honest statement of what this module stands in for.

    If `PackageHealth` ever declares a contributable column, the cases above stop
    being the only place the gate is exercised -- and
    `tests/integration/django_apps/test_rollup.py` should assert it end to end
    instead. This is what says so.
    """
    assert contributable_columns() == frozenset()
    assert rollup_module.ROLLUP_MODEL is PackageHealth


def test_the_rollup_row_renders_before_it_is_saved() -> None:
    """A `__str__` that raised would break the two places a half-built row is rendered.

    An unsaved instance has no related object, so reading `self.package` raises
    `RelatedObjectDoesNotExist` -- in a debugger and in a traceback, which are
    exactly where a `__str__` is called on a half-built object. Read off
    `package_id` instead, on the same terms as `Feedstock.__str__`.
    """
    assert "no package" in str(PackageHealth())
    assert "not computed" in str(PackageHealth())
    assert LATER_INSTANT.isoformat() in str(PackageHealth(package_id=7, computed_at=LATER_INSTANT))
