# Spine Pair Review — Conda Package Supply Chain Monitor

Lens: **rubric walker** (`.claude/skills/bmad-ux/references/validate.md`)
Reviewed: `DESIGN.md` (857 lines) · `EXPERIENCE.md` (653 lines)
Sources of truth: `.working/extract-epics.md`, `extract-prd.md`, `extract-architecture.md`, `extract-mockups.md`, `.memlog.md`
Run at: 2026-09-04

---

## Overall verdict

This is a strong spine pair. The document boundary is real and mostly held — DESIGN owns pixels, EXPERIENCE owns behaviour and references tokens by path — and the hardest thing in the brief, the CPM-SM-C1 / CPM-FR-6 no-collapse doctrine, is carried correctly and redundantly through both files. The stale-as-a-property correction is applied cleanly in both documents with no residue, which was the single highest-risk consistency check and it passes outright. Rigor around withheld numbers is genuinely good: p95, `PAGE_SIZE`, `CPM_SYNC_EXPORT_MAX_ROWS`, the score function and P1–P10 content are all absent as values, and both files carry an explicit "numbers this document does not state" section.

Three things stop it being ready to hand to an implementer. Eight token references in EXPERIENCE.md do not resolve against DESIGN.md's frontmatter, so a consumer extracting mechanically gets nulls on the stale chip, the plain chip and the stale footline — the three components that carry the document's central doctrine. Three of the PRD's no-collapse invariants (CPM-FR-10, CPM-FR-16, CPM-FR-17) appear nowhere in either spine, even though they are exact siblings of the CPM-FR-6 rule the pair treats as its thesis. And the flagship surface — the current package-health view, CPM-APP-S02 — never has its column set stated, while the queue list's is.

Everything else is small, mechanical, and cheap to fix.

---

## Category verdicts (rubric passes 1 and 2)

| # | Category | Verdict |
|---|---|---|
| 1 | Flow coverage | **adequate** — three flows, named protagonists, climaxes, edge cases, one failure path; UJ identifiers not carried |
| 2 | Token completeness | **thin** — colours complete with light/dark pairs; 8 references unresolvable; type ramp declared closed then violated |
| 3 | Component coverage | **adequate** — 17 of 18 components paired; `.notebox`, the disclosure control and the app shell unspecified |
| 4 | State coverage | **strong** — five outcome states, five emptinesses, 403/404/500/session-expired, in-progress, collector error, all designed |
| 5 | Visual reference coverage | **thin** — no inline link from any spec section to any mockup screen |
| 6 | Bloat & overspecification | **strong** — no source restatement of substance, no decorative narrative, tables used where tables work |
| 7 | Inheritance discipline | **adequate** — sources resolve, glossary held rigorously (V1–V4 is exemplary); UJ names and three FRs not inherited |
| 8 | Shape fit | **strong** — both section orders exact, invented sections earn their place |

---

## The eleven requested checks

| # | Check | Result |
|---|---|---|
| 1 | EXPERIENCE.md has all eight required sections | **PASS, clean.** Foundation (L23), Information Architecture (L51), Voice and Tone (L131), Component Patterns (L170), State Patterns (L196), Interaction Primitives (L455), Accessibility Floor (L506), Key Flows (L550). Five invented sections (Evidence and Provenance, Queues and Transitions, Reports and Export, Open Gaps, Withheld Values) all earn their place. |
| 2 | DESIGN.md canonical section order | **PASS, clean.** All eight present, none out of order: Brand & Style 332 → Colors 344 → Typography 440 → Layout & Spacing 499 → Elevation & Depth 544 → Shapes 580 → Components 597 → Do's and Don'ts 829. |
| 3 | All eight CPM-APP stories addressed | **PASS with one note.** S01–S06 and S08 have surfaces or named behaviour. S07 has no screen — but its load-bearing requirement (a status serialized verbatim as its `OutcomeState` value over the API) *is* covered at EXPERIENCE.md:160 and :491, and the missing docs surface is named as G-7. No story is silently missing. |
| 4 | Three journeys as Key Flows | **PASS with one low finding.** Dana Okafor (L554, climax step 7, edge case, failure path), Ravi Nandakumar (L572, climax step 7, edge case), Sam Ibarra (L590, climax step 6, edge case). See **L1** — the `CPM-UJ-1/2/3` identifiers are not carried onto the headings. |
| 5 | IA closure in both directions | **FAIL.** Surfaces with no journey: **H2** (feedstock-gap), **M9** (remediation queue, identity queue item). Needs with no surface: **H3** (three FRs), **H4** (health-view columns). |
| 6 | Cross-document contradictions | **FAIL.** **H5** (viewport), **M1** (`.plain` enumerations), **M6** (split gutter, internal to DESIGN), **M7** (amber freshbar cell), plus **L2**, **L3**, **L4**, **L8**. |
| 7 | Source invariants | **PASS on everything checked except H3.** CPM-AD-9 (EXP:266), AD-10 (EXP:237, 475, 584), AD-11 (EXP:245, 342), AD-12 (EXP:497), AD-13 (EXP:389–398, both halves stated per the memlog resolution), AD-14 (EXP:601–607), AD-22 (EXP:396, 402), AD-24 (EXP:217, 442), CPM-FR-6 (EXP:200–217), CPM-FR-31 (EXP:43, 393), CPM-SM-C1 (EXP:47, 298, 597; DESIGN:338) are all carried correctly and none is contradicted. **H3** is a coverage gap, not a contradiction. |
| 8 | Stale-as-a-property applied consistently | **PASS, clean.** Swept both files for residue and found none. DESIGN:428–438, 638–660, 834 and EXPERIENCE:221–231 agree exactly: stale keeps the underlying hue and marker, `--warn` is determinate amber only, `blocked` sits on the CPM-FR-41 readiness axis. The mockup's `stale evidence` readiness value is correctly demoted to a property (mockup had `ready/blocked/stale evidence/unknown`; EXPERIENCE:229 has `ready/blocked/unknown` + stale as a property). No place in either document still treats stale as a status or overloads warn. The only stale-adjacent defects are naming (**H1**) and an example string (**M2**). |
| 9 | Invented numbers | **PASS except M2.** p95: withheld (DESIGN:856, EXP:644), no value. `PAGE_SIZE`: withheld (EXP:645), and the pager is specified to read it from settings (EXP:185). `CPM_SYNC_EXPORT_MAX_ROWS`: withheld (EXP:646, 449); the "1,091 rows" in EXP:142/274 is an illustrative row count, not the cap. P1–P10 content: withheld (DESIGN:707, EXP:409, 648); DESIGN's four-band colour mapping is presentation, explicitly disclaimed. Score function: absent everywhere. "three KEV findings, all ranked P1" (EXP:560) is verbatim PRD journey text, not an invented assignment. **Only violation: `target 24h`, twice — see M2.** |
| 10 | `[ASSUMPTION]` tags genuine | **PASS with one low finding.** Six tags. Google Fonts reachability (DESIGN:452), job-poll ceiling (EXP:290), bulk-transition semantics (EXP:419), keyboard model (EXP:500) are all genuinely unsourced. Queue-to-role mapping (EXP:387) correctly stays an assumption — `.memlog.md` records it as `(assumption) OPEN DECISION for Kevin`, never upgraded. See **L6** for the one that partly restates a user decision. |
| 11 | Buildable without the mockup | **Mostly, with named holes.** See **H4** (health-view columns), **M8** (no inline screen references), **M10** (`.notebox`, the `evidence ▾` control, the app shell / avatar). Everything else — the chip system, the five states, the freshness bar, the queue mechanics, the async state, every empty and error state — is buildable from the text alone. |

---

## Findings by severity

### HIGH (5)

**H1 — Eight token references in EXPERIENCE.md do not resolve.**
`EXPERIENCE.md:163, 177, 227, 336, 363, 417` (and `227` again)
`{components.chip.plain}` (×5), `{components.chip.stale}` (×1), `{components.ev.stale}` (×2) are written in dotted-subkey form. DESIGN.md's frontmatter keys are flat and hyphenated: `chip-plain` (DESIGN:208), `chip-stale-overlay` (DESIGN:213), `ev-stale` (DESIGN:223). DESIGN.md itself uses the hyphenated form internally (`footline: '{components.ev-stale}'`, DESIGN:216), so the two files disagree on the reference syntax for exactly the three components that carry the no-collapse doctrine. `.memlog.md:37` records a post-distill sweep that claimed "75 refs, 0 unresolved" — the sweep missed these because they look well-formed. A consumer resolving mechanically gets three nulls.
*Fix:* rewrite the eight references to `{components.chip-plain}`, `{components.chip-stale-overlay}`, `{components.ev-stale}`. Re-run the sweep with a check that every `{components.X}` matches a literal frontmatter key, not a dotted path.

**H2 — Flow 2's entry surface is not one of the six reports, and the gap is not flagged.**
`EXPERIENCE.md:431, 433` vs `576` (also `247`, `574`, `577`)
L431 lists the six recurring reports (daily KEV · **weekly feedstock lag** · Python 3.14 readiness · licence exceptions · unmapped identities · stale evidence and collector failures) and L433 states `/reports/` is "an index of **six** cards". Ravi then opens `/reports/**feedstock-gap**/` at L576, and L247 makes the feedstock-gap report the single surface where the `unmapped` exclusion rule (APP.05-API-002) lives. `extract-prd.md:120` names this precisely: *"The feedstock-gap report (UJ-2's central artifact). FR-26 lists 'weekly feedstock lag' which is currency, not presence."* So either feedstock-gap is a seventh report (contradicting "six cards") or it is "weekly feedstock lag" renamed (contradicting the source distinction between lag and gap). The asymmetry is what makes this high: the coverage view has exactly the same defect and *is* flagged as G-9, while this one is silently designed around.
*Fix:* add **G-18** naming the feedstock-gap report as a journey-entry surface with no FR, mirroring G-9's wording, and state in Reports and Export whether it is a seventh card or a renaming of "weekly feedstock lag". Until decided, mark the index count as "six named in FR-26, plus feedstock-gap pending G-18".

**H3 — Three PRD no-collapse invariants appear in neither document.**
`EXPERIENCE.md` (absent), `DESIGN.md` (absent)
Grep for `CPM-FR-10`, `CPM-FR-16`, `CPM-FR-17` returns nothing in either file. From `extract-prd.md:40–42`:
- **CPM-FR-17** — KEV membership always distinguishable, **never averaged into severity**. The mockup carries KEV as its own health-table column for this reason.
- **CPM-FR-10** — each monitored channel produces its own observation; **channels are never merged**.
- **CPM-FR-16** — currency computed **per surface**; source-current and feedstock-stale must be expressible simultaneously across four surfaces (source, PyPI, feedstock recipe, published conda).
These are the same class of rule as CPM-FR-6, which the pair treats as its whole thesis — each is a "never collapse two things into one cell" constraint with a direct rendering consequence. An implementer reading only these spines will happily average KEV into a severity chip or merge two channels' observations into one footline, and nothing in either document stops them.
*Fix:* add three rules to **State Patterns**, adjacent to "The five outcome states never collapse": KEV renders as its own value in its own column, never folded into a severity chip (CPM-FR-17); a per-channel observation gets its own row/footline and channels are never merged into one value (CPM-FR-10); currency is per surface, and the four surfaces render side by side so source-current and feedstock-stale are simultaneously visible (CPM-FR-16). The last one also settles part of H4.

**H4 — The flagship surface's column set is never stated.**
`EXPERIENCE.md:111` (and absent thereafter)
The queue list's columns are specified exactly (`EXPERIENCE.md:413`: checkbox · package · priority bucket · score · work type · why this bucket · readiness · workflow state · age). The health view — CPM-APP-S02, called "the flagship" at L111 — gets only its *filters* ("derived status, package-identity confidence, priority bucket, work type"). Its columns exist only in `extract-mockups.md:159` (Package · P · Score · Work · Currency · Vulnerability · KEV · Licence · Py 3.14 · Feedstock · Confidence). V3 at L153 even corrects the *heading* of a column the document never says exists. This is the single largest place an implementer without the mockup must guess, and the guess is load-bearing: the KEV and Currency columns are where H3's invariants land.
*Fix:* add a health-view column table to Information Architecture or Reports and Export, in the same shape as the queue-list line at L413, applying the V3 heading rule. Name which columns are outcome-status columns (one chip each), which is the readiness axis, and which is the `{components.conf}` tag, so the "two axes never share a column" rule at L230 is checkable.

**H5 — The two documents give different minimum viewports.**
`DESIGN.md:538` vs `EXPERIENCE.md:546`
DESIGN: *"App screens assume a viewport of at least roughly 960px."* EXPERIENCE: *"The app currently pins each screen to a 920–1180px minimum width."* Both statements are load-bearing — they set the WCAG 1.4.10 Reflow shortfall both documents record as an accepted v1 limitation, and 920 vs 960 vs 1180 are three different answers to "what does an implementer set `min-width` to". The 920–1180 range is lifted from `extract-mockups.md:243` (a per-screen range in the specimen book), so EXPERIENCE is reporting the mockup's state while DESIGN is specifying the contract. Secondary defect: this is also EXPERIENCE.md restating a layout value instead of referencing DESIGN, in violation of its own rule at L17.
*Fix:* DESIGN.md owns the number — pick one (960px reads as the intended contract) and state it once in Layout & Spacing. EXPERIENCE.md:546 should say "the minimum width DESIGN.md sets in Layout & Spacing" with no digits, and keep only the behavioural consequence (horizontal scroll at 200% zoom, accepted, G-6).

---

### MEDIUM (10)

**M1 — The two documents enumerate `.plain` chip contents differently, and DESIGN's list is illegal under EXPERIENCE's rule.**
`DESIGN.md:636` vs `EXPERIENCE.md:163–164`
DESIGN:636 — `.plain` "carries non-outcome facts only: workflow states, `superseded`, `skipped`, `authority`, `idle`, a selection count."
EXPERIENCE:163 (rule L4) — plain chips draw labels from "workflow state names, run-ledger states (`running`, `succeeded`, `failed`, `idle`), readiness values (`ready`, `blocked`, `unknown`), and `superseded`."
Then EXPERIENCE:164 (rule L5): *"A string that belongs to none of these enumerations is not a chip."* Under that rule, DESIGN's `authority`, `skipped` and "a selection count" are not chips at all. Conversely DESIGN's list omits readiness values, which are the readiness column's entire vocabulary. An implementer building the readiness column has one document telling them it is a plain chip and the other omitting it.
*Fix:* EXPERIENCE.md owns the enumeration (it is a copy/vocabulary rule, not a visual one). Make L4's list authoritative and complete — add or explicitly reject `authority`, `skipped` and the selection count — then reduce DESIGN:636 to "carries non-outcome facts only; the closed enumerations are in EXPERIENCE.md rule L4".

**M2 — `target 24h` is printed twice as a concrete freshness target the document forbids.**
`EXPERIENCE.md:227` — ``footline naming the target it missed: `vulnerability_findings · observed 2026-08-29 · stale, target 24h` ``
`EXPERIENCE.md:334` — ``it is where every disqualified chip label from rule L3 lands: `target 24h`, `trace 4c1f9a2e`, … ``
`EXPERIENCE.md:652` — *"The mockup's 500-row cap, its **24h / 7d / 30d freshness targets**, … are illustrative and self-declared invented. **None may be lifted into an implementation.**"* Per-collector freshness targets are PRD OQ 7 and are listed in Withheld Values at L647. The document lifts one of the three numbers it names, into the two places an implementer copies the footline grammar from.
*Fix:* replace both with a placeholder that cannot be pasted — ``stale, target {freshness_target}`` and ``target {freshness_target}``. This is the sharpest case in the pair because the surrounding prose is otherwise scrupulous about it.

**M3 — The toast stacking cap is asserted as a rule in one section and declared undefined in two others.**
`EXPERIENCE.md:188` vs `EXPERIENCE.md:502` and `628`
L188 (Component Patterns): *"Never stacked more than three deep."* L502 (Interaction Primitives): *"Stacking rules are undefined (G-11)."* L628 (G-11): *"Stack newest-first, cap at three visible"* — offered as a recommendation on an open gap. So the Component Patterns table states as binding what the gap table says is undecided.
*Fix:* soften L188 to reference the gap ("stacking per G-11 — undecided"), or promote G-11's recommendation to a decision and delete the gap. Do not leave a binding rule and an open gap pointing at the same number.

**M4 — Triggering a recollection is designed with no source permission, no assumption tag and no gap entry.**
`EXPERIENCE.md:231`, `566`
L231 makes "Recollect evidence" the primary control on any stale finding — the pivot of Dana's journey and the mechanism behind the CPM-FR-38 stale rule. L566 has Dana execute it and receive a `202`. `extract-prd.md:123` names this explicitly: *"Trigger a recollection (UJ-1 edge case). **No FR grants any role the ability to initiate one**; it is another write."* The document handles the structurally identical problem — Ravi's tracking-URL write — with exemplary care (G-2, a full inline note at L584, and an explicit "until both exist, no implementation may add one"). This one gets nothing. Architecturally an enqueue is permitted (CPM-AD-9 makes a collector run a task), but *which roles may enqueue it* is unstated by every source and unstated here.
*Fix:* add **G-19**: recollection is an enqueue, not a third write, and CPM-AD-9 permits it — but no FR grants any role the right to initiate one. Recommend all three roles (read is shared and no derived state is written by the request), and flag it for confirmation before CPM-APP-S08 is written. One paragraph, in the shape of G-2.

**M5 — DESIGN declares a closed type ramp, then uses at least four sizes outside it.**
`DESIGN.md:482` — *"The table above is the whole scale; **a size not in it does not exist**."*
Violations, all in Components: `11.5px` Sans at **:732** (stat foot line), **:743** (`.btn.sm`), **:755** (toast secondary line), **:770** (`.help` and `.errmsg`); `12px/600` Sans at **:770** (`.field` label — the ramp has 12px only at weight 400, as `meta`); `10.5px` mono at **:728** (`.kv dt`); `12px` mono at **:766** (`.input.mono` — the ramp has mono at 11.5 and 11). Seven uses, four sizes. The ramp is otherwise the document's best piece of discipline, and the sentence at L482 is what makes it enforceable, so the violations undercut a genuinely good rule rather than being cosmetic.
*Fix:* add the missing roles to the frontmatter and the L464 table — `body-xs` (Sans 11.5/400), `field-label` (Sans 12/600), `mono-kv` (Mono 10.5/400), `mono-input` (Mono 12/400) — or amend L482 to name the control-internal exception the way L520–524 already does for padding.

**M6 — DESIGN contradicts itself on the split layout's gutter, and gives two column definitions.**
`DESIGN.md:302–305` (frontmatter) vs `530` vs `778`
Frontmatter: `gridTemplateColumns: 236px 1fr`, `gap: '{spacing.5}'` (24px). L530: `grid-template-columns: 236px minmax(0, 1fr)`, *"wrapped in a 1px `--line` border **with no gutter between them**."* L778: `grid-template-columns:236px 1fr; gap:{spacing.5}`. So the gutter is 24px in two places and zero in one, and the main column is `1fr` in two places and `minmax(0, 1fr)` in one. The `minmax` distinction is not cosmetic — with plain `1fr` a wide health table blows the grid out instead of scrolling inside its container, which is the exact behaviour L538 requires.
*Fix:* settle on `236px minmax(0, 1fr)` and one gap value in all three places. Given L530's "no gutter" reads as the intended design (the sidebar sits inside the same bordered container), `gap: 0` with the `--line` divider is the likely answer.

**M7 — EXPERIENCE specifies a colour by name for a freshbar cell DESIGN does not define.**
`EXPERIENCE.md:559` — ``and `collectors: 7 of 8 healthy` **in amber**``
Two problems. First, it restates a visual value in words instead of referencing a token, against the document's own rule at L17 ("Where this document needs to name a visual thing it references a token by path… It never restates a value"). Second, DESIGN.md's `.freshbar` spec (:225–230, :677–681) defines cells as `.lbl` in `mono-eyebrow` plus a `<b>` value in `--ink-2`, with no semantic-hued cell variant; the only warn-coloured freshbar affordance DESIGN offers is the 3px left rule (:566–570). So the treatment EXPERIENCE asks for does not exist. (L566's "it did not become amber" is fine — that is prose about a rule, not a spec.)
*Fix:* add a hued-cell variant to DESIGN's `.freshbar` (a cell whose `<b>` takes a semantic hue, with the permitted hues enumerated), then change L559 to reference it — e.g. "`collectors: 7 of 8 healthy`, the value in `{colors.warn}`". Or drop the colour from the journey beat entirely and let the 3px rule carry it.

**M8 — Neither document links to a single mockup screen at any relevant section.**
`DESIGN.md:11, 15`; `EXPERIENCE.md:12, 19`
`imports/ui-mockups.html` appears in both frontmatters, once in a DESIGN comment ("Verbatim from … lines 7-39"), and once in EXPERIENCE's spines-win statement. Every other reference is to "the mockup" in prose. Both documents spend substantial text *correcting* specific screens — the nav resolution at EXPERIENCE:75 names S7/S8/S10/S11, the sidebar-width defect at DESIGN:530 and the modal-offset defect at DESIGN:751 each name "one screen" without saying which — and a reader holding the mockup cannot find the screen being corrected without searching 2,911 lines.
*Fix:* the surface inventory at EXPERIENCE:107–119 already keys every screen S1–S11; add an anchor link per row into `imports/ui-mockups.html`, and cite the screen id inline wherever either document corrects a specific one (DESIGN:530 → S7, DESIGN:751 → S7, EXPERIENCE:153 → S3 and S9).

**M9 — Two queue surfaces have no journey that lands on them, including the protagonist's own queue.**
`EXPERIENCE.md:114` (S6, `/queues/remediation/`), `115` (S7, `/queues/identity/<name>/`)
S6 is the richest queue surface in the inventory — bucket-then-score ranking, the readiness column, "why this bucket", bulk selection, all specified at L413 and L419 — and no flow opens it. Ravi *is* the packaging engineer and the queue-to-role table at L384 assigns Remediation to him, yet Flow 2 enters at a report, works from package detail, and advances a workflow item at step 7 from an unstated surface. Flow 1 routes *into* the remediation queue (L564) but Dana never sees it. Similarly, S7 is the package-identity review item surface, and Flow 3's override happens "from the package detail view" (L601), so the identity queue is only ever *exited* (L606), never entered. Bulk actions (L419) and the "why this bucket" column are likewise never exercised by a journey.
*Fix:* add a beat to Flow 2 between steps 5 and 6 in which Ravi opens `My queue` → the remediation work queue, reads a "why this bucket" sentence and its rule footline, and picks up the item Dana routed in Flow 1. That single beat closes S6, closes the bulk/readiness affordances, and joins Flow 1's climax to Flow 2 — which is the pair's strongest available demonstration that routing moves one object rather than creating two.

**M10 — Three referenced things have no specification in either document.**
- **`.notebox`** — `DESIGN.md:514, 561, 823` (and implicitly `577`, `586`). Referenced as one of the three carriers of the 3px left rule, and named as Bootstrap `.alert`'s replacement, but it has no frontmatter token, no Components row, and no Component Patterns row. An implementer knows it exists, is dashed-adjacent, and takes a 3px rule — nothing else.
- **The `evidence ▾` control** — `EXPERIENCE.md:360, 495`; DESIGN has no row for it. The disclosure's *behaviour* is fully specified (hx-get, afterend, superseded rows, re-fetch on reopen); its appearance is inferable only from the collision note at `DESIGN.md:722`.
- **The app shell** — neither document specifies the page header block (h1 + subtitle + button row), the top-nav bar's own metrics, or the avatar, though `DESIGN.md:591` applies `{rounded.full}` to "avatars" and `:408` mentions a brand glyph and an active-nav underline.
*Fix:* add a `.notebox` token and Components row to DESIGN (it is a `.freshbar` sibling); add a one-line visual spec for the disclosure control to DESIGN's `.tbl` section; add a short "page shell" subsection to DESIGN's Layout & Spacing covering the header block and the nav bar, since EXPERIENCE:62 makes the shell the only navigation the platform gives us.

---

### LOW (11)

**L1 — Key Flow headings do not carry the `CPM-UJ-1/2/3` identifiers.**
`EXPERIENCE.md:554, 572, 590`. The string `CPM-UJ` appears exactly once in the whole file, at L384, and it is a citation in the queue-mapping table — not a flow heading. A consumer tracing a requirement name from the sources cannot grep to the flow that satisfies it.
*Fix:* `### Flow 1 · CPM-UJ-1 — Dana Okafor clears a KEV finding before standup`, and equivalently for 2 and 3.

**L2 — `.pager` and `.pagenums` name the same component.**
`DESIGN.md:788` (`### .pager`) and frontmatter key `pager` (`:316`) vs `DESIGN.md:824` (Bootstrap `.pagination` → **`.pagenums`**). EXPERIENCE:185 uses `{components.pager}`.
*Fix:* pick one class name; `.pager` matches the token.

**L3 — DESIGN contradicts itself on which token draws the emphasised diagram path.**
`DESIGN.md:409` — *"`--accent-2` — inline `<code>` and **the emphasised path stroke in diagrams**. Nothing else."* `DESIGN.md:808` — *"solid **`--accent`** = the emphasised path."* `extract-mockups.md:238` records `--accent-2` as used only by `.anno code`, which suggests :808 is right.
*Fix:* delete the diagram clause from :409.

**L4 — The line-height summary contradicts the frontmatter.**
`DESIGN.md:482` — *"Line height is 1.2 on headings, 1.5 on body and mono, 1.45 on small sans."* Frontmatter has `section-title` 1.25, `dialog-title` 1.3, `panel-title` 1.3, `mono-th` 1.4, `mono-eyebrow` 1.4, `stat-value` 1.
*Fix:* the frontmatter is authoritative; soften the prose to "1.2–1.3 on headings, 1.5 on body and most mono, 1.4–1.45 on small sans and mono micro-labels — see the frontmatter for per-role values".

**L5 — The stated letter-spacing range does not match any token.**
`DESIGN.md:489` — *"Positive on mono micro-labels (**+0.03em to +0.13em**)."* The tokens run 0.03em (`conf`) to 0.1em (`mono-eyebrow`); 0.13em appears nowhere. `extract-mockups.md:80` shows +.05 to +.13em, so the upper bound was carried over from the mockup unchanged. Separately `.pbucket` sets `letter-spacing:.02em` (`:700`), below the stated floor, on a value rather than a micro-label.
*Fix:* state "+0.03em to +0.1em" and either drop `.pbucket`'s tracking or name it as a third case.

**L6 — The accessibility-floor `[ASSUMPTION]` conflates an origination with a user decision.**
`EXPERIENCE.md:510` tags the whole of "WCAG 2.2 AA … internal tool behind OIDC, three known roles, no public exposure — a reasonable floor with no formal compliance audit planned" as an assumption. The second half is verbatim a user decision: `.memlog.md:8` — *"(decision) Stakes: internal. Org-internal tool behind OIDC, three known roles, no public exposure. Reasonable accessibility floor, no formal compliance audit."* Only the specific standard version (2.2 AA rather than 2.1 AA) is originated here.
*Fix:* split it — "Stakes and posture are a recorded decision (internal, OIDC, no audit). `[ASSUMPTION: the specific target of WCAG 2.2 AA is originated here; no source names a standard.]`"

**L7 — "verbatim from the PRD" is not quite true of the protagonists' names.**
`EXPERIENCE.md:552` — *"Three journeys, three protagonists, **verbatim from the PRD**."* The PRD gives Dana, Ravi and Sam (`extract-prd.md:5–9`); the surnames Okafor, Nandakumar and Ibarra come from the mockup (`extract-mockups.md:25`). Both are legitimate sources — the claim is just mis-attributed.
*Fix:* "…three protagonists, first names and roles verbatim from the PRD, surnames inherited from the mockup."

**L8 — The two documents count the permitted action locations differently.**
`DESIGN.md:745` lists four ("the page-header button row, the package-name link, a per-row evidence disclosure control, and bulk verbs"); `EXPERIENCE.md:495` says "Actions live in **exactly three places**" and merges bulk selection with the header button row. Not a functional disagreement, but "exactly three" and a four-item list are both stated as rules.
*Fix:* this is a behavioural rule — let EXPERIENCE:495 own it and reduce DESIGN:745 to "There is no per-row action menu anywhere in the application; permitted action locations are in EXPERIENCE.md."

**L9 — DESIGN specifies a surface EXPERIENCE puts out of scope.**
`DESIGN.md:468, 549, 589` give the sign-in box a type role, a shadow and a radius; `EXPERIENCE.md:109` places S1 outside CPM-EP-APP ("platform-owned") and G-4 says "do not build it here."
*Fix:* mark the three sign-in entries in DESIGN as applying to the platform's allauth templates, or drop them and let the platform own the look too.

**L10 — DESIGN carries a handful of behavioural rules.**
`DESIGN.md:713` (`.sorted` is "a static indicator, **not a control**"), `:745` (no per-row action menu — see L8), `:790` (no page-size selector, no infinite scroll), `:774` (server-side validation — this one does defer, "EXPERIENCE.md owns that contract"), `:404` (no theme toggle in v1). Each is duplicated in EXPERIENCE (L499, L495, L185, L476, G-5) and each is a second place to keep in step. Mild, and DESIGN:342 explicitly promises behaviour lives in EXPERIENCE.
*Fix:* keep the visual half in DESIGN and cut the behavioural clause, or append "(behaviour: EXPERIENCE.md)" as :774 already does.

**L11 — "`--warn` means determinate amber and nothing else … One meaning, one hue" then lists five uses across four axes.**
`DESIGN.md:434` — `lagging`, `medium`, `manual review`, the `p3`–`p4` priority band, `inventory-derived` confidence. Those span a currency axis, a severity axis, a priority axis and a confidence axis. The underlying idea is sound and consistent (a determinate middle position on whatever ramp it appears on), and it is a genuine improvement on the mockup's three-way overload — the rhetoric is just stronger than the fact, which slightly weakens the correction it is making.
*Fix:* "one meaning — a determinate middle position — applied on four ramps: severity, currency, priority and package-identity confidence. It never marks staleness, blockedness, or any sentinel."

---

## Mechanical notes

- **Frontmatter.** Both files parse as valid YAML. DESIGN carries 44 colour tokens as full light/dark pairs with hex on every one, 15 typography roles, 6 radii, 8 spacing steps and 31 component tokens. EXPERIENCE's frontmatter is minimal (title/project/scope/status/updated/design_spine/sources) which is correct for the behaviour spine. `design_spine: ./DESIGN.md` resolves.
- **Sources.** All four `sources` paths in both frontmatters point outside this worktree (into the main repo's `_bmad-output/planning-artifacts/`) and could not be resolved from here; they were checked against the `.working/` extractions instead, which the caller confirms are faithful. `imports/ui-mockups.html` exists.
- **Token references.** 61 references across EXPERIENCE.md, of which 53 resolve and 8 do not (H1). All `{colors.*}` and `{typography.*}` references resolve.
- **Glossary discipline.** Exemplary and worth calling out. The V1–V4 rules at EXPERIENCE:151–154 hold the PRD's §3 glossary against the PRD's own practice, including the mono-face exception for machine identifiers, and the bare words *identity* and *confidence* do not appear as UI labels anywhere in either file. Component names are identical across both documents in every case except `.pager`/`.pagenums` (L2).
- **No Mermaid.** Both documents mandate hand-authored inline SVG and neither contains a diagram, so there is no syntax to check. Given how much of this pair is structural (the five states, the transition model, the four provenance layers), the absence of any diagram is a legitimate choice rather than an omission — the mockup carries five and EXPERIENCE inherits them by reference.
- **No `[ASSUMPTION]` in DESIGN.md beyond the fonts one**, which is appropriate: DESIGN is codifying an existing token system rather than originating one.
- **Withheld Values (EXPERIENCE:638–652) and "Numbers this document deliberately does not state" (DESIGN:854–856)** are the strongest rigor mechanism in the pair. DESIGN:856 — *"An implementer who finds a number here that is not in a source has found a defect in this document"* — is the right posture, and M2 is the only place it is breached.
