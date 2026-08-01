from unittest.mock import Mock

from fastapi import FastAPI

from job_bot import telemetry


def test_configure_telemetry_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)
    monkeypatch.setattr(telemetry, "_configured", False)

    assert telemetry.configure_telemetry(FastAPI()) is False


def test_configure_telemetry_honors_sdk_disabled(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setattr(telemetry, "_configured", False)

    assert telemetry.configure_telemetry(FastAPI()) is False


def test_configure_telemetry_instruments_supported_libraries(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", Mock())
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", Mock())
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", Mock())
    monkeypatch.setattr(telemetry, "PeriodicExportingMetricReader", Mock())
    monkeypatch.setattr(telemetry, "TracerProvider", Mock())
    monkeypatch.setattr(telemetry, "MeterProvider", Mock())
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", Mock())
    monkeypatch.setattr(telemetry.metrics, "set_meter_provider", Mock())
    fastapi_instrumentor = Mock()
    httpx_instrumentor = Mock()
    sqlalchemy_instrumentor = Mock()
    monkeypatch.setattr(telemetry, "FastAPIInstrumentor", fastapi_instrumentor)
    monkeypatch.setattr(telemetry, "HTTPXClientInstrumentor", Mock(return_value=httpx_instrumentor))
    monkeypatch.setattr(
        telemetry, "SQLAlchemyInstrumentor", Mock(return_value=sqlalchemy_instrumentor)
    )
    app = FastAPI()

    assert telemetry.configure_telemetry(app) is True
    fastapi_instrumentor.instrument_app.assert_called_once_with(app)
    httpx_instrumentor.instrument.assert_called_once_with()
    sqlalchemy_instrumentor.instrument.assert_called_once_with()
