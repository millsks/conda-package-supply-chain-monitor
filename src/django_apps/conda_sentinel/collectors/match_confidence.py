"""How certain an advisory source is that its advisory applies -- three values, and nothing else.

One `TextChoices` class, in a module of its own, and the module is the point --
the same point `identity/confidence.py` makes and for the same mechanical
reason. `collectors/models.py` reads this vocabulary for
`VulnerabilityFinding.match_confidence`, while the collector that decides what a
row says reads `VulnerabilityFinding` -- so declaring it in either of those two
files makes them import each other, and Python resolves that by failing at
import. The vocabulary is a leaf instead: it imports `django.db.models` and
nothing else, it depends on no model and no collector, and both sides import it
without importing each other. `collectors/vulnerability.py` re-exports it, so a
reader looking for the vocabulary beside the collector that reads it finds it.

**It is deliberately not an outcome type, and that is a decision rather than an
omission** (`CPM-AD-5`). `core/outcomes.py`'s `outcome_type` composes the
*derived-status* vocabulary: values a policy pass computed, carried verbatim on
every read surface (`CPM-AD-24`) and swept by
`tests/unit/django_apps/test_outcome_field_audit.py`. Match confidence is
neither computed nor derived -- **the advisory source states it**, the collector
records it as stated, and no policy in this product produces one. Composing it
from `OutcomeState` would put a source's own assertion into the vocabulary
`CPM-AD-5` governs, where `unknown` and `not_found` would suddenly be things a
source could claim about its own certainty. The precedent is exact:
`IdentityConfidence` is a plain `TextChoices` for the same reason and says so in
its own docstring.

**And it is never abbreviated to "confidence".** The PRD glossary is emphatic
that match confidence is "the separate, unrelated certainty that a vulnerability
advisory applies to a given package and version", never abbreviated, while
*confidence* alone means package identity and nothing else. So the class is
`MatchConfidence`, the column is `match_confidence`, and neither this module nor
the collector spells the bare word anywhere it could be read as the other thing.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from django.db import models

__all__ = ["MatchConfidence"]


class MatchConfidence(models.TextChoices):
    """How an advisory source says it matched the version it was asked about.

    Three values, hyphenated in the spelling `IdentityConfidence` uses for
    `inventory-derived`: `CPM-AD-5`'s fixed-lowercase rule binds *derived-status*
    vocabularies, and this is not one -- see the module docstring.

    **No precedence order in this product reads these values.** `CPM-AD-5`'s
    single total order is over `OutcomeState` and is `core`'s alone, and no
    function anywhere ranks, compares or reduces a match confidence. What the
    declaration order below *is* is the order Django hands a form, an admin
    select and a serializer's choice list -- it is presentation, and it is
    strongest-claim-first for that reason alone. Whether a `name-only` match is
    worth acting on is a judgement `CPM-FR-17`'s policy pass makes
    (`CPM-SECURITY-S04`), from a rule set that is versioned data, and that story
    is where an order over these values would be declared if one ever is.

    **Every value is the source's claim about its own work, and nothing in this
    product corroborates it.** The row records the version *this product* asked
    about and the certainty the source asserted; it does not carry what the source
    actually compared, so an adapter that matched on name alone and stated
    `exact-version` produces a row indistinguishable from one that did the work.
    That is inherent in a pluggable source (`CPM-AD-29`) and is why the
    descriptions below say what a source is *claiming* rather than what happened.

    The three are the whole vocabulary because they are the three distinct claims
    an advisory source can make about a version, and a source whose answer is none
    of them is a source whose shape this collector does not understand -- refused
    rather than recorded, on the terms every other document field is refused.

    Attributes:
        EXACT_VERSION: The source claims it matched the version it was handed
            against an advisory's enumerated affected versions. The strongest
            claim: no range was interpreted by anybody.
        EXACT_RANGE: The source claims it evaluated the version it was handed
            against the advisory's affected range, in that ecosystem's own version
            grammar. The range semantics are the source's -- this product
            evaluates none (`CPM-AD-8`).
        NAME_ONLY: The source claims it matched the package by name or identifier
            and could not place the version inside or outside the advisory's
            range. The advisory is about this package; whether it is about the
            version we ship is what the finding does **not** say, and the row says
            so rather than presenting the match as settled.

    """

    EXACT_VERSION = "exact-version"
    EXACT_RANGE = "exact-range"
    NAME_ONLY = "name-only"
