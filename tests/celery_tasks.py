"""How the suite puts a fixture task in the real Celery registry, and takes it out.

`EVIDENCE.04-AUDIT-001` sweeps `app.tasks` and asks what each registered task's
declared name routes to. Today that sweep sees exactly one product-relevant task
-- the inherited platform demo `django_service.users.tasks.get_users_count` --
because no collector, policy pass or verification build exists yet. So the audit
passes by finding nothing to fault, which is how an audit becomes permanently
green and permanently useless.

What keeps it honest is the same device
`tests/unit/django_apps/test_outcome_field_audit.py` and
`tests/unit/django_apps/test_evidence_inheritance_audit.py` use for models: the
detector is measured against fixtures registered around the case and removed
afterwards. Models get `django.test.utils.isolate_apps`, which patches
`Options.default_apps` so the fixtures never reach the global registry. Celery
ships no equivalent -- `Celery.tasks` is one process-wide `TaskRegistry` and
there is no isolated view of it -- so the registration is real and the removal is
this module's responsibility.

**Removal is in a `finally`, and it is checked.** A fixture task left behind
would be seen by every later case in the session as a real registered task, and
the audit it was written to exercise would then fail on it -- in a different
module, with no indication of where it came from. `registered_tasks` restores the
exact name set it found, and raises if the registry it is handed already holds
one of the names, so a fixture can never overwrite a real task and vanish with it
on the way out.

**`shared=False` on every fixture.** `app.task` defaults to also registering the
task with celery's process-wide shared-task registry, which is consulted by every
`Celery` instance created afterwards -- including one built by a later test. The
flag keeps a fixture local to this application, which is the only place the audit
looks.

**Why `import_default_modules` is called before the registry is read.**
`config/celery_app.py` ends in `autodiscover_tasks()`, which is *lazy*: it
registers a callback and imports nothing until the application finalizes. A test
that read `app.tasks` in a session where nothing had imported
`django_service.users.tasks` would see celery's own built-ins and nothing else,
and every sweep over the registry would be vacuous for a reason no assertion
mentions. Forcing the import is what makes "every registered task" mean the tasks
this component actually ships. It imports the `tasks` module of each installed
application and touches no database and no network.

A helper module, not a collected one. `[tool.pytest.ini_options] python_files`
matches `test_*.py` and `tests.py`, so nothing here is collected, and it sits at
`tests/` rather than under `tests/unit/` for the reason `tests/source_scan.py`
and `tests/model_registry.py` do: a collected test module is not a helper
library.
"""

from __future__ import annotations

import sys
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

from config.celery_app import app

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The prefix celery's own built-in tasks carry -- `celery.chain`,
#: `celery.backend_cleanup` and the rest. They are the framework's, they are
#: registered in every application whether or not this product wrote a line, and
#: no product routing rule is about them.
BUILT_IN_TASK_PREFIX: Final[str] = "celery."

#: The prefix the suite's own tasks carry, because `@shared_task` derives a name
#: from the defining module and this package is `tests`.
#:
#: One task has it today: `tests/integration/test_celery_log_correlation.py`
#: declares `correlation_probe` at module scope, and `@shared_task` registers into
#: every `Celery` instance in the process, so importing that module puts the probe
#: in the same registry the routing audit sweeps. It is not a task this component
#: ships -- it exists to prove a *published* message carries the enqueueing
#: request's correlation headers, and it must keep landing on the default queue
#: for that fixture to mean anything.
#:
#: It is skipped by prefix rather than recorded as a counted exemption, and the
#: reason is that a count would be wrong half the time: `pixi run test` collects
#: only `tests/unit/`, never imports that module, and would find zero occurrences
#: of a record that says one. An exemption whose truth depends on which subset of
#: the suite is running is worse than no exemption. What keeps the skip narrow is
#: that it is a prefix on the *name* -- nothing under `src/` can produce a task
#: named `tests.…`, because no module there is in the `tests` package.
SUITE_TASK_PREFIX: Final[str] = "tests."

#: Both prefixes the sweep drops, in one place so a caller cannot apply one and
#: forget the other.
EXCLUDED_TASK_PREFIXES: Final[tuple[str, ...]] = (BUILT_IN_TASK_PREFIX, SUITE_TASK_PREFIX)


def registered_task_names() -> frozenset[str]:
    """Return every task name the real application holds, autodiscovery forced.

    Returns:
        The names in `app.tasks`, celery's own built-ins and the suite's own
        tasks included. Callers that care only about the tasks this component
        ships use `product_task_names` below.

    """
    app.loader.import_default_modules()
    return frozenset(app.tasks)


def product_task_names() -> frozenset[str]:
    """Return every registered task name this component itself ships.

    Returns:
        The names the routing audit is about: everything this component
        registers, whether it declared a `cpm.` name or inherited a
        `module.function` one. Celery's own built-ins and the suite's own tasks
        are dropped, each for the reason its prefix constant records.

    """
    return frozenset(name for name in registered_task_names() if not name.startswith(EXCLUDED_TASK_PREFIXES))


@contextmanager
def registered_tasks(*names: str, **options: Any) -> Iterator[tuple[str, ...]]:
    """Register fixture tasks under the given names for the body of a `with`.

    Args:
        *names: The task names to register, exactly as a real task would declare
            them.
        **options: Further keyword arguments for `app.task`, so a case can
            measure a detector against a task carrying an option it should not.

    Yields:
        The names, in the order they were given.

    Raises:
        ValueError: When the registry already holds one of the names, and -- only
            where the body did not raise -- when the registry it is handed back
            differs from the one it took. A fixture that overwrote a real task
            would take it away again on the way out, leaving a registry quieter
            than the one the session started with.

    """
    already = sorted(name for name in names if name in app.tasks)
    if already:
        message = f"the celery registry already holds {already}; a fixture task must not displace a real one"
        raise ValueError(message)

    before = frozenset(app.tasks)
    # Registration is inside the `try` and each success is recorded as it
    # happens, so a failure on the third of three names still removes the first
    # two. Registering ahead of the `try` -- which this did -- leaks exactly the
    # tasks the module docstring says the helper exists not to leak, and does it
    # on the path where something is already going wrong.
    registered: list[str] = []
    try:
        for name in names:
            _register(name, **options)
            registered.append(name)
        yield names
    finally:
        for name in registered:
            app.tasks.pop(name, None)
        restored = frozenset(app.tasks)
        # **An exception raised in a `finally` replaces the one propagating.**
        # `core/ledger.py`'s finalization records the same hazard and takes the
        # same resolution: the drift is reported either way, and it is raised
        # only when it is not standing on somebody else's exception. With a body
        # error in flight the caller keeps its own, which is the more useful of
        # the two -- it says why the case failed, where this one only says the
        # registry was left untidy on the way out.
        if restored != before:
            message = (
                f"fixture tasks changed the celery registry: added {sorted(restored - before)}, "
                f"removed {sorted(before - restored)}"
            )
            if sys.exc_info()[1] is None:
                raise ValueError(message)
            # Never swallowed. A warning is what a helper has instead of a raise
            # here: pytest surfaces it in the run's warnings summary, so the
            # untidy registry is on the record beside the failure that caused it.
            warnings.warn(message, stacklevel=2)


def _register(name: str, **options: Any) -> None:
    """Register one fixture task with a body that does nothing.

    The body is never called. The audits this supports read declared names and
    decorator options off the registry, and a task that did work would give a
    case a way to pass for a reason other than the one it states.

    `__module__` is set to the module part of the declared name, because that is
    what a real task registered under that name would carry and because
    `tests/unit/django_apps/test_task_routing_audit.py` reconciles the two for
    the exempted task. A fixture left claiming `tests.celery_tasks` would be a
    fixture the audit could not be measured against.

    Args:
        name: The task's declared name.
        **options: Further keyword arguments for `app.task` -- `time_limit`,
            `run_every` and the rest -- so a case can measure a detector against
            a task carrying an option it should not.

    """

    def _fixture() -> None:
        """Do nothing; the registration is the whole point."""

    declaring_module = name.rpartition(".")[0]
    if declaring_module:
        _fixture.__module__ = declaring_module
    app.task(name=name, shared=False, **options)(_fixture)
