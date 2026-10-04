"""Endpoints n8n calls. Protected by the shared secret in X-Backhouse-Secret."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.auth import DEMO_TENANT, verify_webhook_secret
from app.db import get_db
from app.models import DocStatus, Document, Tenant, Vendor
from app.schemas import ExportedIn

router = APIRouter(prefix="/webhooks", tags=["webhooks"], dependencies=[Depends(verify_webhook_secret)])


@router.post("/intake", status_code=status.HTTP_201_CREATED)
async def intake(
    file: UploadFile = File(...),
    sender: str | None = Form(default=None),
    subject: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    # Single-tenant demo: email intake lands in the demo tenant.
    tenant = db.scalar(select(Tenant).where(Tenant.name == DEMO_TENANT)) or db.scalar(select(Tenant).order_by(Tenant.id))
    if tenant is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No tenant configured")
    try:
        doc = services.ingest(
            db,
            tenant_id=tenant.id,
            filename=file.filename or "attachment",
            data=await file.read(),
            declared_type=file.content_type,
            source="email",
            email_from=(sender or "")[:320] or None,
        )
    except services.IngestError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if subject:
        services.audit(db, doc, "email_received", after={"subject": subject[:300], "from": sender})
        db.commit()
    return {"document_id": doc.id, "status": doc.status}


@router.post("/exported")
def exported(body: ExportedIn, db: Session = Depends(get_db)) -> dict:
    doc = db.get(Document, body.document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if doc.status not in (DocStatus.APPROVED, DocStatus.EXPORTED):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is {doc.status}")
    doc.odoo_bill_id = body.odoo_bill_id
    doc.status = DocStatus.EXPORTED
    doc.error = None
    if body.odoo_partner_id and doc.vendor_id:
        vendor = db.get(Vendor, doc.vendor_id)
        if vendor and not vendor.odoo_partner_id:
            vendor.odoo_partner_id = body.odoo_partner_id
    services.audit(db, doc, "exported", after={"odoo_bill_id": body.odoo_bill_id})
    db.commit()
    return {"ok": True}
