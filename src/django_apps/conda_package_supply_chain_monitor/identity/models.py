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
shape, and `identity/services.py`'s `_require_aware` is where it lives. The same
rule and the same check apply to `PackageMapping.resolved_at` below.

**Neither model is evidence, and neither takes the escape.** `Package` declares
no `observed_at` and inherits no `AppendOnlyModel`, so it carries none of the
three marks `tests/model_registry.py` reads -- which means it also must not
declare `not_evidence = True`, because that attribute is `CPM-AD-2`'s recorded
exemption *for a model that carries a mark*, and a third user of it fails
`tests/unit/django_apps/test_evidence_inheritance_audit.py` until somebody
records the decision. A package row is not an observation; it is the thing
observations are about.

**Per-mapping outcomes are a third table, and they could not have been a
column.** `CPM-FR-1` needs a mapping that does not apply to be distinguishable
from one that failed and from a successful empty result -- three states, which no
nullable value column can carry. A column named `*_status` or `*_outcome` on
`Package` would also be swept into the derived-status vocabulary by
`tests/unit/django_apps/test_outcome_field_audit.py`, and `CPM-AD-1` says this
row holds no derived status at all. So the outcome moved to `PackageMapping`,
one row per `(package, kind)`, carrying why a value is absent and nothing the
package row already holds. The established *values* stay here, because they are
cross-ecosystem mappings and `CPM-AD-1` puts those on this row.

**The audit row is here and it is evidence, which is the one model in this
module that is.** `CPM-AD-14` puts the correction of a package identity on an
audited override path, `CPM-FR-32` says the record of it is append-only and
independently queryable, and `IdentityOverride` below is that record: it inherits
`core.models.AppendOnlyModel`, so the base refuses a re-save, an `update()` and a
`delete()` and the three registry audits reach it by construction. "Append-only"
is then machinery rather than a docstring. The classification carries obligations
-- `PROTECT` on every relation (`EVIDENCE.02-AUDIT-001`) and no unique constraint
of any kind (`EVIDENCE.02-AUDIT-003`) -- and both are what an audit row wants
anyway: deleting a user must not delete the record of what they decided, and two
corrections of one package are two rows.

**One row per human decision, never one per changed field.** An override may
correct the canonical name and the display name in one act, and PRD Appendix A.2
speaks of "prior value, new value" in the singular. One row per field would split
a single human decision across rows that have to be read back together to
reconstruct it; one row per decision, carrying each pair it changed, keeps "an
override" and "a row" the same thing -- which is what an auditor reviewing a
correction is actually looking for.

**`IdentityConfidence` is declared next door, in `identity/confidence.py`, and
re-exported from here.** It is still `identity`'s vocabulary and every importer
still spells it `identity.models.IdentityConfidence`; what moved is only the
*declaration*, into a leaf module that imports nothing, because `core/models.py`
reads it while this module now reads `core.models.AppendOnlyModel` -- and those
two edges together are an import cycle. That file records the reasoning at
length; the short version is that the vocabulary is the half of the pair that
depends on nothing, so it is the half that moves.

**What is still deliberately absent, and whose it is.** Admin, serializers, views,
URLs and tasks are `CPM-EP-APP`'s. `core.CollectionRun.package_id` stays the
integer `CPM-AD-3` specifies and is not converted to a `ForeignKey` here -- see
`CPM-IDENTITY-S01`'s design notes: the conversion changes `core/ledger.py`'s
recorder contract, and it belongs to the story that first makes packages exist to
point at.
"""

from __future__ import annotations

from typing import Final

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from conda_package_supply_chain_monitor.core.outcomes import outcome_type
from conda_package_supply_chain_monitor.core.roles import IDENTITY_OVERRIDE_CODENAME
from conda_package_supply_chain_monitor.identity.confidence import IdentityConfidence

__all__ = [
    "ESTABLISHED",
    "ESTABLISHED_MEMBER",
    "MAPPED_FIELDS",
    "OVERRIDE_READ_INDEX",
    "UNKNOWN",
    "Feedstock",
    "IdentityConfidence",
    "IdentityOverride",
    "MappingKind",
    "MappingOutcome",
    "Package",
    "PackageMapping",
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

#: How wide the two `PackageMapping` vocabulary columns are. `MappingKind`'s
#: longest value is `source_repository`, seventeen characters, and
#: `MappingOutcome`'s is `not_applicable`, fourteen; the rest is headroom, so a
#: sixth kind or a second determinate verdict needs no migration for the width
#: alone. One number for both because they are the same kind of value -- a fixed
#: token from a closed vocabulary -- and splitting them would be two numbers
#: nothing distinguishes.
_VOCABULARY_LENGTH: Final[int] = 32

#: How wide the correlation identifier is. `CPM-AD-15` takes it from the active
#: span formatted `032x`, so it is exactly 32 hexadecimal digits -- the same
#: number `core/models.py` declares for `CollectionRun.trace_id` and
#: `collectors/models.py` for `InventorySnapshot.trace_id`. Restated here rather
#: than imported, on the terms that module states: those constants are private to
#: their modules, and one spelling shared by import would still be three column
#: declarations. What keeps them in step is that each is 32 because the format
#: says 32, and `tests/integration/django_apps/test_run_ledger.py` pins the format.
_TRACE_ID_LENGTH: Final[int] = 32

#: The index the override history's one read needs, by name.
#:
#: An index is permitted on an evidence model and a unique *constraint* is not,
#: and the difference is exactly the one `CPM-AD-2` draws: an index makes a read
#: cheaper and changes no write, while a unique constraint would turn the second
#: correction of one package into an `IntegrityError`.
#: `tests/unit/django_apps/test_evidence_constraint_audit.py` reads
#: `Meta.constraints` and the field flags, never `Meta.indexes`.
#:
#: It serves the question `CPM-FR-32` makes askable -- what has been overridden on
#: this package, newest first -- in the order `Meta.ordering` asks it in. Django's
#: automatic foreign-key index covers the filter alone and leaves the sort to a
#: scan of that package's whole correction history. Django caps an index name at
#: 30 characters, which is why it does not spell out `identity_override`.
OVERRIDE_READ_INDEX: Final[str] = "identity_ovr_pkg_observed"


class MappingKind(models.TextChoices):
    """The mappings `CPM-FR-1` asks a resolution to establish, one member each.

    A **closed** vocabulary, and closed is the operative word: every mapping
    column this model holds belongs to exactly one member, `MAPPED_FIELDS` below
    states which, and `tests/unit/django_apps/test_identity_models.py` reconciles
    the two against `Package._meta`. A mapping column added without a kind would
    be a value no resolution could record an outcome for, and a kind added
    without a column would be an outcome about nothing.

    `CPM-FR-1` lists "a canonical name, a source repository, its release
    ecosystem identity (PyPI for the Python packages v1 targets), and zero or
    more conda-forge feedstocks", and adds that "cross-ecosystem identifiers
    (package URLs, CPEs) are recorded when derivable". The canonical name is not
    among the members: it is the package's own name rather than a mapping onto
    another ecosystem, it is never absent (`canonical_name_is_present`), and
    "this package has no name" is not a state `CPM-FR-1` asks anybody to record.

    `CONDA_ARTIFACT` is separate from `FEEDSTOCK` for the reason `conda_purl` is
    separate from the `Feedstock` rows: a feedstock is the *recipe* that builds a
    conda artifact, and a package can have the second without the first --
    `CPM-FR-9`'s staged-recipe state exists precisely because those two travel
    apart.

    Values are fixed lowercase tokens, matching the shape every stored
    vocabulary in this product uses. They are not an `OutcomeState` and carry no
    sentinel: a *kind* names which question was asked, and the answer is the
    `outcome` column beside it.
    """

    SOURCE_REPOSITORY = "source_repository"
    RELEASE_ECOSYSTEM = "release_ecosystem"
    CONDA_ARTIFACT = "conda_artifact"
    FEEDSTOCK = "feedstock"
    CROSS_ECOSYSTEM = "cross_ecosystem"


#: The determinate verdict `MappingOutcome` adds to `core`'s four sentinels,
#: declared once as the `(member name, value)` pair `outcome_type` takes.
#:
#: One pair rather than a member reference, because the composed type below is
#: built from it and `ESTABLISHED` is read back out of it: a second spelling of
#: `"established"` anywhere would be a value that could drift from the one the
#: column actually offers, which is the duplication `core/outcomes.py` exists to
#: prevent applied to this module.
ESTABLISHED_MEMBER: Final[tuple[str, str]] = ("ESTABLISHED", "established")

#: The mapping outcome vocabulary: `core`'s four sentinels plus `established`.
#:
#: **Bound once, at module scope, and that is load-bearing.** `outcome_type`
#: mints a distinct class on every call, so two calls would produce two types
#: whose members compare unequal as enum members and equal only as strings --
#: `core/outcomes.py` says so in as many words and
#: `tests/unit/django_apps/test_outcomes.py` pins it. This is the repository's
#: first production caller; every later per-status vocabulary follows this shape.
#:
#: Composed rather than written out. The four sentinels arrive by construction
#: with `core`'s own names, values and labels, which is what
#: `tests/unit/django_apps/test_outcome_field_audit.py` reads to prove the table
#: was not hand-rolled -- a hand-written table with the right values and Django's
#: own derived labels would pass a value check and fail that one.
#:
#: `established` rather than `ok`: `CPM-AD-5` says a per-status type refines the
#: generic determinate value into verdicts of its own, and what a resolution
#: determines is that the mapping *was established*, which is a fact about the
#: mapping rather than a clean bill of health. `core.outcomes.aggregate` cannot
#: rank it -- `PRECEDENCE` holds no composed determinate value -- and nothing
#: here aggregates one; see the story's design notes.
MappingOutcome: Final[type[models.TextChoices]] = outcome_type("MappingOutcome", [ESTABLISHED_MEMBER])

#: `MappingOutcome`'s own members, by name, read off the composed type itself.
#:
#: The composed type is built by the functional enum API, so its members are
#: invisible to a type checker reading its declared `type[TextChoices]` and
#: `MappingOutcome.ESTABLISHED` will not type-check. This table is how the two
#: values this module names are reached *through the type* rather than beside it
#: -- so a sentinel that had drifted, or a determinate member that had been
#: renamed, fails here at import rather than silently making every comparison
#: below false.
_MEMBER_VALUES: Final[dict[str, str]] = {member.name: member.value for member in MappingOutcome}

#: `established`, the one determinate verdict this vocabulary adds.
#:
#: Named because resolution branches on it: only an `established` mapping may
#: carry a value, and an `established` mapping that owns columns must carry one
#: -- which is `CPM-FR-1`'s "records nothing rather than a guess" and its
#: converse, expressed as rules a writer can be held to.
ESTABLISHED: Final[str] = _MEMBER_VALUES["ESTABLISHED"]

#: `unknown` as *this* vocabulary spells it, which is the column's default.
#:
#: The same string `OutcomeState.UNKNOWN` carries -- `verify_sentinels`
#: guarantees that -- but reached through `MappingOutcome`, because the column's
#: default must be one of its own choices and reaching across to the other class
#: for it would be the one place this module took a value from a type the field
#: does not declare.
UNKNOWN: Final[str] = _MEMBER_VALUES["UNKNOWN"]

#: Which `Package` columns each mapping kind owns. Every mapping column appears
#: exactly once, and no other column appears at all.
#:
#: The table is what makes "the values are written when the outcome is
#: `established`, and never otherwise" a rule rather than a habit: resolution
#: reads it instead of naming columns one at a time, so a column that acquired a
#: kind and a kind that acquired a column both arrive here, in the open.
#:
#: `FEEDSTOCK` maps to no column on purpose. `CPM-FR-1` says "zero or more", so
#: the mapping is the `Feedstock` child rows -- which is also why the empty tuple
#: is not an omission: a feedstock outcome of `established` with no rows is a
#: *successful empty result*, the third state `CPM-FR-6` insists on keeping
#: apart from `not_found` and `not_applicable`, and it is expressible only
#: because the outcome lives beside the rows rather than being inferred from them.
MAPPED_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    MappingKind.SOURCE_REPOSITORY.value: ("source_repository_url",),
    MappingKind.RELEASE_ECOSYSTEM.value: ("primary_purl", "primary_type"),
    MappingKind.CONDA_ARTIFACT.value: ("conda_purl",),
    MappingKind.FEEDSTOCK.value: (),
    MappingKind.CROSS_ECOSYSTEM.value: ("alternative_purls", "cpes"),
}


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
    #:
    #: It advances when the identity *changes*, not every time a resolver looks:
    #: `record_resolution` leaves this row untouched when a resolution establishes
    #: nothing new, so a package nothing has resolved does not read as freshly
    #: resolved. When a resolver last looked is `PackageMapping.resolved_at`,
    #: which is a different question and has its own column.
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
            # The pair ingestion and resolution both join on, made unique by the
            # database rather than by a check-then-act nothing serialises.
            #
            # `CPM-IDENTITY-S06`'s review recorded the trap this closes and
            # `CPM-IDENTITY-S07` delivered its first half by moving the lookup
            # here from the correctable `canonical_name`. Without the constraint
            # the lookup is still only a convention: two sweeps racing a package
            # the source has just named would each find nothing and each create a
            # shell, and the second key's evidence would hang off a row the first
            # key's does not.
            #
            # **Partial, and it has to be.** Both columns are `blank=True,
            # default=""`, so an unconditional constraint would make `("", "")` a
            # single permissible row for the whole product -- and every creator
            # that is not ingestion, `CPM-IDENTITY-S05`'s override included,
            # would collide with it for no reason. `condition=~Q(associator_key="")`
            # says the rule that is actually meant: a package some source claims
            # is unique to that source's key, and a package no source claims is
            # not constrained at all. Keyed on the *key* rather than on both
            # columns because the key is the half that identifies -- a row with a
            # source and no key names nothing to be unique about.
            #
            # No NULLs are involved, so PostgreSQL and the SQLite fallback
            # enforce this identically; `pixi run gate-postgres` is where it is
            # proven rather than assumed.
            models.UniqueConstraint(
                fields=["identity_source", "associator_key"],
                condition=~models.Q(associator_key=""),
                name="one_package_per_source_key",
            ),
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


class PackageMapping(models.Model):
    """What resolution concluded about one mapping of one package. Table `package_mappings`.

    **This row exists because three states will not fit in a value column.**
    `CPM-FR-1` requires a mapping that does not apply to be distinguishable from
    one that failed *and* from a successful empty result. A blank
    `source_repository_url` cannot say which of the three it is, and a nullable
    one adds a fourth spelling of "missing" rather than a third meaning. So the
    answer moves to its own row and the value stays on `Package`, where
    `CPM-AD-1` puts cross-ecosystem mappings.

    **It could not have been a column on `Package` even if it fitted.**
    `CPM-AD-1` says the package row holds no derived status, and
    `tests/unit/django_apps/test_identity_models.py` enforces that by name:
    nothing there may be called `status`, `outcome`, `*_status` or `*_outcome`.
    A `source_repository_outcome` column would have been swept into the
    derived-status vocabulary by `tests/unit/django_apps/test_outcome_field_audit.py`
    at the same moment. Both rules point the same way, which is usually the sign
    that the shape rather than the naming was wrong.

    **One row per `(package, kind)`, never per resolution.** This is not
    evidence: it carries no `observed_at`, inherits no `AppendOnlyModel`, and is
    rewritten in place when a later resolution reaches a different conclusion --
    exactly as `Package.confidence` is. What a resolution *observed* belongs in
    an evidence table owned by the collector that observed it (`CPM-AD-2`,
    `CPM-AD-7`); what it *concluded* is identity, and identity is mutable by
    construction.
    """

    #: The package this outcome is about, by the integer primary key `CPM-AD-3`
    #: fixes. `CASCADE` on the same terms as `Feedstock.package`: an outcome about
    #: a package that has gone describes nothing, and `EVIDENCE.02-AUDIT-001`'s
    #: `PROTECT`/`RESTRICT` rule reaches relations touching *evidence* models,
    #: which neither end of this one is.
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name="mappings",
        verbose_name=_("package"),
    )

    #: Which mapping this row answers for. A closed vocabulary rather than a free
    #: string, because `MAPPED_FIELDS` ties each member to the columns it owns and
    #: a kind nothing recognises would be an outcome about nothing.
    kind = models.CharField(
        _("kind"),
        max_length=_VOCABULARY_LENGTH,
        choices=MappingKind.choices,
    )

    #: What resolution concluded. `established`, or one of `core`'s four
    #: sentinels: `not_applicable` for a mapping the package's type puts out of
    #: scope, `not_found` for one that was looked for and is not there, `unknown`
    #: for one nobody has looked for yet, `error` for a look that failed
    #: (`CPM-FR-6`).
    #:
    #: Non-null and non-blank, because `NULL` and `""` would each be a fifth
    #: non-answer with no name and no place in the precedence order -- which is
    #: the whole of what the sentinels exist to remove. Defaults to `UNKNOWN`,
    #: this vocabulary's own `unknown`, which is the honest value for a mapping
    #: no resolution has reached and is one of the column's own choices.
    outcome = models.CharField(
        _("outcome"),
        max_length=_VOCABULARY_LENGTH,
        choices=MappingOutcome.choices,
        default=UNKNOWN,
    )

    #: When this conclusion was reached (`CPM-FR-2`). Supplied by the caller from
    #: an injected `Clock` on the same terms as `Package.resolved_at`: no
    #: `default`, no `auto_now_add`, and no wall clock anywhere near it
    #: (`CPM-AD-26`).
    #:
    #: **This is when the mapping was last *looked at*, and `Package.resolved_at`
    #: is when the identity last *changed*.** The two answer different questions
    #: and would be the same column only while every resolution established
    #: something: a resolver that runs daily and finds nothing advances these
    #: five rows every day and leaves the package row alone, which is what stops
    #: a package nothing has resolved from reading as freshly resolved to
    #: `CPM-IDENTITY-S04`'s review queue.
    #:
    #: All five rows are stamped with one instant by the only writer there is
    #: today, because `record_resolution` requires an outcome for every kind --
    #: so the column is not carrying per-mapping *divergence* yet. It is on the
    #: row rather than on the package because the answer is, and a second
    #: timestamp on the package row would be a coarser answer to a question this
    #: table already answers exactly.
    resolved_at = models.DateTimeField(_("resolved at"))

    class Meta:
        """The table the architecture names, not the `identity_packagemapping` Django derives.

        Rejected for the reason `Package.Meta` gives: the schema is named by the
        architecture rather than by which application happened to declare the
        model.
        """

        db_table = "package_mappings"
        verbose_name = _("package mapping")
        verbose_name_plural = _("package mappings")
        constraints = [
            # One answer per question. Without it a second resolution appends a
            # second row and "what did we conclude about this package's
            # feedstocks" has two answers with nothing to choose between them --
            # and `CPM-AD-2` is not available as a tie-break, because this is not
            # evidence and carries no `observed_at` to order by.
            models.UniqueConstraint(fields=["package", "kind"], name="one_outcome_per_package_mapping"),
        ]

    def __str__(self) -> str:
        """Return the mapping this row answers for and what it concluded.

        Returns:
            A one-line summary naming the package, the kind and the outcome, or
            saying which of them is absent. Read off `package_id` rather than
            `package` for the reason `Feedstock.__str__` gives: the related object
            of an unsaved instance raises `RelatedObjectDoesNotExist`, and a
            `__str__` that raises is what a failure message would have been.

        """
        kind = self.kind or "(no kind)"
        outcome = self.outcome or "(no outcome)"
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        return f"{kind} is {outcome} for {scope}"


class IdentityOverride(AppendOnlyModel):
    """One audited human correction of a package identity. Table `identity_overrides`.

    `CPM-FR-3` makes this the only human write in the product that mutates
    governed reference data, and `CPM-AD-14` puts the whole weight of the rule on
    it: the override requires a permission, requires a reason, and writes this row
    in the same transaction as the correction it records. See the module docstring
    for why the row is evidence, and `identity/services.py`'s `override_identity`
    for the one writer.

    `observed_at` and `objects` come from `AppendOnlyModel`: the instant is
    supplied by the writer from an injected `Clock` (`CPM-AD-26`) and the manager
    is the one that offers no `update()` and no `delete()` (`CPM-AD-2`). The
    inherited column is called `observed_at` rather than `decided_at`, and it
    means what the base says it means -- the moment *this* row's fact was
    recorded. What was observed here is a decision a person made, and giving it a
    second name would put this table outside the freshness, retention and
    append-only machinery that reads that column across the whole product.

    **The prior and new values are stored in pairs, and both halves are stored
    even where nothing changed.** A row that recorded only what differed could not
    say whether a field was left alone deliberately or was never considered, and
    an auditor asking "what did this package read before" would have to
    reconstruct it from the rows on either side. Three pairs, because three fields
    are what an override may correct: the canonical name, the display name, and
    the confidence -- which an override always raises to `verified`, because a
    human establishing an identity is exactly what `CPM-AD-4` says that value
    means.

    **No `*_status` or `*_outcome` column, and no unique constraint.**
    `tests/unit/django_apps/test_outcome_field_audit.py` sweeps the first by name
    across every first-party model and
    `tests/unit/django_apps/test_evidence_constraint_audit.py` the second across
    every evidence one. Neither is a rule this row has to work around: a
    confidence is identity provenance rather than a derived status, and two
    corrections of one package are two facts.
    """

    #: The package this correction is about, by the integer primary key
    #: `CPM-AD-3` fixes. `PROTECT` rather than `Feedstock`'s `CASCADE`:
    #: `EVIDENCE.02-AUDIT-001` requires it of every relation on an evidence model,
    #: because Django's deletion collector issues its `DELETE` through
    #: `sql.DeleteQuery` and would go straight past every append-only refusal in
    #: `core/models.py` on the way. It is independently right -- the record of a
    #: correction outliving the row it corrected is the whole point of an audit --
    #: and it agrees with `CPM-AD-25`, which says no package row is ever deleted.
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        related_name="identity_overrides",
        verbose_name=_("package"),
    )

    #: Who decided. `PROTECT` on the same terms and for a second reason of its
    #: own: deleting a user must not delete the record of what they decided, and
    #: an audit row whose actor had been cascaded away would say a correction
    #: happened and refuse to say who made it.
    #:
    #: `settings.AUTH_USER_MODEL` rather than an import of
    #: `django_service.users.models.User`. That is Django's own rule for a
    #: relation to the user model, and here it also keeps a domain application
    #: from importing the platform's model module at model-definition time.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="identity_overrides",
        verbose_name=_("actor"),
    )

    #: What the package was called before this correction, and what it is called
    #: after. Equal when the override corrected no name, which is a state an
    #: override may legitimately be in: raising a correct identity to `verified`
    #: changes nothing about the name and is still a decision worth recording.
    prior_canonical_name = models.CharField(_("prior canonical name"), max_length=_NAME_LENGTH)
    new_canonical_name = models.CharField(_("new canonical name"), max_length=_NAME_LENGTH)

    #: The display name on the same terms. Blank means missing rather than empty
    #: (PRD Appendix A.1's data rules), on both sides of the pair -- so an
    #: override that supplies a display name for the first time reads as `""` to
    #: a name, which is exactly what happened.
    prior_display_name = models.CharField(_("prior display name"), max_length=_NAME_LENGTH, blank=True, default="")
    new_display_name = models.CharField(_("new display name"), max_length=_NAME_LENGTH, blank=True, default="")

    #: How certain the identity was before this correction, and after. The second
    #: is always `verified` today -- `override_identity` writes nothing else --
    #: and it is stored rather than implied, because a row that recorded only the
    #: prior value would stop being readable the day the override path learns to
    #: record a second verdict.
    prior_confidence = models.CharField(
        _("prior confidence"),
        max_length=_CONFIDENCE_LENGTH,
        choices=IdentityConfidence.choices,
    )
    new_confidence = models.CharField(
        _("new confidence"),
        max_length=_CONFIDENCE_LENGTH,
        choices=IdentityConfidence.choices,
    )

    #: Why. `CPM-AD-14` requires a reason and `override_identity` refuses a blank
    #: one before it writes anything, so no stored row carries an empty reason --
    #: which is why this field declares no `blank=True`. A `TextField` rather than
    #: a bounded `CharField`: the reason is prose a person wrote, there is no
    #: length at which one becomes wrong, and a bound would be refused in the
    #: gate's PostgreSQL and truncated by the local SQLite (`R-5`).
    reason = models.TextField(_("reason"))

    #: The `trace_id` of the request or task the correction was made in, formatted
    #: `032x` exactly as `config/observability/logging.py` formats it for every log
    #: line (`CPM-AD-15`). Read from `core/ledger.py`'s `current_trace_id()`, which
    #: never raises. Empty when no span was active, which never blocks the write:
    #: an uncorrelated audit row is worth far more than a refused correction.
    trace_id = models.CharField(_("trace id"), max_length=_TRACE_ID_LENGTH, blank=True, default="")

    class Meta:
        """The table PRD Appendix A.2 names, not the `identity_identityoverride` Django derives.

        Rejected for the reason `Package.Meta` gives: the schema is named by the
        architecture and the PRD rather than by which application declared the
        model.

        **No unique constraint of any kind** (`CPM-AD-2`, `EVIDENCE.02-AUDIT-003`).
        Two corrections of one package are two facts, and a constraint spanning
        the corrected fact would turn the second one into an `IntegrityError` --
        the same history loss as an overwrite, arriving as a crash.

        **Newest first, declared here rather than at each call site.**
        `CPM-FR-32` makes the overrides independently queryable, and the question
        anybody asks of an audit trail is "what happened, most recently first".
        Written at each call site that ordering is one keystroke from being
        omitted, and an unordered read of an append-only table returns rows in
        whatever order the database chose. The tie-break on descending primary key
        is what makes the answer total: two corrections can share an `observed_at`
        -- one clock, two calls in one request -- and an unordered tie would make
        the answer depend on the database's own arbitrary row order.
        """

        db_table = "identity_overrides"
        verbose_name = _("identity override")
        verbose_name_plural = _("identity overrides")
        ordering = ("-observed_at", "-id")
        indexes = [
            models.Index(fields=["package", "-observed_at"], name=OVERRIDE_READ_INDEX),
        ]
        #: The permission `CPM-AD-14` requires of the actor, declared on the model
        #: the write records itself in. The codename is `core/roles.py`'s, imported
        #: rather than restated -- see that module for why the one spelling lives
        #: there and not here.
        permissions = [(IDENTITY_OVERRIDE_CODENAME, "Can override a package identity")]

    def __str__(self) -> str:
        """Return the correction, the package it was made against and when.

        Returns:
            A one-line summary. Read off `package_id` and `actor_id` rather than
            off the related objects, because the related object of an unsaved
            instance raises `RelatedObjectDoesNotExist` -- and a `__str__` that
            raises breaks the two places a half-built object is most likely to be
            rendered, a debugger and a traceback.

        """
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        who = "nobody" if self.actor_id is None else f"user {self.actor_id}"
        when = "never" if self.observed_at is None else self.observed_at.isoformat()
        prior = self.prior_canonical_name or "(no name)"
        corrected = self.new_canonical_name or "(no name)"
        return f"{prior} -> {corrected} on {scope} by {who} at {when}"
