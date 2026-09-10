"""What a build and an import of a package actually did, and never what its metadata claimed.

`CPM-FR-14` splits Python 3.14 readiness into a cheap static pass and an expensive
verification pass, and the whole purpose of `CPM-EP-PY314` is that the two stay
distinguishable. `collectors/python_readiness.py` is the cheap pass and records what
a project's metadata *claims*; this module is the expensive one and records what an
execution *did*. A claim is not a build, and this table is where the difference is
kept.

**It is on the `verify` queue, and that follows from the task's name rather than
from a route anybody could get wrong.** `core/queues.py` routes `cpm.verify.*` to
`verify` and carries `cpm.verify.py314_build` as its worked example;
`collectors/tasks.py` declares exactly that name. `CPM-AD-20` puts a compute-backed
build on its own queue precisely so a five-minute job cannot starve the daily
security sweep (`R-11`), and a queue that is a property of the declared name cannot
drift from the collector that owns it.

**Triggered, and never swept.** `CPM-FR-14` makes verification "a separate,
optionally triggered capability" and `CPM-PY314-S02`'s AC 3 says it is not run
across the inventory by default. `selectable_packages` therefore answers `None` --
"this collector is not swept one package at a time" -- so `collectors/sweep.py`
refuses to dispatch it **by name**, no `CELERY_BEAT_SCHEDULE` entry names it, and
this collector declares no cadence. AC 3 is a property of what is declared here
rather than of a schedule somebody remembered not to write.

**Nothing in this module executes anything.** The thing that runs a build is a
**declared adapter** at the collector base's transport seam, and `CPM-PY314-S02`
ships **none** -- `collectors/verification.py` is the slot and argues at length why
choosing an isolation posture for running third-party code, unasked, in a
supply-chain security tool is not a decision this story makes. So there is no
subprocess here, no container, no build, no import, no fetch of a package under
test. What ships is the seam, the evidence and the refusal.

**The determinate values name proof.** `verified_compatible` and
`verification_failed`, never `ok` and never a bare `compatible`: `CPM-FR-14`
requires inferred and verified compatibility to be *distinct recorded states* and
`CPM-AD-24` carries a state's value verbatim onto every read surface, so a value
called `compatible` here would sit on a queue beside
`collectors/python_readiness.py`'s row and read identically.
`collectors/outcomes.py` composes the vocabulary and argues both halves --
including why a failed build is `verification_failed` rather than
`verified_incompatible`.

**Every determinate row says where it ran.** `CPM-PY314-S02`'s AC 1 requires the
platform, the architecture and a log reference, and it is not conditional on the
answer: a build that failed on `linux`/`x86_64` is a different fact from a build
that failed on `osx`/`arm64`, and a row that could not say which is not a
verification at all. `result_in` refuses a document that omits any of the three and
`python_verification_results` refuses the row, so the criterion holds at the reader
and at the database rather than only in this docstring.

**A failed build is a result, and a backend that fell over is not.**
`verified: false` is a determinate row carrying its log reference; a backend that
raises is a `TransportError` the base records as `error`, with nothing to open. The
two are the rows an engineer most needs to tell apart, and folding them together
would hide the one worth reading.

**Which packages it will answer about, and the one rule it inherits whole.**
Applicability is `collectors/python_readiness.py`'s exactly: `identity`'s
`release_ecosystem` mapping recorded `not_applicable` is the **only** path to a
`not_applicable` row, and a mapping that is `unknown`, `error`, `not_found` or
absent establishes **nothing** -- so the question is *unanswered* rather than
inapplicable and the trigger is refused rather than recorded. Reading the one as
the other would be worse here than there: a `not_applicable` verification row is
this product saying it need never build a package nobody has resolved yet.

**What it does not inherit is the PyPI restriction, and that is deliberate.** The
static pass reads `pypi.org`'s JSON API, so it can only answer for a package whose
purl names a PyPI project. This module reads no host: it hands a purl to a backend
that already knows what it can build (`CPM-AD-29`), and a backend that builds conda
packages is as legitimate as one that builds wheels. So an `established` mapping
with any usable purl is a package this collector can be triggered for, and what a
backend does with a purl it does not recognise is the backend's to say -- through
`found`, or through a `TransportError`.

**No re-derivation of the static assessment, and no read of its table.**
`CPM-AD-7` forbids one collector reading another's evidence, the exemption list
holds exactly one entry and it is not this module's. A verification is triggered by
a person or a caller who has already decided it is worth spending; deciding it from
`python_readiness_assessments` would be this collector reaching into a table it does
not own, and *ranking* the two is `CPM-PY314-S03`'s policy (`CPM-AD-8`,
`CPM-AD-21`).

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

import structlog
from django.db import models

from conda_sentinel.collectors.models import PythonVerificationResult
from conda_sentinel.collectors.outcomes import VERIFICATION_FAILED
from conda_sentinel.collectors.outcomes import VERIFIED_COMPATIBLE
from conda_sentinel.collectors.specifiers import Series
from conda_sentinel.collectors.specifiers import series_of
from conda_sentinel.core.collection import NO_CACHE
from conda_sentinel.core.collection import NO_WINDOW
from conda_sentinel.core.collection import Collector
from conda_sentinel.core.collection import CollectorConfigurationError
from conda_sentinel.core.ledger import current_trace_id
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.rate_limit import RateLimit
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
    "ARCHITECTURE_FIELD",
    "COLLECTOR_NAME",
    "DETAIL_FIELD",
    "IDENTITY_UNRESOLVED_DETAIL",
    "LOG_REFERENCE_FIELD",
    "MAX_DOCUMENT_CHARACTERS",
    "MAX_SENTINEL_DETAIL_CHARACTERS",
    "NOT_BUILT_DETAIL",
    "NOT_OBTAINABLE_DETAIL",
    "PLATFORM_FIELD",
    "PYTHON_SERIES",
    "REQUIRED_FIELDS",
    "RESULT_FIELDS",
    "SHORTENED_DETAIL",
    "UNNAMEABLE_IDENTITY_SEGMENT",
    "VERIFICATION_CACHE_TTL",
    "VERIFICATION_FRESHNESS_TARGET",
    "VERIFICATION_HEADERS",
    "VERIFICATION_OBSERVATION_WINDOW",
    "VERIFICATION_RATE_LIMIT",
    "VERIFICATION_RETRIES",
    "VERIFICATION_TIMEOUT",
    "VERIFIED_FIELD",
    "VERIFY_LOCATOR_PREFIX",
    "VERIFY_SCHEME",
    "Py314VerificationCollector",
    "Py314VerificationDocumentError",
    "Py314VerificationIdentityError",
    "ReleaseIdentity",
    "VerificationResult",
    "asks_about",
    "inapplicability_of",
    "package_locator",
    "result_in",
]

logger = structlog.get_logger(__name__)

#: What this collector is called, on its ledger rows, in its cache keys and in the
#: registry `config/startup/stage_two.py` sweeps.
#:
#: **It is not the last segment of this collector's task name, and it is the only
#: collector in this component of which that is true.** The other nine are swept,
#: and `collectors/sweep.py` derives `cpm.collect.<name>` from the name to enqueue
#: them; this one is never swept, so no task name is derived from this string at
#: all. The task is `cpm.verify.py314_build` -- `core/queues.py`'s own worked
#: example, spelled there before this module existed -- and it is declared verbatim
#: in `collectors/tasks.py`.
COLLECTOR_NAME: Final[str] = "py314_verification"

#: The Python series this collector verifies, and the one value in this module a
#: later story is expected to change.
#:
#: **Restated rather than imported from `collectors/python_readiness.py`**, on the
#: terms that module restates `PYPI_HOST`: no collector imports another
#: (`CPM-AD-7`), and one that did would be a collector whose *subject* changed when
#: a different story edited its neighbour. `tests/unit/django_apps/
#: test_py314_verification.py` reconciles the two spellings, because restating them
#: is right under `CPM-AD-7` and nothing else would have compared them -- and here
#: the comparison matters more than it did there: `CPM-PY314-S03` reduces the two
#: tables together, and two collectors assessing two different Pythons would make
#: that reduction meaningless with every gate green.
#:
#: The *spelling* helper is imported rather than restated, and the difference is
#: the one `collectors/specifiers.py` exists for: how a series is written into a
#: column is one decision, made in a leaf module that is nobody's collector, so the
#: two tables cannot come to disagree about whether `3.14` has a trailing zero.
PYTHON_SERIES: Final[Series] = (3, 14)

#: How long this collector's evidence may be read as current (`CPM-AD-28`), and it
#: is **provisional**.
#:
#: **PRD Open Question 7c is what this constant answers, and it answers it in the
#: shape the PRD's first candidate reading names.** Every other collector derives a
#: target from `cadence x (1 + tolerated_missed_runs)`; this one has no cadence to
#: derive from, because `CPM-NFR-2` runs it on demand -- and `CPM-AD-28` still
#: requires a strictly positive target, with no sentinel for "never goes stale".
#: So the target is measured from the **request**: thirty days is how long a
#: verification result stays worth acting on before somebody should ask for a fresh
#: one, and it is chosen rather than derived.
#:
#: **Shipped as provisional, on the terms `policies/parameters.py` shipped its risk
#: order.** What review is expected to change is the number and nothing else: the
#: *derivation* is what the PRD says is settled, and there is none here to settle.
#: Thirty days is argued from what ages underneath a verification -- a package
#: publishes new releases, an interpreter takes patch releases, a build toolchain
#: moves -- rather than measured, because measuring it needs a backend and no
#: backend ships. The first operator to declare one is where it is revisited, and
#: `docs/conda-sentinel/operations.md` says so to them.
#:
#: **The alternative reading was available and is deliberately not taken.** The PRD
#: offers a second: treat a verification as durable evidence about an immutable
#: artifact and therefore never stale. It is a defensible reading -- a wheel does
#: not change -- and the PRD says in as many words that it "would need `CPM-AD-28`
#: amending rather than a number". Amending an architecture decision unilaterally
#: is not a story's to do, and the amendment would be load-bearing well beyond this
#: table: `CPM-AD-28`'s refusal of a target-less collector is what stops six-month-
#: old evidence reading as current everywhere. So the number is chosen here and the
#: architecture question is left where it belongs.
VERIFICATION_FRESHNESS_TARGET: Final[timedelta] = timedelta(days=30)

#: How long a successful observation suppresses the next one (`CPM-AD-7`):
#: `NO_WINDOW`, meaning observe on every run.
#:
#: **The trigger *is* the decision to run, so there is nothing for a window to
#: protect against.** Every other collector is swept, and its window is what stops a
#: scheduled sweep from re-reading a source it read an hour ago. Nothing sweeps this
#: one: a run happens because a person or a caller asked for it, and a window would
#: silently discard that request -- writing no row, returning `skipped`, and leaving
#: whoever triggered it to conclude the verification ran and agreed with the
#: previous one.
#:
#: It is also `CPM-PY314-S02`'s matrix row about two triggers for one package: two
#: rows, and the second does not replace the first (`CPM-AD-2`). A window would have
#: made that row unreachable.
VERIFICATION_OBSERVATION_WINDOW: Final[timedelta] = NO_WINDOW

#: How many times a failed run is retried, and therefore what the rate limiter is
#: charged per collection.
#:
#: **Zero, and it is the one declaration in this module that departs from every
#: sibling's shared default.** A retry here is not another HTTP request: it is
#: another *build*, minutes of somebody's compute, re-run automatically over a
#: failure nobody has looked at. That is exactly the compute amplification the
#: `verify` queue exists to contain (`CPM-AD-20`, `R-11`), reached from inside the
#: collector rather than from the queue. A verification that failed is a row saying
#: so, with a log reference; asking for it again is a second trigger, which is a
#: decision a person makes.
VERIFICATION_RETRIES: Final[int] = 0

#: Seconds any single connect or read phase may take.
#:
#: **It bounds the transport this base would build, and not the backend's own
#: execution** -- the same limit `collectors/vulnerability.py` records against its
#: own declared adapter, and here the gap between the declaration and the reality is
#: wider than anywhere else in this component. `core/collection.py` builds a
#: `RequestsTransport` from this value when no transport is passed, and the declared
#: execution backend is passed instead (`CPM-AD-29`), so five seconds is what an
#: unsubstituted collector would allow a socket and says nothing about how long a
#: build may take. Claiming otherwise would be claiming something this module does
#: not do.
#:
#: **What actually bounds a backend is the inherited soft time limit**, which
#: `CPM-AD-9` fixes in settings and forbids raising. `docs/conda-sentinel/operations.md` and
#: `collectors/verification.py` both say so to an operator, and
#: `CPM-PY314-S02` records it as deferred work: a backend whose `fetch` blocks for
#: the length of a real build meets that limit and the task is killed with no row
#: written, so a shipped backend must drive the work elsewhere and answer about a
#: run that has already finished.
VERIFICATION_TIMEOUT: Final[float] = 5.0

#: How hard this collector may push its backend (`CPM-AD-20`).
#:
#: **The only allowance in this component that bounds compute rather than
#: courtesy.** There is no source with a published ceiling here -- there is a runner
#: somebody owns, and what it costs to push it is minutes of CPU rather than a
#: rate-limit response. Six a minute, charged `1 + retries` -- one -- per
#: collection, so six verifications a minute and no more.
#:
#: The number is a bound on a *trigger loop* rather than a throughput target: one
#: verification is expected to take minutes, so a component reaching this allowance
#: is one whose triggers are arriving far faster than its backend can serve them,
#: and refusing them is better than queueing them. It is declared rather than left
#: generous because an allowance that was unlimited by omission would let a scripted
#: caller fill the `verify` queue with every package in the inventory -- which is
#: `CPM-PY314-S02`'s AC 3 defeated from the trigger side, having been made
#: structural on the schedule side.
VERIFICATION_RATE_LIMIT: Final[RateLimit] = RateLimit(calls=6, per=timedelta(minutes=1))

#: What this collector's backend is sent on every request: **nothing**.
#:
#: Empty is a complete statement here, in a way it is not for the collectors that
#: read a known host. An execution backend is not necessarily an HTTP client at all
#: -- it may drive a container runtime or a build cluster -- so an `Accept` header
#: would be this module telling a runner what representation to serve, and a
#: `User-Agent` would identify this component to a host it may never contact. A
#: backend that does speak HTTP sends its own headers, which is what
#: `collectors/watchlist.py`'s file adapter already does with the empty mapping it
#: is handed.
VERIFICATION_HEADERS: Final[Mapping[str, str]] = MappingProxyType({})

#: `NO_CACHE`: short-circuits the cache read, the cache write and the conditional
#: headers.
#:
#: **Declared, and it is the one declaration here that could not have been anything
#: else.** A remembered response replayed through `translate` produces a row the
#: base writes exactly as a fresh one -- which is right for a document a source
#: published and catastrophic for an execution: it would record a build that did not
#: run, stamped with the instant it did not run at, on a table whose entire subject
#: is what actually happened. A verification is never replayed. If a caller wants
#: yesterday's answer, yesterday's row is still there; `CPM-AD-2` guarantees it.
VERIFICATION_CACHE_TTL: Final[timedelta] = NO_CACHE

#: The scheme and host of the locator this collector hands the backend, and it is
#: deliberately opaque.
#:
#: `CPM-AD-29` makes an execution backend a transport substitution, so the adapter
#: already knows which runner, image or cluster it drives -- the locator's job is to
#: name *what is being asked about*, which is the package's identity, and to name the
#: run in the ledger's `detail` and in every log line. A hostname spelled here would
#: be this module choosing where a build runs, which is exactly the decision
#: `collectors/verification.py` refuses to make.
VERIFY_SCHEME: Final[str] = "py314-verify://declared-backend"
VERIFY_LOCATOR_PREFIX: Final[str] = f"{VERIFY_SCHEME}/"

#: What a locator says where this product's identity for the package names no usable
#: purl.
#:
#: Unreachable through the shipped trigger, which refuses such a package before a
#: locator is built -- and present anyway, on the terms `collectors/vulnerability.py`
#: states its own: the locator builder is a pure function this module's cases call
#: directly, and one that raised for the case the refusal already covers would move a
#: refusal from where it is argued to where it is not.
UNNAMEABLE_IDENTITY_SEGMENT: Final[str] = "unnameable-identity"

#: The fields of the result document this collector reads, named rather than spelled
#: at the call sites so the reader and the cases that build documents cannot drift.
VERIFIED_FIELD: Final[str] = "verified"
PLATFORM_FIELD: Final[str] = "platform"
ARCHITECTURE_FIELD: Final[str] = "architecture"
LOG_REFERENCE_FIELD: Final[str] = "log_reference"
DETAIL_FIELD: Final[str] = "detail"

#: The three facts `CPM-PY314-S02`'s AC 1 requires of every verification, as one
#: tuple so the refusal, the row and the cases cannot enumerate them differently.
#:
#: `verified` is deliberately not in it: it is required too, and it is a boolean
#: rather than a non-blank string, so it is checked by its own type rather than
#: swept with these three.
REQUIRED_FIELDS: Final[tuple[str, ...]] = (PLATFORM_FIELD, ARCHITECTURE_FIELD, LOG_REFERENCE_FIELD)

#: Every field a result document may carry. An undefined one is **refused** rather
#: than dropped, on the terms `collectors/tasks.py` refuses an undefined inventory
#: column: a backend that grows a `partial` or `timed_out` flag has changed what its
#: `verified` means, and a reader that ignored the new field would record a
#: half-finished build as a finished one.
RESULT_FIELDS: Final[frozenset[str]] = frozenset(
    {VERIFIED_FIELD, PLATFORM_FIELD, ARCHITECTURE_FIELD, LOG_REFERENCE_FIELD, DETAIL_FIELD},
)

#: The longest document this collector will hand to `json.loads`, in characters.
#:
#: A result document is five short fields, so this is four orders of magnitude of
#: headroom rather than a measurement -- and it is deliberately far below
#: `collectors/python_readiness.py`'s, which decodes a project's whole file listing.
#: What it protects is the decode: a backend that answered with a build **log**
#: rather than a result would otherwise spend a worker's soft time limit being
#: parsed (`CPM-AD-9`), and the log belongs behind `log_reference` rather than in
#: the document.
MAX_DOCUMENT_CHARACTERS: Final[int] = 64 * 1024

#: The longest reason a *sentinel* row will carry, in characters, on the terms
#: `collectors/python_readiness.py` states: a sentinel row is written on a path
#: already recording a failure and `CPM-NFR-3` requires it to be written, so a reason
#: too long, or one carrying a control character, is shortened and cleaned rather
#: than refused.
MAX_SENTINEL_DETAIL_CHARACTERS: Final[int] = 1024

#: The one character PostgreSQL refuses inside a text value, refused by the driver
#: several frames past the `try` `translate` is wrapped in -- which is why it is
#: refused where the value enters.
_NUL: Final[str] = "\x00"

#: C0 and C1 control characters and the delete character, for the one place a
#: *substitution* is the answer rather than a refusal. See `_safe_detail`.
_CONTROL_CHARACTERS: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: The UTF-16 surrogate range, for the same place.
_SURROGATES: Final[re.Pattern[str]] = re.compile(r"[\ud800-\udfff]")

#: What a row says in its own words, in each of the ways it is reachable. Named so
#: the row a run writes and the case that reads it back cannot drift.
NOT_BUILT_DETAIL: Final[str] = (
    "verification ran and did not produce a working build of this package under this Python, on the platform and "
    "architecture this row names. That is a result about this run rather than a claim that the package cannot be "
    "made to work: a build fails for reasons that are not the interpreter, and the log reference is what says "
    "which this was"
)
NOT_OBTAINABLE_DETAIL: Final[str] = (
    "the execution backend reports that it cannot obtain the artifact for this package at all, which is an "
    "absence from wherever it fetches from rather than a package that fails to build"
)
IDENTITY_UNRESOLVED_DETAIL: Final[str] = (
    "identity has established nothing about this package's release ecosystem, so there is no artifact to build "
    "and the verification question is unanswered rather than inapplicable -- a package nobody has resolved yet "
    "is not a package this product need never build"
)
SHORTENED_DETAIL: Final[str] = "[shortened by this collector]"


class Py314VerificationIdentityError(ValueError):
    """A package's identity cannot be turned into an artifact to build.

    A `ValueError` subclass, matching `collectors/python_readiness.py`'s
    `PythonReadinessIdentityError` and every other "this input cannot describe what
    it claims to be" in this product.

    **It escapes `collect()` rather than becoming an evidence row.** `source_for` is
    called before the allowance and the transport, so the run ledger row exists and
    is finalized `failed` carrying this message, and no evidence row is written at
    all -- which is `CPM-PY314-S02`'s matrix row saying a package identity
    established nothing about is not triggered and carries no claim.

    **What it refuses, and the distinction that matters most in this module.** It
    refuses a package whose `release_ecosystem` mapping resolution has *not*
    established -- `unknown`, `error`, `not_found`, or no mapping row at all -- and a
    package whose established mapping names no purl. Every one of those is identity
    having established **nothing**, and the message says so in as many words: the
    verification question is *unanswered*, not *inapplicable*. It is emphatically
    **not** `not_applicable`, which is for a mapping resolution *did* reach and found
    inapplicable and which goes through `inapplicability` instead. Turning an
    unresolved mapping into a `not_applicable` verification row would record this
    product deciding it need never build a package it simply has not identified,
    which is the guess `CPM-FR-1` forbids and the absence trap `CPM-PY314-S01` was
    written against.

    Nothing sweeps this collector, so every run reaching this class is a run somebody
    asked for: the refusal is what a caller triggering an unresolvable package gets,
    and it names what is missing rather than recording a verification nobody ran.
    """


class Py314VerificationDocumentError(ValueError):
    """A backend's answer could not be read as a verification result.

    Raised from `translate`, which the base answers by writing an `error` row and
    re-raising unchanged -- so `CPM-NFR-3`'s guarantee holds on this path too: never
    a clean result, and never no row.

    Refused rather than partially read, and the stakes here are this story's whole
    subject. A document this collector cannot understand is a backend whose shape has
    changed, and reading around it would record a determinate verdict about somebody's
    package from an answer the reader did not understand -- a row that looks exactly
    like a build that ran.

    **What it refuses is everything that is not the declared schema**: a body that is
    not JSON or not an object, a `verified` that is absent or not a boolean, a
    missing or blank `platform`, `architecture` or `log_reference`, a `detail` that is
    not a string, a field the schema does not define, a value wider than the column
    that records it, and a value no database will hold at all.

    **Width is refused here rather than recorded**, which is where this class parts
    company with `collectors/python_readiness.py`'s document error. There, an
    over-wide specifier records `unknown` with the reason, because the specifier is
    context for a verdict the run still reached. Here the over-wide values *are* the
    verdict's evidence: `CPM-PY314-S02`'s AC 1 requires them, the table refuses a
    determinate row without them, and a truncated log reference resolves to nothing.
    A verification whose evidence cannot be recorded is not a verification, so the
    document is refused and the row says `error`.
    """


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    """What resolution recorded about one package's release ecosystem.

    The one identity read this collector makes, held as a value so the two hooks that
    need it -- `inapplicability` and `source_for` -- read it once and agree about what
    it said.

    Restated rather than imported from `collectors/python_readiness.py`, which
    declares a value of the same shape for the same mapping: no collector imports
    another (`CPM-AD-7`), and a unit case reconciles the two spellings so a rename
    there is noticed here rather than silently making this collector ask a different
    question.

    Attributes:
        outcome: The `release_ecosystem` mapping's outcome, as `PackageMapping` spells
            it: `established` or one of `core`'s four sentinels.
        primary_purl: The package URL resolution recorded, or blank.

    """

    outcome: str
    primary_purl: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """What one backend document says about one execution, and nothing else from it.

    Attributes:
        state: `VERIFIED_COMPATIBLE` or `VERIFICATION_FAILED`. A result document
            always reaches one of the two: `found` is what says the artifact was not
            obtainable, and a backend that could not run at all raises rather than
            answering.
        platform: The platform the execution ran on, exactly as the backend reported
            it. Never blank -- `result_in` refuses a document that omits it.
        architecture: The architecture the execution ran on, exactly as reported.
            Never blank.
        log_reference: Where the log of this execution can be read, exactly as
            reported. Never blank.
        detail: What this row says in its own words -- the backend's own note where it
            offered one, and otherwise this module's sentence for the verdict.

    """

    state: str
    platform: str
    architecture: str
    log_reference: str
    detail: str


def package_locator(purl: str) -> str:
    """Return the locator naming one package to the declared execution backend.

    Args:
        purl: The package URL `identity` recorded as this package's primary, or the
            empty string when it recorded none.

    Returns:
        `py314-verify://declared-backend/<purl>`, or the `unnameable-identity` form
        when no purl was recorded. Never a hostname and never a path a backend has to
        interpret as a resource -- see `VERIFY_SCHEME`.

    """
    named = purl.strip()
    if not named:
        return f"{VERIFY_LOCATOR_PREFIX}{UNNAMEABLE_IDENTITY_SEGMENT}"
    return f"{VERIFY_LOCATOR_PREFIX}{named}"


def asks_about(identity: ReleaseIdentity) -> bool:
    """Report whether this collector has an artifact to ask a backend to build.

    Args:
        identity: What resolution recorded about the package's release ecosystem.

    Returns:
        `True` when the mapping is `established` and names a purl. Deliberately
        broader than `collectors/python_readiness.py`'s equivalent, which also
        requires the purl to be a PyPI one: that collector reads `pypi.org` and can
        answer for nothing else, while this one hands the purl to a backend that
        already knows what it can build -- see the module docstring.

    """
    return identity.outcome == ESTABLISHED and bool(identity.primary_purl.strip())


def inapplicability_of(identity: ReleaseIdentity) -> str:
    """Say why building this package is not a question, or say nothing.

    `CPM-PY314-S01`'s rule, restated here rather than imported, and it is the one
    rule in this module that is inherited whole rather than adapted.

    Args:
        identity: What resolution recorded about the package's release ecosystem.

    Returns:
        The reason the question does not apply -- a `release_ecosystem` mapping
        recorded `not_applicable`, and **nothing else** -- or the empty string, which
        covers both "the question applies" and "identity has established nothing",
        the second of which `source_for` refuses.

    """
    if identity.outcome != OutcomeState.NOT_APPLICABLE.value:
        return ""
    return (
        "identity established that this package has no release ecosystem, so there is no artifact to build and "
        "no Python compatibility question to verify. This is the only path to a not_applicable verification "
        "result: a mapping that is unknown, error or not_found has established nothing, and a package nobody "
        "has resolved is not a package this product need never build"
    )


def result_in(body: object, *, source: str) -> VerificationResult:
    """Read one backend answer as the verification result it claims to be.

    The whole of what a document owes, in one place, so
    `collectors/verification.py`'s prose contract has something that enforces it.

    Args:
        body: The document the backend answered with, as it was recorded.
        source: The locator it was asked about, for the messages.

    Returns:
        The result, with every required fact present and recordable.

    Raises:
        Py314VerificationDocumentError: When the body is not a readable object, when
            `verified` is absent or not a boolean, when any of `platform`,
            `architecture` and `log_reference` is absent, not a string or blank, when
            `detail` is present and not a string, when the document carries a field
            the schema does not define, or when any value cannot be recorded
            verbatim.

    """
    document = _document_in(body, source=source)
    undefined = sorted(set(document) - RESULT_FIELDS)
    if undefined:
        message = (
            f"{source} answered a document carrying {undefined!r}, which this collector's result schema does not "
            f"define. An undefined field is refused rather than dropped: a backend that grew a flag has changed "
            f"what its {VERIFIED_FIELD!r} means, and reading past it would record a half-finished build as a "
            f"finished one."
        )
        raise Py314VerificationDocumentError(message)

    verified = document.get(VERIFIED_FIELD)
    if not isinstance(verified, bool):
        message = (
            f"{source} answered a document whose {VERIFIED_FIELD!r} is {verified!r} rather than a boolean. The "
            f"verdict is the one field a backend cannot leave to interpretation: a missing or truthy-ish value "
            f"read as success would be this product recording a build it has no answer about."
        )
        raise Py314VerificationDocumentError(message)

    facts = {field: _required_string(document, field=field, source=source) for field in REQUIRED_FIELDS}
    detail = _optional_string(document, field=DETAIL_FIELD, source=source)
    return VerificationResult(
        state=VERIFIED_COMPATIBLE if verified else VERIFICATION_FAILED,
        platform=facts[PLATFORM_FIELD],
        architecture=facts[ARCHITECTURE_FIELD],
        log_reference=facts[LOG_REFERENCE_FIELD],
        detail=detail or ("" if verified else NOT_BUILT_DETAIL),
    )


def _document_in(body: object, *, source: str) -> dict[str, object]:
    """Decode a document and refuse anything that is not an object.

    Args:
        body: The document the backend answered with, as it was recorded.
        source: The locator it was asked about, for the messages.

    Returns:
        The decoded object.

    Raises:
        Py314VerificationDocumentError: When the body is not a string, is too long to
            decode, is not JSON, or is not an object.

    """
    if not isinstance(body, str):
        message = (
            f"{source} recorded a payload whose body is {type(body).__name__} rather than a string. A Payload is "
            f"a value a transport built, so its body is checked here rather than left to raise a TypeError from a "
            f"length check that names no source."
        )
        raise Py314VerificationDocumentError(message)
    if len(body) > MAX_DOCUMENT_CHARACTERS:
        message = (
            f"{source} answered {len(body)} characters, and this collector decodes at most "
            f"{MAX_DOCUMENT_CHARACTERS}. A result document is five short fields; one this size is a backend "
            f"answering with the build log rather than with a result, and the log belongs behind "
            f"{LOG_REFERENCE_FIELD!r} rather than in the document (CPM-AD-9)."
        )
        raise Py314VerificationDocumentError(message)
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError) as unreadable:
        # Three rather than one, on the terms `collectors/kev.py` states: `json.loads`
        # recurses per level of nesting, so a deeply nested body raises
        # `RecursionError`, and a body that reached here as bytes raises
        # `UnicodeDecodeError` for an undecodable one. The `TypeError` a body that is
        # not a string would raise is unreachable, because such a body is refused
        # above by name.
        message = (
            f"{source} did not answer a readable verification result: {type(unreadable).__name__}: {unreadable}. "
            f"The run is refused rather than recorded as a build that did something, which is the honest-looking "
            f"result this table must not manufacture (CPM-FR-14)."
        )
        raise Py314VerificationDocumentError(message) from unreadable
    if not isinstance(document, dict):
        message = (
            f"{source} answered {type(document).__name__} rather than a result object. A backend whose shape has "
            f"changed is refused rather than read for whatever still parses."
        )
        raise Py314VerificationDocumentError(message)
    return document


def _required_string(document: dict[str, object], *, field: str, source: str) -> str:
    """Return one of the three facts AC 1 requires, or refuse the document.

    Args:
        document: The decoded result object.
        field: Which field to read.
        source: The locator, for the message.

    Returns:
        The value, stripped of surrounding whitespace and known to fit its column.

    Raises:
        Py314VerificationDocumentError: When the field is absent, is not a string, is
            blank, cannot be recorded verbatim, or is wider than the column that
            records it.

    """
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        message = (
            f"{source} answered a document whose {field!r} is {value!r}, and this collector records the "
            f"platform, the architecture and a log reference on every verification (CPM-PY314-S02 AC 1). A "
            f"verification that cannot say where it ran is not verification: a build succeeds on a platform, "
            f"and a row claiming a verdict without naming one would be a claim about every platform made from "
            f"an execution on one."
        )
        raise Py314VerificationDocumentError(message)
    stated = value.strip()
    _require_encodable(stated, source=source, what=field)
    width = _column_width(field)
    if len(stated) > width:
        message = (
            f"{source} answered a {field!r} of {len(stated)} characters and the column that records it takes "
            f"{width}, so this product cannot preserve it exactly as stated. It is refused rather than "
            f"truncated: a truncated log reference resolves to nothing, so the row would carry a determinate "
            f"verdict whose evidence nobody can open -- which is a row with no evidence wearing a value that "
            f"looks fine."
        )
        raise Py314VerificationDocumentError(message)
    return stated


def _optional_string(document: dict[str, object], *, field: str, source: str) -> str:
    """Return a field that may be absent or null, stripped, or refuse a mistyped one.

    Args:
        document: The decoded result object.
        field: Which field to read.
        source: The locator, for the message.

    Returns:
        The stripped string, or the empty string when the field is absent or null.

    Raises:
        Py314VerificationDocumentError: When the field is present, is not null, and is
            not a string, or when it cannot be recorded verbatim.

    """
    value = document.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        message = (
            f"{source} answered a document whose {field!r} is {type(value).__name__} rather than a string. A "
            f"backend whose shape has changed is refused rather than read past."
        )
        raise Py314VerificationDocumentError(message)
    stated = value.strip()
    _require_encodable(stated, source=source, what=field)
    return stated


def _require_encodable(value: str, *, source: str, what: str) -> None:
    """Refuse a value no database will take at all, whatever column it was headed for.

    The narrow unstorable set, asked as the question the driver asks, on the terms
    `collectors/python_readiness.py` states: a NUL byte and a lone UTF-16 surrogate
    are refused by psycopg from *inside* the driver, several frames past the `try`
    `translate` is wrapped in, so an unrefused one escapes as neither a document
    refusal nor a recorded observation.

    Width is asked separately and by the caller, because it is a question about one
    column rather than about the value.

    Args:
        value: What the backend answered.
        source: The locator, for the message.
        what: What the value is, for the message.

    Raises:
        Py314VerificationDocumentError: When it carries a NUL byte or is not
            encodable as UTF-8.

    """
    if _NUL in value:
        message = (
            f"{source} answered a {what} carrying a NUL byte. The result is refused rather than cleaned: a value "
            f"this collector rewrote is not the value the backend reported, and one it stored unchanged is a row "
            f"PostgreSQL refuses from inside the driver, outside the guard that would have recorded the failure."
        )
        raise Py314VerificationDocumentError(message)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as unstorable:
        message = (
            f"{source} answered a {what} that is not encodable as UTF-8: {unstorable}. A lone surrogate decodes "
            f"out of JSON perfectly well and is refused by the database driver, outside the guard that would "
            f"have recorded the failure -- so it is refused here, where the value enters."
        )
        raise Py314VerificationDocumentError(message) from unstorable


def _column_width(field: str) -> int:
    """Return how wide one of this table's text columns is.

    Read off the model rather than restated, so the bound a value is refused against
    is the bound the table actually enforces -- `max_length` is enforced by
    PostgreSQL and ignored by SQLite (`R-5`).

    Args:
        field: The column's name.

    Returns:
        Its `max_length`.

    Raises:
        CollectorConfigurationError: When the column is not a `CharField`, or declares
            no `max_length`. A defect in this module or in the models beside it, and
            never something a backend can cause.

    """
    column = PythonVerificationResult._meta.get_field(field)  # noqa: SLF001 - Django's own public-by-convention API
    width = column.max_length if isinstance(column, models.CharField) else None
    if width is None:
        message = (
            f"PythonVerificationResult.{field} declares no max_length, so there is no bound to refuse an "
            f"over-wide value against. Refused rather than skipped: a width guard that quietly stops guarding is "
            f"one that stores whatever a backend sends on SQLite and fails the run on PostgreSQL (R-5)."
        )
        raise CollectorConfigurationError(message)
    return width


def _safe_detail(text: str) -> str:
    """Return a reason that can be stored, however the caller built it.

    The opposite posture from `_require_encodable`, and the difference is the path:
    this one is called where a sentinel row is being shaped, which is a path already
    recording a failure and one `CPM-NFR-3` requires to write a row. The reason
    arriving there is the base's own sentence with a third party's exception message
    inside it, so raising over its shape would turn "the backend failed" into "no row
    at all".

    Args:
        text: The reason the base composed.

    Returns:
        The reason with control characters and lone surrogates replaced by spaces
        and, where it was longer than `MAX_SENTINEL_DETAIL_CHARACTERS`, shortened with
        a marker saying so.

    """
    cleaned = _SURROGATES.sub(" ", _CONTROL_CHARACTERS.sub(" ", text))
    if len(cleaned) > MAX_SENTINEL_DETAIL_CHARACTERS:
        return f"{cleaned[:MAX_SENTINEL_DETAIL_CHARACTERS]} {SHORTENED_DETAIL}"
    return cleaned


class Py314VerificationCollector(Collector):
    """The collector that records what a build and an import actually did under Python 3.14.

    Writes `python_verification_results`. Five methods and nine declarations. See the
    module docstring for why it is on the `verify` queue, why nothing sweeps it, why
    it ships with no execution backend, and why the determinate values name proof.
    """

    #: The nine declarations the base checks at construction, every one written out
    #: on the terms `SourceReleaseCollector` gives.
    name: ClassVar[str] = COLLECTOR_NAME

    evidence_model: ClassVar[type[AppendOnlyModel] | None] = PythonVerificationResult

    observation_window: ClassVar[timedelta | None] = VERIFICATION_OBSERVATION_WINDOW

    timeout: ClassVar[float | None] = VERIFICATION_TIMEOUT

    retries: ClassVar[int] = VERIFICATION_RETRIES

    rate_limit: ClassVar[RateLimit] = VERIFICATION_RATE_LIMIT

    headers: ClassVar[Mapping[str, str]] = VERIFICATION_HEADERS

    freshness_target: ClassVar[timedelta | None] = VERIFICATION_FRESHNESS_TARGET

    response_cache_ttl: ClassVar[timedelta | None] = VERIFICATION_CACHE_TTL

    #: **No cadence, and the absence is the declaration** (`CPM-CURRENCY-S05`).
    #: `None` means "nothing schedules this collector", which is exactly
    #: `CPM-PY314-S02`'s AC 3 and exactly what `CPM-NFR-2` says of this signal class:
    #: on demand. `collectors/sweep.py`'s reconciliation reads a collector declaring
    #: neither a cadence nor a selection as a run-scoped or triggered collector and
    #: passes it, and would fail a collector that declared one without the other --
    #: which is what makes the pair below a checked statement rather than two
    #: omissions.
    cadence: ClassVar[timedelta | None] = None

    #: The one identity read, remembered on the instance for the run in progress, on
    #: the terms `PythonReadinessCollector._identity` states: the base asks
    #: `inapplicability` and then `source_for` about one package in one run and both
    #: need the same answer. Forgotten at the start of every run, and keyed by package
    #: as well, so a caller reaching `source_for` directly for another package reads
    #: afresh.
    _identity: ReleaseIdentity | None = None
    _identity_package: int | None = None

    #: The locator this run asked about, remembered when `source_for` answered, for
    #: the reason `SourceReleaseCollector._locator` gives: `sentinel_evidence` records
    #: it and is not handed it. Blank on the `not_applicable` path, because no locator
    #: was ever built.
    _locator: str = ""

    @classmethod
    def selectable_packages(cls) -> Iterable[int] | None:
        """Say that this collector is not swept one package at a time.

        **`CPM-PY314-S02`'s AC 3, made structural.** `None` is not an empty selection:
        it means "nothing sweeps this collector", and `collectors/sweep.py` refuses
        to dispatch such a collector **by name** rather than skipping it quietly. So
        a beat entry that named this collector would fail loudly at the first tick,
        and there is no state in which a schedule silently runs verification across
        the inventory.

        An empty iterable would have been the other reading of the story's "does not
        exist for this collector or answers empty", and it is the weaker one: it says
        "the selection ran and matched nothing", which is a *successful sweep of
        nothing* and would leave a dispatch enqueueing zero packages every tick
        forever, looking exactly like a selection whose query had quietly stopped
        matching. `None` says the sweep was never this collector's mechanism.

        Declared rather than inherited, even though the base's default answers `None`
        already: AC 3 is an acceptance criterion, and a criterion satisfied by not
        writing anything is one the next reader has no way to see was decided.

        Returns:
            `None`, always.

        """
        return None

    def inapplicability(self, *, package_id: int) -> str:
        """Say whether building this package is a question at all, from what identity recorded.

        Args:
            package_id: The package being verified, by the integer primary key
                `CPM-AD-3` fixes.

        Returns:
            The reason the question does not apply -- a `release_ecosystem` mapping
            recorded `not_applicable`, and nothing else -- or the empty string, which
            covers both "the question applies" and "identity has not decided", the
            second of which `source_for` refuses.

        """
        # A new run: forget the last one's locator and identity, so neither is
        # answered from a package this instance verified before -- or from this
        # package as it was before a resolution changed it.
        self._locator = ""
        self._identity = None
        self._identity_package = None
        identity = self._release_identity(package_id)
        return "" if identity is None else inapplicability_of(identity)

    def source_for(self, *, package_id: int) -> str:
        """Return the locator this collector hands the declared execution backend.

        Args:
            package_id: The package being verified.

        Returns:
            The package's locator. Remembered on the instance as well as returned --
            see `_locator`.

        Raises:
            Py314VerificationIdentityError: When the package has no
                `release_ecosystem` mapping row; when the mapping is `unknown`,
                `error` or `not_found`; or when it is established and names no purl.
                Every one of those is identity having established **nothing**, and
                the message says the question is unanswered rather than inapplicable.
                A `not_applicable` mapping never reaches here: `inapplicability`
                answers it first.

        """
        identity = self._release_identity(package_id)
        if identity is None:
            message = (
                f"package {package_id} has no release_ecosystem mapping row, so identity has recorded nothing "
                f"about where it is released and there is no artifact to ask a backend to build. "
                f"{IDENTITY_UNRESOLVED_DETAIL}"
            )
            raise Py314VerificationIdentityError(message)
        if not asks_about(identity):
            message = (
                f"package {package_id}'s release_ecosystem mapping is {identity.outcome!r} with "
                f"primary_purl={identity.primary_purl!r}, and this collector asks a backend to build a package "
                f"only when the mapping is {ESTABLISHED!r} and names one. {IDENTITY_UNRESOLVED_DETAIL}, so the "
                f"run is refused rather than recorded as a build nobody ran (CPM-FR-1) and emphatically rather "
                f"than recorded {OutcomeState.NOT_APPLICABLE.value!r}, which only identity may establish."
            )
            raise Py314VerificationIdentityError(message)
        self._locator = package_locator(identity.primary_purl)
        return self._locator

    def translate(self, payload: Payload, *, package_id: int, observed_at: datetime) -> Sequence[AppendOnlyModel]:
        """Turn one backend answer into the one verification result it is worth.

        One row and never none: the base reads an empty translation as a parser that
        no longer matches its source.

        Args:
            payload: What the backend said, recorded. Reached only for an execution
                the backend answered -- an unobtainable artifact and a backend that
                raised are the base's to record.
            package_id: The package the verification was about.
            observed_at: The instant to stamp the row with, from the injected clock.
                The base refuses a row stamped with anything else.

        Returns:
            One unsaved `PythonVerificationResult`.

        Raises:
            Py314VerificationDocumentError: When the answer cannot be read as a
                verification result. The base writes an `error` row and re-raises.

        """
        result = result_in(payload.body, source=payload.source)
        return [
            PythonVerificationResult(
                observed_at=observed_at,
                package_id=package_id,
                trace_id=current_trace_id(),
                source=payload.source,
                state=result.state,
                python_series=series_of(PYTHON_SERIES),
                platform=result.platform,
                architecture=result.architecture,
                log_reference=result.log_reference,
                detail=result.detail,
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

        Every fact about the execution is absent, and it has to be: a sentinel row is
        written for a run that produced no result, or for a question that was never
        asked, so there is no platform, no architecture and no log to name.
        `VERIFICATION_EVIDENCE_CONSTRAINT` is what makes that structural rather than a
        habit -- the three columns are blank on exactly the rows that are not
        determinate. What the row does carry is the Python series it was about,
        required of every row.

        **A `not_found` row carries a caveat the base cannot know to write.** The base
        reaches it when the backend says the artifact does not exist, which is an
        absence from wherever it fetches from rather than a package that fails to
        build -- and those are the two rows on this table a reader could most
        plausibly confuse.

        Args:
            state: `OutcomeState.ERROR`, `OutcomeState.NOT_FOUND` or
                `OutcomeState.NOT_APPLICABLE`, decided by the base.
            package_id: The package the run was about.
            observed_at: The instant to stamp the row with.
            detail: What happened, in words worth storing beside the state. Cleaned
                and bounded rather than trusted -- see `_safe_detail`: on the `error`
                path it carries a third party's exception message.

        Returns:
            One unsaved `PythonVerificationResult` carrying the state's value verbatim
            in `state` (`CPM-AD-24`).

        Raises:
            CollectorConfigurationError: When asked for a state this collector has no
                row shape for -- `ok`, which is not in this vocabulary at all;
                `unknown`, which no shipped path reaches; and the two verified
                verdicts, which are what an *execution* produced and which a sentinel
                path never has. Refused at the call rather than at the insert, which
                is where a row carrying a verdict and no platform would land, several
                frames from the call that was wrong.

        """
        # Written as three comparisons rather than as membership of a declared set,
        # for the reason `PythonReadinessCollector.sentinel_evidence` gives:
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
                f"{OutcomeState.NOT_APPLICABLE.value!r} only. A verified verdict is what an execution produced, "
                f"which a sentinel path never has -- and it would carry a platform, an architecture and a log "
                f"reference this path has no way to name."
            )
            raise CollectorConfigurationError(message)
        reason = _safe_detail(detail)
        if state is OutcomeState.NOT_FOUND:
            reason = f"{reason}: {NOT_OBTAINABLE_DETAIL}"
        return PythonVerificationResult(
            observed_at=observed_at,
            package_id=package_id,
            trace_id=current_trace_id(),
            source=self._locator,
            state=state.value,
            python_series=series_of(PYTHON_SERIES),
            platform="",
            architecture="",
            log_reference="",
            detail=reason,
        )

    def _release_identity(self, package_id: int) -> ReleaseIdentity | None:
        """Return what resolution recorded about this package's release ecosystem.

        The one database read in this module, and it reads `identity` -- the only
        application a collector may read (`CPM-AD-7`). One query, joining the mapping
        row to the one column that mapping owns and this collector needs.

        Args:
            package_id: The package being verified.

        Returns:
            The identity, or `None` when no `release_ecosystem` mapping row exists for
            the package -- which is also what a package with no identity row at all
            produces, and the two are refused together.

        """
        if self._identity_package != package_id:
            recorded = (
                PackageMapping.objects.filter(package_id=package_id, kind=MappingKind.RELEASE_ECOSYSTEM.value)
                .values_list("outcome", "package__primary_purl")
                .first()
            )
            self._identity = None if recorded is None else ReleaseIdentity(*recorded)
            self._identity_package = package_id
        return self._identity
