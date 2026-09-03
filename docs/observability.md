# Observability

Logging and tracing are permanent parts of this template, not an optional
add-on. Every process — web, ASGI, Celery worker, management command — emits
structured logs through **structlog** and creates **OpenTelemetry** spans.

## What a log line looks like

```json
{
  "event": "request_started",
  "request": "GET /",
  "request_id": "779e9522-1615-4425-baa1-a6f8ac9f1495",
  "user_id": null,
  "ip": "127.0.0.1",
  "level": "info",
  "logger": "django_structlog.middlewares.request",
  "timestamp": "2026-08-08T21:37:00.576800Z",
  "trace_id": "3293968340d1e265f91e2e43e120bba8",
  "span_id": "eb80a5eaf6eba477"
}
```

Three identifiers do the work:

- **`request_id`** ties every line from one request together, and follows the
  request into any Celery task it enqueues.
- **`trace_id`** opens the corresponding trace in your tracing backend.
- **`user_id`** is populated because `RequestMiddleware` is ordered *after*
  `AuthenticationMiddleware`.

Django, allauth and Celery log through the standard library, not structlog.
They are routed through `structlog.stdlib.ProcessorFormatter` with the same
`foreign_pre_chain`, so their output is structured and carries the same
timestamp, level and trace context. There is no second log format to parse.

## Configuration

All standard OpenTelemetry variables apply. The ones that matter most:

| Variable | Default | Effect |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Where spans are sent. Unset means spans are created but not exported. |
| `OTEL_TRACES_EXPORTER` | `otlp` when an endpoint is set, else `none` | `otlp`, `console` or `none`. |
| `OTEL_SERVICE_NAME` | `conda-package-supply-chain-monitor` | `service.name` on the resource. |
| `OTEL_SDK_DISABLED` | `false` | Turns tracing off entirely, per the OTel spec. |
| `COMPONENT_RUNTIME` | unset — the `dev` pixi environment sets `local`, so every `pixi run` path is local | Reported as `deployment.environment`, which takes exactly two values: `local` when this variable is `local` (after stripping and lowercasing), and `deployed` otherwise. This attribute previously mirrored `DJANGO_ENV` and could carry a tier name such as `staging`; a dashboard or alert keyed on those values needs updating. |
| `DJANGO_LOG_LEVEL` | `INFO` | Root log level. |
| `DJANGO_LOG_FORMAT` | `console` under DEBUG, else `json` | `json` or `console`. |

### Why export is conditional

A `BatchSpanProcessor` whose collector is unreachable retries on every export
cycle and floods stderr — in every test run and every `runserver`. So the OTLP
processor is attached **only** when an endpoint is configured:

| Condition | SDK + instrumentation | Span export | `trace_id` in logs |
| --- | --- | --- | --- |
| Endpoint set | on | OTLP | yes |
| Endpoint unset | on | dropped | yes |
| `OTEL_TRACES_EXPORTER=console` | on | stdout | yes |
| `OTEL_SDK_DISABLED=true` | off | none | no |

Instrumentation is installed either way, which is why `trace_id` appears in the
sample above even with no collector running.

**Instrumentation is unconditional, not merely "not skipped".** The Django,
Celery, psycopg and redis instrumentors are installed on every run, in every
environment, with no `if DEBUG`, no locality check and no endpoint check in
front of them — `configure_telemetry` attaches a span processor conditionally
and then instruments unconditionally. Nothing about the export decision reaches
the instrumentors, so a local run exercises the same instrumentation code a
deployed one does. Spans are created and ended locally exactly as they are
deployed; with no processor attached they are simply discarded when they end,
and their `SpanContext` is live for the whole span, which is what keeps
`trace_id` and `span_id` on every log line a span is active for. The one
condition that turns instrumentation off is `OTEL_SDK_DISABLED`, and nothing in
this repository sets or defaults it.

Setting `OTEL_TRACES_EXPORTER=otlp` explicitly is the one way to attach a batch
processor without configuring an endpoint: the explicit choice is honoured, and
the exporter then falls back to the SDK's own default endpoint. That is a
deliberate opt-in, not a default anything reaches by accident — the *unset* case
resolves to `none`.

## Seeing it work

Spans to your terminal, no collector required:

```sh
OTEL_TRACES_EXPORTER=console pixi run runserver
curl localhost:8000/
```

JSON logs in development, which normally default to console rendering:

```sh
DJANGO_LOG_FORMAT=json pixi run runserver
```

Against a collector:

```sh
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_SERVICE_NAME=my-service
pixi run serve
```

## What is instrumented

`DjangoInstrumentor`, `CeleryInstrumentor`, `PsycopgInstrumentor` and
`RedisInstrumentor` — so a trace spans the request, the queries it ran, the
cache calls it made and any task it queued.

!!! warning "`opentelemetry-instrumentation-asgi` is not optional here"

    It is an *optional* import of the Django instrumentor, but this project
    needs it. Without it `_is_asgi_supported` is `False` and the middleware
    returns early for ASGI requests — **no span, and no warning**. Since
    `pixi run serve` and the production uvicorn worker are both ASGI, dropping
    the package would silently disable tracing in production while leaving
    `runserver` working.

    Three guards keep this from regressing, and they defend different things.
    `tests/unit/test_observability_init.py` asserts `_is_asgi_supported` is true
    — that the package is importable in *this* environment, whichever one the
    suite happens to be running in. `tests/unit/test_dependency_policy.py`
    asserts it is declared in `pixi.toml`'s unconditional `[dependencies]` table
    and in no `[feature.*]` or `[target.*]` table — that it is present in *every*
    combination rather than in the one that was tested. Neither implies the
    other: a package could be importable in `dev` and absent from a combination
    nobody ran the suite in, and a correct declaration could still fail to
    install.

    The third, `tests/integration/test_asgi_tracing.py`, asserts the behaviour
    the other two exist to protect: a request driven through `config.asgi.application` produces a
    `SERVER` span carrying the HTTP method and a real trace id, and the same
    request's log line names that trace.

## Configuration is read before Django starts

`configure_observability()` runs at entrypoint import — before Django loads its
settings. That is deliberate: the Django instrumentor inserts its middleware
into `MIDDLEWARE`, which has no effect once the middleware chain is built.

The consequence is that `OTEL_*` variables must be in the environment before
settings are read. `configure_observability()` therefore loads `.env` itself
when `DJANGO_READ_DOT_ENV_FILE` is set, rather than waiting for the settings
module to do it — otherwise `OTEL_*` entries in `.env` would be parsed too late
and appear to be ignored. Real environment variables still take precedence.

## Writing logs

Use structlog, never the standard library, and pass data as keyword arguments
rather than interpolating it into the message:

```python
import structlog

logger = structlog.get_logger(__name__)

logger.info("order_placed", order_id=order.pk, total=order.total)
```

`request_id`, `user_id` and `trace_id` are added for you.

## Layout

```
src/config/observability/
  __init__.py     configure_observability() -- called by each process entrypoint
  logging.py      processor chains and the LOGGING dictConfig factory
  telemetry.py    tracer provider, exporter selection, instrumentors
```

`configure_observability()` is called from `manage.py`, `wsgi.py`, `asgi.py`
and `celery_app.py`, and is idempotent. It is deliberately not called from an
`AppConfig.ready()` hook: that runs after Django has built its handler stack,
and can fire more than once.

structlog itself is configured from `config/settings/base.py`, because
`LOGGING` has to be built while settings are being read.

## Adding metrics or OTLP logs later

Both are additive and need no restructuring:

- **Metrics** — add a `MeterProvider` with a `PeriodicExportingMetricReader` in
  `configure_telemetry()`, plus `opentelemetry-exporter-otlp-proto-http`, which
  is already a dependency.
- **OTLP logs** — attach an OTel `LoggingHandler` in `build_logging_config()`
  alongside the console handler. Logs would then go to both stdout and the
  collector.

## Note on dependencies

Every dependency resolves from conda-forge, including `django-celery-beat`. It
used to be the one exception: the recipe dropped the environment marker on
upstream's `importlib-metadata<5.0; python_version < "3.8"` and applied the cap
unconditionally, which collided with `opentelemetry-api`'s
`importlib-metadata>=6.0` and made the two impossible to install together. Build
`2.9.0 pyhcf101f3_1` removed the cap, so the dependency moved into
`[dependencies]` in `pixi.toml` and the project now carries no supply-chain
exceptions at all.

The recipe's remaining constraint is a `django <6.1` cap, which will block a
Django 6.1 upgrade until it is relaxed. See [Supply chain](development.md#supply-chain)
for the policy the whole dependency set is held to.
