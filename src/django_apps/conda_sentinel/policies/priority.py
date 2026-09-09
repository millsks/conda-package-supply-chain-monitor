"""`CPM-FR-20`: which bucket a package is in, why it is there, and how it ranks.

The seventh policy pass, and the first that reads what the others concluded. Six
passes each answer one question about a package; this one turns those answers into
an ordered queue of work, and -- the half the requirement is actually about --
makes every assignment explain itself, so nobody has to open the rule set to know
why a package is `P1`.

**It reads six derived tables, and it is the only pass that reads any.** Every
other pass reads evidence. `core/policy.py` keeps the pass registry in
*declaration* order precisely so a later pass may read an earlier one's rows, and
`core/policy_run.py` makes it safe: the package is the outer loop, the passes run
inside it in declared order, and all seven share one `transaction.atomic()` per
package (`CPM-AD-23`). So by the time this pass runs, this package's six rows for
**this run** exist and are visible.

**Every read filters on the run as well as the package, and that is load-bearing.**
`policies/remediation.py` records the hazard: a verdict derived from another run's
rows would depend on two policy versions at once, and `CPM-FR-22`'s replay could
then be stated for neither. Filtering on `(package, policy_run)` -- which is
`CPM-AD-21`'s own key -- is what keeps one run's conclusions made entirely of that
run's rows.

**The engine ships and the content does not.** PRD Open Question 8 asks what seeds
the rule set and the score function and answers "both are undefined -- they encode
an organizational risk posture that does not exist yet", naming the question as
blocking this epic; `CPM-PRIORITY-S01`'s epic entry then constrains this story to
"the engine, the schema and the explainability fields -- not a seeded rule set". So
`policies/data/policy-parameters.toml` records an empty rule set and an empty score
function, and this pass puts every package in `unknown`.

**No bucket is assigned by default, and `p10` is the value that would have looked
harmless.** A version recording no rule set, a rule set that matches nothing, and a
package whose identity was never established all reach `unknown`. "Lowest priority"
reads as a considered answer; "we have not prioritised this" is the truth, and they
are different rows. `policies/models.py` puts a check constraint behind the
explanation so a bucket that arrives without one is refused by PostgreSQL.

**A score is never invented from a missing signal.** PRD Open Question 3b makes
`apps`, `platforms`, `downloads` and `versions` nullable and Appendix A.1 says blank
means missing and is never invented. A score that treated a missing signal as zero
would rank a package this product has observed nothing about *below* one it has
observed -- so a package missing a weighted signal gets **no** score, and the row
names the signal. Zero is a count; `NULL` is an absence.

**Rank is derived rather than stored, and `ranking_order` is the one derivation.**
`CPM-PRIORITY-S01`'s AC 1 asks that rank be derived from bucket and score and be
stable for a given policy run, and `CPM-AD-1` lists rank among the fields
*projected* from the rollup. A pass sees one package at a time, so an ordinal would
need a post-loop hook `core/policy.py` does not have; and a stored ordinal is a
third copy that can disagree with the two columns it came from. What ships instead
is one ordering, declared here, total by construction -- bucket, then score, then
the package key -- so two read surfaces cannot rank one run two ways.

**A version predating these parameters is a historical fact, not a
misconfiguration.** `policies/vulnerability.py` records the defect at length: a pass
that raised for such a version failed every package, took the other passes' rows
down with it and finalized the run `failed`, which is a `CPM-FR-22` regression
caused by registering a pass. A run at an older recorded version writes priority
rows carrying no bucket and saying so.

**It contributes one rollup column and writes none.** `CPM-AD-21` says no pass
writes `package_health`; this pass returns `priority_status` from `evaluate` and
`core/rollup.py` writes it, through `CPM-AD-4`'s confidence gate. The bucket is on
the rollup because that is the table a queue filters; the score, the rank and the
explanation are on `package_priority` because a contribution carries statuses and
nothing else.

**No work type.** `CPM-FR-21` is `CPM-PRIORITY-S02`'s, with its own closed set of
eight values, and it is derived *independently* of priority -- so nothing here
computes one and nothing here is shaped to make one easy to fold in.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

from conda_sentinel.collectors.models import snapshot_as_of
from conda_sentinel.core.clock import is_aware
from conda_sentinel.core.policy import PolicyPass
from conda_sentinel.policies.models import MAX_PRIORITY_SCORE
from conda_sentinel.policies.models import MIN_PRIORITY_SCORE
from conda_sentinel.policies.models import PackageCurrency
from conda_sentinel.policies.models import PackageFeedstockPresence
from conda_sentinel.policies.models import PackageLicense
from conda_sentinel.policies.models import PackagePriority
from conda_sentinel.policies.models import PackagePythonReadiness
from conda_sentinel.policies.models import PackageRemediation
from conda_sentinel.policies.models import PackageVulnerability
from conda_sentinel.policies.outcomes import PRIORITY_STATUS_UNKNOWN
from conda_sentinel.policies.parameters import parameters_for

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from django.db import models

    from conda_sentinel.collectors.models import InventorySnapshot
    from conda_sentinel.core.models import PolicyRun
    from conda_sentinel.identity.models import Package
    from conda_sentinel.policies.parameters import PolicyParameters
    from conda_sentinel.policies.parameters import PriorityRule

__all__ = [
    "DOMAIN_READERS",
    "MISSING_SIGNAL_DETAIL",
    "NO_MATCH_DETAIL",
    "NO_RULE_SET_DETAIL",
    "NO_SCORE_FUNCTION_DETAIL",
    "NO_SIGNALS_DETAIL",
    "POLICY_NAME",
    "RANKING_ORDER",
    "ROLLUP_COLUMN",
    "Assignment",
    "DomainReader",
    "PriorityPass",
    "PriorityPolicyError",
    "current_verdicts",
    "matching_rule",
    "ranking_order",
    "rule_label",
    "usage_score",
]

#: What this pass is called. It keys the pass registry, keys the rollup's
#: per-domain `policy_versions` map, and appears in every refusal message.
POLICY_NAME: Final[str] = "priority"

#: The rollup column this pass contributes (`CPM-AD-11`).
#:
#: Named here rather than spelled at the two places that need it -- the
#: `contributes` declaration and the mapping `evaluate` returns -- because
#: `core/policy.py` refuses a contribution the pass did not declare, and two
#: spellings of one column name would make that refusal fire on a column the pass
#: is producing perfectly well.
ROLLUP_COLUMN: Final[str] = "priority_status"


@dataclass(frozen=True, slots=True)
class DomainReader:
    """One earlier pass's derived table, and the column its verdict lives in.

    Frozen and slotted, holding only data: the table below is a declaration a
    reader checks against `PRIORITY_DOMAINS`, not machinery.

    Attributes:
        domain: The name a rule's `when` uses, which is also the name
            `policies/parameters.py` validates a rule against.
        model: The derived table to read.
        column: The field on that table holding the verdict.

    """

    domain: str
    model: type[models.Model]
    column: str


#: The six domains a rule may match on, each bound to the table and column that
#: answers it.
#:
#: **The domain names are `policies/parameters.py`'s**, so the file's validation
#: and this pass's reads cannot come to disagree about what `vulnerability_status`
#: means. `tests/unit/django_apps/test_priority_policy.py` reconciles this table
#: against `PRIORITY_DOMAINS` in both directions -- a domain the file accepts and
#: nothing reads would match nothing for ever, and a domain read here that the file
#: refuses would be unreachable.
#:
#: Ordered as the passes are declared in `policies/apps.py`, which is the order a
#: reader meets them everywhere else in this application.
DOMAIN_READERS: Final[tuple[DomainReader, ...]] = (
    DomainReader(domain="currency_status", model=PackageCurrency, column="overall_status"),
    DomainReader(
        domain="feedstock_presence_status",
        model=PackageFeedstockPresence,
        column="presence_status",
    ),
    DomainReader(domain="vulnerability_status", model=PackageVulnerability, column="vulnerability_status"),
    DomainReader(domain="license_outcome", model=PackageLicense, column="license_outcome"),
    DomainReader(domain="remediation_readiness", model=PackageRemediation, column="readiness_status"),
    DomainReader(domain="python_readiness", model=PackagePythonReadiness, column="readiness"),
)

#: How a run's assignments order, as the field names a queryset takes.
#:
#: **Total by construction, which is what "stable for a given policy run" needs.**
#: Bucket first, because that is the policy; score descending within it, because
#: `CPM-FR-20` says the score ranks *within* a bucket; and the package key last, so
#: two packages with one bucket and one score still have an order. Without the third
#: term the ordering would be stable only up to ties, and two read surfaces
#: paginating it would disagree about which of two equal packages comes first --
#: silently, and only on some pages.
#:
#: `-score` puts the higher score first, and `nulls_last` is not spelled here
#: because `ranking_order` builds the expression: a `NULL` score is an absence and
#: an unscored package sorts after every scored one in its bucket rather than
#: before them.
RANKING_ORDER: Final[tuple[str, ...]] = ("bucket", "-score", "package_id")

#: What a row says in its own words. Named so the row a run writes and the case
#: that reads it back cannot drift.
NO_RULE_SET_DETAIL: Final[str] = (
    "this run's policy version records no priority rule set, so no bucket was assigned. That is the shipped "
    "state: PRD Open Question 8 asks what seeds the rules and answers that they encode a risk posture that does "
    "not exist yet, so policies/data/policy-parameters.toml names no rule. This is emphatically not p10 -- a "
    "package nobody has prioritised is not a package somebody decided is unimportant"
)
NO_MATCH_DETAIL: Final[str] = (
    "no priority rule in this run's policy version matched this package's derived statuses, so no bucket was "
    "assigned. Rules are matched top down and the first match wins; a package none of them names reaches no "
    "bucket rather than the last one"
)
NO_SCORE_FUNCTION_DETAIL: Final[str] = (
    "this run's policy version records no score function, so no score was computed. A bucket may still have "
    "been assigned: CPM-FR-20's rules and its score are separate parameters and are read separately"
)
NO_SIGNALS_DETAIL: Final[str] = (
    "the inventory recorded no observation of this package at this run's cut-off, so there are no usage signals "
    "to score. An absence of an observation is not a package with no usage"
)
MISSING_SIGNAL_DETAIL: Final[str] = (
    "the inventory observation current at this run's cut-off records no value for the weighted signal(s) "
    "{signals}, so no score was computed. Blank means missing and is never invented (PRD Appendix A.1): a score "
    "that read a missing signal as zero would rank a package this product has observed nothing about below one "
    "it has"
)


class PriorityPolicyError(ValueError):
    """A priority evaluation was asked for something it cannot judge.

    One flat type, a `ValueError` subclass on the same terms every policy error in
    this application is.

    **It is raised for almost nothing.** `core/policy_run.py` wraps all seven passes
    for one package in one `transaction.atomic()`, so raising here rolls back that
    package's other six domains' rows. A naive cut-off and a pass that was never
    prepared are the two conditions worth that price: both are caller defects rather
    than facts about the package. An empty rule set, a rule that matches nothing, a
    missing usage signal and a version predating the parameters are all honest
    states this table records instead.
    """


@dataclass(frozen=True, slots=True)
class Assignment:
    """One package's priority, and everything the row needs to explain it.

    Attributes:
        bucket: The `PriorityBucket` value.
        description: What the bucket means, from the rule that matched, or blank.
        matched_rule: Which rule matched, by its position in the version's rule
            set, or blank.
        reason: Why the rule fires, from the rule that matched, or blank.
        score: The 1-100 score, or `None` where none was computed.
        detail: What the row says in its own words.

    """

    bucket: str
    description: str
    matched_rule: str
    reason: str
    score: int | None
    detail: str


def _require_aware(cutoff: datetime) -> None:
    """Refuse a naive cut-off before anything is read.

    Args:
        cutoff: The instant evidence is read as of.

    Raises:
        PriorityPolicyError: When it carries no timezone.

    """
    if not is_aware(cutoff):
        message = (
            f"a priority evaluation was asked to read as of {cutoff!r}, which carries no timezone. Every "
            f"observation instant in this product is aware (CPM-AD-26), so a naive cut-off would compare "
            f"against them silently."
        )
        raise PriorityPolicyError(message)


def current_verdicts(*, package_id: int, policy_run_id: int) -> dict[str, str]:
    """Return what the six earlier passes concluded about one package in this run.

    **Filtered on the run as well as the package**, which is `CPM-AD-21`'s own key
    and what keeps one run's priority made entirely of that run's conclusions. A
    read that took the newest row per package would derive today's bucket from
    yesterday's currency verdict and make `CPM-FR-22`'s replay unstateable.

    Args:
        package_id: The package to read.
        policy_run_id: The run whose rows to read -- this run, always.

    Returns:
        The verdict per domain, by the name a rule's `when` uses. A domain whose
        pass wrote no row for this package is **absent** from the mapping rather
        than present with a guessed value, so a rule requiring it simply does not
        match.

    """
    verdicts: dict[str, str] = {}
    for reader in DOMAIN_READERS:
        # `_default_manager` rather than `objects`: the reader holds a
        # `type[models.Model]`, and Django declares the manager on the metaclass
        # rather than on the base, so `objects` is invisible to a type checker
        # reading that annotation. This is Django's own documented accessor for
        # exactly this -- reaching a manager off a model class you were handed --
        # and it is the same shape the `_meta` reads elsewhere in this package take.
        manager = reader.model._default_manager  # noqa: SLF001 - Django's own public-by-convention API
        row = manager.filter(package_id=package_id, policy_run_id=policy_run_id).first()
        if row is not None:
            verdicts[reader.domain] = str(getattr(row, reader.column))
    return verdicts


def rule_label(position: int) -> str:
    """Return how a matched rule is named on the row.

    Args:
        position: The rule's zero-based index in the version's rule set.

    Returns:
        `rule 1` for the first rule. One-based, because that is how a reviewer
        counts down the file -- and the row is read by whoever has to open it.

    """
    return f"rule {position + 1}"


def matching_rule(
    rules: tuple[PriorityRule, ...],
    verdicts: Mapping[str, str],
) -> tuple[int, PriorityRule] | None:
    """Return the first rule whose every condition holds, with its position.

    **Top down, first match wins**, which is `CPM-FR-20` in as many words. The
    order is the file's and the order *is* the policy: a broad rule above a narrow
    one makes the narrow one unreachable, which
    `policies/data/policy-parameters.toml` warns a reviewer about because nothing
    here can.

    Args:
        rules: The version's rule set, in the order the file states it.
        verdicts: What the six earlier passes concluded, by domain.

    Returns:
        The zero-based position and the rule, or `None` when none matched. A rule
        naming a domain this package has no row for does not match: an absent
        verdict is not a wildcard.

    """
    for position, rule in enumerate(rules):
        if all(verdicts.get(domain) == verdict for domain, verdict in rule.conditions):
            return position, rule
    return None


def usage_score(
    weights: tuple[tuple[str, int], ...],
    snapshot: InventorySnapshot | None,
) -> tuple[int | None, str]:
    """Return the 1-100 score this package's usage signals earn, or why there is none.

    **Normalized against the weights recorded**, so the absolute numbers in the file
    only have to be comparable to each other. Each weighted signal contributes its
    observed count times its weight; the total is mapped onto 1-100 against the
    largest total those weights could produce for a signal at this product's own
    ceiling. The arithmetic is deliberately dull -- what `CPM-FR-20` asks for is a
    number that ranks within a bucket, and PRD Open Question 8 says what the numbers
    *mean* is not decided.

    Args:
        weights: The `(signal, weight)` pairs the version records, in file order.
        snapshot: The inventory observation current at the cut-off, or `None`.

    Returns:
        The score and the empty string, or `None` and the reason there is none.
        There are four reasons and the row says which: no score function is
        recorded, no observation exists, a weighted signal is blank, or every
        recorded weight is zero.

    """
    if not weights:
        return None, NO_SCORE_FUNCTION_DETAIL
    if snapshot is None:
        return None, NO_SIGNALS_DETAIL

    missing = sorted(signal for signal, _weight in weights if getattr(snapshot, signal, None) is None)
    if missing:
        return None, MISSING_SIGNAL_DETAIL.format(signals=missing)

    total = sum(int(getattr(snapshot, signal)) * weight for signal, weight in weights)
    ceiling = sum(weight for _signal, weight in weights) * _SIGNAL_CEILING
    if ceiling == 0:
        return None, NO_SCORE_FUNCTION_DETAIL

    span = MAX_PRIORITY_SCORE - MIN_PRIORITY_SCORE
    scaled = MIN_PRIORITY_SCORE + (min(total, ceiling) * span) // ceiling
    return scaled, ""


#: The count this product treats as the top of the usage scale, for normalising a
#: score onto 1-100.
#:
#: **A scaling constant, not a claim about any organisation.** The score has to land
#: in a stated range and the counts it is built from are unbounded, so something has
#: to say what "as used as it gets" is. A hundred components or lines of business
#: depending on one package is that, and a package past it scores 100 rather than
#: overflowing.
#:
#: It is deliberately *not* in the parameter file. PRD Open Question 8 leaves the
#: score function open and a reviewer answering it chooses the weights; this is the
#: arithmetic that turns weights into the range `CPM-FR-20` states, and a reviewer
#: who wants a different curve is changing the function rather than a number.
#: `CPM-PRIORITY-S01` records it as the alternative not taken.
_SIGNAL_CEILING: Final[int] = 100


def ranking_order() -> tuple[str, ...]:
    """Return the field ordering a run's assignments rank in.

    **The one derivation of `CPM-PRIORITY-S01`'s rank**, so two read surfaces cannot
    rank one run two ways. See `RANKING_ORDER` for why the package key is the third
    term and why it is not optional.

    Returns:
        The field names, ready for `order_by`. A row's rank is its position in that
        ordering, which is what "derived from bucket and score" means -- there is no
        stored ordinal to disagree with the columns it came from.

    """
    return RANKING_ORDER


class PriorityPass(PolicyPass):
    """`CPM-FR-20` as a `PolicyPass`: read six verdicts, apply a rule set, write one row.

    Three declarations and two methods. The derived table is `PackagePriority` and
    the rollup column is `priority_status` -- the third domain column on
    `package_health` and the first this epic adds.

    **It is registered last**, which is the one thing about its position that
    matters: it reads the six earlier passes' rows for the same run, and
    `core/policy.py` keeps registration order precisely so a later pass may.
    """

    name: ClassVar[str] = POLICY_NAME
    derived_model: ClassVar[type[models.Model] | None] = PackagePriority
    contributes: ClassVar[tuple[str, ...]] = (ROLLUP_COLUMN,)

    #: The parameter set this run applies, established once by `prepare`.
    parameters: PolicyParameters | None = None

    def prepare(self, *, policy_run: PolicyRun, evidence_cutoff: datetime) -> None:
        """Establish the parameter set this run applies, once, before any package.

        One line, on exactly the terms `FeedstockPresencePass.prepare` states: the
        version is a run-wide fact, and a version the reviewed file does not record
        is a run-wide failure the shared `parameters_in` refuses.

        Args:
            policy_run: The run about to execute. Its `policy_version` is what the
                rule set and the score function are looked up by, which is what
                makes them versioned rather than merely external (AC 3).
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
        """Assign one package's priority, write its derived row, and contribute its bucket.

        Called once per package, inside that package's transaction (`CPM-AD-23`) and
        **after** the six passes whose rows it reads.

        **Every package gets a row**, including one no rule matched and one with no
        usage signals: the bucket is `unknown`, the score is `NULL`, and the row says
        which absence it is.

        Args:
            package: The package to judge.
            policy_run: The run this evaluation belongs to. Its version and its
                cut-off are copied onto the row.
            evidence_cutoff: The instant to read the inventory as of. Nothing here
                reads the current time.

        Returns:
            The bucket, under `priority_status`, for `core/rollup.py` to write
            through `CPM-AD-4`'s gate. This pass never writes the rollup itself.

        Raises:
            PriorityPolicyError: When the cut-off is naive, or when the pass was
                never prepared. Deliberately not for an empty rule set, a rule that
                matched nothing, or a missing usage signal: a raise here rolls back
                this package's other six domains' rows too, and each of those is an
                honest state the row records instead.

        """
        _require_aware(evidence_cutoff)
        parameters = self._parameters()
        assignment = self._assign(
            package_id=package.pk,
            policy_run_id=policy_run.pk,
            cutoff=evidence_cutoff,
            parameters=parameters,
        )
        PackagePriority.objects.create(
            package=package,
            policy_run=policy_run,
            bucket=assignment.bucket,
            bucket_description=assignment.description,
            matched_rule=assignment.matched_rule,
            reason=assignment.reason,
            score=assignment.score,
            policy_version=policy_run.policy_version,
            evidence_cutoff=evidence_cutoff,
            detail=assignment.detail,
        )
        return {ROLLUP_COLUMN: assignment.bucket}

    def _assign(
        self,
        *,
        package_id: int,
        policy_run_id: int,
        cutoff: datetime,
        parameters: PolicyParameters,
    ) -> Assignment:
        """Return one package's bucket, score and explanation.

        Split from `evaluate` so the decision is testable without a run: everything
        here is a function of two reads and a parameter set.

        Args:
            package_id: The package to judge.
            policy_run_id: The run whose derived rows to read.
            cutoff: The instant to read the inventory as of.
            parameters: The version's rule set and score function.

        Returns:
            The assignment, with the reasons for whatever it could not establish.

        """
        score, score_detail = usage_score(
            parameters.priority_score_weights,
            snapshot_as_of(package_id=package_id, cutoff=cutoff),
        )
        if not parameters.priority_rules:
            return Assignment(
                bucket=PRIORITY_STATUS_UNKNOWN,
                description="",
                matched_rule="",
                reason="",
                score=score,
                detail=_joined(NO_RULE_SET_DETAIL, score_detail),
            )

        matched = matching_rule(
            parameters.priority_rules,
            current_verdicts(package_id=package_id, policy_run_id=policy_run_id),
        )
        if matched is None:
            return Assignment(
                bucket=PRIORITY_STATUS_UNKNOWN,
                description="",
                matched_rule="",
                reason="",
                score=score,
                detail=_joined(NO_MATCH_DETAIL, score_detail),
            )

        position, rule = matched
        return Assignment(
            bucket=rule.bucket,
            description=rule.description,
            matched_rule=rule_label(position),
            reason=rule.reason,
            score=score,
            detail=score_detail,
        )

    def _parameters(self) -> PolicyParameters:
        """Return the parameter set `prepare` established, or refuse.

        Args:
            None.

        Returns:
            The parameter set this run applies.

        Raises:
            PriorityPolicyError: When the pass was never prepared. A caller
                defect -- `core/policy_run.py` calls `prepare` for every pass before
                the loop -- and refusing is better than deriving a bucket from a rule
                set nobody chose.

        """
        if self.parameters is None:
            message = (
                f"the {POLICY_NAME} pass was asked to evaluate a package before prepare() established this "
                f"run's parameter set. CPM-AD-8 makes the rule set versioned data chosen by the run's policy "
                f"version, so a bucket assigned without one would be a bucket from no policy at all."
            )
            raise PriorityPolicyError(message)
        return self.parameters


def _joined(*clauses: str) -> str:
    """Return the non-empty clauses as one sentence.

    Args:
        *clauses: The reasons this row has to give, in the order they are read.

    Returns:
        The clauses joined, or the empty string when there are none. A row can have
        no bucket *and* no score for two different reasons, and both belong on it.

    """
    return "; ".join(clause for clause in clauses if clause)
