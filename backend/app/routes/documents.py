from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import services, storage
from app.auth import get_current_user, require_admin
from app.celery_app import enqueue_export, enqueue_processing
from app.config import get_settings
from app.db import get_db
from app.models import AuditLog, Check, DocStatus, Document, Extraction, GuardResult, User
from app.pipeline.extract import trace_url
from app.schemas import ApproveIn, DocumentSummary, InvoiceFields, RejectIn

router = APIRouter(prefix="/documents", tags=["documents"])


def odoo_bill_url(bill_id: int | None) -> str | None:
    if not bill_id:
        return None
    return f"{get_settings().odoo_public_url.rstrip('/')}/web#id={bill_id}&model=account.move&view_type=form"


def summarize(doc: Document) -> DocumentSummary:
    data = doc.extraction.data if doc.extraction else {}
    return DocumentSummary(
        id=doc.id,
        filename=doc.filename,
        source=doc.source,
        status=doc.status,
        created_at=doc.created_at,
        processed_at=doc.processed_at,
        processing_ms=doc.processing_ms,
        vendor_name=(doc.vendor.name if doc.vendor else None) or data.get("vendor_name"),
        invoice_number=data.get("invoice_number"),
        total=data.get("total"),
        currency=data.get("currency"),
        flagged=bool(doc.guard_result and doc.guard_result.flagged),
        auto_approved=doc.auto_approved,
        warnings=sum(1 for c in doc.checks if c.severity == "warning" and not c.passed),
        failed_checks=sum(1 for c in doc.checks if c.severity == "blocking" and not c.passed),
    )


def _load(db: Session, document_id: int, user: User) -> Document:
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.tenant_id == user.tenant_id)
        .options(
            selectinload(Document.extraction),
            selectinload(Document.checks),
            selectinload(Document.guard_result),
            selectinload(Document.vendor),
        )
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


def detail(db: Session, doc: Document) -> dict:
    ext = doc.extraction
    audit_rows = db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, AuditLog.user_id == User.id)
        .where(AuditLog.document_id == doc.id)
        .order_by(AuditLog.at, AuditLog.id)
    ).all()
    pages = (doc.layout or {}).get("pages", [])
    return {
        **summarize(doc).model_dump(mode="json"),
        "content_type": doc.content_type,
        "page_count": doc.page_count,
        "text_source": doc.text_source,
        "sha256": doc.sha256,
        "email_from": doc.email_from,
        "error": doc.error,
        "odoo_bill_id": doc.odoo_bill_id,
        "odoo_url": odoo_bill_url(doc.odoo_bill_id),
        "vendor": (
            {"id": doc.vendor.id, "name": doc.vendor.name, "odoo_partner_id": doc.vendor.odoo_partner_id}
            if doc.vendor
            else None
        ),
        "file_url": f"/documents/{doc.id}/file",
        "page_urls": [f"/documents/{doc.id}/pages/{i}" for i in range(len(pages))],
        "layout": doc.layout or {"pages": [], "spans": []},
        "extraction": (
            {
                "data": ext.data,
                "field_confidence": ext.field_confidence,
                "field_boxes": ext.field_boxes,
                "model": ext.model,
                "latency_ms": ext.latency_ms,
                "langfuse_trace_id": ext.langfuse_trace_id,
                "trace_url": trace_url(ext.langfuse_trace_id),
            }
            if ext
            else None
        ),
        "checks": [
            {"name": c.name, "passed": c.passed, "severity": c.severity, "detail": c.detail, "data": c.data}
            for c in doc.checks
        ],
        "guard": (
            {"flagged": doc.guard_result.flagged, "signals": doc.guard_result.signals} if doc.guard_result else None
        ),
        "audit": [
            {"action": a.action, "user": email, "before": a.before, "after": a.after, "at": a.at.isoformat()}
            for a, email in audit_rows
        ],
    }


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DocumentSummary)
async def upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentSummary:
    data = await file.read()
    try:
        doc = services.ingest(
            db,
            tenant_id=user.tenant_id,
            filename=file.filename or "upload",
            data=data,
            declared_type=file.content_type,
            source="upload",
            user=user,
        )
    except services.IngestError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return summarize(_load(db, doc.id, user))


@router.get("", response_model=list[DocumentSummary])
def list_documents(
    status_filter: str | None = Query(default=None, alias="status"),
    flagged: bool | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentSummary]:
    q = (
        select(Document)
        .where(Document.tenant_id == user.tenant_id)
        .options(
            selectinload(Document.extraction),
            selectinload(Document.checks),
            selectinload(Document.guard_result),
            selectinload(Document.vendor),
        )
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        statuses = [s for s in status_filter.split(",") if s in DocStatus.ALL]
        q = q.where(Document.status.in_(statuses))
    if flagged is not None:
        q = q.join(GuardResult, isouter=True).where(func.coalesce(GuardResult.flagged, False) == flagged)
    return [summarize(d) for d in db.scalars(q).all()]


@router.get("/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return detail(db, _load(db, document_id, user))


@router.get("/{document_id}/file")
def get_file(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    doc = _load(db, document_id, user)
    return Response(
        storage.get_bytes(doc.minio_key),
        media_type=doc.content_type,
        headers={"Content-Disposition": f'inline; filename="{doc.filename.replace(chr(34), "")}"', "Cache-Control": "private, max-age=300"},
    )


@router.get("/{document_id}/pages/{page}")
def get_page(document_id: int, page: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    doc = _load(db, document_id, user)
    if page < 0 or page >= (doc.page_count or 0):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such page")
    return Response(
        storage.get_bytes(storage.page_key(doc.id, page)),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


def _diff(before: dict, after: dict) -> tuple[dict, dict]:
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


@router.post("/{document_id}/approve")
def approve(
    document_id: int,
    body: ApproveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    doc = _load(db, document_id, user)
    if doc.status != DocStatus.NEEDS_REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is {doc.status}, only documents in review can be approved")
    ext = doc.extraction or Extraction(document_id=doc.id, data=InvoiceFields().model_dump(), field_confidence={})
    doc.extraction = ext
    before = InvoiceFields.model_validate(ext.data or {}).model_dump()
    after = body.fields.model_dump() if body.fields else before
    if after != before:
        changed_before, changed_after = _diff(before, after)
        services.audit(db, doc, "corrected", user=user, before=changed_before, after=changed_after)
        ext.data = after
    if body.note:
        services.audit(db, doc, "note", user=user, after={"note": body.note})
    # Re-run the rules on what the reviewer approved, for the record. The human decision stands.
    services.validate_and_store(db, doc, after)
    services.mark_approved(db, doc, after, user=user, auto=False)
    return detail(db, _load(db, document_id, user))


@router.post("/{document_id}/reject")
def reject(
    document_id: int,
    body: RejectIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    doc = _load(db, document_id, user)
    if doc.status not in (DocStatus.NEEDS_REVIEW, DocStatus.FAILED, DocStatus.QUEUED):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is {doc.status} and can't be rejected")
    doc.status = DocStatus.REJECTED
    services.audit(db, doc, "rejected", user=user, after={"reason": body.reason})
    db.commit()
    return detail(db, _load(db, document_id, user))


@router.post("/{document_id}/export")
def retry_export(document_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    """Send an approved document to n8n again, e.g. after Odoo was down."""
    doc = _load(db, document_id, user)
    if doc.status != DocStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is {doc.status}; only approved documents are exported")
    services.audit(db, doc, "export_retry_requested", user=user)
    db.commit()
    enqueue_export(doc.id)
    return detail(db, _load(db, document_id, user))


@router.post("/{document_id}/reprocess")
def reprocess(document_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    doc = _load(db, document_id, user)
    if doc.status in (DocStatus.APPROVED, DocStatus.EXPORTED):
        raise HTTPException(status.HTTP_409_CONFLICT, "Approved documents can't be reprocessed")
    doc.status = DocStatus.QUEUED
    db.query(Check).filter(Check.document_id == doc.id).delete()
    services.audit(db, doc, "reprocess_requested", user=user)
    db.commit()
    enqueue_processing(doc.id)
    return detail(db, _load(db, document_id, user))
