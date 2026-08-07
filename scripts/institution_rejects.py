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
}
