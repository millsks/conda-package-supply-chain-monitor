# Extraction: prd.md — journeys, roles, surface constraints

## The three protagonists (the entirety of the persona material)

| Name | Role | Cadence | Entry surface | Context the PRD gives |
|---|---|---|---|---|
| **Dana** | security and compliance reviewer | daily ("already authenticated from yesterday's session", "before standup") | **the queue** | time-pressured, short morning session |
| **Ravi** | packaging engineer | none stated | **a report** (feedstock-gap) | session spans two systems; files into an external issue tracker |
| **Sam** | platform lead | **monthly** ("before a monthly review") | **the coverage view** | produces a review deck; only actor who can correct governed reference data |

Pronouns: all three they/them in the PRD.

No persona section, no expertise level, no device context, no frequency beyond the above. That is deliberate (the PRD's own rubric calls it "the right density... without a UX narrative this product does not need"). **Expertise, frequency and device context are ours to assert.**

## The journeys (verbatim beats)

### CPM-UJ-1 — "Dana clears a KEV finding before standup." (prd.md:82-90)
Queue leads with three KEV findings ranked P1. Opens top one, sees **six fields at once**: advisory ID, affected range, fixed range, matched version, source, observation time. Fixed range already on conda-forge, so marks for remediation → routes to packaging engineer's queue **with evidence attached**.
**Edge case:** vulnerability evidence past freshness target → finding shows **stale rather than actionable**, and Dana can trigger a recollection instead of acting.
→ Stale is a distinct visual state that **swaps the primary action** from "act" to "recollect".

### CPM-UJ-2 — "Ravi files the feedstock that never existed." (prd.md:92-101)
Opens feedstock-gap report: packages with no feedstock and no staged recipe, **ranked by internal usage breadth**. Opens highest-impact package, confirms from the **identity panel** that mapping is `verified` rather than inferred, sees no feedstock URL on any monitored channel. **Drafts a tracking issue from the package detail view**, carrying identity + usage counts + evidence rows. Files it; tracking URL recorded.
**Edge case:** an `unmapped` package **never appears** in this report — absence of a feedstock cannot be claimed for unresolved identity.
→ "identity panel" is a named component. Draft composition is a named interaction.

### CPM-UJ-3 — "Sam sees where the coverage gaps are." (prd.md:103-112)
Opens **coverage view** before monthly review. Three metric families: fraction of inventory with resolved identity, evidence inside freshness target **per collector**, which collection runs failed **and why**. A collector failing against a rate-limited source for two days → its packages show `error`, **not clean**. Exports current-inventory view for the deck; export carries **same freshness and confidence columns** as the app.
**Edge case:** wrong upstream repo → corrects it **from the package detail view**, the one write that changes governed reference data, recorded with identity and **a required reason**.

## The five states — the central rule

**CPM-FR-6 (prd.md:221-228):** `not_applicable`, `unknown`, `not_found`, `error`, and a successful clean result are **five distinct, separately displayable states everywhere they appear. No rollup, view, export, or generated answer collapses them.**

Every status cell in every table needs five visually distinguishable states, not two.

Reinforcing rules:
- CPM-FR-38: stale never displays as clean; failures visible in the app, not only logs.
- CPM-FR-37: **every displayed status is accompanied by the observation timestamp behind it.**
- CPM-FR-17: KEV membership always distinguishable, **never averaged into severity**.
- CPM-FR-10: each monitored channel produces its own observation; **channels are never merged**.
- CPM-FR-16: currency computed **per surface** — source-current and feedstock-stale must be expressible simultaneously. Four surfaces side by side: source, PyPI, feedstock recipe, published conda.

## THE PRIMARY FAILURE MODE (design constraint above all others)

**CPM-SM-C1 (prd.md:746-748):** "Proportion of packages showing a clean result... **Driving this up by resolving `unknown` or `unmapped` into clean is the primary failure mode of the entire product.**"

Any design that visually flattens `unknown` toward `clean` — soft grey that reads as "fine", an empty cell, a green-by-default row — actively causes the failure the product exists to prevent.

**CPM-SM-C2 (prd.md:749-750):** "Time to close a queue item... **Faster is not better** if overrides are recorded without a substantive reason." → do not optimize the override flow for speed.

**CPM-SM-C3 (prd.md:751-752):** the NL capability "succeeds by being traceable, not by being used often" → do not make it a prominent entry point.

## Confidence — a three-tier presentation treatment (CPM-FR-5, prd.md:211-219)

- `verified` — automated comparisons and recommendations **shown normally**
- `inventory-derived` — recommendations **shown labeled lower confidence**
- `unmapped` — the system **never reports the package as current, clean, or lacking a feedstock**; routes to the review queue instead

## Roles: what each reads and acts on

| Role | Reads | Acts on |
|---|---|---|
| Security and compliance reviewer | vulnerability, KEV, licence findings with evidence and confidence | licence exception review; risk acceptance |
| Packaging engineer | feedstock currency and presence, version lag, Python 3.14 readiness | the remediation work queue |
| Platform and engineering leadership | prioritized rollups, coverage, evidence freshness, collector health | prioritization and reporting decisions |

**The sharpest surface constraint (CPM-FR-31, prd.md:547-554):** "**Read access to evidence is available to all three roles; queues are role-exclusive.**"

Only the platform lead may override a package identity; the other two roles are refused (CPM-FR-3, prd.md:194).

## ⚠ Queue-to-role mapping is NOT stated, and the PRD's list order misleads

FR-25 lists "identity review, remediation, compliance review" in an order that positionally maps onto the role order as security→identity, packaging→remediation, leadership→compliance. **The brief's role table and FR-3's override permission imply the opposite pairing for first and third.** The PRD's own rubric flags this (medium) and prescribes stating it as a table.

Defensible pairing from the permission model:

| Queue | Role | Basis |
|---|---|---|
| Compliance review | Security and compliance reviewer | brief role table; FR-13 manual-review route |
| Remediation | Packaging engineer | brief explicit; prd.md:87 explicit |
| Identity review | Platform and engineering leadership | FR-3 override permission; JTBD; FR-4 exit condition |

**This is a decision the UX spec must make and flag, not one the PRD made.**

## Queue mechanics

- Ranked by **priority bucket then score** (FR-25) — except the identity queue, which FR-4 ranks by **internal usage breadth**. FR-4 and FR-25 conflict on this one queue.
- Identity queue: lists every `unmapped` and `inventory-derived` package; a package leaves **only when confidence reaches `verified`**; shows candidate mappings and the evidence for each.
- Override write is **rejected without a reason** (prd.md:196-197).
- Remediation items gated by CPM-FR-41 readiness: `ready`, `blocked`, `unknown`, plus stale. "A fix that exists nowhere yet is `blocked`, distinct from `ready` and from `unknown`."
- Closed work-type set (Appendix A.1): fix vulnerability · create recipe · file tracking issue · already tracked · update feedstock · validate Python 3.14 · review licence · resolve identity.
- **§6 Non-goal:** "CPM-FR-25 routes work to a human; **it never acts**." No automated remediation.
- Priority explainability: three fields must sit next to any priority — `priority_description`, `priority_source`, `priority_reason` — "so the result is explainable **without reading the rule set**".

## Export contract (Appendix A.1, prd.md:846-873)

Stored field names and export column names are **two different contracts**. Export columns preserve **historical report headings existing consumers read**. Notable headings: `Core_Python_Package_Name`, `P`, `Rank`, `Score`, `Work`, `Vuln`, `Platforms`/`Apps`/`Downloads`/`Versions`, `Conda-Forge_FeedStock_URL`, `Local_Build_Status`, `Verification_Timestamp_UTC`, `Priority_Bucket_Description`/`Priority_Source`/`Priority_Reason`, `JFROG_risk_level`, `OpenTeams_Title`.

**"Blank means missing; values are never invented. Multi-value export columns separate with `;`."**

## What the PRD does NOT specify — the UX contract must originate all of it

- **Accessibility: zero statements.** No WCAG, contrast, screen reader, or keyboard mention in 917 lines.
- **Browser/device/responsive: zero statements.** No matrix, no mobile assumption, no dark mode.
- **No density guidance, no visual hierarchy, no navigation model, no IA statement** beyond the named surfaces.
- **"Dashboard" appears exactly once — in the out-of-scope list** (prd.md:721, "Historical trend dashboards beyond queryable history").
- No sort keys specified (sorting is named, keys are not).

## Vocabulary constraint on all UI copy

**§3 Glossary preamble (prd.md:116):** "Downstream artifacts **must use these terms exactly**. 'Identity' alone is never used."

Two overloaded-term traps:
1. **package identity** vs **user identity** — never abbreviate either to "identity".
2. **Confidence** (`verified`/`inventory-derived`/`unmapped`, package identity only) vs **Match confidence** ("the separate, unrelated certainty that a vulnerability advisory applies to a given package and version. **Never abbreviated to 'confidence'**"). The rubric flags the PRD violating its own rule here (high severity). **Our copy must pick a side.**

## Surfaces named in journeys with no FR behind them

1. **The feedstock-gap report** (UJ-2's central artifact). FR-26 lists "weekly feedstock lag" which is *currency, not presence*. Reachable only by inference through FR-23 filtering. Policy source exists (CPM-FR-40: absent / present-and-maintained / present-and-inactive / staged-recipe-pending) but no report surfaces it.
2. **The coverage view** (UJ-3's entry surface). Named as a view; closest FR-26 entry is "stale-evidence and collector failures". Its three content areas exist only in journey narrative.
3. **Tracking-issue draft composition + tracking-URL write** (UJ-2). Rubric high severity: no FR provides it, and **the write is forbidden by FR-3/FR-27 as written**.
4. **Trigger a recollection** (UJ-1 edge case). No FR grants any role the ability to initiate one; it is another write.
5. **Export of the current-health view** (UJ-3). Only FR-26 carries an export consequence; FR-23 does not.

## Blocked numbers (do not invent)

- **OQ 5:** p95 latency budget and inventory size at which it is measured.
- **OQ 7:** per-collector freshness targets are undefined — yet "stale vs actionable" is the pivotal state change in UJ-1.
- **OQ 8:** priority rule set and score function are undefined. **P1-P10 have no defined content**, yet every queue is "ranked by priority bucket then score". The primary ordering of every queue is unspecified.

## Auth model

OIDC only; no local password auth in any deployed environment. Group claims resolve to roles; mapping is configuration, not code. An authentication carrying **no group claim is refused**, and is **distinguishable from** one asserting **zero groups** — two different refusal states the UI must express. Refused authorization is a logged event, so the UX needs a defined refusal state.

Assume returning, session-persistent users (UJ-1 entry: "already authenticated from yesterday's session"). No sign-in screen in the happy path.

## Scale
~10,000 packages, firm ceiling. v1 targets the Python subset only; non-Python conda artifacts modeled via `not_applicable`. Inventory is a curated watchlist versioned in-repo, changed by pull request.
