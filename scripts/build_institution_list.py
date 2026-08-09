"""Regenerate ``shared/institutions.py`` - the login picker's bundled directory.

    python scripts/build_institution_list.py                 # full rebuild
    python scripts/build_institution_list.py --limit 500     # a bigger list
    python scripts/build_institution_list.py --dry-run       # report, write nothing
    python scripts/build_institution_list.py --cache crawl.json   # skip the crawl

NOT bundled in the app - this is build/maintenance tooling like everything else
in ``scripts/``. The app never talks to Instructure's finder: that would put a
network round-trip on the login path and make a first run depend on a service
this project does not own. The whole point is to pay that cost HERE, once, and
ship a verified static list.

──────────────────────────────────────────────────────────────────────────────
THE PIPELINE
──────────────────────────────────────────────────────────────────────────────
1. CRAWL   Instructure publishes an account finder, and paginating it across
           every letter and digit yields the complete set of accounts that
           opted into discovery (~7,200 as of 2026-08). That set is the hard
           ceiling: anything not in it cannot be verified, and plenty of large
           universities simply are not there (most IITs, most Japanese
           universities). A seed finding nothing is a correct outcome.

2. MATCH   ``scripts/institution_seeds.py`` (well-known institutions per
           country) is matched against the crawl to give the biggest names a
           clean, consistent DISPLAY name - Canvas account names are wildly
           inconsistent ("The University of Melbourne (non-SSO)"). See the
           four gates below; they exist because the first version of this
           script shipped wrong-university pairings.

3. FILL    The rest of the list is taken from the crawl directly, each account
           under its OWN name and OWN domain. This carries **no pairing risk
           at all** - nothing is being mapped to anything - so the only filters
           needed are "is this higher education" and "is it a real tenant".

4. VERIFY  Every surviving domain must answer ``/api/v1/users/self`` with
           Canvas's own unauthenticated payload. A parked domain, a marketing
           site and an SSO portal all answer an ordinary request, so
           "it responded" is not evidence.

5. REJECT  ``scripts/institution_rejects.py`` is the hand-review gate for
           same-name collisions no heuristic can settle.

──────────────────────────────────────────────────────────────────────────────
WHY THE MATCH GATES LOOK LIKE THIS - each fixed a measured failure
──────────────────────────────────────────────────────────────────────────────
* **Score symmetrically (Jaccard).** v1 scored one-way RECALL of the seed's
  tokens, so any account merely CONTAINING the seed's distinctive word scored
  1.00. It paired KTH with RMIT Melbourne, Korea University with Yamaha Music
  Korea, and Cairo University with the American University in Cairo.

* **Do not stop "college", "state" or "university".** They are DISCRIMINATING
  in higher education. With them stopped, "University of Florida" and "Florida
  College" both reduce to {florida} and score 1.00 - which is how a later
  version paired Boston University with Boston College, UC Berkeley with
  Berkeley College, and the University of Miami with Miami University (Ohio).

* **Require the DOMAIN to corroborate**, by whole-label equality or prefix -
  never substring, since "jesuit" contains "uit" and would vouch for UiT Norway
  on six unrelated high schools. Note the LMS-affix stripping: institutions
  fuse the LMS word into one label ('cbscanvas'), and without the stripped
  variant Copenhagen Business School's own domain fails to corroborate its own
  perfectly-matching name.

* **Veto a contradicting ccTLD.** This is the only gate that rejects "Open
  University" (GB) matching "UTS Open" on ``canvas.open.uts.edu.au``: the names
  genuinely share their one distinctive token, so nothing name-based separates
  them.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import string
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from institution_seeds import SEEDS, LOCAL_NAMES          # noqa: E402
from institution_rejects import REJECT, REJECT_DOMAINS, RENAME  # noqa: E402

FINDER = "https://canvas.instructure.com/api/v1/accounts/search"
UA = {"User-Agent": "Mozilla/5.0 (CanvasDownloader institution-list builder)"}
OUT = _ROOT / "shared" / "institutions.py"

# ── Vocabulary ───────────────────────────────────────────────────────────────
# ONLY articles and prepositions. See the header for why nothing else may go in.
_STOP = {"the", "of", "at", "and", "for", "in", "de", "del", "la", "el", "des", "y"}

# Words too generic to CORROBORATE a domain on their own (otherwise every
# university domain is vouched for by the word "university").
_GENERIC = {"university", "universitat", "universitet", "universiteit", "universidad",
            "universidade", "universite", "universiti", "universitas", "college",
            "school", "institute", "institution", "state", "national", "technology",
            "science", "sciences", "business", "online", "academy", "polytechnic",
            # Honorifics. 'Royal' identifies nobody: KTH publishes as "KTH" and
            # its seed is "KTH Royal Institute of Technology", so counting it as
            # a distinguishing token makes an institution contradict ITSELF.
            "royal", "pontificia", "pontifical",
            # LMS words. An account routinely publishes as "UBC Canvas" or
            # "Chalmers LMS"; the platform's own name identifies nobody.
            "canvas", "lms", "learning", "learn", "moodle", "portal"}

# Non-production or adjacent tenants of a real institution. Matching one sends a
# student to a Canvas holding none of their courses, with nothing on screen
# suggesting the address was the problem.
_BAD_ACCOUNT = re.compile(
    r"\b(non-sso|nonsso|dev|test|testing|sandbox|beta|demo|training|trial|archive|"
    r"archived|old|legacy|staging|stage|qa|practice|template|sample|catalog|guest|"
    # A pre-college / visiting-student tenant is a real programme, but it is
    # not the university, and it can OUTRANK the university's own account:
    # measured, `app.opvs.georgetown.edu` ("Georgetown University - Pre-College
    # & Visiting Student Programs") beat `georgetown.instructure.com` on ccTLD
    # alone and then evicted it in the dedupe. The FILL blocklist has excluded
    # `pre-college` since it existed; the SEED pool never did.
    r"pre[- ]?college|visiting student|"
    r"alumni|athletics|bulldogs|parents|k-?12|extension|continuing|summer|pilot|"
    r"executive|exec ed|bookstore|conference|camp|canvascon|isd|county|district|"
    r"high school|public schools|academy)\b", re.I)

# ── The FILL gate: is this account an educational institution? ───────────────
#
# THIS IS NOT A LEVEL FILTER, and it used to be one. The app is for every
# institution and every level that uses Canvas - erhvervsakademier, VUC,
# gymnasier, konservatorier, K-12 districts - not only universities (confirmed
# with the product owner 2026-08-09). The old `_HIGHER_ED` allowlist named only
# English, Spanish, Portuguese and German higher-ed words, so it silently
# excluded two whole categories at once:
#
#   * every non-university institution, whatever its language; and
#   * every institution whose own published name is not in one of those four
#     languages - which is most of the Nordic market. Measured: Denmark shipped
#     TWO entries (KU and CBS, both rescued by SEEDS) while Erhvervsakademi
#     Aarhus, Den Danske Filmskole, VUC Roskilde, Det Kgl. Danske
#     Musikkonservatorium and IBA all verified as live Canvas hosts and were
#     dropped on the word gate alone. The same regex loses the Norwegian
#     "Hogskolen" family and the Finnish "korkeakoulu" family entirely.
#
# WHY WIDENING THIS IS SAFE, and the reason it is the fill gate that moved and
# not `_BAD_ACCOUNT`: the two paths in `build()` have completely different risk.
# The SEED path PAIRS a curated name with some account's domain, and that is
# where a wrong university comes from - the ten shipped in 2026-08-08 all came
# from there. The FILL path maps an account's OWN published name onto its OWN
# domain; there is nothing to mispair, by construction. `_BAD_ACCOUNT`, which
# gates the seed pool, is deliberately UNTOUCHED, so no seed pairing can change
# because of anything here. `tests/test_institution_gate.py` pins that.
#
# Matching is done on an accent-FOLDED name so the table can be written in
# plain ASCII: "Universitetet", "Universitat" and "Universite" are one entry.
# Nordic and German compounds are matched as substrings without a leading word
# boundary on purpose - "Erhvervsakademi" and "Fachhochschule" carry the
# education word in the middle of a single token, so \b would reject them.
_EDUCATION = re.compile(
    # --- English and international --------------------------------------
    r"\buniversit\w*|\bcolleges?\b|\bschools?\b|\bschooling\b|"
    r"\binstitutes?\b|\bpolytechnics?\b|\bseminary\b|\bconservator\w*|"
    r"\bacadem(?:y|ies|ia|ie)\b|\bcampus\b|\bfacult(?:y|ies)\b|"
    r"\beducation(?:al)?\b|\bk-?12\b|\bisd\b|\bschool district\b|"
    r"\b(?:high|middle|elementary|primary|secondary|grammar|charter)\b|"
    r"\bpreparatory\b|\bprep\b|\bmontessori\b|\bgymnasium\b|\blyce(?:e|um)\b|"
    # US school-district and secondary shorthand, from a review of what the
    # allowlist still rejected: "Madera Unified", "Oyster Bay-East Norwich
    # CSD", "Uvalde CISD", "Life Skills HS" and "Warren County Career Center"
    # are all real schools carrying no spelled-out education word.
    r"\bunified\b|\b(?:c|u|ci|uf)?sd\b|\bhs\b|"
    r"\bcareer (?:center|centre|technical)\b|\byeshiva\w*|\bmadrasa\w*|"
    # --- Nordic (da / no / sv / is / fi) ---------------------------------
    r"universitet\w*|hogskol\w*|hoyskol\w*|hojskol\w*|"
    r"\w*skole\w*|\w*skola\w*|\w*skolan\b|\w*skolen\b|"
    r"gymnasie\w*|\w*akademi\w*|"
    r"konservatori\w*|larosate\w*|laereanstalt\w*|videregaende\w*|"
    r"yliopisto\w*|korkeakoulu\w*|\bkoulu\w*|\blukio\w*|"
    r"haskol\w*|menntaskol\w*|\bvuc\b|"
    # --- German / Dutch --------------------------------------------------
    r"hochschul\w*|\w*schule\w*|berufskolleg\w*|universiteit\w*|"
    r"hogeschool\w*|onderwijs\w*|"
    # --- Romance ---------------------------------------------------------
    r"universidad\w*|universidade\w*|universita\w*|"
    r"escuela\w*|escola\w*|\bcolegi\w*|instituto\w*|"
    r"\binstitut\b|facultad\w*|faculdade\w*|\becole\w*|\bscuola\w*|"
    r"\bliceo\w*|accademia\w*",
    re.I)

# Things that are NOT an institution, or are a SUB-TENANT of one.
#
# This is the surviving half of the old `_NOT_HIGHER_ED`. Everything in it is
# here because it is not a school at all (a church, a vendor, a hospital, a
# corporate training portal) or because it is one school's side entrance
# (alumni, catalog, continuing education, athletics, a sandbox). The LEVEL words
# that used to sit here - high school, secondary, primary, elementary, middle
# school, academy, grammar, charter, k-12, prep, montessori, isd, district,
# county, public schools, boys, girls, junior high - are gone, because those are
# now exactly the institutions we are trying to include.
#
# `seminary` and `bible college` are likewise gone: a theological college is a
# real institution whose students have Canvas courses. `church` and `ministry`
# stay - those are congregations, not schools.
_NOT_AN_INSTITUTION = re.compile(
    r"\b(sandbox|test|testing|dev|demo|training|catalog|guest|alumni|athletics|"
    r"parents|conference|camp|bootcamp|church|ministry|hospital|clinic|"
    r"inc\.?|llc|corp|daycare|driving|beauty|barber|massage|yoga|dance|"
    r"tutoring|press|credentials|continuing education|continuing studies|"
    r"executive education|staff and students|corporate|partners|vendor|"
    r"pre-?college|professional development|micro-?credential|mooc)\b", re.I)


def fold(s: str) -> str:
    """Accent-folded lowercase, so one ASCII table matches every spelling.

    o-slash and ae are not accented forms of anything, so NFKD leaves them
    alone and they need an explicit map - the same trap `search_blob` in
    ui/institution_picker.py documents for the search haystack.
    """
    s = (s.replace("\u00f8", "o").replace("\u00d8", "O")
          .replace("\u00e6", "ae").replace("\u00c6", "AE")
          .replace("\u00e5", "a").replace("\u00c5", "A")
          .replace("\u00df", "ss"))
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c)).lower()


# An ACADEMIC top-level domain is proof on its own. `.edu` is restricted to
# accredited US institutions, and the `ac.*` / `edu.*` / `sch.*` / `k12.*`
# namespaces are their national equivalents - so a tenant there is a school
# whatever it chose to call itself. This is what reaches the accounts published
# only as an acronym, which no word list can express: measured on the crawl,
# 2,194 accounts carry no education word at all, and among them are real
# institutions like NJIT, XLRI and VMI beside genuine non-schools like Hubspot
# and a medical-software vendor. The TLD separates those two groups without
# needing to guess from the name.
_ACADEMIC_TLD = re.compile(
    r"\.edu$|\.edu\.[a-z]{2}$|\.ac\.[a-z]{2}$|\.sch\.[a-z]{2}$|\.k12\.[a-z]{2}\.us$",
    re.I)


def is_institution(name: str, domain: str) -> bool:
    """The whole FILL gate, in one place so the audit script can reuse it."""
    n, d = fold(name), fold(domain)
    if not (_EDUCATION.search(n) or _ACADEMIC_TLD.search(d)):
        return False
    return not (_NOT_AN_INSTITUTION.search(n) or _NOT_AN_INSTITUTION.search(d))


# Institutions published in the local language or as an acronym sharing no
# tokens with the English seed. Confirmed by hand against the crawl. Keep short
# and evidenced: an alias bypasses the name gate.
ALIASES: dict[str, list[str]] = {
    "University of Copenhagen": ["UCPH", "Absalon"],
    "UiT The Arctic University of Norway": ["UiT Norges arktiske universitet"],
    # A REORDERED initialism, which `acronyms()` cannot reach: the seed reads
    # "University of Hong Kong" and its in-order initials are UHK, but the
    # school is universally HKU and its tenant publishes as exactly "HKU" on
    # `hku.instructure.com`. Without the alias `contradicts()` correctly reads
    # "hku" as a distinctive token the seed lacks and vetoes the pairing - and
    # because the account name carries no education word, the FILL path cannot
    # rescue it either. Measured 2026-08-09: the seed then settled on
    # `canvas.cityu.edu.hk`, i.e. City University of Hong Kong, a different
    # university; that row was won back by CityU's own seed, so the visible
    # symptom was not a wrong label but the University of Hong Kong being
    # ABSENT from the picker entirely. Do NOT "fix" this by permuting initials
    # in `acronyms()` - that widens every seed's reach at once.
    "University of Hong Kong": ["HKU"],
    # Same reordered-initialism trap, same city. The main Clear Water Bay
    # campus publishes only as "HKUST" on `canvas.ust.hk`, so it has almost no
    # token overlap with the seed, while the Guangzhou campus publishes the
    # full name and won on overlap alone. See RENAME for the other half.
    # "UST" is here for the TIEBREAK, not for the name match. With "HKUST"
    # alone both campuses score a full 1.00 on overlap, and the next key is
    # corroboration - which the Guangzhou host wins, because `hkust-gz` starts
    # with the acronym and the main campus's `ust` label does not. Adding UST
    # lets the main campus corroborate its own host, and the third key (ccTLD)
    # then decides for `.hk` over `.instructure.com`.
    #
    # UST is also University of Santo Tomas, so this was checked rather than
    # assumed: with the alias in place the HKUST seed accepts exactly one
    # `ust`-labelled account, the Guangzhou one, and Santo Tomas still takes
    # `ust.instructure.com`. `contradicts()` is what holds that line - "santo"
    # and "tomas" are distinctive tokens the probes lack and the host does not
    # vouch for.
    "Hong Kong University of Science and Technology": ["HKUST", "UST"],
}

_TLD_FOR = {"GB": "uk"}
_NEUTRAL_TLD = {"com", "edu", "org", "net", "int", "info", "io"}
_LMS_AFFIX = ("canvas", "lms", "learn", "elearning", "online", "my", "courses", "study")


# ── Name comparison ──────────────────────────────────────────────────────────
def norm_name(s: str) -> str:
    """Drop parentheticals and trailing qualifiers before comparing."""
    return re.split(r"\s+[-–—|/]\s+", re.sub(r"\([^)]*\)", " ", s or ""))[0]


def toks(s: str) -> set:
    s = re.sub(r"[^a-z0-9À-ɏ ]+", " ", norm_name(s).lower())
    return {t for t in s.split() if len(t) > 1 and t not in _STOP}


def jaccard(a: str, b: str) -> float:
    A, B = toks(a), toks(b)
    return len(A & B) / len(A | B) if A and B else 0.0


def containment(a: str, b: str) -> float:
    """1.0 when one name's tokens are a subset of the other's - lets an account
    published as 'KTH' or 'Chalmers' match its full seed. Accepted only WITH
    domain corroboration, since 'Cairo University' is also a subset of
    'American University in Cairo'."""
    A, B = toks(a), toks(b)
    return len(A & B) / min(len(A), len(B)) if A and B else 0.0


def labels(domain: str) -> list:
    out = []
    for lab in (domain or "").lower().split("."):
        if lab in ("instructure", "com", "edu", "ac", "org", "net", "canvas", "lms",
                   "learn", "elearning", "www", "online", "courses", "cursos", "my"):
            continue
        out.append(lab)
        out.extend(p for p in re.split(r"[-_]", lab) if p)
        for affix in _LMS_AFFIX:
            if lab.startswith(affix) and len(lab) > len(affix):
                out.append(lab[len(affix):])
            if lab.endswith(affix) and len(lab) > len(affix):
                out.append(lab[:-len(affix)])
        # ...and with a fused GENERIC word removed. Institutions contract their
        # own name into the host - `colostate` is "Colorado State" - and the
        # remainder is a prefix of the real token where the whole label is not.
        # Without this, Colorado State University cannot corroborate
        # colostate.instructure.com, which is its actual Canvas.
        for gen in ("state", "university", "college", "institute", "uni"):
            if lab.endswith(gen) and len(lab) - len(gen) >= 3:
                out.append(lab[:-len(gen)])
    return out


def acronyms(name: str) -> set:
    """Initialisms a school is plausibly known by.

    BOTH forms, and the stopword-free one is the fix for a measured defect: the
    original built the acronym from every word, so "University of Central
    Florida" produced ``uocf`` and never ``ucf``. An institution whose Canvas
    host IS its acronym therefore could not corroborate its own domain -
    ``ucf``, ``unt``, ``ubc``, ``uio`` all failed - and the matcher settled for
    some other host that could. That is not a cosmetic miss: it is half of why
    ``University of Central Florida`` shipped pointing at Central State.
    """
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if w]
    out = set()
    for seq in (words, [w for w in words if w not in _STOP]):
        acro = "".join(w[0] for w in seq)
        if len(acro) >= 3:
            out.add(acro)
    return out


def corroborates(seed: str, domain: str, probes: list | None = None) -> bool:
    """Does the DOMAIN independently point at this institution?

    Aliases corroborate too: 'Absalon' IS what absalon.instructure.com is
    called, and requiring the English seed to match it dropped Denmark's
    largest university from a Danish-market build.
    """
    labs = labels(domain)
    cand: set = set()
    for p in (probes or [seed]):
        cand |= {t for t in toks(p) if len(t) >= 3 and t not in _GENERIC}
        cand |= acronyms(p)
    for t in cand:
        for lab in labs:
            # Both directions. `lab.startswith(t)` covers a host that EXTENDS
            # the name (`manchestermet`); `t.startswith(lab)` covers one that
            # CONTRACTS it, which is what `labels()` produces when it strips a
            # fused generic word - `colostate` -> `colo`, a prefix of Colorado.
            if (lab == t or (len(t) >= 4 and lab.startswith(t))
                    or (len(lab) >= 4 and t.startswith(lab))):
                return True
    return False


def _tld_of(domain: str):
    last = (domain or "").lower().rsplit(".", 1)[-1]
    return last if len(last) == 2 and last not in _NEUTRAL_TLD else None


def tld_vetoes(cc: str, domain: str) -> bool:
    t = _tld_of(domain)
    return t is not None and t != _TLD_FOR.get(cc, cc.lower())


def tld_matches(cc: str, domain: str) -> bool:
    # `.edu` is effectively US-only and ``cc_of`` already treats it that way, so
    # a US seed on a .edu host has a real country signal. Without this a US
    # school whose name matches EXACTLY still needed its acronym to appear in
    # the host, which is how `canvas.okstate.edu` lost Oklahoma State's slot to
    # `oklahomachristian.instructure.com`.
    if cc == "US" and (domain or "").lower().endswith(".edu"):
        return True
    t = _tld_of(domain)
    return t is not None and t == _TLD_FOR.get(cc, cc.lower())


# LOCAL_NAMES keyed by the ACCENT-FOLDED seed, because the two tables disagree
# about spelling and the lookup failed silently when they did.
#
# `SEEDS` writes "Malmo University", "Umea University", "Linkoping University";
# `LOCAL_NAMES` keys the same schools "Malmö University", "Umeå University",
# "Linköping University". A plain dict lookup therefore returned None, so those
# universities shipped with no Swedish name at all - neither as a matcher probe
# nor in the display label - and a student typing "Malmö universitet" found
# nothing. It fails silently in the worst way: `display_name` simply returns
# the English name, which looks like a deliberate choice.
#
# Folding the KEY rather than aligning the two tables is what stops it coming
# back the next time somebody adds a seed without the accents.
_LOCAL_BY_FOLD = {fold(k): v for k, v in LOCAL_NAMES.items()}


def local_name(seed: str) -> str | None:
    """The seed's local-language name, however either table spells the seed."""
    return LOCAL_NAMES.get(seed) or _LOCAL_BY_FOLD.get(fold(seed))


def local_probes(seed: str) -> list:
    """The seed's local-language name, as a matcher probe. Empty when it has none."""
    loc = local_name(seed)
    return [loc] if loc else []


def display_name(seed: str) -> str:
    """What the picker SHOWS for a seeded institution.

    ``Local (English)`` when the two differ - local first, because that is what
    the institution's own students call it and what they will type. The English
    half stays because an exchange student may know only that, and because both
    halves land in the search haystack this way.
    """
    loc = local_name(seed)
    return f"{loc} ({seed})" if loc and loc.lower() != seed.lower() else seed


def distinctive(s: str) -> set:
    """The tokens that actually IDENTIFY an institution.

    Everything a thousand universities share ("university", "state", "college",
    "royal", ...) is dropped, so what remains is the part a student would use to
    tell two schools apart: the place, the person, the founding body.
    """
    return {t for t in toks(s) if t not in _GENERIC and len(t) > 2}


def is_acronym_of(name: str, probe: str) -> bool:
    """True if *name* is *probe* written as its initials and nothing more."""
    a = distinctive(name)
    return bool(a) and a <= (distinctive(probe) | acronyms(probe))         and bool(a & acronyms(probe))


def contradicts(domain: str, name: str, probes: list) -> bool:
    """True when the seed and the account name are DIFFERENT institutions.

    THE HOLE THIS CLOSES, and why a threshold could never close it. Scoring is
    a similarity measure, and similarity is exactly the wrong question here:
    "University of British Columbia" and "Columbia University" are genuinely
    similar - they share two of three tokens - and the domain
    ``courseworks2.columbia.edu`` genuinely corroborates the shared one. Every
    gate agreed, and the pairing scored 0.667, comfortably over the 0.50 bar.
    The single word that decides it, ``british``, is the one the score throws
    away. Measured on the shipped list, eight pairings failed exactly this way:

        British Columbia -> Columbia University      (courseworks2.columbia.edu)
        Duke Kunshan     -> Duke University          (canvas.duke.edu)
        Colorado State   -> U. of Colorado Boulder   (canvas.colorado.edu)
        Oklahoma State   -> Oklahoma Christian U.    (oklahomachristian...)
        Central Florida  -> Central State University (centralstate...)
        North Texas      -> North Park University    (northpark...)
        South Carolina   -> U. of South Alabama      (usaonline.southalabama.edu)
        Manchester Met   -> The University of Manchester (canvas.manchester.ac.uk)

    So ask a DIFFERENT question, one a score cannot express: does either name
    carry a distinctive token the other lacks *and* the domain does not vouch
    for? A word like ``british`` / ``kunshan`` / ``boulder`` / ``christian``
    present on one side only, with nothing in the host to back it, is not a
    spelling variation - it is the name of another school.

    Corroboration is what keeps this from rejecting honest matches: an account
    published as "UBC Canvas" on ``canvas.ubc.ca`` has ``ubc`` vouched by its
    own host, and a seed's local-language name reaches here as a *probe* (see
    LOCAL_NAMES), so "Goteborgs universitet" and "University of Gothenburg" are
    compared as the one institution they are rather than as two.

    ANY probe that is compatible clears the pairing - the probes are alternative
    names for one school, so agreeing with one of them is agreement.
    """
    labs = labels(domain)

    def vouched(tok: str) -> bool:
        return any(lab == tok or (len(tok) >= 4 and lab.startswith(tok))
                   for lab in labs)

    acct = distinctive(name)
    for p in probes:
        seed_t = distinctive(p)
        if not seed_t or not acct:
            continue          # nothing distinctive to compare - other gates decide

        # An account may publish as the seed's INITIALISM ("UBC" for University
        # of British Columbia). The expansion it drops is then not a missing
        # qualifier but the same name written out, so those tokens must not
        # count against it - provided the account adds nothing of its own.
        acct_extra = acct - (seed_t | acronyms(p))
        reduced = is_acronym_of(name, p)
        seed_extra = set() if reduced else seed_t - acct

        if all(vouched(t) for t in seed_extra) and all(vouched(t) for t in acct_extra):
            return False
    return True


def accepts(seed: str, cc: str, domain: str, name: str) -> bool:
    if tld_vetoes(cc, domain):
        return False
    probes = [seed] + ALIASES.get(seed, []) + local_probes(seed)
    if contradicts(domain, name, probes):
        return False
    j = max(jaccard(p, name) for p in probes)
    ct = max(containment(p, name) for p in probes)
    corr = corroborates(seed, domain, probes)
    if j >= 0.75 and (corr or tld_matches(cc, domain)):
        return True
    if j >= 0.50 and corr:
        return True
    # Abbreviation path, e.g. 'KTH', 'Chalmers', 'OsloMet'.
    if ct >= 0.999 and corr and len([t for t in toks(name) if t not in _GENERIC]) <= 1:
        return True
    # INITIALISM path. "UBC Canvas" and "University of British Columbia" share
    # not one token, so jaccard and containment are both 0.0 and every branch
    # above is blind to a pairing that is obviously right. Safe because it is
    # the strictest branch here: the account must reduce ENTIRELY to the seed's
    # own initials, and the host must independently confirm them.
    if corr and any(is_acronym_of(name, p) for p in probes):
        return True
    return False


# ── Network ──────────────────────────────────────────────────────────────────
def finder(term: str, page: int = 1, per: int = 100, timeout: float = 25.0) -> list:
    url = f"{FINDER}?per_page={per}&page={page}&search_term={urllib.parse.quote(term)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def crawl(verbose: bool = True) -> dict:
    """Every account the finder publishes, as ``{domain: account name}``."""
    seen: dict[str, str] = {}
    for term in list(string.ascii_lowercase) + list(string.digits):
        for page in range(1, 61):
            got = None
            for attempt in range(3):
                try:
                    got = finder(term, page=page)
                    break
                except Exception:
                    time.sleep(1.2 * (attempt + 1))
            if not got:
                break
            for x in got:
                dom = (x.get("domain") or "").strip().lower()
                nm = (x.get("name") or "").strip()
                if dom and nm:
                    seen.setdefault(dom, nm)
            if len(got) < 100:
                break
            time.sleep(0.12)
        if verbose:
            print(f"  '{term}' -> {len(seen)} accounts", flush=True)
    return seen


def verify_domain(domain: str, timeout: float = 12.0) -> str:
    """``'ok'`` iff *domain* is a live Canvas host, else a short reason code."""
    url = f"https://{domain}/api/v1/users/self"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            body = r.read(400).decode("utf-8", "replace")
            return "ok" if "unauthenticated" in body.lower() else f"http{r.status}:body"
    except urllib.error.HTTPError as e:
        if e.code != 401:
            return f"http{e.code}"
        try:
            body = e.read(400).decode("utf-8", "replace")
        except Exception:
            body = ""
        return "ok" if "unauthenticated" in body.lower() else "401:body"
    except Exception as e:
        return type(e).__name__


def verify_many(domains: list, workers: int = 16) -> dict:
    """Verify in parallel, then RETRY every failure - patiently, and REPEATEDLY.

    A transient network error is not evidence that a domain is dead, and
    treating it as such makes the shipped list quietly depend on the weather.
    The asymmetry is the whole design: a slow retry costs seconds, a wrong drop
    costs an institution - or, measured once, three countries.

    **One retry pass is not enough, and the failure scales with the sweep.**
    Measured 2026-08-09 on a 4,452-domain run: the parallel sweep plus a single
    serial retry still reported 178 hosts "genuinely unreachable", and 16 of
    them - sampled and checked by hand - answered on the FIRST try when asked
    on their own, every one in under 1.5 seconds. Among them were the
    University of Kansas, Georgetown, Rhode Island School of Design and Wake
    Technical Community College. Nothing was wrong with those hosts; the sweep
    itself was the problem, so retrying it the same way reproduces it.

    Hence: back off between passes, drop the concurrency to 1 for the last one,
    and only believe a failure that survives all of them. A pass that fixes
    nothing costs one cooldown, which is why the loop exits as soon as a pass
    clears the backlog.
    """
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        res = dict(zip(domains, ex.map(verify_domain, domains)))

    # (workers, timeout, cooldown before the pass) - progressively gentler.
    for pass_workers, timeout, cooldown in ((3, 25.0, 0.0), (1, 30.0, 20.0)):
        retry = [d for d, v in res.items() if v != "ok"]
        if not retry:
            break
        if cooldown:
            print(f"  cooling down {cooldown:.0f}s before the final pass...", flush=True)
            time.sleep(cooldown)
        print(f"  retrying {len(retry)} verification failure(s) "
              f"({pass_workers} worker(s), {timeout:.0f}s)...", flush=True)
        if pass_workers == 1:
            for d in retry:
                res[d] = verify_domain(d, timeout=timeout)
        else:
            with cf.ThreadPoolExecutor(max_workers=pass_workers) as ex:
                for d, v in zip(retry, ex.map(lambda x: verify_domain(x, timeout=timeout), retry)):
                    res[d] = v

    still = [d for d, v in res.items() if v != "ok"]
    if still:
        print(f"  {len(still)} genuinely unreachable: {', '.join(sorted(still)[:6])}"
              f"{' ...' if len(still) > 6 else ''}", flush=True)
    return res


# ── Assembly ─────────────────────────────────────────────────────────────────
def clean_name(n: str) -> str:
    """Strip tenant qualifiers so 'The University of Melbourne (non-SSO)' and
    'University of Melbourne Online' collapse onto one recognisable entry."""
    n = re.sub(r"\([^)]*\)", " ", n)
    n = re.split(r"\s+[-–—|]\s+", n)[0]
    n = re.sub(r"\s+(Online|Canvas|LMS|Learning|Global|Digital)$", "", n, flags=re.I)
    return re.sub(r"\s+", " ", n).strip().strip(",")


def dedupe_key(n: str) -> str:
    k = re.sub(r"[^a-z0-9 ]+", " ", clean_name(n).lower())
    return re.sub(r"\s+", " ", re.sub(r"^(the|de|la)\s+", "", k)).strip()


# Sub-tenant markers in a DOMAIN. An institution routinely runs several Canvas
# hosts, and only one of them is where an ordinary student's courses live.
_TENANT_NOISE = re.compile(
    r"(continuing|conted|-ce\b|workforce|execed|executive|alumni|catalog|"
    r"online|summer|prof|pd|test|dev|sandbox|training)", re.I)


def domain_rank(domain: str) -> tuple:
    """Sort key preferring an institution's MAIN Canvas host.

    Lower is better: no sub-tenant marker, then fewer hyphens, then shorter.
    Used only to decide which of several hosts wins one institution's slot -
    never to decide whether a host is included at all.
    """
    return (bool(_TENANT_NOISE.search(domain)), domain.count("-"), len(domain))


def cc_of(domain: str) -> str:
    last = domain.rsplit(".", 1)[-1].lower()
    if last == "edu":
        return "US"                        # .edu is effectively US-only
    if len(last) == 2 and last not in _NEUTRAL_TLD:
        return _TLD_FOR_INV.get(last, last.upper())
    return ""


_TLD_FOR_INV = {v: k for k, v in _TLD_FOR.items()}


def build(pool: dict, limit: int) -> tuple[list, list]:
    # --- seed core: curated display names for the best-known institutions ----
    usable = [(d, n) for d, n in pool.items()
              if not _BAD_ACCOUNT.search(n) and not _BAD_ACCOUNT.search(d)]
    core, rejected = [], []
    for seed, cc in SEEDS:
        probes = [seed] + ALIASES.get(seed, []) + local_probes(seed)
        best = None
        for dom, name in usable:
            if not accepts(seed, cc, dom, name):
                continue
            # `domain_rank` is the LAST word, and without it the winner among
            # equals was whichever the crawl dict happened to yield first.
            #
            # An institution routinely publishes one tenant per campus, and
            # `jaccard` scores token SETS - so "University of Michigan - Ann
            # Arbor", "- Dearborn" and "- Flint" are all exactly 1.00 against
            # the seed, as are "University of Kansas - KU" and "University of
            # Kansas - kuconnect.ku.edu". Corroboration and ccTLD tie too, at
            # which point `key > best[0]` keeps the FIRST one seen. Measured
            # 2026-08-09: the seed "University of Michigan" settled on
            # DEARBORN, and Kansas on `kuconnect` over `canvas.ku.edu` - a
            # student picking their own university by name got another campus.
            #
            # It is negated because `domain_rank` reads low-is-better while
            # this key reads high-is-better. Note the fix belongs HERE and not
            # in the dedupe below: that pass already sorts by `domain_rank`,
            # but core rows are ordered ahead of fill rows, so by then the
            # seed's choice is frozen and the better host has already lost.
            key = (max(jaccard(p, name) for p in probes),
                   corroborates(seed, dom, probes), tld_matches(cc, dom),
                   tuple(-int(x) for x in domain_rank(dom)))
            if best is None or key > best[0]:
                best = (key, {"name": display_name(seed), "domain": dom, "cc": cc})
        if best is None:
            continue
        if REJECT.get(seed) == best[1]["domain"]:
            rejected.append((seed, best[1]["domain"]))
            continue
        core.append(best[1])

    # --- fill: accounts under their OWN name (no pairing risk whatsoever) ----
    used = {c["domain"] for c in core}
    fill = []
    for dom, name in pool.items():
        if dom in used or dom in REJECT_DOMAINS:
            continue
        if not is_institution(name, dom):
            continue
        nm = clean_name(re.split(r"\s+\|\s+", name)[0])
        # Re-test the CLEANED name: `clean_name` strips parentheticals and
        # everything after " - ", so the education word can be the thing it
        # just removed, leaving a label that names no institution at all.
        if not (4 <= len(nm) <= 64) or not _EDUCATION.search(fold(nm)):
            continue
        # A hand-written label wins: it is there because the account's own name
        # over-claims (names a whole university while serving one of its
        # schools), and the fix is to disambiguate rather than to drop.
        fill.append({"name": RENAME.get(dom, nm), "domain": dom, "cc": cc_of(dom)})
    # Own-domain first: configuring a CNAME is a fair proxy for an established
    # institution, and it is the only ranking signal the finder exposes at all.
    fill.sort(key=lambda r: (r["domain"].endswith(".instructure.com"), r["name"].lower()))

    want = max(0, limit - len(core))
    cand = core + fill[:want]
    res = verify_many([c["domain"] for c in cand])
    ok = [c for c in cand if res.get(c["domain"]) == "ok"]

    # Backfill so verification losses do not shrink the list below the target.
    if len(ok) < limit and len(fill) > want:
        have = {c["domain"] for c in ok}
        extra = [c for c in fill[want:] if c["domain"] not in have][:(limit - len(ok)) * 2]
        if extra:
            r2 = verify_many([c["domain"] for c in extra])
            ok += [c for c in extra if r2.get(c["domain"]) == "ok"][:limit - len(ok)]

    core_doms = {c["domain"] for c in core}
    seen_dom, seen_inst, final = set(), set(), []
    # Core first so a curated display name always wins its institution's slot;
    # then BEST DOMAIN first, so when one institution publishes several tenants
    # the student's main Canvas wins the slot rather than whichever sorted
    # first. Measured: Saint Joseph's University publishes both `sju` and
    # `sju-continuing-ed`, and St Catherine both `stkate` and `stkateonline`.
    for c in sorted(ok, key=lambda r: (r["domain"] not in core_doms,
                                       domain_rank(r["domain"]),
                                       r["cc"] or "ZZ", r["name"].lower())):
        k = dedupe_key(c["name"])
        if c["domain"] in seen_dom or k in seen_inst:
            continue
        seen_dom.add(c["domain"])
        seen_inst.add(k)
        final.append(c)
    final.sort(key=lambda r: (r["cc"] or "ZZ", r["name"].lower()))
    return final, rejected


# ── Codegen ──────────────────────────────────────────────────────────────────
def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_module(rows: list) -> str:
    body = "\n".join("    (%s, %s, %s)," % (_q(r["name"]), _q(r["domain"]), _q(r["cc"]))
                     for r in rows)
    return _TEMPLATE.replace("@@COUNT@@", str(len(rows))).replace("@@ROWS@@", body)


_TEMPLATE = '''"""Bundled directory of Canvas institutions - the login picker's data.

GENERATED by ``scripts/build_institution_list.py``. Do not hand-edit ``DATA``;
re-run the script instead, so every entry keeps its verification provenance.

Every domain here was proven, at generation time, to answer
``/api/v1/users/self`` with Canvas's own unauthenticated payload - i.e. a live
Canvas host, not a parked domain, marketing site or SSO portal (all of which
answer an ordinary request and would pass a naive reachability check).

**The list is deliberately not exhaustive, and the UI must keep saying so.**
Canvas is used by thousands of institutions; this covers the largest and
best-known across the app's markets so the common case is one click. The URL
field beside the picker remains the universal path - any Canvas school works
whether or not it appears here. A student whose school is missing must never
conclude the app does not support them, which is why the picker's empty state
is worded as an instruction rather than a failure.

``country`` may be empty: it is inferred from the domain's ccTLD, and a
``*.instructure.com`` tenant carries no country signal. It only ever widens the
search haystack and is never displayed, so "unknown" costs nothing.

Shipped as a ``.py`` rather than a data file on purpose: a module is picked up
by PyInstaller's import graph automatically, so neither spec file needs a
``datas`` entry that could be added on one platform and forgotten on the other.
"""
from __future__ import annotations

# (display name, canvas domain, ISO 3166-1 alpha-2 country or "")
DATA: tuple[tuple[str, str, str], ...] = (
@@ROWS@@
)

COUNT = @@COUNT@@


def count() -> int:
    """How many institutions ship in the picker (used in UI copy)."""
    return len(DATA)


def _host(url: str) -> str:
    """Bare lowercase host of *url*, with scheme, port, path and ``www.`` gone."""
    s = (url or "").strip().lower()
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    s = s.split("@")[-1].split(":", 1)[0]
    return s[4:] if s.startswith("www.") else s


def match_url(url: str):
    """The row whose domain is *url*'s host, else ``None``.

    Exact host equality only - deliberately no fuzzy or suffix matching. A
    suffix rule would make ``evil-harvard.edu`` match ``harvard.edu`` and let
    the UI vouch for a host this list never verified.
    """
    h = _host(url)
    if not h:
        return None
    for row in DATA:
        if row[1] == h:
            return row
    return None


def search_blob(row: tuple[str, str, str]) -> str:
    """Lowercased haystack for one row - name, domain and country together.

    Built here rather than in the UI so the server-rendered ``data-q``
    attribute and any Python-side search can never disagree.
    """
    return f"{row[0]} {row[1]} {row[2]}".lower()
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300,
                    help="target size (the crawl supports ~1,800 higher-ed entries)")
    ap.add_argument("--cache", help="reuse a crawl JSON instead of re-crawling")
    ap.add_argument("--save-crawl", help="write the crawl to this path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.cache:
        pool = json.loads(Path(args.cache).read_text(encoding="utf-8"))
        print(f"loaded {len(pool)} accounts from {args.cache}")
    else:
        print("crawling the public Canvas account finder...", flush=True)
        pool = crawl()
        print(f"crawled {len(pool)} accounts")
    if args.save_crawl:
        Path(args.save_crawl).write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")

    rows, rejected = build(pool, args.limit)
    print(f"\n{len(rows)} institutions "
          f"({sum(1 for r in rows if r['cc']) } with a known country)")
    if rejected:
        print(f"hand-review rejections applied: {len(rejected)}")
        for seed, dom in rejected:
            print(f"   drop  {seed[:44]:<46} {dom}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    OUT.write_text(render_module(rows), encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
