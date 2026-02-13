# orchestration/finance_graph.py

import datetime
import logging
from typing import TypedDict, Annotated, List, Optional
from langgraph.graph import StateGraph, END
import operator
import yfinance as yf

logger = logging.getLogger("DeepRouter.FinanceGraph")

MAX_RECALCULATE_ATTEMPTS = 3
TARGET_DTE = 30
BASE_SPREAD_WIDTH = 5.0

# ==========================================
# 1. State
# ==========================================
class QuantWorkflowState(TypedDict):
    ticker: str
    user_query: str
    market_data: dict
    options_analysis: dict
    risk_score: float
    recalculate_attempts: int
    messages: Annotated[List[str], operator.add]

# ==========================================
# 2. Nodes
# ==========================================
def fetch_market_data_node(state: QuantWorkflowState) -> dict:
    """
    Fetches live price + BOTH puts and calls chain from Yahoo Finance.
    Trend determines which strategy the quant node will build.
    """
    ticker = state["ticker"]
    logger.info(f"[Data Agent] Fetching market data for {ticker}...")

    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="3mo")

        if hist.empty:
            raise ValueError(f"No price history returned for '{ticker}'. Check the ticker symbol.")

        current_price = float(hist["Close"].iloc[-1])
        ma20 = float(hist["Close"].tail(20).mean())
        ma50 = float(hist["Close"].tail(50).mean()) if len(hist) >= 50 else ma20

        if current_price > ma20 > ma50:
            trend = "bullish"
        elif current_price < ma20 < ma50:
            trend = "bearish"
        else:
            trend = "neutral"

        expirations = tk.options
        if not expirations:
            raise ValueError(f"No options data available for '{ticker}'.")

        target_date = datetime.date.today() + datetime.timedelta(days=TARGET_DTE)
        best_expiry = min(
            expirations,
            key=lambda d: abs((datetime.date.fromisoformat(d) - target_date).days),
        )
        actual_dte = (datetime.date.fromisoformat(best_expiry) - datetime.date.today()).days

        chain = tk.option_chain(best_expiry)

        def _normalize(df):
            df = df.copy()
            df.columns = [c.lower() for c in df.columns]
            wanted = ["strike", "bid", "ask", "volume", "openinterest", "impliedvolatility"]
            available = [c for c in wanted if c in df.columns]
            return df[available].fillna(0).to_dict("records")

        puts  = _normalize(chain.puts)
        calls = _normalize(chain.calls)

        market_data = {
            "current_price": round(current_price, 2),
            "trend": trend,
            "ma20": round(ma20, 2),
            "ma50": round(ma50, 2),
            "options_expiry": best_expiry,
            "dte": actual_dte,
            "puts": puts,
            "calls": calls,
        }
        msg = (
            f"[Data] {ticker} @ ${current_price:.2f} | trend={trend} | "
            f"MA20={ma20:.2f} MA50={ma50:.2f} | expiry={best_expiry} ({actual_dte} DTE) | "
            f"puts={len(puts)} calls={len(calls)}"
        )
        logger.info(msg)
        return {"market_data": market_data, "messages": [msg]}

    except Exception as e:
        logger.error(f"[Data Agent] Failed for {ticker}: {e}")
        return {
            "market_data": {"error": str(e), "current_price": 0.0, "puts": [], "calls": []},
            "messages": [f"[Data] ERROR: {e}"],
        }


def analyze_options_strategy_node(state: QuantWorkflowState) -> dict:
    """
    Selects the strategy based on market trend, then builds it from live chains.

      bullish  → Bull Put Spread   (sell OTM put spread, profit if stays above short put)
      neutral  → Iron Condor       (sell OTM put + call spread, profit from low volatility)
      bearish  → Bear Call Spread  (sell OTM call spread, profit if stays below short call)

    On each recalculation the spread width widens by $5 for a safer risk profile.
    """
    market_data = state["market_data"]
    attempts    = state.get("recalculate_attempts", 0)

    if market_data.get("error"):
        return {
            "options_analysis": {"error": market_data["error"], "strategy": "none"},
            "recalculate_attempts": attempts + 1,
            "messages": [f"[Quant] Attempt {attempts + 1} skipped — no market data."],
        }

    current_price = market_data["current_price"]
    trend         = market_data.get("trend", "neutral")
    puts          = market_data.get("puts",  [])
    calls         = market_data.get("calls", [])
    spread_width  = BASE_SPREAD_WIDTH + attempts * 5.0

    logger.info(
        f"[Quant Agent] Attempt {attempts + 1} | {state['ticker']} @ ${current_price} | "
        f"trend={trend} | spread_width=${spread_width}"
    )

    if trend == "bullish":
        analysis = _find_bull_put_spread(puts, current_price, spread_width)
        fallback_label = "Bull Put Spread"
    elif trend == "bearish":
        analysis = _find_bear_call_spread(calls, current_price, spread_width)
        fallback_label = "Bear Call Spread"
    else:  # neutral
        analysis = _find_iron_condor(puts, calls, current_price, spread_width)
        fallback_label = "Iron Condor"

    # Fallback: if preferred strategy has no liquid contracts, try the others
    if analysis is None:
        analysis = (
            _find_bull_put_spread(puts, current_price, spread_width)
            or _find_bear_call_spread(calls, current_price, spread_width)
        )
    if analysis is None:
        analysis = {
            "strategy": "none",
            "error": f"No liquid contracts found for a ${spread_width:.0f}-wide spread.",
        }

    msg = f"[Quant] Attempt {attempts + 1} | trend={trend} | width=${spread_width:.0f} | strategy={analysis.get('strategy')}"
    logger.info(msg)
    return {
        "options_analysis": analysis,
        "recalculate_attempts": attempts + 1,
        "messages": [msg],
    }


def assess_risk_node(state: QuantWorkflowState) -> dict:
    """
    Computes a 0-1 risk score: max_loss / (max_loss + max_profit).
    A score > 0.7 triggers recalculation for a safer spread.
    """
    analysis = state["options_analysis"]

    if analysis.get("error") or analysis.get("strategy") == "none":
        msg = "[Risk] No valid strategy — risk score forced to 1.0."
        logger.warning(msg)
        return {"risk_score": 1.0, "messages": [msg]}

    max_profit = analysis.get("max_profit", 0.0)
    max_loss   = analysis.get("max_loss",   0.0)
    total      = max_profit + max_loss
    score      = round(max_loss / total, 3) if total > 0 else 1.0

    msg = (
        f"[Risk] Score={score:.3f} | "
        f"max_profit=${max_profit:.2f} max_loss=${max_loss:.2f}"
        + (f" | reward/risk={max_profit/max_loss:.2f}" if max_loss > 0 else "")
    )
    logger.info(msg)
    return {"risk_score": score, "messages": [msg]}


# ==========================================
# 3. Conditional edge
# ==========================================
def risk_gatekeeper(state: QuantWorkflowState) -> str:
    attempts = state.get("recalculate_attempts", 0)
    score    = state["risk_score"]

    if score > 0.7 and attempts < MAX_RECALCULATE_ATTEMPTS:
        logger.info(f"[Gatekeeper] Risk {score:.3f} > 0.70 — recalculating ({attempts}/{MAX_RECALCULATE_ATTEMPTS})")
        return "recalculate"

    if attempts >= MAX_RECALCULATE_ATTEMPTS:
        logger.warning(f"[Gatekeeper] Max attempts reached. Finalising with risk={score:.3f}.")
    else:
        logger.info(f"[Gatekeeper] Risk {score:.3f} acceptable. Finalising.")
    return "finalize"


# ==========================================
# 4. Graph assembly
# ==========================================
workflow = StateGraph(QuantWorkflowState)
workflow.add_node("data_fetcher",  fetch_market_data_node)
workflow.add_node("quant_analyzer", analyze_options_strategy_node)
workflow.add_node("risk_assessor", assess_risk_node)

workflow.set_entry_point("data_fetcher")
workflow.add_edge("data_fetcher",  "quant_analyzer")
workflow.add_edge("quant_analyzer", "risk_assessor")
workflow.add_conditional_edges(
    "risk_assessor",
    risk_gatekeeper,
    {"recalculate": "quant_analyzer", "finalize": END},
)

finance_agent_app = workflow.compile()


# ==========================================
# 5. Strategy builders
# ==========================================

def _liquid(contracts: List[dict]) -> List[dict]:
    """Filter contracts for bid > 0, ask > 0, volume > 0."""
    return [c for c in contracts if c.get("bid", 0) > 0 and c.get("ask", 0) > 0 and c.get("volume", 0) > 0]

def _mid(c: dict) -> float:
    return (c["bid"] + c["ask"]) / 2.0

def _spread_result(strategy: str, short: dict, long: dict, is_call: bool, width: float) -> Optional[dict]:
    """Shared P&L math for any single-leg credit spread."""
    short_mid = _mid(short)
    long_mid  = _mid(long)
    net_credit = short_mid - long_mid
    if net_credit <= 0:
        return None

    spread_width = abs(long["strike"] - short["strike"])
    max_profit = round(net_credit * 100, 2)
    max_loss   = round((spread_width - net_credit) * 100, 2)

    result = {
        "strategy":    strategy,
        "expiry":      None,
        "spread_width": float(spread_width),
        "net_credit":  round(float(net_credit), 2),
        "max_profit":  max_profit,
        "max_loss":    max_loss,
        "short_iv":    round(float(short.get("impliedvolatility", 0)), 4),
        "long_iv":     round(float(long.get("impliedvolatility",  0)), 4),
    }

    if is_call:
        result["short_call_strike"] = float(short["strike"])
        result["long_call_strike"]  = float(long["strike"])
        result["short_call_mid"]    = round(float(short_mid), 2)
        result["long_call_mid"]     = round(float(long_mid),  2)
        result["breakeven"]         = round(float(short["strike"]) + net_credit, 2)
    else:
        result["short_put_strike"] = float(short["strike"])
        result["long_put_strike"]  = float(long["strike"])
        result["short_put_mid"]    = round(float(short_mid), 2)
        result["long_put_mid"]     = round(float(long_mid),  2)
        result["breakeven"]        = round(float(short["strike"]) - net_credit, 2)

    return result


def _find_bull_put_spread(puts: List[dict], current_price: float, target_width: float = 5.0) -> Optional[dict]:
    """
    Bull Put Spread — sell OTM put, buy lower-strike put.
    Profit if stock stays above short put strike.  Best when trend is BULLISH.
    """
    liquid = _liquid(puts)
    otm    = sorted([p for p in liquid if p["strike"] < current_price], key=lambda p: p["strike"], reverse=True)
    if not otm:
        return None

    short_put        = otm[0]
    long_target      = short_put["strike"] - target_width
    long_candidates  = sorted([p for p in liquid if p["strike"] <= long_target],
                               key=lambda p: abs(p["strike"] - long_target))
    if not long_candidates:
        return None

    return _spread_result("Bull Put Spread", short_put, long_candidates[0], is_call=False, width=target_width)


def _find_bear_call_spread(calls: List[dict], current_price: float, target_width: float = 5.0) -> Optional[dict]:
    """
    Bear Call Spread — sell OTM call, buy higher-strike call.
    Profit if stock stays below short call strike.  Best when trend is BEARISH.
    """
    liquid = _liquid(calls)
    otm    = sorted([c for c in liquid if c["strike"] > current_price], key=lambda c: c["strike"])
    if not otm:
        return None

    short_call       = otm[0]
    long_target      = short_call["strike"] + target_width
    long_candidates  = sorted([c for c in liquid if c["strike"] >= long_target],
                               key=lambda c: abs(c["strike"] - long_target))
    if not long_candidates:
        return None

    return _spread_result("Bear Call Spread", short_call, long_candidates[0], is_call=True, width=target_width)


def _find_iron_condor(puts: List[dict], calls: List[dict], current_price: float, target_width: float = 5.0) -> Optional[dict]:
    """
    Iron Condor — sell OTM put spread + sell OTM call spread simultaneously.
    Profit if stock stays between the two short strikes.  Best when trend is NEUTRAL.
    """
    put_leg  = _find_bull_put_spread(puts,  current_price, target_width)
    call_leg = _find_bear_call_spread(calls, current_price, target_width)

    if put_leg is None or call_leg is None:
        return None

    put_credit  = put_leg["net_credit"]
    call_credit = call_leg["net_credit"]
    total_credit = round(put_credit + call_credit, 2)

    # Max loss on one side = width - credit collected on that side
    # (can only lose on one side at expiry)
    max_loss_put  = put_leg["max_loss"]
    max_loss_call = call_leg["max_loss"]
    max_loss      = round(max(max_loss_put, max_loss_call), 2)
    max_profit    = round(total_credit * 100, 2)

    return {
        "strategy":          "Iron Condor",
        "expiry":            None,
        # Put spread leg
        "short_put_strike":  put_leg["short_put_strike"],
        "long_put_strike":   put_leg["long_put_strike"],
        "short_put_mid":     put_leg["short_put_mid"],
        "long_put_mid":      put_leg["long_put_mid"],
        "put_credit":        put_credit,
        # Call spread leg
        "short_call_strike": call_leg["short_call_strike"],
        "long_call_strike":  call_leg["long_call_strike"],
        "short_call_mid":    call_leg["short_call_mid"],
        "long_call_mid":     call_leg["long_call_mid"],
        "call_credit":       call_credit,
        # Combined
        "net_credit":        total_credit,
        "max_profit":        max_profit,
        "max_loss":          max_loss,
        "spread_width":      put_leg["spread_width"],
        "breakeven_low":     put_leg["breakeven"],
        "breakeven_high":    call_leg["breakeven"],
        "profit_zone":       f"${put_leg['short_put_strike']} – ${call_leg['short_call_strike']}",
        "short_iv":          put_leg["short_iv"],
        "long_iv":           call_leg["long_iv"],
    }


# ==========================================
# 6. Local smoke test
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for ticker in ["NVDA", "SPY"]:
        print(f"\n{'='*50}")
        result = finance_agent_app.invoke({
            "ticker": ticker,
            "user_query": f"Best options strategy for {ticker}?",
            "market_data": {}, "options_analysis": {},
            "risk_score": 0.0, "recalculate_attempts": 0, "messages": [],
        })
        a = result["options_analysis"]
        print(f"Ticker:   {result['ticker']}")
        print(f"Trend:    {result['market_data'].get('trend')}")
        print(f"Strategy: {a.get('strategy')}")
        print(f"P&L:      max_profit=${a.get('max_profit')}  max_loss=${a.get('max_loss')}")
        print(f"Risk:     {result['risk_score']}")
