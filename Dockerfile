FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-dev.txt requirements-voice.txt ./
RUN pip install -r requirements.txt
COPY . .
RUN useradd --system --uid 10001 --home /app xa \
 && mkdir -p /app/storage /app/workspace && chown -R xa:xa /app
USER xa
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
