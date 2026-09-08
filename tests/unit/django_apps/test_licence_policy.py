"""`CPM-FR-18`'s five outcomes and the rule set they come from, without a database.

`policies/licence.py` is split into one query and some matching on exactly the
terms `policies/currency.py`, `policies/feedstock.py` and
`policies/vulnerability.py` are: `current_findings` is the only function that
touches the database, and everything that *decides* anything takes evidence rows
and a rule set and returns a value. That split is what lets every row of the
story's I/O matrix that is about a decision be exercised here, in milliseconds,
against constructed observations -- and it is why the integration module beside
this one is about the orchestration, the constraints, the cut-off and the replay
rather than about the rules.

`policies/parameters.py`'s new key is split the same way and for the same reason:
`parameters_from` turns *text* into parameter sets, so every refusal the reviewed
file can earn for a rule set is measured here against a string.

**The story's central property is asserted in both tiers, and neither assertion
is the whole of it.** Here it is structural and exhaustive: `allowed` is returned
from a rule's own recorded disposition and from nowhere else, so every path that
does not reach a rule is enumerated and required to answer `manual_review` or
`unknown`. In the integration module it is behavioural: two packages with
identical evidence, one whose licence a rule names and one whose licence no rule
names, driven through `evaluate` -- which is a comparison an implementation that
had started defaulting could actually fail, where a case computing one expression
twice could not.

**Unsaved model instances, and that is what keeps this a unit test.** A
`LicenseFinding` is constructed and never saved: `_meta` is populated at import,
the fields hold whatever they were given, and nothing here opens a connection. It
is also the only way to build the rows the database refuses -- a state outside the
vocabulary, the `not_applicable` the table forbids outright, and a determinate row
carrying no expression -- which are exactly the rows this pass must not read as a
permission.

No database, no network, no subprocess, no filesystem.
"""

from __future__ import annotations

import re
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_sentinel.collectors.models import LicenseFinding
from conda_sentinel.collectors.outcomes import LICENSE_ERROR
from conda_sentinel.collectors.outcomes import LICENSE_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import LICENSE_NOT_FOUND
from conda_sentinel.collectors.outcomes import LICENSE_UNKNOWN
from conda_sentinel.collectors.outcomes import NORMALIZED
from conda_sentinel.collectors.outcomes import LicenseOutcome
from conda_sentinel.collectors.spdx import OPERATORS
from conda_sentinel.collectors.spdx import SPELLINGS
from conda_sentinel.collectors.spdx import DetectionMethod
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.outcomes import SENTINEL_MEMBERS
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.outcomes import OutcomeVocabularyError
from conda_sentinel.core.outcomes import verify_sentinels
from conda_sentinel.core.rollup import contributable_columns
from conda_sentinel.policies.licence import BLANK_EXPRESSION_DETAIL
from conda_sentinel.policies.licence import CONJOINED_OPERAND_DETAIL
from conda_sentinel.policies.licence import CONJUNCTION
from conda_sentinel.policies.licence import DISAGREEING_CHANNELS_DETAIL
from conda_sentinel.policies.licence import ESTABLISHED_ELSEWHERE_DETAIL
from conda_sentinel.policies.licence import LICENSE_VOCABULARY
from conda_sentinel.policies.licence import NO_MATCHING_RULE_DETAIL
from conda_sentinel.policies.licence import NO_RULE_SET_DETAIL
from conda_sentinel.policies.licence import POLICY_NAME
from conda_sentinel.policies.licence import READ_ORDERING
from conda_sentinel.policies.licence import RESTRICTIVE_DISPOSITIONS
from conda_sentinel.policies.licence import UNESTABLISHED_LICENCE_DETAIL
from conda_sentinel.policies.licence import UNREADABLE_CHANNEL_DETAIL
from conda_sentinel.policies.licence import UNSERVED_PACKAGE_DETAIL
from conda_sentinel.policies.licence import WITHIN_A_SWEEP
from conda_sentinel.policies.licence import LicensePass
from conda_sentinel.policies.licence import LicensePolicyError
from conda_sentinel.policies.licence import conjoined_operands
from conda_sentinel.policies.licence import contributing_findings
from conda_sentinel.policies.licence import current_findings
from conda_sentinel.policies.licence import finding_verdict
from conda_sentinel.policies.licence import license_detail
from conda_sentinel.policies.licence import license_outcome
from conda_sentinel.policies.licence import matched_rule
from conda_sentinel.policies.licence import normalized_expression
from conda_sentinel.policies.licence import restrictive_rule
from conda_sentinel.policies.licence import rule_for
from conda_sentinel.policies.licence import stated_expressions
from conda_sentinel.policies.licence import supporting_finding
from conda_sentinel.policies.models import A_MATCHED_RULE_ONLY_WHERE_A_RULE_DECIDED
from conda_sentinel.policies.models import A_RULED_OUTCOME_NAMES_THE_RULE_THAT_PRODUCED_IT
from conda_sentinel.policies.models import JUDGED_LICENSE_OUTCOMES
from conda_sentinel.policies.models import LICENSE_ROW_NAMES_ITS_POLICY_VERSION
from conda_sentinel.policies.models import ONE_LICENSE_ROW_PER_PACKAGE_PER_RUN
from conda_sentinel.policies.models import THE_JUDGED_LICENSE_OUTCOME_NEEDS_ITS_FINDING
from conda_sentinel.policies.models import PackageLicense
from conda_sentinel.policies.outcomes import ALLOWED
from conda_sentinel.policies.outcomes import FORBIDDEN
from conda_sentinel.policies.outcomes import LICENSE_PRECEDENCE
from conda_sentinel.policies.outcomes import LICENSE_STATE_LENGTH
from conda_sentinel.policies.outcomes import LICENSE_STATUS_ERROR
from conda_sentinel.policies.outcomes import LICENSE_STATUS_NOT_APPLICABLE
from conda_sentinel.policies.outcomes import LICENSE_STATUS_NOT_FOUND
from conda_sentinel.policies.outcomes import LICENSE_STATUS_UNKNOWN
from conda_sentinel.policies.outcomes import MANUAL_REVIEW
from conda_sentinel.policies.outcomes import RESTRICTED
from conda_sentinel.policies.outcomes import RULE_DISPOSITIONS
from conda_sentinel.policies.outcomes import PackageLicenseOutcome
from conda_sentinel.policies.outcomes import worst_license
from conda_sentinel.policies.parameters import MAX_LICENSE_EXPRESSION_CHARACTERS
from conda_sentinel.policies.parameters import NORMALIZABLE_IDENTIFIERS
from conda_sentinel.policies.parameters import NORMALIZABLE_OPERATORS
from conda_sentinel.policies.parameters import RULE_DISPOSITION_KEY
from conda_sentinel.policies.parameters import RULE_EXPRESSION_KEY
from conda_sentinel.policies.parameters import RULES_KEY
from conda_sentinel.policies.parameters import LicenseRule
from conda_sentinel.policies.parameters import PolicyParameterError
from conda_sentinel.policies.parameters import PolicyParameters
from conda_sentinel.policies.parameters import parameters_from
from tests.policy_parameters import license_rule_array
from tests.policy_parameters import parameter_document

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The policy version the parameter cases record. Any stable string does here:
#: what these cases assert is the *keying*, not which version it is.
A_VERSION: Final[str] = "cpm-fixture-policy-1"

#: The expression most cases are about, spelled as SPDX spells it -- mixed case,
#: which is what makes the case-folding cases mean something.
AN_EXPRESSION: Final[str] = "MIT"

#: A second expression, for the disagreement cases.
ANOTHER_EXPRESSION: Final[str] = "GPL-3.0-only"

#: A disjunction, which this pass matches whole and never decomposes: which of
#: two licences a package took is the compliance judgement it will not make.
A_COMPOUND_EXPRESSION: Final[str] = "MIT OR Apache-2.0"

#: A conjunction, which binds both sets of obligations at once -- so a rule about
#: either operand may restrict or forbid it, and no rule about either may permit
#: it. Built from the two expressions above rather than written out, so a case
#: about an operand and a case about the compound cannot drift apart.
A_CONJUNCTION: Final[str] = f"{AN_EXPRESSION} AND {ANOTHER_EXPRESSION}"

#: A rule set naming the first expression and permitting it -- the only shape in
#: this repository that can produce `allowed`.
AN_ALLOWING_RULE_SET: Final[tuple[LicenseRule, ...]] = (LicenseRule(expression=AN_EXPRESSION, disposition=ALLOWED),)

#: A rule set naming an expression no case's evidence uses, for the matrix's "a
#: rule names a licence no evidence uses" row.
AN_UNUSED_RULE_SET: Final[tuple[LicenseRule, ...]] = (LicenseRule(expression="Zlib", disposition=ALLOWED),)

#: The shipped rule set: no rules at all.
NO_RULES: Final[tuple[LicenseRule, ...]] = ()

#: A state no `OutcomeState` member carries. `license_findings` declares
#: `choices`, which Django does not enforce on `save()`, so the value is
#: reachable in Python and this is the only place it can be built.
A_STATE_FROM_NOWHERE: Final[str] = "probably_fine"

#: A naive instant, for the cut-off refusal. Naive is the whole of what makes it
#: unusable: there is no offset to interpret, so the read would be shifted by
#: whichever offset the reader happened to be in.
A_NAIVE_INSTANT: Final = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - naive on purpose; it is the subject

#: A package primary key for the read refusal, which never reaches a query.
A_PACKAGE_ID: Final[int] = 1

#: A rule whose expression is one character wider than a stored expression can
#: be. Bound to a name rather than spelled inside the refusal table, because a
#: two-part f-string inside a tuple reads as a missing comma to a linter and to
#: a human.
AN_OVERLONG_RULE: Final[str] = (
    f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = "{"M" * (MAX_LICENSE_EXPRESSION_CHARACTERS + 1)}", '
    f'{RULE_DISPOSITION_KEY} = "allowed" }}]'
)

#: How many rules `NO_MATCHING_RULE_DETAIL` reports for a one-rule set, named so
#: the assertion reads as the count it is.
ONE_RULE: Final[int] = 1

#: How many distinct expressions two disagreeing channels state.
TWO_EXPRESSIONS: Final[int] = 2

#: The shortest rule set whose faults sort differently by position and by rendered
#: clause: with eleven of them, `rule 10` precedes `rule 2` lexicographically.
ELEVEN_RULES: Final[int] = 11


def a_finding(
    *,
    state: str = NORMALIZED,
    expression: str = AN_EXPRESSION,
    detail: str = "",
    pk: int = 1,
) -> LicenseFinding:
    """Build one unsaved licence finding.

    Args:
        state: What the observation concluded.
        expression: The normalized SPDX expression, on a determinate row.
        detail: What the collector had to say.
        pk: The primary key, so a case can tell two findings apart in a message
            and in a reference.

    Returns:
        The unsaved row. Never saved: the table's own biconditional would refuse
        several of these, and the rows it refuses are exactly the ones the
        verdict must not read as a permission.

    """
    determinate = state == NORMALIZED
    finding = LicenseFinding(
        state=state,
        channel="conda-forge",
        raw_license=expression,
        normalized_license=expression if determinate else "",
        detection_method=DetectionMethod.SPDX_IDENTIFIER.value if determinate else "",
        detail=detail,
    )
    finding.pk = pk
    return finding


# ---------------------------------------------------------------------------
# The vocabulary and its order.
# ---------------------------------------------------------------------------


def test_the_licence_vocabulary_carries_the_four_sentinels_by_construction() -> None:
    """`CPM-AD-5`: every per-status type is composed from `core`'s sentinel table.

    `verify_sentinels` is the post-condition `outcome_type` already enforces, and
    asserting it here is what says this vocabulary was composed rather than
    hand-rolled -- a hand-rolled table spelling `("not_applicable", "N/A")` would
    satisfy every value comparison below and fail this.
    """
    verify_sentinels(PackageLicenseOutcome)

    assert {value for _, value in SENTINEL_MEMBERS} <= set(PackageLicenseOutcome.values)


def test_the_five_outcomes_cpm_fr_18_names_are_five_distinct_values() -> None:
    """AC 1's vocabulary, and `ok` is deliberately not a member.

    `CPM-FR-18` names allowed, restricted, forbidden, unknown and manual review.
    Four are determinate members composed here and the fifth is `core`'s own
    `unknown`, which arrives by construction -- so `unknown` here and `unknown`
    anywhere else in the product are the same string with the same meaning.

    `ok` is absent for the reason `collectors/outcomes.py` gives one level down:
    on a licence column the generic determinate value reads as "this licence is
    fine", which is precisely the verdict only a rule may reach.
    """
    assert len({ALLOWED, RESTRICTED, FORBIDDEN, MANUAL_REVIEW, LICENSE_STATUS_UNKNOWN}) == len(LICENSE_PRECEDENCE)
    assert OutcomeState.OK.value not in PackageLicenseOutcome.values


def test_manual_review_and_unknown_are_never_the_same_value() -> None:
    """The distinction a reviewer needs and the one a reader would flatten first.

    `unknown` is a gap in the *evidence* -- the licence itself was never
    established. `manual_review` is a gap in the *policy* -- the licence is known
    and no rule names it. Collapsing them would hide which of the two somebody is
    being asked to fix, and they are different people.
    """
    assert MANUAL_REVIEW != LICENSE_STATUS_UNKNOWN
    assert MANUAL_REVIEW not in {value for _, value in SENTINEL_MEMBERS}


def test_the_outcome_column_is_wide_enough_for_every_value_it_offers() -> None:
    """A width shorter than the longest choice is a truncated verdict.

    Django's own `fields.E009` would reject it, and this says the number was
    argued rather than inherited: the longest value is `not_applicable`.
    """
    assert max(len(value) for value in PackageLicenseOutcome.values) <= LICENSE_STATE_LENGTH


def test_this_domains_order_is_declared_by_name_and_by_contents() -> None:
    """The assertion `tests/unit/django_apps/test_single_ordering_audit.py` cannot make.

    That audit matches a literal holding two or more `OutcomeState` member
    references, and this order holds one, because the reduction never meets the
    other three sentinels. Its recorded table therefore records this order in
    prose and points here, and this is the case it points at.

    The *ends* matter most and both are the story. `forbidden` leads it because
    disagreement never resolves upward: a package one channel says is forbidden
    must not report something milder because another channel said something else.
    `allowed` is last because `worst_license` takes the worst rank, so a
    reduction cannot reach `allowed` while any channel said anything at all
    besides `allowed`.
    """
    assert LICENSE_PRECEDENCE == (FORBIDDEN, RESTRICTED, LICENSE_STATUS_UNKNOWN, MANUAL_REVIEW, ALLOWED)
    assert LICENSE_PRECEDENCE[0] == FORBIDDEN
    assert LICENSE_PRECEDENCE[-1] == ALLOWED


def test_the_dispositions_a_rule_may_state_are_the_three_a_rule_can_reach() -> None:
    """`manual_review` and every sentinel are deliberately outside the set.

    A rule stating `manual_review` would be a rule saying nothing -- that is what
    a licence no rule names already reaches -- and a rule stating a sentinel would
    be a rule claiming to make a licence un-established. The set is read by
    `policies/parameters.py` to refuse anything else and by `policies/models.py`
    to require the rule behind such a row, so a second spelling of it would be a
    constraint that stops matching what the file accepts.
    """
    assert set(RULE_DISPOSITIONS) == {ALLOWED, RESTRICTED, FORBIDDEN}
    assert MANUAL_REVIEW not in RULE_DISPOSITIONS
    assert LICENSE_STATUS_UNKNOWN not in RULE_DISPOSITIONS


@pytest.mark.parametrize(
    "unranked",
    [LICENSE_STATUS_ERROR, LICENSE_STATUS_NOT_FOUND, LICENSE_STATUS_NOT_APPLICABLE, "fine"],
    ids=["error", "not-found", "not-applicable", "from-nowhere"],
)
def test_the_reduction_refuses_a_value_it_cannot_rank(unranked: str) -> None:
    """An unrankable verdict refuses rather than being treated as determinate.

    Three of these are members of the vocabulary that this pass never produces --
    `error` and `not_found` are folded into `unknown` where they arrive, and
    `not_applicable` is refused by `license_findings` outright -- and the fourth is
    from outside it entirely. Ranking any of them beside `allowed` would be
    `CPM-FR-6`'s fold arrived at by silence, on the one column a compliance
    reviewer reads first.
    """
    with pytest.raises(OutcomeVocabularyError, match="licence precedence order"):
        worst_license([MANUAL_REVIEW, unranked])


def test_no_verdicts_at_all_reduce_to_unknown_and_never_to_allowed() -> None:
    """The matrix's "no licence evidence at all": nothing to reduce is `unknown`.

    Never clean and emphatically never `allowed` -- which is the assertion worth
    writing, because an empty reduction is exactly where a `min()` over an empty
    sequence or a "nothing objected" reading would land on the permissive value.
    """
    assert worst_license([]) == LICENSE_STATUS_UNKNOWN
    assert worst_license([]) != ALLOWED


# ---------------------------------------------------------------------------
# One channel at a time: where `allowed` comes from, and where it cannot.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("disposition", list(RULE_DISPOSITIONS), ids=list(RULE_DISPOSITIONS))
def test_a_rule_naming_the_licence_gives_the_row_that_rules_own_disposition(disposition: str) -> None:
    """The matrix's three rule rows, and the only path to `allowed`.

    The verdict is the rule's recorded disposition and nothing else -- there is no
    branch in `finding_verdict` spelling any of these three values, so the string
    a row carries came out of the reviewed file.
    """
    rules = (LicenseRule(expression=AN_EXPRESSION, disposition=disposition),)

    assert finding_verdict(a_finding(), rules=rules) == disposition


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (LICENSE_UNKNOWN, LICENSE_STATUS_UNKNOWN),
        (LICENSE_ERROR, LICENSE_STATUS_UNKNOWN),
        (LICENSE_NOT_FOUND, LICENSE_STATUS_UNKNOWN),
    ],
    ids=["unrecognised", "unread-channel", "unserved-package"],
)
def test_every_sentinel_evidence_state_reaches_unknown_and_never_a_permission(state: str, expected: str) -> None:
    """The matrix's three "never established" rows, under a rule set that allows the licence.

    The rule set is the *allowing* one deliberately: a sentinel row states no
    expression, so an implementation that reached for the rule set before checking
    what the row established -- or that treated a blank expression as matching a
    rule -- would answer `allowed` here. It answers `unknown`, whatever the rules
    say, because there is no licence for a rule to name.

    At the package level "the channel stated something we will not normalize",
    "the channel could not be read" and "the channel does not serve this package"
    all mean this run established no licence, which is what `unknown` means, and
    none of them is a licence with no restrictions.
    """
    verdict = finding_verdict(a_finding(state=state), rules=AN_ALLOWING_RULE_SET)

    assert verdict == expected
    assert verdict != ALLOWED


def test_a_licence_no_rule_names_is_manual_review_rather_than_allowed() -> None:
    """The matrix's "rules recorded, none matches", at one channel.

    A recorded policy exists and does not cover this licence. The permissive
    reading -- "nothing forbids it" -- is the whole failure mode this story is
    written against, and `manual_review` is the answer.
    """
    assert finding_verdict(a_finding(), rules=AN_UNUSED_RULE_SET) == MANUAL_REVIEW


def test_the_shipped_empty_rule_set_reaches_manual_review_and_nothing_else() -> None:
    """The matrix's first row and the state this component ships in.

    PRD Open Question 2 is unanswered, so no version records a rule and every
    package whose licence was established reads `manual_review`. That is the
    correct answer to "no policy has been decided" and is exactly what
    `CPM-SECURITY-S03`'s AC 2 promised -- and it is emphatically not a failure,
    which the integration module asserts end to end.
    """
    verdict = finding_verdict(a_finding(), rules=NO_RULES)

    assert verdict == MANUAL_REVIEW
    assert verdict != ALLOWED


def test_a_determinate_row_stating_no_expression_is_unknown_rather_than_reviewable() -> None:
    """The matrix's "a blank normalized expression", which the evidence table forbids.

    `license_findings`' own biconditional requires an expression on a determinate
    row, so reaching this means something went round that constraint. There is
    nothing for a rule to name, so nothing was established -- `unknown`, never
    `manual_review`, which would claim the licence is known, and never `allowed`.
    """
    verdict = finding_verdict(a_finding(expression=""), rules=AN_ALLOWING_RULE_SET)

    assert verdict == LICENSE_STATUS_UNKNOWN
    assert verdict not in {MANUAL_REVIEW, ALLOWED}


def test_the_expression_is_matched_case_insensitively_and_through_whitespace() -> None:
    """SPDX identifiers are mixed case and a reviewer writes them as SPDX spells them.

    So the file records the reviewer's spelling and the comparison folds both
    sides, rather than demanding a lowercase file that no SPDX reader would
    recognise. Surrounding whitespace on the stored expression is stripped for
    the same reason it is on the vulnerability collector's detail: a stored line
    carrying a newline is the same expression, and missing it would route a
    licence a rule *does* name to `manual_review`.
    """
    assert finding_verdict(a_finding(expression="  mit\n"), rules=AN_ALLOWING_RULE_SET) == ALLOWED


def test_a_disjunction_is_matched_whole_and_never_decomposed() -> None:
    """Deciding what a disjunction of two licences comes to is a compliance judgement.

    A rule naming `MIT` does not reach `MIT OR Apache-2.0`, and the unmatched
    expression reaches `manual_review` -- which for a disjunction *is* the
    conservative direction, because the permission is withheld. A rule that should
    cover the compound names it in full, and then it does.
    """
    compound = a_finding(expression=A_COMPOUND_EXPRESSION)

    assert finding_verdict(compound, rules=AN_ALLOWING_RULE_SET) == MANUAL_REVIEW
    assert (
        finding_verdict(compound, rules=(LicenseRule(expression=A_COMPOUND_EXPRESSION, disposition=ALLOWED),))
        == ALLOWED
    )


def test_a_rule_naming_a_compound_does_not_reach_one_of_its_operands() -> None:
    """The comparison is equality over the whole string, in both directions.

    A rule permitting `MIT OR Apache-2.0` permits the *choice* between them and
    says nothing about a package stating `MIT` alone -- and a comparison written
    as "the evidence appears in the rule" rather than as equality would read
    `allowed` here. It survives every other case in this module, because every
    other case's rule and evidence are the same length.
    """
    permitted_compound = (LicenseRule(expression=A_COMPOUND_EXPRESSION, disposition=ALLOWED),)

    assert rule_for(AN_EXPRESSION, rules=permitted_compound) is None
    assert finding_verdict(a_finding(), rules=permitted_compound) == MANUAL_REVIEW


@pytest.mark.parametrize(
    "disposition",
    [FORBIDDEN, RESTRICTED],
    ids=[FORBIDDEN, RESTRICTED],
)
def test_a_conjunction_takes_the_disposition_a_rule_states_about_one_of_its_operands(disposition: str) -> None:
    """**`AND` is not `OR`, and calling both "the conservative direction" was wrong.**

    A conjunction binds every one of its operands at once, so `MIT AND
    GPL-3.0-only` carries `GPL-3.0-only`'s obligations whatever else it carries.
    Matched whole and left there it reaches `manual_review`, which is rank 3 of 5
    -- strictly *more permissive* than the `forbidden` a rule about that operand
    already states, and more permissive than `unknown`. That is not conservatism;
    it is a deny rule a reviewer wrote being silently weakened by a conjunction.

    The row names the operand rule that decided it, which is also what
    `A_RULED_OUTCOME_NAMES_THE_RULE_THAT_PRODUCED_IT` requires of it: a
    `forbidden` naming no rule is refused by the database.
    """
    conjunction = a_finding(expression=A_CONJUNCTION)
    rules = (LicenseRule(expression=ANOTHER_EXPRESSION, disposition=disposition),)

    assert finding_verdict(conjunction, rules=rules) == disposition
    decided = matched_rule(conjunction, outcome=disposition, rules=rules)
    assert decided is not None
    assert decided.expression == ANOTHER_EXPRESSION


def test_a_conjunction_is_never_decomposed_in_the_permissive_direction() -> None:
    """The half of the decomposition that must not exist, and the story's whole property.

    A rule allowing `MIT` says nothing about the obligations `GPL-3.0-only` adds,
    so `MIT AND GPL-3.0-only` is not permitted by it and must not be: `allowed`
    stays reachable only from a rule naming the whole expression. An
    implementation that decomposed symmetrically would answer `allowed` here,
    which is the one value this story exists to keep out of reach.
    """
    conjunction = a_finding(expression=A_CONJUNCTION)

    assert finding_verdict(conjunction, rules=AN_ALLOWING_RULE_SET) == MANUAL_REVIEW
    assert finding_verdict(conjunction, rules=AN_ALLOWING_RULE_SET) != ALLOWED
    assert restrictive_rule(A_CONJUNCTION, rules=AN_ALLOWING_RULE_SET) is None


def test_a_disjunction_with_a_forbidden_operand_is_still_manual_review() -> None:
    """Only `AND` is taken apart, because only `AND` binds both sets of obligations.

    `MIT OR GPL-3.0-only` offers a choice, and which one a package took is the
    compliance judgement this pass will not make -- so a rule forbidding one
    operand does not forbid the choice, and the expression reaches
    `manual_review` for a person to decide. Decomposing it would be this component
    answering the question it exists to route to somebody else.
    """
    disjunction = a_finding(expression=f"{AN_EXPRESSION} OR {ANOTHER_EXPRESSION}")
    rules = (LicenseRule(expression=ANOTHER_EXPRESSION, disposition=FORBIDDEN),)

    assert conjoined_operands(f"{AN_EXPRESSION} OR {ANOTHER_EXPRESSION}") == ()
    assert finding_verdict(disjunction, rules=rules) == MANUAL_REVIEW


def test_a_rule_naming_the_conjunction_whole_beats_a_rule_naming_an_operand() -> None:
    """A reviewer's statement about the compound is a statement about the compound.

    Decomposition is what happens when there is *no* rule about the expression,
    not a second opinion beside one -- so a version that permits `MIT AND
    GPL-3.0-only` outright permits it, whatever it says about `GPL-3.0-only` on
    its own. Ordering the two lookups the other way would make a whole-expression
    rule unwritable for any conjunction with a ruled operand.
    """
    conjunction = a_finding(expression=A_CONJUNCTION)
    rules = (
        LicenseRule(expression=ANOTHER_EXPRESSION, disposition=FORBIDDEN),
        LicenseRule(expression=A_CONJUNCTION, disposition=ALLOWED),
    )

    assert finding_verdict(conjunction, rules=rules) == ALLOWED


def test_the_worst_operand_of_a_conjunction_decides_it() -> None:
    """Two restrictive operands are not a tie to be broken by the file's order.

    `restricted` and `forbidden` are both statements about obligations the
    conjunction binds, and taking whichever the reviewer wrote first would let the
    order of a list decide a compliance verdict. The reduction's own order decides
    it instead, in the same direction it decides everything else here.
    """
    rules = (
        LicenseRule(expression=AN_EXPRESSION, disposition=RESTRICTED),
        LicenseRule(expression=ANOTHER_EXPRESSION, disposition=FORBIDDEN),
    )

    assert finding_verdict(a_finding(expression=A_CONJUNCTION), rules=rules) == FORBIDDEN


def test_a_row_a_conjunction_decided_says_which_operand_decided_it() -> None:
    """Three columns a reader would otherwise have to reconcile by guesswork.

    The outcome is `forbidden`, the matched rule is `GPL-3.0-only`, and the
    finding it references states `MIT AND GPL-3.0-only`. Nothing in those three
    says they were arrived at by decomposition, and the inference a reader is
    likeliest to draw from "a rule about one operand decided this" is the one that
    is false -- that a rule about one operand could equally have permitted it.
    """
    supporting = a_finding(expression=A_CONJUNCTION)
    rules = (LicenseRule(expression=ANOTHER_EXPRESSION, disposition=FORBIDDEN),)

    line = license_detail(
        [supporting],
        outcome=FORBIDDEN,
        supporting=supporting,
        rules=rules,
        version=A_VERSION,
    )

    assert line == CONJOINED_OPERAND_DETAIL.format(
        expression=A_CONJUNCTION,
        operand=ANOTHER_EXPRESSION,
        disposition=FORBIDDEN,
    )


def test_the_operator_this_pass_decomposes_is_one_collectors_spdx_actually_writes() -> None:
    """The one string this module spells that another module owns the meaning of.

    `CONJUNCTION` is written here because `collectors/spdx.py`'s `OPERATORS` is a
    frozenset with nothing to index, and this story may not change a collector to
    declare it there instead. Two modules agreeing by docstring is what this
    repository has already decided is not enough, so they are reconciled by a
    case: were `AND` to stop being an operator that module recognises, no evidence
    row could carry a conjunction and every decomposition here would be dead code.
    """
    assert CONJUNCTION in OPERATORS
    assert f"{AN_EXPRESSION} {CONJUNCTION} {ANOTHER_EXPRESSION}" == A_CONJUNCTION


def test_the_dispositions_a_conjunction_may_impose_exclude_the_permissive_one() -> None:
    """`allowed` is on the other side of `unknown`, and that is what keeps it unreachable.

    The set is derived from the precedence order rather than listed, so
    "restrictive" means "ranked below `unknown`" by construction: a fourth
    disposition ranked there would join it without a second edit, and one ranked
    above it could not be smuggled in. Asserting the membership *and* the
    exclusion, because a set that had quietly become all three dispositions would
    satisfy the first alone.
    """
    assert set(RESTRICTIVE_DISPOSITIONS) == {FORBIDDEN, RESTRICTED}
    assert ALLOWED not in RESTRICTIVE_DISPOSITIONS
    assert set(RESTRICTIVE_DISPOSITIONS) < set(RULE_DISPOSITIONS)


def test_a_rule_naming_a_licence_no_evidence_uses_has_no_effect_and_no_failure() -> None:
    """The matrix's "the rule set is broader than the inventory".

    A rule about a licence nothing in this inventory carries is inert: it decides
    nothing and refuses nothing, and a reviewer adding one for a licence they
    expect to see one day has not changed a single verdict.
    """
    assert rule_for("Zlib", rules=AN_UNUSED_RULE_SET) is not None
    assert finding_verdict(a_finding(), rules=AN_UNUSED_RULE_SET) == MANUAL_REVIEW


def test_a_blank_expression_never_matches_a_rule() -> None:
    """The lookup's own guard, and the reason it is a guard rather than an accident.

    A recorded rule can never name nothing -- `policies/parameters.py` refuses a
    blank expression -- so the loop would never match anyway. Returning early is
    what makes that a property of this function rather than of that one, on a
    lookup whose answer decides whether a package reads `allowed`.
    """
    assert rule_for("", rules=AN_ALLOWING_RULE_SET) is None


@pytest.mark.parametrize(
    "state",
    [LICENSE_NOT_APPLICABLE, A_STATE_FROM_NOWHERE],
    ids=["not-applicable", "from-nowhere"],
)
def test_a_state_this_pass_cannot_read_refuses_rather_than_becoming_a_verdict(state: str) -> None:
    """`choices` is a form rule Django does not enforce on `save()`.

    `not_applicable` is refused by `license_findings`' own check constraint --
    every package a monitored channel could serve is licensed under something --
    and is refused again here, because a table's constraint binds that table's
    writers and this binds the reader. A value from outside the vocabulary
    entirely is the same defect arrived at differently.

    A refusal here costs one package, and it is the one place this pass refuses
    over evidence rather than recording: an outcome derived from a value nothing
    recognises is the one thing that must not reach the column a compliance
    reviewer reads first.
    """
    with pytest.raises(LicensePolicyError, match="cannot read as a verdict"):
        finding_verdict(a_finding(state=state), rules=NO_RULES)


# ---------------------------------------------------------------------------
# Several channels, and the direction disagreement resolves in.
# ---------------------------------------------------------------------------


def test_two_channels_stating_different_licences_reach_the_least_permissive_outcome() -> None:
    """The matrix's "several channels disagree": disagreement never resolves upward.

    One channel states a licence a rule allows and the other states one a rule
    forbids. A reduction taking the first row, the newest row, or the commonest
    value could answer `allowed` here, and that is a package cleared because one
    of two channels happened to sort first.
    """
    rules = (
        LicenseRule(expression=AN_EXPRESSION, disposition=ALLOWED),
        LicenseRule(expression=ANOTHER_EXPRESSION, disposition=FORBIDDEN),
    )
    findings = [a_finding(pk=1), a_finding(expression=ANOTHER_EXPRESSION, pk=2)]

    assert license_outcome(findings, rules=rules) == FORBIDDEN


def test_a_channel_that_established_nothing_beside_one_that_did_is_unknown() -> None:
    """`unknown` outranks `manual_review`, in `core`'s own relative order.

    A run that read one channel and failed on another has not established this
    package's licence, and `manual_review` would say the licence is known and
    only the rule is missing. The row's `detail` still names both facts, which is
    what keeps the claim honest rather than merely conservative -- so this asserts
    the line as well as the outcome, because the outcome on its own is the
    conservative half and the honest half is the one that was missing.
    """
    findings = [a_finding(pk=1), a_finding(state=LICENSE_ERROR, pk=2)]

    outcome = license_outcome(findings, rules=NO_RULES)
    supporting = supporting_finding(findings, outcome, rules=NO_RULES)
    line = license_detail(findings, outcome=outcome, supporting=supporting, rules=NO_RULES, version=A_VERSION)

    assert outcome == LICENSE_STATUS_UNKNOWN
    assert supporting is findings[1]
    assert UNREADABLE_CHANNEL_DETAIL.format(findings="2") in line
    assert ESTABLISHED_ELSEWHERE_DETAIL.format(expressions=[AN_EXPRESSION]) in line


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        (AN_ALLOWING_RULE_SET, ALLOWED),
        (NO_RULES, MANUAL_REVIEW),
        ((LicenseRule(expression=AN_EXPRESSION, disposition=FORBIDDEN),), FORBIDDEN),
    ],
    ids=["allowed", "manual-review", "forbidden"],
)
def test_a_channel_that_does_not_serve_the_package_does_not_erase_the_verdict(
    rules: Sequence[LicenseRule],
    expected: str,
) -> None:
    """**The reduction defect a multi-channel deployment would have met on every package.**

    `collectors/license.py` writes one row per monitored channel and never fewer,
    so a package conda-forge serves and bioconda does not gets a determinate row
    *and* a `not_found` row in the same sweep -- which is the ordinary shape, not
    an edge case. Counting the absence as a verdict puts `unknown` into the
    reduction, and `unknown` outranks both `manual_review` and `allowed`: the
    whole determinate output of the pass would collapse to `unknown` the moment a
    second channel was monitored, `manual_review` would be masked, and `allowed`
    would be unreachable outside a single-channel deployment.

    A channel that does not carry the package has not disagreed with one that
    does; it has said nothing, exactly as a channel stating a blank expression
    has. The third case is the safety half: dropping the absence only ever removes
    an `unknown` vote, so a channel that states a forbidden licence still decides
    the row.
    """
    findings = [a_finding(pk=1), a_finding(state=LICENSE_NOT_FOUND, pk=2)]

    assert license_outcome(findings, rules=rules) == expected


def test_a_package_no_monitored_channel_serves_is_unknown_and_says_so() -> None:
    """The other end of the same rule, and the matrix row it must not break.

    Dropping every absence leaves nothing to reduce, and an empty reduction is
    `unknown` -- which is the same answer reducing the absences themselves would
    give, so the outcome is `unknown` by two routes and the matrix's "only a
    `not_found` row" is satisfied either way. What the row must not lose is
    *which* nothing it met, so it still names the absent channels.
    """
    findings = [a_finding(state=LICENSE_NOT_FOUND, pk=1), a_finding(state=LICENSE_NOT_FOUND, pk=2)]

    outcome = license_outcome(findings, rules=AN_ALLOWING_RULE_SET)
    supporting = supporting_finding(findings, outcome, rules=AN_ALLOWING_RULE_SET)
    line = license_detail(
        findings,
        outcome=outcome,
        supporting=supporting,
        rules=AN_ALLOWING_RULE_SET,
        version=A_VERSION,
    )

    assert outcome == LICENSE_STATUS_UNKNOWN
    assert contributing_findings(findings) == ()
    assert UNSERVED_PACKAGE_DETAIL.format(findings="1, 2") in line


def test_an_absent_channel_is_never_the_row_the_verdict_names() -> None:
    """The reference points at the fault the outcome rests on, not at an absence.

    One channel could not be read and one does not serve the package, and the
    absence was inserted first. The reduction is `unknown` because of the
    unreadable channel; naming the absence instead would send a reviewer to a
    package that is simply not on that channel while the read failure went
    unmentioned.
    """
    absent = a_finding(state=LICENSE_NOT_FOUND, pk=1)
    unreadable = a_finding(state=LICENSE_ERROR, pk=2)
    findings = [absent, unreadable]

    assert supporting_finding(findings, LICENSE_STATUS_UNKNOWN, rules=NO_RULES) is unreadable


def test_an_allowed_licence_beside_a_forbidden_one_never_reads_allowed() -> None:
    """The story's property at the reduction, with the permissive rule listed first.

    The `allowed` finding is given **first**, so an implementation returning the
    first verdict -- or one short-circuiting on a permission -- reads `allowed`
    and fails here. `worst_license` takes the worst rank, and `allowed` is last
    in the order precisely so no arrangement of inputs can reach it while another
    channel said something else.
    """
    rules = (
        LicenseRule(expression=AN_EXPRESSION, disposition=ALLOWED),
        LicenseRule(expression=ANOTHER_EXPRESSION, disposition=FORBIDDEN),
    )
    findings = [a_finding(pk=1), a_finding(expression=ANOTHER_EXPRESSION, pk=2)]

    assert license_outcome(findings, rules=rules) != ALLOWED


def test_every_channel_agreeing_on_an_allowed_licence_does_read_allowed() -> None:
    """The other direction, and the case that stops the rule above being vacuous.

    Without it, an implementation that never produced `allowed` at all would pass
    every assertion in this module that says a row is not `allowed`.
    """
    findings = [a_finding(pk=1), a_finding(pk=2)]

    assert license_outcome(findings, rules=AN_ALLOWING_RULE_SET) == ALLOWED


# ---------------------------------------------------------------------------
# The evidence and the rule a row names.
# ---------------------------------------------------------------------------


def test_the_row_names_the_first_finding_that_supports_the_outcome() -> None:
    """A verdict names an observation a reader can open, and names the same one on a replay.

    First in read order, which is ascending primary key. The forbidding channel is
    given **second**, so an implementation returning `findings[0]` writes a row
    whose reference states a licence its own column contradicts -- and no
    constraint backstops that, because any non-null reference satisfies "a judged
    outcome names a row".
    """
    rules = (
        LicenseRule(expression=AN_EXPRESSION, disposition=ALLOWED),
        LicenseRule(expression=ANOTHER_EXPRESSION, disposition=FORBIDDEN),
    )
    permitted = a_finding(pk=1)
    refused = a_finding(expression=ANOTHER_EXPRESSION, pk=2)

    assert supporting_finding([permitted, refused], FORBIDDEN, rules=rules) is refused
    assert supporting_finding([permitted, refused], ALLOWED, rules=rules) is permitted


def test_two_channels_supporting_one_verdict_always_name_the_same_row() -> None:
    """ "First in read order" is only a property while more than one row can be first.

    Every other case in this module has at most one finding per verdict, so a
    reduction naming the *last* supporting row -- or any other one -- satisfies all
    of them. Three channels agreeing on one licence is the ordinary shape of a
    multi-channel sweep, and a replay that named a different one of them each time
    would make `CPM-FR-22`'s reproduction untrue of the reference column while
    every value column agreed.
    """
    findings = [a_finding(pk=1), a_finding(pk=2), a_finding(pk=3)]

    assert supporting_finding(findings, ALLOWED, rules=AN_ALLOWING_RULE_SET) is findings[0]


def test_no_finding_supports_the_outcome_of_a_package_with_no_evidence() -> None:
    """The `unknown` row with nothing behind it.

    `None` here is what makes the derived table's reference nullable honest: the
    absence of a finding rather than a second spelling of a state.
    """
    assert supporting_finding([], LICENSE_STATUS_UNKNOWN, rules=NO_RULES) is None


def test_the_row_names_the_rule_that_produced_it_and_only_where_one_did() -> None:
    """The guard that makes the database constraint one the pass cannot violate.

    A rule is looked up only for an outcome a rule can state, so `manual_review`
    and `unknown` rows carry no rule *structurally* rather than incidentally. An
    implementation that looked the rule up unconditionally would write a
    `manual_review` row naming a rule on any package whose supporting finding
    happened to match one -- which is a row saying both that a rule decided this
    licence and that none did, and which
    `A_MATCHED_RULE_ONLY_WHERE_A_RULE_DECIDED` then refuses at the database.
    """
    supporting = a_finding()

    decided = matched_rule(supporting, outcome=ALLOWED, rules=AN_ALLOWING_RULE_SET)

    assert decided is not None
    assert decided.expression == AN_EXPRESSION
    assert matched_rule(supporting, outcome=MANUAL_REVIEW, rules=AN_ALLOWING_RULE_SET) is None
    assert matched_rule(None, outcome=ALLOWED, rules=AN_ALLOWING_RULE_SET) is None


def test_the_matched_rule_is_the_reviewers_spelling_and_not_the_evidence_row_s() -> None:
    """What the audit trail records is the rule, so it is the rule's own text.

    The evidence states `mit` and the file records `MIT`; the stored value is the
    file's, because a reviewer reading a report has to be able to find the rule
    they wrote. The comparison folds both sides, which is what lets the two
    differ at all.
    """
    decided = matched_rule(a_finding(expression="mit"), outcome=ALLOWED, rules=AN_ALLOWING_RULE_SET)

    assert decided is not None
    assert decided.expression == AN_EXPRESSION


def test_the_stated_expressions_are_distinct_sorted_and_exclude_the_silent_channels() -> None:
    """A channel that stated no licence has not disagreed with one that did.

    Counting it would report a disagreement on every package one channel could
    not answer for, which is the commonest shape there is.

    **Sorted, and the input is deliberately not.** `MIT` is written first and
    sorts second, so an implementation that returned the channels in read order --
    or in whatever order a set happened to iterate in -- writes a different line
    from this one, and a replay's `detail` would differ from the original's by the
    order of two strings.
    """
    findings = [
        a_finding(pk=1),
        a_finding(expression=ANOTHER_EXPRESSION, pk=2),
        a_finding(pk=3),
        a_finding(state=LICENSE_ERROR, pk=4),
    ]

    assert stated_expressions(findings) == (ANOTHER_EXPRESSION, AN_EXPRESSION)
    assert stated_expressions(findings) == tuple(sorted(stated_expressions(findings)))
    assert len(stated_expressions(findings)) == TWO_EXPRESSIONS


def test_the_normalized_expression_is_read_stripped() -> None:
    """`normalized_license` is stored text and a stored line may carry whitespace."""
    assert normalized_expression(a_finding(expression="  MIT  ")) == AN_EXPRESSION
    assert normalized_expression(a_finding(state=LICENSE_ERROR)) == ""


# ---------------------------------------------------------------------------
# What the row says for itself.
# ---------------------------------------------------------------------------


def test_a_manual_review_at_a_version_with_no_rule_set_says_so_and_names_the_key() -> None:
    """The matrix's first row: the row says no rule set was recorded.

    A `manual_review` on every package in an inventory is exactly the shape
    somebody would otherwise read as a broken pass, so the line says which version
    and which key, and says plainly that this is the decided answer rather than a
    fault.
    """
    supporting = a_finding()

    line = license_detail(
        [supporting],
        outcome=MANUAL_REVIEW,
        supporting=supporting,
        rules=NO_RULES,
        version=A_VERSION,
    )

    assert line == NO_RULE_SET_DETAIL.format(version=A_VERSION, key=RULES_KEY, expression=AN_EXPRESSION)
    assert RULES_KEY in line
    assert A_VERSION in line
    # The shipped `2026.09.2` entry declares `license_rules = []`, so a line
    # saying the version "records no license_rules" is false of the very entry
    # that produces most of these rows. The two spellings parse to one state
    # deliberately, so the line is about the *rules* and names the key as the
    # thing a reviewer fills in. Asserting the equality above cannot catch this:
    # the expected value is the constant under test.
    assert f"records no {RULES_KEY}" not in line
    assert "records no licence rule" in line


def test_a_manual_review_at_a_version_with_rules_that_miss_says_a_different_thing() -> None:
    """The matrix's fifth row, and it is distinct from the first.

    There, nobody has written a policy at all and the work is to write one. Here a
    policy exists and does not cover this licence, and the work is to decide
    whether it should. Different sentences, because different people fix them --
    and the two lines are required to differ, because a reader seeing only one of
    them has to be able to tell which case it is.
    """
    supporting = a_finding()

    line = license_detail(
        [supporting],
        outcome=MANUAL_REVIEW,
        supporting=supporting,
        rules=AN_UNUSED_RULE_SET,
        version=A_VERSION,
    )

    assert line == NO_MATCHING_RULE_DETAIL.format(version=A_VERSION, rules=ONE_RULE, expression=AN_EXPRESSION)
    assert line != NO_RULE_SET_DETAIL.format(version=A_VERSION, key=RULES_KEY, expression=AN_EXPRESSION)


@pytest.mark.parametrize(
    ("state", "expression", "expected"),
    [
        (LICENSE_ERROR, AN_EXPRESSION, UNREADABLE_CHANNEL_DETAIL),
        (LICENSE_NOT_FOUND, AN_EXPRESSION, UNSERVED_PACKAGE_DETAIL),
        (LICENSE_UNKNOWN, AN_EXPRESSION, UNESTABLISHED_LICENCE_DETAIL),
        (NORMALIZED, "", BLANK_EXPRESSION_DETAIL),
    ],
    ids=["unread-channel", "unserved-package", "unrecognised", "blank-expression"],
)
def test_every_unknown_with_evidence_behind_it_says_which_kind_it_was(
    state: str,
    expression: str,
    expected: str,
) -> None:
    """Four ways to establish nothing, four sentences, because four different fixes.

    Without them each of these rows is indistinguishable from a row for a package
    nobody looked at: the same outcome, the same blank rule, and a reference a
    reader has to open to see the difference. A blank `detail` on an `unknown` now
    means one thing only -- there was no evidence at all.
    """
    supporting = a_finding(state=state, expression=expression, pk=7)

    line = license_detail(
        [supporting],
        outcome=LICENSE_STATUS_UNKNOWN,
        supporting=supporting,
        rules=NO_RULES,
        version=A_VERSION,
    )

    assert line == expected.format(findings=supporting.pk)


def test_every_kind_of_nothing_the_sweep_met_is_reported_and_not_only_the_first() -> None:
    """Which fault an operator is sent to must not depend on insertion order.

    `supporting_finding` takes the first row in primary-key order, so a
    single-valued account of a sweep holding an unreadable channel *and* one
    stating something unrecognisable reports whichever the collector happened to
    insert first and silently drops the other. Both channels are real work and
    they are different work.

    Both findings of one kind are named in one line rather than in two, because
    two identically-worded sentences differing only in a number is not something a
    reader parses.
    """
    findings = [
        a_finding(state=LICENSE_ERROR, pk=1),
        a_finding(state=LICENSE_UNKNOWN, pk=2),
        a_finding(state=LICENSE_ERROR, pk=3),
    ]

    line = license_detail(
        findings,
        outcome=LICENSE_STATUS_UNKNOWN,
        supporting=findings[0],
        rules=NO_RULES,
        version=A_VERSION,
    )

    assert UNREADABLE_CHANNEL_DETAIL.format(findings="1, 3") in line
    assert UNESTABLISHED_LICENCE_DETAIL.format(findings="2") in line


def test_an_unknown_beside_a_channel_that_did_establish_a_licence_does_not_deny_it() -> None:
    """The row must not assert the opposite of the truth in the one field that says which.

    A sweep of one determinate channel and one unreadable one reduces to
    `unknown` and references the *unreadable* row, so an account worded about the
    package -- "so this run established no licence for this package" -- is false:
    a channel established one, and `detail` is the only thing distinguishing the
    four kinds of `unknown` from each other and from a package nobody looked at.

    One expression is not a disagreement, so the disagreement line cannot carry
    this; the row says it in its own line, and the unknown line is worded about
    the channel it names rather than about the package.
    """
    determinate = a_finding(pk=1)
    unreadable = a_finding(state=LICENSE_ERROR, pk=2)

    line = license_detail(
        [determinate, unreadable],
        outcome=LICENSE_STATUS_UNKNOWN,
        supporting=unreadable,
        rules=NO_RULES,
        version=A_VERSION,
    )

    assert ESTABLISHED_ELSEWHERE_DETAIL.format(expressions=[AN_EXPRESSION]) in line
    assert AN_EXPRESSION in line
    assert "no licence for this package" not in line


def test_the_disagreement_line_is_written_beside_an_unknown_outcome_too() -> None:
    """The least permissive outcome over several channels is not always a rule's.

    Two channels state different licences and a third could not be read, so the
    reduction answers `unknown` -- and the row still has to show that there were
    several and what they said, which is the whole reason the line exists. An
    implementation that wrote it only beside `manual_review` would drop it exactly
    where the outcome is least self-explanatory.
    """
    findings = [
        a_finding(pk=1),
        a_finding(expression=ANOTHER_EXPRESSION, pk=2),
        a_finding(state=LICENSE_ERROR, pk=3),
    ]

    line = license_detail(
        findings,
        outcome=LICENSE_STATUS_UNKNOWN,
        supporting=findings[2],
        rules=NO_RULES,
        version=A_VERSION,
    )

    assert DISAGREEING_CHANNELS_DETAIL.format(expressions=[ANOTHER_EXPRESSION, AN_EXPRESSION]) in line
    assert UNREADABLE_CHANNEL_DETAIL.format(findings="3") in line


def test_a_package_whose_channels_disagree_says_so_beside_whatever_else_it_says() -> None:
    """The single outcome is the least permissive of several, and the row shows there were several.

    The line is added *beside* the manual-review line rather than instead of it,
    because a package whose channels disagree and whose licences no rule names
    needs both sentences -- and an implementation that returned early on the first
    would drop one of them.
    """
    findings = [a_finding(pk=1), a_finding(expression=ANOTHER_EXPRESSION, pk=2)]

    line = license_detail(
        findings,
        outcome=MANUAL_REVIEW,
        supporting=findings[0],
        rules=NO_RULES,
        version=A_VERSION,
    )

    assert NO_RULE_SET_DETAIL.format(version=A_VERSION, key=RULES_KEY, expression=AN_EXPRESSION) in line
    assert DISAGREEING_CHANNELS_DETAIL.format(expressions=[ANOTHER_EXPRESSION, AN_EXPRESSION]) in line


@pytest.mark.parametrize(
    ("outcome", "supporting"),
    [
        (LICENSE_STATUS_UNKNOWN, None),
        (ALLOWED, a_finding()),
        (FORBIDDEN, a_finding()),
    ],
    ids=["no-evidence", "allowed", "forbidden"],
)
def test_an_unremarkable_row_carries_no_detail(outcome: str, supporting: LicenseFinding | None) -> None:
    """`detail` is an explanation, and a column populated on every row says nothing.

    A package with no evidence is said by its two empty columns. A row a rule
    decided is said by its outcome, its matched rule and its referenced finding
    together, and there is nothing left to explain.
    """
    assert (
        license_detail(
            [] if supporting is None else [supporting],
            outcome=outcome,
            supporting=supporting,
            rules=AN_ALLOWING_RULE_SET,
            version=A_VERSION,
        )
        == ""
    )


# ---------------------------------------------------------------------------
# The read's one refusal, and the declarations.
# ---------------------------------------------------------------------------


def test_a_naive_cutoff_is_refused_before_anything_is_read() -> None:
    """`USE_TZ` is on, so a naive cut-off would be read as UTC and shift the evidence set.

    Refused before the query, which is what makes this a unit case: no connection
    is opened. Refused rather than converted, because a cut-off shifted by
    whichever offset the reader happened to be in selects a different evidence
    set on every replay -- the opposite of what `CPM-FR-22` promises.
    """
    with pytest.raises(LicensePolicyError, match="licence findings"):
        current_findings(package_id=A_PACKAGE_ID, cutoff=A_NAIVE_INSTANT)


def test_the_read_ordering_agrees_with_the_sibling_passes() -> None:
    """The sixth hand-written copy of `snapshot_as_of`'s rule, reconciled by a case.

    `policies/vulnerability.py` declares the same key and the two are only
    interchangeable while they agree; docstrings agreeing with each other is what
    this repository has already decided is not enough.
    """
    from conda_sentinel.policies.vulnerability import (  # noqa: PLC0415 - read beside the subject
        READ_ORDERING as VULNERABILITY_READ_ORDERING,
    )

    assert READ_ORDERING == VULNERABILITY_READ_ORDERING


def test_the_order_rows_are_read_in_within_one_sweep_is_ascending_and_fixed() -> None:
    """A replay names the same supporting row only while this key is what it says.

    Ascending is the whole content of it: `supporting_finding` takes the *first*
    row that supports the outcome, and "first" is only a fact while the read order
    is fixed. Flipping it to `-pk` reverses which channel a verdict names on every
    package four channels serve.
    """
    assert WITHIN_A_SWEEP == "pk"
    assert not WITHIN_A_SWEEP.startswith("-")


def test_the_evidence_vocabulary_is_read_off_the_composed_type() -> None:
    """A listed copy would be a second spelling of values `outcome_type` has already fixed.

    And a module-scope literal holding several `OutcomeState` members is
    indistinguishable from a precedence order to
    `tests/unit/django_apps/test_single_ordering_audit.py`, which is a false
    positive that module records. A comprehension is neither.
    """
    assert frozenset(LicenseOutcome.values) == LICENSE_VOCABULARY


def test_the_pass_declares_its_table_and_contributes_no_rollup_column() -> None:
    """`CPM-AD-21`: this pass writes its own per-domain table and nothing else.

    The empty `contributes` is the assertion, not an omission: `core/rollup.py`
    offers no column for this domain and `CPM-AD-21` forbids adding one, so a
    pass that had grown a contribution would be writing the health rollup by
    proxy. Both halves are checked, because a misspelled column would be refused
    at registration while an *added* one would not.
    """
    assert LicensePass.name == POLICY_NAME
    assert LicensePass.derived_model is PackageLicense
    assert LicensePass.contributes == ()
    assert "licence_status" not in contributable_columns()
    assert "license_outcome" not in contributable_columns()


def test_the_pass_refuses_to_evaluate_before_it_was_prepared() -> None:
    """A caller driving the pass by hand has to prepare it, as the orchestration does.

    Unreachable through `core/policy_run.py`, which prepares every pass before
    the package loop -- and stated rather than assumed, because the alternative is
    an `AttributeError` on `None` in a caller that would learn nothing from it.
    """
    with pytest.raises(LicensePolicyError, match="before its parameter set was established"):
        LicensePass().evaluate(None, policy_run=None, evidence_cutoff=A_NAIVE_INSTANT)  # type: ignore[arg-type]


def test_a_version_that_records_no_rule_set_is_read_as_ruling_nothing() -> None:
    """The Never list's central rule: an unrecorded rule set must not refuse.

    `CPM-SECURITY-S04`'s sibling raised here, on the argument that failing the run
    would take the other domains' rows down with it. The argument is right about
    the harm and wrong about the containment: `core/policy_run.py` wraps every
    pass for one package in one transaction, so raising rolls those rows back
    anyway -- package by package, until the run finalizes `failed` having written
    nothing. The integration module asserts the consequence end to end; this is
    the unit half, which is that reading a version recording nothing is not an
    error at all.
    """
    policy_pass = LicensePass()
    policy_pass.parameters = PolicyParameters(version=A_VERSION, feedstock_inactivity=timedelta(days=30))

    rules = policy_pass._rules()  # noqa: SLF001 - the private half of the decision this case is about

    assert rules == ()
    assert finding_verdict(a_finding(), rules=rules) == MANUAL_REVIEW


# ---------------------------------------------------------------------------
# The derived table's declarations.
# ---------------------------------------------------------------------------


def test_every_column_this_pass_writes_is_uneditable() -> None:
    """`CPM-FR-37`: a derived verdict is a policy run's to write and nobody else's.

    Every column this pass writes, not only the one the naming convention
    reaches: `matched_rule` is deliberately not named for a status, and a form
    that could rewrite which rule permitted a package while leaving the outcome
    alone is a row that contradicts itself.
    """
    written = {"license_outcome", "matched_rule", "policy_version", "evidence_cutoff", "detail"}
    editable = {
        field.name
        for field in PackageLicense._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if field.name in written and field.editable
    }

    assert editable == set()


def test_the_copied_policy_version_column_is_as_wide_as_the_run_ledgers() -> None:
    """A column narrower than the run's own would truncate a version the ledger accepted.

    The two numbers are declared separately -- a version is operator data rather
    than a value from a closed vocabulary -- and this is what stops them drifting.
    """
    copied = PackageLicense._meta.get_field("policy_version")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    recorded = PolicyRun._meta.get_field("policy_version")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert copied.max_length == recorded.max_length


def test_the_matched_rule_column_offers_no_choices_and_holds_any_recorded_expression() -> None:
    """The rules are versioned data, so the set of values is a property of the run's version.

    Declaring `choices` here would freeze into code the licence policy PRD Open
    Question 2 says nobody has decided, which is the one thing shipping the rules
    as data avoids. The width is reconciled in both directions: the parameter
    reader refuses an expression this column could not hold, and the evidence
    column a rule is matched against is exactly as wide -- a rule that could not be
    matched against a stored expression is a rule nothing would ever apply.
    """
    column = PackageLicense._meta.get_field("matched_rule")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    evidence = LicenseFinding._meta.get_field("normalized_license")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert not column.choices
    assert column.max_length == MAX_LICENSE_EXPRESSION_CHARACTERS
    assert column.max_length == evidence.max_length


def test_the_judged_outcomes_are_the_four_a_finding_can_support() -> None:
    """`unknown` is deliberately absent from the constraint's set.

    Requiring a finding behind it would forbid exactly the row this vocabulary
    exists to make honest: a package with no licence evidence at all.
    `manual_review` is deliberately *inside* it, on the terms
    `ESTABLISHED_VULNERABILITY_STATUSES` records: it is the value a reader is
    least likely to check, because "somebody has to look at this" reads as a
    to-do rather than as the assertion that a licence was established.
    """
    assert set(JUDGED_LICENSE_OUTCOMES) == {ALLOWED, RESTRICTED, FORBIDDEN, MANUAL_REVIEW}
    assert LICENSE_STATUS_UNKNOWN not in JUDGED_LICENSE_OUTCOMES


def test_the_derived_table_declares_the_constraints_this_story_names() -> None:
    """Named constants and declarations cannot drift, because the case reads both.

    The integration module is what shows each of them refusing a row; this is
    what shows the names the cases assert against are the names the table
    carries.
    """
    declared = {constraint.name for constraint in PackageLicense._meta.constraints}  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert declared == {
        ONE_LICENSE_ROW_PER_PACKAGE_PER_RUN,
        THE_JUDGED_LICENSE_OUTCOME_NEEDS_ITS_FINDING,
        A_RULED_OUTCOME_NAMES_THE_RULE_THAT_PRODUCED_IT,
        A_MATCHED_RULE_ONLY_WHERE_A_RULE_DECIDED,
        LICENSE_ROW_NAMES_ITS_POLICY_VERSION,
    }


def test_the_row_renders_the_rule_beside_the_outcome() -> None:
    """This table's whole rule, applied to the one line a human is likeliest to read.

    Read off `package_id` rather than off `package`, so an unsaved instance
    renders rather than raising -- which is what keeps a debugger and a traceback
    working.
    """
    rendered = str(PackageLicense(license_outcome=ALLOWED, matched_rule=AN_EXPRESSION))

    assert ALLOWED in rendered
    assert AN_EXPRESSION in rendered
    assert "no package" in rendered


def test_an_empty_row_renders_every_absence_by_name() -> None:
    """The other half of `__str__`, and the reason each blank has words rather than nothing."""
    rendered = str(PackageLicense())

    assert "(no verdict)" in rendered
    assert "no rule" in rendered


# ---------------------------------------------------------------------------
# The reviewed rule set, as text.
# ---------------------------------------------------------------------------


def test_a_version_recording_rules_reads_them_back_in_order() -> None:
    """The parameter is a list of tables and each rule is a pair of strings.

    The order is preserved because the file states it, though nothing reads it as
    a ranking: `policies/parameters.py` refuses a duplicate expression, so at most
    one rule ever matches.
    """
    recorded = parameters_from(
        parameter_document({A_VERSION: 30}, license_rules=[(AN_EXPRESSION, ALLOWED), (ANOTHER_EXPRESSION, FORBIDDEN)]),
        source="a-fixture-file",
    )

    assert recorded[A_VERSION].license_rules == (
        LicenseRule(expression=AN_EXPRESSION, disposition=ALLOWED),
        LicenseRule(expression=ANOTHER_EXPRESSION, disposition=FORBIDDEN),
    )


@pytest.mark.parametrize(
    "rules",
    [None, ()],
    ids=["key-absent", "key-empty"],
)
def test_a_version_recording_no_rules_parses_to_the_same_empty_rule_set(
    rules: Sequence[tuple[str, str]] | None,
) -> None:
    """The two spellings of "no policy has been decided" mean one thing.

    A version recorded before `CPM-SECURITY-S05` cannot carry the key and must
    stay replayable; a version that means to record no rule writes `[]`. There is
    exactly one parsed state, so no verdict anywhere has to distinguish them --
    which is deliberately unlike `vulnerability_risk_order`, where an empty list
    is refused and `None` is therefore unambiguous.
    """
    recorded = parameters_from(parameter_document({A_VERSION: 30}, license_rules=rules), source="a-fixture-file")

    assert recorded[A_VERSION].license_rules == ()


@pytest.mark.parametrize(
    ("recorded", "fault"),
    [
        (f'{RULES_KEY} = "MIT"', "rather than a list"),
        (f"{RULES_KEY} = [1]", "int rather than a table"),
        (f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = "MIT" }}]', "rather than"),
        (
            f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = "MIT", {RULE_DISPOSITION_KEY} = "allowed", note = "x" }}]',
            "unrecognised",
        ),
        (
            f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = 1, {RULE_DISPOSITION_KEY} = "allowed" }}]',
            "int rather than a string",
        ),
        (f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = "  ", {RULE_DISPOSITION_KEY} = "allowed" }}]', "names nothing"),
        (f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = " MIT", {RULE_DISPOSITION_KEY} = "allowed" }}]', "whitespace"),
        (AN_OVERLONG_RULE, "longer than"),
        (f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = "MIT", {RULE_DISPOSITION_KEY} = 1 }}]', "rather than a string"),
        (
            f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = "MIT", {RULE_DISPOSITION_KEY} = "manual_review" }}]',
            "not one of",
        ),
        (f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = "MIT", {RULE_DISPOSITION_KEY} = "fine" }}]', "not one of"),
    ],
    ids=[
        "not-a-list",
        "not-a-table",
        "missing-disposition",
        "unrecognised-key",
        "expression-not-a-string",
        "expression-blank",
        "expression-untrimmed",
        "expression-too-long",
        "disposition-not-a-string",
        "disposition-manual-review",
        "disposition-from-nowhere",
    ],
)
def test_a_rule_set_nobody_could_apply_is_refused(recorded: str, fault: str) -> None:
    """Every way a reviewer can believe they recorded a compliance decision and not have.

    None of these is repaired and none is defaulted, on exactly the terms the
    threshold's own refusals state: coercion is how a rule nobody meant becomes a
    verdict about every package. `manual_review` is refused as a disposition
    specifically because it is the plausible mistake -- it is a real outcome, and
    a rule stating it would be a rule saying what a licence with no rule already
    says.
    """
    document = f'[versions."{A_VERSION}"]\nfeedstock_inactivity_days = 30\n{recorded}\n'

    with pytest.raises(PolicyParameterError, match=fault):
        parameters_from(document, source="a-fixture-file")


def test_two_rules_naming_one_licence_differently_are_refused_naming_both() -> None:
    """The matrix's "two rules name the same licence differently".

    A licence one rule allows while another forbids it has no verdict at all,
    only whichever rule a reader stopped at -- so it is refused rather than
    resolved, and the message names both dispositions, because which of two
    compliance decisions stands is a reviewer's to state and not this component's
    to guess.
    """
    document = (
        f'[versions."{A_VERSION}"]\nfeedstock_inactivity_days = 30\n'
        f"{RULES_KEY} = {license_rule_array([(AN_EXPRESSION, ALLOWED), (AN_EXPRESSION, FORBIDDEN)])}\n"
    )

    with pytest.raises(PolicyParameterError) as refused:
        parameters_from(document, source="a-fixture-file")

    assert ALLOWED in str(refused.value)
    assert FORBIDDEN in str(refused.value)


def test_two_rules_naming_one_licence_in_two_spellings_are_refused_too() -> None:
    """The match case-folds, so two spellings of one expression are one licence.

    A refusal that compared the recorded strings would let `MIT` and `mit` both
    stand while only one of them could ever match -- and which one would depend on
    the file's order, which nothing else in this contract makes meaningful.
    """
    document = (
        f'[versions."{A_VERSION}"]\nfeedstock_inactivity_days = 30\n'
        f"{RULES_KEY} = {license_rule_array([(AN_EXPRESSION, ALLOWED), (AN_EXPRESSION.lower(), ALLOWED)])}\n"
    )

    with pytest.raises(PolicyParameterError, match="more than once"):
        parameters_from(document, source="a-fixture-file")


def test_every_fault_in_one_rule_set_is_reported_at_once() -> None:
    """A reviewer told about one rule at a time edits the file three times to learn it had three mistakes."""
    document = (
        f'[versions."{A_VERSION}"]\nfeedstock_inactivity_days = 30\n'
        f'{RULES_KEY} = [{{ {RULE_EXPRESSION_KEY} = " MIT", {RULE_DISPOSITION_KEY} = "allowed" }}, '
        f'{{ {RULE_EXPRESSION_KEY} = "GPL-3.0-only", {RULE_DISPOSITION_KEY} = "fine" }}]\n'
    )

    with pytest.raises(PolicyParameterError) as refused:
        parameters_from(document, source="a-fixture-file")

    assert "surrounding whitespace" in str(refused.value)
    assert "not one of" in str(refused.value)


def test_the_faults_are_listed_in_the_order_the_file_states_the_rules() -> None:
    """`rule 10` after `rule 2`, which sorting the rendered clauses did not give.

    Deterministic either way, so nothing replayed differently -- and still an
    order nobody could follow down a twelve-rule list, on the one message whose
    whole purpose is that a reviewer can correct every fault in one pass. Eleven
    rules is the shortest list where the two orders differ.
    """
    faulty = [(AN_EXPRESSION, "fine")] * ELEVEN_RULES
    document = f'[versions."{A_VERSION}"]\nfeedstock_inactivity_days = 30\n{RULES_KEY} = {license_rule_array(faulty)}\n'

    with pytest.raises(PolicyParameterError) as refused:
        parameters_from(document, source="a-fixture-file")

    reported = str(refused.value)
    assert reported.index("rule 2 (") < reported.index("rule 10 (")


@pytest.mark.parametrize(
    "expression",
    ["GPL-3.0", "GPLv3", "AGPL-3.0", "LGPL-2.1"],
    ids=["gpl-3.0", "gplv3", "agpl-3.0", "lgpl-2.1"],
)
def test_a_rule_naming_a_licence_the_normalizer_cannot_produce_is_refused(expression: str) -> None:
    """**The silent failure an operator is least able to detect.**

    `normalized_license` is never free text: `collectors/spdx.py` writes an
    identifier from its own table or a compound of them, and the GNU family
    carries identifiers and no abbreviations at all -- `CPM-SECURITY-S03` removed
    those deliberately, because each names a version without an
    `-only`/`-or-later` disposition and is therefore two licences.

    So a reviewer writing `{ expression = "GPL-3.0", disposition = "forbidden" }`
    has forbidden nothing, permanently: no row can ever carry that string, every
    affected package reads `manual_review`, and `manual_review` is exactly what
    "no rule covers this" looks like. The deny half of a licence policy would fail
    with no refusal and no log line, which is the one failure mode nothing else
    here would surface.

    `GPL-3.0` is first because it is the spelling a reviewer is likeliest to
    write.
    """
    document = (
        f'[versions."{A_VERSION}"]\nfeedstock_inactivity_days = 30\n'
        f"{RULES_KEY} = {license_rule_array([(expression, FORBIDDEN)])}\n"
    )

    with pytest.raises(PolicyParameterError, match=re.escape("name nothing collectors/spdx.py normalizes to")):
        parameters_from(document, source="a-fixture-file")


@pytest.mark.parametrize(
    "expression",
    [
        "MIT AND GPL-3.0-only OR Apache-2.0",
        "(MIT OR Apache-2.0)",
        "Apache-2.0 WITH LLVM-exception",
        "MIT  OR  Apache-2.0",
        "MIT OR",
        "mit license",
    ],
    ids=["mixed-operators", "parenthesised", "with", "doubled-space", "dangling-operator", "a-spelling"],
)
def test_a_rule_naming_a_shape_the_normalizer_cannot_produce_is_refused_too(expression: str) -> None:
    """Every other way to write something no stored expression is ever spelled as.

    Each of these is a string `collectors/spdx.py` refuses outright or would
    rewrite, so no `license_findings` row can carry it: a mixed expression and a
    parenthesised one need a precedence that module will not invent, `WITH` names
    an exception identifier from a list it does not carry -- which is also the
    example this module's own docstring used to offer a reviewer -- a doubled
    space is not the single-space form it writes, a dangling operator is not an
    expression at all, and `mit license` is a *spelling* it normalizes away to
    `MIT` rather than a value it stores.
    """
    document = (
        f'[versions."{A_VERSION}"]\nfeedstock_inactivity_days = 30\n'
        f"{RULES_KEY} = {license_rule_array([(expression, FORBIDDEN)])}\n"
    )

    with pytest.raises(PolicyParameterError, match="rule 0"):
        parameters_from(document, source="a-fixture-file")


@pytest.mark.parametrize(
    "expression",
    ["MIT", "mit", "MIT OR Apache-2.0", "mit or apache-2.0", "MIT AND GPL-3.0-only"],
    ids=["identifier", "folded-identifier", "disjunction", "folded-disjunction", "conjunction"],
)
def test_a_rule_the_pass_could_match_is_recorded_and_not_refused(expression: str) -> None:
    """The other direction, and the one the refusal above could break.

    A check that refused more than the normalizer's own output would refuse rules
    that *work*, which is worse than the defect it fixes: a compliance decision a
    reviewer wrote and this component would not read. The folded spellings are
    here because `policies/licence.py` case-folds both sides of the comparison, so
    a lower-case rule does match a stored expression -- refusing it would be this
    contract demanding a spelling its own matcher does not.
    """
    document = (
        f'[versions."{A_VERSION}"]\nfeedstock_inactivity_days = 30\n'
        f"{RULES_KEY} = {license_rule_array([(expression, FORBIDDEN)])}\n"
    )

    recorded = parameters_from(document, source="a-fixture-file")

    assert recorded[A_VERSION].license_rules == (LicenseRule(expression=expression, disposition=FORBIDDEN),)


def test_what_a_rule_may_name_is_read_off_the_normalizers_own_table() -> None:
    """A second list of identifiers here would drift from the one that matters.

    What a rule has to be able to match is exactly what `collectors/spdx.py`
    writes, so the reachable operands are that module's *values* -- the SPDX
    identifiers -- and not its keys, which include every recognised spelling. A
    hand-written copy would refuse a rule naming a licence added to that table
    last week, or accept one naming a spelling that is normalized away.
    """
    assert {identifier.casefold() for identifier in SPELLINGS.values()} == NORMALIZABLE_IDENTIFIERS
    assert {operator.casefold() for operator in OPERATORS} == NORMALIZABLE_OPERATORS
    assert "mit license" not in NORMALIZABLE_IDENTIFIERS
    assert "mit" in NORMALIZABLE_IDENTIFIERS
