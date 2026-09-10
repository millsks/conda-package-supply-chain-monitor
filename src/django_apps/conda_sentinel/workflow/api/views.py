"""Queue reads and the queue action: the second of the API's two writes.

**This module does not implement the transition.** `workflow/services.apply_transition`
does, and everything that makes the move safe -- the row lock, the expected-state
check, the declared-transition check, the role check, the justification check, and the
`WorkflowTransition` written in the same transaction (`CPM-AD-23`) -- happens there.
A view that re-implemented any of it would be a second way to move an item, and the
two would disagree the first time somebody changed one.

So this validates the request's shape, hands the service what it asks for, and turns
`WorkflowError` into a 409. A conflict rather than a 400, and the distinction is the
useful one: a body the API cannot read is the client's mistake, and a move the
machine will not make on an item in that state is a fact about the world that
probably changed under them -- which is what a retrying integrator needs to be able
to tell apart.

**The role is read from the queue, not declared on the class.** The same rule the
HTML queue view follows and for the same reason: which role may work a queue is a
property of the queue, and `QUEUE_OWNERS` is where that is declared. `roles_required`
is not available to a DRF permission the way `RoleRequiredMixin` offers it to a
Django view, so `get_permissions` resolves the owner per request through
`workflow/api/permissions.py` -- which reads a closed table and decides nothing.

**The queue *listing* is not here.** It is a read, and reads are `surface`'s: putting
it here would have `workflow` importing `surface.queues`, which inverts the layering
`test_app_layering_audit.py` exists to fix. What is here is the write.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import APIException
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from conda_sentinel.core.clock import SystemClock
from conda_sentinel.workflow.api.permissions import queue_permission
from conda_sentinel.workflow.api.serializers import TransitionRequestSerializer
from conda_sentinel.workflow.api.serializers import WorkflowItemSerializer
from conda_sentinel.workflow.models import WorkflowItem
from conda_sentinel.workflow.services import WorkflowError
from conda_sentinel.workflow.services import apply_transition

if TYPE_CHECKING:
    from rest_framework.permissions import BasePermission
    from rest_framework.request import Request

    from django_service.users.models import User

__all__ = ["WorkflowConflict", "WorkflowItemTransitionAPIView"]


class WorkflowConflict(APIException):
    """A move the workflow refused, as a status code.

    409 rather than 400. A body the API cannot read is the client's mistake; a move
    the machine will not make on an item in the state it is actually in is a fact
    about the world, and usually one that changed under a caller who read the item a
    moment ago. An integrator retrying a queue needs to tell those apart, and one
    status code for both makes that impossible.
    """

    status_code = 409
    default_detail = "the workflow refused this move."
    default_code = "workflow_conflict"


class WorkflowItemTransitionAPIView(APIView):
    """Move one queue item, on the terms `workflow/services.py` sets.

    The API's second and last write. It creates no item: `CPM-AD-22` gives the policy
    run the opening of work, and an endpoint that created one would let an integrator
    invent a finding the product never derived.
    """

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        """Find the item before anything asks about roles.

        The item's queue is what decides the permission, so there has to *be* an item
        before there is a role to require -- and a 404 for an item nobody can see is
        the same answer either way.

        Done here rather than in `get_permissions` after a correction: that method is
        called by drf-spectacular during schema generation, with no URL kwargs, so a
        `NotFound` raised inside it made `/api/schema/` answer 404 for the entire
        document. Introspection is not a request.

        Args:
            request: The request.
            *args: DRF's positional URL arguments.
            **kwargs: DRF's keyword URL arguments, carrying the item id.

        Raises:
            NotFound: When no item has that id.

        """
        item_id = kwargs.get("item_id")
        item = WorkflowItem.objects.filter(pk=item_id).only("queue").first() if isinstance(item_id, int) else None
        if item is None:
            message = f"no workflow item has id {item_id!r}."
            raise NotFound(message)
        self.item_queue = item.queue
        super().initial(request, *args, **kwargs)

    def get_permissions(self) -> list[BasePermission]:
        """Return the permission the item's *current* queue requires.

        The item's queue rather than the target, and the difference matters for the
        routing move: sending work to another role's queue is an act performed by the
        role that holds it now. The service checks the transition's own declared
        roles again, so this is the outer of two gates rather than the only one.

        Returns:
            One permission, requiring the owning role of the queue the item is in --
            or a deny-all under introspection, where there is no item to read a queue
            from. It does not raise; see `initial`.

        """
        return [queue_permission(getattr(self, "item_queue", ""))()]

    @extend_schema(request=TransitionRequestSerializer, responses={200: WorkflowItemSerializer})
    def post(self, request: Request, item_id: int) -> Response:
        """Apply one move.

        Args:
            request: The request, carrying the move.
            item_id: Which item.

        Returns:
            The moved item.

        Raises:
            WorkflowConflict: When the service refuses the move -- the item is not in
                the expected state, the machine declares no such transition, the
                actor holds none of the roles it requires, or a move demanding a
                justification was given none.

        """
        shape = TransitionRequestSerializer(data=request.data)
        shape.is_valid(raise_exception=True)
        move: dict[str, Any] = shape.validated_data

        try:
            item = apply_transition(
                item_id=item_id,
                expected_state=move["expected_state"],
                to_state=move["to_state"],
                # Narrowed rather than checked: the declared permission has already
                # refused an anonymous request, since anonymity holds no role. A
                # test in this view would be the view deciding authorization for
                # itself, which `test_permission_audit.py` sweeps for.
                actor=cast("User", request.user),
                clock=SystemClock(),
                justification=move["justification"],
                queue=move["queue"],
            )
        except WorkflowError as refusal:
            raise WorkflowConflict(str(refusal)) from refusal

        return Response(WorkflowItemSerializer(item).data)
