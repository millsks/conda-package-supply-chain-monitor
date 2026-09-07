"""What a pass may *return*, which the registry cannot check and the database will not.

`core/policy.py` checks what a pass **claims** at registration. This is the other
half: what it actually handed back for one package, checked before the writer
puts it in a row.

**Three refusals, and the second is the one that surprises people.** `choices` is
a `ModelForm` and `full_clean()` rule -- Django enforces it on neither `save()`
nor `create()` -- so a pass returning `"clean"` where the column offers `ok`
writes `"clean"` into the database, and `CPM-AD-24` then has every read surface
emit it verbatim to a consumer that has never heard of it. `CPM-AD-5` puts the
vocabulary in the column's own `choices` precisely so it is declared once, and
this is what reads it.

**`None` is refused rather than given a reading**, and the docstring on
`_owned` argues why: it has two plausible ones, "leave the column alone" (which a
full-row replace cannot honour) and "write the default" (which is the merge the
writer exists not to do). A pass that means "nothing determinate" has four
sentinels to say it with (`CPM-FR-6`), and one that means "I did not run here"
omits the key.

**The synthetic rollup is `tests/passes.py`'s**, for the reason that module
gives: the real one now declares exactly one contributable column,
`currency_status`, and `CurrencyPass` owns it from `django.setup()` onwards -- so
a fixture pass returning it would be refused for colliding with a real owner, and
each refusal here would be measuring that collision rather than the rule it names.
A column nobody owns is what these cases need. Sharing one declaration with
`tests/unit/django_apps/test_rollup_row.py` is what stops two synthetic rollups
disagreeing about which column is contributable while both modules pass.

Reads no database and opens no network: the validation is a function over a
mapping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_package_supply_chain_monitor.core import policy_run as policy_run_module
from conda_package_supply_chain_monitor.core import rollup as rollup_module
from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.outcomes import OutcomeVocabularyError
from conda_package_supply_chain_monitor.core.outcomes import outcome_type
from conda_package_supply_chain_monitor.core.policy import PolicyPassError
from conda_package_supply_chain_monitor.core.rollup import contributable_columns
from conda_package_supply_chain_monitor.core.rollup import permitted_values
from conda_package_supply_chain_monitor.policies.currency import ROLLUP_COLUMN
from conda_package_supply_chain_monitor.policies.feedstock import ROLLUP_COLUMN as FEEDSTOCK_ROLLUP_COLUMN
from tests.passes import A_DOMAIN_STATUS
from tests.passes import FIRST_DOMAIN
from tests.passes import rollup_with_a_domain_column
from tests.passes import working_pass_class

if TYPE_CHECKING:
    from django.db import models

#: A value the column's vocabulary does not offer. Spelled as a word somebody
#: would plausibly reach for -- a synonym of `ok` -- rather than as gibberish,
#: because that is the mistake this refusal is actually about.
AN_INVENTED_VERDICT: Final[str] = "clean"

#: A determinate verdict the column does offer.
A_VERDICT: Final[str] = OutcomeState.OK.value

#: A stamp column, used to show the vocabulary lookup is about *contributable*
#: columns rather than about every field the rollup has.
A_STAMP: Final[str] = "confidence"


@pytest.fixture
def a_rollup_with_a_domain_column(monkeypatch: pytest.MonkeyPatch) -> type[models.Model]:
    """Substitute a rollup that declares one contributable column, with choices.

    Args:
        monkeypatch: pytest's patcher, used to point `core/rollup.py` at the
            synthetic model where it names the real one. It is also the teardown.

    Returns:
        The synthetic rollup model.

    """
    synthetic = rollup_with_a_domain_column()
    monkeypatch.setattr(rollup_module, "ROLLUP_MODEL", synthetic)
    assert contributable_columns() == frozenset({A_DOMAIN_STATUS}), (
        "the synthetic rollup must offer exactly the one column these cases are about"
    )
    return synthetic


def owned(produced: dict[str, str | None]) -> object:
    """Validate one pass's output for one package, the way the orchestration does.

    Args:
        produced: What the pass returned.

    Returns:
        The mapping, when it is acceptable.

    """
    declared = working_pass_class(name=FIRST_DOMAIN, contributes=(A_DOMAIN_STATUS,))
    return policy_run_module._owned(declared(), produced)  # type: ignore[arg-type] # noqa: SLF001 - the validation is this module's whole subject


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_a_verdict_the_column_offers_is_accepted() -> None:
    """The anti-vacuity guard: a validator that refused everything would pass every case below."""
    assert owned({A_DOMAIN_STATUS: A_VERDICT}) == {A_DOMAIN_STATUS: A_VERDICT}
    assert owned({}) == {}


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_a_verdict_the_column_does_not_offer_is_refused() -> None:
    """Django validates `choices` on neither `save()` nor `create()`, so nothing else would.

    The refusal names the pass and the column, because a message saying only that
    a value was rejected sends the reader looking through eight passes for which
    one produced it.
    """
    with pytest.raises(PolicyPassError, match=AN_INVENTED_VERDICT) as refusal:
        owned({A_DOMAIN_STATUS: AN_INVENTED_VERDICT})

    assert FIRST_DOMAIN in str(refusal.value)
    assert A_DOMAIN_STATUS in str(refusal.value)


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_none_is_refused_rather_than_read_as_the_default() -> None:
    """The one value with two readings, and neither is one this writer can honour.

    "Leave the column alone" is not available to a full-row replace, and "write
    the default" is the merge the writer exists not to do -- silently, on a row
    that names a run which did not produce that value. The message points at the
    sentinels, because that is what a pass meaning "nothing determinate" should
    have said.
    """
    with pytest.raises(PolicyPassError, match="None"):
        owned({A_DOMAIN_STATUS: None})


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_a_column_the_pass_never_declared_is_still_refused() -> None:
    """The refusal that was already here, kept in the same table as the two new ones.

    A pass declaring `licence_status` and returning `currency_status` writes into
    a column another pass owns -- `CPM-AD-11`'s single-owner rule broken at
    runtime by a declaration that passed every static check.
    """
    with pytest.raises(PolicyPassError, match="currency_status"):
        owned({"currency_status": A_VERDICT})


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_the_vocabulary_is_the_columns_own_and_not_the_base_five() -> None:
    """A per-status type's determinate verdicts are legitimate, and must pass.

    `core.outcomes.outcome_type` composes a per-status type from the four
    sentinels plus verdicts of its own, and `CPM-AD-5` is explicit that this is
    how a licence or vulnerability outcome is built. A check against
    `OutcomeState`'s five values would refuse `violation` -- a correct verdict
    from a correctly composed type -- so the lookup reads the *column's* declared
    choices instead.

    The synthetic column declares `OutcomeState.choices`, so what this asserts is
    the shape of the rule rather than a second vocabulary: every sentinel the
    composed type carries is accepted here, and the determinate verdict it adds
    is exactly the value a base-five check would have refused.
    """
    composed_type = outcome_type("LicenceOutcome", [("VIOLATION", "violation")])
    offered = permitted_values(A_DOMAIN_STATUS)

    assert {member.value for member in composed_type} - offered == {"violation"}, (
        "the composed type must add a verdict the synthetic column does not offer, or this case cannot "
        "show the difference between the column's vocabulary and the base five"
    )
    for sentinel in composed_type:
        if sentinel.value in offered:
            assert owned({A_DOMAIN_STATUS: sentinel.value}) == {A_DOMAIN_STATUS: sentinel.value}


@pytest.mark.usefixtures("a_rollup_with_a_domain_column")
def test_the_permitted_values_of_the_column_are_its_declared_choices() -> None:
    """Read straight off the field, so a column and its vocabulary cannot drift.

    A table of values written beside the column would be the second declaration
    `CPM-AD-5` exists to prevent -- and it would be right on the day it was
    written.
    """
    assert permitted_values(A_DOMAIN_STATUS) == {state.value for state in OutcomeState}


def test_a_column_declaring_no_vocabulary_is_refused_rather_than_waved_through() -> None:
    """`CPM-AD-5` requires a `CharField(choices=...)` per derived status.

    A column without them is one no contribution can be checked against, so the
    refusal is on the *declaration* rather than on whatever value happened to
    arrive -- which is where it can still be fixed. Measured against a real
    rollup column that legitimately has none: `policy_versions` is a map, not a
    status, and the message must be about a missing vocabulary rather than about
    a bad value.
    """
    with pytest.raises(OutcomeVocabularyError, match="policy_versions"):
        permitted_values("policy_versions")


def test_the_real_rollups_columns_already_have_owners() -> None:
    """The honest statement of what this module stands in for, now that the columns are real.

    `PackageHealth` declares two contributable columns -- `currency_status`
    (`CPM-CURRENCY-S06`) and `feedstock_presence_status` (`CPM-CURRENCY-S07`) --
    and an adopted pass owns each from `django.setup()` onwards. So the refusals
    here still need a substitute: a fixture pass contributing a real column would
    collide with its real owner, and each case would be measuring that collision
    instead of the rule it names. A column nobody owns is what the synthetic
    rollup supplies.

    The end-to-end half is no longer missing, which is the other thing this says:
    `tests/integration/django_apps/test_currency_policy.py` drives a real
    contribution through the orchestration onto a real rollup row.

    Both directions, because either alone passes for the wrong reason: the offered
    set must be exactly the one real column, and `A_STAMP` must still be outside
    it -- a stamp that had drifted into the contributable set would make every
    refusal in this module about a column a pass is entitled to.
    """
    assert contributable_columns() == frozenset({ROLLUP_COLUMN, FEEDSTOCK_ROLLUP_COLUMN})
    assert rollup_module.ROLLUP_MODEL is PackageHealth
    assert A_STAMP not in contributable_columns()
