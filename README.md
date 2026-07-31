# job_bot

Python app scaffolded for deployment to Google Cloud Run.

## Project structure

- `src/job_bot/main.py`: FastAPI app entrypoint
- `tests/test_health.py`: Basic API tests
- `Dockerfile`: Container image for Cloud Run
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

## Build container locally

```bash
docker build -t job-bot:local .
docker run --rm -p 8080:8080 job-bot:local
```

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
`DB_POOL_RECYCLE_SECONDS`.

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
