"""Which of a package's advisories are known to be exploited, and what "we had nothing to ask" looks like.

`CPM-FR-12`: cross-reference vulnerability findings against the KEV catalog, so
that "a KEV finding links to the vulnerability finding it derives from and records
the catalog date added". This module is that collector, the second surface
`CPM-EP-SECURITY` records, and the seventh collector this component runs.

**This collector reads another collector's evidence table, and that is an
exception `CPM-AD-7` does not grant.** The rule says a collector "writes its own
evidence table plus its run-ledger row, and reads only `identity`. It never imports
another collector, never reads another collector's evidence table". This one reads
`vulnerability_findings`. `CPM-SECURITY-S02`'s Spec Change Log records why the
alternatives are closed, what is taken and what is not, and hands the judgement to
review; **that record lives outside the code** and this docstring is the pointer to
it. What is taken is narrow -- **one table, read-only, reached through
`collectors/models.py` rather than by importing the sibling collector, and never
written** -- and the exception is licensed by an object rather than by this
paragraph: `tests/unit/django_apps/test_collector_base_audit.py` carries
`MODULES_PERMITTED_TO_READ_ANOTHER_COLLECTORS_EVIDENCE`, sweeps every registered
collector's module in both directions, and fails when a second collector takes the
same read or when a licensed module stops needing it.

**The read couples this module to that table's *schema* as well as to its rows.**
`_column_width` reads `VulnerabilityFinding.advisory_id`'s width to bound an
identifier a catalog states, because that is the column an identifier is compared
against. That is a second kind of dependency and it is named in the Spec Change Log
beside the first.

**Which KEV source is read is not decided here, and no source ships.** PRD Open
Question 1 -- which advisory and KEV sources are available and licensed -- is
unresolved and explicitly blocks this epic. So what ships is the *mechanism*: the
source is a declared adapter at the collector base's transport seam (`CPM-AD-27`,
`CPM-AD-29`), this module holds the one slot it is declared in, and this component
declares nothing.

**It is a second source and not a second use of the first.**
`collectors/advisories.py` holds the advisory slot and this module holds the KEV
slot; the two are declared independently, withdrawn independently, and refused
independently. An operator who declared an advisory source and no KEV source gets
advisory findings and no cross-references, which is a state worth being able to be
in: a catalog and an advisory database are different products with different
licences.

**The determinate values are `listed` and `not_listed`, and neither is `ok`.** On a
security table a determinate row is the alarming case, and `core`'s single
precedence order ranks `ok` best of five while `CPM-AD-24` carries a state's value
verbatim onto every read surface -- so a table using `ok` for "this advisory is
being used against people" would render exactly those packages as the clean ones,
and `CPM-UJ-1`'s queue, which opens on KEV findings, would sort them last. That is
the correction `CPM-SECURITY-S01`'s review forced on its sibling table; it is made
here by construction rather than by patch. `collectors/outcomes.py` composes
`KevOutcome` and argues both values.

**`not_listed` is claimed only where it can honestly be established.** An advisory
identifier is matched against the catalog's own identifiers *and the aliases the
catalog states for them*, folded for case. Where that finds nothing, one more
question is asked before the reassuring value is written: does the catalog state
any advisory under this identifier's own *scheme*? A catalog of CVE identifiers has
nothing to say about a `GHSA-` or `PYSEC-` finding it never had the vocabulary to
list, and recording `not_listed` there would be an established negative the run did
not establish -- permanently, about whether something is being exploited. So a
scheme the catalog does not use produces `unknown` and says so. `_scheme_of` is the
rule and it is a prefix convention rather than a registry: a catalog whose
identifiers carry no scheme prefix at all matches nothing, which fails toward
`unknown` rather than toward a clean-looking answer.

**Only the newest matched finding per advisory, and only while it is still
current.** Evidence is append-only and re-observation inserts (`CPM-AD-2`), so a
package accumulates many rows per advisory; the answer is the last one, ordered by
observation instant then primary key so a replay is reproducible (`CPM-FR-22`).
And it is bounded in time: a matched finding older than this collector's own
freshness target is *stale* rather than current, and cross-referencing it would
keep an advisory alive for the life of the package -- because the sibling collector
records "nothing matched today" as one row naming no advisory, so nothing there
ever retires an advisory. The bound is what retires it, it is what keeps the read
and the row count bounded, and a run that excluded anything says so on every row it
writes.

**Only `matched` findings are current.** A vulnerability row carrying `unknown`,
`error` or `not_found` names no advisory at all -- the table's own constraint makes
sure of it -- so there is nothing in one to cross-reference. One that carries only
whitespace is refused rather than cross-referenced: that constraint tests for the
empty string, so a blank-looking identifier reaches here, and answering `not_listed`
about it would be the reassuring value again.

**A package with nothing to cross-reference writes one row carrying `unknown`, and
the row says which of four things happened.** No KEV question could be asked
because no advisory source is declared at all; the advisory collector has not
observed this package yet; it observed it and matched nothing; or everything it
matched is now stale. `CPM-FR-6` exists to keep those apart, and only the third is
a statement about the package rather than about this product.

**And it is why the sweep offers every package.** The `unknown` row is only worth
writing if a *scheduled* run writes it, so a selection narrowed to packages that
already have findings would produce exactly the silence above.
`CPM-SECURITY-S01` was patched for that defect in its own selection.

**The call to the declared adapter is made even when there is nothing to
cross-reference, and the row does not pretend otherwise.** `core/collection.py`
charges the allowance and calls the transport before `translate` is reached, and
the only call-free path it offers writes `not_applicable`, which this table refuses
outright -- so what this module can control is that no *answer* is read, and it
does: `translate` returns the `unknown` row without touching the payload, so no
catalog document is parsed and nothing a source said can influence a row about our
own evidence. `CPM-SECURITY-S01` shipped a row denying a call it had made and was
patched for it.

**The document contract is this module's**, because no source ships to define one.
`catalog_in` is what an adapter's payload must decode to, and it refuses rather
than reads around: an unreadable or self-contradicting catalog is a source whose
shape this collector does not understand, and reading it for whatever still parses
would record that an advisory is *not* known-exploited because the entry naming it
was in a shape the reader skipped.

**A date the collector cannot read is a blank date and a sentence, not a refusal.**
That is the one place this module reads past something it did not understand, and
it is deliberate: the fact `CPM-FR-12` is about is the *link*, and discarding a
whole catalog because one entry's date was malformed would lose every
cross-reference for every package to protect a secondary field. Blank means missing
(PRD Appendix A.1), never guessed, and `detail` says which of the three ways it is
blank -- stated as none, unreadable or naive, or outside the range a stored instant
may take.

**The pure functions are the whole of what this module decides about a document.**
`catalog_in` and `cross_reference` take data and return data, reachable with no
database, no socket and no clock (`CPM-AD-27`). `current_findings` is the one
impure read, named so an audit and a reader can both find it in one place.

**The `error` and `not_found` rows the base writes go through `sentinel_evidence`,
and this module invents neither.** The base decides which sentinel and that there
is always one (`CPM-NFR-3`); this module decides what a row in `kev_findings` looks
like, and refuses a state it has no row shape for -- which here includes `unknown`,
because an `unknown` row is `translate`'s to write with the reason the run actually
established, and `not_applicable`, because any package at all may have an advisory
against it. `sentinel_evidence_rows` is **not** overridden: this collector observes
one surface per package, so one sentinel row is the whole of what any sentinel path
owes, and the base's default is exactly that.

## What a KEV source adapter must do, beyond satisfying `Transport`

`Transport` is `runtime_checkable`, so `isinstance` sees one method *name*.
Everything else an adapter owes is a contract this module states and cannot check.

**The locator it is handed names the catalog, and it is the same string every
time.** The KEV catalog is one document about advisories rather than a question
about a package, so there is no per-package locator to build -- what varies between
runs is which of *our* findings are cross-referenced against it, and that is this
product's own evidence rather than anything an adapter could be told. The scheme is
opaque on purpose: the adapter already knows which catalog it reads.

**It answers with a JSON document in this collector's own schema.** A top-level
object carrying `entries` (a list, optional) and **no other field** -- an undefined
one is refused rather than dropped, so a source that grows a truncation flag fails
loudly instead of being read as a catalog that lists nothing. There is deliberately
no document-level `detail`: a catalog says nothing about our package, so such a
field would have no row to land on but every one of them. Each entry carries
`advisory_id` (required, non-blank), an optional `aliases` (a list of the other
identifiers the same advisory is issued under), and an optional `date_added` (an
ISO-8601 string carrying an offset, or null). Every value must fit its column and
carry no control character. `catalog_in` is the whole of the rule and its refusals
name what was wrong.

**Stating aliases is what makes `not_listed` trustworthy.** An adapter reading a
catalog that publishes only CVE identifiers should say so by stating them; one
reading a source that knows a CVE's GHSA and PYSEC spellings should state those as
aliases, because a finding recorded under one of them otherwise reads as an
advisory the catalog does not list.

**It sets `found` itself.** `False` means the *catalog locator* does not exist,
which this collector records as `not_found` with a caveat saying it is a withdrawn
or misconfigured source rather than a package with nothing exploited against it,
and which emits `CATALOG_ABSENT_EVENT` so an operator hears about it once per
package rather than only by reading rows. A catalog that exists and lists nothing
is not that: it is a document with no entries, which cross-references every current
finding to `not_listed`.

**It raises `TransportError` and nothing else.** `core/collection.py` catches that
class alone; anything else escapes `collect()` **before any evidence row is
written**, which defeats `CPM-NFR-3`'s "never no row" through the one seam this
story makes pluggable.

**It never answers `not_modified`.** This collector declares `NO_CACHE`, so it
sends no validator and holds no cached body -- a `304` is an answer to a question
nobody asked, and the base fails every such run with no body to read.

**It is asked once per package, for the same catalog, and holding the catalog is
the adapter's business.** The base is per-package (`CPM-AD-7`, `CPM-AD-23`) and
this collector declares no response cache, for the reason `CPM-SECURITY-S01`
declares none: a remembered security answer is the one this product should be
slowest to replay. An adapter reading a large catalog over the network on every
package would spend `CPM-NFR-1`'s inventory doing it; `docs/deployment.md` tells an
operator so.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

import structlog
from django.db import models

from conda_sentinel.collectors.advisories import declared_advisory_source
from conda_sentinel.collectors.agent import USER_AGENT
from conda_sentinel.collectors.models import KevFinding
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.collectors.outcomes import KEV_UNKNOWN
from conda_sentinel.collectors.outcomes import LISTED
from conda_sentinel.collectors.outcomes import MATCHED
from conda_sentinel.collectors.outcomes import NOT_LISTED
from conda_sentinel.core.clock import is_aware
from conda_sentinel.core.collection import NO_CACHE
from conda_sentinel.core.collection import Collector
from conda_sentinel.core.collection import CollectorConfigurationError
from conda_sentinel.core.ledger import current_trace_id
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.rate_limit import RateLimit
from conda_sentinel.core.transport import DEFAULT_RETRIES
from conda_sentinel.core.transport import Transport
from conda_sentinel.identity.models import Package

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Iterator
    from collections.abc import Mapping
    from collections.abc import Sequence

    from conda_sentinel.core.models import AppendOnlyModel
    from conda_sentinel.core.transport import Payload

__all__ = [
    "ADVISORY_ID_FIELD",
    "ALIASES_FIELD",
    "CATALOG_ABSENT_EVENT",
    "COLLECTOR_NAME",
    "DATE_ADDED_FIELD",
    "DOCUMENT_FIELDS",
    "EARLIEST_CATALOG_DATE",
    "ENTRIES_FIELD",
    "ENTRY_FIELDS",
    "KEV_CACHE_TTL",
    "KEV_CADENCE",
    "KEV_DISPATCH_OFFSET",
    "KEV_FRESHNESS_TARGET",
    "KEV_HEADERS",
    "KEV_OBSERVATION_WINDOW",
    "KEV_RATE_LIMIT",
    "KEV_RETRIES",
    "KEV_SOURCE_LOCATOR",
    "KEV_TIMEOUT",
    "LATEST_CATALOG_DATE",
    "MAX_ALIASES",
    "MAX_CATALOG_CHARACTERS",
    "MAX_CROSS_REFERENCES",
    "MAX_ECHOED_CHARACTERS",
    "MAX_ENTRIES",
    "MAX_SENTINEL_DETAIL_CHARACTERS",
    "NOTHING_MATCHED_DETAIL",
    "NOTHING_OBSERVED_DETAIL",
    "NOT_LISTED_DETAIL",
    "NO_ADVISORY_SOURCE_DETAIL",
    "NO_CATALOG_DATE_DETAIL",
    "NO_KEV_SOURCE_EVENT",
    "ONLY_STALE_FINDINGS_DETAIL",
    "OUT_OF_RANGE_CATALOG_DATE_DETAIL",
    "SHORTENED_DETAIL",
    "TOLERATED_MISSED_RUNS",
    "UNKNOWN_LOCATOR_DETAIL",
    "UNKNOWN_SCHEME_DETAIL",
    "UNREADABLE_CATALOG_DATE_DETAIL",
    "Catalog",
    "CatalogEntry",
    "CrossReference",
    "CurrentEvidence",
    "CurrentFinding",
    "KevCollector",
    "KevDocumentError",
    "KevEvidenceError",
    "KevSourceError",
    "catalog_in",
    "cross_reference",
    "current_findings",
    "declare_kev_source",
    "declared_kev_source",
    "kev_source",
    "stale_clause",
    "withdraw_kev_source",
]

logger = structlog.get_logger(__name__)

#: What this collector is called, on its ledger rows, in its cache keys and in the
#: registry `config/startup/stage_two.py` sweeps. It is the `collect` half of its
#: task name too, which is what routes it (`core/queues.py`).
COLLECTOR_NAME: Final[str] = "kev"

#: How often this collector is meant to run, and the number every other interval
#: below is derived from.
#:
#: `CPM-NFR-2` puts security and KEV at **daily** with no range to choose inside,
#: and here the number is doing more work than it does for the sibling: an advisory
#: enters the catalog on the day somebody starts exploiting it, and the interval
#: between that and knowing is the whole of what this collector is for. The cadence
#: itself is data in `django_celery_beat` (`CPM-AD-20`); this is the number the
#: arithmetic below assumes, and `CPM-CURRENCY-S05` reconciles the two at start-up,
#: in both directions, from `collectors/apps.py`'s `ready()`.
KEV_CADENCE: Final[timedelta] = timedelta(days=1)

#: How long after its tick the KEV dispatch is asked to run.
#:
#: **The two security sweeps otherwise fire from one instant with nothing
#: sequencing them**, so a KEV run routinely cross-references advisories the
#: vulnerability run of the same tick has not written yet -- the answer is then one
#: cadence behind, silently. The reconciliation `CPM-CURRENCY-S05` owns compares a
#: beat entry's `schedule` with its collector's declared cadence, so the *interval*
#: cannot carry a phase and a crontab cannot be read as an interval; the entry's
#: `options` can, and a countdown on the dispatch is what this component has to
#: offset with. `config/settings/base.py` carries it and
#: `tests/unit/test_settings.py` reconciles the two.
#:
#: **It reduces the window and does not close it**, and that is stated rather than
#: implied: at `CPM-NFR-1`'s ten thousand packages the vulnerability sweep spends
#: most of a day inside its own allowance, so an hour buys the small inventories
#: and not the large ones. `docs/deployment.md` says so to an operator, and the
#: residual is a `deferred` entry on `CPM-SECURITY-S02`.
KEV_DISPATCH_OFFSET: Final[timedelta] = timedelta(hours=1)

#: How many consecutive missed collections may pass before this product stops
#: calling an answer current. PRD Open Question 7 was resolved on 2026-09-05 and
#: fixes this per *signal class*: the vulnerability and KEV class tolerates one.
TOLERATED_MISSED_RUNS: Final[int] = 1

#: How long this collector's evidence may be read as current (`CPM-AD-28`):
#: `cadence x (1 + tolerated_missed_runs)`, which is the two days Open Question 7's
#: table gives this signal class. Strictly greater than the cadence, so a package
#: does not read stale at exactly the moment its next run is due.
#:
#: **It is also what bounds the read of the sibling table**, and that second use is
#: deliberate rather than convenient: the two tables are the same signal class, so
#: the interval past which this collector's own answer stops being current is the
#: interval past which the advisory evidence it is computed from stopped being
#: current too. A cross-reference computed from evidence this product would report
#: as stale is a fresh-looking row about a stale fact.
KEV_FRESHNESS_TARGET: Final[timedelta] = KEV_CADENCE * (1 + TOLERATED_MISSED_RUNS)

#: How long a successful observation suppresses the next one (`CPM-AD-7`). Half the
#: cadence, so a scheduled run is never suppressed by the previous one and a second
#: run of one package inside half a day still is.
KEV_OBSERVATION_WINDOW: Final[timedelta] = KEV_CADENCE / 2

#: How many times a failed request is retried, and therefore what the rate limiter
#: is charged against per collection.
#:
#: **The shared default, and taking it is the decision**, on the terms
#: `collectors/vulnerability.py` states: this collector makes exactly one call per
#: collection, and there is no source to tune the number against because which KEV
#: source is read is PRD Open Question 1. A number invented here would be a claim
#: about the transient-failure behaviour of a source nobody has chosen.
KEV_RETRIES: Final[int] = DEFAULT_RETRIES

#: Seconds any single connect or read phase may take.
#:
#: Five, which is what makes `worst_case_call_seconds(timeout, retries)` fit
#: comfortably inside the inherited 60-second soft limit (`CPM-AD-9`) at the retry
#: count above -- the reconciliation is a case rather than a sum in a reader's head.
#:
#: **It bounds the transport this base would build and not necessarily the
#: adapter's own call**, on the terms the sibling states: `core/collection.py`
#: builds a `RequestsTransport` from this value when no transport is passed, and
#: the declared KEV source adapter is passed instead (`CPM-AD-29`).
KEV_TIMEOUT: Final[float] = 5.0

#: How hard this collector may push its source (`CPM-AD-20`).
#:
#: **A courtesy bound rather than a number a source stated**, and here it could not
#: be anything else: no source is chosen, so there is no published ceiling to
#: honour.
#:
#: Thirty requests a minute, charged `1 + retries` -- four -- per collection, is
#: **7.5 packages a minute**: 450 an hour, and `CPM-NFR-1`'s ten thousand packages
#: in about 22 hours. That is the same arithmetic `collectors/vulnerability.py`
#: does and it fits inside the daily cadence with almost nothing spare, which is
#: stated here rather than discovered at that scale -- and it matters more here,
#: because the two security sweeps run on the same day and each asks its own
#: source. The first operator to declare a KEV source against a full inventory is
#: expected to raise this against what that source actually publishes, and
#: `docs/deployment.md` says the same number to them.
KEV_RATE_LIMIT: Final[RateLimit] = RateLimit(calls=30, per=timedelta(minutes=1))

#: What this collector's source expects on every request (`CPM-AD-20`,
#: `CPM-AD-27`): declared here, merged and sent by the base, never by this module.
#: `Accept` asks for the JSON representation `catalog_in` reads and the
#: `User-Agent` is the one identity every collector shares (`collectors/agent.py`).
#: An adapter that does not speak HTTP is handed them and ignores them. Nothing
#: conditional is declared -- the validators are the base's.
KEV_HEADERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    },
)

#: `NO_CACHE`: short-circuits the cache read, the cache write and the conditional
#: headers.
#:
#: **Declared rather than defaulted**, and for the reason
#: `collectors/vulnerability.py` declares it: a remembered response is only usable
#: against a source that offers a validator, nothing here knows whether the
#: declared adapter speaks HTTP at all, and a cached security answer is the one
#: kind this product should be slowest to replay -- it is the answer whose
#: staleness `CPM-NFR-3` is written about. What it costs is one call per package
#: for a catalog that is the same document every time, which is stated in this
#: module's docstring and in `docs/deployment.md` rather than hidden: an adapter
#: that holds the catalog itself pays it once.
KEV_CACHE_TTL: Final[timedelta] = NO_CACHE

#: The locator this collector hands the adapter, and it is the same one on every
#: run.
#:
#: **A catalog rather than a package**, which is the one declaration where this
#: collector differs from its sibling. The KEV catalog is a document about
#: advisories: there is no per-package question to ask it, because which of *our*
#: advisories to cross-reference is this product's own evidence and not something
#: an adapter could be told. A locator that embedded a purl would name a package
#: the adapter has no use for, and would have every identity-less package sharing
#: one spelling for a question that was never about identity at all.
#:
#: Opaque, on the terms `CPM-AD-29` sets: the adapter already knows which catalog
#: it reads, and a hostname spelled here would be this module answering PRD Open
#: Question 1.
KEV_SOURCE_LOCATOR: Final[str] = "kev://declared-source/catalog"

#: What a value this collector stores, echoes or reads may not contain.
#:
#: C0 and C1 control characters and the delete character, refused where the value
#: enters rather than left to the insert, for the reason
#: `collectors/vulnerability.py` refuses them: PostgreSQL rejects a NUL byte in a
#: `text` value from the *driver*, several frames past the `try` `translate` is
#: wrapped in and outside the guard that would have turned it into an `error` row.
_CONTROL_CHARACTERS: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: The longest KEV catalog document this collector will hand to `json.loads`, in
#: characters.
#:
#: A whole catalog rather than one package's answer, so it is sized differently
#: from the sibling's: the public catalogue this product would most plausibly read
#: carries some fifteen hundred entries, and in this collector's own schema -- an
#: identifier, its aliases and a date -- that is well under a hundred kilobytes. Two
#: mebibytes is therefore more than an order of magnitude above an honest catalog
#: and is a bound rather than an expectation. **What it protects is the parse and
#: nothing earlier**: by the time a body arrives here the adapter has produced it,
#: so what this refuses is handing `json.loads` a document no honest source serves,
#: which is where a worker's soft time limit would be spent (`CPM-AD-9`).
#:
#: **It is sized so that it and `MAX_ENTRIES` are separately reachable**, which the
#: first pass got wrong: two bounds within a percent of each other are one bound
#: and an operator meeting the wrong refusal. A catalog of `MAX_ENTRIES` minimal
#: entries fits comfortably inside this, and a catalog of far fewer wide ones trips
#: this first -- `tests/unit/django_apps/test_kev.py` asserts both directions.
MAX_CATALOG_CHARACTERS: Final[int] = 2 * 1024 * 1024

#: The most entries one catalog document may state.
#:
#: An entry-count bound rather than a second document bound, and unlike the
#: sibling's it is not a row-count bound: entries do not become rows one for one --
#: rows are one per *current finding* -- so what this protects is the mapping this
#: module builds and the duplicate scan over it. Twenty thousand is more than ten
#: times the public catalogue's size and far below a source malfunctioning.
#: Refused rather than truncated: cross-referencing against the first twenty
#: thousand entries of a longer catalog would record `not_listed` for advisories the
#: catalog listed, which is the one answer on this table that reads as reassuring.
MAX_ENTRIES: Final[int] = 20_000

#: The most aliases one catalog entry may state.
#:
#: An advisory issued under a handful of schemes carries a handful of identifiers;
#: thirty-two is generous against every catalogue in use and bounds the fan-out of
#: the lookup this module builds, which would otherwise be `entries x aliases`
#: unbounded inside `MAX_ENTRIES`.
MAX_ALIASES: Final[int] = 32

#: The most rows one collection of one package may write.
#:
#: One row per *current* advisory, and "current" is bounded in time rather than in
#: number -- so without this a package whose advisory history is long enough
#: inserts that many rows in one `bulk_create`, inside one package's transaction,
#: on every run. Refused rather than truncated: recording the first
#: `MAX_CROSS_REFERENCES` of a package's advisories without saying so would be a
#: permanent partial answer nothing could tell from a complete one, and the half
#: that went missing would be the half a reviewer needed.
#:
#: Two thousand, which is the sibling's own per-document bound of a thousand times
#: `1 + TOLERATED_MISSED_RUNS`: at most that many collections' worth of distinct
#: advisories can be inside this collector's freshness window at once. The
#: thousand is **restated rather than imported** -- no collector imports another
#: (`CPM-AD-7`), and this module's one exception is a read of a table rather than
#: of a constant.
MAX_CROSS_REFERENCES: Final[int] = 2000

#: The longest value this collector will copy out of a document into a row's
#: `detail`, in characters.
#:
#: `detail` is a `TextField` and declares no width, so nothing else bounds what a
#: source can put into an append-only column that nothing may correct -- and
#: `core/collection.py` copies a row's reason into the ledger row and into every
#: structured log line the run emits. The only value echoed is the date a catalog
#: stated and could not be read, and a date is short; a value longer than this is a
#: source doing something else and is refused with the rest of the document rather
#: than shortened, because unlike the sibling's narrative `detail` this one is a
#: *fact* the entry claimed.
MAX_ECHOED_CHARACTERS: Final[int] = 128

#: The longest reason a *sentinel* row will carry, in characters.
#:
#: Different from the bound above and for the opposite reason: a sentinel row is
#: written on a path that is already recording a failure, and `CPM-NFR-3` requires
#: it to be written -- so a reason too long, or one carrying a control character,
#: is **shortened and cleaned rather than refused**. The reason reaching that hook
#: is the base's own sentence with a third party's exception message inside it, and
#: raising over its shape would turn "the source failed" into "no row at all",
#: which is the one outcome this product does not permit.
MAX_SENTINEL_DETAIL_CHARACTERS: Final[int] = 1024

#: The window a catalog date must fall inside to be recorded.
#:
#: **A stored instant is not the whole of what Python can represent**, and the
#: mismatch is the failure this bound exists for: a date near
#: `datetime.min`/`datetime.max` converts on its way to the driver and raises there
#: -- several frames past the `try` `translate` is wrapped in, so an unbounded one
#: escapes as neither a document refusal nor a recorded observation, which is "no
#: row" on the one path this module cannot see.
#:
#: 1999 because that is when the CVE scheme began issuing, so no catalog can
#: honestly state an earlier date added; 2200 because a date that far ahead is a
#: source malfunctioning rather than a catalog. Outside the window is treated as a
#: date that could not be read -- blank, with the reason on the row -- rather than
#: as a document defect, on the terms every other unreadable date is: the fact
#: `CPM-FR-12` is about is the link.
EARLIEST_CATALOG_DATE: Final[datetime] = datetime(1999, 1, 1, tzinfo=UTC)
LATEST_CATALOG_DATE: Final[datetime] = datetime(2200, 1, 1, tzinfo=UTC)

#: The fields of a catalog document this collector reads, named rather than spelled
#: at the call sites so the reader and the cases that build documents cannot drift.
ENTRIES_FIELD: Final[str] = "entries"
ADVISORY_ID_FIELD: Final[str] = "advisory_id"
ALIASES_FIELD: Final[str] = "aliases"
DATE_ADDED_FIELD: Final[str] = "date_added"

#: Every field one catalog entry may carry, and nothing else is accepted.
#:
#: An entry naming a severity, a required action or a due date is refused rather
#: than having the field ignored, on the terms `collectors/vulnerability.py`
#: refuses an undefined finding field: a silently dropped column is a source that
#: believes it supplied one. PRD Appendix A.2 gives this table two facts, and
#: `aliases` is not a third -- it is how the first one is *matched*, and it is
#: never stored.
ENTRY_FIELDS: Final[frozenset[str]] = frozenset({ADVISORY_ID_FIELD, ALIASES_FIELD, DATE_ADDED_FIELD})

#: Every field the *document* may carry, and nothing else is accepted.
#:
#: The same rule one level down, and it is worth more here than on an entry. A
#: catalog that grew a `truncated`, `partial` or `as_of` flag would have it
#: silently dropped, and this collector would then record `not_listed` -- "the
#: catalog was read and does not list this advisory" -- for a document that said in
#: as many words that it had not finished listing.
#:
#: **One field, and no narrative one.** `collectors/vulnerability.py` reads a
#: document-level `detail` because its document is an answer *about the package*,
#: so a source has something to say about why it matched nothing. A catalog says
#: nothing about our package -- the cross-reference is this product's own work -- so
#: a `detail` here would have no row to land on but every one of them, repeating one
#: sentence across a package's whole answer.
DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset({ENTRIES_FIELD})

#: What a row says in its own words, in each of the ways it is reachable. Named so
#: the row a run writes and the case that reads it back cannot drift.
NOT_LISTED_DETAIL: Final[str] = (
    "the KEV catalog was read and does not list this advisory, which is not the same as this advisory being "
    "harmless or this package being clear"
)
UNKNOWN_SCHEME_DETAIL: Final[str] = (
    "the KEV catalog states no advisory under this identifier's own scheme and stated no alias matching it, so "
    "reading this advisory's absence from it establishes nothing -- an identifier a catalog does not use cannot "
    "be missing from it"
)
NO_CATALOG_DATE_DETAIL: Final[str] = (
    "the KEV catalog lists this advisory and states no date added, so the date is recorded as missing rather than "
    "inferred"
)
UNREADABLE_CATALOG_DATE_DETAIL: Final[str] = (
    "the KEV catalog lists this advisory and states a date added this collector cannot read as an instant with an "
    "offset, so the date is recorded as missing rather than guessed"
)
OUT_OF_RANGE_CATALOG_DATE_DETAIL: Final[str] = (
    "the KEV catalog lists this advisory and states a date added outside the range a recorded instant may take, "
    "so the date is recorded as missing rather than stored as a value nothing could read back"
)
NO_ADVISORY_SOURCE_DETAIL: Final[str] = (
    "no advisory source is declared, so this product has recorded no advisory against this package for the KEV "
    "catalog to be asked about -- nothing was established about whether anything against it is known to be "
    "exploited, which is not the same as nothing being exploited"
)
NOTHING_OBSERVED_DETAIL: Final[str] = (
    "the vulnerability collector has not yet observed this package, so there is no advisory for the KEV catalog "
    "to be asked about -- nothing was established about whether anything against it is known to be exploited"
)
NOTHING_MATCHED_DETAIL: Final[str] = (
    "the vulnerability collector observed this package and matched no advisory to it, so there was nothing to "
    "cross-reference against the KEV catalog -- which is not the same as nothing against it being exploited"
)
ONLY_STALE_FINDINGS_DETAIL: Final[str] = (
    "every advisory this product records against this package was observed longer ago than this collector calls "
    "an answer current, so there was nothing current to cross-reference and the KEV answer would have been about "
    "evidence this product already reports as stale"
)
UNKNOWN_LOCATOR_DETAIL: Final[str] = (
    "this is the KEV source reporting that the locator itself does not exist, which is a withdrawn or "
    "misconfigured source rather than a package with nothing known-exploited against it"
)
SHORTENED_DETAIL: Final[str] = "[shortened by this collector]"

#: The two events this module emits, and the only observables an operator has for a
#: component that has stopped cross-referencing.
#:
#: `NO_KEV_SOURCE_EVENT` is emitted where no collection happens at all -- from the
#: selection the daily dispatch asks for -- because a component with no KEV source
#: records a `succeeded` dispatch over an empty selection, which is byte-identical
#: to a healthy day on which nothing needed collecting.
#:
#: **Emitted when the selection is drawn rather than when it is asked for**, which
#: is one line per dispatch and none at boot, on the terms
#: `collectors/vulnerability.py`'s own event states: `cadence_reconciliation_fault`
#: asks every registered collector for its selection and only tests whether it is
#: `None`, so logging at the *call* would put a warning inside every start-up
#: reconciliation -- including the ones a refusal contract asserts emit nothing in
#: place of raising.
#:
#: `CATALOG_ABSENT_EVENT` is the other silence, and it is the one a declared source
#: produces: an adapter answering `found=False` writes `not_found` and a
#: **`succeeded`** ledger row, because the source answered -- so a withdrawn or
#: misconfigured catalog produces a full day of clean-looking runs with nothing in
#: the log at all. It is emitted where the sentinel row is shaped, which is once per
#: package rather than once per dispatch; that is noisier than the other by design,
#: because it is the failure a reader of the rows would most easily mistake for an
#: answer. `docs/deployment.md` tells an operator to alert on both by name.
NO_KEV_SOURCE_EVENT: Final[str] = "kev.no_kev_source"
CATALOG_ABSENT_EVENT: Final[str] = "kev.catalog_absent"

#: The declared KEV source adapter, by the one slot there is.
#:
#: A module-level mapping rather than a rebound global, for the reason
#: `collectors/advisories.py`'s `_DECLARED` is one: ruff `PLW0603` forbids the
#: `global` statement, and a `from ... import` of a rebound name would bind a copy
#: that never observes a later write.
_DECLARED: Final[dict[str, Transport]] = {}

#: The key `_DECLARED` holds the adapter under.
#:
#: One slot, because `CPM-AD-29` gives a source-substitution seam exactly one
#: adapter: two would make "which catalog is this component's KEV source" a
#: question answered by import order. It is deliberately a different key in a
#: different mapping from the advisory slot's -- two sources, two slots, two
#: refusals -- so withdrawing one never withdraws the other.
_ADAPTER_SLOT: Final[str] = "kev-source"

#: What makes a declaration and a withdrawal atomic against each other.
#:
#: Both read the slot and then write it, and `AppConfig.ready()` is not the only
#: caller: a Celery worker with a thread pool, or any process that declares a
#: source outside boot, can reach these concurrently. Unguarded, two declarations
#: that both read an empty slot would *both* succeed and the second would silently
#: replace the first -- which is exactly the outcome the duplicate refusal exists
#: to prevent -- and two withdrawals could have the second raise `KeyError` from
#: `del` rather than this module's own refusal.
_SLOT_LOCK: Final[Lock] = Lock()


class KevSourceError(ValueError):
    """No usable KEV source adapter is declared, or a second one is.

    A `ValueError` subclass on the same terms as `collectors/advisories.py`'s
    `AdvisorySourceError`, which it is deliberately shaped after and deliberately
    not: adapters are declared, never discovered (inherited `AD-8`, `CPM-AD-29`),
    a duplicate is refused rather than overwritten, and a KEV source is a
    *different* source from an advisory source, so it fails under a name of its own.
    A caller that caught the sibling's error for both would report a missing
    advisory database when the catalog was the thing nobody declared.

    **The absent case is a misconfiguration and not a cross-reference failure**,
    which is why it is this class rather than an evidence row. A component with no
    KEV source has not looked and cannot say anything about any advisory; a row
    recording that would be an observation nobody made.

    **The run is still recorded**, which is the difference from the sibling. A
    withdrawal between a dispatch's selection and its tasks running leaves ten
    thousand enqueued tasks that each refuse, and refusing before the recorder
    opened would leave no trace of any of them -- a day in which nothing was
    observed and nothing says so. `collectors/tasks.py` opens a ledger row, raises
    inside it, and lets the recorder finalize it `failed`; no evidence row is
    written, because none was earned.
    """


class KevDocumentError(ValueError):
    """A KEV catalog document could not be read as what it claims to be.

    Raised from `translate`, which the base answers by writing an `error` row and
    re-raising unchanged -- so `CPM-NFR-3`'s guarantee holds on this path too:
    never a clean result, and never no row.

    Refused rather than partially read, and the stakes are the sibling's read
    backwards: a document this collector cannot understand is a source whose shape
    has changed, and reading around it would record `not_listed` for advisories the
    catalog listed -- an answer that says "this is not being used against people"
    because the entry saying otherwise was in a shape the reader skipped.
    """


class KevEvidenceError(ValueError):
    """This package's own evidence cannot be cross-referenced as it stands.

    Distinct from `KevDocumentError`, and the distinction is which side was wrong:
    that one is a catalog this collector could not read, and this one is a row in
    `vulnerability_findings` this collector will not derive a cross-reference from.
    An operator meeting the two has different work to do, and a single class would
    have sent them to the source for a defect in their own table.

    Raised from `translate`, so the base writes an `error` row and re-raises -- the
    run is on the record either way. Two things reach it: a package with more
    current advisories than one collection may record, and a matched finding whose
    advisory identifier is blank once stripped, which that table's own constraint
    permits because it tests for the empty string.
    """


@dataclass(frozen=True, slots=True)
class CurrentFinding:
    """One advisory this product currently records against a package.

    The half of a cross-reference that comes from *our* evidence rather than from
    the catalog, read by `current_findings` and handed to the pure
    `cross_reference` so that function needs no database.

    Attributes:
        finding_id: The `vulnerability_findings` row this derives from, by the
            primary key `CPM-AD-3` fixes. What AC 1's link is built from.
        package_id: The package *that row* is about. Carried rather than taken from
            the run, so the row this becomes cannot pair one package with another's
            observation -- see `KevFinding.save` for why that invariant cannot be a
            check constraint and what closes it instead.
        advisory_id: The advisory that row named, exactly as the advisory source
            spelled it and already stripped.

    """

    finding_id: int
    package_id: int
    advisory_id: str

    def __post_init__(self) -> None:
        """Refuse a finding that names no advisory, no package or no row.

        Raises:
            CollectorConfigurationError: When any field is empty. `current_findings`
                refuses a blank advisory identifier before it reaches here with a
                message about the row it came from; this is the guard for a caller
                constructing one by hand, which is how the pure cross-reference is
                exercised.

        """
        if not self.finding_id or not self.package_id or not self.advisory_id:
            message = (
                f"CurrentFinding(finding_id={self.finding_id!r}, package_id={self.package_id!r}, "
                f"advisory_id={self.advisory_id!r}) leaves one of its three facts empty. A cross-reference "
                f"derives from one finding, is about one advisory, and belongs to the package that finding was "
                f"about (CPM-FR-12)."
            )
            raise CollectorConfigurationError(message)


@dataclass(frozen=True, slots=True)
class CurrentEvidence:
    """What this product currently records against one package, and what it does not.

    More than a list of findings, because "there is nothing to cross-reference"
    spans four situations and `CPM-FR-6` requires them kept apart. The counts below
    are what `translate` reads to say which one it is.

    Attributes:
        findings: The current advisories, one per advisory, ordered by identifier.
        excluded: How many matched findings were dropped as older than this
            collector's freshness target. Recorded on every row a run writes, so a
            reader holding one row can tell it was computed against a partial view.
        observed: Whether the vulnerability collector has written any row at all
            about this package, whatever its state.
        matched: Whether any of those rows is a determinate one, fresh or stale.

    """

    findings: tuple[CurrentFinding, ...]
    excluded: int
    observed: bool
    matched: bool


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One advisory the KEV catalog lists, and what it said about the date.

    Attributes:
        advisory_id: The advisory's own identifier, exactly as the catalog spelled
            it.
        date_added: When the catalog says it added the advisory, as an aware
            instant inside `EARLIEST_CATALOG_DATE`..`LATEST_CATALOG_DATE`, or
            `None` where the catalog stated none or stated one this collector could
            not record.
        fault: Why the date is absent, in words worth storing on a row, or the
            empty string where the catalog stated a recordable one. Never both set
            with `date_added`, and never both empty -- see `__post_init__`.

    """

    advisory_id: str
    date_added: datetime | None
    fault: str

    def __post_init__(self) -> None:
        """Refuse an entry whose date and whose reason for having none disagree.

        Raises:
            CollectorConfigurationError: When a date and a fault are both stated,
                or when neither is. Enforced rather than described, on the terms
                `MatchTarget` in `collectors/vulnerability.py` states: a docstring
                is not enforcement, and an entry carrying neither would make a
                `listed` row whose `detail` says nothing about why its date column
                is empty -- which the model's own docstring promises it does.

        """
        if (self.date_added is not None) == bool(self.fault):
            message = (
                f"CatalogEntry(advisory_id={self.advisory_id!r}, date_added={self.date_added!r}, "
                f"fault={self.fault!r}) sets {'both' if self.fault else 'neither'} of its date and its reason for "
                f"having none, and exactly one is set on every entry: a blank date means missing (PRD Appendix "
                f"A.1) and a row that could not say which kind of missing is one a reader cannot act on."
            )
            raise CollectorConfigurationError(message)


@dataclass(frozen=True, slots=True)
class Catalog:
    """One KEV catalog, read into the two things a cross-reference asks it.

    Attributes:
        entries: Every advisory the catalog lists, keyed by case-folded identifier
            **and by every case-folded alias it stated**, so a lookup is one
            dictionary read rather than a scan of the catalog per finding.
        schemes: Every identifier scheme the catalog uses, case-folded -- the
            prefixes of its identifiers and of their aliases. What this exists for
            is the one question asked before the reassuring value is written: a
            catalog that states no advisory under a finding's scheme cannot be said
            not to list it.

    """

    entries: Mapping[str, CatalogEntry]
    schemes: frozenset[str]


@dataclass(frozen=True, slots=True)
class CrossReference:
    """One row's worth of what cross-referencing one advisory concluded.

    Three answers rather than two: the catalog lists the advisory, the catalog was
    read and does not list it, or the catalog has nothing to say about an identifier
    in this scheme. Never a failure and never an absence: a catalog that could not
    be read raises (`KevDocumentError`) and a package with nothing to cross-reference
    produces no `CrossReference` at all -- `translate` writes that row itself,
    because it is about our own evidence rather than about anything the catalog said.

    **The invariant is enforced rather than described** -- see `__post_init__`.

    Attributes:
        finding_id: The `vulnerability_findings` row this derives from. AC 1's
            link, and present on every cross-reference there is, including the
            `unknown` one -- which is about *this advisory* and must say which.
        package_id: The package that finding was about, carried onto the row.
        state: `listed`, `not_listed` or `unknown`. Never any other member: the
            remaining three are the base's.
        catalog_date_added: The catalog's own date, or `None`. Only ever set on a
            `listed` cross-reference.
        detail: Why the date is absent, that the catalog does not list this
            advisory, or that it cannot speak to this identifier's scheme. Empty
            only on a `listed` cross-reference carrying a date.

    """

    finding_id: int
    package_id: int
    state: str
    catalog_date_added: datetime | None
    detail: str

    def __post_init__(self) -> None:
        """Refuse a cross-reference whose facts do not match the state it claims.

        The same biconditional `kev_findings` enforces, applied where the value is
        built rather than where it lands -- because the constraint fires at insert,
        inside `bulk_create`, with a message about a column and nothing about the
        entry or the branch that produced it.

        Raises:
            CollectorConfigurationError: When the state is none of the three a
                catalog lookup can produce; when a cross-reference that is not
                `listed` carries a catalog date; or when one carries neither a date
                nor a reason for having none.

        """
        if self.state not in {LISTED, NOT_LISTED, KEV_UNKNOWN}:
            message = (
                f"CrossReference(state={self.state!r}) is none of {LISTED!r}, {NOT_LISTED!r} and "
                f"{KEV_UNKNOWN!r}, and those are the three a catalog lookup can produce: the advisory is listed, "
                f"it is not, or the catalog cannot speak to this identifier's scheme. Every other value in this "
                f"vocabulary is the base's to decide."
            )
            raise CollectorConfigurationError(message)
        if self.state != LISTED and self.catalog_date_added is not None:
            message = (
                f"CrossReference(state={self.state!r}) carries catalog_date_added={self.catalog_date_added!r}. "
                f"A date is something only a listed advisory has: a row carrying one under any other state would "
                f"say the catalog both does and does not list it, which kev_findings refuses at insert."
            )
            raise CollectorConfigurationError(message)
        if (self.catalog_date_added is not None) == bool(self.detail):
            message = (
                f"CrossReference(state={self.state!r}, catalog_date_added={self.catalog_date_added!r}, "
                f"detail={self.detail!r}) sets {'both' if self.detail else 'neither'} of its date and its "
                f"reason. Exactly one is set on every cross-reference: a row with no date always says which "
                f"kind of missing it is, and a row that has one needs no explanation."
            )
            raise CollectorConfigurationError(message)


def declare_kev_source(adapter: Transport) -> Transport:
    """Adopt one KEV source adapter for this process.

    Args:
        adapter: The `Transport` the KEV collector reads its catalog through.

    Returns:
        The adapter, unchanged, so a caller can bind it in one statement.

    Raises:
        KevSourceError: When the object is not a `Transport`, or when one is
            already declared. `Transport` is `runtime_checkable`, so this check
            sees method *names* only -- the same bound `core/transport.py` records,
            and the reason this module's docstring writes out what an adapter owes
            beyond the protocol.

            The check and the write are one step under `_SLOT_LOCK`, so two
            concurrent declarations cannot both find an empty slot; the refusal is
            raised outside the lock, because a message is not shared state.

    """
    if not isinstance(adapter, Transport):
        message = (
            f"{adapter!r} is not a Transport and cannot be this component's KEV source. A KEV source is a "
            f"transport substitution at the collector base's seam (CPM-AD-27, CPM-AD-29): it answers fetch() "
            f"with a recorded Payload, in the catalog schema this module's docstring states, and raises "
            f"TransportError for every failure."
        )
        raise KevSourceError(message)
    with _SLOT_LOCK:
        existing = _DECLARED.get(_ADAPTER_SLOT)
        if existing is None:
            _DECLARED[_ADAPTER_SLOT] = adapter
    if existing is not None:
        message = (
            f"{type(adapter).__name__} cannot be declared: {type(existing).__name__} is already this "
            f"component's KEV source. A source-substitution seam reads exactly one adapter (CPM-AD-29); a "
            f"second one silently replacing the first would make which catalog this component believes a "
            f"question answered by import order, in findings nothing may correct."
        )
        raise KevSourceError(message)
    return adapter


def withdraw_kev_source() -> None:
    """Withdraw the declared KEV source adapter.

    Symmetric with `declare_kev_source` rather than a test hook bolted on, for the
    reason `withdraw_advisory_source` is: the declaration is process-global, so a
    case that could only add to it could never measure the refusal when nothing is
    declared, and one that left an adapter behind would change what every later
    case reads.

    **Withdrawing returns the component to the state it ships in**, which is one
    that observes nothing: the next dispatch selects no package and emits
    `NO_KEV_SOURCE_EVENT`, which is what an operator alerts on. Tasks a dispatch
    already enqueued still run, and each records a `failed` ledger row rather than
    vanishing -- see `KevSourceError`.

    Raises:
        KevSourceError: When nothing is declared. Refused rather than ignored,
            because a silent no-op turns a mistaken withdrawal into a declaration
            that stays live and a caller that believes it does not. One `pop` under
            `_SLOT_LOCK` rather than a membership test and a `del`, so two
            concurrent withdrawals raise this rather than one of them raising a
            bare `KeyError`.

    """
    with _SLOT_LOCK:
        withdrawn = _DECLARED.pop(_ADAPTER_SLOT, None)
    if withdrawn is None:
        message = (
            "no KEV source adapter is declared, so there is nothing to withdraw. "
            "Declare one with declare_kev_source (CPM-AD-29)."
        )
        raise KevSourceError(message)


def declared_kev_source() -> Transport | None:
    """Return the declared KEV source adapter, or `None` when there is none.

    The read `kev_source` below refuses on, without the refusal. It exists for
    three caller shapes that must **ask** rather than demand: a boot hook checking
    whether the declaration it is about to make has already been made
    (`AppConfig.ready` is Django's to call, and a second `django.setup()` in one
    process calls it again), `KevCollector.selectable_packages`, which offers no
    package at all while nothing is declared, and `collectors/tasks.py`, which
    opens a ledger row before it refuses.

    Returns:
        The adapter this component reads the catalog through, or `None` when
        nothing is declared. `None` is an answer here and never a default: a caller
        that wants the run refused calls `kev_source`.

    """
    return _DECLARED.get(_ADAPTER_SLOT)


def kev_source() -> Transport:
    """Return the declared KEV source adapter.

    Returns:
        The adapter this component reads the catalog through.

    Raises:
        KevSourceError: When none is declared. `collectors/tasks.py` calls this
            **inside** an open ledger row, so an enqueued task that meets a
            withdrawn source records a `failed` run rather than leaving no trace --
            see that class.

    """
    adapter = _DECLARED.get(_ADAPTER_SLOT)
    if adapter is None:
        message = (
            "no KEV source adapter is declared, so there is no catalog to cross-reference this package's "
            "advisories against. Adapters are declared and never discovered (AD-8, CPM-AD-29), and this "
            "component ships with none: which KEV sources are licensed for use is PRD Open Question 1, and a "
            "catalog nobody chose would record which advisories are being exploited from a source an "
            "organisation never agreed to act on. Declare one with declare_kev_source(...) in an "
            "AppConfig.ready() (docs/deployment.md)."
        )
        raise KevSourceError(message)
    return adapter


def current_findings(*, package_id: int, now: datetime) -> CurrentEvidence:
    """Return the advisories this product currently records against one package.

    **This is the read `CPM-AD-7` does not grant, and it is deliberately the only
    one.** It is one table, read-only, reached through `collectors/models.py`
    rather than by importing the sibling collector; see the module docstring for
    the licence that holds it to one module and `CPM-SECURITY-S02`'s Spec Change
    Log for the exception itself.

    **Current means the newest determinate row per advisory, inside the freshness
    window.** Evidence is append-only and re-observation inserts, so a package
    accumulates many rows per advisory; the answer is the last one, ordered by
    observation instant **descending** then primary key descending -- which is the
    order `VULNERABILITY_READ_INDEX` is built in, and which makes the first row seen
    per advisory the newest. The window is `KEV_FRESHNESS_TARGET`, and bounding by
    it is what retires an advisory: the sibling collector records "nothing matched
    today" as one row naming no advisory, so nothing there ever says an advisory has
    gone, and without this bound a single match would be cross-referenced for the
    life of the package.

    **Advisories are grouped without regard to case**, because `CVE-2024-23334` and
    `cve-2024-23334` are one advisory in every catalogue that issues them; the
    identifier kept is the newest row's own spelling, because normalising a recorded
    identifier would be this collector rewriting a fact.

    Args:
        package_id: The package to read, by the integer primary key `CPM-AD-3`
            fixes.
        now: The run's instant, from the injected clock (`CPM-AD-26`). The window
            is measured back from it rather than from the wall clock, so a replay
            at a stated instant reads the same evidence.

    Returns:
        What this product currently records, and what it does not -- see
        `CurrentEvidence` for why the negatives are counted rather than collapsed
        into an empty list.

    Raises:
        KevEvidenceError: When a matched finding's advisory identifier is blank once
            stripped -- `vulnerability_findings` tests for the empty string, so a
            whitespace-only identifier is a row that table permits and this
            collector must not cross-reference, because answering `not_listed`
            about it would be the reassuring value written about an advisory nobody
            named -- or when the package has more current advisories than
            `MAX_CROSS_REFERENCES`.

    """
    cut_off = now - KEV_FRESHNESS_TARGET
    matched = VulnerabilityFinding.objects.filter(package_id=package_id, state=MATCHED)
    observed = VulnerabilityFinding.objects.filter(package_id=package_id).exists()
    matched_total = matched.count()
    # Newest first, so the first row seen for an advisory is the current one --
    # and in the order the read index is built in. `values_list` rather than model
    # instances: three columns per row of a history that grows daily, and nothing
    # here needs a row's behaviour.
    rows = (
        matched.filter(observed_at__gte=cut_off)
        .order_by("-observed_at", "-pk")
        .values_list(
            "pk",
            "package_id",
            "advisory_id",
        )
    )
    current: dict[str, CurrentFinding] = {}
    fresh = 0
    for finding_id, finding_package_id, advisory_id in rows.iterator():
        fresh += 1
        stripped = advisory_id.strip()
        if not stripped:
            message = (
                f"vulnerability finding {finding_id} is a {MATCHED!r} row whose advisory identifier is "
                f"{advisory_id!r}, which names no advisory. That table's constraint tests for the empty string, "
                f"so a whitespace-only identifier reaches here; cross-referencing it would record that a catalog "
                f"does not list an advisory nobody named, which is the reassuring value this table is most "
                f"careful with."
            )
            raise KevEvidenceError(message)
        current.setdefault(
            stripped.casefold(),
            CurrentFinding(finding_id=finding_id, package_id=finding_package_id, advisory_id=stripped),
        )
        if len(current) > MAX_CROSS_REFERENCES:
            message = (
                f"package {package_id} has more than {MAX_CROSS_REFERENCES} current advisories, and this "
                f"collector records at most that many cross-references in one collection. Refused rather than "
                f"truncated: recording the first {MAX_CROSS_REFERENCES} without saying so would be a permanent "
                f"partial answer nothing could tell from a complete one, and the half that went missing would "
                f"be the half a reviewer needed. Refused here rather than after the read, so the bound is a "
                f"bound on what this run holds as well as on what it writes."
            )
            raise KevEvidenceError(message)
    return CurrentEvidence(
        findings=tuple(current[key] for key in sorted(current)),
        excluded=matched_total - fresh,
        observed=observed,
        matched=matched_total > 0,
    )


def stale_clause(excluded: int) -> str:
    """Return what a run says about the findings it left out, or nothing.

    Written onto **every** row a run produces rather than onto one of them, and the
    duplication is the point: a reader holds one row, not a run, and a row computed
    against a partial view must say so wherever it is read. It is the run's fact
    rather than the advisory's, so it is composed onto the row's own reason in
    `_row_for` rather than carried inside a `CrossReference`.

    Args:
        excluded: How many matched findings were older than the freshness target.

    Returns:
        The clause, or the empty string when nothing was excluded.

    """
    if not excluded:
        return ""
    return (
        f" (this run excluded {excluded} advisory observation(s) older than this collector's freshness target "
        f"of {KEV_FRESHNESS_TARGET}, which are stale rather than current)"
    )


def catalog_in(body: object, *, source: str) -> Catalog:
    """Read one KEV catalog document into the entries and schemes it states, or refuse it.

    Pure: no database, no clock, no network.

    **An empty catalog is an answer rather than a defect.** A document stating no
    entries cross-references every current finding whose scheme it uses to
    `not_listed` -- which, since it uses none, is none of them: an empty catalog
    states no scheme, so every finding reads as `unknown`. That is the safe
    direction and it falls out of the rule rather than being a special case.

    Args:
        body: The catalog document the declared adapter recorded. Typed as `object`
            because a `Payload` is a value a third-party adapter built: a body that
            is not a string is refused by name here rather than raising a `TypeError`
            from `len()` that names no source.
        source: The locator it recorded it for, named in the refusal messages.

    Returns:
        The catalog: entries keyed by case-folded identifier and alias, and the set
        of identifier schemes it uses.

    Raises:
        KevDocumentError: When the body is not a string, is longer than
            `MAX_CATALOG_CHARACTERS`, is not JSON, or is not an object; when it
            carries a field the document contract does not define; when `entries`
            is not a list of objects, carries an undefined field, omits or blanks
            the advisory identifier, states one of the wrong type, states `aliases`
            that is not a list of identifiers or states more than `MAX_ALIASES` of
            them, states a `date_added` that is neither a string nor null or one
            longer than `MAX_ECHOED_CHARACTERS`, names one advisory twice under any
            of its spellings, or states more entries than `MAX_ENTRIES`; or when the
            source recorded a locator wider than the column that has to hold it or
            carrying a control character.

    """
    _require_storable(source, field="source", source=source, what="locator")
    document = _document_in(body, source=source)
    undefined = sorted(set(document) - DOCUMENT_FIELDS)
    if undefined:
        message = (
            f"{source} served a catalog carrying the field(s) {undefined}, which the document contract does not "
            f"define. The run is refused rather than the field ignored: a catalog that grew a truncation or "
            f"partial-answer flag would otherwise have it dropped, and this collector would record that the "
            f"catalog does not list advisories it had simply not finished listing."
        )
        raise KevDocumentError(message)
    stated = _entries_stated(document, source=source)
    entries: dict[str, CatalogEntry] = {}
    schemes: set[str] = set()
    repeated: list[str] = []
    for position, entry in enumerate(stated):
        listed, spellings = _entry(entry, source=source, position=position)
        for spelling in spellings:
            key = spelling.casefold()
            seen = entries.get(key)
            if seen is not None:
                # Both spellings, because the pair is what a reader has to go and
                # reconcile in the catalog -- naming only the second would send them
                # looking for a duplicate of a string that appears once.
                repeated.extend((seen.advisory_id, listed.advisory_id))
            entries[key] = listed
            schemes.add(_scheme_of(spelling))
    _refuse_repeated_advisories(repeated, source=source)
    return Catalog(entries=entries, schemes=frozenset(schemes))


def cross_reference(findings: Sequence[CurrentFinding], catalog: Catalog) -> tuple[CrossReference, ...]:
    """Cross-reference a package's current advisories against a catalog.

    Pure: no database, no clock, no network. The whole of what this collector
    decides once both halves are in hand, and the reason it is a function rather
    than a branch inside `translate`: the rule is testable against literals, and
    the two halves come from places that could not be further apart -- one is this
    product's own evidence and one is a third party's document.

    Args:
        findings: The package's current advisories, newest per advisory.
        catalog: What the source served, read.

    Returns:
        One cross-reference per finding, in the order the findings were given.
        Empty when the package has no current finding -- which is a caller's to
        interpret, because "there was nothing to cross-reference" is a statement
        about our own evidence rather than about the catalog.

    """
    return tuple(_answer_for(finding, catalog) for finding in findings)


def _answer_for(finding: CurrentFinding, catalog: Catalog) -> CrossReference:
    """Return what the catalog says about one advisory, or that it cannot say.

    Args:
        finding: The advisory this product currently records.
        catalog: What the source served, read.

    Returns:
        The cross-reference: `listed` with the catalog's date, `listed` with a
        blank date and the reason it is blank, `not_listed` where the catalog uses
        this identifier's scheme and states nothing under it, or `unknown` where it
        does not use the scheme at all.

    """
    listed = catalog.entries.get(finding.advisory_id.casefold())
    if listed is not None:
        return CrossReference(
            finding_id=finding.finding_id,
            package_id=finding.package_id,
            state=LISTED,
            catalog_date_added=listed.date_added,
            detail=listed.fault,
        )
    if _scheme_of(finding.advisory_id) in catalog.schemes:
        return CrossReference(
            finding_id=finding.finding_id,
            package_id=finding.package_id,
            state=NOT_LISTED,
            catalog_date_added=None,
            detail=NOT_LISTED_DETAIL,
        )
    return CrossReference(
        finding_id=finding.finding_id,
        package_id=finding.package_id,
        state=KEV_UNKNOWN,
        catalog_date_added=None,
        detail=UNKNOWN_SCHEME_DETAIL,
    )


def _scheme_of(identifier: str) -> str:
    """Return the issuing scheme an advisory identifier declares, case-folded.

    A prefix convention rather than a registry, and stated as one: every advisory
    scheme in use spells its identifiers `<SCHEME>-<the rest>` -- `CVE-2024-23334`,
    `GHSA-5h86-8mv2-jq9f`, `PYSEC-2024-42`, `RUSTSEC-2021-0079` -- so the segment
    before the first separator is the scheme. Nothing here validates that the
    scheme *exists*, because a closed list of schemes would be this module deciding
    which catalogues are real, and that is PRD Open Question 1's.

    **Failing to recognise a scheme fails toward `unknown`**, which is the direction
    that matters: an identifier with no separator answers with itself, matches no
    catalog scheme, and produces `unknown` rather than the reassuring value.

    Args:
        identifier: The advisory identifier, already stripped.

    Returns:
        The case-folded scheme, or the case-folded identifier when it carries no
        separator.

    """
    return identifier.partition("-")[0].casefold()


def _entries_stated(document: dict[str, object], *, source: str) -> list[object]:
    """Return the entries a catalog states, or refuse a list it cannot be read as.

    Args:
        document: The decoded document.
        source: The locator, for the messages.

    Returns:
        The entries, in the catalog's own order. Empty where the field is absent or
        null -- both of which mean the catalog listed nothing, which is an answer
        rather than a defect.

    Raises:
        KevDocumentError: When the field is present, is not null, and is not a
            list, or when it states more entries than `MAX_ENTRIES`.

    """
    entries = document.get(ENTRIES_FIELD)
    if entries is None:
        return []
    if not isinstance(entries, list):
        message = (
            f"{source} served a catalog whose {ENTRIES_FIELD!r} is {type(entries).__name__} rather than a list. "
            f"A source whose shape has changed is refused rather than read for whatever still parses."
        )
        raise KevDocumentError(message)
    if len(entries) > MAX_ENTRIES:
        message = (
            f"{source} states {len(entries)} catalog entries, and this collector reads at most {MAX_ENTRIES}. "
            f"Refused rather than truncated: cross-referencing against the first {MAX_ENTRIES} of a longer "
            f"catalog would record that advisories the catalog lists are not listed."
        )
        raise KevDocumentError(message)
    return entries


def _entry(entry: object, *, source: str, position: int) -> tuple[CatalogEntry, tuple[str, ...]]:
    """Turn one stated catalog entry into what it is worth, refusing anything it cannot be.

    Args:
        entry: One element of the catalog's entry list.
        source: The locator, for the messages.
        position: Where it sat, so a refusal names the entry a reader can find
            rather than only saying that one of them was wrong.

    Returns:
        The entry, carrying either a recordable date or the reason there is none;
        and every spelling it is to be found under -- its own identifier first, then
        each alias it stated.

    Raises:
        KevDocumentError: When the entry is not an object, carries an undefined
            field, omits or blanks its advisory identifier, states one that is not a
            string, states `aliases` that is not a list of identifiers or too many
            of them, states a `date_added` that is neither a string nor null, or
            states a value wider than the column or the echo bound that holds it.

    """
    if not isinstance(entry, dict):
        message = (
            f"{source} states {type(entry).__name__} at position {position} rather than a catalog entry. Every "
            f"entry names the advisory the catalog added (CPM-FR-12)."
        )
        raise KevDocumentError(message)
    undefined = sorted(set(entry) - ENTRY_FIELDS)
    if undefined:
        message = (
            f"{source} states a catalog entry at position {position} carrying the field(s) {undefined}, which "
            f"the entry contract does not define. The document is refused rather than the field ignored: a "
            f"silently dropped field is a source that believes it supplied one, and PRD Appendix A.2 gives this "
            f"table two facts rather than whichever ones a catalog happens to send."
        )
        raise KevDocumentError(message)
    advisory_id = _required_string(entry, field=ADVISORY_ID_FIELD, source=source, position=position)
    spellings = (advisory_id, *_aliases_stated(entry, source=source, position=position))
    return _dated(entry, advisory_id=advisory_id, source=source, position=position), spellings


def _aliases_stated(entry: dict[str, object], *, source: str, position: int) -> tuple[str, ...]:
    """Return the other identifiers a catalog entry says the same advisory carries.

    **Stating them is what makes `not_listed` trustworthy**, which is why they are
    part of the contract at all: a finding recorded under a GHSA identifier, against
    an advisory the catalog lists under its CVE spelling, would otherwise read as an
    advisory the catalog does not list -- an established negative the run did not
    establish, permanently, about whether something is being exploited.

    Args:
        entry: The catalog entry.
        source: The locator, for the messages.
        position: Where the entry sits, for the messages.

    Returns:
        The aliases, stripped, in the catalog's own order. Empty where the field is
        absent or null.

    Raises:
        KevDocumentError: When the field is present, is not null and is not a list;
            when it states more than `MAX_ALIASES`; or when an element is not a
            non-blank string that fits the column an identifier is compared against.

    """
    stated = entry.get(ALIASES_FIELD)
    if stated is None:
        return ()
    if not isinstance(stated, list):
        message = (
            f"{source} states a catalog entry at position {position} whose {ALIASES_FIELD!r} is "
            f"{type(stated).__name__} rather than a list. A source whose shape has changed is refused rather "
            f"than read past."
        )
        raise KevDocumentError(message)
    if len(stated) > MAX_ALIASES:
        message = (
            f"{source} states {len(stated)} aliases for the entry at position {position}, and this collector "
            f"reads at most {MAX_ALIASES}. An advisory issued under a handful of schemes carries a handful of "
            f"identifiers; more is a source doing something else."
        )
        raise KevDocumentError(message)
    aliases: list[str] = []
    for index, alias in enumerate(stated):
        if not isinstance(alias, str) or not alias.strip():
            message = (
                f"{source} states {alias!r} as alias {index} of the entry at position {position}. An alias is "
                f"another identifier the same advisory is issued under, so it is a non-blank string or it is "
                f"nothing -- and a blank one would key every unnamed advisory to this entry."
            )
            raise KevDocumentError(message)
        stripped = alias.strip()
        _require_storable(stripped, field=ADVISORY_ID_FIELD, source=source, what="alias")
        aliases.append(stripped)
    return tuple(aliases)


def _dated(entry: dict[str, object], *, advisory_id: str, source: str, position: int) -> CatalogEntry:
    """Return one catalog entry with the date it stated, or the reason it has none.

    Args:
        entry: The catalog entry.
        advisory_id: Its identifier, already checked.
        source: The locator, for the messages.
        position: Where the entry sits, for the messages.

    Returns:
        The entry.

    Raises:
        KevDocumentError: When `date_added` is neither a string nor null, carries a
            control character, or is longer than `MAX_ECHOED_CHARACTERS` -- the last
            two because an unreadable date is echoed onto a row, and a value this
            module puts into an append-only column passes the same guard every
            stored value passes.

    """
    stated = entry.get(DATE_ADDED_FIELD)
    if stated is not None and not isinstance(stated, str):
        message = (
            f"{source} states a catalog entry at position {position} whose {DATE_ADDED_FIELD!r} is "
            f"{type(stated).__name__} rather than a string. A source whose shape has changed is refused rather "
            f"than read past -- a date this collector cannot even attempt to read is different from one it "
            f"attempted and could not."
        )
        raise KevDocumentError(message)
    if stated is None or not stated.strip():
        return CatalogEntry(advisory_id=advisory_id, date_added=None, fault=NO_CATALOG_DATE_DETAIL)
    shown = stated.strip()
    _require_echoable(shown, source=source, position=position)
    instant = _instant(shown)
    if instant is None:
        return CatalogEntry(
            advisory_id=advisory_id,
            date_added=None,
            fault=f"{UNREADABLE_CATALOG_DATE_DETAIL}: the catalog states {shown!r}",
        )
    if not EARLIEST_CATALOG_DATE <= instant <= LATEST_CATALOG_DATE:
        return CatalogEntry(
            advisory_id=advisory_id,
            date_added=None,
            fault=f"{OUT_OF_RANGE_CATALOG_DATE_DETAIL}: the catalog states {shown!r}",
        )
    return CatalogEntry(advisory_id=advisory_id, date_added=instant, fault="")


def _instant(value: str) -> datetime | None:
    """Return an aware instant a catalog stated, or `None` where it stated one that cannot be read.

    Args:
        value: What the entry carried for its date, already known to be a non-blank
            string.

    Returns:
        The parsed instant, or `None` when the value does not parse or parses to a
        naive one. A naive value is discarded rather than assumed to be UTC, on the
        terms `collectors/source_release.py` discards one: there is no offset to
        convert from, and an instant shifted by a guess would be written into a row
        nothing may correct (`CPM-AD-26`). A bare date -- which is the shape a
        catalog is likeliest to publish -- parses naive and is therefore recorded
        as missing with a reason, rather than as midnight in a timezone nobody
        stated.

    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if is_aware(parsed) else None


def _refuse_repeated_advisories(repeated: Sequence[str], *, source: str) -> None:
    """Refuse a catalog that reaches one advisory under two entries.

    Two entries keyed to one identifier -- whether by their own spellings or through
    an alias one of them stated -- are two claims about the same advisory in one
    document, and there is no rule for choosing between them that is not an
    invention. The dates in particular could differ, and the date is half of what
    `CPM-FR-12` records.

    Args:
        repeated: The identifiers that collided, in the catalog's own spelling.
        source: The locator, for the message.

    Raises:
        KevDocumentError: When any advisory was reachable under more than one entry.

    """
    if repeated:
        named = sorted(set(repeated))
        message = (
            f"{source} reaches the advisory(ies) {named} under more than one entry, compared without regard to "
            f"case and counting every alias stated. One catalog states one date per advisory; two entries for "
            f"one identifier are a source contradicting itself, and choosing between them would be an "
            f"invention -- and the date is half of what a KEV finding records (CPM-FR-12)."
        )
        raise KevDocumentError(message)


def _document_in(body: object, *, source: str) -> dict[str, object]:
    """Decode a catalog document and refuse anything that is not an object.

    Args:
        body: The document the adapter recorded, as it was recorded.
        source: The locator it was recorded for, for the messages.

    Returns:
        The decoded object.

    Raises:
        KevDocumentError: When the body is not a string, is too long to decode, is
            not JSON, or is not an object.

    """
    if not isinstance(body, str):
        message = (
            f"{source} recorded a payload whose body is {type(body).__name__} rather than a string. A Payload "
            f"is a value a third-party adapter built, so its body is checked here rather than left to raise a "
            f"TypeError from a length check that names no source."
        )
        raise KevDocumentError(message)
    if len(body) > MAX_CATALOG_CHARACTERS:
        message = (
            f"{source} served {len(body)} characters, and this collector decodes at most "
            f"{MAX_CATALOG_CHARACTERS}. The public catalogue this product would read is under a hundred "
            f"kilobytes in this schema, so a document this size is a source doing something else -- and parsing "
            f"it would spend a worker's soft time limit finding out (CPM-AD-9)."
        )
        raise KevDocumentError(message)
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError) as unreadable:
        # Three rather than one, on the terms `collectors/vulnerability.py` states:
        # `json.loads` recurses per level of nesting, so a deeply nested body
        # raises `RecursionError`, and a body that reached here as bytes raises
        # `UnicodeDecodeError` for an undecodable one. The `TypeError` that module
        # also catches is unreachable here, because a body that is not a string is
        # refused above by name.
        message = (
            f"{source} did not serve a readable KEV catalog: {type(unreadable).__name__}: {unreadable}. The "
            f"observation is refused rather than recorded as a catalog that lists none of this package's "
            f"advisories, which is the reassuring-looking result CPM-SM-2 forbids."
        )
        raise KevDocumentError(message) from unreadable
    if not isinstance(document, dict):
        message = (
            f"{source} served {type(document).__name__} rather than an object. A source whose shape has changed "
            f"is refused rather than read for whatever still parses."
        )
        raise KevDocumentError(message)
    return document


def _required_string(entry: dict[str, object], *, field: str, source: str, position: int) -> str:
    """Return a field a catalog entry must state, or refuse the document.

    Args:
        entry: The catalog entry.
        field: Which field to read.
        source: The locator, for the message.
        position: Where the entry sits, for the message.

    Returns:
        The stripped string.

    Raises:
        KevDocumentError: When the field is absent, is not a string, is blank once
            stripped, or is wider than the column that records it.

    """
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        message = (
            f"{source} states a catalog entry at position {position} whose {field!r} is {value!r}. Every entry "
            f"names the advisory it is about (CPM-FR-12); one that does not cannot be cross-referenced against "
            f"anything."
        )
        raise KevDocumentError(message)
    stripped = value.strip()
    _require_storable(stripped, field=field, source=source, what=field.replace("_", " "))
    return stripped


def _require_echoable(value: str, *, source: str, position: int) -> None:
    """Refuse a value this collector would copy into an append-only row's reason.

    The one value a catalog states that lands in `detail` rather than in a column
    of its own is the date it stated and this collector could not read. `detail` is
    a `TextField` and declares no width, so nothing else bounds it -- and
    `core/collection.py` copies a row's reason into the ledger row and into every
    structured log line the run emits.

    Args:
        value: The stated date, stripped.
        source: The locator, for the message.
        position: Where the entry sits, for the message.

    Raises:
        KevDocumentError: When it carries a control character or is longer than
            `MAX_ECHOED_CHARACTERS`. Refused rather than shortened, unlike a
            sentinel's reason: this one is a *fact the entry claimed*, and a
            shortened date is a different date.

    """
    if _CONTROL_CHARACTERS.search(value):
        message = (
            f"{source} states a date added carrying a control character at position {position}. The observation "
            f"is refused rather than cleaned: a value this collector rewrote is not the value the source "
            f"published, and one it stored unchanged is a row PostgreSQL refuses from inside the driver, "
            f"outside the guard that would have recorded the failure."
        )
        raise KevDocumentError(message)
    if len(value) > MAX_ECHOED_CHARACTERS:
        message = (
            f"{source} states a date added of {len(value)} characters at position {position}, and this "
            f"collector copies at most {MAX_ECHOED_CHARACTERS} of a stated value onto a row. A date is short; a "
            f"value this long is a source putting something else in the field."
        )
        raise KevDocumentError(message)


def _safe_detail(text: str) -> str:
    """Return a reason that can be stored, however the caller built it.

    The opposite posture from `_require_echoable`, and the difference is the path:
    this one is called where a sentinel row is being shaped, which is a path already
    recording a failure and one `CPM-NFR-3` requires to write a row. The reason
    arriving there is the base's own sentence with a third party's exception message
    inside it, so raising over its shape would turn "the source failed" into "no row
    at all".

    Args:
        text: The reason the base composed.

    Returns:
        The reason with control characters removed and, where it was longer than
        `MAX_SENTINEL_DETAIL_CHARACTERS`, shortened with a marker saying so.

    """
    cleaned = _CONTROL_CHARACTERS.sub(" ", text)
    if len(cleaned) > MAX_SENTINEL_DETAIL_CHARACTERS:
        return f"{cleaned[:MAX_SENTINEL_DETAIL_CHARACTERS]} {SHORTENED_DETAIL}"
    return cleaned


def _require_storable(value: str, *, field: str, source: str, what: str) -> None:
    """Refuse a value wider than the column that has to hold it.

    Refused where the value enters rather than where it lands, on the terms
    `collectors/vulnerability.py` states: `max_length` is enforced by PostgreSQL
    and ignored by SQLite, so an over-long value is a stored row on a developer's
    machine and a failed run in the gate (`R-5`).

    **The width is read off `vulnerability_findings` for an advisory identifier**,
    because that is the column an identifier is compared against: nothing on
    `kev_findings` stores one. A catalog stating an identifier wider than that
    column is stating one no vulnerability finding could ever carry, so it could
    never match anything. That read couples this module to the sibling table's
    *schema* as well as to its rows, which is a second kind of dependency and is
    named as one in `CPM-SECURITY-S02`'s Spec Change Log.

    Args:
        value: What the document said.
        field: The column it is measured against.
        source: The locator, for the message.
        what: What the value is, for the message.

    Raises:
        KevDocumentError: When it is wider than the column, or when it carries a
            control character. The second is refused here for the reason the first
            is and one more: PostgreSQL rejects a NUL byte from the driver rather
            than from the query, which raises outside the guard `translate` is
            wrapped in -- so an unrefused one escapes as neither a document refusal
            nor a recorded observation.

    """
    if _CONTROL_CHARACTERS.search(value):
        message = (
            f"{source} states a {what} carrying a control character. The observation is refused rather than "
            f"cleaned: a value this collector rewrote is not the value the source published, and one it stored "
            f"unchanged is a row PostgreSQL refuses from inside the driver, outside the guard that would have "
            f"recorded the failure."
        )
        raise KevDocumentError(message)
    width = _column_width(field)
    if len(value) > width:
        message = (
            f"{source} states a {what} of {len(value)} characters, and the column that holds it takes {width}. "
            f"The observation is refused rather than truncated: a truncated advisory identifier names a "
            f"different advisory, and one wider than the column is one no vulnerability finding could carry."
        )
        raise KevDocumentError(message)


def _column_width(field: str) -> int:
    """Return how wide one of the two security tables' text columns is.

    Read off the models rather than restated, so the bound a value is refused
    against is the bound the tables actually enforce. `source` is this table's own
    and `advisory_id` is `vulnerability_findings`' -- see `_require_storable` for
    why an identifier is measured against the table that stores one.

    **A column that declares no width is a refusal rather than a skip**, on the
    terms `collectors/vulnerability.py` states: a guard that answered `None` for
    such a column would have every caller write `if width is not None and ...`, so
    a field renamed or turned into a `TextField` would silently turn its refusal
    off with nothing anywhere failing.

    Args:
        field: The column's name.

    Returns:
        Its `max_length`.

    Raises:
        CollectorConfigurationError: When the column is not a `CharField`, or
            declares no `max_length`. A defect in this module or in the models
            beside it, and never something a source can cause.

    """
    model = VulnerabilityFinding if field == ADVISORY_ID_FIELD else KevFinding
    column = model._meta.get_field(field)  # noqa: SLF001 - Django's own public-by-convention API
    width = column.max_length if isinstance(column, models.CharField) else None
    if width is None:
        message = (
            f"{model.__name__}.{field} declares no max_length, so there is no bound to refuse an over-wide "
            f"value against. Refused rather than skipped: a width guard that quietly stops guarding is one that "
            f"stores whatever a source sends on SQLite and fails the run on PostgreSQL (R-5)."
        )
        raise CollectorConfigurationError(message)
    return width


def _nothing_to_collect() -> Iterator[int]:
    """Yield no package, and say once why there is nothing to collect.

    The empty selection an undeclared component offers, and one of the two events
    this module emits. A dispatch over an empty selection finalizes `succeeded` with
    nothing enqueued, which is byte-identical to a healthy day on which nothing
    needed collecting -- so without this line the only way to learn that a
    component has stopped cross-referencing against the KEV catalog, or that
    somebody withdrew its source from a running process, is to notice that it never
    writes a row.

    **A generator rather than an empty queryset, and the laziness is the point**,
    on the terms `collectors/vulnerability.py`'s own empty selection states:
    `collectors/sweep.py` streams the selection while `cadence_reconciliation_fault`
    only tests whether it is `None`, so logging where the selection is *built*
    would emit a warning inside every start-up reconciliation -- including the ones
    `tests/integration/startup/test_stage_two_served_path.py` asserts emit nothing
    in place of raising.

    Yields:
        Nothing. The annotation is `Iterator[int]` because that is what a selection
        is; this one is empty.

    """
    logger.warning(
        NO_KEV_SOURCE_EVENT,
        collector=COLLECTOR_NAME,
        detail=(
            f"{COLLECTOR_NAME} has no declared KEV source, so no package was selected and nothing will be "
            f"observed about whether any advisory this product records is known to be exploited. Adapters are "
            f"declared and never discovered (AD-8, CPM-AD-29); see docs/deployment.md."
        ),
    )
    # `yield from ()` rather than `return; yield`: both make this a generator and
    # only one of them is a statement the suite executes, so the other would need a
    # coverage pragma -- which `tests/unit/test_coverage_policy.py` forbids
    # outright.
    yield from ()


class KevCollector(Collector):
    """The collector that cross-references a package's advisories against the KEV catalog. Writes `kev_findings`.

    Four hooks and ten declarations. See the module docstring for the one read this
    collector makes that `CPM-AD-7` does not grant, for why no KEV source ships,
    for why a package with nothing to cross-reference still writes a row, and for
    why `sentinel_evidence_rows` is not overridden.
    """

    #: The nine declarations the base checks at construction, every one written out
    #: on the terms `SourceReleaseCollector` gives.
    name: ClassVar[str] = COLLECTOR_NAME

    evidence_model: ClassVar[type[AppendOnlyModel] | None] = KevFinding

    observation_window: ClassVar[timedelta | None] = KEV_OBSERVATION_WINDOW

    timeout: ClassVar[float | None] = KEV_TIMEOUT

    retries: ClassVar[int] = KEV_RETRIES

    rate_limit: ClassVar[RateLimit] = KEV_RATE_LIMIT

    headers: ClassVar[Mapping[str, str]] = KEV_HEADERS

    freshness_target: ClassVar[timedelta | None] = KEV_FRESHNESS_TARGET

    response_cache_ttl: ClassVar[timedelta | None] = KEV_CACHE_TTL

    #: How often the full-inventory sweep dispatches this collector
    #: (`CPM-CURRENCY-S05`). Bound to the module constant the target and the window
    #: are already derived from, so no number moves; `collectors/apps.py` reconciles
    #: it against this collector's `CELERY_BEAT_SCHEDULE` entry at boot, in both
    #: directions. The entry's *phase* is `KEV_DISPATCH_OFFSET` and is not part of
    #: that reconciliation -- see that constant.
    cadence: ClassVar[timedelta | None] = KEV_CADENCE

    @classmethod
    def selectable_packages(cls) -> Iterable[int]:
        """Return the packages this collector can be asked about: every one, or none at all.

        **With no KEV source declared it is nothing, and that is the whole point.**
        No source ships (PRD Open Question 1), and `collectors/tasks.py`'s task
        refuses -- so a selection that offered packages anyway would have a
        scheduled sweep enqueue ten thousand tasks a day, every one of which
        records a failed run that observed nothing. So an undeclared component
        selects nothing, the dispatch records one `succeeded` row saying the
        selection was empty, and drawing that empty selection emits
        `NO_KEV_SOURCE_EVENT`.

        **With one declared it is the whole inventory, including packages this
        product records no advisory for.** Selecting only packages that already
        have a vulnerability finding would look like an optimisation and would be
        the defect `CPM-SECURITY-S01` was patched for, in a second table: the
        package with nothing to cross-reference would never be enqueued, would
        write no row, and would read as never-observed -- which `core/freshness.py`
        reports as neither stale nor `unknown`. The `unknown` row this story exists
        to guarantee is only worth writing if a *scheduled* run writes it, so every
        package is offered and every package gets one.

        It would also be a selection built on another collector's evidence table,
        which is a second and wider version of the read this collector already
        argues for -- one made for convenience rather than because a requirement
        demands it.

        What that costs is one collection per package per day for packages with
        nothing to cross-reference, and the cost is accepted for the reason the
        sibling accepts it: "we had nothing to ask" is the observation `CPM-FR-6`
        asks for rather than a reason not to look. `docs/deployment.md` tells an
        operator that the selection is the whole inventory and what that spends.

        Returns:
            Every package's primary key, as a lazy queryset ordered by key --
            streamed by `collectors/sweep.py` rather than materialised -- or an
            empty *generator* when no KEV source is declared, which says why on
            first use -- see `_nothing_to_collect`.

        """
        if declared_kev_source() is None:
            return _nothing_to_collect()
        # The annotation is `Iterable[int]` rather than the queryset's own, which
        # django-stubs types as `Any` for a flat `values_list`: without it mypy
        # reports "returning Any" for a hook whose whole contract is what it
        # yields. It is not materialised -- the queryset is still lazy and
        # `collectors/sweep.py` still streams it.
        selected: Iterable[int] = Package.objects.order_by("pk").values_list("pk", flat=True)
        return selected

    # `inapplicability` is **not** overridden, and the omission is the decision.
    #
    # The base's default is "the question applies", and it does: any package at all
    # may have an advisory published against it and that advisory may enter the
    # catalog. A package with no current vulnerability finding is deliberately not
    # answered here either -- that would write `not_applicable`, which says the
    # question is not about this package, and it is; what is missing is our own
    # evidence, which may be missing merely because no advisory source is declared.
    # A KEV table recording "not applicable" for the whole inventory in that state
    # would be the fold `CPM-FR-6` forbids, so `translate` records it as `unknown`
    # and `kev_findings` refuses `not_applicable` outright.
    #
    # `VulnerabilityCollector` overrides the hook for a reason this collector does
    # not have: it remembers a run's identity between hooks and the override is
    # where the last run's is forgotten. Nothing here is remembered on the instance
    # -- the locator is a constant and the findings are read inside `translate` --
    # so an override would be a hook that exists to restate a default.
    # `tests/unit/django_apps/test_kev.py` asserts it is the base's by identity.

    def source_for(self, *, package_id: int) -> str:
        """Return the locator naming what this run asks the declared KEV source about.

        **The same locator on every run**, which is the one place this collector's
        shape differs from its sibling's: the catalog is one document about
        advisories rather than a question about a package, so there is nothing of
        this package's to put in it. What varies between runs is which of *our*
        findings are cross-referenced against the answer, and that is read in
        `translate` from this product's own evidence.

        Nothing about a package can make this hook fail, so unlike the sibling's it
        raises nothing: there is no identity to read, no purl to parse and no width
        to exceed -- `KEV_SOURCE_LOCATOR` is a constant, and
        `tests/unit/django_apps/test_kev.py` asserts it fits the column that
        records it.

        Args:
            package_id: The package being collected. Read by no branch here.

        Returns:
            `KEV_SOURCE_LOCATOR`.

        """
        return KEV_SOURCE_LOCATOR

    def translate(self, payload: Payload, *, package_id: int, observed_at: datetime) -> Sequence[AppendOnlyModel]:
        """Turn the catalog's answer into one row per current advisory, or one saying there were none.

        Args:
            payload: What the declared adapter said, recorded. Reached only for a
                call the adapter answered -- absence and failure are the base's to
                record. **Not read at all** when this package has no current
                vulnerability finding: there was nothing to cross-reference, so
                there is no answer to interpret, and reading one would let a
                catalog's document decide what a row about our own evidence says.
            package_id: The package the observation is about.
            observed_at: The instant to stamp every row with, from the injected
                clock. The base refuses a row stamped with anything else, and it is
                also the instant the freshness window is measured back from.

        Returns:
            One unsaved `KevFinding` per current advisory, ordered by advisory
            identifier, or exactly one carrying `unknown`.

        Raises:
            KevDocumentError: When the catalog cannot be read as what it claims to
                be. The base writes an `error` row and re-raises.
            KevEvidenceError: When this package has more current advisories than one
                collection may record, or when one of them names no advisory --
                both raised from `current_findings`. The base writes an `error` row
                and re-raises.

        """
        evidence = current_findings(package_id=package_id, now=observed_at)
        if not evidence.findings:
            return [
                KevFinding(
                    observed_at=observed_at,
                    package_id=package_id,
                    trace_id=current_trace_id(),
                    source=KEV_SOURCE_LOCATOR,
                    state=KEV_UNKNOWN,
                    vulnerability_finding_id=None,
                    catalog_date_added=None,
                    detail=f"{self._nothing_current(evidence)}{stale_clause(evidence.excluded)}",
                ),
            ]
        catalog = catalog_in(payload.body, source=payload.source)
        excluded = stale_clause(evidence.excluded)
        return [
            self._row_for(answer, observed_at=observed_at, source=payload.source, excluded=excluded)
            for answer in cross_reference(evidence.findings, catalog)
        ]

    def sentinel_evidence(
        self,
        *,
        state: OutcomeState,
        package_id: int,
        observed_at: datetime,
        detail: str,
    ) -> AppendOnlyModel:
        """Return one row carrying the sentinel the base decided on.

        Every catalog fact is absent and the link is null: a sentinel row is
        written for a call that produced no catalog at all, so it derives from no
        finding.

        **A `not_found` row carries a caveat the base cannot know to write, and an
        event beside it.** On every sibling table `not_found` means the *observed
        thing* is not there; here the base reaches it when the KEV source says the
        **locator** is not there, which is a withdrawn or misconfigured source
        rather than a package with nothing known-exploited against it -- and the
        base finalizes that run `succeeded`, because the source answered. Left with
        only the base's own sentence it would be the one row in this table a reader
        could mistake for reassuring, under a clean-looking ledger, for a whole day.
        So the caveat is appended and `CATALOG_ABSENT_EVENT` is emitted.

        Args:
            state: `OutcomeState.ERROR` or `OutcomeState.NOT_FOUND`, decided by the
                base.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with.
            detail: What happened, in words worth storing beside the state. Cleaned
                and bounded rather than trusted -- see `_safe_detail`: on the
                `error` path it carries a third party's exception message.

        Returns:
            One unsaved `KevFinding` carrying the state's value verbatim in `state`
            (`CPM-AD-24`).

        Raises:
            CollectorConfigurationError: When asked for a state this collector has
                no row shape for -- `ok`, `unknown` or `not_applicable`. `ok`
                because it is not in this vocabulary at all: the determinate values
                are `listed` and `not_listed`, and that is the whole of why the
                vocabulary is composed. `unknown` because that row is `translate`'s
                to write with the reason the run established, and one shaped here
                would carry the base's reason for a state the base never decides.
                `not_applicable` because a KEV question applies to every package,
                so `inapplicability` never answers a reason and the base never
                asks -- and `kev_findings` refuses it outright.

        """
        # Written as two comparisons rather than as membership of a declared set,
        # for the reason `VulnerabilityCollector.sentinel_evidence` gives:
        # `tests/unit/django_apps/test_single_ordering_audit.py` reads a literal
        # holding two or more `OutcomeState` members outside `core/outcomes.py` as
        # a second precedence order, and it is right to.
        if state is not OutcomeState.ERROR and state is not OutcomeState.NOT_FOUND:
            message = (
                f"{type(self).__name__}.sentinel_evidence was asked for {state.value!r}, and this collector "
                f"shapes a sentinel row for {OutcomeState.ERROR.value!r} and {OutcomeState.NOT_FOUND.value!r} "
                f"only. A KEV question applies to every package, so there is no "
                f"{OutcomeState.NOT_APPLICABLE.value!r} row to write -- kev_findings refuses one outright; "
                f"{OutcomeState.UNKNOWN.value!r} is written by translate with the reason the run established; "
                f"and {LISTED!r} and {NOT_LISTED!r} are cross-references, which a sentinel path never has."
            )
            raise CollectorConfigurationError(message)
        reason = _safe_detail(detail)
        if state is OutcomeState.NOT_FOUND:
            reason = f"{reason}: {UNKNOWN_LOCATOR_DETAIL}"
            logger.warning(
                CATALOG_ABSENT_EVENT,
                collector=COLLECTOR_NAME,
                package_id=package_id,
                source=KEV_SOURCE_LOCATOR,
                detail=(
                    f"the declared KEV source reports that {KEV_SOURCE_LOCATOR} does not exist, so this run "
                    f"recorded {OutcomeState.NOT_FOUND.value!r} under a succeeded ledger row. That is a "
                    f"withdrawn or misconfigured catalog rather than a package with nothing known-exploited "
                    f"against it; see docs/deployment.md."
                ),
            )
        # `state.value` rather than this vocabulary's own constant, and the two are
        # the same string by construction: `outcome_type` builds every composed
        # vocabulary from `SENTINEL_MEMBERS` and `verify_sentinels` refuses one
        # whose sentinel carries a different value, so an `OutcomeState` sentinel
        # *is* a `KevOutcome` value. `tests/unit/django_apps/test_kev.py` asserts
        # that relation rather than leaving it to be assumed here.
        return KevFinding(
            observed_at=observed_at,
            package_id=package_id,
            trace_id=current_trace_id(),
            source=KEV_SOURCE_LOCATOR,
            state=state.value,
            vulnerability_finding_id=None,
            catalog_date_added=None,
            detail=reason,
        )

    def _nothing_current(self, evidence: CurrentEvidence) -> str:
        """Return which of the four ways this package had nothing to cross-reference.

        `CPM-FR-6` is the whole of why this is four sentences rather than one: "no
        advisory source is declared", "the advisory collector has not observed this
        package", "it observed it and matched nothing" and "everything it matched
        has gone stale" are four different pieces of work for an operator, and only
        the third is a statement about the package rather than about this product.

        The advisory source is asked first because it explains the two silences
        underneath it: with no source declared, `VulnerabilityCollector` selects no
        package, so nothing has been observed and nothing could have matched.
        Reading that slot is a read of a *declaration* rather than of another
        collector -- `collectors/advisories.py` is the seam, not a collector -- and
        it is the only way this row can tell an unconfigured component from an
        observed package with nothing against it.

        Args:
            evidence: What the read of the sibling table found, and did not.

        Returns:
            The reason, in words worth storing on a permanent row.

        """
        if declared_advisory_source() is None:
            return NO_ADVISORY_SOURCE_DETAIL
        if not evidence.observed:
            return NOTHING_OBSERVED_DETAIL
        if evidence.matched:
            return ONLY_STALE_FINDINGS_DETAIL
        return NOTHING_MATCHED_DETAIL

    def _row_for(
        self,
        answer: CrossReference,
        *,
        observed_at: datetime,
        source: str,
        excluded: str,
    ) -> KevFinding:
        """Return the evidence row one cross-reference earns.

        The one place a `CrossReference` becomes a row, so no later branch can come
        to disagree about which column a fact lands in.

        **The package comes from the finding rather than from the run**, which is
        what makes a row pairing one package with another's observation unreachable
        from this writer -- see `KevFinding.save` for why that invariant cannot be
        expressed as a check constraint and what closes it for every other writer.

        Args:
            answer: What the catalog said about one of this package's advisories.
            observed_at: The instant to stamp it with.
            source: The locator this row's facts came from -- the adapter's own,
                because a determinate row names where its facts came from and the
                catalog is the adapter's business (`CPM-AD-29`).
            excluded: What this run says about the observations it left out as
                stale, or the empty string. A property of the run rather than of the
                advisory, so it is composed here rather than carried inside the
                answer.

        Returns:
            The unsaved row, carrying AC 1's link by foreign key rather than by a
            copied identifier.

        """
        return KevFinding(
            observed_at=observed_at,
            package_id=answer.package_id,
            trace_id=current_trace_id(),
            source=source,
            state=answer.state,
            vulnerability_finding_id=answer.finding_id,
            catalog_date_added=answer.catalog_date_added,
            detail=f"{answer.detail}{excluded}".strip(),
        )
