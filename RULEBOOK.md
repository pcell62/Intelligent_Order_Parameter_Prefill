# Intelligent Order Parameter Prefill — Complete Rulebook

> Every field on the order ticket is computed through a layered decision engine.
> This document breaks down **every rule**, the **exact conditions** that fire it, **why it exists**,
> and how it connects to the rest of the system.

---

## Table of Contents

1. [Urgency Score](#1-urgency-score) — the master variable
2. [Algo Type](#2-algo-type) — the most complex decision
3. [Order Type](#3-order-type)
4. [Limit Price](#4-limit-price)
5. [Time In Force (TIF)](#5-time-in-force)
6. [Get Done](#6-get-done)
7. [Time Window](#7-time-window)
8. [Aggression Level](#8-aggression-level)
9. [POV Parameters](#9-pov-parameters)
10. [VWAP Parameters](#10-vwap-parameters)
11. [ICEBERG Parameters](#11-iceberg-parameters)
12. [Quantity Hint](#12-quantity-hint)
13. [Order Notes Template](#13-order-notes-template)
14. [Scenario Detection](#14-scenario-detection)
15. [Why-Not Explanations](#15-why-not-explanations)
16. [Cross-Cutting: Historical Blending](#16-historical-blending)
17. [Cross-Cutting: Cross-Client Signals](#17-cross-client-signals)
18. [Cross-Cutting: Order Notes NLP](#18-order-notes-nlp)

---

## 1. Urgency Score

**File:** `prefill_service.py` → `_compute_urgency_score()`

Urgency is the **single most important computed value** in the entire system. It starts at a baseline of **50** and is adjusted by ~15 independent factors. The final score (clamped 0–100) cascades to control algo type, order type, limit price offset, TIF, aggression, time window, and get-done.

### 1.1 Adjustment Table

| Factor | Condition | Delta | Why |
|--------|-----------|-------|-----|
| **Time to close** | < 10 min | **+35** | Near close, unfilled orders become overnight risk or compliance violations. The trader has almost no margin for error. |
| | < 20 min | **+25** | Tight but not critical — still need to push toward completion. |
| | < 30 min | **+18** | Approaching the "danger zone" where algos may not have enough runway. |
| | < 60 min | **+10** | Mild time pressure — should factor into but not dominate the decision. |
| | > 240 min | **−10** | Full session ahead — no reason to rush. Patience improves price. |
| **Client tag** | `eod_compliance` | **+12** | These clients have regulatory mandates to complete by close. |
| | `hft` | **+18** | Prop desks value microseconds — speed is their edge. |
| | `stealth` | **−12** | These clients specifically want to be invisible. Rushing defeats the purpose. |
| | `conservative` | **−15** | Pension funds and restricted mandates prefer minimal market footprint. |
| | `arrival_price` | **+5** | Slight urgency to minimize drift from entry — but not rushing. |
| **Order size** | > 20% ADV | **−12** | A whale order MUST be patient or it will move the market against itself. |
| | > 10% ADV | **−5** | Significant size needs caution but isn't extreme. |
| | < 2% ADV | **+10** | Tiny relative to daily flow — can be absorbed instantly. |
| | < 5% ADV | **+5** | Small enough that the market won't notice. |
| **Volatility** | > 3% | **−8** | In volatile markets, aggressive execution risks adverse fills. |
| | < 1.5% | **+5** | Calm markets mean fills are predictable — safe to move faster. |
| **Notes: urgency** | "urgent", "asap", "rush", etc. | **+20** | Trader is explicitly telling us to hurry. |
| **Notes: patience** | "patient", "no rush", "stealth" | **−15** | Trader explicitly wants patience. |
| **Notes: get done** | "must complete", "get done" | **+12** | Completion mandate — implicit time pressure. |
| **Notes: deadline** | Deadline < 30 min away | **+20** | Deadline is imminent — functionally equivalent to close pressure. |
| | Deadline < 60 min away | **+10** | Deadline approaching but manageable. |
| **Risk aversion** | `(50 − risk_aversion) × 0.15` | **±7.5 max** | Conservative clients (risk=80) get −4.5; aggressive clients (risk=15) get +5.25. Light influence — doesn't dominate but tilts the score. |

### 1.2 Why Urgency Matters

Urgency is the "turn the knob" variable. When a trader drags the urgency slider in the UI, **every other field recascades automatically**:

- Urgency **85+** → algo goes to NONE (direct), order type becomes MARKET, TIF becomes IOC
- Urgency **70+** → aggression goes to High, time window shrinks to 35% of remaining session
- Urgency **< 25** → ICEBERG/VWAP chosen for patience, aggression goes Low, window stretches to 75%

Without urgency, the system has no unified way to express "how quickly must this fill?"

### 1.3 Code Location

```python
# prefill_service.py, line 176
def _compute_urgency_score(time_to_close, tag, size_pct_adv, volatility,
                           notes_intent, risk_aversion) -> int:
    score = 50  # baseline
    # ... all adjustments ...
    return max(0, min(100, int(score)))
```

---

## 2. Algo Type

**File:** `prefill_service.py` → `compute_prefill()`, algo type section

This is the most complex field. It follows a strict **priority chain** — the first matching rule wins.

### 2.1 Priority Chain

#### Priority A: Order Notes Override (confidence 95%)

| Notes contain | Algo | Why |
|---------------|------|-----|
| `"vwap"` | VWAP | Trader explicitly requested it. The system's job is to listen, not argue. |
| `"pov"` or `"percentage of volume"` | POV | Same — explicit intent. |
| `"iceberg"` or `"hidden"` | ICEBERG | Same — explicit intent. |

**Why this is highest priority:** A trader typing "use vwap" into the notes field is giving a direct instruction. No heuristic should override human intent. This is the #1 trust-building feature.

#### Priority B: High Urgency + Small Order (confidence 85%)

| Condition | Algo | Why |
|-----------|------|-----|
| Urgency ≥ 85 AND size < 5% ADV | NONE (direct) | When you need maximum speed on a small order, adding an algorithm only introduces latency. The order can be absorbed in a single sweep. |

#### Priority C: Client Profile Tag Rules (confidence 85–90%)

| Client Tag | Algo | Why |
|------------|------|-----|
| `eod_compliance` | VWAP | These clients must fill by close. VWAP distributes execution along the volume curve, ensuring the order participates in every interval and reaches completion by the end of the session. |
| `stealth` | ICEBERG | These clients want to be invisible. ICEBERG shows only a small "display quantity" on the order book — the market never sees the true size, preventing front-running and information leakage. |
| `arrival_price` | POV | These clients benchmark against the price at order entry. POV controls exactly what percentage of market volume you consume, keeping execution near the arrival price by matching the market's rhythm. |
| `hft` + size < 2% ADV | NONE | Prop desks trade small and fast. An algo adds latency and complexity for no benefit on a sub-2% order. Direct access is their competitive advantage. |

**Why tags exist:** Client profiles encode *institutional behavior* that doesn't change between orders. A pension fund always wants low impact; a prop desk always wants speed. Tagging avoids re-deriving this on every order.

#### Priority D: Urgency × Size Matrix (confidence 60–75%)

This is the fallback when no notes override or tag rule applies.

**High Urgency (≥ 75):**

| Size (% ADV) | Algo | Why |
|---------------|------|-----|
| > 10% | POV | Large + urgent = you need controlled speed. POV participates at a set rate of market volume, ensuring you fill quickly without dominating the tape. |
| 3–10% | POV | Mid-size at high urgency still benefits from controlled participation. |
| < 3% | NONE | Small + urgent = just send it. No algo overhead needed. |

**Low Urgency (≤ 25):**

| Size (% ADV) | Algo | Why |
|---------------|------|-----|
| > 15% | ICEBERG | Large + patient = classic stealth accumulation scenario. Hide the true size, refill the display quantity, and let the market come to you over hours. |
| 5–15% | VWAP | Moderate size with no rush = distribute along the volume curve for best average price. VWAP's "set it and forget it" approach is perfect for patient orders. |
| < 5% | NONE | Small + patient = there's nothing to optimize. Direct execution is simpler and cheaper. |

**Medium Urgency (26–74):**

| Size (% ADV) | Algo | Why |
|---------------|------|-----|
| > 20% | ICEBERG | Even at medium urgency, an order this large needs to hide. 20%+ of daily volume showing on the book would cause a price run. |
| 10–20% | VWAP | Significant but not massive — VWAP provides steady distribution without revealing size. |
| 3–10% | POV | Mid-size, mid-urgency = POV is the "Goldilocks" algo. It participates proportionally without being too aggressive or too passive. |
| < 3% | NONE | Tiny order, normal urgency = direct execution is fine. |

#### Priority E: Historical Blending (weight 10–30%)

If ≥ 3 past orders exist for the same client+symbol pair, history gets a weight of 10–30% (scaling with order count). The rule-based pick gets the remaining weight.

**Condition check:** History only overrides when market conditions are similar. The system computes a "volatility ratio" (`min(current_vol, hist_vol) / max(current_vol, hist_vol)`). If `hist_weight × condition_similarity ≥ 0.20`, the historical preference wins.

**Why:** Institutional traders repeat patterns for good reason — they've learned what works for their flow. If Client XYZ always uses VWAP for RELIANCE in 2% volatility, the system should follow that when conditions match. But it should NOT blindly copy a calm-market preference into a 4% volatility crash.

#### Priority F: Cross-Client Signal (annotation only)

If ≥ 5 similar-sized filled orders exist for this symbol across ALL clients, and 60%+ use a specific algo, this is mentioned in the explanation text but **does not override** the chosen algo.

**Why:** This is "wisdom of the crowd." If 70% of all clients use ICEBERG for 500K+ RELIANCE orders, there's probably a structural reason (illiquidity at that size). Even as a non-binding hint, it gives the trader intelligence they wouldn't see otherwise.

### 2.2 Code Location

```python
# prefill_service.py, lines 628–745
# Priority A: notes_intent.get("algo_hint")
# Priority B: urgency >= 85 and size_pct_adv < 5
# Priority C: tag-based rules
# Priority D: urgency × size matrix
# Priority E: historical blending
# Priority F: cross-client annotation
```

---

## 3. Order Type

**File:** `prefill_service.py` → order type section

### 3.1 Decision Table

| # | Condition | Result | Confidence | Why |
|---|-----------|--------|------------|-----|
| 1 | Algo ≠ NONE | LIMIT | 80% | Algos manage their own timing, but you still need a price ceiling/floor. A MARKET order with an algo would let it fill at any price — defeating the purpose of controlled execution. |
| 2 | Urgency ≥ 85 | MARKET | 85% | When the trader needs guaranteed immediate execution (closing a hedge, expiry day), the risk of a LIMIT order not filling outweighs the risk of slippage. Certainty > price. |
| 3 | Time to close < 15 min | MARKET | 85% | With 15 minutes left, a LIMIT that doesn't fill means the order goes unexecuted overnight — potentially a compliance violation, margin call, or unhedged position. |
| 4 | Volatility > 3% | LIMIT | 75% | In whippy markets, a MARKET order can slip significantly between order submission and fill. LIMIT provides a cap/floor on the fill price. |
| 5 | Default | LIMIT | 60% | All else equal, LIMIT is safer. It prevents adverse fills and gives the trader price control. The lower confidence (60%) means the system isn't strongly opinionated. |
| 6 | History (5+ orders) | Follow client | varies | If a client always uses MARKET despite rules suggesting LIMIT, they probably have an internal reason (e.g., compliance requires guaranteed fills). Respect the pattern. |

### 3.2 Code Location

```python
# prefill_service.py, lines 750–781
```

---

## 4. Limit Price

**File:** `prefill_service.py` → limit price section

Only computed when `order_type == "LIMIT"` and `LTP > 0`.

### 4.1 Offset Table

| # | Condition | Offset (bps) | Why |
|---|-----------|-------------|-----|
| 1 | Urgency ≥ 75 | 18 | High urgency means the trader is willing to pay more for fill certainty. 18 bps above LTP (for buys) gives room for the price to drift up and still get filled. |
| 2 | Urgency ≥ 50 | 12 | Moderate urgency — a balanced offset that increases fill probability without overpaying. |
| 3 | Time to close < 30 min | 15 | Near close, the opportunity cost of non-fill is high. Widen the limit slightly to stay executable. |
| 4 | Volatility > 2.5% | 12 | In volatile stocks, the price can jump 10+ bps in seconds. A tight limit would get leapfrogged, so we widen the buffer. |
| 5 | Default | 8 | Calm market, no urgency = a tight 8 bps offset provides price protection with minimal premium. |

### 4.2 Application

- **BUY:** `limit = LTP × (1 + offset/10000)` → set *above* current price
- **SELL:** `limit = LTP × (1 − offset/10000)` → set *below* current price
- **Rounding:** Result is rounded to the instrument's tick size (e.g., 0.05 for NSE). Exchanges reject prices not on valid tick increments.

### 4.3 Why Basis Points

Basis points (1 bps = 0.01%) scale with the stock price. An 18 bps offset on a ₹2,450 stock is ₹4.41; on a ₹100 stock it's ₹0.18. Using absolute values would be biased toward cheap stocks.

### 4.4 Code Location

```python
# prefill_service.py, lines 786–807
```

---

## 5. Time In Force

**File:** `prefill_service.py` → TIF section

TIF determines **how long** the order stays alive if not immediately filled.

### 5.1 Decision Table — Direct Orders (algo = NONE)

| Condition | TIF | Why |
|-----------|-----|-----|
| Urgency ≥ 90 | **IOC** (Immediate or Cancel) | At extreme urgency, any delay is unacceptable. IOC fills whatever liquidity is available *right now* and cancels the rest. No resting order, no information leakage. |
| Urgency ≥ 80 | **FOK** (Fill or Kill) | "All or nothing." Used when partial fills are worse than no fill — e.g., hedging a specific options position where a 60% hedge is useless. |
| Urgency ≥ 65 | **IOC** | Grab what's available immediately. Unlike FOK, partial fills are acceptable. |
| Default | **GFD** (Good For Day) | Standard intraday validity. The order rests in the book until filled or session close. Safe default for most orders. |

### 5.2 Decision Table — Algo Orders (algo ≠ NONE)

| Condition | TIF | Why |
|-----------|-----|-----|
| Urgency ≥ 85 + get-done | **GFD** | Algos manage their own timing — urgency is expressed through aggression and time window, not TIF. GFD gives the algo the full session. |
| Urgency ≥ 70 | **GFD** | Same reasoning — algo handles urgency internally. |
| Time to close > 375 min (full day) | **GTC** | With a full session ahead and low urgency, Good Till Cancel allows the order to carry over to the next session if not fully filled. |
| Default | **GFD** | Standard for intraday algo execution. |

### 5.3 Override Chain

1. **Historical preference** (3+ orders): If a client consistently uses a specific TIF, follow it.
2. **Order notes NLP**: If notes contain "IOC", "fill or kill", "good for day", etc., those override everything at 95% confidence.

### 5.4 Why TIF Matters

Without TIF, every order implicitly rests in the book until session end. This is dangerous for:
- **HFT desks:** A resting order leaks their position intent. IOC ensures nothing lingers.
- **Hedging orders:** A partial hedge is sometimes worse than no hedge (FOK prevents this).
- **Multi-day strategies:** GTC allows patient accumulation across sessions.

### 5.5 Code Location

```python
# prefill_service.py, lines 812–868
```

---

## 6. Get Done

**File:** `prefill_service.py` → get-done section

A boolean flag that tells the execution engine: **this order MUST complete, even if it means crossing the spread aggressively in the final minutes.**

### 6.1 Activation Conditions (any one triggers it)

| Condition | Why |
|-----------|-----|
| Order notes contain "must be done", "get done", "ensure fill", "guaranteed fill" | Trader is explicitly requesting guaranteed completion. |
| Client tag is `eod_compliance` | Regulatory mandate — these orders must be 100% filled by close. |
| Urgency ≥ 75 | High urgency implies strong fill expectations. |
| History shows get-done used >50% of the time (3+ orders) | The client historically treats this symbol as must-complete. Pattern speaks louder than a single order. |

### 6.2 What Get Done Does

When an order has `get_done = true`:
- The execution engine switches from passive to aggressive in the final 15–20% of the time window
- The end time is set to market close (15:30) if not already
- It appears in the auto-generated notes as "Get Done: must complete"
- It influences the scenario detection (triggers "EOD Compliance Execution" when combined with <90 min to close)

### 6.3 Why It Matters

Without Get Done, an algo might reach 15:28 with 15% of the order unfilled and simply let it expire. For a compliance-driven client, that's a regulatory breach. For a hedging desk, that's an overnight unhedged position. Get Done is the safety net that says "completion is non-negotiable."

### 6.4 Code Location

```python
# prefill_service.py, lines 610–615 (inference), lines 873–887 (suggestion)
```

---

## 7. Time Window

**File:** `prefill_service.py` → time window section

Only applies when `algo ≠ NONE`. Defines the start and end times within which the algo is allowed to execute.

### 7.1 Start Time

| Rule | Why |
|------|-----|
| Current time, rounded up to the nearest 5-minute mark | Clean intervals prevent odd timestamps like 14:37 that don't align with exchange reporting periods. |
| Clamped to market hours: 09:15 – 15:30 | Can't trade outside session. If current time is before open, start at open. If past close, start 30 min before close (error recovery). |

### 7.2 End Time — Priority Chain

| # | Condition | End Time | Why |
|---|-----------|----------|-----|
| 1 | Deadline from notes (e.g., "by 2pm") | 14:00 (parsed) | A deadline in the notes is a hard constraint from the trader or client. "By 2pm" means the algo must complete before 14:00. |
| 2 | EOD compliance OR get-done | Market close (15:30) | These orders must complete within the session. Setting end time to close gives the algo maximum runway. |
| 3 | Time to close < 60 min | Market close (15:30) | Less than an hour left — no point in setting an earlier end time. Use all remaining time. |
| 4 | Otherwise: urgency-based fraction | Calculated | The fraction of remaining session time allocated to the algo varies with urgency. |

### 7.3 Urgency → Window Fraction

| Urgency | Fraction | Example (3 hrs left) | Why |
|---------|----------|---------------------|-----|
| ≥ 70 | 35% | ~63 min | High urgency → compressed window → algo must be aggressive to complete in a short timeframe. Forces faster execution. |
| ≥ 50 | 55% | ~99 min | Moderate urgency → balanced window. The algo has enough time to be thoughtful but not leisurely. |
| < 50 | 75% | ~135 min | Low urgency → maximum window. The algo can spread execution across most of the remaining session, minimizing market impact. |

### 7.4 Why the Fraction Matters

A fixed window (e.g., "always use 65% of remaining time") can't distinguish between:
- An urgent order that should fill in the next 30 minutes
- A patient order that should spread across 3 hours

The urgency-based fraction ensures the time window **matches the trader's intent**. An urgent order with a long window risks the algo being too passive; a patient order with a short window risks unnecessary market impact.

### 7.5 Deadline Parsing

The NLP parser extracts deadlines from free text:
- `"by 2pm"` → `14:00`
- `"complete by 14:30"` → `14:30`
- `"before 3pm"` → `15:00`
- `"by close"` / `"by end of day"` → `15:30`

### 7.6 Code Location

```python
# prefill_service.py, lines 892–946
```

---

## 8. Aggression Level

**File:** `prefill_service.py` → aggression section

Controls *how* the algo executes each slice: passively (post at our price and wait) or aggressively (cross the spread and take liquidity).

### 8.1 Base Rule (urgency-driven)

| Urgency | Aggression | Why |
|---------|-----------|-----|
| ≥ 70 | **High** | Cross the spread, take liquidity. You pay more per share but fill faster. When urgency is high, speed is worth the extra cost. |
| 35–69 | **Medium** | Execute at mid-price or LTP. A balanced approach that doesn't overpay but doesn't rest passively either. |
| < 35 | **Low** | Post passive orders at the bid (for buys). Cheapest fills but slowest execution. Perfect when there's no time pressure. |

### 8.2 Risk Aversion Override

| Condition | Override | Why |
|-----------|---------|-----|
| Risk aversion ≥ 70 AND urgency < 70 | **Low** | A conservative pension fund should never have High aggression even under moderate urgency. Their mandate prohibits aggressive market-taking. The risk aversion override protects the client's investment philosophy. |
| Risk aversion ≤ 29 AND urgency ≥ 30 | **High** | An aggressive prop desk with low risk aversion should be pushed to High even at moderate urgency. Their tolerance for market impact is high, and speed is valued. |

**Note:** Risk aversion does NOT override when `urgency ≥ 70` and the client is conservative — time pressure wins over preference because non-completion is worse than paying extra spread.

### 8.3 Historical Blend (5+ orders)

If the client has 5+ historical orders for this symbol, the system computes their average aggression (Low=1, Medium=2, High=3) and follows the historical average.

**Why:** Some clients always trade passively on certain symbols (perhaps they know the stock is liquid enough). Respecting this saves the trader from manually overriding every time.

### 8.4 Code Location

```python
# prefill_service.py, lines 951–980
```

---

## 9. POV Parameters

**File:** `prefill_service.py` → POV section

POV (Percentage of Volume) targets a fixed percentage of market volume. These parameters fine-tune its behavior.

### 9.1 Target Participation Rate

| Urgency | Size (% ADV) | Rate | Why |
|---------|-------------|------|-----|
| ≥ 75 | < 10% | **20%** | High urgency + manageable size → participate aggressively. At 20% of volume, you're a significant but not dominant player. Fills happen quickly. |
| ≥ 75 | ≥ 10% | **15%** | High urgency but large size → slightly lower participation to avoid signaling. Even urgent large orders need some restraint. |
| ≥ 50 | < 10% | **12%** | Moderate urgency → standard participation. Fills steadily without being too visible. |
| ≥ 50 | ≥ 10% | **10%** | Moderate urgency + large size → conservative participation. Blends with normal flow. |
| any | > 15% ADV | **5%** | Very large order regardless of urgency → minimal participation. If you ARE 15% of daily volume, participating at more than 5% per interval would make you the dominant player, signaling your intent. |
| any | < 60 min to close | **18%** | Time pressure overrides size concerns. Need to fill before the bell. |
| default | | **10%** | Standard rate for balanced execution. |

### 9.2 Min/Max Order Size

| Parameter | Formula | Why |
|-----------|---------|-----|
| Min size | `max(50, avg_trade_size × 0.3)` | Child orders smaller than typical trade size look suspicious on the tape — they signal algorithmic execution. Flooring at 30% of average trade size helps slices blend into normal flow. Absolute floor of 50 prevents absurdly small orders. |
| Max size | `max(min_size × 10, avg_trade_size × 3)` | Caps individual slices so no single child order is so large it spikes the price. 3x the average trade size is the upper bound of "normal-looking" flow. |

### 9.3 Code Location

```python
# prefill_service.py, lines 986–1013
```

---

## 10. VWAP Parameters

**File:** `prefill_service.py` → VWAP section

VWAP (Volume Weighted Average Price) distributes execution along a volume curve to match the day's benchmark.

### 10.1 Volume Curve

| # | Condition | Curve | Why |
|---|-----------|-------|-----|
| 1 | Urgency ≥ 65 | **Front-loaded** | Concentrates execution in the first 40% of the window. Fills the majority of the order early, ensuring completion even if later intervals are thin. Trades VWAP tracking quality for fill certainty. |
| 2 | Tag = `eod_compliance` | **Back-loaded** | Concentrates volume toward the close. For compliance clients who need to match the closing price or fill in the closing auction, back-loading ensures the order's weight falls where it matters most. |
| 3 | Time to close < 90 min | **Front-loaded** | Limited runway — front-load to ensure the order completes before the bell. Better to overshoot early than undershoot late. |
| 4 | Default | **Historical** | Follows the stock's historical intraday volume pattern (usually U-shaped: heavy at open/close, light midday). Produces the best VWAP tracking because you trade when the market trades. |

### 10.2 Max Volume Percentage

| Size (% ADV) | Max Vol % | Why |
|---------------|----------|-----|
| > 10% | **25%** | Large orders can tolerate higher per-interval participation because they need to fill a lot. 25% is the upper limit before you start dominating the interval. |
| > 5% | **15%** | Mid-size orders should be more conservative. 15% per interval keeps the footprint moderate. |
| ≤ 5% | **20%** | Small orders can afford slightly higher participation — the absolute volume is small even at 20%. |

### 10.3 Code Location

```python
# prefill_service.py, lines 1015–1036
```

---

## 11. ICEBERG Parameters

**File:** `prefill_service.py` → ICEBERG section

ICEBERG orders hide the true size by showing only a "display quantity" on the order book, refilling it as it gets consumed.

### 11.1 Display Quantity

**Formula:** `min(qty × 8%, avg_trade_size × 1.5)`, floored at 100 shares.

| Component | Value | Why |
|-----------|-------|-----|
| `qty × 8%` | Percentage of total order | Never reveals more than 8% of true intent. On a 1M share order, that's 80,000 — large enough to attract fills but small enough to look like a normal institutional order. |
| `avg_trade_size × 1.5` | Relative to normal flow | The display should "blend in" with the market's natural trade sizes. At 1.5x the average, it looks like a slightly-larger-than-normal order — unremarkable. |
| `min(...)` | Take the smaller of the two | Conservative approach — we want the display quantity to be hidden both as a percentage of total AND relative to market flow. |
| Floor: 100 | Absolute minimum | Below 100 shares, orders look suspicious — too small for an institutional player. |

### 11.2 Why Hiding Size Matters

When the market sees a 1M share buy order on the book, every other participant knows:
1. There's a large buyer (information)
2. The price will likely go up (anticipation)
3. They should buy first and sell to you at a higher price (front-running)

ICEBERG prevents this by showing only 8,000 shares at a time. The market sees a normal order, fills it, and the ICEBERG refills. This process repeats ~125 times until the full 1M shares are filled — all without anyone knowing the true size.

### 11.3 Code Location

```python
# prefill_service.py, lines 1038–1049
```

---

## 12. Quantity Hint

**File:** `prefill_service.py` → quantity hint section

Only suggested when the trader hasn't entered a quantity.

### 12.1 Logic

- **Source:** Median quantity from past client+symbol orders
- **Fallback:** Average quantity if median isn't available

### 12.2 Confidence Scaling

```
confidence = 0.4 + min(0.3, order_count × 0.04)
```

| Past Orders | Confidence | Why |
|-------------|-----------|-----|
| 3 | 52% | Just enough history to suggest, but not confident. |
| 5 | 60% | Moderate history — median is stabilizing. |
| 7 | 68% | Good history — pattern is clear. |
| 8+ | 70% (cap) | Capped at 70% because quantity varies more than other fields. Even with rich history, the trader may want a different size today. |

### 12.3 Why It Exists

When a trader repeatedly buys 200,000 shares of RELIANCE for client XYZ, pre-filling 200,000 saves time and prevents typos. Typing "20000" instead of "200000" is a 10x error that could cost millions. The conservative confidence (never above 70%) ensures the system suggests without overstepping.

### 12.4 Code Location

```python
# prefill_service.py, lines 1054–1060
```

---

## 13. Order Notes Template

**File:** `prefill_service.py` → notes template section

Auto-assembles structured notes from context flags. These become part of the audit trail.

### 13.1 Template Components

| Condition | Note Added | Why |
|-----------|-----------|-----|
| Tag = `eod_compliance` | `"EOD compliance required"` | Marks the order for regulatory purposes. Auditors can filter by this. |
| Tag = `stealth` | `"Minimize market impact — stealth execution"` | Documents the execution intent for post-trade analysis. |
| Tag = `arrival_price` | `"Benchmark: arrival price (₹X.XX)"` | Records the arrival price for later benchmark comparison (was the algo good?). |
| Size > 15% ADV | `"Large block: X.X% of ADV"` | Flags the order as large relative to daily volume. Important for post-trade impact analysis. |
| Get-done active | `"Get Done: must complete"` | Documents the completion mandate. Critical for compliance: "we activated get-done because X." |
| Deadline from notes | `"Deadline: HH:MM"` | Records the parsed deadline so the execution engine and audit trail both know the hard stop. |

### 13.2 Why Auto-Notes Matter

When a regulator asks "why did you execute this order using ICEBERG?", the notes immediately show:
> `Minimize market impact — stealth execution | Large block: 22.3% of ADV | Get Done: must complete`

Without auto-notes, the trader would have to reconstruct the reasoning months later from scattered logs. Structured notes are the compliance team's best friend.

### 13.3 Code Location

```python
# prefill_service.py, lines 1065–1082
```

---

## 14. Scenario Detection

**File:** `prefill_service.py` → `_detect_scenario()`

Assigns a human-readable label to the current execution context. Displayed prominently in the order ticket UI.

### 14.1 Scenario Table

| # | Condition | Tag | Label | Why This Scenario |
|---|-----------|-----|-------|-------------------|
| 1 | Tag = `eod_compliance` OR (get-done + <90 min) | `eod_compliance` | **EOD Compliance Execution** | The order must fill by close under regulatory or client mandate. All parameters should bias toward completion. |
| 2 | Tag = `stealth` OR (>20% ADV + urgency <40) | `stealth_execution` | **Stealth / Minimal Impact** | The order needs to be invisible. Large size with low urgency = classic "accumulate without being detected." |
| 3 | Tag = `arrival_price` OR notes benchmark = arrival | `arrival_benchmark` | **Arrival Price Benchmark** | The client will judge execution quality against the price at order entry. Parameters should minimize drift from that price. |
| 4 | Urgency > 80 OR <15 min to close | `speed_priority` | **Speed Priority** | Time is the dominant constraint. Everything else (price, impact) is secondary to getting filled. |
| 5 | Urgency < 25 AND >120 min to close | `patient_accumulation` | **Patient Accumulation** | Maximum patience — plenty of time, no urgency. The algo should spread execution as widely as possible. |
| 6 | Default | `standard` | **Standard Execution** | No special scenario detected. Balanced approach. |

### 14.2 Why Scenario Detection Matters

Scenarios provide a **one-glance summary** of the system's understanding. Instead of the trader parsing 12 individual field suggestions, they see "Scenario: EOD Compliance Execution" and immediately know:
- **Trust:** "Yes, the system understood my client's mandate."
- **Error detection:** If it says "Speed Priority" but the trader intended patient accumulation, they instantly know the suggestions are wrong.
- **Compliance mapping:** Scenarios map to pre-approved execution strategies that compliance has signed off on. The audit trail shows which strategy was applied and why.

### 14.3 Code Location

```python
# prefill_service.py, lines 423–435
```

---

## 15. Why-Not Explanations

**File:** `prefill_service.py` → `_generate_why_not()`

For each algo that was **not** chosen, a context-specific explanation is generated.

### 15.1 Example Explanations

| Unchosen Algo | Context | Why-Not Text |
|---------------|---------|-------------|
| NONE | Size > 3% ADV | "Direct execution skipped — order is 15.2% of ADV. A single market order this size would cause 4–12 bps of market impact. An algorithm can slice it to reduce footprint." |
| POV | Tag = `eod_compliance` | "POV not ideal for EOD compliance — it targets a fixed participation rate but doesn't guarantee completion by close. VWAP with back-loaded curve better ensures timely fill." |
| POV | Size > 20% ADV | "POV risky for very large orders (22.1% ADV) — fixed participation at this size would signal large buyer/seller to the market." |
| VWAP | Time to close < 20 min | "VWAP not recommended — only 12min to close. Insufficient time window for meaningful volume-weighted distribution." |
| VWAP | Tag = `stealth` + size > 15% | "VWAP less suitable for stealth — it follows predictable volume patterns that sophisticated counterparties can detect. ICEBERG better hides intent." |
| ICEBERG | Size < 3% ADV | "ICEBERG unnecessary — order is only 1.8% of ADV. The full quantity can be absorbed without significant market impact." |
| ICEBERG | Urgency > 75 | "ICEBERG too slow for current urgency — it reveals only small slices at a time, which limits fill speed. A more aggressive algo is needed." |

### 15.2 Why This Matters

This is the most important **transparency** feature. Traders want to know not just "why ICEBERG" but "why NOT VWAP" and "why NOT POV." Why-not explanations:
- **Preempt questions:** The trader doesn't need to ask "what about VWAP?" — the answer is already there.
- **Educate junior traders:** A new trader learns WHY VWAP is bad near close by reading the explanation.
- **Compliance evidence:** The audit trail shows all alternatives were considered and rejected for specific reasons, not randomly.
- **Build trust:** The system shows it evaluated the full picture, not just picked one answer.

### 15.3 Code Location

```python
# prefill_service.py, lines 442–526
```

---

## 16. Historical Blending

**File:** `prefill_service.py` → `_get_historical_pattern()`

A cross-cutting concern that affects algo type, order type, TIF, aggression, and quantity.

### 16.1 How It Works

1. **Query:** Fetch the last 10 orders for this client+symbol pair
2. **Compute statistics:**
   - `preferred_algo` — mode (most common) algo type
   - `preferred_order_type` — mode order type
   - `preferred_tif` — mode TIF
   - `avg_aggression` — numeric average (Low=1, Medium=2, High=3)
   - `median_quantity` / `avg_quantity`
   - `get_done_freq` — fraction of orders with get-done enabled
   - `avg_hist_volatility` / `avg_hist_spread` — market conditions at time of past orders
3. **Weight:** `hist_weight = min(0.30, max(0.0, (count − 2) × 0.10))`

| Order Count | Weight | Meaning |
|-------------|--------|---------|
| < 3 | 0% | Not enough history. Rules dominate. |
| 3 | 10% | Light influence. |
| 4 | 20% | Moderate influence. |
| 5+ | 30% (cap) | Strong influence, but rules still get 70%. |

### 16.2 Condition Similarity Check

Before overriding, the system checks if current market conditions resemble historical ones:

```
vol_ratio = min(current_vol, hist_vol) / max(current_vol, hist_vol)
effective_hist = hist_weight × vol_ratio
```

If `effective_hist < 0.20`, history is noted but doesn't override. This prevents blindly copying a calm-market preference into a volatile environment.

### 16.3 What Gets Blended

| Field | Min Orders to Override | Additional Condition |
|-------|----------------------|---------------------|
| Algo type | 3+ (with condition similarity ≥ 0.20) | Market vol must be similar |
| Order type | 5+ | None |
| TIF | 3+ | None |
| Aggression | 5+ | None |
| Get done | 3+ (frequency > 50%) | None |
| Quantity | 1+ (hint only) | Only when trader hasn't entered one |

### 16.4 Code Location

```python
# prefill_service.py, lines 264–379 (pattern extraction)
# Blending applied at each field's section in compute_prefill()
```

---

## 17. Cross-Client Signals

**File:** `prefill_service.py` → `_get_cross_client_patterns()`

### 17.1 How It Works

1. **Query:** All FILLED orders for this symbol where quantity is within 0.4x–2.5x of the current order
2. **Aggregate:** Count by algo type, compute percentages
3. **Signal:** If the most common algo has ≥60% share across ≥5 orders, mention it in the explanation

### 17.2 Why 0.4x–2.5x Range

The comparison must be size-appropriate. A 10,000-share order and a 1,000,000-share order have completely different execution profiles. The 0.4x–2.5x range captures "similar-ish" orders while filtering out irrelevant extremes.

### 17.3 Why Non-Overriding

Cross-client signals are **informational only** — they appear in the explanation but never change the chosen algo. This is because:
- Different clients have different mandates (a pension fund and a prop desk shouldn't copy each other)
- The signal could reflect a bygone market condition
- It's most useful as "here's what the market is doing" intelligence

### 17.4 Code Location

```python
# prefill_service.py, lines 386–416 (query)
# prefill_service.py, lines 734–741 (annotation)
```

---

## 18. Order Notes NLP

**File:** `prefill_service.py` → `_parse_order_notes()`

Extracts structured intent from free-text order notes using regex pattern matching.

### 18.1 What Gets Extracted

| Feature | Patterns Recognized | Output |
|---------|-------------------|--------|
| **Algo hint** | "vwap", "pov", "percentage of volume", "iceberg", "hidden" | `algo_hint: "VWAP"/"POV"/"ICEBERG"` |
| **Deadline** | "by 2pm", "before 14:30", "complete by 3pm", "by close", "by end of day" | `deadline: "14:00"` / `"15:30"` |
| **Urgency** | "urgent", "asap", "rush", "critical", "time sensitive" → high; "patient", "no rush", "stealth", "low footprint" → low | `urgency_hint: "high"/"low"` |
| **Get done** | "must be done", "must complete", "get done", "ensure fill", "guaranteed fill" | `get_done: true` |
| **Benchmark** | "arrival" → arrival; "vwap" + "benchmark" → vwap; "close"/"closing" + "benchmark" → close | `benchmark: "arrival"/"vwap"/"close"` |
| **TIF hint** | "IOC", "immediate or cancel", "FOK", "fill or kill", "GFD", "good for day", etc. | `tif_hint: "IOC"/"FOK"/...` |
| **Constraints** | "max participation 15%" | `constraints: [{type, value}]` |

### 18.2 Priority

Order notes NLP has the **highest priority** for algo type (95% confidence) and TIF (95% confidence). When a trader types an explicit instruction, the system follows it without question.

### 18.3 Debouncing in the UI

The frontend debounces notes changes by 800ms before re-triggering the prefill API. This prevents excessive API calls while the trader is mid-sentence.

### 18.4 Code Location

```python
# prefill_service.py, lines 72–169
```

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    ORDER TICKET (UI)                      │
│  Client + Symbol selected → triggers prefill API call     │
│  Urgency slider change → debounced re-prefill (400ms)     │
│  Notes change → debounced re-prefill (800ms)              │
└────────────────────────┬─────────────────────────────────┘
                         │ POST /api/prefill
                         ▼
┌──────────────────────────────────────────────────────────┐
│                   PREFILL ENGINE                          │
│                                                          │
│  1. Parse order notes (NLP)                              │
│  2. Fetch historical patterns (client+symbol, last 10)   │
│  3. Fetch cross-client patterns (same symbol, ±size)     │
│  4. Compute urgency score (15 factors → 0-100)           │
│  5. Infer get-done flag                                  │
│  6. Detect scenario                                      │
│  7. For each field:                                      │
│     a. Apply priority chain (notes > tags > urgency×size)│
│     b. Blend with history (10-30% weight)                │
│     c. Annotate cross-client signal                      │
│     d. Generate explanation + confidence                 │
│  8. Generate why-not for unchosen algos                  │
│                                                          │
│  Returns: suggestions, explanations, confidence,          │
│           urgency_score, scenario, why_not                │
└──────────────────────────────────────────────────────────┘
```

---

## Data Flow Summary

| Input | Used By | How |
|-------|---------|-----|
| Client profile notes | `_client_tag()` | Keyword scan → tag classification |
| Client risk_aversion | Urgency score, aggression override | Numeric (0=aggressive, 100=conservative) |
| Order notes (user-typed) | `_parse_order_notes()` | Regex NLP → algo hint, deadline, urgency, get-done, TIF |
| Instrument ADV | Size % ADV calculation | `qty / adv × 100` |
| Market volatility | Urgency, limit offset, why-not | Real-time from market data service |
| Market time_to_close | Urgency, time window, scenario | Minutes until 15:30 |
| Market avg_trade_size | POV min/max, ICEBERG display | Determines what "normal" trade flow looks like |
| Historical orders (last 10) | All blended fields | Statistical summaries (mode, median, mean) |
| Cross-client orders | Algo explanation | Percentage distribution of algo choices |
| Urgency slider (UI) | All cascading fields | Override auto-computed urgency → re-prefill all params |
