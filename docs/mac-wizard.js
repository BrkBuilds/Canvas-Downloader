/* ============================================================
   Canvas Downloader — macOS Setup Wizard
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

  // ── helpers ──────────────────────────────────────────────
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function ytEmbed(id, title) {
    if (location.protocol === 'file:') {
      return '<div class="mw-media ratio"><a class="mw-yt-fallback" href="https://www.youtube.com/watch?v=' + id +
        '" target="_blank" rel="noopener" style="background-image:url(\'https://img.youtube.com/vi/' + id +
        '/hqdefault.jpg\')"><span class="mw-play"></span><span class="mw-yt-label">Watch on YouTube</span></a></div>';
    }
    return '<div class="mw-media ratio"><iframe src="https://www.youtube.com/embed/' + id +
      '?modestbranding=1&rel=0&showinfo=0" title="' + esc(title) +
      '" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"' +
      ' allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div>';
  }

  function installVideo() {
    return '<div class="mw-media"><video src="' + VIDEO_INSTALL +
      '" autoplay loop muted playsinline disablepictureinpicture></video></div>';
  }

  function note(kind, ico, html) {
    return '<div class="mw-note ' + kind + '"><span class="mw-note-ico">' + ico + '</span><div>' + html + '</div></div>';
  }

  // ── screen content ───────────────────────────────────────
  function introScreen() {
    return {
      eyebrow: 'Setup Assistant',
      title: 'Welcome! Let’s get you set up',
      sub: 'It only takes about two minutes. First — which version of macOS are you on? We’ll tailor the steps to your Mac.',
      body:
        '<div class="mw-options">' +
          optBtn('new', '🆕', 'macOS 15 Sequoia or 26 Tahoe', 'The latest versions (2024–2025)') +
          optBtn('mid', '💻', 'macOS 13 Ventura or 14 Sonoma', 'Released 2022–2023') +
          optBtn('old', '🗄️', 'macOS 11 Big Sur or 12 Monterey', 'Released 2020–2021') +
        '</div>' +
        '<details class="mw-disclosure"><summary>Not sure which one you have?</summary>' +
        '<p>Click the  <strong>Apple menu</strong> in the top-left corner of your screen and choose <strong>About This Mac</strong>. The version name and number are listed at the top.</p></details>',
      noFoot: true
    };
  }

  function optBtn(v, emoji, title, desc) {
    return '<button class="mw-opt" data-version="' + v + '">' +
      '<span class="mw-opt-emoji">' + emoji + '</span>' +
      '<span class="mw-opt-main"><span class="mw-opt-title">' + title + '</span>' +
      '<span class="mw-opt-desc">' + desc + '</span></span>' +
      '<span class="mw-opt-arrow">→</span></button>';
  }

  function installScreen() {
    return {
      eyebrow: 'Step 1 of 5',
      title: 'Move the app to Applications',
      sub: 'Drag the Canvas Downloader icon into your Applications folder.',
      body:
        installVideo() +
        '<p class="mw-media-cap">Drag the icon onto the Applications folder — just like the clip above.</p>' +
        note('cyan', '💡', 'Installing into <strong>Applications</strong> is what lets macOS trust the app. Once it’s copied across, you can close and eject the installer window.')
    };
  }

  function openScreen() {
    if (state.version === 'new') {
      return {
        eyebrow: 'Step 2 of 5',
        title: 'Open the app for the first time',
        sub: 'Apple is extra-cautious with free apps. Here’s the one-time fix.',
        body:
          note('cyan', '🛡️', 'You’ll see a warning that the app “can’t be opened.” This is completely normal for free, open-source apps — it does <strong>not</strong> mean anything is wrong. Here’s the 30-second fix:') +
          ytEmbed(YT_GATEKEEPER, 'Opening Canvas Downloader on macOS') +
          '<p class="mw-media-cap">The full process, start to finish (shown on macOS Sequoia).</p>' +
          '<ul class="mw-steps">' +
            '<li>Double-click <strong>Canvas Downloader</strong> in Applications. In the “Not Opened” dialog, click <strong>Done</strong>.</li>' +
            '<li>Open the  <strong>Apple menu</strong> → <strong>System Settings</strong> → <strong>Privacy &amp; Security</strong>.</li>' +
            '<li>Scroll down to <strong>Security</strong>. Next to “Canvas Downloader was blocked”, click <strong>Open Anyway</strong>.</li>' +
            '<li>Click <strong>Open Anyway</strong> again to confirm.</li>' +
            '<li>Enter your Mac password and click <strong>OK</strong> — the app opens. 🎉</li>' +
          '</ul>'
      };
    }
    if (state.version === 'mid') {
      return {
        eyebrow: 'Step 2 of 5',
        title: 'Open the app for the first time',
        sub: 'Good news — on your macOS version it’s just two clicks.',
        body:
          note('cyan', '🛡️', 'Apple blocks free apps on first launch. This does <strong>not</strong> mean anything is wrong — it’s normal for every unsigned app. The quickest way around it on macOS Ventura / Sonoma:') +
          '<ul class="mw-steps">' +
            '<li>In your <strong>Applications</strong> folder, <strong>right-click</strong> (or Control-click) Canvas Downloader and choose <strong>Open</strong>.</li>' +
            '<li>A warning appears — click <strong>Open</strong>. The app launches and is trusted from now on. 🎉</li>' +
          '</ul>' +
          '<p class="mw-hint">Don’t see an <strong>Open</strong> option? Use  → <strong>System Settings</strong> → <strong>Privacy &amp; Security</strong> → <strong>Open Anyway</strong> instead — the full written guide shows every step.</p>'
      };
    }
    // old
    return {
      eyebrow: 'Step 2 of 5',
      title: 'Open the app for the first time',
      sub: 'On your macOS version it’s just a couple of clicks.',
      body:
        note('cyan', '🛡️', 'Apple blocks free apps on first launch. This is normal for every unsigned app and doesn’t mean anything is wrong:') +
        '<ul class="mw-steps">' +
          '<li>In <strong>Applications</strong>, <strong>right-click</strong> Canvas Downloader → <strong>Open</strong>, then click <strong>Open</strong> in the dialog.</li>' +
          '<li>Still blocked? Open  → <strong>System Preferences</strong> → <strong>Security &amp; Privacy</strong> → <strong>General</strong> tab → click <strong>Open Anyway</strong>. 🎉</li>' +
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
        note('cyan', '🔔', 'That’s the only notification the app ever sends — a single alert when your download or sync is finished, so you can step away while it works.') +
        '<p class="mw-hint">Missed the prompt? You can switch it on any time under  → <strong>System Settings</strong> → <strong>Notifications</strong> → <strong>Canvas Downloader</strong>.</p>'
    };
  }

  function loginScreen() {
    return {
      eyebrow: 'Step 4 of 5',
      title: 'Log in to Canvas',
      sub: 'Enter your Canvas URL and a personal API token.',
      body:
        ytEmbed(YT_TOKEN, 'How to get your Canvas API token') +
        '<p class="mw-media-cap">Creating an API token takes about 30 seconds — the clip shows exactly how.</p>' +
        '<ul class="mw-steps">' +
          '<li>Type your <strong>Canvas URL</strong> (for example <strong>https://your-school.instructure.com</strong>).</li>' +
          '<li>Paste a personal <strong>API token</strong>, then click <strong>Log In</strong>.</li>' +
        '</ul>' +
        note('cyan', '🔒', 'Your token is stored securely in your Mac’s Keychain and is only ever used to talk to your university’s Canvas server. The app has no backend — everything runs locally.') +
        '<p class="mw-hint">The login screen also has built-in <strong>“How to find your Canvas URL”</strong> and token guides if you’d rather read along.</p>'
    };
  }

  function permissionsScreen() {
    var perms = '';
    if (state.version === 'new') {
      perms += permRow('🗂️', 'App data access', 'Lets conversions run in a private scratch folder.', true);
    }
    perms += permRow('📁', 'Your Downloads folder', 'So your course files can be saved.', false);
    perms += permRow('⚙️', 'System Events', 'Keeps Office windows hidden during conversions.', false);
    perms += permRow('📊', 'Microsoft PowerPoint, Word &amp; Excel', 'The actual PowerPoint/Word/Excel → PDF conversions.', false);

    return {
      eyebrow: 'Step 5 of 5',
      title: 'Your first download',
      sub: 'macOS asks for a few one-time permissions. Click Allow on each — they never come back.',
      body:
        note('amber', '⏱️', '<strong>Stay near your Mac for the first minute of your first download.</strong> If a permission dialog sits unanswered too long, that one file’s conversion is skipped — you can always re-run a Sync to catch it later.') +
        '<div class="mw-perms">' + perms + '</div>' +
        '<p class="mw-hint">The Office permissions only appear for the apps you actually have installed. <strong>No Office?</strong> Those are skipped automatically and your original files are kept as-is.</p>',
      lastLabel: 'I’m ready — finish →'
    };
  }

  function permRow(ico, name, desc, isNew) {
    return '<div class="mw-perm"><div class="mw-perm-ico">' + ico + '</div>' +
      '<div class="mw-perm-body"><div class="mw-perm-name">' + name +
      (isNew ? ' <span class="mw-tag-15">macOS 15+ only</span>' : '') + '</div>' +
      '<div class="mw-perm-desc">' + desc + '</div></div>' +
      '<span class="mw-perm-allow">Allow</span></div>';
  }

  function doneScreen() {
    var actions = '<a class="mw-link primary" href="index.html">🏠 Back to homepage</a>';
    if (GUIDE_HREF) {
      actions += '<a class="mw-link" href="' + esc(GUIDE_HREF) + '">📖 ' + esc(GUIDE_LABEL) + '</a>';
    }
    return {
      done: true,
      body:
        '<div class="mw-done">' +
          '<div class="mw-done-emoji">🎉</div>' +
          '<h2>You’re all set!</h2>' +
          '<p>Every future download and sync runs completely hands-free. Enjoy your fully offline Canvas library.</p>' +
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

  // ── render ───────────────────────────────────────────────
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

  function footer(data) {
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

  function render() {
    var data = BUILDERS[state.screen]();
    var head = '';
    if (!data.done) {
      head = '<div class="mw-head">' +
        (data.eyebrow ? '<div class="mw-eyebrow">' + data.eyebrow + '</div>' : '') +
        '<h2 class="mw-title">' + data.title + '</h2>' +
        '<p class="mw-sub">' + data.sub + '</p></div>';
    }
    mount.innerHTML = '<div class="mw"><div class="mw-card">' +
      progressBar() + head +
      '<div class="mw-body">' + data.body + '</div>' +
      footer(data) +
      '</div></div>';
    wire();
  }

  // ── navigation ───────────────────────────────────────────
  function goTo(screen) {
    state.screen = screen;
    render();
    // keep the wizard in view when advancing
    var top = mount.getBoundingClientRect().top + window.pageYOffset - 80;
    if (window.pageYOffset > top + 40) window.scrollTo({ top: top, behavior: 'smooth' });
  }

  function next() {
    var idx = STEPS.indexOf(state.screen);
    if (idx === -1) return;
    if (idx === STEPS.length - 1) goTo('done');
    else goTo(STEPS[idx + 1]);
  }

  function back() {
    var idx = STEPS.indexOf(state.screen);
    if (idx <= 0) goTo('intro');
    else goTo(STEPS[idx - 1]);
  }

  function wire() {
    var opts = mount.querySelectorAll('.mw-opt');
    for (var i = 0; i < opts.length; i++) {
      opts[i].addEventListener('click', function () {
        state.version = this.getAttribute('data-version');
        goTo('install');
      });
    }
    var nx = mount.querySelector('[data-next]');
    if (nx) nx.addEventListener('click', next);
    var bk = mount.querySelector('[data-back]');
    if (bk) bk.addEventListener('click', back);
    var rs = mount.querySelector('[data-restart]');
    if (rs) rs.addEventListener('click', function () { state.version = null; goTo('intro'); });
  }

  render();
})();
