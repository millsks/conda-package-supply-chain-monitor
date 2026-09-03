# Django 15-Factor Base

A Django application accelerator template built on 15-factor application principles.

## Layout

```text
manage.py
pixi.toml            # dependencies (conda-forge) and tasks
pyproject.toml       # build metadata and tool configuration
src/                 # first import root -- declared in pyproject.toml, not a package
  config/            # settings, urls, wsgi/asgi, celery
  django_service/    # the platform application package
    users/           # the users app
    templates/
    static/
  django_apps/       # second import root -- also not a package, never imported
    conda_package_supply_chain_monitor/   # the domain applications live here
      core/          # the first one
tests/
  unit/              # no database, no network, no filesystem
  integration/       # marked `integration`, exercises real resources
docs/                # this documentation (mkdocs)
```

There are **two** import roots and **one** declaration of them. `src/` and
`src/django_apps/` are both deliberately not packages — neither has an
`__init__.py` and neither ever appears in an import statement — so `config`,
`django_service` and `conda_package_supply_chain_monitor` all import as
top-level packages.

Both roots come out of a single table,
`[tool.hatch.build.targets.wheel]` in `pyproject.toml`. Its `sources` mapping
names the three subtrees of `src/`: `config` and `django_service` keep their
names, and `src/django_apps` maps onto the wheel root, which is what makes it a
root of its own. The editable install generated from that table is what resolves
those three names at runtime — a redirecting finder rather than directories on
`sys.path`, which is why `django_apps` is not importable even in a working tree.
See [Technology stack](technology-stack.md#build-and-packaging) for the mechanism.
Nothing else declares them — no `sys.path` insert in `manage.py`, `asgi.py` or
`wsgi.py`, no `--app-dir` in any pixi task, and no `pythonpath` in the pytest
configuration.

Domain applications are subpackages of `conda_package_supply_chain_monitor`, so
they share one stable top-level name. Adding one is creating a directory —
neither `pyproject.toml` nor the ruff configuration needs an edit, and no
reinstall is required. *Adopting* it is two more lines, and they are separate
from making it importable: an entry in `component.toml`'s `adopted_apps` (the
declaration) and an entry appended to `LOCAL_APPS` in
`src/config/settings/base.py` (what installs it today, until Epic 9 composes the
first into the second). A brand-new *top-level* package under either root is the
one case that needs a `pixi install` before it resolves, because the finder's
map is fixed at install time.

## Quick start

```sh
pixi install
pixi run migrate
pixi run runserver
```

The application boots against sqlite by default. See
[Development](development.md) for the database configuration and the full task
list.
