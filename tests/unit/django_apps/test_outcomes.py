"""Tests for the outcome vocabulary, the precedence order and the reducer.

`EVIDENCE.01-UNIT-002`. Everything here is pure: five strings in, one string
out. No database, no network, no filesystem.

Two shapes recur and both are deliberate.

**Nothing writes the order out.** Every expectation about which of two states
wins is derived from `PRECEDENCE` itself, never from a winner spelled here. The
story records that `unknown` above `not_found` is the one free choice in the
order and that a later reading may overturn it; a test carrying its own copy of
the order would make that a two-file change and would pass on either copy alone.
What is asserted instead is the *property* -- the state earlier in the declared
order wins, whichever order is declared -- plus the two boundaries the PRD
actually fixes, which are checked against `CPM-FR-6` rather than against a
tuple.

**Nothing here binds a sequence of `OutcomeState` members to a name.**
`tests/unit/django_apps/test_single_ordering_audit.py` fails the gate on any
module-level or class-level assignment of two or more members, this module
included, because that is what a second ordering looks like. Locals, parametrize
tables and derived tuples are all fine; a module constant would not be.
"""

from __future__ import annotations

from itertools import product

import pytest
from django.db import models

from conda_package_supply_chain_monitor.core.outcomes import DETERMINATE
from conda_package_supply_chain_monitor.core.outcomes import EMPTY_AGGREGATE
from conda_package_supply_chain_monitor.core.outcomes import PRECEDENCE
from conda_package_supply_chain_monitor.core.outcomes import SENTINEL_MEMBERS
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.outcomes import OutcomeVocabularyError
from conda_package_supply_chain_monitor.core.outcomes import aggregate
from conda_package_supply_chain_monitor.core.outcomes import outcome_type
from conda_package_supply_chain_monitor.core.outcomes import verify_sentinels

# The four sentinel names and the exact strings `CPM-AD-5` fixes them to,
# written out rather than read back from the module under test. A derived table
# would agree with whatever it found, which is the one thing this case must not
# do: the values are a wire contract -- they are emitted verbatim on every export
# and every API surface (`CPM-AD-24`) -- so a rename is a breaking change and has
# to be a deliberate edit here.
FIXED_SENTINEL_VALUES = {
    "ERROR": "error",
    "UNKNOWN": "unknown",
    "NOT_FOUND": "not_found",
    "NOT_APPLICABLE": "not_applicable",
}

# The generic determinate value, pinned on the same terms and for the same
# reason. It is the fifth state.
FIXED_DETERMINATE_VALUE = "ok"

# A per-status type of the kind a later story will declare, used to exercise the
# factory without this story creating one for a policy that does not exist. The
# names are deliberately unlike anything in the PRD's policy vocabulary so that
# nothing downstream can start importing it from here.
A_STATUS_TYPE = "WharfOutcome"
A_DETERMINATE_MEMBER = ("MOORED", "moored")
ANOTHER_DETERMINATE_MEMBER = ("ADRIFT", "adrift")


# ---------------------------------------------------------------------------
# Row 1 -- the five states, and the values they are fixed to.
# ---------------------------------------------------------------------------


def test_the_four_sentinels_carry_their_fixed_lowercase_values() -> None:
    """`CPM-FR-6`'s four distinguishable non-answers, by name and by value."""
    for name, value in FIXED_SENTINEL_VALUES.items():
        member = OutcomeState[name]

        assert member.value == value, name
        assert member.value == member.value.lower(), name


def test_the_determinate_value_is_the_fifth_state() -> None:
    """Four sentinels plus one clean value, all separately representable."""
    assert DETERMINATE is OutcomeState.OK
    assert DETERMINATE.value == FIXED_DETERMINATE_VALUE
    assert len(OutcomeState) == len(FIXED_SENTINEL_VALUES) + 1


def test_the_sentinel_table_is_the_enum_minus_the_determinate_value() -> None:
    """`SENTINEL_MEMBERS` is derived, so it cannot drift from the enum by a character.

    Asserted in both directions: the table is exactly the four fixed pairs, and
    the determinate member is not in it -- a table that had swallowed `ok` would
    make every composed type carry a fifth "sentinel" and would make the
    collision check in `outcome_type` reject a caller's own clean value.
    """
    assert dict(SENTINEL_MEMBERS) == FIXED_SENTINEL_VALUES
    assert DETERMINATE.name not in dict(SENTINEL_MEMBERS)


# ---------------------------------------------------------------------------
# Rows 2 and 3 -- composing a per-status type, and refusing a broken one.
# ---------------------------------------------------------------------------


def test_a_composed_type_carries_all_four_sentinels_by_name_and_value() -> None:
    """AC #1's "inherits those four sentinels by name *and* value".

    Both halves matter. A type carrying `NOT_APPLICABLE = "n/a"` satisfies every
    `hasattr` check ever written about it and still writes a value no other
    policy, export or rollup recognises.
    """
    composed = outcome_type(A_STATUS_TYPE, [A_DETERMINATE_MEMBER, ANOTHER_DETERMINATE_MEMBER])

    members = {member.name: member.value for member in composed}

    assert {name: members.get(name) for name in FIXED_SENTINEL_VALUES} == FIXED_SENTINEL_VALUES
    assert members[A_DETERMINATE_MEMBER[0]] == A_DETERMINATE_MEMBER[1]
    assert members[ANOTHER_DETERMINATE_MEMBER[0]] == ANOTHER_DETERMINATE_MEMBER[1]


def test_a_composed_type_puts_the_sentinels_first_and_keeps_the_caller_order() -> None:
    """The choices a `CharField` is handed, in a stable order.

    Not cosmetic: `choices` order is what a form or an admin filter renders in,
    and a per-status type whose ordering depended on dict iteration would render
    differently between two composed types carrying the same members.
    """
    composed = outcome_type(A_STATUS_TYPE, [A_DETERMINATE_MEMBER, ANOTHER_DETERMINATE_MEMBER])

    assert [member.name for member in composed] == [
        *(name for name, _ in SENTINEL_MEMBERS),
        A_DETERMINATE_MEMBER[0],
        ANOTHER_DETERMINATE_MEMBER[0],
    ]


def test_a_composed_type_is_a_text_choices_type_a_char_field_can_take() -> None:
    """What the type is *for*: `CharField(choices=...)`, never a boolean (`CPM-AD-5`)."""
    composed = outcome_type(A_STATUS_TYPE, [A_DETERMINATE_MEMBER])

    assert dict(composed.choices)["not_applicable"], "every member must carry a label a field can render"
    assert [value for value, _ in composed.choices] == [member.value for member in composed]


def test_a_type_composed_without_a_sentinel_is_rejected() -> None:
    """Row 3: rejected at construction, and the message names what is missing.

    Reached through `verify_sentinels` directly rather than through the factory,
    because the factory supplies the sentinels itself and so cannot be made to
    omit one. That is the point of the factory; this is the post-condition that
    makes it a checked property of the *type* rather than a property of the one
    code path that happens to build types today. A later story handed an outcome
    type from anywhere else asserts it with this same call.
    """
    dropped = models.TextChoices(A_STATUS_TYPE, [A_DETERMINATE_MEMBER])

    with pytest.raises(OutcomeVocabularyError) as refusal:
        verify_sentinels(dropped)

    for name in FIXED_SENTINEL_VALUES:
        assert name in str(refusal.value), name


def test_a_type_that_renames_a_sentinels_value_is_rejected() -> None:
    """AC #1's "by name **and** value", exercised on the half that is dangerous.

    A type missing all four sentinels is caught by the crudest possible check.
    The one that actually ships is a type spelling `NOT_APPLICABLE` correctly and
    valuing it `n/a` -- every `hasattr`, every `getattr`, every import passes, and
    the column fills with a token no other policy, export or rollup recognises.
    The refusal names the member, what was expected and what was found, because
    "this type is wrong" sends a reader to compare two member lists by eye.
    """
    renamed = [(name, "n/a" if name == "NOT_APPLICABLE" else value) for name, value in SENTINEL_MEMBERS]
    drifted = models.TextChoices(A_STATUS_TYPE, [*renamed, A_DETERMINATE_MEMBER])

    with pytest.raises(OutcomeVocabularyError) as refusal:
        verify_sentinels(drifted)

    message = str(refusal.value)
    assert "NOT_APPLICABLE" in message
    assert "not_applicable" in message
    assert "n/a" in message
    assert "ERROR" not in message, "only the sentinel that drifted should be reported"


def test_verify_sentinels_refuses_something_that_is_not_an_outcome_type() -> None:
    """Callers are told to catch `OutcomeVocabularyError`, so nothing else escapes.

    The audit in `tests/unit/django_apps/test_outcome_field_audit.py` is the
    caller that matters: it is handed whatever a model put in `choices`, and a
    bare `TypeError` out of here would crash the audit rather than fail it.
    """
    with pytest.raises(OutcomeVocabularyError, match="not an outcome type"):
        verify_sentinels(object())  # type: ignore[arg-type]


def test_a_composed_type_that_carries_every_sentinel_verifies() -> None:
    """The other side of the check, so a `verify_sentinels` that always raised would fail.

    Returns None rather than a verdict, so what is asserted is that it does not
    raise -- which is exactly what a caller depends on.
    """
    assert verify_sentinels(outcome_type(A_STATUS_TYPE, [A_DETERMINATE_MEMBER])) is None


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("ERROR", "boom"),
        ("NOT_APPLICABLE", "na"),
    ],
    ids=["renames-error", "renames-not-applicable"],
)
def test_a_determinate_member_may_not_reuse_a_sentinel_name(member: str, value: str) -> None:
    """Redefining a sentinel is how a type would drift a value while keeping the name."""
    with pytest.raises(OutcomeVocabularyError, match=member):
        outcome_type(A_STATUS_TYPE, [(member, value)])


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("FAILED", "error"),
        ("SKIPPED", "not_applicable"),
    ],
    ids=["aliases-error", "aliases-not-applicable"],
)
def test_a_determinate_member_may_not_reuse_a_sentinel_value(member: str, value: str) -> None:
    """A duplicate value makes the sentinel an alias of a verdict.

    Python's enum machinery would accept the pair and quietly collapse the two
    members into one, so the sentinel would still be *present* while every
    reference to it returned the verdict. Refused before the type is built, with
    the offending pair in the message, rather than left to the `ValueError`
    `enum.unique` raises after the fact.
    """
    with pytest.raises(OutcomeVocabularyError, match=value):
        outcome_type(A_STATUS_TYPE, [(member, value)])


@pytest.mark.parametrize(
    "determinate",
    [
        [A_DETERMINATE_MEMBER, A_DETERMINATE_MEMBER],
        [("MOORED", "moored"), ("MOORED", "elsewhere")],
        [("MOORED", "moored"), ("BERTHED", "moored")],
    ],
    ids=["same-pair-twice", "same-name", "same-value"],
)
def test_two_determinate_members_may_not_collide_with_each_other(determinate: list[tuple[str, str]]) -> None:
    """The sentinel collision rule, applied to the caller's own table.

    Two verdicts sharing a *value* are silently aliased by the enum machinery --
    the second name becomes the first member, and a policy writing `BERTHED`
    reads back `MOORED` -- which is precisely the failure the sentinel check
    exists to prevent. There is no reason it should be caught for four members
    and not for the rest. Two sharing a *name* raise a bare `TypeError` from
    `_EnumDict` that never mentions the type being built.
    """
    with pytest.raises(OutcomeVocabularyError, match="twice"):
        outcome_type(A_STATUS_TYPE, determinate)


def test_a_type_with_no_determinate_member_is_refused() -> None:
    """Four sentinels and no verdict can record that a check ran and never that it passed.

    Left unchecked this builds happily, and the story that reached for it would
    discover the gap only when a policy had nowhere to write a clean result.
    """
    with pytest.raises(OutcomeVocabularyError, match="no determinate members"):
        outcome_type(A_STATUS_TYPE, [])


@pytest.mark.parametrize(
    ("name", "determinate"),
    [
        ("Wharf Outcome", [A_DETERMINATE_MEMBER]),
        (A_STATUS_TYPE, [("not an identifier", "moored")]),
    ],
    ids=["type-name", "member-name"],
)
def test_a_name_that_is_not_an_identifier_is_refused(name: str, determinate: list[tuple[str, str]]) -> None:
    """Refused here, with the offending name, rather than by the enum machinery.

    `TextChoices("Wharf Outcome", ...)` raises from deep inside `enum` with a
    message about class creation, which tells the reader nothing about the
    vocabulary they were declaring.
    """
    with pytest.raises(OutcomeVocabularyError, match="identifier"):
        outcome_type(name, determinate)


def test_every_call_mints_a_distinct_type() -> None:
    """A per-status type is bound once and imported, never rebuilt at the point of use.

    Pinned rather than left to be discovered: two calls with identical arguments
    produce two classes that are unequal by identity, whose members are unequal
    as enum members and equal only as strings. A story that called the factory
    inside a function would get `isinstance` failures that depend on import
    order, which is close to the worst failure mode available.
    """
    first = outcome_type(A_STATUS_TYPE, [A_DETERMINATE_MEMBER])
    second = outcome_type(A_STATUS_TYPE, [A_DETERMINATE_MEMBER])

    assert first is not second
    assert first.MOORED is not second.MOORED
    assert first.MOORED == second.MOORED, "equal as strings, which is what makes `aggregate` work across types"
    assert not isinstance(first.MOORED, second)


# ---------------------------------------------------------------------------
# Row 4 -- the order is one declaration, total, with no ties.
# ---------------------------------------------------------------------------


def test_the_precedence_order_is_total_over_every_state() -> None:
    """Every state appears exactly once: no member unranked, no member ranked twice.

    Both halves are the same edit gone wrong in opposite directions. A sixth
    state added to `OutcomeState` and not placed here would aggregate as
    unrankable and take a policy run down; a state listed twice would give the
    reducer two answers for one input and make the winner depend on which index
    was found first.
    """
    assert len(PRECEDENCE) == len(OutcomeState)
    assert set(PRECEDENCE) == set(OutcomeState)
    assert len(set(PRECEDENCE)) == len(PRECEDENCE)


def test_the_order_never_places_the_determinate_value_above_a_sentinel() -> None:
    """`CPM-FR-6` stated as a property of the order rather than as a tuple.

    "A check that does not apply to a package is never folded into clean or
    unknown" is what forces the determinate value to the bottom: put it anywhere
    else and some sentinel aggregated against it loses, which *is* the fold. This
    is the one constraint the PRD places on the order, so it is asserted
    directly, and it holds for whatever the free part of the order is later
    decided to be.
    """
    determinate_rank = PRECEDENCE.index(DETERMINATE)

    assert determinate_rank == len(PRECEDENCE) - 1
    for name, _ in SENTINEL_MEMBERS:
        assert PRECEDENCE.index(OutcomeState[name]) < determinate_rank, name


# ---------------------------------------------------------------------------
# Rows 5, 6 and 7 -- aggregation.
# ---------------------------------------------------------------------------


def test_aggregating_one_state_returns_it() -> None:
    """The identity case, which every pair below assumes."""
    for state in PRECEDENCE:
        assert aggregate([state]) is state


@pytest.mark.parametrize(
    ("first", "second"),
    list(product(PRECEDENCE, repeat=2)),
    ids=str,
)
def test_every_ordered_pair_aggregates_to_the_state_earlier_in_the_order(
    first: OutcomeState,
    second: OutcomeState,
) -> None:
    """All 25 ordered pairs, and the result does not depend on the order given.

    The expected winner is read out of `PRECEDENCE`, so this case follows the
    declared order wherever it goes rather than pinning today's reading of it.
    Both directions are asserted in one case because order-independence is not a
    separate property here -- it is the same claim, and splitting it would let
    one half pass while the other regressed.
    """
    expected = first if PRECEDENCE.index(first) <= PRECEDENCE.index(second) else second

    assert aggregate([first, second]) is expected
    assert aggregate([second, first]) is expected


def test_a_sentinel_is_never_folded_into_the_determinate_value() -> None:
    """Row 6, and `CPM-FR-6` in the exact words the PRD uses.

    Asserted per sentinel rather than for `not_applicable` alone: "never folded
    into clean" is a claim about all four, and `{unknown, ok}` yielding `ok` is
    the same defect wearing a different name.
    """
    for name, value in SENTINEL_MEMBERS:
        assert aggregate([OutcomeState[name], DETERMINATE]).value == value, name
        assert aggregate([DETERMINATE, OutcomeState[name]]).value == value, name


def test_aggregating_nothing_returns_the_stated_empty_result() -> None:
    """Row 7: a documented answer rather than an accident.

    `unknown` -- see `EMPTY_AGGREGATE` in `core/outcomes.py` for why it is that
    and not a raise. Asserted against the declared constant *and* against the
    state it must not be, because "returns `EMPTY_AGGREGATE`" alone would pass if
    that constant were quietly changed to the clean value.
    """
    assert aggregate([]) is EMPTY_AGGREGATE
    assert EMPTY_AGGREGATE is OutcomeState.UNKNOWN
    assert EMPTY_AGGREGATE is not DETERMINATE


def test_aggregation_accepts_the_bare_string_values() -> None:
    """A value read back from a `CharField` is a `str`, not a member.

    The reducer ranks by value for exactly this reason, and because a per-status
    type's `NOT_APPLICABLE` is a different member object carrying the same value.
    """
    for state in PRECEDENCE:
        assert aggregate([state.value]) is state

    assert aggregate([OutcomeState.NOT_FOUND.value, OutcomeState.ERROR.value]) is OutcomeState.ERROR


def test_aggregation_ranks_a_composed_types_sentinels_identically() -> None:
    """One reducer serves every status in the product.

    The members are different objects from `OutcomeState`'s -- a composed type is
    its own enum -- so this is what makes "rank by value" a property rather than
    an implementation note.
    """
    composed = outcome_type(A_STATUS_TYPE, [A_DETERMINATE_MEMBER])

    assert aggregate([composed.NOT_APPLICABLE, OutcomeState.OK]) is OutcomeState.NOT_APPLICABLE
    assert aggregate([composed.ERROR, composed.UNKNOWN]) is OutcomeState.ERROR


def test_aggregation_refuses_a_value_it_cannot_rank() -> None:
    """A per-status determinate verdict has no rank until a story gives it one.

    Ranking it alongside `ok` by default would be the `CPM-FR-6` fold reached by
    silence: a `violation` aggregated against `ok` would come back `ok` roughly
    half the time, depending on nothing but argument order.
    """
    composed = outcome_type(A_STATUS_TYPE, [A_DETERMINATE_MEMBER])

    with pytest.raises(OutcomeVocabularyError, match=A_DETERMINATE_MEMBER[1]):
        aggregate([composed.MOORED, OutcomeState.OK])


def test_aggregation_refuses_a_bare_string() -> None:
    """`aggregate("ok")` is a mistake, and it must say so rather than iterate characters.

    A `str` is iterable, so without the guard the reducer walks `"ok"` and
    refuses on `'o'` -- a message pointing at a character, in a stack that gives
    no hint the caller forgot a pair of brackets.
    """
    with pytest.raises(OutcomeVocabularyError, match="not the single state"):
        aggregate(OutcomeState.OK.value)


def test_aggregation_refuses_a_value_from_outside_the_vocabulary() -> None:
    """The same refusal for a string that was never an outcome at all.

    A `""` or a `None`-turned-`"None"` arriving from a serializer is the shape a
    boolean status field collapses into, and it must not read as clean.
    """
    with pytest.raises(OutcomeVocabularyError, match="clean"):
        aggregate([OutcomeState.OK, "clean"])
