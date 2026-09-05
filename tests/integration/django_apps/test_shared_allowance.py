"""One allowance, two operating-system processes, one real Redis.

`core/rate_limit.py` writes `add`-then-`incr` and says why in its own words: the
two-step "create at zero, then increment" exists so that two processes racing a
new window both increment one counter rather than one of them resetting the
other. Everything else in this repository proves the limiter against
`LocMemCache`, and under LocMem that property **cannot fail** -- each process
holds its own dictionary, so a limiter that lost the race would pass every case
in `tests/unit/django_apps/test_rate_limit.py`, and the reasoning behind the
sequence would be unverified prose.

These are the cases that can fail, and there are two because the sequence makes
two claims that need different arrangements to see.

**The counter is shared** (AC 4). Two real interpreters
(`tests/rate_limit_workers.py`), started together, ask one collector's allowance
for one window against a `redis:7` container. The allowance is one, so the pair
is decisive: with a shared counter exactly one is permitted, and with a
per-process counter both are. There is no arithmetic between those outcomes for
a race to make ambiguous, and running this against the LocMem substitution
produces two permitted workers -- which is what makes the case a proof of the
backend rather than of the arithmetic.

**A later arrival does not reset the window**, which is what `add` buys over
`set` and what the concurrent case above cannot see: when both processes overlap,
both write the counter to zero before either increments it, so it reaches two and
one is refused whichever verb was used. The second case therefore waits for the
first worker before starting the second -- the ordinary shape of a sweep -- where
`set` hands the collector a second full allowance inside one window.

**Why a service and a skip.** `tests/unit/test_suite_policy.py` bans skips so
that a CI-only failure is fixed rather than dodged, and records the exceptions
per file per form. This is the shape its own docstring sanctions -- "a genuinely
platform-specific test", here a test that needs a service -- and the decision is
recorded in that table beside the four that came before it. What makes it not a
dodge is that the service exists where it matters: `.github/workflows/ci.yml`
declares a `redis:7` on the gate job and sets `CPM_TEST_REDIS_URL` at job level,
so both cases run on every pull request, and `pixi run gate-redis` runs them
locally in one command. They are skipped only on a developer's machine with no
Redis, which is the same accommodation
`tests/integration/test_image_payload.py` makes for a machine with no Docker.

**What the recorded count does and does not constrain.** The exemption licenses
one `pytest.mark.skipif` *expression* in this file, and the detector counts
expressions. `needs_redis` below is one such expression bound to a name, so
applying it to a further case adds no count -- which is the intent: the recorded
decision is "this module needs a Redis", taken once, and a second case needing
the same service is that decision being used rather than a new one. What the
count does prevent is a *second condition*: a skip on a different capability, or
on the same one spelled differently, is a second `pytest.mark.skipif` and fails
the gate until somebody records why. So the alias is the mechanism that makes
the count mean "one decision" rather than "one test".

**Why the backend is asserted rather than assumed.** A run whose environment
variable never reached the settings module would fall back to LocMem, both
workers would be permitted, and the failure would read as "the counter is not
shared" -- pointing at the code rather than at the environment. The assertion
turns that into a message naming the real problem.

Every process here reaches a real Redis over a socket, which is why this is an
integration test. It touches no database: the limiter reads the cache and
nothing else.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.conf import settings

from tests.clocks import FIXED_INSTANT
from tests.collectors import cleared_cache
from tests.rate_limit_workers import DEFAULT_SETTINGS_MODULE
from tests.rate_limit_workers import PERMITTED_EXIT
from tests.rate_limit_workers import REFUSED_EXIT
from tests.rate_limit_workers import WORKER_ALLOWANCE

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The variable that both selects the Redis backend (`config/settings/test.py`)
#: and arms this module. One variable for both, so a run cannot be configured to
#: skip the case while the cache is Redis, or to run it while the cache is not.
REDIS_URL_VARIABLE: Final[str] = "CPM_TEST_REDIS_URL"

#: The worker entry point, resolved from this file rather than from the working
#: directory: `pytest` may be invoked from anywhere, and a relative path would
#: make this case pass or fail on where somebody stood.
WORKER_MODULE: Final[Path] = Path(__file__).resolve().parents[2] / "rate_limit_workers.py"

#: The collector name the workers count against. Prefixed like every other
#: fixture name so it cannot collide with a real collector's the day one exists.
A_COLLECTOR: Final[str] = "cpm-fixture-shared-allowance"

#: How long a worker is given to start an interpreter, configure Django and ask
#: once. Generous: the subject is which verdicts come back, and a tight bound
#: would make this the flakiest case in the suite on a loaded runner.
WORKER_TIMEOUT_SECONDS: Final[int] = 120

#: What `django_redis` is spelled as in `config/settings/test.py`'s Redis branch
#: and in `config/settings/production.py`. Asserted so a run that quietly landed
#: on the in-process substitution says so, rather than failing as though the
#: limiter were wrong.
REDIS_BACKEND_MARKER: Final[str] = "django_redis"

#: How many workers ask. Two, which is the smallest number that can race.
WORKERS: Final[int] = 2


needs_redis = pytest.mark.skipif(
    not os.environ.get(REDIS_URL_VARIABLE),
    reason=(
        f"{REDIS_URL_VARIABLE} is not set, so the cache is the in-process LocMem substitution and a counter "
        f"shared across processes cannot exist. Run `pixi run gate-redis`, which starts a throwaway redis:7 "
        f"and sets the variable; the CI gate job sets it too, so this case runs on every pull request."
    ),
)


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    """Start and end every case with no counter for anybody, and a worker to run.

    A counter left behind by an earlier case is an allowance already spent, and
    with an allowance of one that is the difference between the assertions below
    passing and failing.

    The worker's existence is checked here rather than in one of the cases,
    because it is a precondition of both and a rename is a change neither of
    them is about. Checked in a case, it produced one clear failure and one
    interpreter exiting `2` with "can't open file" -- and the second is the one
    somebody meets first if the suite runs in that order.

    Yields:
        Nothing; the fixture is its check and its two side effects.

    """
    assert WORKER_MODULE.is_file(), (
        f"the worker entry point is missing: {WORKER_MODULE}. Both cases here run it in a subprocess, "
        f"where a missing file is an exit code rather than an error message."
    )
    with cleared_cache():
        yield


@needs_redis
def test_two_worker_processes_share_one_allowance() -> None:
    """AC 4: the counter is shared, and the allowance is spent once across the pair.

    Both workers are started before either is waited on, so they genuinely
    overlap rather than running in sequence -- which is the state
    `core/rate_limit.py`'s two-step sequence was written for. Sequential runs
    would pass against a limiter that read, compared and wrote; concurrent ones
    are what that shape exists to survive.

    The assertion is on the multiset of verdicts rather than on which worker got
    which: which one wins is a race and is not a property of anything. That
    exactly one wins is the property.
    """
    assert REDIS_BACKEND_MARKER in settings.CACHES["default"]["BACKEND"], (
        f"{REDIS_URL_VARIABLE} is set but the cache is {settings.CACHES['default']['BACKEND']}; the variable "
        "never reached config/settings/test.py, so this case would be measuring the in-process substitution"
    )

    verdicts = sorted(_ask_together())

    assert verdicts == sorted([PERMITTED_EXIT] * WORKER_ALLOWANCE + [REFUSED_EXIT] * (WORKERS - WORKER_ALLOWANCE))


@needs_redis
def test_a_later_process_does_not_reset_a_window_it_did_not_start() -> None:
    """The half `add` buys, and the half the concurrent case above cannot see.

    `core/rate_limit.py` uses `add` -- create only if absent -- rather than
    `set`, and the difference is invisible when two processes overlap: both
    write the counter to zero before either increments it, so it reaches two and
    one is refused whichever verb was used. It becomes visible the moment the
    second process arrives *after* the first has finished, which is the ordinary
    case in a sweep. `set` would put the counter back to zero and hand a
    collector a second full allowance inside one window -- silently, and only
    under the load that makes rate limiting matter.

    So this one waits for the first worker before starting the second. The
    verdicts are asserted positionally rather than as a multiset, because here
    the order is the property: the first arrival wins.
    """
    first = _ask()
    second = _ask()

    assert [first, second] == [PERMITTED_EXIT, REFUSED_EXIT]


def _ask() -> int:
    """Run one worker to completion and return its verdict.

    Returns:
        The worker's exit code, checked against the two a verdict may be.

    """
    return _verdict(_start())


def _start() -> subprocess.Popen[str]:
    """Start one worker against the shared window.

    Returns:
        The running process, not yet waited on -- which is what lets the
        concurrent case start both before waiting for either.

    """
    # The whole environment, so the worker inherits the locality, the settings
    # module and `CPM_TEST_REDIS_URL` exactly as this process has them -- which
    # is what makes the two interpreters reach one cache. The settings module is
    # defaulted rather than assumed: pytest configures it from `pyproject.toml`,
    # and a run that had set it only there would leave the worker guessing.
    environment = dict(os.environ)
    environment.setdefault("DJANGO_SETTINGS_MODULE", DEFAULT_SETTINGS_MODULE)
    return subprocess.Popen(  # noqa: S603 - a fixed argument list, no shell, and every element is built here
        [sys.executable, str(WORKER_MODULE), A_COLLECTOR, FIXED_INSTANT.isoformat()],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _verdict(worker: subprocess.Popen[str]) -> int:
    """Wait for one worker and return the verdict it reported.

    Args:
        worker: The running process.

    Returns:
        Its exit code. `PERMITTED_EXIT` and `REFUSED_EXIT` are the two a worker
        may report; anything else means it never reached the limiter, and the
        message says so with its standard error attached rather than letting a
        crash read as a refusal.

    """
    _, failed = worker.communicate(timeout=WORKER_TIMEOUT_SECONDS)
    assert worker.returncode in (PERMITTED_EXIT, REFUSED_EXIT), (
        f"a worker exited {worker.returncode} rather than reporting a verdict; its stderr was:\n{failed}"
    )
    return worker.returncode


def _ask_together() -> list[int]:
    """Start both workers, then wait for both, and return their exit codes.

    Returns:
        One exit code per worker, in launch order. Every worker is started
        before any of them is waited on, which is what makes them overlap: a
        list comprehension that started and waited in one step would be two
        sequential runs wearing the shape of a concurrent one.

    """
    running = [_start() for _ in range(WORKERS)]
    return [_verdict(worker) for worker in running]
