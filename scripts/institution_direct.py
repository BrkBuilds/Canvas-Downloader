"""Institutions whose Canvas is LIVE but which the account finder never lists.

WHY THIS FILE EXISTS
    The crawl in ``build_institution_list.py`` reads Instructure's public
    account finder, and that finder only publishes accounts which opted into
    discovery. It is NOT the set of live tenants, and the gap is not small:
    ``harvard.instructure.com`` answers as Canvas and appears nowhere in the
    crawl. Measured 2026-08-09, a targeted sweep of ~1,300 plausible slugs
    found **72 live Canvas hosts**, 26 of them for institutions the shipped
    list did not have.

    So a third source: hand-curated ``(display name, host, country)`` rows that
    go through exactly the same verification as everything else. A wrong host
    here cannot survive - it simply fails ``verify_domain`` and is dropped.

THE HARD PART IS NOT FINDING A HOST, IT IS PROVING WHOSE IT IS
    A host answering as Canvas says nothing about which institution owns it,
    and slug guessing is wrong far more often than it looks. Of the 72 live
    hosts above, 46 were already in the crawl **under names that contradicted
    the guess**:

        rhodes.instructure.com    -> Rhodes COLLEGE (Memphis), not Rhodes University ZA
        nwu.instructure.com       -> Northwestern University PHILIPPINES, not North-West ZA
        nu.instructure.com        -> NIHON University (Japan), not National University PH
        lpu.instructure.com       -> Life Pacific University (US), not Lovely Professional IN
        abu.instructure.com       -> Arlington Baptist, not Ahmadu Bello NG
        landmark.instructure.com  -> Landmark College (US), not Landmark University NG
        msu.instructure.com       -> Michigan State, not Mindanao State
        boston.instructure.com    -> Boston College UK (EU data region), not Massachusetts

    Shipping those guesses would have recreated, at scale, the exact
    wrong-university class this list spent a whole session eliminating. So
    every row below carries EVIDENCE, and the bar is a signal that names the
    institution - not a plausible slug:

      * a link to the institution's OWN domain in the login page, or
      * a branding logo whose uploaded FILENAME names it,
    corroborated where possible by the tenant's S3 data region (``apse1`` is
    Singapore, i.e. India/SEA; ``dub`` Ireland; the unsuffixed bucket us-east-1).

    Candidates that answered as Canvas but could not be IDENTIFIED were left
    out on purpose - `usp`, `fgv`, `insper`, `mackenzie`, `iie`, `milpark`,
    `wvsu`, `utec`, `vut`, `stadio`, `cti`, `afe`, `lbs`, `ul`, `apu`,
    `bennett`, `du`, `gems`, `snu`, `stonehill`, `upes`, `imi` all use default
    Canvas branding and publish nothing that names their owner. Missing is
    recoverable (the user types their address); wrong is not.

DO NOT TURN THIS INTO A SCANNER
    The sweep that produced these was a one-off, bounded and hand-reviewed. The
    answer to wanting more coverage is more EVIDENCE per candidate, not more
    candidates - an unidentified host is not a row, however many of them there
    are.
"""
from __future__ import annotations

#: (display name, canvas host, ISO 3166-1 alpha-2)
DIRECT: list[tuple[str, str, str]] = [
    # ── India ────────────────────────────────────────────────────────────
    # 33 Store installs and the crawl held exactly ONE Indian institution
    # (Krea). These three are the rest of what a wide sweep could PROVE.
    # logo `RU_Logos-02.png`, ap-southeast-1; the slug is unique worldwide.
    ("Rishihood University", "rishihood.instructure.com", "IN"),
    # logo `logo-xlri[1].svg`, ap-southeast-1.
    ("XLRI Jamshedpur", "xlri.instructure.com", "IN"),
    # logo `Inventure-logo.png`, ap-southeast-1. A K-12 international school
    # in Bangalore - kept because the app is for every level.
    ("Inventure Academy", "inventureacademy.instructure.com", "IN"),

    # ── Brazil (12 installs, the crawl held a handful) ───────────────────
    # login page links sgl.icei.pucminas.br - the institution's own domain.
    ("Pontifícia Universidade Católica de Minas Gerais", "pucminas.instructure.com", "BR"),
    # logo `logo-unip-home.png`.
    ("Universidade Paulista", "unip.instructure.com", "BR"),
    # logo `senac_logo.png`.
    ("Senac", "senac.instructure.com", "BR"),

    # ── Andes / LatAm ────────────────────────────────────────────────────
    # logo `logo_usfq_Login.png`. Ecuador is 7 installs and had almost nothing.
    ("Universidad San Francisco de Quito", "usfq.instructure.com", "EC"),
    # login page links campusvirtual.unitec.edu.co - COLOMBIA, not the
    # Honduran UNITEC the slug suggests. Exactly why identification is required.
    ("UNITEC Colombia", "unitec.instructure.com", "CO"),

    # ── Indonesia ────────────────────────────────────────────────────────
    # logo `logougm_left.png`.
    ("Universitas Gadjah Mada", "ugm.instructure.com", "ID"),
]
