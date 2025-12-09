# scripts/debug_sqlmodel_bookings.py

from sqlmodel import select
from app.db import get_session
from app.models import Booking as BookingModel


def main():
    gen = get_session()
    session = next(gen)

    rows = session.exec(select(BookingModel)).all()
    print("TOTAL BookingModel rows:", len(rows))
    for b in rows:
        # adjust attributes if your model uses different names
        print(
            f"id={b.id}  tenant_id={b.tenant_id!r}  "
            f"name={b.name!r}  start={b.start!r}  source={getattr(b, 'source', None)!r}"
        )

    session.close()


if __name__ == "__main__":
    main()
