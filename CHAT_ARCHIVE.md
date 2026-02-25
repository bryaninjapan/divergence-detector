# 對話存檔（可選參考）

本檔為該次對話的存檔說明，大部分情況下無需查閱。

## 完整對話紀錄位置

- Cursor 存放路徑：`~/.cursor/projects/Users-iruka-Downloads-wanai/agent-transcripts/` 下對應 session 的 `.txt`
- 若已關閉 session，可從 Cursor 的對話歷史或 export 取得

## 本次對話重點摘要

1. **方案 B 實作**：改寫 `detect_divergence.py` 的 ETH 匹配邏輯，不再要求 BTC/ETH swing 時間接近，改為在寬時間窗內找 ETH 絕對極值 + BTC 第二點附近的局部極值，以正確偵測如 2021-04 的 bullish divergence（ETH 低點 18Apr、BTC 低點 25Apr）。
2. **參數**：`ETH_LOOKBACK_DAYS = 5`，`ETH_MATCH_TOLERANCE = 3`（根 K 線）。
3. **上傳 GitHub**：`divergence-detector` 已可單獨推送到自己的 repo（需先在 GitHub 建立倉庫再 `git push`）。
4. **報告更新**：以 `fetch_data.py --update` → `detect_divergence.py` → `generate_report.py` 更新 `output/divergence_report.xlsx`。

之後若只需「更新報告」，執行上述三支腳本即可。
