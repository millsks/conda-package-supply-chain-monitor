# CPM-RENAME-S04: The repository is called conda-sentinel

Status: done

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

4. **Given** every tracked file that names the repository — the README badges, `mkdocs.yml`'s
   `repo_url`, `sonar-project.properties`' `projectKey` and `projectName`, `.github/**`'s
   URLs and clone paths, `collectors/agent.py`'s `PROJECT_URL` and `pyproject.toml`'s
   commented git-cliff samples
   **When** they are read after this story
   **Then** each names `conda-sentinel`, and `pixi run ci` and `pixi run docs` both exit 0

## Tasks / Subtasks

This story has **two halves**, and they are sequenced: the operator-run rename first, the
tracked-file edits second, because every URL those files carry 404s until the repository has
actually moved.

- [ ] **Half one — operator-run** (the "The remote" and "The local working copy" sections
      below). This half cannot be done by anything running *inside* the working copy it is
      renaming, and `gh repo rename` is not a repository edit.
- [ ] **Half two — tracked files** ("The tracked files that name the repository" below). An
      ordinary code change, gated the ordinary way. Run it only after half one, and open it as
      a normal branch and PR.

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

### The tracked files that name the repository

**This half is tracked-file work, and it is sequenced after the rename above.** Not for
tidiness: every URL below resolves to the *former* repository name until `gh repo rename` has
run, so editing them first replaces working links with 404s for however long the two halves
are apart. Nothing here can be verified before the remote has moved.

`CPM-RENAME-S02` renamed the product on every operator-facing surface and left these
deliberately, because they name the **repository** rather than the product. That is why it is
this story that owns them, and why no other story will pick them up:

- **`sonar-project.properties`** — `sonar.projectKey` (`millsks_conda-package-supply-chain-monitor`),
  `sonar.projectName` and the header comment. The key and the display name move **together**:
  changing the key orphans the SonarCloud project and its history, and changing the name alone
  leaves the two out of step. If the key is changed, the README's two SonarCloud badge URLs
  carry it and must move in the same commit, and the SonarCloud project's own key needs
  renaming in its UI — a badge pointing at a key that does not exist renders broken rather
  than failing anything. If that trade is not worth taking, record the decision to keep the
  key and say so beside it; what is not acceptable is leaving it undecided.
- **`README.md`** — the CI badge and its link, and the two SonarCloud badges and their links.
- **`mkdocs.yml`** — `repo_url`, which is the doc site's "edit this page" and repository link.
- **`.github/ISSUE_TEMPLATE/config.yml`** — four `url:` entries (security advisories,
  discussions, readme, development guide).
- **`.github/workflows/release.yml`** — the clone URL and the directory it `cd`s into, and two
  changelog links in the release body.
- **`src/django_apps/conda_sentinel/collectors/agent.py`** — `PROJECT_URL`, which is emitted in
  every collector's outbound `User-Agent`. Its comment records that the distribution and the
  repository disagree until this story; that comment goes when the disagreement does.
- **`pyproject.toml`** — the two commented-out `git-cliff` sample lines that carry the URL.
- **`_bmad/*/config.yaml` and `_bmad/config.toml`** — `project_name` and the absolute output
  paths. Vendored agent tooling rather than project source; change them if the rename is to be
  invisible to the next agent session, and note that they are excluded from Sonar and ruff.
- **`.github/copilot/settings.json`** — three absolute paths naming the working directory.
  These follow the *directory* rename in the half above, not the repository rename.

**Not this story's, and specifically not to be swept up here:**

- `src/config/observability/telemetry.py`'s `DEFAULT_SERVICE_NAME`, and the `OTEL_SERVICE_NAME`
  row in `docs/observability.md` that documents it. That string names the **product**, not the
  repository, and `CPM-RENAME-S02` deliberately kept it: it is an *emitted* value, so moving it
  silently breaks every dashboard and alert keyed on the old `service.name`. **Nothing in the
  test suite pins the literal** — `tests/unit/test_telemetry.py` asserts by reference — so a
  change here passes the whole gate silently. Leave it. A story that wants the trace identity
  renamed states so and owns the migration note.
- `tests/unit/test_former_import_root.py`'s `NEAR_MISS_HYPHENATED_SPELLING`. It is a constant of
  a *former* name and is deliberately never updated; its docstring names the two live
  hyphenated survivors under `src/`, and the `PROJECT_URL` half of that becomes historical when
  this story runs. Update the prose, not the constant.
- `docs/ux/ui-mockups.html`'s three planning-artifact directory names. Those are real paths
  under `_bmad-output/` and are `CPM-RENAME-S03`'s.

### What else is keyed to the directory path

Anything outside the repository that remembers where the repository is will need re-pointing.
These are not tracked files and no test can catch them:

- **Claude Code project state.** Session history and the project memory directory are keyed to
  the absolute path, so a renamed directory reads as a new project and the accumulated memory
  notes are orphaned rather than lost. Move or re-point them deliberately.
- Editor and IDE workspace files, shell aliases, and any local script holding the old path.
- Any container or service on the machine that bind-mounts this directory.

### Not in scope

The import root, which is `CPM-RENAME-S01`'s, and the distribution name, which is
`CPM-RENAME-S02`'s — not `CPM-RENAME-S01`'s, as this section previously said. `S01` moved the
import root to `conda_sentinel` and left `[project] name` alone; its guard docstring recorded
that `S02` owned the distribution, and `S02` moved it to `conda-sentinel`. Both are done by the
time this story runs.

### Testing Standards

- `pixi` is the only Python runner.
- **Half one** is verified by acceptance criterion 2: `pixi run ci` exits 0 from the renamed
  directory, in a freshly installed environment. Nothing else can prove it.
- **Half two** is verified the ordinary way — `pixi run ci` and `pixi run docs` both exit 0 —
  plus one thing no gate covers: **open each changed URL**. Every one of them points outside
  the repository, so a wrong URL is green here and broken in a browser. The two SonarCloud
  badges are the sharpest case: they render as broken images rather than failing anything.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-RENAME-S04]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Auto Run Result

**Outcome:** done. Both halves ran — the operator half by the user, the tracked-file half here —
and `CPM-EP-RENAME` is complete.

**Half one, operator-run.** `gh repo rename conda-sentinel`, `git remote set-url`, then the
local directory move with `pixi clean` and `pixi install`. All three worked.

**The environment trap was real, and worth recording as observed rather than predicted.**
Between the directory move and `pixi clean`, **97 executables** under `.pixi/envs/dev/bin`
still carried the old absolute path on their interpreter line — `python` itself is a binary and
kept working, which is what makes the state deceptive: `pixi run python -c "import
conda_sentinel"` succeeded while the console scripts were broken. That is exactly why this
story's runbook removes the environment *before* the move rather than repairing it after. The
clean and reinstall cleared all 97.

**Half two, the tracked files.** 19 files, 35 references: the release workflow's clone URL and
two changelog links, four issue-template links, the README's CI and SonarCloud badges, the doc
site's repository link, the collector agent's `PROJECT_URL`, the packaging `git-cliff` samples,
seven BMAD configs, and three absolute paths in `.github/copilot/settings.json` that the
directory move had actively broken.

**The Sonar decision was taken, not deferred.** The key moves to `millsks_conda-sentinel` with
both badge URLs in the same commit. The cost is accepted and recorded: the project's prior
analysis history is orphaned, and the badges render broken until the key is renamed in the
SonarCloud UI — which fails nothing in CI. The story required this to be decided either way
rather than left open, and it was.

**Four passages became false the moment the repository moved.** The guard's module docstring,
its near-miss constant's comment, its separation case, and the collector's own note all said
**two** live examples under `src/` carry the former hyphenated name — one of them `PROJECT_URL`.
That one moved with the repository, so exactly one remains: `telemetry.py`'s
`DEFAULT_SERVICE_NAME`, deliberately kept because it is emitted on every span and dashboards are
keyed on it.

This is the fourth time in this epic that prose *about* a rename needed re-reading rather than
substituting, and the most consequential place for it: the guard's docstring is where a future
story would look before "finishing the job" on the trace identity and silently breaking every
dashboard keyed on the old service name.

**What still carries the former name, on purpose.** `telemetry.py`'s `DEFAULT_SERVICE_NAME`, the
guard's own near-miss fixture, and — under `_bmad-output/` — the four dated planning-artifact
directories and 27 merged story records, all recorded by `CPM-RENAME-S03`.

**Verification:** `pixi run ci` exit 0 — 7506 passed, 2 skipped, coverage 99.17%, run against
the renamed repository in a freshly installed environment. Staged by explicit path, with
`git ls-files --others --exclude-standard` confirmed empty first.
