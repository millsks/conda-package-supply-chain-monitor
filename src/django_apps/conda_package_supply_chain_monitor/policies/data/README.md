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
```

`versions` is the only top-level table, and each entry under it is one policy
version's complete parameter set.

| Key | Required | Meaning |
|---|---|---|
| `feedstock_inactivity_days` | yes | How long a feedstock may go without a push to its repository before `CPM-FR-40`'s policy calls it **inactive**. A positive whole number of days. A feedstock pushed to *exactly* this long before the run's evidence cut-off is still `present_and_maintained`; inactivity begins strictly after it. |
| `vulnerability_risk_order` | no | The severity labels `CPM-FR-17`'s per-package **risk level** is drawn from, **worst first**. A non-empty list of distinct, fixed lowercase strings, each at most 32 characters. Compared case-insensitively against the `severity` a vulnerability finding stored exactly as its source stated it. A version that omits it gets vulnerability rows with **no risk level**, and every other verdict on them is unaffected. |

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

## The operational consequence, stated plainly

**A policy run must name a version this file records, or every package fails.**
`CPM-AD-23` contains the refusal to one package at a time, so the run finalizes
`partial` or `failed` and the ledger says how many — but a run at an unrecorded
version accomplishes nothing. Check this file before enqueuing `cpm.policy.run`
with a new version string.

## Both shipped parameters are provisional

PRD Open Question 10 asks what the inactivity threshold should be, and this
component has not answered it. `CPM-FR-17` names a risk level and the PRD seeds
no severity scale for it, and this component has not answered that either. Both
values in the file are starting points with their reasoning written beside them —
the file is the only place either appears, so this document does not repeat them
— and both are changeable by review **without a code change**, which is the whole
point of the mechanism.

Nothing in the codebase depends on it: the pass reads whatever this file records,
each derived row stores the threshold it applied, and both test tiers
deliberately use a different number so that a pass which had gone back to reading
a constant would fail.
