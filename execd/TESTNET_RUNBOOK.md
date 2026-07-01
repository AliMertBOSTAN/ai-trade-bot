# execd — Testnet Derleme & Ölçüm Runbook

Bu doküman execd emir-iletim servisini (Rust, axum + alloy 0.3 + rustls) bir
**testnette** çalıştırıp gecikme (latency) ve doğruluk metriklerini ölçmek için
adım adım yol gösterir. Üretimde gerçek fonla çalıştırmadan önce burada ölçün.

> Güvenlik: testnette bile **ayrı bir test cüzdanı** kullanın. Ana ağ özel
> anahtarını ASLA testnet RPC'sine veya bu servise koymayın.

## 0. Derleme

execd, TLS için **rustls** kullanır; sistemde OpenSSL gerekmez.

```bash
cd execd
cargo build --release            # tüm workspace (core + service)
cargo test  -p execd-core        # 18 birim test
cargo clippy --workspace         # lint
```

Çıktı ikili: `target/release/execd`.

## 1. Testnet yapılandırması

`.env` (veya ortam değişkenleri):

```
EXECD_BIND=127.0.0.1:8799
EXECD_SHARED_SECRET=degistir-bir-deger
WALLET_PRIVATE_KEY=0x<TEST_CUZDAN_ANAHTARI>   # sadece testnet!

# Sepolia (chainId 11155111) + Base Sepolia (84532) RPC'leri (birden çok = yarış)
CHAIN_11155111_RPCS=https://rpc.sepolia.org,https://ethereum-sepolia.publicnode.com
CHAIN_84532_RPCS=https://sepolia.base.org,https://base-sepolia.publicnode.com

# Flashbots testnette yok; bundle yerine normal gönderim kullanılır
EXECD_USE_FLASHBOTS=false
```

Test ETH musluğu (faucet): Sepolia/Base Sepolia resmi faucet'lerinden alın.

## 2. Servisi başlat

```bash
./target/release/execd
# log: "execd dinliyor 127.0.0.1:8799" + bağlanan zincir sayısı
```

Sağlık kontrolü:

```bash
curl -s localhost:8799/health | jq
curl -s localhost:8799/metrics            # Prometheus formatı
```

## 3. Python motorunu execd'ye yönlendir

Python tarafı `ExecBackend` köprüsüyle execd'yi kullanır (fail-safe: execd
yanıt vermezse paper moda düşer).

```
EXEC_BACKEND=execd
EXECD_URL=http://127.0.0.1:8799
EXECD_SHARED_SECRET=degistir-bir-deger
```

## 4. Ölçüm senaryoları

Her senaryoyu **paper** ve **testnet-live** modda ayrı ayrı çalıştırıp
karşılaştırın. Aşağıdaki uçlar `X-Execd-Secret` başlığı ister.

### 4.1 Simülasyon gecikmesi (zincire yazmaz, güvenli)

```bash
hyperfine -w 3 -r 50 \
  'curl -s -X POST localhost:8799/simulate \
     -H "X-Execd-Secret: $EXECD_SHARED_SECRET" \
     -H "content-type: application/json" \
     -d "{\"chain_id\":11155111,\"to\":\"0x...\",\"from\":\"0x...\",\"data\":\"0x\"}"'
```

Ölçülen: `eth_call` + `estimate_gas` round-trip; çoklu-RPC **yarışın** en hızlı
yanıtı döndürdüğünü `/metrics`'teki `execd_rpc_race_winner_total` ile doğrulayın.

### 4.2 Swap iletim gecikmesi (testnet, gerçek tx)

```bash
curl -s -X POST localhost:8799/swap \
  -H "X-Execd-Secret: $EXECD_SHARED_SECRET" \
  -H "content-type: application/json" \
  -d '{"chain_id":84532,"dex":"uniswap_v3","token_in":"0x...WETH",
       "token_out":"0x...USDC","amount_in":"1000000000000000",
       "min_out":"0","recipient":"0x<TEST_CUZDAN>","deadline_s":120}'
```

Ölçülen kademeler (her biri `/metrics` histogramında):
- `execd_fill_seconds` — nonce/gas/fee doldurma
- `execd_sign_seconds` — yerel imzalama
- `execd_broadcast_seconds` — `eth_sendRawTransaction` yarışı
- `execd_confirm_seconds` — ilk onay (1 blok)

### 4.3 Nonce yönetimi doğruluğu

Aynı zincire **eşzamanlı 10 swap** gönderin; `execd_nonce_conflict_total`
**0** olmalı ve tüm tx'ler farklı ardışık nonce almalı (core `nonce` testi
bu mantığı birim düzeyde doğrular).

## 5. Karşılaştırma tablosu (doldurun)

| Metrik                     | Paper | Sepolia | Base Sepolia |
|----------------------------|-------|---------|--------------|
| simulate p50 / p99 (ms)    |       |         |              |
| broadcast p50 / p99 (ms)   |       |         |              |
| confirm p50 (s)            |       |         |              |
| RPC yarış kazananı dağılımı|   —   |         |              |
| nonce çakışması            |   0   |         |              |
| revert-on-no-profit isabet |       |         |              |

## 6. Başarı kriterleri (üretime geçiş öncesi)

- [ ] 50+ testnet swap'ta **0 nonce çakışması**
- [ ] `revert-on-no-profit` kârsız arbitrajı zincirde geri sardı (gas hariç kayıp yok)
- [ ] simulate p99 < 300 ms (yerel RPC ile)
- [ ] çoklu-RPC yarışı en az 2 farklı sağlayıcıyı kazanan olarak gösterdi (failover kanıtı)
- [ ] kill-switch testnette tetiklendiğinde tüm yeni emirler reddedildi

## 7. Bilinen sınırlar

- Flashbots yalnızca Ethereum ana ağında; testnette `use_flashbots=false`.
- `simulate_swap` şu an konservatif `min_out` döndürür; gerçek quote entegrasyonu
  (Quoter v3 / getAmountsOut) üretim öncesi eklenmeli (router.rs'de işaretli).
- Gas→USD dönüşümü Python tarafında yapılır; execd ham gas birimi döndürür.
