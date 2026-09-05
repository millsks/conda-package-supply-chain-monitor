"""The collector base: every external-call rule in one place, written once.

`CPM-AD-20` puts "rate limiting, retry with backoff, timeouts and caching ... in
a shared collector base in `core`, not per collector", and `CPM-AD-27` puts the
transport boundary here so that a collector is a pure translation from a recorded
payload to evidence rows. Eight collectors are coming. Written eight times these
rules would differ eight ways, and the difference that matters is not cosmetic:
`CPM-NFR-3` says the system "degrades to stale evidence, never to a clean
result", and a rate-limited source quietly producing an empty parse is exactly
that failure.

**What a subclass supplies, and what it never touches.** It declares six values
-- `name`, `evidence_model`, `observation_window`, `timeout`, `retries`,
`rate_limit` -- and implements three methods: which source to read, how to turn a
payload into evidence rows, and how to shape one sentinel row for a table only it
knows. It never sees a socket, a session, a retry policy, a cache or a clock
read. Every one of those is applied here.

**The order is the whole guarantee, and it is written out rather than implied:**

```python
with collection_run(collector=self.name, clock=clock, package_id=package_id) as run:
    payload = self._transport.fetch(...)          # outside any transaction
    with transaction.atomic():                    # nested, one package
        self.evidence_model.objects.bulk_create(self.translate(payload))
```

**The run ledger is written outside any transaction this base opens.** That is
`CPM-EVIDENCE-S03`'s recorded, deferred constraint arriving at the story that
makes it enforceable. `core/ledger.py` states it: the `running` row is only worth
having because it is *committed* before the outbound call, so a caller wrapping
the recorder in `transaction.atomic()` and then being killed loses the row and
the ledger is back to recording nothing. No runtime guard was available -- pytest's
`django_db` runs every test inside exactly such a block, so a check on
`connection.in_atomic_block` would refuse the whole suite -- and the guard that
*is* available is a source sweep. This module is the first thing there was to
sweep, and `tests/unit/django_apps/test_collector_base_audit.py` is the sweep. It
runs in both directions: no transaction may enclose the recorder, and every
evidence write here must be inside one.

**The atomic unit is one package's evidence write** (`CPM-AD-23`), nested inside
the recorder and never around it. A later package's failure never rolls back an
earlier package's evidence, which is what makes `CPM-FR-15`'s partial success
reachable at all.

**Never a clean result, and never no row.** Every path that reaches the transport
writes evidence. A call that ultimately fails writes a row carrying `error`; a
source that answered "this does not exist" writes one carrying `not_found`; a
translation that raises writes `error` and *then* lets the exception out; and a
translation that returns **nothing** writes `error` too, because a parser that
found no rows in a body the source served is a parser that no longer matches its
source, and recording that as a clean success is the `R-01` ambiguity the outcome
vocabulary exists to remove. Both states come from `core/outcomes.py`'s
vocabulary and neither is `ok` (`CPM-AD-5`), and the base checks that the row a
collector hands back actually carries the state it was asked for.

The one path that writes nothing is the observation window, and it writes nothing
on purpose: `CPM-AD-7` says a second run inside the window records a ledger row
with status `skipped` and no evidence, which is a *decision not to observe*
rather than an observation.

**Re-observation inserts, and the instant is checked on the way in.** Evidence
goes through `AppendOnlyModel`, so this base uses `bulk_create` and never
`update_or_create` (`CPM-AD-2`). `bulk_create` does not call `save()`, which
means it bypasses the naive-`observed_at` refusal `core/models.py` calls "the one
place every evidence write passes through" -- so that refusal is restored here,
strengthened: every row must carry *exactly* the instant this run was handed, not
merely an aware one. One observation has one moment (`CPM-AD-7`), and a collector
that stamped rows from somewhere else would make every freshness comparison and
every observation window silently wrong.

**Rate limiting is reconciled with retry.** The limiter is charged `1 + retries`
per collection, because that is how many real requests the mounted retry policy
may issue. See `core/rate_limit.py`.

**Freshness targets and observation-window values are not chosen here.** They are
PRD Open Question 7 and are declared per collector; this module builds the
mechanism and reads them. The startup refusal for a collector that declares no
freshness target is `CPM-EVIDENCE-S06`'s (`CPM-AD-28`) and is deliberately not
here -- declaring it in two places would leave two enforcement points.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final
from typing import Self

import structlog
from django.db import DatabaseError
from django.db import models
from django.db import transaction

from conda_package_supply_chain_monitor.core.clock import is_aware
from conda_package_supply_chain_monitor.core.ledger import collection_run
from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.rate_limit import CacheRateLimiter
from conda_package_supply_chain_monitor.core.rate_limit import RateLimit
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.core.transport import DEFAULT_RETRIES
from conda_package_supply_chain_monitor.core.transport import RequestsTransport
from conda_package_supply_chain_monitor.core.transport import TransportError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from types import TracebackType

    from conda_package_supply_chain_monitor.core.clock import Clock
    from conda_package_supply_chain_monitor.core.ledger import RunHandle
    from conda_package_supply_chain_monitor.core.rate_limit import RateLimiter
    from conda_package_supply_chain_monitor.core.transport import Payload
    from conda_package_supply_chain_monitor.core.transport import Transport

__all__ = [
    "COLLECTION_FAILED_EVENT",
    "COLLECTION_REFUSED_EVENT",
    "COLLECTION_SKIPPED_EVENT",
    "EVENT_KEYS",
    "NO_WINDOW",
    "SUPPRESSING_STATES",
    "CollectionResult",
    "CollectionWriteError",
    "Collector",
    "CollectorConfigurationError",
    "has_recent_success",
    "window_query",
]

logger = structlog.get_logger(__name__)

#: The event a windowed skip is logged under. Dotted, as
#: `config/health/drain.py`'s `drain.begin` is; named so the case that asserts
#: the log and the code that emits it cannot drift, exactly as
#: `core/ledger.py`'s `FINALIZATION_FAILED_EVENT` is and
#: `tests/integration/django_apps/test_run_ledger.py` proves.
COLLECTION_SKIPPED_EVENT: Final[str] = "collection.skipped_inside_window"

#: The event a rate-limit refusal is logged under. Distinct from a failure: the
#: call was never issued, which is a different operational fact from a source
#: that answered badly, and an operator reading "why did this collect nothing"
#: needs to tell them apart.
COLLECTION_REFUSED_EVENT: Final[str] = "collection.refused_by_rate_limit"

#: The event a failed call is logged under. Emitted from three places -- a
#: transport failure, a translation that raised, and a translation that found
#: nothing -- and every one of them carries the same keys, so a log query does
#: not have to know which.
COLLECTION_FAILED_EVENT: Final[str] = "collection.failed"

#: The keys every one of the four events above carries, and the reason they are
#: named here. A `detail` that is an exception's `"Type: message"` on two paths
#: and a sentence on the third is two schemas wearing one key, and a log query
#: written against either would be wrong half the time. So the value is fixed as
#: *the same string the ledger row's `detail` column carries* on every path --
#: which is also what `CollectionResult.detail` promises a caller.
EVENT_KEYS: Final[tuple[str, ...]] = ("collector", "package_id", "source")

#: The shortest window that means anything. Zero is permitted and means "never
#: skip": a collector that should observe on every run says so by declaring it,
#: which is a decision a reader can see, rather than by omitting the value. It is
#: also short-circuited rather than queried -- see `Collector.collect`.
NO_WINDOW: Final[timedelta] = timedelta(0)

#: The run states that suppress a later observation inside the window.
#:
#: Exactly one. `failed` is excluded because a source that is broken must not
#: suppress the observation that would record it as broken; `partial` is excluded
#: because a run that did *some* of its work did not observe this package
#: completely, and treating it as an observation is the same false-clean move by
#: a quieter route; `running` is excluded because it has not finished. Derived as
#: a set rather than written into the query so the decision is one a reader meets
#: rather than one they infer from a keyword.
SUPPRESSING_STATES: Final[frozenset[RunState]] = frozenset({RunState.SUCCEEDED})


class CollectorConfigurationError(ValueError):
    """A collector's declared configuration cannot be used to make a call.

    One type rather than a hierarchy, on the same terms as `core/models.py`'s
    `AppendOnlyError`: every occurrence is a defect in a class definition or in
    an override of one, to be fixed where that code is written, and no caller
    branches on which declaration was wrong. The detail is in the message.

    A `ValueError` subclass, matching `core/rate_limit.py`'s `RateLimitError` and
    `core/outcomes.py`'s `OutcomeVocabularyError`: every "this declaration is
    unusable" in this product is a `ValueError`, so a caller catching one catches
    them all. `core/transport.py`'s `TransportError` is deliberately not one -- a
    source being down is not a declaration defect.

    It is raised at **construction** wherever it can be, which is the matrix row
    `CPM-EVIDENCE-S05` states in so many words: a collector configured with no
    timeout is refused when it is built. The alternative is a worker discovering
    it halfway through a sweep, with a run ledger row already `running` and a
    source already contacted. The two checks that cannot happen at construction --
    that `translate` stamps the instant it was handed, and that
    `sentinel_evidence` carries the state it was asked for -- are made at the
    write, which is the first moment the answer exists.
    """


class CollectionWriteError(Exception):
    """Evidence could not be written, on a path that was already recording a failure.

    Not a declaration defect and so not a `ValueError`. It exists for one
    ordering hazard: on a failing path the base has a *reason* -- the source was
    unreachable, the allowance was spent, the parser broke -- and it then writes
    a sentinel row. If that write raises, the database error would reach the run
    recorder and become the ledger row's `detail`, replacing the reason with a
    message about the write. So the write's failure is wrapped in this, carrying
    both, and `core/ledger.py`'s recorder records the pair.

    Attributes:
        detail: The reason the run was already failing, preserved verbatim so a
            reader is never left with only the epitaph.

    """

    def __init__(self, message: str, *, detail: str) -> None:
        """Record the combined message and the original reason.

        Args:
            message: The reason and the write failure, in that order.
            detail: The reason on its own.

        """
        super().__init__(message)
        self.detail = detail


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """What one collection run did, for the caller that asked for it.

    The ledger row is the durable record and this is the immediate answer: a
    Celery task (`CPM-EVIDENCE-S04`'s, not this story's) returns it, and a test
    asserts against it without reading the row back. Frozen, because it is a
    report rather than a workspace.

    Attributes:
        state: How the run ended, over `RunState` -- the same value the ledger
            row carries, never `RunState.RUNNING`.
        evidence_rows: How many evidence rows were inserted. Zero only for a
            windowed skip; every other path writes at least one row, which is
            `CPM-NFR-3`'s "never no row".
        detail: Why the run ended this way, in the same words the ledger row's
            `detail` carries -- every terminal path declares the same string to
            both, which
            `tests/integration/django_apps/test_collection.py` asserts. Empty for
            a plain success, which needs no explanation.

    """

    state: RunState
    evidence_rows: int
    detail: str


def window_query(*, collector: str, package_id: int, since: datetime) -> models.Q:
    """Return the filter that finds a successful observation inside the window.

    Four conditions, and three of them are the matrix rows that would otherwise
    be silent. `collector` and `package_id` are what make the window
    *per collector and per package*: a recent run of another collector, or of
    this one against another package, must not suppress this observation.
    `status` is what makes only a **succeeded** run suppress -- see
    `SUPPRESSING_STATES` for why `failed` and `partial` are both excluded and
    what each exclusion prevents.

    `finished_at` rather than `started_at` is the authority for the same reason
    `RunLedgerQuerySet.unfinished()` reads it: it is the column the recorder's
    `finally` writes, so it exists exactly when the run has an ending.

    Args:
        collector: The declared collector name, as its ledger rows carry it.
        package_id: The package the window is being asked about, by the integer
            primary key `CPM-AD-3` fixes.
        since: The start of the window -- `now` minus the declared observation
            window, from the injected clock (`CPM-AD-26`).

    Returns:
        A `Q` naming all four conditions. Returned as a `Q` rather than applied
        here so that `tests/unit/django_apps/test_collection.py` can assert its
        shape without a database: the three conditions above are the difference
        between a correct window and one that suppresses the wrong runs, and
        each of them is one keyword away from being absent.

    """
    return models.Q(
        collector=collector,
        package_id=package_id,
        status__in=sorted(state.value for state in SUPPRESSING_STATES),
        finished_at__gte=since,
    )


def has_recent_success(*, collector: str, package_id: int, since: datetime) -> bool:
    """Report whether this collector already observed this package inside the window.

    Args:
        collector: The declared collector name.
        package_id: The package being collected.
        since: The start of the window.

    Returns:
        True when a `succeeded` run for this collector and package finished at
        or after `since`. `exists()` rather than a fetch: the answer is a
        boolean and the rows are not wanted.

    """
    return CollectionRun.objects.filter(window_query(collector=collector, package_id=package_id, since=since)).exists()


class Collector(ABC):
    """The base every collector inherits, and the only code that makes a call.

    **Declared configuration, not implemented behaviour.** The six class
    attributes below are what a subclass states about itself; every one of them
    is checked -- for presence *and* for type -- when the collector is
    constructed, so a class that forgets one, or declares a string where an
    interval belongs, fails where it is built with a message naming the
    declaration rather than with a `TypeError` from somewhere downstream.
    `CPM-AD-20`'s rule -- that these live in one shared base -- is only true if a
    subclass has no way of its own to make a call, and the abstract methods are
    shaped so that it does not: it says *what* to fetch and *what a payload
    means*, and never *how* to fetch.

    **Three abstract methods, and the third is not an accident.** `translate` is
    the one `CPM-AD-27` is about. `source_for` is what makes the URL a property
    of the collector rather than of the base. `sentinel_evidence` exists because
    the base owns the *rule* -- an `error` row for a failed call, a `not_found`
    row for an absent resource, always, never `ok` -- while the collector owns
    the *shape* of a row in a table `CPM-AD-7` gives it and this base has never
    seen. A base that built the row itself would need a concrete evidence model,
    which `CPM-AD-7` puts in `CPM-EP-CURRENCY` and which this story is forbidden
    to invent. What the base does *not* do is trust the result: it checks that
    the row carries the state it asked for, because a subclass that ignored the
    argument and wrote `ok` would defeat "never a clean result" entirely and
    would type-check perfectly.

    **The clock is a constructor parameter and there is no default**
    (`CPM-AD-26`): `observed_at`, the window comparison, the rate-limit window
    and the ledger's two instants all read it, and a base that reached for
    `SystemClock()` on its own would make every window test a statement about how
    long the test took.

    **It is closable, and it is a context manager.** A collector that was handed
    no transport builds one, and that transport holds a connection pool; `close()`
    releases it and closes nothing the caller owns.
    """

    #: What this collector is called, on its ledger rows and in its cache keys.
    #: A blank name is refused: `CPM-FR-39` needs a run traceable to the code
    #: that performed it, and `core/ledger.py` refuses one for the same reason.
    name: ClassVar[str] = ""

    #: The append-only table this collector writes (`CPM-AD-7`: its own, never
    #: another collector's). Declared rather than owned by this base, which
    #: deliberately holds no concrete evidence model. It must inherit
    #: `AppendOnlyModel`: a plain `Model` would satisfy every type annotation
    #: here and would go around every refusal `CPM-AD-2` exists to make.
    evidence_model: ClassVar[type[AppendOnlyModel] | None] = None

    #: How long a successful observation suppresses the next one (`CPM-AD-7`).
    #: The *value* is PRD Open Question 7 and is not chosen here.
    #: `NO_WINDOW` is permitted and means "observe on every run".
    observation_window: ClassVar[timedelta | None] = None

    #: Seconds any single connect or read phase may take. Applied by the
    #: transport this base builds from it; refused at construction when it is
    #: absent, which is the matrix row that says a timeout has no default-less
    #: path. `core/transport.py` says what the value does and does not bound.
    timeout: ClassVar[float | None] = None

    #: How many times a failed request is retried. Declared here as well as
    #: applied by the transport, because it is what the rate limiter is charged:
    #: one collection may issue `1 + retries` requests, and an allowance that
    #: counted collections would not bound requests at all.
    retries: ClassVar[int] = DEFAULT_RETRIES

    #: How hard this collector may push its source (`CPM-AD-20`). Required
    #: rather than optional: "never issued unlimited" is not a property a
    #: collector gets to opt out of by omission.
    rate_limit: ClassVar[RateLimit | None] = None

    def __init__(
        self,
        *,
        clock: Clock,
        transport: Transport | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        """Check the declared configuration and build what it describes.

        Args:
            clock: The clock every instant in this run is read from
                (`CPM-AD-26`). No default: a component's dependence on time
                belongs in its signature.
            transport: The seam `CPM-AD-27` opens. Defaults to a
                `RequestsTransport` carrying this collector's declared timeout
                and retry count, which is the only place either becomes a call
                setting. A test substitutes a fake returning recorded payloads,
                and `CPM-AD-29`'s inventory adapter substitutes a file reader.
            limiter: The rate limiter, defaulting to the shared cache-backed one.
                Substituted in a test that wants a refusal without arranging a
                cache state.

        Raises:
            CollectorConfigurationError: When any declared value is absent, of
                the wrong type, or unusable. Raised here rather than at call
                time, so a misdeclared collector never reaches a source.

        """
        label = type(self).__name__
        self._name = _require_name(self.name, label=label)
        self._evidence_model = _require_evidence_model(self.evidence_model, label=label)
        self._window = _require_window(self.observation_window, label=label)
        self._timeout = _require_timeout(self.timeout, label=label)
        self._retries = _require_retries(self.retries, label=label)
        self._rate_limit = _require_rate_limit(self.rate_limit, label=label)
        self._clock: Clock = clock
        # Ownership is tracked so `close()` releases only what this object
        # built. Closing a transport the caller supplied would take a pool away
        # from whoever else is holding it, which is the kind of tidy-up that is
        # only ever discovered in production.
        self._owns_transport = transport is None
        self._transport: Transport = (
            RequestsTransport(timeout=self._timeout, retries=self._retries) if transport is None else transport
        )
        self._limiter: RateLimiter = CacheRateLimiter() if limiter is None else limiter

    def __enter__(self) -> Self:
        """Return this collector, so a caller can scope its connection pool.

        Returns:
            This collector, unchanged. Typed `Self` so a subclass's own methods
            stay visible to a caller that entered the block.

        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release anything this collector built.

        Args:
            exc_type: The exception's type, if one is leaving the block.
            exc: The exception, if one is leaving the block.
            traceback: Its traceback, if one is leaving the block.

        """
        self.close()

    def close(self) -> None:
        """Release the connection pool, if this collector built one.

        A transport the caller supplied is left alone: it belongs to whoever
        made it, and may well outlive this collector.
        """
        if self._owns_transport and isinstance(self._transport, RequestsTransport):
            self._transport.close()

    @property
    def request_cost(self) -> int:
        """Return how many requests one collection may issue.

        Returns:
            `1 + retries`. This is what the rate limiter is charged per
            collection, so a declared allowance bounds *requests* rather than
            bounding collections while the retry policy multiplies underneath
            it (`core/rate_limit.py`).

        """
        return 1 + self._retries

    @abstractmethod
    def source_for(self, *, package_id: int) -> str:
        """Return the locator this collector reads for one package.

        Args:
            package_id: The package being collected, by the integer primary key
                `CPM-AD-3` fixes.

        Returns:
            The URL, path or other locator to hand the transport.

        """

    @abstractmethod
    def translate(self, payload: Payload, *, package_id: int, observed_at: datetime) -> Sequence[AppendOnlyModel]:
        """Turn a recorded payload into unsaved evidence rows.

        The method `CPM-AD-27` exists for: it takes data, returns data, and
        needs no network to test. It is called only for a payload the source
        answered successfully -- absence and failure are the base's to record --
        so it never has to decide whether it was handed a real answer.

        Args:
            payload: What the source said, recorded.
            package_id: The package the observation is about.
            observed_at: The instant to stamp every row with, from the injected
                clock. Passed in rather than read, because `observed_at` means
                "the moment of *this* observation" (`CPM-AD-7`); the base
                refuses a row stamped with anything else.

        Returns:
            At least one unsaved row for this collector's evidence model. The
            base inserts them; an implementation that saved them itself would
            write outside the per-package transaction. Returning nothing is a
            failure, not a success -- see the module docstring.

        """

    @abstractmethod
    def sentinel_evidence(
        self,
        *,
        state: OutcomeState,
        package_id: int,
        observed_at: datetime,
        detail: str,
    ) -> AppendOnlyModel:
        """Return one unsaved evidence row carrying a sentinel state.

        The base decides *which* sentinel and that there is always one; the
        collector decides what a row in its own table looks like. See the class
        docstring for why the split is where it is, and why the base checks the
        result rather than trusting it.

        Args:
            state: `OutcomeState.ERROR` or `OutcomeState.NOT_FOUND`. Never
                `OutcomeState.OK` -- the base does not call this for a
                successful observation. Keyword only, as every other argument in
                this module is: eight subclasses implement this by hand, and a
                positional first argument is the one place their signatures
                could quietly disagree.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with. The base refuses a
                row stamped with anything else.
            detail: What happened, in words worth storing beside the state.

        Returns:
            One unsaved row carrying `state`'s value verbatim (`CPM-AD-24`) in
            one of its fields.

        """

    def collect(self, *, package_id: int, force: bool = False) -> CollectionResult:
        """Collect one package, applying every rule this base owns.

        The recorder is opened first and nothing wraps it -- see the module
        docstring for why that ordering is the whole of `CPM-EVIDENCE-S03`'s
        deferred constraint. Inside it: the window, the rate limit, the call,
        and one `transaction.atomic()` around the evidence write.

        Args:
            package_id: The package to collect, by the integer primary key
                `CPM-AD-3` fixes.
            force: Bypass the observation window. `CPM-UJ-1`'s manually
                triggered recollection "always bypasses the window and always
                writes", so this is a parameter rather than a separate entry
                point -- one path, one set of rules, one difference.

        Returns:
            What the run did, mirroring the ledger row it wrote.

        Raises:
            CollectorConfigurationError: When a row this collector produced does
                not carry the instant it was handed, or when a sentinel row does
                not carry the state it was asked for. Both are defects in the
                subclass; both are caught before the row reaches the table.
            CollectionWriteError: When the evidence write itself failed on a
                path that was already recording a failure. It carries the
                original reason, so the ledger never records only the epitaph.
            Exception: Whatever `translate` raised, re-raised unchanged *after*
                an evidence row carrying `error` has been written and with the
                ledger row finalized to `failed` by the recorder. Caught this
                widely and deliberately: a malformed payload can break a parser
                in any way at all, and the guarantee being defended -- never no
                row -- does not depend on which way.

        """
        with collection_run(collector=self._name, clock=self._clock, package_id=package_id) as run:
            observed_at = self._clock.now()
            # Asked for once, before the window is consulted, so that every log
            # line and every message below names the same locator -- and so that
            # a `source_for` which cannot answer fails the run rather than
            # failing only on the paths that happen to reach the transport.
            source = self.source_for(package_id=package_id)

            if not force and self._inside_window(package_id=package_id, now=observed_at):
                detail = (
                    f"{self._name} observed package {package_id} within the last {self._window}; "
                    f"the observation window suppressed this run (CPM-AD-7)."
                )
                logger.info(
                    COLLECTION_SKIPPED_EVENT,
                    collector=self._name,
                    package_id=package_id,
                    source=source,
                    detail=detail,
                )
                run.skipped(detail=detail)
                return CollectionResult(state=RunState.SKIPPED, evidence_rows=0, detail=detail)

            if not self._limiter.acquire(
                collector=self._name,
                limit=self._rate_limit,
                now=observed_at,
                cost=self.request_cost,
            ):
                detail = (
                    f"{self._name} has spent its allowance of {self._rate_limit.calls} requests per "
                    f"{self._rate_limit.per}; the call was refused rather than issued unlimited (CPM-AD-20)."
                )
                logger.warning(
                    COLLECTION_REFUSED_EVENT,
                    collector=self._name,
                    package_id=package_id,
                    source=source,
                    detail=detail,
                    cost=self.request_cost,
                )
                return self._failed(run_detail=detail, package_id=package_id, observed_at=observed_at, run=run)

            try:
                payload = self._transport.fetch(source)
            except TransportError as failure:
                detail = f"{type(failure).__name__}: {failure}"
                logger.warning(
                    COLLECTION_FAILED_EVENT,
                    collector=self._name,
                    package_id=package_id,
                    source=source,
                    detail=detail,
                )
                return self._failed(run_detail=detail, package_id=package_id, observed_at=observed_at, run=run)

            if not payload.found:
                detail = f"{source} reports that the resource does not exist"
                rows = self._write_evidence(
                    [
                        self._sentinel(
                            OutcomeState.NOT_FOUND,
                            package_id=package_id,
                            observed_at=observed_at,
                            detail=detail,
                        ),
                    ],
                    observed_at=observed_at,
                )
                # `succeeded`, not `failed`: the source answered, and the answer
                # was "no such thing". `CPM-AD-5` keeps the two distinguishable
                # precisely so a reader is never asked to infer which happened.
                # The detail is declared so the ledger row says what the returned
                # result says, on this path as on every other.
                run.succeeded(detail=detail)
                return CollectionResult(state=RunState.SUCCEEDED, evidence_rows=rows, detail=detail)

            # Caught this widely and re-raised unchanged. Nothing is swallowed --
            # the `raise` below is unconditional and re-raises the same object,
            # which inherited `CG-3` requires -- and the row is written first so
            # that the "never no row" guarantee survives a parser breaking in a
            # way nobody anticipated. The recorder finalizes the ledger row to
            # `failed` with the exception's type and message on the way out, so
            # there is no `run.failed()` here to contradict it.
            try:
                evidence = self.translate(payload, package_id=package_id, observed_at=observed_at)
            except Exception as broken:
                detail = f"{type(broken).__name__}: {broken}"
                logger.warning(
                    COLLECTION_FAILED_EVENT,
                    collector=self._name,
                    package_id=package_id,
                    source=source,
                    detail=detail,
                )
                self._write_evidence(
                    [
                        self._sentinel(
                            OutcomeState.ERROR,
                            package_id=package_id,
                            observed_at=observed_at,
                            detail=detail,
                        ),
                    ],
                    observed_at=observed_at,
                )
                raise

            if not evidence:
                detail = (
                    f"{self._name} translated {source} into no evidence rows. A parser that finds nothing in a "
                    f"body the source served no longer matches its source, and recording that as a clean "
                    f"success is the ambiguity the outcome vocabulary exists to remove (CPM-NFR-3)."
                )
                logger.warning(
                    COLLECTION_FAILED_EVENT,
                    collector=self._name,
                    package_id=package_id,
                    source=source,
                    detail=detail,
                )
                return self._failed(run_detail=detail, package_id=package_id, observed_at=observed_at, run=run)

            written = self._write_evidence(evidence, observed_at=observed_at)
            return CollectionResult(state=RunState.SUCCEEDED, evidence_rows=written, detail="")

    def _inside_window(self, *, package_id: int, now: datetime) -> bool:
        """Report whether the observation window suppresses this run.

        A zero window short-circuits rather than querying, and the difference is
        not cosmetic: `finished_at__gte=since` is inclusive, so with
        `NO_WINDOW` a run that finished at exactly this instant would suppress.
        That is unreachable under `SystemClock` and exactly reproducible under
        the `FixedClock` every case injects -- which is the worst combination,
        because it makes the bug a property of the tests rather than of the
        product. `NO_WINDOW` means "observe on every run", so it is answered
        without asking.

        Args:
            package_id: The package being collected.
            now: The instant the window is measured back from.

        Returns:
            True when a suppressing run finished inside the window.

        """
        if self._window <= NO_WINDOW:
            return False
        return has_recent_success(collector=self._name, package_id=package_id, since=now - self._window)

    def _failed(
        self,
        *,
        run_detail: str,
        package_id: int,
        observed_at: datetime,
        run: RunHandle,
    ) -> CollectionResult:
        """Declare the run failed, write the `error` row, and report both.

        The declaration comes first so the ledger's reason is set before
        anything else can go wrong, and the write is wrapped so that a database
        failure carries the reason with it rather than replacing it.

        Args:
            run_detail: Why the run failed.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with.
            run: The recorder's handle, so the ledger row's reason is declared
                before anything else can go wrong.

        Returns:
            The failed result, carrying the row count and the same detail the
            ledger row now holds.

        Raises:
            CollectionWriteError: When the sentinel row could not be written.

        """
        run.failed(detail=run_detail)
        rows = self._write_sentinel(
            OutcomeState.ERROR,
            package_id=package_id,
            observed_at=observed_at,
            detail=run_detail,
        )
        return CollectionResult(state=RunState.FAILED, evidence_rows=rows, detail=run_detail)

    def _write_sentinel(
        self,
        state: OutcomeState,
        *,
        package_id: int,
        observed_at: datetime,
        detail: str,
    ) -> int:
        """Write one sentinel row, preserving the reason if the write itself fails.

        Args:
            state: The sentinel the base decided on.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with.
            detail: The reason the run is already failing.

        Returns:
            How many rows were inserted.

        Raises:
            CollectionWriteError: When the write raised. The message carries the
                original reason first, so the ledger row -- which the recorder
                fills from the exception on its way out -- never records only
                that the epitaph could not be written.

        """
        try:
            return self._write_evidence(
                [self._sentinel(state, package_id=package_id, observed_at=observed_at, detail=detail)],
                observed_at=observed_at,
            )
        except DatabaseError as write_failure:
            message = (
                f"{detail} -- and the {state.value} evidence row recording it could not be written: "
                f"{type(write_failure).__name__}: {write_failure}"
            )
            raise CollectionWriteError(message, detail=detail) from write_failure

    def _sentinel(
        self,
        state: OutcomeState,
        *,
        package_id: int,
        observed_at: datetime,
        detail: str,
    ) -> AppendOnlyModel:
        """Ask the collector for a sentinel row, and check it carries the state.

        Args:
            state: The sentinel the base decided on.
            package_id: The package the observation is about.
            observed_at: The instant to stamp the row with.
            detail: What happened.

        Returns:
            The row the collector built.

        Raises:
            CollectorConfigurationError: When no field on the row carries the
                state's value. A subclass that ignored the argument and wrote a
                determinate verdict would type-check perfectly and would defeat
                "never a clean result" outright, so the base checks rather than
                trusts. `CPM-AD-24` requires the value to be emitted verbatim,
                which is exactly what makes the check possible.

        """
        row = self.sentinel_evidence(
            state=state,
            package_id=package_id,
            observed_at=observed_at,
            detail=detail,
        )
        carried = {
            getattr(row, field.attname, None)
            for field in row._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        }
        if state.value not in carried:
            message = (
                f"{type(self).__name__}.sentinel_evidence was asked for {state.value!r} and returned a row "
                f"carrying no field with that value. A sentinel that does not say which sentinel it is cannot "
                f"be told from a clean result (CPM-AD-5, CPM-AD-24)."
            )
            raise CollectorConfigurationError(message)
        return row

    def _write_evidence(self, evidence: Sequence[AppendOnlyModel], *, observed_at: datetime) -> int:
        """Insert one package's evidence rows, inside one transaction and no more.

        `transaction.atomic()` is *here* -- around the write of one package's
        rows -- and nowhere else in this class. It is nested inside the recorder
        (`CPM-AD-23`), so a later package's failure never rolls back an earlier
        package's evidence and the run ledger row is never inside a block that
        could take it away. `tests/unit/django_apps/test_collector_base_audit.py`
        asserts both halves: that no transaction encloses the recorder, and that
        this write is inside one.

        `bulk_create` and never `update_or_create`: evidence is append-only, and
        re-observation inserts (`CPM-AD-2`). `bulk_create` does not call
        `save()`, so the instant is checked here -- see `_require_stamped`.

        Args:
            evidence: The unsaved rows to insert.
            observed_at: The instant every one of them must carry.

        Returns:
            How many rows were inserted.

        Raises:
            CollectorConfigurationError: When a row carries a different instant.

        """
        rows = list(evidence)
        self._require_stamped(rows, observed_at=observed_at)
        with transaction.atomic():
            created = self._evidence_model.objects.bulk_create(rows)
        return len(created)

    def _require_stamped(self, rows: Sequence[AppendOnlyModel], *, observed_at: datetime) -> None:
        """Refuse a row that does not carry the instant this run was handed.

        `AppendOnlyModel.save()` refuses a missing or naive `observed_at` and
        `core/models.py` calls that "the one place every evidence write passes
        through" -- but `bulk_create` does not call `save()`, so this base would
        walk around it on every write it makes. The check is restored here and
        made stricter: not merely aware, but *this* observation's instant. One
        observation has one moment (`CPM-AD-7`), and a collector stamping rows
        from anywhere else would make every freshness comparison and every
        observation window silently wrong -- in an append-only table that nothing
        may correct.

        Args:
            rows: The rows about to be inserted.
            observed_at: The instant they must carry.

        Raises:
            CollectorConfigurationError: When any row's `observed_at` is absent,
                naive, or a different instant.

        """
        wrong = [
            row.observed_at
            for row in rows
            if row.observed_at is None or not is_aware(row.observed_at) or row.observed_at != observed_at
        ]
        if wrong:
            message = (
                f"{type(self).__name__} produced {len(wrong)} evidence row(s) stamped {wrong!r} rather than "
                f"with the observed_at it was handed ({observed_at!r}). bulk_create does not call save(), so "
                f"this is the only guard between a mis-stamped observation and an append-only table nothing "
                f"can correct (CPM-AD-7, CPM-AD-26)."
            )
            raise CollectorConfigurationError(message)


def _require_name(name: str, *, label: str) -> str:
    """Refuse a collector that does not say what it is called.

    Args:
        name: The declared name.
        label: The class's own name, for the message.

    Returns:
        The name, unchanged.

    Raises:
        CollectorConfigurationError: When it is not a non-blank string.

    """
    if not isinstance(name, str) or not name.strip():
        message = (
            f"{label} declares name={name!r}. A run is traceable to the code that performed it (CPM-FR-39), "
            f"and a blank or absent name is a ledger row nothing can be traced to."
        )
        raise CollectorConfigurationError(message)
    return name


def _require_evidence_model(model: type[AppendOnlyModel] | None, *, label: str) -> type[AppendOnlyModel]:
    """Refuse a collector with nowhere append-only to write.

    Args:
        model: The declared evidence model.
        label: The class's own name, for the message.

    Returns:
        The model, unchanged.

    Raises:
        CollectorConfigurationError: When it is absent, or is not a subclass of
            `AppendOnlyModel`. A plain `Model` satisfies every annotation in
            this module and goes around every refusal `CPM-AD-2` makes -- the
            manager that offers no `update()`, the `save()` that refuses a
            written row, the base manager that cannot be used to bypass either.

    """
    if model is None:
        message = (
            f"{label} declares no evidence_model. A collector writes its own append-only table (CPM-AD-7); "
            f"a collector with nowhere to write cannot record that it failed either."
        )
        raise CollectorConfigurationError(message)
    if not (isinstance(model, type) and issubclass(model, AppendOnlyModel)):
        message = (
            f"{label} declares evidence_model={model!r}, which does not inherit AppendOnlyModel. Evidence is "
            f"append-only (CPM-AD-2); a plain Model would satisfy every annotation here and would carry none "
            f"of the refusals."
        )
        raise CollectorConfigurationError(message)
    return model


def _require_window(window: timedelta | None, *, label: str) -> timedelta:
    """Refuse an observation window that is absent, mistyped or negative.

    Args:
        window: The declared window.
        label: The class's own name, for the message.

    Returns:
        The window, unchanged.

    Raises:
        CollectorConfigurationError: When it is not a non-negative `timedelta`.

    """
    if not isinstance(window, timedelta) or window < NO_WINDOW:
        message = (
            f"{label} declares observation_window={window!r}, which is not an interval a window can be "
            f"measured over. Declare timedelta(0) to observe on every run; omitting the value, or declaring "
            f"a number of unstated units, is not the same statement."
        )
        raise CollectorConfigurationError(message)
    return window


def _require_timeout(timeout: float | None, *, label: str) -> float:
    """Refuse a timeout that is absent, mistyped or unusable.

    Args:
        timeout: The declared timeout in seconds.
        label: The class's own name, for the message.

    Returns:
        The timeout, unchanged.

    Raises:
        CollectorConfigurationError: When it is not a positive finite number.
            `bool` is excluded explicitly: it is a subclass of `int`, so
            `timeout = True` would otherwise be a one-second timeout that
            somebody meant as a flag.

    """
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not isfinite(timeout) or timeout <= 0:
        message = (
            f"{label} declares timeout={timeout!r}. Every outbound call carries a positive finite timeout "
            f"(CPM-NFR-3) and there is no default-less path; this is refused at construction rather than at "
            f"the call, where a ledger row would already be running."
        )
        raise CollectorConfigurationError(message)
    return float(timeout)


def _require_retries(retries: int, *, label: str) -> int:
    """Refuse a retry count that is mistyped or negative.

    Args:
        retries: The declared retry count.
        label: The class's own name, for the message.

    Returns:
        The count, unchanged.

    Raises:
        CollectorConfigurationError: When it is not a non-negative integer.

    """
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        message = (
            f"{label} declares retries={retries!r}, which is not a number of attempts. Declare 0 for a call "
            f"that is tried once; the value is also what the rate limiter is charged per collection."
        )
        raise CollectorConfigurationError(message)
    return retries


def _require_rate_limit(limit: RateLimit | None, *, label: str) -> RateLimit:
    """Refuse a collector that declares no allowance.

    Args:
        limit: The declared allowance.
        label: The class's own name, for the message.

    Returns:
        The allowance, unchanged.

    Raises:
        CollectorConfigurationError: When it is absent or is not a `RateLimit`.

    """
    if not isinstance(limit, RateLimit):
        message = (
            f"{label} declares rate_limit={limit!r}. Rate limiting lives in this base rather than per "
            f"collector (CPM-AD-20), and a call issued unlimited is the one thing that arrangement exists to "
            f"prevent."
        )
        raise CollectorConfigurationError(message)
    return limit
