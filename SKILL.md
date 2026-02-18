---
name: cross-asset-divergence-detector
description: "Detects cross-asset divergence patterns between BTCUSDT and ETHUSDT on Bybit perpetual futures (4H timeframe). Identifies bearish divergence (BTC Higher High vs ETH Lower High) and bullish divergence (BTC Lower Low vs ETH Higher Low), validates with neckline break and rejection confirmation, then generates Excel backtest reports. Use when the user asks about BTC/ETH divergence detection, pattern backtesting, or cross-asset structure analysis."
---

# Cross-Asset Divergence Detector

Detects structural divergence between BTCUSDT.P and ETHUSDT.P on Bybit, using 4H candlestick data.

## When to Use

- User asks to detect BTC/ETH divergence patterns
- User wants to backtest cross-asset divergence on historical data
- User wants an Excel report of bearish/bullish divergence cases

## Quick Start (首次使用)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Fetch full history from 2021-01-01 to now
python scripts/fetch_data.py

# 3. Detect divergence patterns
python scripts/detect_divergence.py

# 4. Generate formatted Excel report
python scripts/generate_report.py
```

Output: `output/divergence_report.xlsx` with 3 sheets (Summary / Bearish / Bullish).

## Weekly Update (每週手動更新)

每週執行一次以下指令，即可取得最新數據並重新生成報告：

```bash
cd divergence-detector

# Step 1: 增量拉取新 K 線（只抓上次之後的新數據，幾秒鐘完成）
python scripts/fetch_data.py --update

# Step 2: 重新偵測全部 divergence
python scripts/detect_divergence.py

# Step 3: 重新生成 Excel 報告
python scripts/generate_report.py
```

> **Note**: `--update` 會讀取現有 CSV 的最後時間戳，只拉取之後的新 K 線並合併。
> 如果要完全重新拉取，不加 `--update` 即可。

## Core Logic

See `references/divergence-rules.md` for the complete trading rules. Summary:

### Bearish Divergence
1. **Divergence**: BTC makes Higher High, ETH makes Lower High (within 5-day window)
2. **Neckline break**: Structural support breaks (4H close below neckline)
3. **Rejection**: Post-break bounce fails to reclaim the failure price
4. **Success**: Price continues lower; **Failure**: Bounce reclaims failure price

### Bullish Divergence
Mirror of bearish: BTC Lower Low + ETH Higher Low → neckline (resistance) breakout → pullback holds above failure price.

## Key Parameters (in detect_divergence.py)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SWING_LOOKBACK` | 3 | Bars on each side to confirm swing point |
| `MAX_DIVERGENCE_DAYS` | 5 | Max days between the two highs/lows |
| `REJECTION_WINDOW` | 15 | Number of 4H candles to monitor after neckline break |
| `SUCCESS_THRESHOLD` | 0.02 | Min drop/rise (2%) to confirm success |

Adjust these parameters based on backtest results to improve detection accuracy.

## Scripts

- `scripts/fetch_data.py` — Fetches OHLCV from Bybit API, saves CSV to `output/`
  - `--start YYYY-MM-DD` — Custom start date (default: 2021-01-01)
  - `--update` — Incremental mode: only fetch candles newer than existing data
- `scripts/detect_divergence.py` — Detects divergence, saves JSON results to `output/`
  - `--swing-lookback N` — Override swing lookback (default: 3)
  - `--max-days N` — Override max divergence window (default: 5)
  - `--rejection-window N` — Override rejection monitoring window (default: 15)
  - `--success-threshold N` — Override success threshold (default: 0.02)
- `scripts/generate_report.py` — Reads JSON results, generates formatted Excel

## Data Source

Bybit v5 REST API (public, no API key required):
- Category: `linear` (USDT perpetual)
- Symbols: `BTCUSDT`, `ETHUSDT`
- Interval: `240` (4 hours)
