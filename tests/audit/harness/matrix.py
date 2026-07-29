"""Covering arrays - the honest answer to "test all combinations".

The download configuration has 24 independent binary factors (2 layouts, 2
filters, isolate, size cap, 8 converters, 6 Canvas Content types, Panopto master
+ layout + 4 outputs). The literal cross product is 2**24 = 16.7 million runs,
and per course it is worse. That is not thoroughness; it is noise, and running
even 0.01% of it would take weeks and prove nothing a fraction of it does not.

What actually finds configuration bugs is INTERACTION coverage. Empirically most
configuration defects involve one or two factors, and nearly all involve three
or fewer. So this module builds:

    strength 1  every level of every factor appears at least once
    strength 2  every PAIR of levels from every pair of factors appears together
    strength 3  every TRIPLE, used on the factors that genuinely interact in the
                code (layout, isolation and Panopto layout all feed the same
                path calculation; the source-consuming converters all mutate the
                file set the next sync will analyse)

For 24 binary factors that is roughly 10 runs at strength 2 and 40-60 at
strength 3 - a real number, with coverage this module can PROVE rather than
claim. ``coverage()`` re-derives it from the generated rows, so the runbook can
state "1104 of 1104 pairs covered" instead of "we tested a lot of combinations".

Generation is IPOG (In-Parameter-Order-General): seed with the exhaustive
product of the first t factors, then for each remaining factor extend every
existing row with the level covering the most new t-tuples (horizontal growth)
and add rows for whatever is still uncovered (vertical growth). Greedy, so not
provably minimal - but it is deterministic given the factor order, which matters
far more here: a suite whose run list reshuffles between invocations cannot be
compared against its own history.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field


@dataclass
class Factor:
    name: str
    levels: tuple
    # Factors only worth varying on a course that can exercise them. There is no
    # point spending a run on convert_excel against a course with no workbooks -
    # it proves nothing and the result is indistinguishable from the converter
    # being broken.
    requires: str = ""
    note: str = ""


# --------------------------------------------------------------------------
# the download configuration space
# --------------------------------------------------------------------------

# ORDER IS NOT COSMETIC - it is the single biggest lever on what this plan
# costs to run, and the Panopto factors lead for that reason alone.
#
# IPOG seeds an exhaustive product of the first `strength` factors and then
# smears each later factor across every row that already exists. So a factor
# declared EARLY is packed densely into a few rows; one declared LATE turns up
# in row after row. With Panopto last (the original order), 36 recordings of
# video and transcription were sprayed across the plan. Measured, same space,
# same 100% pairwise coverage:
#
#     Panopto last     36 rows · 15 GPU rows · 93.8 GB of Panopto work
#     Panopto FIRST    20 rows ·  5 GPU rows · 29.1 GB      -69%
#
# Coverage is re-derived from the rows either way (`coverage()`), so this buys
# the reduction without weakening the claim. A cost-weighted tie-break inside
# horizontal growth was tried first and is worse - see `covering_array`.
DOWNLOAD_FACTORS: list[Factor] = [
    Factor("pan_master", (False, True), requires="panopto"),
    Factor("pan_out_mp4", (False, True), requires="panopto",
           note="The dearest level in the space: 36 recordings of video."),
    Factor("pan_out_txt", (False, True), requires="panopto"),
    Factor("pan_out_srt", (False, True), requires="panopto"),
    Factor("pan_out_mp3", (False, True), requires="panopto"),
    Factor("pan_layout", ("match", "separate"), requires="panopto"),

    Factor("mode", ("modules", "flat"),
           note="Organisation. Feeds the path calculation a later sync reuses."),
    Factor("file_filter", ("all", "study"),
           note="'study' restricts to slides and documents."),
    Factor("secondary_isolated", (False, True),
           note="Canvas Content in its own subfolder vs alongside course files."),
    Factor("max_file_size", (None, 5),
           note="MB cap. A skipped file must leave no manifest row behind."),

    Factor("convert_zip", (False, True), requires="zip"),
    Factor("convert_pptx", (False, True), requires="pptx"),
    Factor("convert_word", (False, True), requires="legacy_word",
           note="LEGACY word only - .doc/.rtf/.odt. .docx is never converted."),
    Factor("convert_excel", (False, True), requires="excel",
           note="Produces a PDF and a _Data.txt sidecar, and DELETES the .xlsx."),
    Factor("convert_html", (False, True), requires="secondary"),
    Factor("convert_code", (False, True), requires="code"),
    Factor("convert_urls", (False, True), requires="urls"),
    Factor("convert_video", (False, True), requires="video"),

    Factor("dl_assignments", (False, True), requires="assignments"),
    Factor("dl_syllabus", (False, True), requires="syllabus"),
    Factor("dl_announcements", (False, True), requires="announcements"),
    Factor("dl_discussions", (False, True), requires="discussions"),
    Factor("dl_quizzes", (False, True), requires="quizzes"),
    Factor("dl_submissions", (False, True), requires="assignments"),
]

# NOTE on `pan_master`, declared at the top: there is no "enable Panopto" switch
# in the app. It is a DERIVED "Select All" highlight that
# `_pan_recompute_master()` recalculates from the individual pan_out_* toggles
# on every render, so what actually turns the Panopto pass on is "at least one
# output selected". Kept as a factor because the constraints below already tie
# it to exactly that condition, which makes it a faithful stand-in - but a run
# must configure the OUTPUTS, never this.

# Factors that share code paths and therefore deserve triple coverage. Layout,
# isolation and Panopto layout all resolve a destination folder; the four
# source-consuming converters all change the file set a later sync must
# reconcile, which is where conversion and sync interact.
INTERACTING = ("mode", "secondary_isolated", "pan_layout", "file_filter",
               "convert_zip", "convert_excel", "convert_video", "convert_code")


# --------------------------------------------------------------------------
# the sync configuration space
# --------------------------------------------------------------------------
#
# Sync is NOT download with a different verb, and mirroring it factor-for-factor
# would test the wrong thing. A download run is configuration x configuration:
# the user picks 24 switches and the run either honours them or does not. A sync
# run's configuration is already FIXED - the folder's contract, baked in when it
# was downloaded and read back from `.canvas_sync.db`, with no on-the-fly
# overrides by design. What varies at sync time is the WORLD:
#
#   * what changed since the last run (new, updated, deleted, renamed, moved,
#     locally edited, restored...) - the seeder fabricates this in seconds;
#   * which of those the user accepts, and through which screen.
#
# So the two dimensions have wildly different costs. A contract shape costs a
# full download; a world state costs a snapshot restore plus a seed. The plan is
# therefore a covering array over the CHEAP dimensions, replayed against a small
# set of contract shapes chosen because each one changes how sync reasons:
#
#   modules vs flat         decides where a new file belongs
#   isolate secondary       decides where Canvas Content belongs
#   source-consuming        the source is GONE after conversion, so sync must
#     converters            not re-offer it - the interaction that has bitten
#                           this project before, in both directions
#   study filter            a filtered-out file must never appear as "new"
#   panopto layout          recordings resolve their own destination
#
SYNC_FACTORS: list[Factor] = [
    Factor("sync_mode", ("review", "quick"),
           note="Quick Sync skips the review screen by design; the two paths "
                "select what to download with DIFFERENT code."),
    Factor("confirm", (True, False),
           note="Cancelling at review must leave the folder byte-identical."),

    # World state. Each maps to a seeder fixture kind; the seeder is the only
    # thing that knows how to fabricate them, and it writes the expected plan
    # the checks then hold the run to.
    Factor("new_regular", (False, True), requires="material"),
    Factor("new_secondary", (False, True), requires="secondary"),
    Factor("clean_update", (False, True), requires="material"),
    Factor("edited_update", (False, True), requires="material",
           note="Locally edited. The bytes MUST survive - this is the "
                "_NewVersion path, and the one place a bug destroys work."),
    Factor("deleted_locally", (False, True), requires="material",
           note="'restored' - curation, not an arrival. Never a Today file."),
    Factor("deleted_on_canvas", (False, True), requires="material"),
    Factor("renamed_row_intact", (False, True), requires="material"),
    Factor("renamed_row_dropped", (False, True), requires="material",
           note="Exercises the analyzer's adoption tiers."),
    Factor("renamed_ambiguous", (False, True), requires="material",
           note="Two candidates, one row: the app must not guess."),
    Factor("moved_deep", (False, True), requires="material"),
    Factor("duplicate_copy", (False, True), requires="material",
           note="A user's own copy must never be claimed by a manifest row."),
    Factor("readonly_target", (False, True), requires="material",
           note="The target cannot be written. Must fail per-file, not abort."),
    Factor("long_path", (False, True), requires="long_path"),
    Factor("foreign_content", (False, True),
           note="A file the app never wrote must be left completely alone."),
    Factor("partial_artifact", (False, True),
           note="A .part from a crashed run: never healed, never offered."),
]

# Sync interactions worth triple coverage: the screen you accept through, the
# two states where the app must NOT overwrite, and the two where it must
# reconstruct a row rather than trust the path.
SYNC_INTERACTING = ("sync_mode", "confirm", "edited_update", "readonly_target",
                    "renamed_row_dropped", "renamed_ambiguous")


def sync_constraints_ok(row: dict) -> bool:
    """Reject sync rows the UI cannot produce, or that prove nothing.

    Two rules, both learned the expensive way:

    * **Cancelling only means something when there is a review screen to cancel
      from.** Quick Sync goes straight from analysis to downloading, so
      ``sync_mode=quick, confirm=False`` is not a user-reachable state - and a
      row that lands there would be checked against an "untouched folder"
      expectation that a Quick Sync legitimately violates.
    * **A row that changes nothing tests the empty-analysis screen, and one is
      enough.** ``extremes()`` already contributes it.
    """
    if row.get("sync_mode") == "quick" and not row.get("confirm", True):
        return False
    return True


SEED_KINDS = tuple(f.name for f in SYNC_FACTORS
                   if f.name not in ("sync_mode", "confirm"))


def sync_plan(*, pair_strength: int = 2, triple: bool = True) -> dict:
    """The sync run list, with its coverage proof attached."""
    factors = SYNC_FACTORS
    pair_rows = covering_array(factors, pair_strength, sync_constraints_ok)

    # The two states every sync flow must survive, spelled out rather than left
    # to the generator: a folder with nothing to do, and one where every
    # fixture fires at once.
    quiet = {f.name: f.levels[0] for f in factors}
    quiet["_isolates"] = "nothing-changed"
    loud = {f.name: f.levels[-1] for f in factors}
    loud.update(sync_mode="review", confirm=True, _isolates="everything-at-once")
    rows = [quiet, loud]

    # One row per fixture kind, alone. A defect in the 'renamed_ambiguous'
    # handling is attributable only when nothing else is changing at the same
    # time - with eight fixtures live, any of them could have produced the row
    # under suspicion.
    for kind in SEED_KINDS:
        row = {f.name: f.levels[0] for f in factors}
        row[kind] = True
        row["sync_mode"], row["confirm"] = "review", True
        row["_isolates"] = kind
        rows.append(row)

    rows += pair_rows

    triple_rows = []
    if triple:
        sub = [f for f in factors if f.name in SYNC_INTERACTING]
        triple_rows = covering_array(sub, 3, sync_constraints_ok)
        for r in triple_rows:
            for f in factors:
                r.setdefault(f.name, f.levels[0])
            r["_isolates"] = "triple"
        triple_rows = [r for r in triple_rows if sync_constraints_ok(r)]
        rows += triple_rows

    seen, unique = set(), []
    for r in rows:
        k = tuple(sorted((n, str(v)) for n, v in r.items() if not n.startswith("_")))
        if k not in seen:
            seen.add(k)
            unique.append(r)

    return {
        "runs": unique,
        "count": len(unique),
        "composition": {"extremes": 2, "isolation": len(SEED_KINDS),
                        "pairwise": len(pair_rows), "triple": len(triple_rows)},
        "coverage_2way": coverage(unique, factors, 2, sync_constraints_ok),
        "coverage_3way_interacting": coverage(
            unique, [f for f in factors if f.name in SYNC_INTERACTING], 3,
            sync_constraints_ok) if triple else None,
        "factors": [{"name": f.name, "levels": [str(x) for x in f.levels],
                     "requires": f.requires, "note": f.note} for f in factors],
    }


def constraints_ok(row: dict) -> bool:
    """Reject configurations the UI itself cannot produce.

    A generator that emits unreachable rows wastes runs and produces findings
    nobody can act on, because no user could ever have been in that state.
    """
    # Panopto outputs and layout are inert unless the section is enabled, and
    # enabling it with no output selected downloads nothing.
    outs = ("pan_out_mp3", "pan_out_mp4", "pan_out_txt", "pan_out_srt")
    if row.get("pan_master"):
        if not any(row.get(o) for o in outs):
            return False
    else:
        if any(row.get(o) for o in outs):
            return False

    # A transcript needs audio or video to transcribe from.
    if (row.get("pan_out_txt") or row.get("pan_out_srt")) and \
            not (row.get("pan_out_mp3") or row.get("pan_out_mp4")):
        return False

    # convert_html rewrites Canvas Content HTML; with no Canvas Content selected
    # it has nothing to act on and the run cannot distinguish "converter broken"
    # from "nothing to convert".
    sec = ("dl_assignments", "dl_syllabus", "dl_announcements",
           "dl_discussions", "dl_quizzes", "dl_submissions")
    if row.get("convert_html") and not any(row.get(s) for s in sec):
        return False
    if row.get("secondary_isolated") and not any(row.get(s) for s in sec):
        return False
    return True


# --------------------------------------------------------------------------
# IPOG
# --------------------------------------------------------------------------

def covering_array(factors: list[Factor], strength: int = 2,
                   constraint=constraints_ok) -> list[dict]:
    """IPOG. **Factor ORDER decides how expensive the plan is** - see below.

    Growth is in-parameter-order: the first ``strength`` factors are seeded as
    an exhaustive product, and each later factor is smeared across every row
    that already exists. So a factor placed EARLY is packed densely into few
    rows, and one placed LATE turns up in row after row. That is a cost
    decision disguised as a declaration order, and it dominated this plan -
    see ``DOWNLOAD_FACTORS`` for the measurement.

    A cost-weighted tie-break in horizontal growth was built and measured
    first, and it is **worse**: refusing an expensive level there pushes its
    tuples into vertical growth, which appends whole new rows that must carry
    the expensive level anyway. Rows 36 -> 50-61 and mp4 rows 14 -> 18-23
    across weights 0.5 to 4.0. Do not re-litigate; reorder instead.
    """
    if strength < 1:
        raise ValueError("strength must be >= 1")
    if len(factors) < strength:
        strength = len(factors)

    names = [f.name for f in factors]
    levels = {f.name: list(f.levels) for f in factors}

    rows = [dict(zip(names[:strength], combo))
            for combo in itertools.product(*(levels[n] for n in names[:strength]))]
    rows = [r for r in rows if _partial_ok(r, constraint, names[:strength], factors)]

    for i in range(strength, len(names)):
        cur = names[:i + 1]
        new_name = names[i]
        need = _tuples_to_cover(cur, levels, strength, new_name)

        # horizontal growth
        for row in rows:
            best, best_gain = None, -1
            for lv in levels[new_name]:
                cand = {**row, new_name: lv}
                if not _partial_ok(cand, constraint, cur, factors):
                    continue
                gain = sum(1 for t in _row_tuples(cand, cur, strength, new_name)
                           if t in need)
                # Strictly greater keeps the FIRST level on a tie, and every
                # boolean factor here is ordered (off, on), so a tie already
                # favours the cheap side.
                if gain > best_gain:
                    best, best_gain = lv, gain
            if best is None:
                best = levels[new_name][0]
            row[new_name] = best
            need -= set(_row_tuples(row, cur, strength, new_name))

        # vertical growth
        for t in sorted(need, key=str):
            placed = False
            for row in rows:
                if _fits(row, t) and _partial_ok({**row, **dict(t)}, constraint, cur, factors):
                    row.update(dict(t))
                    placed = True
                    break
            if placed:
                continue
            new_row = dict(t)
            for n in cur:
                new_row.setdefault(n, levels[n][0])
            if not _partial_ok(new_row, constraint, cur, factors):
                # Fall back to any legal completion rather than dropping the
                # tuple silently - a dropped tuple is a coverage hole nobody
                # would ever notice.
                new_row = _legalise(new_row, dict(t), cur, levels, constraint, factors)
                if new_row is None:
                    continue
            rows.append(new_row)

    for row in rows:
        for n in names:
            row.setdefault(n, levels[n][0])
    return [r for r in rows if constraint(r)]


def _partial_ok(row, constraint, active, factors) -> bool:
    """Constraints are checked on a partially-built row.

    They must not reject a row merely because a factor has not been assigned
    yet, so unassigned factors are filled with their first level - which is the
    "off" level for every boolean here - before testing.
    """
    probe = {f.name: (row[f.name] if f.name in row else f.levels[0]) for f in factors}
    return constraint(probe)


def _tuples_to_cover(cur, levels, strength, new_name) -> set:
    out = set()
    others = [n for n in cur if n != new_name]
    for combo in itertools.combinations(others, strength - 1):
        pools = [levels[n] for n in combo] + [levels[new_name]]
        for vals in itertools.product(*pools):
            out.add(tuple(sorted(zip(list(combo) + [new_name], vals), key=lambda kv: kv[0])))
    return out


def _row_tuples(row, cur, strength, new_name) -> list:
    out = []
    others = [n for n in cur if n != new_name and n in row]
    for combo in itertools.combinations(others, strength - 1):
        pair = [(n, row[n]) for n in combo] + [(new_name, row[new_name])]
        out.append(tuple(sorted(pair, key=lambda kv: kv[0])))
    return out


def _fits(row, t) -> bool:
    return all(k not in row or row[k] == v for k, v in t)


def _legalise(row, must, cur, levels, constraint, factors):
    """Find SOME legal row containing the required tuple, cheaply.

    The exhaustive version of this is a cross product over every assigned factor
    - 2**24 for the full download space - which hangs the generator. Greedy
    repair plus a bounded random restart finds a completion in practice, and
    returning None on failure is honest: the tuple is then genuinely unreachable
    and ``coverage()`` will not count it as a hole, because it re-tests
    reachability with the same constraint function.
    """
    fixed = dict(must)
    free = [n for n in cur if n not in fixed]

    def legal(c):
        return constraint({f.name: c.get(f.name, f.levels[0]) for f in factors})

    cand = {**{n: levels[n][0] for n in free}, **fixed}
    if legal(cand):
        return cand

    # Greedy repair: flip one free factor at a time, keeping any flip that makes
    # the row legal. Every constraint here is satisfiable by switching a single
    # companion on (pan_master, an output, some Canvas Content), so one pass is
    # usually enough.
    for _ in range(3):
        for n in free:
            for lv in levels[n]:
                if cand[n] == lv:
                    continue
                trial = {**cand, n: lv}
                if legal(trial):
                    return trial
                cand_score = _violations(trial, constraint, factors)
                if cand_score < _violations(cand, constraint, factors):
                    cand = trial
        if legal(cand):
            return cand

    rng = __import__("random").Random(20260727)
    for _ in range(400):
        trial = {**{n: rng.choice(levels[n]) for n in free}, **fixed}
        if legal(trial):
            return trial
    return None


def _violations(cand, constraint, factors) -> int:
    return 0 if constraint({f.name: cand.get(f.name, f.levels[0]) for f in factors}) else 1


def coverage(rows: list[dict], factors: list[Factor], strength: int = 2,
             constraint=constraints_ok) -> dict:
    """Re-derive coverage from the generated rows. The suite's proof of work.

    Takes the constraint explicitly. It used to hardcode the DOWNLOAD one, so
    measuring a differently-constrained space (sync) against it would count
    tuples as reachable that its generator had correctly refused to emit - and
    report holes that are not holes.
    """
    names = [f.name for f in factors]
    levels = {f.name: list(f.levels) for f in factors}
    total, covered = 0, 0
    holes = []
    for combo in itertools.combinations(names, strength):
        for vals in itertools.product(*(levels[n] for n in combo)):
            probe = dict(zip(combo, vals))
            if not constraint({f.name: probe.get(f.name, f.levels[0]) for f in factors}):
                continue          # unreachable by construction, not a hole
            total += 1
            if any(all(r.get(k) == v for k, v in probe.items()) for r in rows):
                covered += 1
            elif len(holes) < 40:
                holes.append(probe)
    return {"strength": strength, "runs": len(rows), "tuples": total,
            "covered": covered,
            "percent": round(100.0 * covered / total, 2) if total else 100.0,
            "uncovered_examples": holes}


# --------------------------------------------------------------------------
# the run plan
# --------------------------------------------------------------------------

def isolation_rows(factors: list[Factor], base: dict | None = None) -> list[dict]:
    """One run per factor with ONLY that factor switched on.

    Pair coverage alone lets a converter hide behind another: if zip and code
    are always on together and the zip step silently does nothing, the run still
    produces .txt files and looks healthy. Isolating each one is the only way to
    attribute an output to the toggle that was supposed to produce it.
    """
    base = base or {f.name: f.levels[0] for f in factors}
    rows = []
    for f in factors:
        for lv in f.levels[1:]:
            row = dict(base)
            row[f.name] = lv
            # Minimal legal companions: a Panopto output needs its master, and a
            # Canvas Content converter needs some Canvas Content to chew on.
            if f.name.startswith("pan_out_"):
                row["pan_master"] = True
            if f.name == "pan_layout":
                row["pan_master"] = True
                row["pan_out_mp3"] = True
            if f.name in ("convert_html", "secondary_isolated"):
                row["dl_announcements"] = True
            if f.name in ("pan_out_txt", "pan_out_srt"):
                row["pan_out_mp3"] = True
            if constraints_ok({g.name: row.get(g.name, g.levels[0]) for g in factors}):
                row["_isolates"] = f"{f.name}={lv}"
                rows.append(row)
    return rows


def extremes(factors: list[Factor]) -> list[dict]:
    """All-off and all-on. The two configurations users actually pick most."""
    off = {f.name: f.levels[0] for f in factors}
    on = {f.name: f.levels[-1] for f in factors}
    on["file_filter"] = "all"          # 'study' would mask most converters
    on["max_file_size"] = None         # a cap would mask most downloads
    out = [dict(off, _isolates="all-off")]
    if constraints_ok(on):
        out.append(dict(on, _isolates="all-on"))
    return out


def build_plan(factors: list[Factor] | None = None, *, pair_strength: int = 2,
               triple: bool = True) -> dict:
    """The full download run list, with its coverage proof attached."""
    factors = factors or DOWNLOAD_FACTORS
    pair_rows = covering_array(factors, pair_strength)
    rows = extremes(factors) + isolation_rows(factors) + pair_rows

    triple_rows = []
    if triple:
        sub = [f for f in factors if f.name in INTERACTING]
        triple_rows = covering_array(sub, 3)
        for r in triple_rows:
            for f in factors:
                r.setdefault(f.name, f.levels[0])
            # Panopto layout only means anything with the section enabled.
            if r.get("pan_layout") == "separate":
                r["pan_master"], r["pan_out_mp3"] = True, True
            r["_isolates"] = "triple"
        triple_rows = [r for r in triple_rows if constraints_ok(r)]
        rows += triple_rows

    seen, unique = set(), []
    for r in rows:
        k = tuple(sorted((n, str(v)) for n, v in r.items() if not n.startswith("_")))
        if k not in seen:
            seen.add(k)
            unique.append(r)

    return {
        "runs": unique,
        "count": len(unique),
        "composition": {"extremes": 2, "isolation": len(isolation_rows(factors)),
                        "pairwise": len(pair_rows), "triple": len(triple_rows)},
        "coverage_2way": coverage(unique, factors, 2),
        "coverage_3way_interacting": coverage(
            unique, [f for f in factors if f.name in INTERACTING], 3) if triple else None,
        "factors": [{"name": f.name, "levels": [str(x) for x in f.levels],
                     "requires": f.requires, "note": f.note} for f in factors],
    }


# --------------------------------------------------------------------------
# course capabilities
# --------------------------------------------------------------------------

def panopto_items(snapshot: dict) -> list[dict]:
    """The module items that genuinely launch Panopto, by HOST.

    Not every ``ExternalTool`` is Panopto, and the difference is expensive.
    Measured across the whole account on 2026-07-28: course 43660 has 36
    ExternalTool items, all on ``cbs.cloud.panopto.eu``; course 45899 has 12,
    all Alma/ExLibris library citations. Counting the item TYPE made 45899 look
    Panopto-capable, and because it is far cheaper than 43660 the assignment
    then sent it **25 of the 29 Panopto rows and 17 of the 18 transcription
    rows** - hours of GPU time producing green results against a course with
    zero recordings. That is precisely the "green result that proves nothing"
    this module's own docstring calls the most expensive kind of test.

    The host rule mirrors the product: ``panopto.auth.panopto_base_from_url``
    decides the same way (``"panopto" in netloc``). Note the app itself is
    host-AGNOSTIC at discovery time - it LTI-launches every ExternalTool and
    keeps whatever yields a Panopto GUID - so this is a capability estimate for
    scheduling, not a reimplementation of discovery. It is deliberately the
    conservative direction: a false positive wastes a whole row, a false
    negative only declines a course we have a proven alternative for.
    """
    from urllib.parse import urlparse
    out = []
    for m in snapshot.get("modules", []):
        for it in m.get("items", []):
            if it.get("type") != "ExternalTool":
                continue
            host = (urlparse(it.get("external_url") or "").hostname or "").lower()
            if "panopto" in host:
                out.append(it)
    return out


def capabilities(snapshot: dict) -> set[str]:
    """Which factors a course can actually exercise, derived from oracle O5.

    Assigning a run to a course that cannot exercise its factors produces a
    green result that proves nothing, which is the most expensive kind of test.
    """
    caps: set[str] = set()
    sc = snapshot.get("secondary_counts", {})
    if sc.get("assignment"):
        caps.add("assignments")
    if sc.get("syllabus"):
        caps.add("syllabus")
    if sc.get("announcement"):
        caps.add("announcements")
    if sc.get("discussion"):
        caps.add("discussions")
    if sc.get("quiz"):
        caps.add("quizzes")
    if any(sc.values()):
        caps.add("secondary")
    types = snapshot.get("module_item_types", {})
    if panopto_items(snapshot):
        caps.add("panopto")
    if types.get("ExternalUrl"):
        caps.add("urls")

    ext_map = {
        ".zip": "zip", ".tar": "zip", ".gz": "zip",
        ".pptx": "pptx", ".ppt": "pptx", ".pptm": "pptx",
        ".doc": "legacy_word", ".rtf": "legacy_word", ".odt": "legacy_word",
        ".xlsx": "excel", ".xls": "excel", ".xlsm": "excel",
        ".mp4": "video", ".mov": "video", ".mkv": "video", ".avi": "video",
    }
    from .crosscheck import CONVERTERS
    code_exts = CONVERTERS["convert_code"]["sources"]
    for f in snapshot.get("files_tab", {}).values():
        name = (f.get("display_name") or f.get("filename") or "").lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if ext in ext_map:
            caps.add(ext_map[ext])
        if ext in code_exts:
            caps.add("code")
    # A restricted Files tab hides the extensions; fall back to module item
    # titles, which still carry the filename.
    for m in snapshot.get("modules", []):
        for it in m.get("items", []):
            title = (it.get("title") or "").lower()
            ext = "." + title.rsplit(".", 1)[-1] if "." in title else ""
            if ext in ext_map:
                caps.add(ext_map[ext])
            if ext in code_exts:
                caps.add("code")
    return caps


def course_stats(snapshot: dict) -> dict:
    """What a run against this course COSTS, in rough megabytes.

    Only ever used as a tie-break, so it needs to be ordinally right rather
    than accurate. Two courses that can exercise the same factors are the same
    test; picking the cheaper one is free coverage.
    """
    ft = snapshot.get("files_tab", {})
    mb = sum(f.get("size", 0) or 0 for f in ft.values() if f.get("has_url")) / 1048576
    files = len(snapshot.get("expected_file_ids", [])) or len(ft)
    if mb <= 0 and files:
        # A restricted Files tab hides every size. Measured on course 45899
        # (124 files, no Files tab, 238 MB on disk) the mean is ~1.9 MB/file.
        mb = files * 1.9
    return {"mb": round(mb, 1), "files": files,
            "recordings": len(panopto_items(snapshot))}


# Rough per-recording cost in MB-equivalents, measured 2026-07-28 on course
# 43660 (36 recordings). The video stream is fetched in full whichever output
# is asked for - mp3 is a transcode of it, mp4 a `-c copy` remux - so the two
# differ on DISK, not on bandwidth. Transcription is priced in the same unit
# from its measured wall time (19.1 s/recording on CUDA + tiny, 65.0 s on CPU)
# against the ~3.4 MB/s this link sustains.
REC_COST_MB = {"stream": 14.0, "mp4_disk": 105.0, "transcribe": 65.0}


def estimate_cost(row: dict, stats: dict) -> float:
    """MB-equivalent cost of running *row* against a course with *stats*."""
    cost = float(stats.get("mb", 0.0))
    rec = int(stats.get("recordings", 0))
    if rec and any(row.get(k) for k in
                   ("pan_out_mp3", "pan_out_mp4", "pan_out_txt", "pan_out_srt")):
        cost += rec * REC_COST_MB["stream"]
        if row.get("pan_out_mp4"):
            cost += rec * REC_COST_MB["mp4_disk"]
        if row.get("pan_out_txt") or row.get("pan_out_srt"):
            cost += rec * REC_COST_MB["transcribe"]
    return cost


def cover_courses(wanted: set[str], row: dict, course_caps: dict[int, set[str]],
                  stats: dict[int, dict]) -> tuple[list[int], list[str]]:
    """The cheapest set of courses that between them exercise *wanted*.

    Greedy set cover: repeatedly take the course covering the most of what is
    still uncovered, cheapest first. Not provably minimal - set cover is
    NP-hard and greedy is the standard ln(n) approximation - but every
    tie-break bottoms out in the course id, so the same inputs regenerate the
    same plan. That determinism matters more than minimality here, for the same
    reason the covering array is generated deterministically: a run list that
    reshuffles between invocations cannot be compared against its own history.

    Returns ``(course_ids, still_unexercised)``. A row that wants nothing in
    particular still gets one course - the cheapest, since it is testing layout
    or filtering and any real course will do.
    """
    chosen: list[int] = []
    left = set(wanted)
    while left:
        best, best_key = None, None
        for cid in sorted(course_caps):
            gain = len(left & course_caps[cid])
            if not gain:
                continue
            key = (-gain, estimate_cost(row, stats.get(cid, {})), cid)
            if best_key is None or key < best_key:
                best, best_key = cid, key
        if best is None:
            break                      # nothing left can cover the remainder
        chosen.append(best)
        left -= course_caps[best]
    if not chosen:
        chosen = [min(sorted(course_caps),
                      key=lambda c: (estimate_cost(row, stats.get(c, {})), c))]
    return chosen, sorted(left)


def assign_courses(plan: dict, course_caps: dict[int, set[str]],
                   factors: list[Factor] | None = None,
                   stats: dict[int, dict] | None = None) -> dict:
    """Give every row enough courses to exercise every factor it switches on.

    **A row may need more than one course, and picking the single best one is
    how "100% pairwise coverage" becomes a claim rather than a fact.** No
    course in this account has zip AND video AND legacy Word AND code AND
    Panopto. Measured on the 73-row plan, single-course assignment left 42
    factor-instances switched on against a course that could not exercise them
    - about 30 rows carrying an ON toggle that provably did nothing, their
    tuples *scheduled* but never *tested*. ``DownloadFlow`` already selects
    several courses in one run, so covering a row's wants with a SET of courses
    costs one flow and no new machinery. Measured after: unexercised factors
    42 -> 10 (all ``syllabus``, see below) for +27% download, with 49 rows on
    one course, 19 on two and 5 on three.

    ``_course_ids`` is the set; ``_course_id`` remains its first member so
    existing readers of the plan keep working.

    **Every row gets at least one course.** The previous version seeded
    ``best_score`` with -1, so a row whose requirements NO course meets
    (``dl_syllabus``: not one course in the account has a syllabus body) scored
    -1 or lower everywhere and kept ``_course_id = None`` - and
    ``jobs_from_plan`` skipped a row with no course, silently. A dropped row is
    a coverage hole nobody would ever notice, the same failure the
    vertical-growth fallback above exists to prevent. Such a row still runs
    ("Syllabus on, course has none" is a real state worth not crashing in) and
    ``unreachable_requirements`` states plainly what could not be proved.
    """
    factors = factors or DOWNLOAD_FACTORS
    stats = stats or {}
    req = {f.name: f.requires for f in factors if f.requires}
    if not course_caps:
        raise ValueError("assign_courses needs at least one course")

    totals: dict[str, int] = {}
    for run in plan["runs"]:
        wanted = {req[n] for n, v in run.items()
                  if n in req and v not in (False, None, "match", "all")}
        ids, left = cover_courses(wanted, run, course_caps, stats)
        run["_course_ids"] = ids
        run["_course_id"] = ids[0]
        run["_unexercised"] = left
        run["_cost_mb"] = round(
            sum(estimate_cost(run, stats.get(c, {})) for c in ids), 1)
        for x in left:
            totals[x] = totals.get(x, 0) + 1

    plan["unexercised_factors"] = dict(sorted(totals.items()))
    # A requirement no course in the pool can meet is a coverage GAP, and it
    # has to be stated rather than inferred from a count: the rows still ran,
    # so nothing else in the plan would ever look wrong.
    reachable = set().union(*course_caps.values()) if course_caps else set()
    plan["unreachable_requirements"] = sorted(set(req.values()) - reachable)
    plan["estimated_cost_mb"] = round(
        sum(r.get("_cost_mb", 0.0) for r in plan["runs"]), 1)
    plan["courses_per_row"] = _tally(len(r["_course_ids"]) for r in plan["runs"])
    return plan


def _tally(items) -> dict:
    out: dict = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))


def to_json(plan: dict) -> str:
    return json.dumps(plan, indent=2, ensure_ascii=False, default=str)
