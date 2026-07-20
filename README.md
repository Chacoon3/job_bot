# job_bot

Python app scaffolded for deployment to Google Cloud Run.

## Project structure

- `src/job_bot/main.py`: FastAPI app entrypoint
- `tests/test_health.py`: Basic API tests
- `Dockerfile`: Container image for Cloud Run
- `cloudrun/service.yaml`: Optional Cloud Run service manifest

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

Set these environment variables:

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
