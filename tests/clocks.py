"""The instant the suite stops the clock at, in one place.

`tests/unit/conftest.py` builds the `fixed_clock` fixture from this, and
`tests/unit/django_apps/test_clock.py` asserts against it. The constant lives
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
