---
title: 'Sprint Change Proposal — The Watchlist Is the Inventory Source'
date: 2026-09-04
sourceWorkflow: 'bmad-correct-course'
status: 'approved-pending-application'
scope: 'Moderate'
triggeredBy: 'Stakeholder requirement — a bounded package set for development, and a declared inventory source for v1'
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/sprint-change-proposal-2026-09-02.md
  - _bmad-output/implementation-artifacts/sprint-status.yaml
supersedes: 'PRD Open Question 3 (both halves), resolved here'
---

# Sprint Change Proposal — The Watchlist Is the Inventory Source

## 1. Issue Summary

**Trigger.** A stakeholder requirement raised during review of `CPM-EP-IDENTITY`: the project
needs a bounded subset of inventory data — on the order of 100 packages — to develop and test
against. Pursuing it surfaced a larger unanswered question, and answering that question
resolved PRD Open Question 3 in full.

**Issue type.** New requirement from stakeholders, caught before implementation. No story is
in flight. `CPM-EP-IDENTITY` is at `backlog`; the epics in front of it — `CPM-EP-PLATFORM`
and `CPM-EP-EVIDENCE` — are partially delivered.

**Problem statement.** Three findings, in the order they emerged.

**A — no supported way to populate a database.** `CPM-AD-14` and `CPM-AD-25` permit only
`identity`'s resolution service to create a package row, and its only caller is
`CPM-IDENTITY-S06`'s ingestion collector. That collector reads an inventory source that PRD
Open Question 3 left undecided. `manage.py migrate` therefore produces an empty database with
no supported path to fill it: the audited override (`CPM-FR-3`) corrects an identity but
cannot create one, and `tests/factories.py` serves automated tests only. Every downstream
story — `CPM-IDENTITY-S02` onward, and all of `CPM-EP-APP` — assumes packages exist.

**B — conda-forge cannot be the inventory source.** The stated preference was to source the
inventory from conda-forge. Ingest duration is the lesser problem. `CPM-FR-42` defines the
inventory as carrying *the internal usage signals that later rank and score it*, and a public
channel carries none: `CPM-FR-4`'s review queue ranks by internal usage breadth and
`CPM-FR-20`'s score reads the same signals. An inventory sourced from conda-forge leaves both
with no input. Its package count also exceeds `CPM-NFR-1`'s 10,000-package collection sizing
several times over, across eight rate-limited collectors.

**C — the dataset is not developer tooling.** Once the inventory is understood as *the set of
packages the organization chooses to track*, a declared watchlist is not a stand-in for a real
source. It **is** the source, and the development subset is the same artifact at a smaller
size. This reframing is what makes the change Moderate rather than Minor: it resolves Open
Question 3a, which four artifacts cite.

**Evidence.**

| Claim | Location |
|---|---|
| Only resolution creates a package row; creation is resolution | `ARCHITECTURE-SPINE.md` `CPM-AD-14`, `CPM-AD-25` |
| The sole caller is the ingestion collector | `epics.md` `CPM-IDENTITY-S06` AC 2 |
| The inventory source was undecided | PRD §10 Open Question 3 |
| The inventory carries internal usage signals | PRD `CPM-FR-42` |
| The review queue ranks by internal usage breadth | PRD `CPM-FR-4`; `epics.md` `CPM-IDENTITY-S04` |
| The score reads internal usage signals | PRD `CPM-FR-20`; `epics.md` `CPM-PRIORITY-S01` |
| Full-inventory collection is sized at 10,000 packages | PRD `CPM-NFR-1` |
| A deployed dev environment is still deployed | `src/config/locality.py` module docstring, `AD-13` |
| The override corrects but never creates | PRD `CPM-FR-3`; `CPM-AD-14` |
| The wheel ships only `src/` | `pyproject.toml:238` |

## 2. Impact Analysis

### Epic impact

| Epic | Impact |
|---|---|
| `CPM-EP-IDENTITY` | **Primary.** Gains one story. The epic's user outcome is unchanged |
| `CPM-EP-PRIORITY` | **Documentation only.** `CPM-PRIORITY-S01`'s constraint line is rewritten and gains the blank-is-not-zero rule |
| `CPM-EP-APP` | **Unblocked.** Its surfaces gain data to render locally. No text change |
| All others | No impact |

**Build order is unchanged.** No epic is added, removed, resequenced or reprioritized.
`CPM-IDENTITY-S07` sits immediately after `CPM-IDENTITY-S06`, inside an epic that already
declares `Depends on: CPM-EP-EVIDENCE`, so its dependency on the collector base
(`CPM-EVIDENCE-S05`) and the transport seam (`CPM-AD-27`) is satisfied by the existing graph.

### Story impact

**No story is renumbered.** The new story is appended as `CPM-IDENTITY-S07` and sequenced
second within its epic, immediately after `CPM-IDENTITY-S06`. Story keys are never reused, and
the TEA handoff binds P0 acceptance criteria and a risk map to existing keys; renumbering would
silently invalidate them.

`CPM-IDENTITY-S06` and `CPM-IDENTITY-S07` are a pair. S06 owns the ingestion collector, the
snapshot model and the cut-off-bound read; S07 owns the adapter contract, the watchlist files
and the selection rule. S06's acceptance criteria cannot be exercised without a source.

### Artifact conflicts

| Artifact | Change |
|---|---|
| PRD | Open Question 3 resolved (3a and 3b); `CPM-FR-42` reworded and given three consequences; §4.2 gains a surface-is-not-an-inventory rule; Appendix A.2 names the signal fields |
| Architecture spine | New `CPM-AD-29` |
| `epics.md` | Four stale OQ 3 citations corrected; new `CPM-IDENTITY-S07` |
| Story files | New `cpm-identity-s07-watchlist-inventory-source.md` |
| `sprint-status.yaml` | New entry, header comment amended, `last_updated` bumped |
| Memlogs | Decision entries in the PRD and architecture memlogs |
| PRD Appendix A.1 | **No change required.** `CPM-AD-1` already declares A.1 an export contract rather than a table definition, and already names the six usage signals as projected from `inventory_snapshots` |
| UX mockups | `docs/ux/ui-mockups.html` (added 2026-09-04 by #13, after this analysis began) cites Open Question 3 as the undecided source of its internal usage field values. One line corrected — the field set is settled; the displayed values remain invented. No screen changes: ingestion has no surface |
| TEA test artifacts | No change required. Every existing story binding survives. `CPM-IDENTITY-S07` carries no P0 scenario today |

### Technical impact

- **No new runtime dependency.** The adapter reads a delimited file from the built package.
- **No new entry point.** `CPM-EVIDENCE-S05` already provides manual recollection that
  bypasses the observation window; ingestion is a collector and inherits it.
- **No amendment to the inherited platform.** `AD-13`'s locality contract is *used* by
  `CPM-AD-29`, not changed by it. The decision to keep the deployed environment on the full
  watchlist is what makes this possible.
- **Packaging constraint.** `[tool.hatch.build.targets.wheel]` sets `only-include = [ "src" ]`,
  so the watchlist files must live under `src/`. A file at the repository root would be absent
  from the wheel and therefore from a deployed container, and `pixi run ci` would not catch it:
  the build succeeds either way.

## 3. Recommended Approach

**Selected: Option 1 — Direct Adjustment.** One story added within the existing epic
structure, plus documentation corrections where a resolved open question is still cited as
open.

- **Effort:** Low. One story; no rework of delivered code; no migration to an existing table.
- **Risk:** Low. Nothing is in flight, and the mechanism reuses two seams that already exist —
  the collector base transport boundary (`CPM-AD-27`) and the locality contract (`AD-13`).
- **Timeline:** No change. The story is inside an epic that has not started.

**Option 2 — Rollback: not viable and not needed.** Nothing has been built that this change
invalidates. `CPM-EVIDENCE-S01` and the two platform stories are delivered and untouched.

**Option 3 — MVP review: not warranted.** MVP scope is unchanged. No functional requirement is
added; `CPM-FR-42` already covered inventory ingestion and is only reworded. This change
*reduces* MVP risk by resolving the last open question blocking `CPM-EP-IDENTITY`.

**Alternatives considered and rejected.**

| Alternative | Rejected because |
|---|---|
| A standalone seeder writing packages directly | Creates a second write path onto the package table, which `CPM-AD-14` forbids. Would require an explicit spine exemption to buy convenience already available at the transport seam |
| A Django fixture loaded with `loaddata` | Bypasses resolution, writes no evidence rows, and produces packages with no provenance or confidence — inconsistent with everything downstream reads. Also a one-shot import, destroying the replay property that append-only ingestion provides |
| conda-forge as the inventory source | See §1 finding B. Recorded in the PRD so it is not revisited |
| Requiring all six usage signals | Forces hand-authored values for `downloads` and `versions` that nobody can verify — the invented content the must-not-invent table exists to prevent |
| Symmetric locality selection | A deployed component reading the development subset would record every package outside it as absent. Absence is append-only evidence that nothing may update or delete, so the error would be permanent and replayable |

## 4. Detailed Change Proposals

Twelve edits across seven artifacts: ten reviewed and approved individually on 2026-09-04, and
two (Edits 11 and 12) added during application — one because `origin/main` advanced mid-flight,
one found by a closing sweep for surviving citations. Full
before/after text for each is recorded in the approving session; the summary below is the
implementation checklist.

### 4a. PRD

**Edit 1 — §10 Open Question 3.** Resolved in place, keeping the number because downstream
artifacts cite it and this list never reuses a number. **3a:** the inventory source is a
curated watchlist, versioned in the repository and changed by review; a local subset of the
same shape is selected by locality; conda-forge is a collector surface and never an inventory
source, with the reason recorded. **3b:** `internal_component_count` and `internal_lob_count`
are required; `apps`, `platforms`, `downloads`, `versions` are nullable.

**Edit 2 — §4.1 `CPM-FR-42`.** "The organization's internal source" becomes "a declared
inventory source", with the v1 answer stated. Three consequences added: the required/nullable
split; blank means missing and never zero; a malformed record fails the whole run. The
`CPM-NFR-10` credentials obligation becomes conditional rather than absolute, so it still binds
a future system adapter.

**Edit 3 — §4.2 Description.** New paragraph, "A surface is not an inventory": none of the
eight evidence collectors introduces a package, and conda-forge in particular is observed by
`CPM-FR-9` and `CPM-FR-10` rather than ingested. Prose, not a new requirement — no `CPM-FR`
number consumed.

**Edit 4 — Appendix A.2.** The `inventory_snapshots` row names the required and nullable
signals instead of deferring to "internal usage signals as observed".

### 4b. Architecture spine

**Edit 5 — new `CPM-AD-29`,** *The inventory source is a declared adapter; locality selects
its file.* Establishes: one declared adapter behind a single contract, substituted at the
`CPM-AD-27` transport seam, never discovered (inherited `AD-8`); the versioned watchlist as
the v1 adapter, governed under `CPM-AD-14` by being reviewable; locality selection that fails
closed toward production, with the evidence-corruption consequence recorded so the asymmetry
is not later tidied away; and refuse-never-repair on malformed input (inherited `CG-3`).

### 4c. epics.md

**Edit 6 — four stale OQ 3 citations.** (a) The must-not-invent table row is reworded rather
than deleted, preserving the residual rule that the four optional signals are never estimated —
deleting it would recreate readiness finding F-2. (b) `CPM-IDENTITY-S04`'s constraint line
records that breadth always has an input. (c) `CPM-IDENTITY-S06` gains `CPM-AD-29` to its
governed-by list, and its **Constrained** paragraph becomes **Source and fields**, because it
now records an answer rather than a prohibition. (d) `CPM-PRIORITY-S01` gains the requirement
that the score function treat blank as missing, never as zero.

**Edit 7 — new story `CPM-IDENTITY-S07`,** *The watchlist is the inventory source.* Seven
acceptance criteria covering the adapter contract, record yielding, refusal of an undefined
column, refusal of malformed input, both locality branches with the three fail-closed cases
asserted separately, and an ingested development subset.

### 4d. Story files

**Edit 8 — new** `_bmad-output/implementation-artifacts/stories/cpm-identity-s07-watchlist-inventory-source.md`.
Standard layout. Two notes a developer could not derive from the other artifacts: the
`only-include = [ "src" ]` packaging constraint, and that the locality cases must be tested
with `monkeypatch.setenv`/`delenv` rather than by mocking `is_local`, since `config.locality`
reads `os.environ` at call time by design.

### 4e. sprint-status.yaml

**Edit 9.** `cpm-identity-s07-watchlist-inventory-source: ready-for-dev` placed immediately
after S06 in build order; the header comment amended to explain the second out-of-sequence
entry; `last_updated` bumped to `09-04-2026`.

### 4f. Memlogs

**Edit 10.** Decision and change entries appended to the PRD and architecture memlogs, with
`updated:` frontmatter bumped to `2026-09-04`. The fail-closed reasoning is recorded in the
architecture memlog specifically because it is the entry most likely to be needed later.

## 5. Implementation Handoff

**Scope classification: Moderate.** Backlog changes plus documentation corrections across
planning artifacts. No fundamental replan; no architectural pass required beyond the single
spine decision already drafted.

**Route to:** Product Owner / Developer.

| Responsibility | Owner |
|---|---|
| Apply Edits 1–4 to the PRD | PO |
| Apply Edit 5 to the architecture spine | PO |
| Apply Edits 6–7 to `epics.md` | PO |
| Create the story file (Edit 8) | PO |
| Apply Edits 9–10 | PO |
| Populate the production watchlist | Organization — content decision, not a story |
| Implement `CPM-IDENTITY-S07` | Developer, via `bmad-build`, after `CPM-IDENTITY-S06` |

**Success criteria.**

1. No artifact cites Open Question 3 as open.
2. `CPM-IDENTITY-S07` exists in `epics.md`, on disk, and in `sprint-status.yaml`, and no
   existing story key changed.
3. `CPM-AD-29` is referenced by both `CPM-IDENTITY-S06` and `CPM-IDENTITY-S07`.
4. On implementation: a deployed run with `COMPONENT_RUNTIME` absent, empty, or unrecognized
   reads the production watchlist, each case asserted separately.
5. On implementation: an undefined column, a missing required column, a non-numeric count, and
   a duplicate source package key each fail the run before any row is written.
6. `pixi run ci` exits 0.

## 6. Not Resolved, and Why

**The watchlist content.** Which packages are tracked, and their breadth counts, is an
organizational decision. This proposal ships the contract, the selection rule, the refusals and
a development subset. The production watchlist is populated by review.

**Open Question 8** — the priority rule set and score function — is untouched and still blocks
`CPM-EP-PRIORITY`. Edit 6d strengthens its eventual answer by requiring blank to be treated as
missing, but does not supply it.

**`solution-design.md` is stale by one change, not by this one.** The spine's reasoning
companion mentions "inventory" four times and references neither `CPM-AD-25` nor the ingestion
collector. It predates the 2026-09-02 proposal. Refreshing it is a separate follow-up, tracked
here so the omission is recorded rather than inherited silently a second time.

### 4g. UX mockups

**Edit 11 — `docs/ux/ui-mockups.html`, the "what the mockup invented" list.** The entry
reading *"The internal usage field values — components, lines of business, downloads. Their
source is Open Question 3."* now records that the field set is settled while the displayed
values remain invented, and carries the blank-is-not-zero rule.

Not part of the approved ten: `docs/ux/ui-mockups.html` was added to `origin/main` by #13 on
2026-09-04, after this analysis began and after §2's artifact table was written. It is
included because success criterion 1 requires that no artifact cite Open Question 3 as open.

### 4h. Architecture spine, Deferred section

**Edit 12 — the Deferred list entry for the inventory source.** Struck and replaced: Open
Question 3 is resolved, and what remains deferred is the watchlist *content*, an
organizational decision rather than an architectural one. Found by sweeping for surviving
"Open Question 3" citations after Edits 1-11 were applied, not during the original analysis.

**Deliberately not edited:** `_bmad-output/planning-artifacts/implementation-readiness.md`
still describes F-1 and F-2 in terms of an open Question 3. It is a dated readiness report
recording what was true on 2026-09-02, and its own Resolution status section already records
the 2026-09-02 fix. Rewriting a historical assessment to match present state would destroy
the record it exists to keep.
