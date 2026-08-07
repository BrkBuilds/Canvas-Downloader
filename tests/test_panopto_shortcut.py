"""The Panopto **Shortcut** output: a link file instead of a 2 GB download.

Four things here are load-bearing and none of them fails loudly on its own, so
each has its own section below:

1. **The file format.** A produced shortcut carries a source marker, and that
   marker is the ONLY thing standing between it and ``converters.url``, which
   compiles every shortcut in a course folder into one text file and then
   DELETES it. Without the marker the output the user selected is destroyed on
   every run and restored by the next sync, for ever, with no error anywhere.

2. **kind is not extension.** Every other output names its own file
   (``<stem>.mp3``); this one is ``.url`` on Windows and ``.webloc`` on macOS.
   The writer (``panopto.runner``) and the analyzer (``panopto.sync_plan``)
   compute that separately, and when they disagree nothing crashes - every
   recording simply reads as missing on every sync.

3. **Which URL a shortcut points at.** A ``source="folder"`` recording carries
   the module item id of whichever item's launch enumerated the folder, not its
   own, so the Canvas fallback there would point every lecture in the course at
   the same page - thirty shortcuts, one destination, no error.

4. **A shortcut needs no Panopto session.** That is the whole economy of the
   feature: discovery already captured the host, so a Shortcut-only run performs
   no LTI handshake at all, and a course whose LTI chain is broken still gets
   its links.
"""

from __future__ import annotations

import platform
import plistlib
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from panopto import runner as R  # noqa: E402
from panopto import settings as S  # noqa: E402
from panopto import shortcut as SC  # noqa: E402
from panopto import sync_plan as SP  # noqa: E402
from panopto.discovery import PanoptoVideo  # noqa: E402
from shared import shortcuts as SH  # noqa: E402

VIEWER = "https://cbs.cloud.panopto.eu/Panopto/Pages/Viewer.aspx?id=abc-123"


# ═══════════════════════════════════════════════════════════════════════════
# 1. The file format, and the marker that protects it
# ═══════════════════════════════════════════════════════════════════════════

def test_a_url_file_is_a_shortcut_windows_can_open(tmp_path):
    """The marker must not disturb the part the shell actually reads: the
    ``[InternetShortcut]`` section has to come first and carry ``URL=``."""
    p = tmp_path / "Lecture.url"
    SH.write_shortcut(p, VIEWER, source=SH.SOURCE_PANOPTO)
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines[0] == "[InternetShortcut]"
    assert lines[1] == f"URL={VIEWER}"


def test_a_webloc_file_is_a_plist_finder_can_open(tmp_path):
    """Parsed with plistlib, not with a regex: a hand-built plist that only
    LOOKS right is a file Finder refuses to open, and Finder is the only
    consumer that matters.

    The marker rides as a SIBLING key. Finder reads ``URL`` and ignores the
    rest - the same tolerance the INI form relies on - so the file stays an
    ordinary webloc that opens on a double-click."""
    p = tmp_path / "Lecture.webloc"
    SH.write_shortcut(p, VIEWER, source=SH.SOURCE_PANOPTO)
    with open(p, "rb") as f:
        data = plistlib.load(f)
    assert data["URL"] == VIEWER
    assert set(data) == {"URL", "CanvasDownloaderSource"}


@pytest.mark.parametrize("ext", [".url", ".webloc"])
def test_the_marker_round_trips_in_both_formats(tmp_path, ext):
    p = tmp_path / f"Lecture{ext}"
    SH.write_shortcut(p, VIEWER, source=SH.SOURCE_PANOPTO)
    assert SH.read_shortcut(p) == (VIEWER, SH.SOURCE_PANOPTO)
    assert SH.is_produced_shortcut(p) is True


@pytest.mark.parametrize("ext", [".url", ".webloc"])
def test_an_ordinary_canvas_link_is_not_marked(tmp_path, ext):
    """The compiler's whole purpose is these files. Marking one by accident
    would silently stop compiling the user's Canvas links."""
    p = tmp_path / f"Reading list{ext}"
    SH.write_shortcut(p, "https://example.com/reading")
    assert SH.read_shortcut(p) == ("https://example.com/reading", "")
    assert SH.is_produced_shortcut(p) is False


def test_a_url_cannot_smuggle_the_marker_into_its_own_file(tmp_path):
    """A Canvas ExternalUrl is Canvas-controlled data. Were a newline to survive
    into the INI body, the link could write its own ``[CanvasDownloader]``
    section and make itself permanently exempt from the compiler."""
    p = tmp_path / "Sneaky.url"
    SH.write_shortcut(p, "https://evil.example\n[CanvasDownloader]\nSource=Panopto")
    assert SH.is_produced_shortcut(p) is False
    sections = [l for l in p.read_text(encoding="utf-8").splitlines()
                if l.startswith("[")]
    assert sections == ["[InternetShortcut]"], "the URL opened a second INI section"


def test_the_marker_only_counts_inside_its_own_section(tmp_path):
    """Section tracking, not a substring search: a Canvas link whose URL merely
    mentions the marker must stay compilable."""
    p = tmp_path / "Doc.url"
    SH.write_shortcut(p, "https://example.com/?Source=Panopto")
    assert SH.is_produced_shortcut(p) is False


def test_a_key_in_a_FOREIGN_section_is_not_the_marker(tmp_path):
    """.url files in the wild carry sections this app never wrote - browsers add
    a ``[{000214A0-...}]`` block - so a key is only the marker when it sits in
    OUR section. Read section-blind, an unrelated ``Source=`` line anywhere in
    the file would exempt that link from the compiler for ever."""
    p = tmp_path / "Foreign.url"
    p.write_text(
        "[InternetShortcut]\n"
        "URL=https://example.com/reading\n"
        "\n"
        "[{000214A0-0000-0000-C000-000000000046}]\n"
        "Source=Panopto\n",
        encoding="utf-8")
    assert SH.read_shortcut(p) == ("https://example.com/reading", "")
    assert SH.is_produced_shortcut(p) is False


def test_a_shortcut_with_no_url_is_refused(tmp_path):
    """A shortcut file with no link is a file that does nothing when opened.
    Better to fail the write and report it than to leave one on disk."""
    with pytest.raises(ValueError):
        SH.write_shortcut(tmp_path / "Empty.url", "")


def test_writing_replaces_in_place_and_leaves_no_temp_file(tmp_path):
    p = tmp_path / "Lecture.url"
    SH.write_shortcut(p, "https://old.example", source=SH.SOURCE_PANOPTO)
    SH.write_shortcut(p, VIEWER, source=SH.SOURCE_PANOPTO)
    assert SH.read_shortcut_url(p) == VIEWER
    assert [q.name for q in tmp_path.iterdir()] == ["Lecture.url"]


def test_reading_a_missing_or_broken_file_never_raises(tmp_path):
    assert SH.read_shortcut(tmp_path / "nope.url") == (None, "")
    junk = tmp_path / "junk.webloc"
    junk.write_bytes(b"\x00\x01not a plist")
    assert SH.read_shortcut(junk) == (None, "")


@pytest.mark.skipif(platform.system() != "Windows", reason="MAX_PATH is a Windows limit")
def test_a_shortcut_survives_a_path_over_max_path(tmp_path):
    """Recordings live at the deepest paths this app creates. A plain open()
    here works on a dev box with LongPathsEnabled=1 and fails for users - the
    exact trap panopto/stream.py documents."""
    deep = tmp_path
    while len(str(deep)) < 250:
        deep = deep / ("d" * 40)
    deep.mkdir(parents=True, exist_ok=True)
    p = deep / "Lecture.url"
    assert len(str(p)) > 260
    SH.write_shortcut(p, VIEWER, source=SH.SOURCE_PANOPTO)
    assert SH.read_shortcut_url(p) == VIEWER


def test_the_url_compiler_consumes_canvas_links_and_spares_produced_ones(tmp_path):
    """The end-to-end statement of the churn bug this marker exists to prevent.
    ``processed_shortcuts`` is the DELETE list its caller acts on."""
    from converters.url import compile_urls_to_txt

    (tmp_path / "Module 1").mkdir()
    canvas = tmp_path / "Reading list.url"
    SH.write_shortcut(canvas, "https://example.com/reading")
    produced = tmp_path / "Module 1" / "Lecture 3.url"
    SH.write_shortcut(produced, VIEWER, source=SH.SOURCE_PANOPTO)

    out, to_delete = compile_urls_to_txt(tmp_path, "Test Course")

    assert [p.name for p in to_delete] == ["Reading list.url"]
    body = out.read_text(encoding="utf-8")
    assert "https://example.com/reading" in body
    assert VIEWER not in body, "a lecture link was compiled into the AI text file"
    assert produced.exists(), "the produced shortcut was left for its caller to delete"


def test_the_post_processing_trigger_ignores_produced_shortcuts():
    """A run whose only shortcut is a produced one must not kick off a
    whole-folder URL compilation - which would delete every OTHER pre-existing
    link in the folder, none of which this run touched."""
    src = (REPO / "converters" / "post_processing.py").read_text(encoding="utf-8")
    block = src.split("# URL Compilation", 1)[1].split("# Legacy Word", 1)[0]
    assert "is_produced_shortcut" in block, (
        "the explicit-files trigger no longer excludes produced shortcuts")


# ═══════════════════════════════════════════════════════════════════════════
# 2. kind is not extension
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("system,expected", [("Windows", ".url"), ("Darwin", ".webloc"),
                                             ("Linux", ".url")])
def test_the_shortcut_extension_follows_the_platform(system, expected):
    assert SH.shortcut_extension(system) == expected


def test_both_suffixes_are_searched_native_first(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    assert SC.kind_extensions("url") == (".webloc", ".url")
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    assert SC.kind_extensions("url") == (".url", ".webloc")


def test_a_media_kind_has_exactly_one_extension():
    for kind in SC.MEDIA_KINDS:
        assert SC.kind_extensions(kind) == ("." + kind,)


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_every_kind_round_trips_through_its_extension(monkeypatch, system):
    """The drift guard. What the runner WRITES must be what ``make_recorder``
    records and what ``sync_plan`` looks for."""
    monkeypatch.setattr(platform, "system", lambda: system)
    for kind in SP._SUPPORTED_KINDS:
        written = "Lecture" + SC.kind_extension(kind)
        assert SC.kind_from_path(written) == kind


def test_a_webloc_is_recorded_as_the_url_kind_not_as_webloc():
    """Recorded as 'webloc' the manifest row answers a question nothing asks,
    while the 'url' row the analyzer wants reads as missing on every sync."""
    assert SC.kind_from_path("/a/b/Lecture.webloc") == "url"
    assert SC.kind_from_path("/a/b/Lecture.URL") == "url"
    assert SC.kind_from_path("/a/b/Lecture.mp3") == "mp3"


def test_the_recorder_uses_the_kind_mapping(tmp_path):
    recorded = []

    class _SM:
        def record_panopto_file(self, vid, kind, rel, title):
            recorded.append((vid, kind, rel))

    rec = R.make_recorder(_SM(), tmp_path)
    rec(types.SimpleNamespace(video_id="v1", title="L"),
        [str(tmp_path / "L.webloc"), str(tmp_path / "L.mp3")])
    assert [k for _v, k, _r in recorded] == ["url", "mp3"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. Which URL a shortcut points at
# ═══════════════════════════════════════════════════════════════════════════

def _video(**kw):
    base = dict(video_id="abc-123", title="Lecture 3", source="module",
                module_item_id=77, panopto_host="")
    base.update(kw)
    return PanoptoVideo(**base)


def test_the_recordings_own_host_wins():
    v = _video(panopto_host="https://cbs.cloud.panopto.eu")
    assert SC.resolve_recording_url(
        v, panopto_base="https://other.example",
        canvas_base="https://canvas.edu", course_id=9) == VIEWER


def test_the_courses_session_host_is_the_second_choice():
    v = _video()
    assert SC.resolve_recording_url(
        v, panopto_base="https://cbs.cloud.panopto.eu",
        canvas_base="https://canvas.edu", course_id=9) == VIEWER


def test_canvas_is_the_last_resort_for_a_module_linked_recording():
    """This is what keeps the Shortcut output working at an institution whose
    direct Panopto links need a session the browser does not have."""
    v = _video()
    assert SC.resolve_recording_url(
        v, canvas_base="https://canvas.edu", course_id=9
    ) == "https://canvas.edu/courses/9/modules/items/77"


@pytest.mark.parametrize("source", ["folder", "page", "assignment", "announcement"])
def test_a_non_module_recording_never_falls_back_to_canvas(source):
    """``module_item_id`` on a folder-expanded recording belongs to whichever
    module item's launch enumerated the folder. Using it would point every
    recording in the course at the SAME lecture, silently."""
    v = _video(source=source)
    assert SC.resolve_recording_url(
        v, canvas_base="https://canvas.edu", course_id=9) is None


def test_no_address_is_reported_as_none_not_as_a_broken_url():
    assert SC.resolve_recording_url(_video(module_item_id=0)) is None
    assert SC.viewer_url("cbs.cloud.panopto.eu", "abc") is None, \
        "a host with no scheme is not a URL a browser can open"
    assert SC.canvas_module_item_url("https://canvas.edu", 9, 0) is None


def test_discovery_captures_the_host_from_a_link_or_a_launch():
    from panopto.auth import extract_panopto_host
    assert extract_panopto_host(
        "https://canvas.edu/courses/1/external_tools/retrieve"
        "?url=https%3A%2F%2Fvideo.uni.edu%2FPanopto%2FLTI%2FLTI.aspx"
    ) == "https://video.uni.edu", (
        "the host must be the HOSTNAME, not everything up to /Panopto/")
    assert extract_panopto_host("https://example.com/files/thing.pdf") is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. The contract, the UI keys, and the presets
# ═══════════════════════════════════════════════════════════════════════════

def test_the_shortcut_output_is_off_by_default():
    """It did not exist before, so every stored contract and every legacy folder
    answers False. A True default would start writing a file beside every
    recording the app has ever synced, on the first run after an update."""
    assert S.PANOPTO_DEFAULTS["output_url"] is False


def test_a_legacy_contract_composes_without_the_shortcut():
    # Every legacy key is named: compose_settings fills ABSENT keys from
    # PANOPTO_DEFAULTS (mp3/txt/srt are on there), so a partial dict would
    # measure the defaults rather than the migration.
    legacy = {"output_mp4": False, "output_mp3": True, "output_txt": True,
              "output_srt": False, "layout": "match"}
    composed = S.compose_settings(legacy)
    assert composed["output_url"] is False
    assert S.active_outputs(composed) == ["mp3", "txt"]


def test_the_shortcut_comes_first_in_the_display_order():
    """One order, reaching the user as the badge order in Review and Confirm."""
    every = {k: True for k in S._OUTPUT_KEYS}
    assert S.active_outputs(every) == ["url", "mp4", "mp3", "txt", "srt"]
    assert SP.wanted_kinds(every) == ["url", "mp4", "mp3", "txt", "srt"]
    assert SP._SUPPORTED_KINDS[0] == SC.SHORTCUT_KIND


def test_a_shortcut_only_contract_enables_the_panopto_pass():
    """Everything downstream gates on ``is_enabled``; a False here would make
    the whole feature a no-op with the toggle visibly on."""
    c = S.make_contract(url=True, mp4=False, mp3=False, txt=False, srt=False,
                        layout="match")
    assert S.is_enabled(c) is True
    assert S.compose_settings(c)["enabled"] is True


def test_the_ui_state_reader_covers_every_output():
    state = {f"persistent_{ui}": True for ui in S._UI_OUTPUT_KEYS.values()}
    state["persistent_pan_layout"] = "separate"
    c = S.contract_from_ui_state(state)
    assert all(c[k] is True for k in S._OUTPUT_KEYS)
    assert c["layout"] == "separate"
    assert S.contract_from_ui_state({})["output_url"] is False


def test_the_ui_state_reader_survives_a_missing_or_odd_state():
    assert S.contract_from_ui_state(None)["layout"] == "match"
    assert S.contract_from_ui_state(
        {"persistent_pan_layout": "sideways"})["layout"] == "match"


def test_the_card_the_registry_and_the_badges_name_the_same_keys():
    """Three lists, one set of toggles. A key in the card but not the registry
    is a toggle nothing ever resets; a key in the contract but not the badge map
    is a selection the confirm screen never shows."""
    from core.state_registry import PANOPTO_OUTPUT_KEYS
    from ui.download_settings import PANOPTO_OUTPUT_DEFS

    card = [k for k, *_ in PANOPTO_OUTPUT_DEFS]
    assert card == PANOPTO_OUTPUT_KEYS
    assert card == list(S._UI_OUTPUT_KEYS.values())
    badges = S.contract_to_ui_keys(S.PANOPTO_DEFAULTS)
    assert set(card) | {"pan_layout"} == set(badges)


def test_every_preset_names_every_panopto_toggle():
    """A preset that omits a toggle leaves whatever the PREVIOUS preset set -
    so applying 'Slides only' after 'Everything' would silently keep an output
    the user just switched away from."""
    from core.preset_manager import PresetManager
    from core.state_registry import PANOPTO_OUTPUT_KEYS
    from ui.quick_download import _QUICK_PRESETS

    for p in PresetManager._BUILTIN_PRESETS:
        missing = [k for k in PANOPTO_OUTPUT_KEYS if k not in p['settings']]
        assert not missing, f"{p['preset_id']} omits {missing}"
    for p in _QUICK_PRESETS:
        missing = [k for k in PANOPTO_OUTPUT_KEYS if k not in p['settings']]
        assert not missing, f"{p['id']} omits {missing}"
    assert set(PANOPTO_OUTPUT_KEYS) <= set(PresetManager.SETTINGS_KEYS)


def test_a_folder_with_only_a_shortcut_infers_the_shortcut_contract():
    """The recovery path for a folder whose contract seed write failed. Without
    'url' here such a folder reads as "Panopto was never configured" and the
    pass is skipped for ever."""
    c = S.infer_contract_from_manifest({"v1": {"url": "Module 1/L.url"}})
    assert c["output_url"] is True
    assert S.is_enabled(c) is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. Classification: the analyzer must look where the runner writes
# ═══════════════════════════════════════════════════════════════════════════

class _CM:
    api_url = "https://canvas.edu"
    api_key = "tok"

    @staticmethod
    def _sanitize_filename(name):
        return str(name).replace("/", "-").strip()


def _classify(tmp_path, settings, manifest=None, video=None):
    return SP.classify_videos(
        _CM(), [video or _video()], tmp_path, "flat", settings,
        manifest or {},
    )[0]


SHORTCUT_ONLY = {"output_url": True, "layout": "match"}


def test_a_missing_shortcut_is_new_work(tmp_path):
    c = _classify(tmp_path, SHORTCUT_ONLY)
    assert c.state == "new"
    assert c.download_kinds == ["url"]


def test_a_shortcut_on_disk_is_up_to_date(tmp_path):
    SH.write_shortcut(tmp_path / ("Lecture 3" + SC.kind_extension("url")),
                      VIEWER, source=SH.SOURCE_PANOPTO)
    c = _classify(tmp_path, SHORTCUT_ONLY)
    assert c.state == "uptodate"
    assert c.download_kinds == []


def test_a_deleted_shortcut_is_a_restore_not_a_new_file(tmp_path):
    """It was produced before and the user removed it, so it belongs in the
    default-UNCHECKED 'Deleted Locally' bucket."""
    c = _classify(tmp_path, SHORTCUT_ONLY,
                  manifest={"abc-123": {"url": "Lecture 3.url"}})
    assert c.state == "restore"
    assert c.deleted_kinds == ["url"]


def test_a_windows_shortcut_is_adopted_on_macos(tmp_path, monkeypatch):
    """A folder synced on Windows holds .url files. A Mac that only looked for
    .webloc would report every link missing and write a second copy of each."""
    SH.write_shortcut(tmp_path / "Lecture 3.url", VIEWER, source=SH.SOURCE_PANOPTO)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    c = _classify(tmp_path, SHORTCUT_ONLY)
    assert c.state == "uptodate", "the existing .url was not adopted"


def test_the_canvas_link_of_the_same_name_does_not_satisfy_the_output(tmp_path):
    """THE defect the first real run exposed. ``core.canvas_logic._create_link``
    writes ``<lecture title>.url`` for the Panopto module ITEM, so in the match
    layout the Panopto pass found its own destination occupied and reported
    "nothing to do" - measured on course 43660: 36 recordings, 34 identically
    named Canvas links, 0 shortcuts written, 0 manifest rows, and a completion
    screen that said nothing at all."""
    canvas_link = tmp_path / "Lecture 3.url"
    SH.write_shortcut(canvas_link, "https://canvas.edu/courses/9/modules/items/77")

    c = _classify(tmp_path, SHORTCUT_ONLY)

    assert c.state == "new", "a Canvas link was mistaken for the Shortcut output"
    assert c.download_kinds == ["url"]
    assert Path(c.paths["url"]).name == "Lecture 3 (Panopto).url", (
        "the analyzer must expect the link at the same disambiguated name the "
        "runner writes it to")


def test_a_shortcut_adds_no_bytes_to_the_confirm_screen(tmp_path):
    """Nothing crosses the network, so it must not inflate the download total -
    and it must not trigger a duration probe to find that out."""
    c = _classify(tmp_path, SHORTCUT_ONLY)
    assert c.download_size == 0
    assert SP.videos_needing_duration([c]) == []


# ═══════════════════════════════════════════════════════════════════════════
# 6. The runner: no session, written first, recorded as it lands
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def no_engine(monkeypatch):
    """Transcription off, hermetically - `whisper_available` imports the engine."""
    monkeypatch.setattr(R.pmodels, "whisper_available", lambda: False)
    monkeypatch.setattr(R.pmodels, "is_installed", lambda *_a, **_k: False)


@pytest.fixture
def launches(monkeypatch):
    """Count LTI handshakes and never perform one."""
    calls = []

    def _fake(url, token, **kw):
        calls.append(url)
        return (None, None, None, None, None)

    monkeypatch.setattr(R, "lti_launch", _fake)
    return calls


def _run(tmp_path, contract, video=None, **target_extra):
    course = types.SimpleNamespace(id=9, name="Course A")
    recorded = []

    class _SM:
        def record_panopto_file(self, vid, kind, rel, title):
            recorded.append((vid, kind, rel))

    events = []
    target = {
        "course": course,
        "course_root": tmp_path,
        "download_mode": "flat",
        "videos": [video or _video(panopto_host="https://cbs.cloud.panopto.eu",
                                   launch_url="https://canvas.edu/sessionless_launch?x=1")],
        "record_fn": R.make_recorder(_SM(), tmp_path),
        "settings": contract,
    }
    target.update(target_extra)
    summary = R.run_panopto_batch(
        _CM(), [target], settings=S.compose_settings(contract),
        progress=lambda kind, **kw: events.append((kind, kw)),
        is_cancelled=lambda: False,
    )
    return summary, events, recorded


def test_a_shortcut_only_run_performs_no_lti_handshake(tmp_path, no_engine, launches):
    """The economy of the whole feature. It also means a course whose LTI chain
    is dead - a real, observed state - still gets its links."""
    summary, events, recorded = _run(tmp_path, S.make_contract(
        url=True, mp4=False, mp3=False, txt=False, srt=False, layout="match"))

    assert launches == [], "a Shortcut-only run authenticated for no reason"
    assert summary["shortcuts"] == 1
    assert summary["failed"] == 0
    written = tmp_path / ("Lecture 3" + SC.kind_extension("url"))
    assert SH.read_shortcut(written) == (VIEWER, SH.SOURCE_PANOPTO)
    # A set: the runner records each artifact as it lands AND once more in the
    # end-of-batch catch-all (deliberate - a cancel interrupts wherever it
    # stands, and record_panopto_file is INSERT OR REPLACE). The row is what
    # matters, not how many times it was written.
    assert set(recorded) == {("abc-123", "url", written.name)}, (
        "the shortcut reached the manifest under the wrong id, kind or path")
    assert [k for k, _ in events if k.startswith("shortcut")] == [
        "shortcut_phase", "shortcut", "shortcut_done"]


def test_the_runner_writes_beside_a_canvas_link_of_the_same_name(
        tmp_path, no_engine, launches):
    """The writer half of the collision, end to end: the Canvas link is left
    exactly as it was (the Canvas file sync owns it and tracks its content
    signature - overwriting would put the two subsystems in a rewrite loop), and
    the lecture still gets its direct link."""
    canvas_link = tmp_path / "Lecture 3.url"
    SH.write_shortcut(canvas_link, "https://canvas.edu/courses/9/modules/items/77")
    canvas_before = canvas_link.read_bytes()

    summary, _events, recorded = _run(tmp_path, S.make_contract(
        url=True, mp4=False, mp3=False, txt=False, srt=False, layout="match"))

    ours = tmp_path / "Lecture 3 (Panopto).url"
    assert summary["shortcuts"] == 1
    assert SH.read_shortcut(ours) == (VIEWER, SH.SOURCE_PANOPTO)
    assert canvas_link.read_bytes() == canvas_before, "the Canvas link was touched"
    assert set(recorded) == {("abc-123", "url", ours.name)}


def test_a_second_run_adopts_the_disambiguated_link(tmp_path, no_engine, launches):
    """And does not add a third file. The resolver has to look PAST the foreign
    name to find our own, or every run would write the next name along."""
    SH.write_shortcut(tmp_path / "Lecture 3.url", "https://canvas.edu/x")
    contract = S.make_contract(url=True, mp4=False, mp3=False, txt=False,
                               srt=False, layout="match")
    _run(tmp_path, contract)
    summary2, _e, _r = _run(tmp_path, contract)

    assert summary2["shortcuts"] == 0 and summary2["skipped"] == 1
    assert sorted(p.name for p in tmp_path.glob("*.url")) == [
        "Lecture 3 (Panopto).url", "Lecture 3.url"]


def test_wanting_media_still_authenticates(tmp_path, no_engine, launches):
    """The gate must be narrow. An mp3 already on disk still means this target
    fetches media in general, and the session is resolved per COURSE."""
    (tmp_path / "Lecture 3.mp3").write_bytes(b"audio")
    _run(tmp_path, S.make_contract(url=True, mp4=False, mp3=True, txt=False,
                                   srt=False, layout="match"))
    assert launches, "a target wanting audio skipped its session bootstrap"


def test_the_link_is_written_before_and_independently_of_the_download(
        tmp_path, no_engine, launches):
    """The reason the phase runs first: a run whose session never authenticates
    (here, every launch fails) must still leave a working link behind."""
    summary, events, _rec = _run(tmp_path, S.make_contract(
        url=True, mp4=True, mp3=False, txt=False, srt=False, layout="match"))

    kinds = [k for k, _ in events]
    assert kinds.index("shortcut_phase") < kinds.index("download_phase")
    assert (tmp_path / ("Lecture 3" + SC.kind_extension("url"))).exists()
    assert summary["shortcuts"] == 1
    assert summary["downloaded"] == 0, "the download was expected to fail here"


def test_a_recording_with_no_address_is_reported_not_skipped_silently(
        tmp_path, no_engine, launches):
    """"Nothing happened" is the one outcome a user cannot act on."""
    orphan = _video(source="page", module_item_id=0, panopto_host="")
    summary, events, _rec = _run(tmp_path, S.make_contract(
        url=True, mp4=False, mp3=False, txt=False, srt=False, layout="match"),
        video=orphan)

    assert summary["shortcuts"] == 0
    assert summary["failed"] == 1
    errors = [kw["error"] for k, kw in events if k == "error"]
    assert len(errors) == 1 and "Link" in errors[0].error_type
    assert not list(tmp_path.glob("*.url")) and not list(tmp_path.glob("*.webloc"))


def test_an_existing_link_is_not_rewritten(tmp_path, no_engine, launches):
    """A no-op run must be a no-op on disk: rewriting would touch the mtime of
    every link in every course on every sync."""
    p = tmp_path / ("Lecture 3" + SC.kind_extension("url"))
    SH.write_shortcut(p, VIEWER, source=SH.SOURCE_PANOPTO)
    before = p.stat().st_mtime_ns

    summary, events, _rec = _run(tmp_path, S.make_contract(
        url=True, mp4=False, mp3=False, txt=False, srt=False, layout="match"))

    assert summary["shortcuts"] == 0 and summary["skipped"] == 1
    assert p.stat().st_mtime_ns == before
    assert "shortcut_phase" not in [k for k, _ in events]


def test_review_can_narrow_a_recording_to_the_shortcut_alone(
        tmp_path, no_engine, launches):
    """Sync mode passes per-recording kinds from Review. Selecting only the
    restore of a deleted link must not drag the video down with it - nor spend
    a handshake resolving one."""
    summary, _events, _rec = _run(
        tmp_path,
        S.make_contract(url=True, mp4=True, mp3=False, txt=False, srt=False,
                        layout="match"),
        per_video_kinds={"abc-123": {"url"}},
    )
    assert launches == []
    assert summary["shortcuts"] == 1
    assert not list(tmp_path.glob("*.mp4"))


def test_review_can_also_exclude_the_shortcut(tmp_path, no_engine, launches):
    """The other direction, and the one that writes a file nobody asked for.
    A user restoring only a deleted MP3 must not have a link appear beside it."""
    summary, _events, _rec = _run(
        tmp_path,
        S.make_contract(url=True, mp4=False, mp3=True, txt=False, srt=False,
                        layout="match"),
        per_video_kinds={"abc-123": {"mp3"}},
    )
    assert summary["shortcuts"] == 0
    assert not list(tmp_path.glob("*.url")) and not list(tmp_path.glob("*.webloc"))


def test_a_recording_the_review_map_does_not_cover_still_gets_its_session(
        tmp_path, no_engine, launches):
    """An incomplete per-recording map falls back to the target's own contract,
    so it must count as media wanted. Reading the map as authoritative would
    leave a genuine download with no Panopto session and fail the whole
    recording - the expensive direction of this gate."""
    _run(tmp_path,
         S.make_contract(url=True, mp4=False, mp3=True, txt=False, srt=False,
                         layout="match"),
         per_video_kinds={"some-other-recording": {"url"}})
    assert launches, "an uncovered recording was assumed to need no media"


# ═══════════════════════════════════════════════════════════════════════════
# 7. macOS: the same feature, the other file format
# ═══════════════════════════════════════════════════════════════════════════
#
# These run on any host by making ``platform.system()`` answer "Darwin", which
# is the ONLY thing the shortcut code branches on - the extension, and therefore
# the file format, the search order and the URL compiler's glob. What that
# cannot prove is Finder itself opening the file; for that, see the plist-shape
# assertions above and the fact that ``core.canvas_logic._create_link`` has
# shipped the identical ``plistlib.dumps({'URL': ...})`` form on macOS for as
# long as external links have existed.

@pytest.fixture
def macos(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")


def _canvas_webloc(path, url):
    """Byte-for-byte what canvas_logic._create_link writes on macOS."""
    Path(path).write_bytes(plistlib.dumps({"URL": url}, fmt=plistlib.FMT_XML))


def test_the_runner_writes_a_webloc_on_macos(tmp_path, macos, no_engine, launches):
    summary, _events, recorded = _run(tmp_path, S.make_contract(
        url=True, mp4=False, mp3=False, txt=False, srt=False, layout="match"))

    written = tmp_path / "Lecture 3.webloc"
    assert summary["shortcuts"] == 1 and written.exists()
    with open(written, "rb") as f:
        assert plistlib.load(f)["URL"] == VIEWER
    assert set(recorded) == {("abc-123", "url", "Lecture 3.webloc")}, (
        "a .webloc must be recorded under kind 'url', not 'webloc'")
    assert not list(tmp_path.glob("*.url"))


def test_the_canvas_link_collision_happens_on_macos_too(tmp_path, macos, no_engine,
                                                        launches):
    """_create_link writes ``<lecture>.webloc`` for the same module item, so the
    match layout collides exactly as it does on Windows - only the suffix
    differs, which is precisely why the rule lives in one resolver."""
    canvas = tmp_path / "Lecture 3.webloc"
    _canvas_webloc(canvas, "https://canvas.edu/courses/9/modules/items/77")
    before = canvas.read_bytes()

    summary, _e, _r = _run(tmp_path, S.make_contract(
        url=True, mp4=False, mp3=False, txt=False, srt=False, layout="match"))

    ours = tmp_path / "Lecture 3 (Panopto).webloc"
    assert summary["shortcuts"] == 1
    assert SH.read_shortcut(ours) == (VIEWER, SH.SOURCE_PANOPTO)
    assert canvas.read_bytes() == before, "the Canvas link was touched"


def test_the_url_compiler_spares_a_produced_webloc(tmp_path, macos):
    """converters/url.py globs ``*.webloc`` on macOS, so the marker has to be
    read out of the PLIST there - a check that only understood the INI form
    would compile every Mac user's lecture links away and delete them."""
    from converters.url import compile_urls_to_txt

    _canvas_webloc(tmp_path / "Reading list.webloc", "https://example.com/reading")
    produced = tmp_path / "Lecture 3.webloc"
    SH.write_shortcut(produced, VIEWER, source=SH.SOURCE_PANOPTO)

    out, to_delete = compile_urls_to_txt(tmp_path, "Course")

    assert [p.name for p in to_delete] == ["Reading list.webloc"]
    assert VIEWER not in out.read_text(encoding="utf-8")
    assert produced.exists()


def test_a_folder_synced_on_windows_is_adopted_on_a_mac(tmp_path, macos, no_engine,
                                                        launches):
    """The migration case, end to end: the same course folder opened on the
    other platform must not grow a second link beside every recording."""
    SH.write_shortcut(tmp_path / "Lecture 3.url", VIEWER, source=SH.SOURCE_PANOPTO)

    summary, _e, _r = _run(tmp_path, S.make_contract(
        url=True, mp4=False, mp3=False, txt=False, srt=False, layout="match"))

    assert summary["shortcuts"] == 0 and summary["skipped"] == 1
    assert not list(tmp_path.glob("*.webloc"))
