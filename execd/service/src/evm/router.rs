//! Uniswap v2/v3 calldata kurma + swap simülasyonu.
//! ABI'ler alloy `sol!` makrosuyla tip-güvenli üretilir.

use alloy::primitives::{Address, U256};
use alloy::providers::Provider;

use super::HttpProvider;
use alloy::rpc::types::TransactionRequest;
use alloy::network::TransactionBuilder;
use alloy::sol;
use alloy::sol_types::SolCall;

use execd_core::types::SwapRequest;
use super::SimOut;

sol! {
    // Uniswap V2 Router
    function swapExactTokensForTokens(
        uint256 amountIn, uint256 amountOutMin, address[] path,
        address to, uint256 deadline
    ) external returns (uint256[] amounts);

    // Uniswap V3 SwapRouter (exactInputSingle)
    struct ExactInputSingleParams {
        address tokenIn; address tokenOut; uint24 fee; address recipient;
        uint256 deadline; uint256 amountIn; uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }
    function exactInputSingle(ExactInputSingleParams params) external returns (uint256 amountOut);
}

fn router_address(dex: &str, chain_id: u64) -> anyhow::Result<Address> {
    // Üretimde: engine/config/chains.py'deki router adresleriyle senkronize bir tablo.
    // Burada yer tutucu; gerçek adresler config'ten beslenmelidir.
    let _ = (dex, chain_id);
    anyhow::bail!("router adresi config'ten gelmeli (chains tablosu ile senkronize edin)")
}

fn now_deadline(deadline_s: u64) -> U256 {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    U256::from(now + deadline_s)
}

pub fn build_swap_tx(req: &SwapRequest, nonce: u64, from: Address) -> anyhow::Result<TransactionRequest> {
    let amount_in: U256 = req.amount_in.parse()?;
    let min_out: U256 = req.min_out.parse()?;
    let token_in: Address = req.token_in.parse()?;
    let token_out: Address = req.token_out.parse()?;
    let recipient: Address = req.recipient.parse()?;
    let router = router_address(&req.dex, req.chain_id)?;

    let calldata = if req.dex.contains("v3") {
        let params = ExactInputSingleParams {
            tokenIn: token_in,
            tokenOut: token_out,
            fee: alloy::primitives::aliases::U24::from(3000u32), // %0.3 havuz
            recipient,
            deadline: now_deadline(req.deadline_s),
            amountIn: amount_in,
            amountOutMinimum: min_out,
            sqrtPriceLimitX96: U256::ZERO.to::<alloy::primitives::U160>(),
        };
        exactInputSingleCall { params }.abi_encode()
    } else {
        swapExactTokensForTokensCall {
            amountIn: amount_in,
            amountOutMin: min_out,
            path: vec![token_in, token_out],
            to: recipient,
            deadline: now_deadline(req.deadline_s),
        }
        .abi_encode()
    };

    Ok(TransactionRequest::default()
        .with_from(from)
        .with_to(router)
        .with_input(calldata)
        .with_nonce(nonce)
        .with_chain_id(req.chain_id))
}

/// Paper simülasyonu: eth_call ile beklenen çıktıyı tahmin et.
pub async fn simulate_swap(provider: &HttpProvider, req: &SwapRequest) -> anyhow::Result<SimOut> {
    // Üretimde: router.getAmountsOut / quoter.quoteExactInputSingle çağrısı.
    // Burada minimal: gas tahmini + kaba effective_price; gerçek quote entegrasyonu README'de.
    let from = req.recipient.parse::<Address>()?;
    let tx = build_swap_tx(req, 0, from)?;
    let gas = provider.estimate_gas(&tx).await.unwrap_or(150_000);
    let amount_in: f64 = req.amount_in.parse().unwrap_or(0.0);
    let min_out: f64 = req.min_out.parse().unwrap_or(0.0);
    let effective_price = if min_out > 0.0 { amount_in / min_out } else { 0.0 };
    Ok(SimOut {
        expected_out: req.min_out.clone(), // konservatif: en az min_out
        effective_price,
        gas_estimate: gas as u64,
        fee_usd: 0.0, // gas→usd dönüşümü provider tarafında
    })
}

pub async fn simulate_tx(provider: &HttpProvider, tx: &TransactionRequest) -> anyhow::Result<SimOut> {
    let gas = provider.estimate_gas(tx).await?;
    Ok(SimOut { expected_out: "0".into(), effective_price: 0.0, gas_estimate: gas as u64, fee_usd: 0.0 })
}
