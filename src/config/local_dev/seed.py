"""The runnable entry point: `python -m config.local_dev.seed`.

Invoked as `pixi run -e dev seed-personas`. The `-e dev` is not optional and it
is not a convenience: locality is declared once, in `[feature.dev.activation.env]`
(AD-13 as amended), so the `dev` environment is what carries
`COMPONENT_RUNTIME=local`. A bare `pixi run seed-personas` resolves in `default`,
which declares nothing, reads *deployed*, and is refused by `seed_personas`
before it touches the database. That is the refusal working, not a bug.

**Not a management command, deliberately.** A management command has to live
inside an installed app; the only installed app package is `django_service`, and
`django_service` importing `config.local_dev` would invert AD-4's dependency
direction. A `python -m` entry point keeps the arrow pointing `config ->
django_service`.

The seeding import is inside `main` on purpose: `config.local_dev.seeding`
reaches the mapper, which imports a model, and a model import before
`django.setup()` is `AppRegistryNotReady`.
"""

from __future__ import annotations

import os

import django
import structlog

__all__ = ["main"]

# Named rather than taken from `__name__`: run as `python -m`, this module's
# `__name__` is `__main__`, and a log aggregator would file the one event that
# says seeding finished under a name that identifies nothing.
logger: structlog.stdlib.BoundLogger = structlog.get_logger("config.local_dev.seed")


def main() -> list[str]:
    """Set up Django, seed the declared personas, and record what was materialized.

    Returns:
        The keys of the personas materialized.

    Raises:
        ImproperlyConfigured: The run is not local. Propagated rather than
            rendered as a message and a non-zero exit: the traceback names the
            refusal and the variable, and a `SystemExit` here would make the task
            indistinguishable from a task that failed for any other reason.

    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    django.setup()

    from config.local_dev.seeding import seed_personas  # noqa: PLC0415 - after django.setup(), see the module docstring

    seeded = seed_personas()
    logger.info("local_dev.seeding_complete", personas=tuple(seeded))
    return seeded


if __name__ == "__main__":
    main()
