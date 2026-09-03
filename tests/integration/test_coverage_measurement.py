"""Tests that the measurement AD-20 describes is the measurement actually running.

`tests/unit/test_coverage_policy.py` pins what the manifests *declare*. This
module pins what is *in force*, which is a different claim and the one AD-20
actually makes: "a test asserts it is in force during a gate run". A declaration
that is read by nothing, or overridden by an environment that never inherited
it, still reads correctly in review.

Four things are interrogated on the live session:

* the tracer core, because under the `sysmon` core that Python 3.12+ selects by
  default the template plugin is loaded, templates are discovered, and every
  one of them reports zero -- a green run measuring nothing;
* a template that this test just rendered, read out of the live coverage data;
* the floor, because every other assertion about it string-matches `pixi.toml`
  and a declaration read by nothing still reads correctly in review;
* the effective omit, include and exclude lists, reconciled in both directions
  against the declared surface.

These need a running coverage session and a rendered response, so they are
integration tests rather than unit tests. They leave no state behind: the only
writes are the ones `django_db` rolls back.

The declared surface is read through `tests/coverage_policy.py`, the single
reader Epic 7 repoints at `accelerator.toml`.
"""

from __future__ import annotations

import os
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from coverage.config import DEFAULT_EXCLUDE
from django.urls import reverse

from tests.coverage_policy import DECLARATION_SITE
from tests.coverage_policy import FLOOR_FLAG
from tests.coverage_policy import FLOOR_SITE
from tests.coverage_policy import declared_exclude
from tests.coverage_policy import declared_floor
from tests.coverage_policy import declared_include
from tests.coverage_policy import declared_omit
from tests.coverage_policy import reconcile
from tests.coverage_policy import require_coverage_session

if TYPE_CHECKING:
    from coverage import Coverage
    from django.test import Client

    from django_service.users.models import User

# `tests/integration/conftest.py` already applies `integration` to everything
# collected here; it is declared explicitly as well so the marker is visible in
# the file it applies to. `django_db` is needed because the rendered surface
# below is a logged-in page.
pytestmark = [pytest.mark.integration, pytest.mark.django_db]

# What `Collector.tracer_name()` reports when the C trace core is in force. The
# alternative is "SysMonitor", the Python 3.12+ default, under which
# django_coverage_plugin -- a dynamic file tracer needing `sys.settrace` -- is
# never consulted.
C_TRACE_COLLECTOR = "CTracer"

COVERAGE_CORE_VARIABLE = "COVERAGE_CORE"
C_TRACE_CORE = "ctrace"

# The rendered surface. `users/user_detail.html` is `core` in every combination
# of the accelerator and survives AD-29's deletion of the `home` and `about`
# demonstration pages, so this assertion does not have to be rewritten in
# Epic 7. Expressed as path segments because coverage reports absolute paths.
MEASURED_TEMPLATE = ("django_service", "templates", "users", "user_detail.html")


@pytest.fixture
def coverage_session(request: pytest.FixtureRequest) -> Coverage:
    """Return the coverage session measuring this run.

    The pytest config is handed over rather than the session being looked up
    alone, because "no session" and "no session was asked for" are different
    situations: the first fails, the second skips. See
    `tests.coverage_policy.require_coverage_session` for why, and for why the
    skip is written there rather than here.
    """
    return require_coverage_session(request.config)


def test_the_c_trace_core_is_in_force_during_the_run(coverage_session: Coverage) -> None:
    """AC #1: the core is asserted during the run, not inherited on trust.

    The collector is asked what it is, rather than the environment being asked
    what it was told. `COVERAGE_CORE` is an activation variable, so a runner
    that starts pytest outside the pixi environment -- an IDE, a CI step that
    forgot `pixi run` -- inherits nothing and silently falls back to `sysmon`.
    The environment check below is the weaker, second half: it catches the
    declaration being removed, which the collector check alone would not
    distinguish from a coverage release changing its default.
    """
    # `_collector` is private and there is no public accessor for the tracer in
    # use; the alternative is to assert nothing about the core that is actually
    # running, which is the one thing this AC asks for.
    collector = coverage_session._collector  # noqa: SLF001
    assert collector.tracer_name() == C_TRACE_COLLECTOR, (
        f"coverage is collecting with {collector.tracer_name()!r}, not {C_TRACE_COLLECTOR!r}; "
        "django_coverage_plugin is a dynamic file tracer and every template will report 0%"
    )
    assert os.environ.get(COVERAGE_CORE_VARIABLE) == C_TRACE_CORE, (
        f"{COVERAGE_CORE_VARIABLE} is {os.environ.get(COVERAGE_CORE_VARIABLE)!r} in this process, not {C_TRACE_CORE!r}"
    )


def test_a_rendered_template_reports_executed_lines(
    client: Client,
    user: User,
    coverage_session: Coverage,
) -> None:
    """AC #2: template measurement is real, not merely configured.

    Two assertions, and the pair is the proof:

    * **The response is 200.** On its own this proves nothing about
      measurement -- `tests/integration/test_template_rendering.py` already
      checks it, and it passes unchanged under the `sysmon` core with every
      template reporting zero, which is the failure AD-20 exists to catch. It
      is here because the coverage data below is *session-cumulative*: it
      accumulates across every test in the run, and both
      `test_template_rendering.py` and `tests/integration/users/test_views.py`
      render this same page. A broken `force_login`, a redirect or a 404 here
      would render nothing, and another test's data would satisfy the lines
      assertion anyway. The status is what says the render being read about is
      this one.
    * **The template reports executed lines.** This is the AC #2 assertion and
      the status check is emphatically not a substitute for it: executed lines
      are the only evidence distinguishing "measured and covered" from
      "discovered and never traced".

    Not a before/after line-count delta: an earlier test can already have taken
    this template to 100%, so no growth is expected and its absence would not
    mean anything.

    `get_data()` flushes the collector, so the lines this request just executed
    are visible without ending the session.
    """
    client.force_login(user)
    response = client.get(reverse("users:detail", kwargs={"username": user.username}))
    assert response.status_code == HTTPStatus.OK, (
        f"the page under test returned {response.status_code}, so this test rendered no template; "
        "the coverage data below is session-cumulative and would be satisfied by another test's render"
    )

    data = coverage_session.get_data()
    depth = len(MEASURED_TEMPLATE)
    rendered = [path for path in data.measured_files() if Path(path).parts[-depth:] == MEASURED_TEMPLATE]
    assert rendered, (
        f"coverage measured no file at {'/'.join(MEASURED_TEMPLATE)}; "
        "the template plugin discovered nothing, so nothing was measured"
    )

    executed = {path: data.lines(path) for path in rendered}
    assert all(lines for lines in executed.values()), (
        f"the template was rendered but reports no executed lines: {executed}. "
        "Templates are being discovered and not traced -- check COVERAGE_CORE "
        "and TEMPLATES[0]['OPTIONS']['debug']"
    )


def test_the_declared_floor_is_the_floor_in_force(
    request: pytest.FixtureRequest,
    coverage_session: Coverage,
) -> None:
    """AC #4: the floor is asserted where it can actually fail to apply.

    Every other assertion about the floor string-matches `pixi.toml`, and the
    thesis of this module is that a declaration read by nothing still reads
    correctly in review. The value is taken from the running configuration and
    compared against the one the manifest declares, read back through
    `tests/coverage_policy.py` rather than restated -- a third hardcoded `90`
    would agree with the other two by construction and observe nothing.

    `coverage_session` is requested for its guard, not its value: this runs
    under the same rule as the rest of the live assertions here, so a gate run
    that requested coverage and is not measuring fails rather than skips.
    """
    in_force = request.config.getoption(FLOOR_FLAG)
    assert in_force == declared_floor(), (
        f"{FLOOR_FLAG} is {in_force!r} in this run but {FLOOR_SITE} declares {declared_floor()}; "
        "the floor that ran is not the floor that was declared"
    )


def test_the_effective_omit_list_equals_the_declared_one(coverage_session: Coverage) -> None:
    """AC #3: the list in force is the list declared, reconciled both ways.

    The declaration and the effective configuration come from the same file
    today, so this passes trivially -- until something else supplies coverage
    configuration. A `.coveragerc`, a `setup.cfg` or a `COVERAGE_RCFILE` in the
    environment all outrank or displace `pyproject.toml`, and any of them would
    leave the declared list looking untouched while a different one ran.
    """
    missing, unexpected = reconcile(declared_omit(), list(coverage_session.config.run_omit))
    assert (missing, unexpected) == ([], []), (
        f"the omit list in force is not the one declared at {DECLARATION_SITE}: "
        f"declared but not in force {missing}, in force but not declared {unexpected}"
    )


def test_the_effective_measurement_bound_equals_the_declared_one(coverage_session: Coverage) -> None:
    """AC #3: `include` is reconciled the same way, for the same reason.

    What this pins is the *declaration*. It is not the bound in force during
    the gate: `test-cov` passes `--cov=src`, which sets coverage's source, and
    a source supersedes `include` -- coverage warns `--include is ignored
    because --source is set` on every run. The bound actually in force is
    therefore the task's `--cov` argument, and
    `tests/unit/test_coverage_policy.py` pins that separately. Both are needed;
    neither substitutes for the other.
    """
    missing, unexpected = reconcile(declared_include(), list(coverage_session.config.run_include))
    assert (missing, unexpected) == ([], []), (
        f"the measurement bound in force is not the one declared at {DECLARATION_SITE}: "
        f"declared but not in force {missing}, in force but not declared {unexpected}"
    )


def test_the_effective_exclude_list_is_coverages_untouched_default(coverage_session: Coverage) -> None:
    """AC #3: nothing has been added to the line-exclusion surface.

    The project declares no exclusions, so the list in force must be coverage's
    own default -- compared against the library's `DEFAULT_EXCLUDE` rather than
    against a copy of it, so a new default in a future `coverage >=7.15,<8`
    release is not read as a project-declared exclusion.

    Reconciled in both directions with the declared surface added in, so a
    pattern appearing on either side names itself.
    """
    expected = [*DEFAULT_EXCLUDE, *declared_exclude()]
    missing, unexpected = reconcile(expected, list(coverage_session.config.exclude_list))
    assert (missing, unexpected) == ([], []), (
        f"the exclude list in force is not coverage's default plus the surface declared at {DECLARATION_SITE}: "
        f"declared but not in force {missing}, in force but not declared {unexpected}"
    )
