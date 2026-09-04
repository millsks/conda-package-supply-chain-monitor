---
title: 'CPM-EVIDENCE-S02: Evidence that refuses to be updated'
type: 'feature'
created: '2026-09-04'
status: 'done'
baseline_revision: '0a6097cb2bbc20eab20973955c01e7eee729c36f'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
warnings: ['oversized']
deferred:
  - summary: >-
      A unique index added by a migration's `RunSQL` or `AddConstraint` is invisible to the
      Meta-level constraint audit.
    evidence: |-
      `EVIDENCE.02-AUDIT-003` reads `Meta.constraints`, `unique_together` and field flags from
      the model registry, so a constraint created in SQL by a migration never appears. Closing
      it needs an integration sweep reading `connection.introspection.get_constraints` for
      every evidence model's real table, and no evidence table exists yet.
    location: >-
      tests/unit/django_apps/test_evidence_constraint_audit.py
    severity: medium
  - summary: >-
      The append-only base declares no index on `observed_at` and no `get_latest_by`.
    evidence: |-
      Several docstrings argue an index on `observed_at` is what makes a freshness query
      answerable at all, and every collector will otherwise have to remember it independently.
      Declaring it on the abstract base is a schema contract binding every future evidence
      table, which belongs with the first collector rather than with the base.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** Nothing stops an observation being overwritten. Once a collector updates an
evidence row instead of inserting one, what the system knew at a point in time is gone and
cannot be reconstructed — `R-06`, and the failure `CPM-FR-36` exists to prevent. A `save()`
guard alone is not enough: `queryset.update()`, `bulk_update()` and raw SQL all go around it.

**Approach:** An abstract append-only base in `core` whose `save()` refuses once the row
exists and whose manager offers no mutating path, plus three registry- and source-level
audits closing the bypasses `save()` cannot see — the mutation paths, the inheritance rule,
and unique constraints that would silently make re-observation impossible.

## Boundaries & Constraints

**Always:**
- Re-observation inserts. A second observation of an unchanged fact is a new row with its own `observed_at`, never an update and never a no-op.
- `observed_at` is set by the writer from an injected clock (`CPM-AD-26`). It has no field default and no `auto_now_add` — `EVIDENCE.01-AUDIT-002` already fails both, so the base model cannot take the shortcut.
- Refusals raise. Never a warning, never log-and-continue (inherited `CG-3`).
- Audits are AST or registry sweeps in the shape the repository already uses — `tests/source_scan.py`, `tests/unit/django_apps/test_clock_audit.py`, `tests/unit/django_apps/test_outcome_field_audit.py`. Every sweep carries an anti-vacuity guard, and a pre-existing violation is grandfathered only as a counted `RECORDED_EXEMPTIONS` entry naming file and count.
- The mutation-path scan must not fire on `dict.update()`, which is ordinary Python. Distinguish by receiver shape, and state in the module what it cannot resolve.
- `structlog` only, no `print`, no stdlib `logging`. Full type hints, Google docstrings, line length 120.

**Block If:**
- Enforcing the mutation-path audit would require editing inherited `src/config/` or `src/django_service/` behaviour rather than recording a counted exemption.
- The append-only guarantee cannot be expressed without a concrete evidence table this story is not scoped to create.

**Never:**
- Do not create the `evidence` app or any concrete evidence model. Each collector owns its own table; the first arrives with `CPM-EP-CURRENCY`. Prove the base against models built and discarded inside the tests.
- Do not create the run-ledger models. `CPM-AD-2` exempts `collection_runs` and `policy_runs` explicitly — they are mutable, they are not evidence, and they are `CPM-EVIDENCE-S03`'s.
- Do not implement observation windows, skip semantics or idempotency. `CPM-AD-7` puts those in the run ledger, not here.
- Do not add a status field, a collector, a queue, or a settings key.
- Do not weaken `EVIDENCE.01-AUDIT-002` to let the base model default `observed_at`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First save | an unsaved instance | inserted; `pk` assigned | No error expected |
| Second save | an instance whose `pk` is set | refused (`EVIDENCE.02-UNIT-001`) | Raises, naming the model and pk |
| Forced update | `save(force_update=True)` | refused | Raises |
| Loaded then saved | a row fetched from the database, then saved | refused — this is the accidental path, not a constructed one | Raises |
| Instance delete | `instance.delete()` | refused | Raises |
| Manager mutation | `Model.objects.update(...)`, `.bulk_update(...)`, `.delete()` | not available, or refuses | Raises `AttributeError` or the base's own error; whichever, it is tested |
| Insert path preserved | `bulk_create`, `create` | permitted — an insert is not a mutation | No error expected |
| Re-observation | the same fact observed twice through the writer | two rows, second with a later `observed_at` (`EVIDENCE.02-INT-001`) | No error expected |
| Clock supplies the instant | a fixed clock | `observed_at` equals the clock's instant; no wall-clock read anywhere in the path | No error expected |
| Missing `observed_at` | a write that supplies none | refused rather than silently defaulted | Raises |
| Inheritance audit | every concrete evidence model in the registry | inherits the append-only base (`EVIDENCE.02-AUDIT-001`) | Assertion names the model |
| Inheritance anti-vacuity | no evidence model exists yet | the detector is proven against fixture models, conforming and not | Test fails if the detector matches nothing |
| Unique-constraint audit | an evidence model declaring `unique=True`, `unique_together` or a `UniqueConstraint` that spans the observed fact | rejected (`EVIDENCE.02-AUDIT-003`) | Assertion names the constraint |
| Mutation-path audit | any `.objects.update(...)`, `.bulk_update(...)`, `.raw(...)` or cursor `UPDATE`/`DELETE` under the product's own source | audit fails, naming the module (`EVIDENCE.02-AUDIT-002`) | Assertion names the offending path |
| Ordinary dict update | `some_dict.update({...})` | not an offence | No error expected |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/` -- `apps.py`, `clock.py`, `outcomes.py`, `roles.py`, `migrations/0001_provision_role_groups.py`. **No `models.py` yet; the base lands here.** The app has a migrations package already, so a migration for an abstract model is not needed — abstract models create no table.
- `src/django_apps/.../core/clock.py` -- `Clock`, `SystemClock`, `FixedClock`. This story is the clock's first real consumer: `observed_at` comes from an injected `Clock`, which is what makes `EVIDENCE.02-INT-001` assertable rather than flaky. Read-only.
- `src/django_apps/.../core/outcomes.py` -- the shape to mirror for a `core` declaration module, and the source of the "declare once, enforce mechanically" convention. Read-only.
- `tests/source_scan.py` -- `REPO_ROOT`, `project_files`, `parse`, `dotted_name`, the unreadable/symlink sets. The mutation-path audit builds on this; do not write a fourth walk.
- `tests/unit/django_apps/test_clock_audit.py` -- the closest model for the new mutation-path audit: canonical-name resolution through `Import`/`ImportFrom` so an alias cannot evade it, `RECORDED_EXEMPTIONS` as a counted table, a reported form that distinguishes shapes, and detector fixtures parametrized as source strings. Reuse the structure, including its negative controls.
- `tests/unit/django_apps/test_outcome_field_audit.py` -- the model-registry sweep to mirror for `EVIDENCE.02-AUDIT-001` and `-003`: scope to apps whose package lives under `src/`, guard the third-party exclusion by asserting the app is installed first, and carry `isolate_apps` fixture models as the anti-vacuity half.
- `tests/integration/django_apps/` -- exists, holds `test_role_groups.py`. Where `EVIDENCE.02-INT-001` goes; integration tests are marked by directory.
- `tests/clocks.py` -- `FIXED_INSTANT`, shared across test modules. Extend rather than re-declare.
- `src/django_service/users/models.py` -- the repository's existing model module, for field-declaration and `Meta` conventions. Read-only.

## Tasks & Acceptance

**Execution:**

- `src/django_apps/conda_package_supply_chain_monitor/core/models.py` -- new. The abstract append-only base: `observed_at` as a non-null `DateTimeField` with no default and no `auto_now_add`; a `save()` that refuses when the row already exists (including `force_update`, and including an instance loaded from the database) and refuses a missing `observed_at`; an instance `delete()` that refuses; and a manager whose queryset offers no `update`, `bulk_update` or `delete` while leaving `create` and `bulk_create` intact, because an insert is not a mutation. A dedicated error type, raised with the model and pk. `Meta.abstract = True`, so no migration is produced.
- `tests/unit/django_apps/test_append_only_model.py` -- new. Matrix rows 1-7 and 10, against concrete subclasses built and discarded with `isolate_apps`. `EVIDENCE.02-UNIT-001` is the second-save case.
- `tests/unit/django_apps/test_evidence_inheritance_audit.py` -- new. `EVIDENCE.02-AUDIT-001`: sweep the model registry for concrete evidence models and assert each inherits the base. Define "evidence model" as the union of two independent marks — a model whose app label is `evidence`, and a model inheriting the base — so neither definition can be gamed by moving a model or dropping a base. Both sets are empty today, so the anti-vacuity guard is the load-bearing half: prove the detector against conforming and non-conforming fixture models.
- `tests/unit/django_apps/test_evidence_constraint_audit.py` -- new. `EVIDENCE.02-AUDIT-003`: for every evidence model, reject `unique=True` on a non-primary-key field, `unique_together`, and any `UniqueConstraint` — each would suppress the insert that re-observation depends on. Same anti-vacuity treatment.
- `tests/unit/django_apps/test_mutation_path_audit.py` -- new. `EVIDENCE.02-AUDIT-002`: AST sweep over the product's own source for the bypasses `save()` cannot catch — manager/queryset `update` and `bulk_update`, queryset `delete`, `.raw(...)`, and cursor execution of `UPDATE`/`DELETE`. Resolve names through imports as the clock audit does. **`dict.update()` must not fire**: distinguish by receiver shape, and state in the module docstring which shapes the scan cannot resolve, as the ordering audit states its own holes. Counted exemptions for anything pre-existing.
- `tests/integration/django_apps/test_append_only_evidence.py` -- new. `EVIDENCE.02-INT-001`: with a real table created for a fixture model, write the same fact twice through a `FixedClock` advanced between writes, and assert two rows with distinct `observed_at`; then assert the database rejects nothing and no unique constraint exists on the table.
- `tests/clocks.py` -- extend with whatever a second, later instant needs, rather than declaring one inline.

**Acceptance Criteria:**

- Given an abstract append-only base model in `core`, when `save()` is called on an instance whose primary key is already set, then it raises rather than updating, and the manager exposes no `update()` or `delete()` path.
- Given an unchanged fact is observed again, when the collector writes it, then a new row is inserted with a new `observed_at`, and no evidence table carries a unique constraint that would suppress that insert.
- Given any evidence model in the project, when the test suite runs, then a test asserts it inherits the append-only base.
- Given an evidence table, when the audit runs, then it fails on any `queryset.update()`, `bulk_update()` or raw SQL write against that table.
- Given the whole change, when `pixi run ci` runs, then it exits 0 with coverage at or above the 90% floor, and `makemigrations --check` reports no missing migration.

## Spec Change Log

## Review Triage Log

### 2026-09-04 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 36: (high 5, medium 21, low 10)
- defer: 2: (high 0, medium 1, low 1)
- reject: 0
- addressed_findings:
  - `[high]` `[patch]` `Model._base_manager` bypassed the guard entirely — Django builds it itself
    when `Meta.base_manager_name` is unset, so it was a plain `Manager` returning a plain `QuerySet`,
    and `_base_manager.get_queryset().update(...)` compiled and executed an `UPDATE`. It is the
    spelling a developer reaches for *because* `objects.update()` refuses. Closed by
    `base_manager_name = "objects"`, with the spelling added to the refusal parametrize.
  - `[high]` `[patch]` Cascade deletion removed evidence past both refusals: Django's `Collector`
    issues `DELETE` through `sql.DeleteQuery.delete_batch()`, consulting neither `Model.delete()`
    nor `QuerySet.delete()`. The registry sweep now requires every evidence foreign key to use
    `PROTECT`, `RESTRICT` or `DO_NOTHING`, with fixtures both ways.
  - `[high]` `[patch]` `bulk_create(update_conflicts=True)` compiles to `ON CONFLICT DO UPDATE` — an
    overwrite through the insert path the spec deliberately left open, because "an insert is not a
    mutation" holds only for the plain form. `ignore_conflicts=True` silently dropped an observation
    instead. Both flags now refuse; the plain path still delegates to Django.
  - `[high]` `[patch]` Raw SQL reached the same upsert: `INSERT` was allow-listed, so
    `INSERT ... ON CONFLICT DO UPDATE` passed. `UPSERT`, `MERGE` and `REPLACE` are now writing verbs,
    `WITH`/`BEGIN`/`START` bodies are searched for an embedded write, and comments are stripped
    before the verb is read. `ON CONFLICT DO NOTHING` and plain `INSERT` stay permitted.
  - `[high]` `[patch]` A concrete evidence model re-declaring `objects = models.Manager()`, or setting
    `Meta.default_manager_name`/`base_manager_name`, reopened every path while passing both audits —
    the failure the diff's own docstring called "the half a subclass can silently lose". The
    inheritance sweep now asserts both the default and base managers are append-only.
  - `[medium]` `[patch]` Twenty-one further fixes, the substantive ones being: `leading_keyword` took
    the first constant anywhere in an f-string rather than the leading segment, so
    `f"{verb} FROM evidence"` resolved to `"FROM"` and escaped both branches; `BEGIN; DELETE ...`
    resolved to `"BEGIN;"` because punctuation walked the write past the check; every previously dead
    ban-table entry (`_base_manager`, `TRUNCATE`, `adelete`, `abulk_update`, the `ast.Import`
    connection source, `unique_for_month`/`unique_for_year`) gained a fixture and is now load-bearing;
    `string_constants` walks the whole tree rather than `tree.body`; `executescript` and `callproc`
    are handled, the latter separately because its argument is a procedure name; the async refusals
    are driven rather than asserted in prose; the inheritance union gained an `observed_at` third mark
    so a collector's own-app model that forgot the base is no longer invisible; a model-level
    `not_evidence` escape was added so `CPM-EVIDENCE-S03`'s mutable run ledgers do not need file-level
    exemptions for correct code; `get_queryset` passes `using`/`hints`; the integration fixture's table
    was renamed so its stale-table drop can never land on a migrated `core_observation`; and
    `django_db_blocker` is correctly typed, removing two `type: ignore` under strict mypy.
  - `[low]` `[patch]` Ten cleanups, including the scan's asymmetric and false-positive limits being
    documented and pinned, `RECORDED_EXEMPTIONS` annotated `Final` in both audits, and the fixture
    constants single-sourced across four modules.

## Design Notes

**`observed_at` has no default, and that is forced rather than chosen.** The obvious Django
spellings — `default=timezone.now`, `auto_now_add=True` — are both now failures of
`EVIDENCE.01-AUDIT-002`. That is the audit working: `CPM-AD-26` wants the instant injected so
freshness and window tests are writable at all, and a field default reads the process wall
clock. The writer supplies the instant from its clock; `save()` refuses a row that has none,
so the omission is loud rather than a silent epoch-zero row.

**Why "evidence model" is defined twice.** The audits need a subject, and today there are no
evidence models at all. A definition of "inherits the base" alone makes `EVIDENCE.02-AUDIT-001`
circular — every model inheriting the base inherits the base. A definition of "lives in the
`evidence` app" alone is escapable by putting a table elsewhere. The union is neither: a model
in the `evidence` app that does not inherit the base fails, and a model inheriting the base is
held to the constraint and mutation rules wherever it lives.

**The mutation-path audit bans forms, not tables.** "Against an evidence table" is not
statically resolvable — a queryset bound to a local, passed through a helper, or built by a
manager method defeats any AST-level attempt to prove what model it belongs to. So the scan
bans the bypass forms across the product's own source and licenses exceptions by count, which
is the same trade `EVIDENCE.01-AUDIT-002` makes for the clock. Say so in the module: the
guarantee is "no new bypass-shaped write", not "no bypass".

**`dict.update()` is the false positive to design against.** It is ordinary Python and will
appear. Keying on a receiver chain containing `objects` or `_default_manager` is the cheap
discriminator; whatever is chosen, a fixture asserting `some_dict.update({...})` is not an
offence belongs in the parametrized set, as `auto-now-off` does in the clock audit.

## Verification

**Commands:**
- `pixi run test` -- expected: the new unit tests pass; run after each file rather than once at the end.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: clean under strict mypy.
- `pixi run test-integration` -- expected: the new integration test passes and no existing test regresses.
- `pixi run python manage.py makemigrations --check --dry-run` -- expected: "No changes detected". The base is abstract, so it creates no table; a migration appearing means a concrete model was added by mistake.
- `pixi run ci` -- expected: exit 0, coverage at or above 90.

**Manual checks:**
- Confirm each new audit fails when its guard is removed, and fails *only* its own audit: add a concrete model in an `evidence` app label that does not inherit the base; add a `UniqueConstraint` to a fixture evidence model; add a `Thing.objects.update(...)` and a `cursor.execute("UPDATE ...")` to a `django_apps` module; and confirm a plain `dict.update()` added alongside them does not fire.

## Auto Run Result

Status: done

### Implemented change

An observation can no longer be overwritten. `core` gains an abstract append-only base whose
`save()` refuses once the row exists and whose manager offers no mutating path, so
re-observing an unchanged fact inserts a new row with its own `observed_at` rather than
destroying what the system knew at a point in time. Because a `save()` guard alone is not
enough — `queryset.update()`, `bulk_update()` and raw SQL all go around it — three
registry- and source-level audits close the bypasses it cannot see. This is `R-06`'s
mitigation, landed before any evidence table exists, so no collector can inherit the mistake.

### Files changed

- `src/django_apps/conda_package_supply_chain_monitor/core/models.py` — new. `AppendOnlyModel`,
  `AppendOnlyManager`, `AppendOnlyQuerySet`, `AppendOnlyError`. Abstract, so no table and no migration.
- `tests/model_registry.py`, `tests/unit/test_model_registry.py` — new shared registry-scope helper
  and its guards.
- `tests/unit/django_apps/test_append_only_model.py` — the runtime guarantees, DB-free.
- `tests/unit/django_apps/test_evidence_inheritance_audit.py` — `EVIDENCE.02-AUDIT-001`.
- `tests/unit/django_apps/test_evidence_constraint_audit.py` — `EVIDENCE.02-AUDIT-003`.
- `tests/unit/django_apps/test_mutation_path_audit.py` — `EVIDENCE.02-AUDIT-002`.
- `tests/integration/django_apps/test_append_only_evidence.py` — `EVIDENCE.02-INT-001`.
- `tests/clocks.py`, `tests/unit/django_apps/test_clock.py`, `test_clock_audit.py`,
  `test_outcome_field_audit.py` — shared instants, and the scope predicate single-sourced.

### Review findings breakdown

- Patches applied: 36 (high 5, medium 21, low 10).
- Items deferred: 2 (the migration-level unique-index sweep; `Meta.indexes`/`get_latest_by` on the base).
- Items rejected: 0.

### Follow-up review recommendation

`true`. Patched findings by severity: high 5, medium 21, low 10. Five high-severity patches trip the
rule on their own; the weighted score is `3 × 21 + 1 × 10 = 73`.

### Verification performed

- `pixi run ci` — exit 0 at the merged tree. 2340 tests, coverage 97.27%; `core/models.py` at 100%.
- `pixi run python manage.py makemigrations --check --dry-run` — "No changes detected". The base is
  abstract, so a migration appearing would mean a concrete model crept in.
- Audits probed independently of the implementing agent, each introduced then reverted with
  `git diff --stat src/` empty afterwards: a suppressing `unique_together` fails only the constraint
  audit; an `objects.update(...)` plus a raw `cursor.execute("UPDATE ...")` fails only the mutation
  audit; and a bare `dict.update()` alongside them does not fire.
- The clean-merge claim was checked three ways before the branch landed: zero file overlap with main's
  intervening commits, a conflict-free `git merge-tree`, and GitHub reporting `MERGEABLE`.

### Process note

This story did not run start-to-finish in one session. The implementation agent was stopped mid-way
through its review-patch pass and left no completion record, so the tree was inspected directly and a
second agent finished the remainder against a verified done/not-done split. Separately, a peer Claude
session was working in the same working directory and on the same branch; it committed the work as
`adc9616`, opened PR #15 and merged it as `4febd58`. Nothing was lost and the merge was clean, but
the collision is the reason this bookkeeping landed as a follow-up rather than with the code.

### Residual risks

- **Nothing inherits the base yet.** Both registry sweeps pass over an empty set, so the detectors are
  measured against fixture models rather than the repository. The first real evidence table is where
  these contracts meet reality.
- **The mutation audit bans forms, not tables.** "Against an evidence table" is not statically
  resolvable, so the scan bans the bypass shapes across the product's source and licenses exceptions by
  count. It cannot see a queryset bound to a local — `prune_expired_state.py` does exactly that — and
  `objects` matches any attribute so named, so an S3 `bucket.objects.delete()` would be reported. Both
  limits are documented and pinned. The guarantee is "no new bypass-shaped write", not "no bypass".
- **`CPM-EVIDENCE-S03` must use the `not_evidence` escape.** `CPM-AD-2` makes run ledgers mutable, and
  the audit bans mutation on every model; the model-level declaration exists so that correct code does
  not accumulate file-level exemptions.
- **Raw SQL coverage is verb-based.** `ON CONFLICT DO UPDATE`, `MERGE`, `REPLACE` and CTE bodies are
  closed; anything assembled dynamically past the leading segment is reported as unresolved rather
  than parsed.
