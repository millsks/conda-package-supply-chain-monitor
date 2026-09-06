"""The currency pass's own derived table. One row per package per policy run.

`CPM-AD-21` gives every pass a per-domain table keyed `(package, policy_run)`,
and this is the first one. The key is what makes `CPM-FR-22`'s replay a
comparison rather than an overwrite: re-running the same policy version against
the same cut-off opens a *new* run, writes a new row, and leaves the original
where it was for the two to be diffed.

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

**This is derived state, and it is not evidence.** It carries none of the three
marks `tests/model_registry.py` reads -- it does not inherit `AppendOnlyModel`,
its app label is `policies`, and it declares no `observed_at` -- so it needs no
`not_evidence` declaration and must not take one (`CPM-AD-2`'s escape is for a
model that carries a mark, and
`tests/unit/django_apps/test_evidence_inheritance_audit.py` fails an unused one).

**It declares no `computed_at`, and the consequence is stated rather than
implied.** `CPM-AD-11` requires that column of the *rollup*, and
`tests/unit/django_apps/test_derived_status_writability_audit.py` uses it as the
mark of a model holding derived state -- so this table is outside that audit's
registry sweep. The instant this row was computed at is the run's, on the row
`policy_run` names, and a copy of it here would be a second spelling of one fact
on a row that already carries the reference. What the audit's *source* scan still
reaches is the write itself, in `policies/currency.py`, which is recorded in its
exemption table by name. The status columns are declared `editable=False` anyway:
nothing but a policy run may write a derived verdict, and that is true whether or
not an audit is currently looking.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import Final

from django.db import models
from django.utils.translation import gettext_lazy as _

from conda_package_supply_chain_monitor.collectors.models import CondaPackageSnapshot
from conda_package_supply_chain_monitor.collectors.models import FeedstockSnapshot
from conda_package_supply_chain_monitor.collectors.models import PyPIReleaseSnapshot
from conda_package_supply_chain_monitor.collectors.models import SourceReleaseSnapshot
from conda_package_supply_chain_monitor.core.models import PolicyRun
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.models import VersionSurface
from conda_package_supply_chain_monitor.policies.outcomes import BEHIND
from conda_package_supply_chain_monitor.policies.outcomes import CURRENCY_STATE_LENGTH
from conda_package_supply_chain_monitor.policies.outcomes import CURRENT
from conda_package_supply_chain_monitor.policies.outcomes import CurrencyOutcome

__all__ = [
    "AUTHORITY_IS_A_KNOWN_SURFACE",
    "DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY",
    "ONE_ROW_PER_PACKAGE_PER_RUN",
    "SURFACE_STATUS_FIELDS",
    "AuthorityOrderSource",
    "PackageCurrency",
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
