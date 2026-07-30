import json
import os
import stat
import shutil
import sqlite3
import time
from fnmatch import fnmatch
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
    "System Volume Information",
    "Recovery",
    "MSOCache",
    "debug",
    "release",
    "build",
    ".vscode",
    "vcpkg_installed",
    "__pycache__",
}
SKIP_DIRS_NORMALIZED = {d.lower() for d in SKIP_DIRS} if IS_WINDOWS else SKIP_DIRS

SKIP_FILES = {
    "desktop.ini",
    "thumbs.db",
    "WHSArchiveConfig.dat",
    "folder.jpg",
    "folder.jpeg",
}
SKIP_FILES_NORMALIZED = {f.lower() for f in SKIP_FILES} if IS_WINDOWS else SKIP_FILES

SKIP_WILDCARDS = {
    "*.dll",
    "*.so",
    "*.dylib",
    "*.obj",
    "*.lib",
    "*.slo",
    "*.exe",
    "*.msi",
    "*.tmp",
    "*.bak",
    "*.lnk",
    "*.swp",
    "*.ini",
    "*.db",
    "*.dat",
    "*.plist",
    "albumart*.jpg",
    "albumart*.jpeg",
    "*.rsuser",
    "*.suo",
    "*.user",
    "*.userosscache",
    "*.sln.docstates",
    "*.userprefs",
    "mono_crash.*",
    "*.lock",
    "*.lock.json",
}

SKIP_WILDCARDS_NORMALIZED = (
    [p.lower() for p in SKIP_WILDCARDS] if IS_WINDOWS else SKIP_WILDCARDS
)
LOG_FILE = None  # set later


# -----------------------------
# LOGGING
# -----------------------------
def log(msg: str, error: bool = False):
    global LOG_FILE
    LOG_FILE.write(
        json.dumps(
            {
                "local-time": time.asctime(),
                "timestamp": time.asctime(time.gmtime()),
                "msg": msg,
            }
        )
        + "\n"
    )
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
    try:
        cur = db.execute(
            "SELECT dst_path, hash, status FROM files WHERE src_path=?",
            (str(src_path),),
        )
        return cur.fetchone()
    except Exception as e:
        log(f"[DB-READ-ERROR] {src_path} -> {e}", error=True)
        return None


def mark_pending(db: sqlite3.Connection, src_path: Path, dst_path: Path) -> None:
    try:
        db.execute(
            "INSERT OR REPLACE INTO files (src_path, dst_path, status) VALUES (?, ?, ?)",
            (str(src_path), str(dst_path), "pending"),
        )
    except Exception as e:
        log(f"[DB-PENDING-ERROR] {src_path} -> {e}", error=True)


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
    except Exception as e:
        log(f"[DB-DONE-ERROR] {src_path} -> {e}", error=True)


# -----------------------------
# SAFE FILE DETECTION
# -----------------------------
def safe_is_regular_file(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        log(f"[MISSING] {path}", error=True)
        return False
    except OSError as e:
        log(f"[LSTAT-ERROR] {path} -> {e}", error=True)
        return False

    if not stat.S_ISREG(st.st_mode):
        return False

    if hasattr(st, "st_file_attributes"):
        if st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return False

    if path.is_symlink():
        return False

    return True


# -----------------------------
# HASHING
# -----------------------------
def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    try:
        h = blake3()
        with path.open("rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        log(f"[HASH-MISSING] {path}", error=True)
        raise
    except Exception as e:
        log(f"[HASH-ERROR] {path} -> {e}", error=True)
        raise


# -----------------------------
# REPARSE POINT DETECTION
# -----------------------------
def is_reparse_point(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        log(f"[MISSING] {path}", error=True)
        return False
    except OSError as e:
        log(f"[LSTAT-ERROR] {path} -> {e}", error=True)
        return False

    if hasattr(st, "st_file_attributes"):
        return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def recreate_directory_symlink(src_path: Path, dst_path: Path) -> None:
    try:
        stored_target = os.readlink(src_path)
    except Exception as e:
        log(f"[READLINK-ERROR] {src_path} -> {e}", error=True)
        return

    abs_target = (src_path.parent / stored_target).resolve()
    relative_target = os.path.relpath(abs_target, start=dst_path.parent)

    try:
        retry(
            lambda: dst_path.symlink_to(relative_target, target_is_directory=True),
            f"dir symlink {dst_path}",
        )
        log(f"[DIR-LINK] {dst_path} -> {relative_target}")
    except Exception as e:
        log(f"[DIR-LINK-ERROR] {dst_path} -> {e}", error=True)


# -----------------------------
# MAIN COPY LOGIC (ONE DISK)
# -----------------------------
def copy_with_dedup(
    src_root: Path,
    dst_root: Path,
    db: sqlite3.Connection,
    progress_count: int,
    global_counter: dict,
) -> None:

    hash_index: dict[str, Path] = {}
    for h, dst in db.execute("SELECT hash, dst_path FROM files WHERE hash IS NOT NULL"):
        hash_index[h] = Path(dst)

    processed = 0

    for src_path in src_root.rglob("*"):
        rel = src_path.relative_to(src_root)
        dst_path = dst_root / rel

        # Progress reporting
        processed += 1
        global_counter["total"] += 1

        if progress_count > 0 and processed % progress_count == 0:
            print(
                f"\r[{src_root}] Progress: {processed:,} items processed… "
                f"(Global: {global_counter['total']:,})",
                end="",
                flush=True,
            )

        # --- Skip by wildcard patterns (case-insensitive on Windows) ---
        name = src_path.name
        name_cmp = name.lower() if IS_WINDOWS else name

        for pattern in SKIP_WILDCARDS_NORMALIZED:
            if fnmatch(name_cmp, pattern):
                log(f"[SKIP-WILDCARD] {src_path} matches {pattern}")
                continue  # skip this item

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
                        if prev_dst_path.is_file() or prev_dst_path.is_symlink():
                            prev_dst_path.unlink()
                    except Exception as e:
                        log(f"[CLEANUP-ERROR] {prev_dst_path} -> {e}", error=True)

        # --- Directories ---
        try:
            is_dir = src_path.is_dir()
        except Exception as e:
            log(f"[ISDIR-ERROR] {src_path} -> {e}", error=True)
            continue

        if is_dir:
            if is_reparse_point(src_path):
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                mark_pending(db, src_path, dst_path)
                recreate_directory_symlink(src_path, dst_path)
                mark_done(db, src_path, dst_path, None, "dir_symlink")
                db.commit()
                continue

            try:
                dst_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                log(f"[MKDIR-ERROR] {dst_path} -> {e}", error=True)
            continue

        # --- Non-regular files ---
        if not safe_is_regular_file(src_path):
            log(f"[SKIP] Not a regular file: {src_path}")
            continue

        # --- Files ---
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log(f"[MKDIR-ERROR] {dst_path.parent} -> {e}", error=True)
            continue

        # Hash with retry + safe guard
        try:
            file_hash = retry(lambda: hash_file(src_path), f"hash {src_path}")
        except Exception:
            continue

        mark_pending(db, src_path, dst_path)

        if file_hash not in hash_index:
            try:
                retry(lambda: shutil.copy2(src_path, dst_path), f"copy {src_path}")
            except Exception:
                continue

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
                try:
                    retry(
                        lambda: shutil.copy2(src_path, dst_path),
                        f"fallback copy {src_path}",
                    )
                    mark_done(db, src_path, dst_path, file_hash, "copied")
                except Exception:
                    continue

        db.commit()

    print()  # newline after progress bar
    log(f"Done disk: {src_root} -> {dst_root}")


# -----------------------------
# MULTI-DISK FAST IMPORT
# -----------------------------
def FastImport(
    sources: List[Tuple[str, str]], destination: str, progress_count: int = 0
) -> None:
    global LOG_FILE

    dest_root = Path(destination)
    dest_root.mkdir(parents=True, exist_ok=True)

    LOG_FILE = open(dest_root / "fastimport.log", "a", encoding="utf-8")

    db = open_db(dest_root / "copy_state.db")

    global_counter = {"total": 0}

    try:
        for src_str, label in sources:
            src = Path(src_str)
            dst = dest_root / label

            log(f"Source:      {src}")
            log(f"Destination: {dst}")

            dst.mkdir(parents=True, exist_ok=True)
            copy_with_dedup(src, dst, db, progress_count, global_counter)

        log("FastImport completed")
        print(f"\nTotal items processed across all disks: {global_counter['total']:,}")

    finally:
        db.close()
        LOG_FILE.close()


if __name__ == "__main__":
    sources = [
        (r"Y:\\", "MediaDisk01"),
        (r"Z:\\", "JOFREMORENO-NO PELICULAS"),
    ]
    destination = r"C:\Public\Fast-Import"
    FastImport(sources, destination, progress_count=500)
