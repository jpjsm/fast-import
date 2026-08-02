# FastImport Ignore-Based Cleanup — Dedup-Safe Deletion Algorithm

This document defines the **dedup-safe deletion algorithm** used by the
FastImport Ignore-Based Cleanup System. It describes how files and directories
matching `.importignore` are deleted while preserving dedup integrity and
keeping the FastImport database consistent.

This algorithm is the destructive counterpart to the dry-run format described
in `fastimport-ignore-cleanup-dryrun-format.md`.

---

## 1. Goals

The deletion algorithm must:

- safely delete files and directories matching `.importignore`
- respect dedup relationships (canonical targets and symlinks)
- update the FastImport database consistently
- remove stray files not tracked in the DB
- avoid breaking symlinks or leaving dangling references
- never delete outside the destination root

---

## 2. Inputs

- **Destination root**: directory tree where FastImport placed files.
- **`.importignore`**: patterns defining what must be removed.
- **FastImport database**: SQLite DB with at least:
  - `src_path`
  - `dst_path`
  - `hash`
  - `status` (`copied`, `symlink`, `dir_symlink`, `pending`, `corrupted_dir`, etc.)

---

## 3. High-Level Algorithm Overview

1. Load `.importignore` patterns.
2. Walk the destination tree (using `safe_walk`).
3. Classify each path:
   - in DB vs not in DB
   - file vs directory
   - symlink vs regular file
   - canonical dedup target vs non-dedup
4. Build dedup maps:
   - `hash -> [dst_paths]`
5. Determine deletion candidates:
   - symlinks matching `.importignore`
   - canonical dedup targets matching `.importignore`
   - regular files matching `.importignore`
   - stray files matching `.importignore`
   - directories matching `.importignore`
6. Delete in a safe order:
   - symlinks first
   - regular files
   - canonical dedup targets (only when safe)
   - directories
7. Update DB statuses to `deleted` where applicable.

---

## 4. Detailed Steps

### 4.1 Load Ignore Patterns

- Read `.importignore`.
- Normalize patterns (case, path separators).
- Use relative paths for matching.

### 4.2 Walk Destination with `safe_walk`

- Use `safe_walk(destination_root, ...)` to traverse.
- For each path:
  - compute relative path to destination root
  - determine type:
    - directory
    - regular file
    - symlink
  - check if it matches `.importignore`.

### 4.3 Query DB for Each Path

For each file path:

- Look up `dst_path` in DB:
  - If found:
    - read `hash`, `status`.
  - If not found:
    - classify as **stray file**.

For directories:

- DB presence is optional; directories may or may not be tracked.

### 4.4 Build Dedup Map

From DB:

- For all rows with non-NULL `hash`:
  - group by `hash`:
    - `hash -> [dst_paths]`

This map is used to determine:

- canonical dedup targets (`status='copied'`)
- symlinks (`status='symlink'`)
- how many paths reference each hash.

---

## 5. Deletion Order and Rules

### 5.1 Symlinks (First Pass)

For each symlink that:

- matches `.importignore`, and
- is inside destination root:

Perform:

1. **Delete symlink**:
   - `unlink(dst_path)`
2. **Update DB**:
   - `UPDATE files SET status='deleted' WHERE dst_path = ?`

Rationale:

- symlinks are leaves in the dedup graph.
- deleting them first prevents dangling references.

---

### 5.2 Regular Files (Second Pass)

For each regular file that:

- matches `.importignore`, and
- is inside destination root:

Case A: File is in DB (non-dedup or dedup canonical):

- If `hash` is NULL:
  - treat as non-dedup regular file.
  - **Delete file**.
  - **Update DB**: `status='deleted'`.

Case B: File is in DB with non-NULL `hash`:

- This may be a canonical dedup target.
- Defer deletion to the canonical pass (see 5.3).

Case C: File is **not in DB** (stray file):

- **Delete file**.
- No DB update (not tracked).

---

### 5.3 Canonical Dedup Targets (Third Pass)

For each canonical dedup target:

- `status='copied'`
- non-NULL `hash`
- matches `.importignore`

Determine reference count:

- `ref_count = len(hash_to_paths[hash])`

Rules:

- If `ref_count > 1`:
  - other paths (symlinks or copies) still reference this hash.
  - **Delete symlinks first** (already done in 5.1).
  - Recompute `ref_count` after symlink deletion.
- If `ref_count == 1`:
  - this is the only remaining path for this hash.
  - **Delete canonical file**.
  - **Update DB**: `status='deleted'`.

Rationale:

- canonical files must not be deleted while symlinks still depend on them.
- dedup integrity is preserved by deleting leaves first.

---

### 5.4 Directories (Fourth Pass)

For each directory that:

- matches `.importignore`, and
- is inside destination root:

Perform:

1. Recursively delete contents:
   - files (regular and symlink) using the same rules as above.
2. Delete directory itself when empty.

Additionally:

- After file deletion, remove any directories that become empty, even if they
  do not directly match `.importignore`.

---

## 6. Database Update Rules

For any path present in DB:

- When deleted:
  - `status` must be set to `'deleted'`.
- No rows are removed from DB.
- `src_path`, `dst_path`, and `hash` remain unchanged.

For stray files (not in DB):

- No DB updates are performed.

---

## 7. Safety Constraints

- Never delete files or directories outside the destination root.
- Always use `safe_walk` for traversal.
- Always normalize paths (case, separators, UNC) before DB comparison.
- Deletion must be preceded by a dry-run using the documented dry-run format.
- The deletion algorithm must not run in destructive mode without explicit
  confirmation.

---

## 8. Summary

The dedup-safe deletion algorithm ensures that:

- all files and directories matching `.importignore` are removed,
- dedup relationships are respected,
- symlinks are deleted before canonical targets,
- stray files not tracked in the DB are cleaned up,
- the FastImport database remains consistent and historically accurate.

This document explains *how* deletion is performed and *why* the order and rules
are structured as they are, so future maintainers can understand and safely
evolve the cleanup system.
