"""
divergenceplus.py — Cross-Asset Divergence Backtest Engine
============================================================
在 detect_divergence.py 偵測到的 divergence 事件基礎上，
加入完整的出場邏輯與績效報告，符合 exit-risk-rules.md 規範。

對應規則：
  references/divergence-rules.md    → 進場條件（偵測邏輯）
  references/exit-risk-rules.md     → 出場條件（本腳本實作）

JSON 欄位依賴（detect_divergence.py 輸出）：
  Bearish: eth_high_price, eth_failure_price, eth_neckline,
           eth_rejection_time
  Bullish: eth_low_price,  eth_failure_price, eth_neckline,
           eth_rejection_time

用法：
  python scripts/divergenceplus.py
  python scripts/divergenceplus.py --use-measured-move
  python scripts/divergenceplus.py --rr-ratio 2.5 --time-stop-bars 24

輸出：
  output/divergenceplus_trades.csv     ← 每筆交易明細
  output/divergenceplus_report.txt     ← 績效報告
  output/divergenceplus_equity.csv     ← 資金曲線
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路徑設定 ────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"


# ═══════════════════════════════════════════════════════════════════
# 1. 資料載入
# ═══════════════════════════════════════════════════════════════════

def load_divergence_json(path: Path) -> list:
    """
    讀取 detect_divergence.py 產出的 JSON。
    格式：{"bearish": [...], "bullish": [...], "params": {...}}
    每個事件 dict 加上 "type" 欄位後展平成清單。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = []
    for div_type in ("bearish", "bullish"):
        for ev in data.get(div_type, []):
            ev["type"] = div_type
            events.append(ev)
    return events


def load_ohlcv(symbol: str) -> pd.DataFrame:
    """讀取 fetch_data.py 產出的 CSV（output/<symbol>*.csv）。"""
    candidates = list(OUTPUT_DIR.glob(f"{symbol}*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"找不到 {symbol} 的 K 線資料，請先執行 fetch_data.py"
        )
    path = sorted(candidates)[-1]
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


# ═══════════════════════════════════════════════════════════════════
# 2. 欄位解析助手
# ═══════════════════════════════════════════════════════════════════

def _parse_event(ev: dict) -> dict | None:
    """
    從 detect_divergence.py 的事件 dict 中提取回測所需欄位。
    回傳 None 表示欄位缺失，跳過此事件。

    Bearish 欄位：
      eth_high_price    → ETH H2（LH）價格，作為 measured_move 起點
      eth_failure_price → ETH 判斷失敗價（止損錨點）
      eth_neckline      → ETH 頸線（measured_move 終點）
      eth_rejection_time→ Rejection 確認時間（進場觸發）

    Bullish 欄位：
      eth_low_price     → ETH L2（HL）價格，作為 measured_move 起點
      eth_failure_price / eth_neckline / eth_rejection_time → 同上
    """
    div_type = ev.get("type", "bearish")
    is_bearish = (div_type == "bearish")

    try:
        rejection_str = ev.get("eth_rejection_time", "")
        if not rejection_str:
            return None   # Rejection 未確認（失敗案例），不回測

        rejection_time = pd.Timestamp(rejection_str, tz="UTC")
        eth_failure    = float(ev["eth_failure_price"])
        eth_neckline   = float(ev["eth_neckline"])

        if is_bearish:
            eth_extreme = float(ev["eth_high_price"])   # LH
        else:
            eth_extreme = float(ev["eth_low_price"])    # HL
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "type":           div_type,
        "rejection_time": rejection_time,
        "eth_failure":    eth_failure,
        "eth_neckline":   eth_neckline,
        "eth_extreme":    eth_extreme,   # LH（bearish）或 HL（bullish）
    }


# ═══════════════════════════════════════════════════════════════════
# 3. 回測引擎
# ═══════════════════════════════════════════════════════════════════

def run_backtest(events: list, eth_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    對每個 Rejection 已確認的 divergence 事件模擬交易（做多/做空 ETH）。

    進場：Rejection 確認棒之後的第一根 4H 收盤
    出場：
      1. 止損 — 4H 收盤穿越 stop_line（failure price ± buffer）
      2. 止盈 — measured_move 目標（或固定盈虧比）
      3. 時間止損 — 進場後 time_stop_bars 根強制出場
    """
    fee_pct    = cfg["fee_pct"] / 100
    slip_pct   = cfg["slip_pct"] / 100
    total_cost = fee_pct + slip_pct
    sl_buffer  = cfg["sl_buffer_pct"] / 100
    rr_ratio   = cfg["rr_ratio"]
    time_stop  = cfg["time_stop_bars"]
    use_mm     = cfg["use_measured_move"]

    eth_close = eth_df["close"]
    eth_high  = eth_df["high"]
    eth_low   = eth_df["low"]
    eth_times = eth_df.index

    trades = []

    for ev in events:
        parsed = _parse_event(ev)
        if parsed is None:
            continue

        is_bearish     = (parsed["type"] == "bearish")
        rejection_time = parsed["rejection_time"]
        eth_failure    = parsed["eth_failure"]
        eth_neckline   = parsed["eth_neckline"]
        eth_extreme    = parsed["eth_extreme"]

        # ── 進場棒 = rejection_time 之後第一根 4H ───────────────
        future_mask = eth_times > rejection_time
        if not future_mask.any():
            continue

        entry_iloc = int(np.argmax(future_mask.values))
        if entry_iloc >= len(eth_df):
            continue

        # 進場價（含交易成本）
        raw = float(eth_close.iloc[entry_iloc])
        entry_price = raw * (1 + total_cost) if not is_bearish else raw * (1 - total_cost)

        # ── 止損線 ───────────────────────────────────────────────
        if is_bearish:
            stop_line = eth_failure * (1 + sl_buffer)   # 做空：close > stop_line → 出場
        else:
            stop_line = eth_failure * (1 - sl_buffer)   # 做多：close < stop_line → 出場

        sl_dist = abs(entry_price - stop_line) / entry_price

        # ── 止盈價 ───────────────────────────────────────────────
        if use_mm:
            measured_move = abs(eth_extreme - eth_neckline)
            tp_price = (entry_price - measured_move) if is_bearish else (entry_price + measured_move)
        else:
            tp_dist  = sl_dist * rr_ratio
            tp_price = (entry_price * (1 - tp_dist)) if is_bearish else (entry_price * (1 + tp_dist))

        # ── 逐棒掃描出場 ─────────────────────────────────────────
        exit_iloc   = None
        exit_reason = None
        exit_price  = None

        scan_end = min(entry_iloc + 1 + time_stop, len(eth_df))
        for j in range(entry_iloc + 1, scan_end):
            c = float(eth_close.iloc[j])
            h = float(eth_high.iloc[j])
            lo = float(eth_low.iloc[j])

            if is_bearish:
                # 止損：收盤突破止損線
                if c > stop_line:
                    exit_iloc, exit_reason = j, "stop_loss"
                    exit_price = stop_line * (1 + total_cost)
                    break
                # 止盈：當棒低點觸及 TP
                if lo <= tp_price:
                    exit_iloc, exit_reason = j, "take_profit"
                    exit_price = tp_price * (1 + total_cost)
                    break
            else:
                # 止損：收盤跌破止損線
                if c < stop_line:
                    exit_iloc, exit_reason = j, "stop_loss"
                    exit_price = stop_line * (1 - total_cost)
                    break
                # 止盈：當棒高點觸及 TP
                if h >= tp_price:
                    exit_iloc, exit_reason = j, "take_profit"
                    exit_price = tp_price * (1 - total_cost)
                    break

        # 時間止損
        if exit_iloc is None:
            j  = min(entry_iloc + time_stop, len(eth_df) - 1)
            c  = float(eth_close.iloc[j])
            exit_iloc   = j
            exit_reason = "time_stop"
            exit_price  = c * (1 + total_cost) if is_bearish else c * (1 - total_cost)

        # ── 損益計算 ─────────────────────────────────────────────
        if is_bearish:
            pnl_pct = (entry_price - exit_price) / entry_price * 100
        else:
            pnl_pct = (exit_price - entry_price) / entry_price * 100

        trades.append({
            "type":             parsed["type"],
            "direction":        "short" if is_bearish else "long",
            "entry_time":       eth_times[entry_iloc],
            "entry_price":      round(entry_price, 4),
            "stop_line":        round(stop_line, 4),
            "tp_price":         round(tp_price, 4),
            "sl_dist_pct":      round(sl_dist * 100, 3),
            "exit_time":        eth_times[exit_iloc],
            "exit_price":       round(exit_price, 4),
            "exit_reason":      exit_reason,
            "bars_held":        exit_iloc - entry_iloc,
            "pnl_pct":          round(pnl_pct, 4),
            "win":              pnl_pct > 0,
            "year":             eth_times[entry_iloc].year,
            "eth_failure_price":round(eth_failure, 4),
            "eth_neckline":     round(eth_neckline, 4),
            "eth_extreme_price":round(eth_extreme, 4),
        })

    return pd.DataFrame(trades)


# ═══════════════════════════════════════════════════════════════════
# 4. 績效報告
# ═══════════════════════════════════════════════════════════════════

def compute_metrics(trades: pd.DataFrame, label: str = "All") -> dict:
    if trades.empty:
        return {"label": label, "n": 0}

    wins   = trades[trades["win"]]
    losses = trades[~trades["win"]]
    n      = len(trades)

    win_rate   = len(wins) / n
    avg_win    = float(wins["pnl_pct"].mean())   if not wins.empty   else 0.0
    avg_loss   = float(losses["pnl_pct"].mean()) if not losses.empty else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    pnl_std = float(trades["pnl_pct"].std())
    sharpe  = (float(trades["pnl_pct"].mean()) / pnl_std * np.sqrt(n)) if pnl_std > 0 else 0.0

    equity = (1 + trades["pnl_pct"] / 100).cumprod()
    peak   = equity.cummax()
    mdd    = float(((equity - peak) / peak).min() * 100)

    rr = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    return {
        "label":        label,
        "n":            n,
        "win_rate":     round(win_rate * 100, 1),
        "avg_win_pct":  round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "rr_ratio":     round(rr, 2),
        "expectancy":   round(expectancy, 4),
        "sharpe":       round(sharpe, 3),
        "mdd_pct":      round(mdd, 2),
        "exits":        trades["exit_reason"].value_counts().to_dict(),
    }


def print_report(df_trades: pd.DataFrame) -> str:
    SEP = "=" * 60
    lines = []

    def section(m: dict):
        lines.append(f"\n{SEP}")
        lines.append(f"  {m['label']}")
        lines.append(SEP)
        if m["n"] == 0:
            lines.append("  （無交易）")
            return
        exits = m.get("exits", {})
        lines.append(f"  交易次數 : {m['n']}")
        lines.append(f"  勝率     : {m['win_rate']}%")
        lines.append(f"  平均獲利 : {m['avg_win_pct']:+.3f}%")
        lines.append(f"  平均虧損 : {m['avg_loss_pct']:+.3f}%")
        lines.append(f"  盈虧比   : {m['rr_ratio']:.2f}")
        lines.append(f"  期望值   : {m['expectancy']:+.4f}%")
        lines.append(f"  Sharpe   : {m['sharpe']:.3f}")
        lines.append(f"  最大回撤 : {m['mdd_pct']:.2f}%")
        lines.append(
            f"  出場分佈 : SL={exits.get('stop_loss', 0)} | "
            f"TP={exits.get('take_profit', 0)} | "
            f"TimeStop={exits.get('time_stop', 0)}"
        )

    section(compute_metrics(df_trades, "■ 整體"))
    for div_type in ("bearish", "bullish"):
        sub = df_trades[df_trades["type"] == div_type]
        section(compute_metrics(sub, f"  {div_type.capitalize()} Divergence"))

    lines.append(f"\n{SEP}")
    lines.append("  年份分拆")
    lines.append(SEP)
    for year, grp in df_trades.groupby("year"):
        m = compute_metrics(grp, str(year))
        lines.append(
            f"  {year}  n={m['n']:3d}  "
            f"勝率={m['win_rate']:5.1f}%  "
            f"期望值={m['expectancy']:+.4f}%  "
            f"Sharpe={m['sharpe']:.3f}"
        )

    lines.append(f"\n{SEP}\n")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 5. 資金曲線（固定 1% 風險法）
# ═══════════════════════════════════════════════════════════════════

def build_equity_curve(
    df_trades: pd.DataFrame,
    initial_capital: float = 10_000.0,
    risk_pct: float = 0.01,
    max_position_pct: float = 0.20,
) -> pd.DataFrame:
    df = df_trades.sort_values("entry_time").reset_index(drop=True)
    capital = initial_capital
    equity_list = []

    for _, row in df.iterrows():
        sl_dist = row["sl_dist_pct"] / 100
        if sl_dist > 0:
            risk_amt = capital * risk_pct
            position = min(risk_amt / sl_dist, capital * max_position_pct)
            pnl_abs  = position * (row["pnl_pct"] / 100)
            capital += pnl_abs
        equity_list.append(capital)

    df["equity"] = equity_list
    return df[["entry_time", "exit_time", "type", "direction",
               "exit_reason", "pnl_pct", "equity"]]


# ═══════════════════════════════════════════════════════════════════
# 6. CLI
# ═══════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Cross-Asset Divergence Backtest (exit-risk-rules edition)"
    )
    p.add_argument("--json", default=str(OUTPUT_DIR / "divergence_results.json"),
                   help="detect_divergence.py 產出的 JSON 路徑")
    p.add_argument("--eth-csv", default=None,
                   help="ETH 4H K 線 CSV（預設自動尋找 output/ETHUSDT*.csv）")
    # ── 出場參數 ────────────────────────────────────────────────
    p.add_argument("--sl-buffer-pct",     type=float, default=0.1,
                   help="止損 buffer 百分比（預設 0.1）")
    p.add_argument("--rr-ratio",          type=float, default=2.0,
                   help="固定盈虧比止盈倍數（預設 2.0）")
    p.add_argument("--time-stop-bars",    type=int,   default=20,
                   help="時間止損棒數，4H 計算（預設 20）")
    p.add_argument("--use-measured-move", action="store_true",
                   help="使用 measured move 作為主止盈（預設用固定 RR）")
    p.add_argument("--fee-pct",           type=float, default=0.055,
                   help="手續費單邊百分比（預設 0.055）")
    p.add_argument("--slip-pct",          type=float, default=0.05,
                   help="滑點單邊百分比（預設 0.05）")
    return p.parse_args()


# ═══════════════════════════════════════════════════════════════════
# 7. 主程式
# ═══════════════════════════════════════════════════════════════════

def main():
    args = parse_args()

    cfg = {
        "sl_buffer_pct":    args.sl_buffer_pct,
        "rr_ratio":         args.rr_ratio,
        "time_stop_bars":   args.time_stop_bars,
        "use_measured_move":args.use_measured_move,
        "fee_pct":          args.fee_pct,
        "slip_pct":         args.slip_pct,
    }

    SEP = "=" * 60
    print(SEP)
    print("  Cross-Asset Divergence Backtest — divergenceplus.py")
    print(SEP)
    tp_mode = "measured_move" if cfg["use_measured_move"] else f"fixed {cfg['rr_ratio']}:1 RR"
    print(f"  JSON      : {args.json}")
    print(f"  SL buffer : {cfg['sl_buffer_pct']}%")
    print(f"  TP mode   : {tp_mode}")
    print(f"  Time stop : {cfg['time_stop_bars']} bars ({cfg['time_stop_bars'] * 4}h)")
    print(f"  Costs     : fee={cfg['fee_pct']}% + slip={cfg['slip_pct']}% (per side)")
    print()

    # ── 載入偵測結果 ─────────────────────────────────────────────
    events_path = Path(args.json)
    if not events_path.exists():
        print(f"❌ 找不到 {events_path}")
        print("   請先執行：python scripts/detect_divergence.py")
        sys.exit(1)

    events = load_divergence_json(events_path)
    print(f"✅ 載入 {len(events)} 個 divergence 事件")

    # ── 載入 ETH K 線 ────────────────────────────────────────────
    if args.eth_csv:
        eth_df = pd.read_csv(args.eth_csv, index_col=0, parse_dates=True)
        eth_df.index = pd.to_datetime(eth_df.index, utc=True)
        eth_df = eth_df.sort_index()
    else:
        eth_df = load_ohlcv("ETHUSDT")
    print(f"✅ ETH K 線：{len(eth_df)} 根 "
          f"({eth_df.index[0].date()} → {eth_df.index[-1].date()})")

    # ── 回測 ─────────────────────────────────────────────────────
    df_trades = run_backtest(events, eth_df, cfg)

    if df_trades.empty:
        print("\n⚠️  無可回測的交易")
        print("   可能原因：所有事件的 eth_rejection_time 為空（全部為失敗案例）")
        sys.exit(0)

    print(f"✅ 回測完成：{len(df_trades)} 筆交易\n")

    # ── 輸出 CSV ─────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(exist_ok=True)

    trades_path = OUTPUT_DIR / "divergenceplus_trades.csv"
    df_trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
    print(f"💾 交易明細 → {trades_path.name}")

    # ── 績效報告 ─────────────────────────────────────────────────
    report_str = print_report(df_trades)
    print(report_str)

    report_path = OUTPUT_DIR / "divergenceplus_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"Config: {json.dumps(cfg, ensure_ascii=False)}\n")
        f.write(report_str)
    print(f"💾 績效報告 → {report_path.name}")

    # ── 資金曲線 ─────────────────────────────────────────────────
    equity_df   = build_equity_curve(df_trades)
    equity_path = OUTPUT_DIR / "divergenceplus_equity.csv"
    equity_df.to_csv(equity_path, index=False, encoding="utf-8-sig")
    print(f"💾 資金曲線 → {equity_path.name}")


if __name__ == "__main__":
    main()
