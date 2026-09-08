---
title: 'CPM-RENAME-S03: The living planning artifacts name the new module'
type: 'refactor'
created: '2026-09-07'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false
baseline_revision: '770a284'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/implementation-artifacts/stories/cpm-rename-s01-import-root-becomes-conda-sentinel.md
  - _bmad-output/implementation-artifacts/stories/cpm-rename-s02-conda-sentinel-on-operator-surfaces.md
warnings: []
deferred: []
---

# CPM-RENAME-S03: The living planning artifacts name the new module

Epic: `CPM-EP-RENAME` — The product is called Conda-Sentinel

<intent-contract>

## Story

As the next person to pick up a story,
I want the documents I am told to read to name paths that exist,
so that a Code Map does not send me to a directory that is gone.

## Acceptance Criteria

1. **Given** `epics.md`, the architecture spine, the PRD and `CLAUDE.md`
   **When** they name a module path after this story
   **Then** the path is the one on disk

2. **Given** the story files of already-merged work
   **When** they are read after this story
   **Then** they are unchanged, and a recorded decision says why

## Intent

**Problem:** `CPM-RENAME-S01` moved the import root and `CPM-RENAME-S02` finished the
operator-facing surfaces. What remains under `_bmad-output/` is two different kinds of
document that a single search-and-replace would treat alike, and must not.

**Approach:** Survey first, decide, then edit the small part that needs editing. The survey is
already done and it changed the shape of this story:

- The **architecture spine and the PRD contain zero** references to the module path. Their
  contents need nothing.
- **No unstarted story stub** names the old module either — so the trap this story was written
  to prevent, a future Code Map copied from a stale one, does not exist.
- `epics.md` carries **3** module-path references, and only **one** is stale: the other two
  correctly name the former identifier because they describe the rename itself.
- Four **dated planning-artifact directories** are named for the old product, and **178
  citations across 59 files** point at them.

So the editing is small and the **decision is the deliverable**.

## Boundaries & Constraints

**Always:**
- Update `epics.md` where it names a module path **as a live path**, so the path is the one
  on disk. Leave references that name the former identifier as their *subject* — the epic
  describing the rename, and `CPM-RENAME-S01`'s acceptance criterion — because substituting
  those destroys the statement.
- Record, where a reader will meet it, why the dated directories and the merged story files
  keep the former name. A reader who finds 178 references to a name the rest of the repository
  has abandoned must be able to tell a decision from an unfinished job.
- Verify the claims this story rests on rather than trusting this spec: that the spine and the
  PRD contain no module-path reference, and that no unstarted stub does either. If either is
  false, the scope is larger than stated and the spec is what is wrong.

**Block If:**
- Correcting `epics.md` would require changing a *historical* statement — something an epic
  says about what was true when a merged story ran. Amend forward with a dated note, the way
  `CPM-RENAME-S01` and `S02` amended their own acceptance criteria; do not rewrite the past
  tense.

**Never:**
- **No renaming of the four dated planning-artifact directories** — `briefs/`, `prds/`,
  `architecture/`, `ux-designs/`. 178 citations across 59 files name them, almost all in merged
  story records this epic preserves. The date in each name marks it as a snapshot of a moment;
  renaming would make merged stories cite paths that did not exist when the work was done.
- **No rewriting of merged story files.** They record what was built, against which baseline,
  and what the reviewers found.
- No change under `src/`, `tests/`, `docs/`, or any manifest. Those are `S01` and `S02`, and
  both are merged.
- No renaming of the repository, the working directory, the Sonar identity or any GitHub URL —
  `CPM-RENAME-S04`.
- No renaming of the `CPM-` requirement prefix.
- No weakening of `tests/unit/test_former_import_root.py`. Its scope is `src/` and `tests/`,
  and this story touches neither, so it should need no change at all. If it does, that is a
  signal something is out of scope.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| A module path in `epics.md` (AC 1) | 3 references, 1 stale | the stale one names the path on disk | |
| A reference that names the former identifier *on purpose* | the epic describing the rename; S01's acceptance criterion | unchanged — it is the subject, not a stale path | Substituting it destroys the statement |
| A historical statement in `epics.md` | an epic describing what was true for a merged story | amended forward with a dated note, not rewritten | The Block If |
| The architecture spine and the PRD | surveyed as carrying zero module-path references | unchanged — and the claim re-verified, not trusted | If false, the spec is wrong |
| An unstarted story stub | surveyed as carrying none | unchanged — and re-verified | If false, they are in scope |
| The four dated directories | 178 citations across 59 files | unchanged, with the reason recorded | Never renamed |
| A merged story file (AC 2) | 27 of them | unchanged, with the reason recorded | Never rewritten |
| A reader finding the old name in `_bmad-output/` | after this story | meets a recorded decision, not a silence | The deliverable |
| The S01 guard | scoped to `src/` and `tests/` | untouched and still passing | Needing a change is a signal |

</intent-contract>

## Code Map

- `_bmad-output/planning-artifacts/epics.md` — the only file with a stale module path, at the
  platform epic's current-state list. Also where the preservation decision is recorded, because
  it is where a reader of `CPM-EP-RENAME` will meet it.
- `_bmad-output/planning-artifacts/architecture/.../ARCHITECTURE-SPINE.md`,
  `.../prds/.../prd.md` — surveyed as carrying zero module-path references. Verify, do not edit.
- `_bmad-output/implementation-artifacts/stories/*.md` — 27 merged records, left alone.
- The four dated directories under `planning-artifacts/` — left alone; 178 citations name them.

## Tasks & Acceptance

**Execution:**
- Re-verify the survey at this baseline before editing anything.
- Correct the one stale module path in `epics.md`.
- Record the preservation decision in `epics.md`, inside `CPM-EP-RENAME`.

**Acceptance Criteria:**
- Given `epics.md`, when it names a module path as a live path, then the path exists on disk.
- Given a reference that names the former identifier as its subject, when read, then it is
  unchanged.
- Given the merged story files and the four dated directories, when read, then they are
  unchanged and `epics.md` says why.
- Given `pixi run ci`, when run, then it exits 0.

## Spec Change Log

### 2026-09-07 — The survey in this spec was wrong, and re-verification caught it

The spec said `epics.md` carried **14** module-path references. Re-verified at `770a284`: it
carries **3**, and only **one** is stale. The 14 came from an earlier count that conflated the
underscored module path with the hyphenated product name, which are different things and have
different owners.

The two non-stale references name the former identifier **as their subject** — the epic
describing what the rename does, and `CPM-RENAME-S01`'s acceptance criterion naming what must be
absent. Substituting those would destroy the statements. That distinction was not in the spec
and is now in the matrix.

This is why the Always list told the implementer to verify the survey rather than trust it. The
spec was the thing that was wrong.

## Design Notes

**Why the decision is the deliverable and the edit is a footnote.** One stale path is a typo's
worth of work. The reason this is a story is that after it, `_bmad-output/` still holds 178
references to a name the rest of the repository has abandoned, and a reader has no way to tell a
deliberate preservation from a sweep that ran out of steam. Recording it in `CPM-EP-RENAME`,
where someone chasing the old name will actually look, is the part that has value in a year.

**Why dated directories are not renamed.** Each carries a date because it is a snapshot of a
moment. Renaming makes 27 merged stories cite paths that did not exist when the work was done —
the same argument that keeps the stories themselves untouched, applied one level up.

## Verification

- `pixi run ci` — expected: exit 0. This story changes no code, so the gate proves only that
  nothing was disturbed.
- `grep` for the module path across `_bmad-output/planning-artifacts/` — expected: only the two
  subject references remain.

## Dev Notes

**Satisfies:** no functional requirement — this story changes no behaviour

**Governed by:** none

**Depends on:** `CPM-RENAME-S01`, `CPM-RENAME-S02`, both merged.

### Testing Standards

- `pixi` is the only Python runner.
- `pixi run ci` must exit 0.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-RENAME-S03]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context), working directly rather than through an implementation agent: the
change is one corrected line plus a recorded decision, and dispatching would have cost more
than it caught.

### Debug Log References

Survey re-verified at `770a284` before editing: architecture spine 0 module-path references,
PRD 0, `epics.md` 3, unstarted story stubs 0. The spec's claim of 14 was wrong and is corrected
in the Spec Change Log.

### Completion Notes List

- Corrected the one stale module path in `epics.md`'s platform current-state list, and noted
  inline that the rename moved the import root and nothing else.
- Left the two references that name the former identifier as their subject.
- Recorded the preservation decision inside `CPM-EP-RENAME`, covering both the four dated
  directories and the merged story files, with the citation count that makes the case.
- Touched no file under `src/`, `tests/`, `docs/` or any manifest, and did not weaken the S01
  guard, which needed no change — as the spec predicted it should not.

### File List

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/implementation-artifacts/stories/cpm-rename-s03-planning-artifacts-name-new-module.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

## Auto Run Result

**Outcome:** done. One corrected line, one recorded decision, and a spec that was wrong about
its own scope.

**No review loop.** This story changes no code, no test and no manifest — `pixi run ci` proves
only that nothing was disturbed. The four-layer review exists to find defects in behaviour, and
there is no behaviour here. What would have justified a review is the *decision*, and that was
settled by measurement before the story started rather than by argument after it.

**The survey was the story.** The spec asserted 14 module-path references in `epics.md`.
Re-verified at the baseline: **3**, and only **one** stale. The 14 came from an earlier count
that conflated the underscored module path with the hyphenated product name — two different
things with two different owners. The Always list told the implementer to verify rather than
trust the spec, and that is what caught it.

More usefully, the survey found two things the epic had assumed were problems and are not. The
architecture spine and the PRD contain **zero** module-path references, so their contents needed
nothing. And **no unstarted story stub** names the old module — which removes the trap this
story was written to prevent, a future Code Map copied from a stale one.

**The distinction that matters, and was not in the spec.** Two of the three references name the
former identifier **as their subject**: the epic describing what the rename does, and
`CPM-RENAME-S01`'s acceptance criterion naming what must be absent. A sweep would have
substituted both and destroyed the statements. That is the same class of error S01 and S02 each
hit once — prose about a rename cannot be renamed — and it is now in the matrix.

**The decision is the deliverable.** After this epic, `_bmad-output/` still carries the former
product name in **178 citations across 59 files**: four dated planning-artifact directories and
27 merged story records. Both are preserved on purpose. Each directory carries a date because it
is a snapshot of a moment, and renaming would make merged stories cite paths that did not exist
when the work was done — the same argument that keeps the stories themselves untouched, applied
one level up.

That reasoning is now recorded inside `CPM-EP-RENAME`, where someone chasing the old name will
actually look. Without it, a reader finding 178 references to a name the rest of the repository
has abandoned has no way to tell a deliberate preservation from a sweep that ran out of steam.

**Verification:** `pixi run ci` exit 0 — 7506 passed, 2 skipped, coverage 99.17%. The S01 guard
needed no change, as the spec predicted it should not, because this story touches neither `src/`
nor `tests/`.
