"""AI destekli strateji danışmanı.

Görev: strateji-bazlı gerçek performans (işlem geçmişinden atıflı PnL),
anlık piyasa rejimi dağılımı ve mevcut yapılandırmayı toplayıp;
  1) LLM varsa: yapılandırılmış bir öneri iste (ağırlık / aç-kapa / giriş eşiği)
  2) LLM yoksa/bozuksa: kural-tabanlı (heuristic) öneri üret (fail-safe)
Öneri ASLA otomatik uygulanmaz — kullanıcı UI'dan onaylar (apply endpoint'i).
"""
from __future__ import annotations

import json
import logging
import re

from engine.signals import llm as llm_layer
from engine.strategy import registry

log = logging.getLogger("strategy.advisor")

_STRAT_RE = re.compile(r"strateji: ([a-z_]+)")

ADVISOR_SYSTEM = (
    "Sen kantitatif bir portföy yöneticisisin. Sana bir kripto trade botunun "
    "strateji-bazlı performans istatistikleri, anlık piyasa rejimi ve mevcut "
    "yapılandırması verilir. Görevin: hangi stratejilerin açık kalacağını, "
    "sermaye ağırlıklarını (0-3) ve pozisyon giriş eşiğini (0.50-0.95) önermek. "
    "İlkeler: kanıt yoksa (az işlem) mevcut ayarı koru; zarar eden stratejiyi "
    "kıs/kapat; rejime uymayan stratejiye yüksek ağırlık verme; en az bir "
    "strateji açık kalmalı; küçük adımlarla değiştir (±0.5 ağırlık, ±0.05 eşik). "
    'SADECE şu JSON şemasıyla yanıt ver: {"min_confidence": 0.0-1.0, '
    '"rationale": "1-2 cümle Türkçe gerekçe", "strategies": '
    '[{"name": "...", "enabled": true/false, "weight": 0.0-3.0, '
    '"comment": "kısa Türkçe not"}]}'
)


# ---------------- veri toplama ----------------

def per_strategy_stats(trades: list[dict]) -> dict[str, dict]:
    """İşlem geçmişinden strateji-bazlı gerçekleşen PnL istatistikleri.

    Atıf: pozisyonu AÇAN alımın 'strateji: X' etiketi; satış (SL/TP dahil)
    kapanınca PnL o stratejiye yazılır (ortalama maliyet yöntemi).
    """
    rows = sorted((t for t in trades if t.get("status") == "filled"),
                  key=lambda t: t.get("timestamp") or 0)
    book: dict[str, tuple[float, float, str]] = {}  # key -> (miktar, ort, strateji)
    out: dict[str, dict] = {}

    def bucket(name: str) -> dict:
        return out.setdefault(name, {"trades": 0, "wins": 0,
                                     "pnl_usd": 0.0, "buys": 0})

    for t in rows:
        key = f"{t.get('chainId', 0)}:{t.get('base', '?')}"
        px = float(t.get("filledPrice") or t.get("price") or 0.0)
        amt = float(t.get("amount") or 0.0)
        fee = float(t.get("feeUsd") or 0.0)
        if px <= 0 or amt <= 0:
            continue
        m = _STRAT_RE.search(t.get("reason") or "")
        tag = m.group(1) if m else None
        cur_amt, avg, opener = book.get(key, (0.0, 0.0, ""))
        if t.get("side") == "BUY":
            new_amt = cur_amt + amt
            avg = ((avg * cur_amt + px * amt) / new_amt) if new_amt > 0 else px
            book[key] = (new_amt, avg, tag or opener)
            if tag:
                bucket(tag)["buys"] += 1
        elif t.get("side") == "SELL" and cur_amt > 0:
            sell = min(amt, cur_amt)
            pnl = (px - avg) * sell - fee
            name = tag or opener or "bilinmeyen"
            b = bucket(name)
            b["trades"] += 1
            b["pnl_usd"] += pnl
            if pnl > 0:
                b["wins"] += 1
            book[key] = (cur_amt - sell, avg, opener)

    for name, b in out.items():
        n = b["trades"]
        b["win_rate"] = round(b["wins"] / n, 3) if n else 0.0
        b["expectancy_usd"] = round(b["pnl_usd"] / n, 4) if n else 0.0
        b["pnl_usd"] = round(b["pnl_usd"], 2)
    return out


def regime_summary(regimes: dict[str, str]) -> dict[str, int]:
    s = {"trend_up": 0, "trend_down": 0, "range": 0}
    for r in regimes.values():
        if r in s:
            s[r] += 1
    return s


# ---------------- öneri üretimi ----------------

def _clamp_weight(w) -> float:
    try:
        return max(0.0, min(3.0, round(float(w) * 4) / 4))
    except (TypeError, ValueError):
        return 1.0


def _validate_advice(raw: dict | None, known: set[str],
                     cur_conf: float) -> dict | None:
    """LLM çıktısını şemaya zorla; bozuksa None (heuristic'e düşülür)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("strategies"), list):
        return None
    strategies = []
    any_enabled = False
    for item in raw["strategies"]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name not in known:
            continue
        enabled = bool(item.get("enabled", True))
        any_enabled = any_enabled or enabled
        strategies.append({
            "name": name,
            "enabled": enabled,
            "weight": _clamp_weight(item.get("weight", 1.0)),
            "comment": str(item.get("comment", "") or "")[:200],
        })
    if not strategies or not any_enabled:
        return None
    try:
        mc = float(raw.get("min_confidence", cur_conf))
    except (TypeError, ValueError):
        mc = cur_conf
    return {
        "min_confidence": max(0.50, min(0.95, mc)),
        "rationale": str(raw.get("rationale", "") or "")[:500],
        "strategies": strategies,
    }


def heuristic_advice(stats: dict[str, dict], config: list[dict],
                     regimes: dict[str, int], cur_conf: float) -> dict:
    """Kural-tabanlı öneri (LLM yoksa/bozuksa). Kanıt temelli ve temkinli."""
    trending = regimes.get("trend_up", 0) + regimes.get("trend_down", 0)
    ranging = regimes.get("range", 0)
    regime_bias = "trend" if trending > ranging else "range"

    strategies = []
    total_pnl, total_n, total_wins = 0.0, 0, 0
    for item in config:
        name = item["name"]
        w = float(item.get("weight", 1.0))
        enabled = bool(item.get("enabled", True))
        st = stats.get(name, {})
        n = st.get("trades", 0)
        comment = "kanıt az — mevcut ayar korundu"
        if n >= 5:
            total_pnl += st["pnl_usd"]; total_n += n
            total_wins += st.get("wins", 0)
            if st["expectancy_usd"] < 0 and st["win_rate"] < 0.45:
                if w > 0.5:
                    w, comment = max(0.5, w - 0.5), (
                        f"zayıf performans (n={n}, WR %{st['win_rate']*100:.0f}, "
                        f"beklenti {st['expectancy_usd']:.2f}$) — ağırlık kısıldı")
                else:
                    enabled, comment = False, (
                        f"istikrarlı zarar (n={n}) — kapatıldı")
            elif st["expectancy_usd"] > 0 and st["win_rate"] >= 0.5:
                w, comment = min(3.0, w + 0.5), (
                    f"iyi performans (n={n}, WR %{st['win_rate']*100:.0f}) — "
                    "ağırlık artırıldı")
            else:
                comment = f"nötr performans (n={n}) — korundu"
        # rejim eğilimi (küçük dokunuş)
        if enabled:
            if regime_bias == "range" and name in ("trend", "momentum", "breakout"):
                w = max(0.5, w - 0.25)
                comment += " · piyasa yatay: trend-takip hafif kısıldı"
            elif regime_bias == "trend" and name == "mean_reversion":
                w = max(0.5, w - 0.25)
                comment += " · piyasa trendde: ortalamaya dönüş hafif kısıldı"
        strategies.append({"name": name, "enabled": enabled,
                           "weight": _clamp_weight(w), "comment": comment})

    if not any(s["enabled"] for s in strategies) and strategies:
        # fail-safe: hepsi kapanamaz — hybrid'i (ya da ilkini) açık bırak
        keep = next((s for s in strategies if s["name"] == "hybrid"), strategies[0])
        keep["enabled"] = True
        keep["comment"] += " · fail-safe: en az bir strateji açık kalmalı"

    mc = cur_conf
    overall_wr = (total_wins / total_n) if total_n >= 10 else None
    if overall_wr is not None:
        if overall_wr < 0.45:
            mc = min(0.95, cur_conf + 0.03)
        elif overall_wr > 0.60:
            mc = max(0.50, cur_conf - 0.02)
    rationale = (f"Kural-tabanlı analiz: {total_n} kapanış, rejim eğilimi "
                 f"{'trend' if regime_bias == 'trend' else 'yatay'}. "
                 "Zarar eden stratejiler kısıldı, kazananlar güçlendirildi; "
                 "kanıtı az olanlara dokunulmadı.")
    return {"min_confidence": round(mc, 2), "rationale": rationale,
            "strategies": strategies}


def llm_advice(stats: dict[str, dict], config: list[dict],
               regimes: dict[str, int], cur_conf: float,
               performance: dict | None = None) -> dict | None:
    """LLM'den yapılandırılmış öneri ister; bozuk yanıtta None (fail-safe)."""
    import engine.strategy.strategies  # noqa: F401
    known = set(registry.available())
    lines = ["== STRATEJİ PERFORMANSI (kapanan işlemlerden) =="]
    for item in config:
        name = item["name"]
        st = stats.get(name, {})
        lines.append(
            f"- {name}: {'AÇIK' if item.get('enabled', True) else 'KAPALI'} "
            f"ağırlık={item.get('weight', 1.0)} · kapanış={st.get('trades', 0)} "
            f"· WR={st.get('win_rate', 0.0):.0%} · PnL={st.get('pnl_usd', 0.0):.2f}$ "
            f"· beklenti={st.get('expectancy_usd', 0.0):.2f}$/işlem")
    lines.append(f"== REJİM DAĞILIMI == {json.dumps(regimes)}")
    lines.append(f"== MEVCUT GİRİŞ EŞİĞİ == {cur_conf:.2f}")
    if performance:
        lines.append("== PORTFÖY == "
                     f"Sharpe={performance.get('sharpe')} "
                     f"MaxDD=%{performance.get('max_drawdown_pct')} "
                     f"WR={performance.get('win_rate')}")
    lines.append("Öneri JSON'unu ver (yalnızca mevcut strateji adları: "
                 + ", ".join(sorted(known)) + ").")
    text = llm_layer.complete(ADVISOR_SYSTEM, "\n".join(lines), max_tokens=700)
    if not text:
        return None
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        raw = json.loads(text[start:end])
    except Exception:  # noqa: BLE001
        return None
    return _validate_advice(raw, known, cur_conf)


def get_advice(stats: dict[str, dict], config: list[dict],
               regimes: dict[str, int], cur_conf: float,
               performance: dict | None = None) -> dict:
    """Önce LLM, olmazsa kural-tabanlı öneri. Kaynağı işaretler."""
    advice = None
    try:
        advice = llm_advice(stats, config, regimes, cur_conf, performance)
    except Exception as e:  # noqa: BLE001
        log.warning("LLM strateji önerisi alınamadı: %s", e)
    if advice is not None:
        advice["source"] = "llm"
        return advice
    advice = heuristic_advice(stats, config, regimes, cur_conf)
    advice["source"] = "heuristic"
    return advice
