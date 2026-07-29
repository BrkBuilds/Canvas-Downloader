"""The step tracker: what each screen claims is happening.

Every case here is a defect the tracker actually shipped:

* the sync flow rendered the ANALYSIS phase and the REVIEW screen both as
  "step 2", so the entire analysis ran under the label "Review Changes";
* Quick Sync advertised a Review step it structurally never visits;
* the download flow's scan phase hid inside "Downloading", so the first ~30s
  of every run named work that had not started;
* the labels are MARKDOWN, and a bare "1. Select Courses" is an ordered-list
  item - Streamlit ate the number and rendered only the label.

The state machine is pure, so it is testable without a browser; the icon test
closes the other half, where a new step renders with no glyph because nobody
added a rule to global.css.
"""

import re
from pathlib import Path

import pytest

from shared.helpers import (
    DOWNLOAD_WIZARD_STEPS, SYNC_WIZARD_STEPS,
    render_download_wizard, render_sync_wizard, render_wizard_step,
)


class _FakeSlot:
    def __init__(self):
        self.buttons = []

    def button(self, label, *, key, disabled, on_click, use_container_width):
        self.buttons.append({'label': label, 'key': key,
                             'disabled': disabled, 'on_click': on_click})


class _FakeContainer:
    """Stands in for ``st``: the wizard only ever calls ``.container(key=)``."""

    def __init__(self):
        self.slot = _FakeSlot()
        self.key = None

    def container(self, key):
        self.key = key
        return self.slot


def render(flow='sync', current='select', **kw):
    c = _FakeContainer()
    steps = SYNC_WIZARD_STEPS if flow == 'sync' else DOWNLOAD_WIZARD_STEPS
    render_wizard_step(c, flow, steps, current, **kw)
    return c


def states(container):
    """[(step id, state)] read back off the widget keys - the same string the
    stylesheet selects on, so a test passing here means the CSS can see it."""
    out = []
    for b in container.slot.buttons:
        m = re.match(r'cd_wiz_\w+?_\d+_(\w+?)_st_(done|active|idle|skipped)_(\w+sep)$',
                     b['key'])
        assert m, f"unparseable key {b['key']!r}"
        out.append((m.group(1), m.group(2)))
    return out


# ── The label is markdown ───────────────────────────────────────────────────

def test_step_number_survives_markdown():
    """`1. Label` is an ordered-list item; the escaped `1\\.` is not."""
    for b in render(current='select').slot.buttons:
        assert re.match(r'^\d+\\\. ', b['label']), b['label']


def test_skipped_label_is_struck_through_but_says_why():
    quick = render(current='sync', skipped=('review',))
    lbl = [b['label'] for b in quick.slot.buttons if 'review' in b['key']][0]
    assert lbl == '3\\. ~~Review Changes~~ (skipped)'


# ── The sync flow ───────────────────────────────────────────────────────────

def test_analysis_and_review_are_different_steps():
    """The bug this whole model exists to kill: they used to share step 2."""
    assert states(render(current='analyze')) == [
        ('select', 'done'), ('analyze', 'active'),
        ('review', 'idle'), ('sync', 'idle'), ('complete', 'idle'),
    ]
    assert states(render(current='review')) == [
        ('select', 'done'), ('analyze', 'done'),
        ('review', 'active'), ('sync', 'idle'), ('complete', 'idle'),
    ]


def test_quick_sync_marks_review_skipped_in_every_later_phase():
    for current in ('analyze', 'sync', 'complete'):
        got = dict(states(render(current=current, skipped=('review',))))
        assert got['review'] == 'skipped', current


def test_step_one_shows_the_whole_flow():
    """The mode is not chosen yet, so nothing is skipped: the tracker states
    what the flow CAN do before it states what this run will do."""
    assert 'skipped' not in dict(states(render(current='select'))).values()


def test_separator_after_a_skipped_step_still_reads_as_progress():
    """The line LEAVING a step tracks progress, not the skip - a skipped step
    the run is already past still joins two completed steps."""
    keys = [b['key'] for b in render(current='sync', skipped=('review',)).slot.buttons]
    assert keys[2].endswith('_donesep'), keys[2]


# ── The download flow ───────────────────────────────────────────────────────

def test_download_scan_is_its_own_step():
    assert states(render(flow='download', current='analyze')) == [
        ('select', 'done'), ('configure', 'done'), ('analyze', 'active'),
        ('download', 'idle'), ('complete', 'idle'),
    ]


def test_configure_download_is_not_called_download_settings():
    assert dict(DOWNLOAD_WIZARD_STEPS)['configure'] == 'Configure Download'


# ── Clickability ────────────────────────────────────────────────────────────

def test_only_a_completed_step_with_a_handler_is_clickable():
    def go():
        pass

    c = render(current='review', nav={'select': go})
    by_id = {re.search(r'_\d+_(\w+?)_st_', b['key']).group(1): b
             for b in c.slot.buttons}
    assert by_id['select']['disabled'] is False
    assert by_id['select']['on_click'] is go
    # Every other step is inert, including the one the page named but which the
    # run has not passed yet.
    for sid in ('analyze', 'review', 'sync', 'complete'):
        assert by_id[sid]['disabled'] is True, sid
        assert by_id[sid]['on_click'] is None, sid


def test_the_current_step_is_never_a_link_to_itself():
    c = render(current='select', nav={'select': lambda: None})
    assert c.slot.buttons[0]['disabled'] is True


def test_a_forward_step_is_never_clickable_even_if_nav_names_it():
    c = render(current='select', nav={'complete': lambda: None})
    assert c.slot.buttons[-1]['disabled'] is True


# ── The stylesheet has to be able to draw it ────────────────────────────────

_GLOBAL_CSS = (Path(__file__).resolve().parents[1] / 'styles' / 'global.css').read_text(encoding='utf-8')


@pytest.mark.parametrize('step_id', sorted(
    {s for s, _ in SYNC_WIZARD_STEPS} | {s for s, _ in DOWNLOAD_WIZARD_STEPS}))
def test_every_step_has_a_glyph_in_global_css(step_id):
    """Adding a step without a mask rule renders a label with an empty box in
    front of it - a silent, CSS-only failure that no Python test would catch."""
    assert f'[class*="_{step_id}_st_"]' in _GLOBAL_CSS


@pytest.mark.parametrize('state', ['done', 'active', 'idle', 'skipped'])
def test_every_state_is_painted(state):
    assert f'[class*="_st_{state}_"]' in _GLOBAL_CSS


def test_the_tracker_opts_out_of_the_disabled_button_paint():
    """Almost every step is `disabled` by design. Left to the app's one disabled
    recipe (brightness .5 saturate .5, further up global.css) the whole tracker
    would read as broken rather than as a row of labels."""
    # Comments first: this block's own comment quotes the recipe it opts out of,
    # braces included, so a naive scan to the next '}' stops inside the prose.
    css = re.sub(r'/\*.*?\*/', '', _GLOBAL_CSS, flags=re.S)
    block = css[css.index('div[class*="st-key-cd_wizard_"] button {'):]
    assert 'filter: none !important;' in block[:block.index('}')]


# ── The public wrappers ─────────────────────────────────────────────────────

def test_sync_wrapper_honours_an_explicit_quick_flag():
    c = _FakeContainer()
    render_sync_wizard(c, 'sync', quick=True)
    assert dict(states(c))['review'] == 'skipped'

    c = _FakeContainer()
    render_sync_wizard(c, 'sync', quick=False)
    assert dict(states(c))['review'] == 'done'


def test_download_wrapper_renders_the_download_flow():
    c = _FakeContainer()
    render_download_wizard(c, 'download')
    assert [s for s, _ in states(c)] == [s for s, _ in DOWNLOAD_WIZARD_STEPS]
    assert c.key == 'cd_wizard_download'
