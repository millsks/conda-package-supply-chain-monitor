---
title: 'CPM-PY314-S03: Readiness that states its own evidence type'
type: 'feature'
created: '2026-09-09'
status: 'done'
review_loop_iteration: 0
baseline_revision: '4b7f974588caf0093f3aa0dfd9af1ee5bf78fa44'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-py314-s01-static-readiness-assessment.md
  - _bmad-output/implementation-artifacts/stories/cpm-py314-s02-verified-compatibility-own-queue.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s06-whether-finding-can-actually-be.md
deferred: []
---

# CPM-PY314-S03: Readiness that states its own evidence type

Epic: `CPM-EP-PY314` — Inferred and verified compatibility, kept apart

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Story

As a packaging engineer,
I want every readiness claim to say which kind of evidence produced it,
so that inference is never mistaken for proof.

## Acceptance Criteria

1. **Given** readiness evidence of either kind
   **When** the policy runs
   **Then** it derives a readiness status and states which evidence type produced it

2. **Given** both inferred and verified evidence exist for one package
   **When** the policy runs
   **Then** the distinction survives into the derived result

## Intent

**Problem:** `CPM-PY314-S01` records what a project's metadata *claims* and
`CPM-PY314-S02` records what a build *did*. Both are evidence and neither is a
verdict, so nothing in this product answers "is this package ready for Python
3.14" — and `CPM-FR-19` requires that, when something does, the answer says on
what basis. The epic has kept inference and proof apart in two tables with two
vocabularies; the risk this story exists to close is that reducing them re-merges
them at the last step, in the one column a read surface renders.

**Approach:** A sixth policy pass (`CPM-AD-8`) reading both of this epic's
evidence tables as of the run's cut-off and writing one derived row per package
per run. The readiness value **names the evidence type that produced it**, and a
separate evidence-type column carries the same fact where a query can filter on
it. Proof outranks inference; a disagreement between the two is recorded on the
row, never averaged away.

## Boundaries & Constraints

**Always:**
- A **pass**, never a collector (`CPM-AD-8`): it reads evidence as of the run's
  stated cut-off, writes only its own derived table keyed `(package, policy_run)`,
  mutates no evidence, and makes no outbound call.
- **The determinate values name the evidence type.** `CPM-AD-24` carries a value
  verbatim onto every read surface, so a bare `ready` on a queue would be exactly
  the confusion `CPM-FR-19` forbids — reached at the last step, after two stories
  spent keeping it out of the collectors. The separate evidence-type column is the
  second half of AC 1 and never a substitute for the first.
- **Verified outranks inferred, always.** A build that ran is proof; published
  metadata is a claim. When both exist the readiness comes from the verification,
  and the row still cites the assessment it also read.
- **Only rows about the same `python_series` are reduced together.** Both tables
  record the series precisely so an assessment of 3.14 and a verification of
  whatever comes next can never be read as one answer.
- **Every package gets a row**, including one with no evidence at all: `unknown`,
  evidence type `none`. An absent row must read as never-evaluated rather than as
  an answer.
- Staleness is `core/freshness.py`'s answer, consumed rather than restated, and
  **stale evidence never produces a determinate readiness** (`CPM-FR-38`: stale
  never displays as clean).
- The row **cites the evidence rows it read**, so a claim can be traced to the
  observation behind it without a second query guessing at it.
- Time comes from the run's cut-off and the injected clock; no `timezone.now()`.
- `pixi` is the only runner; `pixi run ci` exits 0.

**Ask First:**
- **If review finds this reduction should be versioned data rather than a fixed
  rule.** `CPM-AD-8` makes rule sets versioned data, and this pass ships **no
  parameter**, on `policies/remediation.py`'s precedent: "verified outranks
  inferred" is this epic's own semantics rather than an organisational risk
  posture, and the PRD seeds no readiness thresholds. If that judgement is wrong,
  the fix is a `policies/data/` parameter and a reviewer's decision, not a code
  branch invented here.
- **If review finds the derived table should carry a per-platform breakdown.** A
  verification is about one platform, and this pass reads the latest one. Naming
  every platform a package has been verified on is a different table and a
  different question from the one `CPM-FR-19` asks.

**Never:**
- **No rollup column.** `contributes` is empty. `CPM-AD-21` says no pass writes
  `package_health`, and which columns that table grows is `CPM-EP-PRIORITY`'s.
- **No reading of another *pass's* derived table.** A readiness derived from
  another pass's rows would depend on two policy versions at once, and
  `CPM-FR-22`'s replay could then be stated for neither.
- **No re-derivation of either collector's verdict**, and no change to either
  evidence table, either collector, or `core/`.
- **No priority, score, rank or work type** (`CPM-FR-20`, PRD Open Question 8).
- **Never a determinate readiness from an absence.** No evidence, unreadable
  evidence, a failed look and stale evidence are all `unknown` — never `not_ready`.
  Reading "nobody has checked" as "it does not work" is the defect class this
  epic has met in both preceding stories.
- No averaging, scoring or ranking of the two evidence kinds into one number. An
  order can be read; a number invites a mean.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Proof, and it built (AC 1) | a `verified_compatible` result, no assessment | `verified_ready`, evidence type `verified`, citing the verification row | — |
| Proof, and it did not build | a `verification_failed` result | `verified_not_ready`, evidence type `verified`, citing the row that names the platform | A failed build is a result, not an error |
| Inference only, admitting | an `inferred_compatible` assessment, no verification | `inferred_ready`, evidence type `inferred`, citing the assessment | — |
| Inference only, excluding | an `inferred_incompatible` assessment | `inferred_not_ready`, evidence type `inferred` | Never `verified_not_ready` |
| Both, agreeing (AC 2) | `inferred_compatible` **and** `verified_compatible` | `verified_ready`, evidence type `verified`, **citing both rows** | The inference is recorded, not discarded |
| Both, disagreeing (AC 2) | `inferred_compatible` **and** `verification_failed` | `verified_not_ready`, evidence type `verified`, `detail` naming the disagreement, citing both | Proof wins; the claim is preserved beside it |
| Evidence established nothing | an `unknown` assessment or result | `unknown`, evidence type `none`, `detail` saying which | Never a determinate verdict |
| Looking failed | an `error` or `not_found` row | `unknown`, evidence type `none` | Never `not_ready` |
| The question does not apply | `not_applicable` on either table | `not_applicable`, naming what identity established | The `CPM-PY314-S01` rule, inherited |
| Stale evidence | evidence older than the collector's declared target | `unknown`, `detail` saying it is stale | `CPM-FR-38`; never clean |
| Nobody has looked | no row on either table | `unknown`, evidence type `none` | Every package still gets a row |
| Two verifications, two platforms | an earlier success and a later failure | the **latest** result as of the cut-off is the reading, and the row cites it | The "latest observation" convention every pass takes |
| Evidence about another series | a row whose `python_series` is not the assessed one | not read at all | Never reduced together |
| A replay of one version at one cut-off | the same run re-executed | byte-identical rows | `CPM-AD-8`'s reproducibility |

</frozen-after-approval>

## Code Map

- `policies/licence.py` — **the closest precedent and the file to read first.** One
  evidence table, a rule, one derived row. Module layout to copy: `POLICY_NAME`,
  `READ_ORDERING = ("-observed_at", "-pk")`, a `*_VOCABULARY` frozenset built by
  comprehension (never a member literal — `test_single_ordering_audit.py` reads one
  as a precedence order), one `*_DETAIL` template per shape the columns cannot
  explain, a flat `ValueError` subclass, pure functions, then the `PolicyPass`.
- `policies/remediation.py` — the precedent for **two things this pass needs and
  licence does not**: reading more than one evidence table (a distinctly named
  reader per table), and consuming freshness. `freshness_target(evidence_model)`
  (~`:896`) walks the collector registry matching `collector.evidence_model is
  evidence_model`; `evidence_is_stale(...)` (~`:930`) wraps `freshness_of` and
  measures from the **run's cut-off, never a clock**, so a replay agrees.
  `latest_observation` is deliberately not used — it ignores the cut-off.
- `core/policy.py` — `PolicyPass`: `name`, `derived_model`, `contributes`,
  `prepare(*, policy_run, evidence_cutoff)`, `evaluate(package, *, policy_run,
  evidence_cutoff) -> Mapping[str, str]`. `register_pass` refuses ten things; the
  ones this pass must satisfy are a unique name, a `derived_model` that is not
  `PackageHealth` and not another pass's, and `contributes` entries the rollup
  really offers. `contributes = ()` passes the last three by construction.
- `core/policy_run.py` — `prepare` runs **uncaught** before the loop (a failure
  fails the run); `evaluate` runs inside one `transaction.atomic()` wrapping *all*
  passes for one package, so raising here rolls back the other five domains' rows
  for that package too. That is why so little in a pass refuses.
- `core/freshness.py` — `freshness_of(*, observed_at, target, now, status)` →
  `FreshnessReport(status, stale, observed_at)`. `is_stale` is strict: exactly at
  target is fresh.
- `collectors/models.py` — `PythonReadinessAssessment` and
  `PythonVerificationResult`, the two evidence tables read. Both carry
  `python_series`; the verification table carries `platform`, `architecture` and
  `log_reference`.
- `collectors/outcomes.py` — `INFERRED_COMPATIBLE`, `INFERRED_INCOMPATIBLE`,
  `VERIFIED_COMPATIBLE`, `VERIFICATION_FAILED` and both vocabularies' sentinels.
  A pass imports these; `CPM-AD-7` binds collectors, not passes.
- `policies/models.py` — `PackageLicense` (~`:1292`) is the field/constraint
  template: every relation `PROTECT`, every non-relational column
  `editable=False`, the state column non-null, the evidence FK nullable,
  `policy_version` + `evidence_cutoff` copied on, `detail` last, **no**
  `computed_at`, **no** `indexes`, `db_table` the architecture's name. Constraint
  names are `Final[str]` sentences above the class whose *values* are short
  domain-prefixed snake_case. `PackageRemediation` (~`:1707`) shows the
  `evidence_stale` boolean and multi-evidence FKs.
- `policies/outcomes.py` — the four-step composition: `*_MEMBER` pairs →
  `outcome_type(...)` bound once → a domain-prefixed `_*_MEMBER_VALUES`
  comprehension → flat constants, with the four sentinels re-exported under
  domain-prefixed names because the bare ones are taken. `KevMembership` /
  `FixAvailability` are the precedent for a small vocabulary with **no** sentinels,
  which is what the evidence-type column needs.
- `policies/apps.py` — the roster tuple and the ordering narrative in `ready()`.
  Declaration order is load-bearing and asserted.
- `tests/passes.py` — `ADOPTED_PASS_NAMES` and `ADOPTED_PASSES` (~`:181`).
- `tests/unit/django_apps/test_policies_app.py` — pass imports, the roster
  assertion, the **order** assertion, and `EXPECTED_MIGRATIONS`.
- **No edit to `tests/unit/test_model_registry.py`**: its rosters enumerate
  *evidence* models and the two ledgers. A derived policy table is neither.

## Tasks & Acceptance

**Execution:**
- [ ] `policies/outcomes.py` — add the readiness vocabulary (four determinate
      members naming the evidence type) and a sentinel-free `ReadinessEvidence`
      type. No precedence order: nothing reduces these rows, and an unread order
      is data the next reader mistakes for a ranking.
- [ ] `policies/models.py` — the constraint-name block and `PackagePythonReadiness`
      (`package_python_readiness`), carrying both evidence FKs, the series, the
      evidence type and `evidence_stale`.
- [ ] `policies/migrations/0006_package_python_readiness.py` — generated, then
      hand-renamed and annotated as `0004`/`0005` were.
- [ ] `policies/py314_readiness.py` — the pass: two cut-off-bound readers, the
      series filter, the staleness read, the reduction, the detail composer.
- [ ] `policies/apps.py` — import, roster entry, ordering narrative.
- [ ] `tests/passes.py`, `tests/unit/django_apps/test_policies_app.py` — the
      rosters, the order assertion and `EXPECTED_MIGRATIONS`.
- [ ] `tests/unit/django_apps/test_py314_readiness_policy.py` and
      `tests/integration/django_apps/test_py314_readiness_policy.py` — every
      matrix row, plus the series reconciliation against both collectors.
- [ ] `docs/deployment.md` — the operator section, after the remediation one.

**Acceptance Criteria:**
- Given a verified result and no assessment, when the policy runs, then the row is
  `verified_ready`/`verified_not_ready`, evidence type `verified`, citing the
  verification.
- Given an assessment and no verification, then the row is
  `inferred_ready`/`inferred_not_ready`, evidence type `inferred`.
- Given both, then the verification decides the verdict, the evidence type is
  `verified`, and **both** rows are cited.
- Given no evidence, unreadable evidence or stale evidence, then the row is
  `unknown` with evidence type `none` — never `not_ready`.
- Given a hand-written `INSERT`, when the evidence type contradicts the verdict,
  then the database refuses it.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage
  above the floor.

## Design Notes

**Why the derived verdict may say what the collector could not.**
`collectors/outcomes.py` refuses `verified_incompatible` and records
`verification_failed`, because a build fails for reasons that are not the
interpreter and a collector may reach no verdict at all (`CPM-AD-8`). "This package
is not ready" *is* a verdict, drawn from the best evidence there is, and reaching
it is what a policy pass exists to do. The two registers are the collector/policy
line, and a unit case compares all three vocabularies as sets so a rename on any of
them that collapsed the distinction fails.

**Why the redundancy between the value and the column is the design.** Carrying the
evidence type only in `evidence_type` was the tidier option and is the one this
story declines: `CPM-AD-24` renders a status verbatim, so a surface projecting
`readiness` alone would show `ready` for a package nobody has ever built. The
column exists so a query can filter without a `LIKE` over prefixes; the value
exists so a projection cannot lose the distinction. Three check constraints keep
them agreeing.

**Why the latest verification wins rather than a per-platform breakdown.** A
verification is about one platform, and reducing several into one verdict is a
different question from the one `CPM-FR-19` asks. The pass reads the latest result
as of the cut-off — the "latest observation" convention every pass in this
application takes — and the row cites it, which is what names the platform. A
per-platform table is recorded in the spec as the alternative not taken.

**Why staleness withholds one reading rather than the whole answer.** A stale
verification beside a fresh assessment falls through to the inference, with
`evidence_stale` recording that something behind the row was old. Discarding both
would throw away evidence this product does trust, and `unknown` would read as
"nobody looked" for a package somebody did.

## Verification

- `pixi run ci` — the gate.
- `tests/unit/django_apps/test_py314_readiness_policy.py` — the reduction, the
  three-vocabulary collision check, the series reconciliation against both
  collectors, and every absence.
- `tests/integration/django_apps/test_py314_readiness_policy.py` — the rows a real
  policy run writes, the cut-off and series filters, and the five constraints.

## Dev Agent Record

### Completion Notes

**What ships.** The sixth policy pass, and the first code in the repository that
reads both of `CPM-EP-PY314`'s evidence tables. It writes
`package_python_readiness`, one row per package per run, carrying a verdict whose
value names the evidence type behind it and a column that states the same fact for
a query.

**Files added:** `policies/py314_readiness.py`,
`policies/migrations/0006_package_python_readiness.py`, and both test modules.

**Files changed:** `policies/outcomes.py` (the sixth composed vocabulary plus a
sentinel-free `ReadinessEvidence`), `policies/models.py` (the sixth derived table),
`policies/apps.py` (the roster and its ordering narrative), `docs/deployment.md`,
and four test modules carrying a roster, a module list, a migration list or the
rollup's per-domain version map.

**Each acceptance criterion, and where it is enforced rather than asserted:**

- **AC 1 (a verdict, and the evidence type).** The four determinate values name
  the evidence type; `evidence_type` states it; and three check constraints refuse
  a row whose two columns disagree, including the third side that stops an
  `unknown` row claiming an evidence type.
- **AC 2 (the distinction survives).** A package with both kinds of evidence
  produces one row citing **both**, resting on the verification, with `detail`
  naming agreement or disagreement. Proved on real rows in the integration tier —
  the only place in the repository where the epic's two evidence tables and its
  derived table meet.

**Two decisions were put to the user at the spec checkpoint** and both were
confirmed: the prefixed value *and* the column rather than either alone, and proof
winning a disagreement with the conflict recorded rather than the disagreement
reading `unknown`.

**One defect the tests found and the code fixed:** `readiness_of` originally
checked the cut-off's awareness only where a staleness comparison happened to touch
it, so a package with **no** evidence — the majority row — took a branch that
accepted a naive cut-off silently. The guard is now at the function's boundary.

**Coverage:** the new pass, the new table and the extended vocabulary are at 100%;
the gate's floor is 90%.
