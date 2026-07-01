//! POST /simulate — eth_call ile revert/gas tahmini (yan etkisiz).

use axum::{extract::State, response::Json};
use execd_core::types::{Envelope, SimulateRequest, SimulateResult};
use serde_json::Value;

use crate::state::AppState;

pub async fn simulate(
    State(st): State<AppState>,
    Json(req): Json<SimulateRequest>,
) -> Json<Value> {
    let env = match st.0.pool.eth_call_simulate(&req).await {
        Ok(res) => serde_json::to_value(Envelope::ok(res)).unwrap(),
        Err(e) => serde_json::to_value(Envelope::<SimulateResult>::err(
            "SIMULATION_REVERT",
            e.to_string(),
        ))
        .unwrap(),
    };
    Json(env)
}
