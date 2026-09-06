"""Where PyPI says a Python package's latest release is, observed and recorded.

`CPM-FR-8`: obtain "project existence, latest version and date, and
`Requires-Python` metadata", record `not_found` for a package with no PyPI
presence, record `not_applicable` for a non-Python package, and never mark a
package stale against PyPI merely for not being published there. This module is
that collector.

**It is the second collector on the per-package path, and the first whose
question does not apply to every package.** `CPM-CURRENCY-S01`'s source
collector asks about a repository any package may have; this one asks about a
release ecosystem only Python packages have. So it is the first to implement the
base's `inapplicability` hook: before any locator is built, it reads what
resolution recorded about the package's release ecosystem and says whether the
question is about this package at all. When it is not, the base writes the
`not_applicable` row itself -- no call, no allowance, no cache -- and the run
succeeds carrying the reason.

**Applicability is read from identity and never guessed.** `CPM-FR-1` says "a
package whose type makes a mapping inapplicable records `not_applicable` for that
mapping", so resolution has already answered the question this collector would
otherwise have to infer -- and inferring "Python" from a name is the guess
`CPM-FR-1` forbids. The rule is therefore mechanical: a package is asked about
on PyPI only when its `release_ecosystem` mapping is `established` with
`primary_type == "pypi"`, and the project name comes from `primary_purl`, never
from `canonical_name`. A mapping recorded `not_applicable`, or established for
some other ecosystem, is the `not_applicable` row. A mapping that is `unknown`,
`not_found` or `error` -- or absent -- cannot be turned into a PyPI question
either, and is *refused* (run `failed`, no row) on the terms `SourceLocatorError`
set in `CPM-CURRENCY-S01`: the selection that offers only askable packages is
`CPM-CURRENCY-S05`'s.

**One document answers every fact, and one call reads it.** `GET
https://pypi.org/pypi/<name>/json` carries `info.version` (PyPI's own "latest"),
`info.requires_python` (the specifier), and `releases[<version>]` (the files
that version was uploaded as, each dated). A project that does not exist -- or
that exists and has never released -- is a `404`, which is AC 2's `not_found`
and is unambiguous here: PyPI is a public index with no private projects for an
unauthenticated reader to be shut out of, so the row carries no caveat.

**`info.version` is Warehouse's own "latest", under Warehouse's own rules, and
this collector applies none of its own.** PyPI decides which version it reports
there -- how pre-releases rank, what a yanked release does to the answer -- and
this collector records that value as the source states it, trimmed of
surrounding whitespace and otherwise exactly as spelled (`CPM-AD-8`: comparing
versions is a policy pass, and choosing a "latest" by a rule of this module's
would be one). It dates the version from that version's files regardless of any
file's `yanked` flag, for the same reason: whether a yanked upload should date a
release is a question about what "latest" ought to mean for a comparison, and
it is recorded as deferred rather than answered here.

**`released_at` is the earliest usable upload instant of the latest version's
files** -- the moment the version became installable. A version whose files
carry no usable instant is still `ok` (the version is a fact PyPI stated) and
dates nothing, with `detail` saying so.

**The project name is PEP 503-normalised before it reaches the locator.** PyPI
treats `Zope.Interface`, `zope_interface` and `zope-interface` as one project,
and every key built from the result -- the cache entry, the row's `source`, the
ledger's locator -- is exact. A purl carries a version, qualifiers and a subpath
this collector does not want (the question is "what is latest", not "what is
this version"), so they are dropped; a purl carrying a namespace, or a name that
is not a valid project name once normalised, is refused rather than repaired.

**Two of the three hooks reduce to module functions, and that is deliberate.**
`project_name`, `project_locator` and `pypi_facts` take data and return data,
reachable with no database, no socket and no clock (`CPM-AD-27`).

**The document is large, and the bound is a refusal to be surprised by the
decode.** The project document lists every file of every release the project
ever published; for a large project that runs to several mebibytes. By the time
this module sees a body the transport has already transferred and decoded it to
a string, so the bound saves neither the transfer nor the memory of holding it
-- what it refuses is handing `json.loads` a document an order of magnitude past
the largest honest one, which is where a worker's soft time limit would be spent
(`CPM-AD-9`). The ceiling is set well above real documents so it is never the
reason an honest one is refused.

**The `error`, `not_found` and `not_applicable` rows the base writes go through
`sentinel_evidence`, and this module invents none of them.** The base decides
which sentinel and that there is always one (`CPM-NFR-3`); this module decides
what a row in `pypi_release_snapshots` looks like, and refuses a state it has no
row shape for.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final
from urllib.parse import unquote

from django.db import models

from conda_package_supply_chain_monitor.collectors.agent import USER_AGENT
from conda_package_supply_chain_monitor.collectors.models import PyPIReleaseSnapshot
from conda_package_supply_chain_monitor.core.clock import is_aware
from conda_package_supply_chain_monitor.core.collection import Collector
from conda_package_supply_chain_monitor.core.collection import CollectorConfigurationError
from conda_package_supply_chain_monitor.core.ledger import current_trace_id
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.rate_limit import RateLimit
from conda_package_supply_chain_monitor.core.transport import DEFAULT_RETRIES
from conda_package_supply_chain_monitor.identity.models import ESTABLISHED
from conda_package_supply_chain_monitor.identity.models import MappingKind
from conda_package_supply_chain_monitor.identity.models import PackageMapping

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
    from conda_package_supply_chain_monitor.core.transport import Payload

__all__ = [
    "COLLECTOR_NAME",
    "INFO_FIELD",
    "MAX_DOCUMENT_CHARACTERS",
    "NO_RELEASE_DETAIL",
    "PURL_SCHEME",
    "PURL_TYPE",
    "PYPI_HOST",
    "PYPI_RELEASE_CACHE_TTL",
    "PYPI_RELEASE_CADENCE",
    "PYPI_RELEASE_FRESHNESS_TARGET",
    "PYPI_RELEASE_HEADERS",
    "PYPI_RELEASE_OBSERVATION_WINDOW",
    "PYPI_RELEASE_RATE_LIMIT",
    "PYPI_RELEASE_RETRIES",
    "PYPI_RELEASE_TIMEOUT",
    "RELEASES_FIELD",
    "REQUIRES_PYTHON_FIELD",
    "TOLERATED_MISSED_RUNS",
    "UNDATED_VERSION_DETAIL",
    "UPLOAD_TIME_FIELD",
    "VERSION_FIELD",
    "PyPIDocumentError",
    "PyPIFacts",
    "PyPILocatorError",
    "PyPIReleaseCollector",
    "ReleaseIdentity",
    "asks_about",
    "inapplicability_of",
    "project_locator",
    "project_name",
    "pypi_facts",
]

#: What this collector is called, on its ledger rows, in its cache keys and in
#: the registry `config/startup/stage_two.py` sweeps. It is the `collect` half of
#: its task name too, which is what routes it (`core/queues.py`).
COLLECTOR_NAME: Final[str] = "pypi_release"

#: How often this collector is meant to run, and the number every other interval
#: below is derived from. `CPM-NFR-2`'s fast end for version currency, on the
#: terms `collectors/source_release.py` gives at length: the cadence is data in
#: `django_celery_beat` (`CPM-AD-20`), this is the number the arithmetic assumes,
#: and `CPM-CURRENCY-S05` reconciles the two.
PYPI_RELEASE_CADENCE: Final[timedelta] = timedelta(days=1)

#: How many consecutive missed collections may pass before this product stops
#: calling an answer current -- PRD Open Question 7's risk posture for the
#: version-currency signal class.
TOLERATED_MISSED_RUNS: Final[int] = 1

#: How long this collector's evidence may be read as current (`CPM-AD-28`):
#: `cadence x (1 + tolerated_missed_runs)`, strictly greater than the cadence so
#: a package does not read stale at exactly the moment its next run is due.
PYPI_RELEASE_FRESHNESS_TARGET: Final[timedelta] = PYPI_RELEASE_CADENCE * (1 + TOLERATED_MISSED_RUNS)

#: How long a successful observation suppresses the next one (`CPM-AD-7`). Half
#: the cadence, so a scheduled run is never suppressed by the previous one and a
#: second run of one package inside one day still is.
PYPI_RELEASE_OBSERVATION_WINDOW: Final[timedelta] = PYPI_RELEASE_CADENCE / 2

#: How many times a failed request is retried, and therefore what the rate
#: limiter is charged against per collection.
PYPI_RELEASE_RETRIES: Final[int] = DEFAULT_RETRIES

#: Seconds any single connect or read phase may take. Five, bounded from above by
#: the inherited Celery soft limit (`CPM-AD-9`) through `core/transport.py`'s
#: `worst_case_call_seconds()`, which `tests/unit/django_apps/test_pypi_release.py`
#: reconciles against the settings module's own declared limit.
PYPI_RELEASE_TIMEOUT: Final[float] = 5.0

#: How hard this collector may push its source (`CPM-AD-20`).
#:
#: PyPI publishes **no numeric ceiling** for its JSON API: its guidance is to send
#: an identifying `User-Agent`, to cache, and to be reasonable. Sixty requests a
#: minute is therefore a declared courtesy bound rather than a number the source
#: stated -- one request a second, which at `1 + retries` per collection is
#: fifteen packages a minute. It is written down so that it is a decision a
#: reader can see and a limit the base enforces, rather than an allowance that
#: is unlimited by omission.
PYPI_RELEASE_RATE_LIMIT: Final[RateLimit] = RateLimit(calls=60, per=timedelta(minutes=1))

#: What this collector's source expects on every request (`CPM-AD-20`,
#: `CPM-AD-27`): declared here, merged and sent by the base, never by this module.
#: `Accept` asks for the JSON representation and the `User-Agent` is the one
#: identity every collector shares (`collectors/agent.py`). Nothing conditional is
#: declared -- the validators are the base's.
PYPI_RELEASE_HEADERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    },
)

#: How long a remembered response may be replayed before it is re-read. A week,
#: so scheduled collections revalidate rather than re-transfer a document that
#: runs to mebibytes for a large project. PyPI serves an `ETag` on this endpoint,
#: which is what makes a `304` reachable at all.
PYPI_RELEASE_CACHE_TTL: Final[timedelta] = timedelta(days=7)

#: The host this collector reads.
PYPI_HOST: Final[str] = "pypi.org"

#: The purl scheme and the one purl type this collector reads. A purl is
#: `pkg:<type>/[<namespace>/]<name>[@<version>][?<qualifiers>][#<subpath>]`, and
#: a PyPI purl has no namespace.
PURL_SCHEME: Final[str] = "pkg:"
PURL_TYPE: Final[str] = "pypi"

#: What a project name looks like once PEP 503 has normalised it: lowercase
#: letters, digits and single hyphens, never starting or ending with one. A name
#: that does not match after normalisation is not a name PyPI could have a
#: project under.
_NORMALISED_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

#: The runs of separators PEP 503 collapses to one hyphen.
_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[-_.]+")

#: How many segments a PyPI purl's path has: the type and the name. A third is a
#: namespace, which PyPI purls do not carry.
_PURL_SEGMENTS: Final[int] = 2

#: The longest document this collector will hand to `json.loads`, in characters.
#:
#: The project document lists every file of every release the project ever
#: published, so for a large, long-lived project it runs to several mebibytes.
#: Thirty-two mebibytes is an order of magnitude above the largest such document.
#: What the bound protects is the decode and nothing earlier: the transport has
#: already transferred the body and decoded it to a string by the time it arrives
#: here, so this is not a guard on memory or bandwidth -- it is a refusal to spend
#: a worker's soft time limit parsing something no honest source serves
#: (`CPM-AD-9`).
MAX_DOCUMENT_CHARACTERS: Final[int] = 32 * 1024 * 1024

#: The fields of the project document this collector reads, named rather than
#: spelled at the call sites so the reader and the cases that build documents
#: cannot drift.
INFO_FIELD: Final[str] = "info"
VERSION_FIELD: Final[str] = "version"
REQUIRES_PYTHON_FIELD: Final[str] = "requires_python"
RELEASES_FIELD: Final[str] = "releases"
UPLOAD_TIME_FIELD: Final[str] = "upload_time_iso_8601"

#: What a row says in its own words, in each of the ways it is reachable. Named
#: so the row a run writes and the case that reads it back cannot drift.
NO_RELEASE_DETAIL: Final[str] = "the project lists no release: its document names no latest version"
UNDATED_VERSION_DETAIL: Final[str] = "the source dated none of the latest version's files with a usable upload time"


class PyPILocatorError(ValueError):
    """A package's release-ecosystem identity cannot be turned into a PyPI locator.

    A `ValueError` subclass, matching `collectors/source_release.py`'s
    `SourceLocatorError` and `core/collection.py`'s `CollectorConfigurationError`:
    every "this input cannot describe what it claims to" in this product is a
    `ValueError`.

    **It escapes `collect()` rather than becoming an evidence row, and that is a
    decision rather than an omission.** `source_for` is called before the window,
    the allowance and the transport, so the run ledger row exists and is finalized
    `failed` carrying this message. What it refuses is a package whose
    release-ecosystem mapping resolution has *not* established -- `unknown`,
    `not_found`, `error`, or no mapping row at all -- or whose purl cannot be read
    as a PyPI project. Neither is `not_applicable`: that state is for a mapping
    resolution *did* reach and found inapplicable, and it goes through the base's
    `inapplicability` hook rather than through here. Turning an unresolved
    mapping into a `not_applicable` observation would record a fact about the
    package that nobody established, which is the guess `CPM-FR-1` forbids.
    The selection that offers only askable packages is `CPM-CURRENCY-S05`'s.
    """


class PyPIDocumentError(ValueError):
    """A project document could not be read as what it claims to be.

    Raised from `translate`, which the base answers by writing an `error` row and
    re-raising unchanged -- so `CPM-NFR-3`'s guarantee holds on this path too:
    never a clean result, and never no row. Refused rather than partially read: a
    document this collector cannot understand is a source whose shape has changed,
    and reading around it would record a latest version chosen from whatever
    happened to still parse, permanently.
    """


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    """What resolution recorded about one package's release ecosystem.

    The one identity read this collector makes, held as a value so the two
    hooks that need it -- `inapplicability` and `source_for` -- read it once and
    agree about what it said.

    Attributes:
        outcome: The `release_ecosystem` mapping's outcome, as `PackageMapping`
            spells it: `established` or one of `core`'s four sentinels.
        primary_type: The purl type resolution recorded as the package's primary
            ecosystem, or blank.
        primary_purl: The package URL resolution recorded, or blank.

    """

    outcome: str
    primary_type: str
    primary_purl: str


@dataclass(frozen=True, slots=True)
class PyPIFacts:
    """What one project document says, as the facts the evidence row holds.

    Attributes:
        state: What the lookup concluded. `ok` for a document naming a latest
            version, `not_found` for one that names none. Never `error` -- a
            document that could not be read raises rather than returning.
        latest_version: The version PyPI reports as latest, trimmed of
            surrounding whitespace and otherwise exactly as spelled. Empty when
            there is none.
        released_at: The earliest usable upload instant of that version's files,
            or `None` when the source dated none of them -- or when there is no
            version.
        requires_python: The `Requires-Python` specifier, trimmed of surrounding
            whitespace and otherwise exactly as spelled, or blank when the
            project declares none.
        detail: Why there is no latest version, or why there is no date for the
            one there is. Empty for an ordinary determinate observation.
        source: The locator this answer came from, recorded on the row.

    """

    state: OutcomeState
    latest_version: str
    released_at: datetime | None
    requires_python: str
    detail: str
    source: str


def project_name(purl: str) -> str:
    """Return the PEP 503-normalised project name a PyPI purl names, or refuse it.

    Pure: no database, no clock, no network. A purl is
    `pkg:pypi/<name>[@<version>][?<qualifiers>][#<subpath>]`; the version, the
    qualifiers and the subpath are dropped, because the question this collector
    asks is "what is latest" and a locator carrying a version would ask a
    different one. The name is percent-decoded -- a purl encodes what a name
    cannot carry raw -- and then normalised as PEP 503 says PyPI itself does, so
    `Zope.Interface`, `zope_interface` and `zope-interface` reach one locator,
    one cache entry and one spelling of `source`.

    Args:
        purl: The package's `primary_purl`, as `identity` stored it.

    Returns:
        The normalised project name.

    Raises:
        PyPILocatorError: When the purl is blank or not a string; does not carry
            the `pkg:` scheme; names a type other than `pypi`; carries a
            namespace; names no project; or names one that is not a valid
            project name once normalised. Refused rather than repaired, because
            a stored purl is data a resolution wrote (`CPM-FR-1`).

    """
    if not isinstance(purl, str) or not purl.strip():
        message = (
            f"a PyPI project cannot be located for primary_purl={purl!r}: this package's release-ecosystem "
            f"identity names no package URL. CPM-FR-8 observes the project a resolution established, and a "
            f"package whose identity names none has nothing for this collector to read (CPM-FR-1)."
        )
        raise PyPILocatorError(message)

    stripped = purl.strip()
    if not stripped.lower().startswith(PURL_SCHEME):
        message = (
            f"{purl!r} does not carry the {PURL_SCHEME!r} scheme, so it is not a package URL. A stored purl is "
            f"data a resolution wrote; one that is not a purl is refused rather than repaired."
        )
        raise PyPILocatorError(message)

    # Subpath, then qualifiers, then version -- each introduced by a character
    # a name cannot carry unencoded, so the first occurrence is the boundary.
    path = stripped[len(PURL_SCHEME) :].lstrip("/")
    path = path.partition("#")[0].partition("?")[0].partition("@")[0]
    segments = [segment for segment in path.split("/") if segment]

    if not segments or segments[0].lower() != PURL_TYPE:
        found = segments[0] if segments else ""
        message = (
            f"{purl!r} names the purl type {found!r}, and this collector reads {PURL_TYPE!r}. A package whose "
            f"primary ecosystem is another type is not asked about on PyPI; resolution records that as the "
            f"mapping's outcome, which is where the base reads it (CPM-FR-1)."
        )
        raise PyPILocatorError(message)
    if len(segments) > _PURL_SEGMENTS:
        message = (
            f"{purl!r} carries a namespace, and a PyPI purl has none: a project is named by one segment, and a "
            f"locator built from more would ask about a project nobody established."
        )
        raise PyPILocatorError(message)
    if len(segments) < _PURL_SEGMENTS:
        message = f"{purl!r} names no project: the purl carries a type and nothing after it."
        raise PyPILocatorError(message)

    name = _SEPARATORS.sub("-", unquote(segments[1])).lower()
    if not _NORMALISED_NAME.match(name):
        message = (
            f"{purl!r} names {name!r} once PEP 503 has normalised it, which is not a name PyPI could hold a "
            f"project under. Refused rather than encoded: a locator built from it would ask about nothing."
        )
        raise PyPILocatorError(message)
    return name


def project_locator(purl: str) -> str:
    """Return the locator naming a PyPI project's JSON document.

    Args:
        purl: The package's `primary_purl`, as `identity` stored it.

    Returns:
        `https://pypi.org/pypi/<name>/json`, with the name normalised.

    Raises:
        PyPILocatorError: On every refusal `project_name` makes, and when the
            locator is wider than the `source` column that has to hold it.
            `Package.primary_purl` is as wide as that column, so a valid purl
            near the width builds a locator PostgreSQL refuses at insert -- after
            the call was spent -- and SQLite stores (`R-5`). Refused here, before
            the window and the allowance, on the terms `_require_storable`
            refuses the two other text columns.

    """
    locator = f"https://{PYPI_HOST}/pypi/{project_name(purl)}/json"
    width = _column_width("source")
    if width is not None and len(locator) > width:
        message = (
            f"{purl!r} builds a locator of {len(locator)} characters, and the source column that records it "
            f"takes {width}. Refused rather than truncated or written unrecorded: a row that cannot say where "
            f"its observation came from is a row an append-only history cannot tell from its neighbours."
        )
        raise PyPILocatorError(message)
    return locator


def pypi_facts(body: str, *, source: str) -> PyPIFacts:
    """Read one project document into the facts the evidence row holds.

    Pure: no database, no clock, no network. See the module docstring for where
    each fact comes from and `PyPIFacts` for what each means.

    **A blank latest version is `not_found` rather than nothing.** PyPI answers
    `404` for a project that has never released, so a `200` whose `info.version`
    is blank is a document this collector did not expect -- but it is an answer,
    and the honest row for "the source named no version" is the informative
    negative, with `detail` saying why.

    **An unusable upload time is missing rather than fatal, and a *mistyped* one
    is neither**, on the terms `collectors/source_release.py` sets: a value of
    the wrong type is the document's shape changing and is refused with the rest
    of the shape checks, while a string this collector cannot read as an aware
    instant simply dates nothing.

    Args:
        body: The document the source served.
        source: The locator it was served from, recorded on the row and named in
            the refusal messages.

    Returns:
        The facts. `state` is `ok` when a latest version was named and
        `not_found` otherwise.

    Raises:
        PyPIDocumentError: When the body is longer than `MAX_DOCUMENT_CHARACTERS`,
            is not JSON, is not an object, has an `info` that is not an object,
            has a `version`, `requires_python`, `releases`, file list, file or
            upload time of the wrong type, or names a version or specifier wider
            than the column that has to hold it.

    """
    document = _document_in(body, source=source)
    info = document.get(INFO_FIELD)
    if not isinstance(info, dict):
        message = (
            f"{source} served a document whose {INFO_FIELD!r} is {type(info).__name__} rather than an object. A "
            f"source whose shape has changed is refused rather than read for whatever still parses."
        )
        raise PyPIDocumentError(message)

    version = _optional_string(info, field=VERSION_FIELD, source=source)
    requires_python = _optional_string(info, field=REQUIRES_PYTHON_FIELD, source=source)
    # The raw spelling is kept for one purpose: `releases` is keyed by whatever
    # `info.version` says, and a version the source padded with whitespace is
    # keyed padded. The row stores the trimmed value.
    spelled = info.get(VERSION_FIELD)
    raw_version = spelled if isinstance(spelled, str) else version
    if not version:
        return PyPIFacts(
            state=OutcomeState.NOT_FOUND,
            latest_version="",
            released_at=None,
            requires_python="",
            detail=NO_RELEASE_DETAIL,
            source=source,
        )

    _require_storable(version, field="latest_version", source=source, what="latest version")
    _require_storable(requires_python, field="requires_python", source=source, what="Requires-Python specifier")
    released_at = _earliest_upload(document, version=version, raw_version=raw_version, source=source)
    return PyPIFacts(
        state=OutcomeState.OK,
        latest_version=version,
        released_at=released_at,
        requires_python=requires_python,
        detail="" if released_at is not None else UNDATED_VERSION_DETAIL,
        source=source,
    )


def _document_in(body: str, *, source: str) -> dict[str, object]:
    """Decode a document and refuse anything that is not an object.

    Args:
        body: The document the source served.
        source: The locator it was served from, for the messages.

    Returns:
        The decoded object.

    Raises:
        PyPIDocumentError: When the body is too long to decode, is not JSON, or
            is not an object.

    """
    if len(body) > MAX_DOCUMENT_CHARACTERS:
        message = (
            f"{source} served {len(body)} characters, and this collector decodes at most "
            f"{MAX_DOCUMENT_CHARACTERS}. The largest project document is an order of magnitude smaller than "
            f"that, so a document this size is a source doing something else -- the body is already in memory, "
            f"and parsing it would spend a worker's soft time limit finding out (CPM-AD-9)."
        )
        raise PyPIDocumentError(message)
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, RecursionError) as unreadable:
        # `RecursionError` beside the decode error deliberately: `json.loads`
        # recurses per level of nesting, and an uncaught one escapes as a crash
        # naming this module's own stack rather than the source that caused it.
        message = (
            f"{source} did not serve a readable project document: {type(unreadable).__name__}: {unreadable}. "
            f"The observation is refused rather than recorded empty, which would say the project publishes "
            f"nothing (CPM-FR-8)."
        )
        raise PyPIDocumentError(message) from unreadable
    if not isinstance(document, dict):
        message = (
            f"{source} served {type(document).__name__} rather than a project object. A source whose shape has "
            f"changed is refused rather than read for whatever still parses."
        )
        raise PyPIDocumentError(message)
    return document


def _optional_string(mapping: dict[str, object], *, field: str, source: str) -> str:
    """Return a field that may be absent or null, stripped, or refuse a mistyped one.

    Args:
        mapping: The decoded object the field sits in.
        field: Which field to read.
        source: The locator, for the message.

    Returns:
        The stripped string, or the empty string when the field is absent or
        null -- both of which PyPI really sends, and both of which mean "the
        project declares none".

    Raises:
        PyPIDocumentError: When the field is present, is not null, and is not a
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
        raise PyPIDocumentError(message)
    return value.strip()


def _require_storable(value: str, *, field: str, source: str, what: str) -> None:
    """Refuse a value wider than the column that has to hold it.

    Refused where the value enters rather than where it lands, on the terms
    `collectors/source_release.py` states: `max_length` is enforced by PostgreSQL
    and ignored by SQLite, so an over-long value is a stored row on a developer's
    machine and a failed run in the gate (`R-5`).

    Args:
        value: What the document said.
        field: The column it would land in.
        source: The locator, for the message.
        what: What the value is, for the message.

    Raises:
        PyPIDocumentError: When it is wider than the column.

    """
    width = _column_width(field)
    if width is not None and len(value) > width:
        message = (
            f"{source} names a {what} of {len(value)} characters, and the column that holds it takes {width}. "
            f"The observation is refused rather than truncated: a stored value that is not the value the source "
            f"published is a comparison that will be wrong for ever."
        )
        raise PyPIDocumentError(message)


def _column_width(field: str) -> int | None:
    """Return how wide one of the evidence table's text columns is.

    Read off the model rather than restated, so the bound a value is refused
    against is the bound the table actually enforces.

    Args:
        field: The column's name.

    Returns:
        Its `max_length`, or `None` for a column that declares none.

    """
    column = PyPIReleaseSnapshot._meta.get_field(field)  # noqa: SLF001 - Django's own public-by-convention API
    return column.max_length if isinstance(column, models.CharField) else None


def _earliest_upload(
    document: dict[str, object],
    *,
    version: str,
    raw_version: str,
    source: str,
) -> datetime | None:
    """Return when the latest version became installable, or `None` when the source dated nothing.

    Every file of the version is read, whatever its `yanked` flag says -- see the
    module docstring for why that is a deferred question rather than a rule here.

    Args:
        document: The decoded project document.
        version: The latest version, trimmed, whose files are read.
        raw_version: The version as `info.version` spelled it. `releases` is
            keyed by that spelling, so a padded version is looked up padded when
            the trimmed key finds nothing.
        source: The locator, for the messages.

    Returns:
        The earliest usable upload instant among that version's files, or `None`
        when the version lists no files, or lists none with a usable instant.

    Raises:
        PyPIDocumentError: When `releases` is present and is not an object, when
            the version's entry is present and is not a list, when a file is not
            an object, or when a file's upload time is present and is neither a
            string nor null.

    """
    releases = document.get(RELEASES_FIELD)
    if releases is None:
        return None
    if not isinstance(releases, dict):
        message = (
            f"{source} served a document whose {RELEASES_FIELD!r} is {type(releases).__name__} rather than an "
            f"object. A source whose shape has changed is refused rather than read past."
        )
        raise PyPIDocumentError(message)
    files = releases.get(version)
    if files is None and raw_version != version:
        files = releases.get(raw_version)
    if files is None:
        return None
    if not isinstance(files, list):
        message = (
            f"{source} lists {type(files).__name__} for version {version!r} rather than a list of files. A "
            f"source whose shape has changed is refused rather than read past."
        )
        raise PyPIDocumentError(message)

    instants: list[datetime] = []
    for position, entry in enumerate(files):
        if not isinstance(entry, dict):
            message = f"{source} lists {type(entry).__name__} at position {position} of {version!r} rather than a file."
            raise PyPIDocumentError(message)
        uploaded = _optional_string(entry, field=UPLOAD_TIME_FIELD, source=source)
        instant = _instant(uploaded)
        if instant is not None:
            instants.append(instant)
    return min(instants) if instants else None


def _instant(value: str) -> datetime | None:
    """Return an aware instant a source stated, or `None` where it stated none.

    Args:
        value: What a file carried for its upload time, already known to be a
            string.

    Returns:
        The parsed instant, or `None` when the value is blank, does not parse,
        or parses to a naive one. A naive value is discarded rather than assumed
        to be UTC (`CPM-AD-26`).

    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if is_aware(parsed) else None


def asks_about(identity: ReleaseIdentity) -> bool:
    """Report whether this collector asks PyPI about a package with this identity.

    The one spelling of the rule: the `release_ecosystem` mapping is
    `established` and the primary type is `pypi`, compared case-insensitively
    because purl types are. `inapplicability_of` and `source_for` both read it,
    so the hook can never say "applies" while `source_for` refuses the same
    identity on the same check.

    Args:
        identity: What resolution recorded.

    Returns:
        True for an established PyPI identity.

    """
    return identity.outcome == ESTABLISHED and identity.primary_type.lower() == PURL_TYPE


def inapplicability_of(identity: ReleaseIdentity) -> str:
    """Return why PyPI is not a question about this package, or nothing when it is -- or might be.

    Pure: the whole of the applicability rule, over what resolution recorded and
    nothing else, so every branch of it is reachable with no database
    (`CPM-AD-27`). `PyPIReleaseCollector.inapplicability` reads the identity and
    hands it here.

    Args:
        identity: What resolution recorded.

    Returns:
        The reason when the mapping was recorded `not_applicable`, or was
        established for a *named* ecosystem other than PyPI. The empty string
        otherwise -- for an established PyPI identity; for an unresolved one,
        because "resolution has not decided" is not "does not apply"; and for a
        mapping established with a blank primary type, which is an inconsistent
        identity row rather than a fact about the package. All three of those
        are `source_for`'s to answer, and only the first is answered with a
        locator.

    """
    if identity.outcome == OutcomeState.NOT_APPLICABLE.value:
        return (
            f"resolution recorded this package's release-ecosystem identity as {identity.outcome!r}: the "
            f"package's type gives it no release ecosystem PyPI could be asked about (CPM-FR-1, CPM-FR-8)."
        )
    if identity.outcome == ESTABLISHED and identity.primary_type and not asks_about(identity):
        return (
            f"resolution established this package's primary release ecosystem as {identity.primary_type!r}, not "
            f"{PURL_TYPE!r}: PyPI is not where it is released, so the question does not apply (CPM-FR-8)."
        )
    return ""


class PyPIReleaseCollector(Collector):
    """The collector that observes a Python package's PyPI project. Writes `pypi_release_snapshots`.

    Four methods and nine declarations. See the module docstring for what the
    base owns, how applicability is decided from identity, and why an unresolved
    identity is refused rather than recorded.
    """

    #: The nine declarations the base checks at construction, every one written
    #: out on the terms `SourceReleaseCollector` gives.
    name: ClassVar[str] = COLLECTOR_NAME

    evidence_model: ClassVar[type[AppendOnlyModel] | None] = PyPIReleaseSnapshot

    observation_window: ClassVar[timedelta | None] = PYPI_RELEASE_OBSERVATION_WINDOW

    timeout: ClassVar[float | None] = PYPI_RELEASE_TIMEOUT

    retries: ClassVar[int] = PYPI_RELEASE_RETRIES

    rate_limit: ClassVar[RateLimit] = PYPI_RELEASE_RATE_LIMIT

    headers: ClassVar[Mapping[str, str]] = PYPI_RELEASE_HEADERS

    freshness_target: ClassVar[timedelta | None] = PYPI_RELEASE_FRESHNESS_TARGET

    response_cache_ttl: ClassVar[timedelta | None] = PYPI_RELEASE_CACHE_TTL

    #: The one identity read, remembered on the instance for the run in progress.
    #: The base asks `inapplicability` and then `source_for` about one package in
    #: one run, and both need the same answer; reading it twice would be a second
    #: query on every collection and a window in which the two could disagree.
    #: It is forgotten at the start of every run -- `inapplicability` is the first
    #: hook the base asks, and it clears both fields before reading -- so an
    #: instance that collects the same package twice reads identity fresh each
    #: time rather than answering the second run from the first. Keyed by package
    #: as well, so a caller reaching `source_for` directly for another package
    #: reads afresh rather than being answered about the last.
    _identity: ReleaseIdentity | None = None
    _identity_package: int | None = None

    #: The locator this run asked for, remembered when `source_for` answered, for
    #: the reason `SourceReleaseCollector._locator` gives: `sentinel_evidence`
    #: records it and is not handed it. Blank on the `not_applicable` path,
    #: because no locator was ever built -- and reset when a new question is
    #: asked, so a row on that path never carries the previous package's.
    _locator: str = ""

    def inapplicability(self, *, package_id: int) -> str:
        """Say whether PyPI is a question about this package, from what resolution recorded.

        Args:
            package_id: The package being collected, by the integer primary key
                `CPM-AD-3` fixes.

        Returns:
            The reason the question does not apply -- a `release_ecosystem`
            mapping recorded `not_applicable`, or established for another
            ecosystem -- or the empty string when it applies or when resolution
            has not decided, in which case `source_for` refuses.

        """
        # A new run: forget the last one's locator and identity, so neither is
        # answered from a package this instance collected before -- or from this
        # package as it was before a resolution changed it.
        self._locator = ""
        self._identity = None
        self._identity_package = None
        identity = self._release_identity(package_id)
        return "" if identity is None else inapplicability_of(identity)

    def source_for(self, *, package_id: int) -> str:
        """Return the locator this collector reads for one package.

        Args:
            package_id: The package being collected.

        Returns:
            The project's JSON locator. Remembered on the instance as well as
            returned -- see `_locator`.

        Raises:
            PyPILocatorError: When the package's release-ecosystem mapping is not
                `established` for PyPI -- including a mapping that is
                `not_applicable`, which the base never reaches here because
                `inapplicability` answers first -- or when its purl cannot be
                read as a PyPI project. See that class for why this escapes
                rather than becoming an evidence row.

        """
        identity = self._release_identity(package_id)
        if identity is None:
            message = (
                f"package {package_id} has no release_ecosystem mapping row, so resolution has recorded nothing "
                f"about where it is released. CPM-FR-8 observes the project a resolution established "
                f"(CPM-IDENTITY-S02), and a package nobody has resolved is refused rather than guessed at "
                f"(CPM-FR-1)."
            )
            raise PyPILocatorError(message)
        if not asks_about(identity):
            message = (
                f"package {package_id}'s release_ecosystem mapping is {identity.outcome!r} with "
                f"primary_type={identity.primary_type!r}, and this collector asks about a package only when the "
                f"mapping is {ESTABLISHED!r} for {PURL_TYPE!r}. An unresolved mapping is refused rather than "
                f"recorded as an observation nobody made (CPM-FR-1); the selection that offers only askable "
                f"packages is CPM-CURRENCY-S05's."
            )
            raise PyPILocatorError(message)
        self._locator = project_locator(identity.primary_purl)
        return self._locator

    def translate(self, payload: Payload, *, package_id: int, observed_at: datetime) -> Sequence[AppendOnlyModel]:
        """Turn one project document into the one row it is worth.

        One row and never none: the base reads an empty translation as a parser
        that no longer matches its source.

        Args:
            payload: What the source said, recorded. Reached only for a call the
                source answered -- absence and failure are the base's to record.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with, from the injected
                clock. The base refuses a row stamped with anything else.

        Returns:
            One unsaved `PyPIReleaseSnapshot`.

        Raises:
            PyPIDocumentError: When the document cannot be read as a project.
                The base writes an `error` row and re-raises.

        """
        facts = pypi_facts(payload.body, source=payload.source)
        return [
            PyPIReleaseSnapshot(
                observed_at=observed_at,
                package_id=package_id,
                source=facts.source,
                state=facts.state.value,
                latest_version=facts.latest_version,
                released_at=facts.released_at,
                requires_python=facts.requires_python,
                detail=facts.detail,
                trace_id=current_trace_id(),
            ),
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

        Every observed fact is absent: a sentinel row is written for a call that
        produced no document, or for a question that was never asked. A
        `not_found` row carries no caveat -- PyPI is public, and a `404` means
        what it says.

        Args:
            state: `OutcomeState.ERROR`, `OutcomeState.NOT_FOUND` or
                `OutcomeState.NOT_APPLICABLE`, decided by the base.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with.
            detail: What happened, in words worth storing beside the state.

        Returns:
            One unsaved `PyPIReleaseSnapshot` carrying the state's value verbatim
            in `state` (`CPM-AD-24`).

        Raises:
            CollectorConfigurationError: When asked for a state this collector has
                no row shape for -- `ok` or `unknown`. The alternative failure is
                worse than a refusal: a row carrying `ok` and no version is
                refused by the table's own constraint at insert, several frames
                from the call that was wrong.

        """
        # Written as three comparisons rather than as membership of a declared
        # set, for the reason `SourceReleaseCollector.sentinel_evidence` gives:
        # `tests/unit/django_apps/test_single_ordering_audit.py` reads a literal
        # holding two or more `OutcomeState` members outside `core/outcomes.py`
        # as a second precedence order, and it is right to.
        if (
            state is not OutcomeState.ERROR
            and state is not OutcomeState.NOT_FOUND
            and state is not OutcomeState.NOT_APPLICABLE
        ):
            message = (
                f"{type(self).__name__}.sentinel_evidence was asked for {state.value!r}, and this collector "
                f"shapes a sentinel row for {OutcomeState.ERROR.value!r}, {OutcomeState.NOT_FOUND.value!r} and "
                f"{OutcomeState.NOT_APPLICABLE.value!r} only. A row carrying any other state would have no "
                f"version and would be refused by pypi_release_snapshots' own constraint at insert."
            )
            raise CollectorConfigurationError(message)
        return PyPIReleaseSnapshot(
            observed_at=observed_at,
            package_id=package_id,
            source=self._locator,
            state=state.value,
            latest_version="",
            released_at=None,
            requires_python="",
            detail=detail,
            trace_id=current_trace_id(),
        )

    def _release_identity(self, package_id: int) -> ReleaseIdentity | None:
        """Return what resolution recorded about this package's release ecosystem.

        The one database read in this module, and it reads `identity` -- the only
        application a collector may read (`CPM-AD-7`). One query, joining the
        mapping row to the columns it owns (`MAPPED_FIELDS`), and only those
        columns: the row's other fields are none of this collector's business.

        Args:
            package_id: The package being collected.

        Returns:
            The identity, or `None` when no `release_ecosystem` mapping row
            exists for the package -- which is also what a package with no
            identity row at all produces, and the two are refused together.

        """
        if self._identity_package != package_id:
            recorded = (
                PackageMapping.objects.filter(package_id=package_id, kind=MappingKind.RELEASE_ECOSYSTEM.value)
                .values_list("outcome", "package__primary_type", "package__primary_purl")
                .first()
            )
            self._identity = None if recorded is None else ReleaseIdentity(*recorded)
            self._identity_package = package_id
        return self._identity
