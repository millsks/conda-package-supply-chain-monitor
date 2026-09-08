"""The composed evidence vocabularies, in a leaf module that imports one thing.

`CPM-AD-5` composes every per-status vocabulary in this product from
`core.outcomes.outcome_type`, and these are `CPM-SECURITY-S01`'s,
`CPM-SECURITY-S02`'s, `CPM-SECURITY-S03`'s and `CPM-PY314-S01`'s.
`VulnerabilityOutcome` is the vocabulary `vulnerability_findings.state` is drawn
from, `KevOutcome` is `kev_findings.state`'s, `LicenseOutcome` is
`license_findings.state`'s and `PythonReadinessOutcome` is
`python_readiness_assessments.state`'s, and the whole of why any of them exists
rather than the bare `OutcomeState` is one sentence: **a determinate row here is
never merely "fine"**, and `core`'s single precedence order ranks `ok` best of
five.

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
`collectors/models.py` declares these vocabularies as columns' `choices` and
`collectors/vulnerability.py` and `collectors/kev.py` read their models from
`collectors/models.py`, so a type bound in any of them would close an import cycle
and fail at start-up. `identity/confidence.py` records the same problem and the
same solution: the vocabulary is the half of the pair that depends on nothing, so
the vocabulary is the half that moves. This module imports `core.outcomes` and
nothing else, in either direction.

**All four vocabularies live here rather than one per collector**, which is the
one place this module departs from "a leaf per story". They are the same kind of
thing declared for the same reason, they are read by the same models module, and a
second file would be a second copy of every argument below — while a reader
comparing the determinate values, which is the comparison `CPM-SECURITY-S01`'s
review turned on, would have to open four files to make it.

**Bound once, at module scope, and that is load-bearing.** `outcome_type` mints a
distinct class on every call, so two calls would produce two types whose members
compare unequal as enum members and equal only as strings —
`core/outcomes.py` says so in as many words and
`tests/unit/django_apps/test_outcomes.py` pins it. Everything that needs the type
imports it from here.

**None of them declares a precedence order, and that is a decision rather than an
omission.** `CURRENCY_PRECEDENCE` exists because the currency pass reduces four
surfaces' verdicts to one column, and a reduction needs a ranking. Nothing
reduces vulnerability, KEV or licence findings yet: `CPM-SECURITY-S04`'s rollup
pass is the first consumer of the first two and does not exist, and
`CPM-SECURITY-S05`'s licence policy is the first consumer of the third and does
not exist either. An order declared here would be data no function reads — which
`tests/unit/django_apps/test_single_ordering_audit.py` would have to license by
name, and which the next reader would take for a ranking this product applies
somewhere. Until then `core.outcomes.aggregate` **refuses** `matched`, `listed`,
`not_listed`, `normalized`, `inferred_compatible` and `inferred_incompatible`
outright, which is the safe failure and exactly what that module says it is for: a
caller that reduced these rows without deciding the order is told, loudly, rather
than having `matched` silently ranked beside `ok`.

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

from conda_sentinel.core.outcomes import outcome_type

if TYPE_CHECKING:
    from django.db import models

__all__ = [
    "INFERRED_COMPATIBLE",
    "INFERRED_COMPATIBLE_MEMBER",
    "INFERRED_INCOMPATIBLE",
    "INFERRED_INCOMPATIBLE_MEMBER",
    "KEV_ERROR",
    "KEV_NOT_APPLICABLE",
    "KEV_NOT_FOUND",
    "KEV_UNKNOWN",
    "LICENSE_ERROR",
    "LICENSE_NOT_APPLICABLE",
    "LICENSE_NOT_FOUND",
    "LICENSE_UNKNOWN",
    "LISTED",
    "LISTED_MEMBER",
    "MATCHED",
    "MATCHED_MEMBER",
    "NORMALIZED",
    "NORMALIZED_MEMBER",
    "NOT_LISTED",
    "NOT_LISTED_MEMBER",
    "READINESS_ERROR",
    "READINESS_NOT_APPLICABLE",
    "READINESS_NOT_FOUND",
    "READINESS_UNKNOWN",
    "VULNERABILITY_ERROR",
    "VULNERABILITY_NOT_APPLICABLE",
    "VULNERABILITY_NOT_FOUND",
    "VULNERABILITY_UNKNOWN",
    "KevOutcome",
    "LicenseOutcome",
    "PythonReadinessOutcome",
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


#: The determinate verdict for a row recording that the KEV catalog lists the
#: advisory a vulnerability finding named, declared once as the
#: `(member name, value)` pair `outcome_type` takes.
#:
#: **This is the alarming half of this table and it is deliberately not `ok`.** It
#: is the same correction `CPM-SECURITY-S01` was patched for, made here by
#: construction rather than by review: `CPM-AD-24` carries a state's value verbatim
#: onto every read surface and `core`'s single precedence order ranks `ok` best of
#: five, so a KEV table using `ok` would render exactly the packages with a
#: known-exploited advisory against them as the clean ones — and would rank them
#: above a package nothing was established about. `CPM-UJ-1` opens with a queue led
#: by KEV findings; a value that sorted them last would empty that queue.
#:
#: `listed` rather than `exploited`, `vulnerable` or `kev`, and the difference is
#: what the row can honestly claim. What happened is that a catalog listed an
#: advisory this product had already recorded against this package. Whether the
#: package is *actually* being exploited is a claim about the world that no
#: cross-reference establishes, and a state that said so would be a verdict a
#: collector is not allowed to reach (`CPM-AD-8`); what a KEV hit *means* for a
#: package is `CPM-FR-17`'s rollup, which is `CPM-SECURITY-S04`.
LISTED_MEMBER: Final[tuple[str, str]] = ("LISTED", "listed")

#: The determinate verdict for a row recording that the catalog does **not** list
#: the advisory a vulnerability finding named.
#:
#: **A second determinate member rather than a sentinel, and that is the decision
#: this vocabulary makes that its sibling did not have to.** "We read the catalog
#: and this advisory is not in it" is a negative that was *established* about a
#: specific advisory — which is different from `unknown` (nothing was established)
#: and different again from `not_found`, which on this table means the KEV source
#: reported that the **locator** does not exist. Folding the established negative
#: into either would be `CPM-FR-6`'s fold: three facts, one column, and a reader
#: unable to tell "not in the catalog" from "the catalog is gone".
#:
#: It is emphatically **not** a clean verdict about the package. The advisory is
#: still an advisory; all this row says is that this particular catalog does not
#: list it. The row's `detail` says so in as many words, because the value alone
#: is the one on this table a surface could most plausibly paint green.
NOT_LISTED_MEMBER: Final[tuple[str, str]] = ("NOT_LISTED", "not_listed")

#: The KEV vocabulary: `core`'s four sentinels plus the two determinate verdicts.
KevOutcome: Final[type[models.TextChoices]] = outcome_type(
    "KevOutcome",
    [LISTED_MEMBER, NOT_LISTED_MEMBER],
)

#: `KevOutcome`'s own members, by name, read off the composed type itself for the
#: reason `_MEMBER_VALUES` above is read off its own.
_KEV_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in KevOutcome}

#: The KEV catalog lists the advisory this row's vulnerability finding named. The
#: alarming value, and the one a rollup will care about first.
LISTED: Final[str] = _KEV_MEMBER_VALUES["LISTED"]

#: The KEV catalog was read and does not list that advisory. An established
#: negative about one advisory, and never a statement that the package is clean.
NOT_LISTED: Final[str] = _KEV_MEMBER_VALUES["NOT_LISTED"]

#: The run established nothing about this package's KEV exposure -- which here
#: means it had no current vulnerability finding to cross-reference at all. Never
#: clean (`CPM-FR-6`, `CPM-SM-2`): a package this product has no advisory for has
#: not been shown to be free of known-exploited vulnerabilities.
KEV_UNKNOWN: Final[str] = _KEV_MEMBER_VALUES["UNKNOWN"]

#: Looking failed -- the adapter raised, the allowance was refused, or the catalog
#: document could not be read.
KEV_ERROR: Final[str] = _KEV_MEMBER_VALUES["ERROR"]

#: The KEV source reports that the locator itself does not exist, which is a
#: withdrawn or misconfigured source rather than a package with nothing exploited
#: against it.
KEV_NOT_FOUND: Final[str] = _KEV_MEMBER_VALUES["NOT_FOUND"]

#: `core`'s "the question was never ours to ask", kept in the vocabulary by
#: construction and produced by nothing, on the terms
#: `VULNERABILITY_NOT_APPLICABLE` states: a KEV question applies to every package
#: that could have an advisory against it, which is every package.
KEV_NOT_APPLICABLE: Final[str] = _KEV_MEMBER_VALUES["NOT_APPLICABLE"]


#: The determinate verdict for a row recording a licence this collector
#: recognised and normalized, declared once as the `(member name, value)` pair
#: `outcome_type` takes.
#:
#: **`normalized`, and emphatically not `ok`.** On a licence table `ok` reads as
#: "this licence is fine", which is a compliance verdict `CPM-SECURITY-S03`'s AC 2
#: forbids this collector from making in as many words and which `CPM-FR-18` gives
#: to a policy that does not exist yet (`CPM-SECURITY-S05`). `CPM-AD-24` carries a
#: state's value verbatim onto every read surface and `core`'s single precedence
#: order ranks `ok` best of five, so a licence table using it would render every
#: recognised licence — a copyleft one, a commercial one, one an organisation has
#: never approved — as the clean ones, and rank them above the rows a reviewer
#: actually has to look at. The two sibling vocabularies above were corrected on
#: exactly this point; here it is made by construction.
#:
#: `normalized` rather than `recognised`, `permitted` or `compliant`, and the
#: difference is what the row can honestly claim. What happened is that the raw
#: string a channel stated was recognised and rewritten as an SPDX expression, with
#: the method that did it recorded beside both. Whether that licence is *allowed*
#: is somebody else's judgement over a rule set that is versioned data
#: (`CPM-AD-8`, `CPM-FR-18`), and a state that said so would be a verdict a
#: collector is not allowed to reach.
NORMALIZED_MEMBER: Final[tuple[str, str]] = ("NORMALIZED", "normalized")

#: The licence vocabulary: `core`'s four sentinels plus `normalized`.
#:
#: **One determinate member rather than several.** A determinate row here says one
#: thing -- the stated licence was recognised and normalized -- and every other
#: fact about it is a column of its own: the raw string, the SPDX expression and
#: the method. Folding "which licence" or "how permissive" into the state would be
#: the compliance verdict this vocabulary exists to keep out of the one column a
#: policy pass reads first.
LicenseOutcome: Final[type[models.TextChoices]] = outcome_type(
    "LicenseOutcome",
    [NORMALIZED_MEMBER],
)

#: `LicenseOutcome`'s own members, by name, read off the composed type itself for
#: the reason `_MEMBER_VALUES` above is read off its own.
_LICENSE_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in LicenseOutcome}

#: The channel stated a licence this collector recognised, and the row carries the
#: SPDX expression and the detection method beside the raw string. The only
#: determinate value, and never a statement that the licence is acceptable.
NORMALIZED: Final[str] = _LICENSE_MEMBER_VALUES["NORMALIZED"]

#: The run established no normalized licence -- the channel stated nothing, or it
#: stated something this collector will not normalize without guessing. Never
#: permissive and never clean (`CPM-FR-6`, `CPM-SM-2`, and `CPM-SECURITY-S03`'s
#: AC 2 in as many words): the raw string is preserved on the row so a reviewer has
#: something to act on, and `detail` says which of the two it is.
LICENSE_UNKNOWN: Final[str] = _LICENSE_MEMBER_VALUES["UNKNOWN"]

#: Looking failed -- the channel raised, the allowance was refused, or the
#: document could not be read.
LICENSE_ERROR: Final[str] = _LICENSE_MEMBER_VALUES["ERROR"]

#: The channel reports that it does not serve this package at all, which is an
#: absence from that channel rather than a package with no licence.
LICENSE_NOT_FOUND: Final[str] = _LICENSE_MEMBER_VALUES["NOT_FOUND"]

#: `core`'s "the question was never ours to ask", kept in the vocabulary by
#: construction and produced by nothing, on the terms the two above state: every
#: package a monitored channel could serve is licensed under something, so
#: `LicenseCollector.inapplicability` never answers a reason and `license_findings`
#: refuses a row carrying this value outright.
LICENSE_NOT_APPLICABLE: Final[str] = _LICENSE_MEMBER_VALUES["NOT_APPLICABLE"]


#: The determinate verdict for a row recording that the package's *declared*
#: metadata admits the target Python, declared once as the `(member name, value)`
#: pair `outcome_type` takes.
#:
#: **`inferred_compatible`, and neither `ok` nor a bare `compatible`.** Two
#: separate rules land on this one value and both of them forbid the shorter
#: spellings.
#:
#: `ok` is the correction `CPM-SECURITY-S01` was patched for and every composed
#: vocabulary above applies by construction: `CPM-AD-24` carries a state's value
#: verbatim onto every read surface and `core`'s single precedence order ranks
#: `ok` best of five, so a readiness table using it would rank a *metadata claim*
#: above every row a reader actually has to look at.
#:
#: A bare `compatible` is the failure this story's own epic exists to prevent.
#: `CPM-FR-14` requires inferred compatibility and *verified* compatibility to be
#: **distinct recorded states**, and `CPM-PY314-S02` writes the verified one. A
#: value called `compatible` on this table would appear on a queue beside a
#: verified result and read identically -- the whole of what "kept apart" means,
#: undone in the one column a policy pass reads first. Naming the inference in the
#: value is what makes the distinction survive the projection.
#:
#: What the row can honestly claim is exactly that: a specifier or a classifier the
#: project published admits the target Python. No build ran, nothing was imported
#: and no subprocess was started (`CPM-PY314-S02` owns all three), so the value
#: says *inferred* and the row's `deciding_signal` says which piece of metadata
#: said so.
INFERRED_COMPATIBLE_MEMBER: Final[tuple[str, str]] = ("INFERRED_COMPATIBLE", "inferred_compatible")

#: The determinate verdict for a row recording that the package's declared
#: metadata **cannot** admit the target Python.
#:
#: **A second determinate member rather than a sentinel**, on the terms
#: `NOT_LISTED_MEMBER` states: "we read the specifier and it excludes this Python"
#: is a negative that was *established* from a claim the project published, which
#: is different from `unknown` (the project claimed nothing either way) and
#: different again from `not_found` (the release ecosystem does not know the
#: package). Folding the established negative into either would be `CPM-FR-6`'s
#: fold, and it would be the expensive direction of it: `CPM-PY314-S02` spends
#: verification where this table says it is worth spending, and a column that
#: could not tell "declared it will not run" from "declared nothing" would send
#: that spend exactly where it is least warranted.
#:
#: `inferred_incompatible` rather than `incompatible`, for the reason its
#: counterpart is not `compatible`: the row records what a specifier *claims*
#: rather than what a build *did*, and a project whose specifier excludes 3.14
#: today may well build under it.
INFERRED_INCOMPATIBLE_MEMBER: Final[tuple[str, str]] = ("INFERRED_INCOMPATIBLE", "inferred_incompatible")

#: The static-readiness vocabulary: `core`'s four sentinels plus the two inferred
#: verdicts.
#:
#: **Two determinate members and not three.** "The metadata says nothing either
#: way" is emphatically *not* a third determinate value: it is `unknown`, the
#: sentinel `core` already has for "nothing was established", and it is the single
#: property `CPM-PY314-S01` turns on. Most projects have not declared 3.14 support,
#: so a vocabulary that had a determinate member for silence -- however carefully
#: named -- would put most of the inventory into a *claim* nobody made.
PythonReadinessOutcome: Final[type[models.TextChoices]] = outcome_type(
    "PythonReadinessOutcome",
    [INFERRED_COMPATIBLE_MEMBER, INFERRED_INCOMPATIBLE_MEMBER],
)

#: `PythonReadinessOutcome`'s own members, by name, read off the composed type
#: itself for the reason `_MEMBER_VALUES` above is read off its own.
_READINESS_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in PythonReadinessOutcome}

#: The project's declared metadata admits the target Python. An inference from a
#: claim somebody else published, and never a build that ran.
INFERRED_COMPATIBLE: Final[str] = _READINESS_MEMBER_VALUES["INFERRED_COMPATIBLE"]

#: The project's declared metadata cannot admit the target Python. An inference
#: from a claim somebody else published, and never a build that failed.
INFERRED_INCOMPATIBLE: Final[str] = _READINESS_MEMBER_VALUES["INFERRED_INCOMPATIBLE"]

#: The run established nothing about this package's readiness -- and this is the
#: value most of a real inventory carries, on purpose.
#:
#: Five things reach it and `detail` says which: the project declared neither a
#: `Requires-Python` specifier nor a version classifier; it enumerated Python
#: versions in its classifiers without naming the series being assessed; its two
#: static signals disagree; it declared a specifier in a shape this product will not
#: read as a containment question; or it declared one wider than the column that
#: records it, which the row says while carrying no specifier. **None of them is a
#: claim of incompatibility**, and reading the first as one is the defect
#: `CPM-PY314-S01` exists to prevent.
#:
#: **A package this product's own identity has not resolved is deliberately not on
#: that list**, because no row is written for it at all: the selection does not offer
#: such a package and a forced recollection is refused before any evidence is
#: written. Every read surface reports it `unknown` for want of an observation
#: (`core/freshness.py`'s `UNOBSERVED_STATUS`) rather than from a row on this table.
#: `CPM-PY314-S01`'s Spec Change Log records why the row the matrix asked for is not
#: expressible against the shipped base.
READINESS_UNKNOWN: Final[str] = _READINESS_MEMBER_VALUES["UNKNOWN"]

#: Looking failed -- the source raised, the allowance was refused, or the document
#: could not be read.
READINESS_ERROR: Final[str] = _READINESS_MEMBER_VALUES["ERROR"]

#: The release ecosystem reports that it does not know this package at all, which
#: is an absence from the index rather than a project that declared nothing.
READINESS_NOT_FOUND: Final[str] = _READINESS_MEMBER_VALUES["NOT_FOUND"]

#: `core`'s "the question was never ours to ask", and the one composed vocabulary
#: in this module whose table really does hold it.
#:
#: `CPM-PY314-S01` AC 2 asks for it in as many words, and there is exactly one path
#: to it: `identity` recorded this package's release-ecosystem mapping as
#: `not_applicable`, which is resolution saying the package has no release
#: ecosystem a Python question could be asked of. A mapping that is `unknown`,
#: `error` or `not_found` establishes **nothing** and never reaches this value --
#: reading an unresolved identity as an inapplicable question is the absence trap
#: the preceding epic met in every story.
READINESS_NOT_APPLICABLE: Final[str] = _READINESS_MEMBER_VALUES["NOT_APPLICABLE"]
