import os
import stat
import shutil
from pathlib import Path
from typing import List, Tuple
from blake3 import blake3

SKIP_DIRS = {
    "$RECYCLE.BIN",
    "RECYCLER",
    "WHSArchiveConfig.dat",
    "desktop.ini",
    "Thumbs.db",
    "System Volume Information",
    "Recovery",
    "MSOCache",
}


def hash_file(path: Path, chunk_size=1024 * 1024) -> str:
    h = blake3()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def is_reparse_point(path: Path) -> bool:
    attrs = os.lstat(path).st_file_attributes
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def recreate_directory_symlink(src_path: Path, dst_path: Path):
    """
    Recreate a directory junction/symlink at dst_path,
    using a relative target based on the original src_path.
    """
    try:
        # Original target as stored in the reparse point
        stored_target = os.readlink(src_path)

        # Make it absolute relative to the source junction location
        abs_target = (src_path.parent / stored_target).resolve()

        # Compute relative target from destination directory
        relative_target = os.path.relpath(abs_target, start=dst_path.parent)

        dst_path.symlink_to(relative_target, target_is_directory=True)
        print(f"[DIR-LINK] {dst_path} -> {relative_target}")
    except OSError as e:
        print(f"[DIR-LINK-ERROR] {src_path} -> {e}")


def copy_with_dedup(src_root: Path, dst_root: Path):
    """
    Walk src_root, copy files to dst_root with dedup:
    - First occurrence of content: copy file
    - Subsequent occurrences: create file symlink to first copy
    - Directory reparse points: recreated as directory symlinks (relative)
    """
    hash_index: dict[str, Path] = {}

    for src_path in src_root.rglob("*"):
        rel = src_path.relative_to(src_root)
        dst_path = dst_root / rel

        # --- Skip system folders ---
        parts = rel.parts
        if parts and parts[0] in SKIP_DIRS:
            print(f"[SKIP-DIR] {src_path}")
            continue

        # Directories
        if src_path.is_dir():
            if is_reparse_point(src_path):
                # Recreate junction/symlink, do NOT traverse into it
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                recreate_directory_symlink(src_path, dst_path)
                continue

            # Normal directory
            dst_path.mkdir(parents=True, exist_ok=True)
            continue

        # Files
        if not src_path.is_file():
            # Skip other types (devices, etc.)
            print(f"[SKIP] Non-file: {src_path}")
            continue

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        file_hash = hash_file(src_path)

        if file_hash not in hash_index:
            # First time seeing this content → copy file
            shutil.copy2(src_path, dst_path)
            hash_index[file_hash] = dst_path
            print(f"[COPY] {src_path} -> {dst_path}")
        else:
            # Duplicate content → create file symlink to first copy
            target = hash_index[file_hash]
            try:
                # Relative symlink for files too
                rel_target = os.path.relpath(target, start=dst_path.parent)
                dst_path.symlink_to(rel_target)
                print(f"[FILE-LINK] {dst_path} -> {rel_target}")
            except OSError as e:
                print(f"[FILE-LINK-ERROR] {dst_path} -> {e}, fallback to copy")
                shutil.copy2(src_path, dst_path)


def FastImport(sources: List[Tuple[str, str]], destination: str):
    for src_str, label in sources:
        src = Path(src_str)
        dst = Path(destination) / label
        print(f"Source:      {src}")
        print(f"Destination: {dst}/{dst}")
        dst.mkdir(parents=True, exist_ok=True)

        copy_with_dedup(src, dst)
        print(f"Done: {src} -> {dst}")
    print("FastImport completed")


if __name__ == "__main__":
    sources = [(r"Y:\\", "MediaDisk01"), (r"Z:\\", "JOFREMORENO-NO PELICULAS")]
    destination = r"C:\Public\Fast-Import"
    FastImport(sources, destination)
