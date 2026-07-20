from fastapi import FastAPI

app = FastAPI(title="job_bot", version="0.1.0")


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "job_bot", "status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "healthy"}
