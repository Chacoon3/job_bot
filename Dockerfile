FROM python:3.11-slim AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8080

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

EXPOSE 8080

CMD ["uvicorn", "job_bot.main:app", "--host", "0.0.0.0", "--port", "8080"]

FROM runtime-base AS browser-worker

COPY requirements-browser.txt ./
RUN pip install --no-cache-dir -r requirements-browser.txt \
    && python -m playwright install --with-deps chromium

ENV BROWSER_AUTOMATION_ENABLED=true

FROM runtime-base AS api

ENV BROWSER_AUTOMATION_ENABLED=false
