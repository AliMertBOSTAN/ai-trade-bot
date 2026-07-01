//! POST /execute/arb — atomik arbitraj + Flashbots bundle. Akış: ADR §9.2.

use axum::{extract::State, response::Json};
use execd_core::types::{ArbRequest, ArbResult, Envelope, Mode};
use execd_core::ExecError;
use serde_json::Value;

use crate::state::AppState;

pub async fn execute_arb(State(st): State<AppState>, Json(req): Json<ArbRequest>) -> Json<Value> {
    if let Some(prev) = st.0.idempo.get(&req.idempotency_key) {
        return Json(prev);
    }
    let env = match run(&st, &req).await {
        Ok(r) => serde_json::to_value(Envelope::ok(r)).unwrap(),
        Err(e) => {
            st.0.metrics.inc_send_error(e.code().as_str());
            serde_json::to_value(Envelope::<ArbResult>::err(e.code().as_str(), e.to_string()))
                .unwrap()
        }
    };
    if env.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        st.0.idempo.put(req.idempotency_key.clone(), env.clone());
    }
    Json(env)
}

async fn run(st: &AppState, req: &ArbRequest) -> Result<ArbResult, ExecError> {
    let pool = &st.0.pool;
    st.0.safety.check_kill_switch()?;

    // 1) ArbExecutor.execute statik simülasyonu — net kâr tahmini
    let sim = pool
        .simulate_arb(req)
        .await
        .map_err(|e| ExecError::SimulationRevert(e.to_string()))?;
    // ikinci-savunma edge kapısı (on-chain revert-on-no-profit'e ek)
    st.0.safety.check_min_profit(sim.net_profit_usd, req.min_profit_usd)?;

    if req.mode == Mode::Paper {
        return Ok(ArbResult {
            tx_hash: None,
            bundle_hash: None,
            net_profit_usd: sim.net_profit_usd,
            included_block: None,
            simulated_only: true,
        });
    }

    // 2) tx kur (revert-on-no-profit zaten sözleşmede); Flashbots veya normal gönderim
    let nonce = st.0.nonce.next(req.chain_id);
    let tx = pool
        .build_arb_tx(req, nonce)
        .await
        .map_err(|e| ExecError::Internal(e.to_string()))?;

    let res = if req.use_flashbots {
        pool.send_flashbots_bundle(req.chain_id, tx, sim.net_profit_usd).await
    } else {
        pool.sign_and_send_race(req.chain_id, tx)
            .await
            .map(|h| crate::evm::flashbots::BundleOutcome {
                tx_hash: Some(h),
                bundle_hash: None,
                included_block: None,
            })
    };

    match res {
        Ok(out) => Ok(ArbResult {
            tx_hash: out.tx_hash,
            bundle_hash: out.bundle_hash,
            net_profit_usd: sim.net_profit_usd,
            included_block: out.included_block,
            simulated_only: false,
        }),
        Err(e) => {
            st.0.nonce.release(req.chain_id, nonce);
            Err(ExecError::RpcUnavailable(e.to_string()))
        }
    }
}
