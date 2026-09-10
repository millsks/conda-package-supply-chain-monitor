"""The one function that moves a queue item, and the one that opens them.

`CPM-AD-22`: transitions are "applied by one service function that locks the row with
`select_for_update`, checks the expected prior state, refuses on mismatch, and
appends the audit row in the same transaction (`CPM-AD-23`)". `apply_transition` is
that function, and the four clauses are four separate protections against four
different failures:

* **The lock** stops two people moving one item at once. Without it, two reviewers
  who open a queue at the same moment both read `triaged`, both write, and the second
  write wins silently -- last-writer-wins clobbering, which `CPM-AD-22` names.
* **The expected prior state** stops a *stale* move. A reviewer whose page was
  rendered ten minutes ago clicks "resolve" on an item somebody else has since
  accepted; the lock alone would let that through, because by the time it is held the
  item is simply in a different state. So the caller says what it believed and is
  refused when it was wrong.
* **The refusal** is a refusal, not a repair. Advancing the item from wherever it
  actually is would be the system deciding what the person meant.
* **The same transaction** is what makes the audit trail true rather than
  approximately true. An audit row written afterwards is missing whenever the process
  dies in between, and the moves that go missing are the ones somebody will later
  want to ask about.

**Opening items is the policy run's job and nobody else's.** `open_items_for` is
called from the run; no transition in `workflow/states.py` produces `open`, so there
is no path by which a person puts work back into the state that means "nobody has
looked at this". The mockups state the rule directly -- *"created by the policy run,
never by a human"* -- and this is where it is true.

**Opening is idempotent by key, and that is `CPM-APP-S04`'s second criterion.**
Evidence is append-only, so tonight's run inserts a new advisory row for the same
advisory it saw last night. `get_or_create` on the finding key finds the existing
item -- whatever state it has reached -- and touches nothing. An accepted finding
stays accepted.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import NoReturn

import structlog
from django.db import transaction

from conda_sentinel.core.permissions import granted_roles
from conda_sentinel.workflow.models import WorkflowItem
from conda_sentinel.workflow.models import WorkflowTransition
from conda_sentinel.workflow.states import TERMINAL_STATES
from conda_sentinel.workflow.states import ItemState
from conda_sentinel.workflow.states import transition_for

if TYPE_CHECKING:
    from conda_sentinel.core.clock import Clock
    from conda_sentinel.core.finding_keys import FindingKeyed
    from conda_sentinel.identity.models import Package
    from conda_sentinel.workflow.states import Transition
    from django_service.users.models import User

__all__ = [
    "ITEM_OPENED_EVENT",
    "TRANSITION_APPLIED_EVENT",
    "TRANSITION_REFUSED_EVENT",
    "OpenedItem",
    "WorkflowError",
    "apply_transition",
    "open_item",
    "open_keyed_item",
]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: The events an operator alerts on or audits from.
#:
#: A refusal is logged at warning and separately from an applied transition, because
#: the two answer different questions: one is somebody's work, the other is either a
#: stale page or an attempt to do something the machine forbids -- and a run of them
#: on one item is worth looking at.
ITEM_OPENED_EVENT: str = "workflow.item_opened"
TRANSITION_APPLIED_EVENT: str = "workflow.transition_applied"
TRANSITION_REFUSED_EVENT: str = "workflow.transition_refused"


class WorkflowError(Exception):
    """A move was refused.

    One exception for every refusal, carrying a message that says which of the four
    checks failed. Named rather than raised as `ValueError` so a view can turn it
    into a 409 and nothing else can -- a `ValueError` out of a serializer would
    otherwise be reported to a reviewer as a workflow conflict.
    """


@dataclass(frozen=True, slots=True)
class OpenedItem:
    """What opening produced, and whether it was new.

    The flag is what lets the policy run report "opened 4, matched 137" rather than
    "processed 141", which is the number that tells an operator whether tonight's run
    found anything.
    """

    item: WorkflowItem
    created: bool


def open_item(
    *,
    evidence: FindingKeyed,
    package: Package,
    queue: str,
    clock: Clock,
) -> OpenedItem:
    """Open a queue item for a finding, or return the one that already exists.

    Args:
        evidence: The row whose finding this is. Its declared key is what the item is
            filed under -- never the row's own id, which changes every re-observation.
        package: The package the work is about.
        queue: The queue to open it in, as a `Queue` value.
        clock: The clock both stamps are read from (`CPM-AD-26`).

    Returns:
        The item, and whether this call created it.

    """
    key, facts = evidence.finding_key()
    return open_keyed_item(finding_key=key, finding_facts=facts, package=package, queue=queue, clock=clock)


def open_keyed_item(
    *,
    finding_key: str,
    finding_facts: str,
    package: Package,
    queue: str,
    clock: Clock,
) -> OpenedItem:
    """Open a queue item under a key built by the caller, or return the existing one.

    The half of `open_item` that takes a key rather than deriving one, for the queue
    whose finding is **not** evidence-backed: an unidentified package's work exists
    because nothing was observed, so there is no row to ask for a key and the caller
    builds one from `packages`.

    Kept as a separate entry point rather than as an optional argument to
    `open_item`, so the ordinary path cannot be called with a hand-made key by
    accident -- an evidence-backed item keyed by anything but its table's declaration
    is the duplicate-in-a-queue failure `CPM-AD-22` is about.

    Args:
        finding_key: What the work is filed under.
        finding_facts: The readable form, for a reviewer.
        package: The package the work is about.
        queue: The queue to open it in.
        clock: The clock both stamps are read from (`CPM-AD-26`).

    Returns:
        The item, and whether this call created it.

    """
    now = clock.now()
    item, created = WorkflowItem.objects.get_or_create(
        finding_key=finding_key,
        defaults={
            "finding_facts": finding_facts,
            "package": package,
            "queue": queue,
            "state": ItemState.OPEN.value,
            "opened_at": now,
            "changed_at": now,
        },
    )
    if created:
        logger.info(ITEM_OPENED_EVENT, finding_key=finding_key, queue=queue, package=package.canonical_name)
    return OpenedItem(item=item, created=created)


def apply_transition(  # noqa: PLR0913 - see the docstring: each argument is a separate check
    *,
    item_id: int,
    expected_state: str,
    to_state: str,
    actor: User,
    clock: Clock,
    justification: str = "",
    queue: str = "",
) -> WorkflowItem:
    """Move one item, under a lock, and record that it moved.

    Args:
        item_id: The item to move, by primary key rather than by instance -- the row
            this function acts on is the one it locks, not one a caller read earlier
            and has been holding.
        expected_state: The state the caller believed the item was in. Refused on
            mismatch; see the module docstring for why the lock alone is not enough.
        to_state: The state to move it to.
        actor: The person making the move.
        clock: The clock the stamps are read from (`CPM-AD-26`).
        justification: Why, for the transition that demands one.
        queue: The queue to route to, for a routing move. Ignored otherwise -- and
            `CPM-APP-S04`'s AC 4 is that this *changes* the column and creates
            nothing.

    Returns:
        The moved item.

    Raises:
        WorkflowError: When the item does not exist, when it is not in the expected
            state, when the machine declares no such move, when the actor holds none
            of the roles the move requires, or when a move that demands a
            justification was given none.

    """
    with transaction.atomic():
        item = WorkflowItem.objects.select_for_update().filter(pk=item_id).first()
        if item is None:
            message = f"no workflow item has id {item_id}."
            raise WorkflowError(message)

        _require_expected(item, expected_state=expected_state, to_state=to_state, actor=actor)
        declared = _require_declared(item, to_state=to_state, actor=actor)
        _require_role(item, declared=declared, actor=actor)
        _require_justification(item, declared=declared, justification=justification, actor=actor)

        now = clock.now()
        from_state = item.state
        moved_queue = queue or item.queue

        item.state = to_state
        item.queue = moved_queue
        # A claim is meaningful in one state, and the model's own constraint says so.
        # Setting it here rather than leaving it to the caller is what keeps the two
        # from disagreeing -- the constraint would refuse the write, but only after
        # the caller had convinced itself the move succeeded.
        item.claimed_by = actor if to_state == ItemState.IN_PROGRESS.value else None
        item.changed_at = now
        item.save(update_fields=("state", "queue", "claimed_by", "changed_at"))

        # In the same transaction (`CPM-AD-23`). See the module docstring.
        WorkflowTransition.objects.create(
            item=item,
            from_state=from_state,
            to_state=to_state,
            queue=moved_queue,
            actor=actor,
            justification=justification,
            occurred_at=now,
        )

    logger.info(
        TRANSITION_APPLIED_EVENT,
        item=item.pk,
        finding_key=item.finding_key,
        **_move(from_state, to_state, actor),
        queue=moved_queue,
    )
    return item


def _require_expected(item: WorkflowItem, *, expected_state: str, to_state: str, actor: User) -> None:
    """Refuse a move made against a state the item is no longer in.

    Args:
        item: The locked item.
        expected_state: What the caller believed.
        to_state: Where they wanted it to go, for the refusal record.
        actor: Who asked, for the refusal record.

    Raises:
        WorkflowError: On mismatch.

    """
    if item.state == expected_state:
        return
    _refuse(
        item,
        to_state=to_state,
        actor=actor,
        reason="stale",
        message=(
            f"item {item.pk} is {item.state!r} and the move was made against {expected_state!r}. Somebody else "
            f"moved it since this page was rendered; nothing was changed."
        ),
    )


def _require_declared(item: WorkflowItem, *, to_state: str, actor: User) -> Transition:  # noqa: RET503
    """Return the declared transition, or refuse a move the machine does not have.

    Args:
        item: The locked item.
        to_state: Where the caller wants it.
        actor: Who asked.

    Returns:
        The declaration.

    Raises:
        WorkflowError: When no transition joins the two states.

    """
    declared = transition_for(item.state, to_state)
    if declared is not None:
        return declared
    ending = " It is already finished." if item.state in TERMINAL_STATES else ""
    _refuse(
        item,
        to_state=to_state,
        actor=actor,
        reason="undeclared",
        message=(
            f"the workflow declares no move from {item.state!r} to {to_state!r}.{ending} The machine is "
            f"declared in workflow/states.py and this service can make no move that is not in it."
        ),
    )


def _require_role(item: WorkflowItem, *, declared: Transition, actor: User) -> None:
    """Refuse a move the actor holds no role for.

    The check reads `granted_roles`, which is `core/permissions.py`'s and the only
    implementation of "which roles does this person hold" (`CPM-AD-13`). A second one
    here would be the per-surface role check the decision exists to prevent, moved
    into a service.

    Args:
        item: The locked item.
        declared: The transition declaration.
        actor: Who asked.

    Raises:
        WorkflowError: When they hold none of the required roles.

    """
    held = granted_roles(actor)
    required = declared.required_roles
    if held & required:
        return
    _refuse(
        item,
        to_state=declared.to_state,
        actor=actor,
        reason="role",
        message=(
            f"this move requires one of {sorted(required)} and the actor holds {sorted(held)}. CPM-FR-31 scopes "
            f"what each role may do; the item was not changed."
        ),
    )


def _require_justification(
    item: WorkflowItem,
    *,
    declared: Transition,
    justification: str,
    actor: User,
) -> None:
    """Refuse a move that demands a reason and was given none.

    Required by the *declaration* rather than by each caller, which is the whole
    point of the transition table: the one move that decides not to fix something
    cannot be made without saying why, whoever calls it and from wherever.

    Args:
        item: The locked item.
        declared: The transition declaration.
        justification: What the caller supplied.
        actor: Who asked.

    Raises:
        WorkflowError: When a justification is required and blank.

    """
    if not declared.requires_justification or justification.strip():
        return
    _refuse(
        item,
        to_state=declared.to_state,
        actor=actor,
        reason="justification",
        message=(
            "this move records a decision not to act and cannot be made without a reason. The reason is the "
            "only thing a later reader has to go on."
        ),
    )


def _refuse(item: WorkflowItem, *, to_state: str, actor: User, reason: str, message: str) -> NoReturn:
    """Record a refusal and raise it.

    One place, so every refusal is logged in one shape and none can be raised without
    being recorded -- a refused move is the thing an operator most wants to see a run
    of, and a bare `raise` somewhere would be the one that never appears.

    Args:
        item: The locked item.
        to_state: Where the caller wanted it.
        actor: Who asked.
        reason: Which of the four checks failed, as a short tag to alert on.
        message: What the caller is told.

    Raises:
        WorkflowError: Always.

    """
    logger.warning(
        TRANSITION_REFUSED_EVENT,
        item=item.pk,
        finding_key=item.finding_key,
        refusal=reason,
        **_move(item.state, to_state, actor),
    )
    raise WorkflowError(message)


def _move(from_state: str, to_state: str, actor: User) -> dict[str, object]:
    """Return the fields every workflow event carries.

    Args:
        from_state: Where the item was.
        to_state: Where it was going.
        actor: Who asked.

    Returns:
        The shared shape, so an operator can query one set of keys across applied and
        refused moves alike.

    """
    return {
        "from_state": from_state,
        "to_state": to_state,
        # The username rather than the primary key, on the terms `core/permissions.py`
        # sets: whoever reads this is about to go and ask somebody a question.
        "actor": str(getattr(actor, "username", actor)),
    }
