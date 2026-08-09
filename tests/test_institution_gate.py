"""The FILL gate: which accounts count as an educational institution.

The app is for every institution and every level that uses Canvas, not only
universities. The generator's old ``_HIGHER_ED`` allowlist encoded the opposite,
and in a way that failed twice over: it named only English/Spanish/Portuguese/
German HIGHER-ED words, so it dropped non-universities everywhere AND dropped
institutions of every level whose own published name is Nordic, Finnish, Dutch,
French or Italian. Denmark shipped two entries.

Two properties are pinned here, and the second is the one that matters:

  * the gate accepts real institutions across levels and languages, and still
    refuses things that are not schools;
  * **widening it cannot move a single SEED pairing.** The seed path pairs a
    curated name with somebody else's domain and is where a wrong university
    comes from; the fill path maps an account's own name onto its own domain
    and has nothing to mispair. They are gated by different regexes on purpose
    (``_BAD_ACCOUNT`` vs ``is_institution``), and that separation is what makes
    coverage safe to increase. tests/test_institution_picker.py pins the
    matcher itself.
"""
from __future__ import annotations

import importlib.util
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _builder():
    p = ROOT / "scripts" / "build_institution_list.py"
    spec = importlib.util.spec_from_file_location("_bil_gate", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BIL = _builder()


# -- The gate accepts real institutions, across levels and languages ---------
# Every Danish row here was verified live against /api/v1/users/self on
# 2026-08-09 and every one of them was excluded by the old gate.
_MUST_ACCEPT = [
    ("Erhvervsakademi Aarhus", "eaaa.instructure.com"),
    ("Den Danske Filmskole", "filmskolen.instructure.com"),
    ("VUC Roskilde", "vucroskilde.instructure.com"),
    ("Royal Danish Academy of Music", "dkdm.instructure.com"),
    ("IBA International Business Academy", "iba.instructure.com"),
    # Nordic families the old regex could not express at all.
    ("Høgskolen i Molde", "himolde.instructure.com"),
    ("Högskolan i Skövde", "his.instructure.com"),
    ("Københavns Professionshøjskole", "kp.instructure.com"),
    ("Göteborgs Universitet", "canvas.gu.se"),
    ("Norges Musikkhøgskole", "nmh.instructure.com"),
    ("Háskóli Íslands", "hi.instructure.com"),
    ("Tampereen yliopisto", "tuni.instructure.com"),
    ("Metropolia Ammattikorkeakoulu", "metropolia.instructure.com"),
    # Other languages.
    ("Fachhochschule Bern", "fhb.instructure.com"),
    ("Université de Montréal", "udem.instructure.com"),
    ("Hogeschool Rotterdam", "hr.instructure.com"),
    ("Università di Bologna", "unibo.instructure.com"),
    ("Universidade de Lisboa", "ulisboa.instructure.com"),
    # Levels below university, which are in scope.
    ("Lincoln High School", "lincoln.instructure.com"),
    ("Springfield ISD", "springfield.instructure.com"),
    ("Riverside Charter School", "riverside.instructure.com"),
]


@pytest.mark.parametrize("name,domain", _MUST_ACCEPT)
def test_gate_accepts_real_institutions(name, domain):
    assert BIL.is_institution(name, domain), (
        f"{name!r} was refused by the fill gate; it is a real institution and "
        "the app is not university-only"
    )


# -- ...and still refuses what is not a school, or is a side entrance --------
_MUST_REFUSE = [
    ("Acme Corp Training", "acme.instructure.com"),
    ("Grace Church", "grace.instructure.com"),
    ("Riverbend Ministry", "riverbend.instructure.com"),
    ("Mercy Hospital", "mercy.instructure.com"),
    ("Widget Inc", "widget.instructure.com"),
    ("Elite Driving School", "elitedriving.instructure.com"),
    ("Sunrise Beauty School", "sunrise.instructure.com"),
    ("Ridgeview Dance Academy", "ridgeviewdance.instructure.com"),
    ("Some University Sandbox", "sandbox.instructure.com"),
    ("Harvard Alumni", "alumni.instructure.com"),
    ("State University Catalog", "catalog.instructure.com"),
    ("Anytown University Continuing Education", "anytownce.instructure.com"),
    ("Random Consulting", "random.instructure.com"),
]


@pytest.mark.parametrize("name,domain", _MUST_REFUSE)
def test_gate_refuses_non_institutions_and_sub_tenants(name, domain):
    assert not BIL.is_institution(name, domain), (
        f"{name!r} passed the fill gate; it is not an institution a student "
        "would pick, and every such row costs precision in the picker"
    )


def test_a_name_with_no_education_word_at_all_is_refused():
    """The gate is an allowlist, not just a blocklist - otherwise every
    corporate Canvas customer the blocklist happens not to name gets in."""
    assert not BIL.is_institution("Northwind Holdings", "northwind.instructure.com")


# -- fold() ------------------------------------------------------------------
def test_fold_maps_the_letters_nfkd_will_not():
    """o-slash, ae and eszett are letters, not accented forms, so NFKD leaves
    them alone. Without the explicit map a Danish or German name never matches
    the ASCII table."""
    for raw, want in (("ø", "o"), ("æ", "ae"), ("å", "a"),
                      ("ß", "ss"), ("Ø", "o"), ("Å", "a")):
        assert BIL.fold(raw) == want, f"fold({raw!r}) != {want!r}"


def test_fold_strips_combining_marks_and_lowercases():
    assert BIL.fold("GÖTEBORGS") == "goteborgs"
    assert BIL.fold("Université") == "universite"
    # NFKD-decomposed input must fold the same as the precomposed form.
    assert BIL.fold(unicodedata.normalize("NFD", "ü")) == BIL.fold("ü")


# -- THE SAFETY PROPERTY -----------------------------------------------------
def _pool():
    """A pool holding one genuine seed target plus decoys the fill gate rules
    on. ``bc.instructure.com`` is the Boston College decoy the matcher tests
    already use - it must never become Boston University's row."""
    return {
        "bu.instructure.com": "Boston University",
        "bc.instructure.com": "Boston College",
        "eaaa.instructure.com": "Erhvervsakademi Aarhus",
        "lincoln.instructure.com": "Lincoln High School",
        "northwind.instructure.com": "Northwind Holdings",
    }


def _build_no_network(monkeypatch, permissive: bool):
    monkeypatch.setattr(BIL, "verify_many",
                        lambda domains, workers=16: {d: "ok" for d in domains})
    if permissive:
        monkeypatch.setattr(BIL, "is_institution", lambda name, domain: True)
    rows, _rejected = BIL.build(_pool(), limit=50)
    return rows


def test_widening_the_fill_gate_cannot_move_a_seed_pairing(monkeypatch):
    """The whole reason coverage could be raised without re-auditing pairings.

    Seed rows are gated by ``_BAD_ACCOUNT``; fill rows by ``is_institution``.
    Force the fill gate wide open and every seed row must be identical - if
    this fails, the two paths have been wired together and a coverage change is
    once again a mismatch risk.
    """
    seed_names = {BIL.display_name(s) for s, _cc in BIL.SEEDS}

    strict = _build_no_network(monkeypatch, permissive=False)
    monkeypatch.undo()
    wide = _build_no_network(monkeypatch, permissive=True)

    def seeds_of(rows):
        return sorted((r["name"], r["domain"]) for r in rows if r["name"] in seed_names)

    assert seeds_of(strict), "the fixture produced no seed rows; test is vacuous"
    assert seeds_of(strict) == seeds_of(wide), (
        "opening the fill gate changed a seed pairing - the two paths are no "
        "longer independent"
    )


# -- The seed tiebreak: campus tenants score IDENTICALLY -------------------
#
# `jaccard` scores token SETS, so every "University of X - <campus>" variant is
# an exact 1.00 against the seed, and corroboration and ccTLD tie with them.
# Before `domain_rank` was added to the key, the winner among equals was
# whichever the crawl dict yielded first. Measured 2026-08-09 on the real
# crawl: the seed "University of Michigan" settled on DEARBORN and "University
# of Kansas" on `kuconnect` - a student picking their own university by name
# got a different campus. This is the same wrong-institution class as the ten
# in tests/test_institution_picker.py, reached by a different route.
_TIEBREAK = [
    ("University of Michigan", {
        "m.canvas.umich.edu": "University of Michigan - Ann Arbor",
        "canvas.umd.umich.edu": "University of Michigan - Dearborn",
        "canvas.flint.umich.edu": "University of Michigan - Flint",
    }, "m.canvas.umich.edu"),
    ("University of Kansas", {
        "canvas.ku.edu": "University of Kansas - KU",
        "kuconnect.ku.edu": "University of Kansas - kuconnect.ku.edu",
    }, "canvas.ku.edu"),
]


@pytest.mark.parametrize("seed,pool,expected", _TIEBREAK)
@pytest.mark.parametrize("order", ["as-written", "reversed"])
def test_the_main_campus_wins_a_tie_between_an_institutions_own_tenants(
    monkeypatch, seed, pool, expected, order
):
    """BOTH orderings, because crawl order is exactly what must not decide it.

    The first version of this test only fed the pool in one order - with the
    right answer first - so it passed with the fix REMOVED. A tie test that
    does not present the tie in the losing order is testing nothing.
    """
    items = list(pool.items())
    if order == "reversed":
        items.reverse()
    monkeypatch.setattr(BIL, "verify_many",
                        lambda domains, workers=16: {d: "ok" for d in domains})
    rows, _ = BIL.build(dict(items), limit=50)
    want = BIL.display_name(seed)
    got = [r for r in rows if r["name"] == want]
    assert got, f"the seed {seed!r} produced no row from {sorted(pool)}"
    assert got[0]["domain"] == expected, (
        f"{want!r} points at {got[0]['domain']} instead of {expected} with the "
        f"pool in {order} order - the seed ranking is deciding a tie by crawl "
        "order again"
    )


def test_a_pre_college_tenant_never_outranks_the_university_itself():
    """`app.opvs.georgetown.edu` won on ccTLD and then evicted Georgetown's own
    account in the dedupe. It is a real programme, but it is not the
    university, and `_BAD_ACCOUNT` is what keeps it out of the seed pool."""
    for name in ("Georgetown University - Pre-College & Visiting Student Programs",
                 "Somewhere University Pre College"):
        assert BIL._BAD_ACCOUNT.search(name), f"{name!r} reached the seed pool"


def test_the_seed_pool_is_gated_by_bad_account_and_not_by_the_fill_gate():
    """Structural counterpart: the separation must be visible in ``build``."""
    src = (ROOT / "scripts" / "build_institution_list.py").read_text(encoding="utf-8")
    body = src[src.index("def build("):]
    usable = body[:body.index("for seed, cc in SEEDS")]
    assert "_BAD_ACCOUNT" in usable, "the seed pool no longer uses _BAD_ACCOUNT"
    assert "is_institution" not in usable, (
        "the fill gate now also filters the seed pool; widening coverage would "
        "again change which account a curated name can pair with"
    )


def test_an_ambiguous_initialism_is_not_evidence():
    """"USC" is the initialism of BOTH the University of South Carolina and the
    University of Southern California, and the account on
    ``courses.online.usc.edu`` is called simply "USC Online" - so the
    initialism path accepted it for whichever seed reached it first, and the
    dedupe then kept the alphabetically earlier name. Shipped result: South
    Carolina pointing at Southern California's tenant, AND Southern California
    missing from the list entirely, its domain already taken.

    The initialism branch is the strictest in ``accepts`` and the only one that
    can fire on zero token overlap, so an ambiguous acronym reaching it is not
    weak evidence - it is none.
    """
    assert "usc" in BIL._AMBIGUOUS_ACRONYMS
    # A host with NO sub-tenant word in it, so the initialism branch is the one
    # actually under test. The shipped case (courses.online.usc.edu) is vetoed
    # earlier by `domain_is_subtenant`, so asserting on it alone passes with
    # this guard deleted - it proves the other rule, not this one.
    for seed in ("University of South Carolina", "University of Southern California"):
        assert not BIL.accepts(seed, "US", "usc.instructure.com", "USC"), (
            f"{seed!r} claims a host through an initialism two universities share"
        )
        assert not BIL.accepts(seed, "US", "courses.online.usc.edu", "USC Online"), (
            f"{seed!r} still claims a host it can only reach through an "
            "initialism that two universities share"
        )
    # ...while an UNambiguous one still works, or the guard has simply disabled
    # the branch it was meant to narrow.
    assert "ubc" not in BIL._AMBIGUOUS_ACRONYMS
    assert BIL.accepts("University of British Columbia", "CA",
                       "canvas.ubc.ca", "UBC Canvas")


def test_the_crawl_paginates_past_sixty_pages():
    """The finder has no result cap: measured 2026-08-09, letter 'a' ends at
    page 94 and 'e' at 106. The old ``range(1, 61)`` therefore discarded ~40%
    of every common letter - on 'a' alone, pages 61-94 hold 2,433 domains the
    crawl never saw, 1,400 of which pass ``is_institution``.

    A cap that reads as generous and silently truncates is the worst kind, so
    pin the floor rather than the exact value.
    """
    assert BIL._MAX_PAGES >= 150, (
        f"_MAX_PAGES is {BIL._MAX_PAGES}; a common letter needs ~110 pages and "
        "a cap near that truncates the crawl without saying so"
    )
    src = (ROOT / "scripts" / "build_institution_list.py").read_text(encoding="utf-8")
    body = src[src.index("def crawl("):]
    body = body[:body.index("def best_account_name(")]
    assert "_MAX_PAGES" in body, "crawl() no longer honours the page bound"
    assert "range(1, 61)" not in body


def test_a_domain_is_seedable_when_ANY_of_its_names_is_clean(monkeypatch):
    """`_BAD_ACCOUNT` is applied per NAME, and a domain survives if one of its
    names is clean. Applied to whichever name the crawl stored first - an
    artefact of alphabetical search order - it excluded the domain from seeding
    outright.

    Measured on the real crawl: `canvas.lms.unimelb.edu.au` publishes both "The
    University of Melbourne (non-SSO)" and "The University of Melbourne". The
    first matches `_BAD_ACCOUNT`, so the seed found no candidate and Australia's
    best-known university shipped without its curated name - and, once ranking
    existed, below Melbourne Grammar School for the query `melbourne`.
    """
    monkeypatch.setattr(BIL, "verify_many",
                        lambda domains, workers=16: {d: "ok" for d in domains})
    pool = {"canvas.lms.unimelb.edu.au": ["The University of Melbourne (non-SSO)",
                                          "The University of Melbourne"]}
    rows, _ = BIL.build(pool, limit=10)
    got = [r for r in rows if r["domain"] == "canvas.lms.unimelb.edu.au"]
    assert got, "the domain was excluded from seeding by its dirtier name"
    assert got[0]["name"] == "University of Melbourne", got[0]
    assert got[0]["flags"] == "s", "a seeded row must carry the prominence flag"


def test_a_hand_written_rename_is_not_re_tested_by_the_heuristics(monkeypatch):
    """RENAME exists because a human looked at this account and decided what it
    is. Re-running the name gates on their answer dropped four real tenants:
    `clean_name` strips a trailing "Online", which is the only education word
    "Western Sydney Online" and "USC Online" have, so the re-test rejected them
    and the rename never got the chance to apply."""
    monkeypatch.setattr(BIL, "verify_many",
                        lambda domains, workers=16: {d: "ok" for d in domains})
    pool = {"canvas.westernsydneyonline.edu.au": ["Western Sydney Online"]}
    rows, _ = BIL.build(pool, limit=10)
    # Scoped to the domain under test:  also emits the DIRECT rows,
    # which are hand-verified tenants the crawl never sees.
    got = [r["name"] for r in rows if r["domain"] == "canvas.westernsydneyonline.edu.au"]
    assert got == ["Western Sydney University (Online)"], rows


def test_a_two_letter_tld_that_is_not_a_country_never_becomes_one():
    """`.eu` is two letters and supranational, so `cc_of` emitted the country
    code "EU" - a code no country table can name. Such a row is excluded from
    every regional suggestion list and asks the picker for a label that does
    not exist.

    Asserted on the FUNCTION, not on the shipped data: the data is regenerated,
    so a data-only check passes against a builder that has started emitting the
    bad code again and simply has not been re-run.
    """
    assert BIL.cc_of("canvas.example.eu") == ""
    assert BIL.infer_cc("Some University", "canvas.example.eu") == ""
    # ...and a real ccTLD still resolves, or the fix is just a blanket disable.
    assert BIL.cc_of("canvas.example.dk") == "DK"
    assert BIL.cc_of("canvas.example.edu") == "US"


def test_country_is_inferred_from_the_name_when_the_domain_says_nothing():
    """93% of the list is `*.instructure.com`, which carries no country signal,
    so before this the picker's opening list had almost nothing to work with -
    Denmark had two rows with a country while five more Danish institutions
    shipped as country-unknown."""
    assert BIL.infer_cc("Erhvervsakademi Aarhus", "eaaa.instructure.com") == "DK"
    assert BIL.infer_cc("VUC Roskilde", "vucroskilde.instructure.com") == "DK"
    assert BIL.infer_cc("Giles County Schools - VA", "gilesk12.instructure.com") == "US"
    assert BIL.infer_cc("Tippecanoe School District", "tsc.instructure.com") == "US"
    # A proven ccTLD always wins over a guess from the name.
    assert BIL.infer_cc("Erhvervsakademi Aarhus", "canvas.eaaa.se") == "SE"
    # ...and an unknown stays unknown. Inventing one to avoid an empty string
    # is exactly the confident wrong answer this module exists to avoid.
    assert BIL.infer_cc("Riverside Academy", "riverside.instructure.com") == ""


def test_clean_name_keeps_the_tail_that_says_WHICH_institution_this_is():
    """`clean_name` exists to collapse tenant qualifiers, and it used to strip
    every parenthetical and everything after a dash unconditionally. That is
    right for "The University of Melbourne (non-SSO)" and a falsehood for
    "University of Tennessee - Martin", which it turned into "University of
    Tennessee" - promoting a branch campus into a claim on the whole
    university, on the fill path, where no pairing gate can see it.

    Note this uses a DIFFERENT rule from the pairing veto (`tail_tokens`, not
    `qualifier_tokens`). The veto was deliberately narrowed to
    institution-like tails so it would stop rejecting "University of Michigan -
    Ann Arbor"; display must stay broad, or the narrowing silently re-breaks
    every campus label.
    """
    keeps = {
        "University of Tennessee - Martin": "University of Tennessee - Martin",
        "Universidad de los Andes - Chile": "Universidad de los Andes - Chile",
        "University of Michigan - Ann Arbor": "University of Michigan - Ann Arbor",
        "University of Arizona - College of Public Health":
            "University of Arizona - College of Public Health",
        "Xavier University - Ateneo de Cagayan": "Xavier University - Ateneo de Cagayan",
    }
    for raw, want in keeps.items():
        assert BIL.clean_name(raw) == want, f"{raw!r} lost the tail that identifies it"

    drops = {
        "The University of Melbourne (non-SSO)": "The University of Melbourne",
        "Central Philippine University (CPU)": "Central Philippine University",
        "Brentwood School District - Students/Teachers": "Brentwood School District",
        "Far Eastern University (FEU)": "Far Eastern University",
    }
    for raw, want in drops.items():
        assert BIL.clean_name(raw) == want, f"{raw!r} kept a tenant qualifier"


def test_clean_name_keeps_qualifiers_in_source_order():
    """The tail used to be rebuilt by concatenating every parenthetical AHEAD
    of every dash-tail, which rewrites the name: "TOS - The Olympia Schools
    (Teacher, Student)" came out as "TOS - Teacher, Student The Olympia
    Schools". Segments are judged one at a time and kept where they were."""
    assert BIL.clean_name("TOS - The Olympia Schools (Teacher, Student)") == \
        "TOS - The Olympia Schools"
    assert BIL.tail_segments("A (one) - two - (three)") == ["one", "two", "three"]


def test_build_emits_the_direct_tenants_even_with_an_empty_crawl(monkeypatch):
    """Asserted on `build`, not on the shipped data.

    A data-only check passes against a builder that has stopped emitting these
    rows and simply has not been re-run - the same hole the `.eu` country test
    had. With an empty pool there is nothing BUT the direct source, so the
    assertion is exact.
    """
    from institution_direct import DIRECT
    monkeypatch.setattr(BIL, "verify_many",
                        lambda domains, workers=16: {d: "ok" for d in domains})
    rows, _ = BIL.build({}, limit=500)
    got = {(r["name"], r["domain"], r["cc"], r["flags"]) for r in rows}
    want = {(n, d, cc, "s") for n, d, cc in DIRECT}
    assert got == want, f"build() did not emit the DIRECT tenants\n got={got}\nwant={want}"


def test_a_country_marker_must_be_unambiguous_in_practice():
    """Each marker is a word that means ONE thing. Three did not, and each put
    a real institution in the wrong country's suggestion list: "indian school"
    is a Native American school in the United States, "islands" caught
    California State University Channel Islands, and "city college of" is a US
    pattern that moved San Francisco to the Philippines."""
    # "" is the right answer, not a US guess: none of these carries a marker
    # that means one thing, and an unknown country costs one row a place in a
    # suggestion list while a wrong one puts it in the wrong country entirely.
    for name, dom in (("Red Cloud Indian School", "redcloudschool.instructure.com"),
                      ("California State University, Channel Islands", "csuci.instructure.com"),
                      ("City College of San Francisco", "ccsf.instructure.com"),
                      ("Association of Commonwealth Universities", "aculms.instructure.com")):
        assert BIL.infer_cc(name, dom) == "", f"{name} was given a country it has no claim to"
    # ...and the markers that ARE unambiguous still fire.
    assert BIL.infer_cc("Universiti Brunei Darussalam", "ubd.instructure.com") == "MY"
    assert BIL.infer_cc("VUC Roskilde", "vucroskilde.instructure.com") == "DK"
