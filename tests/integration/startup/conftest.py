"""What the startup boot probes share: where the repository is, and how long to wait.

Two modules in this package drive a fresh interpreter through `config.asgi` --
`test_stage_two_fires.py` proves the stage-2 hook fires on a served path, and
`test_stage_two_served_path.py` drives every stage-2 condition from a process
that has served one. Both need the same two facts, and they lived in the first of
those two modules until the second imported them from it.

The third fact -- the environment a child probe inherits -- moved on to
`tests/conftest.py` once `tests/unit/startup/test_refusal_coverage_audit.py`
needed it too. A unit module importing an integration package's conftest is the
same cross-import this file exists to remove, so the builder went to the home
both halves already share rather than being copied. `subprocess_env` is imported
from there by the modules that use it, not re-exported here: a re-export is a
second name for one declaration, and there is nothing here to hang it on.

That direction of import is what this file exists to remove. A collected test
module is not a helper library: importing one from another makes a collection
error in the first surface as an import error in the second, ties the two files'
collection order together, and hands the importer whatever fixtures and
module-scope state the imported file happens to carry. The same changeset that
introduced the cross-import also moved two URLconf builders into
`tests/conftest.py` for precisely the "shared helpers need a shared home"
reason; this is that answer applied consistently.

`tests/integration/conftest.py` is what marks everything beneath it as an
integration test, so nothing here re-applies the marker.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

#: The repository root, the working directory every boot probe is launched from.
#: Four parents up: `conftest.py` -> `startup` -> `integration` -> `tests`.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Generous rather than tight: a cold Django start pays for app loading and four
#: OpenTelemetry instrumentors, and overshooting costs nothing when boot is quick.
BOOT_PROBE_TIMEOUT_SECONDS: Final[float] = 180.0
