---
title: CPM Design Spine
project: conda-package-supply-chain-monitor
scope: CPM-EP-APP
status: final
updated: 2026-09-04
sources:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - imports/ui-mockups.html
name: Conda Package Supply Chain Monitor
description: An internal evidence-first monitoring surface. Django templates, Bootstrap 5.2.3 for structure, plain CSS custom properties for every semantic colour. The whole visual system exists to stop an `unknown` from ever reading as `clean`.
colors:
  # Light. Verbatim from imports/ui-mockups.html lines 7-39.
  paper: '#e9edef'
  surface: '#ffffff'
  surface-2: '#f4f7f8'
  surface-3: '#eaeff1'
  ink: '#0e1719'
  ink-2: '#33454c'
  muted: '#556670'
  line: '#ccd7db'
  line-2: '#e0e8ea'
  accent: '#0d5c73'
  accent-2: '#0a4557'
  accent-wash: '#dfedf1'
  on-accent: '#ffffff'
  ok: '#22643f'
  ok-wash: '#e0efe6'
  warn: '#855505'
  warn-wash: '#f7ecd8'
  crit: '#9d1729'
  crit-wash: '#f7e2e4'
  unk: '#5a6d75'
  unk-wash: '#e6ecee'
  nf: '#3c5a80'
  nf-wash: '#e3eaf3'
  na: '#655684'
  na-wash: '#eae6f2'
  err: '#8a3115'
  err-wash: '#f6e5dd'
  # Dark. Dual-gated: @media (prefers-color-scheme:dark){:root:not([data-theme="light"])}
  # AND :root[data-theme="dark"]. Both blocks carry identical values.
  paper-dark: '#0b1214'
  surface-dark: '#121c1f'
  surface-2-dark: '#172327'
  surface-3-dark: '#1d2c31'
  ink-dark: '#e6eef0'
  ink-2-dark: '#b3c4c9'
  muted-dark: '#8ba1a8'
  line-dark: '#2b3d43'
  line-2-dark: '#223136'
  accent-dark: '#57b6d2'
  accent-2-dark: '#8ad2e6'
  accent-wash-dark: '#123039'
  on-accent-dark: '#08171c'
  ok-dark: '#6cc191'
  ok-wash-dark: '#14301f'
  warn-dark: '#e0ab55'
  warn-wash-dark: '#33260d'
  crit-dark: '#f08a95'
  crit-wash-dark: '#3a161c'
  unk-dark: '#9fb2b9'
  unk-wash-dark: '#1f2c30'
  nf-dark: '#93b3dd'
  nf-wash-dark: '#182533'
  na-dark: '#b7a6dd'
  na-wash-dark: '#241f33'
  err-dark: '#e3946f'
  err-wash-dark: '#331a10'
typography:
  display:
    fontFamily: IBM Plex Sans
    fontSize: clamp(30px, 4.4vw, 45px)
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.022em
  page-title:
    fontFamily: IBM Plex Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.01em
  section-title:
    fontFamily: IBM Plex Sans
    fontSize: 17px
    fontWeight: '600'
    lineHeight: '1.25'
    letterSpacing: -0.01em
  dialog-title:
    fontFamily: IBM Plex Sans
    fontSize: 14.5px
    fontWeight: '600'
    lineHeight: '1.3'
  panel-title:
    fontFamily: IBM Plex Sans
    fontSize: 12.5px
    fontWeight: '600'
    lineHeight: '1.3'
  body:
    fontFamily: IBM Plex Sans
    fontSize: 13px
    fontWeight: '400'
    lineHeight: '1.5'
  body-sm:
    fontFamily: IBM Plex Sans
    fontSize: 12.5px
    fontWeight: '400'
    lineHeight: '1.45'
  meta:
    fontFamily: IBM Plex Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.45'
  stat-value:
    fontFamily: IBM Plex Sans
    fontSize: 27px
    fontWeight: '600'
    lineHeight: '1'
    letterSpacing: -0.02em
  mono-value:
    fontFamily: IBM Plex Mono
    fontSize: 11.5px
    fontWeight: '400'
    lineHeight: '1.5'
  mono-chip:
    fontFamily: IBM Plex Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: '1.5'
  mono-th:
    fontFamily: IBM Plex Mono
    fontSize: 10px
    fontWeight: '500'
    lineHeight: '1.4'
    letterSpacing: 0.09em
  mono-ev:
    fontFamily: IBM Plex Mono
    fontSize: 10px
    fontWeight: '400'
    lineHeight: '1.5'
  mono-eyebrow:
    fontFamily: IBM Plex Mono
    fontSize: 9.5px
    fontWeight: '500'
    lineHeight: '1.4'
    letterSpacing: 0.1em
  editorial-prose:
    fontFamily: IBM Plex Serif
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.62'
    note: 'Documentation and specimen pages only. Never loaded by, and never rendered inside, the application.'
rounded:
  sm: 2px
  DEFAULT: 3px
  md: 4px
  lg: 6px
  xl: 7px
  full: 50%
spacing:
  hairline: 1px
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  '5': 24px
  '6': 32px
  '7': 56px
components:
  chip:
    fontFamily: '{typography.mono-chip.fontFamily}'
    fontSize: '{typography.mono-chip.fontSize}'
    padding: 2px 8px 2px 7px
    radius: '{rounded.sm}'
    border: '1px solid color-mix(in srgb, <state-hue> 32%, transparent)'
    markerGap: 6px
    markerSize: 8px
  chip-ok:
    color: '{colors.ok}'
    background: '{colors.ok-wash}'
    marker: filled-dot
  chip-warn:
    color: '{colors.warn}'
    background: '{colors.warn-wash}'
    marker: filled-dot
  chip-crit:
    color: '{colors.crit}'
    background: '{colors.crit-wash}'
    marker: filled-dot
  chip-unknown:
    color: '{colors.unk}'
    background: '{colors.unk-wash}'
    marker: hollow-ring
  chip-notfound:
    color: '{colors.nf}'
    background: '{colors.nf-wash}'
    marker: dashed-ring
  chip-na:
    color: '{colors.na}'
    background: '{colors.na-wash}'
    marker: struck-circle
  chip-error:
    color: '{colors.err}'
    background: '{colors.err-wash}'
    marker: triangle
  chip-plain:
    color: '{colors.ink-2}'
    background: '{colors.surface-2}'
    border: '1px solid {colors.line}'
    marker: none
  chip-stale-overlay:
    appliesTo: any outcome chip, hue and marker unchanged
    trailingMark: 'two 2px bars, 2px apart, 8px tall, {colors.warn}'
    footline: '{components.ev-stale}'
  ev:
    fontFamily: '{typography.mono-ev.fontFamily}'
    fontSize: '{typography.mono-ev.fontSize}'
    color: '{colors.muted}'
    marginTop: 3px
    tieLine: '9px x 1px {colors.line}'
  ev-stale:
    color: '{colors.warn}'
  freshbar:
    background: '{colors.surface-2}'
    border: '1px solid {colors.line}'
    borderLeft: '3px solid {colors.accent}'
    cellPadding: 7px 13px
    labelType: '{typography.mono-eyebrow}'
  conf:
    fontFamily: '{typography.mono-ev.fontFamily}'
    fontSize: '{typography.mono-ev.fontSize}'
    letterSpacing: 0.03em
    verified: '{colors.ok}'
    derived: '{colors.warn}'
    unmapped: '{colors.unk}'
    marker: none
  pbucket:
    fontFamily: '{typography.mono-value.fontFamily}'
    fontSize: 12px
    fontWeight: '600'
    padding: 2px 7px
    radius: '{rounded.sm}'
    bands: 'p1-p2 crit · p3-p4 warn · p5-p7 accent · p8-p10 muted'
  tbl:
    fontSize: '{typography.body-sm.fontSize}'
    headBackground: '{colors.surface-2}'
    headType: '{typography.mono-th}'
    cellPadding: 9px 11px
    cellBorderBottom: '1px solid {colors.line-2}'
    cellVerticalAlign: top
    rowHover: '{colors.surface-2}'
  panel:
    background: '{colors.surface}'
    border: '1px solid {colors.line}'
    radius: '0'
    shadow: none
    headerPadding: 9px 13px
    bodyPadding: '{spacing.4}'
  stat:
    padding: 13px
    labelType: '{typography.mono-eyebrow}'
    valueType: '{typography.stat-value}'
  btn:
    fontSize: '{typography.body-sm.fontSize}'
    fontWeight: '500'
    padding: 6px 12px
    radius: '{rounded.md}'
    border: '1px solid {colors.line}'
    background: '{colors.surface}'
    color: '{colors.ink}'
  btn-primary:
    background: '{colors.accent}'
    border: '1px solid {colors.accent}'
    color: '{colors.on-accent}'
  btn-danger:
    border: '1px solid color-mix(in srgb, {colors.crit} 45%, transparent)'
    color: '{colors.crit}'
    note: 'Defined, unused in v1. No destructive write exists.'
  modal:
    width: min(560px, 92%)
    radius: '{rounded.lg}'
    shadow: '0 1px 2px rgba(14,23,25,.06), 0 10px 26px -16px rgba(14,23,25,.35)'
    scrimColor: 'color-mix(in srgb, {colors.ink} 42%, transparent)'
    offsetTop: 26px
  toast:
    background: '{colors.surface-2}'
    border: '1px solid {colors.line}'
    borderLeft: '3px solid {colors.accent}'
    padding: 11px 14px
    spinner: '14px ring, 2px {colors.line}, top {colors.accent}'
  input:
    padding: 7px 10px
    radius: '{rounded.md}'
    border: '1px solid {colors.line}'
    background: '{colors.surface}'
    fontSize: '{typography.body-sm.fontSize}'
  input-invalid:
    border: '1px solid {colors.crit}'
    background: '{colors.crit-wash}'
  split:
    display: grid
    gridTemplateColumns: 236px minmax(0, 1fr)
    gap: '{spacing.5}'
  facet:
    font: '{typography.body-sm}'
    count: '{typography.mono-value}'
    activeColor: '{colors.accent}'
  filterpill:
    font: '{typography.mono-chip}'
    color: '{colors.accent}'
    background: '{colors.accent-wash}'
    radius: '{rounded.sm}'
    padding: 2px 8px
  pager:
    font: '{typography.body-sm}'
    pageBox: 26px
    activeBackground: '{colors.accent}'
    activeColor: '{colors.on-accent}'
  field:
    labelFont: '{typography.body-sm}'
    helpFont: '{typography.meta}'
    requiredColor: '{colors.crit}'
    errorColor: '{colors.crit}'
  focus-ring:
    outline: '2px solid {colors.accent}'
    outlineOffset: 2px
    radius: '{rounded.DEFAULT}'
---

# Conda Package Supply Chain Monitor — Design Spine

This document owns **every visual specification**: colour, type, spacing, radii, shadow, marker geometry, and the components built from them. `EXPERIENCE.md` owns **behaviour** — when HTMX swaps and when a plain page load is correct, what Alpine may and may not hold, focus management, announcement, empty and refusal states, and the copy vocabulary that separates status *values* from chip *labels*. This document specifies only what things look like.

## Brand & Style

This is an internal supply-chain monitor for roughly ten thousand conda packages, read by three people in three different moods: a security and compliance reviewer clearing findings before standup, a packaging engineer working a remediation queue, a platform lead assembling a monthly coverage picture. It is a working instrument, not a dashboard. The word "dashboard" appears exactly once in the PRD, in the out-of-scope list.

The posture is **forensic**. Every value on screen is a claim, and every claim carries the evidence and the observation time that produced it. Typographically that means machine values are set in mono, so they read as *readings* rather than as prose. Structurally it means a provenance footline hangs under cells and a freshness strip sits under page headers. Density is high and deliberate — thirteen-pixel body text, nine-by-eleven table cells, hairline rules instead of shadows. Nothing floats. Nothing is decorative.

**The one rule that outranks every aesthetic consideration.** PRD CPM-SM-C1 names the product's primary failure mode: driving the clean-result proportion up by resolving `unknown` or `unmapped` into `clean`. A design that visually flattens `unknown` toward `clean` — a soft grey that reads as "fine", an empty cell, a green-by-default row — actively causes the failure the product exists to prevent. Every colour, marker, footline and copy decision below is downstream of that. Where a visual choice is in tension with elegance, density, or Bootstrap convention, this rule wins.

**The stack constraint shapes everything else.** The application is Python-native by intent: Django templates, django-crispy-forms for form rendering, HTMX for four specific interactions, Alpine for view state. Design tokens are plain CSS custom properties in `src/django_service/static/css/project.css`. **There is no build step, no npm, no preprocessor, no JS framework, no design-system dependency.** Proof that none is needed: the source mockup renders this entire system in 2,911 lines with zero `<script>` tags. Bootstrap 5.2.3 — already loaded from cdnjs with SRI in `base.html` — supplies the grid, the spacing and display utilities, and the markup crispy-forms emits. It supplies no semantic colour. Every semantic component in this document overrides its Bootstrap counterpart outright.

## Colors

The palette is one teal accent, a three-step determinate ramp, and four sentinel hues chosen specifically so they cannot be read as positions on that ramp.

### The token block is the contract

Reproduce this verbatim at the top of `project.css`. Nothing below may introduce a colour outside it.

```css
:root{
  --paper:#e9edef;      --surface:#ffffff;   --surface-2:#f4f7f8;  --surface-3:#eaeff1;
  --ink:#0e1719;        --ink-2:#33454c;     --muted:#556670;
  --line:#ccd7db;       --line-2:#e0e8ea;
  --accent:#0d5c73;     --accent-2:#0a4557;  --accent-wash:#dfedf1;  --on-accent:#ffffff;
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

Dark mode is **dual-gated** — the system preference and an explicit opt-in must both be honoured, and an explicit `light` must be able to defeat the system preference:

```css
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){ /* the dark values below */ }
}
:root[data-theme="dark"]{ /* the same dark values, repeated verbatim */ }
```

Both blocks carry identical declarations. The duplication is correct: without a build step there is no other way to express "system dark unless explicitly light, or explicitly dark regardless of the system".

```css
  --paper:#0b1214;      --surface:#121c1f;   --surface-2:#172327;  --surface-3:#1d2c31;
  --ink:#e6eef0;        --ink-2:#b3c4c9;     --muted:#8ba1a8;
  --line:#2b3d43;       --line-2:#223136;
  --accent:#57b6d2;     --accent-2:#8ad2e6;  --accent-wash:#123039;  --on-accent:#08171c;
  --ok:#6cc191;         --ok-wash:#14301f;
  --warn:#e0ab55;       --warn-wash:#33260d;
  --crit:#f08a95;       --crit-wash:#3a161c;
  --unk:#9fb2b9;        --unk-wash:#1f2c30;
  --nf:#93b3dd;         --nf-wash:#182533;
  --na:#b7a6dd;         --na-wash:#241f33;
  --err:#e3946f;        --err-wash:#331a10;
  --shadow-sm:0 1px 2px rgba(0,0,0,.5);
  --shadow-md:0 1px 2px rgba(0,0,0,.4),0 12px 30px -18px rgba(0,0,0,.9);
```

The dark palette is not a filter over the light one. Each hue was re-picked to hold its character against a near-black ground while staying off the determinate ramp. The sentinels lift to `#9fb2b9` slate, `#93b3dd` blue, `#b7a6dd` violet and `#e3946f` burnt orange, and remain as separable from `#6cc191`/`#e0ab55`/`#f08a95` as they are in light.

**`--on-accent` is a correction of the mockup.** The mockup hard-codes `#fff` on accent fills and repeats a three-selector pair (`:root[data-theme="dark"] X, :root:not([data-theme="light"]) X { color:#08171c }`) to invert it, once for each accent-filled element. Those two literals were the only hex values outside the token block. Promoting them to `--on-accent` collapses the paired selectors and closes the last hole: after this, **no hex value appears anywhere in `project.css` outside the three `:root` blocks.** The behaviour is unchanged — on-accent text is `#ffffff` in light and `#08171c` in dark, on the primary button, the brand glyph and the active page-number box.

There is no theme toggle control in v1. `data-theme` is honoured wherever it is set; nothing in the application sets it.

### What each colour is for

- **`--accent` teal** — the single brand chromatic. Active nav item and its 2px underline, links, primary button fill, brand glyph, the 3px provenance rule, the focus ring, selected-row wash, active page number, facet-on state. It is chrome and emphasis. **It never encodes an outcome state.**
- **`--accent-2`** — inline `<code>` and the emphasised path stroke in diagrams. Nothing else. Deliberately scoped small; it is not a second brand colour.
- **`--ok` / `--warn` / `--crit`** — the determinate ramp. These are positions on a severity or currency axis and mean only that. `--ok` is a clean, current, verified determinate result; `--crit` is determinate red; `--warn` is determinate amber and **exactly one thing** — see "The warn correction" below.
- **`--unk` slate, `--nf` blue, `--na` violet, `--err` burnt orange** — the four sentinels. Chosen for one reason: **none of them sits on the green→amber→red ramp**, so no reader can place them on a severity scale and infer "not that bad" or "worse than amber". Slate leaves the ramp by desaturation, blue and violet by hue in the opposite direction, and burnt orange is close enough to red to read as *wrong* while being browner and duller than `--crit` will ever be.
- **`--paper` / `--surface` / `--surface-2` / `--surface-3`** — the tonal ladder. `--paper` is the ground behind the app; `--surface` is content; `--surface-2` is a recessed or chrome band (table heads, panel headers, sidebar, toolbars, the freshness bar, the toast); `--surface-3` is a deeper recess (browser chrome, meter troughs, inline-code ground, the lowest priority band).
- **`--line` / `--line-2`** — structural hairlines. `--line` for a container edge or band boundary; `--line-2` for a row divider or a hairline grid gap. That two-weight distinction is the whole of the app's structural hierarchy.
- **`--ink` / `--ink-2` / `--muted`** — the text ladder: primary value, secondary prose, metadata. `--muted` is the default colour of every `.ev` footline and every mono micro-label.
- **The `*-wash` pairs** — each semantic hue's low tint. Used only as a chip background, a `.pbucket` band, a diagram box fill, or a callout ground. **Never as a page or panel background.** A washed panel would tint whole regions with a status meaning.

### `color-mix` ratios are tokens too

Four mix percentages recur and carry meaning. Treat them as fixed values, not as taste:

| Ratio | Use |
|---|---|
| 32% | every chip border — `color-mix(in srgb, <hue> 32%, transparent)` |
| 40% | diagram box strokes for `ok` / `crit` / `warn` |
| 42% | the modal scrim over `--ink` |
| 45% | `.btn.danger` border, `.hxnote` dashed border, the diagram accent stroke |

### The contrast floors this palette must hold

EXPERIENCE.md assigns contrast ratios to this document. This section accepts them, and sets the floor at **4.5:1 for every status chip, footline, table header and metadata label**, in both themes. Chip text is 11px and mono, so it is never large text and never qualifies for the 3:1 allowance.

Three consequences follow, and none of them is a matter of taste.

**`--muted` is `#556670`, not a lighter grey.** At `#63767e` it failed against `--surface-2` (4.41), `--surface-3` (4.10), `--paper` (4.03) and `--accent-wash` (3.96). Those four grounds carry every evidence footline in the product, including footlines on a hovered or selected row. The corrected value clears all four — 5.54 / 5.15 / 5.06 / 4.98 — with its hue and its ladder position intact.

**`--unk` on `--unk-wash` is the tightest passing pair in the system, at 4.537.** It has almost no headroom, so **do not lighten `--unk` or darken `--unk-wash`** without recomputing. That pair is the `unknown` chip, the one state that must never be easy to overlook.

**Superseded rows are not dimmed, which is the exception a reader will expect and not find.** Dimming superseded evidence is a real signal, but `opacity:.62` on `--ink-2` computes to 3.45:1 in light and 4.48:1 in dark, and both fail. **Superseded rows are marked by their `superseded` chip and by placement, not by opacity below 1.** Where a dim is wanted, `--muted` at full opacity is the floor.

### The warn correction — stale is not a status

The mockup overloaded `--warn` three ways: determinate amber (`lagging`, `medium`, `manual review`), the stale overlay, and remediation `blocked`. That is a real defect, and it is exactly the collapse CPM-FR-6 forbids. Three unrelated meanings sharing one channel leave the channel carrying no meaning at all.

**Corrected, and binding:**

1. **`--warn` means determinate amber and nothing else.** A middle position on a severity or currency ramp: `lagging`, `medium`, `manual review`, the `p3`–`p4` priority band, `inventory-derived` package-identity confidence. One meaning, one hue.
2. **Stale is a property of a status, not a status in its own right.** A stale `critical` is still `critical`: it keeps `--crit`, keeps its filled-dot marker, keeps the word `critical`. A stale `clean` keeps `--ok`. Staleness is expressed by a **trailing amber mark on the chip plus an amber `.ev` footline** — an overlay on top of a status, never a replacement for one. Full specification in Components → the stale overlay.
3. **`blocked` is not an outcome status.** It belongs to the CPM-FR-41 readiness axis (`ready` / `blocked` / `unknown`, plus stale), which is a separate column with its own vocabulary. It is never rendered as an outcome chip and never takes `--warn` on the outcome axis.

There are five outcome states and there will never be a sixth. `blocked`, `stale`, `superseded`, `skipped` and every workflow state are not among them.

## Typography

Three families, from Google Fonts, loaded by `<link>` in `base.html` with `preconnect` to `fonts.googleapis.com` and `fonts.gstatic.com`.

```
IBM Plex Sans   400 500 600      — UI, headings, prose inside the app
IBM Plex Mono   400 500 600      — every machine value, without exception
IBM Plex Serif  400 600 + italic — documentation and specimen pages only
```

**The application loads Sans and Mono only.** Serif never appears inside the app, so the app must not pay for it; Serif is loaded exclusively by the design documentation and the specimen page. **Weight 700 is dropped from the font load** — the mockup requested it and never used it. 600 is the heaviest weight in the system.

[ASSUMPTION: Google Fonts is reachable from the deployment. The platform already loads Bootstrap 5.2.3 from cdnjs, so third-party CDN egress is established, but the Google Fonts variable stylesheet has no SRI equivalent. If egress or SRI policy forbids it, self-host the two families as static WOFF2 under `static/fonts/` and swap the `<link>` for an `@font-face` block. Nothing else in this document changes.]

### The mono rule — load-bearing

**Every machine value is set in `--mono`.** Timestamps, package names in identifier position, version strings, advisory identifiers, trace ids, job ids, URLs, counts, table column headers, micro-labels, eyebrows, status chip labels, evidence footlines, priority buckets, key-value keys, page numbers.

This is not a stylistic preference. It is a second, always-on signal that a value came from a machine and has an observation time behind it. Prose describes; mono reports. A reviewer scanning a dense table can tell at a glance which cells are claims and which are guidance. Setting a timestamp in Sans, or a sentence of guidance in Mono, breaks the distinction the entire surface depends on.

### The ramp is the whole scale

The app shell resets to **13px**. The documentation and specimen shell is 15px/1.55; the application is not.

| Role | Family | Size | Weight | Tracking | Where |
|---|---|---|---|---|---|
| `display` | Sans | `clamp(30px, 4.4vw, 45px)` | 600 | −0.022em | Documentation mastheads. Not used in the app. |
| `page-title` | Sans | 20px | 600 | −0.01em | The one `<h1>` per app screen |
| `section-title` | Sans | 17px | 600 | −0.01em | Sign-in box, major in-page section |
| `dialog-title` | Sans | 14.5px | 600 | — | Modal header |
| `panel-title` | Sans | 12.5px | 600 | — | Panel header |
| `body` | Sans | 13px | 400 | — | App default |
| `body-sm` | Sans | 12.5px | 400 | — | Table cells, buttons, nav, inputs, help text |
| `meta` | Sans | 12px | 400 | — | Facet rows, secondary lines |
| `stat-value` | Sans | 27px | 600 | −0.02em | `.stat .big`, tabular numerals |
| `mono-value` | Mono | 11.5px | 400 | — | Inline machine values, `.mono` spans |
| `mono-chip` | Mono | 11px | 400 | — | Chip labels; `.chip.sm` at 10px |
| `mono-th` | Mono | 10px | 500 | +0.09em, uppercase | Table column headers |
| `mono-ev` | Mono | 10px | 400 | — | `.ev` footlines, `.conf` tags |
| `mono-eyebrow` | Mono | 9.5px | 500 | +0.1em, uppercase | `.stat .lbl`, `.freshbar .lbl`, sidebar group headings |
| `editorial-prose` | Serif | 16px | 400 | — | Documentation only. **Never inside the app.** |

The size scale in the mockup was ad hoc — twenty distinct px values with no ratio. The table above is the whole scale; a size not in it does not exist. Line height is 1.2 on headings, 1.5 on body and mono, 1.45 on small sans.

### Tracking is a signal, never a decoration

It is applied in exactly two directions and never arbitrarily:

- **Negative on display headings** (−0.01em to −0.022em, scaling with size). Large type sets loose by default; tightening it makes a heading read as one object.
- **Positive on mono micro-labels** (+0.03em to +0.1em, always paired with `text-transform: uppercase`). Small uppercase mono sets tight and closes up; opening it keeps a 9.5px eyebrow legible and marks it as a *label* rather than a *value*.

Body text, table cells and chip labels take no tracking at all.

### Other type rules

- `font-variant-numeric: tabular-nums` on `.tbl .num` and `.stat .big`, so columns of numbers align and a changing counter does not reflow.
- `text-wrap: balance` on `h1`–`h4`.
- Headings are never set in `--serif`, never italic, never in caps.

## Layout & Spacing

**The mockup has no spacing token.** Padding and gaps are ad hoc — some thirty distinct values. This document imposes a scale.

### How the scale was derived

The observed values cluster into six bands. The scale is those clusters' modes, snapped to a 4px grid, plus a 1px hairline step:

| Step | Value | Derived from the cluster |
|---|---|---|
| `hairline` | 1px | the 1px `gap` on hairline grids over `--line-2` (`.toc`, `.annos`, `.legend`) |
| `1` | 4px | micro offsets — `.stat .big` top 4, `.btn.sm` vertical 4, `.urlbar` vertical 4 |
| `2` | 8px | inline gaps 5–9 — `.btnrow` gap 8, `.facet` gap 8, `.side h5` margin 8 |
| `3` | 12px | card and column gaps 12–14 — `.cards` gap 12, `.kv` gaps 7/14 |
| `4` | 16px | container padding 13–18 — `.panel .body` 13, `.side` 14, `.modal .body` 16, `.app-body` 18 |
| `5` | 24px | section gaps 22–28 — `.figure` top 24, `.notebox` top 24, `.wrap` inline 28 |
| `6` | 32px | the single large value 30 (`.loginbox`) |
| `7` | 56px | the band rhythm 44/56 (documentation only) |

Adopting the scale moves a handful of mockup values by one to three pixels — `.app-body` from 18 to 16, `.panel .body` from 13 to 16, `.loginbox` from 30 to 32. That is the point of having a scale. The scale is derived from the mockup's own clustering rather than from a fresh ratio, so the density the mockup achieved survives intact.

### What the scale governs, and what it does not

The scale governs **layout**: container padding, gaps between blocks, section margins, grid gutters.

It does **not** govern **control-internal metrics**. A chip's `2px 8px 2px 7px`, a table cell's `9px 11px`, a button's `6px 12px`, an input's `7px 10px` are optical values tuned to the 13px shell and to each control's marker geometry — the chip's asymmetric 7/8 exists because the 8px marker sits on the left and needs less optical inset than the label's trailing edge. These are fixed per component and listed in Components. Do not round them onto the layout scale.

### Every control clears a 24×24px hit area

EXPERIENCE.md assigns target sizes to this document. This section accepts them. WCAG 2.5.8 requires 24×24px for pointer targets, and two controls fail it if built at their label size: the filter-pill remove control and the `evidence` disclosure control. Both take a **minimum 24×24px hit area, achieved with padding rather than by growing the visible mark** — the pill and the disclosure caret keep their drawn size and gain invisible target area around it. The rule applies to every control in a dense table row, not only to those two.

This is a control-internal metric, so it does not move onto the layout scale either.

### Three layout idioms, and no others

Page scaffolding uses Bootstrap's grid and its spacing/display/flex utilities as-is. Inside the content area, three idioms exist:

- **The split** — `grid-template-columns: 236px minmax(0, 1fr)`, a faceted sidebar on `--surface-2` against a main pane on `--surface`, wrapped in a 1px `--line` border with no gutter between them. **236px is the single sidebar width.** The mockup also used 300px on one screen; that is a defect, not a variant. Rationale in Components → `.split`.
- **The card row** — `.cards` at `gap: {spacing.3}`, in two, three or four equal columns (`.c2` `.c3` `.c4`), each cell a `.panel`.
- **The hairline grid** — a grid with `gap: {spacing.hairline}` on a `--line-2` background, so the gap itself draws the rules. Used for tiled index and legend blocks.

Content is left-aligned inside its container; nothing in the app is centred. Numeric table columns are right-aligned via `.num`.

### A desktop floor of 1180px, decided rather than omitted

The app is a desktop instrument at high density. App screens assume a viewport of at least **1180px**, the widest minimum any surface requires. A surface narrower than its own content scrolls horizontally **inside its own container**, and the page body never scrolls horizontally. 1180px is the single stated figure; EXPERIENCE.md's Accessibility Floor refers to it rather than restating a range.

**The floor is a decision, not an omission.** No source states a device, browser or breakpoint requirement — the PRD is silent across all 917 lines — and all three journeys are desk-bound: Dana before standup, Ravi across two systems, Sam building a review deck. No mobile or tablet layout is specified, and the mockup's gestured-at offcanvas facet panel is **not** assumed into existence.

The cost is stated rather than hidden. Pinning screens to a desktop minimum produces horizontal scrolling under zoom, which is a genuine WCAG AA shortfall against 1.4.10 Reflow. EXPERIENCE.md's Accessibility Floor records the shortfall and states its true threshold. Revisiting it is a scoped piece of work, not a default this document quietly assumed.

## Elevation & Depth

**Two shadows exist, both tokens, and neither is used on ordinary application chrome.**

- `--shadow-sm` — documentation figure plates only.
- `--shadow-md` — exactly three surfaces: the sign-in box, the modal, and the specimen browser frame. All three genuinely sit above the page.

**Panels, cards and tables have no shadow at all.** Elevation inside the app is expressed by 1px borders and `--surface-2` fills, not by light. A recessed band — table head, panel header, sidebar, toolbar, freshness bar, toast — is `--surface-2` inside a `--line` edge. A deeper recess is `--surface-3`. That is the entire depth vocabulary, and it is what keeps a dense table from looking like a stack of floating cards.

### The 3px left rule

The one distinctive elevation move in the system is not a shadow. It is a **3px left border**, and it is a **semantic marker, not decoration**. It means: *this block is provenance, or the system speaking about itself.*

```css
border:1px solid var(--line); border-left:3px solid var(--accent);
```

It appears on `.freshbar` (page-level provenance), `.toast` (a job reporting on its own progress) and `.notebox` (a system-level statement). Its colour is overridden per instance to carry the block's semantic:

| Rule colour | Meaning |
|---|---|
| `--accent` | default — provenance or system speech |
| `--unk` | the block concerns unresolved or unmapped state |
| `--na` | the block concerns a `not_applicable` scope |
| `--ok` | the block reports a completed, clean outcome |
| `--warn` | the block reports stale or lagging evidence |

Never use the 3px rule for visual emphasis on a block that is not provenance or system speech, and never colour it with a hue whose meaning contradicts the block's content.

### Borders as language

- **Solid 1px `--line`** — a container edge or band boundary.
- **Solid 1px `--line-2`** — a row divider or hairline grid gap.
- **Dashed** — provisional, annotative, or documentation of itself. `.hxnote` is dashed; the `not_found` marker is a dashed ring. Dashed never means "disabled".
- **2px bottom border in `--accent`** on the active top-nav item — the only place a border carries selection.

## Shapes

Deliberately tight and mostly square. The system reads as an instrument panel, not a consumer app. Nothing is a pill; nothing is soft.

| Token | Value | Applied to |
|---|---|---|
| `{rounded.sm}` | 2px | chips, filter pills, priority buckets, meters, washed callouts, `.hxnote`, `.reftag` |
| `{rounded.DEFAULT}` | 3px | the focus ring, the brand glyph, page-number boxes, small diagram nodes |
| `{rounded.md}` | 4px | buttons, inputs, selects, textareas, the search box, diagram containers |
| `{rounded.lg}` | 6px | the sign-in box, the modal |
| `{rounded.xl}` | 7px | the specimen browser frame (documentation only) |
| `{rounded.full}` | 50% | status-chip markers, avatars, the toast spinner, chrome dots |

`{rounded.full}` is reserved for genuinely circular objects of 8–24px. **No surface is ever pill-shaped.** The 2px radius on a chip is precisely what stops it reading as a Bootstrap badge.

The `.panel` has **no radius at all** — square corners, 1px border. Panels tile against each other and against table edges; a radius would open a gap at every junction.

## Components

Visual specification only. Interaction, state transitions, focus order, announcement, and the copy vocabulary are in **EXPERIENCE.md**.

Every component here **overrides its Bootstrap counterpart**. Bootstrap's `.badge`, `.table`, `.modal`, `.btn`, `.card`, `.alert`, `.pagination` and `.form-control` defaults do not apply and must not be expected. What Bootstrap keeps is listed at the end of this section.

### `.chip` — the status chip, the heart of the system

```css
.chip{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;
  padding:2px 8px 2px 7px;border-radius:2px;border:1px solid;white-space:nowrap;line-height:1.5}
.chip::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
.chip.sm{font-size:10px;padding:1px 6px}
```

Each variant sets `color: var(--hue)`, `background: var(--hue-wash)`, and `border-color: color-mix(in srgb, var(--hue) 32%, transparent)`. Because the marker is `currentColor`, hue and marker can never drift apart.

**Four redundant channels carry every outcome state.** Colour alone is never sufficient, and neither is any single other channel:

1. **Hue** — determinate on the ramp, sentinel deliberately off it.
2. **Marker shape** — a distinct geometry per sentinel.
3. **The lowercase status word as visible text** — the `OutcomeState` value verbatim, never re-labelled, never abbreviated, never replaced by an icon.
4. **The `.ev` footline** — source and observation time underneath.

Remove any one channel and the other three still separate the states. That redundancy is the design.

#### Marker geometry, exactly

| State | Class | Marker CSS | Reads as |
|---|---|---|---|
| determinate | `.ok` `.warn` `.crit` | the default `::before` — 8px circle, `background: currentColor` | **filled dot** |
| `unknown` | `.unknown` | `background:transparent; border:1.5px solid currentColor` | **hollow ring** |
| `not_found` | `.notfound` | `background:transparent; border:1.5px dashed currentColor` | **dashed ring** |
| `not_applicable` | `.na` | `background:linear-gradient(to bottom right, transparent 44%, currentColor 44%, currentColor 56%, transparent 56%); border:1.5px solid currentColor` | **struck circle** — a solid ring crossed by a 12%-wide diagonal bar |
| `error` | `.error` | `border-radius:0; clip-path:polygon(50% 0, 100% 100%, 0 100%); height:9px` | **triangle** |
| non-outcome metadata | `.plain` | `::before{display:none}` | **no marker** |

The four sentinel markers are mutually distinguishable at 8px by geometry alone: filled, hollow, dashed, struck, angular. Print the page in greyscale and every state is still separable.

`.plain` is the **only markerless chip** and takes `--ink-2` on `--surface-2` with a `--line` border. It carries non-outcome facts only: workflow states, `superseded`, `skipped`, `authority`, `idle`, a selection count. **The five outcome states are never rendered `.plain`, and `.plain` is never used to say something is fine.**

#### The stale overlay

Stale is an overlay on a status, never a status. The chip keeps its hue, its marker and its word. It gains three things:

**A trailing amber hold mark.** The `::before` slot belongs permanently to the state's own marker, so the stale mark takes `::after`:

```css
.chip.is-stale::after{content:"";flex:none;width:6px;height:8px;margin-left:1px;
  background:linear-gradient(to right,
    var(--warn) 0 2px, transparent 2px 4px, var(--warn) 4px 6px)}
```

Two 2px vertical amber bars, 2px apart, 8px tall — the same optical height as the leading marker, on the opposite side of the label. It reads as *held*: the conclusion stands, but it cannot be acted on until the evidence is re-collected.

Why this geometry. It is rectilinear where all four sentinel markers are round or triangular; it sits on the right where they sit on the left; it is `--warn` where they are `currentColor`; and at 6×8px it resolves cleanly at 11px in a dense table in both themes (`#855505` on a light wash, `#e0ab55` on a dark one, both well clear of the chip grounds they sit on). It cannot be confused with any sentinel and it cannot be mistaken for a state of its own.

**This replaces the mockup's unimplemented strikethrough.** The mockup's `#states` prose promised the conclusion would be "struck through"; `line-through` appears exactly once in the whole file, and not on a chip. A strikethrough is also the wrong instrument here — it would degrade the status word, and the status word is a load-bearing channel that must stay fully legible.

**An amber `.ev` footline.** `.ev.stale` recolours the footline to `--warn`, and its text names the staleness in words. The footline is real text where the mark is CSS-generated, so the meaning survives for a reader who cannot see the mark.

**The word `stale` as text inside the chip**, visually hidden. The chip's visible label stays the bare `OutcomeState` value — `critical`, not `critical · stale` — which preserves the lowercase-and-verbatim rule and keeps the closed set of status *values* separate from the open set of chip *labels*. A visually-hidden span carries `stale` so assistive technology announces "critical stale". Markup and announcement details belong to EXPERIENCE.md.

So a stale critical is: `--crit` hue, filled dot, the word `critical`, the amber hold mark, an amber footline saying so. Three channels carry staleness, and none of them is `--warn` on the chip's own hue.

### `.ev` — the evidence footline

```css
.ev{font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:3px;
  display:flex;gap:6px;align-items:center;white-space:nowrap}
.ev::before{content:"";width:9px;height:1px;background:var(--line);flex:none}
.ev.stale{color:var(--warn)}
```

The `::before` is a **9px tie-line** — a one-pixel horizontal rule that attaches the footline to the value above it. Without it, a 10px muted line under a chip reads as an unrelated caption; with it, the footline is visibly subordinate to the value it explains. It is the smallest and most characteristic mark in the system, and it must not be dropped for tidiness.

Grammar is fixed: `<source table or collector> · <observed_at> [· <qualifier>]`. The footline wraps (`white-space: normal`) inside panels and toasts, where the line is long and the column narrow; in table cells it does not wrap.

**Every displayed status carries one.** CPM-FR-37 and CPM-AD-11 make this mandatory chrome, not progressive disclosure.

### `.freshbar` — the freshness bar

The page-level provenance strip and the signature component of the system. A horizontal row of mono cells on `--surface-2`, inside a 1px `--line` border with the 3px `--accent` left rule. Each cell is `7px 13px` with a `--line-2` right divider (none on the last) and holds a `.lbl` in `mono-eyebrow` followed by a `<b>` value in `--ink-2` at weight 500. The bar wraps rather than scrolls.

It sits directly under the page header on every list, every detail view and every report. Cell content is parameterised per surface — rollup computed, evidence cut-off, policy versions, policy run, collectors, ranked by, tracking, last full refresh, produced, excludes.

### `.conf` — the package-identity confidence tag

```css
.conf{font-family:var(--mono);font-size:10px;letter-spacing:.03em;color:var(--muted)}
.conf.verified{color:var(--ok)}
.conf.derived{color:var(--warn)}
.conf.unmapped{color:var(--unk)}
```

**Text only. No chip, no border, no marker. This is deliberate and it is not a shortcut.** Package-identity confidence is not an outcome state. Giving it chip form would put it on the same visual axis as the five states and invite exactly the collapse CPM-FR-6 forbids. The tag is an annotation *on* a row, not a verdict *about* it.

`--warn` on `.derived` is consistent with the corrected single meaning of warn: `inventory-derived` is a determinate middle position, shown normally and labelled. CPM-AD-5 is explicit — a package-identity confidence label never degrades the value beneath it, so a derived row is never greyed, dimmed, hidden, or turned into `unknown`.

### `.pbucket` — the priority bucket

```css
.pbucket{font-family:var(--mono);font-weight:600;font-size:12px;padding:2px 7px;
  border-radius:2px;display:inline-block;letter-spacing:.02em}
```

P1–P10 map to **four colour bands, not ten**: `p1`–`p2` on `--crit` / `--crit-wash`, `p3`–`p4` on `--warn` / `--warn-wash`, `p5`–`p7` on `--accent` / `--accent-wash`, `p8`–`p10` on `--muted` / `--surface-3`. Ten hues would be ten discriminations a reader has to make; four bands are scannable, and the exact bucket number is still printed inside the badge.

No marker, no border, bold mono — visually distinct from a `.chip` at a glance, which is what stops a priority being read as a status.

[The *content* of P1–P10 — the rule set, the score function, and which findings land in which bucket — is PRD OQ 8 and is undefined in every source. This document specifies only the presentation mapping.]

### `.tbl` — the data table

`border-collapse: separate; border-spacing: 0`, 12.5px.

- **`th`** — `mono-th`, uppercase, +0.09em, `--muted`, weight 500, `9px 11px`, on `--surface-2` between a `--line` top and bottom border, `white-space: nowrap`. `.sorted` recolours to `--accent` and is a **static indicator, not a control** — the sort statement lives in the applied-filter bar, not in the column head.
- **`td`** — `9px 11px`, `border-bottom: 1px solid var(--line-2)`, and **`vertical-align: top`**. Top alignment is what lets the `.ev` footline hang below its value without pushing the row's other cells off their baseline. It is not optional.
- **`tr:hover td`** — `--surface-2`. **The only genuine hover effect in the application.**
- **`.num`** — mono, `tabular-nums`, right-aligned.
- **`.pkg`** — 13px weight 600; its link is `--ink` and undecorated, going `--accent` and underlined on hover.
- **Selected row** — `--accent-wash`.

Inside a `.panel`, cells wrap (`white-space: normal`); at page level they do not.

Note the one collision to avoid: `--accent-wash` marks both a selected row and the ground of an expanded evidence disclosure. Never let both appear in the same table at the same time; if a selected row can also be expanded, the disclosure block moves to `--surface-2`.

### `.panel` — the content container

1px `--line`, square, **no shadow**, `--surface` ground, `min-width: 0`, `overflow-x: auto`. The header is a `--surface-2` band at `9px 13px` with a `--line-2` bottom border, carrying a `panel-title` on the left and optional mono metadata on the right. The body is `{spacing.4}`.

`.kv` inside a panel body is a `150px minmax(0, 1fr)` definition grid: `dt` in 10.5px mono `--muted`, `dd` in `--ink` with `word-break: break-word`.

### `.stat` — the metric tile

Inside a `.panel`, padded `13px`. A `mono-eyebrow` label, then `stat-value` at 27px/600 with `tabular-nums` and −0.02em, then an optional 11.5px `--muted` foot line. An optional `.bar` beneath: 5px tall, `{rounded.sm}`, a `--surface-3` trough filled by semantic-hued segments.

A stat tile never states a bare number without its label and its foot line. A count with no denominator and no provenance is the same failure as a status with no evidence.

### `.btn` — buttons

12.5px Sans, weight 500, `6px 12px`, `{rounded.md}`, 1px `--line`, `--surface` ground, `--ink` text, `inline-flex` with a 6px gap.

- `.primary` — `--accent` fill and border, `--on-accent` text.
- `.ghost` — transparent background, border retained.
- `.danger` — `--crit` text on a `color-mix(--crit 45%)` border. **Defined and unused in v1**: the only two writes are a workflow transition and a package-identity override, and neither is destructive.
- `.sm` — 11.5px, `4px 9px`.

There is no per-row action menu anywhere in the application. Actions live in the page-header button row, in the package-name link, in a per-row evidence disclosure control, and in bulk verbs that appear when rows are checked.

### `.modal` — the dialog

`width: min(560px, 92%)`, `{rounded.lg}`, `--surface`, 1px `--line`, `--shadow-md`, over a scrim of `color-mix(in srgb, var(--ink) 42%, transparent)`. Header at `13px 16px` with a `dialog-title` and a `--line-2` bottom border; body at `{spacing.4}` as a column with `{spacing.3}` gaps; footer at `12px 16px` on `--surface-2` with a `--line-2` top border, buttons right-aligned, ghost Cancel then primary action.

**Vertical offset is 26px, always.** The mockup used 26px on one screen and 40px on another; that is a defect, not a variant.

### `.toast` — the async progress banner

The in-progress state CPM-AD-9 requires, rendered as an in-page banner rather than a floating notification. `--surface-2` ground, 1px `--line`, 3px `--accent` left rule, `11px 14px`, a flex row with an 11px gap. Optionally led by a 14px `.spin` ring — 2px `--line` with an `--accent` top edge, `animation: sp 1s linear infinite`. A 12.5px bold line, an 11.5px `--muted` line, and `.ev` footlines carrying job id, trace id and start time.

The spinner is the only animation in the application. `@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}` is global and non-negotiable; under it the ring renders as a static broken circle, which is still a legible "working" mark.

### Form controls — `.input`, `.textarea`, `.select`, `.field`

Rendered by crispy-forms, restyled here.

```css
.input,.textarea,.select{width:100%;padding:7px 10px;border:1px solid var(--line);
  border-radius:4px;background:var(--surface);font-family:var(--sans);font-size:12.5px;color:var(--ink)}
.input.mono,.textarea.mono{font-family:var(--mono);font-size:12px}
.textarea{min-height:66px;resize:none}
```

`.field` is a `{spacing.1}`-gap column: a `{typography.body-sm}` `label` at weight 600, an optional `.req` marker in `{typography.mono-ev}` `--crit`, the control, an optional `{typography.meta}` `--muted` `.help`, and on failure an `.errmsg` in `{typography.meta}` `--crit`. These are ramp steps, not the mockup's 11.5px and 12px literals — the ramp exists to retire exactly those.

**The invalid state is `border-color: var(--crit)` *and* `background: var(--crit-wash)`** — border and fill together, never fill alone and never colour alone, because the `.errmsg` text is what carries the reason. Any field holding a machine value — a URL, a package name, an identifier — takes `.mono`.

Validation is server-side by doctrine. The invalid state is a bound form re-rendered by the server, and nothing client-side decides whether a value is acceptable. EXPERIENCE.md owns that contract.

### `.split` — the sidebar layout

`display:grid; grid-template-columns:236px minmax(0, 1fr); gap:{spacing.5}`. The `minmax(0, 1fr)` is load-bearing, not pedantry: a bare `1fr` has an automatic minimum of `min-content`, so an 11-column table would push the grid wider than its container instead of scrolling inside it — which is the one thing the horizontal-scroll rule forbids. The one two-column layout in the application, used by the health view for its facet sidebar. 236px is fixed, not fluid: facet labels and their counts have a known maximum width, and a fluid sidebar would reflow the table on every viewport change. Layout & Spacing states the width rule; this is the reason it holds.

### `.facet` — a filter row

A `<label>` wrapping a checkbox, its text, and a right-aligned count in `{typography.mono-value}`. Active facets take `{colors.accent}`. Counts are server-computed. The four sentinel states appear as first-class facets with their own counts — never folded into an "other" row, which would reintroduce the collapse the whole system exists to prevent.

### `.filterpill` — an applied filter

`{typography.mono-chip}` in `{colors.accent}` on `{colors.accent-wash}`, `{rounded.sm}`, with a trailing remove control. The remove control is a real `<button>` carrying an accessible name. The mockup used a bare `<x>` element, which is not focusable and announces nothing. Behaviour in EXPERIENCE.md.

### `.pager` — pagination

A left summary line and right-aligned 26px square page boxes; the current page takes `{colors.accent}` with `{colors.on-accent}` text. No prev/next arrows, no page-size selector, no infinite scroll — the page size and its ceiling are settings constants and are stated, not chosen, in the summary line.

### One focus ring, never restyled

```css
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}
```

Global, one ring, never removed and never restyled per component. The 2px offset is what keeps it visible against `--surface-2` chrome bands and inside dense table rows.

### Diagrams

Any diagram in this system is hand-authored inline SVG built on the same custom properties, so it re-themes with the page. No mermaid, no charting library, no rasterised image. Fills use `--surface-2` and the `*-wash` tokens; strokes use `color-mix` at 40–45%; text uses the `svg .t-*` scale (`.t-ttl` 12.5px/600, `.t-lbl` 11px mono `--muted`, `.t-sm` 10.5px `--ink-2`, `.t-xs` 9.5px mono `--muted`).

Three line semantics, and only three: **solid `--muted`** = primary flow, **solid `--accent`** = the emphasised path, **dashed `--muted`** = secondary or derived. Every SVG carries `role="img"` and a descriptive `aria-label`.

### What Bootstrap keeps, and what it loses

**Bootstrap 5.2.3 supplies:** the grid (`container`, `row`, `col-*`), spacing / display / flex / text utilities, the `base.html` navbar collapse behaviour, offcanvas, and the structural markup crispy-forms emits.

**Bootstrap is overridden, and its default appearance must not be expected, on:**

| Bootstrap | Replaced by | Why |
|---|---|---|
| `.badge` | `.chip` | Bootstrap badges are pill-shaped, markerless and carry no state geometry. The entire no-collapse doctrine lives in the marker. |
| `.table`, `.table-striped` | `.tbl` | Striping fights the `--surface-2` row hover and the `.ev` footlines; Bootstrap's `th` is neither mono nor uppercase; its middle vertical alignment breaks the footline. |
| `.modal` | `.modal` (ours) | Different radius, scrim opacity, header/footer bands and width. |
| `.btn`, `.btn-primary` | `.btn` (ours) | Bootstrap's blue, radius and padding are all wrong for a 13px shell. |
| `.card` | `.panel` | Bootstrap cards are rounded and shadowed; panels are square, flat, and tile against each other. |
| `.alert` | `.toast` / `.notebox` | Bootstrap alerts have no provenance rule and no room for `.ev` lines. |
| `.pagination` | `.pager` (whose page-number boxes are `.pagenums`) | 26px square boxes in mono at `{rounded.DEFAULT}`; no prev/next chevrons. |
| `.form-control` | `.input` / `.textarea` / `.select` | Sizing, radius and the invalid state all differ. Crispy-forms' emitted classes are restyled, not replaced. |

Colour is the sharp edge: **Bootstrap's `success` / `warning` / `danger` / `info` / `secondary` colour utilities are forbidden in application templates.** They carry a green–amber–red semantic with no sentinel states in it, which is precisely the collapse this system exists to prevent.

## Do's and Don'ts

| Do | Don't |
|---|---|
| Render every one of the five outcome states as itself — hue, marker, lowercase word, `.ev` footline | **Never render a status as a blank cell.** Blank is reserved for a field with no value (CPM-AD-24) and is never used for a status |
| Keep `--warn` for determinate amber only — lagging, medium, manual review, `p3`–`p4`, `inventory-derived` | **Never use `--warn` for stale.** Stale keeps its underlying status's hue and takes the amber hold mark and amber footline instead |
| Give sentinels hues off the determinate ramp — slate, blue, violet, burnt orange | **Never let a sentinel take `--ok`, `--warn` or `--crit`**, and never let a determinate value take a sentinel hue |
| Treat stale, `blocked`, `superseded` and `skipped` as properties or separate axes | **Never add a sixth outcome state.** `OutcomeState` is closed; the UI may not invent, collapse or re-label at the value level |
| Carry status on four channels — hue, marker shape, the word, the footline | **Never convey status by colour alone.** Greyscale printing and colour-vision deficiency must each leave the state fully readable |
| Set every machine value in `--mono` | **Never set a timestamp, identifier, version or count in Sans**, and never set guidance prose in Mono |
| Keep `--serif` in documentation | **Never put serif inside the application**, and never load Serif in `base.html` |
| Reference `var(--token)` for every colour | **Never hard-code a colour outside the three `:root` blocks.** After the `--on-accent` promotion, zero hex literals remain elsewhere — keep it that way |
| Use `.chip.plain` for non-outcome metadata only | **Never render an outcome state as `.plain`**, and never use `.plain` to imply that something is fine |
| Keep `.conf` text-only | **Never promote a package-identity confidence tag to a chip** — a confidence is not an outcome state |
| Show a `inventory-derived` row normally, with its label | **Never grey, dim, hide or downgrade a derived row.** The label annotates; it does not degrade the value |
| Put the freshness bar under every list, detail and report header | **Never treat provenance as progressive disclosure.** CPM-AD-11 makes it mandatory chrome on every view and export |
| Use the 3px left rule only for provenance or system speech, coloured to match the content | **Never use the 3px rule as generic emphasis**, and never colour it with a hue that contradicts the block |
| Express elevation with 1px borders and `--surface-2` fills | **Never shadow a panel, card or table.** `--shadow-md` belongs to the modal and the sign-in box only |
| Override Bootstrap's badge, table, modal, button, card, alert, pagination and form control | **Never use Bootstrap's `success` / `warning` / `danger` / `info` colour utilities** — that palette has no sentinels |
| Keep `vertical-align: top` on every `td` | **Never centre-align table cells** — the `.ev` footline needs somewhere to hang |
| Hold radii at 2 / 3 / 4 / 6, and reserve 50% for 8–24px circles | **Never make a surface pill-shaped**; a rounded chip reads as a Bootstrap badge |
| Track display headings negative and mono micro-labels positive | **Never track body text, table cells or chip labels** |
| Use the layout scale for containers and gaps | **Never round a control's internal padding onto the layout scale** — chip, cell, button and input metrics are optical and fixed |
| Ship plain CSS custom properties in `project.css` | **Never introduce a build step, an npm dependency, a preprocessor or a JS framework** |

### Numbers this document deliberately does not state

Each of the following is an open question in the sources:

- The p95 latency budget, and the inventory size it is measured at (PRD OQ 5).
- `PAGE_SIZE`.
- `CPM_SYNC_EXPORT_MAX_ROWS` (OQ 5), and with it the visible branch between a synchronous download and an async job.
- Per-collector freshness targets (OQ 7).
- The priority rule set, the score function, and the content of buckets P1–P10 (OQ 8).

This document specifies the **presentation** of each — the async toast, the pager, the stale overlay, the four priority bands — and asserts no value for any of them. An implementer who finds a number here that is not in a source has found a defect in this document.
