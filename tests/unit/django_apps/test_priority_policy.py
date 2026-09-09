"""What a priority rule matches, what a score is worth, and what neither may invent.

`CPM-PRIORITY-S01` is three questions and almost all of each is pure: which rule
matches a set of derived verdicts, what a set of usage signals scores, and how a
run's assignments order. That is what this module measures. What needs a run --
the rows, the constraints, the six reads against real derived tables, the rollup
contribution -- is in `tests/integration/django_apps/test_priority_policy.py`.

**The case this module exists for is that nothing is assigned by default.** The
shipped rule set is empty, and an empty rule set that quietly produced `p10` would
satisfy every other assertion here while putting the whole inventory into a bucket
nobody chose. Every path that fails to establish a bucket asserts `unknown` **and**
asserts the result is not any of the ten -- the second half deliberately, because a
vocabulary change that made `unknown` one of the buckets would satisfy the first
alone.

**The second is that a score is never invented.** A weighted signal that is `NULL`
produces no score, not zero, and the case asserts both.

No database, no network: every derived verdict here is a literal mapping and every
inventory observation is an unsaved model instance.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any
from typing import Final

import pytest

from conda_sentinel.collectors.models import InventorySnapshot
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.rollup import contributable_columns
from conda_sentinel.policies.models import MAX_PRIORITY_SCORE
from conda_sentinel.policies.models import MIN_PRIORITY_SCORE
from conda_sentinel.policies.models import PackagePriority
from conda_sentinel.policies.outcomes import PRIORITY_BUCKET_LENGTH
from conda_sentinel.policies.outcomes import PRIORITY_BUCKETS
from conda_sentinel.policies.outcomes import PRIORITY_STATUS_UNKNOWN
from conda_sentinel.policies.outcomes import PriorityBucket
from conda_sentinel.policies.parameters import MAX_PRIORITY_TEXT_CHARACTERS
from conda_sentinel.policies.parameters import MAX_SIGNAL_WEIGHT
from conda_sentinel.policies.parameters import PRIORITY_DOMAINS
from conda_sentinel.policies.parameters import PRIORITY_RULES_KEY
from conda_sentinel.policies.parameters import PRIORITY_SIGNALS
from conda_sentinel.policies.parameters import PRIORITY_WEIGHTS_KEY
from conda_sentinel.policies.parameters import PolicyParameterError
from conda_sentinel.policies.parameters import PriorityRule
from conda_sentinel.policies.parameters import parameters_from
from conda_sentinel.policies.priority import DOMAIN_READERS
from conda_sentinel.policies.priority import MISSING_SIGNAL_DETAIL
from conda_sentinel.policies.priority import NO_SCORE_FUNCTION_DETAIL
from conda_sentinel.policies.priority import NO_SIGNALS_DETAIL
from conda_sentinel.policies.priority import POLICY_NAME
from conda_sentinel.policies.priority import RANKING_ORDER
from conda_sentinel.policies.priority import ROLLUP_COLUMN
from conda_sentinel.policies.priority import PriorityPass
from conda_sentinel.policies.priority import PriorityPolicyError
from conda_sentinel.policies.priority import matching_rule
from conda_sentinel.policies.priority import ranking_order
from conda_sentinel.policies.priority import rule_label
from conda_sentinel.policies.priority import usage_score

#: What to call the file in a refusal the cases build by hand.
A_SOURCE: Final[str] = "a-fixture.toml"

#: A version key the hand-built parameter documents record under.
A_VERSION: Final[str] = "2026.09.3"

#: How many buckets `CPM-FR-20` states, and how many domains a rule may match on.
#: Named because `PLR2004` is right about a bare number in an assertion.
TEN_BUCKETS: Final[int] = 10
SIX_DOMAINS: Final[int] = 6

#: A weight and a count the score cases use, chosen so the arithmetic is checkable
#: by hand rather than by re-implementing the function.
A_WEIGHT: Final[int] = 1


def _document(**parameters: Any) -> str:
    """Return one hand-built parameter document, as TOML.

    Args:
        **parameters: The parameters the version records, already TOML-encoded as
            strings.

    Returns:
        The document text.

    """
    body = "\n".join(f"{key} = {value}" for key, value in parameters.items())
    return f'[versions."{A_VERSION}"]\nfeedstock_inactivity_days = 180\n{body}\n'


def _rules_from(rules: str) -> tuple[PriorityRule, ...]:
    """Parse one `priority_rules` value through the real reader.

    Args:
        rules: The TOML value to record.

    Returns:
        The rules the reader produced.

    """
    return parameters_from(_document(**{PRIORITY_RULES_KEY: rules}), source=A_SOURCE)[A_VERSION].priority_rules


def _weights_from(weights: str) -> tuple[tuple[str, int], ...]:
    """Parse one `priority_score_weights` value through the real reader.

    Args:
        weights: The TOML value to record.

    Returns:
        The weights the reader produced.

    """
    return parameters_from(_document(**{PRIORITY_WEIGHTS_KEY: weights}), source=A_SOURCE)[
        A_VERSION
    ].priority_score_weights


def _rule(bucket: str = "p1", **conditions: str) -> PriorityRule:
    """Return one rule, for the matching cases.

    Args:
        bucket: The bucket it assigns.
        **conditions: The verdicts that must all hold.

    Returns:
        The rule.

    """
    return PriorityRule(
        bucket=bucket,
        description="what this bucket means",
        reason="why this rule fires",
        conditions=tuple(conditions.items()),
    )


def _snapshot(**signals: int | None) -> InventorySnapshot:
    """Return an unsaved inventory observation carrying these signals.

    Args:
        **signals: The usage signals to record. Any not named are `None`, which is
            the state the score cases turn on.

    Returns:
        The unsaved row.

    """
    return InventorySnapshot(**signals)


# ---------------------------------------------------------------------------
# The vocabulary, and the thing it must never do by default.
# ---------------------------------------------------------------------------


def test_the_vocabulary_offers_ten_buckets_and_cores_four_sentinels() -> None:
    """`CPM-FR-20` says `P1`-`P10`, and the sentinels are what make the column gateable."""
    assert len(PRIORITY_BUCKETS) == TEN_BUCKETS
    assert tuple(f"p{number}" for number in range(1, TEN_BUCKETS + 1)) == PRIORITY_BUCKETS
    assert set(PriorityBucket.values) == set(PRIORITY_BUCKETS) | {
        PRIORITY_STATUS_UNKNOWN,
        "error",
        "not_found",
        "not_applicable",
    }


def test_the_unassigned_value_is_not_one_of_the_ten_buckets() -> None:
    """The property every "no bucket" case below rests on.

    Asserted once, here, rather than implied by each of them: if `unknown` ever
    became a bucket, every one of those cases would still pass and the whole
    inventory would be in a bucket nobody chose.
    """
    assert PRIORITY_STATUS_UNKNOWN not in PRIORITY_BUCKETS


def test_the_gate_writes_a_value_this_columns_vocabulary_offers() -> None:
    """Why the bucket vocabulary is composed rather than a bare `TextChoices`.

    `core/confidence.py`'s gate writes `unknown` into every contributed rollup
    column for an unmapped package, and `core/policy_run.py` refuses a value outside
    the column's own choices. A ten-value vocabulary would have made the gate write
    a value its own column does not offer -- so this is not a style point about
    sentinels, it is what lets the column be gated at all.
    """
    from conda_sentinel.core.confidence import GATED_VALUE  # noqa: PLC0415 - read beside the claim it is about

    assert GATED_VALUE in PriorityBucket.values


def test_the_rollup_column_is_wide_enough_and_offers_the_same_vocabulary() -> None:
    """A column narrower than its own choices stores on SQLite and refuses on PostgreSQL."""
    field = PackageHealth._meta.get_field(ROLLUP_COLUMN)  # noqa: SLF001 - Django's API

    assert field.max_length == PRIORITY_BUCKET_LENGTH
    assert max(len(value) for value in PriorityBucket.values) <= PRIORITY_BUCKET_LENGTH
    assert {value for value, _label in field.choices} == set(PriorityBucket.values)


def test_the_pass_declares_its_name_its_table_and_the_one_column_it_contributes() -> None:
    """Three declarations, and the contributed column must be one the rollup offers."""
    assert PriorityPass.name == POLICY_NAME
    assert PriorityPass.derived_model is PackagePriority
    assert PriorityPass.contributes == (ROLLUP_COLUMN,)
    assert ROLLUP_COLUMN in contributable_columns()


# ---------------------------------------------------------------------------
# The domains a rule may match on.
# ---------------------------------------------------------------------------


def test_the_domains_the_file_accepts_are_exactly_the_ones_the_pass_reads() -> None:
    """Reconciled in both directions, and nothing else would compare them.

    A domain the file accepts and nothing reads would match nothing, for ever and
    silently -- a reviewer would write the rule and watch it never fire. A domain
    the pass reads that the file refuses is unreachable. The two live in different
    modules on purpose (the file's validation must not import the pass), so this is
    the only place they meet.
    """
    assert {reader.domain for reader in DOMAIN_READERS} == PRIORITY_DOMAINS
    assert len(DOMAIN_READERS) == SIX_DOMAINS


def test_every_domain_reads_a_field_its_model_actually_declares() -> None:
    """A column renamed on a derived table would otherwise fail at the first run.

    `getattr` on a model instance raises nothing useful for a field that does not
    exist -- it raises `AttributeError` several frames into the pass -- so the
    binding is checked against each model's own `_meta` here instead.
    """
    for reader in DOMAIN_READERS:
        assert reader.model._meta.get_field(reader.column) is not None, reader  # noqa: SLF001 - Django's API


# ---------------------------------------------------------------------------
# Matching: top down, first match wins.
# ---------------------------------------------------------------------------


def test_no_rules_match_nothing() -> None:
    """The shipped state: an empty rule set matches no package."""
    assert matching_rule((), {"currency_status": "behind"}) is None


def test_the_first_matching_rule_wins() -> None:
    """`CPM-FR-20`'s "top-down first-match", and the order is the file's.

    Both rules match, so a reader that took the last or the most specific would
    still produce a bucket -- and would produce a different one. The position is
    asserted with the rule, because the position is what the row records.
    """
    first = _rule(bucket="p1", currency_status="behind")
    second = _rule(bucket="p5", currency_status="behind")

    matched = matching_rule((first, second), {"currency_status": "behind"})

    assert matched == (0, first)


def test_every_condition_must_hold() -> None:
    """A rule's `when` is a conjunction, so one unmet condition is no match."""
    rule = _rule(currency_status="behind", vulnerability_status="advisories_matched")

    assert matching_rule((rule,), {"currency_status": "behind"}) is None
    assert matching_rule(
        (rule,),
        {"currency_status": "behind", "vulnerability_status": "advisories_matched"},
    ) == (0, rule)


def test_a_domain_with_no_row_is_absent_rather_than_a_wildcard() -> None:
    """An earlier pass that wrote no row for this package is not a rule that matches.

    The distinction a `dict.get` returning `None` would erase if the comparison were
    written the other way round: a rule naming a domain nothing answered must not
    fire, because the verdict it requires was never established.
    """
    rule = _rule(license_outcome="allowed")

    assert matching_rule((rule,), {}) is None


def test_the_matched_rule_is_named_by_the_position_a_reviewer_counts() -> None:
    """One-based, because the row is read by whoever has to open the file."""
    assert rule_label(0) == "rule 1"
    assert rule_label(9) == "rule 10"


# ---------------------------------------------------------------------------
# The score.
# ---------------------------------------------------------------------------


def test_no_weights_means_no_score_and_says_so() -> None:
    """The shipped state, and `None` rather than zero."""
    score, detail = usage_score((), _snapshot(internal_component_count=5))

    assert score is None
    assert detail == NO_SCORE_FUNCTION_DETAIL


def test_no_observation_means_no_score_and_says_so() -> None:
    """An absence of an observation is not a package with no usage."""
    score, detail = usage_score((("internal_component_count", A_WEIGHT),), None)

    assert score is None
    assert detail == NO_SIGNALS_DETAIL


def test_a_missing_weighted_signal_produces_no_score_and_names_it() -> None:
    """The case this function exists for: blank means missing and is never invented.

    A score that read the missing signal as zero would rank a package this product
    has observed nothing about *below* one it has. Both halves asserted -- no score,
    and not a score of zero -- because a function that returned `0` would satisfy
    "not the full score" while making exactly that claim.
    """
    score, detail = usage_score(
        (("internal_component_count", A_WEIGHT), ("apps", A_WEIGHT)),
        _snapshot(internal_component_count=5),
    )

    assert score is None
    assert score != 0
    assert "apps" in detail
    assert detail == MISSING_SIGNAL_DETAIL.format(signals=["apps"])


def test_a_score_lands_inside_the_stated_range() -> None:
    """`CPM-FR-20` says 1-100, and both ends are bounded.

    The low end is the one that matters: a package observed with zero components
    still scores `1`, because it was observed. `0` is what an unobserved package
    would score if this function invented one, and the table refuses it outright.
    """
    weights = (("internal_component_count", A_WEIGHT),)

    lowest, _ = usage_score(weights, _snapshot(internal_component_count=0))
    highest, _ = usage_score(weights, _snapshot(internal_component_count=10_000))

    assert lowest == MIN_PRIORITY_SCORE
    assert highest == MAX_PRIORITY_SCORE


def test_a_higher_count_never_scores_lower() -> None:
    """Monotonic in the signal, which is the whole of what "ranks by usage" means.

    Asserted over a sweep rather than two points, because a scaling bug that
    inverted or wrapped would pass a two-point check at the ends.
    """
    weights = (("internal_component_count", A_WEIGHT),)
    scores = [usage_score(weights, _snapshot(internal_component_count=count))[0] for count in range(0, 200, 7)]

    assert all(earlier is not None and later is not None and earlier <= later for earlier, later in pairwise(scores))


def test_weights_that_are_all_zero_produce_no_score() -> None:
    """A recorded function that weights nothing has decided nothing.

    Zero weights are individually legal -- a reviewer may switch a signal off -- but
    a set of them that sums to zero cannot rank anything, and returning `1` for
    every package would look like a score.
    """
    score, detail = usage_score((("internal_component_count", 0),), _snapshot(internal_component_count=5))

    assert score is None
    assert detail == NO_SCORE_FUNCTION_DETAIL


# ---------------------------------------------------------------------------
# The ordering rank is derived from.
# ---------------------------------------------------------------------------


def test_the_ranking_is_total_so_it_is_stable_within_a_run() -> None:
    """AC 1's "stable for a given policy run", and the package key is what makes it so.

    Bucket and score alone leave ties, and two read surfaces paginating a tied
    ordering disagree about which package comes first -- silently, and only on some
    pages. The third term is not decoration.
    """
    assert ranking_order() == RANKING_ORDER
    assert RANKING_ORDER[0] == "bucket"
    assert RANKING_ORDER[1] == "-score"
    assert RANKING_ORDER[-1] == "package_id"


def test_the_ranking_is_expressible_against_the_derived_table() -> None:
    """Every term names a real field, so the ordering cannot be a string nothing accepts."""
    fields = {field.name for field in PackagePriority._meta.get_fields()}  # noqa: SLF001 - Django's API

    for term in RANKING_ORDER:
        assert term.lstrip("-").removesuffix("_id") in fields, term


# ---------------------------------------------------------------------------
# What the parameter file refuses.
# ---------------------------------------------------------------------------


def test_the_shipped_file_records_an_empty_rule_set_and_no_score_function() -> None:
    """The shipped state, read through the real loader from the real file.

    Asserted against the file this component ships rather than a fixture, because
    what the story promises is that *this repository* seeds nothing.
    """
    from conda_sentinel.policies.parameters import parameters_file  # noqa: PLC0415 - read beside the claim
    from conda_sentinel.policies.parameters import parameters_for  # noqa: PLC0415 - read beside the claim

    recorded = parameters_for("2026.09.3")

    assert parameters_file().exists()
    assert recorded.priority_rules == ()
    assert recorded.priority_score_weights == ()


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        ('"not a list"', "rather than a list of rules"),
        ("[1]", "rather than a table"),
        ('[{ bucket = "p1" }]', "rather than exactly"),
        (
            '[{ bucket = "p11", description = "d", reason = "r", when = { currency_status = "behind" } }]',
            "not one of",
        ),
        (
            '[{ bucket = "p1", description = "", reason = "r", when = { currency_status = "behind" } }]',
            "cannot explain itself",
        ),
        (
            '[{ bucket = "p1", description = "d", reason = "", when = { currency_status = "behind" } }]',
            "cannot explain itself",
        ),
        ('[{ bucket = "p1", description = "d", reason = "r", when = {} }]', "would match every package"),
        (
            '[{ bucket = "p1", description = "d", reason = "r", when = { nonsense = "x" } }]',
            "which no policy pass answers",
        ),
        (
            '[{ bucket = "p1", description = "d", reason = "r", when = { currency_status = "" } }]',
            "non-string or blank verdict",
        ),
        (
            '[{ bucket = "p1", description = "d", reason = "r", when = "not a table" }]',
            "rather than a table",
        ),
        (
            (
                f'[{{ bucket = "p1", description = "{"d" * (MAX_PRIORITY_TEXT_CHARACTERS + 1)}", '
                'reason = "r", when = { currency_status = "behind" } }]'
            ),
            "and the column that stores it takes",
        ),
    ],
    ids=[
        "not-a-list",
        "not-a-table",
        "missing-keys",
        "unknown-bucket",
        "blank-description",
        "blank-reason",
        "empty-when",
        "unknown-domain",
        "blank-verdict",
        "when-not-a-table",
        "over-wide-description",
    ],
)
def test_a_rule_nobody_could_apply_is_refused_where_a_reviewer_can_see_it(rules: str, expected: str) -> None:
    """Every way a rule can be unusable, refused at the read rather than at the run.

    The blank description and the blank reason are the two worth naming: a rule that
    assigns a bucket and explains nothing is exactly the row `CPM-PRIORITY-S01`
    exists to prevent, and it is the *reviewer* who would have left the explanation
    out -- so the refusal has to reach them.

    Args:
        rules: The `priority_rules` value the file records.
        expected: What the refusal says.

    """
    with pytest.raises(PolicyParameterError, match=expected):
        _rules_from(rules)


def test_a_usable_rule_set_parses_in_the_order_the_file_states_it() -> None:
    """The order is the policy, so it survives the read unchanged."""
    parsed = _rules_from(
        '[{ bucket = "p3", description = "d3", reason = "r3", when = { currency_status = "behind" } },'
        '{ bucket = "p1", description = "d1", reason = "r1", when = { license_outcome = "forbidden" } }]',
    )

    assert [rule.bucket for rule in parsed] == ["p3", "p1"]
    assert parsed[0].conditions == (("currency_status", "behind"),)


@pytest.mark.parametrize(
    ("weights", "expected"),
    [
        ('"not a table"', "rather than a table"),
        ("{ nonsense = 1 }", "which the inventory does not observe"),
        ("{ internal_component_count = -1 }", "unusable weights"),
        ('{ internal_component_count = "three" }', "unusable weights"),
        (f"{{ internal_component_count = {MAX_SIGNAL_WEIGHT + 1} }}", "unusable weights"),
    ],
    ids=["not-a-table", "unknown-signal", "negative", "not-a-number", "too-large"],
)
def test_a_score_function_nobody_could_compute_is_refused(weights: str, expected: str) -> None:
    """A weight on a signal nothing observes contributes nothing to every score, silently.

    Args:
        weights: The `priority_score_weights` value the file records.
        expected: What the refusal says.

    """
    with pytest.raises(PolicyParameterError, match=expected):
        _weights_from(weights)


def test_the_signals_a_weight_may_name_are_the_ones_the_inventory_observes() -> None:
    """Reconciled against `InventorySnapshot`'s own fields, not against a list written here.

    A signal added to the inventory and not to this set could never be weighted; one
    named here and absent from the table would be refused at every score with an
    `AttributeError`.
    """
    fields = {field.name for field in InventorySnapshot._meta.get_fields()}  # noqa: SLF001 - Django's API

    assert fields >= PRIORITY_SIGNALS


# ---------------------------------------------------------------------------
# The pass's refusals.
# ---------------------------------------------------------------------------


def test_evaluating_before_prepare_is_refused_rather_than_assigning_from_no_policy() -> None:
    """A bucket assigned without a parameter set would be a bucket from no policy at all."""
    with pytest.raises(PriorityPolicyError, match="before prepare"):
        PriorityPass()._parameters()  # noqa: SLF001 - the guard under test


def test_a_naive_cutoff_is_refused_before_anything_is_read() -> None:
    """The one other condition worth a raise: every observation instant is aware."""
    from datetime import datetime  # noqa: PLC0415 - a naive instant is the subject

    naive = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - naive on purpose

    with pytest.raises(PriorityPolicyError, match="carries no timezone"):
        PriorityPass().evaluate(None, policy_run=None, evidence_cutoff=naive)  # type: ignore[arg-type]


def test_the_pass_reads_no_other_passs_derived_table_outside_its_own_run() -> None:
    """Every read filters on the run, which is what keeps a replay stateable.

    A source check rather than a behavioural one, because the failure it guards
    against is a filter somebody *removes*: a read that took the newest row per
    package would pass every case in the integration tier that uses a single run,
    and would silently derive today's bucket from yesterday's verdicts.
    """
    from pathlib import Path  # noqa: PLC0415 - a source sweep needs the path

    source = Path(__file__).resolve().parents[3] / "src" / "django_apps" / "conda_sentinel" / "policies" / "priority.py"
    body = source.read_text(encoding="utf-8")

    assert "policy_run_id=policy_run_id" in body
    assert body.count("filter(package_id=package_id") == body.count("filter(package_id=package_id, policy_run_id=")


def test_a_row_renders_the_bucket_and_the_score_it_carries() -> None:
    """What an admin list and a debugger show, for an unsaved row.

    `package_id` and `policy_run_id` are the two that can be absent and both have
    their own wording, and an absent score reads `unscored` rather than as a blank:
    a row rendered inside a traceback is exactly the row whose relations are not
    there to follow.
    """
    rendered = str(PackagePriority(bucket="p1", score=42))
    unscored = str(PackagePriority(bucket=PRIORITY_STATUS_UNKNOWN))

    assert "p1" in rendered
    assert "score 42" in rendered
    assert "no package" in rendered
    assert "no run" in rendered
    assert "unscored" in unscored
