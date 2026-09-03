"""Locality and process type, read from the environment the pixi environment declares.

AD-13. A component is *deployed* unless it says otherwise. The declaration is
`COMPONENT_RUNTIME=local`, and it lives exactly once, in
`[feature.dev.activation.env]`: every developer path runs in the `dev` pixi
environment and inherits it, so a freshly cloned component is local from the
first command and no untracked file has to be created to make it so. The
`default` environment declares nothing and therefore reads *deployed* -- which
is what the golden base runs, and what the release stage invokes when it calls
`pixi run migrate` and `pixi run collectstatic`.

Nothing is declared on a task. A task's `env` *overrides* the caller's
environment, so a task-level `COMPONENT_RUNTIME=local` on `migrate` could not be
corrected by the deployment platform's configmap and would make the production
release stage read *local*. Declaring nothing in `default` inverts that: the
platform keeps sole control of the variable, and absence fails closed.

Two defaults, deliberately opposite, and neither may be tidied into the other:

* **Locality fails closed.** Absent or unrecognized means *deployed*. Local
  development is the exception that has to declare itself, so a declaration lost
  anywhere between here and production leaves the refusals armed rather than
  disarmed.
* **Process type fails open.** Absent means *not a serving process*. Failing it
  closed would make `pixi run migrate` -- a release-stage step -- declare itself
  a serving process and refuse on the unapplied-migrations condition, deadlocking
  the release. The recorded price is R-3: a serving process started outside
  `pixi run web` does not fire the migrations refusal.

This module owns two names -- `COMPONENT_RUNTIME` and `COMPONENT_PROCESS` -- and
the values each accepts, and it is the only place in the tree where either is
spelled (AD-1). It does not own the wider `COMPONENT_*` convention, which the
spine's Consistency Conventions define; a third component-level fact invented
later would be declared wherever it is read, not necessarily here. Epic 4's
`src/config/startup/` imports this module rather than re-reading `os.environ`;
Epic 5's `web`, `worker` and `beat` tasks are the producers of
`COMPONENT_PROCESS`. Do not add a second reader, and do not infer locality from
`sys.argv`, `DEBUG`, the settings module name, `DJANGO_ENV` or a bare `ENV` -- a
platform is likely to set a generic `ENV=dev` for a development *deployment*,
and a deployed dev environment is still deployed.

Every function reads `os.environ` at call time rather than at import time, so a
process that sets a variable after import -- and a test that uses
`monkeypatch.setenv` -- is observed without reloading the module.
"""

from __future__ import annotations

import os
from typing import Final

__all__ = [
    "LOCAL",
    "PROCESS_ENV_VAR",
    "RUNTIME_ENV_VAR",
    "SERVING_PROCESSES",
    "component_process",
    "is_deployed",
    "is_local",
    "is_serving_process",
]

#: The variable the `dev` pixi environment declares in its activation env, and
#: the only `COMPONENT_*` variable permitted in an activation env at all. Never
#: in `[activation.env]`, and never in a task's `env`: the unscoped table is
#: evaluated by the golden base in production, and a task `env` overrides the
#: caller, which takes the deployment platform's configmap out of the loop.
RUNTIME_ENV_VAR: Final[str] = "COMPONENT_RUNTIME"

#: The variable a serving-process task sets in its own `env` (Epic 5, AD-14).
#: Never in *any* activation env, feature-scoped included: placed there it would
#: make every management command declare itself a serving process, `pixi run
#: migrate` included, and deadlock the release stage on the migrations refusal.
PROCESS_ENV_VAR: Final[str] = "COMPONENT_PROCESS"

#: The one recognized value of `COMPONENT_RUNTIME`. Anything else is deployed.
LOCAL: Final[str] = "local"

#: The process types that serve traffic or consume work. Anything else -- a
#: management command, a shell, a test run -- is not a serving process.
SERVING_PROCESSES: Final[frozenset[str]] = frozenset({"web", "worker", "beat"})


def is_local() -> bool:
    """Report whether this process is running in a local development environment.

    Fails closed: only the value `local`, after stripping surrounding whitespace
    and lowercasing, counts. `dev`, `1`, `true`, the empty string and an absent
    variable all mean deployed, so a declaration that never arrived is deployed
    rather than silently local.

    Returns:
        True when `COMPONENT_RUNTIME` declares this a local run.
    """
    return os.environ.get(RUNTIME_ENV_VAR, "").strip().lower() == LOCAL


def is_deployed() -> bool:
    """Report whether this process is running deployed.

    The default, and the answer whenever locality is not declared: deployment
    requires no declaration, which is what keeps a lost declaration safe.

    Returns:
        True when nothing declares this a local run.
    """
    return not is_local()


def component_process() -> str | None:
    """Return the declared serving-process type, or None when there is none.

    Fails open: an unset, empty or unrecognized `COMPONENT_PROCESS` yields None
    rather than a guess. Only the members of `SERVING_PROCESSES` are recognized,
    so a value such as `shell` reads as "not a serving process" exactly as an
    absent one does.

    The value is stripped and lowercased before it is matched, and the
    normalized name is what comes back -- the same normalization `is_local()`
    applies, so `COMPONENT_PROCESS` and `COMPONENT_RUNTIME` cannot disagree
    about whether ` Web ` and `web` are the same declaration.

    Returns:
        The normalized process type when it names a serving process, otherwise
        None.
    """
    declared = os.environ.get(PROCESS_ENV_VAR, "").strip().lower()
    return declared if declared in SERVING_PROCESSES else None


def is_serving_process() -> bool:
    """Report whether this process declares itself a serving process.

    Returns:
        True when `COMPONENT_PROCESS` names one of `SERVING_PROCESSES`.
    """
    return component_process() is not None
