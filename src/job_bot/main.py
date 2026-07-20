from datetime import datetime, timedelta

from fastapi import FastAPI

from job_bot.flow import Interval, JobEntry, JobQuery, find_jobs

app = FastAPI(title="job_bot", version="0.1.0")


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "job_bot", "status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/test/find_jobs")
def test_find_jobs() -> list[JobEntry]:

    criteria = JobQuery(
        job_title="Software Engineer",
        year_of_experience=Interval(minimum=1, maximum=4),
        job_location="United States",
        pay_range=Interval(minimum=130000, maximum=180000),
        key_words=["Python", "C#", "Cloud", "Agents", "LangChain", "Backend"],
        posted_since=datetime.now() - timedelta(days=30),
    )

    jobs = find_jobs(criteria)
    return jobs
