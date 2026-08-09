"""Hand-review rejections for ``scripts/build_institution_list.py``.

Each entry is a (seed, domain) pairing the automated gates accepted and a human
found to be a DIFFERENT institution. They are kept here, with reasons, rather
than fixed by loosening a threshold, because every one of them is a same-name
collision that no name- or domain-based heuristic can separate:
"University of Miami" and "Miami University" (Ohio) are both real universities
whose names share every token, and both own a corroborating domain.

This list is the last gate before shipping, and it exists because the cost is
asymmetric: omitting a school costs one student one extra paste into a field
that is right there, while a wrong entry hands them a real, working Canvas
login page belonging to a different university and offers no clue that the
address was the problem.

Re-run the builder after editing; ``tests/test_institution_picker.py`` asserts
none of these domains survives into the shipped module.
"""
from __future__ import annotations

# seed name -> domain that must never be paired with it
REJECT: dict[str, str] = {
    # Different country, near-identical name.
    "University of South Australia": "usaonline.southalabama.edu",   # University of South Alabama
    "Queens University": "canvas.queens.edu",                        # Queens University of Charlotte, US
    "Western University": "western.instructure.com",                 # Western Colorado University
    "University of Miami": "miamioh.instructure.com",                # Miami University, Ohio
    "North-West University": "northpark.instructure.com",            # North Park University, US
    "Central European University": "centralstate.instructure.com",   # Central State University, US
    "Hebrew University of Jerusalem": "hebrewrootsuniversity.instructure.com",
    "Catholic University of Portugal": "catholiciu.instructure.com",
    "King Saud University": "king.instructure.com",                  # "King University Student"
    "Trinity College Dublin": "trinitygladstone.instructure.com",    # Trinity College - Gladstone

    # Shares a place name with an unrelated institution.
    "Portland State University": "portland.instructure.com",         # University of Portland
    "Smith College": "smithchason.instructure.com",                  # Smith Chason College
    "University of Arizona": "arizonachristian.instructure.com",
    "University of Arkansas": "arkansasstateuniversity.instructure.com",
    "University of Kansas": "canvas.kansascity.edu",                 # Kansas City University
    # NC State vs UNC Charlotte. The Charlotte tenant publishes itself
    # correctly, but `clean_name` strips the campus off " - Charlotte" and what
    # is left shares every distinctive token with this seed, on a host
    # (`charlotte.edu`) that vouches for the one word that would have separated
    # them. Measured 2026-08-09: the seed took it, and because core rows beat
    # fill rows in the dedupe the RENAME below never applied - so the row
    # shipped as "North Carolina State University" pointing at UNC Charlotte,
    # and Charlotte lost its own entry. NC State keeps a row either way: its
    # own tenant publishes as "NC State University" and arrives through FILL.
    "North Carolina State University": "instructure.charlotte.edu",
    "University of Missouri": "missouriwestern.instructure.com",
    "University of Nebraska Lincoln": "lincoln.instructure.com",     # Lincoln University
    "University of Oklahoma": "oklahomachristian.instructure.com",
    "University of Rochester": "rochesterchristianu.instructure.com",

    # Acronym collision on a shared initialism.
    "Austin Community College": "acc.instructure.com",               # Anguilla Community College
    "Houston Community College": "hcc.instructure.com",              # Hillsborough Community College

    # A sub-unit or secondary tenant, not the institution's student Canvas.
    "New York University": "steinhardt-nyu.instructure.com",         # one NYU school only
    "Liberty University": "libertyce.instructure.com",               # continuing-education tenant

    # Too ambiguous to verify.
    "Universitat Politecnica de Valencia": "politecnica.instructure.com",
    "York University": "york1.instructure.com",

    # ── Found in the shipped list on 2026-08-08, all ten live ────────────────
    # Every one of these reached users: the picker offered a real, working
    # Canvas login page belonging to a DIFFERENT university, which is the exact
    # failure this file exists to stop.
    #
    # READ THIS BEFORE ADDING THE NEXT ENTRY. Four of the ten domains were
    # ALREADY listed above as a trap - for a different seed. `northpark` was
    # blocked for "North-West University" and then captured "University of
    # North Texas"; `centralstate` was blocked for "Central European
    # University" and captured "University of Central Florida";
    # `oklahomachristian` was blocked for "University of Oklahoma" and captured
    # "Oklahoma State University"; `usaonline.southalabama.edu` was blocked for
    # "University of South Australia" and captured "University of South
    # Carolina". A hand-review gate keyed on ONE pairing cannot close a hole
    # that any similarly-shaped name walks straight back into - which is why
    # the real fix is `contradicts()` in the builder, and why these entries are
    # a backstop rather than the remedy.
    "University of British Columbia": "courseworks2.columbia.edu",   # Columbia University, US
    "Duke Kunshan University": "canvas.duke.edu",                    # Duke University, US
    "Colorado State University": "canvas.colorado.edu",              # U. of Colorado Boulder
    "Oklahoma State University": "oklahomachristian.instructure.com",# Oklahoma Christian U.
    "University of Central Florida": "centralstate.instructure.com", # Central State U., Ohio
    "University of North Texas": "northpark.instructure.com",        # North Park U., Chicago
    "University of South Carolina": "usaonline.southalabama.edu",    # U. of South Alabama
    "Manchester Metropolitan University": "canvas.manchester.ac.uk", # The University of Manchester
    "University of Western Australia": "western.instructure.com",    # Western Colorado University
    "American University in Dubai": "american.instructure.com",      # American University, Washington DC
}


# Domains dropped outright, whatever name they publish under.
#
# These are hand-identified because no NAME rule can reach them without
# collateral damage. "College" means a SECONDARY school across much of
# Australia and Ireland, and the accounts below are Catholic high schools -
# but they are spelled exactly like the real American liberal-arts colleges
# sitting beside them in the same list (Saint Anselm College, St. Norbert
# College, Saint Vincent College). Any regex broad enough to catch
# "St Aloysius' College" also catches those, so the list is enumerated instead.
REJECT_DOMAINS: dict[str, str] = {
    # Australian / Irish Catholic secondary schools.
    "riverview.instructure.com": "Saint Ignatius' College, Riverview - AU secondary",
    "staloysius.instructure.com": "St Aloysius' College, Sydney - AU secondary",
    "sec.instructure.com": "St Edmund's College Canberra - AU secondary",
    "sjc.instructure.com": "St Joseph's College Toowoomba - AU secondary",
    "mackillop.instructure.com": "St Mary MacKillop College - AU secondary",
    "sjccoomera.instructure.com": "St Joseph's College Coomera - AU secondary",
    "stscholastica.instructure.com": "St. Scholastica's College, Glebe - AU secondary",
    "stdominics.instructure.com": "St. Dominic's College - secondary",
    "saintpatricks.instructure.com": "St Patrick's College - secondary",
    "stmaryscollege.instructure.com": "St Mary's College - secondary",
    "oscott.instructure.com": "St Mary's College Oscott - seminary",

    # Not the institution's student Canvas: an ancillary tenant that happens to
    # publish under the university's name.
    "workforcecenter.instructure.com": "Saint Louis University workforce centre, not the university",
    "uwoms.instructure.com": "University of Washington Merchant Services - not an institution",

    # A domain serving SEVERAL unrelated organisations, so there is no name it
    # could ship under that is not wrong for somebody. Found 2026-08-09 while
    # tracing how "Eotvos Lorand University" came to point here: the finder
    # publishes both "ELU - European Leadership University" and "MCT -
    # Management Centre Turkiye" on this one host, and neither is ELTE.
    "elu.instructure.com": "two unrelated organisations share this host",
    "virtualcampus.instructure.com": "shared host - American University of Nigeria, "
                                     "Davis & Elkins, Oklahoma Panhandle State and others",
}


# Display-name overrides, by domain.
#
# For the case where an account is genuinely a real institution's Canvas but its
# self-declared name OVER-CLAIMS - it names the whole university while serving
# one school of it. Dropping such an account costs the students who actually use
# it; shipping it unchanged sends everyone else to a Canvas holding none of
# their courses. Renaming serves both, so prefer this over a rejection whenever
# the tenant is real and the only problem is the label.
RENAME: dict[str, str] = {
    # The only NYU account the finder publishes, and it is Steinhardt's.
    "steinhardt-nyu.instructure.com": "New York University (Steinhardt)",

    # This account publishes itself CORRECTLY as "University of North Carolina
    # - Charlotte"; it was `clean_name()` that broke it. That function splits a
    # name on " - " to collapse tenant qualifiers ("... - non-SSO"), and here
    # the tail is not a qualifier but the CAMPUS - so a correctly-named campus
    # tenant was promoted into a claim on the whole UNC system, sitting in the
    # list one row above the real Chapel Hill. Any "X - <campus>" account has
    # this shape; rename rather than drop, because its own students need it.
    "instructure.charlotte.edu": "University of North Carolina at Charlotte",

    # Same shape, via the PARENTHETICAL half of clean_name rather than the
    # " - " half: this account publishes as "The Hong Kong University of
    # Science and Technology (GuangZhou)" and the qualifier that is stripped is
    # the campus. Measured 2026-08-09 - it then outscored `canvas.ust.hk`, the
    # main Clear Water Bay campus, which publishes only as the acronym "HKUST"
    # and so has almost no token overlap with the seed. A student at the main
    # campus picked their own university's name and got Guangzhou's Canvas.
    # The ALIASES entry for the seed is the other half of this fix.
    # NOTE the qualifier is NOT parenthesised. `dedupe_key` runs `clean_name`
    # again on the finished label, so a "(...)" or " - ..." tail is stripped
    # right back off and the row collides with the one it was renamed to be
    # distinct FROM - measured: with "(Guangzhou)" this account vanished
    # entirely instead of sitting beside the main campus.
    "hkust-gz.instructure.com": "Hong Kong University of Science and Technology Guangzhou",

    # Tenants whose account name claims the whole institution while serving one
    # school or one mode of study. Each was traced from a shipped row on
    # 2026-08-09; the pairing gates now decline them for the SEED, but the fill
    # path still ships them under the name the account gives itself, which is
    # the over-claim these renames exist for. Real tenants with real students -
    # rename, never drop.
    "robinsongsu.instructure.com": "Georgia State University (Robinson College of Business)",
    "healtharizona.instructure.com": "University of Arizona (College of Public Health)",
    "onlinestudy.york.ac.uk": "University of York (Online)",
    "witsstudyonline.instructure.com": "University of the Witwatersrand (Online)",
    "canvas.westernsydneyonline.edu.au": "Western Sydney University (Online)",
    "courses.online.usc.edu": "University of Southern California (Online)",
    "utm.instructure.com": "University of Tennessee at Martin",
    # NOT uandes.instructure.com: the seed "Universidad de los Andes Chile"
    # takes that domain, so `fill` never sees it and a rename here would be
    # dead config that reads as an applied decision.
}
