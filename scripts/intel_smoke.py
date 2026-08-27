"""Intel sağlayıcılarını CANLI uçlara karşı dener (ağ gerektirir).

Kullanım:
    python scripts/intel_smoke.py              # tüm paneller
    python scripts/intel_smoke.py macro        # tek grup (macro|onchain|hl)
    python scripts/intel_smoke.py --panel etf  # tek panel

Çıktı: her panel için ok/süre/kaynak ve varsa gerekçe. Bir panelin ok=False
olması botu etkilemez (fail-safe); bu betik yalnızca hangi kaynağın erişilebilir
olduğunu görmek içindir. Örneğin Binance bazı ülkelerden HTTP 451 döner ve
smart-money vekili kapanır — bu beklenen bir durumdur.
"""
from __future__ import annotations

import sys
import time

from engine.marketdata.intel import PANELS, panel, sources
from engine.marketdata.intel import bias as bias_mod


def main() -> int:
    args = sys.argv[1:]
    only_panel = None
    group = None
    if "--panel" in args:
        only_panel = args[args.index("--panel") + 1]
    elif args and args[0] in ("macro", "onchain", "hl"):
        group = args[0]

    names = ([only_panel] if only_panel else
             [n for n, e in PANELS.items() if group is None or e[2] == group])

    print(f"{'PANEL':22s} {'OK':5s} {'SÜRE':>7s}  DETAY")
    print("-" * 96)
    bad = 0
    for n in names:
        t0 = time.time()
        d = panel(n)
        ok = d.get("ok")
        detail = (d.get("reason") or d.get("error") or
                  d.get("note") or (f"src={d['source']}" if d.get("source") else ""))
        rows = d.get("rows")
        if isinstance(rows, list) and rows and not detail:
            detail = f"{len(rows)} satır"
        if not ok:
            bad += 1
        print(f"{n:22s} {str(ok):5s} {time.time() - t0:6.1f}s  {str(detail)[:66]}")

    print("-" * 96)
    src = sources()
    on = [k for k, v in src["providers"].items() if v["enabled"]]
    off = [f"{k}({v.get('env')})" for k, v in src["providers"].items()
           if not v["enabled"]]
    print("Açık kaynaklar :", ", ".join(on))
    if off:
        print("Kapalı (anahtar):", ", ".join(off))

    b = bias_mod.market_bias()
    print(f"\nPiyasa yapısı bias: {b['score']:+.3f} ({b['label']}) — "
          f"{b.get('available', 0)} bileşen")
    for c in b.get("components", []):
        print(f"   {c['name']:14s} {c['score']:+.2f}  {c['detail'][:64]}")
    print(f"\n{len(names) - bad}/{len(names)} panel dolu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
