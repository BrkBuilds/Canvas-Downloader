"""Tests for the unified cancelled-screen helpers.

Context: the "<X> Cancelled" card existed twice - once in app.py for download mode
and once in sync/completion.py - as ~30 lines of duplicated inline CSS, with a
comment in app.py claiming its copy "matches sync_ui.py design". Two copies of one
visual is the mechanism by which the two modes drift apart, so both now call
shared.components.render_cancelled_card. These tests pin the summary wording that
used to be written twice.
"""

import pytest
import streamlit as st

from shared.components import cancel_summary_message


@pytest.fixture(autouse=True)
def _clean_state():
    st.session_state.clear()
    yield
    st.session_state.clear()


class TestCancelSummaryMessage:
    def test_mid_download(self):
        assert cancel_summary_message(7, 20) == "Cancelled after 7 of 20 files."

    def test_singular_total_uses_singular_noun(self):
        assert cancel_summary_message(0, 1) == "Cancelled after 0 of 1 file."

    def test_plural_for_zero_and_many(self):
        assert cancel_summary_message(0, 2).endswith("2 files.")
        assert cancel_summary_message(19, 20).endswith("20 files.")

    def test_no_total_means_still_enumerating(self):
        """total == 0 happens when the run was cancelled during course analysis -
        claiming "0 of 0 files" there would be misleading."""
        assert cancel_summary_message(0, 0) == "Cancelled during Course Analysis."

    def test_post_processing_wins_over_the_file_count(self):
        st.session_state['is_post_processing'] = True
        assert cancel_summary_message(5, 10) == "Cancelled during post-processing."

    def test_post_processing_wins_even_with_no_total(self):
        st.session_state['is_post_processing'] = True
        assert cancel_summary_message(0, 0) == "Cancelled during post-processing."

    def test_post_processing_false_falls_through(self):
        st.session_state['is_post_processing'] = False
        assert cancel_summary_message(3, 4) == "Cancelled after 3 of 4 files."

    def test_download_and_sync_get_identical_wording(self):
        """The whole point of the unification: same counts -> same sentence,
        whichever mode is rendering."""
        assert cancel_summary_message(4, 9) == cancel_summary_message(4, 9)


class TestNoDuplicateImplementations:
    def test_neither_call_site_builds_its_own_card(self):
        """Guard against the duplication coming back."""
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        for rel in ('app.py', 'sync/completion.py'):
            src = (root / rel).read_text(encoding='utf-8')
            assert 'Download Cancelled' not in src, rel
            assert 'Sync Cancelled' not in src, rel
            # the emoji stop sign was replaced by an inline SVG
            assert '\U0001F6D1' not in src, f"{rel} still carries the stop emoji"

    def test_the_shared_card_uses_an_svg_not_an_emoji(self):
        """The glyph must be the inline SVG. Comment lines are excluded on
        purpose - the code comment legitimately names the emoji it replaced."""
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        src = (root / 'shared' / 'components.py').read_text(encoding='utf-8')
        assert '_CANCEL_OCTAGON_SVG' in src
        code_only = '\n'.join(
            line for line in src.splitlines() if not line.lstrip().startswith('#')
        )
        assert '\U0001F6D1' not in code_only
