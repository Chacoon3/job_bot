from fastapi import FastAPI

from job_bot.api.api_v1 import router
from job_bot.api.greenhouse_api import router as greenhouse_router
from job_bot.api.job_api import router as routerv2
from job_bot.api.probes import router as probes_router
from job_bot.api.user_api import router as user_router
from job_bot.app_logging import configure_logging
from job_bot.config import settings
from job_bot.middleware import register_middleware
from job_bot.telemetry import configure_telemetry

configure_logging()
app = FastAPI(
    title="job_bot",
    version="0.1.0",
    debug=settings().APP_ENV.strip().lower() == "local",
)
register_middleware(app)
configure_telemetry(app)
app.include_router(probes_router)
app.include_router(router)
app.include_router(greenhouse_router)
app.include_router(routerv2)
app.include_router(user_router)
