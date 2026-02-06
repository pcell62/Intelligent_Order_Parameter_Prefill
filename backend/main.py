import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routers import clients, instruments, orders, market_data, prefill, analytics, accounts
from services.market_data_service import MarketDataService
from services.execution_engine import ExecutionEngine

load_dotenv()

market_service: MarketDataService | None = None
execution_engine: ExecutionEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global market_service, execution_engine

    # Startup
    init_db()
    market_service = MarketDataService()
    execution_engine = ExecutionEngine(market_service)

    app.state.market_service = market_service
    app.state.execution_engine = execution_engine

    # Start background tasks
    market_task = asyncio.create_task(market_service.run())
    execution_task = asyncio.create_task(execution_engine.run())

    yield

    # Shutdown
    market_service.stop()
    execution_engine.stop()
    market_task.cancel()
    execution_task.cancel()
    try:
        await market_task
    except asyncio.CancelledError:
        pass
    try:
        await execution_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Intelligent Order Parameter Prefill - Trading System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clients.router, prefix="/api/clients", tags=["Clients"])
app.include_router(instruments.router, prefix="/api/instruments", tags=["Instruments"])
app.include_router(orders.router, prefix="/api/orders", tags=["Orders"])
app.include_router(accounts.router, prefix="/api/accounts", tags=["Accounts"])
app.include_router(prefill.router, prefix="/api/prefill", tags=["Prefill"])
app.include_router(market_data.router, prefix="/api/market-data", tags=["Market Data"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}
