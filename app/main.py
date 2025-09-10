# app/main.py
from fastapi import FastAPI
from app import config
from app.routers.leads import router as leads_router

app = FastAPI(title="HVAC SaaS Bot (MVP)", version="0.1.0")

@app.get("/")
def root():
    return {"ok": True, "msg": "root alive"}

@app.get("/health")
def health():
    return {"ok": True, "env": config.ENV}

# plug in the leads endpoints (we'll add more routers later)
app.include_router(leads_router)
