"""What a package's published metadata claims about Python 3.14, and never what a build did.

`CPM-FR-14` splits Python 3.14 readiness into a cheap static pass and an expensive
verification pass, and the whole purpose of `CPM-EP-PY314` is that the two stay
distinguishable. This module is the cheap pass, the ninth collector this component
runs: it says where verification is worth spending, and it must never be mistaken
for verification.

**A metadata silence is not a claim of incompatibility.** This is the single
property `CPM-PY314-S01` turns on, and every branch below is arranged around it.
Metadata that **admits** 3.14 records an inferred-compatible value; metadata that
**excludes** it records an inferred-incompatible one; metadata that says nothing
either way records `unknown`. Most projects have not declared 3.14 support, so
reading the third case as the second would report most of an inventory as
incompatible on no evidence at all -- and would send `CPM-PY314-S02`'s expensive
verification exactly where it is least warranted, which is the opposite of what this
collector exists to do.

**The determinate values name the inference.** Not `ok`, which is the lesson
`CPM-SECURITY-S01` was patched for; and not a bare `compatible`, because
`CPM-FR-14` requires inferred and verified compatibility to be *distinct recorded
states* and `CPM-AD-24` carries a state's value verbatim onto every read surface --
so a value called `compatible` would appear on a queue beside `CPM-PY314-S02`'s
verified result and read identically. `collectors/outcomes.py` composes the
vocabulary and argues both halves at length.

**`not_applicable` is recorded only where identity established it, and that is the
second absence trap.** The applicability signal is the `release_ecosystem` mapping
outcome in `identity`, whose vocabulary is `core`'s four sentinels plus
`established`:

- the mapping is `established` -- the package has a release ecosystem and the
  question applies;
- the mapping is `not_applicable` -- resolution established that the package's type
  gives it no release ecosystem, and **that is the only path** to a
  `not_applicable` row here;
- the mapping is `unknown`, `error` or `not_found`, or there is no mapping row at
  all -- identity established **nothing**, so the compatibility question is
  *unanswered* rather than *inapplicable*.

A package identity has not resolved yet is not a package without a Python
ecosystem, and reading the one as the other is the defect class found in every
story of the preceding epic.

**Deciding whether a specifier admits 3.14 is a containment question, not a
version comparison.** `CPM-SECURITY-S06` established that no architecture decision
in this product owns version ordering, and none is cited here.
`collectors/specifiers.py` holds the whole of the decision: a `Requires-Python`
value is a bounded grammar over numeric release segments, the series being assessed
is the half-open interval `[3.14, 3.15)`, and "does this specifier admit that
series" is whether the two sets intersect. A shape that cannot be answered that way
records `unknown` with the reason and the specifier preserved -- never
`inferred_incompatible`, and never a guess. That is `CPM-PY314-S01`'s Block If.

**Two static signals, and their disagreement is recorded rather than resolved.**
`info.requires_python` is a range and `info.classifiers` may name the series
outright. A classifier list is positive-only, so its silence excludes nothing -- but
a project whose specifier admits 3.14 while its classifiers enumerate Python
versions without naming it has said two different things about somebody's package,
and this collector records that as the `unknown` it is rather than picking a winner.

**The source is read directly, and never another collector's evidence table.**
`collectors/pypi_release.py` reads the same host for a different fact and already
stores a `requires_python` specifier, which would have been quicker to read.
`CPM-AD-7` forbids it -- the exemption list holds exactly one entry, for a collector
whose question is inherently about another's rows, and this one's is not -- so this
collector asks the same *source* independently, on the terms
`collectors/license.py` reads the channel it shares with `collectors/conda_package.py`.
It is necessary rather than merely principled: the **classifiers** are the second
static signal and no collector stores them, so an independent read is required
whatever the sharing rule said.

**No verification, no build, no import, no subprocess.** All four are
`CPM-PY314-S02`, on the `verify` queue, on demand. And no derived status of any
kind: whether a package is *ready* is `CPM-FR-19`'s policy (`CPM-PY314-S03`), which
reads this table and writes its own (`CPM-AD-8`, `CPM-AD-21`).

**Which packages are asked, and the one shape this collector inherits rather than
invents.** The selection is `collectors/pypi_release.py`'s: a `release_ecosystem`
mapping recorded `established` for PyPI **with a PyPI purl beside it**, or recorded
`not_applicable`. Those are the packages this collector has something to say about --
the first is a project to read and the second is AC 2's row, written with no call
made. Everything else is a package whose identity names no project to ask about, and
`CPM-FR-1` forbids guessing one from a name; `source_for` refuses it rather than
recording an observation nobody made, and `PythonReadinessIdentityError` says in as
many words that the question is unanswered rather than inapplicable. The purl is part
of the selection rather than only of the refusal because `identity` permits the type
and the purl to disagree -- see `selectable_packages`.

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
from urllib.parse import unquote

import structlog
from django.db import models

from conda_sentinel.collectors.agent import USER_AGENT
from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.outcomes import INFERRED_COMPATIBLE
from conda_sentinel.collectors.outcomes import INFERRED_INCOMPATIBLE
from conda_sentinel.collectors.outcomes import READINESS_UNKNOWN
from conda_sentinel.collectors.specifiers import ADMITS
from conda_sentinel.collectors.specifiers import EXCLUDES
from conda_sentinel.collectors.specifiers import DecidingSignal
from conda_sentinel.collectors.specifiers import Series
from conda_sentinel.collectors.specifiers import admits_series
from conda_sentinel.collectors.specifiers import classifier_for
from conda_sentinel.collectors.specifiers import declares_version_classifiers
from conda_sentinel.collectors.specifiers import series_of
from conda_sentinel.core.collection import Collector
from conda_sentinel.core.collection import CollectorConfigurationError
from conda_sentinel.core.ledger import current_trace_id
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.rate_limit import RateLimit
from conda_sentinel.core.transport import DEFAULT_RETRIES
from conda_sentinel.identity.models import ESTABLISHED
from conda_sentinel.identity.models import MappingKind
from conda_sentinel.identity.models import PackageMapping

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Mapping
    from collections.abc import Sequence
    from datetime import datetime

    from conda_sentinel.core.models import AppendOnlyModel
    from conda_sentinel.core.transport import Payload

__all__ = [
    "ABSENT_FROM_INDEX_DETAIL",
    "CLASSIFIERS_FIELD",
    "COLLECTOR_NAME",
    "DISAGREEMENT_DETAIL",
    "IDENTITY_UNRESOLVED_DETAIL",
    "INFO_FIELD",
    "MAX_CLASSIFIERS",
    "MAX_DOCUMENT_CHARACTERS",
    "MAX_SENTINEL_DETAIL_CHARACTERS",
    "NOTHING_DECLARED_DETAIL",
    "NO_CLASSIFIER_FOR_SERIES_DETAIL",
    "OVERSIZE_SPECIFIER_DETAIL",
    "PURL_SCHEME",
    "PURL_TYPE",
    "PYPI_HOST",
    "PYPI_PURL_PREFIX",
    "PYTHON_SERIES",
    "READINESS_CACHE_TTL",
    "READINESS_CADENCE",
    "READINESS_DISPATCH_OFFSET",
    "READINESS_FRESHNESS_TARGET",
    "READINESS_HEADERS",
    "READINESS_OBSERVATION_WINDOW",
    "READINESS_RATE_LIMIT",
    "READINESS_RETRIES",
    "READINESS_TIMEOUT",
    "REQUIRES_PYTHON_FIELD",
    "SHORTENED_DETAIL",
    "TOLERATED_MISSED_RUNS",
    "UNREADABLE_SPECIFIER_DETAIL",
    "UNREADABLE_SPECIFIER_EVENT",
    "Assessment",
    "DeclaredMetadata",
    "PythonReadinessAssessmentError",
    "PythonReadinessCollector",
    "PythonReadinessDocumentError",
    "PythonReadinessIdentityError",
    "ReleaseIdentity",
    "asks_about",
    "assess",
    "declared_metadata",
    "inapplicability_of",
    "project_locator",
    "project_name",
]

logger = structlog.get_logger(__name__)

#: What this collector is called, on its ledger rows, in its cache keys and in the
#: registry `config/startup/stage_two.py` sweeps. It is the `collect` half of its
#: task name too, which is what routes it (`core/queues.py`).
COLLECTOR_NAME: Final[str] = "python_readiness"

#: The Python series this collector assesses, and the one value in this module a
#: later story is expected to change.
#:
#: A tuple rather than the string, because `collectors/specifiers.py` answers a
#: containment question over numeric release segments and a string would have to be
#: split at every call site. `series_of` spells it for a column, a locator or a
#: message, and `python_readiness_assessments.python_series` records it on **every**
#: row -- so a later assessment of a later Python is a different row rather than an
#: ambiguous one.
PYTHON_SERIES: Final[Series] = (3, 14)

#: How often this collector is meant to run, and the number every other interval
#: below is derived from.
#:
#: **Weekly, and the reason is what the answer is made of.** `CPM-NFR-2` fixes
#: cadence per signal class and names only the *verification* half of `CPM-FR-14`
#: ("on demand"), so the static pass takes the cadence its evidence justifies: what
#: this collector reads is a project's declared metadata, which changes when the
#: project publishes a release and at no other time. The daily collectors already
#: watch for those releases; asking every project's document every day for a value
#: that moves a few times a year would be a second daily sweep of the whole
#: inventory against `pypi.org` bought for nothing. The cadence itself is data in
#: `django_celery_beat` (`CPM-AD-20`); this is the number the arithmetic below
#: assumes, and `CPM-CURRENCY-S05` reconciles the two at start-up, in both
#: directions, from `collectors/apps.py`'s `ready()`.
READINESS_CADENCE: Final[timedelta] = timedelta(days=7)

#: How long after its tick the readiness dispatch is asked to run.
#:
#: **Three entries in this schedule now carry a phase, and no two of them share
#: one.** The KEV offset exists because a KEV run reads what the vulnerability run
#: wrote; the licence offset exists because two collectors read one host on one
#: tick. This one exists because a weekly sweep of the whole inventory against
#: `pypi.org` and `CPM-CURRENCY-S02`'s daily sweep of the same host would otherwise
#: begin at the same instant one day in seven, each spending its own allowance
#: against one source -- the limiter's counter is keyed by collector, so two
#: collectors reading one host are two allowances rather than one shared bound.
#:
#: Three hours, deliberately neither of the other two: entries sharing a phase fire
#: together and the offset buys nothing. The reconciliation `CPM-CURRENCY-S05` owns
#: compares a beat entry's `schedule` with its collector's declared cadence, so the
#: *interval* cannot carry a phase and a crontab cannot be read as an interval; the
#: entry's `options` can. `config/settings/base.py` carries it and
#: `tests/unit/test_settings.py` reconciles the two.
READINESS_DISPATCH_OFFSET: Final[timedelta] = timedelta(hours=3)

#: How many consecutive missed collections may pass before this product stops
#: calling an answer current. PRD Open Question 7 fixes this per *signal class*, and
#: one is the posture every scheduled surface in this component takes.
TOLERATED_MISSED_RUNS: Final[int] = 1

#: How long this collector's evidence may be read as current (`CPM-AD-28`):
#: `cadence x (1 + tolerated_missed_runs)`. Strictly greater than the cadence, so a
#: package does not read stale at exactly the moment its next run is due -- PRD Open
#: Question 7a's rule, and the reason it exists.
READINESS_FRESHNESS_TARGET: Final[timedelta] = READINESS_CADENCE * (1 + TOLERATED_MISSED_RUNS)

#: How long a successful observation suppresses the next one (`CPM-AD-7`). Half the
#: cadence, so a scheduled run is never suppressed by the previous one and a second
#: run of one package inside half a week still is.
READINESS_OBSERVATION_WINDOW: Final[timedelta] = READINESS_CADENCE / 2

#: How many times a failed request is retried, and therefore what the rate limiter
#: is charged against per collection. The shared default: one call per collection,
#: on the terms `collectors/pypi_release.py` takes it against the same host.
READINESS_RETRIES: Final[int] = DEFAULT_RETRIES

#: Seconds any single connect or read phase may take. Five, bounded from above by
#: the inherited Celery soft limit (`CPM-AD-9`) through `core/transport.py`'s
#: `worst_case_call_seconds()`, which
#: `tests/unit/django_apps/test_python_readiness.py` reconciles against the settings
#: module's own declared limit.
READINESS_TIMEOUT: Final[float] = 5.0

#: How hard this collector may push its source (`CPM-AD-20`).
#:
#: PyPI publishes **no numeric ceiling** for its JSON API: its guidance is to send
#: an identifying `User-Agent`, to cache, and to be reasonable. Sixty a minute is
#: therefore a declared courtesy bound rather than a number the source stated -- one
#: request a second, which at the `1 + retries` the base charges is fifteen packages
#: a minute. It is charged **separately** from `CPM-CURRENCY-S02`'s allowance
#: against the same host: `CPM-AD-20` puts rate limiting in the shared base rather
#: than in each collector and says nothing about how an allowance is scoped, and
#: `core/rate_limit.py` keys the counter by *collector*, so two collectors reading
#: one host spend two allowances. That is a property of the shipped limiter rather
#: than a decision this module may cite an `AD-` for; `docs/conda-sentinel/operations.md` says so
#: to an operator, and `READINESS_DISPATCH_OFFSET` is what keeps the two sweeps from
#: starting at one instant.
READINESS_RATE_LIMIT: Final[RateLimit] = RateLimit(calls=60, per=timedelta(minutes=1))

#: What this collector's source expects on every request (`CPM-AD-20`,
#: `CPM-AD-27`): declared here, merged and sent by the base, never by this module.
#: `Accept` asks for the JSON representation `declared_metadata` reads and the
#: `User-Agent` is the one identity every collector shares
#: (`collectors/agent.py`). Nothing conditional is declared -- the validators are
#: the base's.
READINESS_HEADERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    },
)

#: How long a remembered response may be replayed before it is re-read.
#:
#: Thirty days, and it is deliberately longer than the cadence rather than equal to
#: it: an entry that expired *inside* the cadence would make the cache inert, so
#: every weekly collection would re-transfer a document that lists every file of
#: every release the project ever published. PyPI serves an `ETag` on this endpoint,
#: which is what makes a `304` reachable at all, and a `304` is an observation --
#: the base replays the remembered body through `translate` and the row is written
#: exactly as a `200`'s would be (`CPM-AD-5`, `R-01`).
#:
#: **A remembered assessment is not the remembered security answer `CPM-NFR-3` is
#: written about.** The two security collectors declare `NO_CACHE` because a
#: replayed advisory answer is a claim about exploitation that has moved on; what is
#: replayed here is metadata a *published release* declared, and the cache is
#: conditional -- a project that published a new release answers with the new
#: document.
READINESS_CACHE_TTL: Final[timedelta] = timedelta(days=30)

#: The host this collector reads.
#:
#: **Restated rather than imported**, on the terms `collectors/license.py` restates
#: `CPM-CURRENCY-S04`'s channel setting: no collector imports another (`CPM-AD-7`),
#: and one that did would be a collector whose locators changed when a different
#: story edited its neighbour. `tests/unit/django_apps/test_python_readiness.py`
#: reconciles this module's spelling of the host, the purl grammar and the document
#: bound against `collectors/pypi_release.py`'s, because restating them is right
#: under `CPM-AD-7` and nothing else would have compared them.
PYPI_HOST: Final[str] = "pypi.org"

#: The purl scheme and the one purl type this collector reads. A purl is
#: `pkg:<type>/[<namespace>/]<name>[@<version>][?<qualifiers>][#<subpath>]`, and
#: a PyPI purl has no namespace.
PURL_SCHEME: Final[str] = "pkg:"
PURL_TYPE: Final[str] = "pypi"

#: What a PyPI purl starts with, composed from the two above so no third spelling
#: exists. `selectable_packages` filters on it, because identity permits an
#: `established` mapping to record `primary_type='pypi'` beside a blank or
#: non-PyPI `primary_purl` and a selection that read only the type would offer a
#: package `source_for` then refuses -- see that method.
PYPI_PURL_PREFIX: Final[str] = f"{PURL_SCHEME}{PURL_TYPE}/"

#: What a project name looks like once PEP 503 has normalised it: lowercase
#: letters, digits and single hyphens, never starting or ending with one.
_NORMALISED_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

#: The runs of separators PEP 503 collapses to one hyphen.
_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[-_.]+")

#: How many segments a PyPI purl's path has: the type and the name. A third is a
#: namespace, which PyPI purls do not carry.
_PURL_SEGMENTS: Final[int] = 2

#: The one character PostgreSQL refuses inside a text value, refused by the driver
#: several frames past the `try` `translate` is wrapped in -- which is why it is
#: refused where the value enters. See `_require_encodable`.
_NUL: Final[str] = "\x00"

#: C0 and C1 control characters and the delete character, for the one place a
#: *substitution* is the answer rather than a refusal. See `_safe_detail`.
_CONTROL_CHARACTERS: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: The UTF-16 surrogate range, for the same place. A lone surrogate decodes out of
#: JSON perfectly well and is refused by psycopg from inside the driver, so a stored
#: value is refused by `_require_encodable` -- which asks whether the value *encodes*
#: rather than matching this pattern, because the encode is the check that cannot be
#: outrun by a character nobody enumerated.
_SURROGATES: Final[re.Pattern[str]] = re.compile(r"[\ud800-\udfff]")

#: The longest document this collector will hand to `json.loads`, in characters.
#:
#: The project document lists every file of every release the project ever
#: published, so for a large, long-lived project it runs to several mebibytes.
#: Thirty-two mebibytes is an order of magnitude above the largest such document.
#: What the bound protects is the decode and nothing earlier: by the time a body
#: arrives here the transport has already transferred it, so what this refuses is
#: handing `json.loads` a document no honest source serves, which is where a
#: worker's soft time limit would be spent (`CPM-AD-9`).
MAX_DOCUMENT_CHARACTERS: Final[int] = 32 * 1024 * 1024

#: How many classifiers this collector will read from one document.
#:
#: PyPI's own classifier list is a few hundred entries long and a project declares a
#: handful; a document naming more than this is a source doing something else, and
#: scanning an unbounded list is a worker's soft time limit spent finding out. The
#: list is refused rather than truncated: a truncated classifier list is a
#: *different* declaration, and reading the first thousand of ten thousand would
#: answer "this project does not name 3.14" from a document that might.
MAX_CLASSIFIERS: Final[int] = 1024

#: The longest reason a *sentinel* row will carry, in characters. A sentinel row is
#: written on a path already recording a failure and `CPM-NFR-3` requires it to be
#: written, so a reason too long, or one carrying a control character, is shortened
#: and cleaned rather than refused, on the terms `collectors/kev.py` states.
MAX_SENTINEL_DETAIL_CHARACTERS: Final[int] = 1024

#: The fields of the project document this collector reads, named rather than
#: spelled at the call sites so the reader and the cases that build documents cannot
#: drift.
INFO_FIELD: Final[str] = "info"
REQUIRES_PYTHON_FIELD: Final[str] = "requires_python"
CLASSIFIERS_FIELD: Final[str] = "classifiers"

#: The event emitted when a specifier is in a shape this product will not answer.
#:
#: **This is how the gap is recorded rather than guessed at.** `CPM-PY314-S01`'s
#: Block If says a specifier shape the containment question cannot answer records
#: `unknown` with the reason *and records the gap*; the row carries the reason for a
#: reviewer and this event carries it for an operator, so a shape that turns out to
#: be common shows up in a log rather than only in a column nobody aggregates.
UNREADABLE_SPECIFIER_EVENT: Final[str] = "python_readiness.unreadable_specifier"

#: What a row says in its own words, in each of the ways it is reachable. Named so
#: the row a run writes and the case that reads it back cannot drift.
NOTHING_DECLARED_DETAIL: Final[str] = (
    "this project declares neither a Requires-Python specifier nor any Python version classifier, so it has said "
    "nothing either way about this Python -- which is the common case and is emphatically not a statement that it "
    "will not run"
)
NO_CLASSIFIER_FOR_SERIES_DETAIL: Final[str] = (
    "this project declares no Requires-Python specifier and enumerates Python versions in its classifiers without "
    "naming this one. A classifier list states what a project claims and never what it denies, so an omission "
    "establishes nothing and is recorded as nothing"
)
DISAGREEMENT_DETAIL: Final[str] = (
    "this project's two static signals disagree about this Python, and the disagreement is recorded rather than "
    "resolved: neither signal is ranked above the other here, and a determinate row would be this collector "
    "picking a winner in a claim about somebody else's package"
)
UNREADABLE_SPECIFIER_DETAIL: Final[str] = (
    "this project declares a Requires-Python specifier in a shape this product will not read as a containment "
    "question, so the specifier is recorded exactly as stated and nothing is inferred from it. An unreadable "
    "claim is not a negative claim"
)
OVERSIZE_SPECIFIER_DETAIL: Final[str] = (
    "this project declares a Requires-Python specifier too wide for the column that records it, so this product "
    "cannot preserve it exactly as stated and will not read it. The row is unknown and carries no specifier: a "
    "determinate verdict resting on a claim the row could not show is an inference with no argument attached, "
    "and truncating the claim would record a different specifier from the one the project published. An "
    "unrecordable claim is not a negative claim"
)
IDENTITY_UNRESOLVED_DETAIL: Final[str] = (
    "identity has established nothing about this package's release ecosystem, so the Python compatibility "
    "question is unanswered rather than inapplicable -- a package nobody has resolved yet is not a package "
    "without a Python ecosystem"
)
ABSENT_FROM_INDEX_DETAIL: Final[str] = (
    "the release ecosystem reports that it does not know this project at all, which is an absence from the index "
    "rather than a project that declared nothing about this Python"
)
SHORTENED_DETAIL: Final[str] = "[shortened by this collector]"


class PythonReadinessIdentityError(ValueError):
    """A package's release-ecosystem identity cannot be turned into a question to ask.

    A `ValueError` subclass, matching `collectors/pypi_release.py`'s
    `PyPILocatorError` and every other "this input cannot describe what it claims to
    be" in this product.

    **It escapes `collect()` rather than becoming an evidence row.** `source_for` is
    called before the window, the allowance and the transport, so the run ledger row
    exists and is finalized `failed` carrying this message, and no evidence row is
    written at all.

    **What it refuses, and the distinction that matters most in this module.** It
    refuses a package whose `release_ecosystem` mapping resolution has *not*
    established -- `unknown`, `error`, `not_found`, or no mapping row at all -- and a
    package whose purl cannot be read as a PyPI project. Every one of those is
    identity having established **nothing**, and the message says so in as many
    words: the compatibility question is *unanswered*, not *inapplicable*. It is
    emphatically **not** `not_applicable`, which is for a mapping resolution *did*
    reach and found inapplicable and which goes through `inapplicability` instead.
    Turning an unresolved mapping into a `not_applicable` observation would record a
    determinate fact about the package that nobody established, which is the guess
    `CPM-FR-1` forbids and the absence trap `CPM-PY314-S01` is written against.

    The selection offers only packages identity can answer for, so a scheduled sweep
    never reaches this class: it is what a *forced* recollection meets, and what a
    package whose mapping changed between the selection and the run meets.
    """


class PythonReadinessDocumentError(ValueError):
    """A project document could not be read as what it claims to be.

    Raised from `translate`, which the base answers by writing an `error` row and
    re-raising unchanged -- so `CPM-NFR-3`'s guarantee holds on this path too: never
    a clean result, and never no row.

    Refused rather than partially read, and the stakes here are this story's whole
    subject: a document this collector cannot understand is a source whose shape has
    changed, and reading around it would record "this project declared nothing"
    for a project that declared something in a shape the reader skipped -- an
    `unknown` row that looks exactly like an honest one.

    **What it refuses is narrow.** A document that carries neither
    `requires_python` nor `classifiers` is *not* refused: that is a project that
    declared nothing, which is the single most common row this table holds. What is
    refused is a document whose shape contradicts itself -- a body that is not JSON
    or not an object, an `info` that is not an object, a `requires_python` that is
    not a string, a `classifiers` that is not a list of strings, a classifier list
    longer than `MAX_CLASSIFIERS`, and a value no database will hold at all.

    **A value merely too wide for one column is not refused here**, and the
    difference is the one `_require_encodable` draws: a NUL byte or a lone surrogate
    makes the document unreadable whatever it was headed for, while a width is a
    question about one column and is answered where that column is filled. An
    over-wide `Requires-Python` records `unknown` (`OVERSIZE_SPECIFIER_DETAIL`), and
    an over-wide classifier is not measured at all, because no classifier a document
    states is ever what `matching_classifier` holds.
    """


class PythonReadinessAssessmentError(ValueError):
    """An assessment was built whose columns do not match the verdict it claims.

    Raised where the value is built rather than at the insert, on the terms
    `collectors/kev.py`'s value objects state: the table's own constraint fires
    inside `bulk_create`, with a message about a column and nothing about the branch
    that produced it.
    """


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    """What resolution recorded about one package's release ecosystem.

    The one identity read this collector makes, held as a value so the two hooks
    that need it -- `inapplicability` and `source_for` -- read it once and agree
    about what it said.

    Restated rather than imported from `collectors/pypi_release.py`, which declares
    a value of the same shape for the same mapping: no collector imports another
    (`CPM-AD-7`), and a unit case reconciles the two spellings so a rename there is
    noticed here rather than silently making this collector ask a different
    question.

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
class DeclaredMetadata:
    """What one project document declares about Python, and nothing else from it.

    Two fields because there are two static signals, and they are kept apart because
    they fail differently and a reviewer reads them as two separate claims.

    Attributes:
        requires_python: The specifier the project declared, exactly as stated and
            stripped only of the whitespace around it. Blank when it declared none,
            which is a silence rather than a range.
        classifiers: Every classifier the project declared, on the same terms: the
            whitespace around each is stripped and nothing inside one is touched.
            Empty when it declared none.

    """

    requires_python: str
    classifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Assessment:
    """What this collector concluded about one package, as the fields the row holds.

    Attributes:
        state: `inferred_compatible`, `inferred_incompatible` or `unknown`. Never
            `ok`, which is not in this vocabulary at all; never `error` or
            `not_found`, which are the base's to decide; and never
            `not_applicable`, which only `inapplicability` reaches.
        requires_python: The specifier the project declared, verbatim, or blank.
            Recorded on every assessment that has one, whatever the state -- it is
            what makes an `inferred_incompatible` row argue-able and an `unknown`
            row reviewable.
        matching_classifier: The classifier naming the assessed series, verbatim, or
            blank where the project declared none.
        deciding_signal: Which declared signal reached the verdict. Set exactly when
            the state is determinate.
        detail: Which silence, which disagreement, or why a specifier was not read.
            Empty for a determinate assessment.

    """

    state: str
    requires_python: str
    matching_classifier: str
    deciding_signal: str
    detail: str

    def __post_init__(self) -> None:
        """Refuse an assessment whose columns do not match the verdict it claims.

        Raises:
            PythonReadinessAssessmentError: When a determinate assessment names no
                deciding signal, or when one that is not determinate names one. The
                same rule `python_readiness_assessments` enforces, applied where the
                value is built. The two transcribed columns are deliberately
                unconstrained: they are permitted on every row, which is what makes
                an `unknown` one reviewable.

        """
        determinate = self.state in {INFERRED_COMPATIBLE, INFERRED_INCOMPATIBLE}
        if determinate != bool(self.deciding_signal):
            message = (
                f"Assessment(state={self.state!r}, deciding_signal={self.deciding_signal!r}) sets the deciding "
                f"signal on a row that is {'not ' if not determinate else ''}determinate. It is present exactly "
                f"on an inferred row: an inference that cannot say what it inferred from is a claim about "
                f"somebody's package with no argument attached, and a signal named under any other state claims a "
                f"decision the run never made."
            )
            raise PythonReadinessAssessmentError(message)


def project_name(purl: str) -> str:
    """Return the PEP 503-normalised project name a PyPI purl names, or refuse it.

    Pure: no database, no clock, no network. A purl is
    `pkg:pypi/<name>[@<version>][?<qualifiers>][#<subpath>]`; the version, the
    qualifiers and the subpath are dropped, because the question this collector asks
    is about the project rather than about one release. The name is percent-decoded
    and then normalised as PEP 503 says PyPI itself does, so `Zope.Interface`,
    `zope_interface` and `zope-interface` reach one locator, one cache entry and one
    spelling of `source`.

    Args:
        purl: The package's `primary_purl`, as `identity` stored it.

    Returns:
        The normalised project name.

    Raises:
        PythonReadinessIdentityError: When the purl is blank or not a string; does
            not carry the `pkg:` scheme; names a type other than `pypi`; carries a
            namespace; names no project; or names one that is not a valid project
            name once normalised. Refused rather than repaired, because a stored
            purl is data a resolution wrote (`CPM-FR-1`).

    """
    if not isinstance(purl, str) or not purl.strip():
        message = (
            f"a PyPI project cannot be located for primary_purl={purl!r}: this package's release-ecosystem "
            f"identity names no package URL, so there is no declared metadata to assess. {IDENTITY_UNRESOLVED_DETAIL}"
        )
        raise PythonReadinessIdentityError(message)

    stripped = purl.strip()
    if not stripped.lower().startswith(PURL_SCHEME):
        message = (
            f"{purl!r} does not carry the {PURL_SCHEME!r} scheme, so it is not a package URL. A stored purl is "
            f"data a resolution wrote; one that is not a purl is refused rather than repaired."
        )
        raise PythonReadinessIdentityError(message)

    # Subpath, then qualifiers, then version -- each introduced by a character a
    # name cannot carry unencoded, so the first occurrence is the boundary.
    path = stripped[len(PURL_SCHEME) :].lstrip("/")
    path = path.partition("#")[0].partition("?")[0].partition("@")[0]
    segments = [segment for segment in path.split("/") if segment]

    if not segments or segments[0].lower() != PURL_TYPE:
        found = segments[0] if segments else ""
        message = (
            f"{purl!r} names the purl type {found!r}, and this collector reads {PURL_TYPE!r}. A package whose "
            f"primary ecosystem is another type has its Python metadata somewhere this collector does not read; "
            f"that is a question this run leaves unanswered rather than one it declares inapplicable (CPM-FR-1)."
        )
        raise PythonReadinessIdentityError(message)
    if len(segments) > _PURL_SEGMENTS:
        message = (
            f"{purl!r} carries a namespace, and a PyPI purl has none: a project is named by one segment, and a "
            f"locator built from more would ask about a project nobody established."
        )
        raise PythonReadinessIdentityError(message)
    if len(segments) < _PURL_SEGMENTS:
        message = f"{purl!r} names no project: the purl carries a type and nothing after it."
        raise PythonReadinessIdentityError(message)

    name = _SEPARATORS.sub("-", unquote(segments[1])).lower()
    if not _NORMALISED_NAME.match(name):
        message = (
            f"{purl!r} names {name!r} once PEP 503 has normalised it, which is not a name PyPI could hold a "
            f"project under. Refused rather than encoded: a locator built from it would ask about nothing."
        )
        raise PythonReadinessIdentityError(message)
    return name


def project_locator(purl: str) -> str:
    """Return the locator naming a PyPI project's JSON document.

    Args:
        purl: The package's `primary_purl`, as `identity` stored it.

    Returns:
        `https://pypi.org/pypi/<name>/json`, with the name normalised.

    Raises:
        PythonReadinessIdentityError: On every refusal `project_name` makes, and
            when the locator is wider than the `source` column that has to hold it.
            `Package.primary_purl` is as wide as that column, so a valid purl near
            the width builds a locator PostgreSQL refuses at insert -- after the call
            was spent -- and SQLite stores (`R-5`). Refused here, before the window
            and the allowance.

    """
    locator = f"https://{PYPI_HOST}/pypi/{project_name(purl)}/json"
    width = _column_width("source")
    if len(locator) > width:
        message = (
            f"{purl!r} builds a locator of {len(locator)} characters, and the source column that records it "
            f"takes {width}. Refused rather than truncated or written unrecorded: a row that cannot say where "
            f"its observation came from is a row an append-only history cannot tell from its neighbours."
        )
        raise PythonReadinessIdentityError(message)
    return locator


def declared_metadata(body: object, *, source: str) -> DeclaredMetadata:
    """Read one project document into the two static signals this collector assesses.

    Pure: no database, no clock, no network. The first of this module's two
    decisions about a document -- what the project *declared* -- kept apart from the
    second, what this product infers from it, because they fail differently and a
    reviewer reads them as two separate claims.

    **Nothing here rewrites a value.** Both signals are stripped of the whitespace
    *around* them, which is a rewrite of the field rather than of what the field
    declares, and neither is touched inside that: a specifier and a classifier are
    recorded character for character between their first and last non-space.

    Args:
        body: The document the source served. Typed as `object` because a `Payload`
            is a value a transport built: a body that is not a string is refused by
            name here rather than raising a `TypeError` from `len()` that names no
            source.
        source: The locator it was served from, for the messages.

    Returns:
        What the project declared. Both fields empty for a project that declared
        neither, which is a document this collector reads perfectly well and the
        commonest row this table holds.

    Raises:
        PythonReadinessDocumentError: When the body is longer than
            `MAX_DOCUMENT_CHARACTERS`, is not JSON, is not an object, has an `info`
            that is not an object, has a `requires_python` that is not a string, has
            a `classifiers` that is not a list of strings, names more classifiers
            than `MAX_CLASSIFIERS`, or states a value no database will hold. A value
            merely wider than one column is **not** refused here -- see `assess`.

    """
    document = _document_in(body, source=source)
    info = document.get(INFO_FIELD)
    if not isinstance(info, dict):
        message = (
            f"{source} served a document whose {INFO_FIELD!r} is {type(info).__name__} rather than an object. A "
            f"source whose shape has changed is refused rather than read for whatever still parses -- reading "
            f"around it would record 'this project declared nothing', which is an honest-looking row this table "
            f"must not manufacture (CPM-FR-14)."
        )
        raise PythonReadinessDocumentError(message)
    specifier = _optional_string(info, field=REQUIRES_PYTHON_FIELD, source=source)
    _require_encodable(specifier, source=source, what="Requires-Python specifier")
    return DeclaredMetadata(requires_python=specifier, classifiers=_classifiers_in(info, source=source))


def _classifiers_in(info: dict[str, object], *, source: str) -> tuple[str, ...]:
    """Read the classifier list a project declared, or refuse a shape that is not one.

    Args:
        info: The document's `info` object, already known to be one.
        source: The locator it was served from, for the messages.

    Returns:
        The classifiers, stripped of the whitespace around them and otherwise exactly
        as stated. Empty when the field is absent or null, both of which mean "this
        project declared none".

    Raises:
        PythonReadinessDocumentError: When the field is present, is not null and is
            not a list; when an entry is not a string; when there are more than
            `MAX_CLASSIFIERS`; or when an entry is one no database will hold. An
            entry wider than `matching_classifier` is **not** refused: the only
            classifier that column ever holds is the one equal to the series marker,
            whose width the series fixes -- see `_require_encodable`.

    """
    stated = info.get(CLASSIFIERS_FIELD)
    if stated is None:
        return ()
    if not isinstance(stated, list):
        message = (
            f"{source} served a document whose {CLASSIFIERS_FIELD!r} is {type(stated).__name__} rather than a "
            f"list. A source whose shape has changed is refused rather than read past."
        )
        raise PythonReadinessDocumentError(message)
    if len(stated) > MAX_CLASSIFIERS:
        message = (
            f"{source} names {len(stated)} classifiers and this collector reads at most {MAX_CLASSIFIERS}. "
            f"Refused rather than truncated: a truncated classifier list is a different declaration, and reading "
            f"part of one would answer 'this project does not name this Python' from a document that might."
        )
        raise PythonReadinessDocumentError(message)
    classifiers: list[str] = []
    for position, entry in enumerate(stated):
        if not isinstance(entry, str):
            message = (
                f"{source} lists {type(entry).__name__} at position {position} of {CLASSIFIERS_FIELD!r} rather "
                f"than a string. A source whose shape has changed is refused rather than read past."
            )
            raise PythonReadinessDocumentError(message)
        # Stripped of the whitespace around it and recorded character for character
        # inside that: PyPI's own classifier list carries no padding, and a project
        # that indented one still declared the classifier it names. What is compared
        # against the series marker and what would be stored are therefore the same
        # string, which is why `DeclaredMetadata.classifiers` says so.
        cleaned = entry.strip()
        _require_encodable(cleaned, source=source, what="classifier")
        classifiers.append(cleaned)
    return tuple(classifiers)


def assess(metadata: DeclaredMetadata, *, series: Series) -> Assessment:  # noqa: PLR0911 - one return per outcome
    """Turn what a project declared into what this collector may claim about one Python series.

    Pure: no database, no clock, no network (`CPM-AD-27`), so every branch of the
    rule is reachable without a socket in sight. This function is the whole of
    `CPM-PY314-S01`'s judgement, and it is arranged so that **no path from an
    absence reaches a determinate value**.

    The rule, in the order the branches are written:

    - A specifier wider than the column that records it records `unknown` with the
      reason and **no specifier**: the row cannot show a claim it had to shorten, and
      a truncated specifier is a different specifier. `CPM-PY314-S01`'s Spec Change
      Log records why this is `unknown` rather than the document refusal an earlier
      shape of the guard made of it.
    - A specifier this product will not read records `unknown` with the reason,
      whatever the classifiers say. An unreadable claim is not a negative claim, and
      it is not a positive one either -- a classifier could not overrule a range
      nobody read.
    - A specifier that **admits** the series, with the matching classifier beside
      it, is `inferred_compatible` on both signals.
    - A specifier that admits it while the project enumerates Python versions and
      omits this one is a **disagreement**, recorded as `unknown`. The classifier's
      silence establishes nothing on its own, but a project that took the trouble to
      list its Pythons and left this one out has said something a reviewer should
      weigh, and resolving it here would be this collector picking a winner.
    - A specifier that admits it while the project declares no version classifiers
      at all is `inferred_compatible` on the specifier: there is no second signal to
      disagree with.
    - A specifier that **excludes** the series while a classifier names it is the
      same disagreement in the other direction, and records `unknown` for the same
      reason.
    - A specifier that excludes it with no classifier naming it is
      `inferred_incompatible` on the specifier -- the one determinate negative this
      collector reaches, and it rests on a range the project itself published.
    - With no specifier at all, a classifier naming the series is
      `inferred_compatible` on the classifier.
    - With no specifier and no classifier for the series, the row is `unknown`, and
      `detail` says which silence it is: a project that enumerated its Pythons
      without this one, or a project that declared nothing whatever. **Neither is
      ever incompatible.**

    Args:
        metadata: What the project declared.
        series: The Python series being assessed.

    Returns:
        The assessment. Determinate values name the inference; every silence is
        `unknown`.

    """
    matching = classifier_for(series)
    classifier = next((stated for stated in metadata.classifiers if stated == matching), "")
    enumerated = declares_version_classifiers(metadata.classifiers)
    if not metadata.requires_python:
        return _inferred_from_classifier(classifier, metadata=metadata, enumerated=enumerated)
    unrecordable = _unrecordable_specifier(metadata.requires_python)
    if unrecordable:
        # The event carries the reason and the specifier's *length* rather than the
        # specifier: the whole finding is that the value is too wide to record, and a
        # log line is not the place to put what a column would not take.
        logger.info(
            UNREADABLE_SPECIFIER_EVENT,
            collector=COLLECTOR_NAME,
            requires_python_characters=len(metadata.requires_python),
            series=series_of(series),
            detail=unrecordable,
        )
        return _undecided(
            metadata,
            classifier=classifier,
            detail=f"{OVERSIZE_SPECIFIER_DETAIL}: {unrecordable}",
            specifier="",
        )
    reading = admits_series(metadata.requires_python, series=series)
    if reading.verdict == ADMITS:
        if classifier:
            return _inferred(metadata, classifier=classifier, state=INFERRED_COMPATIBLE, signal=DecidingSignal.BOTH)
        if enumerated:
            return _undecided(
                metadata,
                classifier="",
                detail=(
                    f"{DISAGREEMENT_DETAIL}: the specifier {metadata.requires_python!r} admits "
                    f"{series_of(series)} and the project's Python version classifiers do not name it"
                ),
            )
        return _inferred(
            metadata,
            classifier="",
            state=INFERRED_COMPATIBLE,
            signal=DecidingSignal.REQUIRES_PYTHON,
        )
    if reading.verdict == EXCLUDES:
        if classifier:
            return _undecided(
                metadata,
                classifier=classifier,
                detail=(
                    f"{DISAGREEMENT_DETAIL}: the specifier {metadata.requires_python!r} cannot admit "
                    f"{series_of(series)} and the project declares {matching!r}"
                ),
            )
        return _inferred(
            metadata,
            classifier="",
            state=INFERRED_INCOMPATIBLE,
            signal=DecidingSignal.REQUIRES_PYTHON,
        )
    logger.info(
        UNREADABLE_SPECIFIER_EVENT,
        collector=COLLECTOR_NAME,
        requires_python=metadata.requires_python,
        series=series_of(series),
        detail=reading.reason,
    )
    return _undecided(metadata, classifier=classifier, detail=f"{UNREADABLE_SPECIFIER_DETAIL}: {reading.reason}")


def _inferred_from_classifier(classifier: str, *, metadata: DeclaredMetadata, enumerated: bool) -> Assessment:
    """Return what a project that declared no specifier earns, from its classifiers alone.

    Args:
        classifier: The classifier naming the assessed series, or blank.
        metadata: What the project declared.
        enumerated: Whether it named any Python version at all.

    Returns:
        A determinate assessment when a classifier names the series, and otherwise
        the `unknown` whose `detail` says which of the two silences it is.

    """
    if classifier:
        return _inferred(metadata, classifier=classifier, state=INFERRED_COMPATIBLE, signal=DecidingSignal.CLASSIFIER)
    return _undecided(
        metadata,
        classifier="",
        detail=NO_CLASSIFIER_FOR_SERIES_DETAIL if enumerated else NOTHING_DECLARED_DETAIL,
    )


def _inferred(
    metadata: DeclaredMetadata,
    *,
    classifier: str,
    state: str,
    signal: DecidingSignal,
) -> Assessment:
    """Return a determinate assessment, carrying the signal that reached it.

    Args:
        metadata: What the project declared, so the specifier is recorded verbatim.
        classifier: The classifier naming the assessed series, or blank.
        state: `inferred_compatible` or `inferred_incompatible`.
        signal: Which declared signal decided it.

    Returns:
        The assessment, with no `detail`: the columns say the whole of it.

    """
    return Assessment(
        state=state,
        requires_python=metadata.requires_python,
        matching_classifier=classifier,
        deciding_signal=signal.value,
        detail="",
    )


def _undecided(
    metadata: DeclaredMetadata,
    *,
    classifier: str,
    detail: str,
    specifier: str | None = None,
) -> Assessment:
    """Return the `unknown` a silence, a disagreement or a specifier not read earns.

    Never `inferred_incompatible`: every one of them is an absence of a claim rather
    than a negative claim, and recording it as one would report most of an inventory
    as incompatible on no evidence -- the defect `CPM-PY314-S01` exists to prevent.

    Args:
        metadata: What the project declared, so the specifier survives on the row.
        classifier: The classifier naming the assessed series, or blank.
        detail: Which of them this is.
        specifier: What to record in `requires_python`, when it is not what the
            project declared. Blank on the one path where the declared specifier is
            wider than the column that records it, which is the only reason this
            override exists: the row cannot say "the project declared this" about a
            value it had to shorten, so it says nothing there and `detail` says why.

    Returns:
        An `unknown` assessment carrying no deciding signal.

    """
    return Assessment(
        state=READINESS_UNKNOWN,
        requires_python=metadata.requires_python if specifier is None else specifier,
        matching_classifier=classifier,
        deciding_signal="",
        detail=detail,
    )


def asks_about(identity: ReleaseIdentity) -> bool:
    """Report whether this collector reads PyPI about a package with this identity.

    The one spelling of the rule: the `release_ecosystem` mapping is `established`
    and the primary type is `pypi`, compared case-insensitively because purl types
    are. `selectable_packages` and `source_for` both rest on it, so a selection can
    never offer a package `source_for` then refuses **on this check**.

    **It is not the whole of what `source_for` demands, and saying so is the point.**
    Passing here only means the mapping named this ecosystem; the locator is built
    from `primary_purl`, which identity permits to be blank or to name another
    ecosystem beside a `pypi` type. `selectable_packages` therefore filters the purl
    as well, so the query stays at least as strict as the refusal -- see it for why a
    selection that read only the type fills a ledger with failed runs for ever.

    Args:
        identity: What resolution recorded.

    Returns:
        True for an established PyPI identity.

    """
    return identity.outcome == ESTABLISHED and identity.primary_type.lower() == PURL_TYPE


def inapplicability_of(identity: ReleaseIdentity) -> str:
    """Return why Python compatibility is not a question about this package, or nothing.

    Pure: the whole of the applicability rule, over what resolution recorded and
    nothing else, so every branch of it is reachable with no database
    (`CPM-AD-27`).

    **There is exactly one reason, and that is the point.** `CPM-PY314-S01` AC 2's
    `not_applicable` is reachable only where identity *established* that the
    question does not apply, which is a `release_ecosystem` mapping recorded
    `not_applicable`. A mapping that is `unknown`, `error` or `not_found` -- or
    absent -- established **nothing**, and answering a reason for it would record a
    determinate claim from an absence: the defect class found in every story of the
    preceding epic. Those are `source_for`'s to refuse, saying the question is
    unanswered.

    An `established` mapping naming some *other* ecosystem is deliberately not a
    reason either, and this is where this collector diverges from
    `collectors/pypi_release.py`'s otherwise identical hook. That sibling reads it as
    "PyPI is not where this package is released", which is true of the question it
    asks; here the question is whether a package is ready for a Python, and identity
    having named a non-Python ecosystem is not the same as identity having
    established that no Python question exists. `CPM-PY314-S01`'s matrix says the
    mapping's own `not_applicable` is "the only path to it", so the divergence is the
    story's rather than this module's.

    Args:
        identity: What resolution recorded.

    Returns:
        The reason when the mapping was recorded `not_applicable`, and the empty
        string otherwise.

    """
    if identity.outcome == OutcomeState.NOT_APPLICABLE.value:
        return (
            f"identity recorded this package's release-ecosystem mapping as {identity.outcome!r}: resolution "
            f"established that the package's type gives it no release ecosystem, so there is no declared Python "
            f"metadata for this collector to assess (CPM-FR-1, CPM-FR-14). This is the only thing that makes the "
            f"question inapplicable -- an unresolved mapping leaves it unanswered instead."
        )
    return ""


def _document_in(body: object, *, source: str) -> dict[str, object]:
    """Decode a document and refuse anything that is not an object.

    Args:
        body: The document the source served, as it was recorded.
        source: The locator it was served from, for the messages.

    Returns:
        The decoded object.

    Raises:
        PythonReadinessDocumentError: When the body is not a string, is too long to
            decode, is not JSON, or is not an object.

    """
    if not isinstance(body, str):
        message = (
            f"{source} recorded a payload whose body is {type(body).__name__} rather than a string. A Payload is "
            f"a value a transport built, so its body is checked here rather than left to raise a TypeError from a "
            f"length check that names no source."
        )
        raise PythonReadinessDocumentError(message)
    if len(body) > MAX_DOCUMENT_CHARACTERS:
        message = (
            f"{source} served {len(body)} characters, and this collector decodes at most "
            f"{MAX_DOCUMENT_CHARACTERS}. The largest project document is an order of magnitude smaller than that, "
            f"so a document this size is a source doing something else -- and parsing it would spend a worker's "
            f"soft time limit finding out (CPM-AD-9)."
        )
        raise PythonReadinessDocumentError(message)
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError) as unreadable:
        # Three rather than one, on the terms `collectors/kev.py` states:
        # `json.loads` recurses per level of nesting, so a deeply nested body raises
        # `RecursionError`, and a body that reached here as bytes raises
        # `UnicodeDecodeError` for an undecodable one. The `TypeError` a body that is
        # not a string would raise is unreachable, because such a body is refused
        # above by name.
        message = (
            f"{source} did not serve a readable project document: {type(unreadable).__name__}: {unreadable}. The "
            f"observation is refused rather than recorded as a project that declared nothing, which is the "
            f"honest-looking result this table must not manufacture (CPM-FR-14)."
        )
        raise PythonReadinessDocumentError(message) from unreadable
    if not isinstance(document, dict):
        message = (
            f"{source} served {type(document).__name__} rather than a project object. A source whose shape has "
            f"changed is refused rather than read for whatever still parses."
        )
        raise PythonReadinessDocumentError(message)
    return document


def _optional_string(mapping: dict[str, object], *, field: str, source: str) -> str:
    """Return a field that may be absent or null, stripped, or refuse a mistyped one.

    Args:
        mapping: The decoded object the field sits in.
        field: Which field to read.
        source: The locator, for the message.

    Returns:
        The stripped string, or the empty string when the field is absent or null --
        both of which PyPI really sends, and both of which mean "the project
        declares none".

    Raises:
        PythonReadinessDocumentError: When the field is present, is not null, and is
            not a string.

    """
    value = mapping.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        message = (
            f"{source} served a document whose {field!r} is {type(value).__name__} rather than a string. A source "
            f"whose shape has changed is refused rather than read past -- a specifier this collector cannot even "
            f"attempt to read is different from one it attempted and would not answer."
        )
        raise PythonReadinessDocumentError(message)
    return value.strip()


def _require_encodable(value: str, *, source: str, what: str) -> None:
    """Refuse a value no database will take at all, whatever column it was headed for.

    **The unstorable set is narrow, and it is asked as the question the driver
    asks.** A NUL byte and a lone UTF-16 surrogate are refused by psycopg from
    *inside* the driver, several frames past the `try` `translate` is wrapped in, so
    an unrefused one escapes as neither a document refusal nor a recorded
    observation and repeats every cadence. The surrogate half is asked by *encoding*
    rather than by matching a pattern, because the encode is what the driver will
    actually do.

    **Width is deliberately not asked here, and the two halves part company on
    purpose.** A value that cannot round-trip is a *document* this collector will not
    read, whatever it was going to be used for; a value that is merely wider than one
    column is a question about that column, and the answer differs per field:

    - a classifier is measured nowhere, because the only classifier that ever lands
      in `matching_classifier` is the one equal to `classifier_for(series)`, whose
      width the series fixes and the document cannot influence. Measuring *every*
      declared classifier against that column -- as an earlier shape of this guard
      did -- turned one long, entirely unrelated classifier into an `error` row for a
      document that was otherwise perfectly readable, every run, for ever;
    - a `Requires-Python` value is measured in `assess`, which records `unknown` with
      the reason rather than refusing the document. See `OVERSIZE_SPECIFIER_DETAIL`.

    Args:
        value: What the document said.
        source: The locator, for the message.
        what: What the value is, for the message.

    Raises:
        PythonReadinessDocumentError: When it carries a NUL byte or is not encodable
            as UTF-8.

    """
    if _NUL in value:
        message = (
            f"{source} states a {what} carrying a NUL byte. The observation is refused rather than cleaned: a "
            f"value this collector rewrote is not the value the source published, and one it stored unchanged is "
            f"a row PostgreSQL refuses from inside the driver, outside the guard that would have recorded the "
            f"failure."
        )
        raise PythonReadinessDocumentError(message)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as unstorable:
        message = (
            f"{source} states a {what} that is not encodable as UTF-8: {unstorable}. A lone surrogate decodes out "
            f"of JSON perfectly well and is refused by the database driver, outside the guard that would have "
            f"recorded the failure -- so it is refused here, where the value enters."
        )
        raise PythonReadinessDocumentError(message) from unstorable


def _unrecordable_specifier(specifier: str) -> str:
    """Return why a specifier cannot be recorded verbatim, or nothing.

    Pure but for reading one column's declared width off the model, which
    `project_locator` does for the same reason: the bound a value is measured against
    is the bound the table actually enforces, and `max_length` is enforced by
    PostgreSQL and ignored by SQLite (`R-5`).

    Args:
        specifier: The `Requires-Python` value the project declared.

    Returns:
        The reason it will not fit its column, or the empty string when it will.

    """
    width = _column_width("requires_python")
    if len(specifier) <= width:
        return ""
    return (
        f"the specifier is {len(specifier)} characters and the column that records it takes {width}, so this "
        f"product cannot preserve it exactly as stated -- and a truncated specifier is a different specifier"
    )


def _column_width(field: str) -> int:
    """Return how wide one of this table's text columns is.

    Read off the model rather than restated, so the bound a value is refused against
    is the bound the table actually enforces.

    **A column that declares no width is a refusal rather than a skip**, on the terms
    `collectors/kev.py` states: a guard that answered `None` for such a column would
    have every caller write `if width is not None and ...`, so a field renamed or
    turned into a `TextField` would silently turn its refusal off with nothing
    anywhere failing.

    Args:
        field: The column's name.

    Returns:
        Its `max_length`.

    Raises:
        CollectorConfigurationError: When the column is not a `CharField`, or
            declares no `max_length`. A defect in this module or in the models beside
            it, and never something a source can cause.

    """
    column = PythonReadinessAssessment._meta.get_field(field)  # noqa: SLF001 - Django's own public-by-convention API
    width = column.max_length if isinstance(column, models.CharField) else None
    if width is None:
        message = (
            f"PythonReadinessAssessment.{field} declares no max_length, so there is no bound to refuse an "
            f"over-wide value against. Refused rather than skipped: a width guard that quietly stops guarding is "
            f"one that stores whatever a source sends on SQLite and fails the run on PostgreSQL (R-5)."
        )
        raise CollectorConfigurationError(message)
    return width


def _safe_detail(text: str) -> str:
    """Return a reason that can be stored, however the caller built it.

    The opposite posture from `_require_encodable`, and the difference is the path:
    this one is called where a sentinel row is being shaped, which is a path already
    recording a failure and one `CPM-NFR-3` requires to write a row. The reason
    arriving there is the base's own sentence with a third party's exception message
    inside it, so raising over its shape would turn "the source failed" into "no row
    at all".

    Args:
        text: The reason the base composed.

    Returns:
        The reason with control characters and lone surrogates replaced by spaces
        and, where it was longer than `MAX_SENTINEL_DETAIL_CHARACTERS`, shortened
        with a marker saying so.

    """
    cleaned = _SURROGATES.sub(" ", _CONTROL_CHARACTERS.sub(" ", text))
    if len(cleaned) > MAX_SENTINEL_DETAIL_CHARACTERS:
        return f"{cleaned[:MAX_SENTINEL_DETAIL_CHARACTERS]} {SHORTENED_DETAIL}"
    return cleaned


class PythonReadinessCollector(Collector):
    """The collector that records what a package's metadata claims about Python 3.14.

    Writes `python_readiness_assessments`. Four methods and nine declarations. See
    the module docstring for why a metadata silence is `unknown`, why the determinate
    values name inference, why `not_applicable` has exactly one path to it, and why
    this collector reads the source a sibling already reads rather than that
    sibling's rows.
    """

    #: The nine declarations the base checks at construction, every one written out
    #: on the terms `SourceReleaseCollector` gives.
    name: ClassVar[str] = COLLECTOR_NAME

    evidence_model: ClassVar[type[AppendOnlyModel] | None] = PythonReadinessAssessment

    observation_window: ClassVar[timedelta | None] = READINESS_OBSERVATION_WINDOW

    timeout: ClassVar[float | None] = READINESS_TIMEOUT

    retries: ClassVar[int] = READINESS_RETRIES

    rate_limit: ClassVar[RateLimit] = READINESS_RATE_LIMIT

    headers: ClassVar[Mapping[str, str]] = READINESS_HEADERS

    freshness_target: ClassVar[timedelta | None] = READINESS_FRESHNESS_TARGET

    response_cache_ttl: ClassVar[timedelta | None] = READINESS_CACHE_TTL

    #: How often the full-inventory sweep dispatches this collector
    #: (`CPM-CURRENCY-S05`). Bound to the module constant the target and the window
    #: are already derived from, so no number moves; `collectors/apps.py` reconciles
    #: it against this collector's `CELERY_BEAT_SCHEDULE` entry at boot, in both
    #: directions. The entry's *phase* is `READINESS_DISPATCH_OFFSET` and is not part
    #: of that reconciliation -- see that constant.
    cadence: ClassVar[timedelta | None] = READINESS_CADENCE

    #: The one identity read, remembered on the instance for the run in progress, on
    #: the terms `PyPIReleaseCollector._identity` states: the base asks
    #: `inapplicability` and then `source_for` about one package in one run and both
    #: need the same answer, so reading it twice would be a second query on every
    #: collection and a window in which the two could disagree. Forgotten at the
    #: start of every run, and keyed by package as well, so a caller reaching
    #: `source_for` directly for another package reads afresh.
    _identity: ReleaseIdentity | None = None
    _identity_package: int | None = None

    #: The locator this run asked for, remembered when `source_for` answered, for the
    #: reason `SourceReleaseCollector._locator` gives: `sentinel_evidence` records it
    #: and is not handed it. Blank on the `not_applicable` path, because no locator
    #: was ever built -- and reset when a new question is asked, so a row on that path
    #: never carries the previous package's.
    _locator: str = ""

    @classmethod
    def selectable_packages(cls) -> Iterable[int]:
        """Return the packages this collector can be asked about: the ones identity can answer for.

        The complement of `source_for`'s refusal, expressed as the query that
        refusal is written against. `asks_about` needs a `release_ecosystem` mapping
        recorded `established` for PyPI, and `inapplicability_of` answers for one
        recorded `not_applicable` -- so those are the whole of what this collector can
        say anything about.

        **`not_applicable` is selected on purpose, and it is the row that would
        otherwise be unreachable.** A package whose mapping is `not_applicable`
        produces `CPM-PY314-S01` AC 2's row with no call made and no allowance spent,
        which is also what keeps it from reading stale against a question it will
        never be asked. Selecting it costs one database read; not selecting it would
        make the acceptance criterion's row unreachable in a real deployment.

        **An established mapping naming another ecosystem is deliberately excluded,
        and it is the one filter this selection adds to
        `PyPIReleaseCollector`'s.** That sibling records such a package
        `not_applicable`; this collector may not, because `CPM-PY314-S01` makes
        identity's own `not_applicable` the only path to that state. Left in the
        selection the package would fail a run every cadence for ever, which is the
        "ledger fills with failed runs" shape every selection in this package exists
        to prevent -- so it is not offered, and it reads `unknown` for want of an
        observation rather than carrying a determinate claim nobody established.

        **An unresolved mapping is not offered either, and that is the same rule.**
        Identity has established nothing, `CPM-FR-1` forbids guessing a project name
        from a package name, and there is therefore no question to ask; `source_for`
        refuses one if a forced recollection reaches it, saying the compatibility
        question is unanswered rather than inapplicable.

        **The purl is filtered as well as the type, because identity permits the two
        to disagree.** `identity/services.py` validates an `established` mapping by
        asking whether *any* of its fields carries a value, so a row with
        `primary_type='pypi'` and a blank or non-PyPI `primary_purl` is legal and
        writable. Selected on the type alone, such a package would be offered,
        would pass `asks_about` -- which reads the type and nothing else -- and would
        then raise from `project_locator`, which `core/collection.py` calls outside
        every `try`: a `failed` run with no evidence row, every cadence, for ever.
        That is the shape this selection exists to prevent, so the query requires the
        purl prefix `source_for` will go on to demand.

        The filter is a case-sensitive prefix while `project_name` is tolerant of
        case, of surrounding whitespace and of a leading slash, so this query is
        strictly *narrower* than the refusal rather than exactly its complement --
        which is the safe direction and the one `asks_about` claims: a selection may
        withhold a package this collector could have answered for, and may never
        offer one `source_for` then refuses.

        Returns:
            The primary keys, as a lazy queryset ordered by key -- streamed by
            `collectors/sweep.py` rather than materialised. One row per
            `(package, kind)` means one key per package, so no key repeats.

        """
        return (
            PackageMapping.objects.filter(kind=MappingKind.RELEASE_ECOSYSTEM.value)
            .filter(
                models.Q(outcome=OutcomeState.NOT_APPLICABLE.value)
                | models.Q(
                    outcome=ESTABLISHED,
                    package__primary_type__iexact=PURL_TYPE,
                    package__primary_purl__startswith=PYPI_PURL_PREFIX,
                ),
            )
            .order_by("package_id")
            .values_list("package_id", flat=True)
        )

    def inapplicability(self, *, package_id: int) -> str:
        """Say whether Python compatibility is a question about this package, from what identity recorded.

        Args:
            package_id: The package being collected, by the integer primary key
                `CPM-AD-3` fixes.

        Returns:
            The reason the question does not apply -- a `release_ecosystem` mapping
            recorded `not_applicable`, and nothing else -- or the empty string, which
            covers both "the question applies" and "identity has not decided", the
            second of which `source_for` refuses.

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
            PythonReadinessIdentityError: When the package has no `release_ecosystem`
                mapping row; when the mapping is `unknown`, `error` or `not_found`;
                when it is established for another ecosystem or with a blank type; or
                when its purl cannot be read as a PyPI project. Every one of those is
                identity having established **nothing**, and the message says the
                question is unanswered rather than inapplicable. A `not_applicable`
                mapping never reaches here: `inapplicability` answers it first.

        """
        identity = self._release_identity(package_id)
        if identity is None:
            message = (
                f"package {package_id} has no release_ecosystem mapping row, so identity has recorded nothing "
                f"about where it is released and there is no declared Python metadata to assess. "
                f"{IDENTITY_UNRESOLVED_DETAIL}"
            )
            raise PythonReadinessIdentityError(message)
        if not asks_about(identity):
            message = (
                f"package {package_id}'s release_ecosystem mapping is {identity.outcome!r} with "
                f"primary_type={identity.primary_type!r}, and this collector reads declared metadata only when "
                f"the mapping is {ESTABLISHED!r} for {PURL_TYPE!r}. {IDENTITY_UNRESOLVED_DETAIL}, so the run is "
                f"refused rather than recorded as an observation nobody made (CPM-FR-1) and emphatically rather "
                f"than recorded {OutcomeState.NOT_APPLICABLE.value!r}, which only identity may establish."
            )
            raise PythonReadinessIdentityError(message)
        self._locator = project_locator(identity.primary_purl)
        return self._locator

    def translate(self, payload: Payload, *, package_id: int, observed_at: datetime) -> Sequence[AppendOnlyModel]:
        """Turn one project document into the one assessment it is worth.

        One row and never none: the base reads an empty translation as a parser that
        no longer matches its source.

        Args:
            payload: What the source said, recorded. Reached only for a call the
                source answered -- absence and failure are the base's to record.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with, from the injected clock.
                The base refuses a row stamped with anything else.

        Returns:
            One unsaved `PythonReadinessAssessment`.

        Raises:
            PythonReadinessDocumentError: When the document cannot be read as a
                project. The base writes an `error` row and re-raises.

        """
        assessment = assess(declared_metadata(payload.body, source=payload.source), series=PYTHON_SERIES)
        return [
            PythonReadinessAssessment(
                observed_at=observed_at,
                package_id=package_id,
                trace_id=current_trace_id(),
                source=payload.source,
                state=assessment.state,
                python_series=series_of(PYTHON_SERIES),
                requires_python=assessment.requires_python,
                matching_classifier=assessment.matching_classifier,
                deciding_signal=assessment.deciding_signal,
                detail=assessment.detail,
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

        Every declared fact is absent: a sentinel row is written for a call that
        produced no document, or for a question that was never asked. What the row
        does carry is the Python series it was about -- required of every row by
        `readiness_names_the_series_it_assessed`, because a later story writes a
        *verified* result about a series and a row that could not name one would make
        the two indistinguishable.

        **A `not_found` row carries a caveat the base cannot know to write.** The
        base reaches it when the release ecosystem says the project is not there,
        which is an absence from the index rather than a project that declared
        nothing about this Python -- and those are the two rows on this table a reader
        could most plausibly confuse. So the caveat is appended to the base's own
        sentence rather than left to be inferred.

        Args:
            state: `OutcomeState.ERROR`, `OutcomeState.NOT_FOUND` or
                `OutcomeState.NOT_APPLICABLE`, decided by the base.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with.
            detail: What happened, in words worth storing beside the state. Cleaned
                and bounded rather than trusted -- see `_safe_detail`: on the `error`
                path it carries a third party's exception message.

        Returns:
            One unsaved `PythonReadinessAssessment` carrying the state's value
            verbatim in `state` (`CPM-AD-24`).

        Raises:
            CollectorConfigurationError: When asked for a state this collector has no
                row shape for -- `ok`, which is not in this vocabulary at all;
                `unknown`, which is `translate`'s to write with the reason the run
                established; and the two inferred verdicts, which are a *claim* a
                project made and which a sentinel path never has. Refused at the call
                rather than at the insert, which is where a row carrying an inferred
                verdict and no deciding signal would land, several frames from the
                call that was wrong.

        """
        # Written as three comparisons rather than as membership of a declared set,
        # for the reason `PyPIReleaseCollector.sentinel_evidence` gives:
        # `tests/unit/django_apps/test_single_ordering_audit.py` reads a literal
        # holding two or more `OutcomeState` members outside `core/outcomes.py` as a
        # second precedence order, and it is right to.
        if (
            state is not OutcomeState.ERROR
            and state is not OutcomeState.NOT_FOUND
            and state is not OutcomeState.NOT_APPLICABLE
        ):
            message = (
                f"{type(self).__name__}.sentinel_evidence was asked for {state.value!r}, and this collector "
                f"shapes a sentinel row for {OutcomeState.ERROR.value!r}, {OutcomeState.NOT_FOUND.value!r} and "
                f"{OutcomeState.NOT_APPLICABLE.value!r} only. An inferred verdict is a claim a project's own "
                f"metadata made, which a sentinel path never has, and {OutcomeState.UNKNOWN.value!r} is written "
                f"by translate with the reason the run established."
            )
            raise CollectorConfigurationError(message)
        reason = _safe_detail(detail)
        if state is OutcomeState.NOT_FOUND:
            reason = f"{reason}: {ABSENT_FROM_INDEX_DETAIL}"
        return PythonReadinessAssessment(
            observed_at=observed_at,
            package_id=package_id,
            trace_id=current_trace_id(),
            source=self._locator,
            state=state.value,
            python_series=series_of(PYTHON_SERIES),
            requires_python="",
            matching_classifier="",
            deciding_signal="",
            detail=reason,
        )

    def _release_identity(self, package_id: int) -> ReleaseIdentity | None:
        """Return what resolution recorded about this package's release ecosystem.

        The one database read in this module, and it reads `identity` -- the only
        application a collector may read (`CPM-AD-7`). One query, joining the mapping
        row to the columns that mapping owns, and only those columns: the row's other
        fields are none of this collector's business.

        Args:
            package_id: The package being collected.

        Returns:
            The identity, or `None` when no `release_ecosystem` mapping row exists
            for the package -- which is also what a package with no identity row at
            all produces, and the two are refused together.

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
