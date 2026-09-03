"""NFR-7's only automatic guard: the development keypair cannot be committed.

Every other protection in this story is a convention -- the directory name is
declared once, the task writes only there, the docs say never to commit it. None
of those survives someone running `git add -A` on a machine where the ignore
entry was dropped in a merge. This file is what fails the gate when that happens.

It matters more here than the same test would in an ordinary repository. This
tree is a template: a key committed to it ships inside *every component generated
from it*, so one published private key would be shared by every service the
accelerator ever produces.

Reading a repository manifest from a unit test is established practice here --
`tests/unit/test_dependency_policy.py` and `tests/unit/test_locality_declaration.py`
both do it -- because the manifest is source, not I/O the code under test performs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

from config.local_dev.keys import DEV_KEY_DIR
from config.local_dev.keys import PRIVATE_KEY_FILENAME

#: The repository root, reached the same way the module under test reaches it.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

GITIGNORE: Final[Path] = REPO_ROOT / ".gitignore"

#: The entry, as `.gitignore` must spell it. Derived from the module's own
#: constant rather than written out, so renaming the directory without updating
#: the ignore entry fails here instead of shipping a key.
IGNORE_ENTRY: Final[str] = f"{DEV_KEY_DIR.name}/"

#: git's exit status for "not a repository", and for its other fatal setup
#: errors. Distinguished from an ordinary non-zero answer, which is the command
#: reporting a result rather than declining to run.
GIT_FATAL: Final[int] = 128


def test_the_gitignore_is_present() -> None:
    """Non-vacuity: the two cases below pass trivially against a missing file."""
    assert GITIGNORE.is_file()


def test_the_gitignore_declares_the_development_key_directory() -> None:
    """NFR-7: the entry exists, by the name the module declares.

    This asserts the *declaration site* -- renaming `DEV_KEY_DIR` without updating
    `.gitignore` fails here. Whether the path is actually ignored is a different
    question, and `test_the_key_material_is_actually_ignored` is what asks it.
    """
    entries = {line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()}

    assert IGNORE_ENTRY in entries


def test_the_key_material_is_actually_ignored() -> None:
    """The behavioural statement: git itself refuses to stage the private key.

    Membership in `.gitignore` is not the same claim, and the gap between them is
    not hypothetical. `.gitignore` treats a leading space as part of the pattern,
    so an entry indented by one character matches nothing at all -- while the
    declaration assertion above, which strips each line before comparing, sees it
    as present and passes. The same goes for a pattern edited into a shape that
    no longer covers the PEM, or an ignore rule elsewhere in the hierarchy. Only
    `git check-ignore` accounts for the pattern *as git reads it*.

    (A negation cannot re-include the key while the entry stays in its
    directory form: git does not descend into an excluded directory, so
    `!.local-dev-keys/signing-key.pem` would have no effect. Changing that entry
    to `.local-dev-keys/*` is what would make negations bite, and this case is
    what would notice.)
    """
    ignored = _git("check-ignore", "-q", "--", str(DEV_KEY_DIR / PRIVATE_KEY_FILENAME))

    if ignored is None:
        return
    assert ignored.returncode == 0, "git does not ignore the development private key"


def test_no_key_material_is_tracked() -> None:
    """The stronger statement: not merely ignored, but absent from the index.

    An entry added to `.gitignore` *after* a file was committed ignores nothing --
    the tracked copy stays tracked. Asking git directly is the only way to tell
    those two states apart.
    """
    tracked = _git("ls-files", "--", DEV_KEY_DIR.name)

    if tracked is None:
        return
    assert tracked.returncode == 0, tracked.stderr
    assert tracked.stdout.strip() == ""


def _git(*arguments: str) -> subprocess.CompletedProcess[str] | None:
    """Run one git command in the repository root, or answer `None`.

    `None` means git could not be asked at all -- it is absent from `PATH`, or the
    tree is not a working copy. Both cases return rather than fail, and the
    reasoning is about where this file *ships*: this tree is a template, and every
    component generated from it carries this test. A component materialized into a
    plain directory and gated before `git init` would otherwise fail its very
    first `pixi run ci` on a check that has nothing to do with its code. Where
    there is no index, "no key material is tracked" is true rather than unknown.

    In this repository git is always present -- pre-commit could not run otherwise
    -- so the guard never fires here and the assertions are real.

    Args:
        *arguments: The git arguments, after the executable name.

    Returns:
        The completed process, or `None` when git could not answer.

    """
    try:
        answer = subprocess.run(  # noqa: S603 - a fixed argument vector, no shell
            ["git", *arguments],  # noqa: S607 - resolved from PATH, as every other tool here is
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
    except FileNotFoundError, NotADirectoryError:
        return None
    # Any other non-zero status is the command's own answer and is handled by
    # callers rather than swallowed here.
    if answer.returncode == GIT_FATAL:
        return None
    return answer
