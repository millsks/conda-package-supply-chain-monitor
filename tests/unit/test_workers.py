"""The `web` process's drain, and the upstream shape the fix is copied from.

`config/health/drain.py` installs a `SIGTERM` handler that flips readiness before
the drain begins, and in `worker` and `beat` that handler is what runs. In `web`
it is not: `uvicorn.Server.serve()` opens `with self.capture_signals():`, which
replaces every handled signal unconditionally, after the application -- and
therefore `config.asgi`'s handler installation -- has already been imported. So
`config.workers.DrainingServer` overrides the callable uvicorn installs instead.

Two things are asserted here and they fail for different reasons:

* **The behaviour.** `handle_exit` flips readiness *and* delegates. Either half
  alone is a defect: a flip that does not delegate is a process that goes
  unready and never shuts down; a delegation that does not flip is the bug this
  story exists to fix.
* **The coupling.** `_serve` is a copy of four upstream statements, because
  `uvicorn_worker` constructs `Server(config=self.config)` from a module-level
  name with no overridable seam. The pin below fails on a `uvicorn-worker`
  upgrade that changes that shape, which is the one event that would silently
  restore the bug.

**Every case here returns early off POSIX, and the imports are guarded with it.**
`pixi.toml` declares `gunicorn` and `uvicorn-worker` only under
`[target.linux-64.dependencies]` and `[target.osx-arm64.dependencies]` -- gunicorn
is POSIX-only and has no conda-forge win-64 build -- while
`.github/workflows/ci.yml` runs `pixi run test` on `windows-latest`. There the
subject of this module is not installed, and importing it at collection time fails
the whole run.

Branched rather than skipped: `tests/unit/test_suite_policy.py` bans
`skip`/`skipif`/`xfail` *and* `pytest.importorskip`, with one recorded exemption
that is not this one. `tests/unit/test_local_dev_keys.py` uses the same
branch-and-return shape for its POSIX-only mode assertions. Nothing is lost by it:
the `web` process runs only where gunicorn does, so there is no Windows deployment
for these cases to be silent about.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import os
import signal
import textwrap
from typing import TYPE_CHECKING

import pytest

from config.health.state import is_draining
from config.health.state import reset_health_state_for_testing

#: True where `gunicorn` and `uvicorn-worker` are installed, which `pixi.toml`
#: scopes to the two POSIX targets. Read at import, because it decides whether the
#: imports below can happen at all.
ON_POSIX = os.name == "posix"

if ON_POSIX:
    import uvicorn_worker
    from uvicorn.config import Config
    from uvicorn.server import Server

    from config import workers
    from config.workers import DrainingServer
    from config.workers import DrainingUvicornWorker

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Drain state is process-global; a leak makes a later case pass for the wrong reason."""
    reset_health_state_for_testing()


class TestTheDrainingServer:
    """AC #1 for the `web` process: readiness flips before the drain begins."""

    def test_handle_exit_flips_readiness(self) -> None:
        """The acceptance criterion itself."""
        if not ON_POSIX:
            return

        server = DrainingServer(config=_config())

        assert not is_draining()
        server.handle_exit(signal.SIGTERM, None)

        assert is_draining()

    def test_handle_exit_still_shuts_the_server_down(self) -> None:
        """The other half. A flip that does not delegate never exits.

        `should_exit` is uvicorn's own shutdown latch, set by the base
        implementation. Asserting it is what proves `super().handle_exit` was
        reached rather than replaced.
        """
        if not ON_POSIX:
            return

        server = DrainingServer(config=_config())

        server.handle_exit(signal.SIGTERM, None)

        assert server.should_exit is True

    def test_the_flip_precedes_the_shutdown_latch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Order, not just presence -- AD-22's word is *before*.

        Both assertions above pass against a `handle_exit` that shut down first
        and flipped afterwards, which is the sequence that lets a probe arriving
        between the two read 200 on a process already closing its socket. The
        flip is wrapped so it can record uvicorn's own latch at the instant it
        runs: `should_exit` must still be False there.
        """
        if not ON_POSIX:
            return

        server = DrainingServer(config=_config())
        latched_at_flip: list[bool] = []
        original = workers.begin_drain

        def _recording() -> None:
            latched_at_flip.append(server.should_exit)
            original()

        monkeypatch.setattr(workers, "begin_drain", _recording)
        server.handle_exit(signal.SIGTERM, None)

        assert latched_at_flip == [False], "uvicorn had already latched the shutdown when readiness flipped"
        assert server.should_exit is True

    def test_a_second_signal_still_reaches_uvicorns_escalation(self) -> None:
        """The flip never guards the delegation, so an escalating platform is not swallowed."""
        if not ON_POSIX:
            return

        server = DrainingServer(config=_config())

        server.handle_exit(signal.SIGTERM, None)
        server.handle_exit(signal.SIGINT, None)

        assert server.force_exit is True


class TestTheHandlerUvicornActuallyInstalls:
    """The loop the original bug slipped through, closed.

    Story 5.3's and 5.4's drain tests invoke the `SIGTERM` handler as a plain
    function -- they call whatever `signal.getsignal` returns, or the module
    function directly. That is why the `web` process could be broken while every
    one of them passed: in a real `web` process the handler they exercise is the
    one `uvicorn.Server.capture_signals()` threw away.

    These cases run uvicorn's own installation instead and ask what is actually
    registered afterwards. They fail if the fix is reverted, and they would have
    failed before it.
    """

    def test_capture_signals_installs_the_draining_handler(self) -> None:
        """What uvicorn registers for SIGTERM is *our* `handle_exit`, not the stock one."""
        if not ON_POSIX:
            return

        server = DrainingServer(config=_config())

        with server.capture_signals():
            installed = signal.getsignal(signal.SIGTERM)

        assert getattr(installed, "__self__", None) is server
        assert getattr(installed, "__func__", None) is DrainingServer.handle_exit

    def test_the_installed_handler_flips_readiness_when_it_is_called(self) -> None:
        """End to end through uvicorn's own installation: register, then invoke what is registered.

        The two halves are asserted together on purpose. Registering the right
        object proves nothing if calling it does not drain, and draining proves
        nothing if uvicorn registered something else.

        Wrapped in `_absorbing_sigterm` because `capture_signals` re-raises every
        signal it captured on the way out, *after* restoring the handler it
        displaced -- so without an absorbing handler in place beforehand this case
        delivers a real `SIGTERM` to the test runner under the default
        disposition and kills it mid-session. Found by writing it without one.
        """
        if not ON_POSIX:
            return

        server = DrainingServer(config=_config())

        with _absorbing_sigterm(), server.capture_signals():
            installed = signal.getsignal(signal.SIGTERM)
            assert callable(installed)
            installed(signal.SIGTERM, None)

        assert is_draining()
        assert server.should_exit is True

    def test_uvicorn_reraises_what_it_captured_on_the_way_out(self) -> None:
        """The behaviour the case above has to work around, asserted rather than worked around silently.

        It is also load-bearing for the component: it is how a `web` process that
        was asked to stop actually stops once uvicorn's graceful shutdown has
        finished. A future uvicorn that stopped re-raising would change what
        `SIGTERM` does to the serving process, and this is where that shows up.
        """
        if not ON_POSIX:
            return

        server = DrainingServer(config=_config())
        delivered: list[int] = []

        with _absorbing_sigterm(delivered), server.capture_signals():
            installed = signal.getsignal(signal.SIGTERM)
            assert callable(installed)
            installed(signal.SIGTERM, None)

        assert delivered == [signal.SIGTERM]

    def test_capture_signals_restores_what_it_displaced(self) -> None:
        """The block leaves the process's handler as it found it, so cases stay independent.

        No absorbing handler is needed here: nothing calls the installed handler,
        so `_captured_signals` stays empty and there is nothing to re-raise.
        """
        if not ON_POSIX:
            return

        before = signal.getsignal(signal.SIGTERM)
        server = DrainingServer(config=_config())

        with server.capture_signals():
            pass

        assert signal.getsignal(signal.SIGTERM) is before


class TestTheUpstreamCouplingIsPinned:
    """`_serve` is a copy; this is what notices when the original changes."""

    def test_the_worker_subclasses_the_stock_one(self) -> None:
        """Everything except the server class is inherited, and that is deliberate."""
        if not ON_POSIX:
            return

        assert issubclass(DrainingUvicornWorker, uvicorn_worker.UvicornWorker)

    def test_upstream_still_builds_its_server_inside_serve(self) -> None:
        """The reason `_serve` had to be overridden at all.

        If a future `uvicorn-worker` exposes the server class as an attribute,
        this fails and the override should be replaced by setting it -- which is
        a smaller and supported seam. A failure here is an invitation, not a
        defect.
        """
        if not ON_POSIX:
            return

        # SLF001 is the point of the case, not an oversight: `_serve` being private
        # with no public seam is exactly what forced the copy, so the pin has to
        # read the private member to notice when that stops being true.
        source = inspect.getsource(uvicorn_worker.UvicornWorker._serve)  # noqa: SLF001

        assert "Server(config=self.config)" in source, (
            "uvicorn_worker no longer constructs Server inside _serve; "
            "config.workers.DrainingUvicornWorker._serve was copied from that shape and must be revisited"
        )

    def test_the_override_matches_the_upstream_statement_for_statement(self) -> None:
        """The copy is a copy. One name differs and nothing else does.

        A drifted override is how a uvicorn-worker fix -- a new call, a changed
        exit path -- would be silently dropped from the `web` process. Compared
        on normalized source rather than by eye.
        """
        if not ON_POSIX:
            return

        upstream = _normalize(inspect.getsource(uvicorn_worker.UvicornWorker._serve))  # noqa: SLF001 - see above
        ours = _normalize(inspect.getsource(DrainingUvicornWorker._serve))  # noqa: SLF001 - see above

        assert ours == upstream.replace("Server(config=self.config)", "DrainingServer(config=self.config)"), (
            "config.workers.DrainingUvicornWorker._serve has drifted from the upstream statements it copies"
        )

    def test_the_server_uvicorn_would_have_used_is_the_one_we_subclass(self) -> None:
        """A pin on the identity of the base, so a vendored fork is noticed."""
        if not ON_POSIX:
            return

        assert issubclass(DrainingServer, Server)


@contextlib.contextmanager
def _absorbing_sigterm(delivered: list[int] | None = None) -> Iterator[None]:
    """Hold `SIGTERM` harmless for the duration of a block, recording what arrives.

    `uvicorn.Server.capture_signals` re-raises every captured signal as it exits,
    after restoring the handler that was in place when it was entered. Under
    pytest that handler is the default disposition, which terminates the runner --
    so a case that drives `capture_signals` and calls the installed handler must
    put something absorbing in place first.

    Args:
        delivered: Optional list to record the signal numbers that arrive.

    Yields:
        None, with `SIGTERM` bound to a handler that records and returns.

    """
    record = delivered if delivered is not None else []

    def _absorb(signum: int, _frame: object | None) -> None:
        record.append(signum)

    original = signal.signal(signal.SIGTERM, _absorb)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, original)


def _config() -> Config:
    """Return the smallest uvicorn config a `Server` will accept.

    Returns:
        A config naming a trivial ASGI callable. Nothing is served: every case
        here calls `handle_exit` directly, which touches no socket and no loop.

    """
    return Config(app=_noop_app)


async def _noop_app(scope: object, receive: object, send: object) -> None:
    """Stand in for the application. Never called.

    Args:
        scope: Unused.
        receive: Unused.
        send: Unused.

    """
    return


def _normalize(source: str) -> str:
    """Return a function's statements as source, with its docstring and comments gone.

    Parsed rather than filtered line by line: a docstring is a statement, and
    recognizing one by its quotes mistakes a multi-line docstring's body for code
    and a bare string expression for a docstring.

    Args:
        source: The source of a function, as `inspect.getsource` returns it.

    Returns:
        The unparsed body statements, one per line, docstring excluded.

    """
    function = ast.parse(textwrap.dedent(source)).body[0]
    assert isinstance(function, ast.AsyncFunctionDef | ast.FunctionDef)
    body = function.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return "\n".join(ast.unparse(node) for node in body)
