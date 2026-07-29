import os
import stat
import shutil
import sqlite3
import time
from pathlib import Path
from typing import List, Tuple
from blake3 import blake3

# -----------------------------
# CONFIG
# -----------------------------
IS_WINDOWS = os.name == "nt"

SKIP_DIRS = {
    "$RECYCLE.BIN",
    "RECYCLER",
    "WHSArchiveConfig.dat",
    "System Volume Information",
    "Recovery",
    "MSOCache",
}
SKIP_DIRS_NORMALIZED = {d.lower() for d in SKIP_DIRS} if IS_WINDOWS else SKIP_DIRS

SKIP_FILES = {
    "desktop.ini",
    "thumbs.db",
}
SKIP_FILES_NORMALIZED = {f.lower() for f in SKIP_FILES} if IS_WINDOWS else SKIP_FILES

LOG_FILE = None  # set later


# -----------------------------
# LOGGING
# -----------------------------
def log(msg: str, error: bool = False):
    """Write everything to log file; print only errors to console."""
    global LOG_FILE
    LOG_FILE.write(msg + "\n")
    LOG_FILE.flush()
    if error:
        print(msg)


# -----------------------------
# RETRY WRAPPER
# -----------------------------
def retry(operation, description: str, max_attempts=3, delay=0.2):
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as e:
            log(f"[RETRY {attempt}/{max_attempts}] {description}: {e}", error=True)
            if attempt == max_attempts:
                raise
            time.sleep(delay)


# -----------------------------
# SQLITE SETUP
# -----------------------------
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
    cur = db.execute(
        "SELECT dst_path, hash, status FROM files WHERE src_path=?",
        (str(src_path),),
    )
    return cur.fetchone()


def mark_pending(db: sqlite3.Connection, src_path: Path, dst_path: Path) -> None:
    db.execute(
        "INSERT OR REPLACE INTO files (src_path, dst_path, status) VALUES (?, ?, ?)",
        (str(src_path), str(dst_path), "pending"),
    )


def mark_done(
    db: sqlite3.Connection,
    src_path: Path,
    dst_path: Path,
    file_hash: str | None,
    status: str,
) -> None:
    db.execute(
        "UPDATE files SET hash=?, status=? WHERE src_path=?",
        (file_hash, status, str(src_path)),
    )


# -----------------------------
# SAFE FILE DETECTION
# -----------------------------
def safe_is_regular_file(path: Path) -> bool:
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            return False
        if hasattr(st, "st_file_attributes"):
            if st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return False
        return True
    except OSError:
        return False


# -----------------------------
# HASHING
# -----------------------------
def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = blake3()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# -----------------------------
# REPARSE POINT DETECTION
# -----------------------------
def is_reparse_point(path: Path) -> bool:
    st = os.lstat(path)
    if hasattr(st, "st_file_attributes"):
        return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def recreate_directory_symlink(src_path: Path, dst_path: Path) -> None:
    stored_target = os.readlink(src_path)
    abs_target = (src_path.parent / stored_target).resolve()
    relative_target = os.path.relpath(abs_target, start=dst_path.parent)

    retry(
        lambda: dst_path.symlink_to(relative_target, target_is_directory=True),
        f"dir symlink {dst_path}",
    )
    log(f"[DIR-LINK] {dst_path} -> {relative_target}")


# -----------------------------
# MAIN COPY LOGIC (ONE DISK)
# -----------------------------
def copy_with_dedup(src_root: Path, dst_root: Path, db: sqlite3.Connection) -> None:
    # Build persistent hash index from DB (for dedup across restarts)
    hash_index: dict[str, Path] = {}
    for h, dst in db.execute("SELECT hash, dst_path FROM files WHERE hash IS NOT NULL"):
        hash_index[h] = Path(dst)

    for src_path in src_root.rglob("*"):
        rel = src_path.relative_to(src_root)
        dst_path = dst_root / rel

        # --- Skip system folders ---
        parts = rel.parts
        if parts:
            first = parts[0]
            first_cmp = first.lower() if IS_WINDOWS else first
            if first_cmp in SKIP_DIRS_NORMALIZED:
                log(f"[SKIP-DIR] {src_path}")
                continue

        # --- Skip specific files ---
        filename = src_path.name
        filename_cmp = filename.lower() if IS_WINDOWS else filename
        if filename_cmp in SKIP_FILES_NORMALIZED:
            log(f"[SKIP-FILE] {src_path}")
            continue

        # --- Restart-safe DB check ---
        record = get_record(db, src_path)
        if record:
            prev_dst, prev_hash, status = record

            if status in ("copied", "symlink", "dir_symlink"):
                log(f"[SKIP-DB] Already processed: {src_path}")
                continue

            if status == "pending":
                log(f"[RETRY-PREV] Incomplete previous attempt: {src_path}", error=True)
                prev_dst_path = Path(prev_dst)
                if prev_dst_path.exists():
                    try:
                        prev_dst_path.unlink()
                    except Exception:
                        pass

        # --- Directories ---
        if src_path.is_dir():
            if is_reparse_point(src_path):
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                mark_pending(db, src_path, dst_path)
                recreate_directory_symlink(src_path, dst_path)
                mark_done(db, src_path, dst_path, None, "dir_symlink")
                db.commit()
                continue

            dst_path.mkdir(parents=True, exist_ok=True)
            continue

        # --- Non-regular files ---
        if not safe_is_regular_file(src_path):
            log(f"[SKIP] Not a regular file: {src_path}")
            continue

        # --- Files ---
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        mark_pending(db, src_path, dst_path)

        # Hash with retry
        file_hash = retry(lambda: hash_file(src_path), f"hash {src_path}")

        if file_hash not in hash_index:
            retry(lambda: shutil.copy2(src_path, dst_path), f"copy {src_path}")
            hash_index[file_hash] = dst_path
            mark_done(db, src_path, dst_path, file_hash, "copied")
            log(f"[COPY] {src_path} -> {dst_path}")
        else:
            target = hash_index[file_hash]
            rel_target = os.path.relpath(target, start=dst_path.parent)
            try:
                retry(
                    lambda: dst_path.symlink_to(rel_target), f"file symlink {dst_path}"
                )
                mark_done(db, src_path, dst_path, file_hash, "symlink")
                log(f"[FILE-LINK] {dst_path} -> {rel_target}")
            except Exception as e:
                log(f"[FILE-LINK-ERROR] {dst_path} -> {e}", error=True)
                retry(
                    lambda: shutil.copy2(src_path, dst_path),
                    f"fallback copy {src_path}",
                )
                mark_done(db, src_path, dst_path, file_hash, "copied")

        db.commit()

    log(f"Done disk: {src_root} -> {dst_root}")


# -----------------------------
# MULTI-DISK FAST IMPORT
# -----------------------------
def FastImport(sources: List[Tuple[str, str]], destination: str) -> None:
    global LOG_FILE

    dest_root = Path(destination)
    dest_root.mkdir(parents=True, exist_ok=True)

    LOG_FILE = open(dest_root / "fastimport.log", "a", encoding="utf-8")

    db = open_db(dest_root / "copy_state.db")

    try:
        for src_str, label in sources:
            src = Path(src_str)
            dst = dest_root / label

            log(f"Source:      {src}")
            log(f"Destination: {dst}")

            dst.mkdir(parents=True, exist_ok=True)
            copy_with_dedup(src, dst, db)

        log("FastImport completed")
    finally:
        db.close()
        LOG_FILE.close()


if __name__ == "__main__":
    sources = [
        (r"Y:\\", "MediaDisk01"),
        (r"Z:\\", "JOFREMORENO-NO PELICULAS"),
    ]
    destination = r"C:\Public\Fast-Import"
    FastImport(sources, destination)
