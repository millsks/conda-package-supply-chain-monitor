# Technology Stack

The frameworks and libraries this accelerator is built on, and what each one is
there to do. Only the load-bearing choices are listed — the full, authoritative
set with exact version constraints is `pixi.toml`.

Two facts frame everything below:

- **`pixi.toml` is the single source of truth for versions.** `pyproject.toml`
  declares no runtime dependencies; it carries build metadata and tool
  configuration only.
- **Every third-party package comes from conda-forge.** There are no
  `[pypi-dependencies]` exceptions — the one PyPI entry is this project's own
  editable install.

---

## Core runtime

| Package | Constraint | Role |
| --- | --- | --- |
| Django | `>=5.2,<5.3` | Web framework. The 5.2 LTS series, supported to April 2028. The cap is the next *minor*, not the next major: 5.3 is a feature release like 6.0, so `>=5.2,<6` would admit it — which is the thing the pin exists to prevent. |
| Python | `3.14.*` | Floor and ceiling both. `requires-python = "==3.14.*"` and the pixi pin agree; there is no older runtime to stay compatible with, and no CI version matrix. |
| djangorestframework | `>=3.17,<4` | API layer, routed from `src/config/api_router.py`. |
| drf-spectacular | `>=0.30,<0.31` | OpenAPI 3 schema generation for the DRF surface. |
| celery | `>=5.6,<6` | Async task execution. App defined in `src/config/celery_app.py`. |
| django-celery-beat | `>=2.9,<3` | Database-backed periodic task scheduling. Pulls `python-crontab` (schedule parsing) and `cron-descriptor` (pinned `<2` by the package itself). |
| psycopg | `>=3.2.4,<3.2.11` | PostgreSQL driver, psycopg 3. |
| libpq | `>=17,<18` | Client library, held at 17 to match the `postgres:17` server the CI gate runs against. It is what constrains the `psycopg` pin. |
| redis-py | `>=8.1,<9` | Redis client. |
| hiredis | `>=3.4,<4` | C parser that speeds up the Redis client. |
| django-redis | `>=7.0,<8` | Django cache backend over Redis. |
| uvicorn | `>=0.52,<0.53` | ASGI server. `uvicorn-standard` adds the optional extras. |
| gunicorn | `>=26.0,<27` | Process manager for production serving. Declared per-platform (`linux-64`, `osx-arm64`) — it has no Windows build. |
| uvicorn-worker | `>=0.4,<0.5` | The gunicorn worker class that runs uvicorn. Same per-platform declaration. |
| whitenoise | `>=6.12,<7` | Static file serving from the application process, no separate web server needed. |

## Authentication and security

| Package | Constraint | Role |
| --- | --- | --- |
| django-allauth | `>=65.19,<66` | Account and social account handling. `allauth.account`, `allauth.socialaccount`, and the `openid_connect` provider are all installed. |
| pyjwt | `>=2.13,<3` | JWT decoding and verification. |
| cryptography | `>=50.0,<51` | Signature verification behind PyJWT; backs the JWKS handling in `src/config/authorization/`. |
| django-cors-headers | `>=4.9,<5` | Cross-origin request policy. |
| requests | `>=2.34,<3` | HTTP client, including JWKS retrieval. |

The authorization logic lives in `src/config/authorization/` — claims contract,
JWKS cache, DRF authentication class, and the group/role mapper.

## Observability

| Package | Constraint | Role |
| --- | --- | --- |
| structlog | `>=26.1,<27` | Structured logging. Configured in `src/config/observability/logging.py`. |
| django-structlog | `>=10.1,<11` | Request-scoped binding of Django context into structlog events. |
| opentelemetry-api / -sdk | `>=1.44,<2` | Tracing and metrics API and implementation. |
| opentelemetry-exporter-otlp-proto-http | `>=1.44,<2` | OTLP/HTTP export to a collector. |
| opentelemetry-instrumentation-* | `>=0.65b0` | Auto-instrumentation for Django, ASGI, Celery, psycopg, and Redis. |

## Configuration and presentation

| Package | Constraint | Role |
| --- | --- | --- |
| django-environ | `>=0.14,<0.15` | Environment-driven settings — the mechanism behind the 15-factor config story. |
| django-crispy-forms | `>=2.6,<3` | Form rendering. conda-forge tops out at 2.6 while PyPI has 2.7; conda-forge wins. |
| crispy-bootstrap5 | `>=2026.3,<2027` | Bootstrap 5 template pack for crispy-forms. |
| django-anymail | `>=15.1,<16` | Provider-agnostic transactional email. |
| django-timezone-field | `>=7.2,<8` | Timezone model field, required by django-celery-beat. |

**Front end:** Bootstrap 5.2.3, loaded from a CDN in `base.html`. There is no
`package.json` and no Node build step — project CSS and JS are two hand-written
files under `src/django_service/static/`.

---

## Build and packaging

| Package | Constraint | Role |
| --- | --- | --- |
| Pixi | `>=0.70.2` | Package manager and task runner. The only supported way to run anything in this repository. |
| hatchling | `>=1.27,<2` | Build backend. |
| hatch-vcs | `>=0.5,<1` | Derives the package version from git tags. |
| python-build | `>=1.3,<2` | Builds the wheel and sdist via `pixi run build`. |

`[tool.hatch.build.targets.wheel]` in `pyproject.toml` is the one import-root
declaration site in the repository: `sources = ["src"]` remaps the directory so
`config` and `django_service` land at the wheel root, and the editable install
is what puts them on `sys.path` — under pytest exactly as under gunicorn.

## Testing

| Package | Constraint | Role |
| --- | --- | --- |
| pytest | `>=9.1,<10` | Test runner. |
| pytest-django | `>=4.13,<5` | Django integration. `django_find_project = false` — it is not allowed to declare an import root on the project's behalf. |
| pytest-cov | `>=7.0,<8` | Coverage integration; the gate fails under 90%. |
| coverage | `>=7.15,<8` | Measurement engine. |
| django_coverage_plugin | `>=3.2,<4` | Extends coverage to Django templates. Needs `COVERAGE_CORE=ctrace` and template debug mode, both set. |
| factory_boy | `>=3.3,<4` | Test data factories. |
| pytest-sugar | `>=1.1,<2` | Progress output. |

Tests split into `tests/unit/` (fast, no I/O) and `tests/integration/`, the
latter marked with `@pytest.mark.integration`.

## Static analysis and quality

| Package | Constraint | Role |
| --- | --- | --- |
| mypy | `>=2.3,<3` | Type checking, `strict = true` as a gate condition rather than an advisory. |
| django-stubs / django-stubs-ext | `>=5.2,<5.3` | Django type stubs and the mypy plugin. |
| djangorestframework-stubs | `>=3.16.9,<3.17` | DRF type stubs and plugin. |
| ruff | `>=0.16,<0.17` | Linting and formatting. Broad rule selection (40+ groups), line length 120 with `E501` enforced rather than ignored. |
| djlint | `>=1.43,<2` | Django template linting and formatting. |
| django-upgrade | `>=1.31,<2` | Rewrites deprecated Django idioms. |
| pre-commit | `>=4.6,<5` | Hook runner; `pre-commit-hooks` supplies the file-hygiene checks. |
| conventional-commit-hook | `>=0.1,<1` | Validates commit messages at the `commit-msg` stage. |
| git-cliff | any | Generates `CHANGELOG.md` from conventional commits. |

**SonarCloud** runs as a separate merge-blocking gate, configured in
`sonar-project.properties`. It maintains its own coverage exclusion list, which
is deliberately *not* reconciled entry-for-entry with the pytest-cov one.

## Documentation and local development

| Package | Constraint | Role |
| --- | --- | --- |
| mkdocs | `>=1.6,<2` | Documentation site. Built with `--strict`, so a page missing from `nav:` fails the build. |
| mkdocs-material | `>=9.7,<10` | Theme. |
| django-debug-toolbar | `>=7.0,<8` | Request introspection. Dev environment only. |
| django-extensions | `>=4.1,<5` | Management command extras. Dev environment only. |
| werkzeug + watchdog | `>=3.1,<4` | Enhanced dev server with reloading. Dev environment only. |
| watchfiles | `>=1.2,<2` | Reload watcher for `uvicorn --reload`. |
| ipdb | `>=0.13,<0.14` | Debugger. |

---

## Environments

Three pixi environments, all in one solve group:

- **`default`** — runtime only. What a deployed component gets.
- **`dev`** — `default` plus the `dev` and `gate` features. What the CI gate and
  local development use.
- **`spike-storage`** — `dev` plus `django-storages >=1.14.6,<2`, isolated for
  the R-1 fitness spike. It is *not* part of the runtime set, and its tests
  never run in the gate.

## Continuous integration

GitHub Actions, with a `postgres:17` service container on the Linux gate job.
`prefix-dev/setup-pixi` provisions the environment; `pixi run ci` is the single
entry point, chaining pre-commit, build, typecheck, lint, and the coverage
floor. Additional workflows cover releases, SonarQube analysis, PR labelling,
and stale issue triage.
