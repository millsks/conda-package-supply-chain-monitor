"""What each monitored channel says a package is licensed under, raw and normalized.

`CPM-FR-13`: record the licence a package is under, as the source stated it and
as an SPDX expression beside it. This module is that collector, the third surface
`CPM-EP-SECURITY` records, and the eighth collector this component runs.

**Two columns, and the second one is only worth having because the first
survives.** `CPM-SECURITY-S03`'s AC 1 exists so a compliance reviewer can "see
what normalization did before I trust its result", which is answerable only if the
raw string and the expression sit side by side on one row. So the raw value is
recorded **verbatim** on every row that has one -- including the rows
normalization refused, where it matters most: an `unknown` row carrying the raw
string is a review item somebody can act on, and an `unknown` row carrying nothing
is an absence of information. `license_findings`' constraint is asymmetric for
exactly that reason.

**An unrecognised licence records `unknown`, never a permissive value.** AC 2
says so in as many words and `CPM-SM-2` measures this product on zero findings
presenting an unknown as clean. `collectors/spdx.py` refuses what it does not
recognise rather than guessing at it -- `BSD` alone is two-clause or three-clause,
and the difference is a legal obligation -- so the row says the licence needs
review and names the part of it that stopped.

**Refusing a value and refusing to normalize it are two different things, and only
one of them fails a run.** What a channel states is refused outright only where the
database itself will not hold it -- a NUL byte, a lone surrogate, a value wider than
its column -- because those raise from inside the driver, past every guard. A value
the database *will* hold and this product will not read as an identifier -- a
licence stated across two lines, say, which is ordinary in conda metadata -- is an
`unknown` row carrying the raw string and a reason. The difference matters because a
refusal here costs every *other* channel its answer: `translate` returns one
sequence, so a raise for channel one writes `error` rows for channels two onward
without asking them, and does it again tomorrow.

**"Routes to manual review" is a row a review queue will select, and not a queue
item.** `CPM-AD-22` gives every workflow queue item to one application that does
not exist yet and `CPM-EP-APP` owns it, so this story records the reviewable row
and records the queue as belonging elsewhere. `CPM-SECURITY-S03`'s Block If is
where that reading is fixed.

**No compliance verdict of any kind, and no column for one.** Whether a licence is
allowed is `CPM-FR-18`'s policy (`CPM-SECURITY-S05`), whose seed is PRD Open
Question 2; a collector may not compute a derived status (`CPM-AD-8`) and a policy
pass writes only its own derived table (`CPM-AD-21`). Nothing here ranks a licence,
calls one permissive, or divides them into allowed and forbidden.

**The licence is read from the source, and never from a sibling's evidence.**
`collectors/conda_package.py` reads the same channel document for a different
fact and that document also carries a licence, but `CPM-AD-7` forbids reading
another collector's evidence table -- so this collector asks the same *source*
independently and records its own row. That is a second call to one host rather
than a shared read, and `CPM-SECURITY-S03`'s Spec Change Log records it as the
shape `CPM-AD-7` intends.

**One row per monitored channel, and never fewer.** Two channels may state
different licences for one package, and each states its own: disagreement is a
fact to record rather than a verdict to resolve, so no row ever stands for two
channels and `license_names_the_channel_it_is_about` is the database saying so.
There is deliberately no platform in this table, which is the one place this
collector's shape differs from `collectors/conda_package.py`'s: a build string is
a property of a build and is per platform, while a licence is a property of the
package the channel serves.

**Several rows come out of one collection rather than out of several runs.** The
observation window and the ledger row are per `(collector, package)` (`CPM-AD-7`,
`CPM-AD-23`), so collecting each channel as its own run would have the second
channel suppressed by the first. `translate` returns a **sequence** and the base
inserts it, and it is what `CPM-FR-15`'s partial success looks like here: a
channel that fails becomes an `error` row for that channel and never discards
another channel's answer.

**One call per channel, and the first of them is the base's.** `source_for` names
the first declared channel's package document; `translate` reads that answer and
then makes one bounded call per remaining channel. Bounded means one locator and
no way of failing that raises -- **not** un-retried: the retry policy
`core/transport.py` mounts lives on the session, so every request this module
issues is retried exactly like the one the base issues. That is why the call count
is capped (`MAX_MONITORED_CHANNELS`) and why the retry budget is smaller than the
shared default; the arithmetic is reconciled against the inherited soft time limit
in `tests/unit/django_apps/test_license.py`.

**A first channel that answers "no such package" does not end the collection**,
and that is what `sentinel_evidence_rows` is for. The base's `not_found` branch
writes its rows without reaching `translate`, so a collector that owed one row per
channel could not answer for the channels the base's one call never touched --
which is a package absent from one channel and licensed on another recording
nothing at all about the second. `CPM-CURRENCY-S04` was patched for exactly that
defect in its own table and this module does not repeat it. An `error` is
deliberately *not* the same case: the run has been declared `failed` before the
hook is reached and the reason may be a refused allowance, so every channel gets
an `error` row and nothing is asked.

**Which channels are monitored is configuration, and it ships empty.** PRD Open
Question 4 is unresolved and explicitly blocks the currency epic; this collector
reads the *same* declaration `CPM-CURRENCY-S04` established
(`CPM_MONITORED_CHANNELS`) rather than inventing a second source of truth, and it
declares no adapter of its own. The setting's name and the rule that turns a
declaration into channels are **restated here rather than imported**, on the terms
`collectors/kev.py` restates its sibling's document bound: no collector imports
another (`CPM-AD-7`), and one that did would be a collector whose refusals change
when a different story edits its neighbour. `CPM_MONITORED_PLATFORMS` is
deliberately not read: a licence is not per platform, and a collector that read a
setting no branch of it needs would fail runs for a declaration that has nothing
to do with it.

**The settings access is a read, not an import.** Nothing under `src/django_apps/`
imports `config` (inherited `AD-4`); what happens here is a read of a value the
platform composed. `monitored_channels` and `declaration_fault` are pure functions
over the value, so every branch of them is reachable with no settings module in
sight.

**The pure functions are the whole of what this module decides.**
`monitored_channels`, `package_locator`, `stated_license` and `channel_license`
take data and return data, reachable with no database, no socket and no clock
(`CPM-AD-27`) -- and the normalization itself is data in `collectors/spdx.py`.

**The `error` and `not_found` rows the base writes go through
`sentinel_evidence_rows`, and this module invents neither.** The base decides which
sentinel and that there is always one (`CPM-NFR-3`); this module decides what a row
in `license_findings` looks like, and refuses a state it has no row shape for --
which here includes `unknown`, because that row is `translate`'s to write with the
reason the run actually established, and `not_applicable`, because every package a
channel could serve is licensed under something.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

from django.conf import settings
from django.db import models

from conda_package_supply_chain_monitor.collectors.agent import USER_AGENT
from conda_package_supply_chain_monitor.collectors.models import LicenseFinding
from conda_package_supply_chain_monitor.collectors.outcomes import LICENSE_ERROR
from conda_package_supply_chain_monitor.collectors.outcomes import LICENSE_NOT_FOUND
from conda_package_supply_chain_monitor.collectors.outcomes import LICENSE_UNKNOWN
from conda_package_supply_chain_monitor.collectors.outcomes import NORMALIZED
from conda_package_supply_chain_monitor.collectors.spdx import DetectionMethod
from conda_package_supply_chain_monitor.collectors.spdx import normalize
from conda_package_supply_chain_monitor.core.collection import Collector
from conda_package_supply_chain_monitor.core.collection import CollectorConfigurationError
from conda_package_supply_chain_monitor.core.collection import request_headers
from conda_package_supply_chain_monitor.core.ledger import current_trace_id
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.rate_limit import RateLimit
from conda_package_supply_chain_monitor.identity.models import Package

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Mapping
    from collections.abc import Sequence
    from datetime import datetime

    from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
    from conda_package_supply_chain_monitor.core.transport import Payload

__all__ = [
    "ABSENT_FROM_CHANNEL_DETAIL",
    "ANACONDA_API_HOST",
    "CHANNELS_SETTING",
    "COLLECTOR_NAME",
    "LICENSE_CACHE_TTL",
    "LICENSE_CADENCE",
    "LICENSE_DISPATCH_OFFSET",
    "LICENSE_FIELD",
    "LICENSE_FRESHNESS_TARGET",
    "LICENSE_HEADERS",
    "LICENSE_OBSERVATION_WINDOW",
    "LICENSE_RATE_LIMIT",
    "LICENSE_RETRIES",
    "LICENSE_TIMEOUT",
    "MAX_DOCUMENT_CHARACTERS",
    "MAX_MONITORED_CHANNELS",
    "MAX_SENTINEL_DETAIL_CHARACTERS",
    "NOTHING_MONITORED",
    "NO_LICENSE_FIELD_DETAIL",
    "NO_LICENSE_STATED_DETAIL",
    "SHORTENED_DETAIL",
    "TOLERATED_MISSED_RUNS",
    "UNNORMALIZABLE_LICENSE_DETAIL",
    "UNREAD_CHANNEL_DETAIL",
    "UNRECOGNISED_LICENSE_DETAIL",
    "ChannelLicense",
    "DetectionMethod",
    "LicenseChannelError",
    "LicenseCollector",
    "LicenseDocumentError",
    "channel_license",
    "declaration_fault",
    "monitored_channels",
    "package_locator",
    "stated_license",
]

#: What this collector is called, on its ledger rows, in its cache keys and in the
#: registry `config/startup/stage_two.py` sweeps. It is the `collect` half of its
#: task name too, which is what routes it (`core/queues.py`).
COLLECTOR_NAME: Final[str] = "license"

#: The setting this collector reads its monitored channels from.
#:
#: **The same setting `CPM-CURRENCY-S04` established, restated rather than
#: imported.** The monitored channels are already configuration and this story
#: declares no second source of truth; but no collector imports another
#: (`CPM-AD-7`), so the *name* is spelled here beside the read that uses it and
#: `tests/unit/django_apps/test_license.py` reconciles the two spellings. A
#: `from ... conda_package import CHANNELS_SETTING` would be one collector's
#: refusals changing when a different story edits its neighbour.
#:
#: `CPM_MONITORED_PLATFORMS` is deliberately **not** read. A licence is a property
#: of the package a channel serves rather than of a build, so no branch here needs
#: a subdir -- and a collector that read a setting it has no use for would fail
#: every run over a declaration that has nothing to do with its question.
CHANNELS_SETTING: Final[str] = "CPM_MONITORED_CHANNELS"

#: How often this collector is meant to run, and the number every other interval
#: below is derived from.
#:
#: `CPM-NFR-2` puts the security signals at **daily** with no range to choose
#: inside, and this surface belongs to that class: a licence changes rarely, but
#: the day it changes is the day a compliance reviewer wants to hear about it, and
#: a slower cadence here would be this collector deciding that a re-licensing is
#: less urgent than an advisory. The cadence itself is data in `django_celery_beat`
#: (`CPM-AD-20`); this is the number the arithmetic below assumes, and
#: `CPM-CURRENCY-S05` reconciles the two at start-up, in both directions, from
#: `collectors/apps.py`'s `ready()`.
LICENSE_CADENCE: Final[timedelta] = timedelta(days=1)

#: How long after its tick the licence dispatch is asked to run.
#:
#: **Three security sweeps otherwise fire from one instant**, and the reason to
#: offset this one is not the reason `CPM-SECURITY-S02` had. The KEV offset exists
#: because a KEV run *reads what the vulnerability run wrote*; nothing here reads
#: another collector at all. What this offset buys is that the two collectors
#: reading `api.anaconda.org` -- this one and `CPM-CURRENCY-S04`'s -- do not spend
#: their separate allowances against one host at the same instant, and that the
#: three security dispatches are distinguishable in a worker log rather than
#: arriving together.
#:
#: Two hours, which is deliberately not the KEV offset: two entries carrying one
#: phase would fire together again and the offset would buy nothing. The
#: reconciliation `CPM-CURRENCY-S05` owns compares a beat entry's `schedule` with
#: its collector's declared cadence, so the *interval* cannot carry a phase and a
#: crontab cannot be read as an interval; the entry's `options` can, and a
#: countdown on the dispatch is what this component has to offset with.
#: `config/settings/base.py` carries it and `tests/unit/test_settings.py`
#: reconciles the two.
LICENSE_DISPATCH_OFFSET: Final[timedelta] = timedelta(hours=2)

#: How many consecutive missed collections may pass before this product stops
#: calling an answer current. PRD Open Question 7 fixes this per *signal class*,
#: and this surface tolerates one on the terms its two security siblings do.
TOLERATED_MISSED_RUNS: Final[int] = 1

#: How long this collector's evidence may be read as current (`CPM-AD-28`):
#: `cadence x (1 + tolerated_missed_runs)`. Strictly greater than the cadence, so a
#: package does not read stale at exactly the moment its next run is due.
LICENSE_FRESHNESS_TARGET: Final[timedelta] = LICENSE_CADENCE * (1 + TOLERATED_MISSED_RUNS)

#: How long a successful observation suppresses the next one (`CPM-AD-7`). Half the
#: cadence, so a scheduled run is never suppressed by the previous one and a second
#: run of one package inside half a day still is.
LICENSE_OBSERVATION_WINDOW: Final[timedelta] = LICENSE_CADENCE / 2

#: How many times a failed request is retried, and therefore what the rate limiter
#: is charged against per collection.
#:
#: **One rather than the shared default of three**, for the reason
#: `collectors/conda_package.py` takes one: this collector makes several calls
#: where its security siblings make one, every call it issues goes through the
#: base's transport whose retry policy is mounted on the *session*, and at the
#: shared default the arithmetic does not fit the inherited soft time limit
#: (`CPM-AD-9`) at any usable timeout. One retry still recovers the transient blip
#: a retry exists for; the reconciliation is in
#: `tests/unit/django_apps/test_license.py` and is made against the settings
#: module's own limit rather than against a number repeated here.
LICENSE_RETRIES: Final[int] = 1

#: Seconds any single connect or read phase may take.
#:
#: Low, and the difference from a single-call sibling's is the channel count: one
#: collection is up to `MAX_MONITORED_CHANNELS` calls, each retried, so the figure
#: that has to fit inside the inherited 60-second soft limit is
#: `MAX_MONITORED_CHANNELS * worst_case_call_seconds(timeout, retries)`. Nothing
#: here is described as un-retried, because nothing here is.
LICENSE_TIMEOUT: Final[float] = 2.5

#: The most channels one collection may be asked to observe.
#:
#: **A time bound rather than an opinion about which channels are worth
#: monitoring.** Which channels this product watches is PRD Open Question 4 and is
#: not this module's to answer; how many of them one Celery task can ask about
#: inside its soft time limit *is*. Every channel costs a retried connect and read,
#: so an unbounded declaration is an unbounded worst case in a task the platform
#: will kill at sixty seconds -- and a killed task writes no rows at all, which is
#: worse than refusing the declaration that caused it.
#:
#: The same four `collectors/conda_package.py` affords, restated rather than
#: imported for the reason `CHANNELS_SETTING` is: it is the same *arithmetic*
#: reached independently rather than a shared constant, and this module's own
#: reconciliation is what holds it.
MAX_MONITORED_CHANNELS: Final[int] = 4

#: How hard this collector may push its source (`CPM-AD-20`).
#:
#: anaconda.org publishes **no numeric ceiling** for its package API, so this is a
#: declared courtesy bound rather than a number the source stated. Thirty a minute
#: is one request every two seconds, which at the `1 + retries` = 2 the base charges
#: is **fifteen packages a minute** -- and it is charged **separately** from
#: `CPM-CURRENCY-S04`'s allowance against the same host, because an allowance is
#: per collector (`CPM-AD-20`). `docs/deployment.md` says so to an operator, and
#: `LICENSE_DISPATCH_OFFSET` is what keeps the two sweeps from spending them at one
#: instant.
#:
#: **What it bounds is one call of the four, and a reader sizing it needs both
#: numbers.** The limiter is acquired once per `collect()`, before the first channel;
#: `_channel_instead` issues channels two onward afterwards, so a four-channel
#: declaration *sends* up to `MAX_MONITORED_CHANNELS * (1 + LICENSE_RETRIES)` = 8
#: requests and is charged for 2. That is the inherited defect `CPM-CURRENCY-S04`
#: recorded against the same seam, restated as a `deferred` entry on
#: `CPM-SECURITY-S03` against this module's own copy; the whole collection still fits
#: inside the declared thirty, and
#: `tests/unit/django_apps/test_license.py` pins both figures.
LICENSE_RATE_LIMIT: Final[RateLimit] = RateLimit(calls=30, per=timedelta(minutes=1))

#: What this collector's source expects on every request (`CPM-AD-20`,
#: `CPM-AD-27`): declared here, merged and sent by the base, never by this module.
#: `Accept` asks for the JSON representation `stated_license` reads and the
#: `User-Agent` is the one identity every collector shares
#: (`collectors/agent.py`). Nothing conditional is declared -- the validators are
#: the base's.
LICENSE_HEADERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    },
)

#: How long a remembered response may be replayed before it is re-read. A week, so
#: a scheduled daily collection revalidates rather than re-transfers a document
#: that lists every file a channel ever published for the package; an entry that
#: expired inside the cadence would make the cache inert.
#:
#: **It covers the first monitored channel and no other**, on the terms
#: `collectors/conda_package.py` states: the base composes a conditional request,
#: reads the cache and writes to it around the *one* call it makes, so the calls
#: this module issues for channels two onward carry no validator and remember
#: nothing.
#:
#: **A remembered licence is not the remembered security answer `CPM-NFR-3` is
#: written about.** The two security siblings declare `NO_CACHE` because a replayed
#: advisory answer is a claim about exploitation that has moved on; a licence is a
#: statement in the artifact metadata of a build that has already been published,
#: and the cache is *conditional* -- a channel whose document changed answers with
#: the new one. What is replayed is a body the channel has said is unchanged.
LICENSE_CACHE_TTL: Final[timedelta] = timedelta(days=7)

#: The host this collector reads. One host for every channel: a channel is a path
#: segment under it rather than a host of its own.
ANACONDA_API_HOST: Final[str] = "api.anaconda.org"

#: The one field of the channel document this collector reads, named rather than
#: spelled at the call sites so the reader and the cases that build documents
#: cannot drift.
#:
#: One field and not two. anaconda.org also states a `license_family`, which is a
#: coarse grouping the channel computed -- `GPL`, `BSD`, `Other` -- and recording it
#: would be recording somebody else's classification beside our own normalization,
#: in a table whose whole point is that a reader can see what normalization did.
LICENSE_FIELD: Final[str] = "license"

#: What a channel or a package name may be spelled with, once this collector has
#: lower-cased it.
#:
#: The same grammar `collectors/conda_package.py` applies to a channel segment and
#: for the same reason: what is being built is one path segment of a locator, so
#: what must be refused is anything that could make it two -- or make it a
#: navigation instruction. A leading `-` or `.` is refused, which is also what
#: refuses `.` and `..`; a `/` or a `\` anywhere is refused. Refused rather than
#: encoded: a declared channel is a decision an operator wrote down, and quietly
#: encoding one into something else would ask a question nobody asked.
_SEGMENT: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_][a-z0-9._-]*$")

#: What a stated licence may carry and still be *storable*, but not be something
#: this product will normalize.
#:
#: C0 and C1 control characters and the delete character. PostgreSQL stores a
#: newline or a tab in a `text` or `varchar` value without complaint, and a
#: multi-line `license` field is ordinary in conda metadata -- so a value carrying
#: one is neither a document error nor a licence: it is a review item, recorded
#: `unknown` with the raw string preserved verbatim and a `detail` saying why
#: nothing was normalized from it. What may *not* reach the database is a much
#: narrower set -- see `_UNSTORABLE_CHARACTERS` and `_require_storable`.
_CONTROL_CHARACTERS: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: The one character PostgreSQL refuses inside a `text` value.
#:
#: Refused by the *driver* rather than by the query, several frames past the `try`
#: `translate` is wrapped in and outside the guard that would have turned the
#: failure into an `error` row -- which is why it is refused where the value enters.
#: It is spelled out rather than left inside `_CONTROL_CHARACTERS` because it is the
#: only member of that class the database will not take.
_NUL: Final[str] = "\x00"

#: The UTF-16 surrogate range, for the one place a *substitution* is the answer.
#:
#: A lone surrogate is the second thing no value here may carry: psycopg raises
#: `UnicodeEncodeError: surrogates not allowed` from inside the driver, on the same
#: frames the NUL raises from. A stated licence carrying one is refused by
#: `_require_storable`, which asks whether the value encodes rather than matching
#: this pattern -- the encode is the check that cannot be outrun by a character
#: nobody enumerated. What this pattern is for is `_safe_detail`, where a reason is
#: cleaned rather than refused and something has to be substituted *in*.
#:
#: `json.loads('{"license": "\\ud800"}')` succeeds, so this is a value a channel can
#: really state: one character wide, not a control character, and not a recognised
#: spelling.
_SURROGATES: Final[re.Pattern[str]] = re.compile(r"[\ud800-\udfff]")

#: The longest channel document this collector will hand to `json.loads`, in
#: characters.
#:
#: The package document lists every file of every version the channel holds, so for
#: a large, long-lived package it runs to several mebibytes -- **and it is bounded
#: by the channel count as well as by the document**, because up to
#: `MAX_MONITORED_CHANNELS` of these are parsed inside one soft time limit, so the
#: figure that matters is the product rather than the single bound.
#:
#: **What the bound protects is the parse and nothing earlier**: by the time a body
#: arrives here the transport has already transferred it, so what this refuses is
#: handing `json.loads` a document no honest source serves, which is where a
#: worker's soft time limit would be spent (`CPM-AD-9`).
MAX_DOCUMENT_CHARACTERS: Final[int] = 8 * 1024 * 1024

#: The longest reason a *sentinel* row will carry, in characters.
#:
#: A sentinel row is written on a path that is already recording a failure, and
#: `CPM-NFR-3` requires it to be written -- so a reason too long, or one carrying a
#: control character, is **shortened and cleaned rather than refused**, on the terms
#: `collectors/kev.py` states. The reason reaching that hook is the base's own
#: sentence with a third party's exception message inside it, and raising over its
#: shape would turn "the channel failed" into "no row at all".
MAX_SENTINEL_DETAIL_CHARACTERS: Final[int] = 1024

#: What a row says in its own words, in each of the ways it is reachable. Named so
#: the row a run writes and the case that reads it back cannot drift.
NO_LICENSE_STATED_DETAIL: Final[str] = (
    "this channel serves the package and states no license at all, so there is nothing to normalize -- which is "
    "not the same as the package being unrestricted"
)
NO_LICENSE_FIELD_DETAIL: Final[str] = (
    f"this channel's document carries no {LICENSE_FIELD!r} key at all, so the field this collector reads was not "
    f"found -- which is a document whose shape may have changed, and is deliberately not recorded as the channel "
    f"stating no license"
)
UNRECOGNISED_LICENSE_DETAIL: Final[str] = (
    "this channel states a license this product does not recognise, so it is recorded exactly as stated with no "
    "normalized expression beside it and needs review. Nothing is guessed and no part of it is normalized as if "
    "it were the whole"
)
UNNORMALIZABLE_LICENSE_DETAIL: Final[str] = (
    "this channel states a license carrying a line break, a tab or another control character, so it is recorded "
    "exactly as stated and nothing is normalized from it. A license written across two lines is a statement this "
    "product will not read as one identifier, and a reviewer needs to see it whole"
)
ABSENT_FROM_CHANNEL_DETAIL: Final[str] = (
    "this channel reports that it does not serve the package at all, which is an absence from this channel rather "
    "than a package with no license"
)
UNREAD_CHANNEL_DETAIL: Final[str] = (
    "this channel could not be read, so this row records that nothing was established about the license it states "
    "and not that it states none"
)
SHORTENED_DETAIL: Final[str] = "[shortened by this collector]"


class LicenseChannelError(ValueError):
    """The monitored channels cannot be turned into a question to ask.

    A `ValueError` subclass, matching `collectors/conda_package.py`'s
    `CondaChannelError` and every other "this input cannot describe what it claims
    to" in this product.

    **It escapes `collect()` rather than becoming an evidence row, and that is a
    decision rather than an omission.** `source_for` is called before the window,
    the allowance and the transport, so the run ledger row exists and is finalized
    `failed` carrying this message, and no evidence row is written at all. There is
    nothing honest to write: a row must name the channel it is about
    (`license_names_the_channel_it_is_about`), and every way of reaching this class
    is a way of not knowing which channel the run was going to be about.

    What it refuses is a declaration this product cannot act on: an empty one --
    which is what ships, and which PRD Open Question 4 leaves an operator to answer
    -- one carrying a blank, mistyped, duplicated or separator-carrying entry, one
    naming more channels than a collection can ask about inside its soft time
    limit, and a package whose canonical name is not a segment a channel could
    serve it under.
    """


class LicenseDocumentError(ValueError):
    """A channel's package document could not be read as what it claims to be.

    Raised from `translate` **for the first channel only** -- the one the base
    fetched -- which the base answers by writing an `error` row and re-raising
    unchanged, so `CPM-NFR-3`'s guarantee holds on this path too: never a clean
    result, and never no row.

    Refused rather than partially read, and the stakes here are the licence's: a
    document this collector cannot understand is a source whose shape has changed,
    and reading around it would record "this channel states no license" for a
    channel that stated one in a shape the reader skipped -- an `unknown` row that
    looks exactly like an honest one.

    **What it refuses is narrow, and the near miss is instructive.** A document
    missing the `license` key entirely is *not* refused: it is an `unknown` row
    carrying `NO_LICENSE_FIELD_DETAIL`, which names the absence of the field rather
    than claiming the channel stated no licence. That keeps a renamed or nested
    field visible in a sweep of details without failing every package on every
    channel over a shape change this collector cannot fix. Neither is a licence
    carrying a line break or a tab: PostgreSQL stores those, so they are review
    items rather than unreadable documents.

    A *later* channel's unreadable document never escapes. That call is bounded on
    the terms `collectors/conda_package.py` bounds its own, so an unreadable answer
    from it becomes an `error` row for that channel beside the rows the channels
    that did answer earned (`CPM-FR-15`).
    """


#: What a collector instance remembers before any run has reached it, and what it
#: is reset to at the start of every one. A value rather than `None`, so the hooks
#: that read it need no optional-narrowing dance for a state none of them can reach
#: through `collect()` -- and empty rather than plausible, so a hook reached without
#: a run says "no channel" instead of naming one nobody declared.
NOTHING_MONITORED: Final[tuple[str, ...]] = ()


@dataclass(frozen=True, slots=True)
class ChannelLicense:
    """What one channel says about one package's licence, as the fields the row holds.

    One per monitored channel, which is one evidence row. Never a failure: a
    channel that could not be read produces a fact carrying `error` and a reason,
    because a row per channel is owed whatever happened.

    **The invariant is enforced rather than described** -- see `__post_init__` --
    on the terms `collectors/kev.py`'s value objects state: the table's own
    constraint fires at insert, inside `bulk_create`, with a message about a column
    and nothing about the branch that produced it.

    Attributes:
        channel: The channel this fact is about. Never blank.
        state: What the look concluded -- `normalized`, `unknown`, `not_found` or
            `error`. Never `ok`, which is not in this vocabulary at all, and never
            `not_applicable`, which this table refuses outright.
        raw_license: The licence exactly as the channel stated it, or blank where
            it stated none or where no answer was read. Recorded on every fact that
            has one, whatever the state.
        normalized_license: The SPDX expression, or blank. Set exactly when the
            state is `normalized`.
        detection_method: How the expression was established, or blank. Set exactly
            when the expression is.
        source: The locator this fact was read from, or blank where none could be
            built.
        detail: Why a fact is missing, where one is. Empty for an ordinary
            determinate observation.

    """

    channel: str
    state: str
    raw_license: str
    normalized_license: str
    detection_method: str
    source: str
    detail: str

    def __post_init__(self) -> None:
        """Refuse a fact whose columns do not match the state it claims.

        Raises:
            CollectorConfigurationError: When the fact names no channel; when a
                determinate fact carries no expression or no method; or when a fact
                that is not determinate carries either. The same rule
                `license_findings` enforces, applied where the value is built.
                `raw_license` is deliberately unconstrained: it is permitted on
                every row, which is what makes an `unknown` one reviewable.

        """
        if not self.channel:
            message = (
                f"ChannelLicense(state={self.state!r}, raw_license={self.raw_license!r}) names no channel. Every "
                f"row in license_findings says which channel stated the licence it records (CPM-FR-13); a row "
                f"that could not would have merged the channels that disagree."
            )
            raise CollectorConfigurationError(message)
        determinate = self.state == NORMALIZED
        stated = bool(self.normalized_license) and bool(self.detection_method)
        if determinate != stated or bool(self.normalized_license) != bool(self.detection_method):
            message = (
                f"ChannelLicense(state={self.state!r}, normalized_license={self.normalized_license!r}, "
                f"detection_method={self.detection_method!r}) sets the normalized facts on a row that is "
                f"{'not ' if not determinate else ''}determinate. They are present exactly on a {NORMALIZED!r} "
                f"row: a normalized expression under any other state claims a normalization the run never made, "
                f"and a determinate row without one is a licence nobody can check."
            )
            raise CollectorConfigurationError(message)


def declaration_fault(values: object, *, setting: str = CHANNELS_SETTING, what: str = "channel") -> str:
    """Return why a declaration's *shape* is unusable, or nothing when it is usable.

    Pure, and separate from `monitored_channels` for one reason: an **empty**
    declaration is the shipped state and must let a component boot, while a
    declaration of the wrong *shape* is a misconfiguration that should stop it.
    `LicenseCollector.selectable_packages` asks this and `monitored_channels` asks
    it at run time, so one rule decides both and a selection cannot come to accept
    a shape the run refuses.

    **A bare string is refused before a sequence is accepted**, and that is the case
    worth the function: a `str` *is* a sequence of one-character strings, so
    `CPM_MONITORED_CHANNELS = "conda-forge"` would otherwise be read as eleven
    channels named `c`, `o`, `n` and so on -- eleven locators, eleven rows a run,
    and nothing anywhere saying the declaration had been misread.

    Args:
        values: What the settings module holds.
        setting: The setting's name, for the message.
        what: What its entries are, for the message.

    Returns:
        The reason it cannot be read, or the empty string. An empty list or tuple is
        *usable*: it means no channel is monitored yet, which is a failed collection
        naming the setting rather than a component that will not start.

    """
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        return (
            f"{setting} holds {type(values).__name__} rather than a list or tuple of {what} names, so this "
            f"component cannot tell which {what}s it is meant to read a license from. PRD Open Question 4 leaves "
            f"the choice to an operator; it does not leave the shape open."
        )
    return ""


def monitored_channels(channels: object) -> tuple[str, ...]:
    """Return the channels a declaration names, or refuse it.

    Pure: no database, no clock, no network, and no settings module -- the value is
    handed in, so every branch of the rule is reachable without one
    (`CPM-AD-27`).

    Entries are normalised the way `package_locator` will spell them -- stripped and
    lower-cased -- **before** duplicates are looked for, so `Conda-Forge` beside
    `conda-forge` is refused as the one declaration it is rather than accepted as
    two. Order is the operator's: the first channel is the one the base calls, and a
    run whose call order depended on a set's iteration would make "which channel
    does a failed first call cost" unanswerable.

    Args:
        channels: What `CPM_MONITORED_CHANNELS` holds. Typed as `object` because the
            whole point of this function is that a settings module may hold anything
            at all.

    Returns:
        The channels, stripped, lower-cased and in declared order. Never empty.

    Raises:
        LicenseChannelError: When the declaration is not a list or tuple of strings;
            is empty; carries a blank, mistyped, or separator-carrying entry;
            carries the same entry twice once normalised; carries an entry wider
            than the column that has to record it; or names more channels than
            `MAX_MONITORED_CHANNELS`.
            Refused rather than defaulted: an unusable declaration silently narrowed
            to the entries that happened to parse would record evidence about a set
            of channels nobody chose.

    """
    unusable = declaration_fault(channels)
    if unusable:
        raise LicenseChannelError(unusable)
    # Narrowed by the shape check above, which is the one place this module decides
    # what a declaration may be.
    entries: list[object] = list(channels)  # type: ignore[call-overload]
    if not entries:
        message = (
            f"{CHANNELS_SETTING} is empty, so no channel is monitored and there is no source for this collector "
            f"to read a license from. It ships empty on purpose: which conda channels this product watches is PRD "
            f"Open Question 4 and is an operator's decision, and a component that picked one would record facts "
            f"about a surface nobody chose -- permanently, in a log nothing may correct. Declare "
            f"{CHANNELS_SETTING} in config/settings/base.py and this collector starts observing "
            f"(docs/deployment.md)."
        )
        raise LicenseChannelError(message)
    if len(entries) > MAX_MONITORED_CHANNELS:
        message = (
            f"{CHANNELS_SETTING} declares {len(entries)} channels and one collection may ask about at most "
            f"{MAX_MONITORED_CHANNELS}. Every channel costs a retried call inside one task -- the transport's "
            f"retry policy is mounted on the session and applies to every request it issues -- and a declaration "
            f"whose worst case exceeds the inherited soft time limit (CPM-AD-9) is a task the platform kills "
            f"before it writes anything. Refused rather than truncated: reading some of the channels an operator "
            f"declared, without saying which, is worse than reading none."
        )
        raise LicenseChannelError(message)
    width = _column_width("channel")
    seen: list[str] = []
    for position, value in enumerate(entries):
        entry = _segment(value, position=position, what="channel")
        if len(entry) > width:
            message = (
                f"{CHANNELS_SETTING} names the channel {entry!r} at position {position}, which is {len(entry)} "
                f"characters, and the channel column that records it takes {width}. Refused rather than "
                f"truncated: a row that cannot say which channel it observed is a row an append-only history "
                f"cannot tell from its neighbours."
            )
            raise LicenseChannelError(message)
        if entry in seen:
            message = (
                f"{CHANNELS_SETTING} names the channel {entry!r} twice -- at position {position} and earlier. "
                f"Refused rather than de-duplicated: two identical rows for one observation would be two facts "
                f"where there is one, and an operator who wrote a channel twice meant something this collector "
                f"cannot guess at."
            )
            raise LicenseChannelError(message)
        seen.append(entry)
    return tuple(seen)


def _segment(value: object, *, position: int, what: str) -> str:
    """Return one declared entry as a locator segment, or refuse it.

    Args:
        value: The entry as the settings module holds it, or the package's own name.
        position: Where in the declaration it sits, for the messages.
        what: What the entry is, for the messages.

    Returns:
        The entry, stripped and lower-cased.

    Raises:
        LicenseChannelError: When it is not a string, is blank, or is not a single
            locator segment once lower-cased -- which is what refuses a path
            separator, and what refuses `.` and `..`, because neither may begin a
            segment and percent-encoding leaves both untouched.

    """
    if not isinstance(value, str) or not value.strip():
        message = (
            f"{CHANNELS_SETTING} names {value!r} at position {position}, which is not a {what} this collector "
            f"could ask about. A declaration is refused whole rather than read for the entries that happen to "
            f"parse."
        )
        raise LicenseChannelError(message)
    entry = value.strip().lower()
    if not _SEGMENT.match(entry):
        message = (
            f"{CHANNELS_SETTING} names the {what} {value!r} at position {position}, which is {entry!r} once "
            f"lower-cased and is not a single locator segment. Refused rather than encoded: a locator built from "
            f"it would ask about nothing, or would be a path the source is entitled to resolve somewhere else."
        )
        raise LicenseChannelError(message)
    return entry


def package_locator(channel: str, name: str) -> str:
    """Return the locator naming one package's document on one channel.

    The one document a channel is asked for, and one call per channel. It is the
    same document `collectors/conda_package.py` reads for a different fact and is
    read here **independently** -- a second call to one host rather than a shared
    read, which is what `CPM-AD-7` intends and what `CPM-SECURITY-S03`'s Spec
    Change Log records.

    Args:
        channel: The channel, already normalised by `monitored_channels`.
        name: The package's canonical name.

    Returns:
        `https://api.anaconda.org/package/<channel>/<name>`.

    Raises:
        LicenseChannelError: When either segment is not a string, is blank, or is
            not a single locator segment once lower-cased. Refused rather than
            encoded, on the terms `_segment` states.

    """
    return (
        f"https://{ANACONDA_API_HOST}/package/"
        f"{_segment(channel, position=0, what='channel')}/"
        f"{_segment(name, position=0, what='package name')}"
    )


def stated_license(body: object, *, source: str) -> str:
    """Read one channel's package document into the licence it states, exactly as stated.

    Pure: no database, no clock, no network. The first of this module's two
    decisions about a document -- what the channel *said* -- kept apart from the
    second, what this product normalizes it to, because they fail differently and a
    reviewer reads them as two separate claims.

    **Nothing here rewrites the value.** It is stripped of surrounding whitespace,
    which is not a rewrite of the licence but of the field around it, and otherwise
    recorded character for character.

    Args:
        body: The document the channel served. Typed as `object` because a
            `Payload` is a value a transport built: a body that is not a string is
            refused by name here rather than raising a `TypeError` from `len()`
            that names no source.
        source: The locator it was served from, for the messages and for the row.

    Returns:
        The licence as stated, stripped. The empty string when the document states
        none, states `null`, or states only whitespace -- all three mean "the source
        stated no licence", which is a different fact from one it stated and this
        product could not read.

    Raises:
        LicenseDocumentError: When the body is longer than
            `MAX_DOCUMENT_CHARACTERS`, is not JSON, is not an object, states a
            `license` that is not a string, states one wider than the column that
            has to record it, or states one no database will hold -- a NUL byte or
            a lone surrogate. A licence carrying an ordinary control character is
            **not** refused here: PostgreSQL stores it, so it is a review item
            rather than an unreadable document, and `channel_license` routes it.

    """
    return _stated_in(_document_in(body, source=source), source=source)


def _stated_in(document: Mapping[str, object], *, source: str) -> str:
    """Read one already-decoded channel document into the licence it states.

    Split from `stated_license` so `channel_license` can decode once and still ask
    the *document* whether it carried the field at all -- which is a different fact
    from the field being present and empty, and the two record different reasons.

    Args:
        document: The decoded document.
        source: The locator it was served from, for the messages.

    Returns:
        The licence as stated, stripped, or the empty string.

    Raises:
        LicenseDocumentError: On every refusal `stated_license` documents about the
            field itself.

    """
    value = document.get(LICENSE_FIELD)
    if value is None:
        return ""
    if not isinstance(value, str):
        message = (
            f"{source} served a document whose {LICENSE_FIELD!r} is {type(value).__name__} rather than a string. "
            f"A source whose shape has changed is refused rather than read past -- a license this collector "
            f"cannot even attempt to read is different from one it attempted and could not recognise."
        )
        raise LicenseDocumentError(message)
    stated = value.strip()
    _require_storable(stated, field="raw_license", source=source, what="license")
    return stated


def channel_license(body: object, *, channel: str, source: str) -> ChannelLicense:
    """Read one channel's document into the one fact this collector records about it.

    Pure: no database, no clock, no network. `stated_license` and
    `collectors/spdx.py`'s `normalize` are the two decisions; this composes them
    into the row's columns so no later branch can come to disagree about which
    column a fact lands in.

    Args:
        body: The document the channel served, as it was recorded.
        channel: The channel it came from, recorded on the fact.
        source: The locator it was served from, recorded on the fact.

    **A missing key and an empty value are two different facts.** `document.get`
    answers `None` for both, and reading them as one would record the affirmative
    claim "this channel states no license" for a document whose `license` field had
    been *renamed or nested* -- silently, for every package on every channel, with
    nothing failing. `LicenseDocumentError`'s own docstring names that hazard as the
    reason its refusals exist, so the key's absence earns its own `detail` and a
    sweep of details makes a field rename visible. Both stay `unknown`: an absent
    field is still not a reason to fail a run.

    Returns:
        A determinate fact carrying the raw string, the SPDX expression and the
        method; or an `unknown` fact carrying the raw string and saying why there
        is no expression beside it. The raw string is on the fact either way, which
        is the whole of AC 1.

    Raises:
        LicenseDocumentError: On every refusal `stated_license` makes.

    """
    document = _document_in(body, source=source)
    raw = _stated_in(document, source=source)
    if not raw:
        stated_none = LICENSE_FIELD in document
        return _unnormalized(
            channel=channel,
            source=source,
            raw=raw,
            detail=NO_LICENSE_STATED_DETAIL if stated_none else NO_LICENSE_FIELD_DETAIL,
        )
    if _CONTROL_CHARACTERS.search(raw):
        # Storable and not normalizable, which the matrix assigns to `unknown`
        # rather than to the document-error path: PostgreSQL takes a newline or a
        # tab, a multi-line `license` field is ordinary in conda metadata, and
        # refusing one would fail the whole run -- writing `error` rows for every
        # *other* channel without asking them, and losing the very string a
        # reviewer needs to see.
        return _unnormalized(channel=channel, source=source, raw=raw, detail=UNNORMALIZABLE_LICENSE_DETAIL)
    reading = normalize(raw)
    if not reading.expression:
        return _unnormalized(
            channel=channel,
            source=source,
            raw=raw,
            detail=_safe_detail(f"{UNRECOGNISED_LICENSE_DETAIL}: {list(reading.unrecognised)}"),
        )
    return ChannelLicense(
        channel=channel,
        state=NORMALIZED,
        raw_license=raw,
        normalized_license=reading.expression,
        detection_method=reading.method,
        source=source,
        detail="",
    )


def _unnormalized(*, channel: str, source: str, raw: str, detail: str) -> ChannelLicense:
    """Return the fact a licence this product will not normalize earns.

    `unknown` and never a permissive value (`CPM-SECURITY-S03` AC 2, `CPM-SM-2`),
    and never `not_found`: `not_found` is an informative negative -- we looked and
    the thing is not there -- which on a licence table reads as *unrestricted*, and
    neither this collector nor the channel is in a position to say that.

    Args:
        channel: The channel this fact is about.
        source: The locator it was read from.
        raw: The licence exactly as the channel stated it, preserved on the row
            whether or not it was recognised. Blank only where the channel stated
            none.
        detail: Why there is no expression beside it.

    Returns:
        An `unknown` fact carrying the raw string and no normalized fact at all.

    """
    return ChannelLicense(
        channel=channel,
        state=LICENSE_UNKNOWN,
        raw_license=raw,
        normalized_license="",
        detection_method="",
        source=source,
        detail=detail,
    )


def _unread(*, channel: str, source: str, state: str, detail: str) -> ChannelLicense:
    """Return the fact a channel this run could not read, or that does not serve the package, earns.

    The shape a bounded call's answer takes when it is not a document. A channel
    that raised, answered `304` to a request carrying no validator, served a
    document whose shape has changed, or said "no such package" still owes a row --
    and each of them says what happened rather than claiming the channel states no
    licence.

    Args:
        channel: The channel this fact is about.
        source: The locator that was asked, or blank when none could be built.
        state: What the row records -- `error` for a look that failed, `not_found`
            for a channel that answered "no such package".
        detail: What happened, in words worth storing.

    Returns:
        A fact carrying no licence fact at all -- not even a raw one, because
        nothing was stated.

    """
    return ChannelLicense(
        channel=channel,
        state=state,
        raw_license="",
        normalized_license="",
        detection_method="",
        source=source,
        detail=detail,
    )


def _document_in(body: object, *, source: str) -> dict[str, object]:
    """Decode a document and refuse anything that is not an object.

    Args:
        body: The document the source served, as it was recorded.
        source: The locator it was served from, for the messages.

    Returns:
        The decoded object.

    Raises:
        LicenseDocumentError: When the body is too long to decode, is not JSON, or
            is not an object.

    """
    if not isinstance(body, str):
        message = (
            f"{source} recorded a payload whose body is {type(body).__name__} rather than a string. A Payload is "
            f"a value a transport built, so its body is checked here rather than left to raise a TypeError from a "
            f"length check that names no source."
        )
        raise LicenseDocumentError(message)
    if len(body) > MAX_DOCUMENT_CHARACTERS:
        message = (
            f"{source} served {len(body)} characters, and this collector decodes at most "
            f"{MAX_DOCUMENT_CHARACTERS}. A package document is kilobytes to a few mebibytes, so a document this "
            f"size is a source doing something else -- and parsing it would spend a worker's soft time limit "
            f"finding out (CPM-AD-9)."
        )
        raise LicenseDocumentError(message)
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError) as unreadable:
        # Three rather than one, on the terms `collectors/kev.py` states:
        # `json.loads` recurses per level of nesting, so a deeply nested body
        # raises `RecursionError`, and a body that reached here as bytes raises
        # `UnicodeDecodeError` for an undecodable one. The `TypeError` a body that
        # is not a string would raise is unreachable, because such a body is
        # refused above by name.
        message = (
            f"{source} did not serve a readable document: {type(unreadable).__name__}: {unreadable}. The "
            f"observation is refused rather than recorded as a channel that states no license, which is the "
            f"honest-looking result this table must not manufacture (CPM-FR-13)."
        )
        raise LicenseDocumentError(message) from unreadable
    if not isinstance(document, dict):
        message = (
            f"{source} served {type(document).__name__} rather than an object. A source whose shape has changed "
            f"is refused rather than read for whatever still parses."
        )
        raise LicenseDocumentError(message)
    return document


def _require_storable(value: str, *, field: str, source: str, what: str) -> None:
    """Refuse a value wider than the column that has to hold it, or one no database will take at all.

    Refused where the value enters rather than where it lands, on the terms
    `collectors/vulnerability.py` states: `max_length` is enforced by PostgreSQL and
    ignored by SQLite, so an over-long value is a stored row on a developer's
    machine and a failed run in the gate (`R-5`). And a truncated licence is a
    *different licence* -- `CPM-SECURITY-S03`'s matrix says so in as many words --
    so there is no reading on which shortening one is better than refusing it.

    **The unstorable set is narrow on purpose, and it is asked as a question the
    driver asks.** A NUL byte and a lone UTF-16 surrogate are refused by psycopg
    from *inside* the driver, several frames past the `try` `translate` is wrapped
    in -- so an unrefused one escapes as neither a document refusal nor a recorded
    observation, and repeats daily. Every other control character PostgreSQL stores
    perfectly well, and refusing those here would fail a whole run over a
    multi-line `license` field, which is ordinary in conda metadata:
    `channel_license` routes those to `unknown` with the raw string preserved.

    The surrogate half is asked by *encoding* rather than by matching a pattern.
    The regex is the enumeration a reviewer reads; `str.encode` is what the driver
    will actually do, so it cannot be outrun by a character nobody thought to
    enumerate.

    Args:
        value: What the document said.
        field: The column it is measured against.
        source: The locator, for the message.
        what: What the value is, for the message.

    Raises:
        LicenseDocumentError: When it is wider than the column, carries a NUL byte,
            or is not encodable as UTF-8.

    """
    if _NUL in value:
        message = (
            f"{source} states a {what} carrying a NUL byte. The observation is refused rather than cleaned: a "
            f"value this collector rewrote is not the value the source published, and one it stored unchanged is "
            f"a row PostgreSQL refuses from inside the driver, outside the guard that would have recorded the "
            f"failure."
        )
        raise LicenseDocumentError(message)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as unstorable:
        message = (
            f"{source} states a {what} that is not encodable as UTF-8: {unstorable}. A lone surrogate decodes out "
            f"of JSON perfectly well and is refused by the database driver, outside the guard that would have "
            f"recorded the failure -- so it is refused here, where the value enters."
        )
        raise LicenseDocumentError(message) from unstorable
    width = _column_width(field)
    if len(value) > width:
        message = (
            f"{source} states a {what} of {len(value)} characters, and the column that holds it takes {width}. "
            f"The observation is refused rather than truncated: a truncated license is a different license, and "
            f"one written permanently into a row nothing may correct."
        )
        raise LicenseDocumentError(message)


def _column_width(field: str) -> int:
    """Return how wide one of this table's text columns is.

    Read off the model rather than restated, so the bound a value is refused against
    is the bound the table actually enforces.

    **A column that declares no width is a refusal rather than a skip**, on the
    terms `collectors/kev.py` states: a guard that answered `None` for such a column
    would have every caller write `if width is not None and ...`, so a field renamed
    or turned into a `TextField` would silently turn its refusal off with nothing
    anywhere failing.

    Args:
        field: The column's name.

    Returns:
        Its `max_length`.

    Raises:
        CollectorConfigurationError: When the column is not a `CharField`, or
            declares no `max_length`. A defect in this module or in the models
            beside it, and never something a source can cause.

    """
    column = LicenseFinding._meta.get_field(field)  # noqa: SLF001 - Django's own public-by-convention API
    width = column.max_length if isinstance(column, models.CharField) else None
    if width is None:
        message = (
            f"LicenseFinding.{field} declares no max_length, so there is no bound to refuse an over-wide value "
            f"against. Refused rather than skipped: a width guard that quietly stops guarding is one that stores "
            f"whatever a source sends on SQLite and fails the run on PostgreSQL (R-5)."
        )
        raise CollectorConfigurationError(message)
    return width


def _safe_detail(text: str) -> str:
    """Return a reason that can be stored, however the caller built it.

    The opposite posture from `_require_storable`, and the difference is the path:
    this one is called where a sentinel row is being shaped, which is a path already
    recording a failure and one `CPM-NFR-3` requires to write a row. The reason
    arriving there is the base's own sentence with a third party's exception message
    inside it, so raising over its shape would turn "the channel failed" into "no
    row at all".

    **Every reason a third party's words reach goes through here**, not only the
    base's sentinels: `_channel_instead` interpolates a transport exception's message
    into four of its own reasons, and that write is a `bulk_create` with no
    `DatabaseError` handler over it -- so one bad byte in one channel's failure
    message would discard every channel's row, on the path that exists precisely so
    that it cannot.

    Args:
        text: The reason the base, or this module, composed.

    Returns:
        The reason with control characters and lone surrogates replaced by spaces
        and, where it was longer than `MAX_SENTINEL_DETAIL_CHARACTERS`, shortened
        with a marker saying so.

    """
    cleaned = _SURROGATES.sub(" ", _CONTROL_CHARACTERS.sub(" ", text))
    if len(cleaned) > MAX_SENTINEL_DETAIL_CHARACTERS:
        return f"{cleaned[:MAX_SENTINEL_DETAIL_CHARACTERS]} {SHORTENED_DETAIL}"
    return cleaned


class LicenseCollector(Collector):
    """The collector that records each monitored channel's stated licence. Writes `license_findings`.

    Four hooks and nine declarations, on the terms `CondaPackageCollector` counts
    them. See the module docstring for why one collection
    produces several rows, why the channels are the declaration
    `CPM-CURRENCY-S04` already established, why the first channel's call is the
    base's while the rest are bounded calls made from `translate`, and why an
    unrecognised licence is `unknown` rather than anything reassuring.
    """

    #: The nine declarations the base checks at construction, every one written out
    #: on the terms `SourceReleaseCollector` gives.
    name: ClassVar[str] = COLLECTOR_NAME

    evidence_model: ClassVar[type[AppendOnlyModel] | None] = LicenseFinding

    observation_window: ClassVar[timedelta | None] = LICENSE_OBSERVATION_WINDOW

    timeout: ClassVar[float | None] = LICENSE_TIMEOUT

    retries: ClassVar[int] = LICENSE_RETRIES

    rate_limit: ClassVar[RateLimit] = LICENSE_RATE_LIMIT

    headers: ClassVar[Mapping[str, str]] = LICENSE_HEADERS

    freshness_target: ClassVar[timedelta | None] = LICENSE_FRESHNESS_TARGET

    response_cache_ttl: ClassVar[timedelta | None] = LICENSE_CACHE_TTL

    #: How often the full-inventory sweep dispatches this collector
    #: (`CPM-CURRENCY-S05`). Bound to the module constant the target and the window
    #: are already derived from, so no number moves; `collectors/apps.py` reconciles
    #: it against this collector's `CELERY_BEAT_SCHEDULE` entry at boot, in both
    #: directions. The entry's *phase* is `LICENSE_DISPATCH_OFFSET` and is not part
    #: of that reconciliation -- see that constant.
    cadence: ClassVar[timedelta | None] = LICENSE_CADENCE

    #: What this run is about, remembered on the instance between the hooks, on the
    #: terms `CondaPackageCollector` states: the base asks one hook after another
    #: about one package in one run and they must agree, and reading the declaration
    #: twice would be a second chance for the two to disagree across a settings
    #: change. Forgotten at the start of every run by `inapplicability`, so an
    #: instance that collects twice reads fresh each time.
    _channels: tuple[str, ...] = NOTHING_MONITORED
    _package_name: str = ""
    _locator: str = ""

    @classmethod
    def selectable_packages(cls) -> Iterable[int]:
        """Return the packages this collector can be asked about: every one, or none at all.

        The complement of `source_for`'s refusals, and that complement has two
        shapes rather than one.

        **When channels are declared it is the whole inventory.** "What does this
        channel say this package is licensed under" applies to every package --
        "it is not there" is an observation rather than a reason not to look, which
        is why `inapplicability` never answers a reason and `sentinel_evidence`
        refuses `not_applicable` outright. Nothing this collector reads from
        `identity` can make a package unaskable: it needs a canonical name, and
        every package row has one (`canonical_name_is_present`).

        **When they are not, it is nothing, and that is the whole point.** The
        setting ships empty (PRD Open Question 4), and an empty or unusable
        declaration refuses every package equally -- so a selection that offered the
        inventory anyway would have a scheduled sweep write one `failed` collection
        per package per day, for ever, out of the box. That is the matrix's
        "nothing declared" row: the selection is empty, so a scheduled run records
        an empty selection rather than failing every package. It is the lesson
        `CPM-CURRENCY-S04` was patched for, reached from the shipped settings rather
        than from any mistake an operator made.

        The check is `declaration_fault` -- this collector's own rule -- and it is
        the *shape* rule only. `monitored_channels` refuses more than
        `MAX_MONITORED_CHANNELS` entries, duplicates, blanks, non-segments and
        over-wide entries on top of it, so a declaration of five well-formed channels
        is offered as the whole inventory here and then fails every collection. That
        is inherited from `collectors/conda_package.py` and is deliberately not
        diverged from: one collector narrowing its selection where its sibling does
        not would be two answers to "what does declared mean" rather than one. It is
        recorded as a `deferred` entry on `CPM-SECURITY-S03`.

        Returns:
            Every package's primary key, as a lazy queryset ordered by key --
            streamed by `collectors/sweep.py` rather than materialised -- or an empty
            queryset when no usable channel is declared.

        """
        declared = getattr(settings, CHANNELS_SETTING, ())
        if declaration_fault(declared) or not declared:
            return Package.objects.none().values_list("pk", flat=True)
        return Package.objects.order_by("pk").values_list("pk", flat=True)

    def inapplicability(self, *, package_id: int) -> str:
        """Say why this question does not apply to a package, which here is never.

        **The question applies to every package**, and that is a statement about the
        surface rather than an omission: every package a monitored channel could
        serve is licensed under something, and "this channel states none" is the
        observation `CPM-FR-13` asks for rather than a reason not to look. There is
        no identity mapping to consult and no `not_applicable` row shape --
        `sentinel_evidence` refuses that state outright and `license_findings`
        refuses it at insert.

        What the override is for is the other half of the hook's position: it is the
        first thing the base calls on every run, which makes it the one place a
        run's remembered declaration can be forgotten before the next one reads it.

        Args:
            package_id: The package being collected, by the integer primary key
                `CPM-AD-3` fixes. Read by no branch here.

        Returns:
            The empty string, always.

        """
        # A new run: forget the last one's declaration, name and locator, so none is
        # answered from a package this instance collected before -- or from a
        # declaration an operator has since changed.
        self._channels = NOTHING_MONITORED
        self._package_name = ""
        self._locator = ""
        return ""

    def source_for(self, *, package_id: int) -> str:
        """Return the first monitored channel's locator, and remember what the run is about.

        The declaration is read here, once, and at *run* time -- so a channel added
        by an operator takes effect on the next collection rather than at the next
        process restart, and so a run that finds nothing declared fails naming the
        setting rather than observing an empty set of surfaces silently.

        Args:
            package_id: The package being collected.

        Returns:
            `package_locator(first channel, canonical name)`. The remaining channels
            are asked from `translate`, so that this collection is one call per
            channel and no more.

        Raises:
            LicenseChannelError: On every refusal `monitored_channels` makes -- an
                empty, mistyped, blank, duplicated, separator-carrying or over-long
                declaration, and one naming more channels than a collection may ask
                about -- and when the package's canonical name is not a segment a
                channel could serve it under. See that class for why it escapes
                rather than becoming an evidence row.

        """
        self._channels = monitored_channels(getattr(settings, CHANNELS_SETTING, ()))
        # `core/ledger.py` refuses a package_id naming no package before the opening
        # ledger row is written (`CPM-EVIDENCE-S09`), so the row exists by the time
        # a hook runs -- unless it went between the two, which is a narrow race and
        # not one this collector may answer with a bare `DoesNotExist` out of
        # `collect()`.
        try:
            self._package_name = Package.objects.values_list("canonical_name", flat=True).get(pk=package_id)
        except Package.DoesNotExist as gone:
            message = (
                f"package {package_id} has no row, so this collector has no name to ask a channel about. The run "
                f"ledger checks the key before it opens a row (CPM-EVIDENCE-S09), so a package that is absent "
                f"here went between that check and this read."
            )
            raise LicenseChannelError(message) from gone
        self._locator = package_locator(self._channels[0], self._package_name)
        return self._locator

    def translate(self, payload: Payload, *, package_id: int, observed_at: datetime) -> Sequence[AppendOnlyModel]:
        """Turn the first channel's answer, plus one bounded call per remaining channel, into a row per channel.

        Args:
            payload: What the *first* monitored channel said, recorded. Reached only
                for a call the source answered -- absence and failure of that one
                call are the base's to record.
            package_id: The package the observation is about.
            observed_at: The instant to stamp every row with, from the injected
                clock. The base refuses a row stamped with anything else.

        Returns:
            One unsaved `LicenseFinding` per monitored channel, in declared order.

        Raises:
            LicenseDocumentError: When the *first* channel's document cannot be read
                as what it claims to be. The base writes an `error` row and
                re-raises. A later channel's cannot escape -- see
                `_channel_instead`.

        """
        # `source_for` always runs before `translate` on the base's per-package path
        # and a locator is answered only for a declaration `monitored_channels`
        # accepted, so the tuple is non-empty by the time this is reached.
        facts = [channel_license(payload.body, channel=self._channels[0], source=payload.source)]
        facts.extend(self._channel_instead(channel=channel) for channel in self._channels[1:])
        return [self._row_for(fact, package_id=package_id, observed_at=observed_at) for fact in facts]

    def _channel_instead(self, *, channel: str) -> ChannelLicense:
        """Ask one further channel what licence it states, and never let its failure cost another channel's answer.

        **One of this collector's bounded calls**, and it is bounded two ways: it is
        one locator, and no way of failing raises. The second is the invariant
        rather than an omission -- `CPM-FR-15`'s partial success on the per-package
        path *is* this method returning a row that says "this channel could not be
        read" beside rows another channel earned, and an exception escaping here
        would discard every one of them. It is *not* bounded by being un-retried:
        the transport's retry policy is mounted on the session, so this call is
        retried exactly like the one the base makes, which is what
        `MAX_MONITORED_CHANNELS` exists to bound.

        The base's allowance was charged once, before the first call, so this
        request is not counted against it; neither is it a conditional request, so
        channels after the first re-transfer their document on every run. Both are
        the `deferred` entries `CPM-CURRENCY-S04` recorded against the same shape and
        `CPM-SECURITY-S03` restates against this one.

        **Every reason built here is cleaned before it is carried**, because every
        one of them interpolates a third party's exception message and the rows this
        method produces are written by one `bulk_create` with no `DatabaseError`
        handler over it. An uncleaned NUL byte in one transport failure's message
        would discard every channel's row from inside the driver -- exactly what this
        method exists not to do.

        Args:
            channel: The channel to ask.

        Returns:
            What the channel stated, that it does not serve the package, or that
            this run could not find out -- which are three different claims and
            never one.

        """
        try:
            locator = package_locator(channel, self._package_name)
        except LicenseChannelError as unnameable:
            return _unread(
                channel=channel,
                source="",
                state=LICENSE_ERROR,
                detail=_safe_detail(f"{UNREAD_CHANNEL_DETAIL}: {unnameable}"),
            )
        try:
            payload = self._transport.fetch(locator, headers=request_headers(declared=self._headers, entry=None))
        except Exception as failure:  # noqa: BLE001 - see below
            # Caught this widely and deliberately, on the terms the base catches
            # around `translate`: nothing is swallowed -- the reason becomes the
            # row's own `detail` -- and the guarantee being defended does not depend
            # on which way a substituted transport, a socket library or a DNS
            # resolver breaks. A narrower `except TransportError` would let anything
            # else discard every answering channel's rows, and from the sentinel
            # path would replace the reason the run is recording.
            return _unread(
                channel=channel,
                source=locator,
                state=LICENSE_ERROR,
                detail=_safe_detail(
                    f"{UNREAD_CHANNEL_DETAIL}: {locator} could not be read: {type(failure).__name__}: {failure}",
                ),
            )
        if payload.not_modified:
            # This request carried no validator, so a `304` is the source answering
            # a question nobody asked and there is no body behind it. Left to fall
            # through it would read as a document that is not JSON, which is a
            # refusal describing the wrong problem.
            return _unread(
                channel=channel,
                source=locator,
                state=LICENSE_ERROR,
                detail=_safe_detail(
                    f"{UNREAD_CHANNEL_DETAIL}: {locator} answered that nothing had changed, to an unconditional "
                    f"request",
                ),
            )
        if not payload.found:
            # The channel's *own* answer, which is why this is `not_found` rather
            # than `error`: it said the package is not there, which is an
            # observation and not a failure to look.
            return _unread(
                channel=channel,
                source=locator,
                state=LICENSE_NOT_FOUND,
                detail=_safe_detail(f"{locator}: {ABSENT_FROM_CHANNEL_DETAIL}"),
            )
        try:
            return channel_license(payload.body, channel=channel, source=locator)
        except Exception as unreadable:  # noqa: BLE001 - as above
            # Inside the `try` deliberately, and as widely. Raised, it would leave
            # `translate`, and the base would write one `error` row over answers the
            # channels before it had already given -- exactly what this method exists
            # not to do.
            return _unread(
                channel=channel,
                source=locator,
                state=LICENSE_ERROR,
                detail=_safe_detail(f"{UNREAD_CHANNEL_DETAIL}: {type(unreadable).__name__}: {unreadable}"),
            )

    def sentinel_evidence(
        self,
        *,
        state: OutcomeState,
        package_id: int,
        observed_at: datetime,
        detail: str,
    ) -> AppendOnlyModel:
        """Return one row carrying the sentinel the base decided on, for the channel its call was about.

        Every licence fact is absent, the raw string included: a sentinel row is
        written for a call that produced no document, so there is no stated licence
        to preserve. What the row does carry is the channel it is about -- the first
        monitored one, which is what the base's one call was about -- because
        `license_names_the_channel_it_is_about` requires it of every row and because
        a row that could not name a channel would be an observation of nowhere.

        **This shapes one row; `sentinel_evidence_rows` decides how many there
        are.** The base calls the plural hook, and this collector overrides it --
        and the override builds the first channel's row through `_sentinel_row`
        directly rather than through this method, so on every path the base takes
        this hook is **not** reached at all. It stays the single-row shaper the
        base's contract requires, it makes no call of its own, and it is the hook a
        caller reaching this collector directly meets: `_require_shapeable` below is
        the refusal that caller gets, and it is deliberately the only one, for the
        reason `_require_shapeable` gives.

        Args:
            state: `OutcomeState.ERROR` or `OutcomeState.NOT_FOUND`, decided by the
                base.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with.
            detail: What happened, in words worth storing beside the state. Cleaned
                and bounded rather than trusted -- see `_safe_detail`: on the `error`
                path it carries a third party's exception message.

        Returns:
            One unsaved `LicenseFinding` carrying the state's value verbatim in
            `state` (`CPM-AD-24`).

        Raises:
            CollectorConfigurationError: When asked for a state this collector has
                no row shape for -- `ok`, `normalized`, `unknown` or
                `not_applicable`. `ok` because it is not in this vocabulary at all;
                `normalized` because a determinate row is a licence a channel
                *stated*, which a sentinel path never has, and it is the refusal
                `CPM-SECURITY-S03`'s matrix names; `unknown` because that row is
                `translate`'s to write with the reason the run established;
                `not_applicable` because every package a channel could serve is
                licensed under something, so `inapplicability` never answers a
                reason and `license_findings` refuses it outright.

                Also when no declaration is remembered -- see `_asked_channel`.

        """
        self._require_shapeable(state)
        return self._sentinel_row(
            state=state.value,
            package_id=package_id,
            observed_at=observed_at,
            detail=_safe_detail(detail),
            channel=self._asked_channel(),
            source=self._locator,
        )

    def sentinel_evidence_rows(
        self,
        *,
        state: OutcomeState,
        package_id: int,
        observed_at: datetime,
        detail: str,
    ) -> Sequence[AppendOnlyModel]:
        """Return one row per monitored channel, asking the channels the base's own call never reached.

        **This is what keeps "one row per channel" true on the paths the base
        decides.** The base's one call is the first declared channel's, and its
        `404` or its failure ends the collection before `translate` runs -- so
        without this hook a package absent from channel one would record nothing
        whatever about channel two. `CPM-CURRENCY-S04` was patched for exactly that
        defect and this collector does not repeat it.

        **A `not_found` asks the remaining channels; an `error` does not, and the
        difference is the ledger row.**

        - `not_found` means the first channel *answered*, and answered "no such
          package". The allowance was granted, one call was made, and the base
          finalizes the run `succeeded` -- so the remaining channels are asked
          exactly as `translate` would have asked them, and a channel that does
          state a licence is recorded as `normalized` beside the first channel's
          absence.
        - `error` means the run has already been declared `failed` before this is
          reached, and it is reachable from a *refused allowance* as well as from a
          failed call. Issuing calls here would spend the remote budget the limiter
          has just refused (`CPM-AD-20`) and would write determinate rows underneath
          a ledger row that says the run failed. So every channel gets an `error`
          row carrying the base's own reason, and nothing is asked.

        **Nothing here raises**, except over a missing declaration, which is the
        same invariant `_channel_instead` carries and matters more here: this runs on
        a path that is already recording a failure, where an exception would replace
        the reason being recorded.

        Args:
            state: The sentinel the base decided on.
            package_id: The package the observation is about.
            observed_at: The instant to stamp every row with.
            detail: What happened, in words worth storing beside the state.

        Returns:
            One unsaved `LicenseFinding` per monitored channel, in declared order.

        Raises:
            CollectorConfigurationError: When no declaration is remembered -- see
                `_asked_channel`. It is the one thing this hook refuses rather than
                records, because there is no channel for a row to be about and a
                blank one is refused by the table itself.

                It deliberately refuses no *state*. `sentinel_evidence` does, and is
                the hook a caller reaching this collector directly meets; this one
                is called from paths that are already recording a failure, where a
                raise would replace the reason being recorded.

        """
        reason = _safe_detail(detail)
        rows: list[AppendOnlyModel] = [
            self._sentinel_row(
                state=state.value,
                package_id=package_id,
                observed_at=observed_at,
                detail=reason,
                channel=self._asked_channel(),
                source=self._locator,
            ),
        ]
        for channel in self._channels[1:]:
            fact = (
                self._channel_instead(channel=channel)
                if state is OutcomeState.NOT_FOUND
                else _unread(channel=channel, source="", state=LICENSE_ERROR, detail=reason)
            )
            rows.append(self._row_for(fact, package_id=package_id, observed_at=observed_at))
        return rows

    def _require_shapeable(self, state: OutcomeState) -> None:
        """Refuse a sentinel state this collector has no row shape for.

        Asked by `sentinel_evidence` and deliberately **not** by
        `sentinel_evidence_rows`: the plural hook is the one the base calls, on paths
        that are already recording a failure, and a raise from it would replace the
        reason being recorded.

        **What stands behind the plural hook is this collector's own discipline and
        not a backstop in `core`.** The base checks that a sentinel row carries the
        state it decided on verbatim and that no `ok` row is written under a failed
        run -- but `LicenseOutcome` has no `ok` member at all, so that second check
        can never fire for this table and is structurally inert here. What actually
        holds the line is narrower and local: `sentinel_evidence_rows` is reached
        only with `error` or `not_found`, its `error` branch issues no call and can
        therefore produce no determinate row, and every row it builds goes through
        `_row_for` or `_sentinel_row`, both of which construct a `LicenseFinding` the
        table's own constraints then check at insert.

        Args:
            state: The state the caller asked for.

        Raises:
            CollectorConfigurationError: For every state but `error` and
                `not_found`. Refused at the call rather than at the insert, which is
                where a row carrying `normalized` and no expression would land --
                several frames from the call that was wrong.

        """
        # Written as two comparisons rather than as membership of a declared set,
        # for the reason `CondaPackageCollector._require_shapeable` gives:
        # `tests/unit/django_apps/test_single_ordering_audit.py` reads a literal
        # holding two or more `OutcomeState` members outside `core/outcomes.py` as a
        # second precedence order, and it is right to.
        if state is not OutcomeState.ERROR and state is not OutcomeState.NOT_FOUND:
            message = (
                f"{type(self).__name__}.sentinel_evidence was asked for {state.value!r}, and this collector "
                f"shapes a sentinel row for {OutcomeState.ERROR.value!r} and {OutcomeState.NOT_FOUND.value!r} "
                f"only. A license question applies to every package a channel could serve, so there is no "
                f"{OutcomeState.NOT_APPLICABLE.value!r} row to write -- license_findings refuses one outright; "
                f"{OutcomeState.UNKNOWN.value!r} is written by translate with the reason the run established; "
                f"and {NORMALIZED!r} is a license a channel stated, which a sentinel path never has."
            )
            raise CollectorConfigurationError(message)

    def _sentinel_row(  # noqa: PLR0913 - one parameter per column a sentinel row carries
        self,
        *,
        state: str,
        package_id: int,
        observed_at: datetime,
        detail: str,
        channel: str,
        source: str,
    ) -> LicenseFinding:
        """Return one sentinel row about one channel.

        Args:
            state: The state the row carries, verbatim (`CPM-AD-24`).
            package_id: The package the observation is about.
            observed_at: The instant to stamp it with.
            detail: What happened, already cleaned and bounded.
            channel: The channel the row is about.
            source: The locator it is about, blank where none was built.

        Returns:
            The unsaved row, with every licence fact absent.

        """
        return LicenseFinding(
            observed_at=observed_at,
            package_id=package_id,
            trace_id=current_trace_id(),
            source=source,
            state=state,
            channel=channel,
            raw_license="",
            normalized_license="",
            detection_method="",
            detail=detail,
        )

    def _row_for(self, fact: ChannelLicense, *, package_id: int, observed_at: datetime) -> LicenseFinding:
        """Return the evidence row one fact earns.

        The one place a `ChannelLicense` becomes a row, so `translate` and
        `sentinel_evidence_rows` cannot come to disagree about which column a fact
        lands in.

        Args:
            fact: What one channel said.
            package_id: The package the observation is about.
            observed_at: The instant to stamp it with.

        Returns:
            The unsaved row, carrying the raw string exactly as the channel stated
            it beside whatever normalization made of it.

        """
        return LicenseFinding(
            observed_at=observed_at,
            package_id=package_id,
            trace_id=current_trace_id(),
            source=fact.source,
            state=fact.state,
            channel=fact.channel,
            raw_license=fact.raw_license,
            normalized_license=fact.normalized_license,
            detection_method=fact.detection_method,
            detail=fact.detail,
        )

    def _asked_channel(self) -> str:
        """Return the channel the base's one call was about.

        Returns:
            The first monitored channel.

        Raises:
            CollectorConfigurationError: When no declaration is remembered. Refused
                rather than answered with a blank: a blank channel is a row
                `license_names_the_channel_it_is_about` refuses at insert, and on the
                base's `not_found` branch that write is not wrapped -- so the
                `IntegrityError` would escape raw and replace the reason the run was
                recording. Unreachable through `collect()`, where `source_for`
                refuses an empty declaration before the base gets anywhere near a
                sentinel.

        """
        if not self._channels:
            message = (
                f"{type(self).__name__} was asked for a sentinel row before {CHANNELS_SETTING} was read, so there "
                f"is no channel for the row to be about. Every row in license_findings names one, and a blank "
                f"channel is refused by the table itself -- several frames from the call that was wrong."
            )
            raise CollectorConfigurationError(message)
        return self._channels[0]
