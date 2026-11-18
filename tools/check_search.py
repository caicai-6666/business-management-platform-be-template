"""在内存数据库验证词法检索及可选的 sqlite-vec，无业务数据输入。"""
import argparse
import sqlite3
from contextlib import closing


def check_lexical(db):
    db.execute("CREATE VIRTUAL TABLE docs USING fts5(title, body)")
    db.executemany("INSERT INTO docs(rowid,title,body) VALUES(?,?,?)", [
        (1, "验收", "合同 付款"), (2, "合同", "验收 付款"), (3, "发票", "设备 金额"),
    ])
    rows = db.execute(
        "SELECT rowid, bm25(docs, 8, 1) AS score FROM docs "
        "WHERE docs MATCH ? ORDER BY score, rowid", ("验收",)
    ).fetchall()
    if [row[0] for row in rows] != [1, 2] or rows[0][1] >= rows[1][1]:
        raise RuntimeError(f"FTS5 排序异常 {rows}")
    print("SQLite", sqlite3.sqlite_version, "FTS5 BM25", rows)


def check_vector(db):
    import sqlite_vec

    db.enable_load_extension(True)
    try:
        sqlite_vec.load(db)
    finally:
        db.enable_load_extension(False)
    db.execute("CREATE VIRTUAL TABLE vectors USING vec0(v float[2])")
    db.executemany("INSERT INTO vectors(rowid,v) VALUES (?,?)", [
        (1, "[1,0]"), (2, "[0,1]"), (3, "[0.9,0.1]"),
    ])
    rows = db.execute(
        "SELECT rowid,distance FROM vectors WHERE v MATCH ? AND k=2 ORDER BY distance",
        ("[1,0]",),
    ).fetchall()
    if [row[0] for row in rows] != [1, 3]:
        raise RuntimeError(f"向量近邻异常 {rows}")
    print("sqlite-vec", db.execute("SELECT vec_version()").fetchone()[0], rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector", action="store_true")
    args = parser.parse_args()
    with closing(sqlite3.connect(":memory:")) as connection:
        check_lexical(connection)
        if args.vector:
            check_vector(connection)
