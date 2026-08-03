# safe_walk.py
import os
from pathlib import Path
from fs import log
from ignore import IgnoreEngine


def safe_walk(root: Path, db, ignore_engine: IgnoreEngine, retries=2):
    """
    Crash-resistant directory walker.
    - Skips ignored directories BEFORE scandir.
    - Retries N times on scandir failure.
    - Logs corrupted directories.
    - Marks corrupted directories in DB.
    - Yields files and directories safely.
    """

    stack = [root]

    while stack:
        current = stack.pop()

        # Check ignore BEFORE scandir
        if current != root:
            if (
                (current.is_dir() and ignore_engine.ignore_folder(current.name))
                or (current.is_file() and ignore_engine.ignore_file(current.name))
                or (
                    current.is_file() and ignore_engine.ignore_extension(current.suffix)
                )
            ):
                log(f"[SKIP-IGNORE] {current}")
                continue

        # Yield the directory itself
        yield current

        # Try to list entries
        for attempt in range(1, retries + 1):
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        p = Path(entry.path)

                        # ------------------------------------------------------------
                        # CHILD IGNORE CHECK (BEFORE yield)
                        # ------------------------------------------------------------
                        if entry.is_dir(follow_symlinks=False):
                            if ignore_engine.ignore_folder(entry.name):
                                log(f"[SKIP-IGNORE] {p}")
                                continue

                        # Yield file or directory
                        yield p

                        # Recurse into directories
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(p)

                break  # success → stop retry loop

            except PermissionError as e:
                log(
                    f"[DIR-PERMISSION] {current} (attempt {attempt}/{retries}) -> {e}",
                    error=True,
                )

            except FileNotFoundError as e:
                log(
                    f"[DIR-MISSING] {current} (attempt {attempt}/{retries}) -> {e}",
                    error=True,
                )

            except OSError as e:
                log(
                    f"[DIR-OSERROR] {current} (attempt {attempt}/{retries}) -> {e}",
                    error=True,
                )

        else:
            # All retries failed → mark directory as corrupted
            log(f"[DIR-CORRUPTED] {current} (after {retries} retries)", error=True)
            try:
                db.execute(
                    "INSERT OR REPLACE INTO files (src_path, dst_path, status) VALUES (?, ?, ?)",
                    (str(current), "", "corrupted_dir"),
                )
                db.commit()
            except Exception:
                pass

            continue
