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

import functools
import unicodedata



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

# `.instructure.com` is a QUARTER of the payload, so it travels as one byte.
#
# Most Canvas tenants have no vanity domain, so the same 16 characters repeat
# once in the domain field and again inside the search blob. Measured on the
# 2026-08-09 list: 7,844 occurrences, 123 KB, 28% of a 437 KB payload - on the
# login page, which is the slowest screen in the app and the one a user
# reported hanging. The picker is the whole point of that screen (it is how
# nearly everyone finds their Canvas URL, and typing one by hand is the
# friction it exists to remove), so the answer is to make rows CHEAP, never to
# ship fewer of them.
#
# The bridge expands it on both fields at parse time, so nothing downstream can
# tell the difference: the displayed domain, the `https://` link and the search
# haystack are all byte-identical to the uncompressed form. Expansion happens
# once per mount - `rows()` memoises on the raw attribute - so the cost is two
# string operations per row, once.
#
# `*` is safe for the same reason as the delimiters above: it cannot occur in a
# hostname, `build_payload` strips it from names anyway, and a test proves the
# shipped payload carries none of its own.
_SUF = ".instructure.com"
_SUF_TOKEN = "*"

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


#: Display names for the same keys. A SECOND table rather than a richer value
#: on `COUNTRY_NAMES` because the two answer different questions - one is what
#: a user might TYPE (aliases, endonyms, "uk"), the other is what the picker
#: SAYS - and merging them would either lose the aliases or put "danmark" on
#: screen. `test_country_label_covers_country_names` pins the keys equal in
#: both directions, which is what stops the pair drifting.
COUNTRY_LABEL = {
    "AD": "Andorra", "AE": "the United Arab Emirates", "AF": "Afghanistan", "AL": "Albania",
    "AM": "Armenia", "AO": "Angola", "AR": "Argentina", "AS": "American Samoa",
    "AT": "Austria", "AU": "Australia", "AW": "Aruba", "AX": "Aland", "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina", "BB": "Barbados", "BD": "Bangladesh", "BE": "Belgium",
    "BG": "Bulgaria", "BH": "Bahrain", "BM": "Bermuda", "BN": "Brunei", "BO": "Bolivia",
    "BR": "Brazil", "BS": "the Bahamas", "BW": "Botswana", "BZ": "Belize", "CA": "Canada",
    "CH": "Switzerland", "CI": "Ivory Coast", "CK": "the Cook Islands", "CL": "Chile",
    "CM": "Cameroon", "CN": "China", "CO": "Colombia", "CR": "Costa Rica", "CU": "Cuba",
    "CW": "Curacao", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark",
    "DO": "the Dominican Republic", "DZ": "Algeria", "EC": "Ecuador", "EE": "Estonia",
    "EG": "Egypt", "ES": "Spain", "ET": "Ethiopia", "FI": "Finland", "FJ": "Fiji",
    "FM": "Micronesia", "FO": "the Faroe Islands", "FR": "France", "GA": "Gabon",
    "GB": "the United Kingdom", "GE": "Georgia", "GF": "French Guiana", "GG": "Guernsey",
    "GH": "Ghana", "GI": "Gibraltar", "GL": "Greenland", "GP": "Guadeloupe", "GR": "Greece",
    "GT": "Guatemala", "GU": "Guam", "GY": "Guyana", "HK": "Hong Kong", "HN": "Honduras",
    "HR": "Croatia", "HT": "Haiti", "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland",
    "IL": "Israel", "IM": "the Isle of Man", "IN": "India", "IQ": "Iraq", "IR": "Iran",
    "IS": "Iceland", "IT": "Italy", "JE": "Jersey", "JM": "Jamaica", "JO": "Jordan",
    "JP": "Japan", "KE": "Kenya", "KH": "Cambodia", "KR": "South Korea", "KW": "Kuwait",
    "KY": "the Cayman Islands", "KZ": "Kazakhstan", "LA": "Laos", "LB": "Lebanon",
    "LI": "Liechtenstein", "LK": "Sri Lanka", "LT": "Lithuania", "LU": "Luxembourg",
    "LV": "Latvia", "LY": "Libya", "MA": "Morocco", "MC": "Monaco", "ME": "Montenegro",
    "MH": "the Marshall Islands", "MK": "North Macedonia", "MM": "Myanmar",
    "MN": "Mongolia", "MO": "Macau", "MP": "the Northern Mariana Islands",
    "MQ": "Martinique", "MT": "Malta", "MU": "Mauritius", "MV": "the Maldives",
    "MW": "Malawi", "MX": "Mexico", "MY": "Malaysia", "MZ": "Mozambique", "NA": "Namibia",
    "NC": "New Caledonia", "NG": "Nigeria", "NI": "Nicaragua", "NL": "the Netherlands",
    "NO": "Norway", "NP": "Nepal", "NZ": "New Zealand", "OM": "Oman", "PA": "Panama",
    "PE": "Peru", "PF": "French Polynesia", "PG": "Papua New Guinea",
    "PH": "the Philippines", "PK": "Pakistan", "PL": "Poland", "PR": "Puerto Rico",
    "PS": "Palestine", "PT": "Portugal", "PW": "Palau", "PY": "Paraguay", "QA": "Qatar",
    "RE": "Reunion", "RO": "Romania", "RS": "Serbia", "RW": "Rwanda", "SA": "Saudi Arabia",
    "SB": "the Solomon Islands", "SC": "Seychelles", "SD": "Sudan", "SE": "Sweden",
    "SG": "Singapore", "SI": "Slovenia", "SK": "Slovakia", "SM": "San Marino",
    "SN": "Senegal", "SR": "Suriname", "SV": "El Salvador", "SY": "Syria", "TH": "Thailand",
    "TN": "Tunisia", "TO": "Tonga", "TR": "Turkey", "TT": "Trinidad and Tobago",
    "TW": "Taiwan", "TZ": "Tanzania", "UA": "Ukraine", "UG": "Uganda",
    "US": "the United States", "UY": "Uruguay", "UZ": "Uzbekistan", "VA": "Vatican City",
    "VE": "Venezuela", "VI": "the US Virgin Islands", "VN": "Vietnam", "VU": "Vanuatu",
    "WS": "Samoa", "YE": "Yemen", "ZA": "South Africa", "ZM": "Zambia", "ZW": "Zimbabwe",
}


#: Letters that do NOT decompose under NFKD, with what a keyboard without them
#: types instead. `ø` and `æ` are single code points with no combining form, so
#: no amount of Unicode normalisation turns them into `o` and `ae`.
_FOLD_PAIRS = (
    ("ø", "o"), ("æ", "ae"), ("å", "aa"), ("ß", "ss"),
    ("ð", "d"), ("þ", "th"), ("ł", "l"), ("đ", "d"), ("ı", "i"), ("œ", "oe"),
)


def fold(text: str) -> str:
    """*text* as someone would type it on a keyboard without the accents.

    NFKD splits a letter from its combining mark so the mark can be dropped -
    which handles `ö`, `ü`, `é`, `í`. It does NOT handle `ø`, `æ` or `ß`, which
    are letters in their own right, so those are mapped explicitly first.

    `å` folds to `aa`, not `a`: that is the Danish/Norwegian substitution people
    actually type (Aarhus, Aalborg), and it still matches a query of `a` by
    prefix. `aa` also survives the NFKD pass unchanged.
    """
    out = (text or "").lower()
    for src, dst in _FOLD_PAIRS:
        out = out.replace(src, dst)
    return "".join(c for c in unicodedata.normalize("NFKD", out)
                   if not unicodedata.combining(c))


def search_blob(row) -> str:
    """The searchable haystack for one institution, as ONE string.

    Kept because it is the readable definition of "what text finds this row",
    and the tests assert against it - but note the PAYLOAD no longer ships it
    (see `build_payload`). The bridge reassembles exactly this text from the
    fields it is given, which is why `test_payload_haystack_matches_blob` can
    compare the two.

    It carries an ACCENT-FOLDED copy, which local-language names made necessary
    the moment they shipped: the row is called "Københavns Universitet", and a
    student who types `kobenhavn` - because their keyboard has no `ø`, or
    because they simply did not bother - matched nothing at all. Measured in
    the running app: `kobenhavn`, `goteborg`, `hogskolan`, `lulea`, `haskolinn`
    and `nurnberg` each returned ZERO rows. Folding the HAYSTACK rather than
    the query is what keeps the query side simple: both spellings are present,
    so a plain substring test finds the row whichever way it was typed.

    Known and accepted: an UNACCENTED query finds the row but does not
    highlight it, because `mark()` runs against the displayed (accented) text
    and the two strings differ in length. Mapping folded offsets back onto the
    original is real work for a yellow background; being findable is the part
    that matters, and an accented query still highlights normally.
    """
    blob = (f"{_inst.search_blob(row)} {COUNTRY_NAMES.get(row[2], '')} "
            f"{aliases_of(row)}").strip()
    folded = fold(blob)
    return blob if folded == blob else f"{blob} {folded}"


def row_flags(row) -> str:
    """Per-row ranking flags. ``"s"`` marks a curated seed institution.

    Tolerant of a 3-tuple so the module keeps working against a list generated
    before flags existed - but the generator always emits four fields now, and
    a test pins that, because a silently flag-less list would rank exactly like
    the unranked one this replaced.
    """
    return row[3] if len(row) > 3 else ""


#: What students CALL their school, where that is nothing like its name.
#:
#: Search-only text, keyed by domain. It lives here and not in the generated
#: data because it is editorial rather than crawled - and deliberately NOT in
#: the builder's ``ALIASES``, which feeds the name MATCHER: a probe there can
#: make a seed corroborate a domain, so adding "KU" to it would let the
#: University of Copenhagen lay claim to any host with a `ku` label. Here the
#: worst a wrong entry can do is put one extra row in a result list.
#:
#: The gap this closes is real and was measured in the running app: a Dane
#: typing `ku` - which is what every Danish student calls Kobenhavns
#: Universitet - got the University of Kansas and not one Danish row, because
#: KU's Canvas is called `absalon` and its name contains no `ku` at all.
#: `test_search_aliases_point_at_shipped_domains` keeps the keys honest.
SEARCH_ALIASES = {
    # Nordics
    "absalon.instructure.com": "ku ucph kobenhavn koebenhavn",
    "cbscanvas.instructure.com": "cbs handelshojskolen",
    "uio.instructure.com": "uio",
    "uib.instructure.com": "uib",
    "uit.instructure.com": "uit",
    "uia.instructure.com": "uia",
    "nhh.instructure.com": "nhh",
    "oslomet.instructure.com": "hioa oslomet",
    "canvas.kth.se": "kth",
    "canvas.chalmers.se": "chalmers cth",
    "canvas.gu.se": "gu goteborg",
    "canvas.su.se": "su",
    "canvas.kau.se": "kau",
    "canvas.miun.se": "miun",
    "canvas.du.se": "du hda",
    "helsinki.instructure.com": "hy helsingin",
    "reykjavik.instructure.com": "hr ru",
    # Australia / NZ
    "canvas.lms.unimelb.edu.au": "unimelb",
    "canvas.sydney.edu.au": "usyd",
    "canvas.uts.edu.au": "uts",
    "canvas.anu.edu.au": "anu",
    "canvas.qut.edu.au": "qut",
    "learning.curtin.edu.au": "curtin",
    "myuni.adelaide.edu.au": "adelaide uofa",
    "canvas.auckland.ac.nz": "uoa auckland",
    # Philippines
    "ust.instructure.com": "ust santo tomas thomasian",
    "dlsu.instructure.com": "dlsu la salle",
    "ateneo.instructure.com": "admu ateneo",
    "feu.instructure.com": "feu",
    "tip.instructure.com": "tip",
    "mapua.instructure.com": "mapua",
    "ceu.instructure.com": "ceu",
    "sanbeda.instructure.com": "sanbeda",
    # Hong Kong / Asia
    "hku.instructure.com": "hku",
    "canvas.ust.hk": "hkust ust",
    "canvas.cityu.edu.hk": "cityu",
    "canvas.polyu.edu.hk": "polyu",
    "canvas.nus.edu.sg": "nus",
    # Africa / LatAm
    "ulwazi.wits.ac.za": "wits",
    "ashesi.instructure.com": "ashesi",
    "aucegypt.instructure.com": "auc",
    "cursos.canvas.uc.cl": "puc uc catolica",
    "usach.instructure.com": "usach",
    "unab-cl.instructure.com": "unab",
    "uandes.instructure.com": "uandes",
    "pucp.instructure.com": "pucp",
    "cientificavirtual.cientifica.edu.pe": "ucsur cientifica",
    "utpl.instructure.com": "utpl",
    "pucpr.instructure.com": "pucpr",
    "uva.instructure.com": "uva",
    # North America / UK
    "canvas.ubc.ca": "ubc",
    "q.utoronto.ca": "uoft utoronto",
    "canvas.harvard.edu": "harvard",
    "bruinlearn.ucla.edu": "ucla bruin",
    "webcourses.ucf.edu": "ucf",
    "canvas.ox.ac.uk": "oxon",
    "canvas.imperial.ac.uk": "icl imperial",
    "qmul.instructure.com": "qmul",
}


def folded_name(name: str) -> str:
    """The name as a keyboard without accents would type it, or ``""``.

    Shipped ONLY when it differs. Everything else the old blob carried - the
    name, the domain, the country code, the country's names - the bridge
    already has or can derive, and shipping it a second time inside a per-row
    string was half the payload.
    """
    f = fold(name)
    return "" if f == name.lower() else f


def aliases_of(row) -> str:
    """*row*'s search aliases, or ``""``.

    A SEPARATE payload field from the folded name, not one blob of "extra
    text", because the two are scored differently and must be: the folded name
    IS the name, so it feeds coverage and prefix matching, while an alias is an
    identity token that should never count as one of the name's own words.
    Merging them let "ku" and "ucph" dilute the coverage of "Kobenhavns
    Universitet" and rank it below rows the query barely touched.
    """
    return SEARCH_ALIASES.get(row[1], "")


def build_payload() -> str:
    """Every institution as one delimited string, for a single data attribute.

    **Memoised on the DATA ITSELF, not on nothing.** Building this folds, cleans
    and joins every one of the ~4,750 rows - and ``folded_name`` runs an NFKD
    normalisation plus a per-character combining-mark scan on each - which
    measured **17.4 ms**, paid again on EVERY rerun of the login page. That is
    the app's slowest screen and the one this list was already made smaller to
    protect, so recomputing a constant there is the one cost with no argument for
    it at all. Cached, ``picker_html()`` is 0.6 ms.

    The cache key is ``_inst.DATA`` rather than a bare ``lru_cache()`` because
    tests legitimately SWAP that tuple to drive this real function with a hostile
    or constructed row - which is exactly how the escaping and field-packing
    guarantees are proven. A zero-argument cache silently serves the shipped list
    to those tests instead, and the failure mode is the dangerous direction: a
    warm cache makes such a test pass against code that no longer escapes
    anything. Keying on the tuple makes a swap a cache MISS by construction, so
    no test needs to know this cache exists. ``DATA`` is a tuple of tuples and
    hashing it costs 0.04 ms, i.e. 400x less than the rebuild it skips.

    **Why not one button per institution.** That is what this shipped first,
    and at 274 entries it was fine. At 4,272 it is ~460 KB of markup that
    Streamlit re-sends and React re-parses on every rerun of the login page,
    plus 4,272 live DOM nodes for the bridge to toggle on every keystroke. The
    payload costs three DOM nodes and lets the bridge render only the rows a
    query actually matches.

    The data still comes from the SERVER, which is the part that matters: a
    components.html bridge runs once per mount and never again, so anything it
    invented would vanish the first time Streamlit re-rendered this markdown.
    Rendering *from* server-sent data on demand is safe; *being* the data is
    not.

    **FOUR fields, and the third one is why this is half the size it was.** The
    old format shipped ``name » domain » blob``, where the blob was
    ``"{name} {domain} {cc} {country names} {folded copy}"`` - so every row
    carried its own name and domain a SECOND time, inside a string only the
    search used. Measured on the 4,272-row list: 333 KB total, of which the
    blob was 169 KB (51%) and could be reassembled from the other two fields
    plus a country table sent ONCE. The fields are now:

        name » domain » cc+flags » folded-name-if-different

    which is 170 KB for the same data. That is not a micro-optimisation: this
    is the login page, the slowest screen in the app, and halving the payload
    is what pays for doubling the number of institutions in it.

    ``cc`` and the flags share one field because ``cc`` is exactly two
    characters or empty, so ``f.slice(0, 2)`` and ``f.slice(2)`` split it for
    free rather than costing another delimiter on every row.
    """
    return _build_payload(_inst.DATA)


@functools.lru_cache(maxsize=2)
def _build_payload(data) -> str:
    """The real builder. See :func:`build_payload` for why *data* is a parameter.

    ``maxsize=2`` so a test that swaps ``DATA`` and restores it does not evict
    the shipped list on the way back.
    """
    out = []
    for row in data:
        name, domain = row[0], row[1]
        out.append(_FS.join((
            _clean_field(name),
            domain.replace(_SUF, _SUF_TOKEN),
            # PADDED to two characters, always. Country is 2 letters or empty
            # and flags are letters too, so an unpadded join is ambiguous the
            # moment a row has a flag and no country: "" + "s" is "s", which
            # reads back as the country `s`. That row then matches no country
            # term, is excluded from every regional suggestion list, and asks
            # the country table for a label that does not exist. 19 rows were
            # in exactly that state when this was written.
            f"{row[2]:<2}" + row_flags(row),
            _clean_field(folded_name(name)),
            _clean_field(aliases_of(row)),
        )))
    return _RS.join(out)


def country_payload() -> str:
    """``CC»names«CC»names`` - the country table, sent ONCE for the whole list.

    Deliberately NOT memoised: it measured 0.1 ms, so a cache would buy nothing
    and would need the same swap-awareness :func:`build_payload` documents.

    It used to travel inside every row's search blob, which cost 8 KB of
    duplicated text and, far worse, made ``united states`` part of the haystack
    of all 220 US rows: measured, **194 of the 322 hits for the query `state`
    matched nothing but that phrase**, and 232 of 535 for `us`. The bridge now
    tests a query term against these as whole TOKENS, so `denmark` still finds
    Danish schools and `state` no longer pretends every US university is a
    match for a word in its country's name.
    """
    return _RS.join(f"{cc}{_FS}{names}{_FS}{COUNTRY_LABEL.get(cc, '')}"
                    for cc, names in sorted(COUNTRY_NAMES.items()))


def _clean_field(s: str) -> str:
    """Strip every character the payload format reserves.

    The suffix token joins the two delimiters here: a literal `*` arriving from
    an institution's name would be expanded into `.instructure.com` by the
    bridge and corrupt both the displayed name and the search haystack.
    """
    return s.replace(_FS, " ").replace(_RS, " ").replace(_SUF_TOKEN, " ")


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
        f" aria-label='Institutions' data-rows='{_he(build_payload())}'"
        f" data-cc='{_he(country_payload())}'></div>"
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

  // Escapes for BOTH element text and an attribute VALUE. The quotes matter:
  // `render()` builds `data-u='https://...'`, so an unescaped apostrophe would
  // close the attribute early. No shipped domain contains one today - which is
  // exactly the kind of fact that stops being true when someone adds a row, and
  // the failure would be markup corruption, not a visible error.
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
  // `.instructure.com` travels as a single `*` - a quarter of the payload was
  // that one string repeated. Expanded here so every consumer downstream sees
  // exactly what it saw before the compression: the rendered domain, the
  // https:// link and the haystack are byte-identical. Runs once per mount
  // (see the memo below), not per keystroke.
  var SUF = '.instructure.com', SUF_TOKEN = '*';
  function expand(s) { return s.indexOf(SUF_TOKEN) < 0 ? s : s.split(SUF_TOKEN).join(SUF); }
  // With results RANKED, 60 is generous: what the user wants is at the top, and
  // the count line says how much was left out. Unranked, this cap was the whole
  // problem - the list was ordered by country code, so 93% of it (every
  // `*.instructure.com` row, which has no ccTLD and therefore sorted last)
  // could not be reached by any query with more than 60 hits.
  var RENDER_CAP = 60;

  // Split into word-ish runs. Codes above 127 count as letters so that an
  // accented name is one word, not several.
  function words(s) {
    var out = [], cur = '';
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if ((c >= 97 && c <= 122) || (c >= 48 && c <= 57) || c > 127) cur += s.charAt(i);
      else if (cur) { out.push(cur); cur = ''; }
    }
    if (cur) out.push(cur);
    return out;
  }

  // *s* with a leading definite/indefinite article removed, else ''.
  var ART = ['the ', 'a ', 'an ', 'la ', 'le ', 'les ', 'el ', 'los ', 'las ',
             'de ', 'det ', 'den ', 'der ', 'die ', 'das ', 'het '];
  function article(s) {
    for (var i = 0; i < ART.length; i++) {
      if (s.indexOf(ART[i]) === 0) return s.slice(ART[i].length);
    }
    return '';
  }

  // Index of `t` at the START of a word in `hay`, else -1.
  //
  // This is the whole difference between "unsw" meaning the University of New
  // South Wales and "unsw" meaning br-UNSW-ick County Public Schools. Both are
  // still found - recall matters, because a mid-word hit is exactly what makes
  // `roskilde` find `vucroskilde` and `akademi` find `Erhvervsakademi` - but
  // only one of them is a plausible thing to have meant.
  function wordAt(hay, t) {
    var i = hay.indexOf(t);
    while (i >= 0) {
      if (i === 0) return i;
      var c = hay.charCodeAt(i - 1);
      if (!((c >= 97 && c <= 122) || (c >= 48 && c <= 57) || c > 127)) return i;
      i = hay.indexOf(t, i + 1);
    }
    return -1;
  }

  // The country table, sent once for the whole list rather than baked into
  // every row's haystack. Tokens are matched WHOLE (see `ccHit`).
  function ccNames() {
    var list = D.querySelector('.cd-inst-list');
    var raw = list ? (list.getAttribute('data-cc') || '') : '';
    if (reg.ccRaw === raw && reg.ccMap) return reg.ccMap;
    var m = {}, recs = raw ? raw.split(RS) : [];
    for (var i = 0; i < recs.length; i++) {
      var f = recs[i].split(FS);
      if (f.length >= 3) m[f[0]] = { t: f[1].split(' '), label: f[2] };
    }
    reg.ccRaw = raw; reg.ccMap = m;
    return m;
  }

  function ccLabel(cc) {
    var e = ccNames()[cc];
    return e ? e.label : '';
  }

  function rows() {
    var list = D.querySelector('.cd-inst-list');
    if (!list) return [];
    var raw = list.getAttribute('data-rows') || '';
    if (reg.raw === raw && reg.rows) return reg.rows;
    var cc = ccNames(), out = [], recs = raw ? raw.split(RS) : [];
    for (var i = 0; i < recs.length; i++) {
      var f = recs[i].split(FS);
      if (f.length < 3) continue;
      var name = f[0], domain = expand(f[1]);
      // The country is space-padded to two characters by `build_payload`, so
      // the split is fixed-width and a flag can never be read as a country.
      var meta = f[2] || '', code = meta.slice(0, 2).replace(/ /g, '');
      var nl = name.toLowerCase(), nf = f[3] || '', al = f[4] || '';
      out.push({
        name: name, domain: domain, cc: code,
        seed: meta.slice(2).indexOf('s') >= 0,
        nl: nl,
        // The accent-folded name, present ONLY when it differs - so the
        // common row costs one null check rather than a second haystack.
        n2: (nf && nf !== nl) ? nf : null,
        // The name with a leading article removed, for the PREFIX test only.
        // Canvas accounts are titled inconsistently - "The University of
        // Melbourne" beside "University of Sydney" - and without this the
        // article alone decided the ranking: measured, `melbourne` answered
        // with Melbourne Grammar School, because a name that merely STARTS
        // with the word beat the university whose name is the word preceded
        // by "The".
        na: article(nl),
        dl: domain.toLowerCase(),
        labs: domain.toLowerCase().split('.'),
        // Precomputed at parse time, not per keystroke: coverage is scored for
        // every matching row, and splitting thousands of names on every letter
        // typed is the kind of cost that turns an instant list into a laggy one.
        w: words(nf || nl),
        // What students CALL this school. Scored like a domain label, never
        // like a word of the name - see `aliases_of` in the Python module.
        at: al ? al.split(' ') : null,
        ct: (cc[code] && cc[code].t) || null
      });
    }
    reg.raw = raw; reg.rows = out;
    return out;
  }

  // ── Ranking ───────────────────────────────────────────────────────────
  // The picker used to have NO ranking: it filtered, and returned rows in the
  // order the generated module happened to list them, which is (country code,
  // name). Measured in the running app before this existed - `harvard` put
  // "Harvard Medical School Pre-Med Online Certificate Program" above Harvard
  // University, `oxford` led with "Said Business School", and `singapore` with
  // "National Institute of Early Childhood Development". Each of those is a
  // real institution and a real match; none of them is what was meant.
  //
  // The weights are ordinal, not tuned: what matters is that a whole-name hit
  // beats a name prefix, which beats a word inside the name, which beats a
  // fragment inside a word, which beats the domain, which beats "your country
  // is called this". Everything else is a bonus small enough that it can order
  // near-equals without ever promoting a worse text match.
  var S_EXACT = 100, S_PREFIX = 62, S_WORD = 44, S_MID = 16;
  // S_DLAB sits ABOVE a name prefix on purpose. A whole domain LABEL equal to
  // the whole query is an institution stating its own identity in four
  // characters, and typing that acronym is how people who know their school
  // look it up - `ust`, `cbs`, `ubc`, `unsw`, `tip`. Measured with it below
  // the prefix score: `ust` answered with "UST Angelicum College" over the
  // University of Santo Tomas on `ust.instructure.com`, and `tip` with
  // "Tippecanoe School District" over the Technological Institute of the
  // Philippines on `tip.instructure.com` - in both cases beaten by a name
  // that merely begins with the same three letters.
  var S_DLAB = 66, S_DPRE = 30, S_DMID = 9, S_SYN = 11, S_CC = 8;
  var B_COVERAGE = 30, B_SEED = 24, B_HOME = 22, P_SUBTENANT = 10;

  // Education words across the languages this app is actually used in. They
  // say what KIND of place a school is, never which one, so they score low -
  // but without them "university of sao paulo" cannot find "Universidade de
  // São Paulo", and a Dane's "universitet" cannot find an English-named row.
  var SYN = [
    ['university', 'universitet', 'universitetet', 'universiteit', 'universidad',
     'universidade', 'universita', 'universitat', 'universite', 'universiti',
     'universitas', 'uniwersytet', 'universitatea', 'univerzita', 'univerza',
     'yliopisto', 'haskoli', 'haskolinn', 'egyetem', 'uniwersytet'],
    ['college', 'colegio', 'collegio', 'kolleg', 'faculdade', 'facultad',
     'faculty', 'hogskolan', 'hogskola', 'hogskole', 'hojskole', 'korkeakoulu'],
    ['school', 'skole', 'skola', 'skolan', 'skolen', 'schule', 'escuela',
     'escola', 'ecole', 'scuola', 'koulu', 'okul'],
    ['institute', 'instituto', 'institut', 'istituto', 'instituut', 'institutet'],
    ['academy', 'akademi', 'akademie', 'academia', 'accademia', 'akademia'],
    ['polytechnic', 'politecnico', 'politecnica', 'polytechnique', 'polyteknisk'],
    ['technology', 'teknik', 'tecnologia', 'tecnologico', 'teknologi',
     'technische', 'tekniska', 'tekniske', 'teknillinen']
  ];

  // Only for a term of 4+ characters that PREFIXES a known form. Below that a
  // term like "uni" prefixes half the table and the expansion says nothing.
  function alts(t) {
    if (t.length < 4) return null;
    for (var g = 0; g < SYN.length; g++) {
      for (var k = 0; k < SYN[g].length; k++) {
        if (SYN[g][k].indexOf(t) === 0) return SYN[g];
      }
    }
    return null;
  }

  // A country name matches as a WHOLE token. Prefixes were tried and are wrong:
  // "state" prefixes "states", so every US row matched the query `state` - 194
  // of its 322 hits were that and nothing else.
  function ccHit(r, t) {
    if (!r.ct) return false;
    for (var i = 0; i < r.ct.length; i++) { if (r.ct[i] === t) return true; }
    return false;
  }

  // A domain that is one institution's side entrance rather than its Canvas.
  // Note the ABSENCE of 'college' and 'health': those name real institutions,
  // and getting a sub-unit off the top of the list is the builder's job (it
  // decides which domain an institution IS), not the search's.
  var SUBT = ['continuing', 'conted', 'workforce', 'execed', 'executive',
              'alumni', 'catalog', 'summer', 'sandbox', 'training',
              'precollege', 'pre-college', 'parents', 'observer', 'online'];
  function subtenant(dl) {
    for (var i = 0; i < SUBT.length; i++) { if (dl.indexOf(SUBT[i]) >= 0) return true; }
    return false;
  }

  function termScore(r, t, alt) {
    var best = 0, k, h;
    for (k = 0; k < 2; k++) {
      h = k ? r.n2 : r.nl;
      if (!h) continue;
      if (h === t) { best = S_EXACT; break; }
      if (h.indexOf(t) === 0) { if (S_PREFIX > best) best = S_PREFIX; }
      else if (wordAt(h, t) >= 0) { if (S_WORD > best) best = S_WORD; }
      else if (h.indexOf(t) >= 0) { if (S_MID > best) best = S_MID; }
    }
    if (best < S_EXACT && r.na) {
      if (r.na === t) best = S_EXACT;
      else if (r.na.indexOf(t) === 0 && S_PREFIX > best) best = S_PREFIX;
    }
    // The domain is checked even when the name already scored: a bare host
    // label ("ubc", "cbs") is a stronger statement of identity than the same
    // letters buried inside a word of the name.
    for (k = 0; k < r.labs.length; k++) {
      if (r.labs[k] === t) { if (S_DLAB > best) best = S_DLAB; break; }
      if (r.labs[k].indexOf(t) === 0 && S_DPRE > best) best = S_DPRE;
    }
    if (r.at) {
      for (k = 0; k < r.at.length; k++) {
        if (r.at[k] === t) { if (S_DLAB > best) best = S_DLAB; break; }
        if (r.at[k].indexOf(t) === 0 && S_DPRE > best) best = S_DPRE;
      }
    }
    if (!best && r.dl.indexOf(t) >= 0) best = S_DMID;
    if (!best && alt) {
      for (k = 0; k < alt.length; k++) {
        if (alt[k] !== t && (wordAt(r.nl, alt[k]) >= 0
                             || (r.n2 && wordAt(r.n2, alt[k]) >= 0))) { best = S_SYN; break; }
      }
    }
    if (!best && ccHit(r, t)) best = S_CC;
    return best;
  }

  function score(r, terms, altv, home) {
    var tot = 0, i, j, s;
    for (i = 0; i < terms.length; i++) {
      s = termScore(r, terms[i], altv[i]);
      if (!s) return -1;               // every term must match SOMETHING
      tot += s;
    }
    // How much of this name the query accounted for. One signal, and it is the
    // one that separates "Harvard University" from "Harvard Medical School
    // Pre-Med Online Certificate Program": both contain the word, one of them
    // very nearly IS the word.
    var hit = 0;
    for (i = 0; i < r.w.length; i++) {
      for (j = 0; j < terms.length; j++) {
        if (r.w[i].indexOf(terms[j]) === 0) { hit++; break; }
      }
    }
    if (r.w.length) tot += B_COVERAGE * (hit / r.w.length);
    // Curated seeds are the institutions a lot of people are looking for. This
    // is NOT a level preference - a school district typing its own name wins on
    // coverage and exactness long before this matters - it is the only signal
    // available for "many users mean this one", and without it `melbourne` puts
    // Melbourne Business School above the University of Melbourne purely
    // because its name starts with the word.
    if (r.seed) tot += B_SEED;
    if (home && r.cc === home) tot += B_HOME;
    if (subtenant(r.dl)) tot -= P_SUBTENANT;
    return tot;
  }

  // The user's country, from the device and nothing else - no request is made
  // and nothing is stored. The TIME ZONE is asked first on purpose: it reports
  // where the machine is, whereas the UI language is a preference, and an
  // English-language Windows is the norm across most of this app's markets. A
  // Filipino student running en-US Windows is in Asia/Manila.
  var TZ_CC = {
    'Africa/Cairo': 'EG', 'Africa/Johannesburg': 'ZA', 'Africa/Lagos': 'NG',
    'Africa/Accra': 'GH', 'Africa/Nairobi': 'KE', 'Africa/Kampala': 'UG',
    'Africa/Dar_es_Salaam': 'TZ', 'Africa/Lusaka': 'ZM', 'Africa/Harare': 'ZW',
    'Africa/Gaborone': 'BW', 'Africa/Windhoek': 'NA', 'Africa/Kigali': 'RW',
    'Africa/Casablanca': 'MA', 'Africa/Tunis': 'TN', 'Africa/Algiers': 'DZ',
    'Africa/Addis_Ababa': 'ET', 'Africa/Dakar': 'SN', 'Africa/Abidjan': 'CI',
    'Africa/Douala': 'CM', 'Africa/Maputo': 'MZ', 'Africa/Blantyre': 'MW',
    'Africa/Khartoum': 'SD', 'Africa/Luanda': 'AO', 'Indian/Mauritius': 'MU',
    'Asia/Manila': 'PH', 'Asia/Kolkata': 'IN', 'Asia/Calcutta': 'IN',
    'Asia/Tokyo': 'JP', 'Asia/Seoul': 'KR', 'Asia/Shanghai': 'CN',
    'Asia/Hong_Kong': 'HK', 'Asia/Taipei': 'TW', 'Asia/Singapore': 'SG',
    'Asia/Kuala_Lumpur': 'MY', 'Asia/Jakarta': 'ID', 'Asia/Bangkok': 'TH',
    'Asia/Ho_Chi_Minh': 'VN', 'Asia/Saigon': 'VN', 'Asia/Dhaka': 'BD',
    'Asia/Karachi': 'PK', 'Asia/Colombo': 'LK', 'Asia/Kathmandu': 'NP',
    'Asia/Yangon': 'MM', 'Asia/Phnom_Penh': 'KH', 'Asia/Dubai': 'AE',
    'Asia/Riyadh': 'SA', 'Asia/Qatar': 'QA', 'Asia/Kuwait': 'KW',
    'Asia/Bahrain': 'BH', 'Asia/Muscat': 'OM', 'Asia/Amman': 'JO',
    'Asia/Beirut': 'LB', 'Asia/Jerusalem': 'IL', 'Asia/Tel_Aviv': 'IL',
    'Asia/Istanbul': 'TR', 'Europe/Istanbul': 'TR', 'Asia/Baghdad': 'IQ',
    'Asia/Tehran': 'IR', 'Asia/Almaty': 'KZ', 'Asia/Tashkent': 'UZ',
    'Europe/Copenhagen': 'DK', 'Europe/Oslo': 'NO', 'Europe/Stockholm': 'SE',
    'Europe/Helsinki': 'FI', 'Atlantic/Reykjavik': 'IS', 'Europe/London': 'GB',
    'Europe/Dublin': 'IE', 'Europe/Amsterdam': 'NL', 'Europe/Brussels': 'BE',
    'Europe/Berlin': 'DE', 'Europe/Vienna': 'AT', 'Europe/Zurich': 'CH',
    'Europe/Paris': 'FR', 'Europe/Madrid': 'ES', 'Europe/Lisbon': 'PT',
    'Europe/Rome': 'IT', 'Europe/Warsaw': 'PL', 'Europe/Prague': 'CZ',
    'Europe/Budapest': 'HU', 'Europe/Bucharest': 'RO', 'Europe/Sofia': 'BG',
    'Europe/Athens': 'GR', 'Europe/Ljubljana': 'SI', 'Europe/Zagreb': 'HR',
    'Europe/Belgrade': 'RS', 'Europe/Bratislava': 'SK', 'Europe/Kiev': 'UA',
    'Europe/Kyiv': 'UA', 'Europe/Tallinn': 'EE', 'Europe/Riga': 'LV',
    'Europe/Vilnius': 'LT', 'Europe/Luxembourg': 'LU', 'Europe/Malta': 'MT',
    'Asia/Nicosia': 'CY', 'Europe/Skopje': 'MK', 'Europe/Tirane': 'AL',
    'Europe/Sarajevo': 'BA', 'Europe/Podgorica': 'ME',
    'America/New_York': 'US', 'America/Chicago': 'US', 'America/Denver': 'US',
    'America/Los_Angeles': 'US', 'America/Phoenix': 'US', 'America/Anchorage': 'US',
    'America/Detroit': 'US', 'America/Indiana/Indianapolis': 'US',
    'Pacific/Honolulu': 'US', 'America/Puerto_Rico': 'PR',
    'America/Toronto': 'CA', 'America/Vancouver': 'CA', 'America/Edmonton': 'CA',
    'America/Winnipeg': 'CA', 'America/Halifax': 'CA', 'America/Montreal': 'CA',
    'America/Mexico_City': 'MX', 'America/Monterrey': 'MX',
    'America/Sao_Paulo': 'BR', 'America/Bahia': 'BR', 'America/Fortaleza': 'BR',
    'America/Recife': 'BR', 'America/Manaus': 'BR',
    'America/Santiago': 'CL', 'America/Lima': 'PE', 'America/Bogota': 'CO',
    'America/Guayaquil': 'EC', 'America/Caracas': 'VE', 'America/La_Paz': 'BO',
    'America/Asuncion': 'PY', 'America/Montevideo': 'UY',
    'America/Argentina/Buenos_Aires': 'AR', 'America/Buenos_Aires': 'AR',
    'America/Costa_Rica': 'CR', 'America/Panama': 'PA', 'America/Guatemala': 'GT',
    'America/Tegucigalpa': 'HN', 'America/El_Salvador': 'SV',
    'America/Managua': 'NI', 'America/Santo_Domingo': 'DO',
    'America/Port-au-Prince': 'HT', 'America/Jamaica': 'JM', 'America/Havana': 'CU',
    'America/Belize': 'BZ', 'America/Paramaribo': 'SR', 'America/Guyana': 'GY',
    'Australia/Sydney': 'AU', 'Australia/Melbourne': 'AU', 'Australia/Brisbane': 'AU',
    'Australia/Perth': 'AU', 'Australia/Adelaide': 'AU', 'Australia/Hobart': 'AU',
    'Australia/Darwin': 'AU', 'Australia/Canberra': 'AU',
    'Pacific/Auckland': 'NZ', 'Pacific/Fiji': 'FJ', 'Pacific/Port_Moresby': 'PG',
    'Pacific/Guam': 'GU', 'Pacific/Pago_Pago': 'AS'
  };

  function homeCC() {
    if (typeof reg.home === 'string') return reg.home;
    var out = '';
    try {
      var tz = (P.Intl && P.Intl.DateTimeFormat)
        ? P.Intl.DateTimeFormat().resolvedOptions().timeZone : '';
      if (tz && TZ_CC[tz]) out = TZ_CC[tz];
    } catch (e) {}
    if (!out) {
      var langs = (P.navigator && P.navigator.languages)
        || [(P.navigator && P.navigator.language) || ''];
      for (var i = 0; i < langs.length && !out; i++) {
        var parts = String(langs[i] || '').replace('_', '-').split('-');
        var tail = parts[parts.length - 1];
        // Only a 2-letter REGION subtag; 'da' alone says nothing about where.
        if (parts.length > 1 && tail.length === 2) out = tail.toUpperCase();
      }
    }
    reg.home = out;
    return out;
  }

  // What to show before a single key is pressed.
  //
  // This used to be `all` sliced to 60, i.e. the first 60 rows of a list
  // ordered by country code - so the picker opened on the United Arab Emirates
  // and Australia for everybody on earth. It is the first thing a new user sees
  // of this app's most important screen, and it was noise.
  function defaults(home) {
    var all = rows(), out = [], i;
    if (home) {
      for (i = 0; i < all.length; i++) { if (all[i].cc === home) out.push(all[i]); }
    }
    // Too thin to be worth a heading - fall back to the curated institutions,
    // which is a better "here is what this is" than an alphabetical slice.
    if (out.length < 5) {
      out = [];
      for (i = 0; i < all.length; i++) { if (all[i].seed) out.push(all[i]); }
      if (!out.length) out = all.slice(0, RENDER_CAP);
      return { rows: out, home: '' };
    }
    out.sort(function (a, b) {
      if (a.seed !== b.seed) return a.seed ? -1 : 1;
      return a.nl < b.nl ? -1 : (a.nl > b.nl ? 1 : 0);
    });
    return { rows: out, home: home };
  }

  function matches(q) {
    var all = rows();
    q = (q || '').trim().toLowerCase();
    if (!q) return null;               // caller uses `defaults()` instead
    // Every whitespace-separated term must match, so "melb uni" finds "The
    // University of Melbourne" where a single substring test would not.
    var terms = q.split(/\\s+/), altv = [], out = [], i, sc;
    for (i = 0; i < terms.length; i++) altv.push(alts(terms[i]));
    var home = homeCC();
    for (i = 0; i < all.length; i++) {
      sc = score(all[i], terms, altv, home);
      if (sc >= 0) out.push([sc, all[i]]);
    }
    out.sort(function (a, b) {
      if (b[0] !== a[0]) return b[0] - a[0];
      // A stable, meaningful tie-break: the shorter name is the less qualified
      // one, and the less qualified one is the institution itself.
      if (a[1].name.length !== b[1].name.length) return a[1].name.length - b[1].name.length;
      return a[1].nl < b[1].nl ? -1 : 1;
    });
    var res = [];
    for (i = 0; i < out.length; i++) res.push(out[i][1]);
    return res;
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

  // Match on the RAW text, escape each piece afterwards.
  //
  // The order is the whole point. Escaping first and then matching searches the
  // ESCAPED string, so a query containing `&` matches inside the `&amp;` that
  // escaping just produced and splices a <mark> into the middle of an entity -
  // `<mark>&</mark>amp;` renders as literal "&amp;" in an institution's name.
  // Matching first also means a term is highlighted where the user actually
  // sees it, since `matches()` searched the raw text too.
  function mark(text, re) {
    text = String(text);
    if (!re) return esc(text);
    re.lastIndex = 0;
    var out = '', last = 0, m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out += esc(text.slice(last, m.index));
      out += '<mark>' + esc(m[0]) + '</mark>';
      last = m.index + m[0].length;
      if (m[0].length === 0) re.lastIndex++;   // a zero-width match would spin
    }
    return out + esc(text.slice(last));
  }

  function nfmt(n) { return String(n).replace(/\\B(?=(\\d{3})+(?!\\d))/g, ','); }

  function render() {
    var r = root(); if (!r) return;
    var list = r.querySelector('.cd-inst-list');
    var meta = r.querySelector('.cd-inst-meta');
    var s = r.querySelector('.cd-inst-input');
    var q = (s && s.value) || '';
    var terms = q.trim() ? q.trim().toLowerCase().split(/\\s+/) : [];
    var hits = matches(q), suggested = null;
    if (hits === null) { suggested = defaults(homeCC()); hits = suggested.rows; }
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
      var total = rows().length;
      if (suggested) {
        // Before anything is typed the count is not news - what the line has to
        // do is explain why THESE rows are the ones on screen, and say that the
        // rest are one keystroke away.
        var label = suggested.home ? ccLabel(suggested.home) : '';
        meta.textContent = label
          ? 'Institutions in ' + label + ' - or type to search all ' + nfmt(total)
          : 'Type to search ' + nfmt(total) + ' institutions';
      } else {
        meta.textContent = !hits.length ? ''
          : (hits.length > show.length
               ? 'Best ' + show.length + ' of ' + nfmt(hits.length) + ' matches - keep typing to narrow'
               : hits.length + (hits.length === 1 ? ' match' : ' matches'));
      }
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
