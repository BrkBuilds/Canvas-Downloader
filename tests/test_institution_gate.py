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
