"""Tests for the Celery application module."""

from __future__ import annotations

import inspect
import logging
import weakref
from typing import TYPE_CHECKING

from celery.signals import before_task_publish
from celery.signals import worker_ready
from django_structlog.celery.receivers import CeleryReceiver
from django_structlog.celery.steps import DjangoStructLogInitStep

from config.celery_app import app
from config.celery_app import config_loggers
from config.celery_app import install_drain_handler

if TYPE_CHECKING:
    import pytest
    from celery.utils.dispatch import Signal


def _connected_receivers(signal: Signal) -> list[object]:
    """Return the live receivers connected to one celery signal.

    Celery's dispatcher stores receivers weakly by default, so the entries are
    `(lookup_key, weakref)` pairs and a dead reference resolves to `None`. It is
    walked rather than asserted through `has_listeners()`, which would be
    satisfied by any receiver at all.

    Args:
        signal: The celery signal whose receivers to resolve.

    Returns:
        Every receiver still reachable from the signal, in connection order.

    """
    receivers: list[object] = []
    for _key, receiver in signal.receivers:
        resolved = receiver() if isinstance(receiver, weakref.ReferenceType) else receiver
        if resolved is not None:
            receivers.append(resolved)
    return receivers


def test_celery_app_is_named_for_the_service():
    assert app.main == "django_service"


def test_config_loggers_applies_the_django_logging_config():
    """The setup_logging receiver hands Django's LOGGING dict to dictConfig.

    Celery otherwise installs its own logging config and Django's is ignored.
    """
    config_loggers()
    assert logging.getLogger("django").handlers


def test_the_drain_handler_is_connected_to_worker_ready():
    """AD-22: a worker installs the same handler the web process does.

    `worker_ready` and not `worker_process_init`: Celery installs its own
    `SIGTERM` handler in the main worker process, which is the process the
    platform signals, while the prefork children have their handlers reset and
    never receive it directly.

    Importing `config.celery_app` only *connects* the receiver -- nothing is
    installed until Celery fires the signal -- so this case has no effect on the
    test process's own handler.
    """
    assert install_drain_handler in _connected_receivers(worker_ready)


def test_the_worker_ready_receiver_installs_the_sigterm_handler(monkeypatch: pytest.MonkeyPatch):
    """The connection is only worth asserting if the receiver does the work.

    The installer is patched where it is defined rather than where it is used:
    the receiver imports it inside its own body -- `config/__init__.py` imports
    `config.celery_app`, so a module-level import would drag the health concern
    into every import of anything under `config` -- and a function-local import
    resolves against the defining module at call time.
    """
    calls: list[int] = []
    monkeypatch.setattr("config.health.drain.install_sigterm_handler", lambda: calls.append(1))

    install_drain_handler()

    assert calls == [1]


def test_the_django_structlog_bootstep_is_registered_on_the_worker():
    """FR-46: the step that binds an enqueueing request's context in the task.

    `DjangoStructLogInitStep` is what calls `connect_worker_signals()`, and
    `task_prerun` -- the receiver that reads `__django_structlog__` off the
    message and binds `request_id` for the task's own log lines -- is connected
    nowhere else. Without the step a worker logs tasks with no correlation at
    all, and nothing else in the tree would notice.
    """
    assert DjangoStructLogInitStep in app.steps["worker"]


def test_the_publish_side_receiver_is_connected():
    """The observable consequence of `DJANGO_STRUCTLOG_CELERY_ENABLED = True`.

    Asserted as a consequence rather than by reading the setting back: the
    setting's value is already held by `tests/unit/test_settings.py`, and a
    reading of it here would pass just as happily against a django-structlog
    that had stopped acting on it. `DjangoStructLogConfig.ready()` calls
    `CeleryReceiver().connect_signals()`, which is what writes the enqueueing
    request's context into the published headers.
    """
    owners = {
        type(receiver.__self__) for receiver in _connected_receivers(before_task_publish) if inspect.ismethod(receiver)
    }

    assert CeleryReceiver in owners, f"no CeleryReceiver method is connected to before_task_publish: {owners}"
