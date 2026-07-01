"""Şifreli keystore'dan özel anahtar yükleme (düz-metin anahtara güvenli alternatif).

Öncelik sırası:
  1) WALLET_KEYSTORE_PATH + WALLET_KEYSTORE_PASSWORD  → şifreli JSON keystore çöz
  2) WALLET_PRIVATE_KEY                                → düz-metin (geri-uyum)
  3) hiçbiri                                           → None (paper mod)

Anahtar ASLA log'lanmaz veya döndürülen sözlüğe konmaz. Yalnızca türetilen
public adres dışarı sızar. Çözme başarısızsa fail-safe: None döner, paper'da kalır.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("security.keystore")


def keystore_configured() -> bool:
    return bool(os.environ.get("WALLET_KEYSTORE_PATH"))


def load_private_key() -> str | None:
    """Özel anahtarı güvenli kaynaktan yükler (varsa). Hata = None."""
    path = os.environ.get("WALLET_KEYSTORE_PATH")
    if path:
        pw = os.environ.get("WALLET_KEYSTORE_PASSWORD")
        if not pw:
            log.warning("WALLET_KEYSTORE_PATH var ama WALLET_KEYSTORE_PASSWORD yok")
            return None
        try:
            from eth_account import Account
            with open(path, encoding="utf-8") as f:
                enc = json.load(f)
            key = Account.decrypt(enc, pw)  # bytes / HexBytes
            hex_key = key.hex()
            if not hex_key.startswith("0x"):
                hex_key = "0x" + hex_key
            return hex_key
        except Exception as e:  # noqa: BLE001
            log.error("keystore çözme başarısız: %s", type(e).__name__)
            return None
    pk = os.environ.get("WALLET_PRIVATE_KEY", "").strip()
    return pk or None


def create_keystore(private_key: str, password: str, out_path: str) -> str:
    """Yardımcı: düz-metin anahtardan şifreli keystore üretir (bir kez, CLI ile).

    Üretimden sonra düz-metin WALLET_PRIVATE_KEY'i ortamdan KALDIRIN.
    """
    from eth_account import Account
    acct = Account.from_key(private_key)
    enc = Account.encrypt(acct.key, password)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(enc, f)
    try:
        os.chmod(out_path, 0o600)
    except Exception:
        pass
    return acct.address


def derive_address() -> str | None:
    """Yüklü anahtardan public adresi türetir (anahtarı sızdırmadan)."""
    pk = load_private_key()
    if not pk:
        return None
    try:
        from eth_account import Account
        return Account.from_key(pk).address
    except Exception:
        return None
