"""Tests for `component.toml` and the loader that reads it (AD-28).

Two halves, and they check different things.

The **schema** half is asserted against the repository's own `component.toml`.
It is the file that travels, so what it says is what every materialized component
inherits: an entry that drifted here drifts everywhere at once. These cases read
the committed file and nothing else.

The **loader** half is asserted against declarations written into `tmp_path`.
Every refusal the loader can raise gets a case, because a refusal nothing
exercises is a refusal nobody has seen work -- and because AD-20's floor counts
the error branches like any other line. `load_component_declaration` takes a
path precisely so these cases supply one rather than monkeypatching a
module-level constant, which would be a second declaration site for where the
file lives.

The placement rule (AC #3) is checked mechanically rather than by reading the
prose: the top-level key set has to be a subset of the closed set, which is what
fails when somebody puts a disposition, a parameter site or a preset into the
file that travels instead of into `accelerator.toml`.

These are unit tests. They read committed repository files and write into
`tmp_path`; no network, no database, no other filesystem surface.
"""

from __future__ import annotations

import ast
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any
from typing import Final

import pytest
import yaml
from django.core.exceptions import ImproperlyConfigured

from config.component import SELECTABLE_FEATURES
from config.component import TOP_LEVEL_KEYS
from config.component import AdminProcessDeclaration
from config.component import ComponentDeclaration
from config.component import DatabaseDeclaration
from config.component import ProcessDeclaration
from config.component import load_component_declaration
from config.component.loader import COMPONENT_DECLARATION_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
DECLARATION = REPO_ROOT / "component.toml"
MKDOCS = REPO_ROOT / "mkdocs.yml"
DEPLOYMENT_DOC = REPO_ROOT / "docs" / "deployment.md"
COMPONENT_PACKAGE = REPO_ROOT / "src" / "config" / "component"

# The two closed sets, written out here as literals rather than imported.
#
# This is the whole point of these two names existing twice. A test that checks
# the committed file against `TOP_LEVEL_KEYS` and `SELECTABLE_FEATURES` checks
# the file against whatever the loader currently says, so adding `presets` to one
# constant or `graphql` to the other passes every case in this module -- the
# closure would be self-certifying and the placement rule (AC #3) and AD-29's
# three features would both become editable by editing the thing that enforces
# them. The independent copy is what makes the widening visible.
CLOSED_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "component",
        "adopted_apps",
        "selected_features",
        "databases",
        "processes",
        "admin_processes",
    }
)
CLOSED_SELECTABLE_FEATURES: Final[frozenset[str]] = frozenset({"celery", "redis", "storage"})

# The reference application is the all-features combination, so all three
# selectable features are declared here. A materialized component carries the
# subset it selected; the *Minimal* preset carries none.
REFERENCE_FEATURES: Final[frozenset[str]] = frozenset({"celery", "redis", "storage"})

# The process group AD-14 constrains. `worker` and `beat` exist only where
# `celery` is selected, which is why they sit inside an AD-24 marker pair in the
# file -- but this is the reference application, so all three are present.
EXPECTED_PROCESSES: Final[tuple[str, ...]] = ("web", "worker", "beat")

# The members of that group the AD-24 `celery` region owns, in declaration
# order. `web` is core and is deliberately not among them: it is what the region
# must stay above.
CELERY_PROCESSES: Final[tuple[str, ...]] = ("worker", "beat")

# AD-24's delimiters, matched as whole lines in TOML's own comment syntax.
FEATURE_MARKERS: Final[tuple[str, str]] = ("# feature:celery", "# /feature:celery")

# The section Story 5.1 Task 3 requires the deployment page to carry.
TWO_DECLARATIONS_HEADING: Final[str] = "## The two declarations"

# A declaration every case below starts from and mutates, so a case that removes
# a key is visibly removing it rather than quietly never having written it.
#
# The adopted application is spelled `example_apps.billing` -- a synthetic
# component's own distribution package, not this repository's. It must not be
# spelled through `django_apps`: that is a path root rather than a package and is
# deliberately not importable, so a fixture spelling it that way would be the one
# place in the repository modelling an adoption that cannot resolve.
VALID_DECLARATION: Final[str] = """
adopted_apps = ["example_apps.billing"]
selected_features = ["celery", "redis"]

[component]
name = "example"

[[databases]]
alias = "default"
required = true
migrate = ["migrate --database default --noinput"]

[[processes]]
name = "web"
task = "web"
replacement = "rolling"

[[admin_processes]]
name = "prune"
task = "prune"
schedule = "deployment-repository"
"""


def _nav_targets(entries: list[Any]) -> set[str]:
    """Return every page a mkdocs `nav` registers, at whatever depth.

    A `nav` entry is a bare page string, a `{title: page}` mapping, or a
    `{title: [...]}` section holding more of either. A comprehension over
    `entry.values()` alone raises `TypeError` on the third form and
    `AttributeError` on the first, so it would fail as an error rather than as an
    assertion the moment the navigation grew a section.

    Args:
        entries: One `nav` list.

    Returns:
        Every page target reachable from it.

    """
    targets: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            targets.add(entry)
            continue
        for value in entry.values():
            if isinstance(value, list):
                targets |= _nav_targets(value)
            else:
                targets.add(value)
    return targets


def _imported_modules(tree: ast.AST) -> set[str]:
    """Return every module name a syntax tree imports, dotted and whole.

    `from django import conf` and `import django.conf` name the same module in
    two shapes, so both are normalised to `django.conf` here rather than left for
    each caller to spell out.

    Args:
        tree: The parsed module.

    Returns:
        The imported module names.

    """
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            modules.add(module)
            modules |= {f"{module}.{alias.name}" if module else alias.name for alias in node.names}
    return modules


def _write(tmp_path: Path, source: str) -> Path:
    """Write one declaration into a temporary directory.

    Args:
        tmp_path: The directory to write into.
        source: The TOML text.

    Returns:
        The path written.

    """
    path = tmp_path / "component.toml"
    path.write_text(source, encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    """Return the repository's `component.toml`, parsed."""
    with DECLARATION.open("rb") as handle:
        parsed: dict[str, Any] = tomllib.load(handle)
    return parsed


@pytest.fixture(scope="module")
def declaration() -> ComponentDeclaration:
    """Return the repository's `component.toml`, loaded through the loader."""
    return load_component_declaration()


# ---------------------------------------------------------------------------
# The file itself (AC #1, AC #2).
# ---------------------------------------------------------------------------


def test_the_declaration_exists_at_the_repository_root() -> None:
    """AC #2: the file that always travels is at the root, beside `pixi.toml`.

    Asserted against the loader's own resolution as well as against the path this
    module computes, so a change to either walk fails here rather than leaving
    the loader reading a file no test looks at.
    """
    assert DECLARATION.is_file()
    assert COMPONENT_DECLARATION_PATH == DECLARATION


def test_the_declaration_parses(document: dict[str, Any]) -> None:
    """AC #1: the committed file is valid TOML and is not empty."""
    assert document != {}


def test_the_declaration_carries_only_its_own_concerns(document: dict[str, Any]) -> None:
    """AC #3: the mechanical form of AD-28's placement rule.

    A disposition, an AD-25 parameter site, a preset, a feature surface or the
    pinned verification subset written here is an `accelerator.toml` concern in
    the file that travels, and this is what fails when one appears.

    `selected_features` is the one key that looks like an accelerator concern and
    is not: the carrier declares what each feature *is*, this file declares which
    ones *this component has* -- and it is the only such declaration present at
    settings import in both trees.
    """
    unknown = sorted(set(document) - CLOSED_TOP_LEVEL_KEYS)
    assert unknown == [], f"component.toml carries {unknown}, which belongs in accelerator.toml (AD-28)"


def test_the_closed_key_set_is_the_one_this_module_pins() -> None:
    """The loader's closure is checked against a literal, not against itself.

    Every other case here reads `component.toml` through `TOP_LEVEL_KEYS`, so
    widening that constant would widen the check with it and an
    `accelerator.toml` concern would arrive in this file with every test still
    green. This is the case that fails instead.
    """
    assert TOP_LEVEL_KEYS == CLOSED_TOP_LEVEL_KEYS


def test_the_selectable_features_are_the_three_this_module_pins() -> None:
    """AD-29 revision 3: three features, and the constant cannot widen quietly.

    A fourth name added to `SELECTABLE_FEATURES` -- `ui` most of all, but any
    name -- changes the number of valid combinations and what AD-8's
    settings-import refusal will accept. It is a spine decision, so it fails here
    until the spine says otherwise.
    """
    assert SELECTABLE_FEATURES == CLOSED_SELECTABLE_FEATURES


def test_the_component_declares_its_name(document: dict[str, Any]) -> None:
    """AC #1: `[component]` carries the name and nothing another manifest owns."""
    assert document["component"] == {"name": "conda-package-supply-chain-monitor"}


def test_adopted_apps_is_present_and_names_the_adopted_application(document: dict[str, Any]) -> None:
    """AC #4: the adopted-app list is present, and it carries this repository's adoption.

    The key existing is what keeps AD-8's composition step from having to
    distinguish "adopted nothing" from "said nothing"; both of those remain
    ordinary states and are exercised below against synthetic declarations --
    present-and-empty by `test_a_present_but_empty_adopted_app_list_loads_as_empty`
    and absent by `test_an_absent_adopted_app_list_loads_as_empty`, which are
    different inputs and are asserted separately. What this asserts is the repository's
    own state: `conda_package_supply_chain_monitor.core` is adopted, which is the
    declaration half of the adoption whose installing half is `LOCAL_APPS` in
    `src/config/settings/base.py`.
    """
    assert isinstance(document["adopted_apps"], list)
    assert document["adopted_apps"] == ["conda_package_supply_chain_monitor.core"]


def test_selected_features_is_the_reference_combination(document: dict[str, Any]) -> None:
    """AC #1: the reference application is the all-features combination."""
    assert set(document["selected_features"]) == set(REFERENCE_FEATURES)


def test_selected_features_stays_inside_the_closed_set(document: dict[str, Any]) -> None:
    """The three selectable features are exactly `celery`, `redis` and `storage`."""
    assert set(document["selected_features"]) <= set(CLOSED_SELECTABLE_FEATURES)


def test_the_interface_mechanism_is_never_a_feature(document: dict[str, Any]) -> None:
    """AD-29 revision 3: the server-rendered interface is immovable core.

    A `ui` entry here is the mechanical form of that regression -- it would make
    an immovable part of every component look removable to the one list AD-8's
    settings-import refusal reads.
    """
    assert "ui" not in set(document["selected_features"])
    assert "ui" not in CLOSED_SELECTABLE_FEATURES
    assert "ui" not in SELECTABLE_FEATURES


def test_every_database_declares_its_alias_requiredness_and_migration_steps(document: dict[str, Any]) -> None:
    """AC #1 and AD-9: a deployment repository never has to guess a release step."""
    databases = document["databases"]
    assert databases != []
    for entry in databases:
        assert isinstance(entry["alias"], str)
        assert isinstance(entry["required"], bool)
        assert entry["migrate"] != [], f"{entry['alias']} declares no release-stage migration step"


def test_the_process_group_is_exactly_web_worker_and_beat(document: dict[str, Any]) -> None:
    """AC #1: the reference application's process model, in declaration order."""
    assert tuple(entry["name"] for entry in document["processes"]) == EXPECTED_PROCESSES


def test_beat_is_a_single_replica_replaced_before_it_is_started(document: dict[str, Any]) -> None:
    """AD-14: two schedulers double-enqueue every periodic task.

    A rolling replacement produces that second scheduler for the length of the
    overlap, which is why the count and the strategy are one decision rather than
    two.
    """
    beat = next(entry for entry in document["processes"] if entry["name"] == "beat")
    assert beat["replicas"] == 1
    assert beat["replacement"] == "stop-before-start"


def test_the_celery_processes_sit_inside_a_marker_pair() -> None:
    """AD-24: `worker` and `beat` exist in two of the six combinations.

    Without the markers, AD-14's two-way gate test (Story 5.2) fails in the four
    non-Celery combinations by declaring processes with no matching task. The
    markers are matched as whole lines because AD-24 delimits a region with
    paired line comments, and because prose *about* a marker is not one.

    Both bounds are asserted, and the upper one is the load-bearing half. A
    region that merely *contains* `worker` and `beat` is satisfied by a closing
    marker moved past `[[admin_processes]]` -- and a materializer stripping that
    region in a non-Celery combination would then silently delete the prune admin
    process, which has nothing to do with Celery and exists in all six.
    """
    lines = [line.strip() for line in DECLARATION.read_text(encoding="utf-8").splitlines()]
    opening, closing = FEATURE_MARKERS
    first_process = lines.index("[[processes]]")
    start = lines.index(opening, first_process)
    end = lines.index(closing, start)
    region = lines[start + 1 : end]

    # Lower bound: both Celery processes are inside, and they are the only
    # entries inside -- an exact list, not a containment check.
    assert region.count("[[processes]]") == len(CELERY_PROCESSES)
    assert [line for line in region if line.startswith("name = ")] == [
        f'name = "{process}"' for process in CELERY_PROCESSES
    ]

    # Upper bound: `web` is core and is declared before the region opens, and the
    # region closes before the administrative processes begin.
    assert lines.index('name = "web"') < start
    assert end < lines.index("[[admin_processes]]")


def test_each_selected_feature_sits_on_its_own_marked_line() -> None:
    """The per-combination *value* is produced by the one mechanism AD-24 permits.

    `selected_features` is not removed per combination, it takes a different
    value per combination -- which is neither a disposition nor a declared AD-25
    parameter. One feature per line, each line inside its own marker pair, keeps
    that inside AD-24's permitted mechanism and needs no value rewrite.
    """
    lines = [line.strip() for line in DECLARATION.read_text(encoding="utf-8").splitlines()]
    start = lines.index("selected_features = [")
    end = lines.index("]", start)
    region = lines[start + 1 : end]
    for feature in sorted(REFERENCE_FEATURES):
        assert region.count(f"# feature:{feature}") == 1
        assert region.count(f"# /feature:{feature}") == 1
        assert region.index(f"# feature:{feature}") < region.index(f'"{feature}",')
        assert region.index(f'"{feature}",') < region.index(f"# /feature:{feature}")


def test_admin_processes_declare_a_schedule_owner(document: dict[str, Any]) -> None:
    """AD-13: an admin process is outside the process group.

    It never sets `COMPONENT_PROCESS`, so it carries no process type -- which is
    checked here by the record's shape rather than by its absence from prose.
    """
    admin_processes = document["admin_processes"]
    assert admin_processes != []
    for entry in admin_processes:
        assert set(entry) == {"name", "task", "schedule"}
        assert entry["schedule"] == "deployment-repository"


def test_the_header_states_the_placement_rule_and_the_disposition() -> None:
    """AC #2 and AC #3: a future author reads the rule in the file it governs.

    Prose, so asserted as prose -- the substantive check on the split is
    `test_the_declaration_carries_only_its_own_concerns`. What this case protects
    is *both halves of the rule*: three loose substrings (`core`,
    `accelerator.toml`, `runtime`) survive a header that has lost the rule
    entirely and merely mentions the other file, which is exactly the header a
    reader would then place a rule by.

    The comment lines are unwrapped before matching, because the rule is one
    sentence and the file wraps it across two.
    """
    header = DECLARATION.read_text(encoding="utf-8").split("\n\n", 1)[0]
    prose = " ".join(" ".join(line.lstrip("# ") for line in header.splitlines()).split())

    # The disposition, which is what makes the file worth placing a rule in.
    assert "core" in prose
    assert "always travels" in prose

    # Half one: a runtime or deploy-time rule belongs in this file.
    assert "runtime or deploy time** belongs here" in prose

    # Half two: a materializer-only rule belongs in the other one. Losing this
    # half is the failure that fills `component.toml` with dispositions.
    assert "only the materializer needs** belongs in `accelerator.toml`" in prose


# ---------------------------------------------------------------------------
# The documentation half of Task 3.
# ---------------------------------------------------------------------------


def test_the_deployment_page_records_the_split() -> None:
    """AC #3: the placement rule is written where a future author will read it."""
    assert TWO_DECLARATIONS_HEADING in DEPLOYMENT_DOC.read_text(encoding="utf-8")


def test_the_deployment_page_is_registered_in_the_navigation() -> None:
    """`pixi run docs` is `mkdocs build --strict`, which fails on an unregistered page."""
    with MKDOCS.open(encoding="utf-8") as handle:
        config: dict[str, Any] = yaml.safe_load(handle)
    assert "deployment.md" in _nav_targets(config["nav"])


def test_navigation_targets_are_read_out_of_nested_sections_and_bare_entries() -> None:
    """The reader above must not break on the two other shapes a `nav` takes.

    `mkdocs` accepts a bare page string and a `{title: [...]}` section alongside
    the `{title: page}` mapping this navigation happens to use today. A reader
    that only handles the third raises `AttributeError` on the first and
    `TypeError` on the second -- so the day somebody groups the pages, the
    registration check above stops being an assertion and becomes an error, which
    is a different test from the one it was written to be.
    """
    nav = ["index.md", {"Deployment": "deployment.md"}, {"Reference": ["a.md", {"B": "b.md"}]}]

    assert _nav_targets(nav) == {"index.md", "deployment.md", "a.md", "b.md"}


# ---------------------------------------------------------------------------
# The loader (AC #1, AC #4).
# ---------------------------------------------------------------------------


def test_the_package_imports_no_django_settings() -> None:
    """The invariant the whole design of this loader rests on, observed.

    AD-8's refusal reads the selected-feature list *at settings import*, from
    inside the composition step Epic 9 adds to `config.settings.base`. A loader
    that reached the file through `django.conf.settings.BASE_DIR` would be
    importing the settings module that is in the middle of importing it -- and
    every behavioural case in this module passes under that rewrite, because they
    all run long after settings are configured. So the property is asserted
    structurally, over the package's own syntax trees, the way
    `tests/unit/startup/test_module_shape.py` asserts the allowlist's.

    `django.core.exceptions` is imported and is deliberately not caught here: it
    defines an exception class and touches no configuration.
    """
    offenders = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in COMPONENT_PACKAGE.rglob("*.py")
        if any(
            module == "django.conf" or module.startswith("django.conf.")
            for module in _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
        )
    )

    assert offenders == [], (
        f"these modules import django.conf, which the settings composition cannot afford: {offenders}"
    )


# ---------------------------------------------------------------------------
# Loading (AC #1, AC #4).
# ---------------------------------------------------------------------------


def test_the_loader_reads_the_repositorys_own_declaration(declaration: ComponentDeclaration) -> None:
    """The no-argument path resolves the root file without importing settings."""
    assert declaration.name == "conda-package-supply-chain-monitor"
    assert declaration.adopted_apps == ("conda_package_supply_chain_monitor.core",)
    assert declaration.selected_features == REFERENCE_FEATURES
    assert tuple(process.name for process in declaration.processes) == EXPECTED_PROCESSES
    assert declaration.databases[0].migrate == ("migrate --database default --noinput",)
    assert declaration.admin_processes[0].schedule == "deployment-repository"


def test_the_no_argument_path_is_cached() -> None:
    """Readiness (Story 5.3) answers a probe on a schedule; it must not re-read."""
    assert load_component_declaration() is load_component_declaration()


def test_an_explicit_path_is_re_read_rather_than_served_from_the_cache(tmp_path: Path) -> None:
    """A caller who names a file means that file's bytes, not the ones it held before.

    Asserted by rewriting *the same path*. Comparing `load(path)` against
    `load()` proves nothing at all: they read two different files, so they differ
    under every caching scheme including the stale one -- a cache keyed on the
    path would return the first parse for the second read and that comparison
    would still hold.
    """
    path = _write(tmp_path, VALID_DECLARATION)
    assert load_component_declaration(path).name == "example"

    _write(tmp_path, VALID_DECLARATION.replace('name = "example"', 'name = "rewritten"'))

    assert load_component_declaration(path).name == "rewritten"


def test_an_absent_adopted_app_list_loads_as_empty(tmp_path: Path) -> None:
    """AC #4: no `None`, no sentinel, no caller-side special case."""
    source = VALID_DECLARATION.replace('adopted_apps = ["example_apps.billing"]\n', "")
    loaded = load_component_declaration(_write(tmp_path, source))
    assert loaded.adopted_apps == ()


def test_a_present_but_empty_adopted_app_list_loads_as_empty(tmp_path: Path) -> None:
    """The state a component that adopts nothing actually writes, which is not the absent one.

    Distinct from the case above, and it stopped being covered by the committed
    file when this repository adopted its first application: `adopted_apps = []`
    is present-and-empty, `adopted_apps` missing entirely is absent, and only the
    second was exercised here. AD-8's composition step has to read both as
    "adopted nothing" without a special case, so both are asserted -- against a
    synthetic declaration, because the repository's own is no longer either one.
    """
    source = VALID_DECLARATION.replace('adopted_apps = ["example_apps.billing"]', "adopted_apps = []")
    loaded = load_component_declaration(_write(tmp_path, source))

    assert loaded.adopted_apps == ()


def test_an_absent_admin_process_list_loads_as_empty(tmp_path: Path) -> None:
    """A component with no maintenance process is ordinary, not malformed."""
    source = VALID_DECLARATION.split("[[admin_processes]]")[0]
    loaded = load_component_declaration(_write(tmp_path, source))
    assert loaded.admin_processes == ()


def test_an_absent_feature_list_is_the_minimal_preset(tmp_path: Path) -> None:
    """The *Minimal* preset selects no feature, which is a combination not an omission."""
    source = VALID_DECLARATION.replace('selected_features = ["celery", "redis"]\n', "")
    loaded = load_component_declaration(_write(tmp_path, source))
    assert loaded.selected_features == frozenset()


def test_an_absent_requiredness_defaults_to_required(tmp_path: Path) -> None:
    """AD-9: readiness treats a database as required unless this file says otherwise."""
    source = VALID_DECLARATION.replace("required = true\n", "")
    loaded = load_component_declaration(_write(tmp_path, source))
    assert loaded.databases[0].required is True


def test_an_absent_replica_count_is_the_platforms_to_choose(tmp_path: Path) -> None:
    """Absent means unconstrained, never zero."""
    loaded = load_component_declaration(_write(tmp_path, VALID_DECLARATION))
    assert loaded.processes[0].replicas is None


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    """A declaration that is not there is a configuration failure, not an `OSError`."""
    with pytest.raises(ImproperlyConfigured, match="could not be read"):
        load_component_declaration(tmp_path / "component.toml")


def test_unparseable_toml_is_refused(tmp_path: Path) -> None:
    """A `TOMLDecodeError` escaping would be a second exception type to catch."""
    with pytest.raises(ImproperlyConfigured, match="not valid TOML"):
        load_component_declaration(_write(tmp_path, "name = \n"))


def test_an_unknown_top_level_key_is_refused(tmp_path: Path) -> None:
    """AC #3: an `accelerator.toml` concern written here fails rather than being honoured."""
    source = VALID_DECLARATION + '\n[[dispositions]]\npath = "src/"\ndisposition = "core"\n'
    with pytest.raises(ImproperlyConfigured, match="unknown top-level key"):
        load_component_declaration(_write(tmp_path, source))


def test_an_unknown_feature_name_is_refused(tmp_path: Path) -> None:
    """The selectable features are closed; `ui` is core and is not among them (AD-29)."""
    source = VALID_DECLARATION.replace('selected_features = ["celery", "redis"]', 'selected_features = ["ui"]')
    with pytest.raises(ImproperlyConfigured, match="selected_features names"):
        load_component_declaration(_write(tmp_path, source))


def test_celery_without_redis_is_refused(tmp_path: Path) -> None:
    """FR-26: Celery's broker is Redis, so the pairing is not a valid combination."""
    source = VALID_DECLARATION.replace('selected_features = ["celery", "redis"]', 'selected_features = ["celery"]')
    with pytest.raises(ImproperlyConfigured, match="without 'redis'"):
        load_component_declaration(_write(tmp_path, source))


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('name = "example"', "name = 3"),
        ('adopted_apps = ["example_apps.billing"]', "adopted_apps = 7"),
        ('adopted_apps = ["example_apps.billing"]', "adopted_apps = [7]"),
        ('selected_features = ["celery", "redis"]', 'selected_features = "celery"'),
        ("[[databases]]", "[databases]"),
        ('alias = "default"', "alias = 1"),
        ("required = true", 'required = "yes"'),
        ('migrate = ["migrate --database default --noinput"]', "migrate = 1"),
        ('name = "web"', "name = 1"),
        ('task = "web"', "task = 1"),
        ('replacement = "rolling"', "replacement = 1"),
        ('replacement = "rolling"', 'replacement = "rolling"\nreplicas = "one"'),
        ('name = "prune"', "name = 1"),
        # The `[[admin_processes]]` task, which the `task = "web"` case above does
        # not reach: that replacement matches the `[[processes]]` entry, which is
        # written first. Without this case the admin record's task is the one
        # field in the file nothing validates.
        ('task = "prune"', "task = 1"),
        ('schedule = "deployment-repository"', "schedule = 1"),
    ],
)
def test_a_wrongly_typed_field_is_refused(tmp_path: Path, original: str, replacement: str) -> None:
    """Every field is validated, and the refusal names the file and the key.

    Parameterized over each declared field rather than over one representative,
    because "the loader validates" and "the loader validates *this* key" are
    different claims and only the second one survives an edit that adds a field
    read with a bare subscript.
    """
    source = VALID_DECLARATION.replace(original, replacement, 1)
    with pytest.raises(ImproperlyConfigured, match="must be declared as"):
        load_component_declaration(_write(tmp_path, source))


def test_an_absent_field_is_not_reported_as_a_written_null(tmp_path: Path) -> None:
    """A key nobody wrote is not a key somebody wrote as null.

    TOML has no null, so `found None` describes a declaration the author cannot
    have typed and sends them looking for one. The two readings share a raise
    site and differ in the sentence they produce.
    """
    source = VALID_DECLARATION.replace('name = "example"', "")

    with pytest.raises(ImproperlyConfigured, match="must be declared as str, and was not declared") as refusal:
        load_component_declaration(_write(tmp_path, source))

    assert "None" not in str(refusal.value)


def test_a_declaration_that_is_not_utf_8_is_refused(tmp_path: Path) -> None:
    """`tomllib.load` decodes the bytes itself, so this fails before the parse.

    `UnicodeDecodeError` is a `ValueError` and not a `TOMLDecodeError`, so
    uncaught it walks straight past the one exception type every caller of this
    module is told to catch.
    """
    path = tmp_path / "component.toml"
    path.write_bytes(b'[component]\nname = "\xff\xfe"\n')

    with pytest.raises(ImproperlyConfigured, match="not valid UTF-8"):
        load_component_declaration(path)


@pytest.mark.parametrize(
    ("original", "replacement", "refusal"),
    [
        # `bool` subclasses `int`, so this is accepted by an isinstance check
        # against `int` and read as a fixed count of one.
        ('replacement = "rolling"', 'replacement = "rolling"\nreplicas = true', "must be declared as int"),
        # Zero is not "the platform chooses" -- the absent key is -- and a
        # negative count is not a process model at all.
        ('replacement = "rolling"', 'replacement = "rolling"\nreplicas = 0', "must be at least 1"),
        ('replacement = "rolling"', 'replacement = "rolling"\nreplicas = -1', "must be at least 1"),
        # The replacement strategies are closed: either two generations may serve
        # at once or they may not, and a third spelling is a string no deployment
        # repository knows how to read.
        ('replacement = "rolling"', 'replacement = "recreate"', "is not among"),
        ('replacement = "rolling"', 'replacement = "Rolling"', "is not among"),
        # The placement rule one level down. Each of these is an
        # `accelerator.toml` concern written where a top-level check never looks.
        ('name = "example"', 'name = "example"\nversion = "9.9"', r"unknown \[component\] key"),
        ('alias = "default"', 'alias = "default"\ndisposition = "core"', r"unknown \[\[databases\]\] key"),
        ('name = "web"', 'name = "web"\npreset = "Minimal"', r"unknown \[\[processes\]\] key"),
        (
            'schedule = "deployment-repository"',
            'schedule = "deployment-repository"\ndisposition = "core"',
            r"unknown \[\[admin_processes\]\] key",
        ),
        # Identity. Every reader addresses an entry by one of these, so a repeat
        # leaves each of them silently picking one of two.
        (
            'migrate = ["migrate --database default --noinput"]',
            'migrate = []\n\n[[databases]]\nalias = "default"\nmigrate = []',
            r"\[\[databases\]\] alias declares",
        ),
        (
            'replacement = "rolling"',
            'replacement = "rolling"\n\n[[processes]]\nname = "web"\ntask = "web-again"\nreplacement = "rolling"',
            r"\[\[processes\]\] name declares",
        ),
        (
            'schedule = "deployment-repository"',
            (
                'schedule = "deployment-repository"\n\n[[admin_processes]]\n'
                'name = "prune"\ntask = "prune-again"\nschedule = "deployment-repository"'
            ),
            r"\[\[admin_processes\]\] name declares",
        ),
        # A blank identity parses and type-checks, and then addresses nothing.
        ('name = "example"', 'name = ""', r"\[component\] name is empty"),
        ('name = "example"', 'name = "   "', r"\[component\] name is empty"),
        ('alias = "default"', 'alias = ""', r"\[\[databases\]\] alias is empty"),
        ('name = "web"', 'name = ""', r"\[\[processes\]\] name is empty"),
        ('task = "web"', 'task = ""', r"\[\[processes\]\] task is empty"),
        ('name = "prune"', 'name = ""', r"\[\[admin_processes\]\] name is empty"),
        ('task = "prune"', 'task = ""', r"\[\[admin_processes\]\] task is empty"),
        ('schedule = "deployment-repository"', 'schedule = ""', r"\[\[admin_processes\]\] schedule is empty"),
    ],
)
def test_a_malformed_declaration_is_refused(tmp_path: Path, original: str, replacement: str, refusal: str) -> None:
    """Every refusal beyond the type check, one case each.

    A refusal nothing exercises is a refusal nobody has seen work, and each of
    these guards a value that parses cleanly and is then wrong -- a boolean read
    as a count, a strategy nothing downstream understands, a materializer concern
    written one table deeper than the top-level check reaches, an alias declared
    twice, an identity that names nothing.
    """
    source = VALID_DECLARATION.replace(original, replacement, 1)
    with pytest.raises(ImproperlyConfigured, match=refusal):
        load_component_declaration(_write(tmp_path, source))


@pytest.mark.parametrize(
    ("record", "field"),
    [
        (ComponentDeclaration, "name"),
        (DatabaseDeclaration, "alias"),
        (ProcessDeclaration, "name"),
        (AdminProcessDeclaration, "name"),
    ],
)
def test_every_returned_record_is_frozen(record: type, field: str, tmp_path: Path) -> None:
    """Three independent consumers share one declaration; none of them may edit it.

    Readiness, the AD-14 gate test and Epic 9's settings composition all read the
    same object. A mutable record is one any of them can change for the other
    two, and the change would surface as a wrong answer somewhere else entirely.
    """
    loaded = load_component_declaration(_write(tmp_path, VALID_DECLARATION))
    instances: dict[type, object] = {
        ComponentDeclaration: loaded,
        DatabaseDeclaration: loaded.databases[0],
        ProcessDeclaration: loaded.processes[0],
        AdminProcessDeclaration: loaded.admin_processes[0],
    }
    with pytest.raises(FrozenInstanceError):
        setattr(instances[record], field, "changed")
