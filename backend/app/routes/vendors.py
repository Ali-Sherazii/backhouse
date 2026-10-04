from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.db import get_db
from app.models import User, Vendor
from app.schemas import VendorIn, VendorOut

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=list[VendorOut])
def list_vendors(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Vendor]:
    return list(db.scalars(select(Vendor).where(Vendor.tenant_id == user.tenant_id).order_by(Vendor.name)).all())


@router.post("", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
def create_vendor(body: VendorIn, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> Vendor:
    vendor = Vendor(
        tenant_id=user.tenant_id,
        name=body.name.strip(),
        aliases=[a.strip() for a in body.aliases if a.strip()],
        tax_id=(body.tax_id or "").strip() or None,
    )
    db.add(vendor)
    db.commit()
    return vendor
