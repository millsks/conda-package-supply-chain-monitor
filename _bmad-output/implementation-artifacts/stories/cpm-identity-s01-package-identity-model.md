---
title: 'CPM-IDENTITY-S01: The package identity model'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '8ccea02154940c4e712ccd2060b2260c8faf7b7c'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
warnings: ['oversized']
deferred:
  - summary: >-
      `core.CollectionRun.package_id` is still a bare integer now that a `packages` table
      exists to point at, so the ledger can record a run against a package id nothing supplies.
    evidence: |-
      `CPM-AD-3` says every row references the package by its integer primary key, and
      `core/models.py`'s `CollectionRun` docstring says `CPM-EP-IDENTITY` converts it to a
      `ForeignKey(..., on_delete=PROTECT)` "when the model lands". The model has landed here.
      It is not converted because a real foreign key is enforced immediately, while
      `core/ledger.py`'s `_require_package_key` rejects only negatives and every integration
      case passes the literal `A_PACKAGE_ID = 4269` for a package no test creates -- so the
      conversion changes the recorder's contract and rewrites existing `core` tests. The
      conversion is also a `RenameField` + `AlterField` pair rather than an `AlterField`,
      because the attribute is named `package_id` and an FK named `package` reads to the
      autodetector as a remove-and-add. `CPM-IDENTITY-S06` is the story that first makes
      packages exist to point at, and it is where this belongs.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py:710
    severity: medium
  - summary: >-
      `canonical_name` uniqueness is byte-exact, so `numpy` and `NumPy` persist as two
      packages -- which defeats "one row per package" for an ecosystem that normalizes names.
    evidence: |-
      PyPI names normalize under PEP 503 and conda-forge feedstock names are lowercase by
      convention, so two spellings of one package are the same package. There is no
      normalization rule, no `Lower()` functional unique index and no check. The story
      documents every other identity decision at length and is silent on this one. It is
      resolution's to settle -- `CPM-IDENTITY-S02` owns what a canonical name *is* before it
      is stored -- but nothing currently records that it is unsettled.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/models.py -- Package.canonical_name
    severity: medium
  - summary: >-
      Nothing ties `confidence` to the provenance that should justify it: a row may be
      `verified` with an empty `identity_source` and `associator_key`.
    evidence: |-
      `CPM-FR-2` says every package row carries an identity source, an associator key and a
      confidence, and `CPM-AD-4` gates every outward claim on the confidence value -- so the
      three are one invariant rather than three independent columns. There is no
      `CheckConstraint`, no test and no recorded owner. `CPM-IDENTITY-S02` writes all three
      together and is the natural place to enforce it, but the gap is real until it does.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/models.py -- Package.confidence
    severity: medium
  - summary: >-
      `alternative_purls` and `cpes` accept any JSON value -- a dict, a bare string, or a list
      of nulls -- because a `JSONField` validates shape nowhere.
    evidence: |-
      Both columns are documented as lists of identifiers and defaulted to `list`, and the
      round-trip test writes well-formed lists. Nothing refuses a malformed one, and there is
      no negative case. Shape validation belongs with the writer that produces them
      (`CPM-IDENTITY-S02`'s resolution service), in the `core/ledger.py` `_require_*` shape
      this repository already uses, rather than as a Django field validator.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/models.py -- Package.alternative_purls, Package.cpes
    severity: low
  - summary: >-
      Neither `confidence` nor `resolved_at` is indexed, and both are what the next stories
      filter and sort on.
    evidence: |-
      `CPM-IDENTITY-S04` selects every package at `unmapped` or `inventory-derived`
      confidence, and freshness reads `resolved_at`. Adding either index now would be
      speculative -- no query exists to measure -- but the omission is undeclared in a module
      that argues at length about why `canonical_name` must *not* carry a second index. The
      story that writes the query is the one that should size the index.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/models.py -- Package.Meta
    severity: low
  - summary: >-
      The three new AppConfig property audits cover `identity` alone, so `core` is held to
      none of them and the third domain app will inherit none either.
    evidence: |-
      `test_the_app_config_declares_no_default_auto_field`,
      `test_the_app_config_declares_no_label_of_its_own` and
      `test_the_application_declares_no_urls_serializers_or_tasks` are written against
      `identity`'s config by name, and `tests/unit/django_apps/test_core_app.py` has no
      counterpart. These are per-config properties rather than adoption facts, so they are
      exactly the kind that should sweep `tests/model_registry.first_party_app_names()`.
      Generalizing them means editing `test_core_app.py`, which is outside this story's shape.
    location: >-
      tests/unit/django_apps/test_identity_app.py
    severity: low
  - summary: >-
      Nothing reconciles the generated migration against the model, and no test introspects
      the real table names despite an established pattern for it.
    evidence: |-
      The four `Final[int]` widths, the `choices` list and the two check constraints are
      recorded in `0001_package_identity.py` and asserted only against `_meta`. The sole
      guard is `tests/unit/django_apps/test_migration_completeness.py`, whose autodetector
      sweep notices a *missing* migration rather than a wrong one.
      `tests/integration/test_postgres_schema.py` establishes the pattern for asserting
      against the real schema; `db_table` is currently checked against `_meta` alone.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/migrations/0001_package_identity.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** `django_apps/identity` does not exist. `core.CollectionRun.package_id` already
carries the integer package reference `CPM-AD-3` fixes against a table nothing supplies, and
every epic after this one references a package by that key. Until one mutable row per package
exists holding identity and nothing else, there is nothing for evidence, policy or the review
queue to point at -- and every day the row does not exist is a day a collector could be given a
version column on it instead.

**Approach:** Add the `identity` application under the second import root with a `Package` model
and a `Feedstock` child for the zero-or-more conda-forge mapping `CPM-FR-1` requires, complete
both halves of the two-line adoption, and prove by test that the row holds only canonical name,
cross-ecosystem mappings, provenance and confidence -- and that no field is named for a PRD
export column heading.

## Boundaries & Constraints

**Always:**

- `Package`'s primary key is the project-wide `BigAutoField` (`base.py:149`); `canonical_name`
  is `unique=True` and carries **no** `db_index=True` -- unique already creates the index, the
  rule stated at `src/django_service/users/models.py:23` and pinned by
  `tests/unit/users/test_models.py:20`. That is what "unique indexed column" means here.
- Nothing references a package by `canonical_name`: no `ForeignKey(..., to_field="canonical_name")`
  anywhere, so correcting the name cascades nowhere (`CPM-AD-3`).
- Stored field names are snake_case identifiers. Export headings are the reporting layer's, and
  no field is named for one (PRD Appendix A.1, "Two contracts").
- Concrete models declare an explicit `db_table` with a `Meta` docstring saying why Django's
  derived name is rejected -- the `core/models.py:712` shape. `packages` and `feedstocks`.
- Every field carries a `#:` comment naming the rule it serves; fields are written
  `models.X(_("verbose name"), ...)`; column widths are module-private `Final[int]` constants,
  never inline literals.
- Timestamps are plain `DateTimeField`s whose value the caller supplies from an injected
  `Clock`. Never `auto_now_add`, never `auto_now`, never `timezone.now()` (`CPM-AD-26`;
  `tests/unit/django_apps/test_clock_audit.py` fails the build otherwise).
- Adoption is both halves or neither: `LOCAL_APPS` in `src/config/settings/base.py` **and**
  `adopted_apps` in `component.toml`, appended after `core`, never before `django_service.users`.
- `Feedstock.package` is `ForeignKey(Package, on_delete=models.CASCADE, related_name="feedstocks")`.
  A feedstock mapping has no meaning without the package it maps; `PROTECT`/`RESTRICT` are for
  relations that touch evidence models (`EVIDENCE.02-AUDIT-001`), which neither of these is.
- `pixi` is the only runner. Never `uv`, never bare `python`, never `pip`.

**Block If:**

- Satisfying an acceptance criterion appears to require a derived status, an observation, a
  workflow state or an internal usage signal on the `Package` row. That contradicts `CPM-AD-1`
  and is not this story's to resolve.
- Landing the model cannot be done without changing `core/ledger.py`'s recorder signature or
  editing an existing `core` test's expectations.

**Never:**

- Do **not** convert `core.CollectionRun.package_id` to a `ForeignKey`. See Design Notes.
- Do **not** add per-mapping `not_applicable` / `unmapped` outcome columns. `CPM-IDENTITY-S02`
  owns resolution semantics and adds what it needs.
- Do **not** put any of these on `Package`: `priority_bucket`, `rank`, `score`, `work_type`,
  `vulnerability_rollup`, `risk_level`, `latest_vuln_count`, `priority_description`,
  `priority_source`, `priority_reason`, `local_build_status`, `verified_at`, `platforms`, `apps`,
  `downloads`, `versions`, `internal_component_count`, `internal_lob_count`, `tracking_title`,
  `tracking_issue_url`, `staged_recipe_pr_url`, `local_recipe_url`.
- Do **not** declare a field named `observed_at` and do **not** inherit `AppendOnlyModel`:
  either mark makes the model evidence in `tests/model_registry.py` and `Package` is not
  evidence. Do not take the `not_evidence` escape either -- it is for models that carry a mark.
- No `ready()`, no `default_auto_field`, no `label` on the `AppConfig`.
- No admin, serializers, views, URLs, Celery tasks, resolution service or override model. Those
  are `CPM-IDENTITY-S02`, `-S05` and `CPM-EP-APP`.
- No new dependency, no `pyproject.toml` `sources` key, no `DATABASE_ROUTERS`, no
  `NAVIGATION_REGISTRY`, no `MIDDLEWARE` or auth-class contribution.
- No `pytest.skip` / `xfail` / `importorskip`, no `# pragma: no cover`, no `databases=` on
  `django_db`, no `connection.vendor` branch.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Canonical name is unique | two `Package` rows saved with `canonical_name="numpy"` | the first persists, the second is refused by the database | `IntegrityError` |
| A shell at ingestion confidence | `Package` saved with only `canonical_name` and `resolved_at` | row persists; `confidence == "unmapped"`, every text mapping `""`, `alternative_purls == []`, `cpes == []` | No error expected |
| Zero feedstocks is a valid mapping | `package.feedstocks.all()` on a freshly saved row | empty queryset, not an error -- `CPM-FR-1` says "zero or more" | No error expected |
| Two feedstocks for one package | two `Feedstock` rows, same `package`, names `numpy` and `numpy-base` | both persist and both are reachable from `package.feedstocks` | No error expected |
| The same feedstock twice | two `Feedstock` rows with identical `package` and `name` | the second is refused by `one_feedstock_name_per_package` | `IntegrityError` |
| One feedstock name, two packages | `Feedstock(name="numpy")` under package A and under package B | both persist -- the constraint is per package, not global | No error expected |
| Correcting a canonical name cascades nowhere | a saved `Package` with feedstocks; `canonical_name` reassigned and saved | the update succeeds and no related row changes, because nothing points at the name | No error expected |
| An unsaved row is printable | `str(Package())` before any save | a string naming the absent canonical name | No `AttributeError` |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/models.py:604-730` -- `RunLedgerModel`
  and `CollectionRun`: the concrete-model shape to copy. `#:` field comments, `db_table` with a
  `Meta` docstring, `verbose_name`/`verbose_name_plural`, a `__str__` that guards an unsaved
  instance holding `None`, and `_NAME_LENGTH`-style `Final[int]` width constants at :119-139.
- `core/models.py:419-563` -- `AppendOnlyModel`. **Read-only.** `Package` must not inherit it
  and must not declare `observed_at`; :428-433 records that `auto_now_add` is banned here.
- `core/models.py:710` -- `CollectionRun.package_id`, the integer reference `CPM-AD-3` fixes.
  **Read-only in this story** (Design Notes explains why).
- `core/clock.py:81-160` -- `Clock`, `SystemClock`, `FixedClock`, `is_aware`. Any instant a
  caller writes to `Package.resolved_at` comes from here; the model itself reads no clock.
- `core/outcomes.py:90` -- `OutcomeState`, and `:212` `outcome_type`. **Read-only, and not used
  here:** `confidence` is identity provenance, not a derived status, so it is a plain
  `models.TextChoices` declared in `identity`.
- `src/django_service/users/models.py:23,:75` -- the "`unique=True` already indexes, so no
  `db_index=True`" rule, pinned by `tests/unit/users/test_models.py:20-23`.
- `src/config/settings/base.py:190-203` -- `LOCAL_APPS`; append after `core` at :201.
  `DEFAULT_AUTO_FIELD` at :149 is why the AppConfig sets none.
- `component.toml:66` -- `adopted_apps`; append the same dotted name.
- `tests/unit/test_component_declaration.py:291` and `:511` -- **two** exact-equality assertions
  on `adopted_apps` (a list and a tuple). Both must be updated or the gate fails.
- `tests/unit/startup/test_installed_apps_ordering.py:132,:146` -- reconciles the two adoption
  halves and forbids preceding `django_service.users`.
- `tests/unit/django_apps/test_migration_completeness.py:83` -- autodetector sweep over every
  first-party app. A model without a migration fails here; `pixi run ci` has no
  `makemigrations --check` step, so this test is the gate.
- `tests/model_registry.py:129` `FIRST_PARTY_APP_NAMES` -- the anti-vacuity anchor; add
  `identity`. `tests/unit/test_model_registry.py:261` asserts `evidence_models() == []` and that
  exactly the run ledger escapes -- `Package` must keep both true.
- `tests/unit/django_apps/test_core_app.py` -- the app-installation test to mirror; it hardcodes
  `core`, so it is a template, not a sweep.
- `tests/unit/conftest.py` (`fixed_clock`) and `tests/clocks.py` (`FIXED_INSTANT`) -- how a test
  obtains an aware instant.
- `core/migrations/0002_run_ledger.py` -- generated-migration house style: intent-named file,
  explicit `dependencies`, generator header kept.
- `pixi.toml:606,:607,:615,:668,:689` -- `test`, `test-integration`, `test-cov`, `gate-postgres`,
  `ci`. There is no `cov` task and no `check` task in this repository.

## Tasks & Acceptance

**Execution:**

- `src/django_apps/conda_package_supply_chain_monitor/identity/__init__.py` -- create, empty --
  `core/__init__.py` is empty and the package must be importable from the second root.
- `.../identity/apps.py` -- add `IdentityConfig(AppConfig)` with `name` and `verbose_name` only
  -- `test_core_app.py:128`'s shape, so no stage-2 behaviour is smuggled into a domain app.
- `.../identity/models.py` -- add `IdentityConfidence(models.TextChoices)`, `Package` and
  `Feedstock` -- the story's whole subject. Widths as module-private `Final[int]` constants.
- `.../identity/migrations/__init__.py` -- create, empty; then generate
  `0001_package_identity.py` with `pixi run makemigrations` and rename it to that intent --
  `test_migration_completeness.py` fails without it.
- `src/config/settings/base.py` -- append `"conda_package_supply_chain_monitor.identity"` to
  `LOCAL_APPS` after `core` -- this is the half that actually installs the app today.
- `component.toml` -- append the same string to `adopted_apps` -- the `AD-8` declaration half.
- `tests/unit/test_component_declaration.py` -- update both exact-equality assertions -- they
  freeze the adopted list by design and are meant to be edited deliberately.
- `tests/model_registry.py` -- add the app name to `FIRST_PARTY_APP_NAMES` -- keeps the
  anti-vacuity anchor honest now that a second first-party app exists.
- `tests/unit/django_apps/test_identity_app.py` -- new; the app is installed, labelled
  `identity`, resolves from the second import root, declares no `ready()`, and follows the
  stage-2 owner.
- `tests/unit/django_apps/test_identity_models.py` -- new; `_meta` introspection only, no
  database. Covers AC 1-4 below and the field-name half of the matrix.
- `tests/integration/django_apps/test_identity_models.py` -- new; every matrix row that needs a
  real table, each `@pytest.mark.django_db`.

**Acceptance Criteria:**

1. Given the installed application registry, when `identity` is looked up, then it is present as
   `conda_package_supply_chain_monitor.identity` with label `identity`, its `AppConfig` declares
   no `ready()` and no `default_auto_field`, its path resolves under `src/django_apps/`, and its
   index in `INSTALLED_APPS` is greater than `django_service.users`'.
2. Given `Package._meta`, when the primary key is inspected, then it is an auto-created
   `BigAutoField`, and `canonical_name` is `unique=True` with `db_index` False -- and a test
   states in its docstring that `unique=True` is what supplies the index.
3. Given `Package._meta`, when its concrete field names are collected, then the set is disjoint
   from the forbidden names in **Never** above, contains no `observed_at`, and contains nothing
   named `status`, `outcome`, `*_status` or `*_outcome`.
4. Given `Package._meta` and `Feedstock._meta`, when field names are checked against PRD
   Appendix A.1, then every name matches `^[a-z][a-z0-9_]*$` and none equals an export column
   heading that differs from its stored name (`Core_Python_Package_Name`, `Package`, `P`, `Rank`,
   `Score`, `Work`, `Vuln`, `Platforms`, `Apps`, `Downloads`, `Versions`,
   `Conda-Forge_FeedStock_URL`, `Conda-Forge_Metadata_URL`, `Staged_Recipes_PR_URL`,
   `Local_Recipes_URL`, `Local_Build_Status`, `Verification_Timestamp_UTC`, `associator_status`,
   `Priority_Bucket_Description`, `Priority_Source`, `Priority_Reason`, `JFROG_risk_level`,
   `JFROG_latest_vuln_count`, `OpenTeams_Title`).
5. Given every model in the first-party registry, when their relational fields are swept, then
   none targets `Package.canonical_name` -- `field.target_field.name` is never `canonical_name`
   for a relation whose related model is `Package`.
6. Given `tests/model_registry.py`, when `evidence_models()` and `exempt_models()` are read after
   `identity` is installed, then the first is still empty and the second is still exactly the run
   ledger -- `Package` and `Feedstock` are neither evidence nor exempt.

## Spec Change Log

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 0, medium 5, low 8)
- defer: 7: (high 0, medium 3, low 4)
- reject: 17: (high 0, medium 2, low 15)
- addressed_findings:
  - `[medium]` `[patch]` Three statements this change falsified were still in the tree, each
    justifying the `CollectionRun.package_id` deferral with "`identity.Package` does not exist
    yet". Flagged independently by two reviewers. Rewritten in `core/models.py`'s `CollectionRun`
    docstring and field comment, `tests/unit/django_apps/test_run_ledger.py`'s
    `test_the_package_reference_is_a_nullable_indexed_integer` docstring, and `tests/collectors.py`'s
    fixture comment, to give the current reason. Prose only — no field converted, no recorder
    signature touched, no assertion changed.
  - `[medium]` `[patch]` A blank identity persisted: `blank=False` is form-level only, so a
    `Package` with `canonical_name=""` and a nameless `Feedstock` both saved, and the nameless
    feedstock counted toward `package.feedstocks`. Added the `canonical_name_is_present` and
    `feedstock_name_is_present` check constraints, regenerated the migration, and added a
    parametrized unit case plus two integration refusals.
  - `[medium]` `[patch]` `resolved_at`'s NOT NULL refusal was asserted in `_meta` but never
    attempted. Added an integration case that makes the write and asserts the database refuses it.
  - `[medium]` `[patch]` `inventory-derived` — the one deliberate spelling decision in the story —
    was proven only against `_meta.choices`, never written to and read back from a column. Added an
    integration round-trip asserting the stored literal.
  - `[medium]` `[patch]` `sprint-status.yaml` still read `ready-for-dev` for this story and
    `backlog` for the epic while the story was implemented in the same change. Set to `done` and
    `in-progress`.
  - `[low]` `[patch]` `_IDENTIFIER_LENGTH`'s comment claimed it was "narrower than a URL" while
    both constants are 512. Rewritten to say they are deliberately equal, and why they stay separate.
  - `[low]` `[patch]` `_CONFIDENCE_LENGTH`'s comment appealed to `core`'s `_STATUS_LENGTH` as "the
    same shape"; that constant is 16 and this is 32. The appeal is gone; each width is now argued
    from its own longest value.
  - `[low]` `[patch]` `Package.__str__`'s `Returns:` attributed its placeholder to unsaved
    instances, but a saved blank row rendered identically. Corrected — and the new check constraint
    makes the claim true rather than merely restated.
  - `[low]` `[patch]` The `__str__` assertions were weak: one asserted only that the output was
    non-blank, and `Feedstock.__str__`'s populated branches were executed but never checked. Five
    cases now pin exact strings, including a mixed case that catches one `or` covering both halves.
  - `[low]` `[patch]` The app-layout guard proved absence but never asserted the `migrations`
    package exists — the half `test_migration_completeness.py` depends on — and only caught
    file-shaped surfaces, so a `tasks/` directory would have passed. Both fixed.
  - `[low]` `[patch]` The relation sweep was narrower than its own name: `ForeignKey |
    OneToOneField` is redundant and excluded `ManyToManyField` and `ForeignObject`. Widened to every
    relational field, resolving through intermediate tables, with an `isolate_apps` fixture that
    declares a real `to_field="canonical_name"` so the detector is measured rather than assumed.
  - `[low]` `[patch]` The `component.toml` comment had been edited to enumerate `.core`, `.identity`
    — prose needing a re-edit on every future adoption, which is the drift `adopted_apps` exists to
    prevent. Restored to a general statement.
  - `[low]` `[patch]` Style drift between the two new test modules: bare `#` comments and
    un-annotated constants in one where the other used `Final[...]` with `#:`, plus bare
    `# noqa: SLF001` markers where the repository's carry a reason. Brought into line.

## Design Notes

**The field set, and where each field comes from.** `CPM-AD-1`'s four categories, projected onto
PRD Appendix A.1's stored-field column. Nothing else goes on either table.

| Model | Field | Shape | Category |
|---|---|---|---|
| `Package` | `canonical_name` | `CharField(max_length=_NAME_LENGTH, unique=True)` | canonical name |
| `Package` | `display_name` | `CharField(max_length=_NAME_LENGTH, blank=True, default="")` | canonical name |
| `Package` | `source_repository_url` | `URLField(max_length=_URL_LENGTH, blank=True, default="")` | mapping |
| `Package` | `primary_purl` | `CharField(max_length=_IDENTIFIER_LENGTH, blank=True, default="")` | mapping |
| `Package` | `primary_type` | `CharField(max_length=_NAME_LENGTH, blank=True, default="")` | mapping |
| `Package` | `conda_purl` | `CharField(max_length=_IDENTIFIER_LENGTH, blank=True, default="")` | mapping |
| `Package` | `alternative_purls` | `JSONField(default=list, blank=True)` | mapping (multi-valued) |
| `Package` | `cpes` | `JSONField(default=list, blank=True)` | mapping (multi-valued) |
| `Package` | `identity_source` | `CharField(max_length=_NAME_LENGTH, blank=True, default="")` | provenance |
| `Package` | `associator_key` | `CharField(max_length=_IDENTIFIER_LENGTH, blank=True, default="")` | provenance |
| `Package` | `resolved_at` | `DateTimeField()` | provenance |
| `Package` | `confidence` | `CharField(max_length=_CONFIDENCE_LENGTH, choices=IdentityConfidence.choices, default=IdentityConfidence.UNMAPPED)` | confidence |
| `Feedstock` | `package` | `ForeignKey(Package, CASCADE, related_name="feedstocks")` | mapping |
| `Feedstock` | `name` | `CharField(max_length=_NAME_LENGTH)` | mapping |
| `Feedstock` | `url` | `URLField(max_length=_URL_LENGTH, blank=True, default="")` | mapping |
| `Feedstock` | `metadata_url` | `URLField(max_length=_URL_LENGTH, blank=True, default="")` | mapping |

`Feedstock.Meta` carries `constraints = [models.UniqueConstraint(fields=["package", "name"],
name="one_feedstock_name_per_package")]`. `URLField` and `JSONField` are both firsts in this
repository; both are Django built-ins and neither is backend-specific, which matters because the
suite runs on the sqlite fallback and the gate runs on `postgres:17`. `blank=True` on the two
`JSONField`s is what makes an empty list a valid form value rather than a validation error; the
column stays `NOT NULL` with a `list` default, so "no identifiers" is `[]` and never `NULL` --
Appendix A.1's "blank means missing" rule applied to a multi-valued column.

**`CollectionRun.package_id` stays an integer, and that is a decision rather than an omission.**
`core/models.py:687-693` says `CPM-EP-IDENTITY` converts it to a `ForeignKey(..., on_delete=PROTECT)`
"when the model lands", and the model lands here. It is deliberately not converted, for two
reasons the docstring could not have known. First, the conversion is not a field swap: the
attribute is named `package_id`, so an FK named `package` is a remove-and-add to the autodetector,
and preserving the column needs a hand-written `RenameField` + `AlterField` pair. Second, and
decisively, a real foreign key is enforced immediately -- `core/ledger.py`'s recorder currently
accepts any positive integer as a package key and its tests pass literals for packages that do not
exist, so the conversion changes the ledger's contract and breaks existing `core` tests. That is a
ledger story with its own acceptance criteria, and `CPM-IDENTITY-S06` -- which is what first makes
packages exist to point at -- is where it belongs. This story leaves `core` untouched.

**Feedstocks are a second table because `CPM-FR-1` says "zero or more".** A single
`feedstock_url` column cannot hold two, and Appendix A.1's data rule that multi-value export
columns "separate with `;`" is the export contract for exactly this: the reporting layer joins the
child rows. `staged_recipe_pr_url` and `local_recipe_url` are deliberately excluded -- A.1 groups
them as "Conda-forge state" and "Internal packaging state", which is the state of an in-flight
recipe, not a mapping between ecosystems.

**Per-mapping `not_applicable` is `CPM-IDENTITY-S02`'s.** `CPM-FR-1` requires a mapping that does
not apply to record `not_applicable`, distinct from `unmapped` and from a successful empty result.
That is resolution's output, it is bound to S02's acceptance criteria, and a column named
`*_status` would be swept by `test_outcome_field_audit.py` into the derived-status vocabulary --
which is exactly what AC 2 of this story says the row must not hold. S02 adds the columns with the
semantics it defines.

**`confidence` keeps the PRD's own spelling**, `verified` / `inventory-derived` / `unmapped`
(PRD glossary; `CPM-AD-4`'s table). The hyphen is deliberate: this is not an `OutcomeState`, the
fixed-lowercase rule in `CPM-AD-5` binds derived-status vocabularies only, and matching the
governing document verbatim is what keeps `CPM-IDENTITY-S03`'s gate from translating between two
spellings of the same three values. The default is `UNMAPPED`, because `CPM-AD-25` creates the
shell at that confidence.

**`resolved_at` is non-null and clock-supplied.** `CPM-FR-2` requires the resolution timestamp to
be recorded, and `CPM-AD-25` makes resolution the only creator of a package row -- so there is no
state in which a `Package` exists without one. Non-null forces every caller to hand in an instant,
which is how `RunLedgerModel.started_at` (`core/models.py:643`) already behaves and the only shape
compatible with the clock audit. The model performs no awareness check of its own; that is the
service's job, in the `core/ledger.py:139` `_require_*` shape, and it arrives with S02.

Golden example -- the field shape, verbatim in style:

```python
#: The one correctable name for this package. `unique=True` and no `db_index`:
#: unique already creates the index (`CPM-AD-3`), and a second one would be an
#: index Django maintains for nothing.
canonical_name = models.CharField(_("canonical name"), max_length=_NAME_LENGTH, unique=True)
```

## Verification

**Commands:**

- `pixi run test` -- expected: exits 0; the new unit modules run and no existing unit test regresses.
- `pixi run test-integration` -- expected: exits 0; every `django_db` case in the new integration
  module passes.
- `pixi run ci` -- expected: exits 0 through precommit, build, typecheck, lint and test-cov, with
  coverage at or above 90%.
- `pixi run gate-postgres` -- expected: exits 0 with nothing skipped. The unique constraint and
  `one_feedstock_name_per_package` are database-enforced, so they are only genuinely proven
  against `postgres:17` rather than the sqlite fallback.

## Auto Run Result

Status: done

**What was implemented.** The `identity` application, and the first table in this product that a
package can be. `Package` holds one mutable row per package carrying canonical name, cross-ecosystem
mappings, provenance and confidence, and nothing else; `Feedstock` holds the zero-or-more conda-forge
mapping `CPM-FR-1` requires, which a single column could not. Adoption is complete on both halves --
`LOCAL_APPS` installs the app and `component.toml` declares it -- and the tests prove the row's
*shape* rather than merely its contents: the field set is disjoint from the twenty-two names
`CPM-AD-1` projects from the rollup and from evidence, every field name is a snake_case identifier
that is none of the twenty-four historical export headings, and a registry-wide sweep proves nothing
anywhere targets `Package.canonical_name`, which is what makes correcting a name cascade nowhere.

**Files changed.**

- `src/django_apps/conda_package_supply_chain_monitor/identity/models.py` -- new. `IdentityConfidence`,
  `Package`, `Feedstock`, four `Final[int]` widths, two check constraints and the
  `one_feedstock_name_per_package` unique constraint.
- `.../identity/apps.py`, `.../identity/__init__.py`, `.../identity/migrations/__init__.py` -- new.
  `IdentityConfig` carries `name` and `verbose_name` and nothing else.
- `.../identity/migrations/0001_package_identity.py` -- new. Both tables, both check constraints,
  the unique constraint.
- `src/config/settings/base.py`, `component.toml` -- the two halves of the adoption.
- `src/django_apps/conda_package_supply_chain_monitor/core/models.py`, `tests/collectors.py`,
  `tests/unit/django_apps/test_run_ledger.py` -- prose only: the three places that justified the
  `package_id` deferral with a fact this change made false.
- `tests/model_registry.py` -- `identity` added to the anti-vacuity anchor.
- `tests/unit/test_component_declaration.py` -- both frozen `adopted_apps` assertions widened.
- `tests/unit/django_apps/test_identity_app.py`, `tests/unit/django_apps/test_identity_models.py`,
  `tests/integration/django_apps/test_identity_models.py` -- new.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- this story `done`, the epic
  `in-progress`.

**Review findings:** 13 patched (0 high, 5 medium, 8 low), 7 deferred, 17 rejected. Four review
layers ran in parallel over the full diff.

**Follow-up review recommended:** true. Patched counts are high 0, medium 5, low 8; the score is
`3 x 5 + 1 x 8 = 23`, at or above the threshold of 5.

**The finding that mattered most was a sentence, not a defect.** Two independent reviewers
converged on it: `core/models.py` said the package reference is an integer because "`identity.Package`
does not exist yet (`CPM-EP-IDENTITY` is two epics away)", and `tests/unit/django_apps/test_run_ledger.py`
pinned the old shape on the same premise. This change made both false while leaving the deferral
correct, so the next reader would have found a decision defended by a fact they could disprove in one
grep -- and a test certifying the old shape for a reason that no longer applied. The code was right
and the reasons were stale, which is the failure mode a design argued this thoroughly is most exposed
to.

**Verification.** `pixi run ci` exits 0 -- 3130 passed, 2 skipped, coverage 97.85% against a 90%
floor, with `identity/models.py` and `identity/apps.py` each at 100%. `pixi run gate-postgres` exits
0 with the same counts against a throwaway `postgres:17`, which is where the two check constraints,
the unique constraints and the `resolved_at` NOT NULL refusal are genuinely proven rather than
asserted -- the default suite runs on the sqlite fallback. `pixi run test` (2711) and
`pixi run test-integration` (413 passed, 8 skipped) were run separately. Against the pre-story
baseline of 3046 passed / 2 skipped this adds 84 tests and no new skips; the two skips are the
pre-existing redis-only cases in `test_shared_allowance.py`. Every one of the eight I/O matrix rows
has a covering test that ran and passed.

**Residual risks.** The seven `deferred` entries, of which three matter. The first is the one that
qualifies what this story may be said to have delivered: `CollectionRun.package_id` is still a bare
integer, so the ledger can record a run against a package id nothing supplies -- at the exact moment
a real `packages` table exists to point at. The deferral is deliberate and argued, but it is a
promise `CPM-IDENTITY-S06` now owes. The second is that `canonical_name` uniqueness is byte-exact:
`numpy` and `NumPy` are two packages today, which is the wrong answer for an ecosystem that
normalizes names, and nothing in the model says so. The third is that `confidence` and the
provenance that should justify it are three independent columns rather than one invariant -- a row
may be `verified` with an empty `identity_source`. All three are resolution's to settle, and
`CPM-IDENTITY-S02` is where they land.
