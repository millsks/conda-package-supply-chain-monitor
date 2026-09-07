"""`CPM-IDENTITY-S04`: the queue's ordering rules and its refusals, without a database.

Two things belong here rather than in the integration module beside it, and both
for the same reason: they are decisions this product makes in Python, so a
database would only obscure which layer was answering.

**The ordering, and why it must be provable in this tier.** The story's central
claim is that where a missing count sorts is decided in Python rather than by the
backend. The integration cases assert the resulting sequence -- but if the order
were delegated to the database as `ORDER BY internal_component_count DESC, ...`,
SQLite would put NULLs *last* on a descending order, which is exactly what those
cases assert, so every local run and every `test-integration` step without a
`DATABASE_URL` would stay green and only `pixi run gate-postgres` would catch it.
The property would then have one-sided evidence and a developer's own
done-condition run could not observe it. `_breadth_ordering_key` is a pure
function of three values, so the whole rule is assertable here with no database at
all -- which is the tier the divergence is otherwise invisible in.

**The partition of `IdentityConfidence`.** AC 1 requires the filter to be derived
from the enum rather than written as three literals. Both halves and their union
are pinned, so a fourth confidence is a failure here rather than a silent change
to who gets reviewed: `RESOLVED_CONFIDENCES` is the half a new member must be
added to deliberately, and the union assertion is what says so.

**The refusals need no database and that is itself asserted.**
`unresolved_packages` checks the cut-off before it opens a transaction, so the
refusal cases run in a module with no `django_db` marker at all: were a check to
move below the read, pytest-django would fail the case for touching the database
rather than let it pass for the wrong reason.

`_breadth_ordering_key` is private, and importing it here is deliberate. It is the
one piece of this module whose contract is a pure function, and testing it through
`unresolved_packages` would need the database this module exists to do without.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Final

import pytest

from conda_package_supply_chain_monitor.collectors.models import InventoryReadError
from conda_package_supply_chain_monitor.collectors.selection import RESOLVED_CONFIDENCES
from conda_package_supply_chain_monitor.collectors.selection import UNRESOLVED_CONFIDENCES
from conda_package_supply_chain_monitor.collectors.selection import UnresolvedPackage
from conda_package_supply_chain_monitor.collectors.selection import _breadth_ordering_key
from conda_package_supply_chain_monitor.collectors.selection import unresolved_packages
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import Package
from tests.clocks import FIXED_INSTANT

#: A surrogate key, standing in for a real one. Any integer does: the key's role
#: in the order is to be a tiebreak, not to mean anything.
A_KEY: Final[int] = 7

#: A second one, larger, so "the lower key comes first" is a claim about the
#: values rather than about the order they were written in.
A_LATER_KEY: Final[int] = 11

#: Two component counts, the second the larger. Named because the assertions are
#: about *which is bigger*, and two bare integers make that a fact the reader has
#: to re-derive at every call site.
A_COUNT: Final[int] = 3
A_LARGER_COUNT: Final[int] = 9

#: The count that is a genuine observation of "nobody used it", which is the value
#: PRD Appendix A.1 insists stays distinguishable from a missing one.
NO_USERS_OBSERVED: Final[int] = 0


def _key(component: int | None, lob: int | None, package_id: int = A_KEY) -> tuple[bool, int, bool, int, int]:
    """Return the ordering key for one package's breadth, spelled positionally.

    The production signature is keyword-only, which is right for a call site that
    has to say what each number is; a table-driven case comparing a dozen keys
    reads better without the ceremony repeated a dozen times.

    Args:
        component: The internal component count, or `None` when it is missing.
        lob: The internal line-of-business count, or `None`.
        package_id: The surrogate key, defaulted because most cases here are not
            about the tiebreak.

    Returns:
        The sort key `unresolved_packages` orders by.

    """
    return _breadth_ordering_key(
        internal_component_count=component,
        internal_lob_count=lob,
        package_id=package_id,
    )


# ---------------------------------------------------------------------------
# AC #1: the unresolved set is derived from `IdentityConfidence`.
# ---------------------------------------------------------------------------


def test_the_queue_holds_exactly_the_two_unresolved_confidences() -> None:
    """`unmapped` and `inventory-derived`, and `verified` is not among them.

    Asserted against the enum's own members rather than against the strings, so
    this case is about *which confidences* rather than about how they are spelled
    -- the spelling is `IdentityConfidence`'s to fix and
    `tests/unit/django_apps/test_identity_models.py` already pins it.
    """
    assert {
        IdentityConfidence.UNMAPPED.value,
        IdentityConfidence.INVENTORY_DERIVED.value,
    } == UNRESOLVED_CONFIDENCES


def test_the_two_halves_partition_every_confidence_the_enum_declares() -> None:
    """A fourth confidence fails here rather than changing the queue quietly.

    This is the derivation AC 1 asks for, stated as a property: the resolved and
    unresolved sets are disjoint and together they are exactly
    `IdentityConfidence`. A member added without a decision about which half it
    belongs to breaks the union, which is the whole reason the sets are computed
    from the enum instead of listed.
    """
    assert RESOLVED_CONFIDENCES.isdisjoint(UNRESOLVED_CONFIDENCES)
    assert set(IdentityConfidence.values) == RESOLVED_CONFIDENCES | UNRESOLVED_CONFIDENCES


def test_the_resolved_half_is_the_one_a_new_confidence_must_be_added_to() -> None:
    """`verified` alone, which is what makes the complement fail safe.

    The queue is the *complement* of this set rather than the enumerated other
    half, so a confidence nobody has written a rule about -- one a data migration
    stored, or one dropped from the enum while rows still carry it -- arrives in
    the review queue rather than disappearing from it. A package wrongly in the
    queue is a question a human answers once; one wrongly out of it is a package
    nobody ever looks at (`CPM-FR-2`). The integration module asserts the SQL
    actually takes the complement.
    """
    assert {IdentityConfidence.VERIFIED.value} == RESOLVED_CONFIDENCES


# ---------------------------------------------------------------------------
# AC #2 and AC #4: the ordering, decided in Python.
# ---------------------------------------------------------------------------


def test_a_larger_component_count_sorts_first() -> None:
    """`CPM-FR-4` ranks by internal usage breadth, most used first."""
    assert _key(A_LARGER_COUNT, A_COUNT) < _key(A_COUNT, A_COUNT)


def test_the_line_of_business_count_breaks_a_tie_on_components() -> None:
    """The second half of the pair, and only the second.

    PRD Open Question 3b makes the two counts together the breadth, and Open
    Question 8 leaves how they *combine* undecided -- so the order is
    lexicographic over the pair rather than over a weighted sum this story has no
    standing to invent.
    """
    assert _key(A_COUNT, A_LARGER_COUNT) < _key(A_COUNT, A_COUNT)


def test_a_missing_component_count_sorts_after_every_present_one() -> None:
    """Where the NULL goes, decided here rather than by whichever backend is running.

    SQLite would put it first on an ascending order and PostgreSQL last, and the
    two swap over on a descending one. This is the single assertion that says
    which the queue means.
    """
    assert _key(A_COUNT, A_COUNT) < _key(None, None)


def test_missing_counts_partition_to_the_back_of_a_composed_sort() -> None:
    """The parity claim itself, in the tier a developer's own run exercises.

    This is the assertion that a delegated `ORDER BY internal_component_count DESC`
    would fail *here*, with no database involved. Against a real one it would fail
    only under PostgreSQL -- SQLite sorts NULLs last on a descending order, which
    is what the integration cases expect, so the whole local suite would stay
    green while the queue was wrong on the backend that matters. Stated as a
    partition rather than as a sequence, because the claim is "every one of them,
    after every one of the others" rather than a fact about seven particular rows.
    """
    mixed = [
        (None, None, A_KEY),
        (A_COUNT, A_COUNT, A_LATER_KEY),
        (None, None, A_LATER_KEY),
        (NO_USERS_OBSERVED, NO_USERS_OBSERVED, A_KEY),
        (A_LARGER_COUNT, A_COUNT, A_KEY),
    ]

    ranked = sorted(mixed, key=lambda entry: _key(*entry))
    has_breadth = [index for index, entry in enumerate(ranked) if entry[0] is not None]
    has_none = [index for index, entry in enumerate(ranked) if entry[0] is None]

    assert max(has_breadth) < min(has_none)


def test_a_genuine_zero_outranks_a_missing_count() -> None:
    """Blank is missing and is never zero (`CPM-FR-42`, PRD Appendix A.1).

    A package the inventory observed and found nobody using is a fact; a package
    with no observation is the absence of one. The first is ranked, the second is
    ranked last.
    """
    assert _key(NO_USERS_OBSERVED, NO_USERS_OBSERVED) < _key(None, None)


def test_a_missing_line_of_business_count_sorts_after_a_present_one() -> None:
    """The same rule one field down, so the key is total rather than total-ish.

    The check constraint makes both counts present exactly when the state is `ok`,
    so a package with one and not the other is not writable today. The key handles
    it anyway: a rule that only works while a constraint holds is a rule that
    breaks silently the day the constraint is relaxed.
    """
    assert _key(A_COUNT, A_COUNT) < _key(A_COUNT, None)


def test_two_packages_with_identical_breadth_are_ordered_by_the_surrogate_key() -> None:
    """AC 2's tiebreak, and the reason the order is a replay rather than a coincidence.

    `snapshot_as_of` argues that an unordered tie makes a replay stop being a
    replay; a queue that reshuffles between two calls at one cut-off is the same
    defect one layer up.
    """
    assert _key(A_COUNT, A_COUNT, A_KEY) < _key(A_COUNT, A_COUNT, A_LATER_KEY)


def test_two_packages_with_no_breadth_at_all_are_still_ordered_by_the_key() -> None:
    """The three no-breadth states tie with each other, so the key is what separates them.

    A package with no snapshot, one whose latest is `not_found` and one whose
    latest is `error` all carry `None` for both counts, so without this the block
    at the end of the queue would be in whatever order the database returned --
    which differs between SQLite and PostgreSQL and is AC 4's actual claim.
    """
    assert _key(None, None, A_KEY) < _key(None, None, A_LATER_KEY)


def test_sorting_by_the_key_produces_the_whole_ranking() -> None:
    """The rules above compose, asserted over a list rather than pair by pair.

    Built deliberately out of order and sorted, because the property is that the
    key alone determines the sequence -- a set of pairwise comparisons can all
    hold while the composed order is still not the one intended.
    """
    unordered = [
        (None, None, A_LATER_KEY),
        (A_COUNT, A_COUNT, A_LATER_KEY),
        (None, None, A_KEY),
        (A_LARGER_COUNT, NO_USERS_OBSERVED, A_KEY),
        (A_COUNT, A_LARGER_COUNT, A_KEY),
        (A_COUNT, A_COUNT, A_KEY),
        (NO_USERS_OBSERVED, NO_USERS_OBSERVED, A_KEY),
    ]

    assert sorted(unordered, key=lambda entry: _key(*entry)) == [
        (A_LARGER_COUNT, NO_USERS_OBSERVED, A_KEY),
        (A_COUNT, A_LARGER_COUNT, A_KEY),
        (A_COUNT, A_COUNT, A_KEY),
        (A_COUNT, A_COUNT, A_LATER_KEY),
        (NO_USERS_OBSERVED, NO_USERS_OBSERVED, A_KEY),
        (None, None, A_KEY),
        (None, None, A_LATER_KEY),
    ]


def test_the_same_breadth_always_produces_the_same_key() -> None:
    """Determinism spelled out, because "the same sequence twice" is what AC 2 buys.

    The key reads nothing but its three arguments -- no clock, no cached state, no
    row -- so two calls cannot disagree. Asserting it is cheap and it is the
    property the two-call integration case depends on.

    The two calls are bound before they are compared rather than written out on
    either side of the `==`. Comparing the two call expressions in place reads as
    an assertion about one expression against itself, which is a shape a reader
    cannot tell from a typo and which says nothing when it fails.
    """
    first = _key(A_COUNT, A_LARGER_COUNT, A_KEY)
    second = _key(A_COUNT, A_LARGER_COUNT, A_KEY)

    assert first == second, (
        f"two calls on the same breadth produced {first!r} and then {second!r}, so the key reads something "
        f"beyond its three arguments and the queue is not the same sequence twice (AC 2)."
    )


# ---------------------------------------------------------------------------
# The selection is a value, one field deep.
# ---------------------------------------------------------------------------


def test_a_selected_entry_refuses_to_be_rewritten() -> None:
    """The frozen-ness the class argues for, asserted rather than described.

    A surface handed a queue must not be able to restate what was selected at a
    cut-off. The `Package` inside stays as mutable as any model instance -- which
    the class docstring says in as many words -- so this pins the claim that is
    actually made rather than a stronger one that is not true.
    """
    entry = UnresolvedPackage(
        package=Package(canonical_name="unsaved"),
        internal_component_count=A_COUNT,
        internal_lob_count=A_COUNT,
        mappings=(),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.internal_component_count = A_LARGER_COUNT  # type: ignore[misc]


# ---------------------------------------------------------------------------
# The refusals (`CPM-AD-26`), which need no database.
# ---------------------------------------------------------------------------


def test_a_naive_cut_off_is_refused_before_anything_is_read() -> None:
    """The same refusal `snapshot_as_of` makes, at the set-based door.

    There is no `django_db` marker on this case on purpose. The check runs before
    the transaction is opened, so pytest-django's own database block is what
    proves "before anything is read": a refusal moved below the read would fail
    here for touching the database instead of passing for the wrong reason.
    """
    with pytest.raises(InventoryReadError):
        unresolved_packages(cutoff=FIXED_INSTANT.replace(tzinfo=None))


def test_the_refusal_names_the_cut_off_it_was_given() -> None:
    """A message a reader can act on, which is the whole of why it is not a bare `ValueError`.

    `CPM-NFR-3`: the failure says what was wrong with the input rather than that
    something was. The instant is in the message because "a naive cut-off" without
    the value leaves the caller grepping for which of its arguments was naive.
    """
    naive = FIXED_INSTANT.replace(tzinfo=None)

    with pytest.raises(InventoryReadError) as refused:
        unresolved_packages(cutoff=naive)

    assert repr(naive) in str(refused.value)


def test_a_cut_off_that_is_not_an_instant_at_all_is_refused_the_same_way() -> None:
    """`None` is not a cut-off, and the refusal says so rather than raising `AttributeError`.

    Without this the value reaches `is_aware` and comes back as an `AttributeError`
    naming `utcoffset` -- a message about the implementation of a check rather than
    about the argument that was wrong, and one no caller can catch alongside every
    other inventory-read refusal.
    """
    with pytest.raises(InventoryReadError):
        unresolved_packages(cutoff=None)  # type: ignore[arg-type]


def test_a_date_is_refused_because_it_bounds_no_instant() -> None:
    """A `date` is not a `datetime`, and the narrower test is the one that runs.

    The inheritance goes the other way -- a `datetime` *is* a `date` -- so an
    `isinstance(cutoff, date)` check would accept both and this case is what pins
    which of the two was written. A day has no time of day to bound evidence at,
    and guessing midnight in some offset is the silent shift the naive refusal
    exists to prevent.
    """
    with pytest.raises(InventoryReadError):
        unresolved_packages(cutoff=date(2026, 9, 4))  # type: ignore[arg-type]
