# CPM-PLATFORM-S05: A hundred packages, and real advisories behind them

Status: done

Epic: `CPM-EP-PLATFORM` — The service platform

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Asked for
> by the product owner, who named the count and the mixture and then rejected this
> agent's recommendation that the advisories stay fictional. See the epic entry.

## Story

As a reviewer,
I want the demo inventory to look like a real one,
so that what I conclude from these screens is about the design rather than about the
fixture.

## Acceptance Criteria

1. **Given** the demo seeder
   **When** it runs
   **Then** it writes a hundred packages, mixing web frameworks, data science
   packages and ordinary utilities — well known and lesser known — and things
   conda-forge ships that are not Python at all

2. **Given** a package the roster says is vulnerable
   **When** its advisory is recorded
   **Then** the identifier, the severity and the affected range are the ones a real
   advisory database states, and the identifier resolves

3. **Given** a package the roster says is in the KEV catalogue
   **When** its listing is recorded
   **Then** it is genuinely listed and the catalogue date is the one the catalogue
   states

4. **Given** the seeded screens
   **When** they are opened
   **Then** every state `CPM-FR-5` distinguishes appears on more than one row, the
   package table paginates, and the priority buckets the shipped rules can reach are
   reached

## Tasks / Subtasks

- [x] Harvest real advisories from OSV.dev and cross-check CISA's KEV catalogue.
- [x] `config/local_dev/demo_data.py` — the hundred-row roster, `kev_catalogued`,
      `fix_reached`, the two negative Python-readiness kinds, `fixed_range`.
- [x] `tests/unit/test_local_dev_demo_data.py` — nine audits added.
- [x] `tests/integration/test_local_dev_demo_seeding.py` — two unmapped rows, not one.
- [x] `docs/conda-sentinel/running-it.md`, `docs/conda-sentinel/development.md`.

## Dev Notes

**Governed by:** `CPM-AD-2` (the seeder writes evidence, never a verdict),
`CPM-AD-10` (which is why it cannot write one), `CPM-AD-14` and `CPM-AD-25` (identity
arrives through resolution), `CPM-AD-8` (every status on the resulting screens is
concluded by the pass that owns it, at the shipped policy version).

Nothing about how the seeder works changed. It is the same module doing the same
thing to ten times the data: resolve a shell, write evidence, run a real policy pass.

### Where the advisories came from

`https://api.osv.dev/v1/query`, one request per candidate package, keeping the most
recently published advisory that states a severity the shipped
`vulnerability_risk_order` ranks and names a real release on both ends of its range.
Ninety-four candidates were asked; forty-nine had one; twenty-eight are in the roster.

The KEV listing was cross-checked against
`https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`.
**None of the forty-nine Python advisories is in it.** The catalogue holds 1,703
entries and lists software known to be exploited in the wild; the Python library
ecosystem is essentially absent from it. So the one KEV row is `git` —
`CVE-2025-48384`, catalogued 2025-08-25, fixed in 2.50.1 — which conda-forge ships and
which the roster already wanted for the `not_applicable` Python column.

One KEV row out of twenty-eight is not a thin demo. It is what that column looks like.

## Dev Agent Record

### Completion Notes

**Files changed:** `src/config/local_dev/demo_data.py`,
`tests/unit/test_local_dev_demo_data.py`,
`tests/integration/test_local_dev_demo_seeding.py`,
`docs/conda-sentinel/running-it.md`, `docs/conda-sentinel/development.md`.

### Three columns were inert, and only a bigger roster showed it

Each was found by seeding the hundred and reading the resulting distribution — not by
any test, and not visible at ten rows.

**1 — Every vulnerable package landed in `p3`, "no fix is in sight".** The seeder
never wrote `fixed_range` on a vulnerability finding, so `policies/remediation.py`
read no fix, left all four surface columns `not_read`, and concluded `unknown` for
every package. The priority rules `p1` and `p2` turn on that difference and could
never fire.

The fix is that the advisory states one: OSV's `fixed` event is a bare version, which
is the single form the remediation pass can compare. Recording it moved the twenty-
eight from one bucket to three — but only after `fix_reached` was added, because a fix
that has reached only the upstream release is `awaiting_packaging` for all of them.
The field says which surface carries the fixed version, which is an observation; what
it means is still the pass's to decide.

**2 — Every package was ready for Python 3.14.** The seeder wrote
`inferred_compatible` unconditionally, so the product's headline column rendered one
tone across a hundred rows and the `p8` and `p9` rules were unreachable. Two more
evidence kinds — a static assessment that came out incompatible, and a verification
that ran and failed — put six and two packages on the other side.

**3 — Eighty-six of a hundred packages were behind upstream.** The first draft gave
almost every clean package a newer upstream, which is not an inventory anybody has and
made the `behind` tone mean nothing. Rebalanced to 49 behind, 43 current, 7
`not_found`.

### Two priority rules cannot fire, and one of them is a defect

`p4` and `p7` are licence rules and are unreachable by design: `license_rules` is
deliberately empty (PRD Open Question 4).

**`p6` is different.** "Behind upstream, with no conda-forge feedstock" joins
`currency_status = "behind"` with `feedstock_presence_status = "absent"`, and the two
cannot co-occur. A package with no feedstock has `feedstock_status = not_found`;
`not_found` outranks every determinate value in the one precedence order, so the
package's overall currency is `not_found` and never `behind`. Measured on the seeded
inventory: all seven feedstock-absent packages come out `not_found`, none `behind`.

Not fixed here. A priority rule is `CPM-AD-8` policy, and changing one means recording
a new policy version — a decision for whoever owns PRD Open Question 8, not a side
effect of improving a fixture. Reported to the product owner instead.

### The positional columns, and the audit that makes them safe

A hundred rows only stay readable as one line each, so the first three arguments are
positional: **name, upstream, installed**. That is exactly the shape that makes a
transposition easy, and the transposition here is silent — the currency pass concludes
`behind` for a current package and `current` for a behind one, both render perfectly,
and nothing else notices.

`test_no_roster_row_declares_an_installed_version_ahead_of_its_upstream` compares every
parsable pair, and a second case asserts the comparison itself works against a
deliberately inverted declaration — because the first passes on an empty roster, on a
roster of equal pairs, and on one where nothing parsed.

### A smaller thing the roster broke

`detection_method` was chosen by testing the licence string for `" OR "`. True of the
ten-package roster; false of this one, where `tqdm` declares `MPL-2.0 AND MIT` and
`python-dateutil` declares `Apache-2.0 AND BSD-3-Clause`. Both would have been filed
as single SPDX identifiers. Now a compiled pattern over `OR`, `AND` and `WITH`, with a
parametrized case including `BSD-3-Clause-Clear` — where the word is inside an
identifier rather than joining two.

### Verified by opening every screen

Seeded, then signed in as `operations-persona` and opened each page. A hundred rows,
2.0 seconds to seed, and the whole product renders:

```
/conda-sentinel/                             200
/conda-sentinel/packages/                    200   50 rows, paginated (page 2: 50)
/conda-sentinel/coverage/                    200
/conda-sentinel/queues/identity_review/      200    2 items
/conda-sentinel/queues/remediation/          200   28 items
/conda-sentinel/queues/compliance_review/    200   50 items
/conda-sentinel/reports/kev/                 200    1 row   (git)
/conda-sentinel/reports/python-314/          200    8 rows
/conda-sentinel/reports/feedstock-lag/       200   55 rows
/conda-sentinel/reports/licence-exceptions/  200   90 rows
/conda-sentinel/reports/unmapped-identities/ 200    2 rows
/conda-sentinel/reports/stale-evidence/      200    2 rows
```

All seven tones the stylesheet draws appear on page one of the packages table:
`tone-ok`, `tone-warn`, `tone-crit`, `tone-unknown`, `tone-notfound`, `tone-na`,
`tone-plain`.

What the policy run concluded, at `2026.09.4`:

```
vulnerability   advisories_matched 28  no_advisory_matched 69  unknown 3
risk level      critical 2  high 12  moderate 11  low 3
kev             listed 1  not_listed 27  not_established 72
currency        behind 49  current 43  not_found 7  unknown 2
feedstock       maintained 88  absent 7  inactive 5
python 3.14     inferred_ready 59  verified_ready 26  not_applicable 7
                inferred_not_ready 6  verified_not_ready 2
remediation     not_applicable 69  awaiting_packaging 15  awaiting_build 7
                ready 6  unknown 3
priority        p1 6  p2 7  p3 15  p5 4  p8 2  p9 2  p10 21  unknown 43
```
