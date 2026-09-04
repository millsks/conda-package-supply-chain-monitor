"""`RunState` is a second vocabulary, and these are the assertions that keep it separate.

`core/runs.py` declares the five states a run-ledger row may hold. The risk it
carries is not that a value is wrong -- there are five of them and they are
obvious -- but that a later reader, seeing `CPM-AD-5`'s "one status type, fixed
values" and finding a second `TextChoices` in `core`, tidies the two together by
building this one with `outcome_type`. That change compiles, migrates, and puts
four permanently unreachable values (`not_applicable`, `not_found`, `unknown`,
`error`) into the `status` column of every ledger row while making `aggregate()`
willing to rank a run's lifecycle against a licence verdict.

So the separation is asserted from both sides: `RunState` carries none of the
four sentinels, and `verify_sentinels` -- the post-condition every composed
outcome type satisfies -- refuses it. A unification would fail here rather than
be discovered in a rollup.

`TERMINAL_STATES` gets its own cases because it is derived by exclusion. That is
the right shape (a sixth ending is terminal the moment it is declared) and it is
also the shape that fails silently if the exclusion is ever written the other way
round, so both halves are pinned: `running` is not in it, and everything else is.

No database and no network: this module reads two module-level declarations.
"""

from __future__ import annotations

import pytest

from conda_package_supply_chain_monitor.core.outcomes import SENTINEL_MEMBERS
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.outcomes import OutcomeVocabularyError
from conda_package_supply_chain_monitor.core.outcomes import verify_sentinels
from conda_package_supply_chain_monitor.core.runs import TERMINAL_STATES
from conda_package_supply_chain_monitor.core.runs import RunState

#: The five members, name to value, written out rather than derived.
#:
#: The one table in this module that is *not* read off the type under test, and
#: deliberately: every other assertion here would pass against a `RunState` whose
#: members had been renamed together. A stored `status` value is what a person
#: reads off a row and what a later query filters on, so a rename is a data
#: migration rather than a refactor, and it should fail here first.
EXPECTED_MEMBERS = {
    "RUNNING": "running",
    "SUCCEEDED": "succeeded",
    "PARTIAL": "partial",
    "FAILED": "failed",
    "SKIPPED": "skipped",
}


def test_run_state_declares_exactly_the_five_expected_members() -> None:
    """The vocabulary itself, pinned name and value.

    Both halves matter for a different reason: the *name* is what product code
    spells, and the *value* is what lands in the column and survives into a
    query somebody writes six months from now.
    """
    assert {member.name: member.value for member in RunState} == EXPECTED_MEMBERS


def test_run_state_values_are_fixed_lowercase_tokens() -> None:
    """The same wire-format rule `CPM-AD-5` states for outcomes.

    The two vocabularies are separate, but the *shape* of a stored status value
    is not a per-vocabulary decision: a run's state is read off a row and shown
    in an operational view exactly as an outcome is, so `"Not Sure"` would be
    just as wrong here.
    """
    assert [value for value in RunState.values if value != value.strip().lower()] == []


def test_run_state_carries_none_of_the_four_outcome_sentinels() -> None:
    """The separation, asserted from the values' side.

    `not_applicable` and `not_found` are meaningless for a run -- a run either
    happened or it did not -- and `unknown` and `error` would collide with
    `RunState`'s own `failed`, giving two spellings of one fact. If any of the
    four appears here, the two vocabularies have started merging.
    """
    sentinel_values = {value for _, value in SENTINEL_MEMBERS}
    sentinel_names = {name for name, _ in SENTINEL_MEMBERS}

    assert sentinel_values & set(RunState.values) == set()
    assert sentinel_names & {member.name for member in RunState} == set()


def test_run_state_is_not_an_outcome_type_product() -> None:
    """The separation, asserted from the factory's side.

    `verify_sentinels` is the post-condition `outcome_type` enforces on
    everything it builds, so a `RunState` that satisfied it would be a
    `RunState` somebody had composed from the outcome vocabulary. It must
    refuse, and refuse with the vocabulary's own error rather than with a bare
    `TypeError`.
    """
    with pytest.raises(OutcomeVocabularyError, match="does not carry the four outcome sentinels"):
        verify_sentinels(RunState)


def test_the_two_vocabularies_share_no_value_at_all() -> None:
    """Not one value in common, which is what makes a stored value unambiguous.

    Stronger than the sentinel check above and worth stating separately: a value
    appearing in both types would make a bare string read out of a column
    interpretable two ways, and `aggregate` ranks by value precisely because
    values are the shared currency.
    """
    assert set(RunState.values) & set(OutcomeState.values) == set()


def test_terminal_states_excludes_running() -> None:
    """`running` is the one state that is not an ending.

    It is the value the row is created with, before the first outbound call, and
    a row still carrying it after the process is gone is the whole observation
    `CPM-EVIDENCE-S03` exists to make.
    """
    assert RunState.RUNNING not in TERMINAL_STATES


def test_terminal_states_covers_every_other_member() -> None:
    """Derived by exclusion, so a sixth ending needs no edit -- and that is checked.

    The failure this guards against is the exclusion being written the other way
    round, or against the wrong member: either produces a `TERMINAL_STATES` that
    is plausible, non-empty, and wrong.
    """
    assert {member for member in RunState if member is not RunState.RUNNING} == TERMINAL_STATES


def test_every_run_state_is_either_running_or_terminal() -> None:
    """The partition is total, which is what lets a reader trust either half.

    A state that was neither would be a row nothing could finalize and nothing
    would report as unfinished.
    """
    assert TERMINAL_STATES | {RunState.RUNNING} == set(RunState)
