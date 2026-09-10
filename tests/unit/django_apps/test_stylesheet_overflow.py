"""Wide content scrolls inside its own container; the page body never scrolls sideways.

`CPM-APP-S16`. The health table has eleven columns of status chips and does not fit a
laptop beside the facet rail. That is fine and expected -- what is not fine is *how it
failed*: `.main-pane` could shrink and had no `overflow-x`, so the table did not
overflow its container, it made its container wider. The page grew, and the
navigation and the page heading went off-screen to the left.

**The distinction is the whole rule.** A table that scrolls is a table somebody reads.
A page that scrolls is a layout somebody thinks is broken -- they cannot see the
product's name, they cannot see which screen they are on, and the first thing they do
is scroll left to find out, which puts the table's own left edge off-screen instead.

**Why `min-width: 0` is the load-bearing half.** A grid or flex item defaults to
`min-width: auto`, which is its *content's* minimum -- so it refuses to shrink and
pushes its parent instead. `overflow-x` alone does nothing on an item that never
became smaller than its content.

**Asserted against the stylesheet rather than a rendered page**, because there is no
browser in this suite. That is a real limit and worth stating: this checks the rules
are declared, not that the result looks right. What it prevents is the specific
regression -- a container that holds a wide table and declares half the pair, which is
exactly the state `.main-pane` was in.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

import django_service

#: The product's stylesheet, read off the package rather than rebuilt from a layout
#: this module has no business knowing.
STYLESHEET: Final[Path] = Path(django_service.__file__ or "").parent / "static" / "css" / "conda-sentinel.css"

#: A width below which the health table's columns would be crushed rather than
#: scrolled. Not the declared minimum -- a floor under it, so the case is about the
#: table having a real one rather than about the exact number, which is a design
#: choice and may move.
A_CRUSHED_TABLE: Final[int] = 900

#: The containers that hold something wider than a laptop, and must scroll it.
#:
#: `.main-pane` holds the health table; `.panel` holds the queue, coverage and report
#: tables. `.panel` has carried both declarations since the mockups and `.main-pane`
#: had only `min-width` -- which is why the health view was the one that broke.
SCROLLING_CONTAINERS: Final[tuple[str, ...]] = (".main-pane", ".panel")

#: What each container must declare, and why one without the other is not enough.
REQUIRED: Final[dict[str, str]] = {
    "min-width:0": (
        "a grid or flex item defaults to min-width:auto, its content's minimum -- without this it never shrinks, "
        "so it pushes the page wider instead of overflowing"
    ),
    "overflow-x:auto": "without this the content that does not fit spills onto the page rather than scrolling",
}


def declarations(selector: str) -> str:
    """Return the declaration block for one selector.

    Args:
        selector: The selector to find, matched at the start of a rule.

    Returns:
        Its declarations with whitespace removed, so a rule written across two lines
        reads the same as one written across one.

    """
    source = STYLESHEET.read_text(encoding="utf-8")
    found = re.search(rf"^{re.escape(selector)}\s*\{{([^}}]*)\}}", source, re.M)

    assert found is not None, f"{selector} is not declared in {STYLESHEET.name}"
    return re.sub(r"\s+", "", found.group(1))


@pytest.mark.parametrize("selector", SCROLLING_CONTAINERS)
@pytest.mark.parametrize(("declaration", "reason"), sorted(REQUIRED.items()))
def test_a_container_of_wide_content_declares_both_halves(selector: str, declaration: str, reason: str) -> None:
    """Both, because either alone leaves the page scrolling.

    Parameterised over the pair rather than asserted together, so a failure says which
    half is missing -- which is the difference between "this rule is wrong" and "this
    rule is half of what it needs", and only the second tells you what to add.

    Args:
        selector: The container.
        declaration: What it must declare.
        reason: Why, for the failure message.

    """
    assert declaration in declarations(selector), (
        f"{selector} does not declare {declaration}: {reason}. CPM-APP-S16: wide content scrolls inside its own "
        f"container, and the page body never scrolls horizontally."
    )


def test_the_health_table_has_a_width_below_which_it_scrolls() -> None:
    """`width:100%` alone crushes columns instead of producing a scrollbar.

    Eleven columns of status chips squeezed into a laptop beside the facet rail is a
    table that is technically visible and not readable -- `advisories_matched` wrapped
    over four lines in a ninety-pixel cell. The minimum is what turns that into a
    scroll.
    """
    declared = declarations(".tbl")

    assert "min-width:" in declared, declared
    width = int(re.search(r"min-width:(\d+)px", declared).group(1))  # type: ignore[union-attr]
    assert width > A_CRUSHED_TABLE, f"a minimum of {width}px is narrower than the columns this table carries"


def test_the_stylesheet_is_where_this_module_thinks_it_is() -> None:
    """So every case above cannot pass by reading an empty string.

    A path built from a layout assumption is one that resolves to nothing after a move,
    and a regex over nothing matches nothing.
    """
    assert STYLESHEET.is_file(), STYLESHEET
    assert ".tbl" in STYLESHEET.read_text(encoding="utf-8")
