# 420.000 $ Hedefi — Matematik, Ölçüm ve Ne Yapılabilir

Girdi: **başlangıç 100 $ (Base'de native ETH)**, **ufuk 1–2 yıl**,
**hedef 420.000 $**. Bu belge hedefi duygusal değil aritmetik olarak ele alır.

---

## 1. Gereken şey

| | Değer |
|---|---|
| Gereken çarpan | **4.200×** |
| Gereken yıllık bileşik getiri (2 yıl) | **%6.381** |
| Gereken **günlük** getiri | **%1,15 — her gün, 730 gün boyunca, kayıpsız** |
| Gereken yıllık getiri (1 yıl) | %419.900 |

Karşılaştırma için: dünyanın en iyi bilinen sonuçları (Renaissance Medallion)
uzun vadede yıllık ~%39 net. Bitcoin'in en iyi yılı ~%1.300. Yani hedef, en iyi
tek yıllık kripto performansının **beş katını, üst üste iki yıl** ister.

> Bu, "zor bir hedef" değil; **sürdürülebilir örneği olmayan** bir orandır.
> `engine/analytics/goal.py` bunu `feasibility: "gerçekçi değil"` olarak
> etiketler ve uyarı üretir.

---

## 2. Botun ölçülen gerçek performansı

60 backtest koşuldu (5 sembol × 3 çıkış konfigürasyonu × 4 güven eşiği,
1000 gerçek Binance mumu, ücret + gas dahil):

| Sembol | 4h en iyi hücre | Al-tut |
|---|---|---|
| **BTC** | **+3,93%** (eşik 0,73 · PF 2,16 · 7 işlem) | −7,64% |
| ETH | +0,31% (eşik 0,73) | −6,44% |
| SOL | −1,12% (en iyisi bile negatif) | −15,38% |
| BNB | −0,93% | −5,65% |
| LINK | −0,94% | −6,56% |

### Bu bir kenar değil — parametre sivri ucu

BTC · 4h · fixed çıkış, eşiğe göre getiri:

```
0,66 → −12,77%     0,70 → −0,47%     0,73 → +3,93%     0,78 → −1,00%
```

Gerçek bir kenar **plato** yapar (komşu parametrelerde de pozitif kalır).
Buradaki tek noktalık sivri uç, **aşırı-uyumun (overfit) klasik imzasıdır.**

### Walk-forward (out-of-sample) sonucu

| Test | Ortalama OOS getiri | Pozitif kat |
|---|---|---|
| BTC 4h | +0,04% | 1/2 |
| ETH 4h | −1,53% | 0/2 |
| BTC 1d | −0,59% | 0/2 |
| ETH 1d | −1,09% | 0/2 |

**Sonuç: istatistiksel olarak kanıtlanmış bir kâr kaynağı yok.**
Ölçülebilen tek tutarlı davranış, düşen piyasada **al-tut'tan daha az kaybetmek**
(sermaye koruma).

---

## 3. Aynı hedef, gerçek sayılarla

Bot ölçülen ~%9/yıl hızıyla çalışsa bile:

| Senaryo | 100 $ → 420.000 $ süresi |
|---|---|
| %9/yıl (botun ölçülen hızı) | ~97 yıl |
| %15/yıl (iyi bir uzun vade) | ~60 yıl |
| %39/yıl (Medallion seviyesi) | ~25 yıl |

Aylık ekleme ile 2 yılda hedefe varmak için gereken katkı:
**ayda ~15.250 $** (yani hedefi bot değil, katkı taşır).

---

## 4. Yapılan işler

1. **`engine/analytics/goal.py`** — hedef takip modülü.
   `GET /goal` gereken CAGR'ı, ölçülen CAGR'ı, gerçekçilik bandını, hedefe
   kalan süreyi ve gereken aylık katkıyı döndürür.
   **Bilerek pasiftir:** hiçbir risk parametresine dokunmaz. Test
   `test_rapor_hicbir_risk_ayarini_degistirmez` bunu koruma altına alır.
   Sebebi basit: "hedefe yetişmek için riski artır" mantığı, sermayeyi sıfırlama
   olasılığını hedefe ulaşma olasılığının üstüne çıkarır.

2. **Küçük sermaye profili** — `MIN_TRADE_USD` env'i eklendi (varsayılan 10 $,
   Base'de 5 $'a düşürülebilir; tur gas ~0,005 $). 100 $ için önerilen ayarlar
   `.env.example` içinde bir blok olarak duruyor.

3. **Derin tarama** — yukarıdaki 60 backtest + walk-forward; bulgular bu belgede.

---

## 5. Öneri

Hedefi **iki katmana ayırın**:

- **Katman 1 — kanıt (bugün):** 100 $ ile shadow-live. Amaç para kazanmak değil,
  kanıt kapısını (30 kapanan işlem · PF ≥ 1,2 · net PnL > 0) yeşile çevirmek.
  Bu olmadan gerçek para koymak, kanıtlanmamış bir sisteme bahis oynamaktır.
- **Katman 2 — hedef (kanıt sonrası):** kanıt geldikten sonra `GET /goal`
  gerçek ölçülen hızla bir takvim üretir. O takvim 420.000 $ için ne diyorsa,
  gerçek olan odur.

Hedefi hemen düşürmek zorunda değilsiniz — ama botu 4.200× arayacak şekilde
ayarlamak, 100 $'ı 420.000 $ yapmaz; **100 $'ı 0 $ yapar.** Kod bu yüzden
hedefi görür ama hedefe göre davranmaz.
