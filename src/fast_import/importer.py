# importer.py
from pathlib import Path
from typing import Dict

from db import get_record, mark_pending, mark_done
from fs import (
    log,
    safe_is_regular_file,
    hash_file,
    is_reparse_point,
    recreate_directory_symlink,
    safe_mkdir,
    safe_is_dir,
    safe_unlink,
    safe_copy,
    safe_symlink,
)
from ignore import matches_ignore
from safe_walk import safe_walk


def copy_with_dedup(
    src_root: Path,
    dst_root: Path,
    db,
    progress_count: int,
    global_counter: Dict[str, int],
    ignore_patterns: list[str],
) -> None:

    # Build hash index from DB
    hash_index: dict[str, Path] = {}
    for h, dst in db.execute("SELECT hash, dst_path FROM files WHERE hash IS NOT NULL"):
        hash_index[h] = Path(dst)

    processed = 0

    # Use safe walker instead of rglob
    for src_path in safe_walk(src_root, db, retries=2):

        # Skip root itself (we handle directory creation separately)
        if src_path == src_root:
            continue

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

        name = src_path.name

        # --- Ignore via .importignore ---
        try:
            is_dir = safe_is_dir(src_path)
        except Exception:
            is_dir = False

        if matches_ignore(name, is_dir, ignore_patterns):
            log(f"[SKIP-IGNORE] {src_path}")
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
                safe_unlink(prev_dst_path)

            if status == "corrupted_dir":
                log(f"[SKIP-CORRUPTED-DIR] {src_path}")
                continue

        # --- Directories ---
        if safe_is_dir(src_path):
            if is_reparse_point(src_path):
                safe_mkdir(dst_path.parent)
                mark_pending(db, src_path, dst_path)
                recreate_directory_symlink(src_path, dst_path)
                mark_done(db, src_path, dst_path, None, "dir_symlink")
                db.commit()
                continue

            safe_mkdir(dst_path)
            continue

        # --- Non-regular files ---
        if not safe_is_regular_file(src_path):
            log(f"[SKIP] Not a regular file: {src_path}")
            continue

        # --- Files ---
        if not safe_mkdir(dst_path.parent):
            continue

        # Hash with retry + safe guard
        try:
            file_hash = hash_file(src_path)
        except Exception:
            continue

        mark_pending(db, src_path, dst_path)

        if file_hash not in hash_index:
            if not safe_copy(src_path, dst_path, f"copy {src_path}"):
                continue

            hash_index[file_hash] = dst_path
            mark_done(db, src_path, dst_path, file_hash, "copied")
            log(f"[COPY] {src_path} -> {dst_path}")

        else:
            target = hash_index[file_hash]
            if safe_symlink(target, dst_path, f"file symlink {dst_path}"):
                mark_done(db, src_path, dst_path, file_hash, "symlink")
                log(f"[FILE-LINK] {dst_path} -> {target}")
            else:
                if safe_copy(src_path, dst_path, f"fallback copy {src_path}"):
                    mark_done(db, src_path, dst_path, file_hash, "copied")

        db.commit()

    print()  # newline after progress bar
    log(f"Done disk: {src_root} -> {dst_root}")
