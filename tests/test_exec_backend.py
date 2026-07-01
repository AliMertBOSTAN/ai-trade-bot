"""exec_backend — RustExecBackend (httpx mock) + fail-safe select_backend."""
import json

import httpx
import pytest

from engine.trading.exec_backend import (
    ExecError, ExecUnavailable, PythonExecBackend, RustExecBackend, select_backend,
)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x")


def test_execute_swap_builds_payload_and_parses():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True, "data": {
            "tx_hash": "0xabc", "effective_price": 3350.0, "gas_used": 142000,
            "fee_usd": 0.42, "nonce": 7, "simulated_only": False}})

    rb = RustExecBackend(client=_client(handler))
    out = rb.execute_swap(chain_id=42161, dex="uniswap-v3", token_in="0xA",
                          token_out="0xB", amount_in="1000000000", min_out="5",
                          recipient="0xC", mode="live")
    assert seen["path"] == "/execute/swap"
    assert seen["body"]["chainId"] == 42161
    assert "idempotency_key" in seen["body"]  # otomatik eklenir
    assert out["tx_hash"] == "0xabc"


def test_business_error_raises_exec_error():
    def handler(req):
        return httpx.Response(200, json={"ok": False, "error": {
            "code": "SIMULATION_REVERT", "message": "STF"}})
    rb = RustExecBackend(client=_client(handler))
    with pytest.raises(ExecError) as ei:
        rb.execute_swap(chain_id=1, dex="x", token_in="a", token_out="b",
                        amount_in="1", min_out="1", recipient="c")
    assert ei.value.code == "SIMULATION_REVERT"


def test_server_5xx_raises_unavailable():
    def handler(req):
        return httpx.Response(503, text="down")
    rb = RustExecBackend(client=_client(handler))
    with pytest.raises(ExecUnavailable):
        rb.health()


def test_connection_error_raises_unavailable():
    def handler(req):
        raise httpx.ConnectError("refused")
    rb = RustExecBackend(client=_client(handler))
    with pytest.raises(ExecUnavailable):
        rb.health()


def test_select_backend_default_python(monkeypatch):
    monkeypatch.delenv("EXEC_BACKEND", raising=False)
    be, mode = select_backend(want_live=True)
    assert isinstance(be, PythonExecBackend)
    assert mode == "live"


def test_select_backend_rust_healthy(monkeypatch):
    monkeypatch.setenv("EXEC_BACKEND", "rust")

    def handler(req):
        return httpx.Response(200, json={"ok": True, "data": {"status": "ok"}})
    rb = RustExecBackend(client=_client(handler))
    be, mode = select_backend(rust=rb, want_live=True)
    assert be is rb and mode == "live"


def test_select_backend_failsafe_to_paper(monkeypatch):
    monkeypatch.setenv("EXEC_BACKEND", "rust")

    def handler(req):
        raise httpx.ConnectError("execd yok")
    rb = RustExecBackend(client=_client(handler))
    be, mode = select_backend(rust=rb, want_live=True)
    assert isinstance(be, PythonExecBackend)  # fail-safe
    assert mode == "paper"                      # live engellendi


def test_select_backend_halted_to_paper(monkeypatch):
    monkeypatch.setenv("EXEC_BACKEND", "rust")

    def handler(req):
        return httpx.Response(200, json={"ok": True, "data": {"status": "halted"}})
    rb = RustExecBackend(client=_client(handler))
    be, mode = select_backend(rust=rb, want_live=True)
    assert isinstance(be, PythonExecBackend) and mode == "paper"
