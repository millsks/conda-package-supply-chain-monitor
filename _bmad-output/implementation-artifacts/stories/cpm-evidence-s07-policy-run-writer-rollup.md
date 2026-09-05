---
title: 'CPM-EVIDENCE-S07: The policy run, and the one writer of the rollup'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: true
baseline_revision: '12b3e3f608da1224ab695cabe03d37f9256f2eea'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s06-stale-failed-evidence-read-as.md
warnings: ['oversized']
deferred:
  - summary: >-
      The per-domain version map is a map holding a scalar: every key carries the run's own
      `policy_version`, because a pass has no version of its own to declare.
    evidence: |-
      `CPM-AD-11` requires "a per-domain version map, not a scalar version", and its reason is
      that a scalar forces every domain to be re-run when any one of them changes version, or
      lies about the ones that did not. The shape here is a map -- `{pass name: policy_version}`
      -- but every value is the same run-level string, so the property the map exists for is not
      yet delivered. `PolicyPass` declares four things and a version is not one of them. Closing
      it means adding a `version` declaration to the pass contract, which is a change to a
      contract no real pass has implemented yet; doing it now would be designing against zero
      consumers. The shape is right, so this becomes a value change rather than a schema change.
    severity: medium
  - summary: >-
      A full-inventory run is one unbroken task: the package list is materialized whole and each
      package costs a transaction and two queries.
    evidence: |-
      `packages_for_rollup()` does `list(Package.objects.order_by("pk"))`, and `compose_rollup`
      issues an `update_or_create` inside its own `transaction.atomic()` per package.
      `core/tasks.py`'s docstring cites `CPM-AD-9` ("work that exceeds the time limit is chunked
      per package") as why the inherited Celery limits stand, but nothing chunks, streams via
      `.iterator()`, or resumes. At the product's stated ten-thousand-package target this is one
      task holding one worker slot for its whole duration, and a soft time limit lands mid-run
      with no way to continue from where it stopped. Chunking needs a resumption story -- which
      packages a run already composed -- and that is a design this story did not take on.
    severity: medium
  - summary: >-
      Two policy runs composing the same package concurrently race on the rollup's unique key.
    evidence: |-
      `compose_rollup` calls `update_or_create` inside a per-package transaction with no
      `select_for_update`, so two overlapping runs can both miss the row and both insert,
      leaving one to raise `IntegrityError`. The compose phase now contains per package, so the
      loser skips that package rather than aborting the run -- but it is a skipped package for a
      reason no operator can act on. Beat schedules one run, so overlap needs a manual trigger
      or a run outliving its interval; a lock or an idempotent upsert closes it.
    severity: low
  - summary: >-
      Fixture literals are duplicated across the new test modules, in the pattern `tests/passes.py`
      was extracted to prevent.
    evidence: |-
      `A_POLICY_VERSION`, `A_COLLECTOR`, `an_ended_collection_run()` and `a_package()` appear in
      both `tests/integration/django_apps/test_policy_run.py` and `test_rollup.py`, and the two
      `a_package` helpers took different signatures at one point. `"licence_status"` is declared
      three times under two names across the unit modules. Each is harmless alone and the set is
      exactly the drift those helper modules exist to prevent.
    severity: low
  - summary: >-
      `CPM-IDENTITY-S03` must call `core/confidence.py`'s gate rather than build a second one.
    evidence: |-
      `identity/models.py`'s docstring assigns the `CPM-AD-4` gate to `CPM-IDENTITY-S03`, and
      this story built it -- because `CPM-AD-4` names the orchestrating policy run as its caller
      and this story's acceptance criterion requires an unmapped package's gated statuses to
      read `unknown`. The decision is recorded in the Spec Change Log. Whoever picks up S03
      should find `gated_status` and `require_known_confidence` already in `core` and call them;
      a second implementation is the one thing `CPM-AD-4` forbids outright.
    severity: medium
---

<intent-contract>

## Intent

**Problem:** `PolicyRun` is a ledger row and nothing else. There is no pass, no registry, no
rollup and no writer -- so currency, feedstock, vulnerability, licence, readiness and priority
would each invent their own orchestration, their own cut-off, and their own idea of who may
write current health. `CPM-AD-21` exists to make that impossible and none of it is built.

**Approach:** Build the orchestration: passes that *register* rather than being invoked, a run
carrying one id and one cut-off, per-domain derived tables each owned by exactly one pass, and
one writer that composes the rollup by full-row replace per package inside one transaction per
package. Add `CPM-AD-4`'s confidence gate as the single function in `core`. Enforce the
ownership rule by audit so it holds against passes nobody has written yet.

## Boundaries & Constraints

**Always:**
- The cut-off is the `finished_at` of a **completed** collection run, never the current time
  (`CPM-AD-21`). A pass never reads evidence written by a run still `running`.
- Beat schedules the **run**, never a pass (`CPM-AD-20`, `CPM-AD-21`). No cadence in code: the
  schedule is a `django_celery_beat` row, and `test_task_declaration_audit.py` fails any
  `schedule=`/`run_every=`/`time_limit=` in a decorator or `CELERY_BEAT_SCHEDULE` outside
  `config/settings/`. The task is named in the `cpm.policy.` namespace so `core/queues.py`
  routes it by name; a name outside the namespace is routed nowhere and silently never runs.
- A pass writes **only** its own per-domain derived table, keyed `(package, policy_run)`. No pass
  writes the rollup -- enforced by an audit over the registry, not by review (`ASR-3`).
- One writer composes the rollup: full-row replace per package, one `transaction.atomic()` **per
  package** (`CPM-AD-23`), stamped with the policy run, the run's cut-off, and a **per-domain
  version map, not a scalar** (`CPM-AD-11`).
- The rollup is a Django-managed table in the migration graph, never a materialized view, and it
  carries `computed_at` (`CPM-AD-11`).
- Exactly one rollup row per `identity.Package`, always -- including `unmapped` ones.
- The confidence gate is **one function in `core`** (`CPM-AD-4`), reusing `IdentityConfidence`
  rather than restating its three values. Expressed as *writing a value*: `unmapped` writes
  `unknown`, `inventory-derived` records the label and does **not** degrade the value. Never as
  suppressing a row.
- Every rollup status column is `CharField(choices=...)` from `core/outcomes.py` and declared
  `editable=False`, or `CPM-EVIDENCE-S06`'s writability audit fails it. The rollup writer is the
  only module that may write one, and is recorded in that audit's `RECORDED_EXEMPTIONS` per form
  per exact count.
- The recorder is never wrapped in `transaction.atomic()`: `core/ledger.py`'s ordering guarantee
  depends on the `running` row committing first.
- Time comes from the injected clock (`CPM-AD-26`).
- `pixi` is the only Python runner.

**Block If:**
- Composing the rollup would require inventing a domain status column no epic has asked for. The
  rollup "grows as passes are added"; this story builds the mechanism and the stamps.

**Never:**
- No concrete policy pass. Currency, licence and the rest are their own epics; this story ships
  the contract and proves it with fixtures.
- No change to `CollectionRun.package_id`. Identity-S01 deliberately left it a
  `PositiveBigIntegerField` and recorded why -- the ledger's writer is not ready for an enforced
  key, and the conversion needs a hand-written `RenameField`+`AlterField` pair. That is
  `CPM-IDENTITY-S06`'s work, not this story's.
- No second confidence vocabulary. `IdentityConfidence` is the one, hyphen and all.
- No JSON blob standing in for status columns: `CPM-AD-5` requires a `CharField(choices=...)` per
  derived status, and a map keyed by domain would evade every audit that reads column names.
- No cadence *value* chosen.
- No `-m` on `test-cov`, and no lowering of the 90% floor.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cut-off chosen | Ledger holds completed and running collection runs | The cut-off is the newest `finished_at` among completed runs | No error expected |
| Cut-off, nothing completed | Only `running` rows, or an empty ledger | The run refuses to start rather than defaulting to now | `PolicyRunError` |
| Cut-off excludes in-flight | A run still `running` finished nothing | Its evidence is outside the cut-off; no pass sees it | No error expected |
| Pass registration | A pass declaring a name and the derived model it owns | Registered, returned in declared order | No error expected |
| Two passes, one name | A second pass under a registered name | Refused | `PolicyPassError` |
| A pass claiming the rollup | A pass declaring the rollup as its derived table | Refused at registration, and the audit fails independently (`EVIDENCE.07-AUDIT-002`) | `PolicyPassError` |
| Two passes, one column | Both contribute the same rollup column | Refused: a column has one owner | `PolicyPassError` |
| A pass inventing a column | A contribution naming a column the rollup does not declare | Refused, naming the column and the pass | `PolicyPassError` |
| Ordered reads | A later pass reads an earlier pass's derived rows for this run | It sees them; passes execute in declared order | No error expected |
| Two domains, one run | Two passes writing two derived tables | Both survive the compose; neither is reset to defaults (`EVIDENCE.07-INT-001`) | No error expected |
| Rollup compose | Passes completed, packages exist | Exactly one row per `Package`, full-row replaced, stamped with run, cut-off, version map | No error expected |
| Recompose | A second run over the same packages | Still exactly one row per package, carrying the newer run's stamps | No error expected |
| A package added between runs | A new `Package` row appears | The next compose gives it a row too -- the set is read, never cached | No error expected |
| Unmapped package | `Package.confidence` is `unmapped` | The row exists and its gated statuses read `unknown` | No error expected |
| Inventory-derived | `Package.confidence` is `inventory-derived` | The value is **not** degraded; the label is recorded | No error expected |
| Verified | `Package.confidence` is `verified` | The value passes through untouched | No error expected |
| One package fails | A pass raises for one package | That package's transaction rolls back; other packages' rows survive (`CPM-AD-23`) | Run finalized `partial` |
| No packages at all | An empty `packages` table | The run completes having written nothing, rather than failing | No error expected |
| Beat wiring | The run task | Named under `cpm.policy.`, routed to the policy queue, no cadence in code | Audit failure otherwise |

</intent-contract>

## Code Map

- `src/.../identity/models.py:181` -- `Package` (table `packages`, `BigAutoField` PK,
  `canonical_name` unique, `confidence` defaulting to `UNMAPPED`). `:126` is
  `IdentityConfidence` (`verified` / `inventory-derived` / `unmapped`, hyphen intentional).
  Neither identity model declares `not_evidence`, and neither declares `computed_at` -- so the
  rollup is the first derived-state model in the repository.
- `src/.../core/models.py:794` -- `PolicyRun` (`policy_version`, non-null `evidence_cutoff`,
  `not_evidence = True`); its docstring says this story owns the orchestration. `:735` is the
  comment recording why `CollectionRun.package_id` is still an integer and that the conversion is
  `CPM-IDENTITY-S06`'s -- read it before deciding the rollup's key.
- `src/.../core/ledger.py:447` -- `policy_run(*, policy_version, evidence_cutoff, clock)`;
  refuses a blank version and a naive cut-off before writing. `RunHandle` at `:228`
  (`succeeded`/`partial`/`skipped`/`failed`; declaring twice raises; an exception overrides and
  re-raises). Finalization writes only `FINALIZED_FIELDS` via `save(update_fields=...)`.
- `src/.../core/models.py` -- `RunLedgerQuerySet.failed()` and `unfinished()`
  (`CPM-EVIDENCE-S06`); `FINISHED_AT_FIELD`. The cut-off query is the mirror of `unfinished()`.
- `src/.../core/runs.py` -- `RunState`; `partial` is the ending a per-package failure produces.
- `src/.../core/outcomes.py` -- `OutcomeState`, `PRECEDENCE`, `aggregate`, `EMPTY_AGGREGATE`.
  The gate writes `OutcomeState.UNKNOWN`. No second precedence order may be defined.
- `src/.../core/registry.py` -- the collector registry `CPM-EVIDENCE-S06` added: explicit
  register/unregister, duplicate-name refusal, frozen read. The shape to imitate; typed to
  `Collector`, so not reusable directly.
- `src/.../core/collection.py` -- `_write_evidence` shows the per-package
  `transaction.atomic()` placement `CPM-AD-23` requires.
- `src/.../core/queues.py:98` -- `Queue.POLICY`; `:25` the `@shared_task(name="cpm.<queue>.<x>")`
  convention; `CELERY_TASK_ROUTES` derived from the namespace.
- `core/migrations/0002_run_ledger.py` -- a **generated** schema migration left verbatim, with
  `db_table` in `options`. `tests/unit/django_apps/test_migration_completeness.py:83` fails if
  `makemigrations` would produce anything.
- `tests/unit/django_apps/test_derived_status_writability_audit.py` -- `DERIVED_STATE_MARK`
  (`computed_at`) is how the rollup is recognised; `DERIVED_STATUS_NAMES`/`_SUFFIXES` the column
  convention; `ORM_WRITE_METHODS` and `RECORDED_EXEMPTIONS` the scan the writer must be recorded
  in. `derived_state_models()` is empty today and this story is named in its docstring as the one
  that makes it non-vacuous.
- `tests/model_registry.py:123` -- `RUN_LEDGER_MODEL_LABELS`; `:109` the `not_evidence`
  escape hatch, still unused. A new non-evidence model must carry none of the three evidence
  marks, or declare the hatch *and* be recorded.
- `tests/unit/django_apps/test_task_declaration_audit.py` / `test_task_routing_audit.py` /
  `tests/celery_tasks.py` -- what a new task must satisfy and the fixture-task helper.
- `tests/collectors.py` -- the fixture-model pattern (`isolate_apps` plus a session-scoped
  schema-editor fixture in the integration tier) fixture passes and derived tables will follow.

## Tasks & Acceptance

**Satisfies:** `CPM-FR-37`, and the orchestration half of `CPM-FR-22`

**Governed by:** `CPM-AD-4`, `CPM-AD-8`, `CPM-AD-11`, `CPM-AD-21`, `CPM-AD-23`

**Test design.** Bound by the TEA system-level test design: test IDs
`EVIDENCE.07-AUDIT-002` and `EVIDENCE.07-INT-001`; risk closed, `R-02`.

**Execution:**
- `src/.../core/confidence.py` -- **new.** `CPM-AD-4`'s gate as the single function in `core`,
  importing `IdentityConfidence` rather than restating three values whose spelling has already
  been fixed once. `unmapped` writes `unknown`; `inventory-derived` records the label and does
  not degrade; `verified` passes through. One function so eight passes cannot each re-implement
  it, and it writes a value rather than suppressing a row so every package keeps its rollup row.
- `src/.../core/policy.py` -- **new.** `PolicyPassError`, the `PolicyPass` contract (declared
  `name`, the `derived_model` it owns, the rollup columns it contributes, and a method producing
  per-package results), and the ordered registry: `register_pass`, `unregister_pass`,
  `registered_passes()`. Refuses a duplicate name, a pass claiming the rollup, two passes
  claiming one column, and a contribution naming a column the rollup does not declare. Passes
  register rather than being invoked, which is what makes the set enumerable and the ownership
  rule enforceable against passes not yet written.
- `src/.../core/models.py` -- add `PackageHealth`: `package` (`OneToOneField(Package,
  on_delete=PROTECT)`), `policy_run` (`ForeignKey(PolicyRun, PROTECT)`), `computed_at`,
  `evidence_cutoff`, `confidence`, `policy_versions` (the per-domain map), plus indexes on the
  two columns a read surface filters and sorts on. `not_evidence = True` is **not** declared --
  it carries none of the three evidence marks. A real relation here where `CollectionRun` keeps
  an integer, because neither of that column's two recorded reasons applies to a new table with a
  new writer. `OneToOneField` rather than `ForeignKey(unique=True)`: the two build the same column
  and the same index, and only the first says what the contract is -- `package.health` is the row,
  not a manager a read surface must call `.first()` on and then decide what a second row means.
  Also add `RunLedgerQuerySet.finished()`, the mirror of `unfinished()`, so the cut-off filter is
  spelled once.
- `core/migrations/0003_package_health.py` -- **new, generated and left verbatim**, as `0002` was.
- `src/.../core/rollup.py` -- **new.** The one writer: read the packages, compose the registered
  passes' contributions, apply the gate, full-row replace inside one transaction per package.
  Its own module so "who writes the rollup" has a one-file answer and the audit exemption names
  one file.
- `src/.../core/policy_run.py` -- **new.** The orchestration: choose the cut-off from the newest
  completed collection run, open the recorder, execute registered passes in declared order, then
  compose. Refuses to start when nothing has completed, because the alternative is the current
  time and that is the one value `CPM-AD-21` forbids.
- `src/.../core/tasks.py` -- **new.** `@shared_task(name="cpm.policy.run")`, carrying no cadence
  and no time limit. Beat schedules the run; a pass is never a task.
- `tests/passes.py` -- **new.** Fixture passes and fixture derived tables in one place, as
  `tests/collectors.py` holds the collector fixtures.
- `tests/unit/django_apps/test_confidence.py` -- **new.** The gate's three rows, and that
  `inventory-derived` does not degrade a determinate value.
- `tests/unit/django_apps/test_policy_registry.py` -- **new.** Registration, declared order, and
  the four refusals.
- `tests/unit/django_apps/test_pass_ownership_audit.py` -- **new.** `EVIDENCE.07-AUDIT-002`,
  with a synthetic the detector is measured against so an empty registry cannot pass vacuously.
- `tests/unit/django_apps/test_rollup_row.py` -- **new.** The unit half of the writer: the gate
  applied to a contributed column and to a *defaulted* one, and the full-row replace. Both need a
  contributable column, which the real rollup does not declare, so they are measured against the
  synthetic rollup in `tests/passes.py`.
- `tests/unit/django_apps/test_policy_contribution.py` -- **new.** What a pass may *return*: the
  column must be one it declared, the value one the column's own `choices` offer -- Django
  enforces `choices` on neither `save()` nor `create()` -- and `None` is refused rather than read
  as the default.
- `tests/integration/django_apps/conftest.py` -- **new.** The session-scoped schema fixture for
  the two fixture derived tables, shared by the two integration modules below so a per-module copy
  cannot drift.
- `tests/integration/django_apps/test_policy_run.py` -- **new.** The cut-off rows -- including a
  still-running run that bounds it and one that cannot -- the ordered read, the per-package
  transaction boundary, the `partial` and `failed` endings, and the failure log.
- `tests/integration/django_apps/test_rollup.py` -- **new.** `EVIDENCE.07-INT-001`: two passes,
  two domains, both surviving; one row per package; recompose replacing rather than
  accumulating; the stamps; the unmapped gate; the empty-inventory case; per-package containment
  in the compose phase; and the `PROTECT`/uniqueness constraints the docstrings argue for,
  asserted against the database rather than the declaration.
- `tests/unit/django_apps/test_derived_status_writability_audit.py` -- record the rollup writer
  in `RECORDED_EXEMPTIONS`, per form and per exact count -- which today means recording, in the
  open, that it needs no entry: the rollup declares no domain status column yet, so the writer
  contains nothing the scan matches. Two guards keep that honest: the scan is asserted to still
  reach `core/rollup.py`, and the rollup is asserted to be a recognised derived-state model, which
  is this audit's registry sweep meeting its first real subject.
- `tests/unit/django_apps/test_task_routing_audit.py` -- the new task's routing, asserted from a
  name composed out of `core/queues.py` rather than imported from the module under test, so the
  registry read is autodiscovery's rather than one this case seeded.
- `tests/unit/django_apps/test_run_ledger.py` / `tests/unit/django_apps/test_identity_models.py`
  -- the `RunHandle.run` refusal, and the reconciliation of the rollup's mirrored `confidence`
  width against identity's.

**Acceptance Criteria:**
- Given a policy run, when it is scheduled, then beat schedules the **run** and never an
  individual pass, and the run has one identifier, one cut-off and a declared ordered list of
  passes.
- Given a ledger with completed and running collection runs, when a policy run starts, then its
  cut-off is the newest completed run's `finished_at` that no still-running run can write behind,
  and a ledger with nothing settled refuses rather than using the current time.
- Given the rollup, when its storage is chosen, then it is a Django-managed table inside the
  migration graph -- never a database materialized view -- and it carries `computed_at`.
- Given registered passes, when the run executes, then each writes only its own derived table
  keyed `(package, policy_run)`, in declared order, and a later pass can read an earlier one's
  rows.
- Given the passes have completed, when the rollup is composed, then exactly one row per
  `identity.Package` is full-row replaced inside one transaction per package, stamped with the
  run, the cut-off and the per-domain version map.
- Given a pass declaring the rollup as its own table, when the ownership audit runs, then it
  fails and names the pass (`EVIDENCE.07-AUDIT-002`).
- Given two passes writing different domains in one run, when the run completes, then both
  results survive and neither is reset (`EVIDENCE.07-INT-001`).
- Given an `unmapped` package, when the rollup is composed, then it still has exactly one row and
  its gated statuses read `unknown`.
- Given `pixi run ci`, when it runs, then it exits 0 with coverage at or above the 90% floor.

## Spec Change Log

- **The cut-off reads *ended* collection runs, not "completed" ones, and is additionally bounded
  by the earliest in-flight start.** The contract says "the `finished_at` of a **completed**
  collection run". Two deliberate readings sit under that word. First, `finished()` filters on
  `finished_at` and never on `status`, exactly mirroring `unfinished()`: a run that failed *after*
  writing some evidence has still ended and its rows are in the ledger, so a cut-off chosen behind
  it would hide evidence the system holds -- a quieter failure than the one the rule exists to
  prevent, and just as wrong. Second, the newest ending alone does **not** satisfy `CPM-AD-21`'s
  other half: a run that started earlier and is still `running` may write evidence stamped inside
  that ending, so the cut-off is bounded to the newest ending at or before the earliest
  still-running `started_at`. The consequence, recorded rather than discovered: a stuck collection
  run holds policy runs back, which is `CPM-NFR-3`'s trade taken deliberately -- the previous
  rollup stands rather than being replaced by an answer no replay reproduces. Argued at
  `core/policy_run.py`'s `choose_evidence_cutoff`.
- **`CPM-AD-4`'s confidence gate is built here rather than in `CPM-IDENTITY-S03`.** Identity's own
  module docstring names S03 as the gate's home. `CPM-AD-4` says the gate is "one function in
  `core`, called by the orchestrating policy run (`CPM-AD-21`), never re-implemented per pass" --
  this story *is* that run, and its own acceptance criterion requires an `unmapped` package's
  gated statuses to read `unknown`. Building it in S03 instead would either leave that criterion
  unmet or produce the second implementation `CPM-AD-4` forbids. S03 keeps the resolution
  semantics that *set* a confidence; `core/confidence.py` is what reads one. Argued in that
  module's docstring and in the Design Notes below.

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 19: (high 2, medium 13, low 4)
- defer: 5: (high 0, medium 3, low 2)
- reject: 0
- addressed_findings:
  - `[high]` `[patch]` `choose_evidence_cutoff` did not exclude in-flight evidence, and its
    docstring claimed it did. The newest ending is not safe while a run that started *earlier* is
    still going: that run may write evidence stamped inside the cut-off. A pass then reads rows
    an in-flight run is still adding to, and the same version replayed reads a different set --
    exactly the non-reproducibility `CPM-FR-22` promises cannot happen. Bounded by the earliest
    `started_at` among unfinished runs. The existing case asserted the unsafe answer against
    precisely the hazardous arrangement, so it was rewritten rather than the code changed, and
    two cases added: the in-flight run that genuinely cannot have written behind, and the ledger
    whose only ending is behind an in-flight run and therefore refuses.
  - `[high]` `[patch]` The confidence gate was skipped for any column nobody contributed: a
    contributed verdict went through `gated_status`, the default branch did not. The first real
    `currency_status` with a determinate default would have made every **unmapped** package read
    that value -- a determinate claim about a package whose identity was never established, which
    is the outcome `CPM-AD-4` exists to prevent. Both paths now resolve into one gated write, and
    the fifth `test_rollup_row.py` case covers the one branch combination none of the four
    existing cases reached.
  - `[medium]` `[patch]` The inventory was read twice per run, so a `Package` inserted between
    the reads got a row no pass evaluated and the "n of m failed" count was against a different
    m. Read once and handed to both phases.
  - `[medium]` `[patch]` A run in which *every* package failed finalized `partial`.
    `RunLedgerQuerySet.failed()` excludes `partial`, so a run that accomplished nothing was
    invisible to the one query `CPM-FR-38` exists to make answerable. Now `failed`.
  - `[medium]` `[patch]` The compose phase had no per-package containment, unlike the pass phase,
    so one unwritable row aborted every package after it. Contained, and proved with a real data
    condition rather than an injected fault -- a `confidence` value outside `IdentityConfidence`,
    which `create()` accepts because Django validates `choices` on neither `save()` nor
    `create()`. Fixing the test surfaced a second defect: the writer was copying an unrecognised
    confidence straight into a `choices` column.
  - `[medium]` `[patch]` A pass could return a value the column's vocabulary does not offer, or
    `None`, and it landed in the column unchecked. Both refused, naming the pass and the column.
    The check reads the **column's own declared choices** rather than `OutcomeState`'s five, so a
    composed per-status type's verdict is accepted -- `CPM-AD-5` exists to allow exactly that.
  - `[medium]` `[patch]` `core/policy.py` bound `ROLLUP_MODEL` by value at import, so a
    substituted rollup left the registry comparing against the real model. Read at call time,
    which also let three inert `monkeypatch.setattr` calls be deleted: those cases now substitute
    the model itself, so the patch is load-bearing rather than decorative.
  - `[medium]` `[patch]` The registry refused a duplicate name, a rollup claim and a contested
    column, but not two passes declaring the same `derived_model`, the same class registering
    twice under two names, or one pass declaring a column twice. All three refused.
  - `[medium]` `[patch]` `ForeignKey(unique=True)` became `OneToOneField(..., related_name=
    "health")`: it expresses the actual contract, drops Django's `fields.W342`, and gives read
    surfaces `package.health` rather than a manager they must call `.first()` on. `Meta` gained
    indexes on `evidence_cutoff` and `computed_at` -- the two columns the model's own docstring
    says a read surface filters and sorts on. Migration regenerated.
  - `[medium]` `[patch]` Nothing asserted the database held the constraints the docstrings argue
    for. Added cases: deleting a referenced `PolicyRun` or `Package` raises `ProtectedError`, and
    a second rollup row for one package raises `IntegrityError`.
  - `[medium]` `[patch]` The task-registration case was satisfied by the test module's own import
    of `core.tasks`, so renaming that module to anything autodiscovery does not scan would have
    kept the suite green while beat could never reach the task.
  - `[low]` `[patch]` Two log-event constants carried "named so the case that asserts the log and
    the code that emits it cannot drift" and no case asserted either; the per-package failure log
    is the only record of *which* pass broke on *which* package. Both asserted.
  - `[low]` `[patch]` `test_the_rollup_row_survives_and_is_replaced_by_the_run_that_follows_a_partial_one`
    asserted only the survival half -- a writer that skipped a package once and kept skipping it
    would have passed. The third, successful run now runs and the replacement is asserted.
  - `[low]` `[patch]` Story record: `**Satisfies:** CPM-FR-37` and the `CPM-AD-23`, `CPM-FR-37`
    and TEA test-design references had been dropped by the rewrite while the body still cited
    them; original AC 1 and AC 5 survived only as prose; the task list named an untouched file
    and omitted two new ones. All restored and corrected.

Two instructions I gave were narrowed or widened by the implementer, and both corrections were
right:

- I asked for a refusal of "any value that is not an `OutcomeState` member". That would refuse a
  correct `violation` verdict from a `LicenceOutcome` composed by `core/outcomes.py`'s
  `outcome_type` -- which is exactly what `CPM-AD-5` says a per-status vocabulary is for. Reading
  the column's own `choices` is narrower than "any string" and wider than the base five.
- I asked for a compose-phase failure test; monkeypatching the writer would have tested the
  `except` clause and nothing else. A real unrecognised-confidence row tests the same containment
  and found a second bug on the way.

## Design Notes

**Why the rollup takes a real relation while the ledger keeps its integer.** Identity-S01
left `CollectionRun.package_id` alone and recorded two reasons: a real key is enforced from the
moment it is migrated and that ledger's writer is not ready for it, and the conversion is not one
`AlterField` because renaming the attribute reads to the autodetector as a remove-and-add.
Neither reason reaches a table that does not exist yet. There is nothing to rename, and the
writer is being built in this story to satisfy the constraint. Taking the integer "for
consistency" would mean the one table whose whole purpose is *one row per inventory package*
could not say which packages those were. It is a `OneToOneField` rather than
`ForeignKey(unique=True)` for a reason about the *reader* rather than the schema: the two build
the same column and the same unique index, and Django says so in `fields.W342`, but only the
first gives a read surface `package.health` as the row. A `ForeignKey` hands it a related manager,
so every projection writes `.first()` and has to decide what a second row means -- a question
`CPM-AD-11` has already answered.

**Why the gate is built here even though identity names `CPM-IDENTITY-S03`.** `CPM-AD-4` says the
gate is "one function in `core`, called by the orchestrating policy run (`CPM-AD-21`), never
re-implemented per pass". This story *is* the orchestrating policy run, and its own acceptance
criterion requires an `unmapped` package's gated statuses to read `unknown`. Building it in S03
instead would either leave that criterion unmet or produce a second implementation, which is the
one thing `CPM-AD-4` forbids. It reuses `IdentityConfidence` rather than restating the values --
identity's own docstring says the hyphenated spelling exists so a later gate is not translating
between two spellings of three values.

**Why the rollup has no domain status columns yet.** `epics.md` says it "composes whatever
derived tables exist, so it grows as passes are added", and today none exist. So the rollup ships
with its identity, its stamps and the confidence, plus the *mechanism* by which a pass
contributes a column -- declared, validated against the model's real fields, owned by exactly one
pass. Inventing `currency_status` now would be guessing at an epic that has not run, and
`CPM-AD-5` forbids the alternative of a JSON map keyed by domain.

The honest consequence, stated rather than discovered: **no real domain column is composed in
this story**, so the contribution path is proven by fixture passes and by the refusals rather
than by a shipped column. The first real pass exercises it end to end.

**Why the cut-off refuses rather than defaults.** `CPM-AD-21` names exactly one forbidden value,
the current time, because a cut-off of *now* silently includes evidence from a run still in
flight -- the non-reproducibility `CPM-FR-22`'s replay guarantee exists to prevent. A run with
nothing completed behind it has no correct cut-off, and inventing one makes every later replay of
that version disagree with the original.

**Why passes register rather than being called.** So the set is enumerable, so "no pass writes
the rollup" can be checked against passes nobody has written. A run that called its passes
directly would make that a code review somebody has to remember to do, which is `ASR-3`.

## Verification

**Commands:**
- `pixi run ci` -- expected: exit 0, coverage at or above 90%.
- `pixi run gate-postgres` -- expected: exit 0. This story adds a migration, two protected
  relations and two indexes, which is exactly the shape sqlite accepts and PostgreSQL may reject
  -- and the `ProtectedError` and `IntegrityError` cases assert against whichever backend the run
  is on.
- `pixi run gate-redis` -- expected: exit 0, nothing skipped.

## References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S07]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-21]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-11]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-4]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-23]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-22]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-37]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]
- [Source: _bmad-output/implementation-artifacts/stories/cpm-identity-s01-package-identity-model.md] -- why the ledger's key was left alone

## Auto Run Result

Status: done
Blocking condition: none

**What this completes.** `CPM-AD-21` in full, and the orchestration half of `CPM-FR-22`. A policy
run now chooses one cut-off, opens one ledger row, executes registered passes in declared order,
and hands their contributions to one writer that composes the rollup by full-row replace per
package. `CPM-AD-4`'s confidence gate exists as one function in `core`.

**Files changed**

- `src/.../core/confidence.py` -- new. The gate, plus `require_known_confidence`.
- `src/.../core/policy.py` -- new. The pass contract and the ordered registry, with seven
  refusals.
- `src/.../core/rollup.py` -- new. The one writer.
- `src/.../core/policy_run.py` -- new. The cut-off, the ordered execution, the three endings.
- `src/.../core/tasks.py` -- new. `cpm.policy.run`, carrying no cadence.
- `src/.../core/models.py` + `core/migrations/0003_package_health.py` -- `PackageHealth`, keyed
  `OneToOneField(Package, PROTECT)`, with indexes on the two columns a read surface uses.
- `src/.../core/ledger.py` -- `RunHandle` gained the row it is recording, so orchestration can
  key derived rows and stamp the rollup. Additive; the ordering guarantee is untouched.

**Review findings:** 19 patched (2 high, 13 medium, 4 low), 5 deferred, 0 rejected.

**Follow-up review recommended:** true. Two high-severity patches; either fires the rule alone.

**Both high findings were latent rather than active, which is why they would have shipped.**
The cut-off excluded in-flight evidence in its docstring and not in its code: a run still going
that started before the newest ending can write inside the cut-off, and a pass then reads rows
that run is still adding to. And the confidence gate was applied to contributed verdicts only,
so the first domain column with a determinate default would have made every unmapped package
read a determinate verdict. Neither is reachable today -- no domain column exists -- and both
become live with the first real pass.

**Verification.** `pixi run ci` exits 0 -- 3438 tests, coverage 98.06% against a 90% floor, with
every module this story adds at 100%. `pixi run gate-postgres` exits 0 against `postgres:17`,
which matters here because this story adds a migration and two relations. `pixi run gate-redis`
exits 0 with nothing skipped.

**Residual risks.** The five `deferred` entries. The one that qualifies what this story delivered:
the per-domain version map is a map holding a scalar, because `PolicyPass` declares no version of
its own -- the shape `CPM-AD-11` asks for, without the property it asks for it. The rollup also
declares no domain status column yet, so the contribution path is proved by fixtures and
refusals rather than by a shipped column; the first real pass is what exercises it end to end.
