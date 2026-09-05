"""`CPM-AD-4`'s confidence gate: one function, in `core`, never re-implemented per pass.

`CPM-AD-4` says the gate is "one function in `core`, called by the orchestrating
policy run (`CPM-AD-21`), never re-implemented per pass". There are eight passes
coming -- currency, feedstock, vulnerability, licence, readiness, priority and
the rest -- and the failure this exists to prevent is not that one of them gets
the rule wrong. It is that eight of them each get it *slightly* differently, so
"what may automation claim about an unmapped package" has eight answers and no
way to tell which one produced a given row.

**The gate writes a value; it never suppresses a row.** That is the whole shape
of it. `CPM-AD-11` puts exactly one rollup row per package, unmapped ones
included, and a gate expressed as "skip this package" would produce a rollup
whose missing rows mean two different things -- not yet computed, and not
confident enough to compute -- neither of which a read surface can tell from the
other. Written as a value, `unknown` says precisely what happened: we did not
establish this package's identity, so we are not claiming anything about it. The
row exists, the column is populated, and `OutcomeState.UNKNOWN` is the sentinel
`core/outcomes.py` reserves for exactly this.

**The three rows, and why only one of them changes anything.**

* `unmapped` writes `unknown`. `CPM-FR-5` forbids automation claiming a verdict
  about a package whose identity was never established: the mapping the verdict
  would be about is not known to be this package's.
* `inventory-derived` **records the label and does not degrade the value.** An
  inventory-derived identity is a real identity that a resolver established from
  the inventory rather than from a verified mapping; downgrading its verdicts to
  `unknown` would throw away every determinate answer this product can give
  about the majority of its inventory. What the reader needs is the *provenance*
  beside the verdict, and that is why `PackageHealth` carries `confidence` as a
  column of its own -- the label travels with the row rather than being folded
  into the value.
* `verified` passes through, which needs no argument.

**It reuses `IdentityConfidence` rather than restating three values.**
`identity/models.py` says the hyphen in `inventory-derived` is deliberate and
that matching the governing document exactly is what keeps a later gate from
"translating between two spellings of the same three values". Restating the
values here -- even correctly -- would create the second vocabulary that sentence
exists to prevent, and the two would agree right up until one of them was
edited.

**An unrecognised confidence is refused rather than passed through.** Passing it
through is the silent option: a fourth confidence value added to
`IdentityConfidence` without a decision about what automation may claim at it
would inherit "claim everything" from this function, which is the one default
that cannot be safely guessed. `CPM-FR-5` is about what may be claimed, so the
absence of a rule is a refusal.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import Final

from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence

__all__ = [
    "GATED_VALUE",
    "ConfidenceError",
    "gated_status",
    "require_known_confidence",
]

#: What the gate writes for a package whose identity was never established.
#:
#: Named rather than spelled at the one branch below, because the *role* is what
#: a reader and a test both depend on: this is "we are not claiming anything
#: about this package", and `core/outcomes.py` already owns the sentinel that
#: says so. A second spelling of it here would be a second vocabulary, which is
#: the failure `CPM-AD-5` exists to prevent.
GATED_VALUE: Final[str] = OutcomeState.UNKNOWN.value

#: The confidences this gate has a rule for, by value.
#:
#: Derived from `IdentityConfidence` rather than written out, for the reason the
#: module docstring gives: a literal table here would be the second spelling of
#: three values whose spelling has already been fixed once.
_KNOWN_CONFIDENCES: Final[frozenset[str]] = frozenset(IdentityConfidence.values)


class ConfidenceError(ValueError):
    """A confidence value has no rule about what automation may claim at it.

    A `ValueError` subclass, matching `core/outcomes.py`'s
    `OutcomeVocabularyError` and `core/registry.py`'s `CollectorRegistryError`:
    every "this declaration is unusable" in this product is a `ValueError`, so a
    caller catching one catches them all.
    """


def require_known_confidence(confidence: str) -> str:
    """Refuse a confidence value this product has no rule about.

    Split out of `gated_status` below because the rollup writer needs the same
    refusal on a path where nothing is being gated: it *records* the confidence on
    every row, in a `CharField(choices=...)` Django does not validate on `save()`,
    so a value from outside `IdentityConfidence` would be written into a column no
    read surface understands -- and would then be read back as a package whose
    identity provenance is a string nobody recognises.

    Args:
        confidence: The package's `IdentityConfidence` value.

    Returns:
        The value, unchanged.

    Raises:
        ConfidenceError: When it is not one of `IdentityConfidence`'s values. See
            the module docstring for why an unknown confidence is refused rather
            than treated as certain.

    """
    if confidence not in _KNOWN_CONFIDENCES:
        message = (
            f"{confidence!r} is not an identity confidence, so there is no rule about what automation may "
            f"claim at it. The declared values are {sorted(_KNOWN_CONFIDENCES)} (CPM-AD-4, CPM-FR-5); a "
            f"fourth one needs its gate decided by the story that adds it, not inferred here."
        )
        raise ConfidenceError(message)
    return confidence


def gated_status(value: str, *, confidence: str) -> str:
    """Return what a rollup may claim about a package, given how certain its identity is.

    `CPM-AD-4`'s gate, and the only implementation of it. A pass computes its
    verdict without knowing anything about identity confidence; the orchestrating
    policy run applies this on the way into the rollup, which is what makes the
    rule hold for a pass nobody has written yet.

    Args:
        value: The verdict a pass produced, as its stored string. A member of a
            type `core.outcomes.outcome_type` composed, or one of
            `OutcomeState`'s own values; taken as a string because the gate is
            about *whether* the verdict may be claimed and never about which
            verdict it is.
        confidence: The package's `IdentityConfidence` value.

    Returns:
        `GATED_VALUE` when the identity is `unmapped`, and `value` unchanged
        otherwise. An `inventory-derived` identity is a real identity: its
        verdicts are not degraded, and the label is recorded beside them on the
        rollup row.

    Raises:
        ConfidenceError: When `confidence` is not one of `IdentityConfidence`'s
            values. See the module docstring for why an unknown confidence is
            refused rather than treated as certain.

    """
    if require_known_confidence(confidence) == IdentityConfidence.UNMAPPED:
        return GATED_VALUE
    return value
