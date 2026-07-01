//! Hyperliquid perp istemcisi: imzalı emir (REST) + dolum akışı (WS).
//!
//! İmzalama şeması Hyperliquid'in EIP-712 tabanlı action imzasıdır; ayrıntılar
//! değişebileceğinden bu modül izole tutulur ve sözleşme testiyle korunur (README).

use axum::extract::ws::{Message, WebSocket};
use execd_core::types::{PerpRequest, PerpResult};
use futures::{SinkExt, StreamExt};

const HL_REST: &str = "https://api.hyperliquid.xyz/exchange";
const HL_WS: &str = "wss://api.hyperliquid.xyz/ws";

#[derive(Clone)]
pub struct HyperliquidClient {
    /// İmzalama anahtarı (yalnız execd). Gerçek imzalama EIP-712 ile yapılır.
    key: String,
    http: reqwest::Client,
}

impl HyperliquidClient {
    pub fn new(key: String) -> Self {
        HyperliquidClient { key, http: reqwest::Client::new() }
    }

    /// İmzalı emir gönderir. İmza üretimi (EIP-712 action hash) üretimde tamamlanır.
    pub async fn place_order(&self, req: &PerpRequest) -> anyhow::Result<PerpResult> {
        let action = serde_json::json!({
            "type": "order",
            "orders": [{
                "coin": req.symbol,
                "is_buy": req.side.eq_ignore_ascii_case("BUY"),
                "sz": req.size,
                "limit_px": req.price,
                "reduce_only": req.reduce_only,
                "tif": req.tif,
            }]
        });
        let signature = self.sign_action(&action)?;
        let body = serde_json::json!({ "action": action, "signature": signature, "nonce": now_ms() });

        let resp: serde_json::Value =
            self.http.post(HL_REST).json(&body).send().await?.json().await?;

        // HL yanıtından order_id/status çıkar (şemaya göre)
        let status = resp
            .get("status")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        let order_id = resp
            .pointer("/response/data/statuses/0/resting/oid")
            .and_then(|v| v.as_u64())
            .map(|o| o.to_string())
            .unwrap_or_default();

        Ok(PerpResult { order_id, status, fill_price: None, fill_size: None })
    }

    pub async fn cancel(&self, order_id: &str) -> anyhow::Result<()> {
        let action = serde_json::json!({ "type": "cancel", "cancels": [{ "oid": order_id }] });
        let signature = self.sign_action(&action)?;
        let body = serde_json::json!({ "action": action, "signature": signature, "nonce": now_ms() });
        self.http.post(HL_REST).json(&body).send().await?;
        Ok(())
    }

    /// Üst-akış (HL) WS dolum bildirimlerini axum soketine (Python) iletir.
    pub async fn stream_fills(&self, mut downstream: WebSocket) {
        let connect = tokio_tungstenite::connect_async(HL_WS).await;
        let Ok((upstream, _)) = connect else {
            let _ = downstream.send(Message::Text("{\"error\":\"hl ws bağlanamadı\"}".into())).await;
            return;
        };
        let (mut up_tx, mut up_rx) = upstream.split();

        // userFills aboneliği
        let sub = serde_json::json!({ "method": "subscribe",
            "subscription": { "type": "userFills", "user": "0x..." } });
        let _ = up_tx.send(tokio_tungstenite::tungstenite::Message::Text(sub.to_string())).await;

        while let Some(Ok(msg)) = up_rx.next().await {
            if let tokio_tungstenite::tungstenite::Message::Text(t) = msg {
                if downstream.send(Message::Text(t)).await.is_err() {
                    break; // Python soketi kapandı
                }
            }
        }
    }

    /// EIP-712 action imzası (yer tutucu — üretimde HL şemasıyla tamamlanır).
    fn sign_action(&self, _action: &serde_json::Value) -> anyhow::Result<serde_json::Value> {
        // Gerçek: keccak(action) -> EIP-712 typed data -> self.key ile imzala -> {r,s,v}
        let _ = &self.key;
        Ok(serde_json::json!({ "r": "0x", "s": "0x", "v": 27 }))
    }
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}
