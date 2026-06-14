# AI Trade Bot — Çoklu-Zincir DEX Arbitraj & Sinyal Botu

EVM ağlarında (Ethereum, Arbitrum, Base, Optimism, BNB Chain, Polygon) çalışan,
Uniswap / PancakeSwap / QuickSwap gibi borsalardaki fiyatları okuyan, hibrit
(teknik + LLM) sinyal üreten, paper ↔ live mod geçişli, masaüstü arayüzlü bir
trade botu.

> ⚠️ **Finansal risk uyarısı.** Bu yazılım eğitim/araştırma amaçlıdır, finansal
> tavsiye değildir. `live` mod gerçek para harcar. Önce uzun süre `paper` modda
> ve testnet'te çalıştırın. Kullandığınız cüzdanın anahtarını asla ana
> cüzdanınızdan vermeyin; küçük bakiyeli, izole bir "hot wallet" kullanın.

---

## Mimari — neden iki dil?

```
┌────────────────────────────┐         REST + WebSocket          ┌──────────────────────────────┐
│  Electron + TypeScript      │  ◀──────────────────────────────▶ │  Python engine (web3.py)       │
│  (arayüz / keeper)          │        http://127.0.0.1:8787       │  (on-chain + AI + execution)   │
│                             │                                    │                                │
│  • React dashboard          │                                    │  • Çoklu-zincir provider        │
│  • Ethers.js keeper         │                                    │  • Uniswap v2/v3 quote          │
│    (Flashbots MEV koruması) │                                    │  • Arbitraj tarayıcı            │
│  • mod switch / kontrol      │                                    │  • Teknik indikatör + LLM       │
└────────────────────────────┘                                    │  • Risk manager (slippage/gas)  │
                                                                   │  • Paper + Live broker          │
        ┌──────────────────────┐                                  │  • SQLite + backtest            │
        │ Solidity ArbExecutor │  ◀── Ethers.js keeper deploy/çağrı│  • FastAPI + WS sunucu          │
        │ (atomik arbitraj)    │                                  └──────────────────────────────┘
        └──────────────────────┘
```

- **Python (`web3.py`)** ağır işi yapar: zincir okuma, fiyatlama, arbitraj,
  indikatörler, AI sinyal, risk kapıları, işlem yürütme, kalıcı depolama.
- **TypeScript (`Ethers.js`)** masaüstü arayüzü ve **keeper**'ı sağlar: arbitraj
  işlemlerini `ArbExecutor` kontratına **MEV-korumalı (Flashbots Protect)** gönderir.
- **Solidity** atomik arbitrajı zincir üzerinde garanti eder (kâr yoksa revert).

---

## Kurulum

### 1) Python engine

```bash
cd engine
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env        # .env doldurun (RPC, LLM, cüzdan)
uvicorn engine.app:app --port 8787
```

### 2) Electron arayüz

```bash
npm install
npm run dev          # arayüz açılır, 127.0.0.1:8787'e bağlanır
```

Arayüzü açtıktan sonra **Paper/Live** geçişi ve **Başlat/Durdur** üst bardadır.

Electron, Python engine'ini (uvicorn :8787) **uygulamayla birlikte otomatik
başlatır ve kapanışta durdurur** (varsayılan açık). Python'u `.venv` varsa
ondan, yoksa sistem `python`'ından çalıştırır; özel yorumlayıcı için
`ENGINE_PYTHON` ortam değişkenini ayarlayın. Zaten elle başlatılmış bir engine
(port 8787) varsa ona dokunmaz. Otomatik başlatmayı kapatmak için
`AUTO_START_ENGINE=0`. Bu durumda engine'i ayrıca `uvicorn engine.app:app
--port 8787` ile elle başlatabilir veya arayüzdeki IPC köprüsünü kullanabilirsiniz.

### 3) Backtest

**Gerçek geçmiş veriyle** (Binance/CoinGecko'dan otomatik mum çeker, ek bağımlılık yok):

```bash
cd engine && source .venv/bin/activate
python -m engine.backtest.run_live_backtest --symbol ETHUSDT --interval 1h --limit 500
python -m engine.backtest.run_live_backtest --symbol BTCUSDT --interval 4h --limit 700 --cash 25000
python -m engine.backtest.run_live_backtest --symbol WETH --source coingecko --days 90 --save eth.json
```

Çıktı: toplam getiri, al-tut karşılaştırması, maks. düşüş, Sharpe, kazanma oranı.
`--save` ile equity eğrisi + işlemler JSON'a yazılır.

Kendi mum verinizle programatik olarak:

```python
from engine.backtest.backtester import run_backtest
from engine.config.settings import RiskConfig
print(run_backtest(candles, "WETH", "USDC", 10000.0, RiskConfig()))
```

### 4) Kontrat (opsiyonel, live arbitraj için)

`contracts/ArbExecutor.sol` — Foundry/Hardhat ile derleyip deploy edin, adresini
TS keeper config'ine verin.

---

## Doğrulama (bu repoda yapıldı)

| Katman | Kontrol | Sonuç |
| --- | --- | --- |
| Python engine | `py_compile` tüm modüller | ✅ |
| Python logic | sentetik veriyle backtest + arbitraj + sinyal | ✅ (return +3.3%, Sharpe 1.36) |
| TypeScript | `tsc --strict` (React/ethers/electron/chart.js dahil) | ✅ |
| Solidity | `solc 0.8.26` derleme | ✅ 0 uyarı |

---

## Açık piyasa verisi + haber + LLM analist

Bot, kendi zincir-üstü fiyatlamasına ek olarak herkese açık verileri okur
(API key gerektirmez) ve LLM ile karşılaştırmalı yorum üretir:

- **Binance public REST** — 24s ticker, OHLCV, emir defteri, son işlemler (`engine/marketdata/binance.py`)
- **DexScreener** — Uniswap v2/v3, PancakeSwap, QuickSwap havuz fiyat/likidite/hacim verisi; bilinen tokenlarda adres-tabanlı sorgu (`engine/marketdata/dexscreener.py`)
- **CEX/DEX karşılaştırma** — aynı varlık için Binance vs Uniswap fiyatı, spread (bps), likidite bağlamı (`engine/marketdata/aggregator.py`)
- **Anlık haberler** — CoinDesk/Cointelegraph/Decrypt/The Defiant RSS; `.env > NEWS_FEEDS` ile özelleştirilebilir (`engine/marketdata/news.py`)
- **LLM piyasa analisti** — piyasa verisi + haberleri LLM'e verip yapılandırılmış yorum alır: sentiment, CEX/DEX uyum yorumu, haber etkisi, riskler (`engine/marketdata/analyst.py`). LLM key'i `.env`'den okunur (`LLM_PROVIDER` + `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`); key yoksa yalnızca sayısal rapor döner (fail-safe).

REST endpoint'leri (sunucu: `uvicorn engine.app:app --port 8787`):

```
GET /marketdata/ETH        # CEX+DEX karşılaştırmalı anlık veri
GET /marketdata?symbols=ETH,BTC,ARB
GET /news?limit=20&q=bitcoin
GET /analyst/ETH           # LLM karşılaştırmalı piyasa yorumu
```

## Risk Controls (özet)

| Önlem | Nerede | Açıklama |
| --- | --- | --- |
| Slippage tavanı | `risk/manager.py` `min_out()` + kontrat | `amountOutMinimum`; aşılırsa revert |
| Gas tavanı | `manager.gas_ok()` + keeper | gwei tavanı aşılırsa işlem atlanır |
| Revert-on-no-profit | `ArbExecutor.sol` | net kâr < eşik ise tüm tx geri alınır |
| MEV (sandwich) koruması | `flashbotsKeeper.ts` | tx private relay (Flashbots Protect) ile gider |
| Günlük zarar kill-switch | `manager.kill_switch_triggered()` | limit aşılınca işlem durur |
| Pozisyon limiti | `manager.evaluate()` | max notional & max açık pozisyon |
| Stop-loss / take-profit | `manager.check_stop_take()` | otomatik pozisyon kapama |
| Fail-safe live geçiş | `executor.set_mode()` | anahtar yoksa live'a geçilemez |

Detaylı gerekçe için **`docs/PROJECT_WRITEUP.md`** dosyasına bakın.

---

## Dizin yapısı

```
ai-trade-bot/
├── engine/              # Python (web3.py) çekirdek motor + FastAPI
│   ├── config/          # ayarlar + zincir/DEX/token tanımları
│   ├── web3x/           # provider yöneticisi
│   ├── dex/             # uniswap v2/v3 fiyat okuyucu + ABI'ler
│   ├── arbitrage/       # çoklu-zincir arbitraj tarayıcı
│   ├── indicators/      # RSI/EMA/MACD/momentum
│   ├── signals/         # hibrit sinyal motoru + LLM danışman
│   ├── risk/            # risk yönetimi (slippage/gas/kill-switch)
│   ├── trading/         # portföy + paper/live broker + mod switch
│   ├── backtest/        # backtester
│   ├── storage/         # SQLite
│   └── app.py           # FastAPI + WebSocket
├── contracts/
│   └── ArbExecutor.sol  # atomik arbitraj (revert-on-no-profit)
├── src/                 # Electron + TypeScript
│   ├── main/            # main process (+ engine spawn)
│   ├── preload/         # IPC köprüsü
│   ├── core/            # apiClient + Ethers.js Flashbots keeper
│   ├── renderer/        # React dashboard
│   └── shared/types.ts  # ortak tip sözleşmesi
└── docs/PROJECT_WRITEUP.md
```

## Lisans
MIT
