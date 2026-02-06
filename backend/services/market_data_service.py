"""
Market Data Service
Simulates realistic intraday price movements using geometric Brownian motion.
Maintains a live in-memory order book per symbol and streams updates via WebSocket.
"""

import asyncio
import math
import random
import time
import json
from datetime import datetime, time as dtime
from typing import Any
from database import get_db

# Indian market hours (NSE)
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)

# Base prices for seeded instruments
BASE_PRICES: dict[str, float] = {
    "RELIANCE": 2450.00,
    "TCS": 3820.00,
    "INFY": 1580.00,
    "HDFCBANK": 1720.00,
    "ICICIBANK": 1150.00,
    "SBIN": 780.00,
    "BHARTIARTL": 1620.00,
    "ITC": 452.00,
    "TATAMOTORS": 710.00,
    "WIPRO": 485.00,
}

# Volatility profiles (annualized %)
VOLATILITY: dict[str, float] = {
    "RELIANCE": 1.8,
    "TCS": 1.5,
    "INFY": 2.0,
    "HDFCBANK": 1.6,
    "ICICIBANK": 2.2,
    "SBIN": 2.8,
    "BHARTIARTL": 1.9,
    "ITC": 1.3,
    "TATAMOTORS": 3.5,
    "WIPRO": 2.1,
}


class MarketDataService:
    """Generates and broadcasts simulated market data."""

    def __init__(self):
        self._running = False
        self._subscribers: list[asyncio.Queue] = []

        # Current market state per symbol
        self.prices: dict[str, dict[str, Any]] = {}
        self._init_prices()

    def _init_prices(self):
        """Initialize market prices from base prices."""
        for symbol, base in BASE_PRICES.items():
            spread_pct = random.uniform(0.01, 0.05) / 100
            spread = round(base * spread_pct, 2)
            vol = VOLATILITY.get(symbol, 2.0)

            self.prices[symbol] = {
                "symbol": symbol,
                "bid": round(base - spread / 2, 2),
                "ask": round(base + spread / 2, 2),
                "ltp": base,
                "volume": 0,
                "day_volume": 0,
                "volatility": vol,
                "avg_trade_size": random.randint(500, 15000),
                "open": base,
                "high": base,
                "low": base,
                "change_pct": 0.0,
            }

    def _minutes_to_close(self) -> int:
        """Calculate minutes remaining until market close."""
        now = datetime.now().time()
        if now >= MARKET_CLOSE:
            return 0
        if now < MARKET_OPEN:
            # Before market open, return full session
            close_mins = MARKET_CLOSE.hour * 60 + MARKET_CLOSE.minute
            open_mins = MARKET_OPEN.hour * 60 + MARKET_OPEN.minute
            return close_mins - open_mins
        now_mins = now.hour * 60 + now.minute
        close_mins = MARKET_CLOSE.hour * 60 + MARKET_CLOSE.minute
        return max(0, close_mins - now_mins)

    def _simulate_tick(self, symbol: str):
        """Generate one price tick using geometric Brownian motion."""
        data = self.prices[symbol]
        vol = data["volatility"] / 100  # Convert from percentage
        dt = 1 / (6.25 * 60 * 60)  # 1 second in trading day fraction (6.25 hr session)

        # GBM: dS = S * (mu*dt + sigma*sqrt(dt)*Z)
        mu = random.uniform(-0.0001, 0.0001)  # Small drift
        z = random.gauss(0, 1)
        price_change = data["ltp"] * (mu * dt + vol * math.sqrt(dt) * z)

        new_ltp = round(max(0.05, data["ltp"] + price_change), 2)

        # Realistic bid-ask spread (wider for volatile stocks)
        spread_bps = max(1, int(vol * 500 + random.uniform(-2, 2)))
        spread = round(new_ltp * spread_bps / 10000, 2)
        spread = max(0.05, spread)  # Minimum tick size

        new_bid = round(new_ltp - spread / 2, 2)
        new_ask = round(new_ltp + spread / 2, 2)

        # Volume tick
        tick_volume = random.randint(50, int(data["avg_trade_size"] * 0.3))
        data["day_volume"] += tick_volume

        # Update OHLC
        data["high"] = max(data["high"], new_ltp)
        data["low"] = min(data["low"], new_ltp)
        data["change_pct"] = round((new_ltp - data["open"]) / data["open"] * 100, 3)

        data["bid"] = new_bid
        data["ask"] = new_ask
        data["ltp"] = new_ltp
        data["volume"] = tick_volume

        # Recalculate rolling volatility with some noise
        data["volatility"] = round(
            data["volatility"] + random.uniform(-0.02, 0.02), 3
        )
        data["volatility"] = max(0.5, min(5.0, data["volatility"]))

    def get_snapshot(self) -> list[dict]:
        """Return current market data for all symbols."""
        minutes_to_close = self._minutes_to_close()
        result = []
        for symbol, data in self.prices.items():
            result.append({
                **data,
                "time_to_close": minutes_to_close,
                "spread": round(data["ask"] - data["bid"], 2),
                "spread_bps": round((data["ask"] - data["bid"]) / data["ltp"] * 10000, 1),
                "timestamp": datetime.now().isoformat(),
            })
        return result

    def get_symbol_data(self, symbol: str) -> dict | None:
        """Return current market data for a specific symbol."""
        if symbol not in self.prices:
            return None
        data = self.prices[symbol]
        return {
            **data,
            "time_to_close": self._minutes_to_close(),
            "spread": round(data["ask"] - data["bid"], 2),
            "spread_bps": round((data["ask"] - data["bid"]) / data["ltp"] * 10000, 1),
            "timestamp": datetime.now().isoformat(),
        }

    def subscribe(self) -> asyncio.Queue:
        """Add a WebSocket subscriber."""
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Remove a WebSocket subscriber."""
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def _broadcast(self, data: list[dict]):
        """Send market data to all subscribers."""
        msg = json.dumps(data)
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def stop(self):
        self._running = False

    async def run(self):
        """Main loop — tick every second, broadcast every 2 seconds."""
        self._running = True
        tick_count = 0
        while self._running:
            for symbol in self.prices:
                self._simulate_tick(symbol)
            tick_count += 1

            # Broadcast every 2 ticks (2 seconds)
            if tick_count % 2 == 0:
                snapshot = self.get_snapshot()
                await self._broadcast(snapshot)

                # Persist a snapshot every 30 seconds
                if tick_count % 30 == 0:
                    self._persist_snapshot()

            await asyncio.sleep(1)

    def _persist_snapshot(self):
        """Write current prices to database for historical reference."""
        try:
            conn = get_db()
            for symbol, data in self.prices.items():
                conn.execute(
                    """INSERT INTO market_data (symbol, bid, ask, ltp, volume, volatility, avg_trade_size)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (symbol, data["bid"], data["ask"], data["ltp"],
                     data["day_volume"], data["volatility"], data["avg_trade_size"]),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error persisting market data: {e}")
