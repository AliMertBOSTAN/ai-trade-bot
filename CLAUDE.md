# CLAUDE.md

Bu dosya, bu depoda çalışan Claude (ve diğer AI asistanları) için rehberdir.

## Proje Özeti

AI destekli çoklu-zincir DEX trade botu. Üç dil, tek ürün:

- **Python (`engine/`)** — çekirdek motor: zincir okuma, fiyatlama, sinyal, strateji,
  risk, paper/live broker, SQLite, FastAPI+WebSocket sunucu (port **8787**).
- **TypeScript (`src/`)** — Electron/React masaüstü arayüzü (`src/renderer/`),
  Flashbots MEV-korumalı keeper (`src/core/keeper/flashbotsKeeper.ts`).
- **Solidity (`contracts/ArbExecutor.sol`)** — atomik arbitraj, revert-on-no-profit.

Kapsam: Ethereum, Arbitrum, Base, Optimism, BNB, Polygon · Uniswap v2/v3,
PancakeSwap, QuickSwap · paper↔live mod · hibrit sinyal (teknik + haber + LLM + ML).

## Komutlar

```bash
# Python motoru (önce: pip install -e . veya requirements)
uvicorn engine.app:app --port 8787        # API + WS sunucu
python -m engine.backtest.run_live_backtest --symbol BTCUSDT   # gerçek veriyle backtest

# Testler
pytest tests/ -q                          # Python testleri
npm run typecheck                         # tsc --strict (web + node)
npm test                                  # vitest
npm run dev                               # Electron arayüz (engine ayrı çalışmalı)
```

`.env` ile yapılandırma: `TRADING_MODE`, `MIN_CONFIDENCE`, `STRATEGIES`,
`RPC_*`, `LLM_PROVIDER`, `PAPER_SEED_USD`… Tam liste: `engine/config/settings.py`.
Kalıcı veri `data/` altında: `trades.db`, `state.json`, `strategies.json`, `chains.json`.

## Mimari — veri akışı

```
orchestrator._tick (engine/bot/orchestrator.py)  ← ana döngü, her POLL_INTERVAL_MS
 1. fetch_all_prices → DEX fiyatları; watchlist tokenları Binance'ten beslenir
 2. generate_signal (engine/signals/engine.py) → hibrit TradeSignal (teknik+haber+LLM+ML)
 3. Rejim tespiti (engine/strategy/regime.py) → trend_up | trend_down | range
 4. StrategyManager.evaluate → her etkin strateji kendi sermaye dilimiyle karar üretir
 5. Rejime UYAN stratejilerin kararları RiskManager kapılarından geçer → Executor
 6. Stop-loss/take-profit kontrolü, arbitraj taraması, DB kaydı, WS event yayını
```

- **Sinyal motoru** (`engine/signals/engine.py`): `_rule_decision` çok-göstergeli
  kural skoru üretir; LLM/ML/haber/MTF katmanları güveni modüle eder.
- **Strateji çatısı** (`engine/strategy/`): `registry` ad→sınıf kaydı,
  `manager.StrategyManager` ağırlıklı sermaye tahsisi, `router.select_active`
  rejim filtresi, `strategies/` somut stratejiler (trend, mean_reversion,
  breakout, hybrid, funding_arb, momentum, pullback, squeeze, sentiment).
  Genel profiller: `STRATEGY_PRESETS` (orchestrator.py) — safe/balanced/aggressive.
  Kullanıcı yapılandırması `data/strategies.json`
  dosyasında kalıcıdır; API: `GET /strategies`, `POST /strategies/config`.
- **Risk** (`engine/risk/manager.py`): kill-switch, min_confidence eşiği,
  pozisyon/gas limitleri. UI'daki işlem eşiği backend `/config` → `risk.min_confidence`
  değerinden okunur — **frontend'e sabit eşik yazma**.
- **UI köprüsü**: renderer `src/renderer/src/api.ts` üzerinden REST + `/ws`
  WebSocket. Tip eşlemesi `src/shared/types.ts` (+ `types.gen.ts`).

## Kurallar / Gelenekler

- Yorumlar ve kullanıcıya görünen metinler **Türkçe**; tanımlayıcılar İngilizce.
- Python 3.11+, dataclass ağırlıklı, `from __future__ import annotations`.
- TS strict açık; `npm run typecheck` temiz kalmalı. Solidity 0.8.26, 0 uyarı hedefi.
- Sessiz başarısızlık yok: risk retleri gerekçeli döner, config hataları fail-fast
  (`settings.validate_or_raise`).
- Yeni strateji: `BaseStrategy`'den türet → modülde `register(...)` →
  `strategies/__init__.py` içine import → `STRATEGY_INFO`'ya (manager.py) açıklama ekle.
- Live moda etki eden değişikliklerde temkinli ol: gas tavanı, harcama limiti,
  Flashbots yolu ve kill-switch akışlarını bozma; önce paper modda doğrula.
- Değişiklik sonrası asgari doğrulama: `pytest -q` + `npm run typecheck`.

## Bilinen tuzaklar

- `_maybe_trade` pozisyonları `chain:base` anahtarıyla tutar — stratejiler aynı
  tokenda ortak pozisyonu paylaşır (strateji-başına ayrı pozisyon defteri yok).
- Watchlist tokenları RPC olmadan da (Binance klines/ticker) sinyal üretir;
  DEX fiyatı yoksa işlem yine de paper broker'da simüle edilir.
- `engine/signals/engine.py` modül-seviyesi durum tutar (`_llm_last`, `_ml_model`) —
  testlerde sızıntıya dikkat.
