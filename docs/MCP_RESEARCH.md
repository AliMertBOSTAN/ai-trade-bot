# MCP Araştırması — AI Trade Bot için İlgili Sunucular

Bu botun ihtiyaç duyabileceği harici veri/yetenekler için MCP (Model Context
Protocol) sunucuları araştırıldı. Aşağıdakiler Claude bağlayıcı kayıt defterinde
(connector registry) bulundu ve trade botu bağlamında değerlendirildi.

## Doğrudan ilgili (piyasa / kripto verisi)

| MCP | Ne sağlar | Botta kullanım | Öncelik |
|-----|-----------|----------------|---------|
| **Crypto.com** | Gerçek zamanlı fiyat, emir, mum (candlestick), ticker, index/mark price | CEX referans fiyatı + canlı mum; `marketdata` ve backtest beslemesine alternatif/yedek kaynak | Yüksek |
| **CoinDesk** | Canlı + tarihsel spot/index OHLCV, orderbook, trades, top list | Backtest için tarihsel veri (Binance'e yedek), index fiyatları | Yüksek |
| **LunarCrush** | Gerçek zamanlı **sosyal medya duyarlılığı**, coin/konu/etkileyici metrikleri | Hibrit sinyale **sosyal duyarlılık ağırlığı**; haber + sosyal sinyal füzyonu | Orta-Yüksek |
| **Blockscout** | On-chain veri: adres/işlem/token/kontrat, ENS, blok | Cüzdan/işlem doğrulama, on-chain likidite/holder analizi, arbitraj öncesi kontrat kontrolü | Orta |
| **FMP** (Financial Modeling Prep) | Geniş finansal piyasa verisi, takvim, analist, emtia | Makro bağlam (DXY, emtia), risk-on/off rejimi | Düşük-Orta |

## Değerlendirme ve entegrasyon yol haritası

Bu MCP'ler iki şekilde kullanılabilir:

1. **Cowork/Claude masaüstü tarafında (hemen):** Kullanıcı bu bağlayıcıları
   bağlayıp Claude'a "ETH için Crypto.com fiyatını ve LunarCrush duyarlılığını
   getir" diyebilir. Kod değişikliği gerektirmez; sadece bağlantı.

2. **Engine'e veri kaynağı olarak (kod):** Bot şu an Binance + DexScreener +
   RSS kullanıyor. Mimaride `engine/marketdata/` altında her kaynak ayrı modül
   (`binance.py`, `dexscreener.py`, `news.py`). Aynı desende eklenebilir:
   - `engine/marketdata/social.py` → LunarCrush (sosyal duyarlılık skoru).
     `analyst._build_prompt` ve `signals/engine._rule_decision`'a opsiyonel
     "social" bloğu olarak girer.
   - `engine/marketdata/coindesk.py` → backtest için tarihsel OHLCV yedeği
     (`run_live_backtest` zaten Binance + CoinGecko yedeği yapıyor; CoinDesk 3.
     kaynak olur).
   - On-chain doğrulama için Blockscout, live broker öncesi token/kontrat
     güvenlik kontrolü (honeypot/holder dağılımı) olarak değerlidir.

   Not: Bu engine entegrasyonları HTTP API anahtarı ister; MCP sunucuları
   doğrudan Python'dan çağrılmaz (MCP istemci protokolü gerekir). Pratik yol:
   ilgili sağlayıcının REST API'sini `marketdata/http.py` deseniyle eklemek.

## Önerilen ilk adım

- **LunarCrush sosyal duyarlılığı**, en yüksek katma değerli ekleme: hibrit
  sinyal şu an teknik + (opsiyonel) LLM. Sosyal duyarlılık üçüncü bağımsız
  sinyal bloğu olarak eklenirse choppy/haber-odaklı piyasalarda ayırt edicilik
  artar.
- **CoinDesk/Crypto.com** tarihsel veri yedeği backtest güvenilirliğini artırır.

Bu belge bir öneri/araştırma çıktısıdır; bağlayıcıların bağlanması kullanıcı
onayı gerektirir (registry üzerinden "Connect").
