"""Piyasa İstihbaratı (intel) katmanı testleri — AĞ ÇAĞRISI YOK.

Buradaki her test yalnızca saf mantığı doğrular: cache davranışı, bias
hesabı, sinyal/risk entegrasyonunun fail-safe olması. Sağlayıcıların canlı
uçları `scripts/intel_smoke.py` ile ayrıca denenir.
"""
from __future__ import annotations

import time

import pytest

from engine.marketdata.intel import cache as intel_cache
from engine.marketdata.intel import bias as intel_bias
from engine.marketdata.intel import keys as intel_keys


@pytest.fixture(autouse=True)
def _clean_cache():
    intel_cache.clear()
    yield
    intel_cache.clear()


# ------------------------------------------------------------------- cache
def test_cache_ttl_ve_yeniden_kullanim():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return {"ok": True, "v": calls["n"]}

    a = intel_cache.cached("k", 60, fn)
    b = intel_cache.cached("k", 60, fn)
    assert a == b == {"ok": True, "v": 1}
    assert calls["n"] == 1, "TTL içinde ikinci kez çağrılmamalı"


def test_cache_ttl_dolunca_tazelenir():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return calls["n"]

    intel_cache.cached("k", 0.0, fn)
    intel_cache.cached("k", 0.0, fn)
    assert calls["n"] == 2


def test_cache_hata_durumunda_bayat_veri_doner():
    intel_cache.put("k", {"ok": True, "v": "eski"})

    def patlar():
        raise RuntimeError("upstream düştü")

    # TTL dolmuş olsa bile hata -> son BAŞARILI değer döner (fail-safe).
    assert intel_cache.cached("k", 0.0, patlar) == {"ok": True, "v": "eski"}


def test_cache_hicbir_veri_yokken_hata_yukselir():
    def patlar():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        intel_cache.cached("bos", 60, patlar)


# -------------------------------------------------------------------- bias
def test_bias_cache_bosken_notr():
    b = intel_bias.market_bias()
    assert b["ok"] is False
    assert b["score"] == 0.0
    assert b["components"] == []


def test_bias_bayat_veriyi_yok_sayar():
    intel_cache.put("macro:riskonoff", {"ok": True, "score": 90, "mode": "Risk On"})
    # Yaşı MAX_AGE_S'den büyük göster
    intel_cache._MEM["macro:riskonoff"]["ts"] = time.time() - intel_bias.MAX_AGE_S - 10
    assert intel_bias.market_bias()["ok"] is False


def test_bias_pozitif_bilesenler_pozitif_skor():
    intel_cache.put("macro:riskonoff", {"ok": True, "score": 90, "mode": "Risk On"})
    intel_cache.put("macro:fng", {"crypto": {"ok": True, "value": 15, "label": "Fear"}})
    intel_cache.put("premium", {"ok": True, "bias": 1.0, "note": "güçlü alım"})
    b = intel_bias.market_bias()
    assert b["ok"] is True
    assert b["score"] > 0.5, b
    assert b["available"] == 3


def test_bias_asiri_acgozluluk_contrarian_negatif():
    intel_cache.put("macro:fng", {"crypto": {"ok": True, "value": 85, "label": "Greed"}})
    b = intel_bias.market_bias()
    assert b["score"] < 0, "aşırı açgözlülük contrarian olarak negatif olmalı"


def test_bias_skor_daima_sinirli():
    for key, val in (("macro:riskonoff", {"ok": True, "score": 100, "mode": "Risk On"}),
                     ("premium", {"ok": True, "bias": 5.0, "note": ""}),
                     ("llama:stables", {"ok": True, "bias": 9.0,
                                        "change_30d_pct": 50, "note": ""})):
        intel_cache.put(key, val)
    assert -1.0 <= intel_bias.market_bias()["score"] <= 1.0


def test_symbol_bias_ilgili_satiri_bulur():
    intel_cache.put("flows:smartmoney", {"ok": True, "source": "proxy", "rows": [
        {"symbol": "ETH", "score": 0.8, "label": "birikim"},
        {"symbol": "BTC", "score": -0.6, "label": "dağıtım"},
    ]})
    assert intel_bias.symbol_bias("BTC")["score"] == pytest.approx(-0.6)
    assert intel_bias.symbol_bias("WETH")["score"] == pytest.approx(0.8), \
        "WETH -> ETH normalizasyonu"
    assert intel_bias.symbol_bias("SOL")["ok"] is False


def test_combined_genel_ve_sembol_harmanlar():
    """combined() = 0.7 x genel + 0.3 x sembole-ozel (agirliklardan bagimsiz)."""
    intel_cache.put("macro:riskonoff", {"ok": True, "score": 100, "mode": "Risk On"})
    intel_cache.put("flows:smartmoney", {"ok": True, "score": 0.0, "rows": [
        {"symbol": "BTC", "score": -1.0, "label": "dağıtım"}]})
    g = intel_bias.market_bias()
    sb = intel_bias.symbol_bias("BTC")
    c = intel_bias.combined("BTC")
    assert g["ok"] and sb["ok"]
    assert c["market_score"] == pytest.approx(g["score"])
    assert c["symbol_score"] == pytest.approx(sb["score"])
    assert c["score"] == pytest.approx(round(0.7 * g["score"] + 0.3 * sb["score"], 3))


# ------------------------------------------------------------- risk kapisi
def _signal(action: str = "BUY", conf: float = 0.9):
    from engine.models import TechnicalSnapshot, TradeSignal
    tech = TechnicalSnapshot(rsi=50, ema_fast=1, ema_slow=1, macd=0,
                             macd_signal=0, momentum=0, price=100.0)
    return TradeSignal(chain_id=1, base="BTC", quote="USDC", action=action,
                       confidence=conf, technical=tech, rationale="t",
                       source="technical")


def test_risk_intel_kapisi_veri_yokken_pasif():
    from engine.config.settings import RiskConfig
    from engine.risk.manager import RiskManager
    rm = RiskManager(RiskConfig())
    d = rm.evaluate(_signal(), {}, 1000.0)
    assert d.approved is True, "intel verisi yokken kapı işlemi engellememeli"


def test_risk_intel_kapisi_ters_yapida_alimi_durdurur():
    from dataclasses import replace
    from engine.config.settings import RiskConfig
    from engine.risk.manager import RiskManager
    intel_cache.put("macro:riskonoff", {"ok": True, "score": 0, "mode": "Risk Off"})
    intel_cache.put("premium", {"ok": True, "bias": -1.0, "note": "satış baskısı"})
    intel_cache.put("macro:fng", {"crypto": {"ok": True, "value": 85, "label": "Greed"}})
    rm = RiskManager(replace(RiskConfig(), intel_block_score=0.5))
    d = rm.evaluate(_signal("BUY"), {}, 1000.0)
    assert d.approved is False
    assert "yapisi" in d.reason.lower() or "yapı" in d.reason.lower()


def test_risk_intel_kapisi_kapaliyken_gecer():
    from dataclasses import replace
    from engine.config.settings import RiskConfig
    from engine.risk.manager import RiskManager
    intel_cache.put("macro:riskonoff", {"ok": True, "score": 0, "mode": "Risk Off"})
    intel_cache.put("premium", {"ok": True, "bias": -1.0, "note": ""})
    intel_cache.put("macro:fng", {"crypto": {"ok": True, "value": 85, "label": "Greed"}})
    rm = RiskManager(replace(RiskConfig(), intel_block_score=0.0))
    assert rm.evaluate(_signal("BUY"), {}, 1000.0).approved is True


def test_risk_intel_kapisi_pozisyon_kapatmayi_engellemez():
    from dataclasses import replace
    from engine.config.settings import RiskConfig
    from engine.models import Position
    from engine.risk.manager import RiskManager
    intel_cache.put("macro:riskonoff", {"ok": True, "score": 100, "mode": "Risk On"})
    intel_cache.put("premium", {"ok": True, "bias": 1.0, "note": ""})
    intel_cache.put("macro:fng", {"crypto": {"ok": True, "value": 10, "label": "Fear"}})
    rm = RiskManager(replace(RiskConfig(), intel_block_score=0.3))
    pos = Position(chain_id=1, base="BTC", quote="USDC", amount=1.0,
                   avg_entry=100.0, last_price=100.0)  # acik LONG
    # Güçlü POZİTİF yapı SELL ile çelişir; yine de long kapatma serbest olmalı.
    d = rm.evaluate(_signal("SELL"), {"1:BTC": pos}, 1000.0)
    assert d.approved is True and "kapat" in d.reason


# ------------------------------------------------------- sinyal entegrasyonu
def _closes(n: int = 120) -> list[float]:
    # Yukselen duz trend -> kural motoru BUY uretir.
    return [100.0 + i * 0.5 for i in range(n)]


def test_sinyal_intel_kapaliyken_breakdown_notr(monkeypatch):
    monkeypatch.setenv("INTEL_SIGNAL", "0")
    from engine.signals.engine import generate_signal
    sig = generate_signal(1, "BTC", "USDC", _closes())
    assert sig.breakdown["intelScore"] == 0.0
    assert "kapali" in (sig.breakdown["intelLabel"] or "")


def test_sinyal_intel_verisi_yokken_degismez(monkeypatch):
    monkeypatch.setenv("INTEL_SIGNAL", "1")
    from engine.signals.engine import generate_signal
    sig = generate_signal(1, "BTC", "USDC", _closes())
    assert sig.breakdown["intelNote"] == "yok"
    assert sig.breakdown["intelScore"] == 0.0


def test_sinyal_ters_yapi_guveni_tavanlar(monkeypatch):
    monkeypatch.setenv("INTEL_SIGNAL", "1")
    from engine.signals.engine import _INTEL_CONFLICT_CAP, generate_signal
    intel_cache.put("macro:riskonoff", {"ok": True, "score": 0, "mode": "Risk Off"})
    intel_cache.put("premium", {"ok": True, "bias": -1.0, "note": "satış"})
    intel_cache.put("macro:fng", {"crypto": {"ok": True, "value": 90, "label": "Greed"}})
    sig = generate_signal(1, "BTC", "USDC", _closes())
    if sig.action == "BUY":
        assert sig.confidence <= _INTEL_CONFLICT_CAP + 1e-9
        assert "ters" in sig.breakdown["intelNote"]


# ------------------------------------------------------------- panel kayidi
def test_panel_kaydi_tutarli():
    import engine.marketdata.intel as intel
    assert intel.PANELS, "panel kaydı boş olmamalı"
    cache_keys = [e[1] for e in intel.PANELS.values()]
    assert len(cache_keys) == len(set(cache_keys)), "cache anahtarları benzersiz olmalı"
    for name, (fn, key, group) in intel.PANELS.items():
        assert callable(fn), name
        assert group in ("macro", "onchain", "hl"), (name, group)


def test_bilinmeyen_panel_hata_verir():
    import engine.marketdata.intel as intel
    with pytest.raises(ValueError):
        intel.panel("olmayan-panel")


def test_anahtar_durumu_ve_kapali_yaniti(monkeypatch):
    monkeypatch.delenv("COINGLASS_API_KEY", raising=False)
    assert intel_keys.coinglass() == ""
    d = intel_keys.disabled("coinglass", "COINGLASS_API_KEY")
    assert d["enabled"] is False and "COINGLASS_API_KEY" in d["reason"]
    st = intel_keys.status()
    assert set(st) >= {"coinglass", "coinmarketcap", "nansen"}
