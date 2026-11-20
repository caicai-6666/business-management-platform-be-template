"""读取 MySQL 业务账号的连接参数。"""
import os


def connection_options():
    return dict(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "platform"),
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ.get("MYSQL_DATABASE", "platform"),
        charset="utf8mb4", connect_timeout=5, autocommit=False,
    )
