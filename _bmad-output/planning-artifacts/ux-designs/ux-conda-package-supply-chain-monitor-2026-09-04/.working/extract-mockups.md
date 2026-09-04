# Extraction: imports/ui-mockups.html — the existing design system

2911 lines. An editorial specimen book containing 11 mock screens in fake browser chrome + 5 hand-authored SVG diagrams. `<title>Supply Chain Monitor Screens</title>`.

Masthead declares: `Surface: Django templates · HTMX · Alpine.js` · `Styling: Bootstrap 5.2, inherited from the platform base` · `Status: Mockup — not implemented` · `Binds: CPM-EP-APP · CPM-EP-IDENTITY · CPM-EP-NL`.

**The framing rule (line 445):** "no value is shown without the evidence and the observation time behind it, and the five outcome states never collapse into each other."

## The eleven screens

| # | Screen | Route | Role |
|---|---|---|---|
| S1 | Sign-in + the claim that carries no role (two panels) | `/accounts/login/` and `?error=no_group_claim` | none |
| S2 | Reviewer home — "Good morning, Dana" | `/` | security & compliance reviewer |
| S3 | Current package health (the flagship) | `/packages/?vuln=critical&confidence=verified&page=1` | shared, all roles |
| S4 | Package detail — every status traced to evidence | `/packages/aiohttp/` | shared, all roles |
| S5 | Finding detail and routing + open modal | `/queues/compliance/wf_01JQ8G7T/` | security & compliance reviewer |
| S6 | The remediation queue | `/queues/remediation/?state=open&ready=1` | packaging engineer |
| S7 | Identity review and override + modal in error state | `/queues/identity/internal-telemetry-sdk/` | platform & engineering leadership |
| S8 | Coverage and collector health | `/coverage/` | platform & engineering leadership |
| S9 | Reports and export + async toast | `/reports/feedstock-gap/` | shared, all roles |
| S10 | Refused (403) and in-progress (two panels) | `/queues/identity/` and `/packages/tornado/?job=...` | packaging engineer |
| S11 | Investigation — NL, post-MVP | `/investigate/` | post-MVP, read-only |

Personas rendered with full names and avatar initials: **Dana Okafor** (DO), **Ravi Nandakumar** (RN), **Sam Ibarra** (SI).

Nav on every screen: Home · Packages · My queue · Reports · Coverage.

## THE TOKEN SYSTEM (light) — verbatim, lines 7-39

```css
:root{
  --paper:#e9edef;      --surface:#ffffff;   --surface-2:#f4f7f8;  --surface-3:#eaeff1;
  --ink:#0e1719;        --ink-2:#33454c;     --muted:#63767e;
  --line:#ccd7db;       --line-2:#e0e8ea;
  --accent:#0d5c73;     --accent-2:#0a4557;  --accent-wash:#dfedf1;
  --ok:#22643f;         --ok-wash:#e0efe6;
  --warn:#855505;       --warn-wash:#f7ecd8;
  --crit:#9d1729;       --crit-wash:#f7e2e4;
  --unk:#5a6d75;        --unk-wash:#e6ecee;
  --nf:#3c5a80;         --nf-wash:#e3eaf3;
  --na:#655684;         --na-wash:#eae6f2;
  --err:#8a3115;        --err-wash:#f6e5dd;
  --shadow-sm:0 1px 2px rgba(14,23,25,.07);
  --shadow-md:0 1px 2px rgba(14,23,25,.06),0 10px 26px -16px rgba(14,23,25,.35);
  --sans:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --serif:"IBM Plex Serif",Georgia,"Times New Roman",serif;
}
```

**The key colour decision:** the four sentinel states get hues that are deliberately OFF the green-amber-red determinate ramp. unknown = neutral slate, not_found = blue, not_applicable = violet, error = burnt orange. **The sentinels cannot be misread as a severity position.** This is the direct answer to CPM-SM-C1.

### Dark mode — implemented, dual-gated

`@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){...} }` plus `:root[data-theme="dark"]{...}`. Dark values:
```
--paper:#0b1214; --surface:#121c1f; --surface-2:#172327; --surface-3:#1d2c31;
--ink:#e6eef0;   --ink-2:#b3c4c9;   --muted:#8ba1a8;
--line:#2b3d43;  --line-2:#223136;
--accent:#57b6d2; --accent-2:#8ad2e6; --accent-wash:#123039;
--ok:#6cc191; --ok-wash:#14301f;      --warn:#e0ab55; --warn-wash:#33260d;
--crit:#f08a95; --crit-wash:#3a161c;  --unk:#9fb2b9;  --unk-wash:#1f2c30;
--nf:#93b3dd;  --nf-wash:#182533;     --na:#b7a6dd;   --na-wash:#241f33;
--err:#e3946f; --err-wash:#331a10;
```
On-accent text inverts to `#08171c` in dark (3 paired selectors). **No theme toggle control exists** — `data-theme` is honoured but never set.

Only two hard-coded colours outside tokens: `#fff` and `#08171c` (on-accent text). Everything else is `var()` or `color-mix()`.
`color-mix` percentages functioning as tokens: **32%** (all chip borders), **40%** (svg ok/crit/warn strokes), **45%** (danger border, hxnote dash, svg accent stroke), **42%** (modal dim overlay).

### Typography

Three families from Google Fonts: **IBM Plex Sans** (400/500/600/700), **IBM Plex Mono** (400/500/600), **IBM Plex Serif** (400/600 + italic, loaded).

- **Sans** = UI and headings. **Mono** = every machine value: timestamps, identifiers, versions, table headers, labels, eyebrows, URLs, counts, evidence lines. **Serif** = editorial prose only — **it never appears inside the mock application.**
- Body 15px/1.55. **The app shell resets to 13px** (`.app`).
- Size scale is ad hoc px, no ratio system: 9.5 · 10 · 10.5 · 11 · 11.5 · 12 · 12.5 · 13 · 13.5 · 14 · 14.5 · 15 · 16 · 16.5 · 17 · 18 · 19 · 20 · 27 · clamp(30,4.4vw,45).
- Weights: 400 / 500 / 600. **700 is loaded but never used.**
- Letter-spacing is a real signal: negative on display headings (-.01 to -.022em), positive on mono micro-labels (+.05 to +.13em).
- `tabular-nums` on `.tbl .num` and `.stat .big`. `text-wrap:balance` on h1-h4.

### Spacing, radii, shadows

**No spacing scale token exists** — padding is ad hoc but clusters: 1×4, 2×7/8 (chips), 3×8, 4×9/11, 6×9/12 (buttons/inputs), 7×10/13, 9×11/13 (table cells), 11×14, 13 (panel body), 14×16, 16×18, 18 (app-body), 30 (loginbox), 44/0/34 (masthead), 56/0 (band). Gaps: 1px (hairline grids), 5-9 (inline), 12-14 (cards), 22-28 (sections).

**Radii — a deliberately tight, mostly-square system:** 2px (chips, pills, badges, bars) · 3px (focus ring, brand glyph, pagenums, small svg) · 4px (buttons, inputs, searchbox, urlbar, svg containers) · 6px (loginbox, modal) · 7px (browser frame) · 50% (dots, avatars, chip markers, spinner).

**Shadows: only two, both tokens.** `--shadow-sm` on `.figure`; `--shadow-md` on `.screen`, `.loginbox`, `.modal`. **Panels, cards and tables have no shadow at all** — elevation inside the app is 1px borders + `--surface-2` fills.

**The distinctive border move:** structure is hairlines; the accent is a **3px left rule** as a semantic marker — `border-left:3px solid var(--accent)` on `.freshbar`, `.toast`, `.notebox` meaning "this block is provenance / system speech". Overridden per-instance to `--unk`, `--na`, `--ok`, `--warn`. 1px-gap grids over `--line-2` produce hairline cells. Dashed borders mean provisional/annotation.

## THE STATUS CHIP — the heart of the system

Section `#states` thesis (line 753), verbatim:

> "The product's primary failure mode is an unknown rendered as clean. So the four sentinels are given their own colour **and** their own marker shape — a hollow ring, a dashed ring, a struck circle, a triangle — and none of them is ever a blank cell. Status values are emitted lowercase and verbatim on every surface, screen and export alike."

```css
.chip{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;
  padding:2px 8px 2px 7px;border-radius:2px;border:1px solid;white-space:nowrap;line-height:1.5}
.chip::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
```

| State | Class | Marker geometry |
|---|---|---|
| determinate ok/warn/crit | `.ok` `.warn` `.crit` | filled dot |
| **unknown** | `.unknown` | `background:transparent;border:1.5px solid currentColor` → **hollow ring** |
| **not_found** | `.notfound` | `background:transparent;border:1.5px dashed currentColor` → **dashed ring** |
| **not_applicable** | `.na` | diagonal `linear-gradient` 44%/56% + solid border → **struck circle** |
| **error** | `.error` | `border-radius:0;clip-path:polygon(50% 0,100% 100%,0 100%);height:9px` → **triangle** |
| neutral metadata | `.plain` | `::before{display:none}` — **the only markerless chip** |

`.plain` is used only for non-outcome facts (workflow states, `superseded`, `skipped`, `authority`, `idle`, "3 selected"). **The five outcome states are never rendered `.plain`.**

**Stale is an overlay, not a sixth state:** "the conclusion is shown, struck through with an amber evidence line, and cannot be acted on." Implemented as a warn chip whose *label* carries both words: `critical · stale`, `stale — recollect`, `stale evidence`, `stale · 31h`, paired with `.ev.stale`.

## PROVENANCE — the `.ev` footline

```css
.ev{font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:3px;
  display:flex;gap:6px;align-items:center;white-space:nowrap}
.ev::before{content:"";width:9px;height:1px;background:var(--line);flex:none}
.ev.stale{color:var(--warn)}
```
The `::before` is a **9px tie-line** attaching the footline to the value above.

**Grammar is consistent:** `<source table or collector> · <observed_at> [· <qualifier>]`.
Qualifiers seen: `target 24h`, `trace 4c1f9a2e`, `gated by confidence`, `depends on stale finding`, `never "absent" while unmapped`, `metadata only — not verified by build`, `inside the 6h observation window`.

Canonical cell: `<span class="chip crit">critical</span><div class="ev">advisory · 05:38Z</div>`

**Four escalating provenance layers:**
1. `.ev` footline under every cell (always-on)
2. `.freshbar` at page level — `rollup computed`, `evidence cut-off`, `policy versions`, `policy run`
3. Expanded evidence disclosure on S4 — nested table in a `colspan` cell, accent-wash ground, columns Advisory/Severity/Affected/Fixed/Matched/Source/Match confidence/observed_at. Superseded rows at `opacity:.62` with a `superseded` plain chip. Caption: "re-observation inserts a new row; nothing above was updated in place · show all 14 observations"
4. Evidence citation table on S11 — Package/Evidence table/Row/observed_at/Used for

## The freshness bar — the signature component

`.freshbar`, 3px accent left rule, horizontal strip of mono cells each `.lbl` (9.5px uppercase) + `<b>` value. On S2, S3, S4, S6, S8, S9.
Closing note claims it is "a single inclusion tag ... one implementation, so a surface cannot forget it."
Cell vocabulary observed: `rollup computed`, `evidence cut-off`, `policy versions`, `policy run`, `collectors`, `ranked by`, `tracking`, `last full refresh`, `produced`, `excludes`.

## Other components

- **Priority buckets** `.pbucket .p1-.p10` mapped to **four** colour bands, not ten: p1-2 crit, p3-4 warn, p5-7 accent, p8-10 muted.
- **Confidence tags** `.conf` — **text-only, no chip, no dot**: `.verified` ok, `.derived` warn, `.unmapped` unk. Deliberately a different class from `.chip` — identity confidence is not an outcome state.
- **Tables** `.tbl` — th mono 10px uppercase +.09em on `--surface-2`; td `9px 11px`, `vertical-align:top` so `.ev` hangs below. `tr:hover td{background:var(--surface-2)}` is the only genuine hover in the app.
- **Faceted sidebar** `.split` grid `236px / 1fr`, facet rows with right-aligned mono counts.
- **Applied filter bar** `.applied` > `.filterpill` with `<x>✕</x>` remove, right slot carrying the sort statement.
- **Pager** — "Showing 1–8 of 1,204 · page size 50, capped at 200" + 26px square page boxes. No prev/next arrows, no page-size selector.
- **Modal** — `.dim` at 42% ink, `width:min(560px,92%)`, header/body/footer, ghost Cancel + primary action.
- **Toast** `.toast` — 3px left rule, optional 14px spinner ring, `animation:sp 1s linear infinite`.
- **`.hx` / `.hxnote`** — panel headers print the *actual HTMX attribute* that would drive the panel. Documentation-in-the-mock, not UI.

## The health table (S3) — 11 columns

`Package · P · Score · Work · Currency · Vulnerability · KEV · Licence · Py 3.14 · Feedstock · Confidence`

Six facet groups with counts: Search · Vulnerability status (critical/high/none found/**unknown/error/not_applicable**) · Identity confidence (verified/inventory-derived/unmapped) · Priority bucket · Work type · Evidence freshness (stale only).

**The vulnerability facet exposes unknown / error / not_applicable as first-class filterable values, not an "other" bucket.**

Sorting is stated in the `.applied` bar, not column headers: "sorted by **rank** · bucket then score". **No clickable sort controls on any `th`** — `.sorted` is a static indicator only.

## The remediation queue (S6) — 9 columns

`☐ · Package · P · Score · Work · Why this bucket · Readiness · State · Age`

"Why this bucket" is the notable column: a human sentence + `.ev` naming the rule and ruleset version — "KEV-listed advisory with a published fix" / `rule kev_with_fix · rules@6`. Readiness: `ready` / `blocked` / `stale evidence` / `unknown`. Anno: "Readiness and priority are independent: the queue tells you what you cannot do yet rather than hiding it."

## Row actions

**No per-row action menu.** Actions live in three places: the package name link; `evidence ▾` per derived-status row; bulk checkboxes with selected rows at `background:var(--accent-wash)` and a `.app-h` btnrow showing "3 selected" + bulk verbs.

## The five SVG diagrams — all hand-authored inline, no mermaid, no library

D1 collection→evidence→policy→surface · D2 screen map and role gates · D3 UJ-1 swimlane · D4 workflow item state machine · D5 request/task boundary.

All `viewBox` width 1180, `min-width:840px`, `role="img"` + descriptive `aria-label`. A parallel SVG token system (`.box`, `.box-acc/ok/crit/warn`, `.lane`, `.flow`, `.flow-acc`, `.flow-dash`, `.t-ttl/.t-lbl/.t-sm/.t-xs`) all built on `var()` so **diagrams theme with the page**. Three line semantics: solid = primary flow, accent = emphasised path, dashed = secondary/derived.

D2's punchline: a crit-coloured dashed path to "403 — refused, and logged with the user identity / **a queue that is not yours is refused, never rendered empty**".
D4's punchline: "the UI renders only the transitions your role holds; **the service enforces them regardless of what the UI rendered**." States shown `open → triaged → routed → in_progress → resolved / accepted`, each arrow labelled with the required role. Caption disclaims: "State names are illustrative — the spine fixes the mechanism, not the vocabulary."

## Interaction — a fully static mockup

**No `<script>` tag anywhere.** No HTMX or Alpine library loaded, no `onclick`, no real `hx-*` or `x-*` attributes. Every HTMX/Alpine reference is **printed as literal text** in `.hx`, `.hxnote` or `<code>`. `.btn{cursor:default}` makes it explicit.

Documented interaction contract (from `.hx` spans):
| Surface | Attribute |
|---|---|
| S2 queue partial | `hx-get="/queues/compliance/?top=4" hx-trigger="every 60s"` |
| S2 recollect | `hx-post="/collectors/advisory/recollect/" → 202 Accepted` |
| S3 search | `hx-trigger keyup changed delay:300ms` |
| S3 facets | `hx-get`, `hx-target="#health-rows"`, `hx-push-url="true"`, `hx-indicator` |
| S4 evidence disclosure | `hx-get=".../evidence/<domain>/" hx-swap="afterend"` |
| S5 route form | `hx-post` + CSRF in `hx-headers`, `hx-target="#wf-row"` |
| S9 job poll | `hx-get="/jobs/job_01JQ8H2P/" hx-trigger="every 3s" hx-swap="outerHTML"` |

**The stated boundary (line 2884):** "HTMX earns its place on four interactions: facet swaps on the health view, evidence disclosure on package detail, queue transitions posting a form and swapping a row, and job polling. **Everything else can be a plain page load.**"
"Alpine holds view state only — open panels, pending filter selections, bulk checkboxes, modal focus. **It never computes a status, a count, or a timestamp**, because derived state is read-only to the application."
"Every partial is a template fragment the full page also renders, so a swapped table row and a freshly loaded page cannot disagree."

**Validation is server-side by doctrine:** "The invalid state is a bound `IdentityOverrideForm` re-rendered by the server and swapped into the modal body. **Alpine never decides whether a reason is acceptable.**"

**Async is a designed state, not an afterthought:** S9/S10 toasts carry job id, trace id, start time, honest duration estimate, Cancel, plus a "Meanwhile, what is known" panel. "the banner survives a reload — job state is server-side, keyed by the id in the URL."

## Accessibility — good bones, specific gaps

**Good:** semantic elements throughout; every facet checkbox wrapped in its own `<label>`; explicit `for`/`id` on modal fields; global `:focus-visible{outline:2px solid var(--accent);outline-offset:2px}`; **`@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}`**; all SVGs `role="img"` + descriptive `aria-label`; spinner `role="presentation"`.

**The strongest a11y decision, and it is doctrinal:** colour is never the only channel for the five states — every chip carries (a) the lowercase status word as visible text, (b) a distinct marker *shape*, (c) a distinct hue, (d) an `.ev` sentence naming source and time.

**Gaps to close in EXPERIENCE.md:**
- **No `<h1>` inside any app screen** — screens start at `<h2>`, then jump to `<h4>` (panel headers), skipping `<h3>`.
- **No `aria-live` on the async toast** — a job that finishes and swaps out announces nothing.
- **No `aria-sort`** on `<th class="sorted">`.
- **`<x>✕</x>` in `.filterpill` is a made-up element**, not a button, no accessible name. Weakest control in the file.
- Modals have no `role="dialog"`, `aria-modal`, `aria-labelledby`, or focus trap.
- `.errmsg` not tied via `aria-describedby`; `.textarea.invalid` has no `aria-invalid`.
- Select-all header checkbox has no label.
- `a.locked` is a link, not `<button disabled>`; anno claims a tooltip, none present.
- `.chip::before` markers are CSS-generated, invisible to AT — mitigated because the status word is always real text.

## ⚠ CONTRADICTIONS AND GAPS

1. **BOOTSTRAP VS THE TOKEN SYSTEM — the largest open question.** Masthead says "Bootstrap 5.2, inherited from the platform base"; the mockup is drawn in an entirely bespoke IBM Plex + teal system. Closing note admits the tension — "drawn in a neutral system, but every component shown maps onto what the platform already loads" — **but gives no mapping table**, and Bootstrap's badge/table/modal defaults look nothing like `.chip`/`.tbl`/`.modal`. DESIGN.md must resolve: is the token system the contract, or is Bootstrap?
2. **Stale is described as "struck through" but no strikethrough is implemented.** `line-through` appears exactly once in the file — on the prior value of a human override. Stale is an amber chip whose label contains the word.
3. **`.chip.warn` is overloaded three ways:** determinate amber (`lagging`, `medium`, `manual review`), the stale overlay, AND remediation `blocked`. The no-collapse doctrine holds for the four sentinels but not for warn.
4. **The chip label vocabulary is unbounded** — 60+ distinct label strings across 8 variant classes. Doctrine says values are "lowercase and verbatim" but many labels are prose fragments and some contain data (`yes · 3.10.1`, `4 rows returned · limit 500`). **EXPERIENCE.md needs a rule separating status values (closed set) from chip labels (currently open).**
5. **Filtering solved three ways:** S3 faceted sidebar with counts; S6 applied-pills only; S7 sidebar repurposed as a record list; S5/S8/S9 no filtering. No stated rule for when a screen gets facets.
6. **Freshness bar cells vary per screen** despite the "single inclusion tag" claim. Either parameterised (undocumented) or the claim is aspirational.
7. **Nav inconsistent across roles** — S7/S8 swap `My queue`→`Identity queue`, S11 swaps `Coverage`→`Investigate`, S10 omits Coverage entirely where S6/S9 use the `.locked` treatment. Same role, two treatments.
8. Sidebar width 236px (S3) vs 300px (S7). Modal top 26px (S5) vs 40px (S7). No rule.
9. **Two "expanded row" idioms share one colour:** S4 nests a table in a colspan cell on accent-wash; S6 uses accent-wash on the row to mean "selected".

**Defined but unused:** `.btn.danger` (no destructive action exists anywhere), `--accent-2` (only `.anno code`), Plex Serif italic, weight 700.

**Undesigned surfaces:**
- **No generic empty state.** No "your queue is empty", no zero-results, no first-run. Doctrine says a queue that is not yours is refused, never rendered empty — but a legitimately empty own-queue is undrawn.
- **No error states beyond 403 and collector `error`.** No 404, no 500, no "policy run never completed", no session-expired.
- **No mobile/narrow layout.** Every app screen pinned to `min-width` 920-1180px inside a horizontally scrolling viewport. Closing note gestures at "offcanvas for the facet panel on narrow screens" — undrawn.
- **"Save this view"** button exists; the flow, naming, listing, sharing are undesigned.
- **"Draft tracking issue"** offered on three screens; the draft, its fields, and the tracking-URL write-back are undrawn.
- **"Accept risk"** button exists and D4 requires "a recorded justification"; only the *route* modal is drawn.
- No sign-out, no account/preferences, no theme toggle, no notification surface.
- The "zero groups" sign-in case is described in an anno but not drawn.
- The governed API has no screen.
- No keyboard/shortcut model, no focus order, no toast dismissal or stacking rules.

## The mockup's own invented-vs-settled ledger

**SELF-DECLARED INVENTED (lines 2850-2872) — do NOT codify as decisions:**
URL paths · workflow state names (`open, triaged, routed, in_progress, resolved, accepted` — "the spine fixes the mechanism; the vocabulary is open") · priority rule names and every bucket assignment (**OQ-8**) · freshness targets 24h/7d/30d (**OQ-7**) · the 500-row export cap and any latency figure (**OQ-5**) · advisory source names and licence policy outcomes (**OQ-1, OQ-2**) · channel names (**OQ-4**) · the 14-month feedstock-inactivity threshold (**OQ-10**) · all internal usage values · all package names, CVE ids, versions, counts, timestamps.

**SELF-DECLARED SETTLED (lines 2829-2847) — safe to codify:**
The three roles and what each reads vs acts on · the five outcome states, lowercase values, no-collapse rule · confidence values and their gate, distinct from match confidence · the rollup (one row per package always, carrying computed_at, cut-off, per-domain version map) · evidence tables and run ledgers as a separate class · one workflow table / three filtered queues / finding-key items / (from_state,to_state,required_role) transitions · the override as the only human write to governed reference data with required reason + audit row in one transaction · the six recurring reports each stating cut-off and policy version · structural pagination, the request/task boundary, three Celery queues · the export column contract · the NL capability as post-MVP and read-only.
