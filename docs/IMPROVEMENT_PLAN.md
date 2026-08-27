# AI Trade Bot — Geliştirme Planı ve Uygulama Kaydı

Bu belge, botun "daha verimli ve daha güzel" hale getirilmesi için çıkarılan
geliştirme maddelerini ve her birinin uygulama durumunu içerir. Hedef: kullanıcının
yalnızca cüzdanını değil **piyasayı, haberleri, göstergeleri ve AI yorumunu** da
tek ekrandan görebilmesi.

## A. Görünürlük (piyasayı da gör) — UYGULANDI

1. **Piyasa paneli (CEX vs DEX).** Engine'de zaten var olan `/marketdata` ucu
   arayüze bağlandı. Binance (CEX) ve Uniswap/DEX fiyatı yan yana; spread (bps),
   24s değişim, hacim, likidite, emir defteri dengesizliği gösteriliyor.
   → `components/MarketPanel.tsx`, `api.market()/marketMulti()`.
2. **Haber akışı paneli.** `/news` (CoinDesk, Cointelegraph, Decrypt, The Defiant,
   Investing.com TR, Ninja News) arayüze geldi; kaynak + zaman + başlık, tıklanır.
   → `components/NewsPanel.tsx`, `api.news()`.
3. **AI analist paneli.** `/analyst/{symbol}` arayüze bağlandı (on-demand, LLM
   maliyetini boşa harcamamak için butonla). Sentiment, özet, CEX/DEX yorumu,
   haber etkisi, riskler. LLM yoksa sayısal rapor.
   → `components/AnalystPanel.tsx`, `api.analyst()`.
4. **Gösterge detayları.** Sinyaller artık sadece AL/SAT değil; RSI, StochRSI,
   ADX, Supertrend, Bollinger %B, MACD, MFI, WaveTrend, Squeeze gibi 40+ gösterge
   barlar/çiplerle görünüyor. → `components/Indicators.tsx`.
5. **Canlı gas göstergesi.** Yeni `/gas` ucu zincir başına canlı gas (gwei + tek
   swap USD tahmini) döndürüyor; üst barda ve KPI'da görünüyor.

## B. Daha güzel arayüz — UYGULANDI

6. **Sekmeli dashboard.** Tek uzun sayfa yerine: Genel · Piyasa · Sinyaller ·
   Arbitraj · Haberler · Analist · İşlemler sekmeleri.
7. **Modern görsel dil.** Yenilenen `styles.css`: yumuşak kartlar, durum renkleri,
   gösterge barları, sticky üst bar, daha okunur tipografi, boş-durum mesajları.
8. **KPI şeridi.** Equity, Nakit, Toplam PnL, Açık pozisyon, Arbitraj fırsatı,
   Canlı gas — renk kodlu.

## C. Doğruluk / verimlilik — UYGULANDI (önceki turlar + bu tur)

9. **Gas her zaman hesaba katılır.** Canlı `eth_gasPrice` × gas birimi × native USD;
   arbitraj net kârı, paper/live broker fee'si ve risk kararı gas'i içerir
   (`engine/dex/gas.py`).
10. **Çoklu-DEX arbitraj.** ETH ve BNB'de 6'şar DEX (Uniswap/Sushi/Pancake/Shiba/
    Biswap/ApeSwap) — intra-chain fırsat yüzeyi büyüdü.
11. **Genişletilmiş sinyal motoru.** 40+ klasik + TradingView göstergesi, ADX trend
    filtresi (choppy piyasada aşırı işlemi azaltır).
12. **Engine otomatik başlat/durdur** + .venv tespiti (`src/main/index.ts`).

## D. MCP araştırması — bkz. `docs/MCP_RESEARCH.md`

13. Piyasa/sosyal/on-chain veri için MCP sunucuları araştırıldı (Crypto.com,
    CoinDesk, LunarCrush, Blockscout, FMP) ve entegrasyon yol haritası çıkarıldı.

## E. Sonraki adımlar (öneri, henüz uygulanmadı)

- Gerçek zamanlı WebSocket fiyat akışı (şu an REST polling 5 sn).
- Pozisyon bazlı grafik (mum + giriş/çıkış işaretleri).
- Çoklu sembol watchlist + kullanıcı tanımlı token listesi.
- Backtest sonuçlarını arayüzden çalıştırma ekranı.
- LunarCrush sosyal duyarlılığını hibrit sinyale ağırlık olarak ekleme.
- Bot'u bir MCP sunucusu olarak dışa açma (Claude masaüstünden sorgulanabilir).
