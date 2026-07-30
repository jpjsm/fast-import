import sqlite3
from pathlib import Path


def open_db(db_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(db_path))
    db.execute("""
        CREATE TABLE IF NOT EXISTS files (
            src_path TEXT PRIMARY KEY,
            dst_path TEXT NOT NULL,
            hash TEXT,
            status TEXT NOT NULL
        )
        """)
    return db


def get_record(db: sqlite3.Connection, src_path: Path):
    try:
        cur = db.execute(
            "SELECT dst_path, hash, status FROM files WHERE src_path=?",
            (str(src_path),),
        )
        return cur.fetchone()
    except Exception:
        return None


def mark_pending(db: sqlite3.Connection, src_path: Path, dst_path: Path) -> None:
    try:
        db.execute(
            "INSERT OR REPLACE INTO files (src_path, dst_path, status) VALUES (?, ?, ?)",
            (str(src_path), str(dst_path), "pending"),
        )
    except Exception:
        pass


def mark_done(
    db: sqlite3.Connection,
    src_path: Path,
    dst_path: Path,
    file_hash: str | None,
    status: str,
) -> None:
    try:
        db.execute(
            "UPDATE files SET hash=?, status=? WHERE src_path=?",
            (file_hash, status, str(src_path)),
        )
    except Exception:
        pass
