from fastapi import FastAPI
from app import config
from app.routers.leads import router as leads_router
from app.routers.voice import router as voice_router   # <-- make sure this import exists
from app.routers.calendly import router as calendly_router
from app.routers.reminders import router as reminders_router
from app.routers.tasks import router as tasks_router
from app.routers.reviews import router as reviews_router
from app.routers.oauth_google import router as google_oauth_router
from app.routers.availability import router as availability_router
from app.routers.bookings import router as bookings_router
from app.routers.public import router as public_router
from app.db import create_db_and_tables
from app import models

app = FastAPI(title="HVAC SaaS Bot (MVP)", version="0.1.0")

@app.get("/")
def root():
    return {"ok": True, "msg": "root alive"}

@app.get("/health")
def health():
    return {"ok": True, "env": config.ENV}

app.include_router(leads_router)
app.include_router(voice_router)
app.include_router(calendly_router)
app.include_router(reminders_router)
app.include_router(reviews_router)
app.include_router(google_oauth_router)
app.include_router(availability_router)
app.include_router(tasks_router)
app.include_router(bookings_router)
app.include_router(public_router)
@app.on_event("startup")
def on_startup():
    create_db_and_tables()

