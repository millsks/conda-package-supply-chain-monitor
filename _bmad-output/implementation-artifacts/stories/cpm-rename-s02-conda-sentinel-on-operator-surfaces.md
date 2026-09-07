# CPM-RENAME-S02: Conda-Sentinel on every operator-facing surface

Status: ready-for-dev

Epic: `CPM-EP-RENAME` — The product is called Conda-Sentinel

## Story

As an operator,
I want the documentation and packaging to call the product by its name,
so that what I deploy and what I read about are recognisably the same thing.

## Acceptance Criteria

1. **Given** the README, `docs/`, the packaging metadata and the workspace manifests
   **When** they are read after this story
   **Then** they name Conda-Sentinel, and no operator-facing surface uses the former name

2. **Given** an operator following the deployment documentation
   **When** they run the commands it gives
   **Then** the commands work against the renamed import root

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.

## Dev Notes

**Satisfies:** no functional requirement — this story changes no behaviour

**Governed by:** none — this story touches no architecture decision

**Depends on:** `CPM-RENAME-S01`. The commands in the deployment documentation name module
paths, so the prose cannot be correct until the paths have moved.

### What this story covers

The surfaces an operator or a newcomer actually reads: `README.md`, everything under `docs/`,
the `[project]` metadata in `pyproject.toml`, the workspace name in `pixi.toml`, and
`component.toml`. The product name is **Conda-Sentinel**; the Python distribution and import
root are `conda_sentinel`.

### The failure this story is written against

`docs/deployment.md` names module paths inside runnable commands, not only in narrative. A
rename that updates the prose and leaves a stale path in a command is worse than not renaming
at all: the surrounding text then reads as current while the command fails, and the reader has
no reason to doubt it. Every command in the documentation is to be checked as a command, not
skimmed as text.

### Not in scope

Renaming the GitHub repository, the clone URL, the local working directory, or any CI badge
pointing at them. Those are `CPM-RENAME-S04`, which is sequenced last and is operator-run.
Nothing in this story depends on that one having happened: GitHub's redirect keeps existing
links and remotes working either way.

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- `pixi run ci` must exit 0.
- Documentation that carries commands is verified by running them, not by reading them.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-RENAME-S02]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
