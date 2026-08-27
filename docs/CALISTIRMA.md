# Çalıştırma & Test Kılavuzu

Sıfırdan her şeyi çalıştırıp test etmek için adım adım. **Windows/PowerShell** öncelikli;
macOS/Linux notları eklenmiştir. Önerilen sıra: **önce testler → sonra paper modda çalıştır →
en son opsiyonel Rust (execd) / Docker.** Gerçek para hiçbir adımda gerekmez (paper varsayılan).

---

## 0. Ön koşullar

| Araç | Sürüm | Zorunlu mu? |
|---|---|---|
| Python | 3.10+ | Evet (motor) |
| Node.js | 20+ | Evet (arayüz) |
| Rust | 1.81+ | Hayır (yalnız Rust execd için) |
| Docker | güncel | Hayır (yalnız konteyner için) |

Kontrol:
```powershell
python --version
node --version
cargo --version   # opsiyonel
```

---

## 1. Kurulum (bir kez)

Proje klasöründe (`...\ai-trade-bot`):

### Python motoru
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```
> PowerShell "script çalıştırılamıyor" hatası verirse, bir kez:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### Arayüz (Electron + React)
```powershell
npm install
```

### .env
```powershell
copy .env.example .env
```
`.env` varsayılanları paper mod için yeterlidir. LLM **opsiyoneldir** — anahtar yoksa bot saf
teknik+haber kararıyla çalışır (uyarı verir, durmaz).

---

## 2. Testler (önce bunu çalıştır)

Her şeyin sağlam olduğunu **çalıştırmadan önce** doğrula.

### Python (88 test)
```powershell
pytest
```
Beklenen: hepsi `passed` (web3 yoksa birkaç provider testi `skipped` — normal).

### TypeScript tip kontrolü + arayüz testleri
```powershell
npm run typecheck      # tsc --strict (web + node)
npm test               # vitest (format yardımcıları)
```

### Tip drift (Python↔TS senkron mu)
```powershell
python scripts/gen_types.py --check
```

### Rust execd çekirdeği (opsiyonel, Rust kuruluysa)
```powershell
cd execd
cargo test -p execd-core
cargo clippy -p execd-core -- -D warnings
cd ..
```

> Tek komutla: `make test` (Make varsa) veya yukarıdakileri sırayla.

---

## 3. Paper modda çalıştır (asıl uygulama)

İki yol var. **Kolay yol: tek komut** — Electron motoru otomatik başlatır.

### Yol A — Tek komut (önerilen)
```powershell
npm run dev
```
`AUTO_START_ENGINE` açık olduğundan Electron, Python motorunu (`:8787`) kendisi başlatır ve
arayüz ona bağlanır. Üst barda **"engine bağlı"** (yeşil nokta) görünmeli.

### Yol B — Motor ve arayüzü ayrı çalıştır (hata ayıklama için)
1. Terminal 1 (motor):
   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m uvicorn engine.app:app --port 8787
   ```
2. Terminal 2 (arayüz):
   ```powershell
   npm run dev
   ```

### İlk bakışta ne görmelisin
- **Genel**: equity eğrisi, KPI'lar, fiyatlar.
- **Sinyaller**: birkaç dakika ısınmadan sonra BUY/SELL/HOLD kartları (Binance verisiyle ön-dolar).
- **Stratejiler**: aktif stratejiler + sermaye dilimi + canlı kararlar.
- **İşlemler**: paper işlemler (DEX/gas etiketli). Üstte 🗑 "Geçmişi temizle".
- Sağ üstte 🌐 ile TR/EN dil değişimi.

> Not: Sinyaller "bot çalışıyor mu?" diyorsa, üst bardaki **▶ Başlat** ile botu başlat.

---

## 4. Çoklu strateji (aynı anda birkaç strateji)

`.env`'e ekle (ad:ağırlık, virgülle):
```
STRATEGIES=hybrid:1, trend:1, mean_reversion:0.5
```
Mevcut stratejiler: `hybrid`, `trend`, `mean_reversion`, `breakout`, `funding_arb`.
Yeniden başlat; **Stratejiler** sekmesinde her birine düşen sermaye dilimini ve canlı kararlarını
görürsün. (Boş bırakılırsa yalnız `hybrid` çalışır.)

---

## 5. Backtest (strateji doğrulama, opsiyonel)

Gerçek Binance verisiyle, maliyet-farkında (gas+slippage+ücret) backtest + zengin metrikler:
```powershell
.\.venv\Scripts\Activate.ps1
python -m engine.backtest.run_live_backtest --symbol ETHUSDT --interval 1h --limit 500
```
Çıktıda Sharpe, Sortino, Calmar, max drawdown, profit factor, expectancy göreceksin.

---

## 6. (Opsiyonel) Rust emir-iletim servisi — execd

Yalnız **daha hızlı/deterministik iletim** istiyorsan ve Rust kuruluysa. Paper'da gerçek para yok.

```powershell
cd execd
cargo build --release        # ilk derleme alloy'u indirir, birkaç dakika sürer
cd ..
```
`.env`'de:
```
EXEC_BACKEND=rust
EXECD_MODE=paper             # önce paper!
# WALLET_KEY=...             # SADECE live için, SADECE execd görür (burner cüzdan)
```
execd'yi başlat (ayrı terminal):
```powershell
cd execd
cargo run --bin execd        # 127.0.0.1:8788
```
Sağlık: `http://127.0.0.1:8788/health` `ok` dönmeli. execd kapalıysa motor **otomatik paper'a
düşer** (fail-safe) — riskli bir şey olmaz.

> Üretim öncesi tamamlanacak yer-tutucular: router/ArbExecutor adres tabloları, Flashbots imza
> header'ı, Hyperliquid EIP-712 imzası (bkz. `execd/README.md`). Bunlar gerçek adres/anahtar ister.

---

## 7. (Opsiyonel) Docker ile motor + execd

```powershell
docker compose up --build
```
`engine` (:8787) ve `execd` (:8788, yalnız localhost) ayağa kalkar. Arayüzü yine `npm run dev`
ile aç; `EXECD_URL`/`EXEC_BACKEND` ile bağla.

---

## 8. Canlı (live) moda geçiş — DİKKAT

Sadece paper'da kanıtladıktan **sonra**:
1. Backtest + paper performansı iyi (Sharpe, win-rate, pozitif expectancy).
2. `.env`: `TRADING_MODE=live` (ve execd kullanıyorsan `EXECD_MODE=live`).
3. `WALLET_PRIVATE_KEY` / `WALLET_KEY` — **burner cüzdan**, ana cüzdanın değil. Rust kullanıyorsan
   anahtar yalnız execd ortamında olmalı; Python motoru görmemeli.
4. RPC anahtarların (`RPC_ETHEREUM`, ...) tanımlı olmalı (yoksa public yedekler devreye girer).
5. Önce **testnet** (Sepolia/Arbitrum-Sepolia) + küçük tutar.

Risk kontrolleri zaten aktif: slippage tavanı, gas tavanı, günlük zarar kill-switch, min-edge kapısı,
revert-on-no-profit, paper→live terfi kriteri.

---

## 9. Sorun giderme

| Belirti | Çözüm |
|---|---|
| Arayüz "engine yok (uvicorn?)" | Motoru başlat (Yol B) veya `AUTO_START_ENGINE=1` kontrol et; portu (8787) başka şey tutuyor mu? |
| PowerShell venv aktive olmuyor | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `npm run dev` derleme/rollup hatası | `node_modules` sil + `npm install` (platform ikilisi yenilenir) |
| Sinyal yok | Birkaç dk ısınma bekle + üst bardan **▶ Başlat** |
| LLM çağrısı gitmiyor | Normal — anahtar yoksa LLM atlanır; sadece güçlü sinyalde + cooldown sonrası çağrılır |
| `cargo build` (execd) alloy hatası | alloy sürümünü güncelle; `execd/README.md` derleme notu |
| execd bağlanmıyor | `EXEC_BACKEND=rust` + execd çalışıyor mu (`/health`); değilse motor paper'a düşer |

---

## Hızlı özet (kopyala-çalıştır)

```powershell
# kurulum
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt
npm install; copy .env.example .env

# test
pytest; npm run typecheck; npm test

# çalıştır (paper)
npm run dev
```
