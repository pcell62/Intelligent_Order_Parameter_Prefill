import asyncio
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.get("/")
async def get_market_data(request: Request):
    """Get current market data snapshot for all instruments."""
    market_service = request.app.state.market_service
    return market_service.get_snapshot()


@router.get("/{symbol}")
async def get_symbol_market_data(symbol: str, request: Request):
    """Get current market data for a specific symbol."""
    market_service = request.app.state.market_service
    data = market_service.get_symbol_data(symbol.upper())
    if not data:
        return {"error": f"Symbol '{symbol}' not found"}
    return data


@router.websocket("/ws")
async def market_data_ws(websocket: WebSocket):
    """WebSocket endpoint for streaming market data."""
    await websocket.accept()
    market_service = websocket.app.state.market_service
    queue = market_service.subscribe()
    try:
        while True:
            msg = await queue.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        market_service.unsubscribe(queue)


@router.websocket("/ws/orders")
async def order_updates_ws(websocket: WebSocket):
    """WebSocket endpoint for streaming order execution updates."""
    await websocket.accept()
    execution_engine = websocket.app.state.execution_engine
    queue = execution_engine.subscribe()
    try:
        while True:
            msg = await queue.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        execution_engine.unsubscribe(queue)
