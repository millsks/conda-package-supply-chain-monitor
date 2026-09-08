"""The policy passes' own derived tables. One row per package per policy run, each.

`CPM-AD-21` gives every pass a per-domain table keyed `(package, policy_run)`.
`PackageCurrency` (`CPM-CURRENCY-S06`) was the first, `PackageFeedstockPresence`
(`CPM-CURRENCY-S07`) the second, `PackageVulnerability` (`CPM-SECURITY-S04`)
the third, `PackageLicense` (`CPM-SECURITY-S05`) the fourth and
`PackageRemediation` (`CPM-SECURITY-S06`) the fifth; they are five
tables and not one wide one,
because a pass writes only its own and a shared table would make "which pass
wrote this column" a convention rather than a schema. **None of them is the
health rollup** -- `CPM-AD-21` says no pass writes `package_health` and
`CPM-EP-PRIORITY` owns the orchestrating writer, so "rollup" in a story title
means a pass's own reduction into its own table. The key is what makes
`CPM-FR-22`'s replay a comparison rather than an overwrite: re-running the same
policy version against the same cut-off opens a *new* run, writes a new row, and
leaves the original where it was for the two to be diffed.

**Why the per-surface verdicts are four columns rather than one.** `CPM-FR-16`'s
second testable consequence is that "currency is computed per surface, so
source-current and feedstock-stale is expressible", and a single column cannot
express it: a reader would be inferring the parts from the whole, which is the
inference `CPM-AD-5` exists to remove. Four columns, one per `VersionSurface`
member, each holding the full `CurrencyOutcome` vocabulary, is the shape in which
that sentence is a fact the table holds.

**Why the evidence rows are referenced rather than copied.** `CPM-FR-16`'s first
consequence is that "the authority decision and the evidence supporting it are
stored with the result". A row naming an authority without saying which
observation it read could not be audited by a reader and could not be explained
to one -- `CPM-AD-8`'s replay guarantee is about reproducing output, not about
justifying it. Evidence is append-only and nothing may correct it (`CPM-AD-2`),
so a reference can never come to disagree with what it points at, which is why
the version strings themselves are not copied onto this row: they are one join
away and they cannot drift.

**`PackageRemediation` is the one table in this module with a constraint behind
an *adverse* value that would otherwise be reached by silence.** `blocked` tells
a security reviewer to stop looking for a fix, and it is honest only when every
one of the four version surfaces was read and none carried the fixed version. So
the database requires exactly that: a `blocked` row naming a surface this run did
not read is refused, which is `PackageLicense`'s `allowed` rule turned round --
there the danger is a permission reached by an absence, here it is an abandonment
reached by one.

**These are derived state, and they are not evidence.** None carries any of
the three marks `tests/model_registry.py` reads -- none inherits
`AppendOnlyModel`, the app label is `policies`, and none declares
`observed_at` -- so none needs a `not_evidence` declaration and none may
take one (`CPM-AD-2`'s escape is for a model that carries a mark, and
`tests/unit/django_apps/test_evidence_inheritance_audit.py` fails an unused one).

**None declares a `computed_at`, and the consequence is stated rather than
implied.** `CPM-AD-11` requires that column of the *rollup*, and
`tests/unit/django_apps/test_derived_status_writability_audit.py` uses it as the
mark of a model holding derived state -- so these tables are outside that audit's
registry sweep. The instant a row was computed at is the run's, on the row
`policy_run` names, and a copy of it here would be a second spelling of one fact
on a row that already carries the reference. `core/policy_run.py` reinforces it
by construction: a pass is handed no clock at all, so there is no honest instant
for such a column to hold. What the audit's *source* scan still
reaches is the write itself, in `policies/currency.py`, `policies/feedstock.py`
and `policies/vulnerability.py`, each recorded in its exemption table by name.
The status columns are declared
`editable=False` anyway: nothing but a policy run may write a derived verdict,
and that is true whether or not an audit is currently looking. What that audit's
*source* scan still reaches is each pass's own `create()` call, and
`policies/licence.py` and `policies/remediation.py` are recorded in its exemption
table beside the three named above.

**What `PackageVulnerability`, `PackageLicense` and `PackageRemediation` *do*
copy, where the two older tables copy nothing, is the policy version and the
cut-off** -- both facts about the run rather than about the evidence. Their class
docstrings argue why, and the short of it is the same in all three: the value
each carries is meaningless without the version whose reviewed data produced it
-- a severity order, a licence rule set, and for remediation the version under
which the comparison and the vocabulary were fixed at all.

**`PackageLicense` is the one table in this module with a constraint behind a
*clean* value.** Every other constraint here requires evidence behind an adverse
or a determinate verdict. `allowed` is the one verdict in this product that
claims nothing is wrong, and it is the one whose appearance in error is least
likely to be questioned -- so the database requires it to name the rule that
produced it, rather than trusting the pass never to reach it by accident.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from django.db import models
from django.utils.translation import gettext_lazy as _

from conda_sentinel.collectors.models import CondaPackageSnapshot
from conda_sentinel.collectors.models import FeedstockSnapshot
from conda_sentinel.collectors.models import KevFinding
from conda_sentinel.collectors.models import LicenseFinding
from conda_sentinel.collectors.models import PyPIReleaseSnapshot
from conda_sentinel.collectors.models import SourceReleaseSnapshot
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.identity.models import VersionSurface
from conda_sentinel.policies.outcomes import ABSENT
from conda_sentinel.policies.outcomes import ADVISORIES_MATCHED
from conda_sentinel.policies.outcomes import AWAITING_BUILD
from conda_sentinel.policies.outcomes import AWAITING_PACKAGING
from conda_sentinel.policies.outcomes import BEHIND
from conda_sentinel.policies.outcomes import BLOCKED
from conda_sentinel.policies.outcomes import CURRENCY_STATE_LENGTH
from conda_sentinel.policies.outcomes import CURRENT
from conda_sentinel.policies.outcomes import FEEDSTOCK_STATE_LENGTH
from conda_sentinel.policies.outcomes import FIX_AVAILABILITY_LENGTH
from conda_sentinel.policies.outcomes import FIX_NOT_PUBLISHED
from conda_sentinel.policies.outcomes import FIX_PUBLISHED
from conda_sentinel.policies.outcomes import KEV_LISTED
from conda_sentinel.policies.outcomes import KEV_MEMBERSHIP_LENGTH
from conda_sentinel.policies.outcomes import KEV_NOT_LISTED
from conda_sentinel.policies.outcomes import LICENSE_STATE_LENGTH
from conda_sentinel.policies.outcomes import MANUAL_REVIEW
from conda_sentinel.policies.outcomes import NO_ADVISORY_MATCHED
from conda_sentinel.policies.outcomes import PRESENT_AND_INACTIVE
from conda_sentinel.policies.outcomes import PRESENT_AND_MAINTAINED
from conda_sentinel.policies.outcomes import READINESS_STATE_LENGTH
from conda_sentinel.policies.outcomes import READY
from conda_sentinel.policies.outcomes import RULE_DISPOSITIONS
from conda_sentinel.policies.outcomes import STAGED_RECIPE_PENDING
from conda_sentinel.policies.outcomes import SURFACE_NOT_READ
from conda_sentinel.policies.outcomes import VULNERABILITY_STATE_LENGTH
from conda_sentinel.policies.outcomes import CurrencyOutcome
from conda_sentinel.policies.outcomes import FeedstockOutcome
from conda_sentinel.policies.outcomes import FixAvailability
from conda_sentinel.policies.outcomes import KevMembership
from conda_sentinel.policies.outcomes import PackageLicenseOutcome
from conda_sentinel.policies.outcomes import PackageVulnerabilityOutcome
from conda_sentinel.policies.outcomes import RemediationReadiness
from conda_sentinel.policies.parameters import MAX_LICENSE_EXPRESSION_CHARACTERS
from conda_sentinel.policies.parameters import MAX_RISK_LEVEL_CHARACTERS

__all__ = [
    "AN_AGE_EXACTLY_WHEN_THERE_IS_AN_INSTANT",
    "AN_AWAITING_BUILD_ROW_NAMES_THE_RECIPE_THAT_CARRIES_THE_FIX",
    "AN_AWAITING_PACKAGING_ROW_NAMES_THE_RELEASE_THAT_CARRIES_THE_FIX",
    "AUTHORITY_IS_A_KNOWN_SURFACE",
    "A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ",
    "A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION",
    "A_DETERMINATE_READINESS_NEEDS_ITS_FINDING",
    "A_MATCHED_RULE_ONLY_WHERE_A_RULE_DECIDED",
    "A_READY_ROW_NAMES_THE_CHANNEL_THAT_CARRIES_THE_FIX",
    "A_RISK_LEVEL_ONLY_WHERE_ADVISORIES_MATCHED",
    "A_RULED_OUTCOME_NAMES_THE_RULE_THAT_PRODUCED_IT",
    "DETERMINATE_KEV_MEMBERSHIP_NEEDS_ITS_CROSS_REFERENCE",
    "DETERMINATE_PRESENCE_NEEDS_AN_OBSERVATION",
    "DETERMINATE_READINESS_VERDICTS",
    "DETERMINATE_STATUS_NEEDS_ITS_FINDING",
    "DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY",
    "ESTABLISHED_KEV_MEMBERSHIPS",
    "ESTABLISHED_VULNERABILITY_STATUSES",
    "JUDGED_LICENSE_OUTCOMES",
    "LICENSE_ROW_NAMES_ITS_POLICY_VERSION",
    "MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT",
    "MEASURED_VERDICTS",
    "ONE_FEEDSTOCK_ROW_PER_PACKAGE_PER_RUN",
    "ONE_LICENSE_ROW_PER_PACKAGE_PER_RUN",
    "ONE_REMEDIATION_ROW_PER_PACKAGE_PER_RUN",
    "ONE_ROW_PER_PACKAGE_PER_RUN",
    "ONE_VULNERABILITY_ROW_PER_PACKAGE_PER_RUN",
    "REMEDIATION_ROW_NAMES_ITS_POLICY_VERSION",
    "SURFACE_FIX_FIELDS",
    "SURFACE_STATUS_FIELDS",
    "THE_JUDGED_LICENSE_OUTCOME_NEEDS_ITS_FINDING",
    "THRESHOLD_IS_A_POSITIVE_INTERVAL",
    "VULNERABILITY_ROW_NAMES_ITS_POLICY_VERSION",
    "AuthorityOrderSource",
    "PackageCurrency",
    "PackageFeedstockPresence",
    "PackageLicense",
    "PackageRemediation",
    "PackageVulnerability",
]

#: How wide the two short vocabulary columns are. `VersionSurface`'s longest
#: value is `conda_package`, thirteen characters, and `AuthorityOrderSource`'s is
#: `package`, seven; the rest is headroom, so a fifth surface needs no migration
#: for the width alone. One number for both because they are the same kind of
#: value -- a fixed token from a closed vocabulary -- on the terms
#: `identity/models.py`'s `_VOCABULARY_LENGTH` states.
_VOCABULARY_LENGTH: Final[int] = 32

#: How wide a column holding a copied policy version is, matching what
#: `core/models.py` gives `PolicyRun.policy_version`.
#:
#: The number is repeated rather than imported, on the terms every width in this
#: repository is argued: a version string is *not* a value from a closed
#: vocabulary -- `CPM-AD-8` makes it data an operator supplies -- so it cannot
#: share `_VOCABULARY_LENGTH`, and a column narrower than the run's own would
#: truncate a version the ledger accepted. `tests/unit/django_apps/`
#: `test_vulnerability_policy.py` reconciles the two directly rather than
#: trusting this comment.
_POLICY_VERSION_LENGTH: Final[int] = 128

#: The unique constraint that makes `(package, policy_run)` the key `CPM-AD-21`
#: requires, by name, so the case that asserts the refusal and the declaration
#: that makes it cannot drift.
ONE_ROW_PER_PACKAGE_PER_RUN: Final[str] = "one_currency_row_per_package_per_run"

#: The constraint holding `chosen_authority` to the surface vocabulary, by name.
AUTHORITY_IS_A_KNOWN_SURFACE: Final[str] = "currency_authority_is_a_known_surface"

#: The constraint requiring an authority behind any determinate verdict, by name.
DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY: Final[str] = "currency_verdict_names_its_authority"

#: Which column holds each surface's verdict, by `VersionSurface` value.
#:
#: The one place the four columns are tied to the four surfaces, and it is read
#: rather than merely declared: `DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY` below is
#: built from it, so a surface added to `VersionSurface` without a column here
#: fails at import, and a column renamed without its entry drops out of the
#: constraint rather than silently going unchecked.
#:
#: **`policies/currency.py` deliberately does *not* read it**, and that is worth
#: stating because it is the obvious next step. The pass spells the four keywords
#: literally in its `create()` call so that
#: `tests/unit/django_apps/test_derived_status_writability_audit.py` can see the
#: write -- routing a derived status through a mapping to stay out of that
#: audit's view is the `**kwargs` dodge it names. The literal keywords and this
#: table are reconciled by a case in
#: `tests/unit/django_apps/test_currency_policy.py` rather than by one reading
#: the other.
SURFACE_STATUS_FIELDS: Final[dict[str, str]] = {
    VersionSurface.SOURCE.value: "source_status",
    VersionSurface.PYPI.value: "pypi_status",
    VersionSurface.FEEDSTOCK.value: "feedstock_status",
    VersionSurface.CONDA_PACKAGE.value: "conda_package_status",
}


def _no_surface_is_determinate() -> models.Q:
    """Return the condition that no per-surface column holds a comparison verdict.

    Built by walking `SURFACE_STATUS_FIELDS` rather than by naming the four
    columns, so a fifth surface joins the constraint at the moment it acquires a
    column and a renamed column drops out of the check rather than going silently
    unchecked. The migration freezes whatever this produced on the day it ran,
    which is correct: a migration records what the schema was asked to be.

    Returns:
        The conjunction, one `~Q(<column>__in=[current, behind])` per surface. No
        column here is nullable, so no conjunct can be the third thing a SQL
        CHECK can be.

    """
    condition = models.Q()
    for column in SURFACE_STATUS_FIELDS.values():
        condition &= ~models.Q(**{f"{column}__in": [CURRENT, BEHIND]})
    return condition


class AuthorityOrderSource(models.TextChoices):
    """Where the authority order applied to a row came from.

    AC 2 asks that a package with no recorded authority have "the documented
    default order" applied, and the acceptance criterion the story derives from
    it asks that "the row records that it was the default". A row that merely
    carried the order it used could not say that: the recorded order and the
    default are both lists of surfaces, and a package that had explicitly chosen
    the default order would be indistinguishable from one that had chosen
    nothing.

    A closed two-member vocabulary rather than a boolean, on the terms every
    stored vocabulary in this product uses. The values are fixed lowercase
    tokens and are emitted verbatim (`CPM-AD-24`).

    It is not an `OutcomeState` and carries no sentinel: this is provenance, not
    a verdict, and the day a third source exists -- an operator override, a
    resolver's inference -- it is a member here rather than a second column.
    """

    PACKAGE = "package"
    DEFAULT = "default"


class PackageCurrency(models.Model):
    """What one policy run concluded about one package's version currency.

    Table `package_currency`, named by the same convention `package_health` and
    the evidence tables are: the architecture names the schema, and a derived
    `policies_packagecurrency` would make the table depend on which application
    happened to declare the model.

    See the module docstring for why the per-surface verdicts are four columns,
    why the evidence is referenced rather than copied, and why this table carries
    no `computed_at`.

    **Every relation is `PROTECT`.** `EVIDENCE.02-AUDIT-001`'s cascade rule binds
    evidence models and this is not one, so the choice is argued rather than
    inherited, and it is argued twice over. Deleting a policy run under `CASCADE`
    would silently take away the findings that explain a rollup row still naming
    it -- an operational tidy-up somebody will one day write, quietly emptying
    the audit trail. And an evidence row is the *support* for a verdict: a
    snapshot deleted out from under a row that cites it would leave the row
    claiming an authority nothing can be shown for, which is worse than the
    delete failing.

    **The four snapshot references are nullable and the four verdicts are not.**
    A surface with no observation at the cut-off is a real, ordinary answer --
    `unknown`, never `ok` -- so the verdict column always holds a value while the
    reference has nothing to point at. `NULL` here is the absence of a row rather
    than a second spelling of a state.
    """

    #: The package this finding is about, by the integer primary key `CPM-AD-3`
    #: fixes. Together with `policy_run` it is the `(package, policy_run)` key
    #: `CPM-AD-21` requires, made a database rule by the constraint below.
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        related_name="currency_findings",
        verbose_name=_("package"),
    )

    #: The run that computed this row. `CPM-FR-22`'s replay guarantee is "re-run
    #: this version against this cut-off and get identical output", and a row
    #: that could not name the run it came from is a row no replay can be
    #: compared against. The run also carries the cut-off and the instants, which
    #: is why this table copies neither.
    policy_run = models.ForeignKey(
        PolicyRun,
        on_delete=models.PROTECT,
        related_name="currency_findings",
        verbose_name=_("policy run"),
    )

    #: What the upstream source surface concluded. `editable=False` on every
    #: status column here: a derived verdict is a policy run's to write and
    #: nobody else's (`CPM-FR-37`), and the declaration leaves the field out of
    #: every `ModelForm`, out of the admin and out of `full_clean()`'s validation
    #: of user-supplied data.
    source_status = models.CharField(
        _("source currency"),
        max_length=CURRENCY_STATE_LENGTH,
        choices=CurrencyOutcome.choices,
        editable=False,
    )

    #: What the PyPI surface concluded. `not_applicable` here is the point of the
    #: column rather than an edge of it: `CPM-FR-8` records a non-Python package
    #: as inapplicable to PyPI, and `CPM-SM-C1` is the promise that such a
    #: package is never called stale against a registry it never published to.
    pypi_status = models.CharField(
        _("PyPI currency"),
        max_length=CURRENCY_STATE_LENGTH,
        choices=CurrencyOutcome.choices,
        editable=False,
    )

    #: What the conda-forge recipe surface concluded.
    feedstock_status = models.CharField(
        _("feedstock currency"),
        max_length=CURRENCY_STATE_LENGTH,
        choices=CurrencyOutcome.choices,
        editable=False,
    )

    #: What the published-conda-package surface concluded.
    conda_package_status = models.CharField(
        _("published conda package currency"),
        max_length=CURRENCY_STATE_LENGTH,
        choices=CurrencyOutcome.choices,
        editable=False,
    )

    #: The one verdict this pass contributes to the rollup, reduced from the four
    #: above by `policies/currency.py`'s `overall_verdict`. Stored here as well as
    #: contributed because the rollup's copy has been through `CPM-AD-4`'s gate
    #: and this one has not: an `unmapped` package's rollup column reads
    #: `unknown` whatever this pass computed, and the two together are what say
    #: *why*.
    overall_status = models.CharField(
        _("currency"),
        max_length=CURRENCY_STATE_LENGTH,
        choices=CurrencyOutcome.choices,
        editable=False,
    )

    #: What this run has to say about the verdicts it reached -- one line per
    #: surface it called `behind`, naming what that surface stored, what the
    #: authority stored, and what each was compared as.
    #:
    #: **The column exists because `behind` means only "different".**
    #: `policies/currency.py`'s module docstring states the comparison and its
    #: limits once; what follows from them here is that a `behind` verdict can be
    #: a real discrepancy or two surfaces spelling one version differently, and
    #: telling those apart without this column means a human re-deriving the
    #: comparison from four joined evidence rows -- the work the row exists to
    #: remove.
    #:
    #: Empty on every row where nothing is behind, which is the same rule every
    #: evidence table in this product applies to its own `detail`: an ordinary
    #: result needs no explanation. `blank=True, default=""` on those terms, and
    #: `editable=False` because it is written by the same pass and by nobody
    #: else.
    detail = models.TextField(_("detail"), blank=True, default="", editable=False)

    #: Which surface was authoritative for this package in this run -- the first
    #: entry of the applied order that stated a version at the cut-off.
    #:
    #: `editable=False`, as the three columns around it and the rollup's own are.
    #: `tests/unit/django_apps/test_derived_status_writability_audit.py` reaches
    #: only fields *named* for a status, so nothing would have failed on these --
    #: and a form that could rewrite "which surface was authoritative" while
    #: leaving the four verdicts it produced untouched is a row that contradicts
    #: itself, which is the same defect the naming convention exists to catch.
    #:
    #: Blank when no entry of the order stated one, which is an ordinary answer:
    #: a package nothing has observed yet has no authority, and blank means
    #: missing here as it does everywhere else in this product. The constraints
    #: below hold it to the surface vocabulary and require it whenever any
    #: surface carries a determinate verdict.
    chosen_authority = models.CharField(
        _("chosen authority"),
        max_length=_VOCABULARY_LENGTH,
        choices=VersionSurface.choices,
        blank=True,
        default="",
        editable=False,
    )

    #: The order that was actually applied, best first, as `VersionSurface`
    #: values.
    #:
    #: Recorded rather than recoverable, and the difference matters twice.
    #: `Package.version_authority_order` is mutable, so re-reading it later would
    #: answer about the package as it is now rather than as this run found it;
    #: and `DEFAULT_AUTHORITY_ORDER` is a constant this product may change, so a
    #: row that merely said "the default" would silently come to mean a different
    #: order. Never NULL, on the terms `alternative_purls` is not.
    authority_order = models.JSONField(_("authority order"), default=list, blank=True, editable=False)

    #: Whether that order came from the package or from the documented default
    #: (AC 2). See `AuthorityOrderSource` for why this is a vocabulary rather
    #: than a boolean, and why "the row records that it was the default" cannot
    #: be recovered from `authority_order` alone.
    authority_order_source = models.CharField(
        _("authority order source"),
        max_length=_VOCABULARY_LENGTH,
        choices=AuthorityOrderSource.choices,
        editable=False,
    )

    #: The upstream-release observation this verdict rests on: the newest at the
    #: run's cut-off, or NULL where there was none. The `source` half of
    #: `CPM-FR-16`'s "the evidence supporting it is stored with the result".
    source_snapshot = models.ForeignKey(
        SourceReleaseSnapshot,
        on_delete=models.PROTECT,
        related_name="currency_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("source release snapshot"),
    )

    #: The PyPI observation this verdict rests on, on the same terms.
    pypi_snapshot = models.ForeignKey(
        PyPIReleaseSnapshot,
        on_delete=models.PROTECT,
        related_name="currency_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("PyPI release snapshot"),
    )

    #: The feedstock observation this verdict rests on, on the same terms.
    feedstock_snapshot = models.ForeignKey(
        FeedstockSnapshot,
        on_delete=models.PROTECT,
        related_name="currency_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("feedstock snapshot"),
    )

    #: The published-package observation this verdict rests on.
    #:
    #: One row, where `conda_package_snapshots` holds one per `(channel,
    #: platform)` pair. Which one it is, is the whole of what this reference adds
    #: over a bare verdict: `policies/currency.py` reads the newest observation of
    #: any pair at the cut-off, so the channel and the platform the verdict is
    #: about are the ones on the row this points at, and a reader who needs to
    #: know which can see it. See that module for why one row rather than a
    #: verdict per pair, and for what that costs.
    conda_package_snapshot = models.ForeignKey(
        CondaPackageSnapshot,
        on_delete=models.PROTECT,
        related_name="currency_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("conda package snapshot"),
    )

    class Meta:
        """The table the architecture names, not the `policies_packagecurrency` Django derives."""

        db_table = "package_currency"
        verbose_name = _("package currency")
        verbose_name_plural = _("package currency")
        constraints = [
            # `CPM-AD-21`'s key, as a database rule rather than as the writer's
            # promise. A pass is called once per package per run, so a second row
            # for one pair means the pass ran twice or two passes wrote one table
            # -- and a reader joining this to the rollup would silently get
            # whichever the database returned first.
            models.UniqueConstraint(
                fields=["package", "policy_run"],
                name=ONE_ROW_PER_PACKAGE_PER_RUN,
            ),
            # `choices` is a form and `full_clean()` rule and Django enforces
            # neither on `save()`, so without this a misspelled surface reaches
            # the column and every later read is about an authority that does not
            # exist. The values are frozen into the migration exactly as the
            # state vocabularies are elsewhere here: a migration records what the
            # schema was asked to be, and one that followed a constant it can no
            # longer see would rewrite history.
            models.CheckConstraint(
                condition=models.Q(chosen_authority__in=["", *VersionSurface.values]),
                name=AUTHORITY_IS_A_KNOWN_SURFACE,
            ),
            # The comparison's own invariant. `current` and `behind` are verdicts
            # *against an authority*: they are reached by comparing a surface's
            # version with the authority's, so a row carrying either while naming
            # no authority is a comparison against nothing. The converse is
            # deliberately not asserted -- a named authority with every surface
            # indeterminate is impossible for a different reason, that the
            # authority is by definition a surface that stated a version, and
            # expressing it here would take four more disjuncts to restate what
            # one function already guarantees.
            #
            # No column here is nullable, so no conjunct can be the third thing a
            # SQL CHECK can be.
            models.CheckConstraint(
                condition=~models.Q(chosen_authority="") | _no_surface_is_determinate(),
                name=DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY,
            ),
        ]

    def __str__(self) -> str:
        """Return the package, the overall verdict and the authority it was judged against.

        Returns:
            A one-line summary. Read off `package_id` rather than off `package`,
            for the reason `PackageHealth.__str__` gives: the related object of
            an unsaved instance raises `RelatedObjectDoesNotExist`, and a
            `__str__` that raises breaks the two places a half-built object is
            most likely to be rendered, a debugger and a traceback.

        """
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        verdict = self.overall_status or "(no verdict)"
        authority = self.chosen_authority or "no authority"
        return f"currency of {scope}: {verdict} against {authority}"


#: The unique constraint that makes `(package, policy_run)` the key `CPM-AD-21`
#: requires of the feedstock presence table, by name, so the case that asserts
#: the refusal and the declaration that makes it cannot drift.
ONE_FEEDSTOCK_ROW_PER_PACKAGE_PER_RUN: Final[str] = "one_feedstock_presence_row_per_package_per_run"

#: The constraint holding the applied threshold to a positive interval, by name.
THRESHOLD_IS_A_POSITIVE_INTERVAL: Final[str] = "feedstock_threshold_is_a_positive_interval"

#: The constraint tying the computed age to the instant it was computed from, by
#: name.
AN_AGE_EXACTLY_WHEN_THERE_IS_AN_INSTANT: Final[str] = "feedstock_age_exactly_when_there_is_an_instant"

#: The constraint requiring an activity instant behind either maintenance
#: verdict, by name.
MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT: Final[str] = "feedstock_maintenance_verdict_names_its_instant"

#: The constraint requiring the observation behind any determinate verdict, by
#: name.
DETERMINATE_PRESENCE_NEEDS_AN_OBSERVATION: Final[str] = "feedstock_verdict_names_its_observation"

#: The two verdicts that are reached by comparing an age against a threshold, and
#: therefore the two that cannot be reached without an activity instant.
#:
#: A tuple rather than two literals inside the constraint, because
#: `MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT` and
#: `tests/unit/django_apps/test_feedstock_policy.py` both name the same pair and a
#: second spelling of it is a constraint that stops matching what the pass
#: produces. It holds `FeedstockOutcome` values and no `OutcomeState` members, so
#: it is not the shape `tests/unit/django_apps/test_single_ordering_audit.py`
#: reads -- and it is not an order in any case: neither verdict outranks the
#: other.
MEASURED_VERDICTS: Final[tuple[str, ...]] = (PRESENT_AND_MAINTAINED, PRESENT_AND_INACTIVE)

#: Every verdict that is a statement about what conda-forge holds, rather than a
#: statement that this run could not say.
#:
#: The four `CPM-FR-40` names, and therefore the four that are unreachable
#: without an observation to rest on: each is read off a feedstock snapshot, and
#: none of them is a conclusion a run can draw from having found nothing to read.
#: `DETERMINATE_PRESENCE_NEEDS_AN_OBSERVATION` is built from it, and
#: `MEASURED_VERDICTS` above is the subset that additionally needs an *instant*.
DETERMINATE_VERDICTS: Final[tuple[str, ...]] = (ABSENT, STAGED_RECIPE_PENDING, *MEASURED_VERDICTS)


class PackageFeedstockPresence(models.Model):
    """What one policy run concluded about one package's feedstock. Table `package_feedstock_presence`.

    `CPM-FR-40` as a row: does a feedstock exist, and is anybody maintaining it.
    Four determinate outcomes -- `absent`, `present_and_maintained`,
    `present_and_inactive`, `staged_recipe_pending` -- plus `core`'s sentinels for
    the questions this run could not answer.

    Named by the same convention `package_currency` and `package_health` are: the
    architecture names the schema, and a derived
    `policies_packagefeedstockpresence` would make the table depend on which
    application happened to declare the model.

    **A second table rather than a column on `PackageCurrency`.** `CPM-AD-21`
    gives each pass its own derived table and `CPM-AD-11` gives each rollup column
    one owner; a feedstock verdict written onto the currency pass's table would
    make "which pass wrote this" a convention rather than a schema, and would tie
    the two passes' migrations, constraints and retention together for no reason
    beyond both being about feedstocks.

    **Every relation is `PROTECT`**, on exactly the terms `PackageCurrency`
    states: deleting a policy run under `CASCADE` would silently take away the
    findings that explain a rollup row still naming it, and an evidence row is the
    *support* for a verdict, so a snapshot deleted out from under a row that cites
    it would leave the row claiming a maintenance state nothing can be shown for.

    **The three measurement columns are nullable and the verdict is not.** A
    package nothing observed, a feedstock that does not exist, and a feedstock
    whose activity the collector could not date all get a verdict and no instant --
    so the verdict column always holds a value while `last_recipe_activity_at` and
    `activity_age` have nothing to hold. `NULL` here is the absence of a
    measurement rather than a second spelling of a state, which is the distinction
    `CPM-FR-6` exists to keep.

    **The threshold, by contrast, is never NULL.** It is looked up before any
    evidence is read, and a run whose policy version records none never reaches a
    write at all (`policies/parameters.py` refuses first). So a row exists only
    where a threshold was known, and the column says which one was applied --
    which is what makes AC 3's "read as a versioned policy parameter" auditable
    per row rather than per deployment.

    **It records the confidence it was computed under, and it does not gate.**
    `CPM-AD-4` puts the gate in `core/confidence.py`, applied once by
    `core/rollup.py` on the way into `package_health`; a pass never sees a
    confidence and never applies one. What this column is for is the reader of
    *this* table, who can then see what the gate would have done with the verdict
    beside it -- an `unmapped` package's rollup column reads `unknown` while this
    row still says what the evidence supported.

    There is deliberately **no check constraint** holding that column to
    `IdentityConfidence`. `PackageHealth.confidence` has none either, and the
    product's refusal for an unrecognised confidence lives in
    `core/confidence.py`'s `require_known_confidence`, which `core/rollup.py`
    applies before it composes. A constraint here would move that failure out of
    the compose phase and into the pass phase -- changing which phase contains a
    package with broken identity data, for a rule this story is forbidden from
    re-implementing.
    """

    #: The package this finding is about, by the integer primary key `CPM-AD-3`
    #: fixes. Together with `policy_run` it is `CPM-AD-21`'s key, made a database
    #: rule by the constraint below.
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        related_name="feedstock_presence_findings",
        verbose_name=_("package"),
    )

    #: The run that computed this row. It carries the cut-off, the instants and
    #: the policy version whose parameters were applied, which is why this table
    #: copies none of them.
    policy_run = models.ForeignKey(
        PolicyRun,
        on_delete=models.PROTECT,
        related_name="feedstock_presence_findings",
        verbose_name=_("policy run"),
    )

    #: What this run concluded. `editable=False`: a derived verdict is a policy
    #: run's to write and nobody else's (`CPM-FR-37`), and the declaration leaves
    #: the field out of every `ModelForm`, out of the admin and out of
    #: `full_clean()`'s validation of user-supplied data.
    presence_status = models.CharField(
        _("feedstock presence"),
        max_length=FEEDSTOCK_STATE_LENGTH,
        choices=FeedstockOutcome.choices,
        editable=False,
    )

    #: The inactivity threshold this run applied, from the reviewed parameter file
    #: keyed by the run's policy version (`CPM-FR-40`, `CPM-AD-8`).
    #:
    #: Stored on the row rather than looked up again by a reader, and the
    #: difference is the whole of AC 3. The file is a history that a later review
    #: adds to; a reader re-reading it would answer about the parameter set as it
    #: is now rather than as this run applied it, and two runs at two versions
    #: over one cut-off would then look like two runs of the same rule that
    #: disagreed.
    inactivity_threshold = models.DurationField(_("inactivity threshold"), editable=False)

    #: When the feedstock was last pushed to, copied from the observation this row
    #: rests on. NULL where there was no observation, where the observation is not
    #: determinate, or where a feedstock exists whose activity the collector could
    #: not date -- which is the case this pass answers `unknown` for rather than
    #: guessing.
    #:
    #: Copied rather than only referenced, unlike `PackageCurrency`'s version
    #: strings: this is the value the threshold was compared against, and the
    #: comparison is what the row exists to record. Evidence is append-only
    #: (`CPM-AD-2`), so the copy can never come to disagree with the row it was
    #: read from.
    last_recipe_activity_at = models.DateTimeField(
        _("last recipe activity at"),
        null=True,
        blank=True,
        default=None,
        editable=False,
    )

    #: How old that push was at the run's evidence cut-off -- the number the
    #: threshold was actually compared against. NULL exactly when
    #: `last_recipe_activity_at` is, which the constraint below makes a database
    #: rule rather than the writer's promise.
    #:
    #: A stored derivation, and argued rather than assumed. The cut-off is on the
    #: `policy_runs` row and is immutable, so a reader *could* subtract; what the
    #: column buys is that the arithmetic behind a boundary verdict is on the row
    #: a reviewer is looking at, next to the threshold it was measured against.
    #:
    #: It may be non-positive. A source that reports a push instant after the
    #: run's cut-off gives a negative age, and the honest reading of that is
    #: `present_and_maintained` -- a feedstock pushed to after the evidence
    #: boundary is certainly not one nobody has touched. `policies/feedstock.py`
    #: says so and a case pins it; no constraint forbids it, because forbidding it
    #: would turn somebody else's clock skew into a failed package.
    activity_age = models.DurationField(_("activity age"), null=True, blank=True, default=None, editable=False)

    #: How certain the package's identity was when this row was computed. See the
    #: class docstring for why the row records it, why the pass does not gate on
    #: it, and why there is no check constraint on it.
    confidence = models.CharField(
        _("confidence"),
        max_length=_VOCABULARY_LENGTH,
        choices=IdentityConfidence.choices,
        editable=False,
    )

    #: The feedstock observation this verdict rests on: the newest at the run's
    #: cut-off, or NULL where there was none. A verdict that named no observation
    #: could not be audited by a reader or explained to one, which is the same
    #: reason `PackageCurrency` references its four.
    feedstock_snapshot = models.ForeignKey(
        FeedstockSnapshot,
        on_delete=models.PROTECT,
        related_name="feedstock_presence_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("feedstock snapshot"),
    )

    #: What this run has to say about the verdict it reached, where the columns
    #: beside it do not already say it.
    #:
    #: Populated on exactly two verdicts. `unknown` for a feedstock that exists
    #: whose activity could not be dated needs a line, because the row's three
    #: measurement columns are all empty and a reader cannot otherwise tell that
    #: case from "nobody looked". `staged_recipe_pending` needs one, because the
    #: staged recipe's locator lives on the evidence row rather than here and the
    #: whole point of the verdict is that somebody should go and look at it.
    #:
    #: Empty everywhere else, which is the same rule every evidence table in this
    #: product applies to its own `detail`: an ordinary result needs no
    #: explanation, and a column populated on every row says nothing.
    detail = models.TextField(_("detail"), blank=True, default="", editable=False)

    class Meta:
        """The table the architecture names, not the `policies_packagefeedstockpresence` Django derives."""

        db_table = "package_feedstock_presence"
        verbose_name = _("package feedstock presence")
        verbose_name_plural = _("package feedstock presence")
        constraints = [
            # `CPM-AD-21`'s key, as a database rule rather than as the writer's
            # promise. A pass is called once per package per run, so a second row
            # for one pair means the pass ran twice or two passes wrote one table
            # -- and a reader joining this to the rollup would silently get
            # whichever the database returned first.
            models.UniqueConstraint(
                fields=["package", "policy_run"],
                name=ONE_FEEDSTOCK_ROW_PER_PACKAGE_PER_RUN,
            ),
            # `CPM-FR-40`'s parameter, as an invariant of the stored row rather
            # than only of the file it was read from. `policies/parameters.py`
            # refuses a non-positive threshold at the read, and this is what holds
            # for the hand-written `INSERT` that read nothing: a row claiming a
            # verdict measured against zero would say every observed feedstock is
            # inactive the instant it was pushed to.
            #
            # The column is NOT NULL, so this expression is always true or false
            # and never the third thing a SQL CHECK can be.
            models.CheckConstraint(
                condition=models.Q(inactivity_threshold__gt=timedelta()),
                name=THRESHOLD_IS_A_POSITIVE_INTERVAL,
            ),
            # The biconditional between the measurement and what it was measured
            # from. An age with no instant is a number nothing supports; an
            # instant with no age is a measurement the run declined to make while
            # still reaching a verdict. Both halves are asserted because either
            # alone permits the other's row.
            models.CheckConstraint(
                condition=(
                    models.Q(last_recipe_activity_at__isnull=True, activity_age__isnull=True)
                    | models.Q(last_recipe_activity_at__isnull=False, activity_age__isnull=False)
                ),
                name=AN_AGE_EXACTLY_WHEN_THERE_IS_AN_INSTANT,
            ),
            # The policy's own invariant. `present_and_maintained` and
            # `present_and_inactive` are verdicts *about an age*: each is reached
            # by comparing one against the threshold, so a row carrying either
            # while recording no instant is a comparison against nothing -- and it
            # is precisely the row a reader would take as proof that somebody is,
            # or is not, maintaining the recipe.
            #
            # The converse is deliberately not asserted: a row carrying an instant
            # and some other verdict is not a contradiction, because a future
            # story may date a feedstock it nonetheless calls something else.
            models.CheckConstraint(
                condition=~models.Q(presence_status__in=MEASURED_VERDICTS)
                | models.Q(last_recipe_activity_at__isnull=False),
                name=MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT,
            ),
            # The evidence half of the same rule. All four of `CPM-FR-40`'s
            # verdicts are statements about what conda-forge holds, and every one
            # of them is read off a feedstock observation -- so a row carrying one
            # while referencing none is a claim about a package resting on
            # nothing, and it is the row every integration case here would have
            # to assume away. The four sentinels are exempt by construction:
            # `unknown` for a package nobody observed is the row this table exists
            # to write, and it is precisely the row that has no observation.
            models.CheckConstraint(
                condition=~models.Q(presence_status__in=DETERMINATE_VERDICTS)
                | models.Q(feedstock_snapshot__isnull=False),
                name=DETERMINATE_PRESENCE_NEEDS_AN_OBSERVATION,
            ),
        ]

    def __str__(self) -> str:
        """Return the package, the verdict and the threshold it was judged against.

        Returns:
            A one-line summary. Read off `package_id` rather than off `package`,
            for the reason `PackageCurrency.__str__` gives: the related object of
            an unsaved instance raises `RelatedObjectDoesNotExist`, and a
            `__str__` that raises breaks the two places a half-built object is
            most likely to be rendered, a debugger and a traceback.

        """
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        verdict = self.presence_status or "(no verdict)"
        threshold = "no threshold" if self.inactivity_threshold is None else str(self.inactivity_threshold)
        return f"feedstock of {scope}: {verdict} against {threshold}"


#: The unique constraint that makes `(package, policy_run)` the key `CPM-AD-21`
#: requires of the vulnerability table, by name, so the case that asserts the
#: refusal and the declaration that makes it cannot drift.
ONE_VULNERABILITY_ROW_PER_PACKAGE_PER_RUN: Final[str] = "one_vulnerability_row_per_package_per_run"

#: The constraint requiring the finding behind a status the run *established*, by
#: name.
DETERMINATE_STATUS_NEEDS_ITS_FINDING: Final[str] = "vulnerability_status_names_its_finding"

#: The constraint requiring the cross-reference behind an established KEV
#: membership, by name.
DETERMINATE_KEV_MEMBERSHIP_NEEDS_ITS_CROSS_REFERENCE: Final[str] = "kev_membership_names_its_cross_reference"

#: The constraint holding a risk level to a row that matched something, by name.
A_RISK_LEVEL_ONLY_WHERE_ADVISORIES_MATCHED: Final[str] = "risk_level_only_where_advisories_matched"

#: The constraint requiring every row to name the policy version that produced
#: it, by name.
VULNERABILITY_ROW_NAMES_ITS_POLICY_VERSION: Final[str] = "vulnerability_row_names_its_policy_version"

#: The two KEV memberships the catalog itself established, and therefore the two
#: that cannot be reached without the cross-reference row that established them.
#:
#: `not_established` is deliberately absent: it is exactly the membership a
#: package with no cross-reference gets, so requiring a row behind it would
#: forbid the row this column exists to be honest about. A tuple rather than two
#: literals inside the constraint, because
#: `DETERMINATE_KEV_MEMBERSHIP_NEEDS_ITS_CROSS_REFERENCE` and
#: `tests/unit/django_apps/test_vulnerability_policy.py` both name the same pair
#: and a second spelling of it is a constraint that stops matching what the pass
#: produces. It holds `KevMembership` values and no `OutcomeState` members, so it
#: is not the shape `tests/unit/django_apps/test_single_ordering_audit.py` reads
#: -- and it is not an order in any case: `KEV_MEMBERSHIP_PRECEDENCE` is where the
#: ranking lives, and these two are not adjacent in it.
ESTABLISHED_KEV_MEMBERSHIPS: Final[tuple[str, ...]] = (KEV_LISTED, KEV_NOT_LISTED)

#: The two vulnerability statuses this run *established*, and therefore the two
#: that cannot be reached without the finding that established them.
#:
#: **`no_advisory_matched` is here for the same reason `advisories_matched` is**,
#: and it was added because the sibling rule was being held on one half only. It
#: is not the milder of the pair: it is the value a read surface is likeliest to
#: paint green, and a row carrying it while referencing no finding would be a
#: claim that a source was read, made by a row that cannot show a source was ever
#: asked. Unreachable from `VulnerabilityPass`, which derives both *from* a
#: finding -- which is exactly what `PackageCurrency`'s constraints are for too:
#: the rule is held at the database for the hand-written `INSERT` that went round
#: the pass.
#:
#: `unknown` is deliberately absent, on exactly the terms `not_established` is
#: absent from `ESTABLISHED_KEV_MEMBERSHIPS`: it is the status of a package with
#: no evidence at all, so requiring a finding behind it would forbid the row this
#: vocabulary exists to be honest about.
ESTABLISHED_VULNERABILITY_STATUSES: Final[tuple[str, ...]] = (ADVISORIES_MATCHED, NO_ADVISORY_MATCHED)


class PackageVulnerability(models.Model):
    """What one policy run concluded about one package's advisory exposure. Table `package_vulnerability`.

    `CPM-FR-17` as a row: one vulnerability status per package, one KEV
    membership beside it in a column of its own, and a risk level drawn from a
    versioned severity order. Named by the same convention `package_currency`,
    `package_feedstock_presence` and `package_health` are.

    **This is not the health rollup, and the word "rollup" in the story's title
    does not mean that table.** `CPM-AD-21` says no pass writes
    `package_health`; each writes only its own per-domain table keyed
    `(package, policy_run)`, and `CPM-EP-PRIORITY` owns the orchestrating writer.
    This table is the reduction of many findings to one per-package result, and
    it is the only thing this pass writes. It contributes **no** rollup column at
    all, which is the one way its two shipped siblings differ from it: the rollup
    offers none for this domain and adding one would be the new column the
    story's Never list forbids.

    **`kev_membership` is a stored column and never a number, and that is the
    whole point of the table.** `CPM-FR-17`'s one testable hazard is a severity
    score that averages a known-exploited advisory away -- one KEV entry among
    nine moderate findings coming out looking moderate. A design in which KEV
    contributed to `risk_level` can, for some combination of findings, produce a
    level that does not distinguish a KEV package from a non-KEV one; a separate
    column cannot, because a reader filters on it directly. So the requirement is
    the stronger one: KEV never becomes a number here, never contributes to an
    average, and never substitutes for the status. `policies/vulnerability.py` is
    where that is true of the arithmetic, and this column is where it is true of
    the schema.

    **Three values in `kev_membership`, not two.** `KevOutcome` has `listed` and
    `not_listed`; a package the KEV collector never ran for is neither, and
    recording it as `not_listed` would claim an absence the run never
    established. `KevMembership` carries `not_established` for exactly that, and
    the constraint below requires a cross-reference row behind the other two.

    **Every relation is `PROTECT`**, on exactly the terms `PackageCurrency`
    states: deleting a policy run under `CASCADE` would silently take away the
    findings that explain a verdict still naming it, and an evidence row is the
    *support* for that verdict -- a finding deleted out from under a row that
    cites it would leave the row claiming an advisory nothing can be shown for.

    **The two evidence references are nullable and the two verdicts are not.** A
    package with no evidence at the cut-off is `unknown` and `not_established`,
    which is a real, ordinary answer and the story's own AC 2 -- so both verdict
    columns always hold a value while the references have nothing to point at.
    `NULL` here is the absence of a row rather than a second spelling of a state.

    **This table copies the policy version and the cut-off, where its two
    siblings copy neither**, and that is a decision rather than an inconsistency.
    Both are on the `policy_runs` row this one references, so a reader *could*
    join -- but this pass's whole output is governed by a rule set chosen by
    version, and `CPM-FR-22`'s replay is a diff of two runs' rows over one
    cut-off. Carrying both means the diff is a query over this table alone, and
    means a row can never be read at a version it was not computed under. It is
    the same argument `PackageFeedstockPresence.inactivity_threshold` makes for
    storing the parameter it applied, one level up: what the row exists to record
    is a judgement made under stated rules, and the statement of those rules
    belongs on the row.

    **It still declares no `computed_at`, for the reason the module docstring
    gives.** `CPM-AD-11` requires that column of the *rollup*, and
    `tests/unit/django_apps/test_derived_status_writability_audit.py` uses it as
    the mark of the model `CPM-AD-11` governs. `core/policy_run.py` hands a pass
    no clock at all -- the clock reaches `compose_rollup` and nothing else -- so a
    `computed_at` here could only be a copy of an instant the referenced run
    already carries, which is the second spelling of one fact that docstring
    forbids. The status columns are `editable=False` regardless.
    """

    #: The package this finding is about, by the integer primary key `CPM-AD-3`
    #: fixes. Together with `policy_run` it is `CPM-AD-21`'s key, made a database
    #: rule by the constraint below.
    #:
    #: `related_name` is `vulnerability_policy_findings` and not
    #: `vulnerability_findings`, because `collectors.VulnerabilityFinding`
    #: already claims that accessor on `Package`. The two are evidence and
    #: verdict about one subject, and a shared accessor would make
    #: `package.vulnerability_findings` mean whichever application imported last.
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        related_name="vulnerability_policy_findings",
        verbose_name=_("package"),
    )

    #: The run that computed this row.
    policy_run = models.ForeignKey(
        PolicyRun,
        on_delete=models.PROTECT,
        related_name="vulnerability_policy_findings",
        verbose_name=_("policy run"),
    )

    #: What this run concluded about the package's advisory exposure.
    #: `editable=False`: a derived verdict is a policy run's to write and nobody
    #: else's (`CPM-FR-37`), and the declaration leaves the field out of every
    #: `ModelForm`, out of the admin and out of `full_clean()`'s validation of
    #: user-supplied data.
    #:
    #: `no_advisory_matched` and `unknown` are different values on purpose and
    #: `policies/outcomes.py` argues it: "the source was read and matched
    #: nothing" is an established negative, and "nobody looked", "the look
    #: failed" and "the source did not know the package" are three ways of
    #: establishing nothing. Neither is clean.
    vulnerability_status = models.CharField(
        _("vulnerability status"),
        max_length=VULNERABILITY_STATE_LENGTH,
        choices=PackageVulnerabilityOutcome.choices,
        editable=False,
    )

    #: Whether the KEV catalog lists any advisory this run recorded against the
    #: package -- the column `CPM-FR-17` is about. See the class docstring for
    #: why it is a column rather than a contribution to `risk_level`, and
    #: `policies/outcomes.py` for why it carries three values.
    #:
    #: **Named `kev_membership` and deliberately not `kev_status`.**
    #: `tests/unit/django_apps/test_outcome_field_audit.py` recognises a derived
    #: status by name and would then require the four `OutcomeState` sentinels of
    #: this column -- four more ways of spelling `not_established` on a column
    #: whose whole point is that there is exactly one. It is a membership, the
    #: way `authority_order_source` is a provenance.
    kev_membership = models.CharField(
        _("KEV membership"),
        max_length=KEV_MEMBERSHIP_LENGTH,
        choices=KevMembership.choices,
        editable=False,
    )

    #: `CPM-FR-17`'s risk level: the worst-ranked severity among the advisories
    #: matched to this package, by the order this run's policy version records.
    #:
    #: **No `choices`, and that is the shape of the decision rather than an
    #: omission.** The labels are versioned data in
    #: `policies/data/policy-parameters.toml` (`CPM-AD-8`), so the set of values
    #: this column may hold is a property of the run's policy version rather than
    #: of the schema -- declaring `choices` here would freeze into code the
    #: severity taxonomy nobody has decided, which is exactly what shipping the
    #: parameter as data avoids. `policy_version` beside it is what says which
    #: order a given value was drawn from, and `parameters.py` is what stops the
    #: file recording a label this column could not hold.
    #:
    #: Blank means missing (PRD Appendix A.1) and is an ordinary answer: a
    #: package nothing matched has no risk level, and so has one whose matched
    #: advisories state no severity or state severities the version does not
    #: rank. The row's `detail` says which of those it is, because the blank
    #: alone cannot.
    risk_level = models.CharField(
        _("risk level"),
        max_length=MAX_RISK_LEVEL_CHARACTERS,
        blank=True,
        default="",
        editable=False,
    )

    #: The policy version whose parameters produced this row, copied from the run
    #: (`CPM-AD-8`). See the class docstring for why this table copies it where
    #: its siblings do not.
    policy_version = models.CharField(_("policy version"), max_length=_POLICY_VERSION_LENGTH, editable=False)

    #: The instant this row's evidence was read as of, copied from the run
    #: (`CPM-AD-21`). Never NULL: a pass is never called without one, and a row
    #: that could not say what it was as of could not be replayed against.
    evidence_cutoff = models.DateTimeField(_("evidence cutoff"), editable=False)

    #: The vulnerability finding this status rests on: the first, in the read's
    #: stated order, whose own verdict is the one the row carries. NULL where
    #: there was no finding at the cut-off at all.
    #:
    #: One reference where the reduction may have read several rows, and what
    #: that costs is stated rather than left to be discovered: a package with
    #: nine matched advisories names one of them here, and the rest are one query
    #: away on `vulnerability_findings` filtered by the package and this row's
    #: `evidence_cutoff`. What the reference buys is that the verdict names an
    #: observation a reader can open -- which is the same thing
    #: `PackageCurrency`'s four references buy, and the same limitation its
    #: `conda_package_snapshot` records for a table with one row per pair.
    vulnerability_finding = models.ForeignKey(
        VulnerabilityFinding,
        on_delete=models.PROTECT,
        related_name="vulnerability_policy_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("vulnerability finding"),
    )

    #: The KEV cross-reference this membership rests on, on the same terms. NULL
    #: where no cross-reference existed at the cut-off -- which is precisely the
    #: `not_established` row, and is why the constraint below requires one only
    #: of the two memberships the catalog itself established.
    kev_finding = models.ForeignKey(
        KevFinding,
        on_delete=models.PROTECT,
        related_name="vulnerability_policy_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("KEV finding"),
    )

    #: What this run has to say about the verdict it reached, where the columns
    #: beside it do not already say it.
    #:
    #: Populated on exactly the shapes whose reason is not readable off the row:
    #: a status of `unknown` reached from an `error` or a `not_found` finding
    #: rather than from no evidence at all, and a blank `risk_level` on a row
    #: that did match advisories. Empty everywhere else, which is the rule every
    #: table in this product applies to its own `detail`: an explanation of an
    #: unremarkable row is noise.
    detail = models.TextField(_("detail"), blank=True, default="", editable=False)

    class Meta:
        """The table the architecture names, not the `policies_packagevulnerability` Django derives."""

        db_table = "package_vulnerability"
        verbose_name = _("package vulnerability")
        verbose_name_plural = _("package vulnerability")
        constraints = [
            # `CPM-AD-21`'s key, as a database rule rather than as the writer's
            # promise, on exactly the terms the two sibling tables state.
            models.UniqueConstraint(
                fields=["package", "policy_run"],
                name=ONE_VULNERABILITY_ROW_PER_PACKAGE_PER_RUN,
            ),
            # The status's own invariant, over **both** values this run can
            # establish. `advisories_matched` is a claim that an advisory source
            # matched an advisory to this package, and `no_advisory_matched` is a
            # claim that a source was read and matched none; each is reached by
            # reading a finding that says so, and a row carrying either while
            # referencing nothing is a security verdict resting on nothing. The
            # second half is the one a reader is likelier to trust, because it is
            # the half that looks clean.
            #
            # The converse is deliberately not asserted: a row referencing a
            # finding and reading `unknown` is the ordinary shape of an errored
            # lookup, and a row referencing nothing and reading `unknown` is the
            # ordinary shape of a package nobody looked at.
            #
            # No column tested here is the third thing a SQL CHECK can be: the
            # status is NOT NULL and an `IS NULL` test is never itself NULL.
            models.CheckConstraint(
                condition=~models.Q(vulnerability_status__in=ESTABLISHED_VULNERABILITY_STATUSES)
                | models.Q(vulnerability_finding__isnull=False),
                name=DETERMINATE_STATUS_NEEDS_ITS_FINDING,
            ),
            # The membership's own invariant, and the one this story exists to
            # make a schema rule. `listed` and `not_listed` are things the
            # *catalog* said, so each names the cross-reference that said it;
            # `not_established` is the row that says nothing was said, and
            # requiring evidence behind it would forbid the honest answer. A
            # `not_listed` with no cross-reference is exactly the claimed absence
            # the three-valued vocabulary exists to prevent.
            models.CheckConstraint(
                condition=~models.Q(kev_membership__in=ESTABLISHED_KEV_MEMBERSHIPS)
                | models.Q(kev_finding__isnull=False),
                name=DETERMINATE_KEV_MEMBERSHIP_NEEDS_ITS_CROSS_REFERENCE,
            ),
            # A risk level is a statement *about matched advisories*: it is the
            # worst-ranked severity among them, so a row carrying one while
            # matching nothing would be a severity for advisories nobody found.
            # The converse is not asserted -- a matched row with no risk level is
            # ordinary, and means the version ranks none of the severities its
            # findings stated.
            #
            # `risk_level` is NOT NULL and blank means missing, so this
            # expression is always true or false.
            models.CheckConstraint(
                condition=models.Q(risk_level="") | models.Q(vulnerability_status=ADVISORIES_MATCHED),
                name=A_RISK_LEVEL_ONLY_WHERE_ADVISORIES_MATCHED,
            ),
            # `CPM-AD-8` in the column that carries it. A row whose version names
            # nothing cannot be replayed and cannot say which severity order its
            # risk level was drawn from -- and `core/ledger.py` already refuses a
            # policy run whose version names nothing, so this holds the same rule
            # for the hand-written `INSERT` that went round it.
            models.CheckConstraint(
                condition=~models.Q(policy_version=""),
                name=VULNERABILITY_ROW_NAMES_ITS_POLICY_VERSION,
            ),
        ]

    def __str__(self) -> str:
        """Return the package, the status, the KEV membership and the risk level.

        Returns:
            A one-line summary. Read off `package_id` rather than off `package`,
            for the reason `PackageCurrency.__str__` gives: the related object of
            an unsaved instance raises `RelatedObjectDoesNotExist`, and a
            `__str__` that raises breaks the two places a half-built object is
            most likely to be rendered, a debugger and a traceback.

            The KEV membership is rendered beside the status rather than folded
            into it, which is this table's whole rule applied to the one line a
            human is likeliest to read.

        """
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        status = self.vulnerability_status or "(no verdict)"
        membership = self.kev_membership or "(no KEV answer)"
        risk = self.risk_level or "no risk level"
        return f"vulnerability of {scope}: {status}, KEV {membership}, {risk}"


#: The unique constraint that makes `(package, policy_run)` the key `CPM-AD-21`
#: requires of the licence table, by name, so the case that asserts the refusal
#: and the declaration that makes it cannot drift.
ONE_LICENSE_ROW_PER_PACKAGE_PER_RUN: Final[str] = "one_license_row_per_package_per_run"

#: The constraint requiring the finding behind an outcome the run *judged*, by
#: name.
THE_JUDGED_LICENSE_OUTCOME_NEEDS_ITS_FINDING: Final[str] = "license_outcome_names_its_finding"

#: The constraint requiring the rule behind an outcome a rule produced, by name.
#: This is the one this story exists to make a schema rule -- see the class
#: docstring.
A_RULED_OUTCOME_NAMES_THE_RULE_THAT_PRODUCED_IT: Final[str] = "license_outcome_names_the_rule_that_produced_it"

#: The constraint forbidding a matched rule on a row no rule decided, by name.
A_MATCHED_RULE_ONLY_WHERE_A_RULE_DECIDED: Final[str] = "license_rule_only_where_a_rule_decided"

#: The constraint requiring every row to name the policy version that produced
#: it, by name.
LICENSE_ROW_NAMES_ITS_POLICY_VERSION: Final[str] = "license_row_names_its_policy_version"

#: Every licence outcome this run reached *about an established licence*, and
#: therefore every one that cannot be reached without the finding that
#: established it.
#:
#: The three a rule can state plus `manual_review`, which is the outcome for a
#: licence this run established and no rule names -- so it too rests on a row
#: that said what the licence is. A row carrying it while referencing nothing
#: would claim a licence was established by a run that cannot show any channel
#: was ever read, and it is the claim a reader is *least* likely to check,
#: because "somebody has to look at this" reads as a to-do rather than as an
#: assertion.
#:
#: `unknown` is deliberately absent, on exactly the terms `not_established` is
#: absent from `ESTABLISHED_KEV_MEMBERSHIPS`: it is the outcome of a package with
#: no licence evidence at all, so requiring a finding behind it would forbid the
#: row this vocabulary exists to be honest about.
#:
#: A tuple rather than four literals inside the constraint, because
#: `THE_JUDGED_LICENSE_OUTCOME_NEEDS_ITS_FINDING` and
#: `tests/unit/django_apps/test_licence_policy.py` both name the same set and a
#: second spelling of it is a constraint that stops matching what the pass
#: produces. It holds `PackageLicenseOutcome` values and no `OutcomeState`
#: members, so it is not the shape
#: `tests/unit/django_apps/test_single_ordering_audit.py` reads -- and it is not
#: an order in any case: `LICENSE_PRECEDENCE` is where the ranking lives, and
#: these four are not contiguous in it.
JUDGED_LICENSE_OUTCOMES: Final[tuple[str, ...]] = (*RULE_DISPOSITIONS, MANUAL_REVIEW)


class PackageLicense(models.Model):
    """What one policy run concluded about one package's licence compliance. Table `package_license`.

    `CPM-FR-18` as a row: one licence outcome per package, drawn from a rule set
    held as versioned data. Named by the same convention `package_currency`,
    `package_feedstock_presence`, `package_vulnerability` and `package_health`
    are.

    **`allowed` is never a default and never an absence, and this table is where
    that stops being the pass's promise.** Every other outcome here is reachable
    by something *not* happening -- no rule matched, no rule set was recorded, the
    channel stated no licence, the read failed, there was no evidence at all --
    and each of those reaches `manual_review` or `unknown`, which claim nothing.
    `allowed` is the one value that asserts a compliance decision, and the one
    whose appearance in error would be least likely to be noticed, because it
    looks like good news. So `A_RULED_OUTCOME_NAMES_THE_RULE_THAT_PRODUCED_IT`
    requires the row to name the rule: an `allowed` row that names none is
    refused by PostgreSQL, not merely avoided by `policies/licence.py`.

    The constraint covers `restricted` and `forbidden` too, and that is
    deliberate rather than incidental. All three are reachable only from a rule's
    recorded disposition, so holding the rule on one of them and not the others
    would be the sibling rule held on one half only --
    `ESTABLISHED_VULNERABILITY_STATUSES` records what that cost the last time.
    `allowed` is the value the rule exists *for*; it is not the only value it is
    true of.

    **`manual_review` and `unknown` are two values and never one.** `unknown`
    means the licence itself was never established -- no evidence at the cut-off,
    a channel that stated none, one that stated something `collectors/spdx.py`
    will not normalize without guessing, one that could not be read, or a sweep
    in which no monitored channel serves the package at all.
    `manual_review` means the licence *is* known and
    this product has no rule for it, which today is every package with a licence,
    because PRD Open Question 2 is unanswered and the shipped rule set is empty.
    A reader has to be able to tell "fix the evidence" from "decide the policy",
    and collapsing the two would hide which they are being asked to do.

    **This is not the health rollup and contributes no column to it.**
    `CPM-AD-21` says no pass writes `package_health`; each writes only its own
    per-domain table keyed `(package, policy_run)`, and `CPM-EP-PRIORITY` owns
    the orchestrating writer. `tests/passes.py`'s synthetic rollup declares a
    `licence_status` column precisely because the real rollup does not, and this
    story does not add one.

    **Every relation is `PROTECT`**, on exactly the terms `PackageCurrency`
    states: deleting a policy run under `CASCADE` would silently take away the
    findings that explain a verdict still naming it, and an evidence row is the
    *support* for that verdict -- a finding deleted out from under a row that
    cites it would leave the row claiming a licence nothing can be shown for.

    **The evidence reference is nullable and the outcome is not.** A package with
    no licence evidence at the cut-off is `unknown`, which is a real, ordinary
    answer and a matrix row of its own -- so the outcome column always holds a
    value while the reference has nothing to point at. `NULL` here is the absence
    of a row rather than a second spelling of a state.

    **It copies the policy version and the cut-off**, on exactly the terms
    `PackageVulnerability` argues: this pass's whole output is governed by a rule
    set chosen by version, and `CPM-FR-22`'s replay is a diff of two runs' rows
    over one cut-off. Carrying both means the diff is a query over this table
    alone, and means a row can never be read at a version it was not computed
    under -- which matters more here than anywhere, because the same expression
    reads `manual_review` at today's empty rule set and may read `forbidden` at
    tomorrow's.

    **It declares no `computed_at`**, for the reason the module docstring gives:
    `CPM-AD-11` requires that column of the *rollup*, and `core/policy_run.py`
    hands a pass no clock at all, so the only value such a column could hold is a
    copy of an instant the referenced run already carries.
    """

    #: The package this finding is about, by the integer primary key `CPM-AD-3`
    #: fixes. Together with `policy_run` it is `CPM-AD-21`'s key, made a database
    #: rule by the constraint below.
    #:
    #: `related_name` is `license_policy_findings` and not `license_findings`,
    #: because `collectors.LicenseFinding` already claims that accessor on
    #: `Package` -- the same collision `PackageVulnerability` records, and
    #: resolved the same way.
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        related_name="license_policy_findings",
        verbose_name=_("package"),
    )

    #: The run that computed this row.
    policy_run = models.ForeignKey(
        PolicyRun,
        on_delete=models.PROTECT,
        related_name="license_policy_findings",
        verbose_name=_("policy run"),
    )

    #: What this run concluded about the package's licence compliance.
    #: `editable=False`: a derived verdict is a policy run's to write and nobody
    #: else's (`CPM-FR-37`), and the declaration leaves the field out of every
    #: `ModelForm`, out of the admin and out of `full_clean()`'s validation of
    #: user-supplied data.
    #:
    #: Named `license_outcome` and not `license_status`, and either would have
    #: satisfied `tests/unit/django_apps/test_outcome_field_audit.py` -- both
    #: suffixes are in its convention. `outcome` is the word `CPM-FR-18` uses and
    #: the word `collectors/outcomes.py` uses for the evidence one level down, so
    #: the two columns a reviewer joins are named alike.
    license_outcome = models.CharField(
        _("license outcome"),
        max_length=LICENSE_STATE_LENGTH,
        choices=PackageLicenseOutcome.choices,
        editable=False,
    )

    #: The normalized expression the rule that decided this row names, exactly as
    #: the reviewed file spells it -- the audit trail for `allowed`.
    #:
    #: **No `choices`, on exactly the terms `PackageVulnerability.risk_level`
    #: states.** The rules are versioned data in
    #: `policies/data/policy-parameters.toml` (`CPM-AD-8`), so the set of values
    #: this column may hold is a property of the run's policy version rather than
    #: of the schema -- declaring `choices` here would freeze into code the
    #: licence policy PRD Open Question 2 says nobody has decided, which is
    #: exactly what shipping the rules as data avoids. `policy_version` beside it
    #: says which rule set a given value was drawn from, and
    #: `policies/parameters.py` is what stops the file recording an expression
    #: this column could not hold.
    #:
    #: Blank means no rule decided this row, which is `manual_review`, `unknown`,
    #: and today every package there is. The two constraints below make that a
    #: biconditional rather than a convention: a ruled outcome names its rule and
    #: an unruled one names none.
    matched_rule = models.CharField(
        _("matched rule"),
        max_length=MAX_LICENSE_EXPRESSION_CHARACTERS,
        blank=True,
        default="",
        editable=False,
    )

    #: The policy version whose rule set produced this row, copied from the run
    #: (`CPM-AD-8`). See the class docstring for why this table copies it.
    policy_version = models.CharField(_("policy version"), max_length=_POLICY_VERSION_LENGTH, editable=False)

    #: The instant this row's evidence was read as of, copied from the run
    #: (`CPM-AD-21`). Never NULL: a pass is never called without one, and a row
    #: that could not say what it was as of could not be replayed against.
    evidence_cutoff = models.DateTimeField(_("evidence cutoff"), editable=False)

    #: The licence finding this outcome rests on: the first, in the read's stated
    #: order, whose own verdict is the one the row carries. NULL where there was
    #: no finding at the cut-off at all.
    #:
    #: One reference where the reduction may have read several rows -- one per
    #: monitored channel -- and what that costs is stated rather than left to be
    #: discovered: a package four channels disagree about names one of them here,
    #: and the rest are one query away on `license_findings` filtered by the
    #: package and this row's `evidence_cutoff`. The row's `detail` says the
    #: channels disagreed, so the reference is never the only sign of it.
    license_finding = models.ForeignKey(
        LicenseFinding,
        on_delete=models.PROTECT,
        related_name="license_policy_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("license finding"),
    )

    #: What this run has to say about the outcome it reached, where the columns
    #: beside it do not already say it.
    #:
    #: Populated on exactly the shapes whose reason is not readable off the row:
    #: a `manual_review` and which of its two causes it was, an `unknown` that has
    #: evidence behind it, and a package whose channels state different licences.
    #: Empty everywhere else, which is the rule every table in this product
    #: applies to its own `detail`: an explanation of an unremarkable row is
    #: noise.
    detail = models.TextField(_("detail"), blank=True, default="", editable=False)

    class Meta:
        """The table the architecture names, not the `policies_packagelicense` Django derives."""

        db_table = "package_license"
        verbose_name = _("package license")
        verbose_name_plural = _("package license")
        constraints = [
            # `CPM-AD-21`'s key, as a database rule rather than as the writer's
            # promise, on exactly the terms the three sibling tables state.
            models.UniqueConstraint(
                fields=["package", "policy_run"],
                name=ONE_LICENSE_ROW_PER_PACKAGE_PER_RUN,
            ),
            # The evidence half. All four judged outcomes are statements about a
            # licence this run *established*: three of them because a rule named
            # that licence, and `manual_review` because no rule named it -- and
            # both readings require the run to have read a channel that said what
            # the licence is. A row carrying one while referencing nothing is a
            # compliance verdict about a package whose licence was never
            # established.
            #
            # The converse is deliberately not asserted: a row referencing a
            # finding and reading `unknown` is the ordinary shape of a channel
            # that could not answer, and a row referencing nothing and reading
            # `unknown` is the ordinary shape of a package nobody has observed.
            #
            # No column tested here is the third thing a SQL CHECK can be: the
            # outcome is NOT NULL and an `IS NULL` test is never itself NULL.
            models.CheckConstraint(
                condition=~models.Q(license_outcome__in=JUDGED_LICENSE_OUTCOMES)
                | models.Q(license_finding__isnull=False),
                name=THE_JUDGED_LICENSE_OUTCOME_NEEDS_ITS_FINDING,
            ),
            # **The constraint this story exists to put in the schema.**
            # `allowed`, `restricted` and `forbidden` are things a *rule* said,
            # so each names the rule that said it. `allowed` is the one it is
            # written for: it is the only verdict in this product that claims
            # nothing is wrong, every other value here is reachable by an
            # absence, and a row reaching it without a rule would be a package
            # cleared by nobody -- read as good news and questioned by no one.
            # `manual_review` and `unknown` are outside the set because they are
            # precisely the rows no rule decided.
            #
            # `matched_rule` is NOT NULL and blank means missing, so this
            # expression is always true or false.
            models.CheckConstraint(
                condition=~models.Q(license_outcome__in=RULE_DISPOSITIONS) | ~models.Q(matched_rule=""),
                name=A_RULED_OUTCOME_NAMES_THE_RULE_THAT_PRODUCED_IT,
            ),
            # The other half of the same biconditional, and it is asserted where
            # the sibling tables leave their converses alone, because here the
            # converse is a contradiction rather than merely an unusual row: a
            # `manual_review` naming a matched rule says both that a rule decided
            # this licence and that none did. Together the two make
            # `matched_rule` readable as "the rule behind this outcome, or
            # nothing" rather than as a column whose meaning depends on which
            # value sits beside it.
            models.CheckConstraint(
                condition=models.Q(matched_rule="") | models.Q(license_outcome__in=RULE_DISPOSITIONS),
                name=A_MATCHED_RULE_ONLY_WHERE_A_RULE_DECIDED,
            ),
            # `CPM-AD-8` in the column that carries it, on the terms
            # `VULNERABILITY_ROW_NAMES_ITS_POLICY_VERSION` states. A row whose
            # version names nothing cannot be replayed and cannot say which rule
            # set its outcome was drawn from -- which matters most for the row
            # that says `manual_review`, since the answer at a later version may
            # be anything at all.
            models.CheckConstraint(
                condition=~models.Q(policy_version=""),
                name=LICENSE_ROW_NAMES_ITS_POLICY_VERSION,
            ),
        ]

    def __str__(self) -> str:
        """Return the package, the outcome and the rule that produced it.

        Returns:
            A one-line summary. Read off `package_id` rather than off `package`,
            for the reason `PackageCurrency.__str__` gives: the related object of
            an unsaved instance raises `RelatedObjectDoesNotExist`, and a
            `__str__` that raises breaks the two places a half-built object is
            most likely to be rendered, a debugger and a traceback.

            The rule is rendered beside the outcome rather than left to the
            column, because this table's whole rule is that a permissive verdict
            names what permitted it -- and the one line a human is likeliest to
            read is where that should be hardest to miss.

        """
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        outcome = self.license_outcome or "(no verdict)"
        rule = self.matched_rule or "no rule"
        return f"license of {scope}: {outcome} by {rule}"


#: The unique constraint that makes `(package, policy_run)` the key `CPM-AD-21`
#: requires of the remediation table, by name, so the case that asserts the
#: refusal and the declaration that makes it cannot drift.
ONE_REMEDIATION_ROW_PER_PACKAGE_PER_RUN: Final[str] = "one_remediation_row_per_package_per_run"

#: The constraint requiring the advisory finding behind a readiness the run
#: *derived*, by name.
A_DETERMINATE_READINESS_NEEDS_ITS_FINDING: Final[str] = "readiness_names_its_finding"

#: The constraint requiring a `ready` row to name the channel that carries the
#: fix, by name. This is the half of the story AC 1 asks for: a `ready` row that
#: names no surface is refused by the database.
A_READY_ROW_NAMES_THE_CHANNEL_THAT_CARRIES_THE_FIX: Final[str] = "ready_names_the_channel_that_carries_the_fix"

#: The constraint requiring an `awaiting_build` row to name the recipe that
#: carries the fix, by name.
AN_AWAITING_BUILD_ROW_NAMES_THE_RECIPE_THAT_CARRIES_THE_FIX: Final[str] = (
    "awaiting_build_names_the_recipe_that_carries_the_fix"
)

#: The constraint requiring an `awaiting_packaging` row to name the released
#: surface that carries the fix, by name. Either of two surfaces satisfies it --
#: see the class docstring for why upstream and PyPI share one verdict.
AN_AWAITING_PACKAGING_ROW_NAMES_THE_RELEASE_THAT_CARRIES_THE_FIX: Final[str] = (
    "awaiting_packaging_names_the_release_that_carries_the_fix"
)

#: The constraint this story exists to put in the schema, by name: `blocked`
#: needs every surface read.
A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ: Final[str] = "blocked_needs_every_surface_read"

#: The constraint requiring the observation behind any surface that voted, by
#: name.
A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION: Final[str] = "decided_surface_names_its_observation"

#: The constraint requiring every row to name the policy version that produced
#: it, by name.
REMEDIATION_ROW_NAMES_ITS_POLICY_VERSION: Final[str] = "remediation_row_names_its_policy_version"

#: How wide the column holding the fixed version this row looked for is.
#:
#: Sized from `collectors.VulnerabilityFinding.fixed_range`, which is where the
#: value is read from: a column narrower than the evidence column it copies would
#: truncate a fix the collector recorded, and a truncated version compared for
#: equality is a `not_published` reading of a surface that actually carries it.
#: `tests/unit/django_apps/test_remediation_policy.py` reconciles the two
#: directly rather than trusting this comment.
_FIXED_VERSION_LENGTH: Final[int] = 1024

#: Which column holds each surface's fix availability and which holds the
#: observation it was read from, by `VersionSurface` value.
#:
#: The one place the four surfaces are tied to their eight columns, and it is
#: read rather than merely declared: `A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ` and
#: `A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION` below are both built from it, so a
#: surface added to `VersionSurface` without columns here fails at import, and a
#: column renamed without its entry drops out of both constraints rather than
#: silently going unchecked. It is `SURFACE_STATUS_FIELDS`' shape with the
#: evidence reference added, because this table's constraints are about the
#: reference as well as the verdict.
#:
#: **`policies/remediation.py` deliberately does *not* read it**, on exactly the
#: terms `SURFACE_STATUS_FIELDS` records: the pass spells the four `*_fix`
#: keywords literally in its `create()` call so that
#: `tests/unit/django_apps/test_derived_status_writability_audit.py` can see the
#: write, and it carries the four reference column names on its own
#: `SurfaceReader` table, because the four references are spread into the same
#: call and a spread from *this* mapping would tie a constraint's declaration to a
#: writer's argument list. Both spellings are reconciled against this table by a
#: case in `tests/unit/django_apps/test_remediation_policy.py` rather than by one
#: reading the other.
SURFACE_FIX_FIELDS: Final[dict[str, tuple[str, str]]] = {
    VersionSurface.SOURCE.value: ("source_fix", "source_snapshot"),
    VersionSurface.PYPI.value: ("pypi_fix", "pypi_snapshot"),
    VersionSurface.FEEDSTOCK.value: ("feedstock_fix", "feedstock_snapshot"),
    VersionSurface.CONDA_PACKAGE.value: ("conda_package_fix", "conda_package_snapshot"),
}

#: Every readiness this run *derived from an advisory finding*, and therefore
#: every one that cannot be reached without the finding that named the fix.
#:
#: The four `CPM-FR-41` names. `unknown` is deliberately absent, on exactly the
#: terms `unknown` is absent from `ESTABLISHED_VULNERABILITY_STATUSES`: it is the
#: readiness of a package with no advisory evidence at all, so requiring a finding
#: behind it would forbid the row this vocabulary exists to be honest about.
#: `not_applicable` is absent for the stronger reason that it is precisely the row
#: for a package this run matched no advisory to -- there is no finding to name.
#:
#: A tuple rather than four literals inside the constraint, because
#: `A_DETERMINATE_READINESS_NEEDS_ITS_FINDING` and
#: `tests/unit/django_apps/test_remediation_policy.py` both name the same set and
#: a second spelling of it is a constraint that stops matching what the pass
#: produces. It holds `RemediationReadiness` values and no `OutcomeState`
#: members, so it is not the shape
#: `tests/unit/django_apps/test_single_ordering_audit.py` reads -- and it is not
#: an order in any case: `READINESS_PRECEDENCE` is where the ranking lives, and
#: these four are not contiguous in it.
DETERMINATE_READINESS_VERDICTS: Final[tuple[str, ...]] = (READY, AWAITING_BUILD, AWAITING_PACKAGING, BLOCKED)


def _every_surface_was_read() -> models.Q:
    """Return the condition that every per-surface column records an established absence.

    Built by walking `SURFACE_FIX_FIELDS` rather than by naming the four columns,
    so a fifth surface joins the constraint at the moment it acquires a column and
    a renamed column drops out of the check rather than going silently unchecked.
    The migration freezes whatever this produced on the day it ran, which is
    correct: a migration records what the schema was asked to be.

    Returns:
        The conjunction, one `Q(<column>=not_published)` per surface. No column
        here is nullable, so no conjunct can be the third thing a SQL CHECK can
        be.

    """
    condition = models.Q()
    for column, _reference in SURFACE_FIX_FIELDS.values():
        condition &= models.Q(**{column: FIX_NOT_PUBLISHED})
    return condition


def _every_decided_surface_names_its_observation() -> models.Q:
    """Return the condition that a surface which voted names the row it voted from.

    One implication per surface: either the surface was not read, or the
    observation it was read from is on the row. Built by walking
    `SURFACE_FIX_FIELDS` for the reason `_every_surface_was_read` is.

    Returns:
        The conjunction, one `Q(<column>=not_read) | Q(<reference>__isnull=False)`
        per surface. The reference columns are nullable, and an `IS NULL` test is
        never itself NULL, so no conjunct can be the third thing a SQL CHECK can
        be.

    """
    condition = models.Q()
    for column, reference in SURFACE_FIX_FIELDS.values():
        condition &= models.Q(**{column: SURFACE_NOT_READ}) | models.Q(**{f"{reference}__isnull": False})
    return condition


class PackageRemediation(models.Model):
    """What one policy run concluded about whether a package's findings can be acted on.

    Table `package_remediation`. `CPM-FR-41` as a row: is there a fixed version,
    where has it appeared, and therefore is this work a reviewer can do now or
    work that is waiting on somebody else. Named by the same convention
    `package_currency`, `package_feedstock_presence`, `package_vulnerability`,
    `package_license` and `package_health` are: the architecture names the schema,
    and a derived `policies_packageremediation` would make the table depend on
    which application happened to declare the model.

    **`blocked` is never reached by an absence, and this table is where that
    stops being the pass's promise.** `blocked` means the fixed version was looked
    for on every surface and found on none. A surface that was not read is not a
    surface where the fix is absent, so `A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ`
    requires all four per-surface columns to record an established absence before
    a row may carry it, and `A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION` requires
    each of those four absences to name the observation it was read from. A
    hand-written `INSERT` that went round `policies/remediation.py` entirely is
    refused by PostgreSQL.

    It is `PackageLicense`'s `allowed` rule turned round. There the danger is a
    permission reached by an absence, because it looks like good news; here it is
    an abandonment reached by an absence, because it tells a reviewer to stop
    looking. Both are absences masquerading as conclusions and both are held at
    the database rather than trusted to the writer.

    **No `blocked` row is exempt, and an earlier draft's exemption is why that is
    said rather than assumed.** The constraint carried a `Q(fixed_version="")`
    disjunct, admitting any `blocked` row that looked for nothing on the reasoning
    that an advisory which stated there is no fix has nothing for a surface to
    carry. No evidence this product records distinguishes an advisory that stated
    there is no fix from a feed that left the field blank
    (`collectors/vulnerability.py` writes one clause per *blank* field), so the
    exemption admitted exactly the rows the pass should never have written -- four
    `not_read` surfaces, blank fixed version, `blocked`. A finding with no fixed
    range is `unknown`; `policies/remediation.py` argues it at length.

    **`blocked` is currently unreachable, and the table keeps it anyway.** Nothing
    this product records can establish that a surface does not carry a version --
    each surface states its *latest*, not its contents -- so
    `policies/remediation.py` writes no `not_published` column today and no row
    reaches this verdict. The epic's AC 2 requires the value to exist and to be
    distinct from `ready` and `unknown`, and the two constraints below are what
    will hold it the day a version-ordering rule or a collector that records "the
    source stated there is no fix" makes it reachable. A value defined and
    guarded, with the gap recorded, is the honest shipping state; a value reached
    by an absence is not.

    **The per-surface answers are four columns rather than one flag.** AC 1 asks
    *where* the fix is, and a reviewer's next action differs by surface: upstream
    released it means wait for packaging, the recipe carries it means a build is
    due, a channel has it means install it now. Collapsing four surfaces into one
    boolean answers a question nobody asked -- the same argument
    `PackageCurrency`'s four per-surface verdicts make one domain over.

    **`awaiting_packaging` covers two surfaces and that is deliberate.** Upstream
    and PyPI both mean "released, not yet in the recipe", which is one next action;
    which of them released it is on `source_fix` and `pypi_fix` rather than folded
    into the verdict, so nothing is lost. `AN_AWAITING_PACKAGING_ROW_NAMES_THE_RELEASE_THAT_CARRIES_THE_FIX`
    is therefore the one constraint here whose antecedent is satisfied by either
    of two columns.

    **This is not the health rollup and contributes no column to it.**
    `CPM-AD-21` says no pass writes `package_health`; each writes only its own
    per-domain table keyed `(package, policy_run)`, and `CPM-EP-PRIORITY` owns the
    orchestrating writer. Nor does it hold a priority, a score, a rank or a work
    type: `CPM-FR-20` and PRD Open Question 8 own those and `CPM-SECURITY-S06`'s
    Never list forbids them here.

    **Every relation is `PROTECT`**, on exactly the terms `PackageCurrency`
    states: deleting a policy run under `CASCADE` would silently take away the
    findings that explain a verdict still naming it, and an evidence row is the
    *support* for that verdict -- a snapshot deleted out from under a row that
    cites it would leave the row claiming a fix nothing can be shown for.

    **The five evidence references are nullable and the five verdicts are not.** A
    package with no evidence at the cut-off is `unknown` with four `not_read`
    surfaces, which is a real, ordinary answer and a matrix row of its own -- so
    every verdict column always holds a value while the references have nothing to
    point at. `NULL` here is the absence of a row rather than a second spelling of
    a state.

    **It copies the policy version and the cut-off**, on exactly the terms
    `PackageVulnerability` and `PackageLicense` argue: `CPM-FR-22`'s replay is a
    diff of two runs' rows over one cut-off, and carrying both means the diff is a
    query over this table alone.

    **It declares no `computed_at`**, for the reason the module docstring gives:
    `CPM-AD-11` requires that column of the *rollup*, and `core/policy_run.py`
    hands a pass no clock at all, so the only value such a column could hold is a
    copy of an instant the referenced run already carries.
    """

    #: The package this finding is about, by the integer primary key `CPM-AD-3`
    #: fixes. Together with `policy_run` it is `CPM-AD-21`'s key, made a database
    #: rule by the constraint below.
    #:
    #: `related_name` is `remediation_findings`, which nothing else claims on
    #: `Package` -- unlike `PackageVulnerability` and `PackageLicense`, whose
    #: obvious accessors were already taken by the evidence tables they read.
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        related_name="remediation_findings",
        verbose_name=_("package"),
    )

    #: The run that computed this row.
    policy_run = models.ForeignKey(
        PolicyRun,
        on_delete=models.PROTECT,
        related_name="remediation_findings",
        verbose_name=_("policy run"),
    )

    #: What this run concluded about whether the package's findings can be acted
    #: on. `editable=False`: a derived verdict is a policy run's to write and
    #: nobody else's (`CPM-FR-37`), and the declaration leaves the field out of
    #: every `ModelForm`, out of the admin and out of `full_clean()`'s validation
    #: of user-supplied data.
    #:
    #: Named `readiness_status` rather than `readiness`, and the suffix is
    #: load-bearing: `tests/unit/django_apps/test_outcome_field_audit.py`
    #: recognises a derived status by name and then requires the four
    #: `OutcomeState` sentinels of it. This column carries them by construction --
    #: `RemediationReadiness` is composed by `outcome_type` -- so being inside that
    #: sweep is what it wants, where `kev_membership` and the four `*_fix` columns
    #: beside it deliberately are not.
    readiness_status = models.CharField(
        _("remediation readiness"),
        max_length=READINESS_STATE_LENGTH,
        choices=RemediationReadiness.choices,
        editable=False,
    )

    #: Whether the upstream source surface carries the fixed version.
    #:
    #: **Named `*_fix` and deliberately not `*_status`**, on exactly the terms
    #: `PackageVulnerability.kev_membership` records: the audit above recognises a
    #: derived status by name and would then require the four sentinels of a
    #: column whose whole point is that "this surface was not read" is exactly one
    #: value. `FixAvailability` carries three and no more.
    source_fix = models.CharField(
        _("source fix availability"),
        max_length=FIX_AVAILABILITY_LENGTH,
        choices=FixAvailability.choices,
        editable=False,
    )

    #: Whether the PyPI surface carries the fixed version. `not_read` here is
    #: ordinary rather than exceptional: `CPM-FR-8` records a non-Python package
    #: as inapplicable to PyPI, and a surface the question does not apply to has
    #: not said the fix is absent from it.
    pypi_fix = models.CharField(
        _("PyPI fix availability"),
        max_length=FIX_AVAILABILITY_LENGTH,
        choices=FixAvailability.choices,
        editable=False,
    )

    #: Whether the conda-forge recipe carries the fixed version -- the surface
    #: that reaches `awaiting_build`.
    feedstock_fix = models.CharField(
        _("feedstock fix availability"),
        max_length=FIX_AVAILABILITY_LENGTH,
        choices=FixAvailability.choices,
        editable=False,
    )

    #: Whether a monitored channel publishes the fixed version -- the one surface
    #: that reaches `ready`, because it is the only one a reviewer can install
    #: from.
    conda_package_fix = models.CharField(
        _("published conda package fix availability"),
        max_length=FIX_AVAILABILITY_LENGTH,
        choices=FixAvailability.choices,
        editable=False,
    )

    #: The fixed version this row looked for, in the form it was compared as.
    #:
    #: Stored rather than only referenced, unlike the version strings
    #: `PackageCurrency` leaves on its evidence rows: this is the value every one
    #: of the four surfaces was compared against, and the comparison is what the
    #: row exists to record. Evidence is append-only (`CPM-AD-2`), so the copy can
    #: never come to disagree with the finding it was read from.
    #:
    #: Blank means the row looked for nothing, which is three shapes and the
    #: `detail` says which: a matched finding that records no fixed range
    #: (`unknown`), an advisory whose recorded fix states a set of versions and
    #: cannot be compared without version-ordering semantics this product has not
    #: decided (`unknown`; no architecture decision owns version ordering yet), and
    #: an advisory sweep past its own freshness target (`unknown`, and no surface
    #: was asked).
    fixed_version = models.CharField(
        _("fixed version"),
        max_length=_FIXED_VERSION_LENGTH,
        blank=True,
        default="",
        editable=False,
    )

    #: Whether any surface this run read was past its collector's declared
    #: freshness target and was therefore not relied on (`CPM-FR-38`, AC 3).
    #:
    #: **A boolean beside the status rather than a sixth status value**, which is
    #: `core/freshness.py`'s own decision applied to a derived row: "staleness is
    #: a property of a status, not a status of its own", and every export carries
    #: a `<domain>_stale` companion. A `stale` member of `RemediationReadiness`
    #: would put a fifth axis back into the channel `CPM-FR-6` exists to keep
    #: un-collapsed and would break the audit that asserts the five fixed values.
    #:
    #: It is not itself a verdict and gates nothing: what a stale surface does is
    #: read `not_read`, so it can neither assert that the fix is available nor vote
    #: towards `blocked`. This column is how a reader sees that it happened, and
    #: the `detail` says which surfaces they were.
    #:
    #: **True for the advisory evidence as well as for the four surfaces.**
    #: `CPM-UJ-1`'s stated edge case is a finding older than its own freshness
    #: target, and a column that measured only the surfaces would report a
    #: month-old advisory sweep beside a channel refreshed this morning as fresh.
    #: Where the advisory sweep is stale the readiness is `unknown` and no surface
    #: is asked at all.
    evidence_stale = models.BooleanField(_("evidence stale"), default=False, editable=False)

    #: The policy version this row was computed under, copied from the run
    #: (`CPM-AD-8`). See the class docstring for why this table copies it.
    policy_version = models.CharField(_("policy version"), max_length=_POLICY_VERSION_LENGTH, editable=False)

    #: The instant this row's evidence was read as of, copied from the run
    #: (`CPM-AD-21`). Never NULL: a pass is never called without one, and a row
    #: that could not say what it was as of could not be replayed against.
    evidence_cutoff = models.DateTimeField(_("evidence cutoff"), editable=False)

    #: The advisory finding this readiness rests on: the first, in the read's
    #: stated order, whose own readiness is the one the row carries. NULL where
    #: this run matched no advisory to the package at all.
    #:
    #: One reference where the reduction may have read several matched advisories,
    #: and what that costs is stated rather than left to be discovered: a package
    #: with nine matched advisories names one of them here, and the rest are one
    #: query away on `vulnerability_findings` filtered by the package and this
    #: row's `evidence_cutoff`. The four per-surface columns and `fixed_version`
    #: are about *this* finding's fix and no other, which is what makes them
    #: readable at all -- two findings naming two fixed versions have two different
    #: sets of surface answers, and a row that mixed them would say nothing true.
    #: The row's `detail` says when there were several.
    vulnerability_finding = models.ForeignKey(
        VulnerabilityFinding,
        on_delete=models.PROTECT,
        related_name="remediation_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("vulnerability finding"),
    )

    #: The upstream-release observation `source_fix` was read from, or NULL where
    #: that surface was not read. The `source` half of `CPM-FR-16`'s "the evidence
    #: supporting it is stored with the result", applied to this domain -- and here
    #: it is more than an audit trail: `A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION`
    #: makes it the thing that stops `blocked` resting on a surface nobody read.
    source_snapshot = models.ForeignKey(
        SourceReleaseSnapshot,
        on_delete=models.PROTECT,
        related_name="remediation_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("source release snapshot"),
    )

    #: The PyPI observation `pypi_fix` was read from, on the same terms.
    pypi_snapshot = models.ForeignKey(
        PyPIReleaseSnapshot,
        on_delete=models.PROTECT,
        related_name="remediation_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("PyPI release snapshot"),
    )

    #: The feedstock observation `feedstock_fix` was read from, on the same terms.
    feedstock_snapshot = models.ForeignKey(
        FeedstockSnapshot,
        on_delete=models.PROTECT,
        related_name="remediation_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("feedstock snapshot"),
    )

    #: The published-package observation `conda_package_fix` was read from.
    #:
    #: One row, where `conda_package_snapshots` holds one per `(channel,
    #: platform)` pair -- and unlike `policies/currency.py`, this pass reads the
    #: **whole sweep** and this reference names whichever row of it decided the
    #: column: the pair that publishes the fixed version where one does, and
    #: otherwise the first in read order that states a version. See
    #: `policies/remediation.py` for why a single-row read would have made `ready`
    #: depend on which channel sorts first.
    conda_package_snapshot = models.ForeignKey(
        CondaPackageSnapshot,
        on_delete=models.PROTECT,
        related_name="remediation_findings",
        null=True,
        blank=True,
        default=None,
        verbose_name=_("conda package snapshot"),
    )

    #: What this run has to say about the readiness it reached, where the columns
    #: beside it do not already say it.
    #:
    #: Populated on exactly the shapes whose reason is not readable off the row:
    #: an `unknown` and which of its kinds it was, a `blocked` and which of its two
    #: it was, a surface whose evidence was stale and therefore not relied on, a
    #: package whose findings disagreed, and the equality limit wherever a surface
    #: stated a version that is not the fix. Empty everywhere else, which is the
    #: rule every table in this product applies to its own `detail`: an explanation
    #: of an unremarkable row is noise.
    detail = models.TextField(_("detail"), blank=True, default="", editable=False)

    class Meta:
        """The table the architecture names, not the `policies_packageremediation` Django derives."""

        db_table = "package_remediation"
        verbose_name = _("package remediation")
        verbose_name_plural = _("package remediation")
        constraints = [
            # `CPM-AD-21`'s key, as a database rule rather than as the writer's
            # promise, on exactly the terms the four sibling tables state.
            models.UniqueConstraint(
                fields=["package", "policy_run"],
                name=ONE_REMEDIATION_ROW_PER_PACKAGE_PER_RUN,
            ),
            # The evidence half. All four determinate verdicts are statements
            # about *a fix a finding named*, so each names the finding it was
            # derived from. A row carrying one while referencing nothing is a
            # claim about work a reviewer can or cannot do, made by a row that
            # cannot show any advisory was ever matched.
            #
            # The converse is deliberately not asserted: a row referencing a
            # finding and reading `unknown` is the ordinary shape of an advisory
            # whose fix cannot be compared, and a row referencing nothing and
            # reading `unknown` is the ordinary shape of a package with no
            # advisory evidence at all.
            #
            # No column tested here is the third thing a SQL CHECK can be: the
            # status is NOT NULL and an `IS NULL` test is never itself NULL.
            models.CheckConstraint(
                condition=~models.Q(readiness_status__in=DETERMINATE_READINESS_VERDICTS)
                | models.Q(vulnerability_finding__isnull=False),
                name=A_DETERMINATE_READINESS_NEEDS_ITS_FINDING,
            ),
            # AC 1's half: `ready` means a monitored channel publishes the fix, so
            # the row says that channel carries it. A `ready` row naming no surface
            # would be the one verdict in this table that sends a reviewer to
            # install something, resting on nothing.
            models.CheckConstraint(
                condition=~models.Q(readiness_status=READY) | models.Q(conda_package_fix=FIX_PUBLISHED),
                name=A_READY_ROW_NAMES_THE_CHANNEL_THAT_CARRIES_THE_FIX,
            ),
            # The same rule for the recipe verdict. Held on this one and on the
            # next as well as on `ready`, because a rule held on one value of a
            # family and not the others is the sibling defect
            # `ESTABLISHED_VULNERABILITY_STATUSES` records the cost of.
            models.CheckConstraint(
                condition=~models.Q(readiness_status=AWAITING_BUILD) | models.Q(feedstock_fix=FIX_PUBLISHED),
                name=AN_AWAITING_BUILD_ROW_NAMES_THE_RECIPE_THAT_CARRIES_THE_FIX,
            ),
            # And for the released-but-unpackaged verdict, which either release
            # surface may support: upstream and PyPI mean the same next action and
            # share one verdict, so the antecedent is satisfied by either column.
            models.CheckConstraint(
                condition=~models.Q(readiness_status=AWAITING_PACKAGING)
                | models.Q(source_fix=FIX_PUBLISHED)
                | models.Q(pypi_fix=FIX_PUBLISHED),
                name=AN_AWAITING_PACKAGING_ROW_NAMES_THE_RELEASE_THAT_CARRIES_THE_FIX,
            ),
            # **The constraint this story exists to put in the schema.** `blocked`
            # is an established absence: the fixed version was looked for on every
            # surface and found on none. A surface that was not read is not a
            # surface where the fix is absent, so a `blocked` row whose surfaces do
            # not all record `not_published` is refused. No exception, and the
            # exception that was here is the reason to say so: a
            # `Q(fixed_version="")` disjunct admitted any `blocked` row that looked
            # for nothing, which is precisely the shape a `blocked` reached from a
            # blank advisory field produced -- so the hole in the schema was cut to
            # exactly the size of the defect above it, and the claim that a
            # hand-written `INSERT` is refused by PostgreSQL was false for the one
            # row that mattered. `blocked` now requires four established absences
            # and nothing else does.
            models.CheckConstraint(
                condition=~models.Q(readiness_status=BLOCKED) | _every_surface_was_read(),
                name=A_BLOCKED_ROW_NEEDS_EVERY_SURFACE_READ,
            ),
            # The other half of the same property, and the one that makes the
            # constraint above mean something. A surface reads `not_published`
            # only from a determinate observation that stated a version, and reads
            # `published` only from one that stated the fix -- so either way it
            # voted, and a vote names the row it was cast from. Without this, four
            # `not_published` columns could be written by a caller that read
            # nothing, and `blocked` would be back to being reachable by silence.
            models.CheckConstraint(
                condition=_every_decided_surface_names_its_observation(),
                name=A_DECIDED_SURFACE_NAMES_ITS_OBSERVATION,
            ),
            # `CPM-AD-8` in the column that carries it, on the terms
            # `VULNERABILITY_ROW_NAMES_ITS_POLICY_VERSION` states. A row whose
            # version names nothing cannot be replayed and cannot say which
            # vocabulary its readiness was drawn from.
            models.CheckConstraint(
                condition=~models.Q(policy_version=""),
                name=REMEDIATION_ROW_NAMES_ITS_POLICY_VERSION,
            ),
        ]

    def __str__(self) -> str:
        """Return the package, the readiness and the fixed version it looked for.

        Returns:
            A one-line summary. Read off `package_id` rather than off `package`,
            for the reason `PackageCurrency.__str__` gives: the related object of
            an unsaved instance raises `RelatedObjectDoesNotExist`, and a
            `__str__` that raises breaks the two places a half-built object is
            most likely to be rendered, a debugger and a traceback.

            The fixed version is rendered beside the readiness because the one
            line a human is likeliest to read is where "blocked, having looked for
            nothing" should be hardest to mistake for "blocked, having looked
            everywhere".

        """
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        readiness = self.readiness_status or "(no verdict)"
        fixed = self.fixed_version or "no fixed version"
        return f"remediation of {scope}: {readiness} for {fixed}"
