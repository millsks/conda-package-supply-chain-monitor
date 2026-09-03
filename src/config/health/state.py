"""The two flags readiness answers from, held as per-process module state (AD-22).

**Why module state and not the cache.** AD-10 records the reasoning for the epoch
record and it applies unchanged here: two of the six valid combinations select no
`redis` feature, so in those the cache is Django's in-process backend. A flag
written to `django.core.cache` would therefore be per-process in some
combinations and shared in others, which is the worst of both -- the same code
would mean two different things depending on a feature selection this module
knows nothing about. Making it module state makes it per-process *everywhere*,
which is the only reading that is true in all six.

**Why per-process is the correct scope rather than a compromise.** Both flags are
observations a process makes about its own history. `first_contact_made` records
that *this* process has spoken to its databases at least once; a replica that has
just started has not, whatever its siblings have done, and a shared flag would
report the new replica ready on the strength of an older one's success -- exactly
the state AC #3 exists to refuse. `draining` records that *this* process has been
asked to stop serving; a shared flag would drain the whole estate on one pod's
`SIGTERM`.

So NFR-3's "nothing shared through local disk or process memory across replicas"
is honoured rather than bent: nothing here is shared across replicas, and nothing
here is written to disk. The state is born `False` on every process start, which
is the fail-closed reading -- a process that has not yet proved it can reach its
databases is not ready, and a restart is not a shortcut past that proof.

**Why a plain module and not a Django app.** There is no model, no signal
registration and no `AppConfig.ready()` work to do. An app would add an
`INSTALLED_APPS` entry that AD-24 would then have to keep in step with a feature
it does not belong to, in exchange for nothing.

`begin_drain` is written by Story 5.4's `SIGTERM` handler and by nothing else;
it lives here rather than there so that `readiness`'s drain-first ordering can be
implemented and tested before that handler exists.
"""

from __future__ import annotations

__all__ = [
    "begin_drain",
    "first_contact_made",
    "is_draining",
    "mark_first_contact",
    "reset_health_state_for_testing",
]

#: True once this process has successfully reached every required database at
#: least once. Readiness is non-200 until it flips, which is AC #3.
_first_contact_made: bool = False

#: True once this process has been asked to stop serving. Story 5.4 sets it from
#: the `SIGTERM` handler; readiness reads it before it reads anything else, so a
#: draining process is removed from the load balancer's pool before its
#: in-flight work finishes rather than after.
_draining: bool = False


def mark_first_contact() -> None:
    """Record that this process has reached every required database at least once.

    Idempotent and one-way. Readiness calls it on every successful probe rather
    than only on the first, because a caller that had to know whether the flag was
    already set would have to read it and write it as two steps -- and the flag is
    written from the request path, where two steps are two chances to interleave.
    """
    global _first_contact_made  # noqa: PLW0603 - the flag is the module's state; see the module docstring
    _first_contact_made = True


def first_contact_made() -> bool:
    """Report whether this process has ever reached every required database.

    Returns:
        False from process start until the first fully successful readiness
        probe, True afterwards. It never returns to False: a database that goes
        away after first contact makes readiness refuse on the probe result, not
        by rewinding this flag, because "this process has never spoken to its
        database" and "this process cannot speak to its database right now" are
        different states and only the first one is what AC #3 asks about.

    """
    return _first_contact_made


def begin_drain() -> None:
    """Record that this process is shutting down and must stop being routed to.

    One-way by construction: a process that has begun draining does not return to
    service, and an accessor that could clear the flag would invite a caller that
    tried to.
    """
    global _draining  # noqa: PLW0603 - the flag is the module's state; see the module docstring
    _draining = True


def is_draining() -> bool:
    """Report whether this process has begun draining.

    Returns:
        True once `begin_drain` has been called in this process.

    """
    return _draining


def reset_health_state_for_testing() -> None:
    """Return both flags to the value a freshly started process holds.

    Named for its one caller the way `config.observability.telemetry`'s
    equivalent is. Process-global state that only ever moves one way is the right
    shape for a serving process and the wrong shape for a test session, where one
    case's success would otherwise be the next case's starting condition -- a
    leaked `True` makes a later readiness assertion pass without the code under
    test having done anything. The autouse fixtures in
    `tests/unit/test_health_views.py` and `tests/integration/test_health.py` call
    this before and after every case, so no ordering makes one of them true for
    the wrong reason.

    It lives beside the flags rather than in a conftest because the flags are
    module-private: a fixture reaching in to rebind them would be a second place
    that knows their names, and would keep working while silently rebinding the
    wrong one after a rename.
    """
    global _first_contact_made, _draining  # noqa: PLW0603 - test helper
    _first_contact_made = False
    _draining = False
