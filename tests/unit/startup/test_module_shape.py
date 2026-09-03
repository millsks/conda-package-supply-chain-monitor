"""The refusal contract has one home, four public names and two invocation points.

AC #1 and AC #2. Three separable claims, each asserted mechanically rather than
by review:

* **One module.** `src/config/startup/` holds both stages and the FR-17
  allowlist, and it holds no second locality reader -- `config.locality` is the
  single declaration site for the `COMPONENT_*` contract (AD-1, Story 3.1).
  Asserted by *object identity* of the re-exported predicates, not by equal
  behaviour: two readers spelled the same way would pass a behavioural check on
  the day they were written and drift apart afterwards. Backed by a scan of the
  package for any `os.environ` read of its own.

* **Stage 1 is the last statement of every leaf settings module.** Enumerated
  from the directory rather than from a list written here, so a leaf added later
  is covered the moment it exists rather than the moment someone remembers.

* **`base.py` calls it nowhere.** The paired half of AD-26's gate, and the one
  that is easy to revert silently: "every settings module" is the plausible
  reading of the rule and the wrong one.

The last-statement check parses the AST rather than reading the last source
line. `production.py` and `test.py` both end with a trailing comment banner, so
a source-line check would either fail on the comment or re-implement comment
stripping. The technique is the one already in the suite at
`tests/unit/test_asgi_surface.py`.

This is a unit test: it reads repository files and parses them, and opens no
network, database or settings connection of its own.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from config import locality
from config import startup
from config.startup import allowlist
from config.startup import stage_one
from config.startup import stage_two

REPO_ROOT = Path(__file__).resolve().parents[3]
STARTUP_PACKAGE = REPO_ROOT / "src" / "config" / "startup"
SETTINGS_PACKAGE = REPO_ROOT / "src" / "config" / "settings"

# The stage-1 entry point, by the name the settings modules call it under. The
# gate below matches on the `Name` node, so an aliased import would fail it --
# which is the point: the call has to be legible as the call.
STAGE_ONE_CALL = "run_stage_one"

# `base.py` is excluded because it is a composition fragment, not a leaf, and
# `__init__.py` because it is a package marker. Everything else in the package
# is a module `DJANGO_SETTINGS_MODULE` can name.
NOT_A_LEAF_SETTINGS_MODULE = frozenset({"__init__.py", "base.py"})

# Exactly four, and nothing else. Every condition predicate is reached through
# the two entry points; neither the conditions nor the allowlist are public.
PUBLIC_NAMES = ["is_deployed", "is_serving_process", "run_stage_one", "run_stage_two"]


def _leaf_settings_modules() -> list[Path]:
    """Return every settings module `DJANGO_SETTINGS_MODULE` can name."""
    return sorted(path for path in SETTINGS_PACKAGE.glob("*.py") if path.name not in NOT_A_LEAF_SETTINGS_MODULE)


def _parse(path: Path) -> ast.Module:
    """Parse one source file into a module syntax tree."""
    return ast.parse(path.read_text(encoding="utf-8"))


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    """Return every call to a bare `Name` anywhere in a syntax tree."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]


class TestTheContractHasOneHome:
    """AC #1: one module, four public names, and no second locality reader."""

    def test_the_package_holds_both_stages_and_the_allowlist(self) -> None:
        """The three files AC #1 names, in the one directory it names."""
        present = {path.name for path in STARTUP_PACKAGE.glob("*.py")}

        assert {"__init__.py", "stage_one.py", "stage_two.py", "allowlist.py"} <= present

    def test_the_package_declares_no_second_locality_reader(self) -> None:
        """A `startup/locality.py` would be the second spelling of two variable names.

        Story 3.1 delivered `src/config/locality.py` as the single declaration
        site for the `COMPONENT_*` contract and states the rule directly: Epic
        4's `src/config/startup/` imports it rather than re-reading `os.environ`.
        """
        assert not (STARTUP_PACKAGE / "locality.py").exists()

    def test_no_module_in_the_package_reads_the_environment_itself(self) -> None:
        """The stronger form of the same claim: the package imports no `os` at all.

        A second reader does not have to be a file called `locality.py`. It only
        has to be an `os.environ.get("COMPONENT_RUNTIME")` written inline in a
        condition, which is the shape AD-1 is actually about.
        """
        importers = [
            path.name
            for path in sorted(STARTUP_PACKAGE.glob("*.py"))
            for node in ast.walk(_parse(path))
            if (isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "os" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "os")
        ]

        assert importers == [], f"these modules read the environment instead of importing config.locality: {importers}"

    def test_the_package_exports_exactly_the_four_public_names(self) -> None:
        """AC #1: two entry points and the two locality predicates, nothing else."""
        assert sorted(startup.__all__) == PUBLIC_NAMES

    @pytest.mark.parametrize("name", PUBLIC_NAMES)
    def test_every_exported_name_resolves_to_a_callable(self, name: str) -> None:
        """An `__all__` entry naming something that is not there is a lie the gate should catch."""
        assert callable(getattr(startup, name))

    def test_the_locality_predicates_are_the_delivered_ones_by_identity(self) -> None:
        """Object identity, not equal behaviour -- that is what proves no second reader.

        Two independently written readers agree on the day the second one is
        written and diverge the first time either is normalized, renamed or
        given a new recognized value. Identity cannot diverge.
        """
        assert startup.is_deployed is locality.is_deployed
        assert startup.is_serving_process is locality.is_serving_process

    def test_the_allowlist_module_is_the_authoritative_declaration_site(self) -> None:
        """Present and populated. Story 4.1 required it to exist; Story 4.6 filled it.

        Only that each surface says *something*: what any of them says is
        `tests/unit/startup/test_authentication_allowlist.py`'s question, and
        restating it here would give the same fact two owners. What this class can
        say is that the declaration lives in this package, which is AD-26's "one
        module containing both stages and the FR-17 allowlist".

        The rosters are `frozenset[str]` rather than the tuples of resolved
        objects the skeleton declared. `allowlist.py`'s own docstring records why:
        AD-8's composition step imports this module during settings composition,
        where resolving an authentication backend raises `AppRegistryNotReady` --
        the same wall `stage_one.py` hit from the other side -- so the resolution
        moved out to the tests, which is where the guarantee it buys belongs.
        """
        assert allowlist.ALLOWED_AUTHENTICATION_BACKENDS
        assert allowlist.ALLOWED_API_AUTHENTICATION_CLASSES
        assert allowlist.ALLOWED_AUTHENTICATION_ROUTE_SCOPES
        assert allowlist.CONTRIBUTABLE_KEYS
        assert allowlist.FORBIDDEN_CONTRIBUTABLE_KEYS

    def test_the_allowlist_resolves_nothing_at_module_scope(self) -> None:
        """The property that lets Epic 9 import this module from inside settings composition.

        A dotted path resolved here -- `import_string` at module level, or an
        `AUTHENTICATION_BACKENDS` entry written as the class itself -- would drag
        the application registry into a module that has to be importable before it
        is ready. Asserted structurally rather than by importing under a torn-down
        registry, which no test can arrange without breaking the session.
        """
        source = ast.parse((STARTUP_PACKAGE / "allowlist.py").read_text(encoding="utf-8"))
        imported = {
            (node.module or "").split(".")[0] for node in ast.walk(source) if isinstance(node, ast.ImportFrom)
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(source)
            if isinstance(node, ast.Import)
            for alias in node.names
        }

        assert "django" not in imported, "the allowlist imports django, which the composition step cannot afford"
        assert "allauth" not in imported
        assert "rest_framework" not in imported

    def test_stage_one_takes_a_required_positional_only_module(self) -> None:
        """The calling convention every condition story builds on, pinned.

        A default would only ever mask a call site that forgot to pass its own
        namespace, and a `**_: object` catch-all would silently absorb a future
        condition's misrouted keyword rather than failing on it.
        """
        parameters = list(inspect.signature(stage_one.run_stage_one).parameters.values())

        assert len(parameters) == 1
        assert parameters[0].kind is inspect.Parameter.POSITIONAL_ONLY
        assert parameters[0].default is inspect.Parameter.empty

    def test_stage_two_takes_no_arguments(self) -> None:
        """Stage 2 runs after `django.setup()`, so it reads the settings Django resolved."""
        assert list(inspect.signature(stage_two.run_stage_two).parameters) == []


class TestStageOneCannotBeSkippedByNotBeingLoaded:
    """AC #2: the gate on both halves of AD-26's last-statement rule."""

    def test_there_is_more_than_one_leaf_settings_module_to_check(self) -> None:
        """A parametrized gate over an empty enumeration passes without asserting anything."""
        assert {path.name for path in _leaf_settings_modules()} == {"local.py", "production.py", "test.py"}

    @pytest.mark.parametrize("path", _leaf_settings_modules(), ids=lambda path: path.name)
    def test_the_last_statement_of_every_leaf_is_the_stage_one_call(self, path: Path) -> None:
        """AD-26, verbatim: stage 1 is invoked as the last statement of every leaf.

        Last *statement*, not last line: this is what places the evaluation
        after the AD-8 composition step by construction, and it is why AD-9's
        iteration over every configured database will be reachable from a
        condition rather than seeing a half-composed mapping.
        """
        last = _parse(path).body[-1]

        assert isinstance(last, ast.Expr), f"the last statement of {path.name} is not an expression"
        assert isinstance(last.value, ast.Call), f"the last statement of {path.name} is not a call"
        assert isinstance(last.value.func, ast.Name), f"{path.name} calls something other than a bare name"
        assert last.value.func.id == STAGE_ONE_CALL, f"the last statement of {path.name} is not {STAGE_ONE_CALL}()"

    @pytest.mark.parametrize("path", _leaf_settings_modules(), ids=lambda path: path.name)
    def test_every_leaf_calls_stage_one_exactly_once(self, path: Path) -> None:
        """A second call would evaluate the contract against a half-composed namespace."""
        assert len(_calls_named(_parse(path), STAGE_ONE_CALL)) == 1

    def test_base_calls_stage_one_nowhere(self) -> None:
        """The paired half, and the one that can be reverted silently.

        `base.py` is never named by `DJANGO_SETTINGS_MODULE`; it is consumed
        through `from .base import *`, so a call at its end fires *before* the
        leaf finishes composing and destroys the after-composition property the
        rule exists to guarantee. It also configures forbidden states of its own
        that the leaves are what resolve, so the call would refuse in every
        combination. "Every settings module" is the plausible reading of AD-26
        and the wrong one.
        """
        base = SETTINGS_PACKAGE / "base.py"

        assert _calls_named(_parse(base), STAGE_ONE_CALL) == []
