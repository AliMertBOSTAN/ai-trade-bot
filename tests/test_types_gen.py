"""types.gen.ts'in models.py ile senkron olduğunu doğrular (drift koruması)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_generated_types_are_up_to_date():
    """`python scripts/gen_types.py --check` başarılı olmalı.

    Başarısızsa: models.py değişmiş ama types.gen.ts yeniden üretilmemiş demektir.
    Düzeltmek için: python scripts/gen_types.py
    """
    result = subprocess.run(
        [sys.executable, "scripts/gen_types.py", "--check"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "types.gen.ts güncel değil. `python scripts/gen_types.py` çalıştır.\n"
        + result.stdout + result.stderr
    )
