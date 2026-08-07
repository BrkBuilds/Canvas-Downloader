"""The login page's institution picker: markup, and the bridge that drives it.

WHAT THIS IS
    A searchable directory of Canvas institutions sitting to the RIGHT of the
    "Your Canvas URL" field. Picking one writes its address into that field.
    The field stays fully editable, so the picker is a shortcut and never a
    gate - typing or pasting an address remains the universal path, which is
    what keeps every one of the thousands of Canvas schools NOT in the list
    working exactly as before.

WHY IT IS HAND-BUILT MARKUP AND NOT ``st.selectbox``
    Two independent reasons, either one sufficient:

    1. **The URL field lives inside ``st.form``.** A Streamlit widget inside a
       form cannot trigger a rerun, so a native picker could not fill the field
       until the form was submitted - which is the one moment the value is no
       longer needed. Writing the value client-side is the only way "pick a
       school, see it appear" can happen at all without moving the field out of
       the form (and losing Enter-to-submit).
    2. The baseweb select renders through a portal that cannot be styled into
       this card without fighting it, and the app's rule is no default
       Streamlit styling on this screen.

ACCIDENTAL-SUBMIT PROTECTION (and what is actually true in 1.51)
    Measured in the running app on 2026-08-07: ``st.form`` renders a **DIV**,
    not a ``<form>`` element - there are zero ``<form>`` nodes on the login
    page. So a bare ``<button>`` here does NOT natively submit, and an earlier
    version of this note claiming it did was wrong.

    The protections stay, for two reasons that are true:
      * Streamlit implements Enter-to-submit with its own keydown handling, so
        an un-swallowed Enter in the picker's search box can still fire the
        login. The bridge stops the event in the capture phase.
      * ``type="button"`` costs nothing and is the correct declaration for a
        control that is not a submit control. If Streamlit ever renders a real
        form, this code does not silently become a bug.
    Both are asserted by ``tests/test_institution_picker.py``.

THE DATA IS SERVER-SENT; THE ROWS ARE RENDERED ON DEMAND
    A ``components.html`` iframe is rebuilt only when its srcdoc CHANGES, and
    this bridge's script is a constant - so it runs ONCE per mount and gets no
    say in when the next mount is (see CLAUDE.md, "components.html JS bridges").
    That is why the institution DATA travels in the markdown, as one delimited
    payload on ``.cd-inst-list[data-rows]``: the server re-sends it on every
    rerun, so it cannot go stale. Anything the bridge *invented* would vanish
    the first time Streamlit re-rendered this markdown and never come back.

    The option ROWS are a different matter and are built by the bridge, from
    that payload, whenever the panel opens or the query changes. That is safe
    precisely because they are derived - never a source of truth - and every
    path that can show the list re-renders it first. It is also necessary:
    ~1,900 institutions as one button each is ~230 KB of markup for React to
    re-parse on every rerun, plus 1,900 live nodes to filter per keystroke.
    Only the top ``RENDER_CAP`` matches ever exist as DOM.

    The corollary is that user state the bridge DOES set (the picked label) is
    safe for the opposite reason: React leaves an unchanged
    ``dangerouslySetInnerHTML`` subtree alone across reruns, so our mutations
    to it survive - the same property the pure-CSS help card relies on.

KEYBOARD AND SCREEN READERS
    A real combobox: ArrowUp/Down (wrapping), Home/End, PageUp/Down, Enter to
    take the active row, Escape to close and return focus to the trigger, Tab
    to leave. The active row is tracked with ``aria-activedescendant`` on the
    search input rather than by moving focus, so typing never stops working,
    and the live match count sits in an ``aria-live`` region.
"""
from __future__ import annotations



from shared.helpers import esc as _he
from shared import institutions as _inst

# Lucide glyphs, inline so CSS can recolour them via `color` / currentColor.
_ICO_GLOBE = (
    "<svg class='cd-inst-ico' viewBox='0 0 24 24' width='15' height='15' fill='none' "
    "stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
    "<circle cx='12' cy='12' r='10'/><line x1='2' y1='12' x2='22' y2='12'/>"
    "<path d='M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z'/></svg>"
)
_ICO_CHEV = (
    "<svg class='cd-inst-chev' viewBox='0 0 24 24' width='14' height='14' fill='none' "
    "stroke='currentColor' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'>"
    "<polyline points='6 9 12 15 18 9'/></svg>"
)
_ICO_SEARCH = (
    "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' "
    "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
    "<circle cx='11' cy='11' r='8'/><line x1='21' y1='21' x2='16.65' y2='16.65'/></svg>"
)
_ICO_INFO = (
    "<svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' "
    "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
    "<circle cx='12' cy='12' r='10'/><line x1='12' y1='16' x2='12' y2='12'/>"
    "<line x1='12' y1='8' x2='12.01' y2='8'/></svg>"
)

TRIGGER_LABEL = "Find your institution"


# Payload delimiters. Chosen because no institution name or domain can contain
# them, and because both survive an HTML attribute untouched - unlike tabs and
# newlines, which some parsers normalise. `build_payload` strips them anyway,
# and a test proves the shipped data is free of both.
_FS = "»"   # field separator, between name/domain/country
_RS = "«"   # record separator, between institutions

# Country names, so "denmark" finds Danish schools rather than only "dk".
# Only countries actually present in the shipped data need an entry; anything
# missing simply falls back to the two-letter code, which still searches.
COUNTRY_NAMES = {
    "AE": "united arab emirates uae", "AR": "argentina", "AT": "austria",
    "AU": "australia", "BD": "bangladesh", "BE": "belgium", "BR": "brazil",
    "CA": "canada", "CH": "switzerland", "CL": "chile", "CN": "china",
    "CO": "colombia", "CR": "costa rica", "CY": "cyprus", "CZ": "czechia",
    "DE": "germany deutschland", "DK": "denmark danmark", "EC": "ecuador",
    "EE": "estonia", "EG": "egypt", "ES": "spain espana", "FI": "finland",
    "FR": "france", "GB": "united kingdom uk britain england scotland wales",
    "GH": "ghana", "GR": "greece", "HK": "hong kong", "HR": "croatia",
    "HU": "hungary", "ID": "indonesia", "IE": "ireland", "IL": "israel",
    "IN": "india", "IS": "iceland", "IT": "italy", "JP": "japan",
    "KE": "kenya", "KR": "south korea", "LB": "lebanon", "LT": "lithuania",
    "LU": "luxembourg", "LV": "latvia", "MT": "malta", "MX": "mexico",
    "MY": "malaysia", "NA": "namibia", "NG": "nigeria", "NL": "netherlands holland",
    "NO": "norway norge", "NZ": "new zealand", "PE": "peru", "PH": "philippines",
    "PK": "pakistan", "PL": "poland", "PR": "puerto rico", "PT": "portugal",
    "QA": "qatar", "RW": "rwanda", "SA": "saudi arabia", "SE": "sweden sverige",
    "SG": "singapore", "SI": "slovenia", "TH": "thailand", "TR": "turkey",
    "TW": "taiwan", "TZ": "tanzania", "UG": "uganda", "US": "united states usa america",
    "VN": "vietnam", "ZA": "south africa", "ZW": "zimbabwe", "BW": "botswana",
    "MM": "myanmar burma", "NP": "nepal", "LK": "sri lanka", "JO": "jordan",
    "OM": "oman", "BH": "bahrain", "KW": "kuwait", "MA": "morocco",
    "ET": "ethiopia", "SN": "senegal", "CI": "ivory coast", "CM": "cameroon",
    "ZM": "zambia", "MW": "malawi", "MU": "mauritius", "FJ": "fiji",
    "PG": "papua new guinea", "BS": "bahamas", "JM": "jamaica", "TT": "trinidad",
    "BB": "barbados", "GY": "guyana", "BZ": "belize", "PA": "panama",
    "GT": "guatemala", "HN": "honduras", "SV": "el salvador", "NI": "nicaragua",
    "DO": "dominican republic", "UY": "uruguay", "PY": "paraguay", "BO": "bolivia",
    "VE": "venezuela", "RO": "romania", "BG": "bulgaria", "RS": "serbia",
    "SK": "slovakia", "UA": "ukraine", "GE": "georgia", "AM": "armenia",
    "AZ": "azerbaijan", "KZ": "kazakhstan", "UZ": "uzbekistan", "MN": "mongolia",
    "KH": "cambodia", "LA": "laos", "BN": "brunei", "MO": "macau",
    "AL": "albania", "MK": "north macedonia", "BA": "bosnia", "ME": "montenegro",
    "IQ": "iraq", "PS": "palestine", "SD": "sudan", "TN": "tunisia",
    "DZ": "algeria", "LY": "libya", "AO": "angola", "MZ": "mozambique",
    "GA": "gabon", "SC": "seychelles", "MV": "maldives", "AF": "afghanistan",
    "IR": "iran", "SY": "syria", "YE": "yemen", "LI": "liechtenstein",
    "MC": "monaco", "AD": "andorra", "SM": "san marino", "VA": "vatican",
    "GL": "greenland", "FO": "faroe islands", "AX": "aland islands", "GI": "gibraltar", "JE": "jersey",
    "GG": "guernsey", "IM": "isle of man", "BM": "bermuda", "KY": "cayman islands",
    "VI": "us virgin islands", "GU": "guam", "AS": "american samoa",
    "MP": "northern mariana islands", "MH": "marshall islands", "FM": "micronesia",
    "PW": "palau", "CK": "cook islands", "WS": "samoa", "TO": "tonga",
    "VU": "vanuatu", "SB": "solomon islands", "NC": "new caledonia",
    "PF": "french polynesia", "RE": "reunion", "MQ": "martinique",
    "GP": "guadeloupe", "GF": "french guiana", "CW": "curacao", "AW": "aruba",
    "SR": "suriname", "HT": "haiti", "CU": "cuba",
}


def search_blob(row) -> str:
    """The searchable haystack for one institution.

    Reuses the generated module's blob (name + domain + code) and adds the
    country's NAME, so "denmark" works and not only "dk". Built here rather
    than in the generated data because it is a presentation concern, and it is
    the ONE place the haystack is defined - the payload the bridge searches is
    produced from this function, so the two cannot drift.
    """
    return f"{_inst.search_blob(row)} {COUNTRY_NAMES.get(row[2], '')}".strip()


def build_payload() -> str:
    """Every institution as one delimited string, for a single data attribute.

    **Why not one button per institution.** That is what this shipped first,
    and at 274 entries it was fine. At ~1,900 it is ~230 KB of markup that
    Streamlit re-sends and React re-parses on every rerun of the login page,
    plus 1,900 live DOM nodes for the bridge to toggle on every keystroke. The
    payload is ~40% of the size, costs three DOM nodes, and lets the bridge
    render only the rows a query actually matches.

    The data still comes from the SERVER, which is the part that matters: a
    components.html bridge runs once per mount and never again, so anything it
    invented would vanish the first time Streamlit re-rendered this markdown.
    Rendering *from* server-sent data on demand is safe; *being* the data is
    not.
    """
    out = []
    for row in _inst.DATA:
        name, domain, _cc = row
        blob = search_blob(row)
        out.append(_FS.join((
            name.replace(_FS, " ").replace(_RS, " "),
            domain,
            blob.replace(_FS, " ").replace(_RS, " "),
        )))
    return _RS.join(out)


def picker_html() -> str:
    """The trigger + dropdown panel, as ONE line of HTML.

    Built as a single concatenated string with no newlines on purpose. An
    indented multi-line HTML literal passed to ``st.markdown`` turns any blank
    line into a block terminator and renders the 4-space-indented remainder as
    a CODE BLOCK - the failure the hub pair card hit. One line cannot have that
    bug regardless of how the list grows.
    """
    n = _inst.count()
    return (
        "<div class='cd-inst' data-open='0' data-empty='0' data-picked='0'>"
        "<button type='button' class='cd-inst-trigger' aria-haspopup='listbox'"
        " aria-expanded='false' aria-controls='cd-inst-listbox'"
        f" data-default-label='{_he(TRIGGER_LABEL)}'>"
        f"{_ICO_GLOBE}<span class='cd-inst-label'>{_he(TRIGGER_LABEL)}</span>{_ICO_CHEV}</button>"
        "<div class='cd-inst-panel'>"
        f"<div class='cd-inst-searchwrap'>{_ICO_SEARCH}"
        "<input type='text' class='cd-inst-input' autocomplete='off' spellcheck='false'"
        " role='combobox' aria-autocomplete='list' aria-expanded='true'"
        " aria-controls='cd-inst-listbox'"
        f" placeholder='Search {n:,} institutions' aria-label='Search institutions'/></div>"
        "<div class='cd-inst-meta' aria-live='polite'></div>"
        "<div class='cd-inst-list' id='cd-inst-listbox' role='listbox'"
        f" aria-label='Institutions' data-rows='{_he(build_payload())}'></div>"
        "<div class='cd-inst-none'>"
        "<div class='cd-inst-none-h'>Not in the list</div>"
        "<div class='cd-inst-none-b'>The picker covers "
        f"{n:,} institutions worldwide, so it will not have everyone. "
        "<b>Your school still works.</b> Close this and type or paste your Canvas "
        "web address in the field on the left.</div></div>"
        "</div></div>"
    )


def url_status_html() -> str:
    """The empty shell for live URL feedback; the bridge fills it in.

    Rendered unconditionally and left empty rather than emitted only when there
    is something to say. Streamlit reconciles by position, so a row that comes
    and goes would shift every element below it by one slot and hand the next
    element this one's DOM node - the keyed-card inheritance bug. An always
    present, `display:none`-until-`data-state` row cannot do that.
    """
    return "<div class='cd-url-status'><span class='cd-url-status-ico'></span><span class='cd-url-status-tx'></span></div>"


# ── The bridge ───────────────────────────────────────────────────────────────
# Rules this script obeys, each one a scar in CLAUDE.md:
#   * every listener is DELEGATED on `document` and re-queries live nodes, so
#     Streamlit replacing a node never unhooks it;
#   * mutable state lives on `window.parent`, not in this closure, because the
#     closure dies with the iframe realm;
#   * previous listeners are removed and fresh ones attached on EVERY run, so a
#     remount can never leave a listener bound to a dead realm;
#   * `blur()` is preceded by `focus()` - it is a no-op on an unfocused element,
#     which is how the clear-search X silently stopped committing once.
_BRIDGE_JS = """
<script>
(function () {
  var P = window.parent, D = P.document;
  var reg = P._cdInstReg || (P._cdInstReg = {});

  function root()   { return D.querySelector('.cd-inst'); }
  function statusEl(){ return D.querySelector('.cd-url-status'); }
  function urlInput() {
    // Key-class first (stable, ours); aria-label is the fallback because the
    // label text is what Streamlit puts on the control itself.
    return D.querySelector('div[class*="st-key-url_input"] input')
        || D.querySelector('input[aria-label="Your Canvas URL"]');
  }

  // Mirrors ui/auth.py:_looks_like_token. Deliberately the ONLY rule duplicated
  // client-side: it is four stable lines, and it catches the single most common
  // first-run mistake at the moment of the paste instead of after a submit.
  // Everything authoritative (normalisation, the real validation) stays in
  // Python on submit - this row never decides anything, it only explains.
  function looksLikeToken(s) {
    s = (s || '').trim();
    if (!s) return false;
    if (s.indexOf('~') !== -1) return true;
    return s.length >= 40 && s.indexOf('.') === -1 && s.indexOf('/') === -1
        && s.indexOf(' ') === -1 && !/^https?:\\/\\//i.test(s);
  }

  function hostOf(s) {
    s = (s || '').trim().toLowerCase();
    if (s.indexOf('://') !== -1) s = s.split('://')[1];
    s = s.split('/')[0].split('?')[0].split('#')[0];
    s = s.split('@').pop().split(':')[0];
    return s.indexOf('www.') === 0 ? s.slice(4) : s;
  }

  var ICO = {
    ok:   "<svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='20 6 9 17 4 12'/></svg>",
    warn: "<svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'/><line x1='12' y1='9' x2='12' y2='13'/><line x1='12' y1='17' x2='12.01' y2='17'/></svg>",
    info: "<svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><line x1='12' y1='16' x2='12' y2='12'/><line x1='12' y1='8' x2='12.01' y2='8'/></svg>"
  };

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Look the host up in the SERVER-RENDERED option list. Reusing that markup
  // means the recognised-institution check can never disagree with what the
  // picker offers - there is only one copy of the data on the page.
  // Look the host up in the PAYLOAD, never in the rendered rows.
  //
  // These two read the full data set, which exists whether or not the panel is
  // open. Reading the rendered `.cd-inst-opt` nodes instead - as this did once
  // - is only correct while the dropdown is showing: closing it empties the
  // list, so the very act of PICKING a school made that school unknown, and
  // the status line under a freshly-picked Copenhagen Business School read
  // "Not one of the listed institutions".
  function knownByHost(h) {
    if (!h) return null;
    var all = rows();
    for (var i = 0; i < all.length; i++) {
      if (all[i].domain === h) return all[i].name;
    }
    return null;
  }

  // Typing the university's MAIN website (harvard.edu) instead of its Canvas
  // host (canvas.harvard.edu) is a natural mistake, and it fails at login with
  // a generic connection error. If a verified Canvas host sits UNDER the host
  // typed, name it.
  //
  // Note the direction, which is what makes this safe: we are not accepting the
  // typed host as an institution - that is still exact-match only. We are
  // offering OUR verified domain, which cannot vouch for anything it did not
  // already vouch for. `evil-harvard.edu` still matches nothing.
  function suggestUnder(h) {
    var r = root();
    if (!r || !h || h.indexOf('.') === -1 || h.length < 4) return null;
    var all = rows(), best = null;
    for (var i = 0; i < all.length; i++) {
      var d = all[i].domain;
      if (d.length > h.length && d.slice(-(h.length + 1)) === '.' + h) {
        // Prefer the SHORTEST host under the typed domain. A university can
        // publish several tenants beneath one domain, and the main student
        // Canvas is reliably the least-qualified of them
        // (canvas.harvard.edu, not app.pc.hms.harvard.edu). Taking the first
        // match instead pointed Harvard at a pre-college certificate.
        if (!best || d.length < best.domain.length) {
          best = { domain: d, name: all[i].name };
        }
      }
    }
    return best;
  }

  function paintStatus() {
    // Same trigger, same moments: this fires on every URL keystroke, on pick
    // and on mount, which is precisely when the derived label can go stale.
    syncTrigger();
    var box = statusEl(), inp = urlInput();
    if (!box) return;
    var tx = box.querySelector('.cd-url-status-tx');
    var ic = box.querySelector('.cd-url-status-ico');
    var raw = inp ? (inp.value || '').trim() : '';
    var state = null, html = '';
    if (!raw) {
      state = null;
    } else if (looksLikeToken(raw)) {
      state = 'warn';
      html = 'That looks like an access token. It goes in the field below, not here.';
    } else {
      var h = hostOf(raw);
      var name = knownByHost(h);
      var sug = name ? null : suggestUnder(h);
      if (name) {
        state = 'ok'; html = 'Recognised: <b>' + esc(name) + '</b>';
      } else if (sug) {
        state = 'warn';
        html = 'That is the main website. Canvas for <b>' + esc(sug.name)
             + '</b> is at <b>' + esc(sug.domain) + '</b>';
      } else {
        // Deliberately SILENT. "Not one of the listed institutions, that is
        // fine" is exactly what the permanent hint below already says, so
        // saying it here too stacked two near-identical lines under the field
        // and made a normal, perfectly valid address look like a warning.
        // This row only speaks when it knows something the hint does not.
        state = null;
      }
    }
    if (!state) { box.removeAttribute('data-state'); if (tx) tx.innerHTML = ''; if (ic) ic.innerHTML = ''; return; }
    box.setAttribute('data-state', state);
    if (ic) ic.innerHTML = ICO[state] || '';
    if (tx) tx.innerHTML = html;
  }

  function setUrl(val) {
    var inp = urlInput(); if (!inp) return;
    var setter = Object.getOwnPropertyDescriptor(P.HTMLInputElement.prototype, 'value').set;
    setter.call(inp, val);
    // React's onChange is what puts the value into the form's pending state.
    inp.dispatchEvent(new P.Event('input', { bubbles: true }));
    // Streamlit commits a text input on blur. blur() does nothing on an element
    // that is not focused, so focus first - this is the exact trap the search
    // clear-X hit, where the DOM changed but Python never heard about it.
    try { inp.focus({ preventScroll: true }); inp.blur(); } catch (e) {}
  }

  // ── Data ──────────────────────────────────────────────────────────────
  // Parsed ONCE from the server-rendered payload and cached on window.parent,
  // because the iframe closure does not survive a remount. Re-derived if the
  // payload string itself changes (a rebuilt list), never otherwise.
  var FS = '\\u00bb', RS = '\\u00ab';
  // Nobody scrolls 100 unranked rows; the count line tells them to narrow.
  var RENDER_CAP = 60;

  function rows() {
    var list = D.querySelector('.cd-inst-list');
    if (!list) return [];
    var raw = list.getAttribute('data-rows') || '';
    if (reg.raw === raw && reg.rows) return reg.rows;
    var out = [], recs = raw ? raw.split(RS) : [];
    for (var i = 0; i < recs.length; i++) {
      var f = recs[i].split(FS);
      if (f.length >= 3) out.push({ name: f[0], domain: f[1], q: f[2] });
    }
    reg.raw = raw; reg.rows = out;
    return out;
  }

  function matches(q) {
    var all = rows();
    q = (q || '').trim().toLowerCase();
    if (!q) return all;
    // Every whitespace-separated term must appear, so "melb uni" finds "The
    // University of Melbourne" where a single substring test would not.
    var terms = q.split(/\\s+/), out = [];
    outer:
    for (var i = 0; i < all.length; i++) {
      for (var j = 0; j < terms.length; j++) {
        if (all[i].q.indexOf(terms[j]) === -1) continue outer;
      }
      out.push(all[i]);
    }
    return out;
  }

  // Highlight, with the pattern compiled ONCE per render rather than per row.
  // Measured before that change: a broad query cost 55-78 ms per keystroke -
  // visible lag while typing - almost all of it building 200 identical RegExp
  // objects. Escaping happens FIRST and the markup is inserted afterwards, so
  // an institution name can never inject.
  function highlighter(terms) {
    // A one-character term matches nearly everything, so highlighting it is
    // noise AND the most expensive case. Skip it.
    var useful = terms.filter(function (t) { return t && t.length >= 2; });
    if (!useful.length) return null;
    var pat = useful
      .map(function (t) { return t.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'); })
      .sort(function (a, b) { return b.length - a.length; })
      .join('|');
    try { return new RegExp('(' + pat + ')', 'gi'); } catch (e) { return null; }
  }

  function mark(text, re) {
    var safe = esc(text);
    if (!re) return safe;
    re.lastIndex = 0;
    return safe.replace(re, '<mark>$1</mark>');
  }

  function render() {
    var r = root(); if (!r) return;
    var list = r.querySelector('.cd-inst-list');
    var meta = r.querySelector('.cd-inst-meta');
    var s = r.querySelector('.cd-inst-input');
    var q = (s && s.value) || '';
    var terms = q.trim() ? q.trim().toLowerCase().split(/\\s+/) : [];
    var hits = matches(q);
    var show = hits.slice(0, RENDER_CAP);
    var re = highlighter(terms);

    var parts = [];
    for (var i = 0; i < show.length; i++) {
      parts.push("<button type='button' class='cd-inst-opt' role='option' id='cd-inst-opt-",
                 i, "' aria-selected='false' data-u='https://", esc(show[i].domain), "'>",
                 "<span class='cd-inst-nm'>", mark(show[i].name, re), "</span>",
                 "<span class='cd-inst-dm'>", mark(show[i].domain, re), "</span></button>");
    }
    list.innerHTML = parts.join('');
    list.scrollTop = 0;
    r.setAttribute('data-empty', hits.length ? '0' : '1');
    if (meta) {
      meta.textContent = !hits.length ? ''
        : (hits.length > show.length
             ? 'Showing ' + show.length + ' of ' + hits.length + ' matches - keep typing to narrow'
             : hits.length + (hits.length === 1 ? ' match' : ' matches'));
    }
    setActive(hits.length ? 0 : -1, false);
  }

  // ── Keyboard ──────────────────────────────────────────────────────────
  function opts() { var r = root(); return r ? r.querySelectorAll('.cd-inst-opt') : []; }

  function setActive(i, scroll) {
    var r = root(); if (!r) return;
    var list = opts();
    var s = r.querySelector('.cd-inst-input');
    for (var k = 0; k < list.length; k++) {
      var on = (k === i);
      if (on) { list[k].setAttribute('data-active', '1'); list[k].setAttribute('aria-selected', 'true'); }
      else { list[k].removeAttribute('data-active'); list[k].setAttribute('aria-selected', 'false'); }
    }
    reg.active = i;
    if (s) {
      if (i >= 0 && list[i]) s.setAttribute('aria-activedescendant', list[i].id);
      else s.removeAttribute('aria-activedescendant');
    }
    // Scroll ONLY when the keyboard moved the cursor. scrollIntoView forces a
    // synchronous layout, and calling it on every re-render cost 35-60 ms per
    // keystroke on a broad query - the single largest cost in the whole render
    // path, for a scroll that was already at the top anyway.
    if (scroll && i >= 0 && list[i] && list[i].scrollIntoView) {
      list[i].scrollIntoView({ block: 'nearest' });
    }
  }

  function move(delta) {
    var n = opts().length;
    if (!n) return;
    var cur = typeof reg.active === 'number' ? reg.active : -1;
    var next = cur + delta;
    if (next < 0) next = n - 1;
    if (next >= n) next = 0;
    setActive(next, true);
  }

  // `restoreFocus` decides whether closing pulls focus back to the trigger.
  //
  // It must be FALSE when the user closed the panel by clicking somewhere
  // else, because "somewhere else" is where they want the caret. Focusing the
  // trigger unconditionally made the picker steal focus out of the access-token
  // field a split second after every click into it: the field lit up, the
  // document-level click handler ran, focus jumped to the trigger, and the user
  // could not type their token at all. Login was unusable.
  function setOpen(on, restoreFocus) {
    var r = root(); if (!r) return;
    var wasOpen = r.getAttribute('data-open') === '1';
    // Closing something already closed must be a genuine no-op - this runs on
    // every click anywhere on the page.
    if (!on && !wasOpen) return;
    r.setAttribute('data-open', on ? '1' : '0');
    var t = r.querySelector('.cd-inst-trigger');
    if (t) t.setAttribute('aria-expanded', on ? 'true' : 'false');
    var s = r.querySelector('.cd-inst-input');
    if (on) {
      if (s) { s.value = ''; }
      render();
      if (s) { try { s.focus({ preventScroll: true }); } catch (e) {} }
    } else {
      if (s) s.value = '';
      // Drop the rendered rows on close: ~100 nodes that nothing can see, and
      // leaving them means a stale list flashes on the next open.
      var list = r.querySelector('.cd-inst-list');
      if (list) list.innerHTML = '';
      setActive(-1, false);
      // Only for a deliberate close (Escape, or taking a row). An outside
      // click passes false, so the element the user actually clicked keeps
      // the caret.
      if (restoreFocus && t) { try { t.focus({ preventScroll: true }); } catch (e) {} }
    }
  }

  // The trigger's label is DERIVED from the URL field, never remembered.
  //
  // The URL field is the only truth here - the picker exists solely to fill it.
  // Storing the picked name separately let the two drift: clear the field after
  // choosing a school and the picker still displayed that school, cheerfully
  // naming an institution the form was no longer pointing at. Deriving it also
  // gets the reverse for free: paste a different known school's address by hand
  // and the trigger updates to match.
  function syncTrigger() {
    var r = root(); if (!r) return;
    var lbl = r.querySelector('.cd-inst-label');
    var trig = r.querySelector('.cd-inst-trigger');
    if (!lbl || !trig) return;
    var inp = urlInput();
    var name = inp ? knownByHost(hostOf(inp.value || '')) : null;
    // textContent, not innerHTML: a matched row's label carries <mark> markup.
    lbl.textContent = name || trig.getAttribute('data-default-label') || '';
    r.setAttribute('data-picked', name ? '1' : '0');
  }

  function pick(opt) {
    var r = root(); if (!r || !opt) return;
    setUrl(opt.getAttribute('data-u') || '');
    setOpen(false, true);
    paintStatus();   // repaints the status line AND re-derives the trigger
  }

  function onClick(e) {
    var r = root(); if (!r) return;
    var t = e.target;
    if (!t || !t.closest) return;
    var opt = t.closest('.cd-inst-opt');
    if (opt && r.contains(opt)) { e.preventDefault(); e.stopPropagation(); pick(opt); return; }
    var trig = t.closest('.cd-inst-trigger');
    if (trig && r.contains(trig)) {
      e.preventDefault(); e.stopPropagation();
      setOpen(r.getAttribute('data-open') !== '1', true);
      return;
    }
    // No focus restore: the click landed somewhere else on purpose.
    if (!r.contains(t)) setOpen(false, false);
  }

  function onKey(e) {
    var r = root(); if (!r) return;
    var open = r.getAttribute('data-open') === '1';
    var t = e.target;
    var inSearch = t && t.classList && t.classList.contains('cd-inst-input');
    var onTrigger = t && t.closest && !!t.closest('.cd-inst-trigger') && r.contains(t);

    if (!open) {
      // Open from the trigger with the keyboard, the way a combobox should.
      if (onTrigger && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault(); setOpen(true, true);
      }
      return;
    }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setOpen(false, true); return; }
    if (e.key === 'Tab') { setOpen(false, false); return; }
    if (!inSearch) return;

    if (e.key === 'ArrowDown') { e.preventDefault(); move(1); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); return; }
    if (e.key === 'Home') { e.preventDefault(); setActive(0, true); return; }
    if (e.key === 'End') { e.preventDefault(); setActive(opts().length - 1, true); return; }
    if (e.key === 'PageDown') { e.preventDefault(); move(10); return; }
    if (e.key === 'PageUp') { e.preventDefault(); move(-10); return; }
    if (e.key === 'Enter') {
      // Streamlit implements Enter-to-submit itself, so an un-swallowed Enter
      // here fires the login with whatever is in the fields.
      e.preventDefault(); e.stopPropagation();
      var list = opts();
      var i = typeof reg.active === 'number' && reg.active >= 0 ? reg.active : 0;
      if (list[i]) pick(list[i]);
    }
  }

  function onInput(e) {
    var t = e.target;
    if (!t || !t.classList) return;
    if (t.classList.contains('cd-inst-input')) { render(); return; }
    var inp = urlInput();
    if (inp && t === inp) paintStatus();
  }

  // Re-bind: drop the previous handlers (their refs stay valid for removal even
  // if their realm is dead) and attach fresh ones from THIS realm.
  ['click', 'keydown', 'input'].forEach(function (evt) {
    var prev = reg[evt];
    if (prev) { try { D.removeEventListener(evt, prev, true); } catch (e) {} }
  });
  reg.click = onClick; reg.keydown = onKey; reg.input = onInput;
  D.addEventListener('click', onClick, true);
  D.addEventListener('keydown', onKey, true);
  D.addEventListener('input', onInput, true);

  paintStatus();
})();
</script>
"""


def inject_bridge() -> None:
    """Mount the picker's behaviour.

    Height 0: ``global.css`` already pulls zero-height ``components.html``
    iframes out of flow inside ``stMain``, so this costs no layout slot.
    """
    import streamlit.components.v1 as components

    components.html(_BRIDGE_JS, height=0)
