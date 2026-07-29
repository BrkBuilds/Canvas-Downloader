"""A re-check must reach the SAME verdict as the live pass.

`recheck` exists so a finding can be re-derived with the current checker
without re-running anything - a finding is a function of (evidence, checker),
and only the evidence is expensive. That is only true if the re-check feeds the
checker the same inputs the live row did. It did not, in three separate ways,
and each one invented findings rather than losing them:

  * the seed plan's expectation lists were dropped, so the suite reported the
    harness's OWN planted fixtures as defects (40 per run),
  * the after-scan was passed unconditionally, so rows that stopped at the
    review screen were judged on the outcomes of a sync that never ran
    (26 fabricated criticals),
  * the completion capture was preferred over the review capture, losing the
    record of what the user ticked (4 fabricated highs).

All three were measured against a live pass that reported none of them. An
invented finding is worse than a missed one: it costs the trust that makes the
real findings worth reading.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import parallel                 # noqa: E402
from tests.audit.harness.parallel import Job             # noqa: E402


def _job(**kw):
    base = dict(id="s001", name="s001", kind="sync", course_id=45899,
                course_ids=[45899])
    base.update(kw)
    return Job(**base)


# ── the seed plan's expectations ─────────────────────────────────────────


def test_every_expectation_list_reaches_the_checker():
    """`invariants` suppresses each of these by name - all four must arrive.

    A name in the plan that is not forwarded is suppression the checker never
    sees, and the fixture it describes is reported as a defect.
    """
    # Keyed off the module's own list so adding an expectation cannot leave
    # this test agreeing with a stale copy of it.
    plan = {k: [f"{k}.bin"] for k in parallel._SEED_EXPECTATION_KEYS}
    assert parallel.seed_expectations(plan) == plan


def test_a_plan_missing_a_key_yields_an_empty_list_not_none():
    """`invariants` does `(ev.expect.get(k) or [])`, so None would work by
    luck. Returning the key explicitly keeps that from being load-bearing."""
    got = parallel.seed_expectations({})
    assert set(got) == set(parallel._SEED_EXPECTATION_KEYS)
    assert all(v == [] for v in got.values())


def test_a_null_valued_key_is_normalised():
    assert parallel.seed_expectations({"expected_partials": None})["expected_partials"] == []


def test_the_key_set_matches_what_the_checker_reads():
    """The seeder and the checker agree on these names or the whole mechanism
    is inert. Pinned here because the failure is silent in both directions."""
    src = (REPO / "tests" / "audit" / "harness" / "crosscheck.py").read_text(encoding="utf-8")
    for key in parallel._SEED_EXPECTATION_KEYS:
        assert f'"{key}"' in src, f"{key} is forwarded but nothing reads it"


# ── the after-scan is gated on whether a sync actually ran ───────────────


def test_a_confirmed_row_is_judged_on_its_after_scan():
    after = {"files": []}
    assert parallel._sync_outcome_disk(_job(confirm=True), after) is after


def test_a_row_that_stopped_at_review_is_not_judged_on_outcomes():
    """Nothing was supposed to happen to that folder yet.

    Passing the scan anyway asks "was this restored / left alone / forked to
    _NewVersion" of a sync that never ran, and every answer is a fabricated
    failure.
    """
    assert parallel._sync_outcome_disk(_job(confirm=False), {"files": []}) is None


# ── which UI capture a re-check reads ────────────────────────────────────


def test_a_sync_row_is_rechecked_against_its_review_capture(tmp_path, monkeypatch):
    """Both captures exist for a synced row, and only one holds the ticks.

    `_sync_outcome` reads expectations THROUGH the selection - a ticked
    "deleted locally" row flips its fixture from 'absent' to 'restored'. Handed
    the completion capture, the selection is unknown, the flip never happens,
    and the app is reported for restoring exactly what it was asked to restore.
    """
    src = (REPO / "tests" / "audit" / "harness" / "parallel.py").read_text(encoding="utf-8")
    sync_pref = src.index('if job.kind == "sync":\n                ui = _ui_capture(lrp, f"{job.name}_review")')
    assert sync_pref > 0, "a sync row must prefer its review capture"
    # and the download branch must keep preferring the completion screen
    dl_pref = src.index('ui = _ui_capture(lrp, f"{job.name}_complete")', sync_pref)
    assert dl_pref > sync_pref


def test_the_review_capture_is_what_carries_the_ticks():
    """Why the preference above matters, stated against the checker itself."""
    from tests.audit.harness import crosscheck
    review = {"courses": [{"categories": {"deleted_locally": {"rows": [
        {"name": "notes.txt", "stem": "notes", "checked": True},
        {"name": "other.txt", "stem": "other", "checked": False}]}}}]}
    assert crosscheck._selected_stems(review) == {"notes"}
    # A completion capture has no "courses" key at all - and the answer must be
    # None ("unknown"), never an empty set ("nothing was ticked").
    assert crosscheck._selected_stems({"screen": {"text": "Sync Complete!"}}) is None
    assert crosscheck._selected_stems(None) is None
