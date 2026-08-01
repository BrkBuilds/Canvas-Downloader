"""The help card must never again unfold itself behind an open dialog.

The defect
----------
Reported 2026-07-30: opening Saved Groups & Pairs on the sync page and deleting
a saved pair made the Help card behind the dialog expand on its own, and it
stayed expanded until the dialog was dismissed.

It was not a stray click. Three Streamlit facts combine:

1. ``st.html("<style>...</style>")`` - a body of nothing but style tags - is not
   rendered where you call it. ``streamlit/elements/html.py`` routes it to the
   EVENT root container (``_html_only_style_tags`` -> ``self._event_dg._enqueue``),
   one global INDEX-ADDRESSED list.
2. ``st.toast`` writes to that same list (``streamlit/__init__.py``:
   ``toast = _event.toast``), and a toast is inherently conditional.
3. A ``@st.dialog`` body is a FRAGMENT, and ``streamlit/runtime/fragment.py``
   snapshots ``ctx.cursors`` at the dialog's CALL SITE and restores it on every
   fragment rerun - rewinding that list's write index.

The hub was invoked at ``sync_ui.py:1294``; ``render_help_card(mode="card")``
emitted its stylesheet at 1297, i.e. the first event-container write after the
call site. Deleting a pair queues a toast (``ui/hub_dialog.py:306``), the
fragment reran, and the toast landed on the stylesheet's index and deleted it.
Measured in the real app: the event list went 8 entries -> 7,
``cdHelpSlideDown`` vanished document-wide, and the card rendered 951px tall
with its checkbox still ``checked === false``.

The help card's CSS is the only CSS in the app whose ABSENCE makes hidden
content APPEAR, which is why this one became a visible UX failure while the
same mechanism only ever degraded styling behind a modal elsewhere.

What is locked down here
------------------------
* ``render_help_card`` writes no stylesheet at all - its CSS lives in
  ``styles/global.css``, which ``inject_css()`` puts in the MAIN container
  where no fragment can rewind it.
* Every class the component emits still has a rule in that stylesheet. The
  markup and its CSS now live in different files, so nothing but a test keeps
  them in step.
* The three display rules whose loss caused the symptom are present.
* Both pages invoke their dialogs AFTER every event-container write.
* Rule 9 of the audit still catches the shape, in both directions.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import verify_architecture as va  # noqa: E402

_FAKE = pathlib.Path("t.py")
GLOBAL_CSS = (REPO / "styles" / "global.css").read_text(encoding="utf-8")
COMPONENTS_SRC = (REPO / "shared" / "components.py").read_text(encoding="utf-8")


def _func(src: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    return next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name)


# ---------------------------------------------------------------------------
# The component emits no stylesheet of its own
# ---------------------------------------------------------------------------

def test_render_help_card_makes_no_event_container_write():
    """No st.html at all inside render_help_card.

    A style-only st.html would put the card's CSS back in the event container,
    which is exactly what a dialog's fragment rerun overwrites.
    """
    fn = _func(COMPONENTS_SRC, "render_help_card")
    html_calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "html"
    ]
    assert html_calls == [], (
        "render_help_card must not call st.html - a style-only st.html lands in "
        "Streamlit's EVENT container, which a dialog fragment rerun rewinds and "
        "overwrites. Put the CSS in styles/global.css instead."
    )


def test_render_help_card_emits_no_style_tag():
    """Not via st.markdown either - that would cost a flex gap slot on 8 screens."""
    fn = _func(COMPONENTS_SRC, "render_help_card")
    # Skip the docstring: it EXPLAINS the style-block hazard and naturally
    # quotes the tag it is warning about.
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    literals = "".join(
        n.value for stmt in body for n in ast.walk(stmt)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    )
    assert "<style" not in literals.lower(), (
        "render_help_card must emit no <style> block; its CSS belongs in global.css"
    )


# ---------------------------------------------------------------------------
# markup <-> stylesheet, now in different files, must stay in step
# ---------------------------------------------------------------------------

# Every class the component puts in the DOM. A class with no rule renders
# unstyled and, for the display-critical ones, renders VISIBLY.
EMITTED_CLASSES = [
    "cd-help-wrap",
    "cd-help-cb",
    "cd-help-card",
    "cd-help-close",
    "cd-help-card-title",
    "cd-help-card-body",
    "cd-help-trigger-row",
    "cd-help-trigger-row--end",
    "cd-help-trigger",
]


def _class_tokens(text: str) -> set[str]:
    """Every complete ``cd-help*`` class token in *text*.

    Whole tokens, not substrings: ``cd-help-trigger-row`` is a PREFIX of
    ``cd-help-trigger-row--end``, so a plain ``in`` check cannot tell a rename
    from a match and silently passes when someone renames only one side. The
    mutation run that proved this is why the trailing-character guard is here.
    """
    # A token ending in '-' is the f-string PREFIX of the checkbox id
    # (``cb_id = f"cd-help-{key_prefix}"``), not a class. No real class name
    # ends in a hyphen, so dropping those is exact rather than a fudge.
    return {t for t in re.findall(r"cd-help[A-Za-z0-9_-]*", text)
            if not t.endswith("-")}


CSS_CLASSES = _class_tokens(GLOBAL_CSS)
COMPONENT_CLASSES = _class_tokens(COMPONENTS_SRC)


@pytest.mark.parametrize("cls", EMITTED_CLASSES)
def test_emitted_class_is_styled_in_global_css(cls):
    if cls == "cd-help-wrap":
        pytest.skip("structural wrapper only - carries no rule by design")
    assert cls in CSS_CLASSES, (
        f"render_help_card emits class '{cls}' but global.css has no rule for it. "
        f"global.css knows: {sorted(CSS_CLASSES)}"
    )


@pytest.mark.parametrize("cls", EMITTED_CLASSES)
def test_emitted_class_is_actually_emitted(cls):
    """The other direction: a class named in CSS that the component stopped
    emitting is dead weight, and a rename touching only one file is caught by
    whichever half of the pair goes missing."""
    assert cls in COMPONENT_CLASSES, (
        f"global.css styles '{cls}' but render_help_card no longer emits it. "
        f"components.py knows: {sorted(COMPONENT_CLASSES)}"
    )


def test_no_orphan_help_classes_in_either_file():
    """Nothing on either side that the other has never heard of.

    This is the check that actually catches a one-sided rename: the renamed
    token appears in one file's set and in neither the expected list nor the
    other file's set.
    """
    expected = set(EMITTED_CLASSES)
    assert CSS_CLASSES <= expected, (
        f"global.css styles help classes the component does not emit: "
        f"{sorted(CSS_CLASSES - expected)}")
    assert COMPONENT_CLASSES <= expected, (
        f"components.py emits help classes global.css does not style: "
        f"{sorted(COMPONENT_CLASSES - expected)}")


# The three rules whose disappearance produced the reported symptom. Losing any
# one of them makes the closed card take space, show its body, or expose the
# raw checkbox.
@pytest.mark.parametrize("rule", [
    r"\.cd-help-cb\s*\{[^}]*display:\s*none",
    r"\.cd-help-card\s*\{[^}]*display:\s*none",
    r"stElementContainer\"\]:has\(\.cd-help-cb:not\(:checked\)\)",
])
def test_the_three_display_rules_survive(rule):
    assert re.search(rule, GLOBAL_CSS), (
        "a display rule the closed help card depends on is missing from global.css"
    )


def test_open_state_still_reachable():
    """The card must still be able to OPEN - a fix that just nails it shut
    would pass every check above."""
    assert re.search(r"\.cd-help-cb:checked\s*~\s*\.cd-help-card\s*\{[^}]*display:\s*block",
                     GLOBAL_CSS)


def test_trigger_selector_matches_the_generated_key():
    """global.css keys the trigger off the suffix the component builds."""
    assert '_explainer_help_btn"' in GLOBAL_CSS
    assert '_explainer_help_btn"' in COMPONENTS_SRC


# ---------------------------------------------------------------------------
# Both pages invoke their dialogs after every event-container write
# ---------------------------------------------------------------------------

def _dialog_call_lines(src: str, fn_name: str, dialog_names: set[str]) -> list[int]:
    fn = _func(src, fn_name)
    return [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and va._called_name(n) in dialog_names]


def test_sync_page_opens_the_hub_after_the_help_card():
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    fn = _func(src, "render_sync_step1")
    hub = _dialog_call_lines(src, "render_sync_step1", {"_saved_groups_hub_dialog"})
    help_card = [n.lineno for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and va._called_name(n) == "render_help_card"]
    assert hub, "the sync page no longer opens the Saved Groups hub"
    assert help_card, "the sync page no longer renders the help card"
    assert min(hub) > max(help_card), (
        "_saved_groups_hub_dialog() must be invoked AFTER render_help_card(); "
        "a dialog's fragment rerun rewinds the event container to its call site"
    )


def test_sync_list_dialogs_are_returned_not_opened():
    """_sync_pairs_section must hand its dialogs back, not open them.

    Its own tail LOOKS like the end of something, but the helper is called from
    the middle of render_sync_step1, and the Analyze / Quick Sync stylesheet is
    emitted after it. Opening a dialog there destroyed that stylesheet: both
    buttons lost `height: 3.2em` / `font-size: 1rem` and the page jumped.
    """
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    fn = _func(src, "_sync_pairs_section")
    opened = [va._called_name(n) for n in va._own_nodes(fn)
              if isinstance(n, ast.Call)
              and va._called_name(n) in {"_save_pair_dialog", "_save_group_dialog",
                                         "_show_course_ignored_files"}]
    assert opened == [], (
        f"_sync_pairs_section opens {opened} directly; return them instead so "
        f"render_sync_step1 can open them after its last stylesheet")


def test_sync_page_opens_every_dialog_after_its_last_stylesheet():
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    fn = _func(src, "render_sync_step1")
    openers, _ = va._project_index()
    dialog_lines = [n.lineno for n in va._own_nodes(fn)
                    if isinstance(n, ast.Call) and va._called_name(n) in openers]
    style_lines = [n.lineno for n in va._own_nodes(fn)
                   if isinstance(n, ast.Call) and va._is_style_only_html_call(n)]
    assert dialog_lines and style_lines
    assert min(dialog_lines) > max(style_lines), (
        "every dialog on the sync page must be opened after the last "
        f"style-only st.html(); dialogs at {sorted(dialog_lines)}, "
        f"stylesheets at {sorted(style_lines)}")


def test_every_deferred_sync_dialog_is_actually_opened():
    """Deferring a dialog must not quietly stop opening it.

    The ordering tests above are all satisfied by a page that never opens the
    dialog at all - which is precisely how a hoist goes wrong. Mutation-checked:
    disabling the save-pair branch, or dropping _sync_pairs_section's return
    value, passes every other test in this file.
    """
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    fn = _func(src, "render_sync_step1")
    called = {va._called_name(n) for n in va._own_nodes(fn)
              if isinstance(n, ast.Call)}
    for name in ("_saved_groups_hub_dialog", "_save_pair_dialog",
                 "_save_group_dialog", "_show_course_ignored_files",
                 "select_course_dialog_inner"):
        assert name in called, (
            f"render_sync_step1 never opens {name}() - a deferred dialog that "
            f"nothing opens is a dialog that no longer works")

    # ...and the deferral values must actually be read back.
    assigns = [n for n in va._own_nodes(fn) if isinstance(n, ast.Assign)
               and isinstance(n.value, ast.BoolOp | ast.Call)]
    assert any("_sync_pairs_section" in ast.dump(a.value) for a in assigns), (
        "render_sync_step1 must capture _sync_pairs_section()'s return value; "
        "without it the sync list's dialogs can never open")


def test_course_select_dialog_is_flagged_not_called():
    """render_pending_folder_ui sits mid-page; it must only raise a flag."""
    src = (REPO / "ui" / "sync_dialogs.py").read_text(encoding="utf-8")
    fn = _func(src, "render_pending_folder_ui")
    assert not [n for n in va._own_nodes(fn) if isinstance(n, ast.Call)
                and va._called_name(n) == "select_course_dialog_inner"], (
        "render_pending_folder_ui must set _sync_open_course_dialog instead of "
        "opening the dialog from the middle of the page")
    assert "_sync_open_course_dialog" in src


def test_today_import_dialog_is_flagged_not_called():
    src = (REPO / "ui" / "today_dashboard.py").read_text(encoding="utf-8")
    fn = _func(src, "_request_import_dialog")
    assert not [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and va._called_name(n) == "_import_courses_dialog"], (
        "_request_import_dialog must set a flag, not open the dialog mid-page")
    page = _func(src, "render_today_dashboard")
    opens = [n.lineno for n in va._own_nodes(page) if isinstance(n, ast.Call)
             and va._called_name(n) == "_import_courses_dialog"]
    styles = [n.lineno for n in va._own_nodes(page)
              if isinstance(n, ast.Call) and va._is_style_only_html_call(n)]
    assert opens, "render_today_dashboard never opens the import dialog"
    if styles:
        assert min(opens) > max(styles)


# ---------------------------------------------------------------------------
# The page must not be wrapped in st.empty().container()
# ---------------------------------------------------------------------------

def test_page_is_not_wrapped_in_an_empty_placeholder():
    """app.py must render the page in a PLAIN container.

    `st.empty()` enqueues an `Empty` delta. `slot = st.empty(); slot.container()`
    puts both deltas on one path and ForwardMsgQueue composes them, so the Empty
    normally never ships - but composition only holds while both are still
    queued, and the runtime flushes every ~10ms. Lose that race and the browser
    renders an empty box IN PLACE OF THE WHOLE PAGE.

    Measured 2026-07-31 by driving 300 rapid reruns: the page blanked FOUR times
    (~1.3%), stMain down to 5-6 zero-height containers with innerText "" and one
    stEmpty present, ~20ms each. That is the reported "after a certain amount of
    clicks the whole page turns dark for ~10ms and comes back with no shifting".
    After the change, the same 300-click storm: minimum element count 50, zero
    dips.
    """
    src = (REPO / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Any `X = st.empty()` whose X is later used as `X.container()` at module level.
    empties = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name)
               and isinstance(n.value, ast.Call)
               and isinstance(n.value.func, ast.Attribute)
               and n.value.func.attr == "empty"}
    backfilled = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "container"
                  and isinstance(n.func.value, ast.Name)
                  and n.func.value.id in empties]
    assert not backfilled, (
        "app.py wraps the page in st.empty().container() again (line "
        f"{backfilled[0].lineno}). That blanks the ENTIRE page on ~1.3% of "
        "reruns when the Empty wins the flush race - use a plain st.container().")


# ---------------------------------------------------------------------------
# The inline add/edit form must stay isomorphic to the row it replaces
# ---------------------------------------------------------------------------
# Streamlit reconciles by index and prunes the previous run's nodes only when
# the script run FINISHES, so a form rendered at a list row's index must match
# that row in BOTH shape numbers or the old render stays on screen:
#   * slots    - a different top-level count shifts every item below it
#                (measured: a duplicated "Add Course" row for ~25ms on Cancel);
#   * children - addBlock hands the new block the OLD block's children, and only
#                the ones our own elements overwrite go away (measured: the
#                row's red "Remove" button inside the open edit form, 247px
#                instead of 193px).
# Verified in the real app 2026-07-30 after the fix: Edit, Cancel and Add Course
# each move the list through exactly ONE state, with no intermediate frame.

def test_inline_form_occupies_exactly_one_top_level_slot():
    src = (REPO / "ui" / "sync_dialogs.py").read_text(encoding="utf-8")
    fn = _func(src, "render_pending_folder_ui")
    emitting = [s for s in fn.body
                if isinstance(s, ast.With)
                or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                    and isinstance(s.value.func, ast.Attribute)
                    and s.value.func.attr not in ("get", "pop"))]
    assert len(emitting) == 1, (
        "render_pending_folder_ui must emit exactly ONE top-level element (the "
        f"bordered container) so it occupies the same slot a list row does; "
        f"found {len(emitting)} at lines {[s.lineno for s in emitting]}")


def _pad_calls(fn):
    """Every pad_slot_children(...) call directly inside *fn*'s last container."""
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "pad_slot_children":
            out.append(n)
    return out


def test_inline_form_is_padded_to_the_row_column_count():
    """The form pads itself out to the child count of the row it replaces."""
    form_src = (REPO / "ui" / "sync_dialogs.py").read_text(encoding="utf-8")
    fn = _func(form_src, "render_pending_folder_ui")
    container = fn.body[-1]
    assert isinstance(container, ast.With)
    last = container.body[-1]
    assert (isinstance(last, ast.Expr) and isinstance(last.value, ast.Call)
            and isinstance(last.value.func, ast.Name)
            and last.value.func.id == "pad_slot_children"), (
        "the inline add/edit form must END with pad_slot_children(): it pads the "
        "form out to the child count of the sync-list row it replaces, so no "
        "inherited column survives inside it")


def test_add_course_row_is_padded_too():
    """Both Add Course rows must match the form, or cancelling leaves its tail.

    Measured before this: the form's "Cancel" and "Confirm and Add" buttons sat
    under the restored Add Course row for 22ms, the slot 112px instead of 48px.
    """
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    fn = _func(src, "_sync_pairs_section")
    pads = _pad_calls(fn)
    assert len(pads) >= 2, (
        f"expected both Add Course branches (empty list + populated list) to "
        f"call pad_slot_children(); found {len(pads)}")
    # each is wrapped in the slot container so it occupies ONE slot like a row
    assert "sync_add_row_slot" in src, (
        "the Add Course row must sit in its own container so it presents one "
        "slot with a full set of children, like the form that replaces it")


def test_slot_child_constant_is_the_row_column_count():
    from shared.components import SYNC_LIST_SLOT_CHILDREN
    assert SYNC_LIST_SLOT_CHILDREN == 5, (
        "the sync list's rows are st.columns([5, 1.5, 1.1, 1.5, 1.2]) - five "
        "children. Change one and the other must change with it.")


def test_sync_row_column_count_is_still_five():
    """If this row gains a column, the form's padding must grow with it."""
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    fn = _func(src, "_sync_pairs_section")
    widths = None
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "columns" and node.args
                and isinstance(node.args[0], ast.List)
                and len(node.args[0].elts) == 5):
            vals = [getattr(e, "value", None) for e in node.args[0].elts]
            if vals == [5, 1.5, 1.1, 1.5, 1.2]:
                widths = vals
                break
    assert widths is not None, (
        "the 5-column sync-list row was not found. If its column count changed, "
        "ui/sync_dialogs.py:render_pending_folder_ui must be padded to match - "
        "see the comment on its trailing st.empty()")


def test_rule9_is_interprocedural_on_the_dialog_side():
    """The real index must know a helper can open a dialog.

    This is the property whose absence shipped the second bug: the first Rule 9
    only recognised a dialog when the @st.dialog function was named in the same
    function, so sync_ui.py passed clean while holding a live instance.
    """
    openers, _ = va._project_index()

    decorated: set[str] = set()
    funcs: dict[str, list] = {}
    for path in va.collect_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.setdefault(n.name, []).append(n)
                if any(va._is_st_dialog_decorator(d) for d in n.decorator_list):
                    decorated.add(n.name)

    direct_callers = {
        name for name, defs in funcs.items()
        if name not in decorated
        and any(isinstance(c, ast.Call) and va._called_name(c) in decorated
                for fn in defs for c in ast.walk(fn))
    }

    assert decorated, "no @st.dialog functions found - the scan is broken"
    assert decorated <= openers, "every @st.dialog name must be an opener"

    # Asserted as a PROPERTY, not against named functions: the fixes in this
    # change deliberately removed _sync_pairs_section and render_pending_folder_ui
    # from the opener set, so naming them here would rot immediately.
    transitive = openers - decorated - direct_callers
    assert transitive, (
        "openers is not transitive - no function reaches a dialog at 2+ hops, so "
        "a dialog opened by a helper would go unseen, which is exactly the gap "
        "that let the Analyze / Quick Sync stylesheet keep being destroyed")


def test_download_settings_opens_its_dialogs_last():
    src = (REPO / "ui" / "download_settings.py").read_text(encoding="utf-8")
    fn = _func(src, "render_download_settings")
    dialogs = _dialog_call_lines(src, "render_download_settings",
                                 {"_save_config_dialog", "_presets_hub_dialog"})
    assert len(dialogs) == 2, "expected both header dialogs to be invoked"
    style_writes = [n.lineno for n in va._own_nodes(fn)
                    if isinstance(n, ast.Call) and va._is_style_only_html_call(n)]
    assert style_writes, "expected style-only st.html() calls on this page"
    assert min(dialogs) > max(style_writes), (
        "both header dialogs must be invoked after every style-only st.html()"
    )


# ---------------------------------------------------------------------------
# Rule 9 - both directions
# ---------------------------------------------------------------------------

# (openers, writers). BOTH are transitive in the real index: `opens_a_dialog`
# stands for a helper that reaches a @st.dialog function without being one.
# That half was missing in the first version of the rule and it let a real
# instance through - see test_rule9_is_interprocedural_on_the_dialog_side.
_INDEX = ({"my_dialog", "opens_a_dialog"}, {"emits_css"})

RULE9_MUST_FLAG = [
    ("style-only st.html after a dialog call",
     "def page():\n"
     "    if b:\n"
     "        my_dialog()\n"
     "    st.html('<style>.a{}</style>')"),
    ("the write is inside a helper (the exact reported shape)",
     "def page():\n"
     "    my_dialog()\n"
     "    emits_css()"),
    # The gap that shipped the second bug: the page never names a dialog, it
    # calls a helper that opens one. sync_ui.render_sync_step1 ->
    # _sync_pairs_section -> _save_pair_dialog.
    ("the DIALOG is opened by a helper, not named here",
     "def page():\n"
     "    opens_a_dialog()\n"
     "    st.html('<style>.a{}</style>')"),
    ("helper opens a dialog AND a helper emits the css",
     "def page():\n"
     "    opens_a_dialog()\n"
     "    emits_css()"),
    ("f-string body still counts - interpolation lands inside the style tag",
     "def page():\n"
     "    my_dialog()\n"
     "    st.html(f'<style>.a{{color:{c}}}</style>')"),
    ("a leading HTML comment does not make the body non-style-only",
     "def page():\n"
     "    my_dialog()\n"
     "    st.html('<!-- note --><style>.a{}</style>')"),
]

RULE9_MUST_NOT_FLAG = [
    ("stylesheet emitted BEFORE the dialog opens",
     "def page():\n"
     "    st.html('<style>.a{}</style>')\n"
     "    my_dialog()"),
    ("no dialog on the page at all",
     "def page():\n"
     "    st.html('<style>.a{}</style>')"),
    # A toast is the CAUSE of the rewind, never a casualty worth reporting: it
    # is transient, already displayed, and only written on a full-rerun frame.
    ("a toast after the dialog is not a victim",
     "def page():\n"
     "    my_dialog()\n"
     "    st.toast('done')"),
    # st.html with real content goes to the MAIN container, not the event one.
    ("st.html carrying content is not an event-container write",
     "def page():\n"
     "    my_dialog()\n"
     "    st.html('<div>hi</div>')"),
    # inject_css() uses st.markdown -> MAIN container, immune by construction.
    ("st.markdown(<style>) is immune",
     "def page():\n"
     "    my_dialog()\n"
     "    st.markdown('<style>.a{}</style>', unsafe_allow_html=True)"),
    # Inside the dialog the writes are the cause; flagging them would be noise.
    # The guard reads the DECORATOR, not the opener set - because openers are
    # transitive, so a name-set test would skip every page function that reaches
    # a dialog, i.e. exactly the ones the rule exists to check.
    ("writes inside the dialog body itself",
     "@st.dialog('x')\n"
     "def my_dialog():\n"
     "    my_dialog()\n"
     "    st.html('<style>.a{}</style>')"),
]


@pytest.mark.parametrize("label,src", RULE9_MUST_FLAG, ids=[c[0] for c in RULE9_MUST_FLAG])
def test_rule9_flags(label, src):
    found = va.check_event_writes_after_dialog(ast.parse(src), _FAKE, set(), index=_INDEX)
    assert found, f"Rule 9 stopped catching: {label}"


@pytest.mark.parametrize("label,src", RULE9_MUST_NOT_FLAG,
                         ids=[c[0] for c in RULE9_MUST_NOT_FLAG])
def test_rule9_does_not_flag(label, src):
    found = va.check_event_writes_after_dialog(ast.parse(src), _FAKE, set(), index=_INDEX)
    assert not found, f"Rule 9 false positive: {label} -> {[v.message for v in found]}"


def test_rule9_is_clean_across_the_repo():
    """The gate is only a gate while it passes."""
    offenders = []
    for path in va.collect_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        suppressed = va.build_suppressed_lines(lines)
        offenders += [v for v in va.check_event_writes_after_dialog(tree, path, suppressed)
                      if not v.suppressed]
    assert offenders == [], "\n".join(
        f"{v.filepath}:{v.lineno} {v.message}" for v in offenders)
