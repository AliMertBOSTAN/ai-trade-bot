//! execd — emir-iletim servisi giriş noktası.
//! Yalnız 127.0.0.1'e bağlanır. Özel anahtar bu süreçte tutulur (Python görmez).

mod api;
mod config;
mod evm;
mod metrics;
mod perp;
mod state;

use config::Config;
use state::AppState;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_tracing();

    let cfg = Config::from_env()?;
    let port = cfg.port;
    tracing::info!(
        port,
        live = (matches!(cfg.mode, config::Mode::Live)),
        chains = cfg.chains.len(),
        signer = cfg.signer_loaded(),
        "execd başlatılıyor"
    );

    let state = AppState::init(cfg).await?;
    let app = api::router(state);

    // Güvenlik: yalnız loopback. Dışarı açılmaz.
    let addr = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!(%addr, "dinleniyor");
    axum::serve(listener, app).await?;
    Ok(())
}

fn init_tracing() {
    let filter = EnvFilter::try_from_env("EXECD_LOG").unwrap_or_else(|_| EnvFilter::new("info"));
    tracing_subscriber::registry()
        .with(filter)
        .with(tracing_subscriber::fmt::layer().json())
        .init();
}
