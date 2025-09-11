from fastapi import FastAPI
from app import config
from app.routers.leads import router as leads_router
from app.routers.voice import router as voice_router   # <-- make sure this import exists

app = FastAPI(title="HVAC SaaS Bot (MVP)", version="0.1.0")

@app.get("/")
def root():
    return {"ok": True, "msg": "root alive"}

@app.get("/health")
def health():
    return {"ok": True, "env": config.ENV}

app.include_router(leads_router)
app.include_router(voice_router)  # <-- and this line must be here
