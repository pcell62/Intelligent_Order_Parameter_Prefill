"""
Accounts router — manage client trading accounts.
"""

from fastapi import APIRouter, HTTPException
from database import get_db

router = APIRouter()


@router.get("/")
async def list_accounts(client_id: str = None):
    """List accounts, optionally filtered by client_id."""
    conn = get_db()
    try:
        if client_id:
            rows = conn.execute(
                "SELECT * FROM accounts WHERE client_id = ? AND is_active = 1 ORDER BY is_default DESC, account_name",
                (client_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM accounts WHERE is_active = 1 ORDER BY client_id, is_default DESC, account_name"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{account_id}")
async def get_account(account_id: str):
    """Get a single account by ID."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Account not found")
        return dict(row)
    finally:
        conn.close()
