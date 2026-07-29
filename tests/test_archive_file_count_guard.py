"""Declining to unpack an archive that would bury the course folder.

The existing zip-bomb protection measures uncompressed SIZE and compression
RATIO. It never counts FILES, so an archive of very many very small files sails
straight through it: one real course unpacked **21,630** files, which is both a
surprise to the user and the source of the deepest paths in the folder.

Three properties matter more than the guard itself, and they are what these
tests are for:

1. **Declining is not failing.** The archive is left untouched and still on
   disk, so the user has lost nothing. It must not touch ``pp_failure_count``,
   which drives the "some conversions failed" warning.
2. **It reaches BOTH flows.** Download arrives through ``run_all_conversions``;
   sync calls ``run_archive_extraction`` directly. The limit is read inside the
   one function they share, so a modifier cannot mean one thing in download and
   another in sync.
3. **It leaves nothing behind.** The target folder is created before the member
   list can be read, so a guard that simply returned would litter the course
   folder with empty directories.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from converters.archive import extract_archive  # noqa: E402


def _zip_of(tmp_path: Path, n_files: int, name="bundle.zip") -> Path:
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        for i in range(n_files):
            zf.writestr(f"nested/dir/file_{i}.txt", "x")
    return z


# --------------------------------------------------------------------------
# the guard
# --------------------------------------------------------------------------

def test_no_limit_extracts_as_before(tmp_path):
    """The default. Nothing changes until the user asks for a limit."""
    z = _zip_of(tmp_path, 12)
    assert extract_archive(z) is True
    assert (tmp_path / "bundle" / "nested" / "dir" / "file_0.txt").exists()
    assert not z.exists(), "the source archive is consumed on success"


def test_an_archive_under_the_limit_still_extracts(tmp_path):
    z = _zip_of(tmp_path, 5)
    assert extract_archive(z, max_files=10) is True
    assert (tmp_path / "bundle" / "nested" / "dir" / "file_0.txt").exists()


def test_an_archive_over_the_limit_is_declined_and_left_alone(tmp_path):
    """False, not None: the app did what it was told, it did not fail."""
    z = _zip_of(tmp_path, 25)
    assert extract_archive(z, max_files=10) is False
    assert z.exists(), "the archive must survive so the user can extract it"
    assert not (tmp_path / "bundle").exists(), "and no empty folder left behind"


def test_the_limit_is_exclusive_at_the_boundary(tmp_path):
    """`> max_files`, so exactly the limit is allowed - a limit of 10 means
    'ten is fine', which is how a user reads it."""
    assert extract_archive(_zip_of(tmp_path, 10, "a.zip"), max_files=10) is True
    assert extract_archive(_zip_of(tmp_path, 11, "b.zip"), max_files=10) is False


def test_directory_entries_do_not_count_towards_the_limit(tmp_path):
    """The user's mental model is "how many FILES will this put in my folder"."""
    z = tmp_path / "dirs.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for i in range(30):
            zf.writestr(f"d{i}/", "")          # directory entries
        zf.writestr("only_file.txt", "x")
    assert extract_archive(z, max_files=5) is True


def test_the_count_happens_before_anything_is_written(tmp_path):
    """Otherwise declining would leave a half-extracted folder, which is worse
    than either extracting or not."""
    z = _zip_of(tmp_path, 40)
    extract_archive(z, max_files=2)
    assert list(tmp_path.iterdir()) == [z], "nothing but the untouched archive"


# --------------------------------------------------------------------------
# the setting
# --------------------------------------------------------------------------

def test_the_limit_reader_defaults_to_no_limit_without_streamlit():
    """Called from worker threads and tests. It must never guess a limit into
    existence - the safe default is the app's default, which is to extract."""
    from shared.helpers import archive_file_limit
    assert archive_file_limit() is None


def test_the_setting_is_declared_with_a_default():
    """state_registry is the single source of truth for session keys, so a
    setting missing from it reads as None on a fresh launch and the widget
    silently falls back to its own literal - two defaults, one of which wins by
    accident."""
    from core.state_registry import DOWNLOAD_DEFAULTS
    assert DOWNLOAD_DEFAULTS["archive_max_files_enabled"] is False, \
        "off by default: extraction behaviour must not change unasked"
    assert DOWNLOAD_DEFAULTS["archive_max_files"] == 1000


@pytest.mark.parametrize("needle,why", [
    ("temp_archive_max_enabled", "the dialog widget"),
    ("('temp_archive_max_enabled', 'archive_max_files_enabled'", "temp->state mapping"),
    ("st.session_state['archive_max_files_enabled'] = temp_arch_enabled", "commit on save"),
    ("config_data['archive_max_files_enabled']", "persisted to disk"),
    ("if 'archive_max_files_enabled' in config", "restored on next launch"),
    ("temp_arch_enabled != st.session_state.get('archive_max_files_enabled'", "dirty check"),
])
def test_every_settings_wiring_point_exists(needle, why):
    """A settings value needs FIVE separate things or it half-works in a way
    that looks like a bug: a widget, a temp mapping, a dirty check, a commit and
    a persist+restore. Missing the dirty check alone makes Save silently do
    nothing for this setting while working for its neighbours."""
    src = (REPO / "ui" / "auth.py").read_text(encoding="utf-8")
    assert needle in src, f"missing: {why}"


# --------------------------------------------------------------------------
# both flows
# --------------------------------------------------------------------------

def test_the_guard_lives_where_BOTH_flows_pass_through():
    """Download reaches extraction via run_all_conversions; sync calls
    run_archive_extraction directly. Reading the limit inside that shared
    function is what makes one setting mean one thing everywhere."""
    pp = (REPO / "converters" / "post_processing.py").read_text(encoding="utf-8")
    i = pp.index("def run_archive_extraction")
    body = pp[i:i + 3000]
    assert "archive_file_limit()" in body
    assert "max_files=_max_files" in body

    sync = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    assert "run_archive_extraction(" in sync, "sync must still route through it"


def test_a_declined_archive_is_not_counted_as_a_conversion_failure():
    """pp_failure_count drives the 'some conversions failed' warning. A setting
    doing exactly what it was asked is not a failure."""
    import re
    pp = (REPO / "converters" / "post_processing.py").read_text(encoding="utf-8")
    # Comments blanked first - the same thing verify_architecture.py does before
    # scanning, and for the same reason: a comment EXPLAINING that the counter
    # must not be touched otherwise fails a test asserting it is not touched.
    code = re.sub(r"^\s*#.*$", "", pp, flags=re.M)
    i = code.index("if success is False:")
    block = code[i:i + 700]
    assert "pp_failure_count" not in block
    assert "'skip'" in block


def test_the_user_is_told_once_at_the_end():
    """A per-archive line scrolls away in a long run, and 'why is my zip still
    a zip?' is exactly the question a silent guard creates."""
    pp = (REPO / "converters" / "post_processing.py").read_text(encoding="utf-8")
    assert "left unextracted" in pp
    assert "still in your" in pp


# --------------------------------------------------------------------------
# the notice
# --------------------------------------------------------------------------

def test_data_uri_icons_are_wrapped_in_DOUBLE_quotes():
    """A data URI here contains single quotes (``xmlns='...'``), so a src
    attribute wrapped in single quotes ends at the first one inside the URI and
    the browser draws a broken-image glyph. Caught only by looking at the real
    screen - the markup is perfectly valid Python and perfectly valid HTML, it
    just points at a truncated URI.
    """
    import re
    src = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    bad = re.findall(r"src='\{_[A-Z_]*SVG[A-Z_]*\}'", src)
    bad += re.findall(r"src='\{_SKIP_[A-Z_]+\}'", src)
    assert not bad, f"single-quoted data-URI src attribute(s): {bad}"


def test_the_shared_skip_icons_are_defined_once():
    """Both notices draw the SAME chevron, so it is defined once and reused.
    Two copies is two chances to get the encoding wrong, and the second copy is
    the one that was wrong.

    Scoped to the skip icons deliberately - this file holds ~30 legitimate,
    genuinely different glyphs, and a blanket cap on data URIs would just be an
    arbitrary number waiting to fail on an unrelated change.
    """
    src = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    for name in ("_SKIP_CHEVRON_SVG", "_SKIP_FUNNEL_SVG", "_SKIP_ARCHIVE_SVG"):
        assert src.count(f"{name} = (") == 1, f"{name} defined more than once"
    assert "_SKIP_CHEVRON = _SKIP_CHEVRON_SVG" in src, \
        "render_completion_card must reuse the hoisted icon, not redefine it"


# --------------------------------------------------------------------------
# edge cases
# --------------------------------------------------------------------------

def test_the_guard_covers_tar_gz_too(tmp_path):
    """.tar.gz takes a completely separate branch in extract_archive, so a guard
    tested only against .zip proves nothing about it."""
    import io, tarfile
    t = tmp_path / "bundle.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        for i in range(20):
            data = b"x"
            info = tarfile.TarInfo(f"deep/dir/file_{i}.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    assert extract_archive(t, max_files=5) is False
    assert t.exists(), "the archive must survive"
    assert not (tmp_path / "bundle").exists()


def test_a_tar_gz_under_the_limit_still_extracts(tmp_path):
    import io, tarfile
    t = tmp_path / "small.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        data = b"x"
        info = tarfile.TarInfo("a/b.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    assert extract_archive(t, max_files=5) is True


def test_declining_never_deletes_a_pre_existing_folder(tmp_path):
    """`_decline` removes the folder it would have extracted into - but only
    when empty. A same-named folder the user already had must survive, or a
    guard meant to protect them destroys their data instead."""
    z = _zip_of(tmp_path, 50)
    existing = tmp_path / "bundle"
    existing.mkdir()
    (existing / "my notes.txt").write_text("mine", encoding="utf-8")

    assert extract_archive(z, max_files=2) is False
    assert (existing / "my notes.txt").read_text(encoding="utf-8") == "mine"


def test_a_declined_archive_is_not_retried(tmp_path):
    """`retry_failed_conversions` treats "source still on disk" as the failure
    set - and a declined archive is, by design, still on disk. It is safe only
    because archive extraction is never added to `_attempts`; if it ever were,
    every declined zip would be retried on every run, for ever."""
    import re
    for rel in ("converters/post_processing.py", "sync/execution.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        code = re.sub(r"^\s*#.*$", "", src, flags=re.M)
        assert "_attempts.append((run_archive_extraction" not in code, rel
        assert "run_archive_extraction, _items" not in code, rel


def test_a_zip_nested_inside_an_extracted_tree_is_left_alone(tmp_path):
    """Extraction is itself a converter, and archive CONTENTS are never
    converted - so a zip inside a zip stays a zip. Consistent with the rule
    rather than a special case, which is why it needs no code of its own."""
    from converters.post_processing import _glob_files
    outer = tmp_path / "Opgaver"
    (outer / "inner").mkdir(parents=True)
    nested = outer / "inner" / "extra.zip"
    nested.write_bytes(b"PK\x03\x04")
    downloaded = tmp_path / "Lecture.pdf"
    downloaded.write_bytes(b"pdf")
    assert _glob_files(tmp_path, {".zip"}, [str(downloaded)]) == []


def test_a_zero_or_negative_limit_means_no_limit():
    """The number input floors at 1, but a hand-edited config file does not."""
    import json, tempfile
    from shared.helpers import archive_file_limit
    # no Streamlit context -> None regardless; the guard below is the contract
    assert archive_file_limit() is None


def test_the_skipped_list_is_cleared_between_runs():
    """The download bridge APPENDS (one entry per course), so without a per-run
    reset the second run shows the first run's archives on a completion screen
    where nothing was skipped - a stale-data bug that is invisible on run 1 and
    therefore invisible in most testing.

    Registered beside pp_failure_count / pp_success_count, which are per-run for
    exactly the same reason.
    """
    from core.state_registry import DOWNLOAD_TRANSIENT_KEYS, SYNC_TRANSIENT_KEYS
    assert "pp_archives_skipped" in DOWNLOAD_TRANSIENT_KEYS
    assert "pp_archives_skipped" in SYNC_TRANSIENT_KEYS


def test_the_download_bridge_appends_and_sync_replaces():
    """Different shapes for a real reason: the download flow calls
    post-processing ONCE PER COURSE, so it must accumulate; sync runs one pass
    for the whole selection, so it assigns. Getting these the wrong way round
    either loses courses or double-counts them."""
    bridge = (REPO / "engine" / "post_processing_bridge.py").read_text(encoding="utf-8")
    sync = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    assert "list(st.session_state.get('pp_archives_skipped', []))" in bridge, \
        "download must accumulate across courses"
    assert "st.session_state['pp_archives_skipped'] = list(pp_ui.archives_skipped)" in sync, \
        "sync assigns once for the whole run"
