"""
Detect cross-asset divergence between BTCUSDT and ETHUSDT using 4H kline data.
Reads CSV files from output/, detects bearish and bullish divergence, saves JSON results.

Usage:
    python scripts/detect_divergence.py
    python scripts/detect_divergence.py --swing-lookback 4 --max-days 7
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

# ─── Configurable Parameters ───────────────────────────────────────────────

SWING_LOOKBACK = 3        # bars on each side to confirm swing point
MAX_DIVERGENCE_DAYS = 5   # max days between the two swing points
REJECTION_WINDOW = 15     # 4H candles to monitor after neckline break (~2.5 days)
SUCCESS_THRESHOLD = 0.02  # 2% move to confirm success
ETH_LOOKBACK_DAYS = 5     # days to look back before BTC's first swing for ETH extreme
ETH_MATCH_TOLERANCE = 3   # candles (±) to match ETH's second point near BTC's second point


# ─── Helpers ───────────────────────────────────────────────────────────────

def load_data(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath)
    df["timestamp"] = pd.to_numeric(df["timestamp"])
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col])
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def ts_to_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def find_swing_highs(df: pd.DataFrame, lookback: int) -> list[dict]:
    swings = []
    for i in range(lookback, len(df) - lookback):
        h = df.iloc[i]["high"]
        is_swing = True
        for j in range(1, lookback + 1):
            if df.iloc[i - j]["high"] >= h or df.iloc[i + j]["high"] >= h:
                is_swing = False
                break
        if is_swing:
            swings.append({"idx": i, "timestamp": int(df.iloc[i]["timestamp"]), "price": h})
    return swings


def find_swing_lows(df: pd.DataFrame, lookback: int) -> list[dict]:
    swings = []
    for i in range(lookback, len(df) - lookback):
        l = df.iloc[i]["low"]
        is_swing = True
        for j in range(1, lookback + 1):
            if df.iloc[i - j]["low"] <= l or df.iloc[i + j]["low"] <= l:
                is_swing = False
                break
        if is_swing:
            swings.append({"idx": i, "timestamp": int(df.iloc[i]["timestamp"]), "price": l})
    return swings


def find_neckline_break(df: pd.DataFrame, start_idx: int, neckline: float, direction: str) -> Optional[dict]:
    """Find first candle after start_idx where close breaks the neckline.
    direction='bearish': close < neckline; direction='bullish': close > neckline.
    """
    for i in range(start_idx + 1, min(start_idx + 60, len(df))):
        if direction == "bearish" and df.iloc[i]["close"] < neckline:
            return {"idx": i, "timestamp": int(df.iloc[i]["timestamp"])}
        if direction == "bullish" and df.iloc[i]["close"] > neckline:
            return {"idx": i, "timestamp": int(df.iloc[i]["timestamp"])}
    return None


def find_failure_price_bearish(df: pd.DataFrame, hh_idx: int, break_idx: int, lookback: int) -> Optional[float]:
    """Find the most recent swing high between HH and neckline break (below HH price)."""
    hh_price = df.iloc[hh_idx]["high"]
    best = None
    for i in range(hh_idx + 1, break_idx):
        if i < lookback or i >= len(df) - lookback:
            continue
        h = df.iloc[i]["high"]
        is_local = True
        for j in range(1, min(lookback, 3) + 1):
            if i - j >= 0 and df.iloc[i - j]["high"] >= h:
                is_local = False
                break
            if i + j < len(df) and df.iloc[i + j]["high"] >= h:
                is_local = False
                break
        if is_local and h < hh_price:
            best = h
    if best is None and break_idx > hh_idx + 1:
        segment = df.iloc[hh_idx + 1:break_idx]
        max_h = segment["high"].max()
        if max_h < hh_price:
            best = max_h
    return best


def find_failure_price_bullish(df: pd.DataFrame, ll_idx: int, break_idx: int, lookback: int) -> Optional[float]:
    """Find the most recent swing low between LL and neckline break (above LL price)."""
    ll_price = df.iloc[ll_idx]["low"]
    best = None
    for i in range(ll_idx + 1, break_idx):
        if i < lookback or i >= len(df) - lookback:
            continue
        l = df.iloc[i]["low"]
        is_local = True
        for j in range(1, min(lookback, 3) + 1):
            if i - j >= 0 and df.iloc[i - j]["low"] <= l:
                is_local = False
                break
            if i + j < len(df) and df.iloc[i + j]["low"] <= l:
                is_local = False
                break
        if is_local and l > ll_price:
            best = l
    if best is None and break_idx > ll_idx + 1:
        segment = df.iloc[ll_idx + 1:break_idx]
        min_l = segment["low"].min()
        if min_l > ll_price:
            best = min_l
    return best


def check_rejection_bearish(df: pd.DataFrame, break_idx: int, failure_price: float, window: int) -> dict:
    """Check if post-break bounce stays below failure_price."""
    end_idx = min(break_idx + window, len(df))
    max_price = 0.0
    max_ts = 0
    for i in range(break_idx + 1, end_idx):
        if df.iloc[i]["high"] > max_price:
            max_price = df.iloc[i]["high"]
            max_ts = int(df.iloc[i]["timestamp"])
    rejected = max_price < failure_price
    return {"rejected": rejected, "peak_price": max_price, "peak_timestamp": max_ts}


def check_rejection_bullish(df: pd.DataFrame, break_idx: int, failure_price: float, window: int) -> dict:
    """Check if post-breakout pullback stays above failure_price."""
    end_idx = min(break_idx + window, len(df))
    min_price = float("inf")
    min_ts = 0
    for i in range(break_idx + 1, end_idx):
        if df.iloc[i]["low"] < min_price:
            min_price = df.iloc[i]["low"]
            min_ts = int(df.iloc[i]["timestamp"])
    rejected = min_price > failure_price
    return {"rejected": rejected, "trough_price": min_price, "trough_timestamp": min_ts}


def calc_subsequent_move_bearish(df: pd.DataFrame, hh_idx: int, window: int = 30) -> float:
    """Calculate max drop from HH within window candles."""
    hh_price = df.iloc[hh_idx]["high"]
    end_idx = min(hh_idx + window, len(df))
    min_low = df.iloc[hh_idx + 1:end_idx]["low"].min() if hh_idx + 1 < end_idx else hh_price
    return (min_low - hh_price) / hh_price


def calc_subsequent_move_bullish(df: pd.DataFrame, ll_idx: int, window: int = 30) -> float:
    """Calculate max rise from LL within window candles."""
    ll_price = df.iloc[ll_idx]["low"]
    end_idx = min(ll_idx + window, len(df))
    max_high = df.iloc[ll_idx + 1:end_idx]["high"].max() if ll_idx + 1 < end_idx else ll_price
    return (max_high - ll_price) / ll_price


def find_extreme_in_window(df: pd.DataFrame, start_ts: int, end_ts: int, col: str, mode: str) -> Optional[dict]:
    """Find the absolute max or min of a column within a timestamp window.
    mode='max' for highest, mode='min' for lowest.
    Returns {idx, timestamp, price} or None.
    """
    mask = (df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)
    segment = df[mask]
    if segment.empty:
        return None
    if mode == "max":
        idx = segment[col].idxmax()
    else:
        idx = segment[col].idxmin()
    return {"idx": idx, "timestamp": int(df.loc[idx, "timestamp"]), "price": float(df.loc[idx, col])}


def find_local_extreme_near(df: pd.DataFrame, target_ts: int, tolerance_ms: int, col: str, mode: str) -> Optional[dict]:
    """Find the local max/min of a column near a target timestamp (within tolerance).
    mode='max' for highest, mode='min' for lowest.
    Returns {idx, timestamp, price} or None.
    """
    mask = (df["timestamp"] >= target_ts - tolerance_ms) & (df["timestamp"] <= target_ts + tolerance_ms)
    segment = df[mask]
    if segment.empty:
        return None
    if mode == "max":
        idx = segment[col].idxmax()
    else:
        idx = segment[col].idxmin()
    return {"idx": idx, "timestamp": int(df.loc[idx, "timestamp"]), "price": float(df.loc[idx, col])}


# ─── Main Detection ────────────────────────────────────────────────────────

def detect_bearish(btc: pd.DataFrame, eth: pd.DataFrame, params: dict) -> list:
    lookback = params["swing_lookback"]
    max_days = params["max_divergence_days"]
    rej_window = params["rejection_window"]
    threshold = params["success_threshold"]

    interval_ms = 4 * 3600 * 1000
    max_ms = max_days * 24 * 3600 * 1000
    eth_lookback_ms = ETH_LOOKBACK_DAYS * 24 * 3600 * 1000
    eth_tolerance_ms = ETH_MATCH_TOLERANCE * interval_ms

    btc_sh = find_swing_highs(btc, lookback)

    results = []

    for i in range(len(btc_sh) - 1):
        h1_btc = btc_sh[i]
        h2_btc = btc_sh[i + 1]

        if h2_btc["price"] <= h1_btc["price"]:
            continue
        if h2_btc["timestamp"] - h1_btc["timestamp"] > max_ms:
            continue

        window_start = h1_btc["timestamp"] - eth_lookback_ms
        window_end = h2_btc["timestamp"]
        h1_eth = find_extreme_in_window(eth, window_start, window_end, "high", "max")

        h2_eth = find_local_extreme_near(eth, h2_btc["timestamp"], eth_tolerance_ms, "high", "max")

        if h1_eth is None or h2_eth is None:
            continue
        if h1_eth["idx"] == h2_eth["idx"]:
            continue
        if h2_eth["price"] >= h1_eth["price"]:
            continue

        neckline_btc = btc.iloc[h1_btc["idx"]:h2_btc["idx"] + 1]["low"].min()

        eth_start_idx = min(h1_eth["idx"], h2_eth["idx"])
        eth_end_idx = max(h1_eth["idx"], h2_eth["idx"])
        neckline_eth = eth.iloc[eth_start_idx:eth_end_idx + 1]["low"].min()

        break_btc = find_neckline_break(btc, h2_btc["idx"], neckline_btc, "bearish")
        break_eth = find_neckline_break(eth, h2_eth["idx"], neckline_eth, "bearish")

        if break_btc is None or break_eth is None:
            continue

        fail_btc = find_failure_price_bearish(btc, h2_btc["idx"], break_btc["idx"], lookback)
        fail_eth = find_failure_price_bearish(eth, h2_eth["idx"], break_eth["idx"], lookback)

        if fail_btc is None:
            fail_btc = h2_btc["price"]
        if fail_eth is None:
            fail_eth = h2_eth["price"]

        rej_btc = check_rejection_bearish(btc, break_btc["idx"], fail_btc, rej_window)
        rej_eth = check_rejection_bearish(eth, break_eth["idx"], fail_eth, rej_window)

        drop_btc = calc_subsequent_move_bearish(btc, h2_btc["idx"])
        drop_eth = calc_subsequent_move_bearish(eth, h2_eth["idx"])

        success = rej_btc["rejected"] and rej_eth["rejected"] and drop_btc <= -threshold

        results.append({
            "btc_start_time": ts_to_str(h1_btc["timestamp"]),
            "btc_start_price": h1_btc["price"],
            "btc_hh_time": ts_to_str(h2_btc["timestamp"]),
            "btc_hh_price": h2_btc["price"],
            "btc_failure_price": fail_btc,
            "btc_neckline": neckline_btc,
            "btc_neckline_break_time": ts_to_str(break_btc["timestamp"]),
            "btc_rejection_time": ts_to_str(rej_btc["peak_timestamp"]) if rej_btc["peak_timestamp"] else "",
            "btc_rejection_price": rej_btc["peak_price"],
            "eth_start_time": ts_to_str(h1_eth["timestamp"]),
            "eth_start_price": h1_eth["price"],
            "eth_high_time": ts_to_str(h2_eth["timestamp"]),
            "eth_high_price": h2_eth["price"],
            "eth_failure_price": fail_eth,
            "eth_neckline": neckline_eth,
            "eth_neckline_break_time": ts_to_str(break_eth["timestamp"]),
            "eth_rejection_time": ts_to_str(rej_eth["peak_timestamp"]) if rej_eth["peak_timestamp"] else "",
            "eth_rejection_price": rej_eth["peak_price"],
            "result": "成功" if success else "失敗",
            "btc_drop_pct": round(drop_btc * 100, 2),
            "eth_drop_pct": round(drop_eth * 100, 2),
            "note": "",
        })

    return results


def detect_bullish(btc: pd.DataFrame, eth: pd.DataFrame, params: dict) -> list:
    lookback = params["swing_lookback"]
    max_days = params["max_divergence_days"]
    rej_window = params["rejection_window"]
    threshold = params["success_threshold"]

    interval_ms = 4 * 3600 * 1000
    max_ms = max_days * 24 * 3600 * 1000
    eth_lookback_ms = ETH_LOOKBACK_DAYS * 24 * 3600 * 1000
    eth_tolerance_ms = ETH_MATCH_TOLERANCE * interval_ms

    btc_sl = find_swing_lows(btc, lookback)

    results = []

    for i in range(len(btc_sl) - 1):
        l1_btc = btc_sl[i]
        l2_btc = btc_sl[i + 1]

        if l2_btc["price"] >= l1_btc["price"]:
            continue
        if l2_btc["timestamp"] - l1_btc["timestamp"] > max_ms:
            continue

        window_start = l1_btc["timestamp"] - eth_lookback_ms
        window_end = l2_btc["timestamp"]
        l1_eth = find_extreme_in_window(eth, window_start, window_end, "low", "min")

        l2_eth = find_local_extreme_near(eth, l2_btc["timestamp"], eth_tolerance_ms, "low", "min")

        if l1_eth is None or l2_eth is None:
            continue
        if l1_eth["idx"] == l2_eth["idx"]:
            continue
        if l2_eth["price"] <= l1_eth["price"]:
            continue

        neckline_btc = btc.iloc[l1_btc["idx"]:l2_btc["idx"] + 1]["high"].max()

        eth_start_idx = min(l1_eth["idx"], l2_eth["idx"])
        eth_end_idx = max(l1_eth["idx"], l2_eth["idx"])
        neckline_eth = eth.iloc[eth_start_idx:eth_end_idx + 1]["high"].max()

        break_btc = find_neckline_break(btc, l2_btc["idx"], neckline_btc, "bullish")
        break_eth = find_neckline_break(eth, l2_eth["idx"], neckline_eth, "bullish")

        if break_btc is None or break_eth is None:
            continue

        fail_btc = find_failure_price_bullish(btc, l2_btc["idx"], break_btc["idx"], lookback)
        fail_eth = find_failure_price_bullish(eth, l2_eth["idx"], break_eth["idx"], lookback)

        if fail_btc is None:
            fail_btc = l2_btc["price"]
        if fail_eth is None:
            fail_eth = l2_eth["price"]

        rej_btc = check_rejection_bullish(btc, break_btc["idx"], fail_btc, rej_window)
        rej_eth = check_rejection_bullish(eth, break_eth["idx"], fail_eth, rej_window)

        rise_btc = calc_subsequent_move_bullish(btc, l2_btc["idx"])
        rise_eth = calc_subsequent_move_bullish(eth, l2_eth["idx"])

        success = rej_btc["rejected"] and rej_eth["rejected"] and rise_btc >= threshold

        results.append({
            "btc_start_time": ts_to_str(l1_btc["timestamp"]),
            "btc_start_price": l1_btc["price"],
            "btc_ll_time": ts_to_str(l2_btc["timestamp"]),
            "btc_ll_price": l2_btc["price"],
            "btc_failure_price": fail_btc,
            "btc_neckline": neckline_btc,
            "btc_neckline_break_time": ts_to_str(break_btc["timestamp"]),
            "btc_rejection_time": ts_to_str(rej_btc["trough_timestamp"]) if rej_btc["trough_timestamp"] else "",
            "btc_rejection_price": rej_btc["trough_price"],
            "eth_start_time": ts_to_str(l1_eth["timestamp"]),
            "eth_start_price": l1_eth["price"],
            "eth_low_time": ts_to_str(l2_eth["timestamp"]),
            "eth_low_price": l2_eth["price"],
            "eth_failure_price": fail_eth,
            "eth_neckline": neckline_eth,
            "eth_neckline_break_time": ts_to_str(break_eth["timestamp"]),
            "eth_rejection_time": ts_to_str(rej_eth["trough_timestamp"]) if rej_eth["trough_timestamp"] else "",
            "eth_rejection_price": rej_eth["trough_price"],
            "result": "成功" if success else "失敗",
            "btc_rise_pct": round(rise_btc * 100, 2),
            "eth_rise_pct": round(rise_eth * 100, 2),
            "note": "",
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Detect cross-asset divergence")
    parser.add_argument("--swing-lookback", type=int, default=SWING_LOOKBACK)
    parser.add_argument("--max-days", type=int, default=MAX_DIVERGENCE_DAYS)
    parser.add_argument("--rejection-window", type=int, default=REJECTION_WINDOW)
    parser.add_argument("--success-threshold", type=float, default=SUCCESS_THRESHOLD)
    args = parser.parse_args()

    params = {
        "swing_lookback": args.swing_lookback,
        "max_divergence_days": args.max_days,
        "rejection_window": args.rejection_window,
        "success_threshold": args.success_threshold,
    }

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "..", "output")

    btc_path = os.path.join(output_dir, "BTCUSDT_4h.csv")
    eth_path = os.path.join(output_dir, "ETHUSDT_4h.csv")

    if not os.path.exists(btc_path) or not os.path.exists(eth_path):
        print("Error: CSV files not found. Run fetch_data.py first.")
        return

    print("Loading data...")
    btc = load_data(btc_path)
    eth = load_data(eth_path)
    print(f"  BTC: {len(btc)} candles ({btc.iloc[0]['dt']} to {btc.iloc[-1]['dt']})")
    print(f"  ETH: {len(eth)} candles ({eth.iloc[0]['dt']} to {eth.iloc[-1]['dt']})")

    print(f"\nParameters: lookback={params['swing_lookback']}, max_days={params['max_divergence_days']}, "
          f"rej_window={params['rejection_window']}, threshold={params['success_threshold']}")

    print("\nDetecting bearish divergence...")
    bearish = detect_bearish(btc, eth, params)
    print(f"  Found {len(bearish)} cases")

    print("Detecting bullish divergence...")
    bullish = detect_bullish(btc, eth, params)
    print(f"  Found {len(bullish)} cases")

    results = {"bearish": bearish, "bullish": bullish, "params": params}
    results_path = os.path.join(output_dir, "divergence_results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved -> {results_path}")

    for label, cases in [("Bearish", bearish), ("Bullish", bullish)]:
        success_count = sum(1 for c in cases if c["result"] == "成功")
        fail_count = len(cases) - success_count
        print(f"\n{label}: {len(cases)} total | {success_count} 成功 | {fail_count} 失敗")


if __name__ == "__main__":
    main()
