"""`CPM-FR-21`: what to do about this package, decided without looking at its priority.

The eighth policy pass. It reads the six domain passes' derived rows for the same
run and recommends one of the eight actions PRD Appendix A.1 names.

**It never reads the priority bucket, and it is registered *before* the pass that
assigns one.** `CPM-PRIORITY-S02`'s AC 1 is that a work type is computable for a
package in any bucket and that the two are not coupled -- because a low-priority
package still has a recommended action, and a queue that only said what to do about
`P1` rows would leave every other row silent. Making that true by *ordering* rather
than by discipline is the point: this pass runs before `PriorityPass`, so there is
no priority row for this run to read even by mistake, and a later edit that tried
would find nothing there.

**The closed set is the PRD's and the ranking is this component's, and the two are
kept apart.** `policies/outcomes.py` transcribes the eight in Appendix A.1's own
order so a reader can check the transcription; `WORK_TYPE_PRECEDENCE` below is the
order they are *matched* in, which is a judgement this module makes and argues.

**Why the ranking is code and not versioned data.** `CPM-AD-8` makes rule sets
versioned data, and `policies/priority.py` ships an empty one because PRD Open
Question 8 names that decision as open. Nothing names this one as open: the PRD
fixes the set of eight, and what each of them *means* fixes when it applies -- a
package with no feedstock needs a recipe written whatever anybody's risk posture is.
What is left to decide is which recommendation wins when several apply, and that
follows from the same reasoning: an action that unblocks the others comes first.
A parameter here would be a file a reviewer could fill in only by re-deciding what
the eight words mean.

**Two of the eight are unreachable, and this pass says so rather than guessing.**

`already_tracked` means a record exists and the work is somebody else's to progress.
Knowing that means reading the workflow queue, which `CPM-AD-22` gives to a
`workflow` application `CPM-EP-APP` has not built -- so nothing this product records
distinguishes "nobody has filed this" from "somebody has", and no derivation may
claim the second.

`resolve_identity` is the second, and its reason is sharper. The only signal for it
is the package's identity confidence, and `CPM-AD-4` gives that exactly one consumer:
`core/confidence.py`'s gate, called from `core/rollup.py` and nowhere else. A test of
`IdentityConfidence.UNMAPPED` here would be a *second* gate --
`tests/unit/django_apps/test_confidence_gate_audit.py` exists to catch precisely
that, and caught this. It would also claim something the product then erases: the
gate replaces every contributed value for an unmapped package with `unknown`, so a
`resolve_identity` derived here would reach the derived table and never the rollup a
queue reads. The work is real and `CPM-IDENTITY-S04` already has a selection for it;
what is missing is a *derived* signal this pass may read, which is a story that owns
the identity domain rather than this one.

`CPM-PRIORITY-S02` records both gaps. The values and the closed-set constraint that
guards them are already in place for the day either signal exists.

**`unknown` is not "nothing to do".** The closed set offers no member for a package
in good order, so a package with nothing to act on and a package nothing was
established about both read `unknown`. That is a gap in the set rather than in this
derivation, and inventing a ninth value would be this component extending a set the
PRD closed. `CPM-PRIORITY-S02` records it.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

from conda_sentinel.core.clock import is_aware
from conda_sentinel.core.policy import PolicyPass
from conda_sentinel.policies.models import PackageWorkType
from conda_sentinel.policies.outcomes import ABSENT
from conda_sentinel.policies.outcomes import ADVISORIES_MATCHED
from conda_sentinel.policies.outcomes import BEHIND
from conda_sentinel.policies.outcomes import CREATE_RECIPE
from conda_sentinel.policies.outcomes import FILE_TRACKING_ISSUE
from conda_sentinel.policies.outcomes import FIX_VULNERABILITY
from conda_sentinel.policies.outcomes import FORBIDDEN
from conda_sentinel.policies.outcomes import INFERRED_NOT_READY
from conda_sentinel.policies.outcomes import INFERRED_READY
from conda_sentinel.policies.outcomes import MANUAL_REVIEW
from conda_sentinel.policies.outcomes import PRESENT_AND_INACTIVE
from conda_sentinel.policies.outcomes import RESTRICTED
from conda_sentinel.policies.outcomes import REVIEW_LICENSE
from conda_sentinel.policies.outcomes import STAGED_RECIPE_PENDING
from conda_sentinel.policies.outcomes import UPDATE_FEEDSTOCK
from conda_sentinel.policies.outcomes import VALIDATE_PYTHON_314
from conda_sentinel.policies.outcomes import VERIFIED_NOT_READY
from conda_sentinel.policies.outcomes import WORK_TYPE_UNKNOWN
from conda_sentinel.policies.priority import DOMAIN_READERS
from conda_sentinel.policies.priority import current_verdicts

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from django.db import models

    from conda_sentinel.core.models import PolicyRun
    from conda_sentinel.identity.models import Package

__all__ = [
    "NOTHING_RECOMMENDED_DETAIL",
    "POLICY_NAME",
    "ROLLUP_COLUMN",
    "WORK_TYPE_PRECEDENCE",
    "Recommendation",
    "WorkTypePass",
    "WorkTypePolicyError",
    "recommendation_for",
]

#: What this pass is called.
POLICY_NAME: Final[str] = "work-type"

#: The rollup column this pass contributes (`CPM-AD-11`).
ROLLUP_COLUMN: Final[str] = "work_type_status"


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One rule in the work-type derivation: what it recommends and when.

    Frozen and slotted, holding only data. A declaration rather than machinery, so
    the whole derivation is one readable table.

    Attributes:
        work_type: The `WorkType` value this rule recommends.
        domain: The derived domain whose verdict it reads, by the name
            `policies/priority.py`'s readers use.
        verdicts: The verdicts that recommend it. A tuple rather than one value
            because several verdicts can mean the same action -- an inactive
            feedstock and a behind one are both "update the feedstock".
        reason: What the row says about why this action was recommended.

    """

    work_type: str
    domain: str
    verdicts: tuple[str, ...]
    reason: str


#: The derivation, in the order it is matched. First match wins.
#:
#: **The order is the judgement this module makes**, and the rule behind it is that
#: an action which unblocks the others comes first:
#:
#: 1. `fix_vulnerability` -- a matched advisory is the one finding with a clock on
#:    it, and `CPM-UJ-1` opens with that queue.
#: 2. `review_license` -- a licence a rule forbade, restricted, or that no rule
#:    named. It outranks the packaging actions because it can make them pointless:
#:    there is no sense updating a feedstock for a package legal review will remove.
#: 3. `create_recipe` -- no feedstock exists, so there is nothing to update.
#: 4. `update_feedstock` -- one exists and needs work.
#: 5. `validate_python_314` -- readiness that rests on a *claim*. It is the only
#:    action that is work this product can ask for rather than work the world has
#:    forced, so it sits below the four it could otherwise crowd out.
#: 6. `file_tracking_issue` -- twice, and last, because it is the catch-all: a build
#:    that ran and did not come out, or a package behind on a surface, where no more
#:    specific action names what to do. A catch-all above anything else would make
#:    that thing unreachable.
#:
#: **`validate_python_314` fires on an *inference* and not on every unverified
#: readiness**, and an earlier shape of this table had it the other way round. The
#: condition read "every readiness but `verified_ready`", which is true of `unknown`
#: -- and `unknown` is what `CPM-PY314-S03` writes for a package nobody has collected
#: anything about. So a package this product had never observed was told to go and
#: verify it, which is both premature and the opposite of what `CPM-FR-14` says the
#: static pass is for: it "says where verification is worth spending", and it says so
#: by reaching an *inferred* verdict. A package with no assessment at all is not a
#: package whose 3.14 story rests on a claim -- there is no claim.
#:
#: `already_tracked` and `resolve_identity` are absent, and the module docstring
#: says why: one needs a workflow queue this product has not built, and the other
#: needs a derived identity signal that would otherwise be a second confidence
#: gate.
#:
#: A tuple of value objects rather than a chain of `if`s, because the *order* is the
#: decision and a reader has to be able to see it in one place -- and because
#: `tests/unit/django_apps/test_work_type_policy.py` sweeps it, which it could not
#: do to a branch.
WORK_TYPE_PRECEDENCE: Final[tuple[Recommendation, ...]] = (
    Recommendation(
        work_type=FIX_VULNERABILITY,
        domain="vulnerability_status",
        verdicts=(ADVISORIES_MATCHED,),
        reason="an advisory matched this package at the version this run read",
    ),
    Recommendation(
        work_type=REVIEW_LICENSE,
        domain="license_outcome",
        verdicts=(FORBIDDEN, RESTRICTED, MANUAL_REVIEW),
        reason="this package's licence needs a human decision before other work on it is worth doing",
    ),
    Recommendation(
        work_type=CREATE_RECIPE,
        domain="feedstock_presence_status",
        verdicts=(ABSENT,),
        reason="no conda-forge feedstock exists for this package, so there is nothing to update",
    ),
    Recommendation(
        work_type=UPDATE_FEEDSTOCK,
        domain="feedstock_presence_status",
        verdicts=(PRESENT_AND_INACTIVE, STAGED_RECIPE_PENDING),
        reason="a feedstock exists and needs work -- nobody is pushing to it, or its recipe is still staged",
    ),
    Recommendation(
        work_type=VALIDATE_PYTHON_314,
        domain="python_readiness",
        verdicts=(INFERRED_READY, INFERRED_NOT_READY),
        reason=(
            "this package's Python 3.14 readiness rests on what its metadata claims rather than on a build that "
            "ran, which is exactly where CPM-FR-14 says verification is worth spending"
        ),
    ),
    Recommendation(
        work_type=FILE_TRACKING_ISSUE,
        domain="python_readiness",
        verdicts=(VERIFIED_NOT_READY,),
        reason="a build of this package under Python 3.14 ran and did not come out, and that needs a record",
    ),
    Recommendation(
        work_type=FILE_TRACKING_ISSUE,
        domain="currency_status",
        verdicts=(BEHIND,),
        reason="this package is behind on a monitored surface and no more specific action names it",
    ),
)

#: What a row says when nothing recommended an action.
NOTHING_RECOMMENDED_DETAIL: Final[str] = (
    "nothing this run established recommends one of CPM-FR-21's eight actions for this package. That covers two "
    "different packages and the closed set cannot tell them apart: one in good order with nothing to act on, and "
    "one nothing was established about. The set names no action for either, and inventing a ninth value would be "
    "this component extending a set the PRD closed"
)


class WorkTypePolicyError(ValueError):
    """A work-type evaluation was asked for something it cannot judge.

    One flat type, a `ValueError` subclass on the same terms every policy error in
    this application is. Raised only for a naive cut-off: `core/policy_run.py` wraps
    every pass for one package in one transaction, so a raise here costs that
    package its other seven domains' rows, and every other condition this pass meets
    is an honest state the row records.
    """


def recommendation_for(verdicts: Mapping[str, str]) -> tuple[str, str]:
    """Return the work type this package's state recommends, and why.

    The whole of `CPM-FR-21`, as a pure function of the six derived verdicts.

    **Nothing here reads a priority bucket, and nothing here reads an identity
    confidence.** The first is AC 1's "not coupled", in the strongest form a
    signature can state it: the parameter is not offered. The second is
    `CPM-AD-4`'s gate having exactly one implementation -- see the module docstring
    for why a confidence test here would be a second one, and what it would have
    claimed that the product then erases.

    Args:
        verdicts: What the six domain passes concluded, by domain, as
            `policies/priority.py`'s reader returns them. A domain whose pass wrote
            no row is absent rather than present with a guessed verdict.

    Returns:
        The `WorkType` value and what the row says about it. `unknown` and
        `NOTHING_RECOMMENDED_DETAIL` where nothing recommended an action.

    """
    for rule in WORK_TYPE_PRECEDENCE:
        if verdicts.get(rule.domain) in rule.verdicts:
            return rule.work_type, rule.reason

    return WORK_TYPE_UNKNOWN, NOTHING_RECOMMENDED_DETAIL


class WorkTypePass(PolicyPass):
    """`CPM-FR-21` as a `PolicyPass`: read six verdicts, recommend one of eight actions.

    Three declarations and one method, and no `prepare`: this pass reads no
    versioned parameter -- the module docstring says why -- so there is nothing to
    establish before the loop.

    **It is registered before `PriorityPass`**, which is what makes AC 1's
    independence structural rather than a promise.
    """

    name: ClassVar[str] = POLICY_NAME
    derived_model: ClassVar[type[models.Model] | None] = PackageWorkType
    contributes: ClassVar[tuple[str, ...]] = (ROLLUP_COLUMN,)

    def evaluate(
        self,
        package: Package,
        *,
        policy_run: PolicyRun,
        evidence_cutoff: datetime,
    ) -> Mapping[str, str]:
        """Recommend one action for one package, and write its derived row.

        Called once per package, inside that package's transaction (`CPM-AD-23`),
        after the six domain passes and **before** the priority pass.

        **Every package gets a row**, including one nothing recommends an action
        for: the work type is `unknown` and the row says which absence it is.

        Args:
            package: The package to recommend for.
            policy_run: The run this evaluation belongs to. Its version and cut-off
                are copied onto the row, and its id is what bounds the six reads to
                this run's conclusions.
            evidence_cutoff: The instant evidence was read as of. Copied onto the
                row; nothing here reads the current time.

        Returns:
            The work type, under `work_type_status`, for `core/rollup.py` to write
            through `CPM-AD-4`'s gate.

        Raises:
            WorkTypePolicyError: When the cut-off is naive.

        """
        if not is_aware(evidence_cutoff):
            message = (
                f"a work-type evaluation was asked to read as of {evidence_cutoff!r}, which carries no "
                f"timezone. Every instant this product records is aware (CPM-AD-26)."
            )
            raise WorkTypePolicyError(message)

        work_type, detail = recommendation_for(
            current_verdicts(package_id=package.pk, policy_run_id=policy_run.pk),
        )
        PackageWorkType.objects.create(
            package=package,
            policy_run=policy_run,
            work_type=work_type,
            detail=detail,
            policy_version=policy_run.policy_version,
            evidence_cutoff=evidence_cutoff,
        )
        return {ROLLUP_COLUMN: work_type}


#: The domains this pass reads, restated from `policies/priority.py`'s table so a
#: reader can see that both passes read the same six and neither invents a seventh.
#:
#: Imported rather than restated, which is the one place this module reaches into a
#: sibling pass -- and it reaches for a *reader*, never for a verdict.
#: `policies/priority.py` owns the binding from a domain name to a table and column
#: because it declared it first; duplicating it here would be two tables that can
#: disagree about which column answers `license_outcome`.
#: `tests/unit/django_apps/test_work_type_policy.py` asserts every domain this
#: module's precedence names is one of them.
_DOMAINS_READ: Final[frozenset[str]] = frozenset(reader.domain for reader in DOMAIN_READERS)
