---
title: 'CPM-SECURITY-S05: Licence policy as versioned data'
type: 'feature'
created: '2026-09-07'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: true
baseline_revision: 'b44b7456f186345de63e7785cc18af1be8cc94b0'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s03-licence-evidence-raw-normalized.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s04-vulnerability-kev-rollup.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s07-currency-policy-as-versioned-data.md
warnings:
  - oversized
deferred: []
---

# CPM-SECURITY-S05: Licence policy as versioned data

Epic: `CPM-EP-SECURITY` — Vulnerability, KEV and licence exposure

<intent-contract>

## Story

As a compliance reviewer,
I want licence outcomes computed from a versioned policy I can change without a deployment,
so that a policy revision can be replayed over history.

## Acceptance Criteria

1. **Given** licence evidence
   **When** the policy runs
   **Then** it derives allowed, restricted, forbidden, unknown or manual-review
   **And** the policy is data, not code branches, and its version is recorded on every result

2. **Given** the policy content changes
   **When** it is re-run against unchanged evidence
   **Then** it reproduces new results without recollection

## Intent

**Problem:** `CPM-SECURITY-S03` records what a package is licensed under and deliberately
makes no compliance judgement, because `CPM-FR-18` gives that to a versioned policy that does
not exist. This story is that policy. Its content — which licences are allowed and which are
forbidden — is PRD Open Question 2 and nobody has answered it, so the epic entry constrains
this story to shipping **the mechanism and a schema, not a seeded policy**.

**Approach:** A fourth policy pass beside `currency`, `feedstock` and `vulnerability`, writing
its own per-domain derived table keyed `(package, policy_run)`. It reads `license_findings` as
of the run's cut-off and reduces each package to one of the five `CPM-FR-18` outcomes by
matching the normalized SPDX expression against a rule set held in the versioned parameters
file. With no rules seeded, nothing matches, and every package routes to manual review. That
is not a placeholder — it is the correct answer to "no policy has been decided", and it is
exactly what `CPM-SECURITY-S03`'s second acceptance criterion already promised would happen to
a licence this product cannot judge.

## Boundaries & Constraints

**Always:**
- The pass writes **only** its own per-domain table, keyed `(package, policy_run)`
  (`CPM-AD-21`). It does not write the health rollup.
- **`allowed` is never a default and never an absence.** It is reached only by a rule that
  names the licence and says so. Every other path — no rule matched, no rules recorded, an
  `unknown` licence row, a blank normalized expression, an `error` or `not_found` row —
  reaches `manual_review` or `unknown`, never `allowed`. This is the single property the
  whole story turns on.
- The rule set is **data** in `policies/data/policy-parameters.toml`, read the way the three
  shipped passes read theirs. No licence identifier appears in a code branch.
- Every row records the policy version that produced it, so the same evidence at two versions
  yields two readable results (`CPM-FR-22`).
- Evidence is read as of the cut-off, never from a collection run still `running`.
- Time comes from the injected clock; `pixi` is the only runner; `pixi run ci` exits 0.

**Block If:**
- Seeding the rule set requires answering PRD Open Question 2. **Do not answer it.** Ship the
  schema with **no allow entries and no deny entries**, and let every package reach
  `manual_review`. If review finds that a pass which allows nothing is not worth shipping,
  HALT and record it rather than inventing a licence policy.

**Never:**
- **No seeded allow list and no seeded deny list.** Not "a provisional one", not "a
  conservative starting point", not permissive licences "everyone agrees on". `CPM-FR-18`'s
  content is Open Question 2 and this story is constrained by its own epic entry to ship the
  mechanism only. This differs from `CPM-SECURITY-S04`'s provisional severity order, where the
  PRD named a risk level with no seed; here the PRD names the *decision itself* as open.
- **A version recording no rule set must not fail the package.** Derive `manual_review` and
  record why. `CPM-AD-23`'s atomic unit is the package and all passes for one package share a
  transaction, so a refusal here would roll back the other three domains' rows and break
  replay for every run recorded before this pass existed. That is the defect
  `CPM-SECURITY-S04`'s review found in four documents; do not reintroduce it.
- No write to the health rollup, no new column on it, and no re-derivation of a status another
  pass owns.
- No re-reading or re-collection of licence evidence. AC 2 says a policy change reproduces new
  results **without recollection**.
- No change to `core/`, to any collector, or to the three shipped policy passes.
- No priority bucket, score, rank or work type (`CPM-FR-20`, Open Question 8,
  `CPM-EP-PRIORITY`).
- No `timezone.now()` anywhere.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No rules recorded (the shipped state) | the version records an empty rule set | every package with licence evidence reaches `manual_review`, the row saying no rule set was recorded | Never `allowed`, never a failure |
| A rule allows the licence | a rule names the normalized expression as allowed | `allowed`, the row naming the rule that matched | The only path to `allowed` |
| A rule forbids the licence | a rule names it as forbidden | `forbidden`, naming the rule | |
| A rule restricts the licence | a rule names it as restricted | `restricted`, naming the rule | |
| Rules recorded, none matches | a non-empty rule set that does not name this licence | `manual_review`, distinct from the no-rules-recorded case | Never `allowed` |
| The licence row is `unknown` | `CPM-SECURITY-S03` recorded an unrecognised or unstated licence | `unknown`, and the row says the licence itself was never established | Distinct from `manual_review` |
| No licence evidence at all | no `license_findings` row as of the cut-off | `unknown` | Never `allowed`, never clean |
| Only an `error` or `not_found` row | the collector failed, or no channel served the package | `unknown`, the row saying which | Never `allowed` |
| Several channels disagree | two determinate rows with different licences | one row per package, and the outcome is the least permissive the rules yield | Disagreement never resolves upward |
| A rule names a licence no evidence uses | the rule set is broader than the inventory | no effect, no failure | |
| Two rules name the same licence differently | one allows it, one forbids it | refused as a malformed rule set, naming both | An operator error, not a verdict |
| A malformed rule set | wrong type, blank identifier, unknown disposition, duplicate entry | refused, naming every fault at once | The parameters-file precedent |
| Evidence newer than the cut-off | a row observed after the cut-off | ignored | Replay reproduces it |
| Same evidence, two versions (AC 2) | the rule set changes, the evidence does not | two rows, each recording its own version, both readable, no recollection | The point of the story |
| Re-run at the same version and cut-off | the pass runs twice | identical values | |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/policies/vulnerability.py` -- the newest
  and closest sibling, and the one whose Review Triage Log matters most. Read that log before
  writing anything: it records the replay regression, the sweep-alignment defect, and the
  tautological guard, and this story can reproduce all three.
- `policies/currency.py`, `policies/feedstock.py` -- the two older passes.
- `policies/models.py` -- the three derived tables are the shape. Add `PackageLicense` /
  `package_license`: `package` FK, `policy_run` FK, `license_outcome`, `policy_version`,
  `evidence_cutoff`, the FK to the `LicenseFinding` that supported it, the matched rule's
  identifier, and a `detail`. Constraints mirroring the siblings: a determinate outcome names
  its finding, and `allowed` additionally names the rule that produced it -- so an `allowed`
  row that names no rule is refused **by the database**, not only by the pass.
- `policies/outcomes.py` -- three vocabularies live here with their precedence orders. Add the
  five-valued licence vocabulary. Its precedence ranks `forbidden` worst and `allowed` best,
  with `manual_review` and `unknown` between them and **never** collapsing into each other.
- `policies/parameters.py`, `policies/data/policy-parameters.toml`,
  `policies/data/README.md` -- how a version is read, how a malformed value is refused, and
  the added-never-edited contract. `CPM-SECURITY-S04` added `2026.09.1`; add the licence rule
  schema to a new entry, and read that story's handling of a version that records nothing.
- `policies/apps.py`, `policies/migrations/` (`0003` is the newest, add `0004`) -- the pass's
  position in the run's declared ordered list.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` -- `LicenseFinding`
  and its read index, the evidence being reduced.
- `collectors/outcomes.py` -- `LicenseOutcome`, whose determinate member is `normalized` and
  which declares no precedence. That stays true; the ranking is a policy decision made here.
- `tests/unit/django_apps/test_vulnerability_policy.py` and its integration counterpart -- the
  module shapes, and the mutation-test style the last review forced.
- `tests/passes.py`, `tests/policy_parameters.py` -- shared helpers, including the recorded
  version constant. Adding a parameter key may oblige it to move again; `policies/data/README.md`
  now records when that is required.
- `docs/deployment.md` -- the policy sections, and specifically how an operator seeds the rule
  set once Open Question 2 is answered.

## Tasks & Acceptance

**Execution:**
- `policies/outcomes.py` -- the five-valued licence vocabulary and its precedence.
- `policies/models.py` + `policies/migrations/0004_package_license.py` -- the derived table,
  its `(package, policy_run)` key, its evidence FK and its constraints.
- `policies/parameters.py` + `policies/data/policy-parameters.toml` -- the rule schema and its
  refusals, with **no allow or deny content**.
- `policies/licence.py` -- new. The pass.
- `policies/apps.py` -- registration and position in the ordered list.
- `tests/unit/django_apps/test_licence_policy.py`,
  `tests/integration/django_apps/test_licence_policy.py` -- every matrix row.
- Every roster and audit test carrying a policy-pass or model count.
- `policies/data/README.md` and `docs/deployment.md`.

**Acceptance Criteria:**
- Given the shipped empty rule set, when the pass runs over any licence evidence, then no row
  is `allowed` and every package with evidence is `manual_review`.
- Given a rule set that allows a licence, when the pass runs, then the row is `allowed` and
  names the rule; and an `allowed` row that names no rule is refused by the database.
- Given a version recording no rule set, when the run executes, then the currency, feedstock
  and vulnerability rows for that package still commit and the run does not finalize `failed`.
- Given unchanged evidence and a changed rule set, when the pass re-runs at the new version,
  then it produces different outcomes with no collection run in between.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

### 2026-09-07 — Recorded before implementation

**Why this ships empty where `CPM-SECURITY-S04` shipped provisional.** S04 met a requirement
that named a risk level and seeded no thresholds, and resolved it the way `CPM-CURRENCY-S07`
resolved `feedstock_inactivity_days`: a provisional value, marked as provisional in the file.
This story is not that shape. PRD Open Question 2 names *the decision itself* as unanswered and
as blocking this epic, and the epic entry constrains the story to "the mechanism and a schema,
not a seeded policy". A provisional allow list would be this component deciding a compliance
question it was told not to decide. Empty is the answer, and `manual_review` is what empty
produces.

**Why an unrecorded rule set must not refuse.** Carried forward from `CPM-SECURITY-S04`'s
review, where four documents asserted that a per-package refusal contains the damage to one
pass. It does not: `core/policy_run.py` wraps every pass for one package in one transaction, so
a refusal discards the other domains' rows, and a version-wide condition fails every package
and finalizes the run `failed`. Replay for runs recorded before this pass existed would break.

## Design Notes

**Why `allowed` needs a database constraint and not just a code path.** Every other outcome can
be reached by absence — no evidence, no match, no rules. `allowed` is the one value that must
only ever be reached by a positive statement, and it is the one whose appearance in error would
be least likely to be noticed, because it looks like good news. A constraint requiring an
`allowed` row to name the rule that produced it means the database refuses the failure mode
rather than trusting the pass to avoid it.

**Why `manual_review` and `unknown` are both needed.** They answer different questions.
`unknown` means the licence itself was never established — the evidence row said so.
`manual_review` means the licence *is* known and this product has no rule for it. Collapsing
them would hide which of the two a reviewer is being asked to fix.

## Verification

**Commands:**
- `pixi run test`, `pixi run format && pixi run lint && pixi run typecheck`,
  `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected".
- `pixi run ci` -- expected: exit 0; coverage >= 90%, new modules at 100%.
- `pixi run gate-postgres` -- expected: the suite passes against `postgres:17`. Note that this
  task can exit 3 on a local coverage-combine artifact after every test passes; confirm
  `N passed, 0 failed` before treating it as a failure.

## Dev Notes

**Satisfies:** `CPM-FR-18`

**Governed by:**

- `CPM-AD-8` — Policy is a separate versioned pass, not a collector's business

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- Time comes from the injected clock in `core` (`CPM-AD-26`).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-SECURITY-S05]
- [Source: ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: prd.md#CPM-FR-18]
- [Source: prd.md#Open-Question-2]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context) — `claude-opus-5[1m]`.

### Debug Log References

- `pixi run makemigrations policies --name package_license`, then hand-edited
  dependencies down to only what the table references
  (`collectors.0009_license_findings`, `core.0002_run_ledger`,
  `identity.0001_package_identity`, `policies.0003`), on the terms
  `0002_package_feedstock_presence` and `0003_package_vulnerability` record.
  `pixi run manage makemigrations --check --dry-run` then reports "No changes
  detected".
- `pixi run lint` flagged `PLR0911` on `_license_rule_fault` (nine returns).
  Split into `_rule_expression_fault` and `_rule_disposition_fault` rather than
  recorded as a `noqa`: the two are about different fields with different rules,
  and the split is the shape `_risk_label_fault` already has.
- The check-constraint mutation test does **not** reproduce by editing
  `policies/models.py`: `--reuse-db` keeps the schema the migration built, so a
  weakened model constraint leaves the database's own untouched. The mutation has
  to be made in `0004_package_license.py` and run with `--create-db`. Both halves
  are covered by cases — the unit tier asserts the constraint *names* off
  `_meta`, the integration tier asserts the database *refuses* the rows.

### Completion Notes List

**The `Block If` was honoured, not blocked on.** `license_rules` ships with no
allow entries and no deny entries. Every package whose licence this run
established reaches `manual_review`; every package whose licence it did not
reaches `unknown`; nothing reaches `allowed`. No HALT was warranted: a pass that
allows nothing is worth shipping precisely because `allowed` becoming reachable
later is then a reviewed pull request against one file rather than a code change,
which is what `CPM-AD-8` wants — and because `manual_review` on a known licence
is a *verdict*, not a placeholder, and it is the one `CPM-SECURITY-S03`'s AC 2
already promised.

It is also enforced rather than merely intended.
`test_no_shipped_version_records_any_licence_rule` reads the shipped file and
fails if any version records a rule, so adding a "provisional" allow list is a
deliberate edit to a test as well as to the file. Nothing else in the repository
would have noticed one.

**Where the spec was interpreted rather than followed literally.** Five places,
each argued in the code it produced:

1. **`license_rules` is optional, and an absent key and an empty list parse to
   the same `()`.** The matrix's first row says "the version records an empty
   rule set", and the Code Map says to add the schema to a new entry. Both are
   satisfied, but the *parsed* state is single: a version predating the key and a
   version recording `[]` mean the same thing — no rule names any licence — so
   there is one un-ruled state and no verdict anywhere has to distinguish two.
   This is deliberately unlike `vulnerability_risk_order`, where an empty list is
   **refused** and `None` is therefore unambiguous: there an empty order would
   produce a blank risk level for the whole inventory, indistinguishable from
   sources that state no severities, whereas here an empty rule set produces a
   distinct, self-describing verdict and is the shipped answer.
2. **`2026.09.2` was added and is data-identical to `2026.09.1` in behaviour.**
   The Code Map asks for a new entry; nothing about the licence pass differs
   between the three shipped versions. What the entry adds is a *statement* —
   review looked at the licence policy and recorded nothing — plus the commented
   schema an operator copies when Open Question 2 is answered. `2026.09.1` was
   left unedited and `A_RECORDED_POLICY_VERSION` did **not** move, which
   `policies/data/README.md` now records as the ordinary case beside
   `CPM-SECURITY-S04`'s exception.
3. **The `allowed` constraint covers `restricted` and `forbidden` too.** The Code
   Map singles out `allowed`, and it is the value the constraint exists for. All
   three are reachable only from a rule's recorded disposition, so holding the
   rule on one of them would be the "sibling rule on one half only" defect
   `ESTABLISHED_VULNERABILITY_STATUSES` records. A fourth constraint asserts the
   converse — an outcome no rule decided may **not** name a rule — because a
   `manual_review` naming a matched rule is a contradiction rather than an
   unusual row.
4. **A rule field is `expression`, not `license`.** What a rule matches is
   `license_findings.normalized_license`, which is an SPDX *expression* and may
   be compound. The name says what it is, and it avoids shadowing a builtin in a
   repository whose ruff configuration selects `A`.
5. **The module is `licence.py` and the pass is `licence`; the model, table and
   columns are `license`.** The story dictates both spellings and they are kept
   apart on purpose: schema names follow the schema that already exists
   (`license_findings`, `LicenseFinding`), so a reader joining `package_license`
   to `license_findings` never meets two spellings in one query, while this
   component's prose and its module name stay British as the epic's do.

**A compound expression is matched whole, and that is a decision the spec did not
take.** `normalized_license` may hold `MIT OR Apache-2.0`. Deciding what a
disjunction of two differently-ruled licences comes to is a compliance judgement,
not a string operation, so the comparison is over the whole expression and an
unmatched compound reaches `manual_review` — the conservative direction. Recorded
in the pass's docstring, the parameters file and `docs/deployment.md`, because a
reviewer writing `MIT` and expecting it to cover `MIT OR Apache-2.0` would
otherwise be surprised by a silent `manual_review`.

**The three defects `CPM-SECURITY-S04`'s review found, and what was done about
each.**

1. *A version recording no rule set does not refuse.* `LicensePass._rules`
   returns `()` and the row says the version records none.
   `test_a_version_recording_no_rule_set_still_writes_all_four_domains_rows`
   asserts that the currency, feedstock, vulnerability **and** health rows all
   commit and the run finalizes `succeeded`; reinstating the refusal fails seven
   cases across the two modules, which was checked by making the mutation. A
   *malformed* rule set is still refused, in `policies/parameters.py` at the
   read.
2. *No tautological guard.* The story's central property is asserted by two runs
   that genuinely differ:
   `test_the_same_evidence_reads_allowed_or_manual_review_by_whether_a_rule_names_it`
   drives `evaluate` over two packages with byte-identical licence evidence, one
   at a version whose rule set names that licence and one at a version recording
   none, and requires `allowed` on one and `manual_review` on the other. Both
   halves are load-bearing: a pass defaulting to `allowed` fails the second, and
   a pass that could never produce `allowed` fails the first — and the second
   half is exactly what every "this row is not allowed" assertion elsewhere in
   the module would have missed. Making `finding_verdict` return `ALLOWED` for an
   unmatched licence fails twelve cases.
3. *No absence the run never established.* `unknown` and `manual_review` are
   separate members with separate ranks that never collapse, and the row says
   which of the four kinds of "nothing established" it met — a channel that could
   not be read, one that does not serve the package, one whose licence this
   product will not normalize, and a determinate row carrying no expression at
   all. A blank `detail` on an `unknown` now means one thing only: there was no
   evidence.

**The three things this story exists to get right.**

- *`allowed` is never a default and never an absence.* Held in three places, and
  the third is the one the story asked for: `policies/licence.py` returns a
  rule's own recorded disposition and contains no branch spelling `allowed`;
  `LICENSE_PRECEDENCE` ranks it last so a reduction cannot reach it while any
  channel said anything else; and
  `license_outcome_names_the_rule_that_produced_it` makes PostgreSQL refuse a
  row that claims it while naming no rule. That constraint was mutated in the
  migration and re-run with `--create-db`: three cases fail without it.
- *`manual_review` and `unknown` answer different questions.* Two members, two
  ranks, two sets of detail lines, and `JUDGED_LICENSE_OUTCOMES` puts
  `manual_review` inside the "names its finding" constraint precisely because it
  is the value a reader is least likely to check.
- *The rules are data.* No licence identifier appears in a code branch anywhere
  in `src/`. AC 2 is
  `test_two_runs_at_two_versions_over_one_cutoff_reach_two_outcomes_without_recollection`,
  which runs the same evidence at two versions ruling one expression in opposite
  directions and asserts the collection-run count is unchanged between them.

**Both traps avoided.** Nothing writes `package_health` or adds a column to it;
`LicensePass.contributes` is empty and an integration case asserts the rollup
carries no licence field. `tests/passes.py`'s synthetic `licence_status` column
is still unowned, and its comment now records why. Precedence is decided in
`policies/outcomes.py` as one declared order; no rank was added to
`collectors/outcomes.py`, whose `LicenseOutcome` still declares none.

**A note for the next reader of `test_single_ordering_audit.py`.**
`LICENSE_PRECEDENCE` is the fourth order that file's detector cannot see, for the
reason the two `CPM-SECURITY-S04` orders cannot: it holds one `OutcomeState`
member reference and the detector matches two or more. That is a property of the
vocabulary — the reduction never meets the other three sentinels — so the audit's
recorded table still describes `policies/outcomes.py` at one visible declaration,
and this order is pinned by name and by contents in
`tests/unit/django_apps/test_licence_policy.py` instead.

**Two stale sentences left in place, deliberately.**
`policies/vulnerability.py` says twice that `core/policy_run.py` "wraps all
three passes for one package in one transaction"; it is four now. The Never list
forbids changing any of the three shipped passes, and the claim those sentences
are making -- that the atomic unit is one *package* and not one pass -- is still
exactly true and is the whole point they exist to make. `tests/passes.py`'s copy
of the same sentence *was* corrected to "every pass", because that file is this
story's to edit and a number there would go on drifting with each new pass.

**Deferred, recorded rather than done.** Making the evidence reads set-based
across the inventory — this pass adds three queries per package to the currency
pass's five, the feedstock pass's two and the vulnerability pass's five — on the
terms all three earlier stories recorded the same deferral.

**Verification.** `pixi run ci` exit 0 (6855 passed, 2 skipped; coverage 99.13%;
all four policy modules at 100%, `policies/licence.py` at 116/116 statements).
`pixi run manage makemigrations --check --dry-run` reports "No changes detected".
`pixi run test-integration` exit 0. `pixi run gate-postgres` exit 0 against
`postgres:17` -- 6855 passed, zero failures, and the local coverage-combine
artifact `CPM-SECURITY-S04` recorded did not reproduce on this run.

### File List

**New**

- `src/django_apps/conda_package_supply_chain_monitor/policies/licence.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/migrations/0004_package_license.py`
- `tests/unit/django_apps/test_licence_policy.py`
- `tests/integration/django_apps/test_licence_policy.py`

**Modified**

- `src/django_apps/conda_package_supply_chain_monitor/policies/outcomes.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/models.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/parameters.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/apps.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/data/policy-parameters.toml`
- `src/django_apps/conda_package_supply_chain_monitor/policies/data/README.md`
- `docs/deployment.md`
- `tests/passes.py`
- `tests/policy_parameters.py`
- `tests/unit/django_apps/test_policies_app.py`
- `tests/unit/django_apps/test_derived_status_writability_audit.py`
- `tests/unit/django_apps/test_single_ordering_audit.py`
- `tests/integration/django_apps/test_rollup.py`

**Unchanged, and deliberately so**

- `src/config/settings/base.py` — the policy run's ordered list is
  `policies/apps.py`'s `ready()` tuple, not a setting; the application is already
  installed and this story adds no other declaration there.
- `core/collection.py`, `core/outcomes.py`, `core/rollup.py`, `core/models.py`,
  `core/policy_run.py`, every collector, and all three shipped policy passes —
  the Never list.
- `collectors/outcomes.py` — `LicenseOutcome` still declares no precedence, and
  the ranking is a policy decision made in `policies/outcomes.py`.

## Auto Run Result

**Outcome:** done, with a follow-up review recommended.

**Review loop:** one iteration, four parallel layers. Four must-fix, four should-fix, eleven
record-only. Two of the must-fix items changed compliance semantics, and one of those was
found independently by three of the four reviewers.

**The defect three reviewers reached separately.** `collectors/license.py` writes one row per
monitored channel and never fewer, so a package carried by conda-forge but absent from
bioconda produces a determinate `MIT` row *and* a `not_found` row in the same sweep. The
precedence ranks `unknown` worse than both `manual_review` and `allowed`, and the reduction
consumed every row including sentinels — so that package reduced to `unknown` no matter what
conda-forge said.

The consequence was that the pass's entire determinate output collapsed for the common
multi-channel case. `manual_review` was masked, and once Open Question 2 is answered `allowed`
would have been effectively unreachable. The five-value vocabulary exists to separate a gap in
the evidence from a gap in the policy, and this destroyed that distinction exactly where the
licence *had* been established. Three documents stated the opposite of what the code did, and
a unit test asserted the wrong behaviour as correct beneath a docstring claiming a guarantee
it never checked.

The fix separates two sentinels that were being treated alike. A channel that does not carry
the package has said nothing about its licence, so it no longer votes — the same principle the
module already applied to blank expressions, applied consistently. A channel whose read failed
is genuine uncertainty, so it still downgrades. This only ever removes an `unknown` vote, so
`forbidden` and `restricted` still win from any channel that states them, and both matrix rows
that expect `unknown` from absence still hold: an empty reduction and a reduction over
absences both answer `unknown`.

**A row denied a licence that had been established.** Fallout of the same shape and a defect on
its own. With one determinate channel and one errored channel, the supporting row was the
error, and the detail line ended "so this run established no licence for this package". A
channel had. The determinate statement vanished from the row entirely, and since `detail` is
the only thing distinguishing the four kinds of `unknown`, the one signal a reviewer would have
had pointed them the wrong way. All four lines are now worded about the channels they name, and
a new line fires whenever a determinate expression exists but did not win.

**A mistyped rule was permanently inert.** The rule schema validated type, blankness,
whitespace and length, and explicitly declined to check content. But `normalized_license` is
never free text — the normalizer only emits canonical identifiers joined by `AND` or `OR` — and
`CPM-SECURITY-S03` deliberately removed the GNU abbreviations because they guess a disposition.
So a reviewer writing `GPL-3.0` forbade nothing, for ever, with no refusal and no log line, and
every affected package read `manual_review`, indistinguishable from having no rule. The deny
half of the policy failed silently, which is the failure an operator is least able to detect.
Rule expressions are now validated against what the normalizer can actually produce, reading
the recognised set off the normalizer's own table rather than restating it.

**A conjunction was more permissive than a single licence.** `MIT AND GPL-3.0-only` with a rule
forbidding the second operand fell through to `manual_review`, which ranks below `forbidden` and
below `unknown`. Three documents called whole-expression matching "the conservative direction"
using only the `OR` example, where it genuinely is conservative. For `AND` it is not: a
conjunction binds both sets of obligations. Conjunctions are now decomposed in the **restrictive
direction only**, with the permissive set excluded by construction rather than by care, so no
decomposition can ever reach `allowed`. `OR` is untouched, and all four documents were
corrected.

**On the Block If.** It held. `license_rules = []` ships with no allow entries and no deny
entries, and an integration case reads the real shipped file and fails if any version records
any rule — so seeding one later is a deliberate edit to a test as well as to the data. The
central property was verified as genuinely load-bearing rather than tautological, which is what
the sibling story's equivalent test turned out not to be: two packages, byte-identical evidence,
two versions, driven through `evaluate`, so neither an always-`allowed` nor a never-`allowed`
implementation survives it.

**Recorded rather than fixed.** Eleven items, including a commented example in the parameters
file that still lists real identifiers, a `CPM-AD-24` citation doing work that decision's text
does not do, three stale sentences in the shipped vulnerability pass that the Never list
protects, and three more in that story's test modules that it does not. Each is named with its
location so a later sweep can find it.

**Why a follow-up review is recommended.** The channel-masking defect was invisible to a suite
with full line coverage, because no test drove the detail path over a mixed determinate and
sentinel sweep. Any later pass that reduces per-channel evidence should be read against the
collector's actual row-writing behaviour rather than against the shape its own tests construct.

**Verification:** `pixi run ci` exit 0 (6898 passed, 2 skipped; coverage 99.14%;
`policies/licence.py` and `policies/parameters.py` both 100%). `pixi run gate-postgres` exit 0
against `postgres:17`. `makemigrations --check --dry-run` reports no changes. Migration `0004`
was not touched. Twelve mutation checks were run, one per behaviour change, each killing its
intended case and nothing unrelated.
