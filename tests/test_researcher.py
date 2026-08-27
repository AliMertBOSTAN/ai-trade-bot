"""Otonom araştırmacı testleri — ağa ÇIKMAZ (haber/piyasa/LLM yamalı)."""
from __future__ import annotations

import time

import pytest

from engine.marketdata import researcher as R
from engine.marketdata.calendar import CalendarEvent, EconomicCalendar


@pytest.fixture
def izole(tmp_path, monkeypatch):
    """Diskten ve ağdan yalıtılmış araştırmacı + boş takvim."""
    monkeypatch.setattr(R, "_STORE_PATH", str(tmp_path / "research.json"))
    monkeypatch.setattr("engine.marketdata.calendar._CACHE_PATH",
                        str(tmp_path / "cal.json"))
    monkeypatch.setattr("engine.marketdata.calendar._CUSTOM_PATH",
                        str(tmp_path / "custom.json"))
    cal = EconomicCalendar()
    cal._events.clear()
    monkeypatch.setattr(R, "calendar", cal)
    monkeypatch.setattr(R, "_match_headlines", lambda kw, limit=60: [
        {"source": "test", "title": "US inflation cools", "link": "", "ts": 0}])
    monkeypatch.setattr(R, "_market_context", lambda syms=None: {
        "BTC": {"price": 63000.0, "change24h_pct": 2.5, "atr24h_pct": 0.4}})
    monkeypatch.setenv("RESEARCH_LLM", "0")
    monkeypatch.setenv("RESEARCH_NOTIFY", "0")
    return R.Researcher(), cal


def _ev(ts, imp=1.0, title="TÜFE (CPI)"):
    return CalendarEvent(id=f"e-{ts}", title=title, raw_title="Consumer Price Index",
                         ts=ts, category="macro", importance=imp, source="test")


def test_llm_yokken_sayisal_not_uretilir(izole):
    res, _ = izole
    ev = _ev(int(time.time() * 1000) + 6 * 3600_000)
    note = res.research_event(ev, phase="pre")
    assert note.author == "numeric"
    assert "TÜFE" in note.summary and note.scenarios
    assert -1.0 <= note.bias <= 1.0


def test_llm_bozuk_yanit_verirse_sayisal_nota_duser(izole, monkeypatch):
    res, _ = izole
    monkeypatch.setenv("RESEARCH_LLM", "1")
    monkeypatch.setattr("engine.signals.llm.complete",
                        lambda *a, **k: "bu JSON değil")
    note = res.research_event(_ev(int(time.time() * 1000) + 3600_000), phase="pre")
    assert note.author == "numeric" and note.summary


def test_llm_yaniti_nota_islenir(izole, monkeypatch):
    res, _ = izole
    monkeypatch.setenv("RESEARCH_LLM", "1")
    monkeypatch.setattr("engine.signals.llm.complete", lambda *a, **k: (
        '{"ozet":"CPI yumuşak bekleniyor","beklenti":"%2.9 yıllık",'
        '"senaryolar":[{"kosul":"sıcak","etki":"BTC -2%"}],"bias":0.4,'
        '"izlenecek":["63k destek"],"risk":"çekirdek sürpriz"}'))
    note = res.research_event(_ev(int(time.time() * 1000) + 3600_000), phase="pre")
    assert note.author == "llm"
    assert note.bias == 0.4 and note.expectation.startswith("%2.9")
    assert note.scenarios[0]["kosul"] == "sıcak" and note.watch


def test_llm_bias_araligi_kirpilir(izole, monkeypatch):
    res, _ = izole
    monkeypatch.setenv("RESEARCH_LLM", "1")
    monkeypatch.setattr("engine.signals.llm.complete",
                        lambda *a, **k: '{"ozet":"x","bias":99}')
    assert res.research_event(_ev(int(time.time() * 1000)), phase="pre").bias == 1.0


def test_cycle_yaklasan_olayi_arastirir_gecmisi_okur(izole, monkeypatch):
    res, cal = izole
    monkeypatch.setattr(res, "_ingest_news_events", lambda now: 0)
    monkeypatch.setattr(cal, "refresh", lambda *a, **k: 0)
    now = int(time.time() * 1000)
    cal.add_event(_ev(now + 12 * 3600_000))                 # 12 saat sonra -> pre
    cal.add_event(_ev(now - 5 * 3600_000, title="FOMC"))    # 5 saat önce -> post
    out = res.cycle(now_ms=now)
    assert out["pre"] == 1 and out["post"] == 1
    fazlar = {n["phase"] for n in res.notes()}
    assert fazlar == {"pre", "post"}


def test_ayni_olay_tekrar_arastirilmaz(izole, monkeypatch):
    res, cal = izole
    monkeypatch.setattr(res, "_ingest_news_events", lambda now: 0)
    monkeypatch.setattr(cal, "refresh", lambda *a, **k: 0)
    now = int(time.time() * 1000)
    cal.add_event(_ev(now + 10 * 3600_000))
    assert res.cycle(now_ms=now)["pre"] == 1
    assert res.cycle(now_ms=now)["pre"] == 0          # tazeleme penceresi içinde
    ileri = now + int(9 * 3600_000)                    # RESEARCH_REFRESH_H=8 geçti
    assert res.cycle(now_ms=ileri)["pre"] == 1


def test_dusuk_onemli_olay_arastirilmaz(izole, monkeypatch):
    res, cal = izole
    monkeypatch.setattr(res, "_ingest_news_events", lambda now: 0)
    monkeypatch.setattr(cal, "refresh", lambda *a, **k: 0)
    now = int(time.time() * 1000)
    cal.add_event(_ev(now + 6 * 3600_000, imp=0.3, title="Reel Kazançlar"))
    assert res.cycle(now_ms=now) == {"calendar_added": 0, "pre": 0, "post": 0}


def test_notlar_diske_yazilir_ve_yeniden_yuklenir(izole, monkeypatch):
    res, cal = izole
    monkeypatch.setattr(res, "_ingest_news_events", lambda now: 0)
    monkeypatch.setattr(cal, "refresh", lambda *a, **k: 0)
    now = int(time.time() * 1000)
    cal.add_event(_ev(now + 4 * 3600_000))
    res.cycle(now_ms=now)
    yeni = R.Researcher()
    assert yeni.notes(), "notlar diskten geri yüklenmedi"


def test_bias_aktif_pencerede_not_dondurur(izole, monkeypatch):
    res, cal = izole
    monkeypatch.setattr(res, "_ingest_news_events", lambda now: 0)
    monkeypatch.setattr(cal, "refresh", lambda *a, **k: 0)
    now = int(time.time() * 1000)
    cal.add_event(_ev(now + 20 * 60_000))     # 20 dk sonra -> aktif pencere
    res.cycle(now_ms=now)
    b = res.bias("BTC", now_ms=now)
    assert b["count"] == 1 and b["titles"] == ["TÜFE (CPI)"]


def test_bias_pencere_disinda_sifir(izole):
    res, _ = izole
    assert res.bias("BTC")["score"] == 0.0


def test_olay_anahtar_kelimeleri_makro_terimleri_icerir():
    kw = R._event_keywords(_ev(0))
    assert "cpi" in kw and "inflation" in kw


def test_hata_durumunda_dongu_cokmez(izole, monkeypatch):
    res, cal = izole
    monkeypatch.setattr(res, "_ingest_news_events", lambda now: 0)

    def boom(*a, **k):
        raise OSError("ağ yok")

    monkeypatch.setattr(cal, "refresh", boom)
    assert res.cycle() == {"calendar_added": 0, "pre": 0, "post": 0}


def test_watcher_kapaliyken_baslamaz(izole, monkeypatch):
    res, _ = izole
    monkeypatch.setenv("RESEARCH_WATCHER", "0")
    assert res.start() is False and res.running() is False
