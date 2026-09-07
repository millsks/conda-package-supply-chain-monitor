---
title: 'CPM-CURRENCY-S07: Feedstock presence and maintenance'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '17c0ba928aef7a05e4a6eaa481ca70e669805fcb'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s03-feedstock-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s06-currency-judged-against-right-authority.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s07-watchlist-inventory-source.md
warnings:
  - oversized
deferred:
  - summary: >-
      The shipped inactivity threshold is a starting point rather than an answer, and PRD Open
      Question 10's first half remains open.
    evidence: >-
      `CPM-FR-40` requires the threshold to be a versioned policy parameter and this story ships
      the mechanism plus one reviewed value. Nothing in the code or the suite depends on the
      number — both test tiers deliberately use a different one — so it is revocable by review
      without a code change, which is what the requirement asks for. What is not yet true is that
      the open question is settled: no sprint change proposal records a decision, and the value's
      provisional status is carried by prose rather than by anything a planning artifact reads.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/policies/data/policy-parameters.toml
    severity: medium
  - summary: >-
      Nothing validates a policy version before a run starts, so an operator's typo costs a whole
      run.
    evidence: >-
      The version is now load-bearing — an unrecorded one fails every package — and it is supplied
      as a free string to the task that starts a run. Establishing the parameter set once per run
      makes the failure cheap and legible, which this story does, but the run still starts and
      still fails; refusing at enqueue time needs a validation point on the task boundary that no
      story yet owns.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/tasks.py -- run_policy
    severity: medium
  - summary: >-
      The feedstock presence pass reads its evidence one package at a time, adding two queries per
      package to the currency pass's five with nothing batching either.
    evidence: >-
      The orchestration loops packages one at a time and this pass reads its one surface inside
      that loop, so a run over `CPM-NFR-1`'s ten thousand packages is twenty thousand round trips
      for this pass alone, on top of the forty thousand `CPM-CURRENCY-S06` recorded for the
      currency pass. `collectors/selection.py` established the set-based read for exactly this
      shape. The count is pinned by a case at three cardinalities so a regression is visible, and
      the optimisation belongs with the story that first runs a policy pass at inventory scale —
      but it is recorded here rather than only against `CPM-CURRENCY-S06`, because this story's
      own per-package cost is this story's to answer for.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/policies/feedstock.py --
      FeedstockPresencePass.evaluate
    severity: medium
---

# CPM-CURRENCY-S07: Feedstock presence and maintenance

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

<intent-contract>

## Story

As a packaging engineer,
I want to know whether a feedstock exists and whether anyone is maintaining it,
so that I can find the gaps worth filling.

## Acceptance Criteria

1. **Given** a package at `verified` or `inventory-derived` confidence
   **When** the feedstock policy runs
   **Then** it derives one of absent, present-and-maintained, present-and-inactive, or
   staged-recipe-pending

2. **Given** a package at `unmapped` confidence
   **When** the policy runs
   **Then** it reports `unknown` and never absent

3. **Given** the inactivity threshold
   **When** it is applied
   **Then** it is read as a versioned policy parameter, not a constant in code

## Intent

**Problem:** `CPM-CURRENCY-S03` records whether a feedstock exists and when it was last
pushed to, and nothing turns that into the answer `CPM-UJ-2` asks for: which packages have no
feedstock worth filling, and which have one nobody is maintaining. `CPM-FR-40` fixes four
determinate outcomes and requires the inactivity threshold to be a versioned policy parameter;
no parameter mechanism exists, and PRD Open Question 10 has been waiting on this story for its
second half.

**Approach:** A second pass in the `policies` application, beside `CurrencyPass`. It reads the
feedstock snapshot at the run's cut-off, applies an inactivity threshold looked up **by the
run's policy version** from reviewed data rather than from a constant, writes its own derived
table keyed `(package, policy_run)`, and contributes one rollup column. `CPM-AD-4`'s gate is
not re-implemented: the pass computes what the evidence supports and the rollup writer's
existing single gate is what makes an `unmapped` package's outward claim `unknown`.

## Boundaries & Constraints

**Always:**
- A pass reads evidence at the run's stated cut-off and never reads the current time to
  decide anything. Re-running the same version at the same cut-off reproduces identical
  output (`CPM-AD-8`).
- The inactivity threshold is looked up by the run's policy version from data changed by
  review, never from a constant in code and never from a setting. A version with no recorded
  parameters is refused loudly rather than defaulted (AC 3).
- What counts as recipe activity is what `CPM-CURRENCY-S03` recorded: a push to the feedstock
  repository. This story applies a threshold to it and invents no second definition.
- `CPM-AD-4`'s confidence gate is **one function in `core`, never re-implemented per pass**.
  This pass does not gate; AC 2 is satisfied by the rollup writer's existing gate, and this
  story proves it end to end rather than duplicating it.
- The derived row records the confidence it was computed under, so a reader of the pass's own
  table can see what the rollup gate would have done with it.
- The pass writes only its own derived table and contributes rollup columns by returning
  them, never by writing the rollup (`CPM-AD-21`).
- Every derived status is a `CharField(choices=...)` over a type composed by
  `core.outcomes.outcome_type`, bound once at module scope (`CPM-AD-5`).
- A verdict this pass cannot support is a sentinel, never a guess: no observation is
  `unknown`, an errored observation is `error`, and a present feedstock whose activity the
  collector could not date is `unknown` rather than inactive.
- `pixi` is the only runner; `pixi run ci` exits 0 at the end.

**Block If:**
- Choosing the threshold's *value* would settle PRD Open Question 10's first half. This story
  ships the mechanism and one reviewed parameter set whose value is recorded as provisional
  and changeable by review without a code change. If review finds that a story shipping any
  value at all has answered the open question, HALT.

**Never:**
- No change to any collector, to any evidence table, or to what any of them records.
- No second definition of recipe activity, and no reading of any surface other than the
  feedstock snapshot.
- No outbound call of any kind.
- No re-implementation of the confidence gate, and no suppression of a row: the gate is
  expressed as writing a value (`CPM-AD-4`).
- No change to `CurrencyPass`, to what it writes, or to its rollup column.
- No `timezone.now()` anywhere.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Present and maintained (AC 1) | feedstock snapshot `ok`, last recipe activity within the threshold of the cut-off | derived row `present_and_maintained`; the row records the threshold applied, the activity instant and the age it computed | No error |
| Present and inactive (AC 1) | feedstock snapshot `ok`, activity older than the threshold | `present_and_inactive`, with the same three facts recorded | No error |
| Absent (AC 1) | feedstock snapshot `not_found` with no staged recipe recorded | `absent` | No error |
| Staged recipe pending (AC 1) | feedstock snapshot `not_found` carrying a staged recipe URL | `staged_recipe_pending`, never `absent` | The two are distinct outcomes |
| Present but undatable | feedstock snapshot `ok` with no usable activity instant | `unknown`, and the row says the activity could not be dated | Never inactive by default |
| Unmapped package (AC 2) | package at `unmapped` confidence with any feedstock evidence | the **rollup column** reads `unknown`; the derived row records what the evidence supported and the confidence it was computed under | The gate is `core`'s, applied once by the rollup writer |
| Inventory-derived package | package at `inventory-derived` confidence | the rollup column carries the determinate value undegraded, with the confidence recorded beside it | `CPM-AD-4`: a label, never a downgrade |
| No observation | no feedstock snapshot at the cut-off | `unknown`; a row is still written | Never `absent` from an absence of looking |
| Errored observation | latest feedstock snapshot `error` | `error` | An error is not an absence |
| Inapplicable observation | latest feedstock snapshot `not_applicable` | `not_applicable` | Carried through, never folded |
| Evidence after the cut-off | a snapshot written after the run's cut-off | not read; the verdict is what the cut-off's evidence supports | `CPM-AD-21` |
| Threshold by version (AC 3) | two runs at two policy versions whose recorded thresholds differ, over the same evidence at the same cut-off | the two runs reach different verdicts, and each row records the threshold it applied | This is what makes the parameter versioned data |
| Unknown policy version | a run whose version has no recorded parameters | the pass refuses, that package's evaluation fails, and the run finalizes `partial` or `failed` as the orchestration decides | Refused, never defaulted |
| Malformed parameter data | the recorded threshold is missing, not a positive interval, or of the wrong type | refused at read with a message naming the version and the fault | Refuse, never repair |
| Replay (`CPM-AD-8`) | the same version re-run at the same cut-off | identical derived rows | Already an operation |
| Boundary | activity exactly the threshold old at the cut-off | one stated side of the boundary, asserted, and the choice written down | Stated rather than discovered |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/policies/currency.py` -- the sibling
  pass and the closest template: the cut-off-bound read with its stated tie-break, the pure
  functions, the derived-row write with literal keywords (so the writability audit sees it),
  the composed outcome type bound in `policies/outcomes.py`, and the reduction order declared
  as data with the single-ordering audit taught about it by name. Read it and
  `CPM-CURRENCY-S06`'s Review Triage Log first: its twenty-four findings are the mistakes not
  to repeat, particularly claims made in prose that the code does not guarantee.
- `src/django_apps/conda_package_supply_chain_monitor/policies/outcomes.py` -- where a
  composed vocabulary and its precedence live, and why they live in a leaf module rather than
  beside the pass. Add this pass's vocabulary here on the same terms.
- `src/django_apps/conda_package_supply_chain_monitor/policies/models.py` -- `PackageCurrency`
  is the template for the derived table: `(package, policy_run)` unique, `PROTECT` relations,
  check constraints that the database actually refuses, `editable=False` on what the pass
  alone decides, and a `detail` column.
- `src/django_apps/conda_package_supply_chain_monitor/policies/apps.py` -- registers
  `CurrencyPass` in `ready()` under a guard; the second pass is registered beside it, and the
  declared order of passes in a run is what `CPM-AD-21` makes readable.
- `src/django_apps/conda_package_supply_chain_monitor/core/confidence.py` -- `CPM-AD-4`'s
  single gate (`gated_status`, `require_known_confidence`). Read only, and **not** to be
  called from this pass: `core/rollup.py` applies it once on the way in, and its own docstring
  says a pass never sees a confidence.
- `src/django_apps/conda_package_supply_chain_monitor/core/rollup.py` --
  `contributable_columns()` now returns the currency column; this story adds the second. The
  gate is applied here.
- `src/django_apps/conda_package_supply_chain_monitor/core/models.py` -- `PackageHealth`; add
  the feedstock column beside `currency_status`, over the composed type, with its migration.
- `src/django_apps/conda_package_supply_chain_monitor/core/policy_run.py` -- the run carries
  `policy_version`; the pass reads it off the run it is handed. `execute_policy_run` now takes
  an explicit cut-off (`CPM-CURRENCY-S06`), which is what makes the two-version case in the
  matrix expressible.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` --
  `FeedstockSnapshot`: `state`, `last_recipe_activity_at`, `staged_recipe_url`, and the
  constraint that a staged recipe may be recorded only on a row that found no feedstock. Read
  only.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/data/` and
  `collectors/watchlist.py` -- the repository's precedent for **reviewed data shipped in the
  wheel**: a delimited file, read through one contract, refused rather than repaired, with a
  README beside it stating the column contract and the editing rules. The versioned policy
  parameters follow that precedent, including shipping inside the built artifact and being
  asserted there.
- `tests/integration/test_import_resolution.py` -- asserts data files ship inside the built
  wheel; the new parameter data must be asserted the same way.
- `tests/unit/django_apps/test_currency_policy.py`,
  `tests/integration/django_apps/test_currency_policy.py` -- the module shapes to mirror,
  including the constraint-refusal cases, the query-count case, the replay case and the
  source sweeps.
- `tests/unit/django_apps/test_single_ordering_audit.py` -- `RECORDED_ORDERINGS`, reconciled
  in both directions; a second declared precedence is recorded there or it fails.
- `tests/unit/test_model_registry.py`, `tests/unit/django_apps/test_pass_ownership_audit.py`,
  `tests/unit/django_apps/test_derived_status_writability_audit.py`,
  `tests/unit/django_apps/test_policy_contribution.py`, `tests/unit/django_apps/test_rollup_row.py`
  -- the audits and rosters a second pass, a second derived table and a second contributable
  column all reach.
- `docs/deployment.md` -- the currency pass's section is the template; this one must also tell
  an operator where the threshold lives, how to change it, and that changing it changes
  verdicts without a code change.

## Tasks & Acceptance

**Execution:**
- `policies/parameters.py` + `policies/data/policy-parameters.toml` (+ a README beside it) --
  the versioned parameter mechanism: one reviewed file mapping a policy version to its
  parameters, one read contract, refusals for an unknown version and for a malformed or
  non-positive threshold, and the file shipped inside the wheel.
- `policies/outcomes.py` -- the composed feedstock vocabulary and its declared precedence,
  recorded in the single-ordering audit.
- `policies/models.py` + migration -- the derived table keyed `(package, policy_run)`,
  carrying the verdict, the threshold applied, the activity instant, the computed age, the
  confidence the row was computed under, the evidence row it rests on, and a `detail`.
- `core/models.py` + migration -- the rollup's second domain status column.
- `policies/feedstock.py` -- the pure functions (the observation at a cut-off, the age against
  a threshold, the verdict) and `FeedstockPresencePass`.
- `policies/apps.py` -- register the second pass beside the first.
- `tests/unit/django_apps/test_feedstock_policy.py` -- new: every matrix row reachable without
  a database, every parameter refusal, the boundary, and the module's own source sweeps.
- `tests/integration/django_apps/test_feedstock_policy.py` -- new: the pass through a real
  policy run; AC 2 proved **through the rollup column** for an `unmapped` package with a
  paired `inventory-derived` case showing the value is not degraded; the two-version case from
  the matrix; the cut-off excluding later evidence; each constraint refused by the database;
  the query count pinned; and replay.
- The audits, rosters and `docs/deployment.md`.

**Acceptance Criteria:**
- Given a `verified` package whose feedstock was pushed to inside the threshold, when the pass
  runs, then the row reads present-and-maintained and records the threshold it applied.
- Given a `verified` package whose feedstock has not been pushed to inside the threshold, when
  the pass runs, then the row reads present-and-inactive.
- Given a package with no feedstock and a recorded staged recipe, when the pass runs, then the
  row reads staged-recipe-pending and never absent.
- Given an `unmapped` package with any feedstock evidence, when the pass runs, then the rollup
  column reads `unknown`, and an `inventory-derived` package's determinate value is unchanged.
- Given two runs at two policy versions whose recorded thresholds differ, over the same
  evidence at the same cut-off, when both complete, then they reach different verdicts and
  each row records the threshold it applied.
- Given a run whose policy version has no recorded parameters, when the pass runs, then it
  refuses rather than applying a default.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

### 2026-09-06 — `FeedstockOutcome` declares no precedence order

**Task item amended.** The Execution list says "`policies/outcomes.py` -- the composed
feedstock vocabulary **and its declared precedence**, recorded in the single-ordering audit",
and the Code Map repeats it: "a second declared precedence is recorded there or it fails". No
precedence is declared, and `RECORDED_ORDERINGS` still holds exactly one entry.

A precedence order is a **reduction** rule. `CURRENCY_PRECEDENCE` exists because `CurrencyPass`
reduces four surfaces' verdicts about one package to one rollup column, and a reduction needs a
ranking. This pass reduces nothing: one package has one feedstock, one observation at the
cut-off answers for it, and the verdict the derived row carries is the verdict the rollup column
carries. An order declared here would be data no function reads — which is the defect
`CPM-CURRENCY-S06`'s review found and patched ("a constant claiming to be the single
surface-to-column map was read by nothing in the source") — and the next reader would take it
for a ranking this product applies somewhere.

It would also have **weakened the audit the task item names**.
`test_every_recorded_ordering_still_declares_the_order_it_records` asserts that a recorded module
declares exactly *one* ordering, so a second order in `policies/outcomes.py` would have required
relaxing that assertion: a real check traded for a declaration nothing consumes.

The decision and its expiry are written into `policies/outcomes.py` where the vocabulary is
composed: the day a story reduces several feedstock verdicts to one, that story declares the
order and records it in the audit. Everything else in the task item stands — the vocabulary is
composed by `core.outcomes.outcome_type`, bound once, in that module, for that module's stated
import-cycle reason.

### 2026-09-06 — A policy run must now name a version the reviewed file records

**Consequence recorded, not a task amended.** AC 3 and the I/O matrix require that a run whose
policy version has no recorded parameters is refused rather than defaulted. `CPM-AD-8` makes the
policy version an operator's string, and until this story any string worked — three integration
modules said so in as many words. It no longer does: `FeedstockPresencePass` is adopted at boot,
so a run at an unrecorded version fails **every** package and finalizes `failed`.

That is what the spec asks for and it is not softened. What it cost is recorded here because it
is a change to the product's operational contract rather than to this pass alone:
`docs/deployment.md` and `policies/data/README.md` both state it plainly, `tests/passes.py`
carries the one version the shipped file records, and the integration modules that execute
policy runs either name that version or record their own fixture versions into a substituted
file. Shipping fixture versions in the reviewed file was rejected: a version there is a reviewed
decision.

### 2026-09-07 — The collector gains a structural signal, against the Never list

**Amended by review, and the Never list is the thing being set aside.** The story
says "No change to any collector, to any evidence table, or to what any of them records."
`collectors/models.py` gains `FeedstockSnapshot.absence_established` and a constraint,
`collectors/feedstock.py` sets it on one branch, and `collectors.0006` is a third migration.

The finding that forced it is the first of the review's two high-severity ones, and it is a
verdict this pass had no evidence for. `not_found` on a feedstock snapshot is reachable four
ways -- conda-forge answered that the conventional repository is not there; the repository could
not be read; the staged-recipes queue could not be read; the queue held more than one candidate
or overflowed its page -- and only the first is evidence of an absence. The collector already
named them apart, in `detail`, in prose. The pass read neither `detail` nor `source`, so a
two-candidate queue and a GitHub outage both produced `absent` -- which `docs/deployment.md`
calls "the gap to fill: a recipe has to be written". That dispatches somebody to write a recipe
that may already exist or already be queued, which is exactly what `staged_recipe_pending` was
invented to prevent.

**Prose matching was the alternative and was rejected.** The distinction could have been read by
comparing `detail` against `ABSENT_FEEDSTOCK_DETAIL`, which would have coupled a policy pass to
a collector's *sentences* across an application boundary and broken silently on a reword. The
review asked for a structural signal in preference, and named a collector change as in scope for
this finding if one was needed.

**What was not changed.** No collector's *behaviour* moved: every state, every `detail`, every
locator and every fact each row already carried is what it was, and the new column is a second
spelling of a distinction `detail` was already making. `ConventionalAnswer` gained an
`established` flag so the collector reads its own branch structurally rather than matching its
own prose, and `_queue_answered` is the structural half of `_queue_detail`. The column is
`False` on every row that is not an absence, which the database enforces, and `False` on every
row written before the migration -- the safe direction, and the honest one: no earlier row
recorded which of the four shapes it was, so none may claim to have established anything.

## Review Triage Log

### 2026-09-06 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 24: (high 2, medium 16, low 6)
- defer: 3: (high 0, medium 3, low 0)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[high]` `[patch]` **`absent` was derived from an absence nobody established.** The
    collector writes `not_found` in four distinct situations and had named them apart in
    `detail` alone — genuinely absent; a queue with more than one candidate; a queue whose
    page overflowed; and a queue or repository that could not be read at all. This pass read
    neither `detail` nor `source`, so a GitHub outage produced the verdict the operator
    documentation defines as "this is the gap to fill: a recipe has to be written". The
    collector now carries the distinction structurally, set only where conda-forge answered
    that the repository is not there **and** the queue answered conclusively; every
    unestablished shape reads `unknown`. This set aside the story's own Never list and is
    recorded in the Spec Change Log; no collector's state, detail, locator or recorded fact
    changed.
  - `[high]` `[patch]` **A feedstock nobody re-observed read as inactive.** The verdict
    measured the push instant against the cut-off without asking how old the observation was,
    so a snapshot from a year ago whose collector had since stopped running was
    indistinguishable from a genuinely abandoned feedstock. The observation's own age is now
    measured beside the push's, and a stale observation reads `unknown` with the reason
    recorded. The rule deliberately stops at the maintenance verdict: an old observation
    cannot support a claim about the interval since the last push, while absence is a claim
    about what the source held when somebody looked.
  - `[medium]` `[patch]` Sixteen further findings, each addressed. Two were guards that did
    not guard: the case protecting the new rollup column from colliding with the sibling
    pass's built its set from the wrong model and never imported the other one, so a reviewer
    demonstrated the collision could be introduced with the suite green; and the memoization
    case ran under a fixture that had already repointed the file, so it measured the
    substituted parse rather than the shipped one its name described. The rest: a failed
    parameter read was not remembered, so a file repaired mid-run would have judged half the
    inventory under a rule set the other half never saw; a run-wide fault was discovered once
    per package, which a new once-per-run hook now establishes before the loop; the memo was
    keyed on nothing and handed out its live mutable mapping; a naive activity instant failed
    with a message about datetimes rather than a refusal naming the row; an oversized recorded
    interval raised a bare overflow; an empty or padded version key was accepted; a
    whitespace-only staged-recipe URL read as pending; no database rule tied a determinate
    verdict to the observation it rests on; the two outcomes that dispatch work were never
    asserted on the read surface; a future-dated push read healthy forever and silently; the
    pass relied on another application's constraint without pinning it; the editor's own
    contract omitted that a change takes effect at the next process start; and the operator
    documentation booked this story's query cost against the previous story's ledger entry
    while contradicting itself about how the threshold is changed.
  - `[low]` `[patch]` Six further findings: the provisional status of the shipped value is now
    recorded where the open question is tracked rather than in prose three files carry; the
    fourth copy of the cut-off-bound read is reconciled; a constant named for one refined
    value while its own vocabulary refines two; the test helper that renders the parameter
    file escaped nothing; the parameter directory resolved at import, so an unresolvable
    location failed a web process that would never have read it; and the restored migration
    helper no longer guarded against an application carrying two conflicting leaves.

### 2026-09-07 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 24: (high 2, medium 16, low 6)
- defer: 3: (high 0, medium 3, low 0)
- addressed_findings:
  - `[high]` `[patch]` `absent` was derived from rows whose own `detail` said the absence had
    never been established. Three of the four ways `not_found` is reachable are the run failing
    to find out -- an unreadable repository, an unreadable queue, an ambiguous or overfull queue
    -- and all three produced the one verdict that dispatches somebody to write a recipe. The
    collector now records `absence_established` structurally and the pass reports `unknown` for
    every unestablished shape, including the one carrying a staged recipe: a queued recipe is
    only *pending* if there is no feedstock, and that is the half nobody confirmed.
  - `[high]` `[patch]` A feedstock nobody re-observed read as inactive. The verdict measured the
    push against the cut-off without asking how old the *observation* was, so a snapshot from a
    year ago whose collector had stopped running was indistinguishable from an abandoned recipe
    -- an inventory-wide false finding produced by a collector outage. An observation older than
    the applied threshold now reads `unknown` and the row says so, with the rule deliberately
    stopping at the maintenance verdict: an old observation cannot support a claim about the
    interval since the last push, while `absent` is a claim about what conda-forge held when
    somebody looked, which age makes older rather than false.
  - `[medium]` `[patch]` Sixteen further findings, each addressed: the column-collision guard
    built its set from the wrong model and never imported the other, so the collision it exists
    to prevent could be introduced with it green; a refused parameter read was not memoized, so a
    file repaired mid-run would have judged half an inventory under a rule set the other half
    never saw; a run-wide fault was discovered once per package, which `PolicyPass.prepare` now
    establishes once per run and fails the run for; the memo was keyed on nothing while reading a
    module global and handed out its live mutable mapping; a naive activity instant raised a
    `TypeError` about datetimes rather than a refusal naming the row; an absurd day count raised
    a bare overflow; an empty or padded version key was accepted; a whitespace-only staged-recipe
    URL read as a queued recipe; no database rule tied a determinate verdict to the observation
    it rests on; the two verdicts that dispatch work were never asserted on the rollup column; a
    future-dated push was recorded silently; the activity copy leaned on another application's
    constraint; `policies/data/README.md` omitted both the restart rule and the test-constant
    obligation; the operator documentation booked this story's query cost against
    `CPM-CURRENCY-S06`'s deferred entry; the memoization case measured the substituted file; and
    the documentation contradicted itself about how a threshold changes while restating the
    literal value in three unsynchronised places.
  - `[low]` `[patch]` Six further findings: the provisionality of the shipped value is now a
    `deferred:` entry naming PRD Open Question 10 rather than prose in three shipped files; the
    fourth copy of the cut-off-bound read declares its ordering as `READ_ORDERING` and is
    reconciled against the sibling pass's by a case, with the reason a fourth copy is deliberate
    written where the copy is; `REFINED_STATE` became `REFINED_SENTINEL`, which is what it names;
    the parameter-file test helper escapes its version key; the parameter directory resolves
    lazily, so a missing `data/` tree fails the policy run rather than the boot; and the restored
    migration helper refuses a graph carrying two leaves for one application.


## Design Notes

**Why the pass does not gate.** `CPM-AD-4` says the gate is one function in `core`, called by
the orchestrating run, "never re-implemented per pass", and expressed as writing a value rather
than suppressing a row. So AC 2 is a claim about the **rollup column**, and the honest way to
satisfy it is to prove that column reads `unknown` for an `unmapped` package rather than to add
a second gate the architecture forbids. The derived row records the confidence it was computed
under so that a reader of the pass's own table can see what the gate would do, which is what
keeps the run auditable without duplicating the rule.

**Why the threshold is a file rather than a setting or a table.** `CPM-AD-8` says rule sets are
versioned data, and `CPM-AD-14` makes reviewed reference data in the repository the product's
one governed shape for exactly this — the inventory watchlist is the precedent, down to
shipping inside the wheel and being changed by pull request. A setting would be per-deployment
rather than per-version, and would make two components at the same policy version disagree; a
database table would be a write path nothing audits. Keying on the run's own `policy_version`
is what makes AC 3's "read as a versioned policy parameter" observable: two versions over one
cut-off reach different verdicts, which no constant could do.

**What this story does not settle.** PRD Open Question 10 has two halves. `CPM-CURRENCY-S03`
answered the second — recipe activity is a push to the feedstock — and this story answers
neither half by fiat: it ships the mechanism and one provisional value that an operator changes
by review without a code change. The Block If exists because a reviewer may reasonably hold
that shipping any value at all settles the question.

**Why a present feedstock with no datable activity is `unknown`.** The collector records an
absent or unusable push instant honestly rather than inventing one, and a threshold cannot be
applied to nothing. Calling it inactive would be the guess the whole evidence chain is built to
refuse, and calling it maintained would be worse.

## Verification

**Commands:**
- `pixi run test` -- expected: exit 0, the new unit module collected and passing.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: exit 0, no diagnostics.
- `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected".
- `pixi run ci` -- expected: exit 0; coverage >= 90%, `policies/feedstock.py` and
  `policies/parameters.py` at 100%.
- `pixi run gate-postgres` -- expected: exit 0; the new constraints are enforced there.

**Observed, after the review round:**
- `pixi run ci` -- exit 0. 5,812 cases pass, 2 pre-existing skips, coverage 98.92%, and
  `policies/feedstock.py`, `policies/parameters.py`, `policies/outcomes.py`,
  `policies/models.py`, `policies/apps.py`, `core/policy.py`, `core/policy_run.py`,
  `collectors/feedstock.py` and `collectors/models.py` each at 100%.
- `pixi run manage makemigrations --check --dry-run` -- "No changes detected".
- `pixi run gate-postgres` -- exit 0 against `postgres:17`, where the five constraints on
  `package_feedstock_presence` and `feedstock_snapshots`, and the `interval` typing behind
  `inactivity_threshold`, are actually enforced.

**Manual checks (if no CLI):**
- `git diff --stat 17c0ba9` names the new pass, its parameter data, and the **three** migrations
  -- `core.0007`, `policies.0002` and, after review, `collectors.0006`.
- Confirmed: `git diff 17c0ba9 -- policies/currency.py identity/ src/config/ component.toml` is
  empty. `collectors/` is no longer empty and that is the review's decision, recorded in the Spec
  Change Log: two files gain a structural signal, and no collector's behaviour, state, `detail`
  or recorded fact changes.

## Dev Notes

**Satisfies:** `CPM-FR-40`

**Governed by:**

- `CPM-AD-4` — Confidence gates every outward claim, by writing a value
- `CPM-AD-8` — Policy is a separate versioned pass

**Constrained:** the inactivity threshold and what counts as recipe activity are PRD Open
Question 10.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S07]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-4]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-40]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context) — `claude-opus-5[1m]`.

### Debug Log References

- `pixi run ci` — exits 0. See the Verification section for the counts.
- `pixi run manage makemigrations --check --dry-run` — "No changes detected".
- `pixi run gate-postgres` — the suite against `postgres:17`, which is where the four
  constraints on `package_feedstock_presence` are actually enforced and where the seven refusal
  cases land. SQLite enforces `CHECK` too, but only PostgreSQL enforces the `interval` typing
  behind `inactivity_threshold`.

### Completion Notes List

**What was built.** `CPM-FR-40`'s feedstock presence and maintenance policy: the second policy
pass, the versioned-parameter mechanism `CPM-AD-8` has been describing since the first policy
story, and the rollup's second domain status column. `FeedstockPresencePass` reads the feedstock
snapshot at the run's cut-off, looks an inactivity threshold up **by the run's policy version**
from a reviewed file shipped in the wheel, records one verdict per package in
`package_feedstock_presence` with the threshold, the activity instant, the age it measured and
the confidence it was computed under, and returns one rollup column. It makes no outbound call,
writes no evidence, never writes the rollup, and never reads the current time.

**AC 2 is proved through the rollup column, and the pass does not gate.** `CPM-AD-4` puts the
gate in one function in `core`, applied by the rollup writer and "never re-implemented per
pass" — so "an unmapped package reports `unknown` and never `absent`" is a claim about
`package_health.feedstock_presence_status` and not about anything this pass computes. The
integration module drives a real policy run and asserts the column, with a paired
`inventory-derived` package whose determinate verdict travels **undegraded** beside its recorded
label. A gate that replaced anything short of `verified` would have satisfied the `unmapped`
assertion alone and thrown away every answer this product can give about the majority of its
inventory. The pass's own row records the ungated verdict and the confidence, so a reader can
see the two and say why they differ.

**Four determinate outcomes, and `not_found` is refined rather than replaced.**
`CurrencyOutcome` refines only `ok`; this vocabulary refines `ok` into
`present_and_maintained`/`present_and_inactive` **and** `not_found` into
`absent`/`staged_recipe_pending`. `not_found` stays a member by construction and stays legal in
every column that declares it; the pass simply always has the more specific answer. Which
sentinels a pass can produce is a property of the pass, not of the vocabulary, and
`policies/outcomes.py` says so where the type is composed.

**Three judgement calls worth flagging to review.**

1. *No precedence order is declared, against the Execution list's wording.* Recorded in the Spec
   Change Log with the argument: a precedence is a **reduction** rule, this pass reduces nothing,
   and declaring one would have been data no function reads *and* would have forced a real
   assertion in `test_single_ordering_audit.py` to be relaxed. `RECORDED_ORDERINGS` still holds
   exactly one entry and still asserts that its module declares exactly one order.

2. *The boundary is closed on the maintained side.* A feedstock pushed to exactly the threshold
   ago at the cut-off reads `present_and_maintained`; inactivity begins strictly after it. The
   choice is arbitrary in the way every closed boundary is — what is not arbitrary is that it is
   written down in four places a decision-maker actually reads (the pass, the data README, the
   operator documentation, and a case in each tier).

3. *An activity instant later than the cut-off yields a negative age and reads
   `present_and_maintained`, and nothing refuses it.* A source reporting a future push instant is
   clock skew, and a feedstock pushed to after the evidence boundary is certainly not one nobody
   has touched. Refusing would turn somebody else's clock into a failed package; no constraint
   forbids a non-positive `activity_age`, and a case pins the verdict as well as the arithmetic
   so the choice cannot drift silently.

**The `Block If` is live, and this is where a reviewer should look first.** The story says: "If
review finds that a story shipping any value at all has answered [PRD Open Question 10's first
half], HALT." A value is shipped — `feedstock_inactivity_days = 180` for policy version
`2026.09` — and it is recorded as provisional in four places: a comment beside the number with
its reasoning, `policies/data/README.md`'s own section, `docs/deployment.md`, and this note.
Nothing in the codebase depends on the number: no constant names it, no test asserts it, and
both test tiers deliberately use a *different* threshold (90 days) so that a pass which had gone
back to reading a constant would fail. Changing it is a pull request against one line, which is
what "changeable by review without a code change" was asked to mean. The judgement a reviewer
has to make is whether shipping a starting point at all settles the question, and it is not one
this session can make for them.

**The policy version became load-bearing, and that is a change to the operational contract.**
Recorded as the second Spec Change Log entry. A run naming a version
`policies/data/policy-parameters.toml` does not record now fails **every** package and finalizes
`failed`, because the refusal is per package (`CPM-AD-23`) and the fault is every package's. That
is exactly what "refused, never defaulted" costs, and it is stated where an operator will meet
it. What it cost the suite is three integration modules: `test_currency_policy.py` and
`test_policy_run.py` now name the shipped version — which is what keeps the shipped file read end
to end — and `test_rollup.py`, which genuinely needs two versions, records its own into a
substituted file through `tests/policy_parameters.py`. Shipping fixture versions in the reviewed
file was rejected: a version there is a reviewed decision.

**Two migrations, and one of them was hand-edited for a reason worth reading.**
`policies.0002` was generated depending on `core.0007` — the rollup column *this same story*
adds — because the autodetector names each app's newest migration. That made this table a
dependent of a `core` migration after `core.0003`, and
`tests/integration/django_apps/test_run_ledger_migration.py` rolls `core` back to `0003` and
restores `core`'s leaf: the new table was unapplied and never put back, stranding the session's
database and failing seven unrelated cases in three other modules. The dependencies are now the
minimum the table references, which is the rule `policies.0001` already stated — **and the
restore helper was fixed rather than left depending on that rule**. It now restores every leaf in
the graph, which is the state `migrate` with no arguments produces and the only description of
"fully migrated" that stays true as applications are added. The project memory note about pinned
restore targets is now one class of bug narrower.

**The review round -- what the 24 findings changed.** Two were high, and both were the same
failure wearing different clothes: a verdict written down that the evidence did not support.
`absent` was being derived from rows whose own `detail` said the absence had never been
established, and `present_and_inactive` from observations nobody had refreshed. Each dispatched
work -- one sends somebody to write a recipe, the other to revive a feedstock -- on evidence that
said only that the run had failed to find out. The first needed a collector change, recorded in
the Spec Change Log; the second needed the observation's own age, which is now measured beside
the push's.

Of the mediums, three changed shapes rather than lines. `PolicyPass.prepare` is a new hook on
the machinery: a fault that is every package's is now met once, before the loop, and fails the
run -- where before an unrecorded policy version produced a traceback, a failed row and a file
read per package for a condition knowable before the first one. The parameter memo is keyed on
the path and remembers refusals, because `functools.cache` re-runs on exceptions and a file
repaired mid-run would otherwise have judged half an inventory under a rule set the other half
never saw. And the parameter directory resolves lazily, so an installation missing its `data/`
tree fails the policy run that needed it rather than refusing to boot a web process that never
would have read it.

The rest were the ordinary kind and are listed in the Review Triage Log. Two are worth naming
because they were guards that did not guard: the column-collision case built its set from the
wrong model, so the collision it exists to prevent could have been introduced with it green; and
the memoization case ran under a fixture that had already repointed the file, so it measured the
substituted parse while its name described the shipped one.

**Risks and what is left.**

- Recorded as a `deferred:` entry: nothing checks a policy version against the parameter file
  before a run is enqueued, so an operator typo costs a whole run rather than failing at the
  point of the mistake.
- `core` now reads two vocabularies from `policies` at module scope rather than one. This is the
  first repetition of the dependency-direction concern `CPM-CURRENCY-S06` deferred ("the same
  edge lands once per policy epic"); it is not re-deferred here, because it is the same entry
  and duplicating it would make the ledger look like two problems.
- The reviewed file is read **once per process**, so a corrected file needs a restart. That is
  argued rather than inherited — `CPM-AD-8` makes one version mean one rule set, and a per-package
  re-read would let an edit split a run across two of them — and it is deliberately unlike
  `collectors/watchlist.py`, which is re-read on every sweep and says why.
- `package_feedstock_presence` accumulates one row per package per run with `PROTECT` on every
  relation and no retention path, exactly as `package_currency` does. Recorded in
  `docs/deployment.md` under its own heading, pointing at the currency table's reasoning rather
  than restating it.
- It carries no index beyond the `(package, policy_run)` unique constraint and Django's own
  foreign-key indexes. The per-package read is served by the constraint's index; "which packages
  have no feedstock" is the rollup column's question, not this table's.
- The pass adds two evidence queries per package to the currency pass's five, still unbatched.
  Pinned at three cardinalities so a regression is visible; the optimisation is
  `CPM-CURRENCY-S06`'s deferred entry.

### File List

**New — the pass, its parameters and its reviewed data**

- `src/django_apps/conda_package_supply_chain_monitor/policies/feedstock.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/parameters.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/data/policy-parameters.toml`
- `src/django_apps/conda_package_supply_chain_monitor/policies/data/README.md`
- `src/django_apps/conda_package_supply_chain_monitor/policies/migrations/0002_package_feedstock_presence.py`
  — dependencies hand-edited to the minimum the table references; see the Completion Notes.
- `src/django_apps/conda_package_supply_chain_monitor/core/migrations/0007_package_health_feedstock_presence_status.py`
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/0006_feedstock_absence_established.py`
  *(review round)* — dependencies hand-edited to the minimum the field references.

**Modified — the collector, added by the review round**

- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` —
  `FeedstockSnapshot.absence_established` and `ESTABLISHED_ABSENCE_CONSTRAINT`. The story's Never
  list forbade this and review set it aside for one finding; the Spec Change Log records why.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py` —
  `ConventionalAnswer.established`, `_queue_answered`, and the one branch that sets the column.
  No state, no `detail`, no locator and no recorded fact changed.

**Modified — the machinery, added by the review round**

- `src/django_apps/conda_package_supply_chain_monitor/core/policy.py` — `PolicyPass.prepare`, the
  once-per-run hook, and the rule for deciding which of the two methods a check belongs in.
- `src/django_apps/conda_package_supply_chain_monitor/core/policy_run.py` — every pass is
  prepared before the package loop, and a preparation failure is deliberately not contained.

**Modified — the vocabulary, the two tables, the adoption and the rollup's prose**

- `src/django_apps/conda_package_supply_chain_monitor/policies/outcomes.py` — `FeedstockOutcome`
  and its eight named values, and the argument for why it declares no precedence.
- `src/django_apps/conda_package_supply_chain_monitor/policies/models.py` —
  `PackageFeedstockPresence`, its four named constraints and `MEASURED_VERDICTS`.
- `src/django_apps/conda_package_supply_chain_monitor/policies/apps.py` — the second adoption,
  and why the declared order is worth recording while it is still free.
- `src/django_apps/conda_package_supply_chain_monitor/core/models.py` —
  `PackageHealth.feedstock_presence_status`, and the docstring that said the table had one domain
  column.
- `src/django_apps/conda_package_supply_chain_monitor/core/rollup.py` — two prose claims that
  became their own opposite once a second column was contributable.
- `docs/deployment.md` — the operator section: the verdict table, where the threshold lives, how
  to change it, that changing it changes verdicts without a code change, the boundary, and that a
  run must name a recorded version.

**New — tests and helpers**

- `tests/unit/django_apps/test_feedstock_policy.py`
- `tests/integration/django_apps/test_feedstock_policy.py`
- `tests/policy_parameters.py` — the substituted parameter file, and why it is a substitution
  rather than an addition to the reviewed one.

**Modified — the audits, rosters and modules a second pass and a second column reach**

- `tests/passes.py` — `ADOPTED_PASS_NAMES`, `ADOPTED_PASSES`, `A_RECORDED_POLICY_VERSION`.
- `tests/unit/django_apps/test_policies_app.py` — the module roster, the migration roster, the
  `data/` tree, and the second adoption.
- `tests/unit/django_apps/test_derived_status_writability_audit.py` — one recorded write
  exemption for `policies/feedstock.py`.
- `tests/unit/django_apps/test_pass_ownership_audit.py`,
  `tests/unit/django_apps/test_policy_registry.py`,
  `tests/unit/django_apps/test_policy_contribution.py`,
  `tests/unit/django_apps/test_rollup_row.py` — "the rollup's one column" is now two, in the
  assertions and in the prose.
- `tests/integration/test_import_resolution.py` — the reviewed TOML is asserted inside the built
  wheel.
- `tests/integration/django_apps/test_currency_policy.py`,
  `tests/integration/django_apps/test_policy_run.py` — the policy version is now the shipped one.
- `tests/integration/django_apps/test_rollup.py` — its two fixture versions are recorded into a
  substituted parameter file; the gate case asserts the second column too.
- `tests/integration/django_apps/test_run_ledger_migration.py` — the teardown restores every leaf
  in the migration graph rather than `core`'s, and refuses a graph carrying two leaves for one
  application.
- `tests/integration/django_apps/test_feedstock.py` *(review round)* — `absence_established` is
  asserted on each of the four `not_found` shapes where the collector writes it, and its
  constraint is proved by the database refusing a row.

## Auto Run Result

Status: done
Blocking condition: none

**What was implemented.** `CPM-FR-40`'s feedstock presence and maintenance policy — the second
pass in the `policies` application, and the mechanism for versioned policy parameters the
architecture requires but nothing had. `FeedstockPresencePass` reads the feedstock snapshot at
the run's cut-off, looks an inactivity threshold up **by the run's policy version** from
reviewed data shipped in the wheel, and writes one row per package carrying the verdict, the
threshold applied, the activity instant, the age it measured, the identity confidence it was
computed under, the evidence row it rests on, and a detail. Four determinate outcomes, plus the
shared sentinels.

**The threshold is versioned data, and that is observable rather than asserted.** Two runs at
two policy versions over one cut-off reach different verdicts and each row records the
threshold it applied — which no constant and no per-deployment setting could do. An unrecorded
version is refused rather than defaulted, so the version became load-bearing; a new once-per-run
hook establishes the parameter set before the first package so that fault fails the run rather
than each package in it.

**The confidence gate is not re-implemented.** `CPM-AD-4` says the gate is one function in
`core`, called by the orchestrating run, never per pass. So the pass computes what the evidence
supports and the rollup writer's existing gate is what makes an `unmapped` package's outward
value `unknown` — proved end to end on the rollup column, with an `inventory-derived` package
beside it showing the determinate value is not degraded. The derived row records the confidence
it was computed under, so the pass's own table stays auditable without duplicating the rule.

**Files changed.**

- `policies/feedstock.py` *(new)* — the pure functions and the pass.
- `policies/parameters.py`, `policies/data/policy-parameters.toml` + README *(new)* — the
  versioned parameter mechanism, following the inventory watchlist's precedent: reviewed data
  shipped in the wheel, one read contract, refusals rather than defaults.
- `policies/models.py`, `policies/outcomes.py`, `policies/apps.py` + migration — the derived
  table, the vocabulary, the second registered pass.
- `core/models.py` + migration — the rollup's second domain status column.
- `core/policy.py`, `core/policy_run.py` — the once-per-run preparation hook, additive.
- `collectors/models.py`, `collectors/feedstock.py` + migration — the one thing the review
  forced outside this story's stated boundary: the collector now records structurally whether
  an absence was established, because four different situations had been distinguished only in
  prose.
- `docs/deployment.md` — where the threshold lives, how it changes, and what each verdict does
  and does not claim.
- New unit and integration modules; the audits and rosters a second pass and a second
  contributable column reach.

**Review findings.** 24 patched (2 high, 16 medium, 6 low), 3 deferred, 2 rejected. Four review
layers ran in parallel over the 5,100-line diff.

**Follow-up review recommended:** true. Two high-severity patches. Patched counts: high 2,
medium 16, low 6; score `3 x 16 + 1 x 6 = 54`, far over the threshold of 5.

**Both high findings were the same failure this epic exists to prevent: a claim the evidence
does not support.** `absent` — the verdict that dispatches somebody to write a recipe — was
reachable from a GitHub outage and from a queue with two candidates, because the collector had
distinguished those cases only in prose and the pass read none of it. And a feedstock nobody had
re-observed for a year read as inactive, indistinguishable from one genuinely abandoned, in a
product that has a freshness mechanism for exactly that distinction.

**Two of the medium findings were guards that did not guard.** The case protecting this story's
rollup column from colliding with its sibling's built its set from the wrong model, and a
reviewer demonstrated the collision could be introduced with the suite green. The memoization
case ran under a fixture that had already repointed the file it claimed to measure.

**Verification.** `pixi run ci` exits 0 — 5812 passed, 2 pre-existing skips, coverage 98.92%,
with every new module at 100%. `makemigrations --check --dry-run` reports "No changes detected".
`pixi run gate-postgres` passes against `postgres:17`, where the new constraints are enforced.
All three were re-run by the orchestrating session after the patch round.

**Residual risks.** Three `deferred` entries, all medium. The shipped threshold is a starting
point and PRD Open Question 10's first half is still open: nothing in the code or the suite
depends on the number, so it is revocable by review, but no decision has been recorded. Nothing
validates a policy version before a run starts, so an operator's typo costs a whole run rather
than being refused at the boundary. And this pass adds two evidence reads per package with no
batching, on the same terms the sibling pass recorded.
