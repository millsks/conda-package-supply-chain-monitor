"""OpenTelemetry tracing setup.

Configuration comes from the standard `OTEL_*` environment variables rather
than project-specific settings, so anything that already knows OpenTelemetry
knows how to configure this application.

Tracing is always wired in; only *export* is conditional. Registering a
`BatchSpanProcessor` whose collector is unreachable makes the exporter retry on
every cycle and flood stderr, which would happen on every test run and every
`runserver`. So the OTLP processor is attached only when an endpoint is
configured. Instrumentation stays active either way, so `trace_id` still
reaches the logs with no collector present.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from config.locality import is_local

DEFAULT_SERVICE_NAME = "conda-package-supply-chain-monitor"

OTLP = "otlp"
CONSOLE = "console"
NONE = "none"

#: The SDK's own kill switch, named once. It is spelled here rather than at each
#: reader because two consumers now act on it -- the skip below, and Epic 4's
#: stage-1 refusal -- and a refusal message naming a variable this module spells
#: differently would send an operator to a variable that does nothing (AD-1).
OTEL_SDK_DISABLED_ENV_VAR = "OTEL_SDK_DISABLED"

#: The values this component reads as *disabled*. Wider than the literal `"true"`
#: the specification names, and deliberately so: an operator who writes `1` or
#: `yes` has expressed the same intent, and the reader below is what decides
#: whether tracing is actually installed. `"0"` and `"false"` are not here.
_DISABLED_VALUES = frozenset({"true", "1", "yes"})

_configured = False


def otel_sdk_is_disabled() -> bool:
    """Report whether this component has opted out of the OpenTelemetry SDK.

    Public rather than private because it now has two consumers, and they must
    not disagree. `configure_telemetry` below reads it to decide whether to
    install tracing at all; `config.startup.stage_one` reads the *same*
    function for refusal condition 3, which refuses a deployed component that
    has silently opted out of an immovable guarantee (FR-13).

    That shared reading is the whole point. If the refusal recognized only
    `"true"` while this reader also recognized `"1"` and `"yes"`, then
    `OTEL_SDK_DISABLED=1` would disable tracing in a deployed component with
    nothing refusing it -- the exact hole the refusal exists to close. One
    reader, one answer, and this module is the one that owns it because it is
    the module whose behaviour the variable actually changes.

    Returns:
        True when `OTEL_SDK_DISABLED`, stripped and lower-cased, is one of
        `true`, `1` or `yes`. `0` and `false` are not disabled, and neither is
        an unset variable.

    """
    return os.environ.get(OTEL_SDK_DISABLED_ENV_VAR, "").strip().lower() in _DISABLED_VALUES


def _has_otlp_endpoint() -> bool:
    """Report whether an OTLP endpoint is configured.

    Returns:
        True when either the general or traces-specific endpoint is set.

    """
    return bool(
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"),
    )


def build_resource(service_version: str | None = None) -> Resource:
    """Describe this service to the tracing backend.

    `deployment.environment` follows `config.locality.is_local()` (AD-13) rather
    than a `DJANGO_ENV` read. That variable defaulted to `local`, so a deployed
    component that never set it reported itself local -- the fail-open inversion
    AD-13 exists to prevent. The trade is granularity: locality is boolean, so
    every deployed tier now reports `deployed` rather than `staging` or
    `production`.

    Args:
        service_version: Version to report, normally the package version.

    Returns:
        A `Resource` carrying service name, version and deployment environment.

    """
    attributes: dict[str, str] = {
        "service.name": os.environ.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE_NAME,
        "deployment.environment": "local" if is_local() else "deployed",
    }
    if service_version:
        attributes["service.version"] = service_version
    return Resource.create(attributes)


def resolve_traces_exporter() -> str:
    """Decide how spans should leave the process.

    Honours `OTEL_TRACES_EXPORTER`. The default is OTLP, but only when an
    endpoint is actually configured -- otherwise the exporter would retry
    against nothing on every export cycle.

    Returns:
        One of `otlp`, `console` or `none`.

    """
    configured = os.environ.get("OTEL_TRACES_EXPORTER", "").strip().lower()
    if configured in {CONSOLE, NONE, OTLP}:
        return configured
    return OTLP if _has_otlp_endpoint() else NONE


def has_span_processor(provider: TracerProvider) -> bool:
    """Report whether any span processor is attached to `provider`.

    The SDK exposes no public accessor for the processors a provider carries,
    so this reaches into `_active_span_processor` -- the same private reach
    `tests/integration/test_asgi_request_path.py` takes, and for the same
    reason. It exists so that "no processor is attached" can be asserted over
    the built object rather than by re-deriving the environment logic a second
    time, which would prove nothing.

    Args:
        provider: The tracer provider to inspect.

    Returns:
        True when the provider has at least one span processor attached.

    """
    active = getattr(provider, "_active_span_processor", None)
    if active is None:
        # `trace.get_tracer_provider()` answers with a proxy before
        # `configure_telemetry` runs and with a no-op one when the kill switch
        # is set. Neither carries processors, which is the honest answer here.
        return False
    return bool(active._span_processors)  # noqa: SLF001 - no public accessor exists


def configure_telemetry(service_version: str | None = None) -> bool:
    """Install the tracer provider and instrument the stack.

    Safe to call from every process entrypoint; repeat calls are no-ops, which
    matters because wsgi/asgi/celery/manage may each invoke it.

    Args:
        service_version: Version to report on the resource.

    Returns:
        True when telemetry was configured by this call, False when it was
        skipped -- already configured, or disabled via `OTEL_SDK_DISABLED`.

    """
    global _configured  # noqa: PLW0603 - process-wide, deliberately idempotent
    if _configured or otel_sdk_is_disabled():
        return False

    provider = TracerProvider(resource=build_resource(service_version))

    exporter = resolve_traces_exporter()
    if exporter == OTLP:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    elif exporter == CONSOLE:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    # `none` attaches nothing at all, and that absence *is* how spans are
    # discarded: they are still created, they still end, and their
    # `SpanContext` is live for the whole span -- which is what keeps
    # `trace_id` and `span_id` on every log line the request emits. Only the
    # terminal export step is missing. Discarding by attaching a processor
    # pointed at an endpoint that is not there would instead retry on every
    # export cycle and flood stderr. Asserted by
    # `has_span_processor` in `tests/unit/test_telemetry.py`.

    trace.set_tracer_provider(provider)

    # Instrumentation is installed even when nothing is exported, so spans are
    # still created and their ids still reach the logs.
    #
    # `CeleryInstrumentor` alone carries a `# type: ignore[no-untyped-call]`:
    # opentelemetry-instrumentation ships `py.typed`, but CeleryInstrumentor
    # overrides `__init__` without annotating it, so the constructor is an
    # untyped def inside a package that claims to be typed. The other three
    # instrumentors inherit `BaseInstrumentor.__new__` and are unaffected.
    # `warn_unused_ignores` removes the marker when upstream annotates it.
    DjangoInstrumentor().instrument()
    CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
    PsycopgInstrumentor().instrument()
    RedisInstrumentor().instrument()

    _configured = True
    return True


def reset_telemetry_for_testing() -> None:
    """Clear the idempotence guard so a test can configure again."""
    global _configured  # noqa: PLW0603 - test helper
    _configured = False
