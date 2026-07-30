import os
from pathlib import Path
from typing import List, Tuple

from db import open_db
from fs import set_log_file, log
from ignore import load_ignore_file, normalize_patterns
from importer import copy_with_dedup
from stats import Stats


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

    log_path = dest_root / "fastimport.log"
    log_file = log_path.open("a", encoding="utf-8")
    set_log_file(log_file)

    db = open_db(dest_root / "copy_state.db")

    global_counter = {"total": 0}

    script_dir = Path(__file__).resolve().parent
    ignore_patterns = resolve_ignore_patterns(dest_root, script_dir)

    stats = Stats()
    stats.global_counters["ignore_patterns_used"] = ignore_patterns

    try:
        for src_str, label in sources:
            src_stats = stats.start_source(src_str, label)
            src = Path(src_str)
            dst = dest_root / label

            log(f"Source:      {src}")
            log(f"Destination: {dst}")

            dst.mkdir(parents=True, exist_ok=True)
            copy_with_dedup(
                src, dst, db, progress_count, global_counter, ignore_patterns
            )
            stats.finish_source(src_stats)

        log("FastImport completed")
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
