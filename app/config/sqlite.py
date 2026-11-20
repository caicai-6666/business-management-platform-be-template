"""SQLite 主库的环境配置。"""
import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def database_path(*, vector: bool = False) -> Path:
    if os.environ.get("DB_ENGINE", "sqlite") != "sqlite":
        raise ValueError("SQLite 主库要求 DB_ENGINE=sqlite")
    directory = os.environ.get("DATA_DIR", "./data")
    if not directory.strip():
        raise ValueError("DATA_DIR 不能为空")
    name = os.environ.get("SQLITE_FILENAME", "platform.sqlite3")
    index = os.environ.get("VECTOR_INDEX_FILENAME", "vectors.sqlite3")
    for filename in (name, index):
        if (not filename.strip() or Path(filename).name != filename
                or filename in {".", ".."} or "\\" in filename
                or filename.casefold().endswith(("-wal", "-shm", "-journal"))):
            raise ValueError("数据库文件名须为独立的单层文件名")
    if name.casefold() == index.casefold():
        raise ValueError("主库与向量索引须使用不同文件名")
    return BACKEND_ROOT / directory / (index if vector else name)
