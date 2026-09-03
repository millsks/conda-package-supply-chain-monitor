# PRD Quality Review — Conda Package Supply Chain Monitor

- **PRD:** `_bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md`
- **Rubric:** `.claude/skills/bmad-prd/assets/prd-validation-checklist.md`
- **Upstream read:** brief, addendum, `.memlog.md`

## Overall verdict

This is an unusually disciplined PRD. It has a real thesis — deterministic policy is the
source of truth and an unknown is never a clean — and it holds that thesis all the way
down into individual FR consequences, counter-metrics, and the five-state vocabulary of
FR-6. Thirty-nine FRs carry consequences that are genuinely testable rather than
restatements of intent, which is rare; and four of the addendum's five "Decisions the PRD
must close" are closed with named rationale rather than deferred by silence.

What is at risk is concentrated and specific. The PRD asserts three separate times that
there is exactly one human write into governed data, while FR-25, FR-32, UJ-1 and UJ-2 all
describe further human writes — an engineer planning `EP-APP` will encode the wrong
authorization model. Two of the eleven derived statuses in Appendix A.3 have no policy FR
that produces them; the `P1`–`P10` bucket rules are undefined and, unlike the structurally
identical license policy, are not even an Open Question; and the word **confidence** is
overloaded exactly the way the PRD is careful not to overload **identity**. None of these
is a rewrite. All of them will be discovered late — during story creation — if they are
not fixed now.

## Decision-readiness — adequate

The PRD makes decisions and says so. Appendix A.1's key decision is stated as a decision
with the cost named ("a Python-specific natural key does not survive the non-Python later
phase … a surrogate keeps evidence foreign keys narrow and makes correcting a canonical
name non-cascading"). §7 out-of-scope gives reasons rather than a list ("There is nothing
to govern, cite, or explain until they do"). §0 justifies its own numbering scheme. The
`EP-EVIDENCE` note volunteers an inconvenience about its own table ordering. This is a
document that argues.

Against the addendum's table, four of five decisions are genuinely closed: the override
permission goes to the platform-and-engineering-leadership role (FR-3, and exercised by
Sam in UJ-3), matching memlog override 31; the key question is closed in favour of a
surrogate (Appendix A.1), matching override 28; the AI stack is closed by deferral, with
§7 stating the gate has not run; and the read-only analytics role is closed *as a
requirement* in FR-33 with provisioning correctly pushed to architecture. The fifth — how
a separate analytics service fits the deployment contract — has no disposition anywhere:
it is not closed, not named as deferred, and not an Open Question. More broadly, a reader
holding the addendum cannot tell which of the five the PRD believes it closed and which it
consciously handed onward; one short paragraph would fix that.

The real weakness is that the PRD reads as more settled than it is. There is not a single
`[NOTE FOR PM]` callout and exactly one `[ASSUMPTION]` tag across 39 FRs, 13 NFRs and an
appendix — yet there are live tensions (the write-path contradiction below, the unstated
queue-to-role mapping, the unassigned NFRs). NFR-5 was tagged honestly and given Open
Question 5; NFR-1, NFR-2, NFR-3 and NFR-8 have equally unset values and got neither tag
nor question. The rigor is real but applied unevenly.

### Findings

- **medium** Addendum decision 5 has no disposition (§ whole document, vs addendum
  "Decisions the PRD must close") — "How a separate analytics service fits the deployment
  contract" is neither closed, nor deferred by name, nor an Open Question. Open Question 6
  covers only model hosting. *Fix:* add an Open Question ("What deployment-contract
  process types and per-database migration stages does a separate analytics service
  require? Blocks `EP-NL`") and, in §0 or §10, one sentence stating which addendum
  decisions this PRD closed and which it hands to architecture.
- **medium** No `[NOTE FOR PM]` callouts at real tensions (§ throughout) — the write-path
  scope, the queue ownership mapping, and the priority ruleset are all unresolved and all
  presented in settled prose. *Fix:* add callouts at FR-3/FR-25 and FR-20.
- **medium** Uneven honesty about unset thresholds (§5) — NFR-5 carries `[ASSUMPTION]`
  and Open Question 5; NFR-1 ("completes without manual batching" — no time bound),
  NFR-2, NFR-3 (rate limits, backoff, timeouts, cache TTLs) and NFR-8 (row limits, query
  timeouts) are equally unvalued and carry neither. *Fix:* tag them the same way, or state
  once in §5 that all NFR values are set during architecture and only NFR-5 is called out
  because it gates a user-visible budget.
- **low** `EP-PLATFORM` names technologies against §0's stated exclusion (§9) — "Django
  service platform: settings, OIDC authorization, probes, Celery, observability" directly
  contradicts "Two things this document deliberately does not decide: … which products are
  adopted." The row is reporting an accomplished import (addendum §1), which is
  defensible, but nothing says so. *Fix:* one clause on the row — "reflects the completed
  platform import; not a decision this PRD makes."

## Substance over theater — strong

No theater found. The Vision (§1) could not be swapped into another PRD: "A language model
may explain, summarize, or draft; it never decides whether a package is compliant,
vulnerable, current, or high priority" and "v1 … delivers detection, evidence, and
prioritization. It does not remediate" are load-bearing constraints, not positioning.

Three personas, all of them driving actual decisions: the platform lead is why FR-3 exists
and who holds its permission; the packaging engineer is why work type is derived
independently of priority bucket (FR-21); the security reviewer is why FR-17 keeps KEV
membership from being averaged into severity. No fourth persona was invented to look
thorough.

The NFRs are the clearest evidence against boilerplate. NFR-3's "A rate-limited source
degrades to stale evidence, never to a clean result" is a product-specific threshold
disguised as an operational note, and it is the thesis restated at the infrastructure
layer. NFR-9's carve-out on internal usage fields is specific to this data. The
counter-metrics are the strongest section in the document: SM-C1 names the product's own
primary failure mode ("Driving this up by resolving `unknown` or `unmapped` into clean is
the primary failure mode of the entire product") and SM-C2 pre-empts the obvious gaming of
SM-3. That is not furniture.

### Findings

- **low** SM-C3 counterbalances a capability that is out of MVP scope (§8) —
  natural-language answer volume counterbalances SM-2, but FR-33 – FR-35 are explicitly
  post-MVP per §7. The metric cannot be read at MVP. *Fix:* mark SM-C3 as applying from
  the `EP-NL` phase.

## Strategic coherence — strong

There is a thesis and the features serve it. The arc is: evidence must be attributable, so
it is append-only and timestamped (FR-36 – FR-39); attribution is worthless if absence
reads as cleanliness, so `not_applicable`, `unknown`, `not_found`, `error` and clean are
five separate states that "No rollup, view, export, or generated answer collapses"
(FR-6); and derived judgment must be reproducible, so policy is versioned and replayable
(FR-22). Every feature group traces back to one of those three. The MVP scope kind is
coherently a platform, and §7's scope logic matches — the natural-language capability is
cut not because it is hard but because "There is nothing to govern, cite, or explain
until" the evidence store and policy engine are trustworthy.

Success metrics validate the thesis rather than measuring activity, and each names the FRs
it validates — SM-2's "zero findings present an unknown as clean" is the thesis stated as
a measurement. Counter-metrics are present and sharp (see above).

The one soft spot: SM-3, SM-4, SM-5 and SM-6 are binary capability demonstrations rather
than metrics, with no measurement cadence or owner. For an internal platform that is a
defensible shape, but they will not tell anyone whether the system is degrading after
launch.

### Findings

- **low** Four of six success metrics have no cadence or threshold (§8) — SM-3, SM-4,
  SM-5, SM-6 are pass/fail acceptance demonstrations. Only SM-1 (95%) and SM-2 (zero)
  carry a measurable bar. *Fix:* state that SM-3 – SM-6 are acceptance gates measured once
  at release, or give them a recurring measurement.

## Done-ness clarity — thin

Judged FR by FR, this is well above the norm. The consequence blocks are real acceptance
criteria: "A resolution never overwrites a `verified` confidence with a lower one"
(FR-2), "The write is rejected without a reason" (FR-3), "Each monitored channel produces
its own observation; channels are never merged" (FR-10), "Re-running a stated version
against a stated cut-off reproduces identical results" (FR-22), "An answer never states a
figure not present in a cited row" (FR-34). I searched specifically for "handles X
gracefully" / "reasonable" / "user-friendly" and found none. FR-28's split between
liveness and readiness ("Readiness fails when a required dependency is unavailable;
liveness does not") is the kind of precision most PRDs skip.

The dimension is nonetheless thin, because the gaps are located exactly where story
creation will hit them first, and because the PRD's own artifacts contradict each other on
the point that most constrains `EP-APP`.

The write path is the worst of it. FR-3 states the override "is the only human write into
governed data in v1"; §6 states "No write API beyond the override in FR-3"; FR-27 states
"The API is read-only in v1 except for the override write in FR-3". But FR-25 requires
"Acting on an item records who acted, when, and the resulting state", FR-32 requires
"every queue action (FR-25) record actor, timestamp, and prior state" — which is an
audited write by definition — UJ-1 has Dana marking a finding for remediation and routing
it to another role's queue, and UJ-2 has Ravi drafting a tracking issue and recording its
URL against the package. That is at least four human write paths against three assertions
that there is one. Either "governed data" is narrower than it sounds and the PRD must say
what it excludes, or the assertion is wrong.

Second, Appendix A.3 lists eleven derived statuses "Computed by policy (§4.3)", but §4.3
produces only nine of them. **Feedstock presence** and **remediation readiness** have no
owning FR. Both are load-bearing: feedstock presence is what UJ-2's whole report filters
on, and remediation readiness is the judgment UJ-1 turns on ("The fixed range is already
published to conda-forge, so they mark the finding for remediation"). Nothing in §4.3
derives "a fix exists on a monitored channel".

Third, FR-20 assigns `P1`–`P10` "by top-down first-match rules" and a "1–100 score from
internal usage signals", and neither the buckets nor the scoring function is defined
anywhere. The consequences make the *output* explainable, which is good, but a story
author cannot build the ruleset. Note the asymmetry: the structurally identical license
policy got Open Question 2, and the work-type set was enumerated as a closed set in
Appendix A.1. Priority got neither. FR-16's "documented release-authority order" has the
same problem — the PRD requires the order to be documented and recorded per package but
never says what it is or defers it.

### Findings

- **high** The "only human write" claim contradicts FR-25, FR-32, UJ-1 and UJ-2
  (§4.1 FR-3, §4.4 FR-25/FR-27, §4.5 FR-32, §6, §2.2) — three assertions of a single write
  path against at least four specified write paths. This is the single most important fix
  before `EP-APP` is planned; whichever way it resolves changes the API contract and the
  authorization model. *Fix:* define "governed data" to mean package identity, evidence and
  policy results (excluding workflow state), then restate FR-3 as "the only human write
  into *evidence-bearing* data", and amend FR-27 and §6 to admit queue-action writes with
  their own role scoping.
- **high** Two Appendix A.3 derived statuses have no producing policy FR (§ Appendix A.3
  vs §4.3) — "feedstock presence" and "remediation readiness" are listed as computed by
  policy; §4.3 contains no FR that computes either, though UJ-1 and UJ-2 both depend on
  them. *Fix:* add a feedstock-presence policy FR (deriving presence / staged-recipe /
  absent from FR-9 evidence, gated on confidence per FR-5) and a remediation-readiness
  policy FR (is a fixed version published on a monitored channel — FR-10 evidence crossed
  with FR-11 fixed ranges).
- **high** The `P1`–`P10` bucket ruleset is undefined and undeferred (§4.3 FR-20) — no
  bucket semantics, no scoring function, no Open Question, while the comparable license
  policy has Open Question 2 and the work-type set is enumerated in Appendix A.1. Open
  Question 3 asks only where the usage *fields* come from, not how they combine.
  *Fix:* enumerate the ten buckets as a closed set the way work types are, or add an Open
  Question that blocks `EP-PRIORITY` on the ruleset and the scoring function.
- **high** UJ-2's tracking-issue draft and tracking-URL recording have no FR (§2.2 UJ-2 vs
  §4.4) — "They draft a tracking issue from the package detail view … and the package's
  tracking URL is recorded." Appendix A.1 carries `tracking_title` and `tracking_issue_url`
  and the work-type set includes "file tracking issue", but no FR provides the draft
  composition or the write path, and the write is forbidden by FR-3/FR-27 as written.
  *Fix:* add an FR under §4.4 for issue-draft composition and tracking-URL recording, and
  fold it into the write-path resolution above.
- **medium** FR-16's release-authority order is never stated or deferred (§4.3 FR-16) — the
  policy is required to use "a documented release-authority order recorded per package",
  but the order is not in the PRD, not in Appendix A, and not an Open Question. The stored
  *decision* is testable; the *policy* is not. *Fix:* state the default order and its
  per-package override mechanism, or add an Open Question blocking `EP-CURRENCY`.
- **medium** UJ-1's recollection trigger has no FR (§2.2 UJ-1) — "Dana can trigger a
  recollection instead of acting on it." NFR-6 mentions recollection as async work, but no
  FR grants any role the ability to initiate one, and it is another write. *Fix:* add it to
  FR-25 or the new write-path FR.
- **medium** UJ-2's "feedstock-gap report" is not in FR-26's report list (§2.2 UJ-2 vs
  §4.4 FR-26) — FR-26 lists "weekly feedstock lag", which is currency, not presence. The
  journey's central artifact is reachable only by inference through FR-23 filtering.
  *Fix:* name the feedstock-gap report in FR-26, or have UJ-2 cite FR-23 filtering
  explicitly.
- **low** FR-1's "when derivable" is an untestable escape hatch (§4.1 FR-1) —
  "Cross-ecosystem identifiers (package URLs, CPEs) are recorded when derivable" cannot
  fail a test, because "derivable" is undefined. *Fix:* state the derivation inputs, or
  recast as "records a purl for every package with a resolved ecosystem identity; records
  `not_applicable` otherwise."
- **low** FR-13's "routes to manual review" names no destination (§4.2 FR-13) — three
  queues exist in FR-25; this does not say which receives the unparseable license.
  *Fix:* name the compliance review queue.
- **low** FR-23 does not state that the current-health view is exportable (§4.4 FR-23 vs
  §2.2 UJ-3) — UJ-3 has Sam exporting "the current-inventory view", but only FR-26 (reports)
  carries an export consequence. *Fix:* add the export consequence to FR-23 with the same
  freshness and confidence column guarantee.

## Scope honesty — adequate

Omissions are explicit where they matter most. §6 is only two bullets, but that is correct
behaviour, not thinness — it says so and defers to the brief, and the two it keeps are
precisely the requirement-level ones that bound FRs above ("No automated remediation
triggered by a policy result. FR-25 routes work to a human; it never acts"). §7's
out-of-scope entries each carry a reason, and the non-Python entry is honest about being a
phase boundary rather than an exclusion, matching memlog override 29. The Open Questions
are genuinely open — none is rhetorical, and five of seven name the epic they block, which
is more useful than the brief's undecorated list.

Open-items density is low for the stakes: seven Open Questions and one assumption against
39 FRs on a document that is green-lighting a build. That is the right direction, but the
count is low partly because things that should be open were written as settled — the
priority ruleset, the authority order, the queue-to-role mapping, and the report list in
FR-26 (which appears in no upstream source and is not tagged as an inference). The single
`[ASSUMPTION]` tag suggests under-tagging rather than exceptional certainty.

### Findings

- **medium** FR-26's report list is an untagged inference (§4.4 FR-26) — six specific
  recurring reports appear here with no upstream basis in the brief, addendum or memlog.
  If these were inferred, they need a tag. *Fix:* `[ASSUMPTION: the six recurring reports
  are inferred from the role table; confirm the list with the reviewers who consume them.]`
  and index it in §11.
- **low** Open Question 5 lacks the "Blocks" annotation its siblings carry (§10) — every
  other question names a blocked epic or a timing note. *Fix:* add "Blocks `EP-APP`
  acceptance" or state it is set during architecture.

## Downstream usability — thin

This PRD is chain-top — §0 says it feeds "the architecture and epic-breakdown work that
consumes it" — so this dimension carries full weight. Much of it is deliberately built for
extraction: global stable FR ids, non-positional epic keys, a Glossary declared binding
("Downstream artifacts must use these terms exactly"), and Appendix A placed as evidence
rather than prelude. I verified the mechanics and they hold: FR-1 – FR-39 are contiguous
with no gaps or duplicates; NFR-1 – NFR-13, SM-1 – SM-6, SM-C1 – SM-C3 and UJ-1 – UJ-3
likewise; all 39 FRs are assigned to exactly one epic with no FR orphaned and none claimed
twice; §7's in-scope list covers FR-1 – FR-32 and FR-36 – FR-39 exactly, with FR-33 –
FR-35 correctly the only exclusion; every UJ has a named protagonist carrying their role
inline. Cross-references (FR-31 from FR-25/FR-27, FR-39 from FR-15, Appendix A.1 from
FR-21) all resolve.

Two things pull it to thin. First, the Glossary goes to real trouble to disambiguate
**identity** into package identity and user identity — "'Identity' alone is never used" —
and then overloads **confidence** in exactly the same way without noticing. The Glossary
defines Confidence as the three-value package-identity enum (`verified` /
`inventory-derived` / `unmapped`), but FR-11 records "confidence" on a vulnerability
finding, Appendix A.2 gives `vulnerability_findings` a confidence column, and FR-24 and
FR-26 speak of confidence on evidence rows and export columns. These are two different
scales. A downstream artifact told to use Glossary terms exactly will conflate them.

Second, seven of thirteen NFRs — NFR-1, NFR-2, NFR-3, NFR-7, NFR-8, NFR-9, NFR-11 — appear
in no epic row. §9 assigns NFR-4 – NFR-6 to `EP-APP` and NFR-10, NFR-12, NFR-13 to
`EP-PLATFORM`, which sets the expectation that NFRs are epic-assigned; the omissions then
read as oversight rather than intent. The scale and scheduling NFRs in particular have no
delivery home at all.

Third, the epic dependency column contradicts its own prose. The table has `EP-CURRENCY`
and `EP-SECURITY` depending only on `EP-IDENTITY`, while the note beneath states
`EP-EVIDENCE` "is a dependency of them; it is sequenced first in delivery". Any tool
reading the table gets a dependency graph the document itself says is wrong.

### Findings

- **high** "Confidence" is overloaded exactly as "identity" was not (§3 Glossary vs §4.2
  FR-11, §4.4 FR-24/FR-26, Appendix A.2) — the Glossary binds Confidence to the
  package-identity enum, but vulnerability findings carry an unrelated match confidence.
  *Fix:* split into **package-identity confidence** and **finding confidence** in the
  Glossary, define the second one's scale, and qualify every use — the same discipline §3
  already applies to identity.
- **medium** Seven of thirteen NFRs have no epic (§9) — NFR-1, NFR-2, NFR-3, NFR-7, NFR-8,
  NFR-9, NFR-11 are unassigned while six others are assigned, so the omission reads as an
  error. *Fix:* assign them (NFR-1 – NFR-3 to `EP-CURRENCY`/`EP-PLATFORM`, NFR-7 to
  `EP-PLATFORM`, NFR-8/NFR-9 to `EP-NL`, NFR-11 to `EP-IDENTITY`), or state that NFRs are
  cross-cutting and the listed ones are only those with a primary owner.
- **medium** The epic dependency column contradicts the note below it (§9) —
  `EP-CURRENCY` and `EP-SECURITY` do not list `EP-EVIDENCE` as a dependency, though the
  prose says it is one and must be sequenced first. `EP-APP` likewise omits `EP-EVIDENCE`
  despite FR-23/FR-24 depending on it. *Fix:* correct the column and delete the patch note.
- **medium** The queue-to-role mapping is implied, and its ordering misleads (§4.4 FR-25)
  — "the identity review queue (FR-4), the remediation work queue, and the compliance
  review queue" lists three queues in an order that maps positionally onto §2.1's role
  order as security→identity, packaging→remediation, leadership→compliance. The brief's
  role table and FR-3's override permission imply the opposite pairing for the first and
  third. *Fix:* state the pairing explicitly in FR-25 as a table.
- **medium** The five-state vocabulary is load-bearing but absent from the Glossary (§3 vs
  §4.1 FR-6) — `not_applicable`, `unknown`, `not_found`, `error` and clean drive FR-6,
  FR-7, FR-8, FR-11, FR-13, FR-17, FR-34, FR-38 and Appendix A.3, yet none is a Glossary
  entry and "clean" is never defined at all despite SM-C1 measuring it. *Fix:* add all five
  to §3 with FR-6 as the cross-reference.

## Shape fit — strong

The shape matches the product. This is an internal engineering platform with three
account-holding roles and genuinely differentiated surfaces, so it sits between "capability
spec" and "multi-stakeholder" on the rubric's scale — and the PRD lands there. Three light
UJs, one per role, each with an edge case that carries a real constraint (UJ-2's "an
`unmapped` package never appears in this report, because absence of a feedstock cannot be
claimed for a package whose identity is unresolved" is FR-5 restated as narrative). That is
the right density: enough to force specificity about entry state and where value lands,
per memlog decision 33, without a UX narrative this product does not need.

Nothing is over-formalized. Thirty-nine FRs is proportionate to eight collectors, six
policy areas, three surfaces and an authorization model. The success metrics are correctly
operational rather than user-facing for an internal tool. Appendix A is positioned as
evidence for the requirements rather than a schema masquerading as a spec, and §0 says so.

The brownfield aspect is handled honestly: `EP-PLATFORM` is marked "Largely complete —
imported" so the epic breakdown does not re-plan existing work — though see the
decision-readiness finding about it naming technologies against §0's own exclusion.

## Mechanical notes

- **ID continuity — clean.** FR-1 – FR-39, NFR-1 – NFR-13, SM-1 – SM-6, SM-C1 – SM-C3,
  UJ-1 – UJ-3 all contiguous, unique, no gaps. All 39 FRs assigned to exactly one epic.
  §7's MVP list reconciles exactly against the FR set. All internal cross-references
  resolve.
- **Assumptions Index roundtrip — clean but sparse.** The single `[ASSUMPTION]` at NFR-5
  appears inline and is indexed in §11 with its Open Question link. Nothing is indexed
  that does not appear inline. The concern is under-tagging, not roundtrip failure (see
  Scope honesty).
- **Glossary drift.** Beyond the confidence overload above: §2.1 and the brief use
  "Platform and engineering leadership" while FR-3 and UJ-3 use "platform lead" — the
  Glossary's Role entry does not list the three role names verbatim, so nothing anchors
  them. *Fix:* enumerate the three canonical role names in the Glossary's **Role** entry.
- **Product names in Appendix A.1.** Export columns `JFROG_risk_level`,
  `JFROG_latest_vuln_count` and `OpenTeams_Title` name third-party products in a document
  whose §0 states it "does not decide … which products are adopted". These are almost
  certainly legacy report headings preserved as the export contract the appendix describes,
  but nothing says so, and a downstream reader may take them as adoption. Add a one-line
  note that the `JFROG_*` and `OpenTeams_*` headings are inherited consumer contracts, not
  product selections.
- **UJ protagonists — clean.** Dana (security and compliance reviewer), Ravi (packaging
  engineer) and Sam (platform lead) each carry their role inline; no floating UJs.
- **§10 vs the brief's §8.** Five of the seven Open Questions restate the brief's, which
  §0 says the PRD does not do. This is a net gain, not a defect — the PRD versions add
  epic-blocking annotations the brief lacks — but a half-sentence acknowledging the
  deliberate overlap would keep §0's claim exact. The closing note superseding the README's
  divergent list is a good catch and should be actioned.
- **Required sections — all present** for a chain-top internal platform PRD: vision, users
  with JTBD, glossary, features with testable consequences, cross-cutting NFRs, non-goals,
  MVP scope, success metrics with counter-metrics, epics, open questions, assumptions
  index, data-model appendix.
