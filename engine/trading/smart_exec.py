"""Akıllı yürütme + portföy-riski karar yolu yardımcısı.

İki mevcut modülü (dex.execution + risk.portfolio_risk) tek bir çağrıyla
karar/backtest yoluna bağlar:
  - EN İYİ ROTA: derinlik-tabanlı slippage + ücret + gas dahil etkin maliyeti
    en düşük DEX'i seçer (yalnızca en likit DEX'i körlemesine almaz).
  - BOYUT ÖLÇEKLEME: portföy drawdown'una göre pozisyonu küçültür (de-risk).
  - TWAP PLANI: büyük emir için parça planı önerir (fiyat etkisini azaltır).

Tamamen additif ve fail-safe: hata/eksik veri durumunda makul varsayılana döner.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.dex import execution as ex
from engine.risk import portfolio_risk as pr


@dataclass
class ExecPlan:
    dex: str
    price: float
    size_usd: float            # drawdown ölçeklemesinden SONRA
    est_cost_usd: float        # seçilen rotanın etkin maliyeti
    slices: list[float]        # TWAP parça planı (USD)
    derisk_factor: float       # 1.0 = tam boyut, <1 = küçültüldü
    note: str


def _quotes_from_candidates(candidates: list) -> list[ex.Quote]:
    out = []
    for q in candidates:
        out.append(ex.Quote(
            dex=getattr(q, "dex", "?"),
            chain_id=getattr(q, "chain_id", 0),
            price=getattr(q, "price", 0.0),
            liquidity_usd=getattr(q, "liquidity_usd", 0.0) or 0.0,
        ))
    return out


def plan_execution(candidates: list, base_size_usd: float, side: str,
                   equity_usd: float, peak_equity_usd: float,
                   twap_threshold_usd: float = 5000.0,
                   twap_slices: int = 4) -> ExecPlan | None:
    """Aday DEX teklifleri + portföy durumundan bir yürütme planı üretir.

    candidates: PriceQuote benzeri (dex, chain_id, price, liquidity_usd).
    Döner None: aday yoksa.
    """
    quotes = _quotes_from_candidates(candidates)
    if not quotes:
        return None

    # 1) Drawdown'a göre boyut ölçekle
    dd_pct = 0.0
    if peak_equity_usd > 0:
        dd_pct = max(0.0, (peak_equity_usd - equity_usd) / peak_equity_usd * 100.0)
    factor = pr.drawdown_derisk_factor(dd_pct)
    size = base_size_usd * factor

    # 2) Etkin maliyeti en düşük rotayı seç (slippage+ücret+gas)
    try:
        best, cost = ex.best_route(quotes, max(size, 1.0), side)
    except ValueError:
        return None

    # 3) Büyük emir için TWAP parça planı
    if size >= twap_threshold_usd:
        slices = ex.twap_slices(size, twap_slices)
    else:
        slices = [size]

    note = (f"rota={best.dex} maliyet≈${cost:,.2f}"
            + (f" · drawdown %{dd_pct:.1f} → boyut x{factor:.2f}" if factor < 1.0 else "")
            + (f" · TWAP {len(slices)} parça" if len(slices) > 1 else ""))
    return ExecPlan(dex=best.dex, price=best.price, size_usd=size,
                    est_cost_usd=cost, slices=slices, derisk_factor=factor,
                    note=note)
