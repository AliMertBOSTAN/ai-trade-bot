"""Haber izleyici testleri: dedupe, etki skoru, taze bias, alım freni,
sinyal motoru entegrasyonu ve LLM fail-safe."""
from __future__ import annotations

import time

import pytest

from engine.marketdata import news_watcher as nw_mod
from engine.marketdata.news_watcher import NewsWatcher, _assess_keyword


def _item(title, summary="", source="test", link=""):
    return {"source": source, "title": title, "summary": summary,
            "link": link or f"https://x/{abs(hash(title))}", "ts": 0}


@pytest.fixture()
def watcher(monkeypatch):
    """Ağ'a çıkmayan, LLM'siz taze izleyici."""
    w = NewsWatcher()
    monkeypatch.setattr(w, "_use_llm", lambda: False)
    return w


# ---------------- anahtar-kelime değerlendirme ----------------

def test_keyword_assess_bearish_hack_yuksek_etki():
    a = _assess_keyword(_item("Major DEX hacked, $100M exploit drains funds"))
    assert a["score"] < 0
    assert a["impact"] >= 0.8
    assert a["relevant"] is True


def test_keyword_assess_token_eslesmesi():
    a = _assess_keyword(_item("Ethereum ETF approval boosts ETH rally"))
    assert "ETH" in a["tokens"]
    assert a["score"] > 0
    assert a["impact"] >= 0.5


def test_keyword_assess_alakasiz_haber():
    a = _assess_keyword(_item("Local football team wins championship"))
    assert a["relevant"] is False
    assert a["tokens"] == []


# ---------------- tarama / dedupe ----------------

def test_poll_dedupe_ve_ilk_tarama_arsiv_sayilmaz(watcher, monkeypatch):
    batch1 = [_item("Bitcoin rises"), _item("Ethereum hacked badly")]
    monkeypatch.setattr(watcher, "_fetch", lambda limit, ttl: batch1)
    # İlk tarama: arşiv prime edilir, "yeni haber" üretilmez.
    assert watcher.poll_once(now=1000.0) == []
    # Aynı başlıklar tekrar gelirse yine yeni sayılmaz.
    assert watcher.poll_once(now=1060.0) == []
    # Yeni bir başlık eklenince yalnızca o döner.
    batch2 = batch1 + [_item("Solana network outage halts trading")]
    monkeypatch.setattr(watcher, "_fetch", lambda limit, ttl: batch2)
    fresh = watcher.poll_once(now=1120.0)
    assert len(fresh) == 1
    assert "Solana" in fresh[0]["title"]
    assert fresh[0]["assessor"] == "keyword"


# ---------------- taze bias + fren ----------------

def _prime_with(watcher, monkeypatch, items, now):
    monkeypatch.setattr(watcher, "_fetch", lambda limit, ttl: [])
    watcher.poll_once(now=now - 1)  # prime (boş arşiv)
    monkeypatch.setattr(watcher, "_fetch", lambda limit, ttl: items)
    return watcher.poll_once(now=now)


def test_fresh_bias_negatif_breaking_ve_guard(watcher, monkeypatch):
    now = time.time()
    fresh = _prime_with(watcher, monkeypatch,
                        [_item("Ethereum bridge hacked, funds stolen in exploit")],
                        now)
    assert fresh and fresh[0]["breaking"] is True

    bias = watcher.fresh_bias("WETH", now=now + 60)   # WETH -> ETH normalize
    assert bias["count"] == 1
    assert bias["score"] < 0
    assert bias["breaking"] is True

    g = watcher.guard("ETH", now=now + 60)
    assert g is not None and "negatif son-dakika" in g
    # 15 dk fren penceresi dışında serbest
    assert watcher.guard("ETH", now=now + 16 * 60) is None
    # Haber ETH'ye eşlendi -> alakasız sembole fren uygulanmaz
    assert watcher.guard("LINK", now=now + 60) is None


def test_fresh_bias_pozitif_ve_pencere_disi(watcher, monkeypatch):
    now = time.time()
    _prime_with(watcher, monkeypatch,
                [_item("Bitcoin ETF approval: record inflows, rally continues")],
                now)
    bias = watcher.fresh_bias("BTC", now=now + 60)
    assert bias["score"] > 0 and bias["count"] == 1
    # Pencere (varsayılan 45 dk) dışında taze sayılmaz.
    old = watcher.fresh_bias("BTC", now=now + 46 * 60)
    assert old["count"] == 0 and old["score"] == 0.0


def test_fresh_bias_piyasa_geneline_dusme(watcher, monkeypatch):
    now = time.time()
    _prime_with(watcher, monkeypatch,
                [_item("SEC announces sweeping crypto regulation crackdown ban")],
                now)
    # UNI başlıkta geçmiyor -> tokens boş, yüksek etkili genel haber yarı ağırlıkla.
    bias = watcher.fresh_bias("UNI", now=now + 30)
    assert bias["market"] is True
    assert bias["count"] == 1


# ---------------- LLM fail-safe ----------------

def test_llm_bozuk_yanit_keyword_sonucu_korur(monkeypatch):
    w = NewsWatcher()
    monkeypatch.setattr(w, "_use_llm", lambda: True)
    monkeypatch.setattr("engine.signals.llm.complete",
                        lambda *a, **k: "hiç JSON değil")
    now = time.time()
    fresh = _prime_with(w, monkeypatch,
                        [_item("Exchange hacked: bitcoin plunges")], now)
    assert fresh[0]["assessor"] == "keyword"   # LLM parse edilemedi -> keyword
    assert fresh[0]["score"] < 0


def test_llm_yaniti_skoru_netlestirir(monkeypatch):
    w = NewsWatcher()
    monkeypatch.setattr(w, "_use_llm", lambda: True)
    resp = '{"items": [{"i": 0, "score": -0.9, "impact": 0.9, "tokens": ["BTC"], "note": "borsa hack"}]}'
    monkeypatch.setattr("engine.signals.llm.complete", lambda *a, **k: resp)
    now = time.time()
    fresh = _prime_with(w, monkeypatch,
                        [_item("Exchange hacked: bitcoin plunges")], now)
    assert fresh[0]["assessor"] == "llm"
    assert fresh[0]["score"] == -0.9
    assert "BTC" in fresh[0]["tokens"]


# ---------------- sinyal motoru entegrasyonu ----------------

def test_generate_signal_breaking_negatif_buy_guvenini_kisar(monkeypatch):
    from engine.signals import engine as sig_engine

    # Yükselen seri -> kural kararı BUY üretir.
    closes = [100 + i * 0.8 + (0.4 if i % 2 else -0.4) for i in range(60)]

    monkeypatch.setattr(sig_engine.market_news, "sentiment",
                        lambda base, limit=40: {"score": 0.0, "label": "notr",
                                                "count": 5, "matched": 0,
                                                "market": True, "headlines": []})
    neg = {"score": -0.8, "count": 2, "breaking": True,
           "headlines": ["Ethereum hacked"], "market": False}
    monkeypatch.setattr(sig_engine.news_watcher, "fresh_bias", lambda s: neg)
    monkeypatch.setattr(sig_engine.news_watcher, "fresh_for",
                        lambda s, limit=5: [])
    monkeypatch.setattr(sig_engine, "_should_consult_llm",
                        lambda *a, **k: False)

    sig = sig_engine.generate_signal(1, "WETH", "USDC", closes)
    if sig.action == "BUY":
        assert sig.confidence <= 0.45
        assert sig.breakdown["freshBreaking"] is True
        assert "kisildi" in sig.breakdown["freshNote"]
    # Her durumda taze haber breakdown'a işlenmiş olmalı.
    assert sig.breakdown["freshNewsScore"] == -0.8
    assert sig.breakdown["freshNewsCount"] == 2


def test_generate_signal_izleyici_bos_davranis_degismez(monkeypatch):
    from engine.signals import engine as sig_engine

    closes = [100 + i * 0.8 for i in range(60)]
    monkeypatch.setattr(sig_engine.market_news, "sentiment",
                        lambda base, limit=40: {"score": 0.2, "label": "pozitif",
                                                "count": 3, "matched": 1,
                                                "market": False, "headlines": ["x"]})
    empty = {"score": 0.0, "count": 0, "breaking": False,
             "headlines": [], "market": True}
    monkeypatch.setattr(sig_engine.news_watcher, "fresh_bias", lambda s: empty)
    monkeypatch.setattr(sig_engine, "_should_consult_llm",
                        lambda *a, **k: False)
    sig = sig_engine.generate_signal(1, "WETH", "USDC", closes)
    assert sig.breakdown["freshNewsCount"] == 0
    assert sig.breakdown["freshNote"] == "yok"
    assert 0.0 <= sig.confidence <= 1.0


def test_breaking_llm_cooldown_kirilir(monkeypatch):
    from types import SimpleNamespace
    from engine.signals import engine as sig_engine
    # settings frozen dataclass -> modül seviyesinde sahte nesneyle değiştir.
    monkeypatch.setattr(sig_engine, "settings",
                        SimpleNamespace(llm_provider="deepseek"))
    sig_engine._llm_last.clear()
    try:
        # Normal yol: düşük güven -> LLM'e gidilmez.
        assert sig_engine._should_consult_llm("ETH", "BUY", 0.30) is False
        # Breaking: eşik/cooldown kırılır.
        assert sig_engine._should_consult_llm("ETH", "BUY", 0.30,
                                              breaking=True) is True
        # Ama art arda breaking çağrıları en az 180 sn aralıklı.
        assert sig_engine._should_consult_llm("ETH", "BUY", 0.30,
                                              breaking=True) is False
    finally:
        sig_engine._llm_last.clear()


def test_watcher_status_ve_api_semasi(watcher):
    st = watcher.status()
    assert set(st) >= {"running", "intervalS", "freshWindowMin",
                       "llmAssess", "lastPollMs", "eventCount"}
    assert watcher.recent_events() == []
