---
title: "Project Brief — Conda Package Supply Chain Monitor"
status: final
created: 2026-09-02
updated: 2026-09-02
supersedes: "Project Brief — Conda-Forge Package Health Monitor (same path, pre-import revision)"
---

# Project Brief — Conda Package Supply Chain Monitor

An organization runs a ~10,000-package conda inventory with no unified, evidence-based
view of its health. This project builds one: a service that continuously collects
evidence about each package, evaluates it against explicit deterministic policies, and
presents the result — with its provenance — to the people who have to act on it. v1
targets the Python subset of that inventory and delivers detection, evidence, and
prioritization. It does not remediate.

*This revision replaces the pre-import brief titled "Conda-Forge Package Health
Monitor". The PRD and architecture still carry that name and its delivery model.*

## 1. Problem Statement

A ~10,000-package conda inventory currently has no unified, evidence-based view of its
health. Assessments are manual, fragmented, and go stale quickly. There is no auditable
trail showing why a package was flagged.

Three consequences follow. Reviewers cannot distinguish a package that is genuinely
clean from one nobody has looked at. Nobody can reconstruct what was known about a
package at the time a decision was made about it. And hand-produced assessments get
prioritized by whoever is asking loudest rather than by risk and internal usage impact.

## 2. Users

Three account-holding roles authenticate through the organization's identity provider.
The provider's group claims determine authorization. Each role is defined by what it
reads and what it acts on.

| Role | Reads | Acts on |
|---|---|---|
| Security and compliance reviewer | Vulnerability, KEV, and license findings with their evidence and confidence | License exception review; risk acceptance |
| Packaging engineer | Feedstock currency and presence, version lag, Python 3.14 readiness | The remediation work queue |
| Platform and engineering leadership | Prioritized rollups, coverage, evidence freshness, collector health | Prioritization and reporting decisions |

Every role reads; each role acts only on its own queue. This table is the product-level
source for the group-to-permission mapping that the platform enforces.

## 3. Vision

Build a system that continuously collects evidence from source repositories, package
ecosystems, and conda-forge; evaluates that evidence against explicit deterministic
policies; and preserves every observation with its source and timestamp.

Results reach these roles through three surfaces: an authenticated web application where
they do their work, a governed API for integration, and a governed natural-language
layer for investigation.

Deterministic policy is the source of truth throughout. A language model may explain,
summarize, or draft; it never decides whether a package is compliant, vulnerable,
current, or high priority.

## 4. Goals

**Evidence and collection**

1. Establish a reliable identity-resolution layer mapping each package to its conda
   name, source repository, conda-forge feedstock, and release ecosystem — PyPI for the
   Python packages v1 targets. Where a mapping does not apply, record that rather than
   inferring one.
2. Continuously collect version and state facts from source, PyPI, feedstock recipe, and
   published conda package surfaces.
3. Evaluate deterministic policies for version currency, CVE/KEV exposure, license
   compliance, Python 3.14 readiness, and feedstock existence and health.
4. Persist findings as timestamped, sourced evidence; never silently overwrite evidence.
5. Expose a prioritized, explainable work queue (P1–P10 plus work type), ranked by risk
   and internal usage impact.

**The application**

6. Deliver the application as the primary human surface — each role reaching the
   evidence, queues, and reports it is responsible for — with a governed API serving
   integration and automation against the same evidence.
7. Provide a governed, read-only natural-language capability inside the application for
   investigation and reporting. It is a capability within the product, not the product
   itself, and every answer cites the evidence rows behind it.

## 5. Scope

v1 targets the Python subset of the conda inventory, where PyPI identity and Python
version readiness both apply. This is where the immediate compliance pressure sits and
where every check in the policy set is meaningful.

Non-Python conda artifacts — native libraries, compilers, system libraries, Rust
packages, R packages — are a stated later phase, not an exclusion. The data model
carries `not_applicable` as a distinct outcome from v1 so that checks that do not apply
to a package are never folded into clean or unknown; the later phase exercises that path
at scale rather than introducing it.

## 6. Non-Goals

v1 does not:

- Build a general package manager or conda channel.
- Auto-remediate, including auto-PRs or automatic upgrades.
- Replace existing issue trackers — v1 integrates with them instead, including
  OpenTeams-style issue URLs.
- Treat a model-generated answer as authoritative without the evidence behind it.

## 7. Success Metrics

**Evidence and collection**

- At least 95% of the targeted packages have a resolved identity (verified or
  inventory-derived) within the first full collection cycle.
- Every CVE, KEV, license, and Python 3.14 finding has source, timestamp, and
  confidence; no unknown is presented as clean.
- A weekly automated full-inventory refresh completes without manual intervention.

**The application**

- A reviewer can carry an unmapped package from the review queue to a resolved,
  attributed identity entirely within the application, without a database console.
- Each of the three roles can reach its own queue and its own current-health view
  without being granted access to another role's surface.
- Natural-language answers are traceable to the underlying evidence rows and do not
  invent figures.

## 8. Open Questions

- Which advisory and KEV data sources are available and licensed for use?
- What license allow/deny policy should seed evaluation?
- What is the source of internal usage fields such as platform, app, and download counts?
- Which conda channels and platforms are in scope?
- Does the internal-data handling requirement force a private or self-hosted model
  deployment for the natural-language layer?
