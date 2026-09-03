---
paths:
  - "*.spec"
  - "scripts/build_*.py"
  - "scripts/patch_*.py"
  - "scripts/check_*.py"
  - ".github/workflows/**"
  - "msix/**"
  - "Canvas_Downloader_Setup.iss"
  - "core/store_review.py"
  - "start.py"
---

# Build, packaging, release and Store

> Extracted from CLAUDE.md. Loads only when Claude opens a matching file.
> Each entry states the mechanism, the measurement, and why the obvious fix is wrong.

## Startup: the window is NEVER empty
- **The splash is painted TWICE, by two different documents, and they must be identical.** `start.py` shows it in the pywebview window; `scripts/patch_streamlit_boot.py` injects the same markup into Streamlit's bundled `index.html` at build time, immediately after `<body>` so it is the new document's first paint. The hand-off at `load_url()` is then invisible. Colours, sizes and the label live in both files - `tests/test_startup.py` asserts they still match, because a difference there IS the flicker.
  - The label is `16.8px` with `line-height: normal` on **both** sides, not `1.05rem`: the overlay lives in a document whose stylesheet we do not own, so a rem would follow Streamlit's root size and an inherited line-height would change the label's box and shift the spinner at the swap.
- **Why it cannot be done any other way**: `/_stcore/health` answers as soon as tornado *binds*, and that is the only readiness signal the launcher has - the frontend, the websocket session and the first script run all come after it. Measured 2026-07-27 in the real app: `load_url()` → **+2.9s** React mounts → **+6.9s** first content. Streamlit's `index.html` carries no background and an empty `#root`, so all of that is a dark window. There is no supported custom-index hook; pywebview cannot inject a script before document creation; wrapping the app in an iframe of our own page would change the document topology every `window.parent` bridge, the `stDialog` portal and the native dialogs depend on. Patching one static file at build time is the smallest change that guarantees byte-0 continuity, and it is the same mechanism `patch_streamlit_webkit.py` already uses.
- **The overlay hides on REAL readiness, and can never trap the user.** It waits for content in `stMain` (an `stElementContainer` taller than 8px - style-only injections are 0-height and cannot be mistaken for a page) plus `window.prerenderReady`, which Streamlit sets when the first script run finishes and which survives `st.stop()` and any `st.rerun()` chain. Two escape hatches, both load-bearing: **5s after content first appears** it reveals regardless (a launch that goes straight into the daily auto-sync keeps the script RUNNING for minutes, so `prerenderReady` never arrives and the app's own live progress UI is the right thing to show), and a **30s absolute cap**. `finish()` is also armed on a timer next to its double-`requestAnimationFrame`, because rAF does not fire while the window is occluded.
- **Nothing may be emitted into `index.html` containing `{{`, `{%` or `{#`.** Tornado serves it through its TEMPLATE engine on the 404 path (`routes.py:write_error`), so a stray opener takes the page down on any unknown URL. The patch script asserts this.
- **Session restore runs during INIT, not from the login page** (`ui.auth.restore_saved_session`, called from `app.py` between `ensure_download_state()` and `_write_nav_to_query_params()`). It used to sit inside `render_login_page` and end in `st.rerun()`, so every launch with a saved login spent an entire script run doing keyring + Canvas I/O behind an empty window and then threw it away. Two silent consequences of the old placement are also gone: config settings were adopted *after* the sidebar had rendered, and the once-per-session stale-debug-log clear could never fire because `debug_mode` had not been read yet.
- **A URL that is already `*.instructure.com` is never "resolved"** (`core.canvas_logic._is_canonical_canvas_host`). Vanity resolution exists to follow a custom domain to its instructure.com target, so pointing it at the target fetches the whole Canvas landing page to learn nothing - 0.70s measured, on the startup path, before a single pixel existed. The check matches the HOST, so `foo.instructure.com.example.net` is still a vanity domain like any other.
- **`_find_free_port` must not set `SO_REUSEADDR` on Windows.** There it does not mean "reuse a TIME_WAIT port" as it does on Unix - it means "bind even if another process is LISTENING", so the probe handed out occupied ports. Measured twice on 2026-07-27: with a server already on 8501 the launcher picked 8501, Streamlit bound it a second time, and the health check was answered by the *other* process. Tornado skips the flag on Windows for the same reason.
- **Both prewarms in `start.py` are pure overlap, never a behaviour change.** `_prewarm_app_modules` imports the app's graph on a daemon thread while the server boots (safe concurrently: zero module-level import cycles across the 68 local modules, and `app.py` - the only file with module-level `st.*` calls - is never imported); `_prewarm_frontend_assets` pulls the 23 MB static bundle into the page cache, entry bundle first, frozen builds only. Frozen builds also pass `--server.fileWatcherType=none`: a packaged app's sources cannot change, and the watcher installs an observer per local module and re-walks `sys.modules` after every rerun.

## A bundle's SEAL is only as stable as the least deterministic thing in it (2026-08-21)
Both specs bundle the app's packages by DIRECTORY, so PyInstaller sweeps in
whatever `__pycache__` the working tree holds - **75 stale `.pyc` measured** -
and `codesign` seals them. Remove any one afterwards and the seal breaks.
- **The two Gatekeeper verdicts are different CLASSES, not different wordings**,
  measured on macOS 26.6.1 against two quarantined copies of one bundle:
  a valid ad-hoc seal gives `spctl -a -t exec` -> *"rejected"*, **exit 3**; the
  same bundle with `__pycache__` removed gives *"a sealed resource is missing"*,
  **exit 1**. Exit 3 is the not-notarized policy denial - the *"Apple could not
  verify…"* dialog with the **Open Anyway** path `docs/mac-setup.html` walks the
  user through. Exit 1 is a signature VALIDITY failure - *"…is damaged and can't
  be opened"*, which has no Open Anyway path. **The app ships unsigned by design
  (a free student project - do not re-raise notarization), so that one
  recoverable dialog is the entire macOS onboarding route.**
- **REACHABILITY, and this is the part to copy**: the claim was checked against
  the SHIPPED artifact, not reasoned about. The **v2.0.1 DMG was downloaded and
  inspected** - one `__pycache__`, in a third-party `dist-info/licenses` folder,
  none of the app's own. Release DMGs come from a fresh CI checkout with nothing
  to sweep in, so this never reached a user, and the exit-1 verdict was produced
  on a LOCAL build. Fixed anyway so a local build is byte-comparable to the CI
  one. **An inflated severity survives on every machine that reads this file**,
  so state the reachability with the mechanism.
- **What that inspection DID find**: v2.0.1's shipped bundle fails `codesign
  --verify` outright, because `pync` vendors a nested app PyInstaller cannot
  seal. Already fixed - `pync` is out of the spec and a fresh build verifies exit
  0. **It still assessed as exit 3**, because `spctl` does not descend into that
  subcomponent - so a failing `codesign` does NOT by itself mean "damaged", and
  only a top-level sealed-resource failure produces the unrecoverable dialog.
- `scripts/build_excludes.py:strip_bytecode_datas`, applied in BOTH specs
  because a fix landing on one is this repo's documented failure mode.
  `tests/test_bundle_bytecode_exclusion.py` counts the call sites;
  `scripts/_mutate_bundle_bytecode.py` **9/9**.
- **Six of nine mutants survived the first pass and three were defects in my own
  tests**: a text search matched the call inside its own explanatory comment
  (resolve the call through the **AST**), and TWO mutants hit a byte-identical
  anchor in `strip_test_datas`, which is defined FIRST - so `.replace(..., 1)`
  mutated the wrong function and reported SURVIVED under a label that was a lie.
  **Fourth and fifth instances of the twin-anchor trap in this repo.** Anchor
  uniquely, always including a preceding line.

## Building the Windows release: two flags and a path (2026-08-23)
First real run of `scripts/build_windows.py` on Windows, on the machine releases are made from.
- **`--clean` and `--noconfirm` are different knobs and only one touches `dist/`.** `--clean` empties the BUILD cache; PyInstaller's COLLECT step then refuses a non-empty OUTPUT directory (*"use the -y option"*) and exits 1 - **about nine minutes in**, after Analysis, PYZ and EXE. A fresh CI checkout has no `dist/`, so this passes there and fails **only on a machine that has built before**, which is exactly the release machine. The script's own new guards behaved correctly throughout: it caught the non-zero return code and exited 1 rather than reporting success.
- **`find_iscc()` was pinned to one VERSION in one ROOT** (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe`). Inno Setup 7 x64 offers a **per-user** install, which lands in `%LOCALAPPDATA%\Programs\Inno Setup 7` and puts nothing on PATH - so a working compiler was missed and the build exited 1 saying it was "not found". Now: PATH first (an operator can still pin one), else glob `Inno Setup*` across both Program Files roots and `%LOCALAPPDATA%\Programs`, **newest version first** so a machine with 6 and 7 builds with 7. The `.iss` compiles cleanly under Inno Setup 7 including its `[Code]` section.
- **The guard the script's own docstring said could only be written on Windows is now written**: the PE version resource was read back out of the built AND installed exe (`FileVersion 2.0.2`, `ProductVersion 2.0.2`), and Add/Remove Programs reads **2.0.2** - the exact thing the old `build_windows.ps1` got wrong by producing a 2.0.0-labelled installer. The release asset is byte-identical to Inno's output (same md5).

## The licence is GPL-3.0-or-later, and four facts about it are load-bearing (2026-08-24)
Relicensed from MIT on 2026-08-24. The Store/publishing consequences live in `marketing/FINDINGS.md`; these are the engineering ones.
- **It had to be GPL-3 and not GPL-2, and a dependency forces that.** Streamlit and `requests` are **Apache-2.0, which is compatible with GPLv3 and NOT with GPLv2**. Choosing 2 would have put an incompatible licence at the core of the app. Anything proposing to "simplify" to GPLv2 is proposing a licence violation.
- **The bundled FFmpeg is a GPL build** - `imageio-ffmpeg` ships a gyan.dev "essentials" binary compiled with libx264/libx265. Under MIT that was a **live compliance defect being shipped**, not a hypothetical one; GPL-3 resolves it. It is invoked as a **separate process** (argv over a pipe, never linked), which is what makes it aggregation rather than a combined work, and `THIRD_PARTY_NOTICES.md` records that plus where to get FFmpeg's corresponding source.
- **BOTH specs must bundle `LICENSE` and `THIRD_PARTY_NOTICES.md`** - `Canvas_Downloader.spec:31-32` and `Canvas_Downloader_macOS.spec:29-30`. A fix landing on one spec and not its twin is this repo's single most documented failure mode.
- **A build made before a licence change SHIPS THE OLD LICENCE TEXT, silently.** The spec copies `LICENSE` into the bundle, so the artifact carries whatever the file said at build time and nothing reports the mismatch. Measured on 2026-08-24: a finished, verified installer had `dist/Canvas Downloader/_internal/LICENSE` reading `MIT License` while the repo was mid-relicense. **After any licence change, rebuild and read that file out of `dist/` rather than trusting the repo's copy.** The same applies to any other text file the specs bundle.

## The public MSIX files stay public. Do not propose hiding them (2026-09-02)
Asked by the product owner, who is the only person with Partner Center access:
does it make sense to publish the Store how-to at all. Answered and settled, so
that a future session does not re-open it.
- **`scripts/build_msix.py` and `msix/AppxManifest.template.xml` must stay.**
  GPLv3 defines Corresponding Source as including *"the scripts used to control
  compilation and installation of the executable"*, and the MSIX is distributed.
  Removing them is a licence problem, not a tidy-up. They also carry the trust
  story: the Store build is the one with no SmartScreen warning, and its recipe
  being public is what lets anyone check it came from this code.
- **`msix/identity.json` holds nothing secret.** `CN=BE7EDB0D-...` and
  `BrkBuilds.CanvasDownloader` are in the AppxManifest of every installed copy and
  readable with `Get-AppxPackage`. They are not credentials, and Partner Center
  will not let a second account claim a reserved identity.
- **What IS operator-only is the runbook half of `msix/README.md`** - reserve the
  name, copy three values, upload, submit for certification - and it is duplicated
  in `marketing/STORE_LISTING.md` section 7. Two copies of a procedure where only
  one gets updated is the failure this repo documents most. **Reviewed 2026-09-02
  and deliberately NOT split**, because nothing depends on it (the only reference
  in the whole repo is `scripts/build_msix.py:31`) and the duplicate is inert.
  If it is ever edited, update the marketing copy in the same pass or delete one.

## Platform Notes
- **Windows**: `win32com.client` COM automation for Office → PDF conversions. `ctypes` to hide `.canvas_sync.db`.
- **macOS**: `osascript` (AppleScript) via `engine/applescript_bridge.py` for Office conversions. Requires `com.apple.security.automation.apple-events` entitlement in `.spec`.
- **Keyring**: Lazy-imported inside functions on all platforms (`ui/auth.py`). macOS = Keychain with a 90s watchdog: a CLEAN install never prompts (creating/reading your own item is silent); only a REBUILD with a new ad-hoc signature reading the previous build's item triggers the one-time "enter login keychain password" prompt. Windows = Credential Manager (5s watchdog) + DPAPI-encrypted `.token_fallback` file; macOS deliberately has NO disk fallback.
- **File I/O**: Always specify `encoding='utf-8'` explicitly - Windows defaults to CP1252, causing Mojibake in emoji-heavy UI files.

## Build
- Windows: `pyinstaller Canvas_Downloader.spec`
- macOS: `pyinstaller --clean Canvas_Downloader_macOS.spec` + `codesign --force --deep -s - --entitlements entitlements.mac.plist Canvas\ Downloader.app`
- Launcher: `start.py` - daemonized Streamlit thread + `pywebview.start()` on main thread (required for macOS Cocoa).

### Bundle size: the policy lives in `scripts/build_excludes.py`, not in the specs
Measured 2026-07-27 on Windows: **462.8 MB → 326.2 MB installed** (-136.6 MB, -29.5%), **installer 133.7 MB → 87.3 MB** (-34.7%), 5,865 → 4,840 files, and the PYZ from **5,322 → 2,324 modules**.

- **Both specs load ONE shared policy module** (`scripts/build_excludes.py`) the same way they already load `patch_streamlit_webkit`. It is one file on purpose: the specs are near-duplicates, and a trimming fix applied to only one of them is invisible in review and ships a fat build on the other OS. **Do not add a one-off `excludes=[...]` entry to a spec.**
- **Root cause of the bloat: `collect_all()`.** It is `collect_submodules` + `collect_data_files` + `collect_dynamic_libs`, and `collect_submodules` walks **every** submodule - test suites, CLI entry points, optional integrations - forcing each in as a hidden import; PyInstaller then follows *their* imports. Three chains, read off the build's own `xref-*.html`: `huggingface_hub._oauth`→fastapi→pydantic, `huggingface_hub.inference._mcp`→mcp→pydantic_settings→{azure.core→opentelemetry→**grpc**, google.auth→**cryptography**}; `psutil.tests`→**pip**→`cachetools.redis_cache`→**redis** and `numpy.typing.tests`→**_pytest**; `webview.http`→bottle→**gevent**(274 modules)→dnspython.
- **Three mechanisms, and the order matters.** `lean_filter` (passed as `filter_submodules=`) is the root-cause fix and is **safe by construction** - it only stops a module being *force-added*, so anything a real import reaches is still collected normally. `excludes_for()` is the blunt instrument that severs chains reached through genuine imports (bottle→gevent), so every entry there is justified in the module. `strip_test_datas(a.datas)` runs **after** `Analysis` because `collect_data_files` copies test `.py` files back in as *data* even once they are out of the import graph (7.29 MB, 6.36 MB of it numpy's); it touches data only and can never make an import fail.
- **THE TRAP - never exclude the bare `google` namespace.** The huggingface chain reaches `google.auth`, which makes `google` look dead. **Streamlit needs `google.protobuf` for every `ForwardMsg` it sends** - excluding it bricks the app. Only `google.auth`/`google.oauth2` are dead. This was caught by the validation harness, not by reading code.
- **Validate by BLOCKING, not by reasoning.** Install a `sys.meta_path` finder that raises `ImportError` for every candidate, then run the real paths (Streamlit + `ForwardMsg_pb2`, all app modules, canvasapi, `BeautifulSoup(..., "html.parser")` + `.select()`, `webview.http`, keyring, win11toast, win32com, moviepy+PIL, `snapshot_download`, a real transcription). Minutes instead of a 10-minute build cycle, and it names *which* exclusion broke *which* path. **Run transcription in a clean process** - co-loading streamlit/numpy/win32com with ctranslate2 segfaults from an OpenMP clash *with or without* any exclusions, which is exactly why `panopto/transcribe_worker.py` exists; a combined harness will crash and look like your change did it.

### The bundle shipped FFmpeg TWICE - `scripts/patch_faster_whisper_audio.py`
`ffmpeg.exe` (83.6 MB, used by `converters/video.py` and `panopto/stream.py`) **and** PyAV's `av.libs/` (62.0 MB of libav DLLs - avcodec 18.3, libx265 12.0, libSvtAv1Enc 7.3). PyAV was pulled in by **one line** - `faster_whisper/audio.py`'s `import av` - to decode an MP3 this app produced itself, moments earlier, with the other FFmpeg. The x265 and SVT-AV1 *video encoders* have nothing to do with transcribing a lecture.
- The patch rewrites `decode_audio()` to drive the bundled binary (same pattern as `patch_streamlit_webkit.py`), then `av` is excluded: **-65.4 MB**.
- **Verified equivalent, not assumed:** decoded the same MP3 both ways - for a `str` path (the only form this app passes) max abs sample diff **0.00000000**, Pearson r **1.0**, identical length. A file-like object keeps ~1.9 ms of extra tail because trimming an MP3's encoder delay needs a *seekable* input and `pipe:0` is not; nothing here uses that form.
- It is **version-gated** (`_TESTED_VERSIONS`) and raises at build time on an untested faster-whisper rather than silently shipping a wrong decoder. When you bump the pin in `requirements.txt`, run one real transcription and add the version.
- Because it edits site-packages in place, `streamlit run app.py` uses the patched decoder too - dev and frozen behave identically. `pip install --force-reinstall faster-whisper` reverts it; re-run the script.

### Deliberately NOT done - decided 2026-07-27, do not re-litigate
- **`moviepy` stays** (~6.5 MB with PIL + imageio). `converters/video.py` uses `VideoFileClip` for one thing - extracting audio to MP3 - which is a single ffmpeg call the codebase already knows how to make, and dropping it would also delete `_safe_close`'s ThreadPoolExecutor + psutil-kill machinery (which exists *only* because moviepy's `close()` blocks on `Popen.communicate()`). **Declined anyway:** the ffmpeg/Panopto path cost a lot of debugging to get working and ~6.5 MB does not justify disturbing it. Note PIL cannot be dropped separately - `moviepy/video/VideoClip.py` imports it at module level.
- **`onnxruntime` stays** (37.3 MB). It is only the Silero VAD backend and `panopto/transcribe.py` already retries with `vad_filter=False` (`_is_vad_engine_error` matches the `"onnxruntime"` in the raised message, so the fallback genuinely fires). Kept because VAD skips silence, which on lecture recordings is both faster *and* what stops Whisper hallucinating over long quiet stretches.
- **`tkinter` stays on Windows** (7.1 MB) - it is `shared/helpers.py:pick_folder`. Excluded on **macOS**, where it is pure dead weight: that branch returns from `osascript` on every path (`helpers.py:501`), so the tkinter import below it is unreachable.
- **UPX: no.** The Inno installer already uses `lzma2/ultra64` + `SolidCompression`, and UPX-then-LZMA compresses *worse* than LZMA alone - it would not shrink the download at all, only slow startup and attract antivirus heuristics on an installer with no EV signature.
- **Downgrading imageio-ffmpeg: no.** 0.5.1 ships a 61.7 MB binary (-22 MB) but it is FFmpeg **4.2.2** (2019); Panopto HLS delivery, modern AAC/HEVC and current TLS are not worth regressing.
- **Still unmeasured: the macOS PyObjC surface.** All the platform-agnostic wins above apply to the mac build, but `collect_all('UserNotifications')` may pull far more pyobjc than needed. That needs a mac to measure - do not guess at it blind.

## The Microsoft Store rating ask: MSIX-only, and the CLICK is the terminal state (2026-08-24)
A "rate this app" card at the bottom of both completion screens, `shared/components.render_store_review_card` over `core/store_review.py`. The risk in this feature is entirely in WHEN it appears: an ask that lands badly costs a daily user, which is worth far more than a review.
- **The gate is `shared/helpers.is_msix_package()`, which ASKS WINDOWS** (`kernel32.GetCurrentPackageFullName`; `APPMODEL_ERROR_NO_PACKAGE` = not packaged). Off Windows the export does not exist, so macOS and the Inno `.exe` answer False for free and emit no element at all. **Do NOT reuse `core/health_log.py:213`'s heuristic** - `MSIX_PACKAGE_ID` is set by nothing in this repo (`build_msix.py` included), so half of that OR is dead and it rests on `"WindowsApps" in sys.executable`: true of a sideloaded dev package, false of a relocated build. Fine for a telemetry field, not for a gate on a user-facing surface.
- **"Has this user already rated?" is UNANSWERABLE.** No API exposes it - `StoreContext` has licences and collections, not reviews - and the `ms-windows-store://` deep link is fire-and-forget. So the BUTTON PRESS is what is recorded, not a review: anyone who engages is spent, whether or not they followed through. That is the only implementable reading, and it is the polite one (the failure mode is asking a would-be reviewer once fewer, never nagging someone who already helped).
- **Because of that, the LIFETIME CAP is the real protection, not the buttons.** `MAX_ASKS = 3`, ever. A "never ask again" control would only duplicate a promise the cap already keeps. Gate: MSIX · the run just finished CLEAN · 3 distinct days with a clean run · a 7-day floor · ≤3 asks. `should_ask` is pure and takes `today`, so it is testable with no Windows box.
- **"Clean" is the app's own definition - zero RETRIABLE errors, plus no app errors, plus ≥1 file delivered.** `len(errors) == 0` is the tempting spelling and is wrong in both directions: a teacher-locked file and an LTI stream are not failures (the completion card already refuses to count them), while an app error is one. Asking for five stars under an amber "Completed with Errors" header is the one thing this must never do.
- **The ask is charged on SHOW, not on a click**, or a user who simply ignores the card meets it on every clean completion screen for ever. Safe only because `note_clean_run` is idempotent BY DAY - a completion screen re-renders on every rerun, and a naive counter would burn the whole allowance inside one screen. `run_days` also stops growing at the threshold, so the feature costs ≤6 disk writes in an install's life.
- **`core/store_review.py` is the FIFTH co-owner of `canvas_downloader_settings.json`.** It follows the established shape (its own `_read_full_config_for_update` wrapper over the shared `read_json_for_update`, plus a private atomic write) and is registered in both of `tests/test_settings_coownership.py`'s writer lists. Its three public writers funnel through ONE `_save_state`; that they all still do is asserted separately, by `tests/test_store_review.py`.
- **It sits directly under the completion card and OUTSIDE its container**, half width, above "Folders Updated" - a rating ask is not a fact about the run, so it must not join that card's documented stats -> expanders -> notices ordering. **BLUE, never amber**: on these screens amber MEANS a warning and this is the one surface there where nothing is wrong. The buttons are the `pan_open_dialog_btn` recipe in blue (32px, tint + border, not a solid) so they cannot outweigh "Go to front page".
- **BOTH `ms-windows-store://review?ProductId=` and `review/?ProductId=` work, and the slash form is now VERIFIED AGAINST THE PUBLISHED LISTING (2026-08-25).** Worth knowing because the FAILURE MODE is the worst available: `os.startfile` succeeds either way, an unrecognised URI opens the Store's HOME page, the click is still recorded as a rating, and nothing reports an error. Only a human clicking and looking can catch it.
  - **The 2026-08-24 measurement proved LESS than it was recorded as proving, and that is the transferable part.** It was taken before the product was public, so it established that the Store *accepted* the URI, not that the URI reaches THIS product - and those two are indistinguishable from the calling side, because the home-page fallback is silent. A deep link into a marketplace cannot be verified before the thing it points at is published; anything measured earlier is a syntax check wearing a behaviour check's clothes.
  - Re-measured on 2026-08-25 against the live listing: `ms-windows-store://review/?ProductId=9n1dwwvrq5wc` opened Canvas Downloader's own rating dialog on its own Store page, and a rating was submitted through it.
- **`STORE_PRODUCT_ID` lives in the app plus six published surfaces** (`docs/index.html`, `releases.html`, `win-setup.html`, `thanks-win.html`, `llms.txt`, `README.md`), and a test pins all of them together. The Store id is assigned once at NAME RESERVATION and survives listing edits, new screenshots and new package submissions; what issues a new one is creating a new product entry or moving Partner Center account. That is the day the test earns its keep.
- **`help=` on a button breaks its sizing, and `global.css` is WRONG about this.** The comment above the per-key list says a new tooltip "no longer needs registering anywhere"; the generic rule is `.stButton > [stTooltipHoverTarget] > button`, a DIRECT-child chain, and the live DOM nests `stTooltipIcon` in between. Measured here as 40px against a 48px sibling in the same row. Every per-key rule that still works uses a DESCENDANT combinator - they are not the dead weight that comment calls them.
- Covered by `tests/test_store_review.py` (48) and `scripts/_mutate_store_review.py` - **24/24 caught**, so re-run the mutation pass rather than just the suite. Three survivors in the first pass were all real gaps: a test that derived its bound from `MAX_ASKS` could not notice the constant changing, nothing asserted the packaging check was not a path sniff, and nothing asserted the two live states are padded to one child count. **VERIFIED IN THE SHIPPED STORE PACKAGE, 2026-08-25** - `core/store_review.py` is present at `_internal\core\store_review.py` inside `BrkBuilds.CanvasDownloader_2.0.2.0_x64`, i.e. the card went out in v2.0.2, and the review deep link was driven end to end (above). From source the gate still correctly answers False, so `scripts/completion_gallery.py` forces the memo.
  - **`is_msix_package()` was measured answering True under the SHIPPED Store package's identity, with a negative control** - and the technique is the durable part, because it needs neither a sideload nor waiting out the gate. `Invoke-CommandInDesktopPackage -PackageFamilyName <PFN> -AppId <AppId> -Command <python.exe> -Args <probe>` runs an ORDINARY process under a package's identity, and package identity is given by the loader, so the probe sees exactly what the app sees. Measured 2026-08-25: ordinary process `GetCurrentPackageFullName` rc **15700** (`APPMODEL_ERROR_NO_PACKAGE`) -> False; same interpreter, same script, under identity, rc **122** (`ERROR_INSUFFICIENT_BUFFER`, the success path) and full name `BrkBuilds.CanvasDownloader_2.0.2.0_x64__9hvdhsvexxn1j` -> True. **Run the control every time**: a probe that only ever answers True is indistinguishable from a broken one, and this is a boolean, so there is nothing else to catch it. Import the REAL function rather than re-implementing the ctypes call - re-implementing tests the copy.
  - **What is left is the COMPOSITION, not any ingredient.** Every input to `should_ask` is now measured or unit-tested (packaging by the probe above, the day/floor/cap arithmetic by the 48 tests), but the card has never been observed RENDERING on a real completion screen in the packaged app, because that needs 3 distinct clean-run days and a 7-day floor to accrue. Presence in the bundle is not the gate firing, and the gate answering True is not the card drawing - state which of the three you have measured.
