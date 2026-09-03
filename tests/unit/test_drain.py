"""Tests for the `SIGTERM` handler that orders the drain (AD-22, FR-43).

The load-bearing case here is
`test_the_flip_happens_before_the_previous_handler_runs`. AD-22's rule is an
*ordering*, so asserting that readiness flipped and that the server's handler ran
would pass just as happily on the reversed sequence -- which is the failure the
rule exists to prevent, a process that finishes its in-flight work while traffic
is still arriving. The previous handler here is a spy that records
`is_draining()` **at the moment it is called**, which is the only form of the
assertion that can fail on the wrong order.

No real signal is sent. Every case installs the handler and then invokes it as a
plain function, taken back out of `signal.getsignal(signal.SIGTERM)` so that what
runs is the object actually installed rather than an import of the module's
private name. Delivering a real `SIGTERM` to the test process would be a coin
flip between the case passing and the run being killed -- the `SIG_DFL` case
below re-raises the signal, and the default action for `SIGTERM` is termination.

The autouse fixture is not hygiene, twice over. `signal.signal` is
process-global, so a handler left installed by one case is installed for every
case after it and for every unrelated module in the same session. And the
module's `_installed` guard is **already tripped** by the time this file runs
under `pixi run test-cov`: `tests/integration/` collects before `tests/unit/`,
and `tests/integration/test_asgi_request_path.py` imports `config.asgi` at module
scope, which installs the handler. Without the reset every idempotence and
delegation case below would be asserting against that install and would pass by
describing it. That is why the fixture resets before *and* after each case, the
same shape `tests/unit/test_health_views.py` uses for the health flags.

These are unit tests: no database, no network, no subprocess. One case starts a
thread, because "`signal.signal` refuses off the main thread" is not a condition
that can be faked without also faking the thing under test.
"""

from __future__ import annotations

import ast
import signal
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final

import pytest
import structlog

from config.health import drain
from config.health.drain import install_sigterm_handler
from config.health.drain import reset_sigterm_handler_for_testing
from config.health.state import is_draining
from config.health.state import reset_health_state_for_testing
from config.locality import PROCESS_ENV_VAR

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import FrameType

    from structlog.typing import EventDict

#: `src/config/asgi.py`, whose call site nothing measures -- it is in the closed
#: `[tool.coverage.run] omit` list -- so it is asserted structurally instead.
#: Anchored through the repository root rather than through an import, because
#: importing it would install the handler as a side effect of collection.
ASGI_SOURCE: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "config" / "asgi.py"

#: The module the installer must be imported from in `asgi.py`. Asserting the
#: bare name would be satisfied by `from config.shim import noop as
#: install_sigterm_handler`, which is the same hole
#: `test_asgi_surface.py::test_get_asgi_application_is_djangos_own` closes.
INSTALLER_MODULE: Final[str] = "config.health.drain"

#: How long to wait for the one case that needs a thread. Generous: it is a
#: failure bound, not a timing assertion.
THREAD_JOIN_SECONDS: Final[float] = 10.0

#: The control event the capture fixture emits to prove it can see anything at
#: all. Never asserted for by a case -- the fixture removes it before yielding.
_CAPTURE_CONTROL: Final[str] = "drain.capture-control"


@pytest.fixture(autouse=True)
def _isolate_the_sigterm_handler() -> Iterator[None]:
    """Give every case an uninstalled handler and a process that has just started.

    Both directions matter, and for different reasons -- see the module
    docstring. The process's own handler is snapshotted and put back too, because
    the cases below install their own previous handlers with `signal.signal` and
    the module's reset only unwinds what *it* installed.
    """
    reset_sigterm_handler_for_testing()
    reset_health_state_for_testing()
    original = signal.getsignal(signal.SIGTERM)
    yield
    reset_sigterm_handler_for_testing()
    signal.signal(signal.SIGTERM, signal.SIG_DFL if original is None else original)
    reset_health_state_for_testing()


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EventDict]]:
    """Capture what the drain module logs, with the two guards the plain helper lacks.

    The reasoning is `tests/unit/test_health_views.py`'s and is not restated:
    the module-scope logger is rebound so `capture_logs` binds a fresh proxy
    inside its own processor chain, and a control event proves the capture is
    live before the case runs, so an assertion over an empty list fails here and
    says why rather than reporting that the handler logged nothing.

    Args:
        monkeypatch: pytest's patcher, which restores the module's own logger.

    Yields:
        The captured events, in order.

    """
    monkeypatch.setattr(drain, "logger", structlog.get_logger(drain.__name__))
    with structlog.testing.capture_logs() as captured:
        drain.logger.warning(_CAPTURE_CONTROL)
        assert [event["event"] for event in captured] == [_CAPTURE_CONTROL], (
            "structlog.testing.capture_logs() cannot see config.health.drain's logger, so every "
            "assertion over what it logged would be vacuous"
        )
        captured.clear()
        yield captured


def _deliver() -> None:
    """Run the installed handler the way the runtime would, without a signal.

    Taken out of `signal.getsignal` rather than imported, so a case that asserted
    delegation would fail if the module installed something other than the
    function it delegates from.
    """
    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler), "install_sigterm_handler() left no callable handler installed"
    handler(signal.SIGTERM, None)


def _asgi_module() -> ast.Module:
    """Parse `src/config/asgi.py` without importing it.

    Returns:
        The parsed module, for the structural assertions about the call site.

    """
    return ast.parse(ASGI_SOURCE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The ordering AD-22 is about (AC #1)
# ---------------------------------------------------------------------------


def test_the_flip_happens_before_the_previous_handler_runs() -> None:
    """Readiness is already draining by the time the server's handler is entered.

    The spy records `is_draining()` at call time. Asserting that both things
    happened would pass on the reverse order, which is the whole of what AD-22
    forbids.
    """
    observed: list[bool] = []

    def previous(signum: int, frame: FrameType | None) -> None:
        observed.append(is_draining())

    signal.signal(signal.SIGTERM, previous)
    install_sigterm_handler()

    _deliver()

    assert observed == [True], "the previous handler ran before readiness flipped, or did not run at all"


def test_the_handler_is_installed_in_front_of_the_existing_one() -> None:
    """Installing displaces the previous handler rather than merely reading it."""

    def previous(signum: int, frame: FrameType | None) -> None:
        """Stand in for gunicorn's or Celery's own handler."""

    signal.signal(signal.SIGTERM, previous)

    install_sigterm_handler()

    assert signal.getsignal(signal.SIGTERM) is not previous


def test_the_displaced_handler_still_receives_the_signal_arguments() -> None:
    """Delegation passes `(signum, frame)` through unchanged."""
    received: list[tuple[int, FrameType | None]] = []

    def previous(signum: int, frame: FrameType | None) -> None:
        received.append((signum, frame))

    signal.signal(signal.SIGTERM, previous)
    install_sigterm_handler()

    _deliver()

    assert received == [(int(signal.SIGTERM), None)]


# ---------------------------------------------------------------------------
# Idempotence: installing twice must not chain, and must not lose the original
# ---------------------------------------------------------------------------


def test_a_second_install_is_a_no_op() -> None:
    """The guard is what keeps the server's handler reachable.

    Without it the second install captures *this module's own* handler as the
    previous one, which loses gunicorn's and makes delegation recurse into
    itself -- a `SIGTERM` that flips readiness and then never terminates
    anything.
    """
    calls: list[int] = []

    def previous(signum: int, frame: FrameType | None) -> None:
        calls.append(signum)

    signal.signal(signal.SIGTERM, previous)
    install_sigterm_handler()
    first = signal.getsignal(signal.SIGTERM)

    install_sigterm_handler()

    assert signal.getsignal(signal.SIGTERM) is first
    _deliver()
    assert calls == [int(signal.SIGTERM)], "the displaced handler ran a number of times other than once"


def test_the_reset_helper_puts_the_displaced_handler_back() -> None:
    """The helper the autouse fixture depends on, asserted rather than assumed."""

    def previous(signum: int, frame: FrameType | None) -> None:
        """Stand in for the handler that was there first."""

    signal.signal(signal.SIGTERM, previous)
    install_sigterm_handler()

    reset_sigterm_handler_for_testing()

    assert signal.getsignal(signal.SIGTERM) is previous


def test_installing_again_after_a_reset_captures_the_current_handler() -> None:
    """The guard is cleared by the reset, not latched for the process's life."""

    def first(signum: int, frame: FrameType | None) -> None:
        """The handler displaced by the first install."""

    calls: list[str] = []

    def second(signum: int, frame: FrameType | None) -> None:
        calls.append("second")

    signal.signal(signal.SIGTERM, first)
    install_sigterm_handler()
    reset_sigterm_handler_for_testing()
    signal.signal(signal.SIGTERM, second)

    install_sigterm_handler()
    _deliver()

    assert calls == ["second"]


# ---------------------------------------------------------------------------
# The three shapes a displaced handler can take
# ---------------------------------------------------------------------------


def test_a_default_previous_handler_is_reinstalled_and_the_signal_reraised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SIG_DFL` means "terminate", and that must still happen.

    `signal.raise_signal` is patched out because the default action for
    `SIGTERM` is to kill the process, and the point of the case is the sequence
    rather than the killing: the default is re-installed *first*, so the re-raise
    terminates instead of re-entering this module's handler.
    """
    raised: list[int] = []
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    install_sigterm_handler()
    monkeypatch.setattr(signal, "raise_signal", raised.append)

    _deliver()

    assert raised == [int(signal.SIGTERM)], "the signal was swallowed instead of being re-raised"
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
    assert is_draining() is True


def test_an_ignored_previous_handler_is_left_ignored(captured_events: list[EventDict]) -> None:
    """`SIG_IGN` means "this process does not act on SIGTERM", and it still does not.

    Readiness flips regardless -- the process was told to stop serving -- and the
    declined delegation is logged rather than passed over, because nothing else
    is going to happen and an operator reading `drain.begin` alone would expect a
    shutdown that never comes.
    """
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    install_sigterm_handler()
    installed = signal.getsignal(signal.SIGTERM)

    _deliver()

    assert is_draining() is True
    assert signal.getsignal(signal.SIGTERM) is installed, (
        "the ignored handler was replaced; SIG_IGN is left exactly as it was found"
    )
    assert "drain.delegation_declined" in [event["event"] for event in captured_events]
    # Nothing re-raised: the SIG_DFL branch re-installs the default before it
    # re-raises, so the slot above would be `SIG_DFL` if this had taken it.
    assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL

    reset_sigterm_handler_for_testing()
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN


def test_a_handler_python_cannot_describe_is_declined_rather_than_guessed_at() -> None:
    """`None` is what `signal.signal` returns for a handler installed from C.

    It cannot be called and it cannot be re-created, so the only honest response
    is to flip readiness and stop -- inventing a termination here would be the
    shutdown mechanism this module exists not to own. The declined delegation is
    logged, which `test_an_ignored_previous_handler_is_left_ignored` asserts over
    the same branch.

    Restored by hand rather than with `monkeypatch`, whose `undo()` would take
    the whole fixture's patches with it -- including another fixture's -- and
    whose teardown runs too late to keep this substitution out of the delivery
    below.
    """
    real_signal = signal.signal

    def returns_nothing(signalnum: int, handler: object) -> None:
        """Install for real and report no previous handler, as a C handler does."""
        real_signal(signalnum, handler)  # type: ignore[arg-type]

    signal.signal = returns_nothing  # type: ignore[assignment]
    try:
        install_sigterm_handler()
    finally:
        signal.signal = real_signal  # type: ignore[assignment]

    _deliver()

    assert is_draining() is True


# ---------------------------------------------------------------------------
# Off the main thread: declined, logged, never raised
# ---------------------------------------------------------------------------


def test_installing_off_the_main_thread_is_declined_rather_than_raised(
    captured_events: list[EventDict],
) -> None:
    """A management command run in a thread must not fail to start.

    `signal.signal` raises `ValueError` anywhere but the main thread. A real
    thread is used rather than a patched `signal.signal`, because the condition
    under test is the threading rule itself and faking it would assert against
    the fake.
    """

    def previous(signum: int, frame: FrameType | None) -> None:
        """The handler that must survive the declined install."""

    signal.signal(signal.SIGTERM, previous)
    escaped: list[ValueError] = []

    def install_in_this_thread() -> None:
        try:
            install_sigterm_handler()
        except ValueError as error:
            escaped.append(error)

    thread = threading.Thread(target=install_in_this_thread)
    thread.start()
    thread.join(timeout=THREAD_JOIN_SECONDS)

    assert not thread.is_alive(), "the install neither returned nor raised"
    assert escaped == [], "the ValueError escaped instead of being logged and declined"
    assert signal.getsignal(signal.SIGTERM) is previous
    assert "drain.handler_not_installed_off_main_thread" in [event["event"] for event in captured_events]


# ---------------------------------------------------------------------------
# The one event, carrying the one piece of context a signal handler has
# ---------------------------------------------------------------------------


def test_the_drain_event_names_the_process_type(
    monkeypatch: pytest.MonkeyPatch,
    captured_events: list[EventDict],
) -> None:
    """`drain.begin`, once, carrying `COMPONENT_PROCESS`.

    A signal handler has no request, so the Consistency Conventions' `request_id`
    / `trace_id` / `span_id` are unavailable and the process type is the context
    that identifies the emitter. It is read through `config.locality`, the one
    reader of the variable, and not from `os.environ` here.
    """
    monkeypatch.setenv(PROCESS_ENV_VAR, "web")

    def previous(signum: int, frame: FrameType | None) -> None:
        """A benign displaced handler, so the case is about the event."""

    signal.signal(signal.SIGTERM, previous)
    install_sigterm_handler()

    _deliver()

    begins = [event for event in captured_events if event["event"] == "drain.begin"]
    assert len(begins) == 1, "the handler emits exactly one drain event"
    assert begins[0]["process"] == "web"


def test_the_drain_event_survives_a_process_type_that_was_never_declared(
    monkeypatch: pytest.MonkeyPatch,
    captured_events: list[EventDict],
) -> None:
    """`component_process()` fails open, and the event is emitted anyway.

    A process started outside `pixi run web` declares nothing (R-3). It still
    drains, and its event still says so -- with `None` for the process, which is
    the honest answer rather than a guess.
    """
    monkeypatch.delenv(PROCESS_ENV_VAR, raising=False)

    def previous(signum: int, frame: FrameType | None) -> None:
        """A benign displaced handler, so the case is about the event."""

    signal.signal(signal.SIGTERM, previous)
    install_sigterm_handler()

    _deliver()

    begins = [event for event in captured_events if event["event"] == "drain.begin"]
    assert len(begins) == 1
    assert begins[0]["process"] is None


# ---------------------------------------------------------------------------
# The call site in asgi.py, which no coverage run can see
# ---------------------------------------------------------------------------


class TestTheAsgiCallSite:
    """`src/config/asgi.py` is coverage-omitted, so this is asserted from the AST.

    Nothing at runtime observes the one line that makes any of this happen in
    production: `pyproject.toml`'s `[tool.coverage.run] omit` names the module and
    AD-20 makes that list closed, so it is neither measured nor exercised by the
    suite. `tests/unit/test_asgi_surface.py` already solved the same problem for
    `configure_observability()` by parsing the file; this does the same for the
    installer, and lives here rather than there because the subject is this
    story's contract and not AD-16's surface.
    """

    def test_the_installer_is_called_exactly_once_at_module_level(self) -> None:
        calls = [
            node
            for node in _asgi_module().body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "install_sigterm_handler"
        ]

        assert len(calls) == 1, "expected exactly one module-level install_sigterm_handler() call"
        call = calls[0].value
        assert isinstance(call, ast.Call)
        assert call.args == [], "the installer takes no arguments"
        assert call.keywords == [], "the installer takes no arguments"

    def test_the_installer_is_called_after_the_application_is_bound(self) -> None:
        """The ordering is the point: a drain cannot precede something to drain.

        Installing before `get_asgi_application()` would open a window in which
        readiness could flip while no application existed to finish the requests
        already accepted.
        """
        module = _asgi_module()
        calls = [
            node
            for node in module.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "install_sigterm_handler"
        ]
        assignments = [
            node
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "application" for target in node.targets)
        ]

        assert calls, "expected a module-level install_sigterm_handler() call"
        assert assignments, "expected a module-level `application` assignment"
        assert assignments[0].lineno < calls[0].lineno, (
            "install_sigterm_handler() must run after the application is bound"
        )

    def test_the_installer_is_this_projects_own(self) -> None:
        """A same-named import from anywhere else would satisfy the two cases above."""
        sources = {
            node.module
            for node in ast.walk(_asgi_module())
            if isinstance(node, ast.ImportFrom)
            and any((alias.asname or alias.name) == "install_sigterm_handler" for alias in node.names)
        }

        assert sources == {INSTALLER_MODULE}
