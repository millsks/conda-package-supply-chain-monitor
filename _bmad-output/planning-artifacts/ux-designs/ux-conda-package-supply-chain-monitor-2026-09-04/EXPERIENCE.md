---
title: CPM Experience Spine
project: conda-package-supply-chain-monitor
scope: CPM-EP-APP
status: final
updated: 2026-09-04
design_spine: ./DESIGN.md
sources:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - imports/ui-mockups.html
---

# Conda Package Supply Chain Monitor — Experience Spine

This document owns **behaviour**: information architecture, states, interactions, accessibility, and the three journeys. `DESIGN.md` owns **every visual specification** — colour, type, spacing, radii, shadow, marker geometry. Where this document needs to name a visual thing it references a token by path, e.g. `{colors.unk}` or `{components.chip}`. It never restates a value.

Where this spine and the mockup at `imports/ui-mockups.html` disagree, **this spine wins**. The mockup is a specimen book, not a contract; several of its inconsistencies are resolved below, and the resolution is stated each time.

---

## Foundation

**Form factor.** Desktop web. Server-rendered. One surface, no companion app, no mobile layout in v1 (see G-6).

**Stack.** Django templates rendered server-side, `django-crispy-forms` + `crispy-bootstrap5` for every form, **HTMX** for four named interactions, **Alpine.js** for view state only. Bootstrap 5.2.3 from CDN with SRI supplies grid and utilities; **CSS custom properties in `static/css/project.css` own semantic colour and every semantic component** (`.chip`, `.ev`, `.freshbar`, `.tbl`), overriding Bootstrap defaults. `djangorestframework` + `drf-spectacular` serve the governed API alongside.

**No build step.** No npm, no bundler, no JS framework, no CSS preprocessor. Both libraries load from CDN as plain script tags. Proof this is sufficient: the mockup renders the entire token system in 2,911 lines with zero script tags.

> The ARCHITECTURE-SPINE names neither HTMX nor Alpine. This spine codifies the boundary below, and **CPM-EP-APP should raise a follow-up to promote it to a spine invariant** — as written, the interaction technology is unconstrained *and unprotected*.

**Users.** Returning, session-persistent, authenticated via OIDC. Group claims resolve to roles; the mapping is configuration, not code. There is **no sign-in screen in the happy path** — Dana's journey opens with "already authenticated from yesterday's session". No local password path exists in any deployed environment.

**Three roles**, and what each may do:

| Role | Reads | Acts on |
|---|---|---|
| Security and compliance reviewer | vulnerability, KEV and licence findings, with evidence, package-identity confidence and match confidence | the compliance review queue |
| Packaging engineer | feedstock currency and presence, version lag, Python 3.14 readiness | the remediation queue |
| Platform and engineering leadership | prioritised rollups, coverage, evidence freshness, collector health | the package-identity review queue; **the only role that may override a package identity** |

**Read is shared. Act is scoped.** All three roles read all evidence, including every package identity and its provenance (CPM-FR-31, CPM-AD-13). Only queue *access* and queue *transitions* are scoped.

**Scale.** ~10,000 packages, a firm ceiling. The inventory is a curated watchlist versioned in-repo and changed by pull request — it does not grow by user action. Every list is paginated, structurally, and pagination cannot be opted out of.

**The constraint above all others (CPM-SM-C1).** Driving the clean-result proportion up by resolving `unknown` or `unmapped` into clean is *the primary failure mode of the entire product*. Any treatment that flattens `unknown` toward clean — a soft grey that reads as fine, an empty cell, a green-by-default row — actively causes the failure the product exists to prevent. This outranks every convenience and every aesthetic consideration in this document and in `DESIGN.md`.

---

## Information Architecture

### The platform constrains the nav severely — state the constraints first

Navigation is contributed to `NAVIGATION_REGISTRY` (`src/config/startup/allowlist.py:324-345`). An entry is **data, never markup**: a label string (auto-escaped), a **URL name** (not a path), and an optional permission the renderer filters on.

Four consequences the implementer cannot design around:

1. **No markup in an entry.** No icons, no nested submenus, no rich labels.
2. **A queue-count badge in the nav is impossible.** "Remediation (14)" cannot be built — the registry carries a static label string and nothing computes into it. Counts live in the content area (the home stat cards, the page-header subtitle, the pager line) and nowhere else.
3. **Order is inherited from `adopted_apps` order and cannot be specified.** `reporting` and `workflow` each contribute append-only; neither can reorder the other's entries, its own relative to Home/About/Profile, or the platform's.
4. **There is no side nav, tab bar, or breadcrumb mechanism in the platform.** Every navigation affordance richer than the flat top nav is **in-page navigation designed from scratch inside the content area**.

### Nav filtering is presentation, never authorization — both halves

The optional permission on a registry entry **only hides the link**. The registry is permitted where `MIDDLEWARE` and `AUTHENTICATION_BACKENDS` are refused precisely because *it confers presentation and never authorization*.

- **Half one:** a role that may not use a surface does not see its nav entry.
- **Half two:** **the view must still refuse that URL when typed, pasted, or bookmarked**, and log the refusal with the acting user identity (CPM-APP-S05 / APP.05-API-004). A hidden link is not a security boundary. Every role-scoped view carries its own check regardless of what the nav rendered.

Permission is therefore checked twice on every scoped surface. That is deliberate, not redundancy to be optimised away.

### The nav model — resolved

The mockup's nav is inconsistent across screens: S7/S8 swap `My queue` → `Identity queue`, S11 swaps `Coverage` → `Investigate`, and S10 omits `Coverage` where S6/S9 render it with a `.locked` treatment. Same role, two treatments. **Resolution — one model, identical for every role, on every screen:**

| Label | Contributed by | URL name | Permission filter |
|---|---|---|---|
| Packages | `reporting` | `reporting:package_list` | none |
| My queue | `workflow` | `workflow:my_queue` | none |
| Reports | `reporting` | `reporting:report_index` | none |
| Coverage | `reporting` | `reporting:coverage` | none |

Plus the platform's own Home / About / Profile entries, whose position we do not control.

Four rules follow:

- **`My queue` is the label for all three roles.** It never becomes "Identity queue" or "Remediation queue". `workflow:my_queue` resolves server-side to the caller's own queue, so this entry can never 403. The queue's *own page heading* names it precisely ("Package-identity review", "Remediation work queue", "Compliance review"); the nav label stays constant so the nav does not leak role structure and does not need per-role variants the registry cannot express.
- **`Coverage` is present for every role, always.** Coverage is read-only evidence, and read is shared. The mockup's `.locked` styling on S9 and its omission on S10 were both wrong. **The `a.locked` treatment is deleted from the system** — a link that looks disabled is a worse answer than a link that works, and if an entry ever genuinely must not be offered, the registry's permission filter hides it entirely.
- **`Investigate` is not in the v1 registry.** The NL capability is post-MVP (CPM-EP-NL) and read-only. It never replaces `Coverage`; when it ships it is an additional entry contributed by its own app.
- **No v1 entry carries a permission**, because every surface in the flat nav is readable by all three roles. Role scoping happens *below* the nav — at the deep queue URL, at the item, and at the transition. State this explicitly so a future contributor does not mistake the empty permission column for an absence of authorization.

### In-page navigation carries what the platform cannot

Everything the platform cannot give us lives in the content area:

| Pattern | Where | Behaviour |
|---|---|---|
| Report index card grid | `/reports/` | Six cards, one per recurring report, each stating its counts, produced time and policy version. This is the "tab bar" the platform does not have. |
| Faceted sidebar | `/packages/` | Filter groups with counts, `{components.split}`. Swaps the table, not the page. |
| Applied filter bar | `/packages/`, queue pages | Removable filter pills plus a right-slot sort statement. |
| Text trail | package detail, finding detail | `packages / aiohttp` rendered as an `{components.ev}`-styled eyebrow above the `<h1>`. **This is not a breadcrumb component** — it is a one-line text trail with a single link back to the list, because the platform has no breadcrumb mechanism and inventing one would be a second navigation system. |
| Row link | every table | The package name is the link out of a list, and it is the row's only link. Where the rest of the row's actions live is in Interaction Primitives. |

### Surface inventory — eleven mockup screens against eight CPM-APP stories

| # | Screen | Route | Story | Note |
|---|---|---|---|---|
| S1 | Sign-in; the claim that carries no role | `/accounts/login/` | **none** | Platform-owned, outside CPM-EP-APP. The zero-groups variant is described but never drawn (G-4). |
| S2 | Home — "Good morning, Dana" | `/` | **none** | Four stat counters and two panels of real UI with no acceptance criteria behind them (G-8). |
| S3 | Current package health | `/packages/` | **CPM-APP-S02** | The flagship. Filters on derived status, package-identity confidence, priority bucket, work type. |
| S4 | Package detail traced to evidence | `/packages/<name>/` | **CPM-APP-S03** | Evidence disclosure, superseded rows, package-identity panel and override display. |
| S5 | Finding detail and routing | `/queues/<queue>/<item>/` | **CPM-APP-S05** (surface), **S04** (model) | The route modal; the audit table is S04's only visible artifact. |
| S6 | The remediation queue | `/queues/remediation/` | **CPM-APP-S05** | Bucket-then-score ranking, readiness column, bulk selection. |
| S7 | Package-identity review and override | `/queues/identity/<name>/` | **CPM-APP-S05** (queue only) | The override write itself is CPM-AD-14 / CPM-FR-3, owned by **CPM-EP-IDENTITY**, not CPM-EP-APP. The queue is APP's; the modal is IDENTITY's. Flag the seam. |
| S8 | Coverage and collector health | `/coverage/` | **CPM-APP-S06** (partial) | Only report 6 (stale evidence and collector failures) is covered. The coverage *view* — Sam's journey entry — has no FR and no story (G-9). |
| S9 | Reports and export | `/reports/<slug>/` | **CPM-APP-S06** + **S08** | The async export branch lives here. |
| S10 | Refused (403) and in-progress | any scoped URL; any `?job=` URL | **CPM-APP-S01** + **S08** | Two states, both designed. |
| S11 | Investigation (NL) | `/investigate/` | **CPM-EP-NL** | Post-MVP, read-only. Out of scope for CPM-EP-APP; its evidence citation table is inherited from here. |

**Stories with no screen:**

- **CPM-APP-S01** (pagination and role checks, configured once) — cross-cutting. Its only visible artifacts are the pager line and the 403 page. The mockup's pager offers no page-size selector and no prev/next arrows, which is correct and deliberate: page size is a global setting, not a user choice. The Pager row in Component Patterns carries the full rule.
- **CPM-APP-S04** (one workflow table keyed on a stable finding key) — model-only. Its visible consequence is a single audit row on S5 reading *re-observed; not recreated as new work*. That row is the **entire** user-visible proof of the story and must not be dropped as noise.
- **CPM-APP-S07** (a governed, documented API) — **no screen at all.** `drf-spectacular` renders a Swagger/Redoc page that nobody has designed and nobody has decided whether to put in the nav (G-7).

**Screens with no story:** S1, S2, S11, and the coverage-view half of S8.

### The health view carries eleven fixed columns

CPM-APP-S02 is the flagship surface and the one most likely to be built from an implementer's assumption, so its columns are stated rather than left to inference. Eleven columns, in this order:

| # | Column | Content | Notes |
|---|---|---|---|
| 1 | Package | Canonical name as a link to package detail, with the installed version in the footline | The only link in the row |
| 2 | P | `{components.pbucket}` | Bucket only; the four colour bands, not ten |
| 3 | Score | Right-aligned tabular mono | 1–100, ranks within a bucket |
| 4 | Work | Derived work type, plain text | From the closed set in PRD Appendix A.1 |
| 5 | Currency | Status chip + footline | This column is the rollup verdict; package detail shows all four surfaces separately (CPM-FR-16) |
| 6 | Vulnerability | Status chip + footline | Severity only |
| 7 | KEV | Status chip + footline | **Its own column. Never folded into column 6** (CPM-FR-17) |
| 8 | Licence | Status chip + footline | |
| 9 | Py 3.14 | Status chip + footline | Inferred and verified stay distinguishable (CPM-FR-19) |
| 10 | Feedstock | Status chip + footline | `unmapped` packages read `unknown` here, never `not_found` — absence cannot be claimed for an unresolved package identity |
| 11 | Pkg identity confidence | `{components.conf}` text tag + footline naming the source | Package-identity confidence, in its permitted short form (rule V3). Deliberately not a chip |

Every one of columns 5–10 is a status cell, so every one carries a chip **and** a footline, and every one is capable of all five outcome states. A row is therefore never blank across the middle of the table; a package nobody has assessed reads `unknown` six times, which is the point.

Columns are fixed in v1. There is no column chooser, no reorder, and no density toggle — three settings that would let two people look at "the same view" and see different things, which CPM-AD-24 exists to prevent.

**Sorting is stated, not offered.** The health view's sort appears in the applied filter bar as a fact, and the sorted column carries `aria-sort`. If clickable column sorts are added later, **only the cheap rollup columns may be sortable**: every derived status, `computed_at`, cut-off, version map, `priority_bucket`, `rank`, `score`, `work_type`, `vulnerability_rollup`, `risk_level`, `latest_vuln_count` and the three priority-explanation fields. The expensive set is a join away — `local_build_status` and `verified_at` project from evidence, while `platforms`, `apps`, `downloads`, `versions`, `internal_component_count` and `internal_lob_count` come from `inventory_snapshots`, where the correct read is "the latest snapshot at or before the cut-off". **The spine does not settle how to filter or sort those. Do not assume parity** (G-10).

---

## Voice and Tone

Microcopy only. Brand voice and aesthetic posture live in `DESIGN.md`.

The register is **a colleague stating what is true**. This product's job is to refuse to overclaim; the copy has to sound like it means it. No exclamation marks, no encouragement, no celebration, no emoji anywhere in the product.

| Do | Don't |
|---|---|
| "217 packages hold no vulnerability evidence." | "217 packages need attention!" |
| "Your compliance review queue has no open items." | "All clear — nice work." |
| "The package-identity queue belongs to platform and engineering leadership." | "You don't have access." |
| "1,091 rows exceeds the synchronous cap. The export is running as a job." | "This may take a while…" |
| "Recording `not_applicable` is a decision, not a blank." | "Leave blank if not applicable." |
| "An override without a reason is rejected." | "Please enter a reason." |
| Present tense for what is running. Past tense with a timestamp for what happened. | Vague futures: "will be updated shortly". |

### The vocabulary rule — we side with the glossary, not with the PRD's practice

The PRD's §3 glossary preamble is binding on downstream artifacts, and the PRD then violates its own rule in FR-11, FR-24 and FR-26. **This spine sides with the glossary. Every violation in the PRD, in the mockup, and in the existing column headings is corrected.**

- **V1.** The bare word *identity* never appears in UI copy. It is always **package identity** or **user identity**, written in full, every time. One exception: verbatim machine identifiers rendered in `{typography.mono-value}` — table names (`identity_overrides`), permission names (`queues.identity.list`), URL paths (`/queues/identity/`). Those are quoted code, not prose, and the mono face is what marks them as such.
- **V2.** The bare word *confidence* never appears as a standalone label, heading, facet name, or export column. Two full forms only: **package-identity confidence** (`verified` / `inventory-derived` / `unmapped`) and **match confidence** (how certain we are that an advisory applies to this package at this version).
- **V3.** Where a column heading must be short, the permitted short forms are `Pkg identity confidence` and `Match confidence`. **`Confidence` alone is not permitted.** The mockup's `Confidence` heading on S3 and S9 is corrected under this rule, as is its facet group heading, which becomes "Package-identity confidence".
- **V4.** The two are rendered by two different components so the visual channel reinforces the copy: package-identity confidence renders through `{components.conf}` (text-only, no marker); match confidence appears only inside the evidence disclosure table, in `{typography.mono-value}`, as a plain cell value. **Neither is ever a `{components.chip}`** — a confidence is not an outcome state.

### Status values versus chip labels — a closed set inside an open one

The mockup carries 60-plus distinct chip label strings across eight variant classes. Some are prose fragments; some carry interpolated data (`error · 429`, `stale · 31h`, `yes · 3.10.1`, `4 rows returned · limit 500`). The doctrine says values are "lowercase and verbatim" — but a label that is a sentence cannot be verbatim anything. **The rule that separates them:**

- **L1 — A status value is a member of a closed set defined once in Python.** `core.OutcomeState` (`not_applicable`, `unknown`, `not_found`, `error`, plus the determinate values) and the per-domain determinate enums. It is emitted lowercase, verbatim, unabbreviated, untranslated and unpunctuated — identically on screen, over the API, and in every export (CPM-AD-24, CPM-AD-5). Never pluralised, never sentence-cased, never suffixed.
- **L2 — Where a chip carries a status, the label *is* the value.** Nothing may be prefixed, appended, or interpolated. `critical · stale`, `error · 429` and `stale · 31h` are **illegal chip labels**. The chip's text comes out of the enum and out of nothing else.
- **L3 — Every qualifier goes on the `{components.ev}` footline.** The stale explanation, the HTTP code, the elapsed hours, the matched version, the trace id, the rule name. This is what makes L1 enforceable: the chip's text is an enum member, the footline is free prose, and the boundary between them is the boundary between a contract and a sentence.
- **L4 — Chips that do not carry an outcome status use `{components.chip-plain}`** (the markerless variant) and draw their labels from a *second* closed enumeration: workflow state names, run-ledger states (`running`, `succeeded`, `failed`, `idle`), readiness values (`ready`, `blocked`, `unknown`), and `superseded`. **The five outcome states are never rendered `.plain`.**
- **L5 — A string that belongs to none of these enumerations is not a chip.** It is body text, a table cell, or an `.ev` line. If a template author reaches for a chip and cannot name the enum the label comes from, the answer is that it is not a chip.

Net effect: three enumerations plus free-prose footlines, in place of an unbounded label vocabulary. Every illegal label in the mockup decomposes cleanly — `error · 429` becomes an `error` chip with `advisory · 05:40Z · 429 rate limited for 2 days · retries exhausted · trace 4c1f9a2e` beneath it, which is strictly more informative than what it replaced.

---

## Component Patterns

Behavioural only. Visual specification lives in `DESIGN.md.components`.

| Component | Token | Used on | Behavioural rules |
|---|---|---|---|
| Status chip | `{components.chip}` | everywhere a derived status appears | Rendered **only** by `{% status_chip %}`. Carries the status word as real text, a marker shape, a hue, and an `{components.ev}` footline — four redundant channels, never fewer. Never interactive; never a link, button, or tooltip trigger. |
| Plain chip | `{components.chip-plain}` | workflow states, run states, readiness, `superseded` | Markerless. Never used for an outcome status. |
| Package-identity confidence tag | `{components.conf}` | health table, package detail, reports | Text-only, no marker, deliberately a different component from the chip. `inventory-derived` is a *label on a shown value*, never a dimming and never a hiding. |
| Priority bucket | `{components.pbucket}` | health table, queues, detail headers | Renders `P1`–`P10`. **Always accompanied by `priority_description`, `priority_source` and `priority_reason`** — inline on detail surfaces, in the "Why this bucket" column on queues — so a bucket is explainable without reading the rule set (CPM-FR-25). A bucket rendered without those three is a defect. |
| Evidence footline | `{components.ev}` | under every value | Fixed grammar: `<source> · <observed_at> [· <qualifier>]`. See Evidence and Provenance. |
| Freshness bar | `{components.freshbar}` | every list, every detail page, every report, every export header | Rendered **only** by `{% freshbar %}`. Mandatory chrome, not a disclosure. |
| Data table | `{components.tbl}` | all lists | Top-aligned cells so footlines hang below values. The row-hover tint is the only genuine hover in the product and carries **no meaning** — no affordance is hover-revealed. |
| Faceted sidebar | `{components.facet}` | health view only | Each facet is a labelled checkbox with a right-aligned count. Counts are server-computed and sum to the inventory. Sentinel states appear as **first-class facets**, never folded into an "other" bucket. |
| Applied filter bar | `{components.filterpill}` | health view, queues | One pill per applied filter with a real remove button; a right slot states the sort. |
| Pager | `{components.pager}` | all lists | States `showing X–Y of N`, the page size and the cap — **all three read from settings, never hard-coded**. The spine requires `PAGE_SIZE` and a maximum to be set globally in `REST_FRAMEWORK` but names only the former; the maximum is the DRF pagination class's `max_page_size`, and the HTML pager reads the same two constants the API does, so a view and its API equivalent can never disagree about what a page is. No page-size selector, no prev/next arrows, no infinite scroll. |
| Panel | `{components.panel}` | grouped content | Header with an optional right-slot metadata line, then body. No shadow — elevation is hairline plus fill. |
| Stat card | `{components.stat}` | home, coverage | A number, a label, and a footline that says what the number excludes. A stat card whose footline does not qualify the number is incomplete. |
| Toast | `{components.toast}` | in-progress, system speech | Not transient. Not auto-dismissed. Never stacked more than three deep. Survives reload when it carries a job id. `aria-live="polite"`. |
| Modal | `{components.modal}` | route, override, accept risk | One level deep, never two. `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, focus trapped, Escape closes, focus returns to the trigger. |
| Form field | `{components.field}` | modals, forms | Rendered by crispy-forms. Required marker on the label, help text below, server-rendered errors bound by `aria-describedby`. |
| Audit table | `{components.tbl}` | finding detail, package detail | Append-only, oldest first: when · who · from · to · what happened. Never paginated away; never collapsed by default. |
| Evidence disclosure | nested `{components.tbl}` | package detail | Inserted after the status row it belongs to. See Evidence and Provenance. |

---

## State Patterns

This is the heart of the document. The product's whole thesis is that it refuses to render a state it does not have.

### The five outcome states never collapse

CPM-FR-6: `not_applicable`, `unknown`, `not_found`, `error` and a determinate result are **five distinct, separately displayable states everywhere they appear. No rollup, view, export or generated answer collapses them.**

| State | Means | Marker | Hue |
|---|---|---|---|
| determinate | A policy pass ran, evidence was present and sufficient, and it reached a conclusion. Carries a domain value (`critical`, `lagging`, `allowed`, `maintained`, …). | filled | `{colors.ok}` / `{colors.warn}` / `{colors.crit}` |
| `unknown` | The question was asked and no answer could be established. | hollow ring | `{colors.unk}` |
| `not_found` | The question was asked and the answer is a well-established absence — no feedstock exists, no staged recipe exists. | dashed ring | `{colors.nf}` |
| `not_applicable` | The question does not apply to this package: a non-Python artifact, an internal-only package with no release ecosystem. **A recorded decision, not a blank.** | struck circle | `{colors.na}` |
| `error` | The collection or the policy pass failed. The question could not be asked. | triangle | `{colors.err}` |

Two structural properties make this hold:

- **The four sentinel hues sit deliberately off the green–amber–red determinate ramp**, so a sentinel cannot be misread as a position on a severity scale. `DESIGN.md` owns the values; this spine owns the requirement that they stay off the ramp.
- **Precedence is defined once, in `core`, as one total order.** The UI never re-derives it, never re-labels a value, never invents a sixth state, and never sorts statuses by anything other than that order.

**Three further no-collapse rules, exact siblings of CPM-FR-6 and equally binding.** Each has a direct rendering consequence, and nothing in the visual system prevents an implementer from violating them by accident:

- **KEV membership is never averaged into severity (CPM-FR-17).** KEV is its own column with its own chip, never folded into a vulnerability severity value and never used to nudge one upward. A `listed` KEV chip beside a `high` severity chip is two facts; a single `critical` chip standing for both is a collapse.
- **Monitored channels are never merged (CPM-FR-10).** Each channel produces its own observation. Where a package is published to more than one channel, the detail view shows one row per channel with its own value and its own footline. A single "published version" that silently picks a winner is a collapse.
- **Currency is computed per surface (CPM-FR-16).** Source, PyPI, feedstock recipe and published conda are four independent surfaces, and "source-current, feedstock-stale" must be expressible and visible simultaneously. The packaging engineer's stated job is to see all four **at once**, so the detail view renders four values side by side — never one rolled-up "currency" verdict.

**The word `clean` is prose, not a value.** It appears throughout this document and throughout the PRD, and there is no `clean` member of `OutcomeState`. The PRD never defines one, and its own review rubric flags the omission. Each domain carries its own determinate good value instead: the vulnerability domain's is `none found`, the licence domain's is `allowed`, the feedstock domain's is `present`. "Clean" is shorthand for "a determinate result that is not adverse", and it is legitimate in prose, in a heading and in a counter-metric label. **It is never a chip label, never an enum value, and never a column heading.** An implementer who finds themselves writing `clean` into a template or a serializer has taken a wrong turn.

**Blank is reserved for a field with no value and is never used for a status.** A blank field renders as an em dash in `{typography.mono-value}` with no footline. A status cell always has a chip and always has a footline; the two are not confusable. The export applies the same separation — see The export contract.

Per CPM-APP-S02 OQ 3: `apps`, `platforms`, `downloads` and `versions` stay blank until a source supplies them. **Blank means missing — never zero, never estimated.** A zero in one of those columns is a claim, and we do not have it.

### Stale is a property of a status, not a status

**This corrects the mockup**, which rendered stale as an amber chip and thereby overloaded `{colors.warn}` three ways.

- `stale` is **not** a member of `OutcomeState`. It is a boolean property computed per evidence row against that collector's freshness target.
- **A stale status keeps its own hue and its own marker.** A stale `critical` renders `{colors.crit}` and reads `critical`. A stale clean result renders `{colors.ok}` and reads its own determinate value. Neither borrows amber.
- **What stale adds** is the stale marker specified in `{components.chip-stale-overlay}` plus an amber `{components.ev-stale}` footline naming the target it missed: `vulnerability_findings · observed 2026-08-29 · stale, target 24h`.
- **Consequence:** `{colors.warn}` now means exactly one thing — determinate amber (`lagging`, `medium`, `manual review`). The three-way overload is gone.
- **`blocked` moves off the outcome-status axis entirely.** It is a value on the CPM-FR-41 **readiness** axis: `ready` / `blocked` / `unknown`, with stale as a property there too. Readiness renders in its own column, through `{components.chip-plain}`, and never appears in an outcome-status column. Readiness and priority are independent: the queue tells you what you cannot do yet rather than hiding it. "A fix that exists nowhere yet is `blocked`, distinct from `ready` and from `unknown`."
- **Two axes never share a column.** Outcome status in one, readiness in another, package-identity confidence in a third.
- **Stale changes the action, not the value.** CPM-FR-38: stale never displays as clean. On a finding whose evidence is past target, the transition table is evaluated against a stale finding and routing is not offered; the primary control reads **Recollect evidence** instead of **Route**. This is the pivot in Dana's journey, and it is a server-side decision, not a template condition.

### Package-identity confidence gates in the policy layer, never in the view

CPM-FR-5 and CPM-AD-5 define a three-tier treatment. The critical implementer note first:

> **The view does not implement the gate.** The policy layer writes gated statuses as `unknown` *before* the rollup row exists. The application reads derived state and never computes it (CPM-AD-10). If a view finds itself branching on package-identity confidence to decide what status to show, that is a bug — the value it should show is already in the rollup.

| Package-identity confidence | Treatment |
|---|---|
| `verified` | Comparisons and recommendations shown normally. |
| `inventory-derived` | Shown **with a `{components.conf}` label. The value is not degraded.** Not greyed, not hidden, not softened, not converted to `unknown`. The label is the whole treatment. |
| `unmapped` | Every gated status is written `unknown`. The package **never** reads as current, as clean, or as lacking a feedstock. It is routed to the package-identity review queue. |

An `unmapped` package **still appears in every list and still holds exactly one rollup row** (CPM-AD-11: one row per inventory package, always). It is never hidden, never silently filtered out, never dropped from a count. The UX guarantee this buys: **counts across every filter sum to the inventory**, and no package can vanish from a filtered list because policy skipped it.

The one place `unmapped` is legitimately excluded is the feedstock-gap report — absence of a feedstock cannot be claimed for a package whose package identity is unresolved (APP.05-API-002). **That exclusion is stated on the surface**, in the freshness bar's `excludes` cell, with the count and the reason, linking to the unmapped-identities report. An exclusion the reader has to discover is a defect.

### Operational states

| State | Surface | Treatment |
|---|---|---|
| Loading (facet swap) | health view | HTMX `hx-indicator` on the table region only; the page never reloads. The result count is `aria-live="polite"` so the swap announces "1,204 of 9,842 packages". No skeleton rows — the previous table stays until the new one arrives. |
| In progress | any surface that enqueued work | Specified below. |
| Refused (403) | any role-scoped URL | E1 below. |
| Empty | queues, health view, first run | E2–E4 below — **designed here; the mockup has none.** E5 sits with them for contrast but is a field convention, not an empty state. |
| Not found (404) | package detail, finding detail | Designed here. |
| Server error (500) | any | Designed here. |
| Session expired | any, especially mid-HTMX | Designed here. |
| Collector `error` | health view, coverage | **Not a page error.** It is a status on a row and a row in the collector-health table. It is never routed to an error page and never suppressed into a log. Each carries error detail and a `trace_id`, and the trace id is a link (CPM-APP-S06). |

### The in-progress state — specified

The ARCHITECTURE-SPINE requires that "the request returns an in-progress state" and never says what that is. The spine's own note calls this "the one place where the absence of a stated interaction technology bites hardest". This closes it.

**Trigger.** Any of CPM-AD-9's four: an outbound call, a collector run, a policy pass, or an export beyond `settings.CPM_SYNC_EXPORT_MAX_ROWS`. Everything else — reads of derived state and evidence, workflow writes, the package-identity override — is synchronous and must not use this state.

**Response.** `202 Accepted` with a job id. The job id is appended to the current URL as `?job=<id>`. **Job state is server-side, keyed by that id.** The banner therefore survives a reload, survives a new tab, and survives navigating away and returning to the same URL. Closing the tab does not cancel the job.

**Render.** A `{components.toast}` above the content, containing, in order:

1. A spinner, `role="presentation"`, decorative. Suppressed under `prefers-reduced-motion` — which is why it is never the only signal.
2. One line, present tense, naming what is running: "Verification build running on linux-64", "Preparing your export".
3. Where the reason is a threshold, the reason: "1,091 rows exceeds the synchronous cap". **The number comes from settings, interpolated at render.** No template hard-codes it.
4. Job id and trace id, in `{typography.mono-value}`.
5. Queued time, started time, and a duration estimate expressed as an honest range. **Where no estimate exists, the toast says so** rather than guessing.
6. A Cancel control.

**The "Meanwhile, what is known" panel is mandatory** beside every in-progress toast. It shows the current values, unchanged, with their own footlines, and states explicitly what the job will write when it lands — including that **nothing is updated in place; a new evidence row is inserted**. This panel is the anti-optimistic-UI affordance: the page shows what is true now, never what is hoped.

**Polling — and what it must not swap.** The naive form (`hx-swap="outerHTML"` on the whole toast, every 3s, inside an `aria-live` region) is unusable: it resets keyboard focus to `<body>` every three seconds so the **Cancel button can never be reached**, and it re-announces the entire toast every three seconds for the life of the job. Both are disqualifying.

The toast is therefore **two regions, and only one of them polls**:

- A **static shell** — the job id, the trace id, the start time and the **Cancel button** — which is rendered once and never swapped. Focus and the Cancel target are stable for the whole job.
- An **inner status node** carrying the phase and the elapsed time, which is what `hx-get="/jobs/<id>/"` with `hx-trigger="every 3s"` replaces. It is `aria-live="polite"` with **`aria-atomic="false"`**, and the server emits announceable text **only on an actual phase change** — not on every tick. A ticking elapsed time is visual only, marked `aria-hidden="true"`.

**Nothing else on the page polls**, and the page itself never reloads. The terminal fragment carries no `hx-trigger` — that is how polling stops, and it is also the announcement of completion. The client does not decide.

The poll interval is a settings constant, not the literal above.

**Terminal states.**

- *Succeeded, export:* the toast becomes a download link. It does not auto-download.
- *Succeeded, collection or policy:* the toast becomes a line stating what was written, offering a link to reload the surface. **It never reloads the page under the user** — a page that changes while being read is exactly the failure mode this product is about.
- *Failed:* the toast becomes an error-hued block carrying the failure detail and the trace id, satisfying CPM-APP-S06's requirement that failures be retrievable in the application layer, not only from logs.
- *Cancelled:* stated plainly, with the time.

**Bounded polling.** After a ceiling the fragment stops self-polling and offers a manual Refresh. `[ASSUMPTION: no source sets this ceiling. It must be a settings constant, not a template literal. Celery's inherited limits — a 5-minute time limit and a 60-second soft limit, with work exceeding them chunked per package rather than raised — bound the underlying job but do not bound the poll.]`

### The empty states — designed here

The mockup has **no generic empty state**: no "your queue is empty", no zero-results, no first-run. Five states get mistaken for one another, and conflating any two of them is a bug.

**E1 — Refused is not empty.** Doctrine, from the mockup's own screen map: *a queue that is not yours is refused, never rendered empty.* An empty queue and a forbidden queue mean opposite things, and rendering a forbidden queue as empty tells the user their colleagues have no work.

The 403 page carries:

- A `403 · refused` chip **in `{components.chip-plain}`, the markerless variant.** An HTTP status is not an outcome state, and drawing it on the determinate ramp — as the mockup did, with `.chip.crit` — puts a non-outcome fact in the vocabulary reserved for the five. The same applies to the 404, 500 and session-expiry chips.
- A heading naming **which role owns the surface**.
- A sentence stating that reading is permitted and acting is a separate grant.
- A key-value panel: `your role`, `required`, `surface`, `request id`, `logged: yes, with your user identity`.
- Two actions — back to your own queue, and the read-only view of the same object.

Vague refusals generate support tickets; specific ones generate a correct request to an administrator.

**E2 — A legitimately empty own-queue.** Undesigned in the mockup; designed here. The freshness bar **still renders** — provenance is mandatory chrome even with zero rows. The copy names the queue and states the emptiness plainly: "Your compliance review queue has no open items." Then, in the same block and non-optional, **the counter-line**: what is *not* in this queue because it could not be assessed. "217 packages hold no vulnerability evidence and are not in this queue." An empty queue must never be readable as "everything is fine" — that is CPM-SM-C1 arriving through the back door.

**E3 — Zero results under a filter.** Distinct from E2. The applied filter pills stay, the count reads `0 of 9,842`, the facet counts stay visible so the reader can see which facet is at fault, and a **Clear filters** action returns to the unfiltered list. Never "no packages found" — the packages exist; the filter excluded them.

**E4 — First run, or the rollup has never been computed.** Distinct again. There is no rollup row, so the table cannot render. The copy states that the policy run has not completed and shows the run-ledger row for the run in question — including, per CPM-APP-S06, **a killed worker's run shown as `running`**, which is a state the reader needs to see rather than a gap.

**E5 — A blank field.** Not an empty state at all. Em dash, `{typography.mono-value}`, no footline. Enumerated here only so it is never confused with the four above.

### The error states — designed here

The mockup has no 404, no 500, no session-expired.

**404 — package or finding not in the inventory.** The highest-risk copy in the product: it must **not** use the string `not_found`. `not_found` is a status meaning "a collector asked and established an absence"; a 404 means "this identifier is not in the curated watchlist". Copy: "`<name>` is not in the monitored inventory." Plus the mechanism, because it is actionable — the inventory is a curated watchlist versioned in-repo and changed by pull request. Plus a link to the health view.

**500 — unexpected failure.** Keeps the app shell and the nav. Carries the request id in `{typography.mono-value}`. States explicitly that **nothing was written** — because `ATOMIC_REQUESTS=True` makes that true, and a reader of a supply-chain tool needs to know whether their override landed. Never a stack trace.

**Session expired.** The OIDC session lapses. On a full page load the platform redirects to the IdP, and that is fine. **Mid-HTMX it is not**: a 302 to the IdP inside an `hx-post` swaps a login page into a table row. **Rule: the server answers an HTMX request from an unauthenticated session with `HX-Redirect` to the login URL and an empty body — never a partial.** This is a middleware requirement, not a per-view concern.

**Two sign-in refusals, not one.** An authentication carrying **no group claim** and one asserting **zero groups** are different states with different copy and different log events. Both are platform-owned at `/accounts/login/`; the second is described in the mockup and never drawn (G-4).

---

## Evidence and Provenance

The product's whole thesis: *no value is shown without the evidence and the observation time behind it.* Four escalating layers, each mandatory at its own scope.

### Layer 1 — the `.ev` footline, always on

`{components.ev}` sits under **every** value, everywhere. Its grammar is fixed and does not vary by surface:

```
<source> · <observed_at> [· <qualifier>]
```

- `<source>` is the evidence table or the collector that produced the value: `vulnerability_findings`, `kev_findings`, `advisory`, `feedstock`, `inventory_snapshots`, `python314_findings`.
- `<observed_at>` is the observation timestamp behind **that value** — CPM-FR-37 requires every displayed status to be accompanied by the observation timestamp behind it, not by the page's render time and not by the rollup's `computed_at`.
- `<qualifier>` is optional free prose, and it is where every disqualified chip label from rule L3 lands: `target 24h`, `trace 4c1f9a2e`, `gated by package-identity confidence`, `depends on a stale finding`, `metadata only — not verified by build`, `429 rate limited for 2 days`.

An amber `{components.ev-stale}` footline means the evidence beneath it is past its freshness target. That is the only semantic variant.

**A status rendered without a footline is a defect**, and the inclusion tag makes it structurally impossible.

### Layer 2 — the freshness bar, page level

`{components.freshbar}` renders on every list, every detail page, every report, and in **every export header**. CPM-AD-11 makes this **mandatory chrome, not a progressive-disclosure detail**: `computed_at`, the run's cut-off and the per-domain version map "are displayed by every view and export".

The mockup varies its cells per screen despite claiming a single inclusion tag. This cell contract resolves it:

| Cell | When |
|---|---|
| `evidence cut-off` | **Always.** The run's cut-off. |
| `policy versions` | **Always.** The per-domain version map, verbatim. |
| `rollup computed` | Whenever the surface reads the rollup — every list and detail surface does. |
| `policy run` | Whenever a single run produced the surface. |
| `produced` | Reports only. |
| `excludes` | Any surface that excludes rows on principle — states what and why, with the count. |
| `collectors`, `last full refresh`, `ranked by`, `tracking` | Surface-specific additions. |

Rule: the first two are the **mandatory floor**; every other cell is declared per surface and is an **addition, never a substitution**. The tag takes the surface's context object and refuses to render if the floor is absent.

### Layer 3 — evidence disclosure, package detail

Each derived status on package detail carries an `evidence ▾` control. It issues `hx-get="/packages/<name>/evidence/<domain>/"` with `hx-swap="afterend"`, inserting a nested table row directly beneath the status row it explains.

- Columns are per-domain. For vulnerability: Advisory · Severity · Affected · Fixed · Matched · Source · **Match confidence** · `observed_at`.
- **Superseded rows are shown, not deleted.** They render dimmed and carry a `superseded` `{components.chip-plain}`.
- The disclosure's caption states the mechanism — *re-observation inserts a new row; nothing above was updated in place* — followed by a **show all N observations** link. History is reachable, not merely preserved.
- Multiple disclosures may be open at once. Alpine tracks *which* are open; that is view state. Closing removes the inserted row; reopening **re-fetches**. There is no client-side fragment cache: a cached fragment is a fragment that can disagree with the server, and this product's entire value is that two surfaces cannot disagree.

CPM-APP-S03 requires each status to link to evidence rows carrying source, observation timestamp and match confidence, and requires package-identity provenance and confidence to be shown **including any override and the reason recorded with it**. The override is displayed on the package permanently, with its actor, timestamp, prior value and reason. It is never hidden behind a disclosure and never downgraded by a later automated resolution.

### Layer 4 — the evidence citation table

Post-MVP, for CPM-EP-NL: Package · Evidence table · Row · `observed_at` · Used for. Named here so that when the NL capability ships it inherits this contract rather than inventing a fifth provenance idiom. Every generated answer names the tables, row identifiers and observation timestamps it read, and reports missing, stale, failed and not-applicable states as themselves.

---

## Queues and Transitions

### Queue-to-role mapping — our decision, not the PRD's

The PRD does not state the mapping, and FR-25's list order actively misleads: its positional reading contradicts FR-3's override permission and the brief's own role table. The PRD's rubric flags this and prescribes a table. **This is that table, and it is ours:**

| Queue | Role | Basis |
|---|---|---|
| Compliance review | Security and compliance reviewer | brief role table; CPM-FR-13 manual-review route |
| Remediation | Packaging engineer | brief explicit; CPM-UJ-1 explicit |
| Package-identity review | Platform and engineering leadership | CPM-FR-3 override permission; the JTBD; CPM-FR-4 exit condition |

`[ASSUMPTION: derived from the permission model, not stated by any source. Confirm before CPM-APP-S05 is implemented, and correct FR-25's list order so it stops implying the opposite pairing. See G-15.]`

### The two halves — access and action

The PRD, the epics and the spine appeared to contradict each other on whether queues are role-exclusive. They do not: **they govern different layers**, and the UI must implement both without conflating them.

- **Opening a queue page is role-exclusive.** A role that opens a queue that is not its own gets a 403 and a logged refusal carrying the acting user identity (CPM-FR-31, APP.05-API-004). This is E1. The `My queue` nav entry resolves to the caller's own queue and so can never trigger it; the 403 arises from a typed, pasted, or bookmarked deep URL.
- **Acting on an item draws its available actions from the `(from_state, to_state, required_role)` transition table, evaluated against the item's current state** (CPM-AD-13, CPM-AD-22). Not from "which queue am I in", and not from "which role am I".

**These are compatible because an item moves between queues.** Routing changes the item's queue field; **it never creates a second item** (CPM-APP-S04). The "sent to compliance review" item is the *same object* the remediation reviewer was looking at, carrying its full history. Two roles advance it in sequence — each from their own queue page, each seeing only the transitions their role holds.

**The UI renders only the transitions the role holds. The service enforces them regardless of what the UI rendered.** The service locks the row with `select_for_update`, checks the expected prior state, refuses on mismatch, and appends the audit row **in the same transaction** (CPM-AD-22, CPM-AD-23). The UI narrows the options; it does not enforce them.

### Items are keyed on a finding key, never an evidence row id

- Items are keyed on a **re-observation-stable finding key** declared alongside each evidence table — for a vulnerability, `package + advisory_id + affected_range`. **Never an evidence row id.**
- Consequence, and it is CPM-APP-S04's entire user-visible point: **an accepted finding stays accepted.** After the next collection the item does not reappear as new work; the audit table shows a row reading *re-observed; not recreated as new work*.

### Every queue ranks by bucket, then score

Ranking is **priority bucket, then score** (CPM-AD-22). For package-identity items, **internal usage breadth is the score input** — which reconciles CPM-FR-4's "ranked by usage breadth" with CPM-FR-25's "bucket then score" without either winning. The sort is stated in the applied filter bar as a fact ("sorted by rank · bucket then score"), not offered as a control, because it is not a choice.

Priority bucket content — what P1 through P10 mean — and the score function are undefined (PRD OQ 8). See Withheld Values.

### The queue surfaces

**The queue list** carries, per row: selection checkbox · package · priority bucket · score · work type · **why this bucket** · readiness · workflow state · age. "Why this bucket" is a human sentence with an `{components.ev}` naming the rule and the ruleset version. Work type comes from the closed set in Appendix A.1: fix vulnerability · create recipe · file tracking issue · already tracked · update feedstock · validate Python 3.14 · review licence · resolve identity.

**The item detail** puts all six fields a reviewer needs on one screen with no disclosure required — advisory ID, affected range, fixed range, matched version, source, observation time — plus the evidence panel, the "where the fix is" panel, and the append-only audit table.

**Transitions** are posted from a modal. The modal previews the resulting state as `<from> → <to>` using `{components.chip-plain}` and names the transition-table entry that permits it. On success the server returns the re-rendered queue row and HTMX swaps it.

**Bulk actions.** Selected rows tint; the count and the available bulk verbs appear in the header button row. The select-all checkbox selects **the current page, not the result set**, and says so in visible copy as well as in its accessible name. `[ASSUMPTION: no source specifies bulk-transition semantics. Recommendation: a bulk action is N independent transactions, not one — each item's transition is validated against its own prior state, so all-or-nothing would fail an entire batch on one stale item. Partial success must be reported per item, naming which succeeded and which were refused, and why. See G-12.]`

**CPM-FR-25 routes work to a human; it never acts.** There is no automated remediation, no auto-advance, no bot actor in the audit table.

**Do not optimise this flow for speed.** CPM-SM-C2: time to close a queue item is a metric, and *faster is not better* if overrides are recorded without a substantive reason.

---

## Reports and Export

### The six recurring reports

Daily KEV · weekly feedstock lag · Python 3.14 readiness · licence exceptions · unmapped identities · stale evidence and collector failures.

`/reports/` is an index of six cards — the in-page navigation standing in for the tab bar the platform does not have. Each card states its cadence, its name, its headline counts, its produced time and its policy version. Each report page is: `<h1>` and subtitle · freshness bar · optional bulk-action button row · table · pager · export.

**Every report states the evidence cut-off and the policy version it came from** (CPM-APP-S06). That is the freshness bar's floor, and it is why the bar is not optional on a report.

**Reports and the application never disagree** because both read the same rollup through the same projection. This is enforceable, not aspirational: CPM-AD-24 requires every derived-status column in the rollup to appear in the governed views, with a test diffing the two column sets.

### The export contract

- **Stored field names and export column names are two different contracts.** Export headings preserve the historical report headings existing consumers already read: `Core_Python_Package_Name`, `P`, `Rank`, `Score`, `Work`, `Vuln`, `Platforms`/`Apps`/`Downloads`/`Versions`, `Conda-Forge_FeedStock_URL`, `Local_Build_Status`, `Verification_Timestamp_UTC`, `Priority_Bucket_Description`/`Priority_Source`/`Priority_Reason`, `JFROG_risk_level`, `OpenTeams_Title`. The **reporting layer owns the projection**; no model field is named for an export heading.
- **The projection maps names only — never values, never formatting** (CPM-AD-24). A status crosses into the export as its `OutcomeState` value, verbatim, lowercase. This rule exists to prevent exactly one failure: "the export rendering `unknown` as a blank cell — destroying the five states in the one artifact that leaves the system."
- **Staleness crosses the boundary as data, not as styling.** Every status column in an export carries **two required companion columns**: `<domain>_observed_at`, the observation timestamp behind that value, and `<domain>_stale`, a boolean against that domain's freshness target at the export's cut-off. A status column without both is a defect, and the column-set diff test CPM-AD-24 already requires must assert their presence. The reason is the export's sharpest failure mode, and it is not hypothetical. On screen, staleness rides on a CSS `::after` mark, an amber footline and a visually-hidden word — **none of which exists in a CSV**. Left there, a stale `clean` would export as `clean` — the CPM-SM-C1 failure landing in the same artifact the rule above protects, and a direct contradiction of the rule that stale never displays as clean.
- **Blank means missing; values are never invented.** The convention (Appendix A.1) covers package-identity fields only, never a status column.
- **Multi-value columns separate with `;`.**
- **The export carries the same freshness and package-identity-confidence columns the application shows** (CPM-APP-S06), and the freshness bar's contents ride in the export header.

### The synchronous/asynchronous branch is a visible UX fork

An export at or under `settings.CPM_SYNC_EXPORT_MAX_ROWS` downloads immediately. An export above it is enqueued and the request returns the in-progress state. **One settings constant, read by every export path** (CPM-APP-S08), so no report can quietly stream the whole inventory. The user-facing copy names the row count and the cap; both are interpolated, never literal.

Coverage's "Export for the review deck" is the same projection through the same path. There is no second export mechanism.

---

## Interaction Primitives

### The HTMX boundary — exactly four interactions

HTMX earns its place on four, and on nothing else. **Everything else is a plain page load.**

| # | Interaction | Surface | Attributes |
|---|---|---|---|
| 1 | Facet and search swaps | health view | `hx-get`, `hx-target="#health-rows"`, `hx-push-url="true"`, `hx-indicator`; search on `hx-trigger="keyup changed delay:300ms"` |
| 2 | Evidence disclosure | package detail | `hx-get=".../evidence/<domain>/"`, `hx-swap="afterend"` |
| 3 | Queue transitions | finding detail, queue rows | `hx-post` with CSRF in `hx-headers`, `hx-target="#wf-row"` |
| 4 | Job polling | any surface carrying `?job=` | `hx-get="/jobs/<id>/"`, `hx-trigger="every 3s"`, `hx-swap="outerHTML"` |

One bounded exception is permitted and already drawn: the home page's "top of my queue" partial may poll on `hx-trigger="every 60s"`. **The page itself never reloads**, and nothing else on any page polls.

Adding a fifth HTMX interaction is a decision, not a convenience. Justify it against this list, or use a page load.

### Rules that make the boundary safe

- **Every partial is a template fragment the full page also renders.** The same `{% include %}` serves both paths. **A swapped row and a freshly loaded page cannot disagree.** Enforce it with a test that renders both paths for the same object and diffs the output — this is the mechanism by which the product's central promise survives partial rendering.
- **Alpine holds view state only.** Permitted: which disclosure panels are open, pending filter selections before submit, bulk checkbox selection, modal open/closed and focus. **Forbidden: computing a status, a count, a timestamp, a rank, a readiness, a package-identity confidence, or a match confidence.** Derived state is read-only to the application (CPM-AD-10); if Alpine is computing it, the architecture has been violated in JavaScript.
- **Validation is server-side, without exception.** An invalid submission returns the **bound form**, re-rendered by the server through crispy-forms, swapped into the modal body. **Alpine never decides whether a reason is acceptable.** There is no client-side validation logic to keep in step with the server's, because there is none.
- **No optimistic UI.** CPM-AD-23 requires every privileged write and its audit row to be one atomic unit in one service function — never `transaction.on_commit`, never a follow-up task. **Nothing reports success before the audit row lands.** The swapped row is the server's re-render *after* the commit, and it carries the audit timestamp, which is the visible proof the audit exists. A spinner on the button while the transaction runs is correct; a row that changes before the response arrives is not.
- **CSRF travels in `hx-headers`** on every mutating request.
- **An unauthenticated HTMX request gets `HX-Redirect`, never a partial.**
- **No client-side fragment cache.** A disclosure that reopens re-fetches.

### The inclusion tags — Python-side enforcement of the no-collapse rule

The five-state rule cannot survive being restated in twenty templates. It survives by being implementable in exactly one place.

- **`{% status_chip value evidence=... %}`** is the *only* way a status chip enters a template. It takes the status value and its evidence and emits, as one indivisible unit: the lowercase value as real text, the marker shape, the hue, and the `{components.ev}` footline. **The four redundant channels cannot be separated, because they are one tag.** No template writes chip markup.
- **`{% freshbar context %}`** is the only way a freshness bar enters a template. One implementation, so a surface cannot forget it, and so the mandatory floor cannot be dropped per screen.
- **`{% conf_tag %}`** renders package-identity confidence through `{components.conf}`. Deliberately a separate tag so a confidence can never be mistaken for an outcome state at the call site.
- **`{% ev %}`** renders a bare footline for values that are not statuses.

**Enforcement:** a template-lint test greps the template tree for `class="chip`, `class="ev`, `class="conf` and `class="freshbar` outside those four tags' own templates, and fails the build on a hit. Reporting, exports and the API render through the same projection for the same reason.

### Where actions live, and what does not exist

- **Actions live in exactly three places** and nowhere else: the package-name link out of a list, the `evidence ▾` control on a status row, and bulk selection plus the header button row. **There is no per-row action menu** anywhere in the product.
- **No hover-only affordances.** The row-hover tint carries no meaning; nothing is revealed by hovering.
- **No infinite scroll.** Pagination is structural and cannot be opted out of (CPM-APP-S01, CPM-AD-12). One global page size, from settings.
- **No drag, no reorder, no inline editing.** The only two writes in v1 are a workflow transition and a package-identity override, and both go through a form.
- **Keyboard model.** Standard browser semantics only: Tab, Enter, Space, Escape. `[ASSUMPTION: no source specifies a shortcut model and the mockup has none. Recommendation: invent none in v1. A three-role internal tool used daily by one person and monthly by another does not earn a bespoke keybinding layer, and an undiscoverable one is worse than none.]`
- **Modals are one level deep, never two.**
- **Toasts are not transient** and are never auto-dismissed. Stacking rules are undefined (G-11).

---

## Accessibility Floor

The PRD states **zero** accessibility requirements across 917 lines. This section originates all of it.

**Floor: WCAG 2.2 AA.** `[ASSUMPTION: originated here. Internal tool behind OIDC, three known roles, no public exposure — a reasonable floor with no formal compliance audit planned. AA is the target, not a certification claim.]` Contrast ratios and target sizes are `DESIGN.md`'s to hit; this section owns behaviour and semantics.

### The doctrinal rule, and it is the strongest one here

**Colour is never the only channel for a status.** Every status carries four: (a) the lowercase status word as **real text**, (b) a distinct marker **shape**, (c) a distinct **hue**, (d) an `{components.ev}` sentence naming source and time. `{% status_chip %}` makes them inseparable.

**The test:** render any status-bearing surface in greyscale. All five outcome states must remain distinguishable. If they do not, the chip is broken, not the eyes reading it.

The `{components.chip}` marker is a CSS `::before` and is therefore invisible to assistive technology. **That is acceptable only because the status word is always real text.** The word may never be moved into a `title`, an `aria-label`, an icon, or a background image.

### Keep these — the mockup's good bones

Semantic elements throughout · every facet checkbox wrapped in its own `<label>` · explicit `for`/`id` on every modal field · a global `:focus-visible` ring (`{components.focus-ring}`) · `prefers-reduced-motion: reduce` suppressing all animation and transition · every SVG `role="img"` with a descriptive `aria-label` · the spinner as `role="presentation"`.

Because reduced motion suppresses the spinner, **the spinner is never the only in-progress signal** — the toast's text carries it.

### Close these — the mockup's named gaps

| Gap | Fix |
|---|---|
| No `<h1>` in any app screen; starts at `<h2>` and jumps to `<h4>`, skipping `<h3>` | **Exactly one `<h1>` per screen**: the page title in the header block. Panel headers are `<h2>`. Nested evidence-table captions are `<h3>`. **No level is skipped, anywhere.** |
| No `aria-live` on the async toast — a job that finishes and swaps out announces nothing | The toast region is `aria-live="polite"` `aria-atomic="true"`. The terminal fragment therefore announces completion. |
| No `aria-sort` on the sorted column | `aria-sort="ascending"` / `"descending"` on the sorted `<th>`. |
| `<x>✕</x>` in the filter pill — an invented element, no role, no accessible name. The weakest control in the file | **Deleted.** A real `<button type="submit">` with `aria-label="Remove filter: vulnerability status is critical"` — the full filter stated, not "remove". |
| Modals lack `role="dialog"`, `aria-modal`, `aria-labelledby`, focus trap | `role="dialog"` `aria-modal="true"` `aria-labelledby="<header id>"`. Focus moves to the first field on open, is trapped while open, Escape closes, focus returns to the trigger. Alpine owns this — it is view state. |
| `.errmsg` not tied via `aria-describedby`; the invalid textarea has no `aria-invalid` | The error element gets an id; the field gets `aria-describedby` pointing at it and `aria-invalid="true"`. **crispy-forms wires both** — a template-pack concern, not a per-template one. |
| Select-all header checkbox unlabelled | `aria-label="Select all rows on this page"`. And the visible copy says *page*, not *all*, because it selects the page, not the result set. |
| `a.locked` is a link, not a disabled control; its claimed tooltip does not exist | **Deleted from the system.** Coverage is readable by every role, so nothing in the nav is locked. The nav model states the rule and the fallback for an entry that must genuinely be withheld. |

### Additional floor

- **Tables.** `<th scope="col">` on every header cell; the package-name cell is `scope="row"`; nested evidence tables carry a `<caption>` naming the domain and the package.
- **Staleness has exactly one accessible carrier: a visually-hidden `<span>` inside the chip**, holding the word `stale`, so the chip announces "critical stale" rather than "critical". On screen staleness rides on a CSS `::after` mark and an amber footline. The mark is generated content and invisible to assistive technology, and colour alone is never sufficient. The span is not optional decoration — it is the sole reason a screen-reader user learns that a conclusion cannot be acted on. `{components.chip-stale-overlay}` specifies its appearance; the markup obligation is here. A stale chip without it is a defect.
- **Live regions.** The health view's result count is `aria-live="polite"` so a facet swap announces "1,204 of 9,842 packages". The toast is the only other live region. There are no others — a page that announces constantly announces nothing.
- **Skip link and landmarks.** A **skip link is the first focusable element on every page** ("Skip to results" on list surfaces, "Skip to content" elsewhere), visible on focus, targeting the `<main>` content region. Landmarks are explicit and unique per page: `<header>` for the app bar with `<nav aria-label="Primary">` inside it, `<aside aria-label="Filters">` for the facet sidebar, `<main>` for the content region, and the results table wrapped in a labelled region so its name is announced. The flagship health view is why neither is optional: it puts 30+ facet checkboxes ahead of the table, so reaching the data by keyboard means tabbing past the entire sidebar on every page load. Omitting either is a **WCAG 2.4.1 Level A** failure, below the floor this section sets everywhere else. It is called out because the mockup had neither, and nothing else in this document would have caught it.
- **Tab order matches reading order** on every surface.
- **Focus after an HTMX swap** is specified once, here, because the two obvious rules contradict each other on the product's primary write path. A queue transition posts a form **from inside the row that is about to be replaced**, so "return focus to the trigger" and "leave focus where it was" cannot both hold — the trigger no longer exists. The rule:
  - **A swap that replaces the element containing focus** moves focus to the **swapped-in replacement**, which carries `tabindex="-1"` for the purpose. For a queue transition that is the updated row, so the user lands on the item they just advanced and hears its new state.
  - **A swap that does not contain focus** — a facet swap replacing the table body while focus is in the sidebar, a polling status node — **must not move focus at all**.
  - **A modal** returns focus to the control that opened it. Where that control was itself inside a swapped row, focus goes to the replacement row instead.
  - Never `<body>`. A swap that drops focus to the document is a defect, not a cosmetic issue.
- **Every form control has a visible label.** Placeholder text is never a label.
- **Refusals are readable, not just logged.** The 403 states which role is required and which surface was requested, as text.
- **Zoom.** The app pins each screen to the desktop minimum stated in `DESIGN.md` → Layout & Spacing, so it does not meet 1.4.10 Reflow. That criterion requires content to reflow at a 320px-equivalent viewport — 400% zoom at 1280px — without two-dimensional scrolling. Concretely: on a 1280px display horizontal scrolling appears at roughly **110% zoom** (1280 ÷ 1.1 ≈ 1164, already below the floor), and the floor is **3.7× wider** than the 320px the criterion asks for. Nobody had stated where the floor actually breaks; it breaks early. That is a materially larger gap than the 200% figure often quoted, and worth stating accurately for whoever later scopes the work. **Accepted as a v1 limitation for a desktop-only internal tool: a recorded decision, not an oversight (G-6).** It remains a real AA shortfall. It is written down here so that adopting this spine is not mistaken for meeting AA in full, and so that anyone who later needs narrow-viewport support finds a named gap rather than an assumption.

---

## Key Flows

Three journeys, three protagonists, verbatim from the PRD. All three take they/them pronouns.

### Flow 1 — Dana Okafor clears a KEV finding before standup

*Security and compliance reviewer. Daily, before standup. Enters at the queue. Time-pressured, short session.*

1. Dana opens the monitor. They are already authenticated from yesterday's session — no sign-in screen.
2. **The freshness bar is read first, before any number on the page**: rollup computed, evidence cut-off, the per-domain policy version map, and `collectors: 7 of 8 healthy` in amber. Dana now knows how much of what follows is current.
3. The compliance review queue leads with three KEV findings, all ranked P1. The stat cards beside them include "Findings I cannot act on: 6 — 2 stale evidence, 4 fix not published anywhere", which exists so the clean proportion cannot quietly rise by absorbing what could not be assessed.
4. Dana opens the top item. The finding detail shows **six fields at once, with no disclosure required**: advisory ID, affected range, fixed range, matched version, source, observation time. Beside them, the evidence panel and the append-only audit table.
5. The fixed range is already on conda-forge. Dana chooses **Route to the remediation queue**. The modal previews `triaged → routed · remediation`, names the transition-table entry that permits it, offers the work type from the closed set, and takes a note recorded on the audit row.
6. Dana submits. The service locks the row, checks the expected prior state, writes the new state and the audit row **in one transaction**, and returns the re-rendered queue row.
7. **Climax.** The row swaps in place and now reads `routed · remediation`, with an audit footline naming Dana and the second the transaction committed. Nothing said "saved" before the audit row existed — the timestamp on screen *is* the audit row. And the item that moved is the same object, carrying its evidence, its matched version and the fix location with it: **the packaging engineer will open exactly what Dana just read.** No second item was created, no handoff note was written anywhere else, and nothing was copied.

**Edge case — the stale finding swaps the primary action.** One of the three, `pyarrow`, has advisory evidence past its freshness target. Its chip still reads `critical` in `{colors.crit}` — stale did not soften it, and it did not become amber. What changed is the footline, now amber and naming the target it missed, and the primary control, which reads **Recollect evidence** rather than **Route**. Routing is not offered, because the transition table was evaluated against a stale finding. Dana recollects; the request returns `202` with a job id appended to the URL, an in-progress toast carrying the job id, trace id and an honest estimate, and a "Meanwhile, what is known" panel showing the current values unchanged. Dana moves to the next item while it runs.

**Failure — a concurrent advance.** Someone advanced the item between Dana's page load and Dana's submit. The service refuses on the state mismatch, returns the bound form stating the mismatch in plain words ("this item is now `routed`; it was `triaged` when this page loaded"), and the row re-renders at its true state. No write occurred, and the page says so.

---

### Flow 2 — Ravi Nandakumar files the feedstock that never existed

*Packaging engineer. Enters at the feedstock-gap report, not at the home page. The session spans two systems.*

1. Ravi opens `/reports/feedstock-gap/` directly. The nav shows the same four labels every role sees; `Coverage` is present and works.
2. The freshness bar states the evidence cut-off, the policy versions, when the report was produced, and — non-optionally — **`excludes: 321 unmapped packages — absence cannot be claimed`**.
3. The table is ranked by internal usage breadth. `pyarrow` sits at P1 with a feedstock chip carrying a determinate value and a footline: `feedstock · 04:55Z · no recipe activity in 14 months`.
4. Ravi opens the package detail. The **package identity panel** confirms package-identity confidence is `verified`, not `inventory-derived` — rendered as a `{components.conf}` tag, deliberately not a chip, so it can never be read as an outcome state.
5. Further down, another package's feedstock row reads `not_found` on the dashed ring in `{colors.nf}`, with `no feedstock, no staged recipe · 04:55Z` beneath it. **Not blank. Not clean.** A reader can tell "we looked and there is none" from "we have not looked".
6. Ravi drafts a tracking issue from the package detail view, carrying package identity, internal usage counts and the evidence rows.
7. **Climax.** Ravi files it in the external tracker by hand, then advances the workflow item from `file tracking issue` to `already tracked`. The fact that it is tracked comes back onto the monitor through the workflow item — so the report Ravi entered from and the package Ravi left through say the same thing, and the next reader does not file it a second time.

> **The tracking URL is not stored in v1 — a decision, not an oversight.** The PRD's journey has the tracking URL written back onto the package, and that write is **forbidden by CPM-FR-3 / CPM-FR-27**: the only v1 writes are a workflow transition and a package-identity override, and the application layer holds no other write path (CPM-AD-10). Rather than invent a third write verb, v1 ships the honest version above: the draft is **composed server-side as a read-only artifact** carrying package identity, internal usage counts and the evidence rows; Ravi copies it out; and the tracked fact is recorded as **workflow state**, which the application is already permitted to write. Nothing is stored that the contract does not allow, and the "is this already filed?" question is still answerable on the monitor. Restoring the URL field needs a third write verb in the PRD *and* an invariant in the spine governing it — see **G-2**. Until both exist, no implementation may add one.

**Edge case — the unmapped package that never appears.** Ravi cannot find `internal-telemetry-sdk` in this report at any filter setting. It is `unmapped`, and absence of a feedstock cannot be claimed for a package whose package identity is unresolved. The report does not silently omit it: the freshness bar's `excludes` cell states the count and the reason and links to the unmapped-identities report, where the package sits waiting for the one role that can resolve it. The package still holds exactly one rollup row, still appears in the health view, and reads `unknown` on every gated status — never `not_found`, which would be a claim.

---

### Flow 3 — Sam Ibarra sees where the coverage gaps are

*Platform lead. Monthly, before a review. Enters at the coverage view. The only actor who may override a package identity.*

1. Sam opens `/coverage/` ahead of the monthly review. Three metric families, as the journey specifies: the fraction of inventory with resolved package identity; evidence inside its freshness target, **per collector**; and which collection runs failed, and why.
2. The collector-health table shows the advisory collector with an `error` chip — the word `error`, the triangle marker, `{colors.err}` — and a footline carrying everything the mockup had crammed into the chip: `advisory · 05:40Z · 429, rate limited for 2 days, retries exhausted · trace 4c1f9a2e`. The trace id is a link.
3. The row states that 148 packages were affected. **Those 148 show `error` in the health view — not clean, and not omitted from the count.** Sam clicks through on the `error` facet, which is a first-class filter value rather than an "other" bucket, and sees exactly those 148.
4. The third metric card is the counter-metric: *packages presented as clean*, labelled **do not optimise**, with the line that a rise here tracking a fall in `unknown` is the failure mode of the entire product. It sits on the coverage view precisely so the person who builds the review deck reads it before they build the review deck.
5. Sam exports for the deck. The row count exceeds the synchronous cap, so the request returns `202`, the toast names the count and the cap, and Sam keeps reading while it builds.
6. **Climax.** The export lands, and its header carries **the same evidence cut-off and the same policy version map the screen showed**, and its status columns carry `unknown`, `not_found`, `not_applicable` and `error` spelled out as themselves. The deck Sam presents next week cannot disagree with the application, and cannot quietly claim a clean estate. The one artifact that leaves the system was the one place the five states were most likely to collapse, and they did not.

**Edge case — the wrong upstream repo, corrected with a required reason.** Sam finds a package pointing at the wrong upstream repository. They correct it **from the package detail view** — the one write in the product that changes governed reference data.

- The modal takes `source_repository_url` with the prior value shown beside it; a release ecosystem where **`not_applicable` is an explicit, recordable decision** (help text: "Recording `not_applicable` is a decision, not a blank. It is distinct from `not_found`."); and a **required reason**.
- Sam submits with the reason empty. The server returns the bound `IdentityOverrideForm` with the error text, `aria-invalid="true"` on the field, and `aria-describedby` pointing at the message. **Alpine never made that judgement** — there is no client-side rule to drift out of step.
- Sam supplies the reason and submits. The package-identity update and the `identity_overrides` row — actor, timestamp, prior value, new value, reason — **commit together, in one transaction. Neither can survive alone**, so the audit trail cannot develop holes.
- Package-identity confidence moves `unmapped → verified`. The package leaves the package-identity review queue, because reaching `verified` is the single exit condition.
- **The override stays displayed on the package, permanently, with its reason**, and is never downgraded by a later automated resolution. It is a correction on the record, not a correction of the record.
- The other two roles never see this control, and if either types the URL they get the 403 — the refusal, with the required role named, logged with their user identity. The permission was checked when the control was rendered, and again when the view was entered.

---

## Open Gaps

Surfaces the mockup names but never designed, and decisions no source makes. **None of these is silently designed around above** — each is named with a recommendation, and each needs a decision before the story that touches it is written.

| # | Gap | Recommendation |
|---|---|---|
| **G-1** | **"Save this view"** — the button exists on the health view; the flow, the naming, the listing, the sharing, and whether a saved view is a per-user object or governed data are all undesigned. | **Cut from v1.** Facet swaps already carry `hx-push-url="true"`, so the filter state lives in the URL and a browser bookmark is the answer. Remove the button; state in the applied filter bar that the URL carries the filters. Reintroducing it means a new model, a new write path, and a permission question. |
| **G-2** | ~~Draft tracking issue and the tracking-URL write-back~~ — **RESOLVED.** The write-back is forbidden by CPM-FR-3 / CPM-FR-27 and CPM-AD-10 supplies no third write path. | **Decided: v1 ships draft composition as a read-only artifact**, with tracked state carried as a workflow item (`file tracking issue` → `already tracked`). No third write path is added. The tracking URL is not stored. Reopening this requires a PRD amendment *and* a spine invariant, in that order. |
| **G-3** | **"Accept risk" justification form** — the button exists on the finding detail and D4 requires "a recorded justification", but only the *route* modal was drawn. | It is a transition like any other. Reuse the route modal's shape with the note field promoted to **required**, and the same one-transaction audit guarantee. Named here so it is not invented ad hoc at implementation time. |
| **G-4** | **The "zero groups" sign-in page** — an authentication carrying *no group claim* and one asserting *zero groups* are two different refusals with different copy and different log events. The first is drawn; the second is only described. | Platform-owned at `/accounts/login/`, outside CPM-EP-APP. Raise it against the platform; do not build it here. |
| **G-5** | **Sign-out, account/preferences, theme toggle** — none exist. `data-theme` is honoured by the CSS for both `light` and `dark` but **is never set by any control**. | v1 honours `prefers-color-scheme` only and ships no toggle. Keep the `data-theme` hook for a later preference surface. Sign-out is platform-owned. |
| **G-6** | ~~Narrow-viewport layout~~ — **RESOLVED.** No source states a device, browser or breakpoint requirement. | **Decided: a desktop-only floor**, declared in DESIGN.md and stated plainly here. No narrow layout is designed and the mockup's gestured-at offcanvas is not assumed. The WCAG AA Reflow shortfall is recorded in the Accessibility Floor rather than passed silently. |
| **G-7** | **The governed API (CPM-APP-S07) has no screen.** `drf-spectacular` renders one; nobody has designed it or decided whether it belongs in the nav. | Decide before S07: either it is an unlisted URL for integrators, or it is a fifth nav entry. It cannot be both by accident. |
| **G-8** | **The home page (S2) has no story.** Four stat counters and two panels of real UI with no acceptance criteria behind them. | Either add a CPM-APP story for it, or route `/` to the health view. Do not build a landing page against no criteria — its counters ("Findings I cannot act on", "217 packages have no vulnerability evidence") are exactly the CPM-SM-C1 defences that most need a test behind them. |
| **G-9** | **The coverage view (S8) is a journey entry surface with no FR**, and only its collector-failure half is covered by a story. Its three metric families exist only in journey narrative. | Add an FR, or fold the coverage view into report 6 and accept that Sam's journey entry becomes a report. Do not build three metric families against a narrative. |
| **G-10** | **Filtering and sorting the expensive column set** — the spine explicitly does not settle it, and parity with the rollup columns must not be assumed. | Restrict v1 filters and sorts to the cheap rollup columns. Raise the expensive set as a story-level question with a query-count budget attached. |
| **G-11** | **Toast dismissal and stacking** — undefined, and two concurrent jobs are entirely possible (a recollection and an export). | Stack newest-first, cap at three visible, each dismissible. **Dismissal does not cancel the job**, and the copy must say so. |
| **G-12** | **Bulk-action partial-failure semantics** — unspecified by every source. | N independent transactions, not one. Report per item which succeeded and which were refused, and why. |
| **G-13** | **Keyboard shortcut model** — none exists in the mockup and none is specified anywhere. | Invent none in v1. Standard browser semantics only. |
| **G-14** | **Notification surface** — none. A job that completes while the user is on another page announces nothing, anywhere. | Accept for v1: job state is server-side and recoverable from the URL, and the toast reappears on return. Do not build a notification centre for two async operations. |
| **G-15** | **Queue-to-role mapping** is our assumption, not the PRD's. | Confirm before CPM-APP-S05 is written, and correct CPM-FR-25's list order so it stops implying the opposite pairing. |
| **G-16** | **The HTMX/Alpine boundary is unprotected.** The ARCHITECTURE-SPINE never mentions either library, so it neither authorizes nor defends the boundary codified above. | Raise a follow-up to promote the four-interaction boundary, the Alpine view-state rule, and "every partial is a fragment the full page also renders" to spine invariants. Until then a future contributor can violate them without failing anything. |
| **G-17** | **epics.md L161-169** points at "the open question raised at the end of this step" and no such open question exists; L326 asserts no UX design contract exists, while this contract now does. | Docs fix alongside the adoption of this spine. |
| **G-18** | **The feedstock-gap report is Ravi's entry surface and is not one of the six.** CPM-FR-26 names "weekly feedstock lag" — which is *currency*, not *presence*. CPM-UJ-2 opens at a report that no FR creates. Its policy source exists (CPM-FR-40 derives absent / present-and-maintained / present-and-inactive / staged-recipe-pending) but nothing surfaces it. The identical defect in the coverage view is G-9; this one must not be designed around silently. | Add a seventh report, or amend CPM-FR-26's "feedstock lag" to cover presence as well as currency. Do not let Flow 2 depend on a surface no requirement creates. Decide before CPM-APP-S06. |

---

## Withheld Values

Every number below is deliberately absent from this document, and **must be absent from every template, fixture and copy string** — each reaches the UI from `settings` or from the rollup, interpolated at render.

| Value | Withheld by | Requirement on the implementer |
|---|---|---|
| p95 latency budget, and the inventory size at which it is measured | PRD OQ 5 | A value must exist and be enforced by a test (CPM-APP-S02). This spine does not choose it. |
| `PAGE_SIZE` | ARCHITECTURE-SPINE — required to be global, no number given | One global setting. The pager displays it; no template literal repeats it. |
| `CPM_SYNC_EXPORT_MAX_ROWS` | PRD OQ 5 | **One settings constant read by every export path** (CPM-APP-S08). It is the boundary between a download and a job — a visible UX fork — so the copy interpolates it. |
| Per-collector freshness targets | PRD OQ 7 | Per collector, not global. "Stale versus actionable" is the pivotal state change in Dana's journey, so the target must be readable from the rollup and displayed in the footline. |
| Priority bucket content (what P1–P10 mean) and the score function | PRD OQ 8 | Undefined, yet every queue ranks by bucket then score. The three explanation fields — `priority_description`, `priority_source`, `priority_reason` — must render beside every bucket so a rank is explainable without reading the rule set. |
| The job-poll ceiling | no source | A settings constant. See the in-progress state. |
| Advisory source names, licence policy outcomes, channel names, the feedstock-inactivity threshold | PRD OQ 1, 2, 4, 10 | Every such string in the mockup is illustrative. |

**The mockup's 500-row cap, its 24h / 7d / 30d freshness targets, its P1–P10 assignments, and every package name, CVE id, version, count and timestamp in it are illustrative and self-declared invented.** None may be lifted into an implementation. The mockup's own invented-versus-settled ledger governs; where this spine and that ledger agree, the item is settled.
