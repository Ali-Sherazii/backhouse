import hmac
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Tenant, User

DEMO_TENANT = "Demo Bistro"
DEMO_USERS = (
    ("reviewer@demo.backhouse", "reviewer"),
    ("admin@demo.backhouse", "admin"),
)

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "tid": user.tenant_id,
        "iat": now,
        "exp": now + timedelta(hours=s.jwt_ttl_hours),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


def verify_webhook_secret(x_backhouse_secret: str | None = Header(default=None)) -> None:
    expected = get_settings().webhook_secret
    if not x_backhouse_secret or not hmac.compare_digest(x_backhouse_secret, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad webhook secret")


def seed_users(db: Session) -> Tenant:
    """Create the demo tenant and the two demo accounts if they don't exist."""
    tenant = db.query(Tenant).filter_by(name=DEMO_TENANT).one_or_none()
    if tenant is None:
        tenant = Tenant(name=DEMO_TENANT)
        db.add(tenant)
        db.flush()
    password = get_settings().demo_password
    for email, role in DEMO_USERS:
        if db.query(User).filter_by(email=email).one_or_none() is None:
            db.add(User(email=email, password_hash=hash_password(password), role=role, tenant_id=tenant.id))
    db.commit()
    return tenant
