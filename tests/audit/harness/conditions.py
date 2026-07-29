"""Named wait conditions - "when is this phase over?"

Each is a JS expression returning ``{done: bool, ...context}``. The context is
kept because a wait that times out is itself a finding, and the agent needs to
know WHAT the screen was showing when it gave up, not just that it did.

Phase is read off the **step tracker**, not off text. The tracker encodes the
app's own claim about where the user is directly in each button's key
(``cd_wiz_<flow>_<idx>_<id>_st_<state>_<sep>``), which makes it an exact,
translation-proof, layout-proof signal. It is also the right thing to assert
against: this project has shipped a tracker that said "Review Changes" while
the analysis was still running, so a disagreement between the tracker and the
screen's actual content is a real defect class, and reading the tracker is how
the audit notices.

One asymmetry worth knowing: a CANCELLED download leaves the tracker on step 4
(``download``) and simply stops rendering a heading, so "terminal" cannot mean
"tracker says complete". The terminal conditions below therefore also accept
"the run dashboard is gone and a leave-the-screen button is present".
"""

from __future__ import annotations

# Shared JS prelude: the current wizard state, plus a couple of structural facts
# every condition wants. Kept in one string so all conditions agree about what
# "active step" means.
_PRELUDE = r"""
  const steps = [];
  document.querySelectorAll('[class*="st-key-cd_wiz_"]').forEach(el => {
    const m = String(el.className).match(/st-key-cd_wiz_([a-z]+)_(\d+)_([a-z_]+)_st_([a-z]+)_/);
    if (m) steps.push({ flow: m[1], idx: +m[2], id: m[3], state: m[4] });
  });
  const active = steps.find(s => s.state === 'active') || null;
  const dash = !!document.querySelector('[class*="st-key-progress_dashboard"]');
  const main = document.querySelector('[data-testid="stMain"]');
  const txt = (main ? main.innerText : '');
  const btnKeys = [...document.querySelectorAll('button')].map(b => {
    const h = b.closest('[class*="st-key-"]');
    const m = h && String(h.className).match(/st-key-([A-Za-z0-9_\-]+)/);
    return m ? m[1] : '';
  }).filter(Boolean);
  const hasKey = (p) => btnKeys.some(k => k.indexOf(p) === 0);
  const anyKey = (p) => btnKeys.some(k => k.indexOf(p) >= 0);
  const exceptions = document.querySelectorAll('[data-testid="stException"]').length;
  const ctx = { active, dash, exceptions,
                head: (document.querySelector('.step-header')||{}).innerText || '',
                tail: txt.slice(-400) };
"""


def _c(body: str) -> str:
    return "() => {\n" + _PRELUDE + body + "\n}"


CONDITIONS: dict[str, str] = {

    # -- generic ---------------------------------------------------------
    "idle": _c("""
      return { done: !dash && !!active, ...ctx };
    """),

    "any_exception": _c("""
      return { done: exceptions > 0, ...ctx };
    """),

    "dialog_open": _c("""
      const d = document.querySelector('[data-testid="stDialog"]');
      return { done: !!d, title: d ? (d.innerText||'').split('\\n')[0] : '', ...ctx };
    """),

    "dialog_closed": _c("""
      return { done: !document.querySelector('[data-testid="stDialog"]'), ...ctx };
    """),

    # -- download flow ---------------------------------------------------
    # Scanning and downloading share ONE dashboard card by design, so the
    # tracker is the only way to tell them apart.
    "download_scanning": _c("""
      return { done: !!active && active.flow === 'download' && active.id === 'analyze', ...ctx };
    """),

    "download_running": _c("""
      return { done: !!active && active.flow === 'download' && active.id === 'download', ...ctx };
    """),

    # Terminal = the app has stopped working, whether it succeeded, was
    # cancelled, or fell into the isolated-retry tail. Accepting all three is
    # deliberate: a run that ends in an unexpected way must still unblock the
    # audit so the state can be inspected and reported, not hang for an hour.
    "download_terminal": _c("""
      const complete = !!active && active.flow === 'download' && active.id === 'complete';
      const stopped = !dash && (hasKey('dl_fc_') || anyKey('front_page') ||
                                anyKey('go_to_front') || anyKey('start_new'));
      return { done: complete || stopped, complete, stopped, ...ctx };
    """),

    "download_complete": _c("""
      return { done: !!active && active.flow === 'download' && active.id === 'complete', ...ctx };
    """),

    # Panopto is its own phase inside the download flow and can run for a long
    # time; it keeps the tracker on 'download', so it needs its own signal.
    "panopto_phase": _c("""
      return { done: /Panopto Recordings/i.test(ctx.head), ...ctx };
    """),

    # -- sync flow -------------------------------------------------------
    "sync_analyzing": _c("""
      return { done: !!active && active.flow === 'sync' && active.id === 'analyze', ...ctx };
    """),

    # The review screen is reached only by the full Analyze/Review/Sync path;
    # Quick Sync skips it, so waiting on this in Quick Sync would hang forever.
    # 'sync_past_analysis' below is the mode-agnostic wait.
    "sync_review": _c("""
      const cats = document.querySelectorAll('[class*="st-key-cat_"]').length;
      const onReview = !!active && active.flow === 'sync' && active.id === 'review';
      return { done: onReview, categories: cats, ...ctx };
    """),

    # PAST analysis means standing on a step that comes AFTER it - not merely
    # "not on analyze". The negative form was true before the run had even
    # started: a click leaves the wizard on `select` for a moment, so the wait
    # returned immediately, the flow reported `landed_on: 'analyze'`, and the
    # caller went looking for a review screen while the app was still saying
    # "Fetching files from Canvas... TIME REMAINING ~00:04". Measured on sync
    # row s026, which failed in 13 seconds against a 5,400-second timeout - the
    # give-away that it was never waiting at all.
    #
    # Naming the steps also makes the wait mode-agnostic for the right reason:
    # Quick Sync goes select -> analyze -> sync -> complete and never shows
    # review, so any of the three is a legitimate arrival.
    "sync_past_analysis": _c("""
      const past = ['review', 'sync', 'complete'];
      return { done: !!active && active.flow === 'sync' &&
                     past.includes(active.id), ...ctx };
    """),

    "sync_running": _c("""
      return { done: !!active && active.flow === 'sync' && active.id === 'sync', ...ctx };
    """),

    "sync_terminal": _c("""
      const complete = !!active && active.flow === 'sync' && active.id === 'complete';
      const stopped = !dash && (hasKey('sync_complete_fc_') || anyKey('front_page') ||
                                anyKey('go_to_front'));
      return { done: complete || stopped, complete, stopped, ...ctx };
    """),

    # -- today -----------------------------------------------------------
    # The Today page runs a sync in-page, so "finished" is the disappearance of
    # the run dashboard plus the appearance of the dismissible notice card.
    "today_sync_done": _c("""
      const notice = !!document.querySelector('[class*="today_notice"], .today-sync-notice');
      return { done: !dash && (notice || /Today.s files/i.test(txt)), notice, ...ctx };
    """),

    # -- post-processing / model download --------------------------------
    "post_processing_done": _c("""
      return { done: !/Post-?Processing|Converting/i.test(txt), ...ctx };
    """),

    "model_download_done": _c("""
      const busy = /Downloading|Extracting|%/.test(
        (document.querySelector('[class*="st-key-pan_model_"]')||{}).innerText || '');
      return { done: !busy, ...ctx };
    """),
}


def get(name: str) -> str | None:
    return CONDITIONS.get(name)


def names() -> list[str]:
    return sorted(CONDITIONS)
