//! Çoklu-RPC provider havuzu + `send_race` (ilk dönen kazanır) — asıl gecikme kazancı.
//!
//! NOT: alloy API'si sürümle değişebilir; aşağıdaki çağrılar alloy 0.3 kalıbına göredir.
//! `cargo build` sırasında küçük imza farkları gerekebilir (bkz. execd/README.md).

use std::collections::HashMap;

use alloy::network::TransactionBuilder;
use alloy::primitives::{Address, U256};
use alloy::providers::{Provider, ProviderBuilder};
use alloy::rpc::types::TransactionRequest;
use alloy::signers::local::PrivateKeySigner;
use futures::stream::{FuturesUnordered, StreamExt};

use execd_core::types::{SimulateRequest, SimulateResult, SwapRequest, ArbRequest};

use super::{ArbSim, HttpProvider, SimOut};
use crate::config::Config;


/// Bir zincir için N provider (öncelik sırasıyla).
struct ChainProviders {
    #[allow(dead_code)] // teşhis/log için saklanır
    chain_id: u64,
    providers: Vec<HttpProvider>,
    healthy: Vec<bool>,
}

pub struct ProviderPool {
    chains: HashMap<u64, ChainProviders>,
    signer: Option<PrivateKeySigner>,
}

impl ProviderPool {
    pub async fn init(cfg: &Config) -> anyhow::Result<Self> {
        let mut chains = HashMap::new();
        for (id, ccfg) in &cfg.chains {
            let mut providers = Vec::new();
            for url in &ccfg.rpc_urls {
                let p = ProviderBuilder::new().with_recommended_fillers().on_http(url.parse()?);
                providers.push(p);
            }
            let healthy = vec![true; providers.len()];
            chains.insert(*id, ChainProviders { chain_id: *id, providers, healthy });
        }

        let signer = match &cfg.wallet_key {
            Some(k) => Some(k.parse::<PrivateKeySigner>()?),
            None => None,
        };

        Ok(ProviderPool { chains, signer })
    }

    pub fn chain_ids(&self) -> Vec<u64> {
        self.chains.keys().copied().collect()
    }

    pub fn signer_address(&self) -> Option<Address> {
        self.signer.as_ref().map(|s| s.address())
    }

    pub fn is_connected(&self, chain_id: u64) -> bool {
        self.chains.get(&chain_id).map(|c| c.healthy.iter().any(|h| *h)).unwrap_or(false)
    }

    fn primary(&self, chain_id: u64) -> anyhow::Result<&HttpProvider> {
        let c = self.chains.get(&chain_id).ok_or_else(|| anyhow::anyhow!("zincir yok: {chain_id}"))?;
        c.providers.first().ok_or_else(|| anyhow::anyhow!("provider yok: {chain_id}"))
    }

    pub async fn tx_count(&self, chain_id: u64, addr: Address) -> anyhow::Result<u64> {
        let p = self.primary(chain_id)?;
        Ok(p.get_transaction_count(addr).pending().await?)
    }

    pub async fn gas_price_gwei(&self, chain_id: u64) -> anyhow::Result<f64> {
        let p = self.primary(chain_id)?;
        let wei = p.get_gas_price().await?;
        Ok(wei as f64 / 1e9)
    }

    /// Aynı imzalı tx'i N provider'a aynı anda yollar; İLK başarılı tx_hash'i döndürür.
    pub async fn send_race(&self, chain_id: u64, raw: Vec<u8>) -> anyhow::Result<String> {
        let c = self.chains.get(&chain_id).ok_or_else(|| anyhow::anyhow!("zincir yok"))?;
        let mut futs = FuturesUnordered::new();
        for p in &c.providers {
            let raw = raw.clone();
            futs.push(async move {
                p.send_raw_transaction(&raw).await.map(|pending| *pending.tx_hash())
            });
        }
        while let Some(res) = futs.next().await {
            if let Ok(hash) = res {
                return Ok(format!("{hash:#x}"));
            }
        }
        anyhow::bail!("tüm RPC'ler send_raw başarısız")
    }

    pub async fn sign_and_send_race(
        &self,
        chain_id: u64,
        tx: TransactionRequest,
    ) -> anyhow::Result<String> {
        let signer = self.signer.as_ref().ok_or_else(|| anyhow::anyhow!("imzalayıcı yok"))?;
        let p = self.primary(chain_id)?;
        // gas/nonce/fee alanlarını doldur, imzala, ham baytları çıkar
        let filled = p.fill(tx).await?;
        let envelope = filled.as_builder().ok_or_else(|| anyhow::anyhow!("tx kurulamadı"))?;
        let wallet = alloy::network::EthereumWallet::from(signer.clone());
        let signed = envelope.clone().build(&wallet).await?;
        let raw = alloy::eips::eip2718::Encodable2718::encoded_2718(&signed);
        self.send_race(chain_id, raw).await
    }

    // ---- simülasyon ----
    pub async fn eth_call_simulate(&self, req: &SimulateRequest) -> anyhow::Result<SimulateResult> {
        let p = self.primary(req.chain_id)?;
        let tx = TransactionRequest::default()
            .with_to(req.to.parse::<Address>()?)
            .with_input(hex_to_bytes(&req.data)?)
            .with_from(req.from.parse::<Address>()?);
        match p.call(&tx).await {
            Ok(_out) => {
                let gas = p.estimate_gas(&tx).await.unwrap_or(0);
                Ok(SimulateResult { gas_estimate: gas as u64, will_revert: false, revert_reason: None })
            }
            Err(e) => Ok(SimulateResult {
                gas_estimate: 0,
                will_revert: true,
                revert_reason: Some(e.to_string()),
            }),
        }
    }

    pub async fn simulate_swap(&self, req: &SwapRequest) -> anyhow::Result<SimOut> {
        super::router::simulate_swap(self.primary(req.chain_id)?, req).await
    }

    pub async fn simulate_tx(&self, chain_id: u64, tx: &TransactionRequest) -> anyhow::Result<SimOut> {
        super::router::simulate_tx(self.primary(chain_id)?, tx).await
    }

    pub async fn build_swap_tx(
        &self,
        req: &SwapRequest,
        nonce: u64,
    ) -> anyhow::Result<TransactionRequest> {
        let from = self.signer_address().ok_or_else(|| anyhow::anyhow!("imzalayıcı yok"))?;
        super::router::build_swap_tx(req, nonce, from)
    }

    // ---- arbitraj ----
    pub async fn simulate_arb(&self, req: &ArbRequest) -> anyhow::Result<ArbSim> {
        super::abi::simulate_arb(self.primary(req.chain_id)?, req).await
    }

    pub async fn build_arb_tx(&self, req: &ArbRequest, nonce: u64) -> anyhow::Result<TransactionRequest> {
        let from = self.signer_address().ok_or_else(|| anyhow::anyhow!("imzalayıcı yok"))?;
        super::abi::build_arb_tx(req, nonce, from)
    }

    pub async fn send_flashbots_bundle(
        &self,
        chain_id: u64,
        tx: TransactionRequest,
        net_profit_usd: f64,
    ) -> anyhow::Result<super::flashbots::BundleOutcome> {
        let signer = self.signer.as_ref().ok_or_else(|| anyhow::anyhow!("imzalayıcı yok"))?;
        super::flashbots::send_bundle(self.primary(chain_id)?, signer, tx, net_profit_usd).await
    }
}

fn hex_to_bytes(s: &str) -> anyhow::Result<alloy::primitives::Bytes> {
    let s = s.trim_start_matches("0x");
    Ok(alloy::primitives::Bytes::from(hex_decode(s)?))
}

fn hex_decode(s: &str) -> anyhow::Result<Vec<u8>> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(Into::into))
        .collect()
}

#[allow(dead_code)]
fn u256_from_dec(s: &str) -> anyhow::Result<U256> {
    Ok(s.parse::<U256>()?)
}
