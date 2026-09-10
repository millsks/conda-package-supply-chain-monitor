"""Every documentation path this repository cites names a file that exists.

`CPM-DOCS-S01` split one documentation tree into two, and the expensive half was not
the split -- it was the **237 references** in module docstrings, comments, tests and
planning artifacts that named `docs/development.md` or `docs/deployment.md` by path.

**A stale pointer is worse than the mixture it replaced.** A reader who follows one
concludes the documentation was deleted rather than moved, and stops looking. Nothing
fails, nothing is logged, and the only symptom is somebody deciding the codebase is
undocumented while a rewritten version of exactly what they wanted sits one directory
away.

**This is the check that keeps the count from growing back**, and it is deliberately
not about the split: it asserts that any documentation path cited anywhere resolves,
whatever the tree looks like. A later story that moves a page again fails here rather
than in somebody's afternoon.

**Anchors are not checked, and that is a stated limit.** `mkdocs build --strict` --
`pixi run docs` -- refuses a broken link *between* documentation pages, including
anchors, and it is a better tool for that than a regex. What it cannot see is a path
written in a Python comment, which is what this covers. Between them the two directions
are closed.

**Completed story records are deliberately out of scope**, which is a judgement worth
stating rather than a gap. `_bmad-output/implementation-artifacts/stories/` holds
dated records of what each story did: `CPM-RENAME-S02` records verifying eight import
lines at `docs/deployment.md` lines 1201-1202, against a file that existed when it
ran. Rewriting that path would make the record claim work it did not do, at line
numbers that never matched. A record of the past is allowed to name a file that no
longer exists; a pointer somebody is meant to follow is not, and everything in scope
below is the second kind.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

#: The repository root, from this file rather than from a layout assumption.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Where the documentation lives.
DOCS: Final[str] = "docs/"

#: A cited documentation path, written out.
#:
#: Matched loosely -- anything that looks like `docs/<something>.md` -- because the
#: point is to catch every spelling somebody might use rather than a list of the ones
#: used today. The trailing character class stops a match at a quote, a backtick, a
#: comma or a closing bracket, which is how these appear in prose.
A_CITED_DOC: Final[re.Pattern[str]] = re.compile(r"docs/[A-Za-z0-9_./-]+\.md")

#: The same path *constructed* rather than written: `REPO_ROOT / "docs" / "x.md"`.
#:
#: **Added after this sweep missed four of them.** The move was done by rewriting the
#: string `docs/deployment.md`, and four test modules build the path a segment at a
#: time instead -- so they read fine, matched nothing, and failed at
#: `FileNotFoundError` when the suite ran. A path a program *opens* is the one that
#: matters most, and it is the spelling a text sweep is least likely to see.
A_BUILT_DOC: Final[re.Pattern[str]] = re.compile(r'"docs"((?:\s*/\s*"[A-Za-z0-9_.-]+")+)')

#: The trees swept: everything a reader is meant to follow.
#:
#: `_bmad-output/` is excluded on purpose -- see the module docstring. A dated record
#: of what a story did may name the file it acted on; a live pointer may not.
SEARCHED: Final[tuple[str, ...]] = ("src", "tests", "docs", "README.md")

#: This module names the two retired paths on purpose, in the case that asserts they
#: have not come back. Excluding it by name rather than by some cleverness about
#: string literals, because the alternative is a sweep that cannot state its own rule.
THIS_MODULE: Final[str] = "tests/unit/test_documentation_references.py"

#: Suffixes worth reading. A binary or a lock file naming a documentation path is not
#: a citation anybody follows.
READABLE: Final[frozenset[str]] = frozenset({".py", ".md", ".toml", ".yml", ".yaml", ".html"})


def cited_paths() -> dict[str, list[str]]:
    """Return every documentation path cited, and where each is cited from.

    Both spellings: a path written as a string, and one built a segment at a time.
    The second is the one that matters most and the one a text sweep is least likely
    to see -- it is how a test *opens* a page, so a stale one fails with
    `FileNotFoundError` rather than sitting quietly in a comment.

    Returns:
        Cited path to the list of files citing it, so a failure names somewhere to
        go rather than only what is broken.

    """
    found: dict[str, list[str]] = {}
    for entry in SEARCHED:
        root = REPO_ROOT / entry
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in candidates:
            relative = str(path.relative_to(REPO_ROOT))
            if not path.is_file() or path.suffix not in READABLE or ".pixi" in path.parts:
                continue
            if relative == THIS_MODULE:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for cited in A_CITED_DOC.findall(text):
                found.setdefault(cited, []).append(relative)
            for segments in A_BUILT_DOC.findall(text):
                built = "docs/" + "/".join(re.findall(r'"([^"]+)"', segments))
                if built.endswith(".md"):
                    found.setdefault(built, []).append(relative)
    return found


def test_every_cited_documentation_path_exists() -> None:
    """The 237 references, and every one added after them.

    A stale pointer fails nothing at runtime, which is exactly why it needs a test: a
    reader who follows one concludes the documentation was deleted rather than moved,
    and the only symptom is somebody deciding this codebase is undocumented while what
    they wanted sits one directory away.
    """
    missing = {
        cited: sorted(set(citers)) for cited, citers in cited_paths().items() if not (REPO_ROOT / cited).is_file()
    }

    assert missing == {}, (
        f"these documentation paths are cited and do not exist: {missing}. CPM-DOCS-S01 split the tree; a "
        f"pointer that survived the move is worse than the mixture it replaced, because it fails silently and "
        f"a reader who follows it stops looking."
    )


def test_the_sweep_found_the_citations_it_claims_to() -> None:
    """A regex over an empty file list reports no violations rather than no coverage.

    Both trees matter and they fail differently: a wrong source path yields nothing,
    a wrong artifact path yields nothing, and the case above passes on either.
    """
    cited = cited_paths()

    assert len(cited) > 1, sorted(cited)
    citers = {citer for citers in cited.values() for citer in citers}
    assert any(citer.startswith("src/") for citer in citers), sorted(citers)[:10]
    assert any(citer.startswith("tests/") for citer in citers), sorted(citers)[:10]
    assert any(citer.startswith("docs/") for citer in citers), sorted(citers)[:10]


@pytest.mark.parametrize("gone", ["docs/development.md", "docs/deployment.md"])
def test_the_pages_that_moved_are_not_cited_by_their_old_names(gone: str) -> None:
    """Named, because these two are what the sweep was for.

    The general case above would catch them. This says which, so a failure after a
    future merge reads as "somebody reintroduced the old path" rather than as a
    puzzle -- and the two old names are the ones most likely to come back, from a
    branch written before the split.

    Args:
        gone: The path that no longer exists.

    """
    citers = cited_paths().get(gone, [])

    assert citers == [], (
        f"{gone} is cited by {citers} and was split by CPM-DOCS-S01 into the accelerator's tree and this "
        f"product's. Point the citation at whichever half carries the section it means."
    )
