"""The one clock in this product, and the one place a wall clock is read.

`CPM-AD-26`: freshness targets, observation windows, policy cut-offs and every
`observed_at` come from a clock that is passed in, never from `timezone.now()`
called where the work happens. The rule exists because the alternative is
untestable rather than because it is untidy -- a staleness rule that reads the
wall clock can only be tested by waiting, by patching the module it happens to
live in, or by freezing time process-wide, and the first is slow, the second
breaks when the call moves and the third is a dependency this project does not
carry. `R-03` has no credible mitigation without this.

`SystemClock.now` below is the **only** call to `timezone.now()` in this
repository outside a migration. Two inherited platform modules also read a wall
clock directly --
`django_service/users/management/commands/prune_expired_state.py` and
`config/local_dev/tokens.py` -- and they stay as they are: they sit outside
`CPM-EP-EVIDENCE`'s binding, and routing them through this module would make
`django_service` import a domain application, inverting the dependency direction
`AD-4` fixes. Both are recorded as counted exemptions in
`tests/unit/django_apps/test_clock_audit.py`, which licenses exactly one
occurrence in each file and fails on a second -- so the audit stays a gate rather
than becoming a list of directories it does not look in.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix. `AD-4` above is the platform's dependency direction
and `CPM-AD-26` is this product's clock rule -- two registers, not a typo.

**Injection is by parameter.** There is no module-level clock instance and no
`get_clock()`, deliberately: either would be a default a caller can reach for
without meaning to, and the whole benefit of the rule is that a component's
dependence on time is visible in its signature. A caller that wants the wall
clock constructs `SystemClock()` and passes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Protocol
from typing import runtime_checkable

from django.utils import timezone

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ["Clock", "FixedClock", "SystemClock"]


@runtime_checkable
class Clock(Protocol):
    """Something that can be asked for the current instant.

    One method, because one method is the entire dependency. A component that
    takes a `Clock` declares that it reads the time and declares nothing else,
    and a test supplies `FixedClock` without knowing anything about how the
    component uses it.

    `runtime_checkable` so that a test can assert an implementation satisfies
    the protocol at all. That check sees method *names* only, which is why
    `tests/unit/django_apps/test_clock.py` also pins the return value's shape:
    a class with a `now` returning a naive datetime passes `isinstance` and
    breaks every comparison it is used in.
    """

    def now(self) -> datetime:
        """Return the current instant.

        The docstring is the whole body. A protocol method is never executed, so
        an `...` here would be a permanently uncovered line and the only way to
        keep it out of the coverage floor would be a `pragma: no cover` --
        which `tests/unit/test_coverage_policy.py` bans outright, and rightly:
        a pragma is a line excusing itself from a measurement. A docstring-only
        body has no statement to miss.

        Returns:
            An aware `datetime` in UTC. Never naive: comparing a naive instant
            against an `observed_at` read back from PostgreSQL raises, and doing
            it inside a freshness computation raises in a Celery task rather
            than in a test.

        """


@dataclass(frozen=True, slots=True)
class SystemClock:
    """The wall clock, and the repository's one permitted `timezone.now()` call.

    `timezone.now()` rather than `datetime.now(tz=UTC)` because `USE_TZ` is on:
    Django's helper is what the ORM's own defaults and lookups use, so an
    `observed_at` written from here and one written by a field default are the
    same kind of instant.
    """

    def now(self) -> datetime:
        """Return the current instant from the wall clock.

        Returns:
            An aware `datetime` in UTC.

        """
        # The one direct wall-clock read in this repository. The counted
        # exemption in tests/unit/django_apps/test_clock_audit.py points here,
        # and licenses exactly one occurrence in this file.
        return timezone.now()


@dataclass(frozen=True, slots=True)
class FixedClock:
    """A clock stopped at one instant, for tests and for replay.

    Every reader handed one of these observes the same instant, however many
    times it asks and in whatever order the readers run -- which is what makes a
    staleness assertion a statement about the rule rather than about how long
    the test took.

    Frozen, so a case cannot advance it by assignment and leave a later
    assertion in the same test reading a different instant than the one it was
    written against. A case that needs two instants constructs two clocks.

    **Aware instants are converted to UTC rather than stored as given.** The
    protocol promises UTC and `SystemClock` delivers it, so a fixed clock
    answering in `America/New_York` would be a stand-in that differs from the
    thing it stands in for on the one axis every stored timestamp depends on --
    the architecture spine fixes every persisted instant as UTC. The conversion
    is loss-free: the returned instant compares equal to the one that was passed,
    because it *is* the same instant, and only its rendering changes. Refusing
    instead would make a clock built from an operator's local time an error for
    no gain, and storing as given would leave the docstring's UTC claim false.

    Attributes:
        instant: The aware UTC instant every call returns. Normalised at
            construction, so it is not always the exact object passed in.

    """

    instant: datetime

    def __post_init__(self) -> None:
        """Refuse a naive instant, and put an aware one into UTC.

        Raises:
            ValueError: When `instant` carries no timezone. A naive instant
                would satisfy the protocol's method name and fail every
                comparison made against a value read back from the database --
                and it would fail there, in whatever code took the clock, rather
                than here where the mistake was made. It cannot be converted
                either: there is no offset to convert from, and guessing one is
                how a test comes to pass in one timezone and fail in another.

        """
        if self.instant.tzinfo is None or self.instant.tzinfo.utcoffset(self.instant) is None:
            message = f"a fixed clock needs an aware instant; {self.instant!r} is naive"
            raise ValueError(message)
        if self.instant.utcoffset() != timedelta(0):
            # `object.__setattr__` because the dataclass is frozen, which is the
            # documented way to normalise a field in `__post_init__`. Frozen is
            # worth keeping: it is what stops a case winding the clock forward
            # by assignment.
            object.__setattr__(self, "instant", self.instant.astimezone(UTC))

    def now(self) -> datetime:
        """Return the instant this clock was constructed with.

        Returns:
            The same aware UTC `datetime` on every call.

        """
        return self.instant
