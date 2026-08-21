"""
engine.applescript_bridge - Shared AppleScript execution utility for macOS.

Extracted from converters/excel.py, converters/word.py, converters/pdf.py
(Phase 3 remediation - F-08) to eliminate triple-duplicated code.

Provides a single, robust ``run_applescript()`` function that all Office
converters delegate to for macOS AppleScript-based file conversion.
"""

import logging
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Maps the human-readable app_name argument to the AppleScript application
# name and the AppleScript term for an open document in that app.
_APP_DOC_MAP = {
    "PowerPoint": ("Microsoft PowerPoint", "active presentation"),
    "Word":        ("Microsoft Word",       "active document"),
    "Excel":       ("Microsoft Excel",      "active workbook"),
}

# Sandbox container bundle identifiers for the Office apps. A sandboxed app
# always has unrestricted read/write access to its OWN container's Data dir,
# so staging conversion inputs/outputs there sidesteps the macOS "Grant File
# Access" powerbox prompt that otherwise fires for every file in ~/Downloads.
_CONTAINER_IDS = {
    "PowerPoint": "com.microsoft.Powerpoint",
    "Word":       "com.microsoft.Word",
    "Excel":      "com.microsoft.Excel",
}

# Unique sentinel baked into every staged-conversion path. It is what lets us
# later identify (and surgically purge) the Recent-files entries Office records
# for our temp files, without ever touching a real user document.
_CANVAS_TMP_MARKER = "CanvasDownloaderTmp"


def _office_container_tmp(app_name: str) -> Path | None:
    """Return a writable staging dir inside the Office app's sandbox container.

    Returns ``None`` (caller falls back to direct paths) when not on macOS, the
    app is unknown, or the container does not exist (app never launched / not
    installed). The directory is the app's own sandbox container, so both the
    Office app AND our (non-sandboxed) process can read/write it freely.
    """
    if sys.platform != 'darwin':
        return None
    cid = _CONTAINER_IDS.get(app_name)
    if not cid:
        return None
    base = Path.home() / "Library" / "Containers" / cid / "Data"
    if not base.is_dir():
        return None
    # Under Data/tmp so it can never be caught by iCloud Drive sync (which only
    # touches the container's Documents folder). The Office app has full
    # sandbox access to everything under its own Data dir.
    tmp = base / "tmp" / _CANVAS_TMP_MARKER
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp
    except Exception:
        return None


#: How long to wait for another PROCESS to finish its conversion before going
#: ahead anyway. Generous, because one conversion is seconds; bounded, because
#: a run must never hang on a lock - proceeding is what the app did before this
#: existed, so the timeout degrades to the old behaviour rather than to a stall.
_OFFICE_LOCK_TIMEOUT_S = 120.0


@contextmanager
def _office_app_lock(app_name: str):
    """Serialise Office automation ACROSS PROCESSES.

    macOS gives a user session exactly ONE Microsoft PowerPoint / Word / Excel.
    Two Canvas Downloader instances therefore drive the same application, and
    since a conversion is `open` -> `save active` -> `close`, one instance's
    `open` lands between the other's `open` and its `save`.

    MEASURED 2026-08-11, two conversion batches started at the same moment:

        batch A   8 files ->  0 converted, 8 failed
        batch B   8 files ->  0 converted, 8 failed
        errors    "Connection is invalid. (-609)",
                  "reported success but no output file was created"
        artefact  `B8 (1).pdf` - two conversions racing for one destination
        result    PowerPoint CRASHED into Microsoft Error Reporting

    That is the operator's original bug report, reproduced on demand, and it is
    the leading explanation for the 2026-08-11 matrix crash (two audit lanes =
    two instances). `start.py`'s single-instance guard normally prevents a
    second instance, but it **fails OPEN by design** in three ways (mutex
    creation failure, the CANVAS_DL_ALLOW_MULTI escape hatch, any exception on
    the flock path), so it cannot be the only defence for something that ends
    in a crashed Office app and a folder of half-converted lectures.

    The lock is held for ONE conversion, not a whole phase: `open`/`save`/
    `close` is the indivisible unit, and a phase-wide lock would block a second
    instance for the length of an entire course.

    `flock` is the right primitive precisely because the kernel releases it
    when the holder dies - a crashed instance cannot leave a stale lock that
    wedges every future run. Per APP, not global, so Word in one instance never
    waits on PowerPoint in another.

    Degrades to a no-op off macOS, without `fcntl`, or if the lock file cannot
    be made: this makes a bad case better and must never make the normal case
    fail.
    """
    if sys.platform != 'darwin':
        yield
        return
    try:
        import fcntl
        import tempfile
        # The per-user temp dir, NOT the config dir: two instances can be
        # pointed at different config dirs (the audit harness does exactly
        # that) while still sharing the one Office the user session has.
        path = Path(tempfile.gettempdir()) / f"canvas_dl_office_{app_name.lower()}.lock"
        # BINARY: this file is never read or written, only flocked - it exists
        # solely to own a descriptor. Opening it in text mode would raise the
        # encoding question (Rule 2) about bytes that never exist.
        fh = open(path, 'ab')
    except Exception as e:
        logger.debug(f"[AppleScript] Office lock unavailable ({e}); proceeding")
        yield
        return
    held = False
    try:
        deadline = time.time() + _OFFICE_LOCK_TIMEOUT_S
        waited = 0.0
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except OSError:
                if time.time() >= deadline:
                    logger.warning(
                        f"[AppleScript] another process has been driving "
                        f"{app_name} for {_OFFICE_LOCK_TIMEOUT_S:.0f}s; going "
                        f"ahead without the lock")
                    break
                time.sleep(0.25)
                waited += 0.25
        if held and waited:
            logger.debug(f"[AppleScript] waited {waited:.1f}s for {app_name}")
        yield
    finally:
        try:
            if held:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()
        except Exception:
            pass


@contextmanager
def _office_app_lock_unless(app_name: str, already_held: bool):
    """`_office_app_lock`, skipped when the CALLER already holds that app's lock.

    flock is per open file description, so a second acquire from the same
    process blocks against the first - it would not deadlock outright (the
    120s timeout releases it) but it would stall a thread whose entire purpose
    is not to block. The only caller passing True is the timeout-recovery
    sweep fired from inside `_run_applescript_locked`.

    The parameter is REQUIRED and has no default, so a new call site has to
    state which case it is rather than inherit the dangerous answer silently -
    the same discipline `_idle_quit_script.undescribable_is_ours` uses.
    """
    if already_held:
        yield
        return
    with _office_app_lock(app_name):
        yield


def _product_is_real(staged_dst: Path) -> bool:
    """Is the file Office just wrote worth promoting to the user's folder?

    The SAME gate the source-deleting converters already apply after the fact
    (`converters.verify`), asked one step earlier so a reject never reaches the
    destination at all. Asking it in both places is deliberate and not
    redundant: this one decides what the user's folder gains, the converter's
    decides whether the ORIGINAL may be deleted.

    Imported inside the function on purpose. This module is reachable from
    `shared.helpers` and `engine.notifications`, both of which it reaches back
    into, so a module-level app import turns all three into a cycle - and
    `tests/test_applescript_string_escaping.py` checks the import LEVEL, not
    merely its presence.

    Never raises: `converters.verify` reports an unreadable file as not-real,
    and if the import itself fails we answer True, which is the pre-existing
    behaviour - a cosmetic guard must not be able to swallow a good PDF.
    """
    try:
        from converters.verify import file_has_content, pdf_looks_real
    except Exception:
        return True
    if staged_dst.suffix.lower() == '.pdf':
        ok, why = pdf_looks_real(staged_dst)
    else:
        ok, why = file_has_content(staged_dst, what=f"{staged_dst.suffix} file")
    if not ok:
        logger.debug(f"[AppleScript] declining the produced {staged_dst.name}: {why}")
    return ok


def _direct_passthrough(src: Path, dst: Path, app_name: str):
    """The no-container path: Office writes straight to the real destination.

    **Records the fallback here, and here ONLY**, because there are TWO ways to
    reach it and the first version of this instrumented one of them - which is
    the "a fix that lands on two of three sites" mistake this repo keeps
    finding. The container can be missing (`_office_container_tmp` answers
    None), or present-but-unusable, where the `mkdir`/`copy2` INTO it raises -
    and a denied app-data grant takes the SECOND path, because the directory
    still exists and lists. Verified live: the fix landed on the first branch
    and the packaged app went on reporting a bare -1712.

    Nothing can be gated *before* the write here, so the most this can do is
    refuse to LEAVE a reject behind. The two cases are deliberately different:

    * the destination did NOT exist before - a reject is pure litter, tracked
      by nothing and re-offered as a new file on every future sync, so it is
      removed;
    * the destination DID exist - Office has already overwritten whatever was
      there and we cannot get it back. Deleting the reject would add a MISSING
      file to a damaged one, and a manifest row may point at that path, so it
      is kept and reported instead.

    Reachable on macOS whenever the Office container is unavailable. It is also
    the shape non-macOS takes, though no converter reaches it there - Windows
    goes through `office_safe_path` and COM.
    """
    if sys.platform == 'darwin':
        _office_unstaged.add(app_name)
    existed = dst.exists()
    yield src, dst
    try:
        if dst.exists() and not _product_is_real(dst):
            if existed:
                logger.warning(
                    f"[AppleScript] {app_name} overwrote {dst.name} with an "
                    f"unusable file while converting {src.name}; it is kept "
                    f"because deleting it would break anything pointing at it")
            else:
                dst.unlink()
                logger.warning(
                    f"[AppleScript] {app_name} left an unusable {dst.suffix} for "
                    f"{src.name}; removed it rather than leaving an untracked file")
    except OSError as e:
        logger.debug(f"[AppleScript] could not tidy up {dst}: {e}")


@contextmanager
def office_container_stage(src: Path, dst: Path, app_name: str):
    """macOS: stage *src*/*dst* inside the Office app's sandbox container.

    Yields ``(staged_src, staged_dst)``. The Office app opens *staged_src* and
    writes *staged_dst* entirely inside its own container, so macOS never shows
    the per-folder "Grant File Access" / "Additional permissions required"
    powerbox prompt. On a clean exit the produced *staged_dst* is moved back to
    the real *dst*; the staging dir is always cleaned up.

    Degrades to the original ``(src, dst)`` on any platform other than macOS,
    when the container is unavailable, or if the staging copy fails.

    **That degrade is NOT harmless on macOS 15+, and this docstring used to
    say it was** ("never worse than before, only ever better"). Measured
    2026-08-20 in the packaged app with the *"would like to access data from
    other apps"* prompt DENIED: the container reads as unavailable, the
    fallback asks Word to open a file at its real path, macOS raises the
    per-folder file-access prompt **that staging exists to avoid**, and the
    blocked AppleEvent times out after ~2 minutes - twice, because a timeout
    is a per-file category and gets retried. One `.doc` cost ~4 minutes and
    reported only ``AppleEvent timed out (-1712)`` then "Conversion failed
    twice", naming neither the cause nor a remedy. The trap note further
    down this function already described that exact mechanism - as a hazard
    for anyone re-MEASURING staging, without noticing it is a live user path.

    So the fallback still runs (a user who has granted per-folder access
    converts fine), but it is RECORDED in ``_office_unstaged`` so a timeout
    can be attributed to the prompt rather than blamed on the document.
    """
    src = Path(src)
    dst = Path(dst)

    stage_root = _office_container_tmp(app_name)
    if stage_root is None:
        # The fallback records itself inside _direct_passthrough - BOTH routes
        # to it must count, and this one is not the route a denial takes.
        yield from _direct_passthrough(src, dst, app_name)
        return

    work = stage_root / ("cd_" + uuid.uuid4().hex[:10])
    # Staged under a SHORT name, not src.name - the real name is only needed at
    # the final destination, which this function moves the product to itself.
    #
    # Staging preserved src.name until 2026-08-10, which quietly made long
    # filenames UNCONVERTIBLE on macOS. Measured against the real Word converter
    # with a fresh Word and a passing positive control per case:
    #
    #     name 104 bytes -> CONVERTED
    #     name 168 bytes -> FAILED   active document doesn't understand the
    #                                "save as" message (-1708)
    #     172 / 176 / 180 / 184 / 204 / 224 / 244 / 254 -> all FAILED
    #
    # The limit is on the TOTAL path Word is handed, not on the filename, and the
    # discriminating pair is a SHORT name at two different staged depths - keeping
    # the name fixed at 9 bytes and deepening the staged directory inside the
    # container:
    #
    #     name 9B,  staged ~220  -> CONVERTED
    #     name 11B, staged ~281  -> FAILED
    #
    # Same short name, opposite outcomes, so a component limit is ruled out.
    # Every measurement lines up on one rule - staged total under ~255 works,
    # above it fails - including the name sweep (staged 195 converts, staged 259
    # does not) and the 763-byte real path with a 9-byte name, which converts
    # because staging had already replaced the user's directory with a ~100-char
    # staged one. macOS allows 1024 for a path and 255 per component, so this
    # limit is Word's, and 255 is its classic one.
    #
    # So the app was spending 91 characters of a 255 budget on the container
    # prefix and then preserving the filename, leaving an effective name budget of
    # about 164 bytes. Filenames that long are ordinary in Canvas: a lecture title
    # carrying the course code and week runs well past 100 characters. The failure
    # was silent, per file, with only a generic conversion error.
    #
    # A TRAP for anyone re-measuring this: the unstaged path is NOT a usable
    # control. With no container macOS demands the per-folder App Data grant that
    # staging exists to avoid, so even a short-named control fails there, and an
    # earlier pass drew the wrong conclusion from exactly that comparison. Vary
    # the depth INSIDE the container instead.
    #
    # Verified after the change: a 240-byte name CONVERTS and the PDF lands under
    # its real long name.
    #
    # The suffixes are kept because they are load-bearing - Office picks its
    # importer from the source extension and its exporter from the destination's.
    # Nothing reads the staged basename: the three callers pass these paths
    # straight to osascript, run_applescript's success test is
    # `staged_dst.exists()`, and the leftover-document sweeper matches on the
    # CanvasDownloaderTmp marker in the DIRECTORY (_marker_in_value), not on the
    # file name. Each conversion gets its own uuid work dir, so the fixed
    # basenames cannot collide between concurrent conversions.
    # The basename carries the uuid's first 6 hex too, and that is LOAD-BEARING
    # rather than decorative. `our_document_test` identifies our document by
    # NAME, and a constant `src.<ext>` is the same name in every conversion - so
    # two conversions running at once (two app instances against the ONE
    # PowerPoint macOS gives a user session) both answer "yes, that's mine" for
    # each other's document, and the guard silently protects nothing.
    #
    # Measured 2026-08-11 by running two conversion batches concurrently:
    # 8 + 8 files, 0 converted, `Connection is invalid. (-609)`, a stray
    # `B8 (1).pdf` where two conversions raced for one destination, and
    # PowerPoint crashed into Microsoft Error Reporting - the operator's
    # original report, reproduced on demand. `guard_trips` was 0 throughout.
    #
    # 15 characters total, so the ~255-byte staged-path budget below is
    # untouched (and `tests/test_office_staging_short_names.py` still asserts
    # <= 16).
    _tok = work.name[-6:]
    staged_src = work / (f"src_{_tok}" + src.suffix)
    staged_dst = work / (f"out_{_tok}" + dst.suffix)
    try:
        work.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, staged_src)
    except Exception as e:
        # WARNING, not debug: the app's debug log captures INFO and above
        # (measured - a real run with debug mode ON contained 0 DEBUG lines),
        # so at debug level the ONE line explaining why conversions are about
        # to fail could never be read by anyone, including this audit.
        logger.warning(f"[AppleScript] container staging unavailable ({e}); "
                       f"using direct path - Office will be asked to open a file "
                       f"outside its container, which macOS may block")
        shutil.rmtree(work, ignore_errors=True)
        yield from _direct_passthrough(src, dst, app_name)
        return

    dst_existed = dst.exists()
    try:
        yield staged_src, staged_dst
        # Relocate the produced PDF back to its real destination - but ONLY if
        # it is a real one. This used to promote anything that EXISTED, with a
        # comment calling it the "success path", and it is not: a conversion
        # that errors part-way still leaves whatever Office had written.
        #
        # Measured on the 2026-08-11 download matrix (course 43660): an
        # 870-byte "PDF" sitting beside the .pptx it failed to convert, tracked
        # by nothing - it is offered as a NEW file on every future sync, for
        # ever. And the worse half is two lines up: `dst.unlink()` runs first,
        # so a failed re-conversion DESTROYED the good PDF a previous run had
        # produced and replaced it with the stub.
        #
        # The gate is the same `converters.verify` pair every source-deleting
        # converter already uses. It lives HERE, at the promotion, rather than
        # in the three converters, because this is the boundary all of them
        # cross - the counting rule from `pdf_looks_real` (two delete sites
        # needed two gates) is what makes a per-converter version the wrong
        # shape. A fourth converter gets it for free.
        if staged_dst.exists() and _product_is_real(staged_dst):
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    dst.unlink()
                shutil.move(str(staged_dst), str(dst))
            except Exception as e:
                # Last-ditch copy so a same-volume move quirk can't lose output.
                try:
                    shutil.copy2(staged_dst, dst)
                except Exception:
                    logger.warning(
                        f"[AppleScript] converted file produced in container but could "
                        f"not be moved back to {dst}: {e}"
                    )
        elif staged_dst.exists():
            logger.warning(
                f"[AppleScript] {app_name} left an unusable {staged_dst.suffix} "
                f"for {src.name}; discarding it rather than writing it to "
                f"{dst.name}"
                + (" (the existing file there is left untouched)" if dst_existed else "")
            )
    finally:
        # The staging dir goes whatever happened, so a product we declined is
        # discarded with it - "a declined conversion leaves NOTHING behind",
        # the same rule `converters/archive.py:_decline` states for extraction.
        shutil.rmtree(work, ignore_errors=True)


# NO per-file "hide the Office app" step, and that is a MEASURED decision, not an
# omission - macOS 15, real hardware, 2026-08-10.
#
# Until today this module prepended `set visible of (first process whose name is
# "Microsoft Word") to false` via System Events to every conversion script, to
# stop Word's start-screen gallery / a document window flashing past. It was
# removed because it was wrong three ways:
#
# 1. It demanded **Accessibility** ("Canvas Downloader would like to control this
#    computer using accessibility features") - the worst prompt macOS has for a
#    student's first run: it has NO Allow button (only "Open System Settings" and
#    a visually primary "Deny"), it cannot be granted from the dialog at all, and
#    it is the scariest-sounding one, on an app that ships unsigned. Onboarding
#    friction is what kills adoption here. Every other prompt the app raises is
#    Automation or the folder powerbox, both answerable in place with Allow / OK.
#
# 2. It hid the USER'S OWN Office session. Hiding a *process* hides all of its
#    windows. Measured: a Word window the user had opened themselves, with their
#    own document on screen, went visible=true -> false the instant a conversion
#    started - their document vanished mid-work.
#
# 3. It bought NOTHING. Measured on the real converter, cold Word, two
#    conversions back to back, sampling `visible of process` every 0.25s:
#
#        with the System Events hide   ->  visible 2/11 samples (0.13s..0.84s)
#        with `open -g -j` instead     ->  visible 1/12 - 2/11
#        with NEITHER                  ->  visible 0/7, twice, repeatable
#
#    Doing nothing is the QUIETEST of the three. An Apple event to a
#    not-running app (`tell application "Microsoft Word" to open ...`) launches it
#    without activating it, so it comes up already hidden - the trace goes
#    straight `absent -> false`. An explicit `open -g -j -a` is what introduces a
#    brief visible blip, during its own launch.
#
# `prime_office_automation` still launches the apps with `open -g -j` and that is
# right: its job is to batch the one-time Automation prompts up front, so it has
# to launch them, and `-j` keeps that launch hidden. Its blip happens once per
# run, at a moment the user is being shown a permission notice anyway.
#
# What is UNAVOIDABLE is the dock ICON appearing while Office runs - the app
# genuinely is running. It does not bounce, because nothing activates it
# (measured: frontmost stayed Finder throughout every conversion above).
#
# If window-flashing is ever reported again, re-measure with the trace above
# before adding anything back; do not reach for System Events.


# The first-run permission copy, in ONE place because it had two byte-identical
# copies (app.py and sync/execution.py) and it was WRONG in both.
#
# HISTORY, because the copy and the mechanism have to be changed together. It
# said "Click Allow / OK on each" while the app also raised an **Accessibility**
# prompt ("Canvas Downloader would like to control this computer using
# accessibility features"), which has NO Allow button - its only options are
# **Open System Settings** and **Deny**, with Deny visually primary. So the one
# instruction the app gave was impossible to follow on that dialog, and the
# obvious remaining click was the refusal.
#
# That prompt is now GONE: the System Events call that caused it was deleted
# outright (see the measured note above the constant), so the app no longer asks
# for Accessibility at all. Both remaining prompt families CAN be answered from the dialog, which is
# why "Allow / OK" is now true of every prompt the app raises:
#   * Automation, once per Office app + once for System Events - Allow;
#   * the macOS 15 "access data from other apps" folder prompt - OK.
# If a future change reintroduces an Accessibility prompt, this sentence stops
# being true - which is the whole reason the copy lives beside the mechanism.
#
# TWO THINGS THE COPY GOT WRONG, corrected 2026-08-14 after the pre-launch audit.
# Both are the same failure: the notice describes the batch, and then drifted
# from what the batch actually does.
#
#   1. SYSTEM EVENTS IS NOT IN THE BATCH. `first_run_permission_setup` primes
#      `_APP_TRIPLES` - PowerPoint, Word, Excel - and nothing else. The only
#      remaining System Events use is `exists process` inside the Office TEARDOWN
#      (`quit_idle_office_apps`, called from the completion screen), so its
#      Automation prompt arrives when the run FINISHES, not while this notice is
#      on screen. Listing it beside the others told the user to expect it now and
#      then left them with an unanswered dialog at the end - which is exactly the
#      state that leaves Office open with its Recents unpurged.
#
#   2. "YOU ARE ONLY ASKED ONCE" IS FALSE ON macOS 15+. The "access data from
#      other apps" consent is per app INSTANCE by design - `arm_app_data_access`
#      re-arms it every session, and this module's own docstring says so. Full
#      Disk Access is the only permanent silence. The website has stated this
#      correctly for months while the app denied it.
#
# So the rule this constant exists to enforce - the copy and the mechanism change
# together - now has to cover WHEN a prompt appears, not just WHICH prompts exist.
TCC_FIRST_RUN_NOTICE = (
    "<b>First-time macOS setup:</b> macOS will ask you to allow control of "
    "<b>Microsoft Word / Excel / PowerPoint</b>, and access to the folder you are "
    "saving into. Click <b>Allow</b> or <b>OK</b> on each - Canvas Downloader uses "
    "them only to convert Office files to PDF on your own Mac, and nothing is sent "
    "anywhere. One more dialog, for <b>System Events</b>, appears when the run "
    "finishes: that one lets the app close the Office windows it opened. All of "
    "these are one-time - except on macOS 15 and later, where "
    "&ldquo;access data from other apps&rdquo; returns once per session unless you "
    "grant Full Disk Access."
)


# ── "Is the frontmost document OURS?" ───────────────────────────────
# The AppleScript error number the converters raise when it is not. Outside
# Apple's reserved ranges, and distinctive enough to grep for in a debug log.
OFFICE_WRONG_DOC_ERRNO = -30001


def our_document_test(app_name: str, staged_name: str) -> str:
    """An AppleScript BOOLEAN: is the app's frontmost document the one we staged?

    All three converters used to bind the document they were about to export
    with a bare ``active presentation`` / ``active document`` / ``active
    workbook`` - the FRONTMOST one, which is not necessarily ours. Two ways
    that loses a user's work, and the second is silent:

    * the ``on error`` handler did ``close active <doc> saving no``, so a
      conversion that failed while the user had a document open **discarded
      their unsaved edits**. Not hypothetical - the 2026-08-11 matrix logged
      eleven PowerPoint failures (``Parameter error. (-50)``) in one course;
    * on the success path a slow ``open``, or an app in crash-recovery with a
      recovered deck frontmost, means we export THEIR document into our PDF
      and then close it. The PDF has the wrong content and nothing says so.

    The fix binds by name. ``office_container_stage`` stages every conversion
    as ``src.<ext>`` in a per-conversion uuid dir, so we own that name.

    WHY A NAME COMPARISON AND NOT A REFERENCE, measured 2026-08-11 on macOS
    26.6 against the real applications (scripts/probe_office_document_binding.py):

        form                                     Word      Excel     PowerPoint
        set d to (open POSIX file ...)           -2753     -2753     -2753
        first <klass> whose name is "src.x"      ok        NOT FOUND ok
        <klass> "src.x"                          -         -         HUNG
        repeat over <klass>s comparing name      error     -50       no result
        repeat over <klass>s comparing full name error     HUNG      HUNG
        name of active <klass>                   src.docx  src.xlsx  src.pptx

    Only the last row works in all three, and it is the only one that never
    ENUMERATES - which matters, because two of the enumerating forms wedged the
    app hard enough that Microsoft Error Reporting offered to restart it, and a
    restart-by-MER is what puts an Office window on the user's screen for the
    rest of the batch. So the safest guard is also the cheapest one.

    It fails SAFE in the direction that matters. If the frontmost document is
    not ours we do nothing to it: the worst case becomes a document of ours
    left open (recoverable - the run's teardown force-closes marker-matched
    documents), never a user document closed without saving.
    """
    mapping = _APP_DOC_MAP.get(app_name)
    if not mapping:
        raise KeyError(f"unknown Office app_name {app_name!r}")
    _ms_name, doc_term = mapping
    return f'((name of {doc_term}) is "{applescript_string(staged_name)}")'


# ── Last-error reporting ────────────────────────────────────────────
# Post-processing runs conversions sequentially, so a single module-level
# slot is sufficient. Callers read this after run_applescript() returns
# False to show the user the REAL reason (TCC denial, app missing, timeout)
# instead of a generic "Conversion failed".
#
# Categories:
#   'permission'  - macOS Automation (TCC) denied (-1743). FATAL for the
#                   whole phase: every subsequent file will fail identically.
#   'app_missing' - Office app not installed / can't be launched. FATAL.
#   'app_crashed' - the app was running and now is not (-600). Per-file, and
#                   RETRIED once, because `tell application` relaunches it.
#                   Deliberately NOT fatal - see `_classify_stderr` for the
#                   measured run where treating it as fatal abandoned 57 files.
#   'timeout'     - this file took too long (huge deck, hung app). Per-file.
#   'other'       - anything else (corrupt file, sandbox denial, ...). Per-file.
_last_error: tuple[str, str] | None = None

# Categories that doom every remaining file in a conversion phase.
#
# 'app_crashed' is NOT here. A crash is recoverable by relaunch, and a crash
# that is NOT recoverable still ends the phase - it just does it through
# SYSTEMIC_REPEAT_THRESHOLD, after three consecutive failures, which is the
# mechanism that can tell "one bad deck" from "the app is gone".
FATAL_CATEGORIES = ('permission', 'app_missing', 'container_denied')

#: Office apps whose conversions ran WITHOUT container staging this run, i.e.
#: `_office_container_tmp` answered None. Per-run, cleared by
#: `reset_office_priming`. Read only to explain a TIMEOUT: unstaged means
#: macOS is being asked to let us drive Office over a file outside its own
#: container, which is the per-folder powerbox prompt that staging exists to
#: avoid - and an unanswered or denied prompt BLOCKS the AppleEvent until it
#: times out.
_office_unstaged: set = set()

# A failure that REPEATS is systemic even when its category is per-file.
#
# Measured on real macOS 2026-08-10: feeding the Word converter a corrupt or
# 0-byte .doc makes Word raise a MODAL "file could not be opened" alert (seen
# bouncing in the Dock by the operator). AppleScript's `open` then never yields
# an active document, so EVERY later file in the phase answers
#
#     Microsoft Word got an error: missing value doesn't understand
#     the "save as" message. (-1708)
#
# including a genuine .doc that converted seconds earlier. Nothing in the app
# recovers it - `_force_close_canvas_docs_sync` left the phantom document in
# place and only killing the process helped - so the run silently produced no
# PDFs at all and emitted one generic error per file.
#
# `_classify_stderr` maps -1708 to 'other', i.e. per-file, which is right for
# ONE odd document and wrong once it happens to everything. So the signal is not
# the category but the REPETITION: three identical failures in a row means the
# app is wedged, not that three documents are bad. `_abort_applescript_phase`
# already exists for exactly this ("failures that will identically doom every
# remaining file in the phase") and simply had no way to be told.
#
# Deliberately NOT a kill-and-retry: in the wedged state the documents cannot be
# enumerated, so the app cannot certify that no USER document is open, and every
# other Office path here refuses to terminate without that certificate. Aborting
# with one actionable message is the honest option, and the next run recovers.
SYSTEMIC_REPEAT_THRESHOLD = 3

# How long to wait after an Office app was found not running before asking for
# it again. macOS needs a moment to reap the dead process - and Microsoft Error
# Reporting takes its own turn first - so an immediate retry tends to inherit
# the same corpse. Small enough that one crash costs a couple of seconds
# against the 57 files the old classification abandoned.
_CRASH_RELAUNCH_PAUSE_S = 3.0

# (app|category) of the last failure, and how many times it has repeated.
_repeat_key: str | None = None
_repeat_count: int = 0


def get_last_error() -> tuple[str, str] | None:
    """Return (category, detail) for the most recent failed run_applescript()."""
    return _last_error


def systemic_failure() -> tuple[str, int] | None:
    """(app_name, count) when the SAME failure has repeated enough to be systemic.

    ``None`` while failures are still plausibly per-file. Any success resets the
    run, so a phase with scattered bad documents never trips this - it takes
    ``SYSTEMIC_REPEAT_THRESHOLD`` identical failures with nothing working in
    between.
    """
    if _repeat_key and _repeat_count >= SYSTEMIC_REPEAT_THRESHOLD:
        return _repeat_key.split("|", 1)[0], _repeat_count
    return None


def _classify_stderr(err_msg: str) -> str:
    """Map an osascript stderr message to an error category.

    ``-600`` / "isn't running" is deliberately NOT ``app_missing``. It is
    ``procNotFound``: the app is not running *right now*, which is exactly the
    state a CRASH leaves behind - and the next ``tell application`` relaunches
    it. Treating it as "not installed" made a recoverable condition fatal.

    Measured on the 2026-08-11 download matrix, course 43660, in three log
    lines three seconds apart::

        21:29:47  PowerPoint failed (other): ... Parameter error. (-50)
        21:29:50  PowerPoint failed (app_missing): ... Application isn't running. (-600)
        21:29:50  ... skipping remaining 57 PowerPoint file(s)

    PowerPoint had crashed. The user was told it "is not installed or could not
    be launched" - about an app they had just watched convert forty files - and
    **57 files were abandoned for the rest of the run**, permanently, because
    ``app_missing`` is in ``FATAL_CATEGORIES``.

    Genuine absence still lands in ``app_missing``: ``-10810`` (launch failed),
    ``-10814`` (kLSApplicationNotFoundErr) and the "can't be found" wordings.
    """
    # Normalise the apostrophe ONCE rather than spelling every clause twice.
    # macOS writes a TYPOGRAPHIC apostrophe (U+2019) and the clauses below were
    # written with the ASCII one, so they matched nothing. That was already
    # learned here for "isn't running" - which is why that one line carries both
    # forms - and the same fix was never applied to its neighbours. Measured on
    # macOS 26.6.1: a missing app really says `Can’t get application "X". (-1728)`.
    low = err_msg.lower().replace('\u2019', "'").replace('\u2018', "'")
    # 'authorised' as well as 'authorized': this machine's macOS emits the
    # BRITISH spelling, so the American-only clause never fired and the whole
    # verdict rested on the -1743 code beside it.
    if ('-1743' in err_msg
            or 'not authorized to send apple events' in low
            or 'not authorised to send apple events' in low):
        return 'permission'
    # NOTE the numeric list does NOT include -1728. That is errAENoSuchObject,
    # which our own scripts also raise for an absent DOCUMENT (`can't get active
    # document`); mapping it wholesale would abort a phase with "Office is not
    # installed" on a machine where it plainly is. The wording clause below
    # separates the two exactly, now that it can match at all.
    if (
        '-10810' in err_msg or '-10814' in err_msg
        or "application can't be found" in low
        or "can't get application" in low
        or 'unable to find application' in low
    ):
        return 'app_missing'
    # -609 is `connectionInvalid`: the Apple event connection to the app died
    # under us. It is the same recoverable condition as -600 one step earlier -
    # the app was there when we addressed it and is not there now - and this
    # module's OWN docstring already cites `Connection is invalid. (-609)` as
    # the signature of PowerPoint being torn down mid-conversion. It was
    # nonetheless classified `other`, which gets NO retry, so a transient death
    # failed the file outright.
    #
    # Measured 2026-08-21, matrix row m032 (the largest Office batch in the
    # plan, ~88 files across two courses): three files failed transiently, each
    # surrounded by dozens of successes, and all three fell to `other`. They
    # were recovered only because `retry_failed_conversions` sweeps the phase
    # afterwards - and because that late sweep re-resolves the destination, each
    # also minted a duplicate `<stem> (n).pdf` beside the real product.
    #
    # -30001 is deliberately NOT here, and that is a decision, not an omission.
    # It is OUR OWN guard ("the frontmost presentation is not the one Canvas
    # Downloader opened"), and `app_crashed` tells the user the app "stopped
    # running while converting" - which is FALSE for -30001: the app is running
    # perfectly, it simply has someone else's document in front, which is what
    # happens when the user opens a document mid-run. Buying one retry with a
    # message that misdescribes the machine's state is the wrong trade in a
    # product whose whole reporting contract is that it tells the truth. It also
    # collapses the one distinction that made this row diagnosable at all.
    # `test_container_denied_attribution` additionally uses -30001 as its only
    # non-timeout `other` fixture. If it is ever made retryable it needs its own
    # category and its own wording - see MAC_RUNBOOK.md.
    if ('-600' in err_msg or '-609' in err_msg
            or "isn't running" in low
            or 'connection is invalid' in low):
        return 'app_crashed'
    return 'other'


def attribute_office_failure(category: str, app_name: str, err_msg: str) -> str:
    """Refine a stderr-only verdict with what THIS RUN knows about staging.

    `_classify_stderr` is handed the message and nothing else, so it cannot tell
    a slow document from a blocked permission prompt - both surface as
    ``AppleEvent timed out (-1712)``. The deciding fact is whether this run got
    container staging for this app: unstaged means macOS was asked to let us
    drive Office over a file OUTSIDE its container, which raises the per-folder
    powerbox prompt that staging exists to avoid, and a denied or unanswered
    prompt holds the event until it times out.

    A separate function, not an inline test, for two reasons. It is the whole
    decision, so tests can exercise the REAL rule instead of a copy - a copy is
    how four mutants survived the first version of this. And it keeps
    `run_applescript` reading as a sequence of verdicts rather than hiding a
    second classifier inside it.

    Deliberately narrow, because the failure in the other direction is real: a
    genuinely huge deck that times out WITH staging must stay a per-file
    ``other``, not abort the phase and tell the user to change a setting that is
    fine.
    """
    if (category == 'other' and app_name in _office_unstaged
            and ('-1712' in err_msg or 'timed out' in err_msg.lower())):
        return 'container_denied'
    return category


def _timeout_for(src: Path, base: int = 180) -> int:
    """Size-scaled osascript timeout.

    The old fixed 120s killed conversions of large lecture decks (a 50 MB
    pptx legitimately takes minutes on first launch while Office warms up
    and macOS shows the one-time Automation prompt). Scale with file size:
    base + 8s per MB, capped at 10 minutes.
    """
    try:
        size_mb = src.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0
    return min(600, int(base + size_mb * 8))


def applescript_string(text) -> str:
    """Make *text* safe to interpolate into an AppleScript string literal.

    Escapes backslashes first, then double-quotes, then flattens BOTH line
    break characters. Use as: ``display notification "{applescript_string(s)}"``.

    **This is the one implementation, and it is here because the rule had three
    - one of which was wrong.** An AppleScript string literal cannot span lines,
    so a raw ``\\n`` *or* ``\\r`` inside one is a SYNTAX error that takes the
    whole script down; a double-quote or backslash is an injection. Every
    builder in this app agreed on quotes and backslashes and then diverged on
    line breaks: this module and ``shared.helpers.native_folder_picker``
    flattened both, while ``engine.notifications._show_macos_notification``
    flattened only ``\\n`` - so a lone ``\\r`` (a Canvas course name reaches
    that one, via the daily-sync summary) produced an invalid script that
    osascript rejected, and the notification silently never appeared. Same
    divergent-primitive shape as ``make_long_path``'s duplicate in
    ``core/sync_manager.py``: the fix landed on some callers and not others
    because the rule was written more than once.

    This module imports nothing from the app, so every caller can reach it
    without a cycle.
    """
    return (str(text)
            .replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('\n', ' ')
            .replace('\r', ' '))


def _as_posix(path: Path) -> str:
    """Return a POSIX path string safe for embedding in an AppleScript string literal.

    Use inside AppleScript string literals as: ``POSIX file "{_as_posix(path)}"``

    IMPORTANT: Callers that build AppleScript ``script`` strings must use this
    function for every path interpolated into the script to prevent AppleScript
    injection via filenames containing double-quotes or backslashes.

    The line breaks matter and were missing. macOS permits every byte except
    ``/`` and NUL in a filename, so a path carrying one is reachable two ways:
    the user's own download folder (the picker returns whatever they chose), and
    an extracted archive member, whose name comes from the zip and never passes
    through ``_sanitize_filename``. The escaping itself now lives in
    :func:`applescript_string` - see there for why it is only written once.
    """
    return applescript_string(path.resolve())


def _try_close_document_after_timeout(app_name: str, posix_src: str) -> None:
    """Best-effort: close the document that was left open after an osascript
    timeout.  Runs a short-timeout osascript so a hung Office app cannot block
    the next conversion indefinitely.

    We close only the specific document (by POSIX path) rather than quitting
    the whole application, so we don't disturb any files the user had open
    independently of Canvas Downloader.
    """
    mapping = _APP_DOC_MAP.get(app_name)
    if not mapping:
        logger.warning(
            f"[AppleScript] _try_close_document_after_timeout: unknown app_name {app_name!r}; "
            "open document may need to be closed manually."
        )
        return
    ms_app_name, doc_term = mapping

    # Build a targeted close script for the specific file path.
    # Falls back gracefully if the document is not found (e.g., never opened).
    close_script = f'''
        try
            tell application "{ms_app_name}"
                set posixTarget to POSIX file "{posix_src}" as text
                close (every document whose file = posixTarget) saving no
            end tell
        end try
    '''
    try:
        subprocess.run(
            ['osascript', '-e', close_script],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass  # Best-effort only - don't let cleanup failures surface


def run_applescript(src: Path, dst: Path, app_name: str, script: str) -> bool:
    """Convert *src* to *dst* by driving *app_name*, one process at a time.

    A thin wrapper so the cross-process serialisation cannot be forgotten: the
    lock has to cover the WHOLE of `open` -> `save active` -> `close` (and the
    crash retry inside it), and this is the one entry point all three
    converters share. See `_office_app_lock` for the measured reproduction -
    two batches at once produced 0 conversions out of 16 and crashed
    PowerPoint into Microsoft Error Reporting.
    """
    with _office_app_lock(app_name):
        # Under the lock, so the observation cannot race the other instance's
        # launch: "was it already running?" is only meaningful before we
        # ourselves cause it to run.
        _note_office_preexisting(app_name)
        return _run_applescript_locked(src, dst, app_name, script)


def _run_applescript_locked(src: Path, dst: Path, app_name: str, script: str) -> bool:
    """Execute an AppleScript via ``osascript`` to convert a file.

    This is the single source of truth for all AppleScript-based
    Office automation (Excel, Word, PowerPoint) on macOS.

    Args:
        src: Source file path (used only for context logging; the actual
             POSIX path is baked into *script*).
        dst: Expected output path - checked for existence after execution.
        app_name: Human-readable application name for log messages
                  (e.g. ``"Excel"``, ``"Word"``, ``"PowerPoint"``).
        script: The complete AppleScript source to execute.

    Returns:
        ``True`` if ``osascript`` exited cleanly **and** *dst* exists
        on disk; ``False`` otherwise.

    IMPORTANT: All POSIX paths embedded in *script* must be escaped using
    ``_as_posix(path)`` from this module to prevent AppleScript injection
    via filenames containing double-quotes or backslashes.
    """
    global _last_error
    _last_error = None
    timeout_s = _timeout_for(src)

    def _fail(category: str, detail: str) -> bool:
        """Record a conversion failure once, in both places, and return False.

        Every failure exit of this function goes through here so the health
        tally can never drift from ``_last_error`` - the alternative was a
        ``note_failure`` bolted onto each of the five ``_last_error =`` sites,
        which is exactly the shape that goes stale when a sixth is added.
        These failures otherwise reach only the OPT-IN debug log, so on a real
        user's Mac they leave no trace at all - and macOS Office automation is
        the least-tested path this app has, with no crash-telemetry channel.
        """
        global _last_error, _repeat_key, _repeat_count
        _last_error = (category, detail)
        # Count identical (app, category) failures in a row - see
        # SYSTEMIC_REPEAT_THRESHOLD. Keyed on the CATEGORY, not the message,
        # because the message carries the filename and would therefore never
        # repeat; the wedge shows up as the same category over and over.
        key = f"{app_name}|{category}"
        if key == _repeat_key:
            _repeat_count += 1
        else:
            _repeat_key, _repeat_count = key, 1
        try:
            from core.health_log import note_failure
            note_failure(f"osascript_{category}")
        except Exception:
            pass
        return False
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=timeout_s,
        )
        if result.returncode != 0:
            err_msg = result.stderr.strip()
            category = _classify_stderr(err_msg)

            # A CRASHED app is not a missing one - relaunch and try this file
            # once more. `tell application` launches it for us, so the retry is
            # simply the same script again; the pause lets macOS finish tearing
            # the dead process down (and lets Microsoft Error Reporting take its
            # own turn) before we ask for a new one.
            #
            # Bounded at ONE retry per file on purpose. A file that reliably
            # crashes the app would otherwise loop, and the existing
            # SYSTEMIC_REPEAT_THRESHOLD still ends the phase after three such
            # failures in a row - so a genuinely wedged app is still caught,
            # while a single crash costs one file's delay instead of the
            # remaining 57 files.
            if category == 'app_crashed':
                logger.warning(
                    f"[AppleScript] {app_name} was not usable ({err_msg}) - it "
                    f"most likely crashed or was torn down mid-conversion; "
                    f"relaunching and retrying {src.name} once"
                )
                time.sleep(_CRASH_RELAUNCH_PAUSE_S)
                result = subprocess.run(
                    ['osascript', '-e', script],
                    capture_output=True, text=True, timeout=timeout_s,
                )
                if result.returncode == 0 and dst.exists():
                    global _repeat_key, _repeat_count
                    _repeat_key, _repeat_count = None, 0
                    logger.info(f"[AppleScript] {app_name} recovered after a crash; "
                                f"{src.name} converted on the retry")
                    return True
                err_msg = result.stderr.strip() or err_msg
                category = _classify_stderr(err_msg)

            # A timeout while UNSTAGED is the powerbox prompt, not a slow
            # document - see `attribute_office_failure`.
            category = attribute_office_failure(category, app_name, err_msg)

            if category == 'permission':
                detail = (
                    f"macOS blocked Canvas Downloader from controlling Microsoft {app_name} "
                    f"(Automation permission denied). Enable it in System Settings → "
                    f"Privacy & Security → Automation → Canvas Downloader."
                )
            elif category == 'container_denied':
                # Full Disk Access, NOT "Files and Folders": checked in System
                # Settings on 26.6.1 with this denial recorded - the app appears
                # under Files and Folders with NO TOGGLE, so sending the user
                # there is sending them nowhere. FDA supersedes this grant and
                # is the pane the app's own nudge and Settings card already
                # open (`render_fda_settings_card`), so the words match an
                # affordance the user can actually find.
                detail = (
                    f"Microsoft {app_name} did not respond, which usually means "
                    f"macOS is waiting on permission to open files in this folder. "
                    f"Turn on Canvas Downloader under System Settings → Privacy & "
                    f"Security → Full Disk Access (or in the app's Settings → macOS "
                    f"permissions), then run again."
                )
            elif category == 'app_missing':
                detail = f"Microsoft {app_name} is not installed or could not be launched."
            elif category == 'app_crashed':
                detail = (
                    f"Microsoft {app_name} stopped running while converting "
                    f"{src.name} (it may have crashed or been quit) and did not "
                    f"come back on a retry."
                )
            else:
                detail = err_msg or f"Microsoft {app_name} returned an unknown error."
            logger.error(f"[AppleScript] {app_name} failed ({category}): {err_msg}")
            return _fail(category, detail)
        if dst.exists():
            # A success proves the app is not wedged, so the repeat run ends
            # here. Without this reset, a phase with scattered bad documents
            # would eventually accumulate to the threshold and abort a run that
            # was converting everything else perfectly well.
            _repeat_key, _repeat_count = None, 0
            return True
        return _fail('other', f"Microsoft {app_name} reported success but no output file was created.")

    except FileNotFoundError:
        logger.error("[AppleScript] osascript not found (not on macOS?)")
        return _fail('other', 'osascript not found (not on macOS?)')
    except subprocess.TimeoutExpired:
        _fail('timeout', f"Conversion timed out after {timeout_s}s (Microsoft {app_name} stopped responding or the file is very large).")
        logger.error(
            f"[AppleScript] {app_name} conversion timed out after {timeout_s}s - "
            "attempting to close the open document to recover"
        )
        posix_src = _as_posix(src)
        _try_close_document_after_timeout(app_name, posix_src)
        # Also sweep any staged copy left open (the staged path carries the
        # CanvasDownloaderTmp marker; the exact-path close above only covers the
        # direct-path fallback). Async so a hung app can't block the next file.
        mapping = _APP_DOC_MAP.get(app_name)
        if mapping:
            # This runs from INSIDE `run_applescript`'s lock for this app, so
            # the sweep must not try to take it again - see the note in
            # `_force_close_canvas_docs_sync`.
            _force_close_canvas_docs_async(mapping[0], _locked_by_caller=True)
        return False
    except Exception as e:
        logger.error(f"[AppleScript] {app_name} error: {e}")
        return _fail('other', str(e))

def _marker_in_value(value) -> bool:
    """True if *value* (a SQLite cell: str, bytes/UTF-16, or None) holds our marker.

    Office stores recent-file paths in the registry DB either as TEXT or as a
    UTF-16/UTF-8 BLOB depending on version, so we decode defensively rather than
    rely on a SQL ``LIKE`` (which would silently miss UTF-16-encoded paths).
    """
    if value is None:
        return False
    if isinstance(value, str):
        return _CANVAS_TMP_MARKER in value
    if isinstance(value, (bytes, bytearray)):
        for enc in ('utf-16-le', 'utf-8', 'latin-1'):
            try:
                if _CANVAS_TMP_MARKER in bytes(value).decode(enc, errors='ignore'):
                    return True
            except Exception:
                continue
    return False


#: Which Office apps were ALREADY RUNNING when this RUN first drove them.
#:
#: THIS IS THE QUIT DECISION, and it replaces asking the documents. A document
#: check cannot answer it: measured 2026-08-12, every app is left holding one
#: document whose name, path and `saved` are ALL unreadable once a conversion
#: phase has run, and `_force_close_canvas_docs_sync` cannot close it either
#: because it identifies documents by those same properties. Neither default
#: works - treating an unreadable document as pristine QUIT WORD AND DISCARDED
#: THE USER'S UNSAVED ESSAY, and treating it as a blocker left all three apps
#: in the dock after every single run.
#:
#: "Was it running before we touched it?" is answerable, cheap, and exactly the
#: rule the product owner chose. If the user already had Word open, it is
#: theirs and we never quit it; if we launched it, every document in it is ours.
#:
#: PER **RUN**, NOT PER PROCESS - it used to be per process, and that was the
#: same defect one level up (2026-08-13). `reset_office_priming` clears every
#: other piece of per-run Office state and this was not in its list, so run 2 of
#: a session inherited run 1's answer. Reproduced against these functions:
#:
#:     run 1  nothing open, we launch all three   -> recorded False (ours)
#:            ...the user opens Word and starts an unsaved essay...
#:     run 2  Word IS the user's                  -> still reads False
#:            -> the teardown calls it ours, the conversion phase has just made
#:               its documents undescribable, `undescribable_is_ours` says
#:               pristine, and the quit goes out `saving no`
#:
#: i.e. the D9 data loss, reached through a stale fact rather than a wrong
#: default. Three states, and `None` is a real answer - see
#: `office_is_ours_to_quit`.
_office_preexisting: dict = {}

#: Guards the check-then-set in `_note_office_preexisting`. The observation is
#: taken from a worker thread (`_warmup_apps`) as well as the main one, and two
#: callers straddling a launch could otherwise both pass the "not recorded yet"
#: check and let the LATER, post-launch answer win - which is the one direction
#: that costs a user's document. First writer wins, always.
_office_observe_lock = threading.Lock()


def _note_office_preexisting(app_name: str) -> None:
    """Record, ONCE per app per run, whether the user already had it open."""
    if app_name in _office_preexisting:     # fast path: no lock once answered
        return
    bundle = _APP_DOC_MAP.get(app_name, (None,))[0]
    if not bundle:
        return
    with _office_observe_lock:
        if app_name in _office_preexisting:  # another thread got there first
            return
        try:
            running = subprocess.run(["pgrep", "-x", bundle],
                                     capture_output=True, timeout=5).returncode == 0
        except Exception:       # noqa: BLE001
            running = True      # on doubt, treat it as the user's and never quit it
        _office_preexisting[app_name] = running
    if running:
        logger.info(f"[OfficeQuit] {app_name} was already running before this "
                    f"run - it will be left alone at the end")


def observe_office_before_launch() -> None:
    """Record who was already open, for EVERY app, before we launch anything.

    THE ONE PLACE THE RULE IS WRITTEN, because it has to hold at three call
    sites and a rule written three times is a rule one caller is following an
    old version of. It is idempotent, so calling it again costs a dict lookup.

    Note it observes ALL THREE apps, not just the ones about to launch: the
    run's contract can widen between courses (`office_contract_from_folder` is
    scoped per folder), so the app nobody was going to open is exactly the one
    that gets launched later - and by then our own launch has already happened.
    """
    for _key, _ms, short in _APP_TRIPLES:
        _note_office_preexisting(short)


def office_is_ours_to_quit(app_name: str) -> bool:
    """True only for an app we OBSERVED not running and then drove ourselves.

    THREE STATES, and the third is why this is not `dict.get(app, False)`:

    =====================  ==========================================  ========
    `_office_preexisting`  meaning                                     verdict
    =====================  ==========================================  ========
    ``False``              we looked, it was not running, we launched  **quit**
    ``True``               the user already had it open                leave
    *absent*               we never drove this app this run            leave
    =====================  ==========================================  ========

    The absent case used to collapse into "ours", which is the direction that
    reaches `quit saving no`. It is reachable: cancel a download before priming
    has run and NOTHING has been observed, so the teardown - which also fires on
    the cancelled screens - would ask every Office app to quit, including one
    the user is working in. The only thing standing in the way was the document
    check, and D9 is the record of that check being unable to answer.

    "We never used it, so it is not ours to quit" is also simply the correct
    reading, not merely the safe one; `test_an_unobserved_app_is_not_treated_as_the_users`
    said so in its own docstring while asserting the opposite.

    THE ONE RESIDUAL CASE, CONSIDERED AND DECLINED. This asks "was it running
    when we looked?", not "did we drive it?" - and `_QUIT_TARGETS` is all three
    apps on every run. So an app we observed as idle and then never touched (a
    .pptx-only run leaves Word alone) still counts as ours. If the user opens it
    MID-RUN it is asked to quit, and the document check is what protects them
    there - which is sound precisely because no conversion phase ran for that
    app, so its documents are still describable: a real path blocks, and so do
    unsaved changes in a never-saved one. Only a pristine blank is quit, and
    that is the documented behaviour this function was originally written for.

    Recording a separate "we actually drove it" set would close the gap exactly,
    and was rejected: it is a SECOND fact about the same question, kept in a
    second place, and two records of one question drifting apart is the entire
    bug this file has now fixed twice.
    """
    return _office_preexisting.get(app_name) is False


#: The registry segment naming each app's Recents subtree, measured on the real
#: database: Software/Microsoft/Office/15.0/Common/MruUserData/UnsignedUser/
#: <App>/Local/Documents. Keyed by the short name, valued by the process name.
_OFFICE_PROCESSES = {
    "PowerPoint": "Microsoft PowerPoint",
    "Word": "Microsoft Word",
    "Excel": "Microsoft Excel",
}


def _running_office_apps() -> set:
    """Which Office apps are alive right now, by their registry short name.

    `pgrep -x`, not an Apple event: asking an app would LAUNCH it, which is the
    opposite of what a "has this shut down?" check wants.

    EVERYTHING on doubt. A skipped purge costs some clutter in Recents; a purge
    that races a live app costs a half-rewritten shared registry, because a
    live app holds its list in memory and rewrites the DB when it exits.
    """
    running = set()
    for short, bundle in _OFFICE_PROCESSES.items():
        try:
            if subprocess.run(["pgrep", "-x", bundle],
                              capture_output=True, timeout=5).returncode == 0:
                running.add(short)
        except Exception:       # noqa: BLE001
            return set(_OFFICE_PROCESSES)
    return running


def _any_office_running() -> bool:
    """True if any Office app is alive. See `_running_office_apps`."""
    return bool(_running_office_apps())


def _purge_recents_sqlite() -> None:
    """Delete our staged-temp files from Office's Recent-files registry DB.

    Modern Office for Mac shows the start-screen "Recent" list from a shared
    SQLite registry (``MicrosoftRegistrationDB.reg`` under the Office group
    container), NOT from securebookmarks.plist (the old delete-the-plist trick
    stopped working). Each recent file is one ``node_id`` in
    ``HKEY_CURRENT_USER_values`` with a ``name='path'`` row holding the path.

    THE IDENTITY IS THE NODE'S **NAME**, not a ``path`` value. Measured on
    macOS 26.6: 636 of our entries, every one of them a row in
    ``HKEY_CURRENT_USER`` whose ``name`` is the full ``file://`` URL - while the
    whole database contained just 36 rows named ``path``. The first version of
    this function selected ``HKEY_CURRENT_USER_values WHERE name='path'`` and
    deleted only value rows, so it removed **495 value rows and 0 nodes**: the
    Recents list is driven by the nodes, so every entry stayed on screen, now
    stripped of its values. A half-mutation of Office's shared registry is
    worse than not running at all.

    THREE GATES, and each is doing separate work:

    * the node's name carries ``CanvasDownloaderTmp``, a directory name we own;
    * the node is a LEAF - our entries have no children, and refusing anything
      with children means this can never amputate a subtree;
    * an ancestor is an ``MruUserData`` key - so even a marker appearing
      somewhere unexpected cannot take a row outside the Recents subtree.

    It also declines while an Office app is RUNNING: a live app holds its
    Recents list in memory and rewrites this DB when it exits, resurrecting
    whatever was deleted. `quit_idle_office_apps` already orders the two, but
    the guard belongs here so the function is safe to call on its own.

    Best-effort throughout: any schema deviation no-ops rather than guessing.
    """
    import sqlite3
    group = Path.home() / "Library" / "Group Containers" / "UBF8T346G9.Office"
    db_paths = []
    # Apple Silicon: single file at the group-container root.
    asi = group / "MicrosoftRegistrationDB.reg"
    if asi.is_file():
        db_paths.append(asi)
    # Intel: hashed filename inside a sub-folder.
    nested = group / "MicrosoftRegistrationDB"
    if nested.is_dir():
        db_paths.extend(p for p in nested.glob("MicrosoftRegistrationDB*.reg") if p.is_file())

    running = _running_office_apps()
    if len(running) == len(_OFFICE_PROCESSES):
        logger.debug("[AppleScript] Recents purge skipped - every Office app is "
                     "running and would rewrite the registry on exit")
        return

    for db in db_paths:
        try:
            con = sqlite3.connect(str(db), timeout=2.0)
            try:
                cur = con.cursor()
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('HKEY_CURRENT_USER','HKEY_CURRENT_USER_values')"
                )
                if len({r[0] for r in cur.fetchall()}) != 2:
                    continue

                rows = cur.execute(
                    "SELECT node_id, parent_id, name FROM HKEY_CURRENT_USER"
                ).fetchall()
                by_id = {nid: (pid, name) for nid, pid, name in rows}
                has_child = {pid for _nid, pid, _n in rows}

                def _ancestry(node_id):
                    """(under_mru, owning app or None), walking to the root.

                    The app matters because Recents is separable PER APP -
                    measured on the real database, our 636 entries split
                    PowerPoint 487 / Excel 135 / Word 14, each under
                    ``MruUserData/UnsignedUser/<App>/Local/Documents``. That is
                    what lets a run clean up after itself while the user is
                    still editing in one of the three.
                    """
                    under, app = False, None
                    seen = set()
                    cur_id = node_id
                    while cur_id in by_id and cur_id not in seen:
                        seen.add(cur_id)
                        parent, name = by_id[cur_id]
                        text = str(name) if name else ''
                        if 'MruUserData' in text:
                            under = True
                        elif text in _OFFICE_PROCESSES:
                            app = text
                        cur_id = parent
                    return under, app

                victims = set()
                for nid, _pid, name in rows:
                    if not (_marker_in_value(name) and nid not in has_child):
                        continue
                    under, app = _ancestry(nid)
                    if not under:
                        continue
                    # An entry belonging to a RUNNING app is left alone: it
                    # would be resurrected from that app's in-memory list when
                    # it exits. An entry we cannot attribute to an app is only
                    # safe to take when nothing is running at all.
                    if app in running:
                        continue
                    if app is None and running:
                        continue
                    victims.add(nid)
                skipped = sum(1 for nid, _p, name in rows
                              if _marker_in_value(name) and nid not in victims)
                if not victims:
                    continue
                ids = [(nid,) for nid in victims]
                cur.executemany(
                    "DELETE FROM HKEY_CURRENT_USER_values WHERE node_id=?", ids)
                cur.executemany(
                    "DELETE FROM HKEY_CURRENT_USER WHERE node_id=?", ids)
                con.commit()
                logger.info(
                    f"[AppleScript] purged {len(victims)} Canvas temp entries "
                    f"from Office Recents"
                    + (f" ({skipped} marked row(s) left alone - not a childless "
                       f"MruUserData leaf)" if skipped else ""))
            finally:
                con.close()
        except Exception as e:
            logger.debug(f"[AppleScript] Recents SQLite purge skipped for {db.name}: {e}")


def _purge_securebookmarks() -> None:
    """Drop our staged-temp keys from each Office app's securebookmarks.plist.

    This is the per-app access-bookmark layer (separate from the SQLite display
    list). Removing our dead entries here keeps the bookmark store tidy. Format-
    preserving (binary stays binary) and marker-filtered, so it only ever removes
    Canvas Downloader temp paths and never the user's own bookmarks.
    """
    import plistlib
    for cid in _CONTAINER_IDS.values():
        plist = (Path.home() / "Library" / "Containers" / cid / "Data"
                 / "Library" / "Preferences" / f"{cid}.securebookmarks.plist")
        if not plist.is_file():
            continue
        try:
            raw = plist.read_bytes()
            is_binary = raw[:8] == b'bplist00'
            data = plistlib.loads(raw)
            if not isinstance(data, dict):
                continue
            victims = [k for k in list(data.keys()) if _CANVAS_TMP_MARKER in str(k)]
            if not victims:
                continue
            for k in victims:
                data.pop(k, None)
            fmt = plistlib.FMT_BINARY if is_binary else plistlib.FMT_XML
            with open(plist, 'wb') as fh:
                plistlib.dump(data, fh, fmt=fmt)
            logger.debug(f"[AppleScript] purged {len(victims)} temp bookmarks from {plist.name}")
        except Exception as e:
            logger.debug(f"[AppleScript] securebookmarks purge skipped for {cid}: {e}")


#: A quitting Office app writes its Recents list to the shared registry as it
#: goes, and that write lands slightly AFTER the process stops answering
#: `pgrep`. Purging on the strength of "the process is gone" therefore deletes
#: rows the dying app then writes back.
#:
#: MEASURED 2026-08-12, all three apps, nine conversions, cold start: the app's
#: own teardown left **9 of 9 entries** in Recents, and a manual purge moments
#: later removed all 9. `_wait_for_exit` was already waiting for the processes;
#: what it could not wait for was the write.
#:
#: So: settle on the registry going QUIET (its mtime stops moving), then purge,
#: then VERIFY - and go round again if anything reappeared. Verification is the
#: natural guard here because resurrection is the exact failure mode, and it
#: makes the fix independent of however long that final write happens to take
#: on a given machine.
_RECENTS_QUIET_S = 1.0
_RECENTS_MAX_SETTLE_S = 15.0
_RECENTS_ROUNDS = 3


def _registry_paths() -> list:
    group = Path.home() / "Library" / "Group Containers" / "UBF8T346G9.Office"
    out = []
    asi = group / "MicrosoftRegistrationDB.reg"
    if asi.is_file():
        out.append(asi)
    nested = group / "MicrosoftRegistrationDB"
    if nested.is_dir():
        out.extend(p for p in nested.glob("MicrosoftRegistrationDB*.reg") if p.is_file())
    return out


def _count_canvas_recents() -> int:
    """How many of OUR entries are in Office's Recents right now (-1 unknown)."""
    import sqlite3
    total = 0
    seen_any = False
    for db in _registry_paths():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
            try:
                total += sum(
                    1 for (name,) in con.execute("SELECT name FROM HKEY_CURRENT_USER")
                    if _marker_in_value(name))
                seen_any = True
            finally:
                con.close()
        except Exception:       # noqa: BLE001
            continue
    return total if seen_any else -1


def _wait_for_registry_quiet() -> None:
    """Block until the registry stops being written, or the cap expires."""
    paths = _registry_paths()
    if not paths:
        return
    deadline = time.time() + _RECENTS_MAX_SETTLE_S
    last = None
    quiet_since = None
    while time.time() < deadline:
        try:
            stamp = tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
        except OSError:
            return
        now = time.time()
        if stamp != last:
            last, quiet_since = stamp, now
        elif quiet_since is not None and now - quiet_since >= _RECENTS_QUIET_S:
            return
        time.sleep(0.2)


def _purge_canvas_recents() -> None:
    """Remove all traces of our container-staged temp files from Office Recents.

    Settles, purges, then verifies - see `_RECENTS_QUIET_S` for the measurement
    that made the verify necessary.
    """
    for attempt in range(_RECENTS_ROUNDS):
        _wait_for_registry_quiet()
        _purge_recents_sqlite()
        _purge_securebookmarks()
        left = _count_canvas_recents()
        if left <= 0:
            return
        # Anything left is either a running app's (correctly refused, and no
        # number of rounds will change that) or a row written back as an app
        # died. One more round settles the second case.
        if _running_office_apps():
            return
        if attempt == _RECENTS_ROUNDS - 1:
            logger.debug(f"[AppleScript] {left} Canvas temp entr(ies) still in "
                         f"Office Recents after {_RECENTS_ROUNDS} rounds")


# ── Dock "Suggested and Recent Apps" housekeeping ────────────────────
# macOS adds EVERY launched app to the Dock's recents list; the recents section
# shows the ~3 most recently opened unpinned apps. Our hidden Office automation
# therefore leaves its LAST-launched app (always Excel: priming/quit order is
# PowerPoint → Word → Excel) squatting visibly in the Dock after the run - the
# process is genuinely dead, the ICON is a Dock recents tile the user has to
# right-click → Remove from Dock. (This is why the round-5 "quit properly +
# escalate survivors" fix didn't clear the icon: quitting was never the issue.)
# Fix: snapshot which Office apps sat in Dock recents BEFORE the run's first
# hidden launch, and after the quit pass strip exactly the entries we added -
# never a pre-existing tile, never a running app - then restart the Dock (the
# only way it re-reads the list). The Dock is only ever restarted when a wrong
# icon would otherwise stay visible.

_OFFICE_BUNDLE_IDS = {
    "Microsoft PowerPoint": "com.microsoft.powerpoint",
    "Microsoft Word":       "com.microsoft.word",
    "Microsoft Excel":      "com.microsoft.excel",
}

# Office bundle ids present in Dock recents before OUR first Office launch this
# run. None = we have not launched any Office app (cleanup must then never
# touch the Dock). Reset by reset_office_priming() at each run start.
_dock_recents_before: set | None = None


def _dock_prefs_export() -> dict | None:
    """The full com.apple.dock domain as a dict (via cfprefsd), or None."""
    import plistlib
    try:
        r = subprocess.run(['defaults', 'export', 'com.apple.dock', '-'],
                           capture_output=True, timeout=10)
        if r.returncode != 0 or not r.stdout:
            return None
        return plistlib.loads(r.stdout)
    except Exception:
        return None


def _recents_entry_bundle_id(entry) -> str:
    try:
        return ((entry.get('tile-data') or {}).get('bundle-identifier') or '').lower()
    except AttributeError:
        return ''


def _office_ids_in_dock_recents(dock: dict | None) -> set:
    office = set(_OFFICE_BUNDLE_IDS.values())
    found = set()
    for entry in (dock or {}).get('recent-apps') or []:
        bid = _recents_entry_bundle_id(entry)
        if bid in office:
            found.add(bid)
    return found


def _snapshot_dock_recents() -> None:
    """Remember which Office apps were ALREADY in Dock recents pre-run.

    Called (main thread, cheap: one ``defaults export``) right before the
    run's first hidden Office launch. Only taken once per run - later priming
    calls see the snapshot in place and keep the original baseline.
    """
    global _dock_recents_before
    if sys.platform != 'darwin' or _dock_recents_before is not None:
        return
    dock = _dock_prefs_export()
    # Export failure -> treat every Office tile as pre-existing (never clean).
    _dock_recents_before = (_office_ids_in_dock_recents(dock)
                            if dock is not None else set(_OFFICE_BUNDLE_IDS.values()))


def _office_pgrep_alive(app_name: str) -> bool:
    """BSD-level liveness (pgrep) - True on any doubt (safe default)."""
    try:
        return subprocess.run(['pgrep', '-x', app_name],
                              capture_output=True, timeout=10).returncode == 0
    except Exception:
        return True


def _strip_office_recents_tiles() -> list[str]:
    """One export -> filter -> import -> ``killall Dock`` pass.

    Removes a recents tile only when ALL of these hold: it is one of the three
    Office apps, the app was NOT in recents before the run, and its process is
    not running now. Returns the bundle ids removed ([] = nothing needed, so
    the Dock was NOT restarted).
    """
    dock = _dock_prefs_export()
    if not dock:
        return []
    recents = dock.get('recent-apps')
    if not isinstance(recents, list) or not recents:
        return []
    name_by_bid = {b: n for n, b in _OFFICE_BUNDLE_IDS.items()}

    def _removable(entry) -> bool:
        bid = _recents_entry_bundle_id(entry)
        if bid not in name_by_bid or bid in _dock_recents_before:
            return False
        return not _office_pgrep_alive(name_by_bid[bid])

    kept, removed = [], []
    for entry in recents:
        (removed if _removable(entry) else kept).append(entry)
    if not removed:
        return []
    dock['recent-apps'] = kept
    import plistlib
    try:
        payload = plistlib.dumps(dock, fmt=plistlib.FMT_XML)
        p = subprocess.run(['defaults', 'import', 'com.apple.dock', '-'],
                           input=payload, capture_output=True, timeout=10)
        if p.returncode != 0:
            logger.info("[OfficeQuit] Dock recents rewrite failed (rc=%s): %s",
                        p.returncode,
                        (p.stderr or b'').decode(errors='replace')[:200])
            return []
        subprocess.run(['killall', 'Dock'], capture_output=True, timeout=10)
        removed_ids = [_recents_entry_bundle_id(e) for e in removed]
        logger.info(
            "[OfficeQuit] removed %d Office tile(s) from Dock recents (%s) "
            "and refreshed the Dock", len(removed_ids), ", ".join(removed_ids))
        return removed_ids
    except Exception as e:
        logger.debug(f"[OfficeQuit] Dock recents cleanup skipped: {e}")
        return []


def _cleanup_dock_recents() -> None:
    """Strip OUR hidden Office launches from the Dock's recents section.

    Only runs when this run actually launched Office apps (snapshot exists)
    and the recents section is enabled. The Dock is restarted (``killall
    Dock`` - it only reads the list at startup) only when at least one tile
    was actually removed, so the one-off Dock flicker happens exactly when a
    wrong icon would otherwise stay visible.

    TIMING IS THE WHOLE GAME (2026-07-09 19:34 run): the Dock MOVES a quit
    app into its recents list when it processes the app's TERMINATION. The
    first implementation rewrote+restarted the Dock 0.4s after Excel's "quit
    sent" - Word/PPT were already dead so their tiles stayed gone, but Excel
    (always quit LAST, and the slowest to tear down: it rewrites its Recents
    registry on exit) was still terminating; the freshly restarted Dock
    watched it die and re-added its tile. So: wait until every Office process
    is BSD-dead (pgrep), give the Dock a moment to commit its own recents
    write, strip, and VERIFY once after the restart - a tile that was
    re-added by a racing termination event is stripped by the second pass.
    """
    if sys.platform != 'darwin' or _dock_recents_before is None:
        return
    # Recents section disabled -> the list is invisible; nothing to clean.
    if not _dock_recents_enabled():
        return

    import time as _t
    # 1. Wait for every Office process to be truly gone (bounded; an app kept
    # alive by the user's own documents simply stays - its tile is then
    # protected by the pgrep check inside the strip pass anyway).
    _deadline = _t.time() + 15
    while _t.time() < _deadline:
        if not any(_office_pgrep_alive(n) for n in _OFFICE_BUNDLE_IDS):
            break
        _t.sleep(0.5)
    # 2. Wait for the Dock's TERMINATION write. Tile PRESENCE is not a safe
    # signal: the Dock also writes tiles at LAUNCH, which is what satisfied
    # the previous expected-tiles poll instantly on the 21:26 run - the strip
    # still ran before Excel's termination write and the verify pass had to
    # restart the Dock a SECOND time. What is reliably observable is the
    # WRITE itself: the Dock rewrites recent-apps when it processes an app's
    # termination, 0-6s after the process dies (measured across the 21:08 /
    # 21:26 runs). So watch the list: strip only after at least one CHANGE
    # has been observed and the list has then stayed quiet for two
    # consecutive 1s samples (per-app writes usually batch into one Dock
    # pass), or after 8s if no write ever shows (it landed before our first
    # sample, or the Dock declined to add a tile). The verify pass below
    # remains the net for the outliers.
    if any(_ms in _primed_apps and _bid not in _dock_recents_before
           for _ms, _bid in _OFFICE_BUNDLE_IDS.items()):
        _prev = (_dock_prefs_export() or {}).get('recent-apps')
        _changed = False
        _quiet = 0
        _deadline = _t.time() + 8
        while _t.time() < _deadline:
            _t.sleep(1.0)
            _cur = (_dock_prefs_export() or {}).get('recent-apps')
            if _cur != _prev:
                _prev, _changed, _quiet = _cur, True, 0
                continue
            if _changed:
                _quiet += 1
                if _quiet >= 2:
                    break
    # 3. Strip; when something was removed, verify once after the restart
    # (normally a no-op now - it only acts, and only then restarts the Dock
    # again, if a tile still slipped in after the poll above).
    if not _strip_office_recents_tiles():
        return
    _t.sleep(3.0)
    if _strip_office_recents_tiles():
        logger.info("[OfficeQuit] Dock recents needed a second pass (a tile "
                    "was re-added by a racing termination event)")


# ── Self (Canvas Downloader) Dock recents housekeeping ───────────────
# Two ways a phantom "Canvas Downloader" tile (no running process, no dot)
# lands in the Dock's recents section (2026-07-10 Today-mode run, macOS 15):
#   1. Transcription re-execs THIS app's binary per recording
#      (panopto.transcribe). The PyInstaller windowed bootloader registers the
#      child with LaunchServices before start.py can demote it to a Prohibited
#      background process, and the Dock may file the child's TERMINATION
#      (normal exit, or the SIGKILL a cancel sends) as a recents tile.
#   2. System Settings' "Quit & Reopen" (the Full Disk Access grant flow)
#      relaunches the app under a fresh LaunchServices identity; the OLD
#      instance's termination files a tile that can never merge with the
#      running app's (same for a stale App-Translocation launch path).
# Same disease as the Office tiles above, same proven cure: snapshot, strip
# exactly what appeared, restart the Dock only when a tile was removed.

_OWN_BUNDLE_ID = "com.canvasdownloader.app"

# OUR recents rows (raw file-URL keys) present before this Panopto batch.
# None = no snapshot taken -> cleanup must never touch the Dock.
_own_recents_before: set | None = None


def _dock_recents_enabled() -> bool:
    """False only when the Dock's recents section is explicitly disabled."""
    try:
        r = subprocess.run(['defaults', 'read', 'com.apple.dock', 'show-recents'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and (r.stdout or '').strip().lower() in ('0', 'false', 'no'):
            return False
    except Exception:
        pass
    return True


def _recents_entry_url(entry) -> str:
    """The raw _CFURLString of a recents row ('' when absent)."""
    try:
        return (((entry.get('tile-data') or {}).get('file-data') or {})
                .get('_CFURLString') or '')
    except AttributeError:
        return ''


def _recents_entry_path(entry) -> str:
    """A recents row's bundle path, normalized for comparison ('' when absent)."""
    import os
    from urllib.parse import unquote, urlparse
    url = _recents_entry_url(entry)
    if not url:
        return ''
    path = unquote(urlparse(url).path) if url.startswith('file:') else url
    return os.path.realpath(path.rstrip('/')) if path else ''


def _own_bundle_path() -> str:
    """The RUNNING instance's .app bundle path ('' when not bundled, e.g. dev)."""
    import os
    exe = os.path.realpath(sys.executable)
    idx = exe.rfind('.app/Contents/')
    return exe[:idx + 4] if idx > 0 else ''


def _own_recents_rows(dock: dict | None) -> set:
    """Raw file-URL keys of every recents row carrying OUR bundle id."""
    return {
        _recents_entry_url(entry)
        for entry in (dock or {}).get('recent-apps') or []
        if _recents_entry_bundle_id(entry) == _OWN_BUNDLE_ID
    }


def _commit_dock_recents(dock: dict, kept: list, removed: list, tag: str) -> int:
    """defaults-import the filtered recent-apps + restart the Dock.

    Returns the number of rows removed (0 = nothing written, Dock untouched).
    """
    if not removed:
        return 0
    dock['recent-apps'] = kept
    import plistlib
    try:
        payload = plistlib.dumps(dock, fmt=plistlib.FMT_XML)
        p = subprocess.run(['defaults', 'import', 'com.apple.dock', '-'],
                           input=payload, capture_output=True, timeout=10)
        if p.returncode != 0:
            logger.info("[%s] Dock recents rewrite failed (rc=%s): %s", tag,
                        p.returncode,
                        (p.stderr or b'').decode(errors='replace')[:200])
            return 0
        subprocess.run(['killall', 'Dock'], capture_output=True, timeout=10)
        logger.info(
            "[%s] removed %d phantom Canvas Downloader tile(s) from Dock "
            "recents (%s) and refreshed the Dock", tag, len(removed),
            ", ".join(_recents_entry_url(e) or '<no url>' for e in removed))
        return len(removed)
    except Exception as e:
        logger.debug(f"[{tag}] Dock recents cleanup skipped: {e}")
        return 0


def snapshot_own_dock_recents() -> None:
    """Remember OUR pre-batch Dock-recents rows (Panopto batch start, darwin).

    Re-taken per batch (batch scope, unlike the once-per-run Office snapshot).
    Export failure -> None -> cleanup never touches the Dock (fail-safe).
    """
    global _own_recents_before
    if sys.platform != 'darwin':
        return
    dock = _dock_prefs_export()
    _own_recents_before = _own_recents_rows(dock) if dock is not None else None


def _strip_own_recents_tiles() -> int:
    """Remove OUR rows that were NOT in the snapshot. Returns rows removed."""
    if _own_recents_before is None:
        return 0
    dock = _dock_prefs_export()
    recents = (dock or {}).get('recent-apps')
    if not isinstance(recents, list) or not recents:
        return 0
    kept, removed = [], []
    for entry in recents:
        if (_recents_entry_bundle_id(entry) == _OWN_BUNDLE_ID
                and _recents_entry_url(entry) not in _own_recents_before):
            removed.append(entry)
        else:
            kept.append(entry)
    return _commit_dock_recents(dock, kept, removed, 'SelfDock')


def cleanup_own_dock_recents() -> None:
    """Strip the phantom Canvas Downloader tiles this Panopto batch added.

    Called (daemon thread) when the batch ends - every exit path, including
    cancel, which SIGKILLs the live worker and is the likeliest tile filer.
    Timing mirrors _cleanup_dock_recents: the Dock files a tile when it
    processes a TERMINATION, 0-6s after the process dies; the last worker
    exits right before the batch returns. So watch recent-apps until a write
    has been observed and the list stays quiet for two 1s samples (8s cap),
    strip, and verify once after 3s for a racing write.
    """
    global _own_recents_before
    if sys.platform != 'darwin' or _own_recents_before is None:
        return
    if not _dock_recents_enabled():
        _own_recents_before = None
        return
    import time as _t
    _prev = (_dock_prefs_export() or {}).get('recent-apps')
    _changed = False
    _quiet = 0
    _deadline = _t.time() + 8
    while _t.time() < _deadline:
        _t.sleep(1.0)
        _cur = (_dock_prefs_export() or {}).get('recent-apps')
        if _cur != _prev:
            _prev, _changed, _quiet = _cur, True, 0
            continue
        if _changed:
            _quiet += 1
            if _quiet >= 2:
                break
    if _strip_own_recents_tiles():
        _t.sleep(3.0)
        if _strip_own_recents_tiles():
            logger.info("[SelfDock] recents needed a second pass (a tile was "
                        "re-added by a racing termination event)")
    _own_recents_before = None


def purge_stale_self_dock_tiles() -> None:
    """Strip DEAD-IDENTITY Canvas Downloader tiles from Dock recents (boot).

    A recents row carrying our bundle id whose bundle path is not the RUNNING
    bundle's is a dead LaunchServices identity - left by System Settings'
    "Quit & Reopen" (Full Disk Access grant) or by a previous session's
    App-Translocation path. It can never merge with the running app's tile,
    so it squats in the Dock as a second Canvas Downloader with no process
    behind it. The row from a NORMAL previous quit has the SAME path as the
    running bundle and is deliberately kept (stripping it would restart the
    Dock on every boot for nothing). Runs once at GUI boot, off-thread.
    """
    if sys.platform != 'darwin' or not _dock_recents_enabled():
        return
    own = _own_bundle_path()
    if not own:
        return  # not running from an .app bundle (dev) - identity unknowable
    dock = _dock_prefs_export()
    recents = (dock or {}).get('recent-apps')
    if not isinstance(recents, list) or not recents:
        return
    kept, removed = [], []
    for entry in recents:
        if (_recents_entry_bundle_id(entry) == _OWN_BUNDLE_ID
                and _recents_entry_path(entry) != own):
            removed.append(entry)
        else:
            kept.append(entry)
    _commit_dock_recents(dock, kept, removed, 'SelfDock/boot')


# (AppleScript app name, its document collection term) - shared by the idle-quit
# and the staged-document force-close helpers below.
_QUIT_TARGETS = [
    ("Microsoft PowerPoint", "presentations"),
    ("Microsoft Word", "documents"),
    ("Microsoft Excel", "workbooks"),
]


def _close_marker_docs_script(app: str, collection: str) -> str:
    """AppleScript that closes every open document staged by Canvas Downloader.

    Matches ONLY documents whose ``full name``/``path`` contains the unique
    ``CanvasDownloaderTmp`` staging marker, so a user's own files can never
    match. Closes one document per outer pass (re-fetching the live collection
    each time) because deleting from an AppleScript list while iterating it
    skips elements. Property reads are individually ``try``-wrapped: never-saved
    documents and dictionary differences between Office versions just no-op.
    """
    return f'''
        tell application "System Events"
            if not (exists process "{app}") then return
        end tell
        repeat 30 times
            set closedOne to false
            try
                tell application "{app}"
                    repeat with d in ({collection} as list)
                        set hit to false
                        try
                            if (full name of d as text) contains "{_CANVAS_TMP_MARKER}" then set hit to true
                        end try
                        if not hit then
                            try
                                if (path of d as text) contains "{_CANVAS_TMP_MARKER}" then set hit to true
                            end try
                        end if
                        if hit then
                            close d saving no
                            set closedOne to true
                            exit repeat
                        end if
                    end repeat
                end tell
            end try
            if not closedOne then exit repeat
        end repeat
    '''


def _force_close_canvas_docs_sync(only_app: str | None = None, *,
                                  _locked_by_caller: bool = False) -> None:
    """Close any Office documents still open from OUR container staging dir.

    A conversion can leave its staged document open in a hidden Office process
    when the run is cancelled mid-file or when an AppleEvent times out (pending
    TCC prompt, hung app). Those zombie documents then (a) keep the app's
    document count non-zero so the idle-quit refuses to quit it - which is why
    Excel lingered in the dock after a run with timeouts - and (b) confuse users
    who later unhide the app. Marker-matched, so only Canvas Downloader staging
    files are ever closed; user documents are untouchable. Synchronous -
    callers wrap in a thread when needed. Never launches an app (System Events
    running check inside the script).
    """
    if sys.platform != 'darwin':
        return
    for app, collection in _QUIT_TARGETS:
        if only_app and app != only_app:
            continue
        try:
            # macOS has ONE of each Office app per user session, so this drives
            # the same application a second instance may be converting with.
            # `_locked_by_caller` is the ONE exemption: the timeout-recovery
            # sweep in `_run_applescript_locked` already holds this app's lock,
            # and taking it again would stall that thread for the lock timeout
            # - which is exactly what its async wrapper exists to avoid.
            with _office_app_lock_unless(app, _locked_by_caller):
                subprocess.run(
                    ['osascript', '-e', _close_marker_docs_script(app, collection)],
                    capture_output=True, timeout=30,
                )
        except Exception:
            pass


def _force_close_canvas_docs_async(only_app: str | None = None, *,
                                   _locked_by_caller: bool = False) -> None:
    """Fire-and-forget thread wrapper around ``_force_close_canvas_docs_sync``."""
    if sys.platform != 'darwin':
        return
    import threading
    threading.Thread(
        target=_force_close_canvas_docs_sync, args=(only_app,),
        kwargs={'_locked_by_caller': _locked_by_caller}, daemon=True,
    ).start()


def _idle_quit_script(app: str, collection: str,
                      undescribable_is_ours: bool = False) -> str:
    """AppleScript that quits *app* unless a REAL user document is open.

    Returns a human-readable status string (captured on stdout and logged) so a
    failed quit is diagnosable from debug_log.txt instead of vanishing silently
    - the old count-based quit swallowed everything, which made "Excel stayed in
    the dock" impossible to root-cause from a test run.

    A document blocks the quit only when it looks like the USER's: it has a path
    on disk, or it has unsaved changes. Pristine blanks (never saved AND
    unmodified - e.g. the empty ``Book1`` Excel sometimes auto-creates on a
    hidden launch) do NOT block: the old ``count is 0`` condition let a single
    pristine blank keep Excel in the dock forever. Quitting with only pristine
    blanks open shows no save prompt (nothing is modified), so the quit cannot
    hang on a hidden dialog.

    **A DOCUMENT WHOSE PROPERTIES CANNOT BE READ IS DECIDED BY
    ``undescribable_is_ours``, NOT by the property defaults**, and getting that
    wrong destroyed a user's work. "Pristine" is *(no path) AND (saved)*, so
    leaving `hasPath=false` / `isSaved=true` on a failed read - which this
    function used to do, while its own docstring claimed it defaulted to
    "blocker ... never to a wrong quit" - is precisely the combination that says
    PRISTINE, and the quit goes out `saving no`.

    The caller passes True only for an app IT LAUNCHED, where every open
    document is ours by construction. An app the user already had open - or one
    we never drove at all - never reaches this script: `quit_idle_office_apps`
    refuses it on `office_is_ours_to_quit`, which is the gate that actually
    carries the safety, because after a conversion phase the documents cannot be
    described and no property test can tell whose they are.

    **THE DEFAULT IS THE SAFE ONE AND THE CALLER STATES THE POLICY.** It used to
    default to True while the single call site said nothing, so the sentence
    above ("the caller passes True only for...") described a contract nothing
    enforced - a second call site would have inherited the answer that discards
    a document. Now saying nothing means "not ours", and the teardown passes
    True explicitly, one line under the gate that earns it.

    MEASURED 2026-08-12, the ordinary "the user is editing while a sync
    converts" case. A real .doc, open and modified:

        before a conversion phase   path=[Macintosh HD:...:MY WORD WORK.doc]  saved=false
                                    -> "kept running (1 of 1 doc(s) look user-owned)"
        after a conversion phase    name / path / full name / saved ALL FAIL
                                    -> "quit sent (1 open doc(s), none user-owned)"
                                    -> THE USER'S DOCUMENT WAS CLOSED

    Word's scripting layer stops being able to describe its own documents once
    our conversion phase has opened and closed files - not stale references
    either: the reads fail even inside a single `tell` block. So readability
    cannot be relied on, only defaulted safely. Excel and PowerPoint stayed
    readable and behaved correctly throughout, which is exactly why this needed
    all three apps to surface.

    **IT IS LOAD-DEPENDENT, AND THAT IS WHY A SMALL TEST PASSES VACUOUSLY.**
    Re-measured on macOS 26.6.1 on 2026-08-20, same shape, counting the files
    the phase converted before the properties were read:

        2 files -> name/path/full name/saved ALL READ correctly
        3 files -> ALL FAIL
        4 files -> ALL FAIL
        6 files -> ALL FAIL

    Below three, the document check still works, so it catches a wrong gate
    decision and nothing appears to be broken. A harness that converts one or
    two files therefore CANNOT see this failure - the same structural blindness
    that let D11 live while every harness in the repo passed, one variable
    further in. `scripts/verify_office_end_to_end.py:MIN_ARMING_FILES` refuses
    a below-threshold run for exactly this reason; the first 8(b) run of the
    2026-08-20 session used `--files 2`, reported ALL GOOD, and proved nothing.

    The negative control, run on that machine with no product code mutated:
    this script with `undescribable_is_ours=True` - byte-for-byte what the
    teardown emits for an app it believes it launched - sent after a 6-file
    phase with the user's dirty document open returned `quit sent (1 open
    doc(s), none user-owned)`, Word quit, and the document was closed. The
    gate above is therefore the SOLE defence, not a belt-and-braces one.

    The cost of the safe default is an Office app left in the dock; the cost of
    the unsafe one is a student's unsaved essay. `pathKnown`/`savedKnown` make
    "we could not tell" expressible, which the old boolean pair could not say.

    Second defect fixed at the same time: the ``full name`` fallback tested
    ``contains "/"``, but Word returns an HFS **colon** path
    (``Macintosh HD:Users:...``), so that test could never fire for Word.

    IT MUST TEST FOR A PATH SEPARATOR, NOT MERELY A NON-EMPTY NAME. Loosening
    it to "any non-empty full name" - which this file did for a few hours on
    2026-08-12 - makes an UNSAVED document look like it has a path, because an
    unsaved document's ``full name`` is just its name. Measured on the real
    app: ``Book1 || path=[] || full name=[Book1] || saved=true`` was reported
    as user-owned, so Excel's own auto-created blank blocked the quit for ever
    and the operator's cancelled run left all three apps in the dock. That is
    the exact "a single pristine blank keeps Excel in the dock forever" failure
    this function was originally written to fix.

    Structured as three PHASE-TAGGED stages so the returned status pinpoints
    exactly where a failure happened (Excel's gallery-state ``-1700: Can't
    make missing value into type number`` survived two earlier fixes because
    the single "error N" status could not say WHAT threw):

      "enum failed (error N)"     resolving ``{collection} as list`` threw
      "doc scan failed (error N)" reading the documents' properties threw
      "kept running (...)"        a user-owned document blocks the quit
      "quit failed (error N)"     zero user docs, but the quit verb threw
      "quit sent (...)" / "not running"

    Two hard-won structural rules:
      1. The ``repeat`` loop lives OUTSIDE any ``tell application`` block.
         Inside an application tell, ``repeat with x in someList`` dispatches
         its implicit ``count`` command TO THE APP - and Excel's gallery
         state can throw -1700 on events a local evaluation handles fine.
         Each property read targets the app explicitly, per statement.
      2. The quit verb is ``quit saving no`` FIRST (plain ``quit`` as the
         error retry). A plain ``quit`` never errors when a document has
         unsaved changes - the app just shows a (hidden) save sheet and
         waits forever, while the Apple event returns fine and we log
         "quit sent". That is exactly what the 2026-07-09 round-5 run
         showed: Excel answered "quit sent (1 open doc)" and was STILL
         alive with that doc 5 minutes later. ``saving no`` is prompt-free
         and safe here: it is only reached after zero user-owned documents
         were counted.

    The Python caller escalates on the failure statuses: "quit failed"
    certifies no user documents, and for enum/scan failures a separate
    document-count probe (see ``_probe_open_docs``) certifies the app is
    empty before it is force-terminated. Additionally, any app whose status
    carried the "none user-owned" certificate but which SURVIVES the
    post-quit exit wait is terminated - so a save-sheet-stuck or otherwise
    lingering Excel can no longer squat in the dock and resurrect its
    Recents entries.
    """
    return f'''
        tell application "System Events"
            if not (exists process "{app}") then return "not running"
        end tell
        set docList to {{}}
        try
            tell application "{app}" to set docList to ({collection} as list)
        on error errMsg number errNum
            return "enum failed (error " & errNum & "): " & errMsg
        end try
        set total to 0
        set blockers to 0
        try
            repeat with d in docList
                set total to total + 1
                set pristine to false
                try
                    set hasPath to false
                    set pathKnown to false
                    set isOurs to false
                    try
                        tell application "{app}" to set p to (path of d as text)
                        set pathKnown to true
                        if p is not "" then set hasPath to true
                        if p contains "{_CANVAS_TMP_MARKER}" then set isOurs to true
                    end try
                    if not hasPath or not isOurs then
                        try
                            tell application "{app}" to set fn to (full name of d as text)
                            set pathKnown to true
                            if fn contains "/" or fn contains ":" then set hasPath to true
                            if fn contains "{_CANVAS_TMP_MARKER}" then set isOurs to true
                        end try
                    end if
                    set isSaved to true
                    set savedKnown to false
                    try
                        tell application "{app}" to set isSaved to (saved of d)
                        set savedKnown to true
                    end try
                    if isOurs then
                        set pristine to true
                    else if pathKnown and savedKnown then
                        if (not hasPath) and isSaved then set pristine to true
                    else
                        set pristine to {str(undescribable_is_ours).lower()}
                    end if
                end try
                if not pristine then set blockers to blockers + 1
            end repeat
        on error errMsg number errNum
            return "doc scan failed (error " & errNum & "): " & errMsg
        end try
        if blockers > 0 then return "kept running (" & blockers & " of " & total & " doc(s) look user-owned)"
        try
            tell application "{app}" to quit saving no
        on error
            try
                tell application "{app}" to quit
            on error errMsg number errNum
                return "quit failed (error " & errNum & "): " & errMsg & " [" & total & " open doc(s), none user-owned]"
            end try
        end try
        return "quit sent (" & total & " open doc(s), none user-owned)"
    '''


def _probe_open_docs(app: str, collection: str) -> str:
    """Ask *app* how many documents it has open - the kill-safety certificate.

    Returns "gone", "docs N", "count failed (error N)" or "probe failed: ...".
    The semantics that make this a safe gate: an Office app with a REAL open
    document answers ``count of <collection>`` reliably; the pathological
    gallery/no-document state is precisely where the count (like the
    enumeration) throws. So "docs 0" and "count failed" both certify that no
    user document exists, while "docs N>0" or a timeout (possible modal
    dialog) mean the app must be left alone.
    """
    script = f'''
        tell application "System Events"
            if not (exists process "{app}") then return "gone"
        end tell
        try
            tell application "{app}" to set n to (count of {collection})
            return "docs " & n
        on error errMsg number errNum
            return "count failed (error " & errNum & ")"
        end try
    '''
    try:
        # Drives the app (a `count of <collection>` enumeration), so it takes
        # the same per-app lock a conversion does.
        with _office_app_lock(app):
            r = subprocess.run(['osascript', '-e', script],
                               capture_output=True, text=True, timeout=15)
        return (r.stdout or "").strip() or f"probe failed: rc={r.returncode}"
    except Exception as e:
        return f"probe failed: {e}"


def quit_idle_office_apps() -> None:
    """Tidy up Office after a run: quit the apps we launched, then purge Recents.

    Steps, on a single daemon thread (macOS only):

    1. Force-close any documents still open from OUR container staging dir
       (marker-matched - see ``_force_close_canvas_docs_sync``). Cancelled or
       timed-out conversions leave their staged document open in the hidden
       Office process; closing them first is what lets step 2 actually quit.
    2. Quit PowerPoint/Word/Excel - unless a REAL user document is open (a doc
       with a path on disk or unsaved changes - see ``_idle_quit_script``).
       Post-processing leaves the apps running (we deliberately never quit them
       mid-batch, to avoid relaunch churn between courses); this clears them
       from the dock once everything is done. The System Events running check
       means we never auto-launch a quit target. Each app's outcome is LOGGED.
    3. One retry pass ~3s later for any app that didn't quit (a transiently
       busy app - e.g. one still tearing down a conversion when the user
       cancelled - refuses the first Apple event and then lingered forever
       because the quit was one-shot).
    4. Purge our container-staged temp files from Office's Recent-files lists
       (see ``_purge_canvas_recents``) so the conversion scratch files don't
       crowd out the user's real recent documents. Marker-filtered - only
       Canvas Downloader temp paths are ever removed.

    Called from BOTH the completion screens and the cancelled screens (one-shot
    gated by the ``_office_quit_fired`` session sentinel in the callers).
    Best-effort throughout; any failure is swallowed (but logged).
    """
    if sys.platform != 'darwin':
        return
    import threading

    def _quit_pass(pass_no: int, targets) -> tuple[list, dict]:
        """Ask each target app to quit.

        Returns ``(still_running, statuses)`` - the targets whose quit did not
        go through, plus each app's raw status string so the caller can pick
        the right escalation ("quit failed" = zero user-owned docs certified
        by the script but the quit verb errored → force-terminate is safe;
        "kept running"/"error" = leave the app alone).
        """
        still_running = []
        statuses: dict = {}
        for app, collection in targets:
            # THE FIRST GATE, and the one that carries the safety: we quit only
            # an app we OBSERVED not running and then launched ourselves. See
            # `office_is_ours_to_quit` - the document check cannot answer this
            # question, because after a conversion phase the documents are
            # unreadable.
            short = next((k for k, v in _APP_DOC_MAP.items() if v[0] == app), None)
            if not (short and office_is_ours_to_quit(short)):
                statuses[app] = ("left alone (we did not launch it)" if short
                                 in _office_preexisting else
                                 "left alone (we never drove it this run)")
                logger.info(f"[OfficeQuit] pass {pass_no}: {app} -> {statuses[app]}")
                continue
            try:
                # Enumerates and quits the app, so it is Office automation and
                # takes the per-app lock. Without it two instances tearing down
                # at once drive one Excel and crash it into Microsoft Error
                # Reporting - measured 2026-08-21, see `_office_app_lock`.
                with _office_app_lock(app):
                    r = subprocess.run(
                        ['osascript', '-e',
                         # EXPLICIT, never the default. Reaching this line means the
                         # gate above certified we launched the app, which is the
                         # ONLY condition under which an undescribable document may
                         # be treated as ours; the signature defaults to False so a
                         # future second call site cannot inherit the dangerous
                         # answer by saying nothing.
                         _idle_quit_script(app, collection, undescribable_is_ours=True)],
                        capture_output=True, text=True, timeout=30,
                    )
                status = (r.stdout or "").strip() or f"osascript rc={r.returncode}"
            except Exception as e:
                status = f"osascript failed: {e}"
            logger.info("[OfficeQuit] pass %d: %s -> %s", pass_no, app, status)
            statuses[app] = status
            if not status.startswith(("quit sent", "not running")):
                still_running.append((app, collection))
        return still_running, statuses

    def _terminate_gallery_stuck(app: str) -> None:
        """Terminate *app* after its scripted quit failed WITH the certificate
        that no user document is open (a "quit failed" status or a passing
        ``_probe_open_docs`` gate).

        Tries one last graceful ``quit saving no`` (harmless: nothing to
        discard), then SIGTERMs if the process is still alive. The SIGTERM
        path also skips the app's exit-time rewrite of the shared Recents
        registry DB, so the marker purge below sticks.
        """
        import time as _t
        try:
            # Office automation - same lock as every other `tell application`.
            # The pgrep/pkill escalation below is not, and deliberately runs
            # outside it: signalling a process is not driving it.
            with _office_app_lock(app):
                subprocess.run(
                    ['osascript', '-e', f'tell application "{app}" to quit saving no'],
                    capture_output=True, timeout=10,
                )
        except Exception:
            pass
        _t.sleep(1.0)
        try:
            still = subprocess.run(['pgrep', '-x', app], capture_output=True, timeout=10)
            if still.returncode == 0:
                subprocess.run(['pkill', '-x', app], capture_output=True, timeout=10)
                logger.info(
                    "[OfficeQuit] force-terminated %s (no user documents open)", app)
            else:
                logger.info(
                    "[OfficeQuit] %s exited on the final 'quit saving no'", app)
        except Exception as e:
            logger.info("[OfficeQuit] force-terminate of %s failed: %s", app, e)

    def _wait_for_exit(apps: list, timeout: float = 12.0) -> list:
        """Poll until every app in *apps* has actually terminated (or timeout).

        Returns the apps STILL RUNNING at the deadline so the caller can
        escalate (round 5 showed Excel answering "quit sent" and then simply
        never exiting - a hidden save sheet stalls a quit without any error).

        The Recents purge MUST run against dead Office processes: a still-alive
        app keeps its Recent-files list in memory and rewrites the shared
        registry DB when it eventually terminates, resurrecting the very
        entries the purge just deleted (why Excel's Recents kept showing our
        CanvasDownloaderTmp files while PowerPoint's/Word's were clean - they
        had quit, Excel hadn't). A fixed 1s nap was a race; poll instead.
        """
        import time as _time
        deadline = _time.time() + timeout
        remaining = [a for a, _c in apps]
        while remaining and _time.time() < deadline:
            still = []
            for app in remaining:
                try:
                    r = subprocess.run(
                        ['osascript', '-e',
                         f'tell application "System Events" to return '
                         f'(exists process "{app}") as text'],
                        capture_output=True, text=True, timeout=10,
                    )
                    if (r.stdout or "").strip().lower() == "true":
                        still.append(app)
                except Exception:
                    pass  # can't tell - assume gone rather than stall the purge
            remaining = still
            if remaining:
                _time.sleep(0.5)
        if remaining:
            logger.info("[OfficeQuit] still running after %.0fs wait: %s",
                        timeout, ", ".join(remaining))
        return remaining

    def _worker():
        import time as _time
        # 1. Sweep our staged zombie documents first, so idle-quit can succeed.
        _force_close_canvas_docs_sync()

        # 2. + 3. Quit each app that has nothing user-owned open; retry once for
        # stragglers (after re-sweeping staged docs, in case a doc was created
        # between the sweep and the first quit attempt).
        stragglers, statuses = _quit_pass(1, _QUIT_TARGETS)
        if stragglers:
            _time.sleep(3.0)
            for app, _c in stragglers:
                _force_close_canvas_docs_sync(only_app=app)
            stragglers, _retry_statuses = _quit_pass(2, stragglers)
            statuses.update(_retry_statuses)

        # 3b. Escalation for the failure statuses. Two certified-safe paths:
        #   - "quit failed": the script itself counted zero user-owned docs
        #     before the quit verb threw -> terminate directly.
        #   - "enum failed"/"doc scan failed" (Excel's gallery-state -1700
        #     pathology): the script could not inspect the documents, so ask
        #     for a document COUNT first (_probe_open_docs). "docs 0" and
        #     "count failed" both certify the empty/gallery state (a real
        #     open workbook answers the count); anything else - including a
        #     timeout, which can mean a modal dialog - leaves the app alone.
        _terminated = []
        _certified_safe = set()   # apps certified to hold no user documents
        for app, coll in stragglers:
            st = statuses.get(app, "")
            if st.startswith("quit failed"):
                _certified_safe.add(app)
                _terminate_gallery_stuck(app)
                _terminated.append((app, coll))
            elif "failed" in st or st.startswith("error"):
                probe = _probe_open_docs(app, coll)
                logger.info("[OfficeQuit] %s document probe -> %s", app, probe)
                if probe == "gone":
                    continue
                if probe == "docs 0" or probe.startswith("count failed"):
                    _certified_safe.add(app)
                    _terminate_gallery_stuck(app)
                    _terminated.append((app, coll))
                else:
                    logger.info(
                        "[OfficeQuit] leaving %s running (cannot certify it "
                        "has no user documents open)", app)

        # 4. Wait for the quit apps to actually DIE, then surgically purge our
        # container-staged temp files from Office's Recent-files lists (marker-
        # filtered, so a user's real recent documents are never affected).
        # Purging while an app is still alive is futile - it rewrites the
        # registry DB from memory on exit. Only apps we actually asked to exit
        # are waited on, so a legitimately busy app ("kept running") no longer
        # stalls the purge for the full timeout.
        #
        # Escalation on survivors: "quit sent" only means the Apple event was
        # DELIVERED - an app can then stall its own quit forever on a hidden
        # sheet (round 5: Excel answered "quit sent (1 open doc, none
        # user-owned)" and was still alive, doc and all, 5 minutes later,
        # squatting in the dock). Every status that reached the quit verb
        # carries the "none user-owned" certificate, so terminating a
        # survivor is provably safe - and SIGTERM also skips the app's
        # exit-time Recents rewrite, which is what lets the purge stick.
        _expected_exits = [
            (app, coll) for app, coll in _QUIT_TARGETS
            if statuses.get(app, "").startswith(("quit sent", "quit failed"))
        ]
        for pair in _terminated:
            if pair not in _expected_exits:
                _expected_exits.append(pair)
        for app, _coll in _expected_exits:
            if "none user-owned" in statuses.get(app, ""):
                _certified_safe.add(app)
        if _expected_exits:
            _survivors = _wait_for_exit(_expected_exits)
            _escalated = []
            for app in _survivors:
                if app in _certified_safe:
                    logger.info(
                        "[OfficeQuit] %s survived the exit wait despite '%s' "
                        "- escalating to terminate", app, statuses.get(app, ""))
                    _terminate_gallery_stuck(app)
                    _escalated.append((app, None))
                else:
                    logger.info(
                        "[OfficeQuit] %s survived the exit wait without a "
                        "no-user-docs certificate - leaving it alone", app)
            if _escalated:
                _wait_for_exit(_escalated, timeout=6.0)
        _purge_canvas_recents()
        # 5. Drop OUR hidden launches from the Dock's "Suggested and Recent
        # Apps" section - the process being dead does not remove its recents
        # tile (the "Excel still in the Dock after the run" report), and the
        # Dock only re-reads the list on restart. Snapshot-scoped: only tiles
        # our own priming added this run are ever touched.
        _cleanup_dock_recents()

    threading.Thread(target=_worker, daemon=True).start()


# ── Office priming state ────────────────────────────────────────────
# Which Office apps have already been launched/primed this run, and whether the
# macro-security pref has been written. Module-level (not session state) and
# reset by reset_office_priming() at the start of each download/sync run - the
# apps are quit at the previous run's completion screen, so a fresh run re-primes.
_primed_apps: set = set()
_macro_pref_written = False

# Converter key → the Office file extensions it handles. Used to scope priming to
# only the apps a run will ACTUALLY use.
_OFFICE_EXTS = {
    'convert_pptx': {'.ppt', '.pptx', '.pptm', '.pot', '.potx'},
    'convert_word': {'.doc', '.rtf', '.odt'},
    'convert_excel': {'.xlsx', '.xls', '.xlsm'},
}


def reset_office_priming() -> None:
    """Forget this run's Office state, so the next run starts from the truth.

    Call at the start of each download/sync run. The apps are quit at the previous
    run's completion screen, so their primed-state must be cleared or the next run
    would wrongly skip (re-)launching them.

    **`_office_preexisting` IS PER-RUN STATE AND WAS THE ONE PIECE THIS FUNCTION
    DID NOT CLEAR** (fixed 2026-08-13). Everything else about priming was reset
    here while "was this app the user's?" was recorded once per PROCESS, so the
    second download in a session answered with the first one's facts. The
    dangerous direction is not hypothetical:

        run 1  nothing open -> we launch Word -> recorded "ours"
               ...the user opens Word and starts an unsaved essay...
        run 2  Word is now THEIRS, but the record still says ours
               -> the teardown quits it `saving no`

    and run 2 has just had a conversion phase, which is exactly the state D9
    measured Word's documents as undescribable in - so the document check, the
    only remaining defence, cannot see it either. `_office_quit_fired` is reset
    per run by both callers, so the teardown really does fire again.

    The opposite direction (a stale "theirs") only ever costs an app left in the
    dock, which is why the fix is to re-observe rather than to age the value.
    """
    global _macro_pref_written, _dock_recents_before
    _primed_apps.clear()
    _macro_pref_written = False
    _dock_recents_before = None
    # Under the lock: `_warmup_apps` may still be observing on its worker thread
    # from the previous run, and a write landing after this clear would seed the
    # new run with the old run's answer - the very thing being fixed.
    with _office_observe_lock:
        _office_preexisting.clear()
    # Per-run, exactly like _office_preexisting above it: a run that got
    # staging must not inherit the previous run's 'unstaged' verdict and
    # then explain an ordinary timeout as a permission problem.
    _office_unstaged.clear()


def office_contract_from_folder(folder, base_contract: dict) -> dict:
    """Scope *base_contract* to the Office file types ACTUALLY present in *folder*.

    Returns a contract that enables an app only when its converter is on in
    *base_contract* AND at least one matching file exists anywhere under *folder* -
    so a course containing only .pptx never launches Word or Excel. Off macOS it
    returns the contract unchanged; on a scan error it falls back to the unscoped
    contract (so we never suppress an app that's actually needed).
    """
    import os
    if sys.platform != 'darwin':
        return dict(base_contract)
    remaining = {k for k in _OFFICE_EXTS if base_contract.get(k, False)}
    if not remaining:
        return {k: False for k in _OFFICE_EXTS}
    present = {k: False for k in _OFFICE_EXTS}
    try:
        for _root, _dirs, files in os.walk(str(folder)):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                for key in list(remaining):
                    if ext in _OFFICE_EXTS[key]:
                        present[key] = True
                        remaining.discard(key)
            if not remaining:
                break
    except Exception:
        return dict(base_contract)
    return {k: bool(base_contract.get(k, False) and present[k]) for k in _OFFICE_EXTS}


# Converter key → (AppleScript app name, container short name). Single source of
# truth for the priming/permission helpers below.
_APP_TRIPLES = [
    ('convert_pptx', "Microsoft PowerPoint", "PowerPoint"),
    ('convert_word', "Microsoft Word", "Word"),
    ('convert_excel', "Microsoft Excel", "Excel"),
]


def _warmup_apps(apps: list, write_macro_pref: bool,
                 touch_containers: bool = False,
                 on_app_answered=None) -> None:
    """Synchronously launch + permission-prime the given Office apps, hidden.

    The shared engine behind both the per-run scoped priming and the one-time
    first-run permission batch. For each app (skipped when not installed at the
    default path): hidden launch (``open -g -j``), a harmless ``count windows``
    Apple event (this is what triggers the per-app Automation TCC prompt), and
    the Excel link-dialog suppression. Optionally pre-creates our container staging
    dir (``touch_containers``) so macOS 15's "access data from other apps"
    prompt also fires HERE, at the batched moment, instead of at the first
    conversion.

    ``on_app_answered(app)`` fires only when the TCC-triggering event completed
    (Allow → rc 0, or explicit Deny → -1743) - NOT when it timed out unanswered,
    so an ignored prompt is retried on the next run. Callers run this on a
    worker thread; everything is best-effort.

    IT OBSERVES WHO WAS ALREADY OPEN FIRST, because this is the ONE function in
    the app that launches an Office app, and the observation is only meaningful
    before that. Both callers observe on their own (calling) thread too, which
    is what actually orders it correctly - this call is the backstop that makes
    a FUTURE third caller safe by construction rather than by remembering.
    """
    observe_office_before_launch()

    if write_macro_pref:
        # Kill the "this workbook contains macros" dialog suite-wide BEFORE any
        # Office app launches. The CORRECT macOS key is VisualBasicMacroExecutionState
        # (a String) on the SHARED `com.microsoft.office` domain - NOT the Windows-only
        # `VBAWarnings`, and NOT a per-app domain. (Confirmed by Microsoft's "Set
        # preferences for macro security in Office for Mac" doc.) "DisabledWithoutWarnings"
        # = macros never run and never prompt. IMPORTANT for the user's "data exactly as
        # the teacher made it" requirement: disabling macro EXECUTION does NOT blank any
        # cells - a workbook's last-saved values are what render to PDF; VBA only matters
        # if code RUNS, which we never need (a stray Workbook_Open could itself hang/prompt).
        # Written before launch because cfprefsd caches prefs for a running process.
        try:
            subprocess.run(
                ['defaults', 'write', 'com.microsoft.office',
                 'VisualBasicMacroExecutionState', '-string', 'DisabledWithoutWarnings'],
                capture_output=True, timeout=15,
            )
        except Exception:
            pass

    short_by_ms = {ms: short for _k, ms, short in _APP_TRIPLES}
    for app in apps:
        # Check for default installation path to prevent "Where is X?" dialogs
        if not Path(f"/Applications/{app}.app").exists():
            continue
        # ONE Office app per macOS user session, so LAUNCHING it is Office
        # automation exactly as converting is. Two instances priming at the
        # same moment drive one Excel - the crash this lock exists for. Held
        # per app for this app's warmup only, never across the whole loop.
        with _office_app_lock(app):
            try:
                # Launch hidden (-j) and without foregrounding (-g) so the app is
                # already running, off-screen, by the time conversions start.
                subprocess.run(
                    ['open', '-g', '-j', '-a', app],
                    capture_output=True, timeout=60,
                )
            except Exception:
                pass
            if touch_containers:
                # Pre-create the staging dir inside the app's sandbox container so
                # the macOS 15 "Canvas Downloader would like to access data from
                # other apps" prompt fires NOW (user is at the screen) rather than
                # at the first conversion. The container exists once the app has
                # launched (we just did); a missing container simply no-ops.
                try:
                    _office_container_tmp(short_by_ms.get(app, ''))
                except Exception:
                    pass
            answered = False
            try:
                # Harmless Apple Event → triggers the per-app Automation TCC prompt.
                # Returns rc 0 on Allow, -1743 on Deny; raises TimeoutExpired when
                # the prompt sat unanswered - only then is the app NOT recorded as
                # answered, so the next run re-batches it.
                subprocess.run(
                    ['osascript', '-e', f'tell application "{app}" to count windows'],
                    capture_output=True, timeout=120,
                )
                answered = True
            except Exception:
                pass
            # NOTE deliberately NO System Events hide here. `open -g -j` above has
            # already launched the app hidden, and the hide demanded Accessibility
            # while also hiding any Word/Excel/PowerPoint window the USER had open
            # themselves - see the measured note above TCC_FIRST_RUN_NOTICE.
            if app == "Microsoft Excel":
                # Best-effort suppression of the "this workbook contains links to
                # external sources" dialog. Done HERE, in its own isolated
                # osascript, NOT inline in the conversion script: if this Excel
                # build doesn't expose the property the statement is a COMPILE
                # error (-2741) that `try` can't catch - inline it would kill
                # every conversion. Isolated, a bad property name just no-ops.
                for _prop in ('ask to update links', 'ask to update automatic links'):
                    try:
                        subprocess.run(
                            ['osascript', '-e',
                             f'tell application "{app}" to set {_prop} to false'],
                            capture_output=True, timeout=15,
                        )
                    except Exception:
                        pass
            if answered and on_app_answered is not None:
                try:
                    on_app_answered(app)
                except Exception:
                    pass


def prime_office_automation(contract: dict) -> None:
    """Launch + permission-prime the Office apps upfront, hidden, during download.

    macOS shows a blocking "Canvas Downloader wants to control X" prompt the
    first time an Apple Event is sent to each app (and, separately, to System
    Events). Firing those harmless events in a background thread during the
    download phase batches ALL of the prompts before post-processing begins,
    warms up the heavy Office processes, and crucially launches them *hidden*
    so they never bounce the dock into the foreground.

    Also re-touches our container staging dirs (``touch_containers=True``):
    the macOS 15+ App Data consent is TRANSIENT (process lifetime - see
    arm_app_data_access), so unlike the Automation grants it must be re-armed
    every session, not just in the one-time first-run batch. The touch is
    silent when the session's consent already exists; when it doesn't, the
    prompt fires here (mid-download, user recently clicked Start) instead of
    hanging the first conversion.
    """
    import threading
    if sys.platform != 'darwin':
        return

    # Launch an app ONLY when its converter is enabled in *contract* AND it
    # hasn't already been primed this run. Pass a contract SCOPED to the files
    # actually present (office_contract_from_folder / get_synced_file_paths) so
    # a run that only converts PowerPoint never opens Word or Excel. Apps are
    # marked immediately (main thread) so a concurrent call can't double-launch
    # the same app.
    # WHO WAS ALREADY OPEN, recorded BEFORE we launch anything.
    #
    # Priming launches all three with `open -g -j`, so by the time the first
    # conversion asks, every app is running - launched by US - and the quit
    # gate would call them all the user's and never quit anything. Measured
    # exactly that in the real app on 2026-08-12, with all three killed
    # beforehand: "PowerPoint was already running before this run" and all
    # three left in the dock. The harness never saw it, because it drives the
    # converters directly and never primes.
    #
    # It sits ABOVE the `if not to_launch: return` on purpose: a run whose
    # courses hold no Office files still ends at a completion screen that calls
    # the teardown, and an unobserved app is one the teardown must leave alone.
    # Recording "we did not launch these" here is what makes that a decision
    # rather than an absence.
    observe_office_before_launch()

    to_launch = []
    for key, ms, _short in _APP_TRIPLES:
        if contract.get(key, False) and ms not in _primed_apps:
            _primed_apps.add(ms)
            to_launch.append(ms)
    if not to_launch:
        return

    global _macro_pref_written
    write_macro_pref = not _macro_pref_written
    if write_macro_pref:
        _macro_pref_written = True

    # Baseline the Dock recents BEFORE the first hidden launch, so the
    # completion-screen cleanup can tell our tiles from pre-existing ones.
    _snapshot_dock_recents()

    threading.Thread(
        target=_warmup_apps, args=(to_launch, write_macro_pref),
        kwargs={'touch_containers': True}, daemon=True,
    ).start()


def arm_app_data_access(contract: dict) -> None:
    """Fire this session's macOS 15+ "access data from other apps" prompt NOW.

    Conversions stage files inside the Office apps' own sandbox containers
    (office_container_stage), which macOS 15+ gates behind the App Data
    consent. Unlike the Automation grants, that consent is TRANSIENT: Apple
    DTS classifies the privilege as "transient, process lifetime" (dev forums
    thread 742147), so macOS forgets it the moment the app quits and re-asks
    once per app instance - no recording, signing identity, or first-run batch
    can make it stick. (Full Disk Access is the only durable bypass; the
    mac-setup guide documents it.)

    So the best available UX is to make the session's single prompt fire at
    RUN START - the user just clicked Start and is at the screen - by touching
    our staging dir inside every already-existing Office container. Consent is
    granted app-wide per instance, so one Allow covers all later staging AND
    the quit-time Recents purge in the Office group container. Runs on a
    daemon thread: a pending TCC consent BLOCKS the touching syscall until the
    user answers, and that must never freeze the run itself. Idempotent and
    silent when this session's consent (or Full Disk Access) already exists;
    containers that don't exist yet are skipped here and covered instead by
    the touch inside per-run priming, which runs right after the app launches.
    """
    if sys.platform != 'darwin':
        return
    if not any(contract.get(key, False) for key, _ms, _short in _APP_TRIPLES):
        return
    import threading

    def _touch_all():
        # The TCC dialog itself is invisible to us; the only observable is that
        # the first touch BLOCKS until the user answers. Log the duration so
        # debug_log.txt shows whether (and how long) the prompt was up.
        import time as _t
        t0 = _t.time()
        for _key, _ms, short in _APP_TRIPLES:
            try:
                _office_container_tmp(short)
            except Exception:
                pass
        took = _t.time() - t0
        logger.info(
            f"[Setup] App Data container arming finished in {took:.1f}s"
            + (" (consent prompt was likely shown)" if took > 2 else "")
        )

    threading.Thread(target=_touch_all, daemon=True).start()


# ── Full Disk Access (the permanent App Data silence) ───────────────
# FDA-granted apps are exempt from the macOS 15+ App Data check entirely - the
# only DURABLE way to kill the once-per-session "access data from other apps"
# prompt (see arm_app_data_access). These helpers back the Today page's
# "make it fully hands-off" nudge.

_FDA_SETTINGS_URL = (
    'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'
)


def is_macos_15_plus() -> bool:
    """True on macOS 15 Sequoia or newer - where App Data protection exists."""
    if sys.platform != 'darwin':
        return False
    try:
        import platform
        return int((platform.mac_ver()[0] or '0').split('.')[0]) >= 15
    except Exception:
        return False


def has_full_disk_access() -> bool:
    """Best-effort: does this app currently hold Full Disk Access?

    Reads one byte of the user TCC database - a file readable ONLY with FDA
    (kTCCServiceSystemPolicyAllFiles). Probing is silent by construction: FDA
    has no consent prompt (grants live solely in System Settings), so this can
    never pop a dialog. Un-cached on purpose - the user can flip the toggle in
    System Settings mid-session and the next rerun should notice. Any failure
    reports False (worst case: a granted user sees a dismissible nudge).
    """
    if sys.platform != 'darwin':
        return False
    try:
        tcc_db = (Path.home() / 'Library' / 'Application Support'
                  / 'com.apple.TCC' / 'TCC.db')
        with open(tcc_db, 'rb') as fh:
            fh.read(1)
        return True
    except Exception:
        return False


def open_full_disk_access_settings() -> None:
    """Open System Settings directly on Privacy & Security → Full Disk Access.

    The legacy prefpane anchor URL still deep-links correctly in the new
    System Settings (Ventura through Tahoe). Falls back to plainly launching
    System Settings if the anchor is ever rejected. Best-effort, never raises.
    """
    if sys.platform != 'darwin':
        return
    try:
        r = subprocess.run(['open', _FDA_SETTINGS_URL],
                           capture_output=True, timeout=15)
        if r.returncode == 0:
            return
    except Exception:
        pass
    try:
        subprocess.run(['open', '-b', 'com.apple.systempreferences'],
                       capture_output=True, timeout=15)
    except Exception:
        pass


# ── First-run batched permission setup ──────────────────────────────
# macOS asks for each Automation (TCC) consent the FIRST time the matching
# Apple event is actually sent. Left to chance - with priming scoped to the
# files each run happens to contain - those prompts surface mid-run, one app
# at a time, possibly across different days. Worse, an UNANSWERED prompt makes
# every conversion for that app hang until AppleScript's AppleEvent timeout
# (-1712), which is exactly how a user who stepped away lost 3 Excel files.
# This batch fires every outstanding prompt ONCE, at the start of the user's
# first conversion-enabled run - the one moment they are guaranteed to be at
# the screen, because they just clicked Start.
_first_run_batch_started = False  # at most one batch per process
_PERMISSION_RECORD_FILE = 'macos_permission_setup.json'


def _permission_record_path() -> Path:
    from shared.helpers import get_config_dir
    return Path(get_config_dir()) / _PERMISSION_RECORD_FILE


def _load_permission_record() -> dict:
    """Apps whose Automation prompt has been answered (Allow OR Deny) before.

    Total by design - every caller wants "which apps can I skip?", and the safe
    answer to a failed read is "none of them", i.e. re-batch. A read-modify-WRITE
    must use :func:`_load_permission_record_for_update` instead; see there.
    """
    rec, _ = _load_permission_record_for_update()
    return rec


def _load_permission_record_for_update() -> tuple:
    """``(record, may_write)`` - the same cause split every store in this app uses.

    Degrading a failed read to ``{}`` and writing it back is the defect this
    repo has fixed in seven other stores. Here the stake is small (the record
    only decides whether the one-time Office permission batch re-runs, and macOS
    will not re-prompt an already-answered pair), but the shape is identical:
    a transient read would drop the OTHER apps' answers and silently re-launch
    Word, Excel and PowerPoint on a later run.
    """
    from shared.helpers import read_json_for_update
    return read_json_for_update(_permission_record_path())


def _record_permission_answered(ms_name: str) -> None:
    """Persist that *ms_name*'s Automation prompt was answered (atomic write).

    A Deny is recorded too: macOS will not re-prompt a denied pair anyway, so
    re-batching would only churn app launches - the docs point denied users to
    System Settings → Privacy & Security → Automation instead.
    """
    import json
    import os
    try:
        rec, may_write = _load_permission_record_for_update()
        if not may_write:
            return
        rec[ms_name] = True
        path = _permission_record_path()
        tmp = path.with_name(path.name + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def first_run_permission_setup(contract: dict) -> bool:
    """Batch ALL outstanding macOS Office permission prompts at run start.

    *contract* is the UNscoped converter settings (the persistent_convert_*
    toggles) - deliberately not file-scoped: the whole point is to collect the
    prompts for every app the user will EVER need in one predictable moment,
    rather than letting each app's prompt ambush a later run (where an absent
    user means -1712 timeouts and skipped files).

    For each enabled converter whose app is installed and whose Automation
    prompt has never been answered, this launches the app hidden and fires the
    TCC-triggering events (plus the container-staging touch that hoists the
    macOS 15 "access data from other apps" prompt into the same batch - but
    NOTE: that consent is transient per app instance and re-armed each session
    by arm_app_data_access / per-run priming; only the Automation grants are
    what this batch settles durably). Answered apps are recorded in the config
    dir, so this is one-time per machine - NOT per run. Returns True when a batch was actually started, so
    the caller can show a heads-up banner; False otherwise (not macOS, nothing
    outstanding, already ran this process).
    """
    global _first_run_batch_started, _macro_pref_written
    if sys.platform != 'darwin':
        return False

    # WHO WAS ALREADY OPEN, before this function's own `open -g -j` batch.
    #
    # THIS FUNCTION IS A LAUNCHER TOO, and it is the EARLIER of the two - both
    # `app.py` and `sync/execution.py` call it at run start and reach
    # `prime_office_automation` only per course, later. It was missed when the
    # observation was hoisted into priming on 2026-08-12, so on a machine whose
    # Automation grants were not yet recorded - i.e. a new user's FIRST run -
    # the batch launched all three, the later observation saw our own launch,
    # every app read as the user's, nothing was quit, and (because all three
    # were running) the Recents purge declined as well. Reproduced against
    # these functions on 2026-08-13:
    #
    #     first-run batch ran: True;  alive after it: [Excel, PowerPoint, Word]
    #     gate 'this is the user's' -> {PowerPoint: True, Word: True, Excel: True}
    #     >> apps this run will QUIT: NONE
    #
    # ABOVE the `_first_run_batch_started` guard, not below it: that flag is
    # once per PROCESS while `_office_preexisting` is now once per RUN, so a
    # second run must still be able to take its observation here - at run start,
    # which is the earliest moment either flow touches Office.
    observe_office_before_launch()

    if _first_run_batch_started:
        return False
    record = _load_permission_record()
    wanted = []
    for key, ms, _short in _APP_TRIPLES:
        if not contract.get(key, False):
            continue
        if record.get(ms):
            continue
        if not Path(f"/Applications/{ms}.app").exists():
            continue
        wanted.append(ms)
    if not wanted:
        return False
    _first_run_batch_started = True
    # Mark as primed for this run so the scoped per-course priming doesn't
    # re-launch what the batch is already warming up.
    _primed_apps.update(wanted)
    write_macro_pref = not _macro_pref_written
    _macro_pref_written = True

    # Baseline the Dock recents BEFORE the first hidden launch (see
    # _snapshot_dock_recents) - the batch is about to launch every wanted app.
    _snapshot_dock_recents()

    import threading
    threading.Thread(
        target=_warmup_apps,
        args=(wanted, write_macro_pref),
        kwargs={'touch_containers': True, 'on_app_answered': _record_permission_answered},
        daemon=True,
    ).start()
    logger.info(f"[Setup] First-run macOS permission batch started for: {', '.join(wanted)}")
    return True

