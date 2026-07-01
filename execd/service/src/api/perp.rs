//! POST /execute/perp + /cancel + WS /fills — Hyperliquid. Akış: ADR §9.3.

use axum::{
    extract::{State, WebSocketUpgrade},
    response::{IntoResponse, Json},
};
use execd_core::types::{Envelope, Mode, PerpRequest, PerpResult};
use execd_core::ExecError;
use serde_json::{json, Value};

use crate::state::AppState;

pub async fn execute_perp(State(st): State<AppState>, Json(req): Json<PerpRequest>) -> Json<Value> {
    if let Some(prev) = st.0.idempo.get(&req.idempotency_key) {
        return Json(prev);
    }
    let env = match run(&st, &req).await {
        Ok(r) => serde_json::to_value(Envelope::ok(r)).unwrap(),
        Err(e) => serde_json::to_value(Envelope::<PerpResult>::err(
            e.code().as_str(),
            e.to_string(),
        ))
        .unwrap(),
    };
    if env.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        st.0.idempo.put(req.idempotency_key.clone(), env.clone());
    }
    Json(env)
}

async fn run(st: &AppState, req: &PerpRequest) -> Result<PerpResult, ExecError> {
    st.0.safety.check_kill_switch()?;

    let client = st
        .0
        .perp
        .as_ref()
        .ok_or_else(|| ExecError::Validation("perp istemcisi yapılandırılmadı".into()))?;

    if req.mode == Mode::Paper {
        return Ok(PerpResult {
            order_id: "PAPER".into(),
            status: "simulated".into(),
            fill_price: req.price,
            fill_size: Some(req.size),
        });
    }

    client
        .place_order(req)
        .await
        .map_err(|e| ExecError::Internal(e.to_string()))
}

pub async fn cancel(State(st): State<AppState>, Json(body): Json<Value>) -> Json<Value> {
    let order_id = body.get("order_id").and_then(|v| v.as_str()).unwrap_or("");
    match st.0.perp.as_ref() {
        Some(c) => match c.cancel(order_id).await {
            Ok(_) => Json(json!({ "ok": true })),
            Err(e) => Json(json!({ "ok": false, "error": { "code": "INTERNAL", "message": e.to_string() } })),
        },
        None => Json(json!({ "ok": false, "error": { "code": "VALIDATION", "message": "perp yok" } })),
    }
}

/// WS /fills — sunucu, Hyperliquid kullanıcı-dolum akışını Python'a iletir.
pub async fn fills_ws(ws: WebSocketUpgrade, State(st): State<AppState>) -> impl IntoResponse {
    ws.on_upgrade(move |socket| async move {
        if let Some(client) = st.0.perp.as_ref() {
            client.stream_fills(socket).await;
        }
    })
}
