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
    # Maliyet-farkinda giris kapisi: beklenen lehte hareket (edge_atr_mult x ATR)
    # tur maliyetinin (slippage+fee, iki yon) en az min_edge_ratio kati degilse
    # YENI pozisyon acilmaz. 0 = kapali (eski davranis). Onerilen: 2.0
    # Gerekce ve olcumler: docs/BACKTEST_IMPROVEMENTS.md
    min_edge_ratio: float = float(os.getenv("MIN_EDGE_RATIO", "0"))
    edge_atr_mult: float = float(os.getenv("EDGE_ATR_MULT", "3.0"))
    # Piyasa yapisi kapisi: intel bias'i karara TERS ve bu esikten guclu ise
    # YENI pozisyon acilmaz (mevcut pozisyonu KAPATMAYI hicbir zaman engellemez).
    # 0 = kapali. Onerilen 0.6. Intel verisi yoksa kapi otomatik pasiftir.
    intel_block_score: float = float(os.getenv("INTEL_BLOCK_SCORE", "0.6"))


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

    # Sinyal hizalaması: "candles" = sinyaller sabit mum kapanışlarıyla üretilir
    # (backtest ile birebir; önerilen). "ticks" = eski tick-karışımı davranış.
    signal_align: str = os.getenv("SIGNAL_ALIGN", "candles")
    # 4h VARSAYILAN (olcum sonucu): gercek Binance verisiyle 1000 mumluk
    # backtestlerde 1h her esikte ZARAR ederken (BTC -3.3%, ETH -10.0%),
    # 4h esik 0.73'te BTC +3.9% / ETH +0.3% verdi ve ayni donemde al-tut
    # (-7.7% / -6.4%) belirgin sekilde asildi. Olcumler: docs/LIVE_READINESS.md
    signal_interval: str = os.getenv("SIGNAL_INTERVAL", "4h")
    # Otomatik yeniden-optimizasyon periyodu (saat). 0 = kapalı. Örn. 168 = haftalık.
    auto_tune_interval_h: float = float(os.getenv("AUTO_TUNE_INTERVAL_H", "0"))

    llm_provider: str = os.getenv("LLM_PROVIDER", "deepseek")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    # DİKKAT: model adı API'de birebir geçerli olmalı; yanlış ad = her çağrı 404
    # (LLM katmanı sessizce teknik karara düşer). Gerekirse .env ile geçersiz kıl.
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    anthropic_base_url: str = os.getenv("ANTHROPIC_BASE_URL", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    wallet_private_key: str = os.getenv("WALLET_PRIVATE_KEY", "")

    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_secret: str = os.getenv("BINANCE_SECRET", "")

    # --- Piyasa Istihbarati (intel) — hepsi OPSIYONEL ---
    # Anahtar yoksa ilgili panel ucretsiz yedege duser veya "kapali" gorunur;
    # cekirdek akis anahtarsiz calismaya devam eder.
    coinglass_api_key: str = os.getenv("COINGLASS_API_KEY", "")
    cmc_api_key: str = os.getenv("CMC_API_KEY", "")
    nansen_api_key: str = os.getenv("NANSEN_API_KEY", "")
    intel_refresh: bool = os.getenv(
        "INTEL_REFRESH", "1").strip().lower() not in ("0", "false", "no")
    intel_refresh_s: float = float(os.getenv("INTEL_REFRESH_S", "180"))
    intel_signal: bool = os.getenv(
        "INTEL_SIGNAL", "1").strip().lower() not in ("0", "false", "no")

    # --- AI analist (derinlik + otonom tarama) ---
    analyst_depth: str = os.getenv("ANALYST_DEPTH", "normal")
    analyst_auto: bool = os.getenv(
        "ANALYST_AUTO", "0").strip().lower() in ("1", "true", "yes")
    analyst_interval_min: float = float(os.getenv("ANALYST_INTERVAL_MIN", "30"))
    analyst_watchlist: str = os.getenv("ANALYST_WATCHLIST", "")

    # --- Hyperliquid perp masasi (hepsi OPSIYONEL) ---
    # Canli emir icin HEM imzalayici HEM de hl_live=True gerekir.
    hl_live: bool = os.getenv("HL_LIVE", "0").strip().lower() in ("1", "true", "yes")
    hl_testnet: bool = os.getenv(
        "HL_TESTNET", "0").strip().lower() in ("1", "true", "yes")
    hl_account_address: str = os.getenv("HL_ACCOUNT_ADDRESS", "")
    hl_ai_autopilot: bool = os.getenv(
        "HL_AI_AUTOPILOT", "0").strip().lower() in ("1", "true", "yes")

    news_feeds: tuple = field(default_factory=lambda: tuple(
        u.strip() for u in os.getenv("NEWS_FEEDS", "").split(",") if u.strip()
    ))
    # Haber izleyici (news_watcher): NEWS_WATCHER=0 kapatır. Aralık/pencere
    # değerleri izleyici tarafından ÇALIŞMA ANINDA env'den okunur (testlerde
    # değiştirilebilsin diye); buradaki alanlar /config görünürlüğü içindir.
    news_watcher_enabled: bool = os.getenv(
        "NEWS_WATCHER", "1").strip().lower() not in ("0", "false", "no")
    news_poll_interval_s: float = float(os.getenv("NEWS_POLL_INTERVAL_S", "90"))
    news_fresh_window_min: float = float(os.getenv("NEWS_FRESH_WINDOW_MIN", "45"))
    news_llm_assess: bool = os.getenv(
        "NEWS_LLM_ASSESS", "1").strip().lower() not in ("0", "false", "no")

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
        if self.wallet_private_key:
            return
        # Sifreli keystore da gecerli bir imzalayici kaynagidir
        try:
            from engine.security.keystore import load_private_key
            if load_private_key():
                return
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(
            "Live mod icin WALLET_KEYSTORE_PATH(+PASSWORD) veya "
            "WALLET_PRIVATE_KEY gerekli. Guvenli degilse paper modda kalin.")

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
        if self.signal_align not in ("candles", "ticks"):
            errors.append(f"SIGNAL_ALIGN gecersiz: '{self.signal_align}' (candles|ticks)")
        _known_iv = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
        if self.signal_interval not in _known_iv:
            warnings.append(f"SIGNAL_INTERVAL taninmiyor: '{self.signal_interval}' "
                            "-> 1h varsayilir.")
        if self.news_poll_interval_s < 30:
            warnings.append(f"NEWS_POLL_INTERVAL_S cok dusuk ({self.news_poll_interval_s}s) "
                            "-> 30 sn'ye kirpilir (RSS rate-limit korumasi).")
        if self.is_live:
            warnings.append("LIVE MOD: gercek fonla islem yapilabilir.")
        if self.risk.slippage_bps <= 0:
            warnings.append("risk.slippage_bps <= 0 -> slippage korumasi etkisiz.")
        if not (0.0 <= self.risk.intel_block_score <= 1.0):
            errors.append("INTEL_BLOCK_SCORE 0..1 olmali "
                          f"(su an {self.risk.intel_block_score})")
        if self.intel_refresh and self.intel_refresh_s < 60:
            warnings.append(f"INTEL_REFRESH_S cok dusuk ({self.intel_refresh_s}s) "
                            "-> 60 sn'ye kirpilir.")
        if self.analyst_depth not in ("kisa", "normal", "derin", "cok_derin") \
                and not self.analyst_depth.isdigit():
            warnings.append(f"ANALYST_DEPTH taninmiyor: '{self.analyst_depth}' "
                            "-> normal varsayilir.")
        if self.hl_live and not self.hl_account_address \
                and not os.getenv("HL_API_WALLET_KEY"):
            warnings.append("HL_LIVE=1 ama HL imzalayicisi yok -> Hyperliquid "
                            "KAGIT modda kalir (fail-safe).")
        if self.hl_ai_autopilot and self.hl_live:
            warnings.append("HL OTOPILOT + CANLI: AI gercek parayla pozisyon "
                            "acabilir. HL_MAX_*/HL_AI_* tavanlarini gozden gecirin.")
        if self.hl_ai_autopilot and self.llm_provider == "none":
            warnings.append("HL_AI_AUTOPILOT=1 ama LLM kapali -> sezgisel gorusle "
                            "islem ACILMAZ (otopilot etkisiz).")
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
