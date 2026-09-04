# Reconciliation — `imports/ui-mockups.html`

What the mockup proposed, and what the spines did with it. Nothing in the import was
discarded silently; every item below is adopted, corrected, deferred or dropped with a reason.

Source: `docs/ux/ui-mockups.html`, added by PR #13 (`docs(ux): add screen mockups and workflow
diagrams for the app surface`). 2911 lines. Self-declared status: "Mockup — not implemented".

## Adopted wholesale

| Mockup decision | Where it now lives |
|---|---|
| The full token system — 30+ custom properties, light and dark | DESIGN.md → Colors, verbatim |
| Dual-gated dark mode (`prefers-color-scheme` + `data-theme`) | DESIGN.md → Colors |
| Four sentinel hues deliberately off the determinate ramp | DESIGN.md → Colors, with the CPM-SM-C1 rationale made explicit |
| Four sentinel marker *shapes* — hollow ring, dashed ring, struck circle, triangle | DESIGN.md → Components → `.chip`, exact CSS preserved |
| `.ev` evidence footline with its 9px tie-line and `source · observed_at · qualifier` grammar | DESIGN.md → Components; EXPERIENCE.md → Evidence and Provenance |
| The freshness bar as mandatory page chrome | DESIGN.md → Components; EXPERIENCE.md, tied to CPM-AD-11 |
| `.conf` as text-only and deliberately NOT a chip | DESIGN.md → Components, with the reason stated: a confidence is not an outcome state |
| P1–P10 collapsed to four colour bands | DESIGN.md → Components → `.pbucket` |
| IBM Plex Sans / Mono / Serif, and the mono-for-machine-values rule | DESIGN.md → Typography, promoted from convention to a load-bearing rule |
| Two shadows only; panels, cards and tables flat | DESIGN.md → Elevation & Depth |
| The 3px left rule as a semantic "provenance / system speech" marker | DESIGN.md → Elevation & Depth |
| The tight radius system (2/3/4/6/7px) | DESIGN.md → Shapes |
| `prefers-reduced-motion` suppression | EXPERIENCE.md → Accessibility Floor |
| The HTMX four-interaction boundary and the Alpine view-state-only rule | EXPERIENCE.md → Interaction Primitives |
| Server-side validation doctrine ("Alpine never decides whether a reason is acceptable") | EXPERIENCE.md → Interaction Primitives |
| "Every partial is a fragment the full page also renders" | EXPERIENCE.md → Interaction Primitives |
| The in-progress toast contract — job id, trace id, duration estimate, Cancel, survives reload | EXPERIENCE.md → State Patterns |
| "Meanwhile, what is known" panel | EXPERIENCE.md → State Patterns, as the anti-optimistic-UI affordance |
| Readiness and priority as independent axes | EXPERIENCE.md → Queues and Transitions |
| "The UI renders only the transitions your role holds; the service enforces them regardless" | EXPERIENCE.md → Queues and Transitions |
| The three protagonists with full names | EXPERIENCE.md → Key Flows |

## Corrected — the mockup was wrong or inconsistent

| Mockup | Correction | Why |
|---|---|---|
| `--warn` carrying three meanings: determinate amber, the stale overlay, and remediation `blocked` | `--warn` means determinate amber only. Stale is a property of a status; `blocked` moves to the CPM-FR-41 readiness axis | Kevin's decision. Three unrelated meanings in one channel is the collapse CPM-FR-6 forbids — the four sentinels were protected but the fifth axis leaked |
| Stale promised as "struck through" in prose; never implemented (`line-through` appears once, on an override's prior value) | A trailing `::after` amber hold mark, plus the amber footline, plus a visually-hidden `stale` | A strikethrough degrades the status word, which is one of the four channels carrying meaning. The `::before` slot belongs permanently to the state's own marker |
| Chip label `critical · stale` | Visible label is the bare `OutcomeState` value; staleness moves to the mark, the footline and the hidden text | Keeps status *values* (closed set, lowercase, verbatim) separate from chip *labels* (was unbounded at 60+ strings) |
| 60+ open-ended chip labels, some prose fragments, some carrying data (`error · 429`, `yes · 3.10.1`) | Five rules (L1–L5): the label *is* the enum value; every qualifier moves to the footline | Collapses three closed enumerations out of an open set, and makes the row strictly more informative |
| Nav inconsistent across roles — `My queue` → `Identity queue`, `Coverage` omitted on S10 but `.locked` on S6/S9 | One nav model for all three roles. `workflow:my_queue` resolves server-side so it can never 403. `a.locked` deleted from the system | Read access is shared across roles (CPM-AD-13); a locked nav item implied otherwise |
| Sidebar 236px on S3, 300px on S7 | 236px | Drift, not intent |
| Modal top offset 26px on S5, 40px on S7 | 26px | Drift, not intent |
| Two hex literals outside the token system (`#fff`, `#08171c`) | Promoted to an `--on-accent` token | Collapses three paired dark-mode selectors; zero hex values now live outside `:root` |
| Filter-pill remove control as a bare `<x>` element | A real `<button>` with an accessible name | Not focusable, announces nothing — the weakest control in the file |
| Masthead claims "Bootstrap 5.2, inherited from the platform base" while drawing a bespoke system, with a promised mapping table that was never supplied | Bootstrap keeps grid, utilities and crispy-forms output; the tokens own semantic colour. An explicit override table replaces the promised mapping | They were never competing for the same job, so no mapping was needed — the framing was the error |
| No spacing scale at all | A scale derived from the mockup's own observed clustering (1/4/8/12/16/24/32/56) | Derived rather than imposed, so the density the mockup achieved survives |
| IBM Plex weight 700 loaded, never used; Serif loaded for app use | 700 dropped from the load; Serif marked documentation-only | The app ships Sans + Mono |

## Deferred, with the gap named

| Mockup gesture | Disposition |
|---|---|
| "Save this view" button, no flow behind it | **G-1** — cut from v1. `hx-push-url="true"` already puts filter state in the URL; a bookmark is the answer |
| "Draft tracking issue" + tracking-URL write-back | **G-2** — read-only draft for v1. The write-back is forbidden by CPM-FR-3 / CPM-FR-27; tracked state rides on a workflow item instead |
| "Accept risk" button with no justification form | **G-3** — specified as a transition reusing the route modal with a required note. Mock rendered |
| "Offcanvas for the facet panel on narrow screens" | **G-6** — not assumed. Desktop-only floor declared, with the AA Reflow shortfall recorded |
| `data-theme` honoured but never set by any control | **G-5** — v1 honours `prefers-color-scheme` only; the hook is kept for a later preference surface |
| The governed API as a read surface in D1/D2 with no screen | **G-7** — decide before CPM-APP-S07 whether it is an unlisted integrator URL or a fifth nav entry |
| The "zero groups" sign-in case described in an anno, never drawn | **G-4** — platform-owned, outside CPM-EP-APP |

## Dropped

| Mockup element | Why |
|---|---|
| `.btn.danger` | Styled, never rendered, and no destructive action exists anywhere in the product. Every write is a transition or an audited override; nothing is deleted or rejected outright |
| `--accent-2` as a general token | Used only for `.anno code` — documentation chrome, not application UI. Retained in the palette, unused by the app |
| The `.hx` / `.hxnote` attribute annotations | Documentation-in-the-mock. Their *content* was lifted into EXPERIENCE.md → Interaction Primitives; the visual device does not ship |
| Every fixture value — package names, CVE ids, versions, counts, timestamps, the 500-row cap, 24h/7d/30d targets, P1–P10 assignments | Self-declared invented by the mockup's own ledger (lines 2850–2872). None may be lifted into an implementation |

## Qualitative ideas worth preserving that no spine section fully captures

Recorded here so they are not lost between documents:

1. **The editorial framing itself.** The mockup is a specimen book with annotation rails citing requirement ids beneath every screen. That device — a screen and its governing requirements side by side — is why this import was reviewable at all, and it is worth reusing for any future surface.
2. **"A queue that is not yours is refused, never rendered empty."** Carried into EXPERIENCE.md, but the phrasing itself is the clearest one-line statement of the product's whole posture toward absence.
3. **The counter-metric on the coverage view** — *packages presented as clean*, labelled "do not optimise", placed where the person building the review deck reads it before they build the deck. That placement is a deliberate act of design, not an accident of layout.
4. **D4's closing line:** "the UI renders only the transitions your role holds; the service enforces them regardless of what the UI rendered." A one-sentence statement of why nav filtering is not a security boundary.
5. **The invented-versus-settled ledger** at lines 2829–2872. Every design artifact should carry one. It is the single reason this reconciliation could be written without guessing.

## Standing rule

Where this reconciliation and the mockup disagree, the spines win. Where the spines and the
mockup's own invented-versus-settled ledger agree, the item is settled. The mockup remains in
`imports/` unmodified as the historical record.
