# Extraction: epics.md — CPM-EP-APP

## The eight stories

| Story | Title | Satisfies | Governed by |
|---|---|---|---|
| S01 | Pagination and role checks, configured once | FR-31, NFR-4, NFR-11 | AD-12, AD-13 |
| S02 | The current package-health view | FR-23, NFR-5 | AD-10, AD-11, AD-12, AD-24 |
| S03 | Package detail traced to its evidence | FR-24 | AD-10, AD-24 |
| S04 | One workflow table keyed on a stable finding key | model half of FR-25 | AD-22, AD-23 |
| S05 | Three role-scoped queues over one table | surface half of FR-25 + FR-4 | AD-13, AD-22 |
| S06 | The recurring operational reports | FR-26 | AD-11, AD-24 |
| S07 | A governed, documented API | FR-27 | AD-9, AD-10, AD-12, AD-13, AD-24 |
| S08 | Long work leaves the request | NFR-6 | AD-9 |

8 stories, 32 acceptance criteria (epics.md:1708).

### Story statements (verbatim)

- **S02** (L1384): As a platform lead, I want to browse, filter and sort current package health across the inventory, So that I can see the whole estate and narrow to what matters.
- **S03** (L1418): As a security reviewer, I want every status on a package traced to the evidence that produced it, So that I can check the reasoning rather than trusting the conclusion.
- **S04** (L1441): As a security reviewer, I want a finding I have accepted to stay accepted after the next collection, So that my decisions are not silently undone by re-observation.
- **S05** (L1469): As a packaging engineer, I want my own queue ranked by risk, So that I work the highest-impact item first without seeing another role's work.
- **S06** (L1502): As a platform lead, I want the recurring reports produced from the same evidence the views use, So that a report and the application never disagree.
- **S07** (L1526): As an integrator, I want the same reads available over HTTP with a published schema, So that automation uses the product's own contract rather than the database.
- **S08** (L1560): As a security reviewer, I want a recollection or a large export to run in the background, So that the page returns instead of hanging on a rate-limited third party.

## Hard UI constraints (non-negotiable, these bind the spines)

### Status rendering — the central rule
- L1403-1405: `unknown`, `not_found`, `not_applicable`, `error` render **as themselves, never as blank or as clean**.
- L1519: a status value is emitted verbatim; **blank is reserved for a field that has no value**.
- L1550-1553 (APP.07-API-001): serialized verbatim as its `OutcomeState` value, never `null`, `""`, or a boolean.
- L604: `stale` is never rendered as clean.
- L1492-1495 (APP.05-API-002): feedstock-gap surface excludes `unmapped`, which report `unknown` rather than absent.
- L155 (OQ 3): `apps`, `platforms`, `downloads`, `versions` stay **blank until a source supplies them — blank means missing, never zero, never estimated**.

### Health view (S02)
- Carries every derived status **with the observation timestamp behind each** (L1392).
- **States when the underlying rollup was last recomputed** (L1393).
- Filters on: derived status, confidence, priority bucket, work type (L1401).
- 10,000 packages, always paginated (L1395-1397).
- p95 latency budget enforced + a test bounding query count (L1407-1410).

### Detail view (S03)
- Each status links to evidence rows with **source, observation timestamp, confidence** (L1424).
- Identity provenance and confidence shown, **including any override and the reason recorded with it** (L1428).
- **Superseded evidence remains reachable**; current values shown without deleting history (L1432).

### Queues (S05)
- Three queues are **filtered views over one table**: identity review, remediation, compliance review (L1477).
- Ranked by **priority bucket, then score**; usage breadth is the score input for identity items (L1481).
- A role opening another role's queue is **refused and the refusal logged** with acting user identity (L1483-1486).
- Advancing an item records **who acted, when, and the resulting state** (L1489).
- Routing changes the item's queue field; **no second item is created** (L1460-1462).
- Workflow items keyed on a **re-observation-stable finding key**, never an evidence row id (L1450). An accepted finding does not reappear after re-collection (L1454).

### Reports (S06) — the six
1. daily KEV
2. weekly feedstock lag
3. Python 3.14 readiness
4. licence exceptions
5. unmapped identities
6. stale-evidence and collector failures

- Every report **states the evidence cut-off and the policy version** it came from (L1512-1514).
- Exports carry **the same freshness and confidence columns the application shows** (L1518).
- Export column headings applied by the reporting layer; no model field is named for one (L694-696).
- Collector failures retrievable **in the application layer, not only from logs**; each exposes error detail and `trace_id` (L608-609).
- The coverage view must show a killed worker's run row as `running` (L523-525).

### Async boundary (S08)
- Outbound call, collector, policy pass, or export beyond the row cap → **enqueued, request returns an in-progress state** (L1566).
- Row cap from **one settings constant** used by every export path (L1570).
- Everything else — reads of derived state/evidence, writes of workflow state or an override — is synchronous (L1574-1576).

### Writes
- The only v1 writes: **package-identity override** and **queue actions** (L1541-1544).
- No endpoint writes evidence or a derived status.
- Queue actions write **workflow state**, a separate class from governed reference data; never alters package identity or evidence beneath it (L45).

## Deferred surfaces (why UX must exist before APP)

| Deferring story | Defers | To |
|---|---|---|
| CPM-IDENTITY-S04 | queue table + workflow state | CPM-APP-S04 |
| CPM-IDENTITY-S04 | the worked queue surface completing FR-4 | CPM-APP-S05 |
| CPM-IDENTITY-S06 | supplies data so S04's queue and APP surfaces "have data to render" | CPM-EP-APP |
| CPM-EP-NL | whole epic | CPM-EP-APP |

CPM-IDENTITY-S04 goal, L756: "So that the review surface has something correct to render **before the surface exists**."

## The UX-gap statements

- Frontmatter L10: `uxDesignContract: none`
- L17-19: "There is no UX design contract; CPM-EP-APP builds views against the PRD's user journeys and the spine's surface rules alone."
- L161-169 (### UX Design Requirements): "None. No UX design contract exists for this product... **This is a known gap, not an omission.** See the open question raised at the end of this step."
- L327-328 and L1351-1352 repeat: presentation is the implementer's.

**DEFECT FOUND:** L161-169 points at "the open question raised at the end of this step." No such open question exists. The Open Question table (L151-159) has no UX entry. The gap was flagged and the flag went nowhere.

## Open questions that block numbers (do not invent)
- **OQ 5** (L156): the p95 latency budget and the sync export row cap. S02 and S08 enforce that a value exists; they do not choose it.

## Terminology trap
The "three queues" at L535-563 are **Celery** queues (`collect`, `policy`, `verify`) in CPM-EVIDENCE-S04 — unrelated to the three **UI** queues in CPM-APP-S05.
