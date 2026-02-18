# Cross-Asset Divergence Rules (BTCUSDT vs ETHUSDT)

## General Constraints

- **Timeframe**: 4H candles only
- **Data source**: Bybit perpetual (BTCUSDT.P / ETHUSDT.P, category=linear)
- **Time window**: The two swing points (H1→H2 or L1→L2) must occur within **5 days** (30 x 4H candles). Beyond 5 days, the pattern is invalidated.

---

## Bearish Divergence (看跌)

### Condition 1 — Cross-Asset Divergence
- **BTC**: Forms a **Higher High** (H2 > H1), where H1 and H2 are consecutive swing highs
- **ETH**: In the same time window (±2 candles tolerance), forms a **Lower High** (H2_eth < H1_eth)
- The BTC H2 and ETH H2 timestamps must be within 5 days of each other

### Condition 2 — Neckline Structure & Break
- **Neckline definition**: The lowest low between H1 and H2 in BTC (structural support of the ascending move)
- **Neckline break**: A 4H candle **closes** below the neckline level
- Same logic applies independently to ETH (ETH has its own neckline = lowest low between ETH H1 and ETH H2)

### Condition 3 — Failure Price & Rejection
- **BTC failure price**: After the HH (H2), find the most recent swing high that occurs between H2 and the neckline break candle. This price is LOWER than H2 (the HH). If the post-break bounce closes above this price → divergence **fails**.
- **ETH failure price**: Same logic — the most recent swing high between ETH H2 and ETH neckline break.
- **Rejection confirmed**: After the neckline break, monitor the next N candles (default 15 = ~2.5 days). If no 4H close exceeds the failure price, rejection is confirmed.

### Result Determination
- **Success**: Rejection confirmed AND price drops at least `SUCCESS_THRESHOLD` (default 2%) from the HH
- **Failure**: Post-break bounce closes above the failure price

### Example (14-16 Feb 2026)
```
BTC:
  H1 (開始):    14 Feb 17:00
  H2 (HH):     15 Feb 17:00, price = 70899
  Neckline:     69400
  Neckline break: 15 Feb 21:00
  Failure price: 70388
  Rejection:    16 Feb 21:00, bounce < 70388 → confirmed

ETH:
  H1 (開始):    14 Feb 17:00
  H2 (LH):     15 Feb 13:00, price < H1 price → Lower High confirmed
  Neckline:     2056
  Failure price: 2067
  Rejection:    bounce < 2067 → confirmed

Result: SUCCESS (bearish divergence confirmed)
```

---

## Bullish Divergence (看漲)

Complete mirror of bearish divergence:

### Condition 1 — Cross-Asset Divergence
- **BTC**: Forms a **Lower Low** (L2 < L1), where L1 and L2 are consecutive swing lows
- **ETH**: In the same time window, forms a **Higher Low** (L2_eth > L1_eth)

### Condition 2 — Neckline Structure & Break (upward)
- **Neckline definition**: The highest high between L1 and L2 in BTC (structural resistance of the descending move)
- **Neckline break**: A 4H candle **closes** above the neckline level

### Condition 3 — Failure Price & Rejection
- **BTC failure price**: After the LL (L2), find the most recent swing low between L2 and the neckline breakout candle. This price is HIGHER than L2. If post-breakout pullback closes below this price → divergence **fails**.
- **Rejection confirmed**: After breakout, no 4H close drops below the failure price within the monitoring window.

### Result Determination
- **Success**: Rejection confirmed AND price rises at least `SUCCESS_THRESHOLD` from the LL
- **Failure**: Post-breakout pullback closes below the failure price

---

## Swing Point Detection

A **swing high** is a candle whose high is strictly higher than the highs of `SWING_LOOKBACK` candles on each side.

A **swing low** is a candle whose low is strictly lower than the lows of `SWING_LOOKBACK` candles on each side.

Default `SWING_LOOKBACK = 3` (i.e., must be the highest/lowest within 7 candles = 28 hours).

---

## Excel Output Format

### Sheet 1: Bearish Divergence

| Column | Description |
|--------|-------------|
| # | Case number |
| BTC 開始時間 | BTC first swing high (H1) timestamp |
| BTC 開始價格 | BTC H1 price |
| BTC HH 時間 | BTC Higher High (H2) timestamp |
| BTC HH 價格 | BTC H2 price |
| BTC 判斷失敗價格 | Price above which = divergence fails |
| BTC 頸線價位 | BTC neckline level |
| BTC 頸線跌破時間 | BTC neckline break timestamp |
| BTC Rejection 時間 | BTC post-break bounce peak time |
| BTC Rejection 價格 | BTC bounce peak price |
| ETH 開始時間 | ETH first swing high (H1) timestamp |
| ETH 開始價格 | ETH H1 price |
| ETH 高點時間 | ETH Lower High (H2) timestamp |
| ETH 高點價格 | ETH H2 price (< H1 = LH confirmed) |
| ETH 判斷失敗價格 | Price above which = divergence fails |
| ETH 頸線價位 | ETH neckline level |
| ETH 頸線跌破時間 | ETH neckline break timestamp |
| ETH Rejection 時間 | ETH post-break bounce peak time |
| ETH Rejection 價格 | ETH bounce peak price |
| 結果 | 成功 / 失敗 |
| BTC 之後跌幅% | Drop from HH to subsequent low |
| ETH 之後跌幅% | Drop from LH to subsequent low |
| 備註 | Notes |

### Sheet 2: Bullish Divergence

Mirror columns: LL instead of HH, 低點 instead of 高點, 漲幅 instead of 跌幅, 頸線突破 instead of 頸線跌破.
