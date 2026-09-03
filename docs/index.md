# Django 15-Factor Base

A Django application accelerator template built on 15-factor application principles.

## Layout

```text
manage.py
pixi.toml            # dependencies (conda-forge) and tasks
pyproject.toml       # build metadata and tool configuration
src/                 # import root -- declared in pyproject.toml, not a package
  config/            # settings, urls, wsgi/asgi, celery
  django_service/    # the application package
    users/           # the users app
    templates/
    static/
tests/
  unit/              # no database, no network, no filesystem
  integration/       # marked `integration`, exercises real resources
docs/                # this documentation (mkdocs)
```

`src/` is deliberately **not** a package, so `config` and `django_service`
import as top-level packages. The import root is declared in exactly one place:
`[tool.hatch.build.targets.wheel]` in `pyproject.toml` remaps `src/` onto the
wheel root, and the editable install generated from it is what puts the root on
`sys.path` at runtime. Nothing else declares it — no `sys.path` insert in
`manage.py`, `asgi.py` or `wsgi.py`, no `--app-dir` in any pixi task, and no
`pythonpath` in the pytest configuration.

## Quick start

```sh
pixi install
pixi run migrate
pixi run runserver
```

The application boots against sqlite by default. See
[Development](development.md) for the database configuration and the full task
list.
