"""Finding a package by name: what the fragment means before it reaches a database.

`CPM-APP-S17`. `surface/search.py` is two small functions and the whole reason it is a
module is a *rule* -- that a name is not a closed vocabulary and must not be refused
the way a facet value is. So the cases here are about the rule and the
normalisations, and `tests/integration/django_apps/test_package_health_view.py` is
where a query is actually run.

**The case that matters most is the one asserting a refusal does not happen.** A
fragment nobody recognises has to come back as an empty result, and the module beside
this one insists that a *facet* value nobody recognises comes back as a 400. The two
are opposite and both are correct, and the failure this file exists to prevent is
somebody reconciling them.

Builds `Q` objects and normalises strings: no database, no queries executed.
"""

from __future__ import annotations

import pytest
from django.db.models import Q

from conda_sentinel.surface.filters import UnknownFacetValueError
from conda_sentinel.surface.filters import applied_filters
from conda_sentinel.surface.filters import filter_condition
from conda_sentinel.surface.search import MAX_TERM_LENGTH
from conda_sentinel.surface.search import SEARCH_PARAM
from conda_sentinel.surface.search import name_condition
from conda_sentinel.surface.search import search_term


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("django", "django"),
        # Whitespace from a paste, which would otherwise match nothing and read as a
        # broken search rather than as a stray space.
        ("  django  ", "django"),
        ("\tgit\n", "git"),
        # The import name a reader has in their head, spelled the way conda-forge
        # spells the package.
        ("scikit_learn", "scikit-learn"),
        ("umap_learn", "umap-learn"),
        # Case is left alone: `icontains` is what makes it not matter, and folding
        # here would put a second, invisible rule in the way of reading the query.
        ("DJANGO", "DJANGO"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_a_fragment_is_normalised_the_way_a_name_is_spelled(raw: str, expected: str) -> None:
    """Two normalisations, both one-sided, and the asymmetry is the point.

    Args:
        raw: The parameter as it would arrive.
        expected: What should be matched.

    """
    assert search_term(raw) == expected


def test_a_fragment_longer_than_any_name_asks_for_nothing() -> None:
    """A bound on what gets rendered back and what a database is asked to scan for.

    Not a security bound -- the ORM parameterises the value. It is that a fragment
    longer than the longest canonical name cannot match anything, so scanning for it
    and then echoing it into the input and the summary is work done to display a
    result that was empty before it started.
    """
    assert search_term("x" * (MAX_TERM_LENGTH + 1)) == ""
    assert search_term("x" * MAX_TERM_LENGTH) != ""


def test_no_search_narrows_nothing() -> None:
    """So a caller can combine the condition unconditionally rather than branching.

    An empty `Q` ANDs into any other condition without changing it, which is what
    lets `health_queryset` apply the search on one line with no `if` around it -- and
    a branch there is where a "search with no facets" path drifts from a "facets with
    no search" one.
    """
    assert name_condition("", field="package__canonical_name") == Q()


def test_a_fragment_narrows_by_containment_without_regard_to_case() -> None:
    """A reviewer who remembers "learn" should find `scikit-learn`.

    Containment rather than a prefix, because the half of a name somebody remembers
    is frequently not the first half -- and case-insensitively, because nobody types
    a package name the way a channel spells it.
    """
    condition = name_condition("Learn", field="package__canonical_name")

    assert condition == Q(package__canonical_name__icontains="Learn")


def test_the_field_is_the_callers_to_name() -> None:
    """`CPM-APP-S18` puts the same box on the queues and the reports.

    Each reaches the canonical name by a different path, and a module that assumed
    the rollup's would either be copied or grow a special case per surface.
    """
    assert name_condition("git", field="package__canonical_name") == Q(package__canonical_name__icontains="git")
    assert name_condition("git", field="item__package__canonical_name") == Q(
        item__package__canonical_name__icontains="git"
    )


def test_a_fragment_nothing_matches_is_a_result_and_a_facet_value_nothing_matches_is_a_refusal() -> None:
    """The one rule this module exists for, written as the contrast it is.

    `filters.py` refuses `?vuln=criticl` and argues it at length: `CPM-AD-24`'s
    vocabularies are closed, so an unrecognised value is a typo or a stale bookmark
    and returning the unfiltered inventory under a URL claiming to be filtered is the
    worse answer.

    A package name is not a closed vocabulary. `?q=djangoo` is a search that matched
    nothing, and answering it with a 400 would be exactly as wrong.

    Both halves are asserted in one case on purpose. Written as two, somebody
    deleting one would see a passing file; written as one, the contrast is the thing
    that fails.
    """
    with pytest.raises(UnknownFacetValueError):
        filter_condition({"vuln": ["criticl"]})

    assert name_condition(search_term("djangoo"), field="package__canonical_name") != Q()


def test_the_search_parameter_is_not_a_facet_parameter() -> None:
    """Or `applied_filters` would try to read it as one and refuse every fragment.

    The collision is silent in the other direction too: a facet that took `q` would
    make every search a 400 and every URL a reviewer had bookmarked stop working.
    """
    assert applied_filters({SEARCH_PARAM: ["django"]}) == {}
