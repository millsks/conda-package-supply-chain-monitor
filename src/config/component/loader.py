"""Read `component.toml` -- the component's own statement about itself (AD-28).

**Why this module imports no settings.** AD-8's refusal of a contribution naming
an unselected feature reads the selected-feature list *at settings import*, from
inside the composition step Epic 9 adds to `config.settings.base`. A loader that
reached the file through `django.conf.settings.BASE_DIR` would therefore be
importing the settings module that is in the middle of importing it. So the path
is resolved from this module's own location instead --
`Path(__file__).resolve(strict=True).parents[3]`, which walks
`component/` -> `config/` -> `src/` -> the repository root -- and nothing here
imports `django.conf`.

`django.core.exceptions` is imported, and is not the same thing: it defines the
exception class and touches no configuration. `ImproperlyConfigured` is the
refusal type the rest of this component already raises, and a second type for
"the component's declaration is malformed" would be a second vocabulary for one
kind of failure.

**Why the return value is frozen and why one field is a set.** Three independent
consumers read this declaration -- readiness (Story 5.3), the AD-14 two-way gate
test (Story 5.2) and Epic 9's settings composition -- and a mutable record shared
between three readers is a record any one of them can edit for the other two.
`selected_features` is a `frozenset` because every consumer asks it a membership
question and order carries no meaning there; `adopted_apps` is a tuple because
AD-8 makes its order load-bearing, and the two must not be given the same shape
merely because they are both lists in the file.

**Where the closed feature set comes from.** Exactly `celery`, `redis` and
`storage`. The server-rendered interface is immovable core and is not a feature
(AD-29, revision 3), so `ui` is not a name this loader will accept. `celery`
without `redis` is refused here too: the broker constraint (FR-26) makes it one
of the two invalid combinations of the eight declarable, the materializer refuses
the pairing at generation (Epic 8, Story 8.5), and this is the same rule asserted
where the component reads its own declaration rather than a second authority for
it.

Every malformed input raises `ImproperlyConfigured` naming the file and the
offending key. Nothing is defaulted quietly except the three absences AD-28 makes
ordinary: an absent `adopted_apps` (a component that adopts nothing), an absent
`[[admin_processes]]` (a component with no maintenance process) and an absent
`selected_features` (the *Minimal* preset, which selects no feature and is a
valid combination rather than a missing declaration).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any
from typing import Final

from django.core.exceptions import ImproperlyConfigured

__all__ = [
    "ADMIN_PROCESS_KEYS",
    "COMPONENT_DECLARATION_PATH",
    "COMPONENT_KEYS",
    "DATABASE_KEYS",
    "PROCESS_KEYS",
    "REPLACEMENT_STRATEGIES",
    "SELECTABLE_FEATURES",
    "TOP_LEVEL_KEYS",
    "AdminProcessDeclaration",
    "ComponentDeclaration",
    "DatabaseDeclaration",
    "ProcessDeclaration",
    "load_component_declaration",
]

#: The repository root's `component.toml`, resolved from this module's own
#: location rather than from a setting -- see the module docstring.
#:
#: `strict=True` asks the OS to resolve every component of the path and to
#: follow symlinks, so what `parents[3]` walks up from is the module's real
#: location rather than a symlink's apparent one -- an editable install whose
#: `config/` is a link into a checkout resolves to the checkout, which is where
#: `component.toml` is. It is not an error-reporting device: `__file__` for a
#: module that is being imported names a file that exists, so in practice
#: nothing here fails, and where a resolution *can* fail it raises
#: `FileNotFoundError` at import time -- neither `ImproperlyConfigured` nor
#: something `load_component_declaration`'s one-exception contract covers.
#:
#: What it does not protect against: `parents[3]` landing on a wrong-but-existing
#: directory. A non-editable install puts this module four levels below a
#: `site-packages` parent that resolves perfectly well and holds no
#: `component.toml`, and the failure surfaces as the ordinary missing-file
#: refusal in `_read`. Packaging the declaration into a built distribution is
#: Story 5.6's call; see `docs/deployment.md`.
COMPONENT_DECLARATION_PATH: Final[Path] = Path(__file__).resolve(strict=True).parents[3] / "component.toml"

#: The three selectable features, closed (AD-29, revision 3). `ui` is absent
#: because the server-rendered interface is immovable core, and a `ui` entry in
#: `selected_features` is the mechanical form of that regression.
SELECTABLE_FEATURES: Final[frozenset[str]] = frozenset({"celery", "redis", "storage"})

#: The feature whose broker every other feature-free combination does without,
#: and the feature that broker is. FR-26 makes `celery` without `redis` one of
#: the two invalid combinations of the eight declarable.
CELERY_FEATURE: Final[str] = "celery"
REDIS_FEATURE: Final[str] = "redis"

#: Every key this file is permitted to carry, closed. This is the mechanical form
#: of AD-28's placement rule: a disposition, a parameter site, a preset or a
#: feature surface put here is an `accelerator.toml` concern in the wrong file,
#: and it fails on this set rather than being read and quietly honoured.
TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "component",
        "adopted_apps",
        "selected_features",
        "databases",
        "processes",
        "admin_processes",
    }
)

#: The same closure, one level down. AD-28's placement rule is about *this file*,
#: not about its outermost mapping: `[component] version`, `[[databases]]
#: disposition` and `[[processes]] preset` are each an `accelerator.toml` concern
#: written in a place a top-level check never looks, and a key that is read by
#: nothing while its author believes it is honoured is the exact failure the
#: closed set exists to prevent. So every table this file declares carries a
#: closed key set too, and an unknown key inside one fails the same way an
#: unknown key beside one does.
COMPONENT_KEYS: Final[frozenset[str]] = frozenset({"name"})
DATABASE_KEYS: Final[frozenset[str]] = frozenset({"alias", "required", "migrate"})
PROCESS_KEYS: Final[frozenset[str]] = frozenset({"name", "task", "replicas", "replacement"})
ADMIN_PROCESS_KEYS: Final[frozenset[str]] = frozenset({"name", "task", "schedule"})

#: The replacement strategies AD-14 admits, closed. Two, and they are the whole
#: distinction the platform can act on: either two generations of a process may
#: serve at once or they may not. A third spelling -- `Rolling`, `recreate`, a
#: strategy a particular platform happens to name -- would be read by a
#: deployment repository that knows neither, so it is refused here rather than
#: passed through as a string nothing validates.
#:
#: `[[admin_processes]] schedule` is deliberately *not* closed the same way. One
#: known value (`deployment-repository`) is a value, not a set: closing it now
#: would refuse the second cadence owner before anyone has decided what the
#: second one is called.
REPLACEMENT_STRATEGIES: Final[frozenset[str]] = frozenset({"rolling", "stop-before-start"})


@dataclass(frozen=True, slots=True)
class DatabaseDeclaration:
    """One database alias, and what the component states about it (AD-9).

    Attributes:
        alias: The Django database alias, as `DATABASES` spells it.
        required: Whether readiness must refuse while this alias is unreachable.
            Absent means required: a contributed database is required unless this
            file says otherwise, so an omission fails closed.
        migrate: The release-stage steps for this alias, one entry per invocation
            the deployment repository runs before new pods serve.

    """

    alias: str
    required: bool
    migrate: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProcessDeclaration:
    """One member of the process group, and its AD-14 constraints.

    Attributes:
        name: The process type, which is also the value its task sets
            `COMPONENT_PROCESS` to.
        task: The pixi task that runs it. Story 5.2's two-way gate test
            reconciles this against the manifest in both directions.
        replicas: The fixed replica count, or None when the count is the
            platform's to choose. `beat` is the one process that fixes it.
        replacement: How the platform may replace a running process --
            `rolling`, or `stop-before-start` where two generations must never
            overlap.

    """

    name: str
    task: str
    replicas: int | None
    replacement: str


@dataclass(frozen=True, slots=True)
class AdminProcessDeclaration:
    """One administrative process: outside the process group by construction (AD-13).

    An admin process must never set `COMPONENT_PROCESS`. A one-off run that
    declared itself a serving process would fire the serving-process refusals and
    fail the maintenance it was invoked to perform, so the absence of a process
    type on this record is the point of the record being a separate kind.

    Attributes:
        name: What the process is called.
        task: The pixi task that runs it.
        schedule: Who owns the cadence. `deployment-repository` says the
            component declares that the process exists, not when it runs.

    """

    name: str
    task: str
    schedule: str


@dataclass(frozen=True, slots=True)
class ComponentDeclaration:
    """Everything `component.toml` states, parsed and validated.

    Attributes:
        name: The component's own name.
        adopted_apps: The adopted reusable applications, in the order AD-8's
            composition step applies them. Empty is ordinary.
        selected_features: The features this combination selected, as a set --
            every consumer asks membership and order carries no meaning. Empty is
            the *Minimal* preset, not a missing declaration.
        databases: One entry per alias.
        processes: The process group.
        admin_processes: The administrative processes, which are not in the
            process group. Empty is ordinary.

    """

    name: str
    adopted_apps: tuple[str, ...]
    selected_features: frozenset[str]
    databases: tuple[DatabaseDeclaration, ...]
    processes: tuple[ProcessDeclaration, ...]
    admin_processes: tuple[AdminProcessDeclaration, ...]


def load_component_declaration(path: Path | None = None) -> ComponentDeclaration:
    """Read and validate the component's declaration.

    Args:
        path: The declaration to read. Defaults to the repository root's
            `component.toml`, resolved from this module's location. The parameter
            exists so a test supplies a path rather than monkeypatching a
            module-level constant -- a patched constant is a second declaration
            site for where the file lives, which is what AD-1 keeps this module
            from having.

    Returns:
        The parsed declaration.

    Raises:
        ImproperlyConfigured: When the file is missing, is not UTF-8, is not
            valid TOML, carries a key outside `TOP_LEVEL_KEYS` or outside the
            closed key set of the table it is written in, declares a field with
            the wrong type, leaves an identifying field blank, repeats a database
            alias or a process name, declares a replica count that is not a
            positive integer, names a replacement strategy outside
            `REPLACEMENT_STRATEGIES`, names a feature outside
            `SELECTABLE_FEATURES`, or selects `celery` without `redis` (FR-26).

    """
    if path is None:
        return _load_default()
    return _load(path)


@cache
def _load_default() -> ComponentDeclaration:
    """Read the repository root's declaration once per process.

    Cached because readiness (Story 5.3) answers a probe on a schedule and must
    not re-read and re-parse a file that ships with the tree on each one. Only
    the no-argument path is cached: an explicit path is a caller who knows which
    bytes they mean, and handing them a value parsed from an earlier file of the
    same name would be a surprise no caller asked for.

    Returns:
        The parsed declaration.

    """
    return _load(COMPONENT_DECLARATION_PATH)


def _load(path: Path) -> ComponentDeclaration:
    """Parse and validate one declaration file.

    Args:
        path: The file to read.

    Returns:
        The parsed declaration.

    Raises:
        ImproperlyConfigured: On any malformed input -- see
            `load_component_declaration`.

    """
    document = _read(path)
    _refuse_unknown_keys(path, document, TOP_LEVEL_KEYS, "top-level")

    component = _typed(path, document.get("component", {}), dict, "[component]")
    _refuse_unknown_keys(path, component, COMPONENT_KEYS, "[component]")

    databases = tuple(_database(path, table) for table in _tables(path, document, "databases"))
    processes = tuple(_process(path, table) for table in _tables(path, document, "processes"))
    admin_processes = tuple(_admin_process(path, table) for table in _tables(path, document, "admin_processes"))

    # Identity, checked after the entries parse rather than during: an alias or a
    # process name written twice is not a type error in either entry, and the
    # readers downstream key on it. Readiness would probe one of two `default`
    # databases and never learn which; AD-14's gate test would reconcile one of
    # two `beat` entries against one pixi task and call the pair consistent.
    _refuse_duplicates(path, [entry.alias for entry in databases], "[[databases]] alias")
    _refuse_duplicates(path, [entry.name for entry in processes], "[[processes]] name")
    _refuse_duplicates(path, [entry.name for entry in admin_processes], "[[admin_processes]] name")

    return ComponentDeclaration(
        name=_named(path, component.get("name"), "[component] name"),
        adopted_apps=_strings(path, document.get("adopted_apps", []), "adopted_apps"),
        selected_features=_selected_features(path, document),
        databases=databases,
        processes=processes,
        admin_processes=admin_processes,
    )


def _read(path: Path) -> dict[str, Any]:
    """Return one declaration file's parsed TOML.

    Args:
        path: The file to read.

    Returns:
        The parsed document.

    Raises:
        ImproperlyConfigured: When the file is absent, is not UTF-8, or is not
            valid TOML. All three are re-raised as the component's own refusal
            type rather than escaping as an `OSError`, a `UnicodeDecodeError` or
            a `TOMLDecodeError`, so a caller reporting a configuration failure
            has one exception to catch.

    """
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as error:
        message = f"{path}: the component declaration could not be read ({error})"
        raise ImproperlyConfigured(message) from error
    except UnicodeDecodeError as error:
        # `tomllib.load` reads bytes and decodes them as UTF-8 itself, so a file
        # saved in another encoding fails inside the decode rather than inside
        # the parse -- and `UnicodeDecodeError` is a `ValueError`, not a
        # `TOMLDecodeError`. Uncaught it would walk straight past the one
        # exception every caller of this module is told to catch.
        message = f"{path}: the component declaration is not valid UTF-8 ({error})"
        raise ImproperlyConfigured(message) from error
    except tomllib.TOMLDecodeError as error:
        message = f"{path}: the component declaration is not valid TOML ({error})"
        raise ImproperlyConfigured(message) from error


def _refuse_unknown_keys(path: Path, table: dict[str, Any], permitted: frozenset[str], context: str) -> None:
    """Refuse a mapping carrying a key outside its closed set.

    This is where AD-28's placement rule is enforced rather than described: a
    disposition, an AD-25 parameter site, a preset or a feature surface written
    here is an `accelerator.toml` concern in a file that travels, and it fails
    here instead of being read by nothing and believed by its author. It applies
    at the top level and inside every table alike, because the wrong file is the
    wrong file at whatever depth the key was written.

    Args:
        path: The file the keys came from, named in the message.
        table: The parsed mapping.
        permitted: The keys the mapping may carry.
        context: How the message names the mapping -- `top-level`, or the table
            header as the file spells it.

    Raises:
        ImproperlyConfigured: When any key is outside `permitted`.

    """
    unknown = sorted(set(table) - permitted)
    if unknown:
        message = (
            f"{path}: unknown {context} key(s) {unknown}. `component.toml` carries only "
            f"{sorted(permitted)} there; a rule only the materializer needs belongs in `accelerator.toml` (AD-28)"
        )
        raise ImproperlyConfigured(message)


def _refuse_duplicates(path: Path, names: list[str], context: str) -> None:
    """Refuse a repeated identity within one array-of-tables.

    Args:
        path: The file the entries came from, named in the message.
        names: The identifying values, in declaration order.
        context: How the message names the key.

    Raises:
        ImproperlyConfigured: When a value appears more than once.

    """
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        message = (
            f"{path}: {context} declares {duplicated} more than once. Each entry is addressed by that value, "
            f"so a repeat leaves every reader silently picking one of two entries"
        )
        raise ImproperlyConfigured(message)


def _selected_features(path: Path, document: dict[str, Any]) -> frozenset[str]:
    """Return the selected features, refusing an unknown name or an invalid pairing.

    Args:
        path: The file the list came from, named in the messages.
        document: The parsed document.

    Returns:
        The selected features. Empty when the key is absent -- the *Minimal*
        preset selects no feature, which is a combination rather than an
        omission.

    Raises:
        ImproperlyConfigured: When a name falls outside `SELECTABLE_FEATURES`, or
            when `celery` is selected without `redis` (FR-26).

    """
    features = frozenset(_strings(path, document.get("selected_features", []), "selected_features"))

    unknown = sorted(features - SELECTABLE_FEATURES)
    if unknown:
        message = (
            f"{path}: selected_features names {unknown}, which is not among {sorted(SELECTABLE_FEATURES)}. "
            f"The server-rendered interface is immovable core and is not a feature (AD-29)"
        )
        raise ImproperlyConfigured(message)

    if CELERY_FEATURE in features and REDIS_FEATURE not in features:
        message = (
            f"{path}: selected_features selects {CELERY_FEATURE!r} without {REDIS_FEATURE!r}. "
            f"Celery's broker is Redis (FR-26), so the pairing is not one of the valid combinations"
        )
        raise ImproperlyConfigured(message)

    return features


def _database(path: Path, table: dict[str, Any]) -> DatabaseDeclaration:
    """Build one `[[databases]]` record.

    Args:
        path: The file the entry came from, named in any message.
        table: The parsed entry.

    Returns:
        The database declaration. `required` defaults to True when absent, which
        is AD-9's fail-closed reading: readiness treats a database as required
        unless this file declares it optional.

    Raises:
        ImproperlyConfigured: When the entry carries a key outside
            `DATABASE_KEYS`, a field has the wrong type, or the alias is blank.

    """
    _refuse_unknown_keys(path, table, DATABASE_KEYS, "[[databases]]")
    return DatabaseDeclaration(
        alias=_named(path, table.get("alias"), "[[databases]] alias"),
        required=_typed(path, table.get("required", True), bool, "[[databases]] required"),
        migrate=_strings(path, table.get("migrate", []), "[[databases]] migrate"),
    )


def _process(path: Path, table: dict[str, Any]) -> ProcessDeclaration:
    """Build one `[[processes]]` record.

    Args:
        path: The file the entry came from, named in any message.
        table: The parsed entry.

    Returns:
        The process declaration. `replicas` is None when absent, meaning the
        count is the platform's to choose rather than meaning zero.

    Raises:
        ImproperlyConfigured: When the entry carries a key outside
            `PROCESS_KEYS`, a field has the wrong type, a name or task is blank,
            the replica count is not a positive integer, or the replacement
            strategy is outside `REPLACEMENT_STRATEGIES`.

    """
    _refuse_unknown_keys(path, table, PROCESS_KEYS, "[[processes]]")
    return ProcessDeclaration(
        name=_named(path, table.get("name"), "[[processes]] name"),
        task=_named(path, table.get("task"), "[[processes]] task"),
        replicas=_replicas(path, table.get("replicas")),
        replacement=_replacement(path, table.get("replacement")),
    )


def _replicas(path: Path, value: object) -> int | None:
    """Return a fixed replica count, or None when the platform chooses.

    Args:
        path: The file the value came from, named in any message.
        value: The parsed value.

    Returns:
        The count, or None when the key is absent.

    Raises:
        ImproperlyConfigured: When the value is a boolean, is not an integer, or
            is below one.

    """
    if value is None:
        return None
    if isinstance(value, bool):
        # `bool` subclasses `int`, so `replicas = true` satisfies an isinstance
        # check against `int` and would be read as a fixed count of one. A flag
        # is not a count, and the author who meant one replica wrote `1`.
        message = f"{path}: [[processes]] replicas must be declared as int, found {value!r}"
        raise ImproperlyConfigured(message)

    count = _typed(path, value, int, "[[processes]] replicas")
    if count < 1:
        # Zero is not "the platform chooses" -- that is the absent key -- and it
        # is not a process model either: it declares a process type the platform
        # is told never to run, which every reader here would then reconcile
        # against a pixi task that does exist.
        message = f"{path}: [[processes]] replicas must be at least 1, found {count!r}"
        raise ImproperlyConfigured(message)
    return count


def _replacement(path: Path, value: object) -> str:
    """Return a replacement strategy from the closed set.

    Args:
        path: The file the value came from, named in any message.
        value: The parsed value.

    Returns:
        The strategy.

    Raises:
        ImproperlyConfigured: When the value is absent, is not a string, or is
            outside `REPLACEMENT_STRATEGIES`.

    """
    strategy = _typed(path, value, str, "[[processes]] replacement")
    if strategy not in REPLACEMENT_STRATEGIES:
        message = (
            f"{path}: [[processes]] replacement is {strategy!r}, which is not among "
            f"{sorted(REPLACEMENT_STRATEGIES)}. A strategy no deployment repository knows how to read is "
            f"refused here rather than passed through (AD-14)"
        )
        raise ImproperlyConfigured(message)
    return strategy


def _admin_process(path: Path, table: dict[str, Any]) -> AdminProcessDeclaration:
    """Build one `[[admin_processes]]` record.

    Args:
        path: The file the entry came from, named in any message.
        table: The parsed entry.

    Returns:
        The administrative-process declaration.

    Raises:
        ImproperlyConfigured: When the entry carries a key outside
            `ADMIN_PROCESS_KEYS`, a field has the wrong type, or a field is
            blank. The schedule is checked for emptiness and not against a closed
            set: `deployment-repository` is the one value anybody has named so
            far, and one known value is a value rather than a set.

    """
    _refuse_unknown_keys(path, table, ADMIN_PROCESS_KEYS, "[[admin_processes]]")
    return AdminProcessDeclaration(
        name=_named(path, table.get("name"), "[[admin_processes]] name"),
        task=_named(path, table.get("task"), "[[admin_processes]] task"),
        schedule=_named(path, table.get("schedule"), "[[admin_processes]] schedule"),
    )


def _tables(path: Path, document: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    """Return one array-of-tables, empty when absent.

    Args:
        path: The file the array came from, named in any message.
        document: The parsed document.
        key: The array-of-tables key.

    Returns:
        The entries, in declaration order.

    Raises:
        ImproperlyConfigured: When the value is not an array of tables.

    """
    entries = _typed(path, document.get(key, []), list, f"[[{key}]]")
    return tuple(_typed(path, entry, dict, f"[[{key}]] entry") for entry in entries)


def _strings(path: Path, value: object, context: str) -> tuple[str, ...]:
    """Return an array of strings as a tuple.

    Args:
        path: The file the value came from, named in any message.
        value: The parsed value.
        context: How the message names the key.

    Returns:
        The strings, in declaration order.

    Raises:
        ImproperlyConfigured: When the value is not an array of strings.

    """
    entries = _typed(path, value, list, context)
    return tuple(_typed(path, entry, str, f"{context} entry") for entry in entries)


def _named(path: Path, value: object, context: str) -> str:
    """Return an identifying string, refusing a blank one.

    Every field this guards -- a name, an alias, a task, a schedule owner -- is
    something a reader looks a thing up by. `alias = ""` parses, satisfies a type
    check and then addresses no database; the refusal belongs where the value is
    read rather than in each of the three consumers.

    Args:
        path: The file the value came from, named in any message.
        value: The parsed value.
        context: How the message names the key.

    Returns:
        The string, exactly as written.

    Raises:
        ImproperlyConfigured: When the value is absent, is not a string, or is
            empty or whitespace only.

    """
    name = _typed(path, value, str, context)
    if not name.strip():
        message = f"{path}: {context} is empty. It is what a reader addresses this entry by, so it must name something"
        raise ImproperlyConfigured(message)
    return name


def _typed[T](path: Path, value: object, expected: type[T], context: str) -> T:
    """Return a value of the expected type, or refuse.

    One raise site for every type failure in this module, so the message shape is
    the same wherever the malformed key is and so a reader counting refusal paths
    counts one.

    Args:
        path: The file the value came from, named in the message.
        value: The parsed value.
        expected: The type the declaration requires.
        context: How the message names the key.

    Returns:
        The value, narrowed to `expected`.

    Raises:
        ImproperlyConfigured: When the value is absent or of another type. One
            raise site, two readings of the same failure: TOML has no null, so a
            key reading as `None` was not written at all, and reporting that as
            `found None` would describe a declaration nobody can write and send
            its author looking for a null they did not type.

    """
    if isinstance(value, expected):
        return value
    found = "and was not declared" if value is None else f"but is {value!r}"
    message = f"{path}: {context} must be declared as {expected.__name__}, {found}"
    raise ImproperlyConfigured(message)
