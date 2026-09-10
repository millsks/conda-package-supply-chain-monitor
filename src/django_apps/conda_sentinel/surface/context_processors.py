"""What every product template needs and no view should have to remember.

One entry today: the queue names the navigation lists. It is here rather than in each
view's `get_context_data` because the navigation is on the *base* template, so a view
that forgot would render a page with a queue missing from its nav -- and the reader
would conclude the queue did not exist rather than that the page was wrong.

**Every queue is listed to every role**, and the refusal happens when one is opened.
The UX contract is explicit about it: role scoping happens *below* the nav. A nav
that differed per role would make a link somebody shared look broken to whoever
received it, and would tell them nothing about why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conda_sentinel.surface.queues import ALL_QUEUES
from conda_sentinel.surface.reports import REPORTS

if TYPE_CHECKING:
    from django.http import HttpRequest

__all__ = ["navigation"]


def navigation(request: HttpRequest) -> dict[str, object]:
    """Return what the product's navigation renders.

    Args:
        request: The request, unused today and part of the contract Django's template
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
