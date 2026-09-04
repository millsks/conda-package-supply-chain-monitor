"""The three workload queues, and the task-name namespace that reaches them.

`CPM-AD-20`: collection is external I/O and rate-limited, policy is CPU work
with no outbound calls, and verification is a compute-backed Python 3.14 build.
They are three queues because they are three workload classes, and the failure
the split exists to prevent is `R-11` -- a five-minute `verify` build sharing a
queue with the daily security sweep and starving it.

**The three names are declared once, here.** Every other reader -- the settings
module that installs the route table, the audit that sweeps the registry, the
`-Q` list the worker consumes -- resolves them from `Queue` rather than spelling
`"collect"` again. A second literal spelling is exactly what this repository's
audits exist to catch: two spellings of one name look like one decision right up
until they disagree.

**A task's workload class lives in its declared name, never in its module.**
`CPM-EP-PY314`'s verification collectors and `CPM-EP-CURRENCY`'s currency
collectors both land in `django_apps/.../collectors`, so a route keyed on module
path cannot tell a compute-backed build from an HTTP fetch, and getting that
wrong *is* `R-11`. A declared name carries the class with the task wherever the
module moves:

```python
@shared_task(name="cpm.verify.py314_build")
def verify_py314_build(package_id: int) -> None: ...
```

**The route table is derived from the mapping, not written out beside it.**
`CELERY_TASK_ROUTES` below is built from `QUEUE_BY_NAMESPACE`, so a namespace and
its queue cannot drift apart: there is one place a queue is named and one place a
namespace is bound to it. `config/settings/base.py` assigns the table to
`CELERY_TASK_ROUTES`, which `config/celery_app.py`'s
`config_from_object("django.conf:settings", namespace="CELERY")` reads as a live
view -- so the settings assignment *is* `app.conf.task_routes` with no further
wiring.

**No catch-all pattern, and no change to the default queue.** A task that
declares no `cpm.` name keeps landing on the inherited default queue, which is
what the platform's own `django_service.users.tasks.get_users_count` and the
correlation probe in `tests/integration/test_celery_log_correlation.py` both
depend on. A `"*"` route would capture them and there would be nowhere left for
"this task declared no workload class" to show up.

**Cadence is not here, and is not a decorator either.** `CPM-AD-20` puts every
schedule in `django_celery_beat`'s `DatabaseScheduler`, which
`config/settings/base.py` already configures. A cadence written into a decorator
cannot be changed without a deploy, which is what `CPM-NFR-2` forbids;
`tests/unit/django_apps/test_task_declaration_audit.py` is the gate on that.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix. `AD-8` is the platform's adoption rule and `CPM-AD-20`
is this product's queue rule -- two registers, not a typo.

Imports nothing from Django. This module is read by `config/settings/base.py`
during settings import, long before the app registry exists, so a Django import
here would make the settings module unloadable -- the same constraint
`core/roles.py` records and for the same reason.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING
from typing import Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CELERY_TASK_ROUTES",
    "CONTRIBUTED_SETTING_KEY",
    "QUEUE_BY_NAMESPACE",
    "TASK_NAMESPACE_PREFIX",
    "Queue",
    "queue_for",
    "route_pattern",
]

#: The settings key `config/settings/base.py` assigns `CELERY_TASK_ROUTES` to.
#:
#: Declared here because it is this module's contract rather than settings' --
#: the table is built to be contributed under exactly this name, and the name has
#: to be one of `config/startup/allowlist.py`'s `CONTRIBUTABLE_KEYS` for the
#: contribution to be an adoption rather than an override (inherited `AD-8`).
#: Two test modules assert that membership, and one string they could spell
#: differently is the failure this whole module exists to prevent, applied to
#: itself.
CONTRIBUTED_SETTING_KEY: Final[str] = "CELERY_TASK_ROUTES"


class Queue(StrEnum):
    """The three workload classes this product routes by, and their queue names.

    A `StrEnum` rather than a `TextChoices`: this module is imported at
    settings-import time and `django.db.models` is not importable there. The
    members' *values* are the queue names Celery publishes to and the worker
    consumes, so they are the strings every other surface has to agree with --
    `-Q` in `pixi.toml`, the route table below, and any `component.toml` process
    split a later story adds.
    """

    COLLECT = "collect"
    POLICY = "policy"
    VERIFY = "verify"


#: The namespace every task this product registers declares its name under.
#:
#: `cpm.` and not the module path, for the reason the module docstring gives: two
#: collectors with different workload classes live in one package, so the module
#: cannot answer the question the route is asking.
TASK_NAMESPACE_PREFIX: Final[str] = "cpm"

#: The separator between a task name's segments. Celery's own convention, and the
#: character its route globs match against; named so the split below and the
#: pattern built above it cannot disagree about it.
NAME_SEPARATOR: Final[str] = "."

#: The glob Celery matches a task name against, appended to `cpm.<namespace>`.
#:
#: Celery compiles this with `fnmatch.translate`, so `*` spans the rest of the
#: name **including nothing at all**: `cpm.collect.` and `cpm.collect..x` both
#: match, and both are routed to `collect` by a real publish. `queue_for` below
#: reproduces that exactly rather than the tidier rule a reader might expect --
#: see its docstring for why the difference is not a detail.
ROUTE_PATTERN_SUFFIX: Final[str] = ".*"

#: Namespace segment to the queue it routes to.
#:
#: Derived from `Queue` rather than written out, so the three names are declared
#: once. The namespace and the queue are spelled the same today and that is a
#: convenience rather than a rule: this mapping is the seam that lets them differ
#: -- a fourth namespace routed onto an existing queue would be one entry here
#: and no change anywhere else.
QUEUE_BY_NAMESPACE: Final[Mapping[str, Queue]] = MappingProxyType({queue.value: queue for queue in Queue})


def route_pattern(namespace: str) -> str:
    """Return the Celery route glob that captures one namespace.

    Args:
        namespace: The namespace segment, as it appears in `QUEUE_BY_NAMESPACE`.

    Returns:
        The pattern Celery matches task names against -- `cpm.collect.*` for
        `collect`.

    """
    return f"{TASK_NAMESPACE_PREFIX}{NAME_SEPARATOR}{namespace}{ROUTE_PATTERN_SUFFIX}"


#: The contribution `config/settings/base.py` installs as `CELERY_TASK_ROUTES`.
#:
#: One entry per namespace, built from `QUEUE_BY_NAMESPACE`, and no catch-all.
#: `CELERY_TASK_ROUTES` is one of the keys `config/startup/allowlist.py`'s
#: `CONTRIBUTABLE_KEYS` permits a domain application to contribute to, which is
#: what makes writing it from `core` an adoption rather than an override.
CELERY_TASK_ROUTES: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        route_pattern(namespace): MappingProxyType({"queue": queue.value})
        for namespace, queue in QUEUE_BY_NAMESPACE.items()
    }
)


def queue_for(task_name: str) -> Queue | None:
    """Return the queue a task's declared name routes to.

    The resolver the routing audit reads, and it answers the question celery's
    own router answers: given this name, which queue does a publish reach? It is
    written to reproduce `CELERY_TASK_ROUTES` above rather than to describe it,
    because the two disagreeing is not a cosmetic difference -- the audit would
    demand an exemption for a task celery is routing perfectly well, or worse,
    pass a task celery sends somewhere nobody drains.

    So the rule is exactly the glob's: the `cpm.` prefix, a known namespace, and
    the separator after it. What follows the separator is not inspected, and that
    includes the empty string -- `fnmatch` matches `*` against nothing, so
    `cpm.collect.` really is routed to `collect` by a real publish, however
    little anybody wants to name a task that.
    `tests/unit/django_apps/test_task_routing_audit.py` reconciles the two over
    the malformed names as well as the well-formed ones.

    Args:
        task_name: The task's registered name -- what `@shared_task(name=...)`
            declared, or the `module.function` default Celery derives when
            nothing did.

    Returns:
        The queue the name resolves to, or `None` for a name that declares no
        workload class: a bare `module.function`, an unknown namespace such as
        `cpm.sweep.thing`, or `cpm.collect` with no separator after the
        namespace. The `None` is not an error here -- `get_users_count` is
        legitimately none of collection, policy or verification -- so the
        decision about what an unrouted task means belongs to the audit that
        asks.

    """
    prefix, _, remainder = task_name.partition(NAME_SEPARATOR)
    if prefix != TASK_NAMESPACE_PREFIX:
        return None
    namespace, separator, _rest = remainder.partition(NAME_SEPARATOR)
    if not separator:
        return None
    return QUEUE_BY_NAMESPACE.get(namespace)
