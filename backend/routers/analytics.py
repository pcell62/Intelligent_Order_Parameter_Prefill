"""
Analytics router – read-only access to every DB table,
plus OHLC candlestick aggregation from the market_data table.
"""

import sqlite3
import math
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter()
DB_PATH = "trading.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────
#  Generic table endpoints
# ──────────────────────────────────────────────

@router.get("/instruments")
async def get_instruments():
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM instruments ORDER BY symbol").fetchall()
    return [dict(r) for r in rows]


@router.get("/clients")
async def get_clients():
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY client_id").fetchall()
    return [dict(r) for r in rows]


@router.get("/orders")
async def get_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    offset = (page - 1) * page_size
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
    return {
        "data": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/executions")
async def get_executions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    offset = (page - 1) * page_size
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM executions ORDER BY executed_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
    return {
        "data": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/market-data")
async def get_market_data(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    symbol: Optional[str] = None,
):
    offset = (page - 1) * page_size
    where = ""
    params: list = []
    if symbol:
        where = "WHERE symbol = ?"
        params.append(symbol)

    with _conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM market_data {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM market_data {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
    return {
        "data": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/order-history")
async def get_order_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    offset = (page - 1) * page_size
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM order_history").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM order_history ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
    return {
        "data": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


# ──────────────────────────────────────────────
#  Candlestick (OHLC) aggregation
# ──────────────────────────────────────────────

@router.get("/candlesticks/{symbol}")
async def get_candlesticks(
    symbol: str,
    interval: str = Query("1m", regex="^(1m|5m|15m)$"),
):
    """
    Aggregates market_data rows into OHLC candlestick bars.
    interval: '1m' | '5m' | '15m'
    Uses SQLite's strftime to bucket by minute intervals.
    """
    interval_seconds = {"1m": 60, "5m": 300, "15m": 900}[interval]

    query = """
        SELECT
            (CAST(strftime('%s', timestamp) AS INTEGER) / ?) * ? AS bucket,
            MIN(ltp)  AS low,
            MAX(ltp)  AS high,
            SUM(volume) AS volume,
            timestamp,
            ltp
        FROM market_data
        WHERE symbol = ?
        ORDER BY timestamp ASC
    """

    with _conn() as conn:
        rows = conn.execute(query, (interval_seconds, interval_seconds, symbol)).fetchall()

    if not rows:
        return []

    # Group into buckets for proper OHLC (SQLite aggregation doesn't give
    # first/last per group easily, so we do it in Python)
    buckets: dict[int, dict] = {}
    for row in rows:
        b = row["bucket"]
        ltp = row["ltp"]
        vol = row["volume"]
        if b not in buckets:
            buckets[b] = {
                "time": b,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": vol,
            }
        else:
            buckets[b]["high"] = max(buckets[b]["high"], ltp)
            buckets[b]["low"] = min(buckets[b]["low"], ltp)
            buckets[b]["close"] = ltp  # last value in chronological order
            buckets[b]["volume"] += vol

    # Return sorted by time ascending (lightweight-charts expects this)
    return sorted(buckets.values(), key=lambda c: c["time"])


@router.get("/symbols")
async def get_symbols():
    """Return distinct symbols present in market_data for the chart selector."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM market_data ORDER BY symbol"
        ).fetchall()
    return [r["symbol"] for r in rows]
