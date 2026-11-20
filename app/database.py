"""SQLite 主库运维与 MySQL 检索运行时检查。"""
import argparse
import sqlite3
import sys
from pathlib import Path

from app.repository.sqlite import backup, initialize, reader


def check_mysql():
    from app.repository.mysql import reader as mysql_reader

    with mysql_reader() as db, db.cursor() as cursor:
        cursor.execute("SELECT VERSION(), @@ngram_token_size, "
                       "(SELECT PLUGIN_STATUS FROM information_schema.plugins WHERE PLUGIN_NAME='ngram'), "
                       "myvector_distance(myvector_construct('[1,0]'), myvector_construct('[1,0]'), 'Cosine')")
        version, size, status, distance = cursor.fetchone()
        if size != 2 or status != "ACTIVE" or distance is None or abs(distance) > 1e-6:
            raise RuntimeError("MySQL 检索能力检查失败")
        print(f"MySQL {version} ngram=2 MyVector Cosine OK")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("init", help="创建空库或复用现有库，并启用 WAL")
    commands.add_parser("check", help="只读检查现有库的完整性与日志模式")
    commands.add_parser("backup", help="生成一致性快照").add_argument("destination", type=Path)
    commands.add_parser("check-mysql", help="检查 MySQL 中文全文和余弦函数")
    args = parser.parse_args()
    if args.action == "check-mysql":
        check_mysql()
        return
    if args.action == "init":
        initialize()
    elif args.action == "backup":
        backup(args.destination)
    else:
        with reader() as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("完整性校验失败")
            print("journal_mode=" + db.execute("PRAGMA journal_mode").fetchone()[0])
    print(args.action, "OK")


if __name__ == "__main__":
    try:
        main()
    except FileExistsError:
        sys.exit("目标文件已存在")
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as error:
        sys.exit(f"数据库操作失败（{getattr(error, 'sqlite_errorname', type(error).__name__)}）")
