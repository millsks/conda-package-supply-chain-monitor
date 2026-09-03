"""The drain seen from the probe's side: a real database, the real routing stack.

The unit suite proves the ordering inside the handler -- readiness flips before
the displaced handler runs. What it structurally cannot prove is the consequence
AC #1 is actually about: that a readiness probe arriving *after* the flip and
*before* the socket closes reads `503`. That needs the URL resolver, the
middleware stack and a database that is genuinely healthy, because "unready with
a working database" is the only shape of the assertion that distinguishes the
drain from a dependency outage.

So the sequence here is deliberately three steps and not two: `200` first, then
the handler, then `503` -- with nothing done to the database in between. Without
the opening `200` the closing `503` would be satisfied by a process that had
never reached its database at all, which is a different refusal with the same
status code.

The handler is invoked as a plain function. Delivering a real `SIGTERM` would
kill the test session, and the previous handler is replaced with a no-op for the
duration precisely so that delegation cannot reach pytest's own.
"""

from __future__ import annotations

import signal
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from config.health import state
from config.health.drain import install_sigterm_handler
from config.health.drain import reset_sigterm_handler_for_testing
from config.health.views import STATUS_READY
from config.health.views import STATUS_UNREADY

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import FrameType

    from django.test import Client

pytestmark = pytest.mark.integration


def _absorb(signum: int, frame: FrameType | None) -> None:
    """Stand in for gunicorn's own handler, so delegation terminates nothing."""


@pytest.fixture(autouse=True)
def _isolate_the_drain() -> Iterator[None]:
    """Leave the process exactly as found: no handler, no flags, no drain.

    Both halves are load-bearing. A leaked `draining` flag makes every later
    readiness assertion in the session read `503` for a reason that has nothing
    to do with the case that fails, and a leaked handler is installed for the
    rest of the run -- `signal.signal` is process-global. The reset runs before
    each case as well as after, because `tests/integration/test_asgi_request_path.py`
    imports `config.asgi` at module scope and has already installed the handler
    by the time this module is collected.
    """
    reset_sigterm_handler_for_testing()
    state.reset_health_state_for_testing()
    original = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _absorb)
    yield
    reset_sigterm_handler_for_testing()
    signal.signal(signal.SIGTERM, signal.SIG_DFL if original is None else original)
    state.reset_health_state_for_testing()


def _drain() -> None:
    """Run the installed handler the way the runtime would, without a signal."""
    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler), "install_sigterm_handler() left no callable handler installed"
    handler(signal.SIGTERM, None)


@pytest.mark.django_db
def test_readiness_refuses_after_the_drain_begins_with_a_healthy_database(client: Client) -> None:
    """AC #1, mechanically: the flip alone takes this replica out of the pool.

    Nothing is done to the database between the two probes. The second `503` is
    therefore attributable to the drain and to nothing else, which is what makes
    this the drain's test rather than a second copy of the unreachable-database
    one.
    """
    ready = client.get(reverse("readiness"))
    assert ready.status_code == HTTPStatus.OK
    assert ready.json()["status"] == STATUS_READY

    install_sigterm_handler()
    _drain()

    draining = client.get(reverse("readiness"))

    assert draining.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert draining.json()["status"] == STATUS_UNREADY
    assert state.is_draining() is True


@pytest.mark.django_db
def test_the_draining_refusal_asks_no_database_at_all(client: Client) -> None:
    """The drain branch answers before the probe query, not after it.

    The empty `databases` map is the observable form of "without a round trip":
    a draining process has been told to stop serving, so the state of its
    dependencies cannot change the answer and it must not spend a connection
    finding out.
    """
    assert client.get(reverse("readiness")).status_code == HTTPStatus.OK

    install_sigterm_handler()
    _drain()

    assert client.get(reverse("readiness")).json()["databases"] == {}


@pytest.mark.django_db
def test_liveness_still_answers_while_the_process_drains(client: Client) -> None:
    """AD-22's asymmetry: draining removes the replica from routing, not from life.

    A liveness probe that failed here would have the platform kill the process
    mid-drain, which is the outage the two endpoints exist to keep apart -- and
    it would discard exactly the in-flight requests the drain is there to finish.
    """
    install_sigterm_handler()
    _drain()

    assert client.get(reverse("liveness")).status_code == HTTPStatus.OK
