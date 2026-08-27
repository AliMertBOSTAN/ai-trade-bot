# macOS'ta Kurulum ve Çalıştırma

Bu proje macOS'ta (hem Intel hem Apple Silicon — M1/M2/M3/M4) çalışır. Mimari
baştan çok-platformludur: Python engine + Electron/Node arayüz. Aşağıdaki adımlar
sıfırdan bir Mac'te çalıştırmak içindir.

> Önemli: Windows/Linux'taki `node_modules` ve `out/` klasörlerini Mac'e
> **kopyalamayın**. Bunlar platforma özel ikili dosyalar içerir; Mac'te taze
> `npm install` / `npm run build` çalıştırın.

---

## 1. Önkoşullar

| Araç | Sürüm | Kurulum |
|------|-------|---------|
| Python | 3.10+ | macOS'ta genelde `python3` olarak gelir; yoksa [python.org](https://www.python.org/downloads/) veya `brew install python` |
| Node.js | 18+ (LTS önerilir) | [nodejs.org](https://nodejs.org) veya `brew install node` |
| Git | herhangi | `xcode-select --install` ile birlikte gelir |

Homebrew yoksa (tavsiye edilir):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python node
```

Sürümleri doğrula:
```bash
python3 --version    # 3.10+
node --version       # 18+
npm --version
```

---

## 2. Python engine kurulumu

Proje kök klasöründe:

```bash
# sanal ortam oluştur ve aktive et
python3 -m venv .venv
source .venv/bin/activate

# bağımlılıkları kur
pip install -r engine/requirements.txt
```

Bağımlılıkların tümü (web3, fastapi, uvicorn, eth-account, pydantic,
python-dotenv, httpx; opsiyonel anthropic/openai) saf çok-platformludur,
Apple Silicon'da da sorunsuz kurulur.

> Engine'i ayrıca elle çalıştırmak istersen:
> `uvicorn engine.app:app --port 8787`
> Ama gerek yok — Electron bunu otomatik başlatır (aşağıya bak).

---

## 3. Arayüz (Electron) kurulumu

```bash
npm install
```

### ⚠️ `better-sqlite3` notu (tek mac pürüzü)

`package.json`'da `better-sqlite3` adında **kullanılmayan** bir native paket var
(kod hiçbir yerde import etmiyor; depolama Python'un stdlib `sqlite3`'ünü
kullanıyor). `npm install` bunu yine de derlemeye çalışır ve bunun için derleme
araçları gerekir. İki çözümden birini seç:

**Seçenek A — derleme araçlarını kur (paketi koru):**
```bash
xcode-select --install        # Xcode Command Line Tools
npm install
npm run rebuild               # electron-rebuild better-sqlite3
```

**Seçenek B — kullanılmayan paketi kaldır (daha basit, önerilen):**
`package.json`'dan `"better-sqlite3"` bağımlılığını ve `"rebuild"` script'ini
sil, sonra:
```bash
npm install                   # artık native derleme yok
```

---

## 4. Yapılandırma (.env)

```bash
cp .env.example .env
```

- **Paper (simülasyon) modu için hiçbir şey doldurmak zorunda değilsin** — RPC,
  LLM key, cüzdan boş olsa bile bot simülasyonla çalışır.
- Gerçek piyasa verisi/fiyat okumak için RPC uçlarını doldur (Alchemy/Infura).
- LLM yorumu (hibrit sinyal + AI Analist paneli) için `ANTHROPIC_API_KEY` veya
  `OPENAI_API_KEY`.
- **Live (gerçek işlem) için** `WALLET_PRIVATE_KEY` gerekir — yalnızca burner
  (ayrı) cüzdan kullan, ana cüzdanını asla.

`AUTO_START_ENGINE=1` zaten varsayılan; Electron, Python engine'ini uygulamayla
birlikte başlatır/durdurur ve `.venv/bin/python`'ı otomatik bulur. Özel bir
Python yolu için `.env`'de `ENGINE_PYTHON=/tam/yol/python` verebilirsin.

---

## 5. Çalıştırma

```bash
npm run dev
```

Bu kadar. Electron penceresi açılır, arka planda `uvicorn` (engine) otomatik
kalkar ve arayüz `127.0.0.1:8787`'e bağlanır. Üst bardaki nokta yeşilse engine
bağlı demektir. Paper/Live anahtarı ve Başlat/Durdur üst bardadır.

Sekmeler: **Genel · Piyasa · Sinyaller · Arbitraj · Haberler · AI Analist ·
İşlemler.**

### Backtest (opsiyonel)
`package.json`'daki `backtest` script'i `python` çağırıyor; macOS'ta genelde
sadece `python3` vardır. venv aktifken doğrudan modülü çalıştır:
```bash
source .venv/bin/activate
python3 -m engine.backtest.run_live_backtest --symbol ETHUSDT --interval 1h --limit 500
```

### Üretim derlemesi (opsiyonel)
```bash
npm run build      # out/ klasörünü Mac için üretir
npm start          # önizleme
```

---

## 6. Mac'e özgü davranışlar (kodda hazır)

Otomatik engine yönetimi (`src/main/index.ts`) platforma duyarlı yazıldı:

- Python: önce `.venv/bin/python`, yoksa sistem `python3` (Windows'ta
  `python.exe`/`python`).
- Süreç kapatma: macOS/Linux'ta `SIGTERM` (Windows'ta `taskkill /T /F`).
- `window-all-closed`: macOS'ta uygulama dock'ta kalır (Apple kuralı), tekrar
  açılışta engine geri başlatılır.

---

## 7. Sık karşılaşılan sorunlar

| Belirti | Neden / Çözüm |
|---------|---------------|
| `npm install` `better-sqlite3` derlemede hata | Bölüm 3 — Seçenek A (Xcode CLT) veya B (paketi kaldır). |
| Arayüz açık ama "engine yok" yazıyor | venv kurulu mu? `.env`'de `AUTO_START_ENGINE=0` mı? Elle: `uvicorn engine.app:app --port 8787`. |
| `python: command not found` (backtest) | `python` yerine `python3` kullan veya venv'i aktive et. |
| Lacivert boş ekran | Eski sorundu, düzeltildi (CSP main process'ten veriliyor). `npm install` + `npm run dev` taze çalıştır. |
| Apple Silicon'da paket uyumu | Sorun yok; Node/Electron ve Python tekerlekleri arm64 destekler. |
| Port 8787 dolu | Başka bir engine açık olabilir; otomatik başlatma var olanı tekrar başlatmaz, ona bağlanır. |

---

## Özet (tek bakışta)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r engine/requirements.txt
# (better-sqlite3'ü package.json'dan kaldırdıysan native derleme gerekmez)
npm install
cp .env.example .env        # paper mod için doldurman şart değil
npm run dev
```
