"""What a person reads where the product stores a slug, and where the line is drawn.

Three of this product's vocabularies reach a reader: derived statuses, queue names,
and role names. **They are not treated the same, and the difference is the whole of
this module.**

**A derived status is emitted verbatim, and giving it a label would be a defect.**
`CPM-AD-24` says a status appears as its `OutcomeState` value on every read surface,
and `CPM-APP-S07`'s `StatusField` refuses anything else. `unknown` means the same
thing on a screen, in a CSV and in a JSON response precisely because nobody translated
it, and a reader who has learned the five states can carry them between surfaces. A
blanket "never show a raw value" rule would take that away.

**A queue name and a role name are the opposite case.** `identity_review` and
`security_reviewer` are storage: nobody says them aloud, they are not a vocabulary a
reader learns, and no rule requires them to survive a trip to a screen unchanged. They
were reaching the navigation, a page title, a heading and an "owned by" line -- lower
case, underscored, four places -- because the templates rendered the value where a
label existed or should have.

**So the rule is not "labels everywhere". It is: a value a person reads is either a
status this product asserts, or it has a label.** `tests/unit/django_apps/
test_display_vocabulary.py` holds it.

**Two sources underneath, one module on top.** A queue's label is `Queue`'s own --
that is what a `TextChoices` label is for, and a second mapping beside it would be a
second thing to keep true. Roles have no label anywhere: `core/roles.py` is imported
at settings time and deliberately imports almost nothing, so the labels live here
rather than there. What the templates see is one module either way.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from django.utils.translation import gettext_lazy as _

from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER
from conda_sentinel.workflow.states import Queue

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

__all__ = ["ROLE_LABELS", "labelled_queues", "queue_label", "role_label"]

#: What each role is called on a screen.
#:
#: `core/roles.py` holds the slots -- `security_reviewer` and the rest -- and holds
#: nothing else on purpose: it is imported from `config/settings/base.py` at
#: settings-import time, before the app registry exists, and every import added to it
#: is a way for that to stop being true. A label is presentation, presentation is this
#: application's, and this is where it goes.
#:
#: Spelled out rather than derived from the slot by replacing underscores. "Platform
#: and engineering leadership" is not `leadership.title()`, and a rule that produced
#: `Security Reviewer` would be a rule nobody could correct without leaving it.
ROLE_LABELS: Final[dict[str, _StrPromise]] = {
    SECURITY_REVIEWER: _("Security review"),
    PACKAGING_ENGINEER: _("Packaging engineering"),
    LEADERSHIP: _("Platform and engineering leadership"),
}


def queue_label(queue: str) -> str:
    """Return what a queue is called on a screen.

    Args:
        queue: The queue's stored value.

    Returns:
        Its label. The stored value itself for a name that is not a declared queue --
        which no surface should be able to produce, because every one of them refuses
        an unknown queue with a 404 before rendering anything. Falling back rather
        than raising is the choice that keeps a page from 500-ing over a label.

    """
    try:
        return str(Queue(queue).label)
    except ValueError:
        return queue


def role_label(role: str) -> str:
    """Return what a role is called on a screen.

    Args:
        role: The role's slot name.

    Returns:
        Its label, or the slot itself for a name `core/roles.py` does not declare --
        which `tests/unit/django_apps/test_display_vocabulary.py` asserts cannot
        happen for any role this product uses.

    """
    return str(ROLE_LABELS.get(role, role))


def labelled_queues() -> list[dict[str, str]]:
    """Return every queue as the navigation renders it.

    Returns:
        One entry per queue in declaration order, carrying the value the URL needs
        and the label a reader sees. A pair rather than a label alone, because the
        navigation needs both and a template that derived one from the other would be
        the thing this module exists to stop.

    """
    return [{"value": queue.value, "label": str(queue.label)} for queue in Queue]
