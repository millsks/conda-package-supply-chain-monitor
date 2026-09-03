---
runScope: 'system-level'
runKey: 'system'
workflowStatus: 'completed'
totalSteps: 5
stepsCompleted: ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
nextStep: ''
lastSaved: '2026-09-03'
---

# Step 1 — Mode and prerequisites

**Mode: System-Level.** Chosen on user intent (explicit request for a system-level design)
and confirmed by file-based detection: no `sprint-status.yaml` exists, and the inputs are
PRD plus architecture decision records rather than a single epic.

**Run identity:** `run_scope = system-level`, `run_key = system`.

## Prerequisites — all present

| Required | Artifact | State |
|---|---|---|
| PRD with functional and non-functional requirements | `prds/.../prd.md` | 41 `CPM-FR-*`, 13 `CPM-NFR-*`, 6 `CPM-SM-*` incl. 3 counter-metrics, 3 `CPM-UJ-*` |
| Architecture decision records | `architecture/.../ARCHITECTURE-SPINE.md` | 24 `CPM-AD-*`, each with Binds / Prevents / Rule |
| Architecture or tech-spec document | `architecture/.../solution-design.md` | C4 views, run and request walkthroughs, predicted failure modes |
| Supporting | `epics.md` | 9 epics, 42 stories, 131 acceptance criteria |
| Supporting | `briefs/.../brief.md`, `addendum.md` | roles, scope boundary, rationale |

No checkpoint existed at this path. Fresh run.

## Note carried forward

The spine's **Prevents** clauses are a pre-written catalogue of this system's failure
modes — 24 of them, each already tied to the requirement it protects. They are the primary
risk input for step 3, not a secondary source.


---

# Step 2 — Context and knowledge base

## Detected stack: `backend`

`pyproject.toml` present; no `package.json`, no `playwright.config.*`, no `cypress.config.*`,
no mobile manifests. This is a Python / Django / pytest project.

**Two configured integrations are deliberately not loaded, and this is a judgment call
worth recording rather than a silent skip:**

| Flag | Value | Decision |
|---|---|---|
| `tea_use_playwright_utils` | `true` | **Not loaded.** The Playwright utils fragments teach TypeScript patterns — `apiRequest`, `interceptNetworkCall`, merged fixtures. Every code example this workflow emits is a pattern a developer copies, and none of these is copyable in a pytest project. Loading them would put unusable examples into the design. |
| `tea_use_pactjs_utils` / `tea_pact_mcp` | `true` / `mcp` | **Not loaded.** Contract testing is not relevant here: no `pact/`, no `tests/contract/`, no `package.json`, no `PACT_BROKER_*`, and no microservice consumer/provider split. The product's one external contract surface is its own OpenAPI schema, which drf-spectacular generates from the implementation. `pact_mcp_reachable`: not probed, not needed. |

The flags default to `true` and, per the mandate, never mean "add this to the project".

## Knowledge fragments loaded

| Fragment | Why |
|---|---|
| `risk-governance.md` | The scoring model this design uses: probability × impact on 1–3 scales, total 1–9; ≥6 demands documented mitigation; 9 fails the gate. Categories TECH, SEC, PERF, DATA, BUS, OPS |
| `nfr-criteria.md` | NFR assessment checklist and gate decision matrix |
| `test-levels-framework.md` | Unit / integration / E2E selection rules, the duplicate-coverage guard, and test ID format |
| `adr-quality-readiness-checklist.md` | Eight-dimension architecture readiness review, applied against the 24 spine invariants |
| `test-quality.md` | Test quality standards for the generated plan |

Config: `risk_threshold: p1`, `test_design_output: _bmad-output/test-artifacts/test-design`.

## Project artifacts loaded

- **PRD** — 41 `CPM-FR-*`, 13 `CPM-NFR-*`, 6 `CPM-SM-*` (3 of them counter-metrics), 3 `CPM-UJ-*`, Appendix A data model
- **Architecture spine** — 24 `CPM-AD-*` with Binds / Prevents / Rule; consistency conventions; pinned stack
- **Solution design** — C4 views, collection-run and request walkthroughs, "the two things people will get wrong"
- **Epics** — 9 epics, 42 stories, 131 acceptance criteria
- **Brief + addendum** — roles, scope boundary, decision rationale

## Existing test infrastructure — extend, do not replace

1,545 tests at 97.04% coverage against a 90% floor.

- `tests/unit/` — no database, network or filesystem
- `tests/integration/` — the `integration` marker applied automatically by a directory-scoped
  `pytest_collection_modifyitems` hook, not by decorating each module
- `tests/spikes/` — excluded from the gate by filename (`spike_*.py` does not match
  `python_files`), never by `-m`, and a test enforces that
- Registered markers: `integration`, `spike`, `forbidden_state`
- Gate: `pixi run ci` = precommit → build → typecheck → lint → test-cov

**The pattern this design will extend.** `tests/unit/startup/forbidden_states.py` declares
the platform's refusal conditions; `@pytest.mark.forbidden_state("<id>")` tags the test that
proves each one; `tests/unit/startup/test_refusal_coverage_audit.py` mechanically reconciles
the two and fails when a declared state has no test. That is precisely the shape this
product's "unknown is never clean" invariants need, and it already exists and works.

## Integration points extracted

Outbound, all read-only: source repositories, PyPI, conda-forge feedstocks and channels,
advisory sources, the KEV catalog. Inbound: the organization's OIDC provider. Internal:
PostgreSQL 17 (two aliases once `CPM-AD-16` lands), Redis, and an OTLP collector when an
endpoint is configured.

## NFR thresholds — deliberately absent

Four values the PRD leaves open are exactly the thresholds an NFR test would assert. This
design specifies the *mechanism and its test*, and records the missing value as a question
rather than inventing one: the p95 latency budget and export row cap (OQ 5), per-collector
freshness targets and observation windows (OQ 7), the priority rule set and score function
(OQ 8), and the feedstock inactivity threshold (OQ 10).


---

# Step 3 — Testability review and risk assessment

## 🚨 Testability concerns

Seven, ordered by how much they cost if found late. No implementation exists yet, so every
one of these is cheap now and expensive after `CPM-EP-EVIDENCE` ships.

### TC-1 — Time is a hidden input to almost everything, and nothing injects it

Freshness targets, observation windows, policy cut-offs, staleness, KEV catalog dates and
`observed_at` all depend on "now". Nothing in the spine or the stories says where "now"
comes from. Tests that call the real clock are either untestable (you cannot make evidence
six months old) or flaky (they pass until they run at midnight).

**Recommendation:** a single injectable clock in `core`, used by every collector, policy
pass and freshness computation. No module calls `timezone.now()` directly, and a test
enforces that by scanning for it — the same shape as the existing import-root audit.

### TC-2 — The primary inputs are external and unavailable in the unit tier

Eight collectors read from source repositories, PyPI, conda-forge, advisory sources and the
KEV catalog. `tests/unit/` forbids network. Without a seam, collector logic is testable only
in the integration tier, which pushes the majority of this product's behaviour into the slow
half of the suite.

**Recommendation:** put the transport seam in the collector base (`CPM-EVIDENCE-S05`), so
each collector is a pure translation from a recorded payload to evidence rows. That makes
parse, `not_found`, `error` and `not_applicable` handling unit-testable, and leaves the
integration tier to prove the transport itself.

### TC-3 — The single-writer rule is a negative property, and negative properties rot

`CPM-AD-21` says *no pass writes the rollup*. A test asserting the two current passes do not
write it passes today and says nothing about the ninth pass someone adds next quarter.

**Recommendation:** make passes register with the policy run rather than being called
directly, so the set is enumerable, and audit the registry — every registered pass declares
the derived table it owns, and a test fails if any pass declares the rollup. This is the
`forbidden_state` audit pattern applied to a different invariant.

### TC-4 — Full-inventory scale cannot be exercised the obvious way

`CPM-NFR-1` is 10,000 packages without manual batching, and `CPM-NFR-5` is a p95 latency
budget at full size. Neither belongs in a suite that must stay fast.

**Recommendation:** assert the *properties* that make scale work rather than the scale
itself — bounded query counts (no N+1 on the health view), chunking behaviour, pagination
enforcement, and streaming on export. A separate, non-gating performance job carries the
actual volume run.

### TC-5 — Celery runs eager in test, so queue routing is never exercised

`CELERY_TASK_ALWAYS_EAGER = True` in both `config.settings.local` and `config.settings.test`.
`CPM-AD-20`'s three queues are therefore invisible to every behavioural test — a task routed
to a queue that does not exist would still pass.

**Recommendation:** test routing as *configuration* — assert every task's declared route
resolves to one of the three queues — rather than trying to observe it at runtime.

### TC-6 — The second database alias collides with an inherited platform assertion

`CPM-AD-16` adds an `analytics` alias with `ATOMIC_REQUESTS = False`. The inherited
`tests/unit/test_database_selection.py` asserts *every* alias has `ATOMIC_REQUESTS is True`,
deliberately iterating all aliases because the platform "forecasts a second database".

**Recommendation:** decide now whether that inherited assertion is amended to mean "every
alias Django may write through", and whether the analytics alias gets a `TEST` mirror. This
is a cross-boundary change to inherited code and needs a decision before `CPM-EP-NL`.

### TC-7 — Freshness has no configured target, so nothing is ever stale

The freshness mechanism (`CPM-FR-38`) reads a per-collector target that PRD Open Question 7
leaves unset. An unset target does not mean "fresh forever" by design — it means undefined.

**Recommendation:** make the target required configuration and refuse at startup when a
registered collector has none, following the inherited `CG-3` convention that a refusal
raises rather than warns. That converts a silent false-clean into a loud boot failure.

## ✅ Testability assessment summary — what is already strong

- **Policy is pure-function shaped.** Evidence in, derived state out, no I/O, no clock beyond
  the injected cut-off. The most valuable logic in the product is the most unit-testable.
- **Append-only evidence makes fixtures trivial.** No update ordering, no mutation sequencing —
  a test builds history by inserting rows.
- **Replay is a testability feature.** `CPM-FR-22`'s "same version and cut-off reproduce
  identical results" is a property test, and it doubles as a regression harness for every
  policy change.
- **Observability is already wired.** `request_id`, `user_id`, `trace_id` and `span_id` flow
  through requests, tasks, queries and cache calls, so a failing assertion is traceable to
  the run that produced it without new instrumentation.
- **The five states are an enum with a single precedence order**, so "did this boundary
  collapse them" is mechanically checkable rather than a matter of reading code.
- **The `forbidden_state` audit pattern already exists and works** — a declared list, a
  marker, and a reconciliation test. It generalizes directly to this product's invariants.
- **The gate is real.** 1,545 tests, 97.04% against a 90% floor, and the same command locally
  and in CI.

## Architecturally significant requirements

| ASR | Requirement | Disposition |
|---|---|---|
| ASR-1 | An injectable clock, used everywhere, enforced by an audit | **ACTIONABLE** — blocks reliable testing of freshness, windows and cut-offs |
| ASR-2 | A transport seam in the collector base | **ACTIONABLE** — decides whether collector logic is unit- or integration-tested |
| ASR-3 | A policy-pass registry that makes the single-writer rule auditable | **ACTIONABLE** — without it `CPM-AD-21` is unenforceable over time |
| ASR-4 | Freshness targets as required configuration, refused at startup when absent | **ACTIONABLE** — closes the largest false-clean path |
| ASR-5 | `analytics` alias test configuration and the inherited assertion's meaning | **ACTIONABLE** — cross-boundary, needed before `CPM-EP-NL` |
| ASR-6 | Replay determinism as a property test | **FYI** — already designed; `CPM-PRIORITY-S03` covers it |
| ASR-7 | Correlation ids persisted on run-ledger rows | **FYI** — already designed; `CPM-EVIDENCE-S03` covers it |

## Risk register

Scored per `risk-governance.md`: probability × impact, 1–3 each, total 1–9. Score ≥6 demands
documented mitigation. **Residual** is the score after the designed mitigation *and* the test
that proves it — the column that should drive sprint ordering.

| ID | Cat | Risk | P | I | Score | Residual |
|---|---|---|---|---|---|---|
| R-01 | DATA | **A five-state value collapses at a boundary** — a rollup, serializer, export or governed view renders `unknown`, `error` or `not_applicable` as blank or as clean | 3 | 3 | **9** | 3 |
| R-02 | DATA | **Two policy passes clobber the rollup** — the second's full-row upsert resets the first's columns to defaults, silently turning a determinate finding into `unknown` | 3 | 3 | **9** | 2 |
| R-03 | DATA | **Freshness never fires** — no per-collector target is configured, so nothing is ever stale and six-month-old evidence reads as current | 3 | 3 | **9** | 2 |
| R-04 | BUS | **An accepted finding resurrects** — a workflow item keyed on an evidence row id returns as new unactioned work after every re-observation | 2 | 3 | **6** | 2 |
| R-05 | OPS | **A failed collection is invisible** — a worker killed mid-call leaves no ledger row, so the failure looks like no data | 2 | 3 | **6** | 2 |
| R-06 | DATA | **Evidence is updated, not inserted** — a `bulk_update`, `queryset.update()` or raw SQL bypasses the base model's `save()` and destroys the audit trail irrecoverably | 2 | 3 | **6** | 3 |
| R-07 | TECH | **A sweep runs in one transaction** — one package's failure rolls back thousands, making `CPM-FR-15` partial success unreachable and pinning the WAL for the sweep's duration | 2 | 3 | **6** | 2 |
| R-08 | BUS | **The confidence gate is re-implemented per policy** — eight passes each copy it, and `unmapped` reads differently in two views | 3 | 2 | **6** | 2 |
| R-09 | SEC | **The analytics component gets write access** — the second alias and router are unbuilt, and reusing `default` is the path of least resistance | 2 | 3 | **6** | 2 |
| R-10 | SEC | **Sensitive internal usage fields reach an external model** — no field-level restriction exists between the governed views and the tool layer | 2 | 3 | **6** | 2 |
| R-11 | OPS | **A queue-routing regression is undetectable** — eager Celery in test means a task routed to a non-existent queue still passes | 3 | 2 | **6** | 2 |
| R-12 | PERF | **An unpaginated response at full inventory size** — memory exhaustion or timeout on the most-read view | 1 | 3 | 3 | 2 |
| R-13 | TECH | **The `analytics` alias breaks an inherited platform test** — `ATOMIC_REQUESTS` is asserted true for every alias | 3 | 1 | 3 | 1 |
| R-14 | OPS | **A new domain app silently loses trace correlation or lands an unauthenticated route** — inherited guarantees are not re-asserted per app | 2 | 2 | 4 | 2 |

### The three nines are one risk

R-01, R-02 and R-03 are not independent findings. They are three routes to the same
outcome — **a package reading clean when it is unassessed, contradicted, or stale** — which
`CPM-SM-C1` names as the product's defining failure. They score 9 because each is
individually probable (the idiomatic Django call, the export contract's own "blank means
missing" rule, and an unset configuration value) and because the failure is *silent*: no
exception, no alert, and a dashboard that improves as the product gets worse.

They are not a reason to fail the gate. They are the reason this test design exists, and the
mitigation for all three is the same shape — a declared list of forbidden outcomes plus a
mechanical audit that every one has a test proving it cannot happen.

## NFR planning assessment

| Category | In scope via | Threshold | Planned evidence |
|---|---|---|---|
| Reliability | `CPM-NFR-1`, `CPM-NFR-3`, `CPM-FR-15` | Partial success on any single-source failure; no manual batching at 10,000 | Fault-injection integration tests; chunking and bounded-query unit tests |
| Reliability | `CPM-FR-38` | Per-collector freshness target — **UNKNOWN (OQ 7)** | Mechanism test now; threshold test when the value exists. Recommend refusing at startup when unset (ASR-4) |
| Performance | `CPM-NFR-5` | p95 latency at full inventory — **UNKNOWN (OQ 5)** | Bounded query-count assertions now; a non-gating volume job when the budget exists |
| Performance | `CPM-NFR-4` | Enforced maximum page size — value **UNKNOWN**, enforcement is not | Global config assertion plus a per-endpoint audit |
| Performance | `CPM-AD-9` | Sync export row cap — **UNKNOWN (OQ 5)** | Assert one settings constant is read by every export path |
| Security | `CPM-NFR-8`, `CPM-FR-33` | Read-only role, row limits, query timeouts | Permission-level integration test proving the analytics role cannot write |
| Security | `CPM-NFR-9` | No sensitive internal usage fields to an external model | Field-allowlist test on the governed views |
| Security | `CPM-NFR-11`, `CPM-FR-31` | Every refusal logged with acting user identity | Assertion on the structured log record, not on stdout |
| Security | `CPM-NFR-10` | No credential or endpoint defaulted to a production value | Inherited stage-one startup refusals already cover this |
| Maintainability | `pixi run ci` | 90% coverage floor; currently 97.04% | Existing gate |
| Observability | `CPM-NFR-12`, `CPM-NFR-13`, `CPM-FR-39` | `trace_id` on every run-ledger row | Assert the persisted id equals the active span's |
| Compliance / audit | `CPM-FR-32`, `CPM-FR-36` | Append-only evidence; every privileged write audited atomically | Audit-trail integration tests; a mutation-path audit for R-06 |

**Five thresholds are UNKNOWN and none is invented here.** Each is already a PRD open
question with an owner. The pattern throughout: test that the mechanism exists, is wired, and
is honoured everywhere — then add the threshold assertion when the number is chosen.


---

# Step 4 — Coverage plan and execution strategy

## Test levels in this project

`{EPIC}.{STORY}-{LEVEL}-{SEQ}` per `test-levels-framework.md`, with epic and story taken from
the `CPM-` keys — e.g. `EVIDENCE.02-UNIT-001`.

| Level | Meaning here | Tier |
|---|---|---|
| `UNIT` | Pure logic, no database, network or filesystem | `tests/unit/` |
| `INT` | Real models, real database, transactions | `tests/integration/` |
| `API` | Through the HTTP layer with DRF's client, including authorization | `tests/integration/` |
| `AUDIT` | **Project-specific.** Mechanically reconciles a declared list of invariants against the tests or code that prove them | `tests/unit/` |

**`AUDIT` earns its own level.** It does not test behaviour — it tests that a rule cannot be
violated by code written later. The platform already runs one (`test_refusal_coverage_audit.py`
reconciling declared forbidden states against tests that prove refusal). Every `AUDIT` entry
below is that pattern pointed at a new invariant, and each is the answer to a negative
property that would otherwise rot (TC-3).

There is **no E2E level.** No browser framework is installed, no UX contract exists, and the
three user journeys are reachable through `API` plus `INT`. Adding Playwright to satisfy a
level in a framework would be adding a dependency to satisfy a document.

## Coverage matrix — risk-driven

Ordered by residual risk, not by epic. P0 blocks core functionality with no workaround; P1 is
a critical path; P2 secondary; P3 exploratory.

### R-01 · A five-state value collapses at a boundary — score 9

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `EVIDENCE.01-AUDIT-001` | Every derived-status field in the project is a `CharField` with choices carrying all four sentinels — enumerated from the model registry, not a hand-written list | AUDIT | **P0** |
| `EVIDENCE.01-UNIT-001` | The precedence order is total, defined once, and `core` is the only module defining one | UNIT | **P0** |
| `EVIDENCE.01-UNIT-002` | Aggregating any pair of states yields the same result as the declared order — property test over the full cross-product | UNIT | **P0** |
| `APP.06-INT-001` | An export renders `unknown`, `not_found`, `not_applicable` and `error` as their literal values; blank appears only where a field genuinely has no value | INT | **P0** |
| `APP.07-API-001` | The API serializes each of the five states verbatim; none maps to `null`, `""` or `true`/`false` | API | **P0** |
| `NL.01-AUDIT-001` | Every derived-status column present in the rollup is present in the governed views — a set difference, failing on any column added to one and not the other | AUDIT | **P0** |

### R-02 · Two policy passes clobber the rollup — score 9

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `EVIDENCE.07-AUDIT-002` | Every pass registered with the policy run declares the derived table it owns, and none declares the rollup | AUDIT | **P0** |
| `EVIDENCE.07-INT-001` | Two passes writing different domains in one run both survive: neither's columns are reset to defaults by the other | INT | **P0** |
| `EVIDENCE.07-INT-002` | The rollup row carries the run id, the run's cut-off and a per-domain version map — not one scalar version | INT | **P0** |
| `EVIDENCE.07-INT-003` | Exactly one rollup row exists per inventory package after a run, including `unmapped` packages whose gated statuses read `unknown` | INT | **P0** |
| `EVIDENCE.07-UNIT-001` | The cut-off is the `finished_at` of a *completed* collection run; a run still `running` is never selected | UNIT | **P0** |
| `PRIORITY.01-INT-001` | A pass reading an earlier pass's output gets the same run's values, never a previous run's | INT | P1 |

### R-03 · Freshness never fires — score 9

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `EVIDENCE.06-AUDIT-001` | Every registered collector declares a freshness target; startup refuses with `ImproperlyConfigured` when one does not (ASR-4, inherited `CG-3`) | AUDIT | **P0** |
| `EVIDENCE.06-UNIT-001` | Evidence older than its target reports `stale`; `stale` never equals clean at any comparison | UNIT | **P0** |
| `EVIDENCE.06-UNIT-002` | With the clock advanced past the target, previously-fresh evidence flips to `stale` — requires the injectable clock (ASR-1) | UNIT | **P0** |
| `SECURITY.06-UNIT-001` | Remediation readiness on stale supporting evidence reports stale, never "a fix is available" | UNIT | P1 |

### R-04 · An accepted finding resurrects — score 6

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `APP.04-INT-001` | A finding accepted, then re-observed as a new evidence row, does not reappear as new unactioned work | INT | **P0** |
| `APP.04-AUDIT-001` | Every evidence table that can back a workflow item declares a finding key, and no workflow item is keyed on an evidence row id | AUDIT | P1 |
| `APP.04-INT-002` | Accepting one advisory on a package does not accept the package's other advisories | INT | P1 |
| `APP.04-INT-003` | A concurrent transition from a stale prior state is refused, not last-writer-wins | INT | P1 |

### R-05 · A failed collection is invisible — score 6

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `EVIDENCE.03-INT-001` | The ledger row exists with status `running` *before* the first outbound call | INT | **P0** |
| `EVIDENCE.03-INT-002` | A collector raising mid-run still finalizes its ledger row via `finally`; the row is never absent | INT | **P0** |
| `EVIDENCE.03-INT-003` | "Started and never finished" is answerable — rows left `running` are queryable | INT | P1 |
| `EVIDENCE.03-UNIT-001` | The persisted `trace_id` equals the active span's | UNIT | P1 |

### R-06 · Evidence is updated, not inserted — score 6

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `EVIDENCE.02-UNIT-001` | `save()` on an instance with a primary key raises | UNIT | **P0** |
| `EVIDENCE.02-AUDIT-001` | Every evidence model inherits the append-only base — enumerated from the model registry | AUDIT | **P0** |
| `EVIDENCE.02-AUDIT-002` | No module calls `queryset.update()`, `bulk_update()` or raw SQL against an evidence table — the bypass `save()` cannot catch | AUDIT | **P0** |
| `EVIDENCE.02-INT-001` | Re-observing an unchanged fact inserts a second row with a later `observed_at` | INT | **P0** |
| `EVIDENCE.02-AUDIT-003` | No evidence table carries a unique constraint that would suppress an insert | AUDIT | P1 |

### R-07 · A sweep runs in one transaction — score 6

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `CURRENCY.05-INT-001` | A failure on package N leaves packages 1..N-1 evidence committed, and the run reports `partial` | INT | **P0** |
| `CURRENCY.05-UNIT-001` | The atomic unit is one package or one declared chunk — never the sweep | UNIT | P1 |
| `IDENTITY.05-INT-001` | An override and its audit row commit or roll back together; neither survives alone | INT | **P0** |
| `APP.04-AUDIT-002` | No privileged write defers its audit row to `transaction.on_commit` or a follow-up task | AUDIT | P1 |

### R-08 · The confidence gate is re-implemented per policy — score 6

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `IDENTITY.03-AUDIT-001` | The gate has exactly one implementation; no policy module defines its own | AUDIT | **P0** |
| `IDENTITY.03-UNIT-001` | An `unmapped` package reports `unknown` for every gated status and is never current, clean, or "no feedstock" | UNIT | **P0** |
| `IDENTITY.03-UNIT-002` | `inventory-derived` sets a confidence label and does **not** degrade a determinate value | UNIT | **P0** |
| `CURRENCY.07-UNIT-001` | The feedstock policy on an `unmapped` package reports `unknown`, never absent | UNIT | P1 |

### R-09 / R-10 · Analytics write access and sensitive-field exposure — score 6

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `NL.01-INT-001` | The analytics role cannot insert, update or delete on any table — asserted at the database permission level, not by convention | INT | **P0** |
| `NL.01-INT-002` | The router refuses writes and migrations on the `analytics` alias | INT | **P0** |
| `NL.01-AUDIT-002` | Governed views expose no field on the sensitive-usage allowlist | AUDIT | **P0** |
| `NL.01-INT-003` | Query timeout and row limit are enforced on the analytics connection | INT | P1 |

### R-11 · Queue routing regressions are undetectable — score 6

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `EVIDENCE.04-AUDIT-001` | Every registered task's declared route resolves to `collect`, `policy` or `verify` — configuration, not runtime, because eager Celery hides routing (TC-5) | AUDIT | P1 |
| `PY314.02-AUDIT-001` | Verification tasks route to `verify` and never to `collect` | AUDIT | P1 |
| `EVIDENCE.04-UNIT-001` | Cadence is scheduler data; no task carries a hard-coded schedule decorator | UNIT | P2 |

### R-12 / R-13 / R-14 · Lower-scoring risks

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `APP.01-AUDIT-001` | Every list endpoint is paginated; no view or serializer opts out | AUDIT | P1 |
| `APP.08-AUDIT-001` | Every export path reads the same row-cap settings constant | AUDIT | P1 |
| `APP.02-INT-001` | The health view's query count is bounded and independent of row count — no N+1 (stands in for volume, per TC-4) | INT | P1 |
| `NL.01-UNIT-001` | The `analytics` alias sets `ATOMIC_REQUESTS = False`, and the inherited assertion reads "every alias Django may write through" (TC-6) | UNIT | P1 |
| `PLATFORM.01-AUDIT-001` | Every domain app under `django_apps/` is adopted in two lines and self-registers nothing | AUDIT | P2 |
| `PLATFORM.02-AUDIT-001` | Every new route declares a required role; none is unauthenticated except the probes | AUDIT | P1 |
| `EVIDENCE.01-AUDIT-002` | No module calls `timezone.now()` directly; all time comes from the injected clock (ASR-1) | AUDIT | P1 |

### Journey coverage

| Test ID | Scenario | Level | Pri |
|---|---|---|---|
| `APP.05-API-001` | `CPM-UJ-1` — a reviewer opens the KEV queue, sees advisory, ranges, matched version, source and observation time, and routes the finding to remediation | API | P1 |
| `APP.05-API-002` | `CPM-UJ-2` — the feedstock-gap report excludes `unmapped` packages, because absence cannot be claimed for an unresolved identity | API | **P0** |
| `APP.05-API-003` | `CPM-UJ-3` — the coverage view shows resolved-identity fraction, per-collector freshness, and failed runs with their reasons | API | P1 |
| `APP.05-API-004` | A role opening another role's queue is refused, and the refusal is logged with the acting user identity | API | **P0** |

**Duplicate-coverage guard applied.** The five-state rule is proven once at each level for a
different reason: `AUDIT` that the field type permits all five, `UNIT` that precedence is
correct, `INT`/`API` that the boundary does not collapse them on the way out. That is defence
in depth on the product's defining failure, not redundancy. Elsewhere, anything provable by
an `AUDIT` or `UNIT` test is not repeated at `INT`.

## NFR evidence plan

| NFR | Validation | Evidence for later `nfr-assess` |
|---|---|---|
| `CPM-NFR-1`, `CPM-NFR-3` reliability | Fault-injection `INT` tests; chunking `UNIT` tests | Partial-success run ledger rows; `test-cov` report |
| `CPM-FR-38` freshness | Mechanism now; threshold when OQ 7 resolves | Startup refusal test; staleness `UNIT` tests |
| `CPM-NFR-4` pagination | `AUDIT` over every list endpoint | Endpoint audit output |
| `CPM-NFR-5` latency | Bounded query counts now; a **non-gating** volume job when OQ 5 resolves | Query-count assertions; volume job report |
| `CPM-NFR-8`, `CPM-NFR-9` security | Database-permission `INT` test; field-allowlist `AUDIT` | Permission denial output; allowlist diff |
| `CPM-NFR-11` audit logging | Assertion on the structured log record, not stdout | Captured log records |
| `CPM-NFR-12`, `CPM-NFR-13` observability | `trace_id` equality assertion | Run-ledger rows |
| `CPM-NFR-10` config | Inherited stage-one refusals | Existing refusal coverage audit |

Five thresholds remain **UNKNOWN** and are tracked as PRD open questions, not invented here.

## Execution strategy

| Stage | Contents | Budget |
|---|---|---|
| **PR** (`pixi run ci`) | Every `UNIT`, `AUDIT`, `INT` and `API` test. The suite is 1,545 tests in ~30s today; this design keeps everything gating | < 15 min |
| **Nightly** | Volume run at 10,000 packages; live-transport contract checks against real external sources | not gating |
| **Weekly** | Python 3.14 build-and-import verification across a package sample — genuinely compute-backed, on the `verify` queue | not gating |

Everything that protects a score-9 risk runs on **every PR**. The `AUDIT` tests are the
cheapest in the suite — they read declarations, not data — so there is no cost argument for
deferring them.

## Resource estimates

Ranges, not point estimates.

| Priority | Scope | Estimate |
|---|---|---|
| P0 | 31 scenarios — the three nines, the audit harness, the append-only guarantees, analytics permissions | ~45–70 hours |
| P1 | 22 scenarios — journeys, routing audits, concurrency, pagination and export audits | ~30–45 hours |
| P2 | 2 scenarios — adoption and cadence audits | ~4–8 hours |
| P3 | exploratory around advisory-source behaviour once OQ 1 resolves | ~2–5 hours |
| **Total** | | **~80–130 hours**, spread across the epics rather than front-loaded |

Roughly a third of P0 is the reusable `AUDIT` harness itself — the declared-list plus
reconciliation-test machinery. It is built once in `CPM-EP-EVIDENCE` and every later audit
is then a few lines.

## Quality gates

| Gate | Threshold |
|---|---|
| P0 pass rate | **100%** — no exceptions |
| P1 pass rate | ≥ 95% |
| High-risk mitigation | Every risk scoring ≥6 has a passing test before its epic is called done |
| Coverage | ≥ 90% (the project's existing floor, above the framework's 80% default; currently 97.04%) |
| Score-9 risks | Each of R-01, R-02, R-03 has a passing `AUDIT` test before `CPM-EP-APP` starts — they are unfixable-in-place once data exists |
| NFR evidence | Every in-scope NFR category has an identified evidence source; PASS/CONCERNS/FAIL deferred to `nfr-assess` |
| Unknown thresholds | Five UNKNOWN values do not block the gate. Each has a mechanism test now and a threshold test queued behind its open question |


---

# Step 4 addendum — mitigation ownership, data prerequisites, execution order

Added to close checklist items that steps 3 and 4 left open.

## Mitigation owners and timelines

This project has a single maintainer, so a named-person column would be noise. Ownership is
recorded as the **story that owns the mitigation** — the meaningful unit here, because the
backlog is dependency-ordered and a story cannot be called done until its mitigation passes.

| Risk | Mitigation owner (story) | Timeline |
|---|---|---|
| R-01 | `CPM-EVIDENCE-S01` + `CPM-APP-S06` / `S07` | Enum and audit before any collector; boundary tests before `CPM-EP-APP` is done |
| R-02 | `CPM-EVIDENCE-S07` | Before the second policy pass exists — i.e. before `CPM-EP-SECURITY` |
| R-03 | `CPM-EVIDENCE-S06` | Before the first collector ships |
| R-04 | `CPM-APP-S04` | Before any queue is worked by a human |
| R-05 | `CPM-EVIDENCE-S03` | Before the first collector ships |
| R-06 | `CPM-EVIDENCE-S02` | Before the first evidence row is written |
| R-07 | `CPM-CURRENCY-S05`, `CPM-IDENTITY-S05` | Before the first full-inventory sweep |
| R-08 | `CPM-IDENTITY-S03` | Before the second policy consumes confidence |
| R-09 | `CPM-NL-S01` and the alias story that follows the spike | Before `CPM-EP-NL` ships |
| R-10 | `CPM-NL-S01` and the governed-views story | Before `CPM-EP-NL` ships |
| R-11 | `CPM-EVIDENCE-S04` | With the queues themselves |
| R-12 | `CPM-APP-S01` | With global pagination |
| R-13 | `CPM-NL-S01` | With the alias |
| R-14 | `CPM-PLATFORM-S01` / `S02` | With the first domain app |

**Residual risk** is already recorded per row in the register. Every risk scoring ≥6 drops to
2 or 3 residual once its mitigation and test are in place; none is accepted unmitigated, and
no waiver is requested.

## Data prerequisites

| Prerequisite | Why | Where it comes from |
|---|---|---|
| Recorded external payloads per collector | `tests/unit/` forbids network; collector parse logic must be unit-testable (TC-2) | Captured once per source, stored as fixtures alongside the collector's tests |
| A package fixture at each confidence level — `verified`, `inventory-derived`, `unmapped` | The confidence gate is the most-branched logic in the product | `factory_boy`, extending the existing `tests/factories.py` |
| Evidence at controlled ages | Freshness and staleness cannot be tested against a real clock (TC-1) | The injectable clock of ASR-1, not sleeping or backdating rows |
| A completed and an in-flight collection run | The cut-off must never select a run still `running` | Run-ledger fixtures |
| Two policy passes writing different domains in one run | The rollup-clobbering test needs a genuine second writer | Test-only passes registered with the run |
| A package whose type makes a check inapplicable | `not_applicable` must be distinguishable from `unknown` end to end | A non-Python package fixture, even though v1 targets the Python subset |
| An advisory with a known fixed range | Remediation readiness needs `ready`, `blocked` and `unknown` cases | Synthetic advisory fixtures; **not** live advisory data, which is unresolved (OQ 1) |

No production data is required, and none should be used — the inventory carries internal
usage fields that `CPM-NFR-9` restricts.

## Tooling and access requirements

| Need | Status |
|---|---|
| `pytest`, `pytest-django`, `factory_boy` | Already present and in use |
| PostgreSQL 17 for the integration tier | Already used by the gate; the sqlite substitution covers non-Linux legs only |
| A second database role with `SELECT`-only grants | **Not yet provisioned.** Needed for `NL.01-INT-001`, and it must be a real role — asserting read-only by convention proves nothing |
| Network access to external sources | Nightly only. The PR tier uses recorded payloads |
| Compute for Python 3.14 build verification | Weekly tier; genuinely compute-backed, on the `verify` queue |
| Browser automation | **Not required.** No E2E level |
| A load-testing tool | **Not required yet.** Bounded query-count assertions stand in until the p95 budget exists (OQ 5) |

## Execution order within the PR tier

`AUDIT` → `UNIT` → `INT` → `API`.

Audits run first because they are the cheapest — they read declarations, not data — and they
fail on exactly the class of defect that makes later results untrustworthy. A run where
`EVIDENCE.02-AUDIT-002` fails has an evidence table someone can mutate, and every downstream
assertion about history is then meaningless.

The PR tier is not split into smoke and priority waves. At ~30 seconds for 1,545 tests there
is nothing to gain, and the `PR / Nightly / Weekly` model stays simple as the framework asks.


---

# Step 5 correction — scenario count

The step-4 narrative said "53 scenarios: 30 P0, 20 P1, 3 P2". Counting the matrix rows gives
**55 distinct test IDs: 31 P0, 22 P1, 2 P2**, with P3 exploratory and carrying no IDs. The
earlier figure was an estimate stated as a count. The matrix itself was always right; the
summary of it was not. Effort ranges are unchanged — two scenarios do not move an 80–130 hour
band.


---

# Step 5 — Outputs and validation

**Execution mode: `subagent`.** Config `tea_execution_mode: auto` with `tea_capability_probe:
true`; agent-team unavailable, subagents available, so `auto` resolved to `subagent`. The two
system-level documents are independent artifacts and were rendered in parallel, then
reconciled against this checkpoint.

## Documents produced

| Document | Path | Lines | Audience |
|---|---|---|---|
| Architecture test design | `_bmad-output/test-artifacts/test-design-architecture.md` | 504 | Architects and developers — what must be decided or changed for the system to be testable |
| QA test design | `_bmad-output/test-artifacts/test-design-qa.md` | ~690 | Test engineers — the coverage plan, entry/exit criteria, execution strategy |
| BMAD handoff | `_bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md` | 148 | Sprint planning and story retrofit |
| Progress checkpoint | this file | — | The working record of steps 1–5 |

## Reconciliation performed

1. **Scenario count corrected** — 55, not 53. See the correction note above.
2. **Data Prerequisites and Execution Order added to the QA document.** Both came from the
   step-4 addendum, written after the rendering agents had launched, so neither was in their
   source. Inserted and verified.
3. **Cross-document consistency verified** — all three carry the same 14 risks; the QA
   document carries all 55 test IDs; the handoff carries the 17 P0 criteria to retrofit onto
   existing stories and the 5 actionable ASRs.
4. **No forbidden runner** (`uv`, bare `python`, `pip`) appears in any output. The one
   Playwright mention in the QA document is the record of why those fragments were *not*
   loaded, not a prescription.

## Checklist validation

| Area | Result |
|---|---|
| Prerequisites — PRD, ADRs, architecture document, testable requirements | Pass |
| Context loading — artifacts, existing coverage, knowledge fragments | Pass |
| Risk assessment — genuine risks, categories, P and I scored 1–3, scores calculated, ≥6 flagged, mitigations, owners, timelines, residual | Pass |
| NFR planning — categories, thresholds extracted, UNKNOWNs marked and not guessed, evidence sources, NFR risks in the register | Pass |
| Coverage design — atomic scenarios, levels, no duplicate coverage, P0–P3, data prerequisites, tooling, execution order | Pass |
| Deliverables — risk matrix, coverage matrix, execution order, estimates, quality gates, correct location, template structure | Pass |
| Output validation — unique risk IDs, categories, valid P/I, correct scores, ≥6 marked, specific mitigations | Pass |
| Execution strategy — simple PR / Nightly / Weekly, not complex tiers | Pass |
| CLI session hygiene | N/A — no browser automation was used |
| Temp artifacts under `{test_artifacts}` | Pass — nothing written outside `_bmad-output/test-artifacts/` |

## Open assumptions carried forward

- Five PRD thresholds remain UNKNOWN (OQ 1, 2, 5, 7, 8, 10). Each has a mechanism test now and
  a threshold test queued behind its open question. None was invented.
- No implementation exists, so every testability finding is a design-time recommendation
  rather than an observation of running code.
- `CPM-EP-NL` scenarios assume the fitness spike returns adopt or adopt-with-constraints. A
  reject verdict changes `NL.01-*` in shape, though not the underlying requirement that the
  analytics path cannot write.
- A `SELECT`-only database role is **not provisioned**. `NL.01-INT-001` needs a real role with
  real grants; asserting read-only by convention proves nothing.
