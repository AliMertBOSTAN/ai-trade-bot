"""Python dataclass modellerinden TypeScript arayüzleri üretir.

Amaç: engine/models.py ile src/shared/types.ts'in elle senkronize tutulması
hatasını ortadan kaldırmak. Bu script dataclass'ları introspect eder ve
`src/shared/types.gen.ts` dosyasını üretir (asdict/to_dict çıktısıyla — yani
snake_case — birebir hizalı).

Kullanım:
    python scripts/gen_types.py            # types.gen.ts'i (yeniden) üret
    python scripts/gen_types.py --check    # üretilen güncel mi? (CI için)

CI'da --check başarısız olursa: birisi models.py'yi değiştirip tipi yeniden
üretmeyi unutmuş demektir. `python scripts/gen_types.py` çalıştırıp commit'le.
"""
from __future__ import annotations

import dataclasses
import sys
import types as _types
import typing
from pathlib import Path

# models'i import edebilmek için proje kökünü path'e ekle
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import models  # noqa: E402

OUT = ROOT / "src" / "shared" / "types.gen.ts"

# Üretilecek dataclass'lar (bağımlılık sırasına göre: önce iç tipler)
EXPORTS = [
    models.TechnicalSnapshot,
    models.PriceQuote,
    models.ArbitrageOpportunity,
    models.TradeSignal,
    models.TradeOrder,
    models.Position,
]

HEADER = """// ============================================================================
// OTOMATİK ÜRETİLDİ — ELLE DÜZENLEME. Kaynak: engine/models.py
// Yeniden üretmek için: python scripts/gen_types.py
// Bu arayüzler Python to_dict()/asdict() (snake_case) çıktısıyla hizalıdır.
// ============================================================================
/* eslint-disable */
"""


def _ts_type(py_type: typing.Any) -> str:
    """Bir Python tip ipucunu TS tipine çevirir."""
    origin = typing.get_origin(py_type)
    args = typing.get_args(py_type)

    # Literal["BUY","SELL",...] -> 'BUY' | 'SELL'
    if origin is typing.Literal:
        return " | ".join(f"'{a}'" for a in args)

    # Optional[X] / X | None -> X | null
    # (typing.Union hem de PEP 604 "X | None" = types.UnionType)
    if origin is typing.Union or origin is getattr(_types, "UnionType", None):
        non_none = [a for a in args if a is not type(None)]
        rendered = " | ".join(_ts_type(a) for a in non_none)
        if type(None) in args:
            return f"{rendered} | null"
        return rendered

    # listeler / tuple'lar -> dizi
    if origin in (list, tuple):
        if args:
            inner = _ts_type(args[0])
            return f"{inner}[]"
        return "unknown[]"

    if origin is dict:
        return "Record<string, unknown>"

    # iç içe dataclass -> arayüz adı
    if dataclasses.is_dataclass(py_type):
        return py_type.__name__

    # ilkel tipler
    if py_type in (int, float):
        return "number"
    if py_type is str:
        return "string"
    if py_type is bool:
        return "boolean"
    if py_type is dict:
        return "Record<string, unknown>"
    if py_type is type(None):
        return "null"

    return "unknown"


def _render_interface(dc: type) -> str:
    hints = typing.get_type_hints(dc)
    fields = dataclasses.fields(dc)
    lines = [f"export interface {dc.__name__} {{"]
    for f in fields:
        ts = _ts_type(hints.get(f.name, f.type))
        # Varsayılanı olan alan JSON'da her zaman bulunur (asdict hepsini yazar),
        # bu yüzden opsiyonel İŞARETLEMİYORUZ — gerçek şekil bu.
        lines.append(f"  {f.name}: {ts}")
    # Position.to_dict() ek "key" alanı üretir
    if dc is models.Position:
        lines.append("  key: string")
    lines.append("}")
    return "\n".join(lines)


def generate() -> str:
    parts = [HEADER]
    for dc in EXPORTS:
        parts.append(_render_interface(dc))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    content = generate()
    check = "--check" in sys.argv
    if check:
        if not OUT.exists():
            print(f"HATA: {OUT} yok. `python scripts/gen_types.py` çalıştır.")
            return 1
        current = OUT.read_text(encoding="utf-8")
        if current != content:
            print("HATA: types.gen.ts güncel değil. "
                  "`python scripts/gen_types.py` çalıştırıp commit'le.")
            return 1
        print("OK: types.gen.ts güncel.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8")
    print(f"Üretildi: {OUT.relative_to(ROOT)} ({len(EXPORTS)} arayüz)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
