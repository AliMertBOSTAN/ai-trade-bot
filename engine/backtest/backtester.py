"""Geçmiş mumlar üzerinde strateji backtest'i (maliyet-farkında).

Rolling pencere ile teknik sinyal üretir (LLM kapalı - hız/determinizm), paper
broker muhasebesiyle (slippage + DEX fee + gas) simüle eder ve risk-ayarlı
performans metrikleri döndürür.

İki çıkış modu:
  • exit_style="fixed": eski davranış — sabit stop-loss/take-profit (RiskConfig).
  • exit_style="atr":   canlı akışla eşit — ExitManager (ATR stop + trailing +
    kısmi kâr + başabaş) + işlem sonrası cooldown + ATR risk-tabanlı boyut.
    Böylece backtest, orchestrator'ın gerçekte kullandığı mantığı ölçer.

allow_short=True ile çift yön: SELL sinyali pozisyon yokken SHORT açar, BUY
short'u kapatır (cover). Kapılar aynalıdır: HTF filtresi short girişini üst-TF
YUKARIYKEN engeller; cooldown ve volatilite boyutlama iki yönde de uygulanır.
(Short yalnız backtest/perp içindir; spot DEX'te short yapılamaz.)
"""
from __future__ import annotations

from engine.analytics import metrics as _metrics
from engine.config.settings import RiskConfig
from engine.indicators.technical import compute_snapshot
from engine.models import Position, TradeOrder, TradeSignal
from engine.risk.manager import RiskManager
from engine.signals.engine import _rule_decision
from engine.sizing.position_sizing import atr_based_size
from engine.trading.exits import ExitConfig, ExitManager, ExitState
from engine.trading.paper_broker import PaperBroker
from engine.trading.portfolio import Portfolio

# interval -> yıldaki periyot sayısı (Sharpe/Sortino/Calmar yıllıklandırması)
_PERIODS_PER_YEAR = {
    "1m": 525600, "5m": 105120, "15m": 35040, "30m": 17520,
    "1h": 8760, "4h": 2190, "1d": 365,
}

# HTF filtresi: üst zaman dilimi = mevcut mum aralığının bu katı (örn. 1h -> 4h)
_HTF_FACTOR = 4


def htf_up_flags(candles: list[dict], warmup_buckets: int = 35) -> list[bool]:
    """Her bar için: 4× üst zaman diliminde EMA trendi yukarı mı?

    Bakış-öncesi (lookahead) yok: yalnızca o barın AÇILIŞINDAN önce tamamen
    kapanmış üst-TF mumları kullanılır. Isınma süresince filtre pasiftir (True).
    """
    if not candles:
        return []
    step = (candles[1]["t"] - candles[0]["t"]) if len(candles) > 1 else 3600_000
    span = max(step, 1) * _HTF_FACTOR

    # 4× kovalara topla (OHLCV agregasyonu)
    buckets: list[dict] = []
    for c in candles:
        b = c["t"] // span
        if not buckets or buckets[-1]["b"] != b:
            buckets.append({"b": b, "end": (b + 1) * span,
                            "close": c["close"],
                            "high": c.get("high", c["close"]),
                            "low": c.get("low", c["close"]),
                            "volume": c.get("volume", 0.0)})
        else:
            cur = buckets[-1]
            cur["close"] = c["close"]
            cur["high"] = max(cur["high"], c.get("high", c["close"]))
            cur["low"] = min(cur["low"], c.get("low", c["close"]))
            cur["volume"] += c.get("volume", 0.0)

    h_closes = [x["close"] for x in buckets]
    h_highs = [x["high"] for x in buckets]
    h_lows = [x["low"] for x in buckets]
    h_vols = [x["volume"] for x in buckets]

    up_cache: dict[int, bool] = {}
    flags: list[bool] = []
    done = 0
    for c in candles:
        while done < len(buckets) and buckets[done]["end"] <= c["t"]:
            done += 1
        if done < warmup_buckets:
            flags.append(True)     # yetersiz üst-TF geçmişi: filtre pasif
            continue
        if done not in up_cache:
            t = compute_snapshot(h_closes[:done], h_highs[:done],
                                 h_lows[:done], h_vols[:done])
            up_cache[done] = t.ema_fast >= t.ema_slow
        flags.append(up_cache[done])
    return flags


def _mk_signal(base, quote, action, conf, tech) -> TradeSignal:
    return TradeSignal(chain_id=0, base=base, quote=quote, action=action,
                       confidence=conf, technical=tech, rationale="backtest",
                       source="technical")


def run_backtest(candles: list[dict], base: str, quote: str,
                 starting_cash: float, risk: RiskConfig,
                 interval: str = "1h",
                 exit_style: str = "fixed",
                 exit_cfg: ExitConfig | None = None,
                 cooldown_bars: int = 0,
                 risk_pct: float = 0.0,
                 htf_filter: str = "off",
                 allow_short: bool = False) -> dict:
    closes = [c["close"] for c in candles]
    highs = [c.get("high", c["close"]) for c in candles]
    lows = [c.get("low", c["close"]) for c in candles]
    volumes = [c.get("volume", 0.0) for c in candles]
    if len(closes) < 40:
        raise ValueError("Backtest için en az 40 mum gerekli")

    portfolio = Portfolio(starting_cash, allow_short=allow_short)
    broker = PaperBroker(portfolio, risk)
    rm = RiskManager(risk, allow_short=allow_short)
    key = f"0:{base}"

    em = ExitManager(exit_cfg) if exit_style == "atr" else None
    exit_state: ExitState | None = None
    cooldown_until = -1          # bu bar indeksinden önce yeni giriş yok
    exit_counts: dict[str, int] = {}   # çıkış gerekçesi -> adet (teşhis)

    # HTF trend filtresi: üst-TF (4×) EMA trendi aşağıyken yeni BUY engellenir;
    # allow_short'ta ayna: üst-TF YUKARIYKEN yeni SHORT engellenir.
    htf_up = htf_up_flags(candles) if htf_filter == "ema" else None
    htf_blocked = 0

    equity_curve: list[dict] = []
    trades: list[TradeOrder] = []
    trade_pnls: list[float] = []  # kapanan işlemlerin gerçekleşen PnL'leri

    def _exit_trade(pos: Position, fraction: float, price: float,
                    reason: str) -> None:
        """Pozisyonu (kısmen) kapat: long→SELL, short→BUY (cover)."""
        amount = abs(pos.amount) * fraction
        side = "SELL" if pos.amount > 0 else "BUY"
        order = TradeOrder(mode="paper", chain_id=0, dex="backtest",
                           base=base, quote=quote, side=side,
                           amount=amount, price=price, reason=reason)
        before = portfolio.realized_pnl_usd
        broker.execute(order)
        trades.append(order)
        trade_pnls.append(portfolio.realized_pnl_usd - before)
        exit_counts[reason] = exit_counts.get(reason, 0) + 1

    def _entry_size(size: float, price: float, atr: float) -> float:
        """Volatilite-uyarlı boyut TAVANI (yalnızca kısar; iki yön için aynı)."""
        if risk_pct > 0 and atr > 0:
            mult = (exit_cfg or ExitConfig()).atr_stop_mult if em else 2.0
            cap = atr_based_size(portfolio.equity_usd(), risk_pct,
                                 price, atr, atr_mult=mult)
            if cap > 0:
                size = min(size, cap)
        return size

    warmup = 30
    for i in range(warmup, len(closes)):
        window = closes[: i + 1]
        price = closes[i]
        tech = compute_snapshot(window, highs[: i + 1], lows[: i + 1], volumes[: i + 1])
        action, conf = _rule_decision(tech)

        portfolio.mark({key: price})
        pos = portfolio.positions.get(key)

        # ---- 1) Çıkış yönetimi (mevcut pozisyon, iki yön) ----
        exited_this_bar = False
        if pos is not None and pos.amount != 0:
            if em is not None and exit_state is not None and exit_state.atr > 0:
                d = em.update(exit_state, price)
                if d.action == "EXIT":
                    _exit_trade(pos, 1.0, price, d.reason)
                    exit_state = None
                    cooldown_until = i + cooldown_bars
                    exited_this_bar = True
                elif d.action == "PARTIAL":
                    _exit_trade(pos, d.fraction, price, d.reason)
                    exited_this_bar = True
                else:
                    # Emniyet freni: ATR stop ne derse desin sabit felaket
                    # stop'u bağımsız çalışır (canlı akışla birebir; yön-farkında).
                    fb = rm.check_stop_take(pos, price)
                    if fb == "stop-loss":
                        _exit_trade(pos, 1.0, price, fb)
                        exit_state = None
                        cooldown_until = i + cooldown_bars
                        exited_this_bar = True
            else:
                hit = rm.check_stop_take(pos, price)
                if hit:
                    _exit_trade(pos, 1.0, price, hit)
                    exit_state = None
                    cooldown_until = i + cooldown_bars
                    exited_this_bar = True

        # ---- 2) Sinyal işlemi ----
        if exited_this_bar or action == "HOLD" or conf < risk.min_confidence:
            equity_curve.append({"t": candles[i]["t"],
                                 "equity": portfolio.equity_usd()})
            continue

        cur = portfolio.positions.get(key)
        opening_long = action == "BUY" and (cur is None or cur.amount >= 0)
        # Short YALNIZ düz (flat) durumda açılır — piramitleme yok: SELL
        # sinyali düşüşte barlarca sürer; her barda ekleme istif oluşturur ve
        # tek bir ayı rallisi tüm istifi trailing-stop'la süpürür. Ek koruma:
        # aşırı-satım bölgesine (RSI<=35) short atılmaz — dip/sıçrama riski.
        opening_short = (action == "SELL" and allow_short and cur is None
                         and tech.rsi > 35.0)

        # Cooldown: kapanış sonrası yeni GİRİŞ yok (iki yön); kapanışlar serbest.
        if (opening_long or opening_short) and i < cooldown_until:
            equity_curve.append({"t": candles[i]["t"],
                                 "equity": portfolio.equity_usd()})
            continue
        # HTF filtresi: long girişleri üst-TF aşağıyken, short girişleri
        # üst-TF yukarıyken engellenir (kapanışlar etkilenmez).
        if htf_up is not None and ((opening_long and not htf_up[i])
                                   or (opening_short and htf_up[i])):
            htf_blocked += 1
            equity_curve.append({"t": candles[i]["t"],
                                 "equity": portfolio.equity_usd()})
            continue

        decision = rm.evaluate(_mk_signal(base, quote, action, conf, tech),
                               portfolio.positions, portfolio.cash_usd)
        if decision.approved:
            if action == "BUY":
                if cur is not None and cur.amount < 0:
                    # sinyal-kaynaklı short kapanışı (cover)
                    _exit_trade(cur, 1.0, price, "sinyal")
                    exit_state = None
                    cooldown_until = i + cooldown_bars
                else:
                    size = _entry_size(decision.size_usd, price, tech.atr)
                    if size >= 10:
                        order = TradeOrder(mode="paper", chain_id=0,
                                           dex="backtest", base=base,
                                           quote=quote, side="BUY",
                                           amount=size / price, price=price)
                        broker.execute(order)
                        trades.append(order)
                        cur = portfolio.positions.get(key)
                        if em is not None and cur is not None and tech.atr > 0:
                            if exit_state is None:
                                exit_state = ExitState(entry=cur.avg_entry,
                                                       atr=tech.atr)
                            else:  # pozisyona ekleme: girişi/ATR'yi tazele
                                exit_state.entry = cur.avg_entry
                                exit_state.atr = tech.atr
            else:  # SELL
                if cur is not None and cur.amount > 0:
                    # sinyal-kaynaklı long kapanışı
                    _exit_trade(cur, 1.0, price, "sinyal")
                    exit_state = None
                    cooldown_until = i + cooldown_bars
                elif opening_short:
                    size = _entry_size(decision.size_usd, price, tech.atr)
                    if size >= 10:
                        order = TradeOrder(mode="paper", chain_id=0,
                                           dex="backtest", base=base,
                                           quote=quote, side="SELL",
                                           amount=size / price, price=price)
                        broker.execute(order)
                        trades.append(order)
                        cur = portfolio.positions.get(key)
                        if em is not None and cur is not None and tech.atr > 0:
                            if exit_state is None or exit_state.side != "short":
                                exit_state = ExitState(entry=cur.avg_entry,
                                                       atr=tech.atr,
                                                       side="short")
                            else:  # short'a ekleme: girişi/ATR'yi tazele
                                exit_state.entry = cur.avg_entry
                                exit_state.atr = tech.atr

        equity_curve.append({"t": candles[i]["t"], "equity": portfolio.equity_usd()})

    eqs = [starting_cash] + [e["equity"] for e in equity_curve]
    ppy = _PERIODS_PER_YEAR.get(interval, 8760)
    summary = _metrics.summarize(eqs, trade_pnls=trade_pnls, periods_per_year=ppy)

    return {
        "trades": [t.to_dict() for t in trades],
        "equity_curve": equity_curve,
        "total_return_pct": summary["total_return_pct"],
        "max_drawdown_pct": summary["max_drawdown_pct"],
        "win_rate": summary.get("win_rate", 0.0),
        "sharpe": summary["sharpe"],
        "sortino": summary["sortino"],
        "calmar": summary["calmar"],
        "profit_factor": summary.get("profit_factor", 0.0),
        "expectancy_usd": summary.get("expectancy_usd", 0.0),
        "num_closed_trades": summary.get("trades", 0),
        "final_equity_usd": summary["final_equity_usd"],
        "exit_breakdown": exit_counts,
        "exit_style": exit_style,
        "htf_blocked": htf_blocked,
        "allow_short": allow_short,
    }
