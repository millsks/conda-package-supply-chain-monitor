---
workflowStatus: 'completed'
totalSteps: 5
stepsCompleted:
  ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
nextStep: ''
lastSaved: '2026-09-03'
workflowType: 'testarch-test-design'
inputDocuments:
  [
    '_bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md',
    '_bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md',
    '_bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/solution-design.md',
    '_bmad-output/planning-artifacts/epics.md',
    '_bmad-output/test-artifacts/test-design-progress-system.md',
  ]
---

# Test Design for Architecture: Conda Package Supply Chain Monitor (System Level)

**Purpose:** Architectural concerns, testability gaps, and NFR requirements for review by Architecture/Dev teams. Serves as a contract between QA and Engineering on what must be addressed before test development begins.

**Date:** 2026-09-03
**Author:** Murat — Test Architect (BMad TEA)
**Status:** Architecture Review Pending
**Project:** Conda Package Supply Chain Monitor
**PRD Reference:** `_bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md`
**ADR Reference:** `_bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md` (24 `CPM-AD-*` invariants) and the companion `solution-design.md`

---

## Executive Summary

**Scope:** A system-level test design covering the whole product as specified today: 41 `CPM-FR-*`, 13 `CPM-NFR-*`, 6 `CPM-SM-*` (three of them counter-metrics), 3 `CPM-UJ-*` user journeys, 24 `CPM-AD-*` architecture invariants, and 9 epics / 42 stories / 131 acceptance criteria. No implementation of the product's own domain apps exists yet, so every recommendation in this document is a design-time change rather than a refactor.

**Business Context** (from PRD):

- **Revenue/Impact:** Not a revenue product. The measured outcomes are the `CPM-SM-*` success metrics, of which the defining one is the counter-metric `CPM-SM-C1` — a package must never read clean when it is unassessed, contradicted, or stale.
- **Problem:** The organization has no trustworthy, continuously refreshed view of the supply-chain state of the conda packages it depends on, and the failure mode that matters is a confident-looking answer that is wrong.
- **GA Launch:** No date is set in the PRD. Milestones in this document are therefore expressed against epics (`CPM-EP-EVIDENCE`, `CPM-EP-APP`, `CPM-EP-NL`) rather than dates.

**Architecture** (from the 24 `CPM-AD-*` spine invariants):

- **Key Decision 1:** Append-only evidence. Facts are inserted with an `observed_at`, never updated; derived state is computed from evidence, never edited in place (`CPM-FR-32`, `CPM-FR-36`).
- **Key Decision 2:** A five-state model for every derived status — determinate, `unknown`, `not_found`, `not_applicable`, `error` — with a single total precedence order, plus a single-writer rule for the rollup (`CPM-AD-21`: no policy pass writes the rollup).
- **Key Decision 3:** Pinned stack — Python 3.14, Django 5.2, DRF, Celery with three queues (`CPM-AD-20`), PostgreSQL 17 with a second read-only `analytics` alias once `CPM-AD-16` lands, Redis, OTLP-based observability, pytest under `pixi run ci`.

**Expected Scale** (from PRD and spine):

- 10,000 packages in full inventory with no manual batching (`CPM-NFR-1`), a p95 latency budget at that size whose value is unset (`CPM-NFR-5`, Open Question 5), eight collectors reading external read-only sources, and scheduled sweeps on the `collect`, `policy` and `verify` queues.

**Risk Summary:**

- **Total risks**: 14
- **High-priority (≥6)**: 11 risks requiring immediate mitigation, three of which score the maximum 9
- **Test effort**: 53 planned scenarios (30 P0, 20 P1, 3 P2, plus P3 exploratory), estimated at ~80–130 hours — roughly 2 to 3.5 weeks for one engineer, or 1 to 2 weeks for two, spread across the epics rather than front-loaded

---

## Quick Guide

### 🚨 BLOCKERS - Team Must Decide (Can't Proceed Without)

**Pre-Implementation Critical Path** - These MUST be completed before QA can write integration tests:

1. **ASR-1: An injectable clock, used everywhere, enforced by an audit** - Architecture must place a single clock abstraction in `core` that every collector, policy pass and freshness computation reads, so no module calls `timezone.now()` directly (recommended owner: Architecture + `CPM-EP-EVIDENCE` dev)
2. **ASR-2: A transport seam in the collector base** - Architecture must decide where the HTTP/transport boundary sits in `CPM-EVIDENCE-S05`, because that decision alone determines whether eight collectors' parsing logic is unit-testable or integration-only (recommended owner: Architecture + `CPM-EP-EVIDENCE` dev)
3. **ASR-3: A policy-pass registry that makes the single-writer rule auditable** - Passes must register with the policy run and declare the derived table each one owns, rather than being called directly, so `CPM-AD-21` can be mechanically enforced against passes not yet written (recommended owner: Architecture + `CPM-EP-EVIDENCE` dev)
4. **ASR-4: Freshness targets as required configuration, refused at startup when absent** - Every registered collector must declare a freshness target, and startup must raise `ImproperlyConfigured` when one does not, following the inherited `CG-3` convention that a refusal raises rather than warns (recommended owner: Architecture + Product, since the target *values* are Open Question 7)
5. **ASR-5: The `analytics` alias's test configuration and the meaning of the inherited assertion** - `CPM-AD-16` adds an alias with `ATOMIC_REQUESTS = False`, while inherited platform code asserts every alias has it true; the team must decide whether that inherited assertion is amended to mean "every alias Django may write through", and whether the analytics alias gets a `TEST` mirror (recommended owner: Architecture + platform owner — this is a cross-boundary change to inherited code)

**What we need from team:** Complete these 5 items pre-implementation or test development is blocked. Items 1 through 4 must be settled before `CPM-EP-EVIDENCE` ships; item 5 must be settled before `CPM-EP-NL`, which is separately blocked behind its fitness spike.

---

### ⚠️ HIGH PRIORITY - Team Should Validate (We Provide Recommendation, You Approve)

1. **R-06: Evidence is updated, not inserted** - `save()` on the append-only base cannot catch `queryset.update()`, `bulk_update()` or raw SQL. Recommendation: a mutation-path `AUDIT` test over the whole source tree, plus a check that no evidence table carries a unique constraint that would suppress an insert. Approver: Architecture (implementation phase, `CPM-EP-EVIDENCE`)
2. **R-07: A sweep runs in one transaction** - Recommendation: declare the atomic unit as one package or one declared chunk, never the sweep, so `CPM-FR-15` partial success is reachable and the WAL is not pinned for the sweep's duration. Approver: Architecture + `CPM-EP-CURRENCY` dev (implementation phase)
3. **R-08: The confidence gate is re-implemented per policy** - Recommendation: exactly one implementation of the gate, audited so that no policy module defines its own, with `unmapped` reporting `unknown` for every gated status. Approver: Architecture + `CPM-EP-IDENTITY` dev (implementation phase)
4. **R-09 / R-10: Analytics write access and sensitive-field exposure** - Recommendation: enforce read-only at the database permission level rather than by convention, refuse writes and migrations in the router, and hold a field allowlist that the governed views are audited against. Approver: Security + Architecture (implementation phase, `CPM-EP-NL`)
5. **TC-4: Full-inventory scale cannot be exercised the obvious way** - Recommendation: assert the properties that make scale work — bounded query counts, chunking, pagination enforcement, streaming export — in the gating suite, and carry the actual 10,000-package volume run in a separate non-gating job. Approver: Architecture + Dev (implementation phase)
6. **TC-5 / R-11: Queue routing is invisible because Celery runs eager in test** - Recommendation: test routing as configuration — assert every registered task's declared route resolves to `collect`, `policy` or `verify` — rather than attempting to observe routing at runtime. Approver: Architecture + Dev (implementation phase)

**What we need from team:** Review recommendations and approve (or suggest changes).

---

### 📋 INFO ONLY - Solutions Provided (Review, No Decisions Needed)

1. **Test strategy**: Four levels — `UNIT` (pure logic, no database, network or filesystem), `INT` (real models and database), `API` (through DRF's client including authorization), and `AUDIT`, a project-specific level that mechanically reconciles a declared list of invariants against the tests or code that prove them. There is deliberately **no E2E level**: no browser framework is installed, no UX contract exists, and all three `CPM-UJ-*` journeys are reachable through `API` plus `INT`.
2. **Tooling**: The existing suite, extended rather than replaced — pytest, `tests/unit/`, `tests/integration/` with its directory-scoped `integration` marker hook, `tests/spikes/` excluded from the gate by filename, and the registered `integration`, `spike` and `forbidden_state` markers. The `AUDIT` level generalizes the pattern already working in `tests/unit/startup/forbidden_states.py` plus `tests/unit/startup/test_refusal_coverage_audit.py`. Everything runs through `pixi run ci`; pixi is the only Python runner in this project.
3. **Tiered CI/CD**: PR (`pixi run ci`) runs every `UNIT`, `AUDIT`, `INT` and `API` test with a budget under 15 minutes — the suite is 1,545 tests in roughly 30 seconds today and this design keeps everything gating. Nightly, non-gating: the 10,000-package volume run and live-transport contract checks against real external sources. Weekly, non-gating: Python 3.14 build-and-import verification across a package sample on the `verify` queue.
4. **Coverage**: 53 test scenarios prioritized P0–P3 with risk-based classification, ordered by residual risk rather than by epic. Full scenario detail, including every test ID, lives in the companion QA document.
5. **Quality gates**: P0 pass rate 100% with no exceptions; P1 ≥ 95%; every risk scoring ≥6 has a passing test before its epic is called done; coverage ≥ 90% (the project's existing floor, currently 97.04%); each of R-01, R-02 and R-03 has a passing `AUDIT` test before `CPM-EP-APP` starts; and the five UNKNOWN thresholds do not block the gate — each has a mechanism test now and a threshold test queued behind its open question.

**What we need from team:** Just review and acknowledge (we already have the solution).

---

## For Architects and Devs - Open Topics 👷

### Risk Assessment

**Total risks identified**: 14 (11 high-priority score ≥6, 3 medium, 0 low)

Scored per the `risk-governance.md` model: probability × impact, 1–3 on each scale, total 1–9. A score of ≥6 demands documented mitigation. The **Residual** figure quoted in each mitigation plan below is the score after the designed mitigation *and* the test that proves it, and it is the number that should drive sprint ordering.

#### High-Priority Risks (Score ≥6) - IMMEDIATE ATTENTION

| Risk ID  | Category | Description                                                                                                                                                          | Probability | Impact | Score | Mitigation                                                                                                       | Owner (recommended)      | Timeline                        |
| -------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------ | ----- | ---------------------------------------------------------------------------------------------------------------- | ------------------------ | ------------------------------- |
| **R-01** | **DATA** | A five-state value collapses at a boundary — a rollup, serializer, export or governed view renders `unknown`, `error` or `not_applicable` as blank or as clean          | 3           | 3      | **9** | Model-registry `AUDIT` of every derived-status field, a single declared precedence order, and boundary tests at export, API and governed-view level | Architecture + `CPM-EP-EVIDENCE` dev | Before `CPM-EP-APP` starts      |
| **R-02** | **DATA** | Two policy passes clobber the rollup — the second's full-row upsert resets the first's columns to defaults, silently turning a determinate finding into `unknown`       | 3           | 3      | **9** | Policy-pass registry (ASR-3) with an ownership `AUDIT`, plus integration tests that two passes in one run both survive                              | Architecture + `CPM-EP-EVIDENCE` dev | Before `CPM-EP-APP` starts      |
| **R-03** | **DATA** | Freshness never fires — no per-collector target is configured, so nothing is ever stale and six-month-old evidence reads as current                                     | 3           | 3      | **9** | Freshness target as required configuration refused at startup (ASR-4), staleness tests driven by the injectable clock (ASR-1)                       | Architecture + Product   | Before the first collector ships |
| **R-04** | BUS      | An accepted finding resurrects — a workflow item keyed on an evidence row id returns as new unactioned work after every re-observation                                  | 2           | 3      | **6** | A declared finding key per evidence table, audited so no workflow item is keyed on an evidence row id                                               | `CPM-EP-APP` dev         | `CPM-EP-APP`                    |
| **R-05** | OPS      | A failed collection is invisible — a worker killed mid-call leaves no ledger row, so the failure looks like no data                                                     | 2           | 3      | **6** | Ledger row written `running` before the first outbound call and finalized in a `finally`; "started and never finished" is a query                   | `CPM-EP-EVIDENCE` dev    | `CPM-EP-EVIDENCE`               |
| **R-06** | DATA     | Evidence is updated, not inserted — a `bulk_update`, `queryset.update()` or raw SQL bypasses the base model's `save()` and destroys the audit trail irrecoverably       | 2           | 3      | **6** | Append-only base enforced in `save()`, plus a source-tree `AUDIT` for the bypass paths `save()` cannot catch                                        | Architecture             | `CPM-EP-EVIDENCE`               |
| **R-07** | TECH     | A sweep runs in one transaction — one package's failure rolls back thousands, making `CPM-FR-15` partial success unreachable and pinning the WAL for the sweep's duration | 2           | 3      | **6** | Declare the atomic unit as one package or one declared chunk; fault-injection test proving partial commit and a `partial` run status                | Architecture + `CPM-EP-CURRENCY` dev | `CPM-EP-CURRENCY`               |
| **R-08** | BUS      | The confidence gate is re-implemented per policy — eight passes each copy it, and `unmapped` reads differently in two views                                             | 3           | 2      | **6** | Exactly one gate implementation, audited; `unmapped` reports `unknown` for every gated status                                                       | `CPM-EP-IDENTITY` dev    | `CPM-EP-IDENTITY`               |
| **R-09** | SEC      | The analytics component gets write access — the second alias and router are unbuilt, and reusing `default` is the path of least resistance                              | 2           | 3      | **6** | Read-only enforced at the database permission level, router refusing writes and migrations on the `analytics` alias                                 | Security + Architecture  | `CPM-EP-NL`                     |
| **R-10** | SEC      | Sensitive internal usage fields reach an external model — no field-level restriction exists between the governed views and the tool layer                               | 2           | 3      | **6** | A sensitive-usage field allowlist with an `AUDIT` over the governed views                                                                           | Security + Architecture  | `CPM-EP-NL`                     |
| **R-11** | OPS      | A queue-routing regression is undetectable — eager Celery in test means a task routed to a non-existent queue still passes                                              | 3           | 2      | **6** | Route validation as configuration: every registered task's declared route resolves to `collect`, `policy` or `verify`                               | `CPM-EP-EVIDENCE` dev    | `CPM-EP-EVIDENCE`               |

#### Medium-Priority Risks (Score 3-5)

| Risk ID | Category | Description                                                                                                                        | Probability | Impact | Score | Mitigation                                                                                                 | Owner (recommended)     |
| ------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------ | ----- | ---------------------------------------------------------------------------------------------------------- | ----------------------- |
| R-14    | OPS      | A new domain app silently loses trace correlation or lands an unauthenticated route — inherited guarantees are not re-asserted per app | 2           | 2      | 4     | Per-app `AUDIT`: two-line adoption with no self-registration, and every route declaring a required role      | `CPM-EP-PLATFORM` dev   |
| R-12    | PERF     | An unpaginated response at full inventory size — memory exhaustion or timeout on the most-read view                                   | 1           | 3      | 3     | `AUDIT` that every list endpoint is paginated and no view or serializer opts out; bounded query-count test   | `CPM-EP-APP` dev        |
| R-13    | TECH     | The `analytics` alias breaks an inherited platform test — `ATOMIC_REQUESTS` is asserted true for every alias                          | 3           | 1      | 3     | Resolve ASR-5: amend the inherited assertion's meaning and decide the alias's `TEST` mirror                  | Platform owner          |

#### Low-Priority Risks (Score 1-2)

None. The lowest-scoring entry in this register is 3; every risk identified carries either a documented mitigation above or a resolution decision in the BLOCKERS tier.

#### Risk Category Legend

- **TECH**: Technical/Architecture (flaws, integration, scalability)
- **SEC**: Security (access controls, auth, data exposure)
- **PERF**: Performance (SLA violations, degradation, resource limits)
- **DATA**: Data Integrity (loss, corruption, inconsistency)
- **BUS**: Business Impact (UX harm, logic errors, revenue)
- **OPS**: Operations (deployment, config, monitoring)

#### The three nines are one risk

R-01, R-02 and R-03 are not independent findings. They are three routes to the same outcome — a package reading clean when it is unassessed, contradicted, or stale — which `CPM-SM-C1` names as the product's defining failure. They score 9 because each is individually probable (the idiomatic Django call, the export contract's own "blank means missing" rule, and an unset configuration value) and because the failure is *silent*: no exception, no alert, and a dashboard that improves as the product gets worse.

They are not a reason to fail the gate. They are the reason this test design exists, and the mitigation for all three is the same shape — a declared list of forbidden outcomes plus a mechanical audit that every one has a test proving it cannot happen.

---

### NFR Testability Requirements

**Purpose:** Capture what architecture must provide so NFR validation can be automated later. This is planning guidance, not final evidence assessment.

| NFR Category        | Threshold / Requirement                                                                                      | Current Design Support                                                       | Gap / Decision Needed                                                                       | Planned Evidence                                                              |
| ------------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Reliability         | `CPM-NFR-1`, `CPM-NFR-3`, `CPM-FR-15` — partial success on any single-source failure; no manual batching at 10,000 packages | Partial — the spine requires it; the transaction granularity that makes it reachable is undecided | Declare the atomic unit (one package or one declared chunk, never the sweep) — see R-07      | Fault-injection integration tests; chunking and bounded-query unit tests        |
| Reliability         | `CPM-FR-38` — per-collector freshness target: **UNKNOWN (Open Question 7)**                                    | Unknown — the mechanism is specified, the target value is not                 | ASR-4: make the target required configuration and refuse at startup when it is absent        | Mechanism test now; threshold test when the value exists                        |
| Performance         | `CPM-NFR-5` — p95 latency at full inventory: **UNKNOWN (Open Question 5)**                                     | Unknown — the requirement is that a budget exists; its value is set in the architecture pass | The budget value, and the inventory size at which it is measured                             | Bounded query-count assertions now; a non-gating volume job when the budget exists |
| Performance         | `CPM-NFR-4` — enforced maximum page size: value **UNKNOWN**, enforcement is not                                | Supported for enforcement, unknown for the number                              | Choose the page-size ceiling; enforcement is already required and auditable today             | Global config assertion plus a per-endpoint audit                               |
| Performance         | `CPM-AD-9` — sync export row cap: **UNKNOWN (Open Question 5)**                                                | Partial — one settings constant is specified, its value is not                 | The row-cap value; confirm every export path reads the same constant                          | Assert one settings constant is read by every export path                       |
| Security            | `CPM-NFR-8`, `CPM-FR-33` — read-only role, row limits, query timeouts                                          | Partial — the second alias and its router are unbuilt (`CPM-AD-16`)            | Build the alias, the router, and the database role before anything reads through it (R-09)    | Permission-level integration test proving the analytics role cannot write        |
| Security            | `CPM-NFR-9` — no sensitive internal usage fields reach an external model                                       | Unknown — no field-level restriction exists between the governed views and the tool layer | Define the sensitive-usage field allowlist (R-10)                                             | Field-allowlist test on the governed views                                      |
| Security            | `CPM-NFR-11`, `CPM-FR-31` — every refusal logged with acting user identity                                     | Supported — structured logging is already wired                                | None                                                                                          | Assertion on the structured log record, not on stdout                           |
| Security            | `CPM-NFR-10` — no credential or endpoint defaulted to a production value                                       | Supported — inherited stage-one startup refusals already cover this            | None                                                                                          | Existing refusal coverage audit                                                 |
| Maintainability     | `pixi run ci` — 90% coverage floor; currently 97.04%                                                           | Supported — the gate is real and identical locally and in CI                   | None                                                                                          | Existing gate and `test-cov` report                                             |
| Observability       | `CPM-NFR-12`, `CPM-NFR-13`, `CPM-FR-39` — `trace_id` on every run-ledger row                                   | Supported — `request_id`, `user_id`, `trace_id` and `span_id` already flow through requests, tasks, queries and cache calls | Persist the correlation ids on run-ledger rows (ASR-7, already designed in `CPM-EVIDENCE-S03`) | Assert the persisted id equals the active span's                                 |
| Compliance / audit  | `CPM-FR-32`, `CPM-FR-36` — append-only evidence; every privileged write audited atomically                     | Partial — the base model is specified; bypass paths are not yet closed         | Close the `queryset.update()` / `bulk_update()` / raw-SQL bypass (R-06)                        | Audit-trail integration tests; a mutation-path audit                             |

**Unknown thresholds:** Five threshold values are unresolved. None is invented here; each is an open PRD question with an owner, and the pattern throughout is the same — test that the mechanism exists, is wired, and is honoured everywhere, then add the threshold assertion once the number is chosen.

1. Per-collector freshness target — `CPM-FR-38` — **Open Question 7** ("What are the per-collector freshness targets for `CPM-FR-38`?" — needed before the first collector ships, not before the epic starts)
2. p95 latency budget, and the inventory size at which it is measured — `CPM-NFR-5` — **Open Question 5**
3. Sync export row cap — `CPM-AD-9` — **Open Question 5**
4. Priority rule set and score function — `CPM-FR-20` — **Open Question 8** (blocks `CPM-EP-PRIORITY`; does not block the collectors or the application)
5. Feedstock inactivity threshold, and what counts as recipe activity — `CPM-FR-40` — **Open Question 10** (blocks `CPM-EP-CURRENCY`)

Separately, `CPM-NFR-4`'s maximum page size has no chosen value either, although its *enforcement* is unambiguous and is auditable today; it is carried as a design decision rather than a PRD open question.

**Assessment boundary:** Final PASS/CONCERNS/FAIL status belongs in `nfr-assess` after implementation evidence exists.

---

### Testability Concerns and Architectural Gaps

**🚨 ACTIONABLE CONCERNS - Architecture Team Must Address**

Seven concerns, ordered by how much they cost if found late. No implementation exists yet, so every one of these is cheap now and expensive after `CPM-EP-EVIDENCE` ships.

#### 1. Blockers to Fast Feedback (WHAT WE NEED FROM ARCHITECTURE)

| Concern                                                                       | Impact                                                                                                                                       | What Architecture Must Provide                                                                                                                                             | Owner (recommended)                  | Timeline                              |
| ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ------------------------------------- |
| **TC-1 — Time is a hidden input to almost everything, and nothing injects it** | Tests that call the real clock are either untestable (you cannot make evidence six months old) or flaky (they pass until they run at midnight) | A single injectable clock in `core`, used by every collector, policy pass and freshness computation; no module calls `timezone.now()` directly, enforced by a scanning audit  | Architecture + `CPM-EP-EVIDENCE` dev | Pre-implementation                    |
| **TC-2 — The primary inputs are external and unavailable in the unit tier**    | Eight collectors read external sources and `tests/unit/` forbids network, so without a seam the majority of the product's behaviour lands in the slow half of the suite | A transport seam in the collector base (`CPM-EVIDENCE-S05`), so each collector is a pure translation from a recorded payload to evidence rows                                  | Architecture + `CPM-EP-EVIDENCE` dev | Pre-implementation                    |
| **TC-3 — The single-writer rule is a negative property, and negative properties rot** | A test asserting today's two passes do not write the rollup passes today and says nothing about the ninth pass added next quarter        | Passes register with the policy run rather than being called directly, so the set is enumerable, and each registered pass declares the derived table it owns                   | Architecture + `CPM-EP-EVIDENCE` dev | Pre-implementation                    |
| **TC-7 — Freshness has no configured target, so nothing is ever stale**        | An unset target does not mean "fresh forever" by design — it means undefined, and undefined reads as clean                                     | Make the freshness target required configuration and refuse at startup when a registered collector has none, following the inherited `CG-3` convention that a refusal raises rather than warns | Architecture + Product               | Before the first collector ships       |
| **TC-6 — The second database alias collides with an inherited platform assertion** | `CPM-AD-16` adds an `analytics` alias with `ATOMIC_REQUESTS = False` while `tests/unit/test_database_selection.py` asserts every alias has it true | A decision on whether that inherited assertion is amended to mean "every alias Django may write through", and whether the analytics alias gets a `TEST` mirror              | Platform owner + Architecture        | Before `CPM-EP-NL`                    |
| **TC-4 — Full-inventory scale cannot be exercised the obvious way**            | `CPM-NFR-1` at 10,000 packages and `CPM-NFR-5`'s p95 budget do not belong in a suite that must stay fast                                       | Agreement that the gating suite asserts the *properties* that make scale work — bounded query counts, chunking, pagination, streaming export — and that volume runs in a separate non-gating job | Architecture + Dev                   | Implementation phase                  |
| **TC-5 — Celery runs eager in test, so queue routing is never exercised**      | `CELERY_TASK_ALWAYS_EAGER = True` in both `config.settings.local` and `config.settings.test`, so `CPM-AD-20`'s three queues are invisible to every behavioural test | Agreement that routing is validated as configuration — every task's declared route resolves to one of the three queues — rather than observed at runtime                    | Architecture + Dev                   | Implementation phase                  |

#### 2. Architectural Improvements Needed (WHAT SHOULD BE CHANGED)

1. **ASR-1 — An injectable clock, used everywhere, enforced by an audit**
   - **Current problem**: Freshness targets, observation windows, policy cut-offs, staleness, KEV catalog dates and `observed_at` all depend on "now", and nothing in the spine or the stories says where "now" comes from.
   - **Required change**: One clock abstraction in `core`, injected into every collector, policy pass and freshness computation; an audit that scans for direct `timezone.now()` calls, in the same shape as the existing import-root audit.
   - **Impact if not fixed**: Freshness, windows and cut-offs cannot be tested reliably at all — the tests are either impossible to write or flaky by construction, and R-03 (score 9) has no credible mitigation.
   - **Owner**: Architecture + `CPM-EP-EVIDENCE` dev
   - **Timeline**: Pre-implementation

2. **ASR-2 — A transport seam in the collector base**
   - **Current problem**: The eight collectors' inputs are all external, and the unit tier forbids network access.
   - **Required change**: Put the seam in the collector base (`CPM-EVIDENCE-S05`) so a collector becomes a pure translation from a recorded payload to evidence rows; the integration tier then proves only the transport itself.
   - **Impact if not fixed**: Parse, `not_found`, `error` and `not_applicable` handling — the majority of this product's behaviour — becomes integration-only, and the fast feedback loop stops covering the logic that matters.
   - **Owner**: Architecture + `CPM-EP-EVIDENCE` dev
   - **Timeline**: Pre-implementation

3. **ASR-3 — A policy-pass registry that makes the single-writer rule auditable**
   - **Current problem**: `CPM-AD-21` says no pass writes the rollup, but passes are invoked directly, so the set of passes is not enumerable and the rule can only be checked by reading code.
   - **Required change**: Passes register with the policy run; every registered pass declares the derived table it owns; an audit fails if any pass declares the rollup. This is the `forbidden_state` audit pattern pointed at a new invariant.
   - **Impact if not fixed**: `CPM-AD-21` is unenforceable over time, and R-02 (score 9) recurs the first time someone adds a pass.
   - **Owner**: Architecture + `CPM-EP-EVIDENCE` dev
   - **Timeline**: Pre-implementation

4. **ASR-4 — Freshness targets as required configuration, refused at startup when absent**
   - **Current problem**: The freshness mechanism (`CPM-FR-38`) reads a per-collector target that Open Question 7 leaves unset, and an unset target silently behaves as "fresh forever".
   - **Required change**: Require the target on every registered collector and raise `ImproperlyConfigured` at startup when one is missing, per the inherited `CG-3` convention.
   - **Impact if not fixed**: The largest false-clean path stays open — six-month-old evidence reads as current, which is exactly the `CPM-SM-C1` failure.
   - **Owner**: Architecture + Product (the values themselves are Open Question 7)
   - **Timeline**: Before the first collector ships

5. **ASR-5 — `analytics` alias test configuration and the inherited assertion's meaning**
   - **Current problem**: `CPM-AD-16`'s `analytics` alias sets `ATOMIC_REQUESTS = False`, while the inherited `tests/unit/test_database_selection.py` deliberately iterates all aliases and asserts every one has `ATOMIC_REQUESTS is True`, because the platform "forecasts a second database".
   - **Required change**: Decide whether the inherited assertion is amended to mean "every alias Django may write through", and whether the analytics alias gets a `TEST` mirror. This is a cross-boundary change to inherited code, not a product-side edit.
   - **Impact if not fixed**: `CPM-EP-NL` cannot land without either breaking an inherited platform test or silently weakening it.
   - **Owner**: Platform owner + Architecture
   - **Timeline**: Before `CPM-EP-NL`

Two further architecturally significant requirements are **FYI only** and need no decision — they are already designed into stories:

- **ASR-6 — Replay determinism as a property test.** `CPM-FR-22`'s "same version and cut-off reproduce identical results" is already covered by `CPM-PRIORITY-S03`.
- **ASR-7 — Correlation ids persisted on run-ledger rows.** Already covered by `CPM-EVIDENCE-S03`.

---

### Testability Assessment Summary

**📊 CURRENT STATE - FYI**

#### What Works Well

- ✅ **Policy is pure-function shaped** — evidence in, derived state out, no I/O, no clock beyond the injected cut-off. The most valuable logic in the product is the most unit-testable.
- ✅ **Append-only evidence makes fixtures trivial** — no update ordering, no mutation sequencing; a test builds history by inserting rows.
- ✅ **Replay is a testability feature** — `CPM-FR-22`'s reproducibility requirement is a property test, and it doubles as a regression harness for every policy change.
- ✅ **Observability is already wired** — `request_id`, `user_id`, `trace_id` and `span_id` flow through requests, tasks, queries and cache calls, so a failing assertion is traceable to the run that produced it without new instrumentation.
- ✅ **The five states are an enum with a single precedence order**, so "did this boundary collapse them" is mechanically checkable rather than a matter of reading code.
- ✅ **The `forbidden_state` audit pattern already exists and works** — a declared list, a marker, and a reconciliation test (`tests/unit/startup/forbidden_states.py` plus `tests/unit/startup/test_refusal_coverage_audit.py`). It generalizes directly to this product's invariants, and is the basis of the entire `AUDIT` level.
- ✅ **The gate is real** — 1,545 tests at 97.04% coverage against a 90% floor, with the same `pixi run ci` command locally and in CI.

#### Accepted Trade-offs (No Action Required)

For this product's first release, the following trade-offs are acceptable:

- **No E2E level and no browser framework** — no UX contract exists and all three `CPM-UJ-*` journeys are reachable through `API` plus `INT`. Adding Playwright would be adding a dependency to satisfy a document rather than a risk.
- **No contract-testing (Pact) layer** — there is no consumer/provider microservice split; the product's one external contract surface is its own OpenAPI schema, which drf-spectacular generates from the implementation.
- **Scale is asserted by property, not by volume, inside the gate** — bounded query counts and chunking stand in for the 10,000-package run, which lives in a nightly non-gating job (TC-4).
- **Queue routing is validated as configuration, not at runtime** — eager Celery in test makes runtime observation impossible without changing how the test settings work (TC-5).

These are deliberate boundaries for the current phase, not debt to pay down: each is revisited only if the product grows a surface that invalidates its rationale (a browser UI, a second service consuming the API, or a latency budget that a property assertion cannot stand in for).

---

### Risk Mitigation Plans (High-Priority Risks ≥6)

**Purpose**: Detailed mitigation strategies for all 11 high-priority risks (score ≥6). R-01, R-02 and R-03 MUST be addressed before `CPM-EP-APP` starts — they are unfixable in place once data exists. The remainder must have a passing test before their epic is called done.

#### R-01: A five-state value collapses at a boundary (Score: 9) - CRITICAL

**Mitigation Strategy:**

1. Enumerate every derived-status field from the model registry and audit that each is a `CharField` with choices carrying all four sentinels — from the registry, never from a hand-written list.
2. Define the precedence order exactly once, in `core`, and prove by property test over the full cross-product that aggregating any pair of states matches the declared order.
3. Assert at each outbound boundary that the states survive: export renders `unknown`, `not_found`, `not_applicable` and `error` as literal values with blank reserved for genuinely absent values; the API serializes each of the five verbatim with none mapping to `null`, `""`, `true` or `false`; and every derived-status column in the rollup is present in the governed views, checked as a set difference.

**Owner:** Architecture + `CPM-EP-EVIDENCE` dev
**Timeline:** `AUDIT` test passing before `CPM-EP-APP` starts
**Status:** Planned
**Verification:** Six scenarios, all P0 — one AUDIT over the model registry, two UNIT on precedence, one INT on export, one API on serialization, one AUDIT on the rollup-to-governed-view column set. Residual risk 3.

---

#### R-02: Two policy passes clobber the rollup (Score: 9) - CRITICAL

**Mitigation Strategy:**

1. Implement the policy-pass registry (ASR-3) and audit that every registered pass declares the derived table it owns and that none declares the rollup.
2. Prove in integration that two passes writing different domains in one run both survive — neither's columns are reset to defaults by the other — and that exactly one rollup row exists per inventory package after a run, including `unmapped` packages whose gated statuses read `unknown`.
3. Carry the run id, the run's cut-off and a per-domain version map on the rollup row rather than one scalar version, and select the cut-off only from the `finished_at` of a *completed* collection run — never a run still `running`.

**Owner:** Architecture + `CPM-EP-EVIDENCE` dev
**Timeline:** `AUDIT` test passing before `CPM-EP-APP` starts
**Status:** Planned
**Verification:** Six scenarios — one AUDIT on pass ownership, four INT on rollup survival, cardinality and versioning, one UNIT on cut-off selection, plus a P1 INT proving a pass reading an earlier pass's output gets the same run's values. Residual risk 2.

---

#### R-03: Freshness never fires (Score: 9) - CRITICAL

**Mitigation Strategy:**

1. Make the per-collector freshness target required configuration and refuse at startup with `ImproperlyConfigured` when a registered collector has none (ASR-4, inherited `CG-3`).
2. Prove that evidence older than its target reports `stale`, and that `stale` never equals clean at any comparison.
3. Use the injectable clock (ASR-1) to advance time past the target and assert previously-fresh evidence flips to `stale`; extend the same rule to remediation readiness, which on stale supporting evidence must report stale rather than "a fix is available".

**Owner:** Architecture + Product (the target values are Open Question 7)
**Timeline:** Startup refusal in place before the first collector ships; `AUDIT` test passing before `CPM-EP-APP` starts
**Status:** Planned — blocked on ASR-1 and ASR-4 decisions
**Verification:** Four scenarios — one AUDIT on the startup refusal, two UNIT on staleness including the clock-advance case, one P1 UNIT on remediation readiness. Residual risk 2.

---

#### R-04: An accepted finding resurrects (Score: 6) - HIGH

**Mitigation Strategy:**

1. Key workflow items on a declared finding key rather than on an evidence row id, and audit that every evidence table which can back a workflow item declares one.
2. Prove in integration that a finding accepted and then re-observed as a new evidence row does not reappear as new unactioned work.
3. Scope acceptance correctly: accepting one advisory on a package does not accept the package's other advisories, and a concurrent transition from a stale prior state is refused rather than resolved last-writer-wins.

**Owner:** `CPM-EP-APP` dev
**Timeline:** `CPM-EP-APP`
**Status:** Planned
**Verification:** Four scenarios — one P0 INT on non-resurrection, one P1 AUDIT on finding keys, two P1 INT on acceptance scope and concurrent transitions. Residual risk 2.

---

#### R-05: A failed collection is invisible (Score: 6) - HIGH

**Mitigation Strategy:**

1. Write the ledger row with status `running` *before* the first outbound call, not after it returns.
2. Finalize the row in a `finally` so a collector raising mid-run still records an outcome; the row is never absent.
3. Make "started and never finished" answerable — rows left `running` must be queryable — and persist the correlation ids so the `trace_id` on the row equals the active span's (ASR-7).

**Owner:** `CPM-EP-EVIDENCE` dev
**Timeline:** `CPM-EP-EVIDENCE`
**Status:** Planned
**Verification:** Four scenarios — two P0 INT on row-before-call and finalize-on-raise, one P1 INT on queryability, one P1 UNIT on trace id equality. Residual risk 2.

---

#### R-06: Evidence is updated, not inserted (Score: 6) - HIGH

**Mitigation Strategy:**

1. Enforce append-only in the base model: `save()` on an instance that already has a primary key raises.
2. Audit from the model registry that every evidence model inherits the append-only base.
3. Close the paths `save()` cannot see with a source-tree audit: no module calls `queryset.update()`, `bulk_update()` or raw SQL against an evidence table, and no evidence table carries a unique constraint that would suppress an insert. Prove positively that re-observing an unchanged fact inserts a second row with a later `observed_at`.

**Owner:** Architecture
**Timeline:** `CPM-EP-EVIDENCE`
**Status:** Planned
**Verification:** Five scenarios — one P0 UNIT on `save()`, three P0 AUDIT/INT on inheritance, bypass paths and re-observation, one P1 AUDIT on unique constraints. Residual risk 3 — the highest residual in the register, because a source-tree audit is a strong but not total guarantee against a new bypass idiom.

---

#### R-07: A sweep runs in one transaction (Score: 6) - HIGH

**Mitigation Strategy:**

1. Declare the atomic unit as one package or one declared chunk, never the sweep, and assert it in a unit test.
2. Prove by fault injection that a failure on package N leaves packages 1..N-1 committed and the run reports `partial`, satisfying `CPM-FR-15`.
3. Keep genuinely atomic pairs atomic: an override and its audit row commit or roll back together, and no privileged write defers its audit row to `transaction.on_commit` or a follow-up task.

**Owner:** Architecture + `CPM-EP-CURRENCY` dev
**Timeline:** `CPM-EP-CURRENCY`
**Status:** Planned
**Verification:** Four scenarios — two P0 INT on partial success and override/audit atomicity, one P1 UNIT on the atomic unit, one P1 AUDIT on deferred audit rows. Residual risk 2.

---

#### R-08: The confidence gate is re-implemented per policy (Score: 6) - HIGH

**Mitigation Strategy:**

1. Implement the confidence gate exactly once and audit that no policy module defines its own.
2. Fix the semantics of `unmapped` in one place: an `unmapped` package reports `unknown` for every gated status and is never current, clean, or "no feedstock" — including the feedstock policy, which reports `unknown` rather than absent.
3. Keep `inventory-derived` as a confidence label that does not degrade a determinate value.

**Owner:** `CPM-EP-IDENTITY` dev
**Timeline:** `CPM-EP-IDENTITY`
**Status:** Planned
**Verification:** Four scenarios — one P0 AUDIT on single implementation, two P0 UNIT on `unmapped` and `inventory-derived` semantics, one P1 UNIT on the feedstock policy. Residual risk 2.

---

#### R-09: The analytics component gets write access (Score: 6) - HIGH

**Mitigation Strategy:**

1. Enforce read-only at the database permission level, not by convention: the analytics role cannot insert, update or delete on any table.
2. Make the router refuse writes and migrations on the `analytics` alias.
3. Enforce the query timeout and row limit on the analytics connection (`CPM-FR-33`).

**Owner:** Security + Architecture
**Timeline:** `CPM-EP-NL` — which is itself blocked behind the fitness spike
**Status:** Planned — depends on ASR-5 and on `CPM-AD-16` landing
**Verification:** Three scenarios — two P0 INT on database-level permissions and router refusal, one P1 INT on timeout and row limit. Residual risk 2.

---

#### R-10: Sensitive internal usage fields reach an external model (Score: 6) - HIGH

**Mitigation Strategy:**

1. Define the sensitive-usage field allowlist explicitly, as declared data rather than as a code convention.
2. Audit that the governed views expose no field on that allowlist.
3. Keep the allowlist reconciled with the governed views' column set, so a field added to one and not the other fails the audit rather than leaking.

**Owner:** Security + Architecture
**Timeline:** `CPM-EP-NL`
**Status:** Planned
**Verification:** One P0 AUDIT scenario over the governed views, reinforced by the R-01 column-set audit that compares rollup columns to governed-view columns. Residual risk 2.

---

#### R-11: A queue-routing regression is undetectable (Score: 6) - HIGH

**Mitigation Strategy:**

1. Validate routing as configuration, since eager Celery hides it at runtime (TC-5): every registered task's declared route must resolve to `collect`, `policy` or `verify`.
2. Assert the specific mapping that matters most — verification tasks route to `verify` and never to `collect`.
3. Keep cadence as scheduler data: no task carries a hard-coded schedule decorator.

**Owner:** `CPM-EP-EVIDENCE` dev
**Timeline:** `CPM-EP-EVIDENCE`
**Status:** Planned
**Verification:** Three scenarios — two P1 AUDIT on route resolution and verification routing, one P2 UNIT on cadence. Residual risk 2.

---

### Assumptions and Dependencies

#### Assumptions

1. **No implementation of the product's domain apps exists yet.** `src/django_apps/` does not exist; the codebase today is the inherited platform plus its 1,545 tests. Every recommendation here is therefore a design-time decision, not a refactor, and its cost is at its lowest right now.
2. **The inherited platform's conventions hold and are extended rather than replaced.** Specifically: the `forbidden_state` declared-list-plus-reconciliation-test pattern, the directory-scoped `integration` marker hook, the filename-based exclusion of `tests/spikes/`, the `CG-3` "a refusal raises rather than warns" convention, and stage-one startup refusals for configuration.
3. **`pixi run ci` remains the single gate**, identical locally and in CI, and pixi remains the only Python runner in the project. No example, task, or command in this design introduces another runner.
4. **The 90% coverage floor stays the contractual minimum**, with the current 97.04% treated as headroom rather than as the new floor.
5. **The `AUDIT` level is built once and reused.** Roughly a third of the P0 estimate is the reusable declared-list plus reconciliation-test machinery, built in `CPM-EP-EVIDENCE`; every later audit is then a few lines.
6. **Scoring follows `risk-governance.md`** — probability × impact on 1–3 scales — and residual scores assume both the mitigation and the test that proves it are in place.

#### Dependencies

1. **ASR-1 (injectable clock) and ASR-2 (collector transport seam)** - Required before `CPM-EP-EVIDENCE` implementation begins. Freshness, window and cut-off testing depends on the first; the unit-tier testability of eight collectors depends on the second.
2. **ASR-3 (policy-pass registry)** - Required before the second policy pass exists, and its audit must pass before `CPM-EP-APP` starts.
3. **ASR-4 (freshness targets as required configuration)** - Mechanism required before the first collector ships; the target *values* depend on Open Question 7.
4. **ASR-5 (`analytics` alias and the inherited `ATOMIC_REQUESTS` assertion)** - Required before `CPM-EP-NL`. This is a change to inherited platform code and needs the platform owner, not only the product team.
5. **`CPM-AD-16` (second database alias, router, governed views)** - Required before R-09, R-10 and the `NL.*` scenarios can be tested at all. Architecturally settled and independent of the spike's outcome, but unbuilt.
6. **The `CPM-EP-NL` fitness spike** - `CPM-EP-NL` is BLOCKED: only the spike story is authored, and the remaining stories are deliberately not written until the spike establishes LangChain's conda-forge availability and its transitive resolution against Python 3.14. Every `NL.*` scenario in the coverage plan is therefore contingent.
7. **Five unresolved PRD open questions** - Open Question 1 (which advisory and KEV sources are available and licensed; blocks `CPM-EP-SECURITY` and gates the P3 exploratory work), Open Question 5 (p95 latency budget and its measurement size, plus the sync export row cap), Open Question 7 (per-collector freshness targets), Open Question 8 (priority rule set and score function; blocks `CPM-EP-PRIORITY`), and Open Question 10 (feedstock inactivity threshold; blocks `CPM-EP-CURRENCY`).

#### Risks to Plan

- **Risk**: The blocker decisions (ASR-1 through ASR-4) are deferred and `CPM-EP-EVIDENCE` ships without them.
  - **Impact**: The three score-9 risks lose their mitigations, collector logic becomes integration-only, and retrofitting a clock and a transport seam across eight collectors costs far more than designing them in.
  - **Contingency**: Treat the four `AUDIT` tests protecting R-01, R-02 and R-03 as a hard entry condition on `CPM-EP-APP`; if the decisions slip, `CPM-EP-APP` does not start.

- **Risk**: The five UNKNOWN thresholds stay unresolved through implementation.
  - **Impact**: Mechanism tests pass while the values they would assert never arrive, leaving `CPM-NFR-5`, `CPM-FR-38`, `CPM-AD-9`, `CPM-FR-20` and `CPM-FR-40` provable only in shape and not in substance.
  - **Contingency**: The design already separates mechanism from threshold. Each mechanism test ships now; each threshold assertion is queued behind its open question and does not block the gate. No value is invented in the meantime.

- **Risk**: `CPM-EP-NL` stays blocked behind its fitness spike for an extended period.
  - **Impact**: R-09 and R-10, both scoring 6, stay unmitigated and untested because the alias, router and governed views they concern are unbuilt.
  - **Contingency**: `CPM-AD-16` is architecturally settled and independent of the spike's verdict, so the alias, router and permission tests can be built ahead of the consumer; only the tool-layer field allowlist genuinely waits on the spike.

- **Risk**: A regression in the inherited platform's assertions is worked around rather than decided (ASR-5 / R-13).
  - **Impact**: Either `CPM-EP-NL` breaks an inherited test, or the assertion is weakened silently and the platform loses a guarantee it deliberately wrote.
  - **Contingency**: Force the decision as a blocker before `CPM-EP-NL`, with the platform owner in the room, and record the amended meaning in the assertion itself.

- **Risk**: The suite's speed advantage erodes as `INT` and `API` scenarios accumulate, and the team starts deferring tests out of the PR gate.
  - **Impact**: The tests that protect the score-9 risks stop running on every change, which is the only place they are useful.
  - **Contingency**: The `AUDIT` tests — which carry most of the score-9 protection — read declarations rather than data and are the cheapest in the suite, so there is no cost argument for deferring them. The PR budget is under 15 minutes against a current runtime of roughly 30 seconds for 1,545 tests; volume and live-transport work is already outside the gate.

---

**End of Architecture Document**

**Next Steps for Architecture Team:**

1. Review Quick Guide (🚨/⚠️/📋) and prioritize blockers — the five ASR decisions are the critical path
2. Assign owners and timelines for the 11 high-priority risks (≥6); the recommended owners above are suggestions, not assignments
3. Validate assumptions and dependencies, in particular the `CPM-AD-16` sequencing and the `CPM-EP-NL` spike contingency
4. Provide feedback to QA on the seven testability gaps TC-1 through TC-7

**Next Steps for QA Team:**

1. Wait for pre-implementation blockers ASR-1 through ASR-4 to be resolved
2. Refer to the companion QA doc (`test-design-qa.md`) for the full 53-scenario coverage matrix and every test ID
3. Begin test infrastructure setup — the reusable `AUDIT` harness (declared lists plus reconciliation tests), factories, and fixtures — which is roughly a third of the P0 effort and unblocks every later audit
