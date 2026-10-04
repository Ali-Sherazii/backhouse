import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import storage
from app.config import get_settings
from app.db import engine
from app.routes import auth, documents, samples, stats, vendors, webhooks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backhouse")

app = FastAPI(title="Backhouse API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().app_public_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth.router, documents.router, vendors.router, stats.router, samples.router, webhooks.router):
    app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    try:
        storage.ensure_buckets()
    except Exception:
        log.exception("Could not create MinIO buckets (will retry on next start)")


@app.get("/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    return {"status": "ok"}
