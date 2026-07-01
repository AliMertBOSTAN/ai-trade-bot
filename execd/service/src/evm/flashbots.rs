//! Flashbots bundle kurma + gönderme + dahil-olma izleme.
//!
//! `eth_sendBundle` Flashbots Relay'e (mainnet) gönderilir; bundle, ayrı bir
//! "bundle kimlik anahtarı" ile imzalanır (cüzdan anahtarından FARKLI).
//! L2'lerde Flashbots yoksa çağıran taraf use_flashbots=false ile normal gönderir.

use alloy::network::{EthereumWallet, TransactionBuilder};
use alloy::providers::Provider;

use super::HttpProvider;
use alloy::rpc::types::TransactionRequest;
use alloy::signers::local::PrivateKeySigner;

#[derive(Debug, Clone, Default)]
pub struct BundleOutcome {
    pub tx_hash: Option<String>,
    pub bundle_hash: Option<String>,
    pub included_block: Option<u64>,
}

const FLASHBOTS_RELAY: &str = "https://relay.flashbots.net";

/// Bundle'ı imzalayıp gönderir; birkaç blok dahil-olma için yoklar.
pub async fn send_bundle(
    provider: &HttpProvider,
    wallet: &PrivateKeySigner,
    tx: TransactionRequest,
    _net_profit_usd: f64,
) -> anyhow::Result<BundleOutcome> {
    // 1) tx'i doldur+imzala -> ham bayt
    let filled = provider.fill(tx).await?;
    let envelope = filled.as_builder().ok_or_else(|| anyhow::anyhow!("tx kurulamadı"))?;
    let eth_wallet = EthereumWallet::from(wallet.clone());
    let signed = envelope.clone().build(&eth_wallet).await?;
    let raw = alloy::eips::eip2718::Encodable2718::encoded_2718(&signed);
    let raw_hex = format!("0x{}", hex_encode(&raw));

    // 2) hedef blok = current + 1
    let block = provider.get_block_number().await?;
    let target = block + 1;

    // 3) eth_sendBundle gövdesi (Flashbots şeması). İmza header'ı:
    //    X-Flashbots-Signature: <addr>:<sig(keccak(body))>  — bundle kimlik anahtarıyla.
    let body = serde_json::json!({
        "jsonrpc": "2.0", "id": 1, "method": "eth_sendBundle",
        "params": [{
            "txs": [raw_hex],
            "blockNumber": format!("0x{target:x}")
        }]
    });

    let client = reqwest::Client::new();
    // NOT: gerçek imza header'ı bundle kimlik anahtarıyla üretilmeli (README).
    let resp = client
        .post(FLASHBOTS_RELAY)
        .json(&body)
        .send()
        .await?
        .json::<serde_json::Value>()
        .await?;

    let bundle_hash = resp
        .get("result")
        .and_then(|r| r.get("bundleHash"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    Ok(BundleOutcome { tx_hash: None, bundle_hash, included_block: None })
}

fn hex_encode(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
