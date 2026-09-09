"""What a queue item can be, and who may move it -- declared as data, not as code.

`CPM-AD-22`: "state transitions are declared once as data -- `(from_state, to_state,
required_role)` -- and applied by one service function". This module is the data. The
service is `workflow/services.py`, and it can do nothing this table does not permit.

**Why data rather than methods.** A state machine written as `def triage(self)`,
`def route(self)`, `def resolve(self)` has its rules spread across as many methods as
there are transitions, and the rule that matters -- *which* moves exist -- is
readable only by reading all of them. Worse, the role check ends up copied into each,
which is `CPM-AD-13`'s "each view inventing its own check" moved one layer down. As a
table it is nine lines and a reviewer can see the whole machine at once.

**`open` is reachable only by the policy run.** No transition below produces it,
which is the mockups' own annotation -- *"created by the policy run, never by a
human"* -- expressed so that the service enforces it for free: there is no
`(*, open)` row, so nothing a person does can put an item back into the state that
means "nobody has looked at this".

**`blocked` is not a state, and leaving it out is deliberate.** The mockups mark it
explicitly: *"readiness = blocked -- a display state, not a state change; the item
stays open at its bucket and policy re-derives readiness every run"*. A sixth state
here would let a person freeze an item in a condition the policy engine is supposed
to keep re-deciding, and the item would then be wrong the moment a fix appeared.

**Accepting a risk is the one transition that demands a reason**, and the one
restricted to a single role. `CPM-FR-31` gives risk acceptance to the security and
compliance reviewer; everything else on this machine is work anybody in the product
can move along. The justification is required by the *declaration*, so the service
refuses without one rather than each caller remembering.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Final

from django.db import models
from django.utils.translation import gettext_lazy as _

from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER

__all__ = [
    "ANY_PRODUCT_ROLE",
    "QUEUE_LENGTH",
    "STATE_LENGTH",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "ItemState",
    "Queue",
    "Transition",
    "transition_for",
]


class ItemState(models.TextChoices):
    """The six states a queue item can be in.

    Six and not more. Each of the five below `OPEN` is something a *person* did, and
    the machine is small enough that a reviewer can hold it in their head -- which is
    the property that makes a queue trustworthy.
    """

    #: Unactioned work. Written by the policy run and by nothing else.
    OPEN = "open", _("open")

    #: A human has looked at it. The state that says the queue has been read.
    TRIAGED = "triaged", _("triaged")

    #: Sent to the queue that can actually act on it. See `CPM-AD-22`: routing
    #: changes the item's queue and never creates a second item.
    ROUTED = "routed", _("routed")

    #: Somebody has claimed it. `claimed_by` says who, and is meaningless in any
    #: other state -- the model constrains that rather than trusting it.
    IN_PROGRESS = "in_progress", _("in progress")

    #: Done, with an audit row saying who and when.
    RESOLVED = "resolved", _("resolved")

    #: The risk was accepted or an exception recorded. Reachable only from `triaged`,
    #: only by the security and compliance reviewer, and only with a justification.
    ACCEPTED = "accepted", _("accepted")


class Queue(models.TextChoices):
    """The three queues `CPM-AD-22` puts on one table.

    **Filtered views over one table, not three models.** The decision says so, and
    the reason is `CPM-AD-22`'s second failure: "the same item existing twice in two
    role-exclusive queues with diverging state". One row, one queue column, and
    routing is an update.
    """

    IDENTITY_REVIEW = "identity_review", _("identity review")
    REMEDIATION = "remediation", _("remediation")
    COMPLIANCE_REVIEW = "compliance_review", _("compliance review")


#: Column widths, sized from the vocabularies rather than guessed.
STATE_LENGTH: Final[int] = max(len(value) for value in ItemState.values)
QUEUE_LENGTH: Final[int] = max(len(value) for value in Queue.values)

#: The states from which nothing moves.
#:
#: `resolved` and `accepted` are both endings, and neither is reopened by a person:
#: a finding that comes back is a *new* finding under a different key, or the same
#: finding whose item is still there. Reopening would make "resolved" mean "resolved
#: for now", which is the ambiguity the finding key exists to remove.
TERMINAL_STATES: Final[frozenset[str]] = frozenset({ItemState.RESOLVED.value, ItemState.ACCEPTED.value})

#: Every product role, for the transitions any of them may make.
#:
#: Spelled through `core/roles.py`'s slots rather than written out, so a renamed role
#: fails at import here rather than becoming a permission nobody holds.
ANY_PRODUCT_ROLE: Final[frozenset[str]] = frozenset({SECURITY_REVIEWER, PACKAGING_ENGINEER, LEADERSHIP})


@dataclass(frozen=True, slots=True)
class Transition:
    """One legal move, and what it takes to make it."""

    from_state: str
    to_state: str

    #: Who may make it. A frozenset because most moves are open to any role and one
    #: is not; an *any-of* rather than an all-of, for the reason
    #: `core/permissions.py` gives about surfaces.
    required_roles: frozenset[str]

    #: What the audit row says happened, in the words a reviewer reads.
    describes: str

    #: Whether a justification is required. True for exactly one transition, and
    #: required by the declaration so the service refuses without one rather than
    #: each caller remembering to check.
    requires_justification: bool = field(default=False)


#: The whole machine.
#:
#: Read it as a picture: everything enters at `open`, a person acknowledges it
#: (`triaged`), and from there it either goes to somebody who can act (`routed`,
#: `in_progress`, `resolved`) or is accepted as a risk. Nothing returns to `open`,
#: nothing leaves a terminal state, and the only move a single role owns is the one
#: that decides not to fix something.
TRANSITIONS: Final[tuple[Transition, ...]] = (
    Transition(
        from_state=ItemState.OPEN.value,
        to_state=ItemState.TRIAGED.value,
        required_roles=ANY_PRODUCT_ROLE,
        describes="acknowledged the finding",
    ),
    Transition(
        from_state=ItemState.TRIAGED.value,
        to_state=ItemState.ROUTED.value,
        required_roles=ANY_PRODUCT_ROLE,
        describes="sent it to the queue that can act on it",
    ),
    # Claiming without routing, because the person who triaged it is often the person
    # who will do it, and forcing a routing step through their own queue is
    # ceremony that teaches people to click past states.
    Transition(
        from_state=ItemState.TRIAGED.value,
        to_state=ItemState.IN_PROGRESS.value,
        required_roles=ANY_PRODUCT_ROLE,
        describes="claimed it",
    ),
    Transition(
        from_state=ItemState.ROUTED.value,
        to_state=ItemState.IN_PROGRESS.value,
        required_roles=ANY_PRODUCT_ROLE,
        describes="claimed it",
    ),
    Transition(
        from_state=ItemState.IN_PROGRESS.value,
        to_state=ItemState.RESOLVED.value,
        required_roles=ANY_PRODUCT_ROLE,
        describes="resolved it",
    ),
    # Putting a claim back. Not in the mockups' diagram and added anyway: without it
    # an item claimed by somebody who then goes on leave is stuck in `in_progress`
    # for ever, and the only way out is a database console -- which is the thing
    # `CPM-AD-22` exists to make unnecessary.
    Transition(
        from_state=ItemState.IN_PROGRESS.value,
        to_state=ItemState.TRIAGED.value,
        required_roles=ANY_PRODUCT_ROLE,
        describes="released the claim",
    ),
    # The one transition a single role owns, and the one that demands a reason.
    Transition(
        from_state=ItemState.TRIAGED.value,
        to_state=ItemState.ACCEPTED.value,
        required_roles=frozenset({SECURITY_REVIEWER}),
        describes="accepted the risk",
        requires_justification=True,
    ),
)


def transition_for(from_state: str, to_state: str) -> Transition | None:
    """Return the declared transition between two states, if there is one.

    Args:
        from_state: The state the item is in.
        to_state: The state somebody wants it in.

    Returns:
        The declaration, or `None` when the move is not one the machine permits --
        which the service turns into a refusal naming both states.

    """
    for transition in TRANSITIONS:
        if transition.from_state == from_state and transition.to_state == to_state:
            return transition
    return None
