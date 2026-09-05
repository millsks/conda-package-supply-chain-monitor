---
title: 'CPM-EVIDENCE-S06: Stale and failed evidence read as themselves'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: true
baseline_revision: '8ccea02154940c4e712ccd2060b2260c8faf7b7c'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s05-collector-base-carrying-external-call.md
warnings: ['oversized']
deferred:
  - summary: >-
      `RunLedgerQuerySet.failed()` orders by `-finished_at`, and nothing constrains a `failed`
      row to carry one -- so the ordering is backend-dependent at that edge.
    evidence: |-
      PostgreSQL sorts NULLs first under `DESC` and SQLite sorts them last, so a `failed` row
      with no `finished_at` would appear at opposite ends of the page in the gate and in a local
      run. The recorder's `finally` always writes the column, so no production path produces
      such a row today -- but nothing in the schema says so, and `unfinished()` exists precisely
      because a killed worker leaves rows the recorder never finished. Resolving it means either
      excluding unfinished rows from `failed()` (which changes what the query means) or
      constraining the column; neither is this story's to decide.
    severity: medium
  - summary: >-
      `freshness_of` will build a contradictory report: a real observation instant alongside the
      `unknown` status its default supplies.
    evidence: |-
      `status` defaults to `UNOBSERVED_STATUS` so the never-observed caller has something to
      pass. A caller that *did* observe but omits the argument gets `status="unknown"` beside a
      real `observed_at` and a possible `stale=True` -- a combination the design says is
      impossible and nothing refuses. The whole story rests on status and staleness being
      independently meaningful, so a report that carries a contradiction is worth closing;
      making `status` required, or defaulting it only when `observed_at` is None, are both
      defensible and the story chose neither.
    severity: medium
  - summary: >-
      A future-dated observation reads as fresh indefinitely, which is the shape of failure
      `CPM-AD-28` exists to prevent.
    evidence: |-
      `is_stale` is `observed_at < now - target`, so any `observed_at` ahead of `now` is not
      stale however old the real observation was. Clock skew between a collector host and a
      policy host, or a source-supplied timestamp trusted into the column, produces exactly the
      "fresh forever" outcome the decision is named for -- by a different route than the unset
      target it does refuse. No refusal and no test covers it.
    severity: medium
  - summary: >-
      The collector registry is not safe against concurrent registration, and names differing
      only in surrounding whitespace register as two collectors.
    evidence: |-
      `register()` reads `_REGISTERED` and then writes it with no lock, so two threads racing
      the same name both pass the duplicate check and one silently replaces the other.
      Separately, `_require_name` refuses only a blank name, so `"pypi"` and `"pypi "` are two
      registrations for one identity that no report can tell apart. Registration happens at
      import today, which is single-threaded, so neither is reachable yet.
    severity: low
  - summary: >-
      `_refuse_collector_without_freshness_target` catches only `CollectorConfigurationError`,
      so any other error reading a registered class escapes as a non-`ImproperlyConfigured` boot
      failure.
    evidence: |-
      `CG-3` and `CPM-AD-28` require a refusal to raise `ImproperlyConfigured`. A `Collector`
      subclass whose `freshness_target` is a descriptor that raises, or an abstract subclass
      registered without its three methods -- which `register()` currently accepts, provided the
      name is non-blank -- would take the boot down with something else. `tests/unit/startup/`'s
      no-softening sweep asserts the condition *contains* no other raise, not that nothing else
      can escape it.
    severity: low
  - summary: >-
      `test_an_empty_registry_does_not_refuse` asserts a process-global that `CPM-EP-CURRENCY`
      will invalidate.
    evidence: |-
      Its first assertion is `registry.registered_collectors() == ()`, which holds only while no
      `AppConfig.ready()` registers anything. The first real collector -- which this story
      explicitly anticipates -- turns a passing test into a failing one, and the failure will
      read as a registry bug rather than as an assertion that outlived its premise. Isolating
      the registry per case is the fix; it is a change to the test helper's contract rather than
      to this story's code.
    severity: low
  - summary: >-
      `registrations()` is public surface in `src/` with no production caller.
    evidence: |-
      `registered_collectors()` serves the boot sweep. `registrations()` exists to make the
      module docstring's "read through this rather than the private mapping" argument true, and
      is otherwise used only by `tests/unit/django_apps/test_registry.py`. Either a consumer
      arrives with `CPM-EP-CURRENCY` or it should go.
    severity: low
---

<intent-contract>

## Intent

**Problem:** Nothing in this product can yet say that evidence is old. A collector declares an
observation window but no freshness target, so unset means "fresh forever" and six-month-old
evidence reads as current -- the `CPM-SM-C1` failure the product exists to prevent. Collection
failures are recorded in the run ledger but reachable only by reading rows directly; no query
surfaces them. And nothing stops a future rollup from exposing a current-status column that
anything at all may write.

**Approach:** Add a declared freshness target to the collector, a registry of collectors for
startup to sweep, and a stage-two refusal for one that declares no target. Derive staleness in
`core` from the latest observation against that target -- as a *property of* a status, never a
status of its own. Give the run ledger a failure query that carries the detail and `trace_id`
the application layer needs. Add the writability audit that `CPM-EVIDENCE-S07`'s rollup will be
the first model to answer to.

## Boundaries & Constraints

**Always:**
- `stale` is a **property of a status, not a status of its own**. This was settled in the UX
  reconciliation: the visible label stays the bare `OutcomeState` value and staleness travels as
  a separate marker and an `observed_at` companion. No new status vocabulary, and no sixth
  `OutcomeState` member -- `CPM-AD-5` fixes five values and a shipped audit enforces them.
- No boolean or nullable-boolean **status** field anywhere (`CPM-AD-5`). A freshness companion
  is not a status field and is not caught by that rule, but nothing named `status`/`*_status`/
  `outcome`/`*_outcome` may be one.
- Every refusal raises `ImproperlyConfigured` at startup, never a warning and never
  log-and-continue (inherited `CG-3`, `CPM-AD-28`).
- Time comes from the injected clock (`CPM-AD-26`). Staleness is decided from an instant that
  was handed in, never from `timezone.now()`.
- A new stage-two condition defers every model import into its own body: the module is imported
  while a settings module is still executing and again during app loading, when the app registry
  is not populated.
- `pixi` is the only Python runner.

**Block If:**
- Satisfying `CPM-AD-28` would require choosing an actual freshness-target *value* for any
  collector. Those are PRD Open Question 7, explicitly "needed before the first collector ships,
  not before the epic starts". Build the mechanism; choose no numbers.

**Never:**
- No concrete collector and no concrete evidence model (`CPM-AD-7` puts the first in
  `CPM-EP-CURRENCY`). Staleness must be derived generically over any `AppendOnlyModel`.
- No rollup table and no policy-run orchestration -- both are `CPM-EVIDENCE-S07`'s. This story
  writes the audit the rollup will answer to, not the rollup.
- No entry-point discovery for the registry (inherited `AD-8`); registration is explicit.
- No change to the observation window, which suppresses *runs* and is a different mechanism from
  a freshness target, which describes *evidence*.
- No `-m` on `test-cov`, and no lowering of the 90% floor.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Evidence inside the target | Latest `observed_at` newer than `now - target` | Reports not stale, and carries the observation instant | No error expected |
| Evidence past the target | Latest `observed_at` older than `now - target` | Reports stale, and carries the observation instant so a surface can say how old | No error expected |
| Exactly on the boundary | `observed_at == now - target` | Not stale -- the target is the age evidence may reach, not the age it may not | No error expected |
| Never observed | No evidence row for this package and collector | Reports `unknown`, not stale and not clean: an absence of observation is not an old observation | No error expected |
| A determinate status past its target | Latest evidence carries `ok`, older than the target | The status value stays `ok`; staleness travels beside it. Never collapsed into one field | No error expected |
| Naive instant | An `observed_at` or `now` with no timezone | Refused | `ValueError` subclass, as `core/ledger.py` and `core/rate_limit.py` refuse one |
| Collector declares a target | A positive `timedelta` | Accepted at construction and at startup | No error expected |
| Collector declares none | `freshness_target` absent or `None` | Refused at construction, and startup refuses the registered class | `CollectorConfigurationError` at construction; `ImproperlyConfigured` at startup |
| Collector declares a zero or negative target | `timedelta(0)` or negative | Refused: unlike `NO_WINDOW`, "evidence is stale the instant it is written" is not a statement anyone means | `CollectorConfigurationError` |
| Startup, registry empty | No collector registered yet | Startup proceeds. No collector exists until `CPM-EP-CURRENCY`; an empty sweep is not a failure | No error expected |
| Startup, one bad collector | A registered class with no target | `ImproperlyConfigured` naming the class and the declaration | Refusal, never a warning |
| Failed runs queried | Ledger holds failed and succeeded runs | Only the failed ones are returned, each exposing `detail`, `trace_id`, `collector`, `finished_at` | No error expected |
| Failures with no trace | A failed run whose `trace_id` is blank | Still returned; the blank is data, not a reason to omit the row | No error expected |
| Writability audit | A model defines a current-status field writable from outside a policy run | The audit fails and names the field | Audit failure |
| Writability audit, nothing to police | No model holds current derived state yet | The detector is measured against a synthetic model, so a scan finding nothing cannot pass vacuously | Audit failure if the detector has gone blind |

</intent-contract>

## Code Map

- `src/.../core/collection.py` -- `Collector`'s declared ClassVars and their `_require_*`
  module functions (`_require_window` at the end of the file is the closest shape for a new
  `_require_freshness_target`). Line 118 of the module docstring states that this story owns the
  startup refusal and that S05 deliberately left it out, "declaring it in two places would leave
  two enforcement points" -- that sentence needs updating once the refusal exists.
- `src/.../core/outcomes.py` -- `OutcomeState` (five fixed values), `PRECEDENCE`, `aggregate`,
  `EMPTY_AGGREGATE = UNKNOWN`. Read only. `unknown` is what a never-observed package reports.
- `src/.../core/clock.py` -- the injected `Clock` and `is_aware`; the refusal pattern for a naive
  instant is `core/rate_limit.py`'s `window_key` and `core/ledger.py`'s `_require_aware`.
- `src/.../core/models.py` -- `RunLedgerQuerySet` (one helper, `unfinished()`, at :591) with
  `objects = RunLedgerQuerySet.as_manager()` on the abstract base at :672. `CollectionRun` at
  :680 already carries `collector`, `package_id`, `status`, `detail`, `trace_id`, `started_at`,
  `finished_at` -- AC 2 needs a query, not a migration.
- `src/.../core/runs.py` -- `RunState`, whose `FAILED` member the failure query filters on.
- `src/config/startup/stage_two.py` -- conditions are module-private zero-arg `_refuse_<state>`
  callables raising only `ImproperlyConfigured`; registration is appending to the
  `_STAGE_TWO` tuple at :605. `run_stage_two()` at :613 returns early when not deployed. Model
  imports MUST be function-local with `# noqa: PLC0415` -- the module is imported before the app
  registry is populated.
- `tests/unit/startup/forbidden_states.py` -- `ForbiddenState(state_id, condition, stage,
  description, feature=None)` records in `FORBIDDEN_STATES`. `state_id` is a lowercase hyphenated
  noun phrase naming the forbidden condition (`unapplied-migrations`,
  `designated-group-absent`).
- `tests/unit/startup/test_refusal_coverage_audit.py` -- reconciles declarations against
  `@pytest.mark.forbidden_state` claims in both directions, via a child `pytest --collect-only`.
  `UNCONDITIONAL_STATE_COUNT = 12` at :84 and `UNCONDITIONAL_CONDITIONS = frozenset(range(1, 8))`
  at :89 are arithmetic that a new state must move.
- `tests/unit/startup/test_no_softening.py` -- the `REFUSALS` builder table at :291 needs an
  entry (state configured + expected message fragment), or the state joins
  `DELEGATED_TO_THE_INTEGRATION_SUITE`; :567 and :577 reconcile "built here XOR delegated".
- `tests/unit/startup/test_stage_dispatch.py` -- :52, :67, :84 monkeypatch `_STAGE_TWO` and
  assert every member is invoked.
- `tests/unit/django_apps/test_outcome_field_audit.py` -- sweeps derived-status fields by name
  (`status`, `outcome`, `*_status`, `*_outcome`) and asserts CharField + four sentinels + no
  null/blank + in-vocabulary default. It constrains type and vocabulary and says **nothing about
  writability**, which is why AC 3 needs a new audit. `RECORDED_RUN_LEDGER_STATUS` at :153
  exempts the two ledger `status` columns.
- `tests/unit/django_apps/test_mutation_path_audit.py` -- the closest existing writability-shaped
  audit; its subject is evidence tables and its shape (source scan + `RECORDED_EXEMPTIONS` +
  synthetic modules the detector is measured against) is the model for AC 3's.
- `tests/model_registry.py` -- `first_party_models()`, the three evidence marks, and the
  `not_evidence = True` escape hatch, whose users must also appear in `RUN_LEDGER_MODEL_LABELS`.
- `tests/collectors.py` -- `collector_class(declared_*)` factory, which gains a
  `declared_freshness_target` parameter, and the fixture evidence model AC 1 is derived over.

## Tasks & Acceptance

**Execution:**
- `src/.../core/freshness.py` -- **new.** The staleness derivation: a `FreshnessError`
  (`ValueError` subclass, as `RateLimitError` and `OutcomeVocabularyError` are), an `is_stale`
  taking `observed_at`, `target` and `now` and refusing a naive instant, a `latest_observation`
  generic over any `AppendOnlyModel` for one `(package, collector)`, and a report type carrying
  the observation instant beside the verdict. Staleness is derived in one place so that eight
  collectors and every read surface cannot each decide it differently -- and it is `core`'s
  because `CPM-AD-5` puts every shared vocabulary there.
- `src/.../core/collection.py` -- add the declared `freshness_target` ClassVar and
  `_require_freshness_target`, refusing absence, a non-`timedelta`, and a zero or negative
  interval; correct the module docstring sentence that says this story's refusal lives
  elsewhere -- an unset target behaving as "fresh forever" is exactly `CPM-AD-28`'s named
  failure.
- `src/.../core/registry.py` -- **new.** The explicit collector registry startup sweeps:
  a `register` that refuses a duplicate name and a non-`Collector`, and a reader returning the
  registered classes. Explicit because entry-point discovery is forbidden (inherited `AD-8`),
  and separate from `collection.py` so that importing the base does not import a registry.
- `src/config/startup/stage_two.py` -- add `_refuse_collector_without_freshness_target` and
  append it to `_STAGE_TWO`, with every model or registry import deferred into the body --
  `CPM-AD-28` wants the failure at boot, before a worker picks up work, not at the first
  construction in a queue.
- `tests/unit/startup/forbidden_states.py` -- declare the `collector-without-freshness-target`
  state so the refusal is claimable.
- `tests/unit/startup/test_refusal_coverage_audit.py` -- move `UNCONDITIONAL_STATE_COUNT` and,
  if the new condition is numbered, `UNCONDITIONAL_CONDITIONS`; the audit fails until both the
  declaration and its claim exist, which is the point.
- `tests/unit/startup/test_no_softening.py` -- add the `REFUSALS` builder entry, or delegate the
  state to the integration suite and record that.
- `tests/unit/django_apps/test_derived_status_writability_audit.py` -- **new.** AC 3: no current
  -status field is directly writable from outside a policy run. Nothing holds current derived
  state until `CPM-EVIDENCE-S07`, so the detector is measured against synthetic models parsed in
  the test, exactly as `test_mutation_path_audit.py` and `test_collector_base_audit.py` measure
  theirs -- a scan that has gone blind must fail here rather than report a clean repository.
- `src/.../core/models.py` -- add the failure query beside `unfinished()` on
  `RunLedgerQuerySet`, so a collection failure is answerable in the application layer rather
  than only by reading the log (`CPM-FR-38`).
- `tests/unit/django_apps/test_freshness.py` -- **new.** The matrix's derivation rows: inside,
  past, exactly on the boundary, never observed, a determinate status past its target, and the
  naive-instant refusal.
- `tests/unit/django_apps/test_collection.py` -- the new declaration refusals, parametrized
  beside the existing ones.
- `tests/unit/django_apps/test_registry.py` -- **new.** Registration, the duplicate-name
  refusal, and the non-collector refusal.
- `tests/integration/django_apps/test_collector_health.py` -- **new.** AC 2 against real rows:
  only failed runs are returned, each exposing `detail` and `trace_id`, including a failure whose
  `trace_id` is blank.
- `tests/integration/startup/` -- the stage-two refusal against a registered collector with no
  target, carrying `@pytest.mark.forbidden_state("collector-without-freshness-target")`, and the
  empty-registry case that must NOT refuse.
- `tests/collectors.py` -- add `declared_freshness_target` to the factory and a registered
  fixture collector, cleaned up so a registration cannot leak between cases.

**Acceptance Criteria:**
- Given a collector with a declared freshness target, when the latest evidence for a package and
  collector is older than that target, then it reports stale and carries the observation instant,
  and the status value it accompanies is unchanged.
- Given collection runs that failed, when the collector-health query runs, then the failures are
  returned from the application layer with their `detail` and `trace_id`.
- Given a model defining a current-status field writable from outside a policy run, when the
  audit runs, then it fails and names the field; and the detector is proven against a synthetic
  so an empty repository cannot pass it vacuously.
- Given a registered collector declaring no freshness target, when the application starts, then
  startup raises `ImproperlyConfigured` naming the collector (`EVIDENCE.06-AUDIT-001`).
- Given `pixi run ci`, when it runs, then it exits 0 with coverage at or above the 90% floor.

## Spec Change Log

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 15: (high 2, medium 6, low 7)
- defer: 7: (high 0, medium 3, low 4)
- reject: 3: (high 0, medium 1, low 2)
- addressed_findings:
  - `[high]` `[patch]` `latest_observation`'s query was executed by no test, and a docstring
    claimed it was proved in `tests/integration/django_apps/test_collector_health.py`, which
    contains no reference to it. Both `Max` and the per-package `filter` were unasserted:
    swapping `Max` for `Min` would have compared the *oldest* observation against the target,
    and dropping the filter would have let a busy package keep a neglected one looking fresh.
    Added `tests/integration/django_apps/test_freshness_query.py`, which fails on either
    mutation.
  - `[high]` `[patch]` `Collector.freshness()` — the wiring between the declared target, the
    collector's own table and the comparison — had no caller and no test. The same new module
    drives it, with a stale/fresh pair chosen so that substituting the observation window for
    the declared target flips one of them (`tests/collectors.py` declares them an order of
    magnitude apart).
  - `[medium]` `[patch]` `freshness_of` refused a naive `now` only when the package had been
    observed: the awareness check lived in `is_stale`, past the never-observed early return. A
    guard that depends on whether a row exists passes every test written against the populated
    case and reaches production through the empty one. Checked on both paths and pinned.
  - `[medium]` `[patch]` `_require_package_reference` matched `field.name` only, so the
    `package = models.ForeignKey(...)` that `CPM-EP-IDENTITY` implies — field `package`, column
    `package_id` — would have been refused as declaring no package reference, at the moment the
    product finally had a package to refer to. Now accepts `name` or `attname`.
  - `[medium]` `[patch]` The boot refusal reported one offender at a time, costing an operator a
    restart per collector; with eight collectors coming that is eight boots to learn what one
    could have said. Now collects every offender and names them all in one refusal, pinned by a
    two-offender case.
  - `[medium]` `[patch]` The derived-status writability scan matched `status=` in *any* call, so
    it flagged HTTP `Response(status=403)` and even a queryset `filter(status=...)` **read** —
    seven modules, none of which writes derived state. Landing that would have meant seven
    exemptions on day one: an audit exempted into meaning nothing. Narrowed to attribute
    assignments plus keywords to ORM write methods, leaving exactly one honest exemption, with
    the HTTP-status and status-read shapes added as negative cases.
  - `[medium]` `[patch]` The same audit's anti-vacuity synthetic used
    `bulk_update(rows, [...], licence_outcome=...)`, a call shape Django rejects — proving the
    detector against a form that cannot occur. Replaced with a real `create(...)`. Its
    evidence-exclusion case was near-tautological (comparing two module constants); it now
    exercises the predicate against a derived-shaped and an evidence-shaped model.
  - `[medium]` `[patch]` That audit duplicated the derived-status naming convention from
    `test_outcome_field_audit.py` byte for byte with nothing reconciling it — the exact drift its
    own docstring names as the failure to avoid. Added a case that reads the sibling's
    declarations out of its source and asserts they agree.
  - `[low]` `[patch]` Recorded the four write shapes the scan does **not** see
    (`save(update_fields=[...])`, `setattr`, `update(**{...})`, raw SQL) rather than documenting
    only the constructor gap. A reader who believes the scan is total stops looking.
  - `[low]` `[patch]` `registered_collector`'s `finally` called `unregister` unguarded. Every
    case using it asserts a refusal, so the block is left by an exception nearly every time, and
    a raise from the `finally` would replace the assertion under test with a cleanup error.
  - `[low]` `[patch]` Factual corrections: "five endings" where `RunState` has four endings and a
    non-ending; a stale "twelve" and a stale "Fourteen" left behind by this change's own
    arithmetic; a misleading "the fifth is `timedelta(0)`" when zero is the second parameter; a
    paraphrase left inside quotation marks in the FR-16 citation; and a dangling "that story".
  - `[low]` `[patch]` `test_an_empty_ledger_reports_no_failures` wrote a succeeded row first, so
    it did not test an empty ledger and the genuinely empty table was covered nowhere. Split
    into the two claims, each named for what it arranges.
  - `[low]` `[patch]` `FINISHED_AT_FIELD`'s comment claimed both queryset methods read it while
    `unfinished()` still spelled the column literally; `PACKAGE_FIELD` was declared for the
    typo argument and then not used in the filter it guards. Both now use their constants.

Three findings were traced and rejected:

- **An `OverflowError` from a `timedelta` near `timedelta.max`.** Reachable only by a caller
  passing a target no collector can declare — `require_freshness_target` is the only producer of
  the value in this product, and every path to it is a class attribute somebody wrote.
- **Guarding `latest_observation` against an abstract evidence model.** `Collector` refuses a
  non-`AppendOnlyModel` at construction and an abstract model has no manager to reach; the
  `AttributeError` a hand-rolled caller would meet names the cause well enough.
- **Making the write scan understand model constructors.** A constructor call is syntactically
  indistinguishable from `Response(...)`, which is what made version one useless. The gap is
  recorded instead, and closed from the other side by `editable=False`.

## Design Notes

**Why `stale` is not a status value, decided rather than inferred.** The UX reconciliation
settled it and recorded it as the user's own decision: "`--warn` means determinate amber only.
Stale is a property of a status", and the visible chip label is "the bare `OutcomeState` value;
staleness moves to the mark, the footline and the hidden text". A sixth `OutcomeState` member, or
a `FreshnessState` enum, would put a fifth axis back into a channel that `CPM-FR-6` exists to
keep un-collapsed -- and would break the shipped audit that asserts the five fixed values. So
this story derives staleness and returns it *beside* the status, and exports carry the
`<domain>_observed_at` and `<domain>_stale` companions the UX already specified.

**Why the boundary is "not stale".** A target is the age evidence may reach. Evidence observed
exactly `target` ago has reached it and no more, so it is fresh; the first instant past it is
stale. Stated because the opposite convention is equally spellable and only one of them can be
asserted, and because `Collector._inside_window` already had to make the mirror-image decision
for an inclusive `finished_at__gte`.

**Why a zero target is refused, unlike a zero window.** `NO_WINDOW` means "observe on every run",
which is a thing an operator means. A zero freshness target means "evidence is stale the instant
it is written", which nobody means and which would make every surface permanently amber. The two
sentinels look alike and behave oppositely, so the refusal is written out rather than inherited
by symmetry.

**Why the registry is separate from the base.** `collection.py` is imported by anything that
defines a collector; a registry living there would mean importing the base populates a global.
Keeping it in its own module lets startup sweep a registry without the base importing one, and
keeps registration explicit -- entry-point discovery is forbidden by inherited `AD-8`, and this
product's adoption convention is already two explicit lines.

**Why AC 3's audit is written before it has anything to police.** The rollup is
`CPM-EVIDENCE-S07`'s, and writing its guard in the same story that creates it is how a guard
comes to be shaped around the thing it is meant to constrain. Written here, it is shaped by the
rule; the synthetic models it is measured against are what keep it from passing vacuously in the
meantime, which is the same anti-vacuity move
`tests/unit/django_apps/test_collector_base_audit.py` already makes.

## Verification

**Commands:**
- `pixi run ci` -- expected: exit 0. Five steps, coverage at or above 90%.
- `pixi run gate-postgres` -- expected: exit 0. The suite against `postgres:17`.
- `pixi run gate-redis` -- expected: exit 0, nothing skipped, so `CPM-EVIDENCE-S08`'s
  shared-allowance proof is unaffected by this story.

## References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S06]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-5]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-11]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-28]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-37]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-38]
- [Source: _bmad-output/planning-artifacts/ux-designs/ux-conda-package-supply-chain-monitor-2026-09-04/reconcile-ui-mockups.md] -- the decision that stale is a property of a status
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Auto Run Result

Status: done
Blocking condition: none

**What this completes.** `CPM-FR-37` and `CPM-FR-38`. Evidence past its freshness target and
failed collection are now readable as themselves rather than inferable from logs, and a
collector that declares no target refuses the boot (`CPM-AD-28`) instead of behaving as fresh
forever.

**Files changed**

- `src/.../core/freshness.py` -- new. `is_stale`, `freshness_of`, `latest_observation` and the
  frozen `FreshnessReport`. Staleness is derived in one place and reported *beside* a status,
  never as one: the UX reconciliation settled that `stale` is a property of a status, and
  `CPM-AD-5` fixes `OutcomeState` at five values.
- `src/.../core/registry.py` -- new. The explicit registry the boot sweep reads. Separate from
  `collection.py` so that importing the collector base does not populate a global, and explicit
  because entry-point discovery is forbidden (inherited `AD-8`).
- `src/.../core/collection.py` -- the `freshness_target` declaration, the public
  `require_freshness_target` both moments call, and `Collector.freshness()`.
- `src/config/startup/stage_two.py` -- the tenth condition, sweeping registered classes and
  naming every offender in one refusal.
- `src/.../core/models.py` -- `RunLedgerQuerySet.failed()`, so a collection failure is
  answerable in the application layer.

**Review findings:** 15 patched (2 high, 6 medium, 7 low), 7 deferred, 3 rejected.

**Follow-up review recommended:** true. Two high-severity patches; either fires the rule alone.

**The two high findings were both holes in the proof rather than broken code.**
`latest_observation` -- the query the whole read path rests on -- was executed by no test, while
a docstring told the next reader it was proved in a file that never mentions it. Swapping `Max`
for `Min` or dropping the per-package filter would have shipped green. `Collector.freshness()`,
the wiring that decides *which* target and *which* table a verdict comes from, had no caller and
no test at all.

**Verification.** `pixi run ci` exits 0 -- 3215 tests, coverage 97.88% against a 90% floor.
`pixi run gate-redis` exits 0 with nothing skipped, so `CPM-EVIDENCE-S08`'s shared-allowance
proof is unaffected. The suite also passes against a local PostgreSQL 17.8.

**Residual risks.** The seven `deferred` entries. Three are worth naming: `failed()`'s NULL
ordering differs between the two gates; `freshness_of` can still build a report carrying a real
observation instant beside an `unknown` status; and a future-dated `observed_at` reads as fresh
indefinitely -- the same "fresh forever" outcome `CPM-AD-28` refuses by a different route.
