"""The health concern: liveness, readiness, and the per-process state they read.

A `src/config/<concern>/` package rather than a Django app, and rather than a
module bolted onto one of the existing packages. The Consistency Conventions rule
is that "cross-cutting concerns with several independent consumers and no natural
owner live under `src/config/<concern>/`", and health has three consumers already:
the root URLconf, which routes it; Story 5.4's shutdown handler, which calls
`begin_drain`; and Epic 8's per-combination smoke check, which asserts that
readiness answers 200 with no external service running.

The Structural Seed names `settings/`, `observability/`, `authorization/` and
`startup/` and does not name `health/`. The seed is not a closed list, and this is
recorded as the same deliberate variance Story 5.1 records for
`src/config/component/` rather than left as an unexplained extra directory.

This module re-exports the whole public surface so that a consumer imports from
`config.health` and does not have to know which of the two modules a name lives
in. The drain accessors are exported here for that reason above all: Story 5.4
adds a signal handler and nothing else, and `from config.health import
begin_drain` is the import it should be able to write.

That handler is now here too, as `config.health.drain`. `install_sigterm_handler`
is called by `config/asgi.py` and by the Celery `worker_ready` receiver in
`config/celery_app.py`; both are re-exported alongside the state accessors so
that the flip, the flag and the handler that connects them are one import away
from each other.
"""

from __future__ import annotations

from config.health.drain import install_sigterm_handler
from config.health.drain import reset_sigterm_handler_for_testing
from config.health.state import begin_drain
from config.health.state import first_contact_made
from config.health.state import is_draining
from config.health.state import mark_first_contact
from config.health.state import reset_health_state_for_testing
from config.health.views import liveness
from config.health.views import readiness

__all__ = [
    "begin_drain",
    "first_contact_made",
    "install_sigterm_handler",
    "is_draining",
    "liveness",
    "mark_first_contact",
    "readiness",
    "reset_health_state_for_testing",
    "reset_sigterm_handler_for_testing",
]
