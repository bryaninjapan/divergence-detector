# Exit & Risk Rules — Cross-Asset Divergence Strategy

> 此文件為 `divergence-rules.md` 的出場與風控補充，對應 MODELING_RULES C5 要求。
> 回測由 `scripts/divergenceplus.py` 實作。

---

## 前提：交易方向

| 背離類型 | 做的方向 | 交易標的優先順序 |
|---|---|---|
| Bearish Divergence（看跌） | **做空** | ETH（動能弱方，LH）優先；BTC 可同步 |
| Bullish Divergence（看漲） | **做多** | ETH（動能強方，HL）優先；BTC 可同步 |

> **做 ETH 優先的理由**：背離定義本身就是 ETH 動能相對 BTC 更弱（或更強），ETH 是訊號最先體現的一方，期望值通常高於 BTC。

---

## 進場時機（Entry Timing）

```
觸發條件：divergence-rules.md 中三個 Condition 全部滿足
         → Rejection 確認後的下一根 4H 收盤進場

進場價格 = Rejection 確認棒的收盤價
          × (1 + 0.055% + 0.05%)  → Bullish（含手續費 + 滑點）
          × (1 - 0.055% - 0.05%)  → Bearish
```

- 不以即時價格進場，等待 4H 收盤確認，避免 Rejection 窗口內假突破干擾

---

## C5.1 — 止損（Stop Loss）⚠️ 必填

```
[SL] 止損觸發：任何 4H 收盤價穿越「判斷失敗價（failure price）」視為止損出場

     Bearish：4H 收盤 > stop_line → 背離失效，立即平空
     Bullish：4H 收盤 < stop_line → 背離失效，立即平多

[SL-Buffer] 避免 Wick 假觸發（預設 0.1%）：
     Bearish 止損線 = failure_price × (1 + 0.001)
     Bullish 止損線 = failure_price × (1 - 0.001)

[SL-Anchor] 為何用 failure price？
     failure price 已是「背離規則本身的失效點」，天然對應市場結構，
     不是任意設定的固定百分比。每次 setup 的止損距離因結構不同而不同。
```

**止損距離（供倉位計算用）**：
```
sl_distance_pct = |entry_price - stop_line| / entry_price × 100
```

---

## C5.2 — 止盈（Take Profit）

### TP1：結構目標（Measured Move）— 主止盈

```
Bearish：TP1 = entry_price - measured_move
         measured_move = neckline_eth - eth_h2_price   （頸線到 LH 的距離）
         [即從 LH 向下等距離投影]

Bullish：TP1 = entry_price + measured_move
         measured_move = eth_l2_price - neckline_eth   （HL 到頸線的距離）
```

### TP2：固定盈虧比 — 備用止盈

```
當 measured_move 難以計算時（例如頸線不明確），使用固定 RR：
  TP2 = entry_price ± (sl_distance_pct × rr_ratio)
  預設 rr_ratio = 2.0（即 2:1 盈虧比）
```

### 部分出場（可選，預設關閉）

```
在 50% 目標位置平掉 50% 倉位 → 剩餘移動止損至盈虧平衡點
```

---

## C5.3 — 時間止損（Time Stop）⚠️ 必填

```
觸發條件：進場後超過 time_stop_bars 根 4H 棒
          未達 TP 也未觸發 SL → 強制以當根收盤價出場

預設值：time_stop_bars = 20  → 約 3.3 天

理由：Rejection 監控窗口為 15 根 4H；
      若進場後 20 根仍無明確方向，代表市場環境已改變，
      繼續持倉的期望值趨近於零。

可調整範圍：15～40 根（4 天上限）
```

---

## C5.4 — 倉位管理（Position Sizing）

```
固定風險百分比法（推薦）：
  每筆風險金額 = 帳戶總資金 × risk_pct（預設 1.0%）
  名義倉位     = 風險金額 / sl_distance_pct

  例：帳戶 $10,000 / SL distance = 2%
      風險金額 = $100
      名義倉位 = $100 / 0.02 = $5,000（約 0.5× 槓桿）

硬性上限：
  單筆名義倉位 ≤ 帳戶資金 × max_position_pct（預設 20%）
  無論 SL 多緊都不超過此上限
```

---

## 交易成本（RULE-7）

| 項目 | 數值 | 備註 |
|---|---|---|
| 手續費（taker） | 0.055% 單邊 | Bybit 永續合約 |
| 滑點 | 0.05% 單邊 | 保守估算 |
| 合計（來回） | **0.22%** | 每筆須超過此門檻才有淨利 |

---

## RULE-1 合規清單（C1–C7 全部確認）

```
[C1] 目標函數   → 最大化 Sharpe Ratio；最大回撤 ≤ 30%
[C2] 標的市場   → Bybit 永續 BTCUSDT.P / ETHUSDT.P；做空/做多；槓桿上限 3×
[C3] 顆粒度     → 主週期 4H；波段交易（持倉 1～4 天）
[C4] 進場規則   → 三個 Condition 全滿足（見 divergence-rules.md）
[C5] 出場規則   ✅
                 止損    ：4H 收盤穿越 failure price±0.1% buffer
                 止盈    ：Measured Move 目標 或 2:1 固定盈虧比
                 時間止損：進場後 20 根 4H 強制出場
[C6] 交易成本   → 手續費 0.055% + 滑點 0.05%（單邊）
[C7] 風險偏好   → 每筆風險 1% 帳戶；單筆倉位上限 20%
```

---

## 驗證輸出要求（RULE-6）

`divergenceplus.py` 輸出的回測報告必須包含：

| 指標 | 說明 |
|---|---|
| 總交易次數 | Bearish / Bullish 分開統計 |
| 勝率 | Win / Total |
| 盈虧比 | Avg Win / Avg Loss |
| 期望值 | Win rate × Avg Win − (1 − Win rate) × Avg Loss |
| Sharpe Ratio | 年化（以每筆 P&L 計算） |
| 最大回撤（MDD） | 以資金曲線計算 |
| 年份分拆 | 每年勝率 + Sharpe，確認跨市場環境穩健性 |
| 出場原因分佈 | stop_loss / take_profit / time_stop 各佔比 |
