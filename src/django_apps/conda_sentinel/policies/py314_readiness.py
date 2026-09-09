"""`CPM-FR-19`: is this package ready for Python 3.14, and what kind of evidence says so.

The sixth policy pass, and the one `CPM-EP-PY314` was built toward. It reads the
epic's two evidence tables as of the run's stated cut-off --
`python_readiness_assessments` for what a project's metadata *claims* and
`python_verification_results` for what a build *did* -- derives one readiness
verdict, and writes its own derived row. It writes no evidence, makes no outbound
call, and never writes the rollup.

**The single property this pass turns on: the two kinds of evidence stay
distinguishable all the way into the derived row.** `CPM-PY314-S01` and
`CPM-PY314-S02` spent two stories keeping inference and proof in separate tables
with separate vocabularies. This is the first module that reads both, and
therefore the only place they could be quietly re-merged -- in the one column a
read surface renders. They are not. The verdict itself names the evidence type
(`verified_ready`, `inferred_ready`, and their negatives), an `evidence_type`
column states the same fact where a query can filter on it, and
`policies/models.py` puts three check constraints behind the pair so a row whose
evidence type contradicts its verdict is refused by PostgreSQL rather than merely
avoided here.

**Why the value carries the evidence type as well as the column.** `CPM-AD-24`
carries a derived status verbatim onto every read surface, so the question is not
whether *this* module keeps the distinction but whether a surface that projects
one column keeps it. A bare `ready` with the evidence type parked in a
neighbouring column survives only as long as every reader remembers the join --
and the reader who forgets is exactly the reader `CPM-FR-19` is written about.
`policies/outcomes.py` argues both halves.

**Verified outranks inferred, always.** A build that ran is proof; published
metadata is a claim. When a package has both, the verification decides the verdict
and the row still cites the assessment beside it -- which is what makes
`CPM-PY314-S03`'s AC 2 a property of the row rather than of this docstring. A
*disagreement* between the two -- metadata that admits this Python beside a build
that did not come out -- is recorded in `detail` and never averaged: nothing here
ranks two evidence kinds into a number, because an order can be read and a number
invites a mean.

**A policy may say what a collector could not, and that is the one place this
module's vocabulary diverges from the collectors'.**
`collectors/outcomes.py` refuses `verified_incompatible` and records
`verification_failed`, because a build fails for reasons that are not the
interpreter and a collector may reach no verdict at all (`CPM-AD-8`). "This
package is not ready" *is* a verdict, drawn from the best evidence there is, and
reaching it is what a policy pass exists to do. It is still not a claim that the
package can never work: the row cites the verification, which names the single
platform it ran on.

**Never a determinate verdict from an absence.** No evidence at the cut-off,
evidence that established nothing, a look that failed, a source that reported the
package absent, evidence older than its collector's declared freshness target, and
evidence about a different Python series are **all** `unknown` with an evidence
type of `none`. Reading any of them as "not ready" is the defect class both
preceding stories in this epic were written against, and it would be worse here
than there: this is the row a queue renders, and a false `not_ready` sends somebody
to fix a package nobody has looked at.

**Only rows about the assessed series are read.** Both evidence tables record
`python_series` precisely so an assessment of 3.14 and a verification of whatever
comes next can never be reduced into one answer, and the filter is applied in the
query rather than after it -- a row about another series is not "evidence that
disagrees", it is evidence about a different question.

**It reads evidence tables and never another pass's derived table.** All five
shipped passes take that rule and here it is load-bearing for the usual reason: a
readiness derived from another pass's rows would depend on two policy versions at
once, so `CPM-FR-22`'s replay could be stated for neither.

**Staleness is `CPM-FR-38`'s answer, consumed rather than restated, and measured
from the cut-off.** `core/freshness.py` owns the comparison; this asks it, with
the run's `evidence_cutoff` as `now`, so two replays of one run agree.
`latest_observation` is deliberately not used -- it answers about the newest
observation full stop, and a staleness verdict measured off a row the cut-off
excludes would make a replay disagree with the original.

**It ships no parameter, and that is a decision rather than an omission.**
`CPM-AD-8` makes rule sets versioned data, and the three parameterised passes
establish one in `prepare`. "Verified outranks inferred" is this epic's own
semantics rather than an organisational risk posture, and the PRD seeds no
readiness thresholds -- so there is nothing here for review to tune, and a
parameter invented for it would be a file nobody could fill in meaningfully.
`policies/remediation.py` reads no parameter for the same reason and is the
precedent. Should review disagree, the fix is a `policies/data/` parameter and a
reviewer's decision, not a code branch added here.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.models import PythonVerificationResult
from conda_sentinel.collectors.outcomes import INFERRED_COMPATIBLE
from conda_sentinel.collectors.outcomes import INFERRED_INCOMPATIBLE
from conda_sentinel.collectors.outcomes import READINESS_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import VERIFICATION_FAILED
from conda_sentinel.collectors.outcomes import VERIFICATION_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import VERIFIED_COMPATIBLE
from conda_sentinel.core.clock import is_aware
from conda_sentinel.core.freshness import freshness_of
from conda_sentinel.core.policy import PolicyPass
from conda_sentinel.core.registry import registered_collectors
from conda_sentinel.policies.models import PackagePythonReadiness
from conda_sentinel.policies.outcomes import EVIDENCE_INFERRED
from conda_sentinel.policies.outcomes import EVIDENCE_NONE
from conda_sentinel.policies.outcomes import EVIDENCE_VERIFIED
from conda_sentinel.policies.outcomes import INFERRED_NOT_READY
from conda_sentinel.policies.outcomes import INFERRED_READY
from conda_sentinel.policies.outcomes import PY314_READINESS_NOT_APPLICABLE
from conda_sentinel.policies.outcomes import PY314_READINESS_UNKNOWN
from conda_sentinel.policies.outcomes import VERIFIED_NOT_READY
from conda_sentinel.policies.outcomes import VERIFIED_READY

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from datetime import timedelta

    from django.db import models

    from conda_sentinel.core.models import AppendOnlyModel
    from conda_sentinel.core.models import PolicyRun
    from conda_sentinel.identity.models import Package

__all__ = [
    "AGREEMENT_DETAIL",
    "ASSESSED_SERIES",
    "DISAGREEMENT_DETAIL",
    "INAPPLICABLE_DETAIL",
    "NOTHING_ESTABLISHED_DETAIL",
    "NOTHING_OBSERVED_DETAIL",
    "POLICY_NAME",
    "READ_ORDERING",
    "STALE_EVIDENCE_DETAIL",
    "Py314ReadinessPass",
    "Py314ReadinessPolicyError",
    "Readiness",
    "current_assessment",
    "current_verification",
    "evidence_is_stale",
    "freshness_target",
    "inferred_reading",
    "readiness_of",
    "verified_reading",
]

#: What this pass is called. It keys the pass registry, keys the rollup's
#: per-domain `policy_versions` map, and appears in every refusal message.
#:
#: `py314-readiness` and not `readiness`: `policies/remediation.py` already owns a
#: vocabulary whose determinate members are called readiness states, and a second
#: unqualified `readiness` in one component would make "which readiness" a question
#: a reader has to answer from context every time.
POLICY_NAME: Final[str] = "py314-readiness"

#: How the two evidence tables are ordered to find the observation current at the
#: cut-off. Newest first, and the primary key breaks a tie between two rows written
#: at one instant -- the same ordering every pass in this application declares, for
#: the reason `policies/licence.py` gives: two rows sharing an instant is a
#: collision this product does not prevent, and an unordered `first()` would pick
#: whichever the backend felt like.
READ_ORDERING: Final[tuple[str, ...]] = ("-observed_at", "-pk")

#: The Python series this pass judges, dotted, as its evidence tables spell it.
#:
#: **Restated rather than imported from either collector**, on the terms both
#: collectors restate it from each other: a pass that imported a collector module
#: would be a pass whose *subject* changed when a collector was edited, and the two
#: collectors already keep their own spellings.
#: `tests/unit/django_apps/test_py314_readiness_policy.py` reconciles this string
#: against both of them, which is the only thing that would notice this pass
#: quietly judging a series neither collector assesses -- a state in which every
#: package reads `unknown` with every gate green.
ASSESSED_SERIES: Final[str] = "3.14"

#: What a row says in its own words, in each of the ways it is reachable. Named so
#: the row a run writes and the case that reads it back cannot drift.
NOTHING_OBSERVED_DETAIL: Final[str] = (
    "no Python readiness evidence of either kind exists for this package at this run's cut-off, so nothing has "
    "been established about whether it is ready. This is the ordinary state of most of an inventory -- the "
    "static assessment is swept weekly and verification is triggered by hand -- and it is emphatically not a "
    "statement that the package will not run"
)
NOTHING_ESTABLISHED_DETAIL: Final[str] = (
    "this package's Python readiness evidence exists and establishes nothing: the project declared nothing "
    "either way, or the look failed, or the source does not know the package. An absence of a finding is not a "
    "finding of absence, so no readiness verdict rests on it"
)
STALE_EVIDENCE_DETAIL: Final[str] = (
    "this package's Python readiness evidence had aged past its collector's declared freshness target at this "
    "run's cut-off, so no determinate verdict rests on it (CPM-FR-38: stale never displays as clean). The "
    "evidence is still on the row; what is withheld is the conclusion"
)
INAPPLICABLE_DETAIL: Final[str] = (
    "identity established that this package has no release ecosystem, so there is no declared Python metadata "
    "to assess and no artifact to build. This is the only path to a not_applicable readiness: evidence that is "
    "unknown, error or not_found has established nothing, and a package nobody has resolved is not a package "
    "this product need never make ready"
)
AGREEMENT_DETAIL: Final[str] = (
    "this package has both kinds of evidence and they agree. The verdict rests on the verification, because a "
    "build that ran is proof and published metadata is a claim; the assessment is cited beside it so a reader "
    "can see that both were read"
)
DISAGREEMENT_DETAIL: Final[str] = (
    "this package's two kinds of evidence disagree, and the verdict rests on the verification: a build that ran "
    "outranks what a project's metadata claims. The assessment is cited beside it rather than discarded -- the "
    "claim is still what the project published, and a build fails for reasons that are not the interpreter"
)


class Py314ReadinessPolicyError(ValueError):
    """A Python readiness evaluation was asked for something it cannot judge.

    One flat type, a `ValueError` subclass on the same terms every policy error in
    this application is: no caller branches on why, and the detail belongs in the
    message.

    **It is raised for almost nothing, and that is deliberate.**
    `core/policy_run.py` wraps *all* passes for one package in one
    `transaction.atomic()`, so raising here rolls back that package's currency,
    feedstock, vulnerability, licence and remediation rows as well as this one. A
    naive cut-off is the one condition worth that price: it is a caller defect
    rather than a fact about the package, and every read below would silently
    compare an aware instant against a naive one. Everything else -- no evidence,
    unreadable evidence, stale evidence, evidence about another series -- is an
    honest state this table records instead.
    """


class Readiness:
    """The verdict, the evidence type behind it and the rows it rests on.

    A plain class holding four values rather than a `NamedTuple` or a dataclass
    with defaults, so a caller unpacking it cannot get two `str` fields the wrong
    way round without a type error.

    Attributes:
        verdict: The `PackagePythonReadinessOutcome` value.
        evidence_type: The `ReadinessEvidence` value naming what produced it.
        assessment: The static assessment read, or `None`.
        verification: The verification read, or `None`.
        stale: Whether the evidence behind the verdict had aged past its
            collector's target at the cut-off.
        detail: What the row says in its own words.

    """

    __slots__ = ("assessment", "detail", "evidence_type", "stale", "verdict", "verification")

    def __init__(  # noqa: PLR0913 - one parameter per column the row carries; a bundle would hide one
        self,
        *,
        verdict: str,
        evidence_type: str,
        assessment: PythonReadinessAssessment | None = None,
        verification: PythonVerificationResult | None = None,
        stale: bool = False,
        detail: str = "",
    ) -> None:
        """Hold one derived readiness answer.

        Args:
            verdict: The `PackagePythonReadinessOutcome` value.
            evidence_type: The `ReadinessEvidence` value.
            assessment: The static assessment cited, if any.
            verification: The verification cited, if any.
            stale: Whether the evidence had aged past its target.
            detail: What the row says.

        """
        self.verdict = verdict
        self.evidence_type = evidence_type
        self.assessment = assessment
        self.verification = verification
        self.stale = stale
        self.detail = detail


def _require_aware(cutoff: datetime) -> None:
    """Refuse a naive cut-off before any evidence is read.

    Args:
        cutoff: The instant evidence is read as of.

    Raises:
        Py314ReadinessPolicyError: When it carries no timezone. Refused here rather
            than left to compare silently against the aware instants every evidence
            row carries.

    """
    if not is_aware(cutoff):
        message = (
            f"a Python readiness evaluation was asked to read evidence as of {cutoff!r}, which carries no "
            f"timezone. Every evidence row's observed_at is aware (CPM-AD-26), so a naive cut-off would compare "
            f"against them silently and produce a verdict from a window nobody chose."
        )
        raise Py314ReadinessPolicyError(message)


def current_assessment(*, package_id: int, cutoff: datetime) -> PythonReadinessAssessment | None:
    """Return the static assessment current at the cut-off, for the assessed series.

    **One row rather than a sweep, which is where this differs from
    `policies/licence.py`'s reader.** That pass reads a table whose collector may
    write several findings for one package in one collection, so it takes the whole
    sweep. Both of this epic's collectors write exactly one row per collection
    (`core/collection.py` calls `translate` once and both return a single row), so
    the observation current at the cut-off is one row and taking it is
    `collectors/models.py`'s `snapshot_as_of` rule rather than a narrowing of it.

    **The series filter is in the query.** A row about another Python is not
    evidence that disagrees -- it is evidence about a different question -- so it is
    never fetched.

    Args:
        package_id: The package to read.
        cutoff: The instant to read as of (`CPM-AD-21`).

    Returns:
        The assessment, or `None` when this package has none at the cut-off.

    Raises:
        Py314ReadinessPolicyError: When the cut-off is naive.

    """
    _require_aware(cutoff)
    return (
        PythonReadinessAssessment.objects.filter(
            package_id=package_id,
            python_series=ASSESSED_SERIES,
            observed_at__lte=cutoff,
        )
        .order_by(*READ_ORDERING)
        .first()
    )


def current_verification(*, package_id: int, cutoff: datetime) -> PythonVerificationResult | None:
    """Return the verification current at the cut-off, for the assessed series.

    A second reader with its own name rather than one parameterised by model, on
    the terms `policies/vulnerability.py` declares two: the two tables answer
    different questions and a caller reading this one should not be able to pass
    the other by accident.

    **The latest verification wins, and that is the "latest observation"
    convention every pass in this application takes.** A package verified on two
    platforms has two rows; the newest as of the cut-off is the reading, and the
    row the verdict cites is what names the platform it ran on. Reducing several
    platforms into one verdict is a different question from the one `CPM-FR-19`
    asks, and `CPM-PY314-S03` records it as the alternative not taken.

    Args:
        package_id: The package to read.
        cutoff: The instant to read as of (`CPM-AD-21`).

    Returns:
        The verification, or `None` when this package has none at the cut-off.

    Raises:
        Py314ReadinessPolicyError: When the cut-off is naive.

    """
    _require_aware(cutoff)
    return (
        PythonVerificationResult.objects.filter(
            package_id=package_id,
            python_series=ASSESSED_SERIES,
            observed_at__lte=cutoff,
        )
        .order_by(*READ_ORDERING)
        .first()
    )


def freshness_target(evidence_model: type[AppendOnlyModel]) -> timedelta | None:
    """Return the freshness target a registered collector declares for one evidence table.

    `CPM-AD-7` gives every collector its own evidence table, so the table *is* the
    collector and no lookup by name is needed.

    **Restated rather than imported from `policies/remediation.py`**, which
    declares the same helper: no pass imports another, for the reason no collector
    imports another -- a pass whose staleness rule changed when a different story
    edited its neighbour would be a pass nobody could reason about in isolation.
    `tests/unit/django_apps/test_py314_readiness_policy.py` reconciles the two
    behaviours against one shipped collector, so a divergence is noticed.

    Args:
        evidence_model: The evidence table to ask about.

    Returns:
        The declared target, or `None` where no registered collector writes that
        table. `None` is not a fault this pass refuses: `CPM-AD-28` already refuses
        a *registered* collector declaring none, so `None` here means none is
        registered, and the honest consequence is that staleness could not be
        decided.

    """
    for collector in registered_collectors():
        if collector.evidence_model is evidence_model:
            return collector.freshness_target
    return None


def evidence_is_stale(
    evidence_model: type[AppendOnlyModel],
    *,
    observed_at: datetime | None,
    now: datetime,
) -> bool:
    """Report whether one evidence row has aged past its collector's declared target.

    `CPM-FR-38`'s answer, consumed rather than restated: `core/freshness.py` owns
    the comparison and this asks it.

    Args:
        evidence_model: The evidence table, which names the collector whose target
            applies.
        observed_at: The instant the row carries, or `None` where there is no row.
        now: The instant to measure from -- the run's evidence cut-off. Nothing
            here reads a wall clock, so two replays of one run agree.

    Returns:
        Whether the row is stale. A package with no row is not stale, because an
        absence of observation is not an old observation -- `core/freshness.py`
        makes that choice and this inherits it. A table no registered collector
        writes is not stale either, for want of a target to measure against.

    """
    target = freshness_target(evidence_model)
    if target is None:
        return False
    return freshness_of(observed_at=observed_at, target=target, now=now).stale


def verified_reading(verification: PythonVerificationResult) -> str:
    """Return the verdict a verification supports, or nothing.

    Args:
        verification: The verification current at the cut-off.

    Returns:
        `verified_ready` for a build that came out, `verified_not_ready` for one
        that did not, and the empty string for a row that established nothing --
        `unknown`, `error` and `not_found` alike. `not_applicable` is answered
        separately, because it is a verdict rather than an absence of one.

    """
    if verification.state == VERIFIED_COMPATIBLE:
        return VERIFIED_READY
    if verification.state == VERIFICATION_FAILED:
        return VERIFIED_NOT_READY
    return ""


def inferred_reading(assessment: PythonReadinessAssessment) -> str:
    """Return the verdict a static assessment supports, or nothing.

    Args:
        assessment: The assessment current at the cut-off.

    Returns:
        `inferred_ready` for metadata that admits the assessed Python,
        `inferred_not_ready` for metadata that cannot, and the empty string for an
        assessment that established nothing -- which is the majority of a real
        inventory and is emphatically not a negative.

    """
    if assessment.state == INFERRED_COMPATIBLE:
        return INFERRED_READY
    if assessment.state == INFERRED_INCOMPATIBLE:
        return INFERRED_NOT_READY
    return ""


def readiness_of(
    assessment: PythonReadinessAssessment | None,
    verification: PythonVerificationResult | None,
    *,
    cutoff: datetime,
) -> Readiness:
    """Reduce this epic's two kinds of evidence to one readiness verdict.

    The whole of `CPM-FR-19`, as a pure function of two rows and an instant. One
    return per verdict a package can reach rather than a single composed expression,
    for the reason `core/collection.py`'s `collect` gives: each is a different
    statement about a different state, and a reader tracing why a package reads
    `unknown` should land on the branch that says so.

    **The order of the branches is the rule.** Inapplicability first, because
    identity establishing that the question does not apply outranks any evidence
    about it. Then staleness, because stale evidence may not produce a determinate
    verdict whatever it says. Then verification, because proof outranks inference.
    Then the assessment. Then the absences.

    Args:
        assessment: The static assessment current at the cut-off, or `None`.
        verification: The verification current at the cut-off, or `None`.
        cutoff: The instant staleness is measured from.

    Returns:
        The verdict, the evidence type behind it, the rows it rests on and what the
        row says.

    Raises:
        Py314ReadinessPolicyError: When the cut-off is naive. Refused here as well
            as in `evaluate`, and not only where a staleness comparison would have
            met it: a package with no evidence takes a branch that touches no
            instant at all, so a guard placed where the comparison happens would
            let exactly the packages this pass says least about through with a
            cut-off nobody could have measured anything against.

    """
    _require_aware(cutoff)
    if (verification is not None and verification.state == VERIFICATION_NOT_APPLICABLE) or (
        assessment is not None and assessment.state == READINESS_NOT_APPLICABLE
    ):
        return Readiness(
            verdict=PY314_READINESS_NOT_APPLICABLE,
            evidence_type=EVIDENCE_NONE,
            detail=INAPPLICABLE_DETAIL,
        )

    stale_verification = verification is not None and evidence_is_stale(
        PythonVerificationResult,
        observed_at=verification.observed_at,
        now=cutoff,
    )
    stale_assessment = assessment is not None and evidence_is_stale(
        PythonReadinessAssessment,
        observed_at=assessment.observed_at,
        now=cutoff,
    )

    verified = "" if verification is None or stale_verification else verified_reading(verification)
    inferred = "" if assessment is None or stale_assessment else inferred_reading(assessment)

    if verified:
        return Readiness(
            verdict=verified,
            evidence_type=EVIDENCE_VERIFIED,
            assessment=assessment,
            verification=verification,
            stale=stale_assessment,
            detail=_agreement_detail(verified=verified, inferred=inferred),
        )
    if inferred:
        return Readiness(
            verdict=inferred,
            evidence_type=EVIDENCE_INFERRED,
            assessment=assessment,
            verification=verification,
            stale=stale_verification,
            detail="",
        )
    if stale_verification or stale_assessment:
        return Readiness(
            verdict=PY314_READINESS_UNKNOWN,
            evidence_type=EVIDENCE_NONE,
            assessment=assessment,
            verification=verification,
            stale=True,
            detail=STALE_EVIDENCE_DETAIL,
        )
    if assessment is None and verification is None:
        return Readiness(
            verdict=PY314_READINESS_UNKNOWN,
            evidence_type=EVIDENCE_NONE,
            detail=NOTHING_OBSERVED_DETAIL,
        )
    return Readiness(
        verdict=PY314_READINESS_UNKNOWN,
        evidence_type=EVIDENCE_NONE,
        assessment=assessment,
        verification=verification,
        detail=NOTHING_ESTABLISHED_DETAIL,
    )


def _agreement_detail(*, verified: str, inferred: str) -> str:
    """Return what a verified row says about the inference beside it, if any.

    Args:
        verified: The verdict the verification supports.
        inferred: The verdict the assessment supports, or the empty string where
            there was none or it established nothing.

    Returns:
        The disagreement sentence when the two point different ways, the agreement
        sentence when they point the same way, and the empty string when there was
        no usable inference to compare against -- a verified verdict standing alone
        needs no note, because its own value says what it rests on.

    """
    if not inferred:
        return ""
    agrees = (verified == VERIFIED_READY) == (inferred == INFERRED_READY)
    return AGREEMENT_DETAIL if agrees else DISAGREEMENT_DETAIL


class Py314ReadinessPass(PolicyPass):
    """`CPM-FR-19` as a `PolicyPass`: read two evidence tables, reduce, write one row.

    Three declarations and one method. The derived table is
    `PackagePythonReadiness` and there is **no** rollup column: the rollup offers
    none for this domain, `CPM-AD-21` says no pass writes the health rollup, and
    which columns that table grows is `CPM-EP-PRIORITY`'s.

    **It overrides no `prepare`.** The three parameterised passes establish a
    parameter set once per run because their verdicts are governed by reviewed data
    keyed by the policy version. This pass reads no parameter -- the module
    docstring says why -- so there is nothing to establish before the loop and
    nothing a run-wide refusal would be about.
    """

    name: ClassVar[str] = POLICY_NAME
    derived_model: ClassVar[type[models.Model] | None] = PackagePythonReadiness
    contributes: ClassVar[tuple[str, ...]] = ()

    def evaluate(
        self,
        package: Package,
        *,
        policy_run: PolicyRun,
        evidence_cutoff: datetime,
    ) -> Mapping[str, str]:
        """Judge one package's Python readiness, and write its derived row.

        Called once per package, inside that package's transaction (`CPM-AD-23`),
        so a refusal here rolls back **everything this run did for this package** --
        its currency, feedstock, vulnerability, licence and remediation rows as well
        as this one. That is why so little in here refuses.

        **Every package gets a row**, including one with no evidence of either
        kind: the verdict is `unknown`, the evidence type is `none`, and the absence
        of a row would read as never-evaluated instead.

        Args:
            package: The package to judge.
            policy_run: The run this evaluation belongs to. Its version and its
                cut-off are copied onto the row, where together with the package
                they are `CPM-AD-21`'s key.
            evidence_cutoff: The instant to read evidence as of, and the instant
                staleness is measured from. Nothing here reads the current time.

        Returns:
            An empty mapping. This pass contributes no rollup column, which
            `core/policy.py` records as legitimate and `CPM-AD-21` requires.

        Raises:
            Py314ReadinessPolicyError: When the cut-off is naive. Deliberately not
                for absent, unreadable or stale evidence: a raise here rolls back
                this package's other five domains' rows too, and every one of those
                is an honest state the row can record instead.

        """
        _require_aware(evidence_cutoff)
        readiness = readiness_of(
            current_assessment(package_id=package.pk, cutoff=evidence_cutoff),
            current_verification(package_id=package.pk, cutoff=evidence_cutoff),
            cutoff=evidence_cutoff,
        )
        PackagePythonReadiness.objects.create(
            package=package,
            policy_run=policy_run,
            readiness=readiness.verdict,
            evidence_type=readiness.evidence_type,
            python_series=ASSESSED_SERIES,
            assessment=readiness.assessment,
            verification=readiness.verification,
            evidence_stale=readiness.stale,
            policy_version=policy_run.policy_version,
            evidence_cutoff=evidence_cutoff,
            detail=readiness.detail,
        )
        return {}
