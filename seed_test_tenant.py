# seed_test_tenant.py

from sqlmodel import Session, select
from app.db import engine
from app.models import Tenant


def main():
    with Session(engine) as session:
        # check if tenant already exists
        existing = session.exec(
            select(Tenant).where(Tenant.slug == "test-tenant")
        ).first()

        if existing:
            print("[SKIP] Tenant 'test-tenant' already exists.")
            print(existing)
            return

        # Create a basic tenant record
        t = Tenant(
            slug="test-tenant",
            business_name="Test HVAC Pro",
            website="https://testhvac.com",
            address=None,
            email=None,
            phone=None,
            booking_link=None,
            office_sms_to=None,
            office_email_to=None,
            google_place_id=None,
            review_google_url=None,
        )

        session.add(t)
        session.commit()
        session.refresh(t)

        print("[ADDED] Tenant created:", t)


if __name__ == "__main__":
    main()
