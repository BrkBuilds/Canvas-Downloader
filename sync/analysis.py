"""
sync.analysis - Analysis phase logic for sync flow.

Extracted from ``sync_ui.py`` L2682-2941 (Phase 4).
Strict physical move - NO logic changes.

Fix 1 (2026-04): Eliminated duplicate module scan by threading the
    module_map from get_course_files_metadata → analyze_course.
Fix 2 (2026-04): Offloaded blocking Canvas API calls to a background
    thread via asyncio.to_thread + safe_thread_wrapper to improve
    UI responsiveness during the analysis phase.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from pathlib import Path
from urllib.parse import unquote_plus

import streamlit as st

from shared import theme
from core.canvas_logic import CanvasManager, safe_thread_wrapper
from core.cancellation import cancel_sync, is_sync_cancelled, reset_sync_cancel
from core.state_registry import NOTEBOOK_SUB_KEYS
from core.sync_manager import SyncManager
from shared.helpers import render_sync_wizard, esc
from core.pair_labels import pair_display_name
from engine.notifications import play_completion_beep
# MODULE level on purpose. These used to be imported ONLY inside the Today-mode
# branch of sync_progress_hook, so the regular full-page branch below - which
# needs them too - raised NameError on every single tick. The hook wraps its
# whole body in `except Exception`, so the failure was silent and the analysis
# panel simply never painted: a bare "Cancel Sync" button on an otherwise empty
# page until the review screen appeared.
from engine.estimation import stepwise_estimator
from engine.progress_dashboard import (
    DashboardPlaceholders, build_progress_bar_html, metric_count, metric_eta,
    render_analysis_dashboard, analysis_percent,
)

logger = logging.getLogger(__name__)


def _persist_discovered_entries(all_results) -> None:
    """Durably record auto-discovered / healed manifest rows for every analyzed
    pair and stamp ``last_synced`` to the current time.

    Used on the zero-change fast paths (nothing to download) so a fully
    up-to-date folder - especially a student-built one that was just recognized
    via content/size matching - builds its sync "memory" once, instead of
    re-walking and re-hashing the entire tree on every future sync. Passing
    ``update_last_synced=True`` (the default) ensures the sync overview list
    correctly shows when the course was last checked/synced.
    """
    for _res in all_results or []:
        if not isinstance(_res, dict):
            continue
        _sm = _res.get('sync_manager')
        _mf = _res.get('manifest')
        if _sm is None or _mf is None:
            continue
        try:
            _sm.save_manifest(_mf, update_last_synced=True)
        except Exception as _persist_err:
            logger.warning(f"Failed to persist discovered manifest entries: {_persist_err}")


# ---------------------------------------------------------------------------
# Fix 2: Background-thread helper for per-course analysis
# ---------------------------------------------------------------------------

def _analyze_course_blocking(cm, course_id, course_name, local_folder,
                             progress_hook):
    """Execute all blocking Canvas API calls for a single course.

    This function is designed to be called via ``asyncio.to_thread()`` with
    ``safe_thread_wrapper`` so that Streamlit's ScriptRunContext is preserved
    on the background thread (required for ``st.session_state`` reads inside
    the progress hook and for ``st.markdown`` UI pushes).

    Returns:
        Tuple of (course, sync_mgr, manifest, canvas_files, result, detected)
        - all data needed by the caller, with no side effects.
    """
    from core.canvas_debug import log_debug, clear_debug_log, set_active_debug_file, log_session_header
    _dbg = st.session_state.get('debug_mode', False)
    debug_file = str(Path(local_folder) / 'debug_log.txt') if _dbg else None
    if debug_file:
        clear_debug_log(debug_file)
        # Register for the logging bridge so warnings/errors logged via the
        # `logging` module anywhere in the app land in this file too.
        set_active_debug_file(debug_file)
        log_session_header(debug_file, context="Sync analysis")
        _mode_label = "Quick Sync" if st.session_state.get('sync_quick_mode') else "Analyze, Review & Sync"
        log_debug(f"=== Sync Analysis: {course_name} (ID: {course_id}) ===", debug_file)
        log_debug(f"Mode: {_mode_label}", debug_file)
        log_debug(f"Course Folder: {local_folder}", debug_file)

    progress_hook(0, 1, "Connecting to Canvas API...")
    _t_connect = time.perf_counter()
    try:
        course = cm.canvas.get_course(course_id)
    except Exception as _gc_err:
        raise RuntimeError(
            f"Could not fetch course '{course_name}' (ID {course_id}) from Canvas: {_gc_err}"
        ) from _gc_err
    if debug_file:
        log_debug(f"Connected to course: {getattr(course, 'name', course_name)} "
                  f"({int((time.perf_counter() - _t_connect) * 1000)} ms)", debug_file)

    sync_mgr = SyncManager(str(local_folder), course_id, course_name)

    progress_hook(0, 1, "Loading local sync manifest...")
    _t_manifest = time.perf_counter()
    manifest = sync_mgr.load_manifest()
    if debug_file:
        log_debug(f"Loaded local manifest: {len(manifest.get('files', {}))} tracked entrie(s) "
                  f"({int((time.perf_counter() - _t_manifest) * 1000)} ms)", debug_file)

    # Load secondary content contract so analysis includes negative-ID entities
    _sec_contract_source = "database"
    _raw_secondary = sync_mgr._load_metadata('secondary_content_contract')
    if _raw_secondary is not None:
        try:
            _raw_secondary = json.loads(_raw_secondary)
        except (json.JSONDecodeError, TypeError, ValueError) as _sec_err:
            # Truncated or corrupt stored JSON - log a warning and fall through
            # to the session-state fallback so the user's current settings are used.
            logger.warning(
                f"Secondary content contract for course {course_id} is corrupt "
                f"({_sec_err}); falling back to current session settings."
            )
            _raw_secondary = None
            _sec_contract_source = "session state (DB corrupt)"
    if _raw_secondary is None:
        _sec_contract_source = "session state (first sync)"
        # H-4 / L-4: First-ever analysis for this pair - no DB contract yet.
        # Fall back to session state so the user's current settings are honoured.
        # We do NOT persist here: analysis is a read-only "verify" phase and must
        # leave no DB side effects if the user backs out. The contract is durably
        # written at sync execution time (sync/execution.py seeds it on first run),
        # so future syncs still inherit these settings once a sync actually runs.
        _raw_secondary = {
            'download_assignments':   st.session_state.get('persistent_dl_assignments', False),
            'download_syllabus':      st.session_state.get('persistent_dl_syllabus', False),
            'download_announcements': st.session_state.get('persistent_dl_announcements', False),
            'download_discussions':   st.session_state.get('persistent_dl_discussions', False),
            'download_quizzes':       st.session_state.get('persistent_dl_quizzes', False),
            'download_rubrics':       st.session_state.get('persistent_dl_rubrics', False),
            'download_submissions':   st.session_state.get('persistent_dl_submissions', False),
            'isolate_secondary_content': st.session_state.get('persistent_dl_isolate_secondary', True),
        }
    _secondary_settings = _raw_secondary  # may still be empty dict - that's fine
    if debug_file:
        _enabled_sec = [
            k.replace('download_', '') for k, v in (_secondary_settings or {}).items()
            if v and k.startswith('download_')
        ]
        _isolate = (_secondary_settings or {}).get('isolate_secondary_content', True)
        log_debug(
            f"Secondary contract: source={_sec_contract_source} | "
            f"enabled=[{', '.join(_enabled_sec) or 'none'}] | "
            f"isolate={'yes' if _isolate else 'no'}",
            debug_file,
        )

    progress_hook(0, 1, "Fetching files from Canvas...")
    _t_fetch = time.perf_counter()
    _fetch_timings: dict = {}
    # The mode this folder was BUILT in, read from its own contract - not the
    # mode a fresh download would pick. It decides where an isolated Page is
    # expected to sit, so guessing it wrong makes every page read as new.
    _built_mode = sync_mgr._load_metadata('download_mode') or None
    canvas_files, sec_fetch_status, module_map = cm.get_course_files_metadata(
        course,
        progress_callback=progress_hook,
        secondary_content_settings=_secondary_settings,
        timings=_fetch_timings,
        download_mode=_built_mode,
    )
    if debug_file:
        _fetch_ms = int((time.perf_counter() - _t_fetch) * 1000)
        log_debug(f"Fetched {len(canvas_files)} files from Canvas "
                  f"(secondary: {sec_fetch_status}) ({_fetch_ms} ms)", debug_file)
        log_debug(
            "  ↳ fetch breakdown: "
            f"bulk_files={_fetch_timings.get('bulk_files_ms', '?')}ms | "
            f"pages={_fetch_timings.get('pages_ms', '?')}ms "
            f"(bulk‖pages wall-clock={_fetch_timings.get('fetch_parallel_ms', '?')}ms) | "
            f"module_scan={_fetch_timings.get('module_scan_ms', '?')}ms | "
            f"secondary={_fetch_timings.get('secondary_ms', '?')}ms",
            debug_file,
        )

    progress_hook(1, 1, "Healing local sync manifest...")
    _t_heal = time.perf_counter()
    manifest = sync_mgr.heal_manifest(manifest)
    if debug_file:
        log_debug(f"Manifest healed | DB was reset: {sync_mgr.db_was_reset} "
                  f"({int((time.perf_counter() - _t_heal) * 1000)} ms)", debug_file)

    # One-time repair: manifests written before MD5-on-download existed have no
    # original_md5 baseline, which forces every genuine update onto the
    # "locally edited" path (_NewVersion forks) and disables content-based
    # rename matching. Backfill from the pristine bytes on disk. Gated by a DB
    # flag so the disk hashing runs at most once per folder.
    if sync_mgr._load_metadata('baseline_md5_backfilled') != '1':
        _t_backfill = time.perf_counter()
        try:
            _filled = sync_mgr.backfill_baseline_md5(manifest)
            sync_mgr._save_metadata('baseline_md5_backfilled', '1')
            if debug_file:
                log_debug(f"MD5 baseline backfill: repaired {_filled} entrie(s) "
                          f"({int((time.perf_counter() - _t_backfill) * 1000)} ms)", debug_file)
        except Exception as _bf_err:
            # Non-fatal: an empty baseline is safe (engine preserves local copy),
            # so a failed repair must never block the analysis.
            if debug_file:
                log_debug(f"MD5 baseline backfill skipped (error): {_bf_err}", debug_file)

    progress_hook(1, 1, "Comparing files...")
    _t_compare = time.perf_counter()
    detected = sync_mgr.detect_structure()
    if debug_file:
        log_debug(f"Detected folder structure: {detected}", debug_file)
    # Pass the pre-built module_map so analyze_course skips the redundant
    # Canvas API fetch for module structure (Fix 1).
    result = sync_mgr.analyze_course(
        canvas_files, manifest, cm=cm,
        download_mode=detected,
        secondary_fetch_success=sec_fetch_status,
        module_map=module_map,
    )
    if debug_file:
        _nc = len(getattr(result, 'new_files', []) or [])
        _uc_clean = len(getattr(result, 'updated_clean_files', []) or [])
        _uc_mod = len(getattr(result, 'updated_modified_files', []) or [])
        _dc = len(getattr(result, 'deleted_on_canvas', []) or [])
        _lc = len(getattr(result, 'locally_deleted_files', []) or [])
        log_debug(
            f"Analysis complete ({int((time.perf_counter() - _t_compare) * 1000)} ms): "
            f"{_nc} new | {_uc_clean} clean updates | "
            f"{_uc_mod} locally-edited updates | {_dc} deleted on Canvas | "
            f"{_lc} deleted locally",
            debug_file,
        )
        # One line per file, for EVERY category the analyzer produced. The
        # categories are the whole product of this phase, so a log that covers
        # only some of them cannot answer the question a support case actually
        # asks - "why did it not re-download X?" - about the rest.
        #
        # Two details that make these lines usable rather than merely present:
        #
        #   * ``canvas_filename`` is stored URL-ENCODED (it comes straight off
        #     the Canvas API), so a Danish name logged raw reads
        #     `Eksamen+2023E+Ordin%C3%A6r+Klasse+opgave.pdf` while the review
        #     screen shows `Eksamen 2023E Ordinær Klasse opgave.pdf`. Nobody can
        #     match those by eye, and no tooling can match them without knowing
        #     to decode. The UI already decodes with unquote_plus; so does this.
        #   * the local path is appended where it differs from the name, because
        #     post-processing renames files (`x.js` -> `x_js.txt`) and the
        #     Canvas-side name alone will not be found on disk.
        def _row(tag: str, name: str, local: str = '') -> None:
            _disp = unquote_plus(str(name or ''))
            _loc = str(local or '')
            _suffix = f"   -> {_loc}" if _loc and Path(_loc).name != _disp else ""
            log_debug(f"  [{tag}]{' ' * max(1, 14 - len(tag))}{_disp}{_suffix}", debug_file)

        for _f in (getattr(result, 'new_files', []) or []):
            _fn = getattr(_f, 'display_name', None) or getattr(_f, 'filename', str(_f))
            _row('NEW', _fn, getattr(_f, 'target_local_path', ''))
        for _f, _si in (getattr(result, 'updated_clean_files', []) or []):
            _fn = getattr(_f, 'display_name', None) or getattr(_f, 'filename', str(_f))
            _row('UPDATE-CLEAN', _fn, getattr(_si, 'local_path', ''))
        for _f, _si in (getattr(result, 'updated_modified_files', []) or []):
            _fn = getattr(_f, 'display_name', None) or getattr(_f, 'filename', str(_f))
            _row('UPDATE-EDIT', _fn, getattr(_si, 'local_path', ''))
        for _si in (getattr(result, 'deleted_on_canvas', []) or []):
            _row('CANVAS-DEL', getattr(_si, 'canvas_filename', str(_si)),
                 getattr(_si, 'local_path', ''))
        for _si in (getattr(result, 'locally_deleted_files', []) or []):
            _row('LOCAL-DEL', getattr(_si, 'canvas_filename', str(_si)),
                 getattr(_si, 'local_path', ''))
        # Ignored files were previously counted nowhere and listed nowhere, so a
        # file the user had suppressed simply vanished from the log - the one
        # category where "it is missing on purpose" is the answer, and the log
        # could not give it.
        _ign = getattr(result, 'ignored_files', []) or []
        if _ign:
            log_debug(f"Ignored (excluded from sync): {len(_ign)} file(s)", debug_file)
            for _si in _ign:
                _row('IGNORED', getattr(_si, 'canvas_filename', str(_si)),
                     getattr(_si, 'local_path', ''))
        # Up-to-date files are deliberately summarised rather than listed: on a
        # healthy folder they are every file in the course, and 200 lines of
        # "nothing happened" would bury the ~10 lines that matter.
        _utd = len(getattr(result, 'uptodate_files', []) or [])
        if _utd:
            log_debug(f"Up to date (no action): {_utd} file(s)", debug_file)

    # ── Panopto recordings (discovered + disk-compared, like any other file) ──
    # Only when the premium feature is enabled. Discovery is slow (per-recording
    # LTI handshakes), so it runs here ONCE during analysis; execution reuses the
    # result so Review and what actually syncs can never disagree. A failure here
    # must never block the file analysis.
    panopto_payload = None
    _t_panopto = time.perf_counter()
    try:
        from panopto.settings import (
            wants_transcription as _pan_wants_tx,
            compose_settings as _pan_compose, is_enabled as _pan_is_enabled,
            contract_from_ui_state as _pan_contract_from_state,
            is_globally_enabled as _pan_globally_enabled,
        )
        # THE global Panopto switch, for sync mode - read once per course, ahead
        # of everything else in this block. This is where the switch is worth the
        # most: discovery is the slowest thing in an analysis (a per-recording
        # LTI handshake, and at a university with no Panopto at all it is ~48
        # handshakes at 1-2s each that can only ever return nothing).
        #
        # The switch is read here directly rather than through
        # ``effective_contract`` because the point is to skip the WORK, not just
        # to neutralise its result: with Panopto off this course reads no stored
        # contract, heals nothing, writes nothing and scans nothing.
        # ``effective_contract`` is the equivalent for a caller that already
        # holds a contract (app.py's phase trigger, sync_ui's pair helpers).
        #
        # panopto_payload stays None, which is already the documented shape for
        # "the feature is disabled" - so every consumer downstream (Review, the
        # selection loop, execution's phase routing) needs no change at all.
        _pan_on = _pan_globally_enabled()

        # Per-folder Panopto contract (output formats + layout), mirroring the
        # secondary_content_contract: read from this folder's manifest, falling
        # back to the current Section 4 session toggles on the first-ever sync
        # (read-only here - execution durably seeds it). Engine config
        # (model/device/language) is layered in by compose_settings.
        #
        # NOT read while Panopto is off, and the folder's stored contract is
        # therefore left exactly as it is. That is deliberate: switching Panopto
        # off is a statement about what happens NEXT, never a rewrite of what a
        # folder was set up for, so switching it back on resumes recordings with
        # the outputs the user originally chose.
        _raw_pan = sync_mgr._load_metadata('panopto_contract') if _pan_on else None
        _pan_contract = None
        if _raw_pan is not None:
            try:
                _pan_contract = json.loads(_raw_pan)
            except (json.JSONDecodeError, TypeError, ValueError):
                _pan_contract = None
        if _pan_on and _pan_contract is None:
            _pan_contract = _pan_contract_from_state(st.session_state)
            # Those persistent_* keys are session-only and reset to False at every
            # app launch, so on a fresh launch this fallback disables Panopto
            # outright. For a folder that ALREADY holds Panopto artifacts that is
            # provably wrong - it only happens when the download-mode contract
            # seed write failed (best-effort _save_metadata). Recover the contract
            # from what is on disk rather than silently skipping the whole pass.
            if not _pan_is_enabled(_pan_contract):
                try:
                    from panopto.settings import infer_contract_from_manifest
                    _healed = infer_contract_from_manifest(
                        sync_mgr.get_panopto_manifest())
                except Exception as _e:
                    _healed = None
                    logger.debug(f"Panopto contract inference failed: {_e}")
                if _healed:
                    logger.warning(
                        "No stored panopto_contract for '%s', but the folder holds "
                        "Panopto artifacts - recovered the contract from the "
                        "manifest (%s). Re-seeding it.",
                        getattr(sync_mgr, 'local_path', '?'), _healed,
                    )
                    _pan_contract = _healed
                    # Persist the recovery so the next sync reads it normally
                    # instead of re-deriving (and so the UI shows it).
                    try:
                        sync_mgr._save_metadata('panopto_contract',
                                                json.dumps(_healed))
                    except Exception as _e:
                        logger.warning(f"Could not re-seed panopto_contract: {_e}")
        if _pan_on and _pan_is_enabled(_pan_contract):
            # Composed here rather than above because it is only ever read inside
            # this branch (the payload's 'settings'). Built unconditionally, it
            # would also read as a live config for a course that ran no Panopto
            # pass at all - and compose_settings(None) deliberately returns the
            # DEFAULTS, which have mp3/txt/srt ON.
            _pan = _pan_compose(_pan_contract)
            from panopto.discovery import discover_course_videos
            from panopto.sync_plan import (
                classify_videos, tally as _pan_tally,
                videos_needing_duration as _pan_need_dur,
                apply_size_estimates as _pan_apply_sizes,
            )
            from panopto.stream import fetch_durations as _pan_fetch_dur
            from panopto import models as _pmodels

            progress_hook(0, 1, "Searching for Panopto recordings…")

            def _pan_scan(kind, **kw):
                try:
                    if kind == 'stage':
                        progress_hook(0, 1, f"Scanning Panopto - {kw.get('name', '')}…")
                    elif kind == 'video':
                        progress_hook(0, 1, f"Found recording: {kw.get('title', '')}")
                except Exception:
                    pass

            # ── M-11: discovery cache for the FAST sync modes ──
            # Discovery is the slowest part of analysis (per-recording LTI
            # handshakes). Quick Sync and the Today daily auto-sync reuse a
            # scan younger than 24h stored in this folder's DB; the deliberate
            # "Analyze, Review & Sync" flow ALWAYS re-scans so the review is
            # 100% fresh. Every fresh scan (any mode) refreshes the cache.
            from panopto.discovery import PanoptoVideo as _PanVideo
            _PAN_CACHE_KEY = 'panopto_discovery_cache'
            _PAN_CACHE_TTL_SEC = 24 * 3600
            _is_fast_mode = bool(st.session_state.get('sync_quick_mode')
                                 or st.session_state.get('today_sync_active'))
            _pan_videos = None
            if _is_fast_mode:
                try:
                    _raw_cache = sync_mgr._load_metadata(_PAN_CACHE_KEY)
                    if _raw_cache:
                        _cache = json.loads(_raw_cache)
                        from datetime import datetime as _dt, timezone as _tz
                        _ts = _dt.fromisoformat(_cache.get('ts', ''))
                        _age = (_dt.now(_tz.utc) - _ts).total_seconds()
                        if 0 <= _age < _PAN_CACHE_TTL_SEC:
                            _pan_videos = [_PanVideo(**v) for v in _cache.get('videos', [])]
                            progress_hook(0, 1, "Using recent Panopto scan…")
                            if debug_file:
                                log_debug(
                                    f"Panopto: reusing cached discovery "
                                    f"({len(_pan_videos)} recording(s), {_age / 3600:.1f}h old)",
                                    debug_file,
                                )
                except Exception as _cache_err:
                    logger.debug(f"Panopto discovery cache unusable: {_cache_err}")
                    _pan_videos = None

            if _pan_videos is None:
                _pan_videos = discover_course_videos(
                    cm.api_url, cm.api_key, course_id,
                    include_folder_sessions=True,
                    is_cancelled=is_sync_cancelled,
                    on_event=_pan_scan,
                )
                # Refresh the cache (best-effort; skip if the scan was cancelled
                # mid-way - a truncated list must never masquerade as complete).
                if not is_sync_cancelled():
                    try:
                        from dataclasses import asdict as _asdict
                        from datetime import datetime as _dt, timezone as _tz
                        sync_mgr._save_metadata(_PAN_CACHE_KEY, json.dumps({
                            'ts': _dt.now(_tz.utc).isoformat(),
                            'videos': [_asdict(v) for v in _pan_videos],
                        }))
                    except Exception as _cache_err:
                        logger.debug(f"Panopto discovery cache write failed: {_cache_err}")

            _model_id = _pan.get('model', 'small')
            _model_ready = bool(
                _pan_wants_tx(_pan)
                and _pmodels.whisper_available()
                and _pmodels.is_installed(_model_id)
            )
            # Use the SAME download_mode the execution panopto pass will use, so
            # classification paths line up exactly with where files land.
            _pan_dmode = sync_mgr._load_metadata('download_mode') or detected or 'modules'
            _pan_manifest = sync_mgr.get_panopto_manifest()
            _pan_ignored = set(sync_mgr.get_ignored_panopto().keys())
            _pan_changes = classify_videos(
                cm, _pan_videos, local_folder, _pan_dmode, _pan,
                _pan_manifest, ignored_ids=_pan_ignored,
            )
            # Heal stale manifest paths: classify found these kinds alive at
            # the CURRENT layout path while their recorded path is gone (e.g.
            # a download-mode run of the same folder re-fetched them - it
            # plans purely by layout and knows nothing of manifest paths).
            # Re-point the manifest (idempotent upsert) so execution and
            # future analyses resolve to the real file; without this the
            # runner's manifest-first stem keeps writing new outputs next to
            # the dead path, duplicating files the user already has.
            for _hc in _pan_changes:
                for _hk, _hp in (getattr(_hc, 'healed_paths', None) or {}).items():
                    try:
                        _h_rel = str(Path(_hp).relative_to(Path(local_folder))).replace('\\', '/')
                    except Exception:
                        _h_rel = str(_hp)
                    try:
                        sync_mgr.record_panopto_file(
                            _hc.video.video_id, _hk, _h_rel,
                            getattr(_hc.video, 'title', ''))
                        logger.info("Panopto manifest healed: '%s' %s -> %s",
                                    getattr(_hc.video, 'title', _hc.video.video_id),
                                    _hk, _h_rel)
                    except Exception as _heal_err:
                        logger.debug(f"Panopto manifest heal failed: {_heal_err}")
            # Size the recordings whose outputs aren't on disk yet (new/restore/
            # ignored): fetch durations only for those, then estimate. Best-effort -
            # a probe failure just leaves those sizes unknown.
            try:
                _need = _pan_need_dur(_pan_changes)
                if _need and not is_sync_cancelled():
                    progress_hook(0, 1, "Measuring recording sizes…")
                    _durs = _pan_fetch_dur(cm, _need, is_cancelled=is_sync_cancelled)
                    if _durs:
                        _pan_apply_sizes(_pan_changes, _durs)
            except Exception as _pan_size_err:
                logger.debug(f"Panopto size estimation skipped: {_pan_size_err}")
            panopto_payload = {
                'changes': _pan_changes,
                'videos': _pan_videos,
                'download_mode': _pan_dmode,
                'settings': _pan,
                'model_ready': _model_ready,
            }
            if debug_file:
                _t = _pan_tally(_pan_changes)
                log_debug(
                    f"Panopto: discovered {len(_pan_videos)} recording(s) | "
                    f"new/missing {_t['new']} | deleted-locally {_t['restore']} | "
                    f"ignored {_t['ignored']} | up to date {_t['uptodate']}"
                    + ("" if _model_ready else " | (transcription engine/model not "
                       "ready - audio only)"),
                    debug_file,
                )
                for _c in _pan_changes:
                    if _c.bucket == 'new':
                        log_debug(f"  [PAN-NEW]      {_c.title} (missing: {', '.join(_c.missing_kinds)})", debug_file)
                    elif _c.bucket == 'restore':
                        log_debug(f"  [PAN-LOCDEL]   {_c.title} (deleted: {', '.join(_c.deleted_kinds)})", debug_file)
    except Exception as _pan_err:
        logger.warning(f"Panopto analysis failed for course {course_id}: {_pan_err}", exc_info=True)
        if debug_file:
            log_debug(f"[WARNING] Panopto analysis skipped (error): {_pan_err}", debug_file)
        panopto_payload = {'changes': [], 'videos': [], 'download_mode': detected,
                           'settings': {}, 'error': str(_pan_err)}

    # Only log the Panopto phase when it actually ran (payload stays None when the
    # feature is disabled - no noise for the common no-Panopto case).
    if debug_file and panopto_payload is not None:
        log_debug(f"Panopto phase: {int((time.perf_counter() - _t_panopto) * 1000)} ms", debug_file)

    return course, sync_mgr, manifest, canvas_files, result, detected, panopto_payload


def run_analysis(sync_pairs, main_placeholder=None):
    """Execute the analysis phase: compare local vs Canvas for each pair.

    This is a strict physical move of the original ``_run_analysis`` from
    ``sync_ui.py``.  No logic has been changed.
    """
    # M-8 / C-3: Reset the sync cancel event at the start of every fresh analysis
    # run. This clears any stale event left by a prior run that bypassed
    # cleanup_sync_state(), preventing silent self-abort on the first check.
    reset_sync_cancel()

    # Today dashboard hosts this inside its own titled progress card, so skip the
    # full step wizard (the card + its slim bar are the only chrome there).
    _today_minimal = st.session_state.get('today_sync_active', False)

    # Step wizard
    if not _today_minimal:
        render_sync_wizard(st, 'analyze')

    # (The old sync_single_pair_idx single-pair filter was dead code - nothing
    # in the app ever set the key - and has been removed.)
    pairs_to_analyze = sync_pairs

    cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
    all_results = []
    total_pairs = len(pairs_to_analyze)

    # ── Course-identity guard ──────────────────────────────────────────
    # Each folder's .canvas_sync.db is bound to the first course it was
    # synced against. If the pair's course_id no longer matches that
    # binding (e.g. user re-pointed the pair at a different course, or
    # picked the wrong folder), running analysis would treat the entire
    # bound course's manifest as "Deleted on Canvas" - terrifying and
    # wrong. Detect and route to a confirmation screen instead.
    mismatched = []
    for pair_idx, pair in enumerate(pairs_to_analyze):
        try:
            local_folder = pair.get('local_folder')
            requested_id = pair.get('course_id')
            if not local_folder or not Path(local_folder).exists():
                continue  # downstream loop handles missing folder
            bound_id = SyncManager.peek_bound_course_id(local_folder)
            from core.sync_manager import DB_UNREADABLE
            if bound_id == DB_UNREADABLE:
                # M-6: DB exists but couldn't be read - treat as a mismatch so
                # the user is warned rather than silently syncing against a corrupt DB.
                mismatched.append({
                    'pair_idx': pair_idx,
                    'pair': pair,
                    'bound_course_id': DB_UNREADABLE,
                    'bound_course_name': 'an unreadable database',
                    'requested_course_id': requested_id,
                    'requested_course_name': pair.get('course_name', f"course #{requested_id}"),
                })
            elif bound_id is not None and bound_id != requested_id:
                bound_name = SyncManager.peek_bound_course_name(local_folder) or f"course #{bound_id}"
                mismatched.append({
                    'pair_idx': pair_idx,
                    'pair': pair,
                    'bound_course_id': bound_id,
                    'bound_course_name': bound_name,
                    'requested_course_id': requested_id,
                    'requested_course_name': pair.get('course_name', f"course #{requested_id}"),
                })
        except Exception as e:
            logger.warning(f"Course-binding peek failed for {pair.get('local_folder')}: {e}")
            continue

    if mismatched:
        # H-3: Store ALL mismatches so step 1 can render a single aggregate
        # amber notice listing every affected pair. Previously only the first
        # mismatch was surfaced, requiring N round-trips to fix N pairs.
        st.session_state['sync_mismatched_pairs'] = mismatched
        st.session_state['download_status'] = ''
        st.session_state['step'] = 1
        st.session_state.pop('analysis_pass', None)
        st.rerun()

    # Completely wipe the Step 1 / Main UI container before blocking on analysis
    if main_placeholder:
        main_placeholder.empty()

    # Clean progress display - no stale cards. Today mode keeps the single slim
    # placeholder (its own card is already the frame); everywhere else the
    # analysis renders through the SAME dashboard chrome as the sync itself.
    if _today_minimal:
        analysis_ui_placeholder = st.empty()
        analysis_dp = None
    else:
        with st.container(key="progress_dashboard"):
            _an_header = st.empty(); _an_progress = st.empty()
            _an_metrics = st.empty(); _an_active = st.empty()
        analysis_ui_placeholder = None
        analysis_dp = DashboardPlaceholders(
            header=_an_header, progress=_an_progress,
            metrics=_an_metrics, active_file=_an_active,
        )
        st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)

    # Courses are the unit of work. ~5 s each is the opening guess; the measured
    # rate replaces it as soon as the first course finishes.
    analysis_eta = stepwise_estimator(5.0)
    analysis_changes = [0]   # cumulative changes found, for the metrics row

    if _today_minimal:
        # The Today running-sync card sets its own flex `gap: 0` (see
        # today.css) to collapse the many hidden/style-only ghost elements the
        # shared sync engine renders while embedded in that card. That also
        # zeroes the ambient spacing that used to sit between this analysis
        # placeholder and the Cancel button below it, so without a real
        # spacer div here the button visually overlaps the progress bar's
        # negative-margin markdown container. Mirrors the identical spacer
        # already used before the Cancel button in sync/execution.py.
        st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)

    # RENDER GLOBAL CANCEL ABOVE THE ANALYSIS LOOP
    cancel_analysis_placeholder = st.empty()
    if cancel_analysis_placeholder.button('Cancel Sync', type="secondary", key="cancel_analysis_btn"):
        cancel_analysis_placeholder.empty()
        cancel_sync()  # sets threading.Event + sync_cancel_requested + sync_cancelled
        st.session_state['download_status'] = 'sync_cancelled'
        st.rerun()

    # Single pool reused across all pairs - avoids per-iteration thread
    # spawn/teardown overhead (~50 ms each on Windows) for large sync groups.
    import concurrent.futures as _cf
    from streamlit.runtime.scriptrunner import get_script_run_ctx, add_script_run_ctx as _add_ctx
    _analysis_pool = _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="canvas-sync-analysis")
    try:
     for pair_num, pair in enumerate(pairs_to_analyze, 1):
        # CHECK FOR CANCEL INSIDE THE LOOP
        if is_sync_cancelled():
            break

        # Folder-not-found guard
        if not Path(pair['local_folder']).exists():
            from ui.amber_notice import render_amber_notice
            render_amber_notice(
                f"Folder not found: {pair['local_folder']}",
                detail="The folder may have been deleted, renamed, or the drive is disconnected. Edit or remove the sync pair to continue.",
            )
            continue

        # The user's own name for this course when they gave one (Saved Groups &
        # Pairs), else the Canvas name. Display only - every identity the engine
        # below uses still comes from pair['course_id'] / pair['course_name'].
        display_name = pair_display_name(pair, fallback='Unnamed Course')

        # Default-argument capture binds pair_num and display_name to the
        # current iteration's values, preventing late-binding over loop variables.
        def sync_progress_hook(current, total, status_text,
                               _pair_num=pair_num, _display_name=display_name):
            try:
                if is_sync_cancelled():
                    return
                analysis_eta.update(units_done=_pair_num - 1, units_total=total_pairs)
                if _today_minimal:
                    # Today dashboard: the surrounding card already shows the
                    # title + phase description, so render only a slim course
                    # line + an animated bar (the analysis sub-steps mostly
                    # report total=1, so an indeterminate sweep reads better
                    # than a bar frozen near 0%).
                    _course_line = (
                        f"Course {_pair_num} of {total_pairs}: <b>{esc(_display_name)}</b>"
                        if total_pairs > 1 else f"<b>{esc(_display_name)}</b>"
                    )
                    analysis_ui_placeholder.markdown(
                        f"<div style='color:{theme.TEXT_SECONDARY};font-size:0.85rem;"
                        f"margin-bottom:8px;'>{_course_line} &middot; {esc(status_text)}</div>"
                        + build_progress_bar_html(0, indeterminate=True, label="Analyzing…"),
                        unsafe_allow_html=True,
                    )
                    time.sleep(0.05)
                    return
                render_analysis_dashboard(
                    analysis_dp,
                    course_label=(f"Analyzing Course {_pair_num}/{total_pairs}"
                                  if total_pairs > 1 else "Analyzing Course"),
                    course_name=_display_name,
                    status_text=status_text,
                    # Courses are the unit the row counts, so they are the unit
                    # the bar measures too - the analysis sub-step only supplies
                    # the fraction of the course in hand. Passing the sub-step's
                    # own ratio straight through put a 100% bar above
                    # "COURSES 0 / 2" every time a sub-step finished.
                    percent=analysis_percent(_pair_num - 1, total_pairs,
                                             current, total),
                    # Most analysis sub-steps report total=1, where a bar pinned
                    # near 0% reads as a hang rather than as work in progress.
                    indeterminate=total <= 1,
                    metrics=[
                        metric_count('Courses', _pair_num - 1, total_pairs),
                        metric_count('Changes Found', analysis_changes[0],
                                     color=theme.SUCCESS_STAT),
                        metric_eta(analysis_eta.eta_text()),
                    ],
                )
                time.sleep(0.05)
            except Exception as _hook_err:
                # Swallowed on purpose - a progress repaint must never abort an
                # analysis - but LOGGED, because a silent swallow here hid a
                # NameError that blanked this panel entirely (see the
                # analyzing_heading_html import at the top of this module).
                logger.warning(f"Analysis progress repaint failed: {_hook_err}",
                               exc_info=True)

        local_folder = pair['local_folder']
        course_id = pair['course_id']
        course_name = pair['course_name']

        # Paint the panel BEFORE blocking. `analysis_ui_placeholder` is created
        # empty and only ever filled from sync_progress_hook, which cannot fire
        # until the worker thread has reached Canvas - so until now there was a
        # window where the screen showed the Cancel button and nothing else. On
        # a course with no changes the whole analysis could finish inside that
        # window, and the user never saw the analysis panel at all. Seeding it
        # through the same hook keeps one renderer for one visual.
        sync_progress_hook(0, 1, "Connecting to Canvas…")

        try:
            # Offload blocking API work to the shared background thread so
            # asyncio.run() never conflicts with Tornado's running loop.
            _current_ctx = get_script_run_ctx()

            async def _run_course_analysis():
                import threading as _th
                _add_ctx(_th.current_thread(), _current_ctx)
                return await asyncio.to_thread(
                    safe_thread_wrapper,
                    _analyze_course_blocking,
                    _current_ctx,
                    cm, course_id, course_name, local_folder,
                    sync_progress_hook,
                )

            # Submit a CALLABLE that builds + runs the coroutine INSIDE the
            # worker: constructing the coroutine here and cancelling the future
            # before it started used to leave a never-awaited coroutine behind
            # (RuntimeWarning + skipped cleanup).
            _fut = _analysis_pool.submit(
                lambda _coro_fn=_run_course_analysis: asyncio.run(_coro_fn())
            )
            # Poll with a short timeout so the cancel flag is honoured even
            # while the background thread is blocked on Canvas API calls.
            # The heartbeat is a script-thread st.* yield point: Streamlit
            # only delivers pending button clicks (incl. Cancel) at such
            # calls, so without it a click would sit queued until ALL pairs
            # finished analyzing. With it, Cancel takes effect within ~0.3s.
            _analysis_heartbeat = st.empty()
            while True:
                if is_sync_cancelled():
                    _fut.cancel()
                    break
                try:
                    _analysis_result = _fut.result(timeout=0.3)
                    break
                except _cf.TimeoutError:
                    _analysis_heartbeat.markdown("")
                    continue
            _analysis_heartbeat.empty()
            if is_sync_cancelled():
                break
            course, sync_mgr, manifest, canvas_files, result, detected, panopto_payload = _analysis_result

            # Do NOT save manifest here! Fixes Verify-Then-Commit state leakage if user hits Back.

            if sync_mgr.db_was_reset:
                from ui.amber_notice import render_amber_notice
                render_amber_notice(
                    f"Sync database for \"{display_name}\" was corrupted and has been reset.",
                    detail="Previous sync history for this folder has been cleared - all files will appear as new on the next sync.",
                )
                logger.warning(f"Sync DB was reset for '{display_name}' ({pair.get('local_folder')})")

            all_results.append({
                'pair': pair,
                'result': result,
                'manifest': manifest,
                'sync_manager': sync_mgr,
                'canvas_files': canvas_files,
                'course': course,
                'detected_structure': detected,
                'panopto': panopto_payload,
            })

            # Credit the finished course to the estimator, and roll its findings
            # into the running "Changes Found" figure.
            analysis_changes[0] += (
                len(getattr(result, 'new_files', []) or [])
                + len(getattr(result, 'updated_clean_files', []) or [])
                + len(getattr(result, 'updated_modified_files', []) or [])
                + len(getattr(result, 'deleted_on_canvas', []) or [])
                + len(getattr(result, 'locally_deleted_files', []) or [])
            )
            analysis_eta.update(units_done=pair_num, units_total=total_pairs)
        except Exception as e:
            traceback.print_exc()
            # exc_info=True: the canvas_debug logging bridge formats the full
            # traceback into the active debug log (print_exc goes to a console
            # that doesn't exist in frozen builds).
            logger.error(f"Sync Analysis Error: {str(e)}", exc_info=True)
            from ui.amber_notice import render_amber_notice
            render_amber_notice(
                f"Could not analyse \"{display_name}\"",
                detail=str(e),
            )
            continue

    finally:
        # Don't wait for in-flight work if cancelled - let thread finish in bg
        _analysis_pool.shutdown(wait=False)

    # Clean up the UI when all courses are done analyzing
    if analysis_ui_placeholder is not None:
        analysis_ui_placeholder.empty()
    else:
        _an_header.empty(); _an_progress.empty()
        _an_metrics.empty(); _an_active.empty()

    st.session_state['sync_analysis_results'] = all_results

    # Arm the completion screen's "some files were ignored" note (it reads
    # this flag; previously nothing ever set it, so the notice was dead code).
    st.session_state['sync_has_ignored_files'] = any(
        isinstance(_r, dict) and bool(getattr(_r.get('result'), 'ignored_files', None))
        for _r in all_results
    )

    # Reset locally-deleted + Panopto checkbox state so they always start at their
    # defaults in the review (locdel/restore deselected, new-panopto reselected).
    for k in list(st.session_state.keys()):
        if (k.startswith('sync_locdel_') or k.startswith('sync_pan_')
                or k.startswith('sync_panlocdel_')):
            del st.session_state[k]

    # Quick Sync mode - skip review and go straight to sync
    if st.session_state.get('sync_quick_mode'):
        
        def apply_file_filter(file_list, filter_mode, is_tuple=False):
            if filter_mode == 'all':
                return file_list
            elif filter_mode == 'study':
                allowed_exts = {'.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx'}
                filtered = []
                for item in file_list:
                    # updated_files is a list of tuples: (canvas_file, local_file)
                    f = item[0] if is_tuple else item
                    
                    if hasattr(f, 'canvas_filename'):
                        fname = f.canvas_filename
                    elif hasattr(f, 'filename'):
                        fname = getattr(f, 'display_name', '') or getattr(f, 'filename', '')
                    else:
                        fname = getattr(f, 'display_name', '')
                        
                    if Path(fname).suffix.lower() in allowed_exts:
                        filtered.append(item)
                return filtered
            return file_list

        # Auto-select all new, updated, locally deleted, and missing files
        sync_selections = []
        total_filter_skipped = 0  # M-5: files hidden by a non-'all' file_filter
        for idx, res_data in enumerate(all_results):
            result = res_data['result']
            cid = res_data['pair']['course_id']
            
            # --- Load Sync Contract from DB for post-processing settings ---
            # Extract contract for *this specific course*
            _contract = {}
            try:
                _sm = res_data['sync_manager']
                _raw = _sm._load_metadata('sync_contract')
                if _raw:
                    _contract = json.loads(_raw)
            except Exception:
                pass  # Fall back to session_state defaults
            
            # Store contract in res_data so the sync backend can apply per-course post-processing
            res_data['contract'] = _contract
                
            current_filter = _contract.get('file_filter', 'all')

            # Apply the gatekeeper BEFORE execution
            actionable_new = apply_file_filter(result.new_files, current_filter, is_tuple=False)
            # Quick Sync processes CLEAN updates only. Modified updates stay
            # behind for the full Review flow so students can't accidentally
            # clutter their folder with `_NewVersion` siblings of files they
            # edited. (Confirmed by the user's design choice.)
            actionable_updated_clean = apply_file_filter(result.updated_clean_files, current_filter, is_tuple=True)
            actionable_del = apply_file_filter(result.locally_deleted_files, current_filter, is_tuple=False)

            # M-5: account for new/clean-update files hidden by a non-'all'
            # file_filter so the completion screen can surface them instead of
            # silently dropping them. (Locally-deleted/edited are skipped by
            # design and tallied separately as qs_skipped.)
            total_filter_skipped += (len(result.new_files) - len(actionable_new))
            total_filter_skipped += (len(result.updated_clean_files) - len(actionable_updated_clean))

            # M-12: files a non-'all' filter drops are SKIPPED, not ignored.
            # They were previously swept into the permanent Ignored bucket as a
            # side effect of the filter - surprising, invisible, and sticky
            # (the flag survived even a later successful download). Skipping is
            # cheap: the same filter drops them again next run, and the
            # completion notice reports the count so nothing happens silently.

            # Debug: log Quick Sync auto-selection per course
            if st.session_state.get('debug_mode'):
                from core.canvas_debug import log_debug as _qs_log
                _qs_dbg = str(Path(res_data['pair']['local_folder']) / 'debug_log.txt')
                _qs_log(f"--- Quick Sync Auto-Selection: {res_data['pair']['course_name']} ---", _qs_dbg)
                _qs_log(
                    f"File filter: {current_filter} | "
                    f"Selected: {len(actionable_new)} new, {len(actionable_updated_clean)} clean updates "
                    f"(Quick Sync always skips locally-deleted and locally-edited files)",
                    _qs_dbg,
                )
                _qs_log(
                    f"Skipped: {len(result.updated_modified_files or [])} locally-edited updates (require Review), "
                    f"{len(result.deleted_on_canvas or [])} Canvas deletions (no action needed)",
                    _qs_dbg,
                )
                for _f in actionable_new:
                    _fn = getattr(_f, 'display_name', None) or getattr(_f, 'filename', str(_f))
                    _qs_log(f"  [QS-SELECT-NEW]    {_fn}", _qs_dbg)
                for _f, _ in actionable_updated_clean:
                    _fn = getattr(_f, 'display_name', None) or getattr(_f, 'filename', str(_f))
                    _qs_log(f"  [QS-SELECT-UPDATE] {_fn}", _qs_dbg)
                for _si in actionable_del:
                    _fn = getattr(_si, 'canvas_filename', str(_si))
                    _qs_log(f"  [QS-SKIP-LOCDEL]   {_fn}", _qs_dbg)
                for _f, _ in (result.updated_modified_files or []):
                    _fn = getattr(_f, 'display_name', None) or getattr(_f, 'filename', str(_f))
                    _qs_log(f"  [QS-SKIP-EDITED]   {_fn}", _qs_dbg)

            # Set session state keys for UI consistency (if user goes Back)
            for f in actionable_new:
                st.session_state[f'sync_new_{cid}_{f.id}'] = True
            for f, _ in actionable_updated_clean:
                st.session_state[f'sync_upd_{cid}_{f.id}'] = True
            # Modified updates are explicitly left UNCHECKED so the Review UI
            # renders them with their default-off state.
            for f, _ in result.updated_modified_files:
                st.session_state.setdefault(f'sync_updmod_{cid}_{f.id}', False)
            # M-6: Quick Sync never re-downloads locally-deleted files. Leave them
            # explicitly UNCHECKED (setdefault, not forced True) so that if the
            # user later opens Review, they reflect Quick Sync's skip behaviour
            # instead of appearing pre-queued for download.
            for si in actionable_del:
                st.session_state.setdefault(f'sync_locdel_{cid}_{si.canvas_file_id}', False)

            # Panopto recordings: auto-select New/missing (like new files), skip
            # Deleted-Locally (like locally-deleted files). Parity with the file
            # buckets above. Selection is by video_id (the runner's allowlist key).
            _pan_changes = (res_data.get('panopto') or {}).get('changes', [])
            _pan_selected_ids = []
            # An unattended run (the Today daily sync) whose user has never
            # answered the acceptable-use notice selects NO recordings. It
            # cannot ask - a modal thrown at app launch would block a run the
            # user did not start and may not be watching - so it quietly syncs
            # files only and the Today page reports what it left out. The same
            # flag carries a run-scoped decline from the interactive paths.
            from shared.legal import panopto_skipped_this_run
            _pan_declined = panopto_skipped_this_run()
            for _c in ([] if _pan_declined else _pan_changes):
                if _c.bucket == 'new':
                    st.session_state[f'sync_pan_{cid}_{_c.video_id}'] = True
                    _pan_selected_ids.append(_c.video_id)
                elif _c.bucket == 'restore':
                    st.session_state.setdefault(f'sync_panlocdel_{cid}_{_c.video_id}', False)

            clean_updates = [f for f, _ in actionable_updated_clean]
            sync_selections.append({
                'pair_idx': idx,
                'res_data': res_data,
                'new': list(actionable_new),
                'updates': clean_updates,
                'updates_clean': clean_updates,
                'updates_modified': [],
                'redownload': [],
                'ignore': [],
                'panopto': _pan_selected_ids,
            })

        total_count = sum(
            len(s['new']) + len(s['updates']) + len(s['redownload']) + len(s.get('panopto', []))
            for s in sync_selections
        )
        
        # 1. Tally skipped files globally using a bulletproof net
        total_locdel = 0
        total_canvasdel = 0
        total_edited = 0
        total_pan_locdel = 0  # Panopto recordings deleted locally (Quick Sync skips)

        for pair_res in all_results:
            if not isinstance(pair_res, dict):
                continue

            res_obj = pair_res.get('result')
            if res_obj is None:
                continue

            # all_results always contains AnalysisResult objects (never plain dicts)
            if hasattr(res_obj, 'locally_deleted_files') and res_obj.locally_deleted_files is not None:
                total_locdel += len(res_obj.locally_deleted_files)
            if hasattr(res_obj, 'deleted_on_canvas') and res_obj.deleted_on_canvas is not None:
                total_canvasdel += len(res_obj.deleted_on_canvas)
            if hasattr(res_obj, 'updated_modified_files') and res_obj.updated_modified_files is not None:
                total_edited += len(res_obj.updated_modified_files)
            for _c in (pair_res.get('panopto') or {}).get('changes', []):
                if _c.bucket == 'restore':
                    total_pan_locdel += 1

        st.session_state['qs_skipped'] = {
            'local_del': total_locdel,
            'canvas_del': total_canvasdel,
            'edited': total_edited,
            'filtered': total_filter_skipped,
            'panopto_local_del': total_pan_locdel,
        }
        logger.debug(f"Quick Sync Skipped Payload: {st.session_state['qs_skipped']}")

        if st.session_state.get('debug_mode'):
            from core.canvas_debug import log_debug as _qs_final_log
            _qs_route = 'sync_complete (nothing to do)' if total_count == 0 else f'pre_sync ({total_count} files queued)'
            for _res in all_results:
                _qs_f = str(Path(_res['pair']['local_folder']) / 'debug_log.txt')
                _qs_final_log(
                    f"Quick Sync summary: {total_count} files queued | "
                    f"skipped {total_edited} edited, {total_locdel} locally-deleted, {total_canvasdel} Canvas-deleted",
                    _qs_f,
                )
                _qs_final_log(f"→ Routing to: {_qs_route}", _qs_f)

        if total_count == 0:
            # M-1: Persist auto-discovered / healed entries even though no
            # download will run, so an up-to-date folder builds its sync memory.
            _persist_discovered_entries(all_results)
            # 2. Bypass directly to completion.
            # Do NOT pop sync_quick_mode here - show_sync_complete reads it
            # to select the correct 'quick_sync_uptodate' notification tone.
            # cleanup_sync_state() removes it at the end of the flow.
            st.session_state['synced_count'] = 0
            st.session_state['download_status'] = 'sync_complete'

            # 3. Force rerun to instantly show the success screen
            st.rerun()
        else:
            logger.debug(f"Quick Sync total_count={total_count} → jumping to 'pre_sync'")
            st.session_state['sync_selections'] = sync_selections
            st.session_state['download_status'] = 'pre_sync'
            st.session_state['qs_cancel_route'] = True  # routes cancel back to step 1 instead of sync_cancelled screen
            
            # Inject "Start Sync" variables so Step 3 starts executing immediately
            for _k in NOTEBOOK_SUB_KEYS:
                st.session_state[f'persistent_{_k}'] = st.session_state.get(_k, False)

            # Do NOT pop `sync_quick_mode` here so the cancel routing knows we are in Quick Sync!
            st.rerun()
    else:
        # Tally files for sync review notification
        total_new = 0
        total_updated_clean = 0
        total_updated_modified = 0
        total_local_del = 0
        total_panopto = 0  # actionable recordings (new/missing + deleted-locally)

        for res_data in all_results:
            result = res_data.get('result')
            if result:
                total_new += len(getattr(result, 'new_files', []) or [])
                total_updated_clean += len(getattr(result, 'updated_clean_files', []) or [])
                total_updated_modified += len(getattr(result, 'updated_modified_files', []) or [])
                total_local_del += len(getattr(result, 'locally_deleted_files', []) or [])
            for _c in (res_data.get('panopto') or {}).get('changes', []):
                if _c.is_actionable:
                    total_panopto += 1

        total_updated = total_updated_clean + total_updated_modified
        # Panopto recordings count as changes too, so a course whose ONLY change is
        # a new/deleted recording still routes to Review instead of skipping it.
        total_changes = total_new + total_updated + total_local_del + total_panopto

        if st.session_state.get('debug_mode'):
            from core.canvas_debug import log_debug as _rv_log
            _rv_route = 'sync_complete (all up to date)' if total_changes == 0 else 'review screen (user selects files)'
            for _res_d in all_results:
                _rv_dbg = str(Path(_res_d['pair']['local_folder']) / 'debug_log.txt')
                _rv_log(f"--- Review Mode Tally ---", _rv_dbg)
                _rv_log(
                    f"New: {total_new} | Clean updates: {total_updated_clean} | "
                    f"Locally-edited: {total_updated_modified} | Locally-deleted: {total_local_del} | "
                    f"Panopto: {total_panopto} | Total changes: {total_changes}",
                    _rv_dbg,
                )
                _rv_log(f"→ Routing to: {_rv_route}", _rv_dbg)

        if total_changes == 0:
            # M-1: Persist auto-discovered / healed entries even though no
            # download will run, so an up-to-date folder builds its sync memory.
            _persist_discovered_entries(all_results)

            # Record WHAT was compared. "Nothing to sync" on its own reads like
            # the app might not have looked; "checked 412 files across 3
            # courses" is the same outcome with the evidence attached, and it is
            # the only number the user cannot get anywhere else once the run is
            # over. Panopto recordings are counted separately because they are
            # a different unit of work, not files.
            _checked_files = 0
            _checked_recordings = 0
            for _res in all_results:
                _r = _res.get('result')
                if _r is not None:
                    _checked_files += len(getattr(_r, 'uptodate_files', []) or [])
                _checked_recordings += len((_res.get('panopto') or {}).get('videos', []) or [])
            st.session_state['sync_uptodate_stats'] = {
                'files': _checked_files,
                'recordings': _checked_recordings,
                'courses': len(all_results),
            }

            # Nothing to review - skip review step, go straight to completion
            st.session_state['synced_count'] = 0
            st.session_state['download_status'] = 'sync_complete'
            # Pre-arm the flag so show_sync_complete doesn't fire a second notification.
            # M-3: Gate the beep on notifications_enabled so users who disabled
            # notifications don't still hear the sound.
            if st.session_state.get('notifications_enabled', True):
                _n_sum = (
                    f"Checked {_checked_files} file{'s' if _checked_files != 1 else ''} "
                    f"across {len(all_results)} course{'s' if len(all_results) != 1 else ''} "
                    "- nothing to download."
                ) if _checked_files else 'All files are up to date - nothing to download.'
                play_completion_beep(mode='sync_uptodate', summary=_n_sum)
            st.session_state['completion_beep_fired'] = True
            st.rerun()

        parts = []
        if total_new > 0:
            parts.append(f"{total_new} new file{'s' if total_new != 1 else ''}")
        if total_updated > 0:
            parts.append(f"{total_updated} update{'s' if total_updated != 1 else ''}")
        if total_updated_modified > 0:
            parts.append(f"{total_updated_modified} edited locally")
        if total_local_del > 0:
            parts.append(f"{total_local_del} file{'s' if total_local_del != 1 else ''} deleted locally")
        if total_panopto > 0:
            parts.append(f"{total_panopto} Panopto recording{'s' if total_panopto != 1 else ''}")

        summary = ", ".join(parts) + " found."
        # M-7 parity: respect the notifications toggle here too (the other
        # three play_completion_beep call sites are already gated).
        if st.session_state.get('notifications_enabled', True):
            play_completion_beep(mode='sync_review', summary=summary.strip())
        st.session_state['download_status'] = 'analyzed'
