"""Hyperliquid perp risk kapıları — elle ve AI emirleri AYNI kapıdan geçer.

Kaldıraçlı işlemde tek bir hata hesabı silebilir. Bu yüzden emir yolunda tek
bir `check()` var ve hem arayüzdeki düğme hem de AI otopilotu onu çağırır;
kimse bypass edemez.

Kapılar (hepsi .env ile ayarlanır, hepsinin güvenli varsayılanı vardır):

  HL_MAX_LEVERAGE        kaldıraç tavanı (varsayılan 5)
  HL_MAX_NOTIONAL_USD    tek pozisyon nosyonel tavanı (varsayılan 500)
  HL_MAX_POSITIONS       eşzamanlı açık pozisyon sayısı (varsayılan 3)
  HL_MAX_TOTAL_NOTIONAL  toplam maruziyet tavanı (varsayılan 1500)
  HL_MAX_DAILY_LOSS_USD  günlük gerçekleşen zarar kill-switch (varsayılan 100)
  HL_MIN_LIQ_DISTANCE    likidasyona asgari mesafe %, giriş anında (varsayılan 12)
  HL_COOLDOWN_S          aynı sembolde iki emir arası bekleme (varsayılan 300)
  HL_AI_MAX_NOTIONAL_USD AI'ın tek emirde açabileceği tavan (varsayılan 200)
  HL_AI_MAX_LEVERAGE     AI'ın kullanabileceği kaldıraç tavanı (varsayılan 3)
  HL_AI_MIN_CONFIDENCE   AI'ın işlem açması için asgari güven (varsayılan 0.72)

Kapatma (close/reduce) emirleri HİÇBİR kapıdan engellenmez — riski azaltan
işlem her zaman serbesttir. Bu kasıtlıdır: kill-switch bile pozisyondan
çıkmayı yasaklamamalıdır.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger("risk.hl")

_last_order: dict[str, float] = {}


def _num(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def limits(for_ai: bool = False) -> dict:
    """Yürürlükteki tavanlar. AI için ayrı (daha dar) tavanlar uygulanır."""
    base = {
        "max_leverage": _num("HL_MAX_LEVERAGE", 5, 1, 50),
        "max_notional_usd": _num("HL_MAX_NOTIONAL_USD", 500, 10, 1_000_000),
        "max_positions": int(_num("HL_MAX_POSITIONS", 3, 1, 50)),
        "max_total_notional_usd": _num("HL_MAX_TOTAL_NOTIONAL", 1500, 10, 5_000_000),
        "max_daily_loss_usd": _num("HL_MAX_DAILY_LOSS_USD", 100, 1, 1_000_000),
        "min_liq_distance_pct": _num("HL_MIN_LIQ_DISTANCE", 12, 0, 90),
        "cooldown_s": _num("HL_COOLDOWN_S", 300, 0, 86_400),
        "ai_enabled": os.getenv("HL_AI_AUTOPILOT", "0").strip().lower()
        in ("1", "true", "yes"),
        "ai_max_notional_usd": _num("HL_AI_MAX_NOTIONAL_USD", 200, 10, 1_000_000),
        "ai_max_leverage": _num("HL_AI_MAX_LEVERAGE", 3, 1, 50),
        "ai_min_confidence": _num("HL_AI_MIN_CONFIDENCE", 0.72, 0.0, 1.0),
    }
    if for_ai:
        base["max_notional_usd"] = min(base["max_notional_usd"],
                                       base["ai_max_notional_usd"])
        base["max_leverage"] = min(base["max_leverage"], base["ai_max_leverage"])
    return base


@dataclass
class HLDecision:
    approved: bool
    reason: str
    leverage: int = 0
    notional_usd: float = 0.0
    warnings: tuple = ()

    def to_dict(self) -> dict:
        return {"approved": self.approved, "reason": self.reason,
                "leverage": self.leverage,
                "notional_usd": round(self.notional_usd, 2),
                "warnings": list(self.warnings)}


def note_order(symbol: str) -> None:
    """Cooldown sayacını başlat (emir GERÇEKTEN gönderildiğinde çağrılır)."""
    _last_order[symbol.upper()] = time.time()


def reset_cooldowns() -> None:
    """Testler için."""
    _last_order.clear()


def check(*, symbol: str, side: str, notional_usd: float, leverage: int,
          state: dict, for_ai: bool = False, confidence: float | None = None,
          intel_score: float | None = None,
          require_autopilot: bool = True) -> HLDecision:
    """Emir öncesi tüm kapılar. Onaylanırsa kırpılmış kaldıraç/nosyonel döner.

    `require_autopilot=False`: AI tavanları yine uygulanır ama HL_AI_AUTOPILOT
    şalterine BAKILMAZ. Bunu kuru değerlendirme (karar kartı) kullanır — şalter
    kapalıyken bile "risk kapıları geçilir miydi?" sorusunun doğru cevabını
    vermek için. Gerçek emir yolunda daima True kalır.
    """
    lim = limits(for_ai=for_ai)
    warnings: list[str] = []
    sym = symbol.upper()

    if for_ai and require_autopilot and not lim["ai_enabled"]:
        return HLDecision(False, "AI otopilot kapalı (HL_AI_AUTOPILOT=0)")

    # 1) Günlük zarar kill-switch — yeni RİSK almayı durdurur.
    day_pnl = float(state.get("day_realized_pnl") or 0.0)
    if day_pnl <= -abs(lim["max_daily_loss_usd"]):
        return HLDecision(
            False, f"Günlük zarar limiti aşıldı ({day_pnl:,.2f}$ ≤ "
                   f"-{lim['max_daily_loss_usd']:,.0f}$) — kill-switch")

    # 2) AI güven eşiği
    if for_ai and confidence is not None and confidence < lim["ai_min_confidence"]:
        return HLDecision(
            False, f"AI güveni {confidence:.2f} < eşik {lim['ai_min_confidence']:.2f}")

    # 3) Yapı skoru karara ters mi? (intel katmanı — veri yoksa atlanır)
    if intel_score is not None:
        aligned = intel_score if side.upper() == "LONG" else -intel_score
        block = _num("INTEL_BLOCK_SCORE", 0.6, 0.0, 1.0)
        if block > 0 and aligned <= -block:
            return HLDecision(
                False, f"Piyasa yapısı karara ters (skor {intel_score:+.2f})")

    # 4) Cooldown
    last = _last_order.get(sym, 0.0)
    wait = lim["cooldown_s"] - (time.time() - last)
    if last and wait > 0:
        return HLDecision(False, f"{sym} için bekleme süresi: {wait:.0f} sn kaldı")

    # 5) Pozisyon sayısı / toplam maruziyet
    positions = state.get("positions") or []
    open_syms = {p["symbol"] for p in positions}
    if sym not in open_syms and len(open_syms) >= lim["max_positions"]:
        return HLDecision(
            False, f"Azami pozisyon sayısı ({lim['max_positions']}) dolu")
    total_notional = sum(float(p.get("notional_usd") or 0) for p in positions)
    if total_notional + notional_usd > lim["max_total_notional_usd"]:
        room = lim["max_total_notional_usd"] - total_notional
        if room < 10:
            return HLDecision(
                False, f"Toplam maruziyet tavanı dolu "
                       f"({total_notional:,.0f}$ / {lim['max_total_notional_usd']:,.0f}$)")
        warnings.append(f"nosyonel {notional_usd:,.0f}$ → {room:,.0f}$ olarak kırpıldı")
        notional_usd = room

    # 6) Tek pozisyon nosyonel tavanı
    if notional_usd > lim["max_notional_usd"]:
        warnings.append(f"nosyonel {notional_usd:,.0f}$ → "
                        f"{lim['max_notional_usd']:,.0f}$ tavanına kırpıldı")
        notional_usd = lim["max_notional_usd"]
    if notional_usd < 10:
        return HLDecision(False, "Hyperliquid asgari emir büyüklüğü ~$10")

    # 7) Kaldıraç tavanı
    lev = int(max(1, min(leverage, lim["max_leverage"])))
    if lev < leverage:
        warnings.append(f"kaldıraç {leverage}× → {lev}× tavanına kırpıldı")

    # 8) Teminat yeterli mi
    free = float(state.get("cash_usd") or 0.0)
    need = notional_usd / lev
    if need > free:
        return HLDecision(
            False, f"Yetersiz teminat: gerekli ${need:,.2f}, serbest ${free:,.2f}")

    # 9) Likidasyon mesafesi — kaldıraç bunu belirler; tavan zaten kısıtlar
    liq_dist = (1.0 / lev) * 100
    if liq_dist < lim["min_liq_distance_pct"]:
        safe_lev = int(100 / lim["min_liq_distance_pct"])
        if safe_lev < 1:
            return HLDecision(False, "Likidasyon mesafesi kuralı sağlanamıyor")
        warnings.append(f"likidasyon mesafesi %{liq_dist:.1f} < "
                        f"%{lim['min_liq_distance_pct']:.0f} → kaldıraç {safe_lev}×")
        lev = safe_lev

    return HLDecision(True, "onaylandı", leverage=lev, notional_usd=notional_usd,
                      warnings=tuple(warnings))
