---
title: 'CPM-EVIDENCE-S03: A run ledger that survives a killed worker'
type: 'feature'
created: '2026-09-04'
status: 'done'
baseline_revision: '274d5513edb1a3dc4e20ea2ee4b88a316f489d02'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
warnings: ['oversized']
deferred:
  - summary: >-
      The "committed before the outbound call" half of the ordering guarantee is not
      observable by any test that runs.
    evidence: |-
      Every case is `@pytest.mark.django_db` without `transaction=True`, so the ledger insert
      runs inside pytest-django's atomic block and is rolled back. A read on the same
      connection cannot distinguish a committed row from an uncommitted one, so wrapping
      `_recorded`'s body in `transaction.atomic()` leaves the whole suite green while the
      killed-worker row is lost in production. No test in this repository uses
      `transaction=True`; every reference to it is a comment explaining why not.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/ledger.py
    severity: medium
  - summary: >-
      `PolicyRun.evidence_cutoff` was made non-null on a reading the spec did not settle.
    evidence: |-
      The spec named the field without fixing its nullability. Non-null follows `CPM-FR-22`:
      a policy run with no stated cut-off cannot be replayed. If `CPM-EVIDENCE-S07` needs to
      open a policy run before its cut-off is known, this becomes a migration.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py
    severity: low
  - summary: >-
      `detail` is an unbounded TextField fed verbatim from exception messages.
    evidence: |-
      `_raised` writes `f"{type(error).__name__}: {error}"` for anything leaving the body.
      Collector exceptions from HTTP clients routinely embed full request URLs, signed URLs
      or tokens, and sometimes whole response bodies, and this lands in an
      operationally-readable table with no cap and no scrub. Nothing writes to it yet -- no
      collector exists -- so the cap belongs with the first one.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py
    severity: medium
  - summary: >-
      No database constraint keeps `status` and `finished_at` consistent.
    evidence: |-
      `RunLedgerQuerySet`'s own docstring names the divergence as the hazard -- a row whose
      status was never advanced but whose `finished_at` was written is counted by one query
      and not the other -- then leaves both columns free. A CheckConstraint (`finished_at IS
      NULL` iff `status = 'running'`) would make `unfinished()` and `status` provably the
      same set rather than agreeing by convention.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py
    severity: low
  - summary: >-
      `unfinished()` filters on `finished_at`, which carries no index.
    evidence: |-
      `package_id` gets `db_index=True` justified by the coverage view's query, but the one
      queryset the module ships is a `finished_at IS NULL` scan over what becomes the largest
      table in the schema. `started_at`, `collector`, `policy_version` and `evidence_cutoff`
      are likewise unindexed, though `CPM-FR-22` replay queries by version and cut-off.
      Index choices need a populated inventory to measure against.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py
    severity: low
  - summary: >-
      `CollectionRun.Meta` and `PolicyRun.Meta` do not inherit `RunLedgerModel.Meta`.
    evidence: |-
      Harmless today, since the base Meta only sets `abstract`. It is the standard Django
      footgun: any `ordering`, `indexes`, `constraints` or `default_permissions` later added
      to the abstract base is silently dropped by both children -- and the constraint and
      index entries above are the likely next edits to that base.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py
    severity: low
  - summary: >-
      Two new persisted tables ship with no operator-facing documentation.
    evidence: |-
      `docs/observability.md` covers the `trace_id` correlation scheme this ledger joins to
      and is untouched. There is nowhere outside the source for an operator to learn the
      tables exist, what `partial` versus `skipped` means, or that a `running` row with a
      stale `started_at` is the signal of a killed worker.
    location: >-
      docs/observability.md
    severity: low
---

<intent-contract>

## Intent

**Problem:** A collection or policy run that dies mid-call leaves nothing behind. Evidence is
written at the *end* of a successful run, so a worker killed between the outbound call and the
insert is indistinguishable from a run that never started -- and "started and never finished"
cannot be asked at all. `CPM-FR-38` needs failure visible in the application rather than in
logs, and `CPM-FR-39` needs every run traceable to the process that performed it. `R-05`.

**Approach:** Two mutable run-ledger models in `core` -- `collection_runs` and `policy_runs` --
explicitly exempt from the append-only base by `CPM-AD-2`, plus one recording seam that creates
the row with status `running` *before* the first outbound call and finalizes it in a `finally`
on every exit path. The row carries the collector or policy name, the package where the run has
one, and the `trace_id` of the active span.

## Boundaries & Constraints

**Always:**
- The ledger is **mutable and not evidence**. Both models set `not_evidence = True` at the
  definition (the machine-readable form `tests/model_registry.py` already defines for exactly
  this story) and say why in the class docstring, and both are added to
  `RECORDED_NOT_EVIDENCE` in `tests/unit/django_apps/test_evidence_inheritance_audit.py`,
  which reconciles the table against the registry in both directions.
- Neither model inherits `AppendOnlyModel` and neither declares `observed_at`. A run row is not
  an observation.
- The row is **created before the first outbound call** and **finalized in a `finally`**. An
  exception leaving the body finalizes to `failed` and then propagates unchanged -- the
  recorder never swallows, never logs-and-continues (inherited `CG-3`).
- Finalization writes through `instance.save(update_fields=...)`. Never `queryset.update()`,
  `bulk_update()` or raw SQL: `EVIDENCE.02-AUDIT-002` sweeps all of `src/` for those forms
  regardless of which table they touch, and an exemption there is not this story's to take.
- Time comes from an injected `Clock` (`CPM-AD-26`). No module calls `timezone.now()`.
- `trace_id` is read from the active OpenTelemetry span, formatted `032x`, exactly as
  `config/observability/logging.py` formats it. The product adds no correlation scheme of its
  own (`CPM-AD-15`). `core` reads `opentelemetry.trace` directly -- it must not import
  `config`, which would invert `AD-4`'s dependency direction.
- A run with no single package writes **no** package reference (`NULL`), never a placeholder,
  and stays answerable by the unfinished-run query.
- `structlog` only, no `print`, no stdlib `logging`. Full type hints, Google docstrings,
  line length 120.

**Block If:**
- The outcome-audit amendment below cannot be written so that the excluded fields are checked
  against `RunState` instead of merely skipped. A field nothing audits is worse than the
  collision.

**Never:**
- No `ForeignKey` to a package. `identity.Package` does not exist -- `CPM-EP-IDENTITY` is
  backlog -- and a relation to an uninstalled app breaks `makemigrations`. See Design Notes.
- No collectors, no Celery tasks, no queues, no observation window, no coverage view. Those are
  `CPM-EVIDENCE-S04`, `S05`, `S06` and `CPM-EP-APP`.
- No evidence model. `CPM-AD-7` puts the first with `CPM-EP-CURRENCY`.
- No `ready()` on `CoreConfig`; `tests/unit/django_apps/test_core_app.py` asserts it has none.
- Do not rename a ledger column to dodge an audit's marker. The declared, recorded exemption is
  the supported way out -- `tests/model_registry.py` says so in those words.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Run completes | recorder entered, body returns | row `running` on entry; on exit `succeeded`, `finished_at` set from the clock | No error expected |
| Body raises | body raises `RuntimeError` mid-call | row finalized `failed`, `detail` carries the exception type and message | Exception re-raised unchanged (`EVIDENCE.03-INT-002`) |
| Partial success | body calls `handle.partial(detail=...)` | row `partial` with the detail | No error expected |
| Skipped inside window | body calls `handle.skipped(detail=...)` | row `skipped`, no evidence written by the body | No error expected |
| Worker killed | row written, process dies before exit | row persists as `running` with `finished_at` NULL; `unfinished()` returns it | Nothing to handle; the row is the record |
| Run not package-scoped | `package_id` omitted | column is NULL, not 0 and not a sentinel row; `unfinished()` still returns it | No error expected |
| No active span | recorder entered outside any span | `trace_id` is `""`, and the row is still written | Never blocks the run |
| Terminal state set twice | `handle.succeeded()` then `handle.failed()` | Refuses: `RunLedgerError` naming both states | Raised at the call site |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/outcomes.py` -- the *other*
  vocabulary. Read its module docstring: `RunState` is deliberately not built from
  `outcome_type`, and Design Notes says why.
- `src/django_apps/conda_package_supply_chain_monitor/core/clock.py` -- `Clock`, `SystemClock`,
  `FixedClock`. Injected by parameter; there is no module-level instance and no `get_clock()`.
- `src/django_apps/conda_package_supply_chain_monitor/core/models.py:1-79` -- the module
  docstring already states the run-ledger exemption and names this story. Extend it; do not
  restate it elsewhere.
- `src/django_apps/conda_package_supply_chain_monitor/core/models.py:395-420` -- `Meta` on
  `AppendOnlyModel`, including `base_manager_name`. The ledger models take **no** such Meta.
- `src/django_apps/conda_package_supply_chain_monitor/core/migrations/0001_provision_role_groups.py`
  -- the only migration in `core`; the new one is `0002`.
- `src/config/observability/logging.py:29-54` -- `add_otel_context`, the `032x` formatting the
  ledger must match. Read-only: `core` may not import `config`.
- `tests/model_registry.py:96-115,185-258` -- `NOT_EVIDENCE_ATTRIBUTE`, `declares_not_evidence`,
  `evidence_marks`, `exempt_models`. The seam exists; this story is its first user.
- `tests/unit/django_apps/test_evidence_inheritance_audit.py:80-91` -- `RECORDED_NOT_EVIDENCE`,
  empty and commented "`CPM-EVIDENCE-S03` is the story that will add ... to this table".
- `tests/unit/django_apps/test_outcome_field_audit.py:95-153,297-312` --
  `DERIVED_STATUS_NAMES = {"outcome", "status"}` and the sweep over `first_party_models()`.
  **This is the collision**: an unamended sweep demands the four outcome sentinels on the
  ledger's `status`. See Design Notes.
- `tests/unit/django_apps/test_mutation_path_audit.py:150-243` -- `MARKED_MUTATIONS`,
  `MANAGER_MARKERS`, `RECORDED_EXEMPTIONS`. `instance.save(...)` is not a marked form; the
  finalization needs no exemption, and must not acquire one.
- `tests/unit/django_apps/test_single_ordering_audit.py` -- fires only on `OutcomeState`
  member references. A `RunState` declaration is out of its scope.
- `tests/clocks.py` -- `FIXED_INSTANT`, `OBSERVATION_GAP`, `LATER_INSTANT`. Two clocks, never
  one wound forward.
- `tests/unit/conftest.py` -- the `fixed_clock` fixture.
- `tests/integration/conftest.py:47-` -- the `recorded_spans` fixture and the live tracer
  provider; how an integration case gets a real span to read a `trace_id` from.
- `tests/integration/django_apps/test_append_only_evidence.py:1-60` -- the shape an integration
  case in this repository takes (`@pytest.mark.django_db`, rollback per test).
- `pixi.toml:637-644` -- the `ci` gate: precommit, build, typecheck, lint, test-cov.

## Tasks & Acceptance

**Execution:**
- `src/django_apps/conda_package_supply_chain_monitor/core/runs.py` -- new. Declare `RunState`
  (`TextChoices`: `running`, `succeeded`, `partial`, `failed`, `skipped`), `TERMINAL_STATES`,
  and `RunLedgerError`. Docstring states, with the reason, that this is *not* the `CPM-AD-5`
  outcome vocabulary and must never be composed from `outcome_type`.
- `src/django_apps/conda_package_supply_chain_monitor/core/models.py` -- add abstract
  `RunLedgerModel` (`started_at`, `finished_at` nullable, `status` over `RunState` defaulting to
  `running`, `trace_id`, `detail`) carrying `not_evidence = True`, plus concrete `CollectionRun`
  (`collector`, `package_id` nullable indexed) and `PolicyRun` (`policy_version`,
  `evidence_cutoff`), with `db_table` `collection_runs` / `policy_runs`. Extend the module
  docstring: the exemption is documented at the definition, per AC 1.
- `src/django_apps/conda_package_supply_chain_monitor/core/models.py` -- add
  `RunLedgerQuerySet.unfinished()` (`finished_at__isnull=True`) as the ledger's default manager,
  so "started and never finished" is a query the product owns rather than a phrase in a story.
- `src/django_apps/conda_package_supply_chain_monitor/core/ledger.py` -- new. `current_trace_id()`
  reading the active span, and `collection_run(...)` / `policy_run(...)` context managers that
  insert the `running` row before yielding and finalize in a `finally`. Yield a handle offering
  `succeeded`, `partial`, `skipped` and `failed`; normal exit with nothing declared finalizes
  `succeeded`, an exception finalizes `failed` and re-raises.
- `src/django_apps/conda_package_supply_chain_monitor/core/migrations/0002_run_ledger.py` --
  generated by `pixi run makemigrations`, not hand-written.
- `tests/unit/django_apps/test_evidence_inheritance_audit.py` -- add both labels to
  `RECORDED_NOT_EVIDENCE`. The existing both-directions case then proves the exemption is taken
  exactly where it is recorded.
- `tests/unit/django_apps/test_outcome_field_audit.py` -- exclude the recorded run-ledger status
  fields from the sentinel sweep by an explicit `RECORDED_RUN_LEDGER_STATUS` table
  (label -> field name), reconciled in both directions, **and** assert each excluded field's
  choices are exactly `RunState.choices`. Excluded from one vocabulary, checked against the
  other; never unchecked.
- `tests/unit/django_apps/test_runs.py` -- new. `RunState`'s members and values; that it carries
  none of the four outcome sentinels and is not an `outcome_type` product; `TERMINAL_STATES`
  excludes `running` and covers every other member.
- `tests/unit/django_apps/test_run_ledger.py` -- new. Every I/O Matrix row that needs no
  database: the handle's state transitions, the double-terminal refusal, `current_trace_id()`
  with and without an active span, and that the models declare `not_evidence`, no
  `observed_at`, and do not inherit `AppendOnlyModel`.
- `tests/integration/django_apps/test_run_ledger.py` -- new. `EVIDENCE.03-INT-002` and the rows
  that need a real table: the raising body, the `running` row visible before finalization, the
  null-package run in `unfinished()`, and a `trace_id` matching a real recorded span.

**Acceptance Criteria:**
- Given the model registry, when `exempt_models()` is read, then it returns exactly
  `core.CollectionRun` and `core.PolicyRun`, and `evidence_models()` returns neither.
- Given a run recorded inside an active span, when the row is read back, then its `trace_id`
  equals the span's own id formatted `032x`, and equals what `add_otel_context` would emit.
- Given a run whose body raises, when control leaves the recorder, then the row exists, is
  `failed`, has `finished_at` set from the injected clock, and the original exception reaches
  the caller unchanged (`EVIDENCE.03-INT-002`).
- Given a run row written and not yet finalized, when `unfinished()` is queried, then the row is
  returned with status `running` and `finished_at` NULL -- for a package-scoped run and for one
  with no package alike.
- Given the full gate, when `pixi run ci` runs, then it exits 0 with coverage at or above 90%.

## Spec Change Log

## Review Triage Log

### 2026-09-04 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 1, medium 6, low 9)
- defer: 7: (high 0, medium 2, low 5)
- reject: 10: (high 0, medium 4, low 6)
- addressed_findings:
  - `[high]` `[patch]` No test drove a non-`Exception` `BaseException` through `_recorded`; narrowing the catch to `except Exception` left the whole suite green while a `SystemExit` run finalized `succeeded`. Parametrized the raising case over `RuntimeError`, `SystemExit` and an empty-message `TimeoutError`; mutation-checked that the narrowing now fails exactly that case.
  - `[medium]` `[patch]` A finalizing `save()` raising inside the `finally` replaced the caller's exception. Finalization now catches `DatabaseError`, logs it through `structlog` with the run pk and the body error, and re-raises only when no body exception is in flight.
  - `[medium]` `[patch]` The ledger `status` exclusion was wider than the amendment replacing it: nothing asserted `blank is False` or the field type. Both added.
  - `[medium]` `[patch]` The gate had no missing-migrations guard and the migration's length literals duplicated `models.py` constants. Added `test_migration_completeness.py` over the autodetector.
  - `[medium]` `[patch]` `test_unfinished_filters_on_finished_at_rather_than_on_status` asserted Django private query internals; replaced with a behavioural case over a row carrying a terminal status and a NULL `finished_at`.
  - `[medium]` `[patch]` Nothing asserted finalization writes through `update_fields`; added a case mutating a non-finalized column mid-run.
  - `[medium]` `[patch]` The recorders accepted a blank `collector`/`policy_version`, a naive `evidence_cutoff` and a negative `package_id`. All four refused with `RunLedgerError` before the row is built.
  - `[low]` `[patch]` The unrecorded-vocabulary check used exact set equality, so a `RunState`-plus-one status escaped it; now a superset check.
  - `[low]` `[patch]` `current_trace_id`'s prose said "no span is recording" where the code branches on `is_valid`; prose corrected, code unchanged.
  - `[low]` `[patch]` `TRACE_ID_FORMAT`'s comment claimed a single source of truth that cannot exist across the `AD-4` boundary.
  - `[low]` `[patch]` `PolicyRun.__str__` raised `AttributeError` on an unsaved instance.
  - `[low]` `[patch]` `RunHandle.raised` was public and overwrote a declared ending without refusing; renamed `_raised`.
  - `[low]` `[patch]` The ledger model labels were written twice across two test modules; one home in `tests/model_registry.py`.
  - `[low]` `[patch]` Restored the dropped `evidence_models() <= first_party_models()` containment assertion.
  - `[low]` `[patch]` Matrix row 8 was exercised only on a bare handle; added a case at the recorder surface.
  - `[low]` `[patch]` `recorded_spans` was under-typed as `object` behind a blanket `type: ignore`.

## Design Notes

**Why `RunState` is not built from `outcome_type`.** `CPM-AD-5`'s five states answer "what is
this package's derived status"; the ledger answers "what happened to this run". `not_applicable`
and `not_found` are meaningless for a run, and `running` is meaningless for a status. Composing
the ledger's vocabulary from the outcome sentinels would put four unreachable values in a column
and make `aggregate()` rank a run's lifecycle against a licence verdict. Two vocabularies, each
declared once, is the correct shape -- and `core/outcomes.py` stays "the whole of `CPM-AD-5`'s
implementation" exactly as its docstring claims.

**The audit collision, and why the ledger keeps the name `status`.**
`test_outcome_field_audit.py` decides what is a derived status **by field name**, and `status` is
in its table. The ledger's `status` therefore trips a sweep written for a rule it is not bound
by. There are two ways out and only one of them is honest: renaming the column to `state` dodges
a marker, which is precisely what `tests/model_registry.py` calls out as the worse option when it
explains why the `not_evidence` escape exists at all. So the name stays and the audit is amended
-- by a recorded table, reconciled in both directions, whose entries are then checked against
`RunState.choices` rather than merely skipped. An exemption in this repository is a counted
decision, never a hole.

**The package reference is an integer, not a relation, and that is forced.** `CPM-AD-3` says
every row references the package by its integer primary key -- but `identity.Package` does not
exist and `CPM-EP-IDENTITY` is two epics away, so a `ForeignKey` here cannot be migrated.
`package_id = PositiveBigIntegerField(null=True, db_index=True)` carries exactly the value
`CPM-AD-3` specifies today, and the field docstring records that `CPM-EP-IDENTITY` converts it to
a `ForeignKey(..., on_delete=PROTECT)` when the model lands. NULL means "this run was not scoped
to one package" (AC 5) and nothing else.

**Why the guarantee is about autocommit, and where it is stated rather than enforced.** AC 4
holds only because the `running` row is committed before the outbound call. A caller that wraps
the recorder in `transaction.atomic()` and is then killed loses the row -- the ledger is back to
recording nothing. A runtime guard on `connection.in_atomic_block` is not available: pytest's
`django_db` runs every test inside exactly such a block, so the guard would refuse the whole
suite. The constraint is therefore documented at the recorder and belongs to whichever story
first writes a collector that could break it.

**Shape of the recorder.**

```python
with collection_run(collector="pypi", clock=clock, package_id=pkg.pk) as run:
    payload = client.fetch(pkg.canonical_name)   # row is already `running`
    if payload.partial:
        run.partial(detail="3 of 5 sources answered")
```

## Verification

**Commands:**
- `pixi run makemigrations` -- expected: writes `core/migrations/0002_*`; a second run reports
  no changes.
- `pixi run test` -- expected: the unit suite passes, including the two amended audits.
- `pixi run test-integration` -- expected: `EVIDENCE.03-INT-002` and the ledger cases pass
  against a real table.
- `pixi run ci` -- expected: exits 0. Precommit, build, typecheck, lint, then the full suite at
  or above the 90% floor.

## Auto Run Result

Status: done
Blocking condition: none

**Implemented.** Two mutable run-ledger tables in `core` -- `collection_runs` and
`policy_runs` -- explicitly exempt from the append-only base, plus one recording seam that
writes the row with status `running` before the first outbound call and finalizes it in a
`finally` on every exit path, including a `BaseException`. The row carries the collector or
policy name, the package where the run has one, and the `trace_id` of the active span.
"Started and never finished" is a query the product owns: `unfinished()`.

**Files changed**

- `src/.../core/runs.py` -- new. `RunState`, `TERMINAL_STATES`, `RunLedgerError`; states why this is not the `CPM-AD-5` outcome vocabulary.
- `src/.../core/ledger.py` -- new. `current_trace_id()`, `RunHandle`, and the `collection_run` / `policy_run` recorders.
- `src/.../core/models.py` -- abstract `RunLedgerModel` carrying `not_evidence = True`, concrete `CollectionRun` and `PolicyRun`, and `RunLedgerQuerySet.unfinished()`.
- `src/.../core/clock.py` -- `is_aware()` promoted to a public helper; three copies of the naive-datetime predicate reduced to one.
- `src/.../core/migrations/0002_run_ledger.py` -- generated, not hand-written.
- `tests/unit/django_apps/test_outcome_field_audit.py` -- `RECORDED_RUN_LEDGER_STATUS`, reconciled both ways and checked against `RunState.choices`.
- `tests/unit/django_apps/test_evidence_inheritance_audit.py` -- `RECORDED_NOT_EVIDENCE` now names both ledger models.
- `tests/model_registry.py` -- `RUN_LEDGER_MODEL_LABELS`, the one home for the label pair.
- `tests/unit/test_model_registry.py` -- asserts AC 1 directly, replacing a case written to be deleted.
- `tests/unit/django_apps/test_migration_completeness.py` -- new. No model change may go unmigrated.
- `tests/unit/django_apps/test_runs.py`, `tests/unit/django_apps/test_run_ledger.py`, `tests/integration/django_apps/test_run_ledger.py` -- new.

**Review findings:** 16 patched (1 high, 6 medium, 9 low), 7 deferred, 10 rejected.

**Follow-up review recommended:** true. Patched counts by severity: high 1, medium 6, low 9.
The rule fires on the high-severity patch alone; the score `3 x 6 + 1 x 9 = 27` also exceeds 5.

**Verification.** `pixi run makemigrations --check --dry-run` reports no changes.
`pixi run ci` exits 0: 2421 tests pass, coverage 97.41% against a 90% floor, with
`clock.py`, `ledger.py`, `models.py` and `runs.py` each at 100%. The high-severity fix was
mutation-checked independently of the implementing agent: narrowing `except BaseException`
to `except Exception` fails exactly one case, `test_a_raising_body_finalizes_the_row_and_
re_raises_unchanged[base-exception]`, with `- failed / + succeeded` -- the false success the
finding predicted. The migration's `initial = True` was checked by regenerating the file:
Django's autodetector emits it because `core/0001` creates no models, so it is generated
output rather than a hand-edit, and two reviewers' claim to the contrary was rejected.

**Residual risks.** The seven deferred entries in the frontmatter, of which the first is the
one to read: the ordering guarantee this story rests on depends on autocommit, and no test
in the suite can observe it because every test runs inside pytest-django's atomic block --
the exact condition under which the guarantee is void. A future collector wrapping a
recorder in `transaction.atomic()` reopens `R-05` with the suite green. No production caller
of the seam exists yet, so nothing exercises the recorders against a real outbound call.
