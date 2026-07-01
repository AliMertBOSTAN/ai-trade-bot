//! Istek/yanit tipleri — JSON sozlesmesi (ADR §8) ile birebir. Tutarlar string.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    #[default]
    Paper,
    Live,
}

/// Tum yanitlarin ortak zarfi: { ok, data?, error? }
#[derive(Debug, Clone, Serialize)]
pub struct Envelope<T> {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<T>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ErrInfo>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ErrInfo {
    pub code: String,
    pub message: String,
}

impl<T> Envelope<T> {
    pub fn ok(data: T) -> Self {
        Envelope { ok: true, data: Some(data), error: None }
    }
    pub fn err(code: &str, message: impl Into<String>) -> Self {
        Envelope {
            ok: false,
            data: None,
            error: Some(ErrInfo { code: code.into(), message: message.into() }),
        }
    }
}

// ---------- swap ----------
#[derive(Debug, Clone, Deserialize)]
pub struct SwapRequest {
    pub idempotency_key: String,
    #[serde(rename = "chainId")]
    pub chain_id: u64,
    pub dex: String,
    pub token_in: String,
    pub token_out: String,
    pub amount_in: String,
    pub min_out: String,
    pub deadline_s: u64,
    pub recipient: String,
    #[serde(default)]
    pub mode: Mode,
}

#[derive(Debug, Clone, Serialize)]
pub struct SwapResult {
    pub tx_hash: String,
    pub effective_price: f64,
    pub gas_used: u64,
    pub fee_usd: f64,
    pub nonce: u64,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub simulated_only: bool,
}

// ---------- arbitrage ----------
#[derive(Debug, Clone, Deserialize)]
pub struct ArbRequest {
    pub idempotency_key: String,
    #[serde(rename = "chainId")]
    pub chain_id: u64,
    pub route: Vec<serde_json::Value>,
    pub min_profit_usd: f64,
    #[serde(default)]
    pub use_flashbots: bool,
    #[serde(default)]
    pub mode: Mode,
}

#[derive(Debug, Clone, Serialize)]
pub struct ArbResult {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tx_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bundle_hash: Option<String>,
    pub net_profit_usd: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub included_block: Option<u64>,
    pub simulated_only: bool,
}

// ---------- perp ----------
#[derive(Debug, Clone, Deserialize)]
pub struct PerpRequest {
    pub idempotency_key: String,
    pub venue: String,
    pub symbol: String,
    pub side: String,
    pub size: f64,
    #[serde(default)]
    pub price: Option<f64>,
    #[serde(default)]
    pub reduce_only: bool,
    #[serde(default = "default_tif")]
    pub tif: String,
    #[serde(default)]
    pub mode: Mode,
}

fn default_tif() -> String {
    "Gtc".to_string()
}

#[derive(Debug, Clone, Serialize)]
pub struct PerpResult {
    pub order_id: String,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fill_price: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fill_size: Option<f64>,
}

// ---------- simulate ----------
#[derive(Debug, Clone, Deserialize)]
pub struct SimulateRequest {
    #[serde(rename = "chainId")]
    pub chain_id: u64,
    pub to: String,
    pub data: String,
    #[serde(default)]
    pub value: String,
    pub from: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SimulateResult {
    pub gas_estimate: u64,
    pub will_revert: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub revert_reason: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mode_default_is_paper() {
        assert_eq!(Mode::default(), Mode::Paper);
    }

    #[test]
    fn swap_request_parses_and_defaults_mode() {
        let j = r#"{
            "idempotency_key":"k","chainId":42161,"dex":"uniswap-v3",
            "token_in":"0xA","token_out":"0xB","amount_in":"1000000000",
            "min_out":"5","deadline_s":60,"recipient":"0xC"
        }"#;
        let r: SwapRequest = serde_json::from_str(j).unwrap();
        assert_eq!(r.chain_id, 42161);
        assert_eq!(r.amount_in, "1000000000");
        assert_eq!(r.mode, Mode::Paper);
    }

    #[test]
    fn envelope_ok_and_err() {
        let ok = Envelope::ok(42u32);
        let s = serde_json::to_string(&ok).unwrap();
        assert!(s.contains("\"ok\":true"));
        let e: Envelope<u32> = Envelope::err("GAS_CAP", "too high");
        let s2 = serde_json::to_string(&e).unwrap();
        assert!(s2.contains("\"ok\":false") && s2.contains("GAS_CAP"));
    }

    #[test]
    fn perp_request_tif_default() {
        let j = r#"{"idempotency_key":"k","venue":"hyperliquid","symbol":"ETH",
                    "side":"BUY","size":1.0}"#;
        let r: PerpRequest = serde_json::from_str(j).unwrap();
        assert_eq!(r.tif, "Gtc");
        assert!(!r.reduce_only);
    }
}
