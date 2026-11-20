"""SQLite 主库的连接、事务和一致性备份。"""
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config.sqlite import database_path


@contextmanager
def _connection(mode, *, vector=False):
    path = database_path(vector=vector)
    if mode == "rwc":
        path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True,
                                 isolation_level=None, timeout=5)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        if vector:
            import sqlite_vec

            db.enable_load_extension(True)
            try:
                sqlite_vec.load(db)
            finally:
                db.enable_load_extension(False)
        yield db


def initialize(*, vector=False):
    with _connection("rwc", vector=vector) as db:
        if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
            raise RuntimeError("当前存储无法启用 WAL")


@contextmanager
def reader(*, vector=False):
    with _connection("ro", vector=vector) as db:
        db.execute("PRAGMA query_only=ON")
        yield db


@contextmanager
def transaction(*, vector=False):
    with _connection("rw", vector=vector) as db:
        # 进入写事务时取得写锁，避免业务读取快照后再升级写锁。
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def backup(destination: Path):
    if destination.name.casefold().endswith(("-wal", "-shm", "-journal")):
        raise ValueError("备份文件名与 SQLite 辅助文件冲突")
    with reader() as source:
        with TemporaryDirectory(dir=destination.parent) as staging:
            snapshot = Path(staging) / "snapshot"
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
                target.execute("PRAGMA journal_mode=DELETE")
                if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("备份完整性校验失败")
            # 同一文件系统内发布完整快照，目标已存在时保留原件。
            os.link(snapshot, destination)
