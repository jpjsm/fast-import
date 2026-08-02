import signal
import threading

from pathlib import Path
from typing import List, Tuple
from datetime import datetime, UTC

from db import open_db
from fs import set_log_file, log
from ignore import load_ignore_file, normalize_patterns
from importer import copy_with_dedup, CopyResult
from stats import Stats
from control_server import (
    launch_control_server,
    stop_requested,
    pause_requested,
    stats_provider,
    status_provider,
)

RESULT_HANDLERS = {
    CopyResult.STOPPED: lambda src_str: "[STOP] Shutdown requested while processing 'copy_with_dedup'",
    CopyResult.PAUSED: lambda src_str: "[PAUSE] Processing paused by user request",
    CopyResult.ERROR: lambda src_str: "[ERROR] Error occurred during processing 'copy_with_dedup'",
    CopyResult.COMPLETED: lambda src_str: f"[INFO] Completed processing source: {src_str}",
}


# Register signal handlers
def request_stop(signum, frame):
    log(f"[STOP] Received signal {signum}, requesting graceful shutdown")
    stop_requested.set()


signal.signal(signal.SIGINT, request_stop)
signal.signal(signal.SIGTERM, request_stop)


def resolve_ignore_patterns(dest_root: Path, script_dir: Path) -> list[str]:
    # Option A: global .importignore in destination root
    global_ignore = dest_root / ".importignore"
    patterns = load_ignore_file(global_ignore)
    if patterns:
        log(f"Loaded {len(patterns)} ignore patterns from {global_ignore}")
        return normalize_patterns(patterns)

    # Option C: fallback .importignore next to script
    local_ignore = script_dir / ".importignore"
    patterns = load_ignore_file(local_ignore)
    if patterns:
        log(f"Loaded {len(patterns)} ignore patterns from {local_ignore}")
        return normalize_patterns(patterns)

    log("No .importignore found; no ignore patterns loaded")
    return []


def FastImport(
    sources: List[Tuple[str, str]],
    destination: str,
    progress_count: int = 0,
    stats_path=None,
) -> None:
    dest_root = Path(destination)
    dest_root.mkdir(parents=True, exist_ok=True)

    log_path = dest_root / f"fastimport_{datetime.now().strftime('D%Y%m%dH%H%M%S')}.log"
    log_file = log_path.open("a", encoding="utf-8")
    set_log_file(log_file)

    db = open_db(dest_root / "fastimport_state.db")

    global_counter = {"total": 0}

    script_dir = Path(__file__).resolve().parent
    ignore_patterns = resolve_ignore_patterns(dest_root, script_dir)

    stats = Stats()
    stats.global_counters["ignore_patterns_used"] = ignore_patterns

    # Expose stats/status providers to control_server (optional, can refine later)
    def _status_provider():
        return "FastImport running"

    def _stats_provider():
        # For now, just return pretty_print output as text placeholder
        return "Stats available (wire real JSON later)"

    status_provider = _status_provider
    stats_provider = _stats_provider

    # Start control server in background
    launch_control_server()

    try:
        for src_str, label in sources:
            if stop_requested.is_set():
                log("[STOP] Shutdown requested before processing next source")
                break
            src_stats = stats.start_source(src_str, label)
            src = Path(src_str)
            dst = dest_root / label

            log(f"Source:      {src}")
            log(f"Destination: {dst}")

            dst.mkdir(parents=True, exist_ok=True)
            result = copy_with_dedup(
                src, dst, db, progress_count, global_counter, ignore_patterns
            )

            log(RESULT_HANDLERS.get(result, lambda s: "[INFO] Unknown result")(src_str))

            stats.finish_source(src_stats)

            if result is not CopyResult.COMPLETED:
                break

        log("[INFO] FastImport completed")
        stats.finish()

        if stats_path:
            stats.write_json(Path(stats_path))

        stats.pretty_print()
    finally:
        db.close()
        log_file.close()


if __name__ == "__main__":
    sources = [
        (r"Y:\\", "MediaDisk01"),
        (r"Z:\\", "JOFREMORENO-NO PELICULAS"),
    ]
    destination = r"C:\Public\Fast-Import"
    stats_path = Path(destination) / "fastimport-mediadisk1_jofremorenonopeliculas.json"
    FastImport(sources, destination, progress_count=500, stats_path=stats_path)
