---
title: 'CPM-IDENTITY-S02: Resolution that records where it came from'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '42448e6fb700e53aefb5bf48e5477259733c6f3d'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s01-package-identity-model.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s07-watchlist-inventory-source.md
warnings: ['oversized']
deferred:
  - summary: >-
      `core.outcomes.aggregate` cannot rank any value `outcome_type` composes, so the first caller
      to aggregate a mapping outcome raises -- a gap in `CPM-AD-5` rather than in this story.
    evidence: |-
      `PRECEDENCE` orders the four sentinels plus `ok`. `outcome_type` composes the sentinels with
      the determinate members it is given and never includes `ok`, so `MappingOutcome`'s
      `established` -- and the determinate value of every type that factory can produce -- appears
      in no precedence order. `aggregate` refuses an unrankable value, so it raises on any
      composed vocabulary. Nothing in this story aggregates mapping outcomes, and this is the
      repository's first production `outcome_type` caller, which is why the gap surfaces now. The
      fix belongs to `core`: either `PRECEDENCE` gains a rule for where a composed determinate
      value sits, or `aggregate` learns to rank one. The story that first needs to aggregate a
      composed vocabulary is the one that has to settle it.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/outcomes.py -- PRECEDENCE, aggregate
    severity: medium
  - summary: >-
      `record_resolution` reads the package and then writes it with no row lock, so two resolvers
      recording against one package concurrently can both pass the `verified` check.
    evidence: |-
      `_package_at` is a check-then-act: it reads the row, `record_resolution` decides against the
      confidence it found, and then writes. `select_for_update` is not used. The new partial unique
      constraint closes the concurrent-*creation* race, which is what it was added for, but the
      update path has no equivalent. Nothing runs two resolvers today -- there is no resolver at
      all, and `CPM-EP-CURRENCY`'s collectors are what will first call this door -- so the race has
      no way to happen yet. It becomes real the moment two collectors record against one package in
      parallel, and the fix (locking the package row for the duration of the caller's transaction)
      belongs with the story that first runs them concurrently, because it is that story that
      decides the transaction shape.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/services.py -- _package_at
    severity: medium
  - summary: >-
      The create branch of a derived-status column's write is invisible to the audit that exists to
      find such writes.
    evidence: |-
      `tests/unit/django_apps/test_derived_status_writability_audit.py` scans source text for
      assignments to a derived-status attribute, and now records an exemption for
      `mapping.outcome = ...` in `identity/services.py`. The *creating* write of the same column
      goes through `get_or_create(defaults={"outcome": ...})`, which the AST scan does not read at
      all -- the exemption is honest about what it covers, and the gap it names is the scan's
      rather than this story's. Any future model whose derived status is only ever written through
      a `defaults` mapping would be swept by nothing. Widening the scan to read `defaults` is a
      change to a repository-wide audit and belongs with whoever owns that audit's next revision.
    location: >-
      tests/unit/django_apps/test_derived_status_writability_audit.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** Every package in the inventory sits at `unmapped` with its `canonical_name` holding
the watchlist's package name and nothing else established. `resolve_package_shell` is create-only:
it has no way to record that a mapping *was* established, no way to raise a confidence, and no way
to say that a mapping does not apply — which `CPM-FR-1` needs kept distinct from a mapping that
failed and from a successful empty result. Nothing yet stops a later resolution from lowering a
`verified` identity, and nothing enforces that the pair ingestion joins on stays unique.

**Approach:** Add the second door into `identity` — a resolution recorder that writes mappings,
provenance and confidence for a package already found by its stable key, refusing to lower a
`verified` identity and refusing to touch the key it was found by. Give each mapping its own
outcome row, so `not_applicable` is expressible without putting a derived status on the package
row. Make `(identity_source, associator_key)` unique, closing the trap the two stories before this
one recorded.

## Boundaries & Constraints

**Always:**

- Resolution finds a package by `(identity_source, associator_key)` and **never writes either
  field after creation**. That pair is what ingestion joins on; rewriting it while correcting a
  name is what creates a duplicate shell on the next sweep, and it is the trap `CPM-IDENTITY-S06`
  and `-S07` both recorded.
- **A `verified` confidence is never lowered** by any automated resolution (`CPM-FR-2`). Only an
  explicit re-resolution may, and that is `CPM-IDENTITY-S05`'s override path, not this one.
- The package row still holds only canonical name, cross-ecosystem mappings, provenance and
  confidence (`CPM-AD-1`). **No derived status reaches it** — no field named `status`, `outcome`,
  `*_status` or `*_outcome`, which `tests/unit/django_apps/test_identity_models.py` enforces
  mechanically.
- Per-mapping outcomes are a `CharField(choices=...)` built by `core.outcomes.outcome_type`, bound
  **once at module scope**, carrying all four sentinels with `core`'s own labels, non-null,
  non-blank, lowercase values, with a default among its choices (`CPM-AD-5`,
  `tests/unit/django_apps/test_outcome_field_audit.py`).
- `resolved_at` comes from the injected `Clock` (`CPM-AD-26`); no module reads a wall clock.
- Writes go through `instance.save(update_fields=[...])`, `create()` or `get_or_create()`. Never
  `objects.filter(...).update(...)`, `bulk_update`, `raw` or upsert SQL
  (`EVIDENCE.02-AUDIT-002`, `tests/unit/django_apps/test_mutation_path_audit.py`).
- The service opens no transaction of its own; the caller owns the boundary (`CPM-AD-23`), exactly
  as `resolve_package_shell` already documents.
- Every refusal is a `ResolutionError` — one flat `ValueError` subclass, in the shape the module
  already uses. `ImproperlyConfigured` is the startup stages' and the watchlist adapter's, not
  this module's.
- `pixi` is the only runner. `git add -A` before `pixi run ci`, or the gate will not see the new
  files at all.

**Block If:**

- Recording a mapping outcome cannot be done without putting a derived-status column on `Package`.
- Making `(identity_source, associator_key)` unique cannot be done without breaking a path that
  legitimately creates a package with neither set.

**Never:**

- Do **not** build a resolver. Nothing in this repository can discover a mapping: there is no PyPI
  client, no conda-forge client and no purl builder, and the collectors that will supply them are
  `CPM-EP-CURRENCY`'s, which depends on this epic. This story ships the **write path and the
  vocabulary**, exercised with mappings handed in.
- Do **not** change `resolve_package_shell`'s existing four keyword parameters or its refusals;
  ingestion calls it once per package inside a per-package transaction and its contract is settled.
- Do **not** give ingestion a second write path onto the package row (`CPM-AD-14`). The
  collector module still names no model.
- Do **not** add the override, the audit row, the permission check or the review queue. Those are
  `CPM-IDENTITY-S05` and `-S04`.
- Do **not** aggregate mapping outcomes. `core.outcomes.aggregate` ranks by `PRECEDENCE`, which
  holds no composed determinate value, so the first caller to aggregate one raises — see Design
  Notes.
- Do **not** add a dependency, a `pragma`, a coverage omit, a `pytest.skip`, or `databases=` on
  `django_db`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| A mapping is established | a shell at `unmapped`, resolution supplies a source repository, a purl and one feedstock | the values are written, the mapping outcomes read `established`, and the confidence rises to what the resolution claims | No error expected |
| A mapping cannot be established | resolution supplies nothing for the source repository | the value stays blank, its outcome reads `not_found`, and the package's confidence stays `unmapped` | No error expected |
| A mapping does not apply | a package whose type makes a PyPI identity inapplicable | that mapping's outcome reads `not_applicable`, which is neither `not_found` nor a successful empty result | No error expected |
| A successful empty result | resolution establishes that a package has zero feedstocks | the feedstock mapping's outcome reads `established` with no `Feedstock` rows, distinct from both `not_found` and `not_applicable` | No error expected |
| A verified identity is not lowered | a `verified` package, then a resolution claiming `inventory-derived` | the confidence stays `verified` and the mappings it already had are unchanged | No error expected |
| A verified identity accepts an equal claim | a `verified` package, then a resolution claiming `verified` with new mappings | the mappings are written and the confidence stays `verified` | No error expected |
| The join key is never rewritten | a resolution that corrects `canonical_name` | `identity_source` and `associator_key` are byte-identical afterwards | No error expected |
| Correction survives the next sweep | ingest, resolve to a new canonical name, ingest the same source record again | exactly one `Package` exists, it is the corrected one, and it gained a second snapshot | No error expected |
| The pair is unique | two packages created with the same `(identity_source, associator_key)` | the second is refused by the database | `IntegrityError` |
| A package with neither set | a row whose `identity_source` and `associator_key` are both blank, twice | both persist — the uniqueness rule does not apply to a package no source claims | No error expected |
| Resolution names no resolver | a recorded resolution with a blank `identity_source` | refused | `ResolutionError` |
| Resolution of an unknown package | a `(identity_source, associator_key)` pair matching no row | refused rather than silently creating one — creation is `resolve_package_shell`'s | `ResolutionError` |
| A naive instant | a resolution whose clock returns a naive datetime | refused | `ResolutionError` |

</intent-contract>

## Code Map

- `identity/services.py:182` `resolve_package_shell` — the create-only door, keyword-only, returning
  a `Package`. `:247` is the `get_or_create` on `(identity_source, associator_key)` that
  `CPM-IDENTITY-S07` moved there. `:264` `_require_source`, `:294` `_require_key`, `:338`
  `_require_name`, `:379` `_require_aware` — the `_require_*(value, *, field)` shape to copy.
  `:163` `ResolutionError`. `:133` `CANONICAL_NAME_LENGTH` (128), `:153` `ASSOCIATOR_KEY_LENGTH`
  (512), both read off their columns. The module docstring at `:9-17` names this story as the one
  that adds resolution proper "behind this same door".
- `identity/models.py:157` `Package` — 13 concrete fields; `:267` `Meta.constraints` holds only
  `canonical_name_is_present`. `:126` `IdentityConfidence`. `:296` `Feedstock` with its
  `UniqueConstraint` at `:359`. `:68-74` records per-mapping `not_applicable` as this story's.
- `core/outcomes.py:212` `outcome_type(name, determinate)` — composes `SENTINEL_MEMBERS` with the
  determinate members supplied and calls `verify_sentinels`. Every call mints a distinct class, so
  bind once at module scope. `:90` `OutcomeState`, `:148` `PRECEDENCE`, `:308` `aggregate`.
  **This story is the repository's first production caller.**
- `tests/unit/django_apps/test_outcome_field_audit.py:121` the swept names, `:255-295`
  `field_failures` — what a swept field must satisfy. `:138` `FIXTURE_OUTCOME` is the composed-type
  pattern to follow.
- `tests/unit/django_apps/test_identity_models.py:58` `EXPECTED_PACKAGE_FIELDS` (order asserted),
  `:250` the assertion, `:286` `test_neither_row_declares_a_derived_status` — the mechanical reason
  a mapping outcome cannot be a column on `Package`.
- `collectors/tasks.py:863` — ingestion's single call to `resolve_package_shell`, inside
  `transaction.atomic()` at `:862`. `:111` `PACKAGE_MODEL_NAME`, the sweep asserting the collector
  module never names `Package`. **Read-only.**
- `tests/unit/django_apps/test_mutation_path_audit.py:156` — the banned write forms.
- `tests/integration/django_apps/test_inventory_ingestion.py:375` and `:398` — the existing
  already-known and not-lowered-by-ingestion cases, which this story must keep passing.
- `identity/migrations/0001_package_identity.py` — the migration style to follow.

## Tasks & Acceptance

**Execution:**

- `identity/models.py` — add `MappingKind` (a closed `TextChoices` naming the mappings `CPM-FR-1`
  lists) and `MappingOutcome = outcome_type("MappingOutcome", [("ESTABLISHED", "established")])` at
  module scope; add `PackageMapping` (`db_table = "package_mappings"`) with a `PROTECT`-free
  `CASCADE` FK to `Package`, `kind`, `outcome`, `resolved_at`, and a
  `UniqueConstraint(fields=["package", "kind"])`; add the partial
  `UniqueConstraint(fields=["identity_source", "associator_key"], condition=~Q(associator_key=""))`
  to `Package.Meta`.
- `identity/migrations/0002_resolution.py` — the new model and the new constraint.
- `identity/services.py` — add `record_resolution(...)`: find by `(identity_source,
  associator_key)`, refuse an unknown pair, write the mappings and their outcomes, raise the
  confidence without ever lowering `verified`, never write the join key, `resolved_at` from the
  clock. Plus the `_require_*` refusals it needs.
- `tests/unit/django_apps/test_identity_models.py` — extend `EXPECTED_PACKAGE_FIELDS`' companions
  for the new model, and assert `PackageMapping`'s outcome column satisfies the sentinel rules.
- `tests/unit/django_apps/test_identity_services.py` — the new refusals, no database.
- `tests/integration/django_apps/test_identity_resolution.py` — new; every matrix row that needs a
  table, including the ingest-resolve-ingest regression and the uniqueness cases.

**Acceptance Criteria:**

1. Given a resolution recorded against a shell, when the package is read back, then it carries the
   mappings supplied, an identity source, an associator key and a confidence — and `resolved_at` is
   the instant the injected clock returned.
2. Given a `verified` package, when any automated resolution claiming a lower confidence is
   recorded, then the stored confidence is still `verified` and no mapping it already held was
   overwritten.
3. Given any recorded resolution, when the row is compared before and after, then `identity_source`
   and `associator_key` are unchanged — asserted directly, because this is the invariant the
   duplicate-shell trap turns on.
4. Given `PackageMapping.outcome`, when the derived-status audit sweeps it, then it offers all four
   `OutcomeState` sentinels with `core`'s own labels plus at least one determinate value, is
   non-null and non-blank, and defaults to one of its own choices.
5. Given `Package`, when its concrete field names are collected, then the set is unchanged from
   `CPM-IDENTITY-S01`'s — this story adds a table, not a column.
6. Given two packages with the same non-blank `(identity_source, associator_key)`, when the second
   is written, then the database refuses it; and given two packages with both fields blank, then
   both persist.

## Spec Change Log

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 26: (high 4, medium 15, low 7)
- defer: 3: (high 0, medium 2, low 1)
- reject: 6: (high 0, medium 1, low 5)
- addressed_findings:
  - `[high]` `[patch]` The story's most load-bearing write rule was unpinned. A reviewer deleted the
    two `established` guard lines in `_write_identity` — so every mapped field is written
    unconditionally — and the whole suite still passed. With the guard gone a previously established
    URL or purl is overwritten with blank while the outcome row records `not_found` beside it: the
    "records a guess" state `CPM-FR-1` forbids. Now pinned by a case running two resolutions in the
    order that matters, establish then `not_found`, asserting the value survives *and* the outcome
    changed. Re-running the mutation now fails three cases.
  - `[high]` `[patch]` The inverse hole was real code, not just untested: an `established` outcome
    carrying no value was accepted and wrote blanks, indistinguishable in the columns from
    `not_found` — the fold `PackageMapping` exists to prevent. `_require_established_mappings_carry_a_value`
    refuses it, with the feedstock kind as the single argued exception, since `CPM-FR-1`'s "zero or
    more" makes an empty establishment there the successful empty result.
  - `[high]` `[patch]` A correction onto a name another package already holds escaped as a raw
    `IntegrityError`, contradicting the module's own contract that every refusal is a
    `ResolutionError` raised before the first write. Two shells converging on one upstream package
    is exactly what correction is for. Refused now, with a case for the collision and a case
    proving that correcting onto the row's own name is not one.
  - `[high]` `[patch]` The `verified` guard discarded the entire resolution — mappings, feedstocks
    and outcome rows — where `CPM-FR-2` protects only the confidence. As written, no lower-confidence
    collector could ever record a newly found feedstock for a verified package, which would have
    locked out every `CPM-EP-CURRENCY` collector that will call this door. The findings are now
    recorded and only the confidence claim and the corrected name are held back, with the holding
    made observable through a returned result rather than a silent no-op.
  - `[medium]` `[patch]` Nothing correlated the claimed confidence with the outcomes: a resolution
    could claim `verified` while every mapping read `not_found`, and a test encoded that as
    expected. `CPM-AD-4` gates every outward claim on confidence. A confidence above `unmapped` now
    requires at least one mapping established with a value; seven tests that encoded the old
    permissiveness were rewritten to establish something real.
  - `[medium]` `[patch]` The additive-feedstock invariant `CPM-AD-14` depends on was enforced by
    nothing executable — a reviewer's loop-form prune of unnamed feedstocks passed the whole suite,
    because the mutation-path audit catches the queryset form and not the loop. Pinned by a case
    where two resolutions name different feedstocks and both survive.
  - `[medium]` `[patch]` `PackageMapping.resolved_at` went stale unnoticed: dropping its update
    passed the suite, leaving every row dated to the resolution that created it while its outcome
    reflected a later one.
  - `[medium]` `[patch]` `test_an_existing_identity_is_not_lowered_by_ingestion` was vacuous, and
    this change had re-affirmed it with a docstring claiming the run finalizes `partial` when it
    finalizes `FAILED`. Its fixture row carried a blank `associator_key`, so the sweep never found
    it and the assertions passed because nothing was written. The fixture now carries the matching
    pair and the case asserts `SUCCEEDED`.
  - `[medium]` `[patch]` Twelve more: all seven caller-supplied columns bounded against the widths
    their own columns declare, closing the SQLite-truncates/PostgreSQL-refuses parity gap the module
    argues about but had applied to only three; purl and CPE elements shape-checked and stored in a
    form that matches what a re-read returns; duplicate feedstock names within one resolution
    refused rather than last-wins; the non-`verified` downgrade decided and pinned;
    `MultipleObjectsReturned` translated to a `ResolutionError`; the kind vocabulary derived from
    `MappingKind` rather than from the field table; the outcome default taken from the composed type
    rather than reaching across to `OutcomeState`; a `RunPython` pre-check ahead of the
    `AddConstraint` so an existing database holding duplicates fails legibly; the package's
    `resolved_at` advanced only when the identity actually changed; `PackageMapping` returned to the
    derived-status name sweep with only `outcome` exempted; `CASCADE` proved by deleting a real row;
    and a field docstring rewritten to argue from what is true.
  - `[low]` `[patch]` `display_name` proved untouched, feedstock names normalised in one place
    rather than two, and a rollback case proving the caller owns the transaction boundary the
    module's contract depends on.

## Design Notes

**Why a mapping outcome cannot be a column on `Package`, and where it goes instead.** `CPM-AD-1`
says the package row holds no derived status, and `tests/unit/django_apps/test_identity_models.py:286`
enforces it by name: nothing on `Package` may be called `status`, `outcome`, `*_status` or
`*_outcome`. `CPM-FR-1` nonetheless needs a mapping that does not apply to be distinguishable from
one that failed and from a successful empty result — three states, which no nullable value column
can carry. So the outcome moves to its own row: `PackageMapping`, one per `(package, kind)`,
carrying the outcome and nothing the package row already holds. The established *values* stay on
`Package`, because they are cross-ecosystem mappings and `CPM-AD-1` puts those there. What the
child row adds is why a value is absent — which is precisely the distinction `CPM-FR-6` exists for,
and the shape the non-Python conda phase will need.

**The repository's first production `outcome_type`.** Nothing in `src/` has composed an outcome
vocabulary yet; the only callers are test fixtures. `MappingOutcome` is bound once at module scope,
because every call mints a distinct class and two calls would produce two types that compare
unequal. The audit reads the choices off the field and checks the sentinel labels against
`OutcomeState`'s own, which is how it proves the vocabulary was composed rather than hand-written —
so hand-writing the choices would fail even if every value matched.

**`aggregate` cannot be called on this vocabulary, and that is a `core` gap rather than this
story's.** `core.outcomes.PRECEDENCE` ranks the four sentinels plus `ok`; a composed type's
determinate value — here `established` — appears in no precedence order, so `aggregate` raises on
it. That is true of *every* type `outcome_type` can produce, which makes it an unresolved seam in
`CPM-AD-5` rather than a defect here. Nothing in this story aggregates mapping outcomes; the story
that first needs to will have to settle where a determinate value ranks. Recorded as deferred.

**The uniqueness constraint is partial, and it has to be.** `identity_source` and `associator_key`
are both `blank=True, default=""` on `Package`, so an unconditional
`UniqueConstraint(fields=["identity_source", "associator_key"])` would make `("", "")` a single
permissible row for the whole product — and `CPM-IDENTITY-S05`'s override path, or any future
creator that is not ingestion, would collide with it for no reason. The constraint therefore
carries `condition=~Q(associator_key="")`: a package some source claims is unique to that source's
key, and a package no source claims is not constrained at all. Both backends enforce a partial
unique index identically here, since no NULLs are involved.

**What this story closes, and what it does not.** `CPM-IDENTITY-S06`'s review recorded five things
needed to close the duplicate-shell trap. `CPM-IDENTITY-S07` already delivered the first — the
lookup moved to `(identity_source, associator_key)`. This story delivers the second, third and
fifth: the uniqueness constraint, the invariant that resolution never touches those two fields
while correcting a name, and the ingest-resolve-ingest regression test. The fourth — holding
`CPM-IDENTITY-S05`'s audited override to the same invariant — belongs to that story, because the
override path does not exist yet.

**Resolution takes its mappings; it does not find them.** There is no PyPI client, no conda-forge
client and no purl builder anywhere in `src/`, and the collectors that will supply them belong to
`CPM-EP-CURRENCY`, which depends on this epic. So `record_resolution` is a *recorder*: it is handed
what a resolver concluded and is responsible for writing it correctly, refusing what it must, and
preserving what it may not lower. That is the half of `CPM-FR-1` and `CPM-FR-2` that can be built
and proven now, and it is the half every later collector will call.

## Verification

**Commands:**

- `pixi run test` -- expected: exits 0.
- `pixi run test-integration` -- expected: exits 0, no new skips.
- `pixi run ci` -- expected: exits 0, coverage at or above 90%. Run it **after** `git add -A`, or
  it will not see the new files.
- `pixi run gate-postgres` -- expected: exits 0 with nothing newly skipped. The partial unique
  constraint and the FK are database-enforced, so `postgres:17` is where they are proven.

## Auto Run Result

Status: done

**What was implemented.** The second door into `identity`. `resolve_package_shell` creates a shell
and never updates it; `record_resolution` is what writes mappings, provenance and confidence onto a
package already found by its stable key. Per-mapping outcomes move to their own table, so
`not_applicable` is expressible without putting a derived status on the package row, and
`(identity_source, associator_key)` becomes unique — closing the duplicate-shell trap the two
stories before this one recorded.

**Files changed.**

- `identity/models.py` — `MappingKind`, `MappingOutcome` (the repository's first production
  `outcome_type` call, bound once at module scope), `MAPPED_FIELDS`, the `PackageMapping` model, and
  the partial `UniqueConstraint` on `(identity_source, associator_key)` scoped to packages a source
  actually claims.
- `identity/services.py` — `record_resolution`, the `Resolution` and `FeedstockMapping` value types,
  and the refusals that make the door's contract true.
- `identity/migrations/0002_resolution.py` — the new table and the new constraint, with a
  `RunPython` pre-check so an existing database holding duplicate pairs fails legibly rather than
  part-way.
- `tests/unit/django_apps/test_identity_models.py`, `test_identity_services.py`,
  `test_derived_status_writability_audit.py` — the vocabularies, the refusals, and one recorded
  audit exemption.
- `tests/integration/django_apps/test_identity_resolution.py` — new; every matrix row that needs a
  table, including the ingest-resolve-ingest regression.
- `tests/integration/django_apps/test_inventory_ingestion.py` — a vacuous case repaired.

**Review findings:** 26 patched (4 high, 15 medium, 7 low), 3 deferred, 6 rejected. Four review
layers ran in parallel over the full 3,127-line diff.

**Follow-up review recommended:** true. Four high-severity patches.

**The review stopped arguing and started mutating, and that is what found the real defects.** Three
separate mutations passed the entire suite: deleting the `established` guard so every mapped field
is written unconditionally; pruning feedstocks a later resolution stops naming; and dropping the
`resolved_at` update on mapping rows. The first is the story's most load-bearing rule — with the
guard gone, a previously established URL is overwritten with blank while the outcome row records
`not_found` beside it, which is precisely the "records a guess" state `CPM-FR-1` forbids, and no
test anywhere ran two resolutions in that order. All three now fail under the same mutation, and I
re-ran the first myself to confirm rather than take it on report.

**The finding with the widest reach was a scope error.** The `verified` guard discarded the entire
resolution — mappings, feedstocks, outcome rows — where `CPM-FR-2` protects only the confidence.
Under that reading, once a package reached `verified`, no lower-confidence collector could ever
record a newly discovered feedstock, which would have locked out every `CPM-EP-CURRENCY` collector
that will call this door. The findings are recorded now; only the confidence claim and the corrected
name are held back, and the holding is observable rather than a silent no-op.

**Verification.** `pixi run ci` exits 0 — 3832 passed, 2 pre-existing skips, coverage 98.37%, with
`identity/models.py` and `identity/services.py` both at 100%. `pixi run gate-postgres` exits 0
against a throwaway `postgres:17`, where the partial unique index and the FK are actually enforced.
All 13 I/O matrix rows have a covering test that ran and passed. The gate was run after staging, so
it saw every new file.

**Residual risks.** Three `deferred` entries. `core.outcomes.aggregate` cannot rank any value
`outcome_type` composes — `PRECEDENCE` orders the sentinels plus `ok`, and a composed vocabulary
never has `ok` — so the first caller to aggregate a mapping outcome raises. That is a gap in
`CPM-AD-5` rather than in this story, and it surfaces now because this is the first production
caller of that factory. `record_resolution` also reads a package and writes it without a row lock;
the new constraint closes the concurrent-creation race but not the update path, and nothing runs two
resolvers today because no resolver exists yet.
