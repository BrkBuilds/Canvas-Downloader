"""
Post-Processing Pipeline for Canvas Downloader
Unified conversion logic shared between Download (app.py) and Sync (sync_ui.py) flows.

Eliminates ~800 lines of duplicated code by providing:
  - UIBridge: Abstracts Streamlit placeholder references between callers
  - Individual run_* functions: One per converter type
  - run_all_conversions: Convenience entry point for the Download flow (globs + runs all)
  - Consistent DB updates via SyncManager (fixes raw-sqlite3 audit bug)
"""

import glob
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional

from shared import theme
from shared.helpers import esc, make_long_path
from shared.shortcuts import is_produced_shortcut
from engine.estimation import stepwise_estimator
from engine.progress_dashboard import (
    render_active_file, build_terminal_html, build_metrics_row, build_progress_bar_html,
    metric_count, metric_eta, metric_value,
    log_line, log_divider, log_meta, file_icon_svg,
)

logger = logging.getLogger(__name__)

# ── Color map per conversion type for dashboard accent ──
_COLOR_MAP = {
    'Archives':           '#a78bfa',
    'PowerPoint files':   '#f97316',
    'HTML files':         '#34D399',
    'Code files':         '#FBBF24',
    'Legacy Word files':  theme.BLUE_PRIMARY,
    'Excel files':        '#22c55e',
    'Excel data files':   '#14b8a6',
    'Video files':        theme.WARNING,
}

# Starting guess at seconds-per-file, per conversion type. These differ by more
# than an order of magnitude - launching Word through COM to print one page is
# not the same job as rewriting an HTML file as Markdown - so one shared prior
# would be wrong for every task. Each is only a starting point: the estimator
# replaces it with the measured rate after the first couple of files, which is
# what makes a 200-file PowerPoint batch predictable on a slow machine and on a
# fast one alike.
_TASK_PRIOR_SEC = {
    'Archives':           1.5,
    'PowerPoint files':   6.0,
    'HTML files':         0.3,
    'Code files':         0.2,
    'Legacy Word files':  5.0,
    'Excel data files':   1.5,
    'Excel files':        5.0,
    'Video files':        8.0,
}


@dataclass
class UIBridge:
    """Abstracts Streamlit placeholder references between Download and Sync flows.

    Each caller passes its own placeholder objects and cancel-check callable.
    app.py  passes: header_placeholder, progress_placeholder, metrics_placeholder, log_placeholder, ...
    sync_ui passes: status_text,        progress_container,   metrics_dashboard,    log_container, ...
    """
    header_placeholder: Any
    progress_placeholder: Any
    metrics_placeholder: Any
    log_placeholder: Any
    active_file_placeholder: Any
    log_lines: Any  # mutable list or deque of HTML log strings
    is_cancelled: Callable[[], bool] = field(default_factory=lambda: lambda: False)
    on_detail_update: Optional[Callable] = None   # (context, old_name, new_name)
    error_log_path: Optional[Path] = None
    pp_success_count: int = 0   # Post-processing files converted successfully
    pp_failure_count: int = 0   # Post-processing files that failed conversion
    # Archives the file-count guard declined to unpack. Carried here rather
    # than emitted only to the log: the post-processing terminal scrolls away
    # and is gone by the time the user reads the completion screen, so a
    # silent guard produces exactly one question - "why is my zip still a
    # zip?". Both flows already copy bridge counters back into session state.
    archives_skipped: list = field(default_factory=list)
    # Time-remaining state, owned here so all 19 _render_dashboard call sites
    # keep their existing signature. Rebuilt whenever the task changes - each
    # conversion type is its own phase with its own per-file cost.
    _eta_task: str = ''
    _eta: Any = None
    generated_sidecar_paths: list = field(default_factory=list)  # _Data.txt paths for UI ledger injection
    # Phases that ABORTED on a FATAL AppleScript category (Automation denied,
    # Office not installed). Written by `_abort_applescript_phase`, read by
    # `retry_failed_conversions` - see its docstring for why a retry there is
    # not merely wasted but actively contradicts the abort.
    aborted_phases: set = field(default_factory=set)


# ─────────────────────────────────────────────────────
# Shared UI Rendering Helpers
# ─────────────────────────────────────────────────────

def _render_dashboard(ui: UIBridge, current: int, total: int, task_name: str):
    """Render the post-processing progress dashboard into the caller's placeholders."""
    try:
        if ui.is_cancelled():
            return
        accent = _COLOR_MAP.get(task_name, theme.SUCCESS)
        pct = min(100, int((current / total) * 100) if total > 0 else 0)

        # Map internal task names to detailed from → to descriptions for headers and metric cards
        # Heading copy: NO file-extension parentheticals here - the exact
        # formats live in the "Type" metric (type_name_map) below, so repeating
        # them in the H3 only bloats it. Keep these clean and human.
        display_name_map = {
            'Archives':           'Archives to Folders',
            'PowerPoint files':   'PowerPoint to PDF',
            'HTML files':         'HTML Pages to Markdown',
            'Code files':         'Code & Data files to Text',
            'Legacy Word files':  'Legacy Word to PDF',
            'Excel data files':   'Excel to AI Data',
            'Excel files':        'Excel to PDF',
            'Video files':        'Video to Audio',
        }
        
        type_name_map = {
            'Archives':           'ZIP/TAR → Folders',
            'PowerPoint files':   'PPTX/PPT → PDF',
            'HTML files':         'HTML → MD',
            'Code files':         'Code/Data → TXT',
            'Legacy Word files':  'DOC/RTF → PDF',
            'Excel data files':   'XLSX → AI Data',
            'Excel files':        'XLSX/XLS → PDF',
            'Video files':        'Video → MP3',
        }

        display_name = display_name_map.get(task_name, task_name)
        type_name = type_name_map.get(task_name, task_name)
        action_verb = 'Extracting' if task_name in ('Archives', 'Excel data files') else 'Converting'

        ui.header_placeholder.markdown(f'''
        <div style="margin-bottom: 0.5rem;">
            <p style="margin: 0; font-size: 0.8rem; color: {theme.TEXT_SECONDARY}; text-transform: uppercase;">Post-Processing</p>
            <h3 style="margin: 0; padding-top: 0.1rem; color: {theme.TEXT_PRIMARY};">{action_verb} {esc(display_name)}</h3>
        </div>
        ''', unsafe_allow_html=True)

        ui.progress_placeholder.markdown(
            build_progress_bar_html(pct, color=accent), unsafe_allow_html=True)

        # A fresh estimator per conversion type: a batch of Word documents and a
        # batch of code files have per-file costs an order of magnitude apart, so
        # carrying one across the boundary would mis-price the new task for as
        # long as the old task's samples stayed in the window.
        if ui._eta is None or ui._eta_task != task_name:
            ui._eta_task = task_name
            ui._eta = stepwise_estimator(_TASK_PRIOR_SEC.get(task_name, 2.0))
        ui._eta.update(units_done=current, units_total=total)

        ui.metrics_placeholder.markdown(build_metrics_row([
            metric_count('Converted', current, total, accent=accent),
            metric_value('Type', type_name, accent),
            metric_eta(ui._eta.eta_text()),
        ]), unsafe_allow_html=True)

        # Re-render log so it stays in sync with progress/metrics
        ui.log_placeholder.markdown(build_terminal_html(ui.log_lines), unsafe_allow_html=True)

        time.sleep(0.05)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.debug(f"_render_dashboard swallowed: {type(e).__name__}: {e}")


def _log_msg(ui: UIBridge, msg: str, *, is_error: bool = False):
    """Append a pre-built log-line HTML string, mirror to the Python logger, and re-render."""
    try:
        if ui.is_cancelled():
            return
        plain = re.sub(r'<[^>]+>', ' ', msg).strip()
        if is_error:
            logger.error(plain)
        else:
            logger.info(plain)

        ui.log_lines.append(msg)
        ui.log_placeholder.markdown(build_terminal_html(ui.log_lines), unsafe_allow_html=True)
    except Exception as e:
        logger.debug(f"_log_msg swallowed: {type(e).__name__}: {e}")


def _emit(ui: UIBridge, status: str, text: str, *, filename: str | None = None,
          detail: str | None = None):
    """Build and append one unified post-processing log line.

    status: 'success' | 'error' | 'attention' | 'skip'  -> a normal log row
            'divider'                                    -> a centered phase break
            'meta'                                       -> a quiet centered note
    filename (optional) selects the content-type icon for normal rows.
    """
    if status == 'divider':
        line = log_divider(text)
    elif status == 'meta':
        line = log_meta(text)
    else:
        icon = file_icon_svg(filename) if filename else None
        line = log_line(status, text, icon=icon, detail=detail)
    _log_msg(ui, line, is_error=(status == 'error'))


def _show_active_file(ui: UIBridge, filename: str):
    """Update the active-file indicator during post-processing."""
    try:
        render_active_file(ui.active_file_placeholder, filename, phase='postprocess')
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        pass


# ─────────────────────────────────────────────────────
# Database & Error Helpers
# ─────────────────────────────────────────────────────

def _target_protected(sm, path: Path) -> bool:
    """Did THIS sync run classify this conversion output as locally edited?

    The authoritative signal, and the only one that works on a folder created
    before the product hash was recorded: the analyzer compared the tracked
    file against its manifest md5 to classify the update in the first place,
    and ``sync/execution.py`` passes that verdict straight through. The hash
    check below is the durable backstop for runs where no such verdict exists.
    """
    try:
        return bool(sm is not None and sm.is_conversion_target_protected(path))
    except Exception:
        return False


def _product_locally_edited(prod_path: Path, recorded_md5: str) -> bool:
    """Has the student changed the app's own conversion output since it wrote it?

    Compared against the hash stored WITH the product record, not against the
    manifest row: by the time a re-conversion runs, that row has been
    re-pointed at the freshly downloaded source, so its md5 describes the
    source and says nothing about the output.

    No recorded hash means a folder converted by an older version. Those get
    the previous behaviour - overwrite in place - because inventing a
    ``_NewVersion`` for every pre-existing product on the next sync would be a
    worse surprise than the one being fixed. They gain the guard as soon as one
    conversion has run under this version.
    """
    if not recorded_md5 or not prod_path.exists():
        return False
    try:
        from core.sync_manager import SyncManager
        return (SyncManager.compute_local_md5(prod_path) or "") != recorded_md5
    except Exception as e:                      # never block a conversion
        logger.debug(f"could not hash conversion product {prod_path}: {e}")
        return False


def _new_version_name(path: Path) -> Path:
    """``<stem>_NewVersion<ext>``, free, beside the file it protects."""
    cand = path.parent / f"{path.stem}_NewVersion{path.suffix}"
    n = 1
    while cand.exists():
        cand = path.parent / f"{path.stem}_NewVersion ({n}){path.suffix}"
        n += 1
    return cand


def _resolve_conversion_target(sm, src_path, target_ext: str,
                               default_name: str | None = None):
    """Pick the OUTPUT path for converting *src_path* (H-7 collision guard).

    Default target is ``<stem><target_ext>`` beside the source. If that file
    already exists, overwriting is allowed ONLY when the manifest proves it is
    this entry's OWN previous conversion product (recorded by
    ``update_converted_file``); anything else - a teacher-provided X.pdf next
    to X.pptx, an X.xlsx whose PDF would collide with X.pptx's, the user's own
    file - diverts to the first free ``<stem> (n)<target_ext>``. The recorded
    product makes the diverted name STABLE across future updates (the next
    re-conversion overwrites its own ``X (1).pdf`` instead of minting X (2)).
    """
    src = Path(src_path)
    # `default_name` exists for converters whose output is not a plain suffix
    # swap: convert_code writes `<stem>_<ext>.txt`, so with_suffix would have
    # named the wrong file and the guard below would have protected nothing.
    default = (src.with_name(default_name) if default_name
               else src.with_suffix(target_ext))

    if sm is not None:
        # Same spelling problem as the repoint below, and here it costs MORE
        # than bookkeeping: failing to find the row loses the "own product"
        # ownership check, so the fallback plain-suffix name can overwrite a
        # file this entry does not own - including a PDF the student has since
        # annotated. See ``_course_relative``.
        src_rel = _course_relative(sm, src)
        if src_rel is not None:
            try:
                manifest = sm.load_manifest()
                row_id = None
                for fid, info in manifest.get('files', {}).items():
                    if info.get('local_path', '') == src_rel:
                        row_id = fid
                        break
                if row_id is not None:
                    from core.sync_manager import SyncManager as _SM
                    prod_rel, prod_md5 = _SM.conversion_product(
                        sm.get_conversion_products().get(str(row_id), ''))
                    if prod_rel:
                        prod_path = sm.local_path / prod_rel
                        # "Beside the source" is compared in COURSE-RELATIVE
                        # terms, not as absolute paths. `prod_path` is always
                        # built from `sm.local_path` while `src` carries
                        # whatever spelling its caller used, so comparing the
                        # absolute parents re-introduces exactly the mismatch
                        # `_course_relative` exists to remove - and silently, in
                        # the branch that protects an annotated PDF.
                        if (prod_path.suffix.lower() == target_ext.lower()
                                and PurePosixPath(prod_rel).parent
                                == PurePosixPath(src_rel).parent):
                            # OWN product - but only if the student has not
                            # since edited it. `_NewVersion` protects the file
                            # the DOWNLOAD would replace; a converted file is
                            # replaced by post-processing instead, and that
                            # path had no such guard. Measured on sync row
                            # s001: hints.md (0cf8870d -> 44b3b792) and
                            # Create_ILearn_tables_sql.txt (1e213dd3 ->
                            # d18bff9a) were both regenerated straight over the
                            # student's annotations, with no _NewVersion
                            # sibling anywhere - the one thing the feature
                            # exists to prevent.
                            if (_target_protected(sm, prod_path)
                                    or _product_locally_edited(prod_path, prod_md5)):
                                alt = _new_version_name(prod_path)
                                logger.info(
                                    f"Conversion target '{prod_path.name}' has "
                                    f"local edits - writing the new copy to "
                                    f"'{alt.name}' instead.")
                                return alt
                            return prod_path  # own product → overwrite in place
            except Exception as e:
                logger.debug(f"_resolve_conversion_target ownership lookup failed: {e}")

    if not default.exists():
        return default
    n = 1
    while True:
        cand = default.parent / f"{default.stem} ({n}){default.suffix}"
        if not cand.exists():
            logger.info(
                f"Conversion target '{default.name}' exists and is not this file's "
                f"own product - diverting to '{cand.name}' (H-7)."
            )
            return cand
        n += 1


def _course_relative(sm, path) -> str | None:
    """The manifest's spelling of *path*, or None if it is genuinely outside.

    THE MANIFEST KEYS ROWS ON A PATH RELATIVE TO THE COURSE FOLDER, so every
    lookup in this module has to reproduce that spelling exactly.
    ``Path.relative_to`` is a pure STRING operation, and the two sides do not
    always arrive spelled the same way: ``converters/pdf.py`` and
    ``converters/word.py`` both return ``str(dst.resolve())`` from their macOS
    branch while ``converters/excel.py`` returns ``str(dst)``, and
    ``sm.local_path`` carries whatever spelling the destination was configured
    with. On any root reached through a symlink - ``/tmp`` -> ``/private/tmp``,
    or a course folder linked onto an external drive - the resolved and
    unresolved spellings differ, ``relative_to`` raises, and the callers used to
    swallow that in SILENCE.

    Measured 2026-08-21 in a real packaged run of course 43660: **62 of 63
    Office conversions left their manifest row pointing at the source file they
    had just deleted**, and the one converter that repointed correctly was the
    only one that does not call ``resolve()``. Nothing was logged, on either
    path. So the fallback compares REAL paths - the one spelling both sides can
    always agree on - and the callers now say so when even that fails.

    ``os.path.realpath`` is used rather than ``Path.resolve`` because it is
    defined on a path that no longer EXISTS, which ``original_file`` never does
    by the time the repoint runs: every source-consuming converter deletes its
    source before reporting success.
    """
    root = getattr(sm, "local_path", None)
    if root is None:
        return None
    p = Path(path)
    candidates = ((p, Path(root)),
                  (Path(os.path.realpath(p)), Path(os.path.realpath(root))))
    for cand, cand_root in candidates:
        try:
            return str(cand.relative_to(cand_root)).replace('\\', '/')
        except (ValueError, AttributeError, OSError):
            continue
    return None


def _update_manifest_path(sm, original_file: Path, converted_path: Path):
    """Update the sync manifest to point from the original file to the converted file.

    Uses SyncManager exclusively - no raw sqlite3.  Fixes the audit inconsistency.
    """
    original_rel = _course_relative(sm, original_file)
    new_rel = _course_relative(sm, converted_path)
    if original_rel is None or new_rel is None:
        # Not a crash and not data loss - the file IS converted - but the sync
        # record is now stale, and a stale row is re-offered as a restore on the
        # next sync while its product sits untracked. Silence here is what let
        # that ship, so it is stated.
        logger.warning(
            "Could not place %s / %s inside the course folder %s, so the "
            "manifest was not repointed. The file was converted; only the sync "
            "record is stale.",
            original_file, converted_path, getattr(sm, "local_path", None))
        return

    # BOOKKEEPING MUST NOT UNDO WORK THAT ALREADY SUCCEEDED. By the time this
    # runs the converted file is on disk and the original is gone; the only
    # thing left is repointing a manifest row. `load_manifest` deliberately
    # RE-RAISES database errors ("Aborting to prevent data loss"), and none of
    # the conversion runners has a per-item handler - so a manifest that was
    # briefly locked (antivirus, or the sync that just finished writing to it)
    # aborted the whole conversion phase mid-way, leaving the remaining files
    # unconverted, the active-file line stuck on the last one, and the phase's
    # own "complete" message never emitted.
    #
    # The cost of swallowing it is one stale manifest row, which the next sync's
    # heal pass fixes; the cost of propagating it is every later file in the
    # phase. Logged, never silent.
    try:
        manifest = sm.load_manifest()
        for file_id, info in manifest.get('files', {}).items():
            if info.get('local_path', '') == original_rel:
                sm.update_converted_file(int(file_id), new_rel)
                break
        else:
            # A conversion whose source was never tracked is ORDINARY - an
            # extracted archive member, a secondary-content render - so this is
            # not an error. It is logged at debug because "no row matched" and
            # "the row was repointed" were previously indistinguishable from
            # outside, which is exactly what made a spelling mismatch invisible.
            logger.debug(
                "No manifest row for %s; nothing to repoint to %s.",
                original_rel, new_rel)
    except Exception as e:
        logger.warning(
            "Could not repoint the manifest from %s to %s (%s: %s). The file was "
            "converted; only the sync record is stale.",
            original_rel, new_rel, type(e).__name__, e)


def _is_locked(path: Path) -> bool:
    """True when *path* exists but cannot be opened for writing.

    The classic case is a converted file the student still has open in an
    editor or in Word. Opened in append mode so nothing is ever truncated by
    the probe itself, and a missing file is NOT locked - it is simply absent.
    """
    try:
        if not path.is_file():
            return False
        # Binary append: the probe writes nothing and reads nothing, so no text
        # decoder should be involved - and a file whose bytes are not valid
        # UTF-8 must still be probeable.
        with open(path, "ab"):
            return False
    except OSError:
        return True


def _locked_sibling(src: Path) -> Path | None:
    """A locked file that a converter would plausibly have been writing.

    Every converter names its output from the SOURCE stem, in the source's own
    folder (``code.py`` -> ``code_py.txt``, ``slides.pptx`` -> ``slides.pdf``).
    So when a conversion fails, a locked file sharing that stem is almost
    certainly the destination it could not write. Probing for it means the
    reason can be reported without every runner having to know its own output
    naming rule - and it reports a file that demonstrably IS locked, rather
    than guessing at a cause.
    """
    try:
        for sib in src.parent.glob(glob.escape(src.stem) + "*"):
            if sib.is_file() and sib != src and _is_locked(sib):
                return sib
    except OSError:
        pass
    return None


#: Runner function name -> the phase label its `_abort_applescript_phase` call
#: uses. Written here rather than derived, because the label is what the ABORT
#: already carries and deriving it twice is how the two would drift apart.
_RUNNER_PHASE = {
    "run_word_conversion": "Word",
    "run_excel_conversion": "Excel",
    "run_pptx_conversion": "PowerPoint",
}


def retry_failed_conversions(attempts: list, ui: UIBridge) -> list:
    """One retry pass over conversions whose source is still on disk.

    Every source-consuming converter DELETES its source on success, so a source
    still present after a pass is exactly the set that failed - a uniform signal
    that needs no cooperation from the nine individual runners.

    Most conversion failures are transient: a destination locked for a few
    seconds by an editor, an antivirus scanner holding a handle, a COM hiccup.
    Retrying once costs a single extra attempt per failed file and turns a large
    share of them into successes the user never has to think about. Whatever
    fails TWICE gets a message naming the cause where it can be established.

    ``attempts`` is ``[(runner, items), ...]`` in the order they first ran; each
    ``items`` is the runner's own ``[(path, sm, ctx), ...]``. Returns the items
    that failed both times.

    A phase that ABORTED for a FATAL reason is skipped, and that is not an
    optimisation - retrying it directly contradicts the abort. `permission`
    (Automation denied) and `app_missing` are in `FATAL_CATEGORIES` precisely
    because they "will identically doom every remaining file in the phase", so
    the second attempt cannot succeed; what it does instead is emit the one
    actionable message a SECOND time - defeating the whole point of
    `_abort_applescript_phase` - and then label the file "Conversion failed
    twice", which blames the document for a machine-wide permission state.

    Measured in the PACKAGED app on macOS 26.6.1 with Automation for Microsoft
    Word genuinely denied (2026-08-20): 3 per-file errors and 2 aborts for ONE
    `.doc`, corroborated independently by the health record's
    `failures={'osascript_permission': 2}`.

    The skip is per PHASE, not global: a Word denial says nothing about the
    HTML-to-Markdown runner, which uses no AppleScript at all, and `permission`
    is granted per (client, target app) so it says nothing about Excel either.
    Only the phase that actually aborted stands down.
    """
    _aborted = getattr(ui, "aborted_phases", None) or set()

    def _phase_aborted(runner) -> bool:
        return _RUNNER_PHASE.get(getattr(runner, "__name__", "")) in _aborted

    for runner, items in attempts:
        if _phase_aborted(runner) and items:
            logger.info("Not retrying %d %s file(s): the phase aborted on a "
                        "fatal condition (%s), which a second attempt cannot "
                        "change.", len(items),
                        _RUNNER_PHASE.get(getattr(runner, "__name__", "")),
                        ", ".join(sorted(_aborted)))
    attempts = [(r, items) for r, items in attempts if not _phase_aborted(r)]

    pending = [(runner, [it for it in items if _still_present(it)])
               for runner, items in attempts]
    pending = [(r, items) for r, items in pending if items]
    if not pending:
        return []

    n = sum(len(items) for _r, items in pending)
    _emit(ui, 'divider', f"Retrying {n} file{'s' if n != 1 else ''} that could "
                         f"not be converted")
    for runner, items in pending:
        try:
            runner(items, ui)
        except Exception as e:                      # never let a retry kill the run
            logger.warning("Conversion retry failed for %d item(s): %s", len(items), e)

    recovered, still = [], []
    for _runner, items in pending:
        for it in items:
            (still if _still_present(it) else recovered).append(it)

    # Accounting: pass 1 counted every `pending` item as a failure, and the
    # retry counted the ones that failed again. Remove both, leaving exactly one
    # failure per file that is genuinely still unconverted.
    ui.pp_failure_count = max(0, ui.pp_failure_count - (len(recovered) + len(still)))

    for it in still:
        src = Path(it[0]) if not isinstance(it[0], Path) else it[0]
        locked = _locked_sibling(src)
        if locked:
            detail = f"'{locked.name}' is open in another program"
            msg = (f"Could not be converted - '{locked.name}' is open in another "
                   f"program. Close it and sync again.")
        else:
            detail = "Conversion failed twice"
            msg = "Could not be converted (retried once)."
        _emit(ui, 'error', src.name, filename=src.name, detail=detail)
        _log_error_to_file(ui.error_log_path, src.name, msg)
    if recovered:
        _emit(ui, 'meta', f"{len(recovered)} recovered on retry")
    return still


def _run_phase(runner, items, ui) -> bool:
    """Run ONE conversion phase, absorbing anything it raises. Returns success.

    The nine ``run_*`` runners are siblings, and a failure in one says nothing
    about the next: a wedged COM server has no bearing on HTML→Markdown. But
    only ``run_excel_data_conversion`` had a per-item handler, and
    ``run_all_conversions`` called them all bare - so ONE unexpected exception
    anywhere took down every phase after it AND ``retry_failed_conversions``,
    which is the thing that would otherwise have recovered the files.

    One guard here rather than nine inside the runners: it is the boundary the
    phases are already independent across, it cannot be forgotten when a tenth
    converter is added, and it mirrors the handler ``retry_failed_conversions``
    already uses for exactly the same reason.
    """
    try:
        runner(items, ui)
        return True
    except Exception as e:
        label = runner.__name__.replace('run_', '').replace('_', ' ')
        logger.error("Conversion phase %s failed: %s", runner.__name__, e, exc_info=True)
        try:
            _emit(ui, 'error', f"{label} stopped early", detail=str(e))
        except Exception:
            pass
        # The runner clears this on its normal exit; on this path it would stay
        # stuck on whichever file was in flight when it blew up.
        try:
            ui.active_file_placeholder.empty()
        except Exception:
            pass
        return False


def _still_present(item) -> bool:
    """Did this conversion's SOURCE survive the pass (i.e. did it fail)?

    An empty path is not "present": ``Path("").exists()`` is True because it
    resolves to the current directory, which would make a malformed item look
    like a permanently failing file and put it in every retry pass for ever.
    """
    try:
        p = item[0] if not isinstance(item, (str, Path)) else item
        if not p or not str(p).strip():
            return False
        return Path(p).is_file()
    except (OSError, IndexError, TypeError):
        return False


def _log_error_to_file(error_log_path: Path | None, filename: str, error_msg: str):
    """Write a post-processing error to download_errors.txt."""
    if error_log_path is None:
        return
    from datetime import datetime
    from shared.helpers import _err_log_lock
    err_file = error_log_path / "download_errors.txt"
    try:
        error_log_path.mkdir(parents=True, exist_ok=True)
        with _err_log_lock:
            with open(err_file, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] [Post-Processing] {filename}: {error_msg}\n")
    except OSError as e:
        # The UI tells the user "Check download_errors.txt for details", so a
        # dropped line means they open a file that does not contain their error.
        # Mirror it into the application log so the detail still exists somewhere.
        logger.warning(
            "Could not append to %s (%s). Post-processing error for '%s' was: %s",
            err_file, e, filename, error_msg,
        )


def _applescript_last_error() -> tuple[str, str | None]:
    """Describe the most recent macOS AppleScript conversion failure.

    Returns (per_file_suffix, fatal_phase_message). per_file_suffix is
    appended to the generic "Conversion failed" line so the user sees the
    real reason (timeout, permission, ...). fatal_phase_message is non-None
    for failures that will identically doom every remaining file in the
    phase (Automation/TCC permission denied, Office app missing) - callers
    abort early with one actionable message instead of spamming dozens of
    generic errors.
    """
    if sys.platform != 'darwin':
        return '', None
    try:
        from engine.applescript_bridge import get_last_error, FATAL_CATEGORIES
    except ImportError:
        return '', None
    last = get_last_error()
    if not last:
        return '', None
    category, detail = last
    short = detail if len(detail) <= 160 else detail[:157] + '…'
    fatal = detail if category in FATAL_CATEGORIES else None

    # A per-file category that has REPEATED is systemic - the app is wedged and
    # every remaining file will fail identically. See SYSTEMIC_REPEAT_THRESHOLD
    # in engine.applescript_bridge for the measurement (a corrupt .doc leaves
    # Word on a modal alert, after which -1708 answers everything, including
    # files that converted seconds earlier).
    if fatal is None:
        try:
            from engine.applescript_bridge import systemic_failure
            repeat = systemic_failure()
        except ImportError:
            repeat = None
        if repeat:
            app, count = repeat
            fatal = (
                f"Microsoft {app} failed on {count} files in a row with the same "
                f"error ({short.strip(' -')}). It is most likely waiting on a "
                f"dialog and will not convert anything else this run. Quit "
                f"Microsoft {app} and run again to convert the rest."
            )
    return f" - {short}", fatal


def _abort_applescript_phase(ui: UIBridge, fatal_msg: str, remaining: int, phase_label: str) -> None:
    """Log a single actionable message and mark the remaining files as skipped.

    Records *phase_label* on the bridge so the retry pass can decline to run
    this phase again. Measured on macOS 26.6.1 with Automation for Word really
    denied: without it the retry re-ran the phase, the actionable message was
    emitted TWICE, and the file ended up labelled "Conversion failed twice" -
    which blames the document for a machine-wide permission state.
    """
    if remaining > 0:
        ui.pp_failure_count += remaining
    try:
        ui.aborted_phases.add(phase_label)
    except AttributeError:
        # A caller passing a stand-in bridge (tests, sync's own UI shim) must
        # never be broken by bookkeeping - the retry simply stays as it was.
        pass
    _emit(ui, 'error', fatal_msg, detail=f"skipping remaining {remaining} {phase_label} file(s)")


# ─────────────────────────────────────────────────────
# Individual Converter Runners
#
# Each accepts:
#   files: list of (Path, SyncManager, context)
#     - context is opaque; passed back to on_detail_update
#     - app.py passes None; sync_ui passes pair_idx
#   ui: UIBridge
# ─────────────────────────────────────────────────────

def run_archive_extraction(files, ui: UIBridge) -> list:
    """Extract archives (.zip, .tar, .tar.gz).

    Returns the extraction ROOT directory of every archive that unpacked
    successfully - but NOTHING CONSUMES IT, and that is deliberate. A zip is
    unpacked and its contents are then left exactly as they are; no converter
    ever runs over what came out of one, in either the download or the sync
    flow. ``run_all_conversions`` drops this return value on purpose and its
    "NOTE ON ARCHIVES" records the measurements behind the 2026-07-29 reversal
    (one lecture zip: 21,824 files out, 9,730 past Windows' 260-char limit,
    and PowerPoint COM rejecting long paths and the long-path prefix alike).

    Do not wire these roots back into ``_glob_files`` without re-reading that
    note: a source-consuming converter DELETES its input, so doing so turns a
    student's own .js inside their own project into something else.

    The value is still returned because it is the honest result of the work,
    and a caller that ever needs it (a progress line, a report) should not have
    to re-derive it - see ``tests/test_archive_conversion_scope.py``.
    """
    if not files:
        return []
    try:
        from converters.archive import extract_archive
    except ImportError as _imp_err:
        logger.error(f"archive_extractor unavailable: {_imp_err}")
        _emit(ui, 'error', "Archive extraction unavailable: module not found", detail=str(_imp_err))
        return []
    # THE one place both flows converge. The download flow arrives via
    # run_all_conversions and the sync flow calls this function directly, so a
    # guard read here applies to both by construction - whereas a value passed
    # in by each caller is a value that can differ between them, and a modifier
    # that silently means something different in sync than in download is worse
    # than no modifier at all.
    from shared.helpers import archive_file_limit
    _max_files = archive_file_limit()
    extracted_roots = []
    skipped_big: list = []

    total = len(files)
    _emit(ui, 'divider', f"Extracting {total} archive files")
    _render_dashboard(ui, 0, total, "Archives")
    time.sleep(0.2)

    for i, (archive_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break
        old_name = archive_file.name
        _show_active_file(ui, old_name)

        success = extract_archive(archive_file, max_files=_max_files)

        if success is False:
            # DECLINED, not failed. The archive is untouched and still on disk,
            # so the user has lost nothing and can extract it themselves - which
            # is the whole point of a guard rather than a hard limit. It must not
            # touch pp_failure_count: that drives the "some conversions failed"
            # warning, and a setting doing its job is not a failure.
            skipped_big.append(old_name)
            # Name AND size, because the completion screen lists these the same
            # way it lists size-skipped files - filetype icon, extension tag,
            # size - and the size is only knowable here, while the file is
            # still in hand. Read defensively: a guard reporting what it left
            # alone must never be the thing that raises.
            try:
                _bytes = os.path.getsize(make_long_path(archive_file))
            except OSError:
                _bytes = 0
            ui.archives_skipped.append({'name': old_name, 'bytes': _bytes})
            _emit(ui, 'skip', old_name, filename=old_name,
                  detail=f'Skipped: more than {_max_files:,} files inside')
            _render_dashboard(ui, i, total, "Archives")
            continue

        if success:
            # No manifest update needed - the Sync Engine bypass will
            # silently ignore the missing archive on future sync runs.
            _emit(ui, 'success', old_name, filename=old_name)
            ui.pp_success_count += 1
            # Mirrors extract_archive's own naming: .tar.gz strips seven
            # characters, everything else drops a single suffix.
            if old_name.lower().endswith('.tar.gz'):
                root = archive_file.with_name(old_name[:-7])
            else:
                root = archive_file.with_suffix('')
            if root.is_dir():
                # The companion values (sync manager, and course name or pair
                # index depending on the caller) ride along so the SYNC flow can
                # rebuild its own (path, sm, pair_idx) tuples without having to
                # re-derive which pair an archive belonged to.
                extracted_roots.append((root, sm, ctx))
        else:
            _emit(ui, 'error', old_name, filename=old_name, detail='Extraction failed')
            _log_error_to_file(ui.error_log_path, old_name, "Archive extraction failed")
            ui.pp_failure_count += 1
        _render_dashboard(ui, i, total, "Archives")

    # Say it once, plainly, at the end. A per-archive skip line scrolls away in
    # a long run, and "why is my zip still a zip?" is exactly the question a
    # silent guard creates.
    if skipped_big:
        _n = len(skipped_big)
        _emit(ui, 'meta',
              f"{_n} archive{'s were' if _n != 1 else ' was'} left unextracted "
              f"(more than {_max_files:,} files inside). "
              f"The .zip {'files are' if _n != 1 else 'file is'} still in your "
              f"course folder.")
    _emit(ui, 'meta', "Archive extraction complete")
    ui.active_file_placeholder.empty()
    return extracted_roots


def run_pptx_conversion(files, ui: UIBridge):
    """Convert PowerPoint files to PDF."""
    if not files:
        return
    try:
        from converters.pdf import PowerPointToPDF
    except ImportError as _imp_err:
        logger.error(f"pdf_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "PowerPoint conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    pptx_error_log = ui.error_log_path

    _emit(ui, 'divider', f"Converting {total} PowerPoint files to PDF")
    _render_dashboard(ui, 0, total, "PowerPoint files")
    time.sleep(0.2)

    with PowerPointToPDF(error_log_path=pptx_error_log) as converter:
        # L-6: Guard COM init failure - self.app is None when CoInitialize or
        # DispatchEx failed. Without this check the loop runs silently with no
        # conversions and no error visible to the user.
        if getattr(converter, 'app', None) is None and sys.platform != 'darwin':
            _emit(ui, 'error', "PowerPoint COM init failed - conversions skipped")
            ui.pp_failure_count += total
        else:
            for i, (pptx_file, sm, ctx) in enumerate(files, 1):
                if ui.is_cancelled():
                    _emit(ui, 'divider', "Process cancelled by user")
                    break
                old_name = pptx_file.name
                _show_active_file(ui, old_name)

                pdf_path_str = converter.convert(
                    pptx_file, dst=_resolve_conversion_target(sm, pptx_file, '.pdf'))

                if pdf_path_str:
                    pdf_path = Path(pdf_path_str)
                    _update_manifest_path(sm, pptx_file, pdf_path)
                    if ui.on_detail_update:
                        ui.on_detail_update(ctx, old_name, pdf_path.name)
                    _emit(ui, 'success', old_name, filename=old_name, detail='→ PDF')
                    ui.pp_success_count += 1
                else:
                    _reason, _fatal = _applescript_last_error()
                    _emit(ui, 'error', old_name, filename=old_name, detail=f'Conversion failed{_reason}')
                    _log_error_to_file(ui.error_log_path, old_name, f"PDF conversion failed{_reason}")
                    ui.pp_failure_count += 1
                    if _fatal:
                        _abort_applescript_phase(ui, _fatal, total - i, "PowerPoint")
                        _render_dashboard(ui, i, total, "PowerPoint files")
                        break
                _render_dashboard(ui, i, total, "PowerPoint files")

    _emit(ui, 'meta', "PDF conversion complete")
    ui.active_file_placeholder.empty()


def run_html_conversion(files, ui: UIBridge):
    """Convert Canvas Pages (HTML) to Markdown."""
    if not files:
        return
    try:
        from converters.md import convert_html_to_md
    except ImportError as _imp_err:
        logger.error(f"md_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "HTML→Markdown conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Converting {total} HTML files to Markdown")
    _render_dashboard(ui, 0, total, "HTML files")
    time.sleep(0.2)

    for i, (html_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break
        old_name = html_file.name
        _show_active_file(ui, old_name)

        md_path = convert_html_to_md(
            html_file, dst=_resolve_conversion_target(sm, html_file, '.md'))

        if md_path:
            _update_manifest_path(sm, html_file, md_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, md_path.name)
            _emit(ui, 'success', md_path.name, filename=md_path.name)
            ui.pp_success_count += 1
        else:
            _emit(ui, 'error', old_name, filename=old_name, detail='Conversion failed')
            _log_error_to_file(ui.error_log_path, old_name, "Markdown conversion failed")
            ui.pp_failure_count += 1
        _render_dashboard(ui, i, total, "HTML files")

    _emit(ui, 'meta', "Markdown conversion complete")
    ui.active_file_placeholder.empty()


def run_code_conversion(files, ui: UIBridge):
    """Convert code & data files to .txt."""
    if not files:
        return
    try:
        from converters.code import convert_code_to_txt
    except ImportError as _imp_err:
        logger.error(f"code_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "Code→TXT conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Converting {total} code & data files to TXT")
    _render_dashboard(ui, 0, total, "Code files")
    time.sleep(0.2)

    for i, (code_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break
        old_name = code_file.name
        _show_active_file(ui, old_name)

        # Routed through the shared resolver like every other converter, so a
        # locally-edited .txt gets the same protection. Its output is
        # `<stem>_<ext>.txt`, not a suffix swap, hence default_name.
        _code_default = f"{Path(code_file).stem}" \
                        f"{Path(code_file).suffix.replace('.', '_')}.txt"
        txt_path_str = convert_code_to_txt(
            code_file,
            dst=_resolve_conversion_target(sm, code_file, '.txt',
                                           default_name=_code_default))

        if txt_path_str:
            txt_path = Path(txt_path_str)
            _update_manifest_path(sm, code_file, txt_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, txt_path.name)
            _emit(ui, 'success', old_name, filename=old_name, detail='→ TXT')
            ui.pp_success_count += 1
        else:
            _emit(ui, 'error', old_name, filename=old_name, detail='Conversion failed')
            _log_error_to_file(ui.error_log_path, old_name, "Code to TXT conversion failed")
            ui.pp_failure_count += 1
        _render_dashboard(ui, i, total, "Code files")

    _emit(ui, 'meta', "Code to TXT conversion complete")
    ui.active_file_placeholder.empty()


def run_url_compilation(folders, ui: UIBridge):
    """Compile .url shortcuts into a NotebookLM text file.

    folders: list of (course_folder_path: Path, course_name: str)
    """
    if not folders:
        return
    try:
        from converters.url import compile_urls_to_txt
    except ImportError as _imp_err:
        logger.error(f"url_compiler unavailable: {_imp_err}")
        _emit(ui, 'error', "URL compilation unavailable: module not found", detail=str(_imp_err))
        return

    _emit(ui, 'divider', "Compiling external links")

    for course_folder, course_name in folders:
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break

        if course_folder.exists():
            try:
                compiled_path, processed_shortcuts = compile_urls_to_txt(course_folder, course_name)
            except Exception as e:
                _emit(ui, 'error', f"URL compilation failed: {course_name}", detail=str(e))
                _log_error_to_file(ui.error_log_path, course_name, f"URL compilation error: {e}")
                ui.pp_failure_count += 1
                continue
            if compiled_path:
                _emit(ui, 'success', "Compiled_External_Links.txt", filename="Compiled_External_Links.txt", detail=course_name)
                ui.pp_success_count += 1

            # Delete processed shortcuts whether new links were compiled or they were
            # already in the file (deduplication handled inside compile_urls_to_txt).
            for shortcut in processed_shortcuts:
                try:
                    shortcut.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Failed to purely delete shortcut {shortcut.name}: {e}")
                    _log_error_to_file(ui.error_log_path, shortcut.name, f"Shortcut deletion failed: {e}")
                    continue


def run_word_conversion(files, ui: UIBridge):
    """Convert legacy Word documents (.doc, .rtf, .odt) to PDF."""
    if not files:
        return
    try:
        from converters.word import WordToPDF
    except ImportError as _imp_err:
        logger.error(f"word_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "Word→PDF conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Converting {total} legacy Word files to PDF")
    _render_dashboard(ui, 0, total, "Legacy Word files")
    time.sleep(0.2)

    with WordToPDF() as converter:
        if getattr(converter, 'app', None) is None and sys.platform != 'darwin':
            _emit(ui, 'error', "Word COM init failed - conversions skipped")
            ui.pp_failure_count += total
        else:
            for i, (word_file, sm, ctx) in enumerate(files, 1):
                if ui.is_cancelled():
                    _emit(ui, 'divider', "Process cancelled by user")
                    break
                old_name = word_file.name
                _show_active_file(ui, old_name)

                pdf_path_str = converter.convert(
                    word_file, dst=_resolve_conversion_target(sm, word_file, '.pdf'))

                if pdf_path_str:
                    pdf_path = Path(pdf_path_str)
                    _update_manifest_path(sm, word_file, pdf_path)
                    if ui.on_detail_update:
                        ui.on_detail_update(ctx, old_name, pdf_path.name)
                    _emit(ui, 'success', old_name, filename=old_name, detail='→ PDF')
                    ui.pp_success_count += 1
                else:
                    _reason, _fatal = _applescript_last_error()
                    _emit(ui, 'error', old_name, filename=old_name, detail=f'Conversion failed{_reason}')
                    _log_error_to_file(ui.error_log_path, old_name, f"Word to PDF conversion failed{_reason}")
                    ui.pp_failure_count += 1
                    if _fatal:
                        _abort_applescript_phase(ui, _fatal, total - i, "Word")
                        _render_dashboard(ui, i, total, "Legacy Word files")
                        break
                _render_dashboard(ui, i, total, "Legacy Word files")

    _emit(ui, 'meta', "Legacy Word to PDF conversion complete")
    ui.active_file_placeholder.empty()


def run_excel_data_conversion(files, ui: UIBridge):
    """Extract Excel data into a structured _Data.txt sidecar.

    Produces a single _Data.txt file per workbook containing Markdown-headed
    sheet sections with CSV-formatted cell data, optimized for AI ingestion.

    Does NOT delete the original file or update the sync manifest - the
    _Data.txt is an untracked secondary artifact (Approach A).
    """
    if not files:
        return
    try:
        from converters.excel import ExcelToData
    except ImportError as _imp_err:
        logger.error(f"excel_converter (ExcelToData) unavailable: {_imp_err}")
        _emit(ui, 'error', "Excel data extraction unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Extracting data from {total} Excel files")
    _render_dashboard(ui, 0, total, "Excel data files")
    time.sleep(0.2)

    with ExcelToData() as extractor:
        for i, (excel_file, sm, ctx) in enumerate(files, 1):
            if ui.is_cancelled():
                _emit(ui, 'divider', "Process cancelled by user")
                break
            old_name = excel_file.name
            _show_active_file(ui, old_name)

            try:
                abs_path = str(excel_file.absolute())
                data_path, data_error_msg = extractor.convert(abs_path)

                if data_path:
                    data_name = Path(data_path).name
                    # Do NOT update manifest - _Data.txt is an untracked sidecar
                    _emit(ui, 'success', old_name, filename=old_name, detail=f'→ {data_name}')
                    ui.pp_success_count += 1
                    ui.generated_sidecar_paths.append(str(data_path))
                else:
                    err_detail = data_error_msg if data_error_msg else "Excel data extraction failed"
                    _emit(ui, 'error', old_name, filename=old_name, detail=err_detail)
                    _log_error_to_file(ui.error_log_path, old_name, err_detail)
                    ui.pp_failure_count += 1
            except Exception as e:
                _emit(ui, 'error', old_name, filename=old_name, detail='System Error')
                _log_error_to_file(ui.error_log_path, old_name, f"System Error: {e}")
                ui.pp_failure_count += 1
            _render_dashboard(ui, i, total, "Excel data files")
    _emit(ui, 'meta', "Excel AI data extraction complete")
    ui.active_file_placeholder.empty()


def run_excel_conversion(files, ui: UIBridge):
    """Convert Excel files (.xlsx, .xls, .xlsm) to PDF.

    AUDIT FIX: Uses _update_manifest_path (SyncManager) instead of raw sqlite3.
    """
    if not files:
        return
    try:
        from converters.excel import ExcelToPDF
    except ImportError as _imp_err:
        logger.error(f"excel_converter (ExcelToPDF) unavailable: {_imp_err}")
        _emit(ui, 'error', "Excel→PDF conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Converting {total} Excel files to PDF")
    _render_dashboard(ui, 0, total, "Excel files")
    time.sleep(0.2)

    with ExcelToPDF() as converter:
        if getattr(converter, 'app', None) is None and sys.platform != 'darwin':
            _emit(ui, 'error', "Excel COM init failed - conversions skipped")
            ui.pp_failure_count += total
        else:
            for i, (excel_file, sm, ctx) in enumerate(files, 1):
                if ui.is_cancelled():
                    _emit(ui, 'divider', "Process cancelled by user")
                    break
                old_name = excel_file.name
                _show_active_file(ui, old_name)

                abs_path = str(excel_file.absolute())
                new_pdf_path, excel_error_msg = converter.convert(
                    abs_path, dst=_resolve_conversion_target(sm, excel_file, '.pdf'))

                if new_pdf_path:
                    pdf_path = Path(new_pdf_path)
                    _update_manifest_path(sm, excel_file, pdf_path)
                    if ui.on_detail_update:
                        ui.on_detail_update(ctx, old_name, pdf_path.name)
                    _emit(ui, 'success', old_name, filename=old_name, detail='→ PDF')
                    ui.pp_success_count += 1
                else:
                    _reason, _fatal = _applescript_last_error()
                    err_detail = excel_error_msg if excel_error_msg else f"Excel to PDF conversion failed{_reason}"
                    _emit(ui, 'error', old_name, filename=old_name, detail=err_detail)
                    _log_error_to_file(ui.error_log_path, old_name, err_detail)
                    ui.pp_failure_count += 1
                    if _fatal:
                        _abort_applescript_phase(ui, _fatal, total - i, "Excel")
                        _render_dashboard(ui, i, total, "Excel files")
                        break
                _render_dashboard(ui, i, total, "Excel files")

    _emit(ui, 'meta', "Excel to PDF conversion complete")
    ui.active_file_placeholder.empty()


def run_video_conversion(files, ui: UIBridge):
    """Extract audio from video files (.mp4, .mov, .mkv) to MP3."""
    if not files:
        return
    try:
        from converters.video import convert_video_to_mp3
    except ImportError as _imp_err:
        logger.error(f"video_converter unavailable: {_imp_err}")
        _emit(ui, 'error', "Video→MP3 conversion unavailable: module not found", detail=str(_imp_err))
        return

    total = len(files)
    _emit(ui, 'divider', f"Extracting audio from {total} video files")
    _render_dashboard(ui, 0, total, "Video files")
    time.sleep(0.2)

    for i, (video_file, sm, ctx) in enumerate(files, 1):
        if ui.is_cancelled():
            _emit(ui, 'divider', "Process cancelled by user")
            break
        old_name = video_file.name
        _show_active_file(ui, old_name)

        mp3_path_str = convert_video_to_mp3(
            video_file, dst=_resolve_conversion_target(sm, video_file, '.mp3'))

        if mp3_path_str:
            mp3_path = Path(mp3_path_str)
            _update_manifest_path(sm, video_file, mp3_path)
            if ui.on_detail_update:
                ui.on_detail_update(ctx, old_name, mp3_path.name)
            _emit(ui, 'success', old_name, filename=old_name, detail='→ MP3')
            ui.pp_success_count += 1
        else:
            _emit(ui, 'error', old_name, filename=old_name, detail='Audio extraction failed')
            _log_error_to_file(ui.error_log_path, old_name, "Video to MP3 extraction failed")
            ui.pp_failure_count += 1
        _render_dashboard(ui, i, total, "Video files")

    _emit(ui, 'meta', "Video to MP3 conversion complete")
    ui.active_file_placeholder.empty()


# ─────────────────────────────────────────────────────
# Convenience: Glob + Run All (for app.py Download flow)
# ─────────────────────────────────────────────────────

_PACKAGE_DIRS = {
    'node_modules', '.git', '__pycache__', '.cache',
    'venv', '.venv', 'env', '.env',
    'site-packages', 'dist-packages',
}

def _glob_files(course_folder: Path, extensions: set, explicit_files: list = None) -> list:
    """Glob course folder for files matching extensions, filtering OS junk and package dirs.

    ``explicit_files`` scopes a run to the files it just fetched, so a re-run
    does not re-convert the whole folder.

    That scope is also what keeps the CONTENTS of an archive out of conversion:
    extracted files were never downloaded, so they are never in the list. The
    exclusion needs no rule of its own - which is why it holds for a folder
    unpacked by an earlier run too, not just this one.
    """
    if not course_folder.exists():
        return []

    explicit_set = {Path(p).resolve() for p in explicit_files} if explicit_files else None

    def _in_scope(f: Path) -> bool:
        # A falsy explicit_files means "no scoping" and converts the whole
        # folder. Both callers guard against reaching here with an empty list
        # (app.py skips post-processing outright; sync passes this run's synced
        # paths), and that guard is what stops a previously-extracted tree being
        # swept up on a later run.
        if not explicit_set:
            return True
        return f.resolve() in explicit_set

    return [
        f for f in course_folder.rglob('*')
        if f.is_file()
        and not f.name.startswith('._')
        and not f.name.startswith('~$')
        and "__MACOSX" not in f.parts
        and not _PACKAGE_DIRS.intersection(f.parts)
        and f.suffix.lower() in extensions
        and not ('.part.' in f.name.lower() or f.name.lower().endswith('.part'))
        and _in_scope(f)
    ]


def run_all_conversions(course_folder: Path, sm, contract: dict, ui: UIBridge, course_name: str = '', explicit_files: list = None):
    """Run all converters for a single course folder based on contract settings.

    Used by the Download flow in app.py.  Each converter is gated by its
    contract key (e.g. contract['convert_pptx'] == True).
    """
    # NOTE ON ARCHIVES: a zip is
    # unpacked and its contents are then left exactly as they are; nothing
    # inside an archive is ever converted, by design (2026-07-29), and sync
    # follows the identical rule.
    #
    # This reverses an earlier change that fed these roots to every converter.
    # That change was right about the symptom (extracted material was being
    # skipped) and wrong about the cure. Measured on one real lecture zip from
    # course 45899 - a JavaScript project with node_modules - it meant 21,824
    # extracted files, 11,818 of which a converter would rewrite, and 9,730 of
    # those landing past Windows' 260-character path limit. The Office half
    # could never have worked at any depth: COM rejects a long path and rejects
    # the long-path prefix as well (both measured).
    #
    # An archive is an opaque payload the teacher uploaded. Unpacking it is a
    # convenience; rewriting its insides - and DELETING the originals, which is
    # what a source-consuming converter does - is not.
    # Every (runner, items) pair that ran, so ONE retry pass at the end can
    # cover all of them. A source-consuming converter deletes its source on
    # success, so a source still on disk afterwards is exactly the failure
    # set - a uniform signal that needs nothing from the individual runners.
    _attempts: list = []

    # Archive Extraction
    if contract.get('convert_zip', False):
        archive_exts = {'.zip', '.tar'}
        archive_files = _glob_files(course_folder, archive_exts, explicit_files)
        # Also catch .tar.gz by full name (since .gz alone may match other files)
        explicit_set = {Path(p).resolve() for p in explicit_files} if explicit_files else None
        extra_targz = [
            f for f in course_folder.rglob('*')
            if f.is_file() and f.name.lower().endswith('.tar.gz')
            and not f.name.startswith('._') and "__MACOSX" not in f.parts
            and f not in archive_files
            and (not explicit_set or f.resolve() in explicit_set)
        ] if course_folder.exists() else []
        archive_files.extend(extra_targz)
        if archive_files:
            # The return value is deliberately dropped. Extraction is the only
            # converter that CREATES files, and for a while those files were fed
            # to every converter below - see the note at the top of this
            # function for why that was reversed. A zip is unpacked; what comes
            # out of it is left alone.
            _run_phase(run_archive_extraction,
                       [(f, sm, course_name) for f in archive_files], ui)

    # PPTX → PDF
    if contract.get('convert_pptx', False):
        pptx_files = _glob_files(course_folder, {'.ppt', '.pptx', '.pptm', '.pot', '.potx'}, explicit_files)
        if pptx_files:
            _items = [(f, sm, course_name) for f in pptx_files]
            _run_phase(run_pptx_conversion, _items, ui)
            _attempts.append((run_pptx_conversion, _items))

    # HTML → Markdown
    if contract.get('convert_html', False):
        html_files = _glob_files(course_folder, {'.html'}, explicit_files)
        if html_files:
            _items = [(f, sm, course_name) for f in html_files]
            _run_phase(run_html_conversion, _items, ui)
            _attempts.append((run_html_conversion, _items))

    # Code → TXT
    if contract.get('convert_code', False):
        from converters.code import CODE_EXTENSIONS
        code_files = _glob_files(course_folder, CODE_EXTENSIONS, explicit_files)
        if code_files:
            _items = [(f, sm, course_name) for f in code_files]
            _run_phase(run_code_conversion, _items, ui)
            _attempts.append((run_code_conversion, _items))

    # URL Compilation
    if contract.get('convert_urls', False):
        if explicit_files is not None:
             # PATH NORMALIZATION CONSTRAINT: Resolve paths to avoid slashes breaking isolation
             # An app-PRODUCED shortcut (the Panopto Shortcut output) must not
             # trigger this phase: the compiler skips it by design, so a run
             # whose only shortcut is one of those would sweep the entire course
             # folder to compile nothing - and would still delete every OTHER
             # pre-existing link in it, which this run never touched.
             has_shortcut = any(
                 Path(p).resolve().suffix.lower() in {'.url', '.webloc'}
                 and not is_produced_shortcut(p)
                 for p in explicit_files)
             if has_shortcut:
                 _run_phase(run_url_compilation, [(course_folder, course_name)], ui)
        else:
             _run_phase(run_url_compilation, [(course_folder, course_name)], ui)

    # Legacy Word → PDF
    if contract.get('convert_word', False):
        word_files = _glob_files(course_folder, {'.doc', '.rtf', '.odt'}, explicit_files)
        if word_files:
            _items = [(f, sm, course_name) for f in word_files]
            _run_phase(run_word_conversion, _items, ui)
            _attempts.append((run_word_conversion, _items))

    # Excel → AI Data + PDF (single toggle, dual pipeline)
    # CRITICAL ORDERING: Data extraction FIRST (reads .xlsx), PDF SECOND (deletes .xlsx).
    # Each call to _glob_files produces an independent list - no iterator exhaustion.
    if contract.get('convert_excel', False):
        # .xls (Excel 97-2003) is binary format openpyxl cannot read; exclude from data extraction.
        # ExcelToPDF via COM/AppleScript handles .xls fine - it stays in the PDF glob below.
        excel_data_files = _glob_files(course_folder, {'.xlsx', '.xlsm'}, explicit_files)
        if excel_data_files:
            _run_phase(run_excel_data_conversion,
                       [(f, sm, course_name) for f in excel_data_files], ui)

        excel_pdf_files = _glob_files(course_folder, {'.xlsx', '.xls', '.xlsm'}, explicit_files)
        if excel_pdf_files:
            _items = [(f, sm, course_name) for f in excel_pdf_files]
            _run_phase(run_excel_conversion, _items, ui)
            _attempts.append((run_excel_conversion, _items))

    # Video → MP3
    if contract.get('convert_video', False):
        video_files = _glob_files(course_folder, {'.mp4', '.mov', '.mkv', '.avi', '.m4v'}, explicit_files)
        if video_files:
            _items = [(f, sm, course_name) for f in video_files]
            _run_phase(run_video_conversion, _items, ui)
            _attempts.append((run_video_conversion, _items))

    # One retry pass over everything that failed, then a precise reason for
    # whatever failed twice. Most conversion failures are transient - a
    # destination locked for a few seconds by an editor, an antivirus handle,
    # a COM hiccup - and retrying costs one extra attempt per failed file.
    # Anything still failing is reported by name, naming the locked file when
    # one can be found, so "2 files failed during post-processing" becomes a
    # two-second fix instead of a trip to download_errors.txt.
    retry_failed_conversions(_attempts, ui)
