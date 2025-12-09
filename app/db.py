from sqlmodel import SQLModel, create_engine, Session
import os
from pathlib import Path
from app import models  # ensures Lead is registered before create_all()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/app.db")

# SQLite needs this connect arg and a real folder
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
if DATABASE_URL.startswith("sqlite"):
    Path("data").mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args=connect_args)

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