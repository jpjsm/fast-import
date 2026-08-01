import json
import re
from pathlib import Path

META_PATTERNS = [
    re.compile(r"^Loaded"),
    re.compile(r"^Source:"),
    re.compile(r"^Destination:"),
    re.compile(r"^Done disk:"),
]


def match_meta(text: str):
    for pattern in META_PATTERNS:
        if pattern.match(text):
            return (True, pattern.pattern, text[len(pattern.pattern) + 1 :])
    return (False, None, None)


PROCESS_PATTERN = re.compile(r"^\[(?P<process>[A-Z-]+)\]\s*(?P<msg>.+)\s*$")


def match_process(text: str):
    match = PROCESS_PATTERN.match(text)
    if match:
        return (True, match.group("process"), match.group("msg"))
    return (False, None, None)


def logreader(path: str):
    logpath = Path(path)
    if not logpath.exists():
        raise FileNotFoundError(path)

    with open(logpath, "r", encoding="utf-8") as infile:
        lines = infile.readlines()

    stats = {"meta": dict(), "process": dict(), "other": 0}
    for line in lines:
        log = json.loads(line)

        is_process, process_name, process_msg = match_process(log["msg"])
        if is_process:
            if process_name not in stats["process"]:
                stats["process"][process_name] = 0

            stats["process"][process_name] += 1
            continue

        is_meta, meta_name, meta_msg = match_meta(log["msg"])
        if is_meta:
            if meta_name not in stats["meta"]:
                stats["meta"][meta_name] = 0

            stats["meta"][meta_name] += 1
            continue

        stats["other"] += 1
        print(f"[Warning] unexpected log msg: {log['msg']}")

    total_processed = 0
    print("PROCESSED STATISTICS")
    for key in sorted(stats["process"].keys()):
        print(f"-\t{key: <24s}: {stats['process'][key]: 10,d}")
        total_processed += stats["process"][key]

    print(f"-\t{'TOTAL PROCESSED': <24s}: {total_processed: 10,d}")

    total_processed = 0
    print("METADATA STATISTICS")
    for key in sorted(stats["meta"].keys()):
        print(f"-\t{key: <24s}: {stats['meta'][key]: 10,d}")
        total_processed += stats["meta"][key]

    print(f"-\t{'TOTAL PROCESSED': <24s}: {total_processed: 10,d}")

    print("UNEXPECTED STATISTICS")
    print(f"-\t{'other msgs': <24s}: {stats['other']: 10,d}")


if __name__ == "__main__":
    log_filename = r"C:\Public\Fast-Import\fastimport_D20260730H105604 - Copy.log"
    logreader(log_filename)
