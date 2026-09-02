---
title: "Product Requirements Document — Conda-Forge Package Health Monitor"
status: final
created: 2026-09-02
updated: 2026-09-02
---

# Product Requirements Document — Conda-Forge Package Health Monitor

## 1. Background
This PRD covers the MVP through Phase 3. The existing identity snapshot schema is adopted as the canonical inventory view. `Core_Python_Package_Name` is the primary key.

## 2. Canonical Inventory Schema

### Data rules
- Primary key: `Core_Python_Package_Name` (unique string).
- Blank means missing; do not invent values.
- Multi-value fields use `;` as a separator.
- Do not overwrite an `associator_status` of `verified` with a lower-confidence mapping.
- The inventory is the snapshot identity layer. Volatile monitoring facts belong in timestamped evidence tables.

### Required inventory fields
| Field(s) | Type / role |
|---|---|
| `P` | `P1`–`P10`; derived policy priority bucket |
| `Rank` | Integer; 1-based rank within snapshot |
| `Score` | Integer 1–100; ranks within a `P` bucket |
| `Package` | Display name |
| `Work` | Derived actionable work type |
| `Platforms`, `Apps`, `Downloads`, `Versions` | Internal usage signals |
| `Vuln` | Derived vulnerability rollup |
| `Core_Python_Package_Name` | Primary key |
| `OpenTeams_Title`, issue URL fields | Tracking metadata |
| `identity_source`, `associator_key`, `associator_status` | Identity provenance and confidence |
| `primary_purl`, `primary_type`, `alternative_purls`, `cpes`, `conda_purl` | Cross-ecosystem identities |
| `source_repository_url` | Upstream VCS identity |
| `Conda-Forge_FeedStock_URL`, `Conda-Forge_Metadata_URL`, `Staged_Recipes_PR_URL` | Conda-forge state |
| `Local_Recipes_URL`, `Local_Build_Status`, `Verification_Timestamp_UTC` | Internal packaging/build state |
| `Priority_Bucket_Description`, `Priority_Source`, `Priority_Reason` | Explainable priority output |
| `JFROG_risk_level`, `JFROG_latest_vuln_count` | Vulnerability rollups |
| `internal_component_count`, `internal_lob_count` | Internal impact breadth |

### Allowed `Work` values
- `Fix vulnerability`
- `Create recipe`
- `File tracking issue`
- `Already tracked`
- `Update feedstock`
- `Validate Python 3.14`
- `Review license`
- `Resolve identity`

## 3. Evidence Tables
Evidence is append-only and snapshot-keyed by package, source, and observation time.

- `source_release_snapshots`: upstream latest version, release date, repository activity signal, lookup status.
- `pypi_release_snapshots`: PyPI existence, latest version/date, `Requires-Python` metadata.
- `feedstock_snapshots`: feedstock existence, recipe version, recipe activity, build/test outputs.
- `conda_package_snapshots`: published Conda version, channel, build string.
- `vulnerability_findings`: advisory/CVE ID, affected range, fixed range, severity, matched version, source, confidence.
- `kev_findings`: relationship to vulnerability finding and KEV catalog date added.
- `license_findings`: raw license, normalized SPDX expression, detection method, policy result.
- `python314_findings`: status, evidence type, log reference, tested platform/architecture.
- `collection_runs`: job ID, collector, package, status, error detail, started/finished timestamps.
- `policy_runs`: policy version, run timestamp, input evidence cut-off, status.

## 4. Functional Requirements

### FR1 — Identity Resolution Service
- FR1.1: Resolve every inventory package to `primary_purl`, `conda_purl` when applicable, `source_repository_url`, and zero or more `Conda-Forge_FeedStock_URL` values.
- FR1.2: Persist `identity_source` and `associator_status` for every resolution.
- FR1.3: Support manual mapping overrides that are not overwritten by automated collection unless explicitly re-resolved.
- FR1.4: Surface unmapped packages in a review queue. Never equate unmapped with no feedstock or no CVEs.

### FR2 — Independent Collectors
- FR2.1: Source collector obtains latest release/tag and date from `source_repository_url`.
- FR2.2: PyPI collector obtains project existence, latest version/date, and `Requires-Python`.
- FR2.3: Feedstock collector obtains existence, recipe version, recipe metadata, and recent recipe activity.
- FR2.4: Conda package collector obtains published version/build for each monitored channel.
- FR2.5: Vulnerability collector matches package and version against advisory sources and stores affected/fixed ranges.
- FR2.6: KEV collector cross-references vulnerability findings with the KEV catalog.
- FR2.7: License collector extracts and normalizes license metadata and applies organization policy.
- FR2.8: Python 3.14 collector performs static metadata checks by default; optional build/import verification records verified evidence.
- FR2.9: Each collector writes only to its evidence table and `collection_runs`; failures must not block other collectors.

### FR3 — Deterministic Policy and Scoring Engine
- FR3.1: Version currency compares source, PyPI, feedstock recipe, and published Conda versions using a documented authority order per package.
- FR3.2: Vulnerability and KEV policy derives `Vuln` and `JFROG_risk_level` from evidence.
- FR3.3: License policy derives allowed, restricted, forbidden, unknown, or manual-review results from a versioned data-driven policy.
- FR3.4: Python 3.14 policy derives readiness status.
- FR3.5: Priority engine assigns `P` by top-down first-match rules and calculates `Score` from internal usage signals.
- FR3.6: `Work` is derived independently from `P`.
- FR3.7: Every policy run is versioned and can be re-run against historical evidence without recollection.

### FR4 — Reporting and Query Layer
- FR4.1: Generate a materialized current-inventory view matching the canonical inventory schema.
- FR4.2: Configure DB-GPT to use a read-only governed database role and views only.
- FR4.3: Expose LangChain tools backed by real queries: `get_package_health`, `compare_versions`, `get_vulnerability_findings`, `get_license_policy_result`, `list_feedstock_gaps`, and `create_remediation_ticket_draft`.
- FR4.4: Compose LangFlow workflows for daily KEV, weekly feedstock lag, Python 3.14 readiness, license exception, and single-package investigation reports.
- FR4.5: Each generated explanation cites the evidence table, evidence ID, and observation timestamp used.

### FR5 — Auditability
- FR5.1: Never overwrite a finding in place; each observation is a new row.
- FR5.2: Current values are derived from the latest eligible evidence and expose the evidence timestamp.
- FR5.3: Collection failures and evidence older than its service-level freshness target are visibly flagged.

## 5. Non-Functional Requirements
- NFR1: Support collection cycles for 10,000 packages without manual batching.
- NFR2: Configure collector cadences independently: daily for security/KEV, daily-to-weekly for version checks, and on-demand/triggered for Python 3.14 full verification.
- NFR3: LLM-facing components have read-only access, row limits, and query timeouts.
- NFR4: External calls use rate limiting, retries with backoff, and caching.
- NFR5: Do not transmit sensitive internal usage fields to external LLM APIs unless explicitly approved; support private/local model deployment for DB-GPT.

## 6. Epics

### Epic 1 — Identity and Inventory Foundation
Deliver identity resolution and the canonical inventory for the full package set, including a review queue for unmapped and low-confidence records.

### Epic 2 — Collectors: Version Currency
Deliver source, PyPI, feedstock, and Conda-package collectors with snapshot tables, a currency policy, and a current rollup view.

### Epic 3 — Collectors: Security and Compliance
Deliver vulnerability, KEV, and license collectors plus policies and rollups.

### Epic 4 — Python 3.14 Readiness
Deliver metadata-based classification followed by build/import verification evidence.

### Epic 5 — Priority and Scoring Engine
Deliver deterministic, versioned, rerunnable `P`, `Rank`, `Score`, and `Work` policy processing.

### Epic 6 — Natural-Language Access Layer
Deliver the DB-GPT read-only connection, LangChain tools, LangFlow reporting flows, and evidence-cited responses.

## 7. Out of Scope for v1
- Automated remediation or automated pull-request creation.
- Full historical trend dashboards beyond queryable history.
- Non-Python/non-Conda ecosystems.

## 8. Open Questions
- Which advisory and KEV data sources are available and licensed for use?
- What license allow/deny policy should seed evaluation?
- What is the source of internal usage fields such as platform, app, and download counts?
- Is a private/self-hosted LLM required for DB-GPT under the internal-data handling requirement?
