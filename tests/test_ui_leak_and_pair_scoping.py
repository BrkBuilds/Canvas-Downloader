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
    src = inspect.getsource(
        __import__("ui.sync_dialogs", fromlist=["x"]).show_course_ignored_files)
    assert "No ignored files to select from." in src, "Smart Select with nothing to select"
    assert "Nothing is ignored for this course any more." in src, "the emptied list"


def test_both_list_dialogs_keep_their_shape_when_empty():
    """The height lives on each dialog's CONTENT region, never on the dialog.

    Ignored Files keeps its sized `_filelist` container even when empty; the hub
    renders its empty state inside a container of the same height as its populated
    card list, from ONE constant so the two cannot drift.
    """
    hub = (REPO / "ui" / "hub_dialog.py").read_text(encoding="utf-8")
    assert "HUB_LIST_HEIGHT = 580" in hub
    assert 'key="hub_empty_area"' in hub
    assert "st.container(height=580" not in hub, \
        "the populated list must read the same constant as the empty state"
    assert hub.count("st.container(height=HUB_LIST_HEIGHT") >= 2

# ── 3. a JS-gated button must never render UNGATED (2026-08-11) ───────────────
#
# `live_enable_button` injects its greying CSS into the PARENT document, keyed by
# button key (`cd-live-css-<key>`), behind `if (!doc.getElementById(...))` - so it
# is written once and never removed for the life of the session. Its polarity is
# `button:not([data-cd-valid="1"])`, i.e. a MISSING marker means disabled, and only
# the bridge ever sets that marker.
#
# So any render that shows the button WITHOUT calling the helper inherits a
# permanently greyed, pointer-events:none button. That is what happened to Save as
# Pair: it shares `save_group_create` with Save as Group (which always gates) and
# skipped gating whenever the course supplied a suggested name.

def _live_enable_calls(tree: ast.AST):
    """(call node, enclosing If nodes) for every live_enable_button call."""
    out = []

    def walk(node, ifs):
        for child in ast.iter_child_nodes(node):
            nxt = ifs + [child] if isinstance(child, ast.If) else ifs
            if (isinstance(child, ast.Call)
                    and getattr(child.func, "id", None) == "live_enable_button"):
                out.append((child, ifs))
            walk(child, nxt)

    walk(tree, [])
    return out


def _button_keys_in(node: ast.AST) -> set[str]:
    keys = set()
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "button"):
            for kw in n.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                    keys.add(kw.value.value)
    return keys


_GATE_FILES = ["ui/hub_dialog.py", "ui/presets.py", "ui/course_selector.py",
               "sync_ui.py", "app.py", "shared/components.py"]


def test_no_gated_button_can_render_without_its_gate():
    """If the gate is conditional, the button it gates must be under the same condition.

    The safe pattern (the hub's rename row) renders BOTH inside one ``if``, so the
    key and the gate are always co-present. The broken pattern renders the button
    unconditionally and the gate inside an ``if`` - which strands the gate.
    """
    problems = []
    for rel in _GATE_FILES:
        path = REPO / rel
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        if "live_enable_button(" not in src:
            continue
        tree = ast.parse(src)
        for call, enclosing_ifs in _live_enable_calls(tree):
            if not enclosing_ifs:
                continue                      # unconditional - nothing to prove
            passes_active = any(kw.arg == "active" for kw in call.keywords)
            if passes_active:
                continue                      # gate state is a value, not a branch
            if len(call.args) < 2 or not isinstance(call.args[1], ast.Constant):
                continue
            btn_key = call.args[1].value
            # the button must be rendered inside the SAME condition
            if btn_key not in _button_keys_in(enclosing_ifs[-1]):
                problems.append(f"{rel}:{call.lineno} gates {btn_key!r} conditionally "
                                f"while the button renders outside that branch")
    assert not problems, (
        "a stranded gate greys the button for the whole session:\n  "
        + "\n  ".join(problems))


def test_save_pair_gate_is_unconditional_and_passes_active():
    from ui.hub_dialog import save_group_or_pair_inner
    src = inspect.getsource(save_group_or_pair_inner)
    tree = ast.parse(textwrap.dedent(src))
    calls = _live_enable_calls(tree)
    assert len(calls) == 1, "one gate call in this dialog"
    call, enclosing = calls[0]
    assert not enclosing, (
        "the call must NOT sit in an `if` - the skipped branch is the bug; pass "
        "the condition as active= instead"
    )
    assert any(kw.arg == "active" for kw in call.keywords)
    assert "active=not (is_pair and _suggested_name)" in src.replace("\n", " ") \
        or "active=not (is_pair and _suggested_name)" in src


def test_inactive_gate_tears_the_previous_one_down():
    """active=False must REMOVE the parent-document style, not merely skip adding it."""
    from shared.components import live_enable_button
    src = inspect.getsource(live_enable_button)
    assert "if (!ACTIVE)" in src, "there must be a teardown branch"
    teardown = src[src.index("if (!ACTIVE)"):]
    teardown = teardown[:teardown.index("// Inject")]
    assert "removeChild" in teardown, "the persisted <style> must be removed"
    assert "removeAttribute('data-cd-valid')" in teardown
    assert "removeAttribute('title')" in teardown, \
        "a stale reason tooltip would describe a state that no longer applies"


def test_gate_polarity_is_still_fail_closed_while_active():
    """Unknown state must read as UNAVAILABLE while the bridge is running.

    This is deliberate and must not be flipped to fix the bug above: the fix is to
    tear the gate down when it does not apply, not to make an unmarked button look
    clickable (which would let a click land on an empty name and silently do
    nothing).
    """
    from shared.components import live_enable_button
    src = inspect.getsource(live_enable_button)
    assert 'button:not([data-cd-valid="1"])' in src


# ── 4. the edited pair is identified by its LINK, never by its position ───────
#
# PROVEN reachable 2026-08-11, not merely untidy. `editing_pair_idx` is an index
# into st.session_state['sync_pairs'], and the list moves under an open edit form:
# the form replaces its OWN row, but every other row keeps a live Remove button
# (and a remove-all path exists). The save then did
# `sync_pairs[editing_pair_idx]`, which gave:
#
#   [A,B,C]    edit C (idx 2), remove A -> `0 <= 2 < 2` false -> Save Changes
#              APPENDED a duplicate pair instead of editing.
#   [A,B,C,D]  edit C (idx 2), remove A -> idx 2 is now D -> Save Changes
#              repointed D at C's chosen folder/course and MOVED D's user-given
#              name to that link (_retarget_saved_pair_lazy). C untouched.

def _sync_dialog_src() -> str:
    return (REPO / "ui" / "sync_dialogs.py").read_text(encoding="utf-8")


def _code_lines(src: str) -> str:
    """Drop whole-line comments.

    Full string-awareness is not needed here (unlike the AppleScript scan in
    tests/test_macos_no_accessibility_permission.py, where the thing being
    policed LIVES in a string literal): the patterns below are Python
    subscripts, and the only false positive is the explanatory comment that
    names the very expression it warns against.
    """
    return "\n".join(ln for ln in src.splitlines()
                      if not ln.lstrip().startswith("#"))


def test_edit_save_never_indexes_sync_pairs_by_editing_idx():
    src = _code_lines(_sync_dialog_src())
    for bad in ("sync_pairs'][editing_idx]", "sync_pairs'][edit_idx]",
                'sync_pairs"][editing_idx]', 'sync_pairs"][edit_idx]'):
        assert bad not in src, (
            f"{bad} resolves the edited pair by POSITION; the list can shift "
            "while the form is open"
        )


def test_edit_save_resolves_the_pair_through_pair_key():
    src = _sync_dialog_src()
    assert "_edit_sig = st.session_state.get('editing_pair_sig')" in src
    assert "from core.pair_labels import pair_key as _pk" in src, \
        "must use the app's one link primitive, not a locally-rolled key"
    assert "_edit_pair = next(" in src
    assert "old_pair = _edit_pair" in src


def test_an_edit_whose_pair_vanished_does_not_become_an_add():
    """The old else-branch silently turned a lost edit into a duplicate pair."""
    src = _sync_dialog_src()
    i = src.index("if is_edit_mode and _edit_pair is None:")
    j = src.index("_add_pair_lazy(new_pair)")
    assert i < j, "the guard must come BEFORE the append branch"
    guard = src[i:j]
    assert "st.stop()" in guard, "it must stop, not fall through to append"
    # phrase chosen to sit within one source line - the message is split across
    # several string literals, so a longer phrase would span a line break and the
    # test would report a missing guard that is right there
    assert "removed from the sync list while you" in guard, \
        "and it must say so - a silently-refused save is worse than a duplicate"


def test_edit_form_is_matched_on_the_link_so_it_follows_its_pair():
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    assert "editing_sig = st.session_state.get('editing_pair_sig')" in src
    assert re.search(r"_is_editing_row = \(\s*pair_key\(", src), \
        "the row match must be on the link, so the form follows a shifted pair"
    # and a vanished pair must close the form rather than bind it to a stranger
    assert "_still_listed = any(" in src
    assert re.search(r"if not _still_listed:\s*\n\s*st\.session_state\['pending_sync_folder'\] = None",
                     src)


def test_edit_state_is_cleared_as_a_SET_everywhere():
    """editing_pair_sig must be dropped wherever editing_pair_idx is dropped.

    A surviving sig with no idx (or the reverse) is a half-open form - exactly the
    kind of split state this key was added to remove.
    """
    for rel in ("ui/sync_dialogs.py", "sync_ui.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        idx_clears = len(re.findall(r"pop\('editing_pair_idx', None\)", src))
        sig_clears = len(re.findall(r"pop\('editing_pair_sig', None\)", src))
        assert idx_clears == sig_clears, (
            f"{rel}: {idx_clears} idx clears vs {sig_clears} sig clears - a "
            "clear site was missed, leaving half the edit state behind")


def test_editing_pair_sig_is_declared_in_the_state_registry():
    src = (REPO / "core" / "state_registry.py").read_text(encoding="utf-8")
    assert src.count("'editing_pair_sig': None,") == 2, \
        "state_registry is the single source of truth for keys + defaults"


# ── the folder picker opens where you can actually choose ─────────────────────

def test_picker_start_for_existing_returns_the_parent(tmp_path):
    from shared.helpers import picker_start_for_existing as f
    sub = tmp_path / "Course (LA E25 BINTO1060U)"
    sub.mkdir()
    assert f(str(sub)) == str(tmp_path), (
        "re-choosing a folder must list its SIBLINGS; opening inside it forces "
        "the user to navigate up before they can pick anything"
    )


@pytest.mark.parametrize("value", ["", None])
def test_picker_start_passes_empty_through(value):
    """So the caller's own fallback chain (session default -> ~/Downloads) applies."""
    from shared.helpers import picker_start_for_existing as f
    assert f(value) == value


def test_picker_start_leaves_a_missing_path_alone(tmp_path):
    from shared.helpers import picker_start_for_existing as f
    missing = str(tmp_path / "gone")
    assert f(missing) == missing


def test_picker_start_never_climbs_past_a_root():
    from shared.helpers import picker_start_for_existing as f
    assert f("/") == "/"


def test_change_folder_call_sites_open_at_the_parent():
    """The rule is written once and every re-choose site must use it."""
    for rel in ("app.py", "ui/hub_dialog.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        for m in re.finditer(r"native_folder_picker\(initial_dir=([^)]*)\)", src, re.S):
            arg = m.group(1)
            # download-DESTINATION pickers legitimately open inside the folder
            if "download_path" in arg or "_temp_default_path" in arg:
                continue
            assert "picker_start_for_existing" in arg, (
                f"{rel}: a change-folder picker still opens inside the folder: "
                f"{arg.strip()[:60]}")


def test_duplicate_check_excludes_self_by_identity_not_index():
    """Excluding a POSITION excluded the wrong pair once the list shifted.

    Both directions are wrong: a real duplicate goes unreported, and a
    legitimate save can be blocked with "this pair is already on your sync list".
    """
    src = _code_lines(_sync_dialog_src())
    assert "if i != editing_idx" not in src
    assert "candidates = [p for p in existing if p is not _edit_pair]" in src


# ── 5. regressions from my own first attempt, caught by looking in a browser ───
#
# Both were shipped without visual verification and both were wrong. Measured in
# Chrome afterwards:
#   * min-height on `div[role="dialog"] > div:first-child` -> that is NOT the
#     padded body. The dialog has three children and the first is a chrome
#     wrapper, so the rule inflated it into a 300px empty band ABOVE the title
#     (title top=62 -> top=290).
#   * removing the Smart Select card's bottom padding AND pulling its label up by
#     the same amount double-counted: card 39px vs label 49px, so the hover strip
#     hung 11px BELOW the card it lives in.

def test_dialog_height_is_never_put_on_the_dialogs_own_wrapper():
    css = (REPO / "styles" / "global.css").read_text(encoding="utf-8")
    for m in re.finditer(r'div\[role="dialog"\] > div:first-child[^{]*\{([^}]*)\}', css):
        assert "min-height" not in m.group(1), (
            "that element is a chrome wrapper, not the body - a height there "
            "becomes an empty band above the title"
        )


def test_ignored_dialog_always_renders_its_content_area():
    src = inspect.getsource(
        __import__("ui.sync_dialogs", fromlist=["x"]).show_course_ignored_files)
    assert not re.search(
        r"if all_file_tuples or pan_ignored:\s*\n\s*with st\.container\(height=filelist_height",
        src), "the sized content area must render when empty too, or the dialog collapses"
    m = re.search(r'with st\.container\(height=filelist_height, border=True, '
                  r'key=f"\{prefix\}_filelist"\):', src)
    assert m, "the content area moved - re-anchor this test"
    after = src[m.end():m.end() + 1200]
    assert "if not (all_file_tuples or pan_ignored):" in after
    assert "Nothing is ignored for this course any more." in after, \
        "the empty state belongs INSIDE the content area, where the list was"


def test_smart_select_label_is_not_pulled_past_its_own_card():
    src = (REPO / "ui" / "sync_dialogs.py").read_text(encoding="utf-8")
    i = src.index("COLLAPSED: the card must be exactly as tall")
    block = src[i:i + 1800]
    assert "padding-bottom: 0 !important;" in block, "the dead band IS the card's padding"
    assert "margin-bottom: -{card_pad_y}px" not in block, (
        "the label's own padding already recreates the inset; pulling it up as "
        "well makes the hover strip overhang the card"
    )


def test_folder_autodetect_only_fires_when_the_folder_actually_changed():
    src = (REPO / "ui" / "sync_dialogs.py").read_text(encoding="utf-8")
    assert re.search(r"if _nfk\(folder_path\) != _nfk\(_prev\):\s*\n\s*"
                     r"_auto_detect_course_from_manifest\(folder_path\)", src), (
        "confirming the picker without navigating changes nothing and must look "
        "like it - it announced an auto-detected course for an unchanged folder")
    assert "norm_folder_key as _nfk" in src, "compare through the one folder normaliser"
