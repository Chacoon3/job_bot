import asyncio
import sys

import uvicorn
from fastapi import FastAPI

from job_bot.api.greenhouse import router as greenhouse_router
from job_bot.api.job import router

app = FastAPI(title="job_bot", version="0.1.0")
app.include_router(router)
app.include_router(greenhouse_router)


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run("job_bot.main:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    main()
