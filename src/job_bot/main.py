import asyncio
import sys

import uvicorn


def main() -> None:
    if sys.platform == "win32":
        # Psycopg's async connection uses readiness-based file-descriptor APIs,
        # which are not implemented by Windows' default Proactor event loop.

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(
        "job_bot.app_def:app",
        host="127.0.0.1",
        port=8080,
        reload=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
