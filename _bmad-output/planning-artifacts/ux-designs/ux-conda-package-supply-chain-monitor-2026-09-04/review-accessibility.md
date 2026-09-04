---
title: Accessibility Floor Review — CPM UX Spine
project: conda-package-supply-chain-monitor
scope: CPM-EP-APP
reviewed: EXPERIENCE.md (behaviour spine) · DESIGN.md (visual spine)
against: .working/extract-mockups.md
date: 2026-09-04
verdict: strong floor, two blocking interaction defects, one systemic light-mode contrast token, two delegated obligations that neither document accepts
---

# Accessibility Floor Review

**Scope of this review.** Internal tool, three roles, behind OIDC. Reasonable floor, not a compliance audit. AAA is not demanded anywhere below. The **desktop-only floor is a recorded decision and is not re-litigated** — it is checked only for honesty and scoping, and one scoping correction is filed (M-7).

**Counts.** 2 critical · 7 high · 12 medium · 6 low · 21 explicit passes.

---

## Summary — what is actually wrong

The doctrinal core is sound and, in places, better than most commercial work: four redundant channels per status, the status word as real text, the marker as CSS so it cannot be mistaken for the semantic channel, the export carrying enum values verbatim. **All eight of the mockup's named gaps are addressed**; six are fully closed, two are partially closed. Nothing in either document conveys an outcome state by colour alone, and the greyscale claim survives inspection.

What fails is not the doctrine. It is three things:

1. **The async interaction model is a keyboard and screen-reader hazard.** A 3-second `outerHTML` self-swap on a live region containing a Cancel button is the single worst defect in either document. A second defect — focus after a queue-row swap — is specified twice, in two mutually impossible ways.
2. **One light-mode token, `--muted` `#63767e`, fails 4.5:1 on four of the five grounds it is used on.** It is the root cause of every text-contrast failure in the system. Dark mode is clean throughout.
3. **Two measurable AA obligations were delegated and never accepted.** EXPERIENCE.md:510 assigns contrast ratios *and target sizes* to DESIGN.md. DESIGN.md states no contrast requirement and never uses the words "target size" at all. Both fell through the seam, and the failures below live in that gap.

---

# CRITICAL

## C-1 · The job-poll toast destroys keyboard focus and re-announces itself every 3 seconds

**Files** EXPERIENCE.md:188, :281, :531 · DESIGN.md:753-757

Three rules combine into a defect none of them creates alone:

- EXPERIENCE.md:281 — `hx-get="/jobs/<id>/" hx-trigger="every 3s" hx-swap="outerHTML"`. **The toast replaces itself, whole, every 3 seconds.**
- EXPERIENCE.md:188 / :531 — the toast region is `aria-live="polite"` `aria-atomic="true"`.
- EXPERIENCE.md:270-277 — the toast contains **a Cancel control**, plus job id, trace id, queued time, started time and a duration estimate.

**The failure, twice over:**

*Keyboard.* Cancel is a real focusable control inside the element that is destroyed and recreated every 3 seconds. A keyboard user who tabs to Cancel has focus reset to `<body>` within at most 3 seconds, every time, for the whole life of the job. They cannot reliably reach or activate the only control the toast offers. On a long export this is unusable, not merely annoying.

*Screen reader.* `aria-atomic="true"` means the **entire** region is re-announced whenever any part of it changes. The region changes wholesale every 3 seconds, and it contains an elapsed/started time and a duration estimate that genuinely change. The result is the full toast — "Preparing your export, 1,091 rows exceeds the synchronous cap, job zero one J Q eight H two P, trace four c one f…" — read aloud every 3 seconds, indefinitely, with the polite queue never draining. This does not announce the job; it makes the rest of the page unreadable while the job runs.

The same shape recurs, less severely, at EXPERIENCE.md:468 — the home page's "top of my queue" partial polls `every 60s` and contains links. Focus inside it is destroyed once a minute.

**Who it affects** Keyboard-only users (blocked from Cancel). Screen-reader users (page rendered unusable during any async job). Switch and voice-control users (target disappears mid-interaction). This is every async operation in the product: recollection, export, collector run, policy pass.

**Fix**
- Split the toast. Poll into a **small inner status node** (`#job-<id>-status`) carrying only the state line and the elapsed time. Cancel, the job id, the trace id and the reason line live **outside** the swapped region and are never destroyed.
- Put `aria-live="polite"` on that inner node with **`aria-atomic="false"`**, and — because a 3-second tick is not news — emit the status line **only when the job's state actually changes** (running → running is an empty diff and must produce no text change). A ticking elapsed counter must be `aria-hidden="true"`.
- Alternatively: leave the region `aria-live="off"` for the duration of polling and switch it to `polite` only on the terminal fragment, which is the announcement that actually matters.
- Give the home-page 60s partial an `id`-stable wrapper and swap only its list body, or drop the poll (G-14 already accepts that job completion elsewhere announces nothing; the 60s poll buys little).

---

## C-2 · Focus after a queue-row swap is specified twice, in two impossible ways

**Files** EXPERIENCE.md:543, :189, :417, :534 · also :465

Three statements that cannot all hold:

- EXPERIENCE.md:543 — "**HTMX swaps must not move focus; after a row swap, focus stays where the user left it.**"
- EXPERIENCE.md:189 / :534 — the modal's focus is "trapped while open, Escape closes, **focus returns to the trigger**".
- EXPERIENCE.md:417 / :465 — "On success the server returns the re-rendered queue row and HTMX swaps it", `hx-target="#wf-row"`.

The trigger that opened the transition modal is a control **inside the queue row**. On success that row is replaced. So at the moment the modal closes and wants to restore focus, **the element it must restore focus to no longer exists**. And :543's claim that focus "stays where the user left it" is not a property that obtains by doing nothing — when a swap destroys the subtree containing `document.activeElement`, the browser resets focus to `<body>`. Focus preservation across a swap is a mechanism you build, not an outcome you assert.

This is the highest-value flow in the product — it is Dana's climax at EXPERIENCE.md:564 — and a keyboard user completing it lands at the top of the document with no announcement that anything happened.

**Who it affects** Keyboard-only and screen-reader users performing the product's primary write. It is also the flow where silent success is most dangerous, because the whole doctrine is that nothing reports success before the audit row lands.

**Fix** Replace :543's assertion with a mechanism, and state it per interaction:
- **Facet swap (#1)** and **search**: the focused element (a facet checkbox, the search input) is outside `#health-rows`. Focus genuinely survives. Keep :543's wording *for these two only*.
- **Evidence disclosure (#2)**: `hx-swap="afterend"` does not destroy the trigger. Focus survives. See M-1 for the missing disclosure semantics.
- **Queue transition (#3)**: give the re-rendered row a stable `id` and `tabindex="-1"`, and on `htmx:afterSwap` move focus to it. Announce the new state through a single named polite region (see H-7). Delete "focus returns to the trigger" for this path and say instead: *focus moves to the re-rendered row, which carries the new state and the audit timestamp as its first readable content.*
- **Job poll (#4)**: see C-1.
- Add the general rule: **any swap whose target contains or may contain the active element must name its focus destination.** A swap with no named destination is a defect.

---

# HIGH

## H-1 · No skip link and no landmark structure — a Level A failure inside an AA floor

**Files** EXPERIENCE.md:506-546 (the whole Accessibility Floor), :522 · DESIGN.md:776-782

Neither document contains the words `main`, `nav`, `aside`, "landmark", "skip link" or "bypass" anywhere. EXPERIENCE.md:522 credits the mockup with "Semantic elements throughout" but never names a single landmark, and the Additional floor at :539-546 does not mention structure at all.

This matters more here than in an average app because of the layout the documents actually specify. DESIGN.md:776 fixes a **236px facet sidebar** ahead of the table in source order, and EXPERIENCE.md:183 / extract-mockups.md:161 put **six facet groups** in it — Search, vulnerability status (6 values), package-identity confidence (3), priority bucket (up to 10), work type (8), evidence freshness. That is on the order of **30+ checkboxes plus the search field before the first table row**, on the flagship screen, on every load, plus the persistent top nav above it.

**WCAG 2.4.1 Bypass Blocks is Level A.** A floor that declares 2.2 AA (EXPERIENCE.md:510) fails a Level A criterion here.

**Who it affects** Keyboard-only users most acutely (30+ tab stops to reach content, on the screen they use most). Screen-reader users lose landmark navigation (`D` in NVDA, rotor in VoiceOver) — the single fastest way through a dense page.

**Fix** Add to the Additional floor:
- A visible-on-focus skip link as the first focusable element of `base.html`: `<a class="skip" href="#main">Skip to content</a>`.
- Landmarks named explicitly: `<nav aria-label="Primary">` for the top nav, `<main id="main" tabindex="-1">` for the content area, `<aside aria-label="Filters">` for the facet sidebar, `<footer>` where one exists.
- On the health view specifically, a second skip link — **"Skip filters to results"** targeting `#health-rows` — because the facet sidebar is the block being bypassed and it is 30 stops deep.
- The facet sidebar's group headings become real headings (`<h2>`) so heading navigation works within it; see M-3.

---

## H-2 · Light-mode `--muted` `#63767e` fails 4.5:1 on four of the five grounds it is used on

**File** DESIGN.md:414 (the token's stated role), :356 (the token), and every consumer listed below

DESIGN.md:414 — "**`--muted` is the default colour of every `.ev` footline and every mono micro-label.**" That is the most-repeated text in the product: a footline hangs under *every* value (EXPERIENCE.md:326, :338), and every table header, eyebrow and freshbar label is a mono micro-label.

**Computed ratios, `#63767e` against every ground it lands on:**

| Ground | Hex | Ratio | Verdict | Where DESIGN.md puts it |
|---|---|---|---|---|
| `--surface` | `#ffffff` | **4.75** | pass (0.25 margin) | `.ev` in an unhovered table cell; `.kv dt` (:728); `.stat` foot line (:732) |
| `--surface-2` | `#f4f7f8` | **4.41** | **FAIL** | `th` mono-th (:713) · `.freshbar .lbl` (:679) · `.toast` 11.5px line and its `.ev` footlines (:755) · `.panel` header right-slot metadata (:726) · **every `.ev` footline in a hovered row** (:715) · facet sidebar micro-labels (:776) · SVG `.t-lbl`/`.t-xs` on wash fills (:806) |
| `--surface-3` | `#eaeff1` | **4.10** | **FAIL** | `.pbucket` `p8`–`p10` band (:703) |
| `--paper` | `#e9edef` | **4.03** | **FAIL** where used | app ground |
| `--accent-wash` | `#dfedf1` | **3.96** | **FAIL — worst in the system** | `.ev` footlines on a **selected row** (:718) and on the **evidence-disclosure ground** (:722) |

Arithmetic shown for the worst case (`--muted` on `--accent-wash`), sRGB relative luminance per WCAG 2.x:

```
--muted  #63767e = rgb(99, 118, 126)
  linearised   R 0.12477   G 0.18116   B 0.20864
  L = 0.2126(0.12477) + 0.7152(0.18116) + 0.0722(0.20864) = 0.17116

--accent-wash  #dfedf1 = rgb(223, 237, 241)
  linearised   R 0.73791   G 0.84687   B 0.87962
  L = 0.2126(0.73791) + 0.7152(0.84687) + 0.0722(0.87962) = 0.82607

ratio = (0.82607 + 0.05) / (0.17116 + 0.05)
      =  0.87607 / 0.22116
      =  3.96 : 1
```

Required 4.5:1. **Shortfall 12%.** The other three failing grounds by the same method: `--surface-2` **4.41**, `--surface-3` **4.10**, `--paper` **4.03**.

None of these is large text. `mono-ev` is 10px, `mono-eyebrow` is 9.5px, `mono-th` is 10px, `.pbucket` is 12px/600 — bold large text starts at 18.66px. **All require 4.5:1.**

Two aggravating specifics:

- **The hover case is total.** DESIGN.md:715 sets `tr:hover td{background:--surface-2}`. Every `.ev` footline in the table drops from 4.75 to **4.41** whenever the pointer is over its row. WCAG applies to hover states.
- **The evidence disclosure is the deepest provenance layer and has the worst ratio.** DESIGN.md:722 grounds it on `--accent-wash`; footlines there read at **3.96:1**.

**Dark mode passes everywhere.** `--muted` `#8ba1a8`: 6.41 on surface, 5.94 on surface-2, 5.33 on surface-3, 6.99 on paper, 5.15 on accent-wash. No change needed.

**Who it affects** Low-vision users, users with age-related contrast loss, anyone on a glare-affected or low-quality display — reading the provenance footline, which is the one thing this product insists must always be readable.

**Fix — one token change closes every failure above.** Darken light `--muted` from `#63767e` to **`#556670`**:

| Ground | `#63767e` (current) | `#556670` (proposed) |
|---|---|---|
| `--surface` | 4.75 | **5.96** |
| `--surface-2` | 4.41 ✗ | **5.54** |
| `--surface-3` | 4.10 ✗ | **5.15** |
| `--paper` | 4.03 ✗ | **5.06** |
| `--accent-wash` | 3.96 ✗ | **4.98** |

`#556670` preserves the hue and the position in the ink ladder (`--ink` 18.18 › `--ink-2` 10.02 › `--muted` 5.96 on surface) and leaves real headroom on the worst ground. `#5a6d75` also clears (4.52 on accent-wash) but with only 0.5% margin and it collides with `--unk`; `#516168` (5.38 on accent-wash) is the conservative choice if more headroom is wanted. **Do not fix this per-consumer** — the token is the defect.

---

## H-3 · Target size (WCAG 2.2 AA, 2.5.8) is delegated and then never mentioned; two controls fail it

**Files** EXPERIENCE.md:510 (the delegation) · DESIGN.md:784-786, :360 (the controls) · DESIGN.md throughout (the omission)

EXPERIENCE.md:510 — "Contrast ratios and **target sizes** are `DESIGN.md`'s to hit". DESIGN.md never uses the phrase, states no minimum, and specifies no control's total interactive box. The obligation was handed over and not accepted.

The floor is declared **WCAG 2.2** AA at EXPERIENCE.md:510, which brings **2.5.8 Target Size (Minimum) — 24 × 24 CSS px** into scope. Measured against the specified metrics:

| Control | Spec | Computed box | 2.5.8 |
|---|---|---|---|
| `.pager` page box | DESIGN.md:788 — "26px square" | 26 × 26 | **pass** |
| `.btn` | :738 — 12.5px/1.5 + `6px 12px` | ≈ 31px tall | **pass** |
| `.btn.sm` | :743 — 11.5px + `4px 9px` | ≈ 25px tall | pass, no margin |
| **`.filterpill` remove button** | :786 — `mono-chip` 11px, pill padding `2px 8px` | pill itself ≈ **20px tall**; the ✕ inside it is smaller still, ~12 × 12 | **FAIL** |
| **`evidence ▾` disclosure** | EXPERIENCE.md:360; no metric anywhere | inline control in a `9px 11px` cell at ≈ 11px type | **FAIL (unmeasurable — unspecified)** |
| Row / select-all checkbox | EXPERIENCE.md:413, :419; no metric | native default ≈ 13 × 13 | **FAIL** unless the spacing exception is claimed |

The undersized-target exception (a 24px circle centred on the target intersecting no other target's circle) **cannot be claimed for the filter pills**, because applied pills sit adjacent in a single row (DESIGN.md:784, EXPERIENCE.md:184) and each carries its own remove button.

The irony is sharp: the filter-pill remove control is the **one gap EXPERIENCE.md:533 singles out as "the weakest control in the file"** and fixes for semantics — turning `<x>✕</x>` into a real `<button>` with a full accessible name. That fix is correct and lands (see G-4 below). But the same control is then left at roughly 12 × 12 px, so it remains the weakest control in the file for a different reason.

**Who it affects** Motor-impaired users, tremor, touch and stylus users, anyone on a trackpad at speed. Also low-vision users, who overshoot small targets more often.

**Fix**
- Add a **Target size** subsection to DESIGN.md Components: *every interactive control presents at least a 24 × 24 CSS px hit area; where the visible mark is smaller, the hit area is enlarged with padding or a transparent `::after` overlay, not by growing the mark.*
- `.filterpill` remove: keep the 11px glyph, give the button `padding` and `min-width:24px; min-height:24px`, and raise the pill's own height to ≥ 24px. This costs one row of vertical space in the applied-filter bar and nothing else.
- `evidence ▾`: specify it in DESIGN.md as a `.btn.sm`-class control with an enforced 24px minimum box.
- Checkboxes: `width:18px; height:18px` on the input with a `24px` labelled hit area, or wrap in a `<label>` with 24px padding (the facet checkboxes already have wrapping labels — extend the pattern to the table).

---

## H-4 · Stale does not survive the export — the four channels collapse to one, and that one does not carry stale

**Files** EXPERIENCE.md:439-445 (export contract), :227-231 (stale), :442 · DESIGN.md:638-660

The export is the artifact both documents identify as the highest-risk collapse point. EXPERIENCE.md:442 is explicit and correct about the five states: "A status crosses into the export as its `OutcomeState` value, verbatim, lowercase. This rule exists to prevent exactly one failure: the export rendering `unknown` as a blank cell." **That half is airtight.**

Stale is not covered by it, and cannot be, because of the design's own rules:

- Stale's three carriers (DESIGN.md:640-660) are a **CSS `::after` mark**, an **amber `.ev` footline**, and a **visually-hidden span**. None of the three exists in a CSV.
- EXPERIENCE.md:161 — L2 forbids `critical · stale` as a chip label. Correct on screen; it also means **the exported value is the bare word `critical`**, identical for a fresh and a stale finding.
- EXPERIENCE.md:445 says "The export carries the same freshness and package-identity-confidence columns the application shows, and the **freshness bar's contents** ride in the export header." The freshness bar is **page-level** provenance (`computed_at`, cut-off, policy versions — :342-356). It is not per-row staleness. The export heading list at :441 contains no staleness column and no per-value `observed_at` column.

**The consequence, stated in the product's own terms:** a stale clean determinate result exports as `clean`, indistinguishable from a fresh one. EXPERIENCE.md:231 asserts "**CPM-FR-38: stale never displays as clean**". In the export, as specified, it does. That is CPM-SM-C1 arriving through the back door, in the one artifact that leaves the system and gets pasted into a review deck.

This is also the sharpest counterexample to DESIGN.md:621 — "Remove any one channel and the other three still separate the states." The export removes three of four. For the five outcome states that is survivable because the fourth channel is the value itself. For stale it is not, because stale was deliberately kept *out* of the value.

**Who it affects** Everyone downstream of an export — including Sam's monthly review deck (EXPERIENCE.md:598-599), which is the flow the documents use to argue the export is safe.

**Fix** Add to the export contract at EXPERIENCE.md:439-445, as a required column pair, not an optional one:
- **`<domain>_observed_at`** — the per-value observation timestamp behind that status (this is CPM-FR-37 applied to the export, and it is the same value the on-screen footline carries).
- **`<domain>_stale`** — `true` / `false`, from the same boolean the UI computes, alongside the freshness target it was evaluated against.
- State the rule in the same voice as the existing one: *staleness is a property of a status and travels with it into every artifact. An export column that carries a status without its staleness re-creates the collapse the on-screen chip prevents.*
- Whichever shape is chosen, DESIGN.md:660's "Three channels carry staleness" needs a fourth clause naming what carries it off-screen — otherwise the sentence is true of the screen and false of the product.

---

## H-5 · The stale announcement has no owner, and "critical stale" is the wrong string

**Files** DESIGN.md:658 (delegates) · EXPERIENCE.md:506-546 (never receives it)

DESIGN.md:658 — "A visually-hidden span carries `stale` so assistive technology announces 'critical stale'. **Markup and announcement details belong to EXPERIENCE.md.**"

EXPERIENCE.md's Accessibility Floor (:506-546) **does not contain the word "stale" at all**. Nor does the chip's behavioural row at :176, which enumerates "four redundant channels" and stops there. Nor does the `{% status_chip %}` inclusion-tag spec at :486, which is the one place the chip's markup is defined and the only place a visually-hidden span could be made structurally unavoidable. Searched: `visually hidden` / `visually-hidden` / `sr-only` appears **exactly once in both documents**, at DESIGN.md:658 — in the sentence that hands the problem away.

So the single accessible carrier of staleness — the property the product uses to stop a stale finding reading as actionable — exists in one clause of the visual spine, is explicitly assigned to the behaviour spine, and the behaviour spine is silent. It will not be built.

**Secondly, "critical stale" is not the right announcement even if it is built.** Two adjacent bare words with no punctuation are read as a single compound by every major screen reader: *"critical stale"* parses as a severity name, not as "critical, and the evidence is stale". It is also actively confusable with the value set the product is defending — a listener who hears "critical stale" has no way to know that `critical` is the enum member and `stale` is an overlay, which is exactly the collapse the visible design works so hard to prevent.

There is also a **double-announcement**: the hidden span says `stale`, and the amber footline directly below (DESIGN.md:656, EXPERIENCE.md:227) is real text that also says `stale, target 24h`. A screen-reader user reading the cell linearly hears "stale" twice.

**Who it affects** Screen-reader users on every stale finding — and specifically on Dana's pivotal edge case (EXPERIENCE.md:566), where staleness is what removes the Route action. A user who does not perceive staleness sees a `critical` finding whose primary button inexplicably says "Recollect evidence" instead of "Route", with no stated reason.

**Fix** Move the specification into EXPERIENCE.md, into the `{% status_chip %}` contract at :486 so it is inseparable like the other four channels:
- The tag emits, when `stale` is true, a visually-hidden span whose text is a **sentence fragment with punctuation and cause**, not a bare word: `", evidence stale"` — yielding "critical, evidence stale". The target and elapsed time stay in the footline, which already reads them out.
- Drop the duplicate: either the hidden span carries the qualifier and the footline is `aria-hidden`, or (better, since the footline is real text with real content) the hidden span stays minimal at `", evidence stale"` and the footline continues as-is. Both announcing the bare token `stale` is the case to avoid.
- Add the corresponding row to the Accessibility Floor's "Additional floor" list at :539, so the property is discoverable where a reviewer looks for it.
- Same treatment for the **readiness axis**, which EXPERIENCE.md:229 says also carries stale — and which renders through `{components.chip.plain}`, a **markerless** chip. On a plain chip the stale `::after` mark is the *only* visual carrier; the hidden text is the only accessible one. It needs the same tag-level guarantee.

**Assessed, per the brief, for each user:**
- *Sighted screen-reader user* — gets the meaning only via the hidden span (unbuilt) and the footline text (built, and sufficient on its own). Passes today by accident, through the footline. Make it deliberate.
- *Colour-blind user* — passes. The stale mark is distinguished by **shape** (two rectilinear bars) and **position** (right, where all markers are left), not by hue; DESIGN.md:652 argues this correctly. Contrast of the mark against every chip wash is 5.14–5.44 in light and 6.72–7.81 in dark, all clear of the 3:1 non-text floor. Plus the footline says "stale" in words. **Three independent non-colour carriers. Genuine pass.** One exception — see M-2.
- *Magnification user* — passes on the mark itself (6 × 8px at 200% is 12 × 16px, legible). Inherits the recorded Reflow shortfall, correctly scoped at M-7.

---

## H-6 · Server-rendered validation: association is specified, delivery is not

**Files** EXPERIENCE.md:190, :476, :535, :604 · DESIGN.md:759-774

What is specified, and correct: `aria-describedby` from the field to the error element, `aria-invalid="true"` on the field, both wired by crispy-forms at the template-pack level rather than per template (EXPERIENCE.md:535), and reinforced concretely in Sam's flow at :604. Contrast on the error text and the invalid fill both pass (see the pass list). **That closes the mockup's `.errmsg` gap properly.**

What is missing is everything that happens *at the moment of failure*. EXPERIENCE.md:476 — "An invalid submission returns the **bound form**, re-rendered by the server through crispy-forms, **swapped into the modal body**." Neither document says:

- **Where focus goes.** The submit button is in the modal *footer* (DESIGN.md:749), outside the swapped body, so it survives — meaning focus stays on Submit and the user is never taken to the error. A screen-reader user presses Submit and, from their perspective, **nothing happens**: no focus change, no announcement, and the error text is somewhere above them in a region they did not navigate to.
- **What is announced.** The modal body is not a live region, and EXPERIENCE.md:542 explicitly forbids making one ("The toast is the only other live region. There are no others.") — see H-7.
- **Whether the error is summarised.** With one field this is survivable; the identity-override modal (EXPERIENCE.md:603) has at least three (`source_repository_url`, release ecosystem, reason), so multiple simultaneous errors are possible with no summary and no order.
- **The concurrent-advance refusal** (EXPERIENCE.md:568) takes the same path — the bound form re-renders stating "this item is now `routed`; it was `triaged` when this page loaded". That is excellent copy delivered silently.

**Who it affects** Screen-reader users on both of the product's two write paths — a workflow transition and a package-identity override. Those are the only writes in v1, so this is 100% of the write surface.

**Fix**
- On an invalid response, move focus to a `tabindex="-1"` **error summary** at the top of the modal body: a heading-level line stating the count ("2 problems with this override") and a list of links to each invalid field. This announces on focus without needing a live region, which sidesteps H-7 entirely.
- With exactly one error and no summary, move focus to the invalid field itself; its `aria-describedby` then reads the message on arrival.
- State the same for the refusal case, whose message is not field-scoped: the summary line carries the state-mismatch sentence.
- Specify `required` / `aria-required` explicitly alongside the visible `.req` marker (DESIGN.md:770). Crispy-forms emits `required` by default, but the marker itself is a 10px `--crit` glyph — colour plus glyph, no text — and required-ness must not rest on it.

---

## H-7 · "The toast is the only other live region. There are no others." — a rule that forbids its own fixes

**File** EXPERIENCE.md:542

The intent behind the sentence is right, and the reasoning given for it is right: "a page that announces constantly announces nothing." Live regions should be enumerated, not sprinkled.

But as written it is an absolute cap of **two**, and it blocks every announcement the rest of this review shows is needed:

- the error/refusal announcement in the modal (H-6),
- the new state after a queue-row transition (C-2),
- **bulk-action partial failure** — EXPERIENCE.md:419 and G-12 both require reporting "per item which succeeded and which were refused, and why", a result that arrives by swap and, under this rule, cannot be announced,
- row-selection count and the appearance of bulk verbs (M-5),
- zero-results under a filter (E3, :300) — the count region covers this, but only because it happens to be the one permitted region.

It also mis-states what is already there: the health-view **result count** is a live region (:253, :542) and the toast is a live region — but so, implicitly, is anything HTMX swaps that the user needs to know about. The rule as phrased will be read literally by an implementer and will cause the omissions above.

**Who it affects** Screen-reader users, across the modal error path, the transition path, and the bulk path.

**Fix** Replace the cap with an enumeration, keeping the discipline and losing the prohibition:

> **Live regions are enumerated, never ad hoc.** The complete list is: (1) the health-view result count, `polite`, updated only when the count changes; (2) the job status line, `polite`, `aria-atomic="false"`, updated only on a state change; (3) a single **page status region**, `polite`, into which the server writes one sentence after a transition, a bulk action, or a refusal. Any surface wanting a fourth must justify it against this list. Everything else announces through focus movement, not through a live region.

Three regions, one of which is a shared channel. The C-2 and H-6 fixes prefer focus movement anyway, so region (3) carries only what focus cannot.

---

# MEDIUM

## M-1 · The `evidence ▾` disclosure has no disclosure semantics

**Files** EXPERIENCE.md:360-365, :495 · DESIGN.md:745

`evidence ▾` is a disclosure widget — it expands and collapses a nested evidence table, multiple may be open at once (:365), and Alpine tracks which. Neither document specifies **`aria-expanded`**, **`aria-controls`**, or what element type it is. The `▾` glyph is the only state indicator, and it is a text character with no programmatic meaning.

Compounding it: the inserted row arrives via `hx-swap="afterend"` and is **not announced**. A screen-reader user activates the control, hears nothing, and must guess that content appeared below.

**Who it affects** Screen-reader users on package detail — Layer 3 of the four provenance layers, the deepest evidence the product offers.

**Fix** `<button type="button" aria-expanded="false" aria-controls="ev-<domain>-<pkg>">`, toggled to `true` on open (Alpine owns this; it is view state, exactly as :475 permits). Because the trigger survives the swap, no live region is needed: the newly inserted `<tr>` gets `tabindex="-1"` and an optional focus move, or the `aria-expanded` change alone suffices, since AT announces "expanded" on toggle. Its `<caption>` (already required at :541) then names the domain and package on arrival.

## M-2 · The amber stale mark is invisible *as amber* on a `warn` chip

**File** DESIGN.md:652

DESIGN.md:652 lists four properties that make the stale mark unmistakable: "It is rectilinear where all four sentinel markers are round or triangular; it sits on the right where they sit on the left; **it is `--warn` where they are `currentColor`**; and at 6×8px it resolves cleanly."

The third property is **false for exactly one chip**: a stale determinate-amber status (`lagging`, `medium`, `manual review` — the values :434 assigns to `--warn`). There, `currentColor` *is* `--warn`, so the chip's leading dot, its label and its trailing stale mark are all `#855505` on `#f7ecd8`. The hue distinction the sentence claims does not exist.

This is not a contrast failure — the mark reads at **5.44:1** on `--warn-wash`, well clear. Shape and position still separate it. But the document's own argument for why the mark cannot be confused rests partly on a property it does not always have, and `lagging` is a status that genuinely goes stale.

**Who it affects** Nobody severely — shape and position carry it. This is a correctness fix to the specification's reasoning, filed because the brief asks for claims that are not true.

**Fix** Amend :652 to: "it is `--warn` where the sentinels are `currentColor` — and on a determinate-amber chip, where those coincide, **shape and position alone carry it**, which they do: two rectilinear bars on the right against a round dot on the left." Optionally add a 1px `--surface` gap or a hairline separator before the `::after` on `.chip.warn.is-stale` so the two amber marks cannot visually merge at 11px.

## M-3 · The heading policy is incomplete and inverts visual weight

**Files** EXPERIENCE.md:530 · DESIGN.md:464-482, :496

EXPERIENCE.md:530 closes the mockup's gap correctly for the main case: exactly one `<h1>`, panel headers `<h2>`, nested evidence captions `<h3>`, no level skipped. Three problems remain:

1. **Unassigned headings.** The **modal header** is `aria-labelledby`-referenced (:534) but has no level; DESIGN.md:469 gives it `dialog-title` at 14.5px. The **facet sidebar group headings** (DESIGN.md:479, "sidebar group headings" in `mono-eyebrow`) have no level — and H-1 needs them to be headings for in-sidebar navigation. The **freshbar** and **stat** eyebrow labels likewise.
2. **DESIGN.md:496 implies `h4` exists** — `text-wrap: balance` is applied to "`h1`–`h4`" — while EXPERIENCE.md:530 assigns only h1/h2/h3. One of the two is wrong.
3. **Level and visual weight invert.** `page-title` (`<h1>`) is 20px; `panel-title` (`<h2>`) is **12.5px**, which is *smaller than the 13px body text* it introduces. A sighted user cannot see the heading structure that a screen-reader user navigates by. That is not a WCAG failure, but it means the two audiences are reading different documents.

**Who it affects** Screen-reader users navigating by heading (the fastest way through an 11-column page); sighted users scanning for structure.

**Fix** Complete the table at :530: modal header is `<h2>` **within the dialog** (a dialog restarts its own outline); sidebar group headings are `<h2>` inside `<aside>`; stat and freshbar eyebrows are **not headings** — they are `<dt>`/label text and should be marked as such, not as `<h*>`. Resolve DESIGN.md:496 to `h1`–`h3`. And raise `panel-title` to at least 13px/600, or accept the inversion explicitly in writing.

## M-4 · The main tables have no accessible name, and an 11-column row with footlines is very long

**Files** EXPERIENCE.md:541, :413 · DESIGN.md:709-722 · extract-mockups.md:159

`<caption>` is required only on **nested evidence tables** (EXPERIENCE.md:541). The **health table (11 columns)**, the **remediation queue (9 columns)**, the **audit table** and the **collector-health table** get none, so none has an accessible name. A screen-reader user listing tables on the page hears "table" repeated.

Separately, the density has a real cost nothing addresses. The health table is `Package · P · Score · Work · Currency · Vulnerability · KEV · Licence · Py 3.14 · Feedstock · Pkg identity confidence`, and DESIGN.md:714 puts `.ev` footlines under values with `vertical-align: top`. A row read cell-by-cell in table-navigation mode produces roughly **11 × (status word + an 6–10 word footline) ≈ 100+ words**. That is the honest price of Layer 1 provenance, and it should be paid deliberately rather than discovered.

There is a concrete, fixable aggravator: the `.ev` grammar is `<source> · <observed_at> [· <qualifier>]` (EXPERIENCE.md:329), and `·` (U+00B7) is announced inconsistently — NVDA and VoiceOver usually skip it entirely at default punctuation levels. The footline then reads as `vulnerability_findings 2026 08 29 stale target 24h` with no pauses, and the fixed grammar the document is proud of collapses into a word stream. The same `·` is used in the freshbar and in the audit line.

**Who it affects** Screen-reader users, on every list surface in the product.

**Fix**
- Extend :541: **every** `<table>` carries a `<caption>` (or `aria-label`) naming what it lists and its scope — "Package health, 1,204 of 9,842 packages, filtered".
- Replace `·` in the `.ev` grammar with a **comma plus space** in the DOM, and render the middle dot visually via `::before`/`::after` on the separator spans, or wrap each `·` in `<span aria-hidden="true">`. The visual grammar is unchanged; the spoken grammar gains its pauses.
- State the row-length cost in the Accessibility Floor as an accepted consequence, with the mitigation that column headers are short (`mono-th`, already true) and `scope="col"` is correct (already required) so column-by-column navigation works.

## M-5 · Row selection and the appearance of bulk verbs are unannounced

**Files** EXPERIENCE.md:419, :542

"Selected rows tint; the count and the available bulk verbs **appear in the header button row**" (:419). Checking the first checkbox therefore causes **new controls to materialise elsewhere on the page**. Nothing announces this, and :542 forbids a live region for it (H-7).

The checkbox state itself is native and announces correctly, and the select-all's accessible name is specified and good (:536). The gap is the consequence, not the control.

**Who it affects** Screen-reader users doing bulk work in the remediation queue.

**Fix** Write the running count into the page status region from H-7 ("3 rows selected on this page"), debounced. Give the header button row `aria-live="polite"` **or** — cleaner, and no region needed — render the bulk verbs as permanently present but `disabled` until a row is selected, so nothing appears or disappears and the disabled state carries the meaning natively.

## M-6 · WCAG 1.4.12 Text Spacing is unaddressed, and the specified `nowrap` rules are its exact failure mode

**Files** DESIGN.md:607 (`.chip{white-space:nowrap}`), :666 (`.ev{white-space:nowrap}`), :673, :713 (`th … white-space: nowrap`), :720 · EXPERIENCE.md:506-546 (omission)

1.4.12 (AA) requires no loss of content or function when the user forces line-height 1.5×, paragraph spacing 2×, letter-spacing 0.12em and word-spacing 0.16em. Neither document mentions it — and the design leans on precisely the properties it perturbs: a 13px shell, `9px 11px` cells, chip padding tuned to `2px 8px 2px 7px`, `mono-th` at 10px with `+0.09em` tracking already applied, and **`white-space: nowrap` on the chip, on table-level `.ev` footlines and on `th`**.

Under a 0.12em letter-spacing override, an 11px `nowrap` chip grows ~12% wider with no ability to wrap, and a `nowrap` footline in a table cell grows without wrapping in a column that is already dense. The likely result is clipping or overlap in the 11-column table — a 1.4.12 failure.

This is genuinely mitigable, unlike the Reflow shortfall, so it should not be filed alongside it as accepted.

**Who it affects** Dyslexic users and low-vision users who apply text-spacing overrides (a common, well-supported adaptation).

**Fix** Add to the Accessibility Floor: *containers use `min-height`, never fixed `height`; no text container clips overflow; chips and footlines may wrap under a user text-spacing override.* Concretely, change `.ev`'s table-level `nowrap` (DESIGN.md:673) to `overflow-wrap: anywhere` with the visual single-line preference expressed by column width rather than by `nowrap`, and verify the 11-column table under the standard 1.4.12 bookmarklet. `.chip`'s `nowrap` can stay — a chip label is one to two words — provided its container does not clip.

## M-7 · The Reflow shortfall is honestly recorded but under-scoped

**Files** EXPERIENCE.md:546 · DESIGN.md:536-542

**The decision itself is not in question and is not re-litigated here.** The recording is genuinely good practice: G-6 (:623) marks it RESOLVED with a rationale, DESIGN.md:540-542 states the cost rather than hiding it, and EXPERIENCE.md:546 says in terms that "adopting this spine is not mistaken for meeting AA in full". That is exactly how a scoped shortfall should be written down. **Pass on honesty.**

The **scoping** is wrong in two ways:

1. **The zoom level cited understates it.** EXPERIENCE.md:546 and DESIGN.md:542 both frame the failure as "200% zoom produces horizontal scrolling". 1.4.10 Reflow is specified at a **320 CSS px** equivalent width — 400% zoom on a 1280px viewport, not 200%. A screen pinned to a 920–1180px minimum fails 1.4.10 far more comprehensively than "at 200%" conveys: on a 1280px display it begins failing at roughly 110–140% zoom and is unusable well before 400%. A reader of the record will under-estimate the remediation.
2. **1.4.4 Resize Text is conflated with it.** The two are separate AA criteria. 1.4.4 (text to 200% without loss) is probably **satisfied** here — the layout is pinned, the text is not, and the container scrolls rather than clipping. Saying "200% zoom" in a Reflow record invites the reader to think 1.4.4 is also failing when it is not, and to think Reflow is only a 200% problem when it is not.

**Who it affects** Nobody differently — the behaviour is unchanged. This affects whoever later picks up the named gap and scopes the work.

**Fix** Amend both records to: *"App screens assume a ≥960px viewport. **WCAG 2.2 AA 1.4.10 Reflow (320 CSS px, ≈400% zoom on a 1280px display) is not met**, and horizontal scrolling begins well below that. 1.4.4 Resize Text is believed to be met, since text scales and containers scroll rather than clip — verify before relying on it. Accepted for v1 as a desktop-only internal tool (G-6)."* Nothing else about the decision changes.

## M-8 · "Superseded rows render dimmed" — the dim is unspecified, and the mockup's value fails

**Files** EXPERIENCE.md:363 · DESIGN.md (silent) · extract-mockups.md:136

EXPERIENCE.md:363 — "Superseded rows are shown, not deleted. **They render dimmed** and carry a `superseded` `{components.chip.plain}`." DESIGN.md, which owns every visual value, specifies **no superseded treatment at all** — no opacity, no colour, nothing. So the implementer inherits the mockup's `opacity:.62` (extract-mockups.md:136).

`--ink-2` `#33454c` at 62% over `--surface` `#ffffff` composites to `#818c90` → **3.45:1**. Fails 4.5:1. And these rows live in the evidence disclosure, whose ground is `--accent-wash` `#dfedf1` (DESIGN.md:722), where it is worse still.

Dark mode composites to `#768488` → 4.48:1, also a fail, by a hair.

`opacity` is the wrong instrument here regardless: it dims the `superseded` chip along with everything else, including the chip's marker and border.

**Who it affects** Low-vision users reading evidence history — the "show all N observations" path (:364) that makes history reachable rather than merely preserved.

**Fix** Specify it in DESIGN.md Components. Do not use `opacity`. Set the superseded row's **text** to `--muted` (post-H-2: `#556670`, giving 4.98:1 on `--accent-wash`) and leave the `superseded` `.plain` chip at full strength — the chip is the semantic carrier and must not be dimmed. The row then reads as secondary without any text dropping below the floor.

## M-9 · `.pbucket` `p8`–`p10` — `--muted` on `--surface-3` at 4.10:1

**File** DESIGN.md:703

`#63767e` on `#eaeff1` = **4.10:1**, at 12px weight 600 mono — not large text (bold large starts at 18.66px). Fails 4.5:1.

Listed separately from H-2 because the fix differs if `--muted` is not changed globally: the other three bands pair a hue with its own wash (crit/crit-wash 6.55, warn/warn-wash 5.44, accent/accent-wash 6.27, all passing), while the fourth pairs the *text* token with a *surface* token. **Who it affects:** low-vision users reading priority in every queue and list.

**Fix** Adopting `#556670` from H-2 takes it to **5.15:1** and needs nothing else. If `--muted` is left alone, use `--ink-2` for the `p8`–`p10` band (8.64:1) — deprioritised is communicated by the neutral ground, not by dim text.

## M-10 · No `aria-busy` during a facet swap, and the stale table stays interactive

**File** EXPERIENCE.md:253

"HTMX `hx-indicator` on the table region only… **No skeleton rows — the previous table stays until the new one arrives.**" The retention decision is right — it avoids the layout thrash and the empty-then-full announcement. But during the request the visible table is about to become wrong, and it remains fully focusable and clickable. A keyboard user can tab into and activate a row link that is about to be replaced; a screen-reader user can read rows that no longer match the filters they just changed. The `hx-indicator` is a visual signal only.

**Who it affects** Keyboard and screen-reader users on the flagship screen.

**Fix** Set `aria-busy="true"` on `#health-rows` for the duration of the request (`htmx:beforeRequest` → `htmx:afterSwap`), which suppresses AT reading of a region in flux, and pair it with the existing visual `hx-indicator`.

## M-11 · No `aria-current` on the active nav item

**Files** EXPERIENCE.md:73-91 · DESIGN.md:578, :408

The active top-nav item is marked by `--accent` text plus a 2px `--accent` bottom border (DESIGN.md:578 — "the only place a border carries selection"). Visually this is fine and passes 1.4.1, since the border is a non-colour visual means. Programmatically the current page is not exposed at all.

**Who it affects** Screen-reader users, who lose "where am I" in a four-item nav — mild, but free to fix.

**Fix** `aria-current="page"` on the active entry. The `NAVIGATION_REGISTRY` renders the nav from data (EXPERIENCE.md:55), so this is one change in one renderer, not per-template.

## M-12 · Debounced search re-announces the result count on every pause

**Files** EXPERIENCE.md:463, :253

Search fires on `hx-trigger="keyup changed delay:300ms"` and swaps `#health-rows`; the result count is `aria-live="polite"`. Typing `pyarrow` with any hesitation produces a swap — and an announcement — per pause. Polite announcements queue rather than interrupt, so a user typing steadily can end up hearing a backlog of stale counts after they stop.

**Who it affects** Screen-reader users searching the health view.

**Fix** Lengthen the debounce for the announcement specifically (announce on `htmx:afterSettle` with a further ~500ms idle check), or announce only when the count **value** differs from the last announced value. Both are one-liners and neither changes the visual behaviour.

---

# LOW

## L-1 · Document `<title>` is not updated on `hx-push-url` swaps

EXPERIENCE.md:463 — facet swaps carry `hx-push-url="true"`, so the URL changes to reflect the filters. The document title does not, so the page's accessible name and the browser history entry both go stale. WCAG 2.4.2 (A) is arguably still met by the original title, but history navigation becomes ambiguous. **Fix:** have the swap response carry an `HX-Push-Url` companion title update, or include a `<title>` fragment via `hx-swap-oob`.

## L-2 · Forced-colors mode is not considered — and the design survives it, for one reason

Neither document mentions Windows High Contrast / `forced-colors`. Under it, `background-color` and `border-color` are overridden and **`linear-gradient` is dropped entirely**. The consequences for this specific design:

- `.chip::before` markers with `background: currentColor` all collapse to the same forced foreground — **the marker channel is gone**.
- `.na`'s struck-circle marker (DESIGN.md:630) is a `linear-gradient` — **dropped entirely**.
- The stale `::after` (DESIGN.md:645) is a `linear-gradient` in `--warn` — **dropped entirely**.
- All hue is gone.

So two of four status channels vanish, and stale's only visual carrier vanishes. **No state collapses anyway**, because the lowercase word is real text and the footline is real text. This is the doctrine at EXPERIENCE.md:518 paying off exactly as designed, in a mode nobody wrote down.

**Fix** State it as a supported mode rather than an accident: add a `@media (forced-colors: active)` block that redraws the sentinel markers with `border` (which is honoured) instead of `background`/`gradient`, and — since the stale mark cannot be drawn — confirm the visually-hidden `stale` text from H-5 is what carries it. One paragraph in DESIGN.md and one row in the Accessibility Floor.

## L-3 · `403 · refused` violates the document's own chip-label rules

EXPERIENCE.md:296 specifies "a `403 · refused` chip" on the refusal page. But L2 (:161) forbids any chip label that is "prefixed, appended, or interpolated" and names `error · 429` as illegal by exactly this shape; L4 (:163) restricts `.plain` labels to a second closed enumeration that does not contain `403 · refused`; L5 (:164) concludes that a string in none of the enumerations "is not a chip". Scope-adjacent to accessibility rather than a failure in itself, but the chip/text boundary is what keeps the status channel clean, and this is the document breaking its own rule three rules after stating it. **Fix:** make it body text or a key-value row ("`403` — refused"), consistent with L5 and with the key-value panel the same paragraph already specifies.

## L-4 · `--unk` on `--unk-wash` passes with 0.8% headroom — mark it no-touch

`#5a6d75` on `#e6ecee` = **4.537:1** against a 4.5 requirement. It passes. It is also the tightest pair in the system by a wide margin, and it belongs to `unknown` — the one state the entire product exists to keep visible. Any future darkening of the wash or lightening of the hue breaks it. **Fix:** annotate the pair in DESIGN.md's token block as fixed, or take `--unk` to `#566970` (4.9:1) for margin. Related: `--unk` on `--surface-3` is 4.67 and on `--paper` 4.60, both similarly tight.

## L-5 · The greyscale test has no owner and no mechanism

EXPERIENCE.md:516 — "**The test:** render any status-bearing surface in greyscale. All five outcome states must remain distinguishable." DESIGN.md:634 asserts the outcome ("Print the page in greyscale and every state is still separable"). Neither says who runs it, when, or against what. The natural home already exists: EXPERIENCE.md:491 specifies a template-lint test that greps for chip markup outside the four inclusion tags and fails the build. **Fix:** add a companion check to that same suite — render the five chips, desaturate, assert marker-geometry difference — or, if that is over-engineering for an internal tool, downgrade the wording from "the test" to "the review check" and name it as a manual step in the design review.

## L-6 · The 8px marker set is more marginal than DESIGN.md:634 claims

"The four sentinel markers are **mutually distinguishable at 8px by geometry alone**: filled, hollow, dashed, struck, angular." At 8px diameter with a 1.5px stroke, a **dashed** ring has a circumference of ~25px; browsers distribute dashes on tiny circles inconsistently and frequently render them as near-solid or as an irregular ring. `not_found` (dashed) versus `unknown` (hollow) is the pair at risk, and it is a meaningful pair — "we looked and there is none" versus "we have not looked" is the distinction Ravi's flow turns on (EXPERIENCE.md:580). The `.na` struck circle relies on a diagonal bar spanning 12% of 8px ≈ **1px**.

The channel does not fail — the word carries it, which is the design — but the sentence overclaims. **Fix:** soften :634 to "distinguishable by geometry at 8px for most readers; the word remains the authoritative channel", or raise `markerSize` to 9–10px for the ring variants and widen the dash pattern explicitly rather than relying on the browser default.

---

# What passes — verified, not assumed

These were checked and are genuinely sound. Listed so the report is not read as uniformly negative.

**Colour and contrast**

1. **Every status chip passes 4.5:1 on its own wash, in both themes.** Light: ok 5.96 · warn 5.44 · crit 6.55 · unk 4.54 · nf 5.84 · na 5.31 · err 6.78 · accent 6.27. Dark: ok 6.57 · warn 7.11 · crit 6.69 · unk 6.53 · nf 7.20 · na 7.21 · err 6.74 · accent 5.99. The 11px chip text was correctly treated as normal text throughout.
2. **Every semantic hue passes on `--surface` and `--surface-2`**, both themes. Light on surface: 5.41–8.30. Light on surface-2: 5.03–7.71. Dark on surface: 7.21–8.36. Dark on surface-2: 6.69–7.75.
3. **Dark mode has no contrast failure anywhere in the system**, including every pair that fails in light. The claim at DESIGN.md:400 that the dark palette was re-picked rather than filtered holds up numerically.
4. **The status marker, being `currentColor`, inherits the chip's ratio** — so every marker clears 3:1 for 1.4.11 by a wide margin (worst case unk at 4.54).
5. **The stale hold mark clears 1.4.11 on every chip ground.** Light `#855505`: 5.14 (crit-wash) to 5.44 (warn-wash). Dark `#e0ab55`: 6.72 (accent-wash) to 7.81 (err-wash). All ≥ 3:1.
6. **`--on-accent` on `--accent`**: 7.51 light, 7.85 dark. The `--on-accent` promotion at DESIGN.md:402 is correct and improves on the mockup.
7. **The text ladder passes** apart from `--muted`: `--ink` 15.43–18.18 light / 12.25–16.07 dark; `--ink-2` 8.50–10.02 / 8.00–10.49.
8. **`.chip.plain`** (`--ink-2` on `--surface-2`): 9.30 light, 8.92 dark.
9. **`.conf` tags at 10px**: verified 7.09 / derived 6.37 / unmapped 5.41 on surface (light). Pass.
10. **The invalid form state**: `--crit` error text on surface 8.11 light / 7.24 dark; `--ink` on the `--crit-wash` input fill 14.68 / 13.61. And DESIGN.md:772 correctly insists on border **and** fill **and** text, never colour alone.
11. **The focus ring** `--accent` clears 3:1 against every ground it can appear on: 6.27–7.51 light, 5.99–8.13 dark. Global, never removed, never restyled per component (DESIGN.md:796-802), with a 2px offset chosen for `--surface-2` chrome. This is better than most systems manage.
12. Chip borders at `color-mix(32%)` compute to 1.5–2.2:1 against their washes. **Correctly not a failure** — the chip is non-interactive and its border carries no information the four channels do not.

**Status without colour**

13. **Nothing in either document conveys an outcome state by colour alone.** Verified in each context: the table cell (chip word + footline, both real text), the export (enum value verbatim, EXPERIENCE.md:442), the facets (sentinels as first-class filter values with counts, :183/:782), the 403 page (role and surface as text, :545), the collector-health table (word + footline + linked trace id, :595).
14. **The `.sorted` column indicator is colour-only visually** — but the sort is stated in words in the applied-filter bar (EXPERIENCE.md:407, DESIGN.md:713) and exposed as `aria-sort`. 1.4.1 satisfied.
15. **The active facet, the selected row and the priority bucket all pair colour with a non-colour carrier** — a native checkbox, a native checkbox, and the printed bucket number respectively.
16. **`.conf`'s three states differ by hue but carry three different words** (`verified` / `inventory-derived` / `unmapped`). Colour is decoration; the word is the channel.
17. **The decision to keep `.conf` text-only, off the chip axis** (DESIGN.md:692) is the right accessibility call, not just the right semantic one: it stops a confidence being announced in the same shape as a status.
18. **The `--warn` correction** (DESIGN.md:428-438) removes a genuine three-way channel overload the mockup had. It is the single largest accessibility improvement over the mockup and is fully specified.

**Semantics and interaction**

19. **Modals are fully specified**: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, focus to the first field on open, trapped while open, Escape closes, one level deep, never two (EXPERIENCE.md:189, :501, :534). Only the restore-target problem (C-2) is outstanding.
20. **Tables**: `<th scope="col">` on every header, `scope="row"` on the package cell, `<caption>` on nested evidence tables, `aria-sort` on the sorted column (EXPERIENCE.md:532, :541). Putting `aria-sort` on a *non-interactive* `th` is the correct call given sorting is not user-controllable — a subtlety many specs get wrong.
21. **The facet-swap live region is correctly scoped** (EXPERIENCE.md:253) — the result count, not the table, is what announces. And focus genuinely survives that swap, because the focused checkbox is outside `#health-rows`.
22. **`prefers-reduced-motion`** is global, non-negotiable, and — crucially — the spinner is `role="presentation"` and is explicitly never the only in-progress signal (EXPERIENCE.md:272, :524; DESIGN.md:757).
23. **Session expiry mid-HTMX** is handled correctly at the middleware layer with `HX-Redirect` and an empty body (EXPERIENCE.md:314, :479), preventing a login page from being swapped into a table row. This is a real failure mode most specs miss.
24. **`{% status_chip %}` as the only path to a chip**, enforced by a template-lint test that fails the build (EXPERIENCE.md:486, :491). Making the four channels inseparable *at the tag* rather than by convention is the strongest structural decision in either document — it is why the doctrine will survive contact with implementation.
25. **Every SVG carries `role="img"` and a descriptive `aria-label`** (DESIGN.md:808).
26. **No hover-only affordances anywhere** (EXPERIENCE.md:182, :496); the row-hover tint carries no meaning. Nothing is revealed by hovering, so nothing is lost without a pointer.
27. **The keyboard model decision — invent nothing, standard browser semantics only** (EXPERIENCE.md:500, G-13) — is correct and correctly reasoned for a three-role internal tool.

**The mockup's eight named gaps**

| Gap (extract-mockups.md:215-224) | Status | Where |
|---|---|---|
| No `<h1>`; `<h2>` → `<h4>` skipping `<h3>` | **Partially closed** | EXPERIENCE.md:530 fixes the main case; modal, sidebar and eyebrow levels unassigned, and DESIGN.md:496 still implies `h4` — see M-3 |
| No `aria-live` on the async toast | **Partially closed** | EXPERIENCE.md:531 adds it, but `aria-atomic="true"` + a 3s whole-region swap makes it worse than absent — see C-1 |
| No `aria-sort` | **Closed** | EXPERIENCE.md:532 |
| `<x>✕</x>` filter-pill remove | **Closed (semantics) / open (size)** | EXPERIENCE.md:533 makes it a real `<button>` with the full filter as its accessible name — better than the usual "remove". Still ~12×12px — see H-3 |
| Modals lack dialog semantics and focus trap | **Closed** | EXPERIENCE.md:534, with the C-2 caveat on the restore target |
| `.errmsg` not tied by `aria-describedby`; no `aria-invalid` | **Closed (association) / open (delivery)** | EXPERIENCE.md:535, :604 — wired at the crispy template pack, correctly. Focus and announcement missing — see H-6 |
| Unlabelled select-all | **Closed** | EXPERIENCE.md:536, and the "page not result set" scoping is stated in both the accessible name and the visible copy |
| `a.locked` as a link | **Closed** | EXPERIENCE.md:537, :89 — deleted from the system entirely rather than patched, with the right reasoning |

**6 of 8 fully closed, 2 partially.** No named gap was missed. Two new gaps arrived with the fixes (the toast live region, the pill's target size), and both are filed above.

---

## Recommended order of work

1. **C-1** — split the toast; it is the only defect here that makes the product unusable for a whole class of user while a job runs.
2. **H-2** — one token, `--muted` → `#556670`. Closes M-9 and half of M-8 for free.
3. **C-2** — name a focus destination for every swap; it is the primary write path.
4. **H-1** — skip link and landmarks; a Level A gap inside an AA floor, and cheap.
5. **H-4** — two export columns; it is the CPM-SM-C1 hole in the artifact that leaves the system.
6. **H-5, H-6, H-7** — these three are one edit: give the stale span a home, give validation a focus destination, and replace the two-region cap with a three-region enumeration.
7. **H-3** — a target-size subsection in DESIGN.md, which is where EXPERIENCE.md already sent it.
8. The mediums and lows as capacity allows; **M-7** is a wording fix with no implementation cost and should ride along with any edit.

## The single highest-value structural fix

EXPERIENCE.md:510 delegates **contrast ratios and target sizes** to DESIGN.md. DESIGN.md accepts neither — it states no ratio requirement and never uses the phrase "target size". Every measurable failure in this report lives in that one seam, and the seam will re-open the moment a token or a control is added.

**Fix it once:** add a short **Accessibility contract** block to DESIGN.md's Colors and Components sections stating the two numbers it now owns — *every text/ground pair in this document meets 4.5:1 (3:1 for ≥18.66px bold or ≥24px); every interactive control presents a ≥24×24 CSS px hit area* — plus the computed table from H-2 as the evidence that the palette meets it. Then EXPERIENCE.md:510's delegation is true, and the next token added has a number to fail against.
