"""What every product template needs and no view should have to remember.

Two things: the queue names the navigation lists, and the theme the reader chose.
Both are here rather than in each view's `get_context_data` because both are on the
*base* template -- a view that forgot the first would render a page with a queue
missing from its nav, and the reader would conclude the queue did not exist rather
than that the page was wrong. A view that forgot the second would render one page in
the wrong theme, which is `CPM-APP-S11`'s AC 1 failing on exactly the page nobody
tested.

**Every queue is listed to every role**, and the refusal happens when one is opened.
The UX contract is explicit about it: role scoping happens *below* the nav. A nav
that differed per role would make a link somebody shared look broken to whoever
received it, and would tell them nothing about why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conda_sentinel.surface.queues import ALL_QUEUES
from conda_sentinel.surface.reports import REPORTS
from conda_sentinel.surface.theming import THEME_LABELS
from conda_sentinel.surface.theming import THEMES
from conda_sentinel.surface.theming import asserted_theme
from conda_sentinel.surface.theming import theme_of

if TYPE_CHECKING:
    from django.http import HttpRequest

__all__ = ["navigation", "theme"]


def navigation(request: HttpRequest) -> dict[str, object]:
    """Return what the product's navigation renders.

    Args:
        request: The request, unused here and part of the contract Django's template
            engine calls this with.

    Returns:
        The queue names in the order `CPM-AD-22` declares them, and the report the
        nav's single entry points at.

    """
    return {
        "nav_queues": ALL_QUEUES,
        # The nav points at *a* report rather than a list of six, because six entries
        # would crowd out the four surfaces a reader uses daily. The report page
        # carries its own sidebar of the rest.
        "nav_first_report": REPORTS[0].slug,
    }


def theme(request: HttpRequest) -> dict[str, object]:
    """Return the reader's theme, and what the control needs to offer the others.

    `CPM-APP-S11` AC 1: the control is on every page and marks which of the three is
    in force. A context processor is what makes "every page" true -- the control is
    on the base template, and any view that had to remember to provide this would
    eventually be one that did not.

    Args:
        request: The request, whose cookies carry the choice.

    Returns:
        `theme` for marking the control, `data_theme` for the document element --
        empty for `auto`, which the template renders as no attribute at all -- and
        the roster the control is built from.

    """
    return {
        "theme": theme_of(request),
        "data_theme": asserted_theme(request),
        "themes": [{"value": value, "label": THEME_LABELS[value]} for value in THEMES],
    }
