"""Cadence and the inherited limits are not properties of a task declaration.

Two of `CPM-EVIDENCE-S04`'s acceptance criteria are about what a task decorator
may *not* say, and both are invisible failures rather than loud ones.

**A schedule written into a decorator cannot be changed without a deploy**, which
is what `CPM-NFR-2` forbids and what `CPM-AD-20` answers by putting every cadence
in `django_celery_beat`'s `DatabaseScheduler` -- already configured at
`config/settings/base.py`. A `@periodic_task(run_every=...)` or a
`@shared_task(schedule=crontab(...))` looks like configuration, works on the day
it is written, and is then a code change every time an operator wants the sweep
an hour earlier. `app.conf.beat_schedule = {...}` written anywhere but settings is
the same decision spelled as an assignment.

**A task that raises the inherited time limits has changed the wrong thing.**
`CELERY_TASK_TIME_LIMIT` is five minutes and `CELERY_TASK_SOFT_TIME_LIMIT` is
sixty seconds, both inherited, and `CPM-AD-9` is explicit that work exceeding
them is chunked per package rather than given a longer limit. A per-task
`time_limit=900` is how a rate-limited sweep over ten thousand packages becomes
one task holding a worker slot for fifteen minutes, and `CPM-AD-23`'s
per-package transaction boundary stops being reachable.

**Both rules are enforced on both surfaces, and neither surface would do alone.**
Each rule reaches celery two ways -- through a task declaration, and through a
configuration assignment -- and an audit that caught a limit only in a decorator
while catching a cadence in both is one an `app.conf.task_time_limit = 900`
walks straight past. So the decorator sweep covers `time_limit` and `schedule`
alike, and the assignment sweep covers `CELERY_BEAT_SCHEDULE` and
`CELERY_TASK_TIME_LIMIT` alike.

**Matched on the parsed syntax tree, not by text search**, for the reason
`tests/unit/django_apps/test_clock_audit.py` gives: prose about the prohibition
-- this docstring included -- must not itself be an offence, and a decorator's
keyword has to be distinguishable from a settings key that means the opposite.
Local bindings are resolved back to the statement that made them, import and
assignment alike, so both `from celery import shared_task as job` and
`job = shared_task` are seen; `@app.task(...)` is matched on the *receiver* as
well as the attribute, because `task` is an ordinary word and somebody else's
`@router.task(...)` is not this product's to police.

**And the registry is swept as well as the source**, because a source scan can
only see spellings it knows. `@shared_task(**TASK_OPTIONS)` puts a `time_limit`
on a task with no `time_limit` written anywhere in the decorator, and an option
inherited from a base class is not in the scanned file at all. Whatever put it
there, it is an attribute on the task object by the time the registry sweep
below reads it. The two are complementary rather than redundant: the registry
cannot see a module nothing imported, and the source cannot see an option it
cannot resolve.

**The one place a schedule or a limit may be declared is `config/settings/`.**
`CELERY_BEAT_SCHEDULE` is on the platform's `CONTRIBUTABLE_KEYS` roster and the
two inherited limits are declared in `base.py`, so settings is where both belong.
The permitted location is a predicate with its own case below rather than a
directory quietly skipped in the walk -- and because it *is* a carve-out,
`tests/unit/test_settings.py` reads all four settings modules for a cadence or a
raised limit, which is the half this file cannot cover.

Reads and parses repository files, and reads the task registry: no database, no
network, no subprocess.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING
from typing import Final

import pytest

from config.celery_app import app
from tests.celery_tasks import product_task_names
from tests.celery_tasks import registered_tasks
from tests.source_scan import SRC_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse
from tests.source_scan import project_files

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

#: The decorators that turn a function into a celery task wherever they appear.
#: `shared_task` is the app-agnostic form this repository already uses;
#: `periodic_task` is celery's retired scheduling decorator and is the single most
#: direct spelling of the thing `CPM-AD-20` forbids.
BARE_TASK_DECORATORS: Final[frozenset[str]] = frozenset({"periodic_task", "shared_task"})

#: The attribute a celery *application* offers, and the receivers it is
#: recognised on.
#:
#: `@app.task(...)` is how a task is declared against a named application, and
#: `app` is what `config/celery_app.py` calls the one this component has. The
#: receiver is checked rather than the attribute alone, because `task` is an
#: ordinary word: a third-party `@router.task(...)` or `@queue.task(...)` carrying
#: a `time_limit` of its own is not a celery task and failing the gate on it would
#: be the audit describing a rule this architecture does not have. The cost is
#: stated rather than hidden -- an application bound to some fourth name escapes
#: the source sweep -- and it is the registry sweep below that closes it, because
#: a task declared any way at all still arrives in `app.tasks`.
APPLICATION_TASK_ATTRIBUTE: Final[str] = "task"
CELERY_APPLICATION_RECEIVERS: Final[frozenset[str]] = frozenset({"app", "celery", "celery_app"})

#: The distribution the bare decorators are imported from. Used to resolve
#: `from celery import shared_task as job`, which a table of literal names cannot
#: see.
TASK_DECORATOR_PACKAGE: Final[str] = "celery"

#: The two limits `CPM-AD-9` fixes at the inherited values. A task declaring
#: either has raised a limit instead of chunking the work.
BANNED_LIMIT_KEYWORDS: Final[frozenset[str]] = frozenset({"soft_time_limit", "time_limit"})

#: The keywords that carry a cadence into a decorator.
BANNED_SCHEDULE_KEYWORDS: Final[frozenset[str]] = frozenset({"run_every", "schedule"})

#: Every keyword a task decorator may not carry, in one set so the two rules are
#: read in one pass and reported once each.
BANNED_DECORATOR_KEYWORDS: Final[frozenset[str]] = BANNED_LIMIT_KEYWORDS | BANNED_SCHEDULE_KEYWORDS

#: The schedule constructors, matched wherever they appear in a decorator's
#: arguments rather than only under a known keyword: `@periodic_task(crontab(...))`
#: is positional, and a custom decorator wrapping celery's own takes whatever
#: keyword it likes. A constructor sitting under an already-reported keyword is
#: not counted twice -- see `decorator_offences`.
SCHEDULE_CONSTRUCTORS: Final[frozenset[str]] = frozenset({"crontab", "schedule", "solar"})

#: The names that hold a beat schedule. `beat_schedule` is celery's own
#: configuration key and the attribute spelling `app.conf.beat_schedule`;
#: `CELERY_BEAT_SCHEDULE` is the namespaced settings spelling the platform
#: allowlist permits a domain application to contribute to.
SCHEDULE_ASSIGNMENT_NAMES: Final[frozenset[str]] = frozenset({"CELERY_BEAT_SCHEDULE", "beat_schedule"})

#: The names that hold a time limit, and the reason this set exists at all.
#:
#: The two rules were enforced asymmetrically: cadence was caught in a decorator
#: *and* as a configuration assignment, while a limit was caught only in a
#: decorator -- so `app.conf.task_time_limit = 900`, or a bare
#: `CELERY_TASK_TIME_LIMIT = 900` in any module outside settings, raised the
#: inherited limit with every gate green. Both spellings of both limits are here;
#: the namespaced pair is what `config/settings/base.py` legitimately assigns,
#: which is why settings is the permitted location for these as well.
LIMIT_ASSIGNMENT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "CELERY_TASK_SOFT_TIME_LIMIT",
        "CELERY_TASK_TIME_LIMIT",
        "task_soft_time_limit",
        "task_time_limit",
    }
)

#: Every configuration name whose assignment belongs in settings and nowhere
#: else.
CONFIGURATION_ASSIGNMENT_NAMES: Final[frozenset[str]] = SCHEDULE_ASSIGNMENT_NAMES | LIMIT_ASSIGNMENT_NAMES

#: The class attributes a `Task` subclass may not carry. A class-based task is
#: celery's other declaration form, and `time_limit` written as a class attribute
#: is the decorator keyword with the decorator removed.
BANNED_TASK_CLASS_ATTRIBUTES: Final[frozenset[str]] = BANNED_DECORATOR_KEYWORDS

#: The attributes the *registry* sweep reads off a task object.
#:
#: The same four names, because celery puts every one of them on the task class
#: whatever spelling declared it -- a decorator keyword, an unpacked options
#: dictionary, a class attribute, or an inherited base. That is the whole reason
#: the registry is swept as well as the source: a scan of decorator keywords
#: cannot see `@shared_task(**TASK_OPTIONS)`, and the task object cannot hide it.
REGISTRY_DECLARATION_ATTRIBUTES: Final[tuple[str, ...]] = tuple(sorted(BANNED_DECORATOR_KEYWORDS))

#: How a class-based task is recognised: a base class whose final segment ends
#: here. `celery.Task`, `celery.app.task.Task` and a project's own
#: `CollectorTask` all match, and no ordinary class does.
TASK_BASE_CLASS_SUFFIX: Final[str] = "Task"

#: The method that writes configuration without an assignment statement, and the
#: one this repository would plausibly see: `app.conf.update(beat_schedule=...)`.
CONFIGURATION_UPDATE_METHOD: Final[str] = "update"

#: The one directory a schedule or a limit may be assigned in, relative to `src/`.
#: Settings is where a `CELERY_BEAT_SCHEDULE` contribution lands and where the
#: inherited limits are declared, and it is the only place a value read at process
#: start belongs. Stated as a permitted location with a case of its own, rather
#: than pruned from the walk where nobody would see it.
PERMITTED_SCHEDULE_DECLARATION_DIRECTORY: Final[str] = "config/settings"

#: The module that proves the decorator finder still finds decorators. It carries
#: the repository's one real `@shared_task()`, and it is the case that goes red if
#: the matcher stops recognising the plainest spelling there is.
A_MODULE_DECLARING_A_TASK: Final[str] = "django_service/users/tasks.py"

# Synthetic modules the detector is measured against. Source text parsed here
# rather than files on disk: a fixture module under `src/` would be found by the
# scan itself and would need an exemption of its own -- the trade
# `test_clock_audit.py` records and takes for the same reason.

A_HARD_LIMIT_ON_A_TASK = """
from celery import shared_task


@shared_task(name="cpm.collect.slow", time_limit=900)
def collect_slowly() -> None: ...
"""

A_SOFT_LIMIT_ON_A_TASK = """
from celery import shared_task


@shared_task(name="cpm.collect.slow", soft_time_limit=600)
def collect_slowly() -> None: ...
"""

A_LIMIT_ON_AN_APPLICATION_TASK = """
from config.celery_app import app


@app.task(name="cpm.policy.slow", time_limit=900)
def score_slowly() -> None: ...
"""

A_LIMIT_UNDER_AN_ALIASED_DECORATOR = """
from celery import shared_task as job


@job(name="cpm.verify.slow", time_limit=900)
def build_slowly() -> None: ...
"""

A_CRONTAB_IN_A_DECORATOR = """
from celery import shared_task
from celery.schedules import crontab


@shared_task(name="cpm.collect.daily", schedule=crontab(hour=2, minute=0))
def collect_daily() -> None: ...
"""

A_POSITIONAL_CRONTAB = """
from celery.task import periodic_task
from celery.schedules import crontab


@periodic_task(crontab(hour=2, minute=0))
def collect_daily() -> None: ...
"""

A_RUN_EVERY_INTERVAL = """
from datetime import timedelta

from celery.task import periodic_task


@periodic_task(run_every=timedelta(hours=1))
def collect_hourly() -> None: ...
"""

A_BEAT_SCHEDULE_ASSIGNED_IN_A_MODULE = """
from celery.schedules import crontab

beat_schedule = {"daily": {"task": "cpm.collect.daily", "schedule": crontab(hour=2)}}
"""

A_BEAT_SCHEDULE_ASSIGNED_ON_THE_APPLICATION = """
from config.celery_app import app

app.conf.beat_schedule = {"daily": {"task": "cpm.collect.daily", "schedule": 3600}}
"""

A_NAMESPACED_BEAT_SCHEDULE_ASSIGNED_IN_A_MODULE = """
CELERY_BEAT_SCHEDULE = {"daily": {"task": "cpm.collect.daily", "schedule": 3600}}
"""

AN_ORDINARY_TASK = """
from celery import shared_task


@shared_task(name="cpm.collect.pypi_release")
def collect_pypi_release(package_id: int) -> None: ...
"""

A_TASK_WITH_A_RETRY_POLICY = """
from celery import shared_task


@shared_task(name="cpm.collect.pypi_release", autoretry_for=(OSError,), max_retries=5, retry_backoff=True)
def collect_pypi_release(package_id: int) -> None: ...
"""

A_FUNCTION_THAT_IS_NOT_A_TASK = """
from functools import cache


@cache
def schedule(time_limit: int = 900) -> int:
    return time_limit
"""

A_PARAMETER_NAMED_LIKE_A_LIMIT = """
def chunk(packages: list[int], soft_time_limit: int) -> None: ...


chunk([], soft_time_limit=60)
"""

A_LIMIT_UNDER_A_DECORATOR_ALIASED_BY_ASSIGNMENT = """
from celery import shared_task

job = shared_task


@job(name="cpm.verify.slow", time_limit=900)
def build_slowly() -> None: ...
"""

OPTIONS_UNPACKED_INTO_A_DECORATOR = """
from celery import shared_task

TASK_OPTIONS = {"time_limit": 900}


@shared_task(name="cpm.collect.slow", **TASK_OPTIONS)
def collect_slowly() -> None: ...
"""

A_SCHEDULE_SET_THROUGH_UPDATE = """
from config.celery_app import app

app.conf.update(beat_schedule={"daily": {"task": "cpm.collect.daily", "schedule": 3600}})
"""

A_SCHEDULE_SET_THROUGH_A_SUBSCRIPT = """
from config.celery_app import app

app.conf["beat_schedule"] = {"daily": {"task": "cpm.collect.daily", "schedule": 3600}}
"""

A_LIMIT_ASSIGNED_ON_THE_APPLICATION = """
from config.celery_app import app

app.conf.task_time_limit = 900
"""

A_NAMESPACED_LIMIT_ASSIGNED_IN_A_MODULE = """
CELERY_TASK_SOFT_TIME_LIMIT = 600
"""

A_CLASS_BASED_TASK_CARRYING_A_LIMIT = """
from celery import Task


class SlowCollector(Task):
    name = "cpm.collect.slow"
    time_limit = 900
"""

A_CLASS_BASED_TASK_CARRYING_A_CADENCE = """
from celery import Task


class DailyCollector(Task):
    name = "cpm.collect.daily"
    run_every = 86400
"""

A_SCHEDULE_KEYWORD_HOLDING_A_SCHEDULE_CALL = """
from celery import shared_task
from celery.schedules import schedule


@shared_task(name="cpm.collect.daily", schedule=schedule(3600))
def collect_daily() -> None: ...
"""

A_THIRD_PARTY_TASK_DECORATOR = """
from some_other_library import router


@router.task(time_limit=900, schedule="whenever")
def do_something() -> None: ...
"""

A_PLAIN_CLASS_WITH_A_LIMIT_ATTRIBUTE = """
class ChunkPolicy:
    time_limit = 900
"""

PROSE_ONLY = '''
"""Nothing here sets time_limit or crontab(...); it only says so."""
'''


def task_decorator_bindings(tree: ast.Module) -> set[str]:
    """Return every local name bound to a task decorator, by import or assignment.

    Args:
        tree: The parsed module.

    Returns:
        The local names -- `job` for both `from celery import shared_task as job`
        and `job = shared_task` -- so a renamed decorator is still recognised.
        Resolved from the statement that made the binding rather than assumed
        from the spelling, which is the same argument
        `test_clock_audit.py::receiver_bindings` records. The assignment form is
        here because alias-by-import alone leaves the obvious two-line evasion
        open, and it is exactly what somebody writes after being told the import
        alias is seen.

    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            if node.module.split(".")[0] != TASK_DECORATOR_PACKAGE:
                continue
            bound.update(alias.asname or alias.name for alias in node.names if alias.name in BARE_TASK_DECORATORS)
    # A second pass, because an assignment can only be resolved once the imports
    # are known and `ast.walk` gives no ordering guarantee.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not _names_a_task_decorator(node.value, bound):
            continue
        bound.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return bound


def _names_a_task_decorator(node: ast.expr, bound: set[str]) -> bool:
    """Report whether an expression names a celery task decorator.

    Args:
        node: The expression -- a decorator, or the right-hand side of an
            assignment that might alias one.
        bound: The local names already known to hold a task decorator.

    Returns:
        True for `shared_task` and `periodic_task` however they were bound, and
        for `task` reached through a receiver that looks like a celery
        application. See `CELERY_APPLICATION_RECEIVERS` for why the receiver is
        checked rather than the attribute alone.

    """
    spelled = dotted_name(node)
    if not spelled:
        return False
    receiver, _, attribute = spelled.rpartition(".")
    if spelled in bound or attribute in BARE_TASK_DECORATORS:
        return True
    return attribute == APPLICATION_TASK_ATTRIBUTE and receiver.rpartition(".")[2] in CELERY_APPLICATION_RECEIVERS


def task_decorators(tree: ast.Module) -> list[ast.expr]:
    """Return every decorator in one module that declares a celery task.

    Args:
        tree: The parsed module.

    Returns:
        The decorator expressions, called (`@shared_task(...)`) and bare
        (`@shared_task`) alike.

    """
    bound = task_decorator_bindings(tree)
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        found.extend(
            decorator
            for decorator in node.decorator_list
            if _names_a_task_decorator(decorator.func if isinstance(decorator, ast.Call) else decorator, bound)
        )
    return found


def decorator_offences(tree: ast.Module) -> list[str]:
    """Return every limit and every cadence written into a task declaration.

    Args:
        tree: The parsed module.

    Returns:
        One `line: form` string per offence, the form spelled canonically --
        `time_limit=`, `crontab(...) in a task decorator` -- so a failure names
        the decision rather than the line it happened to land on. Covers the
        decorator form and the class-attribute form a `Task` subclass uses.

    """
    found: list[str] = []
    for decorator in task_decorators(tree):
        if not isinstance(decorator, ast.Call):
            continue
        # An option dictionary unpacked into the decorator cannot be read here at
        # all -- `**TASK_OPTIONS` may hold a `time_limit` and this scan would see
        # a decorator with no keywords. It is reported rather than ignored: the
        # options of a task declaration are meant to be legible, and the registry
        # sweep below is the only other thing that would ever catch it.
        found.extend(
            f"{decorator.lineno}: ** unpacked into a task decorator"
            for keyword in decorator.keywords
            if keyword.arg is None
        )
        reported = {
            id(node)
            for keyword in decorator.keywords
            if keyword.arg in BANNED_DECORATOR_KEYWORDS
            for node in ast.walk(keyword.value)
        }
        found.extend(
            f"{decorator.lineno}: {keyword.arg}="
            for keyword in decorator.keywords
            if keyword.arg in BANNED_DECORATOR_KEYWORDS
        )
        # Skipping what a banned keyword already reported is what keeps
        # `schedule=schedule(3600)` one decision rather than two: `schedule` is
        # both a keyword and a constructor, and reporting it twice is the
        # duplication `_ordered` exists to prevent.
        found.extend(
            f"{child.lineno}: {constructor}(...) in a task decorator"
            for child in ast.walk(decorator)
            if isinstance(child, ast.Call)
            and id(child) not in reported
            and (constructor := dotted_name(child.func).rpartition(".")[2]) in SCHEDULE_CONSTRUCTORS
        )
    found.extend(_task_class_attributes(tree))
    return _ordered(found)


def _task_class_attributes(tree: ast.Module) -> list[str]:
    """Return every banned class attribute on a class-based task.

    Args:
        tree: The parsed module.

    Returns:
        One `line: form` string per attribute. A class-based task is celery's
        other declaration form and carries its options as class attributes rather
        than as decorator keywords, so `time_limit = 900` on a `Task` subclass is
        the decorator keyword with the decorator taken away -- and was invisible
        to a scan that read only decorators.

    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(dotted_name(base).rpartition(".")[2].endswith(TASK_BASE_CLASS_SUFFIX) for base in node.bases):
            continue
        for statement in node.body:
            targets = statement.targets if isinstance(statement, ast.Assign) else []
            if isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            found.extend(
                f"{statement.lineno}: {target.id} on a task class"
                for target in targets
                if isinstance(target, ast.Name) and target.id in BANNED_TASK_CLASS_ATTRIBUTES
            )
    return found


def configuration_assignments(tree: ast.Module) -> list[str]:
    """Return every schedule or limit this module writes into celery's configuration.

    Args:
        tree: The parsed module.

    Returns:
        One `line: form` string per write, covering the plain name, the
        namespaced settings key, the `app.conf.beat_schedule` attribute spelling,
        the `app.conf["beat_schedule"]` subscript, and the keyword form
        `app.conf.update(beat_schedule=...)`. The last two are writes with no
        assignment target at all, which is what a scan reading only `ast.Assign`
        misses.

    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and dotted_name(node.func).rpartition(".")[2] == CONFIGURATION_UPDATE_METHOD:
            found.extend(
                f"{node.lineno}: {keyword.arg}= via {CONFIGURATION_UPDATE_METHOD}()"
                for keyword in node.keywords
                if keyword.arg in CONFIGURATION_ASSIGNMENT_NAMES
            )
            found.extend(
                f"{node.lineno}: {key.value}= via {CONFIGURATION_UPDATE_METHOD}()"
                for argument in node.args
                if isinstance(argument, ast.Dict)
                for key in argument.keys
                if isinstance(key, ast.Constant) and key.value in CONFIGURATION_ASSIGNMENT_NAMES
            )
            continue
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        for target in targets:
            assigned = _assigned_name(target)
            if assigned in CONFIGURATION_ASSIGNMENT_NAMES:
                found.append(f"{node.lineno}: {assigned}=")
    return _ordered(found)


def _assigned_name(target: ast.expr) -> str:
    """Return the configuration name an assignment target writes.

    Args:
        target: The assignment target.

    Returns:
        The final segment of a name or attribute chain, the literal key of a
        string subscript (`app.conf["beat_schedule"]`), or `""` for anything
        else.

    """
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Subscript):
        return (
            target.slice.value if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str) else ""
        )
    return dotted_name(target).rpartition(".")[2]


def declaration_offences(tree: ast.Module) -> list[str]:
    """Return every offence of either rule in one module.

    Args:
        tree: The parsed module.

    Returns:
        The declaration offences and the configuration assignments together, in
        line order. The two are separate above because they apply to different
        sets of modules -- a schedule and the inherited limits are permitted in
        settings, and a per-task limit is permitted nowhere -- and joined here
        because the synthetic cases below measure the detector as a whole.

    """
    return _ordered(decorator_offences(tree) + configuration_assignments(tree))


def _ordered(found: list[str]) -> list[str]:
    """Return offences de-duplicated and sorted by the line they were found on.

    Args:
        found: The `line: form` strings collected by a detector.

    Returns:
        The same strings, each once, in line order. `ast.walk` reaches a nested
        node through more than one path in some shapes, and a report that named
        the same decision twice would read as two.

    """
    return sorted(set(found), key=lambda entry: (int(entry.split(":", 1)[0]), entry))


#: Every module under `src/` the rules apply to, migrations excluded for the
#: reason `tests/source_scan.py` records: generated code is not a declaration
#: anybody made.
SUBJECT_MODULES: Final[tuple[Path, ...]] = project_files(SRC_ROOT, skip_migrations=True)

#: The subject modules a schedule or a limit may *not* be assigned in.
MODULES_OUTSIDE_SETTINGS: Final[tuple[Path, ...]] = tuple(
    path
    for path in SUBJECT_MODULES
    if not path.relative_to(SRC_ROOT).as_posix().startswith(f"{PERMITTED_SCHEDULE_DECLARATION_DIRECTORY}/")
)


def test_the_scan_reaches_the_module_that_declares_a_task() -> None:
    """The anti-vacuity guard: there is a task decorator in view.

    A scan that had stopped reaching `src/django_service/` -- an exclusion
    widened, a walk that lost a directory -- would report a clean repository and
    pass every assertion below while looking at nothing that could ever fail.
    """
    relative = {path.relative_to(SRC_ROOT).as_posix() for path in SUBJECT_MODULES}

    assert A_MODULE_DECLARING_A_TASK in relative


def test_the_decorator_finder_finds_the_repositorys_own_task() -> None:
    """The other half of the guard: the looking finds something.

    `django_service/users/tasks.py` carries `@shared_task()`, the plainest
    spelling there is. If the matcher stopped recognising it, every case below
    would still pass -- on a repository the detector could no longer see a single
    task in.
    """
    assert task_decorators(parse(SRC_ROOT / A_MODULE_DECLARING_A_TASK)) != []


def test_the_settings_directory_the_exclusion_names_exists() -> None:
    """A permitted location that named nothing would exempt nothing, silently.

    Asserted both ways: the directory is real, and excluding it actually removed
    modules from the sweep -- a prefix that matched nothing would leave the case
    below testing the same set under a different name.
    """
    assert (SRC_ROOT / PERMITTED_SCHEDULE_DECLARATION_DIRECTORY).is_dir()
    assert len(MODULES_OUTSIDE_SETTINGS) < len(SUBJECT_MODULES)


@pytest.mark.parametrize(
    "path",
    SUBJECT_MODULES,
    ids=lambda path: str(path.relative_to(SRC_ROOT)),
)
def test_no_task_declaration_carries_a_limit_or_a_cadence(path: Path) -> None:
    """AC 2 and AC 3, per module so a violation names the file that introduced it.

    No exemption table, because there is nothing to exempt: the repository's one
    task carries neither, and a task that needs longer than five minutes is a
    task that needs chunking (`CPM-AD-9`). An entry added here would be a
    decision, and it would need the argument that goes with one.
    """
    relative = path.relative_to(SRC_ROOT).as_posix()

    assert decorator_offences(parse(path)) == [], (
        f"{relative} declares a limit or a cadence on a task (CPM-AD-9, CPM-AD-20)"
    )


@pytest.mark.parametrize(
    "path",
    MODULES_OUTSIDE_SETTINGS,
    ids=lambda path: str(path.relative_to(SRC_ROOT)),
)
def test_no_module_outside_settings_assigns_a_schedule_or_a_limit(path: Path) -> None:
    """Cadence and the limits are configuration, not values a module writes at import.

    `CELERY_BEAT_SCHEDULE` in settings is the platform's contributable key and is
    read once at process start; the same dictionary written into a task module,
    or assigned onto `app.conf` at import time, is a schedule that no operator
    can change and that no two processes are guaranteed to agree on.

    The limits are here for the same reason and were the asymmetry worth
    correcting: a decorator carrying `time_limit=900` was caught, while
    `app.conf.task_time_limit = 900` in any module outside settings raised the
    same limit for every task in the process with every gate green.
    """
    relative = path.relative_to(SRC_ROOT).as_posix()

    assert configuration_assignments(parse(path)) == [], (
        f"{relative} assigns a schedule or a limit outside "
        f"{PERMITTED_SCHEDULE_DECLARATION_DIRECTORY} (CPM-AD-9, CPM-AD-20)"
    )


@pytest.mark.parametrize(
    "source",
    [
        A_HARD_LIMIT_ON_A_TASK,
        A_SOFT_LIMIT_ON_A_TASK,
        A_LIMIT_ON_AN_APPLICATION_TASK,
        A_LIMIT_UNDER_AN_ALIASED_DECORATOR,
        A_CRONTAB_IN_A_DECORATOR,
        A_POSITIONAL_CRONTAB,
        A_RUN_EVERY_INTERVAL,
        A_BEAT_SCHEDULE_ASSIGNED_IN_A_MODULE,
        A_BEAT_SCHEDULE_ASSIGNED_ON_THE_APPLICATION,
        A_NAMESPACED_BEAT_SCHEDULE_ASSIGNED_IN_A_MODULE,
        A_LIMIT_UNDER_A_DECORATOR_ALIASED_BY_ASSIGNMENT,
        OPTIONS_UNPACKED_INTO_A_DECORATOR,
        A_SCHEDULE_SET_THROUGH_UPDATE,
        A_SCHEDULE_SET_THROUGH_A_SUBSCRIPT,
        A_LIMIT_ASSIGNED_ON_THE_APPLICATION,
        A_NAMESPACED_LIMIT_ASSIGNED_IN_A_MODULE,
        A_CLASS_BASED_TASK_CARRYING_A_LIMIT,
        A_CLASS_BASED_TASK_CARRYING_A_CADENCE,
    ],
    ids=[
        "hard-limit",
        "soft-limit",
        "app-task-limit",
        "aliased-decorator",
        "crontab-keyword",
        "crontab-positional",
        "run-every",
        "beat-schedule-name",
        "beat-schedule-attribute",
        "namespaced-beat-schedule",
        "decorator-aliased-by-assignment",
        "unpacked-options",
        "schedule-through-update",
        "schedule-through-subscript",
        "limit-on-the-application",
        "namespaced-limit",
        "task-class-limit",
        "task-class-cadence",
    ],
)
def test_the_detector_matches_every_banned_form(source: str) -> None:
    """Eighteen spellings, because a detector that knew one has a door in it.

    Each of the last eight is what somebody writes *after* being told about one
    of the first ten: the decorator aliased by assignment rather than by import,
    the options moved into a dictionary the decorator unpacks, the schedule set
    through `update()` or a subscript rather than by assignment, the limit raised
    on `app.conf` instead of on the task, and the whole declaration moved to a
    `Task` subclass where there is no decorator to inspect at all.
    """
    assert declaration_offences(ast.parse(source)) != []


def test_a_schedule_keyword_holding_a_schedule_call_is_one_offence() -> None:
    """`schedule` is both a banned keyword and a schedule constructor.

    Reported twice, it reads as two decisions in a failure message and inflates
    every count an assertion might make -- the duplication `_ordered` exists to
    prevent, arriving from two detectors rather than from one walking a node
    twice. A constructor sitting inside an already-reported keyword's value is
    skipped, and the keyword is what gets named.
    """
    offences = declaration_offences(ast.parse(A_SCHEDULE_KEYWORD_HOLDING_A_SCHEDULE_CALL))

    assert len(offences) == 1
    assert offences[0].endswith("schedule=")


@pytest.mark.parametrize(
    "source",
    [
        AN_ORDINARY_TASK,
        A_TASK_WITH_A_RETRY_POLICY,
        A_FUNCTION_THAT_IS_NOT_A_TASK,
        A_PARAMETER_NAMED_LIKE_A_LIMIT,
        A_THIRD_PARTY_TASK_DECORATOR,
        A_PLAIN_CLASS_WITH_A_LIMIT_ATTRIBUTE,
        PROSE_ONLY,
    ],
    ids=[
        "plain-task",
        "retry-policy",
        "not-a-task",
        "parameter-name",
        "third-party-task-decorator",
        "plain-class",
        "prose",
    ],
)
def test_the_detector_ignores_what_is_not_a_limit_or_a_cadence(source: str) -> None:
    """The negative control, and the whole point of parsing rather than grepping.

    Retry and backoff are exactly what `CPM-NFR-3` asks the collector base to
    carry, so a detector that flagged them would be switched off within a day. A
    function *named* `schedule`, and a plain parameter called `soft_time_limit`,
    are both matched by a text search for the banned words and by nothing here.

    The third-party row is the one that shaped the matcher. `task` is an ordinary
    word, and `@router.task(time_limit=900)` on somebody else's library is not a
    celery task -- failing the gate on it would be this audit describing a rule
    the architecture does not have, which is the fastest way to have it switched
    off. So the receiver is checked, not just the attribute. The plain class is
    the same argument for `_task_class_attributes`: `time_limit` is a reasonable
    attribute name on a class that has nothing to do with celery.
    """
    assert declaration_offences(ast.parse(source)) == []


# ---------------------------------------------------------------------------
# The same two rules on the registry surface, where no spelling can hide.
# ---------------------------------------------------------------------------


def registry_offences(task_names: Iterable[str]) -> list[str]:
    """Return every limit or cadence a registered task actually carries.

    Args:
        task_names: The registered names to inspect.

    Returns:
        One `name: attribute=value` string per offence. Read off the task object
        rather than off the source, so it is indifferent to how the option got
        there: a keyword, an unpacked dictionary, a class attribute, a decorator
        this scan cannot resolve, or a base class three projects away.

    """
    return sorted(
        f"{name}: {attribute}={value!r}"
        for name in task_names
        for attribute in REGISTRY_DECLARATION_ATTRIBUTES
        if (value := getattr(app.tasks[name], attribute, None)) is not None
    )


def test_the_registry_sweep_has_tasks_to_look_at() -> None:
    """The anti-vacuity guard for the sweep below.

    An empty registry -- autodiscovery not forced, a scope predicate that had
    collapsed -- passes the next case by inspecting nothing.
    """
    assert product_task_names() != frozenset()


def test_no_registered_task_carries_a_limit_or_a_cadence() -> None:
    """AC 2 and AC 3 on the surface celery itself reads.

    The source sweep above is the one that says *where* the mistake is, and it
    can only see spellings it knows: `@shared_task(**TASK_OPTIONS)` puts a
    `time_limit` on a task with no `time_limit` anywhere in the decorator's
    keywords, and a base class carrying one is not in this file's tree at all.
    The registry has no such blind spot -- whatever put the option there, it is an
    attribute on the task object by the time this runs -- and the two together are
    what make the rule hard to get past rather than hard to spell.

    It is the weaker of the two on its own, which is why it is not the only one:
    it can only see a task that has actually been registered, so a module nothing
    imports is invisible here and visible to the source sweep.
    """
    assert registry_offences(product_task_names()) == []


@pytest.mark.parametrize(
    ("attribute", "value"),
    [("time_limit", 900), ("soft_time_limit", 600), ("run_every", 86400)],
    ids=["hard-limit", "soft-limit", "cadence"],
)
def test_the_registry_sweep_finds_an_option_the_source_sweep_would_not(attribute: str, value: int) -> None:
    """Measured against a real registered task, which is the only honest measure.

    The fixture is registered through the same `app.task` call a decorator makes,
    with the option passed as a keyword the source scan never sees -- which is
    exactly the shape `@shared_task(**TASK_OPTIONS)` produces. A sweep that had
    stopped reading the attribute would report a clean registry, and this is the
    case that goes red on the day it stops.
    """
    a_task = f"cpm.collect.carrying_{attribute}"

    with registered_tasks(a_task, **{attribute: value}):
        offences = registry_offences(product_task_names())

        assert offences == [f"{a_task}: {attribute}={value!r}"]


def test_the_registry_sweep_passes_a_task_that_declares_neither() -> None:
    """The conforming case, so the sweep cannot be satisfied by failing everything."""
    with registered_tasks("cpm.collect.plain"):
        assert registry_offences(product_task_names()) == []
