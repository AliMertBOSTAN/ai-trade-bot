"""Cüzdan bağlantısı — public adres yönetimi (özel anahtar ASLA UI'a sızmaz).

İki kaynak:
  • signer : WALLET_PRIVATE_KEY tanımlıysa ondan TÜRETİLEN public adres (live imza).
             Özel anahtar burada okunmaz/dönmez; yalnızca adres türetilir.
  • watch  : uygulama içinden bağlanan/izlenen public adres (imza YOK).

Öncelik: signer > watch > yok. Çalışma-zamanı 'connect' bir watch adresi belirler.
"""
from __future__ import annotations

import logging
import os

from engine.config.settings import settings

log = logging.getLogger("wallet")

_watch_address: str | None = None  # uygulama içinden bağlanan izleme adresi


def _derive_signer_address() -> str | None:
    """Public imzalayıcı adresini türetir (anahtarı ASLA döndürmez).

    Öncelik: şifreli keystore (WALLET_KEYSTORE_PATH) → düz-metin WALLET_PRIVATE_KEY.
    """
    try:
        from engine.security import keystore
        addr = keystore.derive_address()
        if addr:
            return addr
    except Exception as e:  # noqa: BLE001
        log.warning("keystore adresi türetilemedi: %s", e)

    pk = settings.wallet_private_key
    if not pk:
        return None
    try:
        from eth_account import Account
        return Account.from_key(pk).address
    except Exception as e:  # noqa: BLE001
        log.warning("imzalayıcı adresi türetilemedi: %s", e)
        return None


def is_valid_address(addr: str) -> bool:
    a = (addr or "").strip()
    return (a.startswith("0x") and len(a) == 42
            and all(c in "0123456789abcdefABCDEF" for c in a[2:]))


def get_wallet() -> dict:
    """Aktif cüzdan: adres + kaynak + imza yeteneği. Özel anahtar İÇERMEZ."""
    signer = _derive_signer_address()
    if signer:
        return {"address": signer, "source": "signer",
                "can_sign": True, "mode": settings.trading_mode}
    watch = _watch_address or (os.getenv("WALLET_ADDRESS", "").strip() or None)
    if watch:
        return {"address": watch, "source": "watch",
                "can_sign": False, "mode": settings.trading_mode}
    return {"address": None, "source": "none",
            "can_sign": False, "mode": settings.trading_mode}


def set_watch_address(addr: str) -> dict:
    """Uygulama içinden public adres bağla/temizle (boş = bağlantıyı kes)."""
    global _watch_address
    a = (addr or "").strip()
    if a and not is_valid_address(a):
        raise ValueError("Geçersiz adres: 0x ile başlayan 40 hane bekleniyor")
    _watch_address = a or None
    return get_wallet()
