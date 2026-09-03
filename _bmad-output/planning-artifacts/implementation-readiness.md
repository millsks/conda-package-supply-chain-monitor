---
title: 'Implementation Readiness — Conda Package Supply Chain Monitor'
verdict: CONCERNS
date: 2026-09-02
sourceWorkflow: 'bmad-sprint-planning'
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/solution-design.md
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
---

# Implementation Readiness — CONCERNS

Sprint planning ran the readiness gate on 2026-09-02 and returned **CONCERNS**. Tracking
generation was deliberately not run; the decision was to close the gaps first.

## What passes

- Every one of the 41 functional and 13 non-functional requirements traces forward to an
  epic and, where a story exists, back to recorded intent. No orphans in either direction.
- The nine epics carry no forward dependencies; the build-order graph in `epics.md` is
  acyclic and matches the PRD §9 dependency column.
- The mechanism-versus-content split on the deferred open questions (OQ 1, 2, 4, 5, 7, 8,
  10) is handled correctly. Stories build the machinery and read the undecided values as
  versioned configuration; none fabricates content.
- `CPM-EP-NL` is properly quarantined. Only `CPM-NL-S01` (the fitness spike) is authored,
  and the reason the rest are not is recorded rather than implied.
- The five requirements satisfied by inherited platform behaviour are listed with where
  they already live, so *inherited* is distinguishable from *forgotten*.

## Resolution status

F-1 and F-2 were resolved on 2026-09-02 by
`sprint-change-proposal-2026-09-02.md` — `CPM-FR-42`, `CPM-AD-25` and `CPM-IDENTITY-S06`
now cover inventory ingestion, and Open Question 3's blocking scope is recorded wherever it
binds. F-3 and F-4 remain open.

## Findings

Ordered by severity.

### F-1 — Nothing populates the inventory  `blocks CPM-EP-IDENTITY`

PRD §9 assigns "the inventory" to `CPM-EP-IDENTITY`. `CPM-IDENTITY-S01` defines the
`Package` model, but no story ingests packages into it.

Downstream stories assume rows already exist:

| Story | Opening precondition |
|---|---|
| `CPM-IDENTITY-S02` | *Given an inventory package* |
| `CPM-IDENTITY-S04` | *Given packages at `unmapped` or `inventory-derived` confidence* |
| `CPM-CURRENCY-S05` | *Given a full sweep across 10,000 packages* |

A developer starting `CPM-IDENTITY-S02` has no recorded answer for how a package row comes
to exist — what the inventory source is, whether ingestion is a management command, a
collector, or an upload, and whether re-ingestion is append-only evidence or a governed
reference-data write under `CPM-AD-14`.

**Fixed by:** adding an inventory-ingestion story to `CPM-EP-IDENTITY`, sequenced before
`CPM-IDENTITY-S02`. Skill: `bmad-correct-course`, or `bmad-create-epics-and-stories` if the
change stays inside `epics.md`.

### F-2 — Open Question 3 reaches further than the PRD records  `blocks CPM-EP-IDENTITY, CPM-EP-APP`

PRD §10 OQ 3 — *"What is the source of the internal usage fields that drive the CPM-FR-20
score?"* — is scoped to `CPM-EP-PRIORITY`. Two earlier stories depend on the same data:

- `CPM-IDENTITY-S04` ranks the unresolved-package selection "by internal usage breadth".
- `CPM-APP-S05` ranks queues "with usage breadth as the score input for identity items"
  (also `ARCHITECTURE-SPINE.md` `CPM-AD-22`).

Both sit upstream of `CPM-EP-PRIORITY` in the build order.

Separately, `epics.md` §"Values that must NOT be invented" lists OQ 1, 2, 5, 7, 8 and 10 —
OQ 3 is absent from the table, so the constraint is invisible to anyone working from the
epic breakdown alone. The fields themselves are named only in PRD Appendix A.1
(`platforms`, `apps`, `downloads`, `versions`, `internal_component_count`,
`internal_lob_count`).

**Fixed by:** correcting OQ 3's blocking scope in the PRD to include `CPM-EP-IDENTITY` and
`CPM-EP-APP`, and adding OQ 3 to the `epics.md` must-not-invent table. Resolves alongside
F-1, since the ingestion story is where these fields would enter. Skill:
`bmad-correct-course`.

### F-3 — Test-design acceptance criteria never reached the stories  `gate on ATDD`

`_bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md`
carries 17 P0 acceptance criteria bound to named existing stories, plus five architectural
decisions (ASR-1 … ASR-5). `epics.md`'s `inputDocuments` predates the test artifacts and
does not reference them, so a developer reading a story in isolation will not see them.

The handoff sets this as its own phase gate: *"Sprint Planning → ATDD: the five ASR
decisions are made; stories carry the acceptance criteria above."* Neither has happened.

Three of the five ASRs are cheap now and expensive later, because they are structural to
`CPM-EP-EVIDENCE` — the first epic in build order after the platform:

| ASR | Decision |
|---|---|
| ASR-1 | An injectable clock in `core`, used everywhere, enforced by an audit test |
| ASR-2 | A transport seam in the collector base, so collector logic is unit-testable |
| ASR-3 | A policy-pass registry, so the single-writer rule is auditable rather than hoped for |
| ASR-4 | Freshness targets as required configuration, refused at startup when absent |
| ASR-5 | The `analytics` alias test configuration, and what the inherited `ATOMIC_REQUESTS` assertion means once a read-only alias exists |

**Fixed by:** a retrofit pass over `epics.md` folding the 17 criteria into their named
stories and recording the ASR decisions in the spine. Skill: `bmad-create-epics-and-stories`
for the criteria; `bmad-architecture` for the ASRs.

### F-4 — No UX design contract for `CPM-EP-APP`  `accepted risk`

Eight stories and 30 acceptance criteria specify behaviour, data and acceptance without a
UX contract; presentation is the implementer's. `epics.md` declares this a known gap rather
than an omission, and the handoff confirms no browser test layer is planned, so all three
user journeys are covered at `API` and `INT` level.

Recorded as an accepted risk, not a defect. It becomes one only if a story turns out to
depend on a layout decision nothing records.

## Recommended sequence

1. Resolve F-1 and F-2 together — one inventory-ingestion story plus the OQ 3 scope
   correction.
2. Resolve F-3 — retrofit the test-design criteria and settle ASR-1 … ASR-4 before
   `CPM-EP-EVIDENCE` starts.
3. Re-run `bmad-sprint-planning` to regate and generate
   `_bmad-output/implementation-artifacts/sprint-status.yaml`.

F-4 needs no action unless it starts blocking a story.
