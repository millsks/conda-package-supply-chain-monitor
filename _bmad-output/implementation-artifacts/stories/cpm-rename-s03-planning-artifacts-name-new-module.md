# CPM-RENAME-S03: The living planning artifacts name the new module

Status: ready-for-dev

Epic: `CPM-EP-RENAME` — The product is called Conda-Sentinel

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

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.

## Dev Notes

**Satisfies:** no functional requirement — this story changes no behaviour

**Governed by:** none

**Depends on:** `CPM-RENAME-S01`, for the same reason `CPM-RENAME-S02` does.

### The distinction this story turns on

Two kinds of document name module paths, and they are not the same kind of thing.

- **Living documents** are instructions to a future reader: `epics.md`, the architecture
  spine, the PRD, `CLAUDE.md`, and the story stubs of work not yet started. A stale path in
  one of these is a trap — the next story's Code Map is copied from it. These are updated.
- **Merged story files are a record.** They say what was built, against which baseline, and
  what four reviewers found. Rewriting their Code Maps would make them describe paths that did
  not exist when the work was done, and would edit the review history of shipped stories to
  say something that was never true. These are left alone.

The decision and its reasoning are recorded where a reader of an old story will meet it, so
that the mismatch reads as deliberate rather than as neglect.

### The interaction with CPM-RENAME-S01's guard

`CPM-RENAME-S01` adds a source scan that fails if the former name returns. That scan must
record the historical artifacts as **exemptions with a reason**, not skip a directory. This
repository's other audits already work that way, and an exemption a reader can see is the
difference between a decision and a hole.

### Testing Standards

- `pixi` is the only Python runner.
- `pixi run ci` must exit 0.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-RENAME-S03]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
