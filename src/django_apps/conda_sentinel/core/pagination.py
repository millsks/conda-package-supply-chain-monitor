"""`CPM-AD-12`: every collection response is bounded, and no surface may opt out.

`CPM-NFR-1` sizes this product at ten thousand packages and `CPM-NFR-4` requires
that a read stays usable at that size. Nothing in the inherited platform configures
pagination at all -- `CPM-AD-12` says so in as many words, "neither exists today" --
so the first endpoint anybody writes returns the whole inventory unless something
global stops it.

**The bound is a setting, not a per-view decision.** `config/settings/base.py`
installs `BoundedPageNumberPagination` as `DEFAULT_PAGINATION_CLASS` and a
`PAGE_SIZE` beside it, so a view that declares nothing is paginated, and a view that
declares something is the thing an audit looks for.
`tests/unit/django_apps/test_pagination_audit.py` sweeps for every way out.

**A client cannot ask for a bigger page, and that is the whole mechanism.** DRF
honours a client's `?page_size=` only when a pagination class sets
`page_size_query_param`; leaving it `None` means the size is fixed by the server and
`max_page_size` is unreachable by construction. That is deliberately stronger than
declaring a maximum and policing it: there is no request that asks for ten thousand
rows and is refused, because there is no request that asks. The UX contract reaches
the same place from the other side -- "the mockup's pager offers no page-size
selector and no prev/next arrows, which is correct and deliberate: page size is a
global setting, not a user choice."

`max_page_size` is declared anyway and is not decoration. It is the bound that
applies the day a story does open the query parameter -- an export path, a report
with a stated row count -- and having it declared beside the size means that story
changes one line rather than inventing a ceiling. `CPM-AD-12` names the other half
of that path: an export beyond the row cap is a task (`CPM-AD-9`), never an
unpaginated response, which is `CPM-APP-S08`.

**Why a subclass rather than DRF's own class named in settings.** Three reasons, and
the first is enough: a class this product owns is a class this product's audits can
name. The audit asserts that every paginated surface uses *this* class, which it can
only do if there is one to point at. The second is that `page_size_query_param = None`
is DRF's default and therefore invisible -- a later contributor setting it on a
subclass of `PageNumberPagination` would open the door with no diff anybody would
read as opening a door, where a change here sits beside the paragraph saying why it
is shut. The third is that the page size reads from settings, so the number lives
with the other operational numbers rather than in code.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import Final

from rest_framework.pagination import PageNumberPagination

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "PAGE_SIZE_SETTING",
    "PAGINATION_SETTING",
    "BoundedPageNumberPagination",
]

#: The two `REST_FRAMEWORK` keys this module is installed under.
#:
#: Named here rather than spelled in `config/settings/base.py` and again in the
#: audit, because a key spelled twice is one that can be renamed on one side only --
#: and the failure is silent: DRF ignores a key it does not recognise, so a
#: misspelled `DEFAULT_PAGINATION_CLASS` leaves every endpoint unpaginated with
#: nothing to read in a traceback.
PAGINATION_SETTING: Final[str] = "DEFAULT_PAGINATION_CLASS"
PAGE_SIZE_SETTING: Final[str] = "PAGE_SIZE"

#: How many rows a page carries.
#:
#: Fifty, and the number is argued from what a page is *for* rather than from what a
#: database can return. The health view is a table a person scans (`CPM-APP-S02`,
#: eleven columns), and fifty rows is about two screens of it -- enough that paging
#: is not constant, few enough that the first row and the pager are both reachable
#: without hunting. It is emphatically not a performance ceiling: `CPM-NFR-5`'s
#: budget is `CPM-APP-S02`'s to enforce and is measured on a page of this size.
DEFAULT_PAGE_SIZE: Final[int] = 50

#: The largest page any surface may ever serve.
#:
#: Unreachable today, on purpose -- see the module docstring. It bounds the day a
#: story opens `page_size_query_param`, and 500 is chosen as an order of magnitude
#: above the default rather than as a measurement: a caller with a legitimate reason
#: to want a bigger page wants *fewer round trips*, and ten pages in one is that;
#: a caller who wants ten thousand rows wants an export, which `CPM-AD-9` and
#: `CPM-APP-S08` make a task.
MAX_PAGE_SIZE: Final[int] = 500


class BoundedPageNumberPagination(PageNumberPagination):
    """The one pagination class this product serves collections through.

    Installed globally as `DEFAULT_PAGINATION_CLASS` (`CPM-AD-12`), so a view that
    declares nothing is paginated and a view that declares something is what
    `tests/unit/django_apps/test_pagination_audit.py` is looking for.

    **`page_size_query_param` stays `None`.** It is DRF's default, and it is
    restated here as an explicit assignment for the reason the module docstring
    gives: a default nobody wrote down is a door a later contributor can open
    without a diff that reads like opening a door. `max_page_size` is declared
    beside it so the ceiling is already decided when that day comes.
    """

    #: Read from `PAGE_SIZE` in `REST_FRAMEWORK` at request time, with this as the
    #: fallback. Both are `DEFAULT_PAGE_SIZE`, which is not redundant: DRF reads the
    #: setting when it is present and this attribute when it is not, and a
    #: settings module that dropped the key would otherwise silently unpaginate
    #: every endpoint rather than falling back to the size this class was written
    #: for.
    page_size = DEFAULT_PAGE_SIZE

    #: **Not** a query parameter a client may set. See the class docstring.
    page_size_query_param = None

    #: The ceiling that applies if `page_size_query_param` is ever opened.
    max_page_size = MAX_PAGE_SIZE
