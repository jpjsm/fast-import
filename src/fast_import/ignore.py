import os
import fnmatch
import yaml
from pathlib import Path


class IgnoreEngine:
    """
    FastImport ignore rule engine.
    Loads importignore.yml and provides OS-aware ignore checks for:
    - folders
    - files
    - extensions
    - wildcard patterns
    """

    CASE_INSENSITIVE = os.name == "nt"  # Windows only

    def __init__(self, yaml_path: Path):
        self.data = self._load_yaml(yaml_path)
        self.rules = self._normalize_rules(self.data)
        self.patterns = self._normalize_patterns(self.data.get("patterns", []))

    # ------------------------------------------------------------
    # YAML LOADING
    # ------------------------------------------------------------
    def _load_yaml(self, path: Path):
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    # ------------------------------------------------------------
    # NORMALIZATION
    # ------------------------------------------------------------
    def _normalize_value(self, value: str) -> str:
        return value.lower() if self.CASE_INSENSITIVE else value

    def _normalize_patterns(self, patterns):
        return [self._normalize_value(p) for p in patterns]

    def _normalize_rules(self, data):
        folders = set()
        files = set()
        extensions = set()

        # Folders
        for category, entry in data.get("folders", {}).items():
            for v in entry.get("values", []):
                folders.add(self._normalize_value(v))

        # Files
        for category, entry in data.get("files", {}).items():
            for v in entry.get("values", []):
                files.add(self._normalize_value(v))

        # Extensions
        for category, entry in data.get("extensions", {}).items():
            for v in entry.get("values", []):
                extensions.add(self._normalize_extension(v))

        return {
            "folders": folders,
            "files": files,
            "extensions": extensions,
        }

    # ------------------------------------------------------------
    # EXTENSION NORMALIZATION
    # ------------------------------------------------------------
    def _normalize_extension(self, ext: str) -> str:
        if not ext:
            return ""

        # If someone passes a filename instead of an extension
        if "." in ext:
            ext = ext.rsplit(".", 1)[-1]

        # Strip leading dots
        ext = ext.lstrip(".")

        # Extensions should ALWAYS be lowercase
        # (case-insensitive everywhere)
        ext = ext.lower()

        return ext

    # ------------------------------------------------------------
    # IGNORE CHECKS
    # ------------------------------------------------------------
    def ignore_folder(self, name: str) -> bool:
        name = self._normalize_value(name)
        return name in self.rules["folders"]

    def ignore_file(self, name: str) -> bool:
        name_norm = self._normalize_value(name)

        # Direct match
        if name_norm in self.rules["files"]:
            return True

        # Wildcard patterns
        if any(fnmatch.fnmatch(name_norm, p) for p in self.patterns):
            return True

        return False

    def ignore_extension(self, ext: str) -> bool:
        ext_norm = self._normalize_extension(ext)
        if not ext_norm:
            return False
        return ext_norm in self.rules["extensions"]
