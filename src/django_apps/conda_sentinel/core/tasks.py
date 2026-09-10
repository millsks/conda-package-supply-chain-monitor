"""The one task this application registers: the policy run beat schedules.

`CPM-AD-20` splits background work into three queues by *workload class*, and a
task's class lives in its declared name rather than in its module -- so this task
is named `cpm.policy.run` and `core/queues.py`'s route table sends it to the
`policy` queue. A name outside the `cpm.policy.` namespace is routed nowhere and
lands on the default queue, where nothing this product runs drains it: the task
would be registered, enqueued, and silently never executed.
`tests/unit/django_apps/test_task_routing_audit.py` is the gate on that.

**Beat schedules the run. A pass is never a task** (`CPM-AD-20`, `CPM-AD-21`).
There is one unit of scheduling here because there is one cut-off: passes that
were separately scheduled would each choose their own instant to read evidence
as of, and the rollup would then be composed from domains that disagree about
when "now" was -- which is exactly the non-reproducibility `CPM-FR-22`'s replay
guarantee exists to prevent.

**No cadence, and no time limit, in this file.** The schedule is a
`django_celery_beat` row: `CPM-NFR-2` says an operator changes when the sweep
runs without a deploy, and a `schedule=` or `run_every=` in the decorator makes
that a code change. The inherited `CELERY_TASK_TIME_LIMIT` and
`CELERY_TASK_SOFT_TIME_LIMIT` stand, because `CPM-AD-9` says work that exceeds
them is chunked per package rather than given a longer limit -- and this run
already is, one `transaction.atomic()` per package.
`tests/unit/django_apps/test_task_declaration_audit.py` fails any of the four
spellings, in a decorator or as an assignment outside `config/settings/`.

**The policy version is an argument, not a constant.** `CPM-AD-8` makes rule sets
and scoring functions versioned *data*, so the version is a value an operator
sets on the beat row's `kwargs` -- not a literal in this module that a deploy
would be needed to change. A default here would be this module inventing a
version, which is the one thing a versioned-data decision forbids.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import Final

import structlog
from celery import shared_task

from conda_sentinel.core.clock import SystemClock
from conda_sentinel.core.policy_run import execute_policy_run
from conda_sentinel.core.queues import EXPORT_JOB_TASK_NAME
from conda_sentinel.core.queues import NAME_SEPARATOR
from conda_sentinel.core.queues import TASK_NAMESPACE_PREFIX
from conda_sentinel.core.queues import Queue

logger = structlog.get_logger(__name__)

#: What a task records when the job row a request wrote is no longer there.
JOB_MISSING_EVENT: Final[str] = "job.missing"

__all__ = ["EXPORT_JOB_TASK_NAME", "POLICY_RUN_TASK_NAME", "run_job", "run_policy"]

#: The declared name of the policy run, built from `core/queues.py`'s own parts.
#:
#: Composed rather than written out as `"cpm.policy.run"`, because the literal
#: would be a second spelling of a namespace whose whole purpose is that there is
#: one: a rename of the `policy` queue would leave this task declaring a
#: namespace the route table no longer has, and the failure is silent -- the
#: message lands on the default queue and nothing drains it.
POLICY_RUN_TASK_NAME: Final[str] = f"{TASK_NAMESPACE_PREFIX}{NAME_SEPARATOR}{Queue.POLICY.value}{NAME_SEPARATOR}run"


# celery ships no `py.typed` marker and conda-forge carries no stub package for
# it, so `ignore_missing_imports` resolves `shared_task` to `Any` and strict mode
# reports that the decorator erases the annotated signature below. The
# annotations are still the contract this module publishes, and
# `warn_unused_ignores` removes the marker when celery starts publishing types.
# This is the same marker `django_service/users/tasks.py` carries.
@shared_task(name=POLICY_RUN_TASK_NAME)  # type: ignore[untyped-decorator]
def run_policy(policy_version: str) -> int:
    """Run every registered policy pass at one cut-off and compose the rollup.

    Args:
        policy_version: The version of the rule data to apply (`CPM-AD-8`),
            supplied by the beat row that schedules this. Required: see the
            module docstring for why a default here would be this module
            inventing a version.

    Returns:
        How many rollup rows the run wrote. Returned rather than logged only so
        that the celery result carries what the run did, which is what an
        operator reads when asking whether the sweep covered the inventory.

    """
    return execute_policy_run(policy_version=policy_version, clock=SystemClock()).rollup_rows


@shared_task(name=EXPORT_JOB_TASK_NAME)  # type: ignore[untyped-decorator]
def run_job(job_id: int) -> int:
    """Run one handed-off job, and record how it ended either way.

    `CPM-AD-9`'s other half: the request enqueued this and returned an in-progress
    state, so the one thing this must not do is leave the job in that state. Every
    exit below moves it to a terminal one -- including the failure paths, because a
    job stuck at `running` is indistinguishable to a reader from work that hung, and
    a status page that says "in progress" for ever is worse than one that says the
    export broke.

    **It does not know what an export is.** The runner comes from
    `core/jobs.py`'s registry, which `surface/apps.py` fills at `ready()` -- `core`
    may not import `surface`, and the seam is the same one the pass registry and the
    after-run registry use.

    Args:
        job_id: Which job, by primary key. An id rather than the row, because the
            row this acts on should be the one it reads now rather than one a request
            serialized into a message minutes ago.

    Returns:
        How many rows the artifact covers, so the celery result carries what the job
        did -- and `0` for a job that failed, which the state and `detail` explain.

    """
    from conda_sentinel.core.jobs import JobRunnerError  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.core.jobs import finish_job  # noqa: PLC0415 - as above
    from conda_sentinel.core.jobs import registered_job_runner  # noqa: PLC0415 - as above
    from conda_sentinel.core.jobs import start_job  # noqa: PLC0415 - as above
    from conda_sentinel.core.models import BackgroundJob  # noqa: PLC0415 - as above

    clock = SystemClock()
    job = BackgroundJob.objects.filter(pk=job_id).first()
    if job is None:
        # Nothing to fail: the row a request wrote is gone, which is a real state
        # after a rollback and is not this task's to repair. Reported rather than
        # raised, because a retry would find the same absence.
        logger.warning(JOB_MISSING_EVENT, job=job_id)
        return 0

    start_job(job, clock=clock)
    try:
        runner = registered_job_runner(job.kind)
        artifact, rows = runner(job=job, clock=clock)
    except (JobRunnerError, ValueError, LookupError) as failure:
        # Narrow, and each is a way this can genuinely fail: no runner or a bad
        # parameter (`JobRunnerError`), a report that will not project (`ValueError`),
        # a name that resolves to nothing (`LookupError`). A bare `except` here would
        # swallow the programming errors that should reach the worker's log intact.
        finish_job(job, clock=clock, detail=str(failure))
        return 0

    finish_job(job, clock=clock, artifact=artifact, rows=rows)
    return rows
