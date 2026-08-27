"""Kaldıraç motoru — kaldıracı KENARIN büyüklüğü belirler, iştah değil.

Kullanıcı isteği: "AI pozisyonun garantisine göre karar versin." Bunun
matematikteki karşılığı **Kelly kriteridir**: bahis büyüklüğü (burada kaldıraç)
kenarla doğru, oynaklıkla ters orantılıdır. Kritik özelliği şudur:

    kenar yoksa  →  Kelly = 0  →  kaldıraç = 1× (kaldıraçsız)

Yani bu motor, kanıtlanmış bir kenar olmadan kaldıraç AÇMAZ. Bu bir kısıt değil,
kaldıracın tanımıdır: kaldıraç kenarı çarpar; kenar sıfır/negatifse çarpım da
sıfır/negatiftir ve likidasyon (mutlak bariyer) beklenen serveti düşürür.

İçindekiler
-----------
* `kelly_fraction`      — klasik Kelly (p, kazanç/kayıp oranı)
* `decide_leverage`     — sinyal güveni + ölçülen istatistik → kaldıraç
* `liquidation_price`   — pozisyonun likidasyon fiyatı (long/short)
* `risk_of_ruin`        — ardışık kayıpla sermayeyi sıfırlama olasılığı
* `probability_of_target` — X kat büyüme olasılığının ÜST SINIRI (martingale)
* `assess`              — hepsini tek raporda toplar (UI/API için)

Referans: Kelly (1956); Thorp, "The Kelly Criterion in Blackjack, Sports
Betting and the Stock Market" (2006); optional stopping theorem.
"""
from __future__ import annotations

import logging
import math
import os

log = logging.getLogger("risk.leverage")

# Borsaların tipik bakım teminatı (maintenance margin) oranı. Likidasyon,
# teminatın TAMAMI erimeden ÖNCE gelir; bu yüzden hesaba katılır.
DEFAULT_MAINTENANCE_MARGIN = 0.005   # %0,5 (Hyperliquid/Binance perp mertebesi)


def _num(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def enabled() -> bool:
    """Kaldıraç motoru açık mı? Varsayılan KAPALI (bilinçli tercih gerekir)."""
    return os.getenv("LEVERAGE_ENABLED", "0").strip().lower() not in ("0", "false", "no")


def max_leverage() -> float:
    """Sert tavan. Ölçümde 5× üstü getiriyi DÜŞÜRDÜ; varsayılan 3×."""
    return _num("LEVERAGE_MAX", 3.0, 1.0, 50.0)


def kelly_fraction_cap() -> float:
    """Kelly'nin hangi kesri kullanılsın (yarım-Kelly yaygın ve güvenlidir)."""
    return _num("LEVERAGE_KELLY_FRACTION", 0.5, 0.05, 1.0)


def min_samples() -> int:
    """Kelly'yi ciddiye almak için gereken asgari kapanmış işlem sayısı."""
    return int(_num("LEVERAGE_MIN_SAMPLES", 30, 5, 1000))


# ------------------------------------------------------------------- Kelly

def kelly_fraction(win_prob: float, win_loss_ratio: float) -> float:
    """Klasik Kelly kesri: f* = p - (1-p)/b.

    p: kazanma olasılığı (0..1), b: ortalama kazanç / ortalama kayıp.
    Negatif çıkarsa 0 döner — "bahis yapma" demektir, ters bahis değil.
    """
    p = max(0.0, min(1.0, float(win_prob)))
    b = float(win_loss_ratio)
    if b <= 0:
        return 0.0
    f = p - (1.0 - p) / b
    return max(0.0, f)


def stats_from_pnls(pnls: list[float]) -> dict:
    """Kapanmış işlem PnL listesinden Kelly girdileri."""
    wins = [x for x in pnls if x > 0]
    losses = [-x for x in pnls if x < 0]
    n = len(pnls)
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    return {
        "samples": n,
        "win_prob": (len(wins) / n) if n else 0.0,
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "win_loss_ratio": round(avg_win / avg_loss, 4) if avg_loss > 0 else 0.0,
        "net": round(sum(pnls), 4),
    }


def decide_leverage(confidence: float, pnls: list[float] | None = None,
                    hard_cap: float | None = None) -> dict:
    """"AI kararı": sinyal güveni + ÖLÇÜLEN istatistikten kaldıraç.

    Sıra önemlidir — her adım kaldıracı yalnızca AŞAĞI çekebilir:
      1. Motor kapalıysa                        → 1×
      2. Yeterli örnek yoksa                    → 1×  (kanıt yok)
      3. Ölçülen net PnL ≤ 0                    → 1×  (kenar yok)
      4. Kelly ≤ 0                              → 1×  (kenar yok)
      5. kaldıraç = 1 + kesirli_Kelly × güven × (tavan-1)
      6. sert tavan (LEVERAGE_MAX) uygulanır

    Döner: {leverage, reason, kelly, stats, capped}
    """
    cap = float(hard_cap if hard_cap is not None else max_leverage())
    conf = max(0.0, min(1.0, float(confidence)))
    pnls = pnls or []
    st = stats_from_pnls(pnls)

    def _no(reason: str) -> dict:
        return {"leverage": 1.0, "reason": reason, "kelly": 0.0,
                "stats": st, "capped": False}

    if not enabled():
        return _no("kaldıraç motoru kapalı (LEVERAGE_ENABLED=0)")
    if st["samples"] < min_samples():
        return _no(f"yetersiz örnek: {st['samples']} < {min_samples()} kapanan işlem "
                   "— kenar ölçülemedi, kaldıraç açılmaz")
    if st["net"] <= 0:
        return _no(f"ölçülen net PnL {st['net']:+.2f} ≤ 0 — kenar yok, kaldıraç açılmaz")

    k = kelly_fraction(st["win_prob"], st["win_loss_ratio"])
    if k <= 0:
        return _no(f"Kelly kesri {k:.3f} ≤ 0 — kenar yok, kaldıraç açılmaz")

    frac = kelly_fraction_cap()
    lev = 1.0 + min(1.0, k * frac) * conf * (cap - 1.0)
    lev = max(1.0, min(cap, lev))
    return {
        "leverage": round(lev, 3),
        "reason": (f"Kelly {k:.3f} × {frac:g} kesir × güven {conf:.2f} "
                   f"→ {lev:.2f}× (tavan {cap:g}×)"),
        "kelly": round(k, 4),
        "stats": st,
        "capped": lev >= cap - 1e-9,
    }


# ------------------------------------------------------------- likidasyon

def liquidation_price(entry_price: float, leverage: float, side: str = "LONG",
                      maintenance_margin: float = DEFAULT_MAINTENANCE_MARGIN
                      ) -> float | None:
    """Pozisyonun likidasyon fiyatı.

    LONG : entry × (1 - 1/L + mm)
    SHORT: entry × (1 + 1/L - mm)
    L=1 (kaldıraçsız) long'da likidasyon yoktur → None.
    """
    if entry_price <= 0 or leverage <= 0:
        return None
    if leverage <= 1.0 and side.upper() == "LONG":
        return None
    move = 1.0 / leverage - maintenance_margin
    px = entry_price * (1.0 - move) if side.upper() == "LONG" \
        else entry_price * (1.0 + move)
    return max(0.0, round(px, 8))


def liquidation_distance_pct(leverage: float,
                             maintenance_margin: float = DEFAULT_MAINTENANCE_MARGIN
                             ) -> float:
    """Likidasyona kaç % dayanak hareketi kaldı (pozitif sayı)."""
    if leverage <= 0:
        return 100.0
    return max(0.0, (1.0 / leverage - maintenance_margin) * 100.0)


# ----------------------------------------------------------- iflas riski

def risk_of_ruin(win_prob: float, risk_per_trade: float,
                 win_loss_ratio: float = 1.0, capital_units: int | None = None
                 ) -> float:
    """Sermayeyi sıfırlama olasılığı (0..1) — klasik kumarbaç-iflası yaklaşımı.

    `risk_per_trade`: her işlemde sermayenin kaybedilen oranı (ör. 0.10 = %10).
    `capital_units`: kaç ardışık tam kayba dayanılır (verilmezse 1/risk).
    Kenar yoksa (beklenen değer ≤ 0) iflas olasılığı **1.0**'dır — bu bir
    yaklaşım değil, sonsuz oyunda kesin sonuçtur.
    """
    p = max(0.0, min(1.0, float(win_prob)))
    b = max(1e-9, float(win_loss_ratio))
    if risk_per_trade <= 0:
        return 0.0
    units = capital_units if capital_units else max(1, int(1.0 / risk_per_trade))
    edge = p * b - (1.0 - p)          # birim başına beklenen değer
    if edge <= 0:
        return 1.0                     # kenar yok → uzun vadede kesin iflas
    q_over_p = ((1.0 - p) / p) ** (1.0 / b) if p > 0 else 1.0
    if q_over_p >= 1.0:
        return 1.0
    return round(min(1.0, q_over_p ** units), 6)


def probability_of_target(start_usd: float, target_usd: float,
                          edge_cagr: float = 0.0) -> dict:
    """X kat büyüme olasılığının ÜST SINIRI.

    Adil (kenarsız) bir piyasada, iflas etmeden servetini X katına çıkarma
    olasılığı **en fazla 1/X**'tir. Bu optional stopping teoreminin doğrudan
    sonucudur ve KALDIRAÇTAN BAĞIMSIZDIR: kaldıraç yalnızca sonucu ne kadar
    çabuk öğreneceğini değiştirir. Ücret/funding/slippage bu sınırı DÜŞÜRÜR.

    Pozitif bir kenar varsa (`edge_cagr > 0`) sınır yükselir; bu fonksiyon
    yalnızca kenarsız üst sınırı ve kenarın ne kadar gerektiğini raporlar.
    """
    if start_usd <= 0 or target_usd <= start_usd:
        return {"multiple": None, "fair_upper_bound": 1.0,
                "note": "hedef mevcut sermayenin altında veya eşit"}
    x = target_usd / start_usd
    bound = 1.0 / x
    return {
        "multiple": round(x, 2),
        "fair_upper_bound": bound,
        "fair_upper_bound_pct": round(bound * 100, 6),
        "one_in": round(x, 0),
        "edge_cagr_pct": round(edge_cagr * 100, 2),
        "note": ("Kenarsız piyasada bu olasılığın ÜST SINIRI 1/kat'tır ve "
                 "kaldıraçla DEĞİŞMEZ (optional stopping theorem). Ücret, "
                 "funding ve slippage sınırı daha da düşürür. Yalnızca "
                 "kanıtlanmış pozitif kenar bu sayıyı yükseltir."),
    }


# ------------------------------------------------------------- toplu rapor

def assess(confidence: float = 0.0, entry_price: float = 0.0,
           side: str = "LONG", pnls: list[float] | None = None,
           start_usd: float | None = None, target_usd: float | None = None,
           risk_per_trade: float = 0.02) -> dict:
    """Kaldıraç + likidasyon + iflas + hedef olasılığı — tek rapor (UI/API)."""
    dec = decide_leverage(confidence, pnls)
    lev = dec["leverage"]
    st = dec["stats"]
    out = {
        "enabled": enabled(),
        "decision": dec,
        "max_leverage_cap": max_leverage(),
        "liquidation_price": liquidation_price(entry_price, lev, side)
        if entry_price > 0 else None,
        "liquidation_distance_pct": round(liquidation_distance_pct(lev), 3),
        "risk_of_ruin": risk_of_ruin(
            st["win_prob"] or 0.0, risk_per_trade * lev,
            st["win_loss_ratio"] or 1.0),
        "risk_per_trade_effective_pct": round(risk_per_trade * lev * 100, 3),
    }
    if start_usd and target_usd:
        out["target"] = probability_of_target(start_usd, target_usd)
    return out
