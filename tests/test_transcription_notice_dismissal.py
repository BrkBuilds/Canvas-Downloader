"""The transcription-setup notice: dismissible on the sync list, nowhere else.

Reported by the product owner 2026-08-19 against the real sync page: the amber
"Transcripts & Subtitles need a one-time setup" card re-renders on EVERY render
of that page, for ever, and nothing could close it. That is correct as far as it
goes - the card reports a STANDING mismatch (this folder's stored
``panopto_contract`` asks for txt/srt and the next sync will silently not
produce them) - but all three ways out of it are heavy: install a model, switch
Panopto off globally, or re-download the whole course with the outputs unticked.
A folder's ``panopto_contract`` is written by the download flow (``app.py``) and
seeded on first sync; every other reader of it (the hub, the sync dialogs, the
config viewer) only READS. So there was no proportionate answer at all.

The fix is the Full Disk Access nudge's shape, not a plain close: dismissing
collapses the card to a one-line link that is ALWAYS present, so the fact is
never hidden - only stopped from leading. Three properties carry that, and each
one is a defect if it drifts:

1. **Only the sync list opts in.** The sync REVIEW notice is an event report
   about the run in front of you ("N pending recordings are set to produce
   Transcript or Subtitle files"), seen once per analysis at the last checkpoint
   before the run starts. It must keep the full card whatever the stored flag
   says - same rule as the Today off-list footnote not being gated behind Show
   help text: operational state is not help text.

2. **Both branches emit the same number of children.** They render at the same
   index in the parent, and ``AppRoot.addBlock`` hands a new block the CHILDREN
   of whatever block already sat there - so the shorter branch would leave the
   other's tail on screen inside itself until the run finished.

3. **The stylesheet is STATIC.** It used to be an inline ``st.html(<style>)``
   inside the function, i.e. emitted only in the branch where the notice
   renders. Style hosts are reconciled BY INDEX, and this notice now has a
   branch that flips on a click, mid-session - which is exactly the
   conditional-stylesheet bug this repo already documents.

Verified in the REAL app (isolated ``CANVAS_DL_CONFIG_DIR``, the operator's own
sync pair, 2026-08-19): card 864x128 -> link 864x19 -> re-spawned card 864x128,
2 children in every state, 0 stException, 0 page errors, and the dismissal
survived a full page reload.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

COMPONENTS_SRC = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
SYNC_UI_SRC = (REPO / "sync_ui.py").read_text(encoding="utf-8")
REVIEW_SRC = (REPO / "ui" / "sync_review.py").read_text(encoding="utf-8")
GLOBAL_CSS = (REPO / "styles" / "global.css").read_text(encoding="utf-8")


# ── a recorder that stands in for `st` ──────────────────────────────────────
# The REAL renderer is driven; only Streamlit is fake. It records the container
# tree, so "how many children does this branch emit" is answerable, which is the
# whole point of property 2 above.

class _Ctx:
    def __init__(self, rec, node):
        self._rec, self._node = rec, node

    def __enter__(self):
        self._rec.stack.append(self._node)
        return self

    def __exit__(self, *exc):
        self._rec.stack.pop()
        return False


class FakeSt:
    def __init__(self):
        self.session_state = {}
        self.root = {"key": None, "children": []}
        self.stack = [self.root]
        self.buttons = []          # (label, key, has_on_click, help)
        self.html_calls = []
        self.markdowns = []
        self.reruns = 0

    # -- tree helpers --
    def _add(self, kind, key=None):
        node = {"kind": kind, "key": key, "children": []}
        self.stack[-1]["children"].append(node)
        return node

    def container(self, *a, key=None, **kw):
        return _Ctx(self, self._add("container", key))

    def columns(self, spec, **kw):
        row = self._add("columns")
        n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return tuple(_Ctx(self, {"kind": "col", "key": None, "children": row["children"]})
                     for _ in range(n))

    # -- widgets --
    def button(self, label, key=None, on_click=None, help=None, **kw):
        self._add("button", key)
        self.buttons.append((label, key, on_click is not None, help))
        return False

    def markdown(self, body, **kw):
        self._add("markdown")
        self.markdowns.append(body)

    def html(self, body, **kw):
        self._add("html")
        self.html_calls.append(body)

    def empty(self):
        self._add("empty")

    def rerun(self, **kw):
        self.reruns += 1


def _find(node, key_prefix):
    """Depth-first search for the first container whose key starts with *prefix*."""
    for child in node["children"]:
        if child["key"] and child["key"].startswith(key_prefix):
            return child
        hit = _find(child, key_prefix)
        if hit:
            return hit
    return None


@pytest.fixture()
def render(monkeypatch, tmp_path):
    """Drive the real renderer with a fake ``st`` and a not-ready engine."""
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    import shared.components as components
    import panopto.models as pmodels

    monkeypatch.setattr(pmodels, "transcription_status", lambda: {
        "ready": False, "engine_available": True, "model_id": "small",
        "any_installed": False, "reason": "no transcription model is downloaded yet",
    })

    def _run(**kwargs):
        fake = FakeSt()
        monkeypatch.setattr(components, "st", fake)
        rendered = components.render_transcription_setup_notice(
            kwargs.pop("wants_transcription", True),
            key=kwargs.pop("key", "sync_list_setup_tx"),
            **kwargs)
        return fake, rendered

    return _run


# ── 1. only the sync list opts in ───────────────────────────────────────────

def test_the_sync_list_call_site_is_the_only_one_that_opts_in():
    """Matched on the CALL, per file, so a stray keyword cannot pass by name."""
    def _dismissible_args(src):
        out = []
        for n in ast.walk(ast.parse(src)):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id.endswith("render_transcription_setup_notice")):
                kw = {k.arg: k.value for k in n.keywords}
                out.append(kw.get("dismissible"))
        return out

    sync_list = _dismissible_args(SYNC_UI_SRC)
    assert sync_list, "sync_ui.py no longer renders the notice"
    assert all(isinstance(v, ast.Constant) and v.value is True for v in sync_list), (
        "the sync LIST notice must pass dismissible=True - it is the standing "
        "mismatch that re-states itself on every render of that page")

    review = _dismissible_args(REVIEW_SRC)
    assert review, "ui/sync_review.py no longer renders the notice"
    assert all(v is None for v in review), (
        "the sync REVIEW notice must NOT be dismissible: it is an event report "
        "about the run in front of you, at the last checkpoint before it starts")


def test_a_non_dismissible_caller_ignores_a_stored_dismissal(render, monkeypatch):
    """The review screen must render the full card even after the user has
    collapsed the sync-list one. This is the half that a shared flag makes easy
    to get wrong, and it is the half that matters: hiding it there hides the
    last warning before a run that will not produce what was asked for."""
    import panopto.settings as ps
    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda: True)

    fake, rendered = render(key="sync_review_setup_tx", context_note="2 pending recordings.")
    assert rendered is True
    assert _find(fake.root, "tx_setup_card_") is not None
    assert _find(fake.root, "tx_setup_link_") is None
    assert not any(k and k.startswith("tx_setup_close_") for _, k, _, _ in fake.buttons), (
        "a non-dismissible notice must not render a close button")


def test_a_dismissible_caller_collapses_once_dismissed(render, monkeypatch):
    import panopto.settings as ps
    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda: True)

    fake, rendered = render(dismissible=True)
    assert rendered is True, "collapsing must still RENDER - the fact is never hidden"
    assert _find(fake.root, "tx_setup_link_") is not None
    assert _find(fake.root, "tx_setup_card_") is None

    label = next(lbl for lbl, k, _, _ in fake.buttons
                 if k and k.startswith("tx_setup_relink_"))
    assert "Transcripts" in label and "Subtitles" in label, (
        "the collapsed link must still STATE the mismatch - it is the only thing "
        f"left on screen saying so, got {label!r}")


def test_a_dismissible_caller_shows_the_card_until_it_is_dismissed(render, monkeypatch):
    import panopto.settings as ps
    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda: False)
    fake, _ = render(dismissible=True)
    assert _find(fake.root, "tx_setup_card_") is not None
    assert _find(fake.root, "tx_setup_link_") is None


def test_the_session_respawn_flag_beats_the_stored_dismissal(render, monkeypatch):
    """Clicking the link brings the card back for this session without undoing
    the persisted preference."""
    import shared.components as components
    import panopto.settings as ps
    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda: True)

    fake = FakeSt()
    fake.session_state["tx_setup_card_open"] = True
    monkeypatch.setattr(components, "st", fake)
    components.render_transcription_setup_notice(
        True, key="sync_list_setup_tx", dismissible=True)
    assert _find(fake.root, "tx_setup_card_") is not None


def test_an_unreadable_settings_store_collapses_rather_than_nags(render, monkeypatch):
    """It must never turn a broken config file into a card the user cannot
    close. The link still states the fact, so nothing is lost."""
    import panopto.settings as ps

    def _boom():
        raise OSError("config dir offline")

    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", _boom)
    fake, rendered = render(dismissible=True)
    assert rendered is True
    assert _find(fake.root, "tx_setup_link_") is not None


# ── 2. both branches emit the same number of children ───────────────────────

def test_both_branches_emit_the_same_child_count(render, monkeypatch):
    """``AppRoot.addBlock`` hands a new block the CHILDREN of whatever block sat
    at its index, and only the children the new one overwrites go away. The
    shorter branch would therefore render the other's tail INSIDE itself until
    the script run finished."""
    import panopto.settings as ps
    from shared.components import _TX_NOTICE_SLOT_CHILDREN

    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda: False)
    card_fake, _ = render(dismissible=True)
    card = _find(card_fake.root, "tx_setup_card_")

    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda: True)
    link_fake, _ = render(dismissible=True)
    link = _find(link_fake.root, "tx_setup_link_")

    assert len(card["children"]) == _TX_NOTICE_SLOT_CHILDREN
    assert len(link["children"]) == _TX_NOTICE_SLOT_CHILDREN
    assert len(card["children"]) == len(link["children"])


def test_the_padded_slot_has_gap_zero_in_the_css():
    """A blank child is a zero-HEIGHT element container, not a zero-COST one -
    the container's own flex gap still applies to it."""
    idx = GLOBAL_CSS.index('div[class*="st-key-tx_setup_link_"]')
    rule = GLOBAL_CSS[idx:GLOBAL_CSS.index("}", idx)]
    assert "gap: 0" in rule, (
        "the collapsed slot is padded with a blank child to match the card's "
        "child count, so it must set gap: 0 or it gains a phantom gap")


def test_the_non_dismissible_card_has_the_same_shape_as_the_dismissible_one(render, monkeypatch):
    """Both callers render at an index of their own, but keeping the two card
    variants identical means neither can inherit the other's leftovers either."""
    import panopto.settings as ps
    from shared.components import _TX_NOTICE_SLOT_CHILDREN
    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda: False)

    plain, _ = render(key="sync_review_setup_tx")
    withclose, _ = render(key="sync_list_setup_tx", dismissible=True)
    assert (len(_find(plain.root, "tx_setup_card_")["children"])
            == len(_find(withclose.root, "tx_setup_card_")["children"])
            == _TX_NOTICE_SLOT_CHILDREN)


# ── 3. the stylesheet is static ─────────────────────────────────────────────

def test_the_renderer_emits_no_stylesheet_of_its_own(render, monkeypatch):
    """A style block emitted in only one branch shifts every LATER stylesheet on
    the page onto its neighbour's host, because Streamlit reconciles style hosts
    by INDEX - and this notice's branch now flips on a click."""
    import panopto.settings as ps
    for dismissed in (False, True):
        monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda d=dismissed: d)
        fake, _ = render(dismissible=True)
        assert fake.html_calls == [], (
            "render_transcription_setup_notice must not inject CSS - it lives in "
            "styles/global.css, which inject_css() puts in the MAIN container")
        assert not any("<style" in m for m in fake.markdowns), (
            "no stylesheet may ride along in a content markdown either")


def _selectors(css: str) -> set[str]:
    """Every selector in the sheet, comments stripped, one per comma."""
    import re
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = set()
    for block in css.split("}"):
        head = block.split("{")[0]
        if "{" not in block:
            continue
        for sel in head.split(","):
            sel = " ".join(sel.split())
            if sel:
                out.add(sel)
    return out


#: The five rules that make the notice look like itself. Each is the BASE paint
#: for one element - stated exactly, not as a substring, because the sheet also
#: carries :hover / ::before / descendant rules for the same prefixes. A
#: substring test passes while the base rule alone has been renamed out from
#: under the markup, which is a fully unstyled element and a live mutant that
#: escaped the first version of this test.
_BASE_RULES = [
    ("tx_setup_card_", 'div[class*="st-key-tx_setup_card_"]'),
    ("tx_setup_btn_", 'div[class*="st-key-tx_setup_btn_"] button'),
    ("tx_setup_close_", 'div[class*="st-key-tx_setup_close_"] button'),
    ("tx_setup_link_", 'div[class*="st-key-tx_setup_link_"]'),
    ("tx_setup_relink_", 'div[class*="st-key-tx_setup_relink_"] button'),
]


@pytest.mark.parametrize("prefix,selector", _BASE_RULES)
def test_every_key_the_markup_uses_is_styled_in_global_css(prefix, selector):
    """The markup and its CSS now live in different files, so the coupling needs
    an assertion or a renamed key is a silent loss of styling."""
    assert f'"{prefix}' in COMPONENTS_SRC, (
        f"{prefix} is no longer produced by shared/components.py")
    assert selector in _selectors(GLOBAL_CSS), (
        f"styles/global.css has no `{selector}` rule - that element renders "
        f"with no paint at all")


def test_no_key_is_styled_that_the_markup_never_produces():
    """The other direction: a rule left behind after a rename is dead weight
    that reads as coverage."""
    import re
    styled = {m.group(1) for s in _selectors(GLOBAL_CSS)
              for m in re.finditer(r"st-key-(tx_setup_[a-z]+_)", s)}
    assert styled == {p for p, _ in _BASE_RULES}, (
        f"styles/global.css styles {styled}, the markup produces "
        f"{ {p for p, _ in _BASE_RULES} }")


# ── 4. the toggles are callbacks ────────────────────────────────────────────

def test_dismiss_and_respawn_are_on_click_callbacks(render, monkeypatch):
    """``if st.button(): ...; st.rerun()`` renders the page twice and the browser
    drops its scroll anchor. This control sits directly above the Analyze /
    Quick Sync buttons on a long page."""
    import panopto.settings as ps

    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda: False)
    fake, _ = render(dismissible=True)
    close = next(b for b in fake.buttons if b[1].startswith("tx_setup_close_"))
    assert close[2], "the close button must use on_click="
    assert close[3] is None, (
        "no help= on the close button: it wraps the button in a "
        "stTooltipHoverTarget, which breaks the fixed 32px sizing")
    assert fake.reruns == 0

    monkeypatch.setattr(ps, "is_tx_setup_notice_dismissed", lambda: True)
    fake, _ = render(dismissible=True)
    relink = next(b for b in fake.buttons if b[1].startswith("tx_setup_relink_"))
    assert relink[2], "the re-spawn link must use on_click="
    assert fake.reruns == 0


def test_dismissing_clears_the_session_respawn_flag(monkeypatch, tmp_path):
    """Otherwise a dismissal made from a re-spawned card would not take effect
    until the next page load."""
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    import shared.components as components

    fake = FakeSt()
    fake.session_state["tx_setup_card_open"] = True
    monkeypatch.setattr(components, "st", fake)
    components._dismiss_tx_setup_notice()

    assert "tx_setup_card_open" not in fake.session_state
    from panopto.settings import is_tx_setup_notice_dismissed
    assert is_tx_setup_notice_dismissed() is True


# ── 5. the readiness gates still come first ─────────────────────────────────

def test_a_ready_engine_renders_nothing_however_dismissible(render, monkeypatch):
    import panopto.models as pmodels
    monkeypatch.setattr(pmodels, "transcription_status", lambda: {
        "ready": True, "engine_available": True, "model_id": "small",
        "any_installed": True, "reason": "",
    })
    fake, rendered = render(dismissible=True)
    assert rendered is False and fake.root["children"] == []


def test_a_caller_that_wants_no_transcription_renders_nothing(render):
    fake, rendered = render(wants_transcription=False, dismissible=True)
    assert rendered is False and fake.root["children"] == []


# ── 6. the persisted flag ───────────────────────────────────────────────────

def test_the_flag_defaults_to_not_dismissed(monkeypatch, tmp_path):
    """The first time a folder is configured for transcripts with no model, the
    full card is the right thing to show."""
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    from panopto.settings import is_tx_setup_notice_dismissed
    assert is_tx_setup_notice_dismissed() is False


def test_setting_the_flag_preserves_every_other_owner_of_the_file(monkeypatch, tmp_path):
    """It is a TOP-LEVEL key in a file four modules co-own."""
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    cfg = tmp_path / "canvas_downloader_settings.json"
    before = {
        "canvas_url": "https://cbscanvas.instructure.com",
        "panopto_notice_ack_version": 2,
        "panopto_globally_enabled": True,
        "panopto": {"model": "medium"},
        "show_help_text": True,
    }
    cfg.write_text(json.dumps(before), encoding="utf-8")

    from panopto.settings import (is_tx_setup_notice_dismissed,
                                  set_tx_setup_notice_dismissed)
    assert set_tx_setup_notice_dismissed(True) is True
    after = json.loads(cfg.read_text(encoding="utf-8"))
    for k, v in before.items():
        assert after[k] == v, f"setting the dismissal lost {k!r}"
    assert is_tx_setup_notice_dismissed() is True


def test_the_flag_never_reaches_the_per_run_contract_schema():
    """PANOPTO_DEFAULTS is the schema for a per-run CONTRACT - save_settings
    sanitises to exactly its keys and every synced folder's manifest stores a
    copy. A standing preference about the USER in there would be persisted into
    every folder the app has ever touched."""
    from panopto.settings import PANOPTO_DEFAULTS, TX_NOTICE_DISMISSED_KEY
    assert TX_NOTICE_DISMISSED_KEY not in PANOPTO_DEFAULTS


def test_the_dismissal_is_not_confused_with_the_global_switch():
    from panopto.settings import GLOBAL_ENABLED_KEY, TX_NOTICE_DISMISSED_KEY
    assert TX_NOTICE_DISMISSED_KEY != GLOBAL_ENABLED_KEY
