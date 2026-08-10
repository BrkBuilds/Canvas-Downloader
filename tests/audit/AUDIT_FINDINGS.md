# Audit findings register

Cumulative work list produced by the live audit (`/audit-live`, or
`python -m tests.audit`). **This file is meant to be edited by hand.**

Set `**Status**` on any entry to one of `open`, `fixed`, `accepted`,
`wontfix`, `invalid`, and add anything you like under `**Notes**`. The
audit refreshes the facts around your decision on every run and never
overwrites it. Anything you marked `fixed` that appears again is
reported as a **regression** — that is the line worth watching.

Last updated by run `20260810_151922_macos-15-v2.0.2` on 2026-08-10.

**33 open** · 87 total · 24 fixed · 30 invalid

---

### A corrupt or 0-byte .doc wedges Microsoft Word on macOS, and every later Word conversion in the run then silently fails
<!-- fp:200c7fea9f04 -->

**Status**: open
**Severity**: high
**Category**: conversion
**Oracles**: O2,O3
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 7
**Scenario**: mac_m1_word_wedge

**Detail**:

REPRODUCED on real macOS with real Office; only this machine can produce it. CHAIN OF EVENTS, measured: (1) feed the macOS Word converter a hostile legacy .doc (2 KB of random bytes, and separately a 0-byte file). The delete gate behaves CORRECTLY - the source is kept, verified by md5 - and the log records '[AppleScript] Word failed (other)'. Run 1 also logged 'Microsoft Word got an error: AppleEvent timed out. (-1712)', consistent with Word raising a MODAL dialog that waits for a human (hypothesis - not directly observed, see below). (2) Word is then WEDGED: 'count of documents' answers 1, the document's name cannot be read, and 'close every document saving no' answers 'missing value' and changes nothing. (3) EVERY subsequent Word conversion fails with 'missing value doesn't understand the save as message. (-1708)' - INCLUDING a genuine 153 KB .doc from course 43660 that converted perfectly moments earlier in a clean process. Measured across two fresh processes: 4 of 4 good-file conversions failed, each reporting 'word docs before=1'. (4) The app's OWN recovery does not help: engine.applescript_bridge._force_close_canvas_docs_sync left the count at 1. (5) Killing the process DOES recover it: after 'pkill -x Microsoft Word', a good file CONVERTED and a second good file straight after also CONVERTED. WHY IT MATTERS: no data loss (the gate keeps every source), but for the rest of that run the user silently gets NO PDFs from any .doc/.rtf/.odt, with one generic 'Conversion failed' line per file. Reachable in normal use by a single corrupt legacy .doc in a course followed by others. WHY THE EXISTING MECHANISM MISSES IT: the codebase already models this exact class - _abort_applescript_phase exists to 'log a single actionable message instead of spamming dozens of generic errors' for failures that 'will identically doom every remaining file in the phase' - but FATAL_CATEGORIES is only ('permission','app_missing'), keyed on -1743 and -600/-10810. A wedged Word yields -1708, which _classify_stderr maps to 'other' = per-file, so the phase dutifully attempts and fails every remaining file. RECOMMENDED FIX (not applied): treat a run of consecutive identical AppleScript failures within one phase as fatal for that phase and emit one actionable message ('Microsoft Word is not responding to conversion requests - quit Word and run again'). A blind kill+relaunch is NOT safe and must not be added: in the wedged state the documents cannot be enumerated, so the app cannot certify that no USER document is open, and every other Office path in this codebase deliberately refuses to act without that certificate. THE MODAL IS CONFIRMED, by the operator's own eyes: 'word was jumping in the dock and when i clicked it it had some error dialog saying file "name" couldnt be opened or something and i clicked ok to all of them and quit word'. So the chain is: hostile .doc -> Word raises a MODAL file-open error and bounces in the Dock demanding attention -> AppleScript's 'open' never yields an active document -> every later conversion answers -1708 -> nothing in the app dismisses the alert, so the phase is dead until a human clicks OK or the process is killed. Note the converter DOES attempt 'set display alerts to false', but it is wrapped in its own try and evidently does not suppress a file-corruption alert raised during open. I could not observe this myself - screenshots were blind at the time and System Events refused with 'osascript is not allowed assistive access (-1728)' - which is a good argument for keeping a human in the loop on a GUI-automation phase.

**Notes**: 

---

### A failed Keychain save DESTROYS the token that was already saved, tells the user nothing, and logs a DPAPI fallback that does not exist on macOS - so the next launch is a login page
<!-- fp:03713060d77a -->

**Status**: open
**Severity**: high
**Category**: persistence
**Oracles**: O1 UI (lane apps on ?mode=auth) vs O3 disk (Keychain probe)
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 2

**Detail**:

Found because every lane of the sync matrix failed identically ("btn_analyze_sync not clickable"), which turned out to be every lane app sitting on ?mode=auth. The Keychain held NO token at all - and it had held one earlier the same day, because an Aqua-launched app restored its session and rendered "Logged in as Birk".

MEASURED against the real library, not reasoned about:

    keyring.set_password(SVC, USER, "probe-value-before")   -> stored, reads back
    keyring.set_password(SVC, USER, "probe-value-AFTER")    -> PasswordSetError (-25308)
    keyring.get_password(SVC, USER)                          -> None

The macOS backend DELETES any existing item before adding the new one, so a refused write leaves nothing behind. What destroyed the audit's token was me logging in through the real UI from a session whose Keychain is unwritable; the same shape reaches a real user whenever the login keychain is locked for writing, or when ui/auth.py's own 90-second keyring watchdog times out.

Three things in ui/auth.py then combined so that the user was told nothing:
1. _safe_keyring_set RETURNS False rather than raising, so the login flow's `except Exception` amber notice was unreachable for this failure - the only branch that ran was the else.
2. _save_fallback_token returns immediately when sys.platform != 'win32'. That is deliberate and correct (the app must not write tokens to disk on macOS), but it means macOS has no second copy.
3. The else branch's only output was logger.warning("Keyring save failed or timed out. Saved to DPAPI-encrypted fallback storage.") - which off Windows describes a save that did not happen.

So: the previously saved credential is destroyed, nothing new is stored, no notice appears, and the next launch shows the login page. Recovering means going back into Canvas to mint a fresh access token.

WORSE AT THE TWO LEGACY-MIGRATION SITES. Both of them (macOS base64-in-JSON, Windows plain-JSON) did: kr_ok = set(...); if not kr_ok: _save_fallback_token(...); config.pop('<token field>'); write_config_atomically(config) - popping the JSON copy and rewriting the file whatever the keyring returned. That is the one run where the JSON copy is the ONLY copy, which CLAUDE.md already flags in another context as "exactly when the file is most worth not corrupting".

FIX: ui.auth.store_token(username, token) -> bool, now the only writer, with three properties in order because each alone is insufficient:
  (a) SKIP a write that cannot change anything. If the stored value already equals the token there is nothing to gain and a credential to lose - and this is the common path (re-login with the same token, plus both migration sites). Verified live on the real Keychain: same token + refused write = 0 set_password attempts, value intact.
  (b) write, then fall back (Windows DPAPI; nothing on macOS by design).
  (c) VERIFY by reading back, so the return value describes the STORED STATE rather than the return code of one attempt. That is what makes it safe for a caller to delete its own copy - and it matters beyond this bug, because _safe_keyring_set also returns False on a watchdog TIMEOUT, where the native call may still be in flight.
Both migrations now pop the JSON field only when it returns True, and the login flow renders an amber notice ("Your login could not be saved on this device") instead of logging a DPAPI save that did not happen. store_token never raises: a persistence failure must not be able to abort a login.

WHAT THE FIX CANNOT DO, stated plainly: if the Keychain is unreadable as well as unwritable, store_token cannot detect an identical token and the write is attempted, so the old item is still destroyed. That is the context my SSH session was in. It is not worth defending - a machine whose Keychain answers nothing has no credential to preserve - but it is why the audit's own token vanished rather than being skipped.

Verified live in the Aqua session against the real macOS Keychain (all three cases), covered by tests/test_token_store_preserves_credential.py (10 tests), and all 7 mutations of the real code are caught - including one per migration site and one for the amber notice. The 7th survived a first pass as an apparent equivalent mutant (the wrapper it guards swallows backend errors itself) and is genuinely reachable: _safe_keyring_set does `import keyring` OUTSIDE its own try, so a broken or build-excluded keyring package raises straight through it.

**Notes**: 

---

### SAFETY GUARD BYPASSED ON macOS: /etc and /var were accepted as sync folders because the check resolves symlinks before comparing
<!-- fp:d6ba79f3db46 -->

**Status**: open
**Severity**: high
**Category**: persistence
**Oracles**: O3,O4
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 6
**Scenario**: mac_m4_system_roots

**Detail**:

REAL PRODUCT DEFECT, found by running the unit suite on macOS for the first time. sync/persistence._validate_pair_folder refuses 'obviously dangerous system roots' and is the gate on add_pair/add_pairs_batch. It calls Path(folder).resolve() and THEN compares against a blocklist written in plain spelling - but macOS symlinks /etc, /var and /tmp into /private, so '/etc' arrives as '/private/etc', matches nothing, and is ACCEPTED. Measured on macOS 15.6.1: _validate_pair_folder('/etc') -> True, '/etc/nested' -> True, '/var/log' -> True, and add_pair('/etc') WROTE the pairs file instead of rejecting it and showing the 'system folders cannot be used' toast. WHY IT SURVIVED: the tests for this were correct all along and had never run anywhere. They carry skipif(sys.platform == 'win32') with reason 'POSIX system roots', so Windows skipped them, and nobody had ever run the suite on a Mac - six of them fail on the very platform they were written for. This is the platform-asymmetric class CLAUDE.md documents (the Office delete-gate fixed on Windows and left broken on macOS for a full round). WHY IT MATTERS: a sync pair is a folder the engine writes course files into, creates a hidden .canvas_sync.db in, and sweeps .part files out of. The folder normally comes from the native picker, and FINDER RESOLVES SYMLINKS - so '/private/etc' is the spelling a real user is most likely to arrive with, which the raw-only alternative would also have missed. FIXED: the check now refuses a candidate if EITHER the raw or the resolved form names a system root, and _BAD_ROOTS_MAC adds the /private spellings. An explicit exemption keeps the OS's own per-user temp area usable ('/var/folders/<user>/T', which resolves under /private/var and would otherwise be swallowed by the /var entry) - that distinction is real, not a concession to the fixtures: /var/log is the system, /var/folders/<user> is the user's scratch space. Verified on this Mac: /etc, /etc/nested, /private/etc, /var/log, /private/var/log and /usr/local all rejected; /Users/m1/Courses and both the temp root and a mkdtemp under it accepted; all 53 tests in tests/test_sync_persistence.py pass where 6 failed. KNOWN RESIDUAL, deliberately not changed: '/System', '/Library' and '/Applications' are not in the blocklist and are still accepted. Adding new roots is a design decision rather than a bug fix, and SIP makes /System unwritable in practice.

**Notes**: 

---

### A download then a sync duplicated every lecture's audio: 70 mp3 files for 36 lectures, because the shortcut's disambiguated path defined the stem for all media
<!-- fp:5a4befe8de50 -->

**Status**: open
**Severity**: high
**Category**: placement
**Oracles**: O3,O4
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 5
**Scenario**: mac_m4_panopto_dupes

**Detail**:

REAL PRODUCT DEFECT, found by driving the real app: a download of course 43660 with mp3+txt+srt, then a real sync of the same folder. NOT macOS-specific - the same collision happens on Windows with .url, and CLAUDE.md already records it there ('34 identically-named .url files'). MEASURED: 70 .mp3 files in a course with 36 lectures - 36 without a suffix and 34 with ' (Panopto)', the same lectures twice, about 400 MB duplicated and the originals orphaned. Proof by pair: 'Forelaesningsvideo (1) organisationsprojekt - klargoering af data.mp3' beside 'Forelaesningsvideo (1) organisationsprojekt - klargoering af data (Panopto).mp3'. O4 shows the cause exactly - for one video_id the manifest held url -> '<title> (Panopto).webloc' and mp3 -> '<title>.mp3'. MECHANISM: panopto.runner._recording_base is manifest-first and its kind list was (SHORTCUT_KIND, 'mp4', 'mp3', 'txt', 'srt') - shortcut FIRST, returning on the first hit. The shortcut is the ONE kind whose path is legitimately disambiguated, because in the match layout the Canvas file sync owns '<title>.url' and resolve_shortcut_path therefore writes ours as '<title> (Panopto).url'. Asked first, that stem became the base for every other kind, so the sync re-downloaded all 34 recordings it touched to '<title> (Panopto).mp3' beside the mp3s already on disk. This is precisely the divergence the function's own docstring promises to prevent ('instead of diverging to a fresh Title (2)'), and it is invisible in a download-only or sync-only run - it needs a download followed by a sync of the same folder, which is the normal lifecycle. FIXED: media kinds are consulted first, shortcut last. That costs nothing - the shortcut is still reached whenever no media kind is recorded, which is the only case its inclusion was ever justified by ('a folder whose ONLY produced output is the shortcut still has a stem the manifest knows'). tests/test_panopto_stem_from_manifest.py, 9 tests, both directions (the media stem wins when both exist; the shortcut stem is still used when it is alone; an undisambiguated shortcut agrees either way; the no-manifest fallback is unchanged) plus an AST check that the shortcut kind is last. Both mutations caught: restoring the old order fails 6, dropping the shortcut kind fails the alone-case. SIDE OBSERVATION, correct behaviour: those 34 recordings were offered for sync at all because their mp3 existed with no transcript (I had cancelled transcription after 2), which is RUNBOOK's 'a recording with mp3 present but srt missing must appear as new / missing outputs, not as up to date'.

**Notes**: 

---

### The case half of _path_key is a no-op on macOS, so a case-only rename still drops a tracked file out of the tracked set
<!-- fp:f3cdebbc44ff -->

**Status**: open
**Severity**: medium
**Category**: classification
**Oracles**: O3,O4
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 4
**Scenario**: mac_m4_case_rename

**Detail**:

REAL PRODUCT DEFECT on macOS, in a primitive whose Unicode half I verified as working. CLAUDE.md justifies core.sync_manager._path_key = normcase(normpath(NFC(s))) with: 'Case - a case-only rename (Notes.pdf -> notes.pdf) is legal and invisible on Windows/macOS, but the raw strings stop matching. Measured: the tracked file drops out of the tracked set, so it is offered to the healer as an orphan AND inflates the untracked files count the review screen shows.' That fix works on Windows only: os.path.normcase LOWERCASES on Windows and is IDENTITY on POSIX. MEASURED here: os.path.normcase('AbC') -> 'AbC'; _path_key('Notes.pdf') == _path_key('notes.pdf') -> False; _path_key('Tema 1/Slides.PDF') == _path_key('tema 1/slides.pdf') -> False - while the boot volume IS case-insensitive (wrote CaseProbe.txt, and (dir/'caseprobe.txt').exists() -> True, i.e. both names are the SAME FILE). So on macOS the documented symptom is still live: a case-only rename makes the manifest row dangle, offers the file as 'deleted locally' (a re-download of a file that is already there under a different spelling), and inflates the untracked count whose stated purpose is to match what the user sees in the folder. No data loss - the app never deletes on a Canvas-side diff. Two Windows-written tests fail here for the same underlying reason and are the trail that led to it: test_library.py::test_save_pair_matches_link_across_path_spelling and test_pair_labels.py::test_pair_key_normalises_folder_and_course_id, both asserting that 'C:\Courses\Makro' and 'c:/courses/makro' resolve to one key. NOT FIXED, deliberately, and this is the important part: the obvious fix - always .lower() in _path_key - is NOT safe. _path_key drives heal_manifest's local-to-local matching, the untracked count and analyze_course, and on a case-SENSITIVE volume (a case-sensitive APFS or HFS+ format, or an ext4 external drive - and course folders do live on external drives, which is why the NFD case matters at all) 'Notes.pdf' and 'notes.pdf' are two different files. Folding them would let a heal bind a manifest row to the WRONG file, which is data-integrity territory and strictly worse than today's over-reporting. The correct fix is to fold case only when the containing volume is case-insensitive, which needs a per-volume probe (pathconf/_PC_CASE_SENSITIVE or a write-probe, cached per mount) rather than a global lower(), and that is a change I am not willing to make blind at the end of a release. RECOMMENDED: add the volume probe, cache it per mount point, and pin both directions - a case-only rename adopted on the case-insensitive boot volume, and two genuinely distinct names kept apart on a case-sensitive one. REAL-FOLDER CONFIRMATION, measured on the synced 43660 folder: took a tracked row ('Tema 4 .../Maurer_Introduction to Change.pdf'), renamed the file to 'maurer_introduction to change.pdf' (two-step, since a case-only rename needs it on a case-insensitive volume), and asked the manifest. The file's REAL spelling is NOT in the tracked set (_path_key miss), while the row's stored path STILL OPENS because the volume is case-insensitive. So the precise macOS symptom is not a dangling row and not a 'deleted locally' offer - it is DOUBLE COUNTING: the same file is tracked under the old spelling and simultaneously counted as UNTRACKED under its real one, inflating the very count whose stated purpose is to match what the user sees in the folder. Milder than the Windows description in CLAUDE.md, and still wrong. The file was restored to its original spelling afterwards.

**Notes**: 

---

### Packaged .app fails codesign --verify --strict: pync's vendored nested terminal-notifier.app is path-mangled by PyInstaller
<!-- fp:b7bc37bfb6fc -->

**Status**: open
**Severity**: medium
**Category**: config
**Oracles**: O3,O2
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 7
**Scenario**: mac_m3_bundle

**Detail**:

PRODUCT/BUILD finding, first time the macOS bundle's signature has been verified. Built with 'pyinstaller --clean --noconfirm Canvas_Downloader_macOS.spec' (rc=0, 266 MB) and signed exactly as CLAUDE.md documents (codesign --force --deep -s - --entitlements entitlements.mac.plist). The signature then does NOT verify: 'codesign --verify --strict' rc=1, 'the main executable or Info.plist must be a regular file (no symlinks, etc.) In subcomponent: .../Contents/Frameworks/pync/vendor/terminal-notifier-2__dot__0__dot__0/terminal-notifier__dot__app/Contents/MacOS/terminal-notifier'. CAUSE: pync vendors a nested terminal-notifier.app and PyInstaller rewrites '.' to '__dot__' in those directory names, so 'terminal-notifier__dot__app' is no longer a valid bundle - its Info.plist/executable relationship is broken and strict verification of the WHOLE app fails. Both a correct 'terminal-notifier.app' and the mangled copy are present, under two mangled version directories. NOT OVERCLAIMED: 'spctl -a -vv' also says 'rejected', but that is expected for ANY ad-hoc signature (no Developer ID) and is not evidence of this defect. The app LAUNCHES and runs correctly despite it - verified by the operator's own screenshot: splash, login card, onboarding panel and institution picker all render correctly in WKWebView. CONSEQUENCE: harmless for today's ad-hoc distribution; NOTARIZATION would reject this bundle, so it blocks any future Developer-ID release, and it means '--force --deep' silently produces an unverifiable artifact. PROPOSED FIX (not applied - build-policy change, and the notification chain deserves care): exclude pync in scripts/build_excludes.py. It is fallback #3 of 4 in engine/notifications.py; CLAUDE.md documents it as unreliable on arm64 Sequoia; MAC_RUNBOOK says not to report it doing nothing; the PRIMARY UNUserNotificationCenter path is verified working by mac_smoke on this machine; the #4 osascript fallback was fixed 2026-08-10. Cost 180 KB. Stripping only the vendored .app is worse - it leaves pync importable but broken at runtime.

**Notes**: 

---

### RELEASE GATE: version.py still says 2.0.1, so a v2.0.2 build tells every user on every launch that an update is available - to the release they are already running
<!-- fp:240733a9e166 -->

**Status**: open
**Severity**: medium
**Category**: config
**Oracles**: O1 UI vs O3 disk (version.py + git tags)
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 3

**Detail**:

The sidebar of the running app reads 'v2.0.1' (screenshot fda_06_today_card.png, bottom left) while this audit is the final gate before v2.0.2 (tests/audit/MAC_AUDIT_PROMPT.md line 10) and v2.0.1 is ALREADY a shipped git tag. version.py has not been bumped. Four consequences, all measured or read off the source rather than supposed: (1) ui/auth.py:3915 prints the wrong version in the sidebar - observed. (2) ui/update_banner.py:97 computes update_available = _is_newer(github_tag, __version__); driven against the real function, _is_newer('2.0.2','2.0.1') returns True, so once the release is tagged v2.0.2 on GitHub EVERY user of that build sees the update notice permanently, pointing at the build they are running, on every launch. It cannot self-clear. (3) core/health_log.py:162 and core/canvas_debug.py:293 stamp diagnostics with 2.0.1, so every support report from the new release is mis-attributed to the old one - which matters most for the defects this very audit fixed. (4) CLAUDE.md records version.py as read by CI and both build specs, so the installer and bundle metadata would be stamped 2.0.1 too. Fix is one line, but it has to happen before the tag, and nothing in the build or the test suite currently asserts that version.py leads the newest tag.

**Notes**: 

---

### A COM-spawned EXCEL.EXE outlived 4+ rows (2h08m) while the app correctly killed every instance it tracked
<!-- fp:6759ff4ce798 -->

**Status**: open
**Severity**: medium
**Category**: robustness
**Oracles**: O3
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028 · 43665

**Detail**:

REFINES the earlier 'attribution uncertain' note by separating two phenomena I had conflated. The HANGS are plausibly aggravated by this audit's memory pressure (3 lanes on a 13.9 GB machine). The LEAK is not: memory pressure does not explain a process outliving its owner. Measured directly. The app spawns one Excel per conversion attempt and reclaims a hung one by PID - in row m028 alone it logged 'Excel hung >180s on <file>. Killing PID 26740 / 21420 / 27204', three different PIDs, all gone. Yet EXCEL.EXE PID 20872, CreationDate 20260808172055, was still alive at 19:29 - 2h08m, spanning at least m012, m013, m014 and m028. Its command line is 'EXCEL.EXE /automation -Embedding' with ParentProcessId 1396 (DCOM/RPCSS), so it is COM-launched and headless, NOT a user's own Excel window, and CLAUDE.md notes the session orphan reaper cannot see it precisely because it is a child of DCOM rather than of us. This is the class the 2026-08-08 _init_app hardening addresses (capture the PID immediately after DispatchEx, guard the property sets, _kill_app on failure) - one instance reachable from neither direction. User-visible consequence: a ~175 MB headless Excel that never exits, per occurrence, for the life of the session. NOT tied to a specific row by this evidence - 20872 appeared at 17:20:55, inside m014's window, which is a row whose convert_excel toggle was never applied, so the trigger is worth pinning down before fixing. To reproduce cleanly: run the office lane alone and watch for an EXCEL.EXE that survives a COMPLETED row.

**Notes**:   
> Not observed in the latest run.

---

### Architecture Rule 4 has regressed from 0 to 9, and 6 of them are deliberate audit-ignore comments off by ONE LINE
<!-- fp:238af9b928ce -->

**Status**: open
**Severity**: medium
**Category**: robustness
**Oracles**: O2,O3
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 6
**Scenario**: mac_m0_suite

**Detail**:

CROSS-PLATFORM, not macOS-specific - surfaced because the full unit suite was run here for the first time and tests/test_architecture_audit.py::test_repository_passes_its_own_audit fails. CLAUDE.md states Rule 4 is 'a real gate again (0 unsuppressed violations)'; it now reports 12, which this session reduced to 9. WHAT I FIXED (provably correct, 3 of the 12): ui/auth.py escapes with 'from html import escape as _he', and _SAFE_CALL_NAMES whitelists escaper ALIASES by name ('escape', 'html_escape', '_html_escape') but not '_he' - so three already-escaped interpolations read as unescaped. Added '_he'. The list's own comment records this having happened before with another private alias, so name-whitelisting has this cost by design; a named alias is still better than a suppression comment, which would also hide a genuine miss on the same line. WHAT I DID NOT FIX, and why: of the remaining 9, SIX carry a deliberate '# audit-ignore: <var> is a local filesystem path' comment that sits EXACTLY ONE LINE BELOW the reported violation - ui/sync_dialogs.py ignore at 1172 vs violation at 1171, ui/hub_dialog.py 1066 vs 1065 and 1272 vs 1271. The rule is documented as 'on or above a flagged line', so an ignore below suppresses nothing. The consistent off-by-one points at line attribution for a multi-line implicit f-string concatenation (the flagged expression is on one fragment, the author's comment on the next), which means a naive fix - moving the comments - could break on a different Python version, since PEP 701 changed f-string tokenisation in 3.12 and this machine runs 3.11. That needs verifying on both versions, which is off-machine work, so it is recorded rather than guessed at. RISK ASSESSMENT of the 9: none is Canvas-controlled data. Six are local folder names/paths (self-inflicted at worst - a user would have to name a folder with markup), and the other three are app-controlled (a CSS spacing value from _row_gap(), a metric label, and pre-built HTML rows in ui/panopto_page.py). So the gate is broken but the exposure is low. RECOMMENDED: decide whether the suppression window should include the line below for multi-line f-strings, or move the six comments and pin the behaviour with a test that runs on 3.11 and 3.12.

**Notes**: 

---

### CONFIRMED LEAK: the orphaned EXCEL.EXE survived the entire audit - 5h54m, outliving every lane, the app and the browser
<!-- fp:b79fd1dd2b22 -->

**Status**: open
**Severity**: medium
**Category**: robustness
**Oracles**: O3
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 1
**Scenario**: · 43665

**Detail**:

Decisive follow-up to the earlier 'attribution uncertain' note, taken AFTER full teardown. At 23:15, with zero audit Streamlit apps and zero audit Chrome processes remaining, EXCEL.EXE PID 20872 (CreationDate 20260808172055, command line 'EXCEL.EXE /automation -Embedding', ParentProcessId 1396 = DCOM/RPCSS) was STILL RUNNING - 5 hours 54 minutes old. It outlived all 12 office-lane rows, the app that spawned it, and the browser. That excludes the last benign explanation: it cannot be an instance a live conversion was using, because nothing was live. It is also not the user's own Excel - '/automation -Embedding' means COM-launched and headless. Contrast with the instances the app DOES track: during m028 it logged '[COM Timeout] Excel hung >180s ... Killing PID 26740 / 21420 / 27204', three different pids, every one reclaimed. So the app reclaims what it holds a handle or pid for, and 20872 was reachable from neither - exactly the failure the 2026-08-08 _init_app hardening describes (capture the pid immediately after DispatchEx, guard the property sets, _kill_app on failure). CLAUDE.md already notes the session orphan reaper cannot see such a process because it is a child of DCOM rather than of us. User-visible cost: a ~175 MB headless Excel that never exits. STILL NOT PINNED to a trigger: 20872 appeared at 17:20:55, inside m014's window - a row whose convert_excel toggle was never applied - so the spawning path is worth identifying before fixing. Reproduce by running the office lane alone and watching for an EXCEL.EXE that survives a COMPLETED row.

**Notes**:   
> Not observed in the latest run.

---

### On macOS a NORMAL quit is never recorded as a clean exit, so the health log reports every session as a crash
<!-- fp:75d3790bac46 -->

**Status**: open
**Severity**: medium
**Category**: robustness
**Oracles**: O2,O3
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 6
**Scenario**: mac_m3_clean_exit

**Detail**:

REAL PRODUCT DEFECT, reachable only from a packaged Mac app. start.py wraps webview.start() in try/finally and calls core.health_log.session_end(reason) from the finally, with a comment stating 'this marker is what the next launch reads to decide whether the app died or exited' and that its absence 'is the entire signal the health log carries'. On macOS the finally never runs: a Quit Apple event (what Cmd-Q and the Quit menu send) terminates the process from inside Cocoa's run loop without unwinding the Python stack. MEASURED, controlled, on the ad-hoc-signed bundle built here: launch -> pid 12966, state file reads clean_exit=False while running (correct, _save_state writes that on every sample); quit via 'tell application "Canvas Downloader" to quit'; process confirmed gone; state file STILL reads clean_exit=False with exit_reason=None. Three consecutive launches earlier the same hour each logged 'PREVIOUS SESSION DID NOT EXIT CLEANLY', including pid=6737 which had been quit gracefully after 788s of idle uptime. CONSEQUENCES: (1) the health log's central signal is permanently wrong on macOS - a genuine crash is indistinguishable from a normal Tuesday, on the platform CLAUDE.md itself calls out as having 'no crash-telemetry channel' and 'the least-tested path this app has'. (2) core.health_log._reap_recorded_orphans is armed on EVERY launch rather than after a real crash. The liveness guard added 2026-08-07 stops it destroying a live session's children, so this is not dangerous today - but it means that guard is now load-bearing in normal use rather than an edge case. (3) _terminate_child_processes() sits in the SAME finally, so on a normal quit it does not run either; no orphans were observed in practice, but the reaping that is supposed to happen before the hard exit is being skipped. FIXED (commit ad13d00): start.py now hooks pywebview's `closed` event, which fires from the Cocoa delegate - a path the Quit event does reach - and routes it through an idempotent `_shutdown` guarded by a threading.Event, so the ordinary window-close route (where start() DOES return and the finally also runs) still closes the record exactly once. VERIFIED on a rebuilt, re-signed bundle: after a normal quit the state file reads clean_exit=True and the log carries 'SESSION END (clean) uptime=14s'; the NEXT launch's SESSION START is followed by NO post-mortem line, where every earlier launch had one. The app still exits promptly and leaves nothing behind - two processes visible 6s after the quit were teardown lag and were gone shortly after. tests/test_startup.py, test_health_log.py and test_orphan_reaper_liveness.py all pass (60).

**Notes**: 

---

### Unexpected bridged_warning in debug log: Could not fetch items for module 'Uge 44: Forelæsning 8. JavaScript og Browseren, HTML 1':
<!-- fp:16e0de9e610a -->

**Status**: open
**Severity**: medium
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-05 (20260805_220433_sync-matrix)
**Last seen**: 2026-08-05 (20260805_220433_sync-matrix)
**Occurrences**: 1
**Scenario**: s024 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

Could not fetch items for module 'Uge 44: Forelæsning 8. JavaScript og Browseren, HTML 1': Encountered an error: status code 502

**Notes**:   
> Not observed in the latest run.

---

### A folder's Panopto formats can only be changed by running a Download, and that run silently narrows them - the sync side shows the contract but cannot edit it
<!-- fp:2368f8526178 -->

**Status**: open
**Severity**: low
**Category**: config
**Oracles**: O4 manifest (sync_metadata.panopto_contract) vs O1 UI
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 3

**Detail**:

A folder's stored panopto_contract is the single source of truth for which recording formats a sync produces, and this run showed the full consequence of that on a real folder. Before: {output_mp3: true, output_txt: true, output_srt: true, output_url: false, output_mp4: false}. After one Custom Download with Video selected: {output_mp4: true} and EVERY OTHER FORMAT false - while the folder still holds 36 mp3s, 5 txt, 5 srt and 36 weblocs, all still tracked in the panopto manifest.

That overwrite is the documented design and it is what makes the download run the way a user changes a folder's outputs at all (sync_ui only ever seeds the contract when it is None). The finding is about what a user can do NEXT, in two parts:

1. NOTHING on the sync side can change it. The pair's Edit form covers folder and course only; the ignored-recordings dialog READS the contract to decide which kinds count as configured; sync/analysis.py reads it and, by design, does not write unless it is absent. The Saved Groups hub displays a folder's stored Panopto config, so the app SHOWS the user a setting it gives them no control over - the only route back is to run another Download on that course with the formats they want.

2. The narrowing is silent. Nothing on the download screen says "this will also stop future syncs from maintaining the 36 mp3s in this folder". The practical effect is not deletion - nothing on disk is touched, and the manifest rows survive - but a locally deleted mp3 will no longer be restored by a sync, because mp3 is no longer a configured kind for that folder.

Recorded as an observation rather than a defect: every individual behaviour here is deliberate and documented in CLAUDE.md, including the specific warning that a Panopto gate placed inside the runner would let a download write an all-off contract over every folder it touched. The gap is that the contract is presented as visible state with no editor, and the one thing that rewrites it does so without saying so.

**Notes**: 

---

### A filename containing a line break can never be converted on macOS: the shared AppleScript escaper turns CR into a space, so the path stops resolving
<!-- fp:ad96dfaae9ad -->

**Status**: open
**Severity**: low
**Category**: conversion
**Oracles**: O2,O3
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 7
**Scenario**: mac_m1_hostile_names

**Detail**:

MEASURED with a positive control per case and a FRESH Word each time, which is what makes it trustworthy - an earlier all-in-one-process run failed 8 of 8 because the first hostile name wedged Word (see mac_m1_word_wedge), so only the first case after a passing control can be believed. Isolated results: 'Lec\rture.doc' FAILED, 'Say "hi".doc' CONVERTED, a 250-char ASCII component FAILED - each preceded by a plain 'control.doc' that CONVERTED. THE CAUSE for the CR case is exact and visible in the escaper's own output: engine.applescript_bridge.applescript_string renders the path ending as 'Lec ture.doc' - CLAUDE.md's documented rule that 'a line break becomes a SPACE, never empty, because deleting it would silently join two words of a name shown to the user'. That rule is right for a MESSAGE string and wrong for a PATH: the emitted AppleScript is syntactically valid but now names a file that does not exist, so Word cannot open it. Round-trip check: literal.endswith(name) is False for CR and True for the quote and long-name cases, i.e. the quote path is passed through faithfully and the CR path is corrupted. WHY IT IS A DEFECT RATHER THAN A LIMITATION: MAC_RUNBOOK item 4 states of exactly these two names that 'Both must convert normally - _as_posix neutralises them'. It neutralises the SYNTAX hazard only. REACHABILITY: macOS permits every byte but / and NUL in a filename, and CLAUDE.md notes an extracted ARCHIVE member never passes through _sanitize_filename, so a zip can put one in a course folder. CONSEQUENCE is safe but silent: the conversion fails, the source is kept, and the user gets no PDF for that one file. POSSIBLE FIX (not applied): a path must not go through the message escaper - pass it as raw bytes/POSIX file via a mechanism that cannot rewrite it, or reject/rename such a source explicitly so the failure is stated rather than silent. SEPARATE, NOT ISOLATED: the 250-char ASCII component also failed although its path round-tripped identically (component 254 bytes, legal on macOS whose limit is 255 BYTES per component; full path 293 chars, so office_container_stage's >=240 staging applies). The cause was not established - it is Word's own limit or the staging - and is recorded as an open question rather than a diagnosed defect.

**Notes**: 

---

### The locked-target _NewVersion fallback is unreachable on macOS: os.replace succeeds onto a read-only file, so a read-only course file is silently updated (and the 6 criticals it produced were the fixture asserting Windows semantics)
<!-- fp:8e7fc38cea3d -->

**Status**: open
**Severity**: low
**Category**: delivery
**Oracles**: O3 disk (POSIX rename semantics) vs O1 UI/O2 log (no error reported)
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 2

**Detail**:

The engine commits every downloaded file with an atomic rename, and its protection for a destination it cannot write is `except PermissionError` around that rename (sync/execution.py ~1081):

    try:
        os.replace(part_path, final_path)
    except PermissionError:
        # Target is locked (open in another app) ... deliver as _NewVersion

MEASURED on macOS 15, 2026-08-10, on a mode-444 file:
    open(target, 'wb')          -> PermissionError
    os.replace(tmp, target)     -> SUCCEEDS, target replaced

On POSIX a rename is authorised by write permission on the DIRECTORY, not by the target file's mode - so the exception never fires, and `_register_new_version(..., 'in_use')` is unreachable on macOS. Confirmed structurally as well: `_register_new_version` has exactly two call sites, `'edited'` (md5-based) and `'in_use'` (this one), and there is NO proactive writability test anywhere in the sync or download engines - no os.access, no W_OK, no S_IWUSR check in sync/execution.py, sync/analysis.py, core/canvas_logic.py or core/sync_manager.py.

WHAT THIS DOES AND DOES NOT COST, stated carefully, because the severity turns on it:
* It is NOT data loss, and the fixture calling it critical was wrong. The file being replaced in this scenario is a CLEAN update - its content still matches the manifest's recorded md5, so the user has authored nothing that is being discarded. The protection for a file the user has actually EDITED is the separate, md5-based `_NewVersion(reason='edited')` path, which is platform-independent and verified working on macOS by this same matrix.
* What is lost is the INTENT of the read-only flag. A macOS user who marks a course file read-only - the ordinary way to say "do not touch this" - has it silently updated anyway, with no notice and nothing in the log.
* The file-open-in-Word case that the code comment names does not behave as the comment implies either: on macOS an open document does not block a rename, so the file is replaced underneath the application. Word/Excel keeps the old inode, and a later save from that window writes the user's stale copy back over the fresh download. That is ordinary POSIX behaviour rather than a bug in this app, but the comment promises a fallback that cannot run.

NOT FIXED, deliberately, and the reasoning is the asymmetry: making this work on macOS means adding a proactive writability probe (os.access(W_OK), or a mode check) before every download commit. That is a new decision point in the hottest path of the engine, on every file of every sync, whose only benefit is honouring a flag almost nobody sets - and whose failure mode (forking a file the user did NOT edit into a _NewVersion sibling) is worse than the current behaviour, because it litters the folder and re-offers the same file on every later sync. The Windows fallback is an ERROR-AVOIDANCE mechanism, not a data-protection one: it exists because there the rename genuinely fails and the downloaded bytes would otherwise be dropped. On macOS there is no error to avoid.

WHAT WAS FIXED is the audit's own expectation, which produced 6 spurious CRITICAL findings on the first macOS sync matrix - expensive noise in a release gate, and the second time this fixture has misfired (a 2026-07-28 run recorded the same shape after it chmod'ed a conversion output instead of a download target). `readonly_target` now sets expect_after="" on POSIX with the measurement written into the comment, keeping expect_category="updated_clean" so the row still asserts what it can on this platform: that a read-only file is still classified as a clean update, and that the run reports neither a silent success nor a hard error. Re-ran the 3 affected rows (ro001/ro013/ro029) with the corrected fixture: all ok, 0 criticals, only the pre-existing informational long-path note.

**Notes**: 

---

### _show_macos_notification_un returns True before the delivery result arrives, so a REJECTED notification is reported as success and all three fallbacks are skipped
<!-- fp:3833d3d15043 -->

**Status**: open
**Severity**: low
**Category**: robustness
**Oracles**: O2 log (async ordering) vs O1 UI (9s of identical frames)
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 1

**Detail**:

_show_macos_notification_un's docstring promises: "Returns False on ANY failure so the caller falls back to NSUserNotification, keeping us strictly no worse than before". It cannot keep that promise for the failure that matters, because the delivery result arrives ASYNCHRONOUSLY:

    center.addNotificationRequest_withCompletionHandler_(req, _add_cb)
    logger.info("UN notification posted via UNUserNotificationCenter")
    return True                      # <- before _add_cb has run

_add_cb only LOGS the error; nothing consults it. So a request macOS REJECTS is reported to the dispatcher as success, and _show_macos_notification never tries NSUserNotification, pync or osascript. The log ordering proves the race rather than inferring it - "UN notification posted" is printed BEFORE "UN addNotificationRequest error", from one call:

    UN authorization result: granted=False error=UNErrorDomain Code=1
    UN settings: authorizationStatus=0 alertSetting=0 notificationCenterSetting=0
    UN notification posted via UNUserNotificationCenter
    UN addNotificationRequest error: UNErrorDomain Code=1        <- after the return
    _show_macos_notification_un: returned True

UNErrorDomain Code 1 is notificationsNotAllowed. Nine seconds of 0.25s screen captures of the banner corner produced byte-IDENTICAL frames throughout: nothing was ever displayed.

WHY THE FAILING RUN ITSELF IS NOT THE DEFECT, and this took a screenshot to establish rather than a guess: opening System Settings > Notifications showed the pane focused on an app called "Python", with "Allow notifications" OFF. A source run has no bundle identity, so the request is attributed to the INTERPRETER, and the interpreter is not allowed to notify. That is expected and is not what a user has - the packaged .app carries a bundle identifier (set in the PyInstaller spec) and registers as Canvas Downloader, which is why an earlier phase of this audit saw a UserNotificationCenter window appear on every call in the real app shape.

But that same screen is exactly the state that makes the code defect bite a real user: "Allow notifications" off for Canvas Downloader - either because they clicked Don't Allow once, or turned it off later - is an ordinary configuration, and in it the UN path returns True, the three fallbacks are skipped, and the notification silently does not exist. It matters most for the DAILY AUTO-SYNC, which is the one run nobody is watching and the one where the notification is the only signal that anything happened.

NOT FIXED, deliberately, and the reason is that the fix is not verifiable from here. The obvious repair - have _add_cb invoke the remaining fallbacks when it receives an error - is a handful of lines, but whether it HELPS depends on whether osascript/NSUserNotification can still display a banner while the app's own UN authorization is denied, and that question can only be answered in the packaged app with a real user denial. This box cannot produce that state: UN is notDetermined here because of the missing bundle identity, not because of a denial, so any fix would test green for the wrong reason. Shipping an unverifiable change to a fallback chain whose whole purpose is to be more reliable than what it replaces is the wrong trade.

WHAT A LATER SESSION SHOULD DO: launch dist/Canvas Downloader.app, complete one sync so macOS registers it and asks, choose Don't Allow, then fire play_completion_beep again and watch for a banner. If osascript still displays one, the async-callback fallback is worth wiring up; if macOS suppresses every path for a denied app, then returning True is harmless and the docstring is what should change instead.

Also seen: the diagnostic process ended with "Killed: 9" after driving all three paths in one short-lived process, matching the already-recorded finding that the notification path crashes a bare short-lived python process and is not reproducible in the real app shape.

**Notes**: 

---

### Three user-visible copy defects in the two macOS Full Disk Access surfaces - never caught because the gate has never opened on a dev machine
<!-- fp:5c546d9a8ecf -->

**Status**: open
**Severity**: low
**Category**: ui-truth
**Oracles**: O1 UI vs O1 UI (the app's own naming elsewhere)
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 3

**Detail**:

Both FDA surfaces rendered for the first time in this audit (they need macOS 15+ AND Full Disk Access absent, which no dev machine satisfies), and all three defects are in the copy a user reads at the moment they are being asked for a system permission. (1) shared/components.py:3779, Settings dialog card: 'asks a one-click "access data from other apps" permission THE every time you start the app' - a stray word. (2) shared/components.py:3716, Today nudge card: "makes features like the 'Todays Files' mode require your input" - the feature is called 'Today's files' in the sidebar, the page title and the query param; the nudge invented a third spelling and dropped the apostrophe. (3) shared/components.py:3715: 'your ai-ready formats' against 'Optimized for AI.' on the login page (ui/auth.py:1867). Fixed in this commit: the stray word removed, 'Today's files' bolded to match the sidebar label the step list already points at, 'AI-ready' capitalised, and 'office conversions' -> 'Office conversions' in the same sentence as (1). No behaviour change - these are string literals inside f-strings whose render path is verified by the same screenshots.

**Notes**: 

---

### M5 PASS: a quoted folder name survives the native picker's round trip, and the macOS-only trailing slash it returns is normalised by all three path keys
<!-- fp:624f77bfea70 -->

**Status**: open
**Severity**: info
**Category**: config
**Oracles**: O1 UI (real modal,operator click) vs O3 disk
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 1

**Detail**:

The last unproven half of the 2026-08-10 AppleScript escaping unification, and it needed one human click: sending keystrokes is refused on this box (System Events: 'osascript is not allowed to send keystrokes'), so the modal was opened by the real shared.helpers.native_folder_picker and dismissed by the operator. MEASURED: target /tmp/m5_picker/quoted "folder" name, returned /private/tmp/m5_picker/quoted "folder" name/ - the double quote survived intact, the returned path resolves to the folder chosen, and it exists on disk as returned. So both directions of the escaping rule now hold on a Mac: the INPUT (a default location containing a quote produced a working dialog, listing both fixtures correctly) and the OUTPUT. TWO INCIDENTAL FINDINGS, both benign, both worth knowing because they are macOS-only: (1) the returned path carries a TRAILING SLASH, because the macOS branch returns result.stdout.strip() and AppleScript's 'POSIX path of' appends one for a directory - Windows' shell picker and the tkinter fallback both return bare paths, so macOS is the only platform where a picked folder differs in spelling from a typed one. Verified harmless against the real functions: core.library.save_pair returns the SAME pair id for the bare and slashed forms, core.pair_labels.pair_key gives the same key, and core.sync_manager._path_key normalises both to the same string - so picking a folder twice cannot produce two pairs for one link. (2) it returns the /private/tmp resolved form rather than /tmp, because macOS symlinks /tmp into /private - the same symlink resolution that let /etc through the sync-folder safety guard earlier in this audit, here doing no harm because the comparison sites resolve too.

**Notes**: 

---

### M2 PASS: all 36 Panopto mp3s verify through bundled arm64 ffmpeg, duration matching the Windows-recorded baseline
<!-- fp:c671e557d0f3 -->

**Status**: open
**Severity**: info
**Category**: delivery
**Oracles**: O3,O5
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 6
**Scenario**: mac_m2_media

**Detail**:

Verified with RUNBOOK.md's own classification rule rather than by counting stderr lines (a non-empty ffmpeg stderr is muxer noise, not decode failure). Bundled binary: imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1, i.e. the arm64 build the app ships. Results over all 36 recordings of course 43660: 0 decode failures (rc=0 throughout), 0 lines matching the real-error set (Invalid data / corrupt / error while decoding / moov atom not found / Invalid NAL), 0 files missing an audio stream, 0 suspiciously short files, 0 leftover .part or .part.mp3. TOTAL DURATION 8.20 h across 36 files, mean 13.7 min - which matches the figure RUNBOOK.md recorded on Windows ('36 files, 8.21 h total, mean 13.7 min') to within a rounding step, so the arm64 ffmpeg produced equivalent content rather than merely producing something. Note 0 muxer-noise lines here, against the 1-532 per file the runbook records for mp4: the duplicate-DTS complaint is an mp4-muxer artifact and does not arise for mp3, so the 'do not report' trap is specific to the video output. STILL UNTESTED and listed as a gap: the mp4 output, whose specific checks are both streams present and '+faststart' honoured (moov before mdat) - 36 recordings of video is ~3.8 GB and was not run.

**Notes**: 

---

### CONFIRMED GOOD: both branches of resolve_shortcut_path verified live (free name vs Canvas collision)
<!-- fp:773eebe9d42e -->

**Status**: open
**Severity**: info
**Category**: panopto
**Oracles**: O3
**First seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Last seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Occurrences**: 1
**Scenario**: panopto_shortcut2 · 43660

**Detail**:

CLAUDE.md documents that a Panopto lecture IS a Canvas ExternalTool module item, so _create_link has usually already written a .url at the same name; the Shortcut output must ADOPT a link we produced, else take the first FREE name, else step over the foreign one to '<title> (Panopto).url'. Both branches exercised on the real course. BRANCH A (names free): convert_urls had compiled and consumed all 41 Canvas .url files first, so all 36 shortcuts took the PLAIN name; 36/36 carried the [CanvasDownloader] Source=Panopto marker and survived the URL compiler in the SAME run - the marker is the only thing preventing the app from deleting its own selected output. BRANCH B (names taken): a later run recreated the 41 Canvas links with convert_urls OFF, then pan_out_url ON produced 36 shortcuts - ALL 36 landed with the '(Panopto)' suffix, 0 took a plain name, and the 41 Canvas links were left untouched (77 .url total = 41 plain + 36 produced). Also verified: with pan_out_url OFF, the Canvas link phase legitimately reclaims those paths (36 produced -> 0), which is correct - the user did not ask for shortcuts that run.

**Notes**:   
> Not observed in the latest run.

---

### CONFIRMED GOOD: cancel mid-transcription leaves no orphaned worker and no .part files
<!-- fp:744c29fe6cbf -->

**Status**: open
**Severity**: info
**Category**: panopto
**Oracles**: O3
**First seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Last seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Occurrences**: 1
**Scenario**: pan_gpu_tx · 43660

**Detail**:

Cancelled during Phase 3 via cancel_panopto_btn (NOT cancel_download_btn - the Panopto phase has its own control; app.py:908 _active_dl_statuses includes 'panopto' so the click is not swallowed). Python pids before: ...35020, 35512 (workers). After: both gone; the only surviving pythons were the app (18944) and six unrelated processes started hours earlier. Leftover .part/.tmp files: 0. The 6 already-completed txt/srt pairs were correctly KEPT.

**Notes**:   
> Not observed in the latest run.

---

### CONFIRMED GOOD: the CPU downgrade path works end to end - proven for the first time
<!-- fp:684b77fa669f -->

**Status**: open
**Severity**: info
**Category**: panopto
**Oracles**: O2,O3
**First seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Last seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Occurrences**: 1
**Scenario**: pan_cpu_downgrade · 43660

**Detail**:

RUNBOOK ranked gap 1 said the audit had never proven this end to end, only that _is_vad_engine_error exists. Fault injected by replacing the run's cuda_libs JUNCTION with a real dir of 14 zero-value stub DLLs (the developer's real 1.8GB cuda_libs was verified intact at 14 files before and after, and the junction was restored). Settings still requested device=cuda, so the downgrade was genuinely exercised. Evidence chain from debug_log.txt: (1) 'Transcribe worker spawned: pid=30320 device=cuda'; (2) 'worker error: RuntimeError: Library cublas64_12.dll is not found or cannot be loaded' - exactly the injected fault; (3) failed FAST, 3.5s, no hang; (4) 'GPU transcription failed (...); falling back to CPU FOR THE REST OF THE RUN' - the fallback is run-scoped, so it does not re-attempt a broken GPU on all 30 remaining recordings; (5) 'Transcribing [1/30] (device=cpu)'; (6) two transcripts COMPLETED on CPU (srt 6->8). Measured cost: GPU 22.4/40.8/55.4s per recording vs CPU 104.7/129.8s (~3x). The downgrade does not merely log - it finishes the work.

**Notes**:   
> Not observed in the latest run.

---

### M2 PASS: Panopto discovery, 36 collision-resolved .webloc shortcuts, kind=url rows, and Launch Services opens ours
<!-- fp:f8d392f9cffb -->

**Status**: open
**Severity**: info
**Category**: panopto
**Oracles**: O3,O4
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 7
**Scenario**: mac_m2_panopto_url

**Detail**:

FIRST TIME the Panopto subsystem has ever run on macOS. All of it passed. (1) DISCOVERY via module-item LTI launches: 'Discovered 36 recording(s) ... by source {module: 36}', matching O5's ground truth for course 43660. The documented economy held: 'needs no media this run (Shortcut output only) - skipping the per-course session bootstrap', i.e. 0 runner handshakes. Closing line: 'found=36 downloaded=0 transcribed=0 shortcuts=36 skipped=0 failed=0 courses=1'. (2) THE CANVAS COLLISION CASE, which CLAUDE.md records as having shipped broken (36 recordings discovered, 34 identically-named .url files on disk, 0 shortcuts written): the M1 download had already written 41 Canvas ExternalTool/.webloc links via _create_link, so the precondition was real. Result on disk: 77 .webloc total = 41 Canvas-written (is_produced_shortcut False, untouched) + 36 ours, and ALL 36 of ours are named '<title> (Panopto).webloc' beside a still-present Canvas link. Ours carry source='Panopto' and point at the real Panopto viewer (cbs.cloud.panopto.eu/Panopto/Pages/Viewer.aspx?id=...), not at the Canvas module item. (3) O4: 36 rows in panopto_manifest, ALL with kind='url' - the documented rule that a .webloc must be recorded as kind 'url' and never 'webloc'. (4) DOES macOS OPEN IT - the one question MAC_RUNBOOK reserves for a human, and which CLAUDE.md says reasoning cannot settle ('what that cannot prove is Finder itself'). Answered: A/B'd a URL-only plist against one carrying our extra CanvasDownloaderSource key, both opened through Launch Services, and Safari reported 'https://example.com/plain, https://example.com/ours' - so the marker key does NOT prevent the URL being read. Finder also renders both with the internet-location icon. NOTE ON A FALSE ALARM: a first attempt produced a blank Safari with an empty address bar, which looked like the shortcut being broken. Safari on this cloud image is flaky (it failed to launch at all with _LSOpenURLsWithCompletionHandler error -600 for Safari.app itself), and the operator confirmed their own double-clicks worked. An mdls probe was uninformative - kMDItemURL is null for OUR file AND for a Canvas one, so it distinguishes nothing.

**Notes**: 

---

### M2 PASS: all 36 Panopto mp4s carry both streams and honour +faststart, and the mp4-only DTS 'muxer noise' is provably an artifact of RE-muxing, not of the stored file
<!-- fp:4297120c0e6d -->

**Status**: open
**Severity**: info
**Category**: panopto
**Oracles**: O3 disk (mp4 atoms + ffmpeg decode) vs O1 UI vs O4 manifest
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 3

**Detail**:

The mp4 output had never been run on any platform in this audit series. Course 43660, Custom Download with Panopto set to Video only, into the folder that already held the mp3/txt/srt/url run - 36 recordings, 2.0 GB, no cancellation needed because they arrived far faster than expected (20-140 MB each, not the ~100 MB average assumed).

VERIFIED, all 36: both a video and an audio stream present (h264 Main 1920x960 60fps + aac LC 44100 stereo on the sampled file), and moov BEFORE mdat - read out of the container's top-level atom chain rather than trusting that the flag was passed, because a remux whose second pass fails leaves a perfectly valid file with moov at the end. 0 problems, 0 zero-length stubs, 0 ffmpeg errors in the app's log. The audio carries the mp4a/ASC tag rather than ADTS framing, so the conditional aac_adtstoasc bitstream filter did its job on the HLS source.

NOTE the bundle ships NO ffprobe (one ffmpeg binary, by build policy), so these checks use "ffmpeg -i" plus a hand-written mp4 atom walker. A verifier reaching for ffprobe would be testing a tool the product does not have.

THE DTS TRAP, now characterised rather than merely warned about. RUNBOOK.md flags mp4-only duplicate-DTS muxer noise, and it does appear - in 2 of 4 sampled files - but every message is prefixed "[null @ 0x...]", i.e. it is emitted by the VERIFIER's own null OUTPUT MUXER, and ffmpeg still exits rc=0. Isolated further: a video-only re-mux produces 1 such line while decoding all 1201 frames of the sampled 20 seconds successfully; an audio-only re-mux produces 0; and the app's own debug log for the whole 36-recording run contains 0. So a source video track carries a non-monotonic DTS somewhere (an ordinary Panopto HLS segmentation artifact), "-c copy" preserves it verbatim as stream copy must, the file decodes and plays, and the warning is reachable only by re-muxing - which the app never does. It is noise, and it is not the app's noise.

STEM FIX VERIFIED LIVE, on the exact video id that produced the 70-mp3 duplication: the manifest for 0074fde5-eba4-42a7-b226-b35f00c6be2c now holds mp3 and mp4 sharing the plain stem "Forelaesningsvideo (2) Uformelletraek_organisationskultur" while url keeps the disambiguated " (Panopto).webloc" - which is precisely the divergence the pre-fix code resolved the wrong way. Across all 36: 0 mp4s carry a "(Panopto)" stem and 36/36 sit beside their own mp3. Prediction was recorded before the run, so this was falsifiable: without the fix every mp4 would have landed at "<title> (Panopto).mp4" next to the mp3 already there.

Also confirmed in passing: a download re-run does NOT duplicate existing Canvas files. A first pass counting names containing "(N)" reported 136 conflict copies, which was a FALSE POSITIVE - these Canvas lecture titles literally contain "(1)"/"(2)" ("Forelaesningsvideo (2): ..."). Counting only files whose stem ENDS in " (N)" and whose un-suffixed sibling also exists gives 0. The skip-if-size-matches path in _download_file_async is doing its job; 36 of 177 files were skipped in the first 25 seconds and the MB denominator correctly excluded them (0.0 / 849.4 MB).

**Notes**: 

---

### M2 PASS: hardware probe reports Apple Silicon CPU-only calmly, and the model download works through the real dialog
<!-- fp:23e00263ae66 -->

**Status**: open
**Severity**: info
**Category**: panopto
**Oracles**: O1,O3
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 6
**Scenario**: mac_m2_hardware

**Detail**:

Real app, real dialog, macOS 15.6.1 on an Apple M4. MAC_RUNBOOK M2 item 5 requires that 'there is no CUDA, so the CPU path is the only path; panopto/hardware.py must report that calmly rather than raising'. Verified on screen in the Transcription Configuration dialog: 'Detected Hardware - GPU: Apple Silicon - no GPU mode (the engine runs on the CPU)' and 'CPU: 10-core CPU - Apple M4', with Compute Device defaulting to CPU and GPU offered but not selected. The guidance line adapts to the hardware too ('Large v3 Turbo is recommended for CPU transcription on 10 cores. A GPU would allow a larger model.'). No exception, no empty state, no claim of CUDA. mac_smoke independently confirms the same four facts from the probe API (is_mac, no CUDA claimed, CPU recommended, ctranslate2 4.8.1 imports in a clean process). The Tiny model (75 MB) downloaded through the dialog and shows as Active with a delete control, which is MAC_RUNBOOK item 6's 'Manage installed models' state.

**Notes**: 

---

### M2 PASS: transcription runs on the Apple-silicon CPU path out-of-process, and the 2026-08-09 cancel/.part fix holds on macOS
<!-- fp:8865d4a80a5d -->

**Status**: open
**Severity**: info
**Category**: panopto
**Oracles**: O2,O3
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 6
**Scenario**: mac_m2_transcription

**Detail**:

FIRST macOS run of the transcription subsystem, and of the .part cleanup fix that was written for a Windows-observed defect. (1) MODEL: Tiny (75 MB) downloaded through the real Transcription Configuration dialog, landing in panopto_models/tiny/model.bin (90 MB on disk) and shown as Active. (2) MEDIA: all 36 recordings' mp3 produced through the BUNDLED ffmpeg on arm64 in about two minutes; sizes 17.8-24.3 MB. (3) WORKER: 'Transcribe worker spawned: pid=10891 device=cpu frozen=False' - so it runs OUT OF PROCESS as designed (panopto/transcribe_worker.py exists because of an OpenMP clash that segfaults rather than erroring), on the CPU, with no CUDA claimed. Two recordings completed: 'OK in 86.8s: txt, srt' and 'OK in 140.7s: txt, srt' on a 10-core M4. Outputs are genuine, not stubs: srt 25,847 and 33,171 bytes with real timecoded Danish ('Velkommen til enddel af forlaesning om ...' - tiny-model accuracy, as expected), txt 17,519 and 25,158 bytes, each beside its mp3 as a complete triplet. (4) THE CANCEL, which is the point: cancelled 5 seconds into worker pid=11065 while it was actively WRITING - two sidecars ('...organisationsstruktur 2025 37.srt.part' and '.txt.part') were confirmed present on disk at the moment of the click, which is precisely the mid-write condition that produced the original leak. AFTER: zero .part files anywhere in the tree, and no transcribe_worker/faster_whisper process left. So the sweep-in-a-finally fix (panopto/runner.py) and the make_long_path delete (panopto/transcribe.py) both hold on real macOS. NOTE: the log carries no explicit cleanup line, so O3 (the absent files) is the only oracle for the sweep here - the same asymmetry the original finding relied on in the other direction, where the ABSENCE of post-loop lines was the proof it had not run.

**Notes**: 

---

### M3 PASS: the frozen bundle routes transcription workers correctly - argv drop defended, no phantom GUI child
<!-- fp:3597eb288d36 -->

**Status**: open
**Severity**: info
**Category**: panopto
**Oracles**: O2,O3
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 6
**Scenario**: mac_m3_argv_drop

**Detail**:

FIRST test of this from a real bundle. A macOS windowed .app rebuilds sys.argv from Apple events and silently drops a custom flag, which made a child launched with --panopto-transcribe-worker boot the FULL GUI instead: 'a second app window opened for every transcription and the parent blocked until the user closed it'. The fix routes primarily via the CANVAS_DL_TRANSCRIBE_WORKER env var, keeps the flag as a backup, and records the winner in _CANVAS_DL_WORKER_ROUTE. Driven against dist/Canvas Downloader.app built and ad-hoc signed on this machine, feeding a job on stdin: (a) the bundle SHIPS the console worker binary _worker_command prefers (Canvas_Downloader_Worker, arm64) alongside Canvas_Downloader; (b) with ONLY the env var - no flag at all - both binaries answered 'worker start: frozen=True routed_via=env device=cpu want_txt=True want_srt=True' and exited in 0.1-0.2s, so the argv-drop defence itself works; (c) with ONLY the flag, both answered 'routed_via=argv', so the backup signal works too; (d) with NEITHER, both sat until my 20s timeout, i.e. they booted the app rather than a worker - the correct negative control, and the thing that proves (b) and (c) measured routing rather than a binary that always enters worker mode. (e) The count of 'Canvas Downloader' GUI processes stayed at 0 across all six launches, which is the phantom-second-Dock-app symptom absent. The 'KeyError: mp3' each worker returned is my probe's deliberately incomplete job payload, and is itself evidence: worker mode was entered and answered on stdout with a JSON error event instead of ignoring stdin.

**Notes**: 

---

### M4 PASS on real HFS+: the one place _path_key's Unicode normalisation is not a no-op
<!-- fp:2477d9d49c3c -->

**Status**: open
**Severity**: info
**Category**: persistence
**Oracles**: O3,O4
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 7
**Scenario**: mac_m4_hfs_nfd

**Detail**:

Verified on a REAL HFS+ volume created with hdiutil, which is the only way to reach this: APFS is normalisation-PRESERVING so a modern Mac hides the case entirely, and an external drive does not. Four rows, all passing: 'APFS is normalisation-PRESERVING - os.walk returned the NFC we wrote'; '_path_key agrees across NFC/NFD'; 'HFS+ hands back the DECOMPOSED name - as expected, this is the case APFS hides'; '_path_key maps both forms to ONE key'. This is the class CLAUDE.md records as reading like a random defect, because Danish 'aa' decomposes while 'oe' and 'ae' do not - so on an HFS+ external drive a tracked file with an a-ring would drop out of the tracked set and inflate the review screen's untracked count, while its siblings behaved. The single _path_key primitive (normcase(normpath(NFC(s)))) holds. Also green in the same suite: make_long_path is a no-op off Windows, >600-char paths, and the 255-BYTE component limit.

**Notes**: 

---

### All 6 remaining macOS suite failures were Windows-semantics TESTS, not product defects - suite now green at 3240 passed
<!-- fp:e3d7560a21b4 -->

**Status**: open
**Severity**: info
**Category**: regression-guard
**Oracles**: O3 disk (real functions driven per platform) vs the suite
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 1

**Detail**:

The macOS run started with 16 suite failures, was triaged to 6 earlier in this audit, and is now at 0 - 3240 passed, 25 skipped. NOT ONE of the six was a product defect. Every one was a test asserting Windows semantics against code that behaves correctly for its platform, which is worth recording as a class because on a first macOS run it is indistinguishable from a regression, and the temptation is to "fix" the product.

The six, with what each actually proved:

1. test_archive_decline_cleanup - the absolute-member case hard-coded C:/Windows/Temp/... On POSIX that is not absolute at all; it is a legal RELATIVE name whose first component happens to be "C:". Driven against the real extract_archive: it lands at <target>/C:/Windows/Temp/pwn.txt, fully contained, nothing escapes - the right outcome. A POSIX-absolute member (/tmp/...) and a ../../ traversal are both blocked and return None. The test now uses an absolute path for the RUNNING OS, and a second test pins the Windows-path-on-POSIX case as contained rather than deleting the coverage.

2. test_audit_panopto_delivery - looked for the extension minus its dot in the check's title. That equals the kind for mp3/mp4/txt/srt and NOT for the shortcut, whose kind is "url" while its extension is .url on Windows and .webloc on macOS. So it passed on Windows by pure coincidence and on macOS searched for a kind the engine never records. The checker itself gets this right via kind_from_path and carries a comment warning against exactly this reasoning - the test guarding it committed the error the comment describes.

3+4. test_library and test_pair_labels - one test each conflated three different normalisations behind a C:\ path: separators, trailing slash, and case. A backslash is a legal FILENAME character on POSIX and os.path.normcase is the identity function there, so two thirds cannot hold. Split into the platform-invariant half (course-id type and trailing slash) and a Windows-only half. The trailing slash is the form that actually differs on macOS in practice: the native picker returns one (AppleScript's "POSIX path of" appends it), so a picked folder differs in spelling from a typed one - measured, and normalised correctly by save_pair, pair_key and _path_key alike.

5. test_transcribe_partial_cleanup - emulates LongPathsEnabled=0 by requiring a \\?\ prefix, but make_long_path is deliberately a no-op off Windows, so the emulated failure can never be satisfied and the test would assert against its own premise. Skipped with that reason.

6. test_architecture_audit - Rule 4, covered by its own finding: all nine violations were justified suppressions the audit could not reach, because Python 3.11 attributes a FormattedValue to the START of a multi-line f-string while build_suppressed_lines only walks forward.

THE CASE QUESTION IS STILL OPEN and is deliberately not closed by this work. On a case-INSENSITIVE macOS volume (the default) a case-only rename is the same folder to the OS and a different link to the app, so _path_key's case half being a no-op is a real defect there. It is not fixable with a .lower(): an external case-SENSITIVE volume is an ordinary place to keep a course folder, and folding there would mis-bind heals. It needs a per-volume probe. Its own finding covers it.

**Notes**: 

---

### CONFIRMED GOOD: 3 transient Excel COM failures, 2 recovered by retry, 1 permanent - original kept and the UI reported the TRUE final count
<!-- fp:854cd2ac81f9 -->

**Status**: open
**Severity**: info
**Category**: regression-guard
**Oracles**: O1,O2,O3
**First seen**: 2026-08-08 (20260808_223701_minimal-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_223701_minimal-sync-2026-08)
**Occurrences**: 1
**Scenario**: m028_c43665 · 43665

**Detail**:

Full reconciliation of the only genuine conversion survivor in the matrix. O2 (log) records THREE Excel timeouts on m028: 'ekstraopgave 1 - VL.xlsx', 'HA.IT-reeksamen-2020-VL-Endelig1.xlsx' and 'OmkostningerAfsaetning - Ekstra - LOESNING.xlsx', each '[COM Timeout] Excel hung >180s ... Killing PID <n>' with a DIFFERENT pid, so the app spawned a fresh instance per attempt and reclaimed each hung one. O3 (disk) then shows exactly ONE surviving .xlsx and 60 PDFs - the other two converted on a later attempt in the same phase. O1 (completion screen) says '1 file could not be converted', i.e. the TRUE FINAL count, not the 3 transient errors, and explains it in the user's terms: 'The original file downloaded fine and is in your course folder - only the converted copy could not be made ... Close any open Office windows and run this course again to retry just it. Details are in download_errors.txt in each course folder.' Same screen also reports '24 files skipped because they exceeded the 5 MB limit'. So all three oracles agree at 1, the source-deleting converter kept the file it could not convert (the 2026-08-08 pdf_looks_real gate), and the user is told what happened and what to do. CORRECTS an earlier mid-run note of mine that said two originals were kept - that was a snapshot taken while the phase was still running; the end state is one.

**Notes**:   
> Not observed in the latest run.

---

### CONFIRMED GOOD: a real Excel COM failure did NOT delete the user's original workbook
<!-- fp:6b63263260b9 -->

**Status**: open
**Severity**: info
**Category**: regression-guard
**Oracles**: O2,O3
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028 · 43665

**Detail**:

Reproduced live, not synthetically. The office lane hit '[ERROR] [converters.excel] [COM] Excel init failed: (-2146959355, Server-udfoerelse mislykkedes)' = CO_E_SERVER_EXEC_FAILURE, followed by '[ERROR] [converters.post_processing] ekstraopgave 1 - VL.xlsx  Conversion timed out after 180s (Excel stopped responding)'. O3 then shows the source STILL PRESENT at 'Ekstra traening (traening i gl. eksamensopgaver)/ekstraopgave 1 - VL.xlsx', with its 'ekstraopgave 1 - VL_Data.txt' sidecar beside it. This is the exact condition the 2026-08-08 hardening was written for ('An Office converter deletes the user's original - so the PDF must be PROVEN first'): the COM call did not raise cleanly, no usable PDF was produced, pdf_looks_real refused the delete and the workbook was kept. The run also continued to later files rather than aborting the phase, which is _run_phase's isolation doing its job. Worth recording as evidence that the guard holds against a REAL Office failure and not only against a seeded stub.

**Notes**:   
> Not observed in the latest run.

---

### Notification path crashes a bare short-lived python process; NOT reproduced in the real app shape
<!-- fp:ad41f04027c9 -->

**Status**: open
**Severity**: info
**Category**: robustness
**Oracles**: O1,O2
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 7
**Scenario**: mac_m5_notifications

**Detail**:

OBSERVATION with an explicit caveat, recorded so it is not lost and not overstated. Calling the REAL engine.notifications.play_completion_beep(mode='daily_sync', ...) from a bare python process repeatedly produced 'Python quit unexpectedly' (the macOS crash reporter) and a shell 'Killed: 9'; the operator confirmed 'python keeps crashing when you do that'. It is NOT consistently fatal - one invocation that slept 4s afterwards printed 'fired ok' and exited cleanly - so it is a race. WHY THIS IS PROBABLY NOT A PRODUCT DEFECT: my test posts a notification from a short-lived python with no Cocoa NSApplication run loop and then exits, which is not the app's shape. The real app shares the process with the PyWebView Cocoa NSApplication (start.py) and lives on, which is precisely why _show_macos_notification_native calls that 'the robust primary path'. The code already anticipates this exact mismatch: play_completion_beep's comment says 'post on the calling thread avoids run-loop issues - the daemon thread context can differ from what UNUserNotificationCenter/its delegate callbacks expect, and a daemon thread can be killed during process shutdown before the completion handler fully executes'. WHAT IS THEREFORE STILL UNPROVEN, and belongs in the gap list: whether a real sync completion in the PACKAGED app delivers a visible banner. mac_smoke reports 'UNUserNotifications delivered - a banner should be visible', and a UserNotificationCenter window (260x300) does appear on each call, but the banner itself outran every capture attempt (macOS banners last ~5s) and no screenshot of our banner text was obtained. A SEPARATE FALSE LEAD, recorded so the next audit does not chase it: a 'Terminal would like to access the microphone' TCC prompt was captured while investigating this and initially looked like the notification path requesting the microphone. It is not - re-running the identical code produced no such prompt, nothing in the notification chain (UNUserNotificationCenter -> NSUserNotification -> pync -> osascript) or in afplay touches audio input, and a UserNotificationCenter window was already present BEFORE the first notification call. It was almost certainly one of the pending permission prompts the operator approved minutes earlier.

**Notes**: 

---

### M5 PASS: the macOS 15 Full Disk Access nudge verified end to end on all FOUR surfaces, in both gate directions - the first time this code has ever rendered
<!-- fp:afd30c33904c -->

**Status**: open
**Severity**: info
**Category**: ui-truth
**Oracles**: O1 UI vs O3 disk (today_dashboard.json,TCC.db)
**First seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 3

**Detail**:

Reaching it at all was the blocker: the gate needs macOS 15+ AND Full Disk Access absent, and every context that can run the app had FDA. Solved by running the app from the SSH session, whose responsible process (/usr/libexec/sshd-keygen-wrapper) carries an explicit DENIED row for kTCCServiceSystemPolicyAllFiles, so has_full_disk_access() returns False for real rather than by patching. Login was done by hand through the real form because the Keychain is Aqua-scoped - and that incidentally confirmed the 'a persistence failure must never block a login' rule: keyring was unavailable, restore_saved_session correctly fell back to the login page, and a pasted URL+token logged in with no error. VERIFIED: (1) Today page - dismissed state renders the subtle re-spawn link with the exact copy, clicking it spawns the full card, all four walkthrough steps render as a real ordered list with no HTML leaking, the close button collapses the card back to the link and the persisted flag holds. (2) The button runs open_full_disk_access_settings(): System Settings opened directly on Privacy & Security > Full Disk Access with 'Canvas Downloader' present in the app list by name - so the legacy x-apple.systempreferences anchor still deep-links correctly on macOS 15, and step 2 of the walkthrough ('Toggle on Canvas Downloader in the app list') describes what the user actually sees. Screenshot 183506_desktop.png. The toast fired with the right text (fda_08_toast.png). (3) Settings dialog - render_fda_settings_card in its NOT-GRANTED state: blue dot, 'Not granted' status line, full step list. (4) Download settings step 2 - gated on an Office converter; enabling Legacy Word inside Card 3's FRAGMENT made the nudge appear even though the slot lives OUTSIDE that fragment, i.e. the documented escalation to a full-page rerun fired, and disabling it removed the nudge again. Both directions left exactly one Card 3 header and one Confirm button, so the escalation does not produce the inherited-children artifact this repo has hit elsewhere. (5) Quick Download - present for 'Daily study pack (Optimized)', absent for 'Files Only', so the preset gate is real and not always-on.

**Notes**: 

---

### ~~'readonly:Opgave reformulering - bilag.xlsx' was locally edited but no _NewVersion sibling was created~~
<!-- fp:6a83c06e72be -->

**Status**: invalid
**Severity**: critical
**Category**: delivery
**Oracles**: O5,O3
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-08-10 (20260810_151922_macos-15-v2.0.2)
**Occurrences**: 22
**Scenario**: s029 · Virksomhedens økonomiske styring (2) Regnskabsvæsen (LA F26 BINTO1057U)

**Detail**:

The product's stated contract is that local edits are never overwritten and the new copy lands alongside.

**Notes**: AUDIT FIXTURE DEFECT — but TWICE, for two DIFFERENT reasons, so read both before judging a third occurrence.

(1) 2026-07-28, Windows: `readonly_target` had chmod'ed a CONVERSION OUTPUT (`x_js.txt`) rather than a download target. The engine writes the Canvas file first (`x.js`, writable) and the converter renames it afterwards, so the write path was never blocked - no PermissionError, no _NewVersion, and the fixture was silently exercising the converter's failure path instead of the locked-target fallback it was written for. The fixture now only picks rows whose local extension matches their Canvas filename.

(2) 2026-08-10, macOS 15, the 6 occurrences in `20260810_151922_macos-15-v2.0.2` (s001/s013/s029, `.xlsx`, converters OFF - so cause 1 does NOT apply): the fixture was asserting **Windows semantics**. Measured on a mode-444 file: `open(target,'wb')` raises PermissionError but **`os.replace(tmp, target)` SUCCEEDS** - on POSIX a rename is authorised by write permission on the DIRECTORY, not by the target's mode. The engine's fallback is `except PermissionError` around that rename (sync/execution.py ~1081), so `_register_new_version(..., 'in_use')` is unreachable on macOS and a read-only file is simply updated. NOT data loss: the file is a CLEAN update, and the EDITED-file fork is a separate md5-based path that works on every platform. `seed.readonly_target` now sets `expect_after=""` on POSIX; the 3 rows were re-run with the corrected fixture and reported 0 criticals.

So the earlier claim here that "the locked-target fallback is verified working elsewhere" is true **on Windows only** - that run was Windows. Do not read it as cross-platform. Full reasoning, including why the product was deliberately NOT changed, is in the low-severity finding "The locked-target _NewVersion fallback is unreachable on macOS".

---

### ~~Local edits to a CONVERTED file are overwritten - _NewVersion protects the download, but post-processing regenerates the output on top of your work~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:bc9703c2e9f2 -->

**Status**: fixed
**Severity**: critical
**Category**: delivery
**Oracles**: O3,O2
**First seen**: 2026-07-28 (20260728_211019_syncmatrix)
**Last seen**: 2026-07-28 (20260728_211019_syncmatrix)
**Occurrences**: 1
**Scenario**: s001 · 45899

**Detail**:

Measured, both bytes and log, on sync row s001.

The user edited two files that are CONVERSION OUTPUTS - hints.md (from hints.html) and Create_ILearn_tables_sql.txt (from Create_ILearn_tables.sql). The row ticked 'updated_modified', so this is the accepted path.

The analysis is right: it maps the source to the converted target, '[UPDATE-EDIT] hints.html -> .../hints.md'. The plan even says '[modified update (_NewVersion)]'.

But the fork is applied to the DOWNLOADED file's name. The fresh hints.html lands at its own plain path - where nothing needs protecting - and post-processing then regenerates hints.md at its canonical name, straight over the file the user edited.

Result: md5 0cf8870d -> 44b3b792 and 1e213dd3 -> d18bff9a, with NO _NewVersion sibling for either. The edits are gone.

This defeats the one guarantee the feature exists to make. The completion screen says 'Saved next to your copy, which was left untouched' - and for a converted file that is not what happened.

SCOPE: any locally-edited conversion output - convert_html (.md), convert_code (.txt), convert_excel (.pdf/_Data.txt), convert_word/pptx (.pdf), convert_video (.mp3). Quick Sync is NOT affected: it declines locally-edited files entirely and says so ('Quick Sync always skips locally-deleted and locally-edited files').

NOT YET FIXED - the fix belongs where the fork name is chosen, which must become the name of the file actually being replaced (the conversion OUTPUT) rather than the downloaded source. That is the same delicate write path as the open duplicate-download finding, and it needs a verifying re-run.

**Notes**: EXACT SITE: `sync/execution.py:1354` - `if is_update_modified and filepath.exists():`. `filepath` is the DOWNLOAD target (the source name), so the test asks whether the SOURCE is on disk, not whether the file the user edited is. Two ways it fails:
  - `convert_html` keeps its source, so `hints.html` exists and gets forked to `hints_NewVersion.html` - protecting a file nobody edited, while post-processing still regenerates `hints.md` over the edit.
  - `convert_code` CONSUMES its source, so `Create_ILearn_tables.sql` does not exist, no fork happens at all, and the fresh source converts straight over `Create_ILearn_tables_sql.txt`.

TWO WAYS TO FIX:
  (a) Keep the promise exactly - the user's file stays at its own name and the NEW copy lands as `<stem>_NewVersion<ext>`. That means the conversion output name has to be diverted, so post-processing needs to be told the canonical name is taken by an edited file.
  (b) Smaller, and it fully prevents the data loss: EXCLUDE the source from this run's conversion set when its output was locally edited. The chokepoint already exists - `sync/execution.py:2045 get_synced_file_paths()` is the one place sync decides what post-processing may touch, and it already carries a comment about a previous bug where a broader scope 'converted-then-DELETED' the user's own files. The user then keeps their edited output AND gets the fresh source beside it; they simply do not get the new content in converted form until they resolve it.

(b) is the one to land first: it is contained, it stops the data loss, and it needs no change to the converters. (a) is the complete answer and can follow. Either needs a verifying re-run - seed `edited_update` on a snapshot with converters (c45899_base), sync with `updated_modified` ticked, and confirm the edited output's md5 is unchanged.

FIXED 2026-07-28 with (a), the complete answer - (b) was skipped because it trades data loss for a silently WRONG folder (the user keeps their edit but never gets the new content in converted form, and nothing says so). The code had already documented the gap in its own words at `sync/execution.py:1305`: *"the ownership-aware converter then overwrites the tracked PDF in place"* - the design deliberately delegates to the converter and never told it the file was edited. Three parts:

1. `core/sync_manager.py:protect_conversion_target(path)` / `is_conversion_target_protected(path)` - an in-memory, per-run set. `sync/execution.py` marks the edited OUTPUT at the point that already knows it is edited (the analyzer's own `is_update_modified` verdict). This is the authoritative signal and the only one that works on folders created before this version.
2. `converters/post_processing.py:_resolve_conversion_target(sm, src, ext, default_name=)` - the single destination resolver every converter already shared - now diverts to `<stem>_NewVersion<ext>` when the target is protected, or (durable backstop) when the recorded product md5 no longer matches what is on disk.
3. `core/sync_manager.py` now records the product's **md5 alongside its path** (`_record_conversion_product`), with `conversion_product()` reading both the new dict form and the legacy bare-string form. The backstop needed this because by the time post-processing runs, the manifest row has been repointed at the freshly downloaded SOURCE and no longer describes the product at all.

A fourth change was required and is the reason the first attempt failed: `convert_code` never went through the shared resolver, computing its own `<stem>_<ext>.txt` destination - which is exactly why `Create_ILearn_tables_sql.txt` got no diversion whatsoever. It now takes a `dst=` override (`converters/code.py`), passed with an explicit `default_name` because its output is a stem rewrite rather than a suffix swap.

Self-correction worth recording: the first version relied on the recorded md5 ALONE. Every unit test passed, but the verification snapshot predates the record - so real users' existing folders would have received no protection at all. The seeded run caught it. That is why the run-scoped mark is primary and the hash is only a backstop.

VERIFIED in the real app - run `20260728_224830_fixverify`, snapshot `c45899_base`, `seed apply --kinds edited_update` (2 files), `flow sync --select updated_modified` -> landed on review, 2 touched, confirm ok:
```
g1 darts vejl_løsn_js.txt    73678d0d -> 73678d0d   PRESERVED   (+ ..._NewVersion.txt, 1280 B)
gk2 vejl_løsn_js.txt         50199ba0 -> 50199ba0   PRESERVED   (+ ..._NewVersion.txt, 1298 B)
```
Both edits byte-identical, fresh content alongside - exactly what the completion screen promises.

THE OTHER DIRECTION, verified separately and at least as important: this resolver runs on EVERY conversion, so a false positive would fork every product on every sync. Run `20260728_234157_cleanconv`, same snapshot, `seed apply --kinds clean_update` on the same two files, synced **twice**:
- pass 1 - log reads `[UPDATE-CLEAN]` -> `[clean update (overwrite)]` -> `Updated manifest entry ... to new file: ..._js.txt` -> `[SYNCED]`. Products overwritten in place. **0 `_NewVersion` files.**
- pass 2, with the product hash record now live for those two files - again in place, **0 `_NewVersion` files**, and every recorded hash still matches its file on disk. (Pass 2 is the one that matters: pass 1 cannot exercise a record it is itself creating.)
- The restored snapshot carries **103 legacy bare-string product records** alongside the 2 new dict-form ones, so the mixed-format read and the "no recorded hash -> previous behaviour" branch were exercised against real data rather than a fixture. No churn on folders converted by an older version.

1216 tests pass; `verify_architecture.py` clean.  
> Not observed in the latest run.

---

### ~~Sync post-processing crashes with NameError: _attempts is not defined~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:5d735855a0d8 -->

**Status**: fixed
**Severity**: critical
**Category**: robustness
**Oracles**: O1,O2
**First seen**: 2026-07-30 (20260730_142424_ship_sync_20260730)
**Last seen**: 2026-07-30 (20260730_142424_ship_sync_20260730)
**Occurrences**: 1
**Scenario**: s001

**Detail**:

sync/execution.py:2272 calls _attempts.append(...) but _attempts is never initialised anywhere in the file (used 7 times: appends at 2272/2277/2283/2303/2317/2322, read at 2325 retry_failed_conversions). Introduced by commit 4b98b2e (2026-07-29), which copied the conversion retry-pass pattern from converters/post_processing.py:run_all_conversions - where _attempts: list = [] IS declared at line 1125 - without copying the declaration. TRIGGER: unconditional. Unlike the download flow, which guards every append behind 'if pptx_files:', line 2272 runs on every sync that reaches post-processing, regardless of contract or file types. Confirmed on THREE different snapshots simultaneously (c43657_study, c43657_isolated, c45899_base); only the no-op 'nothing changed' row survived because it returns before post-processing. IMPACT: run_pptx_conversion at 2271 completes first - and it is source-consuming, so .pptx originals are deleted - then the NameError aborts the script run. Everything after 2272 never executes: HTML-to-MD, code-to-TXT, URL compilation, Word-to-PDF, Excel data+PDF, video-to-MP3, the retry pass, and the sidecar ledger injection at 2327. The user sees a Streamlit exception screen instead of a completion screen. 1951 unit tests pass against this; it is only reachable by running a real sync.

**Notes**: Fixed 2026-07-30, same day, same session that found it. `_attempts: list = []` now declared in `run_sync` before the converter section (sync/execution.py), mirroring `run_all_conversions`. Introduced by 4b98b2e when the retry-pass was copied over WITHOUT its declaration; unconditional there (the download flow guards each append behind `if <files>:`), so it fired on every sync that transferred a file, on every contract shape - confirmed simultaneously on c43657_study, c43657_isolated and c45899_base. Only the no-op "nothing changed" row survived, because it returns before post-processing. VERIFIED by re-running the full 43-row sync matrix against the fix: 43/43 rows, **0 defects**, zero `NameError` in any lane log, and the `edited_update` critical fixture passing on 11 of 12 rows across all four contract shapes and both sync modes (the 12th was a 20s UI click timeout that the identical configuration passed elsewhere - transient, not a defect). GUARDED by `tests/test_undefined_names.py`, an AST checker asserting no function in 8 engine modules reads a name nothing binds. A test naming `_attempts` would not have caught the FIRST bug of this class (the `isolate` UnboundLocalError in CLAUDE.md) and would not catch the next; the guard validates in both directions and includes a case that strips the real declaration from the real file and asserts it still fires, so it cannot quietly die in a refactor.  
> Not observed in the latest run.

---

### ~~'renamed-ambiguous:zz flertydig 1.pdf' expected as new but no oracle placed it in any category~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:2e38f73c0857 -->

**Status**: invalid
**Severity**: high
**Category**: classification
**Oracles**: O5,O2
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 18
**Scenario**: p2r_defaults · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

Renamed, row dropped, and another file shares its size and extension. The uniqueness guard must REFUSE to adopt, so New is correct - binding here would silently mark a missing file present and the user would never get it back.

**Notes**: AUDIT MATCHER DEFECT, fixed. The app placed all 11 New rows correctly; the matcher did not know three of the app's own naming conventions, so it could not find them on the screen. A fixture records the name a file has ON DISK; the review screen shows the name it has ON CANVAS, and between them sit: a converter rename (`x.js` -> `x_js.txt`), a secondary-entity prefix (`Quiz <title>.md` shown as `<title>` + an HTML chip), and an attachment inside an entity (`Assignment <entity> - <file>.pdf` shown as just `<file>`, sometimes with a `-1` dedup suffix). `crosscheck._name_candidates` now derives every legitimate form. Re-checked on the same folder: 6 of these became 0.  
> Not observed in the latest run.

---

### ~~Adoption tier (c) binds a same-size, same-extension file of UNRELATED content~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:1d964fc34314 -->

**Status**: fixed
**Severity**: high
**Category**: classification
**Oracles**: O5,O4
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-28 (20260727_165705_bootstrap)
**Occurrences**: 4
**Scenario**: p2_sync_45899 · Programmering (45899)

**Detail**:

core/sync_manager.analyze_course tier (c) adopts an untracked on-disk file when exactly one orphan shares the Canvas file's size AND extension. It performs no name comparison and no content comparison.

Proven live: a file of identical byte-length but entirely different content ('decoy N unrelated.pdf', all zero bytes) was silently bound to a deleted Canvas file. The real file was never offered as New and will never be re-downloaded; the user keeps junk under the manifest row of the file they lost. Both decoy fixtures were adopted; both renamed_ambiguous fixtures were correctly REFUSED, so the uniqueness guard itself works.

Why it matters more than the code comment assumes: tier (c) is documented as the fallback for when tier (b) - the md5 content match - is unavailable. Measured on course 43660, Canvas exposes md5 for 0 of 140 files, so tier (b) NEVER fires against this instance and tier (c) is doing all the work, content-blind, on every rename. The safety net the design assumed is not there.

Note heal_manifest is unaffected: its Tier 2 compares original_md5 local-to-local and is exact. This only concerns files whose manifest ROW is gone.

Options: require a name-similarity floor for tier (c) as heal Tier 3 already does (>=0.90 stem containment, ambiguity reject); or mark such adoptions low-confidence and re-verify on next sync; or accept it and document that a size collision can shadow a file.

**Notes**: Fixed 2026-07-27 (option 1: name-similarity floor). core/sync_manager._name_floor_reject now requires stem CONTAINMENT before tier (c) may bind, and every adoption and refusal is logged. Containment was chosen over a similarity ratio by measurement: heal Tier 3's 0.90 ratio rejects genuine renames (Intro->Intro_v2 = 0.857, Lecture 1->Lecture 1 (annotated) = 0.684) while PASSING the substitutions it is meant to stop (Lecture1->Lecture2 = 0.917). Verified live on course 45899: both planted decoys refused, both real files recovered (New went 7 -> 11), and every row-intact rename still adopted via heal Tier 2. Guarded by tests/test_tier_c_name_floor.py (23 tests, incl. the calibration itself) + test_engine_fixes.py.  
> Not observed in the latest run.

---

### ~~Every Panopto shortcut is offered as a 'clean update' on every analysis, for ever~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:6fe18c5a9b2f -->

**Status**: fixed
**Severity**: high
**Category**: classification
**Oracles**: O1,O2,O4
**First seen**: 2026-07-28 (20260728_130002_phase4_panopto_full)
**Last seen**: 2026-07-28 (20260728_130002_phase4_panopto_full)
**Occurrences**: 2
**Scenario**: p4_panopto_sig · 43660

**Detail**:

A module ExternalTool item is written to disk as a .url shortcut, and its content_sig is what a later analysis compares to decide changed-or-not. The signature was computed from a DIFFERENT url than the one the file received:

  file contents : html_url        (https://<canvas>/courses/43660/modules/items/1128498 - unique per recording)
  signature     : external_url    (https://cbs.cloud.panopto.eu/Panopto/LTI/LTI.aspx - the LTI launch endpoint)

That endpoint is the SAME string for all 36 recordings in the course, so it cannot identify one, and the signature could never match the one recorded at download time.

Measured on a folder downloaded minutes earlier: 36 rows in 'Updates Available', 0 md5 mismatches, every one a .url shortcut. Verified by recomputing both candidate signatures against the stored value - sig(url-in-file) matched, sig(external_url) did not, for all 36.

Consequences, all permanent:
  - the course can never reach 'all up to date'
  - every sync rewrites 36 shortcut files
  - Quick Sync and the daily auto-sync do it every day
  - the Today page counts them as 'updated' arrivals daily, so a user on Today mode sees 36 files land every morning that did not change

Same family as the Pages identity bug documented immediately below it in the source ('35 new files on a fresh download', 2026-07-09): the download path and the scan path must agree on what identifies an entity.

FIXED: the signature is now computed from the url the file actually receives, special-cased by type. ExternalUrl keeps its original ordering (external_url first) - a first attempt used one ordering for every type and turned the 5 correct ExternalUrl rows into phantoms instead, the same bug moved. Verified in the running app across three analyses of the same folder: 36 -> 5 -> 0 updates, with the 3 genuine transcript jobs and 33 ignored recordings unaffected throughout.

Guarded by tests/test_link_content_sig_parity.py, which runs BOTH directions and asserts two recordings in one course get different signatures.

**Notes**: Fixed and verified end to end in the running app (36 -> 5 -> 0 across three analyses of the same folder). The intermediate 5 was a wrong first fix that moved the bug to ExternalUrl; both directions are now covered by tests.  
> Not observed in the latest run.

---

### ~~'deleted-locally:Debug - grades - 1.txt' should have been left alone but was written to Uge 48 Forelæsning 12. Node.js og debugger samt eksamensforberedelse/Debug - grades - 1.txt~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:91d640ef7d5a -->

**Status**: invalid
**Severity**: high
**Category**: delivery
**Oracles**: O5,O3
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 2
**Scenario**: p2nv_selected · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

File removed but its manifest row kept, which is what a real user deletion looks like. The deletion must be respected: unchecked by default, and always skipped by Quick Sync.

**Notes**: AUDIT DEFECT, fixed. The fixture predicts 'absent' because a deleted-locally row is UNCHECKED by default. This run ticked it on purpose (`--select deleted_locally`, the second Phase 2 scenario), so restoring the file is exactly what the user asked for. `_sync_outcome` is now selection-aware in BOTH directions: an unticked restore/new_version becomes 'unchanged', and a ticked 'absent' becomes 'restored'. Re-checked: 2 of these became 0.  
> Not observed in the latest run.

---

### ~~'deleted-locally:minefeltVEJL_js.txt' should have been left alone but was written to Uge 44 Forelæsning 8. JavaScript og Browseren, HTML 1/minefeltVEJL_js.txt~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:78c7871b2180 -->

**Status**: invalid
**Severity**: high
**Category**: delivery
**Oracles**: O5,O3
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 2
**Scenario**: p2nv_selected · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

File removed but its manifest row kept, which is what a real user deletion looks like. The deletion must be respected: unchecked by default, and always skipped by Quick Sync.

**Notes**: AUDIT DEFECT, fixed. The fixture predicts 'absent' because a deleted-locally row is UNCHECKED by default. This run ticked it on purpose (`--select deleted_locally`, the second Phase 2 scenario), so restoring the file is exactly what the user asked for. `_sync_outcome` is now selection-aware in BOTH directions: an unticked restore/new_version becomes 'unchanged', and a ticked 'absent' becomes 'restored'. Re-checked: 2 of these became 0.  
> Not observed in the latest run.

---

### ~~Download finished with 1 unexplained error(s)~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:fa2cae30e286 -->

**Status**: fixed
**Severity**: high
**Category**: delivery
**Oracles**: O2,O3
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 15
**Scenario**: m036 · m036

**Detail**:

Errors this course logged that are not teacher-locked files. Each names the item the engine could not deliver.

**Notes**: The undeliverable discussion on course 43660, fixed 2026-07-28 by resolve_discussion_topic() (defined core/canvas_logic.py:290, called at 3 sites). Registered separately as "A discussion Canvas lists but will not serve individually is never downloaded". This title is the reworded check from checker defect 24, which now NAMES the failing item instead of printing a bare count. product-stale evidence from a pre-fix run.  
> Not observed in the latest run.

---

### ~~A discussion Canvas lists but will not serve individually is never downloaded, and is reported as an error~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:fa247ec01d02 -->

**Status**: fixed
**Severity**: high
**Category**: discovery
**Oracles**: O5,O2,O3
**First seen**: 2026-07-28 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 4
**Scenario**: m025 · 43660

**Detail**:

Canvas returns discussion topic 166950 in get_discussion_topics() COMPLETE WITH ITS MESSAGE BODY, and raises ResourceDoesNotExist for get_discussion_topic(166950). It is not a group discussion, it is not locked, and it opens normally in a browser.

The module-item path only ever tried the individual GET. So the item failed outright: no file for a discussion the user can plainly read, an 'ERROR [Discussion Dispatch Error]' entry naming something they cannot act on, and an inflated error count - this is what pushed three otherwise-clean matrix rows to 'Download finished with N errors'.

The data was already in hand on the path the app takes anyway.

FIXED: resolve_discussion_topic() tries the individual endpoint first and falls back to the collection, which is the same 'prefer the richer object, keep the other as fallback' shape the assignment path already uses. A genuinely absent topic still raises, and the individual endpoint's error is the one that propagates. All three call sites route through it; a test fails if a fourth calls the endpoint directly.

**Notes**: Fixed 2026-07-28 and verified against the live API. `resolve_discussion_topic()` tries the individual endpoint first and falls back to the collection - the same 'prefer the richer object, keep the other as fallback' shape the assignment path already uses, in the other direction. A genuinely absent topic still raises, and the individual endpoint's error is the one that propagates. All three call sites route through it; tests/test_discussion_resolve.py fails if a fourth calls the endpoint directly.  
> Not observed in the latest run.

---

### ~~1 content file(s) on disk with no manifest row~~~~~~~~~~~~~~~~
<!-- fp:371b678dbdf1 -->

**Status**: invalid
**Severity**: high
**Category**: persistence
**Oracles**: O3,O4
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Occurrences**: 17
**Scenario**: · Indføring i organisationers opbygning og funktion (LA E25 BINTO1060U)

**Detail**:

Each of these will be offered as a NEW file on every future sync unless the analyzer's adoption tiers reclaim it. This is the 'wrongfully shows up as new' failure.

**Notes**: The file was `Compiled_External_Links.txt` — the single aggregate output `convert_urls` writes for the whole course after consuming every `.url`. It is a conversion product, so it has no manifest row BY DESIGN, exactly like the 21,630 archive-extracted files beside it. || SECOND CAUSE, 2026-07-29 - this entry now covers TWO different defects and the `invalid` above applies only to the first. On m025_c46396 the two files were 'Grupper til Klyngevejledning 1-1.pdf' and 'Grupper til Klyngevejledning 2.pdf': the orphaned second copies of the duplicate-download bug (fetch counts name file ids 1784620/1807289, the exact pair CLAUDE.md records for it), not a conversion product. That cause is FIXED - see the duplicate-download entry - and the evidence here is product-stale from a pre-fix run. HAZARD worth remembering: the register fingerprint is (category + digit-normalised title), so 'N content files on disk with no manifest row' is ONE entry no matter which files or which cause. A status set for one cause silences the other. Before trusting an `invalid`, check that the CURRENT evidence matches the cause the note describes.

The audit's own exemption for this existed and never fired: it read `expect["converters"]` while `check download` is handed a FLAT config. The same shape mismatch was also reporting the 25 consumed `.url` rows as a broken manifest. Both now read the `sync_contract` the app stored in the folder, which is what the engine itself obeys.

Verified on a fresh, never-seeded download of 45899 with every converter on: 0 defects. Guarded by tests/test_audit_converter_evidence.py, including a control proving the exemption still reports a genuinely missing .pdf.  
> Not observed in the latest run.

---

### ~~2 Canvas file(s) were downloaded more than once in one run~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:d05cc83d973a -->

**Status**: fixed
**Severity**: high
**Category**: persistence
**Oracles**: O2,O4
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 6
**Scenario**: m001_c46396 · m001_c46396

**Detail**:

Each of these ids went to the network twice. Two phases both claimed the file, so two copies are on disk and only one can hold the manifest row - the other is an untracked orphan. Canvas Content must run before every Files-tab sweep; see _defer_to_canvas_content.

**Notes**: DUPLICATE of "A file that is both a Files-tab file and a Canvas Content attachment is downloaded twice", fixed 2026-07-28 by running Canvas Content before all THREE Files-tab sweeps. This is the mechanical check added the same day, so it fires on pre-fix rows by construction. Verified fixed on 5 targeted post-fix runs (modules+inline, modules+isolate, flat+inline, each twice; a repeat run made ZERO HTTP requests). product-stale evidence from a pre-fix run.  
> Not observed in the latest run.

---

### ~~4 manifest row(s) point at files that do not exist~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:09c8ffb50041 -->

**Status**: invalid
**Severity**: high
**Category**: persistence
**Oracles**: O4,O3
**First seen**: 2026-07-28 (20260728_005027_baseline_45899_pristine)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 4
**Scenario**: p2r_defaults · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

The app believes these files are present. On the next sync each reads as 'deleted locally', which is unchecked by default and always skipped by Quick Sync - so they are never re-downloaded and never mentioned again.

**Notes**: Same root cause as the `Compiled_External_Links.txt` entry above, and fixed by the same change. These 25 rows are the `.url` files `convert_urls` consumed; the engine documents a bypass that treats a missing source of a source-consuming converter as 'converted away'. The audit's exemption for exactly this existed but read `expect["converters"]` while `check download` passes a flat config, so it never fired — the comment beside it even predicts 25 rows.

Now derived from the folder's stored `sync_contract`. Re-checked on the same pristine folder: reported as an observation, 0 defects. The exemption is per-extension, so a genuinely missing .pdf alongside consumed .url rows is still reported (guarded).  
> Not observed in the latest run.

---

### ~~A file that is both a Files-tab file and a Canvas Content attachment is downloaded twice, and the first copy is orphaned~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:f5c9f9d3c10f -->

**Status**: fixed
**Severity**: high
**Category**: persistence
**Oracles**: O2,O3,O4
**First seen**: 2026-07-28 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 4
**Scenario**: m025 · 46396

**Detail**:

Two HTTP fetches of the same Canvas file id, 21 seconds apart, in one run.

The Catch-All phase downloads every Files-tab file whose id is not already in _downloaded_ids | _module_ids. That set is computed when the Catch-All runs - and the Canvas Content phase runs AFTER it, so a file that phase is about to fetch as an announcement or assignment attachment cannot possibly be in the set yet.

Three consequences, in ascending order of harm:

1. The file is downloaded TWICE. Wasted bandwidth on every run.
2. TWO copies land on disk under different names - the Catch-All writes to the course root under Canvas display_name, the attachment writes under an entity-prefixed name.
3. The manifest ends up holding only the attachment path, so the root copy has NO manifest row. That is the wrongfully-shows-up-as-new failure: every future sync offers it again, for ever.

Measured on course 46396, ids 1784620 and 1807289.

NOT the app own conflict resolution: the 1-1 suffix is Canvas duplicate-upload naming; _handle_conflict appends ' (N)'.

FIX NOT YET APPLIED, deliberately. The candidates all touch download phase ordering or the dedupe contract: pre-compute the secondary attachment ids before the Catch-All, or run Canvas Content first, or dedupe by canvas_file_id at write time. This project already carries one duplicate-files fix in this area, so the change needs the full matrix result and a verifying re-run rather than a same-hour patch.

**Notes**: ROOT CAUSE CONFIRMED, and the design question is settled by the app's own precedent. `sync_manifest.canvas_file_id` is the PRIMARY KEY, so the model is one Canvas file -> one local file; two copies cannot both be tracked, which is why the second write left the first orphaned rather than adding a row. The app already resolves the identical situation for MODULE files: when a file is reachable both through a module and through the Files tab it keeps the content-context copy and logs 'Catch-All skipping module file: X (ID: n)'. By exact analogy the announcement/assignment attachment copy should win and the Catch-All should skip it - which is also the placement a user wants, the file sitting beside the announcement that refers to it.

So the fix is: give the Catch-All the ids the Canvas Content phase is about to claim, the same way it is already given `module_file_ids`. Rejected alternatives: reordering the phases (moves the 'Canvas Content Phase' log marker and the progress UI's phase sequence, for no extra correctness), and deduping at write time by canvas_file_id (same outcome, but it decides the winner by arrival order rather than by which placement is right).

NOT YET IMPLEMENTED: it needs a verifying re-run of an affected configuration (course 46396, dl_announcements on), and the matrix currently owns the machine. The evidence is preserved under _audit_runs/20260728_145153_matrix/evidence/.

WHICH COPY WINS - settled by the app's own placement logic, not by preference. `_resolve_secondary_path` creates an entity's own folder (`Announcements/<Entity Name>/`) ONLY when `has_attachments` is true, so in the default isolate mode the attachment copy is structurally load-bearing: drop it and you get a folder shaped like an entity that has no attachments. The attachment copy must therefore win and the Catch-All must yield.

(The module precedent cited above is weaker than it first looks - `module_file_ids` wins because modules are processed FIRST, not because anything prefers them. The placement logic is the real argument.)

TWO WAYS TO IMPLEMENT, both needing a verifying run:
  (a) give the Catch-All the ids the Canvas Content phase will claim. Complete, but the API-attachment half of that set needs a per-assignment refetch that the secondary phase already performs - so it either costs the calls twice or needs the secondary enumeration split into plan-then-execute.
  (b) let the secondary phase MOVE an already-downloaded copy into the entity folder instead of re-fetching it. One download, correct placement, one manifest row, no pre-pass - but it changes the engine's write path.
(b) is the smaller change and fixes all three symptoms; (a) is the more conservative one. Deferred rather than guessed at: this area already carries one duplicate-files fix, and the matrix owns the machine until the GPU lane finishes.  
> Not observed in the latest run.

---

### ~~2 partial-write artifact(s) left on disk~~~~~~~~~~~~~~~~
<!-- fp:62da7c0a9988 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O3
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Occurrences**: 4
**Scenario**: · Indføring i organisationers opbygning og funktion (LA E25 BINTO1060U)

**Detail**:

A `.part` file after the run means an atomic write was abandoned without cleanup. The next analysis must ignore it, and the user sees a junk file in their course folder.

**Notes**: AUDIT DEFECT, fixed. These are the seeder's own `partial_artifact` fixtures (`interrupted download.pdf.part`, `recording.part.mp4`) - created on purpose to prove the app ignores partials. Counting the fixture that proves correct behaviour as evidence of incorrect behaviour is exactly backwards. The seed plan now DECLARES what it deliberately broke (`seed.declarations`) and the invariants honour it.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: Failed to convert code file g1 darts vejl_løsn.js: [Errno 13] Permission denied: 'G:\\18 A~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:18cc3b9d802a -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 5
**Scenario**: p2nv_pass2 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

Failed to convert code file g1 darts vejl_løsn.js: [Errno 13] Permission denied: 'G:\\18 AI\\ANTIGRAVITY WORKSPACES\\Canvas Downloader\\_audit_runs\\20260728_013336_phase2_newversion\\downloads\\Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)\\Obligatoriske afleveringer

**Notes**: NOT A PRODUCT DEFECT - the app correctly reporting a failure the audit caused. The `readonly_target` fixture had made a conversion OUTPUT read-only, so the converter genuinely could not write it and said so, in download_errors.txt and in the completion screen's post-processing warning. The fixture is fixed (see the _NewVersion entry). The underlying asymmetry it exposed - graceful fallback on a locked download target, hard failure on a locked conversion target - is recorded separately as its own low finding.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: Failed to convert code file gk2 vejl_løsn.js: [Errno 13] Permission denied: 'G:\\18 AI\\AN~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:8224b9e3a4a1 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 5
**Scenario**: p2nv_pass2 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

Failed to convert code file gk2 vejl_løsn.js: [Errno 13] Permission denied: 'G:\\18 AI\\ANTIGRAVITY WORKSPACES\\Canvas Downloader\\_audit_runs\\20260728_013336_phase2_newversion\\downloads\\Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)\\Obligatoriske afleveringer efte

**Notes**: NOT A PRODUCT DEFECT - the app correctly reporting a failure the audit caused. The `readonly_target` fixture had made a conversion OUTPUT read-only, so the converter genuinely could not write it and said so, in download_errors.txt and in the completion screen's post-processing warning. The fixture is fixed (see the _NewVersion entry). The underlying asymmetry it exposed - graceful fallback on a locked download target, hard failure on a locked conversion target - is recorded separately as its own low finding.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: HA.IT-reeksamen-2020-VL-Endelig1.xlsx  Conversion timed out after 180s (Excel stopped resp~~~~~~~~~~~~~~~~~~~~
<!-- fp:f4ec25425a4b -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

HA.IT-reeksamen-2020-VL-Endelig1.xlsx  Conversion timed out after 180s (Excel stopped responding)

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: OmkostningerAfsætning - Ekstra - LØSNING.xlsx  Conversion timed out after 180s (Excel stop~~~~~~~~~~~~~~~~~~~~
<!-- fp:7d8d6987eef9 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

OmkostningerAfsætning - Ekstra - LØSNING.xlsx  Conversion timed out after 180s (Excel stopped responding)

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: Productionanalysis - Eksempel.xlsx  Conversion timed out after 180s (Excel stopped respond~~~~~~~~~~~~~~~~~~~~
<!-- fp:bacba60611c0 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

Productionanalysis - Eksempel.xlsx  Conversion timed out after 180s (Excel stopped responding)

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: VL - Ord2024.xlsx  COM Error: (-2147023174, &#x27;RPC-serveren er ikke til rådighed.&#x27;~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:958f127d0717 -->

**Status**: fixed
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-05 (20260805_154112_matrix-dl)
**Last seen**: 2026-08-05 (20260805_154112_matrix-dl)
**Occurrences**: 1
**Scenario**: m008 · Virksomhedens økonomiske styring (1) Virksomhedens grundlæggende beslutningssituationer (LA E25 BINTO2063U)

**Detail**:

VL - Ord2024.xlsx  COM Error: (-2147023174, &#x27;RPC-serveren er ikke til rådighed.&#x27;, None, None)

**Notes**: Fixed 2026-08-05. The Office->PDF converters left an orphaned, empty process when the RPC channel died (Quit() threw and was swallowed). converters/{excel,word,pdf}.py _kill_app now force-kills the tracked PID via engine.office_pid.kill_office_pid, guarded by pid_is_process (targeted /PID, never a broad /IM). Validated live; full suite green. The RPC blip itself is a transient Excel hiccup the converter self-heals from.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: [COM Timeout] Excel hung >180s on HA.IT-reeksamen-2020-VL-Endelig1.xlsx. Killing PID 21420~~~~~~~~~~~~~~~~~~~~
<!-- fp:f7950a0ff1d0 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

[COM Timeout] Excel hung >180s on HA.IT-reeksamen-2020-VL-Endelig1.xlsx. Killing PID 21420.

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: [COM Timeout] Excel hung >180s on OmkostningerAfsætning - Ekstra - LØSNING.xlsx. Killing P~~~~~~~~~~~~~~~~~~~~
<!-- fp:41de4d13af9a -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

[COM Timeout] Excel hung >180s on OmkostningerAfsætning - Ekstra - LØSNING.xlsx. Killing PID 27204.

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: [COM Timeout] Excel hung >180s on Productionanalysis - Eksempel.xlsx. Killing PID 17556.~~~~~~~~~~~~~~~~~~~~
<!-- fp:d5dff49dc678 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

[COM Timeout] Excel hung >180s on Productionanalysis - Eksempel.xlsx. Killing PID 17556.

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: [COM Timeout] Excel hung >180s on ekstraopgave 1 - VL.xlsx. Killing PID 22472.~~~~~~~~~~~~~~~~~~~~
<!-- fp:fe53cd768483 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 4
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

[COM Timeout] Excel hung >180s on ekstraopgave 1 - VL.xlsx. Killing PID 22472.

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: [COM] Excel init failed: (-2146959355, 'Server-udførelse mislykkedes', None, None)~~~~~~~~~~~~~~~~~~~~
<!-- fp:74a494b938a5 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

[COM] Excel init failed: (-2146959355, 'Server-udførelse mislykkedes', None, None)

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: ekstraopgave 1 - VL.xlsx  Conversion failed twice~~~~~~~~~~~~~~~~~~~~
<!-- fp:23015c7d7ccf -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

ekstraopgave 1 - VL.xlsx  Conversion failed twice

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: ekstraopgave 1 - VL.xlsx  Conversion timed out after 180s (Excel stopped responding)~~~~~~~~~~~~~~~~~~~~
<!-- fp:b751e7a4c30f -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

ekstraopgave 1 - VL.xlsx  Conversion timed out after 180s (Excel stopped responding)

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: g1 darts vejl_løsn.js  Conversion failed~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:0995f8315ce5 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 5
**Scenario**: p2nv_pass2 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

g1 darts vejl_løsn.js  Conversion failed

**Notes**: NOT A PRODUCT DEFECT - the app correctly reporting a failure the audit caused. The `readonly_target` fixture had made a conversion OUTPUT read-only, so the converter genuinely could not write it and said so, in download_errors.txt and in the completion screen's post-processing warning. The fixture is fixed (see the _NewVersion entry). The underlying asymmetry it exposed - graceful fallback on a locked download target, hard failure on a locked conversion target - is recorded separately as its own low finding.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_error in debug log: gk2 vejl_løsn.js  Conversion failed~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:ac0b7c1a10e5 -->

**Status**: invalid
**Severity**: high
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 5
**Scenario**: p2nv_pass2 · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

gk2 vejl_løsn.js  Conversion failed

**Notes**: NOT A PRODUCT DEFECT - the app correctly reporting a failure the audit caused. The `readonly_target` fixture had made a conversion OUTPUT read-only, so the converter genuinely could not write it and said so, in download_errors.txt and in the completion screen's post-processing warning. The fixture is fixed (see the _NewVersion entry). The underlying asymmetry it exposed - graceful fallback on a locked download target, hard failure on a locked conversion target - is recorded separately as its own low finding.  
> Not observed in the latest run.

---

### ~~'Quick Sync now' was physically unclickable whenever auto-sync was OFF - the default state~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:8badba1fc12c -->

**Status**: invalid
**Severity**: high
**Category**: ui-truth
**Oracles**: O1
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 1
**Scenario**: t3_quick_sync · Today page

**Detail**:

The Today page dims its sections when auto-sync is off, and the dimming carried pointer-events: none. That property is INHERITED, so it reached the button inside the 'Sync on demand' card.

Measured in the running app, both states, same session:

  auto-sync OFF   button in viewport, disabled=false, computed pointer-events 'none',
                  elementFromPoint at the button's centre returned the WRAPPER div,
                  and a real click TIMED OUT ('element does not receive pointer events')
  auto-sync ON    button in viewport, disabled=false, computed pointer-events 'auto'

Flipping the toggle alone moved it, which is what establishes the cause.

Why it matters: auto-sync off is the DEFAULT, the button is a primary action painted with its full brand gradient, and the card it sits in says 'trigger a manual Quick Sync any time to bring these courses up to date right now'. The button was enabled server-side (disabled=not runnable or sync_running - auto_sync_enabled is deliberately not part of that), so the app believed it was offering the action. Nothing about this is visible in a screenshot and nothing logs it; only a hit test or a real click finds it.

FIXED: the two reasons for dimming are now separate. Auto-sync off dims the daily-sync sections only (today_courses_card, today_files_hero) - the manual action is the one thing that must still work in that state. A running sync dims the Quick Sync card too, which is honest because the button is disabled server-side then anyway.

Verified after the fix + app restart, auto-sync still off: pointer-events 'auto', section opacity 1 (was 0.45), hit test reaches the button, and a real Playwright click succeeds. The other two sections still dim at 0.45, so the intended visual signal is intact.

Guarded by tests/test_today_quick_sync_clickable.py, including a general check that no future section may be added to the dimming rules without confirming it holds no enabled control.

**Notes**: INVALID - the behaviour is intentional, and the change has been REVERTED.

Quick Sync's real home is the Sync page. What sits on the Today page is a SHORTCUT, for someone who has turned Today mode on and lives on that page day to day, so they can pull the newest files without switching pages. With Today mode off - the default - the page reads "NOT ACTIVATED", every section is dimmed, and the shortcut is inert along with them. The action is still one click away where it actually lives.

The measurements in the Detail above are all correct; the CONCLUSION drawn from them was not. What the dimming expresses is the state of the PAGE, not the state of that one button, and a shortcut into a mode you have not activated is correctly unavailable. "Enabled server-side but inert in CSS" is the normal shape of that, not evidence of a defect.

Reverted to the original single dimming rule and verified in the running app: pointer-events none, section opacity 0.45, identical to the two sections beside it. tests/test_today_quick_sync_clickable.py now guards the INTENDED behaviour - it fails if the Quick Sync section is ever removed from the dimming list again - and carries the reasoning so the next reader does not have to rediscover it.  
> Not observed in the latest run.

---

### ~~Canvas Pages ignore the 'isolate secondary content' setting; every other entity type honours it~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:7e2221df01e0 -->

**Status**: fixed
**Severity**: medium
**Category**: config
**Oracles**: O2,O3
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 3
**Scenario**: m051_c43660 · 43660

**Detail**:

Both Page call sites pass isolate=False literally, so with isolation ON in flat mode every Page lands at the course root - the one folder the setting exists to keep clean - while assignments, quizzes and discussions from the same run go to their category folders. _ENTITY_ROUTING already defines 'Pages' as the destination, so the routing supports it; only the two call sites never ask for it. Reported, not fixed: lanes were still running.

**Notes**: Fixed 2026-07-29, flat mode only (decided with the user; modules mode deliberately unchanged - a module Page belongs with its module, and that path carries legacy_sync_id back-compat machinery precisely because page keying moved once before). In FLAT mode there is no module folder, so 'module placement' degenerates to the course root and the isolate setting is the only instruction left. TWO halves had to move together: the writer (_download_flat_async -> isolate_pages) and the analyzer's expectation (_get_files_from_modules emits 'Pages/<name>.html', because analyze_course only fills target_paths in modules mode and preferred_disk_name passes a name_locked negative-id name through verbatim). If they disagree nothing crashes - every page just reads as new on every sync for ever. VERIFIED IN THE REAL APP: flat+isolate download of course 43660 -> 28 module scans, 35 pages, all 35 in Pages/, no Processing Error; then TWO sync runs, both 'Sync done - everything up to date, Checked 152 files'. Guarded by tests/test_page_isolation_flat_mode.py.  
> Not observed in the latest run.

---

### ~~Files extracted from archives are never converted (root cause: explicit_files excludes extraction output)~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:815c4edf0cb8 -->

**Status**: invalid
**Severity**: medium
**Category**: conversion
**Oracles**: —
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-27 (20260727_165705_bootstrap)
**Occurrences**: 1

**Detail**:

app.py:1778 passes explicit_files=success_paths - only paths the DOWNLOADER wrote - into invoke_post_processing, and converters/post_processing._glob_files filters every converter with 'f.resolve() in explicit_set'. run_archive_extraction runs FIRST (post_processing.py:820) and creates new files on disk, but those paths are never added to the explicit set, so every converter after it skips them.

Measured with all 8 converters on: 7 .pptx and 11,872 code/data files inside extracted archives were left unconverted, while the same types at module level converted normally (97 PDFs produced). The user enabled both 'Unpack Archives' and 'Code & Data -> .txt'; only the first reached that content.

Not data loss - files are present and usable - but it defeats the AI-optimisation feature for any course shipping material in a zip, which is common for code-heavy courses. Fix: append run_archive_extraction's output paths to the explicit set (or drop the explicit filter for converters that run after extraction).

**Notes**: Fixed 2026-07-27: `run_archive_extraction` now returns its extraction roots and `_glob_files` accepts anything under them, so unpacked files get the same treatment as any other teacher-uploaded file. Guarded by `tests/test_archive_conversion_scope.py`.  
> Not observed in the latest run. || REVERSED 2026-07-29, deliberately - this is now WORKING AS DESIGNED and must not be re-filed. A zip is unpacked and its contents are then left exactly as they are; nothing inside an archive is converted, in either flow. The original finding was right about the symptom and wrong about the cure. Measured on one real lecture zip from course 45899 (a JavaScript project with node_modules): 21,824 files extracted, 11,818 a converter would rewrite, 9,730 of those on paths past Windows' 260-char limit - because member names come verbatim from the zip and converting one makes it LONGER (x.d.ts -> x.d_ts.txt). The Office half could never have worked at any depth: PowerPoint COM rejects a long path AND rejects the long-path prefix (both measured directly). Beyond the arithmetic: an archive is an opaque payload the teacher uploaded, and a source-consuming converter DELETES the original, so a student's .js inside their own project would stop being a .js. The Card 3 toggle now says so in its tooltip. Guarded by tests/test_archive_conversion_scope.py, which asserts the reversed rule and explains why.  
> Not observed in the latest run.

---

### ~~Sync mode had the same archive-conversion gap as download, via a different mechanism~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:689a00875c36 -->

**Status**: invalid
**Severity**: medium
**Category**: conversion
**Oracles**: O1,O3
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-28 (20260727_165705_bootstrap)
**Occurrences**: 4
**Scenario**: parity_audit

**Detail**:

The download fix alone was not enough. sync/execution.py does NOT call run_all_conversions - it drives each converter itself and scopes them with get_synced_file_paths(), which returns only the exact relative paths THIS run downloaded (_synced_actual_rels). Files unpacked from an archive were never downloaded, so they were invisible to every sync converter too.

Fixed by routing both flows through one shared helper (converters.post_processing.iter_extracted_files) and having run_archive_extraction return its extraction roots to both callers. Guarded by tests/test_archive_conversion_scope.py, which now also asserts the two flows keep the SAME converter ordering and that neither reverts to a downloaded-files-only scope.

**Notes**: > Not observed in the latest run. || REVERSED 2026-07-29, deliberately - this is now WORKING AS DESIGNED and must not be re-filed. A zip is unpacked and its contents are then left exactly as they are; nothing inside an archive is converted, in either flow. The original finding was right about the symptom and wrong about the cure. Measured on one real lecture zip from course 45899 (a JavaScript project with node_modules): 21,824 files extracted, 11,818 a converter would rewrite, 9,730 of those on paths past Windows' 260-char limit - because member names come verbatim from the zip and converting one makes it LONGER (x.d.ts -> x.d_ts.txt). The Office half could never have worked at any depth: PowerPoint COM rejects a long path AND rejects the long-path prefix (both measured directly). Beyond the arithmetic: an archive is an opaque payload the teacher uploaded, and a source-consuming converter DELETES the original, so a student's .js inside their own project would stop being a .js. The Card 3 toggle now says so in its tooltip. Guarded by tests/test_archive_conversion_scope.py, which asserts the reversed rule and explains why.  
> Not observed in the latest run.

---

### ~~convert_code did not reach 54 file(s) unpacked from archives~~~~~~~~~~~~~~~~~~~~
<!-- fp:5a22b016415d -->

**Status**: invalid
**Severity**: medium
**Category**: conversion
**Oracles**: O1,O3
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 11
**Scenario**: m040 · m040

**Detail**:

convert_zip extracted these, but post-processing filters every converter through explicit_files - the list of paths the DOWNLOADER wrote - and extraction output is never added to it. So enabling both toggles applies only the first to archive contents.

**Notes**: Fixed 2026-07-27: `run_archive_extraction` now returns its extraction roots and `_glob_files` accepts anything under them, so unpacked files get the same treatment as any other teacher-uploaded file. Guarded by `tests/test_archive_conversion_scope.py`.  
> Not observed in the latest run. || REVERSED 2026-07-29, deliberately - this is now WORKING AS DESIGNED and must not be re-filed. A zip is unpacked and its contents are then left exactly as they are; nothing inside an archive is converted, in either flow. The original finding was right about the symptom and wrong about the cure. Measured on one real lecture zip from course 45899 (a JavaScript project with node_modules): 21,824 files extracted, 11,818 a converter would rewrite, 9,730 of those on paths past Windows' 260-char limit - because member names come verbatim from the zip and converting one makes it LONGER (x.d.ts -> x.d_ts.txt). The Office half could never have worked at any depth: PowerPoint COM rejects a long path AND rejects the long-path prefix (both measured directly). Beyond the arithmetic: an archive is an opaque payload the teacher uploaded, and a source-consuming converter DELETES the original, so a student's .js inside their own project would stop being a .js. The Card 3 toggle now says so in its tooltip. Guarded by tests/test_archive_conversion_scope.py, which asserts the reversed rule and explains why.  
> Not observed in the latest run.

---

### ~~convert_excel enabled but 1 source file(s) survived conversion~~~~~~~~~~~~~~~~~~~~
<!-- fp:449c42444584 -->

**Status**: invalid
**Severity**: medium
**Category**: conversion
**Oracles**: O1,O3
**First seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 2
**Scenario**: m028_c43665 · m028_c43665

**Detail**:

This converter is documented to replace its source. A surviving source at module level means the conversion ran and failed for that file - check whether the failure was reported to the user or only swallowed.

**Notes**: AUDIT-ENVIRONMENTAL, not a product defect (2026-08-08). Caused by the harness running THREE lanes on a 13.9 GB machine (2.6-3.0 GB free); CO_E_SERVER_EXEC_FAILURE and headless Excel hangs are classic low-resource symptoms. Controlled comparison: m014 re-ran the SAME course 43665 over the SAME 50 workbooks ~3h later with 5+ GB free and logged ZERO timeouts. The app handled it correctly - detected each hang, force-killed that specific PID (a different pid each time), retried, recovered 3 of 4, kept the original of the one that failed twice (pdf_looks_real refusing to delete a source without a proven PDF), and reported '1 file could not be converted' with cause and remedy; O1, O3 and the log all agree at 1. Do not re-chase. This verdict does NOT cover the separate leaked-EXCEL.EXE entry, which stays open.  
>  
> Not observed in the latest run.

---

### ~~convert_pptx did not reach 7 file(s) unpacked from archives~~~~~~~~~~~~~~~~~~~~
<!-- fp:24e9563de29e -->

**Status**: invalid
**Severity**: medium
**Category**: conversion
**Oracles**: O1,O3
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-08-08 (20260808_170617_minimal-dl-sync-2026-08)
**Occurrences**: 5
**Scenario**: m032_c45899 · m032_c45899

**Detail**:

convert_zip extracted these, but post-processing filters every converter through explicit_files - the list of paths the DOWNLOADER wrote - and extraction output is never added to it. So enabling both toggles applies only the first to archive contents.

**Notes**: Fixed 2026-07-27: `run_archive_extraction` now returns its extraction roots and `_glob_files` accepts anything under them, so unpacked files get the same treatment as any other teacher-uploaded file. Guarded by `tests/test_archive_conversion_scope.py`.  
> Not observed in the latest run. || REVERSED 2026-07-29, deliberately - this is now WORKING AS DESIGNED and must not be re-filed. A zip is unpacked and its contents are then left exactly as they are; nothing inside an archive is converted, in either flow. The original finding was right about the symptom and wrong about the cure. Measured on one real lecture zip from course 45899 (a JavaScript project with node_modules): 21,824 files extracted, 11,818 a converter would rewrite, 9,730 of those on paths past Windows' 260-char limit - because member names come verbatim from the zip and converting one makes it LONGER (x.d.ts -> x.d_ts.txt). The Office half could never have worked at any depth: PowerPoint COM rejects a long path AND rejects the long-path prefix (both measured directly). Beyond the arithmetic: an archive is an opaque payload the teacher uploaded, and a source-consuming converter DELETES the original, so a student's .js inside their own project would stop being a .js. The Card 3 toggle now says so in its tooltip. Guarded by tests/test_archive_conversion_scope.py, which asserts the reversed rule and explains why.  
> Not observed in the latest run.

---

### ~~Cancelling mid-transcription leaves .txt.part/.srt.part in the course folder for ever~~~~~~~~~~~~~~
<!-- fp:02cdd440035e -->

**Status**: fixed
**Severity**: medium
**Category**: panopto
**Oracles**: O2,O3
**First seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Last seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Occurrences**: 1
**Scenario**: pan_cpu_downgrade · 43660

**Detail**:

REPRODUCED. Phase 4's requirement is 'Cancel mid-transcription -> no orphaned worker process, no .part files'. Orphaned workers: PASS (verified twice). .part files: FAIL when the cancel lands while a worker is actively WRITING. Evidence (O3): 'Video med respons pa feedback...srt.part' (16536 B) and '.txt.part' (8416 B) remain on disk. Both are UNLOCKED (append-open succeeds), so they were removable. The recording's .mp3 (12851541 B) sits at the same base path, so _clean_part_files would have derived the correct base. O2: the log shows 'Transcribing [3/30] (device=cpu)' worker pid=31704 at 23:04:41 and the cancel at 23:07:07.633 - i.e. 2.5 min into that file - and contains NO .part cleanup line, success or failure. WHY IT MATTERS: panopto/runner.py's own comment states the engine deliberately ignores .part artifacts everywhere (never healed onto a manifest row, never auto-discovered, never counted as study material), so 'nothing would ever remove or even mention them again' - the leftovers are permanent clutter in the student's course folder. Note the first cancel (GPU run, between recordings) left ZERO .part files, so the trigger is specifically cancelling mid-write. CANDIDATE MECHANISM (not proven): core.cancellation logged 'cancel event set' at 23:07:07.633 and 'cancel event cleared' at 23:07:07.753 - app.py:909-910 resets the flag on any rerun where download_status has left _active_dl_statuses. That 120ms window is SHORTER than the 0.3s is_cancelled() poll in panopto/transcribe.py:435, so the graceful cancel path at transcribe.py:448 - which is what calls _clean_part_files - can miss the flag entirely, while the workers are killed by another route. NOT FIXED: audit ground rule 2 (report, never fix), and a product change mid-run would invalidate the 43-row sync matrix that was executing.

**Notes**: FIXED 2026-08-09, after the matrix had completed and the audit was closed. The
candidate mechanism above was WRONG and the real one is worse. It is not a race
on the cancel flag: a UI cancel makes Streamlit STOP the script run, which it
does by raising `RerunException`/`StopException` from the next `st.*` call -
inside the `progress()` callback, i.e. inside the transcription loop. Both are
`BaseException`, so nothing caught them and they propagated straight past the
sweep, which was ordinary statements after the loop. The absence of every
post-loop log line is the proof: the log ENDS at the cancellation.

Two fixes, both in the product:
  1. `panopto/runner.py` - the sweep is now in a `finally`, which is what its own
     comment ("covers every route out of the phase") always meant.
  2. `panopto/transcribe.py` - `_clean_part_files` now deletes through
     `make_long_path`. Every WRITE in that module already did; the delete did
     not, and on a stock Windows install (LongPathsEnabled=0) a >260-char path
     raises FileNotFoundError, which the retry loop reads as "already gone" - no
     removal, no retry, no log. 259 paths in this course exceed 255 chars and the
     two abandoned sidecars were 341. Latent on this dev box only because it has
     LongPathsEnabled=1.

VERIFIED IN THE REAL APP by reproducing the exact condition: a run was driven to
the mid-write state (2 .part files present on disk, worker on [15/28]) and then
cancelled from the UI. Result: 0 .part files, no stray workers. `check
invariants` on the same folder went from 2 HIGH to 1 (the remaining one is the
known Compiled_External_Links.txt checker gap, filed separately).

`tests/test_transcribe_partial_cleanup.py`: 5 of 6 mutations caught, one per
original defect. The three pre-existing structural tests there had passed against
BOTH defects - they anchored on `_clean_part_files(` appearing within 1800
characters of `progress("transcribe_done")` - and are now resolved through the
AST, asserting the call sits inside a `Try.finalbody`.  
> Not observed in the latest run.

---

### ~~2 manifest row(s) record the wrong size~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:72054c302758 -->

**Status**: invalid
**Severity**: medium
**Category**: persistence
**Oracles**: O4,O3
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 3
**Scenario**: p2r_defaults · Programmering og udvikling af små systemer samt databaser (LA E25 BINTO1064U)

**Detail**:

original_size decides whether the next Canvas change is treated as a real update or vetoed as a metadata touch.

**Notes**: AUDIT DEFECT, fixed. Same cause as the md5 entry above and fixed by the same declaration - an edited-locally file left unchecked legitimately differs from its recorded size.  
> Not observed in the latest run.

---

### ~~36 file(s) differ from their recorded md5~~~~~~~~~~~~~~~~
<!-- fp:8a7f0ead05f4 -->

**Status**: invalid
**Severity**: medium
**Category**: persistence
**Oracles**: O4,O3
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-08-09 (20260809_221807_post-fix-audit-2026-08-09-panopto-and-settings)
**Occurrences**: 5
**Scenario**: panopto_shortcut2 · Indføring i organisationers opbygning og funktion (LA E25 BINTO1060U)

**Detail**:

original_md5 is what classifies the next update as clean (overwrite) or modified (_NewVersion). A wrong baseline silently decides whether the user's edits survive.

**Notes**: AUDIT DEFECT, fixed. These are the `edited_update` fixtures: bytes appended so the file no longer matches its recorded baseline, then left UNCHECKED on the review screen by design. The file therefore MUST still differ - that divergence is the user's edit, and preserving it is the product's data-safety guarantee. The audit was reporting that guarantee working as a persistence defect. Covered by the same `expected_md5_drift` declaration.  
> Not observed in the latest run.

---

### ~~Canvas Content isolation requested but 35 entity file(s) sit at the folder root~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:c52480b4f905 -->

**Status**: fixed
**Severity**: medium
**Category**: placement
**Oracles**: O1,O3
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 3
**Scenario**: m051_c43660 · m051_c43660

**Notes**: Fixed 2026-07-29, flat mode only (decided with the user; modules mode deliberately unchanged - a module Page belongs with its module, and that path carries legacy_sync_id back-compat machinery precisely because page keying moved once before). In FLAT mode there is no module folder, so 'module placement' degenerates to the course root and the isolate setting is the only instruction left. TWO halves had to move together: the writer (_download_flat_async -> isolate_pages) and the analyzer's expectation (_get_files_from_modules emits 'Pages/<name>.html', because analyze_course only fills target_paths in modules mode and preferred_disk_name passes a name_locked negative-id name through verbatim). If they disagree nothing crashes - every page just reads as new on every sync for ever. VERIFIED IN THE REAL APP: flat+isolate download of course 43660 -> 28 module scans, 35 pages, all 35 in Pages/, no Processing Error; then TWO sync runs, both 'Sync done - everything up to date, Checked 152 files'. Guarded by tests/test_page_isolation_flat_mode.py.  
> Not observed in the latest run.

---

### ~~Analysis log omitted the Ignored category and printed URL-encoded filenames~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:4b3b4fd09677 -->

**Status**: fixed
**Severity**: medium
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-28 (20260727_165705_bootstrap)
**Occurrences**: 4
**Scenario**: p2_sync_45899

**Detail**:

CORRECTION of an earlier finding in this register that claimed only 2 of 7 categories were logged - that was an audit error (the grep used tag names UPDATE-MODIFIED/DELETED-CANVAS/DELETED-LOCAL; the real tags are UPDATE-EDIT/CANVAS-DEL/LOCAL-DEL). Five categories were already logged per file.

Two genuine defects remained:
1. CANVAS-DEL and LOCAL-DEL printed sync_info.canvas_filename raw, which is URL-encoded as it comes off the Canvas API. A Danish filename logged as 'Eksamen+2023E+Ordin%C3%A6r+Klasse+opgave.pdf' cannot be matched by eye against the 'Eksamen 2023E Ordinaer Klasse opgave.pdf' the review screen shows.
2. Ignored files were listed nowhere - the one category where 'missing on purpose' is the answer, and the log could not give it.

Fixed in sync/analysis.py: every category now writes one line per file through a shared _row() helper that decodes with unquote_plus and appends the local path wherever post-processing renamed the file (x.sql -> x_sql.txt). Up-to-date files are summarised as a count rather than listed, because on a healthy folder they are every file in the course.

**Notes**:   
> Not observed in the latest run.

---

### ~~Cancelling a transcription leaves .part sidecars in the course folder, invisibly and for ever~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:d433d4f13087 -->

**Status**: fixed
**Severity**: medium
**Category**: robustness
**Oracles**: O3,O2
**First seen**: 2026-07-28 (20260728_130002_phase4_panopto_full)
**Last seen**: 2026-07-28 (20260728_130002_phase4_panopto_full)
**Occurrences**: 1
**Scenario**: p4_cancel · 43660

**Detail**:

The write path is correctly atomic: the worker streams into <name>.txt.part / <name>.srt.part and only os.replace()s them onto the final names when a recording completes. The CLEANUP was broken in two independent ways, both found by cancelling a real run.

1. THE KILL IS ASYNCHRONOUS. transcribe_in_subprocess called proc.kill() and cleaned up immediately. On Windows the dying worker still holds its output handles, so os.remove raised PermissionError - an OSError, swallowed by a bare except. Every cancel left both files.

2. ONLY ONE EXIT FROM THE PHASE CLEANED UP AT ALL. The transcription loop leaves through 'except PanoptoCancelled' (which cleans, via the call above), through 'if is_cancelled() or engine_failed: break' at the loop head (which does not), and through an engine failure (which does not). The two cancel routes are distinguishable in the log - one writes 'Transcription cancelled by user', the other writes nothing - and only the logged one ever cleaned. Both routes were observed: two cancels of the same folder produced different logs and identical leftovers.

Why it is worse than two stray files: the engine deliberately IGNORES .part artifacts everywhere else - never healed onto a manifest row, never auto-discovered, never counted as study material, never post-processed. So a leftover is invisible to the app from then on, and nothing would ever remove or even mention it again.

FIXED, both halves:
  - the cancel path now waits for the worker to actually die before cleaning, and the remove retries briefly and LOGS a persistent failure instead of swallowing it;
  - the phase sweeps every target's sidecars on the way out, whatever ended it - which covers exit routes added later, the thing that went wrong here.

Verified by cancelling three real runs: before, both .part files remained; after, none, with the worker process reaped and the app on a clean 'Sync Cancelled' screen. The no-orphaned-worker half of the runbook check passed throughout.

**Notes**: Fixed and verified by cancelling three real runs. Both halves were needed - the first fix (waiting for the kill) addressed only the route that logs, and a second cancel proved a silent route existed that never called the cleanup at all.  
> Not observed in the latest run.

---

### ~~Unexpected bridged_warning in debug log: Discussion dispatch failed for 'Spørgsmål til pensum i organisationskultur': Not Found~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:98608167bec2 -->

**Status**: fixed
**Severity**: medium
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 15
**Scenario**: m036 · m036

**Detail**:

Discussion dispatch failed for 'Spørgsmål til pensum i organisationskultur': Not Found

**Notes**: Same cause as the undeliverable-discussion entry, fixed 2026-07-28 by resolve_discussion_topic(). This is the generic 'unexpected log line' net catching the WARNING half of that event. product-stale evidence from a pre-fix run.  
> Not observed in the latest run.

---

### ~~Unexpected suspicious in debug log: ERROR [Discussion Dispatch Error] Indføring i organisationers opbygning og funktion (LA E2~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:257805fd303c -->

**Status**: fixed
**Severity**: medium
**Category**: robustness
**Oracles**: O2
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 15
**Scenario**: m036 · m036

**Detail**:

ERROR [Discussion Dispatch Error] Indføring i organisationers opbygning og funktion (LA E25 BINTO1060U) :: Spørgsmål til pensum i organisationskultur :: Not Found

**Notes**: Same cause as the undeliverable-discussion entry, fixed 2026-07-28. This is the generic net catching the ERROR half of the SAME log event - a known redundancy with the dedicated check, documented in RUNBOOK 'Known redundancy: one Canvas condition, three findings'. product-stale evidence from a pre-fix run.  
> Not observed in the latest run.

---

### ~~An online quiz reached through a module Assignment item is saved a second time, saying '(No content provided)'~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:92e8dcc3c9f9 -->

**Status**: fixed
**Severity**: medium
**Category**: ui-truth
**Oracles**: O3,O2
**First seen**: 2026-07-28 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 4
**Scenario**: m001 · 43660

**Detail**:

Canvas exposes an online_quiz as BOTH a quiz (107362) and its shadow assignment (32347). With dl_assignments and dl_quizzes both on, the app saves it twice, and the two copies disagree.

The Quizzes/ copy is right: canvas_logic.py:5860-5889 calls get_questions(), Canvas answers 'user not authorised to perform that action' for a student, and the file says 'Could not load quiz questions.'

The Assignments/ copy goes through canvas_logic.py:4621-4646, which never fetches questions at all - it saves the assignment description, which for an online_quiz is empty by nature because the content IS the questions. _save_secondary_entity then renders the generic empty-body placeholder, so the file reads '(No content provided)'.

That is the wrong statement. The quiz has content; Canvas will not serve it to a student. A user reading it concludes the teacher left the quiz empty. The app knows the true reason - it logged it - and the sibling file two folders away says it correctly.

Measured on course 43660: 10 quizzes saved via the quiz path all explain themselves properly; the one quiz that also sits in a module as an Assignment item is the only one that produced a second, misleading file.

**Notes**: Fixed 2026-07-28 and verified against the live API. TWO defects, one root: questions were fetched in exactly ONE of the five places a quiz can be saved, and that one caught the wrong exception - `Forbidden` is a SIBLING of `Unauthorized` under `CanvasException`, not a subclass, so the informative handler was dead code for every student. Now one `quiz_body_html` helper at all three quiz sites and `assignment_body_html` at all three assignment sites, with copy that states the truth. NOTE: the first version of the fix was wrong and only the live API caught it - `get_questions()` returns a lazy PaginatedList, so guarding the CALL catches nothing; the iteration must be inside the try. 21 unit tests passed against an eagerly-raising double. Guarded by tests/test_quiz_body.py, whose fixtures now raise on iteration.  
> Not observed in the latest run.

---

### ~~Course Finished reports 2 error(s) but this course's log records 0~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:eee718626a2e -->

**Status**: fixed
**Severity**: medium
**Category**: ui-truth
**Oracles**: O2,O2
**First seen**: 2026-07-29 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 87
**Scenario**: m068_c45899 · m068_c45899

**Detail**:

The engine's error counter is not reset per course, so a later course in a batch reports its predecessors' failures as its own.

**Notes**: DUPLICATE of "The per-course 'Course Finished' line reports the whole batch's error count", which this same matrix produced and which was fixed on 2026-07-28 (app.py:1450 filters download_errors_list by course_name; tests/test_per_course_error_count.py). This entry is the MECHANICAL detection of it, added by checker defect 24 on 2026-07-29 - so it necessarily fires on the whole matrix, whose lanes started 18:34 on 2026-07-28 with --server.fileWatcherType=none and therefore ran pre-fix code for all 73 rows. product-stale evidence from a pre-fix run; a fresh run is the only thing that can clear it.  
> Not observed in the latest run.

---

### ~~Recordings skipped by the size cap are unexplained, while files skipped by the same cap are explained on the same screen~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:6b8c9476a66a -->

**Status**: fixed
**Severity**: medium
**Category**: ui-truth
**Oracles**: O1,O2
**First seen**: 2026-07-28 (20260728_125433_phase4_panopto)
**Last seen**: 2026-07-28 (20260728_125433_phase4_panopto)
**Occurrences**: 1
**Scenario**: p4_size_gate · 43660

**Detail**:

With the skip-large-files setting at 5 MB, a download of 43660 produced:

  FILES:      '61 files skipped because they exceeded the 5 MB limit. See 61 skipped files'
  RECORDINGS: 'Panopto Recordings - 36 found across 1 course / 0 DOWNLOADED'

All 36 recordings were skipped by the SAME size gate (estimated 6-24 MB each). The debug log says so per recording, with the reason and the estimate: 'Panopto size gate: skipping <title> (~12 MB est > 5 MB limit)'. The completion card says only '0 DOWNLOADED'.

The app already counts this: panopto/runner.py maintains summary['size_skipped'] and increments it at line 752. shared/components.py:render_panopto_summary never reads that key.

The card deliberately does NOT show a generic 'Skipped' stat, and that decision is sound and documented - a big '24 skipped' reads as '24 missing from my course' when those recordings are simply already present. But size_skipped is the opposite case: those recordings are genuinely absent, for a reason the USER chose and the app knows exactly. It is the same class of information the file half of the screen states plainly one line above.

Effect: a user who has ever set a size limit sees '36 found / 0 downloaded' and no reason, on a screen that explains the identical situation for files. The likeliest reading is that Panopto is broken.

Suggested shape, matching the file line already there: 'N recordings skipped because they exceeded the 5 MB limit.'

Not a delivery defect - nothing was lost and the gate did what it was asked. Recorded as ui-truth.

**Notes**: FIXED - but the original finding was HALF WRONG and the correction matters.

The merge it asked for already existed: `app.py`'s Panopto progress handler appends every size-skipped recording to `size_skipped_files`, so the '61 files skipped because they exceeded the 5 MB limit' line ALREADY included them. Verified by counting the run's log: 25 over-limit Canvas files + 36 over-limit recordings = the 61 reported.

What was actually wrong was only the other half - the Panopto card rendering '36 found across 1 course / 0 DOWNLOADED' directly beside that line. Two panels describing one event, one of them phrased as a success metric reading zero.

`render_panopto_summary` had a '_did_work' guard for SYNC mode only; download mode tested `found <= 0`, which is true of neither. The guard is now shared. A failure still renders - suppressing a zero must never suppress an error.  
> Not observed in the latest run.

---

### ~~The per-course 'Course Finished' line reports the whole batch's error count, not the course's~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:eb27c313381a -->

**Status**: fixed
**Severity**: medium
**Category**: ui-truth
**Oracles**: O2
**First seen**: 2026-07-28 (20260728_145153_matrix)
**Last seen**: 2026-07-29 (20260728_145153_matrix)
**Occurrences**: 4
**Scenario**: m025 · 45899

**Detail**:

app.py computed the per-course error count as len(download_errors_list). That list is created once before the course loop and never reset - the completion screen reads the very same list under the name global_errors - so every course after the first was charged with all the earlier ones' errors.

The download count on the SAME LINE is per-course (download_file_details[course.name]), so the two halves of one line disagreed about what they were counting.

Measured on the three-course row m025: the third course contributed ZERO errors and its line said 'Errors: 5'. Across the run, 124 course-lines reported 312 errors where only 222 exist.

It is a debug-log line rather than a UI one, but it is the line anybody judging a course's health reads - and it sent this audit hunting 90 errors that do not exist across 40 rows before the arithmetic gave it away.

FIXED: count only entries whose DownloadError.course_name matches the course. Guarded by tests/test_per_course_error_count.py, which also asserts the download half of the line stays per-course - fixing one and not the other just moves the disagreement.

**Notes**: Fixed 2026-07-28. Counts only entries whose DownloadError.course_name matches the course. tests/test_per_course_error_count.py also asserts the DOWNLOAD half of the same line stays per-course - fixing one and not the other just moves the disagreement.  
> Not observed in the latest run.

---

### ~~A read-only destination leaves the previous copy on disk, untracked and unexplained~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:7eaa8671abd1 -->

**Status**: fixed
**Severity**: low
**Category**: delivery
**Oracles**: O3,O4
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 3
**Scenario**: p2r_defaults · 45899

**Detail**:

When a clean update's destination cannot be written (the classic 'the file is open in Word' case), the engine correctly writes X_NewVersion.pdf instead of failing the run - no data is lost and one locked file does not cost the whole sync. It then REPOINTS the manifest row to the _NewVersion sibling, which leaves the original X.pdf on disk with no manifest row.

Verified on disk after the sync: both files present, the original still read-only, the row on the sibling. A SECOND analysis was run to test whether the orphan would be re-offered as New or re-adopted by heal Tier 1 (its name is an exact match for the Canvas filename) - it is neither. The state is stable, so this is not a loop and not a correctness bug.

What remains is a small user-facing cost: the folder now holds two copies, the one with the ORIGINAL name is the stale one, and nothing in the app says so. Raised as low rather than as a defect because the alternative - overwriting a file the user has open - is far worse, and because the app is silent rather than wrong. Worth a decision: leave as is, or mention it on the completion screen alongside the existing 'files were skipped' notice.

**Notes**: FIXED 2026-07-28, and the original finding was partly wrong - it said "nothing in the app says so". There IS a "Modified Files Protected" card listing every _NewVersion file with its folder; it just sits inside the collapsed "Files added" expander, so a user who never expands it sees nothing.

Two changes shipped:

1. A short INFO notice on the sync completion screen, directly below the "files were skipped because you ignored them" one: *"N files were saved as a separate copy so we didn't overwrite your version"*, with the _NewVersion naming, an example filename, and what to do (compare, keep one, delete the other). Verified rendering in the real app.

2. The card's subtitle said *"Saved alongside the files you had edited"*, which is FALSE for the locked-file route - the category is assigned purely from the "_NewVersion" filename, so a file that was merely open in another program landed there too and the user was told they had edited something they never touched. Now *"Saved next to your copy, which was left untouched"*, true of both routes. The category legend on the sync page was corrected the same way. Verified in the real app via the sync-history panel, which shares the renderer.

Guarded by tests/test_newversion_notice.py, including a check that every _NewVersion construction site in the sync engine is instrumented, so a third route added later cannot silently under-report the count.  
> Not observed in the latest run.

---

### ~~A locked DOWNLOAD target falls back gracefully; a locked CONVERSION target fails hard~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:fa5b7101bfd4 -->

**Status**: fixed
**Severity**: low
**Category**: robustness
**Oracles**: O2,O3
**First seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Last seen**: 2026-07-28 (20260728_013336_phase2_newversion)
**Occurrences**: 2
**Scenario**: p2nv_selected · 45899

**Detail**:

Two write paths, two different behaviours for the same user situation (a file open in another program):

DOWNLOAD: os.replace onto a locked target raises PermissionError, and the engine delivers the bytes alongside as X_NewVersion.ext. The run continues, nothing is lost, and the completion screen now explains it.

CONVERSION: the converter writing its output onto a locked target (e.g. code.js -> code_js.txt where the .txt is open) raises 'Permission denied' and the file is simply counted as a post-processing failure. No _NewVersion fallback exists on this path.

Not silent, and not destructive: the failure appears in the post-processing warning on the completion screen and in download_errors.txt, and the downloaded source survives, so the user can close the file and re-sync. Rated low for that reason. Recorded because the asymmetry is invisible from the code - the download fallback reads like a general policy and it is not - and because the same locked file produces a tidy outcome through one path and an error through the other.

Found while building the readonly_target fixture: it had been locking a CONVERSION OUTPUT rather than a download target, so it was silently exercising this path instead of the one it was written for. The fixture now picks only files whose local extension matches their Canvas filename.

**Notes**: Fixed with B then C. (B) One retry pass runs at the end of post-processing, in BOTH flows, over every conversion whose source is still on disk - which is the whole failure set, because every source-consuming converter deletes its source on success. That single signal is what let one pass cover all nine runners without touching any of them. (C) Whatever fails twice is reported by name, and when a locked file sharing the source's stem can be found the message names it: "'code_py.txt' is open in another program. Close it and sync again." Failure counts are reconciled so a recovered file is not still counted as failed and a twice-failed one is counted once. A crashing retry can never take down the run.  
> Not observed in the latest run.

---

### ~~Debug log records per-file rows for only 2 of the 7 sync categories~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:f695845da958 -->

**Status**: invalid
**Severity**: low
**Category**: robustness
**Oracles**: —
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-27 (20260727_165705_bootstrap)
**Occurrences**: 1

**Detail**:

sync/analysis.py:247,250 log a [NEW] and [UPDATE-CLEAN] line per file. The other five categories - locally-edited updates, deleted on Canvas, deleted locally, ignored, up to date - appear only as counts on the 'Analysis complete' line. Verified on a run reporting 2 deleted-on-Canvas and 2 ignored: zero per-file rows for either.

Consequence: a shared debug log cannot answer WHICH file the app put in those categories, so 'why did it not re-download X?' is undiagnosable after the fact, and any log-based verification is blind to five sevenths of the classification logic. Extending the existing one-line-per-file treatment to the remaining categories is a few lines and makes the log a complete record of the decision.

**Notes**: AUDIT ERROR, not a product defect. The grep used tag names that do not exist (UPDATE-MODIFIED/DELETED-CANVAS/DELETED-LOCAL); the real tags are UPDATE-EDIT/CANVAS-DEL/LOCAL-DEL, and five categories were already logged. Superseded by the 'omitted the Ignored category and printed URL-encoded filenames' entry, which is the accurate version and is fixed. ---  
> Not observed in the latest run.

---

### ~~Sync review: 'Updates Available — You've Edited These' rendered untinted while its five siblings matched their icons~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:70a043d21429 -->

**Status**: fixed
**Severity**: low
**Category**: ui-truth
**Oracles**: O1
**First seen**: 2026-07-27 (20260727_165705_bootstrap)
**Last seen**: 2026-07-28 (20260727_165705_bootstrap)
**Occurrences**: 3
**Scenario**: p2_sync_45899

**Detail**:

styles/sync_review.css colour-codes each category expander with a substring selector. div[class*="st-key-cat_update"] reads as though it covers cat_updmod_ and does NOT: the keys diverge at upd-M-od vs upd-A-te. So the edited-updates category rendered with an amber icon and an amber summary tile on top of an untinted card, breaking the one visual cue that distinguishes six stacked categories at a glance.

Nothing errors and nothing logs - a substring selector that stops matching is invisible in review, which is why it survived.

Fixed with its own rule using rgba(245,158,11) = theme.WARNING, which is the colour the legend card in ui/sync_review.py (_cc_edited) already assigns to this category, so the expander and the legend explaining it cannot drift. Verified live: all six categories now report the accent their icon uses. Guarded by tests/test_sync_review_category_colours.py, which also fails if a NEW category is rendered without a tint, and asserts no two category selectors can match each other's containers.

**Notes**: Fixed 2026-07-27. Own rule in styles/sync_review.css using theme.WARNING, verified live on all six categories. Guarded by tests/test_sync_review_category_colours.py. ---  
> Not observed in the latest run.

---

### ~~Today says 'You're all caught up' while a daily course is broken and its 15 arrivals are hidden~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
<!-- fp:aa56baa0771b -->

**Status**: fixed
**Severity**: low
**Category**: ui-truth
**Oracles**: O1,O2
**First seen**: 2026-07-28 (20260728_010431_phase2_real)
**Last seen**: 2026-07-28 (20260728_010431_phase2_real)
**Occurrences**: 2
**Scenario**: t3_missing_folder · 45899

**Detail**:

With a daily course whose folder has been renamed or moved, the Today page correctly: keeps the course listed, marks its chip amber (today_chip_missing_0), skips it rather than pausing the daily sync, and shows no per-course state for it. All of that matches the documented contract and is right.

The 'Today's files' panel then reads: 'No new files today. You're all caught up.'

That is a positive assertion, and in this state it is not quite true - 15 files DID arrive today for that course; they are simply in the folder the user moved, and the page cannot resolve it. The off-list footnote does not cover the case either, and correctly so: its wording is 'a course that isn't in your daily sync', and this course IS in it.

So the only signal is the amber chip. That is arguably enough - a user who sees amber investigates - which is why this is low and not a defect. Recorded because the Today page's stated principle is that it must SAY what it is hiding, and this is the one state where it hides something and says the opposite. A one-line variant of the empty state when any daily course is amber ('N course needs attention above') would close it without touching the rest.

Verified: folder renamed on disk, page reloaded, chip amber, no outage screen, no error text, Quick Sync still offered.

**Notes**: Fixed with option A - the empty state is now conditioned on the unreachable list rather than replaced wholesale. A broken daily course reads "No new files today / N course above needs attention, so it was skipped." The healthy case still says "You're all caught up." and the no-courses case is untouched. Verified live in all three states. The contract is unchanged: an unreachable course still gets no card and no file list of its own, and the daily sync still skips it rather than pausing.  
> Not observed in the latest run.

---
