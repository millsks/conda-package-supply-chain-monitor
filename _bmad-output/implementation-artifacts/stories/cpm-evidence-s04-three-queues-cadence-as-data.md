---
title: 'CPM-EVIDENCE-S04: Three queues and cadence as data'
type: 'feature'
created: '2026-09-04'
status: 'done'
baseline_revision: '303fd5e088f11908289f348fd202b08a9f947eb5'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
warnings: ['oversized']
deferred:
  - summary: >-
      No non-eager test proves a `cpm.collect.*` name really lands on `collect` when a
      message is actually published.
    evidence: |-
      Every routing claim here is configuration-level by choice, which the eager-Celery
      constraint forces: `CELERY_TASK_ALWAYS_EAGER` is on for the whole suite and
      `apply_async` never reaches the AMQP layer. `tests/integration/test_celery_log_correlation.py`
      is the one fixture that turns eager off and really publishes, and it is cited four times
      as the reason for the no-catch-all rule but never extended to assert the routing.
      Reconciling `queue_for` against `app.amqp.router` is strong evidence and is not the
      same thing as a real publish.
    location: >-
      tests/integration/test_celery_log_correlation.py
    severity: medium
  - summary: >-
      One worker consuming four queues is not `CPM-AD-20`'s starvation guarantee.
    evidence: |-
      A five-minute `verify` build still occupies the concurrency slots the daily security
      sweep needs. Real isolation is a worker process per queue, which cannot be declared
      here: `component.toml`'s process list is asserted to be exactly `web`, `worker`, `beat`
      by `tests/unit/test_component_declaration.py:326-341`. `R-11` is shared with
      `CPM-PY314-S02`, which is where the first real `verify` work arrives.
    location: >-
      pixi.toml
    severity: medium
  - summary: >-
      The deployed worker command changed and no operator-facing documentation says so.
    evidence: |-
      `docs/deployment.md` and `docs/observability.md` are untouched. Nothing outside the
      pixi manifest comment tells an operator that a worker must drain four queue names, or
      what happens when a process manager starts celery without the flag -- which is silent
      non-consumption, not a crash.
    location: >-
      docs/deployment.md
    severity: low
  - summary: >-
      `pixi run gate-postgres` exited 3 once in six runs with every test passing, and was not
      reproduced.
    evidence: |-
      One invocation on 2026-09-04 printed `2673 passed` and then `the suite failed against
      postgres:17 (exit 3)`. Exit 3 is pytest's INTERNALERROR, i.e. a failure outside the test
      session itself -- collection, a plugin, or teardown. Five further runs of the same
      command on the same commit exited 0. Only two lines of the failing run were captured, so
      there is no traceback to work from. Recorded rather than dismissed: a pre-push check that
      fails once in six is worse than none, because the first person to hit it will re-run it
      and move on. If it recurs, capture the full output before re-running.
    location: >-
      scripts/gate-postgres.sh
    severity: medium
  - summary: >-
      `product_task_names()` re-runs `app.loader.import_default_modules()` on every call.
    evidence: |-
      Idempotent, but it is import-system work inside tests that advertise no database and no
      network, and it runs once per `registered_tasks` block and twice in some cases. A
      session fixture would match what the docstring claims about its cost.
    location: >-
      tests/celery_tasks.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** No Celery routing exists and no default queue is declared, so every task this
product will write lands in one undifferentiated queue. A compute-backed Python 3.14 build
would then share a queue with the daily security sweep and starve it -- `R-11`, and the
failure `CPM-AD-20` exists to prevent. Cadence has nowhere to live but a decorator, which
`CPM-NFR-2` forbids because a per-collector hard-coded schedule cannot be changed without a
deploy.

**Approach:** A queue vocabulary owned by `core` -- `collect`, `policy`, `verify` -- and a
route table keyed on a task-name namespace, installed into settings as `CELERY_TASK_ROUTES`.
Every task this product registers declares a name in one of the three namespaces, which is
what makes its workload class a property of the task rather than of whoever wrote the route.
An audit reads the routing as configuration, because eager Celery never consults it.

## Boundaries & Constraints

**Always:**
- The three queue names are declared **once**, in `core`, and every other reader imports
  them. A second literal spelling of `"collect"` is the failure this repository's audits
  exist to catch.
- A product task's **name** declares its workload class: `cpm.collect.*`, `cpm.policy.*`,
  `cpm.verify.*`. Routing is derived from that name, never from the module a task happens to
  live in -- `CPM-EP-PY314` puts verification collectors beside currency collectors, so a
  module-prefix scheme would route a `verify` build to `collect` and reopen `R-11`.
- Routing is asserted **as configuration**, never by calling a task. `CELERY_TASK_ALWAYS_EAGER`
  is on for the whole suite (`config/settings/test.py:90`), and eager `apply_async`
  short-circuits to `apply()` -- `task_routes` is never consulted and no message acquires a
  queue, so a `.delay()` assertion would assert nothing (`EVIDENCE.04-AUDIT-001`).
- The audit is paired with an **anti-vacuity guard**. No product task exists yet, so the sweep
  passes today by finding nothing; the detector is measured against fixture tasks registered
  and unregistered around the case, in the shape `test_outcome_field_audit.py` and
  `test_evidence_inheritance_audit.py` already use.
- The inherited platform task `django_service.users.tasks.get_users_count` is a **recorded,
  counted exemption**, on the same terms and in the same shape as the two inherited wall-clock
  readers in `tests/unit/django_apps/test_clock_audit.py`: it names the module, licenses
  exactly one task, and fails on a second.
- Cadence is data in `django_celery_beat`'s `DatabaseScheduler` (already configured at
  `base.py:500`). No decorator carries a schedule, and no module assigns `beat_schedule`
  outside settings.
- The inherited limits stay as they are -- 5-minute hard, 60-second soft (`base.py:495,498`).
  Work that would exceed them is chunked per package (`CPM-AD-9`); no task declares a
  `time_limit` or `soft_time_limit` of its own.
- Contributions stay inside `CONTRIBUTABLE_KEYS`, **imported** from
  `config/startup/allowlist.py` and never respelled -- `test_allowlist_declaration.py:292-304`
  permits those names to be declared in that module alone.
- `structlog` only, no `print`, no stdlib `logging`. Full type hints, Google docstrings,
  line length 120.

**Block If:**
- Closing AC 4 would require routing `get_users_count` to one of the three queues. It is
  none of collection, policy or verification work, and giving it a queue to satisfy an audit
  is the audit describing a rule the architecture does not have.

**Never:**
- Do not build AD-8's composition step. It is the platform's Epic 9 and is not built; the
  spine says to treat the contributable surface as convention until then, and `base.py:196-199`
  already installs `core` into `INSTALLED_APPS` on exactly those terms. See Design Notes.
- No catch-all `"*"` route pattern and no change to `CELERY_TASK_DEFAULT_QUEUE`.
  `tests/integration/test_celery_log_correlation.py` turns eager off and really publishes;
  its probe has no route and must keep landing on the default queue.
- No new entry in `component.toml`. Its top-level key set is closed and asserted
  (`test_component_declaration.py:234-258`), and `[[processes]]` is asserted to be exactly
  `web`, `worker`, `beat` (`:326-341`) -- so a per-queue worker process cannot be declared here.
- No collectors, no policy passes, no real tasks, no cadence entries. There is nothing to
  schedule until `CPM-EP-CURRENCY`.
- No `ready()` on `CoreConfig`; `tests/unit/django_apps/test_core_app.py:128-135` asserts it
  has none, so nothing may be registered from an app-ready hook.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Collector task name | `cpm.collect.pypi_release` | resolves to queue `collect` | No error expected |
| Policy task name | `cpm.policy.currency` | resolves to queue `policy` | No error expected |
| Verify task name | `cpm.verify.py314_build` | resolves to queue `verify`, never `collect` (`R-11`) | No error expected |
| Product task, no namespace | a task named `cpm.sweep.thing` | audit fails naming the task and the three permitted namespaces | Raised by the audit |
| Product task, bare name | a task under `src/django_apps/` named `mymodule.thing` | audit fails: a product task must declare a `cpm.` name | Raised by the audit |
| Inherited platform task | `django_service.users.tasks.get_users_count` | exempt, and recorded; resolves to no product queue | No error expected |
| A second inherited task | another unrecorded task outside `cpm.` | audit fails -- the exemption licenses one, not the module | Raised by the audit |
| Task overriding a limit | `@shared_task(time_limit=900)` | audit fails: chunk per package, never raise the limit (`CPM-AD-9`) | Raised by the audit |
| Cadence in a decorator | a task carrying a schedule or `crontab(...)` | audit fails: cadence is data in the scheduler (`CPM-AD-20`) | Raised by the audit |

</intent-contract>

## Code Map

- `src/config/startup/allowlist.py:337-347` -- `CONTRIBUTABLE_KEYS`, already carrying
  `CELERY_TASK_ROUTES`, `CELERY_BEAT_SCHEDULE`, `CELERY_IMPORTS`. Import these names; never
  respell them (`test_allowlist_declaration.py:292-304`).
- `src/config/settings/base.py:194-201` -- the precedent. `core` is installed by a hand-written
  `LOCAL_APPS` entry whose comment records that `adopted_apps` is the AD-8 declaration and
  that nothing consumes it yet. The route table arrives the same way.
- `src/config/settings/base.py:468-506` -- the Celery block. **Textual constraint:**
  `test_settings.py:1076-1103` requires every top-level assignment between the `# Celery`
  banner and the `# django-allauth` banner to start with `CELERY_`. A helper tuple named
  anything else fails there, which is why the vocabulary lives in `core` and is imported.
- `src/config/settings/base.py:495,498,500` -- the inherited 5-minute and 60-second limits and
  the `DatabaseScheduler`. All three already correct; assert, do not change.
- `src/config/celery_app.py:26` -- `config_from_object("django.conf:settings", namespace="CELERY")`
  is a live view, so `CELERY_TASK_ROUTES` in settings becomes `app.conf.task_routes` with no
  change here. `:88` `autodiscover_tasks()` finds `tasks.py` per installed app.
- `src/django_service/users/tasks.py:11` -- `get_users_count`, the inherited platform demo task
  and the only registered task today. The recorded exemption.
- `src/config/settings/test.py:90,92` -- `CELERY_TASK_ALWAYS_EAGER` / `EAGER_PROPAGATES`, why
  the audit reads configuration.
- `src/config/startup/stage_one.py:966-1015` -- `_refuse_eager_tasks`; eager is a locality
  affordance only, so nothing may depend on it outside tests.
- `tests/unit/django_apps/test_clock_audit.py` -- the counted-exemption shape to copy: a module
  keyed to a permitted count, failing on a second occurrence and on a stale record.
- `tests/unit/test_celery_app.py:47-118` -- five existing cases, none about routing. The natural
  home for a configuration-level routing assertion.
- `tests/integration/test_celery_log_correlation.py:128-186` -- the one fixture that turns eager
  off and really publishes, and the reason no catch-all route may be added.
- `tests/unit/test_process_model.py:249-310,642-676` -- the two-way process gate. Adding `-Q` to
  the existing worker command is permitted; adding a second worker task is not.
- `pixi.toml:549` -- `celery ... worker -l INFO`, with **no `-Q`**, so it consumes the default
  queue only. See Design Notes.
- `tests/source_scan.py` -- `project_files`, `EXCLUDED_DIRECTORIES`; the walk every audit shares.

## Tasks & Acceptance

**Execution:**
- `src/django_apps/conda_package_supply_chain_monitor/core/queues.py` -- new. Declare `Queue`
  (the three names, once), `TASK_NAMESPACE_PREFIX`, the namespace-to-queue mapping, the
  `CELERY_TASK_ROUTES` table built from it, and `queue_for(task_name)` returning the queue or
  `None`. No Django imports at module scope -- settings imports this during composition.
- `src/config/settings/base.py` -- import the route table and assign `CELERY_TASK_ROUTES`
  inside the Celery block, with a comment recording that this is AD-8's contribution written by
  hand until the Epic 9 composition step exists, in the same voice as the `LOCAL_APPS` entry.
- `pixi.toml` -- give the `worker` task `-Q` naming the default queue and the three, so routed
  work is actually consumed. Record why the default queue stays in the list.
- `tests/celery_tasks.py` -- new helper. Register and unregister fixture tasks against the real
  app so the audit's detector can be measured without leaving tasks in the registry. A helper
  module, not collected, in the shape of `tests/model_registry.py`.
- `tests/unit/django_apps/test_queues.py` -- new. The vocabulary: three names, no duplicates,
  `queue_for` over each namespace, an unknown namespace, a bare name, and that the route table
  is built from the mapping rather than written out twice.
- `tests/unit/django_apps/test_task_routing_audit.py` -- new. `EVIDENCE.04-AUDIT-001`: sweep
  `app.tasks`, skip `celery.*` built-ins, and assert every remaining task either resolves to one
  of the three queues or is a recorded exemption. Both directions on the exemption table, the
  anti-vacuity guard, and the detector measured against fixture tasks for every I/O matrix row.
- `tests/unit/django_apps/test_task_declaration_audit.py` -- new. AC 2 and AC 3 as source
  sweeps over `src/`: no task decorator carries a `time_limit`/`soft_time_limit`, and none
  carries a schedule or `crontab(...)`; plus no module assigns `beat_schedule` outside settings.
  Anti-vacuity guards on both.
- `tests/unit/test_celery_app.py` -- add the configuration-level assertion that
  `app.conf.task_routes` is the table `core` declares, so the live view is proven rather than
  assumed.
- `tests/unit/test_settings.py` -- extend the Celery-block assertions: the routes are declared,
  the two time limits are unchanged, and `CELERY_BEAT_SCHEDULER` is the database scheduler.

**Acceptance Criteria:**
- Given the settings in force, when `app.conf.task_routes` is read, then it maps each of the
  three namespaces to its queue and declares no catch-all pattern.
- Given every task in the registry, when the routing audit runs, then each one resolves to
  `collect`, `policy` or `verify`, or is named in the recorded exemption table -- and the table
  fails from both sides, on an unrecorded task and on a record naming a task that is gone.
- Given a fixture task named in each namespace, when `queue_for` is asked, then a `cpm.verify.*`
  task resolves to `verify` and never to `collect` (`R-11`).
- Given the full gate, when `pixi run ci` runs, then it exits 0 with coverage at or above 90%.
- Given a real PostgreSQL, when `pixi run gate-postgres` runs, then the suite passes there too.

## Spec Change Log

**The registry sweep skips `tests.*` as well as `celery.*`.** The spec says "skip `celery.*`
built-ins". A second prefix was needed: `tests/integration/test_celery_log_correlation.py`
declares `correlation_probe` with a module-scope `@shared_task`, and a shared task registers
into every `Celery` instance in the process -- so importing that module puts
`tests.integration.test_celery_log_correlation.correlation_probe` in the same registry the
audit sweeps, and `pixi run ci` failed on it where `pixi run test` did not. It is skipped by
prefix rather than recorded as a counted exemption because the count would be one in a full
run and zero in a unit-only run, and a record whose truth depends on which subset of the
suite is invoked is worse than no record. The skip is narrow -- nothing under `src/` can
produce a task named `tests.…` -- and it is measured rather than trusted:
`test_the_sweep_skips_the_suites_own_tasks_and_nothing_wider` registers one suite-shaped and
one product-shaped fixture in a single pass and asserts only the first is dropped. The probe
still lands on the default queue, which is what the Never clause requires of it.

**One test added outside the Execution list: `tests/unit/test_process_model.py`.** The spec
lists the `pixi.toml` `-Q` change as Execution but names no gate on it, and the Code Map
mentions that file only to say adding `-Q` is permitted. Left unasserted, the flag is the one
part of this story that can be deleted with no test going red, and its deletion turns every
routed task into work that is published and never run -- silently, which is the failure mode
the rest of the story is built around. `test_the_worker_drains_the_default_queue_and_all_three_workload_queues`
reconciles the flag's value against `Queue` and `app.conf.task_default_queue` rather than
against a literal list, so the manifest's spelling cannot drift from `core`'s.

**`queue_for` is reconciled against celery's own router.** Not required by the spec, and it
is what makes "asserted as configuration" more than a claim about a dictionary:
`app.amqp.router.route({}, name)` is the lookup a real `apply_async` performs, needs no
broker, and is asserted to agree with `queue_for` for each namespace and to send an unrouted
name to `app.conf.task_default_queue`.

## Review Triage Log

### 2026-09-04 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 22: (high 1, medium 8, low 13)
- defer: 5: (high 0, medium 3, low 2)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[high]` `[patch]` `queue_for` and celery's router disagreed on a trailing-empty segment -- celery routes `cpm.collect.` and `cpm.collect..x` to `collect` because `fnmatch` matches `*` against nothing, while the resolver called both unrouted -- so the audit would have demanded an exemption for a task celery routes correctly, and the module's claim that the resolver cannot be a second opinion was false. The resolver now reproduces the glob, and the reconciliation runs both directions over twelve names including the malformed ones.
  - `[medium]` `[patch]` Nothing pinned `task_create_missing_queues`; the three queues existed only by celery's default, with `task_queues` unset. Now declared and tested.
  - `[medium]` `[patch]` The limits rule was enforced only against parsed source, so a limit arriving through `**options` registered a task carrying it and passed clean. A registry sweep now reads the options off the task object, using the `**options` seam that had been built and left unused.
  - `[medium]` `[patch]` `core/queues.py` recorded a settings-import purity constraint that nothing gated, while `core/roles.py` has one; a `from django.apps import apps` would have imported cleanly and failed later.
  - `[medium]` `[patch]` The beat-schedule carve-out is the whole `config/settings` directory, but only `base` was asserted schedule-free -- a cadence in `production.py` passed both gates. Both cadence and limit cases now run over every settings module.
  - `[medium]` `[patch]` Fixture registration sat outside the `try`, leaking earlier tasks into the process-wide registry on a mid-loop failure.
  - `[medium]` `[patch]` The fixture helper's `finally` raised unconditionally, displacing an in-flight body exception -- the same defect the `CPM-EVIDENCE-S03` review fixed in `core/ledger.py`, and resolved the same way.
  - `[medium]` `[patch]` The time limits were pinned in `base` only; `local`, `test` and `production` could raise them untested.
  - `[medium]` `[patch]` Cadence was caught as a module-level assignment and a limit was not, so `app.conf.task_time_limit = 900` outside settings passed every gate.
  - `[low]` `[patch]` Thirteen further findings: `**` unpack and assignment-aliased task decorators, schedules set through `conf.update`/subscript/class attributes, `--queues` long-form and whitespace in the worker-flag parser, two spellings of one contributed-key constant, fixture names re-spelled beside their own constants, module-scope Django imports in the manifest gate, a meaningless enum-order assertion, the untested inner mapping proxy, one decision double-reported as two offences, a bare `.task` decorator match with no negative control, an exemption keyed on a name a task could claim without living there, two unexercised guards in the fixture helper, and a hard-coded roster count in prose.

**Review loop 1 -- 22 findings triaged `patch`, all applied.** Two rejected findings were
left as they were, on the coordinator's instruction: the `tests.` prefix skip, and the
self-reference in `test_the_route_table_is_built_from_the_mapping_rather_than_written_out_twice`.

The one that changed shipped behaviour rather than a test: **`queue_for` and celery's router
genuinely disagreed.** `fnmatch.translate` makes `*` match the empty string, so
`cpm.collect.*` captures `cpm.collect.` and `cpm.collect..x` and a real publish routes both
to `collect`, while the resolver called them unrouted -- the audit would have demanded an
exemption for a task celery was routing correctly. `queue_for` now reproduces the glob
exactly (prefix, known namespace, separator; what follows is not inspected), and
`test_celerys_own_router_sends_the_name_where_queue_for_says` runs **both directions over
twelve names**, malformed and negative included: every name the resolver routes must reach
that queue under the router, and every name it calls `None` must reach `task_default_queue`.

Three findings added surfaces the spec's Execution list did not name, each because the rule
as written had a way past it:

- **The registry sweep** (`test_task_declaration_audit.py`). The source sweep cannot see
  `@shared_task(**TASK_OPTIONS)` or an option inherited from a base class; the task object
  carries the option however it arrived. This also puts the `**options` seam in
  `tests/celery_tasks.py` to use, which was documented and unused.
- **`task_create_missing_queues`** (`test_celery_app.py`). The three queues exist only
  because celery auto-creates them on publish -- nothing declares `task_queues`. An operator
  setting that `False` turns every routed publish into `QueueNotFound`. The assumption is now
  declared and pinned.
- **The settings modules are read as four, not one** (`test_settings.py`). `config/settings/`
  is the carve-out the source sweep permits a schedule in, and only `base` was being read --
  so a `CELERY_BEAT_SCHEDULE` or a raised `CELERY_TASK_TIME_LIMIT` in `production.py`, the one
  that would actually reach a deployed component, sat inside the carve-out and was parsed by
  nothing. Verified by adding both to `production.py` and watching the two cases go red.

The rest tightened detectors and reporting: limit *assignments* outside settings
(`app.conf.task_time_limit = 900`) now fail as schedule assignments already did; decorators
aliased by assignment, `**`-unpacked options, `update()`/subscript schedule writes and
class-based tasks are all matched; `@obj.task(...)` on a third-party object no longer fails
the gate; `schedule=schedule(...)` reports once rather than twice; the `-Q` parser reads
`--queues` and `--queues=`, strips whitespace, and distinguishes a worker draining too little
from one draining too much; the fixture helper registers inside its own `try` so a partial
failure leaks nothing, and reports registry drift without displacing an exception already
propagating (the resolution `core/ledger.py` records); the exempted task's `__module__` is
reconciled against the module its name claims; and `CELERY_TASK_ROUTES` is now spelled once,
as `queues.CONTRIBUTED_SETTING_KEY`.

## Design Notes

**AD-8's composition step does not exist, and this story must not build it.** The allowlist
declares `CELERY_TASK_ROUTES` contributable and nothing consumes a contribution:
`config/component/loader.py` parses `component.toml` and stops there. The spine is explicit --
AD-8 and the `CONTRIBUTABLE_KEYS` allowlist are both "Declared; enforced by the platform's
Epic 9, which is not built. Treat as convention until then" -- and `base.py:196-199` already
installs `core` into `INSTALLED_APPS` by hand on exactly those terms, saying so in a comment.
So "contributed via the platform's allowlist" is honoured here by using only keys the allowlist
permits, importing those names rather than respelling them, and writing the contribution into
settings the way the adoption already is. Building Epic 9 Story 9.4 inside a domain story would
be a platform change wearing a domain story's number.

**Why the workload class lives in the task's name.** `CPM-EP-PY314`'s verification collectors
and `CPM-EP-CURRENCY`'s currency collectors both land in `django_apps/collectors`, so a route
keyed on module path cannot tell a compute-backed build from an HTTP fetch -- and getting that
wrong is `R-11` exactly: "verification routes to `verify`, never `collect`". A declared name
carries the class with the task wherever the module moves:

```python
@shared_task(name="cpm.verify.py314_build")
def verify_py314_build(package_id: int) -> None: ...
```

**The worker consumes no queue today, and routing without consumption is inert.**
`pixi.toml:549` runs `celery ... worker -l INFO` with no `-Q`, so it drains the default `celery`
queue only; tasks routed to `collect` would be published and never run. The worker therefore
names all four -- the default queue stays because the inherited `get_users_count` and the
correlation probe still land there, and dropping it would strand them.

**What this does not deliver, stated rather than discovered.** One worker consuming all three
queues does not give `CPM-AD-20`'s starvation guarantee: a five-minute `verify` build still
occupies the concurrency slots the daily sweep needs. Real isolation is a worker process per
queue, which cannot be declared here -- `component.toml`'s process list is asserted to be
exactly `web`, `worker`, `beat`. `R-11` is shared with `CPM-PY314-S02`, which is where the
first real `verify` work arrives; the split belongs there, with something to measure.

## Verification

**Commands:**
- `pixi run test` -- expected: the unit suite passes, including the three new audits.
- `pixi run test-integration` -- expected: passes, `test_celery_log_correlation.py` included.
- `pixi run ci` -- expected: exits 0, coverage at or above 90%.
- `pixi run gate-postgres` -- expected: the suite passes against `postgres:17`.

## Auto Run Result

Status: done
Blocking condition: none

**Implemented.** Three queues -- `collect`, `policy`, `verify` -- declared once in `core` and
installed as `CELERY_TASK_ROUTES`, with a task's *name* declaring its workload class so the
class travels with the task rather than with whoever wrote the route. Routing is asserted as
configuration and against celery's own router, because eager Celery never consults a route.
The deployed worker now drains the queues it publishes to.

**Files changed**

- `src/.../core/queues.py` -- new. `Queue`, the namespace mapping, the derived route table, `queue_for`, and the contributed-key constant.
- `src/config/settings/base.py` -- `CELERY_TASK_ROUTES` from `core`, written by hand until the Epic 9 composition step exists, in the voice of the `LOCAL_APPS` entry beside it.
- `pixi.toml` -- the worker drains `celery,collect,policy,verify`; without it the routing is inert.
- `tests/celery_tasks.py` -- new. Register and unregister fixture tasks against the real app.
- `tests/unit/django_apps/test_queues.py` -- the vocabulary, the derivation, the import-purity gate.
- `tests/unit/django_apps/test_task_routing_audit.py` -- `EVIDENCE.04-AUDIT-001`: the registry sweep, the counted exemption both ways, and the router reconciliation.
- `tests/unit/django_apps/test_task_declaration_audit.py` -- AC 2 and AC 3, at both the source and the registry surface.
- `tests/unit/test_celery_app.py`, `tests/unit/test_settings.py`, `tests/unit/test_process_model.py` -- the live view, the settings assertions across every module, and the `-Q` reconciliation.

**Review findings:** 22 patched (1 high, 8 medium, 13 low), 5 deferred, 2 rejected.

**Follow-up review recommended:** true. Patched counts by severity: high 1, medium 8, low 13.
The high-severity patch fires the rule on its own; the score `3 x 8 + 1 x 13 = 37` also exceeds 5.

**Verification.** `pixi run ci` exits 0 -- 2673 tests, coverage 97.43% against a 90% floor,
`queues.py` at 100%. `pixi run gate-postgres` exits 0 against `postgres:17`. Two fixes were
checked independently of the implementing agent rather than taken on report: the resolver was
run against `app.amqp.router` over ten name shapes, including two the agent did not
parametrize (`""` and `cpm..x`), with zero mismatches; and the settings carve-out was
mutation-tested by appending a `CELERY_BEAT_SCHEDULE` and a raised `CELERY_TASK_TIME_LIMIT`
to `production.py`, which reddened exactly the two parametrized cases and nothing else.

**Residual risks.** The four deferred entries, of which the first is the one to read: every
routing claim here is configuration-level, because eager Celery is on for the whole suite and
no test publishes a real message through a route. The reconciliation against celery's own
router is the strongest available substitute and is not the same thing. The second matters at
deployment: one worker draining four queues is not the starvation guarantee `CPM-AD-20` asks
for, and the per-queue split belongs to `CPM-PY314-S02` where real `verify` work arrives.
