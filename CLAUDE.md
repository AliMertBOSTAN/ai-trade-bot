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
python -m engine.backtest.run_live_backtest --symbol BTCUSDT --interval 4h --compare
python scripts/live_preflight.py --chain 8453   # canlıya geçiş ön-uçuş kontrolü
#   --compare: aynı veride fixed (eski) vs atr (canlı-eşdeğer: trailing+cooldown+
#   risk_pct boyut). Parametre seçimi: walk_forward(param_grid=...) —
#   bulgular ve öneriler: docs/BACKTEST_IMPROVEMENTS.md

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

Girişte İKİ ek fren vardır (ikisi de yalnızca ALIMI etkiler, çıkışa dokunmaz):
 • `news_watcher.guard()` — güçlü negatif son-dakika haberi
 • `calendar.guard()` — yüksek etkili veri yayını penceresi (CPI/NFP/FOMC)
   `calendar.size_factor()` orta etkili olayda pozisyonu küçültür.
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

## Canlı mod (live) kapıları

- `set_mode("live")` önce `live_preflight()` çalıştırır; `ready=False` ise mod
  DEĞİŞMEZ (`LIVE_FORCE=1` zorlar). Kontroller: imzalayıcı · RPC · fonlanmış
  zincir · gerçek DEX rota testi (`quote_probe`) · **kanıt kapısı** · LLM ·
  kill-switch · günlük harcama limiti.
- **Kanıt kapısı** (`engine/trading/live_gate.py`): bot paper/shadow modda
  `LIVE_GATE_MIN_TRADES` (30) kapanan işlem, PF ≥ 1.2, net PnL > 0 ve
  maxDD ≤ %15 göstermeden canlıya geçemez. Ölçümler: `docs/LIVE_READINESS.md`.
- `LiveBroker` broker seviyesinde de korur: nosyonel tavanı, gas/nosyonel
  oranı, EIP-1559 `maxFeePerGas` + `max_gas_gwei` sert tavanı.

## Takvim + otonom araştırmacı

- `engine/marketdata/calendar.py` — BLS ICS (TÜFE/ÜFE/NFP) + statik FOMC +
  haberden çıkarılan kripto olayları. Anahtarsız, fail-safe, `data/` önbellekli.
- `engine/marketdata/researcher.py` — arka planda 30 dk'da bir takvimi tazeler,
  yaklaşan olaylar için ÖNCEDEN araştırma notu (LLM + haber + piyasa bağlamı),
  olay sonrası sonuç okuması üretir. WS `research` + Telegram + `/research`.
- Uçlar: `GET /calendar`, `POST /calendar/refresh`, `GET /calendar/guard`,
  `GET /research`, `POST /research/run`, `GET /live/gate`, `GET /live/quote-probe`.

## Piyasa İstihbaratı (intel)

`engine/marketdata/intel/` — makro rejim, on-chain akış ve Hyperliquid/whale
panelleri. NinjaTools benzeri bir istihbarat katmanı; botun işlem mantığından
BAĞIMSIZ çalışır, ona yalnızca tek bir skor besler.

```
engine/marketdata/intel/
  cache.py      TTL cache + "hata olursa bayat veriyi kullan" + disk kalıcılığı
  keys.py       opsiyonel API anahtarları (CoinGlass/CMC/Nansen) tek okuma noktası
  macro.py      Yahoo(→Stooq) endeksler · alternative.me + CNN korku endeksleri
                · risk-on/off skoru · BTC-makro korelasyon
  premium.py    Coinbase primi (Coinbase vs Binance→OKX→Kraken yedekli)
  etf.py        spot ETF akışı — CoinGlass varsa dolar, yoksa Yahoo tabanlı VEKİL
  llama.py      DefiLlama: zincir ücretleri, DEX hacmi, stablecoin, yield,
                unlock (defillama-datasets), hack
  rotation.py   CoinGecko sektör rotasyonu · zincir TVL · dominans
  utxo.py       bitcoin-data.com: gerçekleşmiş fiyat, STH maliyet tabanı, MVRV
  hl.py         Hyperliquid duyarlılığı + cüzdan konumlanması
  flows.py      taker akışı, smart-money radarı, borsa rezervleri
  coinglass.py / cmc.py / nansen.py   anahtarlı adaptörler (yoksa sessizce kapalı)
  bias.py       panelleri TEK bir -1..+1 skoruna indirger  ← sinyal/risk buradan okur
  refresher.py  arka plan tazeleyici (app startup'ta başlar)
```

**İki değişmez kural:**

1. `bias.py` **asla ağ çağrısı yapmaz** — yalnızca `refresher`'ın doldurduğu
   cache'i okur. Cache boşsa (test, ağ yok, ilk açılış) sonuç NÖTR'dür ve
   mevcut davranış hiç değişmez. Tick döngüsü hiçbir zaman upstream beklemez.
2. Her panel bağımsız fail-safe: upstream düşerse `ok=False` + gerekçe döner,
   diğer paneller çalışmaya devam eder. Anahtarsız kaynaklar her zaman aktiftir.

**Sinyal & risk entegrasyonu**

- `engine/signals/engine.py` → `_intel_bias(base)`: karara TERS ve güçlü yapı
  (|skor| ≥ 0.35) güveni `_INTEL_CONFLICT_CAP` (0.55) ile tavanlar; destekleyen
  yapı +%4 bonus verir. `breakdown.intelScore/intelNote/intelComponents` UI'da
  görünür. `INTEL_SIGNAL=0` ile kapatılır.
- `engine/risk/manager.py` → `_intel_ok()`: `INTEL_BLOCK_SCORE` (varsayılan 0.6)
  eşiğinden güçlü ters yapıda YENİ pozisyon açılmaz. Pozisyon KAPATMAYI asla
  engellemez. Intel verisi yoksa kapı pasiftir.

**Uçlar:** `GET /intel/overview` (tüm paneller), `/intel/group/{macro|onchain|hl}`,
`/intel/panel/{ad}`, `/intel/sources` (hangi kaynak açık + tazelik),
`/intel/bias?symbol=`, `/intel/taker/{symbol}`, `/intel/refresh`.

**UI:** `src/renderer/src/views/IntelView.tsx` + `components/intel/`
(`common.tsx` ortak parçalar, `MacroWidgets`, `OnchainWidgets`, `FlowWidgets`).

**Canlı deneme:** `python -m scripts.intel_smoke` — hangi kaynağa erişilebildiğini
tablo halinde gösterir. Testler (`tests/test_intel.py`) ağ kullanmaz.

**Bilinen sınırlar:**
- Binance bazı ülkelerden HTTP 451 döner → taker akışı/whale vekili kapanır
  (panel gerekçeyi gösterir, bot etkilenmez).
- DefiLlama'nın `overview/derivatives` ve toplu `emissions` uçları ücretlidir;
  perp hacmi HL panelinden, unlock'lar `defillama-datasets` üzerinden gelir.
- HL genel PnL sıralaması tek istekte ~35 MB → `HL_LEADERBOARD=0` varsayılan;
  cüzdan paneli `HL_WATCH_WALLETS` ile beslenir.

## AI analist (elle + otonom)

`engine/marketdata/analyst.py` — tek sembol icin TAM gorus. Prompt artik
istihbarat katmanini da okur ve analistin dusunme sirasini dayatir:

```
1 ZEMIN    makro rejim + likidite uygun mu?     (intel: risk-on/off, DXY/VIX/faiz)
2 AKIS     ETF / stablecoin / smart-money / balina ayni yonu mu gosteriyor?
3 YAPI     teknik seviyeler, trend, momentum
4 KALABALIK funding + long/short -> asiri tek yonluyse CONTRARIAN uyari
5 KARAR    katmanlar celisiyorsa BEKLE ve celiskiyi yaz
```

Cikti zengin JSON: `bias/confidence/horizon`, `macro_view/flow_view/chart_view/
crowd_view`, `levels{support,resistance,invalidation}`, `scenarios[]`,
`conflicts[]`, `risks[]` ve somut `trade{side,entry,stop,target,leverage,
size_hint_pct}` plani.

- **Derinlik**: `ANALYST_DEPTH` veya UI segmenti — kisa(500) / normal(1200) /
  derin(2400) / cok_derin(4000) token. Eskiden sabit 600'du ve uzun gerekceler
  kesiliyordu. `analyst.depth_tokens()` sayi da kabul eder.
- **Sembol evreni**: `/analyst/universe` — Hyperliquid'in 177 perp'i + izleme
  listesi. UI'daki sabit 8 sembolluk liste kaldirildi, arama kutusu geldi.
- **Otonom** (`engine/marketdata/ai_analyst.py`): `ANALYST_AUTO=1` ile arka
  planda calisir. Periyodik tarama (`ANALYST_INTERVAL_MIN`) + olay tetikli:
  yapi skoru sicramasi (`ANALYST_BIAS_DELTA`), son-dakika haber, likidasyon
  kaskadi. Sonuclar `data/ai_reports.json` + WS `ai_analysis` olayi.

## Hyperliquid perp masasi

`engine/trading/hl_broker.py` — tek arayuz, iki mod:

- **paper**: GERCEK mark/funding/maxLeverage ile simulasyon. Defter
  `data/hl_paper.json`. Ucret (taker %0.045), kayma, funding tahakkuku,
  likidasyon kontrolu ve net-out davranisi gercek formullerle.
- **live**: `hyperliquid-python-sdk`. Imzalayici iki kaynaktan:
  `HL_API_WALLET_KEY` + `HL_ACCOUNT_ADDRESS` (agent key — PARA CEKEMEZ,
  onerilen) veya mevcut sifreli keystore. **Canli emir icin AYRICA `HL_LIVE=1`
  gerekir**; bayrak kapaliyken mod "live" secilse bile emir gitmez.

`engine/risk/hl_risk.py` — TEK kapi, elle ve AI emirleri ayni yerden gecer:
gunluk zarar kill-switch, kaldirac tavani, tek/toplam nosyonel tavani, pozisyon
sayisi, likidasyon mesafesi (kaldiraci otomatik kisar), cooldown, AI icin ayri
ve DAHA DAR tavanlar + guven esigi + intel yapi skoru kontrolu.
**Kapatma (close) hicbir kapidan engellenmez** — riski azaltmak hep serbesttir.

Uclar: `/hl/state`, `/hl/universe` (TUM evren, 24s degisimle), `/hl/limits`,
`/hl/preview` (emir GITMEDEN kapi sonucu + likidasyon fiyati), `/hl/order`,
`/hl/close`, `/hl/leverage`, `/hl/paper/reset`, `/hl/live/status`,
`/hl/health` (tek cagrida tani: engine / Hyperliquid / imzalayici).

UI kurali: **hicbir istek sessizce yutulmaz**. `HyperliquidView.explain()` ham
hatayi eyleme cevirir (404 -> "engine eski surum, uvicorn'u yeniden baslat";
fetch hatasi -> "engine calismiyor"). Piyasa listesi bos kalirsa NEDEN bos
oldugu kartin icinde yazar. Onceki surumdeki `.catch(() => {})` bu yuzden
kaldirildi — liste sessizce bosaliyor ve kullanici sembol secemiyordu.

**AI kararı** (`ai_analyst.decide()`): otopilot KAPALIYKEN BILE her taramada
uretilir ve `report["decision"]` icinde saklanir. Durum makinesi:

```
READY / ACTED       -> POZISYON AL   (kapi onayladi; ACTED = emir gonderildi)
NO_PLAN / LOW_CONF /
HEURISTIC / NO_SCAN -> BEKLE
BLOCKED / FAILED    -> GIRME
```

Kritik ayrim: **otopilot salteri EMIR GONDERMEYI kontrol eder, risk
degerlendirmesini degil.** `hl_risk.check(require_autopilot=False)` ile salter
kapaliyken de gercek kapi sonucu hesaplanir; aksi halde karar her zaman "GIRME"
gorunur ve kullanici AI'in olumsuz dusundugunu sanir. Gercek emir yolunda
`require_autopilot=True` kalir.

`last_decision(symbol)` karar kaydi yoksa kuru degerlendirmeyle ANINDA hesaplar
(eski `ai_reports.json` formatlari icin de calisir).

Uclar: `GET /analyst/decision/{symbol}` (`?refresh=1` once analiz calistirir),
`POST /analyst/decision/{symbol}/dry-run` (tavanlari degistirdikten sonra
"simdi gecer miydi" denemesi; emir GONDERMEZ).

**Kaldirac karari analistindir.** Prompt stop mesafesi / oynaklik / funding /
katman uyumu kurallariyla 1-10x arasinda sectirir ve `trade.leverage_note`
alaninda gerekcesini yazdirir. `decide()` bunu once BORSA tavaniyla, sonra
`HL_AI_MAX_LEVERAGE` ve likidasyon-mesafesi kapisiyla kirpar; karar kartinda
"4x -> 3x (kirpildi)" seklinde ikisi de gorunur. Arayuzde kaldirac icin
elle/AI modu vardir (`levMode`); AI modunda slider kilitlenir ve AI'in secimi
uygulanir.

## Arayuz yerlesimi

11 sekme tek satirda aranamaz hale gelmisti. Artik iki satir:

```
IZLE   Genel · Istihbarat · Piyasa · Kesfet · Haberler · Takvim
KARAR  Sinyaller · Stratejiler · AI Analist · Hedef & Risk
ISLEM  Hyperliquid · Arbitraj · Islemler
```

`SECTIONS` / `sectionOf` / `tabsOf` → `src/renderer/src/lib/ui.ts`. Son acik
sekme ve yogunluk tercihi localStorage'da (`atb.tab`, `atb.density`). Yogun mod
`<html data-density="compact">` uzerinden CSS'e iner.

## Bilinen tuzaklar

- `_maybe_trade` pozisyonları `chain:base` anahtarıyla tutar — stratejiler aynı
  tokenda ortak pozisyonu paylaşır (strateji-başına ayrı pozisyon defteri yok).
- Watchlist tokenları RPC olmadan da (Binance klines/ticker) sinyal üretir;
  DEX fiyatı yoksa işlem yine de paper broker'da simüle edilir.
- Sinyaller varsayılan olarak SABİT MUM KAPANIŞLARIYLA üretilir
  (`SIGNAL_ALIGN=candles`, `SIGNAL_INTERVAL=4h`, `candle_agg.CandleAggregator`)
  — 1h ölçümlerde her eşikte zarar etti, 4h pozitif: docs/LIVE_READINESS.md
  — girişler mum kapanışında, çıkış kontrolleri her tick. `SIGNAL_ALIGN=ticks`
  eski tick-karışımı davranışa döndürür (backtest ile uyumsuz; önerilmez).
- `engine/signals/engine.py` modül-seviyesi durum tutar (`_llm_last`, `_ml_model`) —
  testlerde sızıntıya dikkat.
- Intel panelleri `data/intel_cache.json` dosyasına yazar; testlerde
  `intel_cache.clear()` ile temizlenmezse bias sızabilir (fixture mevcut).
- ETF paneli anahtarsızken VEKİL'dir: yön/şiddet verir, **dolar tutarı vermez**
  (`source: "proxy"` + `disclaimer`). Bunu gerçek net akış gibi raporlama.
- HL kagit defteri (`data/hl_paper.json`) ile canli hesap AYRI defterlerdir;
  `history` ikisinde de tutulur ama `mode` alanindan ayirt edilir.
- HL cooldown pozisyon KAPATTIKTAN sonra da islerdir (revenge-trade freni).
  Rahatsiz ederse `HL_COOLDOWN_S` dusurulur.
- `analyst_router` app.py'de `/analyst/{symbol}` TANIMINDAN ONCE mount edilir;
  yer degistirirse `/analyst/depths` parametreli yola dusup 500 verir.
- HL isleм masasinda piyasa listesi `position: sticky` ve KENDI izgara satirinda
  (`.hl-top`) durur. Ayni blokta span'li kartlarla birlestirilirse kaydirirken
  onlarin uzerine biner — sticky, grid ALANINDA degil iceren BLOKTA durur.
