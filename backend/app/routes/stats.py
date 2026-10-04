from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.db import get_db
from app.models import Check, DocStatus, Document, GuardResult, User
from app.routes.documents import summarize

router = APIRouter(tags=["stats"])


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    tid = user.tenant_id
    counts = dict(
        db.execute(select(Document.status, func.count()).where(Document.tenant_id == tid).group_by(Document.status)).all()
    )
    processed = db.scalar(select(func.count()).where(Document.tenant_id == tid, Document.processed_at.is_not(None))) or 0
    auto = db.scalar(select(func.count()).where(Document.tenant_id == tid, Document.auto_approved.is_(True))) or 0
    avg_ms = db.scalar(select(func.avg(Document.processing_ms)).where(Document.tenant_id == tid, Document.processing_ms.is_not(None)))
    flagged = (
        db.scalar(
            select(func.count())
            .select_from(GuardResult)
            .join(Document, Document.id == GuardResult.document_id)
            .where(Document.tenant_id == tid, GuardResult.flagged.is_(True))
        )
        or 0
    )

    def docs(q):
        q = q.options(
            selectinload(Document.extraction),
            selectinload(Document.checks),
            selectinload(Document.guard_result),
            selectinload(Document.vendor),
        )
        return [summarize(d).model_dump(mode="json") for d in db.scalars(q).all()]

    recent = docs(select(Document).where(Document.tenant_id == tid).order_by(Document.created_at.desc(), Document.id.desc()).limit(8))
    flagged_docs = docs(
        select(Document)
        .join(GuardResult, GuardResult.document_id == Document.id)
        .where(Document.tenant_id == tid, GuardResult.flagged.is_(True))
        .order_by(Document.created_at.desc())
        .limit(6)
    )
    alerts = db.execute(
        select(Check, Document)
        .join(Document, Document.id == Check.document_id)
        .where(
            Document.tenant_id == tid,
            Check.name == "price_change",
            Check.passed.is_(False),
            Document.status != DocStatus.REJECTED,
        )
        .order_by(Document.created_at.desc())
        .limit(10)
    ).all()
    price_alerts = [
        {
            "document_id": doc.id,
            "vendor_name": doc.vendor.name if doc.vendor else None,
            "status": doc.status,
            "detail": check.detail,
            "changes": (check.data or {}).get("changes", []),
            "created_at": doc.created_at.isoformat(),
        }
        for check, doc in alerts
    ]
    return {
        "counts": {s: counts.get(s, 0) for s in DocStatus.ALL},
        "total": sum(counts.values()),
        "processed": processed,
        "auto_approved": auto,
        "auto_approve_rate": round(auto / processed, 3) if processed else None,
        "flagged": flagged,
        "avg_processing_ms": int(avg_ms) if avg_ms is not None else None,
        "recent": recent,
        "flagged_documents": flagged_docs,
        "price_alerts": price_alerts,
    }
