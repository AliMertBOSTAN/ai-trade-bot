//! HTTP yüzeyi (axum). Sözleşme: ADR §8. Tüm yanıtlar Envelope.

pub mod arb;
pub mod perp;
pub mod simulate;
pub mod swap;

use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Json},
    routing::{get, post},
    Router,
};
use serde_json::json;

use crate::state::AppState;

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/metrics", get(metrics))
        .route("/simulate", post(simulate::simulate))
        .route("/execute/swap", post(swap::execute_swap))
        .route("/execute/arb", post(arb::execute_arb))
        .route("/execute/perp", post(perp::execute_perp))
        .route("/cancel", post(perp::cancel))
        .route("/nonce/:chain_id", get(nonce))
        .route("/fills", get(perp::fills_ws))
        .with_state(state)
}

async fn health(State(st): State<AppState>) -> impl IntoResponse {
    let chains: serde_json::Map<String, serde_json::Value> = st
        .0
        .pool
        .chain_ids()
        .into_iter()
        .map(|c| {
            (
                c.to_string(),
                json!({
                    "connected": st.0.pool.is_connected(c),
                    "nonce": st.0.nonce.peek(c),
                }),
            )
        })
        .collect();

    Json(json!({
        "ok": true,
        "data": {
            "status": if st.0.safety.kill_switch_on() { "halted" } else { "ok" },
            "version": env!("CARGO_PKG_VERSION"),
            "mode": if st.is_live() { "live" } else { "paper" },
            "signer_loaded": st.0.cfg.signer_loaded(),
            "chains": chains,
        }
    }))
}

async fn metrics(State(st): State<AppState>) -> impl IntoResponse {
    (StatusCode::OK, st.0.metrics.render())
}

async fn nonce(
    State(st): State<AppState>,
    axum::extract::Path(chain_id): axum::extract::Path<u64>,
) -> impl IntoResponse {
    Json(json!({ "ok": true, "data": { "nonce": st.0.nonce.peek(chain_id) } }))
}
