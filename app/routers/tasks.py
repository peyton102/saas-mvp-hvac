from fastapi import APIRouter
from app.services.reminders import send_due_reminders

router = APIRouter(tags=["tasks"])

@router.post("/tasks/send-reminders")
def tasks_send_reminders(look_back_minutes: int | None = None):
    """
    Finds due reminders and sends them (respects DRY_RUN_SMS in config).
    Optional: look_back_minutes to catch just-became-due items after a cold start.
    """
    results = send_due_reminders(look_back_minutes=look_back_minutes)
    return {"sent": len(results), "items": results}
