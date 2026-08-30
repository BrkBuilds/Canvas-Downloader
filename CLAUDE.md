# Canvas Downloader

Desktop app that batch-downloads Canvas LMS course material and keeps the folder in sync.
Python + Streamlit, rendered in a pywebview window, shipped as a signed `.exe` (Inno + MSIX)
and an ad-hoc-signed `.app` (PyInstaller). Runs entirely on the user's machine: no server,
no account, no telemetry. Licence GPL-3.0-or-later.

## Commands

```bash
python start.py                        # run the app as users see it (pywebview window)
streamlit run app.py                   # run the UI in a browser (faster dev loop)

pytest                                 # full suite, ~4,500 tests
pytest tests/test_folder_scope.py -x   # one file, stop on first failure
python scripts/verify_architecture.py  # architecture audit (Rules 4-11); must report 0

python scripts/build_windows.py                    # Windows: version_info -> PyInstaller -> Inno
pyinstaller --clean Canvas_Downloader_macOS.spec   # macOS bundle
```

Tests must be green before a mutation pass; the harnesses refuse a red baseline.

## Architecture

```
app.py            Download mode + app orchestrator (routing, session init)
sync_ui.py        Sync mode orchestrator
start.py          Launcher: daemon Streamlit thread + pywebview on the main thread
version.py        __version__ - read by CI and both build specs

ui/               Streamlit screens: auth, course_selector, download_settings,
                  hub_dialog, sync_dialogs, sync_review, sync_confirmation,
                  presets, institution_picker
core/             library (saved pairs/groups/daily), pair_labels, state_registry,
                  cancellation, canvas_logic (API + async download engine),
                  course_cache, sync_manager (SQLite manifest), preset_manager
sync/             analysis (diff), execution (background run), persistence, completion
engine/           progress_dashboard, estimation (ETA), post_processing_bridge,
                  applescript_bridge (macOS osascript)
converters/       post_processing pipeline + pdf/word/excel/code/md/url/video/archive
panopto/          discovery, auth, stream, transcribe, runner, shortcut, settings
shared/           helpers, components, theme (design tokens), institutions (generated)
styles/           static CSS injected once per page via inject_css()
scripts/          build + maintenance tooling (never bundled)
tests/            ~4,500 tests, incl. tests/audit/ (live-audit harness + runbooks)
docs/             THE PUBLISHED WEBSITE (canvasdownloader.app) - never put notes here
                  HAND-MAINTAINED. Edit the pages. The two data pages
                  (canvas-url-directory, canvas-data) are the only generated
                  ones - see .claude/rules/website.md
marketing/        launch, SEO and positioning register - LOCAL-ONLY, gitignored
```

**Runtime data files** (all gitignored - they hold real user data):
`sync_library.json` (saved pairs, groups, daily set), `canvas_sync_pairs.json`,
`canvas_sync_history.json`, `canvas_downloader_settings.json`, and a per-folder
hidden `.canvas_sync.db` SQLite manifest.

**The sync contract**: `.canvas_sync.db` is the single source of truth for a folder's
settings. `_show_sync_confirmation` reads the contract from the DB unconditionally -
there are no on-the-fly UI overrides.

## Rules that always apply

**A fix is not done until every site of its class has it.** This codebase's most expensive
recurring defect is a correct fix landing on some call sites and not others - `pdf_looks_real`
covered two of three delete sites for eight months; a scope rule existed in six places and one
disagreed. When you fix something, grep for the class and count the sites. Where practical,
write the test as a census that fails on a new unclassified site, not as a check that one fix
exists.

**Write a rule once.** A primitive with two implementations is a fix that lands on half the
app, silently: `make_long_path` had a copy in `core/sync_manager.py`, so a fix reached none of
the 26 manifest call sites. Three AppleScript escapers disagreed about `\r`. If you find a
second copy, make it an alias.

**Measure; do not reason.** Every non-obvious claim in the rule files was established by
driving the real thing and reading a number. State the measurement, not the conclusion. A
negative result from a diagnostic you have not controlled is worth nothing - prove your check
can still say yes.

**Verify in the REAL app.** A mock proves how Streamlit behaves, never that a change works
here. 1,431 passing tests did not see an `UnboundLocalError` that made a whole course download
nothing; one real run did. UI changes need a browser, before and after.

**Never destroy data on an error you have not identified.** Corruption must be proven, not
assumed - `sqlite3.OperationalError` is a `DatabaseError`, and treating it as corruption
deleted manifests over a transient lock. "Unreadable" is not "empty": `load -> mutate -> save`
on a failed read wipes the store. Quarantine damaged content; refuse to write on a transient
`OSError`.

**Escape everything that came from Canvas.** `esc()` for HTML; `md_escape()` for widget
labels, which are Markdown. Escape every piece of a split value, not just the half that looks
like text. `.upper()` is not a sanitiser.

**Always pass `encoding='utf-8'`.** Windows defaults to CP1252 and this app is full of Danish
characters and emoji. `UnicodeDecodeError` is a sibling of `JSONDecodeError`, not a subclass -
catch `ValueError` or name both.

**A silent `except Exception: pass` is a bug waiting to be invisible.** A swallowed hook
raised `NameError` on every tick for months and the only symptom was a panel that never
painted. Log at warning with `exc_info=True`. A destructive action that reports nothing is a
bug waiting to be un-diagnosable.

**Never edit source while a test suite or mutation pass is running.** `inspect.getsource`
resolves by line number, so an edit mid-run makes source-anchored tests read the wrong lines
and report a live guard as missing. A killed mutation pass restores its stale snapshot over
newer work - before believing a failure that follows one, `git diff` the source.

**Mutation-test new tests.** A passing suite is not evidence until you have flipped the real
code and watched it fail. Most gaps found here were in the tests, not the product.

**An article is a document, not a build artifact, and tests are for the APP.** A
generator that rebuilt the thirteen articles and `blog.html` from a Python file was
deleted 2026-08-31 after it twice reverted hand-edits made to the pages in between:
a script cannot know which of two copies is newer. Edit the pages. Only
`canvas-url-directory.html` and `canvas-data.html` are generated, because their
bodies are 4,757 rows of data. Website tests are limited to health - links resolve,
downloads reachable, content visible without JS - and never assert wording, a number
a human typed, or a colour. Three such tests were deleted the same day.

**Prose style**: no em dashes anywhere. Quote app copy character-exact rather than reflowing it.

**A document written for the product owner to READ is HTML, not Markdown.** Stated by
him 2026-08-28: raw Markdown is unreadable to him, so a `.md` deliverable is a document
nobody opens. This covers plans, scripts, briefs, reports and worklists - anything whose
audience is a person. It does not cover the registers Claude greps (`CLAUDE.md`,
`.claude/rules/`, `tests/audit/`), which stay Markdown. `marketing/` already had the
convention and it is now the rule: write the HTML, and do not also ship a `.md` twin of
the same content, because the copy nobody reads is the copy that goes stale.

## Where the detail lives

`.claude/rules/*.md` carry the hard-won specifics and load automatically when Claude opens a
matching file, so they cost nothing on unrelated work. Each entry states the mechanism, the
measurement, and why the obvious fix is wrong.

| Rule file | Loads when you touch |
|---|---|
| `streamlit-ui.md` | `app.py`, `sync_ui.py`, `ui/`, `styles/`, `shared/components.py` |
| `sync-engine.md` | `core/`, `sync/` |
| `converters-office.md` | `converters/`, `engine/applescript_bridge.py` |
| `panopto.md` | `panopto/` |
| `macos.md` | the macOS branches of converters, Panopto, auth, the mac spec |
| `data-safety.md` | `core/`, `shared/`, `ui/auth.py` - stores, long paths, silent failures |
| `testing-and-audits.md` | `tests/`, `scripts/_mutate_*.py` |
| `release-and-packaging.md` | specs, `scripts/build_*`, workflows, `msix/` |
| `institution-picker.md` | `ui/institution_picker.py`, `shared/institutions.py` |
| `website.md` | `docs/`, `marketing/` |

Read `streamlit-ui.md` before any UI change. Streamlit reconciles by INDEX, so a conditional
element, a stray `st.empty()` or a dialog invoked mid-page can silently mis-style or delete an
unrelated component. Those failures are invisible in code review and obvious in a screenshot.

Other registers, read on demand rather than loaded:

- `tests/audit/AUDIT_PLAYBOOK.md` - the offline crash/data-loss audit: technique ranking, the
  sweeps that came back clean and must not be repeated, and the mutation-harness hazards.
- `tests/audit/README.md`, `RUNBOOK.md`, `MAC_RUNBOOK.md` - the live audit (real app, real
  browser, real Canvas, five oracles) and its findings register.
- `marketing/README.md` - index for launch, SEO and positioning; `FINDINGS.md` is the register
  and `STRATEGY.md` holds settled decisions. The whole folder is gitignored as of 2026-08-28,
  so it is NOT in a fresh clone and nothing tracked may depend on a file inside it: a test
  that read `marketing/STORE_LISTING.md` turned both CI workflows red with 15 failures the
  first push after the untracking, and was deleted rather than gated.

Anything durable belongs in the repo, in the same commit as the fix. Auto-memory is
machine-local and does not travel between machines; this repo does.
