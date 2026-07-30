"""The UI state gallery must stay wired up.

These are dev tooling, not shipped code, so they are not covered by anything
else - and the ways they break are all silent. A renamed element id keeps
capturing screenshots and quietly drops every note filed against it; a
duplicated id merges two elements' notes; an `innerText` probe returns fewer
elements on exactly the states where a panel happens to be shut.

Nothing here launches a browser. The capture script's own `PROBLEMS` report is
what checks the live behaviour (see .claude/skills/ui-state-gallery/SKILL.md).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import ui_gallery  # noqa: E402
from scripts.capture_completion_gallery import DETECT_JS, ELEMENTS  # noqa: E402

GALLERY = (REPO / "scripts" / "completion_gallery.py").read_text(encoding="utf-8")
ENGINE = (REPO / "scripts" / "ui_gallery.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# the element vocabulary
# --------------------------------------------------------------------------

def test_element_ids_are_unique():
    """A duplicate id silently merges two elements' notes into one bucket."""
    ids = [i for i, _, _ in ELEMENTS]
    assert len(ids) == len(set(ids)), \
        f"duplicated: {sorted({i for i in ids if ids.count(i) > 1})}"


def test_every_element_has_a_label_and_a_group():
    for i, label, group in ELEMENTS:
        assert i and label and group, f"incomplete element row: {(i, label, group)}"


def test_every_element_is_actually_probed():
    """An element with no probe can never be detected, so its chip never
    appears and a note can never be filed against it. The capture reports this
    at runtime too, but only after a full browser pass."""
    missing = [i for i, _, _ in ELEMENTS if f"'{i}'" not in DETECT_JS]
    assert not missing, f"no probe adds these ids: {missing}"


def test_every_probed_id_is_in_the_vocabulary():
    """The inverse: a probe emitting an unknown id would render no chip."""
    known = {i for i, _, _ in ELEMENTS}
    emitted = set(re.findall(r"add\('([a-z0-9-]+)'", DETECT_JS))
    assert emitted <= known, f"probed but not declared: {sorted(emitted - known)}"


def test_the_detector_never_uses_innerText():
    """THE trap. A closed <details> is not rendered, so `innerText` drops
    everything inside one - which is most of the error panel and both skip
    panels, on exactly the states where they happen to be shut."""
    assert "innerText" not in DETECT_JS
    assert "textContent" in DETECT_JS


# --------------------------------------------------------------------------
# the catalogue
# --------------------------------------------------------------------------

def test_the_catalogue_covers_both_flows_and_every_headline():
    from scripts.completion_gallery import SCENARIOS
    assert len(SCENARIOS) >= 30
    ids = set(SCENARIOS)
    assert any(i.startswith("d-") for i in ids) and any(i.startswith("s-") for i in ids)
    # One per card variant in render_completion_card, both modes, plus cancelled.
    for required in ("d-success", "d-partial", "d-failure", "d-nothing",
                     "d-uptodate", "d-cancelled",
                     "s-success", "s-partial", "s-failure", "s-nothing",
                     "s-uptodate", "s-cancelled"):
        assert required in ids, f"catalogue lost {required}"


def test_every_state_has_a_title_and_a_reason_to_look_at_it():
    from scripts.completion_gallery import SCENARIOS
    for sid, (title, why, fn) in SCENARIOS.items():
        assert title and why and callable(fn), sid


def test_the_gallery_renders_one_state_per_page_load():
    """Two cards on one page fight over the same keyed <style> and Streamlit
    rejects the duplicate widget keys - see the module docstring."""
    assert 'st.query_params.get("v"' in GALLERY
    assert GALLERY.count("SCENARIOS[v][2]()") == 1


def test_the_page_render_is_behind_a_main_guard():
    """So the capture script can import the catalogue without executing a page
    render outside a Streamlit runtime."""
    assert 'if __name__ == "__main__":' in GALLERY
    assert GALLERY.index("def _page()") < GALLERY.index('if __name__ == "__main__":')


_ORDER_MARKERS = [
    "render_completion_card(",
    "render_archives_skipped_notice(",
    "render_error_section(",
    "render_pp_warning(",
]


def _order(src: str, start: str, end: str) -> list[str]:
    body = src.split(start, 1)[1].split(end, 1)[0]
    found = [(body.find(m), m) for m in _ORDER_MARKERS if body.find(m) >= 0]
    return [m for _, m in sorted(found)]


def test_the_gallery_renders_the_same_order_as_the_real_screens():
    """THE trap this whole tool exists to avoid.

    The gallery shells are a second copy of each completion screen's
    composition, so a reordering applied to app.py and sync/completion.py but
    not here produces screenshots of a screen that does not exist - and they
    look entirely plausible. That happened once already: the app was regrouped
    to stats -> Panopto -> collapsibles -> notices and the captured images
    still showed the old interleaving.

    The order itself is the contract: metrics first, then everything that can
    be opened, then the run's asides.
    """
    app = (REPO / "app.py").read_text(encoding="utf-8")
    sync = (REPO / "sync" / "completion.py").read_text(encoding="utf-8")

    real_dl = _order(app, "elif st.session_state.get('download_status') == 'done':",
                     "render_folder_cards(")
    mock_dl = _order(GALLERY, "def download_screen(", "def sync_screen(")
    assert real_dl == mock_dl, f"download: app={real_dl} gallery={mock_dl}"

    real_sync = _order(sync, "def show_sync_complete(", "render_folder_cards(")
    mock_sync = _order(GALLERY, "def sync_screen(", "def _front_page(")
    assert real_sync == mock_sync, f"sync: app={real_sync} gallery={mock_sync}"

    # And the contract itself, so "identical" cannot mean "identically wrong".
    assert real_dl == _ORDER_MARKERS, \
        "collapsibles must precede notices, and the error panel is the last one"


def test_the_panopto_grid_renders_inside_the_completion_card():
    """It is a stat grid, so it belongs under the run's other stat grid rather
    than several elements below it. Both screens pass it as a parameter now; a
    call site rendering it itself would put it back where it was."""
    comp = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    card = comp.split("def render_completion_card(", 1)[1].split("\ndef ", 1)[0]
    assert "render_panopto_summary(panopto_summary)" in card
    for path in ("app.py", "sync/completion.py"):
        src = (REPO / path).read_text(encoding="utf-8")
        assert "panopto_summary=st.session_state.get('panopto_summary')" in src
        assert "render_panopto_summary(" not in src, \
            f"{path} renders the Panopto card itself again"


def test_sample_files_are_written_to_disk():
    """`render_folder_cards` hides Open Folder unless the path exists and
    disables the per-file actions unless the file does, so fictional paths
    would review the disabled paint."""
    assert "target.write_bytes" in GALLERY
    assert "mkdir(parents=True" in GALLERY


# --------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------

def test_the_shot_is_proven_not_to_be_clipped():
    """stMain is the scroll container; Playwright scrolls the window. Without
    the viewport grow, everything below the fold is a black band."""
    assert "set_viewport_size" in ENGINE
    assert "scrollHeight - m.clientHeight" in ENGINE


def test_the_capture_waits_for_the_startup_overlay_to_leave():
    assert "cd-boot" in ENGINE


def test_elements_are_detected_after_expanding():
    """Detecting first would miss anything inside a closed collapsible."""
    body = ENGINE.split("def capture(", 1)[1]
    assert body.index("surface.expand_js") < body.index("surface.detect_js")


def test_a_legacy_store_key_is_read_so_a_review_in_progress_survives():
    """Renaming the localStorage key silently orphans notes already taken."""
    assert "legacyKeys" in ENGINE
    from scripts.capture_completion_gallery import main  # noqa: F401
    src = (REPO / "scripts" / "capture_completion_gallery.py").read_text(encoding="utf-8")
    assert "legacy_keys=" in src


def test_the_review_page_is_self_contained():
    """It is opened from a static folder with no build step, so an external
    request would simply fail."""
    page = ui_gallery._PAGE
    assert "<script" in page and "</script>" in page
    assert not re.search(r'(src|href)\s*=\s*["\']https?://', page), \
        "the review page must not reference an external host"


def test_renders_never_default_into_the_published_website():
    src = (REPO / "scripts" / "capture_completion_gallery.py").read_text(encoding="utf-8")
    assert '"ui-review"' in src
    assert 'REPO / "docs"' not in src
    assert "ui-review/" in (REPO / ".gitignore").read_text(encoding="utf-8")
