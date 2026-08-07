import asyncio
import sys

import uvicorn
from fastapi import FastAPI

from job_bot.api.api_v1 import router
from job_bot.api.api_v2 import router as routerv2
from job_bot.api.greenhouse_api import router as greenhouse_router
from job_bot.api.user_api import router as user_router
from job_bot.config import settings
from job_bot.logging import configure_logging
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
app.include_router(router)
app.include_router(greenhouse_router)
app.include_router(routerv2)
app.include_router(user_router)


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "job_bot.main:app",
        host="127.0.0.1",
        port=8080,
        reload=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
