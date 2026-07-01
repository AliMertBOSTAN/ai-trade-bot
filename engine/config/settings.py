"""Ortam tabanli global ayarlar.

Tum gizli bilgiler (.env) buradan okunur. Hicbir secret koda gomulmez.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class RiskConfig:
    """Islem ve sermaye koruma parametreleri (Risk Controls)."""

    max_position_usd: float = float(os.getenv("MAX_POSITION_USD", "500"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
    max_daily_loss_usd: float = 200.0
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    slippage_bps: int = 50
    max_gas_gwei: float = float(os.getenv("MAX_GAS_GWEI", "80"))
    # Emin olma esigi — .env: MIN_CONFIDENCE (0..1). Altindaki sinyale islem acilmaz.
    min_confidence: float = float(os.getenv("MIN_CONFIDENCE", "0.73"))
    min_arb_net_profit_usd: float = 5.0
    use_flashbots: bool = True


@dataclass(frozen=True)
class Settings:
    trading_mode: str = os.getenv("TRADING_MODE", "paper")
    poll_interval_ms: int = int(os.getenv("POLL_INTERVAL_MS", "8000"))
    starting_cash_usd: float = float(os.getenv("STARTING_CASH_USD", "10000"))
    # Paper modu tohumlama: taze başlangıçta portföy bu USD değerinde
    # PAPER_SEED_ASSET (varsayılan ETH) ile başlar. 0 = devre dışı (nakit başlar).
    paper_seed_usd: float = float(os.getenv("PAPER_SEED_USD", "100"))
    paper_seed_asset: str = os.getenv("PAPER_SEED_ASSET", "WETH")
    paper_seed_chain: int = int(os.getenv("PAPER_SEED_CHAIN", "1"))

    llm_provider: str = os.getenv("LLM_PROVIDER", "deepseek")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    anthropic_base_url: str = os.getenv("ANTHROPIC_BASE_URL", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    wallet_private_key: str = os.getenv("WALLET_PRIVATE_KEY", "")

    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_secret: str = os.getenv("BINANCE_SECRET", "")

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
        if not self.wallet_private_key:
            raise RuntimeError(
                "Live mod icin WALLET_PRIVATE_KEY gerekli. Guvenli degilse paper modda kalin.")

    def validate(self) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        if self.trading_mode not in ("paper", "live"):
            errors.append(f"TRADING_MODE gecersiz: '{self.trading_mode}' (paper|live olmali)")
        known_llm = ("deepseek", "anthropic", "openai", "none")
        if self.llm_provider not in known_llm:
            errors.append(f"LLM_PROVIDER gecersiz: '{self.llm_provider}' ({'|'.join(known_llm)})")
        if self.starting_cash_usd <= 0:
            errors.append(f"STARTING_CASH_USD pozitif olmali (su an {self.starting_cash_usd})")
        if not (0.0 <= self.risk.min_confidence <= 1.0):
            errors.append(f"risk.min_confidence 0..1 olmali (su an {self.risk.min_confidence})")
        if self.is_live and not self.wallet_private_key:
            errors.append("Live mod acik ama WALLET_PRIVATE_KEY yok.")
        key_map = {"deepseek": self.deepseek_api_key,
                   "anthropic": self.anthropic_api_key,
                   "openai": self.openai_api_key}
        if self.llm_provider in key_map and not key_map[self.llm_provider]:
            warnings.append(f"LLM_PROVIDER='{self.llm_provider}' ama API anahtari bos -> "
                            "LLM atlanir, saf teknik+haber karari kullanilir.")
        if self.poll_interval_ms < 1000:
            warnings.append(f"POLL_INTERVAL_MS cok dusuk ({self.poll_interval_ms}ms).")
        if self.is_live:
            warnings.append("LIVE MOD: gercek fonla islem yapilabilir.")
        if self.risk.slippage_bps <= 0:
            warnings.append("risk.slippage_bps <= 0 -> slippage korumasi etkisiz.")
        return errors, warnings

    def validate_or_raise(self) -> None:
        import logging
        log = logging.getLogger("config")
        errors, warnings = self.validate()
        for w in warnings:
            log.warning("config: %s", w)
        if errors:
            raise RuntimeError("Yapilandirma hatasi (baslatma durduruldu):\n  - "
                               + "\n  - ".join(errors))


settings = Settings()
