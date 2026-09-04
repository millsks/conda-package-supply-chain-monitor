"""The queue vocabulary `core` owns, and the route table derived from it.

`CPM-AD-20` names three workload classes -- `collect` for rate-limited external
I/O, `policy` for CPU work with no outbound calls, `verify` for compute-backed
Python 3.14 builds -- and the whole value of the split is `R-11`: a five-minute
verification build must not share a queue with the daily security sweep.

Two properties are worth a gate here, and neither is about celery.

**The names are declared once.** Three strings that mean "the collection queue"
-- one in the enum, one in the route table, one in the worker's `-Q` -- look like
one decision until two of them disagree, and the disagreement is silent: work is
published to a queue nobody consumes and simply never runs. So the route table is
*derived* from the mapping below rather than written beside it, and this module
asserts the derivation rather than the resulting literals.

**The workload class is in the task's name.** `CPM-EP-PY314`'s verification
collectors and `CPM-EP-CURRENCY`'s currency collectors both land in one package,
so a route keyed on module path routes a `verify` build to `collect` -- which is
`R-11` happening, not a near miss. `queue_for` is therefore a function of the
declared name and of nothing else, and the cases below exercise it over each
namespace, an unknown one, and a bare `module.function` name.

Reads two modules and calls a pure function: no database, no network, no
filesystem.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from conda_package_supply_chain_monitor.core import queues
from conda_package_supply_chain_monitor.core.queues import CELERY_TASK_ROUTES
from conda_package_supply_chain_monitor.core.queues import CONTRIBUTED_SETTING_KEY
from conda_package_supply_chain_monitor.core.queues import QUEUE_BY_NAMESPACE
from conda_package_supply_chain_monitor.core.queues import TASK_NAMESPACE_PREFIX
from conda_package_supply_chain_monitor.core.queues import Queue
from conda_package_supply_chain_monitor.core.queues import queue_for
from conda_package_supply_chain_monitor.core.queues import route_pattern
from config.startup.allowlist import CONTRIBUTABLE_KEYS

#: The three names `CPM-AD-20` fixes, written out here and nowhere else in the
#: suite. This is the one place a literal spelling is the point: an enum compared
#: against itself would pass just as happily after somebody renamed a member and
#: the queue with it, while the worker's `-Q`, the deployment's queue declarations
#: and any message already in flight kept the old name.
THE_THREE_QUEUE_NAMES = frozenset({"collect", "policy", "verify"})

#: The catch-all a route table must not carry. `tests/integration/test_celery_log_correlation.py`
#: turns eager execution off and really publishes a probe task that declares no
#: `cpm.` name; a `"*"` pattern would capture it, and with it every inherited
#: platform task, so "this task declared no workload class" would have nowhere
#: left to show up.
CATCH_ALL_PATTERN = "*"

#: One task name per namespace, spelled as a task this product plausibly
#: registers. Declared once and used by every case below that needs one, because
#: a name written inline in two parametrize lists is two names the moment one of
#: them is edited.
A_COLLECTOR_TASK = "cpm.collect.pypi_release"
A_POLICY_TASK = "cpm.policy.currency"
A_VERIFICATION_TASK = "cpm.verify.py314_build"

#: The packages `queues.py` must not import, and the reason it must not.
#:
#: It is imported from `config/settings/base.py` at module scope, so it loads
#: before the app registry is populated and before any model is resolvable;
#: either import would make the settings module unloadable, and the module's own
#: docstring rests on this being true. The identical constraint on
#: `core/roles.py` is gated by `tests/unit/django_apps/test_roles.py`, and this is
#: the same shape -- worth copying rather than trusting, because
#: `from django.apps import apps` *imports* perfectly well at settings time and
#: only fails later, when the registry is consulted. Nothing would go red.
FORBIDDEN_IMPORT_ROOTS = ("django.apps", "django.contrib", "django.db")

#: The module's own source, read off `__file__` rather than rebuilt from the
#: second import root's layout -- that layout is `tests/unit/test_import_roots.py`'s
#: to assert, and a hand-built path here would be a second opinion about it.
QUEUES_MODULE = Path(queues.__file__ or "")


def test_there_are_exactly_three_queues_and_they_are_the_declared_ones() -> None:
    """`CPM-AD-20`'s vocabulary, asserted against the names rather than the enum.

    A fourth queue is not a refactor: it is a workload class somebody decided
    exists, and it needs a worker consuming it before a single task is routed
    there. Failing here is the cheapest place for that decision to surface.

    Compared as sets, with the count asserted separately: declaration order
    carries no meaning here -- nothing reads the members positionally -- and an
    ordered comparison would fail on a reordering with a message that said
    nothing about why.
    """
    assert {queue.value for queue in Queue} == set(THE_THREE_QUEUE_NAMES)
    assert len(list(Queue)) == len(THE_THREE_QUEUE_NAMES)


def test_the_module_imports_nothing_that_needs_django_to_be_ready() -> None:
    """It is imported at settings-import time, before the app registry exists.

    Load-bearing rather than stylistic, and the same case
    `tests/unit/django_apps/test_roles.py` makes for the other module settings
    imports. Asserted on the parsed tree rather than by text search so that prose
    naming either package -- of which this module's docstring has a line -- is not
    itself an offence.
    """
    tree = ast.parse(QUEUES_MODULE.read_text(encoding="utf-8"), filename=str(QUEUES_MODULE))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            imported.add(node.module)

    assert imported, "the scan found no imports at all, so it would pass on any module"
    for name in imported:
        assert not name.startswith(FORBIDDEN_IMPORT_ROOTS), f"queues.py imports {name!r}"


def test_no_two_queues_share_a_name() -> None:
    """`StrEnum` aliases members with equal values, so a duplicate hides itself.

    `Queue.VERIFY = "collect"` would not raise, would not appear as a second
    member, and would route every verification build onto the collection queue --
    `R-11`, spelled as a typo. Counting `__members__` rather than iteration is
    what sees it: iteration yields canonical members only, and the alias is not
    one.
    """
    assert len(Queue.__members__) == len(THE_THREE_QUEUE_NAMES)
    assert len({queue.value for queue in Queue.__members__.values()}) == len(THE_THREE_QUEUE_NAMES)


def test_the_namespace_mapping_covers_every_queue_and_nothing_else() -> None:
    """The mapping is the seam, so it is the thing that must stay total.

    A namespace with no queue routes nowhere; a queue with no namespace is a
    queue the worker drains and nothing ever reaches. Both directions are
    asserted because the mapping is derived today and may not always be -- the
    module docstring says so in as many words.
    """
    assert set(QUEUE_BY_NAMESPACE.values()) == set(Queue)
    assert set(QUEUE_BY_NAMESPACE) == {queue.value for queue in Queue}


@pytest.mark.parametrize(
    ("task_name", "expected"),
    [
        (A_COLLECTOR_TASK, Queue.COLLECT),
        (A_POLICY_TASK, Queue.POLICY),
        (A_VERIFICATION_TASK, Queue.VERIFY),
    ],
    ids=["collect", "policy", "verify"],
)
def test_a_declared_name_resolves_to_its_namespaces_queue(task_name: str, expected: Queue) -> None:
    """One row per namespace, spelled as a task this product will actually register.

    The `verify` row is the one `R-11` is about, and the case below states that
    half separately rather than leaving it to be inferred from this one.
    """
    assert queue_for(task_name) is expected


def test_a_verification_task_never_resolves_to_the_collection_queue() -> None:
    """`R-11` as its own case, because it is the failure the split exists to prevent.

    A compute-backed Python 3.14 build landing on `collect` occupies the slots
    the daily security sweep needs, and nothing about the system says so: the
    build succeeds, the sweep is merely late, and "late" is exactly what
    `CPM-SM-C1` describes. Asserted as an inequality as well as an identity so a
    resolver that returned the first queue for everything fails here.
    """
    resolved = queue_for(A_VERIFICATION_TASK)

    assert resolved is Queue.VERIFY
    assert resolved is not Queue.COLLECT


@pytest.mark.parametrize(
    "task_name",
    [
        "cpm.sweep.thing",
        "cpm.collect",
        "mymodule.thing",
        "django_service.users.tasks.get_users_count",
        "collect.cpm.thing",
        "cpm",
        "",
    ],
    ids=[
        "unknown-namespace",
        "namespace-with-no-separator",
        "bare-name",
        "inherited-platform-task",
        "prefix-and-namespace-transposed",
        "prefix-alone",
        "empty",
    ],
)
def test_a_name_declaring_no_workload_class_resolves_to_no_queue(task_name: str) -> None:
    """The other half, and the reason `queue_for` returns `None` rather than raising.

    `None` is not an error here: the inherited `get_users_count` is legitimately
    none of collection, policy or verification, and routing it to one of the
    three to satisfy an audit would be the audit describing a rule the
    architecture does not have. What "unrouted" *means* is the routing audit's
    decision, and it is recorded there in an exemption table rather than here.

    The transposed row is the one worth naming: `collect.cpm.thing` carries both
    segments and neither in the position that matters, so a resolver matching on
    membership rather than on position lets it through.
    """
    assert queue_for(task_name) is None


@pytest.mark.parametrize(
    "task_name",
    ["cpm.collect.", "cpm.collect..x"],
    ids=["empty-task-segment", "empty-middle-segment"],
)
def test_a_malformed_name_under_a_known_namespace_still_routes(task_name: str) -> None:
    """Because celery routes it, and the resolver's job is to say where a task goes.

    `fnmatch` matches `*` against the empty string, so `cpm.collect.*` really does
    capture `cpm.collect.` -- a real publish sends it to `collect`. A resolver
    that called these unrouted would be tidier and wrong in the direction that
    costs something: the audit would demand an exemption for a task celery is
    routing perfectly well, and the person adding it would learn that the two
    disagree by arguing with a gate.

    Nobody should name a task either of these. The point is that if somebody
    does, this module and celery say the same thing about it --
    `tests/unit/django_apps/test_task_routing_audit.py` reconciles them against
    the real router, in both directions, over exactly these names.
    """
    assert queue_for(task_name) is Queue.COLLECT


def test_the_route_table_is_built_from_the_mapping_rather_than_written_out_twice() -> None:
    """The derivation itself, which is the property that keeps the names singular.

    Compared as a whole table rather than key by key: a route table with a
    fourth, hand-written entry has the same keys for the three derived ones and
    is still a second declaration of what routes where.
    """
    expected = {route_pattern(namespace): {"queue": queue.value} for namespace, queue in QUEUE_BY_NAMESPACE.items()}

    assert dict(CELERY_TASK_ROUTES) == expected


def test_every_route_pattern_names_its_namespace_under_the_product_prefix() -> None:
    """The patterns are `cpm.<namespace>.*`, which is what makes the name the route.

    Asserted against the prefix constant and the mapping's own keys, so a pattern
    scheme change -- a different separator, a prefix per epic -- fails here rather
    than being discovered when a task publishes to the default queue in
    production.
    """
    assert set(CELERY_TASK_ROUTES) == {f"{TASK_NAMESPACE_PREFIX}.{namespace}.*" for namespace in QUEUE_BY_NAMESPACE}


def test_the_route_table_declares_no_catch_all() -> None:
    """A `"*"` route would capture every task that declared no workload class.

    Including the inherited platform task and the correlation probe, both of
    which have to keep landing on the default queue. It is asserted as an
    absence, and absences are the assertions that rot: the case above pins the
    key set exactly, so this one is the statement of *why*.
    """
    assert CATCH_ALL_PATTERN not in CELERY_TASK_ROUTES


def test_every_routed_pattern_resolves_through_queue_for_to_the_queue_it_names() -> None:
    """The table and the resolver are one rule, so they are reconciled rather than trusted.

    The routing audit reads `queue_for`; celery reads the table. Two answers to
    "where does this task go" that can disagree look exactly like two passing
    tests -- a resolver that had drifted would leave the audit green while real
    messages went to a queue it had never heard of.
    """
    for pattern, route in CELERY_TASK_ROUTES.items():
        a_task_in_the_namespace = pattern.replace(".*", ".a_task")

        assert queue_for(a_task_in_the_namespace) == route["queue"], pattern


def test_the_contributed_key_is_one_the_platform_allowlist_permits() -> None:
    """Inherited `AD-8`: a domain application contributes only to declared keys.

    `CELERY_TASK_ROUTES` is on that list, which is what makes writing this table
    from `core` an adoption rather than an override. Read from the allowlist
    rather than restated, so the day the roster narrows this fails instead of
    quietly describing a permission that was withdrawn.
    """
    assert CONTRIBUTED_SETTING_KEY in CONTRIBUTABLE_KEYS


def test_neither_the_table_nor_a_route_in_it_can_be_edited_by_a_reader() -> None:
    """The table is shared process-wide state once settings hold it.

    `app.conf.task_routes` is a live view over `django.conf.settings`, so a
    module that appended a route to the object it imported -- or repointed an
    existing one at another queue, which is the quieter of the two and the reason
    each route is a proxy of its own -- would change routing for every publisher
    in the process, with nothing in the settings module saying so. A mapping
    proxy makes both a `TypeError` at the point of the edit.

    What this protects is *readers of the settings object*, not celery: celery
    copies each matched route through `dict(route)` in `MapRoute.__call__` before
    it does anything with it, so a mutable inner dict would never be corrupted by
    the router. It would be corrupted by the next module that imported this table
    and decided to adjust one entry, which is the case worth closing.
    """
    with pytest.raises(TypeError):
        CELERY_TASK_ROUTES["cpm.sweep.*"] = {"queue": Queue.COLLECT.value}  # type: ignore[index]

    with pytest.raises(TypeError):
        CELERY_TASK_ROUTES[route_pattern(Queue.VERIFY.value)]["queue"] = Queue.COLLECT.value  # type: ignore[index]
