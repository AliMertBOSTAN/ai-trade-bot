"""Emir-iletim backend soyutlaması (ADR-0001).

`ExecBackend` arayüzü iki uygulamaya sahiptir:
  • PythonExecBackend  — mevcut live/paper broker (varsayılan, değişmez).
  • RustExecBackend     — `execd` Rust servisine HTTP (düşük gecikme sıcak yol).

`select_backend()` EXEC_BACKEND env'ine göre seçer ve FAIL-SAFE uygular: rust
seçili ama execd erişilemez/sağlıksız ise live emir göndermez, paper'a düşer.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from engine.config.settings import settings


class ExecUnavailable(RuntimeError):
    """execd erişilemez/sağlıksız — çağıran fail-safe uygulamalı."""


class ExecBackend(Protocol):
    name: str

    def health(self) -> dict: ...
    def execute_swap(self, *, chain_id: int, dex: str, token_in: str, token_out: str,
                     amount_in: str, min_out: str, recipient: str,
                     deadline_s: int = 60, mode: str = "paper") -> dict: ...
    def execute_arb(self, *, chain_id: int, route: list, min_profit_usd: float,
                    use_flashbots: bool = True, mode: str = "paper") -> dict: ...
    def execute_perp(self, *, symbol: str, side: str, size: float,
                     price: float | None = None, reduce_only: bool = False,
                     tif: str = "Gtc", venue: str = "hyperliquid",
                     mode: str = "paper") -> dict: ...


@dataclass
class RustExecBackend:
    """execd (Rust) servisine HTTP istemcisi. Düşük gecikme sıcak yol."""

    base_url: str = ""
    timeout_s: float = 10.0
    client: httpx.Client | None = None
    name: str = "rust"

    def __post_init__(self) -> None:
        self.base_url = self.base_url or os.getenv("EXECD_URL", "http://127.0.0.1:8788")
        if self.client is None:
            self.client = httpx.Client(base_url=self.base_url, timeout=self.timeout_s)

    # ---- düşük seviye ----
    def _post(self, path: str, payload: dict) -> dict:
        payload.setdefault("idempotency_key", uuid.uuid4().hex)
        try:
            r = self.client.post(path, json=payload)
        except httpx.HTTPError as e:
            raise ExecUnavailable(f"execd erişilemez: {e}") from e
        return self._unwrap(r)

    def _unwrap(self, r: httpx.Response) -> dict:
        if r.status_code >= 500:
            raise ExecUnavailable(f"execd {r.status_code}")
        body = r.json()
        if not body.get("ok"):
            err = body.get("error") or {}
            raise ExecError(err.get("code", "INTERNAL"), err.get("message", "bilinmeyen"))
        return body.get("data") or {}

    # ---- arayüz ----
    def health(self) -> dict:
        try:
            r = self.client.get("/health")
        except httpx.HTTPError as e:
            raise ExecUnavailable(f"execd /health erişilemez: {e}") from e
        return self._unwrap(r)

    def execute_swap(self, *, chain_id: int, dex: str, token_in: str, token_out: str,
                     amount_in: str, min_out: str, recipient: str,
                     deadline_s: int = 60, mode: str = "paper") -> dict:
        return self._post("/execute/swap", {
            "chainId": chain_id, "dex": dex, "token_in": token_in, "token_out": token_out,
            "amount_in": str(amount_in), "min_out": str(min_out), "recipient": recipient,
            "deadline_s": deadline_s, "mode": mode,
        })

    def execute_arb(self, *, chain_id: int, route: list, min_profit_usd: float,
                    use_flashbots: bool = True, mode: str = "paper") -> dict:
        return self._post("/execute/arb", {
            "chainId": chain_id, "route": route, "min_profit_usd": min_profit_usd,
            "use_flashbots": use_flashbots, "mode": mode,
        })

    def execute_perp(self, *, symbol: str, side: str, size: float,
                     price: float | None = None, reduce_only: bool = False,
                     tif: str = "Gtc", venue: str = "hyperliquid",
                     mode: str = "paper") -> dict:
        return self._post("/execute/perp", {
            "venue": venue, "symbol": symbol, "side": side, "size": size,
            "price": price, "reduce_only": reduce_only, "tif": tif, "mode": mode,
        })


class ExecError(RuntimeError):
    """execd iş kuralı hatası (revert/edge/gas vb.) — fail-safe gerektirmez."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass
class PythonExecBackend:
    """Mevcut Python broker yolunun ince sarmalı (varsayılan). Lazy import."""

    name: str = "python"

    def health(self) -> dict:
        return {"status": "ok", "mode": settings.trading_mode, "backend": "python"}

    def execute_swap(self, **kw) -> dict:
        # Mevcut executor/broker yolu burada kullanılır (paper/live).
        raise NotImplementedError("PythonExecBackend mevcut executor'a bağlanır (orchestrator akışı)")

    def execute_arb(self, **kw) -> dict:
        raise NotImplementedError

    def execute_perp(self, **kw) -> dict:
        raise NotImplementedError


def select_backend(*, rust: RustExecBackend | None = None,
                   want_live: bool | None = None) -> tuple[ExecBackend, str]:
    """EXEC_BACKEND + sağlık durumuna göre backend seç (FAIL-SAFE).

    Döner: (backend, effective_mode).  effective_mode: "live"|"paper".
    Kurallar:
      - EXEC_BACKEND != "rust"  -> PythonExecBackend, istenen mod.
      - "rust" seçili ama execd sağlıksız -> PythonExecBackend + PAPER'a düş (fail-safe).
      - "rust" sağlıklı -> RustExecBackend, istenen mod.
    """
    want_live = settings.is_live if want_live is None else want_live
    backend_name = os.getenv("EXEC_BACKEND", "python").strip().lower()

    if backend_name != "rust":
        return PythonExecBackend(), ("live" if want_live else "paper")

    rb = rust or RustExecBackend()
    try:
        h = rb.health()
    except ExecUnavailable:
        # execd yok/sağlıksız -> live'a izin verme, paper'a düş
        return PythonExecBackend(), "paper"

    # sürüm/sinyal kontrolü (major uyumsuzlukta fail-safe)
    if h.get("status") == "halted":
        return PythonExecBackend(), "paper"
    return rb, ("live" if want_live else "paper")
