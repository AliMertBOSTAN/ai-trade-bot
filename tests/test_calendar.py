"""Ekonomik veri takvimi testleri — ağa ÇIKMAZ (fetcher enjekte edilir)."""
from __future__ import annotations

import time

import pytest

from engine.marketdata.calendar import (BLS_ICS, CalendarEvent, EconomicCalendar,
                                        extract_event_dates, parse_ics)

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:test-cpi-1
DTSTART;TZID=US-Eastern:20260812T083000
SUMMARY:Consumer Price Index
CATEGORIES:IMPORTANT, BLS
END:VEVENT
BEGIN:VEVENT
UID:test-ppi-1
DTSTART;TZID=US-Eastern:20260813T083000
SUMMARY:Producer Price Index
END:VEVENT
BEGIN:VEVENT
UID:test-jan-1
DTSTART;TZID=US-Eastern:20260113T083000
SUMMARY:Consumer Price Index
END:VEVENT
END:VCALENDAR
"""


def _cal(tmp_path, monkeypatch) -> EconomicCalendar:
    """İzole takvim: önbellek/özel dosya tmp'ye yönlenir."""
    monkeypatch.setattr("engine.marketdata.calendar._CACHE_PATH",
                        str(tmp_path / "cal.json"))
    monkeypatch.setattr("engine.marketdata.calendar._CUSTOM_PATH",
                        str(tmp_path / "custom.json"))
    return EconomicCalendar()


def test_parse_ics_basliklari_normalize_eder():
    evs = parse_ics(SAMPLE_ICS)
    titles = {e.title for e in evs}
    assert "TÜFE (CPI)" in titles
    assert "ÜFE (PPI)" in titles
    cpi = next(e for e in evs if e.title == "TÜFE (CPI)")
    assert cpi.importance == 1.0
    assert cpi.category == "macro"


def test_ics_saati_dogru_utc_ye_cevrilir():
    """08:30 US-Eastern (EDT, Ağustos) = 12:30 UTC."""
    cpi = next(e for e in parse_ics(SAMPLE_ICS) if e.id == "test-cpi-1")
    assert time.strftime("%Y-%m-%d %H:%M", time.gmtime(cpi.ts / 1000)) == "2026-08-12 12:30"


def test_ics_kis_saatinde_est_kullanir():
    """13 Ocak = EST (-5): 08:30 ET = 13:30 UTC."""
    jan = next(e for e in parse_ics(SAMPLE_ICS) if e.id == "test-jan-1")
    assert time.strftime("%H:%M", time.gmtime(jan.ts / 1000)) == "13:30"


def test_refresh_agdan_bagimsiz_calisir(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)
    n = cal.refresh(force=True, fetcher=lambda url: SAMPLE_ICS)
    assert n >= 2
    assert any(e.title == "TÜFE (CPI)" for e in cal.all_events())


def test_refresh_akis_coktugunde_statik_fomc_kalir(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)

    def boom(url):
        raise OSError("ağ yok")

    cal.refresh(force=True, fetcher=boom)
    assert any(e.source == "fomc" for e in cal.all_events())
    assert cal.status()["lastError"]


def test_guard_yuksek_etkili_pencerede_freni_acar(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)
    now = int(time.time() * 1000)
    cal.add_event(CalendarEvent(id="x", title="TÜFE (CPI)", raw_title="CPI",
                                ts=now + 30 * 60_000, category="macro",
                                importance=1.0, source="test"))
    assert cal.guard(now_ms=now) is not None          # 30 dk kala fren AÇIK
    assert cal.guard(now_ms=now - 5 * 3600_000) is None  # 5 saat önce fren YOK


def test_guard_env_ile_kapatilabilir(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)
    now = int(time.time() * 1000)
    cal.add_event(CalendarEvent(id="x", title="FOMC", raw_title="FOMC",
                                ts=now, category="macro", importance=1.0,
                                source="test"))
    assert cal.guard(now_ms=now) is not None
    monkeypatch.setenv("CALENDAR_GUARD", "0")
    assert cal.guard(now_ms=now) is None
    assert cal.size_factor(now_ms=now) == (1.0, "")


def test_orta_etkili_olay_bloklamaz_boyut_kucultur(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)
    now = int(time.time() * 1000)
    cal.add_event(CalendarEvent(id="ppi", title="ÜFE (PPI)", raw_title="PPI",
                                ts=now + 10 * 60_000, category="macro",
                                importance=0.7, source="test"))
    assert cal.guard(now_ms=now) is None        # 0.7 < blok eşiği 0.8
    factor, note = cal.size_factor(now_ms=now)
    assert 0.0 < factor < 1.0 and note


def test_sembole_ozgu_olay_baska_sembolu_engellemez(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)
    now = int(time.time() * 1000)
    cal.add_event(CalendarEvent(id="unlock", title="Token Unlock",
                                raw_title="ARB unlock", ts=now, category="crypto",
                                importance=1.0, source="test", symbols=["ARB"]))
    assert cal.guard("ARB", now_ms=now) is not None
    assert cal.guard("BTC", now_ms=now) is None


@pytest.mark.parametrize("text,beklenen_ay", [
    ("Aptos to unlock $60M tokens on August 12", 8),
    ("SEC decision on Solana ETF expected 10 September 2026", 9),
    ("Ethereum upgrade planned for 3 Kasım", 11),
])
def test_haber_basligindan_tarih_cikarimi(text, beklenen_ay):
    ts = extract_event_dates(text, now_ms=int(time.time() * 1000))
    assert ts, f"tarih bulunamadı: {text}"
    assert time.gmtime(ts[0] / 1000).tm_mon == beklenen_ay


def test_tarihsiz_veya_alakasiz_baslik_olay_uretmez(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)
    assert cal.ingest_headline("Bitcoin rallies past $70k") == []
    assert cal.ingest_headline("Big unlock happened yesterday") == []


def test_haberden_kripto_olayi_takvime_girer(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)
    evs = cal.ingest_headline("Arbitrum token unlock scheduled for December 16")
    assert evs and evs[0].category == "crypto"
    assert "ARB" in evs[0].symbols
    assert evs[0] in cal.all_events()


def test_onbellek_diske_yazilir_ve_okunur(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)
    cal.refresh(force=True, fetcher=lambda url: SAMPLE_ICS)
    cal2 = _cal(tmp_path, monkeypatch)   # ağ YOK, yalnızca önbellek
    assert any(e.title == "TÜFE (CPI)" for e in cal2.all_events())


def test_varsayilan_akis_listesi_bls_icerir(tmp_path, monkeypatch):
    cal = _cal(tmp_path, monkeypatch)
    assert BLS_ICS in cal.ics_feeds()
    monkeypatch.setenv("CALENDAR_ICS_FEEDS", "https://example.com/a.ics")
    assert "https://example.com/a.ics" in cal.ics_feeds()
