"""What is actually installable: the published version and build on each monitored channel.

`CPM-FR-10`: obtain "published version, build string, and channel for each
monitored channel", with each monitored channel producing its own observation and
channels never merged. This module is that collector, and it is the fourth
surface `CPM-EP-CURRENCY` records.

**The gap it closes.** A package can be current upstream, current on PyPI and
current in the conda-forge recipe while the artifact a person would actually
install is months behind -- and until this table exists, `CPM-FR-16`'s currency
comparison has no published version to compare against. What the other three
collectors record is what somebody *published*; what this one records is what a
channel *serves*.

**One row per `(channel, platform)`, and never fewer.** AC 1 forbids merging
channels, and a build string is a property of a *build*, which is per platform --
so a row naming a channel and one build string would already have merged the
platforms to produce it. Splitting on both is the only shape in which no row
stands for two of anything, and it is what makes "installable on `linux-64` but
not on `osx-arm64`" a fact this product can state.

**Several rows come out of one collection rather than out of several runs.** The
observation window and the ledger row are per `(collector, package)`
(`CPM-AD-7`, `CPM-AD-23`), so collecting each channel as its own run would have
the second channel suppressed by the first. `translate` returns a **sequence** and
the base inserts it -- this is the first per-package collector to use that -- and
it is what `CPM-FR-15`'s partial success looks like here: a channel that fails
becomes `error` rows for that channel's pairs and never discards another
channel's answer.

**One call per channel, and the first of them is the base's.** `source_for`
names the first declared channel's package document; `translate` reads that
answer and then makes one bounded call per remaining channel. Bounded means one
locator and no way of failing that raises -- **not** un-retried: the retry policy
`core/transport.py` mounts lives on the session, so every request this module
issues is retried exactly like the one the base issues. That is why the call
count is capped (`MAX_MONITORED_CHANNELS`) and why the retry budget is smaller
than the shared default; the arithmetic is reconciled against the inherited soft
time limit in `tests/unit/django_apps/test_conda_package.py`. Reading a channel's
`repodata.json` instead is deliberately not done: a per-platform index runs to
hundreds of megabytes, and the per-package document answers the same question in
kilobytes.

**The version recorded is the one the channel calls latest, and that is not the
same as what an install resolves to.** anaconda.org's `latest_version` spans every
label, so a package whose newest upload is a release candidate on a `dev` label
states that candidate as latest. `CPM-FR-10` asks for the version the channel
states and this story's contract fixes it, so the candidate is what is recorded --
and the row says which labels the observed file carried whenever they do not
include `DEFAULT_LABEL`, because a reader who assumed the two agree would be
wrong and nothing else on the row would tell them.

**A first channel that answers "no such package" does not end the collection**,
and that is what `sentinel_evidence_rows` is for. The base's `not_found` branch
writes its rows without reaching `translate`, so a collector that owed one row
per surface could not answer for the surfaces the base's one call never touched
-- AC 1 failing on exactly the case it exists for, a package absent from one
channel and published on another. `CPM-CURRENCY-S04` added that hook to
`core/collection.py`: non-abstract, defaulted to the single row every other
collector already wrote, and overridden here to ask the remaining channels and
answer for every pair. An `error` is deliberately *not* the same case: the run
has been declared `failed` before the hook is reached and the reason may be a
refused allowance, so every pair gets an `error` row and nothing is asked.

**Which channels and platforms are monitored is configuration, and it ships
empty.** PRD Open Question 4 is unresolved and explicitly blocks this epic.
Choosing a channel here would answer it by default and would be wrong in exactly
the way `CPM-IDENTITY-S07`'s watchlist would have been wrong had it shipped
populated: a component monitoring a channel nobody chose would record facts about
the wrong surface, permanently. So the mechanism ships, `config/settings/base.py`
declares both lists empty, and a run that finds nothing declared fails loudly
naming the setting (`CondaChannelError`). A settings module that declares no such
name at all is refused earlier still, at `AppConfig.ready()`.

**The settings access is a read, not an import.** Nothing under
`src/django_apps/` imports `config` (inherited `AD-4`); what happens here is a
read of a value the platform composed, exactly as `collectors/apps.py` reads the
watchlist path. The rule that turns a declaration into a usable pair --
`monitored` -- is a pure function that takes the two values and refuses what
cannot be a channel or a platform, so every branch of it is reachable with no
settings module in sight.

**No comparison of any kind.** The published version is the one the channel
itself states as latest, recorded exactly as spelled. Ranking it against an
upstream version is `CPM-FR-16`'s policy pass (`CPM-AD-8`), and a collector that
normalised a version would be writing a derived value into a row nothing may
correct.

**The pure functions are the whole of what this module decides.** `monitored`,
`package_locator` and `channel_facts` take data and return data, reachable with
no database, no socket and no clock (`CPM-AD-27`).

**The `error` and `not_found` rows the base writes go through
`sentinel_evidence_rows`, and this module invents neither.** The base decides which
sentinel and that there is always one (`CPM-NFR-3`); this module decides what a
row in `conda_package_snapshots` looks like, and refuses a state it has no row
shape for -- which here includes `not_applicable`, because this collector's
question applies to every package a channel could serve.

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
from conda_package_supply_chain_monitor.collectors.models import CondaPackageSnapshot
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
    "ANACONDA_API_HOST",
    "ATTRS_FIELD",
    "BUILD_FIELD",
    "BUILD_NUMBER_FIELD",
    "CHANNELS_SETTING",
    "COLLECTOR_NAME",
    "CONDA_PACKAGE_CACHE_TTL",
    "CONDA_PACKAGE_CADENCE",
    "CONDA_PACKAGE_FRESHNESS_TARGET",
    "CONDA_PACKAGE_HEADERS",
    "CONDA_PACKAGE_OBSERVATION_WINDOW",
    "CONDA_PACKAGE_RATE_LIMIT",
    "CONDA_PACKAGE_RETRIES",
    "CONDA_PACKAGE_TIMEOUT",
    "CONDA_SUBDIRS",
    "DEFAULT_LABEL",
    "FILES_FIELD",
    "LABELS_FIELD",
    "LATEST_VERSION_FIELD",
    "MAX_BUILD_NUMBER",
    "MAX_DOCUMENT_CHARACTERS",
    "MAX_MONITORED_CHANNELS",
    "NOTHING_MONITORED",
    "NO_LATEST_VERSION_DETAIL",
    "NO_PUBLISHED_FILE_DETAIL",
    "OFF_LABEL_DETAIL",
    "PLATFORMS_SETTING",
    "SUBDIR_FIELD",
    "TOLERATED_MISSED_RUNS",
    "UNREAD_CHANNEL_DETAIL",
    "VERSION_FIELD",
    "ChannelFact",
    "CondaChannelError",
    "CondaDocumentError",
    "CondaPackageCollector",
    "Monitored",
    "channel_facts",
    "declaration_fault",
    "monitored",
    "package_locator",
]

#: What this collector is called, on its ledger rows, in its cache keys and in
#: the registry `config/startup/stage_two.py` sweeps. It is the `collect` half of
#: its task name too, which is what routes it (`core/queues.py`).
COLLECTOR_NAME: Final[str] = "conda_package"

#: The settings names this collector reads its monitored surfaces from. Spelled
#: once, here, so the refusal, the boot check in `collectors/apps.py` and the read
#: all name the same thing -- a literal in each would be three names that can
#: drift apart.
CHANNELS_SETTING: Final[str] = "CPM_MONITORED_CHANNELS"
PLATFORMS_SETTING: Final[str] = "CPM_MONITORED_PLATFORMS"

#: How often this collector is meant to run, and the number every other interval
#: below is derived from.
#:
#: `CPM-NFR-2` gives version currency "daily to weekly", and this is the **fast**
#: end -- the same choice the two release collectors make, and for the same
#: reason turned around: what this collector observes is a *published artifact*,
#: which appears the moment a channel's build lands and is exactly the thing an
#: engineer asks "is it out yet" about. A weekly read would make the answer up to
#: six days old for the surface with the shortest useful half-life. The cadence
#: itself is data in `django_celery_beat` (`CPM-AD-20`); this is the number the
#: arithmetic below assumes, and `CPM-CURRENCY-S05` reconciles the two at
#: start-up, in both directions, from `collectors/apps.py`'s `ready()`.
CONDA_PACKAGE_CADENCE: Final[timedelta] = timedelta(days=1)

#: How many consecutive missed collections may pass before this product stops
#: calling an answer current -- PRD Open Question 7's risk posture for the
#: version-currency signal class, which this surface belongs to.
TOLERATED_MISSED_RUNS: Final[int] = 1

#: How long this collector's evidence may be read as current (`CPM-AD-28`):
#: `cadence x (1 + tolerated_missed_runs)`, strictly greater than the cadence so
#: a package does not read stale at exactly the moment its next run is due.
CONDA_PACKAGE_FRESHNESS_TARGET: Final[timedelta] = CONDA_PACKAGE_CADENCE * (1 + TOLERATED_MISSED_RUNS)

#: How long a successful observation suppresses the next one (`CPM-AD-7`). Half
#: the cadence, so a scheduled run is never suppressed by the previous one and a
#: second run of one package inside half a day still is.
CONDA_PACKAGE_OBSERVATION_WINDOW: Final[timedelta] = CONDA_PACKAGE_CADENCE / 2

#: How many times a failed request is retried, and therefore what the rate
#: limiter is charged against per collection.
#:
#: **One rather than the shared default of three, and the reason is that this
#: collector makes several calls where its siblings make one or two.** Every call
#: it issues goes through the base's `RequestsTransport`, whose retry policy is
#: mounted on the *session* -- so a call made from inside `translate` is retried
#: exactly like the one the base makes, and there is no such thing as an
#: un-retried call here. A collection is therefore up to
#: `MAX_MONITORED_CHANNELS` fully retried calls inside one Celery task, and at
#: the shared default that arithmetic does not fit the inherited soft time limit
#: (`CPM-AD-9`) at any usable timeout. One retry still recovers the transient
#: blip a retry exists for; the reconciliation is in
#: `tests/unit/django_apps/test_conda_package.py` and is made against the
#: settings module's own limit rather than against a number repeated here.
CONDA_PACKAGE_RETRIES: Final[int] = 1

#: Seconds any single connect or read phase may take.
#:
#: **Lower than any sibling's, and the difference is the channel count.** One
#: collection is up to `MAX_MONITORED_CHANNELS` calls, each retried, so the
#: figure that has to fit inside the inherited 60-second soft limit is
#: `MAX_MONITORED_CHANNELS * worst_case_call_seconds(timeout, retries)` -- 40
#: seconds at these declarations, which leaves the ledger writes around it
#: twenty. Nothing here is described as un-retried, because nothing here is.
CONDA_PACKAGE_TIMEOUT: Final[float] = 2.5

#: The most channels one collection may be asked to observe.
#:
#: **A time bound rather than an opinion about which channels are worth
#: monitoring.** Which channels this product watches is PRD Open Question 4 and is
#: not this module's to answer; how many of them one Celery task can ask about
#: inside its soft time limit *is*. Every channel costs a **retried** connect and
#: read -- the transport's retry policy is mounted on the session and applies to
#: every request it issues, wherever in this module the request is made -- so an
#: unbounded declaration is an unbounded worst case in a task the platform will
#: kill at sixty seconds, and a killed task writes no rows at all, which is worse
#: than refusing the declaration that caused it. Four is what the arithmetic
#: above affords with margin, and it is comfortably more than the channel sets
#: this product was described against (conda-forge, the defaults channel, one
#: community channel, one internal mirror). Platforms are deliberately *not*
#: bounded here: a platform costs a row rather than a call, and rows are what the
#: table is for.
MAX_MONITORED_CHANNELS: Final[int] = 4

#: How hard this collector may push its source (`CPM-AD-20`).
#:
#: anaconda.org publishes **no numeric ceiling** for its package API, so this is a
#: declared courtesy bound rather than a number the source stated -- and it is
#: half what `collectors/pypi_release.py` declares against a source with the same
#: silence, because a collection here issues up to `MAX_MONITORED_CHANNELS` calls
#: rather than one. Thirty a minute is one request every two seconds, which at the
#: `1 + retries` the base charges is seven packages a minute. Written down so the
#: limit is a decision a reader can see and one the base enforces, rather than an
#: allowance that is unlimited by omission.
CONDA_PACKAGE_RATE_LIMIT: Final[RateLimit] = RateLimit(calls=30, per=timedelta(minutes=1))

#: What this collector's source expects on every request (`CPM-AD-20`,
#: `CPM-AD-27`): declared here, merged and sent by the base, never by this module.
#: `Accept` asks for the JSON representation `channel_facts` reads and the
#: `User-Agent` is the one identity every collector shares
#: (`collectors/agent.py`). Nothing conditional is declared -- the validators are
#: the base's.
CONDA_PACKAGE_HEADERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    },
)

#: How long a remembered response may be replayed before it is re-read. A week,
#: so a scheduled daily collection revalidates rather than re-transfers a document
#: that lists every file a channel ever published for the package; an entry that
#: expired inside the cadence would make the cache inert.
#:
#: **It covers the first monitored channel and no other.** The base composes a
#: conditional request, reads the cache and writes to it around the *one* call it
#: makes; the calls this module issues for channels two onward carry no validator
#: and remember nothing, so those channels re-transfer their whole document on
#: every run -- and a `304` from one of them is a source answering a question
#: nobody asked, which the row records as `error`. Extending the cache to them
#: means reaching past the base's orchestration into the response cache, and it is
#: a `deferred` entry on `CPM-CURRENCY-S04`.
CONDA_PACKAGE_CACHE_TTL: Final[timedelta] = timedelta(days=7)

#: The host this collector reads. One host for every channel: a channel is a path
#: segment under it rather than a host of its own.
ANACONDA_API_HOST: Final[str] = "api.anaconda.org"

#: What a channel, a platform or a package name may be spelled with, once this
#: collector has lower-cased it.
#:
#: The same grammar the feedstock collector applies to a repository segment, and
#: for the same reason: what is being built is one path segment of a locator, so
#: what must be refused is anything that could make it two -- or make it a
#: navigation instruction. A leading `-` or `.` is refused, which is also what
#: refuses `.` and `..`; a `/` or a `\` anywhere is refused, which is the
#: "carries a path separator" the matrix names. Refused rather than encoded: a
#: declared channel is a decision an operator wrote down, and quietly encoding one
#: into something else would ask a question nobody asked.
_SEGMENT: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_][a-z0-9._-]*$")

#: The longest channel document this collector will hand to `json.loads`, in
#: characters.
#:
#: The package document lists every file of every version the channel holds, so
#: for a large, long-lived package across every subdir it runs to several
#: mebibytes. Eight mebibytes is comfortably above that -- **and it is bounded by
#: the channel count as well as by the document**, which is what makes it lower
#: than the sibling that reads one document per collection: up to
#: `MAX_MONITORED_CHANNELS` of these are parsed inside one soft time limit, so
#: the figure that matters is the product rather than the single bound.
#:
#: **What the bound protects is the parse and nothing earlier**: by the time a
#: body arrives here the transport has already transferred it and decoded it to a
#: string, so this saves neither the transfer nor the memory of holding it -- what
#: it refuses is handing `json.loads` a document no honest source serves, which is
#: where a worker's soft time limit would be spent (`CPM-AD-9`). Bounding the
#: transfer needs a streamed read in `core/transport.py` and is a `deferred` entry
#: on `CPM-CURRENCY-S04`.
MAX_DOCUMENT_CHARACTERS: Final[int] = 8 * 1024 * 1024

#: The largest build number this collector will record: PostgreSQL's `integer`
#: ceiling, which is what `PositiveIntegerField` maps to on the database this
#: product deploys against. Declared rather than read off the column, on the terms
#: `collectors/feedstock.py` states at length: Django derives the field's
#: validators from the *running* backend, so a reader that took the ceiling from
#: the field would accept, on SQLite, a number PostgreSQL refuses at insert.
MAX_BUILD_NUMBER: Final[int] = 2_147_483_647

#: The conda subdirs a declaration may name, and the whole of the vocabulary.
#:
#: **Closed rather than pattern-matched, and that is a correctness rule rather
#: than tidiness.** A subdir is a value conda defines, not a name an operator
#: invents, and a grammar that merely accepted "a lower-case segment" would let
#: `linux_64` or `osx-arm-64` through -- producing a `not_found` row saying this
#: channel's latest version has no file on that platform, for a platform that
#: does not exist. That is a false statement about the channel, written
#: permanently into a log nothing may correct and indistinguishable from a true
#: one. Refusing the declaration is the only reading that cannot lie.
#:
#: `noarch` is in the set: it is a real subdir a channel serves files under, and
#: a package published only as `noarch` is installable everywhere -- which is
#: exactly the fact an operator monitoring it wants.
CONDA_SUBDIRS: Final[frozenset[str]] = frozenset(
    {
        "noarch",
        "linux-32",
        "linux-64",
        "linux-aarch64",
        "linux-armv6l",
        "linux-armv7l",
        "linux-ppc64",
        "linux-ppc64le",
        "linux-riscv64",
        "linux-s390x",
        "osx-64",
        "osx-arm64",
        "win-32",
        "win-64",
        "win-arm64",
        "zos-z",
    },
)

#: The fields of the channel document this collector reads, named rather than
#: spelled at the call sites so the reader and the cases that build documents
#: cannot drift.
LATEST_VERSION_FIELD: Final[str] = "latest_version"
FILES_FIELD: Final[str] = "files"
VERSION_FIELD: Final[str] = "version"
ATTRS_FIELD: Final[str] = "attrs"
SUBDIR_FIELD: Final[str] = "subdir"
BUILD_FIELD: Final[str] = "build"
BUILD_NUMBER_FIELD: Final[str] = "build_number"
LABELS_FIELD: Final[str] = "labels"

#: The label a channel serves by default, and therefore the one `conda install`
#: reads unless a caller names another.
#:
#: **What this collector records is the version the channel states as latest,
#: across every label**, because that is what `CPM-FR-10` asks for and what the
#: story's contract fixes: "the published version is the one the channel itself
#: states as latest". A channel whose newest upload is a release candidate on a
#: `dev` label therefore states that candidate as latest, and this collector
#: records it -- while `conda install` on the default label resolves to something
#: older. Rather than silently substitute a different question, the row says which
#: labels the file it observed carried whenever they are not the default ones, so
#: a reader is never left to assume the two agree.
DEFAULT_LABEL: Final[str] = "main"

#: What a row says in its own words, in each of the ways it is reachable. Named
#: so the row a run writes and the case that reads it back cannot drift.
NO_LATEST_VERSION_DETAIL: Final[str] = (
    "this channel serves the package but names no latest version, so nothing is recorded as published here"
)
NO_PUBLISHED_FILE_DETAIL: Final[str] = "this channel's latest version has no file on this platform"
OFF_LABEL_DETAIL: Final[str] = (
    "the file publishing this version is served under labels a default install does not read, so what "
    "`conda install` resolves to on this channel is something else"
)
UNREAD_CHANNEL_DETAIL: Final[str] = (
    "this channel could not be read, so this row records that nothing was established about it and not that "
    "nothing is published there"
)


class CondaChannelError(ValueError):
    """The monitored channels and platforms cannot be turned into a question to ask.

    A `ValueError` subclass, matching `collectors/feedstock.py`'s
    `FeedstockLocatorError` and `collectors/pypi_release.py`'s `PyPILocatorError`:
    every "this input cannot describe what it claims to" in this product is a
    `ValueError`.

    **It escapes `collect()` rather than becoming an evidence row, and that is a
    decision rather than an omission.** `source_for` is called before the window,
    the allowance and the transport, so the run ledger row exists and is finalized
    `failed` carrying this message, and no evidence row is written at all. There
    is nothing honest to write: a row must name the channel and platform it is
    about (`conda_package_names_channel_and_platform`), and every way of reaching
    this class is a way of not knowing which pair the run was going to be about.

    What it refuses is a declaration this product cannot act on: an empty one --
    which is what ships, and which PRD Open Question 4 leaves an operator to
    answer -- one carrying a blank, mistyped, duplicated or separator-carrying
    entry, one naming more channels than a collection can ask about inside its
    soft time limit, and a package whose canonical name is not a segment a channel
    could serve it under.
    """


class CondaDocumentError(ValueError):
    """A channel's package document could not be read as what it claims to be.

    Raised from `translate` **for the first channel only** -- the one the base
    fetched -- which the base answers by writing an `error` row and re-raising
    unchanged, so `CPM-NFR-3`'s guarantee holds on this path too: never a clean
    result, and never no row. Refused rather than partially read: a document this
    collector cannot understand is a source whose shape has changed, and reading
    around it would record a published version chosen from whatever happened to
    still parse, permanently.

    A *later* channel's unreadable document never escapes. That call is bounded
    on the terms `collectors/feedstock.py` bounds its second one, so an unreadable
    answer from it becomes `error` rows for that channel's pairs beside the rows
    the channels that did answer earned -- which is what keeps a channel's failure
    from discarding another channel's answer (`CPM-FR-15`).
    """


@dataclass(frozen=True, slots=True)
class Monitored:
    """The channels and platforms one run observes, checked and in declared order.

    Held as a value so `source_for` decides once what the run is about and
    `translate` and `sentinel_evidence` read the same answer.

    Attributes:
        channels: The channels to ask, lower-cased, in the order they were
            declared. Never empty.
        platforms: The conda subdirs each channel is asked about, lower-cased, in
            the order they were declared. Never empty.

    """

    channels: tuple[str, ...]
    platforms: tuple[str, ...]


#: What a collector instance remembers before any run has reached it, and what it
#: is reset to at the start of every one. A value rather than `None`, so the two
#: hooks that read it need no optional-narrowing dance for a state neither can
#: reach through `collect()` -- and empty rather than plausible, so a hook reached
#: without a run says "no pair" instead of naming a channel nobody declared.
NOTHING_MONITORED: Final[Monitored] = Monitored(channels=(), platforms=())


@dataclass(frozen=True, slots=True)
class ChannelFact:
    """What one channel says about one platform, as the fields the evidence row holds.

    One per `(channel, platform)` pair, which is one evidence row. Never a
    failure: a channel that could not be read produces facts carrying
    `OutcomeState.ERROR` and a reason, because a row per pair is owed whatever
    happened.

    Attributes:
        channel: The channel this fact is about.
        platform: The conda subdir this fact is about.
        state: What the look concluded -- `ok`, `not_found` or `error`.
        published_version: The version the channel states as latest, exactly as
            spelled, or blank.
        build_string: The build string of the file publishing that version here,
            or blank.
        build_number: That file's build number, or `None`.
        source: The locator this fact was read from.
        detail: Why a fact is missing, where one is. Empty for an ordinary
            determinate observation.

    """

    channel: str
    platform: str
    state: OutcomeState
    published_version: str
    build_string: str
    build_number: int | None
    source: str
    detail: str


def monitored(channels: object, platforms: object) -> Monitored:
    """Return the monitored surfaces a declaration names, or refuse it.

    Pure: no database, no clock, no network, and no settings module -- the values
    are handed in, so every branch of the rule is reachable without one
    (`CPM-AD-27`).

    Both lists are normalised the way `package_locator` will spell them --
    stripped and lower-cased -- **before** duplicates are looked for, so
    `Conda-Forge` beside `conda-forge` is refused as the one declaration it is
    rather than accepted as two. Order is the operator's: the first channel is the
    one the base calls, and a run whose call order depended on a set's iteration
    would make "which channel does a failed first call cost" unanswerable.

    Args:
        channels: What `CPM_MONITORED_CHANNELS` holds. Typed as `object` because
            the whole point of this function is that a settings module may hold
            anything at all.
        platforms: What `CPM_MONITORED_PLATFORMS` holds.

    Returns:
        The checked pair.

    Raises:
        CondaChannelError: When either declaration is not a list or tuple of
            strings; is empty; carries a blank, mistyped, or separator-carrying
            entry; carries the same entry twice once normalised; carries an entry
            wider than the column that has to record it; or names more channels
            than `MAX_MONITORED_CHANNELS`. Refused rather than defaulted: an
            unusable declaration silently narrowed to the entries that happened to
            parse would record evidence about a set of surfaces nobody chose.

    """
    named = _declared(channels, setting=CHANNELS_SETTING, field="channel", what="channel")
    subdirs = _declared(platforms, setting=PLATFORMS_SETTING, field="platform", what="platform")
    unknown = sorted(set(subdirs) - CONDA_SUBDIRS)
    if unknown:
        message = (
            f"{PLATFORMS_SETTING} names {unknown}, which conda has no subdir for. The vocabulary is closed and "
            f"is {sorted(CONDA_SUBDIRS)}. Refused rather than observed: a declared subdir that does not exist "
            f"would record, for every package and for ever, that a channel's latest version has no file on it "
            f"-- a false statement about the channel that nothing may correct and nothing could tell from a "
            f"true one."
        )
        raise CondaChannelError(message)
    if len(named) > MAX_MONITORED_CHANNELS:
        message = (
            f"{CHANNELS_SETTING} declares {len(named)} channels and one collection may ask about at most "
            f"{MAX_MONITORED_CHANNELS}. Every channel costs a retried call inside one task -- the transport's "
            f"retry policy is mounted on the session and applies to every request it issues -- and a "
            f"declaration whose worst case exceeds the inherited soft time limit (CPM-AD-9) is a task the "
            f"platform kills before it writes anything. Refused rather than truncated: observing some of the "
            f"channels an operator declared, without saying which, is worse than observing none."
        )
        raise CondaChannelError(message)
    return Monitored(channels=named, platforms=subdirs)


def declaration_fault(values: object, *, setting: str, what: str = "entry") -> str:
    """Return why a declaration's *shape* is unusable, or nothing when it is usable.

    Pure, and separate from `monitored` for one reason: an **empty** declaration
    is the shipped state and must let a component boot, while a declaration of the
    wrong *shape* is a misconfiguration that should stop it. `collectors/apps.py`
    asks this at `AppConfig.ready()` and `monitored` asks it at run time, so one
    rule decides both and the boot refusal cannot come to accept a shape the run
    refuses.

    **A bare string is refused before a sequence is accepted**, and that is the
    case worth the function: a `str` *is* a sequence of one-character strings, so
    `CPM_MONITORED_CHANNELS = "conda-forge"` would otherwise be read as eleven
    channels named `c`, `o`, `n` and so on -- eleven locators, eleven rows a run,
    and nothing anywhere saying the declaration had been misread.

    Args:
        values: What the settings module holds.
        setting: The setting's name, for the message.
        what: What its entries are, for the message.

    Returns:
        The reason it cannot be read, or the empty string. An empty list or tuple
        is *usable*: it means no surface is monitored yet, which is a failed
        collection naming the setting rather than a component that will not start.

    """
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        return (
            f"{setting} holds {type(values).__name__} rather than a list or tuple of {what} names, so this "
            f"component cannot tell which {what}s it is meant to observe. PRD Open Question 4 leaves the choice "
            f"to an operator; it does not leave the shape open."
        )
    return ""


def _declared(values: object, *, setting: str, field: str, what: str) -> tuple[str, ...]:
    """Return one declaration as checked, normalised, ordered entries, or refuse it.

    Args:
        values: What the settings module holds.
        setting: The setting's name, for the messages.
        field: The column the entries land in, whose width bounds them.
        what: What the entries are, for the messages.

    Returns:
        The entries, stripped, lower-cased and in declared order.

    Raises:
        CondaChannelError: On every refusal `monitored` documents for one
            declaration.

    """
    unusable = declaration_fault(values, setting=setting, what=what)
    if unusable:
        raise CondaChannelError(unusable)
    # Narrowed by the shape check above, which is the one place this module
    # decides what a declaration may be.
    entries: list[object] = list(values)  # type: ignore[call-overload]
    if not entries:
        message = (
            f"{setting} is empty, so no {what} is monitored and there is nothing for this collector to observe. "
            f"It ships empty on purpose: which conda channels and platforms this product watches is PRD Open "
            f"Question 4 and is an operator's decision, and a component that picked one would record evidence "
            f"about a surface nobody chose -- permanently, in a log nothing may correct. Declare {setting} in "
            f"config/settings/base.py and this collector starts observing (docs/deployment.md)."
        )
        raise CondaChannelError(message)

    width = _column_width(field)
    seen: list[str] = []
    for position, value in enumerate(entries):
        entry = _segment(value, setting=setting, position=position, what=what)
        if width is not None and len(entry) > width:
            message = (
                f"{setting} names the {what} {entry!r} at position {position}, which is {len(entry)} characters, "
                f"and the {field} column that records it takes {width}. Refused rather than truncated: a row "
                f"that cannot say which {what} it observed is a row an append-only history cannot tell from its "
                f"neighbours."
            )
            raise CondaChannelError(message)
        if entry in seen:
            message = (
                f"{setting} names the {what} {entry!r} twice -- at position {position} and earlier. Refused "
                f"rather than de-duplicated: two identical rows for one observation would be two facts where "
                f"there is one, and an operator who wrote a {what} twice meant something this collector cannot "
                f"guess at."
            )
            raise CondaChannelError(message)
        seen.append(entry)
    return tuple(seen)


def _segment(value: object, *, setting: str, position: int, what: str) -> str:
    """Return one declared entry as a locator segment, or refuse it.

    Args:
        value: The entry as the settings module holds it.
        setting: The setting's name, for the messages.
        position: Where in the declaration it sits, for the messages.
        what: What the entry is, for the messages.

    Returns:
        The entry, stripped and lower-cased.

    Raises:
        CondaChannelError: When it is not a string, is blank, or is not a single
            locator segment once lower-cased -- which is what refuses a path
            separator, and what refuses `.` and `..`, because neither may begin a
            segment and percent-encoding leaves both untouched.

    """
    if not isinstance(value, str) or not value.strip():
        message = (
            f"{setting} names {value!r} at position {position}, which is not a {what} this collector could ask "
            f"about. A declaration is refused whole rather than read for the entries that happen to parse."
        )
        raise CondaChannelError(message)
    entry = value.strip().lower()
    if not _SEGMENT.match(entry):
        message = (
            f"{setting} names {value!r} at position {position}, which is {entry!r} once lower-cased and is not a "
            f"single locator segment. Refused rather than encoded: a locator built from it would ask about "
            f"nothing, or would be a path the source is entitled to resolve somewhere else."
        )
        raise CondaChannelError(message)
    return entry


def package_locator(channel: str, name: str) -> str:
    """Return the locator naming one package's published files on one channel.

    The one document a channel is asked for, and one call per channel. Not
    `repodata.json`: a channel's per-platform index runs to hundreds of megabytes
    and answers a question about every package, while this document answers the
    question about *this* package -- the latest version the channel states, and
    the files that publish it -- in kilobytes.

    Args:
        channel: The channel, already normalised by `monitored`.
        name: The package's canonical name.

    Returns:
        `https://api.anaconda.org/package/<channel>/<name>`.

    Raises:
        CondaChannelError: When either segment is not a string, is blank, or is
            not a single locator segment once lower-cased. Refused rather than
            encoded, on the terms `_segment` states.

    """
    return (
        f"https://{ANACONDA_API_HOST}/package/"
        f"{_segment(channel, setting=CHANNELS_SETTING, position=0, what='channel')}/"
        f"{_segment(name, setting='canonical_name', position=0, what='package name')}"
    )


def channel_facts(body: str, *, channel: str, platforms: Sequence[str], source: str) -> tuple[ChannelFact, ...]:
    """Read one channel's package document into one fact per monitored platform.

    Pure: no database, no clock, no network.

    **One fact per platform and never fewer**, which is what makes an absence a
    written row rather than a missing one: a platform the channel's latest version
    has no file for is `not_found` with a reason naming the version that exists
    elsewhere, and a channel that names no latest version at all produces
    `not_found` for every platform saying exactly that.

    **The version is the channel's own.** Nothing here ranks, normalises or
    compares -- `CPM-FR-16` is a policy pass (`CPM-AD-8`) -- so what "latest"
    means is whatever the channel says it means, and the row records it as
    spelled.

    Args:
        body: The document the channel served.
        channel: The channel it came from, recorded on every fact.
        platforms: The conda subdirs to answer for, in declared order.
        source: The locator it was served from, recorded on every fact.

    Returns:
        One fact per platform, in the declared order.

    Raises:
        CondaDocumentError: When the body is longer than
            `MAX_DOCUMENT_CHARACTERS`, is not JSON, is not an object, carries a
            `latest_version` or `files` of the wrong type, holds a file entry that
            is not an object or whose fields are mistyped, or names a version or
            build string wider than the column that has to hold it.

    """
    document = _document_in(body, source=source)
    latest = _optional_string(document, field=LATEST_VERSION_FIELD, source=source)
    if not latest:
        return tuple(
            _absent(channel=channel, platform=platform, source=source, detail=NO_LATEST_VERSION_DETAIL)
            for platform in platforms
        )
    _require_storable(latest, field="published_version", source=source, what="published version")

    published = _published_files(document, source=source, latest=latest)
    return tuple(
        _platform_fact(published.get(platform), channel=channel, platform=platform, source=source, latest=latest)
        for platform in platforms
    )


def _platform_fact(
    files: list[_PublishedFile] | None,
    *,
    channel: str,
    platform: str,
    source: str,
    latest: str,
) -> ChannelFact:
    """Return the fact one platform earns from the files publishing the channel's latest version.

    Args:
        files: The files publishing that version on this platform, or `None` when
            the document listed none.
        channel: The channel the document came from.
        platform: The conda subdir this fact is about.
        source: The locator, recorded on the fact.
        latest: The version the channel states as latest.

    Returns:
        A determinate fact naming the build, or an absence naming the version that
        exists elsewhere.

        **Where a platform carries several builds of one version, the recorded
        one is the greatest by build number and, where two share a build number,
        the lexicographically greatest build string.** They are all published, so
        refusing to choose would record no build at all for a platform that
        plainly has one -- and the tie-break is stated rather than left to
        whichever order the channel listed them in, because an arbitrary choice
        recorded permanently is a value a later comparison cannot reproduce.
        `detail` says how many there were, so the column is never mistaken for
        the only build.

        **The row is not a claim about what an install resolves to.** The version
        is the one the channel states as latest across every label, which is what
        `CPM-FR-10` asks for; a file on a non-default label is therefore
        recordable, and `detail` names its labels when they do not include
        `DEFAULT_LABEL` so a reader is never left to assume otherwise.

    """
    if not files:
        return _absent(
            channel=channel,
            platform=platform,
            source=source,
            detail=f"{NO_PUBLISHED_FILE_DETAIL}: the channel states {latest!r} as latest",
        )
    chosen = max(files, key=lambda file: (file.build_number if file.build_number is not None else -1, file.build))
    reasons = []
    if len(files) > 1:
        reasons.append(
            f"the channel lists {len(files)} builds of {latest!r} for this platform and this is the greatest by "
            f"build number, ties broken by build string",
        )
    if chosen.labels and DEFAULT_LABEL not in chosen.labels:
        reasons.append(
            f"{OFF_LABEL_DETAIL}: {list(chosen.labels)}, and not {DEFAULT_LABEL!r}",
        )
    return ChannelFact(
        channel=channel,
        platform=platform,
        state=OutcomeState.OK,
        published_version=latest,
        build_string=chosen.build,
        build_number=chosen.build_number,
        source=source,
        detail="; ".join(reasons),
    )


def _absent(*, channel: str, platform: str, source: str, detail: str) -> ChannelFact:
    """Return the fact a pair with nothing published earns.

    Args:
        channel: The channel this fact is about.
        platform: The conda subdir this fact is about.
        source: The locator it was read from.
        detail: Why there is nothing.

    Returns:
        A `not_found` fact carrying no published fact at all.

    """
    return ChannelFact(
        channel=channel,
        platform=platform,
        state=OutcomeState.NOT_FOUND,
        published_version="",
        build_string="",
        build_number=None,
        source=source,
        detail=detail,
    )


def _unread(
    *,
    channel: str,
    platforms: Sequence[str],
    source: str,
    state: OutcomeState,
    detail: str,
) -> tuple[ChannelFact, ...]:
    """Return one fact per platform for a channel this run could not read.

    The shape a bounded call's failure takes. A channel that raised, answered
    `304` to a request carrying no validator, or served a document whose shape has
    changed still owes a row per monitored platform -- and each of them says what
    happened rather than claiming the channel publishes nothing.

    Args:
        channel: The channel that could not be read.
        platforms: The conda subdirs it was going to be asked about.
        source: The locator that was asked, or blank when none could be built.
        state: What the row records -- `error` for a look that failed,
            `not_found` for a channel that answered "no such package".
        detail: What happened, in words worth storing.

    Returns:
        One fact per platform, carrying no published fact.

    """
    return tuple(
        ChannelFact(
            channel=channel,
            platform=platform,
            state=state,
            published_version="",
            build_string="",
            build_number=None,
            source=source,
            detail=detail,
        )
        for platform in platforms
    )


@dataclass(frozen=True, slots=True)
class _PublishedFile:
    """One file publishing the channel's latest version on one platform.

    Attributes:
        build: The build string, exactly as the channel spelled it.
        build_number: The build number, or `None` where the channel stated none.
        labels: The labels the channel serves this file under, in the order it
            stated them, or empty where it stated none. Read because
            `latest_version` spans every label: a file on a `dev` or `rc` label is
            what the channel calls latest and is *not* what an install on the
            default label resolves to, and a row that did not say so would let a
            reader assume the two agree.

    """

    build: str
    build_number: int | None
    labels: tuple[str, ...]


def _published_files(
    document: dict[str, object],
    *,
    source: str,
    latest: str,
) -> dict[str, list[_PublishedFile]]:
    """Return the files publishing one version, grouped by the subdir they publish it on.

    Args:
        document: The decoded channel document.
        source: The locator, for the messages.
        latest: The version the channel states as latest.

    Returns:
        The files, keyed by subdir. A subdir the version has no file on is simply
        absent from the mapping, which is what makes it a `not_found` row.

    Raises:
        CondaDocumentError: When `files` is not a list, holds an entry that is not
            an object, holds an entry whose `attrs` is not an object, or names a
            build string wider than the column that has to hold it.

    """
    entries = document.get(FILES_FIELD)
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        message = (
            f"{source} served a document whose {FILES_FIELD!r} is {type(entries).__name__} rather than a list. A "
            f"source whose shape has changed is refused rather than read for whatever still parses."
        )
        raise CondaDocumentError(message)

    published: dict[str, list[_PublishedFile]] = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            message = f"{source} lists {type(entry).__name__} at position {position} rather than a published file."
            raise CondaDocumentError(message)
        if _optional_string(entry, field=VERSION_FIELD, source=source) != latest:
            continue
        attributes = _attributes(entry, source=source, position=position)
        subdir = _optional_string(attributes, field=SUBDIR_FIELD, source=source).lower()
        if not subdir:
            continue
        build = _optional_string(attributes, field=BUILD_FIELD, source=source)
        _require_storable(build, field="build_string", source=source, what="build string")
        published.setdefault(subdir, []).append(
            _PublishedFile(
                build=build,
                build_number=_optional_count(attributes, source=source),
                labels=_labels(entry, source=source, position=position),
            ),
        )
    return published


def _labels(entry: dict[str, object], *, source: str, position: int) -> tuple[str, ...]:
    """Return the labels a channel serves one file under, or none where it stated none.

    Args:
        entry: The file entry.
        source: The locator, for the message.
        position: Where the entry sits, for the message.

    Returns:
        The labels, stripped, in the order stated. Empty when the field is absent
        or null, which means the source stated none rather than that the file has
        none.

    Raises:
        CondaDocumentError: When `labels` is present, is not null, and is not a
            list of strings.

    """
    stated = entry.get(LABELS_FIELD)
    if stated is None:
        return ()
    if not isinstance(stated, list) or not all(isinstance(label, str) for label in stated):
        message = (
            f"{source} serves a file at position {position} whose {LABELS_FIELD!r} is not a list of strings. A "
            f"source whose shape has changed is refused rather than read past."
        )
        raise CondaDocumentError(message)
    return tuple(label.strip() for label in stated if label.strip())


def _attributes(entry: dict[str, object], *, source: str, position: int) -> dict[str, object]:
    """Return one file entry's attribute object, or refuse a mistyped one.

    Args:
        entry: The file entry.
        source: The locator, for the message.
        position: Where the entry sits, for the message.

    Returns:
        The attributes, or an empty mapping when the entry carries none -- which
        is a file this collector can say nothing about rather than a document it
        must refuse.

    Raises:
        CondaDocumentError: When `attrs` is present, is not null, and is not an
            object.

    """
    attributes = entry.get(ATTRS_FIELD)
    if attributes is None:
        return {}
    if not isinstance(attributes, dict):
        message = (
            f"{source} serves a file at position {position} whose {ATTRS_FIELD!r} is "
            f"{type(attributes).__name__} rather than an object. A source whose shape has changed is refused "
            f"rather than read past."
        )
        raise CondaDocumentError(message)
    return attributes


def _document_in(body: str, *, source: str) -> dict[str, object]:
    """Decode a document and refuse anything that is not an object.

    Args:
        body: The document the source served.
        source: The locator it was served from, for the messages.

    Returns:
        The decoded object.

    Raises:
        CondaDocumentError: When the body is too long to decode, is not JSON, or
            is not an object.

    """
    if len(body) > MAX_DOCUMENT_CHARACTERS:
        message = (
            f"{source} served {len(body)} characters, and this collector decodes at most "
            f"{MAX_DOCUMENT_CHARACTERS}. A package document is kilobytes to a few mebibytes, so a document this "
            f"size is a source doing something else -- and parsing it would spend a worker's soft time limit "
            f"finding out (CPM-AD-9)."
        )
        raise CondaDocumentError(message)
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError, TypeError) as unreadable:
        # Four rather than one, and each is a way `json.loads` fails that would
        # otherwise escape `translate` as something other than a refusal about
        # this source: it recurses per level of nesting, so a deeply nested body
        # raises `RecursionError`; a body that reached here as bytes raises
        # `UnicodeDecodeError` for an undecodable one and `TypeError` for a value
        # that is not a string at all. An uncaught one names this module's own
        # stack rather than the source that caused it.
        message = (
            f"{source} did not serve a readable document: {type(unreadable).__name__}: {unreadable}. The "
            f"observation is refused rather than recorded empty, which would say this channel publishes nothing "
            f"(CPM-FR-10)."
        )
        raise CondaDocumentError(message) from unreadable
    if not isinstance(document, dict):
        message = (
            f"{source} served {type(document).__name__} rather than an object. A source whose shape has changed "
            f"is refused rather than read for whatever still parses."
        )
        raise CondaDocumentError(message)
    return document


def _optional_string(mapping: dict[str, object], *, field: str, source: str) -> str:
    """Return a field that may be absent or null, stripped, or refuse a mistyped one.

    Args:
        mapping: The decoded object the field sits in.
        field: Which field to read.
        source: The locator, for the message.

    Returns:
        The stripped string, or the empty string when the field is absent or null
        -- both of which mean "the source stated none".

    Raises:
        CondaDocumentError: When the field is present, is not null, and is not a
            string.

    """
    value = mapping.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        message = (
            f"{source} served a document whose {field!r} is {type(value).__name__} rather than a string. A "
            f"source whose shape has changed is refused rather than read past."
        )
        raise CondaDocumentError(message)
    return value.strip()


def _optional_count(mapping: dict[str, object], *, source: str) -> int | None:
    """Return a build number a file states, or `None` where it states none.

    Args:
        mapping: The file's attribute object.
        source: The locator, for the message.

    Returns:
        The build number, or `None` when the field is absent or null.

    Raises:
        CondaDocumentError: When the field is present, is not null, and is not an
            integer -- `bool` refused with the rest, because it is an `int` in
            Python and is not a build number in any document -- when it is
            negative, or when it is above `MAX_BUILD_NUMBER`. The last is the one
            that matters most: the column would refuse it at insert, several
            frames past the `try` `translate` is wrapped in, and on a branch whose
            first call had already established what the row says.

    """
    value = mapping.get(BUILD_NUMBER_FIELD)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        message = (
            f"{source} served a file whose {BUILD_NUMBER_FIELD!r} is {type(value).__name__} rather than an "
            f"integer. A source whose shape has changed is refused rather than read past."
        )
        raise CondaDocumentError(message)
    if value < 0 or value > MAX_BUILD_NUMBER:
        message = (
            f"{source} states a build number of {value}, and the column that records it holds 0 to "
            f"{MAX_BUILD_NUMBER}. The observation is refused rather than clamped: a stored value that is not the "
            f"value the channel published is a comparison that will be wrong for ever."
        )
        raise CondaDocumentError(message)
    return value


def _require_storable(value: str, *, field: str, source: str, what: str) -> None:
    """Refuse a value wider than the column that has to hold it.

    Refused where the value enters rather than where it lands, on the terms
    `collectors/pypi_release.py` states: `max_length` is enforced by PostgreSQL
    and ignored by SQLite, so an over-long value is a stored row on a developer's
    machine and a failed run in the gate (`R-5`).

    Args:
        value: What the document said.
        field: The column it would land in.
        source: The locator, for the message.
        what: What the value is, for the message.

    Raises:
        CondaDocumentError: When it is wider than the column.

    """
    width = _column_width(field)
    if width is not None and len(value) > width:
        message = (
            f"{source} names a {what} of {len(value)} characters, and the column that holds it takes {width}. "
            f"The observation is refused rather than truncated: a stored value that is not the value the channel "
            f"published is a comparison that will be wrong for ever."
        )
        raise CondaDocumentError(message)


def _column_width(field: str) -> int | None:
    """Return how wide one of the evidence table's text columns is.

    Read off the model rather than restated, so the bound a value is refused
    against is the bound the table actually enforces.

    Args:
        field: The column's name.

    Returns:
        Its `max_length`, or `None` for a column that declares none.

    """
    column = CondaPackageSnapshot._meta.get_field(field)  # noqa: SLF001 - Django's own public-by-convention API
    return column.max_length if isinstance(column, models.CharField) else None


class CondaPackageCollector(Collector):
    """The collector that observes what each monitored channel publishes. Writes `conda_package_snapshots`.

    Four hooks and nine declarations. See the module docstring for why one
    collection produces several rows, why the channels are configuration that
    ships empty, and why the first channel's call is the base's while the rest are
    bounded calls made from `translate`.
    """

    #: The nine declarations the base checks at construction, every one written
    #: out on the terms `SourceReleaseCollector` gives.
    name: ClassVar[str] = COLLECTOR_NAME

    evidence_model: ClassVar[type[AppendOnlyModel] | None] = CondaPackageSnapshot

    observation_window: ClassVar[timedelta | None] = CONDA_PACKAGE_OBSERVATION_WINDOW

    timeout: ClassVar[float | None] = CONDA_PACKAGE_TIMEOUT

    retries: ClassVar[int] = CONDA_PACKAGE_RETRIES

    rate_limit: ClassVar[RateLimit] = CONDA_PACKAGE_RATE_LIMIT

    headers: ClassVar[Mapping[str, str]] = CONDA_PACKAGE_HEADERS

    freshness_target: ClassVar[timedelta | None] = CONDA_PACKAGE_FRESHNESS_TARGET

    response_cache_ttl: ClassVar[timedelta | None] = CONDA_PACKAGE_CACHE_TTL

    #: How often the full-inventory sweep dispatches this collector
    #: (`CPM-CURRENCY-S05`). Bound to the module constant the target and the
    #: window are already derived from, so no number moves; what changes is that
    #: `config/startup/stage_two.py` now reconciles it against this collector's
    #: `CELERY_BEAT_SCHEDULE` entry at boot.
    cadence: ClassVar[timedelta | None] = CONDA_PACKAGE_CADENCE

    #: What this run is about, remembered on the instance between the hooks, on
    #: the terms `FeedstockCollector._identity` states: the base asks one hook
    #: after another about one package in one run and they must agree, and reading
    #: the declaration twice would be a second chance for the two to disagree
    #: across a settings change. Forgotten at the start of every run by
    #: `inapplicability`, so an instance that collects twice reads fresh each
    #: time.
    #:
    #: `_monitored` is the checked declaration, `_package_name` the package's
    #: canonical name and `_locator` the locator `source_for` answered with --
    #: which `sentinel_evidence` records and is not handed
    #: (`SourceReleaseCollector`'s reason). All three are empty on an instance no
    #: run has reached.
    _monitored: Monitored = NOTHING_MONITORED
    _package_name: str = ""
    _locator: str = ""

    @classmethod
    def selectable_packages(cls) -> Iterable[int]:
        """Return the packages this collector can be asked about: every one, or none at all.

        The complement of `source_for`'s refusals, and that complement has two
        shapes rather than one.

        **When channels and platforms are declared it is the whole inventory.**
        "Is it published on this channel" applies to every package -- "it is not
        there" is the observation `CPM-FR-10` asks for rather than a reason not to
        look, which is why `inapplicability` never answers a reason and
        `sentinel_evidence` refuses `not_applicable` outright. Nothing this
        collector reads from `identity` can make a package unaskable: it needs a
        canonical name, and every package row has one
        (`canonical_name_is_present`).

        **When they are not, it is nothing, and that is the whole point.** Both
        settings ship empty (PRD Open Question 4), and an empty or unusable
        declaration refuses every package equally -- so a selection that offered
        the inventory anyway would have a scheduled sweep write one `failed`
        collection per package per day, for ever, out of the box. That is the
        "ledger fills with failed runs" shape the other three selections exist to
        prevent, reached by a different route, and it is reached from the shipped
        settings rather than from any mistake an operator made. So an undeclared
        component selects nothing, the dispatch records one `succeeded` row saying
        the selection was empty, and the component says the same thing once a day
        instead of ten thousand times. `docs/deployment.md` tells an operator that
        this is what an undeclared component looks like.

        The check is `declaration_fault` -- the collector's own rule, the one
        `collectors/apps.py` refuses an unusable *shape* with -- so the selection
        and the run-time read cannot come to disagree about what "declared" means.

        Returns:
            Every package's primary key, as a lazy queryset ordered by key --
            streamed by `collectors/sweep.py` rather than materialised -- or an
            empty queryset when no usable channel and platform pair is declared.
            This is the collector `CPM-NFR-1`'s ten thousand is measured against,
            because it is the one that selects all of them.

        """
        declared = (
            getattr(settings, CHANNELS_SETTING, ()),
            getattr(settings, PLATFORMS_SETTING, ()),
        )
        settings_names = (CHANNELS_SETTING, PLATFORMS_SETTING)
        unusable = any(
            declaration_fault(value, setting=name) or not value
            for value, name in zip(declared, settings_names, strict=True)
        )
        if unusable:
            return Package.objects.none().values_list("pk", flat=True)
        return Package.objects.order_by("pk").values_list("pk", flat=True)

    def inapplicability(self, *, package_id: int) -> str:
        """Say why this question does not apply to a package, which here is never.

        **The question applies to every package**, and that is a statement about
        the surface rather than an omission: any package at all may or may not be
        published on a monitored channel, and "it is not there" is the observation
        `CPM-FR-10` asks for rather than a reason not to look. There is no
        identity mapping to consult and no `not_applicable` row shape --
        `sentinel_evidence` refuses that state outright.

        What the override is for is the other half of the hook's position: it is
        the first thing the base calls on every run, which makes it the one place
        a run's remembered declaration can be forgotten before the next one reads
        it.

        Args:
            package_id: The package being collected, by the integer primary key
                `CPM-AD-3` fixes. Read by no branch here: nothing about a package
                can make a published-artifact question inapplicable.

        Returns:
            The empty string, always.

        """
        # A new run: forget the last one's declaration, name and locator, so
        # none is answered from a package this instance collected before -- or
        # from a declaration an operator has since changed.
        self._monitored = NOTHING_MONITORED
        self._package_name = ""
        self._locator = ""
        return ""

    def source_for(self, *, package_id: int) -> str:
        """Return the first monitored channel's locator, and remember what the run is about.

        The declaration is read here, once, and at *run* time -- so a channel
        added by an operator takes effect on the next collection rather than at
        the next process restart, and so a run that finds nothing declared fails
        naming the setting rather than observing an empty set of surfaces
        silently.

        Args:
            package_id: The package being collected.

        Returns:
            `package_locator(first channel, canonical name)`. The remaining
            channels are asked from `translate`, so that this collection is one
            call per channel and no more.

        Raises:
            CondaChannelError: On every refusal `monitored` makes -- an empty,
                mistyped, blank, duplicated, separator-carrying or over-long
                declaration, and one naming more channels than a collection may
                ask about -- and when the package's canonical name is not a
                segment a channel could serve it under. See that class for why it
                escapes rather than becoming an evidence row.

        """
        self._monitored = monitored(
            getattr(settings, CHANNELS_SETTING, ()),
            getattr(settings, PLATFORMS_SETTING, ()),
        )
        # `core/ledger.py` refuses a package_id naming no package before the
        # opening ledger row is written (`CPM-EVIDENCE-S09`), so the row exists by
        # the time a hook runs -- unless it went between the two, which is a
        # narrow race and not one this collector may answer with a bare
        # `DoesNotExist` out of `collect()`. Re-raised as this module's own
        # refusal, naming the package, on the terms the sibling collectors refuse
        # an identity they cannot read.
        try:
            self._package_name = Package.objects.values_list("canonical_name", flat=True).get(pk=package_id)
        except Package.DoesNotExist as gone:
            message = (
                f"package {package_id} has no row, so this collector has no name to ask a channel about. The "
                f"run ledger checks the key before it opens a row (CPM-EVIDENCE-S09), so a package that is "
                f"absent here went between that check and this read."
            )
            raise CondaChannelError(message) from gone
        self._locator = package_locator(self._monitored.channels[0], self._package_name)
        return self._locator

    def translate(self, payload: Payload, *, package_id: int, observed_at: datetime) -> Sequence[AppendOnlyModel]:
        """Turn the first channel's answer, plus one bounded call per remaining channel, into a row per pair.

        **The first per-package collector in this repository to return more than
        one row.** `_write_evidence` has always taken a sequence; this is the
        story that needed it, because one collection observes several surfaces and
        AC 1 forbids folding them into one row.

        Args:
            payload: What the *first* monitored channel said, recorded. Reached
                only for a call the source answered -- absence and failure of that
                one call are the base's to record.
            package_id: The package the observation is about.
            observed_at: The instant to stamp every row with, from the injected
                clock. The base refuses a row stamped with anything else.

        Returns:
            One unsaved `CondaPackageSnapshot` per monitored `(channel, platform)`
            pair, in declared order.

        Raises:
            CondaDocumentError: When the *first* channel's document cannot be read
                as what it claims to be. The base writes an `error` row and
                re-raises. A later channel's cannot escape -- see
                `_channel_instead`.

        """
        # `source_for` always runs before `translate` on the base's per-package
        # path and a locator is answered only for a declaration `monitored`
        # accepted, so both tuples are non-empty by the time this is reached.
        facts = list(
            channel_facts(
                payload.body,
                channel=self._monitored.channels[0],
                platforms=self._monitored.platforms,
                source=payload.source,
            ),
        )
        for channel in self._monitored.channels[1:]:
            facts.extend(self._channel_instead(channel=channel, platforms=self._monitored.platforms))
        return [self._row_for(fact, package_id=package_id, observed_at=observed_at) for fact in facts]

    def _channel_instead(self, *, channel: str, platforms: Sequence[str]) -> tuple[ChannelFact, ...]:
        """Ask one further channel what it publishes, and never let its failure cost another channel's answer.

        **One of this collector's bounded calls**, and it is bounded two ways: it
        is one locator, and no way of failing raises. The second is the invariant
        rather than an omission -- `CPM-FR-15`'s partial success on the
        per-package path *is* this method returning rows that say "this channel
        could not be read" beside rows another channel earned, and an exception
        escaping here would discard every one of them. It is *not* bounded by
        being un-retried: the transport's retry policy is mounted on the session,
        so this call is retried exactly like the one the base makes, which is what
        `MAX_MONITORED_CHANNELS` exists to bound.

        The base's allowance was charged once, before the first call, so this
        request is not counted against it -- a `deferred` entry on
        `CPM-CURRENCY-S04`. Neither is it a conditional request: it carries no
        cached validator and remembers nothing, so channels after the first
        re-transfer their document on every run, which is a second `deferred`
        entry on the same story.

        Args:
            channel: The channel to ask.
            platforms: The conda subdirs it is asked about.

        Returns:
            One fact per platform: what the channel published, that it publishes
            nothing, or that this run could not find out -- which are three
            different claims and never one.

        """
        try:
            locator = package_locator(channel, self._package_name)
        except CondaChannelError as unnameable:
            return _unread(
                channel=channel,
                platforms=platforms,
                source="",
                state=OutcomeState.ERROR,
                detail=f"{UNREAD_CHANNEL_DETAIL}: {unnameable}",
            )
        try:
            payload = self._transport.fetch(locator, headers=request_headers(declared=self._headers, entry=None))
        except Exception as failure:  # noqa: BLE001 - see below
            # Caught this widely and deliberately, on the terms the base catches
            # around `translate`: nothing is swallowed -- the reason becomes the
            # row's own `detail` -- and the guarantee being defended does not
            # depend on which way a substituted transport, a socket library or a
            # DNS resolver breaks. A narrower `except TransportError` would let
            # anything else discard every answering channel's rows, and from the
            # sentinel path would replace the reason the run is recording.
            return _unread(
                channel=channel,
                platforms=platforms,
                source=locator,
                state=OutcomeState.ERROR,
                detail=f"{UNREAD_CHANNEL_DETAIL}: {locator} could not be read: {type(failure).__name__}: {failure}",
            )
        if payload.not_modified:
            # This request carried no validator, so a `304` is the source
            # answering a question nobody asked and there is no body behind it.
            # Left to fall through it would read as a document that is not JSON,
            # which is a refusal describing the wrong problem.
            return _unread(
                channel=channel,
                platforms=platforms,
                source=locator,
                state=OutcomeState.ERROR,
                detail=(
                    f"{UNREAD_CHANNEL_DETAIL}: {locator} answered that nothing had changed, to an unconditional request"
                ),
            )
        if not payload.found:
            # The channel's *own* answer, which is why this is `not_found` rather
            # than `error`: it said the package is not there, which is the
            # observation `CPM-FR-10` asks for and not a failure to look.
            return _unread(
                channel=channel,
                platforms=platforms,
                source=locator,
                state=OutcomeState.NOT_FOUND,
                detail=f"{locator} reports that this channel does not serve the package at all",
            )
        try:
            return channel_facts(payload.body, channel=channel, platforms=platforms, source=locator)
        except Exception as unreadable:  # noqa: BLE001 - as above
            # Inside the `try` deliberately, and as widely. Raised, it would leave
            # `translate`, and the base would write one `error` row over answers
            # the channels before it had already given -- exactly what this method
            # exists not to do.
            return _unread(
                channel=channel,
                platforms=platforms,
                source=locator,
                state=OutcomeState.ERROR,
                detail=f"{UNREAD_CHANNEL_DETAIL}: {type(unreadable).__name__}: {unreadable}",
            )

    def sentinel_evidence(
        self,
        *,
        state: OutcomeState,
        package_id: int,
        observed_at: datetime,
        detail: str,
    ) -> AppendOnlyModel:
        """Return one row carrying the sentinel the base decided on, for the pair its call was about.

        Every published fact is absent: a sentinel row is written for a call that
        produced no document. What the row does carry is the pair it is about --
        the first monitored channel and the first monitored platform, which is
        what the base's one call was about -- because
        `conda_package_names_channel_and_platform` requires it of every row and
        because a row that could not name a pair would be an observation of
        nowhere.

        **This shapes one row; `sentinel_evidence_rows` decides how many there
        are.** The base calls the plural hook, and this collector overrides it,
        so on the base's own sentinel paths this method is reached only through
        that override -- for the first monitored pair. It stays the single-row
        shaper the base's contract requires, and it makes no call of its own.

        Args:
            state: `OutcomeState.ERROR` or `OutcomeState.NOT_FOUND`, decided by
                the base.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with.
            detail: What happened, in words worth storing beside the state.

        Returns:
            One unsaved `CondaPackageSnapshot` carrying the state's value verbatim
            in `state` (`CPM-AD-24`).

        Raises:
            CollectorConfigurationError: When asked for a state this collector has
                no row shape for -- `ok`, `unknown`, or `not_applicable`. The
                first two on the terms every sibling refuses them; the third
                because this collector's `inapplicability` never answers a reason,
                so the base never asks for it, and a row carrying it would name a
                channel nobody asked about.

        """
        self._require_shapeable(state)
        channel, platform = self._asked_pair()
        return self._sentinel_row(
            state=state,
            package_id=package_id,
            observed_at=observed_at,
            detail=detail,
            channel=channel,
            platform=platform,
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
        """Return one row per monitored pair, asking the channels the base's own call never reached.

        **This is what makes AC 1 hold on the paths the base decides.** The base's
        one call is the first declared channel's, and its `404` or its failure
        ends the collection before `translate` runs -- so without this hook a
        package absent from channel one would record nothing whatever about
        channel two, which is "each monitored channel produces its own
        observation" failing outright.

        **A `not_found` asks the remaining channels; an `error` does not, and the
        difference is the ledger row.**

        - `not_found` means the first channel *answered*, and answered "no such
          package". The allowance was granted, one call was made, and the base
          finalizes the run `succeeded` -- so the remaining channels are asked
          exactly as `translate` would have asked them, and every pair gets the
          row it earns. A channel that publishes the package is recorded as `ok`
          beside the first channel's absence.
        - `error` means the run has already been declared `failed` before this is
          reached (`_failed` calls `run.failed()` first), and it is reachable
          from a *refused allowance* as well as from a failed call. Issuing calls
          here would spend the remote budget the limiter has just refused
          (`CPM-AD-20`) and would write `ok` rows underneath a ledger row that
          says the run failed. So every pair gets an `error` row carrying the
          base's own reason, and nothing is asked.

        **Nothing here raises**, which is the same invariant `_channel_instead`
        carries and matters more here: this runs on a path that is already
        recording a failure, where an exception would replace the reason being
        recorded.

        Args:
            state: The sentinel the base decided on.
            package_id: The package the observation is about.
            observed_at: The instant to stamp every row with.
            detail: What happened, in words worth storing beside the state.

        Returns:
            One unsaved `CondaPackageSnapshot` per monitored `(channel,
            platform)` pair, in declared order.

        Raises:
            CollectorConfigurationError: When no declaration is remembered -- see
                `_asked_pair`. It is the one thing this hook refuses rather than
                records, because there is no pair for a row to be about and a
                blank one is refused by the table itself.

                It deliberately refuses no *state*. `sentinel_evidence` does, and
                is the hook a caller reaching this collector directly meets; this
                one is called from paths that are already recording a failure,
                where a raise would replace the reason being recorded, so it
                shapes a row for whatever it is handed and leaves the base's own
                checks -- the state carried verbatim, and no determinate row under
                a failed run -- to be what stands behind it.

        """
        first, _ = self._asked_pair()
        rows = [
            self._sentinel_row(
                state=state,
                package_id=package_id,
                observed_at=observed_at,
                detail=detail,
                channel=first,
                platform=platform,
                source=self._locator,
            )
            for platform in self._monitored.platforms
        ]
        for channel in self._monitored.channels[1:]:
            facts = (
                self._channel_instead(channel=channel, platforms=self._monitored.platforms)
                if state is OutcomeState.NOT_FOUND
                else _unread(
                    channel=channel,
                    platforms=self._monitored.platforms,
                    source="",
                    state=OutcomeState.ERROR,
                    detail=detail,
                )
            )
            rows.extend(self._row_for(fact, package_id=package_id, observed_at=observed_at) for fact in facts)
        return rows

    def _require_shapeable(self, state: OutcomeState) -> None:
        """Refuse a sentinel state this collector has no row shape for.

        Asked by `sentinel_evidence` and deliberately **not** by
        `sentinel_evidence_rows`: the plural hook is the one the base calls, on
        paths that are already recording a failure, and a raise from it would
        replace the reason being recorded. What stands behind the plural hook
        instead is the base's own pair of checks -- the state carried verbatim,
        and no determinate row written under a failed run.

        Args:
            state: The state the caller asked for.

        Raises:
            CollectorConfigurationError: For `ok`, `unknown` and
                `not_applicable`. Refused at the call rather than at the insert,
                which is where a row carrying `ok` and no published version would
                land -- several frames from the call that was wrong.

        """
        # Written as two comparisons rather than as membership of a declared set,
        # for the reason `SourceReleaseCollector.sentinel_evidence` gives:
        # `tests/unit/django_apps/test_single_ordering_audit.py` reads a literal
        # holding two `OutcomeState` members outside `core/outcomes.py` as a
        # second precedence order, and it is right to.
        if state is not OutcomeState.ERROR and state is not OutcomeState.NOT_FOUND:
            message = (
                f"{type(self).__name__}.sentinel_evidence was asked for {state.value!r}, and this collector "
                f"shapes a sentinel row for {OutcomeState.ERROR.value!r} and {OutcomeState.NOT_FOUND.value!r} "
                f"only. A published-artifact question applies to every package, so there is no "
                f"{OutcomeState.NOT_APPLICABLE.value!r} row to write -- and a row carrying any other state "
                f"would name no channel and would be refused by conda_package_snapshots' own constraints at "
                f"insert."
            )
            raise CollectorConfigurationError(message)

    def _sentinel_row(  # noqa: PLR0913 - one parameter per column a sentinel row carries
        self,
        *,
        state: OutcomeState,
        package_id: int,
        observed_at: datetime,
        detail: str,
        channel: str,
        platform: str,
        source: str,
    ) -> CondaPackageSnapshot:
        """Return one sentinel row about one pair.

        Args:
            state: The state the row carries, verbatim (`CPM-AD-24`).
            package_id: The package the observation is about.
            observed_at: The instant to stamp it with.
            detail: What happened.
            channel: The channel the row is about.
            platform: The conda subdir the row is about.
            source: The locator it is about, blank where none was built.

        Returns:
            The unsaved row, with every published fact absent.

        """
        return CondaPackageSnapshot(
            observed_at=observed_at,
            package_id=package_id,
            source=source,
            state=state.value,
            channel=channel,
            platform=platform,
            published_version="",
            build_string="",
            build_number=None,
            detail=detail,
            trace_id=current_trace_id(),
        )

    def _row_for(self, fact: ChannelFact, *, package_id: int, observed_at: datetime) -> CondaPackageSnapshot:
        """Return the evidence row one fact earns.

        The one place a `ChannelFact` becomes a row, so `translate` and
        `sentinel_evidence_rows` cannot come to disagree about which column a fact
        lands in.

        Args:
            fact: What one channel said about one platform.
            package_id: The package the observation is about.
            observed_at: The instant to stamp it with.

        Returns:
            The unsaved row.

        """
        return CondaPackageSnapshot(
            observed_at=observed_at,
            package_id=package_id,
            trace_id=current_trace_id(),
            source=fact.source,
            state=fact.state.value,
            channel=fact.channel,
            platform=fact.platform,
            published_version=fact.published_version,
            build_string=fact.build_string,
            build_number=fact.build_number,
            detail=fact.detail,
        )

    def _asked_pair(self) -> tuple[str, str]:
        """Return the channel and platform the base's one call was about.

        Returns:
            The first monitored channel and the first monitored platform.

        Raises:
            CollectorConfigurationError: When no declaration is remembered, or
                one half of it is empty. Refused rather than answered with
                blanks: a blank pair is a row
                `conda_package_names_channel_and_platform` refuses at insert, and
                on the base's `not_found` branch that write is not wrapped -- so
                the `IntegrityError` would escape raw and replace the reason the
                run was recording. Unreachable through `collect()`, where
                `source_for` refuses an empty declaration before the base gets
                anywhere near a sentinel.

        """
        if not self._monitored.channels or not self._monitored.platforms:
            message = (
                f"{type(self).__name__} was asked for a sentinel row before {CHANNELS_SETTING} and "
                f"{PLATFORMS_SETTING} were read, so there is no (channel, platform) pair for the row to be "
                f"about. Every row in conda_package_snapshots names one, and a blank pair is refused by the "
                f"table itself -- several frames from the call that was wrong."
            )
            raise CollectorConfigurationError(message)
        return self._monitored.channels[0], self._monitored.platforms[0]
