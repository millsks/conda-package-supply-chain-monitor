# CPM-PLATFORM-S03: One command brings up the whole local stack

Status: done

Epic: `CPM-EP-PLATFORM` — The service platform

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Asked for
> by the product owner, who named the task `local-stack` and pointed at the sibling
> `django-python-generate-sbom` repository. See the epic entry.

## Story

As a maintainer,
I want one command that runs the product the way it actually runs,
so that I can see the request boundary work rather than take it on trust.

## Acceptance Criteria

1. **Given** a checkout with Docker available
   **When** `pixi run local-stack` is run
   **Then** Redis and PostgreSQL come up, and the web process, a worker, beat and a
   monitor run together

2. **Given** the containers
   **When** they publish their ports
   **Then** they do not take a port a developer's own services commonly hold

3. **Given** any process in the stack
   **When** it starts
   **Then** it resolves local settings and reaches the broker the stack started — not
   a default it was never pointed at

4. **Given** the tasks the stack adds
   **When** the deployment's process group is reconciled
   **Then** none of them is in it

## Tasks / Subtasks

- [x] `compose.yaml` — Redis 8.2 and PostgreSQL 17, healthchecked, on their own ports.
- [x] `Procfile` — four processes, each delegating to a pixi task.
- [x] `pixi.toml` — `honcho`, `flower`, seven `docker-*` wrappers, `flower`, `local-stack`.
- [x] `config/settings/local.py` — `CELERY_TASK_ALWAYS_EAGER` overridable.
- [x] `tests/unit/test_local_stack.py`.
- [x] `docs/conda-sentinel/running-it.md`.

## Dev Notes

**Governed by:** `CPM-AD-9` — the boundary the stack exists to make visible.
`CPM-AD-20` — the queues the worker drains. And the process-model contract in
`component.toml`.

### Infrastructure only

`compose.yaml` brings up Redis and PostgreSQL. The application runs from the pixi
environment, because that environment *is* the runtime: a `web` service in compose
would mean a rebuild on every edit and a second, slower way to run what pixi already
runs. `Dockerfile` remains what builds the deployable image.

### The docker tasks

Named to match the sibling repository so the same muscle memory works in both. Three
of its eight do not carry over — `docker-build`, `docker-migrate` and `docker-shell`
reach a `web` service through `docker compose exec`, and this compose file has none.
`docker-psql` and `docker-redis` are the equivalents that do make sense here.

## Dev Agent Record

### Completion Notes

**Files added:** `compose.yaml`, `Procfile`, `tests/unit/test_local_stack.py`.
**Files changed:** `pixi.toml`, `src/config/settings/local.py`,
`docs/conda-sentinel/running-it.md`.

### Two defects, both of which looked like a working stack

Neither would have failed anything. Both are cases now.

**1 — A bare `pixi run worker` reads deployed settings.** `COMPONENT_RUNTIME=local`
comes from `[feature.dev.activation.env]` and nowhere else; a task may not declare it
and `test_locality_declaration.py` fails the gate on any that tries. So the first
`Procfile` resolved in `default`, found no broker URL, and Celery fell back to its
built-in `amqp://guest@localhost:5672`.

The worker started. It printed a banner listing `celery, collect, policy, verify,
export` — the right queues — and consumed nothing, because it was connected to a
RabbitMQ that was not running. Found by starting it and reading the banner:

```
- ** ---------- .> transport:   amqp://guest:**@localhost:5672//
```

Every `Procfile` line now runs `pixi run -e dev …`, and the same banner reads
`redis://localhost:6380/0`.

**2 — The containers wanted ports that were already taken.** `infra-up` failed to
bind 6379, because the developer's own Redis was there.

The fix is not "ask them to stop it". This product calls `cache.clear()`, which
flushes an **entire Redis database** — so a stack that bound the default port on a
machine where nothing happened to be listening would eventually flush somebody else's
project. The containers publish on **6380** and **5433**, and `local-stack` sets
`REDIS_URL` and `DATABASE_URL` explicitly rather than relying on defaults that point
somewhere else. The two stacks now coexist and nothing has to be shut down.

### The web process is the deployed one

`pixi run web` — gunicorn with `config.workers.DrainingUvicornWorker`, the line
`Dockerfile` runs — **at the product owner's direction, against this agent's first
draft**, which used `runserver` because the sibling repository does.

The decision is the more coherent one. A stack whose purpose is to run the product the
way it actually runs should serve it the way production serves it, and `runserver`
hides ASGI behaviour, the worker class and shutdown draining. Verified serving:

```
Listening at: http://0.0.0.0:8000   (DrainingUvicornWorker)
GET /                 -> 302
GET /conda-sentinel/  -> 302
```

Two costs, accepted rather than overlooked: no autoreload, because `--reload` does not
belong on a deployed command; and gunicorn is Unix-only, so that one line does not run
on Windows while the worker, beat and flower lines do.

### Nothing here joins the process group

`component.toml` declares the deployment's processes and `test_process_model.py`
reconciles the two directions. None of the nine tasks this story adds declares
`COMPONENT_PROCESS`, and `test_local_stack.py` asserts that — so nobody later "fixes"
the omission by declaring them.

Flower is the one worth spelling out. It is a monitor, and the obvious home would be
`[[admin_processes]]` — except that table requires a Django management command, and
flower is not one. It is bound to `127.0.0.1` rather than `0.0.0.0`: it exposes queue
contents and task arguments, and a monitor listening on every interface is one
somebody on the same network can read.

### A database broker was considered and rejected

At the product owner's suggestion. On inspection kombu 5.6.2 **does** still ship a
`sqla` transport — the expectation that it had been removed was wrong — but it needs
SQLAlchemy, a second ORM beside Django's against the same database. It polls rather
than being pushed to, SQLite serialises writes behind one lock, and the
full-inventory sweep enqueues one task per package against `CPM-NFR-1`'s ten
thousand. Redis stays the broker; the product owner agreed.
