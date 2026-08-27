"""Canlıya geçiş ÖN-UÇUŞ betiği — terminalden tek komutla tam kontrol.

    python scripts/live_preflight.py                 # tüm etkin zincirler
    python scripts/live_preflight.py --chain 8453    # yalnızca Base
    python scripts/live_preflight.py --usd 50        # rota testi büyüklüğü

HİÇBİR TX GÖNDERMEZ, gas harcamaz. Sadece okur:
  • imzalayıcı cüzdan (keystore veya env) ve adresi
  • zincir başına RPC bağlantısı, canlı gas (gwei) ve gas tavanı
  • cüzdanın stable + native bakiyesi
  • GERÇEK DEX quote'u (USDC -> WETH) + tur maliyeti (bps)
  • risk limitleri, günlük harcama limiti, kill-switch
  • takvim penceresi (yüksek etkili veri yayını yakınsak uyarır)

Çıkış kodu 0 = canlıya hazır, 1 = eksik var (CI/otomasyon uyumlu).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Betik depo kökünden bağımsız çalışsın: proje kökünü import yoluna ekle.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK = "  [OK] "
NO = "  [--] "


def _fmt(v) -> str:
    return "-" if v is None else (f"{v}" if not isinstance(v, float) else f"{v:,.6f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Canlı işlem ön-uçuş kontrolü")
    ap.add_argument("--chain", type=int, default=None,
                    help="yalnızca bu zincir (örn. 8453 = Base)")
    ap.add_argument("--usd", type=float, default=25.0,
                    help="rota testi için sanal emir büyüklüğü (USD)")
    ap.add_argument("--json", action="store_true", help="ham JSON çıktısı")
    args = ap.parse_args()

    from engine.bot.orchestrator import bot
    if args.chain:
        bot.enabled_chains = [args.chain]

    report = bot.live_preflight()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ready") else 1

    print("=" * 68)
    print(" AI TRADE BOT — CANLI ÖN-UÇUŞ KONTROLÜ")
    print("=" * 68)
    print(f"\nCüzdan : {report.get('wallet_address') or '(imzalayıcı YOK)'}")
    print(f"LLM    : {report.get('llm_provider')}")

    print("\n--- Zincirler ---")
    for row in report.get("chains", []):
        mark = OK if row.get("rpc_ok") else NO
        print(f"{mark}{row['name']} ({row['chain_id']})")
        print(f"       gas={_fmt(row.get('gas_gwei'))} gwei "
              f"(tavan içinde: {row.get('gas_ok')})")
        print(f"       {row.get('stable_symbol')}={_fmt(row.get('stable_balance'))} · "
              f"{row.get('native_symbol')}={_fmt(row.get('native_balance'))}")
        q = row.get("quote") or {}
        if q.get("ok"):
            print(f"       rota: {q['pair']} @ {q['dex']} (fee {q.get('fee_tier')}) "
                  f"fiyat={q.get('price')} · gas=${q.get('gas_usd')} · "
                  f"tur maliyeti={q.get('roundtrip_cost_bps')} bps")
        elif q:
            print(f"       rota: HATA — {q.get('error')}")
        if row.get("error"):
            print(f"       hata: {row['error']}")

    print("\n--- Risk limitleri ---")
    for k, v in (report.get("limits") or {}).items():
        print(f"       {k} = {v}")

    # Takvim penceresi bilgisi (bloklayıcı değil, uyarı)
    try:
        from engine.marketdata.calendar import calendar
        calendar.refresh()
        g = calendar.guard()
        nxt = calendar.next_event(min_importance=0.7)
        print("\n--- Veri takvimi ---")
        if nxt:
            print(f"       sıradaki yüksek etkili: {nxt.title} "
                  f"({nxt.to_api()['inHours']:.1f} saat sonra)")
        print(f"       aktif pencere freni: {g or 'yok'}")
    except Exception as e:  # noqa: BLE001
        print(f"\n--- Veri takvimi --- okunamadı: {e}")

    g = report.get("gate") or {}
    if g:
        st = g.get("stats") or {}
        print("\n--- Kanıt kapısı (paper/shadow performansı) ---")
        print(f"       kapanan işlem={st.get('closed_trades')} · "
              f"net PnL=${st.get('net_pnl_usd')} · PF={st.get('profit_factor')} · "
              f"kazanma oranı={st.get('win_rate')} · maxDD=%{st.get('max_drawdown_pct')}")
        for r in g.get("reasons", []):
            print(f"       ! {r}")

    print("\n--- Kontroller ---")
    for k, v in (report.get("checks") or {}).items():
        print(f"{OK if v else NO}{k}")

    ready = bool(report.get("ready"))
    print("\n" + ("SONUÇ: CANLIYA HAZIR ✔" if ready else
                  "SONUÇ: HAZIR DEĞİL — yukarıdaki [--] maddeleri giderin ✘"))
    print("Not: TRADING_MODE=live veya POST /mode {\"mode\":\"live\"} ile geçilir;\n"
          "     bu kontrol geçmeden mod DEĞİŞMEZ (LIVE_FORCE=1 zorlar).")
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
