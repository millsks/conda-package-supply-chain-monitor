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

from conda_package_supply_chain_monitor.identity.models import Feedstock
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import Package
from tests.model_registry import FIXTURE_APP
from tests.model_registry import FIXTURE_LABEL
from tests.model_registry import OBSERVED_AT_FIELD
from tests.model_registry import declares_not_evidence
from tests.model_registry import evidence_marks
from tests.model_registry import first_party_models

if TYPE_CHECKING:
    from django.db.models import Field

#: The unique correctable name, and the constraint the story turns on.
CANONICAL_NAME: Final[str] = "canonical_name"

#: Exactly what `Package` holds, in declaration order, plus the surrogate key.
#: `CPM-AD-1`'s four categories -- canonical name, cross-ecosystem mappings,
#: provenance, confidence -- projected onto PRD Appendix A.1's stored-field
#: column, and nothing else. Written out rather than counted: a length assertion
#: would pass while a field was swapped for another.
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

#: The confidence values, in the PRD's own spelling. The hyphen in the middle
#: value is the assertion: `CPM-AD-5`'s fixed-lowercase rule binds derived-status
#: vocabularies, and confidence is identity provenance rather than a derived
#: status, so matching the governing document verbatim is what keeps
#: `CPM-IDENTITY-S03`'s gate from translating between two spellings.
EXPECTED_CONFIDENCE_VALUES: Final[tuple[str, ...]] = ("verified", "inventory-derived", "unmapped")

#: The two models this story adds, for the cases that hold for both.
IDENTITY_MODELS: Final[tuple[type[models.Model], ...]] = (Package, Feedstock)


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


@pytest.mark.parametrize("model", IDENTITY_MODELS, ids=lambda model: model.__name__)
def test_no_projected_or_observed_name_reaches_either_row(model: type[models.Model]) -> None:
    """The **Never** list, asserted as a disjointness rather than field by field.

    Each of these is projected by `reporting` at read time -- from the rollup
    (`CPM-AD-11`), from evidence, or from `inventory_snapshots` (`CPM-AD-25`) --
    and every one of them appears in PRD Appendix A.1 beside the identity fields,
    which is precisely why somebody adds one.
    """
    trespassers = FORBIDDEN_FIELD_NAMES & set(_field_names(model))

    assert trespassers == set(), f"{model.__name__} holds projected or observed fields: {sorted(trespassers)}"


@pytest.mark.parametrize("model", IDENTITY_MODELS, ids=lambda model: model.__name__)
def test_neither_row_declares_a_derived_status(model: type[models.Model]) -> None:
    """`CPM-AD-1`: no derived status on the package row, by any spelling.

    A column named `*_status` would also be swept into the derived-status
    vocabulary by `tests/unit/django_apps/test_outcome_field_audit.py` and held
    to `OutcomeState`'s four sentinels -- so the per-mapping `not_applicable`
    that `CPM-FR-1` needs cannot arrive as a status column here. It is
    `CPM-IDENTITY-S02`'s, with the semantics that story defines.
    """
    offenders = [
        name
        for name in _field_names(model)
        if name in DERIVED_STATUS_NAMES or name.endswith(DERIVED_STATUS_SUFFIXES)
    ]

    assert offenders == [], f"{model.__name__} declares derived-status fields: {offenders}"


@pytest.mark.parametrize("model", IDENTITY_MODELS, ids=lambda model: model.__name__)
def test_neither_model_is_evidence_and_neither_takes_the_escape(model: type[models.Model]) -> None:
    """AC #6, stated where the models are declared rather than only in the registry guard.

    Neither carries any of the three marks `tests/model_registry.py` reads -- no
    `observed_at`, no `AppendOnlyModel`, and the app label is `identity` rather
    than `evidence` -- so neither may declare `not_evidence = True` either. That
    attribute is `CPM-AD-2`'s recorded exemption *for a model that carries a
    mark*, and a third user of it fails
    `tests/unit/django_apps/test_evidence_inheritance_audit.py` until somebody
    records the decision. A package row is not an observation; it is the thing
    observations are about.
    """
    assert OBSERVED_AT_FIELD not in _field_names(model)
    assert evidence_marks(model) == []
    assert declares_not_evidence(model) is False


# ---------------------------------------------------------------------------
# AC #4: two contracts, and no field named for the other one.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", IDENTITY_MODELS, ids=lambda model: model.__name__)
def test_every_field_name_is_a_snake_case_identifier(model: type[models.Model]) -> None:
    """PRD Appendix A.1, "Two contracts": stored fields are valid snake_case identifiers."""
    malformed = [name for name in _field_names(model) if not STORED_FIELD_NAME.match(name)]

    assert malformed == [], f"{model.__name__} declares non-identifier field names: {malformed}"


@pytest.mark.parametrize("model", IDENTITY_MODELS, ids=lambda model: model.__name__)
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
    """"No identifiers" is `[]`, which is a value, and never NULL, which is a second one.

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
