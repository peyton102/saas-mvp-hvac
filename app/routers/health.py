from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health():
    return {"ok": True}

# ✨ Make include_router(health.router) work even if 'health' is imported as a function
health.router = router  # type: ignore[attr-defined]
