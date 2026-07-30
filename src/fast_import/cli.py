import argparse
from fastimport import FastImport


def main():
    parser = argparse.ArgumentParser(description="FastImport ingestion tool")
    parser.add_argument("--dest", required=True, help="Destination root folder")
    parser.add_argument(
        "--source",
        action="append",
        nargs=2,
        metavar=("PATH", "LABEL"),
        help="Source path and label",
    )
    parser.add_argument("--progress", type=int, default=0, help="Progress interval")
    parser.add_argument("--stats", help="Write stats JSON to this file")

    args = parser.parse_args()

    FastImport(
        sources=args.source,
        destination=args.dest,
        progress_count=args.progress,
        stats_path=args.stats,
    )


if __name__ == "__main__":
    main()
