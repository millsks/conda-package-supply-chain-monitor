"""Tests for the locality declaration AD-13 puts in `pixi.toml`.

Locality is declared by the pixi *environment*, not by a file in the source tree
and not by a task: `COMPONENT_RUNTIME=local` sits once in
`[feature.dev.activation.env]`, so the declaration is committed with the
manifest and a freshly cloned component runs with one command, while the
`default` environment declares nothing and reads *deployed* -- which is what the
golden base runs and what the release stage invokes.

Three prohibitions carry that, and none of them fails on its own:

* **No `COMPONENT_*` in the `default` environment's resolved activation env.**
  The golden base runs pixi, so that env is evaluated in production: a
  `COMPONENT_RUNTIME=local` reaching the deployed image would invert the
  fail-closed default and disarm every refusal built on it, silently. It also
  takes the deployment platform's own configmap out of sole control of the
  variable.
* **No `COMPONENT_PROCESS` in *any* activation env**, feature-scoped included.
  There it would make every management command declare itself a serving
  process, and `pixi run migrate` -- a release-stage step -- would refuse on the
  unapplied-migrations condition and deadlock the release.
* **No task declares `COMPONENT_RUNTIME` in its own `env`.** A task's `env`
  overrides the caller's environment (probed on pixi 0.70.2), so a task-level
  declaration could not be corrected by the platform. The single declaration
  site is the environment.

Platform-scoped tables are in scope throughout. `[target.<platform>.activation.env]`
and `[feature.<name>.target.<platform>.activation.env]` are honoured by pixi and
reach the process, so a scanner that read only the unscoped tables would let
`COMPONENT_RUNTIME = "local"` in `[target.linux-64.activation.env]` pass green
and ship in the production image.

Read with `tomllib` and asserted over the parsed structure, never over the raw
text: this manifest carries long comment blocks *about* `COMPONENT_RUNTIME`
beside the tables they constrain, and a substring search would be satisfied --
or broken -- by prose.

This is a unit test. It reads one committed repository file and its own process
environment, and opens no network, database or other filesystem surface.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PIXI_MANIFEST = REPO_ROOT / "pixi.toml"

# The prefix AD-13 keeps out of the deployed activation env. Matched as a prefix
# rather than as the two names, so a third `COMPONENT_*` fact invented later is
# covered on the day it is invented rather than on the day someone remembers
# this test. Matched case-insensitively: environment variables are
# case-insensitive on Windows, which is a declared platform here, so a
# `component_runtime` written in lower case would resolve there exactly as the
# upper-case spelling does.
COMPONENT_PREFIX = "COMPONENT_"

# The two names, restated rather than imported from `config.locality`: a test
# that reads the value it is checking asserts nothing about the manifest, and
# this file's whole job is to hold the manifest to the contract that module
# implements.
RUNTIME_VARIABLE = "COMPONENT_RUNTIME"
PROCESS_VARIABLE = "COMPONENT_PROCESS"
LOCAL = "local"

# The one table permitted to declare a `COMPONENT_*` variable, and the one
# variable it may declare.
DECLARATION_FEATURE = "dev"

# pixi's implicit feature: the unscoped `[activation.env]`, `[tasks]` and
# `[dependencies]` tables belong to it, and every environment includes it unless
# it sets `no-default-feature`.
DEFAULT_FEATURE = "default"

# The environments a developer runs in, and therefore the ones allowed to carry
# the `dev` feature and its declaration. `spike-storage` layers the dev feature
# deliberately (it is `dev` plus django-storages, for R-1's fitness spike), so
# it is a developer environment too. Everything else in `[environments]` is
# production-bound: Epic 8's six-environment matrix lands there, and each entry
# it adds has to stay out of this set or fail the assertion below.
DEVELOPER_ENVIRONMENTS: frozenset[str] = frozenset({"dev", "spike-storage"})

# The process types Epic 5 (AD-14) delivers as tasks of their own. They set
# `COMPONENT_PROCESS` in their own `env` and inherit *deployed*, so none of them
# may declare a runtime -- and no *other* task may declare a process type. None
# exists yet, which is why both assertions below are written to pass vacuously
# rather than to be added later.
SERVING_PROCESS_TASKS: frozenset[str] = frozenset({"web", "worker", "beat"})


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    """Return the parsed pixi manifest.

    Returns:
        The manifest, parsed from TOML.
    """
    with PIXI_MANIFEST.open("rb") as handle:
        parsed: dict[str, Any] = tomllib.load(handle)
    return parsed


def _feature_scopes(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return every feature scope in the manifest, including the implicit default one.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        Feature name -> the table that scopes it. The unscoped root is returned
        under `default`, which is the feature it belongs to.
    """
    scopes: dict[str, dict[str, Any]] = {DEFAULT_FEATURE: manifest}
    for name, feature in manifest.get("feature", {}).items():
        if isinstance(feature, dict):
            scopes[str(name)] = feature
    return scopes


def _activation_tables(manifest: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Return every activation-env table in the manifest, platform scopes included.

    Four shapes are walked: `[activation.env]`,
    `[target.<platform>.activation.env]`, `[feature.<name>.activation.env]` and
    `[feature.<name>.target.<platform>.activation.env]`. The platform-scoped
    pair is not hypothetical -- pixi honours it and it reaches the process, so
    omitting it would leave a hole that ships to production.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        Table location -> (the feature that owns it, the variables it declares).
    """
    tables: dict[str, tuple[str, dict[str, Any]]] = {}
    for feature, scope in _feature_scopes(manifest).items():
        prefix = "" if feature == DEFAULT_FEATURE else f"feature.{feature}."
        env = scope.get("activation", {}).get("env")
        if isinstance(env, dict):
            tables[f"[{prefix}activation.env]"] = (feature, env)
        for platform, target in scope.get("target", {}).items():
            platform_env = target.get("activation", {}).get("env")
            if isinstance(platform_env, dict):
                tables[f"[{prefix}target.{platform}.activation.env]"] = (feature, platform_env)
    return tables


def _activation_scripts(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return every activation *script* declaration in the manifest.

    An activation script is a second export route this module cannot read: it is
    a path to a shell script, and its contents are not part of the manifest. The
    manifest declares none today, and the assertion that uses this keeps it that
    way -- so the prohibitions above stay exhaustive rather than becoming a scan
    of one of two mechanisms.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        Table location -> the declared scripts.
    """
    scripts: dict[str, Any] = {}
    for feature, scope in _feature_scopes(manifest).items():
        prefix = "" if feature == DEFAULT_FEATURE else f"feature.{feature}."
        declared = scope.get("activation", {}).get("scripts")
        if declared is not None:
            scripts[f"[{prefix}activation].scripts"] = declared
        for platform, target in scope.get("target", {}).items():
            platform_scripts = target.get("activation", {}).get("scripts")
            if platform_scripts is not None:
                scripts[f"[{prefix}target.{platform}.activation].scripts"] = platform_scripts
    return scripts


def _task_tables(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return every task table in the manifest, keyed by where it lives.

    `[tasks]`, each `[feature.<name>.tasks]`, and the platform-scoped variants of
    both. The platform-scoped tables hold no tasks today; they are read anyway,
    because a task declared under one is as real as any other and would otherwise
    escape every assertion in this module.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        Table location -> {task name: task definition}.
    """
    tables: dict[str, dict[str, Any]] = {}
    for feature, scope in _feature_scopes(manifest).items():
        prefix = "" if feature == DEFAULT_FEATURE else f"feature.{feature}."
        tasks = scope.get("tasks")
        if isinstance(tasks, dict):
            tables[f"[{prefix}tasks]"] = tasks
        for platform, target in scope.get("target", {}).items():
            platform_tasks = target.get("tasks")
            if isinstance(platform_tasks, dict):
                tables[f"[{prefix}target.{platform}.tasks]"] = platform_tasks
    return tables


def _tasks(manifest: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Return every task in the manifest as (table location, name, definition).

    A list rather than a name-keyed mapping, deliberately. Keying by name lets a
    task declared in two tables overwrite its twin, and the shadowed definition
    then escapes every assertion that walks the mapping -- so a `migrate` with a
    forbidden `env` in `[feature.dev.tasks]` could hide behind the clean one in
    `[tasks]`. Every definition is asserted where it is declared.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        One entry per declaration, in manifest order.
    """
    return [
        (table, str(name), definition)
        for table, tasks in _task_tables(manifest).items()
        for name, definition in tasks.items()
    ]


def _task_env(definition: Any) -> dict[str, Any]:
    """Return the `env` table a task definition declares, or an empty one.

    A task written as a bare command string declares no `env` at all, which is
    the safe answer for both variables: absent locality means deployed, absent
    process type means not a serving process.

    Args:
        definition: One task's definition, in either legal form.

    Returns:
        The declared environment, or `{}` when the task declares none.
    """
    if not isinstance(definition, dict):
        return {}
    env = definition.get("env")
    return env if isinstance(env, dict) else {}


def _environment_features(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """Return the features each declared environment resolves.

    An environment entry is either a bare list of feature names or a table with
    a `features` key. Either way pixi adds the implicit `default` feature unless
    the entry sets `no-default-feature`, which is what makes the unscoped
    `[activation.env]` part of what `default` resolves.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        Environment name -> the features it resolves, `default` included.
    """
    resolved: dict[str, list[str]] = {}
    for name, entry in manifest.get("environments", {}).items():
        if isinstance(entry, dict):
            declared = [str(feature) for feature in entry.get("features", [])]
            implicit = [] if entry.get("no-default-feature", False) else [DEFAULT_FEATURE]
        else:
            declared = [str(feature) for feature in entry]
            implicit = [DEFAULT_FEATURE]
        resolved[str(name)] = implicit + declared
    return resolved


def _is_component_variable(name: str) -> bool:
    """Report whether a variable name is part of the `COMPONENT_*` contract.

    Args:
        name: The variable name as the manifest spells it.

    Returns:
        True when the name carries the prefix, in any casing.
    """
    return name.upper().startswith(COMPONENT_PREFIX)


def test_manifest_is_present() -> None:
    """The manifest resolves from this test file, so the assertions below mean something."""
    assert PIXI_MANIFEST.is_file()


def test_the_scanners_see_the_manifest_they_claim_to(manifest: dict[str, Any]) -> None:
    """The three readers find the tables this file is written against.

    Every prohibition here is an assertion that something is *absent*, so a
    reader that silently found nothing would pass all of them while checking
    nothing at all. This is the non-vacuity guard for the file.
    """
    assert "[activation.env]" in _activation_tables(manifest)
    assert "[feature.dev.activation.env]" in _activation_tables(manifest)
    assert "[tasks]" in _task_tables(manifest)
    assert DEFAULT_FEATURE in _environment_features(manifest)


def test_default_environment_activation_env_declares_no_component_variable(manifest: dict[str, Any]) -> None:
    """No `COMPONENT_*` variable reaches a production-bound environment (AC #3).

    The golden base runs pixi, so the activation env of whatever environment it
    installs is evaluated in production. A `COMPONENT_RUNTIME=local` that
    reached a deployed image would invert the fail-closed locality default and
    disarm every refusal built on it; nothing would break while it did. It would
    also displace the deployment platform's own configuration -- an OpenShift
    configmap or equivalent -- which is meant to be in sole control of the
    variable precisely because `default` declares nothing.

    Scoped to every environment that is not a developer environment, so today's
    `default` is covered and Epic 8's matrix is covered on the day it lands.
    """
    tables = _activation_tables(manifest)
    offenders: list[str] = []
    for environment, features in _environment_features(manifest).items():
        if environment in DEVELOPER_ENVIRONMENTS:
            continue
        offenders.extend(
            f"{variable} in {location}, resolved by the {environment!r} environment"
            for location, (feature, table) in tables.items()
            if feature in features
            for variable in table
            if _is_component_variable(variable)
        )

    assert not offenders, (
        f"these {COMPONENT_PREFIX}* variables reach a production-bound environment: {sorted(offenders)}. "
        f"Activation env is evaluated in production because the golden base runs pixi (AD-13). Locality is "
        f"declared once, in [feature.{DECLARATION_FEATURE}.activation.env], and nothing production-bound "
        f"includes that feature."
    )


def test_component_process_absent_from_every_activation_env(manifest: dict[str, Any]) -> None:
    """`COMPONENT_PROCESS` appears in no activation env anywhere (AC #3).

    Absolute, and independent of which environment resolves the table: a
    `COMPONENT_PROCESS` in *any* activation env makes every command run under it
    declare itself a serving process. `pixi run migrate` is one of those
    commands and it is a release-stage step, so it would refuse on the
    unapplied-migrations condition and deadlock the release. Serving processes
    declare it in their own task `env` (Epic 5, AD-14) and nowhere else.
    """
    offenders = sorted(
        location
        for location, (_feature, table) in _activation_tables(manifest).items()
        if any(variable.upper() == PROCESS_VARIABLE for variable in table)
    )
    assert not offenders, (
        f"{PROCESS_VARIABLE} is declared in these activation tables: {offenders}. "
        f"It belongs in the `env` of the serving-process tasks and nowhere else -- in an activation env it "
        f"makes every management command a serving process and deadlocks the release stage."
    )


def test_dev_feature_declares_local_runtime(manifest: dict[str, Any]) -> None:
    """The `dev` feature's activation env declares `COMPONENT_RUNTIME=local` (AC #1).

    The single declaration site, committed with the manifest, so a freshly
    cloned component is local from the first command with no untracked file to
    create. The value is pinned to exactly `local` -- stricter than
    `config.locality.is_local()`, which also accepts `LOCAL` and `" local "`.
    That is deliberate: the reader is forgiving so a hand-set variable behaves,
    while the manifest is held to one canonical spelling, and a `"dev"` that the
    reader would *not* accept fails loudly here rather than quietly making every
    developer path deployed.
    """
    tables = _activation_tables(manifest)
    location = f"[feature.{DECLARATION_FEATURE}.activation.env]"
    assert location in tables, (
        f"{location} is missing from pixi.toml. It is the one site AD-13 permits for the locality declaration."
    )

    _feature, env = tables[location]
    assert env.get(RUNTIME_VARIABLE) == LOCAL, (
        f"{location} declares {RUNTIME_VARIABLE} = {env.get(RUNTIME_VARIABLE)!r}, not {LOCAL!r}. "
        f"Every developer path resolves to the {DECLARATION_FEATURE} environment and inherits locality from "
        f"this one key."
    )


def test_no_task_declares_component_runtime(manifest: dict[str, Any]) -> None:
    """No task sets `COMPONENT_RUNTIME` in its own `env`, at any value (AC #1).

    The single declaration site is the environment. A task's `env` *overrides*
    the caller's, so a task-level declaration cannot be corrected by the
    deployment platform's configmap: `COMPONENT_RUNTIME=local` on `migrate`
    would make the production release stage read *local* and skip every
    stage-1 refusal, with no way out. This is the assertion that keeps the
    superseded per-task design from creeping back in one task at a time.
    """
    offenders = sorted(
        f"{name} = {env[variable]!r} in {table}"
        for table, name, definition in _tasks(manifest)
        for env in [_task_env(definition)]
        for variable in env
        if variable.upper() == RUNTIME_VARIABLE
    )
    assert not offenders, (
        f"these tasks declare {RUNTIME_VARIABLE} in their own `env`: {offenders}. "
        f"Locality is declared by the pixi environment, not by the task (AD-13) -- a task `env` overrides the "
        f"caller and takes the deployment platform out of the loop."
    )


def test_only_serving_process_tasks_declare_a_process_type(manifest: dict[str, Any]) -> None:
    """`COMPONENT_PROCESS` in a task `env` is confined to the serving processes.

    Epic 5's `web`, `worker` and `beat` are its only producers (AD-14). A
    `COMPONENT_PROCESS = "web"` on `migrate` would pass every other assertion in
    this file and reproduce verbatim the release deadlock AD-13 exists to
    prevent, so the confinement is asserted rather than assumed. Vacuous today:
    no task declares the variable at all.
    """
    offenders = sorted(
        f"{name} = {env[variable]!r} in {table}"
        for table, name, definition in _tasks(manifest)
        if name not in SERVING_PROCESS_TASKS
        for env in [_task_env(definition)]
        for variable in env
        if variable.upper() == PROCESS_VARIABLE
    )
    assert not offenders, (
        f"these non-serving tasks declare {PROCESS_VARIABLE}: {offenders}. "
        f"Only {sorted(SERVING_PROCESS_TASKS)} may declare a process type; on a management command it turns "
        f"that command into a serving process and deadlocks the release stage on the migrations refusal."
    )


def test_no_production_bound_environment_includes_the_dev_feature(manifest: dict[str, Any]) -> None:
    """Only developer environments carry the feature holding the declaration (AC #3).

    This is what keeps the narrowed prohibition honest. `COMPONENT_RUNTIME` is
    permitted in `[feature.dev.activation.env]` on the understanding that no
    production-bound environment resolves that feature; the moment one does, the
    declaration ships. Epic 8's six-environment matrix is where that becomes
    easy to get wrong, so the rule is in force before the matrix arrives.
    """
    environments = _environment_features(manifest)
    missing = sorted(DEVELOPER_ENVIRONMENTS - set(environments))
    assert not missing, (
        f"DEVELOPER_ENVIRONMENTS names environments pixi.toml does not declare: {missing}. "
        f"Remove them from the set in this module in the same change that removes the environment."
    )

    offenders = sorted(
        f"{environment} includes {DECLARATION_FEATURE}"
        for environment, features in environments.items()
        if environment not in DEVELOPER_ENVIRONMENTS and DECLARATION_FEATURE in features
    )
    assert not offenders, (
        f"these production-bound environments include the {DECLARATION_FEATURE!r} feature: {offenders}. "
        f"That feature carries {RUNTIME_VARIABLE} = {LOCAL!r}, so including it ships the locality declaration "
        f"into the deployed image and inverts the fail-closed default."
    )


def test_serving_process_tasks_declare_no_runtime(manifest: dict[str, Any]) -> None:
    """`web`, `worker` and `beat` inherit *deployed* and declare no runtime (AC #4).

    They arrive with Epic 5 (AD-14) and declare `COMPONENT_PROCESS` instead.
    Written to pass vacuously until then, so the rule is in force on the day the
    tasks land rather than added afterwards.
    """
    offenders = sorted(
        f"{name} = {env[variable]!r} in {table}"
        for table, name, definition in _tasks(manifest)
        if name in SERVING_PROCESS_TASKS
        for env in [_task_env(definition)]
        for variable in env
        if variable.upper() == RUNTIME_VARIABLE
    )
    assert not offenders, (
        f"these serving-process tasks declare a runtime: {offenders}. "
        f"A serving process is deployed by default and declares only {PROCESS_VARIABLE}; declaring a runtime "
        f"on one would make a deployed process claim to be local."
    )


def test_no_activation_script_offers_an_unchecked_export_route(manifest: dict[str, Any]) -> None:
    """No activation script exists, so the env-table scan above is the whole surface.

    `[activation] scripts` is the second way pixi exports variables into a
    resolved environment, and its contents live in a shell script this module
    cannot parse. The manifest declares none. Asserting that keeps the
    prohibitions exhaustive: the day someone adds one, this fails and the check
    has to be extended rather than quietly bypassed by an `export
    COMPONENT_RUNTIME=local` in a file nothing reconciles.
    """
    declared = _activation_scripts(manifest)
    assert not declared, (
        f"pixi.toml declares activation scripts: {sorted(declared)}. "
        f"A script can export {COMPONENT_PREFIX}* variables that the activation-env assertions in this module "
        f"cannot see -- extend them to cover the script's contents, or drop the script."
    )


def test_the_declared_runtime_is_in_force_in_this_process() -> None:
    """The declaration actually reaches the process, not merely the manifest (AC #1).

    Every assertion above reads TOML, which proves what is *declared* and
    nothing about what pixi does with it. Feature-scoped activation env is the
    mechanism the whole design now rests on, so the two halves are split the way
    `COVERAGE_CORE` already splits them here -- declared in
    `test_coverage_policy.py`, in force in `test_coverage_measurement.py`.

    This suite runs in the `dev` environment (`pixi run test`, `pixi run
    test-cov`, and `pixi run -e dev -- pytest` alike), so the variable is
    present. A failure here means either the declaration is gone or pytest was
    started outside the pixi environment, which no supported route does.
    """
    assert os.environ.get(RUNTIME_VARIABLE) == LOCAL, (
        f"{RUNTIME_VARIABLE} is {os.environ.get(RUNTIME_VARIABLE)!r} in this process, not {LOCAL!r}. "
        f"The suite runs in the {DECLARATION_FEATURE} environment, whose activation env declares it; if this "
        f"fails, either the declaration was removed or pytest was started outside `pixi run`."
    )
