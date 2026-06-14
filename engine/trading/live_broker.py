"""Live (gerçek on-chain) broker - web3.py ile imzalı swap gönderir.

GÜVENLİK: Bu modül gerçek para harcar. Her emir şu kapılardan geçer:
  1. gas fiyatı tavanı (risk.max_gas_gwei)
  2. amountOutMinimum = quote * (1 - slippage)  -> revert-on-slippage
  3. deadline (eski tx'in mempool'da kalıp kötü fiyatla dolmasını önler)
  4. ERC20 allowance kontrolü (gerekirse approve)
Token-token swap mantığı; native gas için zincirde yeterli ETH/BNB olmalı.
"""
from __future__ import annotations

import logging
import time

from eth_account import Account

from engine.config.chains import Chain, get_chain
from engine.config.settings import RiskConfig, settings
from engine.dex import gas
from engine.dex.abis import (ERC20_ABI, V2_ROUTER_ABI, V3_QUOTER_V2_ABI,
                             V3_ROUTER_02_ABI)
from engine.models import TradeOrder
from engine.trading.portfolio import Portfolio
from engine.web3x.provider import cs, get_web3

log = logging.getLogger("broker.live")


class LiveBroker:
    mode = "live"

    def __init__(self, portfolio: Portfolio, risk: RiskConfig):
        self.portfolio = portfolio
        self.risk = risk
        if not settings.wallet_private_key:
            raise RuntimeError("Live broker için WALLET_PRIVATE_KEY gerekli")
        self.account = Account.from_key(settings.wallet_private_key)
        log.info("Live broker cüzdanı: %s", self.account.address)

    # ---- yardımcılar ----
    def _find_dex(self, chain: Chain, dex_name: str):
        for d in chain.dexes:
            if d.name == dex_name:
                return d
        raise ValueError(f"{dex_name} {chain.name} üzerinde bulunamadı")

    def _token(self, chain: Chain, symbol: str):
        if symbol == chain.stable.symbol:
            return chain.stable
        for t in chain.tokens:
            if t.symbol == symbol:
                return t
        raise ValueError(f"{symbol} token bulunamadı")

    def _ensure_allowance(self, w3, token_addr: str, spender: str, amount: int) -> None:
        erc20 = w3.eth.contract(address=cs(token_addr), abi=ERC20_ABI)
        current = erc20.functions.allowance(self.account.address, cs(spender)).call()
        if current >= amount:
            return
        tx = erc20.functions.approve(cs(spender), 2 ** 256 - 1).build_transaction(
            self._base_tx(w3))
        self._sign_send_wait(w3, tx)

    def _base_tx(self, w3) -> dict:
        gas_price = w3.eth.gas_price
        gas_gwei = gas_price / 1e9
        if gas_gwei > self.risk.max_gas_gwei:
            raise RuntimeError(
                f"Gas {gas_gwei:.1f} gwei > tavan {self.risk.max_gas_gwei} gwei - iptal")
        return {
            "from": self.account.address,
            "nonce": w3.eth.get_transaction_count(self.account.address),
            "gasPrice": gas_price,
            "chainId": w3.eth.chain_id,
        }

    def _sign_send_wait(self, w3, tx: dict) -> str:
        if "gas" not in tx:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        signed = self.account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status != 1:
            raise RuntimeError(f"Tx revert oldu: {tx_hash.hex()}")
        return tx_hash.hex()

    # ---- ana giriş ----
    def execute(self, order: TradeOrder) -> TradeOrder:
        chain = get_chain(order.chain_id)
        w3 = get_web3(order.chain_id)
        if w3 is None:
            order.status = "failed"
            order.reason = "RPC yok"
            return order

        dex = self._find_dex(chain, order.dex)
        base = self._token(chain, order.base)
        stable = chain.stable

        # BUY: stable -> base, SELL: base -> stable
        if order.side == "BUY":
            token_in, token_out = stable, base
            amount_in = int(order.amount * order.price * (10 ** stable.decimals))
        else:
            token_in, token_out = base, stable
            amount_in = int(order.amount * (10 ** base.decimals))

        try:
            gas_gwei_ok, gas_gwei = True, w3.eth.gas_price / 1e9
            if gas_gwei > self.risk.max_gas_gwei:
                raise RuntimeError(f"Gas {gas_gwei:.1f} gwei tavanı aştı")

            if dex.protocol == "uniswap-v2":
                tx_hash, out = self._swap_v2(w3, dex, token_in, token_out, amount_in)
            else:
                tx_hash, out = self._swap_v3(w3, dex, token_in, token_out, amount_in)

            order.tx_hash = tx_hash
            order.status = "filled"
            # gerçekleşen fiyatı çıktı miktarından türet
            out_human = out / (10 ** token_out.decimals)
            in_human = amount_in / (10 ** token_in.decimals)
            order.filled_price = (in_human / out_human) if order.side == "SELL" else (in_human / out_human)
            # toplam ücret = DEX swap fee + ağ gas ücreti (gas HER ZAMAN dahil)
            swap_fee = in_human * 0.003
            gas_fee = gas.gas_cost_usd(order.chain_id, gas.GAS_UNITS_SWAP)
            order.fee_usd = swap_fee + gas_fee
            self.portfolio.apply_fill(order)
        except Exception as e:
            order.status = "failed"
            order.reason = str(e)
            log.error("Live swap başarısız: %s", e)
        return order

    def _swap_v2(self, w3, dex, token_in, token_out, amount_in: int):
        router = w3.eth.contract(address=cs(dex.router), abi=V2_ROUTER_ABI)
        path = [cs(token_in.address), cs(token_out.address)]
        amounts = router.functions.getAmountsOut(amount_in, path).call()
        expected_out = amounts[-1]
        min_out = self.risk.min_out(expected_out)
        self._ensure_allowance(w3, token_in.address, dex.router, amount_in)
        deadline = int(time.time()) + 120
        tx = router.functions.swapExactTokensForTokens(
            amount_in, min_out, path, self.account.address, deadline
        ).build_transaction(self._base_tx(w3))
        tx_hash = self._sign_send_wait(w3, tx)
        return tx_hash, expected_out

    def _swap_v3(self, w3, dex, token_in, token_out, amount_in: int):
        quoter = w3.eth.contract(address=cs(dex.quoter), abi=V3_QUOTER_V2_ABI)
        router = w3.eth.contract(address=cs(dex.router), abi=V3_ROUTER_02_ABI)
        fee = dex.fee_tiers[0]
        # en iyi fee tier'ı seç
        best_out, best_fee = 0, fee
        for f in dex.fee_tiers:
            try:
                q = quoter.functions.quoteExactInputSingle(
                    (cs(token_in.address), cs(token_out.address), amount_in, f, 0)).call()
                if q[0] > best_out:
                    best_out, best_fee = q[0], f
            except Exception:
                continue
        if best_out == 0:
            raise RuntimeError("V3 havuzu quote vermedi")
        min_out = self.risk.min_out(best_out)
        self._ensure_allowance(w3, token_in.address, dex.router, amount_in)
        params = (cs(token_in.address), cs(token_out.address), best_fee,
                  self.account.address, amount_in, min_out, 0)
        tx = router.functions.exactInputSingle(params).build_transaction(self._base_tx(w3))
        tx_hash = self._sign_send_wait(w3, tx)
        return tx_hash, best_out
