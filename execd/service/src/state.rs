//! Paylaşılan uygulama durumu (axum State). Tüm I/O bileşenleri burada toplanır.

use std::sync::Arc;
use std::time::Duration;

use execd_core::{IdempotencyCache, NonceManager, SafetyGate};

use crate::config::{Config, Mode};
use crate::evm::provider::ProviderPool;
use crate::metrics::Metrics;
use crate::perp::hyperliquid::HyperliquidClient;

#[derive(Clone)]
pub struct AppState(pub Arc<Inner>);

pub struct Inner {
    pub cfg: Config,
    pub pool: ProviderPool,
    pub nonce: NonceManager,
    pub idempo: IdempotencyCache,
    pub safety: SafetyGate,
    pub perp: Option<HyperliquidClient>,
    pub metrics: Metrics,
}

impl AppState {
    pub async fn init(cfg: Config) -> anyhow::Result<Self> {
        let pool = ProviderPool::init(&cfg).await?;

        // Nonce mutabakatı: her zincir için on-chain pending nonce'u oku
        let nonce = NonceManager::new();
        if let Some(addr) = pool.signer_address() {
            for chain_id in pool.chain_ids() {
                if let Ok(n) = pool.tx_count(chain_id, addr).await {
                    nonce.reconcile(chain_id, n);
                }
            }
        }

        let perp = match (&cfg.hyperliquid_key, cfg.mode) {
            (Some(key), _) => Some(HyperliquidClient::new(key.clone())),
            _ => None,
        };

        Ok(AppState(Arc::new(Inner {
            safety: SafetyGate::new(cfg.max_gas_gwei),
            idempo: IdempotencyCache::new(Duration::from_secs(600)),
            nonce,
            pool,
            perp,
            metrics: Metrics::new(),
            cfg,
        })))
    }

    pub fn is_live(&self) -> bool {
        self.0.cfg.mode == Mode::Live
    }
}
