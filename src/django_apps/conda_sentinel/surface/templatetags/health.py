"""The template's half of `CPM-AD-24`: values in, no decisions taken.

Two filters and nothing else. `tone` looks a status up in `core/tone.py`, and
`querystring` rebuilds a URL with one parameter changed so the pager and the sort
links keep the filters a reader has applied.

**Neither filter can produce a blank status**, which is the point of both being here
rather than inline in the template: `{{ cell.status }}` is already verbatim, and the
only way a status becomes blank on the screen is a `{% if %}` somebody adds around
it. Keeping the presentation logic in named, tested functions is what leaves the
template with nothing to be clever with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from conda_sentinel.surface.tone import tone_of

if TYPE_CHECKING:
    from django.http import QueryDict

register = template.Library()


@register.filter(name="tone")
def tone(status: str) -> str:
    """Return the stylesheet tone for a status.

    Args:
        status: The status value.

    Returns:
        The tone, never blank.

    """
    return tone_of(status)


@register.simple_tag
def querystring(query: QueryDict, **changes: object) -> str:
    """Return this request's query string with some parameters replaced.

    What the pager and the sort links are built from. Rebuilding rather than
    appending is the whole of it: `?vuln=critical&page=2` plus `page=3` appended
    twice is a URL Django reads as page 2, so a reader paging forward would stick.

    Args:
        query: The request's `GET`.
        **changes: Parameters to set. A value of `None` removes the parameter, which
            is how "back to page one after changing a filter" is expressed.

    Returns:
        The encoded query string, with no leading `?` so a template can decide
        whether one is needed.

    """
    updated = query.copy()
    for key, value in changes.items():
        if value is None:
            updated.pop(key, None)
        else:
            updated[key] = str(value)
    return updated.urlencode()
