"""The three values a package identity's certainty can take, and nothing else.

One `TextChoices` class, in a module of its own, and the module is the point.
`IdentityConfidence` was declared in `identity/models.py` until
`CPM-IDENTITY-S05`, and it could not stay there: `core/models.py` reads it for
`PackageHealth.confidence`, so `core.models` imports `identity.models` -- while
that story's audit row, `identity.IdentityOverride`, has to inherit
`core.models.AppendOnlyModel`. Those two together are a cycle, and Python resolves
it by failing at import with `cannot import name 'AppendOnlyModel' from partially
initialized module`.

**The cycle is broken here rather than by moving the guard.** The alternatives
were moving `AppendOnlyModel` and its queryset out of `core/models.py`, which is
the most safety-critical code in this repository and the one least worth
disturbing, or restating the three values in `core` -- which is the second
spelling `core/confidence.py` says in as many words it exists not to create. What
is left is this: the vocabulary is a leaf. It imports `django.db.models` and
nothing else, it depends on no model and no application, and every module that
needs it -- `identity/models.py`, `core/models.py`, `core/confidence.py`,
`collectors/selection.py` -- can import it without importing anything else.

**`identity/models.py` re-exports it, so nothing else changed.** Every existing
importer spells it `from conda_package_supply_chain_monitor.identity.models
import IdentityConfidence` and still may: the vocabulary belongs to `identity`
and belongs beside the row it describes, and a move that made forty call sites
edit their imports would have been a much larger change than the one this file
is. The rule the split introduces is only the narrow one it had to: a module in
`core` that reads this vocabulary imports it *from here*, because importing it
from `identity.models` is the edge that closes the cycle.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from django.db import models

__all__ = ["IdentityConfidence"]


class IdentityConfidence(models.TextChoices):
    """How certain a package identity is, in the PRD's own spelling.

    `verified`, `inventory-derived` and `unmapped`, verbatim from the PRD
    glossary and `CPM-AD-4`'s table. The hyphen in the middle value is
    deliberate and is not an oversight of `CPM-AD-5`'s fixed-lowercase rule:
    that rule binds *derived-status* vocabularies, the ones composed from
    `OutcomeState` and emitted verbatim on every read surface (`CPM-AD-24`).
    Confidence is neither. It is identity provenance -- a property of what
    resolution established, not a verdict a policy pass computed -- so it is a
    plain `TextChoices` rather than a type composed by
    `core.outcomes.outcome_type`, and matching the governing document exactly is
    what keeps `CPM-IDENTITY-S03`'s gate from translating between two spellings
    of the same three values.

    The order is the one `CPM-AD-4`'s table uses, most certain first. It is
    presentation order and nothing reads it as a ranking: no precedence order
    over these values exists, and `CPM-AD-5`'s single total order is over
    `OutcomeState` and is `core`'s alone.

    Labels are Django's own derivation from the member names, which is why
    `INVENTORY_DERIVED` is spelled with an underscore while its *value* carries
    the PRD's hyphen: the value is the contract and the label is a display
    string.
    """

    VERIFIED = "verified"
    INVENTORY_DERIVED = "inventory-derived"
    UNMAPPED = "unmapped"
