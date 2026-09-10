# Running it

From a fresh checkout to signed in and looking at real data, with **no external
service running** — no Postgres, no Redis, no identity provider.

## Five commands

```bash
pixi install                    # the environment
pixi run migrate                # SQLite, locally
pixi run -e dev seed-demo       # ten packages, their evidence, and a policy run
pixi run runserver              # http://localhost:8000/
```

Then open **<http://localhost:8000/>** — it redirects to `/conda-sentinel/`.

!!! warning "`-e dev` on the seeder is not optional"

    `pixi run seed-demo` refuses:

    > seed_demo_inventory writes inventory and evidence and must never run outside a
    > local run. Evidence is append-only (`CPM-AD-2`): a fictional observation cannot
    > be deleted, and every replayed policy run would read it.

    Only the dev environment declares `COMPONENT_RUNTIME=local`. The refusal is the
    product protecting an append-only log from a fixture, which is worth reading
    once.

## Signing in without an identity provider

Authentication is delegated to an OIDC provider, and you do not have one locally. The
local-dev sign-in gives you five personas instead, at
**<http://localhost:8000/local-signin/>**:

| Persona | Holds | Can reach |
|---|---|---|
| `leader-persona` | platform and engineering leadership | identity review; the identity override |
| `reviewer-persona` | security review | compliance review |
| `engineer-persona` | packaging engineering | remediation |
| `reader-persona` | no product role | nothing — the state the `IsAuthenticated` floor lets through |
| `staff-persona` | Django staff | the admin |

`reader-persona` exists to be refused. Somebody signed in and holding no role is a
real state — the zero-groups sign-in — and it is worth being able to see what they
see.

!!! note "Groups granted by hand will not survive"

    Sign-in runs `sync_authorization`, which makes the account's groups match the
    claim. A group added in the admin is erased on the next sign-in. Use a persona.

## What the seeder does, and how

It writes ten packages and **evidence** for them — release snapshots, advisories, a
KEV cross-reference, licence findings, readiness assessments, feedstock snapshots —
and then **runs a real policy pass** over them. Ten rollup rows, at the shipped policy
version.

The distinction that matters: **it writes no derived status directly.** `CPM-AD-10`
gives the application layer no write path to one, so the seeder produces evidence and
lets the passes that own each domain conclude from it. What the screens show is
something the product actually derived — not a fixture arranged to look like one.

Its own comment puts it best:

> The step that makes the seeded screens honest: every status they show is concluded
> here, by the passes that own it, from the parameter file that ships.

It goes through the real ledger too, opening a collection run before the work and
finalising it after, so the coverage screen reads the shape it would read in
production.

The ten packages are chosen to put something in every state — a KEV-listed advisory, a
licence needing review, a package behind upstream, an absent feedstock, and one
`internal-telemetry-sdk` that nothing can identify, so you can see what
<span class="cs-state unknown">unknown</span> looks like across a whole row.

!!! note "One column still comes out flat, deliberately"

    The seeder reports which, and reads it off the version it ran rather than saying
    it in prose — so this stays true as versions are added.

    `license_rules` is **empty in the shipped parameter file**, so every licence comes
    out <span class="cs-state warn">manual_review</span>. That is PRD Open Question 4
    and the file says so. Record a rule set at a new version to see the column work.

    `priority_rules` was empty too until `2026.09.4` recorded ten of them (PRD Open
    Question 8), so priority buckets and scores are real from that version on. A run
    at an *older* version still produces
    <span class="cs-state unknown">unknown</span> buckets — which is the point of
    versioning the rules rather than the code.

## Running a policy pass yourself

There is no management command for a first run — the schedule owns it in production
(`cpm.policy.run`), and the seeder does it locally. To run one by hand:

```python
# pixi run -e dev python manage.py shell
from conda_sentinel.core.clock import SystemClock
from conda_sentinel.core.policy_run import execute_policy_run
from conda_sentinel.policies.parameters import parameters_file, parameters_from

source = parameters_file()
newest = sorted(parameters_from(source.read_text(encoding="utf-8"), source=source))[-1]

execute_policy_run(policy_version=newest, clock=SystemClock())
```

**Read rather than written down**, which is what the seeder does and for the same
reason: a version pinned in prose is one that stops being the newest the day somebody
records another, and this page would then be telling you to run the old rules.

The version must be one the parameter file **records**. An unrecorded version fails
every package rather than falling back to a default — a verdict whose rules nobody
wrote down is not a verdict this product will produce.

To reproduce what a past run concluded, pass its cut-off as well; see
[Operating Conda-Sentinel](operations.md#replaying-a-run).

## Why a fresh deployment sees nothing

**Every collector ships inert.** None names an upstream, a channel, a catalogue or an
advisory source. On a real deployment nothing is observed until you declare where to
look — see [Operating Conda-Sentinel](operations.md).

The seeder exists so you do not have to do that to see the product work.

## Background work

The export of a large report, and every collector and policy run, leave the request
(`CPM-AD-9`). That needs a broker:

```bash
pixi run worker      # drains celery,collect,policy,verify,export
pixi run beat        # the schedule, which lives in the database
```

Without one, a queued job is **failed with the reason on its own page** rather than
disappearing — the row says the broker refused the connection. That is the intended
behaviour and also what you will see locally until Redis is running and authenticated.

## Reading the screens

| Screen | Path | Read it when |
|---|---|---|
| Home | `/conda-sentinel/` | you want to know how current the picture is |
| Packages | `/conda-sentinel/packages/` | you are looking a package up, or working down a ranking |
| Package detail | `/conda-sentinel/packages/<name>/` | you want to know *why* a status says that |
| Queues | `/conda-sentinel/queues/<queue>/` | you are doing the work |
| Reports | `/conda-sentinel/reports/<slug>/` | a recurring question — KEV, feedstock lag, licences |
| Coverage | `/conda-sentinel/coverage/` | you want to know what the product **cannot** see |

Start at **Coverage** on an unfamiliar deployment. It is the screen that says how much
of what you are looking at is a conclusion and how much is a gap.

## The API

Same data, same projection, under `/conda-sentinel/api/v1/`. The contract is at
`/conda-sentinel/api/v1/schema/` and a browser for it at `.../docs/` — both
admin-only, both generated from the implementation.

## When something looks wrong

| Symptom | Usually |
|---|---|
| every screen empty | no policy run has completed |
| every status `unknown` for one package | its identity is `unmapped` — check the detail screen |
| one domain `unknown` everywhere | that collector has never run, or its source is undeclared |
| one domain `error` | the upstream failed; the row says when it was tried |
| a queue refuses you | it is not your role's — see the table above |
| an export never finishes | no worker, or no broker; check the job's page |
