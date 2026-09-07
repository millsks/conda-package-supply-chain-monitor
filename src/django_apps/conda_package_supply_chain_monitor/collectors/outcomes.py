"""The vulnerability evidence vocabulary, in a leaf module that imports one thing.

`CPM-AD-5` composes every per-status vocabulary in this product from
`core.outcomes.outcome_type`, and this is `CPM-SECURITY-S01`'s.
`VulnerabilityOutcome` is the vocabulary `vulnerability_findings.state` is drawn
from, and the whole of why it exists rather than the bare `OutcomeState` is one
sentence: **on this table a determinate row means an advisory matched**, and
`core`'s single precedence order ranks `ok` best of five.

**What using `ok` here would have done.** `CPM-AD-24` makes every derived status
carry its value verbatim onto every read surface, so the first view over this
table would have rendered exactly the packages that *have* advisories against
them as the clean ones — and `core.outcomes.aggregate` would have ranked a
matched advisory above a package nothing matched, in any rollup that ever reduced
them. `CPM-AD-5` anticipates this in as many words: `ok` is "the generic
determinate value, the one a per-status type refines into verdicts of its own",
and refining it is not optional for a domain where determinate means *bad*.

**Refining `ok` into one verdict rather than several.** A determinate row here is
one advisory matched against one version, and there is exactly one thing to say
about it: it matched. How severe it is, how surely it matched and whether a fix
exists are separate columns the source states and this product ranks nowhere
(`CPM-AD-8`); folding any of them into the state would be the severity ranking
`CPM-SECURITY-S01`'s Never list forbids, done in the one column a policy pass
reads first.

**A leaf module, for the reason `policies/outcomes.py` is one.**
`collectors/models.py` declares this vocabulary as a column's `choices` and
`collectors/vulnerability.py` reads `VulnerabilityFinding` from
`collectors/models.py`, so a type bound in either would close an import cycle and
fail at start-up. `identity/confidence.py` records the same problem and the same
solution: the vocabulary is the half of the pair that depends on nothing, so the
vocabulary is the half that moves. This module imports `core.outcomes` and
nothing else, in either direction.

**Bound once, at module scope, and that is load-bearing.** `outcome_type` mints a
distinct class on every call, so two calls would produce two types whose members
compare unequal as enum members and equal only as strings —
`core/outcomes.py` says so in as many words and
`tests/unit/django_apps/test_outcomes.py` pins it. Everything that needs the type
imports it from here.

**It declares no precedence order, and that is a decision rather than an
omission.** `CURRENCY_PRECEDENCE` exists because the currency pass reduces four
surfaces' verdicts to one column, and a reduction needs a ranking. Nothing
reduces vulnerability findings yet: `CPM-SECURITY-S04`'s rollup pass is the first
consumer of this table and does not exist. An order declared here would be data
no function reads — which `tests/unit/django_apps/test_single_ordering_audit.py`
would have to license by name, and which the next reader would take for a ranking
this product applies somewhere. Until then `core.outcomes.aggregate` **refuses**
`matched` outright, which is the safe failure and exactly what that module says it
is for: a caller that reduced these rows without deciding the order is told,
loudly, rather than having `matched` silently ranked beside `ok`.

**Why this module names no `OutcomeState` member.** The four sentinels are read
back off the composed type rather than written out, so nothing here is a literal
holding two or more `OutcomeState` members — which is the shape
`tests/unit/django_apps/test_single_ordering_audit.py` reads as a second
precedence order, and it is right to. There is no order in this file to hide.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from conda_package_supply_chain_monitor.core.outcomes import outcome_type

if TYPE_CHECKING:
    from django.db import models

__all__ = [
    "MATCHED",
    "MATCHED_MEMBER",
    "VULNERABILITY_ERROR",
    "VULNERABILITY_NOT_APPLICABLE",
    "VULNERABILITY_NOT_FOUND",
    "VULNERABILITY_UNKNOWN",
    "VulnerabilityOutcome",
]

#: The determinate verdict for a row recording one advisory that matched,
#: declared once as the `(member name, value)` pair `outcome_type` takes.
#:
#: A pair rather than a member reference, on the terms `policies/outcomes.py`'s
#: `CURRENT_MEMBER` is one: the composed type below is built from it and `MATCHED`
#: is read back out of it, so a second spelling of `"matched"` anywhere would be a
#: value that could drift from the one the column actually offers.
#:
#: `matched` rather than `affected` or `vulnerable`, and the difference is what
#: the row can honestly claim. What happened is that an advisory source matched an
#: advisory to this package at this version, with a stated match confidence;
#: whether the package is *actually* exploitable is `CPM-FR-41`'s remediation
#: readiness (`CPM-SECURITY-S06`), and a state that said so would be a verdict a
#: collector is not allowed to reach (`CPM-AD-8`).
MATCHED_MEMBER: Final[tuple[str, str]] = ("MATCHED", "matched")

#: The vulnerability vocabulary: `core`'s four sentinels plus `matched`.
VulnerabilityOutcome: Final[type[models.TextChoices]] = outcome_type(
    "VulnerabilityOutcome",
    [MATCHED_MEMBER],
)

#: `VulnerabilityOutcome`'s own members, by name, read off the composed type
#: itself, for the reason `policies/outcomes.py`'s `_MEMBER_VALUES` is: the
#: functional enum API makes the members invisible to a type checker, and reaching
#: them *through* the type is what makes a drifted sentinel fail at import rather
#: than silently make every comparison false. A comprehension rather than a
#: literal, which is also what keeps it out of
#: `tests/unit/django_apps/test_single_ordering_audit.py`'s reach: it is a lookup
#: table with no order in it.
_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in VulnerabilityOutcome}

#: An advisory source matched one advisory to this package at the version this run
#: asked about. The only determinate value, and the only one that is *adverse*.
MATCHED: Final[str] = _MEMBER_VALUES["MATCHED"]

#: The run established nothing about this package's exposure -- the source was
#: read and matched nothing, the source could not identify the package, or this
#: package's identity names no version to match against. Never clean
#: (`CPM-SM-2`).
#:
#: Reached through `VulnerabilityOutcome` rather than through `OutcomeState`,
#: because a column's values must be its own choices and reaching across to
#: another class for them is the one place this module would take a value from a
#: type the field does not declare.
VULNERABILITY_UNKNOWN: Final[str] = _MEMBER_VALUES["UNKNOWN"]

#: Looking failed -- the adapter raised, the allowance was refused, or the
#: document could not be read.
VULNERABILITY_ERROR: Final[str] = _MEMBER_VALUES["ERROR"]

#: The advisory source reports that the locator itself does not exist, which is a
#: withdrawn or misconfigured source rather than a package with no advisories.
VULNERABILITY_NOT_FOUND: Final[str] = _MEMBER_VALUES["NOT_FOUND"]

#: `core`'s "the question was never ours to ask", kept in the vocabulary by
#: construction and produced by nothing: an advisory question applies to every
#: package, `VulnerabilityCollector.inapplicability` never answers a reason, and
#: `vulnerability_findings` refuses a row carrying this value outright. Named so
#: the constraint and the collector's refusal can both spell it once.
VULNERABILITY_NOT_APPLICABLE: Final[str] = _MEMBER_VALUES["NOT_APPLICABLE"]
