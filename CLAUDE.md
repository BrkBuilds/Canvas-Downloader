# Canvas Downloader

Desktop app that batch-downloads Canvas LMS course material and keeps the folder in sync.
Python + Streamlit, rendered in a pywebview window, shipped as a signed `.exe` (Inno + MSIX)
and an ad-hoc-signed `.app` (PyInstaller). Runs entirely on the user's machine: no server,
no account, no telemetry. Licence GPL-3.0-or-later.

## Commands

```bash
python start.py                        # run the app as users see it (pywebview window)
python dev.py                          # app in YOUR browser, sign-in window WORKS
streamlit run app.py                   # UI in a browser; CANNOT open the sign-in window

python scripts/check_handoff.py        # the browser-extension handoff, without Chrome

pytest                                 # full suite, ~4,500 tests
pytest tests/test_folder_scope.py -x   # one file, stop on first failure
python scripts/verify_architecture.py  # architecture audit (Rules 4-11); must report 0

python scripts/build_windows.py                    # Windows: version_info -> PyInstaller -> Inno
pyinstaller --clean Canvas_Downloader_macOS.spec   # macOS bundle
```

Tests must be green before a mutation pass; the harnesses refuse a red baseline.

**`streamlit run app.py` cannot open the Canvas sign-in window, and never could.**
pywebview only builds a second window once `webview.start()` has run on the process's
MAIN thread, and under `streamlit run` Streamlit owns that thread - so
`browser_login.is_available()` correctly answers False and the button refuses.
`python dev.py` is production's threading model with the app window swapped for a small
status window: the real `app.py` through `start.py`'s own `_launch_streamlit`, in one
process, opened in your browser. It reimplements no screen (a test enforces that).
`--window` renders the app in the pywebview window instead, in the same engine the
shipped build uses, for anything about LAYOUT. Run from source the config dir is the
repo root, so the web view profile is `<repo>/webview` - same as `python start.py`, and
not the installed app's.

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
                  course_cache, sync_manager (SQLite manifest), preset_manager,
                  canvas_auth (the ONE credential: access token or browser
                  session), browser_login (signs in through the app's own
                  web view and harvests the session cookies)
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

**Two ways in, and nothing below the auth layer may tell them apart**: a Canvas
Access Token, or a real Canvas login performed in the app's own web view whose
session cookies are then used exactly as a token would be. `core/canvas_auth.py`
is the one credential type and the only place a bearer header is formatted;
every one of the 13 `CanvasManager` construction sites is unchanged because the
VALUE carries the answer. See `.claude/rules/browser-login.md` before touching
any of it - several of its entries are bugs that shipped.

**THREE routes, TWO populations, and the split is not a preference.** It is one
setting on the student's own institution, which they did not choose and cannot
see. Where student access tokens are **allowed**, the token is the right
credential and must stay the straight path: 120 days against a session's one,
revocable, and the only one with Panopto and exported-page parity. The app mints
it for them automatically after a Canvas sign-in, so they pay no friction for
it. Where the institution has **turned tokens off** - an increasing share since
Instructure shipped the switches in September 2025, CBS among them - the token
field is not higher-friction, it is a dead end, and the two new routes are the
only way the app works at all. That is a selling point, not a fallback. The app
only learns which column a user is in on their first sign-in
(`token_upgrade_blocked`), **nothing in the UI reads that yet**, and the auth
screen's job is to serve both columns without guessing. Full statement, and the
handling that is still missing, in `.claude/rules/browser-login.md`.

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

**A 2xx is the SENDER's opinion. The receiver's state is the only oracle.** For
anything crossing a process, thread or window boundary, success is a change you
can observe on the RECEIVING side, read independently of the thing that sent it.
Measured 2026-09-13: the browser extension showed its success screen, the
terminal logged `Accepted a Canvas session handoff`, and `scripts/check_handoff.py`
passed ten of ten, while the app had never signed in. All three were talking to
an orphaned listener, and nothing anywhere asserted the one fact that mattered -
that the app now held a credential it did not have before. **Those were not three
pieces of evidence.** They were written by one author in one sitting and shared a
single premise ("there is exactly one listener and it is ours"), which is exactly
where the defect was. Count independent failure modes, not checks - and never let
a checker discover its target the way the product does, or it will agree with the
product about the thing the product has wrong.

**"The suite is green" is a claim about the TEST PROCESS, not about the app.**
pytest imports each module once and runs no file watcher; `python dev.py` and
`streamlit run` re-import EVERY watched module on ANY file change. A defect that
needs a re-import can never appear in that suite, however many tests are added.
Before calling anything verified, name what the real environment does that your
evidence did not cover - re-imports, a second window, a frozen bundle, another
process holding the same resource - and say which of those you actually drove.
The same applies to a perfect harness score: 38/38 was once produced by a fixture
that could not bind a port, so spot-check one mutant by hand whenever a pass comes
back at 100%.

**Model the LIFETIME before building anything that spans a process.** Write down
each piece of state, who owns it, and what can destroy the owner. Module-global
state that owns an OS resource - a socket, a file handle, a subprocess, a thread -
must not live in a module a file watcher can unload: it is orphaned rather than
closed, it goes on answering as though healthy, and nothing holds a reference that
could ever stop it. Ask also how many instances can exist at once and what happens
to the second.

**A new file is ROUTED to its rule file in the same commit that creates it.**
`.claude/rules/*.md` load by `paths:` frontmatter, so a file no list names gets
none of this repo's recorded lessons - and the absence is invisible, because a
rule that did not load looks exactly like a rule that does not exist.
`browser-login.md` claimed four files while the feature it documents spanned nine,
and the five it missed are where that feature broke; `scripts/check_handoff.py`
matched `scripts/check_*.py` and so loaded RELEASE rules, which is worse than
loading none. `tests/test_rule_routing.py` is the census and fails on any app
module nothing claims.

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
| `browser-login.md` | `core/canvas_auth.py`, `core/browser_login.py`, `ui/auth.py`, `start.py` |
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
- `tests/audit/OWNER_REPORTS.md` - defects the product owner hit in real use, hand-written and
  kept OUT of `AUDIT_FINDINGS.md` because the harness re-fingerprints that file on every run.
  Each entry separates what was confirmed by reading from what still needs a repro.
- `marketing/README.md` - index for launch, SEO and positioning; `FINDINGS.md` is the register
  and `STRATEGY.md` holds settled decisions. The whole folder is gitignored as of 2026-08-28,
  so it is NOT in a fresh clone and nothing tracked may depend on a file inside it: a test
  that read `marketing/STORE_LISTING.md` turned both CI workflows red with 15 failures the
  first push after the untracking, and was deleted rather than gated.

Anything durable belongs in the repo, in the same commit as the fix. Auto-memory is
machine-local and does not travel between machines; this repo does.
