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

    conn.commit()

    # ── Seed data ──
    _seed_instruments(cursor)
    _seed_clients(cursor)
    _seed_accounts(cursor)
    _seed_historical_orders_and_market_data(cursor)

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


if __name__ == "__main__":
    init_db()
