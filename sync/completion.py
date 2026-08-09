"""
sync.completion - Sync completion, cancellation, and error display.

Extracted from ``sync_ui.py`` L5044-5298 (Phase 4).
Strict physical move - NO logic changes.

Contains:
  - ``show_sync_cancelled()``  (was ``_show_sync_cancelled``)
  - ``show_sync_complete()``   (was ``_show_sync_complete``)
  - ``view_error_log_dialog()`` (was ``_view_error_log_dialog``)
  - ``show_sync_errors()``     (was ``_show_sync_errors``)
"""

from __future__ import annotations

import streamlit as st

from core.sync_manager import SyncManager
from shared.helpers import (
    render_sync_wizard,
    friendly_course_name,
    split_delivery_errors,
)
from shared.components import (
    render_completion_card, render_folder_cards,
    render_pp_warning, render_error_section,
    render_archives_skipped_notice, render_panopto_disabled_notice,
    fresh_container,
)
from core.state_registry import cleanup_sync_state
from engine.notifications import play_completion_beep


def build_newversion_notice(records) -> dict | None:
    """Copy for "we saved a second copy instead of overwriting yours".

    Returns ``None`` when there is nothing to say, so the caller never renders
    an empty card.

    This is the one sync outcome that silently ADDS a file to the user's folder,
    and the copy that keeps the familiar name is the OLD one. Two routes reach
    it - the file was open in another program, or the user had edited it - and
    the folder looks identical either way, so one notice covers both. It is
    INFO, not a warning: nothing failed, the app protected work in progress.

    The copy states three things in order, because that is the order the
    questions occur: what happened, how to recognise the new file, and what to
    do about it. It deliberately does not explain WHY per file - the reason
    ("open" vs "edited") is not something the user needs in order to act, and
    splitting the notice in two would make a tidy outcome look like two
    problems.
    """
    records = [r for r in (records or []) if isinstance(r, dict)]
    n = len(records)
    if not n:
        return None
    example = next((r.get("name") for r in records if r.get("name")), "")
    one = n == 1
    message = (f"{n} {'file was' if one else 'files were'} saved as a separate "
               f"copy so we didn't overwrite your version.")
    detail = (
        f"You had {'this file' if one else 'these files'} open or edited, so the "
        f"new version from Canvas was saved next to {'it' if one else 'them'} "
        f"with \"_NewVersion\" in the name"
        + (f" (for example: {example})." if example else ".")
        + " Your copy is untouched - compare the two and keep whichever you "
          "want, then delete the other."
    )
    return {"message": message, "detail": detail, "count": n, "example": example}


def show_sync_cancelled():
    """Render the sync-cancelled screen (summary card only, no error list)."""
    render_sync_wizard(st, 'sync')

    from shared.components import quit_office_once, render_cancelled_card
    quit_office_once()

    render_cancelled_card(
        "Sync",
        done=st.session_state.get('sync_cancelled_file_count', 0),
        total=sum(
            len(sel['new']) + len(sel['updates']) + len(sel['redownload'])
            for sel in st.session_state.get('sync_selections', [])
        ),
    )

    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    col_front, _ = st.columns([0.35, 0.65])
    with col_front:
        if st.button('Go to front page', key="page_nav_front_page_sync", type="primary", use_container_width=True):
            _cleanup_sync_state()
            st.rerun()


def show_sync_complete():
    """Render the sync-complete screen with results and retry options."""
    # Completion beep - fired exactly once per sync via session sentinel.
    # cleanup_sync_state() resets this flag, so the next sync rearms it.
    if (
        st.session_state.get('notifications_enabled', True)
        and not st.session_state.get('completion_beep_fired', False)
    ):
        _sync_count = st.session_state.get('synced_count', 0)
        if _sync_count == 0:
            _is_qs = st.session_state.get('sync_quick_mode', False)
            _notif_mode = 'quick_sync_uptodate' if _is_qs else 'sync_uptodate'
            play_completion_beep(mode=_notif_mode, summary='All files are up to date - nothing to download.')
        else:
            _sync_courses = len(st.session_state.get('sync_selections', []))
            _sync_summary = f"Synced {_sync_count} file{'s' if _sync_count != 1 else ''} across {_sync_courses} course{'s' if _sync_courses != 1 else ''}."
            play_completion_beep(mode='sync', summary=_sync_summary)
        st.session_state['completion_beep_fired'] = True

    # macOS: sync + post-processing are done and we're on the completion screen
    # - quit the Office apps launched for conversion now (only those with zero
    # open documents). Separate one-shot sentinel so it fires regardless of the
    # notifications toggle, and is re-armed at the top of run_sync.
    import sys as _sys_q
    if _sys_q.platform == 'darwin' and not st.session_state.get('_office_quit_fired'):
        st.session_state['_office_quit_fired'] = True
        try:
            from engine.applescript_bridge import quit_idle_office_apps
            quit_idle_office_apps()
        except Exception:
            pass

    # Step wizard
    render_sync_wizard(st, 'complete')
    st.markdown('<h2 class="step-header">Sync Complete!</h2>', unsafe_allow_html=True)

    synced_count = st.session_state.get('synced_count', 0)
    sync_errors = st.session_state.get('sync_errors', [])
    synced_details = st.session_state.get('synced_details', {})
    sync_selections = st.session_state.get('sync_selections', [])

    # Summary card logic
    total_bytes = st.session_state.get('synced_bytes', 0)
    
    size_skipped = st.session_state.get('size_skipped_files', [])
    limit_mb = st.session_state.get('max_file_size_mb', 0)

    # The run screens put their progress dashboard right about here, and
    # Streamlit hands a block landing on another block's index that block's
    # CHILDREN - the run's metrics row + terminal log rendered inside the
    # completion card until the run ended (measured pre-fix: card 537px
    # mid-run, 157px after). These empties tear those nodes down instead, and
    # cost nothing: the screen measures identically with and without them. See
    # shared.components.fresh_container for the full mechanism.
    #
    # TWO slots because run_sync has one CONDITIONAL element before its
    # dashboard: the macOS first-run permission notice (_tcc_batch_active).
    # Without the notice the dashboard sits on the first empty, with it on the
    # second - covered either way.
    st.empty()
    with fresh_container(border=True, key='completion_dashboard'):
        # sync_errors is list[str], but they are NOT all retriable: the engine
        # writes a distinct sentence for a teacher-locked file and for an LTI
        # stream, and neither can ever succeed. Counting them as failures turned
        # a clean sync amber. Classified by the same function the download screen
        # uses, off constants the producer shares - see
        # shared.helpers.split_delivery_errors.
        _sync_split = split_delivery_errors(sync_errors)
        _sync_retriable = _sync_split['retriable']
        _sync_unresolvable = _sync_split['unresolvable']

        _retry_attempted = st.session_state.get('retry_attempted', False)
        _retry_total = st.session_state.get('retry_total_attempted', 0)
        _retry_resolved = st.session_state.get('retry_resolved_count', 0)

        render_completion_card(
            synced_count=synced_count,
            error_count=len(sync_errors),
            total_bytes=total_bytes,
            mode='sync',
            size_skipped_files=size_skipped,
            size_limit_mb=limit_mb,
            retriable_count=_sync_retriable,
            unresolvable_count=_sync_unresolvable,
            courses_count=len(sync_selections),
            retry_attempted=_retry_attempted,
            retry_resolved=_retry_resolved,
            # Rendered INSIDE the card, right under the stat grid - it is a
            # stat grid too. See the ordering note there.
            panopto_summary=st.session_state.get('panopto_summary'),
        )

        # THE ORDER IS BY KIND, and it matches the download screen exactly:
        # stats -> Panopto stats -> every collapsible -> every notice. It used
        # to be the order the features were built in, so an amber warning sat
        # between two expanders and the Panopto stat grid sat below both.
        #
        # EXPANDERS. The size-skip panel comes from render_completion_card
        # above; archives follow it, then the Panopto-off panel (the third
        # member of the same "deliberately left alone" family), and the error
        # panel is last because it is the one the user opens.
        render_archives_skipped_notice()
        render_panopto_disabled_notice(mode='sync')

        retry_selections = st.session_state.get('retry_selections', [])

        # Retry callback
        def _do_sync_retry():
            for r_sel in retry_selections:
                pair_info = r_sel['res_data']['pair']
                r_sel['res_data']['course'] = None
                try:
                    new_sm = SyncManager(
                        local_path=pair_info['local_folder'],
                        course_id=pair_info['course_id'],
                        course_name=pair_info['course_name']
                    )
                    # M-9: A SyncManager with _db_init_failed=True is non-None but
                    # unusable - all DB writes silently fail. Treat it as None so
                    # execution.py's `if sync_mgr is None: continue` guard fires.
                    r_sel['res_data']['sync_manager'] = (
                        None if getattr(new_sm, '_db_init_failed', False) else new_sm
                    )
                except Exception:
                    r_sel['res_data']['sync_manager'] = None

            # Record how many errors we're sending to retry so execution.py
            # can compute retry_resolved_count on the way out.
            st.session_state['retry_total_attempted'] = len(sync_errors)

            st.session_state['sync_selections'] = retry_selections
            st.session_state['download_status'] = 'syncing'
            st.session_state['step'] = 4
            st.session_state['sync_errors'] = []
            st.session_state['sync_cancel_requested'] = False
            st.session_state['sync_cancelled'] = False
            # Drop any cached worker snapshot so the retry submits a fresh
            # download batch instead of replaying the previous run's result.
            st.session_state.pop('sync_worker_result', None)
            st.rerun()

        _has_sync_retry = bool(sync_errors and retry_selections)
        _sync_retry_failed = _retry_attempted and _retry_total > 0 and _retry_resolved == 0

        render_error_section(
            sync_errors,
            key_prefix='sync_complete',
            retry_btn_callback=_do_sync_retry if _has_sync_retry else None,
            has_retriable_errors=_has_sync_retry,
            retry_failed=_sync_retry_failed,
        )
        # (The "Retry didn't work" guidance now lives inside render_error_section
        #  itself, so download mode gets it too - see that function.)

        # NOTICES, last, as one block. Everything above is a metric or a
        # collapsible; these are the run's asides, and interleaving them
        # broke both groups. Same rule, same order, on app.py's screen.
        # UN-TRAPPED QUICK SYNC WARNING:
        skipped_data = st.session_state.get('qs_skipped', {})
        local_del = skipped_data.get('local_del', 0)
        canvas_del = skipped_data.get('canvas_del', 0)
        edited = skipped_data.get('edited', 0)
        filtered = skipped_data.get('filtered', 0)
        pan_local_del = skipped_data.get('panopto_local_del', 0)

        if local_del > 0 or canvas_del > 0 or edited > 0 or filtered > 0 or pan_local_del > 0:
            parts = []
            if edited > 0:
                parts.append(f"{edited} {'file' if edited == 1 else 'files'} you edited locally")
            if local_del > 0:
                parts.append(f"{local_del} {'file' if local_del == 1 else 'files'} deleted locally")
            if pan_local_del > 0:
                parts.append(f"{pan_local_del} Panopto recording{'s' if pan_local_del != 1 else ''} deleted locally")
            if canvas_del > 0:
                parts.append(f"{canvas_del} {'file' if canvas_del == 1 else 'files'} deleted on Canvas")
            if filtered > 0:
                # M-5: files hidden by this course's saved file-type filter
                # (e.g. "study materials only") - surfaced instead of silently dropped.
                parts.append(f"{filtered} {'file' if filtered == 1 else 'files'} outside this course's file-type filter")

            joined_parts = " and ".join(parts)
            from ui.amber_notice import render_amber_notice
            render_amber_notice(
                f"Quick Sync skipped {joined_parts}.",
                icon="⚠️",
                detail="To download them, run a normal 'Analyze, Review & Sync' and select them manually.",
                margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
            )

            # Cleanup
            if 'qs_skipped' in st.session_state:
                del st.session_state['qs_skipped']

        # Post-processing failure warning
        render_pp_warning(st.session_state.get('pp_failure_count', 0))
        render_archives_skipped_notice()
        render_panopto_disabled_notice(mode='sync')

        # L-12: Warn user when Office watchdog did a broad /IM kill (may have
        # closed other open Office documents the user had open independently).
        if st.session_state.pop('pp_force_kill_warning', False):
            from ui.amber_notice import render_amber_notice
            render_amber_notice(
                "An Office process was force-closed during conversion.",
                icon="⚠️",
                detail=(
                    "A hung Office process was terminated to unblock conversion. "
                    "If you had other unsaved Word, Excel, or PowerPoint files open, "
                    "they may have been closed without saving."
                ),
                margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
            )

        # Surface Structural Discovery Errors gracefully
        total_structural_errors = sum(
            res['res_data']['result'].structural_errors
            for res in st.session_state.get('sync_selections', [])
            if res.get('res_data') and 'result' in res['res_data'] and hasattr(res['res_data']['result'], 'structural_errors')
        )
        if total_structural_errors > 0:
            from ui.amber_notice import render_amber_notice
            # `margin=` is NOT optional here. Every other notice on this screen
            # passes "12px 0 2px 0"; this one used the function default
            # ("4px 0 20px 0") and so opened a 48px gap below itself where its
            # neighbours sit 22-30px apart. The break lands directly above the
            # first INFO notice, which is why it reads as the blue cards being
            # spaced wrongly rather than as this amber one being too tall.
            render_amber_notice(
                f"{total_structural_errors} module(s) or folder(s) could not be fetched from Canvas due to connection/server errors. Their files are consequently missing from the syncing checklist and cannot be isolated for a targeted retry. A full Rescan is recommended later.",
                icon="⚠️",
                margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
            )

        # Ignored files note. INFO, not a warning: files are only in this state
        # because the user deliberately put them there, so the sync did exactly
        # what was asked. An amber "⚠️" implied something had gone wrong.
        if st.session_state.get('sync_has_ignored_files'):
            from ui.amber_notice import render_info_notice
            render_info_notice(
                "Some files were skipped because you ignored them.",
                detail="You can manage ignored files from the Sync Hub.",
                margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
            )

        # "_NewVersion" note. INFO for the same reason as the one above: nothing
        # went wrong - the app protected a file the user was working on. But it
        # is the one outcome that silently ADDS a file to their folder, and the
        # copy keeping the familiar name is the OLD one, so saying nothing left
        # them to discover a duplicate and guess which was current.
        _newver = build_newversion_notice(
            st.session_state.get('sync_newversion_files'))
        if _newver:
            from ui.amber_notice import render_info_notice
            # margin="0" - the card's flex gap (16px) is the ONE rhythm; a
            # margin here adds to it. This call site was missed by the earlier
            # pass because the string search there matched the trailing comma
            # every OTHER call had, and this one - the last keyword argument
            # before the closing paren - has none: measured 28px above this
            # notice's own painted box against 16px everywhere else on the
            # same screen.
            render_info_notice(_newver["message"], detail=_newver["detail"],
                               margin="0")

    # Folders updated - card style with filetype summary
    file_dropdown_details = {}
    folder_paths_map = {}
    file_records_map = {}

    # Per-course breakdown (resolved rel paths + categories) built at finalize -
    # powers the per-file Open / Reveal actions on each folder card.
    synced_groups = st.session_state.get('synced_groups', [])
    groups_by_pair = {g.get('pair_idx'): g for g in synced_groups}

    if sync_selections:
        for sel in sync_selections:
            pair_idx = sel['pair_idx']
            # H-6: read the pair from the selection itself. Indexing the global
            # sync_pairs list with pair_idx attributed files to the WRONG course
            # card whenever analysis had skipped a pair (missing folder / error)
            # and the indexes drifted apart.
            pair = sel.get('res_data', {}).get('pair', {})
            if not pair.get('local_folder'):
                continue
            # NOT a display value - render_folder_cards titles each card with
            # short_path(folder), so this string is only a dict key and the
            # "(pair_idx)" suffix is what actually makes it unique. Kept on the
            # Canvas name deliberately: resolving a user label here would imply
            # it reaches the screen, and it does not.
            display_name = friendly_course_name(pair.get('course_name', ''))

            f_key = f"{display_name} ({pair_idx})"
            file_dropdown_details[f_key] = synced_details.get(pair_idx, [])
            folder_paths_map[f_key] = pair['local_folder']
            file_records_map[f_key] = groups_by_pair.get(pair_idx, {}).get('files', [])

    render_folder_cards(
        file_dropdown_details, folder_paths_map,
        key_prefix='sync_complete', show_files_expander=True,
        file_records=file_records_map,
    )

    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    col_front, _ = st.columns([0.35, 0.65])
    with col_front:
        if st.button('Go to front page', key='page_nav_front_page_sync_complete', type="primary", use_container_width=True):
            _cleanup_sync_state()
            st.rerun()





def show_sync_errors():
    """Render sync errors in an expander with error log viewer button."""
    # Size-skipped files are now rendered inside render_completion_card

    sync_errors = st.session_state.get('sync_errors', [])
    if sync_errors:
        # The summary card handles the warning/error banner.
        # Here we just show the details expander.
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        with st.expander("📋 " + 'View Error Details', expanded=True):
            for err in sync_errors[:20]:
                st.markdown(f"❌ {err}")
            if len(sync_errors) > 20:
                st.caption(f"  ... and {len(sync_errors) - 20} more")

            if st.session_state.get('error_log_enabled', False):
                st.caption('📄 Full error details are saved in `download_errors.txt` in each course folder.')

def _cleanup_sync_state():
    """Backward-compatible alias for cleanup_sync_state."""
    cleanup_sync_state()
