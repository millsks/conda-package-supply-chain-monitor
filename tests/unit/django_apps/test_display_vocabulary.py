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
from django.db import models

from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.permissions import PRODUCT_ROLES
from conda_sentinel.surface.labels import COLLECTOR_STATUS_LABELS
from conda_sentinel.surface.labels import ROLE_LABELS
from conda_sentinel.surface.labels import collector_status_label
from conda_sentinel.surface.labels import display_label
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


@pytest.mark.parametrize("status", ["ok", "failing", "never_run"])
def test_every_collector_status_survives_being_labelled(status: str) -> None:
    """The coverage screen's own vocabulary, held to the rule the module opens with.

    `surface/coverage.py` reports `ok`, `failing` or `never_run`, and none of them is
    an `OutcomeState` -- its docstring argues that `never_run` is deliberately not
    `unknown`, because `unknown` is an answer about a package and this is a statement
    about a collector. So the rule applies: a value a person reads is either a status
    this product asserts, or it has a label.

    Args:
        status: The collector status under test.

    """
    assert A_SLUG_SEPARATOR not in collector_status_label(status), status


def test_only_the_slug_shaped_collector_status_is_given_a_label() -> None:
    """`ok` and `failing` are already what a person would say.

    Spelling them into the map would make it look like a translation table for a
    vocabulary that mostly does not need one -- which is how a later reader concludes
    every value must have a label and gives one to a status, undoing
    `test_no_outcome_state_acquires_a_label` from the other direction.
    """
    assert set(COLLECTOR_STATUS_LABELS) == {"never_run"}


def test_no_outcome_state_acquires_a_collector_label() -> None:
    """`ok` is both a collector status and an `OutcomeState`, so it is the risk here.

    A label for it would reach the coverage screen only, and `CPM-AD-24`'s guarantee
    is that the five states read the same wherever they appear -- including beside a
    collector.
    """
    states = {state.value for state in OutcomeState}

    assert {*COLLECTOR_STATUS_LABELS} & states == set()
    for state in states:
        assert collector_status_label(state) == state, state


def test_an_undeclared_collector_status_falls_back_rather_than_raising() -> None:
    """The same choice `queue_label` and `role_label` make: a label is not worth a 500."""
    assert collector_status_label("something-nobody-declared") == "something-nobody-declared"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("advisories_matched", "Advisories matched"),
        ("present_and_maintained", "Present and maintained"),
        ("never_run", "Never run"),
        ("fix_vulnerability", "Fix vulnerability"),
        # Sentence case, not title case. Django's automatic `TextChoices` label
        # title-cases every word and gives `Not Listed`, which is a heading rather
        # than something somebody says.
        ("not_listed", "Not listed"),
        # A hyphen inside a value is a hyphen in the words; an underscore is this
        # product's separator standing in for a space.
        ("inventory-derived", "Inventory-derived"),
        # Delegated, not re-derived: these have labels of their own already.
        ("identity_review", "Identity review"),
        ("security_reviewer", "Security review"),
        # Cannot derive: an initialism, a name spelled two ways, a version number.
        ("kev", "KEV"),
        ("pypi_release", "PyPI release"),
        ("py314_verification", "Python 3.14 verification"),
        ("ok", "OK"),
    ],
)
def test_a_value_reads_the_way_somebody_says_it(value: str, expected: str) -> None:
    """`CPM-APP-S20`: one entry point, four sources, specific before general.

    Args:
        value: The stored value.
        expected: What a person should read.

    """
    assert display_label(value) == expected


def test_no_label_carries_the_slug_separator() -> None:
    """The tell this module opens with, applied to everything it can reach.

    Every value in every vocabulary that reaches a screen, swept rather than sampled --
    a vocabulary added later is covered the day it exists rather than the day somebody
    remembers this file.
    """
    from conda_sentinel.core.registry import registered_collectors  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.policies import outcomes  # noqa: PLC0415 - as above

    values = {collector.name for collector in registered_collectors()}
    for name in dir(outcomes):
        vocabulary = getattr(outcomes, name)
        if isinstance(vocabulary, type) and issubclass(vocabulary, models.TextChoices):
            values |= set(vocabulary.values)

    assert values, "nothing was swept, so this case is measuring nothing"
    unreadable = sorted(value for value in values if A_SLUG_SEPARATOR in display_label(value))

    assert unreadable == [], f"these still read as slugs: {unreadable}"


def test_a_label_is_never_blank_and_never_raises() -> None:
    """A filter that could blank a status would be a second way to hide one.

    `tone` is in the same module for the same reason: the only way a status becomes
    invisible on a screen is an `{% if %}` somebody adds around it, and neither filter
    may become a second.
    """
    for awkward in ("", "   ", "not-a-vocabulary", "P1"):
        assert display_label(awkward) == awkward or display_label(awkward).strip() != ""
    assert display_label(None) == "None"
    assert display_label(7) == "7"
