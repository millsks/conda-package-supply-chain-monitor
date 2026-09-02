---
title: "Project Brief — Conda-Forge Package Health Monitor"
status: final
created: 2026-09-02
updated: 2026-09-02
---

# Project Brief — Conda-Forge Package Health Monitor

## 1. Problem Statement
A ~10,000-package Conda/Python inventory currently has no unified, evidence-based view of version currency (source vs. PyPI vs. conda-forge feedstock), CVE/KEV exposure, license compliance, Python 3.14 readiness, and feedstock existence/maintenance status. Assessments are manual, fragmented, and go stale quickly. There is no auditable trail showing why a package was flagged.

## 2. Vision
Build a system that continuously collects evidence from source repositories, PyPI, and conda-forge; evaluates that evidence against explicit deterministic policies; and exposes results through a queryable database and natural-language interface. Use LangChain agent tools, LangFlow orchestration, and DB-GPT for governed read-only NL-to-SQL analytics.

## 3. Goals
1. Establish a reliable identity-resolution layer mapping each package to its Conda name, PyPI name, source repository, and conda-forge feedstock.
2. Continuously collect version/state facts from source, PyPI, feedstock recipe, and published Conda package surfaces.
3. Evaluate deterministic policies for version currency, CVE/KEV exposure, license compliance, Python 3.14 readiness, and feedstock existence/health.
4. Persist findings as timestamped, sourced evidence; never silently overwrite evidence.
5. Expose a prioritized, explainable work queue (P1–P10 plus Work type), ranked by risk and internal usage/impact.
6. Provide a natural-language query/reporting layer over the evidence store.

## 4. Non-Goals
- Build a general package manager or Conda channel.
- Auto-remediate in v1, including auto-PRs or automatic upgrades. v1 is detection, evidence, and prioritization only.
- Replace existing issue trackers. v1 integrates with them, including OpenTeams-style issue URLs.

## 5. Success Metrics
- At least 95% of the 10,000 packages have a resolved identity (verified or inventory-derived) within the first full collection cycle.
- Every CVE, KEV, license, and Python 3.14 finding has source, timestamp, and confidence; no unknown is presented as clean.
- A weekly automated full-inventory refresh completes without manual intervention.
- Natural-language queries are traceable to underlying evidence rows and do not invent figures.

## 6. Stakeholders / Users
- Security and compliance reviewers: CVE, KEV, and license assessment.
- Packaging engineers: feedstock currency and Python 3.14 readiness.
- Platform and engineering leadership: prioritized reporting and dashboards.
