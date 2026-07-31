import asyncio
import sys

import uvicorn
from fastapi import FastAPI

from job_bot.api.api_v1 import router
from job_bot.api.api_v2 import router as routerv2
from job_bot.api.greenhouse_api import router as greenhouse_router
from job_bot.logging import configure_logging
from job_bot.middleware import register_middleware

configure_logging()
app = FastAPI(title="job_bot", version="0.1.0")
register_middleware(app)
app.include_router(router)
app.include_router(greenhouse_router)
app.include_router(routerv2)


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run("job_bot.main:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    main()
