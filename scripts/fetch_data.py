"""
Fetch 4H kline data from Bybit v5 API for BTCUSDT and ETHUSDT perpetual futures.
Saves CSV files to the output/ directory. Supports incremental updates.

Usage:
    python scripts/fetch_data.py                # Full fetch: 2021-01-01 to now
    python scripts/fetch_data.py --update       # Incremental: append new candles only
    python scripts/fetch_data.py --start 2023-01-01  # Custom start date
"""

import argparse
import csv
import os
import time
from datetime import datetime, timezone, timedelta

import requests

BASE_URL = "https://api.bybit.com/v5/market/kline"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVAL = "240"  # 4 hours
LIMIT = 200       # max per request
DEFAULT_START = "2021-01-01"


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> list:
    """Fetch all 4H klines for a symbol between start_ms and end_ms."""
    all_candles = []
    cursor_end = end_ms
    request_count = 0

    while cursor_end > start_ms:
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": INTERVAL,
            "start": str(start_ms),
            "end": str(cursor_end),
            "limit": str(LIMIT),
        }

        resp = requests.get(BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data["retCode"] != 0:
            raise RuntimeError(f"Bybit API error: {data['retMsg']}")

        rows = data["result"]["list"]
        if not rows:
            break

        for row in rows:
            ts, o, h, l, c, vol, turnover = row
            all_candles.append({
                "timestamp": int(ts),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(vol),
            })

        oldest_ts = int(rows[-1][0])
        if oldest_ts >= cursor_end:
            break
        cursor_end = oldest_ts - 1

        request_count += 1
        if request_count % 20 == 0:
            fetched = len(set(c["timestamp"] for c in all_candles))
            print(f"    ... {fetched} candles fetched so far")

        time.sleep(0.15)

    all_candles.sort(key=lambda x: x["timestamp"])

    seen = set()
    unique = []
    for c in all_candles:
        if c["timestamp"] not in seen:
            seen.add(c["timestamp"])
            unique.append(c)

    return unique


def load_existing_csv(filepath: str) -> list:
    """Load existing CSV and return list of candle dicts."""
    if not os.path.exists(filepath):
        return []
    candles = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                "timestamp": int(row["timestamp"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    return candles


def save_csv(candles: list, filepath: str):
    """Save candles to CSV."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "datetime", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for c in candles:
            row = dict(c)
            row["datetime"] = datetime.fromtimestamp(c["timestamp"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            writer.writerow(row)


def merge_candles(existing: list, new: list) -> list:
    """Merge existing and new candles, deduplicating by timestamp."""
    by_ts = {}
    for c in existing:
        by_ts[c["timestamp"]] = c
    for c in new:
        by_ts[c["timestamp"]] = c
    merged = sorted(by_ts.values(), key=lambda x: x["timestamp"])
    return merged


def main():
    parser = argparse.ArgumentParser(description="Fetch Bybit 4H kline data")
    parser.add_argument("--start", type=str, default=DEFAULT_START,
                        help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})")
    parser.add_argument("--update", action="store_true",
                        help="Incremental update: only fetch new candles since last saved data")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "..", "output")

    now = datetime.now(timezone.utc)
    end_ms = int(now.timestamp() * 1000)

    for symbol in SYMBOLS:
        filepath = os.path.join(output_dir, f"{symbol}_4h.csv")

        if args.update:
            existing = load_existing_csv(filepath)
            if existing:
                last_ts = max(c["timestamp"] for c in existing)
                start_ms = last_ts + 1
                last_dt = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                print(f"[UPDATE] {symbol}: fetching new data from {last_dt} UTC ...")
            else:
                start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                start_ms = int(start_dt.timestamp() * 1000)
                existing = []
                print(f"[UPDATE] {symbol}: no existing data, full fetch from {args.start} ...")
        else:
            start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            start_ms = int(start_dt.timestamp() * 1000)
            existing = []
            print(f"[FULL] {symbol}: fetching from {args.start} to now ...")

        if start_ms >= end_ms:
            print(f"  Already up to date.")
            continue

        new_candles = fetch_klines(symbol, start_ms, end_ms)
        merged = merge_candles(existing, new_candles)
        save_csv(merged, filepath)

        first_dt = datetime.fromtimestamp(merged[0]["timestamp"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        last_dt = datetime.fromtimestamp(merged[-1]["timestamp"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"  Total: {len(merged)} candles ({first_dt} to {last_dt} UTC)")
        if existing:
            print(f"  New candles added: {len(new_candles)}")

    print("Done.")


if __name__ == "__main__":
    main()
