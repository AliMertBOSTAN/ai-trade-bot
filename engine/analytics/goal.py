"""Hedef takibi — "ne kadar gerekiyor" ile "ne kadar üretiyorum"u yan yana koyar.

Bu modül BİLEREK pasiftir: hiçbir risk parametresini değiştirmez, pozisyon
büyütmez, kaldıraç önermez. Tek işi **aritmetiği görünür kılmak**:

  • Hedefe ulaşmak için gereken yıllık bileşik getiri (CAGR)
  • Botun GERÇEKTE ürettiği CAGR (equity eğrisinden ölçülür)
  • Bu hızla hedefe kaç yılda ulaşılır
  • Aradaki fark kapanmıyorsa düzenli ekleme (DCA) ile ne gerekir

Neden pasif? Çünkü "hedefe yetişmek için riski artır" mantığı, kumarbaz
yanılgısının koda gömülmüş hâlidir: gereken getiri yükseldikçe gereken risk de
yükselir ve sermayeyi sıfırlama olasılığı hedefe ulaşma olasılığını geçer.
Bot hedefi görür, ama hedefe göre DAVRANMAZ.

Gerçekçilik bantları (yıllık bileşik getiri):
  ≤ %20   makul      — iyi bir uzun vadeli sonuç
  ≤ %50   zorlu      — dünyanın en iyi hedge fonları bandı, sürdürülmesi nadir
  ≤ %100  çok riskli — ancak yüksek oynaklık + büyük düşüş göze alınarak
  > %100  gerçekçi değil — sürdürülebilir örneği yok

Yapılandırma `data/goal.json` içinde kalıcıdır; `set_goal()` ile güncellenir.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

log = logging.getLogger("analytics.goal")

_PATH = os.path.join("data", "goal.json")

# Gerçekçilik bantları: (üst sınır CAGR, etiket, açıklama)
_BANDS: tuple[tuple[float, str, str], ...] = (
    (0.20, "makul", "İyi bir uzun vadeli sonuç bandı."),
    (0.50, "zorlu", "Dünyanın en iyi fonlarının bandı; sürdürülmesi nadirdir."),
    (1.00, "çok riskli",
     "Ancak büyük oynaklık ve derin düşüş göze alınarak; sermaye kaybı olasılığı yüksek."),
    (float("inf"), "gerçekçi değil",
     "Sürdürülebilir bir örneği yok; bu oran hedef değil kumar bahsidir."),
)

# DCA hesabında varsayılan "gerçekçi" yıllık getiri (env ile değiştirilir).
def _assumed_cagr() -> float:
    try:
        return float(os.getenv("GOAL_ASSUMED_CAGR", "0.15"))
    except (TypeError, ValueError):
        return 0.15


@dataclass
class Goal:
    target_usd: float = 0.0
    horizon_months: float = 0.0
    start_equity_usd: float = 0.0
    start_ts: float = 0.0          # epoch s
    note: str = ""

    @property
    def active(self) -> bool:
        return self.target_usd > 0 and self.horizon_months > 0


# ------------------------------------------------------------------ kalıcılık

def load_goal() -> Goal:
    try:
        with open(_PATH, encoding="utf-8") as f:
            return Goal(**json.load(f))
    except FileNotFoundError:
        return Goal()
    except Exception as e:  # noqa: BLE001
        log.warning("goal.json okunamadı: %s", e)
        return Goal()


def save_goal(goal: Goal) -> None:
    try:
        os.makedirs(os.path.dirname(_PATH) or ".", exist_ok=True)
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(goal), f, ensure_ascii=False)
        os.replace(tmp, _PATH)
    except Exception as e:  # noqa: BLE001
        log.warning("goal.json yazılamadı: %s", e)


def set_goal(target_usd: float, horizon_months: float,
             start_equity_usd: float | None = None, note: str = "") -> Goal:
    """Hedefi tanımla/güncelle. start_equity verilmezse mevcut equity alınır."""
    if start_equity_usd is None:
        start_equity_usd = _current_equity()
    g = Goal(target_usd=max(0.0, float(target_usd)),
             horizon_months=max(0.0, float(horizon_months)),
             start_equity_usd=max(0.0, float(start_equity_usd)),
             start_ts=time.time(), note=str(note)[:200])
    save_goal(g)
    return g


def clear_goal() -> None:
    save_goal(Goal())


# ------------------------------------------------------------------ yardımcı

def _current_equity() -> float:
    try:
        from engine.bot.orchestrator import bot
        return float(bot.portfolio.equity_usd())
    except Exception:  # noqa: BLE001
        return 0.0


def _band(cagr: float) -> tuple[str, str]:
    for limit, label, desc in _BANDS:
        if cagr <= limit:
            return label, desc
    return _BANDS[-1][1], _BANDS[-1][2]


def _cagr(start: float, end: float, years: float) -> float | None:
    """Yıllık bileşik getiri. Tanımsızsa None (sıfır/negatif sermaye, sıfır süre)."""
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1.0 / years) - 1.0


def _years_to_target(current: float, target: float, cagr: float) -> float | None:
    """Verilen büyüme hızıyla hedefe kaç yıl. Hız ≤ 0 ise ulaşılamaz (None)."""
    if current <= 0 or target <= current or cagr <= 0:
        return None
    return math.log(target / current) / math.log(1.0 + cagr)


def _monthly_dca(current: float, target: float, years: float, cagr: float) -> float | None:
    """Hedefe varmak için gereken AYLIK ekleme (verilen gerçekçi getiriyle).

    Gelecek değer = mevcut*(1+r)^n + PMT * ((1+r)^n - 1)/r   (aylık bileşik)
    """
    if years <= 0 or target <= 0:
        return None
    n = years * 12.0
    r = (1.0 + cagr) ** (1.0 / 12.0) - 1.0
    if r <= 0:
        return max(0.0, (target - current) / n)
    growth = (1.0 + r) ** n
    need = target - current * growth
    if need <= 0:
        return 0.0
    return need * r / (growth - 1.0)


# ------------------------------------------------------------------ ana rapor

def report(equity_curve: list[float] | None = None,
           current_equity: float | None = None,
           now: float | None = None) -> dict:
    """Hedef durum raporu. Hiçbir ayarı DEĞİŞTİRMEZ — yalnızca hesaplar."""
    g = load_goal()
    now = time.time() if now is None else now

    if current_equity is None:
        current_equity = _current_equity()
    if equity_curve is None:
        try:
            from engine.storage.db import store
            equity_curve = [row["equity"] for row in store.equity_curve(5000)]
        except Exception:  # noqa: BLE001
            equity_curve = []

    if not g.active:
        return {"active": False, "goal": asdict(g),
                "message": "Hedef tanımlı değil. POST /goal ile tanımlayın."}

    years = g.horizon_months / 12.0
    elapsed_years = max(0.0, (now - g.start_ts) / (365.25 * 86400)) if g.start_ts else 0.0
    remaining_years = max(0.0, years - elapsed_years)

    required_multiple = (g.target_usd / current_equity) if current_equity > 0 else None
    required_cagr = _cagr(current_equity, g.target_usd, remaining_years) \
        if remaining_years > 0 else None
    band, band_desc = _band(required_cagr) if required_cagr is not None else ("—", "")

    # Gerçekleşen hız: equity eğrisinin ilk→son değeri, geçen süreye göre.
    actual_cagr = None
    if equity_curve and elapsed_years > 1 / 365.25:  # en az 1 gün veri
        actual_cagr = _cagr(equity_curve[0], equity_curve[-1], elapsed_years)

    years_at_actual = (_years_to_target(current_equity, g.target_usd, actual_cagr)
                       if actual_cagr and actual_cagr > 0 else None)
    assumed = _assumed_cagr()
    years_at_assumed = _years_to_target(current_equity, g.target_usd, assumed)

    warnings: list[str] = []
    if required_cagr is not None and required_cagr > 1.0:
        warnings.append(
            f"Gereken yıllık getiri %{required_cagr * 100:,.0f} — sürdürülebilir bir "
            "örneği yok. Bu bir hedef değil, bahis. Ufku uzatmayı veya hedefi "
            "düşürmeyi düşünün.")
    elif required_cagr is not None and required_cagr > 0.5:
        warnings.append(
            f"Gereken yıllık getiri %{required_cagr * 100:,.0f} — en iyi fonların "
            "üstünde. Ulaşılırsa büyük düşüşlerle ulaşılır.")
    if actual_cagr is not None and required_cagr is not None and actual_cagr < required_cagr:
        warnings.append(
            f"Ölçülen hız (%{actual_cagr * 100:,.1f}/yıl) gereken hızın "
            f"(%{required_cagr * 100:,.1f}/yıl) altında.")
    if current_equity > 0 and g.target_usd / current_equity > 100:
        warnings.append(
            f"Hedef, mevcut sermayenin {g.target_usd / current_equity:,.0f} katı. "
            "Küçük sermayede bu çarpanlar ancak tek seferlik büyük şansla olur; "
            "bot bunu hedefleyecek şekilde AYARLANMAZ.")
    warnings.append(
        "Bu rapor bilgilendirme amaçlıdır; bot risk ayarlarını hedefe göre "
        "DEĞİŞTİRMEZ ve yatırım tavsiyesi değildir.")

    eta = None
    if years_at_actual is not None:
        eta = (datetime.fromtimestamp(now, timezone.utc)
               + timedelta(days=years_at_actual * 365.25)).date().isoformat()

    return {
        "active": True,
        "goal": asdict(g),
        "current_equity_usd": round(current_equity, 2),
        "progress_pct": round(100 * current_equity / g.target_usd, 4)
        if g.target_usd > 0 else 0.0,
        "elapsed_years": round(elapsed_years, 3),
        "remaining_years": round(remaining_years, 3),
        "required_multiple": round(required_multiple, 2) if required_multiple else None,
        "required_cagr_pct": round(required_cagr * 100, 2) if required_cagr is not None else None,
        "required_daily_pct": round(((1 + required_cagr) ** (1 / 365.25) - 1) * 100, 4)
        if required_cagr is not None and required_cagr > -1 else None,
        "feasibility": band,
        "feasibility_note": band_desc,
        "actual_cagr_pct": round(actual_cagr * 100, 2) if actual_cagr is not None else None,
        "years_to_target_at_actual": round(years_at_actual, 1) if years_at_actual else None,
        "eta_at_actual": eta,
        "assumed_cagr_pct": round(assumed * 100, 2),
        "years_to_target_at_assumed": round(years_at_assumed, 1) if years_at_assumed else None,
        "monthly_dca_needed_usd": (
            round(_monthly_dca(current_equity, g.target_usd, remaining_years, assumed), 2)
            if remaining_years > 0 else None),
        "warnings": warnings,
    }
