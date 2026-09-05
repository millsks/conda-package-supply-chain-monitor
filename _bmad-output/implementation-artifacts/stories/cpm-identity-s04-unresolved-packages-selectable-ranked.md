---
title: 'CPM-IDENTITY-S04: Unresolved packages are selectable and ranked'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: 'a3c4793847b42857115bfe313a2721131409140d'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s02-resolution-records-where-came-from.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s06-inventory-arrives-arrives-as-evidence.md
warnings: []
deferred:
  - summary: >-
      The queue exposes each package's concluded mappings, not the *candidate* mappings with
      per-candidate evidence that `CPM-FR-4` and the approved UX design describe.
    evidence: |-
      PRD `CPM-FR-4` says "the queue shows candidate mappings and the evidence for each where any
      exist", and the UX design specifies it concretely: a panel titled "Candidate mappings the
      resolver found", ranked by associator score, with a per-row Evidence column citing source
      tables and instants, and a radio button per alternative for the reviewer to pick. Nothing in
      the tree produces such a proposal. `PackageMapping` records what a resolution *concluded* --
      one row per kind, rewritten in place -- and the evidence tables the mockup cites do not exist
      yet; `InventorySnapshot` is still the only evidence model in the repository. So the clause's
      "where any exist" antecedent is unsatisfied today, and this story exposes what does exist
      rather than inventing a `MappingCandidate` table, which would have created queue-adjacent
      state against this story's own third criterion and `CPM-AD-1`.
      What is genuinely owed: a producer of candidates, a carrier for per-candidate evidence, and
      the associator score the UX ranks them by. **No downstream story currently claims any of it**
      -- neither `CPM-APP-S05` (the queue surface) nor `CPM-APP-S03` (evidence links) mentions
      candidates in its acceptance criteria -- so this needs an owner rather than an assumption
      that the surface story will discover it.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/selection.py -- UnresolvedPackage.mappings
    severity: medium
  - summary: >-
      How the two breadth counts combine into a single rank is `CPM-FR-20`'s score function and
      PRD Open Question 8; this story orders by the pair rather than deciding it.
    evidence: |-
      `CPM-FR-4` says the queue is "ranked by internal usage breadth" and PRD Open Question 3b says
      `internal_component_count` and `internal_lob_count` "together are" that breadth -- but neither
      the PRD nor the architecture spine says how to combine them, and `CPM-FR-20`'s score function
      is explicitly Open Question 8, which the PRD says "encodes an organizational risk posture that
      does not exist yet". The ordering shipped here is lexicographic over the pair, then the
      surrogate key: total, deterministic, and committing to no weighting. When OQ-8 is answered the
      ordering may need to become a score, and that is a product decision rather than a defect here.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/selection.py -- _breadth_ordering_key
    severity: low
  - summary: >-
      `prefetch_related` emits one `IN (...)` over every selected package id, which at ten-thousand-
      package sizing is a parameter list every backend bounds differently.
    evidence: |-
      The snapshot read was rewritten during review to take the package ids it was told about rather
      than joining on confidence, which removed this hazard there. The mapping prefetch cannot be
      written that way -- Django builds the `IN` list from the outer queryset's keys -- so it remains.
      `CPM-NFR-1` sizes the inventory at ten thousand packages and the review queue is a subset of
      it, so this is not hypothetical at full size, though it is harmless at any size the product
      has run at. The fix is chunking the prefetch or paginating the selection, and pagination is
      `CPM-AD-12`'s and belongs to the surface story that first renders this queue.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/selection.py -- unresolved_packages
    severity: low
  - summary: >-
      The cut-off contract has no production caller, so it has never run against a real
      `core/policy_run.py` cut-off.
    evidence: |-
      `unresolved_packages` takes a cut-off and refuses to derive one, which is what `CPM-AD-25`
      requires -- but nothing outside its own tests calls it. The first real caller is
      `CPM-APP-S05`'s queue surface. Until then the contract is proven only against cut-offs the
      tests author themselves, and the specific thing unexercised is the hand-off: that the instant
      `execute_policy_run` derives is the instant this read is given, so a replayed policy run and
      the queue it renders agree about what was true.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/selection.py -- unresolved_packages
    severity: low
---

<intent-contract>

## Intent

**Problem:** Packages arrive at `unmapped` and some reach `inventory-derived`, but nothing can ask
which ones still need a human. `CPM-FR-4` wants that set worked as a ranked queue rather than read
as a report, and the ranking input — internal usage breadth — lives in append-only inventory
evidence that must be read *at a cut-off*, or a replayed run reads different numbers than the run it
replays. The only cut-off read that exists is per-package; calling it once per package over a
ten-thousand-package inventory is N+1.

**Approach:** One selection function that returns every package needing identity review, ordered by
the breadth its latest snapshot at the cut-off recorded, with the mapping outcomes it already has
attached. No queue table, no workflow state, no view — the surface that works this queue is
`CPM-APP-S05`'s, and `identity` sits below `workflow` in the layer order.

## Boundaries & Constraints

**Always:**

- The **cut-off is an argument**, never derived inside the function and never read from a clock.
  `CPM-AD-25` says a policy reads the latest snapshot at or before **its run's** cut-off;
  `core/policy_run.py` derives one per run and hands it down, and this function is handed one the
  same way. A naive datetime is refused, as `snapshot_as_of` refuses one.
- The unresolved set is derived from `IdentityConfidence` rather than written as literals — the
  shape `core/confidence.py` uses for `_KNOWN_CONFIDENCES`. A fourth confidence added later must
  not be silently included or excluded.
- **Every package in the set is returned**, including those with no snapshot at all, those whose
  latest snapshot is `not_found`, and those whose latest is `error`. AC 1 says "every one of them";
  a package with no breadth is ranked last, not filtered away. `CPM-IDENTITY-S05`'s override path
  can create a package that ingestion never saw, so this is reachable rather than theoretical.
- **NULL ordering is decided in Python, never left to the backend.** SQLite sorts NULLs first
  ascending and PostgreSQL sorts them last; the breadth columns are nullable by construction, so the
  order would differ between the local suite and the gate. This is the single biggest parity trap in
  the story.
- **No backend-specific ORM feature.** No `distinct(*fields)`, no `Window`, no `FILTER`, no
  `NULLS FIRST/LAST`. `collectors/tasks.py` already folds "latest per package" in Python for exactly
  this reason and says so; follow that precedent rather than inventing a first `Subquery` in this
  repository.
- The ordering is **total and deterministic**, ending in a tiebreak on the surrogate key.
  `snapshot_as_of`'s own docstring argues that an unordered tie makes a replay stop being a replay,
  and a ranked queue that reshuffles between two identical calls is the same defect one layer up.
- Reads only. No `update`, no `delete`, no `bulk_update`, no `raw`
  (`tests/unit/django_apps/test_mutation_path_audit.py`).
- `pixi` is the only runner, and `git add -A` before `pixi run ci`.

**Block If:**

- Satisfying AC 1's ranking appears to require a weighted score combining the two counts.
  `CPM-FR-20`'s score function is PRD Open Question 8 and is explicitly undecided; inventing one
  here would put an organizational risk posture into an identity story.
- The selection cannot be written without `identity` importing `collectors`.

**Never:**

- Do **not** create a queue table, a workflow model, or any row recording that a human looked. AC 3
  says so, and `CPM-AD-22` puts all three queues in the `workflow` app.
- Do **not** invent a *candidate mapping* representation. Nothing in the tree models a proposed
  mapping — `PackageMapping` records what a resolution **concluded** — and inventing one would
  collide with `CPM-AD-1` and with AC 3's spirit. Expose what exists; see Design Notes.
- Do **not** add a view, serializer, endpoint or task. `CPM-EP-APP` owns the surface, and
  `identity`'s module list is pinned against exactly these names.
- Do **not** rank by confidence. `IdentityConfidence`'s member order is presentation order and its
  own docstring says nothing reads it as a ranking.
- Do **not** put a module in `identity/` — see Design Notes for where this goes and why.
- Do **not** derive a cut-off, read a clock, or default one. `CPM-AD-26` and the clock audit.
- Do **not** add a dependency, a `pragma`, a coverage omit, a `pytest.skip`, or `databases=`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| The unresolved set | packages at `unmapped`, `inventory-derived` and `verified` | only the first two are returned | No error expected |
| A package reaching `verified` | a selected package is resolved to `verified`, selection runs again | it no longer appears | No error expected |
| Ranked by breadth | three packages whose latest snapshots record different counts | returned highest breadth first | No error expected |
| The cut-off is honoured | a package whose breadth rose after the cut-off | the breadth at the cut-off orders it, not the later one | No error expected |
| Replay is stable | the same cut-off, called twice | the same packages in the same order, by primary key not by chance | No error expected |
| No snapshot at all | a package created outside ingestion | returned, ranked last | No error expected |
| Latest is an absence | a package whose latest snapshot at the cut-off is `not_found` | returned, ranked last — its counts are NULL by constraint | No error expected |
| Latest is an error | a package whose latest snapshot at the cut-off is `error` | returned, ranked last | No error expected |
| Ties break on the key | two packages with identical breadth | ordered by surrogate key, and the same way on both backends | No error expected |
| A snapshot after the cut-off only | every snapshot for a package is later than the cut-off | returned as though it had none | No error expected |
| Mapping outcomes travel | a selected package with `PackageMapping` rows | its outcomes are available without a second query per package | No error expected |
| A package with no mappings | a shell nothing has resolved | returned, with an empty mapping set rather than an absent one | No error expected |
| A naive cut-off | a cut-off with no timezone | refused | an `InventoryReadError`-shaped refusal |
| Nothing to review | every package is `verified` | an empty result, which is not an error | No error expected |

</intent-contract>

## Code Map

- `collectors/models.py:299` `snapshot_as_of(*, package_id, cutoff)` — the per-package cut-off read,
  and the rule this story extends: the module docstring at `:53-59` says it is "the only supported
  way" and bans `.latest()`/`.first()` reaching for a current value. `:337-349` is the whole body —
  `filter(observed_at__lte=cutoff).order_by("-observed_at", "-pk").first()`, including the `-pk`
  tiebreak that makes it deterministic. **A set-based read is new surface and must be argued as an
  extension of that rule, not a bypass of it.**
- `collectors/models.py:166-225` — `InventorySnapshot`'s fields. All six signal columns are
  `PositiveIntegerField(null=True, blank=True, default=None)`; the requiredness lives in the
  `inventory_counts_present_exactly_when_observed` check constraint at `:227-280`, which makes the
  counts present **exactly when** `state == ok`. That is why an absence row has NULL breadth.
  `:227` also declares `inv_snapshot_pkg_observed` on `(package, -observed_at)` — the index this
  story's read wants.
- `collectors/tasks.py:937-949` — **the precedent to follow.** The absence derivation folds "latest
  state per package" in Python over an ascending `values_list`, with a comment saying
  `distinct(*fields)` would do it in the database but is PostgreSQL-only while the suite runs on
  SQLite. This story's read is the same fold plus an `observed_at__lte` filter.
- `identity/models.py:153` `IdentityConfidence` — three values; its docstring says the member order
  is presentation order and is not a ranking. `:398` `Package.confidence`. `:575` `PackageMapping`
  with `related_name="mappings"` and one row per `(package, kind)`.
- `core/rollup.py:145` `packages_for_rollup()` — the only other set-based query over `Package`
  (`list(Package.objects.order_by("pk"))`), and the precedent that an unbounded return is in-house
  practice at ten-thousand-package sizing.
- `core/policy_run.py:229-246` — where a cut-off legitimately comes from: the newest `finished_at`
  no in-flight run can write behind, raised rather than defaulted. **Read-only; this story does not
  derive one.**
- `core/confidence.py:84` `_KNOWN_CONFIDENCES` — the shape for deriving a confidence set from the
  enum rather than writing literals.
- `tests/unit/django_apps/test_identity_app.py:77` `EXPECTED_MODULES` and `:83` `ABSENT_SURFACES` —
  `identity/`'s module list is pinned to exactly four files, and `:278` pins its only subpackage to
  `migrations`. **`collectors/` and `core/` have no equivalent pin.**
- `tests/unit/django_apps/test_single_ordering_audit.py` — bans a module-level collection holding
  two or more `OutcomeState` members. A breadth ordering over integers is fine; an ordering over
  *states* is `core`'s alone.

## Tasks & Acceptance

**Execution:**

- `collectors/selection.py` — new. `unresolved_packages(*, cutoff)`: the confidence filter derived
  from `IdentityConfidence`, one set-based read of snapshots at or before the cut-off folded to
  latest-per-package in Python, the breadth ordering with its NULL and tiebreak rules, and the
  mapping outcomes attached without a per-package query. Refuses a naive cut-off.
- `tests/unit/django_apps/test_selection.py` — new; the ordering rules and the refusal, no database.
- `tests/integration/django_apps/test_selection.py` — new; every matrix row that needs a table,
  including the two-call replay stability case and the three no-breadth states.

**Acceptance Criteria:**

1. Given packages at every confidence, when the selection runs at a cut-off, then exactly those at
   `unmapped` and `inventory-derived` are returned, and the filter is derived from
   `IdentityConfidence` rather than from three literals.
2. Given packages whose latest snapshots at the cut-off record different breadth, when the selection
   runs, then they are returned in descending breadth order, with ties broken on the surrogate key
   so two calls at one cut-off return the same sequence.
3. Given a package whose breadth changed after the cut-off, when the selection runs at that cut-off,
   then the breadth as of the cut-off determines its position — a replayed run reads what the run it
   replays read.
4. Given packages with no snapshot, with a `not_found` latest, and with an `error` latest, when the
   selection runs, then all three are returned and ordered after every package with breadth, in an
   order that is the same on SQLite and on PostgreSQL.
5. Given a selected package's mapping outcomes, when the result is read, then they are available
   without a query per package — asserted by counting queries, not by inspection.
6. Given `identity/`, when its module list is read, then it is unchanged by this story.

## Spec Change Log

### 2026-09-06 — The Constrained note was stale

The story carried "internal usage breadth is read from inventory evidence at a cut-off
(`CPM-AD-25`); its field set and source are PRD Open Question 3 and are not chosen here." The
cut-off half stands. The field set half is **stale**: OQ-3 was resolved on 2026-09-04 —
`internal_component_count` and `internal_lob_count` are required on every inventory record and are
together the breadth `CPM-FR-4` ranks by, with `apps`, `platforms`, `downloads` and `versions`
nullable score inputs for `CPM-FR-20`. Left as written, it would have told the implementer that a
settled question was open and invited a second answer. What remains genuinely open is how the two
counts *combine*, which is `CPM-FR-20`'s score function and PRD Open Question 8 — recorded in the
Design Notes and in `deferred`, not resolved here.

### 2026-09-06 — AC 1's "candidate mappings" clause was reinterpreted, and that is recorded here

**What changed.** The epic's AC 1 reads "candidate mappings and the evidence for each are available
where any exist." This story's acceptance criteria replace it with AC 5, which requires each selected
package's *concluded* mapping outcomes to travel with it without a query per package.

**Why.** No producer of candidate mappings exists. `PackageMapping` records what a resolution
concluded, one row per kind; nothing anywhere proposes alternatives, scores them, or cites evidence
per alternative. The clause's own "where any exist" is what makes it satisfiable in that state.

**The known-bad state this avoids.** Standing up a `MappingCandidate` table to satisfy the clause
literally would create queue-adjacent state that this story's third criterion forbids and
`CPM-AD-22` places in the `workflow` app, and would model a concept with no producer to fill it.

**What the first reading of the record got wrong.** The Design Notes originally argued that the
concept was undefined. It is not: PRD `CPM-FR-4` states it, and the approved UX design specifies it
in detail — a "Candidate mappings the resolver found" panel, ranked by associator score, with a
per-row Evidence column citing source tables and instants. The engineering conclusion stands, but the
justification was wrong about the state of the record, and the obligation is now filed in `deferred`
with the note that **no downstream story currently claims it** — neither `CPM-APP-S05` nor
`CPM-APP-S03` mentions candidates in its acceptance criteria.

## Review Triage Log

### 2026-09-06 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 22: (high 6, medium 9, low 7)
- defer: 4: (high 0, medium 1, low 3)
- reject: 5: (high 0, medium 1, low 4)
- addressed_findings:
  - `[high]` `[patch]` **The tiebreak this whole story turns on was untested, and adding the test was
    not enough.** The fold argues that when two snapshots share an `observed_at` — the *normal* case,
    since one sweep stamps every row with the run's single instant (`CPM-AD-7`) — the highest primary
    key wins. Nothing tested it. Worse, on investigation, dropping `"pk"` from the `order_by` left
    the suite green even *with* the new case, because SQLite returns tied rows in rowid order and
    "last row of an ordered stream wins" reaches the right answer whether or not it asked for one.
    So the fold now compares `(observed_at, pk)` explicitly in Python, spelled as "take it when
    strictly newer" — which makes a narrowed stamp resolve ties to the *wrong* row on every backend
    and therefore fail loudly. Mutation-verified after the change.
  - `[high]` `[patch]` The claim that the fold returns the same row `snapshot_as_of` returns is the
    module's central correctness argument and had no test. A differential case now builds six
    arrangements in one table — a same-instant tie, one straddling the cut-off, a departure, an
    error, an only-later, and a never-observed — and compares both reads at two cut-offs.
  - `[high]` `[patch]` The confidence complement was computed in Python and applied as a *positive*
    filter, so the module's own fail-safe promise held only for values the enum declares: a value
    stored by a data migration, or one later removed from the enum while rows still carry it, left
    the review queue silently. Now `exclude(confidence__in=RESOLVED_CONFIDENCES)` in SQL, with a case
    for an undeclared confidence and mutation verification that the positive filter fails it.
  - `[high]` `[patch]` The two reads were not in one transaction — the defect `core/rollup.py` names
    in its own docstring. Membership is now decided once by the package read and handed to the
    snapshot read, with `transaction.atomic()` around both. The docstring is explicit that atomicity
    alone would not have fixed this under PostgreSQL's default `READ COMMITTED`; single-sourcing the
    membership is what does.
  - `[high]` `[patch]` The parity claim was provable only from the side a developer does not run: if
    the ordering were delegated to the database, SQLite sorts NULLs last under `DESC` — exactly what
    the integration cases assert — so the local gate and both compatibility jobs would stay green and
    only the postgres gate could fail. A unit case now pins where a missing count sorts without
    touching a database.
  - `[high]` `[patch]` The prefetch's ordering guarantee was asserted only where the database's
    natural order already agreed, so a deleted `order_by("pk")` was invisible. **The premise I sent
    turned out to be wrong** — the UPDATE-relocates-the-heap-row effect did not materialise on the
    postgres gate, because the prefetch reads through the foreign key's index — so the case now
    asserts the emitted SQL for `package_mappings` carries an `ORDER BY`, and the module comment is
    corrected to say what was measured rather than what was assumed.
  - `[medium]` `[patch]` `_breadth_at` materialised every snapshot at or before the cut-off, so its
    cost grew with retained *history* rather than with the inventory, while the docstring's "three
    queries regardless of how many packages" let a query-count claim stand in for a cost claim. Now
    `.iterator(chunk_size=...)`, with the growth stated plainly and the incorrect
    "cardinality does not grow with the inventory" comment gone along with the join it justified.
  - `[medium]` `[patch]` The query-count test ran at one cardinality and asserted a hard-coded 3,
    though its own constant's comment said AC 5 is about independence from the package count. Now
    measured at 1, 3 and 9 and asserted *equal*, with no hard-coded number.
  - `[medium]` `[patch]` Four untested arrangements added: mappings not leaking across packages (every
    case had used one package, so a mis-scoped `Prefetch` passed everything); a package healthy before
    the cut-off and departed after it, which must keep its breadth; and the `unknown` and
    `not_applicable` states, two of `OutcomeState`'s five.
  - `[medium]` `[patch]` A `None` or a `date` cut-off raised `AttributeError` rather than the
    documented `InventoryReadError`; the non-`datetime` check now precedes the naive check, since a
    `datetime` is itself a `date`.
  - `[medium]` `[patch]` Two test constants carried comments contradicting their code — one describing
    the opposite instant, one claiming a derivation performed elsewhere — and nothing asserted the
    instants were in the order their names imply. Both corrected, with a guard.
  - `[medium]` `[patch]` "AC 3" meant two different things in one test file, the pre-rewrite meaning
    and the current one. Renumbered.
  - `[low]` `[patch]` Seven smaller ones: the frozen-ness claim described as one field deep and
    asserted; `breadth_ordering_key` made private, since publishing it invited the re-sorting the
    frozen-ness argument forbids; a dead `.order_by("pk")` removed, which had implied the database
    ordering was load-bearing; `django_assert_num_queries` replaced by `CaptureQueriesContext`,
    mooting an `Any` annotation under strict mypy; enum spelling normalised; a structlog event
    binding the cut-off and the queue's size, since a read that runs once per policy run left an
    operator nothing to look at (`CPM-AD-15`); and the module docstring halved, with the placement
    and no-breadth arguments left to this story rather than restated in five places.

## Design Notes

**Where this lives, and why not in `identity`.** The selection needs `Package.confidence` from
`identity` and `InventorySnapshot`'s counts from `collectors`. The architecture spine draws exactly
one arrow between them — `identity → collectors` — and `collectors` already imports `identity` in
two modules, while `identity` has never imported `collectors`. Putting the function in `identity`
would invert the one arrow the spine draws and be the first import of its kind; putting it in
`collectors` adds no arrow at all. `identity/`'s module list is also pinned to exactly four files
with its subpackages pinned to `migrations`, so a new module there is a test edit arguing for a
layering change, which is not what this story is for. It goes in `collectors/selection.py`, beside
the cut-off read it extends.

**Ranking is an ordering, not a score.** `CPM-FR-4` says "ranked by internal usage breadth" and PRD
OQ-3b says the two counts "together **are** the internal usage breadth" — but neither the PRD nor
the spine says how to combine them, and `CPM-FR-20`'s score function is explicitly Open Question 8.
So this story orders by the pair rather than reducing it to a number: component count first, then
LOB count, then the surrogate key. That is defensible, total, deterministic, and — the point — it
commits to nothing about weighting that OQ-8 will have to decide. A weighted score invented here
would be an organizational risk posture smuggled into an identity story, and it would be the wrong
place to argue about it.

**Three ways to have no breadth, and they are not the same as zero.** A package may have no snapshot
at all (reachable: `CPM-IDENTITY-S05`'s override path creates packages ingestion never saw), or its
latest snapshot at the cut-off may be `not_found` or `error` — both of which carry NULL counts by
the check constraint, because an absence observes no counts. `CPM-FR-42` and PRD Appendix A.1 are
explicit that blank means missing and is never conflated with zero. So all three sort after every
package that has breadth, and a package recording a genuine `0` outranks all of them. AC 1 says
"every one of them", so none is filtered away.

**NULL ordering is the parity trap.** SQLite sorts NULLs first on an ascending order and PostgreSQL
sorts them last; `NULLS LAST` is not portable. The breadth columns are nullable by construction, so
leaving the order to the database means the local suite and `gate-postgres` disagree about the
queue's shape — the kind of divergence that passes both gates while being wrong in one of them. The
fold is in Python for the same reason `collectors/tasks.py` already folds latest-per-package there.

**"Candidate mappings" has no referent yet, and that is what "where any exist" is for.** Nothing in
the domain layer models a *proposed* mapping — `PackageMapping` records what a resolution
**concluded**, one row per kind, and there is no proposal, no score, and no alternative-with-evidence
row anywhere. AC 1's clause is hedged "where any exist", which is satisfiable today by exposing what
does exist: each selected package's mapping outcomes and their instants. Inventing a
`MappingCandidate` table to satisfy the clause literally would create the queue-adjacent state AC 3
forbids and would model a concept no story has defined. The module says so plainly rather than
leaving the next reader to wonder whether it was overlooked.

**Attaching the outcomes without N+1.** Returning packages and then reading `package.mappings` per
row is the same N+1 the per-package cut-off read would have been. `prefetch_related` is ordinary
Django and needs no backend-specific feature, and AC 5 asserts the query count rather than trusting
it — a count assertion is the only thing that fails when someone later adds an innocent-looking
attribute read inside a loop.

## Verification

**Commands:**

- `pixi run test` -- expected: exits 0.
- `pixi run test-integration` -- expected: exits 0, no new skips.
- `pixi run ci` -- expected: exits 0, coverage at or above 90%. Run **after** `git add -A`.
- `pixi run gate-postgres` -- expected: exits 0 with nothing newly skipped. **This is the run that
  matters most for this story**: the NULL-ordering and tiebreak cases are exactly where SQLite and
  PostgreSQL diverge, so a green local suite proves half of what is needed.

## Auto Run Result

Status: done

**What was implemented.** One read: `unresolved_packages(*, cutoff)` returns every package needing
identity review — those at any confidence but `verified` — ranked by the internal usage breadth its
latest snapshot at the cut-off recorded, with its concluded mapping outcomes attached. No queue
table, no workflow state, no view, no model, no migration.

**Files changed.**

- `collectors/selection.py` — new. The confidence complement taken in SQL, one bounded read of
  snapshots at or before the cut-off folded to latest-per-package in Python, the breadth ordering
  with its NULL and tiebreak rules, the mapping prefetch, and a structlog event binding the cut-off
  and the queue's size.
- `tests/unit/django_apps/test_selection.py`, `tests/integration/django_apps/test_selection.py` —
  new. The ordering rules, the refusals, the differential against `snapshot_as_of`, and every matrix
  row needing a table.

**Review findings:** 22 patched (6 high, 9 medium, 7 low), 4 deferred, 5 rejected. Four review layers
ran in parallel over the full 1,481-line diff.

**Follow-up review recommended:** true. Six high-severity patches.

**The story's own load-bearing claims were argued in prose and asserted by nothing, and the tiebreak
was the worst of them.** The fold reasons at length that when two snapshots share an `observed_at` —
the normal case, since one sweep stamps every row with the run's single instant — the highest primary
key wins. Nothing tested it. Adding the test was not enough either: dropping `"pk"` from the
`order_by` *still* passed on SQLite, because SQLite returns tied rows in rowid order and "last row of
an ordered stream wins" reaches the right answer whether or not it asked for one. The fold now
compares `(observed_at, pk)` explicitly in Python, spelled so that a narrowed stamp lands on the
wrong row on every backend and fails loudly rather than passing by luck.

**The parity claim — the reason this story exists — was provable only from the side nobody runs
locally.** If the ordering were delegated to the database, SQLite sorts NULLs last under `DESC`,
which is exactly what the integration cases assert, so the local gate and both compatibility jobs
would stay green and only the postgres gate could fail. A unit assertion now pins where a missing
count sorts without touching a database.

**One finding I sent was wrong, and the implementer said so rather than implementing it.** I argued
the mapping prefetch needed an ordering test because a PostgreSQL `UPDATE` relocates the row in the
heap. It does not here — the prefetch reads through the foreign key's index, and the mutation stayed
green on the gate. The case instead asserts the emitted SQL carries an `ORDER BY`, and the module
comment now records what was measured rather than what was assumed.

**Verification.** `pixi run ci` exits 0 — 4324 passed, 2 pre-existing skips, coverage 98.39%, with
`collectors/selection.py` at 100%. `pixi run gate-postgres` exits 0 with identical counts and no new
skips. All fourteen I/O matrix rows have a covering test that ran and passed. Note for whoever runs
these next: two `pytest --cov` runs in one worktree corrupt coverage's parallel fragments and fail
with `no such table: context` while every test passes — run the gates serially.

**Residual risks.** Four `deferred` entries. The one that matters: the queue exposes each package's
*concluded* mappings, not the **candidate** mappings with per-candidate evidence that `CPM-FR-4` and
the approved UX design describe — a ranked panel of alternatives, each citing the evidence behind it.
Nothing in the tree produces such a proposal, so the clause's own "where any exist" is unsatisfied
today and inventing a table for it would have created the queue-adjacent state this story forbids.
What is owed is a producer, a carrier for per-candidate evidence, and the associator score the UX
ranks by — and **no downstream story currently claims any of it**, which is why it is filed rather
than assumed.
