# scripts/init_db.py

from sqlmodel import SQLModel
from sqlalchemy import inspect

from app.db import engine
import app.models  # make sure ALL models are imported / registered

# Some projects also use a separate SQLAlchemy Base for auth models
try:
    from app.models import Base  # if you have a declarative Base
except ImportError:
    Base = None


def main() -> None:
    print("Using engine:", engine.url)

    # Create all SQLModel tables (tenants, bookings, etc.)
    print("Creating SQLModel tables...")
    SQLModel.metadata.create_all(engine)

    # If there is a separate Base (for User, etc.), create those too
    if Base is not None:
        print("Creating Base tables...")
        Base.metadata.create_all(engine)

    # Show what tables actually exist
    insp = inspect(engine)
    print("Tables now in DB:", insp.get_table_names())


if __name__ == "__main__":
    main()
