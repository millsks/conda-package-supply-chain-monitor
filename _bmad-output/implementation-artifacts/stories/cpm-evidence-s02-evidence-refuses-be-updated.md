---
title: 'CPM-EVIDENCE-S02: Evidence that refuses to be updated'
type: 'feature'
created: '2026-09-04'
status: 'in-review'
baseline_revision: '0a6097cb2bbc20eab20973955c01e7eee729c36f'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
warnings: ['oversized']
deferred: []
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
