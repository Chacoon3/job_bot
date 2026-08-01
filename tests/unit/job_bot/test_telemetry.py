from unittest.mock import Mock

from fastapi import FastAPI

from job_bot import telemetry


def test_telemetry_module_is_mocked_for_pytest() -> None:
    app = FastAPI()

    assert isinstance(telemetry.configure_telemetry, Mock)
    telemetry.configure_telemetry.reset_mock()
    assert telemetry.configure_telemetry(app) is False
    telemetry.configure_telemetry.assert_called_once_with(app)
    assert not hasattr(telemetry, "OTLPSpanExporter")
