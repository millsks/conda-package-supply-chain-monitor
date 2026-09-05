---
title: 'CPM-IDENTITY-S06: The inventory arrives, and arrives as evidence'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '12b3e3f608da1224ab695cabe03d37f9256f2eea'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s01-package-identity-model.md
warnings: ['oversized']
deferred:
  - summary: >-
      `CPM-IDENTITY-S06`'s freshness target is 2 days by derivation, but the sweep duration the
      derivation adds has never been measured -- PRD Open Question 7b.
    evidence: |-
      OQ-7 was resolved on 2026-09-05 (`27f20f0`) while this story was being built. The target
      is no longer a guess: `cadence x (1 + tolerated_missed_runs)` gives 2 days for a daily
      cadence tolerating one missed run, and the rule that a target must be strictly greater
      than its cadence is now its own test. What OQ-7b left open is the third term -- a target
      must also exceed one sweep's wall-clock duration, and no sweep has been run at
      `CPM-NFR-1`'s ten thousand packages. Two days is comfortable if a sweep finishes inside
      hours and wrong if it does not. The measurement needs a populated inventory, so it lands
      with `CPM-EP-CURRENCY`; until then the value is derived but unconfirmed.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py -- INVENTORY_FRESHNESS_TARGET
    severity: low
  - summary: >-
      `core.CollectionRun.package_id` is still a bare integer, now declined by two stories in a
      row, and no remaining identity story is a natural home for it.
    evidence: |-
      `CPM-IDENTITY-S01`'s deferred ledger says the `ForeignKey(..., on_delete=PROTECT)`
      conversion "belongs to `CPM-IDENTITY-S06`, the story that first makes packages exist to
      point at", and `core/models.py`'s `CollectionRun` docstring says the same. Packages now
      exist -- this story creates them -- and this story has declined it too, for reasons that
      are sound: it is absent from these acceptance criteria, it changes `core/ledger.py`'s
      recorder contract, it rewrites every existing `core` ledger test that passes a literal
      key for a package no test creates, and it needs a hand-written `RenameField` +
      `AlterField` pair rather than an `AlterField`. `inventory_snapshots` does declare the
      real relation, so `CPM-AD-3` is now met by the first evidence table and unmet only by the
      ledger. Two hand-offs is where a deferral stops being a deferral: this needs a story of
      its own rather than a third nomination.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py -- CollectionRun.package_id
    severity: medium
  - summary: >-
      Resolution finds an existing shell by `canonical_name`, so once `CPM-IDENTITY-S02`
      corrects a name the next sweep creates a duplicate shell and records the original absent.
    evidence: |-
      `resolve_package_shell` looks the package up by the source key written into
      `canonical_name`. `CPM-IDENTITY-S02` exists to correct canonical names, and
      `CPM-IDENTITY-S05` lets a human do it on the record -- after either, the inventory's key
      no longer matches any package, so the next run creates a second shell for the same
      package and `_observe_absences` records the corrected one as departed. Both writes are
      append-only and neither is recoverable. This story now stores the source key in
      `associator_key` as well, which is what a key-based lookup would need, but the lookup
      itself is resolution's shape and belongs to the story that owns correction.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/services.py -- resolve_package_shell
    severity: medium
  - summary: >-
      AC 1's "the source location and its credentials come from the environment with no
      default" is not implemented, and nothing in the new code reads the environment.
    evidence: |-
      The clause predates the resolution of PRD Open Question 3a, which chose an in-repo
      reviewed watchlist over a credentialed remote inventory system -- so for the v1 adapter
      there is no location to configure and no credential to hold, and `CPM-AD-29` selects the
      file by locality instead. The clause binds again the moment a second adapter arrives,
      which OQ-3a explicitly anticipates ("an internal-inventory-system integration, should one
      arrive, is a second adapter behind the same contract"). `CPM-IDENTITY-S07` owns the
      adapter and is where the environment read belongs if its adapter needs one. Recorded
      because the criterion was silently superseded rather than answered.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py -- inventory_adapter
    severity: medium
  - summary: >-
      AC 6's replay property is proven one layer below where the criterion states it -- at the
      query function, not at a policy run -- and nothing binds a reader to that function.
    evidence: |-
      The criterion says "a policy that reads a usage signal ... reads the latest snapshot at
      or before its run's cut-off, and a replay at a stated cut-off reproduces identical
      results". `snapshot_as_of` implements and proves the read, including the `-pk` tie-break
      that makes it deterministic. What does not exist is a policy layer to bind, and no audit
      forbids a future reader calling `.latest()` or `.first()` on `inventory_snapshots`
      directly and getting a cut-off-blind answer. The model docstring calls `snapshot_as_of`
      "the only supported way" to read, which is a claim nothing enforces. The binding belongs
      with `CPM-EP-PRIORITY`, the first epic with a policy pass.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/models.py -- snapshot_as_of
    severity: medium
  - summary: >-
      The evidence `state` column is the first real outcome column in the product and is
      checked by neither mechanism the architecture provides for one.
    evidence: |-
      `EVIDENCE.01-AUDIT-001` sweeps fields named `status`, `outcome`, `*_status` or
      `*_outcome`; this column is named `state`, so the audit never sees it. It also declares
      `OutcomeState.choices` directly rather than a vocabulary composed by
      `core.outcomes.outcome_type`, which that factory's docstring calls "the only supported
      way to mint a per-status enum". Nothing is wrong with the column -- it carries all four
      sentinels because it is `OutcomeState` itself -- but the two guards that exist to keep
      later columns honest both miss it, and `tests/collectors.py`'s fixture model set the
      precedent for the name. Reconciling the convention with the column is worth doing before
      eight collectors copy it.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/models.py -- InventorySnapshot.state
    severity: low
  - summary: >-
      The absence query excludes on an `IN` list holding every key the document named -- ten
      thousand bind parameters on an ordinary run.
    evidence: |-
      `_observe_absences` builds `exclude(source_package_key__in=named)` from the whole
      document. At `CPM-NFR-1`'s ten thousand packages that is a ten-thousand-element `IN`
      clause every sweep: near SQLite's parameter ceiling, and poor for PostgreSQL's planner.
      The complementary read -- latest state per package -- is now a fold in Python because
      `distinct(*fields)` is PostgreSQL-only and the suite runs on SQLite locally. Both are
      correct and neither is slow yet; the fix for both is the same per-package latest-state
      projection, and it belongs with whichever story first has a rollup or a retention window
      to build it from.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py -- InventoryIngestionCollector._observe_absences
    severity: low
  - summary: >-
      `snapshot_as_of` can hand a policy an absence or an error row, and nothing says what a
      usage-signal reader should do with one.
    evidence: |-
      It filters on `package_id` and `observed_at` only, so the latest observation at a cut-off
      may be a `not_found` row whose counts are NULL by construction, or an `error` sentinel.
      A caller reading `internal_component_count` off one of those gets `None` where it expects
      a count. Neither the docstring nor any test states the contract, and there is no
      state-aware variant. `CPM-AD-4`'s confidence gate is the natural place to settle what an
      absent package's usage breadth means, and that is `CPM-IDENTITY-S03`'s.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/models.py -- snapshot_as_of
    severity: low
  - summary: >-
      The record wire contract frozen here carries no package name, though the epic puts one in
      the record `CPM-IDENTITY-S07`'s adapter yields.
    evidence: |-
      `epics.md`'s S07 criteria say each watchlist row "yields a record carrying the source
      package key, the package name, `internal_component_count` and `internal_lob_count`".
      `InventoryRecord` has the key and the counts and no name field, and the shell takes the
      source key as its `canonical_name`. So either S07's adapter drops a column the epic says
      it yields, or this contract widens when S07 lands. Recorded now so S07 finds the
      discrepancy rather than resolving it by accident.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py -- InventoryRecord
    severity: low
---

<intent-contract>

## Intent

**Problem:** Nothing creates packages. `identity.Package` exists but no row is ever written, so
every story after this one has an empty table to work on. The inventory has to arrive, and
`CPM-AD-25` fixes how: as an **observation**, through the shared collector base, written to an
append-only log -- never as a second, unaudited write path onto the package row, and never as
mutable usage columns that silently change what a replayed policy run concludes.

**Approach:** Add a `collectors` application holding the inventory ingestion collector and its own
evidence table `inventory_snapshots`; add the minimal resolution service in `identity` that creates
a package shell at `unmapped` confidence; and give the collector base a run-scoped sweep path,
because one source document yields many packages and some of them have no row yet. Absence is
written as an observation rather than a deletion, and the read policies will use is bound to a
cut-off.

## Boundaries & Constraints

**Always:**

- Ingestion runs **through** the shared collector base and inherits its timeout, retry, backoff,
  rate limit, observation window and run-ledger row. None of those is re-implemented
  (`CPM-AD-20`, `CPM-AD-27`; `tests/unit/django_apps/test_collector_base_audit.py` is the gate).
- The source is reached through the base's **transport seam** and nothing else. `CPM-AD-29` makes
  the inventory adapter a transport substitution at that seam, which is why the collector carries
  no branch on which source is active.
- The collector **never writes the package table**. A source record naming a package that does not
  exist calls `identity`'s resolution service, which is the only creator of a package row
  (`CPM-AD-14`, `CPM-AD-25`). A test asserts the collector module contains no `Package` write.
- The shell and its snapshot commit in **one transaction per package**, nested inside the run
  recorder and never around it (`CPM-AD-23`). A later package's failure never rolls back an earlier
  package's rows; the run ledger records `partial`.
- `inventory_snapshots` inherits `AppendOnlyModel`. Re-observation always inserts; no unique
  constraint of any kind, because idempotency is the run ledger's property and not the evidence
  table's (`CPM-AD-2`, `CPM-AD-7`).
- The package reference is a `ForeignKey("identity.Package", on_delete=models.PROTECT)`. `PROTECT`
  is required of every relation on an evidence model (`EVIDENCE.02-AUDIT-001`): Django's deletion
  collector issues its `DELETE` through `sql.DeleteQuery` and goes past every append-only refusal.
- `observed_at` is the single instant the base reads from the injected `Clock` for the run, handed
  to every row. No `auto_now_add`, no `timezone.now()` (`CPM-AD-26`).
- `trace_id` is taken from `core/ledger.py`'s public `current_trace_id()` at row construction, in
  the `_TRACE_ID_LENGTH`-wide `CharField(blank=True, default="")` shape `CollectionRun` uses
  (`CPM-AD-15`). The product adds no correlation scheme of its own.
- A blank optional signal means **missing**, and stays distinguishable from zero (PRD Appendix A.1
  data rules, Open Question 3b).
- The Celery task is named `cpm.collect.<name>` so `core/queues.py`'s derived route table already
  routes it. Cadence is data in `django_celery_beat`, never a decorator argument (`CPM-AD-20`).
- Every refusal branch is exercised by a real test: `# pragma: no cover` is banned, and so are
  `skip`, `xfail`, `importorskip` and `databases=` on `django_db`.
- `pixi` is the only runner. There is no `cov` task and no `check` task here -- the names are
  `test`, `test-integration`, `test-cov`, `typecheck`, `lint`, `ci`, `gate-postgres`.

**Block If:**

- Giving the base a sweep path cannot be done without changing `Collector.collect`'s existing
  per-package signature or behaviour. Eight later collectors inherit that path; reshaping it for
  this one is not this story's to decide.
- Satisfying an acceptance criterion appears to require the collector to write `Package` directly,
  or to hold one transaction across packages.

**Never:**

- Do **not** choose the inventory source, define the watchlist file format or its columns, write a
  watchlist file, or implement the locality selection rule. All of that is `CPM-IDENTITY-S07`. This
  story ships the collector, the model, the resolution service and the cut-off-bound read.
- Do **not** resolve a mapping. Ingestion never asserts a source repository, a purl, a feedstock or
  a confidence above `unmapped` (`CPM-FR-42`, `CPM-FR-1`). `CPM-IDENTITY-S02` owns resolution.
- Do **not** put a unique constraint, `unique=True`, `unique_together`, `OneToOneField` or
  `unique_for_date`/`_month`/`_year` on the evidence model.
- Do **not** name a field `status`, `outcome`, `*_status` or `*_outcome` unless it is a real
  `OutcomeState`-composed vocabulary built by `core.outcomes.outcome_type`.
- Do **not** add a `computed_at` field -- that name marks derived state in
  `tests/unit/django_apps/test_derived_status_writability_audit.py`.
- Do **not** use `update()`, `bulk_update()`, `update_or_create()`, `_raw_delete` or raw
  `UPDATE`/`DELETE`/upsert SQL anywhere (`EVIDENCE.02-AUDIT-002`). The licensed writes are
  `create()`, `bulk_create(rows)` and `save(update_fields=...)`.
- Do **not** import `config` from anything under `src/django_apps/` (inherited `AD-4`).
- Do **not** add a `pragma`, a coverage omit entry, a `pytest.skip`, or a new dependency.
- No admin, serializers, views or URLs.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First sight of a package | adapter yields a record whose package key matches no `Package` | resolution creates the shell at `confidence="unmapped"` with no mapping set, and one snapshot row is written | No error expected |
| Package already known | adapter yields a record for an existing `Package` | no second `Package` row; one new snapshot referencing the existing pk | No error expected |
| Re-observation | ingestion runs twice over identical source data | two snapshot rows exist for the package; the first is unchanged | No error expected |
| Absence | a package present in an earlier run is absent from this one | a snapshot is written recording absence, carrying this run's `observed_at`; the `Package` row still exists | No error expected |
| Required signals | a record carrying `internal_component_count` and `internal_lob_count` | both are stored as observed | No error expected |
| Optional signals blank | a record whose `apps`, `platforms`, `downloads`, `versions` are absent | the snapshot stores them as missing (NULL), distinguishable from a stored `0` | No error expected |
| Optional signal zero | a record whose `downloads` is `0` | the snapshot stores `0`, and it does not read as missing | No error expected |
| One package fails | the adapter yields three records and the middle one cannot be persisted | the first and third packages keep their rows, the run finalizes `partial`, and the failure is recorded | Per-package rollback only |
| An evidence row is edited | `snapshot.save()` on a row already written, or `queryset.update(...)` | refused | `AppendOnlyError` |
| A package with observations is deleted | `package.delete()` where snapshots reference it | refused by the database | `ProtectedError` |
| Cut-off-bound read | two snapshots for one package at T1 and T2, read at a cut-off between them | the T1 snapshot is returned, and the same cut-off returns it again on a later call | No error expected |
| Cut-off before any observation | a cut-off earlier than the package's first snapshot | no snapshot is returned, and this is not an error | No error expected |
| No adapter declared | the ingestion task runs with no inventory adapter supplied | the run is refused before any row is written | a `ValueError` subclass |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/collection.py:490` -- `Collector`, the
  base. Nine required `ClassVar` declarations at `:531-584` (`name`, `evidence_model`,
  `observation_window`, `timeout`, `retries`, `rate_limit`, `headers`, `freshness_target`,
  `response_cache_ttl`); constructor `:586` takes `clock` plus the `transport`/`limiter`/
  `response_cache` seams; abstract `source_for` `:729`, `translate` `:742`, `sentinel_evidence`
  `:767`; entry point `collect` `:801`; the per-package write `_write_evidence` `:1271` -- the one
  `transaction.atomic()` in the class, and the shape the per-package boundary must keep. **This
  file gains a run-scoped sweep path; its per-package path is read-only.**
- `core/transport.py:359` -- the `Transport` Protocol, one method. `:322` records that
  `Payload.status_code` is `None` "for a transport substituted at this seam that does not [speak
  HTTP] -- the inventory file adapter `CPM-AD-29` describes is the first of those".
  `RequestsTransport`'s `ALLOWED_SCHEMES` `:232` is http/https only, so a file-backed adapter
  **must** be injected at construction.
- `core/ledger.py:117` `current_trace_id()` -- public, never raises, `"032x"` or `""`.
  `collection_run` `:461` -- the recorder; it already accepts `package_id=None` `:466` for a run not
  scoped to one package, which is what a sweep run is. `_require_named` `:139` -- the
  `_require_*(value, *, field)` validator shape to copy.
- `core/models.py:428` `AppendOnlyModel` -- declares `observed_at` `:442`, `objects` `:444` and
  `base_manager_name` `:462`; `save()` refuses at `:465-551`, `delete()` at `:553`. `:714` is the
  `trace_id` column spelling and `:138` its `_TRACE_ID_LENGTH`.
- `core/freshness.py:101` -- `PACKAGE_FIELD = "package_id"` is hard-coded, and
  `_require_package_reference` `:296` raises unless the evidence model declares it;
  `latest_observation` `:238`. A `ForeignKey` named `package` satisfies this through its attname.
- `core/registry.py:89` `register()` -- declared, never discovered; duplicate names refused.
  `src/config/startup/stage_two.py:593` sweeps the registry at boot and refuses a collector with no
  freshness target (`CPM-AD-28`).
- `core/queues.py:93` `Queue`, `:140` `route_pattern`, `:160` `CELERY_TASK_ROUTES` -- derived, not
  hand-edited. A `cpm.collect.*` task name needs no change here.
- `src/django_apps/conda_package_supply_chain_monitor/identity/models.py:126` `IdentityConfidence`
  (`UNMAPPED = "unmapped"`), `:157` `Package`. **The app has no service module yet** -- `:56-58`
  forward-declares one in `core/ledger.py`'s `_require_*` shape.
- `tests/collectors.py:510` `collector_class(...)` and `:566-648` -- the canonical subclass body,
  all nine declarations plus the three methods. Read it before writing the collector. `:227`
  `fixture_evidence_model()` is the evidence-model shape; `:282` `RecordedTransport` and `:972`
  `registered_collector` are the doubles to reuse.
- `tests/unit/test_model_registry.py:285` -- `assert evidence_models() == []`. **Must be edited:**
  this story lands the first evidence model. Its docstring `:268-270`, and the same claim in
  `core/models.py:11-15`, `tests/model_registry.py:55-58` and `:265-268`,
  `tests/unit/django_apps/test_evidence_inheritance_audit.py:194-199` and
  `test_evidence_constraint_audit.py:137-141`, all become false here.
- `tests/unit/django_apps/test_collector_base_audit.py:179` `TRANSACTIONAL_WRITE_MODULES` -- its
  comment says "the day a concrete collector arrives, its module joins this tuple"; `:271`
  `THE_NEW_MODULES` likewise.
- `tests/integration/startup/test_stage_two_collector_registry.py:209` -- asserts
  `registered_collectors() == ()`. Must be edited once the collector registers.
- `tests/unit/test_component_declaration.py:296` and `:517` -- the two frozen `adopted_apps`
  assertions. `src/config/settings/base.py:202` `LOCAL_APPS`; `component.toml:67` `adopted_apps`;
  `tests/model_registry.py:132` `FIRST_PARTY_APP_NAMES`.
- `src/django_apps/conda_package_supply_chain_monitor/identity/apps.py` -- the AppConfig shape. Note
  `core` and `identity` are asserted to declare **no** `ready()`; the new `collectors` AppConfig is
  where `register(...)` belongs.

## Tasks & Acceptance

**Execution:**

- `core/collection.py` -- add a run-scoped sweep path that reuses the base's clock, ledger, window,
  limiter and transport and delegates per-record persistence to the subclass -- because one source
  document yields many packages and `Collector.collect(package_id=...)` cannot express that. Leave
  the per-package path untouched.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/{__init__,apps,models,tasks}.py`
  plus `migrations/` -- new application: `CollectorsConfig` with a `ready()` that registers the
  collector, the `InventorySnapshot` model (`db_table = "inventory_snapshots"`), the ingestion
  collector, and the `cpm.collect.*` task.
- `identity/services.py` -- new. The resolution service's shell-creation entry point: get-or-create
  a `Package` at `unmapped` confidence from a source package key, `resolved_at` from the injected
  clock, inside the caller's transaction. The only creator of a package row.
- `src/config/settings/base.py`, `component.toml` -- both halves of the adoption, appended after
  `identity`.
- `tests/unit/test_component_declaration.py`, `tests/model_registry.py` -- the frozen adoption
  tables.
- `tests/unit/test_model_registry.py` -- replace `evidence_models() == []` with an assertion naming
  `InventorySnapshot`, in the shape line `:286` already uses for the run ledger, and correct the
  docstring.
- `core/models.py`, `tests/model_registry.py`,
  `tests/unit/django_apps/test_evidence_inheritance_audit.py`,
  `tests/unit/django_apps/test_evidence_constraint_audit.py` -- prose only: the five places that say
  no evidence model exists yet, or that `CPM-EP-CURRENCY` lands the first one.
- `tests/unit/django_apps/test_collector_base_audit.py` -- add the new collector module to
  `TRANSACTIONAL_WRITE_MODULES` and `THE_NEW_MODULES`.
- `tests/integration/startup/test_stage_two_collector_registry.py` -- the registry is no longer
  empty.
- `tests/unit/django_apps/test_inventory_ingestion.py` -- new; the collector's declarations, the
  no-`Package`-write assertion, the refusal when no adapter is declared, and the sweep's shape. No
  database.
- `tests/unit/django_apps/test_identity_services.py` -- new; the shell-creation contract.
- `tests/integration/django_apps/test_inventory_ingestion.py` -- new; every matrix row needing a
  real table, each `@pytest.mark.django_db`.

**Acceptance Criteria:**

1. Given the ingestion collector class, when its declarations are read, then it declares all nine of
   the base's required `ClassVar`s including a strictly positive `freshness_target`, its
   `evidence_model` is `InventorySnapshot`, and it appears in `core.registry.registered_collectors()`.
2. Given a boot of a serving process, when `stage_two`'s collector sweep runs, then it finds the
   registered collector and does not refuse it (`CPM-AD-28`).
3. Given the collector module's source, when it is swept, then it contains no write to
   `identity.Package` and no `transaction.atomic()` spanning more than one package.
4. Given a completed sweep, when the run ledger is read, then exactly one `CollectionRun` row exists
   for the run, it is finalized rather than left `running`, and its `package_id` is NULL because the
   run was not scoped to one package.
5. Given the Celery task, when the routing audit runs, then the task name resolves to the `collect`
   queue with no edit to `core/queues.py`, and the task declares no schedule and no time limit.
6. Given `InventorySnapshot`, when the registry audits sweep it, then it is classified as evidence,
   carries no unique constraint, its only relation is `PROTECT`, and it takes no `not_evidence`
   escape.

## Spec Change Log

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 21: (high 3, medium 9, low 9)
- defer: 9: (high 0, medium 4, low 5)
- reject: 11: (high 0, medium 2, low 9)
- addressed_findings:
  - `[high]` `[patch]` A well-formed but empty document marked the entire inventory absent and
    reported success. `persist_sweep` counted absence rows toward `evidence_rows`, so the base's
    "produced no rows" guard never fired once history existed — reproduced by a reviewer in the
    worktree as `state=succeeded, states=['ok','not_found']`. Fixed in three places: `records_in`
    refuses an empty array, `SweepOutcome` splits `observed_rows` from `derived_rows` so the
    terminal decision reads only what the source's records produced, and the collector declines to
    derive absences from a run that observed nothing. The regression case asserts both that the
    run fails and that no absence row exists.
  - `[high]` `[patch]` `test_a_package_the_source_still_names_is_never_recorded_absent` could not
    fail: its failing key never had an `ok` observation, so it never entered the absence query
    under either implementation. Rewritten so the failing package already has one, via a
    collector double — under the `named={persisted}` inversion the docstring warns about, the
    case now fails.
  - `[high]` `[patch]` The sweep path bypassed the invariants the per-package path enforces —
    declared-model and `observed_at` stamping checks — and trusted a row count the subclass
    reported. `SweepOutcome(evidence_rows=99)` over zero writes would have finalized a successful
    run. Sweep rows now go through `_write_evidence`, which gained a declared-model check and a
    per-run tally reconciled against the reported count, with four deviation fixtures.
  - `[medium]` `[patch]` The freshness target was 1 day against a daily cadence. OQ-7 resolved
    mid-build (`27f20f0`) and fixes the rule: a target must be strictly greater than its cadence,
    or evidence goes stale exactly when the next run is due. Now 2 days, derived, with the rule
    asserted against the cadence rather than the literal.
  - `[medium]` `[patch]` The shared freshness read was never exercised against `InventorySnapshot`
    — the first evidence model whose package reference is a `ForeignKey` rather than a literal
    `package_id`. `_require_package_reference`'s `attname` arm exists for exactly this moment and
    was unpinned.
  - `[medium]` `[patch]` The `trace_id` test was vacuous: outside a span both sides were `""`. Now
    asserted against a real recording span and a non-empty `032x` id.
  - `[medium]` `[patch]` An over-long key produced a `partial` run with rows written rather than
    the whole-document refusal `CPM-FR-42` promises. Key length moved into the record contract.
  - `[medium]` `[patch]` A departed package was re-observed absent on every later run forever, in
    a table nothing may prune. Absence is now recorded on the transition, with a re-appearance
    case so the rule is not "has ever been absent".
  - `[medium]` `[patch]` The shell recorded no provenance — `identity_source` and `associator_key`
    left blank, so the inventory's own key survived only as `canonical_name`, which S02 exists to
    correct. Both are now set from what ingestion knows.
  - `[medium]` `[patch]` `_refuse_repeated_keys` was O(n²) — `keys.count()` inside a comprehension,
    ~10⁸ comparisons at ten thousand packages. Now `Counter`.
  - `[medium]` `[patch]` `_require_count` accepted integers above `PositiveIntegerField`'s ceiling,
    which store on SQLite and are refused by PostgreSQL — the same parity gap negatives were
    already guarded for. Now reconciled against `connection.ops.integer_field_range`.
  - `[medium]` `[patch]` `InventorySnapshot` declared no indexes, though two access paths filter
    and order on unindexed columns. Two named indexes, folded into the initial migration.
  - `[low]` `[patch]` Nine smaller ones: idempotent collector registration (a second `ready()`
    aborted startup); the `-pk` tie-break pinned by a same-instant case; `sweep()`'s hook refusal
    driven through `sweep()` rather than the hooks, asserting the allowance was not spent;
    `sweeping_collector_class` honouring its `declared_model`; `not_modified` refused explicitly;
    `partial` given its own log event rather than sharing the failure one; the collector's ad-hoc
    log event removed in favour of the base's; `test_outcome_field_audit.py`'s stale docstring and
    missing anti-vacuity guard; and a cluster of contract/annotation corrections including the
    removal of a blanket `type: ignore[arg-type]`.

## Design Notes

**`InventorySnapshot`'s fields.** PRD Appendix A.2's row for `inventory_snapshots`, plus what
`CPM-AD-15` and the base require. `observed_at` and `objects` come from `AppendOnlyModel`.

| Field | Shape | Why |
|---|---|---|
| `package` | `ForeignKey(Package, PROTECT, related_name="inventory_snapshots")` | `CPM-AD-3` integer pk; `PROTECT` per `EVIDENCE.02-AUDIT-001` |
| `source_package_key` | `CharField(max_length=_KEY_LENGTH)` | the source's own key, kept so a record can be traced back to its row |
| `state` | `CharField(max_length=_STATE_LENGTH, choices=OutcomeState.choices)` | `ok` when the source listed the package, `not_found` when it did not -- absence as an observation |
| `internal_component_count` | `PositiveIntegerField(null=True, blank=True, default=None)` | required *of a present observation*, enforced by constraint rather than by column, because an absence row observes no counts |
| `internal_lob_count` | same | same |
| `apps`, `platforms`, `downloads`, `versions` | `PositiveIntegerField(null=True, blank=True, default=None)` | Open Question 3b: nullable score inputs; NULL means missing and stays distinct from `0` |
| `detail` | `TextField(blank=True, default="")` | the sentinel path's reason; empty on an ordinary observation |
| `trace_id` | `CharField(max_length=32, blank=True, default="")` | `CPM-AD-15`, the `CollectionRun` spelling |

`Meta.constraints` carries a `CheckConstraint` requiring both counts to be non-NULL exactly when
`state` is `ok`, so "required on every record" is enforced where it is true and not where it is
not. A `CheckConstraint` is permitted on an evidence model; a `UniqueConstraint` is not.

**Presence is `state`, not a boolean.** `CPM-AD-5` bans boolean status fields, and the base's
`sentinel_evidence` hook requires the row to carry the `OutcomeState` value verbatim in a concrete
field -- so absence is already expressible as `not_found` through machinery the base owns. A
`present = BooleanField()` would be a second vocabulary for the same fact and would put this model
outside the sentinel path. `tests/collectors.py:227`'s fixture model uses exactly this `state`
shape.

**The nine declarations, and why each value.** The base refuses a missing or ill-typed one at
construction, so these are not defaults to be discovered.

| Declaration | Value | Why |
|---|---|---|
| `name` | `"inventory"` | keys the ledger rows and the rate-limit cache entry |
| `evidence_model` | `InventorySnapshot` | must subclass `AppendOnlyModel` |
| `observation_window` | `NO_WINDOW` | a sweep that is asked to run has been scheduled to run; suppressing it would suppress the absence observations too, and absence is the signal that decays |
| `timeout` | `30.0` | required and capped at `MAX_TIMEOUT`; meaningless for a file adapter, which is why it takes the cap rather than a number pretending to be measured |
| `retries` | `0` | a malformed or missing local file does not become well-formed on a second read; `CPM-IDENTITY-S07` refuses it outright |
| `rate_limit` | `RateLimit(calls=60, per=timedelta(seconds=60))` | the base makes no opt-out available; a generous declared allowance is the honest form for a source that is not rate-limited |
| `headers` | the default empty mapping | a file adapter ignores them |
| `freshness_target` | `timedelta(days=1)` | mandatory and strictly positive (`CPM-AD-28`); the value is provisional against Open Question 7 -- see below |
| `response_cache_ttl` | `NO_CACHE` | short-circuits the cache read, the write and the conditional headers, so no `ETag` machinery runs against a source that has no validators |

**The sweep path is the one structural decision, and the acceptance criteria force it.** The base is
per-package by construction: `collect(*, package_id: int)` asks `source_for(package_id)`, keys the
observation window on `(collector, package_id)`, and writes one package's rows in one transaction.
Inventory ingestion reads **one** document that yields **many** packages, and the packages it names
may have no row yet -- so there is no `package_id` to pass. Three readings were available and two
are excluded by the story's own text: ingesting outside the base is refused by AC 1 ("through the
shared collector base, inheriting its timeout, retry, backoff and ledger row"), and looping
`collect()` over already-known packages is refused by AC 2 (a record naming a package that does not
exist yet must still be ingested). What remains is a run-scoped path in the base, which
`core/ledger.py:466` already anticipates by accepting `package_id=None` for a run not scoped to one
package. The per-package path is left exactly as it is, because eight later collectors inherit it.

**Where the collector and its table live.** A new `collectors` application -- not `identity`, and
not a shared `evidence` app. `CPM-AD-7` says a collector writes its own evidence table and reads
only `identity`; the capability map in the architecture spine assigns `CPM-EP-IDENTITY` to
`django_apps/identity` **and** `collectors`; and `tests/model_registry.py:35-38` records that an
`app_label == "evidence"` table is "the shape `CPM-AD-7` least expects". Putting
`inventory_snapshots` in `identity` would also put an evidence table inside the app that owns the
mutable package row, which is the confusion `CPM-AD-25` exists to prevent.

**The resolution service is built here, minimally.** AC 2 requires `identity`'s resolution service to
create the shell, and no such module exists. This story adds only the shell-creation entry point --
get-or-create at `unmapped`, asserting no mapping -- because `CPM-AD-25` says the shell is "written
by `identity`'s resolution service, not by the collector that triggered it". `CPM-IDENTITY-S02` adds
real resolution behind the same door. It is a domain service, so its refusals are a `ValueError`
subclass in the house shape; `ImproperlyConfigured` is reserved for the two startup stages.

**The adapter is `CPM-IDENTITY-S07`'s, and the seam is the base's transport.** `CPM-AD-29` makes an
inventory source "a transport substitution at the collector base's seam", which is why this
collector carries no branch on which source is active and why the seam needs no new protocol --
`core/transport.py:359`'s `Transport` already is it. This story's tests drive the collector through
an injected test adapter; the task obtains its adapter from one declared point and refuses when none
is declared, which is a real branch with a real test. S07 declares the watchlist adapter, its
columns, its refusals and the locality selection rule. The `config.locality` import problem
`CPM-AD-29` raises is S07's to solve, because S07 owns the selection.

**The freshness target's value is provisional.** `CPM-AD-28` makes a target mandatory, and PRD Open
Question 7 leaves the *values* undecided -- this is the first collector to ship, which is the moment
OQ-7 said its answer would be needed. A daily target matches the PRD's "daily sweep over ten
thousand packages"; it is a number to revisit when OQ-7 is answered, not a finding. Recorded as
deferred rather than silently chosen.

**Absence is a row, not a deletion.** `CPM-AD-25`: "A package present in an earlier run and absent
from a later one is recorded as absent with a timestamp. No package row is ever deleted." So the
snapshot carries presence as data and the absence row is an ordinary append. Nothing in this story
deletes anything.

## Verification

**Commands:**

- `pixi run test` -- expected: exits 0.
- `pixi run test-integration` -- expected: exits 0, no new skips.
- `pixi run ci` -- expected: exits 0 through precommit, build, typecheck, lint and test-cov, with
  coverage at or above 90%.
- `pixi run gate-postgres` -- expected: exits 0 with nothing skipped. `PROTECT` and the NOT NULL
  columns are database-enforced, so they are only genuinely proven against `postgres:17`.

## Auto Run Result

Status: done

**What was implemented.** The inventory arrives, and it arrives as evidence. A new `collectors`
application holds the ingestion collector and `inventory_snapshots` — the first concrete evidence
model in the product, and the first table to prove `AppendOnlyModel`'s refusals and a `PROTECT`
relation against a migrated schema rather than a fixture. `identity/services.py` adds the shell
creation `CPM-AD-25` reserves to resolution, so the collector never writes the package table.
`core/collection.py` gained a run-scoped sweep path, because one document yields many packages and
the packages it names may have no row yet — the per-package path eight later collectors inherit is
untouched.

**Files changed.**

- `collectors/models.py` — new. `InventorySnapshot`, the check constraint making both counts
  present exactly when the observation is `ok`, two named indexes, and `snapshot_as_of`, the
  cut-off-bound read with the `-pk` tie-break that makes a replay deterministic.
- `collectors/tasks.py` — new. The ingestion collector and its nine declarations, the declared
  adapter slot, the record contract, per-package transactions, absence-on-transition, and
  `cpm.collect.inventory`.
- `collectors/apps.py`, `__init__.py`, `migrations/` — new. The first adopted app with a `ready()`,
  which is where `CPM-AD-28`'s registration belongs.
- `identity/services.py` — new. `resolve_package_shell`: get-or-create at `unmapped`, provenance
  recorded, no mapping asserted.
- `core/collection.py` — the sweep path, and `_write_evidence` widened to check the declared model
  and reconcile a reported row count against what it actually wrote.
- `config/settings/base.py`, `component.toml` — the two halves of the adoption.
- `tests/model_registry.py`, `tests/unit/test_model_registry.py`, `test_component_declaration.py`,
  `test_collector_base_audit.py`, `test_evidence_inheritance_audit.py`,
  `test_evidence_constraint_audit.py`, `test_outcome_field_audit.py`,
  `test_stage_two_collector_registry.py`, `test_identity_app.py`, `tests/collectors.py`,
  `test_collection.py` — the frozen tables and the five prose sites that said no evidence model
  existed yet.
- Three new test modules: unit inventory ingestion, unit identity services, integration inventory
  ingestion.

**Review findings:** 21 patched (3 high, 9 medium, 9 low), 9 deferred, 11 rejected. Four review
layers ran in parallel over the full 4,739-line diff.

**Follow-up review recommended:** true. Three high-severity patches; any one fires the rule.

**The finding that mattered most was a permanent, silent data corruption.** A well-formed but empty
document — a truncated file, a source that changed shape — marked every package in the inventory
absent and reported the run a success. `persist_sweep` counted absence rows toward the total the
base reads to decide whether a document produced anything, so the guard meant to catch exactly this
never fired once the table had history. The test that was supposed to cover it passed only because
it ran against an empty database, and the module docstring stated the harm it was not preventing.
A reviewer reproduced it in the worktree. This is the failure `CPM-AD-29` names as the reason
locality must fail closed toward production: absence is an observation, the log is append-only, and
a false absence is permanent and replayable. Two more of the same shape followed — a test that
could not fail whichever way the rule was implemented, and a sweep path that trusted a row count
its subclass reported.

**Verification.** `pixi run ci` exits 0 — 3462 passed, 2 pre-existing skips, coverage 98.09%
against a 90% floor, 100% on every module this story touches. `pixi run gate-postgres` exits 0
against a throwaway `postgres:17` with nothing newly skipped, which is where `PROTECT`, the check
constraint and the integer ceiling are genuinely enforced rather than asserted. All thirteen I/O
matrix rows have a covering test that ran and passed.

**Residual risks.** The nine `deferred` entries. Three matter. `resolve_package_shell` finds an
existing shell by `canonical_name`, so the moment `CPM-IDENTITY-S02` or `-S05` corrects a name, the
next sweep creates a duplicate shell and records the original as departed — both writes append-only
and neither recoverable. AC 1's "source location and credentials from the environment with no
default" is unimplemented, superseded rather than answered by OQ-3a's choice of an in-repo
watchlist; it binds again for a second adapter. And `CollectionRun.package_id` has now been
declined by two stories in a row: the reasoning is sound each time, but two hand-offs is where a
deferral stops being one, and it needs a story of its own rather than a third nomination.
