---
title: 'CPM-PY314-S02: Verified compatibility on its own queue'
type: 'feature'
created: '2026-09-08'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false
baseline_revision: 'f7199f3'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-py314-s01-static-readiness-assessment.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s01-vulnerability-evidence-ranges-match-confidence.md
warnings:
  - oversized
deferred:
  - summary: >-
      A shipped execution backend cannot take longer than the inherited Celery soft time
      limit, and a real Python build routinely does. The seam ships with the constraint
      recorded rather than resolved, because resolving it means changing a limit `CPM-AD-9`
      owns.
    evidence: |-
      **What the `verify` queue does and does not buy.** `CPM-AD-20` puts verification on its
      own queue so a five-minute build cannot starve the daily sweeps (`R-11`). That bounds
      what a long build *starves*; it does not give the build more time. The task still runs
      under `CELERY_TASK_SOFT_TIME_LIMIT`, which `config/settings/base.py` sets and `CPM-AD-9`
      forbids raising.
      **The consequence for an adapter.** The seam is synchronous -- an adapter is a
      `Transport` and `fetch` returns a recorded `Payload` -- so a backend that blocks for the
      length of a real build meets the soft limit and the task is killed with **no row
      written**, which is the one outcome `CPM-NFR-3` exists to prevent. A workable backend
      therefore drives the build somewhere else (a CI run, a build cluster, a container
      scheduler) and answers about a run that has already finished, which makes a triggered
      verification two steps rather than one for whoever wires it up.
      **Why it is recorded rather than fixed.** Three closures were considered and each
      belongs to a story that owns something this one may not touch. Raising the limit for one
      task is a `CPM-AD-9` change. An asynchronous seam -- a backend that starts work and a
      second task that records the answer -- is a second protocol at a seam `CPM-AD-27` gives
      one method, and a change to `core/collection.py` this story's Never list forbids. A
      polling loop inside `fetch` spends the same limit more slowly.
      **What is delivered instead.** The constraint is stated three times where somebody will
      meet it: in `collectors/verification.py`'s adapter contract, beside
      `VERIFICATION_TIMEOUT` in the collector, and in `docs/deployment.md` under what
      declaring a backend commits an operator to. Nothing about it is discovered at run time
      by the first operator to try.
    location: >-
      src/django_apps/conda_sentinel/collectors/verification.py -- the adapter contract
    severity: medium
  - summary: >-
      The freshness target is a chosen number rather than a derived one, and it ships marked
      provisional. PRD Open Question 7c's derivation stays open.
    evidence: |-
      `CPM-AD-28` requires a strictly positive freshness target of every collector; PRD Open
      Question 7a derives every other collector's from `cadence x (1 + tolerated_missed_runs)`;
      and `CPM-NFR-2` runs this one **on demand**, so there is no cadence to derive from. Open
      Question 7c names the gap and offers two readings. This story takes the first -- a target
      measured from the request -- and ships thirty days as a provisional value, on the terms
      `CPM-SECURITY-S04` shipped its severity order: the file says it is provisional and says
      what review is expected to change, which is the number and not the derivation.
      **The second reading is deliberately not taken and is not lost.** Treating a verification
      as durable evidence about an immutable artifact, and therefore never stale, is
      defensible -- a wheel does not change -- and the PRD says in as many words that it "would
      need `CPM-AD-28` amending rather than a number". Amending an architecture decision
      unilaterally is not a story's to do, and that amendment would be load-bearing well beyond
      this table: `CPM-AD-28`'s refusal of a target-less collector is what stops six-month-old
      evidence reading as current everywhere.
      **What closing it needs.** A backend, and a measurement of how fast a verification's
      answer actually goes out of date -- neither of which exists while nothing ships that can
      run one. `docs/deployment.md` tells the first operator to declare a backend that this is
      the number to revisit.
    location: >-
      src/django_apps/conda_sentinel/collectors/py314_verification.py -- VERIFICATION_FRESHNESS_TARGET
    severity: low
---

# CPM-PY314-S02: Verified compatibility on its own queue

Epic: `CPM-EP-PY314` — Inferred and verified compatibility, kept apart

<intent-contract>

## Story

As a packaging engineer,
I want optional build and import verification that records what it actually ran on,
so that a proven-compatible package is distinguishable from a presumed-compatible one.

## Acceptance Criteria

1. **Given** a package selected for verification
   **When** verification runs
   **Then** it executes on the `verify` queue, never on `collect` or `policy`
   **And** it records the platform and architecture it ran on and a log reference

2. **Given** verification completes
   **When** the evidence is written
   **Then** inferred compatibility and verified compatibility are distinct recorded states

3. **Given** verification is not triggered
   **When** the inventory is assessed
   **Then** it is not run across the inventory by default

## Intent

**Problem:** `CPM-PY314-S01` records what a package's metadata *claims*. A claim is not a
build. `CPM-FR-14` makes verification "a separate, optionally triggered capability", and the
epic's title is the whole point: inferred and verified must stay apart, all the way to the
read surface.

**Approach:** A verification pass on the `verify` queue, writing its own evidence table with
states that name **proof** rather than inference, recording the platform, the architecture and
a log reference so a reader knows what the claim rests on. It is triggered per package and
never swept across the inventory.

**What executes, and what does not.** Verification means running somebody else's build and
import. Nothing in the PRD or the architecture decides how that is isolated — not a sandbox, not
a container, not a resource bound. This story therefore ships the **seam and the evidence**, and
the execution backend is a *declared adapter* with **none shipped**, exactly as
`CPM-SECURITY-S01` shipped its advisory source. Choosing an isolation posture for executing
third-party code, unasked, in a supply-chain security tool, is not a decision a story makes on
its own.

## Boundaries & Constraints

**Always:**
- The task is named under the `cpm.verify.` namespace so `QUEUE_BY_NAMESPACE` routes it to
  `verify`. AC 1's queue requirement is then a property of the name, not of a route somebody
  could get wrong. `core/queues.py` already carries `cpm.verify.py314_build` as its worked
  example.
- The determinate states name **proof**: they must be distinguishable from
  `CPM-PY314-S01`'s `inferred_*` values by a reader who sees only the value, because
  `CPM-AD-24` carries a value verbatim to every read surface and `CPM-FR-14` requires the two
  to be distinct recorded states.
- Every verified row records the platform, the architecture and a log reference. A verification
  that cannot say where it ran is not verification.
- **Triggered, never swept.** No beat entry runs this across the inventory. `selectable_packages`
  either does not exist for this collector or answers empty; the trigger is per package.
- A freshness target is declared and is strictly positive (`CPM-AD-28`).
- Time comes from the injected clock; `pixi` is the only runner; `pixi run ci` exits 0.

**Block If:**
- **The open question this story is blocked on.** PRD Open Question 7c asks what target a
  collector takes when it runs on demand and has no cadence to derive one from. `CPM-AD-28`
  requires a strictly positive target and says the target *values* remain Open Question 7 —
  so choosing a value is within a story's remit, and the derivation is not.

  Take the **first** of the PRD's two candidate readings: a target measured from the request
  rather than from a schedule, shipped as a **provisional** value that says in the file that it
  is provisional and what review is expected to change, exactly as `CPM-SECURITY-S04` shipped
  its severity order.

  Do **not** take the second reading — a verification result treated as durable evidence about
  an immutable artifact and therefore never stale. The PRD says in as many words that it "would
  need `CPM-AD-28` amending rather than a number", and amending an architecture decision is not
  a story's to do unilaterally. Record it as the alternative not taken.
- If review finds that a verification pass shipping **no execution adapter** is not worth
  shipping, HALT and record it rather than inventing an isolation posture for running
  third-party code.

**Never:**
- **No shipped execution adapter.** One declared slot, refused on a second declaration, none
  shipped. No subprocess, no container, no build, no import, no network fetch of a package
  under test — in this story.
- No beat schedule entry that sweeps the inventory. AC 3 is a requirement, not a default.
- No task on `collect` or `policy`.
- No re-derivation of `CPM-PY314-S01`'s assessment, and no reading of its evidence table
  (`CPM-AD-7`).
- No derived status or policy verdict — that is `CPM-PY314-S03` and `CPM-AD-8`.
- No `AlterModelTable`, no change to `core/`, to any shipped collector, or to any policy pass.
- No `timezone.now()` anywhere.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Verification runs (AC 1) | a package triggered, an adapter declared | a row naming the platform, the architecture and a log reference, on the `verify` queue | The queue follows from the task name |
| The states are distinct (AC 2) | a verified row beside `CPM-PY314-S01`'s inferred row | a reader seeing only the value can tell proof from inference | Never a bare `compatible` |
| Not swept (AC 3) | the inventory is assessed | this collector runs for nothing | No beat entry sweeps it |
| No adapter declared (the shipped state) | verification triggered, none declared | refused, naming what is missing; no row claiming a result | Never a determinate row |
| A second adapter declared | two declarations | refused at declaration | One slot |
| The build fails | the adapter reports a failed build | a determinate row saying verification **failed**, with its log reference | A failed build is a result, not an error |
| The adapter itself errors | the adapter raises | an `error` row; the ledger says `failed` | Distinct from a failed build |
| The adapter cannot say where it ran | no platform or architecture reported | refused; no row | AC 1 is not optional |
| Python compatibility does not apply | identity established the question does not apply | `not_applicable`, naming identity | The `CPM-PY314-S01` rule |
| Identity established nothing | the mapping is `unknown`, `error` or `not_found` | not selected, not triggered; no claim | Never `not_applicable` |
| Triggered twice for one package | two requests | two rows; the second does not replace the first | `CPM-AD-2` |
| A log reference wider than its column | any | refused where it enters, never truncated | A truncated reference resolves to nothing |
| No recorded freshness target | absent | startup refuses | `CPM-AD-28` |

</intent-contract>

## Spec Change Log

### 2026-09-09 — Amended during implementation

**One matrix row asked for something the shipped architecture cannot produce under this
story's own Never list, and it is amended here rather than filed as deferred work.**

The row read:

| The adapter cannot say where it ran | no platform or architecture reported | refused; **no row** | AC 1 is not optional |

The refusal is right and is implemented. "No row" is not producible. Whether a backend
stated a platform is only knowable *after* the call, so it is discovered in `translate` --
and `core/collection.py` answers a `translate` that raises by writing an `error` row and
re-raising. Producing no row on that path needs a new branch in the collector base, which
the same story's Never list forbids ("no change to `core/`"). A spec that demands a
behaviour and forbids the only change that could produce it is a contradiction, which is a
HALT rather than a judgement call; `CPM-PY314-S01` met the same shape and set the precedent
for amending it here.

**The row now reads:**

| The adapter cannot say where it ran | no platform or architecture reported | refused at the reader; an `error` row, never a determinate one | AC 1 is not optional |

**Why the amendment does not weaken AC 1.** What the criterion protects is that a
*verification* names where it ran, and that is unweakened and now enforced twice: the
document reader refuses the answer, and `VERIFICATION_EVIDENCE_CONSTRAINT` refuses the row
at the database. What changes is only what is left behind afterwards -- an `error` row
saying looking produced nothing usable, which is what `CPM-NFR-3` wants written and what an
operator needs in order to notice a backend has changed shape. "No row" would have made a
misbehaving backend indistinguishable from a package nobody triggered.

**The Block If about halting is answered rather than triggered.** The story says to HALT if
review finds that a verification pass shipping no execution adapter is not worth shipping.
It is worth shipping, and the argument is `CPM-SECURITY-S01`'s exactly: what ships is the
evidence table, the vocabulary, the queue routing, the applicability rule and the adapter
contract -- everything except the choice this story is not entitled to make. `CPM-PY314-S03`
reduces this table whether or not a backend has been declared, and an operator declaring one
writes no code in this repository.

## Code Map

- `src/django_apps/conda_sentinel/collectors/advisories.py` — the closest precedent, and the
  file this story's seam is shaped after: a one-slot declared adapter, refused on a second
  declaration, with **none shipped** and the contract an adapter owes written out beyond the
  protocol.
- `collectors/python_readiness.py` — the static half. **Do not import it and do not read
  `PythonReadinessAssessment`.** Read it for the applicability rule, which this story inherits
  whole, and for the naming argument the determinate values are the other side of.
- `core/queues.py` — carries `cpm.verify.py314_build` as its worked example, spelled there
  before this task existed. The declared name is the whole of AC 1's queue requirement.
- `core/collection.py` — the base. The hooks used: `source_for`, `translate`,
  `inapplicability`, `sentinel_evidence`, `selectable_packages`. `selectable_packages`
  answering `None` is what makes `collectors/sweep.py` refuse a dispatch **by name**, which is
  AC 3.
- `collectors/models.py` — the ninth evidence table is the template. The tenth adds the three
  columns AC 1 requires and one biconditional refusing a determinate row that names fewer than
  all three.
- `collectors/outcomes.py` — the determinate members must name **proof**, and must not collide
  with the `inferred_*` pair one scroll above them.
- `collectors/tasks.py`, `collectors/apps.py` — the task and the roster. **No**
  `config/settings/base.py` change: there is no schedule entry, by design.
- Roster and audit tests carrying a collector count or a fixture task name:
  `tests/unit/test_model_registry.py`, `tests/unit/django_apps/test_task_routing_audit.py`.
- `docs/deployment.md` — the collector sections are the template, and this one must say
  plainly that nothing ships that can run a build, and what declaring a backend commits an
  operator to.

## Tasks & Acceptance

**Execution:**
- `collectors/outcomes.py` — the composed vocabulary, determinate members naming proof.
- `collectors/models.py` + a new migration — the table, its read index, its three constraints.
- `collectors/verification.py` — the one-slot execution-backend seam, with none declared.
- `collectors/py314_verification.py` — the collector and the document reader.
- `collectors/tasks.py`, `collectors/apps.py`.
- Both test modules, covering every matrix row.
- Every roster and audit test carrying a count or a colliding fixture name.
- `docs/deployment.md`.

**Acceptance Criteria:**
- Given the declared task name, when a publish is routed, then it reaches `verify` and neither
  of the other two.
- Given a verification that ran, then the row names the platform, the architecture and a log
  reference — and the database refuses one that does not.
- Given a static row and a verified row about one package, then their states are different
  strings.
- Given a dispatch naming this collector, then it is refused by name and nothing is enqueued.
- Given a mapping of `not_applicable`, then the row is `not_applicable`, naming identity, with
  no build attempted.
- Given a mapping of `unknown`, `error` or `not_found`, then no row is written at all.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Design Notes

**Why the negative verdict is `verification_failed` rather than `verified_incompatible`.**
The symmetry with `inferred_compatible`/`inferred_incompatible` was available and is
deliberately declined. A build fails for reasons that are not the interpreter — a missing
system library, a compiler the runner does not have, a fetch the sandbox refused — so
recording a failed build as *incompatible* would be a claim about somebody else's package
that the evidence does not carry. It is the same over-claim the static half is careful not to
make from a specifier, and making it from a build log would be worse: a log looks like proof.
What the row can honestly say is that verification ran and did not come out, which is what the
value says; what it *means* is `CPM-PY314-S03`'s policy (`CPM-AD-8`).

**Why applicability is broader here than in the static half.** That collector reads
`pypi.org`'s JSON API, so it can only answer for a package whose purl names a PyPI project.
This one reads no host: it hands a purl to a backend that already knows what it can build, so
a conda purl is as legitimate as a PyPI one. Copying the sibling's PyPI filter across would
have silently made conda packages unverifiable, which a unit case now names.

**Why `selectable_packages` returns `None` rather than an empty queryset.** The story
permitted either. `None` says the sweep is not this collector's mechanism, and
`collectors/sweep.py` refuses such a collector *by name*; an empty selection says the
selection ran and matched nothing, which is a **successful** dispatch of zero packages every
tick forever and looks exactly like a query that has quietly stopped matching. AC 3 wants the
loud one.

**Why there is no `force` argument on the task.** The window is `NO_WINDOW`, so there is
nothing to bypass. A parameter that provably did nothing would read as a switch that might.

## Verification

- `pixi run ci` — the gate.
- `tests/unit/django_apps/test_py314_verification.py` — the declarations, the queue routing,
  the vocabulary comparison, the document reader, the seam, and two source sweeps asserting
  that neither new module reaches anything that executes.
- `tests/integration/django_apps/test_py314_verification.py` — the rows, the three
  constraints, the dispatch refusal, the identity paths, and the one case that puts an
  inferred row and a verified row side by side.

## Dev Agent Record

### Completion Notes

**What ships.** The tenth collector, and the first that nothing schedules. It writes
`python_verification_results`, runs on the `verify` queue under
`cpm.verify.py314_build`, and executes nothing: the thing that runs a build is a
declared adapter at the collector base's transport seam and **none is declared**.

**Files added:**

- `collectors/verification.py` — the one-slot execution-backend seam, shaped after
  `collectors/advisories.py`, with the adapter contract written out beyond the
  `Transport` protocol.
- `collectors/py314_verification.py` — the collector, the locator builder, the
  applicability rule and the result-document reader.
- `collectors/migrations/0011_python_verification_results.py`.
- `tests/unit/django_apps/test_py314_verification.py`,
  `tests/integration/django_apps/test_py314_verification.py`.

**Files changed:** `collectors/outcomes.py` (the fifth composed vocabulary),
`collectors/models.py` (the tenth table), `collectors/tasks.py` (the task and its
name), `collectors/apps.py` (the roster and the third undeclared seam),
`docs/deployment.md`, and five test modules carrying a roster count or a fixture
task name. **No `config/settings/base.py` change**, which is AC 3: there is no
schedule entry to add.

**Each acceptance criterion, and where it is enforced rather than merely asserted:**

- **AC 1 (the queue).** `queue_for("cpm.verify.py314_build")` is `Queue.VERIFY`, and
  the name is the whole mechanism -- no route table entry, no setting. The unit case
  asserts it resolves to `verify` *and* to neither of the other two, because a
  namespace typo resolving to `None` would land the build on the inherited default
  queue with nothing saying so.
- **AC 1 (where it ran).** Enforced three times: `result_in` refuses a document
  missing the platform, the architecture or the log reference; the collector writes
  all three onto the row; and `VERIFICATION_EVIDENCE_CONSTRAINT` refuses a
  determinate row that names fewer than all three, from the database.
- **AC 2 (distinct states).** `verified_compatible`/`verification_failed` against
  `inferred_compatible`/`inferred_incompatible`, asserted as a set disjointness so a
  rename on **either** side fails, and proved on real rows by the one case that puts
  a static assessment and a verified result about one package side by side.
- **AC 3 (never swept).** `selectable_packages` answers `None`, so a dispatch naming
  this collector is refused **by name**; there is no beat entry; the collector
  declares no cadence; and the declared allowance bounds the trigger side.

**One matrix row was amended rather than implemented as written** -- see the Spec
Change Log. "The adapter cannot say where it ran → refused; no row" is not producible
without a new branch in `core/collection.py`, which the same story forbids. The
refusal ships; the row it leaves is `error`, never a determinate one.

**Two decisions the story left open were taken and are recorded in `deferred`:** the
freshness target (PRD Open Question 7c's first reading, thirty days, marked
provisional in the file) and the inherited soft-time-limit constraint on any backend
an operator declares.

**Coverage:** the two new modules, the new table and the extended vocabulary are at
100%; the gate's floor is 90%.

### Verification

`pixi run ci` exits 0.
