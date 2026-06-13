/* ============================================================
   Canvas Downloader - macOS Setup Wizard
   Progressive, version-aware setup assistant.
   Mounts into  <div id="mac-wizard" data-guide-href="..."></div>
   Optional data attributes on the mount:
     data-guide-href   URL for the "full written guide" link on the Done screen
     data-guide-label  Label for that link (default: "See the full written guide")
   ============================================================ */
(function () {
  'use strict';

  var mount = document.getElementById('mac-wizard');
  if (!mount) return;

  var VIDEO_INSTALL = 'assets/mac_inst_dmgToApplications.mp4';
  var YT_GATEKEEPER = '0_NuZndZvi8';   // full Sequoia open-flow walkthrough
  var YT_TOKEN      = 'VadvcIvrrhU';   // how to create a Canvas API token

  var GUIDE_HREF  = mount.getAttribute('data-guide-href') || '';
  var GUIDE_LABEL = mount.getAttribute('data-guide-label') || 'See the full written guide';

  // Ordered, progress-bearing steps. 'done' is the celebration screen (not counted).
  var STEPS = ['install', 'open', 'notifications', 'login', 'permissions'];

  var state = {
    version: null,   // 'new' (15/26) | 'mid' (13/14) | 'old' (11/12)
    screen: 'intro'  // 'intro' | <STEPS> | 'done'
  };

  // ── HTML escape ──────────────────────────────────────────
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  // ── SVG icon system ──────────────────────────────────────
  // All icons: 24×24 viewBox, stroke-based (Feather/Heroicons style)
  function svgWrap(inner, size) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + (size || 20) +
      '" height="' + (size || 20) +
      '" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
      ' stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' +
      inner + '</svg>';
  }

  var ICO = {
    monitor: function (s) {
      return svgWrap(
        '<path fill="currentColor" stroke="none" d="M12.152 6.896c-.149 0-2.662-1.01-4.908-1.01-2.222 0-4.269 1.25-5.38 3.197-2.25 3.924-.575 9.722 1.62 12.89 1.077 1.558 2.33 3.3 3.985 3.24 1.597-.06 2.195-1.037 4.122-1.037 1.928 0 2.464 1.037 4.158 1.006 1.758-.03 2.825-1.573 3.882-3.116 1.221-1.782 1.724-3.513 1.75-3.605-.037-.015-3.376-1.294-3.411-5.14-.035-3.235 2.64-4.802 2.76-4.881-1.523-2.226-3.874-2.527-4.707-2.607-1.464-.138-3.085 1.063-4.134 1.063zM15.485 3.525c.842-1.026 1.41-2.454 1.255-3.875-1.213.05-2.704.81-3.568 1.826-.77.886-1.455 2.355-1.272 3.743 1.353.106 2.744-.666 3.585-1.694z"/>', s);
    },
    shield: function (s) {
      return svgWrap('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>', s);
    },
    bell: function (s) {
      return svgWrap(
        '<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/>' +
        '<path d="M13.73 21a2 2 0 01-3.46 0"/>', s);
    },
    lock: function (s) {
      return svgWrap(
        '<rect x="3" y="11" width="18" height="11" rx="2"/>' +
        '<path d="M7 11V7a5 5 0 0110 0v4"/>', s);
    },
    bulb: function (s) {
      return svgWrap(
        '<line x1="9" y1="21" x2="15" y2="21"/>' +
        '<path d="M12 3a6 6 0 016 6c0 3.5-2 5.5-3 7H9c-1-1.5-3-3.5-3-7a6 6 0 016-6z"/>', s);
    },
    clock: function (s) {
      return svgWrap(
        '<circle cx="12" cy="12" r="10"/>' +
        '<polyline points="12 6 12 12 16 14"/>', s);
    },
    folder: function (s) {
      return svgWrap('<path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>', s);
    },
    terminal: function (s) {
      return svgWrap(
        '<polyline points="4 17 10 11 4 5"/>' +
        '<line x1="12" y1="19" x2="20" y2="19"/>', s);
    },
    grid: function (s) {
      return svgWrap(
        '<rect x="3" y="3" width="7" height="7"/>' +
        '<rect x="14" y="3" width="7" height="7"/>' +
        '<rect x="3" y="14" width="7" height="7"/>' +
        '<rect x="14" y="14" width="7" height="7"/>', s);
    },
    layers: function (s) {
      return svgWrap(
        '<polygon points="12 2 2 7 12 12 22 7 12 2"/>' +
        '<polyline points="2 17 12 22 22 17"/>' +
        '<polyline points="2 12 12 17 22 12"/>', s);
    },
    help: function (s) {
      return svgWrap(
        '<circle cx="12" cy="12" r="10"/>' +
        '<path d="M9 9a3 3 0 015.83 1c0 2-3 3-3 3"/>' +
        '<line x1="12" y1="17" x2="12.01" y2="17"/>', s);
    },
    chevron: function (s) {
      return svgWrap('<polyline points="9 18 15 12 9 6"/>', s);
    }
  };

  // ── Media helpers ────────────────────────────────────────
  function ytEmbed(id, title) {
    if (location.protocol === 'file:') {
      // Iframes blocked on file:// - show a simple link tile instead
      return '<div class="mw-media ratio" style="background:#0c1424;">' +
        '<a href="https://www.youtube.com/watch?v=' + esc(id) + '" target="_blank" rel="noopener"' +
        ' style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;text-decoration:none;">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8" fill="#38bdf8" stroke="none"/></svg>' +
        '<span style="font-size:13px;font-weight:600;color:#b8cad8;">' + esc(title) + '</span>' +
        '<span style="font-size:11px;color:#8899a8;">Opens on YouTube ↗</span>' +
        '</a></div>';
    }
    return '<div class="mw-media ratio">' +
      '<iframe src="https://www.youtube-nocookie.com/embed/' + esc(id) +
      '?modestbranding=1&rel=0" title="' + esc(title) +
      '" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"' +
      ' allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>' +
      '</div>';
  }

  function installVideo() {
    return '<div class="mw-media"><video src="' + VIDEO_INSTALL +
      '" autoplay loop muted playsinline disablepictureinpicture></video></div>';
  }

  function note(kind, iconHtml, html) {
    return '<div class="mw-note ' + kind + '"><span class="mw-note-ico">' + iconHtml + '</span><div>' + html + '</div></div>';
  }

  // ── Screen content ───────────────────────────────────────
  function introScreen() {
    var mac = ICO.monitor(22);
    return {
      eyebrow: 'Setup Assistant',
      title: 'Welcome! Let’s get you set up',
      sub: 'It only takes about two minutes. First - which version of macOS are you on? We’ll tailor the steps to your Mac.',
      body:
        '<div class="mw-options">' +
          optBtn('new', mac, 'macOS 15 Sequoia or 26 Tahoe', 'The latest versions (2024-2025)') +
          optBtn('mid', mac, 'macOS 13 Ventura or 14 Sonoma', 'Released 2022-2023') +
          optBtn('old', mac, 'macOS 11 Big Sur or 12 Monterey', 'Released 2020-2021') +
        '</div>' +
        '<details class="mw-help-card">' +
          '<summary>' +
            '<span class="mw-help-icon">' + ICO.help(18) + '</span>' +
            '<span class="mw-help-text">Not sure which macOS version you have?</span>' +
            '<span class="mw-help-chevron">' + ICO.chevron(16) + '</span>' +
          '</summary>' +
          '<div class="mw-help-body">' +
            '<p>Click the <strong>Apple menu</strong> - the apple-shaped icon in the <strong>top-left corner</strong> of your menu bar - then choose <strong>About This Mac</strong>. Your macOS version name appears at the top (e.g. “Sequoia 15.1” or “Ventura 13.5”).</p>' +
          '</div>' +
        '</details>',
      noFoot: true
    };
  }

  function optBtn(v, iconHtml, title, desc) {
    return '<button class="mw-opt" data-version="' + v + '">' +
      '<span class="mw-opt-icon">' + iconHtml + '</span>' +
      '<span class="mw-opt-main">' +
        '<span class="mw-opt-title">' + title + '</span>' +
        '<span class="mw-opt-desc">' + desc + '</span>' +
      '</span>' +
      '<span class="mw-opt-arrow">' + ICO.chevron(16) + '</span>' +
    '</button>';
  }

  function installScreen() {
    return {
      eyebrow: 'Step 1 of 5',
      title: 'Move the app to Applications',
      sub: 'Drag the Canvas Downloader icon into your Applications folder.',
      body:
        installVideo() +
        '<p class="mw-media-cap">Drag the icon onto the Applications folder - just like the clip above.</p>' +
        note('cyan', ICO.bulb(18), 'Installing into <strong>Applications</strong> is what lets macOS trust the app. Once it’s copied across, you can close and eject the installer window.')
    };
  }

  function openScreen() {
    if (state.version === 'new') {
      return {
        eyebrow: 'Step 2 of 5',
        title: 'Open the app for the first time',
        sub: 'Apple is extra-cautious with free apps. Here’s the one-time fix.',
        body:
          note('cyan', ICO.shield(18), 'You’ll see a warning that the app “can’t be opened.” This is completely normal for free, open-source apps - it does <strong>not</strong> mean anything is wrong. Here’s the 30-second fix:') +
          ytEmbed(YT_GATEKEEPER, 'Opening Canvas Downloader on macOS') +
          '<p class="mw-media-cap">The full process, start to finish (shown on macOS Sequoia).</p>' +
          '<ul class="mw-steps">' +
            '<li>Double-click <strong>Canvas Downloader</strong> in Applications. In the “Not Opened” dialog, click <strong>Done</strong>.</li>' +
            '<li>Open <strong>System Settings</strong> (Apple menu → System Settings) → <strong>Privacy &amp; Security</strong>.</li>' +
            '<li>Scroll down to the <strong>Security</strong> section. Next to “Canvas Downloader was blocked”, click <strong>Open Anyway</strong>.</li>' +
            '<li>Click <strong>Open Anyway</strong> again to confirm.</li>' +
            '<li>Enter your Mac password and click <strong>OK</strong> - the app opens.</li>' +
          '</ul>'
      };
    }
    if (state.version === 'mid') {
      return {
        eyebrow: 'Step 2 of 5',
        title: 'Open the app for the first time',
        sub: 'Good news - on Ventura and Sonoma it’s just two clicks.',
        body:
          note('cyan', ICO.shield(18), 'Apple blocks unsigned apps on first launch. This does <strong>not</strong> mean anything is wrong - it’s normal for every free app. The quickest way around it:') +
          '<ul class="mw-steps">' +
            '<li>In your <strong>Applications</strong> folder, <strong>right-click</strong> (or Control-click) Canvas Downloader and choose <strong>Open</strong>.</li>' +
            '<li>A warning appears - click <strong>Open</strong>. The app launches and is trusted from now on.</li>' +
          '</ul>' +
          '<p class="mw-hint"><strong>No "Open" option?</strong> Go to System Settings → <strong>Privacy &amp; Security</strong> → <strong>Open Anyway</strong> instead - the full guide walks through every step.</p>'
      };
    }
    // old (11/12)
    return {
      eyebrow: 'Step 2 of 5',
      title: 'Open the app for the first time',
      sub: 'On your macOS version it’s just a couple of clicks.',
      body:
        note('cyan', ICO.shield(18), 'Apple blocks unsigned apps on first launch. This is normal for every free app and doesn’t mean anything is wrong:') +
        '<ul class="mw-steps">' +
          '<li>In <strong>Applications</strong>, <strong>right-click</strong> Canvas Downloader and choose <strong>Open</strong>, then click <strong>Open</strong> in the dialog.</li>' +
          '<li>Still blocked? Open <strong>System Preferences</strong> → <strong>Security &amp; Privacy</strong> → <strong>General</strong> tab → click <strong>Open Anyway</strong>.</li>' +
        '</ul>'
    };
  }

  function notificationsScreen() {
    return {
      eyebrow: 'Step 3 of 5',
      title: 'Allow notifications',
      sub: 'So you get a “Download Complete” alert when a long run finishes.',
      body:
        '<ul class="mw-steps">' +
          '<li>When the app first opens, a small notification prompt appears in the <strong>top-right corner</strong> of your screen.</li>' +
          '<li>Click it and choose <strong>Allow</strong>.</li>' +
        '</ul>' +
        note('cyan', ICO.bell(18), 'That’s the only notification the app ever sends - a single alert when your download or sync is finished, so you can step away while it works.') +
        '<p class="mw-hint"><strong>Missed the prompt?</strong> Enable it any time: open <strong>System Settings</strong> → <strong>Notifications</strong> → <strong>Canvas Downloader</strong>.</p>'
    };
  }

  function loginScreen() {
    return {
      eyebrow: 'Step 4 of 5',
      title: 'Log in to Canvas',
      sub: 'Enter your Canvas URL and a personal API token.',
      body:
        ytEmbed(YT_TOKEN, 'How to get your Canvas API token') +
        '<p class="mw-media-cap">Creating an API token takes about 30 seconds - the clip shows exactly how.</p>' +
        '<ul class="mw-steps">' +
          '<li>Type your <strong>Canvas URL</strong> (for example <strong>https://your-school.instructure.com</strong>).</li>' +
          '<li>Paste your personal <strong>API token</strong>, then click <strong>Log In</strong>.</li>' +
        '</ul>' +
        note('cyan', ICO.lock(18), 'Your token is stored securely in your Mac’s Keychain and is only ever used to talk to your university’s Canvas server. The app has no backend - everything runs locally.') +
        '<p class="mw-hint">The login screen also has built-in guides for finding your Canvas URL and generating a token, in case you’d rather read along.</p>'
    };
  }

  function permissionsScreen() {
    var rows = '';
    if (state.version === 'new') {
      rows += permRow(ICO.layers(16), 'App data access', 'Lets conversions run in a private scratch folder.', true);
    }
    rows += permRow(ICO.folder(16),   'Your Downloads folder',              'So your course files can be saved.',              false);
    rows += permRow(ICO.terminal(16), 'System Events',                      'Keeps Office windows hidden during conversions.', false);
    rows += permRow(ICO.grid(16),     'Microsoft PowerPoint, Word &amp; Excel', 'The PowerPoint / Word / Excel → PDF conversions.', false);

    return {
      eyebrow: 'Step 5 of 5',
      title: 'Your first download',
      sub: 'macOS asks for a few one-time permissions. Click Allow on each - they never come back.',
      body:
        note('amber', ICO.clock(18), '<strong>Stay near your Mac for the first minute of your first download.</strong> If a permission dialog sits unanswered too long, that one file’s conversion is skipped - you can always re-run a Sync to catch it later.') +
        '<div class="mw-perms">' + rows + '</div>' +
        '<p class="mw-hint">Office permissions only appear for apps you have installed. <strong>No Office?</strong> Those dialogs are skipped automatically and your original files are kept as-is.</p>',
      lastLabel: 'I’m ready - finish →'
    };
  }

  function permRow(iconHtml, name, desc, isNew) {
    return '<div class="mw-perm">' +
      '<div class="mw-perm-ico">' + iconHtml + '</div>' +
      '<div class="mw-perm-body">' +
        '<div class="mw-perm-name">' + name +
          (isNew ? ' <span class="mw-tag-15">macOS 15+ only</span>' : '') +
        '</div>' +
        '<div class="mw-perm-desc">' + desc + '</div>' +
      '</div>' +
      '<span class="mw-perm-allow">Allow</span>' +
    '</div>';
  }

  function doneScreen() {
    var actions = '<a class="mw-link primary" href="index.html">Back to homepage</a>';
    if (GUIDE_HREF) {
      actions += '<a class="mw-link" href="' + esc(GUIDE_HREF) + '">' + esc(GUIDE_LABEL) + '</a>';
    }
    return {
      done: true,
      body:
        '<div class="mw-done">' +
          '<div class="mw-done-emoji">🎉</div>' +
          '<h2>You’re all set!</h2>' +
          '<p>Every future download and sync runs completely hands-free. Enjoy studying with Canvas Downloader!</p>' +
          '<div class="mw-done-actions">' + actions + '</div>' +
          '<button class="mw-restart" data-restart>↺ Run through the setup again</button>' +
        '</div>'
    };
  }

  var BUILDERS = {
    intro: introScreen,
    install: installScreen,
    open: openScreen,
    notifications: notificationsScreen,
    login: loginScreen,
    permissions: permissionsScreen,
    done: doneScreen
  };

  // ── Progress bar ─────────────────────────────────────────
  function progressBar() {
    if (state.screen === 'intro') return '';
    var idx = STEPS.indexOf(state.screen);   // -1 for 'done'
    var html = '<div class="mw-progress">';
    for (var i = 0; i < STEPS.length; i++) {
      var cls = 'mw-seg';
      if (state.screen === 'done' || i < idx) cls += ' done';
      else if (i === idx) cls += ' current';
      html += '<div class="' + cls + '"></div>';
    }
    return html + '</div>';
  }

  function footerBar(data) {
    if (data.noFoot || data.done) return '';
    var idx = STEPS.indexOf(state.screen);
    var isLast = idx === STEPS.length - 1;
    var nextLabel = data.lastLabel || (isLast ? 'Finish →' : 'I’ve done this →');
    return '<div class="mw-foot">' +
      '<button class="mw-btn mw-btn-ghost" data-back>← Back</button>' +
      '<div class="mw-foot-spacer"></div>' +
      '<button class="mw-btn mw-btn-primary" data-next>' + nextLabel + '</button>' +
    '</div>';
  }

  // ── Render ───────────────────────────────────────────────
  function render() {
    var data = BUILDERS[state.screen]();
    var head = '';
    if (!data.done) {
      head = '<div class="mw-head">' +
        (data.eyebrow ? '<div class="mw-eyebrow">' + data.eyebrow + '</div>' : '') +
        '<h2 class="mw-title">' + data.title + '</h2>' +
        '<p class="mw-sub">' + data.sub + '</p>' +
      '</div>';
    }
    mount.innerHTML =
      '<div class="mw"><div class="mw-card">' +
        progressBar() + head +
        '<div class="mw-body">' + data.body + '</div>' +
        footerBar(data) +
      '</div></div>';
    wire();
  }

  // ── Navigation ───────────────────────────────────────────
  function goTo(screen) {
    state.screen = screen;
    render();
    var top = mount.getBoundingClientRect().top + window.pageYOffset - 80;
    if (window.pageYOffset > top + 40) window.scrollTo({ top: top, behavior: 'smooth' });
  }

  function next() {
    var idx = STEPS.indexOf(state.screen);
    if (idx === -1) return;
    goTo(idx === STEPS.length - 1 ? 'done' : STEPS[idx + 1]);
  }

  function back() {
    var idx = STEPS.indexOf(state.screen);
    goTo(idx <= 0 ? 'intro' : STEPS[idx - 1]);
  }

  // ── Wire events ──────────────────────────────────────────
  function wire() {
    // Version option buttons
    var opts = mount.querySelectorAll('.mw-opt');
    for (var i = 0; i < opts.length; i++) {
      opts[i].addEventListener('click', function () {
        state.version = this.getAttribute('data-version');
        goTo('install');
      });
    }

    // Next / back / restart
    var nx = mount.querySelector('[data-next]');
    if (nx) nx.addEventListener('click', next);
    var bk = mount.querySelector('[data-back]');
    if (bk) bk.addEventListener('click', back);
    var rs = mount.querySelector('[data-restart]');
    if (rs) rs.addEventListener('click', function () { state.version = null; goTo('intro'); });

  }

  render();
})();
