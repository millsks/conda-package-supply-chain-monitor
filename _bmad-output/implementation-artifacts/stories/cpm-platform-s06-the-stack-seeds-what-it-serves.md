# CPM-PLATFORM-S06: The local stack seeds the database it runs against

Status: done

Epic: `CPM-EP-PLATFORM` — The service platform

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Raised by
> the product owner reading `CPM-DOCS-S06`'s first-run sequence: `runserver` only
> starts the web server — should day one not start the whole stack? See the epic entry.

## Story

As somebody running this product for the first time,
I want one command that starts the whole thing with something in it,
so that my first look is at the product rather than at an empty database I cannot sign
in to.

## Acceptance Criteria

1. **Given** a fresh clone with Docker running
   **When** `local-stack` is started
   **Then** it finds a migrated schema rather than no tables

2. **Given** the same checkout
   **When** one seeding command is run
   **Then** the database the stack serves holds the demo inventory and the personas

3. **Given** the stack
   **When** it is restarted
   **Then** it does not seed again

4. **Given** any task that runs against the stack
   **When** it names a database
   **Then** it is the stack's, and a test fails if a later task names another

## Tasks / Subtasks

- [x] `pixi.toml` — `stack-migrate`, `stack-personas`, `stack-seed`; `local-stack`
      gains `stack-migrate` in `depends-on`.
- [x] `tests/unit/test_local_stack.py` — four cases added, four tasks swept.
- [x] `tests/unit/test_release_stage.py` — the migration roster, and the property
      behind it.
- [x] `docs/conda-sentinel/onboarding.md` — Part 1 starts the whole stack.
- [x] `docs/conda-sentinel/running-it.md` — the two-database warning, and the persona
      labelling note.

## Dev Notes

**Governed by:** `CPM-AD-2` — the reason seeding is not part of starting.

### The question was about a command; the defect was a database

The product owner asked why day one used `runserver`, which starts only the web
process. Fair on its own. Checking it turned up the real problem:

| Command | Database | Held |
|---|---|---|
| `migrate`, `seed-personas`, `seed-demo` | SQLite | 100 packages, 6 personas |
| `local-stack` | PostgreSQL :5433 | **0 packages, 0 personas** |

Measured, not inferred. The documented first-run sequence seeded one database and then
told the reader to start the other. The screens would have been empty — and because
the personas were in the other database too, there would have been **no way to sign in
and find out why**. That is the worst shape a first-run failure can take: not an error,
an absence, with no route to diagnosing it.

### Why not just fix the prose

Because the prose would then have to say "set `DATABASE_URL` on these three commands",
and a first-run instruction that asks somebody to hand-assemble an environment variable
is one they will get wrong. The tasks now carry it, which is what tasks are for.

### Seeding is not part of starting

`local-stack` migrates on its own — `depends-on` — so a fresh clone finds a schema
rather than fifty-two missing tables. It deliberately does **not** seed.

Evidence is append-only (`CPM-AD-2`). A stack that seeded on start-up would append a
second observation of every seeded fact every time somebody restarted it, which is
realistic behaviour for the seeder and absurd behaviour for a start-up step.

### The fix's own risk, and the audit for it

Four tasks now carry the same `DATABASE_URL`. **Four copies of one URL is the shape the
original defect had**, so `test_every_stack_task_names_the_same_database` sweeps all
four. A fifth task added later that seeded the wrong database would reproduce the bug
exactly, and nothing else in the suite would notice — the seeding would succeed, the
stack would start, and the screens would simply be empty.

## Dev Agent Record

### Completion Notes

**Files changed:** `pixi.toml`, `tests/unit/test_local_stack.py`,
`docs/conda-sentinel/onboarding.md`, `docs/conda-sentinel/running-it.md`.

### Verified by running it, not by reading it

`stack-seed` against the empty container database, then `local-stack`:

```
packages: 100 | health: 100 | personas: 6 | queue items: 120

- ** ---------- .> transport:   redis://localhost:6380/0
 -------------- [queues]
                .> celery   .> collect   .> export   .> policy   .> verify

/_local/          200   six personas listed
/conda-sentinel/  200
/livez            200
/readyz           200
```

One command chains `docker-up → stack-migrate → stack-personas → stack-seed`, and the
stack then serves it.

### An audit refused the fix, and it was right to

`test_the_only_tasks_that_migrate_are_the_two_the_manifest_is_supposed_to_have` holds
an **exact** set, and its argument is that a third migrating task is "either an
aggregate of the steps `component.toml` declares or an entrypoint in waiting".

`stack-migrate` is neither: it runs one step, and it is the same category as `migrate`
— a developer applying migrations locally — differing only in which database. So the
roster was widened.

Widening a roster is one line, though, and a widened roster with nothing behind it is
how a migration ends up somewhere that runs it on every boot. What actually keeps this
safe is `test_no_serving_process_migrates_directly_or_through_a_dependency`, which
walks `depends-on` outward from every task declaring `COMPONENT_PROCESS` —
`local-stack` declares none, so the one dependency that reaches a migration is not
reachable from a deployed process.

`test_every_migrating_task_is_a_local_one` was added to state the other direction: **no
task that migrates may declare itself a serving process.** The existing walk would miss
a migrating task nothing depends on but which the deployment starts by name; this one
catches it. Verified by giving `stack-migrate` a `COMPONENT_PROCESS` and watching both
fail.

### A second, smaller mismatch found while checking the first

The primer said to sign in as `operations-persona`. The sign-in page labels each row by
the persona's **key**, so the row actually reads `operations`. Measured by rendering
the page and reading the labels:

```
['staff', 'reader', 'reviewer', 'engineer', 'leader', 'operations']
```

The documentation's tables name the accounts, which is right — they are what the
database holds — so both spellings stay and the pages now say which is on screen.

### What `runserver` is still for

It remains the right tool when you are editing code and want autoreload, and the
documentation says so. What it is not is the way in: against SQLite with tasks running
inline, everything renders and a reader learns nothing about the request boundary —
no worker, no queue, and no job ever visibly *queued*.
