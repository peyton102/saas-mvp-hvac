from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text
import os
from app import models  # ensures models are registered before create_all()

# Render (and some older Heroku configs) emit "postgres://" which SQLAlchemy 1.4+
# requires as "postgresql://".
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def run_startup_migrations() -> None:
    migrations = [
        ("sp_tenant_twilio_number", "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS twilio_number TEXT DEFAULT ''"),
        ("sp_lead_service_urgency", "ALTER TABLE lead ADD COLUMN IF NOT EXISTS service_urgency TEXT"),
        ("sp_lead_notes", "ALTER TABLE lead ADD COLUMN IF NOT EXISTS notes TEXT"),
        ("sp_tenant_gcal_refresh_token", "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS gcal_refresh_token TEXT"),
        ("sp_tenant_gcal_access_token", "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS gcal_access_token TEXT"),
        ("sp_tenant_gcal_token_expires_at", "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS gcal_token_expires_at BIGINT"),
        ("sp_tenant_gcal_calendar_id", "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS gcal_calendar_id TEXT DEFAULT 'primary'"),
        ("sp_tenant_gcal_sync_token", "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS gcal_sync_token TEXT"),
        ("sp_tenant_gcal_last_synced_at", "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS gcal_last_synced_at TIMESTAMP"),
        ("sp_booking_gcal_event_id", "ALTER TABLE booking ADD COLUMN IF NOT EXISTS gcal_event_id TEXT"),
        ("sp_tenant_booking_days",  "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS booking_days TEXT"),
        ("sp_tenant_booking_start", "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS booking_start TEXT"),
        ("sp_tenant_booking_end",   "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS booking_end TEXT"),
        ("sp_tenant_slot_minutes",  "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS slot_minutes INTEGER"),
        ("sp_lead_job_won",      "ALTER TABLE lead ADD COLUMN IF NOT EXISTS job_won BOOLEAN DEFAULT FALSE"),
        ("sp_lead_job_value",    "ALTER TABLE lead ADD COLUMN IF NOT EXISTS job_value NUMERIC"),
        ("sp_booking_job_value", "ALTER TABLE booking ADD COLUMN IF NOT EXISTS job_value NUMERIC"),
        ("sp_tenant_features",   "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS features TEXT"),
        ("sp_tenant_is_admin",   "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"),
        ("sp_lead_service_address", "ALTER TABLE lead ADD COLUMN IF NOT EXISTS service_address TEXT"),
    ]
    with Session(engine) as session:
        for sp, ddl in migrations:
            try:
                session.exec(text(f"SAVEPOINT {sp}"))
                session.exec(text(ddl))
                session.exec(text(f"RELEASE SAVEPOINT {sp}"))
            except Exception:
                session.exec(text(f"ROLLBACK TO SAVEPOINT {sp}"))
        session.commit()

def get_session():
    with Session(engine) as session:
        yield session

def get_db(): yield from get_session()

try:
    from app import models_reviews as _models_reviews  # noqa: F401
except Exception:
    pass
