# app/routers/tasks.py
"""
Legacy tasks router.

All actual task-style endpoints now live in:
- app.routers.reviews   -> /jobs/complete (review requests)
- app.routers.reminders -> /tasks/send-reminders (appointment reminders)

This file is intentionally empty of routes, so it won't
conflict with /jobs/complete or /debug/reviews anymore.
"""

from fastapi import APIRouter

router = APIRouter(prefix="", tags=["tasks"])
# No routes defined here on purpose.
