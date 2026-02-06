# Intelligent Order Parameter Prefill — Solution Overview

## 1. Problem Summary

Institutional traders today manually configure dozens of order parameters — algo type, aggression, time window, participation rate, TIF, price constraints — for every single trade. This is slow, inconsistent, and error-prone. Market conditions, client behavior, and historical patterns contain strong signals, but they are never surfaced at the moment of order entry.

**The core opportunity**: leverage these signals to assist (not replace) the trader, reducing cognitive load, speeding up order entry, and standardizing execution quality across the desk.

---

## 2. Solution at a Glance

We built a **full-stack intelligent order parameter prefill system** that:

1. **Analyzes context** — client profile, instrument characteristics, real-time market conditions, historical trading patterns, and free-text order notes
2. **Suggests every parameter** — algo type, aggression, time window, participation rate, volume curve, limit price, TIF, get-done, and order notes
3. **Explains every suggestion** — each prefilled field has a human-readable explanation and a confidence score
4. **Adapts via a single urgency knob** — the "turn the knob" concept from the problem statement: one slider from 0 (Patient) to 100 (Urgent) that cascades to all parameters simultaneously
5. **Preserves full trader control** — every field is overridable, the prefill can be toggled off entirely, and "why not" explanations build trust

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js 16)                     │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ Market Data  │  │ Order Ticket │  │   Order Blotter        │  │
│  │ Table (Live) │  │ + Smart      │  │   (Real-time updates)  │  │
│  │              │  │   Prefill    │  │                        │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬───────────────┘  │
│         │ WebSocket       │ REST              │ WebSocket        │
└─────────┼─────────────────┼───────────────────┼──────────────────┘
          │                 │                   │
┌─────────┼─────────────────┼───────────────────┼──────────────────┐
│         ▼                 ▼                   ▼   BACKEND (FastAPI)│
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Market Data  │  │ Prefill      │  │ Execution Engine      │  │
│  │ Service      │  │ Service      │  │ (POV/VWAP/ICEBERG)    │  │
│  │ (GBM Sim)   │  │ (Rule+Hist   │  │                       │  │
│  │              │  │  +NLP+Cross) │  │                       │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────────────┘  │
│         │                 │                   │                  │
│         └─────────────────┼───────────────────┘                  │
│                           ▼                                      │
│                    ┌──────────────┐                               │
│                    │  SQLite DB   │                               │
│                    │ (7 tables)   │                               │
│                    └──────────────┘                               │
└──────────────────────────────────────────────────────────────────┘
```

**Tech Stack**: Next.js 16 + React 19 + TypeScript + Tailwind CSS + shadcn/ui | FastAPI + Python 3.13 + SQLite | WebSocket for real-time streaming

---

## 4. Key Features

### 4.1 The "Turn the Knob" — Urgency Meta-Slider

The centerpiece of the solution. A single 0-100 slider that cascades to all order parameters:

| Urgency | Zone     | Algo Tendency    | Aggression | Time Window     | TIF  | Get Done |
|---------|----------|------------------|------------|-----------------|------|----------|
| 0-20    | Patient  | VWAP / ICEBERG   | Low        | 75% of session  | GFD  | No       |
| 21-40   | Moderate | VWAP             | Low-Med    | 55% of session  | GFD  | No       |
| 41-60   | Balanced | Context-driven   | Medium     | 55% of session  | GFD  | No       |
| 61-80   | Active   | POV              | High       | 35% of session  | GFD  | Yes      |
| 81-100  | Urgent   | Direct / MARKET  | High       | Minimal         | IOC  | Yes      |

The system **computes** the initial urgency from context, but the trader can drag the slider to override — and watch all parameters shift in real-time. Quick-adjust buttons ("More Passive" / "More Urgent") allow fine-grained +/-10 nudges.

### 4.2 Intelligent Prefill Engine

The prefill engine combines **five signal sources**:

1. **Client Profile**: Risk aversion score (0-100), trading tags (EOD compliance, stealth, arrival benchmark, HFT, conservative), notes, restrictions
2. **Instrument Characteristics**: ADV, tick size, sector, circuit limits
3. **Real-Time Market Data**: LTP, bid/ask spread, volatility, avg trade size, time to close
4. **Historical Patterns**: Last 10 orders for the client-symbol pair — preferred algo, typical aggression, median quantity, market conditions at order time. Blended 70% rules / 30% history.
5. **Cross-Client Patterns**: What do all clients typically do for similar-sized orders on this symbol?

### 4.3 Order Notes NLP

Free-text order notes are parsed to extract structured intent:

| Input Text                          | Extracted Signal                          |
|-------------------------------------|-------------------------------------------|
| "VWAP must complete by 2pm"         | algo_hint=VWAP, deadline=14:00, get_done  |
| "Minimize market impact"            | urgency_hint=low                          |
| "Urgent — fill ASAP"               | urgency_hint=high                         |
| "Benchmark: arrival price"          | benchmark=arrival, algo_hint=POV          |
| "Max participation 15%"             | constraint: max_participation=15%         |

This directly addresses **Sample Case 2** from the problem statement.

### 4.4 Scenario Detection

The system classifies each order into a named execution scenario:

- **EOD Compliance Execution** — client has compliance fill requirements by close
- **Stealth / Minimal Impact** — large order or stealth client, hide footprint
- **Arrival Price Benchmark** — execute near entry price to minimize slippage
- **Speed Priority** — high urgency, fill fast with acceptable slippage
- **Patient Accumulation** — low urgency, gradually build position

The scenario is displayed prominently in the prefill summary card, giving the trader immediate context.

### 4.5 Explainability & Trust

Every prefilled field has:
- A **sparkle icon** (✨) indicating it was auto-filled
- A **confidence percentage** (e.g., 90%)
- A **hover tooltip** with a human-readable explanation

Additionally, a **"Why Not?"** expandable panel explains why each alternative algorithm was *not* chosen — e.g., "ICEBERG unnecessary — order is only 1.2% of ADV. The full quantity can be absorbed without significant market impact."

### 4.6 Full Trader Override

- Every prefilled field is directly editable
- Smart Prefill can be toggled off entirely with one switch
- The urgency slider gives broad directional control
- Risk aversion slider inherited from client but adjustable per-order

---

## 5. Data Model

### 5.1 Tables (7 + 1 meta)

| Table          | Purpose                              | Key Fields                                          |
|----------------|--------------------------------------|-----------------------------------------------------|
| instruments    | Traded symbols                       | symbol, adv, tick_size, sector                      |
| clients        | Counterparties                       | client_id, risk_aversion, notes, restrictions       |
| accounts       | Trading accounts per client          | account_id, client_id, type, is_default             |
| orders         | Parent orders                        | All standard fields + **tif, urgency, get_done, capacity** |
| executions     | Fill records                         | fill_price, fill_quantity, venue                    |
| market_data    | Historical price snapshots           | bid, ask, ltp, volatility, avg_trade_size           |
| order_history  | Audit trail                          | order_id, action, details (JSON)                    |

### 5.2 Seed Data

- **10 instruments**: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, BHARTIARTL, ITC, TATAMOTORS, WIPRO
- **5 clients**: Each with a distinct trading personality and risk profile
- **11 trading accounts**: Across all clients (cash, margin, derivatives, prime brokerage)
- **69 historical orders**: Filled orders with realistic patterns per client, covering 3 trading days
- **69 market snapshots**: Correlated with order timestamps for historical pattern analysis

---

## 6. Extended Order Ticket Fields

Beyond the original fields, we added:

| Field      | Type              | Purpose                                        | Prefilled? |
|------------|-------------------|-------------------------------------------------|------------|
| TIF        | GFD/IOC/FOK/GTC/GTD | Time In Force — order validity duration       | Yes        |
| Urgency    | 0-100 integer     | The meta-knob driving all other parameters     | Yes (auto-computed) |
| Get Done   | Boolean           | Must-complete flag for compliance scenarios    | Yes        |
| Capacity   | Agency/Principal/etc. | Regulatory trading capacity               | No (default Agency) |

---

## 7. API Endpoints

| Method | Path                    | Purpose                                     |
|--------|-------------------------|---------------------------------------------|
| POST   | /api/prefill/           | Get intelligent suggestions (with urgency & NLP) |
| POST   | /api/orders/            | Create order (with new fields)              |
| GET    | /api/orders/            | List orders with filters                    |
| GET    | /api/market-data/       | Current market snapshot                     |
| WS     | /api/market-data/ws     | Live market data stream                     |
| WS     | /api/market-data/ws/orders | Live order execution updates             |
| GET    | /api/clients/           | List clients                                |
| GET    | /api/instruments/       | List instruments                            |
| GET    | /api/accounts/          | List accounts                               |
| GET    | /api/analytics/*        | Analytics & historical data                 |

### Prefill Request/Response

**Request:**
```json
{
  "client_id": "CLIENT_XYZ",
  "symbol": "RELIANCE",
  "direction": "BUY",
  "quantity": 150000,
  "urgency": null,
  "order_notes": "VWAP must complete by 2pm"
}
```

**Response:**
```json
{
  "suggestions": {
    "algo_type": "VWAP",
    "order_type": "LIMIT",
    "limit_price": 2452.50,
    "tif": "GFD",
    "get_done": true,
    "start_time": "10:05",
    "end_time": "14:00",
    "aggression_level": "Medium",
    "volume_curve": "Front-loaded",
    "max_volume_pct": "20",
    "order_notes": "EOD compliance required | Deadline: 14:00"
  },
  "explanations": {
    "algo_type": "Order notes explicitly request VWAP",
    "tif": "Good For Day - standard TIF for intraday orders",
    "get_done": "Get Done enabled - order notes indicate must-complete"
  },
  "confidence": {
    "algo_type": 0.95,
    "order_type": 0.80,
    "tif": 0.85
  },
  "urgency_score": 68,
  "computed_urgency": 68,
  "scenario_tag": "eod_compliance",
  "scenario_label": "EOD Compliance Execution",
  "why_not": {
    "NONE": "Direct execution skipped - order is 3.0% of ADV...",
    "POV": "POV not ideal for EOD compliance...",
    "ICEBERG": "ICEBERG considered but VWAP better fits..."
  }
}
```

---

## 8. Design Decisions

| Decision | Rationale |
|----------|-----------|
| Rule-based + historical blending (not ML) | Explainable, deterministic, no training data dependency. Rules encode domain expertise; history adapts to client preferences. |
| Urgency as the meta-parameter | Directly addresses "turn the knob" requirement. Single intuitive control that encapsulates complex multi-parameter decisions. |
| 70/30 rule/history weighting | Rules ensure sensible defaults; history personalizes. Weight scales with order count (0% below 3 orders, up to 30% at 5+). |
| SQLite for storage | Zero-config, sufficient for hackathon demo. Schema designed for easy migration to PostgreSQL/TimescaleDB. |
| WebSocket for market data | Essential for realistic trading UX. 2-second broadcast interval balances responsiveness with resource usage. |
| Scenario detection | Gives traders immediate cognitive shortcut. "This is an EOD compliance order" is faster to process than reading 10 individual parameter explanations. |

---

## 9. Impact & Value

| Metric                          | Before (Manual)        | After (Smart Prefill)     |
|---------------------------------|------------------------|---------------------------|
| Fields to manually configure    | 12-15 per order        | 2-3 (client + symbol + qty) |
| Time to configure algo order    | 45-90 seconds          | 10-15 seconds             |
| Parameter consistency           | Varies by trader       | Standardized by rules + history |
| New trader onboarding           | Trial and error        | Guided by explanations    |
| Execution practice alignment    | Ad-hoc                 | Systematic, auditable     |

---

## 10. Future Directions

1. **ML Model Integration**: Train on historical fill quality to optimize suggestions beyond rules
2. **Portfolio-Level Context**: Consider what else the client is trading today
3. **News & Event Sensitivity**: Adjust urgency/aggression around earnings, macro events
4. **Order Notes NLP Enhancement**: GPT-powered intent extraction for complex instructions
5. **Execution Analytics Feedback Loop**: Track how prefilled vs. overridden parameters perform
6. **Multi-Asset Support**: Extend to derivatives, FX, fixed income with asset-specific rules
