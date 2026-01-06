# app/routers/auth.py
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import hashlib
import secrets

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
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    return hash_password(plain_password) == hashed_password


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

    # --- invite required ---
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

    # --- continue normal signup below ---



    """
    Signup:
    - Uses Tenant as the account (no separate users table).
    - Enforces unique slug (business_name) and email on Tenant.
    - Stores password_hash on tenant row (password_hash column).
    - Creates ApiKey row linked to Tenant.id.
    - Returns JWT + api_key + tenant_slug.
    """

    # 1) slug from business name
    slug = slugify(payload.business_name)

    # 2) check if slug already taken (Tenant.slug)
    existing_slug = session.exec(
        select(Tenant).where(Tenant.slug == slug)
    ).first()
    if existing_slug:
        raise HTTPException(status_code=400, detail="Business name is already taken")

    # 3) check if email already used (Tenant.email)
    email_lower = payload.email.lower().strip()
    existing_email = session.exec(
        select(Tenant).where(Tenant.email == email_lower)
    ).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    # 4) ensure tenant table has password_hash column (safe to run repeatedly)
    try:
        session.exec(text("ALTER TABLE tenant ADD COLUMN password_hash TEXT"))
    except Exception:
        # column already exists, ignore
        pass

    now = datetime.now(timezone.utc)
    booking_link_default = getattr(config, "BOOKING_LINK", "") or ""

    # 5) create Tenant row via SQLModel
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

    # 6) set password_hash on tenant via raw SQL (even if model doesn't have the field)
    password_hash = hash_password(payload.password)
    session.exec(
        text("UPDATE tenant SET password_hash = :pwd WHERE id = :tid")
        .bindparams(pwd=password_hash, tid=tenant.id)
    )

    # 7) create ApiKey row (store the raw key in hashed_key for now)
    api_key_plain = secrets.token_hex(16)
    api_key_row = ApiKey(
        tenant_id=tenant.id,
        hashed_key=api_key_plain,
        is_active=True,
    )
    session.add(api_key_row)
    result = session.exec(text("""
        UPDATE invite_code
        SET used_at = :used_at
        WHERE code = :code AND used_at IS NULL
    """).bindparams(
        used_at=datetime.now(timezone.utc).isoformat(),
        code=code
    ))

    try:
        if result.rowcount == 0:
            raise HTTPException(status_code=403, detail="Invite already used")
    except Exception:
        pass

    session.commit()

    # 8) build JWT
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

    # make sure password_hash column exists (no-op if already there)
    try:
        session.exec(text("ALTER TABLE tenant ADD COLUMN password_hash TEXT"))
    except Exception:
        pass

    # 1) fetch tenant + first active api key
    stmt = text(
        """
        SELECT
          t.id AS tenant_id,
          t.email AS email,
          t.password_hash AS password_hash,
          t.slug AS tenant_slug,
          ak.hashed_key AS api_key
        FROM tenant t
        LEFT JOIN api_key ak ON ak.tenant_id = t.id AND ak.is_active = 1
        WHERE t.email = :email
        LIMIT 1
        """
    ).bindparams(email=email_lower)

    row = session.exec(stmt).first()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    data = row_to_dict(row)

    if not verify_password(payload.password, data.get("password_hash")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    tenant_slug = data["tenant_slug"]
    api_key = data.get("api_key") or ""

    # 3) build JWT
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
