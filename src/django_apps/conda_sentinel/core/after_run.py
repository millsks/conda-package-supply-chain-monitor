"""The seam a policy run offers to whatever has to happen once it has finished.

`CPM-APP-S04` left one thing deliberately unwired: nothing opened queue items.
Opening them is the policy run's job -- the mockups say so, *"created by the policy
run, never by a human"* -- and the obvious way to arrange that is for
`core/policy_run.py` to import `workflow.services` and call it. That would invert the
orchestration `core` is built on, in exactly the way `CPM-APP-S02`'s health
projection nearly did: `core` reaches its passes through a registry it *declares* and
`policies/apps.py` fills, which is what lets a pass be added without the orchestrator
knowing its name.

So this is the same shape for a different kind of work. `core` declares the seam;
`conda_sentinel.workflow` fills it at `ready()`; `core/policy_run.py` calls whatever
is registered and knows nothing about queues.
`tests/unit/django_apps/test_app_layering_audit.py` is what keeps it that way.

**A step runs after the rollup, not instead of a pass.** The distinction is worth
stating because a pass would have been the lazier option. A pass writes a derived
table keyed `(package, policy_run)` and contributes a status column
(`CPM-AD-21`); opening a queue item does neither, and a pass that quietly did
something else instead would make `contributes` and `derived_model` mean "usually".
A step reads what the run concluded and acts on it.

**A failing step fails the run, and that is deliberate.** The alternative -- log it
and finish `succeeded` -- produces a run that reports success while the queues it was
supposed to fill are empty, which is the most expensive kind of silence this product
can produce: nobody is looking at work nobody knows exists. `CG-3`'s rule, applied
here.

**Steps run in registration order and are declared once**, on the terms
`core/policy.py` sets for passes: a second registration under one name is refused
rather than replacing the first, because two things quietly answering to one name is
how a step stops running without anybody noticing.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Protocol

import structlog

if TYPE_CHECKING:
    from collections.abc import Mapping

    from conda_sentinel.core.clock import Clock
    from conda_sentinel.core.models import PolicyRun

__all__ = [
    "STEP_COMPLETED_EVENT",
    "AfterRunStep",
    "AfterRunStepError",
    "register_after_run_step",
    "registered_after_run_steps",
    "run_after_run_steps",
    "step_registrations",
    "unregister_after_run_step",
]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: What a completed step reports. An operator reading a run's log should be able to
#: see that the queues were filled, and how much, without opening the database.
STEP_COMPLETED_EVENT: str = "policy_run.after_step_completed"


class AfterRunStepError(Exception):
    """A step could not be registered, or refused to run.

    Named rather than left as `ValueError`, so `core/policy_run.py` can tell a
    registration mistake from a step that failed doing its work -- the first is a
    programming error at `django.setup()` and the second is a run that has to fail.
    """


class AfterRunStep(Protocol):
    """What a step has to be: a call taking the run and the clock, returning a count.

    A protocol rather than a base class, because a step is one function and a
    hierarchy would be ceremony.

    **The name is not on it**, and that is a correction rather than an omission: an
    earlier version required a `name` attribute, which meant a plain function had to
    have one bolted on after definition -- a shape no type checker can see through
    and no reader expects. The name is what a caller registers *under*, which is
    where a name belongs.
    """

    def __call__(self, *, run: PolicyRun, clock: Clock) -> int:
        """Do the work and report how much of it there was.

        Args:
            run: The finished policy run, whose derived rows the step reads.
            clock: The clock any instant is read from (`CPM-AD-26`).

        Returns:
            A count, for the run's own log line. What it counts is the step's
            business; that there is a number is what makes a run's output readable.

        """
        ...


#: What is registered, by name, in registration order.
#:
#: Module-level and mutable, exactly as `core/policy.py`'s pass registry is, and for
#: the same reason: registration is a side effect of *adoption* rather than of
#: import, so an application that is installed registers and one that is not does
#: not.
_STEPS: dict[str, AfterRunStep] = {}


def register_after_run_step(name: str, step: AfterRunStep) -> AfterRunStep:
    """Adopt one step under a name.

    Args:
        name: What a refusal, a log line and a duplicate registration all say. An
            unnamed step is one nobody can find when a run reports it failed.
        step: The step to adopt.

    Returns:
        The step, so a caller may keep the reference.

    Raises:
        AfterRunStepError: When no name is given, or when a step is already
            registered under it. A second registration is refused rather than
            replacing the first: two things answering to one name is how a step stops
            running without anybody noticing, and the failure is invisible because
            the run still succeeds.

    """
    if not name:
        message = (
            "an after-run step was registered under no name. The name is what a refusal, a log line and a "
            "duplicate registration all have to say."
        )
        raise AfterRunStepError(message)
    if name in _STEPS:
        message = (
            f"a step is already registered as {name!r}. Registering a second under one name would silently "
            f"replace the first, and the run would go on succeeding with half its work not done."
        )
        raise AfterRunStepError(message)
    _STEPS[name] = step
    return step


def unregister_after_run_step(name: str) -> None:
    """Withdraw a step.

    For tests, which is why it exists at all -- production adopts and never
    withdraws. `core/policy.py`'s registry carries the same escape for the same
    reason, and a suite that mutated the module dictionary directly would be relying
    on its shape.

    Args:
        name: The step to withdraw. Withdrawing one that is not registered is not an
            error: a teardown should not have to know whether its setup got that far.

    """
    _STEPS.pop(name, None)


def registered_after_run_steps() -> tuple[tuple[str, AfterRunStep], ...]:
    """Return every registered step with its name, in registration order.

    Returns:
        `(name, step)` pairs. Order is registration order rather than sorted, on the
        terms `core/policy.py` states: it is what was declared, and a later step may
        depend on an earlier one having run.

    """
    return tuple(_STEPS.items())


def step_registrations() -> Mapping[str, AfterRunStep]:
    """Return what is registered, by name.

    Returns:
        A copy, so a caller cannot widen or empty the registry by mutating what it
        was handed.

    """
    return dict(_STEPS)


def run_after_run_steps(*, run: PolicyRun, clock: Clock) -> dict[str, int]:
    """Run every registered step against a finished policy run.

    Args:
        run: The finished run.
        clock: The clock any instant is read from.

    Returns:
        What each step reported, by name, for the run's summary.

    Raises:
        AfterRunStepError: When a step raises. The run fails rather than reporting
            success with empty queues -- see the module docstring: nobody looking at
            work nobody knows exists is the most expensive silence available here.

    """
    counts: dict[str, int] = {}
    for name, step in registered_after_run_steps():
        try:
            counts[name] = step(run=run, clock=clock)
        except Exception as failure:
            message = (
                f"the after-run step {name!r} failed, so policy run {run.pk} is reported failed rather than "
                f"succeeding with work it was supposed to create missing."
            )
            raise AfterRunStepError(message) from failure
        logger.info(STEP_COMPLETED_EVENT, step=name, policy_run=run.pk, count=counts[name])
    return counts
