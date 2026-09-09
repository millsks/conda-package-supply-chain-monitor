---
title: 'CPM-PRIORITY-S01: An explainable priority bucket and score'
type: 'feature'
created: '2026-09-09'
status: 'done'
review_loop_iteration: 0
baseline_revision: 'dc4a37c791be1e50827d3b2ee70a72faa31ebcc0'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s05-licence-policy.md
  - _bmad-output/implementation-artifacts/stories/cpm-py314-s03-readiness-states-own-evidence-type.md
deferred:
  - summary: >-
      Rank is derived rather than stored, so no column carries an ordinal. Storing one
      needs a post-loop hook `core/policy.py` does not have, which is a change this
      story was not asked to make.
    evidence: |-
      `CPM-PRIORITY-S01`'s AC 1 asks that rank be "derived from bucket and score and
      stable for a given policy run", and `CPM-AD-1` lists `rank` among the export fields
      *projected* from the rollup rather than stored on it. What ships is
      `policies/priority.py`'s `ranking_order()` -- one ordering, total by construction
      (bucket, then score descending, then the package key), which every read surface
      calls rather than writing its own `ORDER BY`.
      **Why not a stored integer.** A pass sees one package at a time: `core/policy_run.py`
      puts the package in the outer loop, so an ordinal over the whole run could only be
      computed after the loop, and `core/policy.py` offers `prepare` (before) and
      `evaluate` (per package) and nothing after. Adding a `finalize` hook is a change to
      the pass contract every other pass implements, made by a story whose Never list
      forbids changing an earlier pass -- and a stored ordinal is a third copy that can
      disagree with the two columns it was derived from the moment either is corrected.
      **What is delivered instead.** The ordering is one function, its totality is
      asserted in both tiers, and `docs/deployment.md` tells a read surface to call it.
      **What closing it needs.** A `finalize` hook on `PolicyPass`, which belongs with a
      story that owns the pass contract -- `CPM-PRIORITY-S03` is the epic's remaining
      story and owns replay, so it is the natural place if review wants an ordinal.
    location: >-
      src/django_apps/conda_sentinel/policies/priority.py -- ranking_order
    severity: low
  - summary: >-
      The score's normalisation ceiling is a constant in code rather than versioned data,
      so a reviewer can choose the weights but not the curve.
    evidence: |-
      `usage_score` maps weighted counts onto `CPM-FR-20`'s 1-100 range against
      `_SIGNAL_CEILING`, a hundred, which stands for "as used as it gets". The weights are
      versioned data and a reviewer chooses them; the ceiling is not.
      **Why it is not in the file.** PRD Open Question 8 leaves the score *function* open,
      and a reviewer answering it is choosing what the signals are worth relative to each
      other -- which the weights express. The ceiling is the arithmetic that turns those
      weights into the stated range, and a reviewer who wants a different curve is
      replacing the function rather than tuning a number. Putting it in the file would
      offer a knob whose effect is only visible at the extremes.
      **What it costs.** An organisation whose largest package is used by ten components
      sees every package score near the bottom of the range, and one whose packages are
      used by thousands sees everything at 100. Neither is wrong -- the score ranks
      *within* a bucket and a monotonic squash preserves the order -- but the numbers read
      oddly, and an operator would reasonably expect to change them.
      **What closing it needs.** A decision about what the score function *is*, which is
      Open Question 8 itself.
    location: >-
      src/django_apps/conda_sentinel/policies/priority.py -- _SIGNAL_CEILING
    severity: low
---

# CPM-PRIORITY-S01: An explainable priority bucket and score

Epic: `CPM-EP-PRIORITY` — A ranked, explainable queue of work

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Story

As a platform lead,
I want every priority assignment to explain itself,
so that nobody has to read the rule set to understand why a package is P1.

## Acceptance Criteria

1. **Given** a package with derived statuses
   **When** the priority policy runs
   **Then** it assigns `P1`–`P10` by top-down first-match rules and computes a 1–100 score
   from internal usage signals
   **And** rank is derived from bucket and score and is stable for a given policy run

2. **Given** any assignment
   **When** it is stored
   **Then** it records the bucket description, the rule that matched, and the reason

3. **Given** the rule set and the score function
   **When** they are loaded
   **Then** they are versioned data, changeable without a deployment, and every result
   records the version that produced it

## Intent

**Problem:** Six policy passes each answer one question about a package, and nothing
turns those answers into an ordered queue of work. `CPM-FR-20` asks for one — and asks
that every assignment explain itself, so nobody has to read the rule set to know why a
package is `P1`.

**Approach:** A seventh policy pass, registered **last**, reading the six earlier
passes' derived rows for the same run plus the inventory's usage signals at the
run's cut-off. It applies a top-down first-match rule set and a score function that
are **versioned data**, and writes a derived row carrying the bucket, the score, and
the three explainability fields. The rule set and the score function ship
**unseeded** — PRD Open Question 8 names them as encoding a risk posture that does
not exist yet, and this story's own epic entry constrains it to the engine, the
schema and the explainability fields.

## Boundaries & Constraints

**Always:**
- A **pass** (`CPM-AD-8`), registered last: it reads evidence and earlier passes'
  rows at the run's cut-off, writes only its own derived table keyed
  `(package, policy_run)`, and never writes the rollup (`CPM-AD-21`).
- **Reading an earlier pass's derived rows is safe only inside one run, and only
  because the orchestration guarantees it.** `core/policy_run.py` puts the package
  in the outer loop and runs the passes in declared order inside one
  `transaction.atomic()` per package, so the six rows exist and are visible. Every
  read filters on **both** `package` and `policy_run`, so one run's verdict can
  never be derived from another run's rows — which is what keeps `CPM-FR-22`'s
  replay stateable.
- **The rule set and the score function are versioned data** (`CPM-AD-8`,
  AC 3): `policies/parameters.py` keys them by policy version, they change without
  a deployment, and every row records the version that produced it.
- **The engine ships and the content does not.** An empty rule set is the shipped
  answer, on exactly the terms `license_rules` ships empty: PRD Open Question 8
  names the *decision* as open, so a "sensible default" bucketing would be this
  component deciding a risk posture it was told not to decide.
- **No bucket is assigned by default.** A version recording no rules, and a package
  no rule matches, both reach `unknown` — never `P10`, never "lowest". A default
  bucket is a claim about a package's importance that nobody made.
- **A score is never invented from a missing signal.** PRD Open Question 3b makes
  `apps`, `platforms`, `downloads` and `versions` nullable and says blank means
  missing and is never invented, so a package missing a weighted signal gets **no**
  score and the row says so. Zero is a count; `NULL` is an absence.
- Every assignment records the bucket description, the rule that matched and the
  reason (AC 2), and a row that names a bucket must carry all three.
- A version predating these parameters is a **historical fact, not a
  misconfiguration** (`policies/vulnerability.py`'s recorded defect): such a run
  writes rows carrying no bucket and saying so, and does not fail.
- Time comes from the run's cut-off; no `timezone.now()`.
- `pixi` is the only runner; `pixi run ci` exits 0.

**Ask First:**
- **If review finds `rank` must be a stored integer column.** This story derives it:
  rank is a deterministic total order over `(bucket, score, package)` within a run,
  shipped as one documented ordering the read surfaces call. Storing an ordinal
  needs a post-loop hook in `core/policy.py` — a pass sees one package at a time —
  which this story was not asked to add. `CPM-AD-1` calls rank *projected*.
- **If review finds the rule condition language needs more than a conjunction of
  per-domain verdicts.** The schema ships matching an `AND` over the six domains'
  verdict values, which is what a first-match rule set needs and no more.

**Never:**
- **No seeded rule set and no seeded score weights.** Not one bucket, not one
  weight.
- **No work type** — that is `CPM-PRIORITY-S02` and its own closed set of eight.
- **No re-derivation of any earlier pass's verdict.** This pass reads them as given
  and computes no currency, vulnerability, licence, feedstock, remediation or
  readiness answer of its own.
- **No mutation of evidence**, no outbound call, and no change to any earlier pass.
- No priority claim about a package whose identity was never established — the
  rollup's gate (`CPM-AD-4`) already writes `unknown` there and this pass does not
  second-guess it.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| The shipped state (AC 3) | a version recording an empty rule set | every package `unknown`, the row saying no rule set was recorded | Never a default bucket |
| A version predating the parameter | a run at an older recorded version | the same `unknown` row, saying the version records no rule set | The run does **not** fail |
| First match wins (AC 1) | two rules both matching | the **earlier** rule decides, and the row names it | Order is the file's |
| An assignment explains itself (AC 2) | any rule matched | the row carries the bucket, its description, the rule that matched and the reason | A bucket with no explanation is refused by the database |
| No rule matches | a rule set that matches nothing for this package | `unknown`, the row saying no rule matched | Distinct from "no rule set" in `detail` |
| A score is computed (AC 1) | weights recorded and every weighted signal present | a score in 1–100 | Bounded at both ends |
| A weighted signal is missing | `apps` is `NULL` and weighted | **no** score, the row naming the missing signal | Never treated as zero |
| No weights recorded | a version recording no score function | no score, and a bucket may still be assigned | The two are independent |
| Rank (AC 1) | two packages, one run | a total, stable order over `(bucket, score, package)` | Ties broken by package, so the order is total |
| No inventory observation | no snapshot at the cut-off | no score; a bucket may still be assigned from the derived statuses | An absence, not a zero |
| An earlier pass wrote no row | a package skipped by an earlier pass | that domain reads as absent and matches no rule requiring it | Never a guessed verdict |
| Evidence after the cut-off | a snapshot written later | not read | `CPM-AD-21` |
| A replay of one version at one cut-off | the run repeated | byte-identical rows | `CPM-FR-22` |
| An unmapped package | identity never established | the rollup column is gated to `unknown` by the writer | The pass does not gate |

</frozen-after-approval>

## Code Map

- `policies/licence.py` — the closest precedent for a **version-parameterised pass
  whose content ships empty**: `prepare()` is one line, and the "no rule set
  recorded" answer is a real verdict rather than a failure.
- `policies/vulnerability.py` `_risk_order` (~`:1092`) — the recorded defect this
  story must not repeat: a version predating a parameter is a historical fact, and
  raising for one failed every package and finalized the run `failed`.
- `policies/parameters.py` — `PARAMETER_KEYS` (~`:308`) is the allow-list a new key
  **must** be added to or the shipped file is refused; `PolicyParameters` (~`:381`)
  gains defaulted fields; `_parameters` (~`:653`) refuses an undefined key;
  `parameters_for(version)` is the one entry point a pass calls. `license_rules`
  (~`:671`) is the end-to-end template, including that absent and `[]` are one
  state.
- `policies/data/policy-parameters.toml` — add a **new** `[versions."..."]` entry;
  never edit an existing one. The `license_rules` block is the comment template for
  "empty on purpose, and not provisional".
- `core/policy_run.py` `_execute_passes` (~`:361`) — package in the outer loop,
  passes in declared order, one `transaction.atomic()` per package. This is what
  makes reading the six earlier rows safe.
- `core/policy.py` `register_pass` (~`:255`) — with a non-empty `contributes`: no
  repeated column, every column in `contributable_columns()`, no column another
  pass owns.
- `core/rollup.py` — `contributable_columns()` (~`:129`) is `PackageHealth`'s
  concrete fields minus `STAMP_COLUMNS`; `permitted_values(column)` (~`:169`) reads
  the column's own `choices`; `compose_rollup` (~`:211`) applies `gated_status`.
- `core/confidence.py` `GATED_VALUE` — **`OutcomeState.UNKNOWN.value`.** The gate
  writes it into any contributed column, so the bucket vocabulary must contain
  `unknown`: it is composed with `outcome_type`, not a bare `TextChoices`.
- `core/models.py` `PackageHealth` (~`:916`) — two domain columns today; this story
  adds the third, with a `core` migration, exactly as `CPM-CURRENCY-S07` added
  `feedstock_presence_status`.
- `collectors/models.py` `InventorySnapshot` (~`:708`) and `snapshot_as_of`
  (~`:863`) — the usage signals and the only cut-off-bound read of them
  (`CPM-AD-25`). `internal_component_count` and `internal_lob_count` are required
  on an `ok` row; `apps`, `platforms`, `downloads`, `versions` are nullable.
- `policies/models.py` — the six derived tables this pass reads, and the field and
  constraint conventions the seventh follows.
- `tests/passes.py` (`ADOPTED_PASS_NAMES`, `ADOPTED_PASSES`),
  `tests/unit/django_apps/test_policies_app.py` (`EXPECTED_MODULES`,
  `EXPECTED_MIGRATIONS`, the roster and order assertions),
  `tests/integration/django_apps/test_rollup.py` (the per-domain version map),
  `tests/unit/django_apps/test_derived_status_writability_audit.py`
  (`RECORDED_EXEMPTIONS`, if the pass writes a `*_status` keyword).

## Tasks & Acceptance

**Execution:**
- [ ] `policies/outcomes.py` — `PriorityBucket` composed by `outcome_type` over
      `P1`–`P10`, plus the flat constants and the domain-prefixed sentinels.
- [ ] `policies/parameters.py` — two keys, two `PolicyParameters` fields, two
      parsers, and both added to `PARAMETER_KEYS`.
- [ ] `policies/data/policy-parameters.toml` + `README.md` — a new version entry
      carrying both, empty, with the "empty on purpose" argument.
- [ ] `core/models.py` + a `core` migration — `priority_status` on `PackageHealth`.
- [ ] `policies/models.py` + a `policies` migration — `PackagePriority`.
- [ ] `policies/priority.py` — the pass: the six reads, the signal read, the
      first-match engine, the score, the ordering.
- [ ] `policies/apps.py` — import, roster entry **last**, ordering narrative.
- [ ] The roster and audit tests listed in the Code Map.
- [ ] `tests/unit/django_apps/test_priority_policy.py` and
      `tests/integration/django_apps/test_priority_policy.py` — every matrix row.
- [ ] `docs/deployment.md` — the operator section, and what filling the rule set in
      commits them to.

**Acceptance Criteria:**
- Given an empty rule set, when the policy runs, then every package is `unknown` and
  no package carries a bucket.
- Given two matching rules, then the earlier one decides and the row names it.
- Given a matched rule, then the row carries the description, the rule and the
  reason — and the database refuses a bucket without them.
- Given a weighted signal that is `NULL`, then no score is computed and the row names
  the signal.
- Given two packages in one run, then the derived order is total and stable.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above
  the floor.

## Design Notes

**Why the bucket vocabulary is composed rather than a bare `TextChoices`.**
`core/confidence.py`'s gate writes `OutcomeState.UNKNOWN.value` into every
contributed rollup column for a package whose identity was never established, and
`core/policy_run.py` refuses a contributed value outside the column's own choices.
A ten-value bucket vocabulary would have made the gate write a value its own column
does not offer -- so the four sentinels are what let the column be gated at all,
not decoration. A unit case asserts exactly that, against `GATED_VALUE` itself.

**Why the bucket is on the rollup and the score is not.** A contribution is a
`Mapping[str, str]` of status values, checked against the column's choices, so a
numeric score has no way through that seam. The bucket goes to `package_health`
because that is the table a queue filters; the score, the rank and the explanation
stay on `package_priority` because that is where a reader who has already filtered
goes next.

**Why the domain names live in `parameters.py` and not in the pass.** The file's
validation must not import the pass, and a domain the file accepts but nothing
reads would match nothing for ever -- a reviewer would write the rule and watch it
never fire. So the set is declared beside the validation and the pass binds each
name to a table and column; a unit case reconciles the two in both directions,
which is the only thing that would compare them.

**Why this pass is registered last, and why that is now load-bearing.**
`policies/apps.py` has recorded its ordering since the first pass, while noting
that none read another so the order bound nothing. This is the pass that reads
them: `CPM-FR-20` assigns from the derived statuses, so it must run after all six.
The docstring is updated to say the order now matters rather than left claiming it
does not.

## Verification

- `pixi run ci` -- the gate.
- `tests/unit/django_apps/test_priority_policy.py` -- the vocabulary, the matching,
  the score, the ordering, and every way the parameter file refuses a rule.
- `tests/integration/django_apps/test_priority_policy.py` -- the shipped empty
  state, a recorded rule set end to end, the rollup contribution, the confidence
  gate replacing a real bucket, and the four constraints.

## Dev Agent Record

### Completion Notes

**What ships.** The seventh policy pass, the first that reads another pass's rows,
and the third domain column on the rollup. The engine, the schema and the
explainability fields -- and **no** seeded rule set or score function, which is what
the epic entry constrains this story to.

**Files added:** `policies/priority.py`,
`core/migrations/0008_package_health_priority_status.py`,
`policies/migrations/0007_package_priority.py`, and both test modules.

**Files changed:** `policies/outcomes.py` (the bucket vocabulary),
`policies/parameters.py` (two keys, two parsers, `PARAMETER_KEYS`),
`policies/data/policy-parameters.toml` (a new version entry recording both, empty)
and its `README.md`, `core/models.py` (the rollup column), `policies/models.py`
(the derived table), `policies/apps.py`, `docs/deployment.md`, and six test modules
carrying a roster, a module list, a migration list, the rollup's contributable
column set or its per-domain version map.

**Each acceptance criterion:**

- **AC 1 (bucket, score, rank).** Top-down first-match over the six domains; a
  1-100 score normalized from weighted usage signals; and `ranking_order()`, total
  by construction, as the derivation of rank.
- **AC 2 (it explains itself).** The description, the matched rule and the reason
  are on every row that names a bucket -- and `A_BUCKET_EXPLAINS_ITSELF` refuses one
  that arrives without them, from both directions.
- **AC 3 (versioned data).** Both parameters are keyed by policy version, changeable
  without a deployment, and every row records the version that produced it.

**The shipped answer is that nothing is prioritised.** Every package reaches
`unknown`, nothing reaches `p10`, and the row says which absence it is. A default
bucket would have been the defect this story is most exposed to: unlike an empty
licence policy, a provisional bucketing does not read as a claim -- it reads as a
queue somebody ordered.

**Coverage:** the new pass, the new table, the extended vocabulary and the extended
parameter loader are all at 100%; the gate's floor is 90%.
