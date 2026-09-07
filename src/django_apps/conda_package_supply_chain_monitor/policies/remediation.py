"""`CPM-FR-41`: whether a finding can actually be acted on, and where the fix is.

The fifth policy pass. It reads five evidence tables as of the run's stated
cut-off -- `vulnerability_findings` for the fixed version an advisory names, and
the four currency-surface tables for where that version has appeared -- derives a
readiness state plus the surfaces the fix was found on, and writes its own derived
row. It writes no evidence, makes no outbound call, and never writes the rollup.

**The single property this whole pass turns on: `blocked` is never reached by an
absence.** `blocked` means the fixed version was looked for on *every* surface and
found on none. A surface that was not read is not a surface where the fix is
absent, and collapsing those two is what would tell a security reviewer to give up
on a package whose fix is sitting on a surface nobody checked.
`policies/outcomes.py`'s `FixAvailability` is where the distinction lives -- three
values, `published`, `not_published` and `not_read`, and the third is the whole
reason the type exists -- `finding_readiness` below reaches `blocked` only from
four `not_published` readings, and `policies/models.py` puts two database check
constraints behind it, so a row claiming `blocked` while naming a surface this run
did not read is refused by PostgreSQL rather than merely avoided here.

**`blocked` is, today, unreachable -- and that is this pass's recorded state
rather than a defect to work round.** Applying the property above honestly leaves
no evidence this product records that can establish the absence `blocked` asserts.
`not_published` is the only reading that may vote towards it, and a reading may be
`not_published` only where a surface *established* that the fix is not there. The
four surface tables store the version each surface states as its **latest** (see
`collectors/models.py`), not the set of versions it carries, so a surface stating
`1.2.4` against a fix of `1.2.3` has established nothing in either direction:
PyPI still hosts `1.5` when its latest is `2.0`. Equality can establish "this
surface states the fix"; its negation establishes nothing, and recording the
negation as `not_published` would make every package whose advisory named a fix
the surfaces have since moved past decay into `blocked` as a matter of course.
`surface_availability` therefore reads a non-equal statement as `not_read` and
`EQUALITY_ONLY_DETAIL` names the versions on the row.

Two things would make `blocked` reachable, and neither is this story's:

* a **version-ordering rule** -- given a fix and a version a surface states,
  decide whether the surface is at or past it. No architecture decision owns this
  yet. `CPM-AD-6` is *version authority is explicit per package*: it owns which
  surface is authoritative, not how two version strings compare, and an earlier
  draft of this module cited it wrongly throughout.
* a **collector change** that records "the source stated there is no fix"
  distinctly from "the field was absent". Today `collectors/vulnerability.py`
  writes one clause per field the source left *blank*, and `collectors/models.py`
  is explicit that blank means missing and is never inferred, so the two cannot
  be told apart from a row.

The vocabulary, the reduction and the two check constraints keep `blocked` even
so: the epic's AC 2 requires the value to exist and be distinct from `ready` and
`unknown`, and the day either gap above closes, the value and the rules that
guard it are already in place. `policies/data/README.md` and `docs/deployment.md`
say the same where an operator would look.

It is `policies/licence.py`'s central property turned round. There, `allowed` must
never be reached by an absence because it looks like good news; here, `blocked`
must never be reached by one because it tells a reviewer to stop looking. A false
`allowed` ships a forbidden licence; a false `blocked` abandons a package whose fix
is already published. Both are absences masquerading as conclusions.

**It reads evidence tables and never another pass's derived table.** All four
shipped passes import only their own model and that is the precedent, and here it
is load-bearing twice: a readiness derived from `PackageCurrency` would depend on
*two* policy versions at once, so `CPM-FR-22`'s replay could be stated for neither;
and `PackageCurrency` answers "is this surface current against the authority",
which is a different question from "does this surface carry version X". Nothing
here reads `PackageCurrency`, `PackageFeedstockPresence`, `PackageVulnerability` or
`PackageLicense`, and nothing here re-derives a currency verdict, a vulnerability
status or a licence outcome. This pass answers one question and takes the others as
given.

**The comparison is equality on `comparable_version`, and that is a decision with
a stated limit this story is explicitly forbidden from lifting.**
`policies/currency.py` owns the one version comparison this product has decided --
whitespace, and a single leading `v` or `V` before a digit -- and this module
*imports* it rather than spelling a second one, so the two can never drift. What
equality can establish is one thing only: that a surface states the fixed version.
Its negation establishes nothing. `numpy 1.2.4` on a channel against a fix
published in `1.2.3` is not a channel where the fix is absent -- it is a channel
whose *latest* is a version this product cannot order against the fix -- so it
reads `not_read`, and `EQUALITY_ONLY_DETAIL` names the versions on the row so the
reviewer can see what was compared. Closing that gap needs a version-ordering
rule, which no architecture decision owns yet.

**A fixed range that is not a bare version is `unknown`, with the reason, and the
run does not fail.** `collectors/vulnerability.py` stores `fixed_range` as "the
expression the source wrote in its own ecosystem's grammar", so `>=1.2.3`,
`<2.0.0`, `1.0,<2.0` and `[1.2.3,)` are all reachable values. None of them can be
compared against a surface's single stated version without inventing ordering
semantics, so none of them is: the finding reads `unknown` and the row names the
expression and says why. This is the story's `Block If`, taken rather than worked
round.

**A finding with no fixed range is `unknown`, and there is no second case.** An
earlier draft of this module read the advisory collector's `NO_FIXED_RANGE_DETAIL`
clause as "the source was asked and answered that there is no fix", and made that
`blocked` without reading a surface. The clause does not say that.
`collectors/vulnerability.py` builds one clause per field the source left
**blank**, and `collectors/models.py` and the PRD are explicit that blank means
*missing* and is never inferred -- so the clause is present on exactly the rows
whose `fixed_range` is empty, which is the condition it was being read as
refining. Reading it that way made `unknown` unreachable from any row a real
collector writes and turned every matched advisory whose feed omitted a fixed
range into `blocked` with four unread surfaces. So a blank fixed range is
`UNRECORDED` and `unknown`, full stop, and this pass depends on no advisory prose
except the one seam below.

**The one collector-prose seam is the sentinel that means "read and matched
nothing".** `collectors/vulnerability.py` writes three different `unknown` rows:
the source was read and matched nothing, the source cannot identify the package,
and this package's identity names no version to match against. Only the first
establishes that there is nothing to remediate. `policies/vulnerability.py`
already draws that line with a prefix test against `NOTHING_MATCHED_DETAIL`, and
this module imports the same constant and tests it the same way, so the two passes
cannot disagree about the same rows in the same run. A collector that reworded the
sentence without moving the constant would turn `not_applicable` into `unknown`,
which is the safe direction.

**Staleness is `CPM-FR-38`'s answer, consumed rather than restated, and it is
asked of the advisory evidence too.** `core/freshness.py` already decides whether
an observation has aged past its collector's declared target, and this module asks
it: `evidence_is_stale` calls `freshness_of` and reads the verdict. A surface
whose evidence is stale reads `not_read` -- so it can neither assert that a fix is
available (AC 3) nor vote towards `blocked`. **The advisory sweep's own freshness
is measured on the same terms**: `CPM-UJ-1`'s stated edge case is that a finding
older than its freshness target shows as stale rather than actionable, and a
month-old advisory sweep beside a fresh channel would otherwise read `ready` with
`evidence_stale` false. Where the advisory sweep is stale this run does not know
what to look for, so the readiness is `unknown`, no surface is asked, and the row
says so. `evidence_stale` is true where the advisory sweep or any surface this run
read was past its target, and the `detail` says which. `latest_observation` is
deliberately *not* used: it answers about the newest observation full stop, where
every read here is bound to the run's cut-off, and a staleness verdict measured
off a row the cut-off excludes would not replay.

**The evidence read is the newest *sweep*, not the newest row, on all five
tables.** `vulnerability_findings` holds one row per matched advisory and
`conda_package_snapshots` holds one per `(channel, platform)` pair; the other three
hold one row per package per sweep, and reading them the same way costs nothing.
The published-package table is where it matters most and is where this pass
deliberately departs from `policies/currency.py`, which takes a single row chosen
by an alphabetical tie-break: a package the fix is published for on the
second-sorting channel would read `not_published` there and could then be reduced
to `blocked`, which is a channel list deciding that a reviewer should give up. So
the whole sweep is read and the surface reads `published` if **any** row of it
carries the fixed version. That is `CPM-SECURITY-S05`'s review lesson applied
before the fact: read the collector's actual row-writing behaviour, not the shape
this module's own tests construct.

**A package is only as actionable as its worst finding.** Two matched advisories,
one fixed everywhere and one nowhere, is one row taking the least ready of the two
-- `READINESS_PRECEDENCE` ranks them and `worst_readiness` applies it. The row's
four per-surface columns and its `fixed_version` are about the *supporting*
finding and no other, because two findings naming two fixed versions have two
different sets of surface answers and a row that mixed them would say nothing true.
The `detail` says when there were several.

**No policy parameter, and that is a decision rather than an omission.** The other
three parameterised passes read a threshold, a severity order or a rule set from
`policies/data/policy-parameters.toml`. This pass has nothing of that kind to read:
the comparison is `policies/currency.py`'s and is not a reviewer's to tune, the
freshness targets are the collectors' own declarations (`CPM-AD-28`), and the
readiness vocabulary is fixed by `CPM-AD-5`. Inventing a parameter so this pass
looked like its siblings would put a knob in a reviewed file that nothing reads.
The row still records `policy_version`, because what a row means is fixed by the
version it was computed under whether or not that version carries a key for this
domain. `policies/data/README.md` says so where a reviewer would look.

**Nothing here reads the current time.** Every instant is the run's: the cut-off
arrives as an argument (`CPM-AD-21`), it is what staleness is measured from, and
the row records it. That is what makes `CPM-FR-22`'s replay reproduce identical
rows.

**A pass that cannot compute records rather than refusing.** `core/policy_run.py`
wraps every pass for one package in one `transaction.atomic()` -- `CPM-AD-23`'s
atomic unit is one package and not one pass -- so a refusal here rolls back that
package's currency, feedstock, vulnerability and licence rows as well as its own,
`compose_rollup` skips it, and a condition holding for every package finalizes the
run `failed`. Four documents in `CPM-SECURITY-S04` asserted the opposite and were
wrong in all of them. So exactly one evidence fault raises: an advisory finding
carrying a state outside `VulnerabilityOutcome`, because a readiness derived from a
value nothing recognises is the one thing that must not reach the column that tells
a reviewer whether to stop looking, and one corrupt evidence row is genuinely one
package's problem. Everything else is recorded on the row: an uncomparable fixed
range, a finding with no fix, a surface nobody read, a stale surface, and a
collector that declares no freshness target. (Two guards against a caller doing
something impossible through the orchestration also raise -- a naive cut-off and an
unrecognised surface reading -- and neither is reachable from a policy run.)

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

from conda_package_supply_chain_monitor.collectors.models import CondaPackageSnapshot
from conda_package_supply_chain_monitor.collectors.models import FeedstockSnapshot
from conda_package_supply_chain_monitor.collectors.models import PyPIReleaseSnapshot
from conda_package_supply_chain_monitor.collectors.models import SourceReleaseSnapshot
from conda_package_supply_chain_monitor.collectors.models import VulnerabilityFinding
from conda_package_supply_chain_monitor.collectors.outcomes import MATCHED
from conda_package_supply_chain_monitor.collectors.outcomes import VULNERABILITY_NOT_APPLICABLE
from conda_package_supply_chain_monitor.collectors.outcomes import VULNERABILITY_UNKNOWN
from conda_package_supply_chain_monitor.collectors.outcomes import VulnerabilityOutcome
from conda_package_supply_chain_monitor.collectors.vulnerability import NOTHING_MATCHED_DETAIL
from conda_package_supply_chain_monitor.core.clock import is_aware
from conda_package_supply_chain_monitor.core.freshness import freshness_of
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.policy import PolicyPass
from conda_package_supply_chain_monitor.core.registry import registered_collectors
from conda_package_supply_chain_monitor.identity.models import VersionSurface
from conda_package_supply_chain_monitor.policies.currency import SnapshotModel
from conda_package_supply_chain_monitor.policies.currency import comparable_version
from conda_package_supply_chain_monitor.policies.models import PackageRemediation
from conda_package_supply_chain_monitor.policies.outcomes import AWAITING_BUILD
from conda_package_supply_chain_monitor.policies.outcomes import AWAITING_PACKAGING
from conda_package_supply_chain_monitor.policies.outcomes import BLOCKED
from conda_package_supply_chain_monitor.policies.outcomes import FIX_NOT_PUBLISHED
from conda_package_supply_chain_monitor.policies.outcomes import FIX_PUBLISHED
from conda_package_supply_chain_monitor.policies.outcomes import READINESS_NOT_APPLICABLE
from conda_package_supply_chain_monitor.policies.outcomes import READINESS_UNKNOWN
from conda_package_supply_chain_monitor.policies.outcomes import READY
from conda_package_supply_chain_monitor.policies.outcomes import SURFACE_NOT_READ
from conda_package_supply_chain_monitor.policies.outcomes import worst_readiness

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence
    from datetime import datetime
    from datetime import timedelta

    from django.db import models

    from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
    from conda_package_supply_chain_monitor.core.models import PolicyRun
    from conda_package_supply_chain_monitor.identity.models import Package

__all__ = [
    "ADVISORY_VOCABULARY",
    "EQUALITY_ONLY_DETAIL",
    "NOT_COMPARABLE",
    "NO_ADVISORY_EVIDENCE_DETAIL",
    "NO_ADVISORY_FRESHNESS_TARGET_DETAIL",
    "NO_FIX_RECORDED_DETAIL",
    "NO_FRESHNESS_TARGET_DETAIL",
    "NO_MATCHED_ADVISORY_DETAIL",
    "ORDERING_MARKERS",
    "POLICY_NAME",
    "READINESS_BY_SURFACE",
    "READ_ORDERING",
    "RECORDED",
    "SEVERAL_FINDINGS_DETAIL",
    "STALE_ADVISORY_DETAIL",
    "STALE_SURFACES_DETAIL",
    "SURFACE_READERS",
    "UNCOMPARABLE_FIX_DETAIL",
    "UNESTABLISHED_ADVISORY_EVIDENCE_DETAIL",
    "UNREAD_SURFACES_DETAIL",
    "UNRECORDED",
    "WITHIN_A_SWEEP",
    "AdvisoryReading",
    "RemediationPass",
    "RemediationPolicyError",
    "SurfaceReader",
    "SurfaceReading",
    "advisory_reading",
    "current_findings",
    "evidence_is_stale",
    "finding_readiness",
    "fixed_version",
    "freshness_target",
    "matched_findings",
    "read_surface",
    "remediation_detail",
    "stated_versions",
    "supporting_finding",
    "surface_availability",
    "unestablished_findings",
    "unordered_statements",
]

#: What this pass is called. It keys `core/policy.py`'s registry, keys the
#: rollup's per-domain `policy_versions` map (`CPM-AD-11`) and appears in every
#: refusal about this pass, so it is spelled once and imported.
#:
#: `remediation` rather than `remediation-readiness`, on the terms
#: `policies/vulnerability.py` argues its own plain name: there is no second
#: remediation pass coming, and nothing else in either registry claims the string.
POLICY_NAME: Final[str] = "remediation"

#: The ordering that decides which sweep a cut-off-bound read returns.
#:
#: Declared rather than spelled inside the query, on the terms
#: `policies/licence.py`'s `READ_ORDERING` is: this is now the seventh
#: hand-written copy of `collectors/models.py`'s `snapshot_as_of` rule in this
#: repository, and what the copies are not left to do is drift.
READ_ORDERING: Final[tuple[str, ...]] = ("-observed_at", "-pk")

#: The order rows within one sweep are read in, so the row a verdict names is the
#: same on every replay. Ascending primary key: arbitrary, and chosen only because
#: it is *fixed*.
WITHIN_A_SWEEP: Final[str] = "pk"

#: Every value a `vulnerability_findings` row's state may hold, as strings.
#:
#: Read off the composed vocabulary rather than listed, on the terms
#: `policies/licence.py`'s `LICENSE_VOCABULARY` is derived: listing them would be
#: a second spelling of values `outcome_type` has already fixed once, and a
#: module-scope literal holding several `OutcomeState` members is
#: indistinguishable from a precedence order to
#: `tests/unit/django_apps/test_single_ordering_audit.py`. A comprehension is
#: neither.
ADVISORY_VOCABULARY: Final[frozenset[str]] = frozenset(VulnerabilityOutcome.values)

#: The name this module gives the advisory evidence table where a freshness line
#: has to say which evidence it is about.
#:
#: Not a `VersionSurface` value and deliberately not spelled like one: the four
#: surfaces answer "where has this version appeared" and this table answers "what
#: is there to remediate", and a reader of the row should not have to work out
#: that a fifth "surface" appeared in the list.
ADVISORY_EVIDENCE: Final[str] = "advisory findings"

#: What `fixed_version` reports when the finding names a fix this pass can compare.
RECORDED: Final[str] = "recorded"

#: What it reports when the finding carries no fixed range at all. `unknown`.
#:
#: **There is deliberately no second case beside this one.** An earlier draft
#: carried an `established_absent` reading, selected by the presence of the
#: advisory collector's `NO_FIXED_RANGE_DETAIL` clause and reaching `blocked`
#: without asking a surface. The clause does not distinguish anything: the
#: collector writes one clause per field the source left blank, so it is present
#: on precisely the rows this branch already covers. See the module docstring.
UNRECORDED: Final[str] = "unrecorded"

#: What it reports when the recorded fixed range cannot be compared without
#: version-ordering semantics this product has not decided. `unknown`, naming the
#: expression. This is the story's `Block If`.
NOT_COMPARABLE: Final[str] = "not_comparable"

#: Every character that makes a recorded fixed range something other than a single
#: version this pass can compare for equality.
#:
#: Comparison operators, the boundary markers of an interval, the separators of a
#: conjunction or a disjunction of constraints, and a wildcard. Any of them means
#: the expression states a *set* of versions rather than one, and deciding whether
#: a surface's single stated version falls inside that set is exactly the ordering
#: rule this story is forbidden from inventing, and which no architecture decision
#: owns.
#:
#: A denylist rather than an allowlist of version grammar, deliberately: an
#: allowlist would be this module deciding what a legal version looks like across
#: four ecosystems, which is the same invention by a longer route. What this set
#: says is narrower and defensible -- these characters mean "not one version" in
#: every ecosystem's grammar -- and anything it does not catch still has to survive
#: `comparable_version` and then equal a version some surface actually stored, so
#: the failure direction is a surface reading `not_published`, never a false
#: `published`.
ORDERING_MARKERS: Final[frozenset[str]] = frozenset("<>=!~^*,|&[](){} \t")

#: Which surface reaches which readiness when it carries the fix, best first.
#:
#: **A consultation order and emphatically not a ranking of `FixAvailability`
#: values.** The three values are not ranked against each other anywhere; what is
#: ordered here is the four *surfaces*, because a reviewer's next action differs by
#: surface and the best available action is the one the row should report. A
#: channel that publishes the fix means install it now; a recipe that carries it
#: means a build is due; an upstream or PyPI release means the recipe has to be
#: updated first. It holds `VersionSurface` and `RemediationReadiness` values and
#: no `OutcomeState` members, so it is not the shape
#: `tests/unit/django_apps/test_single_ordering_audit.py` reads.
#:
#: Upstream precedes PyPI and the two reach the same verdict, so the order between
#: them decides nothing about the readiness -- only which surface a reader looks at
#: first, and both columns are on the row either way.
READINESS_BY_SURFACE: Final[tuple[tuple[str, str], ...]] = (
    (VersionSurface.CONDA_PACKAGE.value, READY),
    (VersionSurface.FEEDSTOCK.value, AWAITING_BUILD),
    (VersionSurface.SOURCE.value, AWAITING_PACKAGING),
    (VersionSurface.PYPI.value, AWAITING_PACKAGING),
)

#: What the row says when this run matched no advisory to the package at all.
#:
#: The readiness is `not_applicable` and the line says what that is and is not:
#: there is no finding to be ready for, which is a different fact from the package
#: being clean. Whether this run *established* that it has no advisory is
#: `package_vulnerability`'s verdict, and this pass neither reads it nor restates
#: it.
NO_MATCHED_ADVISORY_DETAIL: Final[str] = (
    "the advisory evidence current at this run's cut-off matched no advisory to this package, so there is no "
    "finding for a fix to be ready for and remediation readiness does not apply. That is not a claim that the "
    "package is clean: whether this run established anything about its exposure is package_vulnerability's "
    "verdict at this same cut-off, which this row neither reads nor restates"
)

#: What the row says when there is no advisory evidence at the cut-off at all.
NO_ADVISORY_EVIDENCE_DETAIL: Final[str] = (
    "there is no advisory evidence for this package at or before this run's cut-off, so this run established "
    "nothing about whether anything needs remediating; unknown rather than nothing to do, and never blocked"
)

#: What the row says when the sweep carries no matched advisory and at least one
#: row that establishes nothing -- a read that failed, or a locator the source does
#: not know.
UNESTABLISHED_ADVISORY_EVIDENCE_DETAIL: Final[str] = (
    "the advisory evidence current at this run's cut-off matched no advisory to this package and the finding(s) "
    "{findings} establish nothing -- see each finding's own detail, which says whether the look failed or the "
    "source does not know the locator -- so this run cannot say there is nothing to remediate; unknown rather "
    "than not applicable, and never blocked"
)

#: What the row says when a matched finding records no fixed range.
#:
#: The line says plainly that the absence is the *field's* and not the advisory
#: source's, because the two look identical from a row: the collector writes its
#: "the source states no fixed range" clause for every blank field, so a reader
#: who took that clause as an answer would read every feed that simply omitted the
#: field as a source saying there is no fix. This row is `unknown`, and `blocked`
#: is not within reach of it.
NO_FIX_RECORDED_DETAIL: Final[str] = (
    "finding {finding} records no fixed range, so this run cannot say whether a fix exists. The advisory "
    "collector records a blank field and a source that stated nothing identically -- blank means missing and is "
    "never inferred -- so this is unknown rather than blocked, which would claim an absence nothing established"
)

#: What the row says when the recorded fixed range cannot be compared. The story's
#: `Block If`, on the row.
UNCOMPARABLE_FIX_DETAIL: Final[str] = (
    "finding {finding} records the fixed range {expression!r}, which states a set of versions rather than one "
    "and cannot be compared against what a surface stores without a version-ordering rule this product has not "
    "decided -- no architecture decision owns version ordering yet. Unknown naming the reason rather than a "
    "guess, and the run does not fail: no surface was asked about this finding, so none of them is a surface "
    "where the fix is absent"
)

#: What the row says when at least one surface was not read, which is why the
#: readiness is `unknown` rather than `blocked`.
#:
#: **The line this pass exists for.** Without it, an `unknown` row whose fix is on
#: no surface it managed to read looks exactly like a row nobody computed, and the
#: distinction between "we looked everywhere" and "we did not look here" is the
#: whole of the story.
UNREAD_SURFACES_DETAIL: Final[str] = (
    "the fixed version {fixed!r} was stated by no surface this run relied on, and the surface(s) {unread} were "
    "not read at this run's cut-off -- nothing was observed for them, what was observed states no version, what "
    "was observed states a version this run cannot order against the fix, or its evidence is past its freshness "
    "target. Unknown rather than blocked: a surface that was not read is not a surface where the fix is absent"
)

#: What the row says about a surface whose evidence is past its collector's
#: declared freshness target (`CPM-FR-38`, AC 3).
STALE_SURFACES_DETAIL: Final[str] = (
    "the evidence for the surface(s) {surfaces} is past the freshness target their collectors declare "
    "(CPM-FR-38), so this run did not rely on it: each reads not_read, which can neither assert that the fix is "
    "available nor establish that it is absent. A fresh surface beside a stale one still decides this row"
)

#: What the row says when a surface's collector declares no freshness target this
#: process can see.
#:
#: `CPM-AD-28` refuses a *registered* collector that declares none, so this is
#: reachable only where nothing is registered for that evidence table at all -- a
#: component that has adopted no collector for the surface. Recorded rather than
#: refused, because a refusal would cost this package its other four domains' rows
#: (`CPM-AD-23`), and the honest state is that staleness could not be decided for
#: that surface rather than that its evidence is fresh.
NO_FRESHNESS_TARGET_DETAIL: Final[str] = (
    "no registered collector declares a freshness target for the surface(s) {surfaces}, so this run could not "
    "decide whether their evidence has aged past one and did not treat it as stale. CPM-AD-28 refuses a "
    "registered collector that declares no target, so this means none is registered for those tables in this "
    "process rather than that one is misconfigured"
)

#: What the row says wherever a surface stated a version that is not the fixed
#: version.
#:
#: **The recorded limit of an equality comparison, and this story's gap.** Equality
#: can establish that a surface states the fix; its negation establishes nothing,
#: because each surface stores the version it states as its *latest* rather than
#: the set of versions it carries. So a surface stating anything else reads
#: `not_read` -- neither a fix a reviewer can install nor an absence they should
#: give up on -- and this line names the versions so the reader can see exactly
#: what was compared and decide for themselves. It fires on every row where a
#: relied-on surface stated something other than the fix, whatever the readiness,
#: because a reviewer reading `unknown` is now the person the limit is about.
EQUALITY_ONLY_DETAIL: Final[str] = (
    "the surface(s) {statements} state versions this run compared against the fixed version {fixed!r} by "
    "equality alone, which is the only version comparison this product has decided (policies/currency.py). "
    "Each of those surfaces reads not_read rather than not_published: a surface states its latest version, not "
    "the set of versions it carries, so stating something other than the fix establishes neither that the fix "
    "is there nor that it is absent. Deciding otherwise needs a version-ordering rule, which no architecture "
    "decision owns yet"
)

#: What the row says when the advisory sweep itself is past the advisory
#: collector's declared freshness target (`CPM-FR-38`, AC 3, `CPM-UJ-1`).
#:
#: The whole row is `unknown` and no surface is asked, because what a stale sweep
#: gives this run is a fixed version that may no longer be the one to look for --
#: and a readiness derived from it would be actionable-looking work resting on
#: evidence the product has already declared it does not trust.
STALE_ADVISORY_DETAIL: Final[str] = (
    "the advisory evidence current at this run's cut-off is past the freshness target the advisory collector "
    "declares (CPM-FR-38), so this run did not rely on it: the readiness is unknown rather than actionable, no "
    "surface was asked where a fix this evidence may no longer name has appeared, and evidence_stale says it "
    "happened"
)

#: What the row says when no registered collector declares a freshness target for
#: the advisory evidence table.
#:
#: The advisory half of `NO_FRESHNESS_TARGET_DETAIL`, spelled separately because
#: the advisory table is not a surface and a line calling it one would leave a
#: reader counting five.
NO_ADVISORY_FRESHNESS_TARGET_DETAIL: Final[str] = (
    "no registered collector declares a freshness target for the {evidence} table, so this run could not decide "
    "whether the advisory evidence has aged past one and did not treat it as stale. CPM-AD-28 refuses a "
    "registered collector that declares no target, so this means none is registered for that table in this "
    "process rather than that one is misconfigured"
)

#: What the row says when several matched advisories were reduced to one readiness.
SEVERAL_FINDINGS_DETAIL: Final[str] = (
    "{matched} advisory finding(s) were current at this run's cut-off and this row carries the least ready of "
    "their readiness verdicts -- a package is only as actionable as its worst finding. The surface columns, the "
    "fixed version and the referenced finding are about finding {finding} and about no other, because two "
    "advisories naming two fixed versions have two different sets of surface answers"
)


class RemediationPolicyError(ValueError):
    """The remediation pass met evidence or an argument it cannot compute from.

    A `ValueError` subclass, matching `policies/currency.py`'s
    `CurrencyPolicyError`, `policies/feedstock.py`'s `FeedstockPolicyError`,
    `policies/vulnerability.py`'s `VulnerabilityPolicyError`,
    `policies/licence.py`'s `LicensePolicyError`, `core/policy.py`'s
    `PolicyPassError` and `core/outcomes.py`'s `OutcomeVocabularyError`: every
    "this is unusable" in this product is a `ValueError`, so a caller catching one
    catches them all.

    **Almost nothing raises this**, and the module docstring argues why:
    `core/policy_run.py` puts one *package* in a transaction rather than one pass,
    so a refusal here costs that package its currency, feedstock, vulnerability and
    licence rows too. An uncomparable fixed range, a missing fix, an unread
    surface, a stale surface and an undeclared freshness target are all recorded on
    the row instead.
    """


def _require_aware(cutoff: datetime, *, reading: str) -> None:
    """Refuse a naive cut-off before anything is read as of it.

    Refused rather than converted, on the same terms `snapshot_as_of` refuses one:
    there is no offset to convert from, `USE_TZ` is on so Django would read it as
    if it were UTC, and a cut-off silently shifted by the reader's offset selects a
    different evidence set on every replay -- which is the opposite of what
    `CPM-FR-22` promises. It is also what staleness is measured from here, so a
    naive value would move the freshness boundary as well as the evidence set.

    Args:
        cutoff: The instant the read is bound by.
        reading: What is being read, for the message.

    Raises:
        RemediationPolicyError: When the cut-off is naive.

    """
    if not is_aware(cutoff):
        message = (
            f"the {reading} cannot be read as of the naive cutoff {cutoff!r}. Every instant comes from a "
            f"Clock, which always answers in UTC (CPM-AD-26); a naive value has no offset to interpret, so "
            f"the read would be silently shifted by whichever offset the reader happened to be in and the "
            f"replay CPM-FR-22 promises would return a different set each time."
        )
        raise RemediationPolicyError(message)


@dataclass(frozen=True)
class SurfaceReader:
    """How to read one version surface: which table and which column holds its version.

    A record rather than four `if` branches, on exactly the terms
    `policies/currency.py`'s equivalent states: the four surfaces differ in these
    two ways and in nothing else, so a fifth surface is an entry in
    `SURFACE_READERS` below rather than a fifth branch in every function here.

    It carries no tie-break, where `policies/currency.py`'s does, and that absence
    is the difference between the two passes. That one picks a single row and needs
    a fixed rule for which; this one reads the whole sweep, so there is nothing for
    a tie-break to decide.

    Attributes:
        surface: The `VersionSurface` value this reads for.
        model: The evidence table it reads. Read only: this pass writes no evidence
            and changes no collector (`CPM-AD-8`).
        version_field: The column on that table holding the version the surface
            states. The four tables spell it three different ways --
            `latest_version` twice, `recipe_version` and `published_version` --
            because each collector named it after what its own source calls it.
        reference_field: The column on `PackageRemediation` that stores the
            observation this surface's availability was read from.

    """

    surface: str
    model: type[SnapshotModel]
    version_field: str
    reference_field: str


@dataclass(frozen=True)
class SurfaceReading:
    """What one surface's newest sweep said at the cut-off, before anything is compared.

    Separated from the availability verdict on purpose, on the terms
    `policies/currency.py`'s `SurfaceReading` states: reading is a query and
    judging is arithmetic, and keeping them apart is what lets every comparison
    rule below be exercised without a database.

    Attributes:
        surface: The `VersionSurface` value this is about.
        observations: Every row of the newest sweep at or before the cut-off, in
            ascending primary-key order, or empty where the surface had none by
            then. A tuple rather than one row, because
            `conda_package_snapshots` holds one per `(channel, platform)` pair and
            a fix published on any of them is a fix a reviewer can install.
        version_field: Which column on those rows holds the version, carried here
            so the pure functions below need no second lookup table.
        stale: Whether the sweep is past the collector's declared freshness target
            as of the run's cut-off (`CPM-FR-38`). A stale surface is not relied
            on: it reads `not_read`, so it can neither assert a fix is available
            nor establish that one is absent.
        target_declared: Whether a registered collector declared a freshness target
            for this table at all. False means staleness could not be decided
            rather than that the evidence is fresh, and the row says so.

    """

    surface: str
    observations: tuple[SnapshotModel, ...]
    version_field: str
    stale: bool
    target_declared: bool


@dataclass(frozen=True)
class AdvisoryReading:
    """What the advisory sweep's own age came to, before any finding is judged.

    The fifth evidence table's freshness, held in a record of its own rather than
    folded into the four `SurfaceReading`s: the advisory table is not a surface --
    it answers "what is there to remediate" where they answer "where has this
    version appeared" -- and a stale sweep here stops the pass rather than muting
    one column.

    Attributes:
        stale: Whether the sweep is past the advisory collector's declared
            freshness target as of the run's cut-off (`CPM-FR-38`). True makes the
            whole row `unknown` with no surface asked: `CPM-UJ-1` says a finding
            older than its target shows as stale rather than actionable.
        target_declared: Whether a registered collector declared a target for
            `vulnerability_findings` at all. False means staleness could not be
            decided rather than that the evidence is fresh, and the row says so.

    """

    stale: bool
    target_declared: bool


#: How to read each of the four surfaces, in `VersionSurface`'s declared order.
#:
#: **This is not the consultation order** -- `READINESS_BY_SURFACE` above is, and
#: the two are deliberately different sequences. This one says which surfaces exist
#: and how to read each; that one says which reached verdict a reviewer should be
#: shown first. Collapsing them would make "read the surfaces in the order a fix is
#: most useful in" look like a rule when it is two rules.
SURFACE_READERS: Final[tuple[SurfaceReader, ...]] = (
    SurfaceReader(
        surface=VersionSurface.SOURCE.value,
        model=SourceReleaseSnapshot,
        version_field="latest_version",
        reference_field="source_snapshot",
    ),
    SurfaceReader(
        surface=VersionSurface.PYPI.value,
        model=PyPIReleaseSnapshot,
        version_field="latest_version",
        reference_field="pypi_snapshot",
    ),
    SurfaceReader(
        surface=VersionSurface.FEEDSTOCK.value,
        model=FeedstockSnapshot,
        version_field="recipe_version",
        reference_field="feedstock_snapshot",
    ),
    SurfaceReader(
        surface=VersionSurface.CONDA_PACKAGE.value,
        model=CondaPackageSnapshot,
        version_field="published_version",
        reference_field="conda_package_snapshot",
    ),
)


def current_findings(*, package_id: int, cutoff: datetime) -> tuple[VulnerabilityFinding, ...]:
    """Return every advisory finding of the newest sweep at or before a cut-off.

    **A sweep rather than a row**, on exactly the terms
    `policies/vulnerability.py`'s equivalent states: `vulnerability_findings` holds
    one row per matched advisory, every row of one collection carries that run's
    single instant, and reading one row would reduce nine advisories to whichever
    the database returned first.

    Two queries rather than one, deliberately. A single query cannot ask for "every
    row carrying the maximum of a column" without a window function or a correlated
    subquery, and both are a query plan this story would then own across two
    backends.

    Args:
        package_id: The package being asked about, by the integer primary key
            `CPM-AD-3` fixes.
        cutoff: The instant to read as of, aware. `CPM-AD-21` makes it the
            `finished_at` of a completed collection run, so a pass never reads
            evidence written by a run that is still `running`.

    Returns:
        The sweep's rows, by ascending primary key so a replay reads them in the
        same order, or empty where the package had no advisory evidence by then.
        Empty is not an error and is a matrix row of its own: the readiness is
        `unknown`, never `not_applicable` and never `blocked`.

    Raises:
        RemediationPolicyError: When `cutoff` is naive.

    """
    _require_aware(cutoff, reading="advisory findings")
    observed = (
        VulnerabilityFinding.objects.filter(package_id=package_id, observed_at__lte=cutoff)
        .order_by(*READ_ORDERING)
        .values_list("observed_at", flat=True)
        .first()
    )
    if observed is None:
        return ()
    return tuple(
        VulnerabilityFinding.objects.filter(package_id=package_id, observed_at=observed).order_by(WITHIN_A_SWEEP),
    )


def matched_findings(findings: Sequence[VulnerabilityFinding]) -> tuple[VulnerabilityFinding, ...]:
    """Return the findings that name an advisory this run matched to the package.

    **The only findings a readiness is derived from.** A finding that established
    nothing names no advisory and carries no fixed range -- `vulnerability_findings`
    forbids one on a row that is not determinate -- so there is nothing for a
    surface to be asked about. Filtering here is a statement rather than a defence,
    on the terms `policies/vulnerability.py`'s `risk_level` states its own.

    This deliberately reads `state` and produces no `PackageVulnerabilityOutcome`
    value: re-deriving a vulnerability status is on this story's Never list, and
    "which rows name an advisory" is a question about the evidence rather than
    about that pass's verdict.

    Args:
        findings: The findings current at the cut-off.

    Returns:
        The matched ones, in read order, or empty -- which is the package with
        nothing to be ready for.

    Raises:
        RemediationPolicyError: When a finding carries a state outside
            `VulnerabilityOutcome` -- including `not_applicable`, which the table
            refuses outright because an advisory question applies to every package.
            `choices` is a form rule Django does not enforce on `save()`, so such a
            row is reachable; reading it as "not matched" would let a value nobody
            recognises decide that a package has nothing to remediate.

    """
    for finding in findings:
        state = finding.state
        if state not in ADVISORY_VOCABULARY or state == VULNERABILITY_NOT_APPLICABLE:
            message = (
                f"the advisory finding {finding.pk} carries state {state!r}, which this pass cannot read as a "
                f"statement about whether the package has a finding to remediate. The states a finding may hold "
                f"are {sorted(ADVISORY_VOCABULARY)} less {VULNERABILITY_NOT_APPLICABLE!r}, which "
                f"vulnerability_findings refuses outright because an advisory question applies to every "
                f"package. A readiness derived from a value outside that set would tell a reviewer whether to "
                f"stop looking on the strength of something nothing in this product recognises."
            )
            raise RemediationPolicyError(message)
    return tuple(finding for finding in findings if finding.state == MATCHED)


def _read_and_matched_nothing(finding: VulnerabilityFinding) -> bool:
    """Report whether one finding is the advisory collector's "read, matched nothing".

    **A prefix test on the collector's own constant, and the same one
    `policies/vulnerability.py` applies to the same rows.** That pass draws this
    exact line to decide `no_advisory_matched` from `unknown`, and two passes
    reading one sweep in one run must not disagree about what it established. The
    prefix rather than an equality is that module's argument, inherited: the
    collector composes the stored line as `f"{because}: {said}"` wherever the
    source stated a reason of its own, so an equality would read every checked,
    clean package from such a source as establishing nothing.

    Args:
        finding: The evidence row.

    Returns:
        Whether the row says the source was read and matched no advisory. False
        for the other two `unknown` rows the collector writes -- the source cannot
        identify the package, and this package's identity names no version to
        match against -- neither of which establishes anything.

    """
    return finding.state == VULNERABILITY_UNKNOWN and finding.detail.strip().startswith(NOTHING_MATCHED_DETAIL)


def unestablished_findings(findings: Sequence[VulnerabilityFinding]) -> tuple[VulnerabilityFinding, ...]:
    """Return the findings that establish nothing about the package's exposure.

    Everything that is neither a matched advisory nor the collector's "read and
    matched nothing" sentinel: a read that failed, a locator the source does not
    know, an identity naming no version, and a source that answered it cannot
    identify the package. Where a sweep carries any of these and no matched
    advisory, this run cannot say there is nothing to remediate -- so the readiness
    is `unknown` rather than `not_applicable`, and the row names these rows.

    **`unknown` is the most common of them and was the defect here.** An earlier
    draft named only `error` and `not_found`, which meant a package the advisory
    source could not identify read `not_applicable` -- "there is nothing to be
    ready for" -- while `package_vulnerability` read `unknown` for the same
    package, the same run and the same rows. That is the clean-looking degradation
    `CPM-NFR-3` forbids, arrived at through the sentinel a real source produces
    most often.

    Args:
        findings: The findings current at the cut-off.

    Returns:
        Those rows, in read order, or empty.

    """
    return tuple(finding for finding in findings if finding.state != MATCHED and not _read_and_matched_nothing(finding))


def fixed_version(finding: VulnerabilityFinding) -> tuple[str, str]:
    """Return the fixed version one finding names, in the form it is compared as.

    Three outcomes, and the module docstring argues each. A bare version is
    `RECORDED` with its comparable form. A blank range is `UNRECORDED`. Anything
    carrying an `ORDERING_MARKERS` character states a *set* of versions and is
    `NOT_COMPARABLE`, which is the story's `Block If`.

    **There is no fourth case, and its removal is the point.** An earlier draft
    read a blank range whose finding carried the advisory collector's
    `NO_FIXED_RANGE_DETAIL` clause as "the source was asked and answered that there
    is no fix", and made it `blocked`. `collectors/vulnerability.py` writes one
    clause per field the source left *blank*, so the clause is present on exactly
    the rows this function already recognises by their blank `fixed_range` and
    refines nothing. What it actually did was make `UNRECORDED` unreachable from
    any row a collector writes and send every feed that omits a fixed range to
    `blocked` with four unread surfaces.

    Args:
        finding: The matched evidence row.

    Returns:
        The comparable version and which of the three cases it is. The version is
        `""` in both cases but `RECORDED`, and `""` is what
        `PackageRemediation.fixed_version` then stores.

    """
    stated = finding.fixed_range.strip()
    if not stated:
        return "", UNRECORDED
    if ORDERING_MARKERS & set(stated):
        return "", NOT_COMPARABLE
    comparable = comparable_version(stated)
    if not comparable:
        return "", NOT_COMPARABLE
    return comparable, RECORDED


def freshness_target(evidence_model: type[AppendOnlyModel]) -> timedelta | None:
    """Return the freshness target a registered collector declares for one evidence table.

    `CPM-AD-7` gives every collector its own evidence table, so the table *is* the
    collector and no lookup by name is needed -- which is what keeps this pass from
    carrying a second spelling of four collector names. `registered_collectors()`
    answers in a fixed order, so two processes with the same registry answer the
    same way.

    **The first match wins, and that is a recorded residual.** Two registered
    collectors writing one evidence table would make the earlier of them decide
    this target silently rather than be refused. Nothing in this product declares
    a second collector for any of these five tables and `CPM-AD-7` says nothing
    should, but the refusal that would hold it belongs with `core/registry.py`
    rather than here, where it would be one pass's private opinion about a
    registry every pass reads.

    Args:
        evidence_model: The surface's evidence table.

    Returns:
        The declared target, or `None` where no registered collector writes that
        table. `None` is not a fault this pass refuses: `CPM-AD-28` already refuses
        a *registered* collector declaring none, so `None` here means none is
        registered, and the honest consequence is that staleness could not be
        decided for that surface. `NO_FRESHNESS_TARGET_DETAIL` puts it on the row.

    """
    for collector in registered_collectors():
        if collector.evidence_model is evidence_model:
            return collector.freshness_target
    return None


def evidence_is_stale(
    evidence_model: type[AppendOnlyModel],
    *,
    observed_at: datetime | None,
    now: datetime,
) -> tuple[bool, bool]:
    """Report whether one evidence table's sweep has aged past its collector's target.

    Asked of all five tables this pass reads and not of the four surfaces alone:
    `CPM-UJ-1`'s stated edge case is that a finding older than its freshness
    target shows as stale rather than actionable, and the advisory table is where
    the finding comes from.

    `CPM-FR-38`'s answer, consumed rather than restated: `core/freshness.py` owns
    the comparison and this asks it. AC 3 is satisfied by what the caller does with
    the verdict -- a stale surface reads `not_read` and therefore cannot assert that
    a fix is available.

    `latest_observation` is deliberately not used. It answers about the newest
    observation full stop, where every read in this pass is bound to the run's
    cut-off; a staleness verdict measured off a row the cut-off excludes would make
    two replays of one run disagree.

    Args:
        evidence_model: The surface's evidence table, which is what names the
            collector whose target applies.
        observed_at: The instant the sweep read at the cut-off carries, or `None`
            where there was no sweep.
        now: The instant to measure from -- the run's evidence cut-off. Nothing
            here reads a wall clock.

    Returns:
        Whether the sweep is stale, and whether a target was declared at all. A
        surface with no sweep is not stale, because an absence of observation is
        not an old observation -- `core/freshness.py` makes that choice and this
        inherits it.

    Raises:
        FreshnessError: When `now` is naive. Unreachable through
            `RemediationPass.evaluate`, which refuses a naive cut-off before any
            read.

    """
    target = freshness_target(evidence_model)
    if target is None:
        return False, False
    return freshness_of(observed_at=observed_at, target=target, now=now).stale, True


def advisory_reading(findings: Sequence[VulnerabilityFinding], *, cutoff: datetime) -> AdvisoryReading:
    """Return the advisory sweep's own freshness, measured from the run's cut-off.

    **The fifth evidence table's freshness, which nothing measured before.**
    `CPM-UJ-1`'s stated edge case is that a finding older than its freshness target
    shows as stale rather than actionable, and a month-old advisory sweep beside a
    channel refreshed this morning would otherwise produce `ready` with
    `evidence_stale` false -- an actionable verdict resting on evidence this
    product has already declared it does not trust.

    No query of its own: every row of one sweep carries that sweep's single
    instant, so the rows `current_findings` already returned say when it was.

    Args:
        findings: The sweep current at the cut-off, possibly empty.
        cutoff: The instant staleness is measured from -- the run's evidence
            cut-off, never a wall clock.

    Returns:
        Whether the sweep is stale, and whether a target was declared at all. A
        package with no advisory evidence is not stale, because an absence of
        observation is not an old observation -- and it is already `unknown` for
        the stronger reason that nothing was established about it.

    """
    observed_at = findings[0].observed_at if findings else None
    stale, declared = evidence_is_stale(VulnerabilityFinding, observed_at=observed_at, now=cutoff)
    return AdvisoryReading(stale=stale, target_declared=declared)


def read_surface(reader: SurfaceReader, *, package_id: int, cutoff: datetime) -> SurfaceReading:
    """Return one surface's newest sweep at or before a cut-off, with its staleness.

    Two queries, on exactly the terms `current_findings` states: the newest instant
    at or before the cut-off, then every row carrying it.

    **The whole sweep rather than one row, and that is where this pass departs from
    `policies/currency.py`.** That one picks a single published-package row by an
    alphabetical channel tie-break, which is defensible for "is this package
    current" and is not defensible here: a fix published on a second-sorting
    channel would read `not_published`, and four such readings are `blocked` -- a
    channel list deciding that a reviewer should give up on a package whose fix
    they could install this morning. The other three tables hold one row per
    package per sweep, so reading them the same way costs nothing and keeps one
    rule.

    Args:
        reader: Which surface to read, and how.
        package_id: The package being asked about.
        cutoff: The instant to read as of, aware.

    Returns:
        The reading. Empty observations where the surface had no sweep by then,
        which is an ordinary answer and reads `not_read`.

    Raises:
        RemediationPolicyError: When `cutoff` is naive.

    """
    _require_aware(cutoff, reading=f"{reader.surface} surface")
    observed = (
        reader.model.objects.filter(package_id=package_id, observed_at__lte=cutoff)
        .order_by(*READ_ORDERING)
        .values_list("observed_at", flat=True)
        .first()
    )
    stale, declared = evidence_is_stale(reader.model, observed_at=observed, now=cutoff)
    observations: tuple[SnapshotModel, ...] = (
        ()
        if observed is None
        else tuple(reader.model.objects.filter(package_id=package_id, observed_at=observed).order_by(WITHIN_A_SWEEP))
    )
    return SurfaceReading(
        surface=reader.surface,
        observations=observations,
        version_field=reader.version_field,
        stale=stale,
        target_declared=declared,
    )


def stated_versions(reading: SurfaceReading) -> tuple[tuple[SnapshotModel, str], ...]:
    """Return the observations that state a version, with the form they are compared as.

    Only determinate observations, and only ones that name something. A sentinel
    row has not said what the surface holds, and a determinate row whose version
    the collector could not read has not either -- `FeedstockSnapshot` records
    exactly that for a recipe whose version is set in a way the collector does not
    parse. Neither is a statement that the fix is absent, which is why both fall
    through to `not_read`.

    Args:
        reading: What the surface's sweep said.

    Returns:
        One pair per observation that states a version, in read order.

    """
    return tuple(
        (observation, comparable)
        for observation in reading.observations
        if observation.state == OutcomeState.OK
        and (comparable := comparable_version(str(getattr(observation, reading.version_field))))
    )


def unordered_statements(reading: SurfaceReading, *, fixed: str) -> tuple[str, ...]:
    """Return the versions a relied-on surface stated when none of them is the fix.

    The equality limit as a fact about one surface, separated from the availability
    verdict so the row can name what was compared without re-deriving why the
    surface reads `not_read`. Empty for every surface this run did not rely on --
    a stale sweep, an undeclared freshness target, no fixed version to look for,
    nothing determinate stating a version -- because a surface nobody compared
    against the fix has no comparison to record.

    Args:
        reading: What the surface's sweep said.
        fixed: The comparable fixed version to look for, or `""`.

    Returns:
        Every version the sweep stated, in read order, where the surface was
        relied on and none of them equals the fix. Empty otherwise, including
        where the sweep carries the fix.

    """
    if not fixed or reading.stale or not reading.target_declared:
        return ()
    stated = tuple(version for _, version in stated_versions(reading))
    if not stated or fixed in stated:
        return ()
    return stated


def surface_availability(reading: SurfaceReading, *, fixed: str) -> tuple[str, SnapshotModel | None]:
    """Return whether one surface carries the fixed version, and the row that says so.

    **Two of the three values are producible here, and the third is the recorded
    gap.** `published` where any row of the sweep states the fixed version;
    `not_read` everywhere else. `not_published` is what a surface reads when it has
    *established* that the fix is not there, and nothing this product records can
    establish that: each of the four tables stores the version its surface states
    as its **latest**, not the set of versions it carries, so `latest != fix` says
    nothing in either direction -- PyPI still hosts 1.5 when its latest is 2.0.

    An earlier draft returned `not_published` for any surface stating a
    non-equal version, which made `blocked` the *steady state* rather than an edge:
    advisories name a fix, surfaces move past it, and every package with an older
    advisory decayed into the one verdict that tells a reviewer to stop looking.
    `unordered_statements` above records what was compared, `EQUALITY_ONLY_DETAIL`
    puts it on the row, and the module docstring names the two things that would
    make `not_published` -- and therefore `blocked` -- reachable again.

    **A `not_read` surface may still name the observation it looked at**, and this
    returns one wherever there was something to look at.
    `A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION` is `not_read OR the reference is
    present`, so the reference is permitted on either reading and a reviewer
    reading `not_read` beside the equality line can open the row it was read from.

    Args:
        reading: What the surface's sweep said.
        fixed: The comparable fixed version to look for, or `""` where the finding
            names none -- in which case there is nothing to look for and the
            surface reads `not_read`, because a surface cannot have established
            anything about a version nobody asked it about.

    Returns:
        The `FixAvailability` value and the observation it was read from: the first
        row of the sweep carrying the fix where one does, the first row that stated
        a version where the surface was relied on and none carried it, and `None`
        where there was nothing to look at.

    """
    if not fixed or reading.stale or not reading.target_declared:
        return SURFACE_NOT_READ, None
    statements = stated_versions(reading)
    if not statements:
        return SURFACE_NOT_READ, None
    for observation, stated in statements:
        if stated == fixed:
            return FIX_PUBLISHED, observation
    return SURFACE_NOT_READ, statements[0][0]


def finding_readiness(availability: Mapping[str, str], *, kind: str) -> str:
    """Return what one matched finding's fix comes to, over the four surfaces.

    The consultation order is `READINESS_BY_SURFACE` and is declared as data beside
    the verdicts it names, so "which surface reaches which readiness" is a table a
    reader can enumerate rather than a chain of `if` statements -- the argument
    `CURRENCY_PRECEDENCE` makes about an order written as control flow.

    **`blocked` is reached from four `not_published` readings and from nowhere
    else.** Every remaining shape -- including three surfaces read and one not --
    is `unknown`, and the row says which surface is unknown. The earlier second
    route, an advisory that "established there is no fix", is gone: no evidence
    this product records distinguishes a source that stated there is no fix from a
    field the source left blank, so that route was `blocked` reached from an
    absence, which is the one thing this pass exists to refuse.

    **So this branch is currently unreachable from `RemediationPass`, and it is
    kept deliberately.** `surface_availability` produces no `not_published`
    reading today -- the module docstring says why, and names the two changes that
    would restore one -- but the rule for what `blocked` *means* belongs here, is
    what `A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ` mirrors in the schema, and is
    exercised directly by the unit suite. Deleting it would leave the epic's AC 2
    value with no definition and the constraint with nothing to agree with.

    Args:
        availability: Each surface's `FixAvailability` value, by `VersionSurface`
            value.
        kind: Which of `fixed_version`'s three cases this finding is.

    Returns:
        A `RemediationReadiness` value: never `not_applicable`, which is a
        package-level answer decided before any finding is read, and never `error`
        or `not_found`, which this pass does not produce.

    Raises:
        RemediationPolicyError: When a surface `READINESS_BY_SURFACE` names is
            missing from the mapping -- a caller that built a partial reading.
            Unreachable through `evaluate`, which reads all four, and stated rather
            than left as a `KeyError` a traceback would blame on a dictionary.

    """
    if kind != RECORDED:
        return READINESS_UNKNOWN
    missing = sorted({surface for surface, _ in READINESS_BY_SURFACE} - set(availability))
    if missing:
        message = (
            f"the surface(s) {missing} carry no fix availability, so this finding's readiness cannot be "
            f"derived. Every surface in READINESS_BY_SURFACE is read for every package, and a partial mapping "
            f"would let an unread surface be mistaken for one where the fix is absent -- which is the single "
            f"thing this pass exists to prevent."
        )
        raise RemediationPolicyError(message)
    for surface, readiness in READINESS_BY_SURFACE:
        if availability[surface] == FIX_PUBLISHED:
            return readiness
    if all(availability[surface] == FIX_NOT_PUBLISHED for surface, _ in READINESS_BY_SURFACE):
        return BLOCKED
    return READINESS_UNKNOWN


def supporting_finding(
    verdicts: Sequence[tuple[VulnerabilityFinding, str]],
    readiness: str,
) -> VulnerabilityFinding | None:
    """Return the finding whose own readiness is the one the row carries.

    The first in read order, which is ascending primary key, so a replay names the
    same row -- and *not* simply the first finding given, which is why this loop
    exists: a package with one advisory fixed on a channel and one fixed nowhere
    must name the blocked one, or the row's four surface columns would describe a
    fix the verdict is not about.

    Args:
        verdicts: Each matched finding beside its own readiness, in read order.
        readiness: The readiness the row will carry.

    Returns:
        The supporting row, or `None` where none supports it -- which is exactly the
        package with no matched finding at all.

    """
    for finding, verdict in verdicts:
        if verdict == readiness:
            return finding
    return None


def remediation_detail(  # noqa: PLR0913 - one keyword per fact a line may name; a bundle would hide which
    *,
    findings: Sequence[VulnerabilityFinding],
    matched: Sequence[VulnerabilityFinding],
    readings: Mapping[str, SurfaceReading],
    availability: Mapping[str, str],
    supporting: VulnerabilityFinding | None,
    fixed: str,
    kind: str,
    readiness: str,
    advisory: AdvisoryReading,
) -> str:
    """Return the row's account of its readiness, or `""` where the columns say it.

    Populated on exactly the shapes whose reason is not readable off the row's own
    columns, and empty everywhere else -- the rule every table in this product
    applies to its own `detail`: an explanation of an unremarkable row is noise.

    A `blocked` row whose four surface columns all read `not_published` gets no
    line about the block itself: the columns say between them that every surface was
    read and none carried the fix, which is the whole of what `blocked` means. What
    it may still carry is the equality-limit line, because that is the one thing
    those columns do not say.

    Args:
        findings: Every finding current at the cut-off.
        matched: The matched ones.
        readings: What each surface's sweep said, by `VersionSurface` value.
            Empty where no surface was read, which is the no-matched-finding row.
        availability: Each surface's `FixAvailability` value, by the same key.
        supporting: The finding the readiness rests on, or `None`.
        fixed: The comparable fixed version the row looked for, or `""`.
        kind: Which of `fixed_version`'s four cases the supporting finding is.
        readiness: The readiness the row carries. Read for one line only -- the
            unread-surface line is what says why this row is `unknown` rather than
            `blocked`, and on a row that found the fix somewhere it would be
            answering a question the verdict did not raise.
        advisory: The advisory sweep's own freshness. A stale sweep is the whole
            of why the row is `unknown`, so it is said first and nothing after it
            is said at all -- no surface was asked.

    Returns:
        One line per fact, joined, in a fixed order so two runs over one package
        produce byte-identical text.

    """
    lines: list[str] = []
    if not advisory.target_declared:
        lines.append(NO_ADVISORY_FRESHNESS_TARGET_DETAIL.format(evidence=ADVISORY_EVIDENCE))
    if advisory.stale:
        lines.append(STALE_ADVISORY_DETAIL)
        return " ".join(lines)
    if supporting is None:
        lines.append(_absent_finding_line(findings))
        return " ".join(lines)
    if len(matched) > 1:
        lines.append(SEVERAL_FINDINGS_DETAIL.format(matched=len(matched), finding=supporting.pk))
    lines.extend(_fix_lines(supporting, fixed=fixed, kind=kind))
    lines.extend(
        _surface_lines(readings, availability=availability, fixed=fixed, kind=kind, readiness=readiness),
    )
    return " ".join(lines)


def _absent_finding_line(findings: Sequence[VulnerabilityFinding]) -> str:
    """Return the line a row with no matched finding carries.

    Args:
        findings: Every finding current at the cut-off.

    Returns:
        One line. Which of the three it is says whether nobody looked, whether the
        look established nothing, or whether the source answered and matched
        nothing -- three different pieces of work behind two different readiness
        values.

    """
    if not findings:
        return NO_ADVISORY_EVIDENCE_DETAIL
    unestablished = unestablished_findings(findings)
    if unestablished:
        return UNESTABLISHED_ADVISORY_EVIDENCE_DETAIL.format(
            findings=", ".join(str(finding.pk) for finding in unestablished),
        )
    return NO_MATCHED_ADVISORY_DETAIL


def _fix_lines(supporting: VulnerabilityFinding, *, fixed: str, kind: str) -> list[str]:
    """Return the lines about the fixed version the supporting finding names.

    Args:
        supporting: The finding the readiness rests on.
        fixed: The comparable fixed version, or `""`.
        kind: Which of `fixed_version`'s four cases it is.

    Returns:
        One line, or none where the finding names a fix this pass compared -- in
        which case `fixed_version` on the row says what it was.

    """
    if kind == UNRECORDED:
        return [NO_FIX_RECORDED_DETAIL.format(finding=supporting.pk)]
    if kind == NOT_COMPARABLE:
        return [
            UNCOMPARABLE_FIX_DETAIL.format(finding=supporting.pk, expression=supporting.fixed_range.strip()),
        ]
    return []


def _surface_lines(
    readings: Mapping[str, SurfaceReading],
    *,
    availability: Mapping[str, str],
    fixed: str,
    kind: str,
    readiness: str,
) -> list[str]:
    """Return the lines about what the four surfaces said.

    Args:
        readings: What each surface's sweep said, by `VersionSurface` value.
        availability: Each surface's `FixAvailability` value, by the same key.
        fixed: The comparable fixed version, or `""`.
        kind: Which of `fixed_version`'s four cases the supporting finding is.
        readiness: The readiness the row carries, which gates the unread-surface
            line: a row that found the fix on some surface is not a row a reader
            has to be told why it is not `blocked`.

    Returns:
        The lines, in `SURFACE_READERS` order within each and in a fixed order
        between them. Empty where there was nothing to look for, because a surface
        cannot have failed to answer a question nobody asked it.

    """
    lines: list[str] = []
    ordered = [reader.surface for reader in SURFACE_READERS if reader.surface in readings]
    stale = [surface for surface in ordered if readings[surface].stale]
    if stale:
        lines.append(STALE_SURFACES_DETAIL.format(surfaces=stale))
    undeclared = [surface for surface in ordered if not readings[surface].target_declared]
    if undeclared:
        lines.append(NO_FRESHNESS_TARGET_DETAIL.format(surfaces=undeclared))
    if kind != RECORDED:
        return lines
    unread = [surface for surface in ordered if availability[surface] == SURFACE_NOT_READ]
    if unread and readiness == READINESS_UNKNOWN:
        lines.append(UNREAD_SURFACES_DETAIL.format(fixed=fixed, unread=unread))
    # Every version of the sweep rather than its first, because
    # `conda_package_snapshots` holds one row per `(channel, platform)` pair and a
    # line naming one of four channels discloses a quarter of what was compared to
    # the reader the equality limit is about.
    statements = [
        f"{surface} states {list(stated)}"
        for surface in ordered
        if (stated := unordered_statements(readings[surface], fixed=fixed))
    ]
    if statements:
        lines.append(EQUALITY_ONLY_DETAIL.format(statements=statements, fixed=fixed))
    return lines


class RemediationPass(PolicyPass):
    """`CPM-FR-41` as a `PolicyPass`: read five evidence tables, compare, write one row.

    Three declarations and one method. The derived table is `PackageRemediation`
    and there is **no** rollup column: the rollup offers none for this domain and
    `CPM-AD-21` says no pass writes the health rollup, so `contributes` is empty and
    `core/policy.py` records that an empty contribution is legitimate.

    **It overrides no `prepare`, and that is the one way its shape differs from the
    three parameterised passes.** They establish a parameter set once per run
    because their verdicts are governed by reviewed data keyed by the policy
    version. This pass reads no parameter -- the module docstring says why -- so
    there is nothing to establish before the loop and nothing a run-wide refusal
    would be about. A run at a version the reviewed file does not record still
    fails, in `FeedstockPresencePass.prepare`, exactly as it did before this pass
    existed.
    """

    name: ClassVar[str] = POLICY_NAME
    derived_model: ClassVar[type[models.Model] | None] = PackageRemediation
    contributes: ClassVar[tuple[str, ...]] = ()

    def evaluate(
        self,
        package: Package,
        *,
        policy_run: PolicyRun,
        evidence_cutoff: datetime,
    ) -> Mapping[str, str]:
        """Judge whether one package's findings can be acted on, and write its derived row.

        Called once per package, inside that package's transaction (`CPM-AD-23`),
        so a refusal here rolls back **everything this run did for this package** --
        its currency, feedstock, vulnerability and licence rows as well as this one,
        and its rollup row with them -- and leaves every other package's committed.
        That is why so little in here refuses: see the module docstring.

        **Every package gets a row**, including one with no evidence and no
        inventory mapping: the readiness is `unknown`, all four surfaces read
        `not_read`, and the absence of a row would read as never-evaluated instead.

        **The four surfaces are read once and reused across every matched
        finding.** A package with nine advisories issues the same eight surface
        queries as one with a single advisory, because what differs between findings
        is the version being looked for and not the evidence being looked at.

        Args:
            package: The package to judge.
            policy_run: The run this evaluation belongs to. Its version and its
                cut-off are copied onto the row, where together with the package it
                is `CPM-AD-21`'s key.
            evidence_cutoff: The instant to read evidence as of, and the instant
                staleness is measured from. Nothing here reads the current time.

        Returns:
            An empty mapping. This pass contributes no rollup column, which
            `core/policy.py` records as legitimate and `CPM-AD-21` requires.

        Raises:
            RemediationPolicyError: When an advisory finding carries a state
                outside `VulnerabilityOutcome`, and when the cut-off is naive.
                Deliberately **not** for an uncomparable fixed range, a finding with
                no fix, a surface nobody read, a stale surface or a collector
                declaring no freshness target: a raise here rolls back this
                package's other four domains' rows too (`CPM-AD-23`), and every one
                of those is an honest state the row can record instead.

        """
        findings = current_findings(package_id=package.pk, cutoff=evidence_cutoff)
        advisory = advisory_reading(findings, cutoff=evidence_cutoff)
        matched = matched_findings(findings)
        readings = (
            {}
            if advisory.stale or not matched
            else {
                reader.surface: read_surface(reader, package_id=package.pk, cutoff=evidence_cutoff)
                for reader in SURFACE_READERS
            }
        )
        readiness, supporting, fixed, kind = self._judge(
            matched,
            readings=readings,
            findings=findings,
            advisory=advisory,
        )
        resolved = self._resolve(readings, fixed=fixed)
        availability = {surface: value for surface, (value, _) in resolved.items()}
        decided = {surface: observation for surface, (_, observation) in resolved.items()}
        # Written with one keyword per column rather than through a `defaults`
        # mapping, on exactly the terms `policies/currency.py` states:
        # `tests/unit/django_apps/test_derived_status_writability_audit.py` reads
        # keyword names, so the mapping form would take this write out of that
        # audit's view -- which is the `**kwargs` dodge that module names. The
        # visible form plus a recorded exemption is the honest shape.
        PackageRemediation.objects.create(
            package=package,
            policy_run=policy_run,
            readiness_status=readiness,
            source_fix=availability[VersionSurface.SOURCE.value],
            pypi_fix=availability[VersionSurface.PYPI.value],
            feedstock_fix=availability[VersionSurface.FEEDSTOCK.value],
            conda_package_fix=availability[VersionSurface.CONDA_PACKAGE.value],
            fixed_version=fixed,
            evidence_stale=advisory.stale or any(reading.stale for reading in readings.values()),
            policy_version=policy_run.policy_version,
            evidence_cutoff=evidence_cutoff,
            vulnerability_finding=supporting,
            # The four evidence references are spread rather than spelled, on
            # exactly the terms `policies/currency.py` spreads its own: the
            # per-surface *verdict* keywords above are literal because
            # `tests/unit/django_apps/test_derived_status_writability_audit.py`
            # reads keyword names, and these four are not verdicts -- they are the
            # rows those verdicts were read from, one model each, which no single
            # literal assignment can be typed for.
            **{reader.reference_field: decided[reader.surface] for reader in SURFACE_READERS},
            detail=remediation_detail(
                findings=findings,
                matched=matched,
                readings=readings,
                availability=availability,
                supporting=supporting,
                fixed=fixed,
                kind=kind,
                readiness=readiness,
                advisory=advisory,
            ),
        )
        return {}

    def _judge(
        self,
        matched: Sequence[VulnerabilityFinding],
        *,
        readings: Mapping[str, SurfaceReading],
        findings: Sequence[VulnerabilityFinding],
        advisory: AdvisoryReading,
    ) -> tuple[str, VulnerabilityFinding | None, str, str]:
        """Reduce the matched findings to one readiness and the finding it rests on.

        **The package-level answer for "no matched finding" is decided here rather
        than in the reduction**, because it is not a verdict about a fix at all:
        `not_applicable` says there is nothing to be ready for, and `unknown` says
        this run could not tell whether there is. `READINESS_PRECEDENCE` ranks
        neither, deliberately -- see `worst_readiness`.

        **A stale advisory sweep is decided here too, and before anything else.**
        `CPM-UJ-1` says a finding older than its freshness target shows as stale
        rather than actionable, and the honest form of that is `unknown` with no
        finding named: what the sweep offers is a fixed version that may no longer
        be the one to look for, so naming it beside four surface answers would be
        an actionable-looking row resting on evidence this run has said it does not
        rely on.

        Args:
            matched: The matched findings current at the cut-off.
            readings: What each surface's sweep said, empty where nothing was read.
            findings: Every finding current at the cut-off, for the two shapes
                above.
            advisory: The advisory sweep's own freshness.

        Returns:
            The readiness, the finding it rests on or `None`, the comparable fixed
            version that finding named or `""`, and which of `fixed_version`'s
            three cases it is.

        """
        if advisory.stale:
            return READINESS_UNKNOWN, None, "", UNRECORDED
        if not matched:
            unestablished = unestablished_findings(findings)
            unknown = not findings or bool(unestablished)
            return (READINESS_UNKNOWN if unknown else READINESS_NOT_APPLICABLE), None, "", UNRECORDED
        verdicts = [
            (
                finding,
                finding_readiness(
                    {surface: value for surface, (value, _) in self._resolve(readings, fixed=version).items()},
                    kind=kind,
                ),
                version,
                kind,
            )
            for finding in matched
            for version, kind in (fixed_version(finding),)
        ]
        readiness = worst_readiness(verdict for _, verdict, _, _ in verdicts)
        supporting = supporting_finding([(finding, verdict) for finding, verdict, _, _ in verdicts], readiness)
        # `next` without a default rather than a loop with a fallback: `readiness`
        # is one of the verdicts `worst_readiness` was handed, so exactly one entry
        # matches and a fallback branch would be a line no case can reach.
        _, _, version, kind = next(entry for entry in verdicts if entry[0] is supporting)
        return readiness, supporting, version, kind

    def _resolve(
        self,
        readings: Mapping[str, SurfaceReading],
        *,
        fixed: str,
    ) -> dict[str, tuple[str, SnapshotModel | None]]:
        """Return each surface's fix availability, including the surfaces nothing read.

        Every surface always appears, and that is what makes `finding_readiness`'s
        `blocked` test total: a surface missing from the mapping would be a surface
        neither read nor recorded, which is the silence this pass exists to refuse.

        Args:
            readings: What each surface's sweep said, by `VersionSurface` value.
                Empty where no surface was read at all.
            fixed: The comparable fixed version to look for, or `""`.

        Returns:
            One `(FixAvailability value, observation)` pair per `SURFACE_READERS`
            entry. A surface with no reading is `not_read` with no observation,
            which is what the row's `A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION`
            constraint requires of it.

        """
        return {
            reader.surface: (
                surface_availability(readings[reader.surface], fixed=fixed)
                if reader.surface in readings
                else (SURFACE_NOT_READ, None)
            )
            for reader in SURFACE_READERS
        }
