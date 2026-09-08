"""Does a declared version specifier admit one Python series? A containment question, and nothing more.

`CPM-PY314-S01` needs one decision made over and over: a project published a
`Requires-Python` specifier, and this product has to say whether that specifier
**admits** the Python series it is assessing, **cannot** admit it, or is written in
a shape this product will not read. This module is the whole of that decision, and
`collectors/python_readiness.py` is its only caller.

**It is a containment question and deliberately not a version comparator.**
`CPM-SECURITY-S06` established that no architecture decision in this product owns
version ordering, and this module does not become one: nothing here ranks two
arbitrary versions, decides which of two releases is newer, or implements PEP 440's
ordering with its epochs, pre-releases, post-releases, development releases and
local versions. What it does is much smaller. A specifier is a bounded grammar over
*numeric release segments*; the Python series being assessed is the half-open
interval `[3.14, 3.15)`; and "does this specifier admit that series" is the question
of whether the two sets intersect. Tuples of integers are compared component-wise
with zero padding, which is what PEP 440 says a release segment comparison is, and
that is the only comparison in this file.

**The series and not the point, and the difference is a real answer.**
`Requires-Python` is evaluated against a full interpreter version, so `>3.14` admits
`3.14.1` while excluding `3.14.0` — and a reader asking "is this project ready for
Python 3.14" means the series rather than one patch release. The target is therefore
an interval, every clause narrows it, and the answer is whether anything is left.

**A shape this module will not read is `undecidable` and never a guess.** That is
`CPM-PY314-S01`'s Block If in as many words: if a specifier shape cannot be answered
as containment, the reason is recorded and the row says `unknown` — never
`inferred_incompatible`, which is a determinate claim about somebody's package. What
is refused is narrow and enumerated: the `===` arbitrary-equality operator, which
PEP 440 defines as a *string* comparison rather than a version one; epochs; and any
release carrying a pre-, post-, development- or local-version segment. Every one of
them is a shape whose answer needs the ordering rules this module refuses to invent.

**An empty answer is not a refusal.** A specifier whose clauses intersect the series
in nothing is `excludes`: the project published a claim, the claim was read, and the
claim cannot admit this Python. That is the one determinate negative
`CPM-PY314-S01` records, and it is what makes an *absence* of metadata
distinguishable from a project that said no.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from django.db import models

__all__ = [
    "ADMITS",
    "ARBITRARY_EQUALITY",
    "CLASSIFIER_PREFIX",
    "EXCLUDES",
    "MAX_CLAUSES",
    "MAX_RELEASE_SEGMENTS",
    "UNDECIDABLE",
    "DecidingSignal",
    "Series",
    "SpecifierReading",
    "admits_series",
    "classifier_for",
    "declares_version_classifiers",
    "series_of",
]

#: The specifier admits at least one release of the series being assessed.
ADMITS: Final[str] = "admits"

#: The specifier was read and cannot admit any release of that series.
EXCLUDES: Final[str] = "excludes"

#: The specifier is in a shape this product will not answer as a containment
#: question. Never `EXCLUDES`: an unreadable claim is not a negative claim.
UNDECIDABLE: Final[str] = "undecidable"

#: How many comma-separated clauses one specifier may carry.
#:
#: A bound rather than an opinion: every clause is parsed and intersected inside a
#: worker's soft time limit (`CPM-AD-9`), and a `Requires-Python` value with more
#: clauses than this is a source doing something other than declaring a Python
#: range. Real ones carry one or two.
MAX_CLAUSES: Final[int] = 32

#: How many dotted segments one release may carry. PEP 440 places no limit;
#: real Python versions carry three, and a value past this is refused rather than
#: compared, on the same terms `MAX_CLAUSES` is.
MAX_RELEASE_SEGMENTS: Final[int] = 8

#: The classifier namespace a project declares a supported Python version under.
#:
#: Spelled once, here, so the reader that looks for the target's classifier and the
#: one that asks whether *any* version classifier was declared cannot drift. The
#: trailing space is part of the separator PyPI's classifier list uses.
CLASSIFIER_PREFIX: Final[str] = "Programming Language :: Python :: "

#: What an *enumerating* version classifier's tail looks like once the prefix is
#: removed: a **dotted** numeric release and nothing else. `:: 3.13` matches;
#: `:: 3 :: Only` does not, and `:: Implementation :: CPython` does not.
#:
#: **A bare major series is deliberately not a match, and the dot is the whole of
#: why.** `Programming Language :: Python :: 3` is a *superset* claim -- it says the
#: project supports Python 3, which contains 3.14 -- rather than an enumeration that
#: left 3.14 out. `declares_version_classifiers` exists to tell "this project
#: enumerated its Pythons and omitted the one being assessed" from "this project
#: said nothing about any minor version", and the umbrella classifier is squarely
#: the second: it corroborates nothing and contradicts nothing. Counting it as an
#: enumeration turns the commonest published shape there is -- `>=3.9` with
#: `:: 3` and `:: 3 :: Only` -- into a *disagreement*, which is `unknown`, which is
#: exactly where `CPM-PY314-S02` spends expensive verification.
_CLASSIFIER_VERSION: Final[re.Pattern[str]] = re.compile(r"^[0-9]+(?:\.[0-9]+)+$")

#: What a release segment may be spelled with, once an operator has been taken off
#: the front: digits and dots, optionally ending in the `.*` PEP 440 permits after
#: `==` and `!=`. Anything else -- a letter, a `!`, a `+`, a bare `*` -- is a shape
#: this module refuses rather than reads.
_RELEASE: Final[re.Pattern[str]] = re.compile(r"^(?P<release>[0-9]+(?:\.[0-9]+)*)(?P<wildcard>\.\*)?$")

#: The comparison operators, longest first so `>=` is never read as `>` and `===`
#: is never read as `==`. Order is load-bearing.
_OPERATORS: Final[tuple[str, ...]] = ("===", "~=", "==", "!=", "<=", ">=", "<", ">")

#: The operators that accept a `.*` wildcard, which PEP 440 permits after exactly
#: these two and nowhere else.
_WILDCARD_OPERATORS: Final[frozenset[str]] = frozenset({"==", "!="})

#: The one operator this module refuses outright.
#:
#: PEP 440 defines `===` as *arbitrary equality*: the two sides are compared as
#: strings rather than as versions, so `===3.14` and `===3.14.0` are different
#: claims about the same interpreter and neither is a containment question. It is
#: refused with a reason rather than guessed at, which is `CPM-PY314-S01`'s Block If.
ARBITRARY_EQUALITY: Final[str] = "==="

#: How many release segments a compatible-release clause needs before it means
#: anything. `~=3` is not a valid compatible release: PEP 440 requires at least
#: `~=X.Y`, because the operator's whole meaning is "hold everything but the last
#: segment".
_COMPATIBLE_RELEASE_SEGMENTS: Final[int] = 2


class DecidingSignal(models.TextChoices):
    """Which piece of declared metadata decided a determinate assessment.

    A plain `TextChoices` in this leaf module rather than in `collectors/models.py`,
    on the terms `collectors/spdx.py`'s `DetectionMethod` states: the models module
    declares it as a column's `choices` and the collector reads it beside the
    decision that produces it, so a type bound in either would close an import
    cycle.

    **Three members and no member for silence.** A row that carries a deciding
    signal is a row that reached a determinate verdict, and the constraint on
    `python_readiness_assessments` says so; the rows that reached none carry a blank
    signal and a `detail` that says which of the several silences they are.

    `BOTH` is a member rather than a preference between the other two, because a
    project that declares a specifier *and* a matching classifier has said the same
    thing twice and a row that named only one of them would lose the corroboration
    a reviewer is entitled to see.
    """

    REQUIRES_PYTHON = "requires-python", "Requires-Python"
    CLASSIFIER = "classifier", "Classifier"
    BOTH = "both", "Both"


#: A Python series, as the two numeric segments that name it: `(3, 14)`.
Series = tuple[int, int]


@dataclass(frozen=True, slots=True)
class SpecifierReading:
    """What one declared specifier says about one Python series.

    Attributes:
        verdict: `ADMITS`, `EXCLUDES` or `UNDECIDABLE`. Never anything else, and
            never a guess: an `UNDECIDABLE` reading is a shape this product will
            not answer, and its caller records `unknown`.
        reason: Why the verdict is `UNDECIDABLE`, naming the clause that stopped
            it. Empty for the two decidable verdicts, which need no reason: the
            specifier is on the row verbatim and says the whole of it.

    """

    verdict: str
    reason: str


@dataclass(frozen=True, slots=True)
class _Bound:
    """One end of a half-open interval over release tuples.

    Attributes:
        release: The release the bound sits at, as numeric segments.
        inclusive: Whether the bound's own release is inside the interval.

    """

    release: tuple[int, ...]
    inclusive: bool


def series_of(series: Series) -> str:
    """Return the dotted spelling of a series, for a locator, a column or a message.

    Args:
        series: The series, as its two numeric segments.

    Returns:
        `"3.14"` for `(3, 14)`.

    """
    return ".".join(str(segment) for segment in series)


def classifier_for(series: Series) -> str:
    """Return the classifier a project declares to claim support for one series.

    Args:
        series: The series being assessed.

    Returns:
        `"Programming Language :: Python :: 3.14"` for `(3, 14)`.

    """
    return f"{CLASSIFIER_PREFIX}{series_of(series)}"


def declares_version_classifiers(classifiers: tuple[str, ...]) -> bool:
    """Report whether a project enumerated Python versions in its classifiers at all.

    Pure. The distinction this function exists for is the one
    `CPM-PY314-S01` turns on: a project that declares **no** version classifier has
    said nothing about any Python, while a project that enumerates several and omits
    the one being assessed has said something a reviewer should see beside whatever
    its specifier claims. Neither is a claim of incompatibility -- a classifier list
    is positive-only and its silence excludes nothing -- but the two are different
    silences and the row's `detail` distinguishes them.

    **An enumeration is a list of *minor* series, so the umbrella classifier is not
    one.** The series this product assesses is always a minor one -- `Series` is the
    two segments that name it -- and `Programming Language :: Python :: 3` is a claim
    *containing* every one of them rather than a list that omitted any. A project
    declaring only the umbrella has not enumerated its Pythons at all, and saying it
    did would make its specifier disagree with a classifier list that never spoke.

    Args:
        classifiers: The classifiers the project declared, exactly as stated.

    Returns:
        True when at least one of them names a dotted Python version.

    """
    return any(_names_a_version(classifier) for classifier in classifiers)


def _names_a_version(classifier: str) -> bool:
    """Report whether one classifier names a Python version rather than something else.

    Args:
        classifier: One declared classifier, exactly as stated.

    Returns:
        True for `Programming Language :: Python :: 3.13`, and False for the bare
        umbrella `... :: 3` (a superset claim rather than an enumeration), for
        `... :: 3 :: Only`, for `... :: Implementation :: CPython`, and for every
        classifier outside the namespace.

    """
    if not classifier.startswith(CLASSIFIER_PREFIX):
        return False
    return bool(_CLASSIFIER_VERSION.match(classifier[len(CLASSIFIER_PREFIX) :].strip()))


def admits_series(specifier: str, *, series: Series) -> SpecifierReading:
    """Read one declared specifier and say whether it admits a Python series.

    Pure: no database, no clock, no network (`CPM-AD-27`). The whole of this
    product's specifier reading, so the collector has one rule to apply and a
    reviewer has one file to read.

    Args:
        specifier: The `Requires-Python` value the project declared, exactly as
            stated. Never blank -- a project that declared none is a silence its
            caller records, not a specifier to read.
        series: The Python series being assessed.

    Returns:
        The reading. `ADMITS` when at least one release of the series satisfies
        every clause; `EXCLUDES` when none does; `UNDECIDABLE`, with a reason, for
        a shape this product will not answer as a containment question.

    """
    clauses = [clause.strip() for clause in specifier.split(",")]
    if len(clauses) > MAX_CLAUSES:
        return SpecifierReading(
            verdict=UNDECIDABLE,
            reason=(
                f"the specifier carries {len(clauses)} clauses and this product reads at most {MAX_CLAUSES}; a "
                f"declaration this long is a source doing something other than naming a Python range"
            ),
        )
    lower = _Bound(release=(*series, 0), inclusive=True)
    upper = _Bound(release=(series[0], series[1] + 1, 0), inclusive=False)
    excluded: list[tuple[_Bound, _Bound]] = []
    for clause in clauses:
        narrowed = _narrow(clause, lower=lower, upper=upper, excluded=excluded)
        if isinstance(narrowed, str):
            return SpecifierReading(verdict=UNDECIDABLE, reason=narrowed)
        lower, upper = narrowed
    if _empty(lower=lower, upper=upper) or _covered(lower=lower, upper=upper, excluded=excluded):
        return SpecifierReading(verdict=EXCLUDES, reason="")
    return SpecifierReading(verdict=ADMITS, reason="")


def _narrow(  # noqa: PLR0911 - one return per operator; a dispatch table would hide the rewrite `~=` needs
    clause: str,
    *,
    lower: _Bound,
    upper: _Bound,
    excluded: list[tuple[_Bound, _Bound]],
) -> tuple[_Bound, _Bound] | str:
    """Apply one clause to the interval under consideration, or say why it cannot be applied.

    Args:
        clause: One comma-separated clause, already stripped.
        lower: The interval's lower bound so far.
        upper: Its upper bound so far.
        excluded: The exclusion ranges gathered so far. Appended to in place, which
            is the one piece of mutation in this module and is confined to the loop
            that owns the list.

    Returns:
        The narrowed bounds, or the reason this clause cannot be read as
        containment.

    """
    parsed = _clause(clause)
    if isinstance(parsed, str):
        return parsed
    operator, release, wildcard = parsed
    if operator == "~=":
        # PEP 440's compatible release, rewritten into the two clauses it is
        # defined as. Nothing is guessed here: the rewrite is the specification's
        # own, and both halves are shapes this module already reads.
        prefix = release[:-1]
        return _narrow(
            f"=={'.'.join(str(segment) for segment in prefix)}.*",
            lower=_raise_lower(lower, _Bound(release=release, inclusive=True)),
            upper=upper,
            excluded=excluded,
        )
    if operator == ">=":
        return _raise_lower(lower, _Bound(release=release, inclusive=True)), upper
    if operator == ">":
        return _raise_lower(lower, _Bound(release=release, inclusive=False)), upper
    if operator == "<=":
        return lower, _lower_upper(upper, _Bound(release=release, inclusive=True))
    if operator == "<":
        return lower, _lower_upper(upper, _Bound(release=release, inclusive=False))
    span = _span(release, wildcard=wildcard)
    if operator == "==":
        return _raise_lower(lower, span[0]), _lower_upper(upper, span[1])
    excluded.append(span)
    return lower, upper


def _clause(clause: str) -> tuple[str, tuple[int, ...], bool] | str:  # noqa: PLR0911 - one return per refusal
    """Split one clause into its operator, its release and whether it carries a wildcard.

    Args:
        clause: One comma-separated clause, already stripped.

    Returns:
        The operator, the release as numeric segments, and whether the clause ended
        in `.*` -- or the reason the clause cannot be read.

    """
    if not clause:
        return "the specifier carries an empty clause, so what it declares cannot be read as a version range"
    operator = next((candidate for candidate in _OPERATORS if clause.startswith(candidate)), "")
    if not operator:
        return (
            f"the clause {clause!r} carries no comparison operator this product reads, so it names no version "
            f"range to test the target against"
        )
    if operator == ARBITRARY_EQUALITY:
        return (
            f"the clause {clause!r} uses arbitrary equality, which PEP 440 defines as a comparison of *strings* "
            f"rather than of versions -- so whether it admits the target depends on how the target happens to be "
            f"spelled, which is not a containment question and is not guessed at here"
        )
    stated = clause[len(operator) :].strip()
    matched = _RELEASE.match(stated)
    if matched is None:
        return (
            f"the clause {clause!r} names {stated!r}, which is not a plain dotted numeric release. An epoch, a "
            f"pre-release, a post-release, a development release or a local version needs the ordering rules this "
            f"product has not decided (CPM-SECURITY-S06), so the specifier is recorded and nothing is inferred "
            f"from it"
        )
    wildcard = matched.group("wildcard") is not None
    if wildcard and operator not in _WILDCARD_OPERATORS:
        return (
            f"the clause {clause!r} ends in a wildcard, which PEP 440 permits after "
            f"{sorted(_WILDCARD_OPERATORS)} and after no other operator"
        )
    segments = tuple(int(segment) for segment in matched.group("release").split("."))
    if len(segments) > MAX_RELEASE_SEGMENTS:
        return (
            f"the clause {clause!r} names a release of {len(segments)} segments and this product compares at most "
            f"{MAX_RELEASE_SEGMENTS}"
        )
    if operator == "~=" and (wildcard or len(segments) < _COMPATIBLE_RELEASE_SEGMENTS):
        return (
            f"the clause {clause!r} is not a compatible release PEP 440 defines: the operator holds every segment "
            f"but the last, so it needs at least {_COMPATIBLE_RELEASE_SEGMENTS} of them and never a wildcard"
        )
    return operator, segments, wildcard


def _span(release: tuple[int, ...], *, wildcard: bool) -> tuple[_Bound, _Bound]:
    """Return the interval one `==` or `!=` clause names.

    Args:
        release: The clause's release, as numeric segments.
        wildcard: Whether the clause ended in `.*`, which makes it a prefix range
            rather than a single release.

    Returns:
        The lower and upper bounds of the range the clause names. A wildcard names
        `[R, R']` where `R'` increments the last segment; an exact release names the
        degenerate closed interval at itself.

    """
    if not wildcard:
        return _Bound(release=release, inclusive=True), _Bound(release=release, inclusive=True)
    return (
        _Bound(release=release, inclusive=True),
        _Bound(release=(*release[:-1], release[-1] + 1), inclusive=False),
    )


def _raise_lower(current: _Bound, candidate: _Bound) -> _Bound:
    """Return whichever lower bound is the stricter of two.

    Args:
        current: The lower bound so far.
        candidate: The one this clause states.

    Returns:
        The stricter bound. At equal releases the exclusive one is stricter.

    """
    order = _compare(candidate.release, current.release)
    if order > 0 or (order == 0 and not candidate.inclusive):
        return candidate
    return current


def _lower_upper(current: _Bound, candidate: _Bound) -> _Bound:
    """Return whichever upper bound is the stricter of two.

    Args:
        current: The upper bound so far.
        candidate: The one this clause states.

    Returns:
        The stricter bound. At equal releases the exclusive one is stricter.

    """
    order = _compare(candidate.release, current.release)
    if order < 0 or (order == 0 and not candidate.inclusive):
        return candidate
    return current


def _empty(*, lower: _Bound, upper: _Bound) -> bool:
    """Report whether an interval holds no release at all.

    Args:
        lower: Its lower bound.
        upper: Its upper bound.

    Returns:
        True when nothing satisfies both bounds -- which is either a lower bound
        above the upper one, or the two meeting at a release at least one of them
        excludes.

    """
    order = _compare(lower.release, upper.release)
    if order > 0:
        return True
    return order == 0 and not (lower.inclusive and upper.inclusive)


def _covered(*, lower: _Bound, upper: _Bound, excluded: list[tuple[_Bound, _Bound]]) -> bool:
    """Report whether the `!=` clauses between them remove every release the interval held.

    Ranges are merged before the coverage question is asked, because two adjacent
    exclusions cover what neither covers alone -- `!=3.14.*` plus `!=3.15.*` over a
    two-series interval is the shape -- and a check that asked them one at a time
    would answer `admits` for a specifier that admits nothing.

    Args:
        lower: The interval's lower bound.
        upper: Its upper bound.
        excluded: The exclusion ranges the specifier's `!=` clauses named.

    Returns:
        True when one merged exclusion range spans the whole interval.

    """
    if not excluded:
        return False
    ordered = sorted(excluded, key=lambda span: (span[0].release, not span[0].inclusive))
    merged: list[tuple[_Bound, _Bound]] = [ordered[0]]
    for span in ordered[1:]:
        previous = merged[-1]
        if _compare(span[0].release, previous[1].release) > 0:
            merged.append(span)
            continue
        merged[-1] = (previous[0], previous[1] if _upper_at_least(previous[1], span[1]) else span[1])
    return any(_lower_at_most(span[0], lower) and _upper_at_least(span[1], upper) for span in merged)


def _lower_at_most(bound: _Bound, other: _Bound) -> bool:
    """Report whether one lower bound starts at or before another.

    Args:
        bound: The bound being asked about.
        other: The bound it is compared with.

    Returns:
        True when everything `other` admits at its low end, `bound` admits too.

    """
    order = _compare(bound.release, other.release)
    return order < 0 or (order == 0 and (bound.inclusive or not other.inclusive))


def _upper_at_least(bound: _Bound, other: _Bound) -> bool:
    """Report whether one upper bound ends at or after another.

    Args:
        bound: The bound being asked about.
        other: The bound it is compared with.

    Returns:
        True when everything `other` admits at its high end, `bound` admits too.

    """
    order = _compare(bound.release, other.release)
    return order > 0 or (order == 0 and (bound.inclusive or not other.inclusive))


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """Compare two releases as PEP 440 says a release segment is compared.

    The only comparison in this module, and it is deliberately the smallest one
    that answers the question: component-wise over integers, with the shorter
    release padded with zeros, because PEP 440 makes trailing zeros insignificant
    (`3.14` and `3.14.0` are the same release). Nothing here knows about epochs,
    pre-releases, post-releases, development releases or local versions -- every one
    of those is refused before it reaches this function.

    Args:
        left: One release, as numeric segments.
        right: The other.

    Returns:
        A negative number when `left` sorts first, zero when they are the same
        release, and a positive number otherwise.

    """
    width = max(len(left), len(right))
    padded_left = (*left, *([0] * (width - len(left))))
    padded_right = (*right, *([0] * (width - len(right))))
    if padded_left < padded_right:
        return -1
    return 0 if padded_left == padded_right else 1
