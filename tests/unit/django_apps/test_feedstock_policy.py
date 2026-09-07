"""`CPM-FR-40`'s verdict, its vocabulary and its versioned parameter, without a database.

`policies/feedstock.py` is split into a query and some arithmetic on exactly the
terms `policies/currency.py` is: `observed_feedstock` is the only function that
touches the database, and everything that *decides* anything takes an observation
and an interval and returns a verdict. That split is what lets every row of the
story's I/O matrix that is about a decision be exercised here, in milliseconds,
against constructed observations -- and it is why the integration module beside
this one is about the orchestration, the rollup gate and the two-version case
rather than about the rules.

`policies/parameters.py` is split the same way and for the same reason.
`parameters_from` turns *text* into parameter sets and `parameters_in` answers
about a mapping, so every refusal the reviewed file can earn is measured here
against a string. Only the two functions that open a file need one, and those are
in the integration module with `tmp_path`.

**Unsaved model instances, and that is what keeps this a unit test.** A
`FeedstockSnapshot` is constructed and never saved: `_meta` is populated at
import, the fields hold whatever they were given, and nothing here opens a
connection. It is also the only way to build the one row the database refuses --
a `state` outside the vocabulary -- which is exactly the row `presence_verdict`
must not read as an absence.

No database, no network, no subprocess. The one filesystem touch is the refusal
case for an unresolvable module location, which uses `tmp_path` for the reason
`tests/unit/django_apps/test_watchlist.py`'s equivalent does.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_package_supply_chain_monitor.collectors.models import FeedstockSnapshot
from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.outcomes import SENTINEL_MEMBERS
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.outcomes import verify_sentinels
from conda_package_supply_chain_monitor.core.policy import PolicyPass
from conda_package_supply_chain_monitor.core.rollup import STAMP_COLUMNS
from conda_package_supply_chain_monitor.core.rollup import contributable_columns
from conda_package_supply_chain_monitor.core.rollup import permitted_values
from conda_package_supply_chain_monitor.identity.confidence import IdentityConfidence
from conda_package_supply_chain_monitor.policies.currency import POLICY_NAME as CURRENCY_POLICY_NAME
from conda_package_supply_chain_monitor.policies.currency import SURFACE_READERS
from conda_package_supply_chain_monitor.policies.currency import CurrencyPass
from conda_package_supply_chain_monitor.policies.feedstock import CARRIED_SENTINELS
from conda_package_supply_chain_monitor.policies.feedstock import POLICY_NAME
from conda_package_supply_chain_monitor.policies.feedstock import READ_ORDERING
from conda_package_supply_chain_monitor.policies.feedstock import REFINED_SENTINEL
from conda_package_supply_chain_monitor.policies.feedstock import ROLLUP_COLUMN
from conda_package_supply_chain_monitor.policies.feedstock import FeedstockPolicyError
from conda_package_supply_chain_monitor.policies.feedstock import FeedstockPresencePass
from conda_package_supply_chain_monitor.policies.feedstock import activity_age
from conda_package_supply_chain_monitor.policies.feedstock import observation_age
from conda_package_supply_chain_monitor.policies.feedstock import observed_feedstock
from conda_package_supply_chain_monitor.policies.feedstock import presence_detail
from conda_package_supply_chain_monitor.policies.feedstock import presence_verdict
from conda_package_supply_chain_monitor.policies.models import AN_AGE_EXACTLY_WHEN_THERE_IS_AN_INSTANT
from conda_package_supply_chain_monitor.policies.models import DETERMINATE_PRESENCE_NEEDS_AN_OBSERVATION
from conda_package_supply_chain_monitor.policies.models import MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT
from conda_package_supply_chain_monitor.policies.models import MEASURED_VERDICTS
from conda_package_supply_chain_monitor.policies.models import ONE_FEEDSTOCK_ROW_PER_PACKAGE_PER_RUN
from conda_package_supply_chain_monitor.policies.models import THRESHOLD_IS_A_POSITIVE_INTERVAL
from conda_package_supply_chain_monitor.policies.models import PackageCurrency
from conda_package_supply_chain_monitor.policies.models import PackageFeedstockPresence
from conda_package_supply_chain_monitor.policies.outcomes import ABSENT
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_ERROR
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_NOT_APPLICABLE
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_NOT_FOUND
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_STATE_LENGTH
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_UNKNOWN
from conda_package_supply_chain_monitor.policies.outcomes import PRESENT_AND_INACTIVE
from conda_package_supply_chain_monitor.policies.outcomes import PRESENT_AND_MAINTAINED
from conda_package_supply_chain_monitor.policies.outcomes import STAGED_RECIPE_PENDING
from conda_package_supply_chain_monitor.policies.outcomes import CurrencyOutcome
from conda_package_supply_chain_monitor.policies.outcomes import FeedstockOutcome
from conda_package_supply_chain_monitor.policies.parameters import INACTIVITY_DAYS_KEY
from conda_package_supply_chain_monitor.policies.parameters import MAX_INACTIVITY_DAYS
from conda_package_supply_chain_monitor.policies.parameters import VERSIONS_TABLE
from conda_package_supply_chain_monitor.policies.parameters import PolicyParameterError
from conda_package_supply_chain_monitor.policies.parameters import PolicyParameters
from conda_package_supply_chain_monitor.policies.parameters import _parameters_directory
from conda_package_supply_chain_monitor.policies.parameters import parameters_directory
from conda_package_supply_chain_monitor.policies.parameters import parameters_file
from conda_package_supply_chain_monitor.policies.parameters import parameters_from
from conda_package_supply_chain_monitor.policies.parameters import parameters_in
from tests.clocks import FIXED_INSTANT
from tests.policy_parameters import parameter_document

if TYPE_CHECKING:
    from pathlib import Path

#: The policy version the parameter cases record. Any stable string does here:
#: what these cases assert is the *keying*, not which version it is.
A_VERSION: Final[str] = "cpm-fixture-policy-1"

#: A version nothing records, for the refusal AC 3 is about.
AN_UNRECORDED_VERSION: Final[str] = "cpm-fixture-policy-nobody-reviewed"

#: The threshold most cases apply, and how it is spelled in a reviewed file.
#: Ninety days rather than the shipped value, deliberately: a case that used the
#: shipped number would pass just as well against a pass that had gone back to
#: reading a constant.
A_THRESHOLD_IN_DAYS: Final[int] = 90
A_THRESHOLD: Final = timedelta(days=A_THRESHOLD_IN_DAYS)

#: A feedstock name, because a determinate `FeedstockSnapshot` row requires one --
#: "a feedstock exists" and "this is which one" are one fact.
A_FEEDSTOCK_NAME: Final[str] = "numpy-feedstock"

#: The staged recipe a `not_found` observation may carry.
A_STAGED_RECIPE_URL: Final[str] = "https://github.com/conda-forge/staged-recipes/pull/26000"

#: A state no `OutcomeState` member carries. The database refuses this row --
#: `state` declares `choices`, which Django does not enforce on `save()`, so the
#: value is reachable in Python and this is the only place it can be built.
A_STATE_FROM_NOWHERE: Final[str] = "probably_fine"

#: A naive instant, for the cut-off refusal. Naive is the whole of what makes it
#: unusable: there is no offset to interpret, so the read would be shifted by
#: whichever offset the reader happened to be in.
A_NAIVE_INSTANT: Final = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - naive on purpose; it is the subject

#: How much older than the threshold an inactive feedstock's last push is, and how
#: much newer a maintained one's. A day either side of the boundary, so neither
#: case is accidentally *on* it -- the boundary has a case of its own, and a
#: fixture sitting on it would make one of these two agree with it by luck.
A_DAY: Final = timedelta(days=1)


def an_observation(  # noqa: PLR0913 - one keyword per fact a feedstock row can carry; a bundle would hide them
    *,
    state: str = OutcomeState.OK,
    activity_at: datetime | None = None,
    staged_recipe_url: str = "",
    established: bool | None = None,
    observed_at: datetime = FIXED_INSTANT,
    pk: int = 1,
) -> FeedstockSnapshot:
    """Build one feedstock observation, unsaved.

    Args:
        state: What the lookup concluded.
        activity_at: When the feedstock was last pushed to, or `None` where the
            collector could not read one.
        staged_recipe_url: The open staged recipe, where the collector found one.
        established: Whether the collector established the absence it recorded.
            `None` -- the default -- means "whatever a `not_found` row ordinarily
            carries", which is True: the great majority of these cases are about
            something other than establishment, and a default of False would make
            every one of them read `unknown` for a reason they are not about.
        observed_at: When the observation was made. Defaulted to the instant the
            cut-off cases use, so an observation is fresh unless a case says
            otherwise.
        pk: The primary key the refusal and the `detail` lines name.

    Returns:
        The unsaved row. Never saved -- see the module docstring for why that is
        what keeps this a unit test, and for why it is the only way to build the
        rows the database refuses.

    """
    return FeedstockSnapshot(
        pk=pk,
        observed_at=observed_at,
        state=state,
        feedstock_name=A_FEEDSTOCK_NAME if state == OutcomeState.OK else "",
        last_recipe_activity_at=activity_at,
        staged_recipe_url=staged_recipe_url,
        absence_established=(state == OutcomeState.NOT_FOUND) if established is None else established,
    )


def a_verdict(
    observation: FeedstockSnapshot | None,
    *,
    threshold: timedelta = A_THRESHOLD,
    cutoff: datetime = FIXED_INSTANT,
) -> str:
    """Return the verdict for one observation, measuring both ages the way the pass does.

    The pass computes the activity age and the observation's own age and hands
    both to `presence_verdict`; a case that computed one and passed `None` for the
    other would be exercising an arrangement the pass never produces.

    Args:
        observation: The observation to judge, or `None`.
        threshold: The inactivity threshold to apply.
        cutoff: The instant to measure both ages against.

    Returns:
        The `FeedstockOutcome` value.

    """
    determinate = observation if observation is not None and observation.state == OutcomeState.OK else None
    return presence_verdict(
        observation,
        age=activity_age(determinate, cutoff=cutoff),
        observed=observation_age(observation, cutoff=cutoff),
        threshold=threshold,
    )


# ---------------------------------------------------------------------------
# The composed vocabulary.
# ---------------------------------------------------------------------------


def test_the_feedstock_outcome_was_composed_by_core_rather_than_written_out() -> None:
    """`CPM-AD-5`: the four sentinels arrive by construction, plus four verdicts of its own.

    Name *and* value, which is what `verify_sentinels` checks and what a
    hand-written table with the right values would fail: Django derives a
    `TextChoices` label from the member name, so a table spelling
    `("not_applicable", "N/A")` satisfies a value check and fails this.

    The four determinate members are asserted in declaration order, because that
    order is what `choices` offers and what the migration froze.
    """
    verify_sentinels(FeedstockOutcome)

    assert [member.value for member in FeedstockOutcome] == [
        *[value for _, value in SENTINEL_MEMBERS],
        ABSENT,
        PRESENT_AND_MAINTAINED,
        PRESENT_AND_INACTIVE,
        STAGED_RECIPE_PENDING,
    ]


def test_the_two_policy_vocabularies_share_their_sentinels_and_nothing_else() -> None:
    """One module, two vocabularies, and no member of either leaking into the other.

    `policies/outcomes.py` holds `CurrencyOutcome` and `FeedstockOutcome` because
    both would close an import cycle anywhere else, and for no other reason. The
    risk of housing them together is a determinate verdict written into the wrong
    one -- a `behind` feedstock, a `present_and_inactive` surface -- which nothing
    else in this repository would notice, because each type is only ever compared
    against itself.
    """
    sentinels = {value for _, value in SENTINEL_MEMBERS}
    currency = {member.value for member in CurrencyOutcome}
    feedstock = {member.value for member in FeedstockOutcome}

    assert currency & feedstock == sentinels
    assert currency - sentinels == {"current", "behind"}
    assert feedstock - sentinels == {ABSENT, PRESENT_AND_MAINTAINED, PRESENT_AND_INACTIVE, STAGED_RECIPE_PENDING}


def test_the_state_length_holds_the_longest_value_this_vocabulary_offers() -> None:
    """A column too narrow for its own vocabulary truncates on SQLite and raises on PostgreSQL.

    The widths are declared per vocabulary rather than derived from one another,
    so this is the check that keeps a declaration honest against the members it is
    about -- and `present_and_maintained` is by some way the longest value any
    outcome type in this product carries.
    """
    assert max(len(member.value) for member in FeedstockOutcome) <= FEEDSTOCK_STATE_LENGTH


def test_the_pass_refines_not_found_and_carries_the_other_three_sentinels() -> None:
    """The one place this vocabulary differs in shape from the currency one.

    `CurrencyOutcome` refines `ok` alone, so its pass returns every sentinel
    unchanged. This domain refines `not_found` as well -- conda-forge answering
    that there is no feedstock is `absent` or `staged_recipe_pending` -- so
    `CARRIED_SENTINELS` must be the other three and `not_found` must still be a
    member of the vocabulary. Both halves: a `CARRIED_SENTINELS` that had grown to
    hold `not_found` would make the pass answer `not_found` and lose the
    distinction the whole story is about, and a vocabulary that had dropped it
    would put a value outside `core`'s five in a column `CPM-AD-5` governs.
    """
    assert OutcomeState.NOT_FOUND.value == REFINED_SENTINEL
    assert {
        OutcomeState.ERROR.value,
        OutcomeState.UNKNOWN.value,
        OutcomeState.NOT_APPLICABLE.value,
    } == CARRIED_SENTINELS
    assert REFINED_SENTINEL not in CARRIED_SENTINELS
    assert FEEDSTOCK_NOT_FOUND in {member.value for member in FeedstockOutcome}


def test_the_rollup_column_offers_exactly_this_vocabulary() -> None:
    """The contribution and the column it lands in must be drawn from one table.

    `core/rollup.py`'s `permitted_values` reads the *column's* declared choices
    and refuses a contribution outside them, so a rollup column declaring
    anything but `FeedstockOutcome` would refuse verdicts this pass is entitled to
    produce -- silently, for as long as the pass ran, because the refusal names
    the value rather than the mismatch.
    """
    assert permitted_values(ROLLUP_COLUMN) == {member.value for member in FeedstockOutcome}
    assert ROLLUP_COLUMN in contributable_columns()
    assert ROLLUP_COLUMN not in STAMP_COLUMNS


def test_the_rollup_column_defaults_to_unknown_rather_than_to_a_clean_value() -> None:
    """A rollup row nothing evaluated must not read as a package with no feedstock problem.

    `core/rollup.py` writes the field's own default for a package no pass
    contributed, and puts that default through `CPM-AD-4`'s gate. A default of
    `present_and_maintained` would make every un-evaluated package read as a
    healthy feedstock; a default of `absent` would be worse still, reporting a
    gap to fill for every package nobody has looked at.
    """
    field = PackageHealth._meta.get_field(ROLLUP_COLUMN)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert field.default == FEEDSTOCK_UNKNOWN
    assert field.editable is False


def test_the_rollup_names_this_column_apart_from_the_currency_passs_feedstock_column() -> None:
    """Two columns in one schema spelled the same and meaning different things.

    `package_currency.feedstock_status` is whether the conda-forge *recipe* pins
    the authoritative version; `package_health.feedstock_presence_status` is
    whether a feedstock exists at all and whether anybody is pushing to it. A
    shared spelling is a query somebody writes correctly and reads wrongly, and
    the naming decision is worth a case rather than a comment because renaming
    either column later is a migration.

    **Both models are read, and that is the correction this case needed.** An
    earlier version built its set from `PackageFeedstockPresence` -- the model
    that has never carried a `feedstock_status` and never will -- so it asserted
    that a column was absent from a table it was never going to be on. A reviewer
    demonstrated the collision could be introduced with the guard green.
    """
    currency_columns = {
        field.name
        for field in PackageCurrency._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    }
    rollup_columns = {
        field.name
        for field in PackageHealth._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    }

    # The non-vacuity half. Built from the *currency* pass's table, and asserted
    # to still hold the column the collision would be with: a guard that read the
    # wrong model would find no `feedstock_status` anywhere, report no collision,
    # and stay green while somebody introduced one.
    assert "feedstock_status" in currency_columns
    assert ROLLUP_COLUMN not in currency_columns
    assert "feedstock_status" not in rollup_columns
    assert ROLLUP_COLUMN in rollup_columns


# ---------------------------------------------------------------------------
# The reviewed parameter file: what it accepts, and what it refuses.
# ---------------------------------------------------------------------------


def test_a_reviewed_file_becomes_one_parameter_set_per_version() -> None:
    """The anti-vacuity guard for every refusal below.

    A reader that refused everything would satisfy each of the refusal cases and
    would make the whole product unrunnable. Two versions with two thresholds,
    because one version cannot show that the *keying* works -- which is the whole
    of AC 3.
    """
    recorded = parameters_from(
        parameter_document({A_VERSION: A_THRESHOLD_IN_DAYS, "cpm-fixture-policy-2": A_THRESHOLD_IN_DAYS * 2}),
        source="a-fixture-file",
    )

    assert set(recorded) == {A_VERSION, "cpm-fixture-policy-2"}
    assert recorded[A_VERSION] == PolicyParameters(version=A_VERSION, feedstock_inactivity=A_THRESHOLD)
    assert recorded["cpm-fixture-policy-2"].feedstock_inactivity == A_THRESHOLD * 2


def test_the_threshold_is_read_as_an_interval_rather_than_as_a_number_of_days() -> None:
    """The unit is converted at the boundary, so nothing downstream carries one in a name.

    A reviewer reads days; the pass compares intervals. If the reader handed on
    the integer, every consumer would have to remember which unit it was in -- and
    the one that forgot would compare a `timedelta` against `180` and get an
    answer rather than an error.
    """
    recorded = parameters_from(parameter_document({A_VERSION: 1}), source="a-fixture-file")

    assert recorded[A_VERSION].feedstock_inactivity == timedelta(days=1)
    assert not isinstance(recorded[A_VERSION].feedstock_inactivity, int)


def test_a_parameter_set_is_frozen() -> None:
    """A set that could be edited after it was read would make "this run applied this version" false."""
    parameters = PolicyParameters(version=A_VERSION, feedstock_inactivity=A_THRESHOLD)

    with pytest.raises((AttributeError, TypeError)):
        parameters.feedstock_inactivity = A_THRESHOLD * 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ("this is not toml at all = = =", "not readable as TOML"),
        (f'strictness = "high"\n[{VERSIONS_TABLE}."{A_VERSION}"]\n{INACTIVITY_DAYS_KEY} = 1\n', "top-level key"),
        (f'[rules."{A_VERSION}"]\n{INACTIVITY_DAYS_KEY} = 1\n', "top-level key"),
        (f"{VERSIONS_TABLE} = 3\n", f"[{VERSIONS_TABLE}] table -- found int"),
        (f"[{VERSIONS_TABLE}]\n", "record no versions at all"),
        (f'[{VERSIONS_TABLE}]\n"{A_VERSION}" = 90\n', "rather than as a table"),
        (f'[{VERSIONS_TABLE}."{A_VERSION}"]\nfeedstock_inactivity_hours = 90\n', "does not define"),
        (f'[{VERSIONS_TABLE}."{A_VERSION}"]\n', f"record no {INACTIVITY_DAYS_KEY}"),
        (f'[{VERSIONS_TABLE}."{A_VERSION}"]\n{INACTIVITY_DAYS_KEY} = 90.5\n', "rather than a whole number of days"),
        (f'[{VERSIONS_TABLE}."{A_VERSION}"]\n{INACTIVITY_DAYS_KEY} = "90"\n', "rather than a whole number of days"),
        (f'[{VERSIONS_TABLE}."{A_VERSION}"]\n{INACTIVITY_DAYS_KEY} = true\n', "rather than a whole number of days"),
        (f'[{VERSIONS_TABLE}."{A_VERSION}"]\n{INACTIVITY_DAYS_KEY} = 0\n', "not a positive interval"),
        (f'[{VERSIONS_TABLE}."{A_VERSION}"]\n{INACTIVITY_DAYS_KEY} = -30\n', "not a positive interval"),
        (
            f'[{VERSIONS_TABLE}."{A_VERSION}"]\n{INACTIVITY_DAYS_KEY} = {MAX_INACTIVITY_DAYS + 1}\n',
            "longer than the",
        ),
        (f'[{VERSIONS_TABLE}.""]\n{INACTIVITY_DAYS_KEY} = 90\n', "names nothing"),
        (f'[{VERSIONS_TABLE}."   "]\n{INACTIVITY_DAYS_KEY} = 90\n', "names nothing"),
        (f'[{VERSIONS_TABLE}." {A_VERSION} "]\n{INACTIVITY_DAYS_KEY} = 90\n', "surrounding whitespace"),
    ],
    ids=[
        "not-toml",
        "an-undefined-top-level-key",
        "the-versions-table-renamed",
        "versions-is-not-a-table",
        "no-versions-recorded",
        "a-version-that-is-a-scalar",
        "a-parameter-key-nothing-reads",
        "a-missing-threshold",
        "a-fractional-threshold",
        "a-threshold-as-a-string",
        "a-threshold-as-a-boolean",
        "a-threshold-of-zero",
        "a-negative-threshold",
        "a-threshold-longer-than-an-interval",
        "an-empty-version-key",
        "a-whitespace-version-key",
        "a-padded-version-key",
    ],
)
def test_a_malformed_parameter_file_is_refused_and_the_message_says_why(document: str, expected: str) -> None:
    """Refuse, never repair -- the matrix's "malformed parameter data" row, per fault.

    Thirteen documents, each one a different way a reviewed file stops being a
    parameter set, and each asserted separately so a failure names which fault
    stopped being caught rather than reporting the reader as broken.

    Sixteen documents. Four are worth naming. **A threshold longer than a
    `timedelta` can express** is refused here so the message names the file and
    the version: built without the check, the constructor raises an
    `OverflowError` about magnitudes with nothing in it to say which parameter
    set a reviewer has to go and correct. **A version key that names nothing, or
    that carries padding**, is refused because the lookup is exact and the run
    ledger refuses a version that names nothing -- so such an entry is one no run
    can ever reach, and a reviewer who wrote it believes they recorded a
    threshold that will be applied. Trimming it instead would match a version the
    run's own ledger row does not carry.

    **A boolean** is refused explicitly because
    `isinstance(True, int)` is true in Python and TOML spells `true` in a way a
    reviewer could reach for -- unrefused it would become a threshold of one day
    and would report almost every feedstock in the inventory as inactive.
    **A key nothing reads** -- `feedstock_inactivity_hours` -- is refused rather
    than ignored, because a silently dropped key is a reviewer who believes they
    changed a verdict. And **zero** is refused because a non-positive interval
    calls every feedstock inactive at the instant it was last pushed to, which is
    a claim about the whole inventory rather than a threshold.

    Every refusal names the file, because these are `CPM-AD-14` governed data and
    an operator sent to the file is being sent to the right place.
    """
    with pytest.raises(PolicyParameterError) as refused:
        parameters_from(document, source="a-fixture-file")

    assert expected in str(refused.value)
    assert "a-fixture-file" in str(refused.value)


def test_a_version_with_no_recorded_parameters_is_refused_rather_than_defaulted() -> None:
    """AC 3's refusal, and the matrix's "unknown policy version" row.

    There is no fallback entry and there must not be one: a default would make a
    run at a version nobody reviewed produce verdicts that look exactly like
    reviewed ones in every report that reads them. The message lists the versions
    the file *does* record, because "no parameters for this version" without them
    sends an operator to open the file by hand.
    """
    recorded = parameters_from(parameter_document({A_VERSION: A_THRESHOLD_IN_DAYS}), source="a-fixture-file")

    with pytest.raises(PolicyParameterError) as refused:
        parameters_in(recorded, version=AN_UNRECORDED_VERSION, source="a-fixture-file")

    assert AN_UNRECORDED_VERSION in str(refused.value)
    assert A_VERSION in str(refused.value), "the message must name the versions that are recorded"
    assert "a-fixture-file" in str(refused.value)


def test_a_recorded_version_is_returned_rather_than_refused() -> None:
    """The other side of the lookup, so it is not simply a function that always refuses."""
    recorded = parameters_from(parameter_document({A_VERSION: A_THRESHOLD_IN_DAYS}), source="a-fixture-file")

    assert parameters_in(recorded, version=A_VERSION, source="a-fixture-file").feedstock_inactivity == A_THRESHOLD


def test_an_unresolvable_module_location_refuses_rather_than_raising_an_oserror(tmp_path: Path) -> None:
    """The directory is computed at import, so a bare `OSError` would have no file name in it.

    An installation that shipped the modules and dropped the data tree is a
    misconfiguration and says so, on exactly the terms
    `collectors/watchlist.py`'s equivalent does.
    """
    with pytest.raises(PolicyParameterError) as refused:
        _parameters_directory(str(tmp_path / "not-a-module.py"))

    assert "not-a-module.py" in str(refused.value)


def test_the_shipped_file_is_the_one_beside_the_reader() -> None:
    """Where the reader looks, asserted without reading it.

    The path is computed from the module's own location rather than from
    `BASE_DIR`, because the `src/` segment does not exist in the wheel layout.
    That the file at that path parses is
    `tests/integration/django_apps/test_feedstock_policy.py`'s to say; that the
    path is the one the wheel puts it at is
    `tests/integration/test_import_resolution.py`'s.

    **Functions rather than module constants**, which is what makes the
    resolution lazy: an installation missing the `data/` tree fails the policy
    run that needed it rather than refusing to boot a web process that would
    never have read it.
    """
    assert parameters_file().parent == parameters_directory()
    assert parameters_directory().name == "data"
    assert parameters_directory().parent.name == "policies"


# ---------------------------------------------------------------------------
# The age, measured against the cut-off and never against the wall clock.
# ---------------------------------------------------------------------------


def test_the_age_is_measured_from_the_cutoff() -> None:
    """`CPM-AD-8`: an age measured from *now* would change every verdict every day.

    The evidence and the rules stand still and the answer must too, which is the
    property the whole replay guarantee is made of. Asserted as an exact interval
    rather than as an inequality: "roughly the right age" is what a wall-clock
    implementation also produces.
    """
    observation = an_observation(activity_at=FIXED_INSTANT - A_THRESHOLD)

    assert activity_age(observation, cutoff=FIXED_INSTANT) == A_THRESHOLD


@pytest.mark.parametrize(
    "observation",
    [None, an_observation(activity_at=None), an_observation(state=OutcomeState.NOT_FOUND)],
    ids=["nothing-observed", "a-feedstock-nobody-could-date", "no-feedstock-at-all"],
)
def test_there_is_no_age_where_there_is_no_instant(observation: FeedstockSnapshot | None) -> None:
    """The three ways a row legitimately carries no measurement.

    None of them is a defensive branch. Nothing observed at the cut-off is an
    ordinary answer for a package the collector has not reached; a determinate
    observation with no instant is what `FeedstockSnapshot` records for a
    feedstock whose last push the collector could not read; and a `not_found` row
    is required by that table's own constraint to carry no feedstock fact at all.
    """
    assert activity_age(observation, cutoff=FIXED_INSTANT) is None


def test_an_activity_instant_after_the_cutoff_gives_a_negative_age_rather_than_a_refusal() -> None:
    """Somebody else's clock skew must not cost a package its verdict.

    A source that reports a push instant after the run's evidence boundary gives a
    negative age, and the honest reading is that the feedstock has been pushed to
    more recently than the boundary -- which is `present_and_maintained` and
    certainly not `present_and_inactive`. Refusing would turn a remote clock into
    a failed package; guessing an age of zero would be an invention. The verdict
    half is asserted here as well as the arithmetic, because the arithmetic alone
    would be satisfied by an implementation that then refused the negative value.
    """
    observation = an_observation(activity_at=FIXED_INSTANT + A_DAY)

    age = activity_age(observation, cutoff=FIXED_INSTANT)

    assert age is not None
    assert age < timedelta()
    assert a_verdict(observation) == PRESENT_AND_MAINTAINED


# ---------------------------------------------------------------------------
# The verdict.
# ---------------------------------------------------------------------------


def test_a_feedstock_pushed_to_inside_the_threshold_is_maintained() -> None:
    """AC 1's first outcome, and the anti-vacuity guard for the rest.

    Every case below is only meaningful while this one holds: a function that
    answered `present_and_inactive` for everything would satisfy the inactive
    case, the boundary case and both sentinel cases.
    """
    observation = an_observation(activity_at=FIXED_INSTANT - (A_THRESHOLD - A_DAY))

    assert activity_age(observation, cutoff=FIXED_INSTANT) == A_THRESHOLD - A_DAY
    assert a_verdict(observation) == PRESENT_AND_MAINTAINED


def test_a_feedstock_not_pushed_to_inside_the_threshold_is_inactive() -> None:
    """AC 1's second outcome: `CPM-UJ-2`'s "one nobody is maintaining"."""
    observation = an_observation(activity_at=FIXED_INSTANT - (A_THRESHOLD + A_DAY))

    assert activity_age(observation, cutoff=FIXED_INSTANT) == A_THRESHOLD + A_DAY
    assert a_verdict(observation) == PRESENT_AND_INACTIVE


def test_a_feedstock_pushed_to_exactly_the_threshold_ago_is_maintained() -> None:
    """The boundary, stated rather than discovered.

    A closed boundary has to fall on one side and the choice is arbitrary; what is
    not arbitrary is that it is written down. The threshold is *how long a
    feedstock may go without a push*, so inactivity begins strictly after it --
    which is what `policies/data/README.md` tells a reviewer choosing a number,
    and what `docs/deployment.md` tells an operator reading a report.

    Asserted as an exact equality on the age as well as on the verdict, or the
    case would be about a fixture that merely happened to be near the boundary.
    """
    observation = an_observation(activity_at=FIXED_INSTANT - A_THRESHOLD)

    age = activity_age(observation, cutoff=FIXED_INSTANT)

    assert age == A_THRESHOLD
    assert a_verdict(observation, threshold=A_THRESHOLD) == PRESENT_AND_MAINTAINED


def test_no_feedstock_and_no_staged_recipe_is_absent() -> None:
    """AC 1's third outcome: `CPM-UJ-2`'s "no feedstock worth filling"."""
    observation = an_observation(state=OutcomeState.NOT_FOUND)

    assert a_verdict(observation) == ABSENT


def test_no_feedstock_but_a_staged_recipe_is_pending_and_never_absent() -> None:
    """AC 1's fourth outcome, and the matrix's "the two are distinct outcomes".

    A package with a staged recipe already has somebody's work behind it: the
    action is to finish a review rather than to write a recipe, and reporting it
    as a gap to fill would send a second person to do the first person's work
    again. The two verdicts are asserted distinct here, because a vocabulary that
    had collapsed them would satisfy the case above and this one's first
    assertion.
    """
    observation = an_observation(state=OutcomeState.NOT_FOUND, staged_recipe_url=A_STAGED_RECIPE_URL)

    assert a_verdict(observation) == STAGED_RECIPE_PENDING
    assert STAGED_RECIPE_PENDING != ABSENT


def test_a_feedstock_that_exists_but_cannot_be_dated_is_unknown_rather_than_inactive() -> None:
    """The matrix's "present but undatable": never inactive by default.

    `FeedstockSnapshot` records a feedstock that exists whose last push the
    collector could not read -- `ok`, with `last_recipe_activity_at` NULL and
    `detail` saying why. A threshold cannot be applied to nothing, so calling it
    inactive would be the guess the whole evidence chain is built to refuse, and
    calling it maintained would be worse. Both wrong answers are asserted against,
    because "not inactive" alone is satisfied by the worse one.
    """
    observation = an_observation(activity_at=None)

    verdict = a_verdict(observation)

    assert verdict == FEEDSTOCK_UNKNOWN
    assert verdict not in MEASURED_VERDICTS


def test_nothing_observed_at_the_cutoff_is_unknown_and_never_absent() -> None:
    """The matrix's "no observation": never `absent` from an absence of looking.

    `absent` is a claim about conda-forge -- there is no feedstock and nothing
    queued to make one -- and it is a claim that sends somebody to write a recipe.
    Reaching it because nobody had looked is the single most expensive wrong
    answer this pass could give, which is why it is asserted against rather than
    left implied by the `unknown`.
    """
    verdict = a_verdict(None)

    assert verdict == FEEDSTOCK_UNKNOWN
    assert verdict != ABSENT


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (OutcomeState.ERROR.value, FEEDSTOCK_ERROR),
        (OutcomeState.UNKNOWN.value, FEEDSTOCK_UNKNOWN),
        (OutcomeState.NOT_APPLICABLE.value, FEEDSTOCK_NOT_APPLICABLE),
    ],
    ids=["errored", "unobserved-by-the-collector", "not-this-packages-question"],
)
def test_each_carried_sentinel_state_becomes_the_same_sentinel_verdict(state: str, expected: str) -> None:
    """`CPM-FR-6`: the states stay un-collapsed, one for one.

    An `error` is not an absence and a `not_applicable` is not an absence, which
    is the distinction a boolean status cannot hold and the reason `CPM-AD-5` bans
    one. Each is asserted separately so a fold of any two would name which.

    `not_found` is deliberately not in this list: it is the one state this domain
    refines, and it has two cases of its own above.
    """
    observation = an_observation(state=state)

    assert a_verdict(observation) == expected


def test_a_state_outside_the_vocabulary_is_refused_rather_than_read_as_an_absence() -> None:
    """An unrecognised value must not become a clean-looking answer.

    `state` declares `choices`, which Django enforces on a form and never on
    `save()`, so a row carrying anything at all is reachable -- through raw SQL,
    through a data migration, through a collector written after somebody widened
    the vocabulary in one place. Reading it as `unknown` would be the fold
    `CPM-FR-6` forbids arrived at by silence; refusing costs one package's row and
    leaves the rest of the run committed (`CPM-AD-23`).
    """
    observation = an_observation(state=A_STATE_FROM_NOWHERE)

    with pytest.raises(FeedstockPolicyError) as refused:
        a_verdict(observation)

    assert A_STATE_FROM_NOWHERE in str(refused.value)


def test_two_thresholds_over_one_observation_reach_two_verdicts() -> None:
    """AC 3, as arithmetic: the verdict is a function of the threshold and nothing else.

    The integration module proves this *through two policy runs at two versions*,
    which is what makes the parameter versioned data rather than merely an
    argument. This is the half that shows the argument is load-bearing at all: one
    observation, two thresholds, two answers. A pass that had gone back to a
    constant would fail here as well as there, and would fail here first.
    """
    observation = an_observation(activity_at=FIXED_INSTANT - A_THRESHOLD - A_DAY)

    assert a_verdict(observation, threshold=A_THRESHOLD) == PRESENT_AND_INACTIVE
    assert a_verdict(observation, threshold=A_THRESHOLD * 2) == PRESENT_AND_MAINTAINED


# ---------------------------------------------------------------------------
# An absence has to have been established, and an observation has to be fresh.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("staged", ["", A_STAGED_RECIPE_URL], ids=["nothing-queued", "something-queued"])
def test_an_absence_the_collector_did_not_establish_is_unknown(staged: str) -> None:
    """The row `not_found` is reachable four ways, and three of them are not evidence.

    `collectors/feedstock.py` writes `not_found` when conda-forge answered that
    the repository is not there, when the repository could not be read, when the
    staged-recipes queue could not be read, and when the queue answered
    ambiguously or overflowed its page. Only the first is evidence of an absence,
    and `absence_established` is what says which one this row is.

    Reporting `absent` from one of the other three sends somebody to write a
    recipe that may already exist or already be queued -- which is exactly the
    outcome `staged_recipe_pending` was invented to prevent, arrived at from the
    other direction.

    **Both queue shapes, because both are wrong for the same reason.** A staged
    recipe is only *pending* if there is no feedstock, and on an unestablished
    row that is the half nobody confirmed: a package whose repository could not
    be read may well have a feedstock *and* an open pull request that will be
    closed as redundant.
    """
    observation = an_observation(state=OutcomeState.NOT_FOUND, staged_recipe_url=staged, established=False)

    verdict = a_verdict(observation)

    assert verdict == FEEDSTOCK_UNKNOWN
    assert verdict != ABSENT
    assert verdict != STAGED_RECIPE_PENDING


def test_an_established_absence_is_what_makes_absent_reachable_at_all() -> None:
    """The other side, so the rule above is not simply one that answers `unknown`.

    Two observations differing in one boolean and in nothing else. Without this
    the case above would pass just as well against a pass that had stopped
    producing `absent` entirely, which is the failure mode a guard against
    over-claiming most easily becomes.
    """
    established = an_observation(state=OutcomeState.NOT_FOUND, established=True)
    unestablished = an_observation(state=OutcomeState.NOT_FOUND, established=False)

    assert a_verdict(established) == ABSENT
    assert a_verdict(unestablished) == FEEDSTOCK_UNKNOWN


def test_a_whitespace_only_staged_recipe_url_is_no_staged_recipe() -> None:
    """A gap that needs a recipe must not be reported as one already queued.

    `staged_recipe_url` is a `CharField` whose blank is `""`, and a value that is
    nothing but spaces is blank in every sense except the one a truth test uses.
    Left alone it produces `staged_recipe_pending` -- and then a `detail` naming
    an empty pull request -- for a package nobody has queued anything for, which
    is the more expensive of the two wrong answers: `absent` at least sends
    somebody to do work that needs doing.
    """
    observation = an_observation(state=OutcomeState.NOT_FOUND, staged_recipe_url="   ")

    assert a_verdict(observation) == ABSENT


def test_a_feedstock_nobody_re_observed_is_unknown_rather_than_inactive() -> None:
    """A collector that stopped running is not a feedstock that stopped moving.

    The activity age is measured against the run's cut-off, so a snapshot from
    long ago whose push was longer ago still produces a large age and, left
    alone, `present_and_inactive` -- indistinguishable on the row from a
    genuinely abandoned recipe. What separates them is the age of the
    *observation*, and this product already treats that as a first-class question
    (`CPM-AD-28`, `core/freshness.py`).

    So an observation older than the applied threshold cannot support a
    maintenance verdict at all, and the row says so rather than leaving a reader
    to notice that the evidence is a year old.
    """
    stale = an_observation(
        observed_at=FIXED_INSTANT - (A_THRESHOLD + A_DAY),
        activity_at=FIXED_INSTANT - (A_THRESHOLD * 3),
    )

    verdict = a_verdict(stale)

    assert verdict == FEEDSTOCK_UNKNOWN
    assert verdict != PRESENT_AND_INACTIVE


def test_a_stale_observation_of_a_recent_push_is_unknown_too() -> None:
    """The claim is about the observation, not about which way its answer pointed.

    A rule that only refused the *inactive* verdict would keep reporting
    `present_and_maintained` from a year-old snapshot, which is the same
    over-claim wearing the other face: it says somebody is maintaining a recipe
    on the strength of evidence nobody has refreshed.
    """
    stale = an_observation(observed_at=FIXED_INSTANT - (A_THRESHOLD + A_DAY), activity_at=FIXED_INSTANT - A_DAY)

    assert a_verdict(stale) == FEEDSTOCK_UNKNOWN


def test_a_fresh_observation_of_an_old_push_is_still_inactive() -> None:
    """The case the staleness rule must not swallow, and the reason it is narrow.

    An old push seen *recently* is exactly the finding `CPM-UJ-2` asks for: a
    feedstock nobody is maintaining. A staleness rule that reached this row would
    turn the pass's whole purpose into `unknown` the moment a threshold was set
    shorter than the pushes it is meant to catch.
    """
    fresh = an_observation(observed_at=FIXED_INSTANT, activity_at=FIXED_INSTANT - (A_THRESHOLD + A_DAY))

    assert a_verdict(fresh) == PRESENT_AND_INACTIVE


def test_an_observation_exactly_the_threshold_old_still_supports_a_verdict() -> None:
    """The staleness boundary, on the same side as the activity boundary.

    Two closed boundaries in one function that disagreed about which side they
    close on would be a rule nobody could state; both are `<=`, and both are
    written down.
    """
    boundary = an_observation(observed_at=FIXED_INSTANT - A_THRESHOLD, activity_at=FIXED_INSTANT)

    assert observation_age(boundary, cutoff=FIXED_INSTANT) == A_THRESHOLD
    assert a_verdict(boundary) == PRESENT_AND_MAINTAINED


def test_staleness_does_not_reach_an_absence() -> None:
    """The stated boundary of the staleness rule, asserted rather than left implied.

    A maintenance verdict is a claim about the interval between the last push and
    the cut-off, and an old observation cannot support it. `absent` is a claim
    about what conda-forge held when somebody looked -- age makes it older, not
    false -- and `core/freshness.py` is where "how old is this" belongs beside
    every verdict for a read surface to report. Widening the rule here would put
    a second freshness mechanism in a policy pass.
    """
    stale = an_observation(
        state=OutcomeState.NOT_FOUND,
        observed_at=FIXED_INSTANT - (A_THRESHOLD * 3),
        established=True,
    )

    assert a_verdict(stale) == ABSENT


@pytest.mark.parametrize(
    "observation",
    [
        an_observation(activity_at=A_NAIVE_INSTANT),
        an_observation(observed_at=A_NAIVE_INSTANT, activity_at=FIXED_INSTANT),
    ],
    ids=["a-naive-activity-instant", "a-naive-observed-at"],
)
def test_a_naive_instant_on_the_evidence_row_is_refused_by_name(observation: FeedstockSnapshot) -> None:
    """A `TypeError` about datetimes names neither the row nor the fault.

    `USE_TZ` is on, so Django reads a naive value back as if it were UTC and the
    subtraction against an aware cut-off raises `can't subtract offset-naive and
    offset-aware datetimes` -- which fails the package with a message about
    Python's arithmetic and nothing in it saying which observation to go and
    look at. Every other instant guard in this product refuses one explicitly,
    and these two now do.

    Both instants, because the row carries two and they are guarded in different
    functions.
    """
    with pytest.raises(FeedstockPolicyError) as refused:
        a_verdict(observation)

    assert str(observation.pk) in str(refused.value)


# ---------------------------------------------------------------------------
# What the row says about itself.
# ---------------------------------------------------------------------------


def test_the_detail_says_an_undatable_feedstock_could_not_be_dated() -> None:
    """The matrix's "the row says the activity could not be dated".

    The three measurement columns are all empty on such a row, so without this
    line a reader cannot tell "a feedstock exists that nobody could date" from "no
    feedstock observation at the cut-off" -- and those call for entirely different
    work. The observation is named, so the reader can go and read the collector's
    own `detail` for why.
    """
    observation = an_observation(activity_at=None, pk=41)

    detail = presence_detail(observation, FEEDSTOCK_UNKNOWN, age=None, observed=timedelta(), threshold=A_THRESHOLD)

    assert "41" in detail
    assert str(A_THRESHOLD) in detail
    assert "unknown rather than inactive" in detail


def test_the_detail_names_the_staged_recipe_a_pending_verdict_is_about() -> None:
    """The locator lives on the evidence row, and the point of the verdict is to go and look at it."""
    observation = an_observation(state=OutcomeState.NOT_FOUND, staged_recipe_url=A_STAGED_RECIPE_URL, pk=42)

    detail = presence_detail(observation, STAGED_RECIPE_PENDING, age=None, observed=timedelta(), threshold=A_THRESHOLD)

    assert A_STAGED_RECIPE_URL in detail
    assert "42" in detail


@pytest.mark.parametrize(
    ("observation", "verdict"),
    [
        (None, FEEDSTOCK_UNKNOWN),
        (an_observation(state=OutcomeState.NOT_FOUND), ABSENT),
        (an_observation(state=OutcomeState.ERROR), FEEDSTOCK_ERROR),
        (an_observation(state=OutcomeState.NOT_APPLICABLE), FEEDSTOCK_NOT_APPLICABLE),
        (an_observation(activity_at=FIXED_INSTANT), PRESENT_AND_MAINTAINED),
        (an_observation(activity_at=FIXED_INSTANT - A_THRESHOLD * 2), PRESENT_AND_INACTIVE),
    ],
    ids=["nothing-observed", "absent", "errored", "inapplicable", "maintained", "inactive"],
)
def test_the_detail_is_empty_on_every_row_that_explains_itself(
    observation: FeedstockSnapshot | None,
    verdict: str,
) -> None:
    """An explanation of an unremarkable row is noise, and every evidence table agrees.

    The negative control for the two cases above: a `detail` populated on every
    row would satisfy both of them and would say nothing. The two maintenance
    verdicts in particular carry the threshold, the instant and the age as
    *columns*, which is the whole of how each was reached.
    """
    determinate = observation if observation is not None and observation.state == OutcomeState.OK else None
    detail = presence_detail(
        observation,
        verdict,
        age=activity_age(determinate, cutoff=FIXED_INSTANT),
        observed=observation_age(observation, cutoff=FIXED_INSTANT),
        threshold=A_THRESHOLD,
    )

    assert detail == ""


def test_the_detail_says_an_absence_was_not_established() -> None:
    """The `unknown` a reader would otherwise take for "nobody looked".

    An unestablished absence and a package with no observation at all produce the
    same verdict and the same three empty measurement columns. The line is what
    separates them, and it points at the observation, whose own `detail` says
    which of the four ways it was.
    """
    observation = an_observation(state=OutcomeState.NOT_FOUND, established=False, pk=51)

    detail = presence_detail(
        observation,
        FEEDSTOCK_UNKNOWN,
        age=None,
        observed=timedelta(),
        threshold=A_THRESHOLD,
    )

    assert "51" in detail
    assert "not established" in detail
    assert "unknown rather than absent" in detail


def test_the_detail_says_the_observation_was_too_old_to_judge() -> None:
    """The other `unknown` a reader would otherwise take for "nobody looked".

    Both ages are named, because the whole of the reason is the comparison
    between them: the observation is older than the threshold it would have been
    measured against.
    """
    observation = an_observation(observed_at=FIXED_INSTANT - (A_THRESHOLD + A_DAY), activity_at=FIXED_INSTANT, pk=52)

    detail = presence_detail(
        observation,
        FEEDSTOCK_UNKNOWN,
        age=A_DAY,
        observed=A_THRESHOLD + A_DAY,
        threshold=A_THRESHOLD,
    )

    assert "52" in detail
    assert str(A_THRESHOLD + A_DAY) in detail
    assert str(A_THRESHOLD) in detail
    assert "unknown rather than inactive" in detail


def test_a_future_dated_push_keeps_its_verdict_and_says_so() -> None:
    """Clock skew must not be visible only to somebody who sorts by the age column.

    A push instant later than the cut-off gives a negative age, and the verdict
    stays `present_and_maintained` -- which is what a push after the evidence
    boundary means, and refusing it would turn somebody else's clock into a
    failed package. What was missing is that the row said nothing: an ordinary
    maintained row and one resting on an impossible instant were byte-identical
    apart from a sign, permanently.
    """
    observation = an_observation(activity_at=FIXED_INSTANT + A_DAY, pk=53)

    detail = presence_detail(
        observation,
        PRESENT_AND_MAINTAINED,
        age=-A_DAY,
        observed=timedelta(),
        threshold=A_THRESHOLD,
    )

    assert a_verdict(observation) == PRESENT_AND_MAINTAINED
    assert "53" in detail
    assert str(A_DAY) in detail
    assert "after this run's cut-off" in detail


# ---------------------------------------------------------------------------
# The cut-off-bound read, and what it refuses without a database.
# ---------------------------------------------------------------------------


def test_a_naive_cutoff_is_refused_before_any_query_runs() -> None:
    """`CPM-FR-22`'s replay depends on the cut-off meaning one instant.

    `USE_TZ` is on, so Django would read a naive value as if it were UTC and the
    read would be silently shifted by whichever offset the reader happened to be
    in -- selecting a different evidence set on every replay. The refusal is made
    before the query, which is what lets this case run with no database at all.

    **The other side of the guard is not here, and deliberately.** An aware
    cut-off opens a query, so a case asserting "this one is not refused" in the
    unit tier could only assert it by catching pytest-django's database block --
    which passes for a reason that has nothing to do with the guard. Every case in
    `tests/integration/django_apps/test_feedstock_policy.py` reads through this
    function with an aware cut-off, which is where "it does not simply refuse
    everything" is actually shown.
    """
    with pytest.raises(FeedstockPolicyError) as refused:
        observed_feedstock(package_id=1, cutoff=A_NAIVE_INSTANT)

    assert "feedstock" in str(refused.value)


# ---------------------------------------------------------------------------
# What the pass and its table declare.
# ---------------------------------------------------------------------------


def test_the_pass_declares_its_name_its_table_and_its_one_column() -> None:
    """The three declarations `core/policy.py` reads, and nothing else.

    `contributes` is asserted as the exact tuple rather than by containment: a
    pass claiming a second column would own a column another epic's pass is coming
    for, and the registry's refusal would then land on *that* pass rather than on
    this one.
    """
    assert issubclass(FeedstockPresencePass, PolicyPass)
    assert FeedstockPresencePass.name == POLICY_NAME
    assert FeedstockPresencePass.derived_model is PackageFeedstockPresence
    assert FeedstockPresencePass.contributes == (ROLLUP_COLUMN,)


def test_the_pass_name_is_not_the_currency_passs() -> None:
    """Two passes under one name are indistinguishable in every report.

    `register_pass` refuses the collision, so this would be caught at boot -- but
    it would be caught as a component that will not start, with a message about a
    registry rather than about the naming decision. `feedstock-presence` rather
    than `feedstock` is that decision: `CPM-EP-PY314` has a feedstock pass of its
    own coming, about whether a recipe *builds*.
    """

    assert POLICY_NAME != CURRENCY_POLICY_NAME
    assert POLICY_NAME == "feedstock-presence"


def test_the_derived_table_declares_every_constraint_by_name() -> None:
    """The four rules the database keeps, read off `Meta.constraints`.

    Names only, which is the weaker half: each is *proved by the database
    refusing a row* in `tests/integration/django_apps/test_feedstock_policy.py`,
    because a case asserting a constraint by name passes just as well against one
    that has been weakened to `1 = 1`. What this adds is that a constraint deleted
    outright fails in the unit tier, where the failure is cheap and names itself.
    """
    declared = {constraint.name for constraint in PackageFeedstockPresence._meta.constraints}  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert declared == {
        ONE_FEEDSTOCK_ROW_PER_PACKAGE_PER_RUN,
        THRESHOLD_IS_A_POSITIVE_INTERVAL,
        AN_AGE_EXACTLY_WHEN_THERE_IS_AN_INSTANT,
        MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT,
        DETERMINATE_PRESENCE_NEEDS_AN_OBSERVATION,
    }


def test_the_measured_verdicts_are_the_two_reached_by_comparing_an_age() -> None:
    """The constraint and the pass must agree about which verdicts need an instant.

    `MEASURED_VERDICTS` is what
    `MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT` is built from, and it is
    read by nothing in `policies/feedstock.py` -- the pass reaches the same two
    verdicts through its own comparison. Two declarations of one fact need a check
    between them, and this is it: a third determinate verdict that also needed an
    age would have to be added here, and one that did not must not be.
    """
    assert set(MEASURED_VERDICTS) == {PRESENT_AND_MAINTAINED, PRESENT_AND_INACTIVE}
    assert ABSENT not in MEASURED_VERDICTS
    assert STAGED_RECIPE_PENDING not in MEASURED_VERDICTS


def test_the_verdict_column_offers_the_whole_vocabulary_and_is_not_editable() -> None:
    """`CPM-AD-5` and `CPM-FR-37`.

    Not nullable and not blank: NULL and the empty string would each be a
    non-answer with no name and no value, which is the second vocabulary
    `CPM-FR-6` exists to prevent. Not editable: a derived verdict is a policy
    run's to write and nobody else's, and `editable=False` is the half of that
    which holds against a human with a browser and a permission.
    """
    field = PackageFeedstockPresence._meta.get_field("presence_status")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert {value for value, _ in field.choices or ()} == {member.value for member in FeedstockOutcome}
    assert field.null is False
    assert field.blank is False
    assert field.editable is False


@pytest.mark.parametrize(
    "column",
    ["presence_status", "inactivity_threshold", "last_recipe_activity_at", "activity_age", "confidence", "detail"],
    ids=str,
)
def test_nothing_a_policy_run_decides_is_editable(column: str) -> None:
    """A form that could rewrite one of these would leave the row contradicting itself.

    The writability audit reaches only fields *named* for a status, so only
    `presence_status` would have failed there -- and a row whose threshold had been
    edited while its verdict had not is a row that cannot be audited or replayed,
    which is the same defect the naming convention exists to catch.
    """
    field = PackageFeedstockPresence._meta.get_field(column)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert field.editable is False, column


def test_the_threshold_is_required_and_the_measurements_are_not() -> None:
    """The nullability decisions, each argued where it lands.

    The threshold is looked up before any evidence is read and a run whose version
    records none never reaches a write, so a row exists only where a threshold was
    known -- which is what lets that column be NOT NULL and what makes AC 3
    auditable per row. The instant and the age are NULL on every row where there
    was no measurement to make, which is three of the eight verdicts.
    """
    fields = {
        name: PackageFeedstockPresence._meta.get_field(name)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        for name in ("inactivity_threshold", "last_recipe_activity_at", "activity_age")
    }

    assert fields["inactivity_threshold"].null is False
    assert fields["last_recipe_activity_at"].null is True
    assert fields["activity_age"].null is True


def test_the_row_records_the_confidence_it_was_computed_under() -> None:
    """`CPM-AD-4` read from the other side: what the gate *would* have done.

    The rollup's copy has been through the gate and this one has not, so a reader
    of this table can see an `unmapped` package's real verdict beside the
    confidence that will replace it. The column declares `IdentityConfidence`'s
    own values rather than a second spelling of three strings, which is the rule
    `identity/confidence.py` exists to make possible.
    """
    field = PackageFeedstockPresence._meta.get_field("confidence")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert {value for value, _ in field.choices or ()} == set(IdentityConfidence.values)


def test_the_derived_table_references_the_evidence_its_verdict_rests_on() -> None:
    """A verdict that named no observation could not be audited or explained.

    Nullable, because a package nothing observed still gets a row; `PROTECT`,
    because a snapshot deleted out from under a row that cites it would leave the
    row claiming a maintenance state nothing can be shown for.
    """
    field = PackageFeedstockPresence._meta.get_field("feedstock_snapshot")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert field.null is True
    assert field.remote_field.model is FeedstockSnapshot  # type: ignore[union-attr]
    assert field.remote_field.on_delete.__name__ == "PROTECT"  # type: ignore[union-attr]


@pytest.mark.parametrize("relation", ["package", "policy_run", "feedstock_snapshot"], ids=str)
def test_every_relation_protects(relation: str) -> None:
    """`CASCADE` would let an operational tidy-up quietly empty the audit trail.

    Deleting a policy run would take away the findings that explain a rollup row
    still naming it, and deleting an evidence row would take away the support for
    a verdict. Asserted per relation because a table gains them one at a time and
    the one added last is the one that gets the default.
    """
    field = PackageFeedstockPresence._meta.get_field(relation)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert field.remote_field.on_delete.__name__ == "PROTECT"  # type: ignore[union-attr]


def test_the_derived_table_row_renders_before_it_is_saved() -> None:
    """A `__str__` that raised would break the two places a half-built row is rendered.

    An unsaved instance has no related object, so reading `self.package` raises
    `RelatedObjectDoesNotExist` -- in a debugger and in a traceback, which are
    exactly where a `__str__` is called on a half-built object. Read off
    `package_id` instead, on the same terms as `PackageCurrency.__str__`.
    """
    assert "no package" in str(PackageFeedstockPresence())
    assert "no threshold" in str(PackageFeedstockPresence())
    rendered = str(PackageFeedstockPresence(package_id=7, presence_status=ABSENT, inactivity_threshold=A_THRESHOLD))
    assert "package 7" in rendered
    assert ABSENT in rendered


def test_this_readers_ordering_key_is_the_sibling_passs() -> None:
    """The fourth hand-written copy of one rule, reconciled against the third.

    `collectors/models.py`'s `snapshot_as_of` states the cut-off-bound read;
    `policies/currency.py` copies it with a per-surface tie-break in the middle,
    and this module copies it with none. `observed_feedstock`'s docstring argues
    why a fourth copy is deliberate rather than lazy -- reuse would make a
    feedstock pass raise a `CurrencyPolicyError` -- and that argument is only
    honest while the two keys actually agree.

    Asserted against the sibling's *construction* rather than against a literal,
    so a change to either one fails here rather than leaving two readers quietly
    ordering differently. The feedstock surface's reader is the one with no
    tie-break, which is what makes the two comparable at all.
    """

    sibling = next(reader for reader in SURFACE_READERS if reader.model is FeedstockSnapshot)

    assert sibling.tie_break == ()
    assert ("-observed_at", *sibling.tie_break, "-pk") == READ_ORDERING


def test_the_pass_refuses_to_evaluate_before_its_parameters_were_established() -> None:
    """`prepare` is not optional for *this* pass, and the refusal says which caller erred.

    `core/policy_run.py` prepares every pass once per run before the package
    loop, so this is unreachable through the orchestration. What it is reachable
    through is a caller constructing the pass by hand -- which is what the
    query-count case does -- and the alternative to this message is an
    `AttributeError` on `None` from inside a comparison, which says nothing about
    what was skipped.
    """
    unprepared = FeedstockPresencePass()

    with pytest.raises(FeedstockPolicyError) as refused:
        unprepared._threshold()  # noqa: SLF001 - the guard is this case's whole subject

    assert POLICY_NAME in str(refused.value)
    assert "prepare" in str(refused.value)


def test_every_pass_may_prepare_and_the_base_does_nothing() -> None:
    """The hook is optional, and `CurrencyPass` relies on that.

    `core/policy.py`'s default is a no-op so a pass with no run-wide precondition
    overrides nothing. Asserted here rather than only in `core`'s own module
    because this story is what added the hook, and a base that had grown a
    default behaviour would change what the sibling pass does without touching
    it.
    """

    assert CurrencyPass.prepare is PolicyPass.prepare
    assert FeedstockPresencePass.prepare is not PolicyPass.prepare
