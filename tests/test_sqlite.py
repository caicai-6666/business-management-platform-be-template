"""使用隔离文件库和正式入口验证 SQLite 基础设施。"""
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.config.sqlite import BACKEND_ROOT, database_path
from app.repository.sqlite import reader, transaction


class SQLiteTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(dir=BACKEND_ROOT / "tests/tmp")
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        settings = patch.dict(os.environ, DATA_DIR=str(self.directory / "source"),
                              SQLITE_FILENAME="test.sqlite3", VECTOR_INDEX_FILENAME="vector.db",
                              DB_ENGINE="sqlite")
        settings.start()
        self.addCleanup(settings.stop)

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, "-B", "-m", "app.database", *args],
                                cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result.stdout

    def version(self):
        with reader() as db:
            return db.execute("PRAGMA user_version").fetchone()[0]

    def test_lifecycle(self):
        path = database_path()
        self.cli("check", success=False)
        self.assertFalse(path.parent.exists())
        self.cli("init")
        with transaction() as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone(), (1,))
            self.assertEqual(db.execute("SELECT name FROM sqlite_schema").fetchall(), [])
            db.execute("PRAGMA user_version=1")
            self.assertEqual(self.version(), 0)
        self.cli("init")
        self.assertIn("journal_mode=wal", self.cli("check"))
        self.assertEqual(self.version(), 1)
        with self.assertRaises(ValueError), transaction() as db:
            db.execute("PRAGMA user_version=2")
            raise ValueError("rollback")
        with reader() as db, self.assertRaises(sqlite3.OperationalError):
            db.execute("PRAGMA user_version=3")
        with transaction():
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"), transaction():
                self.fail("另一个写者取得写锁")
        self.assertEqual(self.version(), 1)

    def test_interrupted_writer(self):
        self.cli("init")
        code = """from app.repository.sqlite import transaction
import os
with transaction() as db:
    db.execute("PRAGMA user_version=9")
    os._exit(17)
"""
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=BACKEND_ROOT, timeout=10)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(self.version(), 0)
        with transaction() as db:
            db.execute("PRAGMA user_version=10")
        self.assertEqual(self.version(), 10)

    def test_backup_and_restore(self):
        self.cli("init")
        with transaction() as db:
            db.execute("PRAGMA user_version=7")
        snapshot = self.directory / "snapshot.db"
        with transaction() as db:
            db.execute("PRAGMA user_version=8")
            self.cli("backup", snapshot)
        self.cli("backup", snapshot, success=False)
        self.assertEqual(self.version(), 8)
        with patch.dict(os.environ, DATA_DIR=str(self.directory), SQLITE_FILENAME=snapshot.name):
            self.cli("check")
            self.cli("init")
            self.assertEqual(self.version(), 7)

    def test_configuration(self):
        for settings in ({"DB_ENGINE": "mysql"}, {"SQLITE_FILENAME": "../other.db"},
                         {"SQLITE_FILENAME": "vector.db"}, {"VECTOR_INDEX_FILENAME": "test.sqlite3-wal"}):
            with self.subTest(settings=settings), patch.dict(os.environ, settings):
                self.cli("init", success=False)
        self.assertFalse(database_path().exists())
        with patch.dict(os.environ, DATA_DIR="data"):
            self.assertEqual(database_path(), BACKEND_ROOT / "data/test.sqlite3")
