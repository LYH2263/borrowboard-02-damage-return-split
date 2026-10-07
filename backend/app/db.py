import os, sqlite3
from pathlib import Path

def db_path() -> Path:
    d = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "borrowboard.db"

def connect():
    c = sqlite3.connect(db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    return c

def transact(c, fn):
    """BEGIN IMMEDIATE … COMMIT 跑 fn；任何异常整体回滚，不落半笔。

    写操作一进来就拿写锁，读-判-写在锁内串行，并发归还/借出不会叠单。
    """
    c.execute("BEGIN IMMEDIATE")
    try:
        r = fn()
    except Exception:
        c.rollback()
        raise
    c.commit()
    return r
