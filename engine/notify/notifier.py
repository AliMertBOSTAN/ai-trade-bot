"""Çok-kanallı bildirim — anahtarsız çalışır (fail-safe).

Etkin kanallar ortam değişkenlerinden okunur:
  - Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  - Discord:  DISCORD_WEBHOOK_URL
  - Masaüstü: NOTIFY_DESKTOP=1 (yerel; başlıksız ortamda yoksayılır)
Hiçbiri yoksa mesaj yalnızca log'a yazılır. Hiçbir bildirim hatası ana akışı
KESMEZ (her gönderim try/except ile sarılıdır).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger("notify")

_TIMEOUT = 8.0


def channels_enabled() -> list[str]:
    out = []
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        out.append("telegram")
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        out.append("discord")
    if os.environ.get("NOTIFY_DESKTOP") == "1":
        out.append("desktop")
    return out


def _post_json(url: str, payload: dict) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return 200 <= r.status < 300


def _send_telegram(message: str) -> bool:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat, "text": message}).encode()
    with urllib.request.urlopen(url, data=body, timeout=_TIMEOUT) as r:
        return 200 <= r.status < 300


def _send_discord(message: str) -> bool:
    return _post_json(os.environ["DISCORD_WEBHOOK_URL"], {"content": message})


def _send_desktop(message: str) -> bool:
    """En iyi çaba: notify-send (Linux) varsa kullan; yoksa False."""
    try:
        import shutil
        import subprocess
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "ai-trade-bot", message], timeout=5)
            return True
    except Exception:
        pass
    return False


def notify(message: str, level: str = "info") -> dict:
    """Mesajı etkin tüm kanallara gönderir. Döner: {kanal: başarı_bool}.

    Hiç kanal yoksa log'a yazar. Hata fırlatmaz.
    """
    prefix = {"info": "ℹ️", "warn": "⚠️", "error": "🔴", "trade": "💱"}.get(level, "")
    text = f"{prefix} {message}".strip()

    results: dict[str, bool] = {}
    enabled = channels_enabled()
    if not enabled:
        log.info("[notify:%s] %s", level, message)
        return {"log": True}

    senders = {"telegram": _send_telegram, "discord": _send_discord,
               "desktop": _send_desktop}
    for ch in enabled:
        try:
            results[ch] = bool(senders[ch](text))
        except Exception as e:  # noqa: BLE001
            log.warning("notify %s hata: %s", ch, e)
            results[ch] = False
    # Hiçbiri başaramazsa log'a da düş
    if not any(results.values()):
        log.info("[notify:%s] %s", level, message)
    return results
