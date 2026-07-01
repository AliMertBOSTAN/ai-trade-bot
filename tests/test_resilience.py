"""Dayanıklılık: HTTP retry sınıflandırma (her zaman) + RPC failover (web3 varsa)."""
import urllib.error

import pytest

from engine.marketdata import http


def test_retryable_classification():
    # 5xx / 429 geçici → retry
    assert http._is_retryable(urllib.error.HTTPError("u", 503, "x", {}, None))
    assert http._is_retryable(urllib.error.HTTPError("u", 429, "x", {}, None))
    # 404 / 400 kalıcı → retry yok
    assert not http._is_retryable(urllib.error.HTTPError("u", 404, "x", {}, None))
    assert not http._is_retryable(urllib.error.HTTPError("u", 400, "x", {}, None))
    # ağ/bağlantı hatası → geçici
    assert http._is_retryable(urllib.error.URLError("dns fail"))
    assert http._is_retryable(TimeoutError("timeout"))


# Aşağıdaki testler web3 gerektirir (provider modülü import zamanı web3'e bağlı).
# web3 kurulu değilse temiz şekilde atlanır; CI'da (requirements ile) çalışır.
pytest.importorskip("web3")
from engine.web3x import provider  # noqa: E402


def test_rpc_candidates_include_public_fallback():
    urls = provider._candidate_urls(1)  # Ethereum
    assert len(urls) >= 1
    assert any("eth" in u or "cloudflare" in u for u in urls)


def test_rpc_candidates_dedupe_and_priority(monkeypatch):
    monkeypatch.setitem(provider.settings.rpc, 1,
                        "https://my-node.example,https://eth.llamarpc.com")
    urls = provider._candidate_urls(1)
    assert urls[0] == "https://my-node.example"
    assert urls.count("https://eth.llamarpc.com") == 1


def test_unknown_chain_without_fallback_is_empty(monkeypatch):
    monkeypatch.setitem(provider.settings.rpc, 99999, "")
    assert provider._candidate_urls(99999) == []
