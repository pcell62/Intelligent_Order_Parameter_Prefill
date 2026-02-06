from fastapi import APIRouter, HTTPException
from database import get_db

router = APIRouter()


@router.get("/")
async def list_clients():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM clients WHERE is_active = 1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{client_id}")
async def get_client(client_id: str):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM clients WHERE client_id = ?", (client_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Client not found")
        return dict(row)
    finally:
        conn.close()
