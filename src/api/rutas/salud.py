from fastapi import APIRouter

from src.db.store import get_conn

router = APIRouter(tags=["Salud"])


@router.get("/salud")
def salud() -> dict:
    try:
        get_conn().execute("SELECT 1").fetchone()
        return {"ok": True, "db": "conectada"}
    except Exception as exc:
        return {"ok": False, "db": str(exc)}
