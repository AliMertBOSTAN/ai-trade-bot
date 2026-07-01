//! ArbExecutor.sol köprüsü: atomik arbitraj çağrısı + statik simülasyon.
//! revert-on-no-profit on-chain'de; burada ek olarak `eth_call` ile ön-simülasyon.

use alloy::primitives::{Address, U256};
use alloy::providers::Provider;

use super::HttpProvider;
use alloy::rpc::types::TransactionRequest;
use alloy::network::TransactionBuilder;
use alloy::sol;
use alloy::sol_types::SolCall;

use execd_core::types::ArbRequest;
use super::ArbSim;

sol! {
    // contracts/ArbExecutor.sol ile hizalı (örnek imza; gerçek ABI'ye göre güncelle).
    function execute(bytes route, uint256 minProfit) external returns (uint256 profit);
}

fn arb_executor_address(chain_id: u64) -> anyhow::Result<Address> {
    // Üretimde: deploy edilmiş ArbExecutor adresi (config/env).
    let _ = chain_id;
    anyhow::bail!("ArbExecutor adresi env'den gelmeli (EXECD_ARB_EXECUTOR_<chain>)")
}

fn encode_route(req: &ArbRequest) -> alloy::primitives::Bytes {
    // Rota JSON'unu sözleşmenin beklediği baytlara çevir (üretimde şemaya göre ABI-encode).
    let raw = serde_json::to_vec(&req.route).unwrap_or_default();
    alloy::primitives::Bytes::from(raw)
}

pub fn build_arb_tx(req: &ArbRequest, nonce: u64, from: Address) -> anyhow::Result<TransactionRequest> {
    let to = arb_executor_address(req.chain_id)?;
    let min_profit = U256::from((req.min_profit_usd.max(0.0) * 1e6) as u128); // 6 ondalık varsayım
    let calldata = executeCall { route: encode_route(req), minProfit: min_profit }.abi_encode();
    Ok(TransactionRequest::default()
        .with_from(from)
        .with_to(to)
        .with_input(calldata)
        .with_nonce(nonce)
        .with_chain_id(req.chain_id))
}

/// Statik simülasyon (eth_call) ile net kâr tahmini.
pub async fn simulate_arb(provider: &HttpProvider, req: &ArbRequest) -> anyhow::Result<ArbSim> {
    let from = Address::ZERO; // simülasyon için herhangi
    let tx = build_arb_tx(req, 0, from)?;
    match provider.call(&tx).await {
        Ok(out) => {
            // dönüş `profit` (6 ondalık) -> usd
            let profit = if out.len() >= 32 {
                let bytes: [u8; 32] = out[..32].try_into().unwrap_or([0u8; 32]);
                U256::from_be_bytes(bytes)
            } else {
                U256::ZERO
            };
            let usd = (profit.to::<u128>() as f64) / 1e6;
            Ok(ArbSim { net_profit_usd: usd })
        }
        Err(e) => anyhow::bail!("arb simülasyonu revert: {e}"),
    }
}
