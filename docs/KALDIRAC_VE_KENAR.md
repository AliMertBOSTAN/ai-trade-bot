# Kaldıraç ve Kenar — Ölçülen Sonuçlar

Kullanıcı isteği: *"Kaldıraç gibi şeyleri tercih edebilirim, hedefimi
küçültmek istemiyorum. AI pozisyonun garantisine göre karar versin."*

Bu belge, o isteğin **koda çevrilmiş hâlini** ve arkasındaki ölçümleri içerir.
Hedef (420.000 $) değiştirilmedi; değiştirilen şey, hedefin arkasındaki
aritmetiğin **görünür** olması.

---

## 1. "AI pozisyonun garantisine göre karar versin" = Kelly kriteri

Bunun matematikteki karşılığı Kelly kriteridir: bahis (burada kaldıraç)
kenarla doğru, oynaklıkla ters orantılıdır.

```
f* = p − (1−p)/b        p: kazanma olasılığı, b: ort.kazanç / ort.kayıp
kaldıraç = 1 + min(1, f*·kesir) · güven · (tavan − 1)
```

`engine/risk/leverage.py` bunu uygular ve **her adımda kaldıracı yalnızca AŞAĞI
çekebilir**:

| Koşul | Sonuç |
|---|---|
| `LEVERAGE_ENABLED=0` | 1× |
| < 30 kapanan işlem | 1× (kenar ölçülemedi) |
| Ölçülen net PnL ≤ 0 | 1× (kenar yok) |
| Kelly ≤ 0 | 1× (kenar yok) |
| Kelly > 0 | 1 + yarım-Kelly × güven × (tavan−1), tavan `LEVERAGE_MAX` |

**Bugünkü gerçek veriyle çıktı: `1.0×`** — 6 kapanan işlem, net −2,69 $.
Yani "AI karar versin" dendiğinde AI'ın verdiği karar şu an *kaldıraç açma*.
Bu bir güvenlik kısıtı değil; kaldıracın tanımı. Kaldıraç kenarı **çarpar**;
kenar sıfır/negatifse çarpım da sıfır/negatiftir.

---

## 2. Kaldıracın gerçek veride ölçülen etkisi

`engine/backtest/leveraged.py` — ücret + funding + **likidasyon bariyeri** dahil.
Girdi: taranan 60 backtest içindeki **en iyi** hücre (BTC 4h, eşik 0,73, spot **+3,93%**).

| Kaldıraç | Getiri | Maks. düşüş | Funding | Komisyon | Durum |
|---|---|---|---|---|---|
| 1× | **+1,27%** | %5,2 | %1,97 | %0,63 | ayakta |
| 2× | **+1,79%** ← en iyi | %10,2 | %3,93 | %1,26 | ayakta |
| 3× | +1,54% | %15,0 | %5,89 | %1,89 | ayakta |
| 5× | −1,18% | %24,1 | %9,82 | %3,15 | ayakta |
| 10× | −19,04% | %45,1 | %19,65 | %6,30 | ayakta |
| 20× | −69,84% | %78,4 | %39,30 | %12,60 | ayakta |
| 50× | **−100% (likidasyon, bar 339)** | %98,7 | — | — | **SIFIR** |

ETH'de her kaldıraç seviyesi negatif (en iyisi 1× ile −1,82%).

**İki bulgu:**
1. Spot +3,93% olan strateji, perp'e taşınınca funding yüzünden 1×'te +1,27%'ye
   düşüyor. **Funding, küçük kenarı yiyor.**
2. Optimal kaldıraç **2×**, ve kazandırdığı ek getiri **+0,52 puan**.
   5×'ten sonra oynaklık sürüklenmesi (volatility drag) getiriyi negatife çeviriyor.

---

## 3. 420.000 $ hedefi ve kaldıraç: teorem

> **Optional stopping theorem:** Kenarsız (adil) bir piyasada, iflas etmeden
> serveti X katına çıkarma olasılığı **en fazla 1/X**'tir.

100 $ → 420.000 $ için X = 4200:

```
olasılık üst sınırı = 1/4200 = %0,024   (yaklaşık 1'e 4200)
```

**Bu sınır kaldıraçtan bağımsızdır.** Kaldıraç yalnızca sonucu ne kadar çabuk
öğreneceğini değiştirir. Ücret, funding ve slippage sınırı daha da düşürür.
Sınırı yukarı taşıyan tek şey **kanıtlanmış pozitif kenardır**.

`probability_of_target()` bunu hesaplar; UI'daki **Hedef & Risk** sekmesi gösterir.

### Kaldıraç seviyesine göre gereken mükemmel seri

| Kaldıraç | Likidasyon eşiği | 4200× için gereken ardışık +%10 hamle |
|---|---|---|
| 5× | dayanak −%20 | 20,6 |
| 10× | dayanak −%10 | 12,0 |
| 20× | dayanak −%5 | 7,6 |
| 25× | dayanak −%4 | 6,7 |

20×'te 8 mükemmel hamle gerekiyor — ve arada BTC'nin **bir kez** %5 ters
gitmesi yeterli. BTC bunu ayda birkaç kez yapar.

---

## 4. Kenar arayışı: ML katmanı gerçek veriyle eğitildi

`python -m engine.ml.train` (saf-Python lojistik regresyon, walk-forward):

| Sembol | Zaman dilimi | Ufuk | Walk-forward doğruluk | Katlar |
|---|---|---|---|---|
| ETH | 4h | 6 bar | **%56,2** | 52,0 / 53,9 / 57,8 / 61,0 |
| SOL | 4h | 6 bar | %55,2 | 63,6 / 44,8 / 52,6 / 59,7 |
| BTC | 1d | 3 bar | %53,9 | 59,2 / 52,4 / 47,6 / 56,3 |
| BTC | 4h | 6 bar | %51,1 | 53,9 / 45,5 / 50,0 / 55,2 |

Toplu: 16 kat, ~1.232 örnek, ortalama **%53,85** · z = 2,70 (yazı-tura hipotezine karşı).

### Bu ne demek — dikkatli okuma

İstatistiksel olarak %50'nin üstünde **görünüyor**, ama:

- Kat aralığı **%44,8 – %63,6** — varyans devasa.
- Birden çok konfigürasyon denendi (çoklu test yanlılığı).
- **Asıl mesele: kenarın büyüklüğü maliyetle aynı mertebede.**

| Sembol | Ort. bar hareketi | Kenar/işlem | Base tur maliyeti | **Net** |
|---|---|---|---|---|
| ETH 4h | %0,783 | %0,238 | %0,122 | **+%0,116** |
| SOL 4h | %0,882 | %0,225 | %0,122 | +%0,103 |
| BTC 1d | %1,767 | %0,239 | %0,122 | +%0,117 |
| BTC 4h | %0,618 | %0,033 | %0,122 | **−%0,089** |

Yani: işlem başına **~%0,11 net** — kâğıt üstünde. Bu, yılda ~20 işlemle
**~%2/yıl** eder. Gerçek olabilir, ama:
- ince (maliyetin ~2 katı — slippage biraz artarsa sıfırlanır),
- ileriye dönük doğrulanmadı,
- ve 4200×'e giden bir yol değil.

En iyi model (ETH 4h) `data/ml_model.json` olarak kaydedildi; sunucu açılışta
yükler ve kural güvenini **en fazla %25** modüle eder.

---

## 5. Kaldıraçlı CANLI işlem: bugün ne var, ne yok

`GET /live/leverage-status` bunu dürüstçe raporlar:

| Bileşen | Durum |
|---|---|
| Base spot canlı emir | ✅ var (gerçek quote doğrulandı) |
| Kaldıraçlı backtest | ✅ var (`engine/backtest/leveraged.py`) |
| Kelly kaldıraç motoru | ✅ var (`engine/risk/leverage.py`) |
| Perp piyasa verisi (Hyperliquid) | ✅ var (salt okuma) |
| **İmzalı perp CANLI emir yolu** | ❌ **kurulmadı** |

Yani bugün canlı işlem **yalnızca Base spot, kaldıraç 1×** üzerinden yapılır.
Kaldıraçlı canlı emir ayrı bir borsa entegrasyonu ister ve **üç kapının**
arkasındadır: kanıt kapısı + `LEVERAGE_ENABLED=1` + `LEVERAGE_MAX`.

Bunu kasten böyle bıraktım: kanıtlanmamış bir kenarı kaldıraçla çarpacak bir
canlı yol açmak, sana yardım etmek değil, sermayeni daha hızlı eritmek olurdu.

---

## 6. Yeni API uçları ve arayüz

```
GET  /goal                    hedef raporu (gereken vs ölçülen CAGR)
POST /goal                    hedef tanımla  {target_usd, horizon_months}
GET  /leverage                Kelly kararı + likidasyon + iflas olasılığı
GET  /leverage/sweep          gerçek veride 1×–50× kaldıraç taraması
GET  /live/leverage-status    kaldıraçlı canlı yol envanteri
GET  /live/gate               kanıt kapısı
```

Arayüzde **Hedef & Risk** sekmesi: hedefin gerektirdiği günlük/yıllık getiri,
botun ölçülen getirisi, kaldıraç kararı, likidasyon fiyatı, iflas olasılığı ve
kaldıraç taraması tablosu.

---

## 7. Özet

| Soru | Ölçülen cevap |
|---|---|
| Kaldıraç hedefe ulaştırır mı? | Hayır — üst sınır 1/4200 ve kaldıraçtan bağımsız |
| Optimal kaldıraç kaç? | En iyi hücrede **2×**, kazancı +0,52 puan |
| Kaldıraç ne zaman zarar verir? | 5×'ten sonra; 50×'te 339. barda likidasyon |
| Kenar var mı? | İnce bir aday var (~%0,11/işlem net), doğrulanmadı |
| AI şu an ne kaldıraç öneriyor? | **1,0×** — çünkü ölçülen kenar yok |
| Kaldıraçlı canlı işlem hazır mı? | Hayır — perp emir yolu kurulmadı, üç kapı kapalı |

Hedef duruyor. Değişen tek şey: artık hedefe giden yolun her adımında
**gerçek sayıyı** görüyorsun.
