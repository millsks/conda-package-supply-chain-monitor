"""`CPM-APP-S15`: a value a person reads is a status this product asserts, or has a label.

The rule is deliberately not "never render a raw value", and getting that distinction
wrong in either direction is a defect:

**A derived status is emitted verbatim and must never acquire a label.** `CPM-AD-24`
says a status appears as its `OutcomeState` value on every read surface, and
`CPM-APP-S07`'s `StatusField` refuses anything else. `unknown` means the same thing on
a screen, in a CSV and in a JSON response *because* nobody translated it. A reader who
has learned the five states carries them between surfaces, and a well-meaning
"Unknown" on one screen takes that away.

**A queue name and a role name are storage.** Nobody says `identity_review` aloud, it
is not a vocabulary anybody learns, and no rule asks it to survive a trip to a screen.
It was reaching the navigation, a page title, a heading and an "owned by" line before
this story, because four templates rendered the value where a label existed or should
have.

So what is checked here is the *pairing*: every queue and every role has a label, no
label is its own value, and the statuses are left alone. The rendered proof --
that the pages actually show the labels -- is
`tests/integration/django_apps/test_queue_views.py`'s and this module's companion
cases in the surface suite.

No database: these are vocabularies and mappings.
"""

from __future__ import annotations

from typing import Final

import pytest

from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.permissions import PRODUCT_ROLES
from conda_sentinel.surface.labels import ROLE_LABELS
from conda_sentinel.surface.labels import labelled_queues
from conda_sentinel.surface.labels import queue_label
from conda_sentinel.surface.labels import role_label
from conda_sentinel.workflow.states import Queue

#: What a stored slug looks like, and therefore what a label must not.
#:
#: An underscore is the tell: it is how this product spells a multi-word *value*, and
#: nothing a person reads is spelled that way. Checked rather than the whole shape,
#: because "looks like a label" is not decidable and "contains the separator we use
#: for slugs" is.
A_SLUG_SEPARATOR: Final[str] = "_"


@pytest.mark.parametrize("queue", [queue.value for queue in Queue])
def test_every_queue_has_a_label_that_is_not_its_value(queue: str) -> None:
    """The four places this leaked were the nav, a title, a heading and an "owned by".

    All four rendered the stored string. The labels existed on `Queue` the whole time
    and nothing used them, which is why this asserts the *pair* rather than the
    presence of a label -- a label equal to its value would satisfy "has a label" and
    change nothing on the screen.

    Args:
        queue: The queue's stored value.

    """
    label = queue_label(queue)

    assert label != queue
    assert A_SLUG_SEPARATOR not in label, label
    assert label[0].isupper(), label


@pytest.mark.parametrize("role", PRODUCT_ROLES)
def test_every_role_has_a_label_that_is_not_its_slot(role: str) -> None:
    """`security_reviewer` reads as a database column, which is what it is.

    Roles reach a reader on the queue page's "owned by" line and in a refusal. They
    have no label anywhere else in the product -- `core/roles.py` is imported at
    settings time and holds the slots and almost nothing else on purpose -- so this is
    the assertion that the presentation layer supplied one for each.

    Args:
        role: The role's slot name.

    """
    label = role_label(role)

    assert label != role
    assert A_SLUG_SEPARATOR not in label, label
    assert label[0].isupper(), label


def test_a_label_is_spelled_out_rather_than_derived_from_the_slot() -> None:
    """`leadership.title()` is "Leadership", and that is not what this role is called.

    The point of a mapping over a transformation: a derived label is one nobody can
    correct without first replacing the mechanism, and the correction is always
    needed -- "Platform and engineering leadership" is what the UX contract calls this
    role and no rule produces it from `leadership`.
    """
    assert role_label("leadership") != "Leadership"
    assert "leadership" in role_label("leadership").lower()


def test_no_outcome_state_acquires_a_label() -> None:
    """The other half of the rule, and the one a tidying pass would break.

    `CPM-AD-24` emits a status verbatim on every surface so the five states mean the
    same thing wherever a reader meets them. A label for `unknown` would be a
    well-meant improvement that quietly made a screen disagree with the CSV exported
    from it.
    """
    labelled = {*ROLE_LABELS}
    states = {state.value for state in OutcomeState}

    assert labelled & states == set(), sorted(labelled & states)
    for state in states:
        assert queue_label(state) == state, state
        assert role_label(state) == state, state


def test_the_navigation_gets_the_value_and_the_label() -> None:
    """Both, because the URL needs one and the reader needs the other.

    A template deriving either from the other is exactly what broke: the nav had the
    value, needed a label, and rendered what it had.
    """
    entries = labelled_queues()

    assert [entry["value"] for entry in entries] == list(Queue.values)
    assert all(entry["label"] != entry["value"] for entry in entries)


def test_an_undeclared_name_falls_back_rather_than_raising() -> None:
    """A label is not worth a 500.

    No surface can reach these with an unknown name -- every one refuses an unknown
    queue with a 404 before rendering anything, and roles come from a closed table --
    so this is about what happens if that ever stops being true, and the answer is
    that the page renders.
    """
    assert queue_label("not-a-queue") == "not-a-queue"
    assert role_label("not-a-role") == "not-a-role"
