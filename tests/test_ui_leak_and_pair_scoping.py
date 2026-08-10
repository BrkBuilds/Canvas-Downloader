"""Two classes of UI defect found by driving the real app on macOS, 2026-08-11.

1. RAW MARKUP LEAKED INTO THE PAGE. The config viewer printed its own
   ``<div style='display: flex; ...'>`` as literal source under "PANOPTO
   RECORDINGS". Cause: an optional interpolation alone on a line of an indented
   triple-quoted HTML string. Empty (the normal case) it leaves a BLANK LINE,
   which ends a type-6 HTML block for Markdown, and the following 4-space
   indented line becomes an indented CODE BLOCK.

   The subtle half is ``st.markdown``'s own transform:
   ``streamlit.string_util.clean_text`` is ``textwrap.dedent(...).strip()``, so
   an f-string whose lines are UNIFORMLY indented gets flattened and is
   harmless - which is why the completion card, with the identical shape, has
   never leaked. Only markup that also has a column-0 line (so dedent removes
   nothing) is at risk. Rule 10 encodes exactly that.

2. A PER-FOLDER FACT WAS KEYED ON THE COURSE. The sync list's "Ignored Files
   (N)" cache was keyed on ``course_id`` alone, so a user with one course synced
   into two folders saw one folder's count on both cards - and, worse, the
   dialog inherited the other folder's ``SyncManager``, so a restore would have
   written to a folder they were not looking at. Verified against the real
   manifests: folder A held 0 ignored rows, folder B 23, and both cards said 23.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re
import sys
import textwrap

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import verify_architecture as va  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]


# ── 1. the markup leak ────────────────────────────────────────────────────────

def _dangerous_lines(html: str) -> list[str]:
    """Lines Markdown would render as a code block, after Streamlit's transform.

    Reproduces ``clean_text`` exactly (dedent + strip) and then looks for the
    real precondition: a blank line followed by a line indented 4+ spaces.
    """
    cleaned = textwrap.dedent(html).strip()
    lines = cleaned.splitlines()
    out = []
    for i, ln in enumerate(lines[:-1]):
        if not ln.strip():
            nxt = lines[i + 1]
            if nxt.strip() and len(nxt) - len(nxt.lstrip(" ")) >= 4:
                out.append(nxt)
    return out


_BADGE_CASES = [
    # (settings, show_path). Panopto ON is the case that leaked: `pan_note` is
    # empty precisely when the feature is switched on.
    ({"download_mode": "flat", "file_filter": "all", "download_path": "/tmp/x",
      "pan_out_mp4": True}, True),
    ({"download_mode": "modules", "file_filter": "slides", "download_path": "",
      "pan_out_mp4": False}, False),
    ({"download_mode": "flat", "file_filter": "all", "download_path": "/tmp/x",
      "pan_out_mp4": True, "convert_pptx": True, "include_assignments": True}, True),
    ({"download_mode": "flat", "file_filter": "all"}, False),
]


@pytest.mark.parametrize("settings,show_path", _BADGE_CASES)
def test_config_badges_never_render_markup_as_text(settings, show_path):
    from shared.components import render_config_summary_badges
    html = render_config_summary_badges(dict(settings), show_path=show_path)
    bad = _dangerous_lines(html)
    assert not bad, (
        "this markup would print as a literal code block in the UI: " + str(bad[:1])
    )


@pytest.mark.parametrize("settings,show_path", _BADGE_CASES)
def test_config_badges_are_newline_free(settings, show_path):
    """The strongest form of the invariant: no newline, so no blank line, ever.

    Asserted rather than merely "no dangerous line" because the dangerous-line
    test alone passed for a fix that had only MOVED the fault - rebuilding
    `pan_html` as one line pushed the blank line onto the grid container, where
    the next line was indented 4 for the first time.
    """
    from shared.components import render_config_summary_badges
    html = render_config_summary_badges(dict(settings), show_path=show_path)
    assert "\n" not in html


def test_no_panopto_column_leak_specifically():
    """The reported symptom, named: the Panopto column's own div as visible text."""
    from shared.components import render_config_summary_badges
    for pan_on in (True, False):
        html = render_config_summary_badges(
            {"download_mode": "flat", "file_filter": "all", "pan_out_mp4": pan_on})
        cleaned = textwrap.dedent(html).strip()
        for ln in cleaned.splitlines():
            assert not (ln.startswith("    ") and "<div" in ln), (
                "a 4-space indented line containing a tag is what rendered as "
                f"source in the real app: {ln[:80]!r}")


# ── Rule 10, both directions ──────────────────────────────────────────────────

def _run_rule10(source: str):
    tree = ast.parse(source)
    return va.check_empty_interpolation_lines(
        tree, source, pathlib.Path("probe.py"), set())


def test_rule10_flags_the_shape_that_shipped():
    """The real defect, reduced: optional fragment alone on a line, column-0 line present."""
    src = textwrap.dedent('''
        def build(pan_badges):
            pan_note = ""
            if something:
                pan_note = "<div>note</div>"
            return f"""
        <div style='display: flex;'>
            <div style='width: 100%;'>Panopto Recordings</div>
            {pan_note}
            <div style='width: 100%;'>{pan_badges}</div>
        </div>
        """
        ''')
    hits = _run_rule10(src)
    assert len(hits) == 1, [h.message for h in hits]
    assert "pan_note" in hits[0].message


def test_rule10_exempts_uniformly_indented_html():
    """dedent flattens it, so the blank line is followed by an UNindented line.

    This is the completion card's shape. Flagging it would be a false positive -
    and it is the exemption that took a source reading of Streamlit's
    ``clean_text`` to justify, rather than a guess.
    """
    src = textwrap.dedent('''
        def build(title):
            notes_html = ""
            if something:
                notes_html = "<div>notes</div>"
            return f"""
            <div class="card">
                <div class="title">{title}</div>
                {notes_html}
            </div>
            """
        ''')
    assert _run_rule10(src) == []


def test_rule10_exempts_style_blocks():
    """<style> is a CommonMark type-1 block: it ends at </style>, not at a blank line."""
    src = textwrap.dedent('''
        def build():
            extra_css = ""
            if something:
                extra_css = ".x { color: red; }"
            return f"""
        <style>
        .a { color: blue; }
            {extra_css}
            .b { color: green; }
        </style>
        """
        ''')
    assert _run_rule10(src) == []


def test_rule10_ignores_interpolations_that_cannot_be_empty():
    """A constant or a call is not an optional fragment - flagging it is noise."""
    src = textwrap.dedent('''
        SVG = "<svg></svg>"

        def build(name):
            return f"""
        <div>
            <div>{SVG}</div>
            {esc(name)}
            <div>x</div>
        </div>
        """
        ''')
    assert _run_rule10(src) == []


def test_rule10_is_registered_and_labelled():
    assert 10 in va.RULE_LABELS
    src = (REPO / "scripts" / "verify_architecture.py").read_text(encoding="utf-8")
    assert "check_empty_interpolation_lines(tree, source, filepath, suppressed)" in src, \
        "Rule 10 must be wired into scan_file or it never runs"


# ── 2. ignored files are a PER-PAIR fact ──────────────────────────────────────

def test_ignored_cache_is_keyed_on_the_pair_not_the_course():
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    assert "ignored_by_course" not in src, (
        "the name records the bug: ignored files live in ONE folder's manifest, "
        "so the key must be the (course_id, folder) link"
    )
    assert "ignored_by_pair" in src
    # keyed through the app's ONE link primitive, not a second local one
    assert re.search(r"ignored_by_pair\[pair_key\(", src), \
        "must key through core.pair_labels.pair_key"
    assert re.search(r"ignored_by_pair\.get\(pair_key\(", src)


def test_pair_key_separates_two_folders_of_one_course():
    from core.pair_labels import pair_key
    a = pair_key(43660, "/Users/x/downloads/Course")
    b = pair_key(43660, "/Users/x/downloads/New folder/Course")
    assert a != b, "two folders of one course are two pairs - the whole point"
    # and the same link spelled differently is ONE pair
    assert pair_key("43660", "/Users/x/downloads/Course/") == a


def test_ignored_dialog_takes_and_uses_a_pair_signature():
    from ui.sync_dialogs import show_course_ignored_files
    params = inspect.signature(show_course_ignored_files).parameters
    assert "pair_sig" in params, (
        "the dialog's widget keys must be unique per PAIR: with a course-only "
        "prefix two pairs of one course shared every checkbox key"
    )
    src = inspect.getsource(show_course_ignored_files)
    assert "pair_sig" in src and "prefix = f\"cign_" in src
    assert re.search(r"prefix = f\"cign_\{course_id\}_\{_disc\}\"", src), \
        "the prefix must carry the per-pair discriminator, not just the course id"


def test_sync_ui_passes_the_pair_key_to_the_dialog():
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    m = re.search(r"_deferred_ignored = \(\s*(.+?)\)", src, re.S)
    assert m, "the deferred-ignored tuple moved - re-anchor"
    assert "pair_key(" in m.group(1), \
        "the dialog cannot scope its keys per pair unless it is told the pair"


# ── the smaller UI-truth fixes ────────────────────────────────────────────────

def test_fda_card_offers_an_action_in_both_states():
    """Granted used to render no button, making the card a dead end.

    Also a reconciliation fix: the keyed container emitted 2 children when not
    granted and 1 when granted, and Streamlit hands a block the CHILDREN of
    whatever occupied its index.
    """
    from shared.components import render_fda_settings_card as _card
    src = inspect.getsource(_card)
    assert "Manage access" in src
    assert "stg_fda_manage_btn" in src and "stg_fda_grant_btn" in src
    # exactly one button per branch -> same child count either way
    assert src.count("st.button(") == 2
    css = (REPO / "styles" / "global.css").read_text(encoding="utf-8")
    assert "st-key-stg_fda_manage_btn" in css, "the granted button must read monochrome"


def test_sync_analysis_phase_has_a_heading_like_its_siblings():
    a = (REPO / "sync" / "analysis.py").read_text(encoding="utf-8")
    assert '<h2 class="step-header">Analyzing...</h2>' in a
    # every other phase of the same flow has one at the same position
    assert '<h2 class="step-header">Syncing...</h2>' in \
        (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    assert '<h2 class="step-header">Sync Complete!</h2>' in \
        (REPO / "sync" / "completion.py").read_text(encoding="utf-8")
    # and it must sit inside the same `not _today_minimal` guard as the wizard,
    # or Today's in-page card grows a duplicate title
    m = re.search(r"if not _today_minimal:\s*\n\s*render_sync_wizard\(st, 'analyze'\)\s*\n\s*st\.markdown\('<h2", a)
    assert m, "heading must be guarded exactly like the wizard it follows"


def test_ignored_dialog_explains_both_empty_states():
    src = inspect.getsource(__import__("ui.sync_dialogs", fromlist=["x"]).show_course_ignored_files)
    assert "No ignored files to select from." in src, "Smart Select with nothing to select"
    assert "Nothing is ignored for this course any more." in src, "the emptied list"
    # the empty state must be an elif on the success notice: that notice is
    # popped as it renders, so the next rerun would otherwise show nothing at all
    assert re.search(r"render_success_notice\(.*\n\s*elif not files and not pan_ignored:",
                     src), "empty state must take over from the popped success notice"


def test_both_list_dialogs_have_a_height_floor():
    css = (REPO / "styles" / "global.css").read_text(encoding="utf-8")
    block = css[css.index("A dialog must never collapse to a sliver"):]
    assert 'st-key-cign_' in block and 'st-key-hub_' in block
    assert "min-height" in block
    # never applied to stDialog at large - small confirm dialogs are correct as-is
    assert 'div[data-testid="stDialog"] div[role="dialog"] > div:first-child {\n    min-height' not in css
