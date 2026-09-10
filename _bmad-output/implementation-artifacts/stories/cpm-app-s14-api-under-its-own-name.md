# CPM-APP-S14: The API is under the application's name, and carries a version

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Raised by
> the product owner, who asked where a version segment belongs and chose between four
> shapes. See the epic entry.

## Story

As an integrator,
I want this product's API under the product's own name and behind a version,
so that I can tell whose contract I am calling, and so a change to it has somewhere to
go that does not break what I already wrote.

## Acceptance Criteria

1. **Given** any endpoint this application publishes
   **When** its URL is resolved
   **Then** it is under `/conda-sentinel/api/v1/`

2. **Given** a request for a version this API does not serve
   **When** it is answered
   **Then** it says which versions exist, rather than answering as though the
   endpoint were missing

3. **Given** the platform's own API
   **When** the move is made
   **Then** it is unmoved, and is not described by this application's contract

4. **Given** this application's published schema
   **When** it is read
   **Then** it describes this application's endpoints and no others

5. **Given** a browser-based caller of either API
   **When** its preflight is evaluated
   **Then** the CORS rule covers both roots

## Tasks / Subtasks

- [x] `config/api_router.py` — two rosters, declared together, mounted apart.
- [x] `config/urls.py` — the mounts, the application's own schema, the version route.
- [x] `config/api_versions.py` — the refusal that names the versions that exist.
- [x] `config/settings/base.py` — CORS across both roots.
- [x] The 31 `api:` references that name this application's endpoints.
- [x] `test_api_contract_audit.py` — the boundary replaces the exemption.
- [x] `test_url_mounting_audit.py` — the API is a second mount under the name.

## Dev Notes

**Satisfies:** nothing directly. Completes `CPM-FR-27`'s addressing.

**Governed by:**

- `CPM-AD-19` — routing is central. Both rosters are declared in
  `config/api_router.py` even though they are mounted apart, because that decision is
  about where routing is *legible*, not about how many mounts there are.

### Why the shape is `/conda-sentinel/api/v1/…`

Four were considered. Two put the version after the resource — `…/packages/v1` — and
both were rejected on the same ground: a version segment at a variable depth cannot be
routed, proxied or deprecated as a unit, and a schema cannot be scoped to it.

Of the remaining two, `/api/conda-sentinel/v1/…` puts the application inside the
platform's API root, which leaves this product addressed in two places —
`/conda-sentinel/` and `/api/conda-sentinel/` — and that is precisely what
`CPM-APP-S13` was written against. One boundary per application, and everything behind
it.

### Why not `URLPathVersioning`

DRF's class reads the version from a URL keyword argument. That means `<str:version>`
in every mounted pattern and a `version` argument in every `reverse()` that names one
of these routes — thirty-one of them. Nothing in this product branches on
`request.version`; the refusal is the only behaviour wanted from versioning today, and
`config/api_versions.py` buys it for one route instead of for every call site.

Adopting the class later changes no path, which is what makes this the cheap order.

### The exemption that went away

While the two APIs shared `/api/` they shared a schema document, and the contract
audit had to record the platform's `UserViewSet` in `PLATFORM_WRITES` to answer "what
does this API write" honestly. Two roots make the question answer itself, and what
replaces the exemption is a boundary assertion — checked from the direction that fails
silently, because a prefix that swept `/api/` along would break a published contract
while every one of this product's own cases still passed.

## Dev Agent Record

### Completion Notes

**Files added:** `config/api_versions.py`, and this story.

**Files changed:** `config/api_router.py`, `config/urls.py`,
`config/settings/base.py`, `tests/integration/django_apps/test_api.py`,
`tests/unit/django_apps/test_api_contract_audit.py`,
`tests/unit/django_apps/test_url_mounting_audit.py`, `tests/unit/test_settings.py`.
**No model, no migration, no view logic in the product.**

**The namespace moved with the mount.** This application's API is reversed by
`conda_sentinel_api:` and the platform's keeps `api:`, because `api:` is the thing
mounted at `/api/` — a namespace whose name says `api` while reversing to somebody
else's prefix is the kind of small untruth that costs an afternoon. Thirty-one
references changed; all were `reverse()` calls, none was a written path.

**Two things worth recording.**

*The version refusal answers every verb the same way.* A caller who posts to a version
that does not exist should not be told the method is wrong — `405` would send them to
look at their verb, which is the one thing about their request that was fine.

*`SCHEMA_PATH_PREFIX` does not trim.* It drives tag and operation-id derivation;
trimming is `SCHEMA_PATH_PREFIX_TRIM` and is off, so the document carries full paths
and a generated client reaches the right URL without being handed a base path to
prepend.

**Three things found by running it.**

1. **A bulk edit split the DEBUG block in `config/urls.py`.** A constants block was
   inserted before `urlpatterns = [`, which appears twice — the second time inside
   `if "debug_toolbar" in INSTALLED_APPS`. The suite failed at import with
   `NameError: debug_toolbar`, which was the honest report of a text edit applied
   where a structural one was meant.
2. **The same bulk rename reached the `CPM-APP-S13` audit's roster**, turning its
   `/api/` entry — which names a route that must *not* move — into one that had just
   moved. It now names `api:user-me`, which is a platform route and cannot be renamed
   by a sweep over this application's names.
3. **The schema, docs and version-refusal views sit under this application's API root
   without being part of its contract.** They serve it rather than being in it, so
   they are a recorded exemption with a spend check rather than a loosened boundary.

**Coverage:** unchanged; this story adds no product branches.
