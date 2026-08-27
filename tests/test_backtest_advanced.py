"""backtester (zengin metrik) + walk_forward testleri."""
import math

from engine.backtest.backtester import run_backtest
from engine.backtest.walk_forward import walk_forward
from engine.config.settings import RiskConfig
from engine.trading.exits import ExitConfig


def _candles(n=200):
    out = []
    for i in range(n):
        c = 100 + 20 * math.sin(i / 12) + i * 0.15
        out.append({"t": i * 3600_000, "open": c, "high": c + 1,
                    "low": c - 1, "close": c, "volume": 1000.0})
    return out


def test_backtest_returns_rich_metrics():
    res = run_backtest(_candles(), "ETH", "USDC", 10000,
                       RiskConfig(min_confidence=0.3), interval="1h")
    for k in ("sharpe", "sortino", "calmar", "profit_factor",
              "expectancy_usd", "max_drawdown_pct", "num_closed_trades"):
        assert k in res
    assert res["max_drawdown_pct"] >= 0


def test_walk_forward_runs_and_reports():
    # 360 mum, 2 kat -> seg=180, %60 train=108, test=72 (>=40 gecerli)
    wf = walk_forward(_candles(360), "ETH", "USDC", 10000,
                      RiskConfig(min_confidence=0.3),
                      min_conf_grid=[0.3, 0.5, 0.7], n_folds=2, interval="1h")
    assert "folds" in wf and "robust" in wf and "total_folds" in wf
    assert wf["total_folds"] >= 1


def test_backtest_atr_mode_reports_exits():
    """ATR (canlı-eşdeğer) mod: exit_breakdown döner, davranış deterministik."""
    res = run_backtest(_candles(), "ETH", "USDC", 10000,
                       RiskConfig(min_confidence=0.3), interval="1h",
                       exit_style="atr",
                       exit_cfg=ExitConfig(atr_stop_mult=2.0, trail_mult=2.5))
    assert res["exit_style"] == "atr"
    assert isinstance(res["exit_breakdown"], dict)


def test_backtest_default_is_backward_compatible():
    """Varsayılan çağrı eski (fixed) davranışla aynı sonucu vermeli."""
    a = run_backtest(_candles(), "ETH", "USDC", 10000,
                     RiskConfig(min_confidence=0.3), interval="1h")
    b = run_backtest(_candles(), "ETH", "USDC", 10000,
                     RiskConfig(min_confidence=0.3), interval="1h",
                     exit_style="fixed", cooldown_bars=0, risk_pct=0.0)
    assert a["total_return_pct"] == b["total_return_pct"]
    assert a["num_closed_trades"] == b["num_closed_trades"]


def test_backtest_cooldown_reduces_or_equals_trades():
    """Cooldown açıkken işlem sayısı artmamalı (aşırı-işlem freni)."""
    kw = dict(interval="1h", exit_style="atr",
              exit_cfg=ExitConfig(atr_stop_mult=2.0, trail_mult=2.5))
    no_cd = run_backtest(_candles(400), "ETH", "USDC", 10000,
                         RiskConfig(min_confidence=0.3), cooldown_bars=0, **kw)
    with_cd = run_backtest(_candles(400), "ETH", "USDC", 10000,
                           RiskConfig(min_confidence=0.3), cooldown_bars=24, **kw)
    assert len(with_cd["trades"]) <= len(no_cd["trades"])


def test_backtest_risk_pct_caps_position_size():
    """Küçük risk_pct, ilk alım nominalini belirgin küçültmeli."""
    big = run_backtest(_candles(), "ETH", "USDC", 10000,
                       RiskConfig(min_confidence=0.3, max_position_usd=10000),
                       interval="1h", exit_style="atr", risk_pct=0.0)
    small = run_backtest(_candles(), "ETH", "USDC", 10000,
                         RiskConfig(min_confidence=0.3, max_position_usd=10000),
                         interval="1h", exit_style="atr", risk_pct=0.001)
    buys_b = [t for t in big["trades"] if t["side"] == "BUY"]
    buys_s = [t for t in small["trades"] if t["side"] == "BUY"]
    if buys_b and buys_s:
        nb = buys_b[0]["amount"] * buys_b[0]["price"]
        ns = buys_s[0]["amount"] * buys_s[0]["price"]
        assert ns < nb


def test_walk_forward_param_grid_mode():
    """Çok-boyutlu ızgara (ATR modu) walk-forward yolu çalışmalı."""
    grid = {"min_confidence": [0.3, 0.5], "trail_mult": [2.5],
            "atr_stop_mult": [2.0], "cooldown_bars": [0, 8], "risk_pct": [0.0]}
    wf = walk_forward(_candles(360), "ETH", "USDC", 10000,
                      RiskConfig(min_confidence=0.3), min_conf_grid=[0.3],
                      n_folds=2, interval="1h", param_grid=grid)
    assert wf["total_folds"] >= 1
    assert all("chosen_params" in f for f in wf["folds"])


def test_htf_flags_follow_trend_without_lookahead():
    """HTF bayrakları: yükselişte True, düşüşte False; uzunluk bar sayısına eşit."""
    from engine.backtest.backtester import htf_up_flags
    n = 800  # 200 adet 4x kova -> ısınma (35) fazlasıyla aşılır
    up = [{"t": i * 3600_000, "open": 100 + i, "high": 101 + i,
           "low": 99 + i, "close": 100 + i * 0.5, "volume": 1.0} for i in range(n)]
    down = [{"t": i * 3600_000, "open": 900 - i, "high": 901 - i,
             "low": 899 - i, "close": 900 - i * 0.5, "volume": 1.0} for i in range(n)]
    fu, fd = htf_up_flags(up), htf_up_flags(down)
    assert len(fu) == n and len(fd) == n
    assert fu[-1] is True
    assert fd[-1] is False


def test_backtest_htf_filter_blocks_or_neutral():
    """htf_filter=ema: sonuç htf_blocked sayacı döndürür, çalışır."""
    res = run_backtest(_candles(400), "ETH", "USDC", 10000,
                       RiskConfig(min_confidence=0.3), interval="1h",
                       exit_style="atr", htf_filter="ema")
    assert isinstance(res["htf_blocked"], int)
    assert res["htf_blocked"] >= 0


def test_exit_manager_short_mirror():
    """Short tarafında trailing/breakeven/kısmi TP aynalı çalışmalı."""
    from engine.trading.exits import ExitManager, ExitState

    em = ExitManager()                       # stop 2.0 / trail 2.5 / tp 3.0 / be 1.0
    st = ExitState(entry=100.0, atr=2.0, side="short")
    assert em.update(st, 99.0).action == "HOLD"
    d = em.update(st, 93.0)                  # ≤ 94 → kısmi TP; başabaş da taşındı
    assert d.action == "PARTIAL" and st.breakeven_moved
    assert em.update(st, 97.9).action == "HOLD"   # stop=min(104, 93+5, 100)=98
    d = em.update(st, 98.2)                  # ≥ 98 → trailing çıkışı
    assert d.action == "EXIT" and d.reason == "trailing-stop"


def test_exit_manager_long_behavior_unchanged():
    """Long tarafı eski davranışla aynı kalmalı (geriye dönük)."""
    from engine.trading.exits import ExitManager, ExitState

    em = ExitManager()
    st = ExitState(entry=100.0, atr=2.0)     # side=long varsayılan
    d = em.update(st, 95.0)                  # ≤ 96 (giriş - 2×ATR) → stop-loss
    assert d.action == "EXIT" and d.reason == "stop-loss"


def test_backtest_allow_short_opens_short_in_downtrend():
    """allow_short: düşüş trendinde SELL-open üretir; long-only üretmez."""
    n = 400
    candles = []
    for i in range(n):
        c = 500 - i * 0.8 + 8 * math.sin(i / 6)
        candles.append({"t": i * 3600_000, "open": c, "high": c + 2,
                        "low": c - 2, "close": c, "volume": 1000.0})
    kw = dict(interval="1h", exit_style="atr", cooldown_bars=8)
    lo = run_backtest(candles, "ETH", "USDC", 10000,
                      RiskConfig(min_confidence=0.3), allow_short=False, **kw)
    sh = run_backtest(candles, "ETH", "USDC", 10000,
                      RiskConfig(min_confidence=0.3), allow_short=True, **kw)
    lo_buys = [t for t in lo["trades"] if t["side"] == "BUY"]
    sh_sell_opens = [t for t in sh["trades"] if t["side"] == "SELL"]
    assert sh["allow_short"] is True
    # düşüş trendinde: long-only girmezken short modu SELL-open üretir
    assert len(sh_sell_opens) > len(lo_buys)
    assert sh["final_equity_usd"] > 0


def test_risk_edge_gate_blocks_low_volatility_entry():
    """Maliyet kapısı: beklenen hareket maliyeti karşılamıyorsa yeni alım reddedilir."""
    from engine.models import TechnicalSnapshot, TradeSignal
    from engine.risk.manager import RiskManager

    def _sig(atr: float) -> TradeSignal:
        tech = TechnicalSnapshot(rsi=50, ema_fast=1, ema_slow=1, macd=0,
                                 macd_signal=0, momentum=0, price=100.0, atr=atr)
        return TradeSignal(chain_id=0, base="ETH", quote="USD", action="BUY",
                           confidence=0.9, technical=tech, rationale="t",
                           source="technical")

    # kapı kapalı (varsayılan): düşük ATR'de bile onay
    rm_off = RiskManager(RiskConfig(min_confidence=0.5))
    assert rm_off.evaluate(_sig(atr=0.01), {}, 10_000).approved

    # kapı açık: ATR %0.01 -> beklenen hareket %0.03 << 2x maliyet -> ret
    rm_on = RiskManager(RiskConfig(min_confidence=0.5, min_edge_ratio=2.0))
    d = rm_on.evaluate(_sig(atr=0.01), {}, 10_000)
    assert not d.approved and "maliyet" in d.reason

    # yüksek ATR (%5) -> beklenen hareket %15 >> maliyet -> onay
    assert rm_on.evaluate(_sig(atr=5.0), {}, 10_000).approved
