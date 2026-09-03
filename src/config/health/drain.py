"""The `SIGTERM` handler that puts readiness ahead of the drain (AD-22, FR-43).

AD-22's word is *before*: "on `SIGTERM` readiness flips **before** the drain
begins". This module is that ordering and nothing else. It does not stop
accepting connections, does not finish in-flight requests and does not exit --
gunicorn and Celery already do all three, correctly, and a component that
reimplemented any of it would own a shutdown mechanism it cannot test against
every server it might be run under. What no server can do on the component's
behalf is know that this component answers a readiness probe, so that is the one
thing installed here.

**Why it delegates rather than replaces.** `signal.signal` returns the handler it
displaced, and this module keeps it and calls it. gunicorn installs its own
`SIGTERM` handler when it forks a worker and Celery installs one in
`install_platform_tweaks` before the consumer starts; either would be silently
discarded by a handler that took the slot and returned. The three shapes the
displaced handler can take are each handled explicitly, because the failure they
share -- a swallowed `SIGTERM` -- is a process that flips readiness, leaves the
routing pool and then never exits, which the platform resolves with `SIGKILL`
after the grace period and in-flight requests do not survive.

**Why the grace period is not here.** AD-22 gives its *value* to the deployment
repository: the platform's termination grace period and gunicorn's
`GUNICORN_CMD_ARGS` are the two knobs, and neither is a component-side flag. See
`docs/deployment.md`, "Shutdown". The component owns the ordering; that is the
whole of its half.

**Why the state lives in `config.health.state` and not here.** Readiness and the
drain flag are one state machine. `begin_drain()` and `is_draining()` are written
and read in `state.py` so that the view's drain-first ordering could be
implemented and tested before this handler existed, and so that the flip and the
flag cannot end up in two modules that disagree.
"""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING

import structlog

from config.health.state import begin_drain
from config.locality import component_process

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import FrameType
    from typing import Any

    #: Everything `signal.signal` can hand back as the displaced handler: a
    #: Python callable, one of the `SIG_DFL`/`SIG_IGN` constants (an `IntEnum`,
    #: hence `int`), or `None` for a handler installed from C that Python cannot
    #: describe. The `None` case is real rather than defensive -- an embedding
    #: runtime can install one -- and it is why the delegation below asks what
    #: the displaced handler *is* instead of assuming it is callable.
    PreviousHandler = Callable[[int, FrameType | None], Any] | int | None

__all__ = ["install_sigterm_handler", "reset_sigterm_handler_for_testing"]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: True once this process has installed the handler. The guard is what makes a
#: second `install_sigterm_handler()` a no-op rather than a second link in a
#: chain: without it, installing twice would capture *this module's own* handler
#: as the previous one and lose the server's, which is the swallowed-`SIGTERM`
#: failure arriving by the one route the delegation logic cannot see.
_installed: bool = False

#: The handler `install_sigterm_handler` displaced, kept so the signal reaches
#: it. Meaningless while `_installed` is False.
_previous_handler: PreviousHandler = None


def install_sigterm_handler() -> None:
    """Install the drain handler in front of whatever already handles `SIGTERM`.

    Idempotent, and safe to call from a process that cannot install a handler at
    all: `signal.signal` may only be called from the main thread, and a
    management command run in a thread must not fail to start because of a
    handler it has no use for. That case is logged and declined rather than
    raised.

    Called from `config/asgi.py` after the application is bound, and from the
    Celery `worker_ready` receiver in `config/celery_app.py`. Deliberately not
    from `manage.py`, from settings or from `AppConfig.ready()` -- `ready()` runs
    for every management command, and a `migrate` that flipped readiness on its
    way out would be describing a serving process it is not.
    """
    global _installed, _previous_handler  # noqa: PLW0603 - the guard and the captured handler are this module's state
    if _installed:
        logger.debug("drain.handler_already_installed", process=component_process())
        return

    try:
        # The return value rather than a preceding `signal.getsignal` call: it is
        # the same handler, read and replaced in one step, and it is not read at
        # all when the call below raises -- so a failed install captures nothing
        # to restore later.
        previous = signal.signal(signal.SIGTERM, _handle_sigterm)
    except ValueError:
        # Raised, and only raised, off the main thread. Named rather than caught
        # broadly: a TypeError here would mean `_handle_sigterm` has the wrong
        # signature, which is a defect in this module and must not be reported as
        # a threading condition.
        logger.warning("drain.handler_not_installed_off_main_thread", process=component_process())
        return

    _previous_handler = previous
    _installed = True
    logger.info("drain.handler_installed", process=component_process())


def _handle_sigterm(signum: int, frame: FrameType | None) -> None:
    """Flip readiness, say so once, then let the real shutdown proceed.

    The order is the acceptance criterion. `begin_drain()` runs first and
    unconditionally, so a readiness probe that arrives after the signal and
    before the server has closed its listening socket reads `503` and the load
    balancer removes this replica -- which is what makes the in-flight work this
    process is about to finish the *last* work it is given.

    Args:
        signum: The signal number the runtime delivered, passed on unchanged.
        frame: The interrupted stack frame, passed on unchanged.

    """
    begin_drain()
    # A signal handler has no request, so the Consistency Conventions' request_id
    # / trace_id / span_id are not available to it and the process type is what
    # identifies the emitter instead.
    logger.warning("drain.begin", process=component_process())
    _delegate(signum, frame)


def _delegate(signum: int, frame: FrameType | None) -> None:
    """Hand the signal to the handler this module displaced.

    Args:
        signum: The signal number, as delivered.
        frame: The interrupted stack frame, as delivered.

    """
    previous = _previous_handler
    if callable(previous):
        previous(signum, frame)
        return

    if previous == signal.SIG_DFL:
        # Re-installing the default first is what makes the re-raise terminate
        # rather than re-enter this handler. `raise_signal` delivers to this
        # thread synchronously, so the default action is taken here and now.
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.raise_signal(signum)
        return

    # `SIG_IGN`, or a handler installed from C that Python cannot call. Neither
    # can be delegated to and neither may be invented a replacement for: a
    # process whose SIGTERM was explicitly ignored must stay ignoring it, and
    # guessing at a C handler's behaviour would be a shutdown mechanism this
    # module has just finished refusing to own. Logged rather than passed over in
    # silence -- readiness has flipped and nothing else will happen.
    logger.warning("drain.delegation_declined", process=component_process(), previous=repr(previous))


def reset_sigterm_handler_for_testing() -> None:
    """Put the displaced handler back and forget that anything was installed.

    Named for its one caller the way `reset_health_state_for_testing()` is, and
    for the same reason plus a sharper one. `signal.signal` is process-global, so
    a handler leaked out of one case is installed for every case after it; and
    the `_installed` guard is *already tripped* by the time
    `tests/unit/test_drain.py` runs, because `tests/integration/` collects first
    under `pytest tests/` and `tests/integration/test_asgi_request_path.py`
    imports `config.asgi` at module scope. Without this helper every idempotence
    and delegation assertion would be made against a handler installed by an
    unrelated module's import, and would pass by describing that instead of the
    code under test.

    It lives beside the state it resets rather than in a conftest because
    `_installed` and `_previous_handler` are module-private: a fixture reaching
    in to rebind them would be a second place that knows their names and would go
    on "working" after a rename by rebinding nothing.
    """
    global _installed, _previous_handler  # noqa: PLW0603 - test helper, mirroring config.health.state's
    if _installed:
        # `None` cannot be handed back to `signal.signal`, so a displaced handler
        # Python could not describe is restored as the default. That is the
        # closest reachable approximation and it only ever happens in a test.
        signal.signal(signal.SIGTERM, signal.SIG_DFL if _previous_handler is None else _previous_handler)
    _installed = False
    _previous_handler = None
