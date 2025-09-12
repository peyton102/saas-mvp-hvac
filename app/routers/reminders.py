# app/routers/reminders.py
from fastapi import APIRouter
from app.services.reminders import preview_due_reminders

router = APIRouter(prefix="", tags=["reminders"])

@router.get("/debug/run-reminders")
def run_reminders_preview(look_back_minutes: int | None = None):
    """
    Preview which reminders would go out if we ran the job now.
    No SMS is sent here—just logs + JSON result.
    """
    due = preview_due_reminders(look_back_minutes=look_back_minutes)
    # Print DRY-RUN lines so you can see them in Render logs
    for d in due:
        print(f"[REMINDER DRY RUN][{d['offset']}] to {d['phone']}: {d['message']}")
    return {"count": len(due), "items": due}
from app.services.sms import send_sms
from app import storage

@router.post("/tasks/send-reminders")
def send_reminders(look_back_minutes: int | None = None):
    """
    Send real reminders for bookings that are due now (respects DRY_RUN).
    De-duped by (phone, start_time_local, offset).
    """
    due = preview_due_reminders(look_back_minutes=look_back_minutes)
    sent, skipped = [], []

    for d in due:
        phone = d["phone"]
        start_local = d["start_time_local"]
        offset = d["offset"]

        if storage.reminder_already_sent(phone, start_local, offset):
            skipped.append({**d, "reason": "already_sent"})
            continue

        ok = send_sms(phone, d["message"])
        if ok:
            storage.save_reminder_sent(phone, start_local, offset)
            print(f"[REMINDER SENT][{offset}] to {phone}")
            sent.append(d)
        else:
            print(f"[REMINDER FAILED][{offset}] to {phone}")
            skipped.append({**d, "reason": "send_failed"})

    return {"sent": len(sent), "skipped": len(skipped), "sent_items": sent, "skipped_items": skipped}

@router.get("/debug/reminders-sent")
def debug_reminders_sent(limit: int = 20):
    items = storage.read_reminders_sent(limit)
    return {"count": len(items), "items": items}
