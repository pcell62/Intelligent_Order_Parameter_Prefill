import sqlite3
import os
import json
import random
from dotenv import load_dotenv

load_dotenv()

DATABASE_PATH = os.getenv("DATABASE_PATH", "./trading.db")

# Schema version — bump to force recreation on next startup
SCHEMA_VERSION = 2

# Base prices (shared with market_data_service)
BASE_PRICES = {
    "RELIANCE": 2450.00, "TCS": 3820.00, "INFY": 1580.00, "HDFCBANK": 1720.00,
    "ICICIBANK": 1150.00, "SBIN": 780.00, "BHARTIARTL": 1620.00,
    "ITC": 452.00, "TATAMOTORS": 710.00, "WIPRO": 485.00,
}


def get_db() -> sqlite3.Connection:
    """Get a database connection with WAL mode and row factory."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize database with schema and seed data."""
    conn = get_db()
    cursor = conn.cursor()

    # ── Version tracking ──
    cursor.execute("CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER NOT NULL DEFAULT 0)")
    row = cursor.execute("SELECT version FROM _schema_version").fetchone()
    current = row[0] if row else 0

    if current < SCHEMA_VERSION:
        print(f"  Schema upgrade v{current} -> v{SCHEMA_VERSION}. Recreating tables...")
        for t in ["order_history", "executions", "market_data", "orders", "accounts", "clients", "instruments"]:
            cursor.execute(f"DROP TABLE IF EXISTS {t}")
        cursor.execute("DELETE FROM _schema_version")
        cursor.execute("INSERT INTO _schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

    # ── Market instruments ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instruments (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            exchange TEXT NOT NULL DEFAULT 'NSE',
            lot_size INTEGER NOT NULL DEFAULT 1,
            tick_size REAL NOT NULL DEFAULT 0.05,
            circuit_limit_pct REAL NOT NULL DEFAULT 5.0,
            adv REAL NOT NULL DEFAULT 0,
            sector TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # ── Clients / counterparties ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            credit_limit REAL NOT NULL DEFAULT 0,
            position_limit INTEGER NOT NULL DEFAULT 0,
            restricted_symbols TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            risk_aversion INTEGER NOT NULL DEFAULT 50,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Client trading accounts ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            account_name TEXT NOT NULL,
            account_type TEXT NOT NULL DEFAULT 'CASH',
            is_default INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        )
    """)

    # ── Orders (parent) — EXTENDED with TIF, urgency, get_done, capacity ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            parent_order_id TEXT,
            client_id TEXT NOT NULL,
            account_id TEXT,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('BUY', 'SELL')),
            order_type TEXT NOT NULL CHECK(order_type IN ('MARKET', 'LIMIT', 'STOP_LOSS')),
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            filled_quantity INTEGER NOT NULL DEFAULT 0,
            limit_price REAL,
            stop_price REAL,
            algo_type TEXT CHECK(algo_type IN ('NONE', 'POV', 'VWAP', 'ICEBERG')),
            algo_params TEXT DEFAULT '{}',
            start_time TEXT,
            end_time TEXT,
            tif TEXT NOT NULL DEFAULT 'GFD'
                CHECK(tif IN ('GFD','IOC','FOK','GTC','GTD')),
            urgency INTEGER NOT NULL DEFAULT 50
                CHECK(urgency BETWEEN 0 AND 100),
            get_done INTEGER NOT NULL DEFAULT 0,
            capacity TEXT NOT NULL DEFAULT 'AGENCY'
                CHECK(capacity IN ('AGENCY','PRINCIPAL','RISKLESS_PRINCIPAL','MIXED')),
            order_notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING','VALIDATED','WORKING','PARTIALLY_FILLED',
                                 'FILLED','CANCELLED','REJECTED','EXPIRED')),
            avg_fill_price REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients(client_id),
            FOREIGN KEY (symbol) REFERENCES instruments(symbol),
            FOREIGN KEY (parent_order_id) REFERENCES orders(order_id)
        )
    """)

    # ── Executions / fills ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS executions (
            execution_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            fill_price REAL NOT NULL,
            fill_quantity INTEGER NOT NULL CHECK(fill_quantity > 0),
            venue TEXT DEFAULT 'NSE',
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)

    # ── Live market data snapshots ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            bid REAL NOT NULL,
            ask REAL NOT NULL,
            ltp REAL NOT NULL,
            volume INTEGER NOT NULL DEFAULT 0,
            volatility REAL NOT NULL DEFAULT 0,
            avg_trade_size REAL NOT NULL DEFAULT 0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (symbol) REFERENCES instruments(symbol)
        )
    """)

    # ── Order audit trail ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)

    # ── Indexes ──
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_client ON orders(client_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_parent ON orders(parent_order_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_executions_order ON executions(order_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_market_data_symbol ON market_data(symbol)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_client ON accounts(client_id)")

    # ── Rule Engine Configuration (persists across schema upgrades) ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rule_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE,
            value REAL NOT NULL,
            label TEXT NOT NULL,
            description TEXT DEFAULT '',
            data_type TEXT NOT NULL DEFAULT 'float',
            min_value REAL,
            max_value REAL,
            unit TEXT DEFAULT '',
            display_order INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    # ── Seed data ──
    _seed_instruments(cursor)
    _seed_clients(cursor)
    _seed_accounts(cursor)
    _seed_historical_orders_and_market_data(cursor)
    _seed_rule_config(cursor)

    conn.commit()
    conn.close()
    print("Database initialized successfully.")


# ─────────────────────────────────────────────────────────────────────
# Seed helpers
# ─────────────────────────────────────────────────────────────────────

def _seed_instruments(cursor):
    instruments = [
        ("RELIANCE", "Reliance Industries", "NSE", 1, 0.05, 5.0, 5000000, "Energy"),
        ("TCS", "Tata Consultancy Services", "NSE", 1, 0.05, 5.0, 3000000, "IT"),
        ("INFY", "Infosys Limited", "NSE", 1, 0.05, 5.0, 4000000, "IT"),
        ("HDFCBANK", "HDFC Bank", "NSE", 1, 0.05, 5.0, 6000000, "Banking"),
        ("ICICIBANK", "ICICI Bank", "NSE", 1, 0.05, 5.0, 4500000, "Banking"),
        ("SBIN", "State Bank of India", "NSE", 1, 0.05, 5.0, 8000000, "Banking"),
        ("BHARTIARTL", "Bharti Airtel", "NSE", 1, 0.05, 5.0, 3500000, "Telecom"),
        ("ITC", "ITC Limited", "NSE", 1, 0.05, 5.0, 7000000, "FMCG"),
        ("TATAMOTORS", "Tata Motors", "NSE", 1, 0.05, 5.0, 5500000, "Auto"),
        ("WIPRO", "Wipro Limited", "NSE", 1, 0.05, 5.0, 2500000, "IT"),
    ]
    for inst in instruments:
        cursor.execute("""
            INSERT OR IGNORE INTO instruments (symbol, name, exchange, lot_size, tick_size, circuit_limit_pct, adv, sector)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, inst)


def _seed_clients(cursor):
    clients = [
        ("CLIENT_XYZ", "XYZ Capital Partners", 50000000, 500000, "",
         "EOD compliance pattern. Regularly sends orders at market close.", 60),
        ("CLIENT_ABC", "ABC Asset Management", 30000000, 300000, "",
         "Prefers stealth execution. Minimize market impact.", 75),
        ("CLIENT_DEF", "DEF Hedge Fund", 100000000, 1000000, "",
         "Benchmarks against arrival price. Large block orders.", 40),
        ("CLIENT_GHI", "GHI Pension Fund", 80000000, 800000, "TATAMOTORS",
         "Conservative. Restricted from auto sector.", 85),
        ("CLIENT_JKL", "JKL Proprietary Trading", 20000000, 200000, "",
         "High frequency. Small to mid-size orders.", 15),
    ]
    for c in clients:
        cursor.execute("""
            INSERT OR IGNORE INTO clients (client_id, name, credit_limit, position_limit, restricted_symbols, notes, risk_aversion)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, c)


def _seed_accounts(cursor):
    accounts = [
        ("ACC_XYZ_CASH", "CLIENT_XYZ", "XYZ Cash Equities", "CASH", 1),
        ("ACC_XYZ_MARGIN", "CLIENT_XYZ", "XYZ Margin Account", "MARGIN", 0),
        ("ACC_ABC_CASH", "CLIENT_ABC", "ABC Primary", "CASH", 1),
        ("ACC_ABC_DERIV", "CLIENT_ABC", "ABC Derivatives", "DERIVATIVES", 0),
        ("ACC_ABC_CUSTODY", "CLIENT_ABC", "ABC Custody", "CUSTODY", 0),
        ("ACC_DEF_PRIME", "CLIENT_DEF", "DEF Prime Brokerage", "PRIME", 1),
        ("ACC_DEF_MARGIN", "CLIENT_DEF", "DEF Margin", "MARGIN", 0),
        ("ACC_GHI_PENSION", "CLIENT_GHI", "GHI Pension Fund", "CASH", 1),
        ("ACC_GHI_ETF", "CLIENT_GHI", "GHI ETF Basket", "CASH", 0),
        ("ACC_JKL_PROP", "CLIENT_JKL", "JKL Prop Trading", "MARGIN", 1),
        ("ACC_JKL_MM", "CLIENT_JKL", "JKL Market Making", "MARGIN", 0),
    ]
    for a in accounts:
        cursor.execute("""
            INSERT OR IGNORE INTO accounts (account_id, client_id, account_name, account_type, is_default)
            VALUES (?, ?, ?, ?, ?)
        """, a)


def _seed_historical_orders_and_market_data(cursor):
    """Generate 70+ realistic historical orders with learnable patterns per client,
    plus correlated market_data snapshots so the prefill engine can discover them."""
    random.seed(42)  # reproducible
    dates = ["2026-02-03", "2026-02-04", "2026-02-05"]

    # ── Client pattern templates ──
    client_patterns = {
        "CLIENT_XYZ": dict(
            symbols=["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK"],
            sym_weights=[35, 25, 20, 20],
            algos=[("VWAP", 73), ("POV", 20), ("NONE", 7)],
            qty_range=(100_000, 300_000),
            hour_range=(13, 15),
            aggression_pool=["Medium", "Medium", "Medium", "High", "High"],
            vwap_curve="Back-loaded",
            notes_pool=[
                "EOD compliance required",
                "Must complete by close",
                "EOD fill - compliance mandate",
                "End of day compliance order",
                "Compliance: complete by market close",
            ],
            tif="GFD", urgency_range=(55, 80), get_done=1, capacity="AGENCY",
            count=15,
        ),
        "CLIENT_ABC": dict(
            symbols=["INFY", "TCS", "WIPRO", "BHARTIARTL"],
            sym_weights=[30, 25, 25, 20],
            algos=[("ICEBERG", 65), ("VWAP", 25), ("NONE", 10)],
            qty_range=(50_000, 150_000),
            hour_range=(10, 14),
            aggression_pool=["Low", "Low", "Low", "Medium"],
            vwap_curve="Historical",
            notes_pool=[
                "Minimize market impact",
                "Stealth execution preferred",
                "Hide order size from market",
                "Low footprint - client request",
            ],
            tif="GFD", urgency_range=(20, 45), get_done=0, capacity="AGENCY",
            count=12,
        ),
        "CLIENT_DEF": dict(
            symbols=["RELIANCE", "SBIN", "HDFCBANK", "TATAMOTORS", "ICICIBANK"],
            sym_weights=[25, 25, 20, 15, 15],
            algos=[("POV", 60), ("VWAP", 25), ("NONE", 15)],
            qty_range=(200_000, 500_000),
            hour_range=(9, 14),
            aggression_pool=["Medium", "Medium", "High", "High"],
            vwap_curve="Historical",
            notes_pool=[
                "Benchmark: arrival price",
                "Block order - arrival benchmark",
                "Target arrival price execution",
                "Arrival price - minimize slippage from entry",
            ],
            tif="GFD", urgency_range=(45, 70), get_done=0, capacity="PRINCIPAL",
            count=14,
        ),
        "CLIENT_GHI": dict(
            symbols=["ITC", "BHARTIARTL", "HDFCBANK", "INFY"],
            sym_weights=[30, 30, 20, 20],
            algos=[("VWAP", 70), ("ICEBERG", 20), ("NONE", 10)],
            qty_range=(50_000, 200_000),
            hour_range=(10, 14),
            aggression_pool=["Low", "Low", "Low", "Medium"],
            vwap_curve="Historical",
            notes_pool=[
                "Conservative approach required",
                "Risk-averse execution",
                "Pension fund - low impact",
                "Patient accumulation",
            ],
            tif="GFD", urgency_range=(15, 35), get_done=0, capacity="AGENCY",
            count=10,
        ),
        "CLIENT_JKL": dict(
            symbols=["RELIANCE", "TCS", "INFY", "SBIN", "ICICIBANK",
                      "HDFCBANK", "BHARTIARTL", "ITC", "TATAMOTORS", "WIPRO"],
            sym_weights=[12, 12, 10, 10, 10, 10, 8, 8, 10, 10],
            algos=[("NONE", 75), ("POV", 18), ("VWAP", 7)],
            qty_range=(5_000, 50_000),
            hour_range=(9, 15),
            aggression_pool=["High", "High", "High", "Medium"],
            vwap_curve="Front-loaded",
            notes_pool=[
                "Quick fill",
                "Speed priority",
                "Fast execution required",
                "Prop desk - immediate",
            ],
            tif="IOC", urgency_range=(70, 95), get_done=0, capacity="PRINCIPAL",
            count=18,
        ),
    }

    all_orders = []
    all_market = []
    oid = 0

    for client_id, pat in client_patterns.items():
        for i in range(pat["count"]):
            oid += 1

            # ── Pick symbol (weighted) ──
            symbol = random.choices(pat["symbols"], weights=pat["sym_weights"])[0]
            direction = random.choice(["BUY", "BUY", "SELL"])  # slight buy bias
            qty = random.randint(*pat["qty_range"])
            qty = (qty // 1000) * 1000  # round to nearest 1000

            # ── Pick algo (weighted) ──
            algo_names = [a[0] for a in pat["algos"]]
            algo_weights = [a[1] for a in pat["algos"]]
            algo_type = random.choices(algo_names, weights=algo_weights)[0]

            # ── Algo params ──
            aggression = random.choice(pat["aggression_pool"])
            algo_params = {}
            if algo_type == "VWAP":
                algo_params = {
                    "volume_curve": pat["vwap_curve"],
                    "max_volume_pct": random.choice([15, 20, 25]),
                    "aggression_level": aggression,
                }
            elif algo_type == "POV":
                algo_params = {
                    "target_participation_rate": random.choice([8, 10, 12, 15, 20]),
                    "min_order_size": random.choice([200, 500, 1000]),
                    "max_order_size": random.choice([10000, 15000, 20000]),
                    "aggression_level": aggression,
                }
            elif algo_type == "ICEBERG":
                algo_params = {
                    "display_quantity": max(1000, int(qty * random.uniform(0.05, 0.12))),
                    "aggression_level": aggression,
                }

            order_type = "LIMIT" if algo_type != "NONE" else random.choice(["MARKET", "MARKET", "LIMIT"])

            # ── Timestamp ──
            date = dates[i % len(dates)]
            hour = random.randint(*pat["hour_range"])
            hour = min(hour, 15)
            minute = random.randint(0, 59)
            if hour == 15:
                minute = min(minute, 25)
            created_at = f"{date} {hour:02d}:{minute:02d}:00"

            # ── Time window for algos ──
            start_time = end_time = None
            if algo_type != "NONE":
                start_time = f"{hour:02d}:{minute:02d}"
                eh = min(15, hour + random.randint(1, 3))
                em = random.randint(0, 30) if eh < 15 else 30
                end_time = f"{eh:02d}:{em:02d}"

            # ── Prices ──
            base = BASE_PRICES[symbol]
            price = base * (1 + random.uniform(-0.015, 0.015))
            avg_fill = round(price, 2)
            limit_price = round(price * (1.001 if direction == "BUY" else 0.999), 2) if order_type == "LIMIT" else None

            notes = random.choice(pat["notes_pool"])
            urgency = random.randint(*pat["urgency_range"])
            order_id = f"H-{client_id[-3:]}-{i + 1:02d}"

            all_orders.append((
                order_id, None, client_id, None, symbol, direction, order_type,
                qty, qty, limit_price, None,
                algo_type, json.dumps(algo_params), start_time, end_time,
                pat["tif"], urgency, pat["get_done"], pat["capacity"],
                notes, "FILLED", avg_fill, created_at, created_at,
            ))

            # ── Matching market_data snapshot (within ±60s for correlation) ──
            vol = round(random.uniform(1.2, 3.5), 3)
            spread = round(base * random.uniform(2, 8) / 10000, 2)
            all_market.append((
                symbol,
                round(price - spread / 2, 2),
                round(price + spread / 2, 2),
                round(price, 2),
                random.randint(50_000, 500_000),
                vol,
                random.randint(500, 10_000),
                created_at,
            ))

    # ── Bulk insert ──
    cursor.executemany("""
        INSERT OR IGNORE INTO orders (
            order_id, parent_order_id, client_id, account_id, symbol, direction, order_type,
            quantity, filled_quantity, limit_price, stop_price,
            algo_type, algo_params, start_time, end_time,
            tif, urgency, get_done, capacity,
            order_notes, status, avg_fill_price, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, all_orders)

    cursor.executemany("""
        INSERT INTO market_data (symbol, bid, ask, ltp, volume, volatility, avg_trade_size, timestamp)
        VALUES (?,?,?,?,?,?,?,?)
    """, all_market)

    print(f"  Seeded {len(all_orders)} historical orders + {len(all_market)} market snapshots.")


def _seed_rule_config(cursor):
    """Seed rule_config with every configurable threshold from the prefill engine.

    Values are stored exactly as used in code.  The label and unit fields
    make each value human-readable on the Settings page.
    Format: (category, key, value, label, description, data_type, min_val, max_val, unit, display_order)
    """
    configs = [
        # ═══════════════════════════════════════════════════════
        # URGENCY SCORING  (category: urgency)
        # ═══════════════════════════════════════════════════════
        ("urgency", "urgency.baseline", 50, "Baseline Score",
         "Starting urgency score before any adjustments", "integer", 0, 100, "points", 1),

        # -- Time to close --
        ("urgency", "urgency.time_close_critical_min", 10, "Critical Close Threshold",
         "Minutes to close considered critical", "integer", 1, 60, "min", 2),
        ("urgency", "urgency.time_close_critical_delta", 35, "Critical Close Delta",
         "Urgency boost when within critical close time", "integer", 0, 50, "points", 3),
        ("urgency", "urgency.time_close_tight_min", 20, "Tight Close Threshold",
         "Minutes to close considered tight", "integer", 5, 60, "min", 4),
        ("urgency", "urgency.time_close_tight_delta", 25, "Tight Close Delta",
         "Urgency boost when close is tight", "integer", 0, 50, "points", 5),
        ("urgency", "urgency.time_close_approaching_min", 30, "Approaching Close Threshold",
         "Minutes to close considered approaching", "integer", 10, 120, "min", 6),
        ("urgency", "urgency.time_close_approaching_delta", 18, "Approaching Close Delta",
         "Urgency boost when close is approaching", "integer", 0, 40, "points", 7),
        ("urgency", "urgency.time_close_mild_min", 60, "Mild Pressure Threshold",
         "Minutes to close for mild time pressure", "integer", 15, 180, "min", 8),
        ("urgency", "urgency.time_close_mild_delta", 10, "Mild Pressure Delta",
         "Urgency boost at mild time pressure", "integer", 0, 30, "points", 9),
        ("urgency", "urgency.time_open_plenty_min", 240, "Full Session Threshold",
         "Minutes to close above which no time pressure", "integer", 120, 375, "min", 10),
        ("urgency", "urgency.time_open_plenty_delta", -10, "Full Session Delta",
         "Urgency reduction with full session ahead", "integer", -30, 0, "points", 11),

        # -- Client profile tags --
        ("urgency", "urgency.tag_eod_compliance", 12, "EOD Compliance Tag Delta",
         "Urgency boost for EOD compliance clients", "integer", 0, 30, "points", 12),
        ("urgency", "urgency.tag_hft", 18, "HFT Tag Delta",
         "Urgency boost for high-frequency clients", "integer", 0, 30, "points", 13),
        ("urgency", "urgency.tag_stealth", -12, "Stealth Tag Delta",
         "Urgency reduction for stealth clients", "integer", -30, 0, "points", 14),
        ("urgency", "urgency.tag_conservative", -15, "Conservative Tag Delta",
         "Urgency reduction for conservative clients", "integer", -30, 0, "points", 15),
        ("urgency", "urgency.tag_arrival_price", 5, "Arrival Price Tag Delta",
         "Urgency boost for arrival price clients", "integer", 0, 20, "points", 16),

        # -- Order size --
        ("urgency", "urgency.size_above_20pct_delta", -12, "Size >20% ADV Delta",
         "Urgency reduction for very large orders (>20% ADV)", "integer", -30, 0, "points", 17),
        ("urgency", "urgency.size_above_10pct_delta", -5, "Size >10% ADV Delta",
         "Urgency reduction for large orders (>10% ADV)", "integer", -20, 0, "points", 18),
        ("urgency", "urgency.size_below_2pct_delta", 10, "Size <2% ADV Delta",
         "Urgency boost for tiny orders (<2% ADV)", "integer", 0, 20, "points", 19),
        ("urgency", "urgency.size_below_5pct_delta", 5, "Size <5% ADV Delta",
         "Urgency boost for small orders (<5% ADV)", "integer", 0, 15, "points", 20),

        # -- Volatility --
        ("urgency", "urgency.vol_high_threshold", 3.0, "High Volatility Threshold",
         "Volatility % considered high", "float", 1.0, 10.0, "%", 21),
        ("urgency", "urgency.vol_high_delta", -8, "High Volatility Delta",
         "Urgency reduction at high volatility", "integer", -20, 0, "points", 22),
        ("urgency", "urgency.vol_low_threshold", 1.5, "Low Volatility Threshold",
         "Volatility % considered low", "float", 0.5, 5.0, "%", 23),
        ("urgency", "urgency.vol_low_delta", 5, "Low Volatility Delta",
         "Urgency boost at low volatility", "integer", 0, 15, "points", 24),

        # -- Notes intent --
        ("urgency", "urgency.notes_high_delta", 20, "Urgent Notes Delta",
         "Boost when notes indicate urgency (e.g. 'urgent', 'asap')", "integer", 0, 40, "points", 25),
        ("urgency", "urgency.notes_low_delta", -15, "Patient Notes Delta",
         "Reduction when notes indicate patience (e.g. 'no rush')", "integer", -30, 0, "points", 26),
        ("urgency", "urgency.notes_get_done_delta", 12, "Get-Done Notes Delta",
         "Boost when notes indicate must-complete", "integer", 0, 30, "points", 27),
        ("urgency", "urgency.deadline_imminent_min", 30, "Imminent Deadline (min)",
         "Deadline within this many minutes treated as imminent", "integer", 5, 60, "min", 28),
        ("urgency", "urgency.deadline_imminent_delta", 20, "Imminent Deadline Delta",
         "Urgency boost when deadline is imminent", "integer", 0, 40, "points", 29),
        ("urgency", "urgency.deadline_approaching_min", 60, "Approaching Deadline (min)",
         "Deadline within this many minutes treated as approaching", "integer", 30, 120, "min", 30),
        ("urgency", "urgency.deadline_approaching_delta", 10, "Approaching Deadline Delta",
         "Urgency boost when deadline is approaching", "integer", 0, 25, "points", 31),

        # -- Risk aversion --
        ("urgency", "urgency.risk_aversion_factor", 0.15, "Risk Aversion Factor",
         "Multiplier for risk aversion influence: (50 - RA) * factor", "float", 0.0, 0.5, "factor", 32),

        # ═══════════════════════════════════════════════════════
        # ALGO SELECTION  (category: algo)
        # ═══════════════════════════════════════════════════════
        ("algo", "algo.direct_urgency_threshold", 85, "Direct Execution Urgency",
         "Min urgency for direct execution (no algo)", "integer", 70, 100, "", 1),
        ("algo", "algo.direct_size_max", 5, "Direct Execution Max Size",
         "Max order size (% ADV) for direct execution at high urgency", "float", 1, 20, "% ADV", 2),
        ("algo", "algo.high_urgency_threshold", 75, "High Urgency Threshold",
         "Urgency level considered 'high' for algo selection", "integer", 60, 95, "", 3),
        ("algo", "algo.low_urgency_threshold", 25, "Low Urgency Threshold",
         "Urgency level considered 'low' for algo selection", "integer", 5, 40, "", 4),
        ("algo", "algo.high_urgency_large_size", 10, "High Urgency Large Size",
         "Size threshold for POV at high urgency (% ADV)", "float", 3, 25, "% ADV", 5),
        ("algo", "algo.high_urgency_mid_size", 3, "High Urgency Mid Size",
         "Size threshold for POV vs Direct at high urgency (% ADV)", "float", 1, 10, "% ADV", 6),
        ("algo", "algo.low_urgency_large_size", 15, "Low Urgency Large Size",
         "Size for ICEBERG at low urgency (% ADV)", "float", 5, 30, "% ADV", 7),
        ("algo", "algo.low_urgency_mid_size", 5, "Low Urgency Mid Size",
         "Size for VWAP at low urgency (% ADV)", "float", 2, 15, "% ADV", 8),
        ("algo", "algo.med_very_large_size", 20, "Medium Urgency Very Large",
         "Size for ICEBERG at medium urgency (% ADV)", "float", 10, 40, "% ADV", 9),
        ("algo", "algo.med_large_size", 10, "Medium Urgency Large Size",
         "Size for VWAP at medium urgency (% ADV)", "float", 5, 25, "% ADV", 10),
        ("algo", "algo.med_mid_size", 3, "Medium Urgency Mid Size",
         "Size for POV at medium urgency (% ADV)", "float", 1, 10, "% ADV", 11),
        ("algo", "algo.hft_small_size", 2, "HFT Small Order Size",
         "Max size for HFT direct execution (% ADV)", "float", 0.5, 5, "% ADV", 12),

        # ═══════════════════════════════════════════════════════
        # ORDER TYPE  (category: order_type)
        # ═══════════════════════════════════════════════════════
        ("order_type", "order_type.market_urgency", 85, "MARKET Urgency Threshold",
         "Min urgency to suggest MARKET order", "integer", 70, 100, "", 1),
        ("order_type", "order_type.market_time_close", 15, "MARKET Time-to-Close",
         "Minutes to close below which MARKET order is suggested", "integer", 5, 30, "min", 2),
        ("order_type", "order_type.limit_volatility", 3.0, "LIMIT Volatility Threshold",
         "Volatility (%) above which LIMIT is forced", "float", 1.0, 10.0, "%", 3),

        # ═══════════════════════════════════════════════════════
        # LIMIT PRICE  (category: limit_price)
        # ═══════════════════════════════════════════════════════
        ("limit_price", "limit_price.high_urgency_threshold", 75, "High Urgency Threshold",
         "Urgency level for widest offset", "integer", 60, 95, "", 1),
        ("limit_price", "limit_price.high_urgency_offset", 18, "High Urgency Offset",
         "Limit price offset at high urgency", "integer", 5, 50, "bps", 2),
        ("limit_price", "limit_price.med_urgency_threshold", 50, "Medium Urgency Threshold",
         "Urgency level for medium offset", "integer", 30, 75, "", 3),
        ("limit_price", "limit_price.med_urgency_offset", 12, "Medium Urgency Offset",
         "Limit price offset at medium urgency", "integer", 3, 30, "bps", 4),
        ("limit_price", "limit_price.time_close_threshold", 30, "Near-Close Threshold",
         "Minutes to close for widened offset", "integer", 10, 60, "min", 5),
        ("limit_price", "limit_price.time_close_offset", 15, "Near-Close Offset",
         "Limit price offset near close", "integer", 5, 40, "bps", 6),
        ("limit_price", "limit_price.vol_threshold", 2.5, "Volatility Threshold",
         "Volatility (%) for widened offset", "float", 1.0, 8.0, "%", 7),
        ("limit_price", "limit_price.vol_offset", 12, "Volatility Offset",
         "Limit price offset at high volatility", "integer", 3, 30, "bps", 8),
        ("limit_price", "limit_price.default_offset", 8, "Default Offset",
         "Default limit price offset", "integer", 1, 20, "bps", 9),

        # ═══════════════════════════════════════════════════════
        # TIME IN FORCE  (category: tif)
        # ═══════════════════════════════════════════════════════
        ("tif", "tif.direct_ioc_extreme", 90, "Direct IOC (Extreme Urgency)",
         "Min urgency for IOC on direct orders", "integer", 80, 100, "", 1),
        ("tif", "tif.direct_fok", 80, "Direct FOK Threshold",
         "Min urgency for FOK on direct orders", "integer", 65, 95, "", 2),
        ("tif", "tif.direct_ioc_high", 65, "Direct IOC (High Urgency)",
         "Min urgency for IOC at high urgency", "integer", 50, 85, "", 3),
        ("tif", "tif.algo_gfd_high", 85, "Algo GFD (High Urgency)",
         "Min urgency for GFD on algo + get-done", "integer", 70, 100, "", 4),
        ("tif", "tif.algo_gfd_moderate", 70, "Algo GFD (Moderate)",
         "Min urgency for GFD on algo orders", "integer", 50, 90, "", 5),
        ("tif", "tif.algo_gtc_time", 375, "GTC Time Threshold",
         "Min time to close (min) for GTC suggestion", "integer", 240, 400, "min", 6),

        # ═══════════════════════════════════════════════════════
        # TIME WINDOW  (category: time_window)
        # ═══════════════════════════════════════════════════════
        ("time_window", "time_window.high_urgency_threshold", 70, "High Urgency Threshold",
         "Urgency level for compressed window", "integer", 55, 90, "", 1),
        ("time_window", "time_window.high_urgency_fraction", 0.35, "High Urgency Fraction",
         "Fraction of remaining session at high urgency (0.35 = 35%)", "float", 0.1, 0.6, "fraction", 2),
        ("time_window", "time_window.med_urgency_threshold", 50, "Medium Urgency Threshold",
         "Urgency level for balanced window", "integer", 30, 70, "", 3),
        ("time_window", "time_window.med_urgency_fraction", 0.55, "Medium Urgency Fraction",
         "Fraction of remaining session at medium urgency (0.55 = 55%)", "float", 0.3, 0.8, "fraction", 4),
        ("time_window", "time_window.low_urgency_fraction", 0.75, "Low Urgency Fraction",
         "Fraction of remaining session at low urgency (0.75 = 75%)", "float", 0.5, 1.0, "fraction", 5),
        ("time_window", "time_window.min_window_min", 20, "Minimum Window",
         "Minimum algo execution window length", "integer", 5, 60, "min", 6),
        ("time_window", "time_window.close_threshold", 60, "Close Threshold",
         "Minutes to close below which window extends to session end", "integer", 15, 120, "min", 7),

        # ═══════════════════════════════════════════════════════
        # AGGRESSION  (category: aggression)
        # ═══════════════════════════════════════════════════════
        ("aggression", "aggression.high_threshold", 70, "High Aggression Urgency",
         "Min urgency for High aggression", "integer", 55, 90, "", 1),
        ("aggression", "aggression.med_threshold", 35, "Medium Aggression Urgency",
         "Min urgency for Medium aggression", "integer", 15, 55, "", 2),
        ("aggression", "aggression.conservative_risk", 70, "Conservative Risk Override",
         "Risk aversion above this forces Low aggression", "integer", 50, 90, "", 3),
        ("aggression", "aggression.aggressive_risk", 29, "Aggressive Risk Override",
         "Risk aversion below this forces High aggression", "integer", 10, 45, "", 4),
        ("aggression", "aggression.aggressive_urgency_floor", 30, "Aggressive Urgency Floor",
         "Min urgency where aggressive risk override applies", "integer", 10, 50, "", 5),
        ("aggression", "aggression.min_orders_blend", 5, "Min Orders for Blend",
         "Min historical orders for aggression blending", "integer", 2, 10, "", 6),

        # ═══════════════════════════════════════════════════════
        # POV PARAMETERS  (category: pov)
        # ═══════════════════════════════════════════════════════
        ("pov", "pov.high_urgency_threshold", 75, "High Urgency Threshold",
         "Urgency level for aggressive participation", "integer", 60, 95, "", 1),
        ("pov", "pov.med_urgency_threshold", 50, "Medium Urgency Threshold",
         "Urgency level for standard participation", "integer", 30, 70, "", 2),
        ("pov", "pov.rate_high_small", 20, "Rate: High Urgency + Small Order",
         "Participation rate for high urgency, small orders", "integer", 10, 40, "%", 3),
        ("pov", "pov.rate_high_large", 15, "Rate: High Urgency + Large Order",
         "Participation rate for high urgency, large orders", "integer", 5, 30, "%", 4),
        ("pov", "pov.rate_med_small", 12, "Rate: Med Urgency + Small Order",
         "Participation rate for medium urgency, small orders", "integer", 5, 25, "%", 5),
        ("pov", "pov.rate_med_large", 10, "Rate: Med Urgency + Large Order",
         "Participation rate for medium urgency, large orders", "integer", 3, 20, "%", 6),
        ("pov", "pov.rate_very_large", 5, "Rate: Very Large Orders",
         "Participation rate for orders >15% ADV", "integer", 1, 15, "%", 7),
        ("pov", "pov.rate_near_close", 18, "Rate: Near Close",
         "Participation rate when near close", "integer", 10, 30, "%", 8),
        ("pov", "pov.rate_default", 10, "Default Rate",
         "Default participation rate", "integer", 3, 25, "%", 9),
        ("pov", "pov.size_split_threshold", 10, "Size Split Threshold",
         "Size (% ADV) to split high/large rates", "float", 3, 20, "% ADV", 10),
        ("pov", "pov.very_large_threshold", 15, "Very Large Threshold",
         "Size (% ADV) for very large order rate", "float", 5, 30, "% ADV", 11),
        ("pov", "pov.time_close_threshold", 60, "Near-Close Threshold",
         "Minutes to close for elevated rate", "integer", 15, 120, "min", 12),
        ("pov", "pov.min_size_floor", 50, "Min Child Order Floor",
         "Absolute minimum child order size", "integer", 10, 500, "shares", 13),
        ("pov", "pov.min_size_multiplier", 0.3, "Min Size Multiplier",
         "Min child order = multiplier x avg trade size", "float", 0.1, 1.0, "x", 14),
        ("pov", "pov.max_size_multiplier", 3.0, "Max Size Multiplier",
         "Max child order = multiplier x avg trade size", "float", 1.0, 10.0, "x", 15),
        ("pov", "pov.max_size_min_ratio", 10, "Max/Min Size Ratio",
         "Max child order = at least ratio x min child order", "integer", 3, 50, "x", 16),

        # ═══════════════════════════════════════════════════════
        # VWAP PARAMETERS  (category: vwap)
        # ═══════════════════════════════════════════════════════
        ("vwap", "vwap.front_load_urgency", 65, "Front-Load Urgency",
         "Min urgency for front-loaded volume curve", "integer", 45, 85, "", 1),
        ("vwap", "vwap.front_load_time", 90, "Front-Load Time Threshold",
         "Minutes to close below which front-loading applies", "integer", 30, 180, "min", 2),
        ("vwap", "vwap.max_vol_large", 25, "Max Volume % (Large Orders)",
         "Max per-interval participation for large orders", "integer", 10, 50, "%", 3),
        ("vwap", "vwap.max_vol_medium", 15, "Max Volume % (Medium Orders)",
         "Max per-interval participation for medium orders", "integer", 5, 35, "%", 4),
        ("vwap", "vwap.max_vol_small", 20, "Max Volume % (Small Orders)",
         "Max per-interval participation for small orders", "integer", 5, 40, "%", 5),
        ("vwap", "vwap.size_large_threshold", 10, "Large Size Threshold",
         "Size above this = large order (% ADV)", "float", 5, 25, "% ADV", 6),
        ("vwap", "vwap.size_medium_threshold", 5, "Medium Size Threshold",
         "Size above this = medium order (% ADV)", "float", 2, 15, "% ADV", 7),

        # ═══════════════════════════════════════════════════════
        # ICEBERG PARAMETERS  (category: iceberg)
        # ═══════════════════════════════════════════════════════
        ("iceberg", "iceberg.display_pct", 0.08, "Display Qty Fraction",
         "Display quantity as fraction of total order (0.08 = 8%)", "float", 0.02, 0.20, "fraction", 1),
        ("iceberg", "iceberg.avg_trade_multiplier", 1.5, "Avg Trade Size Multiplier",
         "Display qty cap = multiplier x avg trade size", "float", 0.5, 5.0, "x", 2),
        ("iceberg", "iceberg.min_display", 100, "Minimum Display Qty",
         "Absolute minimum display quantity (shares)", "integer", 10, 1000, "shares", 3),

        # ═══════════════════════════════════════════════════════
        # HISTORICAL BLENDING  (category: historical)
        # ═══════════════════════════════════════════════════════
        ("historical", "historical.max_weight", 0.30, "Max Historical Weight",
         "Maximum influence of history on decisions (0.30 = 30%)", "float", 0.1, 0.6, "fraction", 1),
        ("historical", "historical.weight_per_order", 0.10, "Weight Per Order",
         "Weight increment per order above minimum (0.10 = 10%)", "float", 0.05, 0.2, "fraction", 2),
        ("historical", "historical.min_orders_start", 3, "Min Orders to Start",
         "Minimum orders before blending begins", "integer", 2, 10, "", 3),
        ("historical", "historical.similarity_threshold", 0.20, "Similarity Threshold",
         "Min condition similarity for history override (0.20 = 20%)", "float", 0.05, 0.5, "fraction", 4),
        ("historical", "historical.min_orders_order_type", 5, "Min Orders: Order Type",
         "Min orders for order type blending", "integer", 2, 10, "", 5),
        ("historical", "historical.min_orders_tif", 3, "Min Orders: TIF",
         "Min orders for TIF blending", "integer", 2, 10, "", 6),
        ("historical", "historical.min_orders_aggression", 5, "Min Orders: Aggression",
         "Min orders for aggression blending", "integer", 2, 10, "", 7),
        ("historical", "historical.get_done_freq", 0.50, "Get-Done Frequency",
         "Historical get-done frequency threshold (0.50 = 50%)", "float", 0.2, 0.9, "fraction", 8),
        ("historical", "historical.query_limit", 10, "Query Limit",
         "Max historical orders to analyze", "integer", 5, 50, "", 9),

        # ═══════════════════════════════════════════════════════
        # CROSS-CLIENT SIGNALS  (category: cross_client)
        # ═══════════════════════════════════════════════════════
        ("cross_client", "cross_client.qty_low_factor", 0.4, "Qty Low Factor",
         "Min quantity factor for similar order matching (0.4 = 40%)", "float", 0.1, 0.8, "x", 1),
        ("cross_client", "cross_client.qty_high_factor", 2.5, "Qty High Factor",
         "Max quantity factor for similar order matching", "float", 1.5, 5.0, "x", 2),
        ("cross_client", "cross_client.min_orders", 5, "Min Similar Orders",
         "Min orders across clients to generate a signal", "integer", 3, 20, "", 3),
        ("cross_client", "cross_client.min_pct", 60, "Min Algo Percentage",
         "Min % of orders using same algo for signal", "integer", 40, 90, "%", 4),

        # ═══════════════════════════════════════════════════════
        # SCENARIO DETECTION  (category: scenario)
        # ═══════════════════════════════════════════════════════
        ("scenario", "scenario.eod_time_threshold", 90, "EOD Time Threshold",
         "Minutes to close for EOD compliance scenario", "integer", 30, 180, "min", 1),
        ("scenario", "scenario.stealth_size", 20, "Stealth Size Threshold",
         "Min size (% ADV) for stealth scenario", "float", 10, 40, "% ADV", 2),
        ("scenario", "scenario.stealth_urgency_max", 40, "Stealth Max Urgency",
         "Max urgency for stealth execution scenario", "integer", 20, 60, "", 3),
        ("scenario", "scenario.speed_urgency_min", 80, "Speed Min Urgency",
         "Min urgency for speed priority scenario", "integer", 65, 95, "", 4),
        ("scenario", "scenario.speed_time", 15, "Speed Time Threshold",
         "Minutes to close for speed priority", "integer", 5, 30, "min", 5),
        ("scenario", "scenario.patient_urgency_max", 25, "Patient Max Urgency",
         "Max urgency for patient accumulation", "integer", 10, 40, "", 6),
        ("scenario", "scenario.patient_time_min", 120, "Patient Min Time",
         "Min minutes to close for patient accumulation", "integer", 60, 240, "min", 7),

        # ═══════════════════════════════════════════════════════
        # GET DONE  (category: get_done)
        # ═══════════════════════════════════════════════════════
        ("get_done", "get_done.urgency_threshold", 75, "Urgency Threshold",
         "Min urgency to auto-enable get-done flag", "integer", 55, 95, "", 1),
    ]

    for cfg in configs:
        cursor.execute("""
            INSERT OR IGNORE INTO rule_config
            (category, key, value, label, description, data_type, min_value, max_value, unit, display_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, cfg)
    print(f"  Rule config: {len(configs)} entries seeded.")


if __name__ == "__main__":
    init_db()
