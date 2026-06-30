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
from ui_shared import SVG_FOLDER_YELLOW, render_help_card, HELP_ICONS


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


# ── Built-in help card (replaces the inline 1-2-3 explainer) ────────────────

_TODAY_HELP_TITLE = "How the Today page works"
_TODAY_HELP_TEXT = (
    # -- Introduction --------------------------------------------------------
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.85); line-height: 1.7; margin-bottom: 12px;'>"
    f"The <b style='color: #ffffff;'>Today</b> page is your daily home for keeping the courses you care about up to date - new slides, readings and lecture recordings are downloaded straight into their folders, ready whenever you need them. <br>"
    f"Set it up once: pick which of your saved course folders should be kept current, then either let <b style='color: #ffffff;'>Daily auto-sync</b> handle it for you every morning, or run <b style='color: #3fd9ff;'>{HELP_ICONS['bolt']} Quick Sync now</b> whenever you like."
    "</div>"
    "<hr>"

    # -- Getting set up ------------------------------------------------------
    "<details style='margin-top: 4px;' open>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['folder']} Setting up your daily sync</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='display: flex; flex-direction: column; gap: 12px; margin-bottom: 8px;'>"

    "<div>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 4px;'>{HELP_ICONS['sync_pair']} 1. Save your course pairs</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "In <b style='color: #ffffff;'>Sync Course Folders</b> (Sync mode), link each course to a folder on your computer and save it as a <b style='color: #ffffff;'>Pair</b>, or save several together as a <b style='color: #ffffff;'>Group</b> (e.g. <em>Semester 1</em>). These live in your Saved Groups &amp; Pairs hub."
    "</div></div>"

    "<div>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 4px;'>{HELP_ICONS['sync_hub']} 2. Add them to your daily sync</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Click <b style='color: #ffffff;'>Add courses</b> below and tick the saved pairs and groups you want kept up to date. Your choice is saved and editable - come back any time to add or remove courses with <b style='color: #ffffff;'>Add courses</b> or the <b style='color: #ffffff;'>Remove</b> button on each card."
    "</div></div>"

    "<div>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 4px;'>{HELP_ICONS['bolt']} 3. Let it run</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Turn on <b style='color: #ffffff;'>Daily auto-sync</b> to have the app sync your chosen courses automatically the first time you open it each day (after 4 AM), or press <b style='color: #ffffff;'>Quick Sync now</b> to catch up on demand."
    "</div></div>"

    "</div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- Auto-sync vs Quick Sync ---------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['compare']} Daily auto-sync vs Quick Sync now</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='display: flex; gap: 16px; margin-bottom: 8px;'>"
    "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>{HELP_ICONS['calendar']} Daily auto-sync</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Runs by itself the first time you open Canvas Downloader each day (after 4 AM), over the courses listed below. Switch it on and forget about it - your folders are quietly kept current in the background."
    "</div></div>"
    "<div style='flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 7px; padding: 11px 13px;'>"
    f"<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 7px;'>{HELP_ICONS['bolt']} Quick Sync now</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Runs the exact same <b style='color: #ffffff;'>Quick Sync</b> as Sync Course Folders, but only over your daily courses - on demand, the moment you click it. Great for a mid-day catch-up between lectures."
    "</div></div>"
    "</div>"
    "<div style='font-size: 0.8rem; color: rgba(255,255,255,0.7); line-height: 1.5;'>"
    "Both grab new files and safe updates automatically and skip anything you've edited, deleted or ignored - the same safe behaviour as Quick Sync in Sync mode."
    "</div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- Today's files -------------------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['download']} Today's files</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65;'>"
    "Everything downloaded today is listed at the bottom of the page, grouped by course. Click a course to expand it and see the individual files, or use <b style='color: #ffffff;'>Open Folder</b> to jump straight to it. <br>"
    "If you've already got everything, you'll see a friendly “all caught up” message instead."
    "</div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- Managing pairs ------------------------------------------------------
    "<details style='margin-top: 4px;'>"
    f"<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>{HELP_ICONS['wrench']} Managing &amp; fixing your courses</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65;'>"
    "The courses on this page come from your Saved Groups &amp; Pairs. To rename a course, change its folder, or fix a folder that was moved or deleted, head to <b style='color: #ffffff;'>Sync mode → Saved Groups &amp; Pairs</b>. <br>"
    "If a course's folder can't be found, it's automatically hidden from the list here and skipped during sync so it never gets in your way - re-link it in the hub to bring it back."
    "</div>"
    "</div>"
    "</details>"
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

def _css_escape_content(text: str) -> str:
    """Escape a string for safe use inside a CSS quoted string (content: "...")."""
    return text.replace('\\', '\\\\').replace('"', '\\"')


# White checkmark badge - mirrors the Card 2/3 "active checkbox" pattern in
# ui/download_settings.py, recoloured to a neutral white/grey theme (matches
# the Saved Groups & Pairs hub cards) instead of a brand accent colour.
_IMPORT_CHECK_SVG = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 24 24'%3E%3Cdefs%3E%3Cmask id='m'%3E%3Crect width='24' "
    "height='24' fill='white'/%3E%3Cpath d='M20 6L9 17l-5-5' fill='none' "
    "stroke='black' stroke-width='4' stroke-linecap='round' "
    "stroke-linejoin='round'/%3E%3C/mask%3E%3C/defs%3E%3Crect width='24' "
    "height='24' rx='5' fill='%23ffffff' mask='url(%23m)'/%3E%3C/svg%3E\")"
)

# White-overlay ladder (idle -> hover -> selected -> selected+hover), the same
# "darkgrey to white" technique the Saved Groups & Pairs hub cards use
# (styles/sync_hub.css `hub_pair_card_`: rgba(255,255,255,0.05) on a dark
# background reads as dark grey; raising the alpha reads as progressively
# lighter/whiter without introducing a separate accent colour).
_CARD_IDLE_BG = "rgba(255, 255, 255, 0.05)"
_CARD_IDLE_BORDER = "rgba(255, 255, 255, 0.15)"
_CARD_IDLE_HOVER_BG = "rgba(255, 255, 255, 0.10)"
_CARD_IDLE_HOVER_BORDER = "rgba(255, 255, 255, 0.32)"
_CARD_SEL_BG = "rgba(255, 255, 255, 0.16)"
_CARD_SEL_BORDER = "rgba(255, 255, 255, 0.48)"
_CARD_SEL_HOVER_BG = "rgba(255, 255, 255, 0.24)"
_CARD_SEL_HOVER_BORDER = "rgba(255, 255, 255, 0.65)"
_CHECK_IDLE_BORDER = "2px solid rgba(255, 255, 255, 0.35)"
_CHECK_HOVER_BORDER = "rgba(255, 255, 255, 0.65)"


def _toggle_import_btn(sel_key: str, pairs: list[dict]):
    """Flip a saved pair/group's daily-sync membership when its card is clicked."""
    from core.today_store import add_today_pairs, remove_today_pair
    new_state = not st.session_state.get(sel_key, False)
    st.session_state[sel_key] = new_state
    if new_state:
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

    Each card is a native st.button styled as a whole-card toggle (mirrors the
    "Canvas Content" card pattern in ui/download_settings.py): clicking
    anywhere on the card toggles its membership in the daily sync, with a
    checkbox indicator that fills in with a checkmark when selected.
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

    # Proactively hide any saved pair/group with a missing or moved folder so the
    # user only picks from healthy entries; they're told once, below, where to fix it.
    selectable, hidden_count = [], 0
    for g_idx, group in enumerate(groups):
        any_missing = any(
            p.get("local_folder") and not Path(p["local_folder"]).exists()
            for p in (group.get("pairs", []) or [])
        )
        if any_missing:
            hidden_count += 1
        else:
            selectable.append((g_idx, group))

    if hidden_count:
        _noun = "saved pair/group" if hidden_count == 1 else "saved pairs/groups"
        _verb = "is" if hidden_count == 1 else "are"
        render_amber_notice(
            f"{hidden_count} {_noun} {_verb} hidden because a folder is missing or "
            f"was moved.",
            detail="Fix the folder in Sync mode → Saved Groups & Pairs to make it "
                   "available here again.",
            margin="0 0 12px 0",
        )

    if not selectable:
        render_info_notice(
            "No saved pairs or groups are available to add right now.",
            detail="Every saved entry currently has a missing folder. Re-link them "
                   "in Sync mode → Saved Groups & Pairs.",
        )
        if st.button("Close", type="secondary", use_container_width=True,
                     key="today_import_done"):
            st.rerun(scope="app")
        return

    with st.container(height=460, border=False, key="today_import_scroll"):
        css_blocks = []
        for g_idx, group in selectable:
            is_sp = group.get("is_single_pair", False)
            pairs = group.get("pairs", []) or []
            gid = group.get("group_id", str(g_idx))
            sel_key = f"today_imp_sel_{gid}"
            btn_key = f"today_imp_btn_{gid}"

            if sel_key not in st.session_state:
                st.session_state[sel_key] = bool(pairs) and all(
                    (p.get("course_id"), p.get("local_folder")) in daily_sigs
                    for p in pairs
                )
            selected = st.session_state[sel_key]

            if is_sp:
                pair = pairs[0] if pairs else {}
                display_name = friendly_course_name(
                    pair.get("course_name", group["group_name"]))
                desc_text = f"Course: {display_name}"
                icon_b64 = b64_pairs
                tag_text = "Pair"
            else:
                n = len(pairs)
                desc_text = f"{n} course{'s' if n != 1 else ''}"
                icon_b64 = b64_groups
                tag_text = "Group"

            bg, border = (
                (_CARD_SEL_BG, _CARD_SEL_BORDER) if selected
                else (_CARD_IDLE_BG, _CARD_IDLE_BORDER)
            )
            hover_bg, hover_border = (
                (_CARD_SEL_HOVER_BG, _CARD_SEL_HOVER_BORDER) if selected
                else (_CARD_IDLE_HOVER_BG, _CARD_IDLE_HOVER_BORDER)
            )
            check_border = "none" if selected else _CHECK_IDLE_BORDER
            check_img_rule = (
                f"background-image: {_IMPORT_CHECK_SVG} !important;"
                if selected else ""
            )
            check_hover_border = "transparent" if selected else _CHECK_HOVER_BORDER

            css_blocks.append(f"""
            div.st-key-{btn_key} button {{
                background-image: url('data:image/png;base64,{icon_b64}') !important;
                background-color: {bg} !important;
                border: 1px solid {border} !important;
            }}
            div.st-key-{btn_key} button:hover {{
                background-color: {hover_bg} !important;
                border-color: {hover_border} !important;
            }}
            div.st-key-{btn_key} button::after {{
                content: "{_css_escape_content(desc_text)}" !important;
            }}
            div.st-key-{btn_key} button p::after {{
                content: "{_css_escape_content(tag_text)}" !important;
            }}
            div.st-key-{btn_key} button::before {{
                border: {check_border} !important;
                background-color: transparent !important;
                {check_img_rule}
            }}
            div.st-key-{btn_key} button:hover::before {{
                border-color: {check_hover_border} !important;
            }}
            """)

            with st.container(key=f"today_import_item_{g_idx}"):
                st.button(group["group_name"], key=btn_key, use_container_width=True,
                          on_click=_toggle_import_btn, args=(sel_key, pairs))

        st.markdown(f"<style>{''.join(css_blocks)}</style>", unsafe_allow_html=True)

    if st.button("Done", type="primary", use_container_width=True,
                 key="today_import_done"):
        st.session_state["today_toast"] = "Daily sync updated."
        st.rerun(scope="app")


def _open_import_dialog():
    """Clear stale selection state, then open the import dialog.

    Clearing ``today_imp_sel_*`` ensures every open recomputes membership fresh
    from the current daily-sync set (e.g. after a card was removed via the
    main page's "Remove" button while the dialog was closed).
    """
    for k in [k for k in st.session_state if k.startswith("today_imp_sel_")]:
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

    # ── Header (title + built-in help button) ───────────────────────────────
    with st.container(key="today_title_help_row"):
        _c_title, _c_help = st.columns([1, 10], vertical_alignment="center")
        with _c_title:
            st.markdown(
                f"<div class='today-title'>{_SVG_TITLE}<span>Today</span></div>",  # audit-ignore: static SVG constant
                unsafe_allow_html=True,
            )
        with _c_help:
            render_help_card(
                key_prefix="today_help",
                title=_TODAY_HELP_TITLE,
                text_html=_TODAY_HELP_TEXT,
                mode="button",
            )
    st.markdown(
        "<p class='today-subtitle'>Your daily course catch-up, in one place.</p>",
        unsafe_allow_html=True,
    )

    # Help card body (renders below the header when opened).
    render_help_card(
        key_prefix="today_help",
        title=_TODAY_HELP_TITLE,
        text_html=_TODAY_HELP_TEXT,
        mode="card",
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

    # Pairs whose folder is missing/moved are proactively hidden from the list so
    # they never get in the way. No notice here - the user can only add courses via
    # the import dialog, which already explains any hidden (issue) entries there.
    visible_pairs = [
        p for p in daily_pairs
        if p.get("local_folder") and Path(p["local_folder"]).exists()
    ]

    if not visible_pairs:
        st.markdown(
            f"<div class='today-empty'>"
            f"<div class='today-empty-icon'>{_SVG_EMPTY_COURSES}</div>"  # audit-ignore: static SVG constant
            f"<div>No courses in your daily sync yet.</div>"
            f"<div class='today-empty-sub'>Use <b>Add courses</b> to import saved "
            f"pairs or groups.</div></div>",
            unsafe_allow_html=True,
        )
    else:
        with st.container(border=True, key="today_list_outline"):
            for i, pair in enumerate(visible_pairs):
                folder = pair.get("local_folder", "")
                name = friendly_course_name(pair.get("course_name") or "Course")
                col_card, col_rm = st.columns([0.84, 0.16],
                                              vertical_alignment="center")
                with col_card:
                    with st.container(key=f"today_pair_card_{i}"):
                        # Title + folder rendered as ONE markdown block (single
                        # element-container) so the two lines stack via the inner
                        # flex `gap` and can never overlap, regardless of how
                        # Streamlit wraps separate elements. (CLAUDE.md: combine
                        # title + subtitle into one st.markdown call.)
                        st.markdown(
                            f"<div class='today-pair-inner'>"
                            f"<div class='today-pair-title'>Course:&nbsp;&nbsp;"
                            f"{esc(name)}</div>"
                            f"<div class='today-pair-folder'>{SVG_FOLDER_YELLOW}"  # audit-ignore: static SVG constant
                            f"{esc(folder)}</div>"  # audit-ignore: folder is a local path
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                with col_rm:
                    st.button(
                        "Remove", key=f"today_remove_{i}", use_container_width=True,
                        on_click=_remove_daily_pair_cb,
                        args=(pair.get("course_id"), folder, name),
                    )

    # ── Add courses + Quick Sync now ────────────────────────────────────────
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
