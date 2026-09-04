"""The product's outcome vocabulary: five states, one order, one aggregation.

Every derived status in this system -- a licence verdict, a vulnerability
verdict, a currency verdict, a rollup over any of them -- answers the same
question and must answer it in the same words. `CPM-AD-5` is the rule; this
module is the whole of its implementation. Four sentinels, one determinate
value, one total precedence order, one reducer. Nothing else in the repository
declares any of them, and `tests/unit/django_apps/test_single_ordering_audit.py`
is what keeps that true rather than merely intended.

**Why the sentinels are separately representable.** `CPM-FR-6` says a check that
does not apply to a package "is never folded into clean or unknown". Three
distinct facts hide behind a boolean status: we looked and found nothing
(`not_found`), we never looked (`unknown`), and looking failed (`error`) -- and a
fourth, that the question was never ours to ask (`not_applicable`). A boolean
column, or a nullable one, can hold at most two of them, so the first policy that
needs the distinction invents a second column to carry it and the second policy
invents a different one. That is `R-01`, the project's highest-scored risk, and
the reason `CPM-AD-5` bans boolean status fields outright rather than
discouraging them.

**Why the determinate type is composed rather than subclassed.** `CPM-AD-5` asks
that a per-status type "inherit" the four sentinels by name and value, and Python
will not give us that literally: an enum that has members cannot be subclassed,
so `class LicenseOutcome(OutcomeState)` raises `TypeError`. What delivers the
property the word is asking for is a factory over one table -- `outcome_type`
below builds every per-status type from `SENTINEL_MEMBERS`, so no type can drift
a name or a value, and it refuses to build one whose determinate members would
drop, rename or alias a sentinel away. Writing the four members out again in each
per-status type is the duplication `CPM-AD-5` exists to prevent, and it is
exactly the duplication that would pass every test written against one type.

**Why `not_applicable` outranks the determinate value.** The order below is
constrained rather than free at that boundary: an order placing `ok` above
`not_applicable` would make aggregating `{ok, not_applicable}` yield `ok`, which
is the fold `CPM-FR-6` forbids in so many words.

**The one genuinely free choice** is `unknown` against `not_found`. Nothing in
the PRD, the architecture spine or the test design fixes it, and no consumer of
the order exists yet. `unknown` is placed the more severe of the two because an
un-observed state hides risk, while `not_found` is an informative negative -- we
looked, and the thing is not there. It is recorded here so that a later reading
can overturn it cheaply: one tuple changes, and the aggregation tests follow it,
because they assert that aggregation matches the *declared* order rather than a
winner written out by hand.

**What aggregation deliberately does not do.** It refuses a value it cannot rank
rather than treating it as determinate. No per-status type exists yet, so the
first caller to aggregate a per-status determinate value (`violation`, say) will
be told, loudly, at the moment it happens. That decision belongs to whichever
story first declares such a type -- `CPM-EP-SECURITY` and `CPM-EP-PY314` are the
epics `CPM-AD-5` binds for policy verdicts -- and to `CPM-EVIDENCE-S07`, which
owns the policy run and the single writer of the rollup and is therefore the
first caller that will aggregate across domains. Ranking an unrecognised value
alongside `ok` here would be the `CPM-FR-6` fold again, arrived at by silence.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix. `CPM-AD-5` above is this product's status rule and
`AD-4`, cited in `core/clock.py`, is the platform's dependency direction -- two
registers, not a typo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final
from typing import cast

from django.db import models

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable
    from collections.abc import Sequence

__all__ = [
    "DETERMINATE",
    "EMPTY_AGGREGATE",
    "PRECEDENCE",
    "SENTINEL_MEMBERS",
    "OutcomeState",
    "OutcomeVocabularyError",
    "aggregate",
    "outcome_type",
    "verify_sentinels",
]


class OutcomeState(models.TextChoices):
    """The five states every derived status in this product is drawn from.

    Fixed lowercase string values, emitted verbatim on every surface
    (`CPM-AD-24`). The four sentinels are `error`, `unknown`, `not_found` and
    `not_applicable`; `ok` is the generic determinate value, the one a
    per-status type refines into verdicts of its own.

    Declared in precedence order, worst first, so that a reader meets the
    members in the same sequence `PRECEDENCE` puts them in. The order is still
    declared separately below and asserted to be total: member order in a class
    body is not a contract, and a member added here without being placed there
    must fail rather than acquire a rank by accident.

    Labels are Django's own derivation from the member names, and are not part
    of the contract. Leaving them derived is what makes a composed per-status
    type carry byte-identical sentinel labels without any machinery to keep two
    label tables in step.
    """

    ERROR = "error"
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"
    NOT_APPLICABLE = "not_applicable"
    OK = "ok"


class OutcomeVocabularyError(ValueError):
    """A type or a value broke the outcome vocabulary's rules.

    Narrow and named rather than a bare `ValueError`, on the same terms as
    `config/authorization/exceptions.py`: a composed type that dropped a
    sentinel and an aggregation handed an unrankable value are both defects in
    the vocabulary itself, and a caller that wants to distinguish them from a
    `ValueError` raised by anything else can.
    """


#: The generic determinate member -- "we looked, the question applies, and the
#: answer is clean". Named rather than spelled `OutcomeState.OK` at each use, so
#: that the *role* is what readers depend on: a per-status type refines this into
#: verdicts of its own, and the sentinel table below is defined by exclusion from
#: it rather than by a second list of four names.
DETERMINATE: Final = OutcomeState.OK

#: The four sentinels, as `(member name, value)` pairs, in declaration order.
#:
#: Derived from `OutcomeState` rather than written out, which is the single-
#: declaration rule applied to itself: a second literal table here could drift
#: from the enum above by one character and every test written against either
#: one alone would still pass. Every per-status type is built from this.
SENTINEL_MEMBERS: Final[tuple[tuple[str, str], ...]] = tuple(
    (state.name, state.value) for state in OutcomeState if state is not DETERMINATE
)

#: The single total precedence order, worst first. Every aggregation of statuses
#: anywhere in this product reduces through this tuple and no other. See the
#: module docstring for which parts of it are forced and which one is a choice.
PRECEDENCE: Final[tuple[OutcomeState, ...]] = (
    OutcomeState.ERROR,
    OutcomeState.UNKNOWN,
    OutcomeState.NOT_FOUND,
    OutcomeState.NOT_APPLICABLE,
    OutcomeState.OK,
)

#: What `aggregate` returns for no states at all, stated once here rather than
#: left to whatever `min()` over an empty sequence happens to do.
#:
#: `unknown`, not a raise and not `ok`. "The worst of nothing observed" is
#: precisely the un-observed state, and it is the answer that stays safe when a
#: caller reaches it by accident: an empty rollup reads as *we do not know*, and
#: no surface can mistake it for clean. A raise would push every caller into a
#: length check, and the caller that forgot one would turn a benign empty set
#: into a failed policy run.
EMPTY_AGGREGATE: Final = OutcomeState.UNKNOWN

#: Rank by value, so that a per-status type's sentinels -- which carry the same
#: values by construction -- rank identically to `OutcomeState`'s own.
_RANK: Final[dict[str, int]] = {state.value: index for index, state in enumerate(PRECEDENCE)}


def verify_sentinels(outcome: type[models.Choices]) -> None:
    """Check that an outcome type carries all four sentinels by name and value.

    The post-condition `outcome_type` enforces on everything it builds, exposed
    separately because it is also the assertion any later story wants to make
    about a type it was handed. Name *and* value: a type that spelled the member
    `NOT_APPLICABLE` but valued it `n/a` would satisfy every `hasattr` check and
    still write a value no other policy recognises.

    Args:
        outcome: The choices type to check.

    Raises:
        OutcomeVocabularyError: When a sentinel is absent, or is present under a
            value other than the one `OutcomeState` fixes, or when `outcome` is
            not an enumerable choices type at all. The message names every
            sentinel that failed and what was found in its place.

    """
    try:
        members = {member.name: member.value for member in outcome}
    except TypeError as not_a_type:
        # Callers are told to catch `OutcomeVocabularyError`, so a bare
        # `TypeError` escaping from here is a hole in that contract: the audit
        # that hands this whatever it found in a model's `choices` would crash
        # rather than report.
        message = f"{outcome!r} is not an outcome type; it cannot be enumerated for sentinels"
        raise OutcomeVocabularyError(message) from not_a_type
    broken = {
        name: members.get(name) for name, value in SENTINEL_MEMBERS if name not in members or members[name] != value
    }
    if broken:
        expected = dict(SENTINEL_MEMBERS)
        detail = ", ".join(
            f"{name}: expected {expected[name]!r}, found {found!r}" for name, found in sorted(broken.items())
        )
        message = f"{outcome.__name__} does not carry the four outcome sentinels -- {detail}"
        raise OutcomeVocabularyError(message)


def outcome_type(name: str, determinate: Sequence[tuple[str, str]]) -> type[models.TextChoices]:
    """Compose a per-status outcome type from the sentinel table and its own verdicts.

    The only supported way to make one. `LicenseOutcome`, a vulnerability
    outcome, a currency outcome: each is this factory called with the determinate
    members it adds, so all four sentinels arrive by construction and none of
    them can be spelled or valued differently in one type than in another.

    **Every call mints a new, distinct class.** Two calls with identical arguments
    produce two types that are unequal by identity and whose members are unequal
    to each other as enum members -- they compare equal only as strings, because
    `TextChoices` is a `StrEnum`. So a per-status type is bound *once*, at module
    scope in the story that owns it, and imported from there; calling this
    factory at the point of use would make `isinstance` and `is` fail in ways
    that depend on import order. `tests/unit/django_apps/test_outcomes.py` pins
    this rather than leaving it to be discovered.

    Args:
        name: The type's name, used in its `repr` and in refusal messages. Must
            be a valid Python identifier.
        determinate: The determinate members this status adds, as
            `(member name, value)` pairs. At least one; sentinels are supplied by
            the factory and must not appear here.

    Returns:
        A `TextChoices` type carrying the four sentinels followed by the
        determinate members, in that order.

    Raises:
        OutcomeVocabularyError: When `name` or a member name is not an
            identifier; when `determinate` is empty; when a determinate member
            reuses a sentinel's name (which would redefine it) or a sentinel's
            value (which would make the sentinel an alias of a verdict); when two
            determinate members share a name or a value; or when the composed
            type somehow fails `verify_sentinels`.

    """
    members = list(determinate)
    if not name.isidentifier():
        message = (
            f"{name!r} is not a valid identifier and so cannot name an outcome type; "
            f"the enum machinery would raise here with no mention of the vocabulary being declared."
        )
        raise OutcomeVocabularyError(message)
    if not members:
        message = (
            f"{name} declares no determinate members. A type carrying only the four sentinels can record "
            f"that a check did not run and never that it passed, which no policy can use."
        )
        raise OutcomeVocabularyError(message)

    invalid = [member for member, _ in members if not member.isidentifier()]
    if invalid:
        message = f"{name} declares member names that are not identifiers: {invalid}"
        raise OutcomeVocabularyError(message)

    sentinel_names = {sentinel for sentinel, _ in SENTINEL_MEMBERS}
    sentinel_values = {value for _, value in SENTINEL_MEMBERS}
    collisions = [
        f"{member!r} = {value!r}" for member, value in members if member in sentinel_names or value in sentinel_values
    ]
    if collisions:
        message = (
            f"{name} would drop or rename an outcome sentinel: {', '.join(collisions)}. "
            f"The sentinels are supplied by this factory and are not a caller's to redeclare."
        )
        raise OutcomeVocabularyError(message)

    # The same collision rule the sentinels get, applied to the caller's own
    # table. Two verdicts sharing a value are silently aliased by the enum
    # machinery -- the second name becomes the first member -- which is exactly
    # the failure the sentinel check above exists to prevent, and there is no
    # reason it should be caught for four members and not for the rest. Two
    # verdicts sharing a *name* raise a bare `TypeError` from `_EnumDict`, with
    # no mention of the type being built.
    duplicated = sorted(
        {member for member, _ in members if [name for name, _ in members].count(member) > 1}
        | {value for _, value in members if [value for _, value in members].count(value) > 1},
    )
    if duplicated:
        message = f"{name} declares the same member name or value twice: {duplicated}"
        raise OutcomeVocabularyError(message)

    # Python's functional enum API, which is what builds a type from a member
    # table rather than from a class body. django-stubs types `TextChoices` only
    # as it is *called on an instance* -- `TextChoices(value)` and
    # `TextChoices(value, label)` -- and has no overload for the two-argument
    # class-construction form, so the cast names the signature the interpreter
    # actually offers rather than suppressing the complaint with an ignore that
    # would also hide a genuine argument error here.
    build = cast("Callable[[str, Sequence[tuple[str, str]]], type[models.TextChoices]]", models.TextChoices)
    composed = build(name, [*SENTINEL_MEMBERS, *members])
    verify_sentinels(composed)
    return composed


def aggregate(states: Iterable[str]) -> OutcomeState:
    """Reduce several outcome states to the worst of them, by the declared order.

    The only "worst of these" in the product. A rollup, a serializer, an export
    and a generated answer all call this rather than each deciding which of two
    statuses to show, which is the three-incompatible-lattices failure
    `CPM-AD-5` names.

    Values, not identities: a per-status type's `NOT_APPLICABLE` is a different
    enum member from `OutcomeState.NOT_APPLICABLE` and carries the same value, so
    ranking by value is what lets one reducer serve every status in the product.

    Args:
        states: The states to reduce. Members of `OutcomeState`, members of any
            type `outcome_type` composed, or their bare string values.

    Returns:
        The state earliest in `PRECEDENCE` among those given, as an
        `OutcomeState` member. `EMPTY_AGGREGATE` when nothing was given.

    Raises:
        OutcomeVocabularyError: When `states` is a bare string, or when a value
            has no rank -- a per-status determinate verdict, or a string from
            outside the vocabulary entirely. See the module docstring for why an
            unrankable value refuses rather than being treated as determinate.

    """
    if isinstance(states, str):
        # A `str` is iterable, so `aggregate("ok")` would otherwise walk its
        # characters and refuse on `'o'` -- a message pointing at a character
        # rather than at the mistake. The caller meant `aggregate(["ok"])`.
        message = f"aggregate takes an iterable of states, not the single state {states!r}; wrap it in a sequence"
        raise OutcomeVocabularyError(message)

    ranked: list[int] = []
    for state in states:
        value = str(state)
        rank = _RANK.get(value)
        if rank is None:
            message = (
                f"{value!r} has no rank in the outcome precedence order. "
                f"The ranked values are {sorted(_RANK)}; a per-status determinate verdict "
                f"needs its rank decided by the story that introduces it, not inferred here."
            )
            raise OutcomeVocabularyError(message)
        ranked.append(rank)
    if not ranked:
        return EMPTY_AGGREGATE
    return PRECEDENCE[min(ranked)]
