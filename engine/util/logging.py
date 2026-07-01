"""Merkezi, yapılandırılmış loglama kurulumu.

- Seviye ortamdan (LOG_LEVEL: DEBUG/INFO/WARNING/ERROR; varsayılan INFO).
- Zaman damgalı, modül adlı tutarlı format.
- İsteğe bağlı dosyaya yazım (LOG_FILE=1): data/logs/engine.log, döner (rotating).
İki kez çağrılırsa tekrar handler eklemez (idempotent).
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_CONFIGURED = False

_FMT = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _data_dir() -> str:
    return os.environ.get("DATA_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


def setup_logging() -> None:
    """Kök logger'ı yapılandırır (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    # Konsol handler
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # İsteğe bağlı dosya handler (döner: 2MB x 5 dosya)
    if os.getenv("LOG_FILE", "").strip() in ("1", "true", "yes"):
        try:
            log_dir = os.path.join(_data_dir(), "logs")
            os.makedirs(log_dir, exist_ok=True)
            fh = RotatingFileHandler(
                os.path.join(log_dir, "engine.log"),
                maxBytes=2_000_000, backupCount=5, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
            logging.getLogger("engine.util").info("dosya log'u açık: %s", log_dir)
        except Exception as e:  # noqa: BLE001
            logging.getLogger("engine.util").warning("dosya log'u açılamadı: %s", e)

    # Gürültülü 3. taraf logger'ları biraz kıs
    for noisy in ("urllib3", "web3", "websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    _CONFIGURED = True
