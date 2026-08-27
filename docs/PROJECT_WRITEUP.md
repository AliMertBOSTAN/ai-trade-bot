# AI Trade Bot — Proje Anlatımı

Bu doküman projeyi beş başlıkta açıklar: **Hedefler, Teknoloji Yığını, Risk
Kontrolleri, Sonuçlar ve Çekirdek Kod Örneği.** Her başlık kodun içindeki gerçek
karşılığına referans verir.

---

## 1. Objectives — Hedefler

Bu otomasyonu **üç somut problemi** çözmek için yazdım:

1. **Çoklu-zincir arbitraj.** Aynı token (ör. WETH) farklı EVM ağlarında ve
   farklı DEX'lerde (Uniswap, PancakeSwap, QuickSwap) farklı fiyatlanır. Amaç bu
   fiyat farklarını sürekli tarayıp, **gas + slippage + köprü maliyeti düşüldükten
   sonra hâlâ net kâr bırakan** fırsatları otomatik tespit etmek.
   → `engine/arbitrage/scanner.py`

2. **AI destekli yön sinyali (direksiyonel trade).** Sadece kural tabanlı
   göstergeler (RSI/EMA/MACD) gürültülü piyasada yanılır; sadece LLM ise
   tutarsız olabilir. Amaç ikisini **hibrit** birleştirmek: teknik katman
   ön-filtre, LLM nihai kararı verir/gerekçelendirir.
   → `engine/signals/engine.py`, `engine/signals/llm.py`

3. **Manuel operasyonu ortadan kaldırmak.** Fiyat izleme, sinyal üretme, risk
   kontrolü ve emir gönderme tek bir döngüde otomatikleşir; insan yalnızca
   parametre ve mod (paper/live) belirler.
   → `engine/bot/orchestrator.py`

Tasarımın değişmez ilkesi: **sermaye korumak getiriden önce gelir.** Bu yüzden
proje önce paper (simülasyon) modunda güvenle çalışır, live mod ise yalnızca tüm
risk kapıları geçildiğinde devreye girer.

---

## 2. Code Stack — Teknoloji Yığını

Bilinçli olarak **polyglot** bir mimari kurdum; her dil en güçlü olduğu yerde:

| Katman | Dil / Kütüphane | Neden |
| --- | --- | --- |
| On-chain okuma + işlem yürütme | **Python + web3.py** | Olgun web3 ekosistemi, hızlı prototipleme, ThreadPool ile paralel RPC |
| AI / LLM danışman | **Python + anthropic / openai SDK** | Sinyal mantığı veriyle aynı süreçte |
| Backend API | **FastAPI + Uvicorn (WebSocket)** | Düşük gecikmeli REST + canlı event akışı |
| Masaüstü arayüz | **Electron + TypeScript + React** | Çapraz platform, tip güvenli UI |
| Keeper / MEV-korumalı gönderim | **TypeScript + Ethers.js v6** | Flashbots Protect entegrasyonu, `staticCall` ön-uçuş |
| Akıllı kontrat | **Solidity ^0.8.24** | Atomik arbitraj, revert garantisi |
| Kalıcı depolama | **SQLite** | İşlem/sinyal/equity geçmişi, backtest |
| Grafik | **Chart.js** | Equity eğrisi |

İki dilin **sınırı net**: Python engine REST+WebSocket (`http://127.0.0.1:8787`)
yayınlar; TypeScript arayüz/keeper bu API'yi tüketir. Bu ayrım sayesinde AI/zincir
mantığı ile sunum/gönderim katmanı bağımsız geliştirilebilir ve test edilebilir.

---

## 3. Risk Controls — Risk Kontrolleri

Bu projenin kalbi risk yönetimidir. Sermayeyi ve işlemi korumak için **çok
katmanlı** savunma uyguladım:

**a) Slippage (fiyat kayması) toleransı.** Her swap'a `amountOutMinimum`
geçilir. Beklenen çıktının altına düşülürse router/kontrat işlemi reddeder.
→ `engine/risk/manager.py::min_out()` ve `ArbExecutor.sol` (`amountOutMin`)

**b) Gas ücreti tavanı.** İşlem öncesi anlık gas fiyatı okunur; `max_gas_gwei`
tavanını aşıyorsa işlem **hiç gönderilmez** (kârsız/zararlı tx engellenir).
→ `manager.gas_ok()`, `live_broker._base_tx()`, `flashbotsKeeper.ts`

**c) Revert-on-no-profit (atomik geri alma).** Arbitraj kontratta tek tx içinde
iki bacak olarak yürütülür. İşlem sonunda net kâr eşiğin altındaysa
`Unprofitable()` ile **tüm transaction revert edilir** — gas dışında kayıp olmaz,
"yarım pozisyon" riski yoktur. → `ArbExecutor.sol::executeArb()`

**d) MEV / Sandwich saldırı koruması.** Live işlemler public mempool yerine
**Flashbots Protect** private relay üzerinden gönderilir; front-running/sandwich
botları işlemi göremez. Ayrıca gönderim öncesi `staticCall` ile **ön-uçuş
simülasyonu** yapılır: revert edecekse zincire hiç gitmez.
→ `src/core/keeper/flashbotsKeeper.ts`

**e) Günlük zarar kill-switch.** Gün içi gerçekleşen zarar `max_daily_loss_usd`'i
aşarsa bot tüm yeni işlemleri durdurur. → `manager.kill_switch_triggered()`

**f) Pozisyon limitleri + stop-loss / take-profit.** Pozisyon başına azami
notional, azami eşzamanlı pozisyon sayısı, otomatik stop-loss/take-profit.
→ `manager.evaluate()`, `manager.check_stop_take()`

**g) Fail-safe mod geçişi + deadline.** Cüzdan anahtarı yoksa live moda
**geçilemez** (paper'da kalır). Tüm router çağrılarına `deadline` verilir; tx
mempool'da beklerse kötü fiyatla dolmaz. → `executor.set_mode()`,
`settings.assert_live_ready()`, `live_broker` deadline

---

## 4. Outcomes — Sonuçlar

> Aşağıdaki sayılar **backtest ve paper-trading** doğrulamasından gelir; canlı
> production getiri vaadi değildir. Amaç sistemin uçtan uca doğru çalıştığını ve
> risk kapılarının devreye girdiğini göstermektir.

**Otomasyonun kazandırdıkları:**

- **Manuel operasyon ortadan kalktı.** Önceden elle yapılması gereken "6 ağ × 2
  DEX × birden çok token fiyatını karşılaştır, spread hesapla, gas düş, karar ver"
  döngüsü tamamen otomatikleşti; tek tick'te onlarca havuz paralel taranıyor.

- **Arbitraj tespiti çalışıyor.** Sentetik fiyatlarla yapılan testte sistem,
  WETH'i Polygon/QuickSwap'ta @\$2.995 alıp Arbitrum/Uniswap'ta @\$3.030 satan
  fırsatı **%1.17 spread** olarak buldu ve **maliyetler düşüldükten sonra net
  \$13.45 kâr** hesapladı; eşik altı fırsatları otomatik eledi.

- **Sinyal + backtest metrikleri.** 300 mumluk sentetik seride backtest:
  **toplam getiri +%3.3, maksimum düşüş %2.9, Sharpe 1.36, kazanma oranı %67**
  (21 işlem). Stop-loss/take-profit otomatik tetiklendi.

- **Risk kapıları doğrulandı.** Güven eşiği altındaki sinyaller, pozisyon limiti
  aşımı ve kill-switch senaryolarının hepsi işlemi gerekçeli biçimde reddetti
  (sessiz başarısızlık yok).

- **Mühendislik kalitesi.** Tüm katmanlar doğrulandı: Python modülleri derlendi,
  TypeScript `--strict` tip kontrolünden (React/ethers/electron/chart.js dahil)
  geçti, Solidity kontratı `solc 0.8.26` ile **0 uyarıyla** derlendi.

- **Operasyonel görünürlük.** Equity eğrisi, açık pozisyonlar, canlı fiyatlar,
  arbitraj fırsatları, sinyaller ve işlem geçmişi tek dashboard'da gerçek zamanlı.

---

## 5. Code Snippet — Çekirdek Kod Örneği

Aşağıda projenin **çekirdek mantığı** var: hibrit sinyal füzyonu (teknik
ön-filtre + LLM nihai karar). Tüm proje değil, kararın nasıl oluştuğunu gösteren
özü. (`engine/signals/engine.py`'den)

```python
def generate_signal(chain_id, base, quote, closes):
    # 1) Teknik göstergelerden kural tabanlı aday karar (ön-filtre)
    tech = compute_snapshot(closes)               # RSI, EMA, MACD, momentum
    rule_action, rule_conf = _rule_decision(tech) # -> ("BUY"/"SELL"/"HOLD", güven)

    # 2) LLM danışman (varsa) kararı doğrular/iyileştirir
    advice = llm.advise(base, quote, tech, rule_action, _returns(closes))

    if advice and advice["action"] in ("BUY", "SELL", "HOLD"):
        llm_action, llm_conf = advice["action"], float(advice["confidence"])
        if llm_action == rule_action:
            # İki katman HEMFİKİR -> güveni yükselt
            action, confidence = rule_action, min(1.0, 0.5*rule_conf + 0.5*llm_conf + 0.1)
        else:
            # ÇELİŞKİ -> daha temkinli LLM kararını al, güveni kıs
            action, confidence = llm_action, max(0.0, 0.5*llm_conf)
        source = "hybrid"
    else:
        # LLM yoksa/başarısızsa -> saf teknik karar (fail-safe)
        action, confidence, source = rule_action, rule_conf, "technical"

    return TradeSignal(chain_id, base, quote, action, confidence,
                       tech, advice and advice.get("rationale", ""), source)
```

Ve risk kapısının özü — bir sinyalin işleme dönüşebilmesi için geçmesi gereken
kontroller (`engine/risk/manager.py`'den):

```python
def evaluate(self, signal, open_positions, cash_usd):
    if self.kill_switch_triggered():                       # günlük zarar limiti
        return RiskDecision(False, "kill-switch")
    if signal.confidence < self.risk.min_confidence:       # güven eşiği
        return RiskDecision(False, "güven düşük")
    if signal.action == "BUY":
        if len(open_positions) >= self.risk.max_open_positions:
            return RiskDecision(False, "azami pozisyon")
        size = min(self.risk.max_position_usd, cash_usd * 0.95)  # pozisyon limiti
        return RiskDecision(True, "onaylandı", size_usd=size)
    ...
```

Ve zincir üstünde kâr garantisi — kontrat, net kâr eşiğin altındaysa **tüm
işlemi geri alır** (`ArbExecutor.sol`'dan):

```solidity
uint256 profit = endBal > startBal ? endBal - startBal : 0;
if (profit < minProfit) revert Unprofitable(profit, minProfit); // revert-on-no-profit
```
