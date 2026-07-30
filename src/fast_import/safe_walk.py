# safe_walk.py
import os
from pathlib import Path
from fs import log


def safe_walk(root: Path, db, retries=2):
    """
    Crash-resistant directory walker.
    - Retries N times on scandir failure.
    - Logs corrupted directories.
    - Marks corrupted directories in DB.
    - Yields files and directories safely.
    """

    stack = [root]

    while stack:
        current = stack.pop()

        # Yield the directory itself
        yield current

        # Try to list entries
        for attempt in range(1, retries + 1):
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        p = Path(entry.path)

                        # Yield file or directory
                        yield p

                        # Recurse into directories
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(p)

                break  # success → stop retry loop

            except FileNotFoundError as e:
                log(
                    f"[DIR-MISSING] {current} (attempt {attempt}/{retries}) -> {e}",
                    error=True,
                )

            except PermissionError as e:
                log(
                    f"[DIR-PERMISSION] {current} (attempt {attempt}/{retries}) -> {e}",
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

            # Skip this directory entirely
            continue
