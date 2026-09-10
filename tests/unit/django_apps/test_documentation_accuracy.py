"""`CPM-DOCS-S03`: the product documentation says things that are true of the code.

Prose cannot be checked for being *good*. It can be checked for two kinds of decay,
and both are the kind that happens quietly:

**A citation that no longer resolves.** The documentation is a distillation and keeps
`CPM-AD-n` identifiers so the full text stays findable. A decision renumbered, split
or withdrawn leaves a page pointing at nothing — and a reader who follows it concludes
the architecture record is gone rather than moved.

**A vocabulary that grew without the documentation noticing.** `CPM-FR-5` makes five
outcome states distinguishable, and the whole product rests on the difference between
them. A sixth added to `OutcomeState` and not explained is a state a reader meets on a
screen with nothing to read about it -- which is precisely the confusion the five
exist to prevent.

**What this deliberately does not do** is assert wording. A test that pinned a
sentence would be edited whenever the sentence improved, and would teach people to
edit it rather than to improve the sentence. What is pinned is the set of things that
must be *mentioned*, which is the part that goes stale on its own.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from conda_sentinel.core.outcomes import OutcomeState

#: The repository root, from this file rather than from a layout assumption.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: The product's own documentation tree.
PRODUCT_DOCS: Final[Path] = REPO_ROOT / "docs" / "conda-sentinel"

#: The architecture spine, which the documentation distils and cites into.
SPINE: Final[Path] = (
    REPO_ROOT
    / "_bmad-output"
    / "planning-artifacts"
    / "architecture"
    / "architecture-conda-package-supply-chain-monitor-2026-09-02"
    / "ARCHITECTURE-SPINE.md"
)

#: A decision citation, as the documentation writes it.
A_DECISION: Final[re.Pattern[str]] = re.compile(r"CPM-AD-(\d+)")

#: The page a reader meets the product on, and therefore the page the five states
#: have to be on. Named rather than swept, because "somewhere in the tree" is not
#: where a reader looks.
THE_OVERVIEW: Final[Path] = PRODUCT_DOCS / "index.md"


def product_pages() -> list[Path]:
    """Return every page of the product's documentation.

    Returns:
        The markdown files, sorted.

    """
    return sorted(PRODUCT_DOCS.glob("*.md"))


def declared_decisions() -> set[str]:
    """Return every decision the architecture spine declares.

    Returns:
        The numbers, as strings, read off the spine's own headings so a decision
        added there is available to cite without touching this module.

    """
    headings = re.findall(r"^### CPM-AD-(\d+)", SPINE.read_text(encoding="utf-8"), re.M)
    return set(headings)


def test_every_decision_the_documentation_cites_exists() -> None:
    """A citation into the spine has to land somewhere.

    The documentation is a distillation -- the spine stays the record -- and the
    identifiers are what make that work. One pointing at nothing is worse than no
    pointer: a reader follows it, finds nothing, and concludes the architecture record
    was deleted rather than renumbered.
    """
    declared = declared_decisions()
    dangling: dict[str, list[str]] = {}
    for page in product_pages():
        for number in A_DECISION.findall(page.read_text(encoding="utf-8")):
            if number not in declared:
                dangling.setdefault(f"CPM-AD-{number}", []).append(page.name)

    assert dangling == {}, (
        f"these decisions are cited by the documentation and are not in the spine: {dangling}. The docs distil "
        f"the spine and keep its identifiers so the full text stays findable; a citation that lands nowhere "
        f"reads as a deleted record."
    )


def test_the_documentation_cites_enough_of_the_spine_to_be_a_distillation() -> None:
    """So the case above cannot pass by citing nothing.

    A page with no identifiers would satisfy "every citation resolves" perfectly and
    would have stopped being a distillation -- it would be a second, unanchored
    account of the same architecture, which is the thing this approach exists to
    avoid.
    """
    cited = {number for page in product_pages() for number in A_DECISION.findall(page.read_text(encoding="utf-8"))}

    assert len(cited) >= len(declared_decisions()) // 3, sorted(cited)


@pytest.mark.parametrize("state", [state.value for state in OutcomeState])
def test_every_outcome_state_is_explained_where_a_reader_meets_the_product(state: str) -> None:
    """`CPM-FR-5`'s five, on the page somebody reads first.

    The product rests on the difference between them, and a state nobody explained is
    one a reader meets on a screen with nothing to read about it. A sixth added to
    `OutcomeState` fails here, which is the moment to write the sentence rather than
    six months later when somebody asks what it means.

    Named page rather than a sweep of the tree: "mentioned somewhere" is not where a
    reader looks.

    Args:
        state: The outcome value.

    """
    assert state in THE_OVERVIEW.read_text(encoding="utf-8"), (
        f"{state!r} is one of CPM-FR-5's outcome states and is not on {THE_OVERVIEW.name}. Every one of them "
        f"has to be explained where a reader meets the product, because the difference between them is what "
        f"the product is."
    )


def test_the_gap_states_are_distinguished_from_the_verdicts() -> None:
    """The distinction that matters more than the list.

    `not_found` is an answer -- it was looked for and is not there. `unknown` is the
    absence of one. A page that listed five states without saying which two are gaps
    would have taught a reader the names and not the idea.
    """
    overview = THE_OVERVIEW.read_text(encoding="utf-8").lower()

    assert "gap" in overview
    assert "nobody established anything here" in overview


def test_the_precedence_order_is_written_the_way_the_code_declares_it() -> None:
    """Worst first, and the documentation must not reorder it for readability.

    A reader who learned the order backwards would predict the opposite of what the
    product does with a package whose evidence disagrees with itself -- and would only
    find out on a package that mattered.
    """
    from conda_sentinel.core.outcomes import PRECEDENCE  # noqa: PLC0415 - read beside the claim

    prose = " ".join(page.read_text(encoding="utf-8") for page in product_pages())
    written = [state.value for state in PRECEDENCE]

    # The *order*, not the spacing. Matching a literal would fail on somebody widening
    # the arrows for legibility, which is an improvement, and would teach the next
    # author to narrow them again rather than to keep the order right.
    chain = r"\s*(?:→|->)\s*".join(re.escape(state) for state in written)

    assert re.search(chain, prose), (
        f"the precedence order is not written anywhere as {' → '.join(written)!r}. It is total, worst first, "
        f"and a reader who learns it backwards predicts the opposite of what the product does."
    )


def test_the_spine_is_where_this_module_thinks_it_is() -> None:
    """So every case above cannot pass by reading an empty string."""
    assert SPINE.is_file(), SPINE
    assert declared_decisions(), "the spine declares no CPM-AD headings, so the citation check asserts nothing"
    assert product_pages(), PRODUCT_DOCS
