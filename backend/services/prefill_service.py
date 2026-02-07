"""
Prefill Service — Intelligent order parameter suggestions.

Key capabilities:
  1. Rule-based engine  (client profile, instrument, market conditions, size)
  2. Historical pattern blending  (client-symbol order history)
  3. Cross-client pattern analysis  (what do similar orders look like?)
  4. Order-notes NLP  (extract algo hint, deadline, urgency from free text)
  5. Urgency meta-score  ("turn the knob" — one number cascades to all params)
  6. Why-not explanations  (why each alternative algo was *not* chosen)
  7. Scenario detection  (EOD Compliance, Stealth, Arrival Benchmark, …)

Every suggestion includes an explanation string and a confidence score.

ALL numeric thresholds are loaded from the rule_config database table via
RuleConfig (aliased RC).  The second argument to every RC.get*() call is the
fallback default — identical to the original hard-coded value — so the engine
behaves exactly the same even if the DB table is empty.
"""

import json
import math
import re
import statistics
from collections import Counter
from datetime import datetime, time as dtime, timedelta
from typing import Any
from database import get_db
from services.rule_config_service import RuleConfig as RC

MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)


# ──────────────────────────────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────────────────────────────

def _minutes_to_close() -> int:
    now = datetime.now().time()
    close_dt = datetime.combine(datetime.today(), MARKET_CLOSE)
    now_dt = datetime.combine(datetime.today(), now)
    diff = (close_dt - now_dt).total_seconds() / 60
    return max(0, int(diff))


def _format_time(t: dtime) -> str:
    return t.strftime("%H:%M")


def _round_to_tick(price: float, tick_size: float) -> float:
    return round(round(price / tick_size) * tick_size, 2)


# ──────────────────────────────────────────────────────────────────────
# 1. Client tagging
# ──────────────────────────────────────────────────────────────────────

def _client_tag(notes: str) -> str:
    lower = notes.lower()
    if "eod" in lower or "close" in lower or "compliance" in lower:
        return "eod_compliance"
    if "stealth" in lower or "minimize" in lower or "impact" in lower:
        return "stealth"
    if "arrival" in lower or "benchmark" in lower or "block" in lower:
        return "arrival_price"
    if "conservative" in lower or "restricted" in lower:
        return "conservative"
    if "high frequency" in lower or "hf" in lower or "proprietary" in lower:
        return "hft"
    return "default"


# ──────────────────────────────────────────────────────────────────────
# 2. Order-notes NLP
# ──────────────────────────────────────────────────────────────────────

def _parse_order_notes(notes: str) -> dict:
    """
    Extract structured intent from free-text order notes.

    Returns dict with keys:
        algo_hint   — "VWAP", "POV", "ICEBERG", or None
        deadline    — "HH:MM" string or None
        urgency_hint — "high" / "low" / None
        get_done    — bool
        benchmark   — "arrival" / "vwap" / "close" / None
        constraints — list of extracted constraints
    """
    if not notes:
        return {}
    lower = notes.lower()
    result: dict[str, Any] = {
        "algo_hint": None,
        "deadline": None,
        "urgency_hint": None,
        "get_done": False,
        "benchmark": None,
        "constraints": [],
    }

    # ── Algo hints ──
    if "vwap" in lower:
        result["algo_hint"] = "VWAP"
    elif "pov" in lower or "percentage of volume" in lower:
        result["algo_hint"] = "POV"
    elif "iceberg" in lower or "hidden" in lower:
        result["algo_hint"] = "ICEBERG"

    # ── Deadline patterns: "by 2pm", "must complete by 14:00", "before 2:30pm" ──
    time_patterns = [
        r"(?:by|before|complete\s+by|finish\s+by|done\s+by)\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?",
        r"(?:by|before)\s+(\d{1,2})\s*(am|pm)",
    ]
    for pat in time_patterns:
        m = re.search(pat, lower)
        if m:
            groups = m.groups()
            h = int(groups[0])
            mins = int(groups[1]) if groups[1] else 0
            ampm = groups[-1] if groups[-1] else None
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            if 0 <= h <= 23 and 0 <= mins <= 59:
                result["deadline"] = f"{h:02d}:{mins:02d}"
            break

    # ── "by close" / "by end of day" → deadline = market close ──
    if not result["deadline"]:
        if re.search(r"by\s+(close|eod|end\s+of\s+day|market\s+close)", lower):
            result["deadline"] = "15:30"

    # ── Urgency signals ──
    urgent_words = ["urgent", "asap", "immediately", "must complete", "critical",
                    "time sensitive", "rush", "fast", "quick"]
    patient_words = ["patient", "no rush", "take time", "slow", "passive",
                     "minimize impact", "stealth", "low footprint"]
    if any(w in lower for w in urgent_words):
        result["urgency_hint"] = "high"
    elif any(w in lower for w in patient_words):
        result["urgency_hint"] = "low"

    # ── Get-done flag ──
    if re.search(r"(must\s+(be\s+)?(done|complete|fill)|get\s+done|ensure\s+fill|guaranteed\s+fill)", lower):
        result["get_done"] = True

    # ── Benchmark ──
    if "arrival" in lower:
        result["benchmark"] = "arrival"
    elif "vwap" in lower and "benchmark" in lower:
        result["benchmark"] = "vwap"
    elif "close" in lower and ("benchmark" in lower or "closing" in lower):
        result["benchmark"] = "close"

    # ── TIF hints ──
    if re.search(r"\bioc\b|immediate\s+or\s+cancel", lower):
        result["tif_hint"] = "IOC"
    elif re.search(r"\bfok\b|fill\s+or\s+kill", lower):
        result["tif_hint"] = "FOK"
    elif re.search(r"\bgtc\b|good\s+till\s+cancel", lower):
        result["tif_hint"] = "GTC"
    elif re.search(r"\bgtd\b|good\s+till\s+date", lower):
        result["tif_hint"] = "GTD"
    elif re.search(r"\bgfd\b|good\s+for\s+day|day\s+order", lower):
        result["tif_hint"] = "GFD"

    # ── Numeric constraints ──
    # "max participation 15%"
    m = re.search(r"max\s+(?:participation|volume)\s*[:\-]?\s*(\d+)\s*%", lower)
    if m:
        result["constraints"].append({"type": "max_participation", "value": int(m.group(1))})

    return result


# ──────────────────────────────────────────────────────────────────────
# 3. Urgency score computation  (ALL thresholds from RC)
# ──────────────────────────────────────────────────────────────────────

def _compute_urgency_score(
    time_to_close: int,
    tag: str,
    size_pct_adv: float,
    volatility: float,
    notes_intent: dict,
    risk_aversion: int,
) -> tuple[int, list[dict]]:
    """
    Compute an urgency score from 0 (patient) to 100 (urgent).
    This is the "turn the knob" base value.

    Returns (score, breakdown) where breakdown is a list of
    {"factor": str, "detail": str, "delta": int} dicts.
    """
    baseline = RC.get_int("urgency.baseline", 50)
    score = baseline
    breakdown: list[dict] = [{"factor": "Baseline", "detail": "Starting value", "delta": baseline}]

    # ── Time pressure ──
    time_delta = 0
    time_detail = f"{time_to_close} min to close"
    if time_to_close < RC.get_int("urgency.time_close_critical_min", 10):
        time_delta = RC.get_int("urgency.time_close_critical_delta", 35)
        time_detail = f"{time_to_close} min to close (critical)"
    elif time_to_close < RC.get_int("urgency.time_close_tight_min", 20):
        time_delta = RC.get_int("urgency.time_close_tight_delta", 25)
        time_detail = f"{time_to_close} min to close (tight)"
    elif time_to_close < RC.get_int("urgency.time_close_approaching_min", 30):
        time_delta = RC.get_int("urgency.time_close_approaching_delta", 18)
        time_detail = f"{time_to_close} min to close (approaching)"
    elif time_to_close < RC.get_int("urgency.time_close_mild_min", 60):
        time_delta = RC.get_int("urgency.time_close_mild_delta", 10)
        time_detail = f"{time_to_close} min to close (mild pressure)"
    elif time_to_close > RC.get_int("urgency.time_open_plenty_min", 240):
        time_delta = RC.get_int("urgency.time_open_plenty_delta", -10)
        time_detail = f"{time_to_close} min to close (plenty of time)"
    if time_delta != 0:
        score += time_delta
        breakdown.append({"factor": "Time Pressure", "detail": time_detail, "delta": time_delta})

    # ── Client profile ──
    tag_delta = 0
    if tag == "eod_compliance":
        tag_delta = RC.get_int("urgency.tag_eod_compliance", 12)
    elif tag == "hft":
        tag_delta = RC.get_int("urgency.tag_hft", 18)
    elif tag == "stealth":
        tag_delta = RC.get_int("urgency.tag_stealth", -12)
    elif tag == "conservative":
        tag_delta = RC.get_int("urgency.tag_conservative", -15)
    elif tag == "arrival_price":
        tag_delta = RC.get_int("urgency.tag_arrival_price", 5)
    if tag_delta != 0:
        score += tag_delta
        breakdown.append({"factor": "Client Profile", "detail": f"Tag: {tag}", "delta": tag_delta})

    # ── Order size ── (larger orders need patience)
    size_delta = 0
    size_detail = f"{size_pct_adv:.1f}% of ADV"
    if size_pct_adv > 20:
        size_delta = RC.get_int("urgency.size_above_20pct_delta", -12)
        size_detail = f"{size_pct_adv:.1f}% of ADV (very large)"
    elif size_pct_adv > 10:
        size_delta = RC.get_int("urgency.size_above_10pct_delta", -5)
        size_detail = f"{size_pct_adv:.1f}% of ADV (large)"
    elif size_pct_adv < 2:
        size_delta = RC.get_int("urgency.size_below_2pct_delta", 10)
        size_detail = f"{size_pct_adv:.1f}% of ADV (small)"
    elif size_pct_adv < 5:
        size_delta = RC.get_int("urgency.size_below_5pct_delta", 5)
        size_detail = f"{size_pct_adv:.1f}% of ADV (moderate)"
    if size_delta != 0:
        score += size_delta
        breakdown.append({"factor": "Order Size", "detail": size_detail, "delta": size_delta})

    # ── Volatility ── (high vol → more careful)
    vol_delta = 0
    if volatility > RC.get_float("urgency.vol_high_threshold", 3.0):
        vol_delta = RC.get_int("urgency.vol_high_delta", -8)
        score += vol_delta
        breakdown.append({"factor": "Volatility", "detail": f"{volatility:.2f}% (high)", "delta": vol_delta})
    elif volatility < RC.get_float("urgency.vol_low_threshold", 1.5):
        vol_delta = RC.get_int("urgency.vol_low_delta", 5)
        score += vol_delta
        breakdown.append({"factor": "Volatility", "detail": f"{volatility:.2f}% (low)", "delta": vol_delta})

    # ── Notes intent ──
    if notes_intent.get("urgency_hint") == "high":
        d = RC.get_int("urgency.notes_high_delta", 20)
        score += d
        breakdown.append({"factor": "Order Notes", "detail": "Urgent language detected", "delta": d})
    elif notes_intent.get("urgency_hint") == "low":
        d = RC.get_int("urgency.notes_low_delta", -15)
        score += d
        breakdown.append({"factor": "Order Notes", "detail": "Patient language detected", "delta": d})
    if notes_intent.get("get_done"):
        d = RC.get_int("urgency.notes_get_done_delta", 12)
        score += d
        breakdown.append({"factor": "Get Done Flag", "detail": "Must-fill intent in notes", "delta": d})
    if notes_intent.get("deadline"):
        # If deadline is soon, add urgency
        try:
            dl_parts = notes_intent["deadline"].split(":")
            dl_min = int(dl_parts[0]) * 60 + int(dl_parts[1])
            now = datetime.now()
            now_min = now.hour * 60 + now.minute
            mins_until = dl_min - now_min
            if 0 < mins_until < RC.get_int("urgency.deadline_imminent_min", 30):
                d = RC.get_int("urgency.deadline_imminent_delta", 20)
                score += d
                breakdown.append({"factor": "Deadline", "detail": f"{mins_until} min away (imminent)", "delta": d})
            elif 0 < mins_until < RC.get_int("urgency.deadline_approaching_min", 60):
                d = RC.get_int("urgency.deadline_approaching_delta", 10)
                score += d
                breakdown.append({"factor": "Deadline", "detail": f"{mins_until} min away (approaching)", "delta": d})
        except (ValueError, IndexError):
            pass

    # ── Risk aversion (light influence) ──
    # 0=aggressive → push up, 100=conservative → push down
    risk_delta = int((50 - risk_aversion) * RC.get_float("urgency.risk_aversion_factor", 0.15))
    if risk_delta != 0:
        score += risk_delta
        label = "aggressive" if risk_delta > 0 else "conservative"
        breakdown.append({"factor": "Risk Aversion", "detail": f"Risk aversion {risk_aversion}/100 ({label})", "delta": risk_delta})

    final = max(0, min(100, int(score)))
    raw_total = sum(b["delta"] for b in breakdown)
    if final != raw_total:
        breakdown.append({"factor": "Clamped", "detail": "Score clamped to 0-100 range", "delta": final - raw_total})

    return final, breakdown


# ──────────────────────────────────────────────────────────────────────
# 4. Historical pattern analysis
# ──────────────────────────────────────────────────────────────────────

def _get_historical_pattern(client_id: str, symbol: str) -> dict:
    """Query the last N orders for this client–symbol pair and compute
    statistical summaries for blending with rule-based suggestions."""
    db = get_db()
    query_limit = RC.get_int("historical.query_limit", 10)
    try:
        rows = db.execute("""
            SELECT o.algo_type, o.order_type, o.direction, o.quantity,
                   o.algo_params, o.order_notes, o.created_at, o.limit_price,
                   o.avg_fill_price, o.tif, o.urgency, o.get_done
            FROM orders o
            WHERE o.client_id = ? AND o.symbol = ?
            ORDER BY o.created_at DESC
            LIMIT ?
        """, (client_id, symbol, query_limit)).fetchall()

        if not rows:
            return {}

        algo_list = [r["algo_type"] or "NONE" for r in rows]
        algo_counter = Counter(algo_list)
        preferred_algo = algo_counter.most_common(1)[0][0]

        order_type_list = [r["order_type"] for r in rows]
        preferred_order_type = Counter(order_type_list).most_common(1)[0][0]

        quantities = [r["quantity"] for r in rows]
        median_qty = int(statistics.median(quantities))
        avg_qty = sum(quantities) // len(quantities)

        # Aggression average (Low=1, Med=2, High=3)
        agg_map = {"low": 1, "medium": 2, "high": 3}
        agg_vals = []
        for r in rows:
            try:
                p = json.loads(r["algo_params"] or "{}")
                lvl = p.get("aggression_level", "").lower()
                if lvl in agg_map:
                    agg_vals.append(agg_map[lvl])
            except (json.JSONDecodeError, AttributeError):
                pass
        avg_agg_num = statistics.mean(agg_vals) if agg_vals else 2.0
        avg_aggression = "Low" if avg_agg_num <= 1.4 else ("High" if avg_agg_num >= 2.6 else "Medium")

        # Last algo_params for preferred algo
        last_params: dict = {}
        for r in rows:
            if (r["algo_type"] or "NONE") == preferred_algo:
                try:
                    last_params = json.loads(r["algo_params"] or "{}")
                except json.JSONDecodeError:
                    pass
                break

        # TIF mode
        tif_list = [r["tif"] for r in rows if r["tif"]]
        preferred_tif = Counter(tif_list).most_common(1)[0][0] if tif_list else "GFD"

        # Average urgency
        urgency_vals = [r["urgency"] for r in rows if r["urgency"] is not None]
        avg_urgency = int(statistics.mean(urgency_vals)) if urgency_vals else 50

        # Get-done frequency
        gd_vals = [r["get_done"] for r in rows if r["get_done"] is not None]
        get_done_freq = sum(gd_vals) / len(gd_vals) if gd_vals else 0.0

        # Market conditions at order time
        market_conditions = _correlate_market_conditions(db, symbol, rows)
        avg_hist_vol = avg_hist_spread = 0.0
        if market_conditions:
            vols = [m["volatility"] for m in market_conditions if m["volatility"] > 0]
            spreads = [m["spread_bps"] for m in market_conditions if m["spread_bps"] > 0]
            avg_hist_vol = statistics.mean(vols) if vols else 0.0
            avg_hist_spread = statistics.mean(spreads) if spreads else 0.0

        return {
            "preferred_algo": preferred_algo,
            "preferred_order_type": preferred_order_type,
            "avg_aggression": avg_aggression,
            "median_quantity": median_qty,
            "avg_quantity": avg_qty,
            "order_count": len(rows),
            "last_params": last_params,
            "preferred_tif": preferred_tif,
            "avg_urgency": avg_urgency,
            "get_done_freq": get_done_freq,
            "market_conditions": market_conditions,
            "avg_hist_volatility": round(avg_hist_vol, 3),
            "avg_hist_spread": round(avg_hist_spread, 2),
        }
    finally:
        db.close()


def _correlate_market_conditions(db, symbol: str, order_rows: list) -> list[dict]:
    results = []
    for row in order_rows:
        created_at = row["created_at"]
        if not created_at:
            continue
        snap = db.execute("""
            SELECT ltp, bid, ask, volatility,
                   CASE WHEN ltp > 0
                        THEN ((ask - bid) / ltp) * 10000 ELSE 0 END AS spread_bps
            FROM market_data
            WHERE symbol = ?
              AND ABS(strftime('%s', timestamp) - strftime('%s', ?)) <= 60
            ORDER BY ABS(strftime('%s', timestamp) - strftime('%s', ?)) ASC
            LIMIT 1
        """, (symbol, created_at, created_at)).fetchone()
        if snap:
            results.append({
                "ltp": snap["ltp"],
                "volatility": snap["volatility"],
                "spread_bps": round(snap["spread_bps"], 2),
            })
    return results


# ──────────────────────────────────────────────────────────────────────
# 5. Cross-client pattern analysis
# ──────────────────────────────────────────────────────────────────────

def _get_cross_client_patterns(symbol: str, quantity: int) -> dict:
    """Analyze what all clients do for similar-sized orders on this symbol."""
    db = get_db()
    try:
        qty_low = max(1, int(quantity * RC.get_float("cross_client.qty_low_factor", 0.4)))
        qty_high = int(quantity * RC.get_float("cross_client.qty_high_factor", 2.5))
        rows = db.execute("""
            SELECT algo_type, COUNT(*) as cnt, AVG(urgency) as avg_urg
            FROM orders
            WHERE symbol = ?
              AND quantity BETWEEN ? AND ?
              AND status = 'FILLED'
            GROUP BY algo_type
            ORDER BY cnt DESC
        """, (symbol, qty_low, qty_high)).fetchall()

        if not rows:
            return {}

        total = sum(r["cnt"] for r in rows)
        return {
            "total_similar": total,
            "algo_distribution": {
                r["algo_type"]: {"count": r["cnt"], "pct": round(r["cnt"] / total * 100)}
                for r in rows
            },
            "most_common_algo": rows[0]["algo_type"],
            "avg_urgency": int(rows[0]["avg_urg"]) if rows[0]["avg_urg"] else 50,
        }
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────
# 6. Scenario detection
# ──────────────────────────────────────────────────────────────────────

def _detect_scenario(tag, urgency, time_to_close, size_pct_adv, notes_intent, get_done_likely) -> tuple[str, str]:
    """Detect the best-matching execution scenario."""
    if tag == "eod_compliance" or (get_done_likely and time_to_close < RC.get_int("scenario.eod_time_threshold", 90)):
        return "eod_compliance", "EOD Compliance Execution"
    if tag == "stealth" or (size_pct_adv > RC.get_float("scenario.stealth_size", 20) and urgency < RC.get_int("scenario.stealth_urgency_max", 40)):
        return "stealth_execution", "Stealth / Minimal Impact"
    if tag == "arrival_price" or notes_intent.get("benchmark") == "arrival":
        return "arrival_benchmark", "Arrival Price Benchmark"
    if urgency > RC.get_int("scenario.speed_urgency_min", 80) or time_to_close < RC.get_int("scenario.speed_time", 15):
        return "speed_priority", "Speed Priority"
    if urgency < RC.get_int("scenario.patient_urgency_max", 25) and time_to_close > RC.get_int("scenario.patient_time_min", 120):
        return "patient_accumulation", "Patient Accumulation"
    return "standard", "Standard Execution"


# ──────────────────────────────────────────────────────────────────────
# 7. Why-not explanations
# ──────────────────────────────────────────────────────────────────────

def _generate_why_not(chosen_algo: str, size_pct_adv: float, time_to_close: int,
                      volatility: float, tag: str, urgency: int) -> dict[str, str]:
    """For each algo that was NOT chosen, explain why."""
    why_not = {}
    alternatives = ["NONE", "POV", "VWAP", "ICEBERG"]
    for algo in alternatives:
        if algo == chosen_algo:
            continue
        if algo == "NONE":
            if size_pct_adv > 3:
                why_not["NONE"] = (
                    f"Direct execution skipped — order is {size_pct_adv:.1f}% of ADV. "
                    f"A single market order this size would cause {size_pct_adv * 0.3:.0f}-{size_pct_adv * 0.8:.0f} bps "
                    f"of market impact. An algorithm can slice it to reduce footprint."
                )
            else:
                why_not["NONE"] = (
                    "Direct execution is viable but the selected algo provides better "
                    "price discovery and execution analytics for audit purposes."
                )
        elif algo == "POV":
            if tag == "eod_compliance":
                why_not["POV"] = (
                    "POV not ideal for EOD compliance — it targets a fixed participation rate "
                    "but doesn't guarantee completion by close. VWAP with back-loaded curve "
                    "better ensures timely fill."
                )
            elif urgency < 30:
                why_not["POV"] = (
                    "POV not recommended at low urgency — its fixed participation rate may "
                    "overshoot in low-volume periods. A patient VWAP or ICEBERG is more appropriate."
                )
            elif size_pct_adv > 20:
                why_not["POV"] = (
                    f"POV risky for very large orders ({size_pct_adv:.1f}% ADV) — fixed "
                    f"participation at this size would signal large buyer/seller to the market."
                )
            else:
                why_not["POV"] = (
                    "POV considered but the selected algorithm better matches "
                    "the current market conditions and client execution style."
                )
        elif algo == "VWAP":
            if time_to_close < 20:
                why_not["VWAP"] = (
                    f"VWAP not recommended — only {time_to_close}min to close. "
                    f"Insufficient time window for meaningful volume-weighted distribution."
                )
            elif tag == "stealth" and size_pct_adv > 15:
                why_not["VWAP"] = (
                    "VWAP less suitable for stealth — it follows predictable volume patterns "
                    "that sophisticated counterparties can detect. ICEBERG better hides intent."
                )
            elif urgency > 80:
                why_not["VWAP"] = (
                    "VWAP too passive for current urgency level — it distributes evenly "
                    "over time which may not complete fast enough."
                )
            else:
                why_not["VWAP"] = (
                    "VWAP considered but the selected algorithm better fits the "
                    "order's size-to-volume ratio and client preferences."
                )
        elif algo == "ICEBERG":
            if size_pct_adv < 3:
                why_not["ICEBERG"] = (
                    f"ICEBERG unnecessary — order is only {size_pct_adv:.1f}% of ADV. "
                    f"The full quantity can be absorbed without significant market impact."
                )
            elif urgency > 75:
                why_not["ICEBERG"] = (
                    "ICEBERG too slow for current urgency — it reveals only small slices "
                    "at a time, which limits fill speed. A more aggressive algo is needed."
                )
            elif tag == "arrival_price":
                why_not["ICEBERG"] = (
                    "ICEBERG not ideal for arrival price benchmark — it doesn't control "
                    "participation rate relative to volume. POV provides better arrival price tracking."
                )
            else:
                why_not["ICEBERG"] = (
                    "ICEBERG considered but the selected algorithm provides a better "
                    "balance of speed and market impact for this order profile."
                )
    return why_not


# ──────────────────────────────────────────────────────────────────────
# MAIN ENGINE
# ──────────────────────────────────────────────────────────────────────

def compute_prefill(
    client_id: str,
    symbol: str,
    direction: str,
    quantity: int | None,
    market_data: dict[str, Any],
    urgency_override: int | None = None,
    risk_aversion_override: int | None = None,
    order_notes_input: str | None = None,
) -> dict:
    """
    Main prefill engine.

    Returns:
    {
        "suggestions": { field: value },
        "explanations": { field: reason },
        "confidence":   { field: 0.0-1.0 },
        "urgency_score": int,
        "computed_urgency": int,      # what the system calculated before override
        "scenario_tag": str,
        "scenario_label": str,
        "why_not": { algo: reason },
    }
    """
    db = get_db()
    try:
        client_row = db.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()
        instrument_row = db.execute("SELECT * FROM instruments WHERE symbol = ?", (symbol,)).fetchone()
    finally:
        db.close()

    if not client_row or not instrument_row:
        return {
            "suggestions": {}, "explanations": {}, "confidence": {},
            "urgency_score": 50, "computed_urgency": 50,
            "urgency_breakdown": [{"factor": "Baseline", "detail": "Starting value", "delta": 50}],
            "scenario_tag": "standard", "scenario_label": "Standard Execution",
            "why_not": {},
        }

    client = dict(client_row)
    instrument = dict(instrument_row)
    tag = _client_tag(client.get("notes", ""))
    risk_aversion = risk_aversion_override if risk_aversion_override is not None else client.get("risk_aversion", 50)

    adv = instrument.get("adv", 1_000_000) or 1_000_000
    tick_size = instrument.get("tick_size", 0.05)
    ltp = market_data.get("ltp", 0)
    bid = market_data.get("bid", ltp)
    ask = market_data.get("ask", ltp)
    volatility = market_data.get("volatility", 2.0)
    avg_trade_size = market_data.get("avg_trade_size", 500)
    time_to_close = market_data.get("time_to_close", _minutes_to_close())
    spread_bps = market_data.get("spread_bps", 5.0)

    # ── Parse order notes ──
    notes_intent = _parse_order_notes(order_notes_input or "")

    # ── Historical patterns ──
    history = _get_historical_pattern(client_id, symbol)
    hist_count = history.get("order_count", 0)

    _min_start = RC.get_int("historical.min_orders_start", 3)
    _max_wt = RC.get_float("historical.max_weight", 0.30)
    _wt_step = RC.get_float("historical.weight_per_order", 0.10)
    hist_weight = min(_max_wt, max(0.0, (hist_count - (_min_start - 1)) * _wt_step)) if hist_count >= _min_start else 0.0
    rule_weight = 1.0 - hist_weight

    # ── Size metrics ──
    qty = quantity or history.get("median_quantity") or history.get("avg_quantity") or int(adv * 0.05)
    size_pct_adv = (qty / adv) * 100 if adv > 0 else 0

    # ── Cross-client patterns ──
    cross = _get_cross_client_patterns(symbol, qty)

    # ── Compute urgency ──
    computed_urgency, urgency_breakdown = _compute_urgency_score(
        time_to_close, tag, size_pct_adv, volatility, notes_intent, risk_aversion
    )
    urgency = urgency_override if urgency_override is not None else computed_urgency

    # ── Get-done inference ──
    _gd_thresh = RC.get_int("get_done.urgency_threshold", 75)
    _gd_freq = RC.get_float("historical.get_done_freq", 0.50)
    get_done_likely = (
        notes_intent.get("get_done", False)
        or tag == "eod_compliance"
        or urgency >= _gd_thresh
        or (hist_count >= _min_start and history.get("get_done_freq", 0) > _gd_freq)
    )

    # ── Scenario ──
    scenario_tag, scenario_label = _detect_scenario(
        tag, urgency, time_to_close, size_pct_adv, notes_intent, get_done_likely
    )

    suggestions: dict[str, Any] = {}
    explanations: dict[str, str] = {}
    confidence: dict[str, float] = {}

    # ─────────────────────────────────────────────────
    # 1. ALGO TYPE  (urgency-aware)
    # ─────────────────────────────────────────────────
    algo_type = "NONE"
    algo_reason = ""
    algo_conf = 0.5

    # Configurable thresholds for algo selection
    _direct_urg = RC.get_int("algo.direct_urgency_threshold", 85)
    _direct_sz = RC.get_float("algo.direct_size_max", 5)
    _high_urg = RC.get_int("algo.high_urgency_threshold", 75)
    _low_urg = RC.get_int("algo.low_urgency_threshold", 25)
    _hft_sz = RC.get_float("algo.hft_small_size", 2)

    # If notes explicitly request an algo, honour it
    if notes_intent.get("algo_hint"):
        algo_type = notes_intent["algo_hint"]
        algo_reason = f"Order notes explicitly request {algo_type}"
        algo_conf = 0.95
    elif urgency >= _direct_urg and size_pct_adv < _direct_sz:
        algo_type = "NONE"
        algo_reason = (
            f"Very high urgency ({urgency}/100) with small order ({size_pct_adv:.1f}% ADV) "
            f"— direct execution for maximum speed"
        )
        algo_conf = 0.85
    elif tag == "eod_compliance":
        algo_type = "VWAP"
        algo_reason = (
            f"Client has EOD compliance pattern — VWAP distributes execution "
            f"over remaining {time_to_close}min to ensure fill by close"
        )
        algo_conf = 0.9
    elif tag == "stealth":
        algo_type = "ICEBERG"
        algo_reason = "Client prefers stealth execution — ICEBERG hides true size to minimize market impact"
        algo_conf = 0.85
    elif tag == "arrival_price":
        algo_type = "POV"
        algo_reason = "Client benchmarks against arrival price — POV provides controlled participation to minimise slippage"
        algo_conf = 0.85
    elif tag == "hft" and size_pct_adv < _hft_sz:
        algo_type = "NONE"
        algo_reason = f"Small order ({size_pct_adv:.1f}% ADV) for HF client — direct execution for speed"
        algo_conf = 0.8
    else:
        # ── Urgency-driven algo selection ──
        if urgency >= _high_urg:
            _hl = RC.get_float("algo.high_urgency_large_size", 10)
            _hm = RC.get_float("algo.high_urgency_mid_size", 3)
            if size_pct_adv > _hl:
                algo_type = "POV"
                algo_reason = f"High urgency ({urgency}/100) with significant size ({size_pct_adv:.1f}% ADV) — POV for fast controlled participation"
                algo_conf = 0.75
            elif size_pct_adv > _hm:
                algo_type = "POV"
                algo_reason = f"High urgency ({urgency}/100) — POV provides speed while managing impact"
                algo_conf = 0.7
            else:
                algo_type = "NONE"
                algo_reason = f"High urgency ({urgency}/100) with small order — direct execution"
                algo_conf = 0.75
        elif urgency <= _low_urg:
            _ll = RC.get_float("algo.low_urgency_large_size", 15)
            _lm = RC.get_float("algo.low_urgency_mid_size", 5)
            if size_pct_adv > _ll:
                algo_type = "ICEBERG"
                algo_reason = f"Low urgency ({urgency}/100) + large order ({size_pct_adv:.1f}% ADV) — ICEBERG for patient stealth accumulation"
                algo_conf = 0.75
            elif size_pct_adv > _lm:
                algo_type = "VWAP"
                algo_reason = f"Low urgency ({urgency}/100) — VWAP for patient volume-weighted distribution"
                algo_conf = 0.7
            else:
                algo_type = "NONE"
                algo_reason = f"Low urgency + small order ({size_pct_adv:.1f}% ADV) — direct execution sufficient"
                algo_conf = 0.65
        else:
            # Medium urgency — size-driven
            _mvl = RC.get_float("algo.med_very_large_size", 20)
            _ml = RC.get_float("algo.med_large_size", 10)
            _mm = RC.get_float("algo.med_mid_size", 3)
            if size_pct_adv > _mvl:
                algo_type = "ICEBERG"
                algo_reason = f"Large order ({size_pct_adv:.1f}% ADV) — ICEBERG hides size to reduce impact"
                algo_conf = 0.75
            elif size_pct_adv > _ml:
                algo_type = "VWAP"
                algo_reason = f"Significant order ({size_pct_adv:.1f}% ADV) — VWAP distributes evenly"
                algo_conf = 0.7
            elif size_pct_adv > _mm:
                algo_type = "POV"
                algo_reason = f"Mid-size order ({size_pct_adv:.1f}% ADV) — POV balances speed and impact"
                algo_conf = 0.6
            else:
                algo_type = "NONE"
                algo_reason = f"Small order ({size_pct_adv:.1f}% ADV) — direct execution is sufficient"
                algo_conf = 0.65

    # ── Blend with historical ──
    _sim_thresh = RC.get_float("historical.similarity_threshold", 0.20)
    if hist_weight > 0 and history.get("preferred_algo") and not notes_intent.get("algo_hint"):
        hist_algo = history["preferred_algo"]
        if hist_algo != algo_type:
            condition_similarity = 1.0
            avg_hist_vol = history.get("avg_hist_volatility", 0)
            if avg_hist_vol > 0 and volatility > 0:
                condition_similarity = min(volatility, avg_hist_vol) / max(volatility, avg_hist_vol)
            effective_hist = hist_weight * condition_similarity
            if effective_hist >= _sim_thresh:
                rule_algo = algo_type
                algo_type = hist_algo
                algo_reason = (
                    f"Blended: history ({hist_count} orders) prefers {hist_algo} "
                    f"(weight {effective_hist:.0%}), rules suggested {rule_algo}. "
                    f"Market conditions similar (hist vol {avg_hist_vol:.1f}% vs current {volatility:.1f}%)"
                )
                algo_conf = min(0.95, algo_conf * rule_weight + 0.9 * effective_hist)
            else:
                algo_reason += f". Note: client used {hist_algo} in {hist_count} past {symbol} orders"
                algo_conf = min(0.95, algo_conf + hist_weight * 0.1)

    # ── Cross-client signal (light influence) ──
    _cc_min = RC.get_int("cross_client.min_orders", 5)
    _cc_pct = RC.get_int("cross_client.min_pct", 60)
    if cross and cross.get("most_common_algo") and cross["total_similar"] >= _cc_min:
        cross_algo = cross["most_common_algo"]
        cross_pct = cross["algo_distribution"].get(cross_algo, {}).get("pct", 0)
        if cross_algo != algo_type and cross_pct >= _cc_pct:
            algo_reason += (
                f". Market pattern: {cross_pct}% of similar-sized {symbol} orders "
                f"across all clients use {cross_algo}"
            )

    suggestions["algo_type"] = algo_type
    explanations["algo_type"] = algo_reason
    confidence["algo_type"] = round(algo_conf, 2)

    # ─────────────────────────────────────────────────
    # 2. ORDER TYPE
    # ─────────────────────────────────────────────────
    _ot_urg = RC.get_int("order_type.market_urgency", 85)
    _ot_tc = RC.get_int("order_type.market_time_close", 15)
    _ot_vol = RC.get_float("order_type.limit_volatility", 3.0)

    if algo_type != "NONE":
        suggestions["order_type"] = "LIMIT"
        explanations["order_type"] = "LIMIT order recommended with algo execution — provides price protection while algo manages timing"
        confidence["order_type"] = 0.8
    elif urgency >= _ot_urg:
        suggestions["order_type"] = "MARKET"
        explanations["order_type"] = f"Urgency {urgency}/100 — MARKET order for guaranteed immediate fill"
        confidence["order_type"] = 0.85
    elif time_to_close < _ot_tc:
        suggestions["order_type"] = "MARKET"
        explanations["order_type"] = f"Only {time_to_close}min to close — MARKET order for guaranteed fill before session ends"
        confidence["order_type"] = 0.85
    elif volatility > _ot_vol:
        suggestions["order_type"] = "LIMIT"
        explanations["order_type"] = f"High volatility ({volatility:.1f}%) — LIMIT order to avoid adverse fills"
        confidence["order_type"] = 0.75
    else:
        suggestions["order_type"] = "LIMIT"
        explanations["order_type"] = "LIMIT order recommended as default for price control"
        confidence["order_type"] = 0.6

    # Blend with historical
    _min_ot = RC.get_int("historical.min_orders_order_type", 5)
    if hist_weight > 0 and history.get("preferred_order_type"):
        hist_ot = history["preferred_order_type"]
        if hist_ot != suggestions["order_type"] and hist_count >= _min_ot:
            rule_ot = suggestions["order_type"]
            suggestions["order_type"] = hist_ot
            explanations["order_type"] = (
                f"Blended: history favors {hist_ot} ({hist_count} orders), "
                f"rules suggested {rule_ot} — following client preference"
            )
            confidence["order_type"] = round(confidence["order_type"] * rule_weight + 0.85 * hist_weight, 2)

    # ─────────────────────────────────────────────────
    # 3. LIMIT PRICE
    # ─────────────────────────────────────────────────
    if suggestions["order_type"] == "LIMIT" and ltp > 0:
        _lp_hu = RC.get_int("limit_price.high_urgency_threshold", 75)
        _lp_mu = RC.get_int("limit_price.med_urgency_threshold", 50)
        _lp_tc = RC.get_int("limit_price.time_close_threshold", 30)
        _lp_vt = RC.get_float("limit_price.vol_threshold", 2.5)

        if urgency >= _lp_hu:
            offset_bps = RC.get_int("limit_price.high_urgency_offset", 18)
        elif urgency >= _lp_mu:
            offset_bps = RC.get_int("limit_price.med_urgency_offset", 12)
        elif time_to_close < _lp_tc:
            offset_bps = RC.get_int("limit_price.time_close_offset", 15)
        elif volatility > _lp_vt:
            offset_bps = RC.get_int("limit_price.vol_offset", 12)
        else:
            offset_bps = RC.get_int("limit_price.default_offset", 8)

        if direction == "BUY":
            limit_price = _round_to_tick(ltp * (1 + offset_bps / 10000), tick_size)
            explanations["limit_price"] = f"Limit set {offset_bps}bps above LTP (₹{ltp:.2f}) — provides fill probability while capping upside risk"
        else:
            limit_price = _round_to_tick(ltp * (1 - offset_bps / 10000), tick_size)
            explanations["limit_price"] = f"Limit set {offset_bps}bps below LTP (₹{ltp:.2f}) — provides fill probability while protecting downside"

        suggestions["limit_price"] = limit_price
        confidence["limit_price"] = 0.6

    # ─────────────────────────────────────────────────
    # 4. TIF (Time In Force)
    # ─────────────────────────────────────────────────
    if algo_type == "NONE":
        _ioc_ext = RC.get_int("tif.direct_ioc_extreme", 90)
        _fok = RC.get_int("tif.direct_fok", 80)
        _ioc_hi = RC.get_int("tif.direct_ioc_high", 65)

        if urgency >= _ioc_ext:
            suggestions["tif"] = "IOC"
            explanations["tif"] = f"Extreme urgency ({urgency}/100) with direct execution — IOC ensures immediate fill or cancel"
            confidence["tif"] = 0.85
        elif urgency >= _fok:
            suggestions["tif"] = "FOK"
            explanations["tif"] = f"Very high urgency ({urgency}/100) — FOK (Fill or Kill) for all-or-nothing immediate execution"
            confidence["tif"] = 0.8
        elif urgency >= _ioc_hi:
            suggestions["tif"] = "IOC"
            explanations["tif"] = f"High urgency ({urgency}/100) direct order — IOC to fill what's available immediately"
            confidence["tif"] = 0.7
        else:
            suggestions["tif"] = "GFD"
            explanations["tif"] = "Good For Day — standard TIF for intraday direct orders"
            confidence["tif"] = 0.8
    else:
        _gfd_hi = RC.get_int("tif.algo_gfd_high", 85)
        _gfd_mod = RC.get_int("tif.algo_gfd_moderate", 70)
        _gtc_time = RC.get_int("tif.algo_gtc_time", 375)

        if urgency >= _gfd_hi and get_done_likely:
            suggestions["tif"] = "GFD"
            explanations["tif"] = f"GFD with Get Done — algo manages timing within the day, urgency {urgency}/100 handled via aggression"
            confidence["tif"] = 0.85
        elif urgency >= _gfd_mod:
            suggestions["tif"] = "GFD"
            explanations["tif"] = f"GFD — algo execution with high urgency ({urgency}/100) managed through aggression and time window"
            confidence["tif"] = 0.8
        elif time_to_close > _gtc_time:
            suggestions["tif"] = "GTC"
            explanations["tif"] = "Full session ahead with low urgency — GTC allows carry-over if not fully filled today"
            confidence["tif"] = 0.6
        else:
            suggestions["tif"] = "GFD"
            explanations["tif"] = "Good For Day — standard TIF for intraday algo execution"
            confidence["tif"] = 0.75

    # Blend with historical TIF preference
    _min_tif = RC.get_int("historical.min_orders_tif", 3)
    if hist_weight > 0 and history.get("preferred_tif"):
        hist_tif = history["preferred_tif"]
        if hist_tif != suggestions["tif"] and hist_count >= _min_tif:
            rule_tif = suggestions["tif"]
            suggestions["tif"] = hist_tif
            explanations["tif"] = (
                f"Historical preference: client uses {hist_tif} for {symbol} "
                f"({hist_count} orders) — rules suggested {rule_tif}"
            )
            confidence["tif"] = 0.75

    # NLP override — if order notes explicitly mention a TIF, honour it
    if notes_intent.get("tif_hint"):
        tif_from_notes = notes_intent["tif_hint"]
        if tif_from_notes != suggestions["tif"]:
            suggestions["tif"] = tif_from_notes
            explanations["tif"] = f"Order notes explicitly request {tif_from_notes}"
            confidence["tif"] = 0.95

    # ─────────────────────────────────────────────────
    # 5. GET DONE
    # ─────────────────────────────────────────────────
    suggestions["get_done"] = get_done_likely
    if get_done_likely:
        reasons = []
        if tag == "eod_compliance":
            reasons.append("EOD compliance client")
        if notes_intent.get("get_done"):
            reasons.append("order notes indicate must-complete")
        if urgency >= _gd_thresh:
            reasons.append(f"high urgency ({urgency}/100)")
        if not reasons:
            reasons.append("historical pattern shows frequent get-done usage")
        explanations["get_done"] = f"Get Done enabled — {', '.join(reasons)}"
    else:
        explanations["get_done"] = "Get Done not needed — no completion pressure detected"
    confidence["get_done"] = 0.8 if get_done_likely else 0.6

    # ─────────────────────────────────────────────────
    # 6. TIME WINDOW (if algo)
    # ─────────────────────────────────────────────────
    if algo_type != "NONE":
        now = datetime.now()
        start_min = now.minute + (5 - now.minute % 5) if now.minute % 5 else now.minute
        start_time = now.replace(minute=start_min % 60, second=0, microsecond=0)
        if start_min >= 60:
            start_time += timedelta(hours=1)

        market_open_dt = datetime.combine(now.date(), MARKET_OPEN)
        market_close_dt = datetime.combine(now.date(), MARKET_CLOSE)
        if start_time < market_open_dt:
            start_time = market_open_dt
        if start_time >= market_close_dt:
            start_time = market_close_dt - timedelta(minutes=30)

        # Deadline from notes overrides
        end_time = None
        if notes_intent.get("deadline"):
            try:
                dl = notes_intent["deadline"].split(":")
                end_time = now.replace(hour=int(dl[0]), minute=int(dl[1]), second=0, microsecond=0)
                if end_time > market_close_dt:
                    end_time = market_close_dt
            except (ValueError, IndexError):
                pass

        _tw_close = RC.get_int("time_window.close_threshold", 60)
        if end_time is None:
            if tag == "eod_compliance" or get_done_likely:
                end_time = market_close_dt
                time_reason = f"Window runs to market close ({_format_time(MARKET_CLOSE)}) — {'EOD compliance' if tag == 'eod_compliance' else 'get-done'} mode"
            elif time_to_close < _tw_close:
                end_time = market_close_dt
                time_reason = f"Less than {_tw_close}min to close — window extends to {_format_time(MARKET_CLOSE)}"
            else:
                remaining_min = (market_close_dt - start_time).total_seconds() / 60
                _tw_hu = RC.get_int("time_window.high_urgency_threshold", 70)
                _tw_mu = RC.get_int("time_window.med_urgency_threshold", 50)
                if urgency >= _tw_hu:
                    frac = RC.get_float("time_window.high_urgency_fraction", 0.35)
                elif urgency >= _tw_mu:
                    frac = RC.get_float("time_window.med_urgency_fraction", 0.55)
                else:
                    frac = RC.get_float("time_window.low_urgency_fraction", 0.75)
                _min_win = RC.get_int("time_window.min_window_min", 20)
                window_min = max(_min_win, int(remaining_min * frac))
                end_time = start_time + timedelta(minutes=window_min)
                if end_time > market_close_dt:
                    end_time = market_close_dt
                time_reason = f"Window spans {window_min}min (~{int(frac*100)}% of remaining session) — urgency {urgency}/100"
        else:
            time_reason = f"End time from order notes deadline: {_format_time(end_time.time())}"

        suggestions["start_time"] = _format_time(start_time.time())
        suggestions["end_time"] = _format_time(end_time.time())
        explanations["start_time"] = time_reason
        explanations["end_time"] = time_reason
        confidence["start_time"] = 0.75
        confidence["end_time"] = 0.75

    # ─────────────────────────────────────────────────
    # 7. AGGRESSION LEVEL (urgency-driven)
    # ─────────────────────────────────────────────────
    if algo_type != "NONE":
        _ag_hi = RC.get_int("aggression.high_threshold", 70)
        _ag_med = RC.get_int("aggression.med_threshold", 35)

        if urgency >= _ag_hi:
            agg = "High"
            agg_reason = f"High urgency ({urgency}/100) → aggressive execution to ensure timely completion"
        elif urgency >= _ag_med:
            agg = "Medium"
            agg_reason = f"Moderate urgency ({urgency}/100) → balanced approach between speed and impact"
        else:
            agg = "Low"
            agg_reason = f"Low urgency ({urgency}/100) → passive execution to minimize market footprint"

        # Risk aversion override
        _cons_risk = RC.get_int("aggression.conservative_risk", 70)
        _aggr_risk = RC.get_int("aggression.aggressive_risk", 29)
        _aggr_floor = RC.get_int("aggression.aggressive_urgency_floor", 30)

        if risk_aversion >= _cons_risk and urgency < _ag_hi:
            agg = "Low"
            agg_reason = f"Client risk aversion {risk_aversion}/100 overrides to Low aggression (urgency {urgency}/100)"
        elif risk_aversion <= _aggr_risk and urgency >= _aggr_floor:
            if agg != "High":
                agg = "High"
                agg_reason = f"Client risk aversion {risk_aversion}/100 pushes to High aggression (urgency {urgency}/100)"

        # Blend with historical
        _min_agg = RC.get_int("aggression.min_orders_blend", 5)
        if hist_weight > 0 and history.get("avg_aggression") and hist_count >= _min_agg:
            hist_agg = history["avg_aggression"]
            if hist_agg != agg:
                agg = hist_agg
                agg_reason = f"Blended: history avg is {hist_agg} ({hist_count} orders), adjusted from rules"

        suggestions["aggression_level"] = agg
        explanations["aggression_level"] = agg_reason
        confidence["aggression_level"] = 0.75

    # ─────────────────────────────────────────────────
    # 8. ALGO-SPECIFIC PARAMETERS
    # ─────────────────────────────────────────────────

    if algo_type == "POV":
        _pov_hu = RC.get_int("pov.high_urgency_threshold", 75)
        _pov_mu = RC.get_int("pov.med_urgency_threshold", 50)
        _pov_split = RC.get_float("pov.size_split_threshold", 10)
        _pov_vl = RC.get_float("pov.very_large_threshold", 15)
        _pov_tc = RC.get_int("pov.time_close_threshold", 60)

        if urgency >= _pov_hu:
            pct = RC.get_int("pov.rate_high_small", 20) if size_pct_adv < _pov_split else RC.get_int("pov.rate_high_large", 15)
        elif urgency >= _pov_mu:
            pct = RC.get_int("pov.rate_med_small", 12) if size_pct_adv < _pov_split else RC.get_int("pov.rate_med_large", 10)
        elif size_pct_adv > _pov_vl:
            pct = RC.get_int("pov.rate_very_large", 5)
        elif time_to_close < _pov_tc:
            pct = RC.get_int("pov.rate_near_close", 18)
        else:
            pct = RC.get_int("pov.rate_default", 10)

        suggestions["target_participation_rate"] = str(pct)
        explanations["target_participation_rate"] = (
            f"Target {pct}% participation — urgency {urgency}/100, "
            f"order {size_pct_adv:.1f}% of ADV, {time_to_close}min to close"
        )
        confidence["target_participation_rate"] = 0.7

        _min_mult = RC.get_float("pov.min_size_multiplier", 0.3)
        _min_floor = RC.get_int("pov.min_size_floor", 50)
        _max_mult = RC.get_float("pov.max_size_multiplier", 3.0)
        _max_ratio = RC.get_int("pov.max_size_min_ratio", 10)

        min_size = max(_min_floor, int(avg_trade_size * _min_mult))
        max_size = max(min_size * _max_ratio, int(avg_trade_size * _max_mult))
        suggestions["min_order_size"] = str(min_size)
        suggestions["max_order_size"] = str(max_size)
        explanations["min_order_size"] = f"~{int(_min_mult*100)}% of avg trade size ({avg_trade_size:.0f}) to avoid odd lots"
        explanations["max_order_size"] = f"~{_max_mult:.0f}x avg trade size ({avg_trade_size:.0f}) to stay within normal flow"
        confidence["min_order_size"] = 0.6
        confidence["max_order_size"] = 0.6

    elif algo_type == "VWAP":
        _vwap_urg = RC.get_int("vwap.front_load_urgency", 65)
        _vwap_tc = RC.get_int("vwap.front_load_time", 90)

        if urgency >= _vwap_urg:
            curve = "Front-loaded"
            curve_reason = f"High urgency ({urgency}/100) — front-loaded to fill majority early"
        elif tag == "eod_compliance":
            curve = "Back-loaded"
            curve_reason = "EOD compliance — back-loaded curve concentrates volume toward close"
        elif time_to_close < _vwap_tc:
            curve = "Front-loaded"
            curve_reason = f"Limited time ({time_to_close}min) — front-loaded to ensure completion"
        else:
            curve = "Historical"
            curve_reason = "Historical curve — follows natural volume distribution for minimal impact"

        suggestions["volume_curve"] = curve
        explanations["volume_curve"] = curve_reason
        confidence["volume_curve"] = 0.75

        _vl_th = RC.get_float("vwap.size_large_threshold", 10)
        _vm_th = RC.get_float("vwap.size_medium_threshold", 5)
        if size_pct_adv > _vl_th:
            max_vol = RC.get_int("vwap.max_vol_large", 25)
        elif size_pct_adv > _vm_th:
            max_vol = RC.get_int("vwap.max_vol_medium", 15)
        else:
            max_vol = RC.get_int("vwap.max_vol_small", 20)
        suggestions["max_volume_pct"] = str(max_vol)
        explanations["max_volume_pct"] = f"Cap at {max_vol}% per interval — limits single-period market participation"
        confidence["max_volume_pct"] = 0.65

    elif algo_type == "ICEBERG":
        _ice_pct = RC.get_float("iceberg.display_pct", 0.08)
        _ice_mult = RC.get_float("iceberg.avg_trade_multiplier", 1.5)
        _ice_min = RC.get_int("iceberg.min_display", 100)

        display_by_pct = max(_ice_min, int(qty * _ice_pct))
        display_by_avg = max(_ice_min, int(avg_trade_size * _ice_mult))
        display_qty = min(display_by_pct, display_by_avg)
        display_qty = max(display_qty, _ice_min)

        suggestions["display_quantity"] = str(display_qty)
        explanations["display_quantity"] = (
            f"Display ~{display_qty / qty * 100:.0f}% of total order "
            f"(≈{display_qty:,} shares) — blends with avg trade flow ({avg_trade_size:.0f})"
        )
        confidence["display_quantity"] = 0.7

    # ─────────────────────────────────────────────────
    # 9. QUANTITY HINT
    # ─────────────────────────────────────────────────
    if not quantity and history.get("median_quantity"):
        suggestions["quantity"] = str(history["median_quantity"])
        explanations["quantity"] = (
            f"Median from {history['order_count']} previous {symbol} orders "
            f"(median: {history['median_quantity']:,}, avg: {history['avg_quantity']:,})"
        )
        confidence["quantity"] = round(0.4 + min(0.3, hist_count * 0.04), 2)

    # ─────────────────────────────────────────────────
    # 10. ORDER NOTES TEMPLATE
    # ─────────────────────────────────────────────────
    notes_parts = []
    if tag == "eod_compliance":
        notes_parts.append("EOD compliance required")
    if tag == "stealth":
        notes_parts.append("Minimize market impact — stealth execution")
    if tag == "arrival_price":
        notes_parts.append(f"Benchmark: arrival price (₹{ltp:.2f})")
    if size_pct_adv > 15:
        notes_parts.append(f"Large block: {size_pct_adv:.1f}% of ADV")
    if get_done_likely:
        notes_parts.append("Get Done: must complete")
    if notes_intent.get("deadline"):
        notes_parts.append(f"Deadline: {notes_intent['deadline']}")

    if notes_parts:
        suggestions["order_notes"] = " | ".join(notes_parts)
        explanations["order_notes"] = "Auto-generated from client profile and order context"
        confidence["order_notes"] = 0.5

    # ─────────────────────────────────────────────────
    # 11. WHY-NOT EXPLANATIONS
    # ─────────────────────────────────────────────────
    why_not = _generate_why_not(algo_type, size_pct_adv, time_to_close, volatility, tag, urgency)

    return {
        "suggestions": suggestions,
        "explanations": explanations,
        "confidence": confidence,
        "urgency_score": urgency,
        "computed_urgency": computed_urgency,
        "urgency_breakdown": urgency_breakdown,
        "scenario_tag": scenario_tag,
        "scenario_label": scenario_label,
        "why_not": why_not,
    }
