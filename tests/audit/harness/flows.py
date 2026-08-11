"""Drive the application the way a user does.

Every step is addressed by the widget ``key`` the app already assigns and every
state change is VERIFIED after it is made, because a configuration that silently
failed to apply turns the whole run into a false negative - the download
succeeds, the checks pass, and nothing was actually tested.

The one non-obvious mechanic is how a toggle's state is read. The download
settings are not checkboxes; they are ``st.button``s styled as cards, and their
on/off state lives only in CSS. Measured in the running app:

    OFF   border-color rgba(255, 255, 255, 0.1)   (achromatic, near-transparent)
    ON    border-color rgb(249, 115, 22)          converters   (orange)
          border-color rgb(104, 212, 163)         Canvas Content (green)
          border-color rgb(184, 157, 254)         Panopto      (purple)
          border-color rgb(63, 217, 255)          segmented radios (cyan)

So the rule is "ON iff the border colour is CHROMATIC", not a list of hexes.
That survives a palette change, which a hard-coded hex would not - and this
project actively polices colour drift, so hexes here would rot quickly.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import conditions
from .browser import Session

# --------------------------------------------------------------------------
# config -> widget key
# --------------------------------------------------------------------------

SEGMENTED = {
    "file_filter": {"all": "btn_include_all", "study": "btn_include_study"},
    "mode": {"modules": "btn_org_subfolders", "subfolders": "btn_org_subfolders",
             "flat": "btn_org_flat"},
    "secondary_isolated": {False: "btn_sec_org_inline", True: "btn_sec_org_subfolders"},
    "pan_layout": {"match": "btn_pan_layout_match", "separate": "btn_pan_layout_separate"},
}

TOGGLES = {
    **{f"convert_{n}": f"btn_convert_{n}" for n in
       ("zip", "pptx", "word", "excel", "html", "code", "urls", "video")},
    **{f"dl_{n}": f"btn_dl_{n}" for n in
       ("assignments", "syllabus", "announcements", "discussions", "quizzes",
        "submissions")},
    # "url" is the Shortcut output (a .url / .webloc link file), and it was
    # missing here while `crosscheck.PANOPTO_OUTPUTS` already carried it - so the
    # checker for the newest Panopto output kind could never fire, which ground
    # rule 7 calls worse than having no check at all. It is FIRST in the app's
    # own PANOPTO_OUTPUTS list and is the only output that costs no bandwidth,
    # so a driver that cannot set it cannot test the cheap path at all.
    **{f"pan_out_{n}": f"btn_pan_out_{n}" for n in ("url", "mp4", "mp3", "txt", "srt")},
}

# Cards 2/3/4 collapse; their contents do not exist in the DOM until expanded.
CARD_FOR = {"dl_": "toggle_card2", "convert_": "toggle_card3", "pan_": "toggle_panopto"}

IS_ON_JS = r"""
(key) => {
  const host = document.querySelector('[class*="st-key-' + String(key).toLowerCase() + '"]');
  const b = host && (host.matches('button') ? host : host.querySelector('button'));
  if (!b) return { found: false };
  const bc = getComputedStyle(b).borderTopColor;
  const m = bc.match(/rgba?\(([^)]+)\)/);
  if (!m) return { found: true, on: false, border: bc };
  const p = m[1].split(',').map(x => parseFloat(x));
  const [r, g, bl] = p;
  const a = p.length > 3 ? p[3] : 1;
  // Chromatic = the channels genuinely differ. Every OFF state in this app is
  // white-at-low-alpha or fully transparent; every ON state is a saturated
  // accent. Alpha guards the transparent segmented-unselected case.
  const spread = Math.max(r, g, bl) - Math.min(r, g, bl);
  return { found: true, on: spread > 24 && a > 0.5, border: bc, spread };
}
"""


class FlowError(RuntimeError):
    pass


class Flow:
    """Shared helpers. One instance wraps one :class:`Session`."""

    def __init__(self, s: Session, rp=None):
        self.s = s
        self.rp = rp or s.rp
        self.trace: list[dict] = []

    def _log(self, action: str, **kw):
        self.trace.append({"t": time.strftime("%H:%M:%S"), "action": action, **kw})
        return kw

    def is_on(self, key: str) -> dict:
        return self.s.page.evaluate(IS_ON_JS, key)

    def set_toggle(self, key: str, want: bool, retries: int = 2) -> dict:
        """Click until the toggle reads the requested state, then verify.

        Verification is the point. These are ordinary buttons driving session
        state through a rerun; a click that lands while the previous rerun is
        still in flight can be dropped, and an unverified 'convert_excel = on'
        produces a run that quietly tested nothing.
        """
        for attempt in range(retries + 1):
            cur = self.is_on(key)
            if not cur.get("found"):
                # Do not give up on the first sample. Every toggle click drives a
                # rerun, and while that rerun is in flight the card's controls can
                # be absent for a beat - so a single read says "collapsed" about a
                # card that is merely re-rendering. Measured 2026-08-08 on m014:
                # convert_zip/pptx/word were set, then the next FIVE in the same
                # loop all reported "control not present" and the row silently
                # tested none of them. Poll before believing it; `_reopen` below
                # then handles a card that really did close.
                if not self._await_key(key, "button", 8):
                    return self._log("set_toggle", key=key, ok=False,
                                     reason="control not present (card collapsed?)")
                cur = self.is_on(key)
            if bool(cur.get("on")) == bool(want):
                return self._log("set_toggle", key=key, want=want, ok=True,
                                 changed=attempt > 0)
            self.s.click(key)
        final = self.is_on(key)
        ok = bool(final.get("on")) == bool(want)
        return self._log("set_toggle", key=key, want=want, ok=ok, final=final)

    def _set_toggle_in_card(self, card_key: str, key: str, want: bool) -> dict:
        """set_toggle, but re-open the card once if the control is really gone.

        A card that has genuinely collapsed cannot be recovered by polling, and
        the loops set several toggles in a row - so one collapse mid-loop drops
        every remaining factor on that card. Re-expanding costs one click on the
        rare path and nothing on the normal one.
        """
        r = self.set_toggle(key, want)
        if r.get("ok") or "not present" not in str(r.get("reason", "")):
            return r
        self.expand_card(card_key)
        return self.set_toggle(key, want)

    def expand_card(self, card_key: str, want_open: bool = True) -> dict:
        """Card 2/3/4 headers are buttons whose contents mount only when open."""
        probe_key = {"toggle_card2": "btn_dl_secondary_master",
                     "toggle_card3": "btn_convert_master",
                     "toggle_panopto": "btn_pan_master"}[card_key]
        for _ in range(3):
            present = self.s.probe_key(probe_key).get("found", False)
            if present == want_open:
                return self._log("expand_card", card=card_key, open=want_open, ok=True)
            self.s.click(card_key)
        return self._log("expand_card", card=card_key, open=want_open, ok=False)

    # -- global settings ---------------------------------------------------

    def set_size_cap(self, mb: int | None) -> dict:
        """Set "Skip large files" in the Settings dialog.

        **The size cap is not on the download page at all** - it is a global
        setting (``ui/auth.py``, ``stg_card_maxsize``) that the engine reads
        from session state at download time. ``configure`` only knows the
        download page, so the ``max_file_size`` factor was accepted into every
        matrix row and applied to none of them: half the plan believed it was
        testing the capped path and ran the uncapped one twice.

        Verified downstream rather than by trusting the click - the engine logs
        ``Max file size: 5 MB`` or ``disabled`` in its parameter line, and
        ``_size_cap_applied`` in crosscheck compares that against what the row
        asked for.
        """
        want_on = bool(mb)
        # The sidebar only exists once the app is loaded, and this may be the
        # first thing a row does against a fresh browser.
        if not self.s.probe_key("nav_btn_settings").get("found"):
            self.s.goto(self.s.app_url("download", "1"))
        opened = self.s.click("nav_btn_settings")
        if not opened.get("clicked"):
            raise FlowError(f"Settings button not clickable: {opened}")
        # The dialog is a portal invoked at the END of app.py's render on the NEXT
        # rerun (the button only sets a flag), and its BODY renders a beat after the
        # container - so on a cold first row a single sample raced it ("Settings
        # dialog did not open" / "Save Settings button not found"). Wait for the
        # toggle: it is the first body control we touch and renders together with
        # the container and the Save button, so gating on it covers all three.
        # probe_key polls the WIDGET, not the dialog, so the dialog-close polling
        # accounting below is unchanged.
        self._await_key("temp_max_size_enabled", "checkbox", 20)
        dlg = self.s.page.locator('[data-testid="stDialog"]').first
        if dlg.count() == 0:
            raise FlowError("Settings dialog did not open")

        tog = self.s.set_checkbox("temp_max_size_enabled", want_on)
        if want_on:
            # NOT s.fill(): it commits by clicking stMain, which is the scrim
            # here and would dismiss the dialog. A number input commits on
            # Enter, which is a real key press and therefore trusted by React.
            box = self.s._host("temp_max_size_mb").locator("input").first
            box.click(timeout=15000)
            box.fill("")
            box.type(str(int(mb)), delay=12)
            box.press("Enter")
            self.s.settle()

        # Address Save by its KEY, not by its accessible name. The app keys it
        # `stg_btn_save` with a comment saying it did so "so the live audit can
        # drive it", and a role+name lookup is a single sample against an
        # accessibility tree that a dialog rerun rebuilds - the number input's
        # Enter commit above IS such a rerun. Measured on 2026-08-08: two lanes
        # died on their first row with "Save Settings button not found" against
        # a dialog that had rendered it perfectly, and neither could be
        # reproduced by hand. `_await_key` polls, so a rebuild in flight costs
        # a retry instead of the row.
        if not self._await_key("stg_btn_save", "button", 20):
            raise FlowError("Save Settings button not found in the dialog")
        self.s.click("stg_btn_save")
        self.s.settle()

        # WAIT for the dialog to go, do not sample once. `settle()` returns when
        # the DOM stops changing, and the modal's unmount can land just after -
        # a single read then said "did not close" on a row that had closed it
        # perfectly and went on to configure and download without a hitch. A
        # check that cries wolf on a healthy run is worse than no check.
        closed = self._await_dialog_gone()
        forced = False
        if not closed:
            # Streamlit only enables Save when something CHANGED, so asking for
            # the state the app is already in leaves a disabled button and an
            # open modal - which the next click would have to fight. Escape is
            # how a user leaves it.
            self.s.page.keyboard.press("Escape")
            self.s.settle()
            closed = self._await_dialog_gone()
            forced = True

        return self._log("set_size_cap", mb=mb, toggle=tog,
                         dialog_closed=closed, closed_with_escape=forced,
                         ok=closed)

    def _await_dialog_gone(self, timeout: float = 10.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.s.page.locator('[data-testid="stDialog"]').count() == 0:
                return True
            time.sleep(0.25)
        return False


# ==========================================================================
# download
# ==========================================================================

    def _accept_panopto_notice(self, wait_s: float = 0.0,
                               until: str | None = "download_running_or_done",
                               stop_key: str | None = None) -> dict:
        """Dismiss the Panopto acceptable-use notice if it is on screen.

        `shared.legal.require_panopto_notice` gates the Panopto pass behind a
        one-time acknowledgement recorded as `panopto_notice_ack_version` in the
        settings file. The audit isolates `CANVAS_DL_CONFIG_DIR`, so the ack is
        absent on every run and the dialog appears whenever a row selects any
        Panopto output - exactly like the first-run Automation batch that
        MAC_RUNBOOK tells you not to report. It is the harness's job to answer
        it, not the product's job to skip it.

        It went unnoticed until a FRESH machine, and the reason is worth
        recording: a developer's real settings file already carries the ack, and
        `paths.app_env` seeds the isolated config from it, so every previous
        Panopto row inherited an acknowledgement it never had to give. On this
        rented Mac the settings file was written by
        `scripts/mac_audit_bootstrap.sh` and has no ack - so the row simply
        stopped, with the dialog waiting and the flow burning its whole timeout.
        Measured 2026-08-10: 15 minutes on a 1-line debug log, and the download
        began the instant `pan_notice_accept` was clicked.

        Answering it is also the honest configuration: the row asked for Panopto
        outputs, so "I understand" is what a user who wanted them would press.
        Clicking `pan_notice_skip` would silently turn the feature off and the
        row would then be judged against a config it never ran.

        WAIT_S EXISTS BECAUSE THE NOTICE IS RAISED **BY** THE CONFIRM CLICK, and
        the first version of this fix probed for it BEFORE that click - so on a
        genuinely fresh config dir it could never see the thing it was written to
        answer. Measured on macOS 26.6, 2026-08-11, with the dialog open on
        screen: the wizard still reports step `configure`, and BOTH conditions
        `confirm_and_run` then waits on (`download_running_or_done`, then
        `download_terminal`) evaluate false - so the row burns 900s and then
        5400s and reports a phase that never started. All four
        `require_panopto_notice` call sites (download settings, quick download,
        sync page, sync review) are ACTION handlers; none renders at page-render
        time, so there is no arrangement in which the pre-click probe fires.

        The pre-click probe is kept, because a dialog left open by a previous row
        is a real state, and answering it is free.

        *until* names the condition meaning "this action got under way without a
        notice", and *stop_key* a widget whose presence means the same thing, so
        a row that never raises one pays a poll rather than the whole budget.
        They differ per flow - a download starts downloading, a sync review opens
        the Confirm Sync dialog - which is why they are parameters.

        The budget is SHORT on purpose. `require_panopto_notice` sets its flag
        synchronously in the click handler, so the dialog is on screen by the
        next rerun or it is never coming; anything longer only slows every row
        that will never see it.
        """
        deadline = time.time() + max(0.0, wait_s)
        while True:
            if self.s.probe_key("pan_notice_accept").get("found"):
                r = self.s.click("pan_notice_accept")
                return {"shown": True, "accepted": bool(r.get("clicked"))}
            if time.time() >= deadline:
                return {"shown": False}
            # A row that never raises the notice must not pay the whole budget:
            # the moment the run is visibly under way (or already finished, for
            # a course that delivers in under a second - see checker defect 28),
            # there is nothing left to wait for.
            if stop_key and self.s.probe_key(stop_key).get("found"):
                return {"shown": False, "moved_on": stop_key}
            if until:
                started = self.s.wait_for(conditions.get(until), timeout=0.1,
                                          poll=0.1, label="notice_wait_shortcut")
                if started.get("done"):
                    return {"shown": False, "run_started_first": True}
            time.sleep(1.0)


class DownloadFlow(Flow):

    def _await_gate_open(self, timeout: float = 20.0) -> bool:
        """Poll until the selection gate stops covering the primary actions.

        Reads the button the same way a user's pointer does - `pointer-events`
        - rather than the `data-cd-has-sel` attribute behind it, so the wait
        cannot pass while the paint the attribute drives is still absent. A
        timeout is NOT swallowed: it returns False and the click below then
        fails with the full probe, which is the finding.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            p = self.s.probe_key("btn_custom_download", "button")
            if p.get("found") and not p.get("gated"):
                return True
            time.sleep(0.3)
        return False

    def _await_key(self, key: str, role: str = "checkbox", timeout: float = 60.0) -> bool:
        """Poll until ``st-key-<key>`` carries an interactive element, or timeout.

        ``goto(ready=True)`` only proves the boot overlay lifted; on a COLD app
        (every lane worker's first row) the course list is fetched and rendered
        AFTER that, so a click/tick issued immediately races a list that does not
        exist yet. ``set_checkbox`` probes once with no retry, so the race showed
        up as an 81s dead wait ending in "could not select 43667" - deterministic,
        and it cascaded the whole lane. This is the wait that closes that gap.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.s.probe_key(key, role).get("found"):
                return True
            time.sleep(0.5)
        return False

    def select_courses(self, course_ids: list[int], view: str = "all") -> dict:
        """Tick the given courses on step 1.

        Defaults to the All Courses view: the Favorites view is a subset, and a
        course that is simply not in it produces "no host for key" - which looks
        exactly like a broken selector and cost a debugging detour the first time.
        """
        self.s.goto(self.s.app_url("download", "1"))
        # Wait for the course-list toolbar before touching anything: it renders
        # only once the (cold) app has fetched the course list, so this warms the
        # app before the view switch instead of racing it.
        self._await_key("btn_course_clear_selection", "button", 120)
        if view == "all":
            self.s.click("btn_fav_all_dl")
        elif view == "favorites":
            self.s.click("btn_fav_favorites_dl")
        self.s.click("btn_course_clear_selection")

        results = []
        for cid in course_ids:
            # The Favorites->All switch (and any non-favorite like 43667) appears
            # only after that rerun lands; wait for THIS target before ticking.
            present = self._await_key(f"dl_chk_{cid}", "checkbox", 60)
            r = self.s.set_checkbox(f"dl_chk_{cid}", True) if present \
                else {"set": False, "reason": "checkbox never appeared (view switch or list render)"}
            results.append({"course_id": cid, "ok": r.get("verified", r.get("set"))})
        bad = [r for r in results if not r["ok"]]
        if bad:
            raise FlowError(f"Could not select course(s): {bad}")
        return self._log("select_courses", courses=course_ids, results=results)

    def open_custom(self) -> dict:
        # The primary actions are gated in CSS, not server-side: the button sits
        # OUTSIDE the course-list fragment, so `disabled=` cannot see a tick made
        # inside it (ui/course_selector._gate_actions_on_selection). Availability
        # is published by a components.html bridge as `data-cd-has-sel` on BODY,
        # and that bridge is an iframe whose boot is not synchronous with the
        # tick React has already committed. So `set_checkbox` can verify a course
        # is selected in the very frame the gate still reads "nothing selected" -
        # measured on a cold lane 2026-08-08, one row lost per lane. The gate
        # lifts on its own; wait for it rather than sampling once.
        self._await_gate_open()
        r = self.s.click("btn_custom_download")
        if not r.get("clicked"):
            raise FlowError(f"Custom Download not clickable: {r}")
        # The click SCHEDULES a rerun; the step tracker flips to 2 only once that
        # rerun lands, and Card 2's content lazy-loads (a "Loading..." spinner is
        # visible on screen), so a single settle can return during a transient
        # quiet BEFORE the transition. Poll the step off the tracker rather than
        # reading it once - measured landing on step 1 on the very next frame.
        deadline = time.time() + 20.0
        st = self.s.extract("screen")
        while st.get("step") != "2" and time.time() < deadline:
            time.sleep(0.3)
            st = self.s.extract("screen")
        if st.get("step") != "2":
            raise FlowError(f"Expected step 2, got {st.get('step')}")
        return self._log("open_custom", step=st.get("step"))

    def open_quick(self) -> dict:
        r = self.s.click("btn_quick_download")
        if not r.get("clicked"):
            raise FlowError(f"Quick Download not clickable: {r}")
        return self._log("open_quick", screen=self.s.extract("screen").get("step"))

    def configure(self, config: dict) -> dict:
        """Apply a matrix row to the Custom Download screen and verify all of it."""
        applied, failed = {}, []

        for name, mapping in SEGMENTED.items():
            if name not in config:
                continue
            key = mapping.get(config[name])
            if not key:
                failed.append({"factor": name, "reason": f"no control for {config[name]!r}"})
                continue
            if name in ("secondary_isolated", "pan_layout"):
                continue      # handled after their card is opened
            self.s.click(key)
            applied[name] = config[name]

        # Cards are opened only when the row actually touches them, so a
        # minimal run stays minimal and the screenshots show what was tested.
        wants_secondary = any(config.get(k) for k in TOGGLES if k.startswith("dl_")) \
            or "secondary_isolated" in config
        wants_convert = any(config.get(k) for k in TOGGLES if k.startswith("convert_"))
        wants_panopto = config.get("pan_master") or \
            any(config.get(k) for k in TOGGLES if k.startswith("pan_out_"))

        if wants_secondary:
            self.expand_card("toggle_card2")
            for name in [k for k in TOGGLES if k.startswith("dl_")]:
                if name in config:
                    r = self.set_toggle(TOGGLES[name], bool(config[name]))
                    if r["ok"]:
                        applied[name] = config[name]
                    else:
                        failed.append({"factor": name, **r})
            if "secondary_isolated" in config:
                self.s.click(SEGMENTED["secondary_isolated"][bool(config["secondary_isolated"])])
                applied["secondary_isolated"] = config["secondary_isolated"]

        if wants_convert:
            self.expand_card("toggle_card3")
            for name in [k for k in TOGGLES if k.startswith("convert_")]:
                if name in config:
                    r = self._set_toggle_in_card("toggle_card3", TOGGLES[name],
                                                 bool(config[name]))
                    if r["ok"]:
                        applied[name] = config[name]
                    else:
                        failed.append({"factor": name, **r})

        if wants_panopto:
            self.expand_card("toggle_panopto")
            for name in [k for k in TOGGLES if k.startswith("pan_out_")]:
                if name in config:
                    r = self.set_toggle(TOGGLES[name], bool(config[name]))
                    if r["ok"]:
                        applied[name] = config[name]
                    else:
                        failed.append({"factor": name, **r})
            if "pan_layout" in config:
                self.s.click(SEGMENTED["pan_layout"][config["pan_layout"]])
                applied["pan_layout"] = config["pan_layout"]

        # Read the whole screen back and compare against what was asked for, so
        # a toggle that reverted during a later rerun is caught before the run.
        verified, drift = {}, []
        for name, key in TOGGLES.items():
            if name in config:
                st = self.is_on(key)
                verified[name] = st.get("on")
                if st.get("found") and bool(st.get("on")) != bool(config[name]):
                    drift.append({"factor": name, "wanted": config[name],
                                  "actual": st.get("on")})

        return self._log("configure", applied=applied, failed=failed,
                         verified=verified, drift=drift,
                         ok=not failed and not drift)

    def confirm_and_run(self, name: str, timeout: float = 5400.0,
                        capture_phases: bool = True) -> dict:
        """Start the download and follow it to a terminal screen.

        Captures the scan and download phases on the way through so a mid-run
        UI defect (a stray card, a bar at 100% over a 0/2 counter) is evidenced
        even though the screen only exists for a few seconds.
        """
        shots = []
        # Answered twice, for two different states: one already open (left by a
        # previous row), and - the case that matters - the one THIS click
        # raises. See `_accept_panopto_notice`.
        notice = self._accept_panopto_notice()
        r = self.s.click("action_dl_confirm", settle=False)
        if not r.get("clicked"):
            raise FlowError(f"Confirm and Download not clickable: {r}")
        if not notice.get("shown"):
            notice = self._accept_panopto_notice(wait_s=15.0)

        if capture_phases:
            time.sleep(3.0)
            shots.append(self.s.capture(f"{name}_phase_scan",
                                        ("screen", "wizard", "dashboard")))
            # Stop as soon as the phase is observed OR the run is already
            # terminal - see `download_running_or_done`. The capture is gated on
            # `running`, never on `done`, so a row that finished too fast to have
            # an observable download phase simply has no shot of one.
            got = self.s.wait_for(conditions.get("download_running_or_done"),
                                  timeout=900, poll=2.0, label="download_running")
            if got.get("running"):
                time.sleep(2.0)
                shots.append(self.s.capture(f"{name}_phase_download",
                                            ("screen", "wizard", "dashboard")))

        done = self.s.wait_for(conditions.get("download_terminal"), timeout=timeout,
                               poll=5.0, label="download_terminal")
        self.s.settle(quiet_ms=800, timeout=180)
        shots.append(self.s.capture(f"{name}_complete",
                                    ("screen", "wizard", "completion")))
        return self._log("confirm_and_run", name=name, terminal=done,
                         panopto_notice=notice,
                         captures=[s["name"] for s in shots], ok=done.get("done", False))

    def run(self, name: str, course_ids: list[int], config: dict) -> dict:
        """Whole custom-download flow: select, configure, run, capture.

        The size cap is set after the courses are picked and before the run
        starts. It lives in the global Settings dialog, not on the download
        page, so it needs the sidebar - which means after ``select_courses``
        has loaded the app, and before ``confirm_and_run``, since the Settings
        button is deliberately disabled while a run is active.
        """
        out = {"name": name, "course_ids": course_ids, "config": config}
        out["select"] = self.select_courses(course_ids)
        # Always applied when the row names it, including when it names None:
        # settings persist for the lifetime of the app, so a row that wants no
        # cap has to actively clear the previous row's.
        if "max_file_size" in config:
            out["size_cap"] = self.set_size_cap(config.get("max_file_size"))
        out["open"] = self.open_custom()
        self.s.capture(f"{name}_config_before", ("screen",))
        out["configure"] = self.configure(config)
        out["config_shot"] = self.s.capture(f"{name}_config", ("screen",))
        out["run"] = self.confirm_and_run(name)
        out["trace"] = self.trace
        return out


# ==========================================================================
# sync
# ==========================================================================

class SyncFlow(Flow):

    # The completion screen's own way out, in both its variants.
    _FRONT_PAGE_KEYS = ("page_nav_front_page_sync",
                        "page_nav_front_page_sync_complete")

    def open(self) -> dict:
        """Open the sync page, LEAVING any terminal screen first.

        A lane runs many sync rows through one app, and navigating to
        ``?mode=sync&step=1`` does not by itself clear the previous row's
        finished sync - the step lives in session state, so the app comes back
        up on "Sync Complete! ... your folder already matches Canvas" and the
        Analyze button is not on the page at all. Measured: row two of a
        two-row lane died with a 20-second timeout clicking `btn_analyze_sync`,
        with no capture to say why, because the failure came before the first
        screenshot.

        The way out is the one the screen offers the user - "Go to front page"
        - rather than a reload, so this exercises the same path a person takes
        between two syncs.
        """
        self.s.goto(self.s.app_url("sync", "1"))
        left = None
        if not self.s.probe_key("btn_analyze_sync", "button").get("found"):
            for key in self._FRONT_PAGE_KEYS:
                if self.s.probe_key(key, "button").get("found"):
                    self.s.click(key)
                    left = key
                    break
            self.s.goto(self.s.app_url("sync", "1"))
        return self._log("open_sync", left_terminal_screen=left,
                         analyze_present=self.s.probe_key(
                             "btn_analyze_sync", "button").get("found"),
                         screen=self.s.extract("screen").get("mode"))

    def analyze(self, name: str, quick: bool = False,
                timeout: float = 5400.0) -> dict:
        """Start an analysis and stop at whatever screen the mode leads to.

        Quick Sync skips Review by design, so waiting on the review screen would
        hang forever in that mode - the wait is on "past analysis" instead, and
        which screen actually arrived is reported rather than assumed.
        """
        key = "btn_quick_sync" if quick else "btn_analyze_sync"
        r = self.s.click(key, settle=False)
        if not r.get("clicked"):
            raise FlowError(f"{key} not clickable: {r}")
        # `sync_ui.py` raises the Panopto acceptable-use notice from THIS
        # handler when any pair's stored contract wants recordings, so it can
        # only be answered after the click. Without this the row sits on the
        # dialog and every later wait reports a phase that never started - see
        # `_accept_panopto_notice`.
        notice = self._accept_panopto_notice(wait_s=15.0, until="sync_analyzing")
        time.sleep(2.5)
        self.s.capture(f"{name}_analyzing", ("screen", "wizard", "dashboard"))
        got = self.s.wait_for(conditions.get("sync_past_analysis"), timeout=timeout,
                              poll=3.0, label="sync_past_analysis")
        self.s.settle(quiet_ms=800, timeout=180)
        wiz = self.s.extract("wizard")
        active = next((w["id"] for w in wiz if w["state"] == "active"), "")
        cap = self.s.capture(f"{name}_after_analysis",
                             ("screen", "wizard", "review") if active == "review"
                             else ("screen", "wizard", "dashboard"))
        return self._log("analyze", quick=quick, landed_on=active, wait=got,
                         panopto_notice=notice,
                         capture=cap["name"], ok=got.get("done", False))

    def review_snapshot(self, name: str) -> dict:
        """Expand every category so its rows are in the DOM, then capture.

        A collapsed expander renders no rows at all, so a review captured
        without this step reports every category as empty and every
        classification check silently passes.
        """
        review = self.s.extract("review")
        opened = []
        for course in review.get("courses", []):
            cid = course["course_id"]
            for cat in course.get("categories", {}):
                key = {"new": f"cat_new_{cid}", "updated_clean": f"cat_update_{cid}",
                       "updated_modified": f"cat_updmod_{cid}",
                       "deleted_locally": f"cat_deleted_local_{cid}",
                       "deleted_on_canvas": f"cat_deleted_canvas_{cid}",
                       "ignored": f"cat_ignored_{cid}"}.get(cat)
                if key:
                    self.s.expand(key, True)
                    opened.append(key)
        cap = self.s.capture(name, ("screen", "review", "wizard"))
        return self._log("review_snapshot", expanded=opened, capture=cap["name"],
                         **{k: v for k, v in cap.items() if k != "name"})

    CATEGORY_KEYS = {
        "new": "cat_new", "updated_clean": "cat_update",
        "updated_modified": "cat_updmod", "deleted_locally": "cat_deleted_local",
        "deleted_on_canvas": "cat_deleted_canvas", "ignored": "cat_ignored",
    }

    def select_category(self, category: str, want: bool = True) -> dict:
        """Tick (or untick) every row in one review category.

        Needed because the two categories that matter most are UNCHECKED by
        default - "you've edited these" and "deleted locally" - so the default
        run never exercises the ``_NewVersion`` path or a restore at all. The
        rows are addressed by the widget keys the screen already assigns, read
        back out of the review extraction rather than guessed, so a category
        that renders no rows is reported as such instead of silently passing.
        """
        review = self.s.extract("review")
        touched, failed = [], []
        for course in review.get("courses", []):
            blob = (course.get("categories") or {}).get(category) or {}
            for row in blob.get("rows", []):
                key = row.get("rowKey")
                if not key:
                    continue          # informational row, no control by design
                r = self.s.set_checkbox(key, want)
                if r.get("verified", r.get("set")):
                    touched.append(key)
                else:
                    failed.append({"key": key, **r})
        return self._log("select_category", category=category, want=want,
                         touched=len(touched), failed=failed,
                         ok=bool(touched) and not failed)

    def wait_terminal(self, name: str, timeout: float = 5400.0) -> dict:
        """Follow a sync that is already running to its terminal screen.

        Quick Sync has NO review screen and NO confirmation dialog - that is
        the whole point of it - so there is nothing to click and the run is
        already under way when ``analyze`` returns. Calling ``confirm`` on one
        looked for ``btn_sync_selected`` and failed with "no host for key",
        which reads like the review screen lost its button rather than like a
        mode that never had one.
        """
        done = self.s.wait_for(conditions.get("sync_terminal"), timeout=timeout,
                               poll=5.0, label="sync_terminal")
        self.s.settle(quiet_ms=800, timeout=180)
        cap = self.s.capture(f"{name}_complete",
                             ("screen", "wizard", "completion"))
        return self._log("wait_terminal", terminal=done, capture=cap["name"],
                         ok=done.get("done", False))

    def has_syncable_selection(self) -> bool:
        """Is the review screen's primary action actually available?

        A run where nothing changed reaches the review screen with no ticked
        rows, and the app disables "Sync Selected" - correctly, there is
        nothing to do. The flow used to click it regardless and reported
        either "no host for key" or a 20-second Playwright timeout against
        ``<button disabled>``, both of which read like the app was broken.
        Asked of the DOM rather than inferred from the seed plan, because the
        screen is the thing that decides.
        """
        info = self.s.probe_key("btn_sync_selected", "button")
        return bool(info.get("found")) and not info.get("disabled")

    def capture_screen(self, name: str) -> str:
        return self.s.capture(name, ("screen", "wizard", "review"))["name"]

    def confirm(self, name: str, timeout: float = 5400.0) -> dict:
        """Accept the review, clear the confirmation dialog, and follow the sync.

        Two distinct controls, verified against the source: the review screen's
        primary action is wrapped in ``st.container(key="btn_sync_selected")``,
        and it opens the Confirm Sync DIALOG whose start button is
        ``page_nav_start_sync`` ("Yes, Start Sync"). Clicking only the first
        leaves the dialog open and the sync never starts - which then looks
        exactly like a hung analysis.
        """
        r = self.s.click("btn_sync_selected", settle=False)
        if not r.get("clicked"):
            raise FlowError(f"Review screen's sync action not clickable: {r}")
        # `ui/sync_review.py` raises the notice from this handler too, and it
        # sits IN FRONT OF the Confirm Sync dialog below - so an unanswered one
        # reads as "the confirmation dialog never opened".
        notice = self._accept_panopto_notice(wait_s=15.0, until=None,
                                             stop_key="page_nav_start_sync")
        time.sleep(1.8)

        dialog = self.s.wait_for(conditions.get("dialog_open"), timeout=45,
                                 poll=1.0, label="confirm_dialog")
        if dialog.get("done"):
            self.s.capture(f"{name}_confirm_dialog", ("screen",))
            start = self.s.click("page_nav_start_sync", settle=False)
            if not start.get("clicked"):
                raise FlowError(f"Confirm Sync dialog open but 'Yes, Start Sync' "
                                f"not clickable: {start}")
        done = self.s.wait_for(conditions.get("sync_terminal"), timeout=timeout,
                               poll=5.0, label="sync_terminal")
        self.s.settle(quiet_ms=800, timeout=180)
        cap = self.s.capture(f"{name}_complete", ("screen", "wizard", "completion"))
        return self._log("confirm_sync", terminal=done, capture=cap["name"],
                         ok=done.get("done", False))


# ==========================================================================
# today
# ==========================================================================

class TodayFlow(Flow):

    def open(self) -> dict:
        self.s.goto(self.s.app_url("today", "1"))
        return self._log("open_today", capture=self.s.capture("today_open",
                                                              ("screen", "today"))["name"])

    def quick_sync(self, name: str, timeout: float = 3600.0) -> dict:
        # The key is verified against the app, not guessed: the three names
        # tried here previously were all wrong, and the flow reported "no Quick
        # Sync control" on a page that plainly had one.
        r = self.s.click("today_sync_now_btn", settle=False)
        if not r.get("clicked"):
            raise FlowError(f"'Quick Sync now' (today_sync_now_btn) not clickable: {r}")
        done = self.s.wait_for(conditions.get("today_sync_done"), timeout=timeout,
                               poll=4.0, label="today_sync_done")
        self.s.settle(quiet_ms=800, timeout=120)
        cap = self.s.capture(name, ("screen", "today"))
        return self._log("today_quick_sync", terminal=done, capture=cap["name"],
                         ok=done.get("done", False))


def save_trace(rp, name: str, data: dict) -> str:
    p = Path(rp.ui) / f"{name}_flow.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                 encoding="utf-8")
    return str(p)
