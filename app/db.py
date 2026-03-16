from sqlmodel import SQLModel, create_engine, Session
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

def get_session():
    with Session(engine) as session:
        yield session

def get_db(): yield from get_session()

try:
    from app import models_reviews as _models_reviews  # noqa: F401
except Exception:
    pass
