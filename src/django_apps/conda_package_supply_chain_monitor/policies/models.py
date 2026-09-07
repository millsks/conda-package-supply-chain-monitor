"""The policy passes' own derived tables. One row per package per policy run, each.

`CPM-AD-21` gives every pass a per-domain table keyed `(package, policy_run)`.
`PackageCurrency` (`CPM-CURRENCY-S06`) was the first and `PackageFeedstockPresence`
(`CPM-CURRENCY-S07`) is the second; they are two tables and not one wide one,
because a pass writes only its own and a shared table would make "which pass
wrote this column" a convention rather than a schema. The key is what makes
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

**These are derived state, and they are not evidence.** Neither carries any of
the three marks `tests/model_registry.py` reads -- neither inherits
`AppendOnlyModel`, the app label is `policies`, and neither declares
`observed_at` -- so neither needs a `not_evidence` declaration and neither may
take one (`CPM-AD-2`'s escape is for a model that carries a mark, and
`tests/unit/django_apps/test_evidence_inheritance_audit.py` fails an unused one).

**Neither declares a `computed_at`, and the consequence is stated rather than
implied.** `CPM-AD-11` requires that column of the *rollup*, and
`tests/unit/django_apps/test_derived_status_writability_audit.py` uses it as the
mark of a model holding derived state -- so this table is outside that audit's
registry sweep. The instant this row was computed at is the run's, on the row
`policy_run` names, and a copy of it here would be a second spelling of one fact
on a row that already carries the reference. What the audit's *source* scan still
reaches is the write itself, in `policies/currency.py` and `policies/feedstock.py`,
each recorded in its exemption table by name. The status columns are declared
`editable=False` anyway: nothing but a policy run may write a derived verdict,
and that is true whether or not an audit is currently looking.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from django.db import models
from django.utils.translation import gettext_lazy as _

from conda_package_supply_chain_monitor.collectors.models import CondaPackageSnapshot
from conda_package_supply_chain_monitor.collectors.models import FeedstockSnapshot
from conda_package_supply_chain_monitor.collectors.models import PyPIReleaseSnapshot
from conda_package_supply_chain_monitor.collectors.models import SourceReleaseSnapshot
from conda_package_supply_chain_monitor.core.models import PolicyRun
from conda_package_supply_chain_monitor.identity.confidence import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.models import VersionSurface
from conda_package_supply_chain_monitor.policies.outcomes import ABSENT
from conda_package_supply_chain_monitor.policies.outcomes import BEHIND
from conda_package_supply_chain_monitor.policies.outcomes import CURRENCY_STATE_LENGTH
from conda_package_supply_chain_monitor.policies.outcomes import CURRENT
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_STATE_LENGTH
from conda_package_supply_chain_monitor.policies.outcomes import PRESENT_AND_INACTIVE
from conda_package_supply_chain_monitor.policies.outcomes import PRESENT_AND_MAINTAINED
from conda_package_supply_chain_monitor.policies.outcomes import STAGED_RECIPE_PENDING
from conda_package_supply_chain_monitor.policies.outcomes import CurrencyOutcome
from conda_package_supply_chain_monitor.policies.outcomes import FeedstockOutcome

__all__ = [
    "AN_AGE_EXACTLY_WHEN_THERE_IS_AN_INSTANT",
    "AUTHORITY_IS_A_KNOWN_SURFACE",
    "DETERMINATE_PRESENCE_NEEDS_AN_OBSERVATION",
    "DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY",
    "MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT",
    "MEASURED_VERDICTS",
    "ONE_FEEDSTOCK_ROW_PER_PACKAGE_PER_RUN",
    "ONE_ROW_PER_PACKAGE_PER_RUN",
    "SURFACE_STATUS_FIELDS",
    "THRESHOLD_IS_A_POSITIVE_INTERVAL",
    "AuthorityOrderSource",
    "PackageCurrency",
    "PackageFeedstockPresence",
]

#: How wide the two short vocabulary columns are. `VersionSurface`'s longest
#: value is `conda_package`, thirteen characters, and `AuthorityOrderSource`'s is
#: `package`, seven; the rest is headroom, so a fifth surface needs no migration
#: for the width alone. One number for both because they are the same kind of
#: value -- a fixed token from a closed vocabulary -- on the terms
#: `identity/models.py`'s `_VOCABULARY_LENGTH` states.
_VOCABULARY_LENGTH: Final[int] = 32

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
