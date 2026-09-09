"""`CPM-AD-12`: pagination is configured once, and no surface may opt out of it.

`CPM-APP-S01`'s first acceptance criterion has two halves and the second is the one
that lasts: `DEFAULT_PAGINATION_CLASS` and a maximum `PAGE_SIZE` are set globally,
**and a test asserts no view or serializer opts out**. The setting is one line; the
audit is what stops the tenth view from being the one that returns ten thousand rows.

**The opt-outs are enumerated rather than guessed at**, because DRF offers several
and they do not look alike. `pagination_class = None` is the obvious one. A different
pagination class is the subtler one -- it is still pagination, and it is still a view
deciding its own bound. `PAGE_SIZE` overridden per view is a third. Each has its own
detector and its own case.

**The sweep is over source, and the reason is that there are no product views yet.**
`CPM-APP-S02` writes the first. An audit that read the URLconf today would sweep the
inherited platform's one viewset and report a clean repository forever, which is how
an audit becomes permanently green and permanently useless. So the detectors are
measured against fixture source that demonstrates each opt-out, and the sweep is over
every module this product owns -- which covers the views that do not exist yet, the
day somebody writes one.

Reads source and settings: no database, no network, no requests.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.conf import settings
from rest_framework.pagination import PageNumberPagination

from conda_sentinel.core.pagination import DEFAULT_PAGE_SIZE
from conda_sentinel.core.pagination import MAX_PAGE_SIZE
from conda_sentinel.core.pagination import PAGE_SIZE_SETTING
from conda_sentinel.core.pagination import PAGINATION_SETTING
from conda_sentinel.core.pagination import BoundedPageNumberPagination
from tests.source_scan import SRC_ROOT
from tests.source_scan import parse
from tests.source_scan import project_files

if TYPE_CHECKING:
    from pathlib import Path

#: The dotted path `config/settings/base.py` installs, spelled here so the audit
#: reconciles the setting against the class rather than against itself.
DECLARED_CLASS: Final[str] = "conda_sentinel.core.pagination.BoundedPageNumberPagination"

#: Every attribute name that turns pagination off or aside, and what each means.
#:
#: `pagination_class` covers both the explicit `None` and a class of the view's own;
#: `page_size` and `PAGE_SIZE` cover a view or a pagination subclass resizing itself.
#: Named as a set because the detector reports *any* of them appearing on a class
#: body in this product's own modules -- see `test_no_module_this_product_owns_opts_out`.
OPT_OUT_ATTRIBUTES: Final[frozenset[str]] = frozenset({"pagination_class", "page_size", "PAGE_SIZE"})

#: The one module permitted to assign them, because it is the declaration itself.
#:
#: A named, licensable exemption in the shape this repository's audits already use:
#: the rule has to be satisfiable by the module the exception exists for, or it would
#: be deleted rather than amended.
THE_DECLARATION: Final[str] = "django_apps/conda_sentinel/core/pagination.py"

#: Source the detector is measured against, so its precision is a fact rather than
#: an absence of findings. Parsed here rather than kept as fixture files, on the
#: terms `tests/unit/django_apps/test_confidence_gate_audit.py` states.
A_VIEW_TURNING_PAGINATION_OFF: Final[str] = """
class PackageListView:
    pagination_class = None
"""

A_VIEW_BRINGING_ITS_OWN: Final[str] = """
class PackageListView:
    pagination_class = SomeOtherPagination
"""

A_VIEW_RESIZING_ITSELF: Final[str] = """
class PackageListView:
    page_size = 10000
"""

A_VIEW_THAT_DECLARES_NOTHING: Final[str] = """
class PackageListView:
    queryset = PackageHealth.objects.all()
"""


def opt_outs(tree: ast.Module) -> list[str]:
    """Return every class-body assignment that opts a surface out of the global bound.

    Args:
        tree: The parsed module.

    Returns:
        One `ClassName.attribute` per offending assignment, in source order.

    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
                if isinstance(statement, ast.AnnAssign)
                else []
            )
            found.extend(
                f"{node.name}.{target.id}"
                for target in targets
                if isinstance(target, ast.Name) and target.id in OPT_OUT_ATTRIBUTES
            )
    return found


# ---------------------------------------------------------------------------
# The setting.
# ---------------------------------------------------------------------------


def test_pagination_is_configured_globally() -> None:
    """AC 1's first half: both keys are set, and the class is this product's own.

    Asserted through DRF's resolved settings rather than the raw dict, because that
    is what a request actually reads -- a key spelled correctly in `base.py` and
    misspelled in an override would pass a dict check and paginate nothing.
    """
    from rest_framework.settings import api_settings  # noqa: PLC0415 - read after settings are composed

    assert settings.REST_FRAMEWORK[PAGINATION_SETTING] == DECLARED_CLASS
    assert api_settings.DEFAULT_PAGINATION_CLASS is BoundedPageNumberPagination
    assert api_settings.PAGE_SIZE == DEFAULT_PAGE_SIZE


def test_the_settings_page_size_is_the_one_the_class_was_written_for() -> None:
    """The reconciliation the literal in `base.py` exists to be checked against.

    The size is a literal there and a constant here, deliberately: importing
    `core/pagination.py` from the settings module evaluates `api_settings` at
    class-definition time, during that module's own import, and DRF then caches its
    *defaults* for the life of the process -- silently reverting every
    `REST_FRAMEWORK` key. So the two are separate spellings reconciled by this case,
    which is the same shape the beat schedule's `countdown` values take against their
    collectors' declared offsets.
    """
    assert settings.REST_FRAMEWORK[PAGE_SIZE_SETTING] == DEFAULT_PAGE_SIZE


def test_a_client_cannot_ask_for_a_bigger_page() -> None:
    """The mechanism, and it is stronger than policing a maximum.

    With no `page_size_query_param` there is no request that asks for ten thousand
    rows and is refused, because there is no request that asks. `max_page_size` is
    asserted as declared and as unreachable, which is what the class docstring
    claims.
    """
    assert BoundedPageNumberPagination.page_size_query_param is None
    assert BoundedPageNumberPagination.max_page_size == MAX_PAGE_SIZE
    assert MAX_PAGE_SIZE > DEFAULT_PAGE_SIZE


def test_the_declared_class_is_a_real_pagination_class() -> None:
    """A class DRF cannot use paginates nothing, and the failure is at request time."""
    assert issubclass(BoundedPageNumberPagination, PageNumberPagination)


# ---------------------------------------------------------------------------
# The detector, measured before it is trusted.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (A_VIEW_TURNING_PAGINATION_OFF, "PackageListView.pagination_class"),
        (A_VIEW_BRINGING_ITS_OWN, "PackageListView.pagination_class"),
        (A_VIEW_RESIZING_ITSELF, "PackageListView.page_size"),
    ],
    ids=["turned-off", "brings-its-own", "resizes-itself"],
)
def test_the_detector_finds_every_way_out(source: str, expected: str) -> None:
    """Three opt-outs, three detections. They do not look alike, so each has a case.

    `pagination_class = None` is the obvious one; a class of the view's own is still
    a view deciding its own bound; and a per-view `page_size` resizes without
    mentioning pagination at all.

    Args:
        source: The offending declaration.
        expected: What the detector should report.

    """
    assert opt_outs(ast.parse(source)) == [expected]


def test_the_detector_passes_a_view_that_declares_nothing() -> None:
    """The anti-vacuity half: a detector that fired on everything would prove nothing.

    A view that declares nothing is the *correct* shape -- it inherits the global
    bound -- so the audit must be silent about it.
    """
    assert opt_outs(ast.parse(A_VIEW_THAT_DECLARES_NOTHING)) == []


# ---------------------------------------------------------------------------
# The sweep.
# ---------------------------------------------------------------------------

#: Every module the sweep reads: this product's shipped source, less the one
#: declaration. Built at import so a violation is a named failing case rather than
#: a line in an assertion message.
SUBJECT_MODULES: Final[tuple[Path, ...]] = tuple(
    path
    for path in project_files(SRC_ROOT, skip_migrations=True)
    if path.relative_to(SRC_ROOT).as_posix() != THE_DECLARATION
)


@pytest.mark.parametrize("path", SUBJECT_MODULES, ids=lambda path: str(path.relative_to(SRC_ROOT)))
def test_no_module_this_product_owns_opts_out(path: Path) -> None:
    """The sweep, over every module rather than over the views that exist today.

    `CPM-APP-S02` writes the first product view; an audit that read the URLconf now
    would sweep the inherited platform's one viewset and report a clean repository
    for ever. Sweeping source covers the views that do not exist yet, the day
    somebody writes one.

    Args:
        path: The module under test.

    """
    relative = path.relative_to(SRC_ROOT).as_posix()

    assert opt_outs(parse(path)) == [], f"{relative} opts out of CPM-AD-12's global pagination bound"


def test_the_licensed_declaration_is_the_only_one_and_still_exists() -> None:
    """The exemption is counted, so it cannot become a hole.

    Two directions: the licensed module really does assign what the sweep forbids
    -- or the exclusion above is licensing nothing and the sweep proves less than it
    reads as proving -- and it is excluded exactly once.
    """
    declaration = SRC_ROOT / THE_DECLARATION
    swept = {path.relative_to(SRC_ROOT).as_posix() for path in SUBJECT_MODULES}

    assert declaration.is_file()
    assert opt_outs(parse(declaration)) != []
    assert THE_DECLARATION not in swept
    assert len(SUBJECT_MODULES) + 1 == len(project_files(SRC_ROOT, skip_migrations=True))
