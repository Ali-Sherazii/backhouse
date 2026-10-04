"""Database-backed operations shared by the api routes and the Celery worker."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app import storage
from app.celery_app import enqueue_export, enqueue_processing
from app.config import get_settings
from app.models import AuditLog, Check, DocStatus, Document, PriceHistory, User, Vendor
from app.pipeline.validate import CheckContext, CheckResult, VendorRef, normalize_item, parse_date, run_checks

LIVE_STATUSES = (DocStatus.QUEUED, DocStatus.PROCESSING, DocStatus.NEEDS_REVIEW, DocStatus.APPROVED, DocStatus.EXPORTED)


class IngestError(ValueError):
    pass


def ingest(
    db: Session,
    *,
    tenant_id: int,
    filename: str,
    data: bytes,
    declared_type: str | None,
    source: str,
    user: User | None = None,
    email_from: str | None = None,
) -> Document:
    """Store an uploaded or emailed file in MinIO, create the document row, queue the pipeline."""
    from app.pipeline.text import guess_content_type

    if not data:
        raise IngestError("Empty file")
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise IngestError(f"File is larger than {get_settings().max_upload_mb} MB")
    filename = os.path.basename(filename or "upload").strip()[:200] or "upload"
    try:
        ctype = guess_content_type(filename, declared_type)
    except ValueError as exc:
        raise IngestError(str(exc)) from exc
    if ctype == "application/pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        raise IngestError("File is not a valid PDF")
    sha = hashlib.sha256(data).hexdigest()
    ext = os.path.splitext(filename)[1].lower() or ".bin"
    key = f"originals/{tenant_id}/{sha[:2]}/{uuid.uuid4().hex}{ext}"
    storage.put_bytes(key, data, ctype)
    doc = Document(
        tenant_id=tenant_id,
        source=source,
        filename=filename,
        content_type=ctype,
        minio_key=key,
        sha256=sha,
        status=DocStatus.QUEUED,
        uploaded_by=user.id if user else None,
        email_from=email_from,
    )
    db.add(doc)
    db.flush()
    audit(db, doc, "received", user=user, after={"source": source, "filename": filename, "from": email_from})
    db.commit()
    enqueue_processing(doc.id)
    return doc


def audit(db: Session, doc: Document, action: str, user: User | None = None, before=None, after=None) -> None:
    db.add(AuditLog(document_id=doc.id, user_id=user.id if user else None, action=action, before=before, after=after))


def vendor_refs(db: Session, tenant_id: int) -> list[VendorRef]:
    rows = db.scalars(select(Vendor).where(Vendor.tenant_id == tenant_id)).all()
    return [VendorRef(id=v.id, name=v.name, aliases=list(v.aliases or []), tax_id=v.tax_id) for v in rows]


def _comparable(doc: Document):
    """Which other documents a document is checked against for duplicates.

    A demo sample run is compared only with the seeded history, so every run of a sample
    behaves like the first one, whatever reviewers have uploaded or emailed since.
    Everything else is compared with everything."""
    if doc.source == "sample":
        return Document.is_seed.is_(True)
    return true()


def check_context(db: Session, doc: Document) -> CheckContext:
    dup = db.scalar(
        select(Document.id)
        .where(
            Document.tenant_id == doc.tenant_id,
            Document.sha256 == doc.sha256,
            Document.id != doc.id,
            Document.status.in_(LIVE_STATUSES),
            _comparable(doc),
        )
        .order_by(Document.id)
        .limit(1)
    )

    def invoice_seen(vendor_id: int, number: str) -> int | None:
        return db.scalar(
            select(Document.id)
            .where(
                Document.tenant_id == doc.tenant_id,
                Document.vendor_id == vendor_id,
                Document.invoice_number == number,
                Document.id != doc.id,
                Document.status.in_(LIVE_STATUSES),
                _comparable(doc),
            )
            .order_by(Document.id)
            .limit(1)
        )

    def last_price(vendor_id: int, item: str):
        row = db.execute(
            select(PriceHistory.unit_price, PriceHistory.invoice_date)
            .join(Document, Document.id == PriceHistory.document_id)
            .where(
                PriceHistory.vendor_id == vendor_id,
                PriceHistory.item_name_normalized == item,
                PriceHistory.document_id != doc.id,
                # Samples compare prices with the seeded history only, and never feed it.
                Document.is_seed.is_(True) if doc.source == "sample" else Document.source != "sample",
            )
            .order_by(PriceHistory.invoice_date.desc().nullslast(), PriceHistory.id.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        return row[0], row[1].isoformat() if row[1] else None

    return CheckContext(
        vendors=vendor_refs(db, doc.tenant_id),
        today=date.today(),
        duplicate_file_of=dup,
        invoice_seen=invoice_seen,
        last_price=last_price,
    )


def validate_and_store(db: Session, doc: Document, data: dict) -> list[CheckResult]:
    """Run every rule, replace the document's check rows, and remember the matched vendor."""
    results, vendor = run_checks(data, check_context(db, doc))
    doc.checks.clear()
    db.flush()
    for r in results:
        doc.checks.append(Check(name=r.name, passed=r.passed, severity=r.severity, detail=r.detail, data=r.data))
    doc.vendor_id = vendor.id if vendor else None
    doc.invoice_number = (data.get("invoice_number") or "").strip() or None
    return results


def record_price_history(db: Session, doc: Document, data: dict) -> None:
    if doc.vendor_id is None:
        return
    db.query(PriceHistory).filter(PriceHistory.document_id == doc.id).delete()
    inv_date = parse_date(data.get("invoice_date"))
    seen = set()
    for item in data.get("line_items") or []:
        key = normalize_item(item.get("description") or "")
        if not key or item.get("unit_price") is None or key in seen:
            continue
        seen.add(key)
        db.add(
            PriceHistory(
                vendor_id=doc.vendor_id,
                item_name_normalized=key,
                unit_price=float(item["unit_price"]),
                invoice_date=inv_date,
                document_id=doc.id,
            )
        )


def ensure_vendor(db: Session, doc: Document, data: dict) -> None:
    """A human approved an invoice from a vendor we don't know yet: remember the vendor."""
    if doc.vendor_id is not None or not data.get("vendor_name"):
        return
    vendor = Vendor(tenant_id=doc.tenant_id, name=data["vendor_name"], aliases=[], tax_id=data.get("vendor_tax_id"))
    db.add(vendor)
    db.flush()
    doc.vendor_id = vendor.id


def mark_approved(db: Session, doc: Document, data: dict, *, user: User | None, auto: bool, export: bool = True) -> None:
    ensure_vendor(db, doc, data)
    record_price_history(db, doc, data)
    doc.status = DocStatus.APPROVED
    doc.auto_approved = auto
    audit(db, doc, "auto_approved" if auto else "approved", user=user, after={"status": DocStatus.APPROVED})
    db.commit()
    if export:
        enqueue_export(doc.id)


def export_payload(db: Session, doc: Document, app_url: str) -> dict:
    data = doc.extraction.data if doc.extraction else {}
    vendor = doc.vendor
    warnings = [
        {"check": c.name, "detail": c.detail, "data": c.data}
        for c in doc.checks
        if c.severity == "warning" and not c.passed
    ]
    approver = db.scalar(
        select(User.email)
        .join(AuditLog, AuditLog.user_id == User.id)
        .where(AuditLog.document_id == doc.id, AuditLog.action == "approved")
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    guard_flagged = bool(doc.guard_result and doc.guard_result.flagged)
    return {
        "document_id": doc.id,
        "document_url": f"{app_url.rstrip('/')}/documents/{doc.id}",
        "vendor": {
            "id": vendor.id if vendor else None,
            "name": (vendor.name if vendor else None) or data.get("vendor_name"),
            "tax_id": (vendor.tax_id if vendor else None) or data.get("vendor_tax_id"),
            "odoo_partner_id": vendor.odoo_partner_id if vendor else None,
        },
        "invoice": {
            "number": data.get("invoice_number"),
            "date": data.get("invoice_date"),
            "due_date": data.get("due_date"),
            "currency": data.get("currency"),
            "subtotal": data.get("subtotal"),
            "discount": abs(data.get("discount") or 0) or None,
            "tax": data.get("tax"),
            "total": data.get("total"),
            "lines": [
                {
                    "description": li.get("description"),
                    "quantity": li.get("quantity") if li.get("quantity") is not None else 1,
                    "unit_price": li.get("unit_price") if li.get("unit_price") is not None else li.get("amount"),
                    "amount": li.get("amount"),
                }
                for li in data.get("line_items") or []
            ],
        },
        "warnings": warnings,
        "guard_flagged": guard_flagged,
        "auto_approved": doc.auto_approved,
        "approved_by": approver or ("auto" if doc.auto_approved else None),
        "alert": bool(warnings) or guard_flagged,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
