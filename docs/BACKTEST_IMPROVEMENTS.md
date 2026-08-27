# Kârlılık İyileştirmeleri — Backtest Canlı-Eşitliği, Cooldown, ATR Çıkışlar, Walk-Forward

Tarih: 2026-07-09 · Veri: Binance gerçek klines (BTCUSDT, ETHUSDT)

## Sorun

Canlı akış (orchestrator) ATR trailing stop (`ExitManager`), işlem cooldown'u ve
ATR risk-tabanlı boyutlamayı zaten kullanıyordu; **backtester ise kullanmıyordu**
(sabit %5/%10 SL/TP, cooldown yok, tam boy pozisyon). Yani backtest, botun
gerçekte çalıştırdığı mantığı ölçmüyordu — parametreler körlemesine seçiliyordu.

## Yapılanlar

1. **Backtester canlı-eşitliği** (`engine/backtest/backtester.py`)
   `run_backtest(..., exit_style="atr", exit_cfg=ExitConfig(...), cooldown_bars=N,
   risk_pct=0.01)` — ExitManager (ATR stop + trailing + kısmi kâr + başabaş),
   kapanış sonrası cooldown ve `atr_based_size` tavanı artık backtest'te birebir
   simüle ediliyor. Varsayılan çağrı eski davranışla bit-uyumlu (geriye dönük).
   Dönüşe `exit_breakdown` (çıkış gerekçesi → adet) eklendi.

2. **Çok-boyutlu walk-forward** (`engine/backtest/walk_forward.py`)
   `walk_forward(..., param_grid=...)` ve `grid_search_params(...)`:
   min_confidence × trail_mult × atr_stop_mult × cooldown_bars × risk_pct
   ızgarası her kat'ın in-sample kısmında taranır, kazanan out-of-sample test
   edilir (`DEFAULT_PARAM_GRID` hazır). Eski `min_conf_grid` yolu korunur.

3. **CLI** (`engine/backtest/run_live_backtest.py`)
   Yeni bayraklar: `--exit-style atr|fixed --trail-mult --atr-stop-mult
   --cooldown --risk-pct` ve **`--compare`** (aynı veride eski/yeni yan yana).

4. **Testler** (`tests/test_backtest_advanced.py`)
   +5 test: geriye-dönük uyumluluk, ATR modu, cooldown işlem-sayısı freni,
   risk_pct boyut tavanı, param_grid'li walk-forward. Tüm süit: **149/149 geçti**.

## Önce/Sonra — aynı sabit veri (1h × 1000 mum, $10k, tavan $10k)

6 pencere ortalaması (BTC+ETH × 3 rejim: düşüş −13.6%, yükseliş +20.3%, çöküş −24%):

| Metrik            | fixed (eski) | atr+cooldown (yeni, en iyi kombin.) |
|-------------------|-------------:|------------------------------------:|
| Ortalama getiri   |      −11.03% |                              −10.70% |
| Ortalama maks. DD |       16.74% |                           **11.83%** |
| İşlem/pencere     |         ~9.0 |                                 ~7.7 |

4h yeniden örneklenmiş aynı veri: fixed ort. −3.20% / DD 7.47 → **atr −2.11% / DD 3.13**.
$500 pozisyon tavanlı ilk ölçümde: BTC −8.35% → −1.83%, ETH −8.37% → −0.92%
(DD ~%85 düştü). Cooldown=30 bar + min_confidence=0.73 en tutarlı kazanım.

## Ana bulgular (kârlılığın asıl kaldıraçları)

1. **Maliyet baskındır.** Paper modeli tur başına ~%1.6 (50bps slippage ×2 +
   %0.3 komisyon ×2) keser. 1h mumda tipik kazanç hedefi bunu karşılamıyor —
   +20%'lik boğa penceresinde bile 10 işlem tüm kârı yedi. CEX-gerçekçi 10bps
   slippage ile aynı strateji başabaşa geliyor (BTC W2: −0.16%, PF 1.57).
   → **Daha az ve daha büyük-hedefli işlem: 4h sinyal ufku, yüksek eşik.**
2. **min_confidence 0.73 ≫ 0.60** her pencerede (varsayılan 0.73 doğru; backtest
   CLI'ında `--min-confidence 0.73` kullan).
3. **Cooldown (≥16-30 bar) DD'yi belirgin düşürüyor**; getiriden götürmüyor.
4. **Tek "en iyi" çıkış stili yok**: 1h'de atr+trailing, 4h'de geniş sabit TP
   kazandı → sembol/interval başına `walk_forward(param_grid=...)` ile seç,
   `engine/tuning/optimizer.py` kalıcılaştırır.
5. **risk_pct (%1) kuyruk riskini sınırlar**, getiri maliyeti ihmal edilebilir.

## Canlı mod için somut öneriler

- `TRADE_COOLDOWN_S`: 900 → **14400+** (4h; 1h mumda 30-bar cooldown'un karşılığı
  daha da yüksek). Aşırı-işlem/maliyet kanamasını keser.
- `MIN_CONFIDENCE=0.73` kalsın (UI'dan düşürme).
- `EXIT_STYLE=atr` varsayılanı kalsın; sembol bazında walk-forward "fixed"
  öneriyorsa değiştir.
- Bilinen tuzak (CLAUDE.md): canlı sinyal geçmişi 1h klines tohumu + 8sn tick
  karışımı — backtest 1h/4h mumlarıyla birebir değil. Sinyal penceresini sabit
  mum aralığına oturtmak bir sonraki doğal adım.

## Nasıl çalıştırılır

```bash
# Aynı veride eski/yeni karşılaştırma
python -m engine.backtest.run_live_backtest --symbol BTCUSDT --interval 4h \
    --limit 1000 --min-confidence 0.73 --cooldown 8 --risk-pct 0.01 \
    --atr-stop-mult 3.0 --trail-mult 3.5 --compare

# Walk-forward (çok-boyutlu ızgara)
python - <<'PY'
from engine.backtest.run_live_backtest import fetch_binance
from engine.backtest.walk_forward import walk_forward, DEFAULT_PARAM_GRID
from engine.config.settings import RiskConfig
c = fetch_binance("BTCUSDT", "4h", 1000)
print(walk_forward(c, "BTC", "USD", 10000, RiskConfig(),
                   min_conf_grid=[0.6], n_folds=3, interval="4h",
                   param_grid=DEFAULT_PARAM_GRID))
PY
```

## Faz 2 — Maliyet kapısı + HTF trend filtresi (2026-07-09)

İki yeni kapı eklendi; ikisi de **varsayılan kapalı** (fail-safe, eski davranış):

1. **Maliyet-farkında giriş kapısı** (`RiskManager._edge_ok`, hem canlı hem
   backtest yolundan geçer): beklenen lehte hareket (`EDGE_ATR_MULT`×ATR/fiyat)
   tur maliyetinin (2×slippage + 2×taker fee) `MIN_EDGE_RATIO` katından azsa
   yeni pozisyon açılmaz. Env: `MIN_EDGE_RATIO=2.0` önerilir (0=kapalı).
2. **HTF (4×) trend filtresi** (`htf_up_flags`, backtester + `--htf-filter ema`):
   üst zaman dilimi EMA trendi aşağıyken yeni alım engellenir; bakış-öncesi yok
   (yalnız kapanmış üst-TF mumları), ısınma süresince pasif.

### Ölçüm — 1h × 6 pencere (BTC+ETH × 3 rejim, $10k, atr-best taban)

| Yapılandırma            | Ort. getiri | Ort. maks. DD | Ort. işlem |
|-------------------------|------------:|--------------:|-----------:|
| atr-best (Faz 1)        |     −10.70% |        11.83% |        7.7 |
| + HTF filtresi          |      −8.75% |         9.48% |        5.5 |
| + maliyet kapısı (2.0)  |      −3.23% |         3.53% |        1.8 |
| + ikisi birden          |  **−2.78%** |     **2.82%** |        0.8 |

Maliyet kapısı 1h'lik işlemlerin çoğunu "ekonomik değil" diye eliyor — doğru
karar: aynı sinyaller 4h'de ekonomik.

### Ölçüm — 4h × 1000 mum (sürekli; BTC al-tut −29.3%, ETH −40.7%)

| Yapılandırma        | BTC ret / DD  | ETH ret / DD  |
|---------------------|---------------|---------------|
| fixed               | −8.76 / 14.62 | −22.98 / 24.34|
| atr cd8             | −14.09 / 14.09| −9.59 / 11.19 |
| atr cd8 + kapılar   | **−7.81 / 8.45** | **−6.02 / 7.71** |

Boğa penceresi kontrolü (W2-4h, +20.3%): fixed +9.27 → kapılarla +6.89 (kazanç
büyük ölçüde korunur); ETH'de kapılar nötr. Asimetri istenen yönde: **düşüşte
zarar/DD yarıdan fazla azalır, yükselişte kazancın çoğu kalır.**

### Canlı için önerilen env

```
MIN_EDGE_RATIO=2.0      # maliyet kapısı (RiskManager, canlıda otomatik etkin)
TRADE_COOLDOWN_S=14400  # aşırı-işlem freni
MIN_CONFIDENCE=0.73     # değiştirme
```

## Faz 3 — Canlı sinyal hizalaması + otomatik yeniden-optimizasyon (2026-07-09)

1. **Sinyal hizalaması** (`engine/marketdata/candle_agg.py` + orchestrator):
   Eski canlı akış sinyalleri "1h kline tohumu + 8sn tick" karışımı seriden
   üretiyordu — göstergeler tutarsız zaman adımları görüyordu ve backtest'te
   kanıtlanan hiçbir şey canlıya birebir taşınmıyordu. Artık tick'ler
   `CandleAggregator` ile sabit aralıklı mumlara toplanır; **sinyaller yalnız
   kapanmış mumlarla üretilir** (girişler mum kapanışında karar bulur),
   stop/trailing çıkışları her tick denetlenmeye devam eder. Yan kazanımlar:
   sinyaller artık gerçek OHLCV (high/low/volume göstergeleri doğru çalışır)
   ve 4× üst-TF serisiyle (MTF onayı canlıda da etkin) besleniyor; mum
   kapanmadan sinyal yeniden üretilmediği için LLM/DB gürültüsü azalır.
   Env: `SIGNAL_ALIGN=candles` (varsayılan; `ticks` = eski davranış),
   `SIGNAL_INTERVAL=1h` (1m…1d).

2. **Otomatik yeniden-optimizasyon** (`optimize_symbol_atr` +
   `TradingBot._maybe_auto_tune`): `AUTO_TUNE_INTERVAL_H` saatte bir (örn. 168
   = haftalık; 0 = kapalı, varsayılan) watchlist sembolleri için gerçek klines
   çekilir, ATR-modu parametre ızgarası (min_confidence × trail × stop ×
   cooldown × risk_pct) walk-forward ile out-of-sample doğrulanır ve
   `data/tuned_params.json` güncellenir. Koşum ayrı daemon thread'dedir;
   bitince sembol-bazlı eşik kapısı (`_maybe_trade`) yeni değerleri hemen
   kullanır. Elle tetikleme:

   ```python
   from engine.backtest.run_live_backtest import fetch_binance
   from engine.tuning.optimizer import optimize_symbol_atr
   from engine.config.settings import RiskConfig
   optimize_symbol_atr(fetch_binance("BTCUSDT", "4h", 1000), "BTC", "USD",
                       10000, RiskConfig(), interval="4h")
   ```

## Faz 4 — Short desteği (2026-07-09)

Altyapı tamamlandı; **varsayılan kapalı** ve dürüst sonuç: mevcut sinyal
motoruyla short, test edilen veride değer katmıyor (aşağıda). Mekanizma doğru
çalışıyor; walk-forward sembol bazında yalnız kanıtlarsa açar.

### Yapılanlar

1. **ExitManager short aynası** (`engine/trading/exits.py`): `side="short"` —
   trailing en düşük fiyatı izler (dip + trail×ATR), başabaş/kısmi TP/zaman
   çıkışı aynalı. Long davranışı bit-uyumlu korunur.
2. **Backtester çift yön** (`run_backtest(..., allow_short=True)`, CLI
   `--allow-short`): SELL sinyali düz durumda SHORT açar, BUY cover eder.
   Kapı aynaları: HTF filtresi short'u üst-TF YUKARIYKEN engeller; cooldown ve
   ATR boyut tavanı iki yönde; ayrıca aşırı-satıma (RSI≤35) short atılmaz.
3. **İki kritik risk düzeltmesi** (ölçümle bulundu):
   - *Gizli kaldıraç*: short açılışı nakdi şişirir; `cash×0.95` boyutlama her
     yeni short'u büyütüyordu → tavan artık **equity** üzerinden
     (`RiskManager.evaluate` short dalı). Düzeltme öncesi ort. zarar −6.19%,
     sonrası −2.71% (1h × 6 pencere).
   - *Piramitleme yok*: SELL sinyali düşüşte barlarca sürer; her barda short'a
     ekleme istif oluşturuyor ve tek ayı rallisi hepsini süpürüyordu → short
     yalnız düz (flat) durumda açılır.
4. **Walk-forward/auto-tune entegrasyonu**: `param_grid`'e
   `"allow_short": [False, True]` (ve `"htf_filter"`) eklenebilir; seçim
   out-of-sample kanıta bağlanır.

### Ölçüm (kapılar açık: edge 2.0 + HTF, atr-best taban)

| Veri                    | long-only     | long+short    |
|-------------------------|---------------|---------------|
| 1h × 6 pencere (ort)    | −2.78 / DD 2.8| −2.72 / DD 4.2|
| 4h BTC (al-tut −29%)    | −7.81 / 8.5   | −10.94 / 11.3 |
| 4h ETH (al-tut −41%)    | −6.02 / 7.7   | −3.53 / 5.7 (PF 0.84) |

Walk-forward (4h, allow_short ızgarada): her katta **short=False** seçildi —
momentum-SELL sinyali short girişi olarak geç kalıyor (dipte açıyor, ayı
rallisi stopluyor). Short'un kazanması için ayrı bir giriş mantığı (ör. ralli
tepesinden pullback-short) gerekir; mevcut haliyle sadece seçenek olarak durur.

### Kullanım

```bash
python -m engine.backtest.run_live_backtest --symbol ETHUSDT --interval 4h \
    --limit 1000 --min-confidence 0.73 --exit-style atr --cooldown 8 \
    --risk-pct 0.01 --htf-filter ema --min-edge 2.0 --allow-short
```

Not: Short yalnız backtest/perp simülasyonudur; spot DEX'te short yapılamaz —
canlı orchestrator long-only kalır (`allow_short` orada açılmaz).

## Açık sonraki adımlar

1. **Short'a özel giriş mantığı** (pullback-short: HTF düşüşte ralli tepesinden
   giriş) — mevcut momentum-SELL girişi short için geç kalıyor (Faz 4 ölçümü).
2. HTF sert kapısını canlı sinyal motoruna da bağlamak (MTF onayı canlıda
   yumuşak: güveni kısıyor; sert kapı backtest'te ölçüldü).
3. Funding arbitrajını gerçek funding verisiyle doğrulamak (piyasa-nötr gelir).
4. Auto-tune sonuçlarından cooldown/trailing'i canlıya sembol-bazlı uygulamak
   (şimdilik yalnız min_confidence kapısı sembol-bazlı).
