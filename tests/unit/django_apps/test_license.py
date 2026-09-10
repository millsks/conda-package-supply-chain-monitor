"""What the licence collector declares, what a channel document means, and what this product will not normalize.

`CPM-FR-13` is several questions and only the last needs a run. The declaration
rule, the locator, the reader that turns a channel document into a stated licence,
and the normalizer that turns a stated licence into an SPDX expression are all pure
functions of data, and all are here with no database, no socket and no clock
(`CPM-AD-27`). What needs a run -- the rows, several channels disagreeing, the two
columns side by side, the constraints the database enforces, the ledger and the
dispatch's selection -- is in `tests/integration/django_apps/test_license.py`.

**The vocabulary is asserted here first, and that is deliberate.**
`CPM-SECURITY-S01` shipped its sibling table with `ok` as the value meaning "this
package has a vulnerability" and two reviewers caught it independently. On a
licence table the same mistake reads worse still -- `ok` says "this licence is
fine", which is the compliance verdict AC 2 forbids in as many words -- so the case
that the determinate value is not the one the shared order ranks best is written
before the collector rather than after the review.

**The refusals are asserted as loudly as the recognitions.** Half of what
`collectors/spdx.py` is for is the licences it will *not* normalize: `BSD` alone is
two-clause or three-clause and the difference is a legal obligation, so every one
of the ambiguous family names has a case saying it reaches a reviewer intact.

No database, no network: nothing here saves a row, no queryset is evaluated, and
every payload is a literal.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.conf import settings
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan
from opentelemetry.trace import SpanContext
from opentelemetry.trace import TraceFlags

from conda_sentinel.collectors import conda_package as conda_package_module
from conda_sentinel.collectors import license as license_module
from conda_sentinel.collectors.agent import USER_AGENT
from conda_sentinel.collectors.license import ABSENT_FROM_CHANNEL_DETAIL
from conda_sentinel.collectors.license import CHANNELS_SETTING
from conda_sentinel.collectors.license import COLLECTOR_NAME
from conda_sentinel.collectors.license import LICENSE_CACHE_TTL
from conda_sentinel.collectors.license import LICENSE_CADENCE
from conda_sentinel.collectors.license import LICENSE_DISPATCH_OFFSET
from conda_sentinel.collectors.license import LICENSE_FIELD
from conda_sentinel.collectors.license import LICENSE_FRESHNESS_TARGET
from conda_sentinel.collectors.license import LICENSE_HEADERS
from conda_sentinel.collectors.license import LICENSE_OBSERVATION_WINDOW
from conda_sentinel.collectors.license import LICENSE_RATE_LIMIT
from conda_sentinel.collectors.license import LICENSE_RETRIES
from conda_sentinel.collectors.license import LICENSE_TIMEOUT
from conda_sentinel.collectors.license import MAX_MONITORED_CHANNELS
from conda_sentinel.collectors.license import MAX_SENTINEL_DETAIL_CHARACTERS
from conda_sentinel.collectors.license import NO_LICENSE_FIELD_DETAIL
from conda_sentinel.collectors.license import NO_LICENSE_STATED_DETAIL
from conda_sentinel.collectors.license import NOTHING_MONITORED
from conda_sentinel.collectors.license import SHORTENED_DETAIL
from conda_sentinel.collectors.license import TOLERATED_MISSED_RUNS
from conda_sentinel.collectors.license import UNNORMALIZABLE_LICENSE_DETAIL
from conda_sentinel.collectors.license import UNREAD_CHANNEL_DETAIL
from conda_sentinel.collectors.license import UNRECOGNISED_LICENSE_DETAIL
from conda_sentinel.collectors.license import ChannelLicense
from conda_sentinel.collectors.license import LicenseChannelError
from conda_sentinel.collectors.license import LicenseCollector
from conda_sentinel.collectors.license import LicenseDocumentError
from conda_sentinel.collectors.license import channel_license
from conda_sentinel.collectors.license import declaration_fault
from conda_sentinel.collectors.license import monitored_channels
from conda_sentinel.collectors.license import package_locator
from conda_sentinel.collectors.license import stated_license
from conda_sentinel.collectors.models import LicenseFinding
from conda_sentinel.collectors.outcomes import LICENSE_ERROR
from conda_sentinel.collectors.outcomes import LICENSE_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import LICENSE_NOT_FOUND
from conda_sentinel.collectors.outcomes import LICENSE_UNKNOWN
from conda_sentinel.collectors.outcomes import NORMALIZED
from conda_sentinel.collectors.outcomes import NORMALIZED_MEMBER
from conda_sentinel.collectors.outcomes import LicenseOutcome
from conda_sentinel.collectors.spdx import OPERATORS
from conda_sentinel.collectors.spdx import RECOGNISED_LICENSES
from conda_sentinel.collectors.spdx import SPELLINGS
from conda_sentinel.collectors.spdx import DetectionMethod
from conda_sentinel.collectors.spdx import LicenseNormalizationError
from conda_sentinel.collectors.spdx import Normalized
from conda_sentinel.collectors.spdx import normalize
from conda_sentinel.collectors.tasks import COLLECT_LICENSE_TASK_NAME
from conda_sentinel.collectors.tasks import collect_license
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.collection import CONDITIONAL_HEADERS
from conda_sentinel.core.collection import CollectorConfigurationError
from conda_sentinel.core.ledger import TRACE_ID_FORMAT
from conda_sentinel.core.outcomes import SENTINEL_MEMBERS
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.outcomes import OutcomeVocabularyError
from conda_sentinel.core.outcomes import aggregate
from conda_sentinel.core.outcomes import verify_sentinels
from conda_sentinel.core.queues import Queue
from conda_sentinel.core.queues import queue_for
from conda_sentinel.core.transport import DEFAULT_RETRIES
from conda_sentinel.core.transport import MAX_TIMEOUT
from conda_sentinel.core.transport import TransportError
from conda_sentinel.core.transport import worst_case_call_seconds
from tests.clocks import FIXED_INSTANT
from tests.collectors import ScriptedTransport
from tests.collectors import recorded_payload
from tests.source_scan import SRC_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from conda_sentinel.core.transport import Payload

#: The two modules this file's source sweeps are about, relative to `src/`.
LICENSE_MODULE: Final[str] = "django_apps/conda_sentinel/collectors/license.py"
SPDX_MODULE: Final[str] = "django_apps/conda_sentinel/collectors/spdx.py"

#: The identity model this collector reads, the evidence model it may not read,
#: and the write methods it may not reach for on any of them.
#:
#: `CPM-AD-7` says a collector "reads only `identity`" and never reads another
#: collector's evidence table. This collector reads the same *document*
#: `collectors/conda_package.py` reads, for a different fact, which is exactly the
#: shape a reviewer would expect to find shortcut through
#: `conda_package_snapshots` -- so the sweep names that model and asserts it is
#: absent.
PACKAGE_MODEL_NAME: Final[str] = "Package"
A_SIBLINGS_EVIDENCE_MODEL: Final[str] = "CondaPackageSnapshot"
WRITE_METHODS: Final[frozenset[str]] = frozenset(
    {
        "abulk_create",
        "acreate",
        "adelete",
        "asave",
        "aupdate",
        "bulk_create",
        "bulk_update",
        "create",
        "delete",
        "get_or_create",
        "save",
        "update",
        "update_or_create",
        # The three the append-only base enumerates as the paths that reach a table
        # without constructing an instance, so `save()` cannot see them.
        "_raw_delete",
        "raw",
        "_base_manager",
    },
)

#: The package the cases ask about, the channels they declare, and the locator the
#: first pair produces. The locator is written out rather than composed from the
#: module's own constants, because one assembled the same way twice would agree
#: with itself however wrong it was.
A_NAME: Final[str] = "numpy"
A_CHANNEL: Final[str] = "conda-forge"
ANOTHER_CHANNEL: Final[str] = "bioconda"
THE_LOCATOR: Final[str] = "https://api.anaconda.org/package/conda-forge/numpy"
THE_OTHER_LOCATOR: Final[str] = "https://api.anaconda.org/package/bioconda/numpy"

#: What the channels state, and what this product records.
A_LICENSE: Final[str] = "MIT"
A_SPELLING: Final[str] = "Apache 2.0"
ITS_IDENTIFIER: Final[str] = "Apache-2.0"
AN_EXPRESSION: Final[str] = "MIT OR Apache-2.0"
AN_UNRECOGNISED_LICENSE: Final[str] = "BSD"

#: The ambiguous spellings this product deliberately refuses, one per reason.
#: `BSD` is two-clause or three-clause; `GPL` and `LGPL` name no version and no
#: `-only`/`-or-later` disposition; `Apache` names no version; `Other`, `Public
#: Domain` and `See LICENSE file` are not licences at all.
#:
#: **The versioned GNU spellings are the half that matters most, and they are the
#: ones this table used to resolve.** `GPL-2.0`, `GPLv3`, `lgpl-2.1` and `agplv3`
#: each state a version and no disposition, which is exactly the criterion the two
#: bare family names above are refused by -- and until `CPM-SECURITY-S03`'s review
#: every one of them produced a *determinate* row naming the `-only` variant. A
#: table holding only bare family names could not fail this case: those are
#: trivially absent. These are the spellings a reader would expect to find, so
#: their absence is the assertion.
#:
#: `psf` is here for the neighbouring reason: it names `Python-2.0` -- the CPython
#: licence, which is what a conda channel almost always means -- or `PSF-2.0`, and
#: a spelling that could mean two is a review item by this module's own rule.
#: `freebsd` is `BSD-2-Clause-Views` rather than `BSD-2-Clause` and carries an extra
#: clause, so resolving it recorded a licence with one fewer obligation than the one
#: stated.
#:
#: Every one of these is really stated on conda channels, which is why they are a
#: named table rather than an afterthought.
AMBIGUOUS_LICENSES: Final[tuple[str, ...]] = (
    "BSD",
    "GPL",
    "LGPL",
    "Apache",
    "Other",
    "Public Domain",
    "See LICENSE file",
    "GPL-2.0",
    "GPLv2",
    "GPL v2",
    "GPL-3.0",
    "GPLv3",
    "GPL v3",
    "LGPL-2.1",
    "LGPLv2.1",
    "LGPL-3.0",
    "LGPLv3",
    "AGPL-3.0",
    "AGPLv3",
    "psf",
    "freebsd",
)

#: A primary key the cases that need one use. This tier never reads a row.
A_PACKAGE: Final[int] = 11

#: The sentence only the `304` branch produces. Written out rather than imported,
#: because what it guards is the branch existing at all: an unconditional request
#: answered `304` has no body behind it, so a payload left to fall through reads as
#: a document that is not JSON -- the same state and the same shared detail, over a
#: problem the source does not have.
NOT_MODIFIED_SENTENCE: Final[str] = "answered that nothing had changed, to an unconditional request"

#: How much of the inherited soft limit one whole *collection* may spend -- three
#: quarters, so the claim is "with room for the ledger writes around it" rather
#: than "by a hair". This collector makes up to `MAX_MONITORED_CHANNELS` calls, so
#: the figure is the product rather than one call.
SOFT_LIMIT_SHARE: Final[float] = 0.75

#: What `collectors/conda_package.py` declares against the same host, which is the
#: comparison worth making: the two collectors read `api.anaconda.org` on the same
#: daily tick and each spends its own allowance.
A_SIBLINGS_COURTESY_BOUND: Final[int] = 30

#: The counts the cases assert against, one named constant per concept, because
#: `PLR2004` is right about a bare number in an assertion.
TWO_OPERATORS: Final[int] = 2
FOUR_SENTINELS: Final[int] = 4
FIVE_VALUES: Final[int] = 5
THREE_METHODS: Final[int] = 3

#: What one collection really sends against `api.anaconda.org` at the declared
#: ceiling: four channels, each a call plus its retry. Written out rather than
#: recomputed, so the case asserting it is asserting a number a reader can compare
#: with `docs/conda-sentinel/operations.md` rather than an expression that agrees with itself.
EIGHT_REQUESTS_A_COLLECTION: Final[int] = 8

#: A valid trace context the correlation cases run inside. The values are the W3C
#: specification's own examples, which is what `tests/unit/django_apps/test_run_ledger.py`
#: uses for the same purpose.
A_TRACE_ID: Final[int] = 0x4BF92F3577B34DA6A3CE929D0E0E4736
A_SPAN_ID: Final[int] = 0x00F067AA0BA902B7

#: The marker the document builder treats as "the channel did not send this field
#: at all", as distinct from `None`, which is an explicit JSON `null`.
OMITTED: Final[object] = object()


def _document(license_value: object = A_LICENSE, **extra: object) -> str:
    """Return the body a channel would serve for one package.

    Args:
        license_value: What the channel states for `license`, or `OMITTED` to leave
            the field out entirely.
        **extra: Any further top-level fields the channel states. The real document
            carries many, and a reader that refused them would refuse every honest
            answer.

    Returns:
        The JSON body.

    """
    stated: dict[str, object] = {"name": A_NAME, "latest_version": "2.1.3", **extra}
    if license_value is not OMITTED:
        stated[LICENSE_FIELD] = license_value
    return json.dumps(stated)


def _license_module() -> Path:
    """Return the collector module's own source file.

    Returns:
        Its path under `src/`.

    """
    return SRC_ROOT / LICENSE_MODULE


def _spdx_module() -> Path:
    """Return the normalization module's own source file.

    Returns:
        Its path under `src/`.

    """
    return SRC_ROOT / SPDX_MODULE


def _shortest_spelling(identifier: str, others: tuple[str, ...]) -> int:
    """Return the length of the shortest way this product recognises one licence.

    Args:
        identifier: The SPDX identifier, which is always recognised under its own
            name.
        others: The other spellings the table lists.

    Returns:
        The character count of the shortest of them.

    """
    return min(len(spelling) for spelling in (identifier, *others))


def _declared_names(module: Path) -> set[str]:
    """Return every name a module declares or reaches for, ignoring its prose.

    A text search over the source cannot make this claim: both modules say in as
    many words that they record no compliance verdict, and the sentence explaining
    the decision contains every word the decision forbids. What is swept instead is
    the *code* -- definitions, references, attributes, parameters and keywords --
    which is where a column, a constant or a vocabulary member would appear.

    Args:
        module: The source file to sweep.

    Returns:
        Every identifier the module's own code mentions.

    """
    declared: set[str] = set()
    for node in ast.walk(parse(module)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            declared.add(node.name)
        elif isinstance(node, ast.Name):
            declared.add(node.id)
        elif isinstance(node, ast.Attribute):
            declared.add(node.attr)
        elif isinstance(node, ast.arg) or (isinstance(node, ast.keyword) and node.arg is not None):
            declared.add(node.arg)
    return declared


def _column(field: str) -> int:
    """Return how wide one of `license_findings`' text columns is.

    Read off the model rather than restated, so a case asserting a relation between
    two widths is asserting about the table rather than about two numbers copied
    here.

    Args:
        field: The column's name.

    Returns:
        Its `max_length`.

    """
    width = LicenseFinding._meta.get_field(field).max_length  # noqa: SLF001 - Django's own public-by-convention API
    assert width is not None
    return width


# ---------------------------------------------------------------------------
# The vocabulary: what a determinate licence row may and may not say.
# ---------------------------------------------------------------------------


def test_the_determinate_value_is_not_the_one_the_shared_order_ranks_best() -> None:
    """`CPM-SECURITY-S03`'s whole reason for composing a vocabulary rather than taking `OutcomeState`.

    On a licence table `ok` reads as "this licence is fine", which is a compliance
    verdict AC 2 forbids this collector from making and which `CPM-FR-18` gives to a
    policy that does not exist yet. `CPM-AD-24` carries a state's value verbatim onto
    every read surface, so a table using `ok` would render every recognised licence
    -- a copyleft one, a commercial one -- as the clean ones.

    Asserted as an inequality with `ok` rather than an equality with `normalized`,
    because the property is the *difference*: a later rename that kept the meaning
    is fine and a value that drifted back to `ok` is not.
    """
    assert OutcomeState.OK.value != NORMALIZED
    assert OutcomeState.OK.value not in {member.value for member in LicenseOutcome}
    assert NORMALIZED_MEMBER == ("NORMALIZED", NORMALIZED)


def test_the_vocabulary_carries_the_four_sentinels_by_construction_and_one_verdict() -> None:
    """`outcome_type` supplies the sentinels; this story supplies exactly one determinate member.

    The sentinels are asserted by *name and value* through `core`'s own checker
    rather than by a literal table here: a type spelling `NOT_APPLICABLE` but
    valuing it `n/a` would satisfy a `hasattr` check and write a value no policy
    recognises.
    """
    verify_sentinels(LicenseOutcome)

    values = {member.value for member in LicenseOutcome}

    assert len(values) == FIVE_VALUES
    assert values == {value for _, value in SENTINEL_MEMBERS} | {NORMALIZED}
    assert len(SENTINEL_MEMBERS) == FOUR_SENTINELS


def test_the_sentinels_this_module_names_are_the_composed_types_own() -> None:
    """Reached through `LicenseOutcome` rather than across to `OutcomeState`.

    A column's values must be its own choices, and the two are the same strings by
    construction -- which is what makes `sentinel_evidence` able to write
    `state.value` verbatim (`CPM-AD-24`). Asserted rather than assumed.
    """
    assert OutcomeState.UNKNOWN.value == LICENSE_UNKNOWN
    assert OutcomeState.ERROR.value == LICENSE_ERROR
    assert OutcomeState.NOT_FOUND.value == LICENSE_NOT_FOUND
    assert OutcomeState.NOT_APPLICABLE.value == LICENSE_NOT_APPLICABLE


def test_the_vocabulary_declares_no_precedence_so_a_reducer_refuses_it_outright() -> None:
    """No function ranks a licence, and `core.outcomes.aggregate` says so loudly.

    `CPM-SECURITY-S05`'s licence policy is the first consumer of this table and does
    not exist, so an order declared now would be data nothing reads and the next
    reader would take it for a ranking this product applies somewhere. Until then a
    caller that reduced these rows without deciding is told.
    """
    with pytest.raises(OutcomeVocabularyError, match="has no rank"):
        aggregate([NORMALIZED])

    # The sentinels still rank, so the refusal is about the determinate value rather
    # than about the vocabulary being unrecognised wholesale.
    assert aggregate([LICENSE_UNKNOWN, OutcomeState.NOT_APPLICABLE.value]) is OutcomeState.UNKNOWN


def test_the_detection_method_is_deliberately_not_an_outcome_type() -> None:
    """`CPM-AD-5` governs *derived statuses*, and how a value was established is not one.

    The precedent is `MatchConfidence`: a plain `TextChoices` in a leaf module,
    with a docstring saying why. Composing this from `OutcomeState` would make
    `unknown` and `not_found` things a normalization step could claim about itself.
    """
    with pytest.raises(OutcomeVocabularyError):
        verify_sentinels(DetectionMethod)

    assert len(DetectionMethod.choices) == THREE_METHODS
    assert {member.value for member in DetectionMethod}.isdisjoint({value for _, value in SENTINEL_MEMBERS})


# ---------------------------------------------------------------------------
# The declarations.
# ---------------------------------------------------------------------------


def test_the_collector_declares_every_value_the_base_checks() -> None:
    """All nine, written out on the class and carrying the module's own constants.

    Compared by *value* rather than by presence, for the reason the six sibling
    collectors' cases give: a class attribute rebound to the wrong constant declares
    nine names and behaves like something nobody wrote down.
    """
    declared = vars(LicenseCollector)

    assert LicenseCollector.name == COLLECTOR_NAME
    assert LicenseCollector.evidence_model is LicenseFinding
    assert LicenseCollector.observation_window == LICENSE_OBSERVATION_WINDOW
    assert LicenseCollector.timeout == LICENSE_TIMEOUT
    assert LicenseCollector.retries == LICENSE_RETRIES
    assert LicenseCollector.rate_limit == LICENSE_RATE_LIMIT
    assert LicenseCollector.headers == LICENSE_HEADERS
    assert LicenseCollector.freshness_target == LICENSE_FRESHNESS_TARGET
    assert LicenseCollector.response_cache_ttl == LICENSE_CACHE_TTL
    assert {
        "name",
        "evidence_model",
        "observation_window",
        "timeout",
        "retries",
        "rate_limit",
        "headers",
        "freshness_target",
        "response_cache_ttl",
    } <= set(declared)


def test_the_cadence_is_the_daily_one_the_prd_gives_the_security_signals() -> None:
    """`CPM-NFR-2` puts security at daily, with no range to choose inside.

    Asserted against the slow end of the *currency* range as well, so a cadence
    quietly lengthened to match the feedstock collector -- on the reasoning that a
    licence changes rarely -- fails here rather than passing by agreeing with a
    constant beside it. A licence changing rarely is why the day it changes matters.
    """
    assert timedelta(days=1) == LICENSE_CADENCE
    assert timedelta(days=7) > LICENSE_CADENCE


def test_the_freshness_target_is_the_arithmetic_open_question_7_settled() -> None:
    """`cadence x (1 + tolerated_missed_runs)`, which for this signal class is two days.

    `core/freshness.py` reports stale when `observed_at < now - target`, so a target
    *equal* to the cadence makes every package read stale at exactly the moment its
    next run is due, without a single collection having failed.
    """
    assert LICENSE_FRESHNESS_TARGET == LICENSE_CADENCE * (1 + TOLERATED_MISSED_RUNS)
    assert timedelta(days=2) == LICENSE_FRESHNESS_TARGET
    assert LICENSE_FRESHNESS_TARGET > LICENSE_CADENCE


def test_the_observation_window_cannot_suppress_a_scheduled_run() -> None:
    """Shorter than the cadence, which is the property rather than the halving."""
    assert LICENSE_OBSERVATION_WINDOW < LICENSE_CADENCE
    assert timedelta(0) < LICENSE_OBSERVATION_WINDOW


def test_the_dispatch_offset_is_shorter_than_the_cadence_it_phases() -> None:
    """A countdown longer than the interval would have every tick overtake the last one.

    The offset is what keeps this sweep and `CPM-CURRENCY-S04`'s off one instant
    against the same host; an offset at or above the cadence would stop being a
    phase and start being a second schedule.
    """
    assert timedelta(0) < LICENSE_DISPATCH_OFFSET < LICENSE_CADENCE


def test_the_worst_collection_this_declaration_permits_fits_inside_the_inherited_soft_limit() -> None:
    """`MAX_MONITORED_CHANNELS` retried calls, reconciled against the settings module's own limit.

    The product rather than one call, which is the arithmetic that matters here: the
    transport mounts its retry policy on the *session*, so every call this collector
    issues -- the base's and the bounded ones -- is retried, and a declaration whose
    worst case exceeds the soft limit is a task the platform kills before it writes
    anything.

    Read from the settings module rather than repeated here, so lowering the limit
    there fails this rather than passing quietly.
    """
    worst_case = MAX_MONITORED_CHANNELS * worst_case_call_seconds(timeout=LICENSE_TIMEOUT, retries=LICENSE_RETRIES)

    assert worst_case <= SOFT_LIMIT_SHARE * settings.CELERY_TASK_SOFT_TIME_LIMIT
    assert LICENSE_TIMEOUT <= MAX_TIMEOUT


def test_the_shared_retry_default_would_not_fit_which_is_why_the_budget_is_lower() -> None:
    """The anti-vacuity half of the case above: the ceiling is doing work.

    A retry budget is only a decision if the alternative fails, and the shared
    default is the alternative a reader would reach for. At four channels it does
    not fit the soft limit, which is what the lower declaration exists for.
    """
    assert LICENSE_RETRIES < DEFAULT_RETRIES

    shared_default = MAX_MONITORED_CHANNELS * worst_case_call_seconds(timeout=LICENSE_TIMEOUT, retries=DEFAULT_RETRIES)

    assert shared_default > settings.CELERY_TASK_SOFT_TIME_LIMIT


def test_the_declared_headers_carry_what_the_source_expects_and_nothing_conditional() -> None:
    """Headers reach a source only through the base (`CPM-AD-20`, `CPM-AD-27`).

    The JSON representation `stated_license` reads is asked for by name and the
    `User-Agent` is the one identity every collector shares. What is not declared is
    a validator, which the base composes from the response cache and refuses at
    construction.
    """
    lowered = {name.lower(): value for name, value in LICENSE_HEADERS.items()}

    assert lowered["user-agent"] == USER_AGENT
    assert lowered["accept"] == "application/json"
    assert set(lowered).isdisjoint({header.lower() for header in CONDITIONAL_HEADERS})


def test_the_declared_allowance_admits_the_one_charge_the_base_makes() -> None:
    """anaconda.org publishes no numeric ceiling, so this is a declared bound rather than a quoted one.

    Three things are worth pinning: the charge the base actually makes fits inside it
    -- an allowance smaller than `1 + retries` would refuse every call -- it is
    counted per minute, and it is no looser than the sibling that reads the same host
    on the same tick.

    **This is `1 + retries` and not the cost of a collection.** The name this case
    carried before said "a whole collection fits inside", which `30 >= 2` does not
    establish: a whole collection is `MAX_MONITORED_CHANNELS` calls. The case below
    is the one that pins that number.
    """
    assert LICENSE_RATE_LIMIT.calls >= 1 + LICENSE_RETRIES
    assert LICENSE_RATE_LIMIT.per == timedelta(minutes=1)
    assert LICENSE_RATE_LIMIT.calls <= A_SIBLINGS_COURTESY_BOUND


def test_a_whole_collection_issues_more_requests_than_the_allowance_is_ever_charged_for() -> None:
    """The real outbound cost, pinned as a number, and the undercount named as a number.

    The limiter is acquired **once** per `collect()`, before the first channel, and
    charged `1 + retries`. `_channel_instead` issues channels two onward from
    `translate`, after that charge -- so a four-channel declaration issues up to
    `MAX_MONITORED_CHANNELS * (1 + LICENSE_RETRIES)` requests against
    `api.anaconda.org` and is charged for two of them.

    That is the inherited defect `CPM-CURRENCY-S04` recorded against the same seam and
    `CPM-SECURITY-S03` restates against this module's copy of it; fixing it means
    reaching past the base's orchestration into the limiter, which belongs with the
    story that first sweeps at volume. What this case does is stop the arithmetic
    being *unstated*: a reader sizing an allowance gets the issued figure rather than
    the charged one, and the whole collection really does fit inside the declared
    thirty.
    """
    charged = 1 + LICENSE_RETRIES
    issued = MAX_MONITORED_CHANNELS * (1 + LICENSE_RETRIES)

    assert issued == EIGHT_REQUESTS_A_COLLECTION
    assert issued > charged
    assert LICENSE_RATE_LIMIT.calls >= issued


def test_a_remembered_document_is_revalidated_rather_than_replayed_blind() -> None:
    """The cache covers the base's one call and outlives the cadence, or it is inert.

    An entry that expired inside the cadence would be re-transferred on every
    scheduled run, which is a cache that costs a lookup and saves nothing. What is
    replayed is a body the channel itself has said is unchanged.
    """
    assert LICENSE_CACHE_TTL > LICENSE_CADENCE
    assert LicenseCollector.response_cache_ttl == LICENSE_CACHE_TTL


def test_the_collector_is_constructed_from_its_declarations_alone() -> None:
    """The base's nine refusals, run against the real class rather than a fixture."""
    collector = LicenseCollector(clock=FixedClock(instant=FIXED_INSTANT))

    try:
        assert collector.request_cost == 1 + LICENSE_RETRIES
        assert LICENSE_RATE_LIMIT.calls >= collector.request_cost
    finally:
        collector.close()


def test_the_task_name_routes_to_the_collect_queue_and_is_the_one_the_worker_registers() -> None:
    """`core/queues.py`'s derived route table, and the decorator reconciled against the constant.

    A renamed constant with an unchanged decorator would route correctly here while
    the worker registered something else, and every scheduled dispatch would enqueue
    into nothing.
    """
    assert f"cpm.collect.{COLLECTOR_NAME}" == COLLECT_LICENSE_TASK_NAME
    assert queue_for(COLLECT_LICENSE_TASK_NAME) is Queue.COLLECT
    assert collect_license.name == COLLECT_LICENSE_TASK_NAME


# ---------------------------------------------------------------------------
# The declaration this collector reads, and what it refuses.
# ---------------------------------------------------------------------------


def test_the_setting_read_is_the_one_the_currency_story_established() -> None:
    """`CPM-CURRENCY-S04`'s declaration, restated rather than imported (`CPM-AD-7`).

    The two spellings are reconciled here, which is the whole point of restating a
    name: no collector imports another, so the guard against drift is a case rather
    than an import. `CPM_MONITORED_PLATFORMS` is asserted *absent* from this module's
    source, because a licence is not per platform and a collector that read a setting
    no branch of it needs would fail runs over a declaration about something else.
    """
    assert CHANNELS_SETTING == "CPM_MONITORED_CHANNELS"

    # The *constants* this module declares, rather than its prose: the module
    # docstring says in as many words that the platform setting is not read, and a
    # text search would fail on the sentence that explains the decision.
    spelled = {
        node.value
        for node in ast.walk(parse(_license_module()))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert CHANNELS_SETTING in spelled
    assert "CPM_MONITORED_PLATFORMS" not in spelled


def test_the_restated_constants_are_reconciled_against_the_collector_that_established_them() -> None:
    """Restating them is right; leaving nothing to compare them *to* is what was missing.

    `CPM-AD-7` forbids one collector importing another, so
    `CPM_MONITORED_CHANNELS`, the channel count, the segment grammar and the host are
    each spelled twice in this repository -- correctly. What a literal here cannot
    catch is the *other* spelling moving: if `CPM-CURRENCY-S04` renames the setting,
    the case above still passes, this collector's `getattr` falls to its `()` default,
    and it offers **zero packages for ever** -- indistinguishable from the
    unconfigured state, with no failed run and no failing case anywhere.

    A test may import both modules even though a collector may not, and this is the
    one place that permission is worth using: four comparisons, and every one of them
    is a silent-failure mode rather than a style point. The segment grammar is
    compared by its `pattern` rather than by the compiled object, which is not
    equality-comparable.
    """
    assert license_module.CHANNELS_SETTING == conda_package_module.CHANNELS_SETTING
    assert license_module.MAX_MONITORED_CHANNELS == conda_package_module.MAX_MONITORED_CHANNELS
    assert license_module.ANACONDA_API_HOST == conda_package_module.ANACONDA_API_HOST
    assert license_module._SEGMENT.pattern == conda_package_module._SEGMENT.pattern  # noqa: SLF001 - the two grammars


@pytest.mark.parametrize(
    "declared",
    ["conda-forge", None, 7, {"conda-forge"}],
    ids=["a-bare-string", "none", "a-number", "a-set"],
)
def test_a_declaration_of_the_wrong_shape_is_refused_rather_than_read(declared: object) -> None:
    """A `str` is a sequence of one-character strings, which is the case worth the function.

    `CPM_MONITORED_CHANNELS = "conda-forge"` read as a sequence is eleven channels
    named `c`, `o`, `n` and so on -- eleven locators, eleven rows a run, and nothing
    anywhere saying the declaration had been misread.
    """
    assert declaration_fault(declared)

    with pytest.raises(LicenseChannelError, match=CHANNELS_SETTING):
        monitored_channels(declared)


def test_an_empty_declaration_is_usable_in_shape_and_refused_at_run_time() -> None:
    """The distinction the boot refusal and the selection both rest on.

    An empty declaration is what *ships* -- PRD Open Question 4 leaves the choice to
    an operator -- so it must not be a component that will not start. What it is
    instead is a run that fails naming the setting, and a selection that offers
    nothing at all.
    """
    assert declaration_fault([]) == ""

    with pytest.raises(LicenseChannelError, match=CHANNELS_SETTING):
        monitored_channels([])


def test_a_declaration_is_normalised_before_duplicates_are_looked_for() -> None:
    """`Conda-Forge` beside `conda-forge` is one declaration written twice.

    Normalising after the duplicate check would accept them as two channels, ask one
    host twice, and write two rows for one observation.
    """
    assert monitored_channels([" Conda-Forge ", ANOTHER_CHANNEL]) == (A_CHANNEL, ANOTHER_CHANNEL)

    with pytest.raises(LicenseChannelError, match="twice"):
        monitored_channels(["Conda-Forge", A_CHANNEL])


@pytest.mark.parametrize(
    "entry",
    ["", "   ", "conda forge/../etc", "conda\\forge", ".", "..", "-leading", 7, None],
    ids=["empty", "blank", "separator", "backslash", "dot", "dotdot", "leading-dash", "a-number", "none"],
)
def test_an_entry_that_is_not_a_locator_segment_refuses_the_whole_declaration(entry: object) -> None:
    """Refused rather than encoded, and refused *whole* rather than narrowed.

    A locator built from a path-carrying segment would ask about nothing, or would be
    a path the source is entitled to resolve somewhere else. Reading the entries that
    happened to parse would record evidence about a set of channels nobody chose.
    """
    with pytest.raises(LicenseChannelError, match=CHANNELS_SETTING):
        monitored_channels([entry])


def test_a_channel_wider_than_its_column_is_refused_where_it_enters() -> None:
    """`max_length` is enforced by PostgreSQL and ignored by SQLite (`R-5`).

    Measured against the model's own column rather than against a number here, so a
    widened column moves the bound rather than leaving this case asserting the old
    one.
    """
    width = _column("channel")

    assert monitored_channels(["c" * width]) == ("c" * width,)

    with pytest.raises(LicenseChannelError, match="truncated"):
        monitored_channels(["c" * (width + 1)])


def test_more_channels_than_one_collection_can_ask_about_are_refused_rather_than_truncated() -> None:
    """The ceiling is a *time* bound, and reading some of them silently is worse than reading none."""
    permitted = tuple(f"channel-{index}" for index in range(MAX_MONITORED_CHANNELS))

    assert monitored_channels(list(permitted)) == permitted

    with pytest.raises(LicenseChannelError, match=str(MAX_MONITORED_CHANNELS)):
        monitored_channels([*permitted, "one-too-many"])


def test_the_locator_names_the_channels_own_package_document() -> None:
    """One document per channel, and the same one `CPM-CURRENCY-S04` reads -- asked independently.

    `CPM-AD-7` forbids reading that collector's evidence table, so this collector
    asks the source itself. The spelling is pinned here because a locator assembled
    the same way twice would agree with itself however wrong it was.
    """
    assert package_locator(A_CHANNEL, A_NAME) == THE_LOCATOR
    assert package_locator(ANOTHER_CHANNEL, A_NAME) == THE_OTHER_LOCATOR
    assert package_locator("Conda-Forge", "NumPy") == THE_LOCATOR


def test_a_package_name_that_is_not_a_segment_refuses_the_locator() -> None:
    """The same grammar the channels pass, applied to the name a channel is asked about."""
    with pytest.raises(LicenseChannelError, match="package name"):
        package_locator(A_CHANNEL, "../../etc/passwd")


# ---------------------------------------------------------------------------
# What this product recognises, and what it refuses.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expression"),
    [
        ("MIT", "MIT"),
        ("mit", "MIT"),
        ("  MIT  ", "MIT"),
        ("The MIT License", "MIT"),
        ("Apache 2.0", "Apache-2.0"),
        ("apache license, version 2.0", "Apache-2.0"),
        ("BSD-3", "BSD-3-Clause"),
        ("new bsd", "BSD-3-Clause"),
        ("BSD-2", "BSD-2-Clause"),
        ("GPL-3.0-only", "GPL-3.0-only"),
        ("gpl-3.0-or-later", "GPL-3.0-or-later"),
        ("LGPL-2.1-only", "LGPL-2.1-only"),
        ("AGPL-3.0-or-later", "AGPL-3.0-or-later"),
        ("mozilla public license 2.0", "MPL-2.0"),
        ("PSF-2.0", "PSF-2.0"),
        ("Python-2.0", "Python-2.0"),
        ("cc0", "CC0-1.0"),
        ("The  MIT  License", "MIT"),
    ],
)
def test_a_recognised_spelling_normalizes_to_one_identifier(raw: str, expression: str) -> None:
    """AC 1's second row: the raw string is left alone and the identifier appears beside it.

    Case-insensitive and whitespace-collapsing, because a channel that pads its
    `license` field with a doubled space is still stating the MIT licence and a table
    carrying every whitespace variant would be a table nobody could read.

    **The GNU entries are here under their identifiers and under nothing else.**
    `GPL-3.0-only` and `GPL-3.0-or-later` are two licences and each is recognised;
    `GPLv3` is neither of them and is in `AMBIGUOUS_LICENSES` below.
    """
    reading = normalize(raw)

    assert reading.expression == expression
    assert reading.unrecognised == ()
    assert reading.method in {member.value for member in DetectionMethod}


def test_the_identifier_stated_verbatim_is_told_apart_from_a_spelling_of_it() -> None:
    """`CPM-SM-2`'s "carries source", at the level a reviewer actually asks about.

    A channel that stated the SPDX identifier itself had nothing interpreted; one
    that stated `mit` had a table consulted. Both are determinate and the row says
    which, because "what did normalization do" is exactly AC 1's question.
    """
    assert normalize("MIT").method == DetectionMethod.SPDX_IDENTIFIER.value
    assert normalize("mit").method == DetectionMethod.RECOGNISED_SPELLING.value
    assert normalize("Apache 2.0").method == DetectionMethod.RECOGNISED_SPELLING.value


@pytest.mark.parametrize(
    ("raw", "expression"),
    [
        ("MIT OR Apache-2.0", "MIT OR Apache-2.0"),
        ("mit OR apache-2", "MIT OR Apache-2.0"),
        ("MIT AND BSD-3", "MIT AND BSD-3-Clause"),
        ("MIT OR Apache-2.0 OR BSD-3", "MIT OR Apache-2.0 OR BSD-3-Clause"),
    ],
)
def test_a_compound_expression_is_one_row_and_says_it_was_an_expression(raw: str, expression: str) -> None:
    """The matrix's compound row: normalized operand by operand, never split into two rows.

    `MIT OR Apache-2.0` is a single statement about a single package; splitting it
    would record two licences a reader could take for two separate grants. The method
    says it was an expression, which is the fact that keeps the single row honest.

    The *operands* still fold case -- `mit` is a spelling of `MIT` however it is
    written -- while the operator does not: see the case below.
    """
    reading = normalize(raw)

    assert reading.expression == expression
    assert reading.method == DetectionMethod.SPDX_EXPRESSION.value
    assert reading.unrecognised == ()


@pytest.mark.parametrize("family", AMBIGUOUS_LICENSES)
def test_an_ambiguous_family_name_is_refused_rather_than_guessed_at(family: str) -> None:
    """The half of `collectors/spdx.py` that matters most, and every one of these is really stated.

    `BSD` alone is two-clause or three-clause and the difference is whether an
    advertising clause binds; `GPL` names no version and no `-only`/`-or-later`
    disposition. A normalizer that picked one would write a permanent claim about
    somebody's legal obligations that nobody made.
    """
    reading = normalize(family)

    assert reading.expression == ""
    assert reading.method == ""
    assert reading.unrecognised
    assert family.casefold() not in SPELLINGS


@pytest.mark.parametrize(
    "raw",
    [
        "(MIT OR Apache-2.0) AND BSD-3-Clause",
        "Apache-2.0 WITH LLVM-exception",
        "Apache 2.0 OR MIT",
        "MIT OR",
        "MIT OR Apache-2.0 AND",
        "MIT NOR Apache-2.0",
        "MIT OR Frobnicate-1.0",
        "MIT or Apache-2.0",
        "MIT and Apache-2.0",
        "MIT OR Apache-2.0 AND BSD-3-Clause",
    ],
    ids=[
        "grouping",
        "with-exception",
        "a-multi-token-operand",
        "a-trailing-operator",
        "an-even-token-count",
        "an-unrecognised-operator",
        "an-unrecognised-operand",
        "a-lower-case-or",
        "a-lower-case-and",
        "mixed-operators",
    ],
)
def test_an_expression_this_product_cannot_read_whole_reaches_a_reviewer_intact(raw: str) -> None:
    """No partial normalization is ever written as if it were complete.

    Grouping needs a precedence this module would have to invent; `WITH` takes an
    exception identifier from a list it does not carry; a multi-token operand needs a
    guess about where the operand ends. Each of them reaches a reviewer whole, which
    is the only reading that cannot be wrong.

    **The last three were determinate before `CPM-SECURITY-S03`'s review.** A
    lower-case conjunction is prose at least as often as it is SPDX, and prose "A and
    B" usually means the package is offered under *either* -- SPDX `OR` -- while SPDX
    `AND` binds both sets of obligations at once, so folding the operator's case is a
    guess about legal obligations. And `MIT OR Apache-2.0 AND BSD-3-Clause` needs
    exactly the precedence the parenthesised form is refused for; reading the flat
    spelling while refusing the parenthesised one would refuse the spelling that
    announces the ambiguity and accept the one that hides it.
    """
    reading = normalize(raw)

    assert reading.expression == ""
    assert reading.method == ""
    assert reading.unrecognised


def test_an_unrecognised_expression_names_every_token_that_stopped_it() -> None:
    """A reviewer fixing one token and meeting the next is a reviewer this collector wasted a day of."""
    reading = normalize("Frobnicate-1.0 OR Widget-2.0")

    assert reading.unrecognised == ("Frobnicate-1.0", "Widget-2.0")


def test_a_blank_licence_normalizes_to_nothing_and_names_nothing() -> None:
    """ "The source stated none" is a different fact from "it stated something unreadable".

    Both are `unknown` rows, and the caller's `detail` is what keeps them apart -- so
    the normalizer answers with a blank pair naming no token rather than naming the
    empty string as something it could not read.
    """
    for blank in ("", "   ", "\t\n"):
        reading = normalize(blank)

        assert reading == Normalized(expression="", method="", unrecognised=())


def test_the_recognised_table_and_its_lookup_cannot_drift() -> None:
    """The lookup is derived from the readable list, which is the single-declaration rule applied to itself.

    Every identifier is recognised under its own name without the table repeating
    itself, and every spelling is folded -- so a case-variant written into the table
    would be a row that never matches anything and is worth failing over.
    """
    for identifier, others in RECOGNISED_LICENSES:
        assert SPELLINGS[identifier.casefold()] == identifier
        for spelling in others:
            assert SPELLINGS[spelling] == identifier, f"{spelling!r} is not folded"

    assert len({identifier for identifier, _ in RECOGNISED_LICENSES}) == len(RECOGNISED_LICENSES)


def test_the_operators_are_the_two_this_product_reads_and_with_is_deliberately_absent() -> None:
    """`WITH`'s right operand is an exception identifier from a list this module does not carry.

    Recognising the operator without the operands would produce an expression naming
    an exception nothing checked, which is the guess the whole module exists not to
    make.
    """
    assert {"AND", "OR"} == OPERATORS
    assert len(OPERATORS) == TWO_OPERATORS
    assert "WITH" not in OPERATORS


def test_the_normalized_column_is_wide_enough_for_anything_the_raw_column_can_hold() -> None:
    """The `_FEEDSTOCK_NAME_LENGTH` trap, avoided by measuring rather than by matching.

    Normalization *expands*: `bsd-3` is five characters and `BSD-3-Clause` is twelve.
    A normalized column merely equal to the raw one would leave a band of perfectly
    storable raw values whose expression can never be recorded, and the refusal would
    fire on those packages on every run for ever.

    Asserted as the relation against the shipped table rather than as the numbers, so
    a spelling added with a longer identifier fails here rather than at an insert.
    """
    widest = max(len(identifier) / _shortest_spelling(identifier, others) for identifier, others in RECOGNISED_LICENSES)

    assert _column("normalized_license") >= _column("raw_license") * widest


def test_a_normalization_result_that_half_claims_an_expression_is_refused_where_it_is_built() -> None:
    """The invariant `license_findings` enforces, applied before a row exists.

    The constraint fires at insert, inside `bulk_create`, with a message about a
    column and nothing about the branch that produced it -- and the second half is
    the one worth enforcing: a partly-normalized expression written as if it were
    complete is precisely what this story's contract forbids.
    """
    with pytest.raises(LicenseNormalizationError, match="method that produced it"):
        Normalized(expression="MIT", method="", unrecognised=())

    with pytest.raises(LicenseNormalizationError, match="expression it describes"):
        Normalized(expression="", method=DetectionMethod.SPDX_IDENTIFIER.value, unrecognised=())

    with pytest.raises(LicenseNormalizationError, match="complete expression"):
        Normalized(expression="MIT", method=DetectionMethod.SPDX_IDENTIFIER.value, unrecognised=("BSD",))


# ---------------------------------------------------------------------------
# The document, and the fact one channel earns.
# ---------------------------------------------------------------------------


def test_a_recognised_licence_earns_a_determinate_fact_carrying_both_columns() -> None:
    """AC 1: the raw string and the SPDX expression side by side, with the method named."""
    fact = channel_license(_document(A_LICENSE), channel=A_CHANNEL, source=THE_LOCATOR)

    assert fact.channel == A_CHANNEL
    assert fact.state == NORMALIZED
    assert fact.raw_license == A_LICENSE
    assert fact.normalized_license == A_LICENSE
    assert fact.detection_method == DetectionMethod.SPDX_IDENTIFIER.value
    assert fact.source == THE_LOCATOR
    assert fact.detail == ""


def test_a_licence_needing_normalization_leaves_the_raw_column_exactly_as_stated() -> None:
    """The matrix's second row, and the property AC 1 turns on: raw is never rewritten."""
    fact = channel_license(_document(A_SPELLING), channel=A_CHANNEL, source=THE_LOCATOR)

    assert fact.raw_license == A_SPELLING
    assert fact.normalized_license == ITS_IDENTIFIER
    assert fact.detection_method == DetectionMethod.RECOGNISED_SPELLING.value


def test_a_compound_expression_is_one_fact_saying_it_was_an_expression() -> None:
    """Never split into two facts, which would be two licences a reader could take for two grants."""
    fact = channel_license(_document(AN_EXPRESSION), channel=A_CHANNEL, source=THE_LOCATOR)

    assert fact.state == NORMALIZED
    assert fact.raw_license == AN_EXPRESSION
    assert fact.normalized_license == AN_EXPRESSION
    assert fact.detection_method == DetectionMethod.SPDX_EXPRESSION.value


def test_an_unrecognised_licence_is_unknown_with_the_raw_value_preserved() -> None:
    """AC 2, and the reason the constraint on this table is asymmetric.

    An `unknown` row carrying the raw string is a review item somebody can act on; an
    `unknown` row carrying nothing is an absence of information. And it is `unknown`
    rather than `not_found`, because `not_found` is an informative negative that on a
    licence table reads as *unrestricted*.
    """
    fact = channel_license(_document(AN_UNRECOGNISED_LICENSE), channel=A_CHANNEL, source=THE_LOCATOR)

    assert fact.state == LICENSE_UNKNOWN
    assert fact.raw_license == AN_UNRECOGNISED_LICENSE
    assert fact.normalized_license == ""
    assert fact.detection_method == ""
    assert UNRECOGNISED_LICENSE_DETAIL in fact.detail
    assert AN_UNRECOGNISED_LICENSE in fact.detail
    assert fact.state != LICENSE_NOT_FOUND


@pytest.mark.parametrize("stated", [None, "", "   "], ids=["null", "empty", "blank"])
def test_a_channel_that_states_no_licence_says_so_in_its_own_words(stated: object) -> None:
    """The matrix's "source states no licence" row: same state, a distinct reason.

    "The channel stated none" and "the channel stated something we will not
    normalize" are two different pieces of work for a reviewer, and `CPM-FR-6` is why
    they may not be folded into one sentence.

    The three inputs here are all the field being *present* and carrying nothing,
    which is a channel affirmatively stating no licence. The field being absent
    altogether is the case below and is deliberately not this one.
    """
    fact = channel_license(_document(stated), channel=A_CHANNEL, source=THE_LOCATOR)

    assert fact.state == LICENSE_UNKNOWN
    assert fact.raw_license == ""
    assert fact.detail == NO_LICENSE_STATED_DETAIL
    assert UNRECOGNISED_LICENSE_DETAIL not in fact.detail


def test_a_document_missing_the_field_entirely_says_that_rather_than_that_the_channel_stated_none() -> None:
    """The near miss `LicenseDocumentError`'s own docstring names, and it had been read the wrong way.

    `document.get(LICENSE_FIELD)` answers `None` for a field stated as `null` and for
    a field that is not there, and the two are opposite facts. If anaconda.org
    renames the field or wraps the body in an envelope, reading them as one records
    the *affirmative* claim "this channel states no license" for every package on
    every channel, permanently, with nothing failing anywhere -- which is precisely
    the honest-looking result this table must not manufacture.

    Both stay `unknown`, because a field this collector could not find is not a
    reason to fail a run; what differs is the reason, so a sweep of `detail` makes a
    field rename visible instead of invisible.
    """
    fact = channel_license(_document(OMITTED), channel=A_CHANNEL, source=THE_LOCATOR)

    assert fact.state == LICENSE_UNKNOWN
    assert fact.raw_license == ""
    assert fact.detail == NO_LICENSE_FIELD_DETAIL
    assert fact.detail != NO_LICENSE_STATED_DETAIL
    assert LICENSE_FIELD in fact.detail


def test_the_reader_ignores_the_rest_of_a_real_channel_document() -> None:
    """The document carries many fields and a reader that refused them would refuse every honest answer.

    Unlike the two security siblings, this collector reads a *third party's* document
    rather than a schema it defined, so an undefined-field refusal would be this
    module telling anaconda.org what to serve.
    """
    fact = channel_license(
        _document(A_LICENSE, license_family="MIT", summary="the fundamental package for array computing"),
        channel=A_CHANNEL,
        source=THE_LOCATOR,
    )

    assert fact.state == NORMALIZED
    assert fact.raw_license == A_LICENSE


def test_the_field_this_collector_reads_is_pinned_by_its_own_spelling() -> None:
    """Both tiers build their fixtures *from* the constant, so nothing pinned its value.

    Renaming `LICENSE_FIELD` to `"licence"` keeps the whole suite green -- every
    document a case builds is rebuilt around the new key -- while production records
    an `unknown` row for every package on every channel for ever: the honest-looking
    result this table must not manufacture. `ANACONDA_API_HOST` is already pinned this
    way by `THE_LOCATOR`, and this is the same guard for the other end of the read.

    So: the constant is asserted against its literal, and one document is built from a
    hard-coded `"license"` key rather than from the constant, which is what makes the
    reader and the source agree about a spelling neither of them chose alone.
    """
    assert LICENSE_FIELD == "license"

    from_the_source = json.dumps({"name": A_NAME, "latest_version": "2.1.3", "license": A_LICENSE})

    assert stated_license(from_the_source, source=THE_LOCATOR) == A_LICENSE
    assert channel_license(from_the_source, channel=A_CHANNEL, source=THE_LOCATOR).state == NORMALIZED


def test_only_the_licence_field_is_read_and_the_channels_own_family_is_not() -> None:
    """Recording `license_family` would be recording somebody else's classification beside our own."""
    assert stated_license(_document(A_LICENSE, license_family="GPL"), source=THE_LOCATOR) == A_LICENSE

    source = _license_module().read_text(encoding="utf-8")

    assert "license_family" not in source.replace("`license_family`", "")


@pytest.mark.parametrize(
    "body",
    ["not json at all", "[]", '"a string"', "7", b"\xff\xfe", None],
    ids=["not-json", "a-list", "a-string", "a-number", "bytes", "none"],
)
def test_an_unreadable_document_is_refused_rather_than_read_as_a_channel_stating_nothing(body: object) -> None:
    """The matrix's unreadable-document row, and the reason it is a refusal.

    Reading around a document whose shape has changed would record "this channel
    states no license" for a channel that stated one in a shape the reader skipped --
    an `unknown` row that looks exactly like an honest one.
    """
    with pytest.raises(LicenseDocumentError, match=THE_LOCATOR):
        stated_license(body, source=THE_LOCATOR)


def test_a_licence_of_the_wrong_type_is_refused_by_name() -> None:
    """A licence this collector cannot even attempt to read is different from one it read and refused."""
    with pytest.raises(LicenseDocumentError, match="rather than a string"):
        stated_license(_document(["MIT"]), source=THE_LOCATOR)


def test_a_document_over_the_bound_is_refused_before_it_reaches_the_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the bound protects is the parse, which is where a worker's soft limit would be spent.

    The real ceiling is lowered for the case rather than met, so the suite does not
    build eight mebibytes to prove a comparison.
    """
    small = 64
    monkeypatch.setattr(license_module, "MAX_DOCUMENT_CHARACTERS", small)

    with pytest.raises(LicenseDocumentError, match=str(small)):
        stated_license(_document(A_LICENSE, summary="x" * small), source=THE_LOCATOR)


def test_a_licence_wider_than_its_column_is_refused_rather_than_truncated() -> None:
    """The matrix says so in as many words: a truncated licence is a different licence.

    Measured against the model's own column, and asserted in both directions so the
    bound is a bound rather than a refusal of everything.
    """
    width = _column("raw_license")

    assert stated_license(_document("M" * width), source=THE_LOCATOR) == "M" * width

    with pytest.raises(LicenseDocumentError, match="truncated"):
        stated_license(_document("M" * (width + 1)), source=THE_LOCATOR)


def test_a_column_with_no_declared_width_is_refused_rather_than_left_unguarded() -> None:
    """A width guard that quietly stops guarding is worse than one that is absent.

    A field renamed, or one turned into a `TextField`, would otherwise silently turn
    its refusal off with nothing anywhere failing -- and the consequence is a value
    stored on SQLite and a failed run in the gate (`R-5`). `detail` is the real
    `TextField` on this model, so the refusal is reachable without inventing one.
    """
    with pytest.raises(CollectorConfigurationError, match="declares no max_length"):
        license_module._column_width("detail")  # noqa: SLF001 - the guard under test


def test_a_licence_carrying_a_nul_byte_is_refused_where_it_enters() -> None:
    """PostgreSQL rejects a NUL byte from the *driver*, outside the guard `translate` is wrapped in.

    Refused rather than cleaned: a value this collector rewrote is not the value the
    channel published, which is the one thing the raw column exists to be.
    """
    with pytest.raises(LicenseDocumentError, match="NUL byte"):
        stated_license(_document("MIT\x00"), source=THE_LOCATOR)


@pytest.mark.parametrize(
    "stated",
    ["\ud800", "MIT \udfff", "\ud800\ud801"],
    ids=["a-lone-high-surrogate", "a-lone-low-surrogate", "an-unpaired-surrogate-pair"],
)
def test_a_licence_that_is_not_utf_8_encodable_is_refused_where_it_enters(stated: str) -> None:
    """The guard `_require_storable` exists for, asked with the character class that actually escapes it.

    `json.loads('{"license": "\\ud800"}')` succeeds. A lone surrogate is one
    character wide, is not in the C0/C1 control range, and is not a recognised
    spelling -- so before this it became an `unknown` row carrying it in
    `raw_license`, reached `_write_evidence` *outside* the `try` wrapping
    `translate`, and psycopg raised `UnicodeEncodeError: surrogates not allowed` from
    inside the driver. No evidence row at all, and again the next day.

    The check is the encode rather than a pattern, and the third case is why that is
    the honest one: two adjacent surrogates that do not pair are two code points no
    encoder will take, and nobody enumerating "a lone surrogate" would have caught
    them. The paired case is the positive control below -- a *valid* pair is a
    perfectly ordinary character and is stored, so this guard refuses what the driver
    refuses rather than everything that looks like a surrogate.
    """
    body = json.dumps({"name": A_NAME, LICENSE_FIELD: stated})

    with pytest.raises(LicenseDocumentError, match="not encodable as UTF-8"):
        stated_license(body, source=THE_LOCATOR)


def test_a_valid_surrogate_pair_is_an_ordinary_character_and_is_stored() -> None:
    """The anti-vacuity half: the guard is the driver's rule and not a ban on a code-point range.

    `"\\ud834\\udd1e"` in JSON is one character -- U+1D11E, the treble clef -- and
    `json.loads` recombines it. It encodes, PostgreSQL stores it, and a guard written
    as "refuse anything in the surrogate range" would refuse a licence name in a
    script this product has no business having an opinion about.
    """
    stated = json.loads('"\\ud834\\udd1e"')
    body = json.dumps({"name": A_NAME, LICENSE_FIELD: stated})

    assert stated_license(body, source=THE_LOCATOR) == stated
    assert len(stated) == 1


@pytest.mark.parametrize(
    "stated",
    ["BSD 3-Clause\nSee LICENSE file", "MIT\tor Apache", "MIT\rMIT"],
    ids=["a-line-break", "a-tab", "a-carriage-return"],
)
def test_a_storable_licence_this_product_will_not_normalize_is_a_review_item_rather_than_a_failed_run(
    stated: str,
) -> None:
    """The difference between "the database will not hold this" and "this product will not read this".

    PostgreSQL stores a newline and a tab in a `text` value without complaint, and a
    multi-line `license` field is ordinary in conda metadata. Refusing one raised
    `LicenseDocumentError` out of `translate`, which made the *run* fail -- writing
    `error` rows for every other channel without asking them, blanking the raw column
    on all of them, and losing the string that caused it precisely where a reviewer
    needs it. Moving the same value to the second channel cost one row. It then
    repeated for ever, because the observation window only suppresses after a
    success.

    So it is an `unknown` row with the raw string preserved **verbatim** -- newline
    and all -- which is what the matrix assigns "the channel states something this
    product will not normalize" to.
    """
    fact = channel_license(_document(stated), channel=A_CHANNEL, source=THE_LOCATOR)

    assert fact.state == LICENSE_UNKNOWN
    assert fact.raw_license == stated
    assert fact.normalized_license == ""
    assert fact.detection_method == ""
    assert fact.detail == UNNORMALIZABLE_LICENSE_DETAIL


def test_a_fact_that_names_no_channel_is_refused_where_it_is_built() -> None:
    """The table's own constraint, applied before a row exists.

    A row that could not say which channel stated a licence would have merged the
    channels that disagree, which is the merge this table exists to prevent.
    """
    with pytest.raises(CollectorConfigurationError, match="names no channel"):
        ChannelLicense(
            channel="",
            state=LICENSE_UNKNOWN,
            raw_license=A_LICENSE,
            normalized_license="",
            detection_method="",
            source=THE_LOCATOR,
            detail="",
        )


@pytest.mark.parametrize(
    ("state", "expression", "method"),
    [
        (LICENSE_UNKNOWN, A_LICENSE, DetectionMethod.SPDX_IDENTIFIER.value),
        (NORMALIZED, "", ""),
        (NORMALIZED, A_LICENSE, ""),
        (LICENSE_ERROR, "", DetectionMethod.SPDX_IDENTIFIER.value),
    ],
    ids=["normalized-facts-under-unknown", "determinate-with-nothing", "no-method", "a-method-with-no-expression"],
)
def test_a_fact_whose_columns_disagree_with_its_state_is_refused(state: str, expression: str, method: str) -> None:
    """The biconditional, enforced where the value is built rather than where it lands."""
    with pytest.raises(CollectorConfigurationError, match="normalized"):
        ChannelLicense(
            channel=A_CHANNEL,
            state=state,
            raw_license=A_LICENSE,
            normalized_license=expression,
            detection_method=method,
            source=THE_LOCATOR,
            detail="",
        )


def test_the_raw_value_is_permitted_on_a_fact_of_any_state() -> None:
    """The asymmetry AC 1 turns on, asserted as the negative the constraint deliberately does not make."""
    for state in (LICENSE_UNKNOWN, LICENSE_ERROR, LICENSE_NOT_FOUND):
        fact = ChannelLicense(
            channel=A_CHANNEL,
            state=state,
            raw_license=AN_UNRECOGNISED_LICENSE,
            normalized_license="",
            detection_method="",
            source=THE_LOCATOR,
            detail="needs review",
        )

        assert fact.raw_license == AN_UNRECOGNISED_LICENSE


# ---------------------------------------------------------------------------
# The bounded call, and the sentinel shapes.
# ---------------------------------------------------------------------------


def _collector_asking(*channels: str, transport: ScriptedTransport) -> LicenseCollector:
    """Return a collector positioned as though a run had already read its declaration.

    The hooks below are reachable without a database only because the declaration,
    the package's name and the first locator are what `source_for` remembers -- and
    `source_for` is the one hook that reads a table. Setting them by hand is what
    keeps the *rest* of the per-channel path assertable at this tier.

    Args:
        *channels: The channels the run is about, in declared order.
        transport: The transport substituted at the base's seam.

    Returns:
        The collector, which the caller closes.

    """
    collector = LicenseCollector(clock=FixedClock(instant=FIXED_INSTANT), transport=transport)
    collector._channels = channels  # noqa: SLF001 - the state `source_for` remembers, set without a table
    collector._package_name = A_NAME  # noqa: SLF001 - as above
    collector._locator = package_locator(channels[0], A_NAME) if channels else ""  # noqa: SLF001 - as above
    return collector


def test_a_further_channels_answer_becomes_a_fact_rather_than_an_exception() -> None:
    """`CPM-FR-15` on the per-package path: one channel's answer never costs another's."""
    transport = ScriptedTransport(
        answers={THE_OTHER_LOCATOR: recorded_payload(source=THE_OTHER_LOCATOR, body=_document(A_SPELLING))},
    )
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=transport)

    try:
        fact = collector._channel_instead(channel=ANOTHER_CHANNEL)  # noqa: SLF001 - the bounded call under test
    finally:
        collector.close()

    assert fact.channel == ANOTHER_CHANNEL
    assert fact.source == THE_OTHER_LOCATOR
    assert fact.normalized_license == ITS_IDENTIFIER
    assert transport.calls == [THE_OTHER_LOCATOR]


@pytest.mark.parametrize(
    "answer",
    [
        "raises",
        "not-modified",
        "not-found",
        "unreadable",
    ],
)
def test_no_way_a_further_channel_can_fail_escapes_the_bounded_call(answer: str) -> None:
    """The invariant rather than an omission: an exception here discards every answering channel's row.

    Four ways a further channel answers with something other than a document, and
    each becomes a row saying what happened rather than a row claiming the channel
    states no licence. `not_found` is the channel's *own* answer and is the one that
    is not an error.
    """
    scripted: dict[str, Any] = {}
    failures: dict[str, TransportError] = {}
    if answer == "raises":
        failures[THE_OTHER_LOCATOR] = TransportError(
            "the host refused the connection",
            source=THE_OTHER_LOCATOR,
        )
    elif answer == "not-modified":
        scripted[THE_OTHER_LOCATOR] = recorded_payload(source=THE_OTHER_LOCATOR, body="", not_modified=True)
    elif answer == "not-found":
        scripted[THE_OTHER_LOCATOR] = recorded_payload(source=THE_OTHER_LOCATOR, body="", found=False)
    else:
        scripted[THE_OTHER_LOCATOR] = recorded_payload(source=THE_OTHER_LOCATOR, body="not json at all")
    collector = _collector_asking(
        A_CHANNEL,
        ANOTHER_CHANNEL,
        transport=ScriptedTransport(answers=scripted, failures=failures),
    )

    try:
        fact = collector._channel_instead(channel=ANOTHER_CHANNEL)  # noqa: SLF001 - the bounded call under test
    finally:
        collector.close()

    assert fact.channel == ANOTHER_CHANNEL
    assert fact.raw_license == ""
    assert fact.normalized_license == ""
    if answer == "not-found":
        assert fact.state == LICENSE_NOT_FOUND
        assert ABSENT_FROM_CHANNEL_DETAIL in fact.detail
    else:
        assert fact.state == LICENSE_ERROR
        assert UNREAD_CHANNEL_DETAIL in fact.detail
    if answer == "not-modified":
        # The distinguishing sentence, and not only the state. Deleting the
        # `not_modified` branch leaves the payload to fall through to the reader,
        # which refuses an empty body as unreadable JSON -- the same state, the same
        # `UNREAD_CHANNEL_DETAIL`, and a reason describing a problem the source does
        # not have.
        assert NOT_MODIFIED_SENTENCE in fact.detail
    else:
        assert NOT_MODIFIED_SENTENCE not in fact.detail


def test_a_further_channel_whose_name_cannot_be_a_locator_never_reaches_the_transport() -> None:
    """The refusal is a row rather than a raise, and no call is made for a locator nothing could build."""
    transport = ScriptedTransport()
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=transport)
    collector._package_name = "../etc/passwd"  # noqa: SLF001 - a name no locator can be built from

    try:
        fact = collector._channel_instead(channel=ANOTHER_CHANNEL)  # noqa: SLF001 - the bounded call under test
    finally:
        collector.close()

    assert fact.state == LICENSE_ERROR
    assert fact.source == ""
    assert transport.calls == []


@pytest.mark.parametrize(
    "state",
    [OutcomeState.OK, OutcomeState.UNKNOWN, OutcomeState.NOT_APPLICABLE],
    ids=lambda state: state.value,
)
def test_a_sentinel_asked_for_a_state_this_collector_cannot_shape_is_refused_at_the_call(
    state: OutcomeState,
) -> None:
    """The matrix's last row, and the refusal names why each of the three is not shapeable.

    `unknown` in particular: that row is `translate`'s to write with the reason the
    run established, and one shaped here would carry the base's reason for a state
    the base never decides.
    """
    collector = _collector_asking(A_CHANNEL, transport=ScriptedTransport())

    try:
        with pytest.raises(CollectorConfigurationError, match=state.value):
            collector.sentinel_evidence(
                state=state,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="whatever the base said",
            )
    finally:
        collector.close()


def test_the_determinate_value_is_named_in_the_sentinel_refusal_rather_than_reachable_through_it() -> None:
    """`normalized` is a licence a channel *stated*, which a sentinel path never has.

    The matrix names this refusal explicitly, and it is the one a reader would most
    plausibly try to satisfy by widening the hook.
    """
    collector = _collector_asking(A_CHANNEL, transport=ScriptedTransport())

    try:
        with pytest.raises(CollectorConfigurationError, match=NORMALIZED):
            collector.sentinel_evidence(
                state=OutcomeState.OK,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="whatever the base said",
            )
    finally:
        collector.close()


def test_a_sentinel_row_names_the_channel_the_base_asked_and_carries_no_licence_fact() -> None:
    """A sentinel is written for a call that produced no document, so there is nothing stated to preserve."""
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=ScriptedTransport())

    try:
        row = collector.sentinel_evidence(
            state=OutcomeState.ERROR,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="the source failed",
        )
    finally:
        collector.close()

    assert row.channel == A_CHANNEL
    assert row.state == LICENSE_ERROR
    assert row.raw_license == ""
    assert row.normalized_license == ""
    assert row.detection_method == ""
    assert row.source == THE_LOCATOR


def test_a_sentinel_reason_is_cleaned_and_shortened_rather_than_refused() -> None:
    """The opposite posture from a stored document value, and the path is the reason.

    A sentinel row is written on a path already recording a failure, and `CPM-NFR-3`
    requires it to be written -- so raising over the shape of a third party's
    exception message would turn "the channel failed" into "no row at all".
    """
    collector = _collector_asking(A_CHANNEL, transport=ScriptedTransport())

    try:
        row = collector.sentinel_evidence(
            state=OutcomeState.ERROR,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="x" * (MAX_SENTINEL_DETAIL_CHARACTERS + 10) + "\x00",
        )
    finally:
        collector.close()

    assert SHORTENED_DETAIL in row.detail
    assert "\x00" not in row.detail


def test_a_sentinel_asked_before_the_declaration_was_read_is_refused_rather_than_answered_blank() -> None:
    """A blank channel is a row the table refuses at insert, several frames from the call that was wrong.

    On the base's `not_found` branch that write is not wrapped, so the
    `IntegrityError` would escape raw and replace the reason the run was recording.
    """
    collector = LicenseCollector(clock=FixedClock(instant=FIXED_INSTANT), transport=ScriptedTransport())

    try:
        with pytest.raises(CollectorConfigurationError, match=CHANNELS_SETTING):
            collector.sentinel_evidence(
                state=OutcomeState.ERROR,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="the source failed",
            )
    finally:
        collector.close()


def test_an_error_sentinel_answers_for_every_channel_and_asks_none_of_them() -> None:
    """The run is already `failed`, and the reason may be a refused allowance.

    Issuing calls here would spend the remote budget the limiter has just refused and
    would write determinate rows underneath a ledger row saying the run failed.
    """
    transport = ScriptedTransport()
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=transport)

    try:
        rows = collector.sentinel_evidence_rows(
            state=OutcomeState.ERROR,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="the allowance was refused",
        )
    finally:
        collector.close()

    assert [row.channel for row in rows] == [A_CHANNEL, ANOTHER_CHANNEL]
    assert {row.state for row in rows} == {LICENSE_ERROR}
    assert transport.calls == []


def test_a_not_found_sentinel_asks_the_channels_the_bases_one_call_never_reached() -> None:
    """The defect `CPM-CURRENCY-S04` was patched for, in a second table: it is not repeated here.

    A package absent from the first channel and licensed on the second must record
    the second, or "one row per monitored channel" fails on exactly the case it
    exists for.
    """
    transport = ScriptedTransport(
        answers={THE_OTHER_LOCATOR: recorded_payload(source=THE_OTHER_LOCATOR, body=_document(A_LICENSE))},
    )
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=transport)

    try:
        rows = collector.sentinel_evidence_rows(
            state=OutcomeState.NOT_FOUND,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="the channel does not serve the package",
        )
    finally:
        collector.close()

    absent, licensed = rows

    assert absent.channel == A_CHANNEL
    assert absent.state == LICENSE_NOT_FOUND
    assert licensed.channel == ANOTHER_CHANNEL
    assert licensed.state == NORMALIZED
    assert licensed.normalized_license == A_LICENSE
    assert transport.calls == [THE_OTHER_LOCATOR]


def test_a_plural_sentinels_reason_is_cleaned_and_shortened_as_the_singular_hooks_is() -> None:
    """The plural hook is the one the base actually calls, and it had no case of its own.

    `sentinel_evidence` is tested above; on every path the base takes it is *not*
    reached -- `sentinel_evidence_rows` builds the first channel's row through
    `_sentinel_row` directly. So replacing this hook's `_safe_detail` with the raw
    `detail` passed every case in the suite while leaving the base's own sentence,
    with a third party's exception message inside it, to reach the driver unchecked.
    """
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=ScriptedTransport())

    try:
        rows = collector.sentinel_evidence_rows(
            state=OutcomeState.ERROR,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="x" * (MAX_SENTINEL_DETAIL_CHARACTERS + 10) + "\x00\ud800",
        )
    finally:
        collector.close()

    assert [row.channel for row in rows] == [A_CHANNEL, ANOTHER_CHANNEL]
    for row in rows:
        assert SHORTENED_DETAIL in row.detail
        assert "\x00" not in row.detail
        assert "\ud800" not in row.detail
        row.detail.encode("utf-8")


def test_a_transport_failure_whose_message_cannot_be_stored_still_leaves_every_channel_a_row() -> None:
    """The hazard `_safe_detail` exists for, reopened on the path that exists so it cannot be.

    All four of `_channel_instead`'s reasons interpolate a third party's exception
    message. The rows this method produces are written by one `bulk_create` with no
    `DatabaseError` handler over it, so one NUL byte in one channel's failure message
    discarded **every** channel's row -- from inside the driver, several frames past
    any `try`, on the method whose whole invariant is that one channel's failure never
    costs another's answer.
    """
    transport = ScriptedTransport(
        failures={
            THE_OTHER_LOCATOR: TransportError(
                "the host refused\x00 the \x07connection \ud800",
                source=THE_OTHER_LOCATOR,
            ),
        },
    )
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=transport)

    try:
        fact = collector._channel_instead(channel=ANOTHER_CHANNEL)  # noqa: SLF001 - the bounded call under test
    finally:
        collector.close()

    assert fact.state == LICENSE_ERROR
    assert "\x00" not in fact.detail
    assert "\x07" not in fact.detail
    assert "\ud800" not in fact.detail
    fact.detail.encode("utf-8")


@dataclass
class _BreakingTransport:
    """A transport that breaks in a way no `TransportError` describes.

    `ScriptedTransport.failures` is typed to `TransportError`, which is exactly the
    narrowing the two `except Exception` clauses exist to survive -- so the case that
    proves they are load-bearing needs a double that raises something else. A
    substituted transport, a socket library or a DNS resolver may break any way at
    all, and the guarantee `_channel_instead` carries does not depend on which.

    Attributes:
        calls: Every locator `fetch` was handed, in order.

    """

    calls: list[str] = field(default_factory=list)

    def fetch(self, source: str, *, headers: Mapping[str, str] | None = None) -> Payload:
        """Record the request and break.

        Args:
            source: The locator the collector asked for.
            headers: The headers the base composed for it.

        Raises:
            ZeroDivisionError: Always, and deliberately not a `TransportError`.

        """
        del headers
        self.calls.append(source)
        message = "the substituted transport broke in a way nothing here anticipated"
        raise ZeroDivisionError(message)


def test_a_further_channel_whose_transport_breaks_outside_the_transport_vocabulary_is_still_a_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The anti-vacuity case for two `# noqa: BLE001` clauses whose comments claim breadth.

    Both say the guarantee "does not depend on which way a substituted transport, a
    socket library or a DNS resolver breaks" -- and every scripted failure in this
    suite is a `TransportError`, so narrowing either to `except TransportError` stayed
    green while an unanticipated break discarded every answering channel's rows.

    Both clauses are exercised: the fetch that raises something outside the transport
    vocabulary, and the reader that does. The second is reached by substituting
    `channel_license` at the module seam, because every refusal it makes on its own is
    a `LicenseDocumentError`.
    """
    broken = _BreakingTransport()
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=broken)

    try:
        from_the_fetch = collector._channel_instead(channel=ANOTHER_CHANNEL)  # noqa: SLF001 - the bounded call

        def _breaks(body: object, *, channel: str, source: str) -> ChannelLicense:
            del body, channel, source
            message = "the reader broke in a way nothing here anticipated"
            raise ZeroDivisionError(message)

        monkeypatch.setattr(license_module, "channel_license", _breaks)
        reading = ScriptedTransport(
            answers={THE_OTHER_LOCATOR: recorded_payload(source=THE_OTHER_LOCATOR, body=_document(A_LICENSE))},
        )
        collector._transport = reading  # noqa: SLF001 - the seam the base takes at construction
        from_the_reader = collector._channel_instead(channel=ANOTHER_CHANNEL)  # noqa: SLF001 - the bounded call
    finally:
        collector.close()

    assert broken.calls == [THE_OTHER_LOCATOR]
    for fact in (from_the_fetch, from_the_reader):
        assert fact.channel == ANOTHER_CHANNEL
        assert fact.state == LICENSE_ERROR
        assert UNREAD_CHANNEL_DETAIL in fact.detail
        assert ZeroDivisionError.__name__ in fact.detail


def test_every_row_carries_the_active_spans_trace_id_so_a_reader_can_pivot_to_the_run() -> None:
    """`CPM-AD-15`: the evidence row and the log lines of the run that wrote it join on one string.

    `trace_id` appeared in neither licence test module, so setting either call to
    `""` -- on the sentinel row or on the fact row -- left the correlation this
    product measures itself on unverified for this table. Both row shapes are built
    here from one call: the first channel's row comes from `_sentinel_row` and the
    second from `_row_for`.
    """
    transport = ScriptedTransport(
        answers={THE_OTHER_LOCATOR: recorded_payload(source=THE_OTHER_LOCATOR, body=_document(A_LICENSE))},
    )
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=transport)
    span = NonRecordingSpan(
        SpanContext(
            trace_id=A_TRACE_ID,
            span_id=A_SPAN_ID,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        ),
    )

    try:
        with trace.use_span(span, end_on_exit=False):
            rows = collector.sentinel_evidence_rows(
                state=OutcomeState.NOT_FOUND,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="the channel does not serve the package",
            )
    finally:
        collector.close()

    sentinel, fact = rows

    assert sentinel.trace_id == format(A_TRACE_ID, TRACE_ID_FORMAT)
    assert fact.trace_id == format(A_TRACE_ID, TRACE_ID_FORMAT)


def test_a_new_run_forgets_what_the_last_one_was_about_before_any_hook_reads_it() -> None:
    """The other half of `inapplicability`'s position, and the half nothing asserted.

    The hook answers "never inapplicable" and is the first thing the base calls on
    every run, which makes it the one place a previous run's declaration, package name
    and locator can be forgotten. Every integration run builds a fresh collector, so
    deleting all three resets and returning `""` passed the whole suite -- and an
    instance reused across two packages would then answer the second package's hooks
    with the first one's name.
    """
    collector = _collector_asking(A_CHANNEL, ANOTHER_CHANNEL, transport=ScriptedTransport())

    try:
        assert collector.inapplicability(package_id=A_PACKAGE) == ""

        assert collector._channels == NOTHING_MONITORED  # noqa: SLF001 - the state the hook forgets
        assert collector._package_name == ""  # noqa: SLF001 - as above
        assert collector._locator == ""  # noqa: SLF001 - as above
    finally:
        collector.close()


# ---------------------------------------------------------------------------
# The modules' own source.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", [LICENSE_MODULE, SPDX_MODULE], ids=["collector", "spdx"])
def test_neither_module_writes_a_row_of_any_kind(module: str) -> None:
    """`CPM-AD-7`: this collector reads `identity` and writes evidence through the base."""
    tree = parse(SRC_ROOT / module)
    written = sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and dotted_name(node.func).rpartition(".")[2] in WRITE_METHODS
    )

    assert written == [], f"{module} reaches a table directly at lines {written}"


def test_the_collector_module_reads_the_one_identity_model_it_is_allowed_to_read() -> None:
    """The anti-vacuity half: a module that named no model would sweep clean.

    `CPM-AD-7` is "a collector writes its own evidence table and reads only
    `identity`", and this collector's read is one column of `Package`: the canonical
    name a channel serves the package under.
    """
    named = {node.id for node in ast.walk(parse(_license_module())) if isinstance(node, ast.Name)}

    assert PACKAGE_MODEL_NAME in named
    assert "PackageMapping" not in named


def test_the_collector_module_reads_no_other_collectors_evidence_table() -> None:
    """The read a reviewer would most expect to find, and it is not taken.

    The licence this collector records is stated by the *same document*
    `collectors/conda_package.py` reads, and that collector's evidence table also
    carries a channel and a package -- so reaching into `conda_package_snapshots`
    would look like an optimisation. `CPM-AD-7` forbids it and
    `tests/unit/django_apps/test_collector_base_audit.py` holds the whole repository
    to it; this is the case that names the specific temptation.
    """
    source = _license_module().read_text(encoding="utf-8")

    assert A_SIBLINGS_EVIDENCE_MODEL not in source
    assert "conda_package_snapshots" not in source


def test_neither_module_opens_a_transaction_of_its_own() -> None:
    """The per-package transaction is the base's, around the evidence write (`CPM-AD-23`)."""
    for module in (_license_module(), _spdx_module()):
        opened = sorted(
            node.lineno
            for node in ast.walk(parse(module))
            if isinstance(node, ast.Call) and dotted_name(node.func).endswith("transaction.atomic")
        )

        assert opened == []


def test_the_collector_module_imports_no_other_collector_and_no_config() -> None:
    """`CPM-AD-7` and inherited `AD-4`, asserted rather than assumed.

    The setting's name is restated in this module rather than imported from the
    collector that established it, which is precisely the import this case forbids --
    so the reconciliation of the two spellings is a case above rather than an import
    here. The shared `User-Agent` lives in `collectors/agent.py` so the first half can
    be true, and the monitored channels are a *settings read* rather than a `config`
    import.
    """
    imported = {
        node.module
        for node in ast.walk(parse(_license_module()))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        module.endswith((".source_release", ".pypi_release", ".feedstock", ".conda_package", ".vulnerability", ".kev"))
        for module in imported
    ), imported
    assert not any(module == "config" or module.startswith("config.") for module in imported), imported
    assert any(module.endswith(".collectors.agent") for module in imported)
    assert "django.conf" in imported


def test_the_normalization_module_is_a_leaf_that_reaches_no_model_and_no_collector() -> None:
    """`collectors/models.py` reads `DetectionMethod` for a column's choices, so this module must depend on nothing.

    A vocabulary declared in the models module or in the collector would close an
    import cycle and fail at start-up. The precedent and the reason are
    `collectors/match_confidence.py`'s.
    """
    imported = {
        node.module
        for node in ast.walk(parse(_spdx_module()))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(module.startswith("conda_sentinel") for module in imported), imported
    assert "django.db" in imported


def test_neither_module_reads_the_wall_clock() -> None:
    """`CPM-AD-26`: every instant comes from the injected clock, and a row carries the run's."""
    for module in (_license_module(), _spdx_module()):
        called = {dotted_name(node.func) for node in ast.walk(parse(module)) if isinstance(node, ast.Call)}

        assert not any(name.endswith(("timezone.now", "datetime.now", "datetime.utcnow")) for name in called), called


def test_no_compliance_verdict_of_any_kind_is_spelled_in_either_module() -> None:
    """`CPM-FR-18`'s judgement is `CPM-SECURITY-S05`'s, and PRD Appendix A.2's column is recorded as not-taken.

    Asserted as an absence of the *words*, which is coarse and is the point: a
    reviewer skimming for "did this collector start deciding whether a licence is
    acceptable" reads a list of names, and a column, constant or vocabulary member
    called any of these would be the first sign it had.

    `allowed`/`denied` are AC 2's own words for what this table must never record;
    `permissive`, `copyleft` and `compliant` are the classifications a licence
    normalizer most plausibly grows into.
    """
    forbidden = ("allow", "deny", "permissive", "copyleft", "compliant", "verdict", "policy")
    for module in (_license_module(), _spdx_module()):
        declared = _declared_names(module)
        found = sorted(name for name in declared if any(word in name.casefold() for word in forbidden))

        assert found == [], f"{module.name} declares {found}"

    # And the vocabulary itself, which is the one place a verdict would land as a
    # *value* rather than as a name.
    assert not any(word in member.value for member in LicenseOutcome for word in forbidden), [
        member.value for member in LicenseOutcome
    ]
