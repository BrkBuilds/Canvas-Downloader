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

The actual syncing reuses the existing Quick Sync engine via core.auto_sync. While
a daily/Quick Sync is running the app is on step 4, but it stays IN-PAGE: this
module re-renders the header + toggle and hosts the sync engine
(render_sync_step4) inside a slim "Running daily sync / Quick Sync" progress card
below the toggle (see ``_render_today_running_sync``), rather than the engine
taking over the whole screen. The engine, seeing ``today_sync_active``, renders a
slimmed view and routes back to this idle dashboard on completion / cancel.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from styles import inject_css
from shared.helpers import esc, friendly_course_name, get_base64_image, get_config_dir, short_path, open_folder, open_file
from shared.components import SVG_FOLDER_YELLOW, render_help_card, HELP_ICONS


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
# Solid book/reader glyph - a filled silhouette with its text lines *subtracted*
# (fill-rule evenodd punches the inner rects into holes), tinted light-grey via
# CSS. The icon for each course chip in the collapsed daily-sync summary.
_SVG_COURSE = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
    "fill='currentColor' class='tcs-pill-ico' "
    # Inline size is REQUIRED, not just cosmetic: when navigating Today -> Download,
    # Streamlit briefly leaves this chip markup in the DOM while today.css (which
    # sizes .tcs-pill-ico) is no longer injected, so an unsized SVG balloons to its
    # huge default replaced-element size on the download loading screen.
    "style='width:16px;height:16px;flex-shrink:0;'>"
    "<path fill-rule='evenodd' d='M6 3H18A2 2 0 0 1 20 5V19A2 2 0 0 1 18 21H6"
    "A2 2 0 0 1 4 19V5A2 2 0 0 1 6 3Z"
    "M7.5 8H16.5V9.4H7.5ZM7.5 11.3H16.5V12.7H7.5ZM7.5 14.6H13.5V16H7.5Z'/></svg>"
)
# Solid file glyph with a transparent corner fold gap - small, colored
# currentColor (inherits parent font color), used inside the completed sync
# course chips. Both the file body and the folded corner are separate path elements
# to guarantee they render as filled shapes.
_SVG_FILE_MINI = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='currentColor' "
    "style='width:0.95em;height:0.95em;vertical-align:-0.15em;margin-right:2px;"
    "display:inline-block;flex-shrink:0;'>"
    "<path d='M6 22h12a2 2 0 0 0 2-2V8l-6-6H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2z'/>"
    "<path d='M13 4l5 5h-5V4z'/>"
    "</svg>"
)
# Lucide refresh-cw glyph (white) - the icon badge on the manual Quick Sync card.
# A "refresh/update" mark (distinct from the button's ⚡ bolt) framing the card as
# the on-demand way to bring these courses up to date.
_SVG_QS_REFRESH = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
    "stroke='#ffffff' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round' "
    "style='width:21px;height:21px;'>"
    "<path d='M21 2v6h-6'/><path d='M3 12a9 9 0 0 1 15-6.7L21 8'/>"
    "<path d='M3 22v-6h6'/><path d='M21 12a9 9 0 0 1-15 6.7L3 16'/></svg>"
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
    "<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>Setting up your daily sync</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='display: flex; flex-direction: column; gap: 12px; margin-bottom: 8px;'>"

    "<div>"
    "<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 4px;'>1. Save your course pairs</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "In <b style='color: #ffffff;'>Sync Course Folders</b> (Sync mode), link each course to a folder on your computer and save it as a <b style='color: #ffffff;'>Pair</b>, or save several together as a <b style='color: #ffffff;'>Group</b> (e.g. <em>Semester 1</em>). These live in your Saved Groups &amp; Pairs hub."
    "</div></div>"

    "<div>"
    "<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 4px;'>2. Add them to your daily sync</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Click <b style='color: #ffffff;'>Add courses</b> below and tick the saved pairs and groups you want kept up to date. Your choice is saved and editable - come back any time to add or remove courses with <b style='color: #ffffff;'>Add courses</b> or the <b style='color: #ffffff;'>Remove</b> button on each card."
    "</div></div>"

    "<div>"
    "<div style='font-weight: 700; color: #ffffff; font-size: 1rem; margin-bottom: 4px;'>3. Let it run</div>"
    "<div style='color: #d9d9d9; font-size: 0.85rem; line-height: 1.6;'>"
    "Turn on <b style='color: #ffffff;'>Daily auto-sync</b> to have the app sync your chosen courses automatically the first time you open it each day (after 4 AM), or press <b style='color: #ffffff;'>Quick Sync now</b> to catch up on demand."
    "</div></div>"

    "</div>"
    "</div>"
    "</details>"
    "<hr>"

    # -- Auto-sync vs Quick Sync ---------------------------------------------
    "<details style='margin-top: 4px;'>"
    "<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>Daily auto-sync vs Quick Sync now</summary>"
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
    "<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>Today's files</summary>"
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
    "<summary style='cursor: pointer; font-weight: 700; color: #ffffff; font-size: 1.25rem; user-select: none; padding: 4px 0;'>Managing &amp; fixing your courses</summary>"
    "<div style='margin-top: 6px; padding-left: 12px;'>"
    "<div style='font-size: 0.85rem; color: rgba(255,255,255,0.88); line-height: 1.65;'>"
    "The courses on this page come from your Saved Groups &amp; Pairs. To rename a course, change its folder, or fix a folder that was moved or deleted, head to <b style='color: #ffffff;'>Sync mode → Saved Groups &amp; Pairs</b>. <br>"
    "If a course's folder can't be found, it's automatically hidden from the list here and skipped during sync so it never gets in your way - re-link it in the hub to bring it back."
    "</div>"
    "</div>"
    "</details>"
)


def _inject_dynamic_css(auto_sync_enabled: bool, sync_running: bool = False) -> None:
    """Button-icon + Quick-Sync brand styling (depends on base64 assets, so inline)."""
    b64_add = get_base64_image("assets/icon_add.png")
    b64_quick = get_base64_image("assets/icon_sync_quick.png")
    b64_folder = get_base64_image("assets/Icon_Folder.svg")
    
    import base64
    open_all_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="black" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h6"/>'
        '<path d="m21 3-9 9"/>'
        '<path d="M15 3h6v6"/>'
        '</svg>'
    )
    b64_open_all = base64.b64encode(open_all_svg.encode('utf-8')).decode('utf-8')
    
    dimming_css = ""
    if not auto_sync_enabled or sync_running:
        # Dim the page sections while auto-sync is off / a sync is running - but
        # NOT the running-sync card sandwiched between them (it's the active thing).
        dimming_css = """
    div.st-key-today_courses_card,
    div.st-key-today_files_hero,
    div.st-key-today_qs_section {
        opacity: 0.45 !important;
        filter: grayscale(100%) brightness(0.85) !important;
        pointer-events: none !important;
    }
        """

    # When auto-sync is ON, theme the whole toggle "pill" green (green tint + green
    # border + green switch track) so the card itself reads ACTIVE; when off it
    # falls back to the standard grey defined in today.css.
    toggle_active_css = ""
    if auto_sync_enabled:
        toggle_active_css = """
    div[class*="st-key-today_toggle_card"] {
        background: rgba(16, 185, 129, 0.12) !important;
        border-color: rgba(16, 185, 129, 0.5) !important;
        box-shadow: 0 0 18px rgba(16, 185, 129, 0.14) !important;
    }
    div[class*="st-key-today_toggle_card"] [data-testid="stCheckbox"] label > div:first-child {
        background-color: #10b981 !important;
    }
        """

    st.markdown(f"""<style>
    div.st-key-today_add_courses_btn button p::before {{
        content: "" !important;
        display: inline-block !important;
        position: relative !important;
        top: 1px !important;
        width: 12px !important; height: 12px !important;
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
    
    /* Today Action Buttons (Open Folder, Open All Files) resting state */
    div[class*="st-key-open_folder_today_"] button,
    div[class*="st-key-open_all_today_"] button {{
        border-radius: 10px !important;
        background-color: rgba(255, 255, 255, 0.07) !important;
        border: 1.5px solid rgba(255, 255, 255, 0.16) !important;
        color: rgba(255, 255, 255, 0.88) !important;
        transition: all 0.2s ease !important;
        padding: 0 12px !important;
        height: 32px !important;
        min-height: 32px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}

    /* Space the button row above the files list: -5px less spacing above, +20px spacing below, and symmetrical margins */
    div[class*="st-key-shist_body_today_"] [data-testid="stHorizontalBlock"] {{
        margin-top: -8px !important;
        margin-bottom: 15px !important;
        margin-left: 0px !important;
        width: calc(100% - 26px) !important;
        max-width: calc(100% - 26px) !important;
    }}

    /* Inner wrapper: force vertical centering */
    div[class*="st-key-open_folder_today_"] button > div,
    div[class*="st-key-open_all_today_"] button > div,
    div[class*="st-key-open_folder_today_"] button > div > span,
    div[class*="st-key-open_all_today_"] button > div > span,
    div[class*="st-key-open_folder_today_"] button div[data-testid="stMarkdownContainer"],
    div[class*="st-key-open_all_today_"] button div[data-testid="stMarkdownContainer"] {{
        display: flex !important;
        align-items: center !important;
        align-self: center !important;
        width: 100% !important;
    }}

    /* p is the icon+text row - inline-flex so ::before sits beside text */
    div[class*="st-key-open_folder_today_"] button p,
    div[class*="st-key-open_all_today_"] button p {{
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 9px !important;
        margin: 0 !important;
        line-height: 1 !important;
        width: 100% !important;
    }}

    /* Base icon: inline-block ::before */
    div[class*="st-key-open_folder_today_"] button p::before,
    div[class*="st-key-open_all_today_"] button p::before {{
        content: '' !important;
        display: inline-block !important;
        width: 20px !important;
        height: 20px !important;
        flex-shrink: 0 !important;
        -webkit-mask-repeat: no-repeat !important;
        -webkit-mask-position: center !important;
        transition: background-color 0.2s ease !important;
    }}

    /* Mask images and sizes */
    div[class*="st-key-open_folder_today_"] button p::before {{
        -webkit-mask-image: url('data:image/svg+xml;base64,{b64_folder}') !important;
        -webkit-mask-size: 18px !important;
        background-color: rgba(255, 255, 255, 0.88) !important;
    }}
    div[class*="st-key-open_all_today_"] button p::before {{
        -webkit-mask-image: url('data:image/svg+xml;base64,{b64_open_all}') !important;
        -webkit-mask-size: 18px !important;
        background-color: rgba(255, 255, 255, 0.88) !important;
    }}

    /* HOVER STATES */
    /* Open Folder -> Yellow (#facc15) */
    div[class*="st-key-open_folder_today_"] button:hover {{
        border-color: rgba(250, 204, 21, 0.7) !important;
        background-color: rgba(250, 204, 21, 0.08) !important;
        color: #ffffff !important;
    }}
    div[class*="st-key-open_folder_today_"] button:hover p::before {{
        background-color: #facc15 !important;
    }}

    /* Open All Files -> Blue (#93c5fd) */
    div[class*="st-key-open_all_today_"] button:hover {{
        border-color: rgba(59, 130, 246, 0.7) !important;
        background-color: rgba(59, 130, 246, 0.08) !important;
        color: #ffffff !important;
    }}
    div[class*="st-key-open_all_today_"] button:hover p::before {{
        background-color: #93c5fd !important;
    }}

    /* Disabled states */
    div[class*="st-key-open_folder_today_"] button:disabled,
    div[class*="st-key-open_all_today_"] button:disabled {{
        opacity: 0.45 !important;
        cursor: not-allowed !important;
        pointer-events: none !important;
    }}

    /* ── Today-page collapsible header: compact 52px, emphasized ── */
    /* Double attribute selector on the run container boosts specificity above the
       generic shist_run_ rules in sync_history_cards.css. Brighter header bar +
       slightly taller than the compact default so the per-course cards read as
       distinct, emphasized rows against the (darker) today_files_inner panel. */
    div[class*="st-key-shist_run_today_"][class*="st-key-shist_run_today_"] {{
        border-color: rgba(255, 255, 255, 0.14) !important;
    }}
    div[class*="st-key-shist_run_today_"][class*="st-key-shist_run_today_"] div[class*="st-key-shist_btn_today_"] button {{
        height: 52px !important;
        min-height: 52px !important;
        background: #2b313d !important;
    }}
    div[class*="st-key-shist_run_today_"][class*="st-key-shist_run_today_"] div[class*="st-key-shist_btn_today_"] button:hover {{
        background: #343b49 !important;
    }}
    div[class*="st-key-shist_run_today_"][class*="st-key-shist_run_today_"] [data-testid="stElementContainer"]:has(.shist-card) {{
        height: 52px !important;
    }}
    div[class*="st-key-shist_run_today_"][class*="st-key-shist_run_today_"] .shist-card {{
        height: 52px !important;
    }}

    /* ── Toggle card: zero the column gap Streamlit injects between toggle and badge ── */
    /* Needs to be inline because Streamlit emotion CSS (loaded after today.css) overrides it */
    div[class*="st-key-today_toggle_card"] [data-testid="stColumn"] {{
        padding: 0 !important;
    }}
    div[class*="st-key-today_toggle_card"] [data-testid="stColumn"]:first-child {{
        padding-right: 0 !important;
    }}


    {dimming_css}
    {toggle_active_css}
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
    from core.sync_manager import SyncHistoryManager
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
                    "course_id": grp.get("course_id"),
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


# Collapse chevron for the per-course cards (rotates 90deg when open). Matches
# the Sync History run cards exactly.
_TODAY_FILES_CHEVRON = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='15' height='15' viewBox='0 0 24 24' "
    "fill='none' stroke='#8b949e' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'>"
    "<polyline points='9 6 15 12 9 18'/></svg>"
)


def _group_widget_id(grp: dict) -> str:
    """Stable, key-safe identity for a today-files course group.

    Cards were previously keyed by their position in the list, so if the set of
    courses with files changed between reruns (e.g. a second sync completed
    mid-session and inserted a course), every card's expand/collapse state -
    and its per-file action-button keys - silently shifted to a NEIGHBOURING
    course. Deriving the key from (course_id, local_folder) pins state to the
    course it belongs to no matter how the list reorders. Hex-digest suffix
    keeps arbitrary folder paths out of Streamlit keys / CSS classes.
    """
    import hashlib
    cid = grp.get("course_id")
    folder = grp.get("local_folder", "") or ""
    folder_h = hashlib.md5(folder.encode("utf-8", "replace")).hexdigest()[:8]
    return f"{cid if cid is not None else 'x'}_{folder_h}"


@st.fragment
def _render_today_files(groups: list[dict]) -> None:
    """Render today's synced files as one collapsible card PER COURSE.

    Reuses the Sync History "fake-expander" card shell verbatim: the shared
    ``sync_history_cards.css`` styles any container keyed ``shist_run_*`` /
    ``shist_body_*``, and the body is the same interactive per-file breakdown
    (filetype icon + name + Open/Reveal + destination chip) used on the sync
    completion and sync-history screens. This is the sync-history layout,
    grouped by course and trimmed for the Today page (no run timestamps, a file
    count badge instead of a run status, and the destination folder on line 2).

    Wrapped in ``@st.fragment`` so expanding/collapsing a course card (and the
    per-file Open/Reveal buttons) reruns ONLY this file list via
    ``st.rerun(scope="fragment")`` - not the whole page. A full-page rerun
    re-injected the heavy ``today.css``, which caused a visible flash ("dip to
    black") and lag on every expander toggle.
    """
    # NOTE: the shared card + file-row CSS is injected by the CALLER, OUTSIDE this
    # fragment (see render_today_dashboard), so a fragment-scoped rerun never
    # re-injects it and the <style> elements never sit inside this fragment's own
    # vertical block (where they'd claim a flex-gap slot above the first card).
    from shared.helpers import short_path
    from shared.components import render_course_file_breakdown

    for grp in groups:
        files = grp.get("files") or []
        if not files:
            continue
        course_name = friendly_course_name(grp.get("course_name", "") or "Course")
        local_folder = grp.get("local_folder", "") or ""
        count = len(files)
        count_label = f"{count} file" if count == 1 else f"{count} files"
        dest = short_path(local_folder) if local_folder else "Course folder"

        gid = _group_widget_id(grp)
        open_key = f"today_files_open_{gid}"
        is_open = st.session_state.get(open_key, True)

        header_html = (
            "<div class='shist-card'>"
            f"<div class='shist-chev' style='transform:rotate({90 if is_open else 0}deg);'>"
            f"{_TODAY_FILES_CHEVRON}</div>"  # audit-ignore: static SVG constant
            "<div class='shist-info'>"
            "<div class='shist-l1'>"
            f"<span class='shist-title'>{esc(course_name)}</span>"
            "<span class='shist-badge' style='color:#34d399;background:rgba(52,211,153,0.1);"
            f"border-color:rgba(52,211,153,0.2);'>{esc(count_label)}</span>"
            "</div>"
            "</div>"
            "</div>"
        )

        with st.container(border=True, key=f"shist_run_today_{gid}"):
            if st.button("​", key=f"shist_btn_today_{gid}", use_container_width=True):
                st.session_state[open_key] = not is_open
                st.rerun(scope="fragment")
            st.markdown(header_html, unsafe_allow_html=True)
            if is_open:
                with st.container(border=True, key=f"shist_body_today_{gid}"):
                    folder_exists = local_folder and Path(local_folder).exists()
                    col_btn_open, col_btn_all = st.columns(2)
                    with col_btn_open:
                        if st.button("Open Folder", key=f"open_folder_today_{gid}", use_container_width=True, disabled=not folder_exists):
                            open_folder(local_folder)
                    with col_btn_all:
                        if st.button("Open All Files", key=f"open_all_today_{gid}", use_container_width=True, disabled=not folder_exists or not files):
                            for f_info in files:
                                f_path = Path(local_folder) / (f_info.get("rel") or f_info.get("name") or "")
                                open_file(str(f_path))
                    render_course_file_breakdown(
                        files, local_folder, key_scope=f"today_{gid}",
                    )


# ── Import-from-hub dialog ──────────────────────────────────────────────────

def _css_escape_content(text: str) -> str:
    """Escape a string for safe use inside a CSS quoted string (content: "...")."""
    return text.replace('\\', '\\\\').replace('"', '\\"')


def _css_content_safe(text: str) -> str:
    """Escape *user* text for a CSS ``content:"…"`` value inside a ``<style>``.

    Extends ``_css_escape_content`` by unicode-escaping ``<`` so a stray
    ``</style>`` in a user-typed group name can't break out of the injected
    style element (the HTML parser scans the raw text for the literal
    ``</style``; ``\\3C`` renders as ``<`` for display but isn't a literal ``<``).
    """
    return _css_escape_content(text).replace('<', '\\00003c ')


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
# "Absorbed" pair: a standalone pair whose course is already covered by a
# selected group. Shown locked (dashed border, dimmed, non-interactive) with an
# "Included in <group>" tag, so the group⊃pair relationship is explicit and the
# same course can never be double-counted while its group is on.
_CARD_ABSORBED_BG = "rgba(255, 255, 255, 0.035)"
_CARD_ABSORBED_BORDER = "rgba(255, 255, 255, 0.12)"


def _toggle_import_btn(sel_key: str):
    """Flip a saved pair/group's *local* selection in the import dialog.

    Selection is local-only now: the daily-sync set is (re)computed as the union
    of every selected entity's courses when the user confirms (see
    ``_commit_import_selection``). The old per-click add/remove could silently
    drop a course that another still-selected entity also owned (e.g. unticking a
    group nuked a standalone pair that shared one of its courses).
    """
    st.session_state[sel_key] = not st.session_state.get(sel_key, False)


def _import_card_css(btn_key: str, icon_b64: str, tag_text: str,
                     selected: bool) -> str:
    """Per-card CSS for a normal (tickable) import card - idle/selected + hover."""
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
        f"background-image: {_IMPORT_CHECK_SVG} !important;" if selected else ""
    )
    check_hover_border = "transparent" if selected else _CHECK_HOVER_BORDER
    return f"""
    div.st-key-{btn_key} button {{
        background-image: url('data:image/png;base64,{icon_b64}') !important;
        background-color: {bg} !important;
        border: 1px solid {border} !important;
    }}
    div.st-key-{btn_key} button:hover {{
        background-color: {hover_bg} !important;
        border-color: {hover_border} !important;
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
    """


def _import_card_css_absorbed(btn_key: str, icon_b64: str, tag_text: str) -> str:
    """Per-card CSS for an *absorbed* pair - locked, dimmed, muted check.

    The whole-card ``opacity`` dims the title/icon/pills/check together. The
    "Included in <group>" tag is set on a stDialog-scoped selector so it BEATS
    today.css's higher-specificity grey ``p::after`` colour and stays legible
    (a soft cyan) instead of fading into the dim card.
    """
    _tag = _css_content_safe(tag_text)
    return f"""
    div.st-key-{btn_key} button {{
        background-image: url('data:image/png;base64,{icon_b64}') !important;
        background-color: {_CARD_ABSORBED_BG} !important;
        border: 1px dashed {_CARD_ABSORBED_BORDER} !important;
        opacity: 0.7 !important;
        cursor: default !important;
        pointer-events: none !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-{btn_key}"] button p::after {{
        content: "{_tag}" !important;
        color: rgba(125, 211, 252, 0.92) !important;
        font-weight: 600 !important;
    }}
    div.st-key-{btn_key} button::before {{
        border: none !important;
        background-color: transparent !important;
        background-image: {_IMPORT_CHECK_SVG} !important;
    }}
    """


def _commit_import_selection(selectable: list) -> None:
    """Persist the daily-sync set as the union of the selected entities' courses.

    Preserves any daily course NOT represented by a currently selectable entity
    (its saved group was deleted, or its folder is missing so the entity is
    hidden here) so managing courses in this dialog never silently drops those.
    """
    from core.today_store import load_today_config, set_today_pairs

    dialog_sigs: set = set()
    resolved: dict = {}
    for g_idx, group in selectable:
        gid = group.get("group_id", str(g_idx))
        selected = st.session_state.get(f"today_imp_sel_{gid}", False)
        for p in group.get("pairs", []) or []:
            sig = (p.get("course_id"), p.get("local_folder"))
            dialog_sigs.add(sig)
            if selected:
                resolved.setdefault(sig, {
                    "course_id": p.get("course_id"),
                    "course_name": p.get("course_name", ""),
                    "local_folder": p.get("local_folder"),
                })
    existing = load_today_config()["pairs"]
    keep = [
        p for p in existing
        if (p.get("course_id"), p.get("local_folder")) not in dialog_sigs
    ]
    set_today_pairs(keep + list(resolved.values()))


@st.dialog("​", width="large")
def _import_courses_dialog():
    """Pick saved groups & pairs from the hub to keep in the daily sync set.

    Each card is a native st.button styled as a whole-card toggle (mirrors the
    "Canvas Content" card pattern in ui/download_settings.py): clicking
    anywhere on the card toggles its membership in the daily sync, with a
    checkbox indicator that fills in with a checkmark when selected.
    """
    from core.sync_manager import SavedGroupsManager
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
            <div style="font-size:1.75rem; font-weight:600; color:white;">Manage daily sync courses</div>
        </div>
        <p style="color:#aaa; font-size:0.9rem; margin:6px 0 12px 0;">
            These are the pairs and groups you've saved in <b>Sync Course Folders.</b> Tick the
            ones you want auto-sync daily. Don't see a course? Save it there
            first, as a Pair or Group, then come back to add it here.
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

    _daily_pairs = load_today_config()["pairs"]
    daily_sigs = {(p["course_id"], p["local_folder"]) for p in _daily_pairs}
    # First-time setup (empty daily list) vs managing an existing one - drives
    # the confirm-button label ("Add N courses" vs "Save changes").
    is_first_time = not _daily_pairs

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

    # ── Seed local selection (group-preferred, minimal) ─────────────────────
    # Selection is LOCAL until the user confirms; the daily set is then the UNION
    # of every selected entity's courses (see _commit_import_selection). Seed a
    # GROUP if all its courses are already in the daily set; seed a standalone
    # PAIR only if its course is in the set AND not already covered by a seeded
    # group. Minimal (non-redundant) seeding means unticking a group cleanly
    # clears its courses instead of leaving orphaned pair ticks behind.
    def _sig(p) -> tuple:
        return (p.get("course_id"), p.get("local_folder"))

    for g_idx, group in selectable:            # groups first
        if group.get("is_single_pair", False):
            continue
        sel_key = f"today_imp_sel_{group.get('group_id', str(g_idx))}"
        if sel_key not in st.session_state:
            gpairs = group.get("pairs", []) or []
            st.session_state[sel_key] = bool(gpairs) and all(
                _sig(p) in daily_sigs for p in gpairs
            )
    _seeded_grp_cover = {
        _sig(p)
        for g_idx, group in selectable
        if not group.get("is_single_pair", False)
        and st.session_state.get(f"today_imp_sel_{group.get('group_id', str(g_idx))}")
        for p in (group.get("pairs", []) or [])
    }
    for g_idx, group in selectable:            # then standalone pairs
        if not group.get("is_single_pair", False):
            continue
        sel_key = f"today_imp_sel_{group.get('group_id', str(g_idx))}"
        if sel_key not in st.session_state:
            gp = (group.get("pairs", []) or [{}])[0]
            s = _sig(gp)
            st.session_state[sel_key] = s in daily_sigs and s not in _seeded_grp_cover

    # Resolve coverage from the CURRENT selection, split by entity type so it
    # works both ways:
    #   grp_cover : sig → selected GROUP name  → locks a matching standalone pair
    #               ("Included in <group>").
    #   pair_cover: sig → selected PAIR name   → covers a matching group
    #               ("Covered by <pairs>") - the symmetric case.
    grp_cover: dict = {}
    pair_cover: dict = {}
    resolved_sigs: set = set()
    for g_idx, group in selectable:
        gid = group.get("group_id", str(g_idx))
        if not st.session_state.get(f"today_imp_sel_{gid}"):
            continue
        is_sp = group.get("is_single_pair", False)
        for p in group.get("pairs", []) or []:
            s = _sig(p)
            resolved_sigs.add(s)
            if is_sp:
                pair_cover.setdefault(s, group.get("group_name", "a pair"))
            else:
                grp_cover.setdefault(s, group.get("group_name", "a group"))
    sel_count = len(resolved_sigs)

    # ── Pre-compute every card's CSS + pill data BEFORE any button renders ──
    # Building all per-card <style> first and injecting it at dialog top level
    # (below, ahead of the scroll container) means each card paints already-styled
    # on the dialog's first frame - instead of first flashing as a plain Streamlit
    # button and then "popping" into a card once the style block arrived at the end
    # of the loop (the visible step-by-step restyle the user saw on open).
    css_blocks = []
    cards_data = []
    render_list = []  # (g_idx, group_name, btn_key, sel_key, locked)
    for g_idx, group in selectable:
        is_sp = group.get("is_single_pair", False)
        pairs = group.get("pairs", []) or []
        gid = group.get("group_id", str(g_idx))
        sel_key = f"today_imp_sel_{gid}"
        btn_key = f"today_imp_btn_{gid}"
        selected = st.session_state[sel_key]

        sigs = [_sig(p) for p in pairs]
        # "Checked" is COVERAGE, not the raw flag: an entity reads as ticked
        # whenever all its courses are in the resolved set (from ANY selected
        # entity). This is what makes two ticked pairs auto-tick their group.
        covered = bool(sigs) and all(s in resolved_sigs for s in sigs)

        locked, tag_text = False, "Pair" if is_sp else "Group"
        if is_sp:
            icon_b64 = b64_pairs
            pill_names = [friendly_course_name(
                (pairs[0] if pairs else {}).get("course_name", group["group_name"]))]
            # Absorbed: a selected GROUP already covers this pair's course.
            if sigs and sigs[0] in grp_cover:
                locked = True
                tag_text = f'Included in "{grp_cover[sigs[0]]}"'
        else:
            icon_b64 = b64_groups
            pill_names = [
                friendly_course_name(p.get("course_name", ""))
                for p in pairs if p.get("course_name")
            ]
            # Covered: all this group's courses come from selected pairs while
            # the group itself isn't the (user-)selected owner.
            if not selected and covered:
                locked = True
                names = []
                for s in sigs:
                    nm = pair_cover.get(s)
                    if nm and nm not in names:
                        names.append(nm)
                if not names:
                    tag_text = "Already covered"
                elif len(names) <= 2:
                    tag_text = "Covered by " + ", ".join(f'"{n}"' for n in names)
                else:
                    tag_text = f"Covered by {len(names)} pairs"

        cards_data.append({
            "key": btn_key, "pills": pill_names,
            "selected": covered, "absorbed": locked,
        })

        if locked:
            css_blocks.append(
                _import_card_css_absorbed(btn_key, icon_b64, tag_text)
            )
        else:
            css_blocks.append(
                _import_card_css(btn_key, icon_b64, tag_text, covered)
            )
        render_list.append((g_idx, group["group_name"], btn_key, sel_key, locked))

    # Hoisted to dialog top level so global.css collapses its ghost box (no gap
    # slot) and the rules land in the DOM before the buttons mount.
    st.markdown(f"<style>{''.join(css_blocks)}</style>", unsafe_allow_html=True)

    with st.container(height=460, border=False, key="today_import_scroll"):
        for g_idx, group_name, btn_key, sel_key, locked in render_list:
            with st.container(key=f"today_import_item_{g_idx}"):
                st.button(group_name, key=btn_key, use_container_width=True,
                          disabled=locked,
                          on_click=_toggle_import_btn, args=(sel_key,))
        _inject_import_pills_bridge(cards_data)

    # Live-count confirm: "Add N courses" first-time, "Save changes" when managing.
    if is_first_time:
        _plural = "" if sel_count == 1 else "s"
        confirm_label = f"Add {sel_count} course{_plural}" if sel_count else "Add courses"
    else:
        confirm_label = "Save changes"
    if st.button(confirm_label, type="primary", use_container_width=True,
                 key="today_import_done"):
        _commit_import_selection(selectable)
        st.session_state["today_toast"] = "Daily sync updated."
        st.rerun(scope="app")


def _inject_import_pills_bridge(cards_data: list[dict]) -> None:
    """Inject pill <span> DOM elements for course names into each import card button.

    CSS ::after can only render plain text, so actual pill styling (background,
    border, border-radius) requires real DOM elements. This bridge reaches into
    window.parent.document (same-origin) and appends a flex row of pill spans
    inside each card's <button>. Re-binding on every rerun is intentional - see
    CLAUDE.md JS bridge rules.
    """
    import json
    import streamlit.components.v1 as components

    cards_json = json.dumps(cards_data)
    components.html(f"""<script>
(function() {{
    var doc = window.parent.document;
    var cards = {cards_json};
    var CLS = 'today-imp-pill-row';
    var PILL_BASE = [
        'display:inline-block',
        'border-radius:4px',
        'padding:0px 5px',
        'font-size:0.75rem',
        'font-weight:400',
        'color:rgba(255,255,255,0.78)',
        'white-space:nowrap',
        'pointer-events:none',
        'font-family:inherit',
    ].join(';');
    var PILL_IDLE = PILL_BASE + ';background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.18)';
    var PILL_SEL  = PILL_BASE + ';background:rgba(0,0,0,0.30);border:1px solid rgba(255,255,255,0.30)';
    var ROW = [
        'display:flex',
        'flex-wrap:wrap',
        'gap:4px',
        'margin-top:4px',
        'pointer-events:none',
        'width:100%',
    ].join(';');

    function inject() {{
        cards.forEach(function(card) {{
            var btn = doc.querySelector('div.st-key-' + card.key + ' button');
            if (!btn) return;
            var old = btn.querySelector('.' + CLS);
            if (old) old.remove();
            if (!card.pills || !card.pills.length) return;
            var row = doc.createElement('div');
            row.className = CLS;
            row.setAttribute('style', ROW);
            var label = doc.createElement('span');
            label.setAttribute('style', 'font-size:0.75rem;font-weight:400;color:rgba(255,255,255,0.78);white-space:nowrap;pointer-events:none;font-family:inherit;align-self:center');
            label.textContent = card.pills.length === 1 ? 'Course:' : 'Courses:';
            row.appendChild(label);
            var pillStyle = card.selected ? PILL_SEL : PILL_IDLE;
            card.pills.forEach(function(name) {{
                var pill = doc.createElement('span');
                pill.setAttribute('style', pillStyle);
                pill.textContent = name;
                row.appendChild(pill);
            }});
            btn.appendChild(row);
        }});
    }}

    inject();
    setTimeout(inject, 80);
    setTimeout(inject, 280);
}})();
</script>""", height=0)


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


def _dismiss_sync_notice() -> None:
    """on_click for the notice's close button - idempotent pop, no dangling flag."""
    st.session_state.pop("today_sync_notice", None)


# ── Last-run success notice (dismissible) ───────────────────────────────────

# Lucide check-circle glyph - green, sized inline (see _SVG_COURSE for why the
# inline size is required, not cosmetic).
_SVG_NOTICE_CHECK = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
    "stroke='#34d399' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round' "
    "style='width:19px;height:19px;flex-shrink:0;'>"
    "<path d='M22 11.08V12a10 10 0 1 1-5.93-9.14'/><polyline points='22 4 12 14.01 9 11.01'/></svg>"
)

_NOTICE_MAX_COURSE_CHIPS = 4


def _render_sync_notice(notice: dict) -> None:
    """Render the dismissible "sync finished" card below the auto-sync toggle.

    Shown on the idle dashboard after a daily auto-sync or a manual "Quick Sync
    now" completes (written by the today completion handler in sync_ui.py;
    survives page navigation until dismissed or replaced by the next run).
    The whole card is one st.markdown block (CLAUDE.md: single call, no
    inter-element gap) beside a compact masked-icon close button.
    """
    from shared.helpers import format_time_display

    if not isinstance(notice, dict):
        st.session_state.pop("today_sync_notice", None)
        return

    total = notice.get("total_files")
    total = total if isinstance(total, int) and total > 0 else 0
    errors = notice.get("errors")
    errors = errors if isinstance(errors, int) and errors > 0 else 0
    courses = [c for c in (notice.get("courses") or []) if isinstance(c, dict)]

    title = "Daily sync complete" if notice.get("is_auto") else "Quick Sync complete"
    when = str(notice.get("completed_at") or "")
    when_html = (
        f"<span class='today-notice-when'>at {esc(format_time_display(when))}</span>"
        if when else ""
    )

    if total > 0:
        headline = f"{total} new file{'s' if total != 1 else ''} downloaded."
    else:
        headline = "No new files &ndash; you were already up to date."

    chips_html = ""
    if total > 0 and courses:
        chips = []
        for c in courses[:_NOTICE_MAX_COURSE_CHIPS]:
            _cnt = c.get("count")
            _cnt = _cnt if isinstance(_cnt, int) and _cnt > 0 else 0
            chips.append(
                f"<span class='today-notice-chip'>{esc(str(c.get('name') or 'Course'))}"
                f"<b>{_SVG_FILE_MINI}{_cnt}</b></span>"  # audit-ignore: int count in static wrapper
            )
        overflow = len(courses) - _NOTICE_MAX_COURSE_CHIPS
        if overflow > 0:
            chips.append(f"<span class='today-notice-chip'>+{overflow} more</span>")
        chips_html = f"<div class='today-notice-chips'>{''.join(chips)}</div>"

    errors_html = ""
    if errors:
        errors_html = (
            f"<div class='today-notice-errors'>{errors} file"
            f"{'s' if errors != 1 else ''} couldn't be downloaded &ndash; "
            f"details in Sync mode &rarr; Sync History.</div>"
        )

    with st.container(key="today_sync_notice_card"):
        c_body, c_close = st.columns([0.95, 0.05], vertical_alignment="center")
        with c_body:
            st.markdown(
                f"<div class='today-notice-inner'>"
                f"<div class='today-notice-head'>{_SVG_NOTICE_CHECK}"  # audit-ignore: static SVG constant
                f"<span class='today-notice-title'>{esc(title)}</span>{when_html}</div>"
                f"<div class='today-notice-desc'>{headline}</div>"
                f"{chips_html}{errors_html}"
                f"</div>",
                unsafe_allow_html=True,
            )
        with c_close:
            # No help= tooltip: it wraps the <button> in a stTooltipHoverTarget,
            # which breaks the fixed 32px sizing CSS (see CLAUDE.md).
            st.button(
                "​", key="today_notice_close_btn",
                on_click=_dismiss_sync_notice,
            )


def _render_course_chips(pairs: list[dict]) -> None:
    """Render the daily-sync courses as clickable chips that open each folder.

    This is the everyday (collapsed) view: the daily-sync set is a
    whole-semester setup that rarely changes, so the main page shows just these
    glanceable chips instead of the full editable list. Each chip is a native
    ``st.button`` styled as a pill (folder glyph + course name); clicking it
    opens that course's local folder in the file explorer. All editing lives
    behind the "Manage" toggle. The keyed wrapper is laid out as a flex-wrap row
    in today.css so the buttons flow like tags.
    """
    with st.container(key="today_courses_summary"):
        for i, p in enumerate(pairs):
            name = friendly_course_name(p.get("course_name") or "Course")
            folder = p.get("local_folder", "") or ""
            if st.button(name, key=f"today_chip_{i}", disabled=not folder):
                open_folder(folder)


# ── Running sync (in-page progress card) ────────────────────────────────────

# Lucide refresh-cw glyph - the animated spinner in the running-sync card head.
_SVG_RUN_SPINNER = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
    "stroke='#3fd9ff' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round' "
    # Inline size (matches today.css .today-run-spin) so it can't balloon if
    # today.css unmounts during a page transition - see _SVG_COURSE above.
    "class='today-run-spin' style='width:20px;height:20px;flex-shrink:0;'>"
    "<path d='M21 12a9 9 0 1 1-6.219-8.56'/></svg>"
)

# Phase → (heading verb, one-line description) shown in the running-sync card.
# Keyed by download_status so the card narrates what the engine is doing.
_RUN_PHASE_DESC = {
    "analyzing": "Checking your courses for new files…",
    "analyzed":  "Reviewing changes…",
    "pre_sync":  "Getting your download ready…",
    "syncing":   "Downloading new files…",
    "sync_panopto": "Fetching lecture recordings…",
}


def _render_today_running_sync() -> None:
    """Render the in-page sync progress content and drive the sync engine.

    The caller owns the ``today_running_card`` container (kept in the tree even
    when idle for DOM-node stability - see render_today_dashboard); this fills it
    with the title + phase description and then calls the engine
    (render_sync_step4) so every progress bar / cancel button it emits lands
    inside that card rather than taking over the page. The engine, seeing
    ``today_sync_active``, renders a slimmed view (no wizard, no metrics/log, no
    full-screen "Analyzing…" blocks) and routes back to the idle dashboard when
    the run completes or is cancelled.
    """
    from sync_ui import render_sync_step4

    is_auto = st.session_state.get("today_sync_is_auto", False)
    status = st.session_state.get("download_status", "")
    title = "Running daily sync" if is_auto else "Running Quick Sync"
    desc = _RUN_PHASE_DESC.get(status, "Working…")

    st.markdown(
        f"<div class='today-run-head'>{_SVG_RUN_SPINNER}"  # audit-ignore: static SVG constant
        f"<span class='today-run-title'>{esc(title)}</span></div>"
        f"<div class='today-run-desc'>{esc(desc)}</div>",
        unsafe_allow_html=True,
    )
    # Drive the shared sync engine; its slim (today) UI renders below.
    render_sync_step4()


# ── Page ────────────────────────────────────────────────────────────────────

def render_today_dashboard(fetch_courses_fn=None):
    """Render the Today dashboard page.

    Two states:
      * idle (step 1)      - the full dashboard (toggle, courses, Quick Sync,
                             today's files).
      * running (step 4)   - a daily/Quick Sync is in flight; the page renders
                             the header + toggle, then an in-page progress card
                             that hosts the sync engine (see
                             ``_render_today_running_sync``). The rest of the
                             dashboard is hidden until the run finishes.
    """
    from core.today_store import load_today_config, set_auto_sync_enabled
    from core.auto_sync import resolve_today_pairs, start_today_sync

    # A daily/Quick Sync launched from this page routes back here at step==4 with
    # today_sync_active set, so the run can surface IN-PAGE. Any other entry means
    # a prior run (incl. a cancelled one) is over - clear the slim-UI marker.
    sync_running = bool(
        st.session_state.get("today_sync_active")
        and st.session_state.get("step") == 4
    )
    if not sync_running:
        st.session_state.pop("today_sync_active", None)

    cfg = load_today_config()
    inject_css("today.css")  # Force reload CSS changes v2
    _inject_dynamic_css(cfg["auto_sync_enabled"], sync_running)

    if "today_toast" in st.session_state:
        st.toast(st.session_state.pop("today_toast"))

    daily_pairs = cfg["pairs"]

    def _on_toggle():
        set_auto_sync_enabled(st.session_state.get("today_auto_toggle", False))

    # ── Main Layout Centering ────────────────────────────────────────────
    _, main_col, _ = st.columns([0.4, 3.6, 0.4])

    with main_col:
        # ── Header (title + auto-sync toggle card on the same row) ───────────────────────────────
        with st.container(key="today_header_row"):
            col_left, col_right = st.columns([0.46, 0.54], vertical_alignment="center")
            with col_left:
                st.markdown(
                    f"<div class='today-title'><span>Auto-download today's new files</span></div>",
                    unsafe_allow_html=True,
                )
            with col_right:
                with st.container(key="today_toggle_card"):
                    c_toggle, c_status = st.columns([0.08, 0.92], vertical_alignment="center")
                    with c_toggle:
                        st.toggle(
                            "Daily auto-sync",
                            value=cfg["auto_sync_enabled"],
                            key="today_auto_toggle",
                            on_change=_on_toggle,
                            disabled=sync_running,
                            label_visibility="collapsed",
                        )
                    with c_status:
                        if cfg["auto_sync_enabled"]:
                            st.html(
                                "<div class='today-status-badge active'>"
                                "<span>Active</span>"
                                "</div>"
                            )
                        else:
                            st.html(
                                "<div class='today-status-badge inactive'>"
                                "<span>Not Activated</span>"
                                "</div>"
                            )

        # Subtitle (title description) + help button
        with st.container(key="today_subtitle_help_row"):
            col_sub, col_help = st.columns([0.94, 0.06], vertical_alignment="center")
            with col_sub:
                st.markdown(
                    "<p class='today-subtitle'>Add your courses to the daily sync, and their new "
                    "files are downloaded automatically each morning, first time you open the app - no need to check "
                    "Canvas yourself.</p>",
                    unsafe_allow_html=True,
                )
            with col_help:
                render_help_card(
                    key_prefix="today_help",
                    title=_TODAY_HELP_TITLE,
                    text_html=_TODAY_HELP_TEXT,
                    mode="button",
                )

        # Help card body (renders below the header when opened).
        render_help_card(
            key_prefix="today_help",
            title=_TODAY_HELP_TITLE,
            text_html=_TODAY_HELP_TEXT,
            mode="card",
        )

        # ── Courses in your daily sync (card) ───────────────────────────────────
        # Day-to-day this list never changes (it's a whole-semester setup), so the
        # main view shows only a compact chip summary of the courses - each chip
        # clickable to open that course's folder. The full management UI (the
        # editable list with Remove + the Add courses dialog) lives "a layer
        # deeper", revealed inline by the "Manage" toggle. Add courses stays a
        # dialog opened from the revealed layer, so it's never nested inside another
        # dialog (which would crash Streamlit). The whole section is boxed in its
        # own card so it reads as distinct from the "Today's files" highlight below.
        #
        # Pairs whose folder is missing/moved are proactively hidden from the list so
        # they never get in the way. No notice here - the user can only add courses via
        # the import dialog, which already explains any hidden (issue) entries there.
        visible_pairs = [
            p for p in daily_pairs
            if p.get("local_folder") and Path(p["local_folder"]).exists()
        ]
        has_courses = bool(visible_pairs)
        manage_open = st.session_state.get("today_manage_open", False)

        with st.container(key="today_courses_card"):
            # Header row: section label (+ live count) ........ Manage / Done toggle.
            with st.container(key="today_courses_head"):
                c_lbl, c_btn = st.columns([0.7, 0.3], vertical_alignment="center")
                with c_lbl:
                    count_badge = (
                        f"<span class='tcs-count'>{len(visible_pairs)}</span>"
                        if has_courses else ""
                    )
                    st.markdown(
                        f"<div class='today-section-label'>Courses in your daily sync"
                        f"{count_badge}</div>",  # audit-ignore: static HTML wrapping an int count
                        unsafe_allow_html=True,
                    )
                with c_btn:
                    # The toggle only makes sense when there's a summary to collapse into.
                    if has_courses and not manage_open:
                        if st.button("Manage", key="today_manage_btn",
                                     use_container_width=True, disabled=sync_running):
                            st.session_state["today_manage_open"] = True
                            st.rerun()
                    elif has_courses and manage_open:
                        if st.button("Done", key="today_manage_done_btn",
                                     use_container_width=True, disabled=sync_running):
                            st.session_state["today_manage_open"] = False
                            st.rerun()

            if not has_courses:
                # No courses yet - offer a direct CTA so first-time setup is one click away.
                st.markdown(
                    f"<div class='today-empty-inner today-courses-empty'>"
                    f"<div class='today-empty-icon'>{_SVG_EMPTY_COURSES}</div>"  # audit-ignore: static SVG constant
                    f"<div class='today-courses-empty-title'>No courses in your daily sync yet.</div>"
                    f"<div class='today-empty-sub'>Use <b>Add courses</b> to import saved "
                    f"pairs or groups.</div></div>",
                    unsafe_allow_html=True,
                )
                if st.button("Add courses", use_container_width=True,
                             key="today_add_courses_btn", disabled=sync_running):
                    _open_import_dialog()
            elif not manage_open:
                # COLLAPSED (the day-to-day view) - clickable course chips (open folder).
                _render_course_chips(visible_pairs)
            else:
                # EXPANDED (the management layer) - editable list + Add courses dialog.
                with st.container(key="today_list_outline"):
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
                                    f"{esc(short_path(folder))}</div>"  # audit-ignore: folder is a local path
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                        with col_rm:
                            st.button(
                                "Remove", key=f"today_remove_{i}", use_container_width=True,
                                on_click=_remove_daily_pair_cb,
                                args=(pair.get("course_id"), folder, name),
                                disabled=sync_running,
                            )
                    if st.button("Add or manage courses", use_container_width=True,
                                 key="today_add_courses_btn", disabled=sync_running):
                        _open_import_dialog()

        # ── Running sync (in-page) — STABLE SLOT ────────────────────────────────
        # A daily/Quick Sync is in flight: surface it as a slim progress card right
        # here, directly BELOW the "Courses in your daily sync" card, instead of the
        # sync engine taking over the whole screen. The sections above and below stay
        # put, dimmed (see the dimming in _inject_dynamic_css); this card itself is
        # never dimmed - it's the active thing.
        #
        # CRITICAL: this keyed container is emitted UNCONDITIONALLY (even when idle)
        # so React always keeps it as its OWN DOM node. If it were only rendered
        # while syncing, then on the idle→syncing frame React would repurpose a
        # neighbouring section's node for this card (all are adjacent
        # stVerticalBlocks), orphaning that section's children INSIDE this card's
        # bordered box - the "content swallowed by the syncing card" bug. When idle
        # the slot holds only a hidden anchor (keeps the node alive) and CSS
        # collapses it to nothing (div[...today_running_card]:not(:has(.today-run-head))).
        with st.container(key="today_running_card"):
            st.markdown(
                "<div class='today-run-anchor'></div>",  # audit-ignore: static node-anchor
                unsafe_allow_html=True,
            )
            if sync_running:
                _render_today_running_sync()

        # ── Last-run success notice — floats in the gap ABOVE the hero ──────────
        # Written by the today completion handler (sync_ui.render_sync_step4) when a
        # daily/Quick Sync finishes. Rendered as a standalone sibling in the space
        # BETWEEN the "Courses in your daily sync" card and the "Today's files" hero
        # (not inside the hero). Dismissible; survives navigation until closed or
        # replaced by the next run.
        _sync_notice = st.session_state.get("today_sync_notice")
        if _sync_notice:
            _render_sync_notice(_sync_notice)

        # ── Today's files — the HERO card (page highlight) ──────────────────────
        # The main event and primary action of the page: a prominent, accented card
        # that owns its own title and either a tall "all caught up" empty state or a
        # highlighted inner panel holding the per-course file expanders (for visual
        # depth + hierarchy). The "last run" notice lives OUTSIDE, above the hero.
        groups = _todays_groups()
        with st.container(key="today_files_hero"):
            # Adaptive header: a live file-count badge + "grouped by course" copy when
            # there are files today; a calmer "lands here" line when all caught up.
            if groups:
                _total = sum(len(g.get("files") or []) for g in groups)
                _cnt_label = f"{_total} file" if _total == 1 else f"{_total} files"
                _badge = (
                    f"<span class='today-files-hero-count'>{esc(_cnt_label)}</span>"  # audit-ignore: static wrapper, int count
                )
                _sub = "Grouped by course &ndash; ready to open."
            else:
                _badge = ""
                _sub = "New downloads from your daily sync land here."
            st.markdown(
                f"<div class='today-files-hero-head'>"
                f"<div class='today-files-hero-titles'>"
                f"<div class='today-files-hero-titlerow'>"
                f"<span class='today-files-hero-title'>Today's files</span>{_badge}</div>"
                f"<div class='today-files-hero-sub'>{_sub}</div>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

            if not groups:
                st.markdown(
                    f"<div class='today-files-empty'>"
                    f"<div class='today-empty-icon'>{_SVG_CAUGHT_UP}</div>"  # audit-ignore: static SVG constant
                    f"<div class='today-files-empty-title'>No new files today</div>"
                    f"<div class='today-files-empty-sub'>You're all caught up.</div></div>",
                    unsafe_allow_html=True,
                )
            else:
                with st.container(key="today_files_inner"):
                    # Inject the shared card + file-row CSS ONCE here, OUTSIDE the
                    # fragment below, so an expand/collapse (fragment-scoped rerun)
                    # doesn't re-inject it and the <style> elements stay direct
                    # children of this gap:0 panel instead of inside the fragment's
                    # own (gapped) block - which was banding space above the 1st card.
                    from shared.components import inject_file_action_css
                    inject_file_action_css()
                    inject_css("sync_history_cards.css")
                    _render_today_files(groups)

        # ── Quick Sync now — the manual, on-demand alternative to auto-sync ─────
        # Rebuilt as an integrated action CARD in the page's card language (icon
        # badge + explainer on the left, brand Quick Sync button on the right).
        # Daily auto-sync (the toggle up top) is the hands-off primary path; this
        # card is the "bring these courses up to date right now" manual option.
        with st.container(key="today_qs_section"):
            runnable = resolve_today_pairs()
            _qs_info, _qs_btn = st.columns([0.66, 0.34], vertical_alignment="center")
            with _qs_info:
                st.markdown(
                    "<div class='today-qs-card'>"
                    f"<div class='today-qs-icon'>{_SVG_QS_REFRESH}</div>"  # audit-ignore: static SVG constant
                    "<div class='today-qs-text'>"
                    "<div class='today-qs-title'>Sync on demand</div>"
                    "<div class='today-qs-sub'>Daily auto-sync runs each morning "
                    "&mdash; trigger a manual Quick Sync any time to bring these "
                    "courses up to date right now.</div>"
                    "</div></div>",
                    unsafe_allow_html=True,
                )
            with _qs_btn:
                # Disabled tooltip reasons (help wraps button in stTooltipHoverTarget)
                help_text = None
                if not runnable:
                    help_text = "Add courses to your daily sync list to enable manual quick sync."
                elif sync_running:
                    help_text = "A sync is already in progress."

                if st.button("Quick Sync now", type="primary", use_container_width=True,
                             key="today_sync_now_btn", disabled=not runnable or sync_running,
                             help=help_text):
                    start_today_sync(runnable)  # sets state + st.rerun()
