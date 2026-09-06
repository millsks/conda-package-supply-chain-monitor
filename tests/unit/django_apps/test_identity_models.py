"""AC #2-#6: the package row holds package identity, and provably nothing else.

`CPM-AD-1` is a rule about a *field set*, which is the one kind of rule a review
comment cannot hold. A version column added to `Package` looks entirely
reasonable at the point somebody adds it -- the collector that wanted it has the
value in hand, the row is mutable, and the alternative is a join -- and the cost
lands somewhere else entirely: the column is overwritten on every collection, so
the history of the value is gone and "what did we know, and when" stops being
answerable for it. There is no migration back from that. So the field set is
asserted, by name, in both directions: what must be there, and what must not.

**Introspection only. No database is touched.** `_meta` is populated at import,
so every case here reads the declaration rather than the schema.
`tests/integration/django_apps/test_identity_models.py` holds the half that needs
a real table -- the unique constraints in particular, which are database
guarantees and are only genuinely proven by a database refusing the second write.

**The forbidden names are written out rather than derived.** Deriving them from
PRD Appendix A.1 would need a parser for a prose table, and the parser would
become the thing under test. They are copied from the story's **Never** list and
from A.1's export-column column, and the vacuity guards below assert that both
tables are non-empty and that the detector they feed actually detects -- which is
what stops an emptied list from reading as a clean model.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.db import models
from django.test.utils import isolate_apps

from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.outcomes import SENTINEL_MEMBERS
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.outcomes import verify_sentinels
from conda_package_supply_chain_monitor.identity.models import ESTABLISHED
from conda_package_supply_chain_monitor.identity.models import MAPPED_FIELDS
from conda_package_supply_chain_monitor.identity.models import UNKNOWN
from conda_package_supply_chain_monitor.identity.models import Feedstock
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import IdentityOverride
from conda_package_supply_chain_monitor.identity.models import MappingKind
from conda_package_supply_chain_monitor.identity.models import MappingOutcome
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.models import PackageMapping
from tests.model_registry import FIXTURE_APP
from tests.model_registry import FIXTURE_LABEL
from tests.model_registry import OBSERVED_AT_FIELD
from tests.model_registry import declares_not_evidence
from tests.model_registry import evidence_marks
from tests.model_registry import first_party_models
from tests.source_scan import SRC_ROOT
from tests.source_scan import project_files

if TYPE_CHECKING:
    from pathlib import Path

    from django.db.models import Field

#: The unique correctable name, and the constraint the story turns on.
CANONICAL_NAME: Final[str] = "canonical_name"

#: Exactly what `Package` holds, in declaration order, plus the surrogate key.
#: `CPM-AD-1`'s four categories -- canonical name, cross-ecosystem mappings,
#: provenance, confidence -- projected onto PRD Appendix A.1's stored-field
#: column, and nothing else. Written out rather than counted: a length assertion
#: would pass while a field was swapped for another.
#:
#: `version_authority_order` arrived with `CPM-CURRENCY-S06` and sits with the
#: cross-ecosystem mappings deliberately: `CPM-AD-6` makes "which ecosystem is
#: authoritative for this package" data on the package, and that is a statement
#: about which ecosystem the package *belongs to* rather than a status any policy
#: derived. It holds no verdict, no observation and no workflow state, which is
#: what keeps it inside `CPM-AD-1`'s categories rather than a fifth one.
EXPECTED_PACKAGE_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "canonical_name",
    "display_name",
    "source_repository_url",
    "primary_purl",
    "primary_type",
    "conda_purl",
    "alternative_purls",
    "cpes",
    "version_authority_order",
    "identity_source",
    "associator_key",
    "resolved_at",
    "confidence",
)

#: Exactly what `Feedstock` holds. The child table `CPM-FR-1`'s "zero or more"
#: forces, carrying the mapping and nothing about the state of an in-flight
#: recipe.
EXPECTED_FEEDSTOCK_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "package",
    "name",
    "url",
    "metadata_url",
)

#: The names `CPM-AD-1` keeps off the package row, from the story's **Never**
#: list. Each is projected at read time by `reporting` -- from the rollup
#: (`CPM-AD-11`), from evidence, or from `inventory_snapshots` (`CPM-AD-25`) --
#: and each appears in PRD Appendix A.1's table beside the identity fields, which
#: is exactly why the ban has to be mechanical.
FORBIDDEN_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "apps",
        "downloads",
        "internal_component_count",
        "internal_lob_count",
        "latest_vuln_count",
        "local_build_status",
        "local_recipe_url",
        "platforms",
        "priority_bucket",
        "priority_description",
        "priority_reason",
        "priority_source",
        "rank",
        "risk_level",
        "score",
        "staged_recipe_pr_url",
        "tracking_issue_url",
        "tracking_title",
        "verified_at",
        "versions",
        "vulnerability_rollup",
        "work_type",
    },
)

#: PRD Appendix A.1's export column headings that differ from the stored name
#: beside them. The reporting layer owns the projection between the two contracts
#: (`CPM-FR-26`), so none of these may be a field name: a field named for a
#: heading makes the projection look unnecessary, and the next export format
#: either is wrong or renames a database column.
EXPORT_COLUMN_HEADINGS: Final[frozenset[str]] = frozenset(
    {
        "Apps",
        "Conda-Forge_FeedStock_URL",
        "Conda-Forge_Metadata_URL",
        "Core_Python_Package_Name",
        "Downloads",
        "JFROG_latest_vuln_count",
        "JFROG_risk_level",
        "Local_Build_Status",
        "Local_Recipes_URL",
        "OpenTeams_Title",
        "P",
        "Package",
        "Platforms",
        "Priority_Bucket_Description",
        "Priority_Reason",
        "Priority_Source",
        "Rank",
        "Score",
        "Staged_Recipes_PR_URL",
        "Verification_Timestamp_UTC",
        "Versions",
        "Vuln",
        "Work",
        "associator_status",
    },
)

#: What a stored field name looks like (PRD Appendix A.1, "Two contracts"): a
#: snake_case identifier. `Conda-Forge_FeedStock_URL` fails it on three counts at
#: once, which is the point -- an export heading is not a spelling a field name
#: can accidentally take.
STORED_FIELD_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")

#: What makes a field a derived status, in the vocabulary
#: `tests/unit/django_apps/test_outcome_field_audit.py` sweeps by. Restated here
#: rather than imported because this case asserts the *absence* of such a field,
#: which is a property of this model rather than of that audit: the audit checks
#: that a derived status carries the four sentinels, and `CPM-AD-1` says this row
#: holds no derived status at all.
DERIVED_STATUS_NAMES: Final[frozenset[str]] = frozenset({"outcome", "status"})
DERIVED_STATUS_SUFFIXES: Final[tuple[str, ...]] = ("_outcome", "_status")

#: The `core` package the import rule below is swept over, and the two spellings
#: it separates. `identity/confidence.py` exists to break the cycle between
#: `core.models` and `identity.models`, and it only breaks it while every `core`
#: module reads the vocabulary from the leaf. Compared as source text rather than
#: resolved from an AST because that is exactly what an import statement is, and
#: both forms are the literal line a developer types.
CORE_PACKAGE: Final[Path] = SRC_ROOT / "django_apps" / "conda_package_supply_chain_monitor" / "core"
FORBIDDEN_CONFIDENCE_IMPORT: Final[str] = (
    "from conda_package_supply_chain_monitor.identity.models import IdentityConfidence"
)
PERMITTED_CONFIDENCE_IMPORT: Final[str] = (
    "from conda_package_supply_chain_monitor.identity.confidence import IdentityConfidence"
)

#: The `core` modules that legitimately read the vocabulary, by path under `src/`.
#: `models.py` mirrors the value onto `PackageHealth`; `confidence.py` is
#: `CPM-AD-4`'s gate over it. Written out so a third reader is a decision somebody
#: made, and so the ban above cannot pass by nothing reading it at all.
EXPECTED_CONFIDENCE_READERS: Final[tuple[str, ...]] = (
    "django_apps/conda_package_supply_chain_monitor/core/confidence.py",
    "django_apps/conda_package_supply_chain_monitor/core/models.py",
)

#: The confidence values, in the PRD's own spelling. The hyphen in the middle
#: value is the assertion: `CPM-AD-5`'s fixed-lowercase rule binds derived-status
#: vocabularies, and confidence is identity provenance rather than a derived
#: status, so matching the governing document verbatim is what keeps
#: `CPM-IDENTITY-S03`'s gate from translating between two spellings.
EXPECTED_CONFIDENCE_VALUES: Final[tuple[str, ...]] = ("verified", "inventory-derived", "unmapped")

#: Exactly what `PackageMapping` holds. One row per `(package, kind)` carrying
#: why a value is absent, and nothing the package row already holds --
#: `CPM-IDENTITY-S02` added the table rather than a column, which is what AC #5
#: below is about.
EXPECTED_MAPPING_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "package",
    "kind",
    "outcome",
    "resolved_at",
)

#: The mapping kinds `CPM-FR-1` lists, in the order `MappingKind` declares them.
#: Written out rather than read off the type, because the *closure* is the claim:
#: a sixth kind is a decision somebody makes here as well as there.
EXPECTED_MAPPING_KINDS: Final[tuple[str, ...]] = (
    "source_repository",
    "release_ecosystem",
    "conda_artifact",
    "feedstock",
    "cross_ecosystem",
)

#: Every table the `identity` application owns. One tuple rather than several,
#: because every case below sweeps all four: dropping a model from a sweep to
#: make it pass is how a table stops being covered by a rule it is still bound by.
#:
#: `IdentityOverride` joined with `CPM-IDENTITY-S05` and is the one that is
#: *evidence* -- so it is excluded from exactly one case here, by name and with
#: the reason written down, rather than by being left out of this tuple. Left out,
#: every rule below would stop reaching it: nothing would stop a `review_status`
#: column, an export heading or a projected name landing on the audit row.
IDENTITY_TABLES: Final[tuple[type[models.Model], ...]] = (Package, Feedstock, PackageMapping, IdentityOverride)

#: The one `identity` table that is evidence, and the one case below it is
#: excluded from.
#:
#: `CPM-FR-32` makes the audit row append-only, so it inherits `AppendOnlyModel`
#: and declares `observed_at` -- two of the three marks `tests/model_registry.py`
#: reads. It is therefore the exact opposite of what
#: `test_no_identity_model_is_evidence_and_none_takes_the_escape` asserts of the
#: other three, and it is named here rather than dropped from `IDENTITY_TABLES`
#: for the reason `RECORDED_STATUS_COLUMNS` is a table rather than an omission.
#: `tests/unit/test_model_registry.py` is where its marks are asserted positively.
THE_EVIDENCE_TABLE: Final[type[models.Model]] = IdentityOverride

#: The derived-status columns this application declares on purpose, by model.
#:
#: Exactly one, and it is the point of the story: `CPM-FR-1` needs a mapping that
#: does not apply to be distinguishable from one that failed and from a
#: successful empty result, `CPM-AD-1` keeps that off the package row, so it
#: lives on `PackageMapping`. Recorded here rather than dropping the model from
#: the sweep, so a `review_status` added to that table later is still caught --
#: keyed on model *and* field for the reason
#: `tests/unit/django_apps/test_outcome_field_audit.py` keys its own amendment
#: both ways: recording one column must not exempt a second.
RECORDED_STATUS_COLUMNS: Final[dict[type[models.Model], frozenset[str]]] = {
    PackageMapping: frozenset({"outcome"}),
}


def _field_names(model: type[models.Model]) -> tuple[str, ...]:
    """Return a model's concrete field names in declaration order.

    Args:
        model: The model to read.

    Returns:
        The name of every concrete field, which is every column the table has.
        Reverse relations and many-to-many descriptors are excluded: neither is a
        column, and `CPM-AD-1` is a rule about what the row holds.

    """
    return tuple(field.name for field in model._meta.concrete_fields)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


# ---------------------------------------------------------------------------
# AC #2: the key, and the index that is not declared twice.
# ---------------------------------------------------------------------------


def test_the_primary_key_is_the_project_wide_surrogate_integer() -> None:
    """`CPM-AD-3`: a surrogate integer key, auto-created from `DEFAULT_AUTO_FIELD`.

    Auto-created is half the assertion. A hand-declared `BigAutoField` would
    satisfy the type check and would be a second declaration of
    `config/settings/base.py`'s project-wide decision, which is what
    `test_identity_app.py` refuses on the `AppConfig`. Reading `auto_created` is
    how the two halves are told apart.
    """
    primary_key = Package._meta.pk  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert primary_key is not None
    assert isinstance(primary_key, models.BigAutoField)
    assert primary_key.auto_created is True


def test_canonical_name_is_unique_and_needs_no_separate_index() -> None:
    """`unique=True` is what supplies the index, so `db_index` stays off.

    Django's schema editor emits an explicit index only for
    `db_index and not unique`, so `db_index=True` beside `unique=True` is a
    second index the database maintains for nothing -- the rule
    `src/django_service/users/models.py:23` states and
    `tests/unit/users/test_models.py` pins for `idp_subject`. "Unique indexed
    column" in `CPM-AD-3` and in the PRD glossary means this one declaration, not
    two.
    """
    field = Package._meta.get_field(CANONICAL_NAME)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert field.unique is True
    assert field.db_index is False


def test_canonical_name_is_required_and_bounded() -> None:
    """A package without a canonical name is not a package.

    Non-null and not blank, which is what makes the unique constraint mean
    something: a nullable unique column admits repeated NULLs on both PostgreSQL
    and SQLite, so "one row per name" would hold for every name except the
    absent one.
    """
    field = Package._meta.get_field(CANONICAL_NAME)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert field.null is False
    assert field.blank is False
    assert field.max_length is not None


# ---------------------------------------------------------------------------
# AC #3: what the row holds, and what it must never hold.
# ---------------------------------------------------------------------------


def test_the_package_row_holds_exactly_the_identity_fields() -> None:
    """`CPM-AD-1`'s four categories, and nothing else.

    Order included. It is not load-bearing for the schema, but a set comparison
    would pass while a field moved between the mapping group and the provenance
    group, and the grouping is how a reader checks the categories against
    `CPM-AD-1` at all.
    """
    assert _field_names(Package) == EXPECTED_PACKAGE_FIELDS


def test_the_feedstock_row_holds_exactly_the_mapping_fields() -> None:
    """The child table carries the mapping, not the state of an in-flight recipe.

    `staged_recipe_pr_url` and `local_recipe_url` are absent deliberately: PRD
    Appendix A.1 groups them as conda-forge state and internal packaging state,
    which is an observation and therefore evidence (`CPM-AD-2`).
    """
    assert _field_names(Feedstock) == EXPECTED_FEEDSTOCK_FIELDS


@pytest.mark.parametrize("model", IDENTITY_TABLES, ids=lambda model: model.__name__)
def test_no_projected_or_observed_name_reaches_any_identity_row(model: type[models.Model]) -> None:
    """The **Never** list, asserted as a disjointness rather than field by field.

    Each of these is projected by `reporting` at read time -- from the rollup
    (`CPM-AD-11`), from evidence, or from `inventory_snapshots` (`CPM-AD-25`) --
    and every one of them appears in PRD Appendix A.1 beside the identity fields,
    which is precisely why somebody adds one.
    """
    trespassers = FORBIDDEN_FIELD_NAMES & set(_field_names(model))

    assert trespassers == set(), f"{model.__name__} holds projected or observed fields: {sorted(trespassers)}"


@pytest.mark.parametrize("model", IDENTITY_TABLES, ids=lambda model: model.__name__)
def test_no_identity_row_declares_an_unrecorded_derived_status(model: type[models.Model]) -> None:
    """`CPM-AD-1`: no derived status on these rows, by any spelling, bar one recorded column.

    A column named `*_status` is swept into the derived-status vocabulary by
    `tests/unit/django_apps/test_outcome_field_audit.py` and held to
    `OutcomeState`'s four sentinels -- so the per-mapping `not_applicable` that
    `CPM-FR-1` needs could not arrive as a status column on `Package`.
    `CPM-IDENTITY-S02` put it on `PackageMapping` instead.

    **`PackageMapping` stays in the sweep, and the exemption is one field name.**
    Dropping the model from the parameters would have been the easy way to make
    this pass, and it would have left a future `review_status` or
    `currency_outcome` on that table unswept forever. The exemption is
    `RECORDED_STATUS_COLUMNS` -- keyed on model *and* field, so recording
    `PackageMapping.outcome` exempts nothing else on it -- and the cases further
    down are what hold that one column to the vocabulary instead of to nothing.
    """
    recorded = RECORDED_STATUS_COLUMNS.get(model, frozenset())
    offenders = [
        name
        for name in _field_names(model)
        if (name in DERIVED_STATUS_NAMES or name.endswith(DERIVED_STATUS_SUFFIXES)) and name not in recorded
    ]

    assert offenders == [], f"{model.__name__} declares derived-status fields: {offenders}"


def test_the_recorded_status_column_table_still_describes_the_models() -> None:
    """The exemption above is a counted decision, reconciled in both directions.

    An entry naming a field that no longer exists is a licence nobody meant to
    leave open, and an emptied table would make the sweep above pass by exempting
    everything it was pointed at. Both fail here.
    """
    assert RECORDED_STATUS_COLUMNS != {}
    for model, names in RECORDED_STATUS_COLUMNS.items():
        assert names, model.__name__
        assert names <= set(_field_names(model)), model.__name__
    assert Package not in RECORDED_STATUS_COLUMNS, "CPM-AD-1 permits no derived status on the package row at all"
    assert Feedstock not in RECORDED_STATUS_COLUMNS


@pytest.mark.parametrize(
    "model",
    [model for model in IDENTITY_TABLES if model is not THE_EVIDENCE_TABLE],
    ids=lambda model: model.__name__,
)
def test_no_identity_row_but_the_audit_row_is_evidence_and_none_takes_the_escape(
    model: type[models.Model],
) -> None:
    """AC #6, stated where the models are declared rather than only in the registry guard.

    None of the three identity rows carries any of the three marks
    `tests/model_registry.py` reads -- no `observed_at`, no `AppendOnlyModel`, and
    the app label is `identity` rather than `evidence` -- so none may declare
    `not_evidence = True` either. That attribute is `CPM-AD-2`'s recorded
    exemption *for a model that carries a mark*, and a further user of it fails
    `tests/unit/django_apps/test_evidence_inheritance_audit.py` until somebody
    records the decision. A package row is not an observation; it is the thing
    observations are about.

    `IdentityOverride` is excluded, and the exclusion is the claim next door: an
    audit row *is* an observation -- of a decision a person made -- so it carries
    two marks on purpose. It stays in every other sweep in this module.
    """
    assert OBSERVED_AT_FIELD not in _field_names(model)
    assert evidence_marks(model) == []
    assert declares_not_evidence(model) is False


def test_the_audit_row_is_evidence_and_does_not_take_the_escape() -> None:
    """The other half of the case above, so the exclusion is not a hole.

    Dropping `IdentityOverride` from a sweep to make it pass is exactly what
    `IDENTITY_TABLES`' comment forbids, so the exclusion is paid for here: the
    model must carry the marks, by the same predicate, and must not have taken the
    `not_evidence` escape to get out of the obligations they bring.

    Both marks are asserted rather than `is_evidence_model(...) is True`, because
    the union is satisfied by any one of them: a model that had lost the base but
    kept `observed_at` would still read as evidence while no longer refusing an
    `update()`.
    """
    assert OBSERVED_AT_FIELD in _field_names(THE_EVIDENCE_TABLE)
    assert evidence_marks(THE_EVIDENCE_TABLE) == ["base", OBSERVED_AT_FIELD]
    assert declares_not_evidence(THE_EVIDENCE_TABLE) is False


# ---------------------------------------------------------------------------
# AC #4: two contracts, and no field named for the other one.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", IDENTITY_TABLES, ids=lambda model: model.__name__)
def test_every_field_name_is_a_snake_case_identifier(model: type[models.Model]) -> None:
    """PRD Appendix A.1, "Two contracts": stored fields are valid snake_case identifiers."""
    malformed = [name for name in _field_names(model) if not STORED_FIELD_NAME.match(name)]

    assert malformed == [], f"{model.__name__} declares non-identifier field names: {malformed}"


@pytest.mark.parametrize("model", IDENTITY_TABLES, ids=lambda model: model.__name__)
def test_no_field_is_named_for_an_export_column_heading(model: type[models.Model]) -> None:
    """The headings belong to the reporting layer's projection, never to a field.

    Compared case-sensitively and exactly, because that is how a heading is
    written: `Package` is a heading and `package` is a field name, and the two
    are the same word in different contracts.
    """
    named_for_a_heading = EXPORT_COLUMN_HEADINGS & set(_field_names(model))

    assert named_for_a_heading == set(), (
        f"{model.__name__} names fields after export column headings: {sorted(named_for_a_heading)}"
    )


def test_the_heading_table_and_the_forbidden_table_would_catch_something() -> None:
    """The vacuity guard both tables above need.

    An emptied table intersects nothing and reports a clean model, which is
    indistinguishable from a model that holds only its identity fields. So the
    detectors are measured against names that must fail them: a heading that is
    not an identifier, and a projected name that is.
    """
    assert FORBIDDEN_FIELD_NAMES, "the forbidden-name table is empty, so it intersects nothing"
    assert EXPORT_COLUMN_HEADINGS, "the export-heading table is empty, so it intersects nothing"
    assert "Core_Python_Package_Name" in EXPORT_COLUMN_HEADINGS
    assert not STORED_FIELD_NAME.match("Core_Python_Package_Name")
    assert "priority_bucket" in FORBIDDEN_FIELD_NAMES
    assert STORED_FIELD_NAME.match("priority_bucket")


# ---------------------------------------------------------------------------
# AC #5: nothing references a package by its name.
# ---------------------------------------------------------------------------


def _targets_of(relation: Field[object, object]) -> list[str]:
    """Return the names of the `Package` columns one relation points at.

    Args:
        relation: A concrete relational field whose related model is `Package`.

    Returns:
        One name per column on the far side. Usually one -- `id` -- but a
        `ForeignObject` may span several, and a `ManyToManyField` points through
        an intermediate table whose own foreign key carries the target, so the
        through model's fields are what answer for it. Reading
        `relation.target_field` alone would return a single name for the first
        case and raise for the last, which is how a many-to-many escapes a sweep
        written for foreign keys.

    """
    if isinstance(relation, models.ManyToManyField):
        through = relation.remote_field.through
        return [
            target.name
            for field in through._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
            if field.is_relation and field.related_model is Package
            for target in field.foreign_related_fields
        ]
    return [target.name for target in relation.foreign_related_fields]


def test_no_relation_anywhere_targets_the_canonical_name() -> None:
    """`CPM-AD-3`: correcting a canonical name cascades nowhere, because nothing points at it.

    Swept over every first-party model rather than over `identity`'s two, because
    the field this forbids would be declared on the *referring* side -- a
    `ForeignKey(Package, to_field="canonical_name")` in `collectors` or
    `workflow` is what makes a rename cascade, and it is invisible from here
    unless the sweep starts from the registry.

    **Every relational field, not only the foreign keys.** `to_field` is not a
    `ForeignKey` affordance: `ManyToManyField` takes `through_fields` onto an
    intermediate table whose own key can name a column, and `ForeignObject`
    spans several columns by construction. A sweep restricted to
    `ForeignKey | OneToOneField` would also have been restricted to `ForeignKey`
    alone, since `OneToOneField` subclasses it -- so the pair read as breadth
    while adding none. The filter is `models.Field` and `is_relation`, which is
    every concrete relation and no reverse-relation descriptor (those are
    `ForeignObjectRel`, carry no target, and describe a relation declared
    somewhere this sweep already visited).

    The empty sweep is guarded: `Feedstock.package` is a real relation to
    `Package`, so the scan has something to look at today, and the day a second
    application points at the table it is already covered.
    """
    relations_to_package = [
        field
        for model in first_party_models()
        for field in model._meta.get_fields()  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if isinstance(field, models.Field) and field.is_relation and field.related_model is Package
    ]

    assert relations_to_package, "no relation to Package was found, so this sweep asserts nothing"
    offenders = [
        f"{relation.model._meta.label}.{relation.name}"  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        for relation in relations_to_package
        if CANONICAL_NAME in _targets_of(relation)
    ]
    assert offenders == [], f"these relations target Package.canonical_name: {offenders}"


def test_the_relation_sweep_would_notice_a_relation_that_targeted_the_name() -> None:
    """The detector, measured against a relation built to fail it.

    Every relation in the repository points at `id` today, so the sweep above
    passes over a set in which nothing is wrong -- and a `_targets_of` that had
    stopped returning target names would pass identically. The fixture is a real
    `ForeignKey` with a real `to_field`, built in an isolated registry so the
    sweep above cannot see it and `makemigrations --check` cannot either.
    """
    with isolate_apps(FIXTURE_APP):

        class Offender(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            package = models.ForeignKey(Package, on_delete=models.CASCADE, to_field=CANONICAL_NAME)

            class Meta:
                app_label = FIXTURE_LABEL

    assert _targets_of(Offender._meta.get_field("package")) == [CANONICAL_NAME]  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    assert _targets_of(Feedstock._meta.get_field("package")) == ["id"]  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


# ---------------------------------------------------------------------------
# Provenance, confidence, and the shapes the matrix turns on.
# ---------------------------------------------------------------------------


def test_confidence_keeps_the_prds_own_spelling_and_defaults_to_unmapped() -> None:
    """`CPM-AD-4`'s three values verbatim, defaulting to the one `CPM-AD-25` creates.

    The hyphen in `inventory-derived` is deliberate. `CPM-AD-5`'s fixed-lowercase
    rule binds derived-status vocabularies composed from `OutcomeState`, and this
    is identity provenance rather than a derived status; matching the PRD
    glossary exactly is what keeps two spellings of three values from existing.
    """
    field = Package._meta.get_field("confidence")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert tuple(IdentityConfidence.values) == EXPECTED_CONFIDENCE_VALUES
    assert field.choices is not None
    assert tuple(value for value, _label in field.choices) == EXPECTED_CONFIDENCE_VALUES
    assert field.default == IdentityConfidence.UNMAPPED
    assert field.null is False


def test_the_rollup_mirrors_this_column_at_the_same_width() -> None:
    """One vocabulary, two columns, and they must agree about how wide it is.

    `CPM-EVIDENCE-S07`'s `core.PackageHealth` records the confidence a rollup row
    was gated at, because `Package.confidence` is mutable and a later resolution
    changes it -- so the rollup would otherwise claim to have been gated at a
    confidence it was not. The two columns hold the same `IdentityConfidence`
    values and are declared in two modules, each with its own private width
    constant: `core` may not read `identity`'s, because a cross-module private
    read is what `SLF001` forbids.

    Two numbers that can disagree look exactly like one decision, right up until
    a widened `IdentityConfidence` value is truncated on one of them. This is the
    reconciliation, in the module that owns the vocabulary.
    """
    identity_column = Package._meta.get_field("confidence")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    rollup_column = PackageHealth._meta.get_field("confidence")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert rollup_column.max_length == identity_column.max_length
    assert rollup_column.choices == identity_column.choices
    assert max(len(value) for value in IdentityConfidence.values) <= identity_column.max_length


def test_resolved_at_is_required_and_reads_no_wall_clock() -> None:
    """`CPM-AD-26`: the instant is injected, so the column carries no default at all.

    `auto_now_add` and `default=timezone.now` both read the process wall clock
    where the row is written, which `EVIDENCE.01-AUDIT-002` fails and
    `tests/unit/django_apps/test_clock_audit.py` enforces tree-wide. Asserted
    here as well because that audit reads the *source* and this reads the
    resolved field: a default arriving through a base class or a subclassed field
    would satisfy the source scan and fail here.
    """
    field = Package._meta.get_field("resolved_at")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert isinstance(field, models.DateTimeField)
    assert field.null is False
    assert field.has_default() is False
    assert field.auto_now_add is False
    assert field.auto_now is False


def test_the_multi_valued_mappings_default_to_an_empty_list_and_never_to_null() -> None:
    """ "No identifiers" is `[]`, which is a value, and never NULL, which is a second one.

    `blank=True` is what makes an empty list a valid form value rather than a
    validation error; the column stays NOT NULL with a `list` default, so
    Appendix A.1's "blank means missing" rule has exactly one spelling on a
    multi-valued column.
    """
    for name in ("alternative_purls", "cpes"):
        field = Package._meta.get_field(name)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

        assert isinstance(field, models.JSONField), name
        assert field.null is False, name
        assert field.blank is True, name
        assert field.get_default() == [], name


def test_the_feedstock_relation_cascades_and_is_reachable_by_name() -> None:
    """A feedstock mapping has no meaning without the package it maps.

    `CASCADE` rather than `PROTECT` or `RESTRICT`: those are what
    `EVIDENCE.02-AUDIT-001` requires of relations touching *evidence* models,
    because Django's deletion collector goes past every append-only refusal.
    Neither of these models is evidence, so that rule does not reach here --
    and nothing deletes a package anyway, since `CPM-AD-25` records absence as an
    observation rather than removing a row.
    """
    field = Feedstock._meta.get_field("package")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert isinstance(field, models.ForeignKey)
    assert field.related_model is Package
    assert field.remote_field.on_delete is models.CASCADE
    assert field.remote_field.related_name == "feedstocks"
    assert field.target_field.name == "id"


def test_one_feedstock_name_per_package_is_declared_as_a_constraint() -> None:
    """The constraint the duplicate-mapping case is refused by.

    Declared over `(package, name)` rather than over `name` alone: two packages
    may legitimately map to a feedstock of the same name, and the constraint
    exists to stop *one* package listing the same feedstock twice.
    `tests/integration/django_apps/test_identity_models.py` proves the refusal
    against a real table; this asserts the declaration that produces it.
    """
    constraints = [
        constraint
        for constraint in Feedstock._meta.constraints  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if isinstance(constraint, models.UniqueConstraint)
    ]

    assert [constraint.name for constraint in constraints] == ["one_feedstock_name_per_package"]
    assert constraints[0].fields == ("package", "name")


@pytest.mark.parametrize(
    ("model", "constraint_name", "field"),
    [
        (Package, "canonical_name_is_present", "canonical_name"),
        (Feedstock, "feedstock_name_is_present", "name"),
    ],
    ids=("packages", "feedstocks"),
)
def test_a_blank_name_is_refused_by_a_check_constraint_rather_than_by_a_form(
    model: type[models.Model],
    constraint_name: str,
    field: str,
) -> None:
    """`blank=False` is a form rule, and nothing in this product runs a form.

    Resolution calls the manager directly (`CPM-AD-25`), as will the ingestion
    path that calls resolution, so a `blank=False` field with no check constraint
    accepts `""` at the database. The consequences differ per model and both are
    bad: a nameless package cannot be corrected, exported or found again, and a
    nameless feedstock is *counted* -- `package.feedstocks` returns it, so "this
    package has a feedstock" reads true for a row naming nothing.

    Asserted here as a declaration; the refusal itself is proven against a real
    table in the integration module, because a constraint declared and never
    migrated satisfies this case and refuses nothing.
    """
    checks = {
        constraint.name: constraint
        for constraint in model._meta.constraints  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if isinstance(constraint, models.CheckConstraint)
    }

    assert constraint_name in checks, sorted(checks)
    assert checks[constraint_name].condition == ~models.Q(**{field: ""})


@pytest.mark.parametrize(
    ("model", "table"),
    [(Package, "packages"), (Feedstock, "feedstocks")],
    ids=("packages", "feedstocks"),
)
def test_each_table_is_named_by_the_architecture_rather_than_derived(
    model: type[models.Model],
    table: str,
) -> None:
    """`identity_package` and `identity_feedstock` are what Django would have derived.

    Rejected for the reason `core/models.py` rejects `core_collectionrun`: moving
    a model between applications must not rename its table, and the schema is
    named by the architecture rather than by which application happened to
    declare the model. The `Meta` docstring on each says so at the definition.
    """
    meta = model._meta  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert meta.db_table == table
    assert meta.verbose_name is not None
    assert meta.verbose_name_plural is not None


def test_an_unsaved_package_renders_the_placeholder_verbatim() -> None:
    """`str(Package())` before any save names the absence, in exactly these words.

    An unsaved instance holds `""` for a non-null `CharField` with no declared
    default, so a `__str__` returning it directly would put an empty string in a
    log line or a failure message with nothing to explain it. What must not
    happen is an exception: a `__str__` that raises is what the message would
    have been.

    The literal is pinned rather than checked for non-blankness. "Some non-empty
    string" is satisfied by returning the class name, by returning `"None"`, and
    by every accident this case exists to catch -- the placeholder *is* the
    method's contribution, so it is the thing asserted.
    """
    assert str(Package()) == "(no canonical name)"


def test_a_named_package_renders_as_its_name() -> None:
    """The ordinary branch, which is every saved row.

    `canonical_name_is_present` makes a blank name impossible on a stored row, so
    this is what a `Package` from the database always renders as -- and asserting
    it is what stops the placeholder branch from quietly becoming both branches.
    """
    assert str(Package(canonical_name="numpy")) == "numpy"


def test_an_unsaved_feedstock_names_both_absences() -> None:
    """The child, whose related object does not exist yet.

    Read off `package_id` rather than `package`: the related object of an unsaved
    instance raises `RelatedObjectDoesNotExist`, which is the exact failure this
    case exists to notice. Both halves are absent here, so both placeholders
    appear.
    """
    assert str(Feedstock()) == "(no name) for no package"


def test_a_mapped_feedstock_names_the_package_it_maps() -> None:
    """The populated branch of both halves, which no other case reaches.

    `package_id` is set directly rather than by saving a `Package`: this module
    touches no database, and the rendering depends on the integer rather than on
    the row it points at -- which is the reason `__str__` reads `package_id` at
    all.
    """
    assert str(Feedstock(name="numpy", package_id=1)) == "numpy for package 1"


def test_a_named_feedstock_with_no_package_names_only_that_absence() -> None:
    """The two placeholders are independent, and a mixed case proves it.

    One `or` covering both would render `(no name) for no package` here, which
    passes the two cases above and loses the half that was actually present.
    """
    assert str(Feedstock(name="numpy")) == "numpy for no package"


def _relation_fields(model: type[models.Model]) -> list[Field[object, object]]:
    """Return a model's concrete relational fields.

    Args:
        model: The model to read.

    Returns:
        Every concrete field that points at another model. Used by the case
        below, which asserts that `Package` points at nothing at all.

    """
    return [field for field in model._meta.concrete_fields if field.is_relation]  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


def test_the_package_row_points_at_nothing() -> None:
    """The row is the anchor, so every relation in the product points *at* it.

    A `ForeignKey` on `Package` would be a mapping the row owned rather than one
    the mapped thing declared, and the first of them is how `Package` acquires a
    workflow state or a derived status by another name.
    """
    assert _relation_fields(Package) == []


# ---------------------------------------------------------------------------
# AC #5 and AC #6: the pair is unique, and the outcome went to a table.
# ---------------------------------------------------------------------------


def test_the_join_key_is_unique_only_where_a_source_claims_the_package() -> None:
    """AC #6's declaration: a partial `UniqueConstraint`, and partial on purpose.

    `identity_source` and `associator_key` are both `blank=True, default=""`, so
    an unconditional constraint would make `("", "")` a single permissible row
    for the whole product -- and `CPM-IDENTITY-S05`'s override path, or any
    creator that is not ingestion, would collide with it for no reason. The
    condition is what says the rule that is meant: a package some source claims
    is unique to that source's key, and a package no source claims is not
    constrained at all.

    The refusal itself is proven against a real table in
    `tests/integration/django_apps/test_identity_resolution.py`; a constraint
    declared and never migrated satisfies this case and refuses nothing.
    """
    constraints = {
        constraint.name: constraint
        for constraint in Package._meta.constraints  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if isinstance(constraint, models.UniqueConstraint)
    }

    assert list(constraints) == ["one_package_per_source_key"]
    pair = constraints["one_package_per_source_key"]
    assert pair.fields == ("identity_source", "associator_key")
    assert pair.condition == ~models.Q(associator_key="")


def test_the_mapping_row_holds_exactly_the_outcome_and_its_subject() -> None:
    """AC #5's other half: `CPM-IDENTITY-S02` added a table, not a column.

    Order included, for the reason the package case gives. What the row must
    *not* hold is anything `Package` already does: a second `canonical_name` or a
    copy of a purl here would make "where is this package's source repository"
    have two answers, which is the failure a child table is usually introduced to
    cause.
    """
    assert _field_names(PackageMapping) == EXPECTED_MAPPING_FIELDS


def test_the_package_field_set_is_unchanged_by_this_story() -> None:
    """AC #5 stated as the thing that must *not* have happened.

    `test_the_package_row_holds_exactly_the_identity_fields` above already pins
    the set; this says why the pinning matters here. `CPM-FR-1` needed three
    states per mapping and the cheapest-looking way to get them is a column per
    mapping on the row that already holds the values. The mapping *outcome* went
    somewhere else, and the two sets still meet only on the surrogate key and the
    resolution instant.

    The set is no longer the one `CPM-IDENTITY-S01` left: `CPM-CURRENCY-S06` added
    `version_authority_order`, which is `CPM-AD-6`'s per-package data and is not a
    per-mapping outcome by any reading -- the disjointness below is what says so,
    and it is the assertion this case is actually about.
    """
    assert _field_names(Package) == EXPECTED_PACKAGE_FIELDS
    assert set(_field_names(Package)) & set(EXPECTED_MAPPING_FIELDS) == {"id", "resolved_at"}


def test_the_mapping_kinds_are_closed_and_cover_every_mapping_column() -> None:
    """`MAPPED_FIELDS` partitions `Package`'s mapping columns, exactly once each.

    This is what makes "a value is written only when its outcome is
    `established`" a rule rather than a habit: resolution reads the table instead
    of naming columns one at a time, so a mapping column with no kind would be a
    value no resolution could record an outcome for, and a kind with no column
    would be an outcome about nothing.

    The feedstock kind maps to no column deliberately -- its value is the
    `Feedstock` child rows -- which is asserted here so the empty tuple reads as
    a decision rather than as the omission it looks like.
    """
    mapped = [name for names in MAPPED_FIELDS.values() for name in names]

    assert tuple(MappingKind.values) == EXPECTED_MAPPING_KINDS
    assert tuple(MAPPED_FIELDS) == EXPECTED_MAPPING_KINDS
    assert MAPPED_FIELDS[MappingKind.FEEDSTOCK.value] == ()
    assert len(mapped) == len(set(mapped)), f"a column is claimed by two kinds: {mapped}"
    assert set(mapped) == {
        "source_repository_url",
        "primary_purl",
        "primary_type",
        "conda_purl",
        "alternative_purls",
        "cpes",
    }
    assert set(mapped) <= set(_field_names(Package))


def test_the_mapping_outcome_was_composed_by_core_rather_than_written_out() -> None:
    """AC #4: the four sentinels by name *and* value, plus one determinate verdict.

    `verify_sentinels` is `core`'s own post-condition, called here rather than
    re-derived: a type that spelled `NOT_APPLICABLE` but valued it `n/a` would
    satisfy every `hasattr` check and still write a value no other policy
    recognises.

    `established` rather than `ok` is the refinement `CPM-AD-5` sanctions, and
    `ESTABLISHED` is asserted to be the value the type actually offers -- the
    service branches on that constant, so a drift between the two would make
    every mapping look unestablished and silently write no values at all.
    """
    offered = dict(MappingOutcome.choices)

    assert verify_sentinels(MappingOutcome) is None
    assert [value for value, _label in MappingOutcome.choices] == [
        *(value for _name, value in SENTINEL_MEMBERS),
        ESTABLISHED,
    ]
    assert ESTABLISHED in offered
    assert OutcomeState.OK.value not in offered, "the determinate value is refined, not inherited (CPM-AD-5)"


def test_the_outcome_column_satisfies_the_derived_status_rules() -> None:
    """AC #4 at the column, which is where `tests/.../test_outcome_field_audit.py` sweeps.

    Restated here rather than left to that audit for the reason the audit's own
    fixture half exists: a sweep that had stopped reaching `identity` would
    report a clean repository, and this fails instead. The four checks are the
    ones `field_failures` makes -- a `CharField`, not nullable, not blank, and a
    default that is one of its own choices -- plus the label check that is how a
    registry-level audit tells a composed table from a hand-rolled one.

    `unknown` is the default because it is the honest value for a mapping no
    resolution has reached: `NULL` and `""` would each be a fifth non-answer with
    no name and no place in the precedence order.
    """
    field = PackageMapping._meta.get_field("outcome")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert isinstance(field, models.CharField)
    assert field.null is False
    assert field.blank is False
    assert field.choices is not None
    offered = dict(field.choices)
    assert {value for _name, value in SENTINEL_MEMBERS} <= set(offered)
    assert all(offered[value] == OutcomeState(value).label for _name, value in SENTINEL_MEMBERS)
    assert str(field.default) in offered
    assert str(field.default) == UNKNOWN
    assert OutcomeState.UNKNOWN.value == UNKNOWN, "verify_sentinels guarantees the two spell it identically"
    assert field.max_length is not None
    assert max(len(value) for value in offered) <= field.max_length


def test_the_kind_column_is_closed_and_carries_no_sentinel() -> None:
    """A kind names which question was asked; the answer is the column beside it.

    Asserted because the two columns sit together and are both fixed-token
    vocabularies, which makes "give `kind` the sentinels too" a plausible next
    edit -- and a `not_applicable` *kind* would be a mapping about nothing rather
    than a mapping that does not apply.
    """
    field = PackageMapping._meta.get_field("kind")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert isinstance(field, models.CharField)
    assert field.null is False
    assert field.blank is False
    assert field.choices is not None
    offered = {value for value, _label in field.choices}
    assert offered == set(EXPECTED_MAPPING_KINDS)
    assert offered.isdisjoint({value for _name, value in SENTINEL_MEMBERS})
    assert field.max_length is not None
    assert max(len(value) for value in offered) <= field.max_length


def test_one_outcome_per_package_mapping_is_declared_as_a_constraint() -> None:
    """One answer per question, guaranteed by the table.

    Without it a second resolution appends a second row and "what did we conclude
    about this package's feedstocks" has two answers with nothing to choose
    between them -- and `CPM-AD-2`'s ordering is not available as a tie-break,
    because this is not evidence and carries no `observed_at`.
    """
    constraints = [
        constraint
        for constraint in PackageMapping._meta.constraints  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if isinstance(constraint, models.UniqueConstraint)
    ]

    assert [constraint.name for constraint in constraints] == ["one_outcome_per_package_mapping"]
    assert constraints[0].fields == ("package", "kind")


def test_the_mapping_relation_cascades_and_points_at_the_surrogate_key() -> None:
    """An outcome about a package that has gone describes nothing.

    `CASCADE` on the same terms as `Feedstock.package`: `EVIDENCE.02-AUDIT-001`'s
    `PROTECT`/`RESTRICT` rule reaches relations touching *evidence* models, and
    neither end of this one is evidence. By the integer primary key `CPM-AD-3`
    fixes, never by `canonical_name`, which is what keeps a name correction
    cascading nowhere.
    """
    field = PackageMapping._meta.get_field("package")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert isinstance(field, models.ForeignKey)
    assert field.related_model is Package
    assert field.remote_field.on_delete is models.CASCADE
    assert field.remote_field.related_name == "mappings"
    assert field.target_field.name == "id"


def test_the_mapping_resolution_instant_is_required_and_reads_no_wall_clock() -> None:
    """`CPM-AD-26` on the third table, for the reason it binds the first two.

    Held per mapping rather than read off the package, because a later resolution
    may settle one mapping and leave another as it found it -- so "when was this
    concluded" is a question about the row, not about the package.
    """
    field = PackageMapping._meta.get_field("resolved_at")  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert isinstance(field, models.DateTimeField)
    assert field.null is False
    assert field.has_default() is False
    assert field.auto_now_add is False
    assert field.auto_now is False


@pytest.mark.parametrize(
    ("instance", "expected"),
    [
        pytest.param(PackageMapping(), "(no kind) is unknown for no package", id="unsaved"),
        pytest.param(
            PackageMapping(kind=MappingKind.FEEDSTOCK, outcome=ESTABLISHED, package_id=1),
            "feedstock is established for package 1",
            id="populated",
        ),
    ],
)
def test_a_mapping_renders_the_question_and_its_answer(instance: PackageMapping, expected: str) -> None:
    """The literals are pinned, on the same terms as the other two `__str__` cases.

    The unsaved instance carries the column's `unknown` default rather than a
    placeholder, which is exactly right and worth pinning: `unknown` is a real
    answer -- nobody has looked -- while the absent kind is not an answer at all.
    """
    assert str(instance) == expected


# ---------------------------------------------------------------------------
# The import rule the leaf vocabulary module exists to make enforceable.
# ---------------------------------------------------------------------------


def test_no_core_module_reads_the_confidence_vocabulary_through_identity_models() -> None:
    """`identity/confidence.py` exists to break a cycle, and this is what keeps it broken.

    `core/models.py` reads `IdentityConfidence` for `PackageHealth.confidence`,
    and `identity/models.py` reads `core.models.AppendOnlyModel` for
    `CPM-IDENTITY-S05`'s audit row. Those two edges together are an import cycle
    that fails at `django.setup()` with `cannot import name 'AppendOnlyModel' from
    partially initialized module`. The vocabulary was moved into a leaf module so
    `core` can read it without reading `identity.models` at all.

    **A module in `core` that imports it from `identity.models` re-arms the
    cycle**, and does not necessarily fail *today* -- it fails the moment
    `core/models.py` reaches that module, which for `core/confidence.py` is a
    plausible edit rather than a hypothetical one, since `PackageHealth` carries
    the very confidence that gate is over. That is the shape of defect a passing
    suite hides, so the rule is swept rather than written in a comment. It was
    already true of one file when this was written: `core/confidence.py` still
    imported from `identity.models` after the split.

    Swept over `core/` alone. `collectors/selection.py` imports it through
    `identity.models` quite legitimately -- `collectors` is a third application and
    closes nothing -- and a repository-wide ban would be a rule about something
    else.
    """
    modules = project_files(CORE_PACKAGE)
    offenders = [
        module.relative_to(SRC_ROOT).as_posix()
        for module in modules
        if FORBIDDEN_CONFIDENCE_IMPORT in module.read_text(encoding="utf-8")
    ]

    assert modules != (), "the sweep found no core modules, so it is vacuous"
    assert offenders == [], (
        f"these core modules read IdentityConfidence through identity.models and re-arm the import cycle "
        f"identity/confidence.py exists to break: {offenders}"
    )


def test_the_core_modules_that_read_the_vocabulary_still_read_it() -> None:
    """The anti-vacuity half: the sweep above passes on a `core` that reads nothing.

    `core/models.py` and `core/confidence.py` both need the vocabulary, so a
    `core` in which neither imported it at all would satisfy the ban perfectly
    while meaning the rule is about nothing. Both are asserted to import it from
    the leaf module by name, which is also what fails if the leaf module is
    deleted and the declaration moves back.
    """
    readers = [
        module.relative_to(SRC_ROOT).as_posix()
        for module in project_files(CORE_PACKAGE)
        if PERMITTED_CONFIDENCE_IMPORT in module.read_text(encoding="utf-8")
    ]

    assert sorted(readers) == sorted(EXPECTED_CONFIDENCE_READERS)
