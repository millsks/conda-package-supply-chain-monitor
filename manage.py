#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

    try:
        from django.core.management import execute_from_command_line  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(  # noqa: TRY003
            "Couldn't import Django. Are you sure it's installed and "  # noqa: EM101
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?",
        ) from exc

    # Management commands are instrumented too, so a data migration or backfill
    # shows up as a trace like any request would.
    #
    # Guarded because this file no longer puts src/ on sys.path itself (AD-7):
    # the editable install is the one import-root declaration, so a clone that
    # has not been installed fails here, and it should say why rather than
    # raising a bare ModuleNotFoundError.
    try:
        from config.observability import configure_observability  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(  # noqa: TRY003
            "Couldn't import the `config` package. src/ is placed on the import "  # noqa: EM101
            "path by this project's editable install and by nothing else "
            "(pyproject.toml [tool.hatch.build.targets.wheel] sources). Run "
            "`pixi install` and invoke this through `pixi run manage`.",
        ) from exc

    configure_observability()

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
