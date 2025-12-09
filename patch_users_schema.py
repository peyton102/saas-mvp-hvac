# patch_users_schema.py
from sqlmodel import Session
from sqlalchemy import inspect, text

from app.db import engine


def main() -> None:
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("users")}
    print("Existing columns on users:", cols)

    with Session(engine) as session:
        # Ensure password_hash column exists
        if "password_hash" not in cols:
            print("Adding column: password_hash")
            session.exec(text("ALTER TABLE users ADD COLUMN password_hash TEXT"))
        else:
            print("password_hash already exists, skipping.")

        # Ensure tenant_slug column exists
        if "tenant_slug" not in cols:
            print("Adding column: tenant_slug")
            session.exec(text("ALTER TABLE users ADD COLUMN tenant_slug TEXT"))
        else:
            print("tenant_slug already exists, skipping.")

        # Ensure is_owner column exists
        if "is_owner" not in cols:
            print("Adding column: is_owner")
            session.exec(
                text("ALTER TABLE users ADD COLUMN is_owner INTEGER DEFAULT 0")
            )
        else:
            print("is_owner already exists, skipping.")

        session.commit()

    print("Done patching users table.")


if __name__ == "__main__":
    main()
