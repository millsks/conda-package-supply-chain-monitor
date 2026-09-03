"""The refusal contract: one module, two evaluation stages, one allowlist (AD-26).

FR-12 puts the whole of the refusal contract here rather than inside the
settings module it exists to guard, so that the guard cannot be skipped by the
very failure it catches -- a deployed process pointed at
`config.settings.local`.

**Stage 1** runs at settings import. Every *leaf* settings module --
`local.py`, `production.py`, `test.py` -- calls `run_stage_one(sys.modules[__name__])`
as its last statement, which places the evaluation after the AD-8 composition
step by construction. `base.py` must not call it: it is a composition fragment
consumed through `from .base import *`, so a call at its end would fire before
the leaf finished composing. `tests/unit/startup/test_module_shape.py` asserts
both halves mechanically.

**Stage 2** runs at serving-process startup, owned by the `AppConfig.ready()` of
one named immovable-core app inside `django_service` -- `STAGE_TWO_OWNER_APP_LABEL`
in `stage_two.py`. `ready()` runs inside `django.setup()`, so gunicorn, uvicorn
and every management command reach it alike, and no adopted app may precede the
owner in `INSTALLED_APPS`.

**Exactly four public names.** `run_stage_one` and `run_stage_two` are the two
entry points; every condition is reached through them and none is public.
`is_deployed` and `is_serving_process` are **re-exported from `config.locality`**,
not redefined: Story 3.1 delivered that module as the single declaration site
for the `COMPONENT_*` contract (AD-1), and a second reader here would give the
two variable names two spellings that can drift apart. The re-export is asserted
by object identity rather than by behaviour, which is what proves no second
reader was written.

`config.locality` reads `os.environ` at call time and imports nothing but `os`
and `typing`, so importing it from here introduces no back-import of the
settings module and no circular import at settings-import time. That property is
load-bearing; nothing in this package may import `django.conf.settings` at
module scope.

This story delivers the frame, the locality decision, the two invocation points
and the ordering gate. It delivers exactly one condition -- FR-12's
settings-module escape route, which is the frame's own reason to exist. Stories
4.2, 4.3, 4.4 and 4.6 fill `stage_one.py`, `stage_two.py` and `allowlist.py`.
"""

from __future__ import annotations

from config.locality import is_deployed
from config.locality import is_serving_process
from config.startup.stage_one import run_stage_one
from config.startup.stage_two import run_stage_two

__all__ = [
    "is_deployed",
    "is_serving_process",
    "run_stage_one",
    "run_stage_two",
]
