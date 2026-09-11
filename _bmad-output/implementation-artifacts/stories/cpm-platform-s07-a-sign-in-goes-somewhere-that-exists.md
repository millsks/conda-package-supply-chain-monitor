# CPM-PLATFORM-S07: A local run sends a sign-in somewhere that exists

Status: done

Epic: `CPM-EP-PLATFORM` — The service platform

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Raised by
> the product owner pasting a `local-stack` log and asking what the errors were. See
> the epic entry.

## Story

As somebody running this locally,
I want an unauthenticated page to send me somewhere I can sign in,
so that my first click is not a traceback.

## Acceptance Criteria

1. **Given** a local run with no identity provider configured
   **When** an unauthenticated request reaches a gated page
   **Then** it is redirected to the local sign-in page, carrying where it was going

2. **Given** the same run
   **When** the redirect is followed
   **Then** it reaches a page that exists

3. **Given** a local run where `COMPONENT_OIDC_ISSUER` **is** configured
   **When** an unauthenticated request reaches a gated page
   **Then** the OIDC flow is kept

## Tasks / Subtasks

- [x] `config/settings/local.py` — `LOGIN_URL` conditional on a configured issuer.
- [x] `tests/unit/test_local_dev_urls.py` — both sides of the condition.
- [x] `docs/conda-sentinel/asynchronous-work.md` — why a running beat has run nothing.
- [x] `docs/conda-sentinel/onboarding.md` — the same, in the troubleshooting table.

## Dev Notes

**Governed by:** inherited `AD-23`. The issuer stays the single trust anchor and
nothing here changes what the Bearer path verifies against; this is only where a
*browser* is sent when there is no provider to send it to.

### What was actually happening

`base.py` points `LOGIN_URL` at allauth's OIDC login view — correct in every
deployment. `local.py` supplies a fallback issuer for the Bearer path and
**deliberately does not reach `SOCIALACCOUNT_PROVIDERS`**, which `base.py` had already
built from the issuer it read there. Its own comment says so:

> `.invalid` is reserved by RFC 2606 and resolves nowhere, which is the point: these
> values are verified as strings and are never fetched. Nothing here reaches
> `SOCIALACCOUNT_PROVIDERS`, which `base.py` already built from the issuer it read
> there.

That separation is right. The consequence nobody had followed through was that the
provider's `server_url` is then `""`, so allauth asks `requests` for
`"" + "/.well-known/openid-configuration"` and gets a `MissingSchema` — a 500 with a
traceback on the first gated page anybody opens.

Measured:

```
OIDC_ISSUER          = 'https://local-dev.invalid/realms/component'
settings.server_url  = ''
```

### Why not fix the provider block

Because it would turn a `MissingSchema` into a DNS failure against a `.invalid` host.
A different 500, not a fix — and it would undo the separation above.

The local sign-in page *is* the substitute for the provider in a local run, so it is
what `LOGIN_URL` names. A developer who exports `COMPONENT_OIDC_ISSUER` keeps the OIDC
flow, because in that case `base.py` built the provider from the same value and the
flow works.

## Dev Agent Record

### Completion Notes

**Files changed:** `src/config/settings/local.py`,
`tests/unit/test_local_dev_urls.py`, `docs/conda-sentinel/asynchronous-work.md`,
`docs/conda-sentinel/onboarding.md`.

### Verified by reproducing the failure and then not reproducing it

Before, against a fresh gunicorn on the stack's database: `GET /conda-sentinel/` →
302 → OIDC login → `MissingSchema` → 500. After:

```
/conda-sentinel/  status=302  ->  /_local/?next=/conda-sentinel/
500s in the log: 0
```

### Three things the audits taught me on the way

**The prefix audit reads comments.** `test_each_constant_is_spelled_in_exactly_one_module`
pins the local sign-in prefix to `constants.py`, and the first draft failed it three
times — not in code, in the explanatory comment, which spelled the path while arguing
that nothing should. Reworded rather than exempted: an audit that skipped comments
would stop catching the case where somebody explains a path instead of reversing it.

**A settings test must import the settings.** The first draft asserted
`django.conf.settings.LOGIN_URL`, which is the *suite's* configuration —
`config.settings.test` — not `local.py`'s. It failed correctly, and
`tests/settings_import.py` already existed for exactly this.

**A cached import made the second case a lie.** With the eviction fixture missing,
`importlib.import_module` returned the module the first case had imported, so
"configured issuer keeps the OIDC flow" passed while reading the unconfigured
environment. It is the negative half of the condition, so a false pass there would have
left the conditional untested in the direction that matters.

### The second question in the same report

"If the workers and the scheduler are running, why does everything say never run?"

Nothing was wrong. The eight beat entries are **intervals**, and
`django_celery_beat` stamps a new entry's `last_run_at` at registration — so the first
fire is one whole interval later, a day or a week. Measured on the running stack:

```
cpm-sweep-source-release  enabled=True  interval=every 86400 seconds  last_run=None  total_runs=0
…all eight the same…
collection runs recorded: 2   Counter({'local-dev-demo-seed': 2})
```

The Coverage screen was right: the only runs in the ledger are the seeder's, filed
under a name that is deliberately not a registered collector so that seeding cannot
make a real collector look healthy.

Confirmed the worker itself was fine by publishing `cpm.policy.run` to the stack's
broker — policy run 3, `succeeded`, 100 rollup rows.

Documented, along with the trap on the other side: hand-triggering a **collector**
sweep against the demo inventory makes real HTTP requests about fixture repositories
and records `not_found` for all of them, permanently, in an append-only log.

### The two log lines that are not errors

Neither needed a change, and both are now explained rather than left to worry about.

**`Inspect method … failed` from flower**, eight of them at start-up: flower polls the
worker while it is still in `mingle`. The worker reported `ready` one second later.
Transient by construction.

**`StreamingHttpResponse must consume synchronous iterators`**, once per page: traced
to whitenoise, which serves static files as `WhiteNoiseFileResponse` — streaming, with
a sync iterator. Proven by response type rather than inferred:

```
/static/css/conda-sentinel.css  200  streaming=True   WhiteNoiseFileResponse
/_local/                        200  streaming=False  HttpResponse
/livez                          200  streaming=False  HttpResponse
```

It looks orphaned in the log because whitenoise's middleware sits **above**
`django_structlog`'s, so those requests are served without a `request_started` line —
the warning is the only trace a static file leaves. Cosmetic, upstream, and not this
product's to fix.
