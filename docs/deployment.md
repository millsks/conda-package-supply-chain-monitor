# Deployment

What a deployment repository needs to know about this component, and where the
component says it.

## The two declarations

Two files describe this project, and they are not interchangeable.

**`component.toml` is the component's statement about itself.** It is `core`: it
ships in the reference application and in every component materialized from it,
so a component always has it. It carries

- `adopted_apps` — the reusable applications this component has adopted, in the
  order the settings composition applies them;
- `selected_features` — which of `celery`, `redis` and `storage` this
  combination selected;
- `[[databases]]` — per alias, whether the database is required and which
  release-stage migration steps to run before new pods serve;
- `[[processes]]` — the process group, with each process's replica count and
  replacement strategy;
- `[[admin_processes]]` — administrative processes, which are deliberately
  *outside* the process group and never declare `COMPONENT_PROCESS`.

**`accelerator.toml` is the accelerator's knowledge about all components.** It is
`machinery`: it stays in this repository and never travels. It carries feature
surfaces, input dispositions, parameter sites, presets, the closed contributable
surface and the pinned verification subset.

The rule for placing anything new:

> A rule the component must obey at **runtime or deploy time** goes in
> `component.toml`. A rule **only the materializer needs** goes in
> `accelerator.toml`.

The reason is not tidiness. `accelerator.toml` does not travel, so a runtime rule
written there is a rule a materialized component cannot read — it would be unable
to adopt a reusable app, declare an extra migration step, or state that a
database is optional, because every one of those rules lived in a file it does
not have. Conversely, a disposition or a preset written into `component.toml`
would ship a materializer concern to every component and give the accelerator two
places to look.

`tests/unit/test_component_declaration.py` enforces the split mechanically: the
top-level key set of `component.toml` must be a subset of `component`,
`adopted_apps`, `selected_features`, `databases`, `processes` and
`admin_processes`. Anything else fails the gate.

`selected_features` is the one entry that looks like an accelerator concern and
is not. The accelerator declares what each feature *is*; `component.toml`
declares which ones *this component has*, and it is the only declaration of that
present when settings are imported in both the reference application and a
materialized component.

## Process model

The component's process types are **pixi tasks**. The deployment repository
invokes them directly:

```sh
pixi run web      # gunicorn + the uvicorn worker class
pixi run worker   # the Celery worker  (only where `celery` is selected)
pixi run beat     # the Celery scheduler (only where `celery` is selected)
```

and enumerates the set with `pixi task list`, which prints each one beside its
description. **There is no Procfile, and none will be added** — a Procfile is a
file the deployment repository may not read, and it would be a second place the
process model is written. Materialized components ship no Dockerfile either, so
`pixi run <process>` against the golden base *is* the invocation path.

`web` exists in all six combinations. `worker` and `beat` exist only where
background task processing is selected, so in `pixi.toml` they sit inside paired
`# feature:celery` / `# /feature:celery` line comments and are removed with the
feature — rather than surviving into a component with no broker that the
deployment repository would then try to run.

Replica counts and replacement strategy are **not** in `pixi.toml`; a task cannot
express them. They are in `component.toml`, one `[[processes]]` entry per process
type:

| Process | Replicas | Replacement |
|---|---|---|
| `web` | the platform's to choose | `rolling` |
| `worker` | the platform's to choose | `rolling` |
| `beat` | exactly `1` | `stop-before-start` |

`beat` is the one that constrains the platform. Its schedule lives in
PostgreSQL, so it is replaceable but never duplicable: a second scheduler
double-enqueues every periodic task, and a default rolling update produces
exactly that second scheduler for the length of the overlap. The replica count
and the replacement strategy are therefore one decision, not two.

`tests/unit/test_process_model.py` reconciles the two files in **both**
directions: every process type `component.toml` names has a matching task, and
every task in the process group is named by `component.toml`. Membership in the
process group is structural — a task is in it when its `env` declares
`COMPONENT_PROCESS`, whatever the task is called.

### The two variables, and which way each one fails

A process task declares `COMPONENT_PROCESS` in its own `env` and declares **no**
`COMPONENT_RUNTIME`, thereby inheriting *deployed*. The two variables fail in
opposite directions, deliberately:

- **Locality fails closed.** An absent or unrecognized `COMPONENT_RUNTIME` means
  *deployed*, so a declaration lost between the manifest and production leaves
  every refusal armed rather than disarmed.
- **Process type fails open.** An absent `COMPONENT_PROCESS` means *not a serving
  process*. Failing it closed would make every command that ran without it a
  serving process — `pixi run migrate` included, which is a release-stage step —
  and it would then refuse on the unapplied-migrations condition and deadlock the
  release. The accepted price is that a serving process started outside the `web`
  task does not fire that refusal.

This is also why `COMPONENT_PROCESS` may not appear in any pixi activation env,
feature-scoped ones included: the golden base runs pixi, so activation env
reaches production, and one placed there would produce that deadlock on every
release.

The grace period is not the component's to state. `web`'s command encodes no
timeout and no port — `GUNICORN_CMD_ARGS` is gunicorn's own injection point for
`--bind`, worker counts and the graceful-shutdown timeout, so the deployment
repository sets them without a component-side flag.

### The deployment platform must set `DJANGO_SETTINGS_MODULE`

It is not optional, and the failure when it is missing is loud rather than
subtle. `config/asgi.py` falls back to `config.settings.local`, and stage-1
condition 1 (`_refuse_the_local_settings_module`) refuses a *deployed* process
that loaded the local settings module. So a platform that forgets the variable
gets a refusal at settings import, not a component quietly serving with
`DEBUG=True`. That is why the entrypoint's fallback is left as it is: it already
fails closed.

`pixi run serve` is **not** a process type. It is the cross-platform local ASGI
server — uvicorn directly, because gunicorn has no conda-forge win-64 build —
and it is invoked as `pixi run -e dev serve`. A deployment runs `web`.

## Reading the declaration

`config.component.load_component_declaration()` parses the file into frozen
records and refuses anything malformed with `ImproperlyConfigured`. It resolves
`component.toml` from its own location rather than from a setting, and imports no
Django settings module, because the settings composition itself is one of its
callers.

The resolution walks up from the loader module — `component/` → `config/` →
`src/` → the directory holding `component.toml`. That holds in the source tree
and in the editable install the component runs from under `pixi run`, which is
where every consumer reads it today. It does **not** hold in a non-editable
install: the wheel is built with `only-include = ["src"]` and the sdist does not
list `component.toml` either, so a component installed from a built distribution
has nothing at that path and the loader raises its ordinary missing-file refusal.
Packaging the declaration into a built distribution is Story 5.6's call — the
component is a payload there — and it is deliberately not settled here.

```python
from config.component import load_component_declaration

declaration = load_component_declaration()
declaration.selected_features  # frozenset({"celery", "redis", "storage"})
declaration.databases[0].migrate  # ("migrate --database default --noinput",)
```

Because `component.toml` is a `core` file that carries lines belonging to a
single feature — the `worker` and `beat` processes exist only where `celery` is
selected — those lines sit inside paired `# feature:celery` / `# /feature:celery`
line comments. That is the only mechanism permitted for removing part of a `core`
file, and it is what keeps the process declarations in step with the pixi tasks
in every combination — `pixi.toml` carries the matching `# feature:celery` region
around its own `worker` and `beat` tasks.

The rule for the process group is that each member declares `COMPONENT_PROCESS`
through the pixi task its `task` field names, which is what
[Process model](#process-model) above describes and what
`tests/unit/test_process_model.py` reconciles in both directions.

## Migrations are a release-stage step

**Migration runs before new pods begin serving, and no process the component
starts performs it.** No entrypoint, no serving-process task and no container
command migrates, and none will be added. That is not an oversight to be
corrected in your deployment repository by adding one — it is the contract, and
the component is built to make the omission safe.

`pixi.toml` does declare a `migrate` task, and it is not a counter-example. It is
a management command — the release stage's own invocation surface, and a
developer's — and it declares no `COMPONENT_PROCESS`, so it is not a serving
process. What the contract forbids is any path from a process that serves
requests to a migration, whether written into its command or reached through
`depends-on`; `tests/unit/test_release_stage.py` asserts both, transitively.

The reason is the race. An entrypoint that migrates runs once per replica, so a
rolling deploy of three replicas starts three concurrent `migrate` invocations
against the same database. The winner applies the schema; the losers do
something between failing loudly and half-applying a data migration. There is no
locking that makes this correct in general, so the invocation is moved to a stage
where there is exactly one of it.

### The ordering your deployment repository must implement

1. **Apply migrations.** Run each step `component.toml` declares, once per
   database, to completion. Nothing else has started.
2. **Start the new replicas.** They boot against a schema that is already
   current.
3. **Let the old replicas drain.** They leave the routing pool on their own
   terms — see [Shutdown](#shutdown).

Step 1 finishing before step 2 begins is the whole property. If your platform
runs the migration as a pre-deploy hook, it must be a *blocking* one.

### One step per database, exactly as `component.toml` declares

The steps are not inferred and must not be guessed. Each `[[databases]]` entry
carries a `migrate` list, one entry per invocation:

```toml
[[databases]]
alias = "default"
required = true
migrate = ["migrate --database default --noinput"]
```

Each step is arguments to a Django management command, so the release stage runs
it through pixi:

```sh
pixi run manage migrate --database default --noinput
```

Every step names its target alias explicitly with `--database`. A component that
adopts a reusable application bringing its own database adds an alias here with
its own step, and the release stage picks it up without any change on your side —
which only works because no step relies on `default` being implied.
`tests/unit/test_release_stage.py` asserts that each declared step is a real
management command and names the alias of the entry that declares it.

There is deliberately **no** component-side task that runs every step in
sequence. One name that migrates everything is one `depends-on` away from
becoming the entrypoint this contract exists to prevent.

### The component refuses to serve an unrecognized schema

Migration state is checked once, at process start. A serving process that finds
unapplied migrations on any configured alias raises `ImproperlyConfigured` and
does not serve — the stage-2 refusal in `src/config/startup/`, which names the
alias and the pending migrations so the message says which database was never
migrated rather than that something is pending somewhere.

This is what makes step 1 above enforceable rather than advisory: a deployment
that starts new pods without migrating gets a process that refuses to start,
which your platform surfaces as a failed rollout, instead of a process that
serves requests against a schema it does not know.

Readiness does **not** re-ask the question — see
[Readiness deliberately does not re-check migrations](#readiness-deliberately-does-not-re-check-migrations).
The two rules fit together: during the rollout every still-serving replica of the
old generation is running against a newer schema, which is precisely what
backwards-compatible migrations are for, and a readiness probe that compared
migration state would drain that entire generation at once and turn a routine
migration into an outage. Refuse at start, never re-check while serving.

### Accepted risk R-3: the refusal only fires for a declared process

The refusal applies to serving processes, and a process is a serving process only
when it declares `COMPONENT_PROCESS` — which the `web` pixi task does, and
`worker` and `beat` where `celery` is selected, and nothing else does. **A
serving process started outside those tasks does not fire the migrations
refusal.** A hand-rolled `gunicorn
config.asgi:application`, or a platform manifest that invokes the server binary
directly instead of `pixi run web`, will start against an unmigrated schema and
serve.

This is recorded as risk **R-3**, and it is accepted rather than mitigated.

Closing it would mean failing the process-type check *closed* — treating
"`COMPONENT_PROCESS` is absent" as "assume this is a serving process". That
inverts into a deadlock immediately: `pixi run migrate` is a management command
and declares no process type, so it would be treated as a serving process, refuse
on the unapplied migrations it was invoked to apply, and leave the release stage
with no way to clear a state only it could clear. The refusal would forbid the
one action that resolves it.

So the price is paid deliberately, and it is a small one, because it is bounded
by a rule you already have to follow: **start processes with `pixi run <process>`,
as [Process model](#process-model) describes.** Every process type the deployment
repository is told to start is a pixi task, that is the only invocation path the
component declares, and a process started any other way is outside the contract
in more ways than this one.

## Health endpoints

Two routes, at the root of the component, reachable with no credential:

| Path | Wire it to | Answers |
|---|---|---|
| `/livez` | the **liveness** probe | `200` with a plain-text body while the process is running |
| `/readyz` | the **readiness** probe | `200` with `{"status": "ready", …}` when the process should be routed to, `503` with `{"status": "unready", …}` when it should not |

Both accept `GET` and `HEAD`, answer `405` to anything else, and carry no-cache
headers so nothing between the probe and the process answers on its behalf.

### They are not interchangeable, and swapping them causes an outage

**Wire liveness to the liveness probe and readiness to the readiness probe, never
the reverse.** The two mean deliberately different things, and the platform's
reactions to them are deliberately different too.

`/livez` checks **nothing external**. It opens no database connection, reads no
cache, resolves no user and makes no network call. The process either answers it
or it does not, and "it does not" is the only signal a liveness probe is entitled
to act on — because the action it takes is to *kill the process*. This is why the
endpoint is so aggressively empty: a liveness check that touched the database
would turn a thirty-second database outage into every replica of every component
being restarted at once, which is the failure the split exists to prevent.

`/readyz` checks that **every required database answers**. Failing it removes the
pod from the load balancer's pool and *leaves the process alive*, which is the
correct response to a dependency being briefly unavailable: the component
degrades and then recovers on its own, instead of crash-looping.

Point the liveness probe at `/readyz` and you have built exactly the outage the
two endpoints exist to avoid — the database blinks, every replica fails its
liveness check, and the platform restarts the entire estate.

### Readiness is non-200 from process start until first contact

A process that has booted but has not yet successfully reached its databases
answers `503`. That is a deliberate property, not a startup race: a replica is
not ready because it started, it is ready because it has proved it can talk to
what it needs. The flag is per-process and lives in process memory, so a restart
does not inherit another replica's proof — and nothing about it is shared across
replicas or written to disk.

Give the readiness probe a `failureThreshold` and `initialDelaySeconds` that
tolerate this, and expect the first probe after a start to fail.

A process that has begun shutting down also answers `503`, before it looks at any
database, so that it leaves the routing pool before it finishes its in-flight
work.

### Readiness deliberately does not re-check migrations

`/readyz` opens a cursor on each required alias and issues `SELECT 1`. It does
**not** compare the migration graph against `django_migrations`, run
`migrate --check`, or ask any other question about the schema, and that is a
decision rather than an omission.

During a rolling deploy the release stage migrates *first* and new pods start
*after*, so for the length of the rollout every still-serving replica of the old
generation is running against a newer schema and sees migrations it has not
applied. That state is legitimate — it is precisely what backwards-compatible
migrations are for. A readiness check that compared migration state would report
every one of those replicas unready, drain the whole old generation at once, and
turn a routine migration into an outage.

Migration state *is* checked, once, at process start, by the startup refusal
contract. It is not re-asked on every probe.
`tests/integration/test_health.py` asserts that readiness still answers `200`
with an unapplied migration present, so this cannot regress quietly.

### Which required means what

An alias is required unless `component.toml` declares `required = false` for it
— see [The two declarations](#the-two-declarations). An alias that
`DATABASES` configures and `component.toml` does not declare at all is treated as
required and logged by name; it is never silently skipped.

The response body names every alias it asked:

```json
{"status": "ready", "databases": {"default": "ok"}}
```

### The `Host` header is the deployment repository's to get right

Platform probes commonly send the **pod IP** as the `Host` header rather than a
service name. `ALLOWED_HOSTS` is environment-driven —
`DJANGO_ALLOWED_HOSTS`, read in `config/settings/production.py` — and Django
rejects a request whose `Host` is not in it with `400`, before any view runs. A
probe that gets a `400` reads it as a failure.

So the deployment repository must do one of two things:

- set an explicit `Host` header (or `httpHeaders`) on both probes to a value
  `DJANGO_ALLOWED_HOSTS` contains; or
- include the pod IP range in `DJANGO_ALLOWED_HOSTS`.

**Do not weaken `ALLOWED_HOSTS` in the component to work around this.** A
wildcard baked into the component travels into every component materialized from
it and disables Django's host validation everywhere, in exchange for saving one
line in one manifest.

## Shutdown

On `SIGTERM` the component flips readiness first, and only then drains.

1. The process marks itself draining. `/readyz` answers `503` from that moment
   on, before it looks at any database.
2. The load balancer sees the first `503` and removes the replica from its pool,
   so no new request is routed here.
3. The server stops accepting connections, finishes the requests already in
   flight, and exits.

A Celery worker does the same thing in its own terms: it stops consuming new
messages and finishes the task it is holding.

**The component owns the ordering; the grace period value is the deployment
repository's setting.** The ordering is the half that cannot be configured from
outside — it is what stops the process finishing in-flight work while traffic is
still arriving — and it ships with the component. The two knobs that decide how
long the drain is allowed to take are yours:

| Knob | Where it lives | What it bounds |
|---|---|---|
| the platform's termination grace period | your deployment manifest (`terminationGracePeriodSeconds` on Kubernetes) | how long after `SIGTERM` the platform waits before `SIGKILL` |
| `GUNICORN_CMD_ARGS` | the process environment you set for the `web` process | gunicorn's own `--graceful-timeout`, alongside `--bind` and worker counts |

Set the platform's grace period *longer* than gunicorn's graceful timeout. The
other way round, `SIGKILL` arrives while requests are still being finished and
the drain buys nothing.

### The platform must keep probing readiness during the drain

The flip is only useful if something reads it. A readiness probe whose interval
is longer than the grace period may never run between the `SIGTERM` and the
process exiting, in which case the load balancer removes the replica because it
stopped answering rather than because it said it was draining — which is the
dropped-request window the flip exists to close. Keep `periodSeconds` well
inside the grace period, and let the load balancer deregister on the first `503`
rather than after a failure threshold, so the pool is updated once and early.

### A second `SIGTERM` is a cold shutdown, and that is your choice

Celery treats a second `SIGTERM` as a *cold* shutdown: it stops waiting for the
running task and terminates. The component neither sends that second signal nor
prevents it. Whether one is sent — and how long the platform waits before
sending it — is a deployment-repository decision, made with the same grace period
above, and it is the point at which unfinished work is deliberately abandoned.

### What the component does not decide

The grace period value, the probe interval, and the load balancer's
deregistration behaviour are all outside this repository. Nothing in
`component.toml` or `pixi.toml` states them: `component.toml` carries replica
counts and replacement strategy, `pixi.toml` carries the commands, and neither
carries a timeout. The `web` command encodes no `--graceful-timeout` and the
`worker` command encodes no flag that alters Celery's warm shutdown — no
`--pool=solo`, no `-Ofair` — because both would take the decision away from you.
`tests/unit/test_process_model.py` holds that.

## The component is a payload

A component built from this accelerator is a **payload**, not an image. It starts
from environment variables alone, runs under a UID assigned by the platform that
the image has never seen, on a read-only root filesystem, and writes nothing
outside a temporary directory. Those are properties of the *application*, and
they are what let it be built by the platform's image pipeline rather than by a
build of its own.

### Materialized components ship no Dockerfile

The buildpack and golden-base path is the default. A materialized component
carries no `Dockerfile`, no `.dockerignore` and no per-component build
definition, and that is deliberate: a component that owns its own build also owns
its own base image, and a CVE in that base becomes one pull request per component
rather than one rebuild for all of them.

A component that genuinely needs its own build is a **deliberate departure** —
something to decide, record and justify, not something to reach for because a
`Dockerfile` is the familiar shape. Nothing prevents it. What the default
prevents is acquiring one by accident.

### The four legs of the zero-writable-path claim

"Writes nothing outside a temporary directory" is not a hope about the
application's behaviour. It is four decisions, each of which removed a reason to
write somewhere:

- **Static files are collected at build and served by the application.**
  `collectstatic` runs at build time, and `whitenoise.middleware.WhiteNoiseMiddleware`
  serves what it produced through `whitenoise.storage.CompressedManifestStaticFilesStorage`.
  There is no run-time collection step, no sidecar and no shared volume — so
  `STATIC_ROOT` is read-only in a running component.
- **User media is a non-goal.** No model declares a file field and nothing is
  saved through the default storage. The `MEDIA_ROOT` and `MEDIA_URL` settings
  and the `static()` media route in `config/urls.py` are still present and are
  inert: `django.conf.urls.static.static` returns nothing whenever `DEBUG` is
  false, so a deployed component mounts no media route at all. Removing the
  surface belongs to the object-storage work; until then its inertness is
  asserted rather than assumed.
- **Logs go to the event stream.** Structured JSON on stdout. No files, no
  rotation, no log directory, and nothing for the platform to mount.
- **Sessions are database-backed.** Not file-backed and not local: a session
  written to disk is per-replica, so a user's session would depend on which
  replica answered — which is the statelessness requirement lost through the one
  setting nobody looks at.

Each leg is asserted rather than asserted-about. `tests/unit/test_payload_properties.py`
holds the static half; `tests/integration/test_image_payload.py` builds the image,
runs it under `--user 12345:0 --read-only --tmpfs /tmp`, and requires that
`docker diff` on a *writable* run reports no changed path outside the temporary
directory.

### Running under an arbitrary UID

A platform that assigns UIDs gives the container a numeric identity that appears
nowhere in the image and has no `/etc/passwd` entry. Two things make that work,
and both are properties an image has to arrange in advance:

- **Group 0 has the owner's permissions on the application tree.** The assigned
  UID is placed in group 0, which is the only group membership such a platform
  guarantees, so access is granted through the group rather than through an
  ownership the image could not have predicted.
- **`HOME` points at the temporary directory.** With no passwd entry, `getpwuid`
  fails and everything resolving `$HOME` falls back to `/`, which is read-only.
  The failure surfaces as a permission error from whichever tool asked first,
  with nothing in the message about UIDs or filesystems.

### This repository's `Dockerfile` is machinery

There is a `Dockerfile` at the root of *this* repository. It is `machinery`: it
does not travel, it is not the deployment artefact, and nothing here pushes it
anywhere. It exists so the harness can *run* the payload properties instead of
believing them — build the image, start it under an arbitrary UID on a read-only
root filesystem, and check that it serves and writes nothing.

Its `CMD` is `pixi run web`, which is the same invocation a deployment repository
makes, so the image and the process model cannot declare two different things.
It applies no migrations at any depth: migration is a release-stage step, as
[Migrations are a release-stage step](#migrations-are-a-release-stage-step)
records.

One component shape inherits it. "Use this template" produces a **fork of this
base**, not a generated component, and that fork carries the machinery — the
materializer, `accelerator.toml` and this `Dockerfile` — so it *can* opt out of
the image pipeline where a materialized component cannot. That is a named
governed exception rather than an oversight, and it is accepted rather than
mitigated.

### What this does not deliver

This is the component-side half, and only that half. Nothing in this repository
starts a component on a platform.

The deployment configuration — manifests, the image pipeline itself, the golden
base image, the buildpack, replica counts as applied, probe intervals, grace
periods, secrets and their rotation — lives in a **separate repository** and is an
explicit non-goal here. This repository states what the component is and what it
needs; the deployment repository decides how it runs.

## Session and epoch pruning

**Sessions are database-backed in every combination, and you schedule the process
that prunes them.** `SESSION_ENGINE` is set explicitly in
`src/config/settings/base.py` to `django.contrib.sessions.backends.db`. It is set
there and nowhere else, outside every feature-owned region, so it is identical in
all six combinations — including the two that ship no Redis.

That explicitness is the point rather than the value. Django's own default is the
same string, so the line changes nothing today; what it removes is the component's
dependence on a default. A session engine nobody states is one a Django release
note can move and one a feature's settings fragment can quietly redefine — and a
cache-backed engine is per-replica wherever the cache is Django's in-process
backend, which is two of the six combinations. A user would then stay signed in
or not depending on which replica answered.

### One admin process prunes both tables

Two tables accumulate rows that stop mattering at a moment written into the row
itself: `django_session`, and the mapper's epoch table, which records the first
sighting of each credential. Nothing in the component removes a dead row from
either.

The component declares one admin process that removes both:

```
pixi run prune            # delete every expired session row and epoch record
pixi run prune --dry-run  # report what would be deleted, and delete nothing
```

It is idempotent and safe to run beside serving traffic, with one qualification
worth stating plainly rather than as "nothing is locked". Each leg issues a single
unbounded `DELETE ... WHERE <expiry> < cutoff` — no `LIMIT`, no chunking — so
PostgreSQL takes a row lock on every row that statement removes and holds it until
the statement ends. What it does **not** take is a table lock, and nothing here
truncates; and no row a live request is using is locked, because the predicate is
expiry and a live session's `expire_date` cannot satisfy it. Your serving traffic
is untouched by the locks.

It is still one statement, and that is the part to plan for. A **first** run
against a table nobody has pruned in months is a single large `DELETE`: it can
exceed the `statement_timeout` your platform or your connection sets and roll back
having made no progress at all — then do the same thing, at the same cost, the
next night. Size it with `--dry-run` before you schedule it, and if the count is
large, raise `statement_timeout` for that one job to get through the backlog.
Every run after it is small.

A second run a second later removes nothing and says so. Both events are still
written, each carrying zero, so a run with nothing to do is visible to your
alerting rather than indistinguishable from a job that stopped being scheduled.

Each run writes one structured event per kind with the row count, on the same
event stream as everything else; nothing in it is a session key or a token
identifier, and neither is the human-facing line on stdout.

The two legs are independent statements in autocommit — there is no transaction
around them, and that is deliberate. If the epoch leg fails after the session leg
has committed, the run exits non-zero **and** the session rows it already removed
stay removed, with `prune.sessions_pruned` already on the stream carrying its
count. Nothing has to be reconciled by hand: fix the cause and run it again. The
command is idempotent, so the re-run takes whatever expired in the meantime and
finishes the epoch leg.

### One residue this process does not remove

An epoch row whose `expires_at` is `NULL` is pruned by nothing, ever. That is
correct rather than an oversight, and it is stated here so you do not schedule
this job believing it bounds both tables without qualification.

The mapper writes `NULL` whenever the token it recorded carried no readable `exp`
— a missing claim, or one the platform cannot represent — and a null expiry means
the credential's end is unknown. Removing such a row by expiry would re-sync a
credential that may still be live, which is the failure the predicate is shaped to
avoid; `<` excludes `NULL` in SQL, which is how the exclusion is enforced.

So: `django_session` is bounded by this process without qualification, and the
epoch table is bounded only for the rows whose expiry was readable. If your IdP
issues tokens with no `exp`, those rows accumulate and nothing here will remove
them. Removing them needs a policy — an age cutoff, or a rule tying the row to
whether the identity still exists — and this repository does not take one, because
a wrong age deletes the record of a live credential. If it matters for your
estate, it is a decision to make in your repository with your IdP's behaviour in
front of you.

**It is deliberately not a background task, and that is not a preference.**
Background task processing exists in only two of the six combinations. A Celery
beat entry would therefore prune nothing at all in the other four, and those four
are precisely the deployments with no worker fleet to notice — the session table
would grow without bound while a scheduled job that does not exist reported
nothing wrong.

### The schedule is yours; the process is the component's

The component declares that the process exists and what it is called, in
`component.toml`:

```toml
[[admin_processes]]
name = "prune"
task = "prune"
schedule = "deployment-repository"
```

`schedule = "deployment-repository"` is the whole of the schedule the component
states. **Pick the cadence yourself** — daily is ample for most estates — and run
it the way your platform runs one-off jobs. Do not add a cron expression or an
interval to `component.toml`; nothing reads one, and a cadence written into the
component is a cadence that ships to every deployment whatever its traffic.

**What the job needs in its environment.** The same configuration a serving
process gets. `pixi run prune` is a Django management command, so it imports the
settings module before it does anything at all: it needs
`DJANGO_SETTINGS_MODULE`, the database URL, and every variable the startup
refusals require. A one-off job given a trimmed-down environment does not run a
smaller version of the work — it refuses at import.

The failure mode is worth knowing by sight, because it names the wrong thing.
`prune_expired_state` is an *application* command, contributed by an installed
app, so Django's management utility can only see it once the settings import
succeeds. When they do not import, the utility falls back to listing the commands
it ships with, and the job reports:

```
Unknown command: 'prune_expired_state'
Type 'manage.py help' for usage.
```

That is a misconfigured environment. It is not a missing command, not a wrong task
name and not a component that failed to ship the process — so check
`DJANGO_SETTINGS_MODULE` and the variables the settings module reads before you go
looking for anything else.

This is a phase boundary rather than an omission. The explicit engine is phase-1
and is delivered here; the *scheduling* half of the requirement is marked **Next**
and belongs to your repository in the same way the grace period, the probe
interval and the replica counts as applied do.

The `prune` task declares no `env` table at all, and both halves of that matter to
you. It sets no `COMPONENT_PROCESS`, because an admin process is not a serving
process: one that said it was would fire the serving-process refusals — the
unapplied-migrations one included — on the very maintenance it was invoked to do.
And it sets no `COMPONENT_RUNTIME`, because locality is declared by the
environment your platform supplies, never by a task.

### What this section does not change

Session *cookie* hardening is unchanged by any of the above and lives where it
already did, in `src/config/settings/production.py`: `SESSION_COOKIE_SECURE = True`
and `SESSION_COOKIE_NAME = "__Secure-sessionid"`. Those govern how the session
cookie travels; the engine governs where the session is stored. They are named
here only so you do not go looking for them somewhere else.

`tests/unit/test_session_settings.py` holds the engine — set in `base.py`, set
exactly once, set in no other settings module, and inside no feature-owned region.
`tests/unit/test_process_model.py` holds the declaration: every declared admin
process names a task `pixi.toml` actually has, in the root `[tasks]` table rather
than under a feature or a platform; that task's command names a management command
Django actually has, so the `Unknown command` above cannot be reached by a typo
that got through review; and no admin process runs a task that declares a process
type. `tests/integration/test_prune_command.py` holds the behaviour against a real
database, including the two boundaries a review will not catch — an epoch record
whose expiry was never readable is *not* prunable by expiry and survives, and one
whose token is still inside the configured clock-skew leeway survives too, because
the Bearer path would still accept it.

## The inventory watchlist ships unpopulated

The inventory source is a reviewed CSV file the component ships
(`CPM-AD-29`), and which file it reads is selected by locality:
`COMPONENT_RUNTIME=local` reads `watchlist-development.csv` and **everything
else** — absent, empty, or a value like `dev` — reads `watchlist.csv`. Selection
fails closed toward production for the same reason locality itself does: a
deployed component that read the development subset would find every package
outside that subset missing and record each one as *absent*, permanently, in an
append-only log nothing may correct.

`watchlist.csv` ships with its header and **no rows**. Which packages your
organization tracks is your decision, not this component's, so nothing is
invented for you. The consequence to plan for: **inventory ingestion fails on
every run until that file is reviewed in.** The task raises an
`ImproperlyConfigured` naming the file, the run's ledger row finalizes `failed`,
and no package and no snapshot is written.

That failure is the intended behaviour rather than a gap. An inventory naming
nothing is indistinguishable from a source that has broken, and a sweep that
accepted one would record every package the inventory has ever named as departed.
A loud failure on day one is the alternative to a silently corrupted evidence log.

Populate it by pull request. The column contract, the bounds and the editing
rules are documented beside the files, in
`src/django_apps/conda_package_supply_chain_monitor/collectors/data/README.md`.
Both files ship inside the wheel, under
`conda_package_supply_chain_monitor/collectors/data/`;
`tests/integration/test_import_resolution.py` asserts that against the built
artifact, because a build that dropped them fails nowhere else until the first
deployed sweep.

## The upstream-release collector reads GitHub unauthenticated

`cpm.collect.source_release` observes a package's own source repository
(`CPM-FR-7`) by asking GitHub's API for one page of its releases. It sends **no
credential**, and its declared allowance says so: sixty requests an hour, which
is GitHub's documented limit for unauthenticated requests, counted per source IP
rather than per component.

Two consequences to plan for.

**The allowance is spent in requests, not collections.** The collector base
charges `1 + retries` against the allowance before each call, because that is how
many requests the mounted retry policy may issue — so sixty an hour is fifteen
packages an hour on the declared retry count. That is enough to observe a small
inventory and is **not** enough to sweep the ten thousand packages `CPM-NFR-1`
sizes for. **The full-inventory sweep below now schedules it daily**, so the
arithmetic is live rather than latent: a sweep of an inventory this allowance
cannot drain records `skipped` dispatch rows and `error` collection rows rather
than exceeding GitHub's budget. Raising it means authenticating, which is recorded
as deferred work.

**A repository that publishes no releases costs a second call.** `CPM-FR-7` asks
for the latest release *or tag*, and many projects tag without ever publishing a
GitHub Release — so an empty release list falls back to the repository's tags. The
fallback fires only then, and it is **not** charged against the local allowance:
the base charges `1 + retries` once, before the first call, so a repository on the
tag path spends more of the *remote* budget than the local counter believes. That
matters only at sweep volume, which nothing reaches yet.

**A spent allowance is recorded, never queued.** The call is refused rather than
waited on — a worker blocked on a limiter holds a slot doing nothing against the
inherited Celery limits — and the refusal writes an evidence row carrying `error`
and finalizes the run `failed`. It is visible in the ledger and in the log line
`collection.refused_by_rate_limit`, which carries the collector, the package and
the locator.

**Telling "we never got to look" from "the source is failing" is `detail`'s job,
not the state's.** Both are `error` rows, deliberately: `OutcomeState` says what
may be claimed about a package, not why a run went the way it did. The row's
`detail` — the same string the ledger row carries — is what separates them. A
refusal names the allowance and the window it was spent in; a transport failure
carries the exception's type and message; a document that could not be read names
the locator and what was wrong with it.

One thing the local counter cannot currently see: GitHub signals an exhausted
anonymous quota with a `403`, which this product's transport reads as an ordinary
failure. So a remote refusal produces an `error` row that looks like any other,
and the local allowance keeps granting until its own window turns over.

**A `not_found` row means "absent **or** unreadable" while no credential is
configured.** GitHub answers `404` identically for a repository that is absent,
one that is private, one that has moved and one that is blocked — by design, so an
unauthenticated reader cannot enumerate private repositories. This collector
cannot tell them apart, so it records `not_found` (which is what the source said)
and writes the caveat into the row's `detail`. Do not read these rows as proof a
repository is gone; a private mirror or a moved upstream produces the same row.

Raising the real allowance, and resolving that ambiguity, both mean authenticating
— which needs a credential, a setting to carry it and a declared header to send it
in. None of the three exists yet; when they do, the allowance declaration moves
with them, because the number and the credential are one decision.

## The PyPI collector reads pypi.org unauthenticated, and asks only about Python packages

`cpm.collect.pypi_release` observes a package's PyPI project (`CPM-FR-8`) by
asking `https://pypi.org/pypi/<name>/json` for the one document that carries the
latest version, its upload dates and `Requires-Python`. It sends **no credential**
— PyPI's JSON API takes none — and its declared allowance is **sixty requests a
minute**.

**The allowance is a declared courtesy bound, not a number the source stated.**
PyPI publishes no numeric ceiling for this API; its guidance is to send an
identifying `User-Agent`, to cache, and to be reasonable. Sixty a minute is one
request a second, which at `1 + retries` per collection is fifteen packages a
minute — written down so it is a limit the base enforces rather than an allowance
that is unlimited by omission, and so an operator can see what "reasonable" was
taken to mean. The response cache is live for this collector: PyPI serves an
`ETag`, so a scheduled recollection revalidates a document that can run to several
mebibytes rather than transferring it again.

**Whether a package is asked about at all is read from its identity, never
guessed.** A package is asked about on PyPI only when resolution recorded its
`release_ecosystem` mapping as `established` with `primary_type = "pypi"`, and the
project name comes from `primary_purl` — PEP 503-normalised, so `Zope.Interface`
and `zope-interface` are one project — never from the canonical name. Nothing
infers "this is a Python package" from how a package is spelled.

**A `not_applicable` row is an observation, and it is what keeps a non-Python
package from reading stale against PyPI.** When resolution recorded the mapping as
`not_applicable`, or established it for some other ecosystem, the collector says
so before any locator is built and the base writes a row carrying
`not_applicable`: no call is made, no allowance is spent, no cache is read, and
the run is `succeeded` with the reason as its `detail`. The row carries this run's
`observed_at`, so the freshness read reports it fresh like any other observation
— `CPM-FR-8`'s "never marked stale against PyPI merely for not being published
there". It is visible in the log line `collection.not_applicable`, whose `source`
is empty because no locator exists on that path. The observation window applies to
it as to every other run, so a sweep does not write the same true fact for one
package more than once per window.

**A package whose release-ecosystem identity is not established fails the run
rather than being guessed at.** A mapping that is `unknown`, `not_found` or
`error` — or a package with no mapping row — cannot be turned into a PyPI
question, and is not the same as "does not apply": the ledger row is `failed`
carrying the reason and no evidence row is written. The same goes for an identity
that records the mapping as `established` with a blank primary type: that is an
inconsistent identity row, and it is refused rather than recorded as either kind of
observation. Until the full-inventory sweep selects only askable packages, expect
such `failed` runs for any package a resolver has not reached; they are a reporting
fact about identity, not about PyPI.

**A `not_found` row means what it says.** PyPI is a public index with no private
projects for an unauthenticated reader to be shut out of, so a `404` is a project
that does not exist or has never released — unlike the GitHub collector above,
this row carries no caveat.

## The feedstock collector reads conda-forge unauthenticated, and asks one of two questions

`cpm.collect.feedstock` observes whether conda-forge has a feedstock for a
package (`CPM-FR-9`). It sends **no credential**, and its declared allowance is
**ten requests a minute**.

**The declared allowance is GitHub's *search* allowance, and that is deliberate.**
One of the two questions this collector asks is a search of the staged-recipes
queue (`GET /search/issues`), which GitHub limits to ten a minute for an
unauthenticated caller — far below the sixty an hour its core API allows, but
counted per minute rather than per hour. The collector base charges one allowance
before it knows which question a package will produce, so a single number has to
cover both, and the tighter of the two is the only one that cannot be exceeded by
accident. At `1 + retries` per collection that is two packages a minute, which is
**not** a rate that sweeps `CPM-NFR-1`'s ten thousand packages. **The
full-inventory sweep below now schedules it weekly**, so the arithmetic is live:
expect `skipped` dispatch rows and `error` collection rows at that scale rather
than a sweep that quietly exceeds GitHub's search budget.

**Which question is asked is read from the package's identity, before any call is
made.**

- A package whose `feedstock` mapping resolution recorded as `established` **with
  feedstock rows** is asked about that feedstock's repository, and then about its
  recipe. Two calls.
- A package whose mapping is `established` with **no** rows, or is `not_found` —
  both of which mean resolution looked and found none — is asked about the
  staged-recipes queue, and then about the conventional `conda-forge/<name>-feedstock`
  repository. Two calls.
- A package whose mapping resolution recorded as `not_applicable` is asked
  nothing at all: the base writes a `not_applicable` row with no call made, no
  allowance spent and no cache read, and the run is `succeeded` with the reason as
  its `detail`.

**The second call on each branch is not charged against the local allowance.** The
base charges `1 + retries` once, before the first call, so every package spends
more of the *remote* budget than the local counter believes — the same gap the
upstream-release collector's tag fallback has, and it matters only at sweep
volume, which nothing reaches yet. The second call is also outside the retry
policy: a failure of it is recorded in the row's `detail` and never fails the
collection, because the first call has already established the fact the row's
`state` claims.

**A `not_found` row does not prove the same thing on both branches, and it does
not always prove absence at all — the row's `detail` is what says which.** On the
mapped branch it means "the feedstock a resolver established for this package is
absent from conda-forge", a statement about identity as much as about the channel,
and the `detail` names that feedstock. On the absent branch it means resolution
established none, and the `detail` then says one of four things: that the
conventional repository is absent too (the only reading that is evidence of
absence); that the conventional repository could not be *read*, so nobody found
out; that the staged-recipes queue itself could not be read and no repository was
checked at all; or that the queue held more results than one page and whether one
of them names this package is not established. Read the `detail`, not the state,
before treating a row as proof that conda-forge has nothing. And none of them is a
claim about *any* possible feedstock under some other name: this collector asks
about the feedstock resolution named, or the conventional one, and about nothing
else.

**A staged recipe is recorded only on a row that says there is no feedstock**, and
the database enforces it (`staged_recipe_only_when_absent`). That is `CPM-FR-9`'s
"staged-recipe state is recorded separately from an existing feedstock" as a rule
rather than a convention. Two open pull requests naming one package produce a row
with **no** staged-recipe URL and a `detail` saying how many matched: which one
would create the feedstock is not a question this collector answers by picking.

**The recipe version is read, never rendered.** A conda-forge recipe is a Jinja
template, and this collector reads the `{% set version = "..." %}` assignment
conda-forge's own recipes open with, falling back to a literal `version:` under
`package:`. A recipe that computes its version any other way records the feedstock
as **present** — which is what the row's `state` claims — with `recipe_version`
blank and `detail` saying it could not be read. Nothing renders a template, so no
recipe-authored code runs in a worker. Recipes are read from
`raw.githubusercontent.com`, which is a second host and has limits of its own that
this product's counter does not see.

**A mapping that holds several feedstocks has only the first by name observed.**
`CPM-FR-1` resolves "zero or more" feedstocks, and this collector asks about one
per collection: the first in name order, so which one a package's history is
about does not depend on which resolver wrote its rows first. The row's `detail`
names how many there were. Nothing about the others is recorded, and a reader
must not treat one row as covering a package's whole feedstock mapping.

**The local counter cannot see a remote refusal, and there are two of them here.**
GitHub signals an exhausted anonymous quota with a `403`, and its search endpoint
applies a *secondary* rate limit that also arrives as a `403`; this product's
transport reads both as ordinary failures. So a remote refusal produces an `error`
row that looks like any other, and the local allowance keeps granting until its own
window turns over. The search endpoint is the one to watch: its limit is the
tightest thing this collector touches, and the secondary limit fires on burst
rather than on rate.

**Egress must be open to two hosts.** `api.github.com` for the repository and the
staged-recipes search, and `raw.githubusercontent.com` for the recipe. A network
policy that allowed only the first would leave every determinate row carrying a
blank `recipe_version` with "the recipe's version could not be read" in `detail` --
a quiet, permanent degradation rather than a failure anything reports.

**A determinate row found on the absent branch carries no recipe facts.** When
resolution established no feedstock and the conventional repository turns out to
exist, the row is `ok` and names that feedstock — but the recipe is not read, so
`recipe_version`, `recipe_build_number` and `recipe_metadata_url` are all blank
and `detail` says the recipe was not read on that branch. Both calls a collection
may make were already spent, and reading the recipe would make it three. The next
run reaches the recipe once resolution has been corrected to name the feedstock
this run found.

**Recipe activity is the feedstock's last push, and it is an instant rather than a
verdict.** `last_recipe_activity_at` is what the repository stated; whether a gap
makes a feedstock "unmaintained" is a policy with a versioned threshold
(`CPM-FR-40`), and no such threshold exists yet.

**A package whose feedstock identity is unresolved fails the run rather than being
recorded absent.** A mapping that is `unknown` or `error` — or a package with no
mapping row — cannot be turned into a feedstock question, and recording it as
`not_found` would be exactly what `CPM-UJ-2` forbids: claiming absence of a
feedstock for a package whose identity nobody has resolved. The ledger row is
`failed` carrying the reason and no evidence row is written. The same goes for a
stored feedstock name that is not a repository segment. Until the full-inventory
sweep selects only askable packages, expect such `failed` runs for any package a
resolver has not reached; they are a reporting fact about identity, not about
conda-forge.

## The published-package collector observes nothing until you declare channels and platforms

`cpm.collect.conda_package` observes what each monitored conda channel actually
publishes for a package (`CPM-FR-10`) — the version the channel states as latest,
the build string and the build number — by asking `api.anaconda.org` for one
package document per channel. It sends **no credential**, and its declared
allowance is **thirty requests a minute**.

**It ships monitoring nothing, and that is the intended behaviour rather than a
gap.** Two settings decide what it observes:

```python
# config/settings/base.py
CPM_MONITORED_CHANNELS: tuple[str, ...] = ()
CPM_MONITORED_PLATFORMS: tuple[str, ...] = ()
```

Both ship **empty**. Which conda channels and which platforms this product
watches is PRD Open Question 4 and is unresolved: a component that picked one for
you would record facts about a surface nobody chose, permanently, in an
append-only log nothing may correct — the same trade the inventory watchlist
makes above, and for the same reason.

**What the failure looks like until you declare them.** Every collection fails.
The task raises a `CondaChannelError` naming the setting, the run's ledger row
finalizes `failed` carrying that message, and **no evidence row is written at
all** — there is nothing honest to write, because every row must name the channel
and platform it is about and an empty declaration names neither. A component in
this state starts, serves and reports normally; it simply records no conda
package evidence.

**Declare them by pull request**, in `config/settings/base.py`, beside the
watchlist that ships unpopulated for the same reason. Each entry is a single
lower-case path segment: a channel is the segment `api.anaconda.org` serves a
package under (`conda-forge`, `bioconda`, an internal mirror's name), and a
platform is a conda subdir (`linux-64`, `osx-arm64`, `win-64`, `noarch`). The
declaration is read at **run** time, so a change takes effect on the next
collection.

**A declaration is refused whole rather than read for the entries that parse.** An
entry that is blank, is not a string, carries a path separator, or repeats another
entry once lower-cased fails the run naming the entry and its position. So does a
bare string where a list was expected — `CPM_MONITORED_CHANNELS = "conda-forge"`
is eleven one-character channels to Python and is refused rather than misread.

**At most four channels.** Every channel costs a full, *retried* call — this
component's HTTP retry policy is mounted on the session, so it applies to every
request the collector issues — and the inherited soft time limit is sixty seconds
(`CPM-AD-9`); a declaration whose worst case exceeds it is a task the platform
kills before it writes anything. Four channels, a 2.5-second per-phase timeout and
a retry budget of one come to forty seconds. Platforms are not bounded: a platform
costs a row rather than a call.

**Platform names are checked against conda's own subdir vocabulary.** `linux_64`
or `osx-arm-64` is refused at the declaration rather than observed: a subdir that
does not exist would otherwise record, for every package and for ever, that a
channel's latest version has no file on it — a false statement about the channel
that nothing may correct and nothing could tell from a true one. The refusal names
the permitted set.

**One row per `(channel, platform)`, always, and channels are never merged.** That
is `CPM-FR-10`'s acceptance criterion and the database enforces it
(`conda_package_names_channel_and_platform`): every row names both, sentinel rows
included. Two channels and two platforms is four rows from one run. A pair with
nothing published is a written `not_found` row carrying that run's instant, never
a missing one — which is the whole point, because "installable on `linux-64` but
not on `osx-arm64`" is only visible if the absence is recorded.

**One channel failing never discards another channel's answer.** The channels
after the first are read by bounded calls from inside the translation step: a
transport failure, an unreadable document, or a `304` to a request that carried no
validator becomes `error` rows for *that channel's* pairs, beside the rows the
channels that answered earned, and the run is still `succeeded`. That is
`CPM-FR-15`'s partial success on the per-package path. Read the row's `detail`
before treating an `error` row as a statement about the channel: it says whether
the channel answered or whether this run failed to find out.

**A `not_found` row means one of four things and `detail` says which.** The
channel does not serve the package at all — read from the channel's own `404`,
whether that channel was the one the base asked or one the run asked afterwards;
it serves the package but states no latest version at all; or it states one whose
files do not include this platform, in which case `detail` names the version that
exists elsewhere. None of them is a claim that the package is absent from conda
generally: this collector asks only the channels you declared.

**The recorded version is what the channel calls latest, not what `conda install`
resolves to.** anaconda.org's `latest_version` spans every label, so a package
whose newest upload is a release candidate on a `dev` or `rc` label records that
candidate — while a default install resolves to something older. That is
deliberate: `CPM-FR-10` asks for the version the channel states, and substituting
a different question would answer something nobody asked. What the row does is say
so: when the file it observed is served under labels that do not include `main`,
`detail` names them. Read it before comparing a published version against
anything.

**A build string is a choice where a platform carries several builds.** The
recorded one is the greatest by build number, ties broken by the greatest build
string, and `detail` says how many there were. Do not read the column as the only
build of that version on that platform.

**A channel that does not serve the package never stops the others being
asked.** The first declared channel is asked by the collector base and the rest
from inside the run, and a `404` from that first one is an ordinary answer: every
remaining channel is still asked and every pair still gets its row, so a package
absent from `conda-forge` and published on your internal mirror records both. The
declaration's order therefore does not change what is observed.

**A run that fails outright records `error` for every pair and calls nothing
further.** If the first channel is unreachable, serves a document that cannot be
read, or the local allowance refuses the call, the run is `failed` and each
monitored pair gets an `error` row carrying the reason. No further channel is
called, deliberately: the allowance may be exactly what refused the first call,
and issuing more would defeat it. Retry the run rather than reading those rows as
statements about the channels.

**Only the first channel's call is charged against the local allowance, and only
its answer is cached.** The base charges `1 + retries` once, before the first
call, so every package spends more of the *remote* budget than the local counter
believes — the same gap the upstream-release and feedstock collectors carry, and
it matters only at sweep volume, which nothing reaches yet. The response cache is
the base's too, and it covers that same one call: channels two onward carry no
validator and remember nothing, so **they re-transfer their whole document on
every run**, and a `304` from one of them is a source answering a question nobody
asked, which the row records as `error`. Both are recorded as deferred work on
`CPM-CURRENCY-S04`. **The full-inventory sweep below now schedules this collector
daily** -- but its selection is empty until the two settings above are declared,
so an undeclared component sweeps nothing rather than failing every package. See
"Which packages a sweep offers".

**A misconfiguration and a transient failure leave this task the same way.** An
undeclared channel raises out of `cpm.collect.conda_package` like any other
error, and Celery cannot tell a permanent refusal from something a retry would
fix — so under a retry policy an unconfigured component would run an unbounded
series of identical failed collections. Do not enable a retry policy for this
task before the channels are declared. Also recorded as deferred work.

**Egress must be open to `api.anaconda.org`**, and to nothing else for this
collector. `repodata.json` is deliberately never read: a channel's per-platform
index runs to hundreds of megabytes and answers a question about every package,
while the per-package document answers the question about one in kilobytes.

**Nothing here compares versions.** The published version is recorded exactly as
the channel spelled it. Whether it is *behind* anything is `CPM-FR-16`'s policy
with a versioned threshold, and no such policy exists yet.

## The full-inventory sweep: what beat fires, and what it does not do

Four collectors observe one package each per run. What runs them across the whole
inventory is one **dispatch** task, `cpm.collect.sweep`, fired by
`django_celery_beat` once per collector at the cadence that collector declares
(`CPM-NFR-1`, `CPM-FR-15`).

**A dispatch never collects.** It resolves the collector by name, asks it which
packages it can be asked about, and enqueues one ordinary per-package collection
task for each — `cpm.collect.source_release`, `cpm.collect.pypi_release`,
`cpm.collect.feedstock` or `cpm.collect.conda_package`, exactly the tasks a manual
recollection uses. It makes no outbound call, writes no evidence and holds no
transaction. Every guarantee described in the four sections above therefore holds
unchanged under a sweep: one package per task, one package per ledger row, one
package per transaction (`CPM-AD-23`).

**One dispatch per collector, and that is what keeps a failing source local.** A
rate-limited or misconfigured source fails its own collector's dispatch and no
other, so it costs you that surface for that cadence rather than a day of
monitoring everywhere else.

### A dispatch row's state is about enqueueing and nothing else

This is the sentence to read twice. A dispatch's ledger row says what the
dispatch did, which is *offer packages to the broker*. It says nothing about what
those collections then observed — they have not run when the row is finalized,
and a dispatch that waited for them would hold a worker slot for the length of a
rate-limited sweep.

| State | Meaning |
|---|---|
| `succeeded` | every selected package was enqueued — or the selection matched no package at all, which is a collector that was asked and answered |
| `partial` | some were enqueued and some were not; the ones that were **stay** enqueued, and `detail` names how many and why |
| `failed` | none of a non-empty selection was enqueued, or the dispatch was refused before it began |
| `skipped` | this collector's previous dispatch had not finished, so this tick offered nothing rather than queueing a second inventory |

So a sweep in which every package was enqueued and every collection then failed
leaves **one `succeeded` dispatch row above ten thousand `failed` collection
rows**, and that is the honest shape rather than a contradiction: the dispatch did
its whole job. Read the per-package rows for what was observed, and the dispatch
row only for whether the work was offered.

### The schedule is data, and it is reconciled against the collectors at start-up

`config/settings/base.py` declares one `CELERY_BEAT_SCHEDULE` entry per
per-package collector, and `django_celery_beat`'s `DatabaseScheduler` seeds its
tables from it. **What that does not buy you is changing one of these four
intervals without a deploy**: the scheduler rewrites every entry it finds in
settings on each beat start, so a value edited in the admin lives only until beat
restarts. Cadence-as-data is what lets a *later*, unrelated schedule live in the
tables; these four are the declaration, and changing one is a pull request.

Each collector separately declares the cadence its freshness target was derived
from. **If the two disagree, the component refuses to start**, naming both
numbers — because a weekly schedule against a daily-derived two-day target would
make the whole inventory read stale five days out of seven with every gate green
and every collection succeeding. The check runs in both directions: a schedule
entry naming a collector this component has not registered is refused too, since
it would fire into nothing on every tick; so is a collector that declares a
cadence without a selection, or a selection without a cadence.

The refusal fires from the collectors application's own `AppConfig.ready()`,
which is the hook that registers the collectors — `config/startup/stage_two.py`
evaluates the same rule as condition 11, but it runs earlier in `django.setup()`
than the registration does, so the application's own hook is the one a deployed
process meets. Either way the process does not start, and no worker picks up
work.

The shipped pairs are:

| Collector | Cadence |
|---|---|
| `source_release` | daily |
| `pypi_release` | daily |
| `feedstock` | weekly |
| `conda_package` | daily |

The three daily entries fire together, from one instant, and that is accepted
rather than overlooked: a dispatch enqueues and returns, so what lands at once is
three cheap tasks rather than three inventories of I/O, and the collections they
enqueue are paced by each collector's own rate limiter.

Inventory ingestion is deliberately absent: it reads one document naming many
packages and is not swept one package at a time, so a dispatch refuses it by name.

### Which packages a sweep offers

The precondition is the collector's own, and it is what stops a sweep failing
every run. Each collector answers only about packages whose identity resolution
has reached the mapping it reads, so a dispatch offers:

| Collector | Packages offered |
|---|---|
| `source_release` | those with a source repository recorded |
| `pypi_release` | those whose release-ecosystem mapping is `established` or `not_applicable` |
| `feedstock` | those whose feedstock mapping is `established`, `not_found` or `not_applicable` |
| `conda_package` | every package — **or none at all, until you declare channels and platforms** |

A package a collector would refuse is never enqueued, so its ledger does not fill
with `failed` runs for every package nobody has resolved. **Until a resolver
populates those mappings, the two release sweeps and the feedstock sweep will
select few packages or none, and record that honestly as a `succeeded` dispatch
with nothing enqueued.**

**The published-package sweep selects nothing until the two settings above are
declared**, and that is deliberate rather than a gap. Its question applies to
every package, so an undeclared component would otherwise enqueue the whole
inventory and fail every one of those collections naming the setting — ten
thousand `failed` rows a day, out of the box. Instead the selection is empty, the
dispatch records one `succeeded` row saying so, and the component says it once a
day. Declare `CPM_MONITORED_CHANNELS` and `CPM_MONITORED_PLATFORMS` and the sweep
starts observing on the next tick.

### What bounds a sweep

**No manual batching, ever.** The selection is streamed from the database five
hundred rows at a time, so ten thousand packages reach the queue without ten
thousand keys existing anywhere in a worker's memory.

**Every enqueued collection expires at one cadence.** A message that has not been
consumed by the time the next tick fires is superseded — the next dispatch offers
the same package again — so it is dropped rather than queued in front of the
fresher one.

**A dispatch whose previous run is still `running` records `skipped` and offers
nothing.** Without that, a sweep that cannot be drained inside its cadence would
enqueue a second whole inventory behind the first on every tick and the queue
would grow without bound. If you see `skipped` dispatch rows accumulating, the
collector is not keeping up with its cadence: lengthen the cadence, or raise the
allowance (which means authenticating — see the deferred work on
`CPM-CURRENCY-S01` and `CPM-CURRENCY-S03`).

**The inherited sixty-second soft limit applies to the dispatch task.** Ten
thousand packages is ten thousand broker round trips inside one task, so a slow
broker can reach it. When it fires the packages already enqueued stay enqueued,
the row is finalized `partial` saying the soft limit stopped it, and the next tick
offers the whole selection again. Nothing raises the limit — `CPM-AD-9` chunks
work rather than lengthening limits.

**A dispatch does not wait, poll or chain.** It hands each task to the broker and
finishes.

**The worker must drain the `collect` queue.** `cpm.collect.sweep` routes there
along with the collections it enqueues, so a worker started without
`-Q celery,collect,policy,verify` accepts the schedule tick and runs nothing —
silently, because an unconsumed queue is not an error.

### Reading a partial sweep

A `partial` dispatch row names how many packages the broker refused and the first
reason. It cannot name ten thousand primary keys, so **each refusal is also a log
line** under `sweep.package_refused`, carrying the collector, the task and the
`package_id`. That is the recovery path: filter the logs for that event and that
collector to get the packages the sweep did not offer.

**Rate limits are per collector and are not yet a sweep rate.** Each of the four
declares its own allowance, and at `1 + retries` per collection none of them
sweeps ten thousand packages inside its declared cadence today. The dispatch does
not change that arithmetic: it enqueues the work, and the per-collector limiter
refuses the calls it cannot afford, which records `error` rows rather than
exceeding the source's budget. Expect `skipped` dispatch rows and `error`
collection rows at that scale until the allowances are raised.

## The currency policy: what it compares, and what it will not

`CPM-CURRENCY-S06` adds the first policy pass. It runs inside the orchestrating
policy run rather than on a schedule of its own, so there is nothing here to
configure: no setting, no cadence, no allowance. What starts it is the
`cpm.policy.run` task (routed to the `policy` queue), and what it reads is the
evidence the four collectors above have already written. **Nothing in
`CELERY_BEAT_SCHEDULE` fires that task today** — a policy run is enqueued
explicitly, with the policy version it applies, and choosing a cadence for it is
not this component's decision to have made for you.

**It makes no outbound call of any kind.** A pass reads the evidence log and
writes derived rows (`CPM-AD-8`, `CPM-AD-9`). Nothing here is affected by a rate
limit, a credential, or a source being down — a source that was down when the
collector ran shows up as an `error` row the pass reports as `error`, and the
policy run itself is unaffected.

### It reads evidence as of the run's cut-off, never as of now

The cut-off is a `finished_at` from the collection-run ledger, chosen by
`choose_evidence_cutoff` — the newest ending that no still-running collection can
write evidence behind — and a ledger with nothing settled behind it makes the
policy run refuse rather than invent one. **A stuck collection run therefore
holds policy runs back**, deliberately: reading past it would include evidence
from a run that is still writing, and every replay would then read a different
set. Evidence written after the cut-off is not read.

### Replaying a run

`execute_policy_run` takes an optional `evidence_cutoff`. A scheduled run passes
nothing and gets the ledger's answer; **a replay passes the cut-off of the run it
is replaying**, which is on that run's `policy_runs` row and copied onto every
`package_health` row it wrote:

```python
from conda_package_supply_chain_monitor.core.clock import SystemClock
from conda_package_supply_chain_monitor.core.models import PolicyRun
from conda_package_supply_chain_monitor.core.policy_run import execute_policy_run

original = PolicyRun.objects.get(pk=...)
execute_policy_run(
    policy_version=original.policy_version,
    clock=SystemClock(),
    evidence_cutoff=original.evidence_cutoff,
)
```

Passing the cut-off is what makes this a replay rather than a repetition. Without
it, any collection run that finished in between moves the boundary, the second
run reads a different evidence set, and the comparison is not the one you wanted.
A supplied cut-off is used as given and is **not** re-derived from the ledger:
the run being replayed may well sit behind a collection that has since started,
and refusing it would refuse the whole operation.

The replay writes its own rows — a new `policy_runs` row, a new
`package_currency` row per package keyed to it — and leaves the original's alone.
The rows to diff are `package_currency` filtered by the two `policy_run_id`s. A
difference means the *rules* changed, never that the sweep happened to run at a
different minute.

### The verdicts, and what each one means

Each package gets one row in `package_currency` per policy run, carrying a
verdict for each of the four surfaces and one overall. The vocabulary is `core`'s
four sentinels plus two verdicts of its own:

| Verdict | What it means |
|---|---|
| `current` | The surface states the same version as the chosen authority. |
| `behind` | The surface states a **different** version from the authority. |
| `unknown` | Nothing was observed for the surface at the cut-off; or the observation itself records `unknown`; or it is determinate but states no version (a feedstock whose recipe names its version in a way the collector does not read); or no authority could be chosen to compare against. |
| `not_found` | The source itself answered that it has no version for this package. |
| `error` | The lookup failed. Not the same as an absence, and never folded into one. |
| `not_applicable` | The surface is not one this package is published on at all — a non-Python package against PyPI, for instance. |

The overall verdict is the worst of the surfaces the question applied to, ranked
worst-first as `error`, `behind`, `unknown`, `not_found`, `current`. `error`
outranks `behind` on purpose: a surface that could not be read may be hiding a
worse discrepancy than the one that was found, so a read failure never disappears
behind a finding. Two consequences are worth knowing before you read a report:

- **A package current on the surfaces somebody looked at and unobserved on the
  rest reads `unknown` overall.** An unobserved surface outranks a determinate
  one, so a full inventory that has only ever run the source collector reads
  `unknown` across the board. That is the honest answer, not a defect: schedule
  all four collectors before treating the overall column as a health signal.
- **A surface that does not apply to the package does not take its verdict
  away.** A non-Python package reads `not_applicable` against PyPI and still
  reads `current` overall when the other three surfaces agree: an inapplicable
  surface is excluded from the package-level reduction rather than ranked in it.
  The surface column keeps `not_applicable`, which is what `CPM-FR-6` is about.
  Only a package where *every* surface is inapplicable reads `not_applicable`
  overall.

### `behind` means *different*, not *older*

This is the limit worth reading twice. The comparison is **equality against the
authoritative surface**, not a version ordering. Ordering across four ecosystems
— PEP 440, conda's own ordering, and a recipe's Jinja-set string — does not have
one grammar, and nothing in the product's requirements fixes a rule for it, so
none was invented. What follows from that:

- A surface that has moved **ahead** of the authority reads `behind`. There is no
  `ahead` verdict.
- Two spellings of one version read as two versions. `1.0` against `1.0.0`, an
  epoch, a build suffix, a PEP 440 normalisation: each reads `behind`.
- The **one** spelling difference that is reconciled is a leading `v` followed by
  a digit, plus surrounding whitespace. `v1.2.3` and `1.2.3` are the same version
  here, because `CPM-FR-7` records "the latest release **or tag**" and a Git tag
  is conventionally written that way — without this, almost every feedstock would
  read `behind` against its own source. Nothing else is normalised.

Expect false `behind` verdicts where an upstream project and a recipe spell one
version differently. The row references the exact evidence rows the verdict rests
on, so what each surface actually said is one join away.

### The authority order, and the default when a package records none

Which ecosystem is authoritative for a package is data on the package
(`CPM-AD-6`), in `packages.version_authority_order`. It is a JSON list of surface
names, best first, and the surfaces it may name are exactly:

```
source          the upstream repository's latest release or tag
pypi            the PyPI project's latest version
feedstock       the version the conda-forge recipe pins
conda_package   the version a monitored conda channel publishes
```

**Every package ships with an empty list, and that is the ordinary state.** An
empty list means no authority has been chosen, and the documented default order
is applied:

```
source -> pypi -> feedstock -> conda_package
```

The chosen authority is the **first entry of the applied order that actually
stated a version at the cut-off**. A surface earlier in the order that was
unobserved, that errored, that answered `not_found`, or that is `not_applicable`
to the package is passed over — which is what stops a package being judged
against a registry it never published to. The row records which order was applied
and whether it was the default, so a report can tell a package that chose the
default order from one that chose nothing.

`CPM-AD-6`'s stated default ends "→ internal deployed version". **This product
observes no such surface**: no collector reads a deployed inventory and no
evidence table holds one, so the entry is absent from both the vocabulary and the
default rather than present and unusable.

**A recorded order may name fewer than four surfaces**, and the consequence is
worth stating: a surface the order leaves out is still read and still recorded,
but can never be the authority. An order naming only `feedstock` on a package
with no feedstock observation therefore produces `unknown` everywhere, because
there is nothing to compare against.

**An order naming anything else fails that package's evaluation.** A misspelling
(`pypy`), a surface this product does not observe (`deployed`), a repeated entry,
or a value that is not a list at all is refused rather than quietly replaced by
the default — replacing it would write a row claiming an order the package's own
data contradicts. `CPM-AD-23` contains the refusal to one package: that package's
derived rows roll back and it keeps whatever rollup row it had, every other
package commits, the run finalizes `partial`, and the failure is logged under
`policy_pass_failed` with the package's primary key and the traceback. Nothing in
this product writes that column yet, so today it can only get a bad value from a
hand-written `UPDATE` or a data migration.

### The rollup column, and why an unmapped package always reads `unknown`

The pass contributes one column to `package_health`: `currency_status`, carrying
the overall verdict. It never writes that table — it returns the value and the
rollup writer writes it, after applying `CPM-AD-4`'s confidence gate. So a
package whose identity is `unmapped` reads `unknown` in `package_health`
**whatever the pass computed**, while `package_currency` still records the
verdict the pass actually reached. If those two disagree for a package, the
identity confidence is why, and the fix is resolution rather than anything here.

A package no policy run has evaluated reads `unknown` too: that is the column's
own default, and it is deliberately not a clean value.

### Running it, and where the result lands

There is no beat entry (see above). A run is enqueued as the `cpm.policy.run`
task on the `policy` queue, or executed in-process:

```sh
pixi run manage shell -c "
from conda_package_supply_chain_monitor.core.tasks import run_policy
run_policy.delay('<your policy version>')
"
```

The `policy_version` is yours: `CPM-AD-8` makes it the version of the *rule data*
a run applies, not a version this component ships. It lands on the run's ledger
row and in every rollup row's per-domain version map, and it is the string a
replay must match.

Three places to read the result:

| Table | What it holds |
|---|---|
| `package_health.currency_status` | One value per package: the overall verdict, **after** the confidence gate. This is the read surface. |
| `package_currency` | One row per package **per run**: the four per-surface verdicts, the overall verdict ungated, the chosen authority, the order that was applied and where it came from, `detail` for anything called `behind`, and a foreign key to each of the four evidence rows the verdicts rest on. |
| `policy_runs` | One row per run: the version, the cut-off, the instants, and the ending — `succeeded`, or `partial` with a count when some packages could not be computed. |

A package that could not be computed is logged under `policy_pass_failed` with
its primary key and the traceback; the ledger row carries the count, and the log
is the only place the names are.

### `package_currency` accumulates, and nothing prunes it

One row per package per run, never updated and never deleted. At ten thousand
packages a daily run adds ten thousand rows a day, and **every relation on the
table is `PROTECT`** — to the package, to the policy run, and to each of the four
evidence rows — so nothing else can be deleted while its rows reference it.

That is deliberate: the rows are what a replay is compared against and what an
audit reads, and `CASCADE` would let an operational tidy-up of old policy runs
silently empty the evidence for every verdict still on the rollup. It also means
**there is no retention path here yet**. Deleting old runs is a decision nobody
has taken, it would have to delete `package_currency` rows before the
`policy_runs` rows they protect, and no story currently claims it. Size the
database accordingly, or run the policy less often than you collect.

### Nothing in this product can set a package's authority order

`packages.version_authority_order` is data (`CPM-AD-6`), and **no code path in
this component writes it**. Resolution does not set it, the identity override
does not cover it, and there is no admin surface for it. Every package therefore
holds `[]` and is judged on the documented default.

The only way to record an authority today is a hand-written `UPDATE`:

```sql
UPDATE packages
   SET version_authority_order = '["feedstock", "source"]'
 WHERE canonical_name = 'numpy';
```

Two things follow, and neither is guarded:

- **Such a change alters derived verdicts and leaves no audit row.**
  `CPM-IDENTITY-S05`'s identity override writes an append-only record of who
  changed what and why; this column has no equivalent, so a verdict that changed
  because somebody edited an order is indistinguishable from one that changed
  because the evidence did.
- **A bad value is not refused at write time.** The column carries a Django
  validator, which runs from a form and never from `save()` or from SQL — so an
  order naming a surface this product does not observe is stored happily and is
  refused later, when the pass reads it, which fails that one package's
  evaluation and finalizes the run `partial`.

Both are recorded as deferred work on `CPM-CURRENCY-S06`.

### What a run costs

This pass issues **five queries per package** — one read per surface, plus the
insert of the derived row — inside the orchestration's per-package loop. Nothing
batches them. At `CPM-NFR-1`'s ten thousand packages that is fifty thousand round
trips for this pass alone, and it multiplies as the remaining policy passes land.
The count is pinned by a test at three inventory sizes so a regression is
visible; making it set-based is recorded as deferred work.

### One published-package verdict, and which channel it is about

`conda_package_snapshots` holds one row per `(channel, platform)`, and this pass
produces **one** conda verdict per package. Which pair it is about is decided by
a stated key, not by luck: one sweep stamps every row it writes with the run's
single instant, so all of a package's rows tie on `observed_at`, and without a
key the answer would be whichever row was inserted last — which changes when you
reorder `CPM_MONITORED_CHANNELS`, silently.

**The key is the channel, then the platform, both ascending, then the newest row
for that pair.** Alphabetical is arbitrary and is chosen only because it is
*fixed*: the same evidence produces the same verdict on every replay. The row
references the observation, so the channel and platform the verdict concerns are
readable from it.

Two costs follow, and both are real:

- A package current on one channel and behind on another gets the
  first-sorting channel's verdict.
- **A channel that simply does not carry the package answers `not_found`**, and
  if that channel sorts first, `not_found` becomes the package's conda verdict
  even where a later-sorting channel publishes the authority's exact version. Read
  the referenced observation before acting on a conda `not_found`.

A verdict per pair is a larger table than this one's `(package, policy_run)` key
describes, and it is not built here.
