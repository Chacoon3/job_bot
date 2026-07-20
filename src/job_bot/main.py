from fastapi import FastAPI

from job_bot.flow import JobEntry, JobQuery, PayRange, find_jobs

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
        year_of_experience=3,
        job_location="San Francisco, CA",
        pay_range=PayRange(minimum=130000, maximum=180000),
        tech_stack=["Python", "Django", "AWS", "Agents", "LangChain"],
    )

    jobs = find_jobs(criteria)
    return jobs
