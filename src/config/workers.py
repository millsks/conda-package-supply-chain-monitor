"""The gunicorn worker class the `web` process runs, and why it is not the stock one.

AD-22's word is *before*: "on `SIGTERM` readiness flips **before** the drain
begins". `config/health/drain.py` installs a `SIGTERM` handler that does exactly
that, and in `worker` and `beat` it is the handler that runs. In `web` it is not,
and no amount of care in that module could have made it so.

**What displaces it, in order.** `gunicorn` forks a worker, and
`uvicorn_worker.UvicornWorker.init_signals()` resets every handled signal to
`SIG_DFL` (`uvicorn_worker/_workers.py`). The worker then loads the application,
which imports `config.asgi` and installs the drain handler -- correctly, and after
the reset, so at that moment it is live. Then `uvicorn.Server.serve()` opens
`with self.capture_signals():`, whose body is
`{sig: signal.signal(sig, self.handle_exit) for sig in HANDLED_SIGNALS}`
(`uvicorn/server.py`). It replaces the handler unconditionally and keeps the
displaced one only to restore on the way out. So the drain flip never runs while
the process is draining, which is the one moment it exists for.

`config/health/drain.py` delegates to the handler it displaced; nothing can
delegate to a handler that displaced *it* afterwards. The fix has to be at the
layer that installs last, and that layer is uvicorn's `Server`.

**What this module does instead.** `DrainingServer` overrides `handle_exit` -- the
callable uvicorn installs -- to flip readiness first and then hand off to
uvicorn's own implementation unchanged. The flip is `begin_drain()`, the same
function the signal handler calls, so `web` and `worker` reach the same state
through the same function and there is one definition of what draining means.
Nothing about uvicorn's shutdown sequence is reimplemented or reordered: the
override is two statements, and the second is `super()`.

**The coupling this accepts, stated plainly.** `uvicorn_worker` constructs
`Server(config=self.config)` inside `_serve` as a module-level name rather than a
class attribute, so there is no supported seam and `_serve` is overridden with a
copy of its four upstream statements. That is a version coupling, and
`tests/unit/test_workers.py` pins it: it asserts the upstream `_serve` still has
the shape this override was copied from, so a uvicorn-worker upgrade that changes
it fails the gate here rather than silently restoring the bug. Pinning a private
method is the cost of the seam not existing; the alternative was reimplementing
uvicorn's shutdown, which is far worse.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import structlog
from gunicorn.arbiter import Arbiter
from uvicorn.server import Server
from uvicorn_worker import UvicornWorker

from config.health.state import begin_drain
from config.locality import component_process

if TYPE_CHECKING:
    from types import FrameType

__all__ = ["DrainingServer", "DrainingUvicornWorker"]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class DrainingServer(Server):
    """A uvicorn server that flips readiness to draining before it begins shutting down."""

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        """Flip readiness, then shut down exactly as uvicorn would.

        The order is the acceptance criterion, and it is the whole of this
        method's content. A readiness probe arriving after the signal and before
        the listening socket closes reads 503, so the load balancer stops routing
        here while the in-flight requests this process already accepted are
        finished -- which is what makes them the last work it is given.

        `begin_drain()` is idempotent and this is called once per handled signal,
        but a second signal (the platform escalating `SIGTERM` to `SIGINT`) must
        still reach uvicorn's own escalation path, so the flip never guards the
        `super()` call.

        Args:
            sig: The signal number the runtime delivered, passed on unchanged.
            frame: The interrupted stack frame, passed on unchanged.

        """
        begin_drain()
        # No request exists in a signal handler, so the Consistency Conventions'
        # request_id / trace_id / span_id are unavailable and the signal is what
        # identifies the event instead.
        logger.warning("drain.begin", process=component_process(), signal=sig)
        super().handle_exit(sig, frame)


# `uvicorn_worker` ships no type information, so mypy sees `UvicornWorker` as
# `Any` and refuses the subclass under strict mode. Narrowly ignored on the one
# line that needs it rather than silenced with a module-wide override: the
# override would also hide a real error in the four statements copied below,
# which are the part of this file most likely to break on an upgrade.
class DrainingUvicornWorker(UvicornWorker):  # type: ignore[misc]
    """The stock uvicorn worker, running `DrainingServer` in place of `Server`."""

    async def _serve(self) -> None:
        """Serve on `DrainingServer`, otherwise exactly as `UvicornWorker` does.

        A copy of upstream's four statements with one name changed, because
        `uvicorn_worker` builds `Server(config=self.config)` from a module-level
        import rather than from an overridable attribute. See the module
        docstring for why this coupling is accepted and
        `tests/unit/test_workers.py` for what pins it.
        """
        self.config.app = self.wsgi
        server = DrainingServer(config=self.config)
        self._install_sigquit_handler()
        await server.serve(sockets=self.sockets)
        if not server.started:
            sys.exit(Arbiter.WORKER_BOOT_ERROR)
