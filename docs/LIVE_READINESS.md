# Canlıya Hazırlık — Ölçümler, Kapılar ve Runbook

Bu belge, botun **Base ağında gerçek parayla** çalıştırılmasından önce yapılan
ölçümleri, eklenen güvenlik kapılarını ve adım adım geçiş prosedürünü içerir.

Tarih: 2026-08-02 · Kapsam: Base (8453) · Mod: paper → shadow → live

---

## 1. Boru hattı doğrulandı (canlı, gerçek ağ)

`scripts/live_preflight.py --chain 8453` **gerçek Base mainnet** üzerinde
salt-okuma olarak koştu:

| Kontrol | Sonuç |
|---|---|
| RPC bağlantısı | ✅ Base bağlı |
| Canlı gas | **0.01 gwei** (tavan 80 gwei — bol pay) |
| Gerçek DEX quote'u | ✅ `USDC → WETH` @ Uniswap V3 (fee tier 500) |
| Gerçekleşen fiyat | 1.860,21 USD/ETH (Binance spot 1.858,74 ile uyumlu) |
| Tek swap gas maliyeti | **0,0027 USD** |
| **Tur (gidiş-dönüş) maliyeti** | **12,2 bps (%0,122)** |
| İmzalayıcı cüzdan | ✅ `0xf953…d1B2` |

**Yorum:** Base'de maliyet yapısı bir trade botu için elverişli — %0,12'lik tur
maliyeti, ETH'nin 4 saatlik tipik hareketinin çok altında. Yani *altyapı* hazır;
kalan soru *stratejinin kenarı*.

---

## 2. Kârlılık ölçümü — dürüst tablo

Gerçek Binance verisiyle (1000 mum) tam matris tarandı:
sembol × zaman dilimi × çıkış stili × güven eşiği.

### 2.1 Zaman dilimi belirleyici

| Zaman dilimi | En iyi getiri (eşik 0,73) | Al-tut | Karar |
|---|---|---|---|
| **1h** | BTC **−3,32%** · ETH **−10,00%** | −2,3% / +7,7% | ❌ her eşikte zarar |
| **4h** | BTC **+3,93%** · ETH **+0,31%** | −7,7% / −6,4% | ✅ en iyi |
| **1d** | BTC **+0,59%** · ETH **−2,10%** | +4,0% / −36,0% | ~ savunmacı |

➡️ **`SIGNAL_INTERVAL` varsayılanı `1h` → `4h` yapıldı.** (`engine/config/settings.py`)

### 2.2 Güven eşiği belirleyici

Eşik 0,60'ta bot **her senaryoda** ağır zarar etti (−15%…−35%): aşırı işlem.
Eşik 0,85'te hiç işlem açmadı. **0,73 tek çalışan bant.**

### 2.3 En iyi hücre (BTC · 4h · eşik 0,73 · fixed çıkış)

```
getiri  +3,93%   |  al-tut  −7,71%   →  +11,6 puan alfa
maks. düşüş  5,12%  |  profit factor 2,16  |  7 kapanan işlem
```

### 2.4 ⚠️ Ama out-of-sample kanıt YOK

Walk-forward (2 ve 4 kat, eğitim/test ayrımı) çalıştırıldı:

| Test | Ortalama OOS getiri | Pozitif kat | Robust? |
|---|---|---|---|
| BTC 4h, 2 kat | +0,04% | 1/2 | sınırda |
| ETH 4h, 2 kat | −1,53% | 0/2 | ❌ |
| BTC 1d, 2 kat | −0,59% | 0/2 | ❌ |
| ETH 1d, 2 kat | −1,09% | 0/2 | ❌ |

Kat başına yalnızca **0–2 işlem** düşüyor — strateji bu veri miktarıyla
istatistiksel olarak doğrulanamayacak kadar seçici.

> **Sonuç (dürüst):** Botun 4h/0,73 ayarında ölçülebilir bir **savunma kenarı**
> var (düşen piyasada al-tut'u belirgin şekilde geçiyor, düşük düşüşle).
> Fakat **"gerçek parayla kâr eder" iddiası bu veriyle kanıtlanmış değildir.**
> Bu yüzden koda bir *kanıt kapısı* eklendi (§3).

---

## 3. Eklenen güvenlik kapıları

### 3.1 Kanıt kapısı — `engine/trading/live_gate.py`
Bot, **kendi ileriye dönük işlemlerinde** kanıt üretmeden canlıya geçemez:

| Eşik | Varsayılan |
|---|---|
| `LIVE_GATE_MIN_TRADES` | 30 kapanan işlem |
| `LIVE_GATE_MIN_PROFIT_FACTOR` | 1,2 |
| `LIVE_GATE_MIN_NET_USD` | 0 (net PnL pozitif olmalı) |
| `LIVE_GATE_MAX_DD_PCT` | %15 |

`live_preflight` bunu **`proven_edge`** kontrolü olarak taşır. Sağlanmazsa
`POST /mode {"mode":"live"}` **reddedilir**.

### 3.2 Ön-uçuş zorunlu
`set_mode("live")` artık önce `live_preflight()` çalıştırır; `ready=False` ise
mod DEĞİŞMEZ. Kontroller: imzalayıcı · RPC · fonlanmış zincir · **gerçek DEX
rota testi** · kanıt kapısı · LLM · kill-switch · günlük harcama limiti.
Zorlamak için `LIVE_FORCE=1` (tavsiye edilmez).

### 3.3 Broker seviyesi son savunma — `LiveBroker`
- Tek işlem nosyoneli `max_position_usd × 1,05` tavanını aşamaz.
- Gas, nosyonelin %50'sinden büyükse işlem "ekonomik değil" diye reddedilir.
- **EIP-1559 desteği**: Base/OP/Arbitrum'da `maxFeePerGas` kullanılır ve
  `max_gas_gwei` sert tavanı uygulanır (legacy `gasPrice` fazla ödüyordu).
- `eth-account` sürüm uyumu (`rawTransaction` / `raw_transaction`).

### 3.4 Base sinyal listesine eklendi
`SIGNAL_WATCHLIST`'e `(8453, WETH/USDC)` ve `(8453, cbBTC/USDC)` girdi —
önceden Base'de hiç sinyal üretilmiyordu.

---

## 4. Veri takvimi + otonom araştırmacı

### 4.1 Takvim — `engine/marketdata/calendar.py`
Anahtarsız, üç kaynaklı:
1. **BLS ICS** (`bls.gov/schedule/news_release/bls.ics`) — TÜFE, ÜFE, İstihdam
   Raporu, JOLTS… gerçek resmi yayın saatleriyle (US-Eastern → UTC, DST doğru).
2. **Statik FOMC tablosu** (2026–2027, 14:00 ET faiz kararı).
3. **Haberden çıkarım** — başlıkta ileri tarihli kripto olayı (unlock / ETF
   kararı / ağ yükseltmesi) geçerse takvime eklenir + `data/calendar_custom.json`.

**Doğrulandı:** canlı BLS akışından 313 olay çekildi; sıradakiler
7 Ağu NFP · 12 Ağu TÜFE · 13 Ağu ÜFE.

### 4.2 İşlem freni
- **Yüksek etkili** olay (TÜFE/NFP/FOMC): yayından **90 dk önce – 45 dk sonra**
  yeni ALIM **durur**. Satış/stop/çıkışlar ASLA engellenmez.
- **Orta etkili** olay (ÜFE, GSYH): pozisyon boyutu **×0,5**.
- Hepsi `CALENDAR_*` env değişkenleriyle ayarlanır, `CALENDAR_GUARD=0` kapatır.

### 4.3 Araştırmacı — `engine/marketdata/researcher.py`
Arka planda **30 dakikada bir** (ayarlanabilir):
1. takvimi tazeler,
2. taze haberlerden yeni olay tarihleri çıkarır,
3. **48 saat içindeki** yüksek etkili her olay için ilgili haberleri + piyasa
   bağlamını (fiyat, oynaklık, funding, OI, long/short) toplar ve LLM ile
   **senaryo notu** üretir (beklenti · senaryolar · izlenecek seviyeler · risk · bias),
4. olay geçince **sonuç okuması** yapar (açıklanan veri + piyasa tepkisi).

Notlar: WS `research` olayı · **Telegram/Discord bildirimi** · `data/research.json` ·
UI'da **"Takvim & Araştırma"** sekmesi. LLM yoksa **sayısal not** üretilir — akış durmaz.

---

## 5. Canlıya geçiş runbook'u (Base)

```bash
# 0) Anahtarı düz metinden çıkar (ÖNEMLİ — .env'de açık anahtar durmasın)
python -c "from engine.security.keystore import *"   # keystore oluşturma akışı
#    .env: WALLET_KEYSTORE_PATH + WALLET_KEYSTORE_PASSWORD

# 1) Ayarlar
TRADING_MODE=paper
SIGNAL_INTERVAL=4h
MIN_CONFIDENCE=0.73
EXIT_STYLE=fixed
MAX_POSITION_USD=25          # küçük başla
MAX_GAS_GWEI=5               # Base'de 0.01 gwei; 5 fazlasıyla yeterli
TELEGRAM_BOT_TOKEN=... ; TELEGRAM_CHAT_ID=...

# 2) SHADOW-LIVE: gerçek fiyat + gerçek gas, sahte para. En az 30 kapanan işlem.
uvicorn engine.app:app --port 8787
#    İlerlemeyi izle:
curl localhost:8787/live/gate

# 3) Kanıt kapısı yeşile dönünce cüzdanı fonla (Base):
#    ~50-100 USDC + ~0.002 ETH (gas). Sonra:
python scripts/live_preflight.py --chain 8453
#    "SONUÇ: CANLIYA HAZIR ✔" görmeden ilerleme.

# 4) Günlük harcama limitini AYARLA (0 = limitsiz; kapı bunu reddeder)
curl -X POST localhost:8787/risk/config -d '{"daily_spend_limit_usd": 100}'

# 5) Live'a geç (ön-uçuş otomatik tekrar çalışır)
curl -X POST localhost:8787/mode -d '{"mode":"live"}'
```

**Geri dönüş (rollback):** `POST /mode {"mode":"paper"}` her zaman serbesttir;
günlük zarar kill-switch'i `max_daily_loss_usd` aşılınca otomatik devreye girer.

---

## 6. Açık riskler / yapılacaklar

1. **Out-of-sample kanıt eksik** — shadow-live 30+ işlem biriktirene kadar
   gerçek para KOYMAYIN. Kanıt kapısı bunu zaten zorluyor.
2. **`.env` içinde düz metin private key + seed cümlesi var.** Şifreli keystore'a
   taşıyın ve o cüzdanı yalnızca bu bot için kullanın.
3. **PCE (BEA) takvimde yok** — BEA ICS yayınlarsa `CALENDAR_ICS_FEEDS`'e ekleyin.
4. Token unlock takvimi için ücretsiz API bulunamadı (DefiLlama emissions artık
   ücretli); şu an haber-çıkarımı + `calendar_custom.json` ile besleniyor.
5. Base watchlist'te `DEGEN` yok (Binance karşılığı olmadığı için sinyal
   beslemesi yapılamıyor) — DEX-only fiyatla eklenebilir.
