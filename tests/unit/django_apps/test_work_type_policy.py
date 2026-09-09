"""What a package's state recommends, and the two things the derivation may not look at.

`CPM-PRIORITY-S02` is one question -- given what the six domain passes concluded,
which of `CPM-FR-21`'s eight actions does this package need -- and all of it is a
pure function of one mapping. That is what this module measures. What needs a run --
the rows, the closed-set constraint, the rollup contribution, the registration
order -- is in `tests/integration/django_apps/test_work_type_policy.py`.

**The case this module exists for is the independence.** AC 1 is that a work type is
computable for a package in *any* priority bucket and that the two are not coupled,
and the strongest form that can take is a signature that is not offered a bucket. So
the derivation's parameters are swept here, and the module is swept for any mention
of the priority table at all.

**The second is the closed set.** The eight are PRD Appendix A.1's, transcribed in
`policies/outcomes.py`, and the transcription is checked here against the eight
words the PRD uses -- because a vocabulary that had quietly acquired a ninth value,
or lost one, would satisfy every derivation case in this file.

No database, no network: every verdict here is a literal mapping.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.rollup import contributable_columns
from conda_sentinel.policies.models import PackageWorkType
from conda_sentinel.policies.outcomes import ABSENT
from conda_sentinel.policies.outcomes import ADVISORIES_MATCHED
from conda_sentinel.policies.outcomes import ALREADY_TRACKED
from conda_sentinel.policies.outcomes import BEHIND
from conda_sentinel.policies.outcomes import CREATE_RECIPE
from conda_sentinel.policies.outcomes import CURRENT
from conda_sentinel.policies.outcomes import FILE_TRACKING_ISSUE
from conda_sentinel.policies.outcomes import FIX_VULNERABILITY
from conda_sentinel.policies.outcomes import FORBIDDEN
from conda_sentinel.policies.outcomes import INFERRED_NOT_READY
from conda_sentinel.policies.outcomes import INFERRED_READY
from conda_sentinel.policies.outcomes import MANUAL_REVIEW
from conda_sentinel.policies.outcomes import NO_ADVISORY_MATCHED
from conda_sentinel.policies.outcomes import PRESENT_AND_INACTIVE
from conda_sentinel.policies.outcomes import PRESENT_AND_MAINTAINED
from conda_sentinel.policies.outcomes import PY314_READINESS_UNKNOWN as PY314_UNKNOWN
from conda_sentinel.policies.outcomes import RESOLVE_IDENTITY
from conda_sentinel.policies.outcomes import RESTRICTED
from conda_sentinel.policies.outcomes import REVIEW_LICENSE
from conda_sentinel.policies.outcomes import UPDATE_FEEDSTOCK
from conda_sentinel.policies.outcomes import VALIDATE_PYTHON_314
from conda_sentinel.policies.outcomes import VERIFIED_NOT_READY
from conda_sentinel.policies.outcomes import VERIFIED_READY
from conda_sentinel.policies.outcomes import WORK_TYPE_LENGTH
from conda_sentinel.policies.outcomes import WORK_TYPE_UNKNOWN
from conda_sentinel.policies.outcomes import WORK_TYPES
from conda_sentinel.policies.outcomes import WorkType
from conda_sentinel.policies.priority import DOMAIN_READERS
from conda_sentinel.policies.work_type import NOTHING_RECOMMENDED_DETAIL
from conda_sentinel.policies.work_type import POLICY_NAME
from conda_sentinel.policies.work_type import ROLLUP_COLUMN
from conda_sentinel.policies.work_type import WORK_TYPE_PRECEDENCE
from conda_sentinel.policies.work_type import WorkTypePass
from conda_sentinel.policies.work_type import recommendation_for

#: This module's subject, for the source sweeps.
WORK_TYPE_MODULE: Final[Path] = (
    Path(__file__).resolve().parents[3] / "src" / "django_apps" / "conda_sentinel" / "policies" / "work_type.py"
)

#: `CPM-FR-21`'s closed set, transcribed here from PRD Appendix A.1's own words so
#: the vocabulary is checked against the requirement rather than against itself.
#:
#: The PRD writes them as prose -- "fix vulnerability · create recipe · ..." -- and
#: these are those eight phrases in the snake_case a stored value takes. A ninth
#: value, or a missing one, fails here whatever the derivation does.
THE_PRDS_EIGHT: Final[frozenset[str]] = frozenset(
    {
        "fix_vulnerability",
        "create_recipe",
        "file_tracking_issue",
        "already_tracked",
        "update_feedstock",
        "validate_python_314",
        "review_license",
        "resolve_identity",
    },
)

#: How many actions the set holds. Named because `PLR2004` is right about a bare
#: number in an assertion.
EIGHT_ACTIONS: Final[int] = 8

#: The two values no shipped derivation reaches, and why each is recorded rather
#: than guessed at. Held as a set so the "everything else is reachable" sweep below
#: is the complement of a decision rather than a list somebody maintained.
THE_UNREACHABLE_TWO: Final[frozenset[str]] = frozenset({ALREADY_TRACKED, RESOLVE_IDENTITY})


def _verdicts(**domains: str) -> dict[str, str]:
    """Return what the six domain passes concluded, as the reader hands it over.

    Args:
        **domains: The verdicts to record. Any domain not named is **absent**,
            which is what a pass that wrote no row produces.

    Returns:
        The mapping.

    """
    return dict(domains)


# ---------------------------------------------------------------------------
# AC 2: the closed set.
# ---------------------------------------------------------------------------


def test_the_vocabulary_is_the_prds_closed_set_of_eight() -> None:
    """AC 2's "the closed set", checked against the PRD's own words rather than itself.

    A vocabulary compared only with the derivation would agree with whatever it had
    drifted into. This compares it with the eight phrases Appendix A.1 lists.
    """
    assert set(WORK_TYPES) == THE_PRDS_EIGHT
    assert len(WORK_TYPES) == EIGHT_ACTIONS


def test_the_column_offers_the_eight_and_cores_four_sentinels_and_nothing_else() -> None:
    """The sentinels are what the column holds *besides* a work type.

    A derived row for a package nothing recommended an action for, and one the
    confidence gate replaced, both need a value -- and the gate's is `unknown`, so
    the vocabulary has to carry it.
    """
    assert set(WorkType.values) == THE_PRDS_EIGHT | {WORK_TYPE_UNKNOWN, "error", "not_found", "not_applicable"}


def test_the_gate_writes_a_value_this_columns_vocabulary_offers() -> None:
    """Why the vocabulary is composed rather than a bare `TextChoices`."""
    from conda_sentinel.core.confidence import GATED_VALUE  # noqa: PLC0415 - read beside the claim it is about

    assert GATED_VALUE in WorkType.values


@pytest.mark.parametrize("model", [PackageWorkType, PackageHealth], ids=["derived", "rollup"])
def test_both_columns_are_wide_enough_and_offer_the_same_vocabulary(model: type) -> None:
    """A column narrower than its own choices stores on SQLite and refuses on PostgreSQL.

    Args:
        model: The table carrying a work-type column.

    """
    name = ROLLUP_COLUMN if model is PackageHealth else "work_type"
    field = model._meta.get_field(name)  # noqa: SLF001 - Django's API

    assert field.max_length == WORK_TYPE_LENGTH
    assert max(len(value) for value in WorkType.values) <= WORK_TYPE_LENGTH
    assert {value for value, _label in field.choices} == set(WorkType.values)


# ---------------------------------------------------------------------------
# AC 1: independence from priority.
# ---------------------------------------------------------------------------


def test_the_derivation_is_not_offered_a_priority_bucket() -> None:
    """AC 1 in the strongest form a signature can state it.

    A derivation that *could* read a bucket and chose not to is a promise; one that
    cannot be handed one is a fact. Asserted over the real signature, so a parameter
    added later fails here rather than being noticed by a reader.
    """
    from inspect import signature  # noqa: PLC0415 - the signature is the subject

    parameters = set(signature(recommendation_for).parameters)

    assert parameters == {"verdicts"}


def test_the_module_mentions_no_priority_table_or_column() -> None:
    """The other half: nothing in the module reaches for one by another route.

    A source sweep rather than a behavioural check, because the failure it guards
    against is an import somebody *adds* -- and a work type derived from a bucket
    would still produce a work type, so every derivation case here would pass.
    """
    named = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(WORK_TYPE_MODULE.read_text(encoding="utf-8")))
        if isinstance(node, (ast.Name, ast.Attribute))
    }

    assert "PackagePriority" not in named
    assert "PriorityPass" not in named
    assert "priority_status" not in named
    assert "bucket" not in named


def test_the_module_tests_no_identity_confidence() -> None:
    """`CPM-AD-4`'s gate has one implementation, and this pass is not a second.

    `tests/unit/django_apps/test_confidence_gate_audit.py` sweeps every shipped
    module for this and would fail on a confidence test here. Asserted again in this
    file because *why* it is absent is this story's decision rather than that
    audit's: the value it would have derived, `resolve_identity`, is one the gate
    then erases from the rollup -- so the pass would be claiming something no queue
    ever sees.
    """
    source = WORK_TYPE_MODULE.read_text(encoding="utf-8")
    named = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Name, ast.Attribute))
    }

    assert "IdentityConfidence" not in named
    assert "confidence" not in named


# ---------------------------------------------------------------------------
# The derivation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        ({"vulnerability_status": ADVISORIES_MATCHED}, FIX_VULNERABILITY),
        ({"license_outcome": FORBIDDEN}, REVIEW_LICENSE),
        ({"license_outcome": RESTRICTED}, REVIEW_LICENSE),
        ({"license_outcome": MANUAL_REVIEW}, REVIEW_LICENSE),
        ({"feedstock_presence_status": ABSENT}, CREATE_RECIPE),
        ({"feedstock_presence_status": PRESENT_AND_INACTIVE}, UPDATE_FEEDSTOCK),
        ({"currency_status": BEHIND}, FILE_TRACKING_ISSUE),
        ({"python_readiness": INFERRED_READY}, VALIDATE_PYTHON_314),
        ({"python_readiness": VERIFIED_NOT_READY}, FILE_TRACKING_ISSUE),
    ],
    ids=[
        "matched-advisory",
        "forbidden-licence",
        "restricted-licence",
        "unruled-licence",
        "no-feedstock",
        "inactive-feedstock",
        "behind",
        "inferred-python",
        "failed-build",
    ],
)
def test_each_derived_state_recommends_the_action_it_names(verdicts: dict[str, str], expected: str) -> None:
    """One case per way a package earns a recommendation, in isolation.

    Args:
        verdicts: The single verdict under test.
        expected: The action it recommends.

    """
    work_type, detail = recommendation_for(_verdicts(**verdicts))

    assert work_type == expected
    assert detail != ""


def test_a_matched_advisory_outranks_everything_else() -> None:
    """The precedence, at the top: an advisory is the finding with a clock on it.

    Asserted against a package that qualifies for four recommendations at once,
    because a first-match derivation is only meaningfully ordered where more than one
    condition holds.
    """
    work_type, _ = recommendation_for(
        _verdicts(
            vulnerability_status=ADVISORIES_MATCHED,
            license_outcome=FORBIDDEN,
            feedstock_presence_status=ABSENT,
            currency_status=BEHIND,
        ),
    )

    assert work_type == FIX_VULNERABILITY


def test_a_licence_decision_outranks_the_packaging_actions() -> None:
    """There is no sense updating a feedstock for a package legal review will remove."""
    work_type, _ = recommendation_for(
        _verdicts(license_outcome=FORBIDDEN, feedstock_presence_status=ABSENT, currency_status=BEHIND),
    )

    assert work_type == REVIEW_LICENSE


def test_python_validation_outranks_the_catch_all() -> None:
    """The catch-all is last, or it makes everything below it unreachable.

    A package both behind and resting on an inference is told to verify: the
    specific action wins over "file a record about it".
    """
    work_type, _ = recommendation_for(
        _verdicts(currency_status=BEHIND, python_readiness=INFERRED_READY),
    )

    assert work_type == VALIDATE_PYTHON_314


def test_validation_is_recommended_for_an_inference_and_not_for_an_absence() -> None:
    """The correction an integration case forced, and the reason it is the right rule.

    An earlier shape read "every readiness but `verified_ready`", which is true of
    `unknown` -- and `unknown` is what `CPM-PY314-S03` writes for a package nobody
    has collected anything about. So a package this product had never observed was
    told to go and verify it.

    `CPM-FR-14` says the static pass "says where verification is worth spending",
    and it says so by reaching an *inferred* verdict. A package with no assessment
    is not one whose 3.14 story rests on a claim -- there is no claim. All four
    states are asserted, because the two that recommend nothing are the point.
    """
    assert recommendation_for(_verdicts(python_readiness=INFERRED_READY))[0] == VALIDATE_PYTHON_314
    assert recommendation_for(_verdicts(python_readiness=INFERRED_NOT_READY))[0] == VALIDATE_PYTHON_314
    assert recommendation_for(_verdicts(python_readiness=VERIFIED_READY))[0] == WORK_TYPE_UNKNOWN
    assert recommendation_for(_verdicts(python_readiness=PY314_UNKNOWN))[0] == WORK_TYPE_UNKNOWN


def test_a_build_that_ran_and_did_not_come_out_needs_a_record() -> None:
    """The catch-all reaching a readiness verdict: verified, and it failed.

    There is no "fix the build" in `CPM-FR-21`'s closed set, so what is wanted is a
    record -- and this product may not invent a ninth value to say otherwise.
    """
    assert recommendation_for(_verdicts(python_readiness=VERIFIED_NOT_READY))[0] == FILE_TRACKING_ISSUE


def test_a_package_in_good_order_is_recommended_nothing_and_the_row_says_why() -> None:
    """`unknown`, and the detail records that the closed set has no member for this.

    A package with nothing to act on and a package nothing is known about both land
    here, which is a gap in `CPM-FR-21`'s set rather than in this derivation.
    """
    work_type, detail = recommendation_for(
        _verdicts(
            currency_status=CURRENT,
            vulnerability_status=NO_ADVISORY_MATCHED,
            feedstock_presence_status=PRESENT_AND_MAINTAINED,
            python_readiness=VERIFIED_READY,
        ),
    )

    assert work_type == WORK_TYPE_UNKNOWN
    assert detail == NOTHING_RECOMMENDED_DETAIL


def test_a_package_nothing_was_established_about_is_recommended_nothing() -> None:
    """An empty mapping is what a package no pass wrote a row for produces."""
    work_type, _ = recommendation_for({})

    assert work_type == WORK_TYPE_UNKNOWN


def test_a_domain_with_no_row_recommends_nothing_from_that_domain() -> None:
    """An absent verdict is not a wildcard, on the terms the priority pass states."""
    work_type, _ = recommendation_for(_verdicts(currency_status=CURRENT))

    assert work_type == WORK_TYPE_UNKNOWN


# ---------------------------------------------------------------------------
# The precedence table itself.
# ---------------------------------------------------------------------------


def test_every_rule_reads_a_domain_some_pass_actually_answers() -> None:
    """A rule on a domain nothing answers would recommend nothing, for ever and silently.

    Reconciled against `policies/priority.py`'s reader table, which is where the
    binding from a domain name to a table and column lives -- one table, so the two
    passes cannot come to disagree about which column answers `license_outcome`.
    """
    answered = {reader.domain for reader in DOMAIN_READERS}

    for rule in WORK_TYPE_PRECEDENCE:
        assert rule.domain in answered, rule


def test_every_rule_recommends_one_of_the_closed_set() -> None:
    """A rule recommending a value outside the eight would be refused at the insert."""
    for rule in WORK_TYPE_PRECEDENCE:
        assert rule.work_type in WORK_TYPES, rule


def test_every_rule_states_a_reason() -> None:
    """The row's `detail` is what says which derived status recommended the action."""
    for rule in WORK_TYPE_PRECEDENCE:
        assert rule.reason.strip() != "", rule


def test_no_two_rules_recommend_the_same_action_from_the_same_domain() -> None:
    """Two rules over one domain and one action is one rule written twice.

    The second would be unreachable, and a reader counting down the table to find
    why a package was recommended something would land on the wrong one.
    """
    pairs = [(rule.domain, rule.work_type) for rule in WORK_TYPE_PRECEDENCE]

    assert len(pairs) == len(set(pairs))


def test_exactly_two_of_the_eight_are_unreachable_and_both_are_recorded() -> None:
    """The honest shipping state, asserted as the complement rather than as a list.

    Every value the table recommends is reachable. The two that are not are
    `already_tracked` -- which needs a workflow queue `CPM-EP-APP` has not built --
    and `resolve_identity`, which would need a second confidence gate. Asserting the
    *complement* is what makes a third value quietly becoming unreachable fail
    here.
    """
    reachable = {rule.work_type for rule in WORK_TYPE_PRECEDENCE}

    assert set(WORK_TYPES) - reachable == THE_UNREACHABLE_TWO


# ---------------------------------------------------------------------------
# The pass's declarations.
# ---------------------------------------------------------------------------


def test_the_pass_declares_its_name_its_table_and_the_one_column_it_contributes() -> None:
    """Three declarations, and the contributed column must be one the rollup offers."""
    assert WorkTypePass.name == POLICY_NAME
    assert WorkTypePass.derived_model is PackageWorkType
    assert WorkTypePass.contributes == (ROLLUP_COLUMN,)
    assert ROLLUP_COLUMN in contributable_columns()


def test_the_pass_overrides_no_prepare_because_it_reads_no_parameter() -> None:
    """The shape that says "this derivation is code, not versioned data".

    Asserted rather than implied: a `prepare` added later would mean a rule set
    somebody could change without a deployment, which is a different story from this
    one and would need the PRD to have left the derivation open.
    """
    assert "prepare" not in vars(WorkTypePass)


def test_a_naive_cutoff_is_refused_before_anything_is_read() -> None:
    """The one condition worth a raise: every instant this product records is aware.

    `core/policy_run.py` wraps every pass for one package in one transaction, so a
    raise here costs that package its other seven domains' rows -- which is why this
    pass refuses for nothing else. A naive cut-off earns it: it is a caller defect
    rather than a fact about the package.
    """
    from datetime import datetime  # noqa: PLC0415 - a naive instant is the subject

    from conda_sentinel.policies.work_type import WorkTypePolicyError  # noqa: PLC0415 - read beside its one raise

    naive = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - naive on purpose

    with pytest.raises(WorkTypePolicyError, match="carries no timezone"):
        WorkTypePass().evaluate(None, policy_run=None, evidence_cutoff=naive)  # type: ignore[arg-type]


def test_a_row_renders_the_work_type_it_recommends() -> None:
    """What an admin list and a debugger show, for an unsaved row.

    `package_id` and `policy_run_id` are the two that can be absent and both have
    their own wording: a row rendered inside a traceback is exactly the row whose
    relations are not there to follow.
    """
    rendered = str(PackageWorkType(work_type=FILE_TRACKING_ISSUE))

    assert FILE_TRACKING_ISSUE in rendered
    assert "no package" in rendered
    assert "no run" in rendered
