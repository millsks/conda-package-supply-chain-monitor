"""Every command and audit the documentation tells you to run actually exists.

`CPM-DOCS-S04` documents how to start the product, seed it and change it safely.
Prose about a command is unusual among documentation in that it is **precisely
checkable** — either `pixi.toml` declares the task or it does not — and it is also the
kind a reader trusts most, because they paste it.

**Both halves of this were caught by writing the page.** A first draft told a new
maintainer to run `python manage.py run_policy_now`, which does not exist; the same
draft named `pixi run cov` and `pixi run fmt`, whose real names are `test-cov` and
`format`. Neither would have failed anything — they would have failed *a person*, on
their first day, on the page written to help them.

**The audit roster is the other half.** `maintaining-it.md` lists a dozen audits by
module name and says what each prevents. A renamed or deleted audit leaves the page
recommending a gate that is gone, which is worse than not listing it: a reader plans
around a check that will never run.

**It deliberately checks existence, not behaviour.** Whether `pixi run test-cov`
enforces the floor is `test_gate_contract.py`'s question. Whether the documentation
names something real is this one's.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Final

import pytest

#: The repository root, from this file rather than from a layout assumption.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The product pages that tell somebody to run something.
INSTRUCTIONAL_PAGES: Final[tuple[Path, ...]] = (
    REPO_ROOT / "docs" / "conda-sentinel" / "running-it.md",
    REPO_ROOT / "docs" / "conda-sentinel" / "maintaining-it.md",
)

#: A pixi task as the documentation writes it, with or without an environment.
A_PIXI_TASK: Final[re.Pattern[str]] = re.compile(r"pixi run (?:-e \w+ )?([a-z][a-z0-9-]*)")

#: Words that follow `pixi run` and are not tasks.
#:
#: `python` is the runner itself -- `pixi run python manage.py shell` -- and `install`
#: is pixi's own subcommand rather than a declared task. Named rather than pattern-
#: matched, because a list of two is clearer than a rule that has to explain itself.
NOT_TASKS: Final[frozenset[str]] = frozenset({"python", "install"})

#: An audit named in prose, as the roster writes it.
AN_AUDIT: Final[re.Pattern[str]] = re.compile(r"`(test_[a-z_]+)`")


def declared_tasks() -> set[str]:
    """Return every task `pixi.toml` declares, across every environment.

    Returns:
        The task names. Read from the parsed manifest rather than by matching lines,
        because a task declared under a feature is as runnable as one at the top
        level and a line-based reader would miss it.

    """
    manifest = tomllib.loads((REPO_ROOT / "pixi.toml").read_text(encoding="utf-8"))
    found: set[str] = set(manifest.get("tasks", {}))
    for feature in manifest.get("feature", {}).values():
        found.update(feature.get("tasks", {}))
    return found


def documented_tasks() -> dict[str, list[str]]:
    """Return every pixi task the documentation tells somebody to run.

    Returns:
        Task name to the pages naming it.

    """
    found: dict[str, list[str]] = {}
    for page in INSTRUCTIONAL_PAGES:
        for task in A_PIXI_TASK.findall(page.read_text(encoding="utf-8")):
            if task not in NOT_TASKS:
                found.setdefault(task, []).append(page.name)
    return found


def test_every_documented_command_exists() -> None:
    """A command in documentation is pasted, not read.

    A first draft of `running-it.md` said `python manage.py run_policy_now`, and
    `maintaining-it.md` said `pixi run cov` and `pixi run fmt` -- three names, none
    of them real, on the two pages written for somebody's first day. Nothing in the
    suite would have failed; a person would have.
    """
    declared = declared_tasks()
    missing = {task: pages for task, pages in documented_tasks().items() if task not in declared}

    assert missing == {}, (
        f"these tasks are documented and `pixi.toml` declares none of them: {missing}. A command in "
        f"documentation is pasted rather than read, so a wrong one fails a person rather than a test."
    )


def test_the_sweep_found_commands_to_check() -> None:
    """A regex over the wrong file reports no violations rather than no coverage."""
    documented = documented_tasks()

    assert len(documented) > 1, sorted(documented)
    assert "precommit" in documented, sorted(documented)


@pytest.mark.parametrize("page", INSTRUCTIONAL_PAGES, ids=lambda page: page.name)
def test_the_instructional_pages_exist(page: Path) -> None:
    """So the sweeps above cannot pass by reading nothing.

    Args:
        page: The page that must be there.

    """
    assert page.is_file(), page


def test_every_audit_the_roster_names_is_a_real_module() -> None:
    """`maintaining-it.md` lists a dozen audits and says what each prevents.

    A renamed or deleted one leaves the page recommending a gate that is gone, which
    is worse than not listing it: a reader plans around a check that will never run,
    and finds out when the thing it prevented happens.
    """
    have = {path.stem for path in (REPO_ROOT / "tests").rglob("test_*.py")}
    roster = REPO_ROOT / "docs" / "conda-sentinel" / "maintaining-it.md"
    named = set(AN_AUDIT.findall(roster.read_text(encoding="utf-8")))

    assert named, "the roster names no audits, so this asserts nothing"
    assert named <= have, (
        f"these audits are named in the documentation and do not exist: {sorted(named - have)}. A roster that "
        f"recommends a gate which is gone is worse than one that omits it."
    )
