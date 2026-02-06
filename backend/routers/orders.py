import json
import uuid
from datetime import datetime, time as dtime
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from typing import Optional
from database import get_db

router = APIRouter()

MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)


# ── Request schemas ──

class AlgoParams(BaseModel):
    # POV
    target_participation_rate: Optional[float] = None  # 1-50%
    min_order_size: Optional[int] = None
    max_order_size: Optional[int] = None
    # VWAP
    volume_curve: Optional[str] = None  # Historical, Front-loaded, Back-loaded
    max_volume_pct: Optional[float] = None  # 1-50%
    # ICEBERG
    display_quantity: Optional[int] = None
    # Common
    aggression_level: Optional[str] = None  # Low, Medium, High


class CreateOrderRequest(BaseModel):
    client_id: str
    symbol: str
    direction: str  # BUY or SELL
    order_type: str  # MARKET, LIMIT, STOP_LOSS
    quantity: int
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    algo_type: Optional[str] = "NONE"  # NONE, POV, VWAP, ICEBERG
    algo_params: Optional[AlgoParams] = None
    account_id: Optional[str] = None
    start_time: Optional[str] = None  # HH:MM
    end_time: Optional[str] = None  # HH:MM
    tif: Optional[str] = "GFD"  # GFD, IOC, FOK, GTC, GTD
    urgency: Optional[int] = 50  # 0-100
    get_done: Optional[bool] = False
    capacity: Optional[str] = "AGENCY"  # AGENCY, PRINCIPAL, RISKLESS_PRINCIPAL, MIXED
    order_notes: Optional[str] = ""

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v):
        if v.upper() not in ("BUY", "SELL"):
            raise ValueError("Direction must be BUY or SELL")
        return v.upper()

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, v):
        if v.upper() not in ("MARKET", "LIMIT", "STOP_LOSS"):
            raise ValueError("Order type must be MARKET, LIMIT, or STOP_LOSS")
        return v.upper()

    @field_validator("algo_type")
    @classmethod
    def validate_algo_type(cls, v):
        if v and v.upper() not in ("NONE", "POV", "VWAP", "ICEBERG"):
            raise ValueError("Algo type must be NONE, POV, VWAP, or ICEBERG")
        return v.upper() if v else "NONE"

    @field_validator("tif")
    @classmethod
    def validate_tif(cls, v):
        valid = ("GFD", "IOC", "FOK", "GTC", "GTD")
        if v and v.upper() not in valid:
            raise ValueError(f"TIF must be one of {valid}")
        return v.upper() if v else "GFD"

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v):
        valid = ("AGENCY", "PRINCIPAL", "RISKLESS_PRINCIPAL", "MIXED")
        if v and v.upper() not in valid:
            raise ValueError(f"Capacity must be one of {valid}")
        return v.upper() if v else "AGENCY"

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v):
        if v is not None and not (0 <= v <= 100):
            raise ValueError("Urgency must be between 0 and 100")
        return v if v is not None else 50


class CancelOrderRequest(BaseModel):
    reason: Optional[str] = ""


class AmendOrderRequest(BaseModel):
    quantity: Optional[int] = None
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None


# ── Validation logic ──

def validate_order(req: CreateOrderRequest, request: Request) -> list[str]:
    """Validate order against business rules. Returns list of errors."""
    errors = []
    conn = get_db()
    try:
        # 1. Symbol existence
        inst = conn.execute(
            "SELECT * FROM instruments WHERE symbol = ? AND is_active = 1",
            (req.symbol.upper(),)
        ).fetchone()
        if not inst:
            errors.append(f"Symbol '{req.symbol}' not found or inactive")
            return errors
        inst = dict(inst)

        # 2. Client existence and active
        client = conn.execute(
            "SELECT * FROM clients WHERE client_id = ? AND is_active = 1",
            (req.client_id,)
        ).fetchone()
        if not client:
            errors.append(f"Client '{req.client_id}' not found or inactive")
            return errors
        client = dict(client)

        # 3. Restricted symbols
        restricted = [s.strip() for s in (client["restricted_symbols"] or "").split(",") if s.strip()]
        if req.symbol.upper() in restricted:
            errors.append(f"Client '{req.client_id}' is restricted from trading '{req.symbol}'")

        # 4. Quantity checks
        if req.quantity <= 0:
            errors.append("Quantity must be positive")
        if req.quantity > client["position_limit"]:
            errors.append(
                f"Order quantity ({req.quantity:,}) exceeds client position limit ({client['position_limit']:,})"
            )

        # 5. Limit price collar check (±5% from LTP)
        market_service = request.app.state.market_service
        md = market_service.get_symbol_data(req.symbol.upper())

        if req.order_type == "LIMIT":
            if req.limit_price is None:
                errors.append("Limit price required for LIMIT orders")
            elif md:
                ltp = md["ltp"]
                collar_low = ltp * 0.95
                collar_high = ltp * 1.05
                if not (collar_low <= req.limit_price <= collar_high):
                    errors.append(
                        f"Limit price {req.limit_price} is outside ±5% collar "
                        f"[{collar_low:.2f} - {collar_high:.2f}] from LTP {ltp:.2f}"
                    )

        if req.order_type == "STOP_LOSS" and req.stop_price is None:
            errors.append("Stop price required for STOP_LOSS orders")

        # 6. Credit limit check (approximate notional)
        if md:
            notional = req.quantity * md["ltp"]
            if notional > client["credit_limit"]:
                errors.append(
                    f"Estimated notional (₹{notional:,.0f}) exceeds credit limit (₹{client['credit_limit']:,.0f})"
                )

        # 7. Time window validation
        if req.start_time and req.end_time:
            try:
                sp = req.start_time.split(":")
                ep = req.end_time.split(":")
                start_m = int(sp[0]) * 60 + int(sp[1])
                end_m = int(ep[0]) * 60 + int(ep[1])
                if start_m >= end_m:
                    errors.append("Start time must be before end time")
            except (ValueError, IndexError):
                errors.append("Invalid time format. Use HH:MM")

        # 8. Algo-specific validation
        if req.algo_type in ("POV", "VWAP", "ICEBERG") and not req.start_time:
            errors.append(f"Start time required for {req.algo_type} algo")
        if req.algo_type in ("POV", "VWAP", "ICEBERG") and not req.end_time:
            errors.append(f"End time required for {req.algo_type} algo")

        if req.algo_params:
            if req.algo_type == "POV":
                rate = req.algo_params.target_participation_rate
                if rate is not None and not (1 <= rate <= 50):
                    errors.append("POV target participation rate must be 1-50%")
            elif req.algo_type == "VWAP":
                max_vol = req.algo_params.max_volume_pct
                if max_vol is not None and not (1 <= max_vol <= 50):
                    errors.append("VWAP max volume % must be 1-50%")
            elif req.algo_type == "ICEBERG":
                disp = req.algo_params.display_quantity
                if disp is not None and disp >= req.quantity:
                    errors.append("ICEBERG display quantity must be less than total order size")
                if disp is not None and disp <= 0:
                    errors.append("ICEBERG display quantity must be positive")

    finally:
        conn.close()

    return errors


# ── Endpoints ──

@router.post("/")
async def create_order(req: CreateOrderRequest, request: Request):
    """Create and validate a new order."""
    # Validate
    errors = validate_order(req, request)
    if errors:
        raise HTTPException(400, detail={"errors": errors})

    order_id = str(uuid.uuid4())[:12].upper()
    algo_params_json = json.dumps(req.algo_params.model_dump() if req.algo_params else {})

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO orders (order_id, client_id, account_id, symbol, direction, order_type,
                quantity, limit_price, stop_price, algo_type, algo_params,
                start_time, end_time, tif, urgency, get_done, capacity,
                order_notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WORKING')
        """, (
            order_id, req.client_id, req.account_id, req.symbol.upper(), req.direction,
            req.order_type, req.quantity, req.limit_price, req.stop_price,
            req.algo_type, algo_params_json, req.start_time, req.end_time,
            req.tif, req.urgency, 1 if req.get_done else 0, req.capacity,
            req.order_notes,
        ))

        # Audit trail
        conn.execute(
            "INSERT INTO order_history (order_id, action, details) VALUES (?, ?, ?)",
            (order_id, "CREATED", json.dumps(req.model_dump())),
        )

        conn.commit()

        # Fetch and return the created order
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.get("/")
async def list_orders(status: str = None, client_id: str = None, symbol: str = None):
    """List orders with optional filters."""
    conn = get_db()
    try:
        query = "SELECT * FROM orders WHERE parent_order_id IS NULL"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status.upper())
        if client_id:
            query += " AND client_id = ?"
            params.append(client_id)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())

        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{order_id}")
async def get_order(order_id: str):
    """Get order details including executions."""
    conn = get_db()
    try:
        order = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not order:
            raise HTTPException(404, "Order not found")

        executions = conn.execute(
            "SELECT * FROM executions WHERE order_id = ? ORDER BY executed_at DESC",
            (order_id,)
        ).fetchall()

        history = conn.execute(
            "SELECT * FROM order_history WHERE order_id = ? ORDER BY created_at DESC",
            (order_id,)
        ).fetchall()

        child_orders = conn.execute(
            "SELECT * FROM orders WHERE parent_order_id = ? ORDER BY created_at DESC",
            (order_id,)
        ).fetchall()

        return {
            "order": dict(order),
            "executions": [dict(e) for e in executions],
            "history": [dict(h) for h in history],
            "child_orders": [dict(c) for c in child_orders],
        }
    finally:
        conn.close()


@router.post("/{order_id}/cancel")
async def cancel_order(order_id: str, req: CancelOrderRequest):
    """Cancel an active order."""
    conn = get_db()
    try:
        order = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not order:
            raise HTTPException(404, "Order not found")

        order = dict(order)
        if order["status"] in ("FILLED", "CANCELLED", "REJECTED"):
            raise HTTPException(400, f"Cannot cancel order in {order['status']} status")

        conn.execute(
            "UPDATE orders SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP WHERE order_id = ?",
            (order_id,),
        )
        conn.execute(
            "INSERT INTO order_history (order_id, action, details) VALUES (?, ?, ?)",
            (order_id, "CANCELLED", json.dumps({"reason": req.reason})),
        )

        # Cancel child orders too
        conn.execute(
            """UPDATE orders SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP
               WHERE parent_order_id = ? AND status NOT IN ('FILLED', 'CANCELLED')""",
            (order_id,),
        )

        conn.commit()
        return {"message": "Order cancelled", "order_id": order_id}
    finally:
        conn.close()


@router.post("/{order_id}/amend")
async def amend_order(order_id: str, req: AmendOrderRequest):
    """Amend an active order's quantity or price."""
    conn = get_db()
    try:
        order = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not order:
            raise HTTPException(404, "Order not found")

        order = dict(order)
        if order["status"] in ("FILLED", "CANCELLED", "REJECTED"):
            raise HTTPException(400, f"Cannot amend order in {order['status']} status")

        updates = []
        params = []
        details = {}

        if req.quantity is not None:
            if req.quantity <= order["filled_quantity"]:
                raise HTTPException(400, "New quantity must be greater than filled quantity")
            updates.append("quantity = ?")
            params.append(req.quantity)
            details["quantity"] = f"{order['quantity']} → {req.quantity}"

        if req.limit_price is not None:
            updates.append("limit_price = ?")
            params.append(req.limit_price)
            details["limit_price"] = f"{order['limit_price']} → {req.limit_price}"

        if req.stop_price is not None:
            updates.append("stop_price = ?")
            params.append(req.stop_price)
            details["stop_price"] = f"{order['stop_price']} → {req.stop_price}"

        if not updates:
            raise HTTPException(400, "No amendments provided")

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(order_id)

        conn.execute(
            f"UPDATE orders SET {', '.join(updates)} WHERE order_id = ?", params
        )
        conn.execute(
            "INSERT INTO order_history (order_id, action, details) VALUES (?, ?, ?)",
            (order_id, "AMENDED", json.dumps(details)),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.get("/{order_id}/executions")
async def get_executions(order_id: str):
    """Get all executions for an order."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM executions WHERE order_id = ? ORDER BY executed_at DESC",
            (order_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
