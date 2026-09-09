"""Priority against real tables: the six reads, the explanation, the rollup and the gate.

`CPM-PRIORITY-S01` assigns a bucket from what the six earlier passes concluded, and
the reduction itself is pure and decided in
`tests/unit/django_apps/test_priority_policy.py`. What is only true or false once a
run exists is here: that the pass reads *this run's* six derived rows, that the
assignment explains itself on the row, that the bucket reaches the rollup through
`CPM-AD-4`'s gate, and that the database refuses a bucket that arrived without its
explanation.

**The shipped state is proved first, because it is what this repository ships.**
Every case that wants a bucket has to record a rule set to get one; the default
run, at the version the suite uses, puts every package in `unknown` and says so.

**This is where the real gating claim lives.**
`tests/integration/django_apps/test_rollup.py` asserts `priority_status` is gated,
and records that with an empty rule set the contributed value is already `unknown`
so the gate has nothing to replace. Here a rule set is recorded, an unmapped package
reaches a real bucket, and the gate is shown replacing it.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction

from conda_sentinel.collectors.models import InventorySnapshot
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.confidence import GATED_VALUE
from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.policy_run import execute_policy_run
from conda_sentinel.core.runs import RunState
from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.policies import parameters as parameters_module
from conda_sentinel.policies.models import A_BUCKET_EXPLAINS_ITSELF
from conda_sentinel.policies.models import A_SCORE_IS_IN_RANGE_OR_ABSENT
from conda_sentinel.policies.models import MAX_PRIORITY_SCORE
from conda_sentinel.policies.models import ONE_PRIORITY_ROW_PER_PACKAGE_PER_RUN
from conda_sentinel.policies.models import PRIORITY_ROW_NAMES_ITS_POLICY_VERSION
from conda_sentinel.policies.models import PackagePriority
from conda_sentinel.policies.outcomes import PRIORITY_BUCKETS
from conda_sentinel.policies.outcomes import PRIORITY_STATUS_UNKNOWN
from conda_sentinel.policies.parameters import forget_recorded_parameters
from conda_sentinel.policies.priority import NO_MATCH_DETAIL
from conda_sentinel.policies.priority import NO_RULE_SET_DETAIL
from conda_sentinel.policies.priority import ROLLUP_COLUMN
from conda_sentinel.policies.priority import ranking_order
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.passes import A_RECORDED_POLICY_VERSION

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from pathlib import Path

#: The collector name the fixture collection run is recorded under.
A_COLLECTOR: Final[str] = "inventory"

#: The bucket the recorded fixture rule set assigns, and what it says about itself.
A_BUCKET: Final[str] = "p1"
A_DESCRIPTION: Final[str] = "Behind on the authoritative surface"
A_REASON: Final[str] = "The currency pass reached behind for this package"

#: The verdict the fixture rule matches on, and the domain it matches it in.
A_DOMAIN: Final[str] = "currency_status"
A_VERDICT: Final[str] = "behind"

#: How many rows the replay case expects. Named because `PLR2004` is right about a
#: bare number in an assertion.
TWO_ROWS: Final[int] = 2


def _document(*, rules: str = "[]", weights: str = "{}") -> str:
    """Return a parameter file recording one version with these priority parameters.

    Args:
        rules: The `priority_rules` value, as TOML.
        weights: The `priority_score_weights` value, as TOML.

    Returns:
        The file text.

    """
    return textwrap.dedent(f"""
        [versions."{A_RECORDED_POLICY_VERSION}"]
        feedstock_inactivity_days = 180
        vulnerability_risk_order = ["critical", "high", "moderate", "low"]
        license_rules = []
        priority_rules = {rules}
        priority_score_weights = {weights}
        """).strip()


@pytest.fixture
def recorded_parameters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    """Point the loader at a file each case writes, and forget it afterwards.

    The loader memoizes on the path, so a case that wrote a file without clearing
    the cache would be read by the next one. Shaped after
    `tests/integration/django_apps/test_licence_policy.py`'s equivalent.

    Yields:
        A callable taking the file text and installing it.

    """
    written = tmp_path / "policy-parameters.toml"

    def install(text: str) -> None:
        written.write_text(text, encoding="utf-8")
        forget_recorded_parameters()

    monkeypatch.setattr(parameters_module, "parameters_file", lambda: written)
    install(_document())
    try:
        yield install
    finally:
        forget_recorded_parameters()


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


def an_observation(package: Package, **signals: int) -> InventorySnapshot:
    """Record one inventory observation carrying these usage signals.

    Args:
        package: The package observed.
        **signals: The counts to record. Any not named stay `NULL`, which is the
            state the score cases turn on.

    Returns:
        The saved row.

    """
    return InventorySnapshot.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        source_package_key=package.canonical_name,
        state=OutcomeState.OK.value,
        internal_component_count=signals.pop("internal_component_count", 1),
        internal_lob_count=signals.pop("internal_lob_count", 1),
        **signals,
    )


def a_policy_run(*, at: datetime = LATER_INSTANT) -> None:
    """Execute one policy run over the whole inventory.

    Args:
        at: The instant the run's clock answers.

    """
    execute_policy_run(policy_version=A_RECORDED_POLICY_VERSION, clock=FixedClock(instant=at))


def the_assignment(package: Package) -> PackagePriority:
    """Return the priority row the latest run wrote for a package.

    Args:
        package: The package whose row is wanted.

    Returns:
        Its row, newest run first.

    """
    return PackagePriority.objects.filter(package=package).order_by("-policy_run_id")[0]


def a_hand_built_row(**overrides: Any) -> PackagePriority:
    """Write one priority row directly, for the cases about what the database refuses.

    Args:
        **overrides: Columns to replace on an otherwise ordinary explained row.

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
        "bucket": A_BUCKET,
        "bucket_description": A_DESCRIPTION,
        "matched_rule": "rule 1",
        "reason": A_REASON,
        "score": None,
        "policy_version": A_RECORDED_POLICY_VERSION,
        "evidence_cutoff": FIXED_INSTANT,
        "detail": "",
    }
    fields.update(overrides)
    return PackagePriority.objects.create(**fields)


#: A rule set that assigns `p1` to a package the currency pass called `behind`.
A_RULE_SET: Final[str] = (
    f'[{{ bucket = "{A_BUCKET}", description = "{A_DESCRIPTION}", '
    f'reason = "{A_REASON}", when = {{ {A_DOMAIN} = "{A_VERDICT}" }} }}]'
)

#: A rule set nothing can match, for the "no rule matched" case. `not_applicable` is
#: a value the currency vocabulary offers and the currency pass never reaches for a
#: package with no evidence.
AN_UNMATCHABLE_RULE_SET: Final[str] = (
    f'[{{ bucket = "{A_BUCKET}", description = "{A_DESCRIPTION}", '
    f'reason = "{A_REASON}", when = {{ {A_DOMAIN} = "not_applicable" }} }}]'
)


# ---------------------------------------------------------------------------
# The shipped state.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.usefixtures("recorded_parameters")
def test_an_empty_rule_set_puts_every_package_in_no_bucket_and_says_so() -> None:
    """What this repository ships, end to end.

    Both halves asserted: the bucket is `unknown`, and it is **not** one of the ten.
    A rule engine that quietly defaulted to `p10` would satisfy every other case in
    this module while putting the whole inventory into a bucket nobody chose.
    """
    an_ended_collection_run()
    package = a_package()

    a_policy_run()

    row = the_assignment(package)
    assert row.bucket == PRIORITY_STATUS_UNKNOWN
    assert row.bucket not in PRIORITY_BUCKETS
    assert row.bucket_description == ""
    assert row.matched_rule == ""
    assert row.reason == ""
    assert NO_RULE_SET_DETAIL in row.detail


@pytest.mark.django_db
def test_a_version_predating_the_parameters_writes_a_row_rather_than_failing_the_run() -> None:
    """A historical version is a fact, not a misconfiguration.

    `policies/vulnerability.py` records the defect this guards against at length: a
    pass that raised for such a version failed every package, took the other passes'
    rows down with it and finalized the run `failed` -- a `CPM-FR-22` regression
    caused by registering a pass. The shipped file's oldest version records no
    priority parameters at all, so this drives exactly that.
    """
    an_ended_collection_run()
    package = a_package()

    execute_policy_run(policy_version="2026.09", clock=FixedClock(instant=LATER_INSTANT))

    row = the_assignment(package)
    assert row.bucket == PRIORITY_STATUS_UNKNOWN
    assert row.policy_version == "2026.09"
    assert PolicyRun.objects.order_by("-pk").first().status == RunState.SUCCEEDED.value


# ---------------------------------------------------------------------------
# AC 1 and AC 2: a bucket, and an assignment that explains itself.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_matching_rule_assigns_its_bucket_and_the_row_carries_the_whole_explanation(
    recorded_parameters: Any,
) -> None:
    """AC 2 end to end: the description, the rule and the reason travel with the bucket.

    The point of the story is that nobody has to open the rule set to know why a
    package is `P1`, so all three are asserted on the row rather than inferred from
    the parameters.

    Args:
        recorded_parameters: Installs the rule set this case needs.

    """
    recorded_parameters(_document(rules=A_RULE_SET))
    an_ended_collection_run()
    package = a_package()
    _a_behind_package(package)

    a_policy_run()

    row = the_assignment(package)
    assert row.bucket == A_BUCKET
    assert row.bucket_description == A_DESCRIPTION
    assert row.reason == A_REASON
    assert row.matched_rule == "rule 1"


@pytest.mark.django_db
def test_a_rule_set_that_matches_nothing_leaves_the_package_unbucketed(recorded_parameters: Any) -> None:
    """Distinct from "no rule set", and `detail` is what tells them apart.

    Args:
        recorded_parameters: Installs the rule set this case needs.

    """
    recorded_parameters(_document(rules=AN_UNMATCHABLE_RULE_SET))
    an_ended_collection_run()
    package = a_package()

    a_policy_run()

    row = the_assignment(package)
    assert row.bucket == PRIORITY_STATUS_UNKNOWN
    assert NO_MATCH_DETAIL in row.detail
    assert NO_RULE_SET_DETAIL not in row.detail


@pytest.mark.django_db
def test_the_bucket_reaches_the_rollup(recorded_parameters: Any) -> None:
    """AC 1's bucket on the table a queue actually filters (`CPM-AD-11`).

    Args:
        recorded_parameters: Installs the rule set this case needs.

    """
    recorded_parameters(_document(rules=A_RULE_SET))
    an_ended_collection_run()
    package = a_package()
    _a_behind_package(package)

    a_policy_run()

    assert getattr(PackageHealth.objects.get(package=package), ROLLUP_COLUMN) == A_BUCKET


@pytest.mark.django_db
def test_an_unmapped_packages_bucket_is_replaced_by_the_gate(recorded_parameters: Any) -> None:
    """`CPM-AD-4` on a column where the gate has something to change.

    `tests/integration/django_apps/test_rollup.py` asserts this column is gated and
    records that the shipped empty rule set makes the contributed value `unknown`
    already, so the gate there replaces nothing. This is the other half: a recorded
    rule set, a real bucket, and the gate replacing it. The derived row keeps the
    bucket the pass computed -- the gate is the rollup writer's and not the pass's.

    Args:
        recorded_parameters: Installs the rule set this case needs.

    """
    recorded_parameters(_document(rules=A_RULE_SET))
    an_ended_collection_run()
    package = a_package("unmapped-one", confidence=IdentityConfidence.UNMAPPED)
    _a_behind_package(package)

    a_policy_run()

    assert getattr(PackageHealth.objects.get(package=package), ROLLUP_COLUMN) == GATED_VALUE
    assert GATED_VALUE != A_BUCKET, "the gate must change the value, or this case asserts nothing"
    assert the_assignment(package).bucket == A_BUCKET


# ---------------------------------------------------------------------------
# The score.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_recorded_score_function_scores_an_observed_package(recorded_parameters: Any) -> None:
    """AC 1's 1-100 score, computed from the signals the inventory observed.

    Args:
        recorded_parameters: Installs the score function this case needs.

    """
    recorded_parameters(_document(weights="{ internal_component_count = 1 }"))
    an_ended_collection_run()
    package = a_package()
    an_observation(package, internal_component_count=1_000)

    a_policy_run()

    assert the_assignment(package).score == MAX_PRIORITY_SCORE


@pytest.mark.django_db
def test_a_weighted_signal_the_inventory_left_blank_produces_no_score(recorded_parameters: Any) -> None:
    """Blank means missing and is never invented, so there is no score rather than a zero.

    `apps` is nullable and this observation records none, which is the ordinary state
    of a hand-authored watchlist.

    Args:
        recorded_parameters: Installs the score function this case needs.

    """
    recorded_parameters(_document(weights="{ apps = 1 }"))
    an_ended_collection_run()
    package = a_package()
    an_observation(package)

    a_policy_run()

    row = the_assignment(package)
    assert row.score is None
    assert "apps" in row.detail


@pytest.mark.django_db
@pytest.mark.usefixtures("recorded_parameters")
def test_a_package_the_inventory_never_observed_gets_no_score() -> None:
    """An absence of an observation is not a package with no usage."""
    an_ended_collection_run()
    package = a_package()

    a_policy_run()

    assert the_assignment(package).score is None


# ---------------------------------------------------------------------------
# Rank, and what the database refuses.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.usefixtures("recorded_parameters")
def test_the_derived_ranking_is_a_total_order_over_a_runs_assignments() -> None:
    """AC 1's rank, derived rather than stored, and stable because it is total.

    Two packages with the same bucket and the same score still have an order,
    because the package key is the third term. Asserted as the query actually
    executing in that order rather than as a tuple of field names, which the unit
    tier already pins.
    """
    an_ended_collection_run()
    packages = [a_package("aaa"), a_package("bbb")]

    a_policy_run()

    ranked = list(PackagePriority.objects.order_by(*ranking_order()).values_list("package_id", flat=True))
    assert ranked == sorted(package.pk for package in packages)


@pytest.mark.django_db
def test_the_database_refuses_a_bucket_that_arrives_without_its_explanation() -> None:
    """AC 2 as a schema rule, from every side an explanation can go missing."""
    for blank in ("bucket_description", "matched_rule", "reason"):
        with pytest.raises(IntegrityError, match=A_BUCKET_EXPLAINS_ITSELF), transaction.atomic():
            a_hand_built_row(**{blank: ""})


@pytest.mark.django_db
def test_the_database_refuses_an_explanation_on_a_row_that_names_no_bucket() -> None:
    """The other half of the biconditional: a rule's words on a package no rule matched."""
    with pytest.raises(IntegrityError, match=A_BUCKET_EXPLAINS_ITSELF), transaction.atomic():
        a_hand_built_row(bucket=PRIORITY_STATUS_UNKNOWN)


@pytest.mark.django_db
@pytest.mark.parametrize("score", [0, MAX_PRIORITY_SCORE + 1], ids=["zero", "past-the-top"])
def test_the_database_refuses_a_score_outside_the_stated_range(score: int) -> None:
    """`CPM-FR-20` says 1-100, and zero is the value a score from missing signals lands on.

    Args:
        score: The out-of-range value.

    """
    with pytest.raises(IntegrityError, match=A_SCORE_IS_IN_RANGE_OR_ABSENT), transaction.atomic():
        a_hand_built_row(score=score)


@pytest.mark.django_db
def test_the_database_refuses_a_row_that_cannot_say_which_version_produced_it() -> None:
    """`CPM-AD-8`: every derived row records the policy version that produced it."""
    with pytest.raises(IntegrityError, match=PRIORITY_ROW_NAMES_ITS_POLICY_VERSION), transaction.atomic():
        a_hand_built_row(policy_version="")


@pytest.mark.django_db
def test_the_database_refuses_a_second_row_for_one_package_in_one_run() -> None:
    """`CPM-AD-21`'s key.

    Matched on the columns rather than the constraint's name: SQLite reports a
    unique violation by the columns it was declared over and never by the name, so a
    case matching the name would pass against PostgreSQL and fail here. The name is
    asserted against the model instead.
    """
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

    declared = {constraint.name for constraint in PackagePriority._meta.constraints}  # noqa: SLF001 - Django's API
    assert ONE_PRIORITY_ROW_PER_PACKAGE_PER_RUN in declared


@pytest.mark.django_db
@pytest.mark.usefixtures("recorded_parameters")
def test_two_runs_over_one_cutoff_produce_identical_assignments() -> None:
    """`CPM-FR-22`: re-running a version against a cut-off reproduces the answer."""
    an_ended_collection_run()
    package = a_package()

    a_policy_run()
    a_policy_run(at=LATER_INSTANT)

    rows = list(PackagePriority.objects.filter(package=package).order_by("policy_run_id"))
    assert len(rows) == TWO_ROWS
    assert rows[0].bucket == rows[1].bucket
    assert rows[0].score == rows[1].score
    assert rows[0].detail == rows[1].detail


def _a_behind_package(package: Package) -> None:
    """Give one package the evidence that makes the currency pass reach `behind`.

    Two surfaces stating different versions is what `CPM-CURRENCY-S06` reads as
    behind, which is the verdict the fixture rule matches on. Written through the
    real evidence tables rather than by writing a `PackageCurrency` row directly:
    the point of these cases is that the priority pass reads what an *earlier pass*
    concluded in the same run, and a hand-written derived row would skip the pass
    whose output is under test.

    Args:
        package: The package to give evidence to.

    """
    from conda_sentinel.collectors.models import PyPIReleaseSnapshot  # noqa: PLC0415 - only these cases need it
    from conda_sentinel.collectors.models import SourceReleaseSnapshot  # noqa: PLC0415 - only these cases need it

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
