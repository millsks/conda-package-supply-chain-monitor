"""The two probe endpoints, and the asymmetry between them (AD-22, FR-42).

Liveness and readiness are deliberately *not* the same check with two names.

**Liveness checks nothing external.** It opens no database connection, reads no
cache, resolves no `request.user`, makes no network call and reads no setting
that performs I/O. The process either answers it or it does not, and "does not"
is the only signal a liveness probe is entitled to act on -- because the action
it takes is to kill the process. A liveness probe that touched the database would
turn a thirty-second database outage into every replica in the estate being
restarted at once, which is AD-22's stated failure and the reason NFR-2 makes
"liveness touches nothing external" a system-wide invariant rather than a
property of this one function. Anything added to this path later inherits that
invariant; `tests/unit/test_health_views.py` holds it mechanically with
`django_assert_num_queries(0)`, at the view and through the whole middleware
stack.

**Readiness checks that every required database answers.** Failing it removes the
pod from the load balancer's pool and leaves the process alive, which is the
correct response to a dependency being briefly unavailable: the component
degrades instead of crash-looping. Requiredness is read from `component.toml`
(AD-9) and never inferred -- a database is required unless the declaration says
`required = false`.

**Readiness never re-checks migrations, and that is a decision rather than an
omission.** During a rolling deploy an older replica legitimately runs against a
newer schema: the release stage migrates first, then new pods start, so for the
length of the rollout every still-serving old replica sees migrations it does not
have. A readiness check that compared the migration graph against
`django_migrations` would report every one of those replicas unready, drain the
whole old generation at once, and turn a routine backwards-compatible migration
into an outage. So nothing here imports `MigrationExecutor`, shells out to
`migrate --check` or `showmigrations`, or reads `django_migrations` by any other
route, and `tests/unit/test_health_views.py` asserts that of this module's own
source rather than trusting the sentence.

**Why the order of evaluation is fixed.** Drain first, then the databases, then
the flag. A draining process is one that has been told to stop serving, so its
answer does not depend on whether its databases are healthy and it must not spend
a round trip finding out; Story 5.4's `SIGTERM` handler is built on that
ordering, which is why the drain branch is here and not deferred to it.

**Why these are plain function-based views and not DRF.**
`REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]` is `IsAuthenticated`
(`config/settings/base.py`) and a platform probe carries no credential, so a DRF
view would answer 403 to a healthy process. Being non-DRF also keeps them out of
drf-spectacular's schema, which is where they belong: they are an operational
contract with the platform, not part of the component's API.

**Why they are Django URL routes and nothing else (AD-16).** An ASGI-level probe
handler would put a network surface *beneath* the URL resolver, where the FR-17
authentication allowlist cannot see it. A route is visible to every mechanism
that inspects this component's surface, which is the property that matters more
than the microseconds a bypass would save.

**Why both views are exempt from `ATOMIC_REQUESTS`.** `config/settings/base.py`
sets `DATABASES["default"]["ATOMIC_REQUESTS"] = True`, which makes Django wrap
*every* view in a transaction on the way in. Measured rather than assumed, that
put two statements (`SAVEPOINT`/`RELEASE SAVEPOINT` under the test harness, a
real `BEGIN`/`COMMIT` in production) on the liveness path -- a database round trip
on the one path NFR-2 says must have none, and the exact shape of AD-22's failure:
with the database down, opening the transaction raises before `liveness` runs at
all, the probe reads a 500, and the platform restarts a perfectly healthy process.
It is just as wrong for readiness, which promises `503` and would answer `500`
from a handler the view never reached.

`transaction.non_atomic_requests` is Django's own per-view exemption and is
therefore what is used, in preference to touching `ATOMIC_REQUESTS` itself: the
setting is right for the rest of the component, and a probe is the one kind of
request that has nothing to make atomic. `tests/unit/test_health_views.py`
asserts the exemption covers every alias that declares the setting, so a
contributed database (Epic 9) that turned it on and was not exempted fails the
gate rather than quietly re-arming this.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Final

import structlog
from django.db import connections
from django.db import transaction
from django.db.utils import DatabaseError
from django.db.utils import OperationalError
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from config.component.loader import load_component_declaration
from config.health.state import first_contact_made
from config.health.state import is_draining
from config.health.state import mark_first_contact

if TYPE_CHECKING:
    from django.http import HttpRequest

__all__ = ["liveness", "readiness"]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: Liveness's whole body. Plain text rather than JSON because there is nothing to
#: report: the status code *is* the answer, and a body a probe has to parse to
#: learn something the code already said is a second place for the two to
#: disagree. It is present at all so that a human who curls the endpoint sees
#: that they reached this component rather than an empty 200 from a proxy.
LIVENESS_BODY: Final[str] = "alive\n"

#: The one statement readiness issues per alias. The cheapest round trip that
#: proves the connection is open and the server is answering, and deliberately
#: not a query against a table -- a table's presence is a schema question, and
#: readiness does not ask schema questions (see the module docstring).
PROBE_QUERY: Final[str] = "SELECT 1"

#: The two per-alias values the readiness body reports, and the two statuses the
#: body's `status` key takes. Named rather than spelled at each use so the view
#: and the tests cannot drift apart on a literal.
ALIAS_OK: Final[str] = "ok"
ALIAS_ERROR: Final[str] = "error"
STATUS_READY: Final[str] = "ready"
STATUS_UNREADY: Final[str] = "unready"

#: The status code an unready process answers with. `SERVICE_UNAVAILABLE` and not
#: `INTERNAL_SERVER_ERROR`: a 500 says the process is broken, which invites an
#: operator to go looking for a stack trace that does not exist. And not
#: `OK`-with-a-body-saying-unready either, which is unreadable by a platform
#: probe -- a probe reads the status code and nothing else.
UNREADY_STATUS: Final[HTTPStatus] = HTTPStatus.SERVICE_UNAVAILABLE
READY_STATUS: Final[HTTPStatus] = HTTPStatus.OK


@transaction.non_atomic_requests
@never_cache
@require_safe
def liveness(request: HttpRequest) -> HttpResponse:
    """Answer that this process is running, having checked nothing else.

    There is no `try`/`except` here and there must not be one. Liveness has
    exactly two outcomes -- the process answers 200, or the process does not
    answer -- and a handler that converted an error into a 500 would invent a
    third that the probe would read as "alive but sad" and act on incorrectly.
    There is also nothing to catch: the body is a constant.

    `@require_safe` rather than `@require_GET`, which despite its convenience is
    `require_http_methods(["GET"])` and answers 405 to a `HEAD` -- verified
    against the installed Django in `django/views/decorators/http.py`. Probes
    send both verbs, so both are permitted and everything else is refused.

    Args:
        request: The incoming request. Unused, and pointedly so: reading
            `request.user` would resolve the lazy object and can load a session,
            which is a database query on the liveness path.

    Returns:
        `200` with a short plain-text body, carrying no-cache headers so that
        nothing between the probe and this process answers on its behalf.

    """
    return HttpResponse(LIVENESS_BODY, content_type="text/plain; charset=utf-8", status=READY_STATUS)


@transaction.non_atomic_requests
@never_cache
@require_safe
def readiness(request: HttpRequest) -> JsonResponse:
    """Answer whether this process should be routed to right now.

    Evaluated in this order, and the order is load-bearing:

    1. A draining process refuses immediately. It has been told to stop serving,
       so the state of its databases cannot change the answer, and Story 5.4's
       shutdown handler depends on the refusal arriving without a round trip.
    2. Every required alias is asked `SELECT 1` through its own connection.
    3. A probe in which every alias answered records first contact, and only then
       does the process report itself ready.

    Args:
        request: The incoming request. Unused; readiness takes no parameters,
            because a probe that could be asked to check less would eventually be
            asked to.

    Returns:
        `200` with `{"status": "ready", "databases": {...}}` when this process is
        draining-free, has reached every required database on this probe, and has
        recorded first contact; otherwise `503` with `{"status": "unready", ...}`.
        The `databases` mapping reports `ok` or `error` per alias and is empty in
        the draining case, where no alias was asked.

    """
    if is_draining():
        # Before the databases, deliberately. See the module docstring.
        logger.warning("health.readiness_refused_draining")
        return _answer(STATUS_UNREADY, {}, UNREADY_STATUS)

    statuses = _probe_required_databases()
    unreachable = sorted(alias for alias, status in statuses.items() if status != ALIAS_OK)
    if not unreachable:
        mark_first_contact()

    if unreachable or not first_contact_made():
        # Two independent reasons to refuse, and the second is not redundant: it
        # is what AC #3 asserts. A process that has never reached its databases
        # is not ready, and the flag -- not this probe's result -- is what says
        # so. Ordinarily the call above has just set it, which is exactly the
        # point: the only way to a 200 is through a probe that actually
        # succeeded in *this* process.
        return _answer(STATUS_UNREADY, statuses, UNREADY_STATUS)
    return _answer(STATUS_READY, statuses, READY_STATUS)


def _answer(status: str, databases: dict[str, str], code: HTTPStatus) -> JsonResponse:
    """Build one readiness response.

    Args:
        status: `ready` or `unready`.
        databases: The per-alias result, `ok` or `error`.
        code: The HTTP status code.

    Returns:
        The JSON response, shaped the same way whichever answer it carries -- a
        body whose keys depend on the outcome is a body every reader has to
        branch on.

    """
    return JsonResponse({"status": status, "databases": databases}, status=code)


def _probe_required_databases() -> dict[str, str]:
    """Ask every required alias for one row, and report what each one said.

    Returns:
        The per-alias result in declaration order, `ok` or `error`. Empty when no
        configured alias is required, which is a valid component rather than a
        misconfiguration -- and one that is ready as soon as it is draining-free.

    """
    statuses: dict[str, str] = {}
    for alias in _required_aliases():
        connection = connections[alias]
        try:
            with connection.cursor() as cursor:
                cursor.execute(PROBE_QUERY)
        except (OperationalError, DatabaseError) as error:
            # Named specifically rather than caught broadly: a `TypeError` from a
            # mis-wired connection is a defect in this component and must reach
            # the error handler, not be reported to a probe as a database outage.
            # Both are named even though `OperationalError` derives from
            # `DatabaseError`, because the pair is the contract this view states
            # it handles and a reader should not have to know the hierarchy to
            # see it.
            logger.warning("health.readiness_database_unreachable", alias=alias, failure=type(error).__name__)
            statuses[alias] = ALIAS_ERROR
        else:
            statuses[alias] = ALIAS_OK
    return statuses


def _required_aliases() -> tuple[str, ...]:
    """Return the configured aliases readiness must be able to reach (AD-9).

    Resolved by iterating the aliases Django actually has connections for and
    asking `component.toml` about each one -- never by matching an engine name, a
    URL or an alias spelling (AD-26). That is also what makes Epic 9's
    contributed database work without editing this view: a new alias appears in
    `DATABASES`, is declared in `component.toml`, and is probed.

    An alias that `DATABASES` configures and `component.toml` does not declare is
    treated as **required** and logged by name. Silently skipping it would make a
    forgotten declaration look like a passing readiness check, which is the one
    outcome an omission must not produce; AD-9's rule already fails closed for a
    declared alias with no `required` key, and this is the same reading one level
    out.

    Returns:
        The required aliases, in the order `DATABASES` declares them.

    """
    declared = {database.alias: database.required for database in load_component_declaration().databases}
    required: list[str] = []
    for alias in connections:
        if alias not in declared:
            logger.warning("health.readiness_alias_undeclared", alias=alias)
            required.append(alias)
        elif declared[alias]:
            required.append(alias)
    return tuple(required)
