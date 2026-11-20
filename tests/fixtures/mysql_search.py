"""仅由独立验收项目使用，在空的隔离库中保留样本供重启复核。"""
import argparse

import pymysql

from app.repository.mysql import reader, transaction
from app.database import check_mysql


def seed():
    with transaction() as db, db.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        if cursor.fetchall():
            raise RuntimeError("验收需要独立空库")
        cursor.execute("CREATE TABLE fixture_docs (id INT PRIMARY KEY, body TEXT, embedding MEDIUMBLOB, "
                       "FULLTEXT KEY ft_body(body) WITH PARSER ngram) ENGINE=InnoDB")
        cursor.executemany("INSERT INTO fixture_docs VALUES (%s, %s, myvector_construct(%s))", [
            (1, "设备验收以及现场验收", "[1,0]"), (2, "验收付款", "[0,1]"), (3, "发票金额", "[0.9,0.1]"),
        ])


def verify_transactions():
    try:
        with transaction() as db, db.cursor() as cursor:
            cursor.execute("UPDATE fixture_docs SET body='隔离写入' WHERE id=1")
            with reader() as other, other.cursor() as check_cursor:
                check_cursor.execute("SELECT body FROM fixture_docs WHERE id=1")
                if check_cursor.fetchone()[0] != "设备验收以及现场验收":
                    raise RuntimeError("并发读取了未提交的数据")
            cursor.execute("INSERT INTO fixture_docs (id) VALUES (1)")
    except pymysql.err.IntegrityError as error:
        if error.args[0] != 1062:
            raise
    else:
        raise RuntimeError("重复主键写入未拒绝")
    try:
        with reader() as db, db.cursor() as cursor:
            cursor.execute("UPDATE fixture_docs SET body='只读写入' WHERE id=1")
    except pymysql.MySQLError as error:
        if error.args[0] != 1792:
            raise
    else:
        raise RuntimeError("只读事务接受了写入")


def verify():
    with reader() as db, db.cursor() as cursor:
        cursor.execute("SELECT id, MATCH(body) AGAINST (%s IN NATURAL LANGUAGE MODE) AS score "
                       "FROM fixture_docs WHERE MATCH(body) AGAINST (%s IN NATURAL LANGUAGE MODE) "
                       "ORDER BY score DESC, id", ("验收", "验收"))
        fulltext = cursor.fetchall()
        cursor.execute("SELECT id, myvector_distance(embedding,myvector_construct(%s),'Cosine') AS distance "
                       "FROM fixture_docs ORDER BY distance,id LIMIT 2", ("[1,0]",))
        vectors = cursor.fetchall()
        if ([r[0] for r in fulltext] != [1, 2] or not fulltext[0][1] > fulltext[1][1]
                or [r[0] for r in vectors] != [1, 3] or not 0 <= vectors[0][1] < vectors[1][1] < 0.01):
            raise RuntimeError("MySQL 检索排序异常")
        print("FULLTEXT 1,2 / Cosine 1,3 OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reopen", action="store_true")
    args = parser.parse_args()
    check_mysql()
    if not args.reopen:
        seed()
        verify_transactions()
    verify()
