"""Günlük özet üretimi (işlemler + equity + PnL) ve bildirim gönderimi.

Saf üretici `build_summary` test edilebilir; `send_daily_summary` bunu bildirim
kanallarına yollar. Zamanlanmış görevle (ör. her sabah) çağrılabilir.
"""
from __future__ import annotations

import time

from engine.notify.notifier import notify


def _window_ms(hours: float) -> int:
    return int((time.time() - hours * 3600) * 1000)


def build_summary(trades: list[dict], equity_curve: list[dict],
                  hours: float = 24.0) -> str:
    """Son `hours` saatlik işlem + equity özetini metin olarak üretir."""
    cutoff = _window_ms(hours)
    recent = [t for t in trades if t.get("timestamp", 0) >= cutoff
              and t.get("status") == "filled"]

    buys = sum(1 for t in recent if t.get("side") == "BUY")
    sells = sum(1 for t in recent if t.get("side") == "SELL")
    fees = sum(float(t.get("feeUsd", 0.0) or 0.0) for t in recent)

    eq_now = equity_curve[-1]["equity"] if equity_curve else 0.0
    eq_window = [e for e in equity_curve if e.get("t", 0) >= cutoff]
    eq_start = eq_window[0]["equity"] if eq_window else (
        equity_curve[0]["equity"] if equity_curve else 0.0)
    pnl = eq_now - eq_start
    pnl_pct = (pnl / eq_start * 100.0) if eq_start > 0 else 0.0

    peak = max((e["equity"] for e in equity_curve), default=eq_now)
    dd_pct = ((peak - eq_now) / peak * 100.0) if peak > 0 else 0.0

    arrow = "📈" if pnl >= 0 else "📉"
    lines = [
        f"📊 Günlük Özet (son {int(hours)}s)",
        f"{arrow} PnL: {pnl:+,.2f} USD ({pnl_pct:+.2f}%)",
        f"Equity: {eq_now:,.2f} USD | Drawdown: %{dd_pct:.1f}",
        f"İşlem: {len(recent)} ({buys} alım / {sells} satım) | Ücret: {fees:,.2f} USD",
    ]
    if recent:
        last = recent[0]
        lines.append(f"Son işlem: {last.get('side')} {last.get('base')} "
                     f"@ {last.get('filledPrice') or last.get('price')}")
    return "\n".join(lines)


def send_daily_summary(store, hours: float = 24.0) -> dict:
    """DB'den özet üretip bildirim kanallarına gönderir."""
    trades = store.recent_trades(500)
    equity = store.equity_curve(1000)
    text = build_summary(trades, equity, hours)
    return {"text": text, "delivery": notify(text, level="info")}
