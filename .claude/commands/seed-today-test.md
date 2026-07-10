Prime one or more synced course folders so a manual Quick Sync produces a known set of changes to visually verify the Today page (Today's files + the sync-history sibling).

The user supplies the course folder path(s). Default fixture is **5 New + 5 Clean Updates per folder**.

## Run

```
python scripts/seed_today_test.py "<folder 1>" "<folder 2>" ...
```

Useful flags:
- `--dry-run` — print the plan, change nothing. Do this first if the user seems unsure which folders they meant.
- `--new N` / `--updates M` — override the 5/5 default.

The app must be **closed** before running (it holds a lock on `.canvas_sync.db`; the script exits with a clear message if so).

## What it does

Per folder, in `.canvas_sync.db` + on disk:
- **New** — deletes N files from disk *and* their `sync_manifest` rows. Empty module folders are pruned.
- **Clean Update** — back-dates M rows' `canvas_updated_at` to `2020-01-01` and knocks `original_size` off by one byte, leaving `original_md5` matching the file on disk.

Candidates are spread across distinct module folders (smallest files first) so the history sibling has something interesting to group.

**This deletes files and takes no backup.** It is meant for disposable, re-downloadable course folders. If the user points it at a folder they care about, say so before running.

## Why the mutations are shaped that way

Both are non-obvious, and both were arrived at by reading the analyzer — don't "simplify" them:

- Deleting only the manifest row is **not enough** for a New file. `analyze_course` auto-discovers untracked on-disk files by name / md5 / unique size+ext and silently re-adopts them as *up-to-date*, so the file would never appear on the Today page. The file must go too, and `_would_be_adopted()` in the script rejects any candidate whose bytes another unclaimed file still on disk could claim.
- Back-dating `canvas_updated_at` alone is **not enough** for an Update. `_is_canvas_newer` ([core/sync_manager.py](../../core/sync_manager.py)) vetoes a newer Canvas timestamp as a "metadata touch" when the byte count is unchanged — hence the one-byte `original_size` lie. And `original_md5` must keep matching the on-disk file, or `_classify_local_modification` returns `'modified'` and the file lands in `updated_modified_files`, which **Quick Sync skips** (it only downloads `new` + `updates_clean`).

Only positive Canvas file ids are used as fixtures. Negative (synthetic) ids — announcements, pages, assignments — compare by content signature rather than timestamp and depend on the folder's secondary-content contract, so they make unreliable update fixtures.

## After running

Tell the user to open the app → **Today page → Quick Sync now**. It must be Quick Sync, not Analyze/Review/Sync: Today's files filters history on `sync_mode == 'quick'`.

The script self-verifies and prints `verify: PASS` per folder. Report:
1. Per folder: how many New / Clean Updates were primed, and which files.
2. Any rows it **skipped** because an unclaimed on-disk file would have re-adopted them (printed as `skipped N row(s)…`). These are usually leftover duplicates in the folder root; mention them, since they mean the folder yields fewer fixtures than requested.
3. Any `WARNING: only found X/N` — the folder ran out of clean, eligible files.
