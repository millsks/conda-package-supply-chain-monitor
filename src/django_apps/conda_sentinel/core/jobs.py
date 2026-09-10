"""`CPM-AD-9`'s boundary, as a thing a request can hand work to and point at.

The decision splits the product in two: a request reads derived state and evidence
and may write workflow state or an override; anything that makes an outbound call,
runs a collector, runs a policy pass, or exports beyond the row cap leaves the
request. `CPM-APP-S08`'s AC 1 adds what the request does *instead* -- it returns an
in-progress state -- and that is what this module is. A boundary a request can cross
but not point back across is one where the work disappears.

**Three of the four triggers have no request path at all today, and the audit is what
keeps it that way.** Nothing in `surface/` calls a collector or a policy pass, and
nothing there makes an outbound call. So for those three the deliverable is
`tests/unit/django_apps/test_request_boundary_audit.py`, which sweeps the modules a
request actually reaches. The fourth -- an export beyond the cap -- exists, and this
is where it goes.

**The runner registry is an inversion, and the same one twice already.** `core` may
not import `surface`: the layering audit says so and the health projection nearly
broke it once. But the work that leaves a request is *surface's* -- producing a
report is what `surface/reports.py` does. So `core` declares the seam and the domain
application fills it at `ready()`, exactly as `core/policy.py` does for passes and
`core/after_run.py` does for the run's aftermath.

**A job is not append-only**, unlike almost everything else in this product. It has a
state that changes: queued, running, then succeeded or failed. `CPM-AD-2` is about
*evidence* -- what a source said at an instant -- and a job is not evidence about
anything; it is a piece of work with a lifecycle. Its history is the three timestamps
it stamps, which is what an operator asking "why did this take four minutes" reads.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final
from typing import Protocol

import structlog
from django.db import models
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from conda_sentinel.core.clock import SystemClock
from conda_sentinel.core.queues import EXPORT_JOB_TASK_NAME

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    from conda_sentinel.core.clock import Clock
    from conda_sentinel.core.models import BackgroundJob
    from django_service.users.models import User

__all__ = [
    "JOB_ENQUEUED_EVENT",
    "JOB_FAILED_EVENT",
    "JOB_FINISHED_EVENT",
    "JobRunner",
    "JobRunnerError",
    "JobState",
    "finish_job",
    "job_runner_registrations",
    "register_job_runner",
    "registered_job_runner",
    "request_job",
    "start_job",
    "unregister_job_runner",
]

logger = structlog.get_logger(__name__)

#: What a request records when it hands work off, and what a worker records at each
#: end of it. Read by an operator asking where a download went.
JOB_ENQUEUED_EVENT: Final[str] = "job.enqueued"
JOB_FINISHED_EVENT: Final[str] = "job.finished"
JOB_FAILED_EVENT: Final[str] = "job.failed"
JOB_UNPUBLISHED_EVENT: Final[str] = "job.unpublished"

#: What a job whose work could never be handed over records about itself.
#:
#: The reason travels into the row rather than only into a log, because the person
#: waiting for the file is looking at the row and an operator is looking at the log,
#: and only one of them can be asked to correlate.
UNREACHABLE_BROKER: Final[str] = (
    "this work could not be handed to a worker -- the broker refused the connection ({reason}). Nothing was "
    "lost: ask for the export again once the queue is reachable."
)


class JobState(models.TextChoices):
    """Where a piece of handed-off work has got to.

    Four states and no fifth. `queued` and `running` are the two an in-progress
    response reports; `succeeded` and `failed` are terminal.

    **`failed` is a state and not an absence.** A job that broke has to be
    distinguishable from one still running, or a page that says "in progress" says it
    for ever -- which is the same failure `CPM-FR-5` makes load-bearing everywhere
    else in this product, arriving in a different place.
    """

    QUEUED = "queued", _("Queued")
    RUNNING = "running", _("Running")
    SUCCEEDED = "succeeded", _("Succeeded")
    FAILED = "failed", _("Failed")


#: The states a job is still working through, for a surface asking "is this done".
IN_PROGRESS_STATES: Final[frozenset[str]] = frozenset({JobState.QUEUED.value, JobState.RUNNING.value})

#: How wide a job's short string columns are, sized from the vocabulary rather than
#: guessed -- the convention `workflow/states.py` sets for the same reason.
STATE_LENGTH: Final[int] = max(len(value) for value in JobState.values)

#: How wide a job kind may be. A kind is a registry key, not free text, and a name
#: this long is already unreadable.
KIND_LENGTH: Final[int] = 64


class JobRunnerError(RuntimeError):
    """A runner could not be registered, or a job named a kind nothing runs.

    Named rather than raised as `KeyError`, so a worker log says which kind had no
    runner rather than showing a bare string in a traceback -- and so the failure of
    a job with no runner is told apart from a job whose runner failed.
    """


class JobRunner(Protocol):
    """What a domain application registers to run one kind of job.

    Takes the job and a clock; returns what to store and how many rows it covered.
    The runner does not touch the job's state -- `start_job` and `finish_job` own
    that, so every kind of job records its lifecycle the same way rather than each
    remembering to.
    """

    def __call__(self, *, job: BackgroundJob, clock: Clock) -> tuple[str, int]:
        """Run one job.

        Args:
            job: The job, carrying its parameters.
            clock: The clock any stamp is read from (`CPM-AD-26`).

        Returns:
            The artifact to store, and how many rows it covers.

        """


#: Kind to the runner that runs it, in registration order.
#:
#: Module-level and mutable, like `core/policy.py`'s pass registry and
#: `core/after_run.py`'s step registry -- and refusing the same things, because every
#: mutable registry fails the same three ways: a thing registered twice, a thing
#: registered under nothing, and a thing that fails and is swallowed.
_RUNNERS: dict[str, JobRunner] = {}


def register_job_runner(kind: str, runner: JobRunner) -> None:
    """Adopt a runner for one kind of job.

    Args:
        kind: What the job's `kind` column holds.
        runner: What runs it.

    Raises:
        JobRunnerError: When the kind is blank, or already has a runner. Replacing
            one silently is the failure worth refusing: the job would run, report
            success, and produce somebody else's artifact.

    """
    if not kind:
        message = "a job runner was registered under no name, so no job could ever name it."
        raise JobRunnerError(message)
    if kind in _RUNNERS:
        message = (
            f"{kind!r} already has a runner. Replacing it silently would leave jobs succeeding and producing "
            f"the wrong artifact, which is a failure nothing in the record would show."
        )
        raise JobRunnerError(message)
    _RUNNERS[kind] = runner


def unregister_job_runner(kind: str) -> None:
    """Withdraw a runner, or do nothing if there is none.

    A teardown should not have to know whether its setup got that far.

    Args:
        kind: The kind to withdraw.

    """
    _RUNNERS.pop(kind, None)


def job_runner_registrations() -> Mapping[str, JobRunner]:
    """Return what is registered.

    Returns:
        A copy, so a caller cannot widen or empty the registry by mutating what it
        was handed -- the same reason `core/policy.py`'s registry returns one.

    """
    return dict(_RUNNERS)


def registered_job_runner(kind: str) -> JobRunner:
    """Return the runner for one kind.

    Args:
        kind: The kind.

    Returns:
        Its runner.

    Raises:
        JobRunnerError: When nothing runs that kind. A job in that state would sit
            at `queued` for ever and the page would say "in progress" indefinitely,
            so it is failed loudly instead.

    """
    runner = _RUNNERS.get(kind)
    if runner is None:
        message = (
            f"no runner is registered for job kind {kind!r}. The registered kinds are {sorted(_RUNNERS)}; a "
            f"runner is adopted in an application's ready(), never discovered."
        )
        raise JobRunnerError(message)
    return runner


def request_job(
    *,
    kind: str,
    parameters: Mapping[str, str],
    requested_by: User,
    clock: Clock,
) -> BackgroundJob:
    """Record a piece of work a request is handing off, and publish it.

    `CPM-AD-9`'s crossing, in one place so every surface crosses it the same way.

    **The publish is `on_commit`, and that is not a nicety.** A task published inside
    the transaction that created the row reaches a worker that may read the database
    before the commit lands -- and finds nothing. The symptom is a job that a page
    shows as queued for ever while a worker log says the id does not exist, on some
    requests and not others, which is the shape of bug that survives a whole quarter.
    `transaction.on_commit` is Django's answer and this is the only place it has to
    be got right.

    Args:
        kind: Which registered runner will run it.
        parameters: What it is work on.
        requested_by: Who asked. Recorded because a job is somebody's request and the
            surfaces below scope on it -- a shared list of everybody's downloads is
            not a thing anybody asked for.
        clock: The clock `requested_at` is read from (`CPM-AD-26`).

    Returns:
        The saved job, in `queued`, which is the in-progress state AC 1 asks a
        request to return.

    """
    # `kind` decides which registered runner runs it; the *task* is one for every
    # kind, so the name below is not a lookup. A later story whose job kind has a
    # different workload class publishes under its own name to its own queue.
    from conda_sentinel.core.models import BackgroundJob  # noqa: PLC0415 - after django.setup()

    job = BackgroundJob.objects.create(
        kind=kind,
        parameters=dict(parameters),
        state=JobState.QUEUED.value,
        requested_by=requested_by,
        requested_at=clock.now(),
    )
    transaction.on_commit(lambda: _publish(job))
    logger.info(JOB_ENQUEUED_EVENT, job=job.pk, kind=kind, **dict(parameters))
    return job


def _publish(job: BackgroundJob) -> None:
    """Publish one job to the worker, and fail it here if the broker will not take it.

    **By name, never by importing the task.** `core/tasks.py` imports the policy-run
    orchestrator and, through it, the collectors -- so reaching for `run_job.delay`
    would pull every one of them into the web process's import graph, which is the
    thing `CPM-AD-9` is about and what
    `tests/unit/django_apps/test_request_boundary_audit.py` refuses. The name is a
    string, the routing is `CELERY_TASK_ROUTES`'s, and `send_task` needs neither.

    **A broker that will not take it fails the job rather than the request**, which
    was found by running this with no broker: the row is already committed by the
    time `on_commit` fires, so the exception propagated out of the response and left
    a job at `queued` that nothing would ever pick up. The reader got a 500 that told
    them nothing and a page that would have said "in progress" for ever.

    This is not log-and-continue. The refusal is recorded where the reader is already
    being sent -- the job's own page, saying the work could not be handed off -- which
    is a louder report than a traceback they never see. `CG-3` asks that a refusal be
    unmissable, not that it be an exception in every case.

    Args:
        job: The job to publish.

    """
    from celery import current_app  # noqa: PLC0415 - after the settings are loaded
    from kombu.exceptions import OperationalError  # noqa: PLC0415 - as above

    try:
        # `ignore_result=True` because **the job row is the result**. Storing a
        # celery result as well would be a second record of the same thing, in a
        # store with its own expiry, that no surface reads -- and it is a second
        # thing that can fail: a result backend that cannot be written turns a
        # successful hand-off into an exception, which is how this was found.
        current_app.send_task(EXPORT_JOB_TASK_NAME, args=[job.pk], ignore_result=True)
    except OperationalError as unreachable:
        logger.exception(JOB_UNPUBLISHED_EVENT, job=job.pk, kind=job.kind)
        finish_job(job, clock=SystemClock(), detail=UNREACHABLE_BROKER.format(reason=unreachable))


def start_job(job: BackgroundJob, *, clock: Clock) -> None:
    """Mark a job as running.

    Args:
        job: The job.
        clock: The clock `started_at` is read from (`CPM-AD-26`).

    """
    job.state = JobState.RUNNING.value
    job.started_at = clock.now()
    job.save(update_fields=("state", "started_at"))


def finish_job(job: BackgroundJob, *, clock: Clock, artifact: str = "", rows: int = 0, detail: str = "") -> None:
    """Mark a job finished, one way or the other.

    Args:
        job: The job.
        clock: The clock `finished_at` is read from (`CPM-AD-26`).
        artifact: What it produced, for a job that succeeded.
        rows: How many rows the artifact covers.
        detail: Why it failed, for a job that did not. **The presence of this is what
            decides the state**, rather than a separate flag: a failed job with no
            explanation and a succeeded job are then not expressible, and "it failed"
            with nothing to read is the report an operator can do nothing with.

    """
    job.state = JobState.FAILED.value if detail else JobState.SUCCEEDED.value
    job.finished_at = clock.now()
    job.artifact = artifact
    job.row_count = rows
    job.detail = detail
    job.save(update_fields=("state", "finished_at", "artifact", "row_count", "detail"))
    event = JOB_FAILED_EVENT if detail else JOB_FINISHED_EVENT
    logger.info(event, job=job.pk, kind=job.kind, rows=rows, detail=detail)


def job_parameters(job: BackgroundJob, *names: str) -> Sequence[str]:
    """Return named parameters off a job, refusing one that is missing.

    Args:
        job: The job.
        *names: The parameter names to read.

    Returns:
        The values, in the order asked for.

    Raises:
        JobRunnerError: When a parameter is absent. A runner reading `None` and
            carrying on would produce an artifact for the wrong thing, which is the
            one failure a job record cannot show.

    """
    missing = [name for name in names if not job.parameters.get(name)]
    if missing:
        message = f"job {job.pk} of kind {job.kind!r} carries no {missing}; it was enqueued with {job.parameters}."
        raise JobRunnerError(message)
    return [str(job.parameters[name]) for name in names]
