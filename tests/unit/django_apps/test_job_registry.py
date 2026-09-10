"""The seam `core` offers for work that left a request, and the ways it refuses.

`core/jobs.py` exists so that `core` never imports `surface`: producing a report is
`surface`'s and the job mechanism is `core`'s, and the inversion is the same one the
pass registry and the after-run registry use. What it *is*, though, is another
mutable module-level registry, and every one of those fails the same three ways -- a
thing registered twice, a thing registered under nothing, and a thing that fails and
is swallowed.

So the cases here are mostly refusals, exactly as `test_after_run_seam.py`'s are. The
happy path is one line and is exercised by every export in the integration suite;
what needs saying out loud is what happens when somebody registers a second runner
under one kind, because the symptom is a job that succeeds and produces somebody
else's artifact.

**Every case restores the registry**, and that lesson was learned the expensive way
in this epic: `test_after_run_seam.py`'s first version ran the *real* registered step
and failed with "Database access not allowed", and a test that left a registration
behind would change what every later job in the session does -- with the failure
landing in an unrelated module.

No database: the registry is a dictionary and `job_parameters` reads an attribute.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest

from conda_sentinel.core.jobs import JobRunnerError
from conda_sentinel.core.jobs import job_parameters
from conda_sentinel.core.jobs import job_runner_registrations
from conda_sentinel.core.jobs import register_job_runner
from conda_sentinel.core.jobs import registered_job_runner
from conda_sentinel.core.jobs import unregister_job_runner

if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Mapping

#: A kind no adopted application uses, so registering it cannot collide with the real
#: runner `conda_sentinel.surface` registers at `ready()`.
A_FIXTURE_KIND: Final[str] = "tests.job_fixture"

#: What the fixture runner reports having produced.
AN_ARTIFACT: Final[str] = "a,b\n1,2\n"
A_ROW_COUNT: Final[int] = 1


class _Job:
    """The three attributes the seam reads off a job, so no database is needed.

    `job_parameters` reads `parameters`, and names `pk` and `kind` in its refusal.
    Nothing else about a `BackgroundJob` is touched, so a stand-in is honest here
    rather than a shortcut -- a real row would prove nothing extra and would make
    this an integration module.
    """

    pk = 1
    kind = A_FIXTURE_KIND

    def __init__(self, **parameters: str) -> None:
        """Hold the parameters a case wants read.

        Args:
            **parameters: What the job was enqueued with.

        """
        self.parameters = parameters


@pytest.fixture(autouse=True)
def adopted_runners() -> Iterator[Mapping[str, Any]]:
    """Empty the registry for each case, hand over what was there, and put it back.

    **Emptying it, not just cleaning up after.** The registry is already filled by
    adoption -- `conda_sentinel.surface` registers its export runner at `ready()` --
    and a case that asserted "these are the registered kinds" would otherwise be
    asserting something about adoption rather than about the case.

    Restoring rather than clearing, because the registry outlives this module: a
    later export in the same session fails with "no runner registered" if the real
    one is gone, and the failure lands somewhere else entirely.

    Yields:
        What adoption had registered before this case emptied the registry, so the
        case below can assert against it rather than re-registering a real kind and
        colliding with its own teardown.

    """
    adopted = dict(job_runner_registrations())
    for kind in adopted:
        unregister_job_runner(kind)
    try:
        yield adopted
    finally:
        unregister_job_runner(A_FIXTURE_KIND)
        for kind, runner in adopted.items():
            register_job_runner(kind, runner)


def a_runner() -> Any:
    """Return a runner that reports an artifact and a count.

    Returns:
        The runner.

    """

    def runner(*, job: Any, clock: Any) -> tuple[str, int]:
        return AN_ARTIFACT, A_ROW_COUNT

    return runner


def test_a_registered_runner_can_be_found_by_its_kind() -> None:
    """The happy path, and it is a lookup rather than an import.

    That is the whole of the inversion: `core` reaches `surface`'s work through a
    string, so a component that has not adopted `surface` runs no exports and `core`
    is none the wiser.
    """
    register_job_runner(A_FIXTURE_KIND, a_runner())

    assert registered_job_runner(A_FIXTURE_KIND) is not None


def test_a_second_runner_under_one_kind_is_refused() -> None:
    """The failure this refusal exists for is a job that succeeds.

    Replacing the first silently would leave every export producing the second
    runner's artifact -- a file that downloads, opens, and is about the wrong thing.
    Nothing in the job record would show it.
    """
    register_job_runner(A_FIXTURE_KIND, a_runner())

    with pytest.raises(JobRunnerError, match=r"already has a runner"):
        register_job_runner(A_FIXTURE_KIND, a_runner())


def test_a_runner_registered_under_no_kind_is_refused() -> None:
    """A kind is what a job row carries; a runner with none can never be found."""
    with pytest.raises(JobRunnerError, match=r"under no name"):
        register_job_runner("", a_runner())


def test_a_kind_nothing_runs_is_refused_and_names_what_does() -> None:
    """A job whose kind has no runner would sit at `queued` for ever.

    That is the one outcome a status page cannot explain -- indistinguishable from a
    worker that is simply behind -- so the lookup fails loudly and the message names
    the kinds that *are* registered, which is what somebody debugging a typo needs.
    """
    register_job_runner(A_FIXTURE_KIND, a_runner())

    with pytest.raises(JobRunnerError, match=A_FIXTURE_KIND):
        registered_job_runner("nobody.registered.this")


def test_withdrawing_a_runner_that_was_never_registered_is_not_an_error() -> None:
    """A teardown should not have to know whether its setup got that far."""
    unregister_job_runner("tests.a-kind-nobody-registered")


def test_the_registrations_mapping_is_a_copy() -> None:
    """A caller cannot empty the registry by mutating what it was handed.

    The same reason `core/policy.py`'s registry returns one, and the failure a shared
    dictionary produces is a runner that disappears mid-session with nothing naming
    the culprit.
    """
    register_job_runner(A_FIXTURE_KIND, a_runner())

    handed = job_runner_registrations()
    handed.clear()  # type: ignore[attr-defined]

    assert A_FIXTURE_KIND in job_runner_registrations()


def test_a_missing_parameter_is_refused_rather_than_read_as_absent() -> None:
    """A runner reading `None` and carrying on produces an artifact for the wrong thing.

    Which is the one failure a job record cannot show: the state says `succeeded`,
    the row count is plausible, and the file is about something nobody asked for.
    """
    with pytest.raises(JobRunnerError, match=r"carries no \['slug'\]"):
        job_parameters(_Job(), "slug")


def test_a_blank_parameter_counts_as_missing() -> None:
    """`{"slug": ""}` names no report, and reads as one right up until it does not.

    Asserted separately from the absent case because the two arrive differently -- a
    key omitted is a caller that forgot, an empty value is a form that submitted --
    and a check testing only `in` would pass the second straight through.
    """
    with pytest.raises(JobRunnerError, match=r"carries no \['slug'\]"):
        job_parameters(_Job(slug=""), "slug")


def test_present_parameters_come_back_in_the_order_asked_for() -> None:
    """So the refusals above are not simply a function that rejects everything.

    Order matters because callers unpack: `(slug,) = job_parameters(job, "slug")`.
    """
    assert list(job_parameters(_Job(slug="kev", scope="all"), "scope", "slug")) == ["all", "kev"]


def test_the_real_runner_is_registered_by_adoption(adopted_runners: Mapping[str, Any]) -> None:
    """The seam is filled, which is what makes every case above about something.

    `conda_sentinel.surface` registers its export runner at `ready()`. If adoption
    stopped registering it, every case here would still pass and every enqueued
    export would fail -- so the fact of registration is asserted rather than assumed.

    Reads what the autouse fixture *saved* rather than what is registered now, since
    the fixture empties the registry for the duration of each case. That is also the
    honest read: the question is what adoption produced, not what this module left
    behind.

    Args:
        adopted_runners: What adoption had registered, from the autouse fixture.

    """
    from conda_sentinel.surface.exports import EXPORT_JOB_KIND  # noqa: PLC0415 - read beside the claim

    assert EXPORT_JOB_KIND in adopted_runners
