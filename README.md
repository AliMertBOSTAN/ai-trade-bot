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
- **LLM piyasa analisti** — piyasa verisi + haberleri LLM'e verip yapılandırılmış yorum alır: sentiment, CEX/DEX uyum yorumu, haber etkisi, riskler (`engine/marketdata/analyst.py`). LLM key'i `.env`'den okunur (`LLM_PROVIDER` + `DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`); key yoksa yalnızca sayısal rapor döner (fail-safe).

### LLM sağlayıcı: DeepSeek (varsayılan)

`.env` içinde:

```
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat        # opsiyonel; "deepseek-reasoner" de seçilebilir
DEEPSEEK_BASE_URL=https://api.deepseek.com  # opsiyonel
```

DeepSeek API'si OpenAI uyumludur; mevcut `openai` paketi `base_url` ile çağrılır
(ek bağımlılık yok). Anahtarı [platform.deepseek.com](https://platform.deepseek.com)
adresinden alabilirsiniz. `LLM_PROVIDER=anthropic` veya `openai` ile diğerlerine
geçebilir, `none` ile LLM katmanını tamamen kapatabilirsiniz (bot teknik karara
düşer — fail-safe).

### Kaldığı yerden devam (snapshot kalıcılığı)

Bot her trade, mod değişimi ve start/stop sonrası **portföy + mod + çalışma
durumunu** `data/state.json` dosyasına yazar (atomik yazım). Engine yeniden
başladığında:

- `state.json` varsa: portföy (nakit, pozisyonlar, realized PnL) ve mod
  geri yüklenir; `was_running=true` ise bot otomatik başlatılır.
- `state.json` yoksa: `.env` defaultlarıyla sıfırdan başlanır.

`state.json` git-friendly metin dosyasıdır. Başka cihazdan kaldığı yerden devam
etmek için:

```bash
# 1. cihaz
git add data/state.json
git commit -m "trade state snapshot"
git push

# 2. cihaz
git pull
uvicorn engine.app:app --port 8787   # snapshot otomatik yüklenir + auto-resume
```

`data/bot.db` (detaylı trade/sinyal/equity geçmişi) `.gitignore`'a alınmıştır;
push edilmez. Yalnızca devam için gerekli minimum durum `state.json`'dadır.
Veri klasörünü taşımak için `DATA_DIR=/path/to/dir` env değişkenini kullanın.

REST endpoint'leri (sunucu: `uvicorn engine.app:app --port 8787`):

```
GET /marketdata/ETH        # CEX+DEX karşılaştırmalı anlık veri
GET /marketdata?symbols=ETH,BTC,ARB
GET /news?limit=20&q=bitcoin
GET /analyst/ETH           # LLM karşılaştırmalı piyasa yorumu
```

## Piyasa İstihbaratı paneli

Electron arayüzündeki **Piyasa İstihbaratı** sekmesi 20 paneli tek ekranda
toplar — üç grup halinde:

| Grup | Paneller | Kaynak |
|---|---|---|
| **Makro & Duyarlılık** | Risk-On/Off skoru, Kripto + ABD Korku&Açgözlülük, makro zemin şeridi (SPX/NDX/DJI/VIX/DXY/ABD10Y/altın/gümüş/WTI/IBIT/MSTR), Coinbase primi, spot ETF akışı, BTC-makro korelasyon | Yahoo Finance, alternative.me, CNN, Coinbase, Binance/OKX/Kraken |
| **On-chain & Akışlar** | Stablecoin likiditesi (+zincir kırılımı), sektör rotasyonu, zincir komisyonları & DEX hacmi, BTC maliyet tabanı (MVRV), zincir TVL & dominans, token unlock takvimi, DeFi getirileri, son exploit'ler | DefiLlama, CoinGecko, bitcoin-data.com |
| **Hyperliquid & Whale** | HL perp duyarlılığı (OI ağırlıklı funding, genişlik), cüzdan konumlanması, smart-money radarı, borsa rezervleri | Hyperliquid public API, Binance orderflow |

Hepsi **anahtarsız** çalışır. `.env`'e `COINGLASS_API_KEY` / `CMC_API_KEY` /
`NANSEN_API_KEY` eklenirse ilgili paneller gerçek (vekil olmayan) veriye geçer;
eklenmezse panel bunu açıkça yazar. Ayrıntılı liste: `.env.example`.

Panellerin birleşik **yapı skoru** (-1..+1) sinyal motoruna girer: karara ters
ve güçlüyse güven tavanlanır, destekliyorsa küçük bonus verilir; `INTEL_BLOCK_SCORE`
eşiğini aşan ters yapıda yeni pozisyon açılmaz (kapanışa dokunmaz).
Sadece görsel istiyorsan `INTEL_SIGNAL=0`.

```bash
python -m scripts.intel_smoke          # hangi kaynak erişilebilir, tablo halinde
curl localhost:8787/intel/overview     # tüm paneller tek JSON
curl localhost:8787/intel/sources      # açık/kapalı sağlayıcılar + veri tazeliği
```

## Hyperliquid kaldıraçlı işlem masası

**İşlem → Hyperliquid** sekmesi: hem sen hem AI aynı masadan işlem yapar.

- **Kağıt mod (varsayılan)** — gerçek mark fiyatı, gerçek funding ve gerçek
  azami kaldıraçla simülasyon. Ücret, kayma, funding tahakkuku, likidasyon
  kontrolü hepsi işler. Anahtar gerekmez.
- **Canlı mod** — iki şart birden: imzalayıcı *ve* `HL_LIVE=1`.
  İmzalayıcı için önerilen yol Hyperliquid'in **API Wallet**'ı: sadece işlem
  yetkisi olan, para çekemeyen ayrı bir anahtar. Alternatif olarak projedeki
  şifreli keystore kullanılır. Anahtarı yalnızca sen `.env`'e yazarsın.

Solda **aranabilir piyasa listesi** var: Hyperliquid'in tüm perp evreni (~177
sembol) fiyat, 24s değişim, saatlik funding, 24s hacim ve azami kaldıraçla
listelenir; hacme/değişime/funding'e/OI'ye göre sıralanır, bir satıra tıklamak
emir formunu o piyasaya geçirir. Sağda seçili piyasanın künyesi ve emir formu.

Emir göndermeden önce **önizleme** çıkar: kapının kararı, kırpılan kaldıraç/
nosyonel, gereken teminat, likidasyon fiyatı ve saatlik funding. Kapı
reddederse sebep formun üstünde kırmızı olarak yazılır ve gönder düğmesi kapanır.

Bir şey görünmüyorsa tek çağrıda tanı: `curl localhost:8787/hl/health` — engine
ayakta mı, Hyperliquid erişilebilir mi, kaç piyasa var, imzalayıcı hazır mı.
Arayüz de aynı hatayı okunur hâle çevirir ("engine çalışmıyor", "eski sürüm —
uvicorn'u yeniden başlat").

### Risk kapıları — elle ve AI emirleri aynı yerden geçer

| Kapı | .env | Varsayılan |
|---|---|---|
| Kaldıraç tavanı | `HL_MAX_LEVERAGE` | 5× |
| Tek pozisyon nosyoneli | `HL_MAX_NOTIONAL_USD` | 500$ |
| Toplam maruziyet | `HL_MAX_TOTAL_NOTIONAL` | 1500$ |
| Eşzamanlı pozisyon | `HL_MAX_POSITIONS` | 3 |
| Günlük zarar kill-switch | `HL_MAX_DAILY_LOSS_USD` | 100$ |
| Likidasyona asgari mesafe | `HL_MIN_LIQ_DISTANCE` | %12 |
| Aynı sembolde bekleme | `HL_COOLDOWN_S` | 300 sn |

Pozisyon **kapatma** hiçbir kapıdan engellenmez — kill-switch bile pozisyondan
çıkmayı yasaklamaz.

### AI kararı — POZİSYON AL / BEKLE / GİRME

İşlem sekmesindeki **AI Kararı** kartı, seçili pair için analistin ne
düşündüğünü otopilot kapalıyken de gösterir. Üç sonuçtan biri çıkar:

| Karar | Ne demek |
|---|---|
| **POZİSYON AL** | Analist yön verdi, güven eşiği geçildi ve risk kapısı onayladı. Otopilot kapalıysa emir gönderilmez — planı tek tıkla emir formuna aktarıp elle açarsın. |
| **BEKLE** | Yön yok, güven düşük, LLM kapalı ya da bu pair hiç taranmadı. |
| **GİRME** | Risk kapısı durdurdu (kill-switch, tavan, likidasyon mesafesi, cooldown, yapı skoru çelişkisi) — sebep kartta yazar. |

Kart ayrıca AI'ın seçtiği kaldıracı, kırpılmış hâlini, nosyoneli, giriş/stop/
hedef seviyelerini ve kaldıraç gerekçesini gösterir. "Kapıyı dene" düğmesi
`.env` tavanlarını değiştirdikten sonra emir göndermeden yeniden değerlendirir.

**Kaldıraç kararı artık analistin.** Prompt onu stop mesafesine, oynaklığa,
funding yönüne ve katman uyumuna göre 1–10× arasında seçmeye ve gerekçesini
yazmaya zorluyor; sonra borsa tavanı ve senin risk tavanların kırpıyor. Emir
formunda kaldıraç için **Elle / AI** modu var — AI modunda slider kilitlenir ve
analistin seçimi uygulanır.

`HL_AI_AUTOPILOT=1` yaparsan aynı plan onay istemeden uygulanır. AI'ın tavanları
seninkilerden **dar**dır (`HL_AI_MAX_NOTIONAL_USD`, `HL_AI_MAX_LEVERAGE`,
`HL_AI_MIN_CONFIDENCE`) ve LLM kapalıyken hiçbir işlem açılmaz.

> Kaldıraçlı işlem sermayenin tamamını kaybettirebilir. Canlıya geçmeden önce
> kağıt modda ölç, sonra `HL_TESTNET=1` ile dene, en son `HL_LIVE=1` yap.

## AI analist

**Karar → AI Analist** sekmesi. Üç yenilik:

1. **Geniş sembol evreni** — arama kutusundan Hyperliquid'in 177 perp'i ve
   izleme listesi. (Eskiden 8 sembole sabitti.)
2. **Analiz derinliği** — Kısa / Normal / Derin / Çok derin. Bu, LLM'in
   üretebileceği token bütçesidir (500 → 4000); eskiden sabit 600 olduğu için
   uzun gerekçeler kesiliyordu.
3. **İstihbarat-farkında prompt** — analist artık makro rejimi, risk-on/off
   skorunu, ETF akışını, stablecoin likiditesini, sektör rotasyonunu, MVRV
   maliyet tabanını, Hyperliquid konumlanmasını ve smart-money akışını da
   görür; zemin → akış → yapı → kalabalık sırasıyla değerlendirip seviyeler,
   senaryolar, çelişkiler ve somut bir perp işlem planı üretir.

Otonom çalıştırmak için `ANALYST_AUTO=1`: izleme listesini periyodik tarar,
ayrıca yapı skoru sıçradığında / son-dakika haberde / likidasyon kaskadında
sıra beklemeden analiz eder.

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
