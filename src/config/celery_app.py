import os
from typing import Any

from celery import Celery
from celery.signals import setup_logging
from celery.signals import worker_ready
from django_structlog.celery.steps import DjangoStructLogInitStep

from config.observability import configure_observability

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

configure_observability()

app = Celery("django_service")

# Carries request_id from the request that enqueued a task into the task's own
# log context, so a task's logs point back at the request that caused it.
app.steps["worker"].add(DjangoStructLogInitStep)

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")


# celery ships no `py.typed` marker and conda-forge carries no stub package for
# it, so `ignore_missing_imports` resolves `setup_logging` to `Any` and strict
# mode reports that the decorator erases the annotated signature below.
# `warn_unused_ignores` removes the marker when celery starts publishing types.
@setup_logging.connect  # type: ignore[untyped-decorator]
def config_loggers(*args: Any, **kwargs: Any) -> None:
    """Install Django's LOGGING dict as the worker's logging configuration.

    Celery otherwise replaces it with its own, which would drop the structlog
    processor chain the rest of the application logs through.

    Args:
        *args: Signal arguments, unused.
        **kwargs: Signal keyword arguments, unused.

    """
    from logging.config import dictConfig  # noqa: PLC0415

    from django.conf import settings  # noqa: PLC0415

    dictConfig(settings.LOGGING)


# `worker_ready` and not `worker_process_init`: Celery installs its own SIGTERM
# handler in the *main* worker process (`install_platform_tweaks`, before the
# consumer starts), and that is the process the platform signals. The prefork
# children have their handlers reset and never receive the platform's SIGTERM
# directly, so a handler installed in one of them would flip a readiness flag
# nobody reads and delegate a signal that never arrives.
#
# The `# type: ignore[untyped-decorator]` marker is for the reason given above
# `config_loggers`.
@worker_ready.connect  # type: ignore[untyped-decorator]
def install_drain_handler(*args: Any, **kwargs: Any) -> None:
    """Put the drain handler in front of Celery's own SIGTERM handler (AD-22).

    A worker has no readiness probe reading the flag, and the flip is still worth
    making: the ordering is one path for every process type rather than two, and
    the `drain.begin` event is what tells an operator which worker began draining
    and when. Celery's own warm shutdown -- finish the current task, decline new
    ones -- is left exactly as it is; this adds nothing to it and takes nothing
    away.

    Args:
        *args: Signal arguments, unused.
        **kwargs: Signal keyword arguments, unused.

    """
    # Imported here rather than at module scope because `config/__init__.py`
    # imports this module, so a top-level import would pull the health concern --
    # and through it `django.db` and the component loader -- into every import of
    # anything under `config`, management commands and settings included. The
    # deferral matches `config_loggers` above.
    from config.health.drain import install_sigterm_handler  # noqa: PLC0415

    install_sigterm_handler()


# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
