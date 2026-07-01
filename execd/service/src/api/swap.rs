//! POST /execute/swap — tek DEX swap (v2/v3). Akış: ADR §9.1.

use axum::{extract::State, response::Json};
use execd_core::types::{Envelope, Mode, SwapRequest, SwapResult};
use execd_core::ExecError;
use serde_json::Value;

use crate::state::AppState;

pub async fn execute_swap(
    State(st): State<AppState>,
    Json(req): Json<SwapRequest>,
) -> Json<Value> {
    // 0) idempotency — aynı anahtar görülmüşse önceki sonucu döndür (yan etki yok)
    if let Some(prev) = st.0.idempo.get(&req.idempotency_key) {
        return Json(prev);
    }
    let _t = st.0.metrics.start_swap();

    let result = run(&st, &req).await;
    let env: Value = match result {
        Ok(r) => serde_json::to_value(Envelope::ok(r)).unwrap(),
        Err(e) => {
            st.0.metrics.inc_send_error(e.code().as_str());
            serde_json::to_value(Envelope::<SwapResult>::err(e.code().as_str(), e.to_string()))
                .unwrap()
        }
    };
    // başarıyı cache'le (idempotency)
    if env.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        st.0.idempo.put(req.idempotency_key.clone(), env.clone());
    }
    Json(env)
}

async fn run(st: &AppState, req: &SwapRequest) -> Result<SwapResult, ExecError> {
    let pool = &st.0.pool;

    // 1) ikinci-savunma kapıları
    st.0.safety.check_kill_switch()?;
    let gwei = pool
        .gas_price_gwei(req.chain_id)
        .await
        .map_err(|e| ExecError::RpcUnavailable(e.to_string()))?;
    st.0.safety.check_gas_cap(gwei)?;

    // 2) paper modda zincire DOKUNMA — yalnız simüle et
    if req.mode == Mode::Paper {
        let sim = pool
            .simulate_swap(req)
            .await
            .map_err(|e| ExecError::SimulationRevert(e.to_string()))?;
        st.0.safety.check_min_out(&sim.expected_out, &req.min_out)?;
        return Ok(SwapResult {
            tx_hash: "PAPER".into(),
            effective_price: sim.effective_price,
            gas_used: sim.gas_estimate,
            fee_usd: sim.fee_usd,
            nonce: st.0.nonce.peek(req.chain_id),
            simulated_only: true,
        });
    }

    // 3) live: nonce + calldata + simülasyon + imzala + çoklu-RPC yarışı
    if !st.0.cfg.signer_loaded() {
        return Err(ExecError::Validation("live için imzalayıcı yok".into()));
    }
    let nonce = st.0.nonce.next(req.chain_id);
    let tx = pool
        .build_swap_tx(req, nonce)
        .await
        .map_err(|e| ExecError::Internal(e.to_string()))?;

    // gönderim öncesi simülasyon (revert/min_out)
    let sim = pool
        .simulate_tx(req.chain_id, &tx)
        .await
        .map_err(|e| ExecError::SimulationRevert(e.to_string()))?;
    if let Err(e) = st.0.safety.check_min_out(&sim.expected_out, &req.min_out) {
        st.0.nonce.release(req.chain_id, nonce); // başarısız: nonce'u geri al
        return Err(e);
    }

    match pool.sign_and_send_race(req.chain_id, tx).await {
        Ok(tx_hash) => Ok(SwapResult {
            tx_hash,
            effective_price: sim.effective_price,
            gas_used: sim.gas_estimate,
            fee_usd: sim.fee_usd,
            nonce,
            simulated_only: false,
        }),
        Err(e) => {
            st.0.nonce.release(req.chain_id, nonce);
            Err(ExecError::RpcUnavailable(e.to_string()))
        }
    }
}
