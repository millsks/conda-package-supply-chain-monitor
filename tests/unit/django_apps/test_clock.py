"""Tests for the two clocks `CPM-AD-26` puts in `core`.

The audit in `tests/unit/django_apps/test_clock_audit.py` proves nothing reads a
wall clock directly. This module proves the thing everything is meant to read
instead actually works: the production clock answers with an aware UTC instant,
the fixed one answers with exactly what it was handed, and a reader that takes a
`Clock` observes whichever it was given.

No database, no network, no filesystem. `SystemClock.now()` reads the process
clock, which is the one piece of ambient state a clock is allowed to have; the
assertions about it are about the *shape* of what comes back rather than about
its value, so nothing here can be made to fail by the hour the suite runs at.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import TYPE_CHECKING

import pytest

from conda_package_supply_chain_monitor.core.clock import Clock
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.clock import SystemClock
from tests.clocks import FIXED_INSTANT

if TYPE_CHECKING:
    from collections.abc import Callable

# A naive instant, which is what a `datetime(...)` written without `tzinfo`
# produces and what `FixedClock` refuses.
A_NAIVE_INSTANT = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - the refusal below is what this is for

# A second instant, far enough from the first that no rounding could confuse
# them. Used to show that two clocks are independent rather than sharing state.
ANOTHER_INSTANT = datetime(2019, 3, 1, 6, 30, tzinfo=UTC)

# The same instant as `FIXED_INSTANT`, rendered at a non-UTC offset. Equal to it
# as a moment in time and unequal to it in `tzinfo`, which is the whole point:
# `FixedClock` must normalise rather than store what it was handed.
A_NON_UTC_OFFSET = timezone(timedelta(hours=-4))
FIXED_INSTANT_ELSEWHERE = FIXED_INSTANT.astimezone(A_NON_UTC_OFFSET)


class NotAClock:
    """Something with no `now`, used as the protocol's negative control."""

    def instant(self) -> None:
        """Do nothing; the class exists for the name it does *not* have."""


def observed_at(clock: Clock) -> datetime:
    """Stand in for every component that will take a clock.

    A collector recording `observed_at`, a freshness computation, a policy
    cut-off: each is this function with more code around it. It is typed on the
    protocol rather than on either implementation, which is the property the
    injection rule is really about -- the component cannot tell which clock it
    was handed, so a test and production differ only in the argument.

    Args:
        clock: The clock to read.

    Returns:
        The instant that clock reports.

    """
    return clock.now()


def test_the_fixed_clock_returns_the_instant_it_was_given(fixed_clock: FixedClock) -> None:
    """Row 12 of the matrix: a test supplies an instant, the reader observes it."""
    assert observed_at(fixed_clock) == FIXED_INSTANT
    assert fixed_clock.instant == FIXED_INSTANT


def test_the_fixed_clock_returns_the_same_instant_every_time(fixed_clock: FixedClock) -> None:
    """Stopped, not merely seeded.

    A clock that advanced between two reads would make every window assertion
    depend on how long the code under test took, which is the flakiness
    `CPM-AD-26` exists to remove rather than relocate.
    """
    assert fixed_clock.now() is fixed_clock.now()


def test_two_fixed_clocks_are_independent() -> None:
    """A case needing two instants constructs two clocks, and they do not share.

    `FixedClock` is frozen precisely so that "advance the clock" is spelled as a
    second object rather than as an assignment a later assertion in the same test
    would silently inherit.
    """
    earlier = FixedClock(instant=ANOTHER_INSTANT)
    later = FixedClock(instant=FIXED_INSTANT)

    assert observed_at(earlier) == ANOTHER_INSTANT
    assert observed_at(later) == FIXED_INSTANT
    assert earlier.now() < later.now()


def test_the_fixed_clock_cannot_be_wound_forward() -> None:
    """Frozen, so the independence above cannot be undone by an assignment."""
    clock = FixedClock(instant=FIXED_INSTANT)

    with pytest.raises((AttributeError, TypeError)):
        clock.instant = ANOTHER_INSTANT


def test_a_naive_instant_is_refused_at_construction() -> None:
    """The mistake is caught where it is made, not where it is compared.

    A naive instant satisfies the protocol's method name and then raises inside
    whatever compared it against a value read back from PostgreSQL -- in a Celery
    task, days later, in code that did nothing wrong.
    """
    with pytest.raises(ValueError, match="naive"):
        FixedClock(instant=A_NAIVE_INSTANT)


def test_the_system_clock_returns_an_aware_utc_instant() -> None:
    """What `CPM-AD-26` requires of the production implementation.

    UTC specifically, not merely aware: `Timestamps` in the architecture spine's
    conventions table fixes every stored instant as UTC, and an aware instant in
    some other offset would compare correctly and then serialize differently on
    every export surface.
    """
    instant = observed_at(SystemClock())

    assert instant.tzinfo is not None
    assert instant.utcoffset() == timedelta(0)


def test_the_system_clock_advances() -> None:
    """It is a wall clock, so two reads are not the same object.

    Asserted as monotonic-or-equal rather than strictly increasing: two reads can
    land in the same clock tick, and a test that demanded a difference would be
    the flaky one.
    """
    clock = SystemClock()

    first = clock.now()
    second = clock.now()

    assert second >= first


def test_an_aware_instant_at_another_offset_is_normalised_to_utc() -> None:
    """The protocol promises UTC, so a stand-in that answers in -04:00 is not one.

    Equal as a moment and different as a rendering -- which is exactly why
    storing it as given would be the silent failure: every comparison in a test
    would pass, and the value written to a column would serialize differently
    from one written by `SystemClock` on every export surface.
    """
    clock = FixedClock(instant=FIXED_INSTANT_ELSEWHERE)

    assert clock.now() == FIXED_INSTANT
    assert clock.now().utcoffset() == timedelta(0)
    assert clock.now().tzinfo is UTC


def test_an_object_without_a_now_is_not_a_clock() -> None:
    """The protocol's negative control.

    Without it, widening `Clock` -- or deleting `now` from it outright -- would
    leave every `isinstance` assertion in this module green, because a protocol
    with no members accepts everything.
    """
    assert not isinstance(NotAClock(), Clock)


@pytest.mark.parametrize(
    "build",
    [SystemClock, lambda: FixedClock(instant=FIXED_INSTANT)],
    ids=["system", "fixed"],
)
def test_both_implementations_satisfy_the_protocol(build: Callable[[], Clock]) -> None:
    """`isinstance` against the runtime-checkable protocol, plus the shape it cannot see.

    `runtime_checkable` compares method *names* only, so it would accept a class
    whose `now` returned a string. The return-value assertions are what make this
    a check of the contract rather than of the spelling, and
    `test_an_object_without_a_now_is_not_a_clock` is what stops the `isinstance`
    half from being true of everything.
    """
    clock = build()

    assert isinstance(clock, Clock)
    assert isinstance(observed_at(clock), datetime)
    assert observed_at(clock).utcoffset() == timedelta(0)
