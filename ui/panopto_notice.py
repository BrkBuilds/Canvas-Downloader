"""One-time acceptable-use notice for Panopto lecture downloads.

Shown once (per :data:`shared.legal.PANOPTO_NOTICE_VERSION`) before the first
recording is fetched, from whichever entry path the user reaches first. See
``shared/legal.py:require_panopto_notice`` for the guard and ``DISCLAIMER.md``
for the full text this summarises.

Two rules from CLAUDE.md govern where this lives, and both are load-bearing:

* **Hosted at the BOTTOM of app.py**, never from the card that triggers it. A
  dialog emitted before the main page inserts its elements ahead of every
  main-page style host, and Streamlit reconciles those hosts by INDEX - the page
  behind the modal then renders with its neighbours' stylesheets for ~110ms.
* **Not gated behind ``help_text_enabled()``.** This is operational copy (it
  states what the software does and does not check), not tuition about the UI.
  The Settings "Show help text" toggle must never be able to hide it.

**Palette: ONE accent, and it is blue.** The first pass used the Panopto purple
for the chip and the primary button, amber for the callout and cyan for the
link - four competing hues on a screen whose entire job is to look sober and
trustworthy. Everything is now neutral greys plus a single blue, and the only
other colour in the dialog is the Panopto mark itself, which is a subject
identifier rather than an accent. Amber in particular was wrong here: this
notice is important information, not a hazard warning, and the alarm colour
made a calm statement of fact read as a scare.

Layout: the entire body is ONE ``st.markdown`` call, so the dialog holds exactly
TWO elements (copy + button row) and therefore exactly ONE of Streamlit's ~1rem
block gaps, which the copy block's own bottom margin then owns.
"""

from __future__ import annotations

import logging
import streamlit as st

from shared import theme
from shared.helpers import esc, get_base64_image
from shared.legal import (
    DISCLAIMER_URL, accept_panopto_notice, apply_pending_resume,
    dismiss_panopto_notice, resume_is_pending, skip_panopto_and_continue,
)

#: Which sentence the decline button should say. The run-start paths are opting
#: OUT of something about to happen ("skip"); the Today card is opting IN to
#: something already switched off, where a "skip" verb is nonsense.
NOTICE_CONTEXT_KEY = "_panopto_notice_context"
_DECLINE_LABEL = {"run": "Skip Panopto recordings", "optin": "Not now"}

logger = logging.getLogger(__name__)

#: The app's own Panopto mark, the same asset Section 4 uses for the feature.
#: A real product icon rather than a generic lucide camera: this dialog names a
#: specific system, and the mark is what the user already associates with it.
_PAN_ICON = "assets/pan_icon.png"

# ── Lucide glyphs ────────────────────────────────────────────────────────────
# Inline SVG for anything inside the copy block (st.markdown lands in the main
# DOM, so these are styleable and need no encoding). The two BUTTON icons must
# be URL-encoded data URIs instead: st.button takes plain text only, so they are
# painted as a ::before on the button element.
_SVG_INFO = (
    "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'>"
    "<circle cx='12' cy='12' r='10'/><path d='M12 16v-4'/><path d='M12 8h.01'/></svg>"
)
_SVG_EXTERNAL = (
    "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'>"
    "<path d='M15 3h6v6'/><path d='M10 14 21 3'/>"
    "<path d='M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'/></svg>"
)

# Button ::before icons. Stroke colours are baked in per state, so hover swaps
# the whole data URI rather than trying to recolour an SVG it cannot reach.
_ICON_X = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
    "fill='none' stroke='%238a91a6' stroke-width='2.2' stroke-linecap='round'%3E"
    "%3Cpath d='M18 6 6 18'/%3E%3Cpath d='m6 6 12 12'/%3E%3C/svg%3E"
)
# Spelled out rather than derived with .replace() from _ICON_X. A derived value
# loses its literal provenance, so the architecture audit's Rule 4 correctly
# stops being able to vouch for it - and reaching for `# audit-ignore` to shut
# that up would blunt the one check that found a real XSS in this repo.
_ICON_X_HOVER = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
    "fill='none' stroke='%23c7ccd9' stroke-width='2.2' stroke-linecap='round'%3E"
    "%3Cpath d='M18 6 6 18'/%3E%3Cpath d='m6 6 12 12'/%3E%3C/svg%3E"
)
_ICON_SHIELD = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
    "fill='none' stroke='%23ffffff' stroke-width='2.2' stroke-linecap='round' "
    "stroke-linejoin='round'%3E%3Cpath d='M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67 "
    "0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 "
    "0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z'/%3E%3Cpath d='m9 12 2 2 4-4'/%3E%3C/svg%3E"
)


def _inject_notice_css() -> None:
    """Scoped stylesheet for the notice modal.

    Emitted inside the dialog, which app.py hosts AFTER every main-page element,
    so adding or removing it shifts no main-page style host (the reason the
    "never emit a stylesheet conditionally" rule does not bite here).
    """
    st.markdown(f"""<style>
    /* `> div:first-child` is the TITLE wrapper, NOT the body - measured in 1.51
       on this dialog: it is ~89px tall (padding + the zero-width-space title)
       and sits 327px above the dialog's bottom edge. So a `padding-bottom` here
       is invisible; the real bottom inset is 24px on `> div:nth-child(2)`, the
       body wrapper. Only padding-TOP is useful here, and it must stay at/above
       ~1.5rem or the pulled-up custom header clips. */
    div[data-testid="stDialog"] div[role="dialog"] > div:first-child {{
        padding-top: 1.7rem !important;
    }}
    div[data-testid="stDialog"] button[aria-label="Close"] {{ display: none !important; }}

    /* ── Header: the Panopto mark + title ───────────────────────────────── */
    div[data-testid="stDialog"] .cd-pn-head {{
        display: flex; align-items: center; gap: 12px;
        /* -83px lands the chip 24.2px below the dialog's top edge, matching the
           24px the body wrapper already puts under the button row (and the
           sides are 24/24 too). Swept in the live DOM rather than derived: the
           title wrapper's height feeds into this, so the arithmetic from the
           declared padding is not what renders. */
        margin-top: -83px; margin-bottom: 15px;
    }}
    /* The mark stands on its own at full size - no plate behind it. A tinted
       chip was half the skittle problem, and a neutral one just shrank the
       icon for no gain. */
    div[data-testid="stDialog"] .cd-pn-chip {{
        flex: 0 0 auto; display: flex; align-items: center;
    }}
    div[data-testid="stDialog"] .cd-pn-chip img {{
        width: 34px; height: 34px; display: block;
    }}
    div[data-testid="stDialog"] .cd-pn-title {{
        font-size: 1.2rem; font-weight: 700; color: {theme.WHITE};
        line-height: 1.25; margin: 0; letter-spacing: -0.01em;
    }}

    /* ── Body copy ──────────────────────────────────────────────────────── */
    div[data-testid="stDialog"] .cd-pn-p {{
        font-size: 0.92rem; line-height: 1.62; color: {theme.TEXT_STEEL};
        margin: 0 0 13px 0;
    }}
    div[data-testid="stDialog"] .cd-pn-p b {{ color: {theme.WHITE}; font-weight: 600; }}

    /* The one thing a user is least likely to know: the app does not read
       Panopto's per-recording download permission. RECESSED (dark well + inset
       shadow) so it reads as a distinct stratum, and emphasised with WEIGHT and
       white ink rather than an alarm colour - it is a statement of fact about
       the software, not a hazard. */
    div[data-testid="stDialog"] .cd-pn-key {{
        display: flex; align-items: flex-start; gap: 11px;
        background: rgba(0, 0, 0, 0.22);
        border: 1px solid rgba(255, 255, 255, 0.09);
        border-left: 3px solid {theme.ACCENT_BLUE};
        border-radius: 4px 10px 10px 4px;
        padding: 12px 14px; margin: 0 0 14px 0;
        box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.35);
    }}
    div[data-testid="stDialog"] .cd-pn-key svg {{
        width: 16px; height: 16px; flex: 0 0 auto;
        margin-top: 2px; color: {theme.ACCENT_BLUE};
    }}
    div[data-testid="stDialog"] .cd-pn-key span {{
        font-size: 0.9rem; line-height: 1.58; color: {theme.TEXT_STEEL};
    }}
    div[data-testid="stDialog"] .cd-pn-key b {{
        color: {theme.WHITE}; font-weight: 650;
    }}

    /* The permanent escape hatch, stated on EVERY appearance rather than
       revealed after N declines. Late help reads as help that was withheld,
       and a decline counter would cost more persisted state than the single
       setting it advertises. */
    div[data-testid="stDialog"] .cd-pn-settings {{
        font-size: 0.84rem; line-height: 1.55; color: {theme.TEXT_SECONDARY};
        margin: 0 0 12px 0;
    }}
    div[data-testid="stDialog"] .cd-pn-settings b {{
        color: {theme.TEXT_STEEL}; font-weight: 600;
    }}

    /* ── Full-disclaimer link ───────────────────────────────────────────── */
    /* A PLAIN text link: no padding, no chip, no bordered box.
       Measured 2026-07-30: hiding the native close button makes this the
       dialog's first tabbable element, so baseweb autofocuses it and any focus
       styling fires on EVERY open, not just on keyboard navigation. While the
       link carried button-sized padding, both the hover chip and the focus ring
       drew a rounded rect the size of a control - so the dialog appeared to have
       THREE buttons, one of them permanently highlighted. Stripping the padding
       fixes the cause rather than the symptom: with the ring hugging the text it
       reads as a focused link, which is what it is, and keyboard focus stays
       visible instead of being suppressed. */
    div[data-testid="stDialog"] .cd-pn-link {{
        display: inline-flex; align-items: center; gap: 7px;
        font-size: 0.86rem; font-weight: 500;
        color: {theme.ACCENT_LINK}; text-decoration: none;
        padding: 0; margin: 0 0 18px 0;
        border-radius: 3px;
        transition: color 0.18s ease;
    }}
    div[data-testid="stDialog"] .cd-pn-link svg {{ width: 13px; height: 13px; }}
    div[data-testid="stDialog"] .cd-pn-link:hover {{
        color: {theme.WHITE};
        text-decoration: underline; text-underline-offset: 3px;
    }}
    /* Focus shows as an UNDERLINE, never a ring. Any box here - border, chip or
       outline - draws a control-sized rect that reads as a third button, and
       because of the autofocus above it would be drawn on every single open.
       An underline is the conventional focus indicator for a text link, so
       keyboard focus stays visible without inventing a button. Brightened to
       white so it is still distinguishable from the hover state. */
    div[data-testid="stDialog"] .cd-pn-link:focus-visible {{
        outline: none;
        color: {theme.WHITE};
        text-decoration: underline; text-underline-offset: 3px;
    }}

    /* ── Action row ─────────────────────────────────────────────────────── */
    div[data-testid="stDialog"] div[class*="st-key-pan_notice_"] button {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 9px !important;
        width: 100% !important;
        min-height: 44px !important;
        height: auto !important;
        padding: 0.55rem 1rem !important;
        border-radius: 10px !important;
        font-size: 0.92rem !important;
        font-weight: 600 !important;
        transition: background-color 0.18s ease, border-color 0.18s ease,
                    transform 0.12s ease, box-shadow 0.18s ease !important;
    }}
    /* The label is plain text, so Streamlit renders NO paragraph element for it
       (measured in 1.51) - the icon therefore goes on the BUTTON, not on a p. */
    div[data-testid="stDialog"] div[class*="st-key-pan_notice_"] button::before {{
        content: "" !important;
        width: 16px !important; height: 16px !important;
        flex: 0 0 auto !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
    }}

    div[data-testid="stDialog"] div[class*="st-key-pan_notice_cancel"] button {{
        background: rgba(255, 255, 255, 0.035) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        color: {theme.TEXT_SECONDARY} !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_notice_cancel"] button::before {{
        background-image: url("{_ICON_X}") !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_notice_cancel"] button:hover {{
        background: rgba(255, 255, 255, 0.075) !important;
        border-color: rgba(255, 255, 255, 0.22) !important;
        color: {theme.TEXT_STEEL} !important;
    }}
    div[data-testid="stDialog"] div[class*="st-key-pan_notice_cancel"] button:hover::before {{
        background-image: url("{_ICON_X_HOVER}") !important;
    }}

    /* Primary: deliberately NO colour or shadow of its own. This is the app's
       standard primary action, so it inherits global.css's
       button[kind="primary"] (#1f77b4 + inset highlight, brighter on hover) and
       looks identical to "Confirm and Download". The first pass painted its own
       background with a wide outer glow - a second, tackier primary style that
       existed nowhere else in the app. Only the icon is added here. */
    div[data-testid="stDialog"] div[class*="st-key-pan_notice_accept"] button::before {{
        background-image: url("{_ICON_SHIELD}") !important;
    }}
    </style>""", unsafe_allow_html=True)


#: How long the teardown run gets before the resume fires. Matches the sync
#: flow's own handover (`sync_ui._advance_to_sync`, 0.4s) closely enough to feel
#: like one interaction rather than a wait.
_ADVANCE_EVERY = 0.3


def render_pending_resume() -> None:
    """Fire an answered notice's action, one COMPLETED run after it closed.

    The two-step is the entire fix for "the dialog stayed on top of the running
    download". Applying the resume in the same run that closes the modal sends
    that run straight into ``asyncio.run(download_course_async(...))``
    (``app.py:1359``), which blocks long before the dialog host at
    ``app.py:2586``. Streamlit removes an element only when a completed run
    stops producing it, so the modal stayed painted - stale-faded grey, because
    it had been marked stale but never dropped.

    The first call here is INLINE, during the run that just closed the dialog,
    and it deliberately returns without doing anything: that lets this run reach
    the end of the script, which is what actually removes the modal from the
    DOM. The timer then fires a second run that applies the resume. Same
    mechanism, and the same reason, as ``sync_ui._advance_to_sync``'s
    "inline call during the teardown run - wait for the timer".
    """
    st.session_state['_pan_resume_tick'] = 0

    @st.fragment(run_every=_ADVANCE_EVERY)
    def _advance() -> None:
        seen = st.session_state.get('_pan_resume_tick', 0)
        st.session_state['_pan_resume_tick'] = seen + 1
        if seen == 0:
            return  # teardown run - let it finish so the dialog is really gone
        if not resume_is_pending():
            return
        st.session_state.pop('_pan_resume_tick', None)
        apply_pending_resume()
        st.rerun(scope="app")

    _advance()


def _on_dismiss() -> None:
    """Native Escape / click-outside. Closes WITHOUT accepting.

    The gated action does not proceed: the caller returned early without setting
    a run status, so dismissing simply leaves the user where they were. Wired as
    the dialog's ``on_dismiss`` so an Escape can never leave the open-flag set
    (which would re-open the modal on the next rerun, unclosable).
    """
    dismiss_panopto_notice()


@st.dialog("​", width="medium", on_dismiss=_on_dismiss)
def render_panopto_notice() -> None:
    """The one-time acceptable-use notice. All copy here is static."""
    _inject_notice_css()

    _icon = get_base64_image(_PAN_ICON)
    _chip = (
        f'<img src="data:image/png;base64,{_icon}" alt="" />' if _icon else ""
    )

    st.markdown(
        f"""<div class="cd-pn-head">
          <div class="cd-pn-chip">{_chip}</div>
          <p class="cd-pn-title">Before you download Panopto lecture recordings</p>
        </div>
        <p class="cd-pn-p"><b>How Panopto recordings are downloaded:</b> Canvas
        Downloader uses your own Canvas token and URL to save the same video your
        Panopto player streams to you when you watch a recording in Canvas. This
        does not break any copy protection - your own account is already allowed
        to open it.</p>
        <div class="cd-pn-key">{_SVG_INFO}<span><b>Important:</b> Panopto has a
        download button your institution can switch on or off per recording.
        This app does not read that setting. Saving a recording may still be
        against your institution&#39;s rules, and doing so is your own
        responsibility.</span></div>
        <p class="cd-pn-p"><b>Download responsibly, and never share:</b>
        Recordings belong to your lecturer and your institution. Keep them for
        your own study. Never share, upload or republish them. You are
        responsible for how you use what you download.</p>
        <p class="cd-pn-settings">Never want lecture recordings? You can turn
        Panopto off completely in <b>Settings</b>, and this will not be shown
        again.</p>
        <a class="cd-pn-link" href="{esc(DISCLAIMER_URL)}" target="_blank"
           rel="noopener noreferrer">{_SVG_EXTERNAL}Read the full disclaimer</a>""",
        unsafe_allow_html=True,
    )

    _decline = _DECLINE_LABEL.get(
        st.session_state.get(NOTICE_CONTEXT_KEY, "run"), _DECLINE_LABEL["run"])

    _c1, _c2 = st.columns([1, 1], gap="small")
    with _c1:
        if st.button(_decline, key="pan_notice_cancel", use_container_width=True):
            # Declining is an ANSWER, so the run the user asked for still
            # starts - just without recordings. It used to call dismiss(),
            # which swallowed the click and left them on the same screen with
            # nothing happening and no explanation.
            skip_panopto_and_continue()
            st.rerun(scope="app")
    with _c2:
        if st.button("I understand", key="pan_notice_accept", type="primary",
                     use_container_width=True):
            accept_panopto_notice()
            st.rerun(scope="app")
