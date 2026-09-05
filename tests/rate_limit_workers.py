"""The worker process the shared-allowance proof needs, and nothing else.

`core/rate_limit.py` writes `add`-then-`incr` rather than read-compare-write for
one stated reason: two *processes* racing to start a window must both increment
one counter instead of one of them resetting the other. Under `LocMemCache` each
process holds its own counter, so that property cannot fail however the limiter
is written -- every case in `tests/unit/django_apps/test_rate_limit.py` would
pass against a limiter that lost the race, because there is no second process for
it to lose to.

`tests/integration/django_apps/test_shared_allowance.py` is the case that can
fail, and this module is what it runs: a whole second interpreter that configures
Django from the environment it inherits, asks one limiter for one allowance in
one window, and says what it was told. Two of them against a `redis:7` container
is the same move `scripts/gate-postgres.sh` already makes for schema behaviour,
and for the same reason -- the property is a property of the real backend.

**The verdict is an exit code, not output.** A worker that wrote to stdout would
need the parent to parse it, and a parse is a second thing that can be wrong: an
empty read, a buffering difference or a stray warning line would each look like a
refusal. An exit code cannot be any of those, and it keeps this module clear of
`print` -- which this repository forbids outright -- without reaching for a
logger whose output the parent would then have to filter.

**What is on the command line is the window.** A window is a collector name and
an instant (`core/rate_limit.py`'s `window_key` divides the instant by the window
length), so those two are what the parent passes and what makes both workers ask
about the *same* window. Everything else -- the allowance, the window length, the
cost -- is a module constant that both the workers and the parent import, so the
two processes cannot come to disagree about the declaration they are testing.

A helper module, not a collected one. `[tool.pytest.ini_options] python_files`
matches `test_*.py` and `tests.py`, so nothing here is collected, and it sits at
`tests/` for the reason `tests/collectors.py` and `tests/source_scan.py` do: a
collected test module is not a helper library.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from datetime import timedelta
from typing import Final

#: What the process exits with when the allowance covered the request, and when
#: it did not. `0` and `3` rather than `0` and `1`: an exit code of `1` is what a
#: traceback also produces, so a parent reading it could not tell "the limiter
#: refused" from "the worker never reached the limiter" -- and the second of
#: those, read as the first, is a proof that passes because it broke.
PERMITTED_EXIT: Final[int] = 0
REFUSED_EXIT: Final[int] = 3

#: The allowance both workers count against. One request, so the pair is
#: decisive: with a shared counter exactly one of them is permitted, and with a
#: per-process counter both are. There is no arithmetic between those two
#: outcomes for a race to make ambiguous.
WORKER_ALLOWANCE: Final[int] = 1

#: The window both workers land in. A minute, which is long enough that the two
#: processes' start-up times cannot put them either side of a boundary -- and the
#: instant is passed in anyway, so the boundary is a property of the argument
#: rather than of when Python finished importing Django.
WORKER_WINDOW: Final[timedelta] = timedelta(minutes=1)

#: What one worker's ask costs. One, the same as its allowance: this module is
#: about the counter being shared, not about the retry-budget arithmetic
#: `tests/unit/django_apps/test_rate_limit.py` proves.
WORKER_COST: Final[int] = 1

#: The settings module a worker configures Django with when the environment
#: names none. The same one the suite runs under, so the cache the worker reaches
#: is the cache `CPM_TEST_REDIS_URL` selected.
DEFAULT_SETTINGS_MODULE: Final[str] = "config.settings.test"

#: How many arguments the entry point takes, after the program name.
EXPECTED_ARGUMENTS: Final[int] = 2


def main(argv: list[str]) -> int:
    """Ask once for the allowance in the named window and report the verdict.

    Django is configured here rather than at import, so importing this module --
    which the parent does, for the constants above -- does not stand up an
    application.

    Args:
        argv: The arguments after the program name: the collector's name and the
            instant the window is decided from, as ISO 8601 with an offset.

    Returns:
        `PERMITTED_EXIT` when the allowance covered the request, `REFUSED_EXIT`
        when it did not.

    Raises:
        SystemExit: When the arguments are not the two this entry point takes.
            Raised rather than defaulted: a worker that invented a window would
            report a verdict about a counter the other worker never touched, and
            the proof would pass while proving nothing.

    """
    if len(argv) != EXPECTED_ARGUMENTS:
        message = f"usage: rate_limit_workers.py <collector> <instant>; got {argv!r}"
        raise SystemExit(message)
    collector, instant = argv

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", DEFAULT_SETTINGS_MODULE)
    import django  # noqa: PLC0415 - configured per process; see the docstring

    django.setup()

    from conda_package_supply_chain_monitor.core.rate_limit import CacheRateLimiter  # noqa: PLC0415 - as above
    from conda_package_supply_chain_monitor.core.rate_limit import RateLimit  # noqa: PLC0415 - as above

    permitted = CacheRateLimiter().acquire(
        collector=collector,
        limit=RateLimit(calls=WORKER_ALLOWANCE, per=WORKER_WINDOW),
        now=datetime.fromisoformat(instant),
        cost=WORKER_COST,
    )
    return PERMITTED_EXIT if permitted else REFUSED_EXIT


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
