"""Which role owns a queue, as a DRF permission resolved from a URL segment.

Declared in `workflow` rather than beside the views that use it, because the answer
is a fact about the *queue* and `QUEUE_OWNERS` is where this app declares it. The
queue listing lives in `surface/api/` -- it is a read, and reads are `surface`'s --
and the transition lives here; both need this, and `surface` may import `workflow`
while the reverse would invert the layering `test_app_layering_audit.py` fixes.

**It decides nothing.** It looks a queue up in a closed table and returns the
permission class for its owner, which is `CPM-AD-13`'s "declared per surface,
enforced centrally" with the declaration coming from data rather than from a literal
on a class. `tests/unit/django_apps/test_permission_audit.py` sweeps for a module
that asks an authorization question itself; this asks none.

**A queue that does not exist is a 404, checked first** -- in `initial()`, before
DRF asks about permissions. An earlier version of the HTML queue view had this
backwards, and the bug was self-concealing: an unknown queue owns no role, so refusing
on the role first made the 404 unreachable and told a reader who mistyped a real
queue's name that a queue exists which does not.

**`queue_permission` therefore does not raise, and that took a correction.** The first
version raised the 404 from inside `get_permissions`, which is a method
drf-spectacular calls during schema generation with no URL kwargs at all -- so
`/api/schema/` answered 404 for the whole document. Introspection is not a request,
and a method a schema generator calls has no business deciding what a *request* gets.
The refusal moved to `initial()`; this returns a class either way, and the class for
an unknown queue is the base `RolePermission`, which declares no roles and so refuses
everybody. Unreachable behind the 404, and the right answer if it ever is reached:
this fails closed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from rest_framework.exceptions import NotFound

from conda_sentinel.core.permissions import RolePermission
from conda_sentinel.core.permissions import requires_roles
from conda_sentinel.workflow.states import QUEUE_OWNERS

if TYPE_CHECKING:
    from rest_framework.permissions import BasePermission

__all__ = ["UNKNOWN_QUEUE", "queue_permission", "require_known_queue"]

#: What a URL naming no declared queue is told.
#:
#: A 404 rather than a refusal: a queue that does not exist is not one somebody lacks
#: a role for, and answering 403 would tell a caller a queue exists that does not.
#: The queue names are not a secret -- the nav lists all three to every role, because
#: `CPM-AD-13` scopes below the navigation -- so naming them leaks nothing and saves
#: a caller a guess.
UNKNOWN_QUEUE: Final[str] = "no queue is called {queue!r}. The queues are {known}."


def require_known_queue(queue: str) -> str:
    """Refuse a name that is not a declared queue.

    Called from a view's `initial()`, so the 404 precedes the role check and a reader
    who mistyped a real queue's name is not told a queue exists that does not.

    Args:
        queue: The queue name from the URL.

    Returns:
        The name, so a caller can use this in an expression.

    Raises:
        NotFound: When it names no declared queue.

    """
    if queue not in QUEUE_OWNERS:
        raise NotFound(UNKNOWN_QUEUE.format(queue=queue, known=sorted(QUEUE_OWNERS)))
    return queue


def queue_permission(queue: str) -> type[BasePermission]:
    """Return the permission class that owns one queue.

    Never raises: see the module docstring. A schema generator calls this with
    nothing, and introspection must not decide what a request gets.

    Args:
        queue: The queue name.

    Returns:
        A `RolePermission` subclass requiring the queue's owning role, or the base
        `RolePermission` for a name that is not a queue -- which declares no roles
        and therefore refuses everybody.

    """
    if queue not in QUEUE_OWNERS:
        return RolePermission
    return requires_roles(QUEUE_OWNERS[queue])
