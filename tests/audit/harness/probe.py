"""JavaScript probes injected into the running app (oracle O1).

These live here rather than being composed ad hoc so that every audit run reads
the screen the SAME way. A probe that is rewritten per invocation produces
findings that cannot be compared between runs, which defeats the point of a
repeatable suite.

Three rules the probes follow, each learned from this project's own CLAUDE.md:

* Read widgets by their ``st-key-<key>`` class. Streamlit lowercases keys when
  it builds the class, so every lookup lowercases too.
* Never assume a testid that 1.51 removed. ``stVerticalBlockBorderWrapper``,
  the hyphenated ``element-container``, ``stToggle``, ``stDialogScrollableBody``
  and ``stModal`` all resolve to zero nodes; the probes use the live forms.
* A style-only element container is 0-height, so "the page has content" means an
  ``stElementContainer`` TALLER than a few pixels - otherwise a page carrying
  nothing but CSS injections reads as loaded.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# console + error collector
#
# Re-injected after every navigation. Streamlit reruns over the websocket
# without reloading the document, so one injection survives an entire flow -
# but a genuine navigation resets it, and a silently-absent collector would
# report "0 console errors" for a screen it never watched.
# --------------------------------------------------------------------------
INSTALL_COLLECTOR = r"""
() => {
  if (window.__cdAudit && window.__cdAudit.installed) return { reused: true };
  const store = { installed: true, console: [], errors: [], startedAt: Date.now() };
  const wrap = (level) => {
    const orig = console[level].bind(console);
    console[level] = (...args) => {
      try {
        store.console.push({
          level, t: Date.now(),
          text: args.map(a => {
            try { return typeof a === 'string' ? a : JSON.stringify(a); }
            catch (e) { return String(a); }
          }).join(' ').slice(0, 600)
        });
      } catch (e) { /* never let instrumentation break the page */ }
      return orig(...args);
    };
  };
  ['error', 'warn'].forEach(wrap);
  window.addEventListener('error', (e) => {
    store.errors.push({ t: Date.now(), text: String(e.message || e).slice(0, 600),
                        src: (e.filename || '') + ':' + (e.lineno || '') });
  });
  window.addEventListener('unhandledrejection', (e) => {
    store.errors.push({ t: Date.now(), text: 'unhandledrejection: ' +
                        String((e.reason && e.reason.message) || e.reason).slice(0, 600) });
  });
  window.__cdAudit = store;
  return { reused: false };
}
"""

DRAIN_COLLECTOR = r"""
() => {
  const s = window.__cdAudit;
  if (!s) return { console: [], errors: [], missing: true };
  const out = { console: s.console.slice(), errors: s.errors.slice(), missing: false };
  s.console.length = 0; s.errors.length = 0;
  return out;
}
"""

# --------------------------------------------------------------------------
# readiness / settle
# --------------------------------------------------------------------------
IS_READY = r"""
() => {
  const main = document.querySelector('[data-testid="stMain"]');
  if (!main) return { ready: false, why: 'no stMain' };
  // A style-only injection renders a 0-height container; requiring real height
  // stops "the stylesheets loaded" being mistaken for "the page rendered".
  const solid = [...main.querySelectorAll('[data-testid="stElementContainer"]')]
    .filter(e => e.getBoundingClientRect().height > 8).length;
  const running = !!document.querySelector('[data-testid="stStatusWidget"]');
  const stale = main.querySelectorAll('[data-stale="true"]').length;

  // The startup splash (#cd-boot, injected into index.html by
  // scripts/patch_streamlit_boot.py) covers the whole viewport until the app
  // has really settled. Streamlit populates the DOM UNDERNEATH it, so element
  // count alone reports "ready" while the user is still looking at a spinner -
  // and a click then lands on a page whose controls have not mounted. Waiting
  // for the overlay to leave is both the correct readiness signal and a free
  // check that the app's own startup contract still works.
  const boot = document.getElementById('cd-boot');
  const bootVisible = !!boot && getComputedStyle(boot).display !== 'none'
                      && parseFloat(getComputedStyle(boot).opacity || '1') > 0.01;

  return { ready: solid > 2 && !running && !bootVisible,
           solid, running, stale, bootVisible,
           prerender: !!window.prerenderReady };
}
"""

# DOM-quiet detector. Streamlit streams a long screen in over several frames, so
# "no status widget" alone can catch it mid-stream; requiring the element count
# and body text length to hold still for a beat is what makes an extraction
# reproducible rather than a race.
SETTLE = r"""
(quietMs) => {
  return new Promise((resolve) => {
    const main = document.querySelector('[data-testid="stMain"]');
    if (!main) { resolve({ settled: false, why: 'no stMain' }); return; }
    let lastSig = '';
    let stableSince = 0;
    const started = Date.now();
    const tick = () => {
      const running = !!document.querySelector('[data-testid="stStatusWidget"]');
      const n = main.querySelectorAll('[data-testid="stElementContainer"]').length;
      const len = (main.innerText || '').length;
      const sig = running + '|' + n + '|' + len;
      if (sig === lastSig) {
        if (!stableSince) stableSince = Date.now();
        if (!running && Date.now() - stableSince >= quietMs) {
          resolve({ settled: true, ms: Date.now() - started, n, len }); return;
        }
      } else { lastSig = sig; stableSince = 0; }
      if (Date.now() - started > 240000) {
        resolve({ settled: false, why: 'timeout', running, n, len }); return;
      }
      setTimeout(tick, 120);
    };
    tick();
  });
}
"""

# --------------------------------------------------------------------------
# generic screen extraction
# --------------------------------------------------------------------------
SCREEN = r"""
() => {
  const keyOf = (el) => {
    const host = el.closest('[class*="st-key-"]');
    if (!host) return '';
    const m = String(host.className).match(/st-key-([A-Za-z0-9_\-]+)/);
    return m ? m[1] : '';
  };
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  const main = document.querySelector('[data-testid="stMain"]');
  const dialog = document.querySelector('[data-testid="stDialog"]');
  const scope = dialog || main || document.body;

  const buttons = [...scope.querySelectorAll('button')].filter(vis).map(b => ({
    key: keyOf(b),
    text: (b.innerText || '').trim().slice(0, 80),
    disabled: b.disabled === true || b.getAttribute('aria-disabled') === 'true',
    // The two JS gates in this app grey a genuinely-enabled button, so a probe
    // that reads only `disabled` would call an unavailable action available.
    gated: getComputedStyle(b).pointerEvents === 'none',
    kind: b.getAttribute('kind') || ''
  }));

  const checks = [...scope.querySelectorAll('[data-testid="stCheckbox"] input, ' +
                                            '[data-testid="stCheckbox"] [role="checkbox"]')]
    .filter(vis).map(c => ({
      key: keyOf(c),
      checked: c.getAttribute('aria-checked') === 'true' || c.checked === true,
      label: (c.closest('label')?.innerText || '').trim().slice(0, 90)
    }));

  const inputs = [...scope.querySelectorAll('input[type="text"], textarea')]
    .filter(vis).map(i => ({ key: keyOf(i), value: (i.value || '').slice(0, 300) }));

  const expanders = [...scope.querySelectorAll('[data-testid="stExpander"] details')]
    .filter(vis).map(d => ({
      key: keyOf(d),
      open: d.hasAttribute('open'),
      label: (d.querySelector('summary')?.innerText || '').trim().slice(0, 160)
    }));

  const alerts = [...scope.querySelectorAll('[data-testid="stAlert"], [role="alert"]')]
    .filter(vis).map(a => ({ text: (a.innerText || '').trim().slice(0, 400) }));

  const exceptions = [...scope.querySelectorAll('[data-testid="stException"]')]
    .map(e => ({ text: (e.innerText || '').trim().slice(0, 2000) }));

  return {
    url: location.href,
    mode: new URLSearchParams(location.search).get('mode') || '',
    step: new URLSearchParams(location.search).get('step') || '',
    quick: new URLSearchParams(location.search).get('quick') || '',
    dialogOpen: !!dialog,
    dialogTitle: dialog ? (dialog.innerText || '').trim().split('\n')[0].slice(0, 120) : '',
    headings: [...scope.querySelectorAll('h1,h2,h3')].filter(vis)
                .map(h => (h.innerText || '').trim()).slice(0, 20),
    buttons, checks, inputs, expanders, alerts, exceptions,
    text: (scope.innerText || '').replace(/\n{3,}/g, '\n\n').slice(0, 20000),
    textLen: (scope.innerText || '').length
  };
}
"""

# The wizard step tracker is the app's own claim about where the user is. It
# disagreeing with the URL or with the screen's content is a finding in itself -
# the sync flow once advertised "Review Changes" during the analysis phase.
WIZARD = r"""
() => {
  const out = [];
  document.querySelectorAll('[class*="st-key-cd_wiz_"]').forEach(el => {
    const m = String(el.className).match(/st-key-cd_wiz_([a-z]+)_(\d+)_([a-z_]+)_st_([a-z]+)_/);
    if (!m) return;
    out.push({ flow: m[1], index: Number(m[2]), id: m[3], state: m[4],
               label: (el.innerText || '').trim().slice(0, 60) });
  });
  return out.sort((a, b) => a.index - b.index);
}
"""

# --------------------------------------------------------------------------
# run dashboard (download + sync progress)
# --------------------------------------------------------------------------
DASHBOARD = r"""
() => {
  const card = document.querySelector('[class*="st-key-progress_dashboard"]');
  const pick = (sel, root) => (root || document).querySelector(sel);
  const bar = pick('.cd-progress-fill') || pick('[class*="progress-fill"]');
  const metricEls = [...document.querySelectorAll('.cd-metrics-row .cd-metric, ' +
                                                  '[class*="cd-metric"]')];
  const metrics = {};
  metricEls.forEach(m => {
    const label = (m.querySelector('[class*="label"]')?.innerText || '').trim();
    const value = (m.querySelector('[class*="value"]')?.innerText || m.innerText || '').trim();
    if (label) metrics[label.toLowerCase()] = value.replace(label, '').trim();
  });
  const logEl = pick('[class*="terminal"], [class*="cd-log"]');
  return {
    present: !!card,
    header: (card?.querySelector('h1,h2,h3,[class*="header"]')?.innerText || '').trim(),
    barWidth: bar ? bar.style.width : '',
    metrics,
    rawMetricsText: (document.querySelector('[class*="cd-metrics-row"]')?.innerText || '')
                      .replace(/\n+/g, ' | ').slice(0, 500),
    activeFile: (document.querySelector('[class*="active-file"]')?.innerText || '').trim().slice(0, 300),
    logTail: logEl ? (logEl.innerText || '').split('\n').slice(-25).join('\n') : '',
    cardText: card ? (card.innerText || '').slice(0, 4000) : ''
  };
}
"""

# --------------------------------------------------------------------------
# sync review screen - the single most important extraction in the suite
#
# It is what the user is told about their files, and this project's own
# contract calls it "the source of truth for any user". Every row is captured
# with its category, its course, its checked state and its displayed path so
# that a file appearing in the wrong bucket is detectable mechanically rather
# than by eyeballing a screenshot.
# --------------------------------------------------------------------------
SYNC_REVIEW = r"""
() => {
  // Category container keys, verified against the running review screen.
  const CATS = {
    cat_new_: 'new', cat_update_: 'updated_clean', cat_updmod_: 'updated_modified',
    cat_deleted_local_: 'deleted_locally', cat_deleted_canvas_: 'deleted_on_canvas',
    cat_ignored_: 'ignored'
  };

  // A course id can be negative (synthetic secondary entities), so the id
  // pattern is [-]?\d+, not \d+. Written with SINGLE backslashes: this file is
  // a Python raw string, so what appears here is exactly what JS parses, and
  // doubling them produced a regex matching a literal backslash - which is why
  // this probe silently returned zero categories on a screen that had six.
  const idRe = (prefix) => new RegExp('st-key-' + prefix + '(-?\\d+)');

  const stem = (s) => String(s || '').replace(/\.[A-Za-z0-9]{1,8}$/, '').trim();

  // Rows come in three shapes on this screen and only the first has a checkbox:
  //   a) st-key-sync_row_*      new / updated / edited / deleted-locally
  //   b) st-key-ign_restore_row_*   the Ignored bucket
  //   c) bare markdown divs     deleted-on-Canvas (info only, no control)
  // A probe that knows only (a) reports the other two as empty categories,
  // which reads as "the app lost them" rather than "the probe cannot see them".
  const readRow = (r, key) => {
    const cb = r.querySelector('[data-testid="stCheckbox"] input, ' +
                               '[data-testid="stCheckbox"] [role="checkbox"]');
    const text = (r.innerText || '').replace(/\s*\n+\s*/g, ' ').trim();
    // The filename is rendered as STEM plus a separate <del>UPPERCASE-EXT</del>
    // chip and a <code>size</code> chip, so innerText never contains
    // "name.ext". Matching has to happen on the stem.
    const del = r.querySelector('del');
    const code = r.querySelector('code');
    let name = text;
    for (const chip of [del, code]) {
      if (chip && chip.innerText) name = name.replace(chip.innerText, '');
    }
    // The lookalike warning is rendered INSIDE the row, after the tags, so it
    // lands in innerText and became part of the filename: "html terninger ⚠️".
    // Every name-keyed comparison against the seed plan or the manifest then
    // misses on exactly the rows the warning is about - a fabricated finding
    // caused by the fix for a real one. Lift it out as its own field, which is
    // also what lets a check assert the warning appears on the RIGHT rows.
    const lookalike = /⚠/.test(name);
    name = name.replace(/[⚠️]/g, '');
    name = name.replace(/\s{2,}/g, ' ').trim();
    return {
      rowKey: key || '',
      checked: cb ? (cb.getAttribute('aria-checked') === 'true' || cb.checked === true) : null,
      name, stem: stem(name),
      ext: del ? (del.innerText || '').trim().toLowerCase() : '',
      lookalike,
      text: text.slice(0, 400)
    };
  };

  const courses = {};
  document.querySelectorAll('[class*="st-key-cat_"]').forEach(el => {
    const cls = String(el.className);
    let cat = null, cid = null;
    for (const [prefix, name] of Object.entries(CATS)) {
      const m = cls.match(idRe(prefix));
      if (m) { cat = name; cid = m[1]; break; }
    }
    if (!cat) return;

    const details = el.querySelector('details');
    const summary = details?.querySelector('summary');
    // The per-category count is drawn as a ::after on the summary paragraph, so
    // it is absent from innerText - read it off the computed style.
    let badge = '';
    const p = summary?.querySelector('p');
    if (p) {
      const c = getComputedStyle(p, '::after').content;
      if (c && c !== 'none') badge = c.replace(/^["']|["']$/g, '');
    }

    let rows = [];
    const keyed = [...el.querySelectorAll(
      '[class*="st-key-sync_row_"], [class*="st-key-ign_restore_row_"]')];
    if (keyed.length) {
      rows = keyed.map(r => {
        const m = String(r.className)
          .match(/st-key-((?:sync_row|ign_restore_row)_[A-Za-z0-9_\-]+)/);
        return readRow(r, m ? m[1] : '');
      });
    } else if (details) {
      // Shape (c): info-only rows. Take the markdown blocks inside the
      // expander, minus the caption, minus anything with no text.
      rows = [...details.querySelectorAll('[data-testid="stMarkdownContainer"] > div')]
        .filter(d => !d.closest('[data-testid="stCaptionContainer"]')
                     && (d.innerText || '').trim().length > 0
                     && !d.querySelector('[data-testid="stMarkdownContainer"]'))
        .map(d => readRow(d, ''));
    }

    courses[cid] = courses[cid] || { course_id: cid, categories: {} };
    courses[cid].categories[cat] = {
      label: (summary?.innerText || '').trim().slice(0, 120),
      badge, open: !!details?.hasAttribute('open'),
      rowCount: rows.length, rows
    };
  });

  // Top-of-page summary cards aggregate ACROSS courses and are computed by
  // different code than the per-course lists, so a mismatch between the two is
  // itself a finding. Both are captured.
  const summary = [...document.querySelectorAll('[class*="cat-summary"], ' +
                                                '[class*="summary-card"]')]
    .map(c => (c.innerText || '').replace(/\n+/g, ' ').trim().slice(0, 200));

  return {
    courses: Object.values(courses),
    summaryCards: summary,
    // Diagnostics so an empty extraction can never again be mistaken for an
    // empty screen: if these are non-zero and `courses` is empty, the probe is
    // broken, not the app.
    seen: {
      categoryContainers: document.querySelectorAll('[class*="st-key-cat_"]').length,
      syncRows: document.querySelectorAll('[class*="st-key-sync_row_"]').length,
      ignoredRows: document.querySelectorAll('[class*="st-key-ign_restore_row_"]').length,
      expanders: document.querySelectorAll('[data-testid="stExpander"]').length
    },
    pageText: (document.querySelector('[data-testid="stMain"]')?.innerText || '')
                .slice(0, 30000)
  };
}
"""

# --------------------------------------------------------------------------
# completion screens + today page
# --------------------------------------------------------------------------
COMPLETION = r"""
() => {
  const main = document.querySelector('[data-testid="stMain"]');
  const folderCards = [...document.querySelectorAll('[class*="st-key-dl_fc_"], ' +
                                                    '[class*="st-key-sync_complete_fc_"]')]
    .map(c => ({
      key: (String(c.className).match(/st-key-([A-Za-z0-9_\-]+)/) || ['', ''])[1],
      text: (c.innerText || '').replace(/\n+/g, ' | ').trim().slice(0, 400)
    }));
  return {
    folderCards,
    // A completion card that has inherited the run dashboard's children renders
    // the metrics row and terminal log INSIDE it - a bug this project has hit.
    dashboardInsideCard: !!document.querySelector(
      '[class*="st-key-dl_fc_"] [class*="cd-metrics-row"], ' +
      '[class*="st-key-sync_complete_fc_"] [class*="cd-metrics-row"]'),
    strayDashboard: !!document.querySelector('[class*="st-key-progress_dashboard"]'),
    text: (main?.innerText || '').slice(0, 20000)
  };
}
"""

TODAY = r"""
() => {
  const chips = [...document.querySelectorAll('[class*="st-key-today_chip_"]')].map(c => ({
    key: (String(c.className).match(/st-key-(today_chip_[A-Za-z0-9_\-]+)/) || ['', ''])[1],
    missing: /today_chip_missing_/.test(String(c.className)),
    text: (c.innerText || '').trim().slice(0, 160)
  }));
  const pairCards = [...document.querySelectorAll('[class*="st-key-today_pair_card_"]')].map(c => ({
    key: (String(c.className).match(/st-key-(today_pair_card_[A-Za-z0-9_\-]+)/) || ['', ''])[1],
    missing: /today_pair_card_missing_/.test(String(c.className)),
    text: (c.innerText || '').replace(/\n+/g, ' | ').trim().slice(0, 300)
  }));
  const offlist = document.querySelector('.today-files-offlist');
  return {
    chips, pairCards,
    offlist: offlist ? (offlist.innerText || '').trim().slice(0, 400) : '',
    hasOfflist: !!offlist,
    text: (document.querySelector('[data-testid="stMain"]')?.innerText || '').slice(0, 20000)
  };
}
"""

# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------
FIND_BY_KEY = r"""
(args) => {
  const { key, role } = args;
  const k = String(key).toLowerCase();
  const hosts = [...document.querySelectorAll('[class*="st-key-' + k + '"]')];
  if (!hosts.length) return { found: false, reason: 'no host for key ' + k };
  for (const host of hosts) {
    // A Streamlit checkbox/toggle keeps its real <input> visually hidden at
    // 0x0 with opacity 0; the thing a user actually clicks is the <label>. So
    // STATE is read from the input and the CLICK TARGET is the label, and a
    // zero-sized input must not be taken as "no control here".
    //
    // The label is addressed as a DIRECT child: when help= is set, Streamlit
    // nests a SECOND label (wrapping the tooltip icon) inside stWidgetLabel,
    // and a descendant selector would sometimes return the tooltip instead of
    // the row.
    let state = null, target = null;
    if (role === 'checkbox') {
      state = host.querySelector('[data-testid="stCheckbox"] input[type="checkbox"], ' +
                                 '[data-testid="stCheckbox"] [role="checkbox"]');
      target = host.querySelector('[data-testid="stCheckbox"] > label') ||
               host.querySelector('label') || state;
    } else if (role === 'input') {
      state = target = host.querySelector('input:not([type="checkbox"]), textarea');
    } else {
      state = target = host.matches('button') ? host : host.querySelector('button');
    }
    if (!state || !target) continue;
    const r = target.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    return {
      found: true,
      disabled: state.disabled === true || state.getAttribute('aria-disabled') === 'true',
      gated: getComputedStyle(target).pointerEvents === 'none',
      checked: state.getAttribute('aria-checked') === 'true' || state.checked === true,
      text: (target.innerText || target.value || '').trim().slice(0, 120),
      box: { x: r.x, y: r.y, w: r.width, h: r.height }
    };
  }
  return { found: false, reason: 'host present but no interactive element' };
}
"""
