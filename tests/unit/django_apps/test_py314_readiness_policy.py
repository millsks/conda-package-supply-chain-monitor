"""What the readiness reduction concludes, and what keeps proof and inference apart in it.

`CPM-PY314-S03` is one question -- given what a project *claimed* and what a build
*did*, is this package ready, and which of the two says so -- and almost all of it
is a pure function of two rows and an instant. That is what this module measures.
What needs a run -- the rows, the constraints, the pass inside a policy run, the
staleness read against a registered collector -- is in
`tests/integration/django_apps/test_py314_readiness_policy.py`.

**The case this module exists for is the collision that never happens.** Two
collectors spent two stories keeping inference and proof in separate tables with
separate vocabularies, and this pass is the first code that reads both. The
determinate values of all three vocabularies are compared as sets here, so a
rename on **any** of the three that made proof and inference share a spelling
fails a case rather than quietly satisfying `CPM-FR-19`'s letter.

**The second is that no absence reaches a verdict.** Every way this pass can fail
to establish something -- no evidence, evidence that established nothing, a failed
look, an absent package, stale evidence, evidence about another series -- has a
case asserting `unknown` **and** asserting it is not `inferred_not_ready` or
`verified_not_ready`. The second half deliberately: a vocabulary rename that made
`unknown` and a negative the same string would satisfy the first alone.

No database, no network: every evidence row here is an unsaved model instance and
nothing is queried.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest

from conda_sentinel.collectors import py314_verification
from conda_sentinel.collectors import python_readiness
from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.models import PythonVerificationResult
from conda_sentinel.collectors.outcomes import INFERRED_COMPATIBLE
from conda_sentinel.collectors.outcomes import INFERRED_INCOMPATIBLE
from conda_sentinel.collectors.outcomes import READINESS_ERROR
from conda_sentinel.collectors.outcomes import READINESS_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import READINESS_NOT_FOUND
from conda_sentinel.collectors.outcomes import READINESS_UNKNOWN
from conda_sentinel.collectors.outcomes import VERIFICATION_ERROR
from conda_sentinel.collectors.outcomes import VERIFICATION_FAILED
from conda_sentinel.collectors.outcomes import VERIFICATION_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import VERIFICATION_NOT_FOUND
from conda_sentinel.collectors.outcomes import VERIFICATION_UNKNOWN
from conda_sentinel.collectors.outcomes import VERIFIED_COMPATIBLE
from conda_sentinel.collectors.outcomes import PythonReadinessOutcome
from conda_sentinel.collectors.outcomes import PythonVerificationOutcome
from conda_sentinel.collectors.specifiers import series_of
from conda_sentinel.policies.models import PackagePythonReadiness
from conda_sentinel.policies.outcomes import EVIDENCE_INFERRED
from conda_sentinel.policies.outcomes import EVIDENCE_NONE
from conda_sentinel.policies.outcomes import EVIDENCE_TYPE_LENGTH
from conda_sentinel.policies.outcomes import EVIDENCE_VERIFIED
from conda_sentinel.policies.outcomes import INFERRED_NOT_READY
from conda_sentinel.policies.outcomes import INFERRED_READY
from conda_sentinel.policies.outcomes import PY314_DECIDED_VERDICTS
from conda_sentinel.policies.outcomes import PY314_INFERRED_VERDICTS
from conda_sentinel.policies.outcomes import PY314_READINESS_ERROR
from conda_sentinel.policies.outcomes import PY314_READINESS_NOT_APPLICABLE
from conda_sentinel.policies.outcomes import PY314_READINESS_NOT_FOUND
from conda_sentinel.policies.outcomes import PY314_READINESS_STATE_LENGTH
from conda_sentinel.policies.outcomes import PY314_READINESS_UNKNOWN
from conda_sentinel.policies.outcomes import PY314_VERIFIED_VERDICTS
from conda_sentinel.policies.outcomes import VERIFIED_NOT_READY
from conda_sentinel.policies.outcomes import VERIFIED_READY
from conda_sentinel.policies.outcomes import PackagePythonReadinessOutcome
from conda_sentinel.policies.outcomes import ReadinessEvidence
from conda_sentinel.policies.py314_readiness import AGREEMENT_DETAIL
from conda_sentinel.policies.py314_readiness import ASSESSED_SERIES
from conda_sentinel.policies.py314_readiness import DISAGREEMENT_DETAIL
from conda_sentinel.policies.py314_readiness import INAPPLICABLE_DETAIL
from conda_sentinel.policies.py314_readiness import NOTHING_ESTABLISHED_DETAIL
from conda_sentinel.policies.py314_readiness import NOTHING_OBSERVED_DETAIL
from conda_sentinel.policies.py314_readiness import POLICY_NAME
from conda_sentinel.policies.py314_readiness import STALE_EVIDENCE_DETAIL
from conda_sentinel.policies.py314_readiness import Py314ReadinessPass
from conda_sentinel.policies.py314_readiness import Py314ReadinessPolicyError
from conda_sentinel.policies.py314_readiness import evidence_is_stale
from conda_sentinel.policies.py314_readiness import freshness_target
from conda_sentinel.policies.py314_readiness import inferred_reading
from conda_sentinel.policies.py314_readiness import readiness_of
from conda_sentinel.policies.py314_readiness import verified_reading
from tests.clocks import FIXED_INSTANT

if TYPE_CHECKING:
    from datetime import datetime

#: A naive instant, on purpose: it is the subject of the refusal cases.
A_NAIVE_INSTANT: Final[datetime] = FIXED_INSTANT.replace(tzinfo=None)

#: A series this product does not assess, for the case that proves the filter is a
#: filter rather than a comparison.
ANOTHER_SERIES: Final[str] = "3.15"

#: How many determinate verdicts this vocabulary carries, and how many values in
#: total. Named because `PLR2004` is right about a bare number in an assertion.
FOUR_VERDICTS: Final[int] = 4
SIX_VALUES: Final[int] = 6
THREE_EVIDENCE_TYPES: Final[int] = 3


def an_assessment(state: str = INFERRED_COMPATIBLE, *, series: str = ASSESSED_SERIES) -> PythonReadinessAssessment:
    """Return an unsaved static assessment.

    Args:
        state: The collector verdict the row carries.
        series: The Python series it is about.

    Returns:
        The unsaved row. Nothing here is saved: the reduction is a pure function of
        the row's columns.

    """
    return PythonReadinessAssessment(observed_at=FIXED_INSTANT, state=state, python_series=series)


def a_verification(state: str = VERIFIED_COMPATIBLE, *, series: str = ASSESSED_SERIES) -> PythonVerificationResult:
    """Return an unsaved verification result.

    Args:
        state: The collector verdict the row carries.
        series: The Python series it is about.

    Returns:
        The unsaved row.

    """
    return PythonVerificationResult(observed_at=FIXED_INSTANT, state=state, python_series=series)


# ---------------------------------------------------------------------------
# AC 1 and AC 2: the two evidence kinds cannot collide.
# ---------------------------------------------------------------------------


def test_no_derived_verdict_is_spelled_like_any_collector_verdict() -> None:
    """Three vocabularies, and none of them shares a determinate spelling with another.

    `collectors/outcomes.py` says what the *evidence* found; this module says what
    the *product concludes* (`CPM-AD-8`). Compared as sets rather than one spelling
    at a time, because what would break `CPM-FR-19` is a collision, and a collision
    introduced by renaming any of the three is what a per-value assertion misses.
    """
    inferred_evidence = {INFERRED_COMPATIBLE, INFERRED_INCOMPATIBLE}
    verified_evidence = {VERIFIED_COMPATIBLE, VERIFICATION_FAILED}
    verdicts = set(PY314_DECIDED_VERDICTS)

    assert verdicts.isdisjoint(inferred_evidence)
    assert verdicts.isdisjoint(verified_evidence)


def test_every_determinate_verdict_names_the_evidence_type_that_produced_it() -> None:
    """`CPM-FR-19`'s AC 1 in the value itself, which is what survives a projection.

    `CPM-AD-24` renders a status verbatim, so a surface showing this column alone
    must still be unable to mistake proof for inference. Asserted as a prefix rule
    over the whole vocabulary rather than four spellings, so a fifth verdict added
    later without a prefix fails here.
    """
    assert all(verdict.startswith("verified_") for verdict in PY314_VERIFIED_VERDICTS)
    assert all(verdict.startswith("inferred_") for verdict in PY314_INFERRED_VERDICTS)
    assert set(PY314_DECIDED_VERDICTS) == set(PY314_VERIFIED_VERDICTS) | set(PY314_INFERRED_VERDICTS)


def test_no_verdict_is_a_bare_readiness_word() -> None:
    """A bare `ready` is the one spelling this story exists to keep out of the column."""
    bare = {"ready", "not_ready", "ok", "compatible"}

    assert bare & set(PackagePythonReadinessOutcome.values) == set()


def test_the_vocabulary_carries_cores_four_sentinels_and_exactly_four_verdicts() -> None:
    """Six values, and a fifth verdict appearing without a case is what the count catches."""
    assert set(PackagePythonReadinessOutcome.values) == {
        VERIFIED_READY,
        VERIFIED_NOT_READY,
        INFERRED_READY,
        INFERRED_NOT_READY,
        PY314_READINESS_UNKNOWN,
        PY314_READINESS_ERROR,
        PY314_READINESS_NOT_FOUND,
        PY314_READINESS_NOT_APPLICABLE,
    }
    assert len(PY314_DECIDED_VERDICTS) == FOUR_VERDICTS


def test_the_evidence_type_vocabulary_holds_three_values_and_none_of_them_is_null() -> None:
    """`none` is a value, because a nullable column cannot tell "no evidence" from "never written"."""
    assert set(ReadinessEvidence.values) == {EVIDENCE_VERIFIED, EVIDENCE_INFERRED, EVIDENCE_NONE}
    assert len(ReadinessEvidence.values) == THREE_EVIDENCE_TYPES


@pytest.mark.parametrize(
    ("column", "values", "width"),
    [
        ("readiness", PackagePythonReadinessOutcome.values, PY314_READINESS_STATE_LENGTH),
        ("evidence_type", ReadinessEvidence.values, EVIDENCE_TYPE_LENGTH),
    ],
    ids=["readiness", "evidence_type"],
)
def test_each_column_is_wide_enough_for_every_value_it_offers(column: str, values: list[str], width: int) -> None:
    """A column narrower than its own choices refuses an honest row on PostgreSQL and stores it on SQLite.

    Args:
        column: The column being measured.
        values: Every value its vocabulary offers.
        width: The declared width.

    """
    declared = PackagePythonReadiness._meta.get_field(column).max_length  # noqa: SLF001 - Django's API

    assert declared == width
    assert max(len(value) for value in values) <= width


def test_this_pass_judges_the_series_both_collectors_assess() -> None:
    """Restated in three places, reconciled here, and nothing else would compare them.

    A pass quietly judging a series neither collector writes evidence about would
    make every package read `unknown` with every gate in the repository green.
    """
    assert series_of(python_readiness.PYTHON_SERIES) == ASSESSED_SERIES
    assert series_of(py314_verification.PYTHON_SERIES) == ASSESSED_SERIES


# ---------------------------------------------------------------------------
# The per-table readings.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (VERIFIED_COMPATIBLE, VERIFIED_READY),
        (VERIFICATION_FAILED, VERIFIED_NOT_READY),
        (VERIFICATION_UNKNOWN, ""),
        (VERIFICATION_ERROR, ""),
        (VERIFICATION_NOT_FOUND, ""),
    ],
    ids=str,
)
def test_a_verification_supports_one_verdict_or_none(state: str, expected: str) -> None:
    """Every value the verification vocabulary offers, and what it supports.

    Parametrized over the vocabulary's own members rather than a list written here,
    so a determinate value added to that vocabulary later fails this case rather
    than silently reading as "established nothing".

    Args:
        state: The collector verdict.
        expected: The derived verdict it supports, or the empty string.

    """
    assert verified_reading(a_verification(state)) == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (INFERRED_COMPATIBLE, INFERRED_READY),
        (INFERRED_INCOMPATIBLE, INFERRED_NOT_READY),
        (READINESS_UNKNOWN, ""),
        (READINESS_ERROR, ""),
        (READINESS_NOT_FOUND, ""),
    ],
    ids=str,
)
def test_an_assessment_supports_one_verdict_or_none(state: str, expected: str) -> None:
    """The same sweep over the static vocabulary.

    Args:
        state: The collector verdict.
        expected: The derived verdict it supports, or the empty string.

    """
    assert inferred_reading(an_assessment(state)) == expected


def test_every_determinate_collector_value_has_a_reading() -> None:
    """The anti-vacuity half: the two sweeps above cover both vocabularies completely.

    Without this, a determinate value added to either collector vocabulary would
    fall through to "established nothing" and no case above would notice, because
    neither is parametrized over the vocabulary itself.
    """
    verified = {state for state in PythonVerificationOutcome.values if verified_reading(a_verification(state))}
    inferred = {state for state in PythonReadinessOutcome.values if inferred_reading(an_assessment(state))}

    assert verified == {VERIFIED_COMPATIBLE, VERIFICATION_FAILED}
    assert inferred == {INFERRED_COMPATIBLE, INFERRED_INCOMPATIBLE}


# ---------------------------------------------------------------------------
# The reduction.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "verdict"),
    [(VERIFIED_COMPATIBLE, VERIFIED_READY), (VERIFICATION_FAILED, VERIFIED_NOT_READY)],
    ids=["built", "did-not-build"],
)
def test_a_verification_alone_decides_and_cites_itself(state: str, verdict: str) -> None:
    """AC 1: a verdict, and the evidence type that produced it.

    Args:
        state: The collector verdict.
        verdict: The derived verdict.

    """
    verification = a_verification(state)

    readiness = readiness_of(None, verification, cutoff=FIXED_INSTANT)

    assert readiness.verdict == verdict
    assert readiness.evidence_type == EVIDENCE_VERIFIED
    assert readiness.verification is verification
    assert readiness.assessment is None


@pytest.mark.parametrize(
    ("state", "verdict"),
    [(INFERRED_COMPATIBLE, INFERRED_READY), (INFERRED_INCOMPATIBLE, INFERRED_NOT_READY)],
    ids=["admits", "excludes"],
)
def test_an_assessment_alone_decides_and_says_it_is_an_inference(state: str, verdict: str) -> None:
    """The other half of AC 1, and the value says `inferred` without reading the column.

    Args:
        state: The collector verdict.
        verdict: The derived verdict.

    """
    assessment = an_assessment(state)

    readiness = readiness_of(assessment, None, cutoff=FIXED_INSTANT)

    assert readiness.verdict == verdict
    assert readiness.evidence_type == EVIDENCE_INFERRED
    assert readiness.assessment is assessment
    assert readiness.verification is None


def test_when_both_agree_the_verdict_rests_on_the_build_and_cites_both() -> None:
    """AC 2: the distinction survives, and so does the evidence it was drawn from.

    The assessment is cited on a *verified* row deliberately. Discarding it would
    satisfy every assertion about the verdict and would lose the fact that both
    kinds of evidence existed, which is the thing AC 2 is about.
    """
    assessment = an_assessment(INFERRED_COMPATIBLE)
    verification = a_verification(VERIFIED_COMPATIBLE)

    readiness = readiness_of(assessment, verification, cutoff=FIXED_INSTANT)

    assert readiness.verdict == VERIFIED_READY
    assert readiness.evidence_type == EVIDENCE_VERIFIED
    assert readiness.assessment is assessment
    assert readiness.verification is verification
    assert readiness.detail == AGREEMENT_DETAIL


def test_when_both_disagree_the_build_wins_and_the_claim_is_kept_beside_it() -> None:
    """AC 2's harder half: proof outranks inference and the inference is not deleted.

    Deliberately not `unknown`. `CPM-PY314-S01` records `unknown` when its own two
    *static* signals disagree, because neither is ranked above the other there.
    Here they are not peers: one of them is a build that ran.
    """
    assessment = an_assessment(INFERRED_COMPATIBLE)
    verification = a_verification(VERIFICATION_FAILED)

    readiness = readiness_of(assessment, verification, cutoff=FIXED_INSTANT)

    assert readiness.verdict == VERIFIED_NOT_READY
    assert readiness.verdict != PY314_READINESS_UNKNOWN
    assert readiness.evidence_type == EVIDENCE_VERIFIED
    assert readiness.assessment is assessment
    assert readiness.detail == DISAGREEMENT_DETAIL


def test_a_verification_that_established_nothing_falls_through_to_the_assessment() -> None:
    """An `unknown` verification is not a verification, so the inference still decides.

    The row still cites the verification, so a reader can see a build was attempted
    and told them nothing.
    """
    assessment = an_assessment(INFERRED_COMPATIBLE)
    verification = a_verification(VERIFICATION_UNKNOWN)

    readiness = readiness_of(assessment, verification, cutoff=FIXED_INSTANT)

    assert readiness.verdict == INFERRED_READY
    assert readiness.evidence_type == EVIDENCE_INFERRED
    assert readiness.verification is verification


def test_a_verified_verdict_standing_alone_says_nothing_about_an_inference() -> None:
    """No agreement note where there was no inference to agree with.

    The value already says what it rests on, so a sentence claiming agreement with
    evidence that does not exist would be the row inventing a second source.
    """
    readiness = readiness_of(None, a_verification(VERIFIED_COMPATIBLE), cutoff=FIXED_INSTANT)

    assert readiness.detail == ""


# ---------------------------------------------------------------------------
# No absence reaches a verdict.
# ---------------------------------------------------------------------------


def test_a_package_nobody_has_looked_at_is_unknown_and_never_a_negative() -> None:
    """The ordinary state of most of an inventory, and the row says so in words."""
    readiness = readiness_of(None, None, cutoff=FIXED_INSTANT)

    assert readiness.verdict == PY314_READINESS_UNKNOWN
    assert readiness.verdict not in PY314_DECIDED_VERDICTS
    assert readiness.evidence_type == EVIDENCE_NONE
    assert readiness.detail == NOTHING_OBSERVED_DETAIL


@pytest.mark.parametrize(
    ("assessment_state", "verification_state"),
    [
        (READINESS_UNKNOWN, None),
        (READINESS_ERROR, None),
        (READINESS_NOT_FOUND, None),
        (None, VERIFICATION_UNKNOWN),
        (None, VERIFICATION_ERROR),
        (None, VERIFICATION_NOT_FOUND),
        (READINESS_UNKNOWN, VERIFICATION_ERROR),
    ],
    ids=["a-unknown", "a-error", "a-not-found", "v-unknown", "v-error", "v-not-found", "both-establish-nothing"],
)
def test_evidence_that_established_nothing_is_unknown_and_never_a_negative(
    assessment_state: str | None,
    verification_state: str | None,
) -> None:
    """Every way evidence can exist and say nothing, swept.

    The second assertion is the load-bearing one: a vocabulary rename that made
    `unknown` and a negative the same string would satisfy the first alone.

    Args:
        assessment_state: The static verdict, or `None` for no assessment.
        verification_state: The verified verdict, or `None` for no verification.

    """
    readiness = readiness_of(
        None if assessment_state is None else an_assessment(assessment_state),
        None if verification_state is None else a_verification(verification_state),
        cutoff=FIXED_INSTANT,
    )

    assert readiness.verdict == PY314_READINESS_UNKNOWN
    assert readiness.verdict not in {INFERRED_NOT_READY, VERIFIED_NOT_READY}
    assert readiness.evidence_type == EVIDENCE_NONE
    assert readiness.detail == NOTHING_ESTABLISHED_DETAIL


@pytest.mark.parametrize(
    ("assessment_state", "verification_state"),
    [(READINESS_NOT_APPLICABLE, None), (None, VERIFICATION_NOT_APPLICABLE)],
    ids=["from-the-assessment", "from-the-verification"],
)
def test_identity_that_established_no_ecosystem_reaches_not_applicable_from_either_table(
    assessment_state: str | None,
    verification_state: str | None,
) -> None:
    """The one path to `not_applicable`, inherited whole from `CPM-PY314-S01`.

    Reachable from either evidence table because either collector may be the one
    that ran: both write the state only where identity established it.

    Args:
        assessment_state: The static verdict, or `None`.
        verification_state: The verified verdict, or `None`.

    """
    readiness = readiness_of(
        None if assessment_state is None else an_assessment(assessment_state),
        None if verification_state is None else a_verification(verification_state),
        cutoff=FIXED_INSTANT,
    )

    assert readiness.verdict == PY314_READINESS_NOT_APPLICABLE
    assert readiness.evidence_type == EVIDENCE_NONE
    assert readiness.detail == INAPPLICABLE_DETAIL


def test_inapplicability_outranks_a_determinate_verdict_beside_it() -> None:
    """The branch order is the rule, and this is the one place it can be observed.

    Identity establishing that the question does not apply outranks evidence about
    it: a package with no release ecosystem has nothing to be ready *for*, so a
    verdict drawn from a stray row beside it would be an answer to a question this
    product has already established it is not asking.
    """
    readiness = readiness_of(
        an_assessment(READINESS_NOT_APPLICABLE),
        a_verification(VERIFIED_COMPATIBLE),
        cutoff=FIXED_INSTANT,
    )

    assert readiness.verdict == PY314_READINESS_NOT_APPLICABLE


# ---------------------------------------------------------------------------
# The pass's declarations and its one refusal.
# ---------------------------------------------------------------------------


def test_the_pass_declares_its_name_its_table_and_no_rollup_column() -> None:
    """`contributes` is empty: `CPM-AD-21` gives the rollup to `CPM-EP-PRIORITY`."""
    assert Py314ReadinessPass.name == POLICY_NAME
    assert Py314ReadinessPass.derived_model is PackagePythonReadiness
    assert Py314ReadinessPass.contributes == ()


def test_the_pass_name_does_not_collide_with_the_remediation_readiness_domain() -> None:
    """Two domains in this component talk about readiness, and the names say which.

    A bare `readiness` here would make the rollup's per-domain version map, and
    every refusal message, ambiguous between two passes.
    """
    assert POLICY_NAME == "py314-readiness"
    assert POLICY_NAME != "readiness"


def test_the_pass_overrides_no_prepare_because_it_reads_no_parameter() -> None:
    """The shape that says "this pass has no run-wide precondition".

    Asserted rather than assumed: a `prepare` added later that established a
    parameter would be a run-wide refusal nobody argued for, and the base's default
    is what says there is none.
    """
    assert "prepare" not in vars(Py314ReadinessPass)


@pytest.mark.parametrize(
    "call",
    [
        lambda: readiness_of(None, None, cutoff=A_NAIVE_INSTANT),
        lambda: Py314ReadinessPass().evaluate(None, policy_run=None, evidence_cutoff=A_NAIVE_INSTANT),  # type: ignore[arg-type]
    ],
    ids=["the-reduction", "the-pass"],
)
def test_a_naive_cutoff_is_refused_before_anything_is_read(call: Any) -> None:
    """The one condition worth a raise, and it is refused before any query.

    `core/policy_run.py` wraps all six passes for one package in one transaction, so
    raising costs that package its other five domains' rows. A naive cut-off earns
    it: it is a caller defect rather than a fact about the package, and every
    comparison below it would silently be against an aware instant.

    Args:
        call: The entry point being refused.

    """
    with pytest.raises(Py314ReadinessPolicyError, match="carries no timezone"):
        call()


def test_stale_evidence_is_measured_from_the_cutoff_and_withholds_the_verdict() -> None:
    """`CPM-FR-38`: stale never displays as clean, and the reason is on the row.

    Driven through the real registry, so the target is the one
    `PythonReadinessCollector` declares rather than a number written here. The
    cut-off is moved far past the observation instead of the observation being
    moved, because staleness is measured from the cut-off and a case that moved the
    row would be asserting about a clock.
    """
    long_after = FIXED_INSTANT + timedelta(days=365 * 10)

    readiness = readiness_of(an_assessment(INFERRED_COMPATIBLE), None, cutoff=long_after)

    assert readiness.verdict == PY314_READINESS_UNKNOWN
    assert readiness.verdict != INFERRED_READY
    assert readiness.stale is True
    assert readiness.detail == STALE_EVIDENCE_DETAIL


def test_a_stale_verification_falls_through_to_a_fresh_assessment() -> None:
    """Staleness withholds one reading rather than the whole answer.

    A verification nobody has refreshed in a decade beside an assessment swept this
    week should read as the assessment says, with the staleness of the other
    recorded beside it -- not as `unknown`, which would throw away evidence this
    product does trust.
    """
    long_after = FIXED_INSTANT + timedelta(days=365 * 10)
    fresh = an_assessment(INFERRED_COMPATIBLE)
    fresh.observed_at = long_after

    readiness = readiness_of(fresh, a_verification(VERIFIED_COMPATIBLE), cutoff=long_after)

    assert readiness.verdict == INFERRED_READY
    assert readiness.evidence_type == EVIDENCE_INFERRED
    assert readiness.stale is True


def test_a_table_no_registered_collector_writes_has_no_target_and_is_never_stale() -> None:
    """The `None` branch of the target lookup, and it is a fact rather than a fault.

    `CPM-AD-28` already refuses a *registered* collector declaring no freshness
    target, so `None` here means no collector is registered for that table -- which
    is the state of `PackagePythonReadiness` itself, a derived table nothing
    collects. The honest consequence is that staleness could not be decided, and
    "could not be decided" is not "stale": treating it as stale would withhold every
    verdict in the component the day a table moved.
    """
    assert freshness_target(PackagePythonReadiness) is None  # type: ignore[arg-type]
    assert evidence_is_stale(PackagePythonReadiness, observed_at=FIXED_INSTANT, now=FIXED_INSTANT) is False  # type: ignore[arg-type]


def test_a_row_renders_the_series_the_verdict_and_the_evidence_type_behind_it() -> None:
    """What an admin list and a debugger show, for an unsaved row.

    `package_id` and `policy_run_id` are the two that can be absent, and both have
    their own wording rather than a bare `None` -- a row rendered inside a traceback
    is exactly the row whose relations are not there to follow.
    """
    rendered = str(
        PackagePythonReadiness(
            readiness=VERIFIED_READY,
            evidence_type=EVIDENCE_VERIFIED,
            python_series=ASSESSED_SERIES,
        ),
    )

    assert ASSESSED_SERIES in rendered
    assert VERIFIED_READY in rendered
    assert EVIDENCE_VERIFIED in rendered
    assert "no package" in rendered
    assert "no run" in rendered


def test_a_row_that_names_nothing_says_so_rather_than_rendering_a_blank() -> None:
    """The sentinel half of the same rendering."""
    rendered = str(PackagePythonReadiness(readiness=PY314_READINESS_UNKNOWN, evidence_type=EVIDENCE_NONE))

    assert "(no series)" in rendered
