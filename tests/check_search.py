"""使用临时 SQLite 文件从正式连接入口验收中文 BM25 与向量检索。"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.sqlite import BACKEND_ROOT
from app.repository.full_text import index_text, match_phrase
from app.repository.sqlite import initialize, reader, transaction


def check_lexical():
    initialize()
    with transaction() as db:
        db.execute("CREATE VIRTUAL TABLE docs USING fts5(title, body)")
        docs = [("设备验收", "合同付款"), ("采购合同", "设备验收"), ("发票", "设备金额")]
        db.executemany("INSERT INTO docs VALUES (?, ?)",
                       [(index_text(title), index_text(body)) for title, body in docs])
    with reader() as db:
        rows = db.execute(
            "SELECT rowid, bm25(docs, 8, 1) AS score FROM docs "
            "WHERE docs MATCH ? ORDER BY score, rowid", (match_phrase("验收"),)
        ).fetchall()
    if [row[0] for row in rows] != [1, 2] or rows[0][1] >= rows[1][1]:
        raise RuntimeError(f"FTS5 排序异常 {rows}")
    print("SQLite", sqlite3.sqlite_version, "FTS5 BM25", rows)


def check_vector():
    initialize(vector=True)
    with transaction(vector=True) as db:
        db.execute("CREATE VIRTUAL TABLE vectors USING vec0(v float[2])")
        db.executemany("INSERT INTO vectors(rowid,v) VALUES (?,?)", [
            (1, "[1,0]"), (2, "[0,1]"), (3, "[0.9,0.1]"),
        ])
    with reader(vector=True) as db:
        rows = db.execute(
            "SELECT rowid,distance FROM vectors WHERE v MATCH ? AND k=2 ORDER BY distance",
            ("[1,0]",),
        ).fetchall()
        version = db.execute("SELECT vec_version()").fetchone()[0]
    if [row[0] for row in rows] != [1, 3]:
        raise RuntimeError(f"向量近邻异常 {rows}")
    print("sqlite-vec", version, rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector", action="store_true", help=argparse.SUPPRESS)
    parser.parse_args()
    with TemporaryDirectory(dir=BACKEND_ROOT / "tests/tmp") as directory:
        os.environ.update(DATA_DIR=directory, DB_ENGINE="sqlite", SQLITE_FILENAME="main.db",
                          VECTOR_INDEX_FILENAME="vectors.db")
        check_lexical()
        check_vector()
