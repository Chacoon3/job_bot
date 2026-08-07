# job_bot

Python app scaffolded for deployment to Google Cloud Run.

## Project structure

- `src/job_bot/main.py`: FastAPI app entrypoint
- `tests/test_health.py`: Basic API tests
- `Dockerfile`: Lightweight API and browser-worker container targets for Cloud Run
- `.github/workflows/cd.yml`: Cloud Run continuous-deployment workflow

## Local setup

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pip install -e .
pytest
```

## PostgreSQL database

Set a SQLAlchemy PostgreSQL connection URL:

```bash
DATABASE_URL=postgresql+psycopg://job_bot:password@localhost:5432/job_bot
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT_SECONDS=30
DB_POOL_RECYCLE_SECONDS=1800
```

Apply all database migrations:

```bash
alembic upgrade head
```

Create a new explicit migration:

```bash
alembic revision -m "describe schema change"
```

Rollback the most recent migration:

```bash
alembic downgrade -1
```

The target database must already exist. Alembic records applied revisions in
its `alembic_version` table. Runtime ORM metadata is not used to generate the
database schema.
The connection pool validates connections before checkout, permits up to
`DB_POOL_SIZE + DB_MAX_OVERFLOW` concurrent connections, and recycles
long-lived PostgreSQL connections.

## Run locally

```bash
uvicorn job_bot.main:app --host 0.0.0.0 --port 8080
```

## OpenTelemetry

The service emits traces and metrics over OTLP/HTTP and automatically instruments
FastAPI requests, HTTPX calls, and SQLAlchemy operations. Structured logs produced
inside a span include `trace_id` and `span_id` fields for correlation.

Telemetry stays off when no endpoint is configured. Point it at an OpenTelemetry
Collector or an OTLP-compatible observability backend:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_SERVICE_NAME=job-bot
```

The exporter honors standard OTLP environment variables, including
`OTEL_EXPORTER_OTLP_HEADERS`, signal-specific endpoints and headers,
`OTEL_RESOURCE_ATTRIBUTES`, and `OTEL_TRACES_SAMPLER`. Set
`OTEL_SDK_DISABLED=true` to disable telemetry explicitly. Individual signals can
be disabled with `OTEL_TRACES_EXPORTER=none` or `OTEL_METRICS_EXPORTER=none`.

For a quick local trace viewer, run Jaeger with OTLP enabled and disable the
metric exporter:

```bash
docker run --rm -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one:latest
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 OTEL_METRICS_EXPORTER=none \
  uvicorn job_bot.main:app --host 0.0.0.0 --port 8080
```

Then open `http://localhost:16686` after sending requests to the application.

## Build container locally

The default `api` target does not contain Chromium. Browser-backed endpoints
return HTTP 503 in that image so application traffic can be routed explicitly
to the browser-capable service.

```bash
docker build -t job-bot:local .
docker run --rm -p 8080:8080 job-bot:local
```

Build the separate browser-worker image when job application automation is
required:

```bash
docker build --target browser-worker -t job-bot-browser:local .
docker run --rm -p 8081:8080 job-bot-browser:local
```

The browser-worker exposes the same authenticated API surface, with
`BROWSER_AUTOMATION_ENABLED=true` and Chromium installed. Route `/api/jobs/load`,
`/api/apply`, `/api/find_and_apply`, and `/apiv2/apply` to this service. The
default target keeps health, user, database, and non-browser discovery routes in
the smaller API image.

## Deploy to Cloud Run

The CD workflow deploys the root `Dockerfile` after the `CI` workflow succeeds
on `main`. It authenticates without a service-account key through Workload
Identity Federation, pushes the image to Artifact Registry, deploys a private
Cloud Run service, and calls `/api/health` with an identity token.

Configure these GitHub Actions repository or `production` environment variables:

```text
GCP_PROJECT_ID
GCP_REGION
GCP_ARTIFACT_REGISTRY_REPOSITORY
GCP_WORKLOAD_IDENTITY_PROVIDER
GCP_SERVICE_ACCOUNT
CLOUD_RUN_SERVICE_NAME
CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT
GCP_DATABASE_URL_SECRET
GCP_OPENAI_API_KEY_SECRET
JOB_BOT_LLM_MODEL
```

`GCP_DATABASE_URL_SECRET` and `GCP_OPENAI_API_KEY_SECRET` are Secret Manager
secret names or resource paths without a version suffix. The workflow deploys
their `latest` versions as `DATABASE_URL` and `OPENAI_API_KEY`.

Optional sizing variables are `CLOUD_RUN_CPU`, `CLOUD_RUN_MEMORY`,
`CLOUD_RUN_MIN_INSTANCES`, `CLOUD_RUN_MAX_INSTANCES`, `DB_POOL_SIZE`,
`DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, and
`DB_POOL_RECYCLE_SECONDS`. Set the optional `OTEL_EXPORTER_OTLP_ENDPOINT`
variable to enable telemetry for deployed revisions.

The Artifact Registry repository must exist before the first deployment. The
deployer service account needs permission to push images, deploy Cloud Run,
act as the runtime service account, access the referenced secrets, and invoke
the private service for the smoke test. The runtime service account also needs
access to both Secret Manager secrets.

For a one-time manual deployment, set these environment variables:

```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"
export REPOSITORY="job-bot-repo"
export IMAGE="job-bot"
```

Create Artifact Registry repo (one-time):

```bash
gcloud artifacts repositories create "$REPOSITORY" \
  --repository-format=docker \
  --location="$REGION" \
  --description="Docker repository for job_bot"
```

Build and push with Cloud Build:

```bash
gcloud builds submit --tag "$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$IMAGE:latest"
```

Deploy service:

```bash
gcloud run deploy job-bot \
  --image "$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$IMAGE:latest" \
  --platform managed \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080
```
