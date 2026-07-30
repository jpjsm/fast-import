import json
import os
import stat
import shutil
import time
from pathlib import Path
from blake3 import blake3

IS_WINDOWS = os.name == "nt"

LOG_FILE = None  # set by main


def set_log_file(f):
    global LOG_FILE
    LOG_FILE = f


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


def retry(operation, description: str, max_attempts=3, delay=0.2):
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as e:
            log(f"[RETRY {attempt}/{max_attempts}] {description}: {e}", error=True)
            if attempt == max_attempts:
                raise
            time.sleep(delay)


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


def safe_mkdir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        log(f"[MKDIR-ERROR] {path} -> {e}", error=True)
        return False


def safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except Exception as e:
        log(f"[ISDIR-ERROR] {path} -> {e}", error=True)
        return False


def safe_unlink(path: Path) -> None:
    try:
        if path.exists() and (path.is_file() or path.is_symlink()):
            path.unlink()
    except Exception as e:
        log(f"[UNLINK-ERROR] {path} -> {e}", error=True)


def safe_copy(src: Path, dst: Path, description: str) -> bool:
    try:
        retry(lambda: shutil.copy2(src, dst), description)
        return True
    except Exception as e:
        log(f"[COPY-ERROR] {src} -> {e}", error=True)
        return False


def safe_symlink(src_target: Path, dst_link: Path, description: str) -> bool:
    rel_target = os.path.relpath(src_target, start=dst_link.parent)
    try:
        retry(lambda: dst_link.symlink_to(rel_target), description)
        return True
    except Exception as e:
        log(f"[SYMLINK-ERROR] {dst_link} -> {e}", error=True)
        return False
