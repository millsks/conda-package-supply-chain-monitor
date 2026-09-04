"""How the suite decides whether a module creates `Group` rows, in one place.

Two modules ask that question and they ask it of different subjects.
`tests/unit/users/test_provisioning.py` asks it of the whole of `src/`, which is
AD-27's "no path creates groups of its own" stated as a property of the source
tree. `tests/unit/django_apps/test_role_migration.py` asks it of one file, so
that a product migration that started creating groups inline fails with its own
name on it rather than only inside the repository-wide audit.

A second implementation of the scan would be worse than a second call site of the
thing it audits: the two could disagree about what counts as creating a group,
and the disagreement would look like a passing test. So the detector lives here
and both callers import it, exactly as `tests/pixi_manifest.py` and
`tests/settings_import.py` hold the shared readers of the pixi manifest and of
the settings modules.

This is a helper module, not a collected one. `[tool.pytest.ini_options]
python_files` matches `test_*.py` and `tests.py`, so nothing here is collected,
and it sits at `tests/` rather than under `tests/unit/` because a collected test
module is not a helper library -- importing one from another ties two files'
collection together.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING
from typing import Final

if TYPE_CHECKING:
    from pathlib import Path

#: Manager methods that bring a row into existence. `get_or_create` is here as
#: well as `create` because the question this module answers is who *writes*
#: groups, not which spelling they used.
CREATION_VERBS: Final[frozenset[str]] = frozenset(
    {"create", "get_or_create", "update_or_create", "bulk_create", "acreate"},
)

#: The model a claim maps onto, as it is named in the registry.
GROUP_MODEL_NAME: Final[str] = "Group"


def group_creation_verbs(path: Path) -> set[str]:
    """Return the manager methods one module uses to create `Group` rows.

    Matched on the parsed tree rather than on the text. The spelling a text
    search would look for -- `Group.objects.get_or_create` -- appears nowhere in
    this repository, because the model is taken from a registry so that one
    implementation serves both the live and the historical path; a grep for it
    would therefore pass while proving nothing at all. What is matched instead is
    a creation call on a manager belonging to a name that module bound to the
    Group model, whatever it chose to call it.

    Args:
        path: The module to scan.

    Returns:
        The creation verbs applied to a Group manager, empty when the module
        creates no groups.

    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bound = group_model_names(tree)
    verbs: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in CREATION_VERBS:
            continue
        manager = node.func.value
        if (
            isinstance(manager, ast.Attribute)
            and manager.attr == "objects"
            and isinstance(manager.value, ast.Name)
            and manager.value.id in bound
        ):
            verbs.add(node.func.attr)
    return verbs


def group_model_names(tree: ast.Module) -> set[str]:
    """Return the local names one module has bound to the `auth.Group` model.

    Both routes are covered: an import of the concrete model, and a lookup
    through a model registry -- `apps.get_model("auth", "Group")` -- which is
    how a data migration and this project's own provisioning reach it.

    Args:
        tree: The parsed module.

    Returns:
        Every local name that refers to the Group model in that module.

    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "django.contrib.auth.models":
            bound |= {alias.asname or alias.name for alias in node.names if alias.name == GROUP_MODEL_NAME}
        elif isinstance(node, ast.Assign) and _is_group_model_lookup(node.value):
            bound |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        # Annotated, because the live and historical models are different
        # classes with the same shape and `Any` is the only honest annotation
        # for the pair. A scan that read only bare assignments would miss the
        # one writer it exists to find, which is what the idempotence assertion
        # in `tests/unit/users/test_provisioning.py` is positioned to catch.
        elif isinstance(node, ast.AnnAssign) and node.value is not None and _is_group_model_lookup(node.value):
            if isinstance(node.target, ast.Name):
                bound.add(node.target.id)
    return bound


def _is_group_model_lookup(value: ast.expr) -> bool:
    """Report whether an expression is a registry lookup of the Group model.

    Args:
        value: The expression a name was bound to.

    Returns:
        True when it is a `get_model` call naming the Group model.

    """
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    if name != "get_model":
        return False
    return any(isinstance(argument, ast.Constant) and argument.value == GROUP_MODEL_NAME for argument in value.args)
