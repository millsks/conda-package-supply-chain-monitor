"""`CPM-FR-16`'s comparison, its vocabulary and its authority choice, without a database.

`policies/currency.py` is deliberately split into a query and some arithmetic:
`observed_surface` is the only function that touches the database, and everything
that *decides* anything takes a reading and returns a verdict. That split is what
lets every row of the story's I/O matrix that is about a decision be exercised
here, in milliseconds, against constructed observations -- and it is why the
integration module beside this one is about the orchestration rather than about
the rules.

**Unsaved model instances, and that is what keeps this a unit test.** An
evidence row is constructed with `SourceReleaseSnapshot(...)` and never saved:
`_meta` is populated at import, the fields hold whatever they were given, and
nothing here opens a connection. It is also the only way to build the one row the
database refuses -- a `state` outside the vocabulary -- which is exactly the row
`surface_verdict` must not read as an absence.

**The composed type's sentinels are asserted by identity of value, not assumed.**
`core.outcomes.outcome_type` guarantees that `CurrencyOutcome`'s four sentinels
carry `OutcomeState`'s values, and `surface_verdict` depends on that guarantee: it
returns the observation's own state string for a sentinel rather than mapping the
four by hand. So the guarantee is pinned here, per sentinel, against this
module's named constants.

No database, no network, no subprocess.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import pytest
from django.core.exceptions import ValidationError

from conda_package_supply_chain_monitor.collectors.models import CondaPackageSnapshot
from conda_package_supply_chain_monitor.collectors.models import FeedstockSnapshot
from conda_package_supply_chain_monitor.collectors.models import PyPIReleaseSnapshot
from conda_package_supply_chain_monitor.collectors.models import SourceReleaseSnapshot
from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.outcomes import SENTINEL_MEMBERS
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.outcomes import OutcomeVocabularyError
from conda_package_supply_chain_monitor.core.outcomes import verify_sentinels
from conda_package_supply_chain_monitor.core.policy import PolicyPass
from conda_package_supply_chain_monitor.core.rollup import STAMP_COLUMNS
from conda_package_supply_chain_monitor.core.rollup import contributable_columns
from conda_package_supply_chain_monitor.core.rollup import permitted_values
from conda_package_supply_chain_monitor.identity.models import DEFAULT_AUTHORITY_ORDER
from conda_package_supply_chain_monitor.identity.models import AuthorityOrderError
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.models import VersionSurface
from conda_package_supply_chain_monitor.identity.models import applied_authority_order
from conda_package_supply_chain_monitor.identity.models import authority_order_fault
from conda_package_supply_chain_monitor.identity.models import validate_authority_order
from conda_package_supply_chain_monitor.policies.currency import POLICY_NAME
from conda_package_supply_chain_monitor.policies.currency import ROLLUP_COLUMN
from conda_package_supply_chain_monitor.policies.currency import SENTINEL_VALUES
from conda_package_supply_chain_monitor.policies.currency import SURFACE_READERS
from conda_package_supply_chain_monitor.policies.currency import CurrencyPass
from conda_package_supply_chain_monitor.policies.currency import CurrencyPolicyError
from conda_package_supply_chain_monitor.policies.currency import SurfaceReader
from conda_package_supply_chain_monitor.policies.currency import SurfaceReading
from conda_package_supply_chain_monitor.policies.currency import authoritative_version
from conda_package_supply_chain_monitor.policies.currency import comparable_version
from conda_package_supply_chain_monitor.policies.currency import discrepancy_detail
from conda_package_supply_chain_monitor.policies.currency import observed_surface
from conda_package_supply_chain_monitor.policies.currency import overall_verdict
from conda_package_supply_chain_monitor.policies.currency import surface_verdict
from conda_package_supply_chain_monitor.policies.models import AUTHORITY_IS_A_KNOWN_SURFACE
from conda_package_supply_chain_monitor.policies.models import DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY
from conda_package_supply_chain_monitor.policies.models import ONE_ROW_PER_PACKAGE_PER_RUN
from conda_package_supply_chain_monitor.policies.models import SURFACE_STATUS_FIELDS
from conda_package_supply_chain_monitor.policies.models import AuthorityOrderSource
from conda_package_supply_chain_monitor.policies.models import PackageCurrency
from conda_package_supply_chain_monitor.policies.outcomes import BEHIND
from conda_package_supply_chain_monitor.policies.outcomes import CURRENCY_PRECEDENCE
from conda_package_supply_chain_monitor.policies.outcomes import CURRENT
from conda_package_supply_chain_monitor.policies.outcomes import ERROR
from conda_package_supply_chain_monitor.policies.outcomes import NOT_APPLICABLE
from conda_package_supply_chain_monitor.policies.outcomes import NOT_FOUND
from conda_package_supply_chain_monitor.policies.outcomes import UNKNOWN
from conda_package_supply_chain_monitor.policies.outcomes import CurrencyOutcome
from tests.clocks import FIXED_INSTANT

#: The version the authoritative surface states in most cases here. Any stable
#: string does: what the comparison asserts is equality, not which version.
AN_AUTHORITY_VERSION: Final[str] = "2.4.0"

#: A different version, for the surface that is behind. Different is the whole of
#: what it has to be -- this pass compares for equality and deliberately does not
#: order, so "earlier" is a description for a reader rather than a property
#: anything here depends on.
A_DIFFERENT_VERSION: Final[str] = "2.3.1"

#: A version any ordering rule would call newer than the authority's. Used by the
#: one case that separates equality from a smuggled-in ordering: a surface ahead
#: of the authority reads `behind` exactly as one behind it does.
A_LATER_VERSION: Final[str] = "2.5.0"

#: A version spelled as a Git tag conventionally spells it. The one difference
#: `comparable_version` reconciles.
THE_SAME_VERSION_TAGGED: Final[str] = f"v{AN_AUTHORITY_VERSION}"

#: A state no `OutcomeState` member carries. The database refuses this row --
#: `state` declares `choices`, which Django does not enforce on `save()`, so the
#: value is reachable in Python and this is the only place it can be built.
A_STATE_FROM_NOWHERE: Final[str] = "probably_fine"

#: A naive instant, for the cut-off refusal. Naive is the whole of what makes it
#: unusable: there is no offset to interpret, so the read would be shifted by
#: whichever offset the reader happened to be in.
A_NAIVE_INSTANT: Final = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - naive on purpose; it is the subject

#: The four surfaces, so a case can say "every surface" without writing them out
#: and without deriving them from the thing under test.
EVERY_SURFACE: Final[tuple[str, ...]] = (
    VersionSurface.SOURCE.value,
    VersionSurface.PYPI.value,
    VersionSurface.FEEDSTOCK.value,
    VersionSurface.CONDA_PACKAGE.value,
)


def a_reading(
    surface: str,
    *,
    state: str = OutcomeState.OK,
    version: str = AN_AUTHORITY_VERSION,
    observed: bool = True,
) -> SurfaceReading:
    """Build one surface reading from an unsaved evidence row.

    Args:
        surface: The `VersionSurface` value the reading is about.
        state: The state the observation carries.
        version: The version it states.
        observed: False for a surface nothing observed at the cut-off, which is
            the reading carrying no row at all.

    Returns:
        The reading. The evidence row is constructed and never saved -- see the
        module docstring for why that is what keeps this a unit test, and for why
        it is the only way to build a row carrying a state the database refuses.

    """
    if not observed:
        return SurfaceReading(surface=surface, observation=None, version="")
    reader = next(candidate for candidate in SURFACE_READERS if candidate.surface == surface)
    observation = reader.model(state=state, observed_at=FIXED_INSTANT, **{reader.version_field: version})
    return SurfaceReading(surface=surface, observation=observation, version=version)


def readings(**by_surface: SurfaceReading) -> dict[str, SurfaceReading]:
    """Return a full set of readings, defaulting every surface not named to unobserved.

    Args:
        **by_surface: The readings to place, keyed by `VersionSurface` value.

    Returns:
        One reading per surface. Complete rather than partial, because
        `CurrencyPass` always reads all four and a partial mapping would let a
        case assert against a shape the pass never produces.

    """
    return {surface: by_surface.get(surface, a_reading(surface, observed=False)) for surface in EVERY_SURFACE}


# ---------------------------------------------------------------------------
# The composed vocabulary.
# ---------------------------------------------------------------------------


def test_the_currency_outcome_was_composed_by_core_rather_than_written_out() -> None:
    """`CPM-AD-5`: the four sentinels arrive by construction, plus two verdicts of its own.

    Name *and* value, which is what `verify_sentinels` checks and what a
    hand-written table with the right values would fail: Django derives a
    `TextChoices` label from the member name, so a table spelling
    `("not_applicable", "N/A")` satisfies a value check and fails this.
    """
    verify_sentinels(CurrencyOutcome)

    assert [member.value for member in CurrencyOutcome] == [
        *[value for _, value in SENTINEL_MEMBERS],
        CURRENT,
        BEHIND,
    ]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ERROR", ERROR),
        ("UNKNOWN", UNKNOWN),
        ("NOT_FOUND", NOT_FOUND),
        ("NOT_APPLICABLE", NOT_APPLICABLE),
    ],
)
def test_each_sentinel_carries_cores_own_value(name: str, expected: str) -> None:
    """The guarantee `surface_verdict` leans on, pinned per sentinel.

    `surface_verdict` returns the *observation's own state string* for a sentinel
    rather than mapping the four by hand, and that is only correct because
    `outcome_type` builds every per-status type from `SENTINEL_MEMBERS`. A
    sentinel that had drifted by one character would make the pass return a value
    the currency column does not offer, which Django would write into the
    database unchallenged (`choices` is not a `save()` rule).

    Parameterized per sentinel so a failure names which one drifted, rather than
    reporting the vocabulary as broken.
    """
    assert getattr(OutcomeState, name).value == expected
    assert expected in SENTINEL_VALUES


def test_the_determinate_verdicts_are_not_sentinels() -> None:
    """`current` and `behind` refine `ok`; neither is a sentinel and neither is `ok`.

    The anti-vacuity half of the case above: a `SENTINEL_VALUES` that had grown
    to hold everything would make `surface_verdict` return `ok` for a determinate
    observation and never compare anything, and every sentinel assertion above
    would still pass.
    """
    assert CURRENT not in SENTINEL_VALUES
    assert BEHIND not in SENTINEL_VALUES
    assert OutcomeState.OK.value not in {CURRENT, BEHIND}
    assert OutcomeState.OK.value not in {member.value for member in CurrencyOutcome}


def test_the_rollup_column_offers_exactly_this_vocabulary() -> None:
    """The contribution and the column it lands in must be drawn from one table.

    `core/rollup.py`'s `permitted_values` reads the *column's* declared choices
    and refuses a contribution outside them, so a rollup column declaring
    anything but `CurrencyOutcome` would refuse verdicts this pass is entitled to
    produce -- silently, for as long as the pass ran, because the refusal names
    the value rather than the mismatch.
    """
    assert permitted_values(ROLLUP_COLUMN) == {member.value for member in CurrencyOutcome}
    assert ROLLUP_COLUMN in contributable_columns()
    assert ROLLUP_COLUMN not in STAMP_COLUMNS


def test_the_rollup_column_defaults_to_unknown_rather_than_to_a_clean_value() -> None:
    """A rollup row nothing evaluated must not read as clean (`CPM-FR-5`).

    `core/rollup.py` writes the field's own default for a package no pass
    contributed, and puts that default through `CPM-AD-4`'s gate. A default of
    `current` would make every un-evaluated package -- an inventory whose first
    policy run has not happened, a run whose pass raised -- read as up to date.
    """
    field = PackageHealth._meta.get_field(ROLLUP_COLUMN)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert field.default == UNKNOWN
    assert field.editable is False


# ---------------------------------------------------------------------------
# The authority order: the column, its rule, and the documented default.
# ---------------------------------------------------------------------------


def test_the_documented_default_order_is_the_one_the_decision_states() -> None:
    """`CPM-AD-6`'s order, and the one entry of it this product cannot observe.

    The decision reads "verified upstream releases -> the verified primary
    release ecosystem (PyPI where it applies) -> feedstock recipe -> published
    conda package -> internal deployed version". The first four are the surfaces
    four collectors write; the fifth is observed by nothing in this product, so
    it is neither a `VersionSurface` member nor an entry here -- see that class
    for why a rank over evidence that does not exist would be worse than the gap.
    """
    assert DEFAULT_AUTHORITY_ORDER == EVERY_SURFACE
    assert set(DEFAULT_AUTHORITY_ORDER) == set(VersionSurface.values)


def test_an_empty_column_means_the_default_order_and_the_row_says_so() -> None:
    """AC 2: no authority explicitly set, so the documented default is applied.

    The empty list is what "no authority is explicitly set" is on a column that
    is never NULL, and it is what every package carries today. The second return
    value is what makes the row able to say the order was the default rather than
    a stored choice -- which a row carrying only the order could not, because a
    package that had explicitly chosen the default order would be
    indistinguishable from one that had chosen nothing.
    """
    order, is_default = applied_authority_order(Package(canonical_name="numpy", version_authority_order=[]))

    assert order == DEFAULT_AUTHORITY_ORDER
    assert is_default is True


def test_a_recorded_order_is_used_and_the_row_says_it_was_not_the_default() -> None:
    """AC 1: the order recorded on the package is the one applied.

    Reversed rather than merely different, so a function that ignored the column
    and returned the default could not pass: the two orders hold the same
    surfaces and disagree only on rank, which is the whole of what an authority
    order is.
    """
    recorded = list(reversed(DEFAULT_AUTHORITY_ORDER))

    order, is_default = applied_authority_order(Package(canonical_name="numpy", version_authority_order=recorded))

    assert order == tuple(recorded)
    assert order != DEFAULT_AUTHORITY_ORDER
    assert is_default is False


def test_a_recorded_order_may_name_fewer_surfaces_than_the_default() -> None:
    """A subset is a legitimate preference, and the consequence is stated where it lands.

    "Judge this package against its feedstock and nothing else" is a real thing
    an operator may want, and refusing it would make the column able to express
    only a permutation. What a surface left out costs is that it is still read
    and still recorded but can never be the authority -- which
    `test_a_surface_outside_the_order_is_never_the_authority` is about.
    """
    recorded = [VersionSurface.FEEDSTOCK.value]

    order, is_default = applied_authority_order(Package(canonical_name="numpy", version_authority_order=recorded))

    assert order == (VersionSurface.FEEDSTOCK.value,)
    assert is_default is False


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        ("source", "must be a list"),
        ({"first": "source"}, "must be a list"),
        ([1], "not surfaces"),
        ([None], "not surfaces"),
        (["deployed"], "observes no evidence"),
        (["pypy"], "observes no evidence"),
        (["source", "source"], "more than once"),
    ],
    ids=["a-bare-string", "a-mapping", "an-integer-entry", "a-null-entry", "an-invented-surface", "a-typo", "a-repeat"],
)
def test_an_unusable_authority_order_is_refused_and_the_message_says_why(order: object, expected: str) -> None:
    """The four faults, each one a different way an order stops being an order.

    A bare string is the one worth naming: `JSONField` stores it happily and
    Python iterates it one character at a time, so `"source"` would read as six
    surfaces, none of them real -- and every one of them would then be reported
    as an invented surface, which is a message about the wrong mistake.
    """
    fault = authority_order_fault(order)

    assert fault is not None
    assert expected in fault


@pytest.mark.parametrize(
    "order",
    [[], list(DEFAULT_AUTHORITY_ORDER), [VersionSurface.PYPI.value], list(reversed(DEFAULT_AUTHORITY_ORDER))],
    ids=["empty", "the-default", "a-subset", "reversed"],
)
def test_a_usable_authority_order_reports_no_fault(order: list[str]) -> None:
    """The other side, so the rule is not simply a function that always refuses.

    The empty list carries the most weight: it is the value every package holds
    today, and a rule that called it a fault would make the whole inventory
    unevaluable.
    """
    assert authority_order_fault(order) is None


def test_the_field_validator_refuses_the_same_orders_the_rule_does() -> None:
    """One rule, two call sites, and the message carried through verbatim.

    The validator is what a `ModelForm`, the admin and any caller of
    `full_clean()` meet; `policies/currency.py`'s read is what a policy run
    meets. Neither is the whole rule, and a second spelling of the check in
    either would be the drift `collectors/sweep.py`'s reconciliation rule was
    split out to prevent.

    **`Model.save()` does not run validators**, which is why the read-side
    refusal exists at all -- and why this case drives the validator directly
    rather than saving a row and expecting it to fail.
    """
    with pytest.raises(ValidationError) as refused:
        validate_authority_order(["deployed"])

    assert authority_order_fault(["deployed"]) in str(refused.value)
    assert validate_authority_order([]) is None


def test_the_field_declares_the_validator_so_a_form_reaches_it() -> None:
    """The declaration, because a validator nothing declares is a rule nothing runs.

    Asserted by identity against the function, not by counting: a field carrying
    *a* validator says nothing about which, and the rule this column needs is the
    one `policies/currency.py` also asks.
    """
    field = Package._meta.get_field("version_authority_order")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert validate_authority_order in field.validators
    assert field.null is False
    assert field.default is list


def test_a_package_whose_order_is_broken_is_refused_rather_than_defaulted() -> None:
    """Falling back to the default would make the row's record of the order a lie.

    `core/policy_run.py` contains this per package (`CPM-AD-23`): the package's
    derived rows roll back, every other package commits, and the run finalizes
    `partial`. Quietly applying the default instead would write a row saying the
    default was chosen for a package whose data says otherwise, and nothing
    downstream could tell that from an ordinary package.

    The message names the package, because a run over ten thousand packages that
    said only "an authority order is unusable" sends an operator through the
    inventory by hand.
    """
    package = Package(pk=7, canonical_name="numpy", version_authority_order=["deployed"])

    with pytest.raises(AuthorityOrderError) as refused:
        applied_authority_order(package)

    assert "numpy" in str(refused.value)
    assert "deployed" in str(refused.value)


# ---------------------------------------------------------------------------
# The comparison.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        ("2.4.0", "2.4.0"),
        ("  2.4.0  ", "2.4.0"),
        ("v2.4.0", "2.4.0"),
        ("V2.4.0", "2.4.0"),
        ("  v2.4.0 ", "2.4.0"),
        ("", ""),
        ("   ", ""),
        ("v", ""),
        ("V", ""),
        ("  v  ", ""),
        ("version-2.4.0", "version-2.4.0"),
        ("vim", "vim"),
        ("2.4.0v", "2.4.0v"),
        ("1.0", "1.0"),
    ],
    ids=[
        "plain",
        "padded",
        "a-lowercase-tag",
        "an-uppercase-tag",
        "a-padded-tag",
        "nothing",
        "whitespace-only",
        "a-bare-prefix",
        "a-bare-uppercase-prefix",
        "a-padded-bare-prefix",
        "a-word-beginning-with-v",
        "a-name-beginning-with-v",
        "a-trailing-v",
        "an-unpadded-release",
    ],
)
def test_the_only_normalisation_is_whitespace_and_a_leading_tag_prefix(stated: str, expected: str) -> None:
    """The whole of what this pass reconciles, and the shapes it must not touch.

    The negatives carry as much weight as the positives. `vim` and
    `version-2.4.0` are the reason the prefix is stripped only when a *digit*
    follows it -- a rule that stripped any leading `v` would turn a package named
    for its own version scheme into a different string. A bare `v` names *no
    version at all*: letting it survive would let it be chosen as the authority
    and would make two surfaces that both state nothing read as agreeing, which
    is the one way this normalisation could manufacture a `current` verdict out
    of two absences.

    Nothing else is reconciled. `policies/currency.py`'s module docstring is the
    one statement of that limit and of why inventing an ordering rule is out of
    scope; this is the executable half of it, and the two cases below --
    `test_a_surface_ahead_of_the_authority_also_reads_behind` and the tagged
    comparison -- are the rest.
    """
    assert comparable_version(stated) == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (OutcomeState.ERROR.value, ERROR),
        (OutcomeState.UNKNOWN.value, UNKNOWN),
        (OutcomeState.NOT_FOUND.value, NOT_FOUND),
        (OutcomeState.NOT_APPLICABLE.value, NOT_APPLICABLE),
    ],
    ids=["errored", "unobserved-by-the-collector", "the-source-has-none", "not-this-packages-question"],
)
def test_each_sentinel_state_becomes_the_same_sentinel_verdict(state: str, expected: str) -> None:
    """`CPM-FR-6`: the five states stay un-collapsed, one for one.

    An `error` is not an absence and a `not_applicable` is not an absence, which
    is the distinction a boolean status cannot hold and the reason `CPM-AD-5`
    bans one. Each is asserted separately so a fold of any two would name which.
    """
    reading = a_reading(VersionSurface.SOURCE.value, state=state, version="")

    assert surface_verdict(reading, authority_version=AN_AUTHORITY_VERSION) == expected


def test_a_surface_nobody_observed_is_unknown_and_never_ok() -> None:
    """The matrix's "no surface observed": a package nobody looked at is not current.

    `unknown` rather than `not_found`, and the difference is the one `CPM-FR-6`
    exists to keep: `not_found` is the *source* answering that it has no version,
    which is an informative negative, and this is nobody having asked.
    """
    reading = a_reading(VersionSurface.SOURCE.value, observed=False)

    assert surface_verdict(reading, authority_version=AN_AUTHORITY_VERSION) == UNKNOWN


def test_a_determinate_observation_stating_no_version_is_unknown() -> None:
    """The feedstock case, which is a real row rather than a defensive branch.

    `FeedstockSnapshot` records a feedstock that exists whose recipe names its
    version in a way the collector does not read: `ok`, with a blank
    `recipe_version`. The feedstock's *existence* is what that row claims, so it
    cannot be read as an absence -- but there is no version to compare, so it
    cannot be `current` either.
    """
    reading = a_reading(VersionSurface.FEEDSTOCK.value, state=OutcomeState.OK, version="")

    assert surface_verdict(reading, authority_version=AN_AUTHORITY_VERSION) == UNKNOWN


def test_a_determinate_observation_with_no_authority_to_compare_against_is_unknown() -> None:
    """A version nothing can be measured against is a fact, not a verdict.

    Reachable when the applied order names a subset that no observed surface is
    in: the surface stated a version, and there is nothing this pass is entitled
    to say about whether it is current.
    """
    reading = a_reading(VersionSurface.PYPI.value, version=AN_AUTHORITY_VERSION)

    assert surface_verdict(reading, authority_version="") == UNKNOWN


def test_a_surface_stating_the_authoritys_version_is_current() -> None:
    """The plainest comparison, and the anti-vacuity guard for the rest.

    Every case below is only meaningful while equality itself works: a comparison
    that answered `behind` for everything would satisfy each of them.
    """
    reading = a_reading(VersionSurface.FEEDSTOCK.value, version=AN_AUTHORITY_VERSION)

    assert surface_verdict(reading, authority_version=AN_AUTHORITY_VERSION) == CURRENT


def test_a_surface_stating_a_different_version_is_behind() -> None:
    """AC 3's second half, at the level of one surface."""
    reading = a_reading(VersionSurface.FEEDSTOCK.value, version=A_DIFFERENT_VERSION)

    assert surface_verdict(reading, authority_version=AN_AUTHORITY_VERSION) == BEHIND


def test_a_surface_ahead_of_the_authority_also_reads_behind() -> None:
    """The property that separates an equality rule from a smuggled-in ordering.

    Every other `behind` case in this change compares a *lower* version against
    the authority, so all of them would pass just as well against an
    implementation that had quietly started comparing order. This one cannot: the
    surface states a version that any ordering rule would call newer, and the
    verdict is still `behind`, because `behind` here means *different* and this
    pass has no notion of newer.

    It is also the case that would have to change first if an ordering rule ever
    arrives, which is why it is asserted rather than left implied by the module
    docstring's promise that there is no `ahead` member.
    """
    ahead = a_reading(VersionSurface.CONDA_PACKAGE.value, version=A_LATER_VERSION)

    assert A_LATER_VERSION > AN_AUTHORITY_VERSION, "the fixture versions must order, or this case proves nothing"
    assert surface_verdict(ahead, authority_version=AN_AUTHORITY_VERSION) == BEHIND


def test_a_tagged_spelling_of_the_authoritys_version_is_current_not_behind() -> None:
    """The false staleness `comparable_version` exists to prevent, at inventory scale.

    The reason the reconciliation exists at all is in `policies/currency.py`'s
    module docstring; what this asserts is that it reaches a verdict rather than
    only a helper.
    """
    reading = a_reading(VersionSurface.FEEDSTOCK.value, version=AN_AUTHORITY_VERSION)

    assert surface_verdict(reading, authority_version=comparable_version(THE_SAME_VERSION_TAGGED)) == CURRENT


def test_a_state_outside_the_vocabulary_is_refused_rather_than_read_as_an_absence() -> None:
    """An unrecognised value must not become a clean-looking answer.

    `state` declares `choices`, which Django enforces on a form and never on
    `save()`, so a row carrying anything at all is reachable -- through raw SQL,
    through a data migration, through a collector written after somebody widened
    the vocabulary in one place. Reading it as `unknown` would be the fold
    `CPM-FR-6` forbids arrived at by silence; refusing costs one package's row
    and leaves the rest of the run committed (`CPM-AD-23`).
    """
    reading = a_reading(VersionSurface.SOURCE.value, state=A_STATE_FROM_NOWHERE, version=AN_AUTHORITY_VERSION)

    with pytest.raises(CurrencyPolicyError) as refused:
        surface_verdict(reading, authority_version=AN_AUTHORITY_VERSION)

    assert A_STATE_FROM_NOWHERE in str(refused.value)


# ---------------------------------------------------------------------------
# The authority choice.
# ---------------------------------------------------------------------------


def test_the_first_surface_in_the_order_that_stated_a_version_is_the_authority() -> None:
    """AC 1: the order recorded on the package decides which surface is authoritative."""
    every = readings(
        source=a_reading(VersionSurface.SOURCE.value, version=AN_AUTHORITY_VERSION),
        pypi=a_reading(VersionSurface.PYPI.value, version=A_DIFFERENT_VERSION),
    )

    assert authoritative_version(every, DEFAULT_AUTHORITY_ORDER) == (
        VersionSurface.SOURCE.value,
        AN_AUTHORITY_VERSION,
    )


def test_the_order_is_a_ranking_rather_than_a_single_choice() -> None:
    """The same readings under a different order pick a different authority.

    This is what makes `CPM-AD-6`'s per-package data mean anything: a function
    that ignored the order and picked, say, the first observed surface in
    declaration order would pass the case above and fail here.
    """
    every = readings(
        source=a_reading(VersionSurface.SOURCE.value, version=AN_AUTHORITY_VERSION),
        pypi=a_reading(VersionSurface.PYPI.value, version=A_DIFFERENT_VERSION),
    )
    pypi_first = (VersionSurface.PYPI.value, VersionSurface.SOURCE.value)

    assert authoritative_version(every, pypi_first) == (VersionSurface.PYPI.value, A_DIFFERENT_VERSION)


@pytest.mark.parametrize(
    "state",
    [OutcomeState.ERROR.value, OutcomeState.UNKNOWN.value, OutcomeState.NOT_FOUND.value],
    ids=["errored", "unobserved-by-the-collector", "the-source-has-none"],
)
def test_a_surface_that_stated_no_version_is_passed_over_for_the_next_in_the_order(state: str) -> None:
    """The matrix's "authority surface unobserved": the next authority is chosen.

    Never `ok` from an absent observation, which is the whole reason the order is
    a ranking: an authority chosen because it was first in the order and then
    compared against nothing would make every other surface read `unknown` for a
    package the run actually has evidence for.
    """
    every = readings(
        source=a_reading(VersionSurface.SOURCE.value, state=state, version=""),
        pypi=a_reading(VersionSurface.PYPI.value, version=AN_AUTHORITY_VERSION),
    )

    assert authoritative_version(every, DEFAULT_AUTHORITY_ORDER) == (
        VersionSurface.PYPI.value,
        AN_AUTHORITY_VERSION,
    )


def test_a_not_applicable_surface_is_never_the_chosen_authority() -> None:
    """`CPM-SM-C1`: a package is never judged against a registry it never published to.

    `CPM-FR-8` records a non-Python package as `not_applicable` to PyPI. A PyPI
    surface chosen as the authority for such a package would make every other
    surface read against nothing -- which is the shape of "called stale against a
    registry it never published to" this whole story is about.
    """
    every = readings(
        pypi=a_reading(VersionSurface.PYPI.value, state=OutcomeState.NOT_APPLICABLE, version=""),
        feedstock=a_reading(VersionSurface.FEEDSTOCK.value, version=AN_AUTHORITY_VERSION),
    )
    pypi_first = (VersionSurface.PYPI.value, VersionSurface.FEEDSTOCK.value)

    assert authoritative_version(every, pypi_first) == (
        VersionSurface.FEEDSTOCK.value,
        AN_AUTHORITY_VERSION,
    )


def test_a_surface_outside_the_order_is_never_the_authority() -> None:
    """The consequence of permitting a recorded order shorter than the full set.

    The source surface states a version and is not in the order, so no authority
    is chosen at all -- which is the state in which nothing can be `current` or
    `behind`. Stated as a case rather than left in a docstring, because it is the
    one shape of recorded order whose result surprises.
    """
    every = readings(source=a_reading(VersionSurface.SOURCE.value, version=AN_AUTHORITY_VERSION))
    feedstock_only = (VersionSurface.FEEDSTOCK.value,)

    assert authoritative_version(every, feedstock_only) == ("", "")


def test_no_authority_is_chosen_when_no_surface_stated_a_version() -> None:
    """The matrix's "no surface observed at all": an ordinary answer, not an error.

    A package nobody has observed yet has no authority, and inventing one would
    be the clean-looking result `CPM-NFR-3` forbids.
    """
    assert authoritative_version(readings(), DEFAULT_AUTHORITY_ORDER) == ("", "")


def test_the_authority_is_chosen_on_its_comparable_form() -> None:
    """The version handed on is the compared form, not the stored one.

    A source that tagged `v2.4.0` and a feedstock that pins `2.4.0` agree, and
    they only agree if the authority's version has been through
    `comparable_version` before anything is compared against it. Returning the raw
    string here would make the tag reconciliation apply to one side of the
    comparison and not the other.
    """
    every = readings(source=a_reading(VersionSurface.SOURCE.value, version=THE_SAME_VERSION_TAGGED))

    _, version = authoritative_version(every, DEFAULT_AUTHORITY_ORDER)

    assert version == AN_AUTHORITY_VERSION


# ---------------------------------------------------------------------------
# The overall verdict.
# ---------------------------------------------------------------------------


def test_every_surface_current_reads_current_overall() -> None:
    """The matrix's first row: the authority agrees with everything compared to it."""
    verdicts = dict.fromkeys(EVERY_SURFACE, CURRENT)

    assert overall_verdict(verdicts) == CURRENT


def test_one_surface_behind_makes_the_package_behind() -> None:
    """AC 3: source current and feedstock behind, expressible separately and together.

    The per-surface verdicts stay exactly as they were -- that is what "the two
    are expressible separately" means, and it is asserted here as well as in the
    integration module because the reduction is where a fold would happen.
    """
    verdicts = {
        VersionSurface.SOURCE.value: CURRENT,
        VersionSurface.PYPI.value: CURRENT,
        VersionSurface.FEEDSTOCK.value: BEHIND,
        VersionSurface.CONDA_PACKAGE.value: CURRENT,
    }

    assert overall_verdict(verdicts) == BEHIND
    assert verdicts[VersionSurface.SOURCE.value] == CURRENT


@pytest.mark.parametrize(
    "masking",
    [UNKNOWN, NOT_FOUND],
    ids=["unobserved", "the-source-has-none"],
)
def test_a_proven_discrepancy_is_never_masked_by_a_surface_nobody_read(masking: str) -> None:
    """`behind` outranks the two un-observed states, which is a rank this story chose.

    `core.outcomes.aggregate` cannot rank `behind` at all -- a per-status
    determinate verdict has no place in `PRECEDENCE`, and `core/outcomes.py`
    refuses to invent one -- so `CURRENCY_PRECEDENCE` places it, and places it
    above `unknown` and `not_found`. A package proven behind on one surface while
    another was merely unobserved would otherwise report `unknown`, and an
    operator would see nothing where the run had established something.

    `error` is deliberately not in this parametrize list: it outranks `behind`,
    and the case below is about that.
    """
    verdicts = dict.fromkeys(EVERY_SURFACE, masking)
    verdicts[VersionSurface.FEEDSTOCK.value] = BEHIND

    assert overall_verdict(verdicts) == BEHIND


def test_a_surface_that_could_not_be_read_outranks_a_discrepancy_that_was_found() -> None:
    """`error` above `behind`, which is the one rank an earlier draft had the wrong way up.

    A lookup that failed may be hiding a worse discrepancy than the one the run
    did find. Reporting the discrepancy as the package's whole answer would make
    the read failure vanish from the rollup column entirely -- an operator would
    see a `behind` they can act on and no sign that a surface went unread, which
    is `CPM-NFR-3`'s "degrades to a clean-looking result" in the one direction
    that looks like diligence.

    Both surfaces are determinate about *something*, which is what makes this a
    ranking question rather than a presence one.
    """
    verdicts = dict.fromkeys(EVERY_SURFACE, CURRENT)
    verdicts[VersionSurface.FEEDSTOCK.value] = BEHIND
    verdicts[VersionSurface.CONDA_PACKAGE.value] = ERROR

    assert overall_verdict(verdicts) == ERROR


def test_the_reduction_order_is_declared_as_data_rather_than_as_control_flow() -> None:
    """The ranking is enumerable, which is what `test_single_ordering_audit.py` needs.

    The first version of this reduction expressed the same ranking as a chain of
    `if` statements, specifically so that a module-scope tuple would not trip that
    audit -- an order hidden from the one check built to enumerate orders, which
    is worse than the duplication the ban exists to prevent. It is data now, and
    `RECORDED_ORDERINGS` licenses it by name.

    Asserted as the exact tuple, because "worst first" is the whole contract and a
    containment check would pass on a shuffled one. `not_applicable` is asserted
    *absent*: it is excluded from the reduction rather than ranked in it, and a
    version that ranked it is the defect the case below is about.
    """
    assert CURRENCY_PRECEDENCE == (ERROR, BEHIND, UNKNOWN, NOT_FOUND, CURRENT)
    assert NOT_APPLICABLE not in CURRENCY_PRECEDENCE


def test_no_surface_observed_reads_unknown_overall() -> None:
    """The matrix's "a package nobody observed is not current"."""
    assert overall_verdict(dict.fromkeys(EVERY_SURFACE, UNKNOWN)) == UNKNOWN


def test_an_errored_surface_stops_the_package_reading_current() -> None:
    """The matrix's "an error is not an absence", at the overall level."""
    verdicts = dict.fromkeys(EVERY_SURFACE, CURRENT)
    verdicts[VersionSurface.CONDA_PACKAGE.value] = ERROR

    assert overall_verdict(verdicts) == ERROR


def test_an_inapplicable_surface_does_not_take_the_packages_verdict_away() -> None:
    """The `not_applicable` fold this reduction was rewritten to stop making.

    `CPM-FR-8` records a non-Python package as `not_applicable` against PyPI, and
    the collector writes exactly that row for every one of them. An earlier
    version of this reduction sent that verdict through `core`'s order, where it
    outranks the determinate value -- so a package `current` on source, feedstock
    and conda reported `not_applicable` overall, discarding three determinate
    findings for a large population of the inventory.

    `CPM-FR-6` asks that the third state not be folded *at the surface*, and the
    surface column still carries it. Hoisting it into the package's verdict is a
    different fold and a worse one: it replaces answers with "the question does
    not apply" on the strength of one surface it did not apply to.
    """
    verdicts = dict.fromkeys(EVERY_SURFACE, CURRENT)
    verdicts[VersionSurface.PYPI.value] = NOT_APPLICABLE

    assert overall_verdict(verdicts) == CURRENT
    assert verdicts[VersionSurface.PYPI.value] == NOT_APPLICABLE


def test_an_inapplicable_surface_never_makes_the_package_behind() -> None:
    """The matrix's `not_applicable` row: the third state produces no staleness claim.

    Held separately from the case above because it is a different guarantee: that
    one says an inapplicable surface does not *take away* a verdict, and this says
    it does not *invent* one. A reduction that dropped `not_applicable` by
    rewriting it to `behind` would satisfy the first and fail this.
    """
    verdicts = dict.fromkeys(EVERY_SURFACE, NOT_APPLICABLE)
    verdicts[VersionSurface.SOURCE.value] = CURRENT

    assert overall_verdict(verdicts) != BEHIND
    assert overall_verdict(verdicts) == CURRENT


def test_every_surface_not_applicable_reads_not_applicable_overall() -> None:
    """A package none of the four surfaces is about is not `unknown` and not clean.

    The one case where excluding `not_applicable` from the reduction must *not*
    collapse to "nothing was judged": every surface was judged, and the answer is
    that none of them applies. A reduction that simply dropped the value would
    answer `unknown` here and would be claiming nobody had looked.
    """
    assert overall_verdict(dict.fromkeys(EVERY_SURFACE, NOT_APPLICABLE)) == NOT_APPLICABLE


def test_reducing_nothing_at_all_is_unknown_rather_than_clean() -> None:
    """`core.outcomes.EMPTY_AGGREGATE`, reached rather than restated.

    Unreachable from `CurrencyPass`, which always produces four verdicts -- and
    asserted anyway, because the alternative is a function whose behaviour on the
    empty case is whatever `min()` over an empty sequence happens to do. Held
    apart from the all-`not_applicable` case above, which is a different empty:
    that one judged four surfaces and this one judged none.
    """
    assert overall_verdict({}) == UNKNOWN
    assert overall_verdict({}) != NOT_APPLICABLE


def test_a_verdict_from_outside_the_vocabulary_is_refused_rather_than_ranked() -> None:
    """An unrankable value must not be treated as determinate.

    `core.outcomes.aggregate` refuses one for this reason and says so at length;
    the reduction here is a second reducer over a second vocabulary and must
    refuse on the same terms, or the first verdict a later epic adds without
    placing it silently ranks as whatever `dict.get` returned.
    """
    verdicts = dict.fromkeys(EVERY_SURFACE, CURRENT)
    verdicts[VersionSurface.SOURCE.value] = A_STATE_FROM_NOWHERE

    with pytest.raises(OutcomeVocabularyError, match=A_STATE_FROM_NOWHERE):
        overall_verdict(verdicts)


# ---------------------------------------------------------------------------
# The cut-off-bound read, and what it refuses without a database.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reader", SURFACE_READERS, ids=lambda reader: str(reader.surface))
def test_a_naive_cutoff_is_refused_before_any_query_runs(reader: SurfaceReader) -> None:
    """`CPM-FR-22`'s replay depends on the cut-off meaning one instant.

    `USE_TZ` is on, so Django would read a naive value as if it were UTC and the
    read would be silently shifted by whichever offset the reader happened to be
    in -- selecting a different evidence set on every replay. The refusal is made
    before the query, which is what lets this case run with no database at all.

    Parameterized over every reader because the message names the surface, and a
    refusal that named the wrong one sends an operator to the wrong table.

    **The other side of the guard is not here, and deliberately.** An aware
    cut-off opens a query, so a case asserting "this one is not refused" in the
    unit tier could only assert it by catching pytest-django's database block --
    which passes for a reason that has nothing to do with the guard. Every case
    in `tests/integration/django_apps/test_currency_policy.py` reads through this
    function with an aware cut-off, which is where "it does not simply refuse
    everything" is actually shown.
    """
    with pytest.raises(CurrencyPolicyError) as refused:
        observed_surface(reader, package_id=1, cutoff=A_NAIVE_INSTANT)

    assert reader.surface in str(refused.value)


# ---------------------------------------------------------------------------
# What the pass and its table declare.
# ---------------------------------------------------------------------------


def test_the_pass_declares_its_name_its_table_and_its_one_column() -> None:
    """The three declarations `core/policy.py` reads, and nothing else.

    `contributes` is asserted as the exact tuple rather than by containment: a
    pass claiming a second column would own a column another epic's pass is
    coming for, and the registry's refusal would then land on *that* pass rather
    than on this one.
    """
    assert issubclass(CurrencyPass, PolicyPass)
    assert CurrencyPass.name == POLICY_NAME
    assert CurrencyPass.derived_model is PackageCurrency
    assert CurrencyPass.contributes == (ROLLUP_COLUMN,)


def test_the_derived_table_is_keyed_by_the_package_and_the_run() -> None:
    """`CPM-AD-21`'s key, as a database rule rather than as the writer's promise.

    Read off `Meta.constraints` rather than off a `unique_together`: a pass that
    ran twice for one package, or two passes writing one table, would make
    `(package, policy_run)` ambiguous, and a reader joining this to the rollup
    would get whichever row the database returned first.
    """
    declared = {constraint.name for constraint in PackageCurrency._meta.constraints}  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert ONE_ROW_PER_PACKAGE_PER_RUN in declared
    assert AUTHORITY_IS_A_KNOWN_SURFACE in declared
    assert DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY in declared


def test_the_derived_table_carries_one_verdict_column_per_surface() -> None:
    """`CPM-FR-16`: currency is computed per surface, and stored per surface.

    `SURFACE_STATUS_FIELDS` is the one place the four columns are tied to the four
    surfaces, and this reconciles it in both directions: every surface has a
    column, and every column named is a real field on the table. A surface with no
    column would be a verdict with nowhere to go, and a column named for a surface
    that does not exist would be a column nothing writes.
    """
    fields = {field.name for field in PackageCurrency._meta.concrete_fields}  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert set(SURFACE_STATUS_FIELDS) == set(VersionSurface.values)
    assert set(SURFACE_STATUS_FIELDS.values()) <= fields
    assert len(set(SURFACE_STATUS_FIELDS.values())) == len(EVERY_SURFACE)


@pytest.mark.parametrize(
    "column",
    [*SURFACE_STATUS_FIELDS.values(), "overall_status"],
    ids=str,
)
def test_every_verdict_column_offers_the_whole_vocabulary_and_is_not_editable(column: str) -> None:
    """`CPM-AD-5` and `CPM-FR-37`, per column.

    Not nullable and not blank: NULL and the empty string would each be a
    non-answer with no name and no value, which is the second vocabulary
    `CPM-FR-6` exists to prevent. Not editable: a derived verdict is a policy
    run's to write and nobody else's, and `editable=False` is the half of that
    which holds against a human with a browser and a permission.
    """
    field = PackageCurrency._meta.get_field(column)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert {value for value, _ in field.choices or ()} == {member.value for member in CurrencyOutcome}
    assert field.null is False
    assert field.blank is False
    assert field.editable is False


def test_the_derived_table_references_the_evidence_each_verdict_rests_on() -> None:
    """AC 1: "the chosen authority *and its supporting evidence*" are stored with the result.

    One nullable reference per surface, on `PROTECT`. NULL is the absence of an
    observation rather than a second spelling of a state -- the verdict column
    beside it always holds a value -- and `PROTECT` is what stops a snapshot being
    deleted out from under a row that cites it, which would leave the row claiming
    an authority nothing can be shown for.

    `SURFACE_READERS` is what the pass writes through, so it is what this reads:
    a reference column renamed without its reader would silently store `None`
    forever.
    """
    for reader in SURFACE_READERS:
        field = PackageCurrency._meta.get_field(reader.reference_field)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

        assert field.null is True
        assert field.remote_field.model is reader.model  # type: ignore[union-attr]
        assert field.remote_field.on_delete.__name__ == "PROTECT"  # type: ignore[union-attr]


def test_the_surface_readers_cover_every_surface_exactly_once() -> None:
    """The roster the pass loops over, reconciled against the closed vocabulary.

    A surface with no reader is a verdict the pass would fail to produce with a
    `KeyError`; a reader for a surface outside the vocabulary would write a row
    the `chosen_authority` constraint refuses. Both are caught here rather than
    at the first policy run.
    """
    covered = [reader.surface for reader in SURFACE_READERS]

    assert sorted(covered) == sorted(VersionSurface.values)
    assert len(covered) == len(set(covered))


@pytest.mark.parametrize("reader", SURFACE_READERS, ids=lambda reader: str(reader.surface))
def test_each_reader_names_a_real_column_on_a_real_evidence_table(reader: SurfaceReader) -> None:
    """The three things a reader declares, checked against the tables it reads.

    A misspelled `version_field` would make the read return whatever `getattr`
    found -- an `AttributeError` for every package, or worse, the wrong column if
    the name happened to exist. This is what makes the roster's correctness a
    property of the declaration rather than of the first run.

    The four tables are named as a set as well, so a reader repointed at a model
    that merely *has* the right column names -- the rollup, say -- fails here.
    """
    fields = {field.name for field in reader.model._meta.concrete_fields}  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert reader.version_field in fields
    assert "state" in fields
    assert "observed_at" in fields
    assert reader.model in {SourceReleaseSnapshot, PyPIReleaseSnapshot, FeedstockSnapshot, CondaPackageSnapshot}


def test_no_two_readers_share_a_reference_or_a_version_field() -> None:
    """Two surfaces pointing at one column is a reference that is permanently NULL.

    `SurfaceReader` is four records that differ only in their three fields, so a
    copy-pasted entry with one field left unedited is the plausible mistake --
    and its consequence is quiet: the pass writes one surface's observation into
    the other's reference column, the second write wins, and one surface's
    evidence reference is `None` on every row for ever while both verdicts still
    look computed.

    The version fields are asserted *not* distinct, because two of them genuinely
    are `latest_version` -- the source and PyPI tables each named the column after
    what their own source calls it. What must be distinct is the pairing of table
    and column, which is what this checks.
    """
    references = [reader.reference_field for reader in SURFACE_READERS]
    pairs = [(reader.model, reader.version_field) for reader in SURFACE_READERS]

    assert len(references) == len(set(references)), f"two readers share a reference column: {references}"
    assert len(pairs) == len(set(pairs)), f"two readers read the same column of the same table: {pairs}"


def test_the_conda_reader_is_the_only_one_that_declares_a_tie_break() -> None:
    """The tie-break exists for the one table that holds several rows per sweep.

    `conda_package_snapshots` holds one row per `(channel, platform)` and one
    sweep stamps every row it writes with that run's single instant, so *every*
    row ties on `observed_at` and something has to decide which pair the package's
    conda verdict is about. Left to the primary key alone it is whichever row was
    inserted last, which changes when the collector's channel list is reordered.

    The other three tables hold at most one observation per package per sweep, so
    a tie-break there would be ranking rows that cannot tie -- machinery arguing
    for a case that does not exist.
    """
    by_surface = {reader.surface: reader.tie_break for reader in SURFACE_READERS}

    assert by_surface[VersionSurface.CONDA_PACKAGE.value] == ("channel", "platform")
    assert set(by_surface.values()) - {()} == {("channel", "platform")}
    for surface in (VersionSurface.SOURCE.value, VersionSurface.PYPI.value, VersionSurface.FEEDSTOCK.value):
        assert by_surface[surface] == (), surface


def test_the_pass_writes_exactly_the_columns_the_surface_map_names() -> None:
    """The reconciliation `SURFACE_STATUS_FIELDS` needs, because the writer does not read it.

    The map is what `DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY` is built from, and
    `policies/currency.py` deliberately spells its four keywords literally so
    `tests/unit/django_apps/test_derived_status_writability_audit.py` can see the
    write. Two declarations of one fact need a check between them, and this is it:
    the table's per-surface verdict columns are exactly the map's values, so a
    column added to the model without an entry, or an entry naming a column the
    model no longer has, fails here.

    Read off the model rather than off the pass's source, because what must agree
    is the *schema* and the map -- a keyword the pass stopped passing would fail
    at `create()` on the first package, loudly, which is a different failure with
    its own signal.
    """
    verdict_columns = {
        field.name
        for field in PackageCurrency._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if field.name.endswith("_status") and field.name != "overall_status"
    }

    assert verdict_columns == set(SURFACE_STATUS_FIELDS.values())


def test_the_derived_tables_authority_columns_are_not_editable_either() -> None:
    """A form that could rewrite the authority would leave the row contradicting itself.

    The writability audit reaches only fields *named* for a status, so nothing
    would have failed on these three -- and "which surface was authoritative",
    "which order was applied" and "where that order came from" are what make the
    four verdicts beside them checkable. A row whose authority had been edited and
    whose verdicts had not is a row that cannot be audited or replayed.
    """
    for column in ("chosen_authority", "authority_order", "authority_order_source", "detail"):
        field = PackageCurrency._meta.get_field(column)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

        assert field.editable is False, column


def test_the_detail_records_both_spellings_of_a_discrepancy() -> None:
    """`behind` means *different*, so the row has to say different how.

    The most common false `behind` is two surfaces spelling one version
    differently, and telling that apart from a real discrepancy without this
    column means a human re-deriving the comparison from four joined evidence
    rows -- the work the row exists to remove. So the line carries each side's
    *stored* string and the form it was *compared* as: where those differ, the
    reader can see the normalisation at work, and where the compared forms differ
    the discrepancy is real.
    """
    every = readings(
        source=a_reading(VersionSurface.SOURCE.value, version=THE_SAME_VERSION_TAGGED),
        feedstock=a_reading(VersionSurface.FEEDSTOCK.value, version=A_DIFFERENT_VERSION),
    )
    verdicts = {
        surface: surface_verdict(reading, authority_version=AN_AUTHORITY_VERSION) for surface, reading in every.items()
    }

    detail = discrepancy_detail(every, verdicts, authority=VersionSurface.SOURCE.value)

    assert verdicts[VersionSurface.FEEDSTOCK.value] == BEHIND
    assert VersionSurface.FEEDSTOCK.value in detail
    assert A_DIFFERENT_VERSION in detail
    assert THE_SAME_VERSION_TAGGED in detail, "the authority's stored spelling is what a false behind is read from"
    assert AN_AUTHORITY_VERSION in detail, "the compared form is what the verdict was actually reached on"


def test_the_detail_is_empty_when_nothing_is_behind() -> None:
    """An explanation of an unremarkable row is noise, and every evidence table agrees.

    The negative control for the case above: a `detail` that was populated on
    every row would satisfy every assertion there and would say nothing.
    """
    every = readings(source=a_reading(VersionSurface.SOURCE.value, version=AN_AUTHORITY_VERSION))
    verdicts = {
        surface: surface_verdict(reading, authority_version=AN_AUTHORITY_VERSION) for surface, reading in every.items()
    }

    assert BEHIND not in verdicts.values()
    assert discrepancy_detail(every, verdicts, authority=VersionSurface.SOURCE.value) == ""
    assert discrepancy_detail(every, verdicts, authority="") == ""


def test_the_authority_order_source_vocabulary_is_closed_and_two_valued() -> None:
    """AC 2's "the row records that it was the default", as a vocabulary rather than a flag.

    A boolean would answer the question and nothing else; a closed vocabulary
    leaves room for the third source a later story will have -- an operator
    override, a resolver's inference -- without a second column beside it.
    """
    assert set(AuthorityOrderSource.values) == {"package", "default"}
    field = PackageCurrency._meta.get_field("authority_order_source")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    assert {value for value, _ in field.choices or ()} == set(AuthorityOrderSource.values)


def test_the_derived_table_row_renders_before_it_is_saved() -> None:
    """A `__str__` that raised would break the two places a half-built row is rendered.

    An unsaved instance has no related object, so reading `self.package` raises
    `RelatedObjectDoesNotExist` -- in a debugger and in a traceback, which are
    exactly where a `__str__` is called on a half-built object. Read off
    `package_id` instead, on the same terms as `PackageHealth.__str__`.
    """
    assert "no package" in str(PackageCurrency())
    assert "no authority" in str(PackageCurrency())
    assert "package 7" in str(PackageCurrency(package_id=7, overall_status=BEHIND))
    assert BEHIND in str(PackageCurrency(package_id=7, overall_status=BEHIND))
