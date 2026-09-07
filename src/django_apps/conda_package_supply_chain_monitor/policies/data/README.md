# The policy parameters

The versioned rule data a policy pass applies (`CPM-AD-8`, `CPM-FR-40`). One
reviewed TOML file, `policy-parameters.toml`, read by `policies/parameters.py`
and keyed by the **policy version the run declares**.

It ships inside the wheel, beside the module that reads it, exactly as
`collectors/data/`'s watchlist does — and for the same reason: a path computed
from `BASE_DIR` works in a checkout and fails in a container.

The contract cannot live in the file itself, because an unrecognised key is a
refused file rather than a comment. It lives here.

## Why a file

A **setting** would be per-deployment rather than per-version, so two components
running the same policy version could disagree about what that version means. A
**database table** would be a write path nothing audits: a verdict would change
because somebody ran an `UPDATE`, with no diff and no reviewer. `CPM-AD-14` makes
reviewed reference data in the repository this product's governed shape for
exactly this, and a change here is a pull request.

## The shape

```toml
[versions."<policy version>"]
feedstock_inactivity_days = <positive whole number>
vulnerability_risk_order = ["<severity>", "<severity>", ...]
license_rules = [{ expression = "<SPDX expression>", disposition = "<disposition>" }]
```

`versions` is the only top-level table, and each entry under it is one policy
version's complete parameter set.

| Key | Required | Meaning |
|---|---|---|
| `feedstock_inactivity_days` | yes | How long a feedstock may go without a push to its repository before `CPM-FR-40`'s policy calls it **inactive**. A positive whole number of days. A feedstock pushed to *exactly* this long before the run's evidence cut-off is still `present_and_maintained`; inactivity begins strictly after it. |
| `vulnerability_risk_order` | no | The severity labels `CPM-FR-17`'s per-package **risk level** is drawn from, **worst first**. A non-empty list of distinct, fixed lowercase strings, each at most 32 characters. Compared case-insensitively against the `severity` a vulnerability finding stored exactly as its source stated it. A version that omits it gets vulnerability rows with **no risk level**, and every other verdict on them is unaffected. |
| `license_rules` | no | `CPM-FR-18`'s licence policy: one table per rule, each declaring exactly `expression` and `disposition`. `expression` is a normalized SPDX expression as `license_findings.normalized_license` stores it, non-blank, at most 2048 characters, spelled as SPDX spells it; the match case-folds both sides and is over the **whole** expression. `disposition` is one of `allowed`, `restricted`, `forbidden`. May be empty or omitted, and **is empty in every shipped version** — see below. |

What counts as recipe activity is **not** a parameter. `CPM-CURRENCY-S03` fixed
it — a push to the feedstock repository — and the collector records the instant.
This file only says how long a gap has to be.

### `vulnerability_risk_order` is optional, and a version that omits it still runs

It is the one key an entry may legitimately omit, and the asymmetry is
deliberate. `CPM-SECURITY-S04` added the key after versions had already been
recorded, and an old entry has to keep saying what it said or `CPM-FR-22`'s
replay of a run at that version stops working. So an entry without it **parses**,
and a run at that version writes a complete `package_vulnerability` row: the
status and the KEV membership are derived exactly as they would be otherwise —
neither reads this parameter — the **risk level is blank**, and the row's
`detail` says the version records no order.

**Nothing fails, and an earlier version of this document said otherwise.** It
claimed the pass refused per package so that "only this domain's rows" were lost.
That was wrong twice over: `CPM-AD-23` puts one *package* in a transaction rather
than one *pass*, so a refusal there rolled the currency and feedstock rows back
with it — and since the condition holds for every package, the whole run
finalized `failed` and wrote nothing at all. That destroyed the currency and
feedstock replay of every run recorded at such a version while protecting no
vulnerability replay, because no run at one ever carried a vulnerability verdict.

A **malformed** order is a different thing and is still refused, at the read,
naming this file: see the editing rules below. There is no default risk level and
there must not be one — a blank is a missing measurement, never a low one.

The practical consequence: **enqueue a policy run at a version that records this
key** if you want risk levels. A run at an older version is complete in every
other respect.

### The risk level is a selection, never an arithmetic

A package's risk level is the **worst-ranked severity among the advisories
matched to it** — the first entry of this list that any matched finding's
severity names. A matched advisory whose severity this list does not name, or
whose source stated no severity, contributes nothing to the ranking; a package
whose matched advisories name none of these labels reads no risk level at all,
and the derived row's `detail` says so.

**Never add a KEV label to this list.** `CPM-FR-17` requires that KEV membership
stay distinguishable and never be averaged into severity, and the derived row
carries it in a stored column of its own. A `"kev"` entry here would be exactly
the collapse the requirement forbids — and the pass reads this order only over a
finding's own stated severity, so such an entry would simply never match
anything while looking to a reviewer as though it did.

### `license_rules` ships empty, and empty is the answer

`CPM-FR-18` gives licence compliance to a versioned policy. **Which licences are
allowed is PRD Open Question 2**, which the PRD names as unanswered and as
blocking `CPM-EP-SECURITY`, so `CPM-SECURITY-S05` shipped the mechanism and the
schema with no allow entries and no deny entries. Every shipped version records
either no rule set at all or an explicitly empty one, and the two mean the same
thing.

What that produces, on every package, today:

* a package whose licence this run **established** — a channel stated one and
  `collectors/spdx.py` normalized it — reads **`manual_review`**, and the row's
  `detail` says the version records no rule set;
* a package whose licence it did **not** establish — no evidence at the cut-off, a
  channel that stated none, one that stated something this product will not
  normalize without guessing, one that could not be read, or a sweep in which no
  monitored channel serves the package at all — reads **`unknown`**, and the row
  says which. A *single* channel that does not serve the package is not one of
  these: an absence from one channel has not disagreed with what another channel
  stated, so it takes no part in the reduction;
* **nothing reads `allowed`.**

That is not a degraded mode. It is the correct answer to "no licence policy has
been decided", and it is exactly what `CPM-SECURITY-S03`'s AC 2 already promised
would happen to a licence this product cannot judge.

**This is deliberately unlike `vulnerability_risk_order`, which ships a
provisional value.** There the PRD named a risk level and simply seeded no
thresholds, so a starting point stated as one in the file is a reviewable list
rather than a claim about any package. Here the PRD names the *decision itself*
as open, and a "conservative starting point" or a list of permissive licences
"everyone agrees on" would be this component deciding a compliance question it
was told not to decide — in the one direction that looks like good news.

**`allowed` is never a default and never an absence.** It is reachable only from
a rule that names a licence and permits it, and that is held in three places
rather than one: the pass returns a rule's own recorded disposition and has no
branch that spells `allowed`; the precedence order ranks `allowed` last, so a
reduction over several channels cannot reach it while any of them said anything
else; and `package_license` carries a check constraint requiring an `allowed` row
to name the rule that produced it, so such a row is refused by the database
rather than merely avoided by the pass.

**A compound expression is matched whole, and `AND` is decomposed only to
restrict.** `MIT OR Apache-2.0` is one expression, and deciding which of two
differently-ruled licences a package took is a compliance judgement rather than a
string operation. A rule naming `MIT` does not reach it; a rule that should cover
it names it in full; and an unmatched disjunction reaches `manual_review`, which
for a disjunction *is* the conservative direction, because the permission is
withheld.

A conjunction is not the same, and calling both cases conservative was wrong.
`MIT AND GPL-3.0-only` binds both sets of obligations at once, so a rule
forbidding `GPL-3.0-only` forbids the compound — and left matched-whole-only it
would read `manual_review`, which ranks *below* `forbidden` and below `unknown`.
So where no rule names a conjunction whole, a rule naming one of its operands
`forbidden` or `restricted` decides it, the least permissive one winning, and the
row's `detail` says which operand and why.

**This never runs the other way.** A rule allowing one operand does not allow the
conjunction: `allowed` still requires a rule naming the whole expression, so no
amount of decomposition can permit anything.

**A rule may not say `manual_review`.** That is what a licence no rule names
already reaches, so a rule stating it would be a rule saying nothing. Nor may a
rule state a sentinel: no rule can make a licence un-established.

**Adding rules is a new `[versions."..."]` entry, never an edit.** A run recorded
while the rule set was empty must keep replaying to `manual_review`
(`CPM-FR-22`), and the same expression may read `manual_review` at one version
and `forbidden` at the next — which is the whole of AC 2 and is why every
`package_license` row copies the policy version that produced it.

**A version's policy version string is the operator's, not this component's.**
`CPM-AD-8` makes the version the identity of the *rule data*, so the strings here
are whatever review calls its rule sets. The shipped entry uses a year-month
form; nothing enforces that.

## Editing

The whole file is validated at the first read in a process, and every refusal
raises `ImproperlyConfigured` naming this file and the fault.

**Changing a threshold means adding a version entry, not editing a number.**
That is the rule, and it has one exception: a version no run has ever recorded
may be edited in place, because there is nothing to keep replayable. Once a run
has been recorded at a version, that version's entry has to keep saying what it
said — `CPM-FR-22`'s replay reproduces a recorded run's output, and it can only
do that while the rules it applied are still readable. Editing in place does not
fail loudly; it silently rewrites what every past run at that version meant.

Either way it is a change to *this file* and nothing else. No code changes, no
constant moves, and no test asserts the number.

* **An unrecognised key is refused, not ignored** — a top-level key other than
  `versions`, or a parameter this table does not define. A silently dropped key
  is a reviewer who believes they changed a verdict.
* **A missing, non-integer, boolean, non-positive or absurdly large threshold is
  refused.** No value is repaired and none is defaulted.
* **A risk order that is not a list, is empty, or holds an entry that is not a
  distinct, non-blank, untrimmed-free, lowercase string of at most 32 characters
  is refused.** Every fault in the list is reported at once, so correcting one
  entry at a time does not mean reading the file four times. A version that means
  to rank nothing **omits the key**; an empty list is refused, because it would
  produce a blank risk level for every package and read exactly like a source
  that states no severities.
* **A licence rule set that is not a list, or that holds an entry which is not a
  table declaring exactly `expression` and `disposition`, is refused.** So is an
  `expression` that is not a string, is blank, carries surrounding whitespace or
  is longer than 2048 characters; an `expression` that **`collectors/spdx.py` can
  never produce** — `GPL-3.0`, `GPLv3`, `AGPL-3.0`, anything with `WITH`,
  parentheses, mixed operators or a doubled space — because such a rule matches no
  row this product can ever write, forbids nothing, and leaves every package it
  was meant to cover reading `manual_review`, which is indistinguishable from "no
  rule covers this"; a `disposition` that is not one of `allowed`,
  `restricted`, `forbidden`; and **two rules naming the same expression**,
  whether or not they agree — a licence one rule allows while another forbids it
  has no verdict at all, only whichever rule a reader stopped at, and which of
  two compliance decisions stands is a reviewer's to state. Every fault in the
  set is reported at once. An **empty** list is *not* refused: it is the shipped
  state and means the same as omitting the key.
* **A version key that names nothing, or that carries surrounding whitespace, is
  refused.** The lookup is exact and the run ledger refuses a version naming
  nothing, so such an entry could never be reached by any run.
* **A policy version with no entry here is refused.** There is no fallback, and
  there must not be one: a defaulted verdict is indistinguishable from a reviewed
  one in every report that reads it.
* Save as UTF-8. TOML is UTF-8 by specification.

## Two things a change does not do by itself

**It does not take effect in a running process.** The file is read once per
process, on purpose: `CPM-AD-8` makes one policy version mean one rule set, and a
file re-read per package would let an edit part-way through a run judge half the
inventory under one threshold and half under another. So a corrected file takes
effect at the next process start — which shipping a new artifact already is. This
is deliberately unlike `collectors/data/`'s watchlist, which is re-read on every
sweep because an operator corrects it between them.

**It does not update the suite's own version constant.** Adding or renaming a
version here obliges an edit to `tests/passes.py`'s `A_RECORDED_POLICY_VERSION`
**only if you removed or renamed the version that constant names**. Three
integration modules execute real policy runs at it, and each of them would fail
every package if it stopped being recorded. Adding a *new* version beside it
needs no test change at all, which is the ordinary case; `CPM-SECURITY-S04`
moved the constant to `2026.09.1` anyway, so that the version the suite runs at
records a *complete* set for every adopted pass and the cases about risk levels
have one to draw from — not because a run at `2026.09` fails, which it does not.

`CPM-SECURITY-S05` added `2026.09.2` and **did not** move the constant, which is
the ordinary case and is worth stating because the previous paragraph records the
exception. `license_rules` is optional, and an absent key and an empty list mean
the same thing, so the licence pass derives exactly the same rows at `2026.09`,
`2026.09.1` and `2026.09.2`: `manual_review` for every package with an
established licence, `unknown` for every package without. There is nothing an
older version cannot express, so nothing obliged the suite to move.

## The operational consequence, stated plainly

**A policy run must name a version this file records, or every package fails.**
`CPM-AD-23` contains the refusal to one package at a time, so the run finalizes
`partial` or `failed` and the ledger says how many — but a run at an unrecorded
version accomplishes nothing. Check this file before enqueuing `cpm.policy.run`
with a new version string.

## Two shipped parameters are provisional, and one is empty

PRD Open Question 10 asks what the inactivity threshold should be, and this
component has not answered it. `CPM-FR-17` names a risk level and the PRD seeds
no severity scale for it, and this component has not answered that either. Both
values in the file are starting points with their reasoning written beside them —
the file is the only place either appears, so this document does not repeat them
— and both are changeable by review **without a code change**, which is the whole
point of the mechanism.

`license_rules` is the third and it is not provisional: it is **empty**, because
PRD Open Question 2 names the licence decision itself as unanswered and blocking,
and a provisional allow list would be a compliance claim rather than a starting
point. The section above says what empty produces and what review writes to
change it.

Nothing in the codebase depends on it: the pass reads whatever this file records,
each derived row stores the threshold it applied, and both test tiers
deliberately use a different number so that a pass which had gone back to reading
a constant would fail.
