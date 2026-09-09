"""Work type against real tables: the derivation end to end, the closed set, and the ordering.

`CPM-PRIORITY-S02` derives a recommended action from what the six domain passes
concluded. The derivation itself is pure and decided in
`tests/unit/django_apps/test_work_type_policy.py`; what is only true or false once a
run exists is here.

**AC 1's independence is proved as registration order.** The work-type pass runs
*before* the priority pass, so there is no priority row for this run when it
executes — it could not read one even if somebody added the code. That is asserted
against the live registry, and the two columns are asserted to disagree on a real
package, which is what "not coupled" means where it matters.

**AC 2's closed set is proved against a real backend.** `choices` is enforced by
neither `save()` nor a migration, so the requirement's "a value outside that set is
rejected" is a check constraint, and this is where it is driven.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction

from conda_sentinel.collectors.models import PyPIReleaseSnapshot
from conda_sentinel.collectors.models import SourceReleaseSnapshot
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.confidence import GATED_VALUE
from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.policy import registered_passes
from conda_sentinel.core.policy_run import execute_policy_run
from conda_sentinel.core.runs import RunState
from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.policies.models import A_WORK_TYPE_IS_ONE_OF_THE_CLOSED_SET
from conda_sentinel.policies.models import ONE_WORK_TYPE_ROW_PER_PACKAGE_PER_RUN
from conda_sentinel.policies.models import WORK_TYPE_ROW_NAMES_ITS_POLICY_VERSION
from conda_sentinel.policies.models import PackagePriority
from conda_sentinel.policies.models import PackageWorkType
from conda_sentinel.policies.outcomes import FILE_TRACKING_ISSUE
from conda_sentinel.policies.outcomes import PRIORITY_STATUS_UNKNOWN
from conda_sentinel.policies.outcomes import WORK_TYPE_UNKNOWN
from conda_sentinel.policies.outcomes import WORK_TYPES
from conda_sentinel.policies.priority import POLICY_NAME as PRIORITY_POLICY_NAME
from conda_sentinel.policies.work_type import POLICY_NAME
from conda_sentinel.policies.work_type import ROLLUP_COLUMN
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.passes import A_RECORDED_POLICY_VERSION

if TYPE_CHECKING:
    from datetime import datetime

#: The collector name the fixture collection run is recorded under.
A_COLLECTOR: Final[str] = "inventory"

#: A value the vocabulary does not offer, for the closed-set refusal.
A_VALUE_FROM_NOWHERE: Final[str] = "have_a_think_about_it"

#: How many rows the replay case expects. Named because `PLR2004` is right about a
#: bare number in an assertion.
TWO_ROWS: Final[int] = 2


def an_ended_collection_run(finished_at: datetime = FIXED_INSTANT) -> CollectionRun:
    """Record a collection run that has ended, which is what supplies the cut-off.

    Args:
        finished_at: When the run ended.

    Returns:
        The saved row.

    """
    return CollectionRun.objects.create(
        collector=A_COLLECTOR,
        started_at=FIXED_INSTANT,
        finished_at=finished_at,
        status=RunState.SUCCEEDED,
    )


def a_package(name: str = "numpy", *, confidence: str = IdentityConfidence.VERIFIED) -> Package:
    """Create one package with a resolved identity.

    Args:
        name: Its canonical name, which is unique.
        confidence: How certain its identity is.

    Returns:
        The saved row.

    """
    return Package.objects.create(canonical_name=name, resolved_at=FIXED_INSTANT, confidence=confidence)


def a_behind_package(package: Package) -> None:
    """Give one package the evidence the currency pass reads as `behind`.

    Two surfaces stating different versions, written as real evidence rather than as
    a hand-built derived row: the point of these cases is that the work-type pass
    reads what an *earlier pass* concluded in the same run.

    Args:
        package: The package to give evidence to.

    """
    SourceReleaseSnapshot.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        source="https://example.invalid/releases",
        state=OutcomeState.OK.value,
        latest_version="2.0.0",
        released_at=FIXED_INSTANT,
    )
    PyPIReleaseSnapshot.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        source="https://pypi.org/pypi/numpy/json",
        state=OutcomeState.OK.value,
        latest_version="1.0.0",
        released_at=FIXED_INSTANT,
    )


def a_policy_run(*, at: datetime = LATER_INSTANT) -> None:
    """Execute one policy run over the whole inventory.

    Args:
        at: The instant the run's clock answers.

    """
    execute_policy_run(policy_version=A_RECORDED_POLICY_VERSION, clock=FixedClock(instant=at))


def the_recommendation(package: Package) -> PackageWorkType:
    """Return the work-type row the latest run wrote for a package.

    Args:
        package: The package whose row is wanted.

    Returns:
        Its row, newest run first.

    """
    return PackageWorkType.objects.filter(package=package).order_by("-policy_run_id")[0]


def a_hand_built_row(**overrides: Any) -> PackageWorkType:
    """Write one work-type row directly, for the cases about what the database refuses.

    Args:
        **overrides: Columns to replace on an otherwise ordinary row.

    Returns:
        The saved row, where the database accepts it.

    """
    fields: dict[str, Any] = {
        "package": overrides.pop("package", None) or a_package("hand-built"),
        "policy_run": overrides.pop("policy_run", None)
        or PolicyRun.objects.create(
            policy_version=A_RECORDED_POLICY_VERSION,
            evidence_cutoff=FIXED_INSTANT,
            started_at=FIXED_INSTANT,
            finished_at=LATER_INSTANT,
            status=RunState.SUCCEEDED,
        ),
        "work_type": FILE_TRACKING_ISSUE,
        "detail": "because the test said so",
        "policy_version": A_RECORDED_POLICY_VERSION,
        "evidence_cutoff": FIXED_INSTANT,
    }
    fields.update(overrides)
    return PackageWorkType.objects.create(**fields)


# ---------------------------------------------------------------------------
# AC 1: independent of priority.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_work_type_pass_runs_before_the_priority_pass() -> None:
    """AC 1's independence, made structural by the registration order.

    A pass that runs first cannot read the other's rows for this run, whatever its
    code says -- there are none. Asserted against the live registry, which keeps
    *declaration* order precisely because a later pass may read an earlier one's
    rows.
    """
    order = [policy_pass.name for policy_pass in registered_passes()]

    assert order.index(POLICY_NAME) < order.index(PRIORITY_POLICY_NAME)


@pytest.mark.django_db
def test_a_package_with_no_bucket_still_gets_a_work_type() -> None:
    """AC 1 where it matters: the shipped priority rule set is empty, and work still computes.

    This is the case the requirement is actually about. Every package in this
    repository is `unknown` for priority -- PRD Open Question 8 -- so if the two were
    coupled at all, *nothing* would ever be recommended. A recommendation on a
    package with no bucket is the whole claim.
    """
    an_ended_collection_run()
    package = a_package()
    a_behind_package(package)

    a_policy_run()

    assert PackagePriority.objects.get(package=package).bucket == PRIORITY_STATUS_UNKNOWN
    assert the_recommendation(package).work_type == FILE_TRACKING_ISSUE


@pytest.mark.django_db
def test_the_two_columns_disagree_on_the_same_rollup_row() -> None:
    """The adjacency the requirement is written about, on the table a queue reads.

    A reader who inferred one column from the other would lose exactly this: a
    package with no priority bucket and a definite recommended action.
    """
    an_ended_collection_run()
    package = a_package()
    a_behind_package(package)

    a_policy_run()

    row = PackageHealth.objects.get(package=package)
    assert row.priority_status == PRIORITY_STATUS_UNKNOWN
    assert getattr(row, ROLLUP_COLUMN) == FILE_TRACKING_ISSUE
    assert row.priority_status != getattr(row, ROLLUP_COLUMN)


# ---------------------------------------------------------------------------
# The derivation, end to end.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_behind_package_is_recommended_a_tracking_issue_and_the_row_says_why() -> None:
    """The derivation reading a real earlier pass's verdict, not a hand-built row."""
    an_ended_collection_run()
    package = a_package()
    a_behind_package(package)

    a_policy_run()

    row = the_recommendation(package)
    assert row.work_type == FILE_TRACKING_ISSUE
    assert "behind" in row.detail
    assert row.policy_version == A_RECORDED_POLICY_VERSION
    assert row.evidence_cutoff == FIXED_INSTANT


@pytest.mark.django_db
def test_a_package_nothing_was_established_about_is_recommended_nothing() -> None:
    """`unknown`, and the row exists -- an absent row would read as never-evaluated."""
    an_ended_collection_run()
    package = a_package()

    a_policy_run()

    assert the_recommendation(package).work_type == WORK_TYPE_UNKNOWN


@pytest.mark.django_db
def test_the_work_type_reaches_the_rollup() -> None:
    """`CPM-AD-11`: the column a queue filters on, written by the rollup writer."""
    an_ended_collection_run()
    package = a_package()
    a_behind_package(package)

    a_policy_run()

    assert getattr(PackageHealth.objects.get(package=package), ROLLUP_COLUMN) == FILE_TRACKING_ISSUE


@pytest.mark.django_db
def test_an_unmapped_packages_work_type_is_replaced_by_the_gate() -> None:
    """`CPM-AD-4`, and the reason this pass reads no confidence of its own.

    The pass derives a recommendation without knowing anything about identity; the
    rollup writer is the one place that knows, and it replaces the value. The derived
    row keeps what the pass computed, which is what makes the two tables tell
    different, honest stories.
    """
    an_ended_collection_run()
    package = a_package("unmapped-one", confidence=IdentityConfidence.UNMAPPED)
    a_behind_package(package)

    a_policy_run()

    assert getattr(PackageHealth.objects.get(package=package), ROLLUP_COLUMN) == GATED_VALUE
    assert GATED_VALUE != FILE_TRACKING_ISSUE, "the gate must change the value, or this case asserts nothing"
    assert the_recommendation(package).work_type == FILE_TRACKING_ISSUE


# ---------------------------------------------------------------------------
# AC 2: what the database refuses.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_database_refuses_a_work_type_outside_the_closed_set() -> None:
    """AC 2 in as many words, and `choices` alone would not have been it.

    Django enforces `choices` on neither `save()` nor a migration, so this value
    reaches the column unchallenged without the check constraint -- which is why the
    requirement says *rejected* rather than *declared*.
    """
    assert A_VALUE_FROM_NOWHERE not in WORK_TYPES

    with pytest.raises(IntegrityError, match=A_WORK_TYPE_IS_ONE_OF_THE_CLOSED_SET), transaction.atomic():
        a_hand_built_row(work_type=A_VALUE_FROM_NOWHERE)


@pytest.mark.django_db
@pytest.mark.parametrize("work_type", sorted(WORK_TYPES), ids=str)
def test_the_database_accepts_every_value_the_closed_set_names(work_type: str) -> None:
    """The other direction, and it is what stops the constraint being too tight.

    A constraint that admitted only the values the shipped derivation reaches would
    refuse `already_tracked` and `resolve_identity` -- the two `CPM-FR-21` names and
    this product cannot yet reach -- and the day either signal exists the refusal
    would arrive as a database error rather than as a design decision.

    Args:
        work_type: One of the eight.

    """
    assert a_hand_built_row(package=a_package(f"accepts-{work_type}"), work_type=work_type).pk is not None


@pytest.mark.django_db
def test_the_database_refuses_a_row_that_cannot_say_which_version_produced_it() -> None:
    """`CPM-AD-8`: every derived row records the policy version that produced it."""
    with pytest.raises(IntegrityError, match=WORK_TYPE_ROW_NAMES_ITS_POLICY_VERSION), transaction.atomic():
        a_hand_built_row(policy_version="")


@pytest.mark.django_db
def test_the_database_refuses_a_second_row_for_one_package_in_one_run() -> None:
    """`CPM-AD-21`'s key. Matched on the columns, because SQLite names no constraint here."""
    package = a_package("twice")
    run = PolicyRun.objects.create(
        policy_version=A_RECORDED_POLICY_VERSION,
        evidence_cutoff=FIXED_INSTANT,
        started_at=FIXED_INSTANT,
        finished_at=LATER_INSTANT,
        status=RunState.SUCCEEDED,
    )
    a_hand_built_row(package=package, policy_run=run)

    with pytest.raises(IntegrityError, match="package_id"), transaction.atomic():
        a_hand_built_row(package=package, policy_run=run)

    declared = {constraint.name for constraint in PackageWorkType._meta.constraints}  # noqa: SLF001 - Django's API
    assert ONE_WORK_TYPE_ROW_PER_PACKAGE_PER_RUN in declared


@pytest.mark.django_db
def test_two_runs_over_one_cutoff_recommend_the_same_thing() -> None:
    """`CPM-FR-22`: re-running a version against a cut-off reproduces the answer."""
    an_ended_collection_run()
    package = a_package()
    a_behind_package(package)

    a_policy_run()
    a_policy_run(at=LATER_INSTANT)

    rows = list(PackageWorkType.objects.filter(package=package).order_by("policy_run_id"))
    assert len(rows) == TWO_ROWS
    assert rows[0].work_type == rows[1].work_type
    assert rows[0].detail == rows[1].detail
