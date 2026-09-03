# Conda Package Supply Chain Monitor

[![CI](https://github.com/millsks/conda-package-supply-chain-monitor/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/millsks/conda-package-supply-chain-monitor/actions/workflows/ci.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=millsks_conda-package-supply-chain-monitor&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=millsks_conda-package-supply-chain-monitor)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=millsks_conda-package-supply-chain-monitor&metric=coverage)](https://sonarcloud.io/summary/new_code?id=millsks_conda-package-supply-chain-monitor)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-5.2%20LTS-092E20.svg)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An evidence-driven platform for monitoring the health, security, compliance, and maintenance status of packages distributed through the conda ecosystem.

The project is designed for inventories that include Python packages as well as native libraries, compilers, system libraries, Rust packages, R packages, and other artifacts available through conda-forge.

## Why This Project Exists

Package inventories change continuously. A package may be current upstream but lagging on PyPI, conda-forge, or an internal channel. It may also have known vulnerabilities, a license-policy issue, incomplete Python 3.14 support, a missing feedstock, or an inactive source repository.

The Conda Package Supply Chain Monitor collects evidence from these sources, evaluates it using deterministic and versioned policies, and produces an explainable package-health and remediation view.

## Capabilities

- Maintain a canonical package inventory and identity mapping.
- Map packages across conda, conda-forge, PyPI, source repositories, package URLs, CPEs, and feedstocks.
- Compare versions across upstream sources, PyPI where applicable, conda-forge recipes, and published conda packages.
- Detect and track CVEs and Known Exploited Vulnerabilities (KEVs).
- Evaluate package and recipe licenses against a configurable policy.
- Assess Python 3.14 readiness where Python compatibility is relevant.
- Determine whether a conda-forge feedstock exists and whether it appears to be maintained.
- Preserve timestamped evidence instead of overwriting historical observations.
- Calculate deterministic priority, ranking, score, and recommended work items.
- Provide a review queue for unmapped, ambiguous, stale, failed, or low-confidence records.
- Support natural-language investigation and reporting through governed AI workflows.

## Project Scope

The initial inventory may contain approximately 10,000 packages. The architecture is intentionally broader than Python so it can support the wider conda-forge ecosystem, including native and system-level dependencies.

Version currency, Python compatibility, and some metadata checks are package-type dependent. The system must represent `not_applicable`, `unknown`, `not_found`, and `error` separately from a successful clean result.

## Requirements

[pixi](https://pixi.sh) is the only prerequisite. It provisions Python 3.14 and
every dependency from conda-forge; nothing is installed with `pip`.

PostgreSQL is the target database. The suite falls back to a sqlite substitution
when `DATABASE_URL` is unset, which is enough for unit tests but does not
exercise everything the PostgreSQL gate does.

## Quick start

```sh
pixi install         # runtime environment
pixi install -e dev  # development toolchain
pixi run bootstrap   # install the git hooks
pixi run migrate     # apply migrations (sqlite by default)
pixi run runserver   # http://127.0.0.1:8000/
```

## Development

```sh
pixi run test              # unit tests (fast, no database or network)
pixi run test-integration  # integration tests
pixi run test-cov          # full suite, 90% coverage floor
pixi run ci                # the full gate -- must pass before any change is done
pixi run docs-serve        # documentation with live reload
```

`pixi run ci` is the gate, and it is the same sequence locally and in CI:
`precommit` -> `build` -> `typecheck` -> `lint` -> `test-cov`, fast-fail-first.
`.github/workflows/ci.yml` invokes exactly that one task and nothing else, so a
green local run and a green pipeline mean the same thing.

Dependencies live in `pixi.toml` and come from conda-forge; `pyproject.toml`
holds build metadata and tool configuration only. The `default` environment
carries runtime dependencies only; `dev` layers the toolchain on top. Tasks
resolve to whichever environment defines them, so `-e` is rarely needed.

See `docs/development.md` for database configuration and the full task list.

## Architecture Overview

The system is organized into five primary layers:

1. **Inventory and identity layer** — stores stable package identity and mapping information.
2. **Evidence collection layer** — independently collects observations from external and internal sources.
3. **Policy and scoring layer** — evaluates evidence using deterministic, versioned rules.
4. **Reporting and query layer** — exposes current health views, reports, and controlled query tools.
5. **AI orchestration layer** — uses LangChain, LangFlow, and DB-GPT to investigate and explain evidence without becoming the source of truth.

```text
Package inventory
        |
        v
Identity resolution
        |
        +-------------------+-------------------+-------------------+
        v                   v                   v                   v
     Source              PyPI              conda-forge          Security /
   collectors          collector            collectors          compliance
        |                   |                   |                   |
        +-------------------+-------------------+-------------------+
                            v
                    Append-only evidence store
                            |
                            v
                 Policy and scoring engine
                            |
                            v
                 Current package-health view
                            |
              +-------------+--------------+
              v                            v
        Operational reports          AI query layer
                                     LangChain / LangFlow / DB-GPT
```

## Core Design Principles

### Identity and evidence are separate

The canonical inventory is a relatively stable identity snapshot. Releases, vulnerabilities, licenses, feedstock activity, build results, and compatibility assessments are volatile observations and belong in timestamped evidence records.

### Deterministic policies are the source of truth

Security status, license results, version currency, Python 3.14 readiness, priority buckets, scores, ranks, and work types are calculated by versioned code or SQL policies. An LLM must not independently decide whether a package is compliant, vulnerable, current, or high priority.

### Unknown is not clean

A failed lookup, missing mapping, stale observation, or unavailable source must remain visible. The system must not convert incomplete evidence into a clean result.

### Evidence is auditable

Every finding should retain its source, observation timestamp, collection run, package identity, and confidence. Reports and AI-generated explanations should be traceable to the evidence used.

### Collectors are independent

Source, PyPI, conda-forge, vulnerability, KEV, license, and Python compatibility collectors should be separately schedulable, retryable, rate-limited, and observable. A failure in one source should not prevent unrelated collectors from running.

## Evidence Domains

The initial monitoring model includes the following evidence domains:

| Domain | Example observations |
|---|---|
| Source releases | Latest upstream version, release date, repository activity, lookup status |
| PyPI | Project existence, latest version, release date, `Requires-Python` |
| Conda-forge feedstock | Feedstock existence, recipe version, recipe activity, build/test state |
| Published conda packages | Channel, package version, build string, publication status |
| Vulnerabilities | CVE/advisory identifier, severity, affected range, fixed range, matched version |
| KEV | KEV catalog membership and date added |
| Licenses | Raw license, normalized SPDX expression, detection method, policy result |
| Python 3.14 | Metadata assessment, build verification, import verification, test result |
| Collection operations | Collector status, errors, retries, start and finish timestamps |

## Canonical Inventory

The inventory identity layer is keyed by `Core_Python_Package_Name`, based on the existing project identity schema. It includes fields for package display information, priority, ranking, internal usage, vulnerability rollups, package URLs, source repositories, feedstocks, staged recipes, local recipes, build status, and issue-tracking links.

Important identity and provenance fields include:

- `Core_Python_Package_Name`
- `Package`
- `primary_purl`
- `primary_type`
- `alternative_purls`
- `cpes`
- `conda_purl`
- `source_repository_url`
- `Conda-Forge_FeedStock_URL`
- `Conda-Forge_Metadata_URL`
- `Staged_Recipes_PR_URL`
- `identity_source`
- `associator_key`
- `associator_status`
- `Verification_Timestamp_UTC`

Derived workflow fields include:

- `P`
- `Rank`
- `Score`
- `Work`
- `Vuln`
- `JFROG_risk_level`
- `JFROG_latest_vuln_count`
- `Priority_Bucket_Description`
- `Priority_Source`
- `Priority_Reason`

The inventory is a reporting and identity contract. It is not the sole storage location for historical monitoring results.

## Policy and Scoring

The policy engine should be deterministic, versioned, and re-runnable against historical evidence.

Policy areas include:

- Version currency and source-to-feedstock lag.
- Vulnerability and KEV rollups.
- License allow, restrict, deny, and manual-review decisions.
- Python 3.14 readiness.
- Feedstock existence and maintenance status.
- Evidence freshness and collector health.
- Priority bucket assignment from top-down rules.
- Usage-weighted score and rank calculation.
- Recommended `Work` type.

Example `Work` values include:

- `Fix vulnerability`
- `Create recipe`
- `Update feedstock`
- `Validate Python 3.14`
- `Review license`
- `Resolve identity`
- `File tracking issue`
- `Already tracked`

AI may explain a policy outcome, summarize evidence, or draft a tracking issue. It must not replace the policy engine.

## LangChain, LangFlow, and DB-GPT

> **Status:** design only. None of LangChain, LangFlow, or DB-GPT is a
> dependency of this repository yet.
### LangChain

LangChain provides the controlled application and tool layer for package investigations. Tools should invoke approved queries and return structured results rather than allowing an agent to invent facts.

Planned tools include:

- `get_package_health`
- `compare_versions`
- `get_vulnerability_findings`
- `get_license_policy_result`
- `list_feedstock_gaps`
- `create_remediation_ticket_draft`

Each tool should return the package identifier, current status, relevant evidence identifiers, source names, observation timestamps, and confidence or freshness information where available.

### LangFlow

LangFlow is used to compose repeatable workflows from collectors, policy outputs, database tools, and reporting components. Candidate flows include:

- Single-package investigation.
- Daily KEV report.
- Weekly feedstock-lag report.
- Python 3.14 readiness report.
- License exception report.
- Unmapped-identity review report.
- Stale-evidence and collector-failure report.

LangFlow flows should orchestrate existing deterministic services and LangChain tools. They should not embed undocumented business rules in prompts.

### DB-GPT

DB-GPT provides a natural-language analytics interface over the evidence store. It should use a read-only database role and approved views designed for analytical queries.

Recommended controls include:

- Read-only credentials.
- Approved reporting views instead of unrestricted raw-table access.
- Query timeouts and row limits.
- SQL and request audit logging.
- Restricted access to sensitive internal usage fields.
- Evidence citations in generated answers.
- Explicit handling of missing, stale, failed, and not-applicable states.

DB-GPT is an analytics and explanation interface. Deterministic policy results remain authoritative.

## Observability

Structured logging (structlog) and distributed tracing (OpenTelemetry) are built
in, not optional. Every log line carries `request_id`, `user_id` and `trace_id`,
and requests, Celery tasks, queries and cache calls are traced. Spans export over
OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, and are dropped when it is not --
so nothing retries against a collector that isn't there.

This matters for the evidence model: a collection run that fails partway is
traceable to the request and task that performed it, which is what makes an
`error` or `unknown` state auditable rather than merely recorded.
See `docs/observability.md`.

## Data and Security Considerations

- Do not send sensitive internal usage data to an external model unless explicitly approved.
- Prefer private or self-hosted model deployment where organizational requirements demand it.
- Keep the AI-facing database role read-only.
- Record the evidence rows used to produce reports and explanations.
- Apply rate limits, caching, request timeouts, and retry/backoff to external collectors.
- Preserve source attribution and collection errors.
- Treat manually curated identity overrides as governed data with provenance.

## Technology Stack

### In place today

Pinned in `pixi.toml` and exercised by the gate:

- **Python 3.14** and **Django 5.2 LTS** (supported to April 2028; the pin is
  `>=5.2,<5.3` so a feature release cannot drift in).
- **PostgreSQL** via `psycopg` 3, with `libpq` held at 17 to match the server the
  gate runs against. A sqlite substitution covers the non-Linux test legs.
- **pixi** for environment and dependency management -- conda-forge is the single
  source for third-party packages, and `[pypi-dependencies]` holds only this
  project's own editable install.
- **Celery** with **django-celery-beat** for background collection and scheduled
  policy evaluation, and **Redis** as broker and cache.
- **Django REST Framework** with **drf-spectacular** for the API surface.
- **django-allauth** for authentication, including OIDC.
- **structlog** / **django-structlog** and **OpenTelemetry** for correlated logs
  and traces.
- **uvicorn** (ASGI) and **whitenoise** for serving.
- **django-crispy-forms** with **crispy-bootstrap5** for form rendering.

### Planned, not yet present

Named in the design but not yet dependencies of this repository:

- **htmx** and **Alpine.js** for dynamic HTML interactions and lightweight
  client-side reactivity.
- **LangChain**, **LangFlow**, and **DB-GPT** for the AI orchestration layer
  described below.

The platform foundation was imported from
[django-15-factor-base](https://github.com/millsks/django-15-factor-base), an
accelerator built on 15-factor application principles -- environment-based
configuration, secure defaults, split settings for local/test/production, a
two-stage startup check, and health and drain endpoints.

## Repository Structure

```text
.
|-- manage.py                  # Django management entry point
|-- pixi.toml                  # environments, dependencies, tasks (the gate)
|-- pyproject.toml             # build metadata and tool configuration only
|-- component.toml             # deployment contract (databases, release steps)
|-- Dockerfile                 # container image
|-- mkdocs.yml                 # documentation site
|-- src/                       # import root -- deliberately NOT a package
|   |-- config/                # settings, urls, asgi/wsgi, celery, startup
|   |   |-- settings/          # base / local / test / production
|   |   |-- authorization/     # OIDC: JWKS, claims, mapper, adapters
|   |   |-- health/            # health and drain endpoints
|   |   |-- observability/     # structlog and OpenTelemetry wiring
|   |   |-- startup/           # two-stage boot checks
|   |   `-- local_dev/         # personas and token minting for local work
|   `-- django_service/        # the application package
|       |-- users/             # users app, provisioning, API, commands
|       |-- templates/
|       `-- static/
|-- tests/
|   |-- unit/                  # no database, network, or filesystem
|   |-- integration/           # marked `integration`
|   `-- spikes/                # dependency fitness spikes
|-- docs/                      # mkdocs sources
`-- _bmad-output/
    `-- planning-artifacts/    # brief, PRD, architecture
```

`src/` is the import root and is deliberately *not* a package, so `config` and
`django_service` import as top-level packages. It is declared in exactly one
place -- `[tool.hatch.build.targets.wheel]` in `pyproject.toml`, which remaps
`src/` onto the wheel root. The editable install is what puts it on `sys.path` at
runtime; no entrypoint, pixi task or test setting declares it a second time.

### Planned domain applications

The evidence pipeline is not yet built. As it lands it will be added under
`src/django_service/` as separate Django applications:

- **identity/** -- package identity resolution, canonical inventory, mapping overrides.
- **collectors/** -- evidence collection from source repositories, PyPI, conda-forge, and vulnerability sources.
- **evidence/** -- append-only evidence models, timestamped observations, retrieval interfaces.
- **policies/** -- deterministic policy evaluation, scoring, priority, and work-type assignment.
- **reporting/** -- operational reports, views, dashboards, exports.
- **ai_integration/** -- LangChain tools, DB-GPT configuration, governed query interfaces.
- **core/** -- shared utilities, base models, middleware, cross-cutting concerns.

LangFlow workflow definitions and scheduler integration scripts will follow the
same rule: they land when they exist, not before.

## Initial Delivery Plan

### Phase 1 — Identity and inventory foundation

- Import the existing package inventory.
- Establish the canonical identity model.
- Add identity provenance and confidence.
- Implement manual mapping overrides.
- Create an unmapped and ambiguous identity review queue.

### Phase 2 — Version and feedstock monitoring

- Implement source, PyPI, feedstock, and published-conda collectors.
- Store append-only release and feedstock snapshots.
- Implement version-currency policies.
- Produce the current package-health view.

### Phase 3 — Security and compliance

- Add vulnerability and KEV evidence collection.
- Add license extraction, normalization, and policy evaluation.
- Implement vulnerability and license rollups.
- Add daily and weekly operational reports.

### Phase 4 — Python 3.14 readiness

- Implement metadata-based classification.
- Add optional build, import, and test verification.
- Track platform and architecture-specific results.
- Separate inferred compatibility from verified compatibility.

### Phase 5 — AI-assisted analytics

- Implement LangChain tools over governed views.
- Compose LangFlow investigation and reporting workflows.
- Configure DB-GPT for read-only natural-language analytics.
- Require evidence references in generated explanations.

## Current Non-Goals

The initial version does not aim to:

- Automatically upgrade packages.
- Automatically create or merge feedstock pull requests.
- Replace an existing issue tracker.
- Build a general-purpose package manager or Conda channel.
- Support every package ecosystem outside the conda ecosystem.
- Treat an LLM-generated answer as authoritative without underlying evidence.

## Open Questions

Before implementation is finalized, the project should confirm:

- Which vulnerability and KEV data sources are available and approved?
- Which license policy should be used as the initial organizational baseline?
- Where do internal platform, application, download, component, and LOB counts originate?
- Which conda channels and platforms are in scope?
- Which source ecosystems are authoritative for version currency on a package-by-package basis?
- Is private or self-hosted model deployment required for DB-GPT and LangChain workflows?
- Which scheduler, database, deployment target, and authentication standards are required?

## Contributing

Contributions should preserve the project's core principles:

1. Keep identity data separate from historical evidence.
2. Make policy decisions deterministic and testable.
3. Preserve unknown, stale, failed, and not-applicable states.
4. Include provenance for external observations.
5. Prevent LLM-facing components from writing directly to operational data.
6. Add tests for collector behavior, policy rules, identity resolution, and evidence rollups.

Mechanically:

- Branch from `main` as `feature/`, `bugfix/`, or `hotfix/`; open a pull request rather than pushing to `main`.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) -- the changelog is generated from them.
- `pixi run ci` must exit 0 before a change is done. Never use `--no-verify`.
- If a pre-commit hook auto-fixes a file, re-stage it before re-running; the fix is left unstaged.

## License

This project is licensed under the MIT License. See the `LICENSE` file for the full license text.
