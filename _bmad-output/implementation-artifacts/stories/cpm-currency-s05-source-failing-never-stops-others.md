---
title: 'CPM-CURRENCY-S05: One source failing never stops the others'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '6a081c7494d2fa633214cf3bf1dd916457298fc8'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s01-upstream-release-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s02-pypi-release-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s03-feedstock-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s04-published-conda-package-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s04-three-queues-cadence-as-data.md
warnings:
  - oversized
deferred:
  - summary: >-
      Stage two's two collector conditions still evaluate an empty registry in a
      deployed process; the enforcement that fires there is the collectors app's own.
    evidence: |-
      `config/startup/stage_two.py` is invoked from `django_service.users`'
      `AppConfig.ready()`, and `tests/unit/startup/test_installed_apps_ordering.py`
      requires every adopted application to be installed *after* that owner -- so in a
      real boot `registered_collectors()` is empty when conditions 10 and 11 run, and
      both return without checking anything. That is now *closed* rather than only
      recorded: `CollectorsConfig.ready()` calls the same two public rules immediately
      after it registers, and
      `tests/integration/startup/test_collector_boot_refusal.py` boots a child process
      with a deliberately mismatched interval and asserts it does not start. What is
      still deferred is the ordering itself -- the two stage-two conditions remain
      suite-only in a deployed process, which is a property of the inherited
      invocation point (`CPM-EVIDENCE-S06` shipped condition 10 with it) rather than of
      either rule, and it is why condition 11's backward direction must skip an empty
      registry rather than refuse over it. Moving the collector sweep to a later hook
      is a change to the platform's stage-two ordering.
    location: >-
      src/config/startup/stage_two.py -- _refuse_unreconciled_cadence
    severity: low
  - summary: >-
      The declared allowances still do not sweep `CPM-NFR-1`'s ten thousand packages,
      and now something schedules them.
    evidence: |-
      Every one of the four collectors recorded this: GitHub's anonymous sixty an hour
      is roughly fifteen packages an hour, GitHub's search allowance is two packages a
      minute, PyPI's declared courtesy bound is fifteen a minute and anaconda.org's is
      seven. At those rates none of the four observes ten thousand packages inside its
      declared cadence. The dispatch does not change the arithmetic -- it enqueues the
      work and the per-collector limiter refuses the calls it cannot afford, which
      writes `error` rows rather than exceeding a source's budget -- but it does change
      the exposure from latent to live, which is exactly what those four entries said
      would happen here. Raising the allowances means authenticating, which needs a
      credential, a settings key and a declared header, and none of the three is this
      story's. `docs/deployment.md` states the arithmetic for an operator.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/sweep.py -- dispatch
    severity: high
  - summary: >-
      A dispatch that is retried re-enqueues every package it already enqueued.
    evidence: |-
      `apply_async` is not idempotent and the dispatch keeps no record of which
      packages it offered, so a `cpm.collect.sweep` message redelivered after a worker
      restart -- or retried by a policy somebody adds -- enqueues the whole selection
      a second time. Three things bound the cost: every enqueued message now expires at
      one cadence, a dispatch whose previous run is still `running` records `skipped`
      rather than offering again, and the observation window makes each duplicated
      collection a `skipped` run with no evidence row. So what is left is a duplicated
      queue depth within one cadence, not duplicated evidence. Nothing declares
      `autoretry_for` and `acks_late` is not set, so redelivery is not reachable in
      this tree; making the dispatch itself idempotent needs a durable record of what
      one tick offered, which is a table this story does not add.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/sweep.py -- dispatch
    severity: low
  - summary: >-
      The `conda_package` sweep observes nothing at all until an operator declares
      channels and platforms, and only the dispatch row says so.
    evidence: |-
      `CPM_MONITORED_CHANNELS` and `CPM_MONITORED_PLATFORMS` ship empty (PRD Open
      Question 4, `CPM-CURRENCY-S04`'s Block If), and `CondaPackageCollector.source_for`
      refuses on an empty declaration for every package equally. The selection now
      answers with an empty queryset in that state rather than the whole inventory, so
      a scheduled sweep of an undeclared component records one `succeeded` dispatch row
      saying nothing was selectable instead of one `failed` collection per package per
      day -- which is what the shipped settings would otherwise have produced out of
      the box. What is still deferred is that the *only* signal is that one row: a
      component silently observing no conda surface reads, from
      `conda_package_snapshots`, exactly like one whose channels serve nothing. A
      louder signal is a read surface's (`CPM-CURRENCY-S06`) or an operator's
      monitoring, and answering Open Question 4 here would be this story choosing a
      channel by the back door.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py -- selectable_packages
    severity: medium
  - summary: >-
      The `source_release` selection reads `Package.source_repository_url` and not the
      mapping outcome beside it, so it cannot tell "not applicable" from "unresolved".
    evidence: |-
      `CPM-CURRENCY-S01` recorded this against `source_for` and it is inherited by the
      selection built on it: `MAPPED_FIELDS[SOURCE_REPOSITORY]` makes the URL the whole
      of what an `established` mapping records, so a non-blank URL *is* an established
      source repository -- but a *blank* one is `unknown`, `not_found`, `not_applicable`
      and `error` collapsed into one value. The selection is right either way today,
      because all four are packages this collector refuses; what it cannot do is what
      the PyPI and feedstock selections do, which is offer the `not_applicable` ones so
      the base writes the row `CPM-FR-6` asks for. Closing it means this collector
      growing an `inapplicability` hook over the `source_repository` mapping, which is
      a change to a shipped collector's observations rather than to its selection.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py -- selectable_packages
    severity: low
  - summary: >-
      An `established` release-ecosystem mapping with a blank primary type is selected
      and then refused, so a contradictory identity row costs one `failed` run a day.
    evidence: |-
      `CPM-CURRENCY-S02`'s review made `source_for` refuse that combination rather than
      record it as `not_applicable`, on the reasoning that it is an identity row
      contradicting itself. The selection follows the spec's matrix exactly --
      `established` or `not_applicable` -- so such a package is offered and its run
      fails naming the contradiction. That is the deliberate reading: a `failed` ledger
      row naming the row is how the contradiction surfaces, where excluding it from the
      selection would hide an identity defect behind a sweep that quietly skipped the
      package. The same argument covers `feedstock`'s `not_found`-with-rows
      contradiction. It is recorded because the cost is now recurring rather than
      hypothetical -- one failed run per cadence, for ever, until identity is corrected.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/pypi_release.py -- selectable_packages
    severity: low
  - summary: >-
      Nothing proves a `cpm.collect.*` message really reaches a worker, so the dispatch
      is asserted against a substituted enqueue and never against a broker.
    evidence: |-
      `CPM-EVIDENCE-S04` recorded this for routing and it now binds the dispatch too:
      `CELERY_TASK_ALWAYS_EAGER` is on for the whole suite, so an unsubstituted
      `apply_async` *runs* the task rather than publishing it -- which is why every
      case about what a dispatch offered substitutes the enqueue. The reconciliation
      against `app.amqp.router` is the strongest available substitute for the routing
      half, and there is no substitute at all for "the worker drained it and ran it".
      `tests/integration/test_celery_log_correlation.py` is the one fixture that turns
      eager off and really publishes, and extending it to a dispatch needs a broker in
      the gate.
    location: >-
      tests/integration/django_apps/test_sweep.py -- _enqueue_recorded
    severity: medium
  - summary: >-
      The reconciliation reads the settings declaration rather than
      `django_celery_beat`'s tables, so a schedule contributed at deploy time or edited
      directly in the database is checked by nothing.
    evidence: |-
      Reading the tables at boot would be a query on a path `CPM-NFR-1` keeps free of
      them, and the installed scheduler rewrites these four entries from settings on
      every beat start, so the window in which a database-side edit is live is bounded
      by the next beat restart rather than by anything this product controls. The check
      is worth having against the artefact an engineer edits; the artefact an operator
      edits needs a different mechanism.
    location: >-
      src/config/startup/stage_two.py -- _refuse_unreconciled_cadence
    severity: medium
  - summary: >-
      A dispatch of ten thousand packages is ten thousand sequential broker round trips
      inside one task, and nothing has measured that against the inherited soft limit.
    evidence: |-
      Celery offers no batch publish on this path, so the dispatch publishes one at a
      time; the soft-limit signal is now handled honestly rather than swallowed, but a
      sweep that reaches it still enqueues only part of its inventory and reports
      `partial` every tick. Measuring it needs a broker and an inventory at
      `CPM-NFR-1` scale, neither of which exists yet; the mitigation if it does not fit
      is a continuation cursor per chunk rather than a longer limit, which `CPM-AD-9`
      would otherwise forbid.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/sweep.py -- dispatch
    severity: medium
---

# CPM-CURRENCY-S05: One source failing never stops the others

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

<intent-contract>

## Story

As a platform lead,
I want a full-inventory sweep to survive a failing source,
so that one rate-limited provider does not cost me a day of monitoring everywhere else.

## Acceptance Criteria

1. **Given** a full sweep across 10,000 packages
   **When** one collector fails for some packages
   **Then** every other collector's run is unaffected and the overall run reports `partial`, not `failed`

2. **Given** a sweep in progress
   **When** a package fails partway through
   **Then** the transaction boundary is one package, and no earlier package's evidence is rolled back

3. **Given** the same collector, package, source and observation window
   **When** the run is repeated
   **Then** it does not duplicate evidence

4. **Given** 10,000 packages
   **When** the sweep is scheduled
   **Then** it completes without manual batching

## Intent

**Problem:** Four collectors exist and nothing runs them. Every one of them has recorded the
same three deferred items: nothing selects the packages it can be asked about, so a sweep
today would fail every run for packages whose identity is unresolved; no cadence entry exists,
so the freshness targets are derived from a number nothing schedules; and no sweep exists at
all, so `CPM-NFR-1`'s ten thousand packages have never been collected.

**Approach:** One dispatch task per collector, fired by `django_celery_beat` at the cadence
that collector declares. A dispatch selects the packages its collector can answer about and
enqueues one existing per-package collection task each, in chunks, so the atomic unit stays
one package (`CPM-AD-23`) and no task holds ten thousand packages. Selection is the
collector's own knowledge, declared on the collector through one additive defaulted hook, and
the cadence becomes a declaration the boot sweep reconciles against the schedule.

## Boundaries & Constraints

**Always:**
- A dispatch never collects. It selects and enqueues; every observation is still written by
  the per-package task through the collector base, so every guarantee those four stories
  built holds unchanged.
- One dispatch per collector, so one collector's dispatch failing leaves every other
  collector's untouched (AC 1). A package's collection failing is its own task and its own
  ledger row, so it cannot roll back another package's evidence (AC 2).
- A dispatch that enqueued some of its packages and not all records `partial`, never
  `failed`. `failed` is for a dispatch that enqueued none.
- A dispatch never holds the whole inventory in memory and never materialises ten thousand
  ids in one list: selection is streamed and enqueued in declared chunks (AC 4).
- Which packages a collector can be asked about is the **collector's** knowledge, declared on
  the collector. No module holds a table of per-collector preconditions.
- Cadence is data (`CPM-AD-20`): every schedule lives in `CELERY_BEAT_SCHEDULE`, never in a
  decorator, and a collector's declared cadence and its schedule entry are reconciled at boot
  rather than left to whoever edits one of them.
- Idempotency is the observation window's, already built (`CPM-AD-7`). This story asserts it
  across a dispatch rather than reimplementing it (AC 3).
- Time comes from the injected clock; nothing calls `timezone.now()`.
- `pixi` is the only runner; `pixi run ci` exits 0 at the end.

**Block If:**
- Making the sweep work would require a collector to collect more than one package inside one
  task, or to hold a transaction across packages. `CPM-AD-23` forbids both and this story
  will not trade them for throughput. HALT rather than widen the atomic unit.

**Never:**
- No new evidence table, no new evidence row shape, and no change to what any of the four
  collectors observes or records.
- No change to `core/freshness.py`, `OutcomeState`, `identity`'s writers, or the run ledger's
  own contract.
- No `@shared_task` carrying a schedule, a `run_every`, or a time limit
  (`test_task_declaration_audit.py` enforces this).
- No cadence *value* invented here beyond the one each collector already declares as the
  number its freshness target was derived from.
- No answer to which channels or platforms are monitored (PRD Open Question 4) and no answer
  to the inventory's content: a dispatch selects from whatever the inventory holds.
- No retry storm: a dispatch enqueues, it does not wait, poll, or chain.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Ordinary dispatch | a collector with a selection and 3 selectable packages | 3 per-package tasks enqueued under that collector's task name, each carrying one `package_id`; one run-ledger row scoped to no package recording `succeeded` and how many were enqueued | No error |
| Nothing selectable | the collector's selection matches no package | `succeeded` with zero enqueued, and a `detail` saying the selection was empty rather than that the sweep failed | An empty inventory is not a failure |
| Some packages cannot be enqueued (AC 1) | the broker refuses for 2 of 5 | 3 enqueued, ledger `partial`, `detail` naming how many and why; the 3 that were enqueued stay enqueued | `CPM-FR-15`'s partial success |
| No package can be enqueued | the broker refuses every one | ledger `failed`, `detail` naming the reason | Nothing was dispatched |
| One collector's dispatch fails (AC 1) | two collectors dispatched; the first raises | the second collector's dispatch runs and records its own row; neither ledger row mentions the other | One dispatch per collector is what makes this structural |
| A package's collection fails (AC 2) | one enqueued task raises | that package's ledger row is `failed` and its evidence is whatever the collector wrote; every other package's rows are committed | Per-package task, per-package transaction |
| Repeat inside the window (AC 3) | the same dispatch runs twice inside the collectors' observation windows | the second dispatch enqueues the same packages, and each per-package run records `skipped` with no evidence row; the evidence count is unchanged | The window, already built |
| Ten thousand packages (AC 4) | 10,000 selectable packages | every one is enqueued, in chunks, with no manual batching by an operator, and the dispatch never materialises them all at once | Streamed selection |
| Collector with no selection | a run-scoped collector such as inventory ingestion | never dispatched per package; the dispatch refuses it by name with a message saying it is not a per-package collector | Refused, not silently skipped |
| Collector not registered | a dispatch named for a collector nothing registered | `SweepDispatchError` (a `ValueError`); ledger `failed`; nothing enqueued | Refused |
| No task for a collector | a registered per-package collector whose task name is not in the Celery registry | `SweepDispatchError`; ledger `failed`; nothing enqueued | A dispatch never invents a task name it cannot find |
| Selection preconditions | `source_release` offered only packages with an established source repository; `pypi_release` only those whose release-ecosystem mapping is `established` or `not_applicable`; `feedstock` only those whose feedstock mapping is `established`, `not_found` or `not_applicable`; `conda_package` every package | each collector's dispatch enqueues exactly its own selectable set, and a package the collector would refuse is never enqueued | This is what stops a sweep failing every run |
| Cadence and schedule disagree | a collector declares a cadence the beat entry does not match | `ImproperlyConfigured` at boot naming both numbers | `CPM-AD-20`'s reconciliation |
| Target not greater than cadence | a collector whose freshness target is at or below its cadence | `ImproperlyConfigured` at boot | Evidence would read stale exactly when its next run is due |
| Schedule entry with no collector | a beat entry naming a collector nothing registered | `ImproperlyConfigured` at boot | The reconciliation runs in both directions |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/collection.py` -- add **one**
  additive, defaulted hook, on the terms `inapplicability` (`CPM-CURRENCY-S02`) and
  `sentinel_evidence_rows` (`CPM-CURRENCY-S04`) were added: `selectable_packages()`
  returning an iterable of package ids, defaulting to `None` meaning "this collector is not
  swept per package". Add one declared `ClassVar`, `cadence: timedelta | None = None`, and
  a `require_cadence`-style refusal beside `require_freshness_target` used by the boot sweep.
  Nothing else in the base changes; `collect()` is untouched.
- `src/django_apps/conda_package_supply_chain_monitor/core/registry.py` --
  `registered_collectors()` and `registrations()` are what a dispatch and the boot sweep walk.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py`,
  `pypi_release.py`, `feedstock.py`, `conda_package.py` -- each gains `cadence` as a class
  declaration (bound to the module constant it already has, so no number moves) and an
  override of `selectable_packages()` expressing the precondition its own story recorded as
  deferred. Read each module's `source_for` refusals: the selection is exactly the set those
  refusals would not reject. Nothing else in these modules changes.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/sweep.py` -- **new**. The
  dispatch: resolve the collector by name from the registry, refuse one with no selection,
  derive its task name as `cpm.collect.<name>` and refuse one Celery does not hold, open the
  run recorder with no package (`core/ledger.py` accepts `package_id=None`), stream the
  selection in chunks, enqueue one task per package, and finalize `succeeded`, `partial` or
  `failed` on the counts. Declared chunk size as a module constant with its reasoning.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` -- the four
  per-package tasks are what a dispatch enqueues; add `cpm.collect.sweep` taking a collector
  name. `core/queues.py` routes it to `collect` by its prefix with no edit.
- `src/config/settings/base.py` -- `CELERY_BEAT_SCHEDULER` is already the database
  scheduler at line ~582 and `CELERY_BEAT_SCHEDULE` does not exist. Add it: one entry per
  per-package collector, each firing `cpm.collect.sweep` with that collector's name at that
  collector's declared cadence.
- `src/config/startup/stage_two.py` -- `_refuse_collector_without_freshness_target` is the
  template and the place `CPM-CURRENCY-S01` said this check belongs: extend the same sweep to
  reconcile each registered collector's declared cadence against its schedule entry, in both
  directions, and to refuse a freshness target that is not strictly greater than its cadence.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/selection.py` -- read only,
  and **not** this: it ranks unresolved packages for identity review (`CPM-IDENTITY-S04`).
  Its `_SNAPSHOT_CHUNK` is the precedent for chunked reads over the inventory.
- `src/django_apps/conda_package_supply_chain_monitor/identity/models.py` -- read only.
  `Package`, `PackageMapping`, `MappingKind`, `ESTABLISHED`; `Package.source_repository_url`.
- `tests/unit/django_apps/test_task_declaration_audit.py` -- the audit that forbids a
  schedule in a decorator and permits one under `config/settings/`; the new entries must
  satisfy it. `tests/unit/test_settings.py` reads all four settings modules for a cadence.
- `tests/unit/django_apps/test_task_routing_audit.py` -- `cpm.collect.sweep` must route to
  the `collect` queue.
- `tests/integration/startup/test_stage_two_collector_registry.py` -- where the boot sweep's
  refusals are proved against the real roster.
- `tests/collectors.py` -- the fixture collector factory; it will need a selectable variant
  and one that declares a cadence.
- `docs/deployment.md` -- the four collector sections; add what an operator has to know about
  the sweep: what beat fires, what a dispatch does and does not do, what `partial` means on a
  dispatch row, and that the schedule and the collectors are reconciled at boot.

## Tasks & Acceptance

**Execution:**
- `core/collection.py` -- the `selectable_packages` hook, the `cadence` declaration and its
  refusal helper. Additive and defaulted, so all five collectors keep working untouched.
- `collectors/{source_release,pypi_release,feedstock,conda_package}.py` -- each declares its
  cadence and its selection, and nothing else changes.
- `collectors/sweep.py` -- the dispatch, chunked and streamed.
- `collectors/tasks.py` -- `cpm.collect.sweep`.
- `config/settings/base.py` -- `CELERY_BEAT_SCHEDULE`, one entry per collector.
- `config/startup/stage_two.py` -- the cadence/schedule reconciliation, both directions, and
  the target-greater-than-cadence refusal.
- `tests/unit/django_apps/test_sweep.py` -- new: the dispatch's refusals, the chunking, the
  task-name derivation, and each collector's selection expressed as a query the unit tier can
  read without a database where possible.
- `tests/integration/django_apps/test_sweep.py` -- new: every matrix row that needs a run,
  including a ten-thousand-package dispatch asserting every package is enqueued in chunks and
  the dispatch never materialises them all, a repeat dispatch inside the window writing no
  second evidence row, and a package failing without touching another package's evidence.
- `tests/integration/startup/test_stage_two_collector_registry.py` -- the two new boot
  refusals and the real roster passing them.
- `tests/unit/test_settings.py`, `tests/unit/django_apps/test_task_routing_audit.py` -- the
  schedule entries and the new task's routing.
- `docs/deployment.md` -- the operator section for the sweep.

**Acceptance Criteria:**
- Given two collectors and a dispatch of each, when the first collector's dispatch raises,
  then the second's still records its own `succeeded` row and enqueues its own packages.
- Given five selectable packages and a broker that refuses two, when the dispatch runs, then
  three tasks are enqueued and the dispatch's ledger row is `partial`, not `failed`.
- Given ten thousand selectable packages, when the dispatch runs, then ten thousand tasks are
  enqueued in chunks and no operator batching is involved.
- Given a dispatch run twice inside the observation window, when both complete, then the
  evidence row count after the second is what it was after the first.
- Given a collector whose declared cadence does not match its schedule entry, when the
  component boots, then it refuses with a message naming both.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

## Review Notes

## Review Triage Log

### 2026-09-06 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 22: (high 4, medium 11, low 7)
- defer: 2: (high 0, medium 2, low 0)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[high]` `[patch]` **The boot refusal this product has claimed since `CPM-AD-28` did not
    exist.** Three reviewers established independently, one through a subprocess boot probe,
    that startup runs from the owner application's `ready()` before the collectors register,
    so both the freshness refusal and this story's new cadence reconciliation evaluated an
    empty registry in every real boot. Six shipped artefacts, the operator documentation among
    them, promised a component that refuses to start. Both rules became pure functions the
    collectors application calls immediately after it registers — the one hook a deployed
    process reaches with a populated registry — and a child-process case boots a real
    component with a mismatched interval and asserts it does not start. Mutation-tested:
    removing the refusal reddens it.
  - `[high]` `[patch]` The shipped schedule enqueued ten thousand failing collections a day
    out of the box: the published-package sweep shipped enabled while both of its declarations
    ship empty and its selection took every package. The selection is now empty until an
    operator declares them, so the dispatch records an empty selection rather than failing
    every package in the inventory.
  - `[high]` `[patch]` The soft-limit signal is a plain exception and was being counted as a
    broker refusal, so a long dispatch kept looping to the hard kill and left its ledger row
    `running` for ever. It is caught by name and finalizes `partial`.
  - `[high]` `[patch]` Every missed tick re-swept the whole inventory: the entries declared no
    expiry and nothing skipped a tick whose predecessor was still draining, against declared
    allowances that cannot drain ten thousand packages in a day. Enqueued tasks now expire
    after one cadence and an overlapping dispatch records `skipped`, with both negative
    controls asserted.
  - `[medium]` `[patch]` Eleven further findings, each addressed: only interval schedules
    reconciled, so a perfectly good crontab was reported as a disagreement; a malformed
    schedule died with an attribute error rather than a named refusal; a selection failing
    mid-stream discarded the count of what it had already enqueued and reported `failed`; a
    collector named for the dispatch task would have enqueued the dispatch once per package;
    the two selections that were pinned only by substring containment in rendered SQL admitted
    demonstrated mutants that offer exactly the packages the hook exists to exclude; the
    declared log key set omitted a key both events emit and no case observed either event; the
    chunker added resident memory rather than bounding it; a partial sweep left no record of
    which packages were refused; the documentation claimed an operator could change an
    interval without a deploy, which the installed scheduler makes false for these entries;
    the duplicate-entry branch was argued for and exercised by nothing; and the two new
    declarations were never cross-checked against each other.
  - `[low]` `[patch]` Seven further findings: two test docstrings described checks their
    bodies do not make; the streaming assertion proved only that a lazy read was requested and
    monkeypatched away the hook it claimed to protect; two case names asserted a deployment
    property they did not exercise; three daily entries fired at one instant from one origin;
    a materialised selection defeated the streaming property unchecked; and the operator
    documentation did not say what a dispatch row's `partial` does and does not mean.

## Design Notes

**Why a dispatch rather than a sweep.** The base already has a run-scoped `sweep()` for the
one collector that reads a document naming many packages. These four read one locator per
package, so their sweep is not a bigger read -- it is *many runs*. Doing it inside one task
would put ten thousand collections under one soft time limit and one ledger row, which is
exactly what `CPM-AD-23` forbids and what makes `CPM-FR-15`'s partial success unreachable.
Fanning out to the per-package tasks that already exist keeps every guarantee those four
stories built and makes AC 1 and AC 2 structural rather than defended.

**Why selection lives on the collector.** Each of the four already refuses, from `source_for`,
the packages it cannot answer about -- and each recorded that refusal as a deferred item
saying "the selection that offers only askable packages is `CPM-CURRENCY-S05`'s". The set a
collector can answer about is the complement of its own refusals, so it belongs beside them.
A dispatch module holding a table of four preconditions would be a second place that has to
be edited whenever a collector's refusals change, and the two would diverge silently.

**Why `not_applicable` packages are selected.** A package whose release-ecosystem mapping is
`not_applicable` is *not* refused by the PyPI collector -- it produces a `not_applicable` row
with no call made, which is what keeps it from reading stale (`CPM-FR-8`). Selecting it costs
one database read and writes the row the acceptance criterion asks for; not selecting it
would make that row unreachable in a real deployment.

**Why the reconciliation is at boot.** `CPM-CURRENCY-S01` recorded it precisely: a weekly
schedule against a daily-derived two-day target would make the whole inventory read stale five
days out of seven with every gate green. `config/startup/stage_two.py` already walks the
registered collectors for `CPM-AD-28`'s freshness refusal, so the check is one more predicate
in a sweep that exists, and it fails the component rather than a report.

## Verification

**Commands:**
- `pixi run test` -- expected: exit 0, the new unit module collected and passing.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: exit 0, no diagnostics.
- `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected"
  (this story adds no model).
- `pixi run ci` -- expected: exit 0; coverage >= 90%, `collectors/sweep.py` at 100%.

**Manual checks (if no CLI):**
- `git diff --stat 6a081c7` names every Code Map file that was meant to change and none of
  the read-only ones (`core/freshness.py`, `core/outcomes.py`, `identity/`,
  `collectors/selection.py`), and no migration is added.

## Dev Notes

**Satisfies:** `CPM-FR-15`, `CPM-NFR-1`

**Governed by:**

- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts
- `CPM-AD-23` — Transaction boundaries are per package

### Project Structure Notes

- Domain applications live under `src/django_apps/`, the second import root declared
  in `pyproject.toml` by `CPM-PLATFORM-S01`. App adoption is explicit and two-line —
  a `pixi.toml` dependency plus an `adopted_apps` entry in `component.toml`, in that
  order. Entry-point discovery is forbidden (inherited `AD-8`).
- A domain app contributes only to `DATABASES`, `DATABASE_ROUTERS`, `INSTALLED_APPS`,
  `NAVIGATION_REGISTRY`, `CELERY_BEAT_SCHEDULE`, `CELERY_IMPORTS`, `CELERY_TASK_ROUTES` —
  never `AUTHENTICATION_BACKENDS`, `DEFAULT_AUTHENTICATION_CLASSES`,
  `DEFAULT_PERMISSION_CLASSES` or `MIDDLEWARE`.
- Every refusal raises `ImproperlyConfigured` — never a warning, never log-and-continue
  (inherited `CG-3`).

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- Time comes from the injected clock in `core` (`CPM-AD-26`); no module calls
  `timezone.now()` directly.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S05]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-20]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-23]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-15]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-1]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context).

### Debug Log References

- `pixi run ci` -- exit 0. 5414 passed, 2 pre-existing skips, coverage 98.83% against a
  90% floor, with `collectors/sweep.py`, `collectors/apps.py`, `collectors/conda_package.py`
  and `core/collection.py` each at 100% and `config/startup/stage_two.py` at 98% (both
  uncovered regions are pre-existing). Counts are after the review patch round; before it,
  5360 passed at 98.82%.
- `pixi run gate-postgres` -- exit 0 against a throwaway `postgres:17`, re-run after the
  patch round.
- `pixi run gate-redis` -- exit 0 against `redis:7`, with nothing skipped.
- `pixi run manage makemigrations --check --dry-run` -- "No changes detected". This story
  adds no model.
- `git diff --cached --stat 6a081c7` -- every Code Map file that was meant to change and
  none of the read-only ones (`core/freshness.py`, `core/outcomes.py`, `identity/`,
  `collectors/selection.py`).

**One diagnosis worth recording.** `pixi run gate-postgres` failed twice with an
`INTERNALERROR` out of coverage (`no such table: context`) and 770 spurious database
errors, and the cause was two runs of it overlapping: the script binds one container name
and the suite writes `.coverage.<host>.<pid>.*` into the repository root, so a second
concurrent run corrupts the first's data files and steals its port. Run once, and remove
stale `.coverage.*` files first. That is very likely the same one-in-six exit 3
`CPM-EVIDENCE-S04` recorded as deferred and could not reproduce.

### Completion Notes List

### Review patch round (22 findings, all applied)

**The four high findings.**

- *The boot refusal did not exist, and six artefacts promised it.* Stage two runs
  from the platform owner's `ready()`, and every adopted application is installed
  after that owner -- so conditions 10 and 11 both swept an **empty registry** in
  every real boot, and `CPM-AD-28`'s freshness refusal had never fired in a
  deployed process either. The two rules are now pure functions in the domain
  application (`core/collection.py`'s `freshness_target_fault` and
  `collectors/sweep.py`'s `cadence_reconciliation_fault`), and
  `CollectorsConfig.ready()` calls both immediately after it registers -- the one
  hook a deployed process reaches with a populated registry. Inherited `AD-4`
  forbids `src/django_apps/` importing `config`, which is why the rules had to
  move rather than be called from the startup package. Stage two keeps both as
  conditions and now delegates to the same functions.
  `tests/integration/startup/test_collector_boot_refusal.py` boots a **child
  process** with a deliberately mismatched interval and asserts it does not start;
  removing the `ready()` raise reddens two of its three cases, which is what says
  it is not vacuous. Every artefact that overstated the guarantee was corrected --
  the four collectors' cadence comments, `core/collection.py`'s declaration,
  `config/settings/base.py`, `collectors/tasks.py`'s sweep task,
  `docs/deployment.md` and `tests/unit/test_settings.py` -- and the two cases whose
  names asserted a deployment property they did not exercise were renamed to say
  what they actually prove.
- *The shipped schedule enqueued ten thousand failing collections a day.*
  `cpm-sweep-conda-package` ships enabled while both channel settings ship empty,
  and that collector selected every package -- so a component with an inventory
  wrote one `failed` collection per package per day from the first tick, out of
  the box. `CondaPackageCollector.selectable_packages` now selects **nothing**
  when either declaration is empty or unusable, through the collector's own
  `declaration_fault` rule, so an undeclared component records one `succeeded`
  dispatch saying the selection was empty and says it once a day.
- *`SoftTimeLimitExceeded` was swallowed as a broker refusal.* It is a plain
  `Exception`, so the broad handler counted the signal as one more failed package,
  the loop carried on to meet it again, and the worker would have run to the hard
  limit -- leaving the ledger row `running` for ever, which is the one state
  `CPM-EVIDENCE-S03`'s recorder exists to make impossible. It is caught by name
  before the broad handler and finalizes `partial`.
- *Every missed tick re-swept the whole inventory, unbounded.* Each enqueued task
  now carries `expires` at the collector's own cadence, and a dispatch whose
  previous run for the same collector is still `running` records `skipped` rather
  than offering a second inventory. Both are asserted, including the two negative
  controls that matter: a *finished* previous run is not an overlap, and another
  *collector's* running dispatch is not one either -- a guard that read either as
  an overlap would reintroduce the failure this story is named for.

**The eleven medium findings.** A bare-seconds schedule is converted rather than
reported as a mismatch, and a `crontab` is refused with a message saying the two
cannot be *compared* rather than that they disagree. A non-mapping
`CELERY_BEAT_SCHEDULE`, a non-mapping entry and an entry whose `kwargs` are absent
or unusable each meet a named refusal instead of an `AttributeError`. An error
raised while *streaming* the selection is caught, the counts are kept and the run
is `partial` -- the documented invariant that `failed` is never reached by a
dispatch that enqueued something. A collector registered under `sweep` derives the
dispatch's own name and would enqueue it once per package, so it is refused at
both boot and dispatch. The `feedstock` and `source_release` selections gained the
behavioural negative half the rendered-SQL assertions could not make. `detail`
joined `EVENT_KEYS`, a per-package refusal event was added so a partial sweep of
ten thousand has a recovery path, and all three run-level events are now asserted
through captured logs. `_chunked` is gone -- the stream was already lazy, so
grouping added five hundred resident integers rather than removing any -- and the
constant is renamed `SELECTION_CHUNK` and re-documented as the database fetch size
it always was. The "change an interval without a deploy" claim is corrected in the
doc and in settings: the installed scheduler rewrites these four entries from
settings on every beat start. The duplicate-entry branch is now exercised. And the
two declarations are cross-checked: a cadence without a selection would be
dispatched and refused on every tick, a selection without a cadence is never
swept, and both are refused where the rest of the reconciliation is.

**The seven low findings.** The source-sweep docstring describes the check it
makes. The ten-thousand-package case *wraps* the shipped hook rather than
replacing it, so the selection the dispatch consumes is the real one and the
laziness assertion is about it. The forbidden-state declaration records that both
of this product's conditions have a second enforcement point and which one a
deployment meets. The settings comment says why three simultaneous daily ticks are
acceptable -- a dispatch enqueues and returns, and the pacing is each collector's
own limiter. A materialised selection is refused by construction rather than
asserted about from outside. And the operator doc gained a section of its own on
what a dispatch row's `partial` means and does not mean, plus the expiry and
overlap behaviour.


**A dispatch never collects, and that sentence is the whole design.** `collectors/sweep.py`
resolves a collector by name, asks it which packages it can be asked about, and enqueues
one *existing* per-package collection task each. It makes no outbound call, writes no
evidence and opens no transaction -- a source sweep in the unit tier asserts all three --
so every guarantee `CPM-CURRENCY-S01` through `-S04` built holds unchanged under a sweep.
`CPM-AD-23`'s per-package boundary and `CPM-FR-15`'s partial success become structural
rather than defended: a package is its own task, its own ledger row and its own
transaction because that is what `Collector.collect` already was, and one collector's
dispatch raising leaves no other dispatch in its call stack.

**The selection is the collector's, and it is exactly the complement of its own
refusals.** All four stories recorded the same deferred item -- offered every package,
this collector would fail every run -- and each is closed by a query written beside the
refusal it inverts: `source_release` takes packages with a source repository recorded,
`pypi_release` a `release_ecosystem` mapping that is `established` or `not_applicable`,
`feedstock` a mapping that is `established`, `not_found` or `not_applicable`, and
`conda_package` every package, because "it is not there" is the observation `CPM-FR-10`
asks for rather than a reason not to look. A table of four preconditions in the dispatch
module would have been a second place to edit whenever a collector's refusals changed.

**`not_applicable` is selected on purpose.** A package whose release-ecosystem mapping is
`not_applicable` is not refused: it produces a `not_applicable` row with no call made,
which is what keeps it from reading stale against PyPI (`CPM-FR-8` AC 3). Not selecting it
would have made that row unreachable in a real deployment.

**Two contradictions are selected and then refused, deliberately.** An `established`
mapping with a blank primary type, and a `not_found` feedstock mapping carrying `Feedstock`
rows, are both identity rows contradicting themselves, and both shipped collectors refuse
them from `source_for`. They stay in the selection so the contradiction surfaces as a
`failed` ledger row naming it; excluding them would hide an identity defect behind a sweep
that quietly skipped the package. Both are recorded as deferred, because the cost is now
recurring.

**`partial` on a dispatch row is a statement about enqueueing and nothing else.**
`succeeded` means every selected package was enqueued -- including when none was selected,
because a collector that was asked and answered is not a failure -- `partial` means some
were and some were not with the enqueued ones staying enqueued, and `failed` means none of
a non-empty selection was. The collections have not run when that row is finalized, and a
dispatch that waited for them would be the retry storm the story forbids. `docs/deployment.md`
gives an operator the table.

**Nothing materialises the inventory.** `selectable_packages` answers with a lazy queryset,
`_streamed` turns it into a server-side iterator and `_chunked` batches it with `islice`,
so ten thousand keys never exist in one place. The claim is asserted twice rather than
documented: a unit case hands the batcher a counting generator and stops after one batch,
and the integration case dispatches ten thousand real packages through the shipped
`conda_package` selection and asserts the queryset's result cache is still empty
afterwards. A `list(queryset)` in the hook would pass every behavioural case and fail both
of those.

**The base grew one declaration and one defaulted hook, and neither changes an existing
collector.** `cadence: ClassVar[timedelta | None] = None` is the tenth declaration and the
one the constructor does *not* check -- `None` is legitimate, and a declared value is
meaningful only against a schedule the object cannot see, so its enforcement point is
`require_cadence`, called by the boot sweep. `selectable_packages()` is a **classmethod**
where the other two defaulted hooks are instance methods, because both callers read it off
a class: a dispatch selects without collecting, and constructing a collector to ask would
build a `RequestsTransport` and its pool for a dispatch that makes no call. `None` means
"not swept per package", which a dispatch refuses **by name** rather than skipping -- a
schedule entry firing a per-package dispatch at run-scoped inventory ingestion would
otherwise look exactly like a collector nothing ever ran.

**The task name is derived and then verified.** `cpm.collect.<name>` is the namespace
`core/queues.py` routes to the `collect` queue, so a dispatch cannot be pointed at another
collector's task; and a derived name Celery's registry does not hold is refused, because
publishing into a name nothing consumes is silent non-delivery -- which looks exactly like
a source that answered nothing.

**Cadence is data, and the two declarations are reconciled at boot as condition 11.**
`config/settings/base.py` gains one `CELERY_BEAT_SCHEDULE` entry per per-package collector,
seeding `django_celery_beat`'s tables so an operator can change an interval without a
deploy. Each collector separately declares the cadence its target was derived from, and
`config/startup/stage_two.py` refuses a boot where the two disagree -- naming both numbers
-- where a schedule entry names a collector nothing registered, and where a freshness
target is not strictly greater than its cadence. It is condition **11** rather than a
second rule inside condition 10, on exactly the argument `forbidden_states.py` makes for
condition 10 not being folded into the inherited nine: `CPM-AD-28` is about a target
nobody declared and `CPM-AD-20` is about the schedule, which is a different decision, a
different artefact and a different fix. The declaration, the coverage audit's arithmetic
(thirteen unconditional states to fourteen, fifteen to sixteen) and `test_no_softening.py`'s
builder all moved with it.

**The empty-registry guard is load-bearing and is why the condition is honest about what
it cannot do.** Stage two runs from the owner app's `ready()` and every adopted application
is installed after it, so in a *real* boot the registry is empty when conditions 10 and 11
run. Without an early return the backward direction would refuse every deployed process
over four schedule entries naming collectors not yet registered. Both conditions are
therefore load-bearing in the suite and vacuous in a deployment -- a pre-existing property
of the inherited invocation point that condition 10 already had, recorded as `deferred`
rather than worked around.

**A settings module cannot import a collector, so three strings are literals and all three
are reconciled.** `config/settings/base.py` executes before the app registry exists and
every collector module reaches a Django model, so the task name, the collector keyword and
the four cadences are written out there. The boot condition reconciles the cadences and the
collector names at run time; `tests/unit/test_settings.py` reconciles the task name and the
keyword against `collectors/sweep.py`'s own declarations, and the cadences against the four
collector classes, so a rename on either side fails a pull request rather than shipping a
beat entry that fires into nothing.

**AC 2 and AC 3 are proved end to end rather than through fixtures.** Both are claims about
what the *enqueued collections* do, so both drive the real `pypi_release` collector, its
real evidence table and its real task with only `RequestsTransport.fetch` substituted: three
packages of which one source is unreachable leave two `ok` rows and one `error` row with
their three separate ledger rows, and a dispatch repeated inside the observation window
enqueues the same packages again and writes no second evidence row. The dispatch's own
contract -- what was offered, what the broker took -- is proved against fixture collectors
with the enqueue substituted, because under the eager suite an unsubstituted `apply_async`
runs the task rather than recording that it was offered.

### File List

- `src/django_apps/conda_package_supply_chain_monitor/core/collection.py` -- the `cadence`
  declaration, the `selectable_packages` classmethod hook, `require_cadence`,
  `freshness_target_fault`, `NO_CADENCE`, `__all__`, and the class docstring's account of
  the third defaulted hook.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/sweep.py` -- new. The
  dispatch: `SWEEP_TASK_NAME`, `RESERVED_COLLECTOR_NAME`, `COLLECTOR_KWARG`,
  `PACKAGE_KWARG`, `SELECTION_CHUNK`, the four events and their two key sets,
  `SweepDispatchError`, `DispatchOutcome`, `collection_task_name`, `_streamed`, `_resolve`,
  `_selection_of`, `_task_for`, `_already_draining`, `dispatch`, `_enqueue_each` and
  `_finalized` -- and `CPM-AD-20`'s reconciliation as the public
  `cadence_reconciliation_fault`, which both boot points call.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py`,
  `pypi_release.py`, `feedstock.py`, `conda_package.py` -- each gains `cadence` bound to the
  module constant it already had and a `selectable_packages` override. Nothing else changed.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` -- the
  `cpm.collect.sweep` task, the re-exported `SWEEP_TASK_NAME`, `__all__`.
- `src/config/settings/base.py` -- `CELERY_BEAT_SCHEDULE`, four entries, with the reasoning
  for the literals and for inventory ingestion's absence.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` -- `ready()` calls
  the two public declaration rules immediately after registering, which is where a deployed
  process meets both refusals.
- `src/config/startup/stage_two.py` -- `_refuse_unreconciled_cadence` and
  `_refuse_collector_without_freshness_target`, both now delegating to the domain
  application's rules; the roster; and the condition-count prose.
- `docs/deployment.md` -- the operator section for the sweep: what beat fires, what a
  dispatch does and does not do, the three dispatch states, the shipped cadences, the four
  selections, the boot reconciliation, and the `-Q` and rate-limit caveats.
- `tests/unit/django_apps/test_sweep.py` -- new. The declarations, the derivations, the
  chunking, `require_cadence`, the four selections read as queries, and the module's own
  source sweeps.
- `tests/integration/django_apps/test_sweep.py` -- new. Every matrix row that needs a run,
  the ten-thousand-package dispatch, and AC 2 and AC 3 end to end.
- `tests/integration/startup/test_stage_two_collector_registry.py` -- condition 11's
  refusals, its negative controls, the declaration-pair cross-check, and the shipped
  schedule reconciling against the shipped collectors.
- `tests/integration/startup/test_collector_boot_refusal.py` -- new. A child process, a real
  `django.setup()`, and the assertion that a misdeclared component does not start.
- `tests/collectors.py` -- `FIXTURE_CADENCE` and `selectable_collector_class`.
- `tests/unit/django_apps/test_collection.py` -- the base's own cases for the two additions.
- `tests/unit/test_settings.py` -- the schedule entries, reconciled three ways.
- `tests/unit/startup/forbidden_states.py`, `tests/unit/startup/test_refusal_coverage_audit.py`,
  `tests/unit/startup/test_no_softening.py`, `tests/unit/startup/test_stage_two_urlconf.py`
  -- condition 11 and its forbidden state, the arithmetic, the refusal's shape, the roster.
- `tests/unit/django_apps/test_collector_base_audit.py`,
  `tests/unit/django_apps/test_task_routing_audit.py` -- the new module as a scan anchor,
  and the dispatch task's routing.

## Auto Run Result

Status: done
Blocking condition: none

**What was implemented.** The full-inventory sweep the four collector stories all deferred to.
One dispatch task per collector, fired by the database scheduler at the cadence that collector
declares. A dispatch never collects: it asks its collector which packages it can answer about,
streams that selection, and enqueues one existing per-package collection task each. So the
atomic unit stays one package, one collector's dispatch failing cannot touch another's, and a
package failing is its own task and its own ledger row — AC 1 and AC 2 are structural rather
than defended, and AC 3's idempotency is the observation window that already existed.

**Selection is the collector's own knowledge.** Each of the four already refuses, from
`source_for`, the packages it cannot answer about, and each recorded that refusal as a deferred
item naming this story. The selection is the complement of those refusals and lives beside
them, so there is no second place holding a table of preconditions that could drift.

**Cadence became a declaration that something checks.** Four schedule entries, and a
reconciliation that refuses a component whose collector and schedule disagree, whose schedule
names a collector nothing registered, or whose freshness target is not strictly greater than
its cadence.

**Files changed.**

- `core/collection.py` — `cadence` as a declaration and `selectable_packages()` as a
  defaulted hook, both additive; every collector written before this is byte-identical.
- `collectors/{source_release,pypi_release,feedstock,conda_package}.py` — each declares its
  cadence and its selection, and nothing else changes.
- `collectors/sweep.py` *(new)* — the dispatch: resolve, refuse, stream, enqueue, finalize.
- `collectors/tasks.py`, `collectors/apps.py` — the dispatch task, and the boot refusal.
- `config/settings/base.py` — `CELERY_BEAT_SCHEDULE`, one entry per collector.
- `config/startup/stage_two.py` — the reconciliation as a startup condition.
- `docs/deployment.md` — what beat fires, what a dispatch does and does not do, and what
  `partial` on a dispatch row means.
- New unit and integration modules, a child-process boot probe, and the audit bookkeeping the
  new startup condition forces.

**Review findings.** 22 patched (4 high, 11 medium, 7 low), 2 deferred, 2 rejected. Four
review layers ran in parallel over the 3,900-line diff.

**Follow-up review recommended:** true. Four high-severity patches. Patched counts: high 4,
medium 11, low 7; score `3 x 11 + 1 x 7 = 40`, far over the threshold of 5.

**The most valuable finding was about a guarantee that had never existed.** `CPM-AD-28` says a
collector without a freshness target refuses to start, and the operator documentation said so
too — but startup runs from the owner application's `ready()` before the collectors register,
so the sweep it performs has always walked an empty registry in a real boot. Three reviewers
established it independently and one proved it with a subprocess probe. Both rules now run
where the registry is populated, and a child-process case boots a real component with a
mismatched interval and asserts it does not start; removing the refusal reddens that case.

**The second was a shipped default.** The published-package sweep shipped enabled while the
declarations it needs ship empty, so a component with an inventory would have written ten
thousand failed collections a day from its first tick.

**Verification.** `pixi run ci` exits 0 — 5414 passed, 2 pre-existing skips, coverage 98.83%,
with `collectors/sweep.py` and `core/collection.py` at 100%. `makemigrations --check
--dry-run` reports "No changes detected"; this story adds no model. `pixi run gate-postgres`
passes against `postgres:17`. All three were re-run by the orchestrating session after the
patch round.

**Residual risks.** Nine `deferred` entries, one high: the four declared allowances still
cannot sweep ten thousand packages inside their cadences, and the dispatch makes that exposure
live rather than latent — the visible symptom is `skipped` and `error` rows rather than silence.
Raising them needs authentication, which is a credential decision none of these stories owns.
Two mediums are worth carrying forward: the reconciliation reads the settings declaration
rather than the scheduler's own tables, and ten thousand sequential broker publishes inside one
task have never been measured against the inherited soft limit.
