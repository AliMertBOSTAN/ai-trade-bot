# Roadmap v2 — 9 Geliştirme + Genel Kontrol (tamamlandı)

Bu turda eklenen 9 ileri özellik. Hepsi **additif ve fail-safe**: yeni katmanlar
mevcut paper/live akışını bozmaz, eksik veri/araç durumunda nötr varsayılana döner.
Tümü `python scripts/check_all.py` ile doğrulanır.

## 1. Rejim-değişimli çoklu-strateji yürütme
`engine/strategy/router.py` + `engine/backtest/multi_backtest.py`. Her stratejiye
sermaye dilimi (alt-portföy); her barda piyasa rejimi (trend↑/trend↓/range) tespit
edilir, yalnızca rejime UYAN stratejiler işlem açar. Birleşik equity + per-strateji
atıf (attribution) + rejim dağılımı raporlanır.

## 2. Short / perp desteği
`portfolio.py` + `risk/manager.py` işaretli (signed) miktar pozisyonları destekler
(negatif = short). Düşüş rejiminde long-only -2.24% → short-açık +18.94% (kanıtlandı).
Stop/TP short için yön ters çevrilir.

## 3. Uyarlanabilir / ML sinyal ağırlıkları
`engine/ml/` — saf-Python lojistik regresyon (numpy YOK). Özellik→sonuç eğitimi,
walk-forward doğrulama (aşırı-uyum ölçümü), `blend_confidence` ile kural güvenini
modüle eder (en fazla %25 etki). `python -m engine.ml.train` ile gerçek Binance
verisiyle eğitilir; sunucu açılışta `data/ml_model.json` varsa otomatik yükler.
Model yokken davranış DEĞİŞMEZ.

## 4. On-chain balina + likidasyon akışı
`engine/marketdata/derivatives.py` — anahtarsız Binance Futures: funding rate,
açık pozisyon (OI) değişimi, long/short oranı → squeeze/likidasyon yönü.
`engine/marketdata/onchain.py` — opsiyonel Etherscan borsa netflow (anahtar yoksa
nötr). AI Analiz paneline ⚡ Türev/Likidasyon kartı olarak işlenir.

## 5. Çoklu-zaman-dilimi (MTF) onayı + otomatik parametre ayarı
Sinyal motoru artık üst-TF onayı alır (çelişkide güven kısılır). `engine/tuning/`
walk-forward ile sembol başına en iyi eşikleri (min_confidence, stop/TP) seçip
`data/tuned_params.json`'a kaydeder; bot açılışta uygular. `python -m engine.tuning.run_tune`.

## 6. execd derleme + testnet ölçüm hazırlığı
Rust execd servisi **tam derlenir** (alloy 0.3.6 + **rustls**, OpenSSL'siz).
core 18 test + clippy temiz. `execd/TESTNET_RUNBOOK.md` ile Sepolia/Base-Sepolia'da
gecikme (simulate/broadcast/confirm) ve nonce doğruluğu ölçüm planı.

## 7. Akıllı yürütme + portföy riski (yola bağlı)
`engine/trading/smart_exec.py` — derinlik-tabanlı slippage + ücret + gas ile EN İYİ
DEX rotası seçer; drawdown'a göre pozisyonu küçültür (de-risk); büyük emir için
TWAP parça planı. Orchestrator karar yoluna bağlandı.

## 8. Bildirimler + günlük özet
`engine/notify/` — Telegram / Discord / masaüstü; anahtar yoksa log'a düşer.
Live işlem, mod değişimi, kill-switch olaylarında bildirim. `/summary`, `/notify/test`,
`/notify/summary` uçları (zamanlanabilir).

## 9. Live güvenlik sertleştirme
`engine/security/keystore.py` — şifreli JSON keystore'dan anahtar yükleme (düz-metne
güvenli alternatif; anahtar ASLA log/UI'a sızmaz). `engine/security/spending.py` —
günlük harcama limiti kapısı (kill-switch'ten bağımsız). `/metrics` (Prometheus),
`/security`, `/backup` uçları.

## Genel kontrol mekanizması
`scripts/check_all.py` (`make check` / `npm run check`): Python pytest + import smoke +
lint, TS typecheck + tip-üretim, Rust core test + clippy + service derleme, sentetik
backtest smoke. Eksik araç → SKIP; zorunlu adım başarısız → çıkış 1 (CI uyumlu).

**Doğrulama:** 143 Python testi + 18 Rust testi geçiyor; tsc --strict temiz;
execd service 0 hata derleniyor.
