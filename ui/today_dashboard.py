"""ui.today_dashboard - the "Today" page.

A daily home that:
  1. explains, in-page, what the daily sync does and how to set it up,
  2. lets the user curate which saved course/folder pairs participate in the
     daily sync - imported (and persisted, editable) from the Saved Groups &
     Pairs hub,
  3. toggles daily auto-sync (runs the first time the app opens each day, after 4am),
  4. offers a manual "Quick Sync now" of that same curated set,
  5. shows "today's files" downloaded, grouped per course (reusing the same
     interactive folder-card component as the sync-complete screen).

The actual syncing reuses the existing Quick Sync engine via core.auto_sync; this
module only renders the dashboard and kicks the wrapper off. While a daily sync is
running the app is on step 4 (render_sync_step4) showing a slim progress bar - the
user is routed back here on completion.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

import theme
from styles import inject_css
from ui_helpers import esc, friendly_course_name, get_base64_image, get_config_dir
from ui_shared import SVG_FOLDER_YELLOW


# Lucide calendar glyph (matches the sidebar "Today" nav icon).
_SVG_TITLE = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
    "stroke='#FFFFFF' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' "
    "style='width:1.4em;height:1.4em;vertical-align:-0.22em;'>"
    "<rect x='3' y='4' width='18' height='18' rx='2'/><line x1='16' y1='2' x2='16' y2='6'/>"
    "<line x1='8' y1='2' x2='8' y2='6'/><line x1='3' y1='10' x2='21' y2='10'/></svg>"
)
# Lucide layers glyph - muted, for the "no courses yet" empty state.
_SVG_EMPTY_COURSES = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
    "stroke='#5b6473' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' "
    "style='width:2rem;height:2rem;'>"
    "<polygon points='12 2 2 7 12 12 22 7 12 2'/><polyline points='2 17 12 22 22 17'/>"
    "<polyline points='2 12 12 17 22 12'/></svg>"
)
# Lucide check-circle glyph - green, for the "all caught up" empty state.
_SVG_CAUGHT_UP = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
    "stroke='#4ade80' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round' "
    "style='width:1.9rem;height:1.9rem;'>"
    "<path d='M22 11.08V12a10 10 0 1 1-5.93-9.14'/><polyline points='22 4 12 14.01 9 11.01'/></svg>"
)


def _inject_dynamic_css() -> None:
    """Button-icon + Quick-Sync brand styling (depends on base64 assets, so inline)."""
    b64_add = get_base64_image("assets/icon_add.png")
    b64_quick = get_base64_image("assets/icon_sync_quick.png")
    st.markdown(f"""<style>
    /* Add-courses button: custom add glyph (matches the hub's add buttons) */
    div.st-key-today_add_courses_btn button p::before {{
        content: "" !important;
        display: inline-block !important;
        position: relative !important;
        top: 2px !important;
        width: 16px !important; height: 16px !important;
        margin-right: 6px !important;
        background-image: url("data:image/png;base64,{b64_add}") !important;
        background-repeat: no-repeat !important;
        background-size: contain !important;
    }}
    /* Quick Sync now: identical to the canonical Quick Sync button (brand teal) */
    div.st-key-today_sync_now_btn button p::before {{
        content: "" !important;
        display: inline-block !important;
        position: relative !important;
        width: 18px !important; height: 18px !important;
        margin-right: 5px !important;
        background-image: url("data:image/png;base64,{b64_quick}") !important;
        background-repeat: no-repeat !important;
        background-size: contain !important;
    }}
    div.st-key-today_sync_now_btn button {{
        background: linear-gradient(135deg, #1e3a8a 0%, #06b6d4 100%) !important;
        border: none !important;
        color: #ffffff !important;
        box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3) !important;
        transition: filter 0.2s ease-in-out, box-shadow 0.2s ease-in-out !important;
    }}
    div.st-key-today_sync_now_btn button:hover {{
        filter: brightness(1.15) !important;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.2),
                    inset 0 1px 1px rgba(255, 255, 255, 0.4) !important;
        color: #ffffff !important;
    }}
    div.st-key-today_sync_now_btn button:disabled {{
        background: #3a3a3a !important;
        color: #6b6b6b !important;
        box-shadow: none !important;
        border: 1px solid #4a4a4a !important;
        filter: none !important;
    }}
    div.st-key-today_sync_now_btn button:disabled p::before {{
        filter: grayscale(100%) opacity(0.4) !important;
    }}
    </style>""", unsafe_allow_html=True)


def _entry_logical_date(ts: str) -> str:
    """Return the logical date (YYYY-MM-DD, day rolls at 4am) of a history entry."""
    from core.today_store import logical_date_of
    try:
        return logical_date_of(datetime.strptime(ts, "%Y-%m-%d %H:%M"))
    except Exception:
        return (ts or "")[:10]


def _todays_groups() -> list[dict]:
    """Aggregate this logical-day's synced files per course from sync history.

    Merges across multiple sync runs today, de-duplicating files by their
    on-disk relative path. Returns a list of
    ``{course_name, local_folder, files:[{name, rel, category}]}``.
    """
    from sync_manager import SyncHistoryManager
    from core.today_store import logical_today

    today = logical_today()
    history = SyncHistoryManager(get_config_dir()).load_history()

    merged: dict = {}
    for entry in history:
        if _entry_logical_date(entry.get("timestamp", "")) != today:
            continue
        for grp in entry.get("synced_groups", []) or []:
            key = (grp.get("course_id"), grp.get("local_folder"))
            agg = merged.setdefault(
                key,
                {
                    "course_name": grp.get("course_name", ""),
                    "local_folder": grp.get("local_folder", ""),
                    "files": [],
                    "_seen": set(),
                },
            )
            for rec in grp.get("files", []) or []:
                rel = rec.get("rel") or rec.get("name")
                if rel in agg["_seen"]:
                    continue
                agg["_seen"].add(rel)
                agg["files"].append(rec)

    out = []
    for agg in merged.values():
        agg.pop("_seen", None)
        if agg["files"]:
            out.append(agg)
    return out


# ── Import-from-hub dialog ──────────────────────────────────────────────────

def _toggle_import_cb(chk_key: str, pairs: list[dict]):
    """Add/remove a saved pair or group's pairs from the daily set on toggle."""
    from core.today_store import add_today_pairs, remove_today_pair
    if st.session_state.get(chk_key):
        add_today_pairs([
            {
                "course_id": p.get("course_id"),
                "course_name": p.get("course_name", ""),
                "local_folder": p.get("local_folder"),
            }
            for p in pairs
        ])
    else:
        for p in pairs:
            remove_today_pair(p.get("course_id"), p.get("local_folder"))


@st.dialog("​", width="large")
def _import_courses_dialog():
    """Pick saved groups & pairs from the hub to keep in the daily sync set.

    Card styling mirrors the Saved Groups & Pairs hub 1:1; the lower action area
    is replaced by a single checkbox that toggles membership in the daily sync.
    """
    from sync_manager import SavedGroupsManager
    from core.today_store import load_today_config
    from ui.amber_notice import render_amber_notice, render_info_notice

    # Hide the native close 'X' so closing is state-aware.
    st.markdown(
        '<style>div[data-testid="stDialog"] button[aria-label="Close"]'
        '{display:none !important;}</style>',
        unsafe_allow_html=True,
    )

    b64_pairs = get_base64_image("assets/icon_sync_pair.png")
    b64_groups = get_base64_image("assets/icon_sync_group.png")
    b64_hub = get_base64_image("assets/icon_sync_hub.png")

    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:12px; margin-top:-70px; margin-bottom:0;">
            <img src="data:image/png;base64,{b64_hub}" style="width:36px; height:36px;" />
            <div style="font-size:1.75rem; font-weight:600; color:white;">Add to your daily sync</div>
        </div>
        <p style="color:#aaa; font-size:0.9rem; margin:6px 0 12px 0;">
            Tick the saved pairs and groups you want kept up to date automatically.
            Your choice is saved - change it any time.
        </p>
        """,
        unsafe_allow_html=True,
    )

    mgr = SavedGroupsManager(get_config_dir())
    groups = list(reversed(mgr.load_groups()))

    if not groups:
        render_info_notice(
            "You haven't saved any groups or pairs yet.",
            detail="Open \"Sync Course Folders\", build a sync list, then use "
                   "\"Save as Pair\" / \"Save List as Group\". They'll appear here.",
        )
        if st.button("Close", type="secondary", use_container_width=True,
                     key="today_import_done"):
            st.rerun(scope="app")
        return

    daily_sigs = {
        (p["course_id"], p["local_folder"]) for p in load_today_config()["pairs"]
    }

    with st.container(height=460, border=False):
        for g_idx, group in enumerate(groups):
            is_sp = group.get("is_single_pair", False)
            pairs = group.get("pairs", []) or []
            gid = group.get("group_id", str(g_idx))
            chk_key = f"today_imp_chk_{gid}"
            fully = bool(pairs) and all(
                (p.get("course_id"), p.get("local_folder")) in daily_sigs
                for p in pairs
            )
            any_missing = any(
                p.get("local_folder") and not Path(p["local_folder"]).exists()
                for p in pairs
            )

            with st.container(border=True, key=f"today_import_item_{g_idx}"):
                if is_sp:
                    pair = pairs[0] if pairs else {}
                    display_name = friendly_course_name(
                        pair.get("course_name", group["group_name"]))
                    title_html = (
                        f"<img src='data:image/png;base64,{b64_pairs}' "
                        f"style='width:24px;height:24px;vertical-align:middle;"
                        f"margin-right:8px;margin-top:-4px;' />{esc(group['group_name'])}"
                    )
                    st.markdown(
                        f"<div style='margin-bottom:10px;'>"
                        f"<div style='display:flex; justify-content:space-between; "
                        f"align-items:flex-start; margin-bottom:6px;'>"
                        f"<div style='font-size:1.25rem; font-weight:600; "
                        f"color:{theme.WHITE}; line-height:1.2;'>{title_html}</div>"
                        f"<div style='font-size:0.75rem; color:rgba(255,255,255,0.5); "
                        f"font-weight:500; letter-spacing:0.5px;'>Pair</div></div>"
                        f"<div style='color:#a3a8b8; font-size:0.9rem;'>"
                        f"Course: {esc(display_name)}</div></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    n = len(pairs)
                    title_html = (
                        f"<img src='data:image/png;base64,{b64_groups}' "
                        f"style='width:24px;height:24px;vertical-align:middle;"
                        f"margin-right:8px;margin-top:-4px;' />{esc(group['group_name'])}"
                    )
                    st.markdown(
                        f"<div style='margin-bottom:10px;'>"
                        f"<div style='display:flex; justify-content:space-between; "
                        f"align-items:flex-start;'>"
                        f"<div style='font-size:1.25rem; font-weight:600; "
                        f"color:{theme.WHITE}; line-height:1.2;'>{title_html}</div>"
                        f"<div style='font-size:0.75rem; color:rgba(255,255,255,0.5); "
                        f"font-weight:500; letter-spacing:0.5px;'>Group</div></div></div>",
                        unsafe_allow_html=True,
                    )
                    with st.expander(f"{n} course{'s' if n != 1 else ''}"):
                        st.markdown("\n".join(
                            f"- {friendly_course_name(p.get('course_name', 'Unknown'))}"
                            for p in pairs
                        ) or "*No courses in this group*")

                if any_missing:
                    render_amber_notice(
                        "One or more folders are missing or moved.",
                        detail="Those courses are skipped during sync. Re-link the "
                               "folder in Sync Course Folders to fix it.",
                        margin="0 0 10px 0",
                    )

                if chk_key not in st.session_state:
                    st.checkbox("Add to daily sync", value=fully, key=chk_key,
                                on_change=_toggle_import_cb, args=(chk_key, pairs))
                else:
                    st.checkbox("Add to daily sync", key=chk_key,
                                on_change=_toggle_import_cb, args=(chk_key, pairs))

    if st.button("Done", type="primary", use_container_width=True,
                 key="today_import_done"):
        st.session_state["today_toast"] = "Daily sync updated."
        st.rerun(scope="app")


def _open_import_dialog():
    """Clear stale checkbox state, then open the import dialog.

    Clearing ``today_imp_chk_*`` ensures every open reflects current membership
    (Streamlit ignores a widget's ``value=`` once its key is in session_state).
    """
    for k in [k for k in st.session_state if k.startswith("today_imp_chk_")]:
        st.session_state.pop(k, None)
    _import_courses_dialog()


# ── Callbacks ───────────────────────────────────────────────────────────────

def _remove_daily_pair_cb(course_id, local_folder, name):
    from core.today_store import remove_today_pair
    remove_today_pair(course_id, local_folder)
    st.session_state["today_toast"] = f"Removed '{name}' from your daily sync."


# ── Page ────────────────────────────────────────────────────────────────────

def render_today_dashboard(fetch_courses_fn=None):
    """Render the Today dashboard page (current_mode == 'today', step == 1)."""
    from core.today_store import load_today_config, set_auto_sync_enabled
    from core.auto_sync import resolve_today_pairs, start_today_sync

    # We're on the dashboard, so any prior daily run (incl. a cancelled one that
    # routed back via qs_cancel_route) is over - clear the slim-UI marker.
    st.session_state.pop("today_sync_active", None)

    inject_css("today.css")
    _inject_dynamic_css()

    if "today_toast" in st.session_state:
        st.toast(st.session_state.pop("today_toast"))

    cfg = load_today_config()
    daily_pairs = cfg["pairs"]

    # ── Header ──────────────────────────────────────────────────────────────
    st.markdown(
        f"<div class='today-title'>{_SVG_TITLE}<span>Today</span></div>"  # audit-ignore: static SVG constant
        f"<p class='today-subtitle'>Your daily course catch-up, in one place.</p>",
        unsafe_allow_html=True,
    )

    # ── How it works ────────────────────────────────────────────────────────
    st.markdown(
        """
        <div class="today-explainer">
            <div class="today-explainer-head">Set it once, stay caught up</div>
            <div class="today-explainer-body">
                Today keeps your chosen courses up to date for you - new slides,
                readings and recordings are downloaded into their folders, ready
                whenever you need them.
            </div>
            <div class="today-steps">
                <div class="today-step"><span class="today-step-num">1</span>
                    <span>In <b>Sync Course Folders</b>, pair your courses with folders and
                    save them as a <b>Pair</b> or <b>Group</b>.</span></div>
                <div class="today-step"><span class="today-step-num">2</span>
                    <span>Use <b>Add courses</b> below to import those into your daily sync
                    - your choice is saved and editable.</span></div>
                <div class="today-step"><span class="today-step-num">3</span>
                    <span>Turn on <b>Daily auto-sync</b>, or run <b>Quick Sync now</b>
                    whenever you like.</span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Daily auto-sync toggle ──────────────────────────────────────────────
    def _on_toggle():
        set_auto_sync_enabled(st.session_state.get("today_auto_toggle", False))

    with st.container(key="today_toggle_card"):
        st.toggle(
            "Daily auto-sync",
            value=cfg["auto_sync_enabled"],
            key="today_auto_toggle",
            on_change=_on_toggle,
            help=(
                "When on, the app automatically syncs your selected courses the first "
                "time you open it each day (after 4am). New lecture files are waiting "
                "for you - no clicks needed."
            ),
        )
        st.markdown(
            "<div class='today-toggle-desc'>Syncs the courses below automatically the "
            "first time you open Canvas Downloader each day (after 4 AM).</div>",
            unsafe_allow_html=True,
        )

    # ── Courses in your daily sync ──────────────────────────────────────────
    st.markdown(
        "<div class='today-section-label'>Courses in your daily sync</div>"
        "<div class='today-section-sub'>Kept up to date automatically. Imported "
        "from your Saved Groups &amp; Pairs.</div>",
        unsafe_allow_html=True,
    )

    if not daily_pairs:
        st.markdown(
            f"<div class='today-empty'>"
            f"<div class='today-empty-icon'>{_SVG_EMPTY_COURSES}</div>"  # audit-ignore: static SVG constant
            f"<div>No courses in your daily sync yet.</div>"
            f"<div class='today-empty-sub'>Use <b>Add courses</b> to import saved "
            f"pairs or groups.</div></div>",
            unsafe_allow_html=True,
        )
    else:
        any_missing = False
        for i, pair in enumerate(daily_pairs):
            folder = pair.get("local_folder", "")
            name = friendly_course_name(pair.get("course_name") or "Course")
            exists = bool(folder) and Path(folder).exists()
            if not exists:
                any_missing = True
            with st.container(border=True, key=f"today_pair_card_{i}"):
                col_info, col_rm = st.columns([0.84, 0.16],
                                              vertical_alignment="center")
                with col_info:
                    st.markdown(
                        f"<div class='today-pair-name'>{esc(name)}</div>"
                        f"<div class='today-pair-folder'>{SVG_FOLDER_YELLOW}"  # audit-ignore: static SVG constant
                        f"{esc(folder)}</div>",  # audit-ignore: folder is a local path
                        unsafe_allow_html=True,
                    )
                with col_rm:
                    st.button(
                        "Remove", key=f"today_remove_{i}", use_container_width=True,
                        on_click=_remove_daily_pair_cb,
                        args=(pair.get("course_id"), folder, name),
                    )
        if any_missing:
            from ui.amber_notice import render_amber_notice
            render_amber_notice(
                "Some folders are missing or were moved.",
                detail="Those courses are skipped during sync. Remove them here, or "
                       "re-link the folder in Sync Course Folders.",
                margin="10px 0 4px 0",
            )

    # ── Add courses + Quick Sync now ────────────────────────────────────────
    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    col_add, col_sync = st.columns([1, 1])
    with col_add:
        if st.button("Add courses", use_container_width=True,
                     key="today_add_courses_btn"):
            _open_import_dialog()
    with col_sync:
        runnable = resolve_today_pairs()
        if st.button("Quick Sync now", type="primary", use_container_width=True,
                     key="today_sync_now_btn", disabled=not runnable):
            start_today_sync(runnable)  # sets state + st.rerun()

    st.markdown(
        "<div class='today-qs-note'>Runs the same <b>Quick Sync</b> as "
        "\"Sync Course Folders\", over just your daily courses.</div>",
        unsafe_allow_html=True,
    )

    # ── Today's files (per course) ──────────────────────────────────────────
    st.markdown(
        f"<hr style='border:none; border-top:1px solid {theme.BG_CARD}; "
        f"margin:26px 0 14px 0;'>"
        f"<div class='today-section-label'>Today's files</div>"
        f"<div class='today-section-sub'>Everything downloaded today, grouped by "
        f"course.</div>",
        unsafe_allow_html=True,
    )

    groups = _todays_groups()
    if not groups:
        st.markdown(
            f"<div class='today-empty'>"
            f"<div class='today-empty-icon'>{_SVG_CAUGHT_UP}</div>"  # audit-ignore: static SVG constant
            f"<div>No new files today - you're all caught up.</div></div>",
            unsafe_allow_html=True,
        )
        return

    from ui_shared import render_folder_cards
    file_details: dict = {}
    folder_paths: dict = {}
    file_records: dict = {}
    for idx, grp in enumerate(groups):
        # Unique key per course (suffix the index so duplicate display names
        # across folders never collide).
        f_key = f"{friendly_course_name(grp['course_name'])} ({idx})"
        file_details[f_key] = [r.get("name", "") for r in grp["files"]]
        folder_paths[f_key] = grp["local_folder"]
        file_records[f_key] = grp["files"]

    render_folder_cards(
        file_details, folder_paths,
        key_prefix="today", show_files_expander=True,
        file_records=file_records,
    )
