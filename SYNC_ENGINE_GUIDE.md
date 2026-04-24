# How Smart Sync Works — A Student's Guide

Canvas Downloader's **Sync mode** keeps your local course folders up to date with Canvas *without ever destroying your work*. This guide explains exactly what the sync engine does, why it makes the decisions it makes, and how to use it effectively for your studies.

It's written for the actual humans who use this app — university students who download lectures, annotate slides, take notes on readings, and want their files to stay organized across a whole semester without lifting a finger.

---

## 1. The Goal

Imagine it's week 8 of the semester. You've got a folder on your laptop called `Organic Chemistry 2026`. Over the past two months it has filled up with:

- Lecture slides from each week (some annotated in GoodNotes or Adobe)
- Problem sets (some you've solved on, others untouched)
- A few PDFs you dragged out because you didn't want them anymore
- A syllabus from week 1
- A couple of files you renamed to make them easier to find

Meanwhile on Canvas, your professor has:

- Uploaded new lecture slides for weeks 7 and 8
- Fixed a typo in the week-3 slides and re-uploaded them
- Taken down the draft of a problem set he decided not to use

**You want one button that handles all of this correctly.** That button is **Sync**. The hard part is making sure it never overwrites your annotations, never re-downloads files you intentionally deleted, and never leaves you wondering which version of a file is the "real" one.

That's what the sync engine is built to do.

---

## 2. The Categories

When you run an analysis, every file ends up in one of seven buckets. Understanding these is the whole game.

### 🆕 New Files
Files Canvas has that you don't. Simple as that.

- **Default:** Checked ✅ — you almost always want these.
- **Behavior:** Downloaded fresh into the correct subfolder.

### 🔄 Updates Available *(clean)*
Canvas has a newer version of a file, AND you haven't touched your local copy.

- **Default:** Checked ✅
- **Behavior:** Your local file is **replaced in place** with the new Canvas version. No `_NewVersion` suffix, no clutter. The old file is gone — but since you hadn't edited it, there was nothing to lose.
- **How we know:** We take a fingerprint (called an **MD5 hash**) of your local file the moment we download it, and we store that fingerprint in a hidden database. When Canvas says there's an update, we take a fresh fingerprint of your current file. If the two match bit-for-bit, we know you haven't changed anything, and we're safe to overwrite.

### ✏️ Updates Available — You've Edited These *(modified)*
Canvas has a newer version, AND your local fingerprint has changed — meaning you annotated, filled out, highlighted, or otherwise modified your copy.

- **Default:** *Unchecked* ☐ — we don't touch edited files unless you explicitly opt in.
- **Behavior (if you opt in):** The new Canvas version is saved **alongside** your edited file as `filename_NewVersion.ext`. Your annotated original is **never touched**.
- **Why this matters:** If you spent two hours annotating `Lecture_3.pdf` and your prof fixes a typo, you don't want the app silently erasing your notes. By defaulting this off, the app assumes your edits are precious.

### 📦 Locally Deleted
Files that Canvas has, that you downloaded before, and that you since deleted from your disk.

- **Default:** *Unchecked* ☐ — we assume the deletion was intentional.
- **Behavior (if you opt in):** Re-downloaded to the original folder.
- **Why this matters:** If you deleted `week_1_intro_slides.pdf` in week 9 because you're cramming for midterms and don't need it anymore, you don't want it back. The app respects that.

### 🗑️ Deleted on Canvas *(Kept Locally)*
Files that used to be on Canvas but the teacher removed. You still have your local copy.

- **Default:** *No checkbox at all* — this is informational only.
- **Behavior:** The app never deletes files from your disk. Ever. Period. If the teacher pulls down a study guide the night before the exam, the app tells you that Canvas no longer hosts it, but your copy on disk is safe.

### ✔️ Up-to-date
Files that are identical on both sides (Canvas + local), with matching fingerprints/timestamps.

- **Default:** Hidden from the review screen. No action needed.
- **Shown as:** A small `✔ N files up to date` tag on each course header.

### 🚫 Ignored Files
Files you've chosen to permanently skip.

- **Default:** Collapsed at the bottom of each course.
- **Behavior:** These never appear in future syncs — the app stops asking about them. You can restore any of them with a single click.
- **Use case:** The course has a 2 GB video lecture series you don't want. Ignore them once, and they're gone from your review forever.

---

## 3. Under the Hood: The Manifest

The secret to making sync work is keeping track of **what each file looked like the last time we saw it**. The app does this with a small hidden SQLite database called `.canvas_sync.db`, stored inside each course folder. We call it the **manifest**.

For every file the app has ever downloaded into this folder, the manifest stores:

| Field | What it means |
|---|---|
| `canvas_file_id` | Canvas's unique ID for the file |
| `canvas_filename` | The filename Canvas used |
| `local_path` | Where the file lives inside your course folder (e.g. `Week 3/lecture.pdf`) |
| `canvas_updated_at` | The timestamp Canvas reported for the file when we downloaded it |
| `downloaded_at` | When we actually wrote it to your disk |
| `original_size` | File size in bytes |
| `original_md5` | The cryptographic fingerprint at the moment of download |
| `is_ignored` | Whether you've marked it "don't sync" |

This manifest is what lets the app answer questions like:

- "Did the user edit this file?" (compare current MD5 to `original_md5`)
- "Where does this file live? (read `local_path`)"
- "Has the teacher updated this since we grabbed it?" (compare Canvas's `updated_at` to ours)
- "Is this file one the user deleted on purpose?" (file is in manifest but missing on disk with `downloaded_at` set)

The manifest is automatically created on your first download and updated every time you sync. It's safe to back up, and the app can rebuild it if it ever gets corrupted.

---

## 4. The Analysis Phase

When you click **Analyze**, the app does the following for each course folder:

1. **Connects to Canvas** and pulls the full list of files the teacher has shared, including module items, assignments, pages, quizzes, etc.
2. **Loads the manifest** from `.canvas_sync.db` so it knows what was previously downloaded.
3. **Heals the manifest** — scans your folder for files that may have been **renamed or moved** by you or your OS. It uses three tiers of matching:
   - **Exact filename match** (the file is still there, just in a different location)
   - **Exact MD5 match** (you renamed it, but the content is the same)
   - **Fuzzy filename match** (>85% similar) — for files you renamed AND whose Canvas-reported name has small differences like extra whitespace
4. **Walks your folder** looking for local copies of each Canvas file.
5. **Classifies every file** into one of the seven buckets above.
6. **Computes fingerprints for update candidates** — when Canvas reports a file is newer, the app re-fingerprints your local copy and compares it against `original_md5` to decide whether to bucket it as "clean update" or "edited locally."

One clever optimization: **Canvas sometimes exposes its own MD5 for a file.** When it does, we compare Canvas's MD5 against the one in our manifest. If they match, we know the file content is byte-identical regardless of what the timestamp says — so we skip the update entirely. This eliminates a very common annoyance where the teacher "touches" a file (changes permissions, edits the description, etc.) and Canvas bumps the timestamp even though the actual content never changed.

**Performance note:** If a file is larger than 50 MB, the app skips the MD5 fingerprint comparison and treats it as clean. Running a full hash on a 1 GB lecture video every analysis would slow you down for no real benefit — you're very unlikely to be annotating big videos.

---

## 5. The Review Phase

After analysis, you land on the **Review screen**. Each course has its own expandable card, and within each card, you see only the buckets that have files in them.

### Metric summary at the top

Five colored tiles give you the big picture:

- **New files** (blue)
- **Updates available** (green) — total clean + modified count
- **Edited locally** (orange) — subset showing how many of those updates are modified
- **Deleted locally** (purple)
- **Deleted on Canvas** (red)

This answers the first question on your mind: *"How much stuff changed, and do I need to pay attention to anything risky?"*

If the "Edited locally" tile shows `0`, you know you can hit Sync without thinking. If it shows `3`, you know three of your edited files need your attention.

### Expanders per category

Each category is a collapsible section. Inside, you see the actual file list with checkboxes. Each checkbox's default is set intelligently:

- **New Files** → all checked
- **Updates Available (clean)** → all checked
- **Updates Available — You've Edited These** → all *unchecked* (protect your edits)
- **Locally Deleted** → all *unchecked* (respect your deletion)

You can:
- **Individually check/uncheck** any file
- **Filter by file extension** at the top (e.g. show only PDFs, hide all videos)
- **Ignore files** permanently with the per-file ignore button
- **Bulk-ignore** unchecked files in a section via the "Move deselected to Ignored" button
- **Restore ignored files** from the Ignored Files section at the bottom

### Confirmation dialog

When you click **Sync & Download**, a confirmation modal appears. It shows:

- Total file count and combined size
- Destination folder(s)
- A disk space check against the drive's available capacity
- **A yellow warning** if any of the files in the queue are ones you've edited locally, explaining that those will be saved as `_NewVersion` rather than replacing your copy

No surprises. Everything the sync is about to do is disclosed before you commit.

---

## 6. The Sync Phase

Once you confirm, the actual download starts. Here's what happens behind the scenes:

### File routing

Every selected file is routed to exactly one of these write strategies:

| Selection | Write strategy |
|---|---|
| New file | Written to its correct module subfolder (or flat, depending on your folder structure) |
| Clean update | **Overwrites** the old file in place. Same name, same location. Clean folder, no clutter. |
| Modified update | Saved as `{filename}_NewVersion.{ext}` alongside your edited copy. If `_NewVersion` already exists from a previous sync, a numeric suffix is added: `(1)`, `(2)`, etc. |
| Locally-deleted redownload | Restored to its original path as if it had never been deleted. |

### Safety rails during writing

- **If clean overwrite fails** (you have the file open in Adobe Reader on Windows, for example), the app automatically falls back to `_NewVersion` mode instead of crashing. You'll get the new file, your old one stays, and the sync continues.
- **If the download fails** (network dropped, Canvas is flaky), the file is added to a retry queue and the sync engine tries again with full backoff.
- **If you cancel mid-sync**, the app stops immediately at a safe boundary — no half-written files.

### After the last file writes

1. The manifest gets updated: every newly-downloaded file's `canvas_updated_at`, `downloaded_at`, `original_size`, and `original_md5` are written to the database. Your "pristine state" snapshot is refreshed.
2. A log file called `☁️ Canvas Updates & Deletions.txt` is appended to each course folder, recording everything that was updated or removed by the teacher. You can always open this file to see a human-readable audit trail.
3. Post-processing runs (if you have those options enabled) — for example, converting PPTX files to PDF, extracting ZIP archives, converting URL shortcuts to readable HTML.
4. The completion screen shows a summary with per-course file counts, synced sizes, and any errors.

---

## 7. Quick Sync

**Quick Sync** is the "I trust it, just do it" button. Clicking it skips the Review screen entirely and performs the sync immediately.

### What Quick Sync syncs
- ✅ **All new files** on Canvas
- ✅ **All clean updates** (files whose local copy you haven't edited)

### What Quick Sync deliberately skips
- ❌ **Modified updates** — files you've edited locally. These always require manual review so you can decide how to handle your annotations.
- ❌ **Locally deleted files** — files you intentionally removed. Quick Sync won't resurrect them.
- ❌ **Nothing is ever deleted** — Canvas-deleted files remain on your disk regardless.

The philosophy: **Quick Sync should never produce a surprising result.** It does the things you'd obviously want done, and stops at any decision that needs your judgment.

After Quick Sync completes, the completion screen will tell you if any files were skipped and why. If it says "Quick Sync skipped 3 files you edited locally and 2 locally deleted files," that's your cue to run a normal Analyze + Review if you want to handle them.

### When to use which

| Situation | Use |
|---|---|
| Checking for fresh content between lectures | **Quick Sync** |
| Start-of-week bulk catch-up | **Quick Sync** |
| Just before an exam when you want everything | **Normal Sync** (full review) |
| You know you've annotated files this week | **Normal Sync** (to handle modified updates explicitly) |
| First time setting up a new course folder | **Normal Sync** (so you can see what you're getting) |

---

## 8. Edge Cases and How They're Handled

### The teacher renamed a file
Canvas treats the renamed file as the same ID. The app reads Canvas's new name, compares against the manifest, and if the file content hasn't changed, nothing happens. If the name changed AND the content changed, it appears as an update.

### You renamed a file
The **heal manifest** step catches this. On the next analysis, the app sees the old path doesn't exist but notices a nearby file with a matching MD5 or highly similar name. It updates the manifest's `local_path` to track the new location. No duplicate download, no broken sync.

### You moved a file into a subfolder
Same as rename — the heal step picks it up and updates the manifest path.

### The teacher deleted a file and immediately uploaded a new one with the same name
Canvas treats this as *delete + create* (different file IDs). The app is smarter than that. It sees an incoming "new" file with the same filename as one you have locally, recognizes the pattern as a teacher re-upload, and treats it as an **update** instead — so you get the normal update behavior (overwrite or `_NewVersion`) rather than winding up with two files.

### You deleted a file locally but also ignored it
Ignored wins. The file doesn't appear in any bucket — the app respects your "I permanently don't want this" choice.

### You restored an ignored file
It goes back to whichever category it was in before you ignored it (new, update-clean, update-modified, or locally-deleted), with its appropriate default. For *modified updates* restored from ignored, the checkbox comes back **unchecked** — we figure you probably ignored it because you wanted to keep your edits.

### You have a large video file and the teacher "touched" it on Canvas
Canvas might report it as newer, but our file-size-based fast path treats files >50 MB as clean without re-hashing them. If Canvas actually provides its own MD5 for the file, we also gate on that — so a no-op "touch" from the teacher gets filtered out entirely and the file stays in "Up to date."

### Your `.canvas_sync.db` database gets corrupted
The app detects corruption on startup, renames the bad database as `.canvas_sync_corrupted.db`, and rebuilds a fresh manifest by scanning your existing files. You won't lose anything — on the next sync, files you already have will be auto-discovered and marked as up-to-date.

### You're running out of disk space
The confirmation dialog includes a disk-space check. If the sync would push you below 1 GB of free space, it blocks and warns you.

---

## 9. What the App Will Never Do

This is short but important. By design, the sync engine **guarantees**:

1. It will **never overwrite a file you've edited** without your explicit consent. Modified files always get the `_NewVersion` treatment.
2. It will **never delete a local file**. Not even when the teacher removes it from Canvas. Not even when you ignore a file. Your disk is sovereign territory.
3. It will **never re-download a file you intentionally deleted** unless you explicitly check the box.
4. It will **never silently create duplicates**. Every file you download is tracked in the manifest; every re-download either overwrites a clean original or creates a clearly-named `_NewVersion`.
5. It will **never modify files outside your course folder**. The sync engine only touches paths inside the folder you paired with a course.

---

## 10. Practical Tips

### Set up one course folder per Canvas course
Mixing multiple courses in one folder will confuse the heal step. One folder = one course = one manifest.

### Annotate confidently
If you annotate a PDF inside your synced folder, the app detects it automatically on the next analysis. You don't have to tell it anything. The MD5 fingerprint comparison handles it invisibly.

### Rename files freely
Go ahead and rename `lecture_1_draft_final_FINAL (1).pdf` to `Week 1 - Intro.pdf`. The heal step tracks renames. The file stays linked to its Canvas ID.

### Use "Ignore" liberally
If a course has files you never want — old recordings, draft docs, optional readings — ignore them once and they disappear from every future sync. Your review screen stays focused on things that actually matter.

### Quick Sync between lectures
Quick Sync is the ideal "between classes" tool. Open the app, hit Quick Sync All, grab your new slides, and go. It takes seconds.

### Use Normal Sync before exams
When it matters, run a full analysis. Check every bucket. Make sure nothing important is sitting in "Locally Deleted" or "Edited These" that you forgot about.

### Trust the log file
`☁️ Canvas Updates & Deletions.txt` inside each course folder is an append-only diary of what the teacher changed. If you're ever unsure "did this file get updated at some point?", open that file.

---

## 11. Summary

The sync engine treats your local folder as **yours** and Canvas as **a source of new content**. It never flows the other direction — Canvas can't cause data loss on your disk.

The seven-bucket classification with MD5-aware update splitting means that for any given file, the app can tell you exactly one of these stories:

- *"You don't have this — want it?"* (New)
- *"Canvas updated this; your copy is pristine so I'll just refresh it."* (Clean update)
- *"Canvas updated this, but I see you've edited yours; want the new one saved alongside?"* (Modified update)
- *"You deleted this on purpose; want it back?"* (Locally deleted)
- *"The teacher took this down, but your copy is safe."* (Deleted on Canvas)
- *"Nothing to do — you're current."* (Up to date)
- *"You told me to stop asking about this."* (Ignored)

Every default, every color, every caption in the UI is chosen to communicate the *right* story for that file. When in doubt, the app errs on the side of preserving your work.

That's the whole system. Happy syncing — and good luck with finals.
