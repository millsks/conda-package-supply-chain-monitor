"""The policy verdict vocabularies, in a leaf module that imports one thing.

Four vocabularies live here: `CurrencyOutcome` (`CPM-CURRENCY-S06`),
`FeedstockOutcome` (`CPM-CURRENCY-S07`), and `CPM-SECURITY-S04`'s
`PackageVulnerabilityOutcome` and `KevMembership`. They share this module for one
reason and it is the same reason none of them is beside its own pass -- the
import cycle argued immediately below -- and they share nothing else. None is
derived from another and none ranks against another.

**`KevMembership` is the one that is not an outcome type**, and its own docstring
argues why: it records a membership rather than a derived status, it carries
three values and not the four sentinels plus verdicts `outcome_type` composes,
and the column that holds it is deliberately not named for a status.

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

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from django.db import models

from conda_package_supply_chain_monitor.core.outcomes import EMPTY_AGGREGATE
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.outcomes import OutcomeVocabularyError
from conda_package_supply_chain_monitor.core.outcomes import outcome_type

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "ABSENT",
    "ABSENT_MEMBER",
    "ADVISORIES_MATCHED",
    "ADVISORIES_MATCHED_MEMBER",
    "BEHIND",
    "BEHIND_MEMBER",
    "CURRENCY_PRECEDENCE",
    "CURRENCY_STATE_LENGTH",
    "CURRENT",
    "CURRENT_MEMBER",
    "ERROR",
    "FEEDSTOCK_ERROR",
    "FEEDSTOCK_NOT_APPLICABLE",
    "FEEDSTOCK_NOT_FOUND",
    "FEEDSTOCK_STATE_LENGTH",
    "FEEDSTOCK_UNKNOWN",
    "INACTIVE_MEMBER",
    "KEV_LISTED",
    "KEV_MEMBERSHIP_LENGTH",
    "KEV_MEMBERSHIP_PRECEDENCE",
    "KEV_NOT_ESTABLISHED",
    "KEV_NOT_LISTED",
    "MAINTAINED_MEMBER",
    "NOT_APPLICABLE",
    "NOT_FOUND",
    "NO_ADVISORY_MATCHED",
    "NO_ADVISORY_MATCHED_MEMBER",
    "PRESENT_AND_INACTIVE",
    "PRESENT_AND_MAINTAINED",
    "STAGED_MEMBER",
    "STAGED_RECIPE_PENDING",
    "UNKNOWN",
    "VULNERABILITY_PRECEDENCE",
    "VULNERABILITY_STATE_LENGTH",
    "VULNERABILITY_STATUS_ERROR",
    "VULNERABILITY_STATUS_NOT_APPLICABLE",
    "VULNERABILITY_STATUS_NOT_FOUND",
    "VULNERABILITY_STATUS_UNKNOWN",
    "CurrencyOutcome",
    "FeedstockOutcome",
    "KevMembership",
    "PackageVulnerabilityOutcome",
    "worst_currency",
    "worst_kev_membership",
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
