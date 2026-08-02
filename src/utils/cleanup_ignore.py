# src/utils/cleanup_ignore.py

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple

import os

from fast_import.ignore import load_ignore_file, matches_ignore
from fast_import.safe_walk import safe_walk
from fast_import.fs import log  # assuming same log() as importer
from fast_import.db import get_record  # or a small helper to query by dst_path

DB_PATH = Path("copy_state.db")
IGNORE_FILE = Path(".importignore")


def normalize_path(path: Path) -> Path:
    """
    Normalize the path for comparison. On Windows, convert to lowercase.
    """
    if os.name.lower() == "nt":
        return Path(str(path).lower())
    return path


def load_db(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = DB_PATH
    if not db_path.exists() or not db_path.is_file():
        raise FileNotFoundError(f"Database file {db_path} does not exist.")
    return sqlite3.connect(db_path)


def build_hash_map(conn: sqlite3.Connection) -> Dict[str, List[str]]:
    """
    Build hash -> [dst_path] map from DB.
    """
    cur = conn.cursor()
    hash_map: Dict[str, List[str]] = {}
    for row in cur.execute("SELECT hash, dst_path FROM files WHERE hash IS NOT NULL"):
        h, dst = row
        if h not in hash_map:
            hash_map[h] = []
        hash_map[h].append(dst)
    return hash_map


def cleanup_by_ignore(
    destination: Path,
    ignore_file: Path | None = None,
    db_path: Path | None = None,
    dry_run: bool = True,
):
    """
    Cleanup files and directories in `destination` based on `.importignore`,
    respecting dedup relationships and the FastImport DB.

    Dry-run is enabled by default: no deletions or DB updates are performed
    unless `dry_run=False` is explicitly passed.
    """
    # Validate destination
    if not destination.exists() or not destination.is_dir():
        log(
            f"[CLEANUP] Destination {destination} does not exist or is not a directory.",
            error=True,
        )
        return

    # Resolve ignore file
    if ignore_file is None:
        ignore_file = IGNORE_FILE
    if not ignore_file.exists():
        log(f"[CLEANUP] Ignore file {ignore_file} does not exist.", error=True)
        return

    ignore_patterns = load_ignore_file(ignore_file)

    # Connect to DB
    try:
        conn = load_db(db_path)
    except FileNotFoundError as ex:
        log(f"[CLEANUP] {ex}", error=True)
        return

    cur = conn.cursor()
    hash_map = build_hash_map(conn)

    log(
        "=== FastImport Cleanup (DRY RUN)"
        if dry_run
        else "=== FastImport Cleanup (LIVE) ==="
    )
    log(f"Destination: {destination}")
    log(f"Ignore file: {ignore_file}")
    log(f"DB: {db_path or DB_PATH}")

    # Collections
    symlinks: List[Tuple[Path, str | None]] = []
    regular_files: List[Tuple[Path, str | None]] = []
    stray_files: List[Path] = []
    directories: List[Path] = []

    # Walk destination
    for src_path in safe_walk(destination, conn, ignore_patterns, retries=2):
        if src_path == destination:
            continue

        rel = src_path.relative_to(destination)
        rel_str = str(rel)

        # Directory?
        if src_path.is_dir():
            if matches_ignore(rel_str, True, ignore_patterns):
                directories.append(src_path)
            continue

        # File or symlink
        is_symlink = src_path.is_symlink()
        is_file = src_path.is_file()

        if not (is_file or is_symlink):
            continue

        if not matches_ignore(rel_str, False, ignore_patterns):
            continue

        # Look up in DB by dst_path
        cur.execute(
            "SELECT hash, status FROM files WHERE dst_path = ?", (str(src_path),)
        )
        row = cur.fetchone()

        if row is None:
            # Stray file
            stray_files.append(src_path)
            continue

        file_hash, status = row

        if is_symlink:
            symlinks.append((src_path, file_hash))
        else:
            regular_files.append((src_path, file_hash))

    # --- Dry-run output (simple, aligned with spec) ---

    log(f"--- Symlinks Matching Ignore Patterns ({len(symlinks)}) ---")
    for path, h in symlinks:
        log(f"[SYMLINK] {path} (hash={h})")

    log(f"--- Regular Files Matching Ignore Patterns ({len(regular_files)}) ---")
    for path, h in regular_files:
        log(f"[FILE] {path} (hash={h})")

    log(f"--- Stray Files Matching Ignore Patterns ({len(stray_files)}) ---")
    for path in stray_files:
        log(f"[STRAY] {path}")

    log(f"--- Directories Matching Ignore Patterns ({len(directories)}) ---")
    for path in directories:
        log(f"[DIR] {path}")

    if dry_run:
        log("=== Summary (DRY RUN) ===")
        log(f"Symlinks to delete: {len(symlinks)}")
        log(f"Regular files: {len(regular_files)}")
        log(f"Stray files: {len(stray_files)}")
        log(f"Directories: {len(directories)}")
        log("----------------------------------------")
        log("No changes have been made (dry-run mode).")
        conn.close()
        return

    # --- LIVE MODE: perform deletions in safe order ---

    # 1) Delete symlinks
    for path, _ in symlinks:
        if path.exists() and path.is_symlink():
            log(f"[DEL-SYMLINK] {path}")
            path.unlink()
            cur.execute(
                "UPDATE files SET status='deleted' WHERE dst_path = ?", (str(path),)
            )

    # 2) Delete regular files (non-dedup or deferred dedup)
    for path, file_hash in regular_files:
        if not path.exists() or not path.is_file():
            continue

        if file_hash is None:
            # Non-dedup regular file
            log(f"[DEL-FILE] {path}")
            path.unlink()
            cur.execute(
                "UPDATE files SET status='deleted' WHERE dst_path = ?", (str(path),)
            )
        else:
            # Dedup canonical candidate; we need to check hash_map
            refs = hash_map.get(file_hash, [])
            # After symlink deletion, recompute references that still exist
            remaining = [p for p in refs if Path(p).exists()]
            if len(remaining) <= 1:
                log(f"[DEL-CANONICAL] {path} (hash={file_hash})")
                path.unlink()
                cur.execute(
                    "UPDATE files SET status='deleted' WHERE dst_path = ?", (str(path),)
                )
            else:
                log(
                    f"[SKIP-CANONICAL] {path} (hash={file_hash}) still referenced by {len(remaining)-1} other paths"
                )

    # 3) Delete stray files
    for path in stray_files:
        if path.exists():
            log(f"[DEL-STRAY] {path}")
            path.unlink()

    # 4) Delete directories (best-effort: only if empty)
    for path in directories:
        if path.exists() and path.is_dir():
            try:
                log(f"[DEL-DIR] {path}")
                path.rmdir()
            except OSError:
                log(f"[SKIP-DIR-NOT-EMPTY] {path}", error=True)

    conn.commit()
    conn.close()

    log("Cleanup complete.")


if __name__ == "__main__":
    # Default: dry-run, destination is current working directory
    DB_PATH = Path(r"C:\Public\Fast-Import\copy_state_copy.db")
    IGNORE_FILE = Path(r"C:\Public\Fast-Import\.importignore")

    destination = Path(r"C:\Public\Fast-Import\MediaDisk01")
    cleanup_by_ignore(destination, dry_run=True)
