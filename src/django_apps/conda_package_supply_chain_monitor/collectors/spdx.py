"""What this product recognises a licence by, as a list a reviewer can read -- and what it refuses.

`CPM-FR-13` asks for the raw licence and its normalized SPDX expression side by
side, and this module is the half that does the normalizing. It is deliberately
**data plus one small rule** rather than a chain of branches: what a component
recognises as a licence is a judgement that will be revised, `CPM-AD-8`'s posture
throughout this product is that rule sets are data, and a reviewer extending the
recognised set should be reading a table rather than tracing control flow. The
table is also what a later licence policy (`CPM-FR-18`, `CPM-SECURITY-S05`) will
be written against.

**It refuses rather than guesses, and that is the whole design.** A licence is the
one surface where a normalizer can quietly turn an ambiguous string into a
confident answer -- `BSD` into `BSD-3-Clause`, `GPL` into `GPL-3.0-only` -- and
every one of those guesses is a permanent claim about somebody's legal obligations
written into a row nothing may correct. So a spelling that is not in the table
below normalizes to **nothing**, the row that carries it records `unknown`, and the
raw string is preserved beside it for a person to look at. `collectors/license.py`
is where that row is shaped.

**The bare family names are absent on purpose.** `bsd`, `gpl`, `lgpl`, `apache`,
`creative commons`, `public domain`, `proprietary`, `other` and `see license file`
are all things conda channels really state, and not one of them names a licence:
`BSD` alone is two-clause or three-clause or four-clause, and the difference is
whether an advertising clause binds. They are review items, and this module makes
them review items by leaving them out rather than by listing them -- a deny list
would be a second table to keep in step with the first.

**A version without a disposition is absent for the same reason, and it is the
case this module got wrong once.** `GPL-2.0`, `GPLv3`, `LGPL-2.1` and `AGPL-3.0`
name a version and say nothing about whether the grant is that version *only* or
that version *or later* -- which is the whole of the difference between a licence
a downstream may relicense forward and one it may not. A table that resolved them
would be making exactly the guess the paragraph above refuses, on the one family
where the guess is legally load-bearing. So the recognised GNU entries are the
current, unambiguous spellings -- `GPL-3.0-only` and `GPL-3.0-or-later` -- and
`GPLv3` reaches a reviewer intact. The same rule removes the bare `psf`, which
could name `Python-2.0` (the CPython licence, which is what a conda channel almost
always means) or `PSF-2.0`; both identifiers are recognised under their own names
and the abbreviation that could mean either is not.

**Grouping, mixed operators and `WITH` are not recognised either.** A parenthesised
expression's meaning depends on precedence this module would have to invent, and so
does an unparenthesised `MIT OR Apache-2.0 AND BSD-3-Clause` -- the same ambiguity
without the punctuation that announces it, so it is refused for the same reason and
not for a weaker one. The right operand of `WITH` is an *exception* identifier drawn
from a different SPDX list that this module does not carry. So
`(MIT OR Apache-2.0) AND BSD-3-Clause`, `MIT OR Apache-2.0 AND BSD-3-Clause` and
`Apache-2.0 WITH LLVM-exception` all reach a reviewer intact rather than being
half-read. Extending the module to any of them is adding data and a case, which is
what this shape is for.

**The operators are recognised in upper case only, which SPDX mandates.** A conda
`license` field is prose at least as often as it is an expression, and prose "A and
B" usually offers a choice -- SPDX `OR` -- while SPDX `AND` means both sets of
obligations bind at once. Folding the case would read one as the other, which is a
guess about legal obligations dressed as a formatting nicety, so `MIT and
Apache-2.0` is a review item and `MIT AND Apache-2.0` is an expression.

**No compliance verdict of any kind lives here.** Nothing below ranks a licence,
calls one permissive, or divides the table into allowed and forbidden. `CPM-FR-18`
owns that judgement, its rule set is versioned data, and a collector may not
compute a derived status (`CPM-AD-8`).

**A leaf module, on the terms `collectors/match_confidence.py` is one.**
`collectors/models.py` reads `DetectionMethod` for a column's `choices` and
`collectors/license.py` reads both the vocabulary and the normalizer, so declaring
either in those files would close an import cycle and fail at start-up. This module
imports `django.db.models` and the standard library, in that direction only.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING
from typing import Final

from django.db import models

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "OPERATORS",
    "RECOGNISED_LICENSES",
    "SPELLINGS",
    "DetectionMethod",
    "LicenseNormalizationError",
    "Normalized",
    "normalize",
]


class LicenseNormalizationError(ValueError):
    """A normalization result was built that could not describe what it claims to.

    A `ValueError` subclass, matching every other "this input cannot describe what
    it claims to" in this product. It is a defect in this module or in a caller
    constructing a `Normalized` by hand, and never something a source can cause:
    `normalize` is total over strings, and every one of its own results satisfies
    the invariant.
    """


class DetectionMethod(models.TextChoices):
    """How a normalized licence expression was established, in the row's own words.

    `CPM-SM-2` measures this product on every licence finding "carrying source,
    timestamp and confidence", and this is the carrying-source half at the level a
    reviewer actually asks about: the row already names the channel it was read
    from, and this names what happened to the string afterwards. A determinate row
    carries one; every other row carries none, because there was nothing to detect.

    **Deliberately not an outcome type** (`CPM-AD-5`), on the terms
    `collectors/match_confidence.py` states: `outcome_type` composes the
    *derived-status* vocabulary, and this is neither a status nor derived from
    one -- it is a description of a step, and composing it from `OutcomeState`
    would make `unknown` and `not_found` things a normalization step could claim
    about itself.

    Hyphenated lower case, in the spelling `MatchConfidence` uses, and for the same
    reason: `CPM-AD-5`'s fixed-lowercase rule binds derived-status vocabularies and
    this is not one.

    Attributes:
        SPDX_IDENTIFIER: The channel stated the SPDX identifier itself, character
            for character. The strongest of the three: nothing was interpreted, and
            the raw and normalized columns differ in no way at all.
        RECOGNISED_SPELLING: The channel stated a spelling of one licence that
            `SPELLINGS` lists -- a different case, a common abbreviation, a
            human-readable name. One licence, one identifier, and the table below
            is the whole of what was consulted.
        SPDX_EXPRESSION: The channel stated two or more recognised licences joined
            by recognised operators, and the expression was normalized operand by
            operand. The row records one expression rather than one row per
            operand: `MIT OR Apache-2.0` is a single statement about a single
            package, and splitting it would record two licences a reader could take
            for two separate grants.

    """

    SPDX_IDENTIFIER = "spdx-identifier"
    RECOGNISED_SPELLING = "recognised-spelling"
    SPDX_EXPRESSION = "spdx-expression"


#: The licence expression operators this module recognises, in their canonical
#: SPDX spelling.
#:
#: Two rather than three. `WITH` is left out because its right operand is an
#: exception identifier from a list this module does not carry, so recognising the
#: operator without the operands would produce an expression naming an exception
#: nothing checked -- see the module docstring.
OPERATORS: Final[frozenset[str]] = frozenset({"AND", "OR"})

#: Every licence this module recognises, as `(SPDX identifier, other spellings)`.
#:
#: **The identifier is always recognised under its own name**, so no entry has to
#: repeat itself; what the second half lists is the *other* ways the same licence is
#: written on a conda channel. Matching is case-insensitive and collapses runs of
#: whitespace, so `MIT`, `mit` and `The  MIT  License` all reach the same row --
#: which is why no entry below spells a case variant.
#:
#: The set is short on purpose. It is what this product will normalize *without
#: guessing*, it is meant to grow by review, and every addition is a decision that
#: one spelling means exactly one identifier. A spelling that could mean two is not
#: an addition -- it is a review item, and leaving it out is how it stays one.
#:
#: **The GNU family carries identifiers and no abbreviations at all.** `GPLv3`,
#: `gpl-3.0` and `agpl-3.0` each name a version and no `-only`/`-or-later`
#: disposition, so each of them is two licences and none of them is an entry here.
#: `freebsd` is absent for a neighbouring reason: the FreeBSD licence is
#: `BSD-2-Clause-Views`, which carries a clause `BSD-2-Clause` does not, so the
#: alias was recording a licence with one fewer obligation than the one stated.
RECOGNISED_LICENSES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("MIT", ("mit license", "the mit license", "mit-license", "expat")),
    ("Apache-2.0", ("apache 2.0", "apache-2", "apache license 2.0", "apache license, version 2.0")),
    ("BSD-2-Clause", ("bsd-2", "bsd 2-clause", "simplified bsd")),
    ("BSD-3-Clause", ("bsd-3", "bsd 3-clause", "new bsd", "modified bsd")),
    ("GPL-2.0-only", ()),
    ("GPL-2.0-or-later", ()),
    ("GPL-3.0-only", ()),
    ("GPL-3.0-or-later", ()),
    ("LGPL-2.1-only", ()),
    ("LGPL-2.1-or-later", ()),
    ("LGPL-3.0-only", ()),
    ("LGPL-3.0-or-later", ()),
    ("AGPL-3.0-only", ()),
    ("AGPL-3.0-or-later", ()),
    ("MPL-2.0", ("mpl 2.0", "mozilla public license 2.0")),
    ("EPL-2.0", ("eclipse public license 2.0",)),
    ("BSL-1.0", ("boost software license 1.0", "boost-1.0")),
    ("PSF-2.0", ()),
    ("Python-2.0", ()),
    ("ISC", ("isc license",)),
    ("Zlib", ("zlib license",)),
    ("Unlicense", ("the unlicense",)),
    ("CC0-1.0", ("cc0", "cc0 1.0")),
)

#: A regular expression, and the only one here: runs of whitespace, collapsed
#: before a spelling is looked up. A channel that states `The  MIT  License` with a
#: doubled space is stating the MIT licence, and a lookup table that had to carry
#: every whitespace variant would be a table nobody could read.
#:
#: **What reaches it in practice is spaces and nothing else.** A value carrying a
#: line break or a tab never gets here: `collectors/license.py` routes it to
#: `unknown` with the raw string preserved, because a channel that states a licence
#: across two lines is stating something this product will not read as one
#: identifier and a reviewer should see it whole. The collapse is still written over
#: `\s+` rather than over a literal space, so a value handed to `normalize` directly
#: -- this function is pure and total over strings -- has one reading rather than
#: two.
_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")


def _folded(value: str) -> str:
    """Return the key a spelling is looked up under.

    Args:
        value: The spelling, as stated or as tabulated.

    Returns:
        The value stripped, its internal whitespace collapsed to single spaces,
        and case-folded -- `casefold` rather than `lower`, because a source may
        state a licence name in any script and `lower` leaves several of them
        distinguishable from their own upper case.

    """
    return _WHITESPACE.sub(" ", value.strip()).casefold()


#: Every recognised spelling, folded, to the SPDX identifier it names.
#:
#: Derived from `RECOGNISED_LICENSES` rather than written out, which is the
#: single-declaration rule applied to itself: a second table here could drift from
#: the readable one above by one character, and the lookup would then recognise
#: something the list a reviewer reads does not.
SPELLINGS: Final[Mapping[str, str]] = MappingProxyType(
    {_folded(spelling): identifier for identifier, others in RECOGNISED_LICENSES for spelling in (identifier, *others)},
)

#: What an expression may not contain, because its meaning would then depend on a
#: precedence this module does not implement. Refused as a whole rather than
#: stripped: a parenthesis removed is a different expression, and the difference is
#: which licences a reader has to satisfy.
_GROUPING: Final[frozenset[str]] = frozenset({"(", ")"})

#: How many distinct operators a flat expression may join its operands with.
#:
#: One. `MIT OR Apache-2.0 AND BSD-3-Clause` needs the same precedence
#: `(MIT OR Apache-2.0) AND BSD-3-Clause` needs, and refusing the parenthesised
#: form while reading the flat one would be refusing the spelling that announces
#: the ambiguity and accepting the spelling that hides it. Named rather than
#: spelled at the comparison, because a bare `1` there reads as an arbitrary bound.
_ONE_OPERATOR: Final[int] = 1

#: The fewest tokens an expression can have -- an operand, an operator and a second
#: operand. Named rather than spelled at the comparison, because a bare `3` there
#: reads as an arbitrary bound rather than as the shape of the smallest expression.
_SHORTEST_EXPRESSION: Final[int] = 3


@dataclass(frozen=True, slots=True)
class Normalized:
    """What normalizing one stated licence concluded, and what it refused.

    Never a failure and never an exception: a licence this module does not
    recognise is a *result* -- the row it becomes carries `unknown` with the raw
    string preserved, which is what makes it reviewable rather than merely wrong
    (`CPM-SECURITY-S03` AC 2).

    **The invariant is enforced rather than described** -- see `__post_init__` --
    on the terms `collectors/kev.py`'s value objects state: a docstring is not
    enforcement, and a result carrying an expression with no method would build a
    row `license_findings` refuses at insert, several frames from the call that was
    wrong.

    Attributes:
        expression: The SPDX expression, or the empty string where nothing was
            recognised. Blank means missing (PRD Appendix A.1) and never "no
            restrictions".
        method: The `DetectionMethod` value naming how the expression was
            established, or the empty string where there is no expression.
        unrecognised: The tokens this module would have had to guess at, in the
            order the source stated them, or empty. What a review item says in its
            own words -- a reviewer reading a row needs to know *which* part of a
            licence string stopped it, not only that something did.

    """

    expression: str
    method: str
    unrecognised: tuple[str, ...]

    def __post_init__(self) -> None:
        """Refuse a result whose expression and whose method disagree.

        Raises:
            LicenseNormalizationError: When exactly one of the expression and the
                method is set, or when a result carrying an expression also names
                tokens it could not recognise. The second is the one worth
                enforcing: a partly-normalized expression written as if it were
                complete is precisely what `CPM-SECURITY-S03`'s contract forbids.

        """
        if bool(self.expression) != bool(self.method):
            missing = "method that produced it" if self.expression else "expression it describes"
            message = (
                f"Normalized(expression={self.expression!r}, method={self.method!r}) sets one of its expression "
                f"and the method that produced it and not the other -- there is no {missing}. A determinate "
                f"licence row requires both (CPM-FR-13), and a blank pair is an unrecognised licence, which is "
                f"the other legal shape."
            )
            raise LicenseNormalizationError(message)
        if self.expression and self.unrecognised:
            message = (
                f"Normalized(expression={self.expression!r}, unrecognised={self.unrecognised!r}) claims a complete "
                f"expression while naming tokens it could not recognise. No partial normalization is written as if "
                f"it were complete: a licence this module cannot read whole is a review item, not a shorter licence."
            )
            raise LicenseNormalizationError(message)


#: The result every refusal returns, built once rather than at each `return`: it
#: carries no expression, no method and no token, which is what an *empty* stated
#: licence normalizes to. A refusal that names tokens builds its own.
_NOTHING_STATED: Final[Normalized] = Normalized(expression="", method="", unrecognised=())


def normalize(raw: str) -> Normalized:
    """Turn one stated licence into an SPDX expression, or refuse to guess at it.

    Pure: no database, no clock, no network, no settings module (`CPM-AD-27`).
    Total over strings -- every input has a result, and an unrecognised one is a
    result rather than a raise, because the row it becomes is the point of the
    story.

    **A single spelling is tried before an expression is.** `Apache License,
    Version 2.0` carries a comma and three spaces and is one licence; reading it as
    an expression first would split it into tokens none of which name anything.
    So the whole stated string is looked up first, and only a string that is not
    itself a recognised spelling is read as an expression.

    **An expression is operands and operators, alternating, separated by
    whitespace, and nothing else.** Each operand must be a recognised spelling that
    is itself a single token, so `Apache 2.0 OR MIT` is *not* recognised -- its
    first operand is two tokens, and deciding where the operand ends is exactly the
    guess this module will not make. `Apache-2.0 OR MIT` is, and states the same
    thing in a form that cannot be misread. Each operator must be upper case, which
    is what SPDX mandates and what tells an expression from prose; and all of them
    must be the *same* operator, because mixing them needs a precedence this module
    does not implement -- see the module docstring for both.

    Args:
        raw: The licence exactly as the channel stated it. Never rewritten: what is
            returned is a second value beside it, and the caller records both.

    Returns:
        The expression and the method that produced it, or a blank pair naming the
        tokens this module would have had to guess at. An empty or whitespace-only
        input returns the blank pair naming nothing -- "the source stated none" is
        a different fact from "the source stated something unreadable", and the
        caller's `detail` keeps them apart.

    """
    stated = raw.strip()
    if not stated:
        return _NOTHING_STATED
    identifier = SPELLINGS.get(_folded(stated))
    if identifier is not None:
        method = (
            DetectionMethod.SPDX_IDENTIFIER.value if stated == identifier else DetectionMethod.RECOGNISED_SPELLING.value
        )
        return Normalized(expression=identifier, method=method, unrecognised=())
    return _expression(stated)


def _expression(stated: str) -> Normalized:
    """Read a stated licence as a compound SPDX expression, or refuse it whole.

    Args:
        stated: The licence, already stripped and already known not to be a
            recognised spelling on its own.

    Returns:
        The normalized expression with `DetectionMethod.SPDX_EXPRESSION`, or a
        blank pair naming what stopped it -- which is every token this module does
        not recognise, rather than only the first, because a reviewer fixing one
        and meeting the next is a reviewer this collector wasted a day of. An
        expression whose tokens are all recognised but which joins them with more
        than one operator names *every* token, on the terms a parenthesised
        expression does: nothing in it is wrong on its own and the whole of it is
        what a reviewer has to read.

    """
    tokens = stated.split()
    if any(character in token for token in tokens for character in _GROUPING):
        return Normalized(expression="", method="", unrecognised=tuple(tokens))
    if len(tokens) < _SHORTEST_EXPRESSION or len(tokens) % 2 == 0:
        # An expression alternates operand, operator, operand, so it has an odd
        # number of at least three tokens. Anything else is a phrase this module
        # has no reading for -- and a phrase read as an expression anyway would
        # pair an operand with whatever word followed it.
        return Normalized(expression="", method="", unrecognised=(stated,))
    parts: list[str] = []
    unrecognised: list[str] = []
    for position, token in enumerate(tokens):
        # Operators are matched exactly -- SPDX mandates upper case, and a folded
        # match would read a prose `and`, which usually offers a choice, as the
        # operator that binds both sets of obligations at once.
        canonical = (token if token in OPERATORS else None) if position % 2 else SPELLINGS.get(_folded(token))
        if canonical is None:
            unrecognised.append(token)
        else:
            parts.append(canonical)
    if unrecognised:
        return Normalized(expression="", method="", unrecognised=tuple(unrecognised))
    if len({token for position, token in enumerate(tokens) if position % 2}) > _ONE_OPERATOR:
        return Normalized(expression="", method="", unrecognised=tuple(tokens))
    return Normalized(
        expression=" ".join(parts),
        method=DetectionMethod.SPDX_EXPRESSION.value,
        unrecognised=(),
    )
