"""The policy verdict vocabularies, in a leaf module that imports one thing.

Seven vocabularies live here: `CurrencyOutcome` (`CPM-CURRENCY-S06`),
`FeedstockOutcome` (`CPM-CURRENCY-S07`), `CPM-SECURITY-S04`'s
`PackageVulnerabilityOutcome` and `KevMembership`, `CPM-SECURITY-S05`'s
`PackageLicenseOutcome`, and `CPM-SECURITY-S06`'s `RemediationReadiness` and
`FixAvailability`. They share this module for one
reason and it is the same reason none of them is beside its own pass -- the
import cycle argued immediately below -- and they share nothing else. None is
derived from another and none ranks against another.

**`KevMembership` and `FixAvailability` are the two that are not outcome
types**, and their own docstrings argue why: each records a membership rather
than a derived status, each carries three values and not the four sentinels plus
verdicts `outcome_type` composes, and the columns that hold them are deliberately
not named for a status.

`CurrencyOutcome` is composed here rather than in `policies/currency.py`, and the
reason is an import cycle rather than a preference. Two modules need the type:
`policies/models.py`, whose per-surface columns declare it as their `choices`,
and `core/models.py`, whose rollup column `currency_status` declares the same
vocabulary so `core/rollup.py`'s `permitted_values` can check a contribution
against it. `policies/currency.py` imports `core.policy`, which reaches
`core.models` -- so a type bound there and read by `core/models.py` would close a
cycle and fail at start-up.

`identity/confidence.py` exists for exactly this problem and solves it exactly
this way: the vocabulary is the half of the pair that depends on nothing, so the
vocabulary is the half that moves. This module imports `core.outcomes` and
nothing else, in either direction. `FeedstockOutcome` is here for the identical
pair of edges: `policies/models.py` declares it as a column's `choices` and
`core/models.py` declares the same vocabulary on the rollup column
`feedstock_presence_status`, while `policies/feedstock.py` reaches `core.policy`.

**Bound once, at module scope, and that is load-bearing.** `outcome_type` mints a
distinct class on every call, so two calls would produce two types whose members
compare unequal as enum members and equal only as strings -- `core/outcomes.py`
says so in as many words, `tests/unit/django_apps/test_outcomes.py` pins it, and
`identity/models.py` binds `MappingOutcome` on the same terms. Everything that
needs the type imports it from here.

**Two determinate verdicts, refining `ok` rather than replacing it.**
`CPM-AD-5` makes `ok` "the generic determinate value, the one a per-status type
refines into verdicts of its own", and currency refines it into two: a surface
that states the same version as the authority is `current`, and one that states a
different version is `behind`. The four sentinels arrive by construction and
carry `core`'s own names, values and labels, so `unknown` here and `unknown`
anywhere else in the product are the same string with the same meaning.

**What is deliberately not a member.** There is no `ahead`, because deciding that
a surface is ahead rather than merely different needs a version *ordering* rule
this product does not have. `policies/currency.py`'s module docstring is the one
statement of what the comparison does and does not do; this vocabulary is shaped
by it rather than restating it.

**This module also declares the one thing `core/outcomes.py` cannot: how these
six values rank against each other.** `core.outcomes.aggregate` refuses a value
it cannot rank, and `PRECEDENCE` holds no per-status determinate verdict by
design -- "that decision belongs to whichever story introduces such a type". So
`CURRENCY_PRECEDENCE` below is this vocabulary's own order, declared as *data*
beside the vocabulary it ranks and recorded by name in
`tests/unit/django_apps/test_single_ordering_audit.py`. Writing it as a chain of
`if` statements instead would have been the same order, expressed in a form that
audit cannot see, which is worse than the duplication the audit exists to
prevent: an order written as control flow is an order nobody can enumerate.

**`FeedstockOutcome` declares no precedence, and that is a decision rather than
an omission.** `CURRENCY_PRECEDENCE` exists because the currency pass reduces
*four surfaces' verdicts* to one column, and a reduction needs a ranking. The
feedstock presence pass reduces nothing: one package has one feedstock, one
observation at the cut-off answers for it, and the verdict the row carries is the
verdict the rollup column carries. An order declared here would be data no
function reads -- which `tests/unit/django_apps/test_single_ordering_audit.py`
would have to license by name, and which the next reader would take for a ranking
this product applies somewhere. The day a story reduces several feedstock
verdicts to one, that story declares the order and records it there.

**Why `FeedstockOutcome` refines two of `core`'s values rather than one.**
`CPM-AD-5` calls `ok` "the generic determinate value, the one a per-status type
refines into verdicts of its own", and `CurrencyOutcome` refines only that.
Feedstock presence refines `ok` into `present_and_maintained` and
`present_and_inactive`, and it also refines `not_found` -- conda-forge answering
that there is no feedstock is `absent` when nothing is queued to create one and
`staged_recipe_pending` when something is, and `CPM-FR-40` fixes both as outcomes
of their own. Refining a sentinel is not the same as replacing it: `not_found`
remains a member of this vocabulary by construction and remains legal in every
column that declares it, and `FeedstockPresencePass` simply never produces it,
because for this domain it always has the more specific answer. Which of the four
sentinels a given pass can produce is a property of the pass, not of the
vocabulary.

**`PackageLicenseOutcome` is the one whose *best* value is the interesting
one.** Every other vocabulary here can be reached by absence -- nothing observed,
nothing matched, nothing recorded -- and the value absence reaches is always one
of `core`'s sentinels, which claim nothing. `allowed` is the exception: it is a
claim that a compliance rule named this licence and permitted it, so it must be
reachable *only* by a rule that says so. `LICENSE_PRECEDENCE` ranks it last, the
pass produces it from a rule's own disposition and from nothing else, and
`policies/models.py` puts a database check constraint behind it so a row claiming
it while naming no rule is refused rather than merely avoided.

**`RemediationReadiness` is the one whose *worst* value is the interesting one,
and it is `PackageLicenseOutcome`'s mirror.** There, `allowed` must never be
reached by an absence because it looks like good news. Here `blocked` must never
be reached by an absence for the opposite reason: it tells a security reviewer to
stop looking. A false `allowed` ships a forbidden licence; a false `blocked`
abandons a package whose fix is sitting on a surface nobody checked. Both are
absences masquerading as conclusions, and both are prevented the same way -- by
making "not read" a value the vocabulary can hold rather than a silence the
reduction has to guess at. `FixAvailability` below is that value's home, and
`policies/models.py` puts a database check constraint behind `blocked` so a row
claiming it while naming a surface that was never read is refused rather than
merely avoided.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from django.db import models

from conda_sentinel.core.outcomes import EMPTY_AGGREGATE
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.outcomes import OutcomeVocabularyError
from conda_sentinel.core.outcomes import outcome_type

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "ABSENT",
    "ABSENT_MEMBER",
    "ADVISORIES_MATCHED",
    "ADVISORIES_MATCHED_MEMBER",
    "ALLOWED",
    "ALLOWED_MEMBER",
    "ALREADY_TRACKED",
    "AWAITING_BUILD",
    "AWAITING_BUILD_MEMBER",
    "AWAITING_PACKAGING",
    "AWAITING_PACKAGING_MEMBER",
    "BEHIND",
    "BEHIND_MEMBER",
    "BLOCKED",
    "BLOCKED_MEMBER",
    "CREATE_RECIPE",
    "CURRENCY_PRECEDENCE",
    "CURRENCY_STATE_LENGTH",
    "CURRENT",
    "CURRENT_MEMBER",
    "ERROR",
    "EVIDENCE_INFERRED",
    "EVIDENCE_NONE",
    "EVIDENCE_TYPE_LENGTH",
    "EVIDENCE_VERIFIED",
    "FEEDSTOCK_ERROR",
    "FEEDSTOCK_NOT_APPLICABLE",
    "FEEDSTOCK_NOT_FOUND",
    "FEEDSTOCK_STATE_LENGTH",
    "FEEDSTOCK_UNKNOWN",
    "FILE_TRACKING_ISSUE",
    "FIX_AVAILABILITY_LENGTH",
    "FIX_NOT_PUBLISHED",
    "FIX_PUBLISHED",
    "FIX_VULNERABILITY",
    "FORBIDDEN",
    "FORBIDDEN_MEMBER",
    "INACTIVE_MEMBER",
    "INFERRED_NOT_READY",
    "INFERRED_NOT_READY_MEMBER",
    "INFERRED_READY",
    "INFERRED_READY_MEMBER",
    "KEV_LISTED",
    "KEV_MEMBERSHIP_LENGTH",
    "KEV_MEMBERSHIP_PRECEDENCE",
    "KEV_NOT_ESTABLISHED",
    "KEV_NOT_LISTED",
    "LICENSE_PRECEDENCE",
    "LICENSE_STATE_LENGTH",
    "LICENSE_STATUS_ERROR",
    "LICENSE_STATUS_NOT_APPLICABLE",
    "LICENSE_STATUS_NOT_FOUND",
    "LICENSE_STATUS_UNKNOWN",
    "MAINTAINED_MEMBER",
    "MANUAL_REVIEW",
    "MANUAL_REVIEW_MEMBER",
    "NOT_APPLICABLE",
    "NOT_FOUND",
    "NO_ADVISORY_MATCHED",
    "NO_ADVISORY_MATCHED_MEMBER",
    "PRESENT_AND_INACTIVE",
    "PRESENT_AND_MAINTAINED",
    "PRIORITY_BUCKETS",
    "PRIORITY_BUCKET_LENGTH",
    "PRIORITY_BUCKET_MEMBERS",
    "PRIORITY_STATUS_ERROR",
    "PRIORITY_STATUS_NOT_APPLICABLE",
    "PRIORITY_STATUS_NOT_FOUND",
    "PRIORITY_STATUS_UNKNOWN",
    "PY314_DECIDED_VERDICTS",
    "PY314_INFERRED_VERDICTS",
    "PY314_READINESS_ERROR",
    "PY314_READINESS_NOT_APPLICABLE",
    "PY314_READINESS_NOT_FOUND",
    "PY314_READINESS_STATE_LENGTH",
    "PY314_READINESS_UNKNOWN",
    "PY314_VERIFIED_VERDICTS",
    "READINESS_ERROR",
    "READINESS_NOT_APPLICABLE",
    "READINESS_NOT_FOUND",
    "READINESS_PRECEDENCE",
    "READINESS_STATE_LENGTH",
    "READINESS_UNKNOWN",
    "READY",
    "READY_MEMBER",
    "RESOLVE_IDENTITY",
    "RESTRICTED",
    "RESTRICTED_MEMBER",
    "REVIEW_LICENSE",
    "RULE_DISPOSITIONS",
    "STAGED_MEMBER",
    "STAGED_RECIPE_PENDING",
    "SURFACE_NOT_READ",
    "UNKNOWN",
    "UPDATE_FEEDSTOCK",
    "VALIDATE_PYTHON_314",
    "VERIFIED_NOT_READY",
    "VERIFIED_NOT_READY_MEMBER",
    "VERIFIED_READY",
    "VERIFIED_READY_MEMBER",
    "VULNERABILITY_PRECEDENCE",
    "VULNERABILITY_STATE_LENGTH",
    "VULNERABILITY_STATUS_ERROR",
    "VULNERABILITY_STATUS_NOT_APPLICABLE",
    "VULNERABILITY_STATUS_NOT_FOUND",
    "VULNERABILITY_STATUS_UNKNOWN",
    "WORK_TYPES",
    "WORK_TYPE_ERROR",
    "WORK_TYPE_LENGTH",
    "WORK_TYPE_MEMBERS",
    "WORK_TYPE_NOT_APPLICABLE",
    "WORK_TYPE_NOT_FOUND",
    "WORK_TYPE_UNKNOWN",
    "CurrencyOutcome",
    "FeedstockOutcome",
    "FixAvailability",
    "KevMembership",
    "PackageLicenseOutcome",
    "PackagePythonReadinessOutcome",
    "PackageVulnerabilityOutcome",
    "PriorityBucket",
    "ReadinessEvidence",
    "RemediationReadiness",
    "WorkType",
    "worst_currency",
    "worst_kev_membership",
    "worst_license",
    "worst_readiness",
    "worst_vulnerability",
]

#: The determinate verdict for a surface stating the authority's version,
#: declared once as the `(member name, value)` pair `outcome_type` takes.
#:
#: A pair rather than a member reference, because the composed type below is
#: built from it and `CURRENT` is read back out of it: a second spelling of
#: `"current"` anywhere would be a value that could drift from the one the column
#: actually offers, which is the duplication `core/outcomes.py` exists to
#: prevent.
CURRENT_MEMBER: Final[tuple[str, str]] = ("CURRENT", "current")

#: The determinate verdict for a surface stating a version the authority does
#: not, on the same terms as `CURRENT_MEMBER`.
BEHIND_MEMBER: Final[tuple[str, str]] = ("BEHIND", "behind")

#: The currency vocabulary: `core`'s four sentinels plus `current` and `behind`.
CurrencyOutcome: Final[type[models.TextChoices]] = outcome_type(
    "CurrencyOutcome",
    [CURRENT_MEMBER, BEHIND_MEMBER],
)

#: `CurrencyOutcome`'s own members, by name, read off the composed type itself.
#:
#: The composed type is built by the functional enum API, so its members are
#: invisible to a type checker reading its declared `type[TextChoices]` and
#: `CurrencyOutcome.CURRENT` will not type-check. This table is how the six
#: values below are reached *through the type* rather than beside it -- so a
#: sentinel that had drifted, or a determinate member that had been renamed,
#: fails here at import rather than silently making every comparison false.
#:
#: A comprehension rather than a literal, which is also what keeps it out of
#: `tests/unit/django_apps/test_single_ordering_audit.py`'s reach: it is a lookup
#: table with no order in it, and the only precedence order in this product
#: remains `core/outcomes.py`'s.
_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in CurrencyOutcome}

#: The surface states the authority's version.
CURRENT: Final[str] = _MEMBER_VALUES["CURRENT"]

#: The surface states a version the authority does not.
BEHIND: Final[str] = _MEMBER_VALUES["BEHIND"]

#: Nothing was observed for the surface at the cut-off, or the observation states
#: no version to compare. Reached through `CurrencyOutcome` rather than through
#: `OutcomeState`, because a column's default and a column's values must be its
#: own choices and reaching across to another class for them is the one place
#: this module would take a value from a type the field does not declare.
UNKNOWN: Final[str] = _MEMBER_VALUES["UNKNOWN"]

#: Looking at the surface failed.
ERROR: Final[str] = _MEMBER_VALUES["ERROR"]

#: The surface answered that it has no version for this package.
NOT_FOUND: Final[str] = _MEMBER_VALUES["NOT_FOUND"]

#: The surface is not one this package is published on at all.
NOT_APPLICABLE: Final[str] = _MEMBER_VALUES["NOT_APPLICABLE"]

#: How wide a column holding one of these values is. `CurrencyOutcome`'s longest
#: value is `not_applicable`, fourteen characters; the rest is headroom, so a
#: third determinate verdict needs no migration for the width alone. Sized like
#: `collectors/models.py`'s `_STATE_LENGTH` rather than derived from it: two
#: vocabularies, two declarations, each argued from its own longest value.
CURRENCY_STATE_LENGTH: Final[int] = 32

#: How the six currency verdicts rank when several surfaces are reduced to one
#: package verdict. Worst first, and `not_applicable` is deliberately absent.
#:
#: **Why this exists at all.** `core.outcomes.aggregate` ranks the five values a
#: single status can hold; this ranks *five surfaces' verdicts about one package*,
#: which is a different reduction over a vocabulary `PRECEDENCE` cannot rank --
#: `core/outcomes.py` refuses a per-status determinate verdict outright and says
#: the decision belongs to the story that introduces one. This is that decision,
#: made once, in data.
#:
#: **The four sentinels are written as `OutcomeState` members on purpose.** They
#: are the same strings the named constants above carry -- `verify_sentinels`
#: guarantees it -- and spelling them this way is what makes this declaration
#: *visible* to `tests/unit/django_apps/test_single_ordering_audit.py`, whose
#: detector matches `OutcomeState` member references. An order written only over
#: this module's own constants would be invisible to that audit, which its own
#: docstring names as a deliberate evasion. It is recorded there by name instead,
#: with both directions reconciled.
#:
#: **Why the ranks are what they are.**
#:
#: * `error` first, and this is the one place this order deliberately departs
#:   from an earlier draft of it. A lookup that failed may be hiding a worse
#:   discrepancy than the one the run did find, so a package whose conda channel
#:   could not be read must not report the feedstock's `behind` as the whole
#:   story. A read failure that vanished from the rollup column would be exactly
#:   the "degrades to a clean-looking result" `CPM-NFR-3` forbids.
#: * `behind` second, above the two un-observed states. It is the only
#:   *established* adverse finding here, and an operator acts on it. A surface
#:   nobody looked at masking a discrepancy the run actually proved would mean
#:   seeing nothing where there is something.
#: * `unknown` then `not_found`, in `core`'s own relative order and for `core`'s
#:   own reason: an un-observed state hides risk, while `not_found` is an
#:   informative negative.
#: * `current` last, because it is the only verdict that claims nothing is wrong.
#:
#: **`not_applicable` is not ranked, and that is the point.** A surface the
#: question does not apply to contributes nothing to the package's answer -- see
#: `worst_currency` for why excluding it is not the fold `CPM-FR-6` forbids.
CURRENCY_PRECEDENCE: Final[tuple[str, ...]] = tuple(
    # `str()` because the four sentinels are written as `OutcomeState` *members*
    # rather than as `.value`, and that spelling is load-bearing: the audit's
    # detector matches a member reference and does not follow a `.value`
    # attribute, so writing the values would make this declaration invisible to
    # the very check it is recorded in. Django renders a `Choices` member as its
    # value, so the tuple is the plain strings the columns hold.
    str(verdict)
    for verdict in (
        OutcomeState.ERROR,
        BEHIND,
        OutcomeState.UNKNOWN,
        OutcomeState.NOT_FOUND,
        CURRENT,
    )
)

#: Rank by value, so a caller may pass either this vocabulary's own strings or
#: `OutcomeState`'s -- which are the same strings for the four sentinels.
_RANK: Final[dict[str, int]] = {value: index for index, value in enumerate(CURRENCY_PRECEDENCE)}


def worst_currency(verdicts: Iterable[str]) -> str:
    """Reduce several surfaces' currency verdicts to the one verdict for the package.

    **`not_applicable` surfaces are dropped before the reduction, and only an
    all-`not_applicable` package reads `not_applicable`.** That is the one rule
    here that needs arguing, because it looks at first like the fold `CPM-FR-6`
    forbids and is the opposite of it.

    `CPM-FR-6` says a check that does not apply to a package "is never folded
    into clean or unknown", and it is about *one* check's own status: the surface
    column keeps `not_applicable` and always will. What this function reduces is
    four statements about four different surfaces, and a surface the question was
    never about has no answer to contribute. Ranking it instead -- which an
    earlier version of this did, by sending it through `core`'s order where it
    outranks the determinate value -- meant that every non-Python package, for
    which `CPM-FR-8` records exactly that row against PyPI, reported
    `not_applicable` overall while three surfaces had answered. That discards
    determinate findings for a large population, which is a worse fold than the
    one the rule was trying to avoid.

    Args:
        verdicts: The per-surface verdicts, as `CurrencyOutcome` values.

    Returns:
        The worst verdict among the surfaces the question applied to, by
        `CURRENCY_PRECEDENCE`. `not_applicable` when every surface given was
        `not_applicable`, and `core.outcomes.EMPTY_AGGREGATE`'s value for no
        surfaces at all -- unreachable from `CurrencyPass`, which always produces
        four, and stated rather than left to whatever `min()` over an empty
        sequence happens to do.

    Raises:
        OutcomeVocabularyError: When a verdict has no rank -- a value from
            outside this vocabulary entirely. Refused rather than treated as
            determinate, on exactly the terms `core.outcomes.aggregate` refuses
            one: ranking an unrecognised value alongside `current` would be the
            `CPM-FR-6` fold arrived at by silence.

    """
    given = list(verdicts)
    if not given:
        return EMPTY_AGGREGATE.value
    judged = [verdict for verdict in given if verdict != NOT_APPLICABLE]
    if not judged:
        return NOT_APPLICABLE

    ranked: list[int] = []
    for verdict in judged:
        rank = _RANK.get(verdict)
        if rank is None:
            message = (
                f"{verdict!r} has no rank in the currency precedence order. The ranked values are "
                f"{sorted(_RANK)}, plus {NOT_APPLICABLE!r}, which is excluded from the reduction rather "
                f"than ranked; a verdict from outside this vocabulary needs its rank decided by the story "
                f"that introduces it, not inferred here."
            )
            raise OutcomeVocabularyError(message)
        ranked.append(rank)
    return CURRENCY_PRECEDENCE[min(ranked)]


# ---------------------------------------------------------------------------
# `CPM-FR-40`'s feedstock presence and maintenance vocabulary.
#
# A second vocabulary in this module and not a second *order*: see the module
# docstring for why this one declares no precedence, and for why it refines
# `not_found` as well as `ok`.
# ---------------------------------------------------------------------------

#: The verdict for a package conda-forge has no feedstock for and nothing queued
#: to create one, declared as the `(member name, value)` pair `outcome_type`
#: takes.
#:
#: A pair rather than a member reference, on exactly the terms `CURRENT_MEMBER`
#: is one: the composed type below is built from it and `ABSENT` is read back out
#: of it, so a second spelling of `"absent"` anywhere would be a value that could
#: drift from the one the column actually offers.
ABSENT_MEMBER: Final[tuple[str, str]] = ("ABSENT", "absent")

#: The verdict for a feedstock that exists and was pushed to within the run's
#: inactivity threshold of its evidence cut-off.
MAINTAINED_MEMBER: Final[tuple[str, str]] = ("PRESENT_AND_MAINTAINED", "present_and_maintained")

#: The verdict for a feedstock that exists and whose last push is older than that
#: threshold.
INACTIVE_MEMBER: Final[tuple[str, str]] = ("PRESENT_AND_INACTIVE", "present_and_inactive")

#: The verdict for a package with no feedstock and an open staged recipe that
#: would create one. Distinct from `absent` because the two call for different
#: work: one is a gap to fill and the other is a review to finish.
STAGED_MEMBER: Final[tuple[str, str]] = ("STAGED_RECIPE_PENDING", "staged_recipe_pending")

#: The feedstock vocabulary: `core`'s four sentinels plus `CPM-FR-40`'s four
#: determinate outcomes.
FeedstockOutcome: Final[type[models.TextChoices]] = outcome_type(
    "FeedstockOutcome",
    [ABSENT_MEMBER, MAINTAINED_MEMBER, INACTIVE_MEMBER, STAGED_MEMBER],
)

#: `FeedstockOutcome`'s own members, by name, read off the composed type itself,
#: for the reason `_MEMBER_VALUES` above is: the functional enum API makes the
#: members invisible to a type checker, and reaching them *through* the type is
#: what makes a drifted sentinel fail at import rather than silently make every
#: comparison false. A comprehension rather than a literal, which is also what
#: keeps it out of `tests/unit/django_apps/test_single_ordering_audit.py`'s
#: reach.
_FEEDSTOCK_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in FeedstockOutcome}

#: conda-forge has no feedstock for this package, and nothing is queued to make
#: one.
ABSENT: Final[str] = _FEEDSTOCK_MEMBER_VALUES["ABSENT"]

#: A feedstock exists and has been pushed to recently enough.
PRESENT_AND_MAINTAINED: Final[str] = _FEEDSTOCK_MEMBER_VALUES["PRESENT_AND_MAINTAINED"]

#: A feedstock exists and has not.
PRESENT_AND_INACTIVE: Final[str] = _FEEDSTOCK_MEMBER_VALUES["PRESENT_AND_INACTIVE"]

#: No feedstock, but a staged recipe is open that would create one.
STAGED_RECIPE_PENDING: Final[str] = _FEEDSTOCK_MEMBER_VALUES["STAGED_RECIPE_PENDING"]

#: Nothing was observed at the cut-off, the observation itself records `unknown`,
#: or a feedstock exists whose activity the collector could not date.
#:
#: Reached through `FeedstockOutcome` rather than through `OutcomeState`, and
#: named apart from `UNKNOWN` above rather than shared with it. The two carry the
#: same string -- `verify_sentinels` guarantees it -- but a column's default and a
#: column's values must be *its own* choices, and a feedstock column defaulting to
#: a constant read off the currency vocabulary would be the one place this module
#: took a value from a type the field does not declare.
FEEDSTOCK_UNKNOWN: Final[str] = _FEEDSTOCK_MEMBER_VALUES["UNKNOWN"]

#: Looking for the feedstock failed.
FEEDSTOCK_ERROR: Final[str] = _FEEDSTOCK_MEMBER_VALUES["ERROR"]

#: `core`'s generic negative, kept in the vocabulary by construction and never
#: produced by `FeedstockPresencePass`, which always has the more specific
#: `absent` or `staged_recipe_pending` to say instead. See the module docstring.
FEEDSTOCK_NOT_FOUND: Final[str] = _FEEDSTOCK_MEMBER_VALUES["NOT_FOUND"]

#: The feedstock question is not this package's -- a package whose feedstock
#: mapping resolution recorded as inapplicable.
FEEDSTOCK_NOT_APPLICABLE: Final[str] = _FEEDSTOCK_MEMBER_VALUES["NOT_APPLICABLE"]

#: How wide a column holding one of these values is. `FeedstockOutcome`'s longest
#: value is `present_and_maintained`, twenty-two characters; the rest is
#: headroom. Sized like `CURRENCY_STATE_LENGTH` rather than derived from it: two
#: vocabularies, two declarations, each argued from its own longest value.
FEEDSTOCK_STATE_LENGTH: Final[int] = 32


# ---------------------------------------------------------------------------
# `CPM-FR-17`'s two vulnerability vocabularies.
#
# A third and a fourth vocabulary in this module, and only one of them is an
# outcome type. `PackageVulnerabilityOutcome` below is the per-package
# *status* the vulnerability pass derives; `KevMembership` is not a status at
# all and is deliberately not built from `outcome_type` -- see its own
# declaration for why three values is the whole of it.
#
# **Both declare a precedence, and neither is visible to
# `tests/unit/django_apps/test_single_ordering_audit.py`'s detector.** That
# detector reads a literal holding *two or more* `OutcomeState` member
# references, and neither order holds two: `VULNERABILITY_PRECEDENCE` ranks
# exactly one sentinel, and `KEV_MEMBERSHIP_PRECEDENCE` ranks none. That is a
# property of the orders rather than a way of writing them -- there is no second
# sentinel to spell -- so the audit's recorded table still describes this file
# accurately at one detector-visible declaration, and the two orders here are
# pinned by name and by contents in
# `tests/unit/django_apps/test_vulnerability_policy.py` instead. Writing either
# as a chain of `if` statements would have been the same ranking in a form
# nobody can enumerate, which `CURRENCY_PRECEDENCE` above already argues is the
# worse shape.
# ---------------------------------------------------------------------------

#: The determinate verdict for a package the run matched at least one advisory
#: to, declared once as the `(member name, value)` pair `outcome_type` takes.
#:
#: A pair rather than a member reference, on exactly the terms `CURRENT_MEMBER`
#: is one: the composed type below is built from it and `ADVISORIES_MATCHED` is
#: read back out of it, so a second spelling of the value anywhere would be one
#: that could drift from what the column actually offers.
#:
#: `advisories_matched` rather than `vulnerable`, `affected` or `exposed`, and
#: the difference is what the row can honestly claim -- the same distinction
#: `collectors/outcomes.py` argues for `matched` one level down. What happened is
#: that an advisory source matched advisories to this package at the version this
#: product asked about. Whether the package is actually exploitable is
#: `CPM-FR-41`'s remediation readiness, and a value that said so would be a
#: verdict this pass has no evidence for.
#:
#: **Plural, and that is the difference from the evidence value it reduces.**
#: `vulnerability_findings` holds one row per matched advisory; this column holds
#: one value per package. A package with nine findings and a package with one
#: both read `advisories_matched`, and how many there were is a count a reader
#: takes from the evidence rather than from a status -- folding it in would be
#: the arithmetic this story exists to keep out of the column.
ADVISORIES_MATCHED_MEMBER: Final[tuple[str, str]] = ("ADVISORIES_MATCHED", "advisories_matched")

#: The determinate verdict for a package whose advisory source was read and
#: matched nothing.
#:
#: **A second determinate member rather than a sentinel, and it is the decision
#: this vocabulary exists to make.** "We read the source and it matched no
#: advisory to this package" is a negative that was *established*; "nobody
#: looked", "the look failed" and "the source did not know the package" are
#: three ways of establishing nothing. `CPM-SM-2` measures this product on not
#: presenting the second group as the first, and `CPM-FR-6` forbids folding
#: them -- so they cannot share a value, and this is the value the established
#: half gets.
#:
#: It is emphatically **not** a clean verdict about the package, and the name
#: says only what happened. One advisory source was read; the package may still
#: carry an advisory that source does not know, and the row's referenced finding
#: says which source was asked.
NO_ADVISORY_MATCHED_MEMBER: Final[tuple[str, str]] = ("NO_ADVISORY_MATCHED", "no_advisory_matched")

#: The per-package vulnerability status vocabulary: `core`'s four sentinels plus
#: the two determinate verdicts above.
#:
#: Named `PackageVulnerabilityOutcome` and not `VulnerabilityOutcome`, because
#: `collectors/outcomes.py` already owns that name for what a *finding* records.
#: The two are different vocabularies about different subjects -- one row per
#: matched advisory there, one value per package here -- and a shared name would
#: make "which of them does this column hold" a question about imports.
PackageVulnerabilityOutcome: Final[type[models.TextChoices]] = outcome_type(
    "PackageVulnerabilityOutcome",
    [ADVISORIES_MATCHED_MEMBER, NO_ADVISORY_MATCHED_MEMBER],
)

#: `PackageVulnerabilityOutcome`'s own members, by name, read off the composed
#: type itself, for the reason `_MEMBER_VALUES` above is: the functional enum API
#: makes the members invisible to a type checker, and reaching them *through* the
#: type is what makes a drifted sentinel fail at import rather than silently make
#: every comparison false. A comprehension rather than a literal, which is also
#: what keeps it out of `tests/unit/django_apps/test_single_ordering_audit.py`'s
#: reach.
_VULNERABILITY_MEMBER_VALUES: Final[dict[str, str]] = {
    member.name: member.value for member in PackageVulnerabilityOutcome
}

#: At least one advisory matched this package at the run's cut-off.
ADVISORIES_MATCHED: Final[str] = _VULNERABILITY_MEMBER_VALUES["ADVISORIES_MATCHED"]

#: The advisory source was read and matched no advisory to this package.
NO_ADVISORY_MATCHED: Final[str] = _VULNERABILITY_MEMBER_VALUES["NO_ADVISORY_MATCHED"]

#: The run established nothing about this package's exposure: no evidence at the
#: cut-off, evidence that says only that nothing was established, a look that
#: failed, or a source that did not know the package.
#:
#: Reached through `PackageVulnerabilityOutcome` rather than through
#: `OutcomeState`, and named apart from `UNKNOWN` and `FEEDSTOCK_UNKNOWN` above
#: rather than shared with either. The three carry the same string --
#: `verify_sentinels` guarantees it -- but a column's default and a column's
#: values must be *its own* choices, and a vulnerability column taking a constant
#: off the currency vocabulary would be the one place this module took a value
#: from a type the field does not declare.
VULNERABILITY_STATUS_UNKNOWN: Final[str] = _VULNERABILITY_MEMBER_VALUES["UNKNOWN"]

#: `core`'s "the look failed", carried in the vocabulary by construction and
#: produced by nothing.
#:
#: **The pass folds an errored finding into `unknown` deliberately**, and the
#: fold is argued in `policies/vulnerability.py`: at the finding level `error`
#: says how the run failed, and at the *package* level all it says is that this
#: run established nothing about the package's exposure -- which is what
#: `unknown` means. The distinction is not lost, because the row references the
#: finding that carries it and says so in its own `detail`.
VULNERABILITY_STATUS_ERROR: Final[str] = _VULNERABILITY_MEMBER_VALUES["ERROR"]

#: `core`'s informative negative, carried in the vocabulary by construction and
#: produced by nothing, on exactly the terms `VULNERABILITY_STATUS_ERROR` states.
#: On `vulnerability_findings` it means the advisory *locator* does not exist,
#: which is a withdrawn or misconfigured source rather than a clean package.
VULNERABILITY_STATUS_NOT_FOUND: Final[str] = _VULNERABILITY_MEMBER_VALUES["NOT_FOUND"]

#: `core`'s "the question was never ours to ask", carried by construction and
#: produced by nothing: an advisory question applies to every package, and
#: `vulnerability_findings` refuses a row carrying this value outright. Named so
#: the reduction below can refuse it by name rather than by silence.
VULNERABILITY_STATUS_NOT_APPLICABLE: Final[str] = _VULNERABILITY_MEMBER_VALUES["NOT_APPLICABLE"]

#: How wide a column holding one of these values is.
#: `PackageVulnerabilityOutcome`'s longest value is `no_advisory_matched`,
#: nineteen characters -- one more than `advisories_matched`, which an earlier
#: version of this comment named; the rest is headroom. Sized like
#: `CURRENCY_STATE_LENGTH` rather than derived from it: four vocabularies, four
#: declarations, each argued from its own longest value.
VULNERABILITY_STATE_LENGTH: Final[int] = 32

#: How the verdicts several findings support rank when they are reduced to one
#: package status. Worst first, and only three of the six values are ranked.
#:
#: **Why only three.** `policies/vulnerability.py` produces exactly three
#: values: a package with a matched advisory, a package whose source answered
#: and matched nothing, and a package about which this run established nothing.
#: `error`, `not_found` and `not_applicable` are members of the vocabulary by
#: construction and are never reached -- the first two are folded into `unknown`
#: where they arrive, and the third is refused by `vulnerability_findings`
#: outright. Ranking a value no reduction can meet would be data no function
#: reads, which is the objection `FeedstockOutcome`'s missing order records.
#:
#: **`advisories_matched` is first, and this deliberately departs from
#: `CURRENCY_PRECEDENCE`'s shape.** There, `error` outranks the determinate
#: adverse verdict, because a lookup that failed may hide a worse discrepancy
#: than the one the run did find. Here the determinate adverse verdict *is* the
#: worst thing this vocabulary can say: an advisory this run matched, named and
#: recorded is an actionable finding, and `CPM-UJ-1` opens with a queue led by
#: exactly those. A package with a matched advisory and a second, errored finding
#: reporting `unknown` would drop it out of that queue -- `CPM-SM-3` measures
#: this product on exploited vulnerabilities being *visible*, and a queue emptied
#: by a failed second read is the failure it names.
#:
#: `unknown` then `no_advisory_matched`, in `core`'s own relative order and for
#: `core`'s own reason: an un-established state hides risk, and the established
#: negative is the only verdict here that claims nothing was found.
#:
#: The one sentinel is written as an `OutcomeState` member on purpose, on the
#: terms `CURRENCY_PRECEDENCE` states: it is the same string
#: `VULNERABILITY_STATUS_UNKNOWN` carries, and spelling it this way is what makes
#: the rank *legible* as a sentinel rather than as one more domain token.
VULNERABILITY_PRECEDENCE: Final[tuple[str, ...]] = tuple(
    # `str()` for the reason `CURRENCY_PRECEDENCE` gives: the sentinel is written
    # as an `OutcomeState` member and Django renders a `Choices` member as its
    # value, so the tuple is the plain strings the column holds.
    str(verdict)
    for verdict in (ADVISORIES_MATCHED, OutcomeState.UNKNOWN, NO_ADVISORY_MATCHED)
)

#: Rank by value, so a caller may pass either this vocabulary's own strings or
#: `OutcomeState`'s -- which are the same strings for the sentinel.
_VULNERABILITY_RANK: Final[dict[str, int]] = {value: index for index, value in enumerate(VULNERABILITY_PRECEDENCE)}


def worst_vulnerability(verdicts: Iterable[str]) -> str:
    """Reduce several findings' verdicts to the one status for the package.

    Args:
        verdicts: The per-finding verdicts, as `PackageVulnerabilityOutcome`
            values.

    Returns:
        The worst verdict among them, by `VULNERABILITY_PRECEDENCE`, and
        `core.outcomes.EMPTY_AGGREGATE`'s value -- `unknown` -- for no verdicts
        at all. The empty case is reachable and is the story's own AC 2: a
        package with no vulnerability evidence at the cut-off has nothing to
        reduce, and the answer is `unknown` rather than clean. Stated here rather
        than left to whatever `min()` over an empty sequence happens to do.

    Raises:
        OutcomeVocabularyError: When a verdict has no rank. That is every value
            this pass never produces -- `error`, `not_found`, `not_applicable` --
            and every string from outside the vocabulary entirely. Refused rather
            than treated as determinate, on exactly the terms
            `core.outcomes.aggregate` refuses one: ranking an unrecognised value
            beside `no_advisory_matched` would be the `CPM-FR-6` fold arrived at
            by silence, on the one column a security reviewer reads first.

    """
    ranked: list[int] = []
    for verdict in verdicts:
        rank = _VULNERABILITY_RANK.get(verdict)
        if rank is None:
            message = (
                f"{verdict!r} has no rank in the vulnerability precedence order. The ranked values are "
                f"{sorted(_VULNERABILITY_RANK)}; every other member of PackageVulnerabilityOutcome is carried "
                f"by construction and produced by nothing, so a verdict outside the three needs its rank "
                f"decided by the story that starts producing it, not inferred here."
            )
            raise OutcomeVocabularyError(message)
        ranked.append(rank)
    if not ranked:
        return EMPTY_AGGREGATE.value
    return VULNERABILITY_PRECEDENCE[min(ranked)]


class KevMembership(models.TextChoices):
    """Whether the KEV catalog lists an advisory recorded against this package.

    **Three values, and the third is the whole reason this type exists.**
    `collectors/outcomes.py`'s `KevOutcome` has two determinate values, `listed`
    and `not_listed`, and a package the KEV collector never ran for is neither.
    Recording such a package as `not_listed` would claim the run established an
    absence it never established -- and `not_listed` is the one value on that
    table a read surface could most plausibly paint green. So `not_established`
    is a value of its own, and the two facts cannot share one.

    **Deliberately not built from `outcome_type`, and deliberately not named for
    a status.** This is not one of `CPM-AD-5`'s derived statuses: it records a
    membership, the way `AuthorityOrderSource` records a provenance, and the four
    sentinels an outcome type supplies would be four more ways of spelling
    `not_established` on a column whose whole point is that there is exactly one.
    The column that holds it is named `kev_membership` for the same reason --
    `tests/unit/django_apps/test_outcome_field_audit.py` recognises a derived
    status by name, and a name ending `_status` would put this column under a
    rule that would then demand the four sentinels it must not offer.

    **`listed` and `not_listed` are spelled exactly as `KevOutcome` spells
    them**, so a reader comparing this derived column with the evidence row that
    supported it is comparing one string rather than translating between two
    vocabularies. The identity is asserted by a case rather than assumed, because
    nothing in either declaration enforces it.

    **It is never a number.** `CPM-FR-17` requires that KEV membership stay
    distinguishable and never be averaged into severity, and this vocabulary is
    how: `policies/vulnerability.py` reads it into its own stored column and no
    arithmetic in that module ever sees it. A rank *within* this vocabulary is
    `KEV_MEMBERSHIP_PRECEDENCE` below and reduces KEV rows to one KEV answer; it
    never leaves this column.
    """

    LISTED = "listed"
    NOT_LISTED = "not_listed"
    NOT_ESTABLISHED = "not_established"


#: How wide a column holding one of these values is. `not_established` is
#: fifteen characters; the rest is headroom, on the terms every width in this
#: module is argued.
KEV_MEMBERSHIP_LENGTH: Final[int] = 32

#: The KEV catalog lists an advisory this run recorded against the package.
KEV_LISTED: Final[str] = KevMembership.LISTED.value

#: The catalog was read and lists none of the advisories this run recorded.
KEV_NOT_LISTED: Final[str] = KevMembership.NOT_LISTED.value

#: No KEV cross-reference established anything about this package: none was
#: written by the cut-off, or the ones that were say only that the catalog could
#: not answer. Never `not_listed`, which is the defect this vocabulary exists to
#: prevent.
KEV_NOT_ESTABLISHED: Final[str] = KevMembership.NOT_ESTABLISHED.value

#: How the three memberships rank when several cross-references are reduced to
#: one answer about a package. Worst first.
#:
#: `listed` first, because one listed advisory among nine that are not is the
#: fact `CPM-FR-17` exists to keep visible. `not_established` above
#: `not_listed`, in `core`'s own relative order and for `core`'s own reason: an
#: un-established state hides risk, while an established negative is an
#: informative one. A package whose only cross-reference errored must not read
#: as one the catalog cleared.
#:
#: Data beside the vocabulary it ranks rather than a chain of `if` statements,
#: which is `CURRENCY_PRECEDENCE`'s argument applied to a second order: an order
#: written as control flow is an order nobody can enumerate.
KEV_MEMBERSHIP_PRECEDENCE: Final[tuple[str, ...]] = (KEV_LISTED, KEV_NOT_ESTABLISHED, KEV_NOT_LISTED)

#: Rank by value, on the terms `_VULNERABILITY_RANK` is built.
_KEV_MEMBERSHIP_RANK: Final[dict[str, int]] = {value: index for index, value in enumerate(KEV_MEMBERSHIP_PRECEDENCE)}


def worst_kev_membership(memberships: Iterable[str]) -> str:
    """Reduce several cross-references' memberships to the one answer for the package.

    Args:
        memberships: The per-row memberships, as `KevMembership` values.

    Returns:
        The worst of them, by `KEV_MEMBERSHIP_PRECEDENCE`, and
        `not_established` for none at all -- a package with no cross-reference at
        the cut-off has had nothing established about it, which is the value's
        entire meaning and is emphatically not `not_listed`.

    Raises:
        OutcomeVocabularyError: When a membership has no rank. Every member of
            this vocabulary is ranked, so an unranked value is one from outside
            it entirely, and treating it as an absence would let a value nobody
            recognises decide whether a package looks cleared.

    """
    ranked: list[int] = []
    for membership in memberships:
        rank = _KEV_MEMBERSHIP_RANK.get(membership)
        if rank is None:
            message = (
                f"{membership!r} has no rank in the KEV membership order. The ranked values are "
                f"{sorted(_KEV_MEMBERSHIP_RANK)}; a value from outside this vocabulary cannot be read as an "
                f"absence, because an absence here is a claim that nothing was established."
            )
            raise OutcomeVocabularyError(message)
        ranked.append(rank)
    if not ranked:
        return KEV_NOT_ESTABLISHED
    return KEV_MEMBERSHIP_PRECEDENCE[min(ranked)]


# ---------------------------------------------------------------------------
# `CPM-FR-18`'s licence compliance vocabulary.
#
# A fifth vocabulary, and the one whose central rule is about a single value:
# `allowed` is never a default and never an absence. See the module docstring,
# and `LICENSE_PRECEDENCE` below for where that shows up in the ranking.
#
# **Its order is invisible to `tests/unit/django_apps/test_single_ordering_audit.py`**
# for the reason `VULNERABILITY_PRECEDENCE`'s is: that detector reads a literal
# holding *two or more* `OutcomeState` member references, and this one ranks
# exactly one sentinel. That is a property of the vocabulary rather than of how
# the tuple is spelled -- there is no second sentinel this reduction can meet --
# so the order is pinned by name and by contents in
# `tests/unit/django_apps/test_licence_policy.py` instead, and recorded in that
# audit's own table in prose.
# ---------------------------------------------------------------------------

#: The verdict for a licence a rule names and permits, declared once as the
#: `(member name, value)` pair `outcome_type` takes.
#:
#: A pair rather than a member reference, on exactly the terms `CURRENT_MEMBER`
#: is one: the composed type below is built from it and `ALLOWED` is read back
#: out of it, so a second spelling of `"allowed"` anywhere would be a value that
#: could drift from the one the column actually offers.
#:
#: **This is the one value in this repository that must never be reached by
#: absence.** `CPM-SECURITY-S03`'s AC 2 already promised that an unrecognised
#: licence "records `unknown` and routes to manual review, never `allowed`", and
#: `CPM-SM-2` measures this product on zero findings presenting an unknown as
#: clean. Nothing derives it from a missing rule set, an unmatched expression, a
#: blank expression or a sentinel evidence row: it comes from a rule whose
#: recorded disposition is this string, and `policies/models.py` requires the row
#: to name that rule.
ALLOWED_MEMBER: Final[tuple[str, str]] = ("ALLOWED", "allowed")

#: The verdict for a licence a rule names and permits subject to conditions --
#: attribution, source disclosure, a notice file. Determinate and adverse: a
#: reviewer has work to do, and the row names the rule that says so.
RESTRICTED_MEMBER: Final[tuple[str, str]] = ("RESTRICTED", "restricted")

#: The verdict for a licence a rule names and refuses. The worst thing this
#: vocabulary can say, and the only one that is a decision rather than a
#: question.
FORBIDDEN_MEMBER: Final[tuple[str, str]] = ("FORBIDDEN", "forbidden")

#: The verdict for a licence this run *established* and no rule names.
#:
#: **Distinct from `unknown`, and the distinction is the whole reason both
#: exist.** `unknown` means the licence itself was never established -- the
#: channel stated none, stated one this product will not normalize, or could not
#: be read -- or no monitored channel serves the package at all.
#: `manual_review` means the licence is
#: known and this product has no rule for it, which includes the shipped state in
#: which no rule set has been recorded at all. Collapsing them would hide which
#: of the two a reviewer is being asked to fix: one is a gap in the *evidence*
#: and the other is a gap in the *policy*.
MANUAL_REVIEW_MEMBER: Final[tuple[str, str]] = ("MANUAL_REVIEW", "manual_review")

#: The per-package licence vocabulary: `core`'s four sentinels plus
#: `CPM-FR-18`'s four determinate outcomes.
#:
#: Named `PackageLicenseOutcome` and not `LicenseOutcome`, because
#: `collectors/outcomes.py` already owns that name for what a *finding* records.
#: The two are different vocabularies about different subjects -- one row per
#: channel there, one value per package here -- and a shared name would make
#: "which of them does this column hold" a question about imports. It is the same
#: split `PackageVulnerabilityOutcome` makes one domain over.
#:
#: `CPM-FR-18` names five outcomes and this type carries eight values, which is
#: not a disagreement: the five are `allowed`, `restricted`, `forbidden`,
#: `unknown` and `manual_review`, and `unknown` arrives as one of the four
#: sentinels `outcome_type` supplies by construction. `error`, `not_found` and
#: `not_applicable` come with it and this pass produces none of them, on exactly
#: the terms `FEEDSTOCK_NOT_FOUND` is a member `FeedstockPresencePass` never
#: produces.
PackageLicenseOutcome: Final[type[models.TextChoices]] = outcome_type(
    "PackageLicenseOutcome",
    [ALLOWED_MEMBER, RESTRICTED_MEMBER, FORBIDDEN_MEMBER, MANUAL_REVIEW_MEMBER],
)

#: `PackageLicenseOutcome`'s own members, by name, read off the composed type
#: itself, for the reason `_MEMBER_VALUES` above is: the functional enum API
#: makes the members invisible to a type checker, and reaching them *through* the
#: type is what makes a drifted sentinel fail at import rather than silently make
#: every comparison false. A comprehension rather than a literal, which is also
#: what keeps it out of `tests/unit/django_apps/test_single_ordering_audit.py`'s
#: reach.
_LICENSE_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in PackageLicenseOutcome}

#: A recorded rule names this package's licence and permits it. Reachable no
#: other way.
ALLOWED: Final[str] = _LICENSE_MEMBER_VALUES["ALLOWED"]

#: A recorded rule names it and permits it subject to conditions.
RESTRICTED: Final[str] = _LICENSE_MEMBER_VALUES["RESTRICTED"]

#: A recorded rule names it and refuses it.
FORBIDDEN: Final[str] = _LICENSE_MEMBER_VALUES["FORBIDDEN"]

#: The licence is established and no recorded rule names it -- including because
#: the run's policy version records no rule set at all, which is the state this
#: component ships in while PRD Open Question 2 is unanswered.
MANUAL_REVIEW: Final[str] = _LICENSE_MEMBER_VALUES["MANUAL_REVIEW"]

#: The licence itself was never established: no evidence at the cut-off, a
#: channel that stated none, one that stated something this product will not
#: normalize, one that could not be read, or a sweep in which no monitored
#: channel serves the package at all. A *single* channel that does not serve it
#: is not one of these: `policies/licence.py` leaves that channel out of the
#: reduction, because an absence from one channel has not disagreed with what
#: another channel stated.
#:
#: Reached through `PackageLicenseOutcome` rather than through `OutcomeState`, and
#: named apart from the three `UNKNOWN` constants above rather than shared with
#: any of them. They carry the same string -- `verify_sentinels` guarantees it --
#: but a column's default and a column's values must be *its own* choices, and a
#: licence column taking a constant off the currency vocabulary would be the one
#: place this module took a value from a type the field does not declare.
LICENSE_STATUS_UNKNOWN: Final[str] = _LICENSE_MEMBER_VALUES["UNKNOWN"]

#: `core`'s "the look failed", carried in the vocabulary by construction and
#: produced by nothing.
#:
#: **The pass folds an errored finding into `unknown` deliberately**, and
#: `policies/licence.py` argues it: at the finding level `error` says how the run
#: failed, and at the *package* level all it says is that this run established no
#: licence for the package -- which is what `unknown` means. The distinction is
#: not lost, because the row references the finding that carries it and says so
#: in its own `detail`.
LICENSE_STATUS_ERROR: Final[str] = _LICENSE_MEMBER_VALUES["ERROR"]

#: `core`'s informative negative, carried by construction and produced by
#: nothing, on the same terms. On `license_findings` it means a monitored channel
#: does not serve the package at all, which is an absence from that channel
#: rather than a package with no licence.
LICENSE_STATUS_NOT_FOUND: Final[str] = _LICENSE_MEMBER_VALUES["NOT_FOUND"]

#: `core`'s "the question was never ours to ask", carried by construction and
#: produced by nothing: every package a monitored channel could serve is licensed
#: under something, and `license_findings` refuses a row carrying this value
#: outright. Named so the reduction below can refuse it by name rather than by
#: silence.
LICENSE_STATUS_NOT_APPLICABLE: Final[str] = _LICENSE_MEMBER_VALUES["NOT_APPLICABLE"]

#: How wide a column holding one of these values is. `PackageLicenseOutcome`'s
#: longest value is `not_applicable`, fourteen characters, and its longest
#: determinate value is `manual_review`, thirteen; the rest is headroom. Sized
#: like `CURRENCY_STATE_LENGTH` rather than derived from it: five vocabularies,
#: five declarations, each argued from its own longest value.
LICENSE_STATE_LENGTH: Final[int] = 32

#: The three dispositions a recorded rule may state, and therefore the three
#: outcomes reachable only through one.
#:
#: **Not an order.** It is the set of verdicts a reviewer may write in
#: `policies/data/policy-parameters.toml`, read by `policies/parameters.py` to
#: refuse anything else and by `policies/models.py` to require the rule behind
#: such a row. `LICENSE_PRECEDENCE` below is where the ranking lives, and these
#: three are not adjacent in it. A tuple rather than three literals inside those
#: two readers, because a second spelling of the set is a constraint that stops
#: matching what the file accepts. It holds `PackageLicenseOutcome` values and no
#: `OutcomeState` members, so it is not the shape
#: `tests/unit/django_apps/test_single_ordering_audit.py` reads.
#:
#: `manual_review` is deliberately absent: it is what "no rule names this
#: licence" produces, so a rule stating it would be a rule saying nothing. So is
#: every sentinel, for the stronger reason that a rule cannot make a licence
#: un-established.
RULE_DISPOSITIONS: Final[tuple[str, ...]] = (ALLOWED, RESTRICTED, FORBIDDEN)

#: How the verdicts several channels support rank when they are reduced to one
#: package outcome. Worst first, and only five of the eight values are ranked.
#:
#: **Why only five.** `policies/licence.py` produces exactly these: the three a
#: rule can state, the review item a known licence with no rule reaches, and the
#: un-established state. `error`, `not_found` and `not_applicable` are members by
#: construction and are never reached -- the first two are folded into `unknown`
#: where they arrive, and the third is refused by `license_findings` outright.
#: Ranking a value no reduction can meet would be data no function reads, which
#: is the objection `FeedstockOutcome`'s missing order records.
#:
#: **Why the ranks are what they are.**
#:
#: * `forbidden` first, because it is the only established refusal here and the
#:   one an operator acts on. A package one channel says is forbidden must not
#:   report anything milder because a second channel says something else --
#:   "disagreement never resolves upward" is this story's own words for it.
#: * `restricted` second, above the two questions. It is an *established* adverse
#:   finding, on exactly the terms `CURRENCY_PRECEDENCE` puts `behind` above its
#:   un-observed states: a question nobody has answered must not mask a condition
#:   the rules actually stated.
#: * `unknown` third and `manual_review` fourth, in `core`'s own relative order
#:   and for `core`'s own reason: an un-established state hides risk, while a
#:   known licence awaiting a rule is a question whose subject is at least known.
#:   The two never collapse into each other -- they are separate ranks of separate
#:   values, and a package reading `unknown` beside a determinate channel says so
#:   in its `detail`.
#: * `allowed` last, because it is the only verdict that claims nothing is wrong,
#:   and because a reduction must never reach it while any other channel had
#:   something to say.
#:
#: The one sentinel is written as an `OutcomeState` member on purpose, on the
#: terms `CURRENCY_PRECEDENCE` states: it is the same string
#: `LICENSE_STATUS_UNKNOWN` carries, and spelling it this way is what makes the
#: rank *legible* as a sentinel rather than as one more domain token.
LICENSE_PRECEDENCE: Final[tuple[str, ...]] = tuple(
    # `str()` for the reason `CURRENCY_PRECEDENCE` gives: the sentinel is written
    # as an `OutcomeState` member and Django renders a `Choices` member as its
    # value, so the tuple is the plain strings the column holds.
    str(verdict)
    for verdict in (FORBIDDEN, RESTRICTED, OutcomeState.UNKNOWN, MANUAL_REVIEW, ALLOWED)
)

#: Rank by value, so a caller may pass either this vocabulary's own strings or
#: `OutcomeState`'s -- which are the same strings for the sentinel.
_LICENSE_RANK: Final[dict[str, int]] = {value: index for index, value in enumerate(LICENSE_PRECEDENCE)}


def worst_license(verdicts: Iterable[str]) -> str:
    """Reduce several channels' licence verdicts to the one outcome for the package.

    **The reduction can never reach `allowed` unless every verdict it was given
    is `allowed`**, because `allowed` is last in the order and `min` takes the
    worst rank. That is the story's central property expressed as arithmetic
    rather than as a branch: there is no input to this function that produces
    `allowed` from an absence, because an absence is not a verdict at all and the
    empty case answers `unknown`.

    Args:
        verdicts: The per-finding verdicts, as `PackageLicenseOutcome` values.

    Returns:
        The worst verdict among them, by `LICENSE_PRECEDENCE`, and
        `core.outcomes.EMPTY_AGGREGATE`'s value -- `unknown` -- for no verdicts
        at all. The empty case is reachable and is a matrix row of its own: a
        package with no licence evidence at the cut-off has nothing to reduce,
        and the answer is `unknown` rather than clean and emphatically rather
        than `allowed`. Stated here rather than left to whatever `min()` over an
        empty sequence happens to do.

    Raises:
        OutcomeVocabularyError: When a verdict has no rank. That is every value
            this pass never produces -- `error`, `not_found`, `not_applicable` --
            and every string from outside the vocabulary entirely. Refused rather
            than treated as determinate, on exactly the terms
            `core.outcomes.aggregate` refuses one: ranking an unrecognised value
            beside `allowed` would be the `CPM-FR-6` fold arrived at by silence,
            on the one column a compliance reviewer reads first.

    """
    ranked: list[int] = []
    for verdict in verdicts:
        rank = _LICENSE_RANK.get(verdict)
        if rank is None:
            message = (
                f"{verdict!r} has no rank in the licence precedence order. The ranked values are "
                f"{sorted(_LICENSE_RANK)}; every other member of PackageLicenseOutcome is carried by "
                f"construction and produced by nothing, so a verdict outside the five needs its rank decided by "
                f"the story that starts producing it, not inferred here."
            )
            raise OutcomeVocabularyError(message)
        ranked.append(rank)
    if not ranked:
        return EMPTY_AGGREGATE.value
    return LICENSE_PRECEDENCE[min(ranked)]


# ---------------------------------------------------------------------------
# `CPM-FR-41`'s remediation readiness vocabulary, and the per-surface
# availability it is reduced from.
#
# A sixth and a seventh vocabulary, and only one of them is an outcome type.
# `RemediationReadiness` below is the per-package *status* the readiness pass
# derives; `FixAvailability` is not a status at all and is deliberately not built
# from `outcome_type` -- see its own declaration for why three values is the whole
# of it, and why the third is the one this story exists for.
#
# **`READINESS_PRECEDENCE` is invisible to
# `tests/unit/django_apps/test_single_ordering_audit.py`'s detector**, for the
# reason `VULNERABILITY_PRECEDENCE`'s and `LICENSE_PRECEDENCE`'s are: that
# detector reads a literal holding *two or more* `OutcomeState` member references,
# and this one ranks exactly one sentinel (`unknown`) alongside four domain
# verdicts. `not_applicable` is not ranked at all -- it is excluded from the
# reduction, on the terms `worst_currency` excludes it -- so there is no second
# sentinel to spell. That is a property of the vocabulary rather than of how the
# tuple is written, and `tests/unit/django_apps/test_remediation_policy.py` pins
# the order by name and by contents instead.
# ---------------------------------------------------------------------------

#: The determinate verdict for a finding whose fixed version a monitored channel
#: publishes, declared once as the `(member name, value)` pair `outcome_type`
#: takes.
#:
#: A pair rather than a member reference, on exactly the terms `CURRENT_MEMBER`
#: is one: the composed type below is built from it and `READY` is read back out
#: of it, so a second spelling of `"ready"` anywhere would be a value that could
#: drift from the one the column actually offers.
#:
#: **The only value that says a reviewer can act this morning.** `CPM-UJ-1` is
#: about separating work that is available from work that is waiting on somebody
#: else, and the difference is entirely whether the fix is installable now. A
#: fixed version upstream, on PyPI or in a recipe is not: there is nothing to
#: install. So `ready` is reached from the published-package surface and from no
#: other, and `policies/models.py` requires the row to name the channel
#: observation that carries it.
READY_MEMBER: Final[tuple[str, str]] = ("READY", "ready")

#: The determinate verdict for a finding whose fixed version the conda-forge
#: recipe carries and no monitored channel has built yet.
#:
#: Distinct from `ready` because the reviewer's next action differs: a recipe
#: carrying the fix means a build is due, and nothing can be installed until it
#: lands. Distinct from `awaiting_packaging` for the same reason in the other
#: direction: the packaging work is done and only the build is outstanding.
AWAITING_BUILD_MEMBER: Final[tuple[str, str]] = ("AWAITING_BUILD", "awaiting_build")

#: The determinate verdict for a finding whose fixed version exists upstream or
#: on PyPI and has not reached the recipe.
#:
#: The matrix's "released but not yet packaged". One value for two surfaces
#: rather than two, because the reviewer's next action is the same for both -- the
#: recipe has to be updated -- and *which* of them released it is on the row's own
#: per-surface columns rather than folded into the verdict. AC 1 asks where, and
#: the columns are where the answer lives.
AWAITING_PACKAGING_MEMBER: Final[tuple[str, str]] = ("AWAITING_PACKAGING", "awaiting_packaging")

#: The determinate verdict for a finding whose fix is on no surface at all.
#:
#: **This is the value that must never be reached by an absence**, and it is the
#: mirror of `ALLOWED_MEMBER` one vocabulary up. `blocked` means the fixed version
#: was looked for on **every** surface and found on none, or that the advisory
#: itself established there is no fix to look for. A surface that was not read is
#: not a surface where the fix is absent: `FixAvailability.NOT_READ` is the value
#: that keeps those two apart, `policies/remediation.py` reaches `blocked` only
#: from four `not_published` readings, and `policies/models.py` puts a database
#: check constraint behind it so a row claiming it while naming an unread surface
#: is refused by PostgreSQL rather than merely avoided here.
BLOCKED_MEMBER: Final[tuple[str, str]] = ("BLOCKED", "blocked")

#: The per-package remediation readiness vocabulary: `core`'s four sentinels plus
#: `CPM-FR-41`'s four determinate verdicts.
#:
#: Named `RemediationReadiness` rather than `ReadinessOutcome`, because
#: "readiness" alone is what `config/` already calls an HTTP probe and what
#: `docs/deployment.md` has a whole section about. The two are unrelated and a
#: shared name would make "which readiness does this mean" a question about
#: imports.
RemediationReadiness: Final[type[models.TextChoices]] = outcome_type(
    "RemediationReadiness",
    [READY_MEMBER, AWAITING_BUILD_MEMBER, AWAITING_PACKAGING_MEMBER, BLOCKED_MEMBER],
)

#: `RemediationReadiness`'s own members, by name, read off the composed type
#: itself, for the reason `_MEMBER_VALUES` above is: the functional enum API makes
#: the members invisible to a type checker, and reaching them *through* the type
#: is what makes a drifted sentinel fail at import rather than silently make every
#: comparison false. A comprehension rather than a literal, which is also what
#: keeps it out of `tests/unit/django_apps/test_single_ordering_audit.py`'s reach.
_READINESS_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in RemediationReadiness}

#: A monitored channel publishes the fixed version. The reviewer can act now.
READY: Final[str] = _READINESS_MEMBER_VALUES["READY"]

#: The recipe carries the fixed version and no monitored channel has built it.
AWAITING_BUILD: Final[str] = _READINESS_MEMBER_VALUES["AWAITING_BUILD"]

#: The fixed version exists upstream or on PyPI and has not reached the recipe.
AWAITING_PACKAGING: Final[str] = _READINESS_MEMBER_VALUES["AWAITING_PACKAGING"]

#: Every surface was read and none carries the fixed version -- or the advisory
#: established that there is no fixed version at all. Never reached from a surface
#: nobody read.
BLOCKED: Final[str] = _READINESS_MEMBER_VALUES["BLOCKED"]

#: This run established nothing about whether the finding can be acted on: no
#: advisory evidence at the cut-off, advisory evidence past its own freshness
#: target, an advisory whose recorded fix cannot be compared without
#: version-ordering semantics this product has not decided -- no architecture
#: decision owns version ordering -- or a fix that at least one surface was never
#: asked about, which since `CPM-SECURITY-S06`'s review includes every surface
#: that stated some other version.
#:
#: Reached through `RemediationReadiness` rather than through `OutcomeState`, and
#: named apart from the four `UNKNOWN` constants above rather than shared with any
#: of them. They carry the same string -- `verify_sentinels` guarantees it -- but a
#: column's default and a column's values must be *its own* choices, and a
#: readiness column taking a constant off the currency vocabulary would be the one
#: place this module took a value from a type the field does not declare.
READINESS_UNKNOWN: Final[str] = _READINESS_MEMBER_VALUES["UNKNOWN"]

#: `core`'s "the look failed", carried in the vocabulary by construction and
#: produced by nothing. An unreadable advisory or surface row makes the readiness
#: `unknown` and the row says so in its own `detail`: at the *package* level, a
#: read that failed means this run established nothing about whether the finding
#: can be acted on, which is what `unknown` means.
READINESS_ERROR: Final[str] = _READINESS_MEMBER_VALUES["ERROR"]

#: `core`'s informative negative, carried by construction and produced by nothing.
#: A surface answering that it has no version for this package has not said the
#: fix is absent -- it has said nothing about the fix -- so it reads
#: `FixAvailability.NOT_READ` and never reaches this column.
READINESS_NOT_FOUND: Final[str] = _READINESS_MEMBER_VALUES["NOT_FOUND"]

#: The readiness question is not this package's: this run matched no advisory to
#: it, so there is no finding to be ready for.
#:
#: **Produced, and deliberately not `unknown`.** `CPM-FR-6` forbids folding a
#: check that does not apply into clean or unknown, and "there is nothing to
#: remediate" is a different fact from "we could not tell whether there is". It is
#: also emphatically not a claim that the package is clean: whether this run
#: *established* that is `package_vulnerability`'s verdict, which this pass reads
#: nothing from and restates nowhere.
READINESS_NOT_APPLICABLE: Final[str] = _READINESS_MEMBER_VALUES["NOT_APPLICABLE"]

#: How wide a column holding one of these values is. `RemediationReadiness`'s
#: longest value is `awaiting_packaging`, eighteen characters, and its longest
#: sentinel is `not_applicable`, fourteen; the rest is headroom. Sized like
#: `CURRENCY_STATE_LENGTH` rather than derived from it: six vocabularies, six
#: declarations, each argued from its own longest value.
READINESS_STATE_LENGTH: Final[int] = 32

#: How the verdicts several findings support rank when they are reduced to one
#: package readiness. Worst first, and only five of the eight values are ranked.
#:
#: **Why only five.** `policies/remediation.py` produces exactly these: the four
#: `CPM-FR-41` names, plus the un-established state. `error` and `not_found` are
#: members by construction and are never reached, and `not_applicable` is decided
#: before there is anything to reduce -- a package with no matched advisory has no
#: per-finding verdicts at all -- so it is excluded from this order rather than
#: ranked, on exactly the terms `CURRENCY_PRECEDENCE` excludes its own. Ranking a
#: value no reduction can meet would be data no function reads, which is the
#: objection `FeedstockOutcome`'s missing order records.
#:
#: **Why the ranks are what they are.** "A package is only as actionable as its
#: worst finding" is the story's own words, so the order runs from least
#: actionable to most.
#:
#: * `blocked` first, because it is the least actionable thing this vocabulary
#:   can say and it is an *established* adverse finding. A package with one
#:   finding whose fix exists nowhere and one whose fix is on a channel is not a
#:   package a reviewer can finish this morning, and reporting the milder verdict
#:   would drop the blocked finding out of the queue `CPM-UJ-1` opens with.
#: * `unknown` second, above the three that say where the fix is. An un-established
#:   state hides risk, on exactly the terms `CURRENCY_PRECEDENCE` puts its own
#:   un-observed states above `current`; and it must not mask `blocked`, which is
#:   why it sits below it rather than above.
#: * `awaiting_packaging`, then `awaiting_build`, then `ready` -- the three
#:   determinate verdicts in order of how much work is left before a reviewer can
#:   install anything. `ready` is last because it is the only verdict that says
#:   the work is available now, so a reduction cannot reach it while any finding
#:   said anything else.
#:
#: The one sentinel is written as an `OutcomeState` member on purpose, on the
#: terms `CURRENCY_PRECEDENCE` states: it is the same string `READINESS_UNKNOWN`
#: carries, and spelling it this way is what makes the rank *legible* as a
#: sentinel rather than as one more domain token.
READINESS_PRECEDENCE: Final[tuple[str, ...]] = tuple(
    # `str()` for the reason `CURRENCY_PRECEDENCE` gives: the sentinel is written
    # as an `OutcomeState` member and Django renders a `Choices` member as its
    # value, so the tuple is the plain strings the column holds.
    str(verdict)
    for verdict in (BLOCKED, OutcomeState.UNKNOWN, AWAITING_PACKAGING, AWAITING_BUILD, READY)
)

#: Rank by value, so a caller may pass either this vocabulary's own strings or
#: `OutcomeState`'s -- which are the same strings for the sentinel.
_READINESS_RANK: Final[dict[str, int]] = {value: index for index, value in enumerate(READINESS_PRECEDENCE)}


def worst_readiness(verdicts: Iterable[str]) -> str:
    """Reduce several findings' readiness verdicts to the one readiness for the package.

    **The reduction can never reach `ready` unless every verdict it was given is
    `ready`**, because `ready` is last in the order and `min` takes the worst
    rank. **`blocked` is the mirror of that and not a second guarantee of it**:
    it is rank 0, so a *single* `blocked` finding makes the package `blocked`
    however many of its siblings are `ready`. That is the intended arithmetic --
    a package with one unfixable finding is not a package a reviewer can finish --
    and this docstring said the inverse of it for a while, which is worse than
    saying nothing: a false safety claim in the place a reviewer checks reads as
    the property holding.

    Where the property this story turns on is actually held is one level down, in
    `policies/remediation.py`: a finding whose surfaces were not all read never
    reaches `blocked` in the first place, so there is no such verdict for this
    reduction to propagate.

    Args:
        verdicts: The per-finding verdicts, as `RemediationReadiness` values.

    Returns:
        The worst verdict among them, by `READINESS_PRECEDENCE`, and
        `core.outcomes.EMPTY_AGGREGATE`'s value -- `unknown` -- for no verdicts at
        all. The empty case is unreachable from `RemediationPass`, which decides
        `not_applicable` before there is nothing to reduce, and is stated here
        rather than left to whatever `min()` over an empty sequence happens to do.

    Raises:
        OutcomeVocabularyError: When a verdict has no rank. That is every value
            this pass never produces -- `error` and `not_found` -- plus
            `not_applicable`, which is decided before the reduction rather than
            ranked inside it, and every string from outside the vocabulary
            entirely. Refused rather than treated as determinate, on exactly the
            terms `core.outcomes.aggregate` refuses one: ranking an unrecognised
            value beside `blocked` would be the `CPM-FR-6` fold arrived at by
            silence, on the one column that tells a reviewer whether to stop
            looking.

    """
    ranked: list[int] = []
    for verdict in verdicts:
        rank = _READINESS_RANK.get(verdict)
        if rank is None:
            message = (
                f"{verdict!r} has no rank in the remediation readiness order. The ranked values are "
                f"{sorted(_READINESS_RANK)}; {READINESS_NOT_APPLICABLE!r} is decided before the reduction "
                f"rather than ranked inside it, and every other member of RemediationReadiness is carried by "
                f"construction and produced by nothing, so a verdict outside the five needs its rank decided by "
                f"the story that starts producing it, not inferred here."
            )
            raise OutcomeVocabularyError(message)
        ranked.append(rank)
    if not ranked:
        return EMPTY_AGGREGATE.value
    return READINESS_PRECEDENCE[min(ranked)]


class FixAvailability(models.TextChoices):
    """Whether one version surface carries the fixed version a finding names.

    **Three values, and the third is the whole reason this type exists.** A
    surface either states the fixed version, states a version that is not it, or
    was never read -- and collapsing the third into the second is what produces a
    false `blocked`. `CPM-SECURITY-S04`'s `KevMembership` needed exactly this
    distinction and is the precedent: recording a package the KEV collector never
    ran for as `not_listed` would claim an absence the run never established, and
    recording a surface nobody read as one where the fix is absent is the same
    claim about a different subject.

    `not_read` covers every way a surface can fail to answer: no observation at
    the run's cut-off, an observation carrying any of `core`'s four sentinels, an
    observation that states no version at all, and an observation whose evidence is
    past its collector's declared freshness target (`CPM-FR-38`) and is therefore
    not relied on. Each of those is a surface this run did not get a current answer
    from, and none of them is a statement that the fix is absent from it.

    **Deliberately not built from `outcome_type`, and deliberately not named for a
    status.** This is not one of `CPM-AD-5`'s derived statuses: it records what one
    surface carries, the way `KevMembership` records a membership and
    `AuthorityOrderSource` records a provenance. The four sentinels an outcome type
    supplies would be four more ways of spelling `not_read` on a column whose whole
    point is that there is exactly one. The columns that hold it are named
    `*_fix` for the same reason `kev_membership` is not `kev_status` --
    `tests/unit/django_apps/test_outcome_field_audit.py` recognises a derived
    status by name, and a name ending `_status` would put these columns under a
    rule that would then demand the four sentinels they must not offer.

    **It declares no precedence and ranks nothing.** The four surfaces are not
    reduced to one availability: `RemediationReadiness` is what a reviewer reads,
    and which surface produced it is a fixed consultation order declared in
    `policies/remediation.py` beside the verdicts it names, not a ranking of these
    three values against each other. The day a story reduces several surfaces'
    availabilities to one availability, that story declares the order.
    """

    PUBLISHED = "published"
    NOT_PUBLISHED = "not_published"
    NOT_READ = "not_read"


#: How wide a column holding one of these values is. `not_published` is thirteen
#: characters; the rest is headroom, on the terms every width in this module is
#: argued.
FIX_AVAILABILITY_LENGTH: Final[int] = 32

#: This surface states the fixed version the finding names.
FIX_PUBLISHED: Final[str] = FixAvailability.PUBLISHED.value

#: This surface was read, states a version, and it is not the fixed version. The
#: only value that may vote towards `blocked`.
FIX_NOT_PUBLISHED: Final[str] = FixAvailability.NOT_PUBLISHED.value

#: This surface was not read, or its answer is not one this run relies on. Never
#: a statement that the fix is absent, which is the defect this vocabulary exists
#: to prevent.
SURFACE_NOT_READ: Final[str] = FixAvailability.NOT_READ.value


#: The determinate verdict for a package a build and an import actually
#: succeeded for, declared once as the `(member name, value)` pair `outcome_type`
#: takes.
#:
#: **The value names the evidence type, and that is `CPM-FR-19` made
#: structural.** The requirement is that "a readiness claim states which evidence
#: type produced it", and `CPM-AD-24` carries a state's value verbatim onto every
#: read surface -- so a queue rendering this column alone must still be unable to
#: mistake proof for inference. `verified_ready` beside `inferred_ready` says it
#: in the one string a surface is guaranteed to show. The `evidence_type` column
#: beside it carries the same fact where a query can filter on it; it is the
#: second half of AC 1 and never a substitute for this half.
#:
#: `ready` rather than `compatible`, and the difference is which question is being
#: answered. `collectors/outcomes.py`'s values say what the *evidence* found --
#: metadata admits this Python, a build came out. This says what the *product*
#: concludes about the package, which is a verdict only a policy may reach
#: (`CPM-AD-8`). Two vocabularies, two registers, and a reader holding a row from
#: each can see which is which.
VERIFIED_READY_MEMBER: Final[tuple[str, str]] = ("VERIFIED_READY", "verified_ready")

#: The determinate verdict for a package whose verification ran and did not
#: produce a working build.
#:
#: **This is where a policy may say what the collector could not.**
#: `collectors/outcomes.py` refuses `verified_incompatible` and records
#: `verification_failed` instead, because a build fails for reasons that are not
#: the interpreter and a collector may not reach a verdict at all (`CPM-AD-8`).
#: A *policy* may: "this package is not ready" is a conclusion about the package
#: drawn from the best evidence there is, which is exactly what a policy pass
#: exists to do. It is still not a claim that the package can never work -- the
#: row cites the verification, which names the one platform it ran on, and a
#: later build on a later day is a new row.
VERIFIED_NOT_READY_MEMBER: Final[tuple[str, str]] = ("VERIFIED_NOT_READY", "verified_not_ready")

#: The determinate verdict for a package whose published metadata admits the
#: assessed Python and which nobody has built.
#:
#: The weaker of the two positive verdicts, and the prefix is what says so. A
#: reader who sees only this value knows that no build has been run, which is the
#: whole of what `CPM-EP-PY314` exists to keep visible.
INFERRED_READY_MEMBER: Final[tuple[str, str]] = ("INFERRED_READY", "inferred_ready")

#: The determinate verdict for a package whose published metadata cannot admit the
#: assessed Python and which nobody has built.
#:
#: An inference from a claim the project published, on the terms
#: `collectors/outcomes.py`'s `inferred_incompatible` states: a project whose
#: specifier excludes this Python today may well build under it, and the prefix is
#: what stops this reading as proof that it does not.
INFERRED_NOT_READY_MEMBER: Final[tuple[str, str]] = ("INFERRED_NOT_READY", "inferred_not_ready")

#: `CPM-FR-19`'s vocabulary: `core`'s four sentinels plus the four verdicts, one
#: per (evidence type, answer) pair.
#:
#: **Four determinate members and not two.** Collapsing the pairs into `ready` and
#: `not_ready` with the evidence type carried only in a neighbouring column was the
#: alternative, and it fails the one requirement this story has: `CPM-AD-24`
#: renders a value verbatim, so any surface that projected the status without
#: joining the second column would show `ready` for a package nobody has ever
#: built. The redundancy between this value and `evidence_type` is deliberate and
#: is the point.
PackagePythonReadinessOutcome: Final[type[models.TextChoices]] = outcome_type(
    "PackagePythonReadinessOutcome",
    [VERIFIED_READY_MEMBER, VERIFIED_NOT_READY_MEMBER, INFERRED_READY_MEMBER, INFERRED_NOT_READY_MEMBER],
)

#: `PackagePythonReadinessOutcome`'s own members, by name, read off the composed
#: type itself for the reason `_MEMBER_VALUES` above is read off its own.
_PY314_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in PackagePythonReadinessOutcome}

#: A build and an import of this package succeeded under the assessed Python.
VERIFIED_READY: Final[str] = _PY314_MEMBER_VALUES["VERIFIED_READY"]

#: Verification ran for this package and did not produce a working build.
VERIFIED_NOT_READY: Final[str] = _PY314_MEMBER_VALUES["VERIFIED_NOT_READY"]

#: The package's published metadata admits the assessed Python, and nobody has
#: built it.
INFERRED_READY: Final[str] = _PY314_MEMBER_VALUES["INFERRED_READY"]

#: The package's published metadata cannot admit the assessed Python, and nobody
#: has built it.
INFERRED_NOT_READY: Final[str] = _PY314_MEMBER_VALUES["INFERRED_NOT_READY"]

#: Nothing was established about this package's readiness -- and in a real
#: inventory this is most of it, on purpose.
#:
#: Six things reach it and `detail` says which: no evidence of either kind at the
#: cut-off; evidence that established nothing; a look that failed; a source that
#: reported the package absent; evidence older than the collector's declared
#: freshness target; and evidence about a different Python series. **None of them
#: is a statement that the package is not ready**, and reading any of them as one
#: is the defect class both preceding stories in this epic were written against.
PY314_READINESS_UNKNOWN: Final[str] = _PY314_MEMBER_VALUES["UNKNOWN"]

#: Reserved by the composed vocabulary and produced by nothing. A *look* that
#: failed is the collector's `error`, and this pass records that as
#: `PY314_READINESS_UNKNOWN` with the reason: a policy that could not read its
#: evidence has established nothing, which is what `unknown` already means. Kept in
#: the vocabulary by construction so the column's choices are `core`'s complete
#: sentinel set.
PY314_READINESS_ERROR: Final[str] = _PY314_MEMBER_VALUES["ERROR"]

#: Reserved on the same terms. "The release ecosystem does not know this package"
#: is an evidence-level absence; what this pass concludes from it is that nothing
#: was established, which is `unknown`.
PY314_READINESS_NOT_FOUND: Final[str] = _PY314_MEMBER_VALUES["NOT_FOUND"]

#: `core`'s "the question was never ours to ask", and this vocabulary really does
#: hold it.
#:
#: One path to it, inherited whole from `CPM-PY314-S01`: `identity` recorded the
#: package's release-ecosystem mapping as `not_applicable`, so there is no Python
#: metadata to assess and no artifact to build. Evidence that is `unknown`,
#: `error` or `not_found` establishes **nothing** and never reaches this value.
PY314_READINESS_NOT_APPLICABLE: Final[str] = _PY314_MEMBER_VALUES["NOT_APPLICABLE"]

#: How wide a column holding one of these values is. `verified_not_ready` is
#: eighteen characters and `not_applicable` fourteen; the rest is headroom, on the
#: terms every width in this module is argued.
PY314_READINESS_STATE_LENGTH: Final[int] = 32

#: The two verdicts a *verification* produces, and the two an *assessment*
#: produces, as the sets the derived table's constraints are written against.
#:
#: Built by comprehension over the member pairs rather than written as literals,
#: for the reason `_PY314_MEMBER_VALUES` is: a member renamed on one side and not
#: the other fails at import rather than silently making a constraint vacuous. It
#: also keeps them out of `tests/unit/django_apps/test_single_ordering_audit.py`'s
#: reach -- these are membership sets with no order in them, and this module's one
#: ordering decision remains `CURRENCY_PRECEDENCE`.
PY314_VERIFIED_VERDICTS: Final[tuple[str, ...]] = tuple(
    value for _name, value in (VERIFIED_READY_MEMBER, VERIFIED_NOT_READY_MEMBER)
)
PY314_INFERRED_VERDICTS: Final[tuple[str, ...]] = tuple(
    value for _name, value in (INFERRED_READY_MEMBER, INFERRED_NOT_READY_MEMBER)
)

#: Every verdict this pass reaches from evidence, which is the complement of the
#: rows whose evidence type is `none`.
PY314_DECIDED_VERDICTS: Final[tuple[str, ...]] = PY314_VERIFIED_VERDICTS + PY314_INFERRED_VERDICTS


class ReadinessEvidence(models.TextChoices):
    """Which kind of evidence produced a readiness verdict. `CPM-FR-19`'s AC 1, as a column.

    **A plain `TextChoices` and not a composed outcome type**, on the terms
    `KevMembership` and `FixAvailability` state: this is not a *status* and it
    holds no sentinel. `error`, `not_found` and `not_applicable` are things that
    happen to evidence; this column answers a different question -- which kind of
    evidence the verdict in the neighbouring column rests on -- and a run that
    established nothing answers it with `none` rather than with a sentinel
    borrowed from a vocabulary it is not drawn from.

    **`none` is a value and never `NULL`.** A nullable column would make "no
    evidence produced this verdict" indistinguishable from "this column was never
    written", which is the same absence-read-as-answer confusion the whole epic is
    written against -- and every row this pass writes has an answer to this
    question, including the rows about packages nobody has looked at.

    **It declares no order.** Verified outranking inferred is a rule
    `policies/py314_readiness.py` applies to two named sources, written as a branch
    a reader can follow; an order declared here would be data nothing reads, which
    the next reader would take for a ranking this product applies somewhere.
    """

    VERIFIED = "verified"
    INFERRED = "inferred"
    NONE = "none"


#: How wide a column holding one of these values is. `inferred` is eight
#: characters; the rest is headroom, on the terms every width in this module is
#: argued.
EVIDENCE_TYPE_LENGTH: Final[int] = 32

#: An execution produced this verdict: a build and an import were run and the row
#: cites the result.
EVIDENCE_VERIFIED: Final[str] = ReadinessEvidence.VERIFIED.value

#: Published metadata produced this verdict, and no build was run.
EVIDENCE_INFERRED: Final[str] = ReadinessEvidence.INFERRED.value

#: Nothing produced this verdict. Never a statement about the package -- only
#: about what this product has looked at.
EVIDENCE_NONE: Final[str] = ReadinessEvidence.NONE.value


#: `CPM-FR-20`'s ten priority buckets, worst first, as the `(member name, value)`
#: pairs `outcome_type` takes.
#:
#: **Built by comprehension rather than written out ten times.** The names and the
#: values are the same ten strings in two shapes, and writing them out would be
#: twenty literals that can disagree by one character. `P1` through `P10`, in
#: numeric order, which is also the order they rank in -- and a range is what makes
#: "ten buckets" a fact a reader can check rather than a list they have to count.
#:
#: **A composed type rather than a bare `TextChoices`, and the reason is the
#: rollup.** `core/confidence.py`'s gate writes `OutcomeState.UNKNOWN.value` into
#: every contributed rollup column for a package whose identity was never
#: established (`CPM-AD-4`), and `core/policy_run.py` refuses a value outside the
#: column's own choices. A ten-value bucket vocabulary with no `unknown` would make
#: the gate write a value its own column does not offer -- so the four sentinels
#: are not decoration here, they are what lets this column be gated at all.
_BUCKET_COUNT: Final[int] = 10
PRIORITY_BUCKET_MEMBERS: Final[tuple[tuple[str, str], ...]] = tuple(
    (f"P{number}", f"p{number}") for number in range(1, _BUCKET_COUNT + 1)
)

#: The priority vocabulary: `core`'s four sentinels plus the ten buckets.
PriorityBucket: Final[type[models.TextChoices]] = outcome_type(
    "PriorityBucket",
    list(PRIORITY_BUCKET_MEMBERS),
)

#: `PriorityBucket`'s own members, by name, read off the composed type itself for
#: the reason `_MEMBER_VALUES` above is read off its own.
_PRIORITY_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in PriorityBucket}

#: The ten buckets, worst first, as the values a rule may name and the order a
#: derived rank reads them in.
#:
#: An order, and this module's second one -- `CURRENCY_PRECEDENCE` is the first.
#: It is declared here rather than in the pass because it is the *vocabulary's*
#: order: `P1` outranking `P2` is what the names mean, not a reduction this
#: product chose, and a pass that declared it would be one place a later reader
#: could reasonably declare it differently.
#:
#: Built from the member pairs rather than from the type's `values`, because the
#: type carries the four sentinels first and they are not buckets. Nothing here
#: ranks a sentinel: a package with no bucket is not ranked *below* `P10`, it is
#: not in the ranking at all, which the pass's ordering states.
PRIORITY_BUCKETS: Final[tuple[str, ...]] = tuple(value for _name, value in PRIORITY_BUCKET_MEMBERS)

#: The run established no bucket for this package. Six things reach it and the row
#: says which: the version records no rule set, the rule set is empty, no rule
#: matched, the package's identity was never established (the rollup's gate), or
#: an earlier pass left the package with no derived row for a domain a rule
#: required.
#:
#: **Never `P10`.** A default bucket is a claim about a package's importance that
#: nobody made, and `P10` is the one that would look harmless -- a package nobody
#: has prioritised is not a package somebody decided is unimportant.
PRIORITY_STATUS_UNKNOWN: Final[str] = _PRIORITY_MEMBER_VALUES["UNKNOWN"]

#: Reserved by the composed vocabulary and produced by nothing: this pass reads
#: rows another pass already wrote and an inventory snapshot, so there is no look
#: to fail. Kept in the vocabulary by construction, which is what makes the column
#: gateable.
PRIORITY_STATUS_ERROR: Final[str] = _PRIORITY_MEMBER_VALUES["ERROR"]

#: Reserved on the same terms.
PRIORITY_STATUS_NOT_FOUND: Final[str] = _PRIORITY_MEMBER_VALUES["NOT_FOUND"]

#: Reserved on the same terms. Priority applies to every package in the inventory
#: -- that is what an inventory is -- so nothing here answers that the question was
#: never ours to ask.
PRIORITY_STATUS_NOT_APPLICABLE: Final[str] = _PRIORITY_MEMBER_VALUES["NOT_APPLICABLE"]

#: How wide a column holding one of these values is. `not_applicable` is fourteen
#: characters and `p10` is three; the rest is headroom, on the terms every width in
#: this module is argued.
PRIORITY_BUCKET_LENGTH: Final[int] = 32


#: `CPM-FR-21`'s closed work-type set, as the `(member name, value)` pairs
#: `outcome_type` takes, in the order PRD Appendix A.1 lists them.
#:
#: **Eight values, and the set is closed by the PRD rather than by this
#: component.** This is the one vocabulary in this module whose *content* was
#: decided somewhere else: Appendix A.1 names all eight, so nothing here is a
#: judgement about what work exists -- only about which of them a package's state
#: recommends, which `policies/work_type.py` owns and argues.
#:
#: Written out in the PRD's own order rather than in the order they are matched.
#: The matching order is `WORK_TYPE_PRECEDENCE` below and is a decision this
#: component makes; this is a transcription, and keeping the two apart is what
#: lets a reader check the transcription against the PRD without also having to
#: agree with the ranking.
WORK_TYPE_MEMBERS: Final[tuple[tuple[str, str], ...]] = (
    ("FIX_VULNERABILITY", "fix_vulnerability"),
    ("CREATE_RECIPE", "create_recipe"),
    ("FILE_TRACKING_ISSUE", "file_tracking_issue"),
    ("ALREADY_TRACKED", "already_tracked"),
    ("UPDATE_FEEDSTOCK", "update_feedstock"),
    ("VALIDATE_PYTHON_314", "validate_python_314"),
    ("REVIEW_LICENSE", "review_license"),
    ("RESOLVE_IDENTITY", "resolve_identity"),
)

#: The work-type vocabulary: `core`'s four sentinels plus the closed set of eight.
#:
#: **A composed type rather than a bare `TextChoices`**, on exactly the terms
#: `PriorityBucket` states: `core/confidence.py`'s gate writes
#: `OutcomeState.UNKNOWN.value` into every contributed rollup column for an
#: unmapped package, and `core/policy_run.py` refuses a value the column does not
#: offer. `CPM-FR-21`'s eight are the values a *derivation* may reach; the
#: sentinels are what the column has to hold besides.
WorkType: Final[type[models.TextChoices]] = outcome_type("WorkType", list(WORK_TYPE_MEMBERS))

#: `WorkType`'s own members, by name, read off the composed type itself for the
#: reason `_MEMBER_VALUES` above is read off its own.
_WORK_TYPE_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in WorkType}

#: The eight `CPM-FR-21` names, as the set a derived row is held to.
#:
#: Built from the member pairs rather than from the type's `values`, because the
#: type carries the four sentinels first and they are not work types: a package
#: with nothing to recommend has no work type, which is not the same as being
#: recommended a sentinel.
WORK_TYPES: Final[tuple[str, ...]] = tuple(value for _name, value in WORK_TYPE_MEMBERS)

#: An advisory matched this package and something has to be done about it.
FIX_VULNERABILITY: Final[str] = _WORK_TYPE_MEMBER_VALUES["FIX_VULNERABILITY"]

#: No conda-forge feedstock exists for this package, so one has to be written.
CREATE_RECIPE: Final[str] = _WORK_TYPE_MEMBER_VALUES["CREATE_RECIPE"]

#: Something about this package needs a human record that does not exist yet.
FILE_TRACKING_ISSUE: Final[str] = _WORK_TYPE_MEMBER_VALUES["FILE_TRACKING_ISSUE"]

#: A record already exists and the work is somebody else's to progress.
#:
#: **Unreachable today, and the vocabulary keeps it anyway.** Knowing that a
#: package is already tracked means reading the workflow queue, which `CPM-AD-22`
#: gives to a `workflow` application `CPM-EP-APP` has not built. Nothing this
#: product currently records distinguishes "nobody has filed this" from "somebody
#: has", so no derivation may claim the second. `CPM-FR-21` requires the value to
#: exist and to be distinct from the other seven, and the day the queue exists the
#: value and the closed-set rule that guards it are already in place --
#: `policies/work_type.py` says so where a reader will look, and
#: `CPM-PRIORITY-S02` records it as deferred work. A value defined and unreachable,
#: with the gap recorded, is the honest shipping state; a value reached by a guess
#: is not.
ALREADY_TRACKED: Final[str] = _WORK_TYPE_MEMBER_VALUES["ALREADY_TRACKED"]

#: A feedstock exists and needs work -- it is behind, or nobody is pushing to it.
UPDATE_FEEDSTOCK: Final[str] = _WORK_TYPE_MEMBER_VALUES["UPDATE_FEEDSTOCK"]

#: This package's Python 3.14 readiness has not been proved and somebody should
#: prove it.
VALIDATE_PYTHON_314: Final[str] = _WORK_TYPE_MEMBER_VALUES["VALIDATE_PYTHON_314"]

#: This package's licence needs a human decision.
REVIEW_LICENSE: Final[str] = _WORK_TYPE_MEMBER_VALUES["REVIEW_LICENSE"]

#: This product cannot say what this package is, so nothing else about it can be
#: acted on.
RESOLVE_IDENTITY: Final[str] = _WORK_TYPE_MEMBER_VALUES["RESOLVE_IDENTITY"]

#: No work type was derived. Two things reach it and `detail` says which: nothing
#: this run established recommends any of the eight, or the package's identity was
#: never established and the rollup's gate replaced whatever was derived.
#:
#: **It is not "nothing to do".** `CPM-FR-21`'s closed set offers no member for a
#: package in good order, so a package with nothing to act on and a package nothing
#: is known about both land here -- which `CPM-PRIORITY-S02` records as deferred
#: work rather than resolving by inventing a ninth value the PRD does not name.
WORK_TYPE_UNKNOWN: Final[str] = _WORK_TYPE_MEMBER_VALUES["UNKNOWN"]

#: Reserved by the composed vocabulary and produced by nothing: this pass reads
#: rows other passes already wrote, so there is no look to fail.
WORK_TYPE_ERROR: Final[str] = _WORK_TYPE_MEMBER_VALUES["ERROR"]

#: Reserved on the same terms.
WORK_TYPE_NOT_FOUND: Final[str] = _WORK_TYPE_MEMBER_VALUES["NOT_FOUND"]

#: Reserved on the same terms: a work type applies to every package in the
#: inventory, so nothing here answers that the question was never ours to ask.
WORK_TYPE_NOT_APPLICABLE: Final[str] = _WORK_TYPE_MEMBER_VALUES["NOT_APPLICABLE"]

#: How wide a column holding one of these values is. `validate_python_314` is
#: nineteen characters, the longest in either half of the vocabulary; the rest is
#: headroom, on the terms every width in this module is argued.
WORK_TYPE_LENGTH: Final[int] = 32
