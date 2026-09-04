"""The instants the suite stops the clock at, in one place.

`tests/unit/conftest.py` builds the `fixed_clock` fixture from this, and
`tests/unit/django_apps/test_clock.py` asserts against them -- including against
the *relationship* between the two instants, which is what
`EVIDENCE.02-INT-001` reads when it asserts two observations are apart by
exactly `OBSERVATION_GAP`. The constants live
here rather than in the conftest because `[tool.pytest.ini_options] addopts`
carries `--import-mode=importlib`: pytest imports `tests/unit/conftest.py` under
its canonical name and a test module that *also* imported it would be reaching
into a conftest, which is a plugin rather than a library. A shared constant
belongs in a helper module, exactly as the readers of the pixi manifest and of
the settings modules do in `tests/pixi_manifest.py` and
`tests/settings_import.py`.

A helper module, not a collected one: `python_files` matches `test_*.py` and
`tests.py`, so nothing here is collected.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Final

#: The instant every unit case that stops the clock is stopped at.
#:
#: Aware and UTC, because `FixedClock` refuses a naive instant and converts an
#: aware one, and because a naive instant is the failure the refusal exists to
#: catch. The date is arbitrary and deliberately not "now": a constant anchored
#: to the run's own wall clock would make a staleness assertion pass or fail
#: depending on when the suite ran, which is the whole class of flakiness the
#: injected clock exists to remove.
FIXED_INSTANT: Final = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

#: How far apart two observations of the same fact are placed.
#:
#: Named rather than spelled at the one call site, because the *distance* is what
#: an assertion about re-observation is made of: the second row's `observed_at`
#: is not merely different from the first's, it is later by exactly this much.
#: Minutes rather than microseconds so that a stored value rounded by a column's
#: precision could not make the two instants compare equal.
OBSERVATION_GAP: Final = timedelta(minutes=5)

#: The second instant, for a case that observes the same fact twice.
#:
#: `FixedClock` is frozen, so a case that needs two instants constructs two
#: clocks rather than winding one forward -- `core/clock.py` says so in those
#: words. This is the instant the second of them is stopped at, derived from
#: `FIXED_INSTANT` rather than written out, so the two cannot drift into an
#: ordering nobody intended.
LATER_INSTANT: Final = FIXED_INSTANT + OBSERVATION_GAP
