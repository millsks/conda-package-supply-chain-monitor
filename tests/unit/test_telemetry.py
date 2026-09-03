"""Tests for the OpenTelemetry setup.

The exporter-selection logic is tested directly because it is what keeps a
missing collector from flooding stderr with retries. `configure_telemetry` is
tested with the instrumentors and the global provider patched out -- calling
them for real would instrument Django, Celery, psycopg and redis for the whole
test session.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from config.observability import telemetry
from config.observability.telemetry import CONSOLE
from config.observability.telemetry import NONE
from config.observability.telemetry import OTLP
from config.observability.telemetry import build_resource
from config.observability.telemetry import configure_telemetry
from config.observability.telemetry import has_span_processor
from config.observability.telemetry import reset_telemetry_for_testing
from config.observability.telemetry import resolve_traces_exporter

SCRUBBED_VARS = (
    "OTEL_SDK_DISABLED",
    "OTEL_TRACES_EXPORTER",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_SERVICE_NAME",
    # `Resource.create` merges `OTELResourceDetector`, which reads this one, so
    # an ambient value would reach `build_resource`'s output.
    "OTEL_RESOURCE_ATTRIBUTES",
    # Not read here, but a sampler inherited from the shell changes what the
    # integration suite records; scrubbed for the same hermeticity reason.
    "OTEL_TRACES_SAMPLER",
    "COMPONENT_RUNTIME",
)

INSTRUMENTED_NAMES = ["Celery", "Django", "Psycopg", "Redis"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    """Start every test from an unconfigured, unset state.

    `COMPONENT_RUNTIME` is scrubbed along with the `OTEL_*` variables: the dev
    pixi environment exports it, and a test that reads it from the ambient
    environment would assert a different answer under `pixi run` than in a
    hermetic one.
    """
    for name in SCRUBBED_VARS:
        monkeypatch.delenv(name, raising=False)
    reset_telemetry_for_testing()
    yield
    reset_telemetry_for_testing()


@pytest.fixture
def installed_provider(monkeypatch: pytest.MonkeyPatch) -> list[TracerProvider]:
    """Capture the provider `configure_telemetry` hands to the global setter.

    The real `set_tracer_provider` installs process-wide and refuses to be
    overridden, so it is patched out -- but the provider it was handed is what
    the processor assertions inspect, so it is kept rather than dropped.
    """
    captured: list[TracerProvider] = []
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", captured.append)
    return captured


@pytest.fixture
def no_side_effects(monkeypatch: pytest.MonkeyPatch, installed_provider: list[TracerProvider]):
    """Patch out instrumentation and the global provider."""
    installed: list[str] = []
    for name in ("Django", "Celery", "Psycopg", "Redis"):
        monkeypatch.setattr(
            telemetry,
            f"{name}Instrumentor",
            lambda name=name: type(
                "Stub",
                (),
                {"instrument": lambda self: installed.append(name)},
            )(),
        )
    return installed


class TestResolveTracesExporter:
    def test_none_when_no_endpoint_is_configured(self):
        """The default path: no collector, so nothing is exported."""
        assert resolve_traces_exporter() == NONE

    def test_otlp_when_endpoint_is_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        assert resolve_traces_exporter() == OTLP

    def test_otlp_when_only_the_traces_endpoint_is_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "http://collector:4318/v1/traces",
        )
        assert resolve_traces_exporter() == OTLP

    @pytest.mark.parametrize("value", [CONSOLE, NONE, OTLP])
    def test_explicit_choice_is_honoured(
        self,
        monkeypatch: pytest.MonkeyPatch,
        value: str,
    ):
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", value.upper())
        assert resolve_traces_exporter() == value

    def test_unknown_value_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", "carrier-pigeon")
        assert resolve_traces_exporter() == NONE


class TestBuildResource:
    def test_default_service_name(self):
        """Locality is undeclared here, so the hermetic answer is `deployed`."""
        attributes = build_resource().attributes
        assert attributes["service.name"] == telemetry.DEFAULT_SERVICE_NAME
        assert attributes["deployment.environment"] == "deployed"

    def test_deployment_environment_follows_locality(self, monkeypatch: pytest.MonkeyPatch):
        """AD-13: `COMPONENT_RUNTIME` decides, and `DJANGO_ENV` no longer can."""
        monkeypatch.setenv("OTEL_SERVICE_NAME", "checkout")
        monkeypatch.setenv("COMPONENT_RUNTIME", "local")
        attributes = build_resource("1.2.3").attributes
        assert attributes["service.name"] == "checkout"
        assert attributes["deployment.environment"] == "local"
        assert attributes["service.version"] == "1.2.3"

        monkeypatch.delenv("COMPONENT_RUNTIME")
        assert build_resource().attributes["deployment.environment"] == "deployed"

        monkeypatch.setenv("DJANGO_ENV", "production")
        assert build_resource().attributes["deployment.environment"] == "deployed"

    def test_version_is_omitted_when_unknown(self):
        assert "service.version" not in build_resource().attributes


class TestConfigureTelemetry:
    def test_disabled_by_the_standard_kill_switch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
        assert configure_telemetry() is False

    def test_is_idempotent(self, no_side_effects: list[str]):
        """Every process entrypoint calls it; repeat calls must be no-ops."""
        assert configure_telemetry() is True
        assert configure_telemetry() is False
        assert sorted(no_side_effects) == ["Celery", "Django", "Psycopg", "Redis"]

    def test_instruments_even_without_an_exporter(self, no_side_effects: list[str]):
        """Spans still get created, so trace ids still reach the logs."""
        assert configure_telemetry() is True
        assert "Django" in no_side_effects

    def test_provider_is_installed_with_no_endpoint_configured(
        self,
        no_side_effects: list[str],
        installed_provider: list[TracerProvider],
    ):
        """Nothing configured is the local default, and it still installs.

        The resource is asserted on the installed provider rather than by
        calling `build_resource` again: the provider is the only path by which
        those attributes leave the process, and a provider built without one
        would satisfy every assertion that re-derives them.
        """
        assert configure_telemetry() is True
        assert len(installed_provider) == 1
        assert isinstance(installed_provider[0], TracerProvider)

        attributes = installed_provider[0].resource.attributes
        assert attributes["service.name"] == telemetry.DEFAULT_SERVICE_NAME
        assert attributes["deployment.environment"] == "deployed"

    def test_all_instrumentors_instrument_with_no_endpoint_configured(
        self,
        no_side_effects: list[str],
    ):
        """Instrumentation is never conditional on export."""
        assert configure_telemetry() is True
        assert sorted(no_side_effects) == INSTRUMENTED_NAMES

    def test_no_processor_is_attached_when_nothing_is_configured(
        self,
        no_side_effects: list[str],
        installed_provider: list[TracerProvider],
    ):
        """The whole point: no collector means no retrying exporter."""
        assert configure_telemetry() is True
        assert has_span_processor(installed_provider[0]) is False

    def test_unreachable_endpoint_is_not_a_configuration_this_code_produces(
        self,
        no_side_effects: list[str],
        installed_provider: list[TracerProvider],
    ):
        """With no endpoint to point at, the OTLP branch is never taken.

        `resolve_traces_exporter` answering `none` is only half of it; the
        other half is that `configure_telemetry` then builds a provider with no
        `BatchSpanProcessor` on it, which is what an unreachable endpoint would
        retry against.
        """
        assert resolve_traces_exporter() == NONE
        assert configure_telemetry() is True

        processors = installed_provider[0]._active_span_processor._span_processors  # noqa: SLF001 - no public accessor
        assert [processor for processor in processors if isinstance(processor, BatchSpanProcessor)] == []

    def test_console_exporter_attaches_a_simple_processor(
        self,
        monkeypatch: pytest.MonkeyPatch,
        no_side_effects: list[str],
        installed_provider: list[TracerProvider],
    ):
        """`OTEL_TRACES_EXPORTER=console` changes export and nothing else."""
        unset_resource = build_resource()

        monkeypatch.setenv("OTEL_TRACES_EXPORTER", CONSOLE)
        assert configure_telemetry() is True

        provider = installed_provider[0]
        assert has_span_processor(provider) is True
        processors = provider._active_span_processor._span_processors  # noqa: SLF001 - no public accessor exists
        assert len(processors) == 1
        assert isinstance(processors[0], SimpleSpanProcessor)
        assert isinstance(processors[0].span_exporter, ConsoleSpanExporter)

        assert sorted(no_side_effects) == INSTRUMENTED_NAMES
        assert provider.resource == unset_resource
