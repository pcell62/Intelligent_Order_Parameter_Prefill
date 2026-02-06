"""
Execution Engine
Processes orders from the queue, simulates matching, handles algo execution.
Manages the order lifecycle: VALIDATED → WORKING → PARTIALLY_FILLED → FILLED.
"""

import asyncio
import json
import math
import random
import uuid
from datetime import datetime
from typing import Any
from database import get_db
from services.market_data_service import MarketDataService


class ExecutionEngine:
    """Simulates order execution with realistic matching logic."""

    def __init__(self, market_service: MarketDataService):
        self.market_service = market_service
        self._running = False
        self._ws_subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._ws_subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._ws_subscribers:
            self._ws_subscribers.remove(q)

    async def _broadcast_order_update(self, order: dict):
        msg = json.dumps({"type": "order_update", "data": order})
        dead = []
        for q in self._ws_subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._ws_subscribers.remove(q)

    def stop(self):
        self._running = False

    async def run(self):
        """Main execution loop — checks for working orders every second."""
        self._running = True
        while self._running:
            try:
                await self._process_orders()
            except Exception as e:
                print(f"Execution engine error: {e}")
            await asyncio.sleep(1)

    async def _process_orders(self):
        """Fetch and process all active orders."""
        conn = get_db()
        try:
            # Get all working / partially filled orders (parent-level)
            rows = conn.execute("""
                SELECT * FROM orders
                WHERE status IN ('WORKING', 'PARTIALLY_FILLED')
                AND parent_order_id IS NULL
                ORDER BY created_at ASC
            """).fetchall()

            for row in rows:
                order = dict(row)
                algo_type = order["algo_type"] or "NONE"

                if algo_type == "NONE":
                    await self._execute_direct(order, conn)
                elif algo_type == "POV":
                    await self._execute_pov(order, conn)
                elif algo_type == "VWAP":
                    await self._execute_vwap(order, conn)
                elif algo_type == "ICEBERG":
                    await self._execute_iceberg(order, conn)

            conn.commit()
        finally:
            conn.close()

    async def _execute_direct(self, order: dict, conn):
        """Execute a non-algo order (market or limit)."""
        symbol = order["symbol"]
        md = self.market_service.get_symbol_data(symbol)
        if not md:
            return

        remaining = order["quantity"] - order["filled_quantity"]
        if remaining <= 0:
            return

        if order["order_type"] == "MARKET":
            # Fill aggressively, possibly with slippage
            fill_price = md["ask"] if order["direction"] == "BUY" else md["bid"]
            slippage = self._calculate_slippage(remaining, md)
            if order["direction"] == "BUY":
                fill_price += slippage
            else:
                fill_price -= slippage
            fill_price = round(max(0.05, fill_price), 2)

            # Fill in chunks for larger orders
            fill_qty = self._determine_fill_size(remaining, md)
            await self._record_fill(order, fill_price, fill_qty, conn)

        elif order["order_type"] == "LIMIT":
            limit = order["limit_price"]
            can_fill = (
                (order["direction"] == "BUY" and md["ask"] <= limit) or
                (order["direction"] == "SELL" and md["bid"] >= limit)
            )
            if can_fill:
                fill_price = md["ask"] if order["direction"] == "BUY" else md["bid"]
                fill_qty = self._determine_fill_size(remaining, md)
                await self._record_fill(order, fill_price, fill_qty, conn)

        elif order["order_type"] == "STOP_LOSS":
            stop = order["stop_price"]
            triggered = (
                (order["direction"] == "SELL" and md["ltp"] <= stop) or
                (order["direction"] == "BUY" and md["ltp"] >= stop)
            )
            if triggered:
                fill_price = md["ask"] if order["direction"] == "BUY" else md["bid"]
                fill_qty = self._determine_fill_size(remaining, md)
                await self._record_fill(order, fill_price, fill_qty, conn)

    async def _execute_pov(self, order: dict, conn):
        """POV algo: participate at target % of market volume."""
        params = json.loads(order["algo_params"] or "{}")
        target_rate = params.get("target_participation_rate", 10) / 100
        min_size = params.get("min_order_size", 100)
        max_size = params.get("max_order_size", 50000)
        aggression = params.get("aggression_level", "Medium")

        md = self.market_service.get_symbol_data(order["symbol"])
        if not md:
            return

        remaining = order["quantity"] - order["filled_quantity"]
        if remaining <= 0:
            return

        # Check time window
        if not self._within_time_window(order):
            return

        # Calculate slice based on recent volume
        market_volume_tick = md.get("volume", 1000)
        target_qty = int(market_volume_tick * target_rate)
        target_qty = max(min_size, min(max_size, target_qty))
        target_qty = min(target_qty, remaining)

        if target_qty < min_size and remaining >= min_size:
            target_qty = min_size
        elif target_qty < 1:
            return

        # Determine fill price based on aggression
        fill_price = self._get_algo_fill_price(order, md, aggression)

        # Random chance of fill (simulates market participation)
        if random.random() < 0.6:  # 60% chance per tick
            await self._record_fill(order, fill_price, target_qty, conn)

    async def _execute_vwap(self, order: dict, conn):
        """VWAP algo: distribute order along volume curve."""
        params = json.loads(order["algo_params"] or "{}")
        max_participation = params.get("max_volume_pct", 20) / 100
        curve = params.get("volume_curve", "Historical")
        aggression = params.get("aggression_level", "Low")

        md = self.market_service.get_symbol_data(order["symbol"])
        if not md:
            return

        remaining = order["quantity"] - order["filled_quantity"]
        if remaining <= 0:
            return

        if not self._within_time_window(order):
            return

        # Calculate time progress through the window
        progress = self._get_time_progress(order)

        # Determine target fill % based on curve
        if curve == "Front-loaded":
            target_pct = min(1.0, progress * 1.5)
        elif curve == "Back-loaded":
            target_pct = max(0, progress ** 1.5)
        else:
            target_pct = progress  # Linear / historical

        expected_filled = int(order["quantity"] * target_pct)
        deficit = expected_filled - order["filled_quantity"]

        if deficit <= 0:
            return  # Ahead of schedule

        # Cap by max participation
        market_volume_tick = md.get("volume", 1000)
        max_this_tick = int(market_volume_tick * max_participation)
        fill_qty = min(deficit, max_this_tick, remaining)
        fill_qty = max(1, fill_qty)

        fill_price = self._get_algo_fill_price(order, md, aggression)

        if random.random() < 0.5:
            await self._record_fill(order, fill_price, fill_qty, conn)

    async def _execute_iceberg(self, order: dict, conn):
        """ICEBERG algo: show display qty, refill when consumed."""
        params = json.loads(order["algo_params"] or "{}")
        display_qty = params.get("display_quantity", 5000)
        aggression = params.get("aggression_level", "Medium")

        md = self.market_service.get_symbol_data(order["symbol"])
        if not md:
            return

        remaining = order["quantity"] - order["filled_quantity"]
        if remaining <= 0:
            return

        # Show only display_qty at a time
        visible = min(display_qty, remaining)

        # Fill a portion of the visible quantity
        fill_qty = random.randint(1, max(1, visible // 3))
        fill_qty = min(fill_qty, remaining)

        fill_price = self._get_algo_fill_price(order, md, aggression)

        if random.random() < 0.4:
            await self._record_fill(order, fill_price, fill_qty, conn)

    # ── Helpers ──

    def _calculate_slippage(self, quantity: int, md: dict) -> float:
        """Estimate slippage based on order size relative to avg trade size."""
        avg = md.get("avg_trade_size", 5000)
        if avg == 0:
            avg = 5000
        size_ratio = quantity / avg
        vol = md.get("volatility", 2.0) / 100
        slippage = md["ltp"] * vol * math.sqrt(size_ratio) * 0.01
        return round(slippage, 2)

    def _determine_fill_size(self, remaining: int, md: dict) -> int:
        """Determine realistic fill size for a single tick."""
        avg = md.get("avg_trade_size", 5000)
        # Fill between 10% and 100% of avg trade size
        fill = random.randint(max(1, int(avg * 0.1)), max(2, int(avg * 0.5)))
        return min(fill, remaining)

    def _get_algo_fill_price(self, order: dict, md: dict, aggression: str) -> float:
        """Get fill price based on aggression level."""
        is_buy = order["direction"] == "BUY"
        spread = md["ask"] - md["bid"]

        if aggression in ("High", "high"):
            # Cross the spread aggressively
            price = md["ask"] if is_buy else md["bid"]
        elif aggression in ("Low", "low"):
            # Passive — try to get filled at our side
            price = md["bid"] if is_buy else md["ask"]
        else:
            # Medium — mid price
            price = md["ltp"]

        # Add small random noise
        noise = random.uniform(-spread * 0.1, spread * 0.1)
        return round(max(0.05, price + noise), 2)

    def _within_time_window(self, order: dict) -> bool:
        """Check if current time is within order's start/end window."""
        now = datetime.now()
        if order["start_time"]:
            try:
                parts = order["start_time"].split(":")
                start = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0)
                if now < start:
                    return False
            except (ValueError, IndexError):
                pass
        if order["end_time"]:
            try:
                parts = order["end_time"].split(":")
                end = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0)
                if now > end:
                    return False
            except (ValueError, IndexError):
                pass
        return True

    def _get_time_progress(self, order: dict) -> float:
        """Get progress through the order time window (0.0 to 1.0)."""
        now = datetime.now()
        try:
            sp = order["start_time"].split(":")
            ep = order["end_time"].split(":")
            start = now.replace(hour=int(sp[0]), minute=int(sp[1]), second=0)
            end = now.replace(hour=int(ep[0]), minute=int(ep[1]), second=0)
            total = (end - start).total_seconds()
            if total <= 0:
                return 1.0
            elapsed = (now - start).total_seconds()
            return max(0.0, min(1.0, elapsed / total))
        except (ValueError, IndexError, AttributeError):
            return 0.5

    async def _record_fill(self, order: dict, fill_price: float, fill_qty: int, conn):
        """Record an execution and update order state."""
        if fill_qty <= 0:
            return

        remaining = order["quantity"] - order["filled_quantity"]
        fill_qty = min(fill_qty, remaining)
        if fill_qty <= 0:
            return

        execution_id = str(uuid.uuid4())
        new_filled = order["filled_quantity"] + fill_qty

        # Calculate new average fill price
        old_total = order["avg_fill_price"] * order["filled_quantity"]
        new_avg = round((old_total + fill_price * fill_qty) / new_filled, 2)

        new_status = "FILLED" if new_filled >= order["quantity"] else "PARTIALLY_FILLED"

        # Insert execution
        conn.execute(
            """INSERT INTO executions (execution_id, order_id, fill_price, fill_quantity)
               VALUES (?, ?, ?, ?)""",
            (execution_id, order["order_id"], fill_price, fill_qty),
        )

        # Update order
        conn.execute(
            """UPDATE orders SET filled_quantity = ?, avg_fill_price = ?, status = ?,
               updated_at = CURRENT_TIMESTAMP WHERE order_id = ?""",
            (new_filled, new_avg, new_status, order["order_id"]),
        )

        # Audit trail
        conn.execute(
            """INSERT INTO order_history (order_id, action, details) VALUES (?, ?, ?)""",
            (order["order_id"], "FILL",
             json.dumps({"fill_price": fill_price, "fill_qty": fill_qty,
                         "total_filled": new_filled, "execution_id": execution_id})),
        )

        # Update in-memory for next tick
        order["filled_quantity"] = new_filled
        order["avg_fill_price"] = new_avg
        order["status"] = new_status

        # Broadcast
        await self._broadcast_order_update({
            "order_id": order["order_id"],
            "status": new_status,
            "filled_quantity": new_filled,
            "avg_fill_price": new_avg,
            "last_fill_price": fill_price,
            "last_fill_qty": fill_qty,
        })
