"""Kanıt kapısı — "önce kazandığını göster, sonra gerçek parayla işlem yap".

Backtest bir hipotezdir; İLERİYE DÖNÜK (forward) sonuç kanıttır. Bu modül,
botun kendi geçmiş işlemlerinden (paper/shadow-live) ölçülebilir bir kenar
(edge) gösterip göstermediğine bakar ve canlı moda geçişi buna bağlar.

Ölçülenler (yalnızca KAPANAN işlemlerden, ücret + gas DAHİL):
  • kapanan işlem sayısı        → istatistiksel anlamlılık
  • net PnL (USD)               → gerçekten para kazandı mı
  • profit factor               → kazanç/kayıp oranı
  • kazanma oranı, expectancy   → dağılımın şekli
  • maksimum düşüş (equity)     → risk

Varsayılan eşikler (env ile ayarlanır):
  LIVE_GATE=1                     0 = kapı kapalı (kontrol yapılmaz)
  LIVE_GATE_MIN_TRADES=30         en az kapanan işlem
  LIVE_GATE_MIN_PROFIT_FACTOR=1.2
  LIVE_GATE_MIN_NET_USD=0         net PnL bu değerin ÜSTÜNDE olmalı
  LIVE_GATE_MAX_DD_PCT=15         equity düşüşü bu yüzdeyi aşmamalı
  LIVE_GATE_WINDOW=500            son N işlem incelenir

Bu kapı, bilerek muhafazakârdır: eşikler tutmuyorsa `ready=False` döner ve
`live_preflight` "proven_edge" kontrolünü DÜŞÜRÜR — yani gerçek para riske
atılmaz. Zorlamak için LIVE_FORCE=1 (tavsiye edilmez).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("trading.live_gate")


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def enabled() -> bool:
    return os.getenv("LIVE_GATE", "1").strip().lower() not in ("0", "false", "no")


def thresholds() -> dict:
    return {
        "min_trades": int(_num("LIVE_GATE_MIN_TRADES", 30)),
        "min_profit_factor": _num("LIVE_GATE_MIN_PROFIT_FACTOR", 1.2),
        "min_net_usd": _num("LIVE_GATE_MIN_NET_USD", 0.0),
        "max_dd_pct": _num("LIVE_GATE_MAX_DD_PCT", 15.0),
        "window": int(_num("LIVE_GATE_WINDOW", 500)),
    }


def evaluate(trades: list[dict] | None = None,
             equity: list[float] | None = None) -> dict:
    """Kanıt kapısını değerlendir. Ağ/DB erişimi başarısızsa güvenli tarafa düşer.

    trades/equity verilmezse SQLite'tan okunur (test edilebilirlik için enjekte
    edilebilir). Döner: {ready, reasons, stats, thresholds, enabled}
    """
    from engine.analytics import metrics as M

    th = thresholds()
    if trades is None or equity is None:
        try:
            from engine.storage.db import store
            trades = store.recent_trades(th["window"]) if trades is None else trades
            if equity is None:
                equity = [row["equity"] for row in store.equity_curve(5000)]
        except Exception as e:  # noqa: BLE001
            log.warning("kanıt kapısı veriyi okuyamadı: %s", e)
            return {"ready": False, "enabled": enabled(), "thresholds": th,
                    "stats": {}, "reasons": [f"işlem geçmişi okunamadı: {e}"]}

    pnls = M.pnls_from_trades(trades or [])
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    net = sum(pnls)
    pf = (gross_win / gross_loss) if gross_loss > 1e-9 else (
        float("inf") if gross_win > 0 else 0.0)

    # equity eğrisinden maksimum düşüş (%)
    peak = dd = 0.0
    for v in (equity or []):
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, (peak - v) / peak * 100.0)

    stats = {
        "closed_trades": len(pnls),
        "net_pnl_usd": round(net, 2),
        "profit_factor": (round(pf, 3) if pf != float("inf") else None),
        "win_rate": round(len(wins) / len(pnls), 3) if pnls else 0.0,
        "expectancy_usd": round(net / len(pnls), 4) if pnls else 0.0,
        "max_drawdown_pct": round(dd, 2),
        "gross_win_usd": round(gross_win, 2),
        "gross_loss_usd": round(gross_loss, 2),
        "window": th["window"],
    }

    reasons: list[str] = []
    if stats["closed_trades"] < th["min_trades"]:
        reasons.append(
            f"yeterli kapanan işlem yok: {stats['closed_trades']} < {th['min_trades']} "
            "(paper/shadow modda çalıştırmaya devam edin)")
    if net <= th["min_net_usd"]:
        reasons.append(
            f"net PnL kanıtı yok: ${net:,.2f} <= ${th['min_net_usd']:,.2f}")
    if pf < th["min_profit_factor"]:
        reasons.append(
            f"profit factor düşük: {stats['profit_factor']} < {th['min_profit_factor']}")
    if dd > th["max_dd_pct"]:
        reasons.append(
            f"maksimum düşüş yüksek: %{dd:.2f} > %{th['max_dd_pct']:.2f}")

    if not enabled():
        return {"ready": True, "enabled": False, "stats": stats, "thresholds": th,
                "reasons": ["kanıt kapısı KAPALI (LIVE_GATE=0) — kontrol atlandı"]}

    return {"ready": not reasons, "enabled": True, "stats": stats,
            "thresholds": th, "reasons": reasons}


def ready() -> bool:
    return bool(evaluate().get("ready"))


def leverage_status() -> dict:
    """Kaldıraçlı CANLI işlem için hazırlık durumu — dürüst envanter.

    Bugün ne VAR, ne YOK'u açıkça bildirir. Kaldıraçlı canlı emir, spot canlı
    emirden farklı bir borsa entegrasyonu ister (perp imzalama + emir API'si);
    bu yol, kanıt kapısı VE ayrı bir bayrak olmadan açılmaz.
    """
    from engine.risk import leverage as lev_mod

    gate = evaluate()
    pnls_ok = bool(gate.get("ready"))
    dec = lev_mod.decide_leverage(1.0, [])   # örnek yok -> 1x beklenir

    have = {
        "spot_live_base": True,       # Base üzerinde gerçek DEX swap (doğrulandı)
        "leveraged_backtest": True,   # engine/backtest/leveraged.py
        "kelly_engine": True,         # engine/risk/leverage.py
        "perp_marketdata": True,      # Hyperliquid public API (salt okuma)
        "perp_live_orders": False,    # ⚠️ imzalı perp emir yolu KURULMADI
    }
    blockers: list[str] = []
    if not have["perp_live_orders"]:
        blockers.append(
            "Kaldıraçlı canlı emir yolu (imzalı perp) henüz kurulmadı — bugün "
            "canlı işlem YALNIZCA Base spot (kaldıraç 1×) üzerinden yapılır.")
    if not lev_mod.enabled():
        blockers.append("LEVERAGE_ENABLED=0 — kaldıraç motoru kapalı.")
    if not pnls_ok:
        blockers.extend(gate.get("reasons", []))
    if dec["leverage"] > 1.0:
        blockers.append("beklenmeyen durum: örneksiz kaldıraç kararı > 1×")

    return {
        "ready": not blockers,
        "have": have,
        "blockers": blockers,
        "current_max_leverage": lev_mod.max_leverage() if lev_mod.enabled() else 1.0,
        "proof_gate": gate,
        "note": ("Kaldıraç kenarı ÇARPAR. Kanıt kapısı yeşile dönmeden kaldıraç "
                 "açmak, ölçülmemiş bir kenarı çarpmaktır — beklenen sonuç "
                 "sermayenin daha hızlı erimesidir."),
    }
