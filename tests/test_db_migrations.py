"""storage/db — sema surumleme (PRAGMA user_version) + yedek testleri."""
import glob
import os

from engine.storage import db as db_mod
from engine.storage.db import Store


def test_schema_version_set_on_init(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    assert store.schema_version() == db_mod._SCHEMA_VERSION


def test_reopen_is_idempotent(tmp_path):
    p = str(tmp_path / "t.db")
    Store(p)  # ilk kurulum
    store2 = Store(p)  # yeniden ac -> migrate tekrar calismamali, hata vermemeli
    assert store2.schema_version() == db_mod._SCHEMA_VERSION


def test_backup_creates_file_and_prunes(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    paths = [store.backup(keep=2) for _ in range(4)]
    # son cagri bir dosya yolu dondurmeli ve dosya var olmali
    assert os.path.exists(paths[-1])
    # en fazla 2 yedek kalmali (budama)
    remaining = glob.glob(str(tmp_path / "backups" / "bot-*.db"))
    assert len(remaining) <= 2
