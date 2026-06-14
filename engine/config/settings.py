"""Ortam tabanlı global ayarlar.

Tüm gizli bilgiler (.env) buradan okunur. Hiçbir secret koda gömülmez.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class RiskConfig:
    """İşlem ve sermaye koruma parametreleri (Risk Controls)."""

    max_position_usd: float = 500.0          # tek pozisyonda azami notional
    max_open_positions: int = 5
    max_daily_loss_usd: float = 200.0        # günlük zarar kill-switch
    stop_loss_pct: float = 0.05              # %5
    take_profit_pct: float = 0.10            # %10
    slippage_bps: int = 50                   # 50 bps = %0.5 azami slippage
    max_gas_gwei: float = 80.0               # gas ücreti tavanı
    min_confidence: float = 0.80             # bu skorun altındaki sinyal işlenmez (emin olma eşiği)
    min_arb_net_profit_usd: float = 5.0      # bu kârın altındaki arbitraj atlanır
    use_flashbots: bool = True               # MEV koruması (live + ETH mainnet)


@dataclass(frozen=True)
class Settings:
    trading_mode: str = os.getenv("TRADING_MODE", "paper")  # "paper" | "live"
    poll_interval_ms: int = int(os.getenv("POLL_INTERVAL_MS", "8000"))
    starting_cash_usd: float = float(os.getenv("STARTING_CASH_USD", "10000"))

    llm_provider: str = os.getenv("LLM_PROVIDER", "deepseek")   # deepseek|anthropic|openai|none
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    wallet_private_key: str = os.getenv("WALLET_PRIVATE_KEY", "")

    # Anlık haber akışları (RSS URL'leri, virgülle ayrılır; boşsa varsayılanlar)
    news_feeds: tuple = field(default_factory=lambda: tuple(
        u.strip() for u in os.getenv("NEWS_FEEDS", "").split(",") if u.strip()
    ))

    rpc: dict = field(default_factory=lambda: {
        1: os.getenv("RPC_ETHEREUM", ""),
        42161: os.getenv("RPC_ARBITRUM", ""),
        8453: os.getenv("RPC_BASE", ""),
        10: os.getenv("RPC_OPTIMISM", ""),
        56: os.getenv("RPC_BSC", ""),
        137: os.getenv("RPC_POLYGON", ""),
    })

    risk: RiskConfig = field(default_factory=RiskConfig)

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live"

    def assert_live_ready(self) -> None:
        """Live moda geçmeden önce ön koşulları doğrula (fail-safe)."""
        if not self.wallet_private_key:
            raise RuntimeError(
                "Live mod için WALLET_PRIVATE_KEY gerekli. "
                "Güvenli değilse paper modda kalın."
            )


settings = Settings()
