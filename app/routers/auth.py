# app/routers/auth.py
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from app.services.seatbelt import backup_event

import hashlib
import secrets

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select
from sqlalchemy import text
from jose import JWTError, jwt
import os
from app.routers.invites import ensure_invite_table

from app.models import Tenant, ApiKey
from app.db import get_session
from app import config

router = APIRouter(prefix="/auth", tags=["auth"])

# ----------------- JWT / security constants -----------------

SECRET_KEY = getattr(config, "JWT_SECRET", None) or getattr(config, "DEBUG_BEARER", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


# ----------------- Helpers -----------------


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    return _pwd_context.verify(plain_password, hashed_password)


def hash_api_key(key: str) -> str:
    """SHA-256 hash for API keys. High-entropy random keys don't need bcrypt."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def slugify(name: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in name)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "tenant"


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def parse_token(token: str) -> Dict[str, Any]:
    """
    Used by app.deps.get_tenant_id and get_current_user.
    Decodes JWT and returns the payload dict or raises HTTPException(401).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise credentials_exception
    if not isinstance(payload, dict):
        raise credentials_exception
    return payload


def row_to_dict(row: Any) -> Dict[str, Any]:
    """
    Safe helper to convert SQLAlchemy Row / RowMapping to dict.
    """
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    try:
        return dict(row)
    except TypeError:
        return {k: getattr(row, k) for k in dir(row) if not k.startswith("_")}


# ----------------- Pydantic models -----------------


class SignupResponse(BaseModel):
    tenant_slug: str
    api_key: str
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_slug: str
    api_key: str


class MeResponse(BaseModel):
    email: EmailStr
    tenant_slug: str
    needs_setup: bool

    business_name: Optional[str] = None
    booking_link: Optional[str] = None
    review_google_url: Optional[str] = None
    office_sms_to: Optional[str] = None
    office_email_to: Optional[str] = None

class SignupRequest(BaseModel):
    invite_code: str
    business_name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str
    review_link: Optional[str] = None

# ----------------- Auth dependency: get_current_user -----------------


def get_current_user(
    authorization: str = Header(...),
    session: Session = Depends(get_session),  # kept for future DB checks if needed
) -> Dict[str, Any]:
    """
    Reads Authorization: Bearer <token>, decodes JWT, returns { email, tenant_slug }.
    """
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.split(" ", 1)[1].strip()
    payload = parse_token(token)  # raises 401 if invalid

    email = payload.get("sub")
    tenant_slug = payload.get("tenant") or payload.get("tenant_slug")

    if not email or not tenant_slug:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    return {"email": email, "tenant_slug": tenant_slug}


# ----------------- Signup -----------------

@router.post("/signup", response_model=SignupResponse)
def signup(payload: SignupRequest, session: Session = Depends(get_session)):
    ensure_invite_table(session)

    code = (payload.invite_code or "").strip()
    row = session.exec(text("""
        SELECT code, expires_at, used_at
        FROM invite_code
        WHERE code = :code
        LIMIT 1
    """).bindparams(code=code)).first()

    if not row:
        raise HTTPException(status_code=403, detail="Invalid invite code")

    data = row_to_dict(row)
    if data.get("used_at"):
        raise HTTPException(status_code=403, detail="Invite already used")

    exp = data.get("expires_at")
    if exp:
        exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > exp_dt:
            raise HTTPException(status_code=403, detail="Invite expired")

    # Ensure password_hash column exists. Use a SAVEPOINT so a "column already
    # exists" error doesn't abort the outer transaction (PostgreSQL DDL is
    # transactional — a bare except:pass leaves the connection in a broken state).
    try:
        session.exec(text("SAVEPOINT sp_add_col"))
        session.exec(text("ALTER TABLE tenant ADD COLUMN password_hash TEXT"))
        session.exec(text("RELEASE SAVEPOINT sp_add_col"))
    except Exception:
        session.exec(text("ROLLBACK TO SAVEPOINT sp_add_col"))

    slug = slugify(payload.business_name)
    email_lower = payload.email.lower().strip()
    api_key_plain = secrets.token_hex(32)

    try:
        existing_slug = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
        if existing_slug:
            raise HTTPException(status_code=400, detail="Business name is already taken")

        existing_email = session.exec(select(Tenant).where(Tenant.email == email_lower)).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already registered")

        booking_link_default = getattr(config, "BOOKING_LINK", "") or ""
        tenant = Tenant(
            slug=slug,
            business_name=payload.business_name.strip(),
            email=email_lower,
            phone=(payload.phone or "").strip(),
            booking_link=booking_link_default,
            review_google_url=(payload.review_link or "").strip(),
            is_active=True,
        )
        session.add(tenant)
        session.flush()  # assign tenant.id

        password_hash = hash_password(payload.password)
        session.exec(
            text("UPDATE tenant SET password_hash = :pwd WHERE id = :tid")
            .bindparams(pwd=password_hash, tid=tenant.id)
        )

        api_key_row = ApiKey(
            tenant_id=tenant.id,
            hashed_key=hash_api_key(api_key_plain),
            is_active=True,
        )
        session.add(api_key_row)

        # Mark invite used atomically — rowcount 0 means a concurrent request
        # already claimed it (race condition guard).
        result = session.exec(text("""
            UPDATE invite_code
            SET used_at = :used_at
            WHERE code = :code AND used_at IS NULL
        """).bindparams(
            used_at=datetime.now(timezone.utc).isoformat(),
            code=code,
        ))
        if result.rowcount == 0:
            raise HTTPException(status_code=403, detail="Invite already used")

        session.commit()

    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail="Signup failed — please try again") from exc

    backup_event(
        session,
        category="auth",
        action="signup_success",
        tenant_id=slug,
        user_email=email_lower,
        ok=True,
        payload={"tenant_slug": slug},
    )

    token_data = {"sub": email_lower, "tenant": slug}
    access_token = create_access_token(token_data)

    return SignupResponse(
        tenant_slug=slug,
        api_key=api_key_plain,
        access_token=access_token,
    )


# ----------------- Login -----------------


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    """
    Login against Tenant:
    - Finds tenant row by email.
    - Verifies password_hash stored on tenant table.
    - Returns JWT + first active ApiKey for that tenant.
    """
    email_lower = payload.email.lower().strip()
    backup_event(
        session,
        category="auth",
        action="login_attempt",
        tenant_id=None,
        user_email=email_lower,
        ok=True,
        payload={"email": email_lower},
    )

    # make sure password_hash column exists (no-op if already there)
    try:
        session.exec(text("ALTER TABLE tenant ADD COLUMN password_hash TEXT"))
    except Exception:
        pass

    # 1) fetch tenant (API key is hashed — cannot be retrieved after signup)
    stmt = text(
        """
        SELECT
          t.id AS tenant_id,
          t.email AS email,
          t.password_hash AS password_hash,
          t.slug AS tenant_slug
        FROM tenant t
        WHERE t.email = :email
        LIMIT 1
        """
    ).bindparams(email=email_lower)

    row = session.exec(stmt).first()
    if not row:
        backup_event(
            session,
            category="auth",
            action="login_fail_user_missing",
            tenant_id=None,
            user_email=email_lower,
            ok=False,
            payload={"email": email_lower},
            error="tenant row not found for email",
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    data = row_to_dict(row)

    # password check
    if not verify_password(payload.password, data.get("password_hash")):
        backup_event(
            session,
            category="auth",
            action="login_fail_bad_password",
            tenant_id=data.get("tenant_slug"),
            user_email=email_lower,
            ok=False,
            payload={"tenant_slug": data.get("tenant_slug")},
            error="password mismatch",
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # API key is hashed in DB — cannot be retrieved after signup
    tenant_slug = data["tenant_slug"]
    api_key = ""

    backup_event(
        session,
        category="auth",
        action="login_success",
        tenant_id=tenant_slug,
        user_email=email_lower,
        ok=True,
        payload={"tenant_slug": tenant_slug},
    )

    # build JWT
    token_data = {"sub": email_lower, "tenant": tenant_slug}
    access_token = create_access_token(token_data)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        tenant_slug=tenant_slug,
        api_key=api_key,
    )


# ----------------- Me -----------------


@router.get("/me", response_model=MeResponse)
def me(
    current_user: Dict[str, Any] = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    email = current_user["email"]
    tenant_slug = current_user["tenant_slug"]

    tenant = session.exec(
        select(Tenant).where(Tenant.slug == tenant_slug)
    ).first()

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    needs_setup = not (
        (tenant.business_name or "").strip()
        and (tenant.booking_link or "").strip()
        and (tenant.review_google_url or "").strip()
        and (tenant.office_sms_to or "").strip()
        and (tenant.office_email_to or "").strip()
    )

    return MeResponse(
        email=email,
        tenant_slug=tenant_slug,
        needs_setup=needs_setup,
        business_name=tenant.business_name,
        booking_link=tenant.booking_link,
        review_google_url=tenant.review_google_url,
        office_sms_to=tenant.office_sms_to,
        office_email_to=tenant.office_email_to,
    )
