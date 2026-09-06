"""What the published-package collector declares, what a declaration is, what a locator is, what a document means.

`CPM-FR-10` is several questions and only the last needs a run. Turning two
settings values into a checked pair of monitored surfaces, turning a channel and
a package name into a locator, and reading a channel's package document into one
fact per platform are all pure functions of data, and all are here with no
database, no socket and no clock (`CPM-AD-27`). What needs a run -- the rows, the
ledger, two channels producing two unmerged rows, a failing channel beside an
answering one, the refusal when nothing is declared, and the two constraints --
is in `tests/integration/django_apps/test_conda_package.py`.

**The declarations are asserted against their derivations rather than against
themselves**, on the terms `tests/unit/django_apps/test_feedstock.py` sets: the
target is the cadence times one plus the tolerated misses, the window is shorter
than the cadence, and one whole collection -- which here is the retried first call
plus one un-retried call per *remaining monitored channel* -- fits inside the
inherited Celery soft limit read from the settings module.

No database, no network: nothing here saves a row, no queryset is evaluated, and
every payload is a literal.
"""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from conda_package_supply_chain_monitor.collectors import conda_package as conda_package_module
from conda_package_supply_chain_monitor.collectors.agent import USER_AGENT
from conda_package_supply_chain_monitor.collectors.conda_package import ANACONDA_API_HOST
from conda_package_supply_chain_monitor.collectors.conda_package import ATTRS_FIELD
from conda_package_supply_chain_monitor.collectors.conda_package import BUILD_FIELD
from conda_package_supply_chain_monitor.collectors.conda_package import BUILD_NUMBER_FIELD
from conda_package_supply_chain_monitor.collectors.conda_package import CHANNELS_SETTING
from conda_package_supply_chain_monitor.collectors.conda_package import COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_CACHE_TTL
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_CADENCE
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_FRESHNESS_TARGET
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_HEADERS
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_OBSERVATION_WINDOW
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_RATE_LIMIT
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_RETRIES
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_TIMEOUT
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_SUBDIRS
from conda_package_supply_chain_monitor.collectors.conda_package import DEFAULT_LABEL
from conda_package_supply_chain_monitor.collectors.conda_package import FILES_FIELD
from conda_package_supply_chain_monitor.collectors.conda_package import LABELS_FIELD
from conda_package_supply_chain_monitor.collectors.conda_package import LATEST_VERSION_FIELD
from conda_package_supply_chain_monitor.collectors.conda_package import MAX_BUILD_NUMBER
from conda_package_supply_chain_monitor.collectors.conda_package import MAX_DOCUMENT_CHARACTERS
from conda_package_supply_chain_monitor.collectors.conda_package import MAX_MONITORED_CHANNELS
from conda_package_supply_chain_monitor.collectors.conda_package import NO_LATEST_VERSION_DETAIL
from conda_package_supply_chain_monitor.collectors.conda_package import NO_PUBLISHED_FILE_DETAIL
from conda_package_supply_chain_monitor.collectors.conda_package import OFF_LABEL_DETAIL
from conda_package_supply_chain_monitor.collectors.conda_package import PLATFORMS_SETTING
from conda_package_supply_chain_monitor.collectors.conda_package import SUBDIR_FIELD
from conda_package_supply_chain_monitor.collectors.conda_package import TOLERATED_MISSED_RUNS
from conda_package_supply_chain_monitor.collectors.conda_package import UNREAD_CHANNEL_DETAIL
from conda_package_supply_chain_monitor.collectors.conda_package import VERSION_FIELD
from conda_package_supply_chain_monitor.collectors.conda_package import CondaChannelError
from conda_package_supply_chain_monitor.collectors.conda_package import CondaDocumentError
from conda_package_supply_chain_monitor.collectors.conda_package import CondaPackageCollector
from conda_package_supply_chain_monitor.collectors.conda_package import Monitored
from conda_package_supply_chain_monitor.collectors.conda_package import channel_facts
from conda_package_supply_chain_monitor.collectors.conda_package import monitored
from conda_package_supply_chain_monitor.collectors.conda_package import package_locator
from conda_package_supply_chain_monitor.collectors.models import CondaPackageSnapshot
from conda_package_supply_chain_monitor.collectors.tasks import COLLECT_CONDA_PACKAGE_TASK_NAME
from conda_package_supply_chain_monitor.collectors.tasks import collect_conda_package
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.collection import CONDITIONAL_HEADERS
from conda_package_supply_chain_monitor.core.collection import CollectorConfigurationError
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.queues import Queue
from conda_package_supply_chain_monitor.core.queues import queue_for
from conda_package_supply_chain_monitor.core.transport import DEFAULT_RETRIES
from conda_package_supply_chain_monitor.core.transport import MAX_TIMEOUT
from conda_package_supply_chain_monitor.core.transport import worst_case_call_seconds
from tests.clocks import FIXED_INSTANT
from tests.collectors import ScriptedTransport
from tests.source_scan import SRC_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse

if TYPE_CHECKING:
    from pathlib import Path

#: The module this file's source sweeps are about, relative to `src/`.
CONDA_PACKAGE_MODULE: Final[str] = "django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py"

#: The identity model this collector reads, and the write methods it may not
#: reach for. `CPM-AD-7` says a collector "reads only `identity`", and this one
#: reads it for the package's canonical name alone -- so the module may *name*
#: `Package` and may write nothing.
PACKAGE_MODEL_NAME: Final[str] = "Package"
WRITE_METHODS: Final[frozenset[str]] = frozenset(
    {"abulk_create", "acreate", "asave", "bulk_create", "create", "get_or_create", "save", "update_or_create"},
)

#: The package the cases ask about, the channels and platforms they declare, and
#: the locator the first pair produces. The locator is written out rather than
#: composed from the module's own constants, because one assembled the same way
#: twice would agree with itself however wrong it was.
A_NAME: Final[str] = "numpy"
A_CHANNEL: Final[str] = "conda-forge"
ANOTHER_CHANNEL: Final[str] = "bioconda"
A_PLATFORM: Final[str] = "linux-64"
ANOTHER_PLATFORM: Final[str] = "osx-arm64"
THE_LOCATOR: Final[str] = "https://api.anaconda.org/package/conda-forge/numpy"

#: The locator a payload claims to have come from, for the document cases.
A_SOURCE: Final[str] = "https://api.anaconda.org/package/a-channel/a-package"

#: What the channel document says.
A_VERSION: Final[str] = "2.1.3"
AN_OLDER_VERSION: Final[str] = "2.0.0"

#: A release candidate, for the case about labels. Newer than the release, so a
#: channel that states it as latest is stating exactly what an off-label upload
#: does to `latest_version`.
A_RC_VERSION: Final[str] = "2.2.0rc1"
A_BUILD: Final[str] = "py312h1234567_0"
ANOTHER_BUILD: Final[str] = "py312h7654321_1"
A_BUILD_NUMBER: Final[int] = 0
ANOTHER_BUILD_NUMBER: Final[int] = 1

#: How much of the inherited soft limit one whole *collection* may spend -- three
#: quarters, so the claim is "with room for the ledger writes around it" rather
#: than "by a hair". Applied to the retried first call plus one un-retried call
#: per remaining monitored channel, which is what this collector's worst
#: collection actually is.
SOFT_LIMIT_SHARE: Final[float] = 0.75

#: The most text one collection may hand to `json.loads` in total, across every
#: monitored channel. Thirty-two mebibytes: a bound on the whole parse rather
#: than on one document, which is the figure a soft time limit is actually
#: spent against.
A_PARSE_BUDGET: Final[int] = 32 * 1024 * 1024

#: A package key the cases that need one use. This tier never reads a row.
A_PACKAGE: Final[int] = 7

#: The application whose `ready()` performs the boot refusal, by label.
COLLECTORS_APP_LABEL: Final[str] = "collectors"

#: What `collectors/pypi_release.py` declares against a source that publishes no
#: numeric ceiling either. Named so the comparison below reads as the argument it
#: is -- this collector is tighter, because one collection issues several calls --
#: rather than as a bare number.
A_SIBLINGS_COURTESY_BOUND: Final[int] = 60

#: The counts the cases assert against, one named constant per concept, because
#: `PLR2004` is right about a bare number in an assertion.
TWO_FACTS: Final[int] = 2
TWO_BUILDS: Final[int] = 2

#: The rows two channels by two platforms owes -- one per pair, on every
#: terminal path.
FOUR_PAIRS: Final[int] = 4

#: The marker the document builder treats as "the source did not send this field
#: at all", as distinct from `None`, which is an explicit JSON `null`.
OMITTED: Final[object] = object()

#: The marker that means "leave this field at the builder's own default". Its own
#: object rather than `OMITTED` reused: a case that wants a field *absent* and one
#: that wants the default are opposite asks, and one sentinel for both makes the
#: absent case unwritable -- which is exactly how it goes unasserted.
DEFAULT: Final[object] = object()


def _document(
    latest: str | object | None = A_VERSION,
    files: list[dict[str, Any]] | object | None = DEFAULT,
    **overrides: Any,
) -> str:
    """Return the body a channel would serve for one package.

    Args:
        latest: The version the channel states as latest, `None` for an explicit
            JSON null, or `OMITTED` for a document that carries no such field.
        files: The published files, `DEFAULT` for the builder's own single file,
            `None` for an explicit null, or `OMITTED` for a document carrying no
            `files` at all.
        **overrides: Further top-level fields to add or replace.

    Returns:
        The JSON body.

    """
    document: dict[str, Any] = {
        LATEST_VERSION_FIELD: latest,
        FILES_FIELD: _files() if files is DEFAULT else files,
        "name": A_NAME,
    }
    document.update(overrides)
    return json.dumps({key: value for key, value in document.items() if value is not OMITTED})


def _files(*entries: tuple[str, str, str, int | None]) -> list[dict[str, Any]]:
    """Return the `files` list a channel document carries.

    Args:
        *entries: One `(version, subdir, build, build_number)` per published
            file. Defaults to one file of the latest version on the first
            platform.

    Returns:
        The file entries, each served under the default label.

    """
    described = entries or ((A_VERSION, A_PLATFORM, A_BUILD, A_BUILD_NUMBER),)
    return [
        {
            VERSION_FIELD: version,
            LABELS_FIELD: [DEFAULT_LABEL],
            ATTRS_FIELD: {SUBDIR_FIELD: subdir, BUILD_FIELD: build, BUILD_NUMBER_FIELD: number},
        }
        for version, subdir, build, number in described
    ]


def _labelled_file(labels: list[Any] | None, version: str = A_VERSION) -> dict[str, Any]:
    """Return one published file served under stated labels.

    Args:
        labels: The labels the channel serves it under, or `None` for a document
            that states none.
        version: The version it publishes.

    Returns:
        The file entry.

    """
    entry: dict[str, Any] = {
        VERSION_FIELD: version,
        ATTRS_FIELD: {SUBDIR_FIELD: A_PLATFORM, BUILD_FIELD: A_BUILD, BUILD_NUMBER_FIELD: A_BUILD_NUMBER},
    }
    if labels is not None:
        entry[LABELS_FIELD] = labels
    return entry


def _stopped_clock() -> FixedClock:
    """Return the clock the collector cases inject.

    Returns:
        A `FixedClock` at `tests.clocks.FIXED_INSTANT`.

    """
    return FixedClock(instant=FIXED_INSTANT)


def _conda_package_module() -> Path:
    """Return the collector module this file's source sweeps read.

    Returns:
        Its path, resolved from `SRC_ROOT`.

    """
    return SRC_ROOT / CONDA_PACKAGE_MODULE


# ---------------------------------------------------------------------------
# The declarations, and the arithmetic behind them.
# ---------------------------------------------------------------------------


def test_the_collector_declares_every_value_the_base_checks() -> None:
    """All nine, written out on the class and carrying the module's own constants.

    Compared by *value* rather than by presence, for the reason the three sibling
    collectors' cases give: a class attribute rebound to the wrong constant
    declares nine names and behaves like something nobody wrote down.
    """
    declared = vars(CondaPackageCollector)

    assert CondaPackageCollector.name == COLLECTOR_NAME
    assert CondaPackageCollector.evidence_model is CondaPackageSnapshot
    assert CondaPackageCollector.observation_window == CONDA_PACKAGE_OBSERVATION_WINDOW
    assert CondaPackageCollector.timeout == CONDA_PACKAGE_TIMEOUT
    assert CondaPackageCollector.retries == CONDA_PACKAGE_RETRIES
    assert CondaPackageCollector.rate_limit == CONDA_PACKAGE_RATE_LIMIT
    assert CondaPackageCollector.headers == CONDA_PACKAGE_HEADERS
    assert CondaPackageCollector.freshness_target == CONDA_PACKAGE_FRESHNESS_TARGET
    assert CondaPackageCollector.response_cache_ttl == CONDA_PACKAGE_CACHE_TTL
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


def test_the_cadence_is_the_fast_end_of_the_range_the_prd_gives() -> None:
    """`CPM-NFR-2` gives version currency "daily to weekly"; a published artifact is the daily one.

    Asserted as a comparison against the range's slow end rather than against
    itself, so a cadence quietly lengthened to match the feedstock collector
    would fail here rather than pass by agreeing with a constant beside it.
    """
    assert timedelta(days=1) == CONDA_PACKAGE_CADENCE
    assert timedelta(days=7) > CONDA_PACKAGE_CADENCE


def test_the_freshness_target_is_the_arithmetic_open_question_7_settled() -> None:
    """`cadence x (1 + tolerated_missed_runs)`, and strictly greater than the cadence.

    `core/freshness.py` reports stale when `observed_at < now - target`, so a
    target *equal* to the cadence makes every package read stale at exactly the
    moment its next run is due, without a single collection having failed.
    """
    assert CONDA_PACKAGE_FRESHNESS_TARGET == CONDA_PACKAGE_CADENCE * (1 + TOLERATED_MISSED_RUNS)
    assert CONDA_PACKAGE_FRESHNESS_TARGET > CONDA_PACKAGE_CADENCE


def test_the_observation_window_cannot_suppress_a_scheduled_run() -> None:
    """Shorter than the cadence, which is the property rather than the halving."""
    assert CONDA_PACKAGE_OBSERVATION_WINDOW < CONDA_PACKAGE_CADENCE
    assert timedelta(0) < CONDA_PACKAGE_OBSERVATION_WINDOW


def test_the_response_cache_outlives_the_cadence() -> None:
    """An entry that expired between runs would make the cache inert."""
    assert CONDA_PACKAGE_CACHE_TTL > CONDA_PACKAGE_CADENCE


def test_the_worst_collection_this_declaration_permits_fits_inside_the_inherited_soft_limit() -> None:
    """Every call this collector makes is retried, including the ones made from inside `translate`.

    The retry policy is mounted on the *session* `core/transport.py` builds, so it
    applies to every request that session issues wherever in the collector the
    request is made -- there is no such thing as an un-retried call here. The
    figure the reconciliation is made against is therefore
    `MAX_MONITORED_CHANNELS * worst_case_call_seconds(...)`, asserted **at the
    ceiling**: a declaration the ceiling permits must be one the soft limit
    affords, or the ceiling is not a bound at all and a full declaration is a task
    the platform kills before it writes anything.

    Read from the settings module rather than repeated here, so lowering the limit
    there fails this rather than passing quietly.
    """
    worst_case = worst_case_call_seconds(timeout=CONDA_PACKAGE_TIMEOUT, retries=CONDA_PACKAGE_RETRIES)
    soft_limit = settings.CELERY_TASK_SOFT_TIME_LIMIT

    assert MAX_MONITORED_CHANNELS * worst_case <= SOFT_LIMIT_SHARE * soft_limit
    assert CONDA_PACKAGE_TIMEOUT <= MAX_TIMEOUT
    # And the ceiling is a real one rather than a formality: it permits more than
    # a single channel, which is what AC 1 is about.
    assert MAX_MONITORED_CHANNELS > 1


def test_the_retry_budget_is_smaller_than_the_shared_default_because_the_call_count_is_larger() -> None:
    """The two declarations trade against each other, and the trade is the reason for the number.

    A collection is up to `MAX_MONITORED_CHANNELS` fully retried calls; at the
    shared default of three retries that is `4 x (8t + 3)` seconds, which does not
    fit the soft limit at any timeout a real source could answer inside. Asserted
    against the default rather than against itself, so a later edit that "restored
    the default" fails here rather than producing a collector the platform kills.
    """
    assert CONDA_PACKAGE_RETRIES < DEFAULT_RETRIES
    assert CONDA_PACKAGE_RETRIES >= 1
    at_the_default = worst_case_call_seconds(timeout=CONDA_PACKAGE_TIMEOUT, retries=DEFAULT_RETRIES)
    assert MAX_MONITORED_CHANNELS * at_the_default > SOFT_LIMIT_SHARE * settings.CELERY_TASK_SOFT_TIME_LIMIT


def test_the_document_ceiling_is_reconciled_against_the_channel_count_rather_than_one_document() -> None:
    """Up to `MAX_MONITORED_CHANNELS` documents are parsed inside one soft time limit.

    A ceiling argued from one document would be four times looser than it reads,
    which is the whole reason this collector's is lower than the sibling that
    reads one document per collection. Both halves are asserted: the product is
    bounded, and the bound is still orders of magnitude above a real document, so
    an honest source is never refused.
    """
    assert MAX_MONITORED_CHANNELS * MAX_DOCUMENT_CHARACTERS <= A_PARSE_BUDGET
    assert len(_document()) * 1000 < MAX_DOCUMENT_CHARACTERS


def test_the_declared_headers_carry_what_the_source_expects_and_nothing_conditional() -> None:
    """Headers reach the socket only through the base (`CPM-AD-20`, `CPM-AD-27`).

    The JSON representation is asked for by name and the `User-Agent` is the one
    identity every collector shares. What is not declared is a validator, which
    the base composes from the response cache and refuses at construction.
    """
    lowered = {name.lower(): value for name, value in CONDA_PACKAGE_HEADERS.items()}

    assert lowered["user-agent"] == USER_AGENT
    assert lowered["accept"] == "application/json"
    assert set(lowered).isdisjoint({header.lower() for header in CONDITIONAL_HEADERS})


def test_the_declared_allowance_is_a_courtesy_bound_a_whole_collection_fits_inside() -> None:
    """anaconda.org publishes no numeric ceiling, so the bound is declared rather than quoted.

    Three things are worth pinning: a single collection's charge fits inside it --
    an allowance smaller than `1 + retries` would refuse every call -- the bound is
    tighter than the sibling that faces a source with the same silence, because a
    collection here issues up to `MAX_MONITORED_CHANNELS` calls rather than one,
    and it is counted per minute rather than per hour.
    """
    assert CONDA_PACKAGE_RATE_LIMIT.calls >= 1 + CONDA_PACKAGE_RETRIES
    assert CONDA_PACKAGE_RATE_LIMIT.per == timedelta(minutes=1)
    assert CONDA_PACKAGE_RATE_LIMIT.calls < A_SIBLINGS_COURTESY_BOUND


def test_the_collector_is_constructed_from_its_declarations_alone() -> None:
    """The base's nine refusals, run against the real class rather than a fixture."""
    collector = CondaPackageCollector(clock=_stopped_clock())

    try:
        assert collector.request_cost == 1 + CONDA_PACKAGE_RETRIES
        assert CONDA_PACKAGE_RATE_LIMIT.calls >= collector.request_cost
    finally:
        collector.close()


def test_the_task_name_routes_to_the_collect_queue() -> None:
    """`cpm.collect.*` is what puts external I/O on the `collect` queue (`R-11`).

    The Celery binding is asserted too: the constant is what routes, and a task
    registered under a name the constant does not spell would route nowhere.
    """
    assert queue_for(COLLECT_CONDA_PACKAGE_TASK_NAME) == Queue.COLLECT
    assert COLLECT_CONDA_PACKAGE_TASK_NAME.endswith(COLLECTOR_NAME)
    assert collect_conda_package.name == COLLECT_CONDA_PACKAGE_TASK_NAME


# ---------------------------------------------------------------------------
# The declaration (`monitored`).
# ---------------------------------------------------------------------------


def test_a_declaration_is_kept_in_the_order_it_was_written() -> None:
    """The first channel is the one the base calls, so the order is a decision rather than an accident."""
    declared = monitored([ANOTHER_CHANNEL, A_CHANNEL], [ANOTHER_PLATFORM, A_PLATFORM])

    assert declared == Monitored(
        channels=(ANOTHER_CHANNEL, A_CHANNEL),
        platforms=(ANOTHER_PLATFORM, A_PLATFORM),
    )


@pytest.mark.parametrize(
    ("declared", "expected"),
    [(["Conda-Forge"], ("conda-forge",)), (["  conda-forge  "], ("conda-forge",))],
    ids=["mixed-case", "surrounded-by-space"],
)
def test_a_declared_channel_is_normalised_the_way_the_locator_will_spell_it(
    declared: list[str],
    expected: tuple[str, ...],
) -> None:
    """One spelling, so one locator, one cache entry and one value of `channel` in an append-only log."""
    assert monitored(declared, [A_PLATFORM]).channels == expected


@pytest.mark.parametrize(
    ("declared", "expected"),
    [(["LINUX-64"], ("linux-64",)), (["  linux-64  "], ("linux-64",))],
    ids=["upper-case", "surrounded-by-space"],
)
def test_a_declared_platform_is_normalised_before_it_is_checked_against_the_vocabulary(
    declared: list[str],
    expected: tuple[str, ...],
) -> None:
    """The normalisation runs first, so a subdir spelled loudly is the same subdir rather than an unknown one."""
    assert monitored([A_CHANNEL], declared).platforms == expected


def test_every_declared_platform_must_be_a_subdir_conda_actually_defines() -> None:
    """A subdir is a value conda defines, not a name an operator invents.

    A grammar that accepted any lower-case segment would let `linux_64` through,
    and every run would then record that this channel's latest version has no file
    on it -- a false statement about the channel, permanently, in a log nothing may
    correct and indistinguishable from a true one. The refusal names the permitted
    set, because an operator reading a `failed` ledger row has nothing else to go
    on.
    """
    for unknown in ("linux_64", "osx-arm-64", "linux-amd64", "darwin-arm64"):
        with pytest.raises(CondaChannelError, match="subdir") as refused:
            monitored([A_CHANNEL], [unknown])
        assert A_PLATFORM in str(refused.value)


def test_the_declared_vocabulary_is_the_one_conda_serves_and_not_an_empty_set() -> None:
    """The anti-vacuity half: a check against an empty vocabulary would refuse everything.

    Both halves matter -- the subdirs a real declaration would name are accepted,
    and `noarch` is among them, because a package published only as `noarch` is
    installable everywhere and is exactly the fact an operator monitoring it wants.
    """
    usual = ["linux-64", "osx-arm64", "win-64", "noarch"]

    assert monitored([A_CHANNEL], usual).platforms == tuple(usual)
    assert set(usual) <= CONDA_SUBDIRS


def test_every_subdir_in_the_vocabulary_fits_the_column_that_records_it() -> None:
    """The width refusal is unreachable for a platform, and that is a property rather than an accident.

    A channel name is a name an operator chose and may be any length, so it is
    refused against the column. A subdir is drawn from a closed set, so what has to
    be true is that the *set* fits -- and if it ever stopped fitting, the refusal
    would fire on a declaration conda itself defines.
    """
    width = CondaPackageSnapshot._meta.get_field("platform").max_length  # noqa: SLF001 - Django's own public-by-convention API
    assert width is not None
    assert max(len(subdir) for subdir in CONDA_SUBDIRS) <= width


def test_a_declaration_may_be_a_tuple_as_well_as_a_list() -> None:
    """What the settings module ships is a tuple, and it must not be the shape that is refused."""
    assert monitored((A_CHANNEL,), (A_PLATFORM,)).platforms == (A_PLATFORM,)


@pytest.mark.parametrize(
    "setting",
    [CHANNELS_SETTING, PLATFORMS_SETTING],
    ids=["channels", "platforms"],
)
def test_an_empty_declaration_is_refused_naming_the_setting_an_operator_must_declare(setting: str) -> None:
    """The shipped state: the mechanism is here and the choice is not (PRD Open Question 4).

    The message has to name the setting, because it is the only thing an operator
    reading a `failed` ledger row has to go on.
    """
    channels = [] if setting == CHANNELS_SETTING else [A_CHANNEL]
    platforms = [] if setting == PLATFORMS_SETTING else [A_PLATFORM]

    with pytest.raises(CondaChannelError, match=setting):
        monitored(channels, platforms)


def test_a_bare_string_is_refused_rather_than_read_as_one_channel_per_character() -> None:
    """`CPM_MONITORED_CHANNELS = "conda-forge"` is eleven channels to Python, and none of them exists.

    The most plausible way to write this declaration wrongly, and the one whose
    silent failure would be worst: eleven locators, eleven rows a run, and nothing
    anywhere saying the declaration had been misread.
    """
    with pytest.raises(CondaChannelError, match="str"):
        monitored(A_CHANNEL, [A_PLATFORM])


@pytest.mark.parametrize("declared", [None, 7, {A_CHANNEL: 1}], ids=["none", "int", "mapping"])
def test_a_declaration_that_is_not_a_list_or_tuple_is_refused(declared: Any) -> None:
    """A settings module may hold anything, so the shape is checked rather than assumed."""
    with pytest.raises(CondaChannelError, match=CHANNELS_SETTING):
        monitored(declared, [A_PLATFORM])


@pytest.mark.parametrize(
    "entry",
    ["", "   ", None, 7, "conda-forge/main", "..", ".", "-leading", ".leading", "with space", "back\\slash"],
    ids=[
        "empty",
        "whitespace",
        "none",
        "int",
        "path-separator",
        "parent",
        "current",
        "leading-hyphen",
        "leading-dot",
        "internal-space",
        "backslash",
    ],
)
def test_an_entry_that_is_not_a_locator_segment_is_refused_rather_than_encoded(entry: Any) -> None:
    """A declaration is refused whole rather than read for the entries that happen to parse.

    A path separator is the one the matrix names, and `.` and `..` are the reason
    percent-encoding would not have been enough: both are unreserved, so encoding
    leaves them untouched and the source is entitled to resolve them somewhere
    else.
    """
    with pytest.raises(CondaChannelError, match=CHANNELS_SETTING):
        monitored([entry], [A_PLATFORM])


@pytest.mark.parametrize(
    "declared",
    [[A_CHANNEL, A_CHANNEL], [A_CHANNEL, "Conda-Forge"], [A_CHANNEL, "  conda-forge"]],
    ids=["identical", "different-case", "surrounded-by-space"],
)
def test_the_same_entry_declared_twice_is_refused_including_where_it_is_spelled_twice(declared: list[str]) -> None:
    """Two identical rows for one observation would be two facts where there is one.

    Duplicates are looked for *after* normalisation, which is the half a set of
    the raw strings would have missed: `Conda-Forge` beside `conda-forge` is one
    declaration written twice and would otherwise become two calls, two rows and
    two spellings that a reader could never tell apart.
    """
    with pytest.raises(CondaChannelError, match="twice"):
        monitored(declared, [A_PLATFORM])


def test_a_platform_declared_twice_is_refused_too() -> None:
    """The anti-vacuity half: both declarations go through the same rule, not just the first."""
    with pytest.raises(CondaChannelError, match="twice"):
        monitored([A_CHANNEL], [A_PLATFORM, A_PLATFORM])


def test_more_channels_than_one_collection_can_ask_about_is_refused() -> None:
    """A ceiling on time rather than an opinion about which channels are worth watching.

    Every channel past the first costs an un-retried call inside one Celery task,
    and a task the platform kills at its soft time limit writes nothing at all --
    which is worse than refusing the declaration that caused it. The refusal names
    the ceiling so an operator can see what it is.
    """
    too_many = [f"channel-{index}" for index in range(MAX_MONITORED_CHANNELS + 1)]

    with pytest.raises(CondaChannelError, match=str(MAX_MONITORED_CHANNELS)):
        monitored(too_many, [A_PLATFORM])

    # And exactly the ceiling is accepted, so the bound is off-by-one correct
    # rather than merely present.
    assert len(monitored(too_many[:-1], [A_PLATFORM]).channels) == MAX_MONITORED_CHANNELS


def test_platforms_are_not_bounded_by_the_channel_ceiling() -> None:
    """A platform costs a row rather than a call, and rows are what the table is for."""
    many = sorted(CONDA_SUBDIRS)[: MAX_MONITORED_CHANNELS + 3]
    assert len(many) > MAX_MONITORED_CHANNELS

    assert len(monitored([A_CHANNEL], many).platforms) == len(many)


def test_a_channel_wider_than_its_column_is_refused_rather_than_truncated() -> None:
    """Refused at the declaration rather than at the insert, which is where it would otherwise land.

    `max_length` is enforced by PostgreSQL and ignored by SQLite, so an over-long
    entry is a stored row on a developer's machine and a failed run in the gate
    (`R-5`). Refusing where the value enters makes both machines agree.

    The channel is the half that needs it: a channel is a name an operator chose
    and may be any length at all, while a platform is drawn from a closed set that
    `test_every_subdir_in_the_vocabulary_fits_the_column_that_records_it` shows
    fits.
    """
    width = CondaPackageSnapshot._meta.get_field("channel").max_length  # noqa: SLF001 - Django's own public-by-convention API
    assert width is not None

    with pytest.raises(CondaChannelError, match=str(width)):
        monitored(["a" * (width + 1)], [A_PLATFORM])

    # And one that exactly fits is not refused, so the bound is the column's
    # rather than one short of it.
    assert monitored(["a" * width], [A_PLATFORM])


# ---------------------------------------------------------------------------
# The locator (`package_locator`).
# ---------------------------------------------------------------------------


def test_the_golden_example_reaches_the_golden_locator() -> None:
    """The story's worked example, spelled out rather than composed the way the code composes it."""
    assert package_locator(A_CHANNEL, A_NAME) == THE_LOCATOR
    assert ANACONDA_API_HOST in THE_LOCATOR


def test_the_locator_normalises_both_of_its_segments() -> None:
    """A channel and a package name reach one locator however they were spelled."""
    assert package_locator("Conda-Forge", "NumPy") == THE_LOCATOR


@pytest.mark.parametrize(
    ("channel", "name"),
    [("", A_NAME), (A_CHANNEL, ""), ("a/b", A_NAME), (A_CHANNEL, "a/b"), (None, A_NAME), (A_CHANNEL, None)],
    ids=[
        "blank-channel",
        "blank-name",
        "channel-separator",
        "name-separator",
        "channel-not-a-string",
        "name-not-a-string",
    ],
)
def test_a_locator_refuses_a_segment_that_is_not_one(channel: Any, name: Any) -> None:
    """Both halves, because a package's canonical name is data a resolution wrote and may be anything."""
    with pytest.raises(CondaChannelError):
        package_locator(channel, name)


def test_a_locator_refuses_the_package_name_by_its_own_name_rather_than_a_settings_key() -> None:
    """The refusal has to say what could not be turned into a segment, and the name is not a setting."""
    with pytest.raises(CondaChannelError, match="canonical_name"):
        package_locator(A_CHANNEL, "not a name")


# ---------------------------------------------------------------------------
# The document (`channel_facts`).
# ---------------------------------------------------------------------------


def test_a_channel_document_records_the_published_version_and_the_build_for_each_platform() -> None:
    """AC 1's facts: the version the channel states as latest, its build string and its build number."""
    body = _document(
        files=_files(
            (A_VERSION, A_PLATFORM, A_BUILD, A_BUILD_NUMBER),
            (A_VERSION, ANOTHER_PLATFORM, ANOTHER_BUILD, ANOTHER_BUILD_NUMBER),
        ),
    )

    facts = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM, ANOTHER_PLATFORM], source=A_SOURCE)

    assert len(facts) == TWO_FACTS
    assert [fact.platform for fact in facts] == [A_PLATFORM, ANOTHER_PLATFORM]
    assert {fact.channel for fact in facts} == {A_CHANNEL}
    assert {fact.state for fact in facts} == {OutcomeState.OK}
    assert {fact.published_version for fact in facts} == {A_VERSION}
    assert [fact.build_string for fact in facts] == [A_BUILD, ANOTHER_BUILD]
    assert [fact.build_number for fact in facts] == [A_BUILD_NUMBER, ANOTHER_BUILD_NUMBER]
    assert {fact.source for fact in facts} == {A_SOURCE}
    assert {fact.detail for fact in facts} == {""}


def test_one_fact_is_produced_per_platform_and_never_one_for_the_channel() -> None:
    """AC 1: a row never stands for two platforms, so the reader never has to unpick a merge."""
    facts = channel_facts(_document(), channel=A_CHANNEL, platforms=[A_PLATFORM, ANOTHER_PLATFORM], source=A_SOURCE)

    assert len(facts) == TWO_FACTS
    assert len({fact.platform for fact in facts}) == TWO_FACTS


def test_a_platform_the_latest_version_has_no_file_on_is_an_absence_naming_the_version_that_exists() -> None:
    """The matrix's "latest version absent from a platform": a written `not_found`, never a missing row.

    The version is in `detail` because the constraint keeps `published_version`
    blank on a row that is not determinate -- and "there is a 2.1.3, just not
    here" is exactly the fact a packaging engineer is reading this table for.
    """
    facts = channel_facts(_document(), channel=A_CHANNEL, platforms=[A_PLATFORM, ANOTHER_PLATFORM], source=A_SOURCE)

    published, absent = facts
    assert published.state == OutcomeState.OK
    assert absent.state == OutcomeState.NOT_FOUND
    assert absent.published_version == ""
    assert absent.build_string == ""
    assert absent.build_number is None
    assert NO_PUBLISHED_FILE_DETAIL in absent.detail
    assert A_VERSION in absent.detail


def test_a_file_of_an_older_version_does_not_publish_the_latest_one() -> None:
    """The version the channel calls latest is the one this collector records, and no other."""
    body = _document(files=_files((AN_OLDER_VERSION, A_PLATFORM, A_BUILD, A_BUILD_NUMBER)))

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.state == OutcomeState.NOT_FOUND
    assert A_VERSION in fact.detail


@pytest.mark.parametrize(
    "latest",
    [OMITTED, None, "", "   "],
    ids=["omitted", "explicit-null", "empty", "whitespace"],
)
def test_a_channel_that_names_no_latest_version_records_an_absence_per_platform_saying_so(latest: Any) -> None:
    """The matrix's "no latest version stated": absence with a reason, and one row per platform still."""
    facts = channel_facts(
        _document(latest=latest),
        channel=A_CHANNEL,
        platforms=[A_PLATFORM, ANOTHER_PLATFORM],
        source=A_SOURCE,
    )

    assert len(facts) == TWO_FACTS
    assert {fact.state for fact in facts} == {OutcomeState.NOT_FOUND}
    assert {fact.detail for fact in facts} == {NO_LATEST_VERSION_DETAIL}


@pytest.mark.parametrize("files", [OMITTED, None, []], ids=["omitted", "explicit-null", "empty"])
def test_a_channel_that_lists_no_file_at_all_records_an_absence_per_platform(files: Any) -> None:
    """A channel may state a latest version and serve no file this collector can attribute to a subdir."""
    facts = channel_facts(
        _document(files=files),
        channel=A_CHANNEL,
        platforms=[A_PLATFORM],
        source=A_SOURCE,
    )

    assert [fact.state for fact in facts] == [OutcomeState.NOT_FOUND]


def test_a_file_that_names_no_subdir_publishes_nothing_rather_than_everything() -> None:
    """A file this collector cannot attribute to a platform is one it says nothing about.

    Attributing it to the platform under test would record a build on a subdir the
    channel never named, which is the invented value PRD Appendix A.1 forbids.
    """
    body = _document(files=[{VERSION_FIELD: A_VERSION, ATTRS_FIELD: {BUILD_FIELD: A_BUILD}}])

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.state == OutcomeState.NOT_FOUND


def test_a_file_carrying_no_attributes_publishes_nothing_rather_than_failing_the_read() -> None:
    """A file with no `attrs` is one this collector can say nothing about, not a document it must refuse."""
    body = _document(files=[{VERSION_FIELD: A_VERSION}])

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.state == OutcomeState.NOT_FOUND


def test_a_subdir_is_matched_however_the_channel_spelled_its_case() -> None:
    """The declaration was lower-cased, so the document's own spelling is too."""
    body = _document(files=_files((A_VERSION, "LINUX-64", A_BUILD, A_BUILD_NUMBER)))

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.state == OutcomeState.OK


def test_several_builds_of_one_version_on_one_platform_record_the_highest_and_say_how_many() -> None:
    """All of them are published, so refusing to choose would record no build for a platform that has one.

    The highest build number is the one a fresh install resolves to, so it is the
    one recorded -- and `detail` says how many there were, because a reader
    comparing build strings across runs needs to know the column is a choice.
    """
    body = _document(
        files=_files(
            (A_VERSION, A_PLATFORM, A_BUILD, A_BUILD_NUMBER),
            (A_VERSION, A_PLATFORM, ANOTHER_BUILD, ANOTHER_BUILD_NUMBER),
        ),
    )

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.build_string == ANOTHER_BUILD
    assert fact.build_number == ANOTHER_BUILD_NUMBER
    assert str(TWO_BUILDS) in fact.detail


def test_a_build_that_states_no_number_loses_to_one_that_does() -> None:
    """`None` is not zero: a build whose number the channel did not state is not a first build."""
    body = _document(
        files=_files(
            (A_VERSION, A_PLATFORM, ANOTHER_BUILD, None),
            (A_VERSION, A_PLATFORM, A_BUILD, A_BUILD_NUMBER),
        ),
    )

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.build_number == A_BUILD_NUMBER
    assert fact.build_string == A_BUILD


def test_a_single_build_that_states_no_number_is_still_recorded() -> None:
    """NULL means missing and the row is still a determinate observation of a published version."""
    body = _document(files=_files((A_VERSION, A_PLATFORM, A_BUILD, None)))

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.state == OutcomeState.OK
    assert fact.build_number is None
    assert fact.build_string == A_BUILD


def test_a_version_published_only_under_a_non_default_label_is_recorded_and_says_so() -> None:
    """`latest_version` spans every label, so the row is not a claim about what an install resolves to.

    A channel whose newest upload is a release candidate on a `dev` label states
    that candidate as latest, and `CPM-FR-10` -- and this story's contract -- say
    the published version is the one the channel itself states. So the candidate is
    recorded, and the row says which labels the file it observed carried, because a
    reader who assumed the version and a default `conda install` agree would be
    wrong and nothing else on the row would tell them.
    """
    body = _document(A_RC_VERSION, [_labelled_file(["dev", "rc"], version=A_RC_VERSION)])

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.state == OutcomeState.OK
    assert fact.published_version == A_RC_VERSION
    assert OFF_LABEL_DETAIL in fact.detail
    assert "dev" in fact.detail
    assert DEFAULT_LABEL in fact.detail


@pytest.mark.parametrize(
    "labels",
    [[DEFAULT_LABEL], [DEFAULT_LABEL, "dev"], None, []],
    ids=["default-only", "default-among-others", "none-stated", "empty-list"],
)
def test_a_file_on_the_default_label_or_none_at_all_carries_no_caveat(labels: list[Any] | None) -> None:
    """The anti-vacuity half: the caveat is a caveat rather than a sentence on every row.

    A channel that states no labels has said nothing to caveat, and one that
    serves the file on the default label agrees with an install by construction.
    """
    body = _document(A_VERSION, [_labelled_file(labels)])

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.state == OutcomeState.OK
    assert OFF_LABEL_DETAIL not in fact.detail


@pytest.mark.parametrize("labels", ["main", [7], [None]], ids=["string", "ints", "nulls"])
def test_a_labels_field_of_the_wrong_shape_is_refused(labels: Any) -> None:
    """A source whose shape has changed is refused rather than read past."""
    body = _document(A_VERSION, [_labelled_file(labels)])

    with pytest.raises(CondaDocumentError, match=LABELS_FIELD):
        channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)


def test_two_builds_sharing_a_build_number_are_broken_by_the_build_string_and_the_row_says_so() -> None:
    """A tie-break recorded permanently must be one a later comparison can reproduce.

    Two builds of one version on one platform with the same build number is a real
    state of a channel -- two variants of the same build. Choosing by whichever the
    channel happened to list first would record a value that changes when the
    channel reorders its files, in a table nothing may correct, so the rule is the
    greatest build string and `detail` states it.
    """
    body = _document(
        A_VERSION,
        _files(
            (A_VERSION, A_PLATFORM, "aaa_0", A_BUILD_NUMBER),
            (A_VERSION, A_PLATFORM, "zzz_0", A_BUILD_NUMBER),
        ),
    )

    (fact,) = channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)

    assert fact.build_string == "zzz_0"
    assert fact.build_number == A_BUILD_NUMBER
    assert "ties broken by build string" in fact.detail


@pytest.mark.parametrize(
    "body", ["", "not json", "[]", '"a string"', "7"], ids=["empty", "text", "list", "string", "int"]
)
def test_a_document_that_is_not_an_object_is_refused(body: str) -> None:
    """A source whose shape has changed is refused rather than read for whatever still parses."""
    with pytest.raises(CondaDocumentError):
        channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)


@pytest.mark.parametrize(
    "document",
    [
        json.dumps({LATEST_VERSION_FIELD: 7}),
        json.dumps({LATEST_VERSION_FIELD: A_VERSION, FILES_FIELD: "not a list"}),
        json.dumps({LATEST_VERSION_FIELD: A_VERSION, FILES_FIELD: ["not an object"]}),
        json.dumps(
            {
                LATEST_VERSION_FIELD: A_VERSION,
                FILES_FIELD: [{VERSION_FIELD: A_VERSION, ATTRS_FIELD: "not an object"}],
            },
        ),
        json.dumps({LATEST_VERSION_FIELD: A_VERSION, FILES_FIELD: [{VERSION_FIELD: 7}]}),
        json.dumps(
            {
                LATEST_VERSION_FIELD: A_VERSION,
                FILES_FIELD: [{VERSION_FIELD: A_VERSION, ATTRS_FIELD: {SUBDIR_FIELD: A_PLATFORM, BUILD_FIELD: 7}}],
            },
        ),
        json.dumps(
            {
                LATEST_VERSION_FIELD: A_VERSION,
                FILES_FIELD: [
                    {
                        VERSION_FIELD: A_VERSION,
                        ATTRS_FIELD: {SUBDIR_FIELD: A_PLATFORM, BUILD_NUMBER_FIELD: "not a number"},
                    },
                ],
            },
        ),
        json.dumps(
            {
                LATEST_VERSION_FIELD: A_VERSION,
                FILES_FIELD: [
                    {VERSION_FIELD: A_VERSION, ATTRS_FIELD: {SUBDIR_FIELD: A_PLATFORM, BUILD_NUMBER_FIELD: True}},
                ],
            },
        ),
    ],
    ids=[
        "mistyped-latest",
        "mistyped-files",
        "file-not-an-object",
        "mistyped-attrs",
        "mistyped-file-version",
        "mistyped-build",
        "mistyped-build-number",
        "boolean-build-number",
    ],
)
def test_a_document_whose_shape_has_changed_is_refused(document: str) -> None:
    """Every field this collector reads is checked, `bool` refused with the rest.

    A `bool` is an `int` in Python and is not a build number in any document, so
    accepting one would store `True` as `1` and record a build nobody published.
    """
    with pytest.raises(CondaDocumentError):
        channel_facts(document, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)


@pytest.mark.parametrize("number", [-1, MAX_BUILD_NUMBER + 1], ids=["negative", "above-the-ceiling"])
def test_a_build_number_the_column_could_not_hold_is_refused_rather_than_clamped(number: int) -> None:
    """The ceiling is PostgreSQL's rather than the column validator's, and that is the `R-5` argument.

    Django derives a `PositiveIntegerField`'s validators from the *running*
    backend, so reading the limit off the field would accept, on SQLite, a number
    the deployed database refuses at insert -- and it would refuse it several
    frames past the `try` the translation is wrapped in.
    """
    body = _document(files=_files((A_VERSION, A_PLATFORM, A_BUILD, number)))

    with pytest.raises(CondaDocumentError, match=str(MAX_BUILD_NUMBER)):
        channel_facts(body, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)


def test_the_declared_build_ceiling_is_one_no_backend_this_product_runs_will_refuse() -> None:
    """The anti-vacuity half: a ceiling above the column's own would let a refused value through.

    Read off the field under test rather than restated, so a backend whose range
    is narrower than the declared ceiling fails here rather than at an insert.
    """
    field = CondaPackageSnapshot._meta.get_field("build_number")  # noqa: SLF001 - Django's own public-by-convention API
    ceilings = [
        validator.limit_value
        for validator in field.validators
        if getattr(validator, "limit_value", None) is not None and hasattr(validator, "compare")
    ]

    assert ceilings
    assert max(ceilings) >= MAX_BUILD_NUMBER


@pytest.mark.parametrize(
    ("field", "document"),
    [
        ("published_version", lambda width: _document(latest="9" * (width + 1))),
        (
            "build_string",
            lambda width: _document(files=_files((A_VERSION, A_PLATFORM, "b" * (width + 1), A_BUILD_NUMBER))),
        ),
    ],
    ids=["published-version", "build-string"],
)
def test_a_value_wider_than_its_column_is_refused_rather_than_truncated(field: str, document: Any) -> None:
    """A stored value that is not the value the channel published is a comparison wrong for ever."""
    width = CondaPackageSnapshot._meta.get_field(field).max_length  # noqa: SLF001 - Django's own public-by-convention API
    assert width is not None

    with pytest.raises(CondaDocumentError, match=str(width)):
        channel_facts(document(width), channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)


def test_a_document_larger_than_the_ceiling_is_refused_before_it_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bound is on the parse, and the message says so rather than claiming to save memory.

    The real ceiling is lowered for the case, so the suite does not build
    thirty-two mebibytes to prove a comparison.
    """
    monkeypatch.setattr(conda_package_module, "MAX_DOCUMENT_CHARACTERS", 8)

    with pytest.raises(CondaDocumentError, match="8"):
        channel_facts(_document(), channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)


def test_a_deeply_nested_document_is_refused_rather_than_crashing_the_worker() -> None:
    """`json.loads` recurses per level, and an uncaught `RecursionError` names this module rather than the source."""
    with pytest.raises(CondaDocumentError):
        channel_facts("[" * 100_000, channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)


def test_the_document_refusals_name_the_source_they_are_about() -> None:
    """A run reads several locators, so a refusal that did not name one says nothing useful."""
    with pytest.raises(CondaDocumentError, match=A_SOURCE):
        channel_facts("not json", channel=A_CHANNEL, platforms=[A_PLATFORM], source=A_SOURCE)


# ---------------------------------------------------------------------------
# The rows (`sentinel_evidence`, `__str__`).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [OutcomeState.ERROR, OutcomeState.NOT_FOUND],
    ids=lambda state: state.value,
)
def test_a_sentinel_row_carries_the_state_and_no_published_fact(state: OutcomeState) -> None:
    """Two shapes, one per sentinel the base may ask this collector for, and every published fact absent."""
    collector = CondaPackageCollector(clock=_stopped_clock())
    try:
        collector._monitored = Monitored(channels=(A_CHANNEL,), platforms=(A_PLATFORM,))  # noqa: SLF001 - what `source_for` remembers
        row = collector.sentinel_evidence(
            state=state,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="a reason",
        )
    finally:
        collector.close()

    assert isinstance(row, CondaPackageSnapshot)
    assert row.state == state.value
    assert row.observed_at == FIXED_INSTANT
    assert row.package_id == A_PACKAGE
    assert row.source == ""
    assert row.channel == A_CHANNEL
    assert row.platform == A_PLATFORM
    assert row.published_version == ""
    assert row.build_string == ""
    assert row.build_number is None
    assert row.detail == "a reason"


def test_a_sentinel_row_names_the_pair_the_bases_one_call_was_about() -> None:
    """Every row names a channel and a platform, and the base's call was about the first of each."""
    collector = CondaPackageCollector(clock=_stopped_clock())
    try:
        collector._monitored = Monitored(  # noqa: SLF001 - what `source_for` remembers through the base
            channels=(A_CHANNEL,),
            platforms=(A_PLATFORM,),
        )
        row = collector.sentinel_evidence(
            state=OutcomeState.NOT_FOUND,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="a reason",
        )
    finally:
        collector.close()

    assert row.channel == A_CHANNEL  # type: ignore[attr-defined]
    assert row.platform == A_PLATFORM  # type: ignore[attr-defined]
    assert row.detail == "a reason"  # type: ignore[attr-defined]


def test_a_failing_run_owes_an_error_row_for_every_pair_and_asks_nothing() -> None:
    """The `error` branch of the plural hook: a row per pair, and no call of any kind.

    `error` is reachable from a *refused allowance* as well as from a failed call,
    and by the time the hook runs the base has declared the run `failed`. So this
    branch may not reach the transport -- which is asserted here by handing the
    collector a transport that has nothing scripted, so any call at all would
    raise rather than pass quietly.
    """
    transport = ScriptedTransport()
    collector = CondaPackageCollector(clock=_stopped_clock(), transport=transport)
    try:
        collector._monitored = Monitored(  # noqa: SLF001 - what `source_for` remembers through the base
            channels=(A_CHANNEL, ANOTHER_CHANNEL),
            platforms=(A_PLATFORM, ANOTHER_PLATFORM),
        )
        rows = collector.sentinel_evidence_rows(
            state=OutcomeState.ERROR,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="a reason",
        )
    finally:
        collector.close()

    assert len(rows) == FOUR_PAIRS
    assert len({(row.channel, row.platform) for row in rows}) == FOUR_PAIRS  # type: ignore[attr-defined]
    assert {row.state for row in rows} == {OutcomeState.ERROR.value}  # type: ignore[attr-defined]
    assert {row.detail for row in rows} == {"a reason"}  # type: ignore[attr-defined]
    assert transport.calls == []


@pytest.mark.parametrize(
    "declared",
    [Monitored(channels=(), platforms=()), Monitored(channels=(A_CHANNEL,), platforms=())],
    ids=["nothing-remembered", "channels-but-no-platforms"],
)
@pytest.mark.parametrize("hook", ["sentinel_evidence", "sentinel_evidence_rows"], ids=["singular", "plural"])
def test_a_sentinel_asked_before_a_declaration_was_read_is_refused_by_name(declared: Monitored, hook: str) -> None:
    """A blank pair is a row the table refuses, several frames from the call that was wrong.

    The base's `not_found` branch does **not** wrap its write, so an
    `IntegrityError` from a blank `channel` would escape raw and replace the
    reason the run was recording. Refused here instead, naming the two settings
    that were never read. The half-declared case is the one an `IndexError` would
    have come out of, from a hook that must not raise.

    Unreachable through `collect()`, where `source_for` refuses an empty or
    half-empty declaration before the base gets anywhere near a sentinel.
    """
    collector = CondaPackageCollector(clock=_stopped_clock())
    try:
        collector._monitored = declared  # noqa: SLF001 - what `source_for` remembers through the base
        with pytest.raises(CollectorConfigurationError, match=CHANNELS_SETTING):
            getattr(collector, hook)(
                state=OutcomeState.ERROR,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="a reason",
            )
    finally:
        collector.close()


@pytest.mark.parametrize(
    "state",
    [OutcomeState.OK, OutcomeState.UNKNOWN, OutcomeState.NOT_APPLICABLE],
    ids=lambda state: state.value,
)
def test_the_plural_hook_shapes_a_row_for_any_state_rather_than_refusing_one(state: OutcomeState) -> None:
    """The hook the base calls is **total** over states, and that is a decision rather than an oversight.

    `sentinel_evidence` refuses `ok`, `unknown` and `not_applicable`, and stays the
    hook a caller reaching this collector directly meets. The plural one is called
    from paths that are already recording a failure -- `_write_sentinel` does not
    wrap it -- so a raise there would replace the reason the run is recording with
    a message about the collector. It records instead, and what stands behind it is
    the base's own pair of checks: the state carried verbatim, and no determinate
    row written under a failed run.
    """
    collector = CondaPackageCollector(clock=_stopped_clock())
    try:
        collector._monitored = Monitored(channels=(A_CHANNEL,), platforms=(A_PLATFORM,))  # noqa: SLF001 - as above
        rows = collector.sentinel_evidence_rows(
            state=state,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="a reason",
        )
        with pytest.raises(CollectorConfigurationError, match=state.value):
            collector.sentinel_evidence(
                state=state,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="a reason",
            )
    finally:
        collector.close()

    assert [row.state for row in rows] == [state.value]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "state",
    [OutcomeState.OK, OutcomeState.UNKNOWN, OutcomeState.NOT_APPLICABLE],
    ids=lambda state: state.value,
)
def test_a_sentinel_state_this_collector_has_no_row_for_is_refused(state: OutcomeState) -> None:
    """Refused at the call rather than at the insert, which is where it would land.

    `ok` because a row carrying it and no published version is refused by the
    table's own constraint; `unknown` because it is what a package with *no* row
    reads as; and `not_applicable` because a published-artifact question applies to
    every package -- this collector's `inapplicability` never answers a reason, so
    the base never asks for that sentinel and a row carrying one would name a
    channel nobody asked about.
    """
    collector = CondaPackageCollector(clock=_stopped_clock())
    try:
        with pytest.raises(CollectorConfigurationError, match=state.value):
            collector.sentinel_evidence(
                state=state,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="a reason",
            )
    finally:
        collector.close()


def test_the_question_applies_to_every_package_and_the_hook_forgets_the_last_run() -> None:
    """Two claims in one hook, and the second is why it is overridden at all.

    Nothing about a package can make "is it published on a monitored channel"
    inapplicable, so the answer is always the empty string. What the override
    buys is the reset: `inapplicability` is the first thing the base calls on
    every run, which makes it the one place a remembered declaration can be
    forgotten before the next run reads it.
    """
    collector = CondaPackageCollector(clock=_stopped_clock())
    try:
        collector._monitored = Monitored(channels=(A_CHANNEL,), platforms=(A_PLATFORM,))  # noqa: SLF001 - as above
        collector._package_name = A_NAME  # noqa: SLF001 - as above
        collector._locator = THE_LOCATOR  # noqa: SLF001 - as above

        assert collector.inapplicability(package_id=A_PACKAGE) == ""

        assert collector._monitored == Monitored(channels=(), platforms=())  # noqa: SLF001 - as above
        assert collector._package_name == ""  # noqa: SLF001 - as above
        assert collector._locator == ""  # noqa: SLF001 - as above
    finally:
        collector.close()


def test_an_unsaved_snapshot_renders_its_absences_rather_than_raising() -> None:
    """A `__str__` that raises is what a failure message would have been."""
    rendered = str(CondaPackageSnapshot())

    assert "nothing published" in rendered
    assert "no channel" in rendered
    assert "no platform" in rendered
    assert "no package" in rendered
    assert "never" in rendered


def test_a_saved_snapshots_rendering_names_what_it_observed() -> None:
    """The anti-vacuity half: the placeholders are placeholders rather than the answer."""
    rendered = str(
        CondaPackageSnapshot(
            observed_at=FIXED_INSTANT,
            package_id=A_PACKAGE,
            state=OutcomeState.OK.value,
            channel=A_CHANNEL,
            platform=A_PLATFORM,
            published_version=A_VERSION,
        ),
    )

    assert A_VERSION in rendered
    assert A_CHANNEL in rendered
    assert A_PLATFORM in rendered
    assert str(A_PACKAGE) in rendered
    assert OutcomeState.OK.value in rendered
    assert FIXED_INSTANT.isoformat() in rendered


# ---------------------------------------------------------------------------
# The module's own source.
# ---------------------------------------------------------------------------


def test_the_collector_module_writes_no_row_of_any_kind() -> None:
    """`CPM-AD-7` and `CPM-AD-14`: this collector reads `identity` and writes evidence through the base."""
    tree = parse(_conda_package_module())
    written = sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and dotted_name(node.func).rpartition(".")[2] in WRITE_METHODS
    )

    assert written == [], f"the collector reaches a table directly at lines {written}"


def test_the_collector_module_reads_the_one_identity_model_it_is_allowed_to_read() -> None:
    """The anti-vacuity half: a module that named no model would sweep clean.

    `CPM-AD-7` is "a collector writes its own evidence table and reads only
    `identity`", and this collector's read is one column of `Package`: the
    canonical name a channel serves the package under. No mapping is consulted,
    because nothing a resolution recorded can make a published-artifact question
    inapplicable.
    """
    named = {node.id for node in ast.walk(parse(_conda_package_module())) if isinstance(node, ast.Name)}

    assert PACKAGE_MODEL_NAME in named
    assert "PackageMapping" not in named


def test_the_collector_module_opens_no_transaction_of_its_own() -> None:
    """The per-package transaction is the base's, around the evidence write (`CPM-AD-23`)."""
    tree = parse(_conda_package_module())
    opened = sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and dotted_name(node.func).endswith("transaction.atomic")
    )

    assert opened == []


def test_the_collector_module_imports_no_other_collector_and_no_config() -> None:
    """`CPM-AD-7` and inherited `AD-4`, asserted rather than assumed.

    The shared `User-Agent` lives in `collectors/agent.py` so that the first half
    can be true. The second is what this story adds: the monitored surfaces are a
    *settings read* rather than a `config` import, and a module that reached for
    `config.locality` to pick a channel itself would fail here.
    """
    imported = {
        node.module
        for node in ast.walk(parse(_conda_package_module()))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        module.endswith((".source_release", ".pypi_release", ".feedstock", ".tasks")) for module in imported
    ), imported
    assert not any(module == "config" or module.startswith("config.") for module in imported), imported
    assert any(module.endswith(".collectors.agent") for module in imported)
    assert "django.conf" in imported


@pytest.mark.parametrize("setting", [CHANNELS_SETTING, PLATFORMS_SETTING], ids=["channels", "platforms"])
def test_a_settings_module_declaring_no_monitored_surfaces_refuses_at_boot_by_name(setting: str) -> None:
    """A misconfiguration says which setting is missing, on the terms the watchlist setting is refused.

    The distinction this rests on is between a settings module that declares
    **nothing** -- refused here, because the alternative is an `AttributeError`
    out of a boot hook naming an attribute and nothing else -- and one that
    declares an **empty** list, which is what ships and is a component honestly
    saying no operator has chosen yet. The second is emphatically *not* a boot
    failure, which the case below pins.
    """
    with override_settings():
        delattr(settings, setting)

        with pytest.raises(ImproperlyConfigured) as refused:
            apps.get_app_config(COLLECTORS_APP_LABEL).ready()

    assert setting in str(refused.value)


@pytest.mark.parametrize("setting", [CHANNELS_SETTING, PLATFORMS_SETTING], ids=["channels", "platforms"])
@pytest.mark.parametrize("declared", [A_CHANNEL, 7, {A_CHANNEL: 1}], ids=["bare-string", "int", "mapping"])
def test_a_settings_module_declaring_the_wrong_shape_refuses_at_boot_too(setting: str, declared: Any) -> None:
    """A shape that can never become a usable declaration is a start-up failure, not a run-time one.

    `CPM_MONITORED_CHANNELS = "conda-forge"` is the misconfiguration this module
    goes to length to describe -- Python reads it as eleven one-character channels
    -- and a boot check that asked only whether the name *existed* would let it
    through, leaving a component that boots clean and fails every collection for
    ever with nothing said at start-up. The shape is asked through the collector's
    own rule, so boot and run time cannot come to disagree about what a
    declaration may be.
    """
    with override_settings(**{setting: declared}), pytest.raises(ImproperlyConfigured) as refused:
        apps.get_app_config(COLLECTORS_APP_LABEL).ready()

    assert setting in str(refused.value)


def test_an_empty_declaration_is_not_a_boot_failure() -> None:
    """The shipped state must start: a component that refused to boot until an operator chose would be useless.

    This is the half a truth test in the boot hook would have got wrong, and it is
    the whole posture of the story: the mechanism ships, the choice does not, and
    what an undeclared surface costs is a `failed` collection naming the setting
    rather than a component nobody can start.
    """
    with override_settings(**{CHANNELS_SETTING: (), PLATFORMS_SETTING: ()}):
        apps.get_app_config(COLLECTORS_APP_LABEL).ready()


def test_a_further_channels_call_answers_rather_than_raises_when_it_cannot_even_name_a_locator() -> None:
    """Nothing in a further channel's call may raise, and the locator is part of "nothing".

    Every other way of not finding out -- a transport failure, a `304`, an
    unreadable document -- is caught and returned as rows that say so. So is this
    one, and it is the least likely and the worst if it were not: an exception from
    here would leave `translate` and turn the answers the channels *before* it had
    already given into a single `error` row and a `failed` run, which is precisely
    the invariant `CPM-FR-15` and `docs/deployment.md` both state.

    It is unreachable through `collect()` today -- `source_for` builds the first
    channel's locator from the same name and refuses the run if it cannot -- so it
    is asserted here, against the method, rather than left to be a claim in a
    docstring that nothing checks.
    """
    transport = ScriptedTransport()
    collector = CondaPackageCollector(clock=_stopped_clock(), transport=transport)

    try:
        collector._package_name = "not a package name"  # noqa: SLF001 - what `source_for` remembers through the base
        facts = collector._channel_instead(  # noqa: SLF001 - the bounded call under test
            channel=ANOTHER_CHANNEL,
            platforms=[A_PLATFORM, ANOTHER_PLATFORM],
        )
    finally:
        collector.close()

    assert len(facts) == TWO_FACTS
    assert {fact.state for fact in facts} == {OutcomeState.ERROR}
    assert {fact.channel for fact in facts} == {ANOTHER_CHANNEL}
    assert {fact.source for fact in facts} == {""}
    assert all(UNREAD_CHANNEL_DETAIL in fact.detail for fact in facts)
    # And no call was made, because there was no locator to make one to.
    assert transport.calls == []
