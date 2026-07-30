import os
from pathlib import Path
from fnmatch import fnmatch

IS_WINDOWS = os.name == "nt"


def load_ignore_file(path: Path) -> list[str]:
    patterns: list[str] = []
    if not path.exists():
        return patterns

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    except Exception:
        # Logging is handled in main module; here we stay pure.
        pass

    return patterns


def normalize_patterns(patterns: list[str]) -> list[str]:
    if IS_WINDOWS:
        return [p.lower() for p in patterns]
    return patterns


def matches_ignore(name: str, is_dir: bool, patterns: list[str]) -> bool:
    """
    Semantics:
    - pattern ending with '/' => directory-only, exact name match (anywhere)
    - pattern without '/' and without wildcard => exact name match (file or dir)
    - pattern with wildcard => fnmatch on name (file or dir)
    - '!pattern' => negation, overrides previous matches
    """
    name_cmp = name.lower() if IS_WINDOWS else name

    matched = False
    for raw_pattern in patterns:
        pat = raw_pattern
        negated = pat.startswith("!")
        if negated:
            pat = pat[1:]

        pat_cmp = pat.lower() if IS_WINDOWS else pat

        # Directory-only pattern: "lib/"
        if pat_cmp.endswith("/"):
            base = pat_cmp[:-1]
            if is_dir and name_cmp == base:
                if negated:
                    matched = False
                else:
                    matched = True
            continue

        # Wildcard pattern
        if any(ch in pat_cmp for ch in "*?"):
            if fnmatch(name_cmp, pat_cmp):
                if negated:
                    matched = False
                else:
                    matched = True
            continue

        # Exact name pattern (file or dir)
        if name_cmp == pat_cmp:
            if negated:
                matched = False
            else:
                matched = True

    return matched
