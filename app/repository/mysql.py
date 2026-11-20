"""MySQL 普通业务账号的读连接与事务入口。"""
from contextlib import closing, contextmanager

import pymysql

from app.config.mysql import connection_options


@contextmanager
def transaction(*, read_only=False):
    with closing(pymysql.connect(**connection_options())) as db:
        with db.cursor() as cursor:
            cursor.execute("START TRANSACTION READ ONLY" if read_only else "START TRANSACTION")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def reader():
    return transaction(read_only=True)
