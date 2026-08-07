import asyncio
import sys

import uvicorn


def main() -> None:

    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else "auto"

    uvicorn.run(
        "job_bot.app_def:app",
        host="127.0.0.1",
        port=8080,
        reload=False,
        log_config=None,
        loop=loop,
    )


if __name__ == "__main__":
    main()
