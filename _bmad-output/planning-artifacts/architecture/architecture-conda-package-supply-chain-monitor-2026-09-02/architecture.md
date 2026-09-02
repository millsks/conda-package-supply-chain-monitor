---
title: "Architecture Decisions — Conda-Forge Package Health Monitor"
status: final
created: 2026-09-02
updated: 2026-09-02
---

# Architecture Decisions — Conda-Forge Package Health Monitor

## 1. Architecture Principles
- Separate stable identity snapshots from volatile, timestamped evidence.
- Use deterministic code and SQL for policy decisions; LLMs may summarize or explain evidence but must not decide compliance, severity, or priority.
- Preserve uncertainty: missing, failed, and ambiguous states must remain visible.
- Make all collector workloads independently schedulable, idempotent, retryable, and rate-limited.
- Provide read-only, governed database access to every LLM-facing component.

## 2. High-Level Components
1. **Identity Resolution Service**: Batch resolution jobs plus manual-override storage.
2. **Inventory Layer**: Canonical package identity snapshot keyed by `Core_Python_Package_Name`.
3. **Collectors**: Independent jobs for source, PyPI, feedstock, Conda package, vulnerability, KEV, license, and Python 3.14 assessment.
4. **Evidence Store**: Relational database storing append-only evidence and collection records.
5. **Policy and Scoring Engine**: Versioned deterministic batch process that reads evidence and produces current rollups, priority, score, rank, and work outputs.
6. **Reporting Layer**: Materialized views, DB-GPT, LangChain tools, and LangFlow workflows.

## 3. Data Flow
`Inventory list → Identity resolution → independent collectors → append-only evidence store → policy/scoring engine → current inventory materialized view → DB-GPT, LangChain, and LangFlow`

## 4. Core Decisions

### ADR-001 — Inventory is a snapshot identity layer
**Decision:** Retain the identity schema as the canonical one-row-per-package inventory. Use `Core_Python_Package_Name` as the inventory key.

**Rationale:** Identity, ownership, workflow links, and internal-use metadata are relatively stable and are convenient in a human-facing export/view.

**Consequences:** The inventory must not be used as the only storage for changing releases, CVEs, KEVs, licenses, or compatibility claims.

### ADR-002 — Monitoring results are append-only evidence
**Decision:** Store observed versions, advisory matches, KEV status, licenses, and Python 3.14 results as timestamped evidence records.

**Rationale:** The monitor must explain what was known, when it was known, where it came from, and why policy changed.

**Consequences:** Current status is derived, not manually overwritten. Historical reporting and policy replay are possible.

### ADR-003 — Policy is deterministic and versioned
**Decision:** Implement currency, vulnerability, KEV, license, Python 3.14, priority, and work-type decisions in versioned deterministic code and/or SQL.

**Rationale:** Security and compliance outcomes require reproducibility and auditability.

**Consequences:** LLMs are limited to grounded explanations, query assistance, remediation ticket drafts, and report composition.

### ADR-004 — Identity confidence gates automation
**Decision:** Use `associator_status` to determine permissible automated actions.

| Status | Behavior |
|---|---|
| `verified` | Allow automated comparisons and recommendations, subject to evidence quality. |
| `inventory-derived` | Collect and report, but label recommendations lower confidence. |
| `unmapped` | Do not infer external identity or declare the package current/clean; route to identity review. |

### ADR-005 — Version authority is explicit per package
**Decision:** Define a documented release-authority order per package, rather than treating PyPI as universal truth.

**Default decision order:**
1. Verified upstream releases at `source_repository_url`, if that source publishes releases.
2. The verified primary release ecosystem, such as PyPI, when it is authoritative for the package.
3. Conda-forge feedstock recipe version.
4. Published Conda package version.
5. Internal/deployed package versions when deployment risk is included.

**Consequences:** Store the authority decision and supporting evidence. Do not mark packages PyPI-stale merely because they are not published to PyPI.

### ADR-006 — Source collectors are independent
**Decision:** Collectors write their own evidence and collection records; one failure does not prevent unrelated monitoring areas from succeeding.

**Rationale:** Sources have separate availability, rate limits, and refresh schedules.

### ADR-007 — Current view is a derived reporting contract
**Decision:** Build a materialized current-inventory view that retains the canonical inventory columns and adds derived health statuses.

**Required derived statuses:**
- source currency status
- PyPI currency status
- feedstock currency status
- feedstock presence status
- Python 3.14 compatibility status
- license compliance status
- vulnerability status
- KEV status
- remediation readiness
- evidence freshness
- recommended work

### ADR-008 — LLM access is governed and read-only
**Decision:** DB-GPT, LangChain, and LangFlow access database views through a read-only role, not raw write-capable tables.

**Controls:** approved views, query timeout, row limit, audit logs, and no write privileges.

## 5. Suggested Technology Choices
- **Database:** PostgreSQL or the organization’s approved relational database.
- **Scheduling:** Existing organization scheduler; cron, Airflow, or Prefect are acceptable implementation choices.
- **Application services:** Python is preferred because of Conda/PyPI ecosystem support.
- **Agent layer:** LangChain tools for controlled query functions; LangFlow for workflow composition/API exposure; DB-GPT for governed natural-language SQL analytics.

## 6. Operational Requirements
- Idempotent jobs keyed by collector, package identity, source, observation time, and relevant package version.
- External requests require caching, rate limits, retry/backoff, timeouts, and structured errors.
- Evidence freshness targets must be defined per collector.
- Dashboards and agent reports must show `unknown`, `not_found`, `error`, and stale states separately.
- Manual mapping overrides must have provenance and survive normal automated refreshes.

## 7. Risks and Mitigations
| Risk | Mitigation |
|---|---|
| Ambiguous or malformed package identities | Confidence states, evidence provenance, and manual review queue; no silent inference. |
| Advisory or KEV source licensing/availability | Confirm sources before the security collector implementation. |
| Python 3.14 verification requires actual build capacity | Treat build/import verification as a separate compute-backed capability; distinguish it from metadata inference. |
| LLM exposure of internal usage data | Enforce governed views and use private/local deployment where required. |
| External source outages/rate limits | Independent collectors, caching, backoff, partial-success runs, and visible stale/error status. |
