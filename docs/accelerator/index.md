# The platform

Conda-Sentinel is built on a Django service platform — an accelerator that supplies
the parts every component needs and none of the parts that make this one Conda-Sentinel:
settings and the two-stage startup gate, OIDC authentication with group-claim sync,
structured logging and tracing, health and drain probes, Celery, and the
`component.toml` deployment contract.

**Everything in this section is the platform's, not the product's.** If you are asking
how package health is decided, which evidence a verdict rests on, or what `unknown`
means on a screen, you want [Conda-Sentinel](../conda-sentinel/index.md) instead.

## Where to start

| If you are… | Read |
|---|---|
| setting up to work on the code | [Developing on the platform](development.md) |
| deploying a component | [Deploying a component](deployment.md) |
| wiring up an identity provider | [Authentication](authentication.md) |
| looking for logs, traces or metrics | [Observability](observability.md) |
| wondering why a dependency is here | [Technology stack](technology-stack.md) |

## Two import roots

The one structural fact worth knowing before reading anything else. `src/` and
`src/django_apps/` are both import roots and **neither is a package** — no
`__init__.py`, and neither ever appears in an import statement. So `config`,
`django_service` and `conda_sentinel` all import as top-level names.

Both come out of a single table, `[tool.hatch.build.targets.wheel]` in
`pyproject.toml`. Nothing else declares them: no `sys.path` insert, no `--app-dir`, no
`pythonpath` in the pytest configuration. See
[Technology stack](technology-stack.md#build-and-packaging) for the mechanism.

```text
src/
  config/            # settings, urls, wsgi/asgi, celery — the platform's wiring
  django_service/    # the platform application: users, templates, static
  django_apps/       # the second import root
    conda_sentinel/  # this product's domains live here
```
