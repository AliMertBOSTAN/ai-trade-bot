# execd — Rust emir-iletim servisi

ADR-0001'in uygulaması. Python motoru _doğrulanmış_ emirleri yerel HTTP ile buraya
iletir; execd iletim + imzalama + simülasyon + çoklu-RPC yarışı + Flashbots'tan sorumludur.

## Yapı

```
execd/
  core/      # saf mantık (types, safety, nonce, idempotency) — TEST EDİLDİ (cargo test)
  service/   # bin (axum + alloy + tokio) — ağ I/O
  contracts/execd.openapi.yaml   # tek kaynak sözleşme
  Dockerfile
```

- **core** ağ-bağımsızdır ve `cargo test` ile doğrulanır (18 birim testi).
- **service** alloy/axum içerir; ilk `cargo build` bağımlılıkları derler (birkaç dakika).

## Çalıştırma

```bash
# Geliştirme
cd execd && cargo run --bin execd        # 127.0.0.1:8788

# Python motorunu rust backend'e geçir
export EXEC_BACKEND=rust
export EXECD_URL=http://127.0.0.1:8788
```

## Güvenlik (ÖNEMLİ)

- Özel anahtar (`WALLET_KEY`) **yalnız execd** ortamında bulunur; Python süreci görmez.
- Yalnız `127.0.0.1`'e bağlanır. Burner cüzdan kullanın; canlı öncesi testnet.
- `paper` modda zincire DOKUNULMAZ (yalnız simülasyon).
- Fail-safe: execd erişilemezse Python live emir göndermez, paper'a düşer.

## Derleme notu (alloy API)

`service/` modülleri alloy 0.3 kalıbına göre yazılmıştır. alloy hızlı geliştiğinden,
ilk `cargo build` sırasında bazı imzaların (provider builder, signer, `sol!` makrosu,
`send_raw_transaction`) güncel alloy sürümüne göre küçük uyarlamalar gerektirebilir.
Yer-tutucu bırakılan noktalar (router/ArbExecutor adres tabloları, Flashbots imza header'ı,
Hyperliquid EIP-712 imzası) üretim öncesi tamamlanmalıdır — kodda açıkça işaretlidir.

## Test

```bash
cd execd
cargo test -p execd-core      # saf mantık (hızlı)
cargo clippy -p execd-core    # lint
cargo build --release         # tam servis (alloy derler)
```

Python köprü testleri: `pytest tests/test_exec_backend.py` (httpx mock ile, execd gerekmez).
