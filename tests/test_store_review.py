"""The Microsoft Store rating ask: the gate, the writes, and the two call sites.

The feature's whole risk is in *when* it appears. An ask that lands on a screen
reporting errors, or that reappears every time somebody finishes a download,
costs a daily user - which is worth far more than a review. So most of this file
is about the conditions, and the rest is the counting discipline this repo keeps
needing: a fix that lands on one of two completion screens looks complete and
ships half a feature (``pdf_looks_real`` sat on two of three delete sites for
eight months).

Nothing here needs Windows, a Store account or a browser: ``core.store_review``
is deliberately pure, and the packaging check is the caller's.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """An isolated config dir the REAL functions resolve through.

    ``get_config_dir`` honours ``CANVAS_DL_CONFIG_DIR`` first and
    unconditionally, and ``core.store_review`` resolves the path per call, so
    this reaches the real persistence with nothing patched inside it.
    """
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    return tmp_path / "canvas_downloader_settings.json"


def _assert_isolated(cfg):
    """Refuse to write unless it lands in the test's own directory.

    ``get_config_dir()`` falls back to the REPO ROOT for a script run, which is
    where a developer's live settings file actually sits. Without this, a broken
    fixture silently rewrites it and the damage looks like nothing at all - it
    has happened in this repo before.
    """
    from shared.helpers import get_config_dir
    resolved = os.path.normcase(os.path.realpath(get_config_dir()))
    expected = os.path.normcase(os.path.realpath(str(cfg.parent)))
    assert resolved == expected, "config-dir isolation is BROKEN"


def _sr():
    import core.store_review as sr
    return sr


def _ready_state(sr, **over):
    """A state that has met the day threshold and nothing else."""
    state = {"rated": False, "asks": 0, "snoozed_until": "",
             "run_days": ["2026-01-01", "2026-01-02", "2026-01-03"]}
    state.update(over)
    return state


# ── The gate ────────────────────────────────────────────────────────────────

def test_a_brand_new_install_is_never_asked():
    """The day threshold is the whole "is this a habit yet" question."""
    sr = _sr()
    assert sr.should_ask({"rated": False, "asks": 0, "snoozed_until": "",
                          "run_days": []}, today="2026-01-03") is False


@pytest.mark.parametrize("days", [0, 1, 2])
def test_fewer_than_three_distinct_days_is_not_enough(days):
    sr = _sr()
    state = _ready_state(sr, run_days=[f"2026-01-0{i + 1}" for i in range(days)])
    assert sr.should_ask(state, today="2026-01-09") is False


def test_three_distinct_days_and_nothing_else_against_it_asks():
    sr = _sr()
    assert sr.should_ask(_ready_state(_sr()), today="2026-01-09") is True


def test_pressing_rate_is_terminal():
    """"Already rated" is unknowable, so the PRESS is what ends it - for good,
    on every later run, whatever else is true."""
    sr = _sr()
    assert sr.should_ask(_ready_state(sr, rated=True), today="2030-01-01") is False


def test_the_lifetime_cap_is_the_promise_that_makes_this_tolerable():
    """Someone who simply ignores the card meets it three times, ever."""
    sr = _sr()
    for n in range(sr.MAX_ASKS):
        assert sr.should_ask(_ready_state(sr, asks=n), today="2026-06-01") is True
    assert sr.should_ask(_ready_state(sr, asks=sr.MAX_ASKS),
                         today="2026-06-01") is False
    assert sr.should_ask(_ready_state(sr, asks=sr.MAX_ASKS + 9),
                         today="2026-06-01") is False


def test_a_live_snooze_suppresses_the_ask_and_expiry_releases_it():
    sr = _sr()
    state = _ready_state(sr, asks=1, snoozed_until="2026-02-01")
    assert sr.should_ask(state, today="2026-01-31") is False
    # The snooze is inclusive of its own end date: "at least a week" should not
    # mean six days and a bit.
    assert sr.should_ask(state, today="2026-02-01") is True
    assert sr.should_ask(state, today="2026-02-02") is True


def test_an_unparseable_snooze_keeps_quiet_rather_than_asking():
    """The quiet direction. A garbled date must not read as "ask now"."""
    sr = _sr()
    state = _ready_state(sr, asks=1, snoozed_until="zzzz-not-a-date")
    assert sr.should_ask(state, today="2026-02-01") is False


# ── The writes ──────────────────────────────────────────────────────────────

def test_a_second_clean_run_on_one_day_writes_nothing(cfg):
    """Idempotence by DAY is what makes charging on a re-rendering screen safe.

    A completion screen re-renders on every rerun, so a naive counter would
    reach the threshold - and then burn the ask allowance - inside one screen.
    """
    sr = _sr()
    _assert_isolated(cfg)
    assert sr.note_clean_run(today="2026-03-01") is True
    assert sr.note_clean_run(today="2026-03-01") is False
    assert sr.note_clean_run(today="2026-03-01") is False
    assert sr.load_state()["run_days"] == ["2026-03-01"]


def test_run_days_stop_growing_once_the_threshold_is_met(cfg):
    """Nothing downstream asks "how many days" beyond the threshold, so the
    whole feature costs at most three writes here in an install's life."""
    sr = _sr()
    _assert_isolated(cfg)
    for d in range(1, sr.REQUIRED_RUN_DAYS + 1):
        assert sr.note_clean_run(today=f"2026-03-0{d}") is True
    assert sr.note_clean_run(today="2026-03-09") is False
    assert len(sr.load_state()["run_days"]) == sr.REQUIRED_RUN_DAYS


def test_an_ask_is_counted_and_starts_the_snooze(cfg):
    sr = _sr()
    _assert_isolated(cfg)
    assert sr.note_ask(today="2026-04-01") is True
    state = sr.load_state()
    assert state["asks"] == 1
    expected = (dt.date(2026, 4, 1)
                + dt.timedelta(days=sr.SNOOZE_DAYS)).isoformat()
    assert state["snoozed_until"] == expected


def test_the_three_writers_only_touch_their_own_block(cfg):
    """The co-owned file's invariant, from this module's side.

    tests/test_settings_coownership.py asserts it across every co-owner; this is
    the same property stated where someone changing THIS module will see it.
    """
    sr = _sr()
    cfg.write_text(json.dumps({
        "canvas_url": "https://cbs.instructure.com",
        "panopto_notice_ack_version": 2,
        "panopto": {"model": "medium"},
    }, indent=2), encoding="utf-8")
    _assert_isolated(cfg)
    sr.note_clean_run(today="2026-05-01")
    sr.note_ask(today="2026-05-01")
    sr.note_rated()
    after = json.loads(cfg.read_text(encoding="utf-8"))
    assert after["canvas_url"] == "https://cbs.instructure.com"
    assert after["panopto_notice_ack_version"] == 2
    assert after["panopto"] == {"model": "medium"}
    assert after[sr.STATE_KEY]["rated"] is True


def test_a_full_lifecycle_ends_silent(cfg):
    """Drive the real thing end to end: three days, three asks, then nothing."""
    sr = _sr()
    _assert_isolated(cfg)
    for d in (1, 2, 3):
        sr.note_clean_run(today=f"2026-06-0{d}")
    day = dt.date(2026, 6, 3)
    for _ in range(sr.MAX_ASKS):
        assert sr.should_ask(today=day.isoformat()) is True
        sr.note_ask(today=day.isoformat())
        assert sr.should_ask(today=day.isoformat()) is False, "snooze not applied"
        day += dt.timedelta(days=sr.SNOOZE_DAYS)
    assert sr.should_ask(today=day.isoformat()) is False
    assert sr.should_ask(today="2099-01-01") is False, "the cap is not a snooze"


def test_rating_ends_it_even_with_asks_left(cfg):
    sr = _sr()
    _assert_isolated(cfg)
    for d in (1, 2, 3):
        sr.note_clean_run(today=f"2026-07-0{d}")
    assert sr.should_ask(today="2026-07-03") is True
    sr.note_rated()
    assert sr.should_ask(today="2099-01-01") is False
    assert sr.asks_remaining() == 0


# ── A hand-edited or half-written file must not re-open a settled ask ───────

@pytest.mark.parametrize("raw", [
    None, "nonsense", 42, [], {"rated": "yes"}, {"run_days": "2026-01-01"},
    {"asks": None}, {"snoozed_until": 17}, {"run_days": [1, 2, 3]},
])
def test_a_garbled_state_block_never_raises_on_the_render_path(raw):
    """This runs while a completion screen paints, so a bad shape has to
    degrade rather than raise into it."""
    sr = _sr()
    state = sr._coerce(raw)
    assert isinstance(state["rated"], bool)
    assert isinstance(state["asks"], int) and state["asks"] >= 0
    assert isinstance(state["run_days"], list)
    assert isinstance(state["snoozed_until"], str)
    sr.should_ask(state, today="2026-01-01")  # must not raise


def test_an_unreadable_ask_count_is_assumed_SPENT_not_fresh():
    """The permissive direction re-opens an ask the user already answered."""
    sr = _sr()
    assert sr._coerce({"asks": "garbage"})["asks"] == sr.MAX_ASKS
    assert sr.should_ask(sr._coerce({"asks": "garbage",
                                     "run_days": ["a", "b", "c"]}),
                         today="2026-01-01") is False


def test_a_truthy_rated_value_of_any_shape_stays_terminal():
    sr = _sr()
    for raw in ({"rated": True}, {"rated": 1}, {"rated": "no"}):
        assert sr._coerce(raw)["rated"] is True


# ── Structural: the conditions all meet in ONE place ────────────────────────

def _calls_in(node) -> set:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                out.add(f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def _fn(path: str, name: str):
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{path}: {name} not found")


def test_every_public_writer_goes_through_the_one_read_modify_write():
    """The census the co-ownership file delegates here.

    Matched on the CALL through the AST, not on the token: an ``import`` or a
    docstring mentioning ``_save_state`` satisfies a substring test while the
    writer has quietly grown its own read. That exact weakness let four mutants
    escape an earlier test in this repo.
    """
    for name in ("note_clean_run", "note_ask", "note_rated"):
        calls = _calls_in(_fn("core/store_review.py", name))
        assert "_save_state" in calls, (
            f"core.store_review.{name} no longer writes through _save_state, so "
            f"the settings co-ownership census no longer covers it")


def test_the_one_read_modify_write_uses_the_SAFE_reader():
    calls = _calls_in(_fn("core/store_review.py", "_save_state"))
    assert "_read_full_config_for_update" in calls, (
        "_save_state does not read through the for-update reader: an unreadable "
        "settings file would be degraded to {} and written back, taking every "
        "other module's settings with it")


def test_the_renderer_refuses_before_it_reads_anything_when_not_packaged():
    """MSIX is checked FIRST, so macOS and the .exe build emit no element at all
    and every index on those completion screens is what it was before."""
    node = _fn("shared/components.py", "render_store_review_card")
    assert "is_msix_package" in _calls_in(node), (
        "the rating card no longer gates on package identity - it would render "
        "on macOS and on the Inno .exe build, where there is nothing to rate")
    body = node.body
    first_return_idx = next(
        i for i, s in enumerate(body)
        if any(isinstance(n, ast.Return) for n in ast.walk(s)))
    src = ast.dump(ast.Module(body=body[:first_return_idx + 1], type_ignores=[]))
    assert "is_msix_package" in src, (
        "the packaging gate is no longer the FIRST thing that can return")


def test_the_ask_is_charged_on_show_not_on_a_click():
    """Only counting an ANSWERED ask means a user who ignores the card meets it
    on every clean completion screen for ever."""
    calls = _calls_in(_fn("shared/components.py", "render_store_review_card"))
    assert "note_ask" in calls
    for cb in ("_store_review_rate", "_store_review_not_now"):
        assert "note_ask" not in _calls_in(_fn("shared/components.py", cb)), (
            f"{cb} charges the ask; it is charged on SHOW")


def test_the_rate_button_records_before_it_navigates():
    """Terminal state first. The Store launch is the step that can fail."""
    node = _fn("shared/components.py", "_store_review_rate")
    calls = _calls_in(node)
    assert "note_rated" in calls and "open_store_review_page" in calls
    order = [n.func.attr for n in ast.walk(node)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert order.index("note_rated") < order.index("open_store_review_page"), (
        "the Store is opened before the outcome is recorded, so a raise or a "
        "crash in between leaves the user asked again after they rated")


# ── Counting the call sites ─────────────────────────────────────────────────

_CALL_SITES = [
    ("app.py", "the download completion screen"),
    ("sync/completion.py", "the sync completion screen"),
]


@pytest.mark.parametrize("path,what", _CALL_SITES)
def test_both_completion_screens_ask(path, what):
    """A fix that lands on one of two screens looks complete and ships half a
    feature. This is the counting discipline, not a spot check."""
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "render_store_review_card"]
    assert len(calls) == 1, (
        f"{path} ({what}) has {len(calls)} rating-card call sites, expected 1")


@pytest.mark.parametrize("path,what", _CALL_SITES)
def test_no_screen_asks_after_a_run_that_reported_a_failure(path, what):
    """``clean_run`` must be the app's OWN definition of clean.

    ``len(errors) == 0`` is the tempting spelling and it is wrong in both
    directions: a teacher-locked file and an LTI stream are not failures (the
    completion card already refuses to count them), while an app error is one
    even though it is not a delivery error. Asking for five stars under an amber
    "Completed with Errors" header is the one thing this feature must not do.
    """
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    call = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "render_store_review_card")
    kw = {k.arg: k for k in call.keywords}
    assert "clean_run" in kw, f"{path}: clean_run is not passed explicitly"
    expr = ast.dump(kw["clean_run"].value)
    assert "retriable" in expr, (
        f"{path} ({what}) no longer gates the ask on the RETRIABLE error count")
    assert "Call" not in expr or "len" not in expr, (
        f"{path} ({what}) gates on len(errors), which counts outcomes the "
        f"completion card itself refuses to call failures")


# ── The stylesheet is static, and it actually covers the markup ─────────────

def test_the_component_emits_no_stylesheet_of_its_own():
    """This surface has branches that flip on a CLICK, mid-session, which is
    exactly the arming condition for the event-host reconciliation bug: a
    conditionally-emitted <style> shifts every LATER stylesheet onto its
    neighbour's host. The CSS therefore lives in styles/global.css.
    """
    # Resolved through the AST, and over STRING LITERALS only. A text scan of
    # the source matches the comment that explains this very rule - which is how
    # the first version of this test failed against correct code. A guard whose
    # reach shrinks when someone documents the code is worse than no guard.
    node = _fn("shared/components.py", "render_store_review_card")
    doc = ast.get_docstring(node)
    emitted = [n.value for n in ast.walk(node)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and n.value != doc]
    offenders = [s for s in emitted if "<style" in s]
    assert not offenders, (
        f"render_store_review_card emits a <style> block ({offenders!r}); move "
        f"it to styles/global.css (see the conditional-stylesheet rule in "
        f"CLAUDE.md)")


def test_every_class_and_key_the_card_emits_is_actually_styled():
    """A markup/CSS rename that lands on one side is invisible in review and
    silently unstyles the card."""
    src = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    css = "\n".join(p.read_text(encoding="utf-8")
                    for p in (REPO / "styles").glob("*.css"))
    for cls in ("sr-title", "sr-body", "sr-thanks"):
        assert f"class='{cls}'" in src, f"{cls} is no longer emitted"
        assert f".{cls}" in css, f"{cls} is emitted but has no CSS rule"
    for key in ("_store_review_card", "_sr_rate", "_sr_later"):
        assert key in src, f"{key} is no longer used as a widget key"
        assert key in css, f"{key} has no CSS rule"


# ── The Store id has to be the one the website advertises ──────────────────

#: Every published surface that names the Store product. The app's own constant
#: has to agree with all of them: a re-listing that updates the site and not the
#: app points every rating click at a product that is no longer ours, and one
#: that updates some pages and not others is the same bug wearing a smaller hat.
#: `scripts/_mutate_store_review.py` also contains the id - as the WRONG one, on
#: purpose - so it is deliberately not in this list.
_ID_SURFACES = [
    "docs/index.html",
    "docs/releases.html",
    "docs/win-setup.html",
    "docs/thanks-win.html",
    "docs/llms.txt",
    "README.md",
]


@pytest.mark.parametrize("surface", _ID_SURFACES)
def test_the_product_id_matches_every_surface_that_advertises_the_listing(surface):
    """The app and the website must name the SAME Store product.

    Updating the Store LISTING (copy, screenshots, a new package) never changes
    the Store id - it is assigned once, when the name is reserved. What does
    change it is creating a NEW product entry, and that is exactly the day this
    test earns its keep: the site gets the new link, the app keeps the old one,
    and every "Rate on the Store" click lands on a delisted product with nothing
    reporting an error.
    """
    sr = _sr()
    text = (REPO / surface).read_text(encoding="utf-8")
    assert sr.STORE_PRODUCT_ID in text, (
        f"{surface} does not name {sr.STORE_PRODUCT_ID}, the product the app "
        f"asks for a rating of - one of the two has been re-pointed and the "
        f"other has not")


def test_the_product_id_is_the_one_the_install_links_use():
    """Not just present somewhere in the page - the actual install URL."""
    sr = _sr()
    page = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    assert f"apps.microsoft.com/detail/{sr.STORE_PRODUCT_ID}" in page, (
        f"the app asks for a rating of {sr.STORE_PRODUCT_ID}, which is not the "
        f"product docs/index.html sends people to install")
    # The SLASH is load-bearing - see the constant's note. Its absence does
    # not raise, it just lands the user on the Store's home page.
    assert sr.STORE_REVIEW_URI == (
        f"ms-windows-store://review/?ProductId={sr.STORE_PRODUCT_ID}")


def test_the_user_facing_promises_are_pinned_to_their_LITERAL_numbers():
    """These three numbers are the design, and two of them are shipped COPY.

    Pinned as literals on purpose. Every other test here derives its expectation
    from the constant, which is right for exercising the logic and useless for
    noticing the constant itself changing - a mutation raising the cap to 99
    moved those tests' own expectations with it and survived the whole suite.
    The "Not now" tooltip says "at least a week" in words, so SNOOZE_DAYS is
    coupled to text the user reads; MAX_ASKS is the promise that makes the
    feature tolerable at all. Changing either is a product decision, not a tweak.

    "At least", not "a week": the snooze is a FLOOR. The card additionally needs
    a clean run on a later day to come back at all, so promising a date would be
    a claim this code cannot keep.
    """
    sr = _sr()
    assert sr.MAX_ASKS == 3, "the lifetime cap is the whole anti-nag promise"
    assert sr.SNOOZE_DAYS == 7, "the 'Not now' tooltip says at least a week"
    assert sr.REQUIRED_RUN_DAYS == 3


def test_packaging_is_ASKED_OF_WINDOWS_not_inferred_from_a_path():
    """The gate must not go back to sniffing ``sys.executable``.

    ``core.health_log`` carries that older heuristic and half of it is dead -
    nothing sets ``MSIX_PACKAGE_ID`` - so it rests entirely on a "WindowsApps"
    substring. A sideloaded dev package lands there too, and a relocated build
    does not. Fine for a telemetry field, not for the gate that decides whether
    a user-facing surface exists at all.
    """
    node = _fn("shared/helpers.py", "is_msix_package")
    # The DOCSTRING is stripped before scanning, because it names the very
    # heuristic this test bans - so a naive dump matches the explanation and
    # fails against correct code. Second time in this one file: the same shape
    # caught the <style> scanner above. A guard whose reach shrinks when
    # somebody documents the code is worse than no guard.
    body = [s for s in node.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str))]
    src = ast.dump(ast.Module(body=body, type_ignores=[]))
    assert "GetCurrentPackageFullName" in src, (
        "is_msix_package no longer asks Windows for package identity")
    for smell in ("WindowsApps", "MSIX_PACKAGE_ID", "executable"):
        assert smell not in src, (
            f"is_msix_package infers packaging from {smell!r} instead of asking "
            f"the OS - see the comment in that function for why that is wrong")


def test_both_live_states_emit_the_same_child_count():
    """The card and the thank-you render at ONE index, and ``addBlock`` hands a
    block the CHILDREN of whatever sat there - so the state with fewer leaves
    the other's tail inside itself (measured elsewhere in this repo at 247px
    against 193px, with a stray red Remove button inside an edit form)."""
    import shared.components as comps
    node = _fn("shared/components.py", "render_store_review_card")
    assert "pad_slot_children" in _calls_in(node), (
        "the thank-you state is no longer padded to the card's child count")
    # The card state emits exactly two children: the copy (one st.markdown) and
    # the button row (one st.columns).
    assert comps._STORE_REVIEW_SLOT_CHILDREN == 2


def test_packaging_detection_is_false_off_windows_and_memoised():
    """The safe answer everywhere that is not an MSIX process, and cached
    because callers ask on a render path."""
    import shared.helpers as h
    h._msix_packaged = None
    first = h.is_msix_package()
    assert isinstance(first, bool)
    if os.name != "nt":
        assert first is False
    h._msix_packaged = True
    assert h.is_msix_package() is True, "the answer is not memoised"
    h._msix_packaged = None
