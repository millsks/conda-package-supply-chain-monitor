"""`CPM-AD-4`'s gate: three rows, and the one that must *not* change anything.

The gate is one function in `core` because eight policy passes are coming and
the failure worth preventing is not that one of them gets the rule wrong -- it is
that eight of them each get it slightly differently, so "what may automation
claim about an unmapped package" has eight answers and no way to tell which one
produced a row.

The `inventory-derived` row carries the weight here. Both other rows are
one-liners that could hardly be written wrongly; the third is the one where a
plausible misreading of `CPM-FR-5` -- "do not claim things about packages you are
unsure of" -- would downgrade every verdict about the majority of the inventory
to `unknown`, and the resulting rollup would look perfectly well-formed. So it is
asserted as a *pass-through of a determinate value*, not merely as "not
`unknown`".

Reads no database and opens no network: the gate is a pure function over two
strings.
"""

from __future__ import annotations

from typing import Final

import pytest

from conda_package_supply_chain_monitor.core.confidence import GATED_VALUE
from conda_package_supply_chain_monitor.core.confidence import ConfidenceError
from conda_package_supply_chain_monitor.core.confidence import gated_status
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence

#: A determinate verdict, which is what the two undegraded rows must return
#: unchanged. The generic determinate value rather than a per-status verdict,
#: because no per-status type exists yet.
A_DETERMINATE_VERDICT: Final[str] = OutcomeState.OK.value

#: A sentinel verdict a pass legitimately produced, used to show the gate does
#: not "improve" a value either. A gate that only ever wrote `unknown` downwards
#: would satisfy every case below except this one.
A_SENTINEL_VERDICT: Final[str] = OutcomeState.NOT_APPLICABLE.value

#: A confidence value nothing declares. Spelled as a plausible fourth value
#: rather than as `"nonsense"`, because the failure this refusal is about is a
#: fourth value being *added* without a decision about what may be claimed at it.
AN_UNDECLARED_CONFIDENCE: Final[str] = "asserted"


def test_the_gate_writes_unknown_for_an_unmapped_package() -> None:
    """`CPM-FR-5`: automation claims nothing about a package whose identity is unresolved.

    Expressed as writing a value rather than as suppressing a row, which is what
    keeps `CPM-AD-11`'s "exactly one row per package" true: a missing row would
    be ambiguous between "not computed yet" and "not confident enough", and no
    read surface can tell those apart.
    """
    assert gated_status(A_DETERMINATE_VERDICT, confidence=IdentityConfidence.UNMAPPED) == GATED_VALUE
    assert OutcomeState.UNKNOWN.value == GATED_VALUE


def test_an_inventory_derived_identity_does_not_degrade_the_verdict() -> None:
    """The row this module exists for, and the one a plausible misreading gets wrong.

    An inventory-derived identity is a real identity that a resolver established
    from the inventory rather than from a verified mapping. Downgrading its
    verdicts would throw away every determinate answer this product can give
    about the majority of its inventory, and the resulting rollup would look
    entirely well-formed. What the reader needs is the provenance beside the
    verdict, which is why `PackageHealth.confidence` is a column of its own.
    """
    gated = gated_status(A_DETERMINATE_VERDICT, confidence=IdentityConfidence.INVENTORY_DERIVED)

    assert gated == A_DETERMINATE_VERDICT
    assert gated != GATED_VALUE, "an inventory-derived identity is a real identity; its verdicts are not degraded"


def test_a_verified_identity_passes_through_untouched() -> None:
    """The row that needs no argument, asserted anyway so the three are one table."""
    assert gated_status(A_DETERMINATE_VERDICT, confidence=IdentityConfidence.VERIFIED) == A_DETERMINATE_VERDICT


@pytest.mark.parametrize(
    "confidence",
    [IdentityConfidence.VERIFIED, IdentityConfidence.INVENTORY_DERIVED],
    ids=["verified", "inventory-derived"],
)
def test_the_gate_never_improves_a_sentinel(confidence: IdentityConfidence) -> None:
    """A gate is a ceiling, not a rewrite.

    A pass that answered `not_applicable` said the question was never ours to
    ask, and no amount of identity confidence turns that into something else.
    Without this, a gate implemented as "return the better of the two" would pass
    every other case here.
    """
    assert gated_status(A_SENTINEL_VERDICT, confidence=confidence) == A_SENTINEL_VERDICT


def test_an_unrecognised_confidence_is_refused() -> None:
    """A fourth confidence value needs a decision, not a default.

    Passing it through is the silent option, and it is the wrong one: a value
    added to `IdentityConfidence` without a rule about what may be claimed at it
    would inherit "claim everything" from this function, which is the one default
    that cannot be safely guessed.
    """
    with pytest.raises(ConfidenceError, match=AN_UNDECLARED_CONFIDENCE):
        gated_status(A_DETERMINATE_VERDICT, confidence=AN_UNDECLARED_CONFIDENCE)


def test_the_gate_reads_identitys_own_vocabulary() -> None:
    """No second spelling of three values whose spelling has already been fixed once.

    `identity/models.py` says the hyphen in `inventory-derived` is deliberate and
    that matching the governing document exactly is what keeps a later gate from
    translating between two spellings. This asserts the gate is bound to that
    type rather than to a literal table of its own: every declared value is
    accepted, so a fourth one added there is a value this function has a branch
    for rather than one it refuses.
    """
    for confidence in IdentityConfidence.values:
        gated_status(A_DETERMINATE_VERDICT, confidence=confidence)

    assert IdentityConfidence.INVENTORY_DERIVED.value == "inventory-derived"
