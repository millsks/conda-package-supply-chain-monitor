# CPM-RENAME-S04: The repository is called conda-sentinel

Status: ready-for-dev

Epic: `CPM-EP-RENAME` — The product is called Conda-Sentinel

## Story

As the person who clones and works in this repository,
I want the repository itself to carry the product's name,
so that the last place still calling it the old thing is not the first place anybody looks.

## Acceptance Criteria

1. **Given** the GitHub repository after this story
   **When** it is fetched, browsed or linked to
   **Then** it answers as `conda-sentinel`, and links to the former name still resolve

2. **Given** the local working copy after this story
   **When** `pixi run ci` is run in the renamed directory
   **Then** it exits 0, with no path from the former directory name anywhere in the
   environment

3. **Given** the git remote after this story
   **When** `git remote -v` is read
   **Then** it names the new repository rather than relying on the redirect

## Tasks / Subtasks

- [ ] Operator-run. The steps are below rather than in `bmad-build`'s hands: this story
      changes no tracked file, and most of it cannot be done by anything running *inside*
      the working copy it is renaming.

## Dev Notes

**Satisfies:** no functional requirement — this story changes no behaviour

**Governed by:** none

**Depends on:** `CPM-RENAME-S01`, `CPM-RENAME-S02` and `CPM-RENAME-S03`. Sequenced **last**
in the epic. Renaming the working directory while the other three stories are in flight would
move every branch and worktree out from under them.

### Order

The remote rename and the local rename are independent. GitHub leaves a redirect behind, so a
local copy keeps fetching and pushing correctly against the old URL for as long as the
redirect stands. Do them in either order.

### The remote

```sh
gh repo rename conda-sentinel
```

Then, in each working copy, point the remote at the new name rather than leaning on the
redirect — a redirect is a courtesy, and it stops working the day somebody creates a new
repository under the old name:

```sh
git remote set-url origin git@github.com:millsks/conda-sentinel.git
```

Open pull requests, issues, and links already published elsewhere survive the rename.

### The local working copy

Renaming the directory **breaks the pixi environment**, because pixi writes absolute paths into
the executables it installs. At the time this story was written, 97 files under
`.pixi/envs/dev/bin` carried a hardcoded interpreter path naming the current directory; a
renamed directory leaves every one of them pointing at somewhere that no longer exists.

Remove the environment *before* the rename rather than repairing it afterwards. There is
nothing to salvage — `pixi.lock` reproduces it exactly:

```sh
pixi clean                 # removes .pixi/, and with it every baked path
cd .. && mv conda-package-supply-chain-monitor conda-sentinel && cd conda-sentinel
pixi install               # rebuilds from pixi.lock, with correct paths
pixi run ci                # proves it
```

**Do not run `pixi clean cache`.** That clears the machine-wide package cache pixi shares
across every project, so it would force a full re-download here *and* cost every other
repository on the machine its warm cache. The cache is content-addressed and carries no path
from this directory, so a rename does not invalidate it. `pixi clean` alone is the whole job.

### What else is keyed to the directory path

Anything outside the repository that remembers where the repository is will need re-pointing.
These are not tracked files and no test can catch them:

- **Claude Code project state.** Session history and the project memory directory are keyed to
  the absolute path, so a renamed directory reads as a new project and the accumulated memory
  notes are orphaned rather than lost. Move or re-point them deliberately.
- Editor and IDE workspace files, shell aliases, and any local script holding the old path.
- Any container or service on the machine that bind-mounts this directory.

### Not in scope

The distribution name and the import root. Those are `CPM-RENAME-S01`'s, and they are already
`conda_sentinel` by the time this story runs.

### Testing Standards

- `pixi` is the only Python runner.
- Acceptance criterion 2 is the whole verification: `pixi run ci` exits 0 from the renamed
  directory, in a freshly installed environment.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-RENAME-S04]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
