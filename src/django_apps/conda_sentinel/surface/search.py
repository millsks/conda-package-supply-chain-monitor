"""Finding a package by name, on every surface that lists packages.

`CPM-APP-S17`. `surface/filters.py` narrows the health table by nine things the policy
engine *decided* -- a status, a bucket, a confidence. None of them answers "where is
django", because `django` is not a status, and until this module the only way to reach
a package's detail page was to page to it or to type its URL. On the seeded hundred
that is two pages; at `CPM-NFR-1`'s ten thousand it is two hundred.

**A search is not a tenth facet, and the difference is the whole design.**
`filters.py` *refuses* a value outside its vocabulary and argues the case at length:
`CPM-AD-24`'s vocabularies are closed, so `?vuln=criticl` is a typo or a stale
bookmark, and silently returning the unfiltered inventory under a URL claiming to be
filtered is the worse of the two answers.

A package name is not a closed vocabulary. `?q=djangoo` is a search that matched
nothing, which is a **result** -- and answering it with a 400 would be exactly as
wrong as answering `?vuln=criticl` with the whole inventory. The two rules point in
opposite directions and both are right; this paragraph exists so that whoever next
notices the inconsistency reconciles it by leaving it alone.

**One module rather than a `filter()` in each view**, because `CPM-APP-S18` puts the
same box on the queues and the reports and the parameter has to be spelled the same
everywhere. A URL a reviewer sends a colleague should not stop working because they
pasted it into a different screen.
"""

from __future__ import annotations

from typing import Final

from django.db.models import Q

__all__ = ["MAX_TERM_LENGTH", "SEARCH_PARAM", "name_condition", "search_context", "search_term"]

#: The query-string parameter carrying the name fragment.
#:
#: The same spelling on every surface that lists packages, for the reason `SORT_PARAM`
#: is the same on two: a bookmark a reviewer sends an integrator should mean what it
#: says wherever it is pasted. `test_search.py` reconciles this against every view
#: that reads it.
SEARCH_PARAM: Final[str] = "q"

#: What a name fragment may not exceed.
#:
#: Not a security bound -- the ORM parameterises the value and `icontains` cannot be
#: made to do anything interesting with a long string. It is a bound on what gets
#: rendered back into the input and into the applied-filter summary, and on what a
#: database is asked to scan for. The longest canonical name in conda-forge is
#: comfortably under this, so a fragment longer than it cannot match anything anyway.
MAX_TERM_LENGTH: Final[int] = 128


def search_term(raw: str) -> str:
    """Return the name fragment a request asked for, normalised.

    Two normalisations and both are one-sided, which is the part worth reading.

    Surrounding whitespace goes, because a fragment pasted from anywhere carries it
    and `" django "` matching nothing would look like a broken search rather than a
    stray space.

    Underscores become hyphens, because conda-forge canonical names use hyphens --
    `scikit-learn`, `umap-learn`, `imbalanced-learn` -- while the PyPI import name a
    reader has in their head often uses underscores. The reverse is deliberately *not*
    done: turning hyphens into underscores in the needle would help nobody, because no
    canonical name in the roster contains an underscore, and doing it to the *column*
    instead would wrap it in a database function and put every index out of reach.

    Args:
        raw: The parameter as it arrived, which may be empty.

    Returns:
        The fragment to match, or `""` when the request asked for no search. An
        all-whitespace parameter is `""`, and so is a fragment too long to be a name.

    """
    term = raw.strip().replace("_", "-")
    if len(term) > MAX_TERM_LENGTH:
        return ""
    return term


def name_condition(term: str, *, field: str) -> Q:
    """Return the condition narrowing rows to packages whose name contains a fragment.

    `icontains` rather than a prefix or an exact match: a reviewer who remembers
    "learn" should find `scikit-learn`, and one who remembers "django" should find it
    whichever case they type. Adequate at ten thousand rows -- the answer if it stops
    being adequate is a trigram index, which is PostgreSQL-only and would make the
    development database diverge from the deployed one.

    Args:
        term: The fragment, from `search_term`. An empty one narrows nothing.
        field: The path from the queryset's model to the canonical name. Every
            surface has a different one, which is why this takes it rather than
            assuming the rollup's.

    Returns:
        The condition, or an empty `Q` when no search was asked for -- so a caller can
        combine it unconditionally rather than branching around it.

    """
    if not term:
        return Q()
    return Q(**{f"{field}__icontains": term})


def search_context(raw: str) -> dict[str, object]:
    """Return everything a template needs to render the search control.

    Three keys rather than one, and they travel together because a template that had
    the fragment but not the parameter name would hard-code `q`, and one that had
    neither bound would hard-code the length -- which is the duplication `CPM-APP-S17`
    caught in the health template before it shipped. A box that accepts more than
    `search_term` will keep turns a long paste into "no search at all", under an input
    still showing the reader's text.

    Takes the raw parameter rather than the request, for the reason `applied_filters`
    takes a mapping: nothing here needs Django's request layer, and a helper that
    asked for a request could not be called from a test that has none.

    Args:
        raw: The parameter as it arrived, which may be empty.

    Returns:
        The normalised fragment, the parameter's spelling, and the length bound.

    """
    return {
        "search": search_term(raw),
        "search_param": SEARCH_PARAM,
        "search_max_length": MAX_TERM_LENGTH,
    }
