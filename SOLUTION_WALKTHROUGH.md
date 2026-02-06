# Intelligent Order Parameter Prefill — Solution Walkthrough

This document walks through the solution step-by-step, demonstrating how the intelligent prefill system works in practice.

---

## Step 1: The Trading Dashboard

When the application loads, the trader sees:

- **Market Data Table** — live streaming prices for 10 NSE instruments (RELIANCE, TCS, INFY, etc.) updated every 2 seconds via WebSocket. Shows LTP, bid/ask, spread, volatility, day change, and time to close.
- **Order Blotter** — real-time view of all orders with status, fill progress, and management actions.
- **"New Order" button** — opens the order ticket dialog.
- **Quick Order** — hovering over any row in the market data table reveals a quick-order button that pre-fills the symbol.

---

## Step 2: Opening the Order Ticket

The order ticket dialog opens with a **Smart Prefill toggle** enabled by default (top-right). The trader sees an empty form with standard fields.

**Two things trigger the intelligence:**
1. Selecting a **Counterparty** (client)
2. Selecting a **Symbol**

As soon as both are selected, the system fires a prefill request to the backend.

---

## Step 3: The Prefill Engine in Action

### What happens behind the scenes:

```
Client selected: CLIENT_XYZ    →  Tag: "eod_compliance", Risk: 60/100
Symbol selected: RELIANCE       →  ADV: 5M shares, Sector: Energy
                                    LTP: ~₹2,450, Volatility: ~1.8%

Historical Query:
  → CLIENT_XYZ has 5 past RELIANCE orders
  → 4/5 used VWAP, 1 used POV
  → Avg aggression: Medium
  → Median quantity: 210,000

Cross-Client Query:
  → 8 similar-sized RELIANCE orders across all clients
  → 62% used VWAP, 25% used POV

Urgency Computation:
  → Base: 50
  → EOD compliance tag: +12
  → Time to close (e.g. 90min): +10
  → Risk aversion 60: -1.5
  → = 70/100 (Active zone)

Scenario: "EOD Compliance Execution"
```

### What the trader sees:

The form auto-fills with a purple-blue glow animation, and a **Prefill Summary Card** appears at the top:

```
┌─────────────────────────────────────────────────────────┐
│ 🎯 EOD Compliance Execution          Urgency: 70/100   │
│                                                         │
│ Client has EOD compliance pattern — VWAP distributes    │
│ execution over remaining 90min to ensure fill by close  │
│                                                         │
│ [← More Passive]  ════════════●══════  [More Urgent →]  │
│   Patient   Moderate  Balanced  Active    Urgent        │
│                                                         │
│ Drag to adjust — all parameters cascade automatically   │
│ (system suggested 70)                                   │
│                                                         │
│ ▸ Show why other algorithms were not chosen             │
└─────────────────────────────────────────────────────────┘
```

Each auto-filled field shows a **✨ sparkle icon** with a **confidence percentage**. Hovering reveals the explanation.

---

## Step 4: The "Turn the Knob" — Urgency Slider

This is the signature feature. The urgency slider at 70/100 means:

| Parameter                | Value at Urgency 70           |
|--------------------------|-------------------------------|
| Algo Type                | VWAP ✨ 90%                   |
| Order Type               | LIMIT ✨ 80%                  |
| Aggression               | High ✨ 75%                   |
| Volume Curve             | Front-loaded ✨ 75%           |
| Time Window              | ~35% of remaining session     |
| TIF                      | GFD ✨ 85%                    |
| Get Done                 | Yes ✨ 80%                    |

### Demo: Dragging the slider

**Drag to 30 (Patient zone):**

| Parameter    | Changes to...                |
|--------------|------------------------------|
| Algo Type    | VWAP (still, but for patience)|
| Aggression   | Low                          |
| Volume Curve | Historical                   |
| Time Window  | 75% of remaining session     |
| Get Done     | No                           |

**Drag to 90 (Urgent zone):**

| Parameter    | Changes to...                |
|--------------|------------------------------|
| Algo Type    | POV or Direct                |
| Aggression   | High                         |
| Time Window  | 20% of session (or minimum)  |
| TIF          | IOC                          |
| Get Done     | Yes                          |

The trader watches the entire form shift as they drag — one control, many parameters. This is the "broader direction" the problem statement asks for.

### Quick-Adjust Buttons

For fine control, **"More Passive"** and **"More Urgent"** buttons nudge by ±10, with debounced API re-computation.

---

## Step 5: Why-Not Explanations

Clicking "Show why other algorithms were not chosen" expands:

```
✗ NONE: Direct execution skipped — order is 4.2% of ADV. A single
  market order this size would cause 1-3 bps of market impact.

✗ POV: POV not ideal for EOD compliance — it targets a fixed
  participation rate but doesn't guarantee completion by close.
  VWAP with back-loaded curve better ensures timely fill.

✗ ICEBERG: ICEBERG considered but VWAP better fits the order's
  size-to-volume ratio and client preferences.
```

This builds **trader trust** — they can see the system considered alternatives and has reasons for its choice.

---

## Step 6: Order Notes NLP (Sample Case 2)

The problem statement describes: *"An electronic order comes before market open. Order notes: 'VWAP must complete by 2pm'."*

### Demo flow:

1. Select any client + symbol
2. Type in Order Notes: **"VWAP must complete by 2pm"**
3. The NLP engine extracts:
   - `algo_hint = "VWAP"` (from the word "VWAP")
   - `deadline = "14:00"` (from "by 2pm")
   - `get_done = true` (from "must complete")
4. The prefill response:
   - Forces algo = VWAP (confidence 95%)
   - Sets end_time = 14:00
   - Enables Get Done
   - Scenario: "EOD Compliance Execution"
   - Explanation: "Order notes explicitly request VWAP" / "End time from order notes deadline: 14:00"

Other NLP examples:
- **"Minimize market impact, no rush"** → urgency_hint=low, ICEBERG suggested
- **"Urgent fill ASAP"** → urgency_hint=high, direct MARKET order
- **"Benchmark: arrival price"** → POV suggested, benchmark=arrival
- **"Max participation 15%"** → POV constraint extracted

---

## Step 7: Client Profiling in Action

Each of the 5 seeded clients demonstrates a different behavior:

### CLIENT_XYZ — "XYZ Capital Partners" (EOD Compliance)
- **Risk Aversion**: 60 (Moderate)
- **Tag**: eod_compliance
- **Pattern**: 15 historical orders, 73% VWAP, back-loaded curves, near-close timing
- **Prefill behavior**: Suggests VWAP with back-loaded curve, Get Done = Yes, window to 15:30

### CLIENT_ABC — "ABC Asset Management" (Stealth)
- **Risk Aversion**: 75 (Conservative)
- **Tag**: stealth
- **Pattern**: 12 orders, 65% ICEBERG, low aggression
- **Prefill behavior**: Suggests ICEBERG with small display quantity, Low aggression

### CLIENT_DEF — "DEF Hedge Fund" (Arrival Price)
- **Risk Aversion**: 40 (Moderately Aggressive)
- **Tag**: arrival_price
- **Pattern**: 14 orders, 60% POV, medium-high aggression, large blocks
- **Prefill behavior**: Suggests POV with 12-15% participation, arrival price in notes

### CLIENT_GHI — "GHI Pension Fund" (Conservative)
- **Risk Aversion**: 85 (Very Conservative)
- **Tag**: conservative
- **Restricted**: TATAMOTORS (auto sector)
- **Pattern**: 10 orders, 70% VWAP, low aggression
- **Prefill behavior**: Suggests VWAP with historical curve, Low aggression, low urgency

### CLIENT_JKL — "JKL Proprietary Trading" (HFT)
- **Risk Aversion**: 15 (Very Aggressive)
- **Tag**: hft
- **Pattern**: 18 orders, 75% direct (NONE), high aggression, small quantities
- **Prefill behavior**: Suggests Direct execution, IOC TIF, high urgency

---

## Step 8: Historical Pattern Blending

The engine doesn't just use rules — it learns from history.

### Example: CLIENT_XYZ + RELIANCE

The system finds 5 historical orders for this pair:
- 4 used VWAP, 1 used POV
- Average aggression: Medium
- Median quantity: 210,000
- Historical volatility when orders were placed: ~2.1%

**Blending logic:**
- Rule weight: 70% → Rules suggest VWAP (EOD compliance)
- History weight: 30% → History confirms VWAP (80% match)
- **Result**: VWAP with 93% confidence (rule + history agree)

If rules and history disagree (e.g., rules say POV but history says VWAP), the system checks if current market conditions match historical conditions. If similar → follow history. If different → follow rules with a note about historical preference.

---

## Step 9: Market Microstructure Awareness

The prefill engine uses real-time market signals:

| Signal | How It's Used |
|--------|---------------|
| **Time to close** | <15min → MARKET order, high urgency; <60min → shorter windows |
| **Volatility** | >3% → LIMIT order preferred, lower aggression |
| **Spread (bps)** | Wide spread → passive algo preferred |
| **Avg trade size** | Determines POV min/max sizes, ICEBERG display quantity |
| **Size vs ADV** | >20% → ICEBERG; 10-20% → VWAP; 3-10% → POV; <3% → Direct |

---

## Step 10: The Complete Order Ticket

The enhanced order ticket includes all standard trading fields plus the new intelligent additions:

### Primary Fields
- Counterparty (client) — triggers profiling
- Symbol — triggers market data lookup
- Account — auto-selected from client's default
- Direction (BUY/SELL)
- Order Type (Market/Limit/Stop Loss) ✨ prefilled
- Quantity ✨ prefilled from history
- Limit Price ✨ prefilled with urgency-based offset

### New Fields
- **Time In Force** (GFD/IOC/FOK/GTC/GTD) ✨ prefilled
- **Get Done** toggle ✨ prefilled
- **Capacity** (Agency/Principal/etc.)

### Execution Strategy
- Algo Type (Direct/POV/VWAP/ICEBERG) ✨ prefilled
- Start Time / End Time ✨ prefilled
- Algo-specific parameters (all ✨ prefilled):
  - POV: target participation %, min/max order size, aggression
  - VWAP: volume curve, max volume %, aggression
  - ICEBERG: display quantity, aggression

### Notes & Context
- Order Notes ✨ auto-generated from context
- Risk Profile slider (from client, adjustable)

---

## Step 11: Order Confirmation & Execution

After the trader reviews and (optionally adjusts) the prefilled form:

1. Click **"BUY RELIANCE"** → **Confirmation Dialog** appears
2. Dialog shows all parameters including TIF, urgency, capacity, get-done
3. Click **"Execute Trade"** → Order submitted to execution engine
4. Order appears in blotter with **WORKING** status
5. Execution engine processes fills based on algo type:
   - **POV**: Participates at target % of volume each tick
   - **VWAP**: Distributes along volume curve (front/back/historical)
   - **ICEBERG**: Shows display quantity, refills when consumed
   - **Direct**: Fills at market/limit price
6. Real-time WebSocket updates show fill progress in the blotter

---

## Step 12: Analytics & Audit Trail

The Analytics page provides:

- **Candlestick charts** with volume histograms (1m/5m/15m intervals)
- **Browsable tables** for all instruments, clients, orders, executions, market data
- **Order history audit trail** — every lifecycle event logged with details
- **Pagination and filtering** for large datasets

---

## Demo Script (Recommended Flow)

For a live demonstration, follow this sequence:

### Part 1: EOD Compliance (Sample Case 1)
1. Open New Order
2. Select **CLIENT_XYZ** → note risk profile loads (60, Moderate)
3. Select **RELIANCE** → watch prefill fire
4. Point out: Scenario card says "EOD Compliance Execution"
5. Point out: VWAP selected, back-loaded curve, Get Done = Yes
6. **Drag urgency slider** from 70 down to 20 → watch everything shift to Patient mode
7. Drag back up to 85 → watch everything shift to Urgent mode
8. Click "Show why other algorithms were not chosen" → explain trust-building
9. Submit the order → show it in blotter

### Part 2: Order Notes NLP (Sample Case 2)
1. Open New Order
2. Select **CLIENT_ABC** + **INFY**
3. Notice: ICEBERG suggested (stealth client)
4. Type in Order Notes: **"VWAP must complete by 2pm"**
5. Re-trigger prefill (change direction to SELL and back, or toggle prefill off/on)
6. Show: Algo switches to VWAP, end time = 14:00, Get Done = Yes
7. Explanation shows "Order notes explicitly request VWAP"

### Part 3: Different Client Personalities
1. Open New Order with **CLIENT_JKL** (HFT) + **SBIN**
2. Notice: Direct execution, IOC, high urgency (~85)
3. Compare: Open New Order with **CLIENT_GHI** (Pension) + **ITC**
4. Notice: VWAP, historical curve, low aggression, urgency ~25

### Part 4: The Knob
1. With any client/symbol selected, slowly drag the urgency slider from 0 to 100
2. Narrate each zone change and the parameters that shift
3. Emphasize: "One control, all parameters cascade. The trader sets intent, the system fills in the details."

---

## Technical Highlights for Evaluators

1. **No ML dependency** — runs instantly, no training data, fully deterministic and explainable
2. **69 seeded historical orders** — realistic patterns the engine discovers and blends
3. **Real-time market simulation** — geometric Brownian motion with per-stock volatility profiles
4. **Order execution simulation** — POV/VWAP/ICEBERG with realistic slippage and fill mechanics
5. **Full WebSocket streaming** — market data + order updates, no polling
6. **Type-safe end-to-end** — TypeScript frontend, Pydantic backend, SQLite with CHECK constraints
7. **Zero external dependencies** for intelligence — no OpenAI, no ML libraries, pure Python logic
