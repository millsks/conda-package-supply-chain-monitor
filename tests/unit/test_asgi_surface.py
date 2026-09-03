"""Tests that `config.asgi` exposes Django's application and nothing else.

AD-16: `asgi.py` exposes Django's ASGI application directly. The scope
dispatcher, `config/websocket.py` and the module's coverage-exclusion entries
are all deleted together, so a surface that the route allowlist cannot see
cannot come back one file at a time.

This module reads `src/config/asgi.py` rather than importing it, because the
invariant is about the module's *source*: exactly one name is bound to an ASGI
callable, and it is `get_asgi_application()` with nothing wrapping it. A runtime
check cannot see a second binding that a wrapper would introduce, nor a
dispatcher nested inside a `settings.DEBUG` branch that the test settings do not
take. The runtime identity of the callable is asserted in
`tests/integration/test_asgi_request_path.py`.

Reading rather than importing buys nothing on side effects, and this file does
not claim otherwise: `src/config/__init__.py` imports `config.celery_app`, which
calls `configure_observability()` at module scope, so any import of anything
under `config` -- including `config.settings.test`, which pytest-django loads
before collection -- has already installed the instrumentors process-wide.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
PIXI_TOML = REPO_ROOT / "pixi.toml"
SONAR_PROPERTIES = REPO_ROOT / "sonar-project.properties"
ASGI_SOURCE = REPO_ROOT / "src" / "config" / "asgi.py"
DEVELOPMENT_DOC = REPO_ROOT / "docs" / "development.md"

SECTION_TITLE = "Protocols below the URL resolver"
SECTION_HEADING = f"## {SECTION_TITLE}"

ASGI_APP_PATH = "config.asgi:application"
ASGI_SERVERS = ("uvicorn", "gunicorn")

# Middleware that can answer a request without calling the rest of the chain, so
# the response never reaches the URL resolver. The section has to name each one.
# `CommonMiddleware` is inert only because DISALLOWED_USER_AGENTS and PREPEND_WWW
# are unset: it is armed by a settings change, with MIDDLEWARE untouched.
SHORT_CIRCUITING_MIDDLEWARE = (
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
)

# The rule AC #4 is satisfied by. The heading and the middleware list can both
# survive its deletion, so the rule itself is asserted by these phrases.
FORWARD_RULE_PHRASES = (
    "its own authentication story",
    "its own entry in the carrier",
    "accelerator.toml",
)


def _asgi_module() -> ast.Module:
    """Parse `src/config/asgi.py` without importing it.

    Returns:
        The parsed module, for structural assertions about the ASGI surface.

    """
    return ast.parse(ASGI_SOURCE.read_text(encoding="utf-8"))


def _omit_entries() -> list[str]:
    """Return the `[tool.coverage.run] omit` list as written in pyproject.toml.

    Returns:
        Every path pattern declared in the coverage omit list.

    """
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    omit = data["tool"]["coverage"]["run"]["omit"]
    return list(omit)


def _sonar_logical_lines() -> list[str]:
    """Return sonar-project.properties as logical lines, continuations joined.

    Sonar reads the file with Java `.properties` semantics, where a trailing
    backslash continues the value onto the next physical line. A reader that
    splits on newlines alone sees the continued half as an unrelated line, so an
    exclusion written that way is invisible to every assertion below -- exactly
    the residue shape those assertions exist to catch.

    Returns:
        One entry per logical property line.

    """
    logical: list[str] = []
    pending = ""
    for physical in SONAR_PROPERTIES.read_text("utf-8").splitlines():
        pending += physical.lstrip() if pending else physical
        if pending.endswith("\\"):
            pending = pending[:-1]
            continue
        logical.append(pending)
        pending = ""
    if pending:
        logical.append(pending)
    return logical


def _sonar_property(name: str) -> list[str]:
    """Return one comma-separated sonar property's entries, as written.

    A repeated key is rejected rather than resolved. Sonar takes the last
    declaration, so a first-match reader would report a cleaned exclusion list
    while the one that ships still names the deleted module.

    Args:
        name: The property key, e.g. `sonar.coverage.exclusions`.

    Returns:
        Every entry declared under that key.

    """
    declarations = [
        value
        for key, separator, value in (line.partition("=") for line in _sonar_logical_lines())
        if separator and key.strip() == name
    ]

    assert declarations, f"sonar-project.properties declares no {name}"
    assert len(declarations) == 1, f"{name} is declared more than once; Sonar uses the last"
    return [entry.strip() for entry in declarations[0].split(",") if entry.strip()]


def _sonar_coverage_exclusions() -> list[str]:
    """Return `sonar.coverage.exclusions` as written in sonar-project.properties.

    Returns:
        Every path pattern excluded from SonarCloud coverage.

    """
    return _sonar_property("sonar.coverage.exclusions")


def _sonar_analysis_exclusions() -> list[str]:
    """Return `sonar.exclusions` as written in sonar-project.properties.

    A path excluded from analysis is excluded from coverage measurement too, so
    this is a strictly stronger exemption than `sonar.coverage.exclusions` and
    belongs under the same residue check.

    Returns:
        Every path pattern excluded from SonarCloud analysis.

    """
    return _sonar_property("sonar.exclusions")


def _server_task_commands() -> list[str]:
    """Return every pixi task command that runs an ASGI/WSGI server.

    Tasks live in more than one table -- `[tasks]` and `[feature.<name>.tasks]` --
    so the file is walked rather than read at a fixed path.

    Returns:
        The command string of every task invoking uvicorn or gunicorn.

    """
    commands: list[str] = []

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key == "tasks" and isinstance(value, dict):
                for task in value.values():
                    command = task.get("cmd", "") if isinstance(task, dict) else task
                    if isinstance(command, str) and any(server in command.split() for server in ASGI_SERVERS):
                        commands.append(command)
            else:
                walk(value)

    walk(tomllib.loads(PIXI_TOML.read_text(encoding="utf-8")))
    return commands


def _forward_rule_section() -> str:
    """Return the body of the `## Protocols below the URL resolver` section.

    Returns:
        Everything between the section heading and the next level-2 heading.

    """
    return DEVELOPMENT_DOC.read_text(encoding="utf-8").split(SECTION_HEADING, 1)[1].split("\n## ", 1)[0]


def _documented_omitted_entrypoints() -> list[str]:
    """Return the entrypoint filenames the Coverage section names as excluded.

    The prose is a third carrier of the exclusion list. It is parsed rather than
    substring-matched so that it can be compared against the two machine-read
    carriers instead of merely being checked for one deleted name.

    Returns:
        Every filename backticked inside the section's parenthesised list.

    """
    text = DEVELOPMENT_DOC.read_text(encoding="utf-8")
    marker = "Deployment entrypoints ("
    start = text.index(marker) + len(marker)
    return re.findall(r"`([^`]+\.py)`", text[start : text.index(")", start)])


def _bound_names() -> list[str]:
    """Return every name `src/config/asgi.py` binds, at any nesting depth.

    `ast.walk` rather than `module.body`: `src/config/urls.py` already gates a
    block on `settings.DEBUG`, so a dispatcher reintroduced inside an `if`,
    `try` or `with` is a shape this package uses, and one that a body-only scan
    cannot see.

    Returns:
        Every name bound by assignment, annotated assignment, function or class
        definition, or import alias.

    """
    bound: list[str] = []
    for node in ast.walk(_asgi_module()):
        if isinstance(node, ast.Assign):
            bound += [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.append(node.target.id)
        elif isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef | ast.ClassDef):
            bound.append(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            bound += [alias.asname or alias.name.split(".")[0] for alias in node.names]
    return bound


class TestAsgiApplication:
    """The module-level callable is Django's handler, not a wrapper."""

    def test_application_is_assigned_from_get_asgi_application(self):
        """`application = get_asgi_application()`, with nothing wrapping it."""
        module = _asgi_module()
        assignments = [
            node
            for node in ast.walk(module)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "application" for target in node.targets)
        ]

        assert len(assignments) == 1, "expected exactly one `application` assignment, at any nesting depth"
        assert assignments[0] in module.body, "`application` must be bound unconditionally, at module level"
        value = assignments[0].value
        assert isinstance(value, ast.Call), "`application` must be the result of a call"
        assert isinstance(value.func, ast.Name)
        assert value.func.id == "get_asgi_application"
        assert value.args == [], "Django's handler is exposed unwrapped"
        assert value.keywords == [], "Django's handler is exposed unconfigured"

    def test_get_asgi_application_is_djangos_own(self):
        """The name is only worth asserting if it is imported from Django.

        `from config.shim import wrap as get_asgi_application` would otherwise
        satisfy the assignment test while wrapping the handler.
        """
        sources = {
            node.module
            for node in ast.walk(_asgi_module())
            if isinstance(node, ast.ImportFrom)
            and any((alias.asname or alias.name) == "get_asgi_application" for alias in node.names)
        }

        assert sources == {"django.core.asgi"}

    def test_no_function_named_application_is_defined(self):
        """The deleted scope dispatcher was `async def application(...)`."""
        definitions = [
            node.name
            for node in ast.walk(_asgi_module())
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef | ast.ClassDef) and node.name == "application"
        ]

        assert definitions == []

    def test_application_is_the_only_name_that_looks_like_an_asgi_callable(self):
        """`django_application` was the dispatcher's inner handle; it is gone.

        Named by shape rather than by an exact roster of the module's names:
        Story 1.6 removes the `sys.path` insert and with it `SRC_DIR`, and that
        deletion must not read as an AD-16 violation.
        """
        candidates = sorted(name for name in _bound_names() if "application" in name)

        assert candidates == ["application", "get_asgi_application"]

    def test_observability_is_configured_before_the_application_is_built(self):
        """The ordering Task 2 calls load-bearing, asserted where it can fail.

        Nothing at runtime can see this: `config/__init__.py` imports
        `config.celery_app`, which calls `configure_observability()` at module
        scope, so the instrumentors are already installed by the time any test
        imports anything. Delete the call from `asgi.py` and the span tests stay
        green -- while uvicorn, which imports `config.asgi` as its entrypoint and
        gets the same package import, would still be relying on a side effect
        this module is supposed to own. FR-47 depends on the call being here and
        being before the handler is constructed.
        """
        module = _asgi_module()
        calls = [
            node
            for node in module.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "configure_observability"
        ]
        assignments = [
            node
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "application" for target in node.targets)
        ]

        assert len(calls) == 1, "expected exactly one module-level configure_observability() call"
        assert assignments, "expected a module-level `application` assignment"
        assert calls[0].lineno < assignments[0].lineno, (
            "configure_observability() must run before get_asgi_application(), or the instrumentors do not attach"
        )


class TestTheServedApplicationIsThisModule:
    """The asserted module is the one the servers actually load.

    Every other assertion in this file is anchored to `src/config/asgi.py` by
    path. Retarget `pixi run serve` at a sibling module holding a dispatcher and
    all of them still pass, with AD-16's surface back in the deployment path.
    """

    def test_every_server_task_serves_the_asgi_module(self):
        commands = _server_task_commands()

        assert commands, "expected at least one uvicorn/gunicorn task in pixi.toml"
        assert [command for command in commands if ASGI_APP_PATH not in command] == []


class TestWebsocketModuleIsGone:
    """The module is deleted, not merely unreferenced."""

    def test_the_module_cannot_be_found(self):
        assert importlib.util.find_spec("config.websocket") is None

    def test_the_source_file_does_not_exist(self):
        assert not (REPO_ROOT / "src" / "config" / "websocket.py").exists()

    def test_asgi_does_not_import_it(self):
        """The wrapper's import carried a `# noqa: E402` and a rationale comment."""
        imported = {
            alias.name
            for node in ast.walk(_asgi_module())
            if isinstance(node, ast.ImportFrom | ast.Import)
            for alias in node.names
        } | {node.module or "" for node in ast.walk(_asgi_module()) if isinstance(node, ast.ImportFrom)}

        assert [name for name in imported if "websocket" in name] == []


class TestCoverageExclusionsAreClosed:
    """AD-16 deletes the coverage exclusions in the same change as the module.

    There are three carriers, not one: `[tool.coverage.run] omit` drives the
    gate, `sonar.coverage.exclusions` drives SonarCloud, and the Coverage section
    of `docs/development.md` is the human-readable restatement -- the one the
    original `websocket.py` residue was found in. `sonar.exclusions` is a fourth
    and stronger exemption, since a path dropped from analysis is dropped from
    coverage with it. A module excluded by any of them is a module whose coverage
    nobody reads, so all of them are asserted here.
    """

    def test_no_omit_entry_mentions_websocket(self):
        assert [entry for entry in _omit_entries() if "websocket" in entry] == []

    def test_no_sonar_exclusion_mentions_websocket(self):
        exclusions = _sonar_coverage_exclusions() + _sonar_analysis_exclusions()

        assert [entry for entry in exclusions if "websocket" in entry] == []

    def test_the_documented_entrypoints_match_the_omit_list(self):
        """The prose carrier is checked against the machine-read one.

        Nothing read this sentence before: reverting it to name the deleted
        module left the whole suite green, which is how the same residue reached
        two carriers in the first place.
        """
        omitted = sorted(Path(entry).name for entry in _omit_entries() if entry.startswith("src/config/"))

        assert sorted(_documented_omitted_entrypoints()) == omitted

    def test_the_deployment_entrypoints_are_still_omitted(self):
        """Story 1.5 declares these two; only the websocket entry goes."""
        omit = _omit_entries()
        assert "src/config/wsgi.py" in omit
        assert "src/config/asgi.py" in omit

    def test_every_excluded_source_path_still_exists(self):
        """An exclusion naming a deleted file is residue; that is how this one survived."""
        declared = _omit_entries() + _sonar_coverage_exclusions() + _sonar_analysis_exclusions()
        candidates = [entry for entry in declared if entry.startswith("src/") and "*" not in entry]

        assert candidates, "expected at least one literal src/ exclusion to check"
        assert [entry for entry in candidates if not (REPO_ROOT / entry).exists()] == []


class TestTheForwardRuleIsDocumented:
    """AC #4's artifact is the `docs/` section; nothing else observes it.

    `src/config/asgi.py` carries a comment pointing at this section by name, and
    Epic 4 is told to consult it before claiming the URLconf describes the whole
    network surface. Both pointers break silently if the section is renamed or
    dropped, so the heading is pinned the way `pixi.toml`, `pyproject.toml` and
    `sonar-project.properties` already are elsewhere in this suite.
    """

    def test_the_section_exists(self):
        """At its own heading level.

        A plain substring check passes on `### Protocols below the URL resolver`
        too, while `_section()`'s `\\n## ` bound would then run past the end of
        the section and assert against unrelated prose.
        """
        assert f"\n{SECTION_HEADING}\n" in DEVELOPMENT_DOC.read_text(encoding="utf-8")

    def test_asgi_points_at_the_section_by_name(self):
        assert SECTION_TITLE in ASGI_SOURCE.read_text(encoding="utf-8")

    def test_the_section_names_the_middleware_that_answer_below_the_resolver(self):
        """The exception list is prose; a middleware added without updating it fails here."""
        section = _forward_rule_section()

        for middleware in SHORT_CIRCUITING_MIDDLEWARE:
            assert middleware in section, f"{middleware} answers below the resolver but the section omits it"

    def test_the_section_states_the_forward_rule(self):
        """AC #4 is the rule, not the heading.

        The heading, the pointer from `asgi.py` and the middleware list all
        survive deleting the three bullets that carry the rule itself -- an
        authentication story of its own and an entry of its own in the carrier.
        Those are what AC #4 requires the documentation to state.
        """
        section = _forward_rule_section()

        for phrase in FORWARD_RULE_PHRASES:
            assert phrase in section, f"AC #4's rule no longer states {phrase!r}"
