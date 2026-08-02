# FastImport Cleanup — Dry‑Run Output Format Specification

This document defines the official dry‑run output format for the FastImport
Ignore‑Based Cleanup System. The dry‑run mode provides a safe, non‑destructive
preview of all cleanup actions that would occur when removing files and
directories matching `.importignore` patterns, while respecting FastImport’s
dedup database and symlink relationships.

Dry‑run mode is the default and must be used before any destructive cleanup
operation.

---

## 1. Header Section

The dry‑run output begins with a contextual header summarizing the environment
and configuration used for cleanup.

```txt
=== FastImport Cleanup (DRY RUN) ===
Destination: <path>
Ignore file: <path>
DB: <path>
Timestamp: <ISO8601 or local time>
```

This section confirms:

- the destination root being scanned  
- the `.importignore` file used  
- the database file used  
- the exact time the dry‑run was executed  

---

## 2. Ignore Patterns Summary

A list of all ignore patterns loaded from `.importignore`.

```txt
--- Ignore Patterns Loaded (N) ---
*.wtv
*.exe
*.dll
pycache/
temp/
backup/
...
```

This section allows the user to visually verify that the ignore file is correct
before cleanup proceeds.

---

## 3. Files Matching Ignore Patterns (Grouped)

Files and symlinks matching `.importignore` are grouped by type for clarity and
dedup‑safe processing.

### 3.1 Symlinks Matching Ignore Patterns

Symlinks are always deleted first.

```txt
--- Symlinks Matching Ignore Patterns (N) ---
[SYMLINK] Movies/Show1/episode1.wtv -> Movies/Show1/episode1_canonical.wtv
[SYMLINK] Apps/Installer/setup.exe -> Apps/Installer/setup_canonical.exe
...
```

Each entry shows:

- the symlink path  
- the canonical target it points to  

---

### 3.2 Canonical Dedup Targets Matching Ignore Patterns

Canonical dedup targets (`status='copied'`) are shown with their hash and
reference count.

```txt
--- Canonical Dedup Targets Matching Ignore Patterns (N) ---
[COPY] Movies/Show1/episode1_canonical.wtv (hash: ABC123)
referenced by: 2 symlinks (will NOT delete until symlinks removed)

[COPY] Apps/Installer/setup_canonical.exe (hash: DEF456)
referenced by: 0 symlinks (SAFE TO DELETE)
```

This section ensures dedup integrity by clearly distinguishing safe vs unsafe
canonical deletions.

---

### 3.3 Regular Files Matching Ignore Patterns

Regular copied files that match `.importignore`.

```txt
--- Regular Files Matching Ignore Patterns (N) ---
[FILE] Apps/Tools/old_tool.dll
[FILE] Temp/cache.tmp
...
```

These files were copied normally (not deduped) and are safe to delete.

---

## 4. Stray Files (Not in DB)

Files present in the destination but not tracked in the FastImport database.

```txt
--- Stray Files Matching Ignore Patterns (N) ---
[STRAY] Movies/Old/episode3.wtv
[STRAY] Apps/Debug/trace.log
...
```

These files are always safe to delete if they match `.importignore`.

---

## 5. Directories Matching Ignore Patterns

Directories matching `.importignore` are listed for recursive deletion.

```txt
--- Directories Matching Ignore Patterns (N) ---
[DIR] pycache/
[DIR] Temp/
[DIR] Backup/
...
```

Empty directories created as a result of file deletion may also be removed.

---

## 6. DB Updates (Preview Only)

A preview of all database updates that would occur during cleanup.

```txt
--- DB Updates (Preview) ---
UPDATE files SET status='deleted' WHERE dst_path='Movies/Show1/episode1.wtv'
UPDATE files SET status='deleted' WHERE dst_path='Apps/Tools/old_tool.dll'
...
```

This section ensures DB consistency and allows the user to verify that the
correct entries will be updated.

---

## 7. Summary

A final summary of all cleanup actions that *would* occur.

```txt
=== Summary (DRY RUN) ===
Symlinks to delete: N
Canonical dedup targets: N (X safe, Y deferred)
Regular files: N
Stray files: N
Directories: N
DB updates: N
----------------------------------------
No changes have been made (dry-run mode).
```

This section provides a quick overview of the cleanup impact and confirms that
no destructive actions were performed.

---

## Notes

- Dry‑run mode must be the default for all cleanup operations.  
- The output format must remain stable to allow diffing and automated review.  
- All paths shown in dry‑run output must be **relative to the destination root**.  
- No deletion or DB modification occurs during dry‑run mode.

---

## Document Name

Recommended filename: `docs/fastimport-ignore-cleanup-dryrun-format.md`

This document explains *why* the dry‑run format exists and *how* it works,
ensuring future maintainers understand the design decisions behind FastImport’s
cleanup system.
