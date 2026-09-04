"""Fixtures scoped to unit tests.

Unit tests must not touch the database, the network or the filesystem; add
fixtures here only if they hold to that.

`fixed_clock` lives here rather than in `tests/conftest.py` because the whole
point of `CPM-AD-26` is that time is a *parameter*: an integration case that
needs a stopped clock constructs one and passes it, exactly as production code
does, and a shared fixture would only be a second way to reach the same one-line
construction. It is here at all so that every unit case that stops the clock
stops it at the same instant, which is what makes two failures comparable.

The instant itself is in `tests/clocks.py`, not here: a conftest is a plugin, and
a constant two modules share belongs in a helper module they can both import
without one of them importing a plugin.
"""

from __future__ import annotations

import pytest

from conda_package_supply_chain_monitor.core.clock import FixedClock
from tests.clocks import FIXED_INSTANT


@pytest.fixture
def fixed_clock() -> FixedClock:
    """A clock stopped at `tests.clocks.FIXED_INSTANT`.

    Returns:
        A `FixedClock` every reader handed it observes the same instant from.

    """
    return FixedClock(instant=FIXED_INSTANT)
