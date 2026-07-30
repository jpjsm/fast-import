import json
import time
from pathlib import Path


class Stats:
    def __init__(self):
        self.started_at = time.time()
        self.sources = []
        self.global_counters = {
            "total_items_seen": 0,
            "total_items_processed": 0,
            "total_items_skipped": 0,
            "total_files_copied": 0,
            "total_files_deduped": 0,
            "total_symlinks_created": 0,
            "total_dir_symlinks_created": 0,
            "total_errors": 0,
            "ignore_patterns_used": [],
        }

    def start_source(self, src: str, label: str):
        entry = {
            "source": src,
            "label": label,
            "items_seen": 0,
            "items_processed": 0,
            "items_skipped": 0,
            "files_copied": 0,
            "files_deduped": 0,
            "symlinks_created": 0,
            "dir_symlinks_created": 0,
            "errors": 0,
            "started_at": time.time(),
            "finished_at": None,
            "duration_seconds": None,
        }
        self.sources.append(entry)
        return entry

    def finish_source(self, entry):
        entry["finished_at"] = time.time()
        entry["duration_seconds"] = entry["finished_at"] - entry["started_at"]

    def finish(self):
        self.finished_at = time.time()
        self.duration_seconds = self.finished_at - self.started_at

    def to_json(self):
        return {
            "version": "1.0",
            "started_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.started_at)
            ),
            "finished_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.finished_at)
            ),
            "duration_seconds": self.duration_seconds,
            "global": self.global_counters,
            "sources": self.sources,
        }

    def write_json(self, path: Path):
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2)

    def pretty_print(self):
        print("\n========== FastImport Summary ==========")
        print(f"Total duration: {self.duration_seconds:.1f} seconds")
        print(
            f"Total items processed: {self.global_counters['total_items_processed']:,}"
        )
        print(f"Total items skipped: {self.global_counters['total_items_skipped']:,}")
        print(f"Files copied: {self.global_counters['total_files_copied']:,}")
        print(f"Files deduped: {self.global_counters['total_files_deduped']:,}")
        print(f"Symlinks created: {self.global_counters['total_symlinks_created']:,}")
        print(
            f"Directory symlinks created: {self.global_counters['total_dir_symlinks_created']:,}"
        )
        print(f"Errors: {self.global_counters['total_errors']:,}")
        print("\nSources:")
        for s in self.sources:
            print(f"  - {s['label']} ({s['source']})")
            print(f"      Items processed: {s['items_processed']:,}")
            print(f"      Items skipped:   {s['items_skipped']:,}")
            print(f"      Files copied:    {s['files_copied']:,}")
            print(f"      Files deduped:   {s['files_deduped']:,}")
            print(f"      Duration:        {s['duration_seconds']:.1f}s")
        print("========================================\n")
