from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database


class DatabaseRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.original_path = database.DB_PATH
        self.original_backups = database.BACKUP_DIR
        database.DB_PATH = root / "autoro.db"
        database.BACKUP_DIR = root / "backups"
        self.addCleanup(setattr, database, "DB_PATH", self.original_path)
        self.addCleanup(setattr, database, "BACKUP_DIR", self.original_backups)

    def test_corrupt_database_is_quarantined_and_restored(self) -> None:
        with closing(sqlite3.connect(database.DB_PATH)) as connection:
            connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
            connection.execute("INSERT INTO sample VALUES ('preserved')")
            connection.commit()

        backup = database.create_daily_backup()
        self.assertIsNotNone(backup)
        database.DB_PATH.write_bytes(b"not a sqlite database")

        self.assertEqual("recovered", database.check_and_recover_database())
        with closing(sqlite3.connect(database.DB_PATH)) as connection:
            self.assertEqual("preserved", connection.execute("SELECT value FROM sample").fetchone()[0])
        self.assertTrue(database.DB_PATH.with_name("autoro.db.corrupt").exists())


if __name__ == "__main__":
    unittest.main()
