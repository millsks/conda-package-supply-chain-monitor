"""`CPM-FR-18`: one licence outcome per package, and `allowed` reachable only by a rule.

The fourth policy pass. It reads `license_findings` -- what each monitored
channel stated and what `collectors/spdx.py` normalized it to -- as of the run's
stated cut-off, matches each normalized expression against a rule set held **by
the run's policy version** in reviewed data, and writes its own derived row. It
writes no evidence, makes no outbound call, and never writes the rollup.

**The single property this whole pass turns on: `allowed` is never a default and
never an absence.** Every other outcome is reachable by something not happening.
No rule matched, no rule set was recorded, the channel stated no licence, it
stated one this product will not normalize, the read failed, no monitored channel
serves the package, there was no evidence at all -- each of those reaches
`manual_review` or `unknown`, and neither claims anything. `allowed` is reached
one way: a rule names the normalized expression and its recorded disposition is
`allowed`. There is no branch here that produces it, only `rule.disposition`
returned from a rule the file recorded; `worst_license` ranks it last, so a
reduction cannot reach it while any channel said anything else; and
`policies/models.py` puts a database check constraint behind it, so a row
claiming it while naming no rule is refused by PostgreSQL rather than merely
avoided here.

**The shipped rule set is empty, and that is the answer rather than a
placeholder.** `CPM-FR-18`'s content -- which licences are allowed -- is PRD Open
Question 2, which the PRD names as unanswered and as blocking `CPM-EP-SECURITY`,
and `CPM-SECURITY-S05`'s epic entry constrains this story to the mechanism and a
schema. So no version records a rule, every package whose licence this run
established reaches `manual_review`, and the row says why. That is not a
degraded mode: it is exactly what `CPM-SECURITY-S03`'s second acceptance
criterion already promised would happen to a licence this product cannot judge,
and it is the only honest verdict available while nobody has decided the policy.

**`manual_review` and `unknown` answer different questions and never share a
value.** `unknown` means the licence itself was never established -- no evidence
at the cut-off, a channel that stated none, one that stated something
`collectors/spdx.py` will not normalize without guessing, one that could not be
read, or a sweep in which no monitored channel serves the package at all.
`manual_review` means the licence
*is* known and no recorded rule names it. One is a gap in the evidence and the
other is a gap in the policy, and a reviewer told only "somebody must look at
this" cannot tell which of the two they are being asked to fix. So the row says
which, in words, on every shape where the columns cannot.

**A version recording no rule set does not fail the package, and this is the one
decision here carried forward from another story's review.**
`CPM-SECURITY-S04`'s pass refused per package for a version recording no
severity order, justified in four documents by the claim that only that domain's
rows would be lost. The claim was false: `core/policy_run.py` wraps *every pass
for one package* in a single `transaction.atomic()`, because `CPM-AD-23`'s atomic
unit is one package and not one pass. A refusal here would therefore roll back
that package's `PackageCurrency`, `PackageFeedstockPresence` and
`PackageVulnerability` rows as well as its own, `compose_rollup` would skip it,
and -- the condition being version-wide -- every package would fail and the run
would finalize `failed`. Every run recorded before this pass existed would stop
replaying, to protect a licence replay that does not exist, because no run at
such a version ever carried a licence verdict. So an unrecorded rule set is read
as "no rule names anything", which is what an empty one means anyway, and the row
says so. A **malformed** rule set is still refused, in `policies/parameters.py`
at the read: that is an operator error in a file somebody can edit rather than a
historical artifact, and it fails the whole file rather than one package.

**A rule names a normalized expression whole, and a conjunction is the one place
where that is not the end of it.** `license_findings.normalized_license` may hold
a compound expression -- `collectors/spdx.py` normalizes two or more recognised
identifiers joined by a single `AND` or a single `OR`, so `MIT OR Apache-2.0` and
`MIT AND GPL-3.0-only` are both reachable values. (`WITH` is not: that module
deliberately excludes it, because its right operand is an exception identifier
from a list nothing here carries, so no rule should ever be written naming one.)
The comparison is over the whole expression, case-folded on both sides.

For `OR`, whole is the whole of it. A disjunction offers a *choice* of licences,
and deciding which one a package took is a compliance judgement rather than a
string operation, so a disjunction no rule names whole reaches `manual_review`:
the permission is withheld, which is the conservative direction, and a reviewer
who wants `MIT OR Apache-2.0` allowed writes a rule naming it.

For `AND` it is not, and an earlier draft of this module called both cases
conservative when only one of them is. A conjunction binds *every* one of its
operands at once, so `MIT AND GPL-3.0-only` carries `GPL-3.0-only`'s obligations
whatever else it carries. Left undecomposed it reaches `manual_review`, which is
rank 3 of 5 -- strictly more permissive than the `forbidden` a rule about that
operand already states, and more permissive than `unknown`. So a conjunction no
rule names whole is decomposed **in the restrictive direction only**: where a
rule names one of its operands `forbidden` or `restricted`, the compound takes
the least permissive such disposition, and the row says which operand decided it
and why. That is not a compliance judgement about the conjunction; it is what
`AND` means.

Decomposition never runs the other way. `allowed` still requires a rule naming
the whole expression, so no rule about one operand can permit a compound, and the
single property this pass turns on is untouched by any of this.

**The evidence read is the newest *sweep*, not the newest row.**
`license_findings` holds one row per monitored channel per collection -- PRD
Appendix A.2's "several channels may state different licences for one package,
and each states its own" -- and every row of one sweep carries that run's single
instant, which is an observed property of `collectors/license.py` stamping every
row it builds from the run's one clock reading rather than something `CPM-AD-7`
guarantees. So the read takes the newest `observed_at` at or before the cut-off
and then every row carrying it. Reading one row would reduce four channels to
whichever the database returned, and on this table that is the difference between
seeing a disagreement and not knowing there was one.

**Disagreement never resolves upward.** Where two channels state different
licences, the outcome is the worst rank any of them yields --
`LICENSE_PRECEDENCE` puts `forbidden` first and `allowed` last, so a package one
channel says is forbidden cannot read `allowed` because another channel says
something milder. The row's `detail` names the expressions that disagreed, so the
verdict is not the only sign of it.

**A channel that does not carry the package has not said anything, and does not
vote.** `collectors/license.py` writes one row per monitored channel and never
fewer, so a package conda-forge serves and bioconda does not gets a determinate
row *and* a `not_found` row in the same sweep. `not_found` is not missing
information about a licence -- the package is simply not there -- so it takes no
part in the reduction at all, on exactly the terms `stated_expressions` drops a
blank expression: a channel that stated no licence has not disagreed with one
that did, it has said nothing. Folding it in would rank `unknown` against the
verdict the serving channel actually supported and would collapse the answer for
every package the monitored channels do not all carry, which is most of them --
`allowed` would become unreachable outside a single-channel deployment, and
`manual_review` would be masked. `error` is emphatically **not** the same case
and still downgrades: a read that failed is genuine uncertainty about what that
channel would have said. Where every channel answered `not_found` there is
nothing left to reduce, and the outcome is `unknown` -- which is the same answer
the empty reduction gives, so the row a package no channel serves gets is
`unknown` either way, and it names the absences it met.

**Nothing here reads the current time.** Every instant is the run's: the cut-off
arrives as an argument (`CPM-AD-21`) and the row records it. That is what makes
`CPM-FR-22`'s replay reproduce identical rows -- the evidence at or before a
fixed instant does not change, and neither does the rule set a recorded version
names.

**What refuses, and what is recorded instead.** Two conditions about a run's
inputs raise: a policy version the reviewed file does not record, from `prepare`,
before the loop, where it costs one traceback rather than ten thousand; and a
licence finding carrying a state outside `LicenseOutcome`, per package, because
an outcome derived from a value nothing recognises is the one thing that must not
reach the column a compliance reviewer reads first, and one corrupt evidence row
is genuinely one package's problem. (Two guards against a caller doing something
impossible through the orchestration also raise -- a naive cut-off and a pass
never prepared -- and neither is reachable from a policy run.) Everything else is
recorded on the row: an empty rule set, a rule set that names nothing this
package uses, a determinate row carrying no expression, and every sentinel state.

**On the spelling.** This module is `licence.py` and the pass is `licence`,
matching this component's prose and `CPM-EP-SECURITY`'s own wording; the model,
the table and the columns are `license`, matching `collectors.LicenseFinding` and
the `license_findings` table they join to. The split is deliberate rather than an
oversight: schema names follow the schema that already exists, and a reader
joining `package_license` to `license_findings` never meets two spellings in one
query.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

from conda_sentinel.collectors.models import LicenseFinding
from conda_sentinel.collectors.outcomes import LICENSE_ERROR
from conda_sentinel.collectors.outcomes import LICENSE_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import LICENSE_NOT_FOUND
from conda_sentinel.collectors.outcomes import NORMALIZED
from conda_sentinel.collectors.outcomes import LicenseOutcome
from conda_sentinel.core.clock import is_aware
from conda_sentinel.core.policy import PolicyPass
from conda_sentinel.policies.models import PackageLicense
from conda_sentinel.policies.outcomes import LICENSE_PRECEDENCE
from conda_sentinel.policies.outcomes import LICENSE_STATUS_UNKNOWN
from conda_sentinel.policies.outcomes import MANUAL_REVIEW
from conda_sentinel.policies.outcomes import RULE_DISPOSITIONS
from conda_sentinel.policies.outcomes import worst_license
from conda_sentinel.policies.parameters import RULES_KEY
from conda_sentinel.policies.parameters import parameters_for

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence
    from datetime import datetime

    from django.db import models

    from conda_sentinel.core.models import PolicyRun
    from conda_sentinel.identity.models import Package
    from conda_sentinel.policies.parameters import LicenseRule
    from conda_sentinel.policies.parameters import PolicyParameters

__all__ = [
    "BLANK_EXPRESSION_DETAIL",
    "CONJOINED_OPERAND_DETAIL",
    "CONJUNCTION",
    "DISAGREEING_CHANNELS_DETAIL",
    "ESTABLISHED_ELSEWHERE_DETAIL",
    "LICENSE_VOCABULARY",
    "NO_MATCHING_RULE_DETAIL",
    "NO_RULE_SET_DETAIL",
    "POLICY_NAME",
    "READ_ORDERING",
    "RESTRICTIVE_DISPOSITIONS",
    "UNESTABLISHED_LICENCE_DETAIL",
    "UNKNOWN_KINDS",
    "UNREADABLE_CHANNEL_DETAIL",
    "UNSERVED_PACKAGE_DETAIL",
    "WITHIN_A_SWEEP",
    "LicensePass",
    "LicensePolicyError",
    "conjoined_operands",
    "contributing_findings",
    "current_findings",
    "deciding_rule",
    "finding_verdict",
    "license_detail",
    "license_outcome",
    "matched_rule",
    "normalized_expression",
    "referenced_findings",
    "restrictive_rule",
    "rule_for",
    "stated_expressions",
    "supporting_finding",
]

#: What this pass is called. It keys `core/policy.py`'s registry, keys the
#: rollup's per-domain `policy_versions` map (`CPM-AD-11`) and appears in every
#: refusal about this pass, so it is spelled once and imported.
#:
#: `licence` plainly, unlike `feedstock-presence`, and on exactly the terms
#: `policies/vulnerability.py` argues its own: there is no second licence pass
#: coming. `collectors/license.py`'s collector is keyed in a separate registry,
#: so nothing collides -- and the two names meaning the same domain is the point.
POLICY_NAME: Final[str] = "licence"

#: The ordering that decides which sweep a cut-off-bound read returns.
#:
#: Declared rather than spelled inside the query, on the terms
#: `policies/vulnerability.py`'s `READ_ORDERING` is: this is the sixth
#: hand-written copy of `collectors/models.py`'s `snapshot_as_of` rule in this
#: repository, and what the copies are not left to do is drift.
READ_ORDERING: Final[tuple[str, ...]] = ("-observed_at", "-pk")

#: The order rows within one sweep are read in, so the row a verdict names is the
#: same on every replay. Ascending primary key: arbitrary, and chosen only
#: because it is *fixed*.
WITHIN_A_SWEEP: Final[str] = "pk"

#: Every value a `license_findings` row's state may hold, as strings.
#:
#: Read off the composed vocabulary rather than listed, on the terms
#: `policies/vulnerability.py`'s `VULNERABILITY_VOCABULARY` is derived: listing
#: them would be a second spelling of values `outcome_type` has already fixed
#: once, and a module-scope literal holding several `OutcomeState` members is
#: indistinguishable from a precedence order to
#: `tests/unit/django_apps/test_single_ordering_audit.py`. A comprehension is
#: neither.
LICENSE_VOCABULARY: Final[frozenset[str]] = frozenset(LicenseOutcome.values)

#: What the row says when the run's policy version records no rule set at all --
#: which is every version this component currently ships.
#:
#: It names the version and the key so an operator can go to the entry that
#: produced it, and it states plainly that this is the decided answer rather than
#: a fault, because a `manual_review` on every package in an inventory is exactly
#: the shape somebody would otherwise read as a broken pass.
#: It is worded about the *rules* rather than about the key, and that is a
#: correction rather than a style choice. `policies/parameters.py` reads an absent
#: `license_rules` and an explicitly empty one to the same `()`, deliberately and
#: at length, so a line saying "records no license_rules" is false of the shipped
#: `2026.09.2` entry, which visibly declares `license_rules = []`. What both
#: spellings have in common is that no rule names anything, so that is what the
#: line says, and it names the key as the thing a reviewer fills in rather than as
#: something the entry lacks.
NO_RULE_SET_DETAIL: Final[str] = (
    "policy version {version} records no licence rule -- its {key} names nothing, whether the entry omits the "
    "key or declares it empty, which this product reads as one state -- so no rule names {expression!r}, the "
    "licence this run established for this package, and the outcome is manual review. That is the answer to "
    "'no licence policy has been decided' rather than a failure: allowed is reachable only from a rule that "
    'names a licence and permits it. Record rules in a new [versions."..."] entry and enqueue a run at it to '
    "reach a compliance verdict"
)

#: What the row says when the version records rules and none of them names this
#: package's licence.
#:
#: A different line from `NO_RULE_SET_DETAIL` because the work is different:
#: there, nobody has written a policy at all; here, a policy exists and does not
#: cover this licence, and somebody has to decide whether it should. The count is
#: in the line so the two cannot be confused by a reader who sees only one of
#: them.
NO_MATCHING_RULE_DETAIL: Final[str] = (
    "policy version {version} records {rules} licence rule(s) and none of them names {expression!r}, which is "
    "the licence this run established for this package, so the outcome is manual review rather than allowed. A "
    "compound expression is matched whole: a rule naming one operand of a disjunction does not reach it, and a "
    "rule naming one operand of a conjunction reaches it only to forbid or restrict it, never to permit it"
)

#: What the row says when no rule names a conjunction whole and a rule naming one
#: of its operands decided it anyway.
#:
#: Present because that row would otherwise be the one shape in this pass where
#: the columns actively mislead: the outcome is `forbidden`, the matched rule is
#: `GPL-3.0-only`, and the finding it references states `MIT AND GPL-3.0-only` --
#: three values a reader has to reconcile with no statement anywhere that they
#: were arrived at by decomposition. The line says which operand decided it, and
#: says that decomposition runs one way only, because "a rule about one operand
#: decided this" invites exactly the wrong inference about `allowed`.
CONJOINED_OPERAND_DETAIL: Final[str] = (
    "no rule names {expression!r} whole, and it is a conjunction: every one of its operands binds at once, so "
    "the rule naming {operand!r} as {disposition} decides the whole expression. A conjunction is decomposed in "
    "the restrictive direction only -- allowed still requires a rule naming the whole expression, so no rule "
    "about one operand can ever permit a compound"
)

#: What the row says when the licence evidence establishes no licence -- the
#: channel stated none, or stated something this product will not normalize.
#:
#: Present so that **every** `unknown` with evidence behind it says which kind it
#: was, on the terms `policies/vulnerability.py`'s equivalent states. It also says
#: what the row is *not*, because `unknown` beside `manual_review` is the one
#: distinction this vocabulary exists to keep and the one a reader is likeliest
#: to flatten.
#: **Each of the four is worded about the channels it names and not about the
#: package**, which is a correction rather than a nicety. An earlier draft ended
#: "so this run established no licence for this package", and on a sweep holding
#: one determinate channel beside one unreadable one that sentence is false: a
#: channel did establish one, and the row that reduced to `unknown` because of the
#: *other* channel was asserting the opposite of the truth in the one field a
#: reviewer has to distinguish four kinds of `unknown` by. What established a
#: licence, where anything did, is named by `ESTABLISHED_ELSEWHERE_DETAIL` or by
#: `DISAGREEING_CHANNELS_DETAIL` beside these.
#:
#: They take `{findings}` rather than one finding because several channels may
#: have met the same fault and only one of them can be the referenced row: which
#: one that is depends on primary-key order, so a line naming only it would report
#: whichever the sweep happened to insert first. See `_unknown_lines`.
UNESTABLISHED_LICENCE_DETAIL: Final[str] = (
    "the licence evidence current at this run's cut-off records that the channel(s) at finding(s) {findings} "
    "established no licence -- see each finding's own detail, which says whether the channel stated none or "
    "stated one this product will not normalize without guessing. Unknown rather than manual review, which "
    "would claim the licence is known and only the rule is missing, and never allowed"
)

#: What the row says about a channel that could not be read.
UNREADABLE_CHANNEL_DETAIL: Final[str] = (
    "the licence evidence current at this run's cut-off records that the channel(s) at finding(s) {findings} "
    "could not be read -- see each finding's own detail -- so what those channels would have stated is not "
    "known; unknown rather than a package with no restrictions, and never allowed"
)

#: What the row says about a channel that does not serve the package.
#:
#: Reachable only where **every** channel answered that way, because a channel
#: that does not carry the package takes no part in the reduction at all: see
#: `contributing_findings` and the module docstring.
UNSERVED_PACKAGE_DETAIL: Final[str] = (
    "the licence evidence current at this run's cut-off records that the channel(s) at finding(s) {findings} "
    "do not serve this package at all, and no other channel answered -- which is an absence from those "
    "channels rather than a package with no licence, so this run established none for it"
)

#: What the row says when a determinate finding carries no expression at all.
#:
#: `license_findings`' own biconditional forbids that row, so reaching it means
#: something went round the table's constraint -- and the answer is `unknown`
#: with the fault on the record, never `allowed` and never `manual_review`, both
#: of which would claim a licence had been established. Recorded rather than
#: raised, on exactly the terms an unreadable KEV state is recorded one domain
#: over: a refusal costs this package its currency, feedstock and vulnerability
#: rows too.
BLANK_EXPRESSION_DETAIL: Final[str] = (
    "the licence evidence current at this run's cut-off records finding(s) {findings} as normalized while "
    "stating no expression at all, which license_findings' own constraint forbids -- so those channels left "
    "nothing for a rule to name. Unknown rather than manual review, and never allowed"
)

#: The order the four lines above are stated in, so a sweep meeting two kinds of
#: nothing writes them the same way on every replay.
#:
#: A tuple of *sentences* rather than of states, so the mapping from a finding to
#: its line is written once, in `_unknown_kind`, and this declares only the order.
#: It is not a precedence order and ranks nothing: every kind it holds reduces to
#: the same `unknown`.
UNKNOWN_KINDS: Final[tuple[str, ...]] = (
    UNREADABLE_CHANNEL_DETAIL,
    UNSERVED_PACKAGE_DETAIL,
    BLANK_EXPRESSION_DETAIL,
    UNESTABLISHED_LICENCE_DETAIL,
)

#: What the row says when a channel did establish a licence and the row's own
#: outcome rests on something else.
#:
#: The other half of the `unknown` correction. A sweep of one determinate channel
#: and one unreadable one reduces to `unknown`, references the unreadable row, and
#: would otherwise carry no sign at all that a licence was established -- the
#: disagreement line cannot fire, because one expression is not a disagreement. So
#: the row names it: this outcome is about the channels it referenced, and not a
#: claim that nothing was stated anywhere.
ESTABLISHED_ELSEWHERE_DETAIL: Final[str] = (
    "a channel current at this run's cut-off did establish a licence ({expressions}) -- its own row is on "
    "license_findings, one row per channel -- so this outcome is about the channel(s) named above and is not a "
    "claim that no channel stated a licence"
)

#: What the row says when the channels current at the cut-off state different
#: licences.
#:
#: The outcome is the worst rank any of them yields, which is what "disagreement
#: never resolves upward" comes to, and the line names the expressions so a
#: reviewer can see the disagreement without opening four evidence rows. It is
#: added *beside* whatever else the row has to say rather than instead of it: a
#: package whose channels disagree and whose worst licence no rule names needs
#: both sentences.
DISAGREEING_CHANNELS_DETAIL: Final[str] = (
    "the channels current at this run's cut-off state different licences ({expressions}), so this row carries "
    "the least permissive outcome the reduction yields over everything they established and everything they "
    "failed to: disagreement never resolves upward. Each channel's own statement is on license_findings, one "
    "row per channel"
)

#: The operator whose operands all bind at once, and therefore the only one this
#: pass decomposes.
#:
#: Spelled here rather than taken from `collectors/spdx.py`'s `OPERATORS`, which
#: is a *frozenset*: selecting one member of it by name would be this string again
#: with a lookup wrapped round it, and `CPM-SECURITY-S05`'s Never list forbids
#: changing a collector to declare it there instead. What keeps the two reconciled
#: is a case, which is what would fail if that module ever stopped recognising
#: `AND` -- at which point no evidence row could carry a conjunction and this would
#: be dead.
CONJUNCTION: Final[str] = "AND"

#: The fewest tokens a compound expression can have: an operand, an operator and a
#: second operand. Named for the reason `collectors/spdx.py` names its own copy --
#: a bare `3` at the comparison reads as an arbitrary bound rather than as the
#: shape of the smallest expression.
_SHORTEST_COMPOUND: Final[int] = 3

#: The dispositions a rule may state that rank *worse than not knowing*, which are
#: exactly the ones one operand of a conjunction may impose on the whole
#: expression.
#:
#: Derived from the precedence order rather than listed, so "restrictive" means
#: "ranked below `unknown`" by construction rather than by this module's opinion.
#: The half that matters is the exclusion: `allowed` sits on the other side of
#: `unknown` and can therefore never be reached by decomposition, whatever a
#: future disposition does to the middle of the order.
RESTRICTIVE_DISPOSITIONS: Final[tuple[str, ...]] = tuple(
    disposition
    for disposition in RULE_DISPOSITIONS
    if LICENSE_PRECEDENCE.index(disposition) < LICENSE_PRECEDENCE.index(LICENSE_STATUS_UNKNOWN)
)


class LicensePolicyError(ValueError):
    """The licence pass met evidence or an argument it cannot compute from.

    A `ValueError` subclass, matching `policies/currency.py`'s
    `CurrencyPolicyError`, `policies/feedstock.py`'s `FeedstockPolicyError`,
    `policies/vulnerability.py`'s `VulnerabilityPolicyError`,
    `core/policy.py`'s `PolicyPassError` and `core/outcomes.py`'s
    `OutcomeVocabularyError`: every "this is unusable" in this product is a
    `ValueError`, so a caller catching one catches them all.

    **`policies/parameters.py` deliberately does not raise this.** A refusal
    about the reviewed parameter file is an `ImproperlyConfigured`, because it
    sends an operator to a file they can edit rather than to evidence they
    cannot. Every fault a *rule set* can carry is refused there, at the read, and
    none of them reaches this class -- a version that records **no** rule set is
    not a fault at all, and derives `manual_review` with the reason on the row.
    See `LicensePass._rules` and the module docstring.
    """


def _require_aware(cutoff: datetime) -> None:
    """Refuse a naive cut-off before anything is read as of it.

    Refused rather than converted, on the same terms `snapshot_as_of` refuses
    one: there is no offset to convert from, `USE_TZ` is on so Django would read
    it as if it were UTC, and a cut-off silently shifted by the reader's offset
    selects a different evidence set on every replay -- which is the opposite of
    what `CPM-FR-22` promises.

    Args:
        cutoff: The instant the read is bound by.

    Raises:
        LicensePolicyError: When the cut-off is naive.

    """
    if not is_aware(cutoff):
        message = (
            f"the licence findings cannot be read as of the naive cutoff {cutoff!r}. Every instant comes from "
            f"a Clock, which always answers in UTC (CPM-AD-26); a naive value has no offset to interpret, so "
            f"the read would be silently shifted by whichever offset the reader happened to be in and the "
            f"replay CPM-FR-22 promises would return a different set each time."
        )
        raise LicensePolicyError(message)


def current_findings(*, package_id: int, cutoff: datetime) -> tuple[LicenseFinding, ...]:
    """Return every licence finding of the newest sweep at or before a cut-off.

    **A sweep rather than a row**, on exactly the terms
    `policies/vulnerability.py`'s equivalent states. `license_findings` holds one
    row per monitored channel, so a package four channels serve has four rows;
    every row of one collection carries that run's single instant, so "the
    licence evidence current at the cut-off" is every row sharing the newest
    instant at or before it. Taking one row would reduce four channels to
    whichever the database returned first, and on this table that is the
    difference between seeing a disagreement and not knowing there was one.

    Two queries rather than one, deliberately. A single query cannot ask for
    "every row carrying the maximum of a column" without a window function or a
    correlated subquery, and both are a query plan this story would then own
    across two backends; the instant is one indexed read on
    `(package, -observed_at)` -- `collectors/models.py`'s `LICENSE_READ_INDEX` --
    and the rows are a second on the same index.

    Args:
        package_id: The package being asked about, by the integer primary key
            `CPM-AD-3` fixes.
        cutoff: The instant to read as of, aware. `CPM-AD-21` makes it the
            `finished_at` of a completed collection run, so a pass never reads
            evidence written by a run that is still `running`.

    Returns:
        The sweep's rows, by ascending primary key so a replay reads them in the
        same order, or empty where the package had no licence evidence by then.
        Empty is not an error -- a cut-off earlier than a package's first
        observation is an ordinary question, and its answer is `unknown`.

    Raises:
        LicensePolicyError: When `cutoff` is naive.

    """
    _require_aware(cutoff)
    observed = (
        LicenseFinding.objects.filter(package_id=package_id, observed_at__lte=cutoff)
        .order_by(*READ_ORDERING)
        .values_list("observed_at", flat=True)
        .first()
    )
    if observed is None:
        return ()
    return tuple(LicenseFinding.objects.filter(package_id=package_id, observed_at=observed).order_by(WITHIN_A_SWEEP))


def normalized_expression(finding: LicenseFinding) -> str:
    """Return the normalized SPDX expression one finding states, or `""`.

    Stripped, because `normalized_license` is stored text and a stored line
    carrying surrounding whitespace is the same expression -- a comparison that
    missed it would route a licence a rule *does* name to `manual_review`, which
    is the safe direction and still wrong.

    Args:
        finding: The evidence row.

    Returns:
        The expression, or `""` where the row states none. Blank means the row is
        not determinate, or is a determinate row `license_findings`' own
        biconditional should have refused.

    """
    return finding.normalized_license.strip()


def contributing_findings(findings: Sequence[LicenseFinding]) -> tuple[LicenseFinding, ...]:
    """Return the findings that take part in the reduction.

    **Every row bar a channel that does not serve the package.** `not_found` is
    not missing information about a licence -- the package is not there -- so
    that channel has said nothing, exactly as a channel stating a blank
    expression has, and `stated_expressions` drops that one for the same reason.
    Counting it would put an `unknown` vote into the reduction for every package
    the monitored channels do not all carry, which would outrank the
    `manual_review` and the `allowed` a serving channel actually supported. See
    the module docstring for why `error` is emphatically not the same case.

    This only ever removes an `unknown` vote, so it cannot make an outcome
    milder than `unknown`: `forbidden` and `restricted` still win from any
    channel that states them.

    Args:
        findings: The findings current at the cut-off.

    Returns:
        The findings that vote, possibly none -- which is a package no monitored
        channel serves, and reduces to `unknown` because there is nothing to
        reduce.

    """
    return tuple(finding for finding in findings if finding.state != LICENSE_NOT_FOUND)


def referenced_findings(findings: Sequence[LicenseFinding]) -> tuple[LicenseFinding, ...]:
    """Return the findings a derived row may name and account for.

    The contributing ones, and the absences where there is nothing else. That
    fallback changes no outcome -- a sweep of nothing but `not_found` rows
    reduces to `unknown` whether those rows are dropped or reduced, because
    `unknown` is what each of them yields and what an empty reduction yields --
    and it exists so the row can still say *which* nothing it met, which is the
    matrix's "only a `not_found` row" and is what `UNSERVED_PACKAGE_DETAIL` is
    for.

    Args:
        findings: The findings current at the cut-off.

    Returns:
        The findings a row may reference, possibly none.

    """
    return contributing_findings(findings) or tuple(findings)


def rule_for(expression: str, *, rules: Sequence[LicenseRule]) -> LicenseRule | None:
    """Return the recorded rule naming one normalized expression, or `None`.

    **Case-folded on both sides, and whole.** SPDX identifiers are mixed case and
    a reviewer writes them as SPDX spells them -- `Apache-2.0`, `GPL-3.0-only` --
    so the file records the reviewer's spelling and this comparison folds it
    rather than demanding a lowercase file. Whole, because a compound expression
    is a compliance question rather than a string operation: see the module
    docstring.

    `policies/parameters.py` refuses a rule set naming one expression twice, so
    "the first rule that names it" and "the rule that names it" are the same
    thing here, and the loop's order carries no meaning a reviewer has to know.

    Args:
        expression: The normalized expression a finding states.
        rules: The rules this run's policy version records, possibly none.

    Returns:
        The rule, or `None` where no rule names that expression -- which includes
        every expression when the rule set is empty, and a blank expression
        always, because a recorded rule can never name nothing.

    """
    if not expression:
        return None
    folded = expression.casefold()
    for rule in rules:
        if rule.expression.casefold() == folded:
            return rule
    return None


def conjoined_operands(expression: str) -> tuple[str, ...]:
    """Return the operands of an `AND` compound, or `()` where it is not one.

    **The only expression this pass takes apart.** `collectors/spdx.py` produces
    a flat expression of alternating operands and one repeated operator,
    separated by single spaces, so this reads exactly that shape and nothing
    else: an even token count, a lone token, a mixed or unrecognised operator, or
    a doubled space all mean the string is not a conjunction this module built,
    and none of them is taken apart.

    Split on a single space rather than on whitespace, deliberately: a normalized
    expression carries single spaces, and a string with a doubled space is one
    `rule_for` could never match either, so reading it as a conjunction would
    decompose something the whole-expression comparison had already declined.

    The operator match case-folds, because the comparison in `rule_for` does: a
    rule spelled `mit and gpl-3.0-only` matches the evidence `MIT AND
    GPL-3.0-only`, so an operand lookup that insisted on upper case would refuse
    to decompose an expression a rule *would* have matched whole.

    Args:
        expression: The normalized expression a finding states.

    Returns:
        The operands, in the order stated, or `()` where the expression is not a
        conjunction -- which includes every single identifier and every `OR`
        compound. A disjunction is never decomposed: see the module docstring.

    """
    tokens = expression.split(" ")
    if len(tokens) < _SHORTEST_COMPOUND or len(tokens) % 2 == 0:
        return ()
    if {operator.casefold() for operator in tokens[1::2]} != {CONJUNCTION.casefold()}:
        return ()
    return tuple(tokens[0::2])


def restrictive_rule(expression: str, *, rules: Sequence[LicenseRule]) -> LicenseRule | None:
    """Return the least permissive rule naming one operand of a conjunction, or `None`.

    **Restrictive only, and that is the whole safety argument.** A conjunction
    binds every one of its operands at once, so a rule forbidding one of them
    forbids the compound -- that is what `AND` means rather than a judgement
    about it. The converse is not true and is not done: a rule *allowing* one
    operand says nothing about the obligations the others carry, so no rule
    considered here can produce `allowed`, and `RESTRICTIVE_DISPOSITIONS` is
    derived from the precedence order so that the exclusion holds by
    construction.

    Args:
        expression: The normalized expression a finding states.
        rules: The rules this run's policy version records.

    Returns:
        The worst-ranked rule naming an operand `forbidden` or `restricted`, or
        `None` where the expression is not a conjunction, no rule names an
        operand, or every rule that does permits it.

    """
    named = [
        rule
        for operand in conjoined_operands(expression)
        if (rule := rule_for(operand, rules=rules)) is not None and rule.disposition in RESTRICTIVE_DISPOSITIONS
    ]
    if not named:
        return None
    return min(named, key=lambda rule: LICENSE_PRECEDENCE.index(rule.disposition))


def deciding_rule(expression: str, *, rules: Sequence[LicenseRule]) -> LicenseRule | None:
    """Return the rule one normalized expression comes to, whole or by conjunction.

    The one place the two lookups are ordered, so `finding_verdict` and
    `matched_rule` cannot disagree about which rule decided a row -- and they
    must not, because `A_RULED_OUTCOME_NAMES_THE_RULE_THAT_PRODUCED_IT` refuses a
    ruled outcome that names none, so a verdict reached by decomposition whose
    rule lookup did not decompose would be refused by the database.

    Whole first: a rule naming the compound is the reviewer's own statement about
    it, and decomposition is what happens only when there is none.

    Args:
        expression: The normalized expression a finding states.
        rules: The rules this run's policy version records.

    Returns:
        The rule, or `None` where no rule reaches this expression -- which is
        `manual_review`.

    """
    return rule_for(expression, rules=rules) or restrictive_rule(expression, rules=rules)


def finding_verdict(finding: LicenseFinding, *, rules: Sequence[LicenseRule]) -> str:
    """Return what one channel's licence statement comes to under this run's rules.

    Four values and no more. A determinate row whose expression a rule reaches
    takes **that rule's own recorded disposition** -- which is the whole of how
    `allowed` is reached, and there is deliberately no branch here that spells it:
    the value comes out of the file. A determinate row no rule reaches is
    `manual_review`. A determinate row stating no expression, and every sentinel
    state, is `unknown`.

    "Reaches" rather than "names" because of `deciding_rule`: a rule naming the
    whole expression, or -- for a conjunction alone, and only where its
    disposition is `forbidden` or `restricted` -- a rule naming one of its
    operands. A rule can never permit an expression it does not name whole.

    **A `not_found` row still has a verdict here, and it is `unknown`.** What
    that channel does not do is *vote*: `contributing_findings` drops it before
    the reduction, and this function is the per-row reading that
    `referenced_findings` and the row's own account still need.

    Args:
        finding: The evidence row.
        rules: The rules this run's policy version records.

    Returns:
        A `PackageLicenseOutcome` value: one of `RULE_DISPOSITIONS`,
        `manual_review`, or `unknown`.

    Raises:
        LicensePolicyError: When the row carries a state outside `LicenseOutcome`
            -- including `not_applicable`, which the table refuses outright
            because every package a monitored channel could serve is licensed
            under something. `choices` is a form rule Django does not enforce on
            `save()`, so such a row is reachable; reading it as an absence would
            let a value nobody recognises decide a compliance verdict, and
            reading it as anything else would be worse.

    """
    state = finding.state
    if state == NORMALIZED:
        expression = normalized_expression(finding)
        if not expression:
            return LICENSE_STATUS_UNKNOWN
        rule = deciding_rule(expression, rules=rules)
        return MANUAL_REVIEW if rule is None else rule.disposition
    if state in LICENSE_VOCABULARY and state != LICENSE_NOT_APPLICABLE:
        return LICENSE_STATUS_UNKNOWN
    message = (
        f"the licence finding {finding.pk} carries state {state!r}, which this pass cannot read as a verdict "
        f"about the package. The states a finding may hold are {sorted(LICENSE_VOCABULARY)} less "
        f"{LICENSE_NOT_APPLICABLE!r}, which license_findings refuses outright because every package a "
        f"monitored channel could serve is licensed under something. A compliance outcome derived from a value "
        f"outside that set would be a claim about this package's licence resting on something nothing in this "
        f"product recognises."
    )
    raise LicensePolicyError(message)


def license_outcome(findings: Sequence[LicenseFinding], *, rules: Sequence[LicenseRule]) -> str:
    """Reduce the current findings to the one licence outcome for the package.

    One line and one filter. The reduction is `policies/outcomes.py`'s: the order
    is declared as data beside the vocabulary it ranks and `worst_license`
    applies it. Both the ranking and why `allowed` is last in it are argued
    there, in the one place they are stated.

    The filter is `contributing_findings`, which drops a channel that does not
    serve the package before anything is ranked: see there and the module
    docstring for why an absence is not a vote, and why that is the one thing it
    changes.

    Args:
        findings: The licence findings current at the cut-off, possibly none.
        rules: The rules this run's policy version records.

    Returns:
        A `PackageLicenseOutcome` value. `unknown` for no findings at all and for
        a sweep of nothing but absences, which is never clean and emphatically
        never `allowed`.

    Raises:
        LicensePolicyError: When a finding carries an unreadable state.

    """
    return worst_license(finding_verdict(finding, rules=rules) for finding in contributing_findings(findings))


def supporting_finding(
    findings: Sequence[LicenseFinding],
    outcome: str,
    *,
    rules: Sequence[LicenseRule],
) -> LicenseFinding | None:
    """Return the finding whose own verdict is the one the row carries.

    The first in read order, which is ascending primary key, so a replay names
    the same row -- and *not* simply the first row given, which is why this loop
    exists: a package one channel says is `MIT` and another says is `GPL-3.0-only`
    must name the channel whose verdict the row actually carries, or the derived
    row would reference evidence contradicting its own column. "First" is also
    what makes two channels supporting one verdict reproducible: whichever the
    database inserted first is named on every replay.

    Over `referenced_findings` rather than over every row given, so the row does
    not name a channel that took no part in the reduction: a sweep of one
    unreadable channel and one that does not serve the package reduces to
    `unknown` because of the *unreadable* one, and referencing the absence
    instead would point a reviewer at the wrong fault.

    What the reference is for is that a verdict names an observation a reader can
    open -- `CPM-FR-16`'s "the evidence supporting it is stored with the result",
    applied to this domain.

    Args:
        findings: The findings current at the cut-off.
        outcome: The outcome the row will carry.
        rules: The rules this run's policy version records.

    Returns:
        The supporting row, or `None` where no finding supports that outcome --
        which is exactly the package with no findings at all, whose outcome is
        `unknown`.

    Raises:
        LicensePolicyError: When a finding carries an unreadable state.
            Unreachable through `LicensePass.evaluate`, which has already reduced
            the same rows, and stated rather than swallowed.

    """
    for finding in referenced_findings(findings):
        if finding_verdict(finding, rules=rules) == outcome:
            return finding
    return None


def matched_rule(
    supporting: LicenseFinding | None,
    *,
    outcome: str,
    rules: Sequence[LicenseRule],
) -> LicenseRule | None:
    """Return the rule that produced this row's outcome, or `None`.

    **Guarded by the outcome rather than only by the lookup**, and that is the
    half worth reading twice. A rule is returned only for an outcome a rule can
    state, so `matched_rule` on a `manual_review` or an `unknown` row is
    structurally `None` rather than incidentally so -- which is what makes
    `A_MATCHED_RULE_ONLY_WHERE_A_RULE_DECIDED` a constraint the pass cannot
    violate by accident, instead of one it merely happens to satisfy.

    Args:
        supporting: The finding the outcome rests on, or `None`.
        outcome: The outcome the row will carry.
        rules: The rules this run's policy version records.

    Returns:
        The rule the supporting finding's expression comes to -- named whole, or
        naming one operand of a conjunction restrictively -- or `None` where no
        rule decided this row. `deciding_rule` is what `finding_verdict` used, so
        the outcome and the rule the row names cannot come from two readings of
        one expression.

    """
    if supporting is None or outcome not in RULE_DISPOSITIONS:
        return None
    return deciding_rule(normalized_expression(supporting), rules=rules)


def stated_expressions(findings: Sequence[LicenseFinding]) -> tuple[str, ...]:
    """Return the distinct normalized expressions the current channels state.

    Args:
        findings: The findings current at the cut-off.

    Returns:
        The expressions, sorted, with blanks dropped -- a channel that stated no
        licence has not disagreed with one that did, it has said nothing, and
        counting it would report a disagreement on every package one channel
        could not answer for. Sorted so the line a replay writes is the same
        line.

    """
    # `dict.fromkeys` rather than a set, so distinctness and order are two
    # separate decisions rather than one: read order is what survives the
    # de-duplication, and `sorted` is then the only thing that decides the line.
    # Over a set, dropping the sort would leave an order that depends on the
    # process's string hash seed -- reproducible within one run, different between
    # two, which is the worst way for a replay to differ.
    return tuple(
        sorted(dict.fromkeys(expression for finding in findings if (expression := normalized_expression(finding)))),
    )


def license_detail(
    findings: Sequence[LicenseFinding],
    *,
    outcome: str,
    supporting: LicenseFinding | None,
    rules: Sequence[LicenseRule],
    version: str,
) -> str:
    """Return the row's account of its outcome, or `""` where the columns say it.

    Populated on exactly the shapes whose reason is not readable off the row's
    own columns, and empty everywhere else -- the rule every table in this
    product applies to its own `detail`: an explanation of an unremarkable row is
    noise.

    Four shapes need a line. A `manual_review`, because the column cannot say
    whether no policy has been recorded at all or a recorded policy does not
    cover this licence, and those are different pieces of work for different
    people. An `unknown` that has evidence behind it, because that row looks
    exactly like a row for a package nobody looked at while meaning something
    quite different -- and it says *which* kinds of nothing it met, one line per
    kind, because the referenced row is the first in read order rather than the
    most alarming and a reader cannot infer the rest from it. A ruled outcome no
    rule named whole, because that is a conjunction one operand decided and three
    of the row's columns otherwise have to be reconciled by guesswork. And the
    expressions the channels did state, where the row's own outcome does not rest
    on one of them or where there is more than one.

    **The `unknown` lines are about the channels they name and not about the
    package**, which is what an earlier draft got wrong: a sweep of one
    determinate channel and one unreadable one reduces to `unknown`, and a line
    saying "this run established no licence for this package" would then be
    asserting the opposite of the truth in the one field that distinguishes the
    kinds. What was established is named beside them.

    A row a rule decided whole gets no line: the outcome, the matched rule and
    the referenced finding say between them what happened, and there is nothing
    left to explain.

    Args:
        findings: The findings current at the cut-off.
        outcome: The outcome the row carries.
        supporting: The finding the outcome rests on, or `None`.
        rules: The rules this run's policy version records.
        version: The policy version, named in the line so a reader can go and
            look at the entry that produced it.

    Returns:
        One line per fact, joined, or `""`.

    Raises:
        LicensePolicyError: When a finding carries an unreadable state.
            Unreachable through `LicensePass.evaluate`, which has already reduced
            the same rows.

    """
    lines: list[str] = []
    if outcome == MANUAL_REVIEW and supporting is not None:
        expression = normalized_expression(supporting)
        lines.append(
            NO_RULE_SET_DETAIL.format(version=version, key=RULES_KEY, expression=expression)
            if not rules
            else NO_MATCHING_RULE_DETAIL.format(version=version, rules=len(rules), expression=expression),
        )
    elif outcome == LICENSE_STATUS_UNKNOWN:
        lines.extend(_unknown_lines(findings, rules=rules))
    elif supporting is not None and (operand := _decomposed_rule(supporting, rules=rules)) is not None:
        lines.append(
            CONJOINED_OPERAND_DETAIL.format(
                expression=normalized_expression(supporting),
                operand=operand.expression,
                disposition=outcome,
            ),
        )
    stated = stated_expressions(findings)
    if len(stated) > 1:
        lines.append(DISAGREEING_CHANNELS_DETAIL.format(expressions=list(stated)))
    elif stated and (supporting is None or not normalized_expression(supporting)):
        lines.append(ESTABLISHED_ELSEWHERE_DETAIL.format(expressions=list(stated)))
    return " ".join(lines)


def _decomposed_rule(supporting: LicenseFinding, *, rules: Sequence[LicenseRule]) -> LicenseRule | None:
    """Return the operand rule that decided a conjunction no rule names whole, or `None`.

    Args:
        supporting: The finding the outcome rests on.
        rules: The rules this run's policy version records.

    Returns:
        The rule, or `None` where a rule named the whole expression -- in which
        case there is nothing to explain -- or where no rule decided this row at
        all.

    """
    expression = normalized_expression(supporting)
    if rule_for(expression, rules=rules) is not None:
        return None
    return restrictive_rule(expression, rules=rules)


def _unknown_kind(finding: LicenseFinding) -> str:
    """Return the line one finding that established nothing is reported under.

    Four kinds and four sentences, because the work each calls for differs: a
    channel that could not be read is an operational fault, a channel that does
    not serve the package is an ordinary absence, a determinate row with no
    expression is a broken write, and everything else is a licence this product
    would not normalize without guessing -- which is a review item the evidence
    row itself explains.

    Args:
        finding: A finding whose own verdict is `unknown`.

    Returns:
        One of `UNKNOWN_KINDS`, unformatted.

    """
    if finding.state == LICENSE_ERROR:
        return UNREADABLE_CHANNEL_DETAIL
    if finding.state == LICENSE_NOT_FOUND:
        return UNSERVED_PACKAGE_DETAIL
    if finding.state == NORMALIZED:
        return BLANK_EXPRESSION_DETAIL
    return UNESTABLISHED_LICENCE_DETAIL


def _unknown_lines(findings: Sequence[LicenseFinding], *, rules: Sequence[LicenseRule]) -> list[str]:
    """Return one line per kind of nothing the referenced channels established.

    **Every kind met, and not only the referenced row's.** `supporting_finding`
    takes the first row in primary-key order, so a single-valued account of a
    sweep holding an unreadable channel *and* a channel that stated something
    unrecognisable reports whichever the collector happened to insert first, and
    silently drops the other -- which is an insertion order deciding what an
    operator is told to go and fix.

    Args:
        findings: The findings current at the cut-off.
        rules: The rules this run's policy version records.

    Returns:
        One formatted line per kind, in `UNKNOWN_KINDS`' order, each naming every
        finding of that kind in read order; empty where the package has no
        evidence at all, which is the one `unknown` whose two empty columns say
        it already.

    Raises:
        LicensePolicyError: When a finding carries an unreadable state.

    """
    met: dict[str, list[int]] = {}
    for finding in referenced_findings(findings):
        if finding_verdict(finding, rules=rules) == LICENSE_STATUS_UNKNOWN:
            met.setdefault(_unknown_kind(finding), []).append(finding.pk)
    return [line.format(findings=", ".join(str(pk) for pk in met[line])) for line in UNKNOWN_KINDS if line in met]


class LicensePass(PolicyPass):
    """`CPM-FR-18` as a `PolicyPass`: read one evidence table, apply a rule set, write one row.

    Four declarations and two methods. The derived table is `PackageLicense` and
    there is **no** rollup column: the rollup offers none for this domain and
    `CPM-AD-21` says no pass writes the health rollup, so `contributes` is empty
    and `core/policy.py` records that an empty contribution is legitimate.
    `tests/passes.py`'s synthetic rollup declares a `licence_status` column
    precisely because the real one does not, and this story does not add it.

    **It overrides `prepare` for the reason `FeedstockPresencePass` and
    `VulnerabilityPass` do.** The reviewed parameter file and the run's version
    are a run-wide fact and their failure is a run-wide failure -- ten thousand
    identical tracebacks for a condition knowable before the loop, and a run that
    finalizes `failed` having written nothing. A version that records no *rule
    set* is emphatically not such a failure and is not one anywhere else either:
    see `_rules`.
    """

    name: ClassVar[str] = POLICY_NAME
    derived_model: ClassVar[type[models.Model] | None] = PackageLicense
    contributes: ClassVar[tuple[str, ...]] = ()

    #: The parameter set this run applies, established once by `prepare`.
    #:
    #: An instance attribute rather than a lookup per package, on exactly the
    #: terms `VulnerabilityPass.parameters` is one: `core/policy_run.py` builds
    #: one instance per run, so the value cannot leak between runs, and a pass
    #: instance that had somehow reached `evaluate` without a run is what this
    #: default makes visible rather than silent.
    parameters: PolicyParameters | None = None

    def prepare(self, *, policy_run: PolicyRun, evidence_cutoff: datetime) -> None:
        """Establish the parameter set this run applies, once, before any package.

        The version is a run-wide fact and a version the reviewed file does not
        record is a run-wide failure: the run finalizes `failed`, nothing is
        written, and the message names the file and the version.
        `FeedstockPresencePass.prepare` argues it at length and this is the same
        argument, not a third one.

        Args:
            policy_run: The run about to execute. Its `policy_version` is what
                the parameter set is looked up by, which is what makes the rule
                set versioned rather than merely external.
            evidence_cutoff: Accepted and unused. The parameter set is chosen by
                version alone.

        Raises:
            PolicyParameterError: When the run's policy version records no
                parameters, or the reviewed file cannot be read.

        """
        self.parameters = parameters_for(policy_run.policy_version)

    def evaluate(
        self,
        package: Package,
        *,
        policy_run: PolicyRun,
        evidence_cutoff: datetime,
    ) -> Mapping[str, str]:
        """Judge one package's licence and write its derived row.

        Called once per package, inside that package's transaction
        (`CPM-AD-23`), so a refusal here rolls back **everything this run did for
        this package** -- its currency, feedstock and vulnerability rows as well
        as this one, and its rollup row with them -- and leaves every other
        package's committed. That is why so little in here refuses: see the
        module docstring.

        **Every package gets a row**, including one with no evidence and no
        inventory mapping: the outcome is `unknown`, no rule is named, and the
        absence of a row would read as never-evaluated instead.

        Args:
            package: The package to judge.
            policy_run: The run this evaluation belongs to. Its version and its
                cut-off are copied onto the row, where together with the package
                it is `CPM-AD-21`'s key.
            evidence_cutoff: The instant to read evidence as of. Nothing here
                reads the current time.

        Returns:
            An empty mapping. This pass contributes no rollup column, which
            `core/policy.py` records as legitimate and `CPM-AD-21` requires.

        Raises:
            LicensePolicyError: When a licence finding carries a state outside
                `LicenseOutcome`, when the cut-off is naive, and when this pass
                was never prepared -- which is a caller that bypassed the
                orchestration. Deliberately **not** for a version that records no
                rule set: a raise here rolls back this package's other three
                domains' rows too (`CPM-AD-23`), and the module docstring argues
                at length why that would be the wrong trade.

        """
        rules = self._rules()
        findings = current_findings(package_id=package.pk, cutoff=evidence_cutoff)
        outcome = license_outcome(findings, rules=rules)
        supporting = supporting_finding(findings, outcome, rules=rules)
        rule = matched_rule(supporting, outcome=outcome, rules=rules)
        # Written with one keyword per column rather than through a `defaults`
        # mapping, on exactly the terms `policies/currency.py` states:
        # `tests/unit/django_apps/test_derived_status_writability_audit.py` reads
        # keyword names, so the mapping form would take this write out of that
        # audit's view -- which is the `**kwargs` dodge that module names. The
        # visible form plus a recorded exemption is the honest shape.
        PackageLicense.objects.create(
            package=package,
            policy_run=policy_run,
            license_outcome=outcome,
            matched_rule="" if rule is None else rule.expression,
            policy_version=policy_run.policy_version,
            evidence_cutoff=evidence_cutoff,
            license_finding=supporting,
            detail=license_detail(
                findings,
                outcome=outcome,
                supporting=supporting,
                rules=rules,
                version=policy_run.policy_version,
            ),
        )
        return {}

    def _rules(self) -> tuple[LicenseRule, ...]:
        """Return the rule set this run's policy version records, or none.

        **A version that records no rule set is not an error**, and that is the
        defect `CPM-SECURITY-S04`'s review found in its sibling and this method
        exists not to repeat. The condition is run-wide, so `prepare` looks like
        a refusal's home, and the argument against putting it there was that
        failing the run would take the other domains' rows down with it. That
        argument is correct about the harm and wrong about the containment:
        `core/policy_run.py` wraps every pass for one package in one
        `transaction.atomic()`, because `CPM-AD-23`'s atomic unit is one package
        and not one pass. So raising per package rolls the other three domains'
        rows back exactly as `prepare` would have, package by package, and -- the
        condition being version-wide -- fails every package and finalizes the run
        `failed` rather than `partial`.

        There is also nothing here to protect. No run recorded at a version
        predating this pass ever carried a licence verdict, so refusing would
        break the replay of every historical run to preserve a licence replay
        that does not exist. And the state is not exceptional in any case: an
        unrecorded rule set and an empty one mean the same thing -- no rule names
        any licence -- which is what this component ships and what PRD Open
        Question 2 leaves it at.

        A **malformed** rule set is still refused, and is refused in
        `policies/parameters.py` at the read: a rule that is not a table, names
        nothing, states an unknown disposition, or names an expression a second
        rule also names. That is an operator error in a file somebody can edit,
        not a historical artifact, and it fails the whole file rather than one
        package.

        Returns:
            The rules this run's policy version records, in the file's order, or
            `()` where it records none. `()` is the shipped state and is the
            state `NO_RULE_SET_DETAIL` describes on the row.

        Raises:
            LicensePolicyError: When `prepare` was never called -- a caller
                driving this pass by hand. Unreachable through the
                orchestration, and stated rather than left as an `AttributeError`
                on `None`.

        """
        if self.parameters is None:
            message = (
                f"policy pass {POLICY_NAME!r} was asked to evaluate a package before its parameter set was "
                f"established. core/policy_run.py calls prepare() once per run, before the package loop; a "
                f"caller driving this pass directly has to do the same."
            )
            raise LicensePolicyError(message)
        return self.parameters.license_rules
