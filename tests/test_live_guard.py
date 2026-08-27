"""Canlı moda geçiş kapıları + LiveBroker sertleştirmesi (ağa çıkmaz)."""
from __future__ import annotations

import types

import pytest

from engine.bot.orchestrator import bot
from engine.config.settings import RiskConfig


# --------------------------------------------------------- set_mode kapısı

def test_live_moda_gecis_onucus_basarisizsa_reddedilir(monkeypatch):
    monkeypatch.setattr(bot, "live_preflight", lambda: {
        "ready": False, "checks": {"funded_chain": False, "rpc_available": True}})
    monkeypatch.delenv("LIVE_FORCE", raising=False)
    out = bot.set_mode("live")
    assert out["mode"] != "live"
    assert "funded_chain" in bot.message


def test_live_moda_gecis_onucus_gecerse_izin_verilir(monkeypatch):
    cagrildi: list[str] = []
    monkeypatch.setattr(bot, "live_preflight", lambda: {"ready": True, "checks": {}})
    monkeypatch.setattr(bot.executor, "set_mode", lambda m: cagrildi.append(m))
    monkeypatch.setattr(bot, "_persist_state", lambda: None)
    bot.set_mode("live")
    assert cagrildi == ["live"], "ön-uçuş geçtiğinde executor live'a alınmalı"


def test_force_bayragi_onucusu_atlar(monkeypatch):
    def patlat():
        raise AssertionError("preflight çağrılmamalıydı")

    cagrildi: list[str] = []
    monkeypatch.setattr(bot, "live_preflight", patlat)
    monkeypatch.setattr(bot.executor, "set_mode", lambda m: cagrildi.append(m))
    monkeypatch.setattr(bot, "_persist_state", lambda: None)
    bot.set_mode("live", force=True)          # preflight ÇAĞRILMAMALI
    assert cagrildi == ["live"]


def test_paper_moda_donus_her_zaman_serbest(monkeypatch):
    def patlat():
        raise AssertionError("paper'a dönüşte preflight çalışmamalı")

    monkeypatch.setattr(bot, "live_preflight", patlat)
    monkeypatch.setattr(bot, "_persist_state", lambda: None)
    assert bot.set_mode("paper")["mode"] == "paper"


# ------------------------------------------------------ LiveBroker koruma

class _FakeEth:
    def __init__(self, gas_price=1_000_000, base_fee=None, tip=1_000):
        self.gas_price = gas_price
        self._base_fee = base_fee
        self.max_priority_fee = tip
        self.chain_id = 8453

    def get_transaction_count(self, addr):
        return 7

    def get_block(self, _which):
        return {"baseFeePerGas": self._base_fee} if self._base_fee else {}


class _FakeW3:
    def __init__(self, **kw):
        self.eth = _FakeEth(**kw)

    @staticmethod
    def to_wei(v, unit):
        return int(v * 1e9)


def _broker(monkeypatch, max_gas_gwei=80.0):
    from engine.trading import live_broker as lb
    monkeypatch.setattr(lb, "load_private_key", lambda: None, raising=False)
    b = lb.LiveBroker.__new__(lb.LiveBroker)      # __init__ (anahtar) atlanır
    b.risk = RiskConfig(max_gas_gwei=max_gas_gwei)
    b.account = types.SimpleNamespace(address="0x" + "11" * 20)
    return b


def test_eip1559_zincirinde_max_fee_alanlari_kullanilir(monkeypatch):
    b = _broker(monkeypatch)
    tx = b._base_tx(_FakeW3(base_fee=500_000))
    assert "maxFeePerGas" in tx and "gasPrice" not in tx
    assert tx["maxPriorityFeePerGas"] <= tx["maxFeePerGas"]
    assert tx["nonce"] == 7 and tx["chainId"] == 8453


def test_max_fee_gas_tavanini_asamaz(monkeypatch):
    b = _broker(monkeypatch, max_gas_gwei=0.05)          # 0.05 gwei tavan
    tx = b._base_tx(_FakeW3(gas_price=10_000, base_fee=10_000_000))
    assert tx["maxFeePerGas"] <= int(0.05 * 1e9)


def test_1559_desteklemeyen_zincirde_legacy_gas_price(monkeypatch):
    b = _broker(monkeypatch)
    tx = b._base_tx(_FakeW3(base_fee=None))
    assert tx["gasPrice"] == 1_000_000 and "maxFeePerGas" not in tx


def test_gas_tavani_asilinca_tx_kurulmaz(monkeypatch):
    b = _broker(monkeypatch, max_gas_gwei=5.0)
    with pytest.raises(RuntimeError, match="tavan"):
        b._base_tx(_FakeW3(gas_price=int(9 * 1e9)))


@pytest.mark.parametrize("attr", ["rawTransaction", "raw_transaction"])
def test_imzali_tx_ham_baytlari_her_eth_account_surumunde_okunur(attr):
    from engine.trading.live_broker import LiveBroker
    signed = types.SimpleNamespace(**{attr: b"\x02\xf8"})
    assert LiveBroker._raw(signed) == b"\x02\xf8"


def test_bilinmeyen_imza_nesnesi_net_hata_verir():
    from engine.trading.live_broker import LiveBroker
    with pytest.raises(RuntimeError, match="ham baytları"):
        LiveBroker._raw(types.SimpleNamespace())
