"""'Try a sample' buttons: list the demo invoices in samples/ and feed one through the pipeline."""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import services
from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.routes.documents import summarize
from app.schemas import DocumentSummary

router = APIRouter(prefix="/samples", tags=["samples"])


@lru_cache
def manifest() -> dict:
    path = Path(get_settings().samples_dir) / "ground_truth.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("")
def list_samples(user: User = Depends(get_current_user)) -> list[dict]:
    return [
        {"name": name, "kind": meta["kind"], "title": meta["title"], "description": meta["description"]}
        for name, meta in manifest().items()
        if not meta.get("seed")
    ]


@router.post("/{name}", response_model=DocumentSummary, status_code=status.HTTP_201_CREATED)
def run_sample(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DocumentSummary:
    meta = manifest().get(name)
    if meta is None or meta.get("seed"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown sample")
    path = Path(get_settings().samples_dir) / name
    doc = services.ingest(
        db,
        tenant_id=user.tenant_id,
        filename=name,
        data=path.read_bytes(),
        declared_type=None,
        source="sample",
        user=user,
    )
    return summarize(doc)
