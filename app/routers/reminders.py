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
