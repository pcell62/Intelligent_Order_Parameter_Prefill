from fastapi import APIRouter, HTTPException
from database import get_db

router = APIRouter()


@router.get("/")
async def list_instruments():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM instruments WHERE is_active = 1 ORDER BY symbol"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{symbol}")
async def get_instrument(symbol: str):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM instruments WHERE symbol = ?", (symbol.upper(),)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Instrument not found")
        return dict(row)
    finally:
        conn.close()
