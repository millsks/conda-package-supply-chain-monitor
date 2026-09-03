---
title: 'Sprint Change Proposal — Inventory Ingestion and Open Question 3'
date: 2026-09-02
sourceWorkflow: 'bmad-correct-course'
status: 'approved-and-applied'
appliedOn: 2026-09-02
scope: 'Moderate'
triggeredBy: '_bmad-output/planning-artifacts/implementation-readiness.md (F-1, F-2)'
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
---

# Sprint Change Proposal — Inventory Ingestion and Open Question 3

## 1. Issue Summary

**Trigger.** The `bmad-sprint-planning` readiness gate, run 2026-09-02, returned CONCERNS
and was stopped before generating tracking. This is not a story-triggered change: nothing is
in flight. `src/django_apps/` does not exist, no `sprint-status.yaml` exists, and zero of the
42 stories have started.

**Issue type.** Misunderstanding of original requirements, caught before implementation.

**Problem statement.** Two related gaps, both in `CPM-EP-IDENTITY`:

**F-1 — nothing populates the inventory.** PRD §9 assigns "the inventory" to
`CPM-EP-IDENTITY`, and `CPM-IDENTITY-S01` defines the `Package` model, but no story ingests
packages into it. No functional requirement states ingestion either — the PRD's 41 FRs cover
resolving, observing, deriving and displaying packages, never acquiring them. Downstream
stories assume rows exist: `CPM-IDENTITY-S02` opens *"Given an inventory package"*,
`CPM-CURRENCY-S05` opens *"Given a full sweep across 10,000 packages"*.

**F-2 — the internal usage signals have no home in the data model.** `CPM-AD-1` already
establishes that PRD Appendix A.1 is an export contract rather than a table definition, and
enumerates which A.1 fields are projections rather than `Package` columns. The internal usage
signals — `platforms`, `apps`, `downloads`, `versions`, `internal_component_count`,
`internal_lob_count` — appear in **neither** list, and `CPM-AD-1`'s rule limits `Package` to
canonical name, cross-ecosystem mappings, provenance and confidence. The core-entity ER
diagram has no entity that could hold them.

Meanwhile `CPM-PRIORITY-S01` needs them as the score input and `CPM-IDENTITY-S04` ranks the
review queue "by internal usage breadth". PRD Open Question 3 asks where these fields come
from and records its blocking scope as `CPM-EP-PRIORITY` only; `epics.md`'s
"Values that must NOT be invented" table omits OQ 3 entirely, listing OQ 1, 2, 5, 7, 8 and 10.

**Evidence.**

| Claim | Location |
|---|---|
| `Package` holds identity only; A.1 projections enumerated, usage signals absent from both lists | `ARCHITECTURE-SPINE.md` `CPM-AD-1` |
| No entity holds usage signals | `ARCHITECTURE-SPINE.md` §Core entities ER diagram |
| Review queue ranked by usage breadth | `epics.md` `CPM-IDENTITY-S04`; PRD `CPM-FR-4` |
| Score computed from internal usage signals | `epics.md` `CPM-PRIORITY-S01`; PRD `CPM-FR-20` |
| OQ 3 scoped to `CPM-EP-PRIORITY` only | PRD §10 item 3 |
| OQ 3 missing from the must-not-invent table | `epics.md` §"Values that must NOT be invented" |
| Inventory assigned to `CPM-EP-IDENTITY` with no FR behind it | PRD §9 epic table |

## 2. Impact Analysis

### Epic impact

| Epic | Impact |
|---|---|
| `CPM-EP-IDENTITY` | **Primary.** Gains one story and one requirement. Scope grows; the epic's user outcome is unchanged |
| `CPM-EP-EVIDENCE` | **Ripple.** One acceptance criterion added to `CPM-EVIDENCE-S03` — see §4 |
| `CPM-EP-PRIORITY` | **Documentation only.** `CPM-PRIORITY-S01` gains a constraint line naming OQ 3 as the source of its score inputs |
| `CPM-EP-APP` | **Documentation only.** `CPM-APP-S05`'s identity-queue ranking inherits the same OQ 3 constraint |
| All others | No impact |

**Build order is unchanged.** `CPM-EP-IDENTITY` already declares `Depends on: CPM-EP-EVIDENCE`,
so the new story's dependency on the collector base (`CPM-EVIDENCE-S05`), the append-only base
(`CPM-EVIDENCE-S02`) and the run ledger (`CPM-EVIDENCE-S03`) is already satisfied by the
existing graph. No epic is added, removed, resequenced or reprioritized.

### Story impact

**No story is renumbered.** The new story is appended as `CPM-IDENTITY-S06` and sequenced
*first* within its epic, mirroring how `epics.md` already handles `CPM-EP-EVIDENCE` being
listed after the collectors it precedes in delivery. Renumbering was considered and rejected:
the TEA handoff binds 17 P0 acceptance criteria and a 14-row risk map to story keys including
`CPM-IDENTITY-S03` and `CPM-IDENTITY-S05`, and renumbering would silently invalidate every one.

### Artifact conflicts

| Artifact | Change |
|---|---|
| PRD | New `CPM-FR-42`; OQ 3 scope widened; §7 and §9 updated; Appendix A.2 gains `inventory_snapshots` |
| Architecture spine | New `CPM-AD-25`; `CPM-AD-1` and `CPM-AD-14` clarified; ER diagram and capability map updated; Deferred gains OQ 3 |
| `epics.md` | New `CPM-IDENTITY-S06`; requirement inventory, coverage map, must-not-invent table, epic header and story totals updated |
| UX design | N/A — no UX contract exists, and ingestion has no surface |
| TEA test artifacts | No change required. The handoff's story bindings all survive; `CPM-IDENTITY-S06` carries no P0 scenario today and can be added during the F-3 retrofit |

### Technical impact

No code exists yet, so there is nothing to migrate or roll back. The change adds one collector,
one evidence model, and one service call on a path that does not exist. It does not alter the
technology stack, the deployment contract, `component.toml`, or any inherited platform behaviour.

## 3. Recommended Approach

**Selected: Option 1 — Direct Adjustment.**

- **Effort: Low.** Documentation only. One new story, one new FR, one new invariant, and six
  small amendments for consistency.
- **Risk: Low.** Nothing is built. The change is purely additive to the plan; no existing
  requirement, invariant or story is contradicted or withdrawn.
- **Timeline impact: none.** The affected epic has not started, and the epic that has to ship
  first (`CPM-EP-EVIDENCE`) is untouched apart from one clarifying criterion.

**Option 2 — Potential Rollback: not viable, and not needed.** No story is complete; there is
nothing to revert.

**Option 3 — PRD MVP Review: not viable, and not warranted.** The MVP is unaffected. Ingestion
was always implied by the MVP scope line "Package identity resolution … (CPM-FR-1 – CPM-FR-6)";
it was simply never written down. Reducing scope would not address the gap, since the gap is a
missing prerequisite rather than excess ambition.

### The shaping decision

Ingestion is shaped as **a collector writing append-only evidence**, with resolution remaining
the only writer of `Package` rows. Two alternatives were considered:

| Shape | Rejected because |
|---|---|
| A third governed write path in `CPM-AD-14` | Gives the usage signals a mutable table, which makes `CPM-PRIORITY-S03`'s replay non-reproducible: re-running a stated policy version at a stated cut-off would read *today's* usage numbers and silently produce different results |
| Folded into resolution | Smallest edit, but leaves the usage signals homeless and blurs what "resolution" means |

The chosen shape keeps `CPM-AD-1`, `CPM-AD-3` and `CPM-AD-14` intact verbatim, and gives the
usage signals freshness, staleness and a cut-off for free — the same treatment every other
observation gets.

**The consequence that must be written down.** Evidence is append-only (`CPM-AD-2`) and every
evidence row references the package by integer primary key (`CPM-AD-3`). At ingest time the
package does not exist yet, and the snapshot's foreign key can never be filled in later
because nothing may update an evidence row. Therefore the ingestion collector calls `identity`'s
resolution service to create the package shell at `unmapped` confidence, then writes the
snapshot against it inside the same per-package transaction (`CPM-AD-23`). The collector never
writes the `Package` table itself. Left unstated, this is got wrong immediately.

## 4. Detailed Change Proposals

### 4a. Architecture spine

**Edit A1 — new invariant `CPM-AD-25`.** Append to §"Invariants & Rules", after `CPM-AD-24`.

```
### CPM-AD-25 — The inventory arrives as evidence; resolution still owns the package row  *(net-new)*

- **Binds:** `CPM-FR-42`, `CPM-EP-IDENTITY`, `CPM-EP-PRIORITY`
- **Prevents:** the inventory becoming a second, unaudited write path onto the package row,
  and the internal usage signals becoming mutable columns that silently change what a
  replayed policy run concludes.
- **Rule:** the internal inventory is observed by a collector like any other source. It runs
  on the `collect` queue through the shared collector base, and writes `inventory_snapshots`
  — append-only rows carrying the source's package key, the internal usage signals as
  observed, `observed_at`, and the run's correlation identifiers.
- **The collector never writes the package table.** For a source record naming a package that
  does not exist yet, it calls `identity`'s resolution service, which creates the shell at
  `unmapped` confidence; the shell and the snapshot commit in one per-package transaction
  (`CPM-AD-23`). `CPM-AD-14` is unchanged: identity is still mutated by resolution or the
  override path, and by nothing else.
- **Absence is an observation.** A package present in an earlier run and absent from a later
  one is recorded as absent with a timestamp. No package row is ever deleted, and the rollup
  keeps its one row per package (`CPM-AD-11`).
- **Every reader is cut-off bound.** A policy reading a usage signal reads the latest snapshot
  at or before its run's cut-off, never the current value, so `CPM-FR-22` replay reproduces
  identical results.
```

**Edit A2 — `CPM-AD-1`, projection paragraph.** The paragraph beginning *"PRD Appendix A.1 is
an export contract, not a table definition"* enumerates the projected fields. Append:

> OLD: `local_build_status` and `verified_at` are projected from evidence.
>
> NEW: `local_build_status` and `verified_at` are projected from evidence, as are
> `platforms`, `apps`, `downloads`, `versions`, `internal_component_count` and
> `internal_lob_count`, which are observed by the inventory collector and read from
> `inventory_snapshots` (`CPM-AD-25`).

*Rationale:* closes the gap that leaves the usage signals belonging to no table.

**Edit A3 — `CPM-AD-14`, clarifying sentence.** Append to the rule:

> Creation is resolution: a package shell created during inventory ingestion is written by
> `identity`'s resolution service, not by the collector that triggered it (`CPM-AD-25`).

*Rationale:* pre-empts reading "mutated by resolution, or by the override path" as silent on creation.

**Edit A4 — core-entity ER diagram.** Add one node and one edge:

```
  PACKAGE ||--o{ INVENTORY_SNAPSHOT : "observed in"
```

**Edit A5 — Capability → Architecture Map.** `CPM-EP-IDENTITY` row:

> OLD: `django_apps/identity` | `CPM-AD-1`, `CPM-AD-3`, `CPM-AD-4`, `CPM-AD-14`
>
> NEW: `django_apps/identity`, `collectors` | `CPM-AD-1`, `CPM-AD-3`, `CPM-AD-4`, `CPM-AD-14`, `CPM-AD-25`

**Edit A6 — Deferred section.** Add:

> - **The inventory source and the internal usage-signal field set** (`CPM-FR-42`,
>   `CPM-FR-20`). `CPM-AD-25` fixes that they arrive as evidence and are read at a cut-off;
>   where they come from is PRD Open Question 3.

### 4b. PRD

**Edit P1 — new `CPM-FR-42`.** Append to §4.1, after `CPM-FR-6`.

```
#### CPM-FR-42: Inventory ingestion

The system acquires the package inventory from the organization's internal source, together
with the internal usage signals that later rank and score it.

**Consequences (testable):**
- Ingestion is an observation: each run writes append-only rows and never updates a prior one.
- A package named by the source for the first time gains an identity row at `unmapped`
  confidence; ingestion never asserts a mapping (CPM-FR-1).
- A package absent from a later run is recorded as absent with a timestamp; no package is
  deleted, and it keeps its row in the current-health rollup.
- The internal usage signals are read at a stated evidence cut-off, so a policy replay
  reproduces identical results (CPM-FR-22).
- The source location and its credentials come from the environment (CPM-NFR-10).
```

**Edit P2 — §7 MVP scope, "In scope".**

> OLD: Package identity resolution, provenance, confidence, the review queue, and the audited override (CPM-FR-1 – CPM-FR-6).
>
> NEW: Inventory ingestion, package identity resolution, provenance, confidence, the review queue, and the audited override (CPM-FR-1 – CPM-FR-6, CPM-FR-42).

**Edit P3 — §9 epic table, `CPM-EP-IDENTITY` row.**

> OLD: CPM-FR-1 – CPM-FR-6, CPM-FR-32
>
> NEW: CPM-FR-1 – CPM-FR-6, CPM-FR-32, CPM-FR-42

**Edit P4 — §10 Open Question 3.**

> OLD: What is the source of the internal usage fields that drive the CPM-FR-20 score? Blocks `CPM-EP-PRIORITY`.
>
> NEW: What is the source of the internal usage fields (`platforms`, `apps`, `downloads`,
> `versions`, `internal_component_count`, `internal_lob_count`), and what is the inventory
> source that carries them (CPM-FR-42)? Blocks `CPM-EP-PRIORITY`, whose score reads them;
> also constrains `CPM-EP-IDENTITY`, whose review queue ranks by usage breadth (CPM-FR-4),
> and `CPM-EP-APP`, whose identity queue inherits that ranking (CPM-FR-25). The mechanism is
> buildable without the answer — `CPM-AD-25` fixes that these arrive as evidence and are read
> at a cut-off — but no story may invent the field set or the source.

**Edit P5 — Appendix A.2.** Add a row, and amend the section's opening line, which currently
reads "Append-only, keyed by package, source, and observation time":

> | `inventory_snapshots` | Source package key, internal usage signals as observed, presence or absence, observation time (CPM-FR-42) |

> OLD: Append-only, keyed by package, source, and observation time (CPM-FR-36).
>
> NEW: Append-only, keyed by package, source, and observation time (CPM-FR-36). An
> `inventory_snapshots` row is keyed the same way; the package shell it references is created
> by resolution in the same transaction, never by the collector (`CPM-AD-25`).

### 4c. epics.md

**Edit E1 — new story `CPM-IDENTITY-S06`.** Append to §`CPM-EP-IDENTITY`, with a sequencing
note directing it to be built first.

```
### CPM-IDENTITY-S06: The inventory arrives, and arrives as evidence

As a platform lead,
I want the package inventory and its usage signals observed like any other source,
So that every later story has packages to work on and a replay reads the numbers that were
true at its cut-off.

**Sequenced first.** Numbered last because story keys are never reused, built before
`CPM-IDENTITY-S02` because every story after it assumes packages exist.

**Acceptance Criteria:**

**Given** the inventory source configured as data
**When** the ingestion collector runs
**Then** it runs on the `collect` queue through the shared collector base, inheriting its
timeout, retry, backoff and ledger row
**And** the source location and its credentials come from the environment with no default

**Given** a source record naming a package that does not exist yet
**When** ingestion processes it
**Then** `identity`'s resolution service creates the shell at `unmapped` confidence
**And** the collector never writes the package table itself, and a test asserts it

**Given** a source record
**When** its snapshot is written
**Then** the shell and the snapshot commit in one per-package transaction
**And** the row is append-only, references the package by integer pk, and carries
`observed_at`, the usage signals as observed, and the run's `trace_id`

**Given** ingestion runs a second time over unchanged source data
**When** the rows are written
**Then** a new row is inserted rather than a prior one updated

**Given** a package present in an earlier run and absent from this one
**When** ingestion completes
**Then** absence is recorded as an observation with a timestamp, and no package row is deleted

**Given** a policy that reads a usage signal
**When** it runs
**Then** it reads the latest snapshot at or before its run's cut-off, and a replay at a stated
cut-off reproduces identical results

**Satisfies:** `CPM-FR-42`, and the inventory prerequisite for `CPM-FR-1` – `CPM-FR-6`
**Governed by:** `CPM-AD-25`, `CPM-AD-2`, `CPM-AD-3`, `CPM-AD-14`, `CPM-AD-23`
**Constrained:** the inventory source and the usage-signal field set are PRD Open Question 3.
This story builds the collector, the model and the cut-off-bound read; it does not choose the
source or invent the fields.
```

**Edit E2 — `CPM-EVIDENCE-S03`, ripple.** The run ledger currently "carries the collector or
policy name, **the package**, and the `trace_id`". The inventory collector runs once per sweep,
not per package, so it has no package to record. Add an acceptance criterion:

```
**Given** a collector whose run is not scoped to a single package
**When** its ledger row is written
**Then** the package reference is absent rather than fabricated, and "started and never
finished" stays answerable for that run
```

*Rationale:* without this, the first ingestion run cannot write a ledger row that satisfies
`CPM-EVIDENCE-S03` as written. Found by tracing the new story against the epic it depends on.

**Edit E3 — `CPM-IDENTITY-S01`, explicitness.** In the AC block ending "it holds no derived
status, no observation and no workflow state":

> NEW **And** it holds no internal usage signal; those are observed evidence (`CPM-AD-25`)

**Edit E4 — `CPM-IDENTITY-S04`, constraint.** Append:

> **Constrained:** internal usage breadth is read from inventory evidence at a cut-off
> (`CPM-AD-25`); its field set and source are PRD Open Question 3 and are not chosen here.

**Edit E5 — `CPM-PRIORITY-S01`, constraint.** Amend the existing Constrained line:

> OLD: the rule content and the score function are PRD Open Question 8.
>
> NEW: the rule content and the score function are PRD Open Question 8; the internal usage
> signals they score are PRD Open Question 3, read from inventory evidence at the run's
> cut-off (`CPM-AD-25`).

**Edit E6 — Requirements Inventory.** Add after `CPM-FR-41`:

> - **CPM-FR-42** — Inventory ingestion. The system acquires the package inventory and its
>   internal usage signals from the organization's internal source, as append-only evidence.

**Edit E7 — FR Coverage Map.** Add a row:

> | `CPM-FR-42` | `CPM-EP-IDENTITY` | Inventory ingestion as evidence |

**Edit E8 — `CPM-EP-IDENTITY` epic header.**

> OLD: **FRs covered:** `CPM-FR-1` – `CPM-FR-6`, `CPM-FR-32`
> NEW: **FRs covered:** `CPM-FR-1` – `CPM-FR-6`, `CPM-FR-32`, `CPM-FR-42`
>
> OLD: **Governed by:** `CPM-AD-1`, `CPM-AD-3`, `CPM-AD-4`, `CPM-AD-14`
> NEW: **Governed by:** `CPM-AD-1`, `CPM-AD-3`, `CPM-AD-4`, `CPM-AD-14`, `CPM-AD-25`

**Edit E9 — "Values that must NOT be invented" table.** Add, in OQ order:

> | OQ 3 | The inventory source and the internal usage-signal field set |

**Edit E10 — Story totals.**

| Epic | Stories | ACs |
|---|---|---|
| `CPM-EP-EVIDENCE` | 7 | 26 → **27** |
| `CPM-EP-IDENTITY` | 5 → **6** | 18 → **24** |
| **Total** | 42 → **43** | 131 → **138** |

## 5. Implementation Handoff

**Scope classification: Moderate.**

It touches the PRD and the architecture spine, which normally signals Major — but nothing is
replanned. The epic set, the build-order graph, the MVP boundary and every existing story
survive unchanged; the change is additive, and it lands before any code exists. What it needs
is backlog reorganization and a documentation pass, not a strategic rethink.

**Route to:** Product Owner / Developer, for the documentation edits in §4.

| Deliverable | Owner | Definition of done |
|---|---|---|
| Edits A1–A6 to `ARCHITECTURE-SPINE.md` | Developer | `CPM-AD-25` exists; `CPM-AD-1` names the usage signals; ER diagram and capability map updated |
| Edits P1–P5 to `prd.md` | Developer | `CPM-FR-42` exists; OQ 3 names its full blocking scope; §7, §9 and A.2 consistent |
| Edits E1–E10 to `epics.md` | Developer | `CPM-IDENTITY-S06` exists and is marked sequenced-first; totals reconcile to 43/138 |
| Branch and commit | Developer | `feature/` branch per §5 of the project standards; Conventional Commits; PR to `main` |

**Success criteria.**

1. A re-run of `bmad-sprint-planning` clears F-1 and F-2 — no story depends on a package row
   whose origin is unrecorded, and OQ 3's reach is stated wherever it binds.
2. Every requirement identifier still resolves: 42 FRs, 13 NFRs, 25 invariants, 43 stories.
3. No existing story key changes, so the TEA handoff's 17 criteria and 14-row risk map still bind.

**Out of scope for this proposal.** Readiness finding F-3 — retrofitting the TEA handoff's P0
acceptance criteria into the stories and settling ASR-1 … ASR-5 — is independent and unchanged
by anything here. F-4 (no UX contract for `CPM-EP-APP`) remains an accepted risk.

**Not resolved, by decision.** PRD Open Question 3 stays open. This proposal widens where it is
recorded and builds the mechanism around it; it does not answer it. `CPM-EP-PRIORITY` remains
blocked on it, as it was before.
