---
title: 'TEA Test Design → BMAD Handoff Document'
version: '1.0'
workflowType: 'testarch-test-design-handoff'
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/solution-design.md
  - _bmad-output/planning-artifacts/epics.md
sourceWorkflow: 'testarch-test-design'
generatedBy: 'TEA Master Test Architect'
generatedAt: '2026-09-03'
projectName: 'conda-package-supply-chain-monitor'
---

# TEA → BMAD Integration Handoff

## Purpose

Bridges the system-level test design into BMad's epic and story work.

**Read this ordering note first.** The template assumes test design runs *before*
`create-epics-and-stories`. Here it ran *after*: `epics.md` already holds 9 epics and 42
stories, merged to `main` in PR #6. So this document is a **retrofit**, and its guidance is
"add these acceptance criteria to stories that already exist" rather than "embed them while
writing stories". Nothing below asks for a story to be renumbered or rewritten.

## TEA Artifacts Inventory

| Artifact | Path | BMAD Integration Point |
|---|---|---|
| Architecture test design | `_bmad-output/test-artifacts/test-design-architecture.md` | Architectural decisions that must land before their epic starts |
| QA test design | `_bmad-output/test-artifacts/test-design-qa.md` | Story test requirements and the coverage plan |
| Risk assessment | embedded in both | Epic risk classification and story priority |
| Coverage strategy | embedded in the QA document | Story test requirements |
| Progress checkpoint | `_bmad-output/test-artifacts/test-design-progress-system.md` | Full working record of steps 1–4 |

## Epic-Level Integration Guidance

### Risk references

| Epic | Risks it must close | Gate before the epic is done |
|---|---|---|
| `CPM-EP-EVIDENCE` | R-01, R-02, R-03, R-05, R-06, R-11 | Six of the eleven high risks land here. This epic builds the audit harness the rest depend on |
| `CPM-EP-IDENTITY` | R-07 (override atomicity), R-08 (confidence gate) | The gate has exactly one implementation |
| `CPM-EP-CURRENCY` | R-07 (sweep transaction) | Partial success is provable under injected failure |
| `CPM-EP-SECURITY` | R-03 (readiness on stale evidence) | Stale never reads as "a fix is available" |
| `CPM-EP-PY314` | R-11 (queue routing) | Verification routes to `verify`, never `collect` |
| `CPM-EP-PRIORITY` | R-02 (rollup composition) | Two passes in one run do not clobber each other |
| `CPM-EP-APP` | R-01 (export/API boundaries), R-04 (finding key), R-12 | The five states survive every read surface |
| `CPM-EP-NL` | R-09, R-10, R-13 | Analytics role proven unable to write, at the database permission level |

### Quality gates

- P0 pass rate 100%, no exceptions. P1 ≥ 95%.
- Coverage ≥ 90% — the project's existing floor, kept rather than relaxed to the framework's 80%.
- Every risk scoring ≥ 6 has a passing test before its epic is called done.
- **R-01, R-02 and R-03 each need a passing `AUDIT` test before `CPM-EP-APP` starts.** They are
  the false-clean family, and they become unfixable in place once real evidence exists — you
  cannot retroactively tell a row that was genuinely clean from one that collapsed to clean.

## Story-Level Integration Guidance

### P0 scenarios that should become acceptance criteria on existing stories

Each row names a story that already exists and the criterion to add. None requires a new story.

| Story | Add this acceptance criterion | Test ID |
|---|---|---|
| `CPM-EVIDENCE-S01` | Every derived-status field in the project carries all four sentinels, enumerated from the model registry rather than a hand-written list | `EVIDENCE.01-AUDIT-001` |
| `CPM-EVIDENCE-S01` | No module calls `timezone.now()` directly; all time comes from an injected clock | `EVIDENCE.01-AUDIT-002` |
| `CPM-EVIDENCE-S02` | No module calls `queryset.update()`, `bulk_update()` or raw SQL against an evidence table — the bypass `save()` cannot catch | `EVIDENCE.02-AUDIT-002` |
| `CPM-EVIDENCE-S03` | A collector raising mid-run still finalizes its ledger row; the row is never absent | `EVIDENCE.03-INT-002` |
| `CPM-EVIDENCE-S04` | Every registered task's declared route resolves to one of the three queues, asserted as configuration because eager Celery hides routing | `EVIDENCE.04-AUDIT-001` |
| `CPM-EVIDENCE-S06` | Startup refuses when a registered collector declares no freshness target | `EVIDENCE.06-AUDIT-001` |
| `CPM-EVIDENCE-S07` | Every registered pass declares the derived table it owns, and none declares the rollup | `EVIDENCE.07-AUDIT-002` |
| `CPM-EVIDENCE-S07` | Two passes writing different domains in one run both survive; neither is reset to defaults | `EVIDENCE.07-INT-001` |
| `CPM-IDENTITY-S03` | The confidence gate has exactly one implementation; no policy module defines its own | `IDENTITY.03-AUDIT-001` |
| `CPM-IDENTITY-S05` | An override and its audit row commit or roll back together; neither survives alone | `IDENTITY.05-INT-001` |
| `CPM-CURRENCY-S05` | A failure on package N leaves packages 1..N−1 committed and the run reports `partial` | `CURRENCY.05-INT-001` |
| `CPM-APP-S04` | A finding accepted, then re-observed as a new evidence row, does not reappear as new work | `APP.04-INT-001` |
| `CPM-APP-S05` | The feedstock-gap report excludes `unmapped` packages | `APP.05-API-002` |
| `CPM-APP-S05` | A role opening another role's queue is refused, and the refusal is logged with the acting identity | `APP.05-API-004` |
| `CPM-APP-S06` | An export renders the five states as their literal values; blank appears only where a field has no value | `APP.06-INT-001` |
| `CPM-APP-S07` | The API serializes each state verbatim; none maps to `null`, `""` or a boolean | `APP.07-API-001` |
| `CPM-NL-S01` | The analytics role cannot write, asserted at the database permission level | `NL.01-INT-001` |

### Data-TestId requirements

**Not applicable.** This project has no browser test layer: no browser framework is installed,
no UX design contract exists, and all three user journeys are covered at the `API` and `INT`
levels. Adding `data-testid` attributes would serve no test that exists or is planned.

## Risk-to-Story Mapping

| Risk ID | Category | P×I | Recommended story / epic | Test level |
|---|---|---|---|---|
| R-01 | DATA | 9 | `CPM-EVIDENCE-S01`, `CPM-APP-S06`, `CPM-APP-S07`, `CPM-NL-S01` | AUDIT + UNIT + INT + API |
| R-02 | DATA | 9 | `CPM-EVIDENCE-S07`, `CPM-PRIORITY-S01` | AUDIT + INT |
| R-03 | DATA | 9 | `CPM-EVIDENCE-S06`, `CPM-SECURITY-S06` | AUDIT + UNIT |
| R-04 | BUS | 6 | `CPM-APP-S04` | INT + AUDIT |
| R-05 | OPS | 6 | `CPM-EVIDENCE-S03` | INT + UNIT |
| R-06 | DATA | 6 | `CPM-EVIDENCE-S02` | AUDIT + UNIT + INT |
| R-07 | TECH | 6 | `CPM-CURRENCY-S05`, `CPM-IDENTITY-S05` | INT + UNIT + AUDIT |
| R-08 | BUS | 6 | `CPM-IDENTITY-S03`, `CPM-CURRENCY-S07` | AUDIT + UNIT |
| R-09 | SEC | 6 | `CPM-NL-S01` | INT |
| R-10 | SEC | 6 | `CPM-NL-S01` | AUDIT + INT |
| R-11 | OPS | 6 | `CPM-EVIDENCE-S04`, `CPM-PY314-S02` | AUDIT |
| R-12 | PERF | 3 | `CPM-APP-S01`, `CPM-APP-S02` | AUDIT + INT |
| R-13 | TECH | 3 | `CPM-NL-S01` | UNIT |
| R-14 | OPS | 4 | `CPM-PLATFORM-S01`, `CPM-PLATFORM-S02` | AUDIT |

## Recommended BMAD → TEA Workflow Sequence

Adjusted for the actual ordering — epics and stories already exist.

1. ~~**TEA Test Design** (`TD`)~~ — done, produced this handoff
2. ~~**BMAD Create Epics & Stories**~~ — already done, merged in PR #6. Retrofit the acceptance
   criteria above rather than regenerating stories
3. **BMAD Sprint Planning** (`SP`) — the readiness gate. Feed it this handoff so the five
   architectural decisions below are visible as prerequisites
4. **TEA ATDD** (`AT`) — red-phase acceptance tests per story, starting with `CPM-EP-EVIDENCE`
5. **BMAD Build** (`BD`) — implement test-first
6. **TEA Automate** (`TA`) — expand coverage
7. **TEA Trace** (`TR`) — validate coverage completeness against `CPM-FR-*`

## Architectural decisions this handoff asks for

Five, all cheap now and expensive after `CPM-EP-EVIDENCE` ships. Full detail in the
architecture test design.

| ASR | Decision needed |
|---|---|
| ASR-1 | An injectable clock in `core`, used everywhere, enforced by an audit |
| ASR-2 | A transport seam in the collector base, so collector logic is unit-testable |
| ASR-3 | A policy-pass registry, so the single-writer rule is auditable rather than hoped for |
| ASR-4 | Freshness targets as required configuration, refused at startup when absent |
| ASR-5 | The `analytics` alias test configuration, and what the inherited `ATOMIC_REQUESTS` assertion means once a read-only alias exists |

## Phase Transition Quality Gates

| From Phase | To Phase | Gate Criteria |
|---|---|---|
| Test Design | Sprint Planning | All 11 risks scoring ≥6 have a documented mitigation and a named test |
| Sprint Planning | ATDD | The five ASR decisions are made; stories carry the acceptance criteria above |
| ATDD | Implementation | Failing acceptance tests exist for all P0 scenarios |
| Implementation | Test Automation | All acceptance tests pass; `pixi run ci` exits 0 |
| Test Automation | Release | R-01, R-02 and R-03 each have a passing AUDIT test; trace matrix shows ≥90% coverage of P0/P1 requirements |
