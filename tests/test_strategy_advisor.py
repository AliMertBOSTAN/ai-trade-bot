"""AI strateji danışmanı testleri (ağ gerektirmez; LLM yoksa heuristic)."""
from __future__ import annotations

from engine.strategy.advisor import (_validate_advice, get_advice,
                                     heuristic_advice, per_strategy_stats)


def _trade(side, price, amount=1.0, strategy=None, ts=0, fee=0.0):
    reason = f"ALIM · pozisyon açılışı · strateji: {strategy} · test" if strategy \
        else "SATIM · pozisyon kapanışı · stop-loss"
    return {"chainId": 1, "base": "WETH", "side": side, "amount": amount,
            "filledPrice": price, "price": price, "feeUsd": fee,
            "status": "filled", "timestamp": ts, "reason": reason}


def test_per_strategy_stats_attribution():
    trades = [
        _trade("BUY", 100.0, strategy="trend", ts=1),
        _trade("SELL", 110.0, ts=2),               # SL/TP çıkışı → trend'e atfedilir
        _trade("BUY", 100.0, strategy="momentum", ts=3),
        _trade("SELL", 95.0, ts=4),
    ]
    st = per_strategy_stats(trades)
    assert st["trend"]["trades"] == 1 and st["trend"]["pnl_usd"] == 10.0
    assert st["trend"]["win_rate"] == 1.0
    assert st["momentum"]["pnl_usd"] == -5.0 and st["momentum"]["win_rate"] == 0.0


def test_heuristic_cuts_losers_boosts_winners():
    stats = {
        "trend": {"trades": 8, "wins": 6, "pnl_usd": 40.0,
                  "win_rate": 0.75, "expectancy_usd": 5.0},
        "momentum": {"trades": 8, "wins": 2, "pnl_usd": -30.0,
                     "win_rate": 0.25, "expectancy_usd": -3.75},
    }
    config = [{"name": "trend", "weight": 1.0, "enabled": True},
              {"name": "momentum", "weight": 1.0, "enabled": True}]
    adv = heuristic_advice(stats, config, {"trend_up": 5, "trend_down": 0,
                                           "range": 1}, 0.73)
    by = {s["name"]: s for s in adv["strategies"]}
    assert by["trend"]["weight"] > 1.0        # kazanan güçlendi
    assert by["momentum"]["weight"] < 1.0     # kaybeden kısıldı
    assert 0.50 <= adv["min_confidence"] <= 0.95


def test_heuristic_never_disables_all():
    stats = {"hybrid": {"trades": 10, "wins": 1, "pnl_usd": -50.0,
                        "win_rate": 0.1, "expectancy_usd": -5.0}}
    config = [{"name": "hybrid", "weight": 0.5, "enabled": True}]
    adv = heuristic_advice(stats, config, {"trend_up": 0, "trend_down": 0,
                                           "range": 3}, 0.73)
    assert any(s["enabled"] for s in adv["strategies"])  # fail-safe


def test_validate_advice_rejects_garbage():
    known = {"trend", "hybrid"}
    assert _validate_advice(None, known, 0.7) is None
    assert _validate_advice({"strategies": "x"}, known, 0.7) is None
    # bilinmeyen strateji adları elenir; hiç geçerli kalmazsa None
    bad = {"strategies": [{"name": "yolo", "enabled": True, "weight": 1}]}
    assert _validate_advice(bad, known, 0.7) is None
    # hepsi kapalıysa None (fail-safe)
    off = {"strategies": [{"name": "trend", "enabled": False, "weight": 1}]}
    assert _validate_advice(off, known, 0.7) is None
    ok = {"min_confidence": 5.0, "rationale": "r",
          "strategies": [{"name": "trend", "enabled": True, "weight": 99}]}
    v = _validate_advice(ok, known, 0.7)
    assert v["min_confidence"] == 0.95 and v["strategies"][0]["weight"] == 3.0


def test_get_advice_falls_back_to_heuristic(monkeypatch):
    """LLM anahtarı yokken kaynak 'heuristic' olmalı."""
    import engine.strategy.advisor as adv_mod
    monkeypatch.setattr(adv_mod.llm_layer, "complete", lambda *a, **k: None)
    adv = get_advice({}, [{"name": "hybrid", "weight": 1.0, "enabled": True}],
                     {"trend_up": 0, "trend_down": 0, "range": 0}, 0.73)
    assert adv["source"] == "heuristic"
    assert adv["strategies"]


def test_bot_advice_roundtrip(tmp_path, monkeypatch):
    """get_strategy_advice + apply_strategy_advice uçtan uca."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("PAPER_SEED_USD", "0")
    monkeypatch.setenv("LLM_PROVIDER", "none")
    import importlib
    import engine.config.settings as st
    importlib.reload(st)
    import engine.storage.db as db
    importlib.reload(db)
    import engine.bot.orchestrator as orch
    importlib.reload(orch)
    b = orch.TradingBot()
    advice = b.get_strategy_advice()
    assert advice["source"] in ("llm", "heuristic")
    assert advice["strategies"]
    assert "current_min_confidence" in advice
    r = b.apply_strategy_advice(
        [{"name": "trend", "enabled": True, "weight": 2.0}],
        min_confidence=0.70)
    assert r["ok"] and r["applied"] == 1
    assert abs(b.risk.min_confidence - 0.70) < 1e-9
    assert b._preset == "ai"
    w = {a.strategy.name: a.weight for a in b.strategies.allocations}
    assert w["trend"] == 2.0
