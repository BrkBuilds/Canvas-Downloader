"""The global Panopto switch, Pass 2: what the SURFACES do about it.

Pass 1 (``tests/test_panopto_global_switch.py``) made runs honour the switch.
This file covers the other half - what the user sees - and the rule that decides
every case:

    **Offer vs record.** A surface that OFFERS Panopto (a control that would
    cause a recording to be fetched) must go unavailable. A surface that RECORDS
    it (a stored contract, a completion screen, sync history) must NOT be
    rewritten, because it is a statement of fact about how something is
    configured, and that stays true while the switch is off. Records get
    ANNOTATED instead.

The failure this guards against is the seductive one: "the run skips it, so make
the config viewer say None selected". That silently misreports a folder set up
for recordings as one that never was, and the pills reappear the moment the
switch goes back on - a viewer that contradicts itself between sessions.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    from shared import helpers
    monkeypatch.setattr(helpers, "get_config_dir", lambda: str(tmp_path))
    return tmp_path


def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    return re.sub(r"#[^\n]*", "", src)


def _func_node(rel: str, name: str) -> ast.AST:
    for node in ast.walk(ast.parse(_src(rel))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {rel}")


def _func_src(rel: str, name: str) -> str:
    return _strip_comments(ast.get_source_segment(_src(rel), _func_node(rel, name)) or "")


PAN_ON_SETTINGS = {
    "download_mode": "modules", "file_filter": "all",
    "pan_out_url": False, "pan_out_mp4": True, "pan_out_mp3": True,
    "pan_out_txt": False, "pan_out_srt": False, "pan_layout": "separate",
}


# ═══════════════════════════════════════════════════════════════════════════
# Config viewers: ANNOTATE the record, never edit it
# ═══════════════════════════════════════════════════════════════════════════

def _badges(settings):
    from shared.components import render_config_summary_badges
    return render_config_summary_badges(settings, show_path=False)


def test_the_pills_still_report_what_is_configured_while_switched_off(config_dir):
    """The load-bearing one. A stored contract wanting Video+Audio must keep
    saying so - the Sync Hub's viewer exists to answer exactly that."""
    from panopto import settings as S
    S.set_globally_enabled(False)
    html = _badges(PAN_ON_SETTINGS)
    assert "Video" in html and "Audio" in html
    assert "None selected" not in html.split("Panopto Recordings")[1], (
        "the Panopto column was rewritten to 'None selected' - that reports a "
        "folder configured for recordings as one that never was"
    )


def test_the_column_says_it_will_not_run_while_switched_off(config_dir):
    from panopto import settings as S
    S.set_globally_enabled(False)
    html = _badges(PAN_ON_SETTINGS)
    assert "Won&#39;t run" in html or "Won't run" in html
    assert "Panopto is off in Settings" in html


def test_nothing_is_annotated_while_switched_on(config_dir):
    """No note and no dimming in the normal case - this must not become a
    permanent fixture of every preset card."""
    from panopto import settings as S
    S.set_globally_enabled(True)
    html = _badges(PAN_ON_SETTINGS)
    assert "Won't run" not in html and "Won&#39;t run" not in html
    assert "brightness(0.5)" not in html


def test_a_column_with_no_outputs_is_not_annotated(config_dir):
    """A preset that never included recordings has nothing to warn about; a
    note there would be noise on the majority of presets."""
    from panopto import settings as S
    S.set_globally_enabled(False)
    off = dict(PAN_ON_SETTINGS)
    off.update({k: False for k in off if k.startswith("pan_out_")})
    html = _badges(off)
    assert "Won&#39;t run" not in html and "Won't run" not in html
    assert "None selected" in html


def test_the_dimming_uses_the_apps_one_disabled_recipe(config_dir):
    """`brightness(0.5) saturate(0.5)` and nothing else - never opacity (it
    MULTIPLIES with the shared filter) and never a second filter (filter is one
    property, so a local one REPLACES it)."""
    from panopto import settings as S
    S.set_globally_enabled(False)
    html = _badges(PAN_ON_SETTINGS)
    assert "filter: brightness(0.5) saturate(0.5)" in html
    pan_col = html.split("Panopto Recordings")[1]
    assert "opacity" not in pan_col
    assert "grayscale" not in pan_col


def test_the_note_is_stated_once_per_column_not_once_per_pill(config_dir):
    from panopto import settings as S
    S.set_globally_enabled(False)
    html = _badges(PAN_ON_SETTINGS)
    assert html.count("Panopto is off in Settings") == 1


# ═══════════════════════════════════════════════════════════════════════════
# Card 4: dimmed and inert, never removed
# ═══════════════════════════════════════════════════════════════════════════

def test_card4_renders_in_both_states():
    """Removing the card drops a top-level element, and Streamlit reconciles by
    POSITION - the Output Folder separator below would inherit the card's node
    and its children. The condition goes on the CONTENT, never on the render."""
    fn = _func_src("ui/download_settings.py", "_render_card_panopto")
    assert "st.container(border=True," in fn
    assert '"card_panopto" if _pan_globally_on else "card_panopto_off"' in fn, (
        "Card 4 no longer uses the two-key trick; a container carries no "
        "attributes, so CSS has nothing to hook the dimming onto"
    )
    # The switch must be read BEFORE the container opens - the key depends on it.
    assert fn.index("_pan_globally_enabled()") < fn.index("st.container(border=True,")


def test_card4_off_state_emits_the_same_three_children_as_collapsed():
    """The collapsed on-state is style / icon / header-row, then returns. The
    off-state must match, or toggling the switch shifts every element below."""
    node = _func_node("ui/download_settings.py", "_render_card_panopto_off")
    top = [n for n in node.body if isinstance(n, ast.Expr) or isinstance(n, ast.With)
           or isinstance(n, ast.Assign)]
    calls = [n for n in ast.walk(node)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "st"]
    kinds = [c.func.attr for c in calls]
    assert kinds.count("markdown") == 3, (
        f"expected 3 st.markdown calls (style, icon, header), got {kinds}"
    )
    assert kinds.count("container") == 1
    assert kinds.count("button") == 1, (
        "the chevron slot must stay so the 24px icon gutter matches every other "
        "card"
    )
    assert top  # the body is not empty


def test_card4_off_state_button_is_disabled():
    fn = _func_src("ui/download_settings.py", "_render_card_panopto_off")
    assert "disabled=True" in fn, "the placeholder chevron must not be clickable"


def test_card4_off_state_names_where_the_switch_is():
    """A disabled control that hides its reason is a dead end - and this is the
    only Panopto affordance left on the whole download page."""
    fn = _func_src("ui/download_settings.py", "_render_card_panopto_off")
    assert "Settings" in fn


def test_card4_off_state_uses_the_one_disabled_recipe():
    fn = _func_src("ui/download_settings.py", "_render_card_panopto_off")
    assert "brightness(0.5) saturate(0.5)" in fn
    assert "filter: none" in fn, (
        "the disabled button inside a dimmed card needs filter:none or the "
        "shared button[disabled] rule COMPOUNDS with the card's (filter "
        "multiplies through nested elements) - the stg_card_pan_off precedent"
    )
    assert "opacity:" not in fn and "opacity :" not in fn


def test_card4_off_state_emits_a_stylesheet_like_the_on_state():
    """Every style block on a page lands in one index-addressed list. Emitting
    one in only one branch shifts every later stylesheet onto its neighbour's
    host."""
    off = _func_src("ui/download_settings.py", "_render_card_panopto_off")
    assert "<style>" in off


# ═══════════════════════════════════════════════════════════════════════════
# The skipped-recordings panel: the third member of an existing family
# ═══════════════════════════════════════════════════════════════════════════

def test_the_notice_reuses_the_skip_panel_family():
    """Not a new component. The size-skip and archive notices already share
    this markup and CSS; a fourth visual language for the same idea is how a
    completion screen stops looking like one screen.

    Asserted as whole CLASS ATTRIBUTES, not bare class names: `"skip-panel"` is
    a substring of `skip-panel-body`, so renaming the outer element still left
    every loose check passing.
    """
    fn = _func_src("shared/components.py", "render_panopto_disabled_notice")
    for attr in ("class='skip-panel skip-panel-solo'",
                 "class='skip-panel-header'",
                 "class='sp-header-row'",
                 'class="sp-chevron"',
                 "class='sp-title'",
                 "class='skip-panel-body'",
                 "class='sp-subtitle'",
                 "class='skip-file-list'",
                 'class="skip-file-row"',
                 'class="skip-file-name"'):
        assert attr in fn, f"the family's {attr!r} is gone"


def test_the_notice_is_silent_while_switched_on(config_dir, monkeypatch):
    """The switch must be the thing that stops it.

    An earlier version left the resolver un-stubbed, so it returned [] and the
    notice fell silent for the WRONG reason - a mutant that deleted the switch
    check entirely still passed. Feed it courses, so the only remaining reason
    to render nothing is the switch.
    """
    import shared.components as C
    from panopto import settings as S
    S.set_globally_enabled(True)
    monkeypatch.setattr(C, "panopto_disabled_courses", lambda mode: ["A", "B"])
    called = []
    monkeypatch.setattr(C.st, "markdown", lambda *a, **k: called.append(a))
    C.render_panopto_disabled_notice(mode="sync")
    assert called == []


def test_the_notice_is_silent_when_nothing_wanted_recordings(config_dir, monkeypatch):
    """Otherwise it appears on every run of every files-only course - which is
    nearly all of them."""
    import shared.components as C
    from panopto import settings as S
    S.set_globally_enabled(False)
    monkeypatch.setattr(C, "panopto_disabled_courses", lambda mode: [])
    called = []
    monkeypatch.setattr(C.st, "markdown", lambda *a, **k: called.append(a))
    C.render_panopto_disabled_notice(mode="sync")
    assert called == []


def test_the_notice_counts_courses_never_recordings(config_dir, monkeypatch):
    """Forced by the fix itself: discovery is skipped, so the recording count is
    genuinely unknown. Claiming one would mean running the very scan the switch
    exists to avoid."""
    import shared.components as C
    from panopto import settings as S
    S.set_globally_enabled(False)
    monkeypatch.setattr(C, "panopto_disabled_courses",
                        lambda mode: ["Makroøkonomi", "Statistik"])
    out = []
    monkeypatch.setattr(C.st, "markdown", lambda *a, **k: out.append(a[0]))
    C.render_panopto_disabled_notice(mode="sync")
    assert len(out) == 1
    html = out[0]
    assert "<b>2</b> course" in html
    assert "recording" not in html.split("</summary>")[0].replace(
        "Lecture recordings", ""), "the headline must not claim a recording count"
    assert "Makroøkonomi" in html and "Statistik" in html


def test_the_notice_escapes_course_names(config_dir, monkeypatch):
    """Course names are Canvas data and reach an unsafe_allow_html string."""
    import shared.components as C
    from panopto import settings as S
    S.set_globally_enabled(False)
    monkeypatch.setattr(C, "panopto_disabled_courses",
                        lambda mode: ["<img src=x onerror=alert(1)>"])
    out = []
    monkeypatch.setattr(C.st, "markdown", lambda *a, **k: out.append(a[0]))
    C.render_panopto_disabled_notice(mode="sync")
    assert "<img src=x" not in out[0]
    assert "&lt;img" in out[0]


def test_the_notice_says_nothing_was_lost(config_dir, monkeypatch):
    """Same register as its two siblings: nothing failed, nothing is missing."""
    import shared.components as C
    from panopto import settings as S
    S.set_globally_enabled(False)
    monkeypatch.setattr(C, "panopto_disabled_courses", lambda mode: ["A"])
    out = []
    monkeypatch.setattr(C.st, "markdown", lambda *a, **k: out.append(a[0]))
    C.render_panopto_disabled_notice(mode="sync")
    assert "Nothing is missing" in out[0]
    assert "Settings" in out[0]


@pytest.mark.parametrize("victim", ["is_globally_enabled", "resolver"])
def test_the_notice_never_raises_on_a_terminal_screen(config_dir, monkeypatch, victim):
    """A completion screen must appear in one frame and must never be the thing
    that breaks - and two of its three call sites sit where a raise blanks the
    screen. Both of the notice's inputs are driven to failure: the settings read
    (an unreadable config) and the course resolver (a locked manifest)."""
    import shared.components as C
    from panopto import settings as S
    S.set_globally_enabled(False)

    def _boom(*a, **k):
        raise RuntimeError("simulated failure")

    if victim == "is_globally_enabled":
        monkeypatch.setattr(S, "is_globally_enabled", _boom)
    else:
        monkeypatch.setattr(C, "panopto_disabled_courses", _boom)

    out = []
    monkeypatch.setattr(C.st, "markdown", lambda *a, **k: out.append(a))
    C.render_panopto_disabled_notice(mode="sync")  # must not raise
    assert out == [], "a failed input must render nothing, not a broken panel"


def test_the_course_resolver_never_raises(config_dir, monkeypatch):
    import shared.components as C
    monkeypatch.setattr(C.st, "session_state",
                        {"sync_pairs": [{"local_folder": "/nope", "course_id": 1}]},
                        raising=False)
    assert C.panopto_disabled_courses("sync") == []
    assert C.panopto_disabled_courses("download") == []


def test_both_completion_screens_render_the_notice_exactly_once():
    """A census. One per screen - and it used to be TWO in sync mode.

    CORRECTED 2026-08-11. This test asserted a count of 2 on the premise that
    "sync/completion.py has two terminal paths and both need the notice". There is
    only one: `show_sync_complete` renders the completion card once, and both
    blocks sat at the SAME level inside its single `with fresh_container(...)`,
    with no branch and no return between them - so both ran, every time. Three
    proofs: the AST shows a flat statement sequence; driving the real
    `show_sync_complete` produced **4** `.skip-panel`s for 2 facts; and app.py, the
    sibling screen whose comment says the order is "the same on both completion
    screens", has always had one of each.

    It shipped unseen because `pp_archives_skipped` and "Panopto is off" are both
    uncommon - most screens had nothing to double - and because
    scripts/completion_gallery.py, the review instrument for these screens,
    mirrors app.py's single block and was therefore MORE correct than the app.
    """
    assert "render_panopto_disabled_notice(mode='download')" in _strip_comments(_src("app.py"))
    sync = _strip_comments(_src("sync/completion.py"))
    assert sync.count("render_panopto_disabled_notice(mode='sync')") == 1, (
        "one screen, one panel - see the docstring for why 2 was wrong"
    )


def test_the_notice_follows_its_sibling_at_every_call_site():
    """Things of the same kind sit together - the module's own stated rule."""
    for rel in ("app.py", "sync/completion.py"):
        src = _strip_comments(_src(rel))
        for m in re.finditer(r"render_panopto_disabled_notice\(", src):
            before = src[:m.start()]
            assert "render_archives_skipped_notice()" in before, (
                f"{rel}: the Panopto panel is emitted before its family siblings"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Today notice + the model-manager dead end
# ═══════════════════════════════════════════════════════════════════════════

def test_today_reports_panopto_separately_from_missing_folders():
    """`skipped` means "your folder is gone, go fix it"; this means "working as
    configured". One needs an action, the other needs none."""
    fn = _func_src("core/auto_sync.py", "build_today_sync_notice")
    # The whole key/VALUE pair, not the key alone - `"panopto_off": []` keeps
    # the key while making the field permanently empty, and a key-only check
    # passes straight through that.
    assert '"panopto_off": panopto_off,' in fn
    assert '"skipped": skipped' in fn
    assert "panopto_disabled_courses('sync')" in fn, (
        "the field is no longer populated from the real resolver"
    )
    body = _strip_comments(_src("ui/today_dashboard.py"))
    assert 'notice.get("panopto_off")' in body
    assert "panopto_html" in body
    assert "{skipped_html}{panopto_html}" in body, (
        "the two must be separate lines in the notice, not merged"
    )


def test_the_model_manager_stays_reachable_while_something_is_installed():
    """It is the ONLY place a Whisper model or the CUDA libraries can be
    deleted, and those are multiple GB. Dimming it with them installed stranded
    that disk space behind a switch-on/delete/switch-off dance."""
    src = _strip_comments(_src("ui/auth.py"))
    assert "_pan_card_live = bool(temp_pan_enabled or _pan_installed)" in src
    assert "disabled=not _pan_card_live" in src
    assert 'key="stg_card_pan" if _pan_card_live else "stg_card_pan_off"' in src
    assert "cuda_provision" in src and "is_provisioned()" in src, (
        "the CUDA libraries are the larger of the two payloads and are removable "
        "from the same dialog - 'installed' must include them"
    )
    assert '"Manage installed models"' in src, (
        "with Panopto off the button is cleanup, not setup, and must say so"
    )
