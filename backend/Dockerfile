# Build context is the repo root (so samples/ can be baked in for seeding and "try a sample").
FROM python:3.11-slim AS py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

FROM py AS api-deps
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

FROM api-deps AS worker-deps
ARG INSTALL_PADDLE=false
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
COPY backend/requirements-worker.txt /tmp/requirements-worker.txt
RUN pip install -r /tmp/requirements-worker.txt
# Optional PaddleOCR fallback (large). docker compose build --build-arg INSTALL_PADDLE=true worker
RUN if [ "$INSTALL_PADDLE" = "true" ]; then pip install "paddlepaddle==2.6.2" "paddleocr==2.9.1"; fi

FROM api-deps AS api
COPY samples/ /samples/
COPY backend/ /app/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM worker-deps AS worker
COPY samples/ /samples/
COPY backend/ /app/
CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "-Q", "backhouse", "--pool=solo", "--loglevel=INFO"]
