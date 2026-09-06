"""`EVIDENCE.04-AUDIT-001`: every registered task resolves to one of the three queues.

`CPM-AD-20` splits this product's background work into `collect`, `policy` and
`verify` because they are three workload classes, and `R-11` is the failure the
split prevents: a compute-backed Python 3.14 build sharing a queue with the daily
security sweep starves it. A route table that is *declared* and a task that does
not match it are the same outcome as no routing at all -- the message lands on the
default queue and the split silently does nothing -- so the gate has to be on the
tasks rather than on the table.

**This is asserted as configuration, and that is not a shortcut.**
`CELERY_TASK_ALWAYS_EAGER` is on for the whole suite (`config/settings/test.py`),
and eager `apply_async` short-circuits to `apply()`: `task_routes` is never
consulted, no message is published, and no message acquires a queue. A
`.delay()`-and-look assertion would therefore pass identically against an empty
route table -- it would assert nothing at all. What is available without a broker
is the routing *decision*, and celery will make it on demand:
`app.amqp.router.route({}, name)` is the same lookup a real publish performs, and
the case below reconciles `queue_for` against it so this module's resolver cannot
drift from the one celery uses.

**The registry is swept, never a list.** A hand-written roster of tasks is edited
by whoever remembers it exists, so the first collector added by somebody who did
not is the one that escapes -- the argument `tests/model_registry.py` records for
models, applied to tasks. Two prefixes are skipped, and `tests/celery_tasks.py`
carries the argument for each: celery's own built-ins (`celery.chain`,
`celery.backend_cleanup` and the rest), which are the framework's and are
registered whether or not this product wrote a line; and the suite's own
`tests.…` tasks, of which the correlation probe is the one that exists -- it is
registered by importing the module that declares it, so a counted record of it
would be true in a full run and false in `pixi run test`. Both skips are measured
below rather than trusted.

**The exemption is counted, and it licenses one task in one module.** The
inherited platform demo task `django_service.users.tasks.get_users_count` is none
of collection, policy or verification, and giving it one of the three queues to
satisfy this audit would be the audit describing a rule the architecture does not
have. So it is recorded instead, on exactly the terms
`tests/unit/django_apps/test_clock_audit.py` records the two inherited wall-clock
readers: the module is named, the count is one, a *second* unrouted task in that
module fails the gate as a first one anywhere else would, and a record that no
longer describes the tree fails from the other side. A path skipped wholesale
would do none of that.

**The anti-vacuity half is the load-bearing one today.** No collector, policy
pass or verification build exists yet -- the first arrives with
`CPM-EP-CURRENCY` -- so the sweep passes over one exempted task and nothing else,
which is how an audit becomes permanently green and permanently useless. What
keeps it honest is that the detector is measured against fixture tasks registered
in the real registry and removed afterwards, one per row of this story's
edge-case matrix. `tests/celery_tasks.py` owns the registration and the removal,
and states why celery has no `isolate_apps` equivalent to borrow.

Reads the task registry and calls a pure resolver: no database, no network, no
broker.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_package_supply_chain_monitor.collectors.sweep import SWEEP_TASK_NAME
from conda_package_supply_chain_monitor.core.queues import QUEUE_BY_NAMESPACE
from conda_package_supply_chain_monitor.core.queues import TASK_NAMESPACE_PREFIX
from conda_package_supply_chain_monitor.core.queues import Queue
from conda_package_supply_chain_monitor.core.queues import queue_for
from config.celery_app import app
from tests.celery_tasks import EXCLUDED_TASK_PREFIXES
from tests.celery_tasks import SUITE_TASK_PREFIX
from tests.celery_tasks import product_task_names
from tests.celery_tasks import registered_task_names
from tests.celery_tasks import registered_tasks

if TYPE_CHECKING:
    from collections.abc import Iterable

# Modules licensed to register tasks that resolve to no product queue, and how
# many each may register.
#
# One entry, and it is the inherited platform's demo task. `get_users_count`
# counts rows in the user table: it makes no outbound call, computes no derived
# status and builds nothing, so none of `collect`, `policy` or `verify`
# describes it. It predates `CPM-EP-EVIDENCE`, it sits outside this epic's
# binding, and renaming it into the `cpm.` namespace would rename an inherited
# platform task to satisfy a product audit.
#
# The count is what makes this an exemption rather than a skipped directory: a
# second unrouted task added to `django_service/users/tasks.py` fails this gate
# exactly as one added anywhere else would. Both directions are checked below.
RECORDED_EXEMPTIONS: Final[dict[str, int]] = {"django_service.users.tasks": 1}

#: The one task the exemption is about, named so the anti-vacuity guard can
#: assert the sweep still reaches it. A rename or a removal fails here rather
#: than leaving the sweep quietly looking at nothing.
AN_INHERITED_PLATFORM_TASK: Final[str] = "django_service.users.tasks.get_users_count"

#: A built-in the sweep must be able to see and must then skip. Asserted to be
#: present before it is asserted to be excluded: a built-in that had gone away
#: would satisfy "not in scope" for the wrong reason and the exclusion this
#: audit relies on would go untested.
A_CELERY_BUILT_IN: Final[str] = "celery.chain"

#: Fixture task names, one per row of the story's edge-case matrix. Spelled as
#: tasks this product plausibly registers rather than as `test_1`, so a failure
#: reads as the case it stands for.
#: `cpm.collect.fixture_release` rather than a real collector's name: the registry
#: refuses a fixture registered over a task it already holds, and
#: `cpm.collect.pypi_release` became one of those with `CPM-CURRENCY-S02`.
A_COLLECTOR_TASK: Final[str] = "cpm.collect.fixture_release"
A_POLICY_TASK: Final[str] = "cpm.policy.currency"
A_VERIFICATION_TASK: Final[str] = "cpm.verify.py314_build"
A_PRODUCT_TASK_IN_NO_NAMESPACE: Final[str] = "cpm.sweep.thing"
A_PRODUCT_TASK_WITH_A_BARE_NAME: Final[str] = "conda_package_supply_chain_monitor.collectors.tasks.fetch"
A_SECOND_TASK_IN_THE_EXEMPTED_MODULE: Final[str] = "django_service.users.tasks.count_something_else"

#: The last segment of the policy run's declared name, and the module celery's
#: autodiscovery imports it from.
#:
#: Spelled here rather than imported from `core.tasks`, deliberately: importing
#: that module *registers* the task, so a case that imported the constant would
#: read a registry it had seeded itself and would stay green over a policy run
#: declared in a module autodiscovery never scans. The namespace and the queue
#: still come from `core/queues.py`, so a renamed queue fails here rather than
#: routing the task nowhere.
POLICY_RUN_TASK_SUFFIX: Final[str] = "run"
AUTODISCOVERED_TASK_MODULE: Final[str] = "conda_package_supply_chain_monitor.core.tasks"

#: Every name the resolver and celery's router are reconciled over, well-formed
#: and not.
#:
#: The malformed rows are the ones that found a real disagreement: `cpm.collect.`
#: and `cpm.collect..x` are routed to `collect` by a real publish, because
#: `fnmatch` matches `*` against the empty string, while the first version of
#: `queue_for` called both unrouted. The negative rows are here for the other
#: direction -- a resolver that started routing them would send work to a queue
#: celery had never heard of, and only a case that checks *both* directions over
#: *both* kinds of name would notice either.
ROUTER_AGREEMENT_NAMES: Final[tuple[str, ...]] = (
    A_COLLECTOR_TASK,
    SWEEP_TASK_NAME,
    A_POLICY_TASK,
    A_VERIFICATION_TASK,
    "cpm.collect.",
    "cpm.collect..x",
    "cpm.collect.a.b.c",
    "cpm.collect",
    A_PRODUCT_TASK_IN_NO_NAMESPACE,
    A_PRODUCT_TASK_WITH_A_BARE_NAME,
    AN_INHERITED_PLATFORM_TASK,
    "collect.cpm.thing",
    "cpm",
)


def declaring_module(task_name: str) -> str:
    """Return the module part of a task name.

    Args:
        task_name: The task's registered name.

    Returns:
        Everything before the last separator -- `django_service.users.tasks` for
        the inherited demo task. Read off the *declared name* rather than off
        `Task.__module__`, because the name is what routing matches and what an
        exemption is granted against; a task whose name says one thing and whose
        module says another must be judged on the half celery reads.

    """
    return task_name.rpartition(".")[0]


def unrouted(task_names: Iterable[str]) -> list[str]:
    """Return every task name that resolves to no product queue.

    Args:
        task_names: The names to resolve.

    Returns:
        The unrouted names, sorted. Sorted rather than in registry order so the
        exemption below is spent deterministically: two runs must license the
        same task.

    """
    return sorted(name for name in task_names if queue_for(name) is None)


def audit_failures(task_names: Iterable[str]) -> list[str]:
    """Return every routing failure among a set of registered task names.

    Args:
        task_names: The names to audit, celery's built-ins already removed.

    Returns:
        One message per offending task, each naming the task and the three
        namespaces a product task may declare. Empty when every name either
        resolves to a queue or is covered by the recorded exemption.

    """
    by_module: defaultdict[str, list[str]] = defaultdict(list)
    for name in unrouted(task_names):
        by_module[declaring_module(name)].append(name)

    permitted = sorted(QUEUE_BY_NAMESPACE)
    failures: list[str] = []
    for module, names in sorted(by_module.items()):
        licensed = RECORDED_EXEMPTIONS.get(module, 0)
        failures.extend(
            f"{name} resolves to no queue. A task this product registers declares its workload class in its "
            f"name -- one of {permitted} under the cpm. prefix -- because routing is derived from the name and "
            f"never from the module (CPM-AD-20, R-11). {module} is licensed for {licensed} unrouted task(s)."
            for name in names[licensed:]
        )
    return failures


# ---------------------------------------------------------------------------
# The sweep, and the guards that it is looking at the right things.
# ---------------------------------------------------------------------------


def test_the_sweep_reaches_the_inherited_platform_task() -> None:
    """The anti-vacuity guard: autodiscovery ran and the registry is populated.

    `config/celery_app.py` ends in a *lazy* `autodiscover_tasks()`, so a session
    in which nothing had imported `django_service.users.tasks` would see celery's
    built-ins and nothing else -- an empty sweep passing every assertion below
    while proving nothing. `tests/celery_tasks.py` forces the import; this is
    what proves the forcing worked.
    """
    assert AN_INHERITED_PLATFORM_TASK in product_task_names()


def test_the_sweep_skips_celerys_own_built_ins_and_can_see_them() -> None:
    """Both halves, because either alone is satisfied for the wrong reason.

    A run where celery had stopped registering `celery.chain` would satisfy "no
    built-in is in scope" without the exclusion doing anything, and the day the
    prefix filter is widened by accident this is what notices.
    """
    assert A_CELERY_BUILT_IN in registered_task_names()
    assert [name for name in product_task_names() if name.startswith(EXCLUDED_TASK_PREFIXES)] == []


def test_the_sweep_skips_the_suites_own_tasks_and_nothing_wider() -> None:
    """The other exclusion, measured rather than asserted as an absence.

    `tests/integration/test_celery_log_correlation.py` declares a
    `@shared_task` at module scope, and a shared task registers into every
    `Celery` instance in the process -- so in a full-suite run the probe is in the
    registry the sweep reads, while in a `pixi run test` run it is not. That is
    why it is skipped by prefix rather than recorded in the counted table: a
    record saying "one" would be false in half the ways this suite is invoked.

    Measured with a fixture registered under a suite-shaped name and one
    registered under a product-shaped name, in the same pass: the first must be
    skipped and the second must not, which is what "narrow" means here.
    """
    a_suite_task = f"{SUITE_TASK_PREFIX}integration.test_something.probe"

    with registered_tasks(a_suite_task, A_PRODUCT_TASK_WITH_A_BARE_NAME):
        in_scope = product_task_names()

        assert a_suite_task not in in_scope
        assert A_PRODUCT_TASK_WITH_A_BARE_NAME in in_scope


def test_the_full_inventory_dispatch_is_a_registered_task_that_routes_to_collect() -> None:
    """`CPM-CURRENCY-S05`'s dispatch, named rather than left to the sweep to notice.

    The sweep above covers it, and covering it is not the same as saying so: this
    is the one product task that is fired by `django_celery_beat` rather than by
    another task, so a name that stopped routing would leave every scheduled
    sweep published to a queue no worker drains -- silently, on every tick, with a
    ledger that records nothing because nothing ran.
    """
    assert SWEEP_TASK_NAME in product_task_names()
    assert queue_for(SWEEP_TASK_NAME) is Queue.COLLECT


def test_every_registered_task_resolves_to_a_queue_or_is_recorded() -> None:
    """`EVIDENCE.04-AUDIT-001`, over the registry this component actually ships.

    One exempted task today and no product tasks at all, which is stated rather
    than hidden: the fixture half below is what keeps the detector honest until
    `CPM-EP-CURRENCY` registers the first collector, and this case needs no edit
    to start mattering on that day.
    """
    assert audit_failures(product_task_names()) == []


def test_the_exemption_table_has_entries_to_check() -> None:
    """The case below means nothing if the table it reads is empty."""
    assert RECORDED_EXEMPTIONS != {}


@pytest.mark.parametrize("module", sorted(RECORDED_EXEMPTIONS), ids=str)
def test_every_recorded_exemption_still_describes_the_registry(module: str) -> None:
    """The other side of the table: a licence nobody meant to leave open.

    Checked in the direction the exemption is granted, exactly as the source
    scans check theirs. Route `get_users_count` into a `cpm.` namespace, or
    delete it, and this fails until its entry goes with it -- so the table cannot
    outlive the thing it describes and quietly license a future task instead.
    """
    found = [name for name in unrouted(product_task_names()) if declaring_module(name) == module]

    assert len(found) == RECORDED_EXEMPTIONS[module], f"{module} holds {found}, recorded {RECORDED_EXEMPTIONS[module]}"


@pytest.mark.parametrize("module", sorted(RECORDED_EXEMPTIONS), ids=str)
def test_every_exempted_task_really_lives_in_the_module_it_is_recorded_under(module: str) -> None:
    """The licence is granted to a module, and a name is not proof of one.

    `declaring_module` reads the module out of the *declared name*, which is
    correct for routing -- celery matches the name and nothing else -- and is not
    proof of where the task was written. A task declared anywhere at all with
    `@shared_task(name="django_service.users.tasks.anything")` would spend this
    exemption, and the review that granted it was a review of a file.

    So the two halves are reconciled here: the exempted task's `__module__` --
    which celery takes from the function it decorated -- has to agree with the
    module its name claims. The name stays the thing the audit routes on; this is
    the case that stops the name being enough to *inherit* somebody else's
    exemption.
    """
    for name in unrouted(product_task_names()):
        if declaring_module(name) != module:
            continue
        assert app.tasks[name].__module__ == module, (
            f"{name} is exempted under {module} but was declared in {app.tasks[name].__module__}"
        )


# ---------------------------------------------------------------------------
# The routing decision, reconciled against the one celery would make.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task_name", ROUTER_AGREEMENT_NAMES, ids=lambda name: name or "empty")
def test_celerys_own_router_sends_the_name_where_queue_for_says(task_name: str) -> None:
    """The configuration-level proof, and the reason eager execution is irrelevant.

    `app.amqp.router.route({}, name)` is the lookup a real `apply_async` performs
    before it publishes, and it needs no broker to answer. Reconciling it against
    `queue_for` is what stops this module's resolver becoming a second opinion:
    an audit that read one rule while celery followed another would be green
    while every `verify` build went to `collect`.

    **Both directions, over the malformed names as well as the well-formed
    ones.** Every name `queue_for` routes must reach that queue under the router,
    and every name it calls `None` must reach `task_default_queue` -- one
    expectation covering both, so neither direction can be the one nobody wrote.
    That is not a completeness gesture: `cpm.collect.` and `cpm.collect..x` are
    where the two really did disagree, because `fnmatch` matches `*` against the
    empty string and the first version of this resolver did not.
    """
    resolved = queue_for(task_name)
    expected = app.conf.task_default_queue if resolved is None else resolved.value

    assert app.amqp.router.route({}, task_name)["queue"].name == expected


def test_an_unrouted_name_keeps_landing_on_the_inherited_default_queue() -> None:
    """No catch-all, stated as the consequence it exists for.

    `tests/integration/test_celery_log_correlation.py` turns eager execution off
    and really publishes a probe that declares no `cpm.` name; the inherited
    `get_users_count` is in the same position. Both must keep reaching the queue
    the worker drained before this story, which is what a `"*"` pattern would
    take away.
    """
    routed = app.amqp.router.route({}, AN_INHERITED_PLATFORM_TASK)["queue"].name

    assert routed == app.conf.task_default_queue
    assert routed not in {queue.value for queue in Queue}


# ---------------------------------------------------------------------------
# The anti-vacuity half: the detector, measured against real registered tasks.
# ---------------------------------------------------------------------------


def test_the_detector_accepts_a_task_in_each_namespace() -> None:
    """The conforming case, which every rejection below is only meaningful against.

    Three fixture tasks registered in the real registry at once, so the sweep
    meets them the way it will meet `CPM-EP-CURRENCY`'s collectors: as names in
    `app.tasks` that it did not know were coming.
    """
    with registered_tasks(A_COLLECTOR_TASK, A_POLICY_TASK, A_VERIFICATION_TASK):
        assert audit_failures(product_task_names()) == []


def test_the_detector_rejects_a_product_task_in_an_unknown_namespace() -> None:
    """`cpm.sweep.thing`: the prefix is right and the workload class is invented.

    A namespace nobody routed is not a harmless name -- the task publishes to the
    default queue, which no `-Q` list treats as `collect`, `policy` or `verify`,
    so it runs beside the platform's own work with none of the isolation the
    split was built for.
    """
    with registered_tasks(A_PRODUCT_TASK_IN_NO_NAMESPACE):
        failures = audit_failures(product_task_names())

        assert len(failures) == 1
        assert A_PRODUCT_TASK_IN_NO_NAMESPACE in failures[0]
        assert all(namespace in failures[0] for namespace in QUEUE_BY_NAMESPACE)


def test_the_detector_rejects_a_product_task_that_declared_no_name_at_all() -> None:
    """The default celery gives a task nobody named: `module.function`.

    This is what a collector written under `src/django_apps/` gets for free from
    a bare `@shared_task()`, and it is the spelling `CPM-EP-CURRENCY` is most
    likely to arrive with. It routes nowhere, and the module it lives in cannot
    be licensed for it -- which is the whole of `CPM-AD-20`'s "the name declares
    the class".
    """
    with registered_tasks(A_PRODUCT_TASK_WITH_A_BARE_NAME):
        failures = audit_failures(product_task_names())

        assert len(failures) == 1
        assert A_PRODUCT_TASK_WITH_A_BARE_NAME in failures[0]


def test_the_exemption_licenses_one_task_and_not_the_module() -> None:
    """A second unrouted task in the exempted module fails the gate.

    The reason the exemption is a count rather than a path. `django_service/users/tasks.py`
    is licensed for the one demo task that was reviewed; the next task added
    there is a new decision, and it surfaces here rather than inheriting a
    licence granted for something else.

    *Which* of the module's two unrouted tasks the licence is spent on is
    arbitrary -- a count cannot say, and the resolution is alphabetical so that
    two runs at least agree. So the assertion is on the number of failures and on
    the module they name, which is the property the exemption actually has;
    claiming the fixture would be reported is a claim the mechanism does not
    make.
    """
    module = declaring_module(A_SECOND_TASK_IN_THE_EXEMPTED_MODULE)

    with registered_tasks(A_SECOND_TASK_IN_THE_EXEMPTED_MODULE):
        failures = audit_failures(product_task_names())

        assert len(failures) == 1
        assert failures[0].startswith(module)
        assert f"licensed for {RECORDED_EXEMPTIONS[module]} unrouted task(s)" in failures[0]


def test_the_detector_separates_the_routed_from_the_unrouted_in_one_sweep() -> None:
    """The whole rule exercised at once, which is how the sweep will meet it.

    A detector that failed everything passes each rejection above in isolation,
    and one that failed nothing passes the acceptance case. Five fixture tasks in
    one pass is what fails both.
    """
    routed = (A_COLLECTOR_TASK, A_POLICY_TASK, A_VERIFICATION_TASK)
    unroutable = (A_PRODUCT_TASK_IN_NO_NAMESPACE, A_PRODUCT_TASK_WITH_A_BARE_NAME)

    with registered_tasks(*routed, *unroutable):
        failures = audit_failures(product_task_names())

        assert {failure.split(" ", 1)[0] for failure in failures} == set(unroutable)
        assert len(failures) == len(unroutable)


def test_the_fixture_tasks_leave_the_registry_as_they_found_it() -> None:
    """The helper's own guard, asserted here because this module is what relies on it.

    A fixture task left behind would be swept by every later case in the session
    as though it were a real registered task, and the audit it was written to
    exercise would then fail somewhere else entirely, naming a task no source
    file declares.
    """
    before = registered_task_names()

    with registered_tasks(A_COLLECTOR_TASK, A_PRODUCT_TASK_IN_NO_NAMESPACE):
        assert A_COLLECTOR_TASK in registered_task_names()

    assert registered_task_names() == before


def test_the_helper_refuses_to_register_over_a_task_that_already_exists() -> None:
    """The displacement guard, exercised rather than only described.

    A fixture registered under a real task's name would replace it for the body
    of the `with` and then be *removed* on the way out, taking the real task with
    it -- so every later case in the session would sweep a registry missing the
    one task this audit is actually about, and the exemption below it would start
    failing as stale. The guard is load-bearing and was untested.
    """
    with pytest.raises(ValueError, match="already holds"), registered_tasks(AN_INHERITED_PLATFORM_TASK):
        pass


def test_the_helper_reports_a_registry_left_different_from_the_one_it_found() -> None:
    """The drift guard, exercised by leaking a task past it on purpose.

    The `finally` pops what it registered; anything else that arrived in the
    registry meanwhile is drift the helper cannot clean up, and reporting it where
    it happened is the difference between one failing case and a later, unrelated
    audit failing on a task no source file declares.

    The intruder is popped by this case rather than by the helper, because the
    helper's contract is to remove what *it* registered -- cleaning up after
    arbitrary other writers is a different and much larger promise.
    """
    intruder = f"{SUITE_TASK_PREFIX}drift.intruder"

    def _intrude() -> None:
        """Stand in for whatever else registered a task during the body."""

    try:
        with pytest.raises(ValueError, match="changed the celery registry"), registered_tasks(A_COLLECTOR_TASK):
            app.task(name=intruder, shared=False)(_intrude)
    finally:
        app.tasks.pop(intruder, None)

    assert intruder not in registered_task_names()


def test_the_policy_run_task_is_registered_and_routed_to_the_policy_queue() -> None:
    """`CPM-EVIDENCE-S07`'s task, asserted by name rather than only by the sweep above.

    The sweep is a *negative*: it fails a task that resolves to no queue. That
    passes just as well for a task nothing ever registered, which is exactly what
    a policy run declared outside `core/tasks.py` would produce -- celery's
    autodiscovery imports each application's `tasks` module and no other, so a
    task in a module named anything else is registered nowhere and the beat row
    can never reach it.

    **The name is composed here rather than imported from the module it names,
    and that is the load-bearing half.** Importing `POLICY_RUN_TASK_NAME` from
    `core.tasks` imports the module, which registers the task -- so this case
    would pass over a registry it had itself seeded, and renaming the module to
    something autodiscovery does not scan would leave the suite green while beat
    could never reach the task. Built from `core/queues.py`'s own parts, the
    registry read is the one autodiscovery produced.

    The declaring module is asserted for the same reason: it is what says the
    task lives where autodiscovery looks.
    """
    composed = f"{TASK_NAMESPACE_PREFIX}.{Queue.POLICY.value}.{POLICY_RUN_TASK_SUFFIX}"

    assert composed in product_task_names(), (
        f"{composed} is not registered. Celery's autodiscovery imports each application's `tasks` module and "
        f"no other; a policy run declared anywhere else is never registered and never runs."
    )
    assert queue_for(composed) is Queue.POLICY
    assert declaring_module(composed) == f"{TASK_NAMESPACE_PREFIX}.{Queue.POLICY.value}"
    assert declaring_module(composed) not in RECORDED_EXEMPTIONS
    assert app.tasks[composed].__module__ == AUTODISCOVERED_TASK_MODULE, (
        f"the policy run is declared outside {AUTODISCOVERED_TASK_MODULE}; celery's autodiscovery imports "
        f"each application's `tasks` module and no other, so it would be registered only by whatever "
        f"happened to import it -- this suite, and not a worker."
    )
