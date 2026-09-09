"""The facet roster: what the health view can be narrowed by, and what it refuses.

`CPM-APP-S02`'s AC 3 names four things -- "any derived status, confidence, priority
bucket and work type" -- and the roster is where "any" is either true or quietly
false. A vocabulary that grew a value and a facet that did not is not a crash: it is
a checkbox that is simply absent, on a screen whose other counts still add up.

So the sweep here is over the *shape* of the roster rather than over what a query
returns, which is
`tests/integration/django_apps/test_package_health_view.py`'s job. Three things are
checked and each has been wrong in some codebase: that every facet reads its
vocabulary off the type the column declares rather than restating it, that every
facet knows exactly one place to look, and that a value outside a vocabulary is
refused rather than absorbed.

**The refusal is the case worth writing.** Silently dropping `?vuln=criticl` returns
the whole inventory under a URL that claims to be filtered, and a reader cannot tell
that from a genuinely empty result -- so a stale bookmark becomes a false all-clear.
`CPM-AD-24`'s vocabularies are closed, which is what makes refusing safe.

Builds `Q` objects and reads declarations: no database, no queries executed.
"""

from __future__ import annotations

from typing import Final

import pytest
from django.db.models import Q

from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.policies.models import PackageVulnerability
from conda_sentinel.policies.outcomes import PriorityBucket
from conda_sentinel.policies.outcomes import WorkType
from conda_sentinel.surface.filters import FACETS
from conda_sentinel.surface.filters import FACETS_BY_PARAM
from conda_sentinel.surface.filters import UnknownFacetValueError
from conda_sentinel.surface.filters import applied_filters
from conda_sentinel.surface.filters import filter_condition
from conda_sentinel.surface.health import COLUMNS

#: The four things AC 3 names, by the facet parameter that offers each. Written out
#: here on purpose -- this is the acceptance criterion restated as data, so a facet
#: removed in a refactor fails against the requirement rather than against itself.
REQUIRED_FACETS: Final[dict[str, str]] = {
    "vuln": "a derived status",
    "confidence": "identity confidence",
    "priority": "the priority bucket",
    "work": "the work type",
}

#: A value no vocabulary holds, spelled as the typo a reader would actually make.
A_TYPO: Final[str] = "criticl"

#: What a `(value, label)` pair holds, and how many facets two ticks come from.
CHOICE_WIDTH: Final[int] = 2
TWO_FACETS: Final[int] = 2


def test_the_roster_offers_everything_the_criterion_names() -> None:
    """AC 3, checked against the requirement rather than against the roster's own length."""
    missing = {param: what for param, what in REQUIRED_FACETS.items() if param not in FACETS_BY_PARAM}

    assert missing == {}, f"the health view offers no facet for: {missing}"


def test_every_status_the_table_shows_is_filterable() -> None:
    """ "Any derived status" means every one the table shows, not a selection of them.

    Each `Column` names its facet, so this walks a declaration rather than guessing
    at a correspondence between two naming schemes -- which genuinely differ, since
    the column is `python_readiness` and the facet a reader types is `py314`.
    """
    unfilterable = [column.key for column in COLUMNS if column.facet not in FACETS_BY_PARAM]

    assert unfilterable == [], f"these columns are shown but cannot be filtered: {unfilterable}"


def test_every_column_narrows_by_a_facet_over_the_same_vocabulary() -> None:
    """The half that a name check cannot reach: the facet has to filter *that* status.

    A column pointed at a facet over a different vocabulary would pass the case
    above and would offer a reader checkboxes that narrow by something else --
    which looks, on the screen, like a filter that does nothing.
    """
    mismatched = {
        column.key: column.origin
        for column in COLUMNS
        if FACETS_BY_PARAM[column.facet].column not in column.origin
        and (
            FACETS_BY_PARAM[column.facet].derived is None
            or FACETS_BY_PARAM[column.facet].derived[1] not in column.origin  # type: ignore[index]
        )
    }

    assert mismatched == {}, f"these columns name a facet that filters a different status: {mismatched}"


@pytest.mark.parametrize("facet", FACETS, ids=lambda facet: facet.param)
def test_every_facet_knows_exactly_one_place_to_look(facet: object) -> None:
    """A rollup column or a derived table, never both and never neither.

    Neither would be a facet that filters nothing while still rendering its
    checkboxes; both would be two conditions for one tick, and which of them won
    would depend on the order of two branches.

    Args:
        facet: The facet under test.

    """
    assert bool(facet.column) != (facet.derived is not None), facet.param  # type: ignore[attr-defined]


@pytest.mark.parametrize("facet", FACETS, ids=lambda facet: facet.param)
def test_every_facet_carries_a_closed_vocabulary(facet: object) -> None:
    """The choices come from the type the column declares, so they cannot go stale.

    Asserted as non-empty and as pairs, because the failure of a restated vocabulary
    is not an exception -- it is a shorter list of checkboxes than there are values.

    Args:
        facet: The facet under test.

    """
    assert facet.choices != (), facet.param  # type: ignore[attr-defined]
    assert all(len(entry) == CHOICE_WIDTH for entry in facet.choices), facet.param  # type: ignore[attr-defined]
    assert facet.values() == frozenset(value for value, _label in facet.choices)  # type: ignore[attr-defined]


def test_the_priority_facet_offers_every_bucket_and_the_sentinels() -> None:
    """One roster spelled out, so "reads it off the type" is a fact rather than a claim.

    `PriorityBucket` is composed by `outcome_type` from `core`'s four sentinels plus
    ten buckets, and a facet offering only the ten would hide every package the
    priority pass reached no conclusion about -- which is the set a reader most needs
    to find.
    """
    assert FACETS_BY_PARAM["priority"].values() == frozenset(PriorityBucket.values)
    assert FACETS_BY_PARAM["work"].values() == frozenset(WorkType.values)
    assert FACETS_BY_PARAM["confidence"].values() == frozenset(IdentityConfidence.values)


def test_a_value_outside_the_vocabulary_is_refused() -> None:
    """The stale bookmark, answered rather than absorbed.

    And the message names the vocabulary, because the person reading it has just
    mistyped one of its values.
    """
    with pytest.raises(UnknownFacetValueError, match=A_TYPO) as refusal:
        FACETS_BY_PARAM["vuln"].condition([A_TYPO])

    assert "vuln" in str(refusal.value)


def test_a_refusal_names_the_facet_rather_than_the_column() -> None:
    """What a reader can act on: the parameter is in their URL, the column is not."""
    with pytest.raises(UnknownFacetValueError, match=r"priority="):
        FACETS_BY_PARAM["priority"].condition(["p11"])


def test_one_bad_value_refuses_the_whole_request() -> None:
    """A partly applied filter is the worst of the three possible answers.

    Applying the good values and dropping the bad one returns a result that is
    narrower than the URL says and wider than the reader asked for, and nothing on
    the screen distinguishes it from a correct one.
    """
    with pytest.raises(UnknownFacetValueError):
        filter_condition({"priority": ["p1", "p11"]})


def test_an_empty_selection_is_not_a_filter() -> None:
    """ "Nothing ticked" and "no parameter at all" are the same request.

    An empty `Q` is what `filter()` treats as no condition; returning something
    narrower would make an unticked facet quietly exclude every row.
    """
    assert FACETS_BY_PARAM["priority"].condition([]) == Q()
    assert filter_condition({}) == Q()


def test_a_rollup_facet_builds_a_plain_column_condition() -> None:
    """The direct half: four statuses are columns of `package_health`.

    Asserted as the condition rather than by running it, because what is under test
    is that no subquery is involved -- a facet that reached for `Exists` on a column
    it already has would work and would cost a correlated read per row.
    """
    condition = FACETS_BY_PARAM["priority"].condition(["p1", "p2"])

    assert condition == Q(priority_status__in=["p1", "p2"])


def test_a_derived_facet_builds_a_correlated_existence_condition() -> None:
    """The harder half, and the shape matters rather than the result.

    A join to a table with one row per package *per run* would match a row from a
    different run and would multiply rows, so the paginator would report a count
    that is not the number of packages. `Exists` correlated on both ids does
    neither.
    """
    condition = FACETS_BY_PARAM["vuln"].condition(["no_advisory_matched"])
    (existence,) = condition.children
    correlated = {
        child.lhs.target.name
        for child in existence.query.where.children  # type: ignore[union-attr]
        if hasattr(child, "lhs") and hasattr(child.lhs, "target")
    }

    assert existence.query.model is PackageVulnerability  # type: ignore[union-attr]
    assert {"package", "policy_run"} <= correlated, correlated


def test_facets_combine_with_and() -> None:
    """Which is what makes the counts beside each checkbox mean anything.

    A second value inside one facet widens the result; a second facet narrows it.
    Reversing either would make every count on the sidebar wrong in a way nobody
    could see.
    """
    condition = filter_condition({"priority": ["p1"], "confidence": [IdentityConfidence.VERIFIED.value]})

    assert condition.connector == Q.AND
    assert len(condition.children) == TWO_FACETS


def test_a_parameter_that_is_not_a_facet_is_ignored() -> None:
    """`page`, `sort`, and whatever an analytics tool appends.

    Refusing these would make a shared link fail for the person it was sent to,
    which is a different failure from a mistyped facet value and deserves a
    different answer.
    """
    assert applied_filters({"page": ["2"], "sort": ["rank"], "utm_source": ["an-email"]}) == {}


def test_an_empty_value_is_read_as_no_selection() -> None:
    """`?priority=` is what an unticked HTML form sends, and it means nothing is ticked."""
    assert applied_filters({"priority": [""]}) == {}
    assert applied_filters({"priority": ["", "p1"]}) == {"priority": ["p1"]}


def test_the_roster_has_no_duplicate_parameters() -> None:
    """Two facets on one parameter would mean one of them silently never applies.

    `FACETS_BY_PARAM` is a dict built from the tuple, so the second would win and
    the first would render its checkboxes and do nothing.
    """
    assert len(FACETS_BY_PARAM) == len(FACETS)
