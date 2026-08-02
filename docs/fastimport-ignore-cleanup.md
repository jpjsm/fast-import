# 📘 FastImport Cleanup Rules — Final Specification

## 1. Purpose

The FastImport Cleanup System removes files and directories inside a **destination root** that should not exist according to the project’s ignore policy (`.importignore`).  
It ensures:

- consistency with FastImport’s dedup database  
- safe deletion of symlinks and canonical dedup targets  
- removal of stray files not tracked in the DB  
- dry‑run safety by default  
- predictable behavior across all file types

---

## 2. Inputs

### 2.1 Destination Root

The directory tree where FastImport placed files.

### 2.2 `.importignore`

A file containing patterns that define **what must be removed**.

Patterns may include:

- file extensions (`*.wtv`, `*.exe`, `*.dll`)  
- directory names (`__pycache__/`, `temp/`)  
- wildcard patterns  
- nested paths  

### 2.3 FastImport Database

The SQLite DB containing:

- `src_path`  
- `dst_path`  
- `hash`  
- `status` (`copied`, `symlink`, `dir_symlink`, `pending`, `corrupted_dir`, etc.)

This DB defines dedup relationships.

### 2.4 Dry‑Run Mode (default)

Cleanup must **not delete anything** unless explicitly requested.

---

## 3. Definitions

### 3.1 Canonical Dedup Target

A file with:

- `status = 'copied'`  
- a non‑NULL `hash`  
- one or more symlinks pointing to it  

### 3.2 Dedup Symlink

A file with:

- `status = 'symlink'`  
- `dst_path` pointing to a canonical dedup target  

### 3.3 Stray File

A file inside destination that:

- exists on disk  
- **is NOT present in the DB**  

These must be treated carefully.

---

## 4. Cleanup Rules (Authoritative)

### Rule 1 — Use `.importignore` as the single source of truth

A file or directory is eligible for deletion **only if** its **relative path** matches `.importignore`.

Matching must use:

- full relative path  
- directory awareness  
- wildcard expansion  
- case normalization (Windows)

---

### Rule 2 — Delete symlinks first

If a symlink matches `.importignore`, it must be deleted **before** any canonical file.

This prevents dangling references.

---

### Rule 3 — Delete canonical dedup targets only when safe

A canonical dedup target (`status='copied'`) may be deleted **only if**:

- it matches `.importignore`, **and**
- **no symlinks reference its hash**, **and**
- it is not referenced by any other file type

If symlinks exist:

- delete symlinks first  
- re‑evaluate canonical file  
- delete canonical file only when safe  

---

### Rule 4 — Delete stray files not in DB

If a file exists in destination but **is not in the DB**, and it matches `.importignore`, it must be deleted.

This includes:

- old development artifacts  
- files copied before FastImport existed  
- files copied before `.importignore` was correct  
- manually copied files  
- leftover dedup targets from early versions  
- orphaned symlinks  

This rule is essential.

---

### Rule 5 — Delete stray directories not in DB

If a directory matches `.importignore`, delete it recursively.

If a directory does **not** match `.importignore`, but becomes empty after cleanup, delete it.

---

### Rule 6 — Update DB status correctly

For files present in DB:

- set `status = 'deleted'`  
- do not remove DB rows  
- do not modify `hash`  
- do not modify `src_path`  

This preserves historical integrity.

---

### Rule 7 — Dry‑Run Mode is mandatory by default

Dry‑run must:

- list files that would be deleted  
- list directories that would be deleted  
- list DB entries that would be updated  
- list dedup relationships  
- list canonical files that would be removed  
- list stray files not in DB  
- list stray directories not in DB  

Dry‑run must **not**:

- delete files  
- unlink symlinks  
- update DB  
- remove directories  

Dry‑run is the default mode.

---

### Rule 8 — Use `safe_walk` instead of `os.walk`

Cleanup must use FastImport’s `safe_walk` to avoid:

- reparse point traversal  
- junction loops  
- permission errors  
- corrupted directories  
- locked files  

This ensures consistency with FastImport’s behavior.

---

### Rule 9 — Normalize paths consistently

On Windows:

- lowercase  
- resolve  
- normalize slashes  
- normalize UNC prefixes  

This ensures DB comparisons are correct.

---

### Rule 10 — Never delete outside destination

Even if `.importignore` matches a pattern, cleanup must **never** delete files outside the destination root.

---

## 5. Summary Table

| Case | In DB? | Matches `.importignore`? | Action |
| ------ | -------- | --------------------------- | -------- |
| Canonical dedup target | Yes | Yes | Delete **only if** no symlinks reference it |
| Dedup symlink | Yes | Yes | Delete |
| Regular copied file | Yes | Yes | Delete |
| Directory | Yes/No | Yes | Delete recursively |
| Stray file | No | Yes | Delete |
| Stray directory | No | Yes | Delete recursively |
| Any file | Yes/No | No | Keep |
| Canonical dedup target with symlinks | Yes | Yes | Delete symlinks first, then re‑evaluate |

---
