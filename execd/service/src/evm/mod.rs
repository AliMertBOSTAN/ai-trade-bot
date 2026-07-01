//! EVM alt-sistemi: çoklu-RPC yarışı, calldata kurma, Flashbots, ABI.

use alloy::network::Ethereum;
use alloy::providers::fillers::{
    BlobGasFiller, ChainIdFiller, FillProvider, GasFiller, JoinFill, NonceFiller,
};
use alloy::providers::{Identity, RootProvider};
use alloy::transports::http::{Client, Http};

/// HTTP sağlayıcı tipi — `with_recommended_fillers()` (gas/nonce/chain-id/blob)
/// ile kurulur; `.fill()` bu tip üzerinde mevcuttur. Tüm EVM alt-modülleri
/// bu tek kanonik tipi paylaşır.
pub type HttpProvider = FillProvider<
    JoinFill<
        Identity,
        JoinFill<GasFiller, JoinFill<BlobGasFiller, JoinFill<NonceFiller, ChainIdFiller>>>,
    >,
    RootProvider<Http<Client>>,
    Http<Client>,
    Ethereum,
>;

pub mod abi;
pub mod flashbots;
pub mod provider;
pub mod router;

/// Simülasyon çıktısı (swap için ortak).
#[derive(Debug, Clone)]
pub struct SimOut {
    pub expected_out: String, // bigint string
    pub effective_price: f64,
    pub gas_estimate: u64,
    pub fee_usd: f64,
}

/// Arbitraj simülasyon çıktısı.
#[derive(Debug, Clone)]
pub struct ArbSim {
    pub net_profit_usd: f64,
}
