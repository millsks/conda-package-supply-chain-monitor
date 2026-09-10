# CPM-APP-S13: The application is mounted under its own name

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Decided by
> the product owner against the implementing agent's recommendation, which was to
> defer. Recorded plainly: the deferral rested on the change being cheap to make
> later, and it is the same change either way.

## Story

As any of the three roles,
I want this product's pages to live under a path that names it,
so that I can tell which application a URL belongs to, and so a second application on
this platform cannot silently take a path this one holds.

## Acceptance Criteria

1. **Given** any of this product's HTML surfaces
   **When** its URL is resolved
   **Then** it is under `/conda-sentinel/`

2. **Given** the root
   **When** it is opened
   **Then** it sends the reader to this product's home under the prefix

3. **Given** anything that names one of this product's pages — a template, a
   redirect, a test
   **When** it is resolved
   **Then** it resolves through the URL namespace and not through a written path

4. **Given** the platform's own routes — the API, the accounts flows, the health
   probes
   **When** the prefix is applied
   **Then** they are unmoved

## Tasks / Subtasks

- [x] `config/urls.py` — the include moves under the prefix; the root redirects.
- [x] `surface/urls.py` — `home` is the root *of the application*.
- [x] The `CPM-APP-S12` cases that asserted the root *is* the home page.
- [x] `tests/unit/django_apps/test_url_mounting_audit.py` — all four criteria.

## Dev Notes

**Satisfies:** nothing directly.

**Governed by:**

- `CPM-AD-19` — one app per domain, **routed centrally**. That decision is the whole
  reason this story is small: there is one line mounting this product's pages, and
  every template reaches them through the `conda_sentinel:` namespace.

### What this is and is not

It names the **application within a service**. `FORCE_SCRIPT_NAME` names the
**service within a host** and moves everything including `/api/` and the accounts
flows. They are different questions and a deployment can use both; this story does not
replace that mechanism.

It does not make the root this product's — `CPM-APP-S12` did that, and the root
continues to lead here.

### Why the platform's routes stay put

`/api/` is versioned and routed centrally on its own terms; moving it would change a
contract `CPM-APP-S07` published and an integrator may already hold. `/accounts/` and
`/users/` are the platform's, not this application's, and putting them under this
application's name would say something untrue about who owns them. The health probes
are deliberately unprefixed and carry no credential.

### AC 3 is the one that decays

Nothing today writes a product path — every reference goes through the namespace,
which is what makes this one line. That property is worth a test rather than a
comment: the first hard-coded `/conda-sentinel/packages/` is the one that survives the
next move.

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a
  90% floor.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**Two lines of routing, and the story is the tests.** `CPM-AD-19` routes centrally, so
one `path()` moved every HTML surface and a second gave the root somewhere to lead.
Nothing inside the application changed — no view, no template, no reverse — because
every reference already went through the `conda_sentinel:` namespace. That property is
what made the change small, and it is what the audit exists to keep.

**Files added:** `tests/unit/django_apps/test_url_mounting_audit.py`.

**Files changed:** `config/urls.py`, `surface/urls.py`, and two integration modules
whose cases asserted the root *was* the home page. **No model, no migration, no view.**

**Each acceptance criterion:**

- **AC 1 (every surface under the prefix).** Swept over resolved routes rather than
  over the line that mounts them — a broken mount fails the whole suite, but a route
  declared *outside* the application's own URLconf, in `config/urls.py` for
  convenience, would sit outside the prefix and nothing else would notice.
- **AC 2 (the root leads here).** A redirect, not a second mount. A second `path("")`
  on the same view would have given the home page two addresses, which is what makes
  a link in a ticket disagree with the one in the navigation.
- **AC 3 (nothing writes a path).** The property that made this one line, and the
  first thing to go: a hard-coded `"/conda-sentinel/packages/"` works perfectly, is
  invisible in review, and is discovered the next time the mount moves — by which
  point there are five of them. Swept across the product package and every template.
- **AC 4 (the platform's routes unmoved).** Checked from the direction that fails
  *silently*: a prefix that took `/api/` with it would break a contract `CPM-APP-S07`
  published, and every one of this product's own tests would still pass. The
  integrator would be the one who found out.

**The decision, recorded honestly.** The implementing agent recommended deferring
this, twice, on the measured ground that the change was one line whenever a second
product actually arrived. The product owner decided in favour of doing it now. Both
positions are kept on the epic because the reasoning matters more than the outcome —
and the recommendation contained its own answer: if the change is cheap to make later,
it is cheap to make now, and only one of those orderings leaves somebody guessing
which application a URL belongs to in the meantime.

**What this is not.** It names the *application within a service*.
`FORCE_SCRIPT_NAME` names the *service within a host* and moves everything including
`/api/` and the accounts flows. A deployment can use both; this does not replace it.

**Verified against a running server:**

```
/                            302 -> /conda-sentinel/
/conda-sentinel/             200
/conda-sentinel/packages/    200
/conda-sentinel/coverage/    200
/api/packages/               200      (unmoved)
/accounts/login/             200      (unmoved)
/packages/                   404      (no stale second address)
```

The navigation followed with no template edit, which is the namespace doing its job.

**Coverage:** unchanged at 99.10%; this story adds no branches.
