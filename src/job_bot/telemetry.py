from __future__ import annotations

from importlib import import_module

import structlog
from fastapi import FastAPI

from job_bot.config import setting_value, settings

OTEL_EXPORTER_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
OTEL_TRACES_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
OTEL_METRICS_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"
OTEL_SDK_DISABLED_ENV = "OTEL_SDK_DISABLED"
OTEL_SERVICE_NAME_ENV = "OTEL_SERVICE_NAME"
OTEL_TRACES_EXPORTER_ENV = "OTEL_TRACES_EXPORTER"
OTEL_METRICS_EXPORTER_ENV = "OTEL_METRICS_EXPORTER"
APP_ENV_ENV = "APP_ENV"

logger = structlog.get_logger(__name__)
_configured = False


def configure_telemetry(app: FastAPI) -> bool:
    """Configure OTLP tracing and metrics when an exporter endpoint is present."""
    global _configured  # pylint: disable=global-statement

    if _configured or _sdk_disabled():
        return False

    cfg = settings()
    common_endpoint = cfg.OTEL_EXPORTER_OTLP_ENDPOINT
    traces_enabled = bool(
        common_endpoint or cfg.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
    ) and not _is_none(OTEL_TRACES_EXPORTER_ENV)
    metrics_endpoint = common_endpoint or cfg.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT
    metrics_enabled = bool(metrics_endpoint) and not _is_none(OTEL_METRICS_EXPORTER_ENV)
    if not traces_enabled and not metrics_enabled:
        return False

    # Exporters and instrumentors are expensive imports, so load them only after
    # configuration proves that telemetry is enabled for this process.
    resource_class = import_module("opentelemetry.sdk.resources").Resource
    resource = resource_class.create(
        {
            "service.name": cfg.OTEL_SERVICE_NAME,
            "service.version": "0.1.0",
            "deployment.environment.name": cfg.APP_ENV,
        }
    )

    if traces_enabled:
        tracer_provider_class = import_module("opentelemetry.sdk.trace").TracerProvider
        batch_processor_class = import_module("opentelemetry.sdk.trace.export").BatchSpanProcessor
        span_exporter_class = import_module(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter"
        ).OTLPSpanExporter
        tracer_provider = tracer_provider_class(resource=resource)
        tracer_provider.add_span_processor(batch_processor_class(span_exporter_class()))
        import_module("opentelemetry.trace").set_tracer_provider(tracer_provider)

    if metrics_enabled:
        meter_provider_class = import_module("opentelemetry.sdk.metrics").MeterProvider
        metric_reader_class = import_module(
            "opentelemetry.sdk.metrics.export"
        ).PeriodicExportingMetricReader
        metric_exporter_class = import_module(
            "opentelemetry.exporter.otlp.proto.http.metric_exporter"
        ).OTLPMetricExporter
        metric_reader = metric_reader_class(metric_exporter_class())
        import_module("opentelemetry.metrics").set_meter_provider(
            meter_provider_class(resource=resource, metric_readers=[metric_reader])
        )

    import_module("opentelemetry.instrumentation.fastapi").FastAPIInstrumentor.instrument_app(app)
    import_module("opentelemetry.instrumentation.httpx").HTTPXClientInstrumentor().instrument()
    import_module("opentelemetry.instrumentation.sqlalchemy").SQLAlchemyInstrumentor().instrument()
    _configured = True
    logger.info(
        "opentelemetry_configured",
        traces_enabled=traces_enabled,
        metrics_enabled=metrics_enabled,
        service_name=cfg.OTEL_SERVICE_NAME,
    )
    return True


def _sdk_disabled() -> bool:
    value = settings().OTEL_SDK_DISABLED or ""
    return value.strip().lower() in {"true", "1", "yes"}


def _is_none(environment_variable: str) -> bool:
    value = setting_value(environment_variable) or "otlp"
    return value.strip().lower() == "none"
