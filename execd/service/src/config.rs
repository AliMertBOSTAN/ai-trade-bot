//! Yapılandırma — yalnız ortamdan. Özel anahtar SADECE burada okunur (Python görmez).

use std::collections::HashMap;

#[derive(Clone)]
pub struct ChainCfg {
    pub chain_id: u64,
    /// Öncelik sırasına göre RPC URL'leri (çoklu-RPC yarışı + failover).
    pub rpc_urls: Vec<String>,
}

#[derive(Clone)]
pub struct Config {
    pub port: u16,
    pub mode: Mode,
    pub max_gas_gwei: f64,
    #[allow(dead_code)] // ileride auth katmaninda
    pub shared_secret: Option<String>,
    pub chains: HashMap<u64, ChainCfg>,
    /// Cüzdan özel anahtarı (0x...) — yalnız execd süreci. Boşsa live imkânsız.
    pub wallet_key: Option<String>,
    #[allow(dead_code)] // Flashbots kimlik anahtari (relay imzasi)
    pub flashbots_signer_key: Option<String>,
    pub hyperliquid_key: Option<String>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Paper,
    Live,
}

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok().filter(|s| !s.trim().is_empty())
}

/// Bilinen zincirler ve env RPC adları.
const CHAIN_ENVS: &[(u64, &str)] = &[
    (1, "RPC_ETHEREUM"),
    (42161, "RPC_ARBITRUM"),
    (8453, "RPC_BASE"),
    (10, "RPC_OPTIMISM"),
    (56, "RPC_BSC"),
    (137, "RPC_POLYGON"),
];

impl Config {
    pub fn from_env() -> anyhow::Result<Self> {
        dotenvy::dotenv().ok();

        let mode = match env("EXECD_MODE").as_deref() {
            Some("live") => Mode::Live,
            _ => Mode::Paper,
        };

        let mut chains = HashMap::new();
        for (id, var) in CHAIN_ENVS {
            if let Some(raw) = env(var) {
                let urls: Vec<String> =
                    raw.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
                if !urls.is_empty() {
                    chains.insert(*id, ChainCfg { chain_id: *id, rpc_urls: urls });
                }
            }
        }

        let cfg = Config {
            port: env("EXECD_PORT").and_then(|s| s.parse().ok()).unwrap_or(8788),
            mode,
            max_gas_gwei: env("MAX_GAS_GWEI").and_then(|s| s.parse().ok()).unwrap_or(150.0),
            shared_secret: env("EXECD_SHARED_SECRET"),
            chains,
            wallet_key: env("WALLET_KEY"),
            flashbots_signer_key: env("FLASHBOTS_SIGNER_KEY"),
            hyperliquid_key: env("HYPERLIQUID_KEY"),
        };

        // Live mod için ön koşul (fail-fast)
        if cfg.mode == Mode::Live && cfg.wallet_key.is_none() {
            anyhow::bail!("EXECD_MODE=live ama WALLET_KEY yok — paper'da kalın veya anahtar verin");
        }
        Ok(cfg)
    }

    pub fn signer_loaded(&self) -> bool {
        self.wallet_key.is_some()
    }
}
