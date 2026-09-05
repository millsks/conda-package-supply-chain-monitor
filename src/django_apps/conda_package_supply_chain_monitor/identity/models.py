"""One mutable row per package, holding package identity and nothing else.

`CPM-AD-1`: "the `identity` app owns one mutable row per package holding **only**
canonical name, cross-ecosystem mappings, provenance and confidence. It holds no
derived status, no observation, and no workflow state." That sentence is the
whole of this module, and the reason it is a rule rather than a preference is
that the alternative is not recoverable: once a collector has written a version,
a CVE count or a build status onto the package row, the history of that value is
gone -- the row is mutable by construction, so every earlier value was
overwritten rather than superseded, and "what did we know, and when" stops being
answerable for the column. `CPM-AD-2` puts observations in an append-only log and
`CPM-AD-11` puts derived state in a rollup one writer owns; what is left for this
table is the identity, and the identity is stable.

**PRD Appendix A.1 is an export contract, not a table definition, and the two are
deliberately different shapes.** A.1 lists `priority_bucket`, `rank`, `score`,
`work_type`, `vulnerability_rollup`, `risk_level`, `latest_vuln_count`,
`priority_description`, `priority_source`, `priority_reason`,
`local_build_status`, `verified_at`, `platforms`, `apps`, `downloads`,
`versions`, `internal_component_count`, `internal_lob_count`, `tracking_title`
and `tracking_issue_url` in the same table as the identity fields, because an
export row is one line per package. Not one of them is a field here: the first
group is projected from the rollup (`CPM-AD-11`), the second from evidence, and
the usage signals are observed by the inventory collector into
`inventory_snapshots` (`CPM-AD-25`). `reporting` performs the projection at read
time, and `tests/unit/django_apps/test_identity_models.py` fails if any of those
names appears on `Package`.

**The stored names and the export headings are two contracts** (A.1, "Two
contracts"). Stored fields are snake_case identifiers; the historical report
headings the existing consumers read -- `Core_Python_Package_Name`,
`Conda-Forge_FeedStock_URL`, `JFROG_latest_vuln_count` -- belong to the reporting
layer's projection and never to a field name here. A field named for a heading
would make the projection look unnecessary, and the next export format would
either be wrong or would rename a column in the database.

**`canonical_name` is unique and is not a foreign-key target** (`CPM-AD-3`).
`unique=True` is what supplies the index -- Django's schema editor emits an
explicit one only for `db_index and not unique`, so a `db_index=True` beside it
is a second index the database maintains for nothing, which is the rule
`src/django_service/users/models.py:23` states and
`tests/unit/users/test_models.py` pins. The other half matters more: nothing in
this product references a package by its name, so correcting a name cascades
nowhere. Every evidence, rollup and workflow row takes the surrogate integer
primary key instead, which is also what makes the later non-Python phase a data
change rather than a schema migration.

**`resolved_at` is non-null and the caller supplies the instant.** `CPM-FR-2`
requires the resolution timestamp to be recorded and `CPM-AD-25` makes resolution
the only creator of a package row, so there is no state in which a `Package`
exists without one. It carries no `default=timezone.now` and no `auto_now_add`:
both read the process wall clock where the row is written, which
`EVIDENCE.01-AUDIT-002` fails and `tests/unit/django_apps/test_clock_audit.py`
enforces. The instant comes from an injected `Clock` (`CPM-AD-26`), exactly as
`RunLedgerModel.started_at` takes it. The model performs no awareness check of
its own -- that is the resolution service's, in `core/ledger.py`'s `_require_*`
shape, and it arrives with `CPM-IDENTITY-S02`.

**Neither model is evidence, and neither takes the escape.** `Package` declares
no `observed_at` and inherits no `AppendOnlyModel`, so it carries none of the
three marks `tests/model_registry.py` reads -- which means it also must not
declare `not_evidence = True`, because that attribute is `CPM-AD-2`'s recorded
exemption *for a model that carries a mark*, and a third user of it fails
`tests/unit/django_apps/test_evidence_inheritance_audit.py` until somebody
records the decision. A package row is not an observation; it is the thing
observations are about.

**What is deliberately absent, and whose it is.** Per-mapping `not_applicable` /
`unmapped` outcome columns are `CPM-IDENTITY-S02`'s, which owns resolution
semantics: `CPM-FR-1` needs a mapping that does not apply to be distinguishable
from one that failed and from a successful empty result, and that is resolution's
output rather than identity's shape. The override model and its audit row are
`CPM-IDENTITY-S05`'s (`CPM-AD-14`). Admin, serializers, views, URLs and tasks are
`CPM-EP-APP`'s. `core.CollectionRun.package_id` stays the integer `CPM-AD-3`
specifies and is not converted to a `ForeignKey` here -- see the story's design
notes: the conversion changes `core/ledger.py`'s recorder contract, and it
belongs to the story that first makes packages exist to point at.
"""

from __future__ import annotations

from typing import Final

from django.db import models
from django.utils.translation import gettext_lazy as _

__all__ = [
    "Feedstock",
    "IdentityConfidence",
    "Package",
]

#: How wide the short name columns are. A canonical package name, a display name,
#: a package type and the name of the source that resolved it are all names a
#: person or a registry chose, and 128 is what `core/models.py` already uses for
#: exactly that class of column -- one width for one kind of value, rather than a
#: new number per table.
_NAME_LENGTH: Final[int] = 128

#: How wide a cross-ecosystem identifier column is. A package URL carries a type,
#: a namespace, a name, a version and qualifiers in one string, and a CPE 2.3
#: name carries thirteen colon-separated components; both are machine-generated
#: and neither has a short bound worth guessing at. Sized like a URL rather than
#: like a name, and deliberately equal to `_URL_LENGTH` rather than ordered
#: against it -- these are the same *kind* of value, a generated string, and a
#: name is the thing that is different because a person chose it. The two stay
#: separate constants because they answer to different sources: a purl grows when
#: its specification adds a qualifier, a URL when a host adds a path segment.
_IDENTIFIER_LENGTH: Final[int] = 512

#: How wide a URL column is. `URLField`'s own default is 200, which is a Django
#: default rather than a fact about repository URLs, and a feedstock metadata URL
#: on a deep path exceeds it easily. Declared here so the three URL columns move
#: together.
_URL_LENGTH: Final[int] = 512

#: How wide the confidence column is. `IdentityConfidence`'s longest value is
#: `inventory-derived`, seventeen characters, and the rest is headroom: a fourth
#: value added by a later story needs no migration for the width alone. Not
#: sized against `core/models.py`'s `_STATUS_LENGTH`, which is 16 and holds a
#: different vocabulary -- `RunState`, whose longest member is nine characters.
#: Two vocabularies, two widths, each argued from its own longest value.
_CONFIDENCE_LENGTH: Final[int] = 32


class IdentityConfidence(models.TextChoices):
    """How certain a package identity is, in the PRD's own spelling.

    `verified`, `inventory-derived` and `unmapped`, verbatim from the PRD
    glossary and `CPM-AD-4`'s table. The hyphen in the middle value is
    deliberate and is not an oversight of `CPM-AD-5`'s fixed-lowercase rule:
    that rule binds *derived-status* vocabularies, the ones composed from
    `OutcomeState` and emitted verbatim on every read surface (`CPM-AD-24`).
    Confidence is neither. It is identity provenance -- a property of what
    resolution established, not a verdict a policy pass computed -- so it is a
    plain `TextChoices` declared here rather than a type composed by
    `core.outcomes.outcome_type`, and matching the governing document exactly is
    what keeps `CPM-IDENTITY-S03`'s gate from translating between two spellings
    of the same three values.

    The order is the one `CPM-AD-4`'s table uses, most certain first. It is
    presentation order and nothing reads it as a ranking: no precedence order
    over these values exists, and `CPM-AD-5`'s single total order is over
    `OutcomeState` and is `core`'s alone.

    Labels are Django's own derivation from the member names, which is why
    `INVENTORY_DERIVED` is spelled with an underscore while its *value* carries
    the PRD's hyphen: the value is the contract and the label is a display
    string.
    """

    VERIFIED = "verified"
    INVENTORY_DERIVED = "inventory-derived"
    UNMAPPED = "unmapped"


class Package(models.Model):
    """One unit of the monitored inventory, and its package identity. Table `packages`.

    See the module docstring for why the field set stops where it does, why
    `canonical_name` carries no `db_index`, and why this model is not evidence.

    The primary key is the project-wide `BigAutoField`
    (`config/settings/base.py:149`'s `DEFAULT_AUTO_FIELD`), which is the
    surrogate integer `CPM-AD-3` requires and the value every evidence, rollup
    and workflow row will reference.
    """

    #: The one correctable name for this package. `unique=True` and no
    #: `db_index`: unique already creates the index (`CPM-AD-3`), and a second
    #: one would be an index Django maintains for nothing. Nothing points at this
    #: column -- no `ForeignKey(..., to_field="canonical_name")` exists anywhere
    #: -- so correcting a name cascades nowhere.
    canonical_name = models.CharField(_("canonical name"), max_length=_NAME_LENGTH, unique=True)

    #: What a human sees, when the canonical name is not what a human calls it.
    #: Blank means missing rather than empty (PRD Appendix A.1's data rules), and
    #: the reporting layer falls back to the canonical name; a `NULL` here would
    #: add a second spelling of "missing" for no gain.
    display_name = models.CharField(_("display name"), max_length=_NAME_LENGTH, blank=True, default="")

    #: Where the package's source lives -- the upstream VCS identity `CPM-FR-1`
    #: resolves. Blank until resolution establishes one, because `CPM-FR-1` says
    #: a resolution that cannot establish a mapping records nothing rather than a
    #: guess.
    source_repository_url = models.URLField(_("source repository URL"), max_length=_URL_LENGTH, blank=True, default="")

    #: The package URL for the package's primary release ecosystem -- PyPI for
    #: the Python packages v1 targets (`CPM-FR-1`). One value, because "primary"
    #: is singular by definition; the rest are in `alternative_purls`.
    primary_purl = models.CharField(_("primary purl"), max_length=_IDENTIFIER_LENGTH, blank=True, default="")

    #: The purl *type* of the primary ecosystem, stored beside the purl it was
    #: taken from rather than parsed back out of it at read time. A stored
    #: identifier is what a later non-Python phase filters on (`CPM-AD-3`'s
    #: "data change, not a schema migration"), and parsing is not filtering.
    primary_type = models.CharField(_("primary type"), max_length=_NAME_LENGTH, blank=True, default="")

    #: The package URL naming this package as a conda artifact. Separate from
    #: `primary_purl` because conda is the ecosystem this product monitors *into*
    #: rather than the one a package is primarily released from, and collapsing
    #: the two would make "which ecosystem is authoritative" (`CPM-AD-6`)
    #: unanswerable from the row.
    conda_purl = models.CharField(_("conda purl"), max_length=_IDENTIFIER_LENGTH, blank=True, default="")

    #: Every other package URL derivable for this package (`CPM-FR-1`, "recorded
    #: when derivable"). A list column rather than a child table because nothing
    #: joins on one and nothing carries per-value state; `blank=True` is what
    #: makes an empty list a valid form value, and the column stays NOT NULL with
    #: a `list` default so "no identifiers" is `[]` and never `NULL`.
    alternative_purls = models.JSONField(_("alternative purls"), default=list, blank=True)

    #: The CPE names this package is known by, for advisory matching
    #: (`CPM-FR-1`). Multi-valued for the same reason and on the same terms as
    #: `alternative_purls`.
    cpes = models.JSONField(_("CPEs"), default=list, blank=True)

    #: Where this identity came from -- which resolver, catalogue or human path
    #: established it (`CPM-FR-2`). A name rather than a relation: resolvers are
    #: code, declared and never discovered (inherited `AD-8`), so there is no
    #: table for this to point at.
    identity_source = models.CharField(_("identity source"), max_length=_NAME_LENGTH, blank=True, default="")

    #: The key the identity source matched on, kept so a resolution can be
    #: re-derived and disputed rather than merely trusted (`CPM-FR-2`). Sized as
    #: an identifier because that is what it is: a source's own key, not a name a
    #: person chose.
    associator_key = models.CharField(_("associator key"), max_length=_IDENTIFIER_LENGTH, blank=True, default="")

    #: When this identity was resolved (`CPM-FR-2`, "the timestamp of the
    #: resolution is recorded"). Non-null: `CPM-AD-25` makes resolution the only
    #: creator of a package row, so there is no row without one. No `default` and
    #: no `auto_now_add` -- the writer supplies the instant from an injected
    #: `Clock` (`CPM-AD-26`), which is what makes a staleness assertion testable
    #: without waiting.
    resolved_at = models.DateTimeField(_("resolved at"))

    #: How certain the identity is, and therefore what automation may claim about
    #: the package (`CPM-FR-2`, `CPM-FR-5`, `CPM-AD-4`). Defaults to `unmapped`
    #: because that is the confidence `CPM-AD-25` creates the shell at: a package
    #: named by the inventory for the first time has an identity row before
    #: anything has resolved it, and the default is the honest value rather than
    #: a convenience.
    confidence = models.CharField(
        _("confidence"),
        max_length=_CONFIDENCE_LENGTH,
        choices=IdentityConfidence.choices,
        default=IdentityConfidence.UNMAPPED,
    )

    class Meta:
        """The table `CPM-AD-2`'s naming convention gives, not `identity_package`.

        Django would derive `identity_package` from the app label and the model
        name. It is rejected for the reason `core/models.py` rejects
        `core_collectionrun`: the tables in this product are named by the
        architecture and the PRD -- `packages` here, `collection_runs` and
        `policy_runs` in `core`, the evidence tables in PRD Appendix A.2 -- and a
        derived name would make the schema depend on which application happened
        to declare the model. Moving a model between applications must not rename
        its table.
        """

        db_table = "packages"
        verbose_name = _("package")
        verbose_name_plural = _("packages")
        constraints = [
            # `blank=False` is a *form* rule. `Package.objects.create()` never
            # runs a form, and neither will resolution or the ingestion path that
            # calls it, so without this the empty string is a canonical name the
            # database accepts -- once, because `unique=True` then refuses the
            # second one, which makes the failure look like a duplicate rather
            # than like the nameless row it is. A package with no name cannot be
            # corrected, cannot be exported and cannot be found again, so the
            # refusal belongs where every writer passes through.
            models.CheckConstraint(condition=~models.Q(canonical_name=""), name="canonical_name_is_present"),
        ]

    def __str__(self) -> str:
        """Return the canonical name, or say that there is not one yet.

        Returns:
            The canonical name, or a placeholder naming its absence. The
            placeholder means the instance was never saved: `canonical_name_is_present`
            makes a blank name impossible on a stored row, so a saved `Package`
            always renders as its name. An unsaved instance holds `""` for the
            column -- Django's default for a non-null `CharField` with no
            declared default -- and returning that would make a log line, an
            admin list or a failure message read as an empty string with no
            explanation.

        """
        return self.canonical_name or "(no canonical name)"


class Feedstock(models.Model):
    """One conda-forge feedstock a package maps to. Table `feedstocks`.

    **A second table because `CPM-FR-1` says "zero or more".** A single
    `feedstock_url` column on `Package` cannot hold two, and the packages that
    map to more than one are exactly the ones a reviewer needs to see whole. PRD
    Appendix A.1's rule that multi-value export columns "separate with `;`" is
    the export contract for precisely this: the reporting layer joins these child
    rows into `Conda-Forge_FeedStock_URL`, and neither the join nor the heading
    is a field name here.

    **`staged_recipe_pr_url` and `local_recipe_url` are deliberately not here.**
    A.1 groups them as "Conda-forge state" and "Internal packaging state", which
    is the state of an in-flight recipe rather than a mapping between ecosystems
    -- an observation, and therefore evidence (`CPM-AD-2`). `CPM-FR-9`'s feedstock
    collector records staged-recipe state separately from an existing feedstock,
    and it records it in its own evidence table.

    **`CASCADE`, and that is a decision.** A feedstock mapping has no meaning
    without the package it maps, so a package row that somehow went would leave
    an orphan describing nothing. `PROTECT` and `RESTRICT` are what
    `EVIDENCE.02-AUDIT-001` requires of relations that touch *evidence* models,
    because Django's deletion collector issues its `DELETE` through
    `sql.DeleteQuery` and goes past every append-only refusal -- neither of these
    models is evidence, so that rule does not reach here. Nothing deletes a
    package in this product either: `CPM-AD-25` says absence is recorded as an
    observation and no package row is ever deleted.
    """

    #: The package this feedstock maps. By the integer primary key `CPM-AD-3`
    #: fixes, never by `canonical_name` -- which is what makes correcting a name
    #: cascade nowhere.
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name="feedstocks",
        verbose_name=_("package"),
    )

    #: The feedstock's name on conda-forge, which is a name a recipe author chose
    #: rather than a derived value. Unique per package rather than globally -- see
    #: `Meta.constraints`.
    name = models.CharField(_("name"), max_length=_NAME_LENGTH)

    #: Where the feedstock repository lives. Blank means the mapping is known by
    #: name and the URL has not been established, which A.1's data rules make
    #: "missing" rather than "none" -- values are never invented.
    url = models.URLField(_("URL"), max_length=_URL_LENGTH, blank=True, default="")

    #: Where the feedstock's recipe metadata lives, when it is somewhere other
    #: than the repository root. Blank on the same terms as `url`.
    metadata_url = models.URLField(_("metadata URL"), max_length=_URL_LENGTH, blank=True, default="")

    class Meta:
        """The table the architecture names, not the `identity_feedstock` Django derives.

        Rejected for the reason `Package.Meta` gives: the schema is named by the
        architecture rather than by which application declares the model.
        """

        db_table = "feedstocks"
        verbose_name = _("feedstock")
        verbose_name_plural = _("feedstocks")
        constraints = [
            # Per package, not globally. Two packages may legitimately map to a
            # feedstock of the same name -- the constraint exists to stop *one*
            # package listing the same feedstock twice, which is a duplicate
            # mapping rather than a second one, and which would make
            # `package.feedstocks` answer "how many feedstocks" wrongly.
            models.UniqueConstraint(fields=["package", "name"], name="one_feedstock_name_per_package"),
            # And the same rule the parent's name carries, for the same reason:
            # `blank=False` is a form rule and nothing here runs a form. A
            # nameless feedstock is worse than a missing one, because it is
            # counted -- `package.feedstocks` returns it, so "this package has a
            # feedstock" reads true for a row naming nothing, which is precisely
            # the claim `CPM-FR-5` forbids making about an unresolved package.
            models.CheckConstraint(condition=~models.Q(name=""), name="feedstock_name_is_present"),
        ]

    def __str__(self) -> str:
        """Return the feedstock's name and the package it maps.

        Returns:
            A one-line summary naming the feedstock and the package it belongs
            to, or saying that either is absent. Read off `package_id` rather
            than `package`: the related object of an unsaved instance raises
            `RelatedObjectDoesNotExist`, and a `__str__` that raises is what a
            failure message would have been.

        """
        name = self.name or "(no name)"
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        return f"{name} for {scope}"
