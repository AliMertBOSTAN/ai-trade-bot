"""Live güvenlik: keystore + harcama limiti testleri."""
from engine.security.spending import SpendingLimiter
from engine.security import keystore


def test_spending_unlimited_when_zero():
    sl = SpendingLimiter(0.0)
    assert sl.allowed(1_000_000) is True
    sl.record(1_000_000)
    assert sl.allowed(1_000_000) is True  # 0 = limitsiz


def test_spending_blocks_over_limit():
    sl = SpendingLimiter(1000.0)
    assert sl.allowed(600) is True
    sl.record(600)
    assert sl.spent_today() == 600
    assert sl.allowed(500) is False   # 600+500 > 1000
    assert sl.allowed(400) is True    # 600+400 = 1000 tam
    assert sl.remaining() == 400


def test_spending_reset():
    sl = SpendingLimiter(1000.0)
    sl.record(800)
    sl.reset_daily()
    assert sl.spent_today() == 0
    assert sl.remaining() == 1000


def test_keystore_roundtrip(tmp_path, monkeypatch):
    # bilinen test anahtari (yalnizca test!)
    pk = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
    path = str(tmp_path / "ks.json")
    addr = keystore.create_keystore(pk, "parola123", path)
    assert addr.startswith("0x") and len(addr) == 42
    # keystore'dan yukle -> ayni anahtar
    monkeypatch.setenv("WALLET_KEYSTORE_PATH", path)
    monkeypatch.setenv("WALLET_KEYSTORE_PASSWORD", "parola123")
    monkeypatch.delenv("WALLET_PRIVATE_KEY", raising=False)
    loaded = keystore.load_private_key()
    assert loaded is not None and loaded.lower() == pk.lower()
    assert keystore.derive_address() == addr


def test_keystore_wrong_password_failsafe(tmp_path, monkeypatch):
    pk = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
    path = str(tmp_path / "ks.json")
    keystore.create_keystore(pk, "dogru", path)
    monkeypatch.setenv("WALLET_KEYSTORE_PATH", path)
    monkeypatch.setenv("WALLET_KEYSTORE_PASSWORD", "yanlis")
    assert keystore.load_private_key() is None  # fail-safe


def test_plaintext_fallback(monkeypatch):
    monkeypatch.delenv("WALLET_KEYSTORE_PATH", raising=False)
    monkeypatch.setenv("WALLET_PRIVATE_KEY", "0xabc")
    assert keystore.load_private_key() == "0xabc"


def test_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("WALLET_KEYSTORE_PATH", raising=False)
    monkeypatch.delenv("WALLET_PRIVATE_KEY", raising=False)
    assert keystore.load_private_key() is None
