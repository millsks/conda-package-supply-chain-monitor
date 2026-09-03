---
title: "Brief Addendum — Conda Package Supply Chain Monitor"
status: current
created: 2026-09-02
updated: 2026-09-02
---

# Brief Addendum — Conda Package Supply Chain Monitor

Depth that belongs downstream (PRD, architecture) or that earned a place but does not
fit a 1–2 page brief. The brief is the contract; this is the material behind it. Each
section below names the brief clause it backs, what the brief says, why, and what is
still open.

## Decisions this addendum raised

Every design decision this document surfaced, in one place. The brief's own §8 Open
Questions is a disjoint list: those are questions about the world (which advisory
sources, which license policy, which channels). These are questions about the design.

**Closed by the PRD.**

| Decision | Settled as | Where |
|---|---|---|
| Who holds the identity-override write permission | The platform and engineering leadership role. It is the only human write into governed *reference* data — queue actions write workflow state, a separate class — and it requires a reason and is audited with actor, timestamp, and prior value | PRD `CPM-FR-3`, `CPM-FR-32` |
| Natural key vs. surrogate key for the package identity | Surrogate integer primary key, with `canonical_name` as a unique indexed column. Survives the non-Python later phase, keeps evidence foreign keys narrow, and makes a canonical-name correction non-cascading | PRD Appendix A.1 |

**Closed by the architecture spine.**

| Decision | Settled as | Where |
|---|---|---|
| Whether the candidate AI stack is adopted | Partly. LangChain is the tool layer and serves natural-language querying; LangFlow composes, as a separate deployment unit. **DB-GPT was evaluated and rejected** — no Python 3.14 classifier against a 3.14-only repository, `sqlalchemy`/`fastapi` pins mutually exclusive with LangFlow's, and unestablished conda-forge availability. Adoption of the remaining two is gated by a fitness spike | `CPM-AD-17` |
| How a read-only analytics role is provisioned under Django | A second `DATABASES` alias `analytics` with `SELECT` on governed views only, a `DATABASE_ROUTERS` entry confining the `ai_integration` app to it, and governed views created and versioned by Django migrations in `reporting` via reversible `RunSQL` | `CPM-AD-16` |
| How a separate analytics service fits the deployment contract | Its own `component.toml` process type inside a `# feature:analytics` marker pair, with its own replica count and `rolling` replacement | `CPM-AD-17` |

**Layering note.** The brief and the PRD deliberately keep stating this layer as a
capability with no product names, and neither was changed. Requirements survive a stack
change unedited; the architecture is where a product gets bound. If the three are ever
replaced, only the spine changes.

## 1. What the platform import already settled

*Backs: the brief as a whole — it is deliberately technology-neutral, so the facts the
platform import settled are recorded here rather than there.*

The repository runs Django 5.2 LTS on Python 3.14, imported from the
`django-15-factor-base` accelerator, with:

- Django REST Framework and drf-spectacular for the API surface
- django-allauth with OIDC for authentication; group-claim-driven authorization
- Celery with django-celery-beat for scheduled collection and policy evaluation; Redis
  as broker and cache
- PostgreSQL via psycopg 3
- structlog and OpenTelemetry, correlating `request_id`, `user_id`, and `trace_id` across
  requests, Celery tasks, queries, and cache calls
- Health and drain endpoints, a two-stage startup check, and a `component.toml`
  deployment contract

The observability wiring matters specifically to the brief's auditability claim: a
collection run that fails partway is traceable to the request and task that performed
it, which is what makes an `error` state investigable rather than merely recorded.

## 2. Why v1 is Python-first

*Backs: brief §5 Scope, and Goal 1's refusal to presuppose PyPI.*

The pre-import brief scoped a "Conda/Python inventory" and its first goal mapped every
package to a PyPI name — presupposing PyPI applies universally. The README deliberately
scopes the architecture wider: native libraries, compilers, system libraries, Rust and R
packages.

The brief and the README are each right about different things, and the resolution is a
phase boundary rather than a scope narrowing. v1 targets the Python subset, where every
check in the policy set is meaningful and where the compliance pressure sits. The
architecture stays broad, and `not_applicable` is modeled from v1 so the later phase
exercises an existing path instead of introducing one.

**Settled.** The phase boundary made the primary key a dated decision rather than a
settled one: `Core_Python_Package_Name` works for a Python-first v1, but a native library
has no core Python package name, so it does not survive the later phase. The PRD closes
this with a surrogate integer primary key and `canonical_name` as a unique indexed
column — evidence foreign keys stay narrow, and correcting a canonical name no longer
cascades (PRD Appendix A.1).

## 3. The three roles: permissions and the write path

*Backs: brief §2 Users.*

The brief's role table is the product-level source for group-to-permission mapping. The
platform already resolves user identity through OIDC and syncs the asserted group claim
to Django groups (`src/config/authorization/`), so the mapping has an enforcement point
waiting for it.

**Settled.** Manual package-identity overrides are the only human write into governed
data. Under the pre-import batch design an override was a config file; here it is an
authenticated, permissioned mutation. A separate identity-steward role was offered and
declined in favor of three roles, which left the permission unassigned; the PRD assigns
it to the platform and engineering leadership role, requires a reason on every write, and
audits actor, timestamp, and prior value (PRD `CPM-FR-3`, `CPM-FR-32`). Queue actions
write workflow state, which is a separate class and never touches identity or evidence.

## 4. Terminology and naming

*Backs: the brief's title, and the naming discipline downstream documents must follow.*

The product is the **Conda Package Supply Chain Monitor**, matching the repository,
README, and CI badges. The name "Conda-Forge Package Health Monitor" — carried by the
pre-import brief, PRD, and architecture — is retired. conda-forge is one monitored
surface, not the subject. The brief, the PRD, and the architecture spine all use the
current name; only the superseded `architecture.md` still carries the retired one.

"Identity" now means two unrelated things: package identity resolution (the planned
`src/django_apps/identity/` app) and user identity via OIDC. Downstream documents should
always qualify it — "package identity" or "user identity", never bare "identity".

## 5. The natural-language layer: the adopted stack

*Backs: brief §3 Vision and Goal 7, which state the capability and name no products.*

The brief states the capability — a governed, read-only natural-language layer whose
answers cite the evidence rows behind them — and deliberately names no products, so it
survives a stack change unedited.

**Two adopted, one rejected — and neither adopted component is a dependency yet.**
`CPM-AD-17` gates both on a fitness spike.

| Component | Status | Role |
|---|---|---|
| LangChain | Adopted, spike-gated | Controlled tool layer — approved queries returning structured results, not free-form generation. Also serves natural-language querying over the governed views |
| LangFlow | Adopted, spike-gated | Workflow composition, as its own image and process type rather than a dependency |
| DB-GPT | **Rejected** | No Python 3.14 classifier against a 3.14-only repository; CI on 3.10/3.11 only; `sqlalchemy <2.0.29` / `fastapi <0.113.0` mutually exclusive with LangFlow's floors; conda-forge availability unestablished |

Tools named in the pre-import PRD, listed for continuity. `CPM-AD-18` governs their shape:
each returns a structured payload carrying evidence references, never a rendered sentence.

| Tool | Intended role |
|---|---|
| `get_package_health` | Current rollup for one package, with evidence references |
| `compare_versions` | Source, PyPI, recipe, and published versions side by side |
| `get_vulnerability_findings` | CVE and KEV findings with severity and matched version |
| `get_license_policy_result` | Normalized license and its policy outcome |
| `list_feedstock_gaps` | Packages with no feedstock or a lagging recipe |
| `create_remediation_ticket_draft` | Drafts a tracking issue; never files one |

**Still open.** Two questions the gate has not answered:

- A separate analytics service brings its own container and deployment-contract
  implications — `component.toml` declares process types and per-database release-stage
  migration steps. Nothing has examined that fit.
- A read-only role over governed views is not a database-administration detail under
  Django: it needs a second `DATABASES` alias and a database router, and the governed
  views must be created and versioned by the migrations Django owns.

## Documents pending realignment

Repository artifacts that still carry the pre-import name or delivery model. Not
rationale for the PRD — a checklist to close out.

- ~~**PRD**~~ — realigned. Now carries the current name, requirements for the web, API,
  and authorization surfaces, global stable FR-N ids, and non-positional epic keys
  including `EP-PLATFORM` and `EP-APP`.
- ~~**Architecture**~~ — realigned and replaced by `ARCHITECTURE-SPINE.md` in the same
  folder. The retired `architecture.md` remains only as the superseded input.
- **README, identifier note** — the README does not mention that the imported platform
  owns bare `AD-n` / `FR-n` / `NFR-n` while this product's artifacts carry `CPM-`. A
  contributor reading a `src/` comment will otherwise resolve `FR-17` against the wrong
  document.
- **README, "Project Scope"** — its opening paragraph reads in the present tense about
  the broader ecosystem. It describes the architecture's reach, not v1's target. Reword
  it to say so, or a reader will take v1 as broader than it is.
