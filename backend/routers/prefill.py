"""
Prefill Router — exposes the prefill service as an API endpoint.
"""

from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Request, HTTPException

from services.prefill_service import compute_prefill

router = APIRouter()


class PrefillRequest(BaseModel):
    client_id: str
    symbol: str
    direction: str = "BUY"
    quantity: Optional[int] = None
    urgency: Optional[int] = None          # 0-100, None = auto-compute
    risk_aversion: Optional[int] = None    # 0-100, None = use client default
    order_notes: Optional[str] = None      # free-text for NLP parsing


class PrefillResponse(BaseModel):
    suggestions: dict
    explanations: dict
    confidence: dict
    urgency_score: int
    computed_urgency: int
    scenario_tag: str
    scenario_label: str
    why_not: dict


@router.post("/", response_model=PrefillResponse)
async def get_prefill(req: PrefillRequest, request: Request):
    """
    Given contextual inputs, return intelligent suggestions for all order
    parameters, including urgency score, scenario detection, and why-not
    explanations for alternative algos.
    """
    market_service = request.app.state.market_service

    md = market_service.get_symbol_data(req.symbol)
    if not md:
        raise HTTPException(status_code=404, detail=f"No market data for {req.symbol}")

    result = compute_prefill(
        client_id=req.client_id,
        symbol=req.symbol,
        direction=req.direction,
        quantity=req.quantity,
        market_data=md,
        urgency_override=req.urgency,
        risk_aversion_override=req.risk_aversion,
        order_notes_input=req.order_notes,
    )
    return result
