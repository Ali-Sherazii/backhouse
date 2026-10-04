"""First-boot seed: demo tenant, users, vendors, and a few already-processed invoices.

Idempotent; runs on every api start. Seeded invoices come from samples/seed/ with their
ground truth standing in for an LLM extraction, so the dashboard has data before the
model has even been pulled.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app import services, storage
from app.auth import seed_users
from app.config import get_settings
from app.db import SessionLocal
from app.models import DocStatus, Document, Extraction, GuardResult, Tenant, Vendor
from app.pipeline import guard, locate, text
from app.pipeline.decide import decide

log = logging.getLogger("backhouse.seed")

SEED_CONFIDENCE = 0.97


def seed_vendors(db, tenant: Tenant, samples: Path) -> None:
    path = samples / "vendors.json"
    if not path.exists():
        return
    for v in json.loads(path.read_text(encoding="utf-8")):
        exists = db.scalar(select(Vendor).where(Vendor.tenant_id == tenant.id, Vendor.name == v["name"]))
        if exists is None:
            db.add(Vendor(tenant_id=tenant.id, name=v["name"], aliases=v["aliases"], tax_id=v["tax_id"]))
    db.commit()


def seed_documents(db, tenant: Tenant, samples: Path) -> None:
    truth_path = samples / "ground_truth.json"
    if not truth_path.exists():
        return
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    for i, (name, meta) in enumerate(truth.items()):
        if not meta.get("seed"):
            continue
        raw = (samples / name).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if db.scalar(select(Document.id).where(Document.tenant_id == tenant.id, Document.sha256 == sha)):
            continue
        expected = meta["expected"]
        created = datetime.combine(
            datetime.fromisoformat(expected["invoice_date"]).date() + timedelta(days=1), dtime(9, 15 + i), tzinfo=timezone.utc
        )
        key = f"originals/{tenant.id}/{sha[:2]}/seed-{Path(name).name}"
        storage.put_bytes(key, raw, "application/pdf")
        doc = Document(
            tenant_id=tenant.id,
            source="email" if i % 2 else "upload",
            filename=Path(name).name,
            content_type="application/pdf",
            minio_key=key,
            sha256=sha,
            status=DocStatus.PROCESSING,
            created_at=created,
            email_from="billing@supplier.example" if i % 2 else None,
            is_seed=True,
        )
        db.add(doc)
        db.flush()

        pdf = text.open_document(raw, "application/pdf")
        layout = text.extract_layout(pdf)
        for pno, png in enumerate(text.page_images(pdf)):
            storage.put_bytes(storage.page_key(doc.id, pno), png, "image/png")
        outcome = guard.run_guard(pdf, layout.spans)
        doc.layout = layout.to_json()
        doc.page_count = len(layout.pages)
        doc.text_source = layout.text_source
        doc.guard_result = GuardResult(flagged=outcome.flagged, signals=outcome.signals)

        confidence = {k: SEED_CONFIDENCE for k in ("vendor_name", "vendor_tax_id", "invoice_number", "invoice_date",
                                                   "due_date", "currency", "line_items", "subtotal", "tax", "total")}
        if meta.get("seed_status") == DocStatus.NEEDS_REVIEW:
            confidence["total"] = 0.62
            confidence["line_items"] = 0.7
        confidence, boxes, ungrounded = locate.ground(expected, confidence, layout.spans)
        doc.extraction = Extraction(
            document_id=doc.id,
            data=expected,
            field_confidence={**confidence, "_ungrounded": ungrounded},
            field_boxes=boxes,
            model="seed (ground truth)",
            latency_ms=None,
        )
        checks = services.validate_and_store(db, doc, expected)
        decision = decide(
            guard_flagged=outcome.flagged,
            checks=checks,
            data=expected,
            confidence=confidence,
            threshold=get_settings().auto_approve_min_confidence,
        )
        doc.processed_at = created + timedelta(seconds=40)
        doc.processing_ms = 21000 + i * 3700
        services.audit(db, doc, "received", after={"source": doc.source, "filename": doc.filename})
        services.audit(db, doc, "processed", after={"decision": decision.status, "reasons": decision.reasons})
        if decision.auto_approved:
            services.mark_approved(db, doc, expected, user=None, auto=True, export=False)
        else:
            doc.status = DocStatus.NEEDS_REVIEW
            db.commit()
        log.info("Seeded %s as %s", name, doc.status)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    samples = Path(get_settings().samples_dir)
    for attempt in range(10):
        try:
            storage.ensure_buckets()
            break
        except Exception as exc:
            log.warning("MinIO not ready (%s), retrying", exc)
            time.sleep(3)
    db = SessionLocal()
    try:
        tenant = seed_users(db)
        seed_vendors(db, tenant, samples)
        try:
            seed_documents(db, tenant, samples)
        except Exception:
            db.rollback()
            log.exception("Seeding demo documents failed; the app still works without them")
    finally:
        db.close()


if __name__ == "__main__":
    main()
