"""`CPM-FR-41`'s readiness vocabulary and the comparison it rests on, without a database.

`policies/remediation.py` is split into queries and arithmetic on exactly the
terms its four siblings are: `current_findings` and `read_surface` are the only
functions that touch the database, and everything that *decides* anything takes
evidence rows and returns a value. That split is what lets every row of the
story's I/O matrix that is about a decision be exercised here, in milliseconds,
against constructed observations -- and it is why the integration module beside
this one is about the orchestration, the constraints, the cut-off, staleness
against a real freshness target and the replay rather than about the rules.

**The story's central property is asserted in both tiers, and neither assertion
is the whole of it.** Here it is structural and exhaustive: `finding_readiness`
reaches `blocked` from four `not_published` readings and from nowhere else, and
every other shape -- including the one with three surfaces read and one not -- is
enumerated and required to answer `unknown`. In the integration module it is
behavioural, driven through `evaluate`.

**And here is where the consequence is pinned: no reading this pass can produce
is `not_published`, so `blocked` is unreachable through the pass today.**
`test_no_evidence_this_pass_reads_can_establish_that_a_surface_lacks_the_fix`
below asserts that directly rather than leaving it to be discovered from four
passing cases, because the honest shipping state of this story is a defined,
guarded verdict that nothing currently reaches -- not a verdict reached from an
absence. The two changes that would restore it are named in
`policies/remediation.py`'s module docstring and in the story's deferred list.

**Unsaved model instances, and that is what keeps this a unit test.** A
`VulnerabilityFinding` and a snapshot are constructed and never saved: `_meta` is
populated at import, the fields hold whatever they were given, and nothing here
opens a connection. It is also the only way to build the rows the database
refuses -- a state outside the vocabulary, the `not_applicable` the table forbids
outright -- which are exactly the rows this pass must not read as an absence.

No database, no network, no subprocess, no filesystem.
"""

from __future__ import annotations

import ast
import importlib
import json
import pathlib
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.db.models import Q

from conda_sentinel.collectors.conda_package import CONDA_PACKAGE_FRESHNESS_TARGET
from conda_sentinel.collectors.conda_package import CondaPackageCollector
from conda_sentinel.collectors.models import CondaPackageSnapshot
from conda_sentinel.collectors.models import FeedstockSnapshot
from conda_sentinel.collectors.models import PyPIReleaseSnapshot
from conda_sentinel.collectors.models import SourceReleaseSnapshot
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.collectors.outcomes import MATCHED
from conda_sentinel.collectors.outcomes import VULNERABILITY_ERROR
from conda_sentinel.collectors.outcomes import VULNERABILITY_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import VULNERABILITY_NOT_FOUND
from conda_sentinel.collectors.outcomes import VULNERABILITY_UNKNOWN
from conda_sentinel.collectors.vulnerability import ADVISORY_ID_FIELD
from conda_sentinel.collectors.vulnerability import AFFECTED_RANGE_FIELD
from conda_sentinel.collectors.vulnerability import FINDINGS_FIELD
from conda_sentinel.collectors.vulnerability import FIXED_RANGE_FIELD
from conda_sentinel.collectors.vulnerability import IDENTIFIED_FIELD
from conda_sentinel.collectors.vulnerability import MATCH_CONFIDENCE_FIELD
from conda_sentinel.collectors.vulnerability import NO_FIXED_RANGE_DETAIL
from conda_sentinel.collectors.vulnerability import NOTHING_MATCHED_DETAIL
from conda_sentinel.collectors.vulnerability import SEVERITY_FIELD
from conda_sentinel.collectors.vulnerability import UNIDENTIFIED_DETAIL
from conda_sentinel.collectors.vulnerability import VULNERABILITY_FRESHNESS_TARGET
from conda_sentinel.collectors.vulnerability import findings_in
from conda_sentinel.core.outcomes import SENTINEL_MEMBERS
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.outcomes import OutcomeVocabularyError
from conda_sentinel.core.outcomes import verify_sentinels
from conda_sentinel.core.rollup import contributable_columns
from conda_sentinel.identity.models import VersionSurface
from conda_sentinel.policies.models import A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ
from conda_sentinel.policies.models import A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION
from conda_sentinel.policies.models import A_DETERMINATE_READINESS_NEEDS_ITS_FINDING
from conda_sentinel.policies.models import A_READY_ROW_NAMES_THE_CHANNEL_THAT_CARRIES_THE_FIX
from conda_sentinel.policies.models import AN_AWAITING_BUILD_ROW_NAMES_THE_RECIPE_THAT_CARRIES_THE_FIX
from conda_sentinel.policies.models import AN_AWAITING_PACKAGING_ROW_NAMES_THE_RELEASE_THAT_CARRIES_THE_FIX
from conda_sentinel.policies.models import DETERMINATE_READINESS_VERDICTS
from conda_sentinel.policies.models import ONE_REMEDIATION_ROW_PER_PACKAGE_PER_RUN
from conda_sentinel.policies.models import REMEDIATION_ROW_NAMES_ITS_POLICY_VERSION
from conda_sentinel.policies.models import SURFACE_FIX_FIELDS
from conda_sentinel.policies.models import PackageRemediation
from conda_sentinel.policies.outcomes import AWAITING_BUILD
from conda_sentinel.policies.outcomes import AWAITING_PACKAGING
from conda_sentinel.policies.outcomes import BLOCKED
from conda_sentinel.policies.outcomes import FIX_AVAILABILITY_LENGTH
from conda_sentinel.policies.outcomes import FIX_NOT_PUBLISHED
from conda_sentinel.policies.outcomes import FIX_PUBLISHED
from conda_sentinel.policies.outcomes import READINESS_ERROR
from conda_sentinel.policies.outcomes import READINESS_NOT_APPLICABLE
from conda_sentinel.policies.outcomes import READINESS_NOT_FOUND
from conda_sentinel.policies.outcomes import READINESS_PRECEDENCE
from conda_sentinel.policies.outcomes import READINESS_STATE_LENGTH
from conda_sentinel.policies.outcomes import READINESS_UNKNOWN
from conda_sentinel.policies.outcomes import READY
from conda_sentinel.policies.outcomes import SURFACE_NOT_READ
from conda_sentinel.policies.outcomes import FixAvailability
from conda_sentinel.policies.outcomes import RemediationReadiness
from conda_sentinel.policies.outcomes import worst_readiness
from conda_sentinel.policies.remediation import ADVISORY_EVIDENCE
from conda_sentinel.policies.remediation import ADVISORY_VOCABULARY
from conda_sentinel.policies.remediation import EQUALITY_ONLY_DETAIL
from conda_sentinel.policies.remediation import NO_ADVISORY_EVIDENCE_DETAIL
from conda_sentinel.policies.remediation import NO_ADVISORY_FRESHNESS_TARGET_DETAIL
from conda_sentinel.policies.remediation import NO_FIX_RECORDED_DETAIL
from conda_sentinel.policies.remediation import NO_FRESHNESS_TARGET_DETAIL
from conda_sentinel.policies.remediation import NO_MATCHED_ADVISORY_DETAIL
from conda_sentinel.policies.remediation import NOT_COMPARABLE
from conda_sentinel.policies.remediation import ORDERING_MARKERS
from conda_sentinel.policies.remediation import POLICY_NAME
from conda_sentinel.policies.remediation import READ_ORDERING
from conda_sentinel.policies.remediation import READINESS_BY_SURFACE
from conda_sentinel.policies.remediation import RECORDED
from conda_sentinel.policies.remediation import SEVERAL_FINDINGS_DETAIL
from conda_sentinel.policies.remediation import STALE_ADVISORY_DETAIL
from conda_sentinel.policies.remediation import STALE_SURFACES_DETAIL
from conda_sentinel.policies.remediation import SURFACE_READERS
from conda_sentinel.policies.remediation import UNCOMPARABLE_FIX_DETAIL
from conda_sentinel.policies.remediation import UNESTABLISHED_ADVISORY_EVIDENCE_DETAIL
from conda_sentinel.policies.remediation import UNREAD_SURFACES_DETAIL
from conda_sentinel.policies.remediation import UNRECORDED
from conda_sentinel.policies.remediation import WITHIN_A_SWEEP
from conda_sentinel.policies.remediation import AdvisoryReading
from conda_sentinel.policies.remediation import RemediationPass
from conda_sentinel.policies.remediation import RemediationPolicyError
from conda_sentinel.policies.remediation import SurfaceReading
from conda_sentinel.policies.remediation import advisory_reading
from conda_sentinel.policies.remediation import current_findings
from conda_sentinel.policies.remediation import evidence_is_stale
from conda_sentinel.policies.remediation import finding_readiness
from conda_sentinel.policies.remediation import fixed_version
from conda_sentinel.policies.remediation import freshness_target
from conda_sentinel.policies.remediation import matched_findings
from conda_sentinel.policies.remediation import remediation_detail
from conda_sentinel.policies.remediation import stated_versions
from conda_sentinel.policies.remediation import supporting_finding
from conda_sentinel.policies.remediation import surface_availability
from conda_sentinel.policies.remediation import unestablished_findings
from conda_sentinel.policies.remediation import unordered_statements
from tests.clocks import FIXED_INSTANT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from conda_sentinel.policies.currency import SnapshotModel

#: The version most cases look for. Spelled as a source spells a bare fix.
A_FIXED_VERSION: Final[str] = "1.2.3"

#: A version that is not the fix, and is *later* than it. A surface stating it has
#: established nothing: this product cannot decide that it supersedes the fix, and
#: the version a surface states is its *latest* rather than the set it carries, so
#: the surface reads `not_read` with the comparison recorded on the row.
A_LATER_VERSION: Final[str] = "1.2.4"

#: A version that is not the fix and is *earlier* than it -- the genuinely-behind
#: case, which no case exercised while every one of them used a later version and
#: the two were treated identically anyway. Named separately so the day a
#: version-ordering rule arrives, the case that has to change is findable.
AN_OLDER_VERSION: Final[str] = "1.2.2"

#: The advisory sweep read as fresh. Every `remediation_detail` case that is not
#: about advisory freshness passes this, so a case never asserts a line by
#: accident of the default.
A_FRESH_ADVISORY: Final = AdvisoryReading(stale=False, target_declared=True)

#: A naive instant, for the cut-off refusal. Naive is the whole of what makes it
#: unusable: there is no offset to interpret, so the read would be shifted by
#: whichever offset the reader happened to be in.
A_NAIVE_INSTANT: Final = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - naive on purpose; it is the subject

#: A package primary key for the read refusal, which never reaches a query.
A_PACKAGE_ID: Final[int] = 1

#: A state no `VulnerabilityOutcome` member carries. `vulnerability_findings`
#: declares `choices`, which Django does not enforce on `save()`, so the value is
#: reachable in Python and this is the only place it can be built.
A_STATE_FROM_NOWHERE: Final[str] = "probably_fine"

#: How many matched findings the several-findings case reduces.
TWO_FINDINGS: Final[int] = 2

#: How many surfaces there are, so the assertions about totality read as the count
#: they are rather than as a magic number.
FOUR_SURFACES: Final[int] = 4


def a_finding(
    *,
    state: str = MATCHED,
    fixed_range: str = A_FIXED_VERSION,
    detail: str = "",
    pk: int = 1,
    observed_at: datetime = FIXED_INSTANT,
) -> VulnerabilityFinding:
    """Build one unsaved advisory finding.

    Args:
        state: What the lookup concluded.
        fixed_range: The versions the source says carry the fix, as it wrote them.
        detail: What the collector had to say -- the seam that says whether an
            `unknown` row was read and matched nothing or established nothing.
        pk: The primary key, so a case can tell two findings apart in a message
            and in a reference.
        observed_at: When the sweep this row belongs to was taken, which is what
            its own freshness is measured from.

    Returns:
        The unsaved row. Never saved: the table's own constraints would refuse
        several of these, and the rows it refuses are exactly the ones a readiness
        must not be derived from.

    """
    determinate = state == MATCHED
    finding = VulnerabilityFinding(
        state=state,
        advisory_id="CPM-FIXTURE-1" if determinate else "",
        affected_range="<1.2.3" if determinate else "",
        fixed_range=fixed_range if determinate else "",
        matched_version="1.2.0" if determinate else "",
        match_confidence="exact-version" if determinate else "",
        detail=detail,
        observed_at=observed_at,
    )
    finding.pk = pk
    return finding


def a_matched_nothing_finding(*, pk: int = 1) -> VulnerabilityFinding:
    """Build the one `unknown` row that establishes there is nothing to remediate.

    The advisory collector writes three different `unknown` rows and only this one
    -- "read and matched nothing" -- says the package has no matched advisory. A
    helper rather than a keyword at each call site, because a case that forgot the
    `detail` would silently become a case about a *different* row.

    Args:
        pk: The primary key.

    Returns:
        The unsaved row.

    """
    return a_finding(state=VULNERABILITY_UNKNOWN, detail=NOTHING_MATCHED_DETAIL, pk=pk)


def a_reading(  # noqa: PLR0913 - one keyword per property of a sweep a case varies; a bundle would hide which
    surface: str,
    *,
    versions: Sequence[str] = (),
    state: str = OutcomeState.OK.value,
    states: Sequence[str] = (),
    stale: bool = False,
    target_declared: bool = True,
) -> SurfaceReading:
    """Build one surface reading over unsaved observations.

    **`states` exists because `state` alone made a mixed sweep unconstructible.**
    `conda_package_snapshots` holds one row per `(channel, platform)` pair and each
    row carries its own outcome, so "conda-forge errored and bioconda answered" is
    an ordinary sweep -- and a helper that applied one state to every row is a
    helper under which the case could not be written at all.

    Args:
        surface: The `VersionSurface` value this is about.
        versions: One version per observation of the sweep. Several is the
            `conda_package_snapshots` shape -- one row per `(channel, platform)`
            pair -- and is what the single-row read this pass refuses would lose.
        state: The state every observation carries, where `states` is not given.
        states: One state per observation, positionally. Overrides `state`.
        stale: Whether the sweep is past its collector's freshness target.
        target_declared: Whether a registered collector declared one at all.

    Returns:
        The reading. Its observations are never saved.

    """
    reader = next(entry for entry in SURFACE_READERS if entry.surface == surface)
    per_row = list(states) if states else [state] * len(versions)
    observations: list[SnapshotModel] = []
    for index, (version, row_state) in enumerate(zip(versions, per_row, strict=True), start=1):
        observation = reader.model(state=row_state, **{reader.version_field: version})
        observation.pk = index
        observations.append(observation)
    return SurfaceReading(
        surface=surface,
        observations=tuple(observations),
        version_field=reader.version_field,
        stale=stale,
        target_declared=target_declared,
    )


def a_recorded_absence_clause(*, fixed_range: str) -> str:
    """Return the `detail` the shipped advisory collector writes for one finding.

    Driven through `findings_in` -- the collector's own document reader -- rather
    than restated here, because what this is evidence *of* is the collector's
    actual behaviour: the clause tracks the field being blank and nothing else.
    Pure: a JSON string in, an unsaved `Finding` out, no database and no network.

    Args:
        fixed_range: What the source states as the fixed range, blank for a source
            that states none.

    Returns:
        The `detail` the collector composes for that finding.

    """
    body = json.dumps(
        {
            IDENTIFIED_FIELD: True,
            FINDINGS_FIELD: [
                {
                    ADVISORY_ID_FIELD: "CPM-FIXTURE-1",
                    SEVERITY_FIELD: "high",
                    AFFECTED_RANGE_FIELD: "<1.2.3",
                    FIXED_RANGE_FIELD: fixed_range,
                    MATCH_CONFIDENCE_FIELD: "exact-version",
                },
            ],
        },
    )
    (finding,) = findings_in(body, source="https://example.invalid/advisories")
    return finding.detail


def _leaf_conditions(condition: Q) -> set[tuple[str, object]]:
    """Return every `(lookup, value)` pair a `Q` tree tests, however it is nested.

    Read off the tree rather than off `str(condition)`, so a case asserts about the
    condition the constraint actually carries rather than about its repr.

    Args:
        condition: The constraint's condition.

    Returns:
        Every leaf pair in it, negations included -- what is asserted about is
        which columns and values appear at all.

    """
    leaves: set[tuple[str, object]] = set()
    for child in condition.children:
        if isinstance(child, Q):
            leaves |= _leaf_conditions(child)
        else:
            leaves.add(child)
    return leaves


def availability_of(**by_surface: str) -> dict[str, str]:
    """Return a complete per-surface availability mapping from a partial spelling.

    Args:
        by_surface: The surfaces a case cares about, keyed by the short name
            `VersionSurface` uses -- `source`, `pypi`, `feedstock`,
            `conda_package`.

    Returns:
        One value per `SURFACE_READERS` entry, defaulting to `not_read`, so a case
        writes only the surfaces it is about and no case can accidentally assert
        over a partial mapping.

    """
    return {reader.surface: by_surface.get(reader.surface, SURFACE_NOT_READ) for reader in SURFACE_READERS}


# ---------------------------------------------------------------------------
# The vocabularies and the order.
# ---------------------------------------------------------------------------


def test_the_readiness_vocabulary_carries_the_four_sentinels_by_construction() -> None:
    """`CPM-AD-5`: every per-status type is composed from `core`'s sentinel table.

    `verify_sentinels` is the post-condition `outcome_type` already enforces, and
    asserting it here is what says this vocabulary was composed rather than
    hand-rolled -- a hand-rolled table spelling `("not_applicable", "N/A")` would
    satisfy every value comparison below and fail this.
    """
    verify_sentinels(RemediationReadiness)

    assert {value for _, value in SENTINEL_MEMBERS} <= set(RemediationReadiness.values)


def test_ready_blocked_and_unknown_are_three_distinct_values_and_none_is_a_default() -> None:
    """The story's own words, and the one assertion the whole vocabulary exists for.

    `ok` is absent for the reason `collectors/outcomes.py` gives one level down:
    the generic determinate value on a readiness column would read as "this is
    fine", and what a reviewer needs to know is *which* of four quite different
    things is true.
    """
    assert len({READY, BLOCKED, READINESS_UNKNOWN}) == len((READY, BLOCKED, READINESS_UNKNOWN))
    assert OutcomeState.OK.value not in RemediationReadiness.values
    assert PackageRemediation._meta.get_field("readiness_status").has_default() is False  # noqa: SLF001 - Django's public-by-convention API


def test_the_four_determinate_verdicts_are_the_four_the_matrix_names() -> None:
    """Each of the matrix's four states is a value of its own, and none is a sentinel.

    "Fix upstream only" and "fix in the recipe" are separate rows of the matrix
    precisely because a reviewer's next action differs, so a vocabulary that
    collapsed either into `ready` or into `blocked` would answer a question nobody
    asked.
    """
    assert set(DETERMINATE_READINESS_VERDICTS) == {READY, AWAITING_BUILD, AWAITING_PACKAGING, BLOCKED}
    assert not set(DETERMINATE_READINESS_VERDICTS) & {value for _, value in SENTINEL_MEMBERS}


def test_the_readiness_column_is_wide_enough_for_every_value_it_offers() -> None:
    """A width shorter than the longest choice is a truncated verdict.

    Django's own `fields.E009` would reject it, and this says the number was
    argued rather than inherited: the longest value is `awaiting_packaging`.
    """
    assert max(len(value) for value in RemediationReadiness.values) <= READINESS_STATE_LENGTH


def test_this_domains_order_is_declared_by_name_and_by_contents() -> None:
    """The assertion `tests/unit/django_apps/test_single_ordering_audit.py` cannot make.

    That audit matches a literal holding two or more `OutcomeState` member
    references, and this order holds one, because `not_applicable` is excluded from
    the reduction and the other two sentinels are members this pass never produces.
    Its recorded table therefore records this order in prose and points here.

    The *ends* matter most and both are the story. `blocked` leads it because a
    package with one finding nobody can act on is not a package a reviewer can
    finish; `ready` is last because a reduction must never reach it while any
    finding said anything else. And `unknown` sits *below* `blocked` rather than
    above, which is deliberate: an established adverse finding must not be masked
    by a question.
    """
    assert READINESS_PRECEDENCE == (BLOCKED, READINESS_UNKNOWN, AWAITING_PACKAGING, AWAITING_BUILD, READY)
    assert READINESS_PRECEDENCE[0] == BLOCKED
    assert READINESS_PRECEDENCE[-1] == READY
    assert READINESS_NOT_APPLICABLE not in READINESS_PRECEDENCE


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        ((), READINESS_UNKNOWN),
        ((READY,), READY),
        ((READY, READY), READY),
        ((READY, BLOCKED), BLOCKED),
        ((READY, READINESS_UNKNOWN), READINESS_UNKNOWN),
        ((BLOCKED, READINESS_UNKNOWN), BLOCKED),
        ((AWAITING_BUILD, AWAITING_PACKAGING), AWAITING_PACKAGING),
        ((READY, AWAITING_BUILD), AWAITING_BUILD),
    ],
    ids=[
        "empty-is-unknown",
        "one-ready",
        "all-ready",
        "blocked-beats-ready",
        "unknown-beats-ready",
        "blocked-beats-unknown",
        "packaging-beats-build",
        "build-beats-ready",
    ],
)
def test_the_reduction_takes_the_least_ready_finding(verdicts: tuple[str, ...], expected: str) -> None:
    """ "A package is only as actionable as its worst finding", as arithmetic.

    The empty case is stated rather than left to whatever `min()` over an empty
    sequence happens to do, and it answers `unknown` rather than `not_applicable`:
    "there is nothing to be ready for" is a package-level decision the pass makes
    before there is anything to reduce.
    """
    assert worst_readiness(verdicts) == expected


@pytest.mark.parametrize(
    "unranked",
    [READINESS_ERROR, READINESS_NOT_FOUND, READINESS_NOT_APPLICABLE, "fine"],
    ids=["error", "not-found", "not-applicable", "from-nowhere"],
)
def test_the_reduction_refuses_a_value_it_cannot_rank(unranked: str) -> None:
    """An unrankable verdict refuses rather than being treated as determinate.

    Three of these are members of the vocabulary the reduction never meets --
    `error` and `not_found` are produced by nothing, and `not_applicable` is
    decided before the reduction -- and the fourth is from outside the vocabulary
    entirely. Ranking any of them beside `blocked` would be the `CPM-FR-6` fold
    arrived at by silence, on the one column that tells a reviewer to stop looking.
    """
    with pytest.raises(OutcomeVocabularyError, match="has no rank in the remediation readiness order"):
        worst_readiness([unranked])


def test_the_per_surface_vocabulary_holds_three_values_and_the_third_is_the_story() -> None:
    """`FixAvailability`: the fix is here, the fix is not here, and this surface was not read.

    Collapsing the third into the second is what produces a false `blocked`, and
    that is the whole reason this type exists rather than a boolean.
    `CPM-SECURITY-S04`'s `KevMembership` needed exactly the same distinction.
    """
    assert set(FixAvailability.values) == {FIX_PUBLISHED, FIX_NOT_PUBLISHED, SURFACE_NOT_READ}
    assert len(FixAvailability.values) == len({FIX_PUBLISHED, FIX_NOT_PUBLISHED, SURFACE_NOT_READ})


def test_the_per_surface_vocabulary_is_not_composed_from_the_outcome_type() -> None:
    """Three values and no sentinels, on exactly `KevMembership`'s terms.

    The four sentinels an outcome type supplies would be four more ways of
    spelling `not_read` on a column whose whole point is that there is exactly one
    -- and the columns are named `*_fix` rather than `*_status` so
    `tests/unit/django_apps/test_outcome_field_audit.py` does not then demand
    them.
    """
    assert not {value for _, value in SENTINEL_MEMBERS} & set(FixAvailability.values)
    assert max(len(value) for value in FixAvailability.values) <= FIX_AVAILABILITY_LENGTH
    assert all(not column.endswith(("_status", "_outcome")) for column, _ in SURFACE_FIX_FIELDS.values())


# ---------------------------------------------------------------------------
# The fixed version, and the `Block If`.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stated", "expected"),
    [("1.2.3", "1.2.3"), (" 1.2.3 ", "1.2.3"), ("v1.2.3", "1.2.3"), ("V1.2.3", "1.2.3")],
    ids=["bare", "padded", "tag-prefix", "upper-tag-prefix"],
)
def test_a_bare_fixed_version_is_compared_in_the_one_form_this_product_normalises(
    stated: str,
    expected: str,
) -> None:
    """The normalisation is `policies/currency.py`'s, imported rather than re-spelled.

    Whitespace and a single leading `v` before a digit, and nothing else. A second
    copy of that rule in this module is what would drift, and a surface and a fix
    normalised differently would compare unequal for no reason a reader could see.
    """
    assert fixed_version(a_finding(fixed_range=stated)) == (expected, RECORDED)


def test_a_blank_fixed_range_is_unrecorded_whatever_the_collector_wrote_beside_it() -> None:
    """**The matrix row this pass got wrong**, corrected against the collector's actual behaviour.

    An earlier draft read `NO_FIXED_RANGE_DETAIL` as "the source was asked and
    answered that there is no fix" and made that `blocked` without asking a
    surface. `collectors/vulnerability.py` builds one clause per field the source
    left *blank*, so the clause is present on precisely the rows whose
    `fixed_range` is empty -- it refines nothing, and reading it as an answer made
    `unrecorded` unreachable from any row a collector writes while sending every
    feed that simply omits a fixed range to the one verdict that tells a reviewer
    to stop looking.

    Both rows below are rows the shipped collector can write, and both are
    `unrecorded`. Under the defect the first was `established_absent` and reached
    `blocked`.
    """
    assert fixed_version(a_finding(fixed_range="", detail=NO_FIXED_RANGE_DETAIL)) == ("", UNRECORDED)
    assert fixed_version(a_finding(fixed_range="")) == ("", UNRECORDED)


def test_the_collector_writes_its_no_fixed_range_clause_for_every_blank_field() -> None:
    """The evidence the case above rests on, asserted rather than asserted about.

    This is the fact that makes the two rows indistinguishable: the clause is a
    function of the field being blank and of nothing else, so no reading of a row
    can recover "the source stated there is no fix". A collector that grew that
    distinction is one of the two changes that would make `blocked` reachable
    again, and it is on this story's deferred list.
    """
    assert NO_FIXED_RANGE_DETAIL in a_recorded_absence_clause(fixed_range="")
    assert NO_FIXED_RANGE_DETAIL not in a_recorded_absence_clause(fixed_range=A_FIXED_VERSION)


@pytest.mark.parametrize(
    "stated",
    [">=1.2.3", "<2.0.0", ">1.0,<2.0", "[1.2.3,)", "1.2.*", "1.0 || 2.0", "~1.2", "^1.2.3", "1.0 - 2.0", "!=1.1"],
    ids=[
        "at-least",
        "less-than",
        "interval",
        "bracketed",
        "wildcard",
        "disjunction",
        "tilde",
        "caret",
        # Named for what actually catches it. `-` is deliberately *not* an
        # ordering marker -- it is how ordinary prerelease versions are spelled,
        # `1.0.0-alpha` and `1.2.3-rc1` -- so `"1.0 - 2.0"` is caught by the
        # spaces and `"1.0-2.0"` is treated as a bare version. The id said
        # "hyphen-range" and claimed coverage this set does not provide; the
        # case below states the residual instead of hiding it.
        "spaced-range",
        "exclusion",
    ],
)
def test_a_fixed_range_that_states_a_set_of_versions_is_not_comparable(stated: str) -> None:
    """The story's `Block If`, taken rather than worked round.

    Deciding whether a surface's single stated version falls inside a range is a
    version-ordering rule no architecture decision owns. So the
    finding reads `unknown` with the reason and the run does not fail -- which is
    the other half: `core/policy_run.py` puts one package in a transaction, so a
    refusal here would cost that package its other four domains' rows.
    """
    version, kind = fixed_version(a_finding(fixed_range=stated))

    assert (version, kind) == ("", NOT_COMPARABLE)


def test_a_hyphen_is_not_an_ordering_marker_and_the_residual_is_stated() -> None:
    """`1.0-2.0` reads as a bare version, and that is a choice rather than an oversight.

    Adding `-` to `ORDERING_MARKERS` would make every ordinary prerelease version
    -- `1.0.0-alpha`, `1.2.3-rc1` -- uncomparable, which is a much larger loss than
    the shape it would catch. What it costs is bounded: an expression that survives
    the denylist still has to equal a version some surface actually stored, and
    since a non-equal statement now reads `not_read` rather than `not_published`,
    the only reachable failure is a surface that literally stores the string
    `1.0-2.0` reading `published`.
    """
    assert "-" not in ORDERING_MARKERS
    assert fixed_version(a_finding(fixed_range="1.0-2.0")) == ("1.0-2.0", RECORDED)


def test_a_bare_tag_prefix_names_no_version_and_is_not_comparable() -> None:
    """`comparable_version` reads a lone `v` as naming nothing, and so does this.

    Letting it survive as a version would make a surface that also stored `v` read
    as carrying the fix, which is the one direction this comparison must never
    fail in.
    """
    assert fixed_version(a_finding(fixed_range="v")) == ("", NOT_COMPARABLE)


def test_every_ordering_marker_makes_an_otherwise_bare_version_uncomparable() -> None:
    """The denylist is exercised character by character rather than by example.

    A marker quietly dropped from the set would let one ecosystem's range grammar
    through as if it were a single version, and the failure would be a `blocked`
    verdict resting on an equality against an expression.
    """
    for marker in ORDERING_MARKERS:
        assert fixed_version(a_finding(fixed_range=f"1.2{marker}3"))[1] == NOT_COMPARABLE


# ---------------------------------------------------------------------------
# What one surface said.
# ---------------------------------------------------------------------------


def test_a_surface_that_states_the_fixed_version_carries_it() -> None:
    """The positive reading, and the only one that can reach `ready`."""
    reading = a_reading(VersionSurface.CONDA_PACKAGE.value, versions=[A_FIXED_VERSION])

    value, observation = surface_availability(reading, fixed=A_FIXED_VERSION)

    assert value == FIX_PUBLISHED
    assert observation is reading.observations[0]


def test_any_row_of_a_sweep_carrying_the_fix_makes_the_surface_carry_it() -> None:
    """The `CPM-SECURITY-S05` lesson applied before the fact.

    `conda_package_snapshots` holds one row per `(channel, platform)` pair, so a
    fix published on the second-sorting channel is still a fix a reviewer can
    install. `policies/currency.py` takes a single row chosen by an alphabetical
    tie-break, and a pass that copied that here would let a channel list decide
    that a reviewer should give up.
    """
    reading = a_reading(VersionSurface.CONDA_PACKAGE.value, versions=[A_LATER_VERSION, A_FIXED_VERSION])

    value, observation = surface_availability(reading, fixed=A_FIXED_VERSION)

    assert value == FIX_PUBLISHED
    assert observation is reading.observations[1]


@pytest.mark.parametrize("stated", [A_LATER_VERSION, AN_OLDER_VERSION], ids=["later", "older"])
def test_a_surface_that_states_another_version_has_established_nothing(stated: str) -> None:
    """**The defect this review turned on**, in one assertion.

    A surface stores the version it states as its *latest*, not the set of versions
    it carries: PyPI still hosts 1.5 when its latest is 2.0. So `latest != fix`
    establishes nothing in either direction, and recording it as `not_published` --
    the one reading permitted to vote towards `blocked` -- made `blocked` the
    steady state rather than an edge, because advisories name a fix and surfaces
    move past it.

    Both directions are exercised. The earlier draft read *both* as
    `not_published`, so the older version -- the genuinely-behind case, where the
    surface really has not got the fix -- was never distinguished from the later
    one anywhere in the suite. It still is not distinguished, and that is now the
    recorded gap rather than a claim: `not_read` is what this run can say about
    either, and the row names the versions.
    """
    reading = a_reading(VersionSurface.SOURCE.value, versions=[stated])

    value, observation = surface_availability(reading, fixed=A_FIXED_VERSION)

    assert value == SURFACE_NOT_READ
    assert observation is reading.observations[0]


def test_a_surface_that_answered_names_the_row_it_looked_at_even_when_it_established_nothing() -> None:
    """`A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION` permits it, and a reviewer needs it.

    The constraint is `not_read OR the reference is present`, so a `not_read`
    surface may still carry the observation it read. Dropping the reference when
    the reading became `not_read` would have taken the row a reviewer wants to open
    -- the one stating the version the equality line names -- off the row.
    """
    reading = a_reading(VersionSurface.CONDA_PACKAGE.value, versions=[A_LATER_VERSION, AN_OLDER_VERSION])

    _, observation = surface_availability(reading, fixed=A_FIXED_VERSION)

    assert observation is reading.observations[0]


def test_no_reading_this_pass_can_produce_is_an_established_absence() -> None:
    """**`blocked` is unreachable through this pass, asserted rather than inferred.**

    `finding_readiness` reaches `blocked` from four `not_published` readings and
    `surface_availability` is the only thing that produces a reading -- so this
    enumeration over every shape a sweep can take is the whole of the claim. The
    two changes that would restore `not_published` are on the story's deferred
    list: a version-ordering rule, and a collector that records "the source stated
    there is no fix" distinctly from a blank field.

    Enumerated here rather than left to be noticed, because a verdict that no row
    reaches is exactly the kind of thing a suite of green cases hides.
    """
    every_shape = [
        a_reading(VersionSurface.SOURCE.value),
        a_reading(VersionSurface.SOURCE.value, versions=[A_FIXED_VERSION]),
        a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION]),
        a_reading(VersionSurface.SOURCE.value, versions=[AN_OLDER_VERSION]),
        a_reading(VersionSurface.SOURCE.value, versions=[""]),
        a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], state=OutcomeState.ERROR.value),
        a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], stale=True),
        a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], target_declared=False),
        a_reading(
            VersionSurface.CONDA_PACKAGE.value,
            versions=[A_LATER_VERSION, AN_OLDER_VERSION],
            states=[OutcomeState.ERROR.value, OutcomeState.OK.value],
        ),
    ]

    readings = [surface_availability(reading, fixed=A_FIXED_VERSION)[0] for reading in every_shape]
    for looked_for in ("", A_FIXED_VERSION):
        readings += [surface_availability(reading, fixed=looked_for)[0] for reading in every_shape]

    assert FIX_NOT_PUBLISHED not in readings
    assert set(readings) == {FIX_PUBLISHED, SURFACE_NOT_READ}


@pytest.mark.parametrize(
    "reading",
    [
        a_reading(VersionSurface.SOURCE.value),
        a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], state=OutcomeState.ERROR.value),
        a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], state=OutcomeState.NOT_FOUND.value),
        a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], state=OutcomeState.NOT_APPLICABLE.value),
        a_reading(VersionSurface.SOURCE.value, versions=[""]),
        a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], stale=True),
        a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], target_declared=False),
        a_reading(
            VersionSurface.CONDA_PACKAGE.value,
            versions=[A_LATER_VERSION, AN_OLDER_VERSION],
            states=[OutcomeState.ERROR.value, OutcomeState.OK.value],
        ),
    ],
    ids=[
        "no-sweep",
        "errored",
        "not-found",
        "not-applicable",
        "no-version-stated",
        "stale",
        "no-freshness-target",
        "half-the-sweep-errored",
    ],
)
def test_a_surface_this_run_did_not_get_a_current_answer_from_is_never_an_absence(reading: SurfaceReading) -> None:
    """**The single property this pass turns on, at the level of one surface.**

    Every one of these is a surface that said nothing this run relies on, and not
    one of them is a statement that the fix is absent from it. `error` in
    particular is the one a careless reading would fold into `not_published` --
    which is exactly how a false `blocked` is reached.
    """
    value, _ = surface_availability(reading, fixed=A_FIXED_VERSION)

    assert value == SURFACE_NOT_READ


def test_a_sweep_with_a_sentinel_row_beside_an_answering_one_still_carries_a_fix_it_states() -> None:
    """The positive direction survives a partial sweep, and only the positive direction.

    `conda_package_snapshots` holds one row per `(channel, platform)` pair, so
    "conda-forge errored and bioconda answered" is an ordinary sweep rather than an
    edge. A fix published on the row that answered is still a fix a reviewer can
    install; a *non*-fix on it establishes nothing, with or without the errored row
    beside it.
    """
    carrying = a_reading(
        VersionSurface.CONDA_PACKAGE.value,
        versions=["", A_FIXED_VERSION],
        states=[OutcomeState.ERROR.value, OutcomeState.OK.value],
    )

    assert surface_availability(carrying, fixed=A_FIXED_VERSION)[0] == FIX_PUBLISHED


def test_a_surface_whose_collector_declares_no_target_does_not_vote() -> None:
    """Staleness that could not be decided is not staleness that was decided against.

    `NO_FRESHNESS_TARGET_DETAIL` says the honest state is that this run could not
    decide whether the evidence had aged, and a surface treated as fresh on that
    basis was voting on evidence of unknown age.
    """
    reading = a_reading(VersionSurface.SOURCE.value, versions=[A_FIXED_VERSION], target_declared=False)

    assert surface_availability(reading, fixed=A_FIXED_VERSION) == (SURFACE_NOT_READ, None)


def test_a_surface_is_not_read_when_there_is_no_fixed_version_to_look_for() -> None:
    """A surface cannot have established the absence of a version nobody asked it about.

    This is what keeps `A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ`'s two disjuncts
    from overlapping: the advisory that established no fix writes four `not_read`
    columns and a blank `fixed_version`, and never four `not_published` ones.
    """
    reading = a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION])

    assert surface_availability(reading, fixed="") == (SURFACE_NOT_READ, None)


@pytest.mark.parametrize(
    ("reading", "expected"),
    [
        (a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION]), (A_LATER_VERSION,)),
        (
            a_reading(VersionSurface.CONDA_PACKAGE.value, versions=[A_LATER_VERSION, AN_OLDER_VERSION]),
            (A_LATER_VERSION, AN_OLDER_VERSION),
        ),
        (a_reading(VersionSurface.SOURCE.value, versions=[A_FIXED_VERSION]), ()),
        (a_reading(VersionSurface.CONDA_PACKAGE.value, versions=[A_LATER_VERSION, A_FIXED_VERSION]), ()),
        (a_reading(VersionSurface.SOURCE.value), ()),
        (a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], stale=True), ()),
        (a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION], target_declared=False), ()),
    ],
    ids=[
        "one-other-version",
        "every-channel-of-the-sweep",
        "the-fix-itself",
        "the-fix-on-one-row-of-the-sweep",
        "no-sweep",
        "stale",
        "no-freshness-target",
    ],
)
def test_the_equality_limit_names_every_version_a_relied_on_surface_stated(
    reading: SurfaceReading,
    expected: tuple[str, ...],
) -> None:
    """What the row discloses about the comparison, and it is the whole sweep.

    An earlier line named only the first stated version, so a four-channel sweep
    told the reader a quarter of what was compared -- on the one line a reviewer
    reads to decide whether the equality limit is why their package looks
    unactionable. A surface this run did not rely on records nothing, because there
    was no comparison to record.
    """
    assert unordered_statements(reading, fixed=A_FIXED_VERSION) == expected


def test_only_determinate_observations_that_name_something_state_a_version() -> None:
    """`FeedstockSnapshot` records a recipe whose version the collector could not read.

    That row is determinate and states nothing, so it has not said what the recipe
    holds -- which is not the same as saying the fix is not in it.
    """
    reading = a_reading(VersionSurface.FEEDSTOCK.value, versions=[A_FIXED_VERSION, ""])

    assert [version for _, version in stated_versions(reading)] == [A_FIXED_VERSION]


# ---------------------------------------------------------------------------
# One finding's readiness.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("availability", "expected"),
    [
        (availability_of(conda_package=FIX_PUBLISHED), READY),
        (availability_of(feedstock=FIX_PUBLISHED), AWAITING_BUILD),
        (availability_of(source=FIX_PUBLISHED), AWAITING_PACKAGING),
        (availability_of(pypi=FIX_PUBLISHED), AWAITING_PACKAGING),
        (
            availability_of(
                source=FIX_PUBLISHED,
                pypi=FIX_PUBLISHED,
                feedstock=FIX_PUBLISHED,
                conda_package=FIX_PUBLISHED,
            ),
            READY,
        ),
        (
            availability_of(source=FIX_PUBLISHED, pypi=FIX_PUBLISHED, feedstock=FIX_PUBLISHED),
            AWAITING_BUILD,
        ),
    ],
    ids=[
        "channel-is-ready",
        "recipe-is-awaiting-build",
        "upstream-is-awaiting-packaging",
        "pypi-is-awaiting-packaging",
        "everywhere-is-ready",
        "everywhere-but-the-channel-is-awaiting-build",
    ],
)
def test_the_surface_the_fix_is_on_decides_what_a_reviewer_can_do(
    availability: dict[str, str],
    expected: str,
) -> None:
    """AC 1: readiness is derived from *where* the fixed version is available.

    The consultation order is `READINESS_BY_SURFACE` and the best available action
    wins: a channel that publishes it means install it now, whatever the recipe or
    upstream also say.
    """
    assert finding_readiness(availability, kind=RECORDED) == expected


def test_a_fix_on_no_surface_with_every_surface_read_is_blocked() -> None:
    """AC 2, and now the *only* shape that reaches `blocked` at all.

    Four established absences. That is what "looked for on every surface and found
    on none" means, and it is what the epic requires the value to mean.

    **No evidence this pass reads produces this mapping today**, which
    `test_no_reading_this_pass_can_produce_is_an_established_absence` states
    directly. The rule is kept because the value has to be defined for
    `A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ` to mirror it and for AC 2's "distinct
    from `ready` and from `unknown`" to mean anything -- and because the day a
    version-ordering rule arrives, this is the case that says what it has to
    produce.
    """
    availability = availability_of(
        source=FIX_NOT_PUBLISHED,
        pypi=FIX_NOT_PUBLISHED,
        feedstock=FIX_NOT_PUBLISHED,
        conda_package=FIX_NOT_PUBLISHED,
    )

    assert finding_readiness(availability, kind=RECORDED) == BLOCKED


@pytest.mark.parametrize(
    "unread",
    [
        VersionSurface.SOURCE.value,
        VersionSurface.PYPI.value,
        VersionSurface.FEEDSTOCK.value,
        VersionSurface.CONDA_PACKAGE.value,
    ],
    ids=["source", "pypi", "feedstock", "conda-package"],
)
def test_three_surfaces_read_and_one_not_is_never_blocked(unread: str) -> None:
    """**The defect `CPM-SECURITY-S05`'s review found, in this story's shape.**

    There, an absent channel voted against channels that had spoken and collapsed
    a determinate verdict. Here the same shape would tell a reviewer to give up on
    a package whose fix is sitting on the surface nobody checked. Every one of the
    four positions is exercised, because a guard written for three of them is a
    guard that holds until somebody reorders the table.
    """
    availability = {
        reader.surface: SURFACE_NOT_READ if reader.surface == unread else FIX_NOT_PUBLISHED
        for reader in SURFACE_READERS
    }

    assert finding_readiness(availability, kind=RECORDED) == READINESS_UNKNOWN


def test_no_surface_read_at_all_is_unknown_and_never_blocked_or_ready() -> None:
    """The matrix's "no currency evidence at all as of the cut-off"."""
    assert finding_readiness(availability_of(), kind=RECORDED) == READINESS_UNKNOWN


@pytest.mark.parametrize("kind", [UNRECORDED, NOT_COMPARABLE], ids=["unrecorded", "not-comparable"])
def test_a_fix_this_run_cannot_compare_is_unknown(kind: str) -> None:
    """Neither of the two "no fix to look for" cases is an established absence.

    A finding with no recorded fix and a finding whose fix states a set of versions
    are different faults, and neither is an established absence: no surface was
    asked about either, so none of them is a surface where the fix is absent.
    `unrecorded` in particular is where an earlier draft returned `blocked` -- from
    a *blank field*, with every surface unread, which is the exact shape this pass
    exists to refuse.
    """
    availability = availability_of(
        source=FIX_NOT_PUBLISHED,
        pypi=FIX_NOT_PUBLISHED,
        feedstock=FIX_NOT_PUBLISHED,
        conda_package=FIX_NOT_PUBLISHED,
    )

    assert finding_readiness(availability, kind=kind) == READINESS_UNKNOWN


def test_a_partial_availability_mapping_refuses_rather_than_defaulting() -> None:
    """A surface missing from the mapping must never be read as one where the fix is absent.

    Unreachable through `evaluate`, which reads all four, and refused rather than
    left as a `KeyError` a traceback would blame on a dictionary -- the message
    says which surface and why it matters.
    """
    with pytest.raises(RemediationPolicyError, match="carry no fix availability"):
        finding_readiness({VersionSurface.SOURCE.value: FIX_NOT_PUBLISHED}, kind=RECORDED)


# ---------------------------------------------------------------------------
# Which findings a readiness is derived from.
# ---------------------------------------------------------------------------


def test_only_matched_findings_name_an_advisory_to_be_ready_for() -> None:
    """A finding that established nothing names no advisory and carries no fixed range.

    `vulnerability_findings` forbids one on a row that is not determinate, so
    filtering here is a statement rather than a defence.
    """
    matched = a_finding(pk=1)
    findings = (matched, a_finding(state=VULNERABILITY_UNKNOWN, pk=2), a_finding(state=VULNERABILITY_ERROR, pk=3))

    assert matched_findings(findings) == (matched,)


@pytest.mark.parametrize(
    "state",
    [A_STATE_FROM_NOWHERE, VULNERABILITY_NOT_APPLICABLE],
    ids=["from-nowhere", "not-applicable"],
)
def test_a_finding_carrying_an_unreadable_state_refuses(state: str) -> None:
    """The one evidence fault this pass raises on, and the reason it is the only one.

    A readiness derived from a value nothing recognises is the one thing that must
    not reach the column that tells a reviewer whether to stop looking, and one
    corrupt evidence row is genuinely one package's problem. `not_applicable` is
    included because `vulnerability_findings` refuses it outright -- an advisory
    question applies to every package.
    """
    with pytest.raises(RemediationPolicyError, match="cannot read as a statement"):
        matched_findings((a_finding(state=state),))


def test_the_advisory_vocabulary_is_read_off_the_composed_type() -> None:
    """Listing the states would be a second spelling of what `outcome_type` already fixed."""
    assert VULNERABILITY_ERROR in ADVISORY_VOCABULARY
    assert MATCHED in ADVISORY_VOCABULARY
    assert A_STATE_FROM_NOWHERE not in ADVISORY_VOCABULARY


def test_only_the_collectors_read_and_matched_nothing_row_establishes_that_there_is_nothing() -> None:
    """**The defect: `unknown` is where "established nothing" actually arrives.**

    The advisory collector writes three different `unknown` rows -- read and
    matched nothing, the source cannot identify this package, and this identity
    names no version to match against -- and only the first says the package has no
    matched advisory. An earlier draft named `error` and `not_found` alone, so a
    package the source could not identify read `not_applicable` here ("there is
    nothing to be ready for") while `package_vulnerability` read `unknown` for the
    same package, the same run and the same rows.

    The line is drawn with the same prefix test `policies/vulnerability.py` already
    applies to the same rows, against the same imported constant, so the two passes
    cannot disagree about one sweep.
    """
    matched_nothing = a_matched_nothing_finding(pk=1)
    errored = a_finding(state=VULNERABILITY_ERROR, pk=2)
    missing = a_finding(state=VULNERABILITY_NOT_FOUND, pk=3)
    unidentified = a_finding(state=VULNERABILITY_UNKNOWN, detail=UNIDENTIFIED_DETAIL, pk=4)
    bare_unknown = a_finding(state=VULNERABILITY_UNKNOWN, pk=5)

    established = (matched_nothing, errored, missing, unidentified, bare_unknown)

    assert unestablished_findings(established) == (errored, missing, unidentified, bare_unknown)
    assert unestablished_findings((a_finding(pk=6),)) == ()


def test_the_matched_nothing_sentinel_is_recognised_through_the_reason_a_source_appended() -> None:
    """A prefix rather than an equality, and `policies/vulnerability.py`'s argument for it.

    The collector composes the stored line as `f"{because}: {said}"` wherever the
    source stated a reason of its own, so an equality would read every checked,
    clean package from such a source as establishing nothing.
    """
    with_a_reason = a_finding(
        state=VULNERABILITY_UNKNOWN,
        detail=f"{NOTHING_MATCHED_DETAIL}: the source had nothing further to add",
        pk=1,
    )

    assert unestablished_findings((with_a_reason,)) == ()


def test_the_supporting_finding_is_the_first_in_read_order_carrying_the_rows_verdict() -> None:
    """Not simply the first finding given, which is why the loop exists.

    A package with one advisory fixed on a channel and one fixed nowhere must name
    the blocked one, or the row's four surface columns would describe a fix the
    verdict is not about.
    """
    ready = a_finding(pk=1)
    blocked = a_finding(pk=2)

    assert supporting_finding([(ready, READY), (blocked, BLOCKED)], BLOCKED) is blocked
    assert supporting_finding([(ready, READY)], BLOCKED) is None


# ---------------------------------------------------------------------------
# What the row says.
# ---------------------------------------------------------------------------


def test_a_package_with_no_advisory_evidence_says_so_and_never_says_nothing_to_do() -> None:
    """`unknown`, and the line separates it from the package this run matched nothing to."""
    detail = remediation_detail(
        findings=(),
        matched=(),
        readings={},
        availability=availability_of(),
        supporting=None,
        fixed="",
        kind=UNRECORDED,
        readiness=READINESS_UNKNOWN,
        advisory=A_FRESH_ADVISORY,
    )

    assert detail == NO_ADVISORY_EVIDENCE_DETAIL
    assert "unknown rather than nothing to do, and never blocked" in detail


def test_a_sweep_that_matched_nothing_and_established_nothing_names_the_rows_that_failed() -> None:
    """`unknown` rather than `not_applicable`, and the line says which rows made it so."""
    errored = a_finding(state=VULNERABILITY_ERROR, pk=7)

    detail = remediation_detail(
        findings=(errored,),
        matched=(),
        readings={},
        availability=availability_of(),
        supporting=None,
        fixed="",
        kind=UNRECORDED,
        readiness=READINESS_UNKNOWN,
        advisory=A_FRESH_ADVISORY,
    )

    assert detail == UNESTABLISHED_ADVISORY_EVIDENCE_DETAIL.format(findings="7")
    assert "so this run cannot say there is nothing to remediate" in detail
    assert "7" in detail


def test_a_sweep_that_matched_no_advisory_says_there_is_nothing_to_be_ready_for() -> None:
    """`not_applicable`, and the line says what that is *not*.

    It is not a claim that the package is clean: whether this run established
    anything about its exposure is `package_vulnerability`'s verdict, which this
    pass neither reads nor restates.

    The sweep is the collector's "read and matched nothing" row and no other. A
    bare `unknown` here reads `unknown`, which is the case above -- and which this
    case asserted by accident before `unestablished_findings` was corrected.
    """
    detail = remediation_detail(
        findings=(a_matched_nothing_finding(pk=4),),
        matched=(),
        readings={},
        availability=availability_of(),
        supporting=None,
        fixed="",
        kind=UNRECORDED,
        readiness=READINESS_NOT_APPLICABLE,
        advisory=A_FRESH_ADVISORY,
    )

    assert detail == NO_MATCHED_ADVISORY_DETAIL
    assert "there is no finding for a fix to be ready for" in detail


@pytest.mark.parametrize("detail_text", ["", NO_FIXED_RANGE_DETAIL], ids=["bare", "with-the-collectors-clause"])
def test_a_row_that_looked_for_nothing_says_so_and_says_the_absence_was_nobodys(detail_text: str) -> None:
    """One line for both rows, because the evidence does not distinguish them.

    An earlier draft carried two lines for two kinds, one of them `blocked`. The
    collector writes its "the source states no fixed range" clause for every blank
    field, so the two rows below are the same row wearing two `detail`s -- and the
    line now says that in as many words, so a reviewer is not left to infer that
    the absence was the advisory's.
    """
    kind = UNRECORDED
    line = NO_FIX_RECORDED_DETAIL
    supporting = a_finding(fixed_range="", detail=detail_text, pk=9)

    detail = remediation_detail(
        findings=(supporting,),
        matched=(supporting,),
        readings={},
        availability=availability_of(),
        supporting=supporting,
        fixed="",
        kind=kind,
        readiness=READINESS_UNKNOWN,
        advisory=A_FRESH_ADVISORY,
    )

    assert detail == line.format(finding=9)
    assert "blank means missing and is never inferred" in detail
    assert "unknown rather than blocked" in detail


def test_an_uncomparable_fix_names_the_expression_and_whose_decision_would_settle_it() -> None:
    """The `Block If`, on the row a reviewer reads.

    Saying what would have to be decided is what makes this a recorded gap rather
    than a silent limitation. It used to say `CPM-AD-6`, which is *version
    authority is explicit per package* -- which surface is authoritative, not how
    two version strings compare -- so a reviewer who followed the citation arrived
    at a decision that does not answer the question they had.
    """
    supporting = a_finding(fixed_range=">=1.2.3", pk=11)

    detail = remediation_detail(
        findings=(supporting,),
        matched=(supporting,),
        readings={},
        availability=availability_of(),
        supporting=supporting,
        fixed="",
        kind=NOT_COMPARABLE,
        readiness=READINESS_UNKNOWN,
        advisory=A_FRESH_ADVISORY,
    )

    assert detail == UNCOMPARABLE_FIX_DETAIL.format(finding=11, expression=">=1.2.3")
    assert "no architecture decision owns version ordering yet" in detail
    assert ">=1.2.3" in detail
    assert "CPM-AD-6" not in detail


def test_an_unknown_row_says_which_surface_it_did_not_read() -> None:
    """**The line this pass exists for**, and the third acceptance criterion of the story.

    Without it, an `unknown` row whose fix is on no surface it managed to read
    looks exactly like a row nobody computed. The line names the surfaces that
    answered and the ones that did not, and says in words why the row is not
    `blocked`.
    """
    supporting = a_finding(pk=3)
    readings = {
        VersionSurface.SOURCE.value: a_reading(VersionSurface.SOURCE.value, versions=[A_LATER_VERSION]),
        VersionSurface.PYPI.value: a_reading(VersionSurface.PYPI.value, versions=[A_LATER_VERSION]),
        VersionSurface.FEEDSTOCK.value: a_reading(VersionSurface.FEEDSTOCK.value, versions=[A_LATER_VERSION]),
        VersionSurface.CONDA_PACKAGE.value: a_reading(VersionSurface.CONDA_PACKAGE.value),
    }
    availability = availability_of()

    detail = remediation_detail(
        findings=(supporting,),
        matched=(supporting,),
        readings=readings,
        availability=availability,
        supporting=supporting,
        fixed=A_FIXED_VERSION,
        kind=RECORDED,
        readiness=READINESS_UNKNOWN,
        advisory=A_FRESH_ADVISORY,
    )

    assert VersionSurface.CONDA_PACKAGE.value in detail
    assert "a surface that was not read is not a surface where the fix is absent" in detail
    assert (
        UNREAD_SURFACES_DETAIL.format(
            fixed=A_FIXED_VERSION,
            unread=[
                VersionSurface.SOURCE.value,
                VersionSurface.PYPI.value,
                VersionSurface.FEEDSTOCK.value,
                VersionSurface.CONDA_PACKAGE.value,
            ],
        )
        in detail
    )


def test_a_row_that_found_the_fix_is_not_told_why_it_is_not_blocked() -> None:
    """The unread-surface line answers a question a determinate row did not raise.

    `detail` is an explanation, and an explanation of an unremarkable row is noise
    -- the rule every table in this product applies to its own.
    """
    supporting = a_finding(pk=5)
    readings = {
        VersionSurface.CONDA_PACKAGE.value: a_reading(
            VersionSurface.CONDA_PACKAGE.value,
            versions=[A_FIXED_VERSION],
        ),
    }

    detail = remediation_detail(
        findings=(supporting,),
        matched=(supporting,),
        readings=readings,
        availability=availability_of(conda_package=FIX_PUBLISHED),
        supporting=supporting,
        fixed=A_FIXED_VERSION,
        kind=RECORDED,
        readiness=READY,
        advisory=A_FRESH_ADVISORY,
    )

    assert detail == ""


@pytest.mark.parametrize(
    ("stated", "readiness"),
    [
        ([A_LATER_VERSION], READINESS_UNKNOWN),
        ([AN_OLDER_VERSION], READINESS_UNKNOWN),
        ([A_LATER_VERSION, AN_OLDER_VERSION], READINESS_UNKNOWN),
    ],
    ids=["later", "older", "a-multi-channel-sweep"],
)
def test_a_row_whose_surfaces_stated_other_versions_records_the_equality_limit(
    stated: list[str],
    readiness: str,
) -> None:
    """The story's recorded gap, on the row of the reviewer it is about.

    **On a non-`blocked` row, and that is the point.** The line used to fire only
    where a surface read `not_published`, which is now no reading at all -- so
    gating it on `blocked` would have silently emptied the one line that says why a
    package looks unactionable. Every version of every sweep is named, because a
    line naming the first of four channels discloses a quarter of the comparison.
    """
    supporting = a_finding(pk=6)
    readings = {reader.surface: a_reading(reader.surface, versions=stated) for reader in SURFACE_READERS}

    detail = remediation_detail(
        findings=(supporting,),
        matched=(supporting,),
        readings=readings,
        availability=availability_of(),
        supporting=supporting,
        fixed=A_FIXED_VERSION,
        kind=RECORDED,
        readiness=readiness,
        advisory=A_FRESH_ADVISORY,
    )

    assert readiness != BLOCKED
    assert (
        EQUALITY_ONLY_DETAIL.format(
            statements=[f"{reader.surface} states {stated}" for reader in SURFACE_READERS],
            fixed=A_FIXED_VERSION,
        )
        in detail
    )
    assert "reads not_read rather than not_published" in detail
    for version in stated:
        assert version in detail


def test_a_stale_surface_is_named_as_one_the_row_did_not_rely_on() -> None:
    """AC 3: readiness reports stale rather than asserting a fix is available.

    The stale surface reads `not_read`, so it can neither carry the row to `ready`
    nor vote towards `blocked` -- and a fresh surface beside it still decides the
    row, which is the matrix's "some surfaces fresh, one stale".
    """
    supporting = a_finding(pk=8)
    readings = {
        VersionSurface.CONDA_PACKAGE.value: a_reading(
            VersionSurface.CONDA_PACKAGE.value,
            versions=[A_FIXED_VERSION],
        ),
        VersionSurface.FEEDSTOCK.value: a_reading(
            VersionSurface.FEEDSTOCK.value,
            versions=[A_FIXED_VERSION],
            stale=True,
        ),
    }

    detail = remediation_detail(
        findings=(supporting,),
        matched=(supporting,),
        readings=readings,
        availability=availability_of(conda_package=FIX_PUBLISHED),
        supporting=supporting,
        fixed=A_FIXED_VERSION,
        kind=RECORDED,
        readiness=READY,
        advisory=A_FRESH_ADVISORY,
    )

    assert detail == STALE_SURFACES_DETAIL.format(surfaces=[VersionSurface.FEEDSTOCK.value])
    assert "A fresh surface beside a stale one still decides this row" in detail


def test_a_surface_whose_collector_declares_no_target_says_staleness_could_not_be_decided() -> None:
    """Recorded rather than refused, and never reported as fresh.

    `CPM-AD-28` refuses a *registered* collector that declares none, so this is
    reachable only where nothing is registered for that table -- and a refusal here
    would cost the package its other four domains' rows (`CPM-AD-23`).
    """
    supporting = a_finding(pk=10)
    readings = {
        VersionSurface.SOURCE.value: a_reading(
            VersionSurface.SOURCE.value,
            versions=[A_FIXED_VERSION],
            target_declared=False,
        ),
    }

    detail = remediation_detail(
        findings=(supporting,),
        matched=(supporting,),
        readings=readings,
        availability=availability_of(),
        supporting=supporting,
        fixed=A_FIXED_VERSION,
        kind=RECORDED,
        readiness=READINESS_UNKNOWN,
        advisory=A_FRESH_ADVISORY,
    )

    assert detail.startswith(NO_FRESHNESS_TARGET_DETAIL.format(surfaces=[VersionSurface.SOURCE.value]))
    assert "did not treat it as stale" in detail
    assert VersionSurface.SOURCE.value in detail


def test_a_row_reducing_several_findings_says_which_one_its_columns_are_about() -> None:
    """Two advisories naming two fixed versions have two different sets of surface answers.

    A row that mixed them would say nothing true, so the columns are about the
    supporting finding and the line says so.
    """
    ready = a_finding(pk=1)
    unknown = a_finding(pk=2)
    readings = {reader.surface: a_reading(reader.surface, versions=[A_LATER_VERSION]) for reader in SURFACE_READERS}

    detail = remediation_detail(
        findings=(ready, unknown),
        matched=(ready, unknown),
        readings=readings,
        availability=availability_of(),
        supporting=unknown,
        fixed=A_FIXED_VERSION,
        kind=RECORDED,
        readiness=READINESS_UNKNOWN,
        advisory=A_FRESH_ADVISORY,
    )

    assert detail.startswith(SEVERAL_FINDINGS_DETAIL.format(matched=TWO_FINDINGS, finding=2))
    assert "the least ready of their readiness verdicts" in detail


# ---------------------------------------------------------------------------
# Freshness, consumed rather than restated.
# ---------------------------------------------------------------------------


def test_the_freshness_target_comes_from_the_collector_that_writes_the_table() -> None:
    """`CPM-AD-7` makes the table the collector, so no second spelling of a name is needed.

    Reading the target off the registry is what keeps `CPM-FR-38`'s answer in one
    place: this pass declares no target of its own and could not disagree with one.
    """
    assert freshness_target(CondaPackageSnapshot) == CONDA_PACKAGE_FRESHNESS_TARGET
    assert CondaPackageCollector.freshness_target == CONDA_PACKAGE_FRESHNESS_TARGET


def test_an_evidence_table_no_registered_collector_writes_declares_no_target() -> None:
    """`None` is not a fault this pass refuses -- it is a staleness it could not decide.

    `PackageRemediation` is not an evidence table at all, which is the cheapest
    thing to ask about that no collector could ever write.
    """
    assert freshness_target(PackageRemediation) is None  # type: ignore[arg-type] - deliberately not an evidence model


def test_an_observation_past_its_target_is_stale_and_one_that_reached_it_is_not() -> None:
    """The boundary is `core/freshness.py`'s and this consumes it rather than restating it.

    Evidence observed exactly `target` ago has reached the age it may reach and no
    more, so it is fresh; the first instant beyond it is stale.
    """
    at_the_boundary = FIXED_INSTANT - CONDA_PACKAGE_FRESHNESS_TARGET
    past_it = at_the_boundary - timedelta(seconds=1)

    assert evidence_is_stale(CondaPackageSnapshot, observed_at=at_the_boundary, now=FIXED_INSTANT) == (False, True)
    assert evidence_is_stale(CondaPackageSnapshot, observed_at=past_it, now=FIXED_INSTANT) == (True, True)


def test_a_surface_nobody_observed_is_not_stale() -> None:
    """An absence of observation is not an old observation.

    `core/freshness.py` makes that choice and this inherits it: reporting a package
    nobody looked at as stale would tell an operator that something never looked at
    has gone out of date.
    """
    assert evidence_is_stale(CondaPackageSnapshot, observed_at=None, now=FIXED_INSTANT) == (False, True)


def test_staleness_cannot_be_decided_where_no_collector_declares_a_target() -> None:
    """Not stale, and the second half of the answer says the question could not be asked."""
    assert evidence_is_stale(
        PackageRemediation,  # type: ignore[arg-type] - deliberately not an evidence model
        observed_at=FIXED_INSTANT,
        now=FIXED_INSTANT,
    ) == (False, False)


# ---------------------------------------------------------------------------
# The advisory evidence's own freshness, which nothing measured before.
# ---------------------------------------------------------------------------


def test_the_advisory_sweeps_own_age_is_measured_against_the_advisory_collectors_target() -> None:
    """**`CPM-UJ-1`'s stated edge case, which had no implementation at all.**

    "If the vulnerability evidence is older than its freshness target, the finding
    shows as stale rather than actionable." `VULNERABILITY_FRESHNESS_TARGET` was
    declared and never consulted: freshness was asked of the four surfaces alone,
    so a month-old advisory sweep beside a channel refreshed this morning produced
    `ready` with `evidence_stale` false.
    """
    at_the_boundary = FIXED_INSTANT - VULNERABILITY_FRESHNESS_TARGET
    past_it = at_the_boundary - timedelta(seconds=1)

    fresh = advisory_reading((a_finding(observed_at=at_the_boundary),), cutoff=FIXED_INSTANT)
    stale = advisory_reading((a_finding(observed_at=past_it),), cutoff=FIXED_INSTANT)

    assert fresh == AdvisoryReading(stale=False, target_declared=True)
    assert stale == AdvisoryReading(stale=True, target_declared=True)


def test_a_package_with_no_advisory_sweep_has_no_stale_advisory_evidence() -> None:
    """An absence of observation is not an old observation, here as everywhere.

    Such a package is already `unknown` for the stronger reason that nothing was
    established about it, so reporting it stale as well would add a second, wrong
    account of the same row.
    """
    assert advisory_reading((), cutoff=FIXED_INSTANT) == AdvisoryReading(stale=False, target_declared=True)


def test_a_stale_advisory_sweep_says_so_and_says_no_surface_was_asked() -> None:
    """The row a reviewer reads when the finding itself is what has aged.

    Not `ready`, not `blocked` and not `not_applicable`: what a stale sweep offers
    is a fixed version that may no longer be the one to look for, so the honest row
    names none and asks nothing. Nothing else is said, because nothing else was
    done.
    """
    supporting = a_finding(pk=12)

    detail = remediation_detail(
        findings=(supporting,),
        matched=(supporting,),
        readings={},
        availability=availability_of(),
        supporting=None,
        fixed="",
        kind=UNRECORDED,
        readiness=READINESS_UNKNOWN,
        advisory=AdvisoryReading(stale=True, target_declared=True),
    )

    assert detail == STALE_ADVISORY_DETAIL
    assert "the readiness is unknown rather than actionable" in detail
    assert NO_ADVISORY_EVIDENCE_DETAIL not in detail
    assert NO_MATCHED_ADVISORY_DETAIL not in detail


def test_an_undeclared_advisory_freshness_target_is_recorded_and_never_read_as_fresh() -> None:
    """The advisory half of `CPM-AD-28`'s recorded consequence.

    Reachable only in a component that registers no advisory collector, and
    recorded rather than refused for the reason every other recorded state here is:
    a refusal costs this package its other four domains' rows (`CPM-AD-23`).
    """
    detail = remediation_detail(
        findings=(),
        matched=(),
        readings={},
        availability=availability_of(),
        supporting=None,
        fixed="",
        kind=UNRECORDED,
        readiness=READINESS_UNKNOWN,
        advisory=AdvisoryReading(stale=False, target_declared=False),
    )

    assert detail.startswith(NO_ADVISORY_FRESHNESS_TARGET_DETAIL.format(evidence=ADVISORY_EVIDENCE))
    assert "could not decide whether the advisory evidence has aged" in detail
    assert NO_ADVISORY_EVIDENCE_DETAIL in detail


def test_the_advisory_evidence_is_named_as_evidence_rather_than_as_a_fifth_surface() -> None:
    """A reader counting surfaces on a freshness line must still count four."""
    assert ADVISORY_EVIDENCE not in set(VersionSurface.values)
    assert freshness_target(VulnerabilityFinding) == VULNERABILITY_FRESHNESS_TARGET


# ---------------------------------------------------------------------------
# The reads, and the one refusal reachable without a database.
# ---------------------------------------------------------------------------


def test_the_advisory_read_refuses_a_naive_cutoff() -> None:
    """Refused rather than converted, before any query is built.

    A cut-off silently shifted by the reader's offset selects a different evidence
    set on every replay, and here it would also move the freshness boundary --
    which is the opposite of what `CPM-FR-22` promises.
    """
    with pytest.raises(RemediationPolicyError, match="naive cutoff"):
        current_findings(package_id=A_PACKAGE_ID, cutoff=A_NAIVE_INSTANT)


def test_the_read_orderings_are_declared_rather_than_spelled_at_the_query() -> None:
    """The seventh hand-written copy of `snapshot_as_of`'s rule, named so it cannot drift."""
    assert READ_ORDERING == ("-observed_at", "-pk")
    assert WITHIN_A_SWEEP == "pk"


# ---------------------------------------------------------------------------
# The declarations.
# ---------------------------------------------------------------------------


def test_the_pass_owns_its_own_table_and_contributes_no_rollup_column() -> None:
    """`CPM-AD-21`: no pass writes `package_health`, and the rollup offers nothing here.

    `core/policy.py` records that an empty contribution is legitimate, "a pass
    whose whole output is its own derived table". This is one.
    """
    assert RemediationPass.name == POLICY_NAME
    assert RemediationPass.derived_model is PackageRemediation
    assert RemediationPass.contributes == ()
    assert "readiness_status" not in contributable_columns()


def test_the_pass_declares_no_prepare_of_its_own() -> None:
    """It reads no policy parameter, so there is nothing to establish before the loop.

    The three parameterised passes override `prepare` because their verdicts are
    governed by reviewed data keyed by the policy version. Inventing a parameter so
    this pass looked like them would put a knob in a reviewed file that nothing
    reads.
    """
    assert "prepare" not in vars(RemediationPass)


def test_every_surface_is_read_and_every_surface_can_reach_a_readiness() -> None:
    """The two tables are different sequences over the same four surfaces.

    `SURFACE_READERS` says which surfaces exist and how to read each;
    `READINESS_BY_SURFACE` says which reached verdict a reviewer should be shown
    first. Collapsing them would make "read them in the order a fix is most useful
    in" look like one rule when it is two.
    """
    assert {reader.surface for reader in SURFACE_READERS} == set(VersionSurface.values)
    assert {surface for surface, _ in READINESS_BY_SURFACE} == set(VersionSurface.values)
    assert len(SURFACE_READERS) == FOUR_SURFACES
    assert READINESS_BY_SURFACE[0] == (VersionSurface.CONDA_PACKAGE.value, READY)


def test_the_pass_and_the_schema_agree_about_which_column_holds_which_surface() -> None:
    """The keyword names the pass writes and the table the constraints are built from.

    `policies/models.py` builds two check constraints by walking
    `SURFACE_FIX_FIELDS`, and `policies/remediation.py` spells the four `*_fix`
    keywords literally so the writability audit can see them and carries the four
    reference columns on its own reader table. Neither reads the other, so this is
    what stops them drifting.
    """
    assert {surface: fix for surface, (fix, _) in SURFACE_FIX_FIELDS.items()} == {
        VersionSurface.SOURCE.value: "source_fix",
        VersionSurface.PYPI.value: "pypi_fix",
        VersionSurface.FEEDSTOCK.value: "feedstock_fix",
        VersionSurface.CONDA_PACKAGE.value: "conda_package_fix",
    }
    assert {reader.surface: reader.reference_field for reader in SURFACE_READERS} == {
        surface: reference for surface, (_, reference) in SURFACE_FIX_FIELDS.items()
    }


def test_the_fixed_version_column_is_as_wide_as_the_evidence_it_copies() -> None:
    """A column narrower than `fixed_range` would truncate a fix the collector recorded.

    And a truncated version compared for equality is a `not_published` reading of a
    surface that actually carries it -- which is the direction that ends in a false
    `blocked`.
    """
    stored = PackageRemediation._meta.get_field("fixed_version").max_length  # noqa: SLF001 - Django's public-by-convention API
    evidence = VulnerabilityFinding._meta.get_field("fixed_range").max_length  # noqa: SLF001 - same

    assert stored is not None
    assert evidence is not None
    assert stored >= evidence


def test_the_table_is_named_by_the_architecture_and_keyed_as_cpm_ad_21_requires() -> None:
    """A derived `policies_packageremediation` would make the table depend on the app.

    **A set equality over all eight rather than six `in names` checks.** Six
    memberships neither notice a constraint dropped from the table nor a seventh
    added without a case, and the two the earlier spelling omitted -- the recipe
    and release verdicts -- were exactly the two with no refusal case anywhere.
    """
    assert PackageRemediation._meta.db_table == "package_remediation"  # noqa: SLF001 - Django's public-by-convention API
    names = {constraint.name for constraint in PackageRemediation._meta.constraints}  # noqa: SLF001 - same

    assert names == {
        ONE_REMEDIATION_ROW_PER_PACKAGE_PER_RUN,
        REMEDIATION_ROW_NAMES_ITS_POLICY_VERSION,
        A_DETERMINATE_READINESS_NEEDS_ITS_FINDING,
        A_READY_ROW_NAMES_THE_CHANNEL_THAT_CARRIES_THE_FIX,
        AN_AWAITING_BUILD_ROW_NAMES_THE_RECIPE_THAT_CARRIES_THE_FIX,
        AN_AWAITING_PACKAGING_ROW_NAMES_THE_RELEASE_THAT_CARRIES_THE_FIX,
        A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ,
        A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION,
    }


def test_a_blocked_row_needs_every_surface_read_admits_no_exception() -> None:
    """The `Q(fixed_version="")` escape is gone, and its absence is asserted.

    While it stood, any `blocked` row that looked for nothing passed whatever its
    four surface columns said -- which is precisely the shape a `blocked` reached
    from a blank advisory field produced, so the hole in the schema was cut to the
    size of the defect above it. Two documents claimed a hand-written `INSERT` was
    refused by PostgreSQL; for the one row that mattered it was not.
    """
    constraint = next(
        entry
        for entry in PackageRemediation._meta.constraints  # noqa: SLF001 - Django's public-by-convention API
        if entry.name == A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ
    )

    assert ("fixed_version", "") not in _leaf_conditions(constraint.condition)
    assert {("source_fix", FIX_NOT_PUBLISHED), ("conda_package_fix", FIX_NOT_PUBLISHED)} <= _leaf_conditions(
        constraint.condition,
    )


def test_the_row_renders_its_readiness_beside_the_version_it_looked_for() -> None:
    """The one line a human is likeliest to read is where the two `blocked` rows differ.

    Read off `package_id` rather than off `package`, so a half-built object renders
    in a debugger and in a traceback instead of raising.
    """
    row = PackageRemediation(readiness_status=BLOCKED, fixed_version=A_FIXED_VERSION)

    assert str(row) == f"remediation of no package: {BLOCKED} for {A_FIXED_VERSION}"
    assert str(PackageRemediation()) == "remediation of no package: (no verdict) for no fixed version"


def test_the_surface_snapshots_are_the_four_evidence_tables_the_story_names() -> None:
    """`CPM-SECURITY-S06` names five evidence tables and this pass reads exactly those."""
    assert [reader.model for reader in SURFACE_READERS] == [
        SourceReleaseSnapshot,
        PyPIReleaseSnapshot,
        FeedstockSnapshot,
        CondaPackageSnapshot,
    ]


def test_nothing_here_reads_another_passs_derived_table() -> None:
    """The constraint carried forward from two sibling reviews, asserted rather than promised.

    A readiness derived from `PackageCurrency` would depend on two policy versions
    at once, and `CPM-FR-22` replay could then be stated for neither.

    **Matched on the parsed syntax tree over the whole module, not on four literal
    import lines.** The earlier spelling grepped for four exact `from ... import`
    strings, so a reverse accessor (`package.currency_findings.all()`), an
    `apps.get_model(...)`, a module import plus attribute access, a function-local
    import and a parenthesised multi-line import all survived it -- and it omitted
    `PackageHealth` entirely, which `CPM-AD-21` forbids this pass to write. What is
    checked now is that no name of a derived table appears anywhere in the module
    as an identifier or an attribute, and that no dynamic model lookup does either.
    """
    module = importlib.import_module("conda_sentinel.policies.remediation")
    assert module.__file__ is not None
    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))

    forbidden = {
        "PackageCurrency",
        "PackageFeedstockPresence",
        "PackageVulnerability",
        "PackageLicense",
        "PackageHealth",
        "get_model",
    }
    reached = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Name | ast.Attribute)
    } | {
        alias.asname or alias.name.rsplit(".", maxsplit=1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    accessors = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr.endswith("_findings")
    }

    assert not forbidden & reached
    assert not accessors


def test_the_naive_instant_this_module_uses_is_genuinely_naive() -> None:
    """A guard on the fixture rather than on the code: an aware value would pin nothing."""
    assert A_NAIVE_INSTANT.tzinfo is None
    assert FIXED_INSTANT.tzinfo is UTC
