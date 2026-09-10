# CPM-DOCS-S05: The three subsystems with no page of their own

Status: done

Epic: `CPM-EP-DOCS` — Documentation that says which product it is about

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Asked for
> by the product owner, who asked to be taught the whole application — the components,
> the collectors, the data sources, the queues, the authorization, OIDC, Celery and
> beat. See the epic entry.

## Story

As a maintainer new to this product,
I want a page for each subsystem I have to operate,
so that I can answer a question about it without reading the source.

## Acceptance Criteria

1. **Given** a person configuring a deployment
   **When** they read the authorization page
   **Then** every environment variable the product reads for identity or roles is
   named, along with what each role reaches and what a refusal looks like

2. **Given** an operator planning a schedule
   **When** they read the asynchronous-work page
   **Then** every registered task is listed with the queue it lands on, every beat
   entry is named, and any task that nothing fires is called out as such

3. **Given** a reviewer working a queue
   **When** they read the queues page
   **Then** they can find every state transition, the role each requires, and where a
   transition is actually performed

4. **Given** somebody adding a package
   **When** they read the inventory page
   **Then** they can do it, and can say what happens to a package they remove

5. **Given** any table on any of these pages
   **When** the code it describes changes
   **Then** a test fails

## Tasks / Subtasks

- [x] `docs/conda-sentinel/authorization.md`
- [x] `docs/conda-sentinel/asynchronous-work.md`
- [x] `docs/conda-sentinel/the-queues.md`
- [x] `docs/conda-sentinel/managing-the-inventory.md`
- [x] `mkdocs.yml` nav, and `index.md`'s next steps.
- [x] `tests/unit/django_apps/test_documented_subsystems.py` — thirty cases.
- [x] `running-it.md` — a claim about the policy run that turned out to be false.

## Dev Notes

**Governed by:** nothing new. Each page distils decisions already recorded —
`CPM-AD-9` (the request boundary), `CPM-AD-13` (authorization declared per surface),
`CPM-AD-14` (one governed write path), `CPM-AD-20` (queues by workload class, cadence
as data), `CPM-AD-22` (the state machine as data), `CPM-AD-25` (inventory as evidence).

### Distil and link, never restate

`operations.md` is 2,900 lines and is the per-collector reference: what each collector
asks for, what its `User-Agent` says, what it does when rate-limited, what each refusal
means. None of that is repeated. The new pages carry the shape of each subsystem and
link into that reference for the detail.

The one table that overlaps deliberately is the collector roster on the onboarding
page (`CPM-DOCS-S06`), which is an index rather than a description.

## Dev Agent Record

### Completion Notes

**Files added:** four documentation pages and
`tests/unit/django_apps/test_documented_subsystems.py`.
**Files changed:** `mkdocs.yml`, `docs/conda-sentinel/index.md`,
`docs/conda-sentinel/running-it.md`.

### The documentation was wrong about the policy run

`running-it.md` said, of a first policy run:

> There is no management command for a first run — **the schedule owns it in
> production (`cpm.policy.run`)**, and the seeder does it locally.

It does not. Writing the task catalogue meant enumerating what beat actually fires,
and beat fires **eight sweep entries and nothing else**. `cpm.policy.run` and
`cpm.collect.inventory` are registered, routed and runnable, and nothing in the
codebase enqueues either — no schedule entry, no chained call at the end of a sweep,
no management command.

So a freshly deployed component collects evidence on schedule and never computes a
verdict from it.

That is not a defect to fix in this story — it is arguably correct, because cadence is
data: settings' eight entries are rewritten by `DatabaseScheduler` on every beat start
and are therefore a *declaration*, while an entry an operator adds in the admin lives
in the tables and survives. The intended path is a `PeriodicTask` row. But it was
**undocumented and actively contradicted**, which is the worst of the three states.

Corrected in `running-it.md`, and `asynchronous-work.md` carries the warning in full.
`test_the_two_unscheduled_tasks_are_still_unscheduled` asserts both halves — that
nothing schedules them, *and* that the page still says so — so the day a story adds a
schedule, the stale warning fails rather than sending an operator to add a duplicate.

### Two smaller corrections, both caught by writing a table

**The justification is not on the item.** A first draft of the queues page listed
`justification` among `WorkflowItem`'s fields. It is on `WorkflowTransition`, which is
a separate append-only log — one row per move, carrying the actor, the queue at the
time, and the reason. The distinction is worth the page it now gets: a `justification`
column on the item would hold only the most recent reason, and an item accepted,
reopened and accepted again would quietly lose the first.

**The rank is on neither.** The bucket and score a queue ranks by are read from the
rollup by correlated subquery at display time, so a queue ranks by what the latest
policy run thinks rather than by what was true when the item opened.

Both were found by checking a table against the model before publishing it, which is
the argument for the audit below.

### Every table is swept against its declaration

Thirty cases in `test_documented_subsystems.py`. A table is the most useful shape for a
reader and the most dangerous one to leave unchecked: prose that goes stale reads as
vague, and a stale table reads as precise and is wrong.

| Table | Swept against |
|---|---|
| The seven environment variables | `CLAIMS_ENVIRONMENT_VARIABLES` + `ROLE_ENVIRONMENT_VARIABLES` |
| The three roles | `PRODUCT_ROLES` |
| The refusal event | `REFUSAL_EVENT` |
| The thirteen tasks | every `*_TASK_NAME` constant — **both directions** |
| The four queues | `Queue` |
| The eight beat entries | `CELERY_BEAT_SCHEDULE` |
| The two unfired tasks | that they are still unfired |
| The seven transitions | `TRANSITIONS` — **both directions** |
| Queue and owning role | `QUEUE_OWNERS` |
| The eight watchlist columns | `WATCHLIST_COLUMNS` |

The task and transition sweeps run in both directions on purpose. A missing row is a
reader who plans around a machine that has a move they do not know about; an **invented**
row is worse, because a name that does not exist is one somebody puts in a
`PeriodicTask` where it fails at fire time with nothing on the page to contradict it.

The transition sweep is anchored on the reason column rather than on the first two
cells, because the queue-and-owner table two sections up has the same shape and was
being read as transitions — which is how the first version of that case failed.

### Verified by reintroducing the errors

Not trusted because it passed. One transition row was deleted from the page and one
task name changed to a non-existent one; the two matching cases failed and no others
did. Restored, and all thirty pass.

Every relative link and anchor across the whole `docs/` tree was resolved by script,
because a heading rename silently breaks a cross-reference and `mkdocs build` does not
say so at this configuration.
