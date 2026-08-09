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
from institution_direct import DIRECT                     # noqa: E402

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
    # `wits` is not a prefix of `witwatersrand` - it diverges at the fourth
    # letter - so the host cannot corroborate the spelled-out name by any rule
    # in `corroborates`, and South Africa's best-known university therefore
    # could not be seeded onto its own Canvas at ulwazi.wits.ac.za. It is what
    # the university calls itself, on its own domain.
    "University of the Witwatersrand": ["Wits", "Wits University"],
    # Same shape: the host contracts the name to one label. Needed here for a
    # second reason - the seed exists to hold `uandes.instructure.com` AWAY
    # from Colombia's Universidad de los Andes, which the qualifier veto now
    # correctly refuses, and which would otherwise leave a real Chilean
    # university shipping under a Colombian one's name.
    "Universidad de los Andes Chile": ["UANDES", "Universidad de los Andes - Chile"],
    "Universidad de Santiago de Chile": ["USACH"],
    "Universidad Andres Bello": ["UNAB", "UNAB Chile"],
    "Universidad Tecnologica Metropolitana": ["UTEM"],
    "Technological Institute of the Philippines": ["TIP"],
    "Far Eastern University": ["FEU"],
    "Central Philippine University": ["CPU"],
    "Pontifical Catholic University of Parana": ["PUCPR",
                                                 "Pontificia Universidade Catolica do Parana"],
    "Pontifical Catholic University of Campinas": ["PUC Campinas",
                                                   "Pontificia Universidade Catolica de Campinas"],
    "Universidade Luterana do Brasil": ["ULBRA"],
    "Universidade Veiga de Almeida": ["UVA"],
    "Escola Superior de Propaganda e Marketing": ["ESPM"],
    "Universidad Tecnologica del Peru": ["UTP"],
    "Universiti Brunei Darussalam": ["UBD"],
    "Universitas Pembangunan Jaya": ["UPJ"],
    "British University Vietnam": ["BUV"],
}

_TLD_FOR = {"GB": "uk"}
# `eu` is two letters and is NOT a country - it is supranational, so `cc_of`
# used to emit the country code "EU", which no country table can name and which
# therefore ships a row that is excluded from every regional suggestion list and
# asks the picker for a label that does not exist. Caught by
# `test_every_shipped_country_has_a_searchable_name`, which is the gate for any
# future one of these.
_NEUTRAL_TLD = {"com", "edu", "org", "net", "int", "info", "io", "eu"}
_LMS_AFFIX = ("canvas", "lms", "learn", "elearning", "online", "my", "courses", "study")


# ── Name comparison ──────────────────────────────────────────────────────────
def norm_name(s: str) -> str:
    """Drop parentheticals and trailing qualifiers before comparing."""
    return re.split(r"\s+[-–—|/]\s+", re.sub(r"\([^)]*\)", " ", s or ""))[0]


def tail_segments(s: str) -> list:
    """Each discarded qualifier of *s*, separately and IN SOURCE ORDER.

    Segments rather than one blob because they are judged one at a time: "TOS -
    The Olympia Schools (Teacher, Student)" has a segment worth keeping and a
    segment that is pure audience noise, and joining them first forces one
    verdict on both. Source order because joining parentheticals ahead of
    dash-tails silently rewrites the name - measured, that example came out as
    "TOS - Teacher, Student The Olympia Schools".
    """
    out, src = [], s or ""
    for m in re.finditer(r"\(([^)]*)\)", src):
        out.append((m.start(), m.group(1)))
    head_and_rest = re.sub(r"\([^)]*\)", lambda m: " " * len(m.group(0)), src)
    pos = 0
    for i, part in enumerate(re.split(r"\s+[-–—|/]\s+", head_and_rest)):
        if i:
            out.append((pos, part))
        pos += len(part) + 3
    return [t.strip() for _p, t in sorted(out) if t.strip()]


def tail_of(s: str) -> str:
    """Everything ``norm_name`` throws away: parentheticals and the trailing
    qualifier after a dash or pipe.

    **This is the single most consequential omission the pairing gates had.**
    Every veto in this file compares ``distinctive`` token sets, and those go
    through ``norm_name`` - so the gates were reasoning about names with the
    disambiguator already deleted. "University of Tennessee - Martin" arrived
    as "University of Tennessee", "Universidad de los Andes - Chile" as
    "Universidad de los Andes", "University of Arizona - College of Public
    Health" as "University of Arizona". Each then scored a perfect 1.00 against
    a seed it is not, because the one word that says so had been removed
    BEFORE the comparison began. All three shipped.
    """
    return " ".join(tail_segments(s))


#: Qualifier words that describe the TENANT, not the institution: how you log
#: in, who the audience is, which platform it runs on. A name carrying only
#: these still names the same school, so they must never be read as evidence of
#: a different one - "The University of Melbourne (non-SSO)" IS the University
#: of Melbourne, and treating `non` and `sso` as distinguishing tokens would
#: veto the university on the strength of its own login method.
_ADMIN_QUALIFIER = {
    "sso", "non", "nonsso", "saml", "shibboleth", "cas", "oauth", "ldap",
    "students", "student", "teachers", "teacher", "staff", "faculty", "parents",
    "parent", "observers", "observer", "guests", "guest", "alumni", "admin",
    "canvas", "lms", "moodle", "portal", "login", "site", "prod", "production",
    "live", "main", "new", "old", "legacy", "beta", "test", "dev", "uat", "qa",
    "sandbox", "archive", "archived", "copy", "only", "and", "for", "the",
    "part", "time", "full", "adjunct", "observers", "all", "new",
}


def tail_tokens(name: str) -> set:
    """Tokens in *name*'s qualifier that carry INFORMATION about which
    institution this is - a campus, a country, a faculty, a city.

    This is the DISPLAY question ("may I delete this tail from the label?"),
    and it is deliberately broader than the veto question below. Keeping the
    two apart matters: narrowing the veto to institution-like qualifiers is
    what stopped it rejecting "University of Michigan - Ann Arbor", but a label
    must still say "University of Tennessee - Martin" rather than promoting a
    branch campus into a claim on the whole university.
    """
    return {t for t in toks(tail_of(name))
            if t not in _ADMIN_QUALIFIER and t not in _GENERIC and len(t) > 2}


def qualifier_tokens(name: str) -> set:
    """Tokens in *name*'s qualifier, but ONLY when the qualifier names an
    institution rather than a place.

    **The narrowing is the whole rule, and it was arrived at by measurement.**
    A veto on every unvouched qualifier token is too strong in one specific and
    very common shape: a university publishing its flagship campus by name.
    "University of Michigan - Ann Arbor" on ``m.canvas.umich.edu`` was rejected
    while "- Flint" on ``canvas.flint.umich.edu`` was accepted, because the
    branch campus names itself in its host and the main campus does not - so
    the veto reliably picked the WRONG campus of any multi-campus university.

    A qualifier carrying an entity-KIND word is a different thing entirely: it
    is not a campus, it is a name. "ELU - European Leadership University" is
    not Eotvos Lorand University, and that pairing shipped. Everything else -
    a bare place, an initialism, a login method - is left to corroboration and
    ``domain_rank``, which handle campuses correctly and were already the only
    gates rejecting "University of Tennessee - Martin" and "Universidad de los
    Andes - Chile".
    """
    tail = tail_of(name)
    if not kinds(tail):
        return set()
    return {t for t in toks(tail)
            if t not in _ADMIN_QUALIFIER and t not in _GENERIC and len(t) > 2}


#: Words naming what KIND of institution this is. They are in ``_GENERIC``
#: because they cannot corroborate a domain - but between two names they are
#: highly discriminating, and dropping them is how "UNSW College" (a separate
#: pathway provider) was accepted as the University of New South Wales and
#: "UTS College" nearly was for UTS. A kind the account claims and the seed
#: does not is a different sort of organisation wearing a familiar name.
_ENTITY_KIND = {
    "university", "universitat", "universitet", "universiteit", "universidad",
    "universidade", "universite", "universiti", "universitas", "college",
    "school", "institute", "academy", "polytechnic", "seminary", "conservatory",
    "hogskole", "hogskolan", "hochschule", "gymnasium", "escuela", "instituto",
}


def kinds(s: str) -> set:
    """Entity-kind words anywhere in *s*, QUALIFIER INCLUDED.

    Deliberately not routed through ``toks``, which drops the tail: "University
    of Arizona - College of Public Health" is a college of a university, and
    reading only the head makes it indistinguishable from the university.
    """
    return {t for t in re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).split()
            if t in _ENTITY_KIND}


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
    qual = qualifier_tokens(name)
    acct_kinds = kinds(name)
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

        # The QUALIFIER, which `distinctive` never saw because `norm_name`
        # removed it. A campus, a faculty or a country named here and nowhere
        # in the seed - and not backed by the host - is another institution.
        qual_extra = qual - (seed_t | acronyms(p))
        # ...and the KIND. "UNSW College" is not the University of New South
        # Wales, and the only word that says so is one `_GENERIC` discards.
        kind_extra = acct_kinds - kinds(p)

        if (all(vouched(t) for t in seed_extra)
                and all(vouched(t) for t in acct_extra)
                and all(vouched(t) for t in qual_extra)
                and all(vouched(t) for t in kind_extra)):
            return False
    return True


#: Initialisms produced by MORE THAN ONE seed. Computed, never hand-listed, so
#: it cannot fall out of date when a seed is added.
#:
#: "USC" is the initialism of BOTH "University of South Carolina" and
#: "University of Southern California", and the account on
#: ``courses.online.usc.edu`` is called simply "USC Online" - so the initialism
#: path accepted it for whichever seed reached it first, and the dedupe then
#: kept the alphabetically-earlier name. Shipped result: South Carolina
#: pointing at Southern California's tenant, AND Southern California missing
#: from the list altogether, because its domain had already been taken.
#:
#: An ambiguous initialism is not weak evidence, it is NO evidence, so the
#: initialism path simply declines it. Both seeds then fall through to the
#: ordinary branches, which need a real name match.
def _ambiguous_acronyms() -> set:
    seen, dupes = set(), set()
    for seed, _cc in SEEDS:
        for a in acronyms(seed):
            (dupes if a in seen else seen).add(a)
    return dupes


_AMBIGUOUS_ACRONYMS = _ambiguous_acronyms()


#: A word in a DOMAIN that announces a side entrance rather than the
#: institution's Canvas. Only a veto when the seed's own name does not contain
#: it - `online.smc.edu` really is Santa Monica College's Canvas, and "Online"
#: really is part of "Melbourne University Online".
#:
#: `_TENANT_NOISE` above cannot be reused for this: it is written for RANKING
#: between candidates, so its alternatives are unanchored and `pd`, `dev` and
#: `prof` match inside ordinary words. As a veto that would delete real
#: institutions.
_SUBTENANT_WORDS = ("online", "continuing", "conted", "execed", "executive",
                    "alumni", "catalog", "summer", "workforce", "precollege",
                    "professional", "health", "medical", "nursing", "extension")


def domain_is_subtenant(domain: str, probes: list) -> bool:
    """The host names a sub-tenant the institution's own name never mentions.

    Declining here is cheap and self-correcting: the domain simply falls
    through to the FILL path, where it ships under the account's own name. So
    the institution is not lost - it is labelled as what it actually is.
    """
    d = fold(domain)
    for w in _SUBTENANT_WORDS:
        if w in d and not any(w in fold(p) for p in probes):
            return True
    return False


def accepts(seed: str, cc: str, domain: str, name: str) -> bool:
    if tld_vetoes(cc, domain):
        return False
    probes_all = [seed] + ALIASES.get(seed, []) + local_probes(seed)
    if domain_is_subtenant(domain, probes_all):
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
        return not (distinctive(name) & _AMBIGUOUS_ACRONYMS)
    return False


# ── Network ──────────────────────────────────────────────────────────────────
def finder(term: str, page: int = 1, per: int = 100, timeout: float = 25.0) -> list:
    url = f"{FINDER}?per_page={per}&page={page}&search_term={urllib.parse.quote(term)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


# The finder paginates as far as its result set goes; there is NO server-side
# result cap. Measured 2026-08-09 by binary-searching the last non-empty page:
# 'a' ends at page 94 (~9,369 results), 'e' at 106 (~10,565), 'i' at 105.
# `_MAX_PAGES` is therefore a runaway guard, not a policy - 250 pages is 25,000
# results for one letter, an order of magnitude past anything observed.
#
# THE OLD `range(1, 61)` WAS SILENTLY DISCARDING ~40% OF EVERY COMMON LETTER.
# It reads like a generous bound and is not: measured on letter 'a' alone,
# pages 61-94 hold 2,433 domains pages 1-60 never saw, and 1,400 of those pass
# `is_institution`. That single cap is the largest reason whole markets were
# missing from the shipped list - India shipped ONE institution, Nigeria none -
# and no gate or seed could have rescued them, because the accounts never
# reached `build()` at all.
_MAX_PAGES = 250

# Why plain a-z + 0-9 is COMPLETE, and why no market-specific search terms are
# needed to make it so. The finder substring-matches the DOMAIN as well as the
# name (verified: 'oskilde' finds vucroskilde.instructure.com, whose account is
# named "VUC Roskilde"; 'cbscanvas' finds Copenhagen Business School). Every
# `*.instructure.com` domain therefore contains "instructure", so the single
# term 'e' alone returns all 9,542 of them, and every vanity domain contains at
# least one a-z letter in its TLD. The union cannot miss an account.
#
# The residual risk this does NOT cover is an account the finder does not
# publish at all - that is the hard ceiling named in the module header, and no
# crawl strategy reaches past it.
_TERMS = list(string.ascii_lowercase) + list(string.digits)


def crawl(verbose: bool = True) -> dict:
    """Every account the finder publishes, as ``{domain: [names...]}``.

    **All** names, not the first one seen. Several accounts routinely share one
    domain - a parents/observers tenant beside the students one, an acronym
    beside the spelled-out title - and the old ``setdefault`` kept whichever the
    crawl happened to reach first, i.e. an artefact of alphabetical search
    order. That is how ``tip.instructure.com`` can ship as "TIP" rather than
    "Technological Institute of the Philippines": both names exist, and nothing
    was choosing between them. `best_account_name` does the choosing now.
    """
    seen: dict[str, list] = {}
    for term in _TERMS:
        pages = 0
        for page in range(1, _MAX_PAGES + 1):
            got = None
            for attempt in range(3):
                try:
                    got = finder(term, page=page)
                    break
                except Exception:
                    time.sleep(1.2 * (attempt + 1))
            if not got:
                break
            pages = page
            for x in got:
                dom = (x.get("domain") or "").strip().lower()
                nm = (x.get("name") or "").strip()
                if dom and nm:
                    names = seen.setdefault(dom, [])
                    if nm not in names:
                        names.append(nm)
            if len(got) < 100:
                break
            time.sleep(0.12)
        if verbose:
            print(f"  '{term}' -> {pages} pages, {len(seen)} domains so far", flush=True)
    return seen


def best_account_name(names: list) -> str:
    """The most useful of several names published on one domain.

    Prefer a name that actually SAYS what the institution is: one carrying an
    education word beats a bare acronym, because the acronym is unsearchable for
    anyone who does not already know it. Among equals, prefer the one without a
    tenant/audience qualifier ("- Parents/Observers", "(SAML)", "| Students &
    Teachers"), then the longer one - a fuller title carries more of the words a
    student might type.
    """
    def rank(n: str) -> tuple:
        f = fold(n)
        return (
            not bool(_EDUCATION.search(f)),          # education word first
            bool(_BAD_ACCOUNT.search(f)),            # audience/tenant qualifier last
            bool(re.search(r"[(|]|\s-\s", n)),       # unqualified first
            -len(n),                                 # then the fuller title
        )
    return sorted(names, key=rank)[0] if names else ""


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


# Verification verdicts carried between runs.
#
# NOTHING IN THIS SCRIPT CHANGES WHAT A HOST ANSWERS, so a verdict from an
# earlier run is as good as a fresh one - and verification is where all the wall
# clock goes (a full run is hours, almost all of it the patient serial pass over
# hosts that really are dead). Reusing it turns "I changed a gate, rebuild"
# from an afternoon into minutes, which is the difference between iterating on
# the gates and not.
#
# Only ``ok`` is cached. A FAILURE is deliberately never remembered: it is the
# verdict that can be wrong for reasons outside the host (see `verify_many`),
# and a cached false negative would delete an institution permanently, silently,
# and identically on every later run - the one failure mode this whole module is
# built to avoid.
_VERIFY_CACHE: dict = {}


def load_verify_cache(path) -> None:
    global _VERIFY_CACHE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        _VERIFY_CACHE = {d: v for d, v in raw.items() if v == "ok"}
        print(f"  reusing {len(_VERIFY_CACHE)} cached 'ok' verdicts from {path}")
    except FileNotFoundError:
        _VERIFY_CACHE = {}
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        print(f"  verify cache unreadable ({type(e).__name__}) - verifying everything")
        _VERIFY_CACHE = {}


def save_verify_cache(path) -> None:
    try:
        path.write_text(json.dumps(_VERIFY_CACHE, ensure_ascii=False, indent=0),
                        encoding="utf-8")
    except OSError as e:
        print(f"  could not write verify cache: {e}")


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
    todo = [d for d in domains if d not in _VERIFY_CACHE]
    res = {d: "ok" for d in domains if d in _VERIFY_CACHE}
    if len(todo) < len(domains):
        print(f"  {len(domains) - len(todo)} already verified, checking {len(todo)}",
              flush=True)
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        res.update(zip(todo, ex.map(verify_domain, todo)))

    # (workers, timeout, cooldown before the pass) - progressively gentler.
    #
    # The last pass is 2 workers rather than 1. At the list sizes this now
    # builds, a strictly serial sweep over the dead hosts is the entire runtime
    # of the script: ~500 unreachable domains x a 30s connect timeout is over
    # four hours, and every second of it is spent waiting on hosts that will
    # never answer. Two workers halves that while staying far below the
    # concurrency that produced the false negatives in the first place.
    for pass_workers, timeout, cooldown in ((3, 25.0, 0.0), (2, 30.0, 20.0)):
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

    _VERIFY_CACHE.update({d: "ok" for d, v in res.items() if v == "ok"})
    still = [d for d, v in res.items() if v != "ok"]
    if still:
        print(f"  {len(still)} genuinely unreachable: {', '.join(sorted(still)[:6])}"
              f"{' ...' if len(still) > 6 else ''}", flush=True)
    return res


# ── Assembly ─────────────────────────────────────────────────────────────────
def clean_name(n: str) -> str:
    """Strip TENANT qualifiers, and keep the ones that identify the institution.

    The old version stripped every parenthetical and everything after a dash,
    unconditionally - which is right for "The University of Melbourne
    (non-SSO)" and a falsehood for "University of Tennessee - Martin", which it
    turned into "University of Tennessee". Same for "Universidad de los Andes -
    Chile" and "University of Arizona - College of Public Health": in each case
    the account named itself accurately and this function promoted it into a
    claim on the whole university.

    The tail is dropped only when it says nothing about WHICH institution this
    is - administrative words, or an initialism of the head (so "Central
    Philippine University (CPU)" still loses its brackets). Otherwise it stays,
    and the row is labelled as the campus or faculty it really is.
    """
    head = norm_name(n).strip()
    keep = []
    for seg in tail_segments(n):
        # An initialism of the head is the same name written shorter, not a
        # different institution - and it is how a great many accounts are
        # titled ("Central Philippine University (CPU)").
        if not tail_tokens(f"x ({seg})") or is_acronym_of(seg, head):
            continue
        keep.append(seg)
    out = " - ".join([head] + keep) if head else " - ".join(keep)
    out = re.sub(r"\s+(Online|Canvas|LMS|Learning|Global|Digital)$", "", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip().strip(",").strip("-").strip()


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


# ── Country inference for fill rows ──────────────────────────────────────────
#
# WHY THIS HAD TO EXIST. `cc_of` reads the ccTLD, and 93% of the shipped list
# is `*.instructure.com`, which carries no country signal at all - so 3,906 of
# 4,272 rows had ``cc == ""``. That was tolerable while country only widened
# the search haystack. It is not tolerable now: the picker opens on the
# institutions in the user's own country, and a country nobody has costs every
# user in it that entire feature. Measured before this: DENMARK had two rows
# with a country, while Erhvervsakademi Aarhus, Den Danske Filmskole, VUC
# Roskilde, VUC KLAR and VUC Storstrom all shipped as country-unknown.
#
# WHAT MAKES IT SAFE. An inferred country is used for exactly two things - it
# widens the search haystack, and it orders the list shown before anything is
# typed - and it is NEVER displayed as a claim about the institution. So the
# cost of a wrong guess is one unexpected row in a suggestion list, which the
# user simply does not click. That is a different universe of consequence from
# a wrong name-to-domain pairing, and it is why the evidence bar here is
# deliberately lower than anywhere else in this file.
#
# Each rule is a marker that is essentially unambiguous IN PRACTICE, not merely
# common: "Erhvervsakademi" is a Danish institution type defined in Danish law,
# `ISD` is a US school-district suffix, "Hogeschool" is Dutch/Flemish. Words
# shared across a language family are deliberately ABSENT - "universitet" is
# Danish, Norwegian AND Swedish, so it proves nothing and is not listed.
_CC_MARKERS = (
    ("DK", r"erhvervsakademi|\bvuc\b|professionshojskol|handelsskol|"
           r"danmarks|dansk\w*|kobenhavn\w*|\baarhus\b|odense|aalborg|"
           r"gymnasiefaellesskab|hf\s*&\s*vuc|social- og sundhedsskol"),
    ("NO", r"hogskolen i |hogskulen|videregaende skole|norges |norsk\w*|"
           r"fylkeskommune|folkehogskole"),
    ("SE", r"hogskolan|gymnasieskola|larosate|kommun\b|sveriges|svensk\w*|"
           r"folkhogskola|yrkeshogskola"),
    ("FI", r"yliopisto|korkeakoulu|ammattikorkeakoulu|\blukio\b|suomen"),
    # NOT "islands": it put "California State University, Channel Islands"
    # in Iceland. The Icelandic school words are unambiguous; the English one
    # was doing nothing but harm.
    ("IS", r"haskol\w*|menntaskol\w*|framhaldsskol\w*"),
    ("NL", r"hogeschool|onderwijs|\bmbo\b|\broc\b|scholengemeenschap"),
    ("DE", r"hochschule|fachhochschule|berufskolleg|gesamtschule|realschule|"
           # NOT a bare "universitat": Germany, Austria and Switzerland all use
           # it, and it tagged Austria's Universitat fur Weiterbildung Krems as
           # German. (Heidelberg keeps DE because it is a SEED, which carries
           # its own country and never consults this table.)
           r"gymnasium der|deutsche\w*"),
    ("BR", r"universidade|faculdade|instituto federal|colegio estadual|senai|sesi"),
    ("PT", r"politecnico de|universidade de lisboa|instituto superior"),
    ("ID", r"universitas|sekolah|institut teknologi|politeknik negeri"),
    # Word-bounded: unbounded, "universiti" is a substring of the English
    # "Universities" and tagged the Association of Commonwealth Universities as
    # Malaysian.
    ("MY", r"\buniversiti\b|\bkolej\b|sekolah menengah"),
    # NOT "city college of": that is a US pattern, and it put City College of
    # San Francisco in the Philippines - twice.
    ("PH", r"philippin\w*|pamantasan|paaralan"),
    ("ZA", r"\bnwu\b|tshwane|kwazulu|stellenbosch|witwatersrand|"
           r"south african|\bsandton\b|gauteng"),
    # NOT "indian school": in the United States that names a Native American
    # school, and it put "Red Cloud Indian School" (Pine Ridge, South Dakota)
    # into the list of institutions in India. A marker has to be unambiguous in
    # PRACTICE, not merely suggestive - the whole table is only safe because
    # each entry is a word that means one thing.
    ("IN", r"\bindian institute of\b|\bcbse\b|vidyalaya|vidyapeeth|"
           r"\bpilani\b|bengaluru|\bmumbai\b|\bchennai\b|\bhyderabad\b"),
    ("US", r"\b(isd|usd|cisd|csd|ufsd|sd\d+)\b|school district|public schools|"
           r"unified school|county schools|\bcommunity college\b|"
           r"\bcharter school\b|\bboe\b|\bboard of education\b"),
)
_CC_MARKERS_RX = tuple((cc, re.compile(rx, re.I)) for cc, rx in _CC_MARKERS)

#: A trailing US state/territory code, as school districts publish it
#: ("Giles County Schools - VA"). Anchored to the END so it cannot fire on an
#: institution that merely contains the letters.
_US_STATE_TAIL = re.compile(
    r"[-,(\s]\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|"
    r"MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|"
    r"VA|WA|WV|WI|WY|DC)\)?\s*$")


def infer_cc(name: str, domain: str) -> str:
    """The institution's country - ccTLD first, then name markers, else ``""``.

    The ccTLD is PROOF and always wins; the markers are evidence and only ever
    speak for a domain that carries no country of its own. Returning ``""``
    stays a perfectly good answer: an unknown country costs one row's place in
    a suggestion list, and inventing one to avoid an empty string would be
    exactly the kind of confident wrong answer this file exists to avoid.
    """
    hard = cc_of(domain)
    if hard:
        return hard
    if _US_STATE_TAIL.search(name):
        return "US"
    folded = fold(name)
    for cc, rx in _CC_MARKERS_RX:
        if rx.search(folded):
            return cc
    return ""


def build(pool: dict, limit: int) -> tuple[list, list]:
    # A domain may publish several account names; a bare string is still
    # accepted so a cached crawl (and the tests' fixtures) keep working.
    names_of = {d: (list(v) if isinstance(v, list) else [v]) for d, v in pool.items()}

    # --- seed core: curated display names for the best-known institutions ----
    #
    # `_BAD_ACCOUNT` is applied PER NAME, and a domain survives if any of its
    # names is clean. It used to be applied to whichever name the crawl
    # happened to store first, which silently excluded the domain from seeding
    # altogether - and the name it happened to store was an artefact of
    # alphabetical search order, not a fact about the institution.
    #
    # Measured on the real crawl: `canvas.lms.unimelb.edu.au` publishes BOTH
    # "The University of Melbourne (non-SSO)" and "The University of
    # Melbourne". The first one matched `_BAD_ACCOUNT`, so the seed "University
    # of Melbourne" found no candidate at all and the domain fell through to
    # the fill path - which is why Australia's best-known university shipped
    # without its curated name and, once ranking existed, ranked below
    # Melbourne Grammar School for the query `melbourne`.
    usable = []
    for d, names in names_of.items():
        if _BAD_ACCOUNT.search(d):
            continue
        clean = [n for n in names if not _BAD_ACCOUNT.search(n)]
        if clean:
            usable.append((d, best_account_name(clean)))
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
                best = (key, {"name": display_name(seed), "domain": dom, "cc": cc,
                              # The picker's only "many people mean this one"
                              # signal. A seed is here because a human judged
                              # the institution well known, which is exactly
                              # the judgement no text score can make - without
                              # it the query `melbourne` ranks Melbourne
                              # Business School above the University of
                              # Melbourne, on the grammatical accident that its
                              # name starts with the word.
                              "flags": "s"})
        if best is None:
            continue
        if REJECT.get(seed) == best[1]["domain"]:
            rejected.append((seed, best[1]["domain"]))
            continue
        core.append(best[1])

    # --- direct: live tenants the finder does not publish at all -------------
    #
    # A THIRD source, and the only one that does not begin with the crawl. The
    # account finder lists accounts that opted into discovery, which is not the
    # set of live tenants - `harvard.instructure.com` answers as Canvas and is
    # nowhere in the crawl - so a market can look empty when it is merely
    # undiscoverable. India held ONE institution against 33 Store installs.
    #
    # These rows carry a hand-checked identification (see the module docstring
    # in `institution_direct.py`), and they still go through `verify_many`
    # below like everything else, so a stale host drops out by itself. Placed
    # after `core` and before `fill` so a curated name outranks a crawled one
    # and neither can be evicted by an account that merely sorts earlier.
    for _name, _dom, _cc in DIRECT:
        if _dom in {c["domain"] for c in core} or _dom in REJECT_DOMAINS:
            continue
        core.append({"name": _name, "domain": _dom, "cc": _cc, "flags": "s"})

    # --- fill: accounts under their OWN name (no pairing risk whatsoever) ----
    used = {c["domain"] for c in core}
    fill = []
    for dom, names in names_of.items():
        if dom in used or dom in REJECT_DOMAINS:
            continue
        # The most informative of the names published here - an account titled
        # both "TIP" and "Technological Institute of the Philippines" is
        # unfindable under the first and obvious under the second.
        name = best_account_name(names)
        if not is_institution(name, dom):
            continue
        # A hand-written label wins, and it is consulted BEFORE the name gates
        # rather than after. It exists because a human looked at this exact
        # account and decided what it is; re-testing their answer with the
        # heuristics they were overriding is how four real tenants were
        # dropped outright - "Western Sydney Online", "USC Online",
        # "University of York" (online) and Wits's online school all lose
        # their education word to `clean_name`'s trailing-"Online" strip and
        # then fail the re-test, so the rename never got the chance to apply.
        # Missing is safer than wrong, but a renamed row is neither.
        nm = RENAME.get(dom)
        if nm is None:
            nm = clean_name(re.split(r"\s+\|\s+", name)[0])
            # Re-test the CLEANED name: `clean_name` strips parentheticals and
            # everything after " - ", so the education word can be the thing it
            # just removed, leaving a label that names no institution at all.
            if not (4 <= len(nm) <= 64) or not _EDUCATION.search(fold(nm)):
                continue
        fill.append({"name": nm, "domain": dom,
                     "cc": infer_cc(nm, dom), "flags": ""})
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
    body = "\n".join("    (%s, %s, %s, %s)," % (_q(r["name"]), _q(r["domain"]),
                                                _q(r["cc"]), _q(r.get("flags", "")))
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

``country`` may be empty. It is PROVEN by the domain's ccTLD where there is
one, and otherwise inferred from unambiguous markers in the institution's own
name ("Erhvervsakademi" is Danish, "ISD" is a US school district) - see
``infer_cc``. It is used to widen the search haystack and to decide which
institutions the picker offers before anything is typed, and it is never
displayed as a claim about the institution, so an unknown country costs one
row's place in a suggestion list and nothing else.

``flags`` marks how the row was chosen: ``"s"`` for one of the curated seeds in
``scripts/institution_seeds.py``, ``""`` for an account taken from the crawl
under its own name. The picker uses it as its only "many people mean this one"
signal, which is what keeps a query like ``melbourne`` from answering with
Melbourne Business School.

Shipped as a ``.py`` rather than a data file on purpose: a module is picked up
by PyInstaller's import graph automatically, so neither spec file needs a
``datas`` entry that could be added on one platform and forgotten on the other.
"""
from __future__ import annotations

# (display name, canvas domain, ISO 3166-1 alpha-2 country or "", flags)
DATA: tuple[tuple[str, str, str, str], ...] = (
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
    ap.add_argument("--crawl-only", action="store_true",
                    help="crawl and save, then stop - skips the slow verify pass")
    ap.add_argument("--verify-cache",
                    help="JSON {domain: verdict} reused instead of re-verifying; "
                         "updated in place after the run")
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
    if args.crawl_only:
        print("--crawl-only: nothing built")
        return 0

    if args.verify_cache:
        load_verify_cache(Path(args.verify_cache))

    rows, rejected = build(pool, args.limit)
    if args.verify_cache:
        save_verify_cache(Path(args.verify_cache))
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
