#!/usr/bin/env python3
"""Genel test mekanizması — TÜM katmanları tek komutla doğrular.

Çalıştır:
    python scripts/check_all.py            # tam kontrol
    python scripts/check_all.py --fast     # Rust service derlemesini atla (yavaş)
    python scripts/check_all.py --no-rust  # tüm Rust adımlarını atla
    python scripts/check_all.py --no-js    # TS/JS adımlarını atla

Katmanlar: Python testleri + import smoke + lint, TS typecheck + tip-üretim
tutarlılığı, Rust core test + clippy + service derleme, sentetik backtest smoke.
Eksik araç (cargo/npx/ruff) varsa o adım SKIP olur; zorunlu adım başarısızsa
çıkış kodu 1 olur (CI için).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Pytest'in eth plugin'i ortama göre kırılabilir; güvenli env.
PYTEST_ENV = dict(os.environ, DATA_DIR=os.environ.get("DATA_DIR", "/tmp/atb_check"))


class Result:
    def __init__(self, name: str, status: str, secs: float, detail: str = ""):
        self.name = name
        self.status = status  # PASS / FAIL / SKIP
        self.secs = secs
        self.detail = detail


def run(name: str, cmd: list[str], required: bool = True,
        cwd: str | None = None, env: dict | None = None,
        timeout: int = 1800) -> Result:
    print(f"\n=== {name} ===\n$ {' '.join(cmd)}", flush=True)
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd or ROOT, env=env or os.environ,
                           timeout=timeout)
        secs = time.time() - t0
        ok = p.returncode == 0
        status = "PASS" if ok else ("FAIL" if required else "WARN")
        return Result(name, status, secs,
                      "" if ok else f"çıkış kodu {p.returncode}")
    except FileNotFoundError:
        return Result(name, "SKIP", time.time() - t0, "araç yok")
    except subprocess.TimeoutExpired:
        return Result(name, "FAIL" if required else "WARN",
                      time.time() - t0, "zaman aşımı")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="Rust service derlemesini atla")
    ap.add_argument("--no-rust", action="store_true")
    ap.add_argument("--no-js", action="store_true")
    args = ap.parse_args()

    py = sys.executable
    results: list[Result] = []

    # 1) Python birim testleri
    results.append(run(
        "Python pytest",
        [py, "-W", "ignore", "-B", "-m", "pytest", "tests/", "-q",
         "-p", "no:cacheprovider", "-p", "no:pytest_ethereum"],
        env=PYTEST_ENV))

    # 2) Python import smoke (kritik modüller yüklenebiliyor mu)
    smoke = ("import importlib;"
             "[importlib.import_module(m) for m in ["
             "'engine.signals.engine','engine.ml.model','engine.tuning.optimizer',"
             "'engine.marketdata.derivatives','engine.marketdata.onchain',"
             "'engine.trading.smart_exec','engine.notify.notifier',"
             "'engine.notify.summary','engine.security.keystore',"
             "'engine.security.spending','engine.bot.orchestrator',"
             "'engine.trading.wallet']];print('import smoke OK')")
    results.append(run("Python import smoke", [py, "-W", "ignore", "-B", "-c", smoke],
                       env=PYTEST_ENV))

    # 3) Python lint (ruff) — opsiyonel
    if shutil.which("ruff"):
        results.append(run("Python ruff", ["ruff", "check", "engine/"],
                           required=False))
    else:
        results.append(Result("Python ruff", "SKIP", 0.0, "ruff yok"))

    # 4) Sentetik backtest smoke (gerçek veri/ağ gerektirmez)
    bt = (
        "import random;from engine.config.settings import RiskConfig;"
        "from engine.strategy.manager import StrategyManager;"
        "from engine.backtest.multi_backtest import run_multi_backtest;"
        "import engine.strategy.strategies as _s;"
        "rng=random.Random(1);p=100.0;c=[]\n"
        "for i in range(300):\n"
        "    p=max(1.0,p+0.2+rng.uniform(-1,1));"
        "c.append({'t':i*3600000,'open':p,'high':p*1.01,'low':p*0.99,'close':p,'volume':1000})\n"
        "m=StrategyManager();r=run_multi_backtest(c,'ETH','USD',10000,m,RiskConfig());"
        "assert 'total_return_pct' in r;print('backtest smoke OK', round(r['total_return_pct'],2),'%')")
    results.append(run("Backtest smoke (sentetik)", [py, "-W", "ignore", "-B", "-c", bt],
                       env=PYTEST_ENV))

    # 5) TypeScript
    if not args.no_js:
        npx = shutil.which("npx")
        if npx:
            results.append(run("TS typecheck", [npx, "tsc", "--noEmit",
                                                "-p", "tsconfig.json"]))
            # tip-üretim tutarlılığı: gen_types çalışıyor mu (diff kontrolü ağır, sadece koşturma)
            results.append(run("TS tip-üretim", [py, "scripts/gen_types.py"],
                               required=False))
        else:
            results.append(Result("TS typecheck", "SKIP", 0.0, "npx yok"))

    # 6) Rust
    if not args.no_rust:
        cargo = shutil.which("cargo")
        if cargo:
            ex = os.path.join(ROOT, "execd")
            results.append(run("Rust core test", [cargo, "test", "-p", "execd-core"],
                               cwd=ex))
            results.append(run("Rust core clippy",
                               [cargo, "clippy", "-p", "execd-core", "--",
                                "-D", "warnings"], cwd=ex, required=False))
            if not args.fast:
                results.append(run("Rust service derleme",
                                   [cargo, "check", "-p", "execd"], cwd=ex))
            else:
                results.append(Result("Rust service derleme", "SKIP", 0.0, "--fast"))
        else:
            results.append(Result("Rust", "SKIP", 0.0, "cargo yok"))

    # ---- özet ----
    print("\n" + "=" * 60)
    print("GENEL KONTROL ÖZETİ")
    print("=" * 60)
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "–", "WARN": "!"}
    failed = 0
    for r in results:
        print(f"  {icon.get(r.status, '?')} {r.name:<28} {r.status:<5} "
              f"{r.secs:6.1f}s {r.detail}")
        if r.status == "FAIL":
            failed += 1
    print("=" * 60)
    if failed:
        print(f"SONUÇ: {failed} ZORUNLU ADIM BAŞARISIZ")
        return 1
    print("SONUÇ: TÜM ZORUNLU ADIMLAR GEÇTI ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
